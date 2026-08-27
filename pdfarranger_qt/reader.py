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
the document the thumbnails render from. Pointing the reader at that document
would show the original file: right pages, wrong order, no rotations.
And it belongs to the render thread, so sharing it is a data race besides.

``SearchIndex`` already takes the same route, so the machinery is proven.
"""

import logging
from typing import List, Optional

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtPdf import QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfPageSelector
from PySide6.QtWidgets import (
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .canvas import ZOOM_LIMITS, ZOOM_STEP, PageCanvas
from .export import get_in_memory_pdf
from .i18n import gettext_ as _
from .outline import Outline
from .render import MemoryDocument


class ReaderView(QWidget):
    """A `PageCanvas` with an outline sidebar.

    Was a `QPdfView`, which did continuous scroll, the zoom modes, navigation
    and search highlighting -- and nothing else. Text selection, link following
    and facing pages are not exposed by it at all (D16), and neither is any
    control over what it renders or caches, so phase 7 replaced it with a view
    of our own. The engine is unchanged (D18): this swapped the widget, not the
    renderer.

    Still deliberately thin. The canvas owns the geometry and the painting; this
    owns the outline, the page selector and the document, and is what the window
    talks to.
    """

    #: Emitted when the visible page changes, so the window can show it.
    page_changed = Signal(int)
    #: Text was selected or deselected, so Edit > Copy can follow it.
    selection_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document: Optional[MemoryDocument] = None

        self.canvas = PageCanvas(self)
        self.canvas.zoom_to_width()

        # The reader's own search model, over the reader's own document.
        # SearchIndex builds a separate in-memory copy for the grid; pointing
        # the canvas at that one would highlight using another document's page
        # geometry. Same page list, so the row numbers still line up.
        self.search_model = QPdfSearchModel(self)
        self.canvas.set_search_model(self.search_model)

        # Ours, not QPdfBookmarkModel: that reads whatever document the reader
        # is showing and cannot be edited (D20).
        self.bookmarks = OutlineModel(self)
        #: Given a page uid, where that page is *now*. Set by the window, which
        #: is the only thing that knows the page list. Without it a bookmark
        #: cannot navigate, because it names a page rather than a position.
        self.page_of_uid = None
        self.outline = QTreeView(self)
        self.outline.setModel(self.bookmarks)
        self.outline.setHeaderHidden(True)
        self.outline.setEditTriggers(QTreeView.NoEditTriggers)
        self.outline.activated.connect(self._go_to_bookmark)
        self.outline.clicked.connect(self._go_to_bookmark)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.addWidget(self.outline)
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 780])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.canvas.current_page_changed.connect(self.page_changed)
        self.canvas.selection_changed.connect(self.selection_changed)
        self.canvas.external_link_activated.connect(self._open_external)
        # No event filter: the page keys and ctrl+wheel are the canvas's own
        # handlers now. They had to be filtered in from outside while the view
        # was QPdfView, which is a scroll area and nothing more.

        # Qt's own page box: shows the current page, accepts a typed one, and
        # understands page *labels*, so a book numbered i, ii, iii, 1, 2 reads
        # the way it is printed rather than by index.
        self.page_selector = QPdfPageSelector()
        self.page_selector.currentPageChanged.connect(self._selector_moved)
        self._syncing = False
        self.page_changed.connect(self._sync_selector)

    # -- document ----------------------------------------------------------

    def load(self, pages, files, source_names=None, source=None) -> bool:
        """Render ``pages`` to an in-memory PDF and show it (D15).

        Returns False if the export or the load failed, leaving whatever was
        showing in place rather than blanking the view.

        ``source`` is the ``(copyname, password)`` of a file the page list is a
        1:1 view of, from ``DocumentSet.source_if_unmodified``, or None. When
        given, that file is opened directly and the export is skipped: on a
        1590 page book the export costs 3.6 s and peaks at 1.7 GB against a
        63 ms parse, for a document that is byte-for-byte what is already on
        disk. See PORTING-NOTES.md section 6.
        """
        if source is not None and self._load_source(*source):
            return True
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
        self._show(document, data)
        return True

    def _load_source(self, copyname: str, password: str) -> bool:
        """Open a source file directly, skipping the export. False to fall back.

        Deliberately silent on failure: the caller retries through the export,
        which is the path that has always worked, so a source that will not open
        costs a slow read mode rather than a broken one.
        """
        try:
            document = MemoryDocument.from_file(copyname, password)
        except Exception:  # noqa: BLE001 - falling back is the whole point
            logging.getLogger(__name__).exception("could not open %s", copyname)
            return False
        if not document.ok:
            document.close()
            return False
        # The fast path has no bytes in hand: the render thread reads the same
        # file instead, which is what makes the path fast in the first place.
        try:
            with open(copyname, "rb") as handle:
                data = handle.read()
        except OSError:
            data = None
        self._show(document, data)
        return True

    def _show(self, document, data=None):
        """Bind a document to every model, then drop the previous one.

        ``data`` is the document as bytes, handed to the canvas for its render
        thread to parse separately: QPdfDocument is not thread-safe and this one
        belongs to the GUI thread, where the search, bookmark and page-selector
        models are bound to it.
        """
        previous = self._document
        self._document = document
        self.canvas.set_document(document.document, data)
        self.search_model.setDocument(document.document)
        self.page_selector.setDocument(document.document)
        self.outline.expandToDepth(1)
        # Only after the view has taken the new one: closing a document the
        # canvas still holds a reference to crashes PDFium on its next paint.
        if previous is not None:
            previous.close()

    def shutdown(self):
        """Stop the canvas's render thread. Qt aborts if one outlives its widget."""
        self.canvas.shutdown()

    def clear(self):
        """Drop the document. Safe to call more than once.

        The reference goes first. setDocument(None) makes the navigator emit
        currentPageChanged, and anything reacting to that would otherwise reach
        a MemoryDocument whose QPdfDocument Python has already collected --
        "Internal C++ object (QPdfDocument) already deleted".
        """
        document, self._document = self._document, None
        self.canvas.set_document(None)
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
            # Kept from when the view was QPdfView, which took ownership of the
            # QPdfDocument it was given and destroyed it with itself, leaving
            # this MemoryDocument holding a wrapper whose C++ side had gone.
            # PageCanvas only borrows the document, so this should no longer be
            # reachable -- but it costs one branch during teardown, and the
            # failure it guards against is a hard crash rather than an
            # exception.
            self._document = None
            return 0

    def set_outline(self, outline):
        """Show the document's outline. Called whenever it changes."""
        self.bookmarks.set_outline(outline)
        self.outline.expandToDepth(1)

    def has_outline(self) -> bool:
        return self.bookmarks.rowCount(QModelIndex()) > 0

    # -- navigation --------------------------------------------------------

    def current_page(self) -> int:
        return max(0, self.canvas.current_page())

    def go_to_page(self, page: int):
        self.canvas.go_to_page(page)

    def next_page(self):
        self.canvas.next_page()

    def previous_page(self):
        self.canvas.previous_page()

    def first_page(self):
        self.canvas.first_page()

    def last_page(self):
        self.canvas.last_page()

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

    #: Schemes a link in a PDF may hand to the desktop. Deliberately short.
    #:
    #: A PDF is an untrusted document that arrived from somewhere, and its links
    #: are whatever its author wrote. Handing an arbitrary URL to
    #: QDesktopServices lets the document choose what the operating system opens
    #: -- `file://` walks the local disk, and the schemes registered on a given
    #: machine are not knowable from here. So this is an allow list rather than
    #: a deny list: the cost of omitting a scheme is a link that does nothing
    #: and says so, which is a great deal cheaper than the reverse.
    SAFE_SCHEMES = frozenset({"http", "https", "mailto", "ftp", "ftps"})

    #: A link was refused because of its scheme, so the window can say so.
    link_refused = Signal(str)

    def _open_external(self, url):
        """Hand a link to the desktop, if its scheme is one we allow."""
        scheme = (url.scheme() or "").lower()
        if scheme not in self.SAFE_SCHEMES:
            logging.getLogger(__name__).info("refused link with scheme %r", scheme)
            self.link_refused.emit(url.toString())
            return
        QDesktopServices.openUrl(url)

    def _go_to_bookmark(self, index: QModelIndex):
        """Follow a bookmark to its page, if it still has one.

        A dangling entry does nothing rather than jumping somewhere arbitrary --
        it is marked in the tree, so the silence is explained rather than
        mysterious.
        """
        item = self.bookmarks.bookmark(index)
        if item is None or item.uid is None or self.page_of_uid is None:
            return
        page = self.page_of_uid(item.uid)
        if page is not None:
            self.go_to_page(int(page))

    # -- zoom --------------------------------------------------------------

    def zoom(self) -> float:
        return self.canvas.zoom()

    def set_zoom(self, factor: float):
        low, high = ZOOM_LIMITS
        self.canvas.set_zoom(max(low, min(factor, high)))

    def zoom_in(self):
        self.set_zoom(self.zoom() * ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom() / ZOOM_STEP)

    def facing(self) -> bool:
        return self.canvas.facing()

    def set_facing(self, on: bool):
        """Show two pages side by side, the way a book falls open.

        The one thing `QPdfView.PageMode` had no setting for at all (see section
        6), so it arrives with our own view rather than as a wiring change.
        """
        self.canvas.set_facing(on)

    def continuous(self) -> bool:
        return self.canvas.continuous()

    def set_continuous(self, on: bool):
        """Continuous scrolling, or one page at a time.

        Single page was also a workaround: `QPdfView` rendered on demand at full
        display resolution and drew nothing until that render arrived -- 48-58ms
        a page on a dense 1590-page book, so scrolling outran it and left blanks.
        The canvas will answer that properly with placeholders and prefetch
        (phase 7 step 5). The mode stays because reading one page at a time is a
        preference in its own right, and it is a setting people already have.

        The old implementation had to remember the page and put it back, because
        changing QPdfView's mode relaunched the layout and left the scrollbar
        near the top while the navigator went on reporting the old page. The
        canvas keeps its place across the change, so that dance is gone.
        """
        self.canvas.set_continuous(on)

    def fit_page(self):
        self.canvas.zoom_to_page()

    def fit_width(self):
        self.canvas.zoom_to_width()

    # -- search ------------------------------------------------------------

    def search(self, phrase: str):
        """Highlight ``phrase`` in place. The canvas draws the highlights."""
        self.search_model.setSearchString(phrase or "")

    def search_phrase(self) -> str:
        return self.search_model.searchString()

    def show_search_result(self, index: int):
        self.canvas.set_current_search_result(index)

    def matches_on_page(self, page: int) -> int:
        """How many hits are on a page. Synchronous, unlike rowCount()."""
        return len(self.search_model.resultsOnPage(page))

    # -- text selection ----------------------------------------------------

    def has_selection(self) -> bool:
        return self.canvas.has_selection()

    def copy(self) -> bool:
        """Put the selected text on the clipboard. False if nothing is selected."""
        return self.canvas.copy()

    def select_all(self):
        """Select the text of the page being read.

        The page rather than the document: Ctrl+A in the grid selects every
        page, but the reader's equivalent would be every character of a 1590
        page book, which is neither useful nor quick.
        """
        self.canvas.select_all_on(self.current_page())

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


class OutlineModel(QAbstractItemModel):
    """A tree over the document's own `Outline` (D20).

    Replaces `QPdfBookmarkModel`, which reads whatever document the reader
    happens to be showing and cannot be edited. This one is a view of the
    outline the document owns, so an edit here is an edit to what will be saved.

    A parent map is kept and rebuilt on reset. `Outline.parent_of` walks the
    tree, and Qt asks for an item's parent constantly -- on 807 Handbook entries
    that would be quadratic for no reason.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._outline = Outline()
        self._parents = {}

    def set_outline(self, outline: Outline):
        self.beginResetModel()
        self._outline = outline if outline is not None else Outline()
        self._reindex()
        self.endResetModel()

    def _reindex(self):
        self._parents = {}
        def walk(items, parent):
            for item in items:
                self._parents[id(item)] = parent
                walk(item.children, item)
        walk(self._outline.roots, None)

    def bookmark(self, index: QModelIndex):
        return index.internalPointer() if index.isValid() else None

    def index_of(self, item) -> QModelIndex:
        """Where an entry lives, so a caller can select or edit it."""
        if item is None:
            return QModelIndex()
        parent = self._parents.get(id(item))
        siblings = self._outline.roots if parent is None else parent.children
        try:
            return self.createIndex(siblings.index(item), 0, item)
        except ValueError:
            return QModelIndex()

    # -- QAbstractItemModel ------------------------------------------------

    def index(self, row, column, parent=QModelIndex()):
        if column != 0:
            return QModelIndex()
        items = (self._outline.roots if not parent.isValid()
                 else parent.internalPointer().children)
        if 0 <= row < len(items):
            return self.createIndex(row, 0, items[row])
        return QModelIndex()

    def parent(self, index=QModelIndex()):
        item = self.bookmark(index)
        if item is None:
            return QModelIndex()
        return self.index_of(self._parents.get(id(item)))

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self._outline.roots)
        return len(parent.internalPointer().children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

    def data(self, index, role=Qt.DisplayRole):
        item = self.bookmark(index)
        if item is None:
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return item.title
        if role == Qt.ForegroundRole and item.dangling:
            # Marked rather than hidden or deleted: the page it wanted has gone,
            # the title may still be worth keeping, and it can be re-homed.
            return QBrush(QColor(150, 150, 150))
        if role == Qt.ToolTipRole:
            if item.dangling:
                return _("This bookmark's page is no longer in the document")
            if item.heading:
                return _("This bookmark does not point at a page")
        return None

    def setData(self, index, value, role=Qt.EditRole):
        """Rename. The caller commits an undo entry around the whole edit."""
        item = self.bookmark(index)
        if item is None or role != Qt.EditRole:
            return False
        title = str(value)
        if title == item.title:
            return False
        item.title = title
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True
