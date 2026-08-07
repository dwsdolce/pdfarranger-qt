# Copyright (C) 2026 pdfarranger-qt contributors
#
# pdfarranger is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""The thumbnail grid.

A QListView in IconMode with a custom delegate, rather than a GtkIconView
subclass.  The delegate draws the page at the model's zoom, so a page that is
physically larger really is drawn larger -- the same convention the GTK version
used, and the reason the cells are not uniformly sized.

Reordering does *not* go through Qt's item-view drag and drop.  In IconMode that
machinery answers the question "which item did you drop onto", whereas arranging
pages is entirely about the gaps *between* items, and it renders a rectangle
around an item rather than an insertion caret.  So the grid tracks the drag
itself: press, threshold, caret, drop.  External file drops still use ordinary
Qt drag and drop, which is a separate path and works as intended.
"""

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QMouseEvent,
    QFontMetrics,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QStyle, QStyledItemDelegate

from . import clipboard
from .model import contiguous_blocks

#: Space around the page image inside its cell.
CELL_MARGIN = 10
#: Gap between the page image and its caption.
LABEL_GAP = 4
#: Extra rows rendered above and below the viewport, so a slow scroll
#: does not chase the renderer.
PREFETCH_ROWS = 12
#: Width of the insertion caret drawn while dragging.
CARET_WIDTH = 3
#: How close to the viewport edge a drag must get before it auto-scrolls.
AUTOSCROLL_MARGIN = 28


class PageDelegate(QStyledItemDelegate):
    """Draws one page: drop shadow, white sheet, thumbnail, caption."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.show_labels = True

    def _label_height(self, option) -> int:
        if not self.show_labels:
            return 0
        return QFontMetrics(option.font).height() + LABEL_GAP

    def sizeHint(self, option, index):
        page = index.data(self.model.PageRole)
        if page is None:
            return QSize(80, 100)
        w, h = self.model.thumb_size(page)
        return QSize(w + 2 * CELL_MARGIN, h + 2 * CELL_MARGIN + self._label_height(option))

    def paint(self, painter: QPainter, option, index: QModelIndex):
        page = index.data(self.model.PageRole)
        if page is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)

        selected = bool(option.state & QStyle.State_Selected)
        palette = option.palette
        if selected:
            painter.fillRect(option.rect, palette.brush(QPalette.Highlight))

        w, h = self.model.thumb_size(page)
        label_h = self._label_height(option)
        avail = QRect(
            option.rect.left() + CELL_MARGIN,
            option.rect.top() + CELL_MARGIN,
            option.rect.width() - 2 * CELL_MARGIN,
            option.rect.height() - 2 * CELL_MARGIN - label_h,
        )
        sheet = QRect(0, 0, w, h)
        sheet.moveCenter(avail.center())

        # Drop shadow, then the sheet itself.
        painter.fillRect(sheet.translated(2, 2), QColor(0, 0, 0, 40))
        painter.fillRect(sheet, QColor(255, 255, 255))

        image = index.data(self.model.ImageRole)
        if image is not None and not image.isNull():
            painter.drawImage(sheet, image)
        else:
            # Not rendered yet: a faint diagonal keeps the grid from looking
            # broken while the render thread catches up.
            painter.setPen(QPen(QColor(0, 0, 0, 25), 1))
            painter.drawLine(sheet.topLeft(), sheet.bottomRight())

        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.drawRect(sheet.adjusted(0, 0, -1, -1))

        if selected:
            painter.setPen(QPen(palette.color(QPalette.HighlightedText), 2))
            painter.drawRect(sheet.adjusted(-2, -2, 1, 1))

        if label_h:
            text_rect = QRect(
                option.rect.left() + 2,
                option.rect.bottom() - label_h,
                option.rect.width() - 4,
                label_h,
            )
            role = QPalette.HighlightedText if selected else QPalette.Text
            painter.setPen(palette.color(role))
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, str(index.row() + 1))
        painter.restore()


class PageView(QListView):
    """Thumbnail grid with rubber-band select and drag reorder."""

    #: Emitted after the selection settles, with the sorted selected rows.
    selection_changed = Signal(list)
    #: Emitted when the user asks to zoom with ctrl+wheel.
    zoom_requested = Signal(float)
    #: Emitted when files are dropped from the desktop: (paths, row or -1).
    files_dropped = Signal(list, int)
    #: Emitted when a drag finishes: (rows, index to insert before, copy).
    #: ``copy`` is true when ctrl was held at the drop, duplicating instead of moving.
    reorder_requested = Signal(list, int, bool)
    #: Emitted on double-click: toggle between zoom-to-fit and the previous zoom.
    zoom_fit_toggled = Signal()
    #: Emitted when pages are dropped from another instance: (payload, row).
    pages_dropped = Signal(str, int)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.page_model = model
        self.setModel(model)
        self.delegate = PageDelegate(model, self)
        self.setItemDelegate(self.delegate)

        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(False)
        self.setMovement(QListView.Static)  # the delegate positions items
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionRectVisible(True)
        # Reordering is handled below, not by Qt; DropOnly still lets files
        # dragged in from the desktop reach dropEvent().
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        # QAbstractScrollArea routes drag and drop through the viewport, and
        # setAcceptDrops() on the view does not propagate to it. Without this
        # the view's drop handlers are never called at all -- drops fall
        # through to the main window, which can only append at the end.
        self.viewport().setAcceptDrops(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        model.selection_provider = self.selected_rows
        model.selection_setter = self.set_selected_rows

        # Drag state.
        self._press_pos = None
        self._press_row = -1
        self._last_move_pos = None
        self._dragging = False
        self._drop_index = -1
        #: Rows carried by an escalated system drag, so a round trip out of the
        #: window and back is still a reorder.
        self._dragged_rows = []
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(40)
        self._autoscroll.timeout.connect(self._do_autoscroll)
        self._autoscroll_delta = 0

        # Coalesce scroll/resize storms into one render request.
        self._needs_layout = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(30)
        self._render_timer.timeout.connect(self._queue_visible)
        self.verticalScrollBar().valueChanged.connect(self._schedule_render)
        model.modelReset.connect(self._schedule_render)
        model.rowsInserted.connect(self._schedule_render)
        model.rowsRemoved.connect(self._schedule_render)
        model.layoutChanged.connect(self._schedule_render)
        model.dataChanged.connect(self._on_data_changed)

    # -- selection ---------------------------------------------------------

    def selected_rows(self):
        return sorted(i.row() for i in self.selectionModel().selectedIndexes())

    def set_selected_rows(self, rows):
        sel = self.selectionModel()
        n = self.page_model.rowCount()
        rows = [r for r in rows if 0 <= r < n]
        selection = QItemSelection()
        for first, last in contiguous_blocks(sorted(set(rows))):
            selection.select(self.page_model.index(first, 0), self.page_model.index(last, 0))
        sel.select(selection, QItemSelectionModel.ClearAndSelect)
        if rows:
            self.scrollTo(self.page_model.index(rows[0], 0), QAbstractItemView.EnsureVisible)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        self.selection_changed.emit(self.selected_rows())

    # -- drag reorder ------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            self._press_pos = event.position().toPoint()
            self._press_row = index.row() if index.isValid() else -1
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            pos = event.position().toPoint()
            if not self.viewport().rect().contains(pos):
                # Left the window: hand the gesture over to a real system drag
                # so the pages can land in another instance.
                self._escalate_to_system_drag()
                return
            self.viewport().setCursor(
                Qt.DragCopyCursor if event.modifiers() & Qt.ControlModifier
                else Qt.ClosedHandCursor)
            self._update_drop_target(pos)
            return
        started = (
            self._press_pos is not None
            and self._press_row >= 0
            and event.buttons() & Qt.LeftButton
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        )
        if started:
            self._begin_drag(event.position().toPoint())
            return
        # Remembered so a scroll can extend a rubber band without the pointer moving.
        self._last_move_pos = event.position().toPoint()
        super().mouseMoveEvent(event)

    def _begin_drag(self, pos):
        rows = self.selected_rows()
        if self._press_row not in rows:
            # Dragging something outside the selection drags just that page.
            self.set_selected_rows([self._press_row])
            rows = [self._press_row]
        if not rows:
            return
        self._dragging = True
        # Stop the rubber band Qt started on press; we own the gesture now.
        self.setState(QAbstractItemView.NoState)
        self.viewport().setCursor(Qt.ClosedHandCursor)
        self._update_drop_target(pos)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            # Modifiers are sampled at the *drop*, not the press: ctrl+press
            # means "toggle this item" to an extended-selection view, so
            # requiring ctrl from the start would fight the selection model.
            self._finish_drag(copy=bool(event.modifiers() & Qt.ControlModifier))
            event.accept()
            return
        self._press_pos = None
        self._press_row = -1
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._dragging and event.key() == Qt.Key_Escape:
            self._cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def _finish_drag(self, copy: bool = False):
        rows, dest = self.selected_rows(), self._drop_index
        self._cancel_drag()
        if rows and dest >= 0:
            self.reorder_requested.emit(rows, dest, copy)

    def _escalate_to_system_drag(self):
        """Convert the in-window gesture into a QDrag carrying the pages.

        The hand-rolled gesture (D9) owns reordering inside the viewport, where
        it can draw an insertion caret. Once the pointer leaves, only a real
        system drag can reach another window, so the two are chained rather than
        chosen between.

        The action is a *copy*: the source keeps its pages, matching the GTK
        version, which likewise never deletes on an external drag. Losing pages
        to a half-understood cross-process protocol is not worth the tidiness.
        """
        rows = self.selected_rows()
        pages = [self.page_model.pages[r] for r in rows if r < len(self.page_model.pages)]
        self._cancel_drag()
        if not pages:
            return

        payload = clipboard.serialize_for_drag(pages)
        mime = QMimeData()
        mime.setData(clipboard.MIME_PAGES, payload.encode("utf-8"))
        # Also offer the clipboard form, so dropping on a text target is useful
        # and a GTK instance has a second chance at understanding it.
        mime.setText(clipboard.serialize(pages))

        drag = QDrag(self)
        drag.setMimeData(mime)
        thumb = self.page_model.data(self.page_model.index(rows[0], 0),
                                     self.page_model.ImageRole)
        if thumb is not None and not thumb.isNull():
            pixmap = QPixmap.fromImage(thumb).scaledToWidth(96, Qt.SmoothTransformation)
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        # Remembered so that wandering out of the window and back in is still a
        # reorder rather than a duplication.
        self._dragged_rows = rows
        try:
            drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)
        finally:
            self._dragged_rows = []

    def _cancel_drag(self):
        self._dragging = False
        self._drop_index = -1
        self._press_pos = None
        self._press_row = -1
        self._autoscroll.stop()
        self.viewport().unsetCursor()
        self.viewport().update()

    def _update_drop_target(self, pos):
        self._drop_index = self._insertion_index(pos)
        rect = self.viewport().rect()
        if pos.y() < rect.top() + AUTOSCROLL_MARGIN:
            self._autoscroll_delta = -12
        elif pos.y() > rect.bottom() - AUTOSCROLL_MARGIN:
            self._autoscroll_delta = 12
        else:
            self._autoscroll_delta = 0
        if self._autoscroll_delta and not self._autoscroll.isActive():
            self._autoscroll.start()
        elif not self._autoscroll_delta:
            self._autoscroll.stop()
        self.viewport().update()

    def _do_autoscroll(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + self._autoscroll_delta)

    def _candidate_rows(self):
        """Rows worth measuring: the visible ones plus a little slack.

        Bounding this keeps a mouse-move on a thousand-page document cheap --
        you can only drop where you can see anyway.
        """
        first, last = self._visible_range()
        return range(max(0, first - 2), min(self.page_model.rowCount(), last + 3))

    def _insertion_index(self, pos: QPoint) -> int:
        """Index the dragged pages would be inserted before."""
        n = self.page_model.rowCount()
        if n == 0:
            return 0
        nearest, best = -1, None
        for row in self._candidate_rows():
            rect = self.visualRect(self.page_model.index(row, 0))
            if rect.isEmpty():
                continue
            centre = rect.center()
            # Weight the vertical distance so items on the pointer's own row
            # win over a horizontally closer item one row up or down.
            dist = (centre.x() - pos.x()) ** 2 + (3 * (centre.y() - pos.y())) ** 2
            if best is None or dist < best:
                nearest, best = row, dist
        if nearest < 0:
            return n
        rect = self.visualRect(self.page_model.index(nearest, 0))
        return nearest + (1 if pos.x() > rect.center().x() else 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._dragging or self._drop_index < 0:
            return
        caret = self._caret_rect(self._drop_index)
        if caret is None:
            return
        painter = QPainter(self.viewport())
        painter.fillRect(caret, self.palette().color(QPalette.Highlight))
        painter.end()

    def _caret_rect(self, index):
        n = self.page_model.rowCount()
        if n == 0:
            return None
        if index < n:
            rect = self.visualRect(self.page_model.index(index, 0))
            x = rect.left()
        else:
            rect = self.visualRect(self.page_model.index(n - 1, 0))
            x = rect.right()
        if rect.isEmpty():
            return None
        return QRect(x - CARET_WIDTH // 2, rect.top() + 2, CARET_WIDTH, rect.height() - 4)

    # -- lazy rendering ----------------------------------------------------

    def _schedule_render(self, *_args):
        self._render_timer.start()

    def _on_data_changed(self, _top_left, _bottom_right, roles=()):
        """Re-queue and re-lay-out after an edit, but not after a thumbnail arrives.

        A rotate changes both the render key and the cell's size hint. QListView
        resizes the rotated cell but leaves its neighbours at their old
        positions, so a page that grew paints over the one beside it and both
        orientations stay on screen; only a full relayout puts the row right.

        Delivery of a rendered bitmap also emits dataChanged -- with ImageRole --
        and reacting to that would loop.
        """
        if self.page_model.ImageRole in roles:
            return
        self._needs_layout = True
        self._schedule_render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_render()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_render()

    def _rows_near(self, y_values):
        """Rows hit by a grid of probes along the given viewport lines.

        Hit-testing a single point is unreliable here: cells are spaced and of
        differing heights, so whether a probe lands on an item or in a gap
        depends on the scroll offset. A miss used to pin the visible range to
        row 0, which both anchored relayouts to the top of the document and
        made the renderer prefetch from page 1 on a scrolled view.
        """
        width = self.viewport().width()
        rows = []
        for y in y_values:
            for fraction in (0.05, 0.25, 0.5, 0.75, 0.95):
                index = self.indexAt(QPoint(int(width * fraction), y))
                if index.isValid():
                    rows.append(index.row())
        return rows

    def _visible_range(self):
        n = self.page_model.rowCount()
        if n == 0:
            return 0, -1
        rect = self.viewport().rect()
        top_rows = self._rows_near([rect.top() + off for off in (2, 8, 20)])
        bottom_rows = self._rows_near([rect.bottom() - off for off in (2, 8, 20)])
        top_row = min(top_rows) if top_rows else 0
        bottom_row = max(bottom_rows) if bottom_rows else n - 1
        if bottom_row < top_row:
            top_row, bottom_row = bottom_row, top_row
        return top_row, bottom_row

    def _queue_visible(self):
        if self._needs_layout:
            # Coalesced: rotating a 500-page selection relays out once, not 500 times.
            self._needs_layout = False
            # Anchor on the top visible page rather than the scroll offset --
            # the cells just changed size, so the old pixel offset points
            # somewhere arbitrary, and doItemsLayout() resets it to zero anyway.
            anchor = self._visible_range()[0]
            self.doItemsLayout()
            if 0 <= anchor < self.page_model.rowCount():
                self.scrollTo(self.page_model.index(anchor, 0),
                              QAbstractItemView.PositionAtTop)
        if not self.page_model.rowCount():
            return
        first, last = self._visible_range()
        # Anything queued for a viewport we have already left is wasted work.
        self.page_model.renderer.cancel_pending()
        self.page_model.ensure_rendered(first - PREFETCH_ROWS, last + PREFETCH_ROWS)

    # -- input -------------------------------------------------------------

    @staticmethod
    def _accepts(mime) -> bool:
        return mime.hasUrls() or mime.hasFormat(clipboard.MIME_PAGES)

    def handle_page_drop(self, payload: str, at: int, internal: bool,
                         copy: bool = False):
        """Route a page drop: our own pages move, everyone else's are copied.

        Dragging out of the window and back in must still be a reorder. Once the
        gesture escalates to a QDrag it carries page data, so on the way back it
        is indistinguishable from a foreign drop unless the source is checked --
        and treating it as foreign silently duplicates the pages.

        ``copy`` (ctrl held) turns our own drop into a duplication. It is
        meaningless for a drop from another instance, which is always a copy.
        """
        if internal and self._dragged_rows:
            self.reorder_requested.emit(list(self._dragged_rows), at, copy)
        else:
            self.pages_dropped.emit(payload, at)

    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._accepts(event.mimeData()):
            # Show where the pages would land, same caret as an internal drag.
            self._drop_index = self._insertion_index(event.position().toPoint())
            self._dragging = True
            self.viewport().update()
            if event.source() is self:
                # Our own pages coming home: move, unless ctrl asks for a copy.
                event.setDropAction(
                    Qt.CopyAction if event.modifiers() & Qt.ControlModifier
                    else Qt.MoveAction)
                event.accept()
            else:
                # Between instances it is always a copy, so ctrl changes nothing.
                event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._cancel_drag()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        at = self._insertion_index(event.position().toPoint())
        self._cancel_drag()
        if mime.hasFormat(clipboard.MIME_PAGES):
            payload = bytes(mime.data(clipboard.MIME_PAGES)).decode("utf-8", "replace")
            self.handle_page_drop(
                payload, at, internal=event.source() is self,
                copy=bool(event.modifiers() & Qt.ControlModifier))
            event.acceptProposedAction()
            return
        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if paths:
                index = self.indexAt(event.position().toPoint())
                self.files_dropped.emit(paths, index.row() if index.isValid() else -1)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def wheelEvent(self, event):
        """Modifier-driven scrolling, matching the GTK version (see §8 of the notes)."""
        modifiers = event.modifiers()
        delta = event.angleDelta().y()
        if modifiers & Qt.ControlModifier:
            steps = delta / 120.0
            if steps:
                self.zoom_requested.emit(1.1 ** steps)
            event.accept()
            return
        if modifiers & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        if modifiers & Qt.AltModifier:
            self._scroll_one_row(up=delta > 0)
            event.accept()
            return
        super().wheelEvent(event)
        self._extend_rubber_band_after_scroll()

    def _extend_rubber_band_after_scroll(self):
        """Grow an in-progress rubber band when the view scrolls under it.

        Qt moves the band with the content but only recomputes the selection on
        the next mouse move, so scrolling with the pointer held still leaves the
        selection stale until you jiggle the mouse. Replaying a move at the last
        known position reuses Qt's own selection logic to settle it immediately.
        """
        if self.state() != QAbstractItemView.DragSelectingState:
            return
        if self._last_move_pos is None:
            return
        point = QPointF(self._last_move_pos)
        QApplication.sendEvent(self.viewport(), QMouseEvent(
            QEvent.MouseMove, point, point,
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

    def _scroll_one_row(self, up: bool):
        """Scroll by exactly one row of thumbnails."""
        first, _last = self._visible_range()
        rect = self.visualRect(self.page_model.index(first, 0))
        step = rect.height() + self.spacing() * 2 if not rect.isEmpty() else 80
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + (-step if up else step))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.zoom_fit_toggled.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
