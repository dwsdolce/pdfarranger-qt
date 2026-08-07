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

"""The document as a Qt item model, plus undo.

Undo uses the memento pattern inherited from the GTK application: a snapshot is
a shallow copy of every Page, which is cheap because a Page is a reference into
an immutable temporary file plus a handful of numbers.  Nothing here touches a
PDF, so undo depth costs almost nothing.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from .core import Dims, Page, Sides
from .render import RenderTask


@dataclass
class UndoState:
    label: str
    pages: List[Page]
    selection: List[int] = field(default_factory=list)


class UndoManager:
    """Snapshot stack. ``commit`` is called *before* a mutating action."""

    def __init__(self, model: "PageListModel"):
        self.model = model
        self.states: List[UndoState] = []
        self.current = 0

    def clear(self):
        self.states.clear()
        self.current = 0

    def snapshot(self, label: Optional[str] = None) -> UndoState:
        return UndoState(
            label,
            [p.duplicate() for p in self.model.pages],
            list(self.model.selected_rows()),
        )

    def commit(self, label: str):
        """Record the state *before* ``label`` happens.

        The label is stored on the snapshot it precedes, so "Undo Rotate" can
        name the action it is about to reverse.
        """
        self.states = self.states[: self.current]
        self.states.append(self.snapshot(label))
        self.current += 1

    @property
    def can_undo(self) -> bool:
        return self.current >= 1

    @property
    def can_redo(self) -> bool:
        return self.current + 1 < len(self.states)

    def undo_label(self) -> Optional[str]:
        return self.states[self.current - 1].label if self.can_undo else None

    def redo_label(self) -> Optional[str]:
        return self.states[self.current].label if self.can_redo else None

    def undo(self):
        if not self.can_undo:
            return
        if self.current == len(self.states):
            self.states.append(self.snapshot())
        self.current -= 1
        self.model.restore(self.states[self.current])

    def redo(self):
        if not self.can_redo:
            return
        self.current += 1
        self.model.restore(self.states[self.current])


class PageListModel(QAbstractListModel):
    """Flat list of Page objects, rendered lazily.

    The model owns the thumbnail requests rather than the view, so that a page
    edit can invalidate exactly the affected rows.
    """

    PageRole = Qt.UserRole + 1
    ImageRole = Qt.UserRole + 2
    #: Search hits on this page, as rectangles in the page's own points.
    MatchRole = Qt.UserRole + 3

    #: Emitted whenever the page list changes in a way that affects the title
    #: bar or the status bar (count, modified flag).
    contents_changed = Signal()

    def __init__(self, renderer, parent=None):
        super().__init__(parent)
        self.pages: List[Page] = []
        self.renderer = renderer
        self.undo = UndoManager(self)
        #: Rendered pixels per PDF point. Every page is drawn at the same zoom,
        #: so an A3 page really does look twice the size of an A4 one.
        self.zoom = 0.22
        #: Set by the view so undo can restore the selection.
        self.selection_provider = lambda: []
        self.selection_setter = lambda rows: None
        self._key_rows = {}
        #: {row: [QRectF]} for the current search, in page points. Empty when
        #: nothing is being searched for.
        self._matches = {}
        self.renderer.ready.connect(self._on_thumbnail_ready)

    # -- search highlighting -----------------------------------------------

    def set_matches(self, matches):
        """Set the search hits to draw, as ``{row: [QRectF in page points]}``.

        Rows outside the current page list are ignored rather than rejected: a
        search result can outlive the edit that shortened the document.
        """
        rows = set(self._matches) | set(matches or {})
        self._matches = {row: list(rects)
                         for row, rects in (matches or {}).items()
                         if 0 <= row < len(self.pages) and rects}
        for row in rows:
            if 0 <= row < len(self.pages):
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [self.MatchRole])

    def clear_matches(self):
        if self._matches:
            self.set_matches({})

    # -- Qt model interface ------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.pages)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.pages):
            return None
        page = self.pages[index.row()]
        if role == self.PageRole:
            return page
        if role == self.ImageRole:
            return self.renderer.get(page.render_key(self.thumb_width(page)))
        if role == self.MatchRole:
            return self._matches.get(index.row())
        if role == Qt.DisplayRole:
            return page.description
        if role == Qt.ToolTipRole:
            w, h = page.size_in_mm()
            return f"{page.description}\n{w:.0f} x {h:.0f} mm"
        return None

    def flags(self, index):
        # Reordering is driven by PageView, not by Qt's item-view drag and
        # drop, so no drag/drop flags are advertised here.
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # -- mutations ---------------------------------------------------------

    def set_pages(self, pages: List[Page]):
        self.beginResetModel()
        self.pages = list(pages)
        self._key_rows.clear()
        self.endResetModel()
        self.contents_changed.emit()

    def insert_pages(self, at: int, pages: List[Page], select=True):
        if not pages:
            return
        at = max(0, min(at, len(self.pages)))
        self.beginInsertRows(QModelIndex(), at, at + len(pages) - 1)
        self.pages[at:at] = pages
        self.endInsertRows()
        self._key_rows.clear()
        if select:
            self.selection_setter(list(range(at, at + len(pages))))
        self.contents_changed.emit()

    def remove_rows(self, rows: List[int]):
        """Remove arbitrary rows, coalescing them into contiguous blocks."""
        if not rows:
            return
        for first, last in reversed(contiguous_blocks(sorted(set(rows)))):
            self.beginRemoveRows(QModelIndex(), first, last)
            del self.pages[first : last + 1]
            self.endRemoveRows()
        self._key_rows.clear()
        self.contents_changed.emit()

    def move_rows(self, rows: List[int], dest: int):
        """Move rows so they land immediately before original index ``dest``."""
        rows = sorted(set(r for r in rows if 0 <= r < len(self.pages)))
        if not rows:
            return
        moving = [self.pages[r] for r in rows]
        # How many of the moved rows sit before the insertion point.
        before = sum(1 for r in rows if r < dest)
        remaining = [p for i, p in enumerate(self.pages) if i not in set(rows)]
        target = max(0, min(dest - before, len(remaining)))
        self.beginResetModel()
        self.pages = remaining[:target] + moving + remaining[target:]
        self._key_rows.clear()
        self.endResetModel()
        self.selection_setter(list(range(target, target + len(moving))))
        self.contents_changed.emit()

    def rotate(self, rows: List[int], angle: int) -> bool:
        changed = [r for r in rows
                   if 0 <= r < len(self.pages) and self.pages[r].rotate(angle)]
        if not changed:
            return False
        # One signal per run of rows rather than one per row: rotating a large
        # selection should not emit thousands of separate changes.
        for first, last in contiguous_blocks(sorted(set(changed))):
            self.dataChanged.emit(self.index(first, 0), self.index(last, 0))
        self.contents_changed.emit()
        return True

    def duplicate(self, rows: List[int]):
        rows = sorted(set(rows))
        if not rows:
            return
        copies = [self.pages[r].duplicate() for r in rows]
        self.insert_pages(rows[-1] + 1, copies)

    def insert_interleaved(self, at: int, pages: List[Page], after: bool):
        """Interleave pages one-for-one with the existing ones from ``at``.

        Pasting X Y Z into A B C D gives X A Y B Z C D before, or
        A X B Y C Z D after. This is how two single-sided scans of a
        double-sided document are recombined.
        """
        if not pages:
            return
        start = max(0, min(at, len(self.pages)))
        self.beginResetModel()
        for i, page in enumerate(pages):
            index = start + 2 * i + (1 if after else 0)
            self.pages.insert(min(index, len(self.pages)), page)
        self._key_rows.clear()
        self.endResetModel()
        self.contents_changed.emit()

    def replace_rows(self, rows: List[int], new_pages: List[Page]):
        """Swap a contiguous run of rows for a different list of pages."""
        rows = sorted(set(rows))
        if not rows:
            return
        first = rows[0]
        self.beginResetModel()
        for row in reversed(rows):
            del self.pages[row]
        self.pages[first:first] = new_pages
        self._key_rows.clear()
        self.endResetModel()
        self.selection_setter(list(range(first, first + len(new_pages))))
        self.contents_changed.emit()

    def reverse_rows(self, rows: List[int]):
        """Reverse a contiguous run of pages in place."""
        rows = sorted(set(rows))
        if len(rows) < 2:
            return
        for row, page in zip(rows, [self.pages[r] for r in reversed(rows)]):
            self.pages[row] = page
        self._reset_view(rows)

    def swap_odd_even(self, rows: List[int]):
        """Swap pages pairwise: 1<->2, 3<->4, ... A trailing odd page is left alone."""
        rows = sorted(set(rows))
        if len(rows) % 2:
            rows.pop()
        if len(rows) < 2:
            return
        for i in range(0, len(rows), 2):
            a, b = rows[i], rows[i + 1]
            self.pages[a], self.pages[b] = self.pages[b], self.pages[a]
        self._reset_view(rows)

    def _reset_view(self, rows):
        self.beginResetModel()
        self._key_rows.clear()
        self.endResetModel()
        self.selection_setter(rows)
        self.contents_changed.emit()

    def rows_matching(self, rows: List[int], attribute: str) -> List[int]:
        """Rows whose pages share an attribute with any of ``rows``.

        Backs "Select Same File" (``copyname``) and "Select Same Format"
        (``size_in_points``).
        """
        wanted = set()
        for row in rows:
            if 0 <= row < len(self.pages):
                value = getattr(self.pages[row], attribute)
                wanted.add(value() if callable(value) else value)
        matched = []
        for row, page in enumerate(self.pages):
            value = getattr(page, attribute)
            if (value() if callable(value) else value) in wanted:
                matched.append(row)
        return matched

    def set_scale(self, rows: List[int], factor) -> bool:
        """Resize pages. ``factor`` is a number, or a target size in points.

        Ported from the GTK ``pageutils.scale``. PDF requires every side to be
        between 72 and 14400 points, so the factor is clamped per page; layers
        are rescaled by the same ratio so they stay put on the page.
        """
        try:
            width, height = factor
        except TypeError:
            width = height = None
        changed = False
        for row in rows:
            if not 0 <= row < len(self.pages):
                continue
            page = self.pages[row]
            page_size = page.size.cropped(page.crop)
            if width is None:
                f = factor
            else:
                # TODO: allow changing the aspect ratio
                f = min(*(Dims(width, height) / page_size))
            f = max(f, *(Dims(72, 72) / page_size))
            f = min(f, *(Dims(14400, 14400) / page_size))
            if page.scale != f:
                changed = True
            for lp in page.layerpages:
                lp.scale = lp.scale * f / page.scale
            page.scale = f
        if changed:
            self._touch(rows)
        return changed

    def set_margins(self, rows: List[int], sides: Sides, hide: bool) -> bool:
        """Set crop or hide margins on pages."""
        changed = False
        for row in rows:
            if not 0 <= row < len(self.pages):
                continue
            page = self.pages[row]
            current = page.hide if hide else page.crop
            if current == sides:
                continue
            if hide:
                page.hide = sides
            else:
                page.crop = sides
            changed = True
        if changed:
            self._touch(rows)
        return changed

    def split_pages(self, rows: List[int], columns: int, row_count: int) -> int:
        """Cut each of ``rows`` into a grid. Returns how many pages were added."""
        from .booklet import crops_from_tiles

        vcrops = crops_from_tiles([[i + 1, 100 / columns] for i in range(columns)])
        hcrops = crops_from_tiles([[i + 1, 100 / row_count] for i in range(row_count)])
        if len(vcrops) <= 1 and len(hcrops) <= 1:
            return 0
        added = 0
        # Walk backwards so the insertion points stay valid.
        for row in sorted(set(rows), reverse=True):
            if not 0 <= row < len(self.pages):
                continue
            extra = self.pages[row].split(vcrops, hcrops)
            if extra:
                self.pages[row + 1:row + 1] = extra
                added += len(extra)
        if added:
            self.beginResetModel()
            self._key_rows.clear()
            self.endResetModel()
            self.contents_changed.emit()
        return added

    def _touch(self, rows):
        """Signal that these rows changed appearance and possibly geometry."""
        for first, last in contiguous_blocks(sorted(set(rows))):
            self.dataChanged.emit(self.index(first, 0), self.index(last, 0))
        self.contents_changed.emit()

    def restore(self, state: UndoState):
        self.beginResetModel()
        self.pages = [p.duplicate() for p in state.pages]
        self._key_rows.clear()
        self.endResetModel()
        self.selection_setter(state.selection)
        self.contents_changed.emit()

    def selected_rows(self) -> List[int]:
        return self.selection_provider()

    # -- thumbnails --------------------------------------------------------

    def thumb_width(self, page: Page) -> int:
        """Rendered width in pixels for one page at the current zoom."""
        return max(20, round(page.width_in_points() * self.zoom))

    def thumb_size(self, page: Page) -> tuple:
        size = page.size_in_points().scaled(self.zoom)
        return max(20, round(size.width)), max(20, round(size.height))

    def set_zoom(self, zoom: float):
        zoom = max(0.05, min(2.0, float(zoom)))
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.zoom = zoom
        self._key_rows.clear()
        self.renderer.cancel_pending()
        self.layoutChanged.emit()

    def ensure_rendered(self, first: int, last: int):
        """Queue thumbnails for a row range; called by the view on scroll."""
        first = max(0, first)
        last = min(len(self.pages) - 1, last)
        if last < first:
            return
        tasks = []
        for row in range(first, last + 1):
            page = self.pages[row]
            width = self.thumb_width(page)
            key = page.render_key(width)
            self._key_rows.setdefault(key, set()).add(row)
            if self.renderer.get(key) is not None:
                continue
            tasks.append(
                RenderTask(
                    key,
                    page.copyname,
                    self.doc_password(page),
                    page.npage,
                    page.angle,
                    page.crop,
                    page.hide,
                    width,
                )
            )
        if tasks:
            self.renderer.request(tasks)

    #: Overridden by the window once a DocumentSet exists.
    def doc_password(self, page: Page) -> str:
        return ""

    def _on_thumbnail_ready(self, key):
        rows = self._key_rows.get(key)
        if not rows:
            return
        for row in list(rows):
            if row >= len(self.pages):
                continue
            page = self.pages[row]
            if page.render_key(self.thumb_width(page)) == key:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ImageRole])


def contiguous_blocks(sorted_rows):
    """[1,2,3,7,8] -> [(1,3),(7,8)]"""
    blocks = []
    start = prev = None
    for row in sorted_rows:
        if start is None:
            start = prev = row
        elif row == prev + 1:
            prev = row
        else:
            blocks.append((start, prev))
            start = prev = row
    if start is not None:
        blocks.append((start, prev))
    return blocks
