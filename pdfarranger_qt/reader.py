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

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtPdf import QPdfBookmarkModel, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
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
