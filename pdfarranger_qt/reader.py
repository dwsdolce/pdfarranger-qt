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

"""Read mode: a continuous-scroll page view (D14).

Not an editor. Nothing here touches the page list -- it renders a snapshot of
it, so what you read is what you would get if you saved (D15).

Why a snapshot and not the renderer's own ``QPdfDocument``: a ``Page`` in this
port is a *reference* into an immutable temp copy plus geometry -- angle, scale,
crop, hide, layerpages. Rotation, cropping, reordering, duplication, blank
pages, imposition and layer compositing all live in the page *list*, never in
the document the thumbnails render from. Pointing a ``QPdfView`` at that
document would show the original file: right pages, wrong order, no rotations.
And it belongs to the render thread, so sharing it is a data race besides.

``SearchIndex`` already takes the same route, so the machinery is proven.
"""

import logging

from typing import List, Optional

from PySide6.QtCore import QEvent, QModelIndex, Qt, Signal
from PySide6.QtPdf import QPdfBookmarkModel, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfPageSelector, QPdfView
from PySide6.QtWidgets import (
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .export import get_in_memory_pdf
from .i18n import gettext_ as _
from .render import MemoryDocument

#: Matches the zoom steps the grid uses, so ctrl+wheel feels the same in both.
ZOOM_STEP = 1.1
ZOOM_LIMITS = (0.1, 8.0)


class ReaderView(QWidget):
    """A `QPdfView` with an outline sidebar.

    Deliberately thin: `QPdfView` already does continuous scroll, the zoom
    modes, page navigation and search highlighting. What it does *not* do, as of
    Qt 6.11, is text selection, link following or facing-page layout -- see D16.
    """

    #: Emitted when the visible page changes, so the window can show it.
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document: Optional[MemoryDocument] = None

        self.pdf_view = QPdfView(self)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        # The reader's own search model, over the reader's own document.
        # SearchIndex builds a separate in-memory copy for the grid; pointing
        # QPdfView at that one would highlight using another document's page
        # geometry. Same page list, so the row numbers still line up.
        self.search_model = QPdfSearchModel(self)
        self.pdf_view.setSearchModel(self.search_model)

        self.bookmarks = QPdfBookmarkModel(self)
        self.outline = QTreeView(self)
        self.outline.setModel(self.bookmarks)
        self.outline.setHeaderHidden(True)
        self.outline.setEditTriggers(QTreeView.NoEditTriggers)
        self.outline.activated.connect(self._go_to_bookmark)
        self.outline.clicked.connect(self._go_to_bookmark)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.addWidget(self.outline)
        self.splitter.addWidget(self.pdf_view)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 780])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.pdf_view.pageNavigator().currentPageChanged.connect(self.page_changed)
        # QPdfView only scrolls. In SinglePage mode there is nowhere to scroll
        # to, so PageUp/PageDown do nothing at all and the mode is unusable
        # without this; in MultiPage they scroll but never reach the ends.
        self.pdf_view.installEventFilter(self)
        # The wheel arrives at the viewport, not the view.
        self.pdf_view.viewport().installEventFilter(self)

        # Qt's own page box: shows the current page, accepts a typed one, and
        # understands page *labels*, so a book numbered i, ii, iii, 1, 2 reads
        # the way it is printed rather than by index.
        self.page_selector = QPdfPageSelector()
        self.page_selector.currentPageChanged.connect(self._selector_moved)
        self._syncing = False
        self.page_changed.connect(self._sync_selector)

    # -- document ----------------------------------------------------------

    def load(self, pages, files, source_names=None) -> bool:
        """Render ``pages`` to an in-memory PDF and show it (D15).

        Returns False if the export or the load failed, leaving whatever was
        showing in place rather than blanking the view.
        """
        try:
            data = get_in_memory_pdf(list(pages), files, outlines=True,
                                     source_names=source_names)
        except Exception:  # noqa: BLE001 - reported by the caller as "cannot read"
            # Logged, not silent. Swallowing this once turned a crash in the
            # export path into "the reader just returns False", and 42 tests
            # failed with an assertion that said nothing about the cause.
            logging.getLogger(__name__).exception("could not build the reader document")
            return False
        document = MemoryDocument(data)
        if not document.ok:
            document.close()
            return False

        previous = self._document
        self._document = document
        self.pdf_view.setDocument(document.document)
        self.bookmarks.setDocument(document.document)
        self.search_model.setDocument(document.document)
        self.page_selector.setDocument(document.document)
        self.outline.expandToDepth(1)
        # Only after the view has taken the new one: closing the document a
        # QPdfView is still pointing at crashes PDFium.
        if previous is not None:
            previous.close()
        return True

    def clear(self):
        """Drop the document. Safe to call more than once.

        The reference goes first. setDocument(None) makes the navigator emit
        currentPageChanged, and anything reacting to that would otherwise reach
        a MemoryDocument whose QPdfDocument Python has already collected --
        "Internal C++ object (QPdfDocument) already deleted".
        """
        document, self._document = self._document, None
        self.pdf_view.setDocument(None)
        self.bookmarks.setDocument(None)
        self.search_model.setDocument(None)
        self.page_selector.setDocument(None)
        if document is not None:
            document.close()

    def page_count(self) -> int:
        if self._document is None:
            return 0
        try:
            return self._document.page_count()
        except RuntimeError:
            # QPdfView takes ownership of the QPdfDocument it is given and
            # destroys it with itself, which leaves this MemoryDocument holding
            # a wrapper whose C++ side has gone. Only reachable during teardown.
            self._document = None
            return 0

    def has_outline(self) -> bool:
        return self.bookmarks.rowCount(QModelIndex()) > 0

    # -- navigation --------------------------------------------------------

    def current_page(self) -> int:
        return self.pdf_view.pageNavigator().currentPage()

    def go_to_page(self, page: int):
        from PySide6.QtCore import QPointF

        page = max(0, min(page, max(0, self.page_count() - 1)))
        self.pdf_view.pageNavigator().jump(page, QPointF(0, 0))

    def next_page(self):
        self.go_to_page(self.current_page() + 1)

    def previous_page(self):
        self.go_to_page(self.current_page() - 1)

    def first_page(self):
        self.go_to_page(0)

    def last_page(self):
        self.go_to_page(self.page_count() - 1)

    def _selector_moved(self, page: int):
        """The user typed or spun a page number."""
        if self._syncing or page == self.current_page():
            return
        self.go_to_page(page)

    def _sync_selector(self, page: int):
        """Follow the view, without bouncing the change straight back."""
        self._syncing = True
        try:
            self.page_selector.setCurrentPage(page)
        finally:
            self._syncing = False

    def page_label(self) -> str:
        """What the page is called, which need not be its number."""
        return self.page_selector.currentPageLabel()

    def eventFilter(self, watched, event):
        """Make the page keys navigate, not merely scroll.

        `QPdfView` is a scroll area and nothing more: PageUp and PageDown move
        the scrollbar, which happens to change page in a continuous view and
        does nothing whatever in SinglePage mode, and Home/End are unhandled in
        both. A reader is expected to have all four.
        """
        if (event.type() == QEvent.Wheel
                and watched is self.pdf_view.viewport()
                and event.modifiers() & Qt.ControlModifier):
            # QPdfView does not zoom on ctrl+wheel, and the grid does; having
            # the same gesture do nothing in one of the two views is worse than
            # not offering it at all.
            steps = event.angleDelta().y() / 120
            if steps:
                self.set_zoom(self.zoom() * (1.1 ** steps))
            return True
        if watched is not self.pdf_view or event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        if key == Qt.Key_Home:
            self.first_page()
            return True
        if key == Qt.Key_End:
            self.last_page()
            return True
        if not self.continuous():
            # One page at a time: the scrollbar cannot take us anywhere.
            if key in (Qt.Key_PageDown, Qt.Key_Down, Qt.Key_Right, Qt.Key_Space):
                self.next_page()
                return True
            if key in (Qt.Key_PageUp, Qt.Key_Up, Qt.Key_Left, Qt.Key_Backspace):
                self.previous_page()
                return True
        return False

    def _go_to_bookmark(self, index: QModelIndex):
        if not index.isValid():
            return
        page = index.data(QPdfBookmarkModel.Role.Page.value)
        if page is None:
            return
        self.go_to_page(int(page))

    # -- zoom --------------------------------------------------------------

    def zoom(self) -> float:
        return self.pdf_view.zoomFactor()

    def set_zoom(self, factor: float):
        low, high = ZOOM_LIMITS
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(max(low, min(factor, high)))

    def zoom_in(self):
        self.set_zoom(self.zoom() * ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom() / ZOOM_STEP)

    def continuous(self) -> bool:
        return self.pdf_view.pageMode() == QPdfView.PageMode.MultiPage

    def set_continuous(self, on: bool):
        """Continuous scrolling, or one page at a time.

        Single page is not only a preference. `QPdfView` renders a page on
        demand at full display resolution and draws nothing until that render
        arrives -- measured at 48-58ms a page on a dense 1590-page book, so
        roughly 17-20 pages a second. Scrolling faster than that outruns it and
        leaves blanks. Showing one page at a time renders one page at a time,
        so paging through stays sharp.
        """
        if on == self.continuous():
            return
        # Changing the mode relaunches the layout and leaves the scrollbar near
        # the top, while the navigator goes on reporting the old page -- so the
        # view shows the start of the document and nothing says otherwise.
        # Remember where we were and go back there.
        page = self.current_page()
        self.pdf_view.setPageMode(
            QPdfView.PageMode.MultiPage if on else QPdfView.PageMode.SinglePage)
        self._restore_page(page)

    def _restore_page(self, page: int):
        """Put the view back on ``page``, scrollbar included.

        `jump()` to the page the navigator already believes it is on does
        nothing, so nudge it off and back.
        """
        if page <= 0 or page >= self.page_count():
            self.go_to_page(page)
            return
        self.go_to_page(0)
        self.go_to_page(page)

    def fit_page(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def fit_width(self):
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    # -- search ------------------------------------------------------------

    def search(self, phrase: str):
        """Highlight ``phrase`` in place. `QPdfView` does the drawing."""
        self.search_model.setSearchString(phrase or "")

    def search_phrase(self) -> str:
        return self.search_model.searchString()

    def show_search_result(self, index: int):
        self.pdf_view.setCurrentSearchResultIndex(index)

    def matches_on_page(self, page: int) -> int:
        """How many hits are on a page. Synchronous, unlike rowCount()."""
        return len(self.search_model.resultsOnPage(page))

    def outline_labels(self) -> List[str]:
        """Top-level outline entries, for tests and for the status bar."""
        out = []
        for row in range(self.bookmarks.rowCount(QModelIndex())):
            out.append(self.bookmarks.index(row, 0, QModelIndex()).data())
        return out

    def describe(self) -> str:
        """One line for the status bar."""
        count = self.page_count()
        if not count:
            return _("Nothing to read.")
        return _("Page {} of {}").format(self.current_page() + 1, count)
