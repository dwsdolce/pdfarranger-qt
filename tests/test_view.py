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

"""The icon view: drag reordering, rubber band and layout."""

import unittest

from support import QT_APP, TEST_PDF, settle


class TestDragReorder(unittest.TestCase):
    """Drives the grid with real mouse events.

    Reordering is implemented in PageView rather than via Qt's item-view drag
    and drop, so it is only meaningfully covered by pushing mouse events at the
    viewport and reading back the page order.
    """

    def setUp(self):
        from PySide6.QtCore import QPointF
        from pdfarranger_qt.mainwindow import MainWindow

        self.QPointF = QPointF
        self.win = MainWindow()
        # Pin the layout: the window otherwise restores the user's saved zoom
        # and geometry, which would move the cells this test aims at.
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.view.selectAll()
        self.win.duplicate_selected()
        for i, page in enumerate(self.win.model.pages):
            page.description = str(i)
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def order(self):
        return [p.description for p in self.win.model.pages]

    def rect(self, row):
        return self.win.view.visualRect(self.win.model.index(row, 0))

    def drag(self, start, end, steps=6, ctrl=False):
        """Press at start, move to end in increments, release.

        ``ctrl`` is applied to the moves and the release only -- ctrl on the
        *press* would toggle the item's selection, which is why the real code
        samples the modifier at the drop.
        """
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QMouseEvent

        vp = self.win.view.viewport()
        held = Qt.ControlModifier if ctrl else Qt.NoModifier

        def send(kind, pos, button, buttons, modifiers=Qt.NoModifier):
            QT_APP.sendEvent(vp, QMouseEvent(kind, pos, pos, button, buttons, modifiers))

        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        for i in range(1, steps + 1):
            send(QEvent.MouseMove, start + (end - start) * i / steps,
                 Qt.NoButton, Qt.LeftButton, held)
        send(QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton, held)

    def drag_row(self, row, target_row, after=False):
        start = self.QPointF(self.rect(row).center())
        target = self.rect(target_row)
        end = (self.QPointF(target.center()) + self.QPointF(target.width(), 0) if after
               else self.QPointF(target.left() + 4, target.center().y()))
        self.win.view.set_selected_rows(sorted(set(self.win.view.selected_rows()) | {row}))
        self.drag(start, end)

    def test_drag_to_end(self):
        self.win.view.set_selected_rows([0])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.order(), ["1", "2", "3", "0"])
        self.assertTrue(self.win.modified)

    def test_drag_backwards(self):
        self.win.view.set_selected_rows([3])
        self.drag_row(3, 1)
        self.assertEqual(self.order(), ["0", "3", "1", "2"])

    def test_drag_is_undoable(self):
        self.win.view.set_selected_rows([0])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.win.act_undo.text(), "&Undo Move")
        self.win.undo()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_multi_select_drag_keeps_relative_order(self):
        self.win.view.set_selected_rows([0, 2])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.order(), ["1", "3", "0", "2"])

    def test_drop_in_place_is_not_undoable(self):
        before = len(self.win.model.undo.states)
        self.win.view.set_selected_rows([1])
        self.drag_row(1, 1)
        self.assertEqual(self.order(), ["0", "1", "2", "3"])
        self.assertEqual(len(self.win.model.undo.states), before)

    def test_dragging_an_unselected_page_drags_only_it(self):
        self.win.view.set_selected_rows([2])
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0))
        self.assertEqual(self.order(), ["1", "2", "3", "0"])

    def test_ctrl_drag_duplicates_instead_of_moving(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.assertEqual(len(self.win.model.pages), 5, "ctrl+drag should copy")
        self.assertEqual(self.order(), ["0", "1", "2", "3", "0"])
        self.assertEqual(self.win.act_undo.text(), "&Undo Copy")

    def test_ctrl_drag_in_place_still_duplicates(self):
        """A plain move onto itself is a no-op; a ctrl-drop is still a copy."""
        before = len(self.win.model.pages)
        rect = self.rect(1)
        self.win.view.set_selected_rows([1])
        self.drag(self.QPointF(rect.center()),
                  self.QPointF(rect.left() + 4, rect.center().y()), ctrl=True)
        self.assertEqual(len(self.win.model.pages), before + 1)

    def test_ctrl_drag_of_a_multi_selection_copies_all(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0, 2])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.assertEqual(self.order(), ["0", "1", "2", "3", "0", "2"])

    def test_ctrl_drag_is_undoable(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.win.undo()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_short_press_does_not_reorder(self):
        """A click must not be mistaken for a drag."""
        start = self.QPointF(self.rect(0).center())
        self.drag(start, start + self.QPointF(2, 0), steps=1)
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

class TestRubberBandScroll(unittest.TestCase):
    """Scrolling with the button held keeps extending the rubber band (§8)."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(700, 500)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.model.set_pages(self.win.model.pages * 24)  # enough to scroll
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def band(self):
        """Start a rubber band in the empty gutter and sweep it across items."""
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        viewport = self.win.view.viewport()

        def send(kind, pos, button, buttons):
            QT_APP.sendEvent(viewport, QMouseEvent(kind, QPointF(pos), QPointF(pos),
                                                 button, buttons, Qt.NoModifier))

        start = QPoint(viewport.width() - 24, 3)
        self.assertFalse(self.win.view.indexAt(start).isValid(),
                         "band must start on empty space, not an item")
        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, QPoint(400, 150), Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseMove, QPoint(100, 205), Qt.NoButton, Qt.LeftButton)
        return QPoint(100, 205)

    def scroll(self, at, notches=-2):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        event = QWheelEvent(QPointF(at), QPointF(at), QPoint(0, 0),
                            QPoint(0, notches * 120), Qt.LeftButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        QT_APP.sendEvent(self.win.view.viewport(), event)
        settle(timeout_ms=200)

    def test_band_selects_items_it_sweeps(self):
        self.band()
        self.assertEqual(self.win.view.selected_rows(), [0, 1, 2, 3])

    def test_scrolling_extends_the_band_without_a_mouse_move(self):
        """Regression: Qt moves the band with the content but only recomputes
        the selection on the next mouse move, so the selection went stale."""
        at = self.band()
        before = self.win.view.selected_rows()
        self.scroll(at)
        after = self.win.view.selected_rows()
        self.assertGreater(len(after), len(before),
                           "selection should grow as the view scrolls under the band")
        self.assertEqual(after[:len(before)], before, "earlier pages stay selected")

    def test_scroll_outside_a_band_does_not_select(self):
        from PySide6.QtCore import QPoint

        self.win.view.clearSelection()
        self.scroll(QPoint(100, 205))
        self.assertEqual(self.win.view.selected_rows(), [])

class TestLayout(unittest.TestCase):
    """Cell geometry has to follow the pages when a page changes shape."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.view.selectAll()
        self.win.duplicate_selected()
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def overlaps(self):
        """Pairs of neighbouring cells whose rects intersect."""
        bad = []
        for row in range(self.win.model.rowCount() - 1):
            a = self.win.view.visualRect(self.win.model.index(row, 0))
            b = self.win.view.visualRect(self.win.model.index(row + 1, 0))
            if a.intersects(b):
                bad.append((row, row + 1))
        return bad

    def test_rotate_relayouts_the_row(self):
        """Regression: a rotated cell grew but its neighbours stayed put.

        QListView resized the rotated item and left the rest of the row where
        it was, so the wider landscape cell painted on top of the portrait one
        beside it and both orientations showed at once.
        """
        self.assertEqual(self.overlaps(), [])
        self.win.view.set_selected_rows([1])
        self.win.rotate(90)
        settle(timeout_ms=400)
        rect = self.win.view.visualRect(self.win.model.index(1, 0))
        self.assertGreater(rect.width(), rect.height(), "cell did not become landscape")
        self.assertEqual(self.overlaps(), [])

    def test_zoom_relayouts(self):
        self.win._zoom_by(1.6)
        settle(timeout_ms=400)
        self.assertEqual(self.overlaps(), [])

    def test_visible_range_follows_the_scrollbar(self):
        """Regression: probing one corner landed between cells and reported row 0.

        That pinned relayout anchoring and thumbnail prefetching to the top of
        the document however far down the user had scrolled.
        """
        self.win.model.set_pages(self.win.model.pages * 12)
        settle(timeout_ms=400)
        bar = self.win.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        settle(timeout_ms=200)
        first, last = self.win.view._visible_range()
        self.assertGreater(first, 0)
        self.assertGreaterEqual(last, first)

    def test_rotate_keeps_the_view_where_it_was(self):
        self.win.model.set_pages(self.win.model.pages * 12)
        settle(timeout_ms=400)
        bar = self.win.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        settle(timeout_ms=200)
        before = self.win.view._visible_range()[0]
        self.win.view.set_selected_rows([before + 1])
        self.win.rotate(90)
        settle(timeout_ms=400)
        self.assertLessEqual(abs(self.win.view._visible_range()[0] - before), 1)
