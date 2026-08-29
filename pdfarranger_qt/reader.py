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
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtPdf import QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfPageSelector
from PySide6.QtWidgets import (
    QColorDialog,
    QMenu,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .canvas import ZOOM_LIMITS, ZOOM_STEP, PageCanvas
from .export import get_in_memory_pdf
from .i18n import gettext_ as _
from .outline import BOLD, ITALIC, Outline
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
    #: A bookmark command is about to change the outline; the argument labels
    #: the undo entry. The window snapshots on this, because it owns the undo
    #: stack -- the outline shares the page list's history rather than keeping
    #: one of its own (D20).
    outline_edit_begun = Signal(str)
    #: The outline changed, so the document is modified.
    outline_edited = Signal()

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
        #: The inverse: the identity of the page at a given position. Set by the
        #: window too, and needed by every command that points a bookmark at
        #: "the page I am on".
        self.uid_of_page = None
        self.outline = QTreeView(self)
        self.outline.setModel(self.bookmarks)
        self.outline.setHeaderHidden(True)
        # Renaming is a command, not a side effect of clicking twice: a click
        # in this tree navigates.
        self.outline.setEditTriggers(QTreeView.NoEditTriggers)
        self.outline.activated.connect(self._go_to_bookmark)
        self.outline.clicked.connect(self._go_to_bookmark)
        # Drag inside the tree re-nests and reorders. InternalMove, so Qt does
        # not offer to copy: there is one outline and an entry is in exactly one
        # place in it.
        self.outline.setDragEnabled(True)
        self.outline.setAcceptDrops(True)
        self.outline.setDropIndicatorShown(True)
        self.outline.setDragDropMode(QTreeView.InternalMove)
        self.outline.setDefaultDropAction(Qt.MoveAction)
        #: True while the tree is being opened to match the document, so the
        #: signals that fire do not write the same values straight back.
        self._seeding = False
        self.outline.expanded.connect(self._note_expanded)
        self.outline.collapsed.connect(self._note_collapsed)
        self.outline.setContextMenuPolicy(Qt.CustomContextMenu)
        self.outline.customContextMenuRequested.connect(self._outline_menu_at)
        self.bookmarks.about_to_edit.connect(self.outline_edit_begun)
        self.bookmarks.edited.connect(self.outline_edited)

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
            # No outlines: the sidebar reads the document's own tree (D20), not
            # this export's, so building one here is work thrown away on every
            # mode switch -- and on a 1590 page book that is not free.
            data = get_in_memory_pdf(list(pages), files,
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
        self.apply_expansion()

    def apply_expansion(self):
        """Open the tree the way the *document* says, not to a fixed depth.

        This used to be `expandToDepth(1)` regardless. That has to go, because
        what the tree shows is now what a save writes: leaving it at a fixed
        depth would mean any save -- for a rotation, for anything -- silently
        rewriting the document's collapse state to two levels deep.

        So a book that ships collapsed opens collapsed, and one that says
        nothing opens expanded, which is what `/Count` absent or positive means.
        Faithful rather than friendly, deliberately: the fallback is the silent
        rewrite in a smaller form.
        """
        self._seeding = True
        try:
            self._expand_from_model()
        finally:
            self._seeding = False

    def _expand_from_model(self, parent=QModelIndex()):
        for row in range(self.bookmarks.rowCount(parent)):
            index = self.bookmarks.index(row, 0, parent)
            item = self.bookmarks.bookmark(index)
            if item is None or not item.children:
                continue
            self.outline.setExpanded(index, not item.closed)
            self._expand_from_model(index)

    def _note_expanded(self, index):
        self._note_expansion(index, closed=False)

    def _note_collapsed(self, index):
        self._note_expansion(index, closed=True)

    def _note_expansion(self, index, closed: bool):
        """Record what the user opened or shut, without calling it an edit.

        Acrobat's behaviour, chosen deliberately (see PORTING-NOTES section 6):
        the panel's shape is written when the document is saved, but toggling it
        is not itself a modification. So reading a document and opening a
        chapter to look inside costs nothing -- no dirty flag, no undo entry --
        and if you save for any other reason the shape you left it in goes with
        it.

        Acrobat's own version of this has a trap: its Save does nothing on an
        unmodified document, so people resort to Save As or adding and deleting
        an annotation to force it. Ours writes whenever asked, so the trap does
        not carry over.
        """
        if self._seeding:
            return
        item = self.bookmarks.bookmark(index)
        if item is not None:
            item.closed = closed

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

    # -- editing bookmarks -------------------------------------------------
    #
    # Read mode, because a bookmark is a reading construct: you notice you want
    # one while reading, and the tree, its navigation and its selection are all
    # already here. Arrange mode gets none of these -- the one command that
    # would suit a grid, picking a target page out of it, is what "re-home to
    # the page I am on" already is.
    #
    # The commands mutate the outline through the model, which snapshots first
    # by way of `outline_edit_begun`. Nothing here touches undo itself: the
    # outline rides the page list's stack (D20), and that stack belongs to the
    # window.

    def current_uid(self):
        """The identity of the page being read, or None if there is not one."""
        if self.uid_of_page is None or not self.page_count():
            return None
        return self.uid_of_page(self.current_page())

    def title_here(self) -> str:
        """What a bookmark added now should be called.

        The selected text if there is any -- which is why text selection had to
        come first, and is how anyone actually titles a bookmark: select the
        heading, add. Whitespace is collapsed because a selection that crosses a
        line break arrives with the break in it, and truncated because a
        selection can be a page.

        With nothing selected, the page's own label rather than a placeholder:
        "Page iv" on a document numbered in roman is at least true, and it is
        one rename away from being right.
        """
        text = " ".join(self.canvas.selected_text().split())
        if text:
            return text[:120].strip()
        return _("Page {}").format(self.page_label() or self.current_page() + 1)

    def _target(self, index) -> QModelIndex:
        """The entry a command acts on: the one given, else the current one."""
        if index is None:
            return self.outline.currentIndex()
        return index

    def add_bookmark(self, index=None, as_child: bool = False) -> bool:
        """Add an entry pointing at the page being read."""
        uid = self.current_uid()
        if uid is None:
            return False
        added = self.bookmarks.add_bookmark(self._target(index),
                                            self.title_here(), uid,
                                            as_child=as_child,
                                            view=self.canvas.selection_view())
        if not added.isValid():
            return False
        # Select it and show it, but do not open the editor: Add and Rename are
        # separate acts with separate undo entries, and starting an edit here
        # would make one command look like two on the stack.
        self.outline.setCurrentIndex(added)
        self.outline.scrollTo(added)
        return True

    def rehome_bookmark(self, index=None) -> bool:
        """Point the selected entry at the page being read."""
        uid = self.current_uid()
        if uid is None:
            return False
        return self.bookmarks.rehome(self._target(index), uid)

    def rename_bookmark(self, index=None) -> bool:
        """Open the tree's inline editor. The model commits when it closes."""
        target = self._target(index)
        if not target.isValid():
            return False
        self.outline.setCurrentIndex(target)
        self.outline.edit(target)
        return True

    def toggle_bold(self, index=None) -> bool:
        return self._toggle_style(index, BOLD)

    def toggle_italic(self, index=None) -> bool:
        return self._toggle_style(index, ITALIC)

    def _toggle_style(self, index, bit: int) -> bool:
        target = self._target(index)
        item = self.bookmarks.bookmark(target)
        if item is None:
            return False
        return self.bookmarks.set_flags(target, item.flags ^ bit)

    def choose_colour(self, index=None) -> bool:
        """Pick a colour for the entry. Cancelling changes nothing."""
        target = self._target(index)
        item = self.bookmarks.bookmark(target)
        if item is None:
            return False
        start = (QColor.fromRgbF(*item.colour) if item.colour is not None
                 else QColor(Qt.black))
        chosen = QColorDialog.getColor(start, self, _("Bookmark Colour"))
        if not chosen.isValid():
            return False
        return self.bookmarks.set_colour(
            target, (chosen.redF(), chosen.greenF(), chosen.blueF()))

    def clear_colour(self, index=None) -> bool:
        """Back to the viewer's default, which is not the same as black."""
        return self.bookmarks.set_colour(self._target(index), None)

    def expand_all_children(self, index=None) -> bool:
        return self._expand_subtree(index, expand=True)

    def collapse_all_children(self, index=None) -> bool:
        return self._expand_subtree(index, expand=False)

    def _expand_subtree(self, index, expand: bool) -> bool:
        """Open or shut an entry and everything beneath it.

        Not an edit, for the same reason a single toggle is not: this is the
        shape of the panel, and it is written when the document is saved rather
        than marking it modified. So it goes through the same `expanded` and
        `collapsed` signals as clicking the arrows, and each entry it touches
        records itself.
        """
        target = self._target(index)
        if not target.isValid():
            return False
        stack = [target]
        while stack:
            current = stack.pop()
            self.outline.setExpanded(current, expand)
            for row in range(self.bookmarks.rowCount(current)):
                stack.append(self.bookmarks.index(row, 0, current))
        return True

    def delete_bookmark(self, index=None) -> bool:
        return self.bookmarks.delete_bookmark(self._target(index))

    def delete_bookmark_tree(self, index=None) -> bool:
        """Delete an entry and its whole subtree, rather than promoting."""
        return self.bookmarks.delete_subtree(self._target(index))

    def delete_dangling_bookmarks(self) -> int:
        return self.bookmarks.delete_dangling()

    def build_outline_menu(self, index=None) -> QMenu:
        """The outline tree's context menu.

        Split from the event handler so the tests can inspect it. Building and
        exec-ing in one place once hung the suite for five minutes: `QMenu.exec`
        is a modal event loop, and there is no way to look at a menu that is
        showing without also dismissing it.
        """
        target = self._target(index)
        item = self.bookmarks.bookmark(target)
        readable = bool(self.page_count()) and self.current_uid() is not None
        menu = QMenu(self.outline)

        add = menu.addAction(_("Add Bookmark Here"))
        add.setEnabled(readable)
        add.triggered.connect(lambda: self.add_bookmark(target))

        add_child = menu.addAction(_("Add Child Bookmark Here"))
        add_child.setEnabled(readable and item is not None)
        add_child.triggered.connect(lambda: self.add_bookmark(target, as_child=True))

        menu.addSeparator()

        rehome = menu.addAction(_("Re-home to This Page"))
        rehome.setEnabled(readable and item is not None)
        rehome.triggered.connect(lambda: self.rehome_bookmark(target))

        rename = menu.addAction(_("Rename"))
        rename.setEnabled(item is not None)
        rename.triggered.connect(lambda: self.rename_bookmark(target))

        style = menu.addMenu(_("Style"))
        style.setEnabled(item is not None)
        bold = style.addAction(_("Bold"))
        bold.setCheckable(True)
        bold.setChecked(bool(item is not None and item.flags & BOLD))
        bold.triggered.connect(lambda: self.toggle_bold(target))
        italic = style.addAction(_("Italic"))
        italic.setCheckable(True)
        italic.setChecked(bool(item is not None and item.flags & ITALIC))
        italic.triggered.connect(lambda: self.toggle_italic(target))
        style.addSeparator()
        colour = style.addAction(_("Colour…"))
        colour.triggered.connect(lambda: self.choose_colour(target))
        default = style.addAction(_("Default Colour"))
        default.setEnabled(item is not None and item.colour is not None)
        default.triggered.connect(lambda: self.clear_colour(target))

        menu.addSeparator()

        # Expanding is not an edit -- see `_note_expansion` -- so these sit
        # apart from the commands that are.
        has_children = bool(item is not None and item.children)
        expand = menu.addAction(_("Expand All Children"))
        expand.setEnabled(has_children)
        expand.triggered.connect(lambda: self.expand_all_children(target))
        collapse = menu.addAction(_("Collapse All Children"))
        collapse.setEnabled(has_children)
        collapse.triggered.connect(lambda: self.collapse_all_children(target))

        menu.addSeparator()

        delete = menu.addAction(_("Delete"))
        delete.setEnabled(item is not None)
        delete.triggered.connect(lambda: self.delete_bookmark(target))

        # Off on a leaf, where it would be Delete under another name. The two
        # differ only in what happens to the children.
        delete_tree = menu.addAction(_("Delete with Children"))
        delete_tree.setEnabled(item is not None and bool(item.children))
        delete_tree.triggered.connect(lambda: self.delete_bookmark_tree(target))

        dangling = menu.addAction(_("Delete Dangling Bookmarks"))
        dangling.setEnabled(bool(self.bookmarks.dangling_count()))
        dangling.triggered.connect(self.delete_dangling_bookmarks)

        return menu

    def _outline_menu_at(self, position):
        index = self.outline.indexAt(position)
        if index.isValid():
            # Right-clicking an entry acts on it, whatever was selected before.
            self.outline.setCurrentIndex(index)
        menu = self.build_outline_menu(index if index.isValid() else QModelIndex())
        menu.exec(self.outline.viewport().mapToGlobal(position))

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

    #: About to change the tree; the argument labels the undo entry. Emitted
    #: *before* the change, because that is when a snapshot has to be taken --
    #: undo restores the state a command started from, not the one it left.
    about_to_edit = Signal(str)
    #: The tree changed, so the document is modified and needs saving. Separate
    #: from the row signals above it, which say what moved rather than what it
    #: means.
    edited = Signal()

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

    def dangling_count(self) -> int:
        """How many entries lost their page, so a menu can offer to clear them."""
        return len(self._outline.dangling())

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
            # Drop-enabled, or nothing could be dragged out to the top level.
            return Qt.ItemIsDropEnabled
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
                | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

    # -- drag to re-nest ---------------------------------------------------

    #: Our own type rather than Qt's `x-qabstractitemmodeldatalist`, which
    #: encodes a row and column and is awkward to turn back into a tree
    #: position. This carries the path from the root -- "0/2/1" -- which
    #: survives being decoded without guessing.
    BOOKMARK_MIME = "application/x-pdfarranger-bookmark"

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return [self.BOOKMARK_MIME]

    def path_of(self, item):
        """Where an entry sits, as indices from the root. None if it is absent."""
        path = []
        while item is not None:
            parent = self._parents.get(id(item))
            siblings = self._outline.roots if parent is None else parent.children
            try:
                path.append(siblings.index(item))
            except ValueError:
                return None
            item = parent
        return tuple(reversed(path))

    def at_path(self, path):
        """The entry at a path from `path_of`, or None."""
        items, item = self._outline.roots, None
        for step in path:
            if not 0 <= step < len(items):
                return None
            item = items[step]
            items = item.children
        return item

    def mimeData(self, indexes):
        from PySide6.QtCore import QMimeData
        data = QMimeData()
        for index in indexes:
            path = self.path_of(self.bookmark(index))
            if path is not None:
                data.setData(self.BOOKMARK_MIME,
                             "/".join(str(n) for n in path).encode())
                break
        return data

    def _dragged(self, data):
        """The entry a drop is carrying, or None."""
        if not data.hasFormat(self.BOOKMARK_MIME):
            return None
        raw = bytes(data.data(self.BOOKMARK_MIME)).decode()
        try:
            return self.at_path(tuple(int(n) for n in raw.split("/") if n != ""))
        except ValueError:
            return None

    def _drop_target(self, item, row, parent):
        """``(parent bookmark, index)`` for a drop, or None if it is not allowed.

        ``row < 0`` is Qt for "onto this entry rather than between two", which
        is the nesting case and appends. A drop that would put an entry inside
        its own subtree is refused here as well as by `Outline.move`, so the
        view can grey it while the drag is still in the air.
        """
        if item is None:
            return None
        into = self.bookmark(parent)
        if into is not None and any(child is into for _d, child in item.walk()):
            return None
        siblings = self._outline.roots if into is None else into.children
        index = len(siblings) if row < 0 else row
        here = self._parents.get(id(item))
        if here is into:
            at = siblings.index(item)
            if index in (at, at + 1):
                return None          # dropped where it already is
        return into, index

    def canDropMimeData(self, data, action, row, column, parent):
        return self._drop_target(self._dragged(data), row, parent) is not None

    def dropMimeData(self, data, action, row, column, parent):
        """Re-nest or reorder by drag. One move, one undo entry.

        `beginMoveRows` and `Outline.move` both take the destination in
        *pre-move* coordinates and both do their own adjusting, so they get the
        same number -- adjusting it here as well would move the entry one place
        short every time it travelled forwards among its own siblings.
        """
        if action == Qt.IgnoreAction:
            return True
        item = self._dragged(data)
        target = self._drop_target(item, row, parent)
        if target is None:
            return False
        into, index = target
        here = self._parents.get(id(item))
        source = self.index_of(here)
        at = (self._outline.roots if here is None else here.children).index(item)

        self.about_to_edit.emit(_("Move Bookmark"))
        self.beginMoveRows(source, at, at, self.index_of(into), index)
        moved = self._outline.move(item, into, index)
        self._reindex()
        self.endMoveRows()
        self.edited.emit()
        return moved

    def data(self, index, role=Qt.DisplayRole):
        item = self.bookmark(index)
        if item is None:
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return item.title
        if role == Qt.FontRole and item.flags:
            font = QFont()
            font.setItalic(bool(item.flags & ITALIC))
            font.setBold(bool(item.flags & BOLD))
            return font
        if role == Qt.ForegroundRole:
            if item.dangling:
                # Marked rather than hidden or deleted: the page it wanted has
                # gone, the title may still be worth keeping, and it can be
                # re-homed. This wins over the entry's own colour: a state the
                # user needs to see beats a decoration they chose.
                return QBrush(QColor(150, 150, 150))
            if item.colour is not None:
                red, green, blue = item.colour
                return QBrush(QColor.fromRgbF(red, green, blue))
        if role == Qt.ToolTipRole:
            if item.dangling:
                return _("This bookmark's page is no longer in the document")
            if item.heading:
                return _("This bookmark does not point at a page")
        return None

    def setData(self, index, value, role=Qt.EditRole):
        """Rename, from the tree's own inline editor.

        One act, one undo entry: the snapshot is taken here, when the editor
        commits, rather than on every keystroke -- so undo returns to the title
        as it was before the rename began, not to a half-typed state. A rename
        that changed nothing is not an edit and takes no entry.
        """
        item = self.bookmark(index)
        if item is None or role != Qt.EditRole:
            return False
        title = str(value)
        if title == item.title:
            return False
        self.about_to_edit.emit(_("Rename Bookmark"))
        item.title = title
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.edited.emit()
        return True

    # -- editing -----------------------------------------------------------
    #
    # Every one of these does its own begin/end row calls rather than resetting
    # the model. A reset would be four lines shorter and would collapse the
    # tree and drop the selection on every edit -- on the Handbook's 807
    # entries, re-expanding to find where you were is the whole cost of the
    # command. Resets are left to the two things that really are wholesale: a
    # newly loaded document, and an undo.

    def add_bookmark(self, index, title: str, uid, as_child: bool = False,
                     view=None):
        """Insert an entry and return its index. Invalid if it could not be.

        Sibling *after* the selected entry, or nested under it as the last
        child; with nothing selected, at the end of the root. Following the
        selection rather than reading order because the tree is what the user is
        pointing at -- which is also what Acrobat's Ctrl+B does.
        """
        item = self.bookmark(index)
        if as_child and item is None:
            return QModelIndex()
        if item is None:
            parent_item, row = None, len(self._outline.roots)
        elif as_child:
            parent_item, row = item, len(item.children)
        else:
            parent_item = self._parents.get(id(item))
            siblings = (self._outline.roots if parent_item is None
                        else parent_item.children)
            row = siblings.index(item) + 1

        self.about_to_edit.emit(_("Add Child Bookmark") if as_child
                                else _("Add Bookmark"))
        self.beginInsertRows(self.index_of(parent_item), row, row)
        added = self._outline.add(title, uid, parent_item, row, view=view)
        self._reindex()
        self.endInsertRows()
        self.edited.emit()
        return self.index_of(added)

    def set_flags(self, index, flags: int) -> bool:
        """Set bold and italic. `/F`: 1 is italic, 2 is bold."""
        item = self.bookmark(index)
        if item is None or item.flags == flags:
            return False
        self.about_to_edit.emit(_("Bookmark Style"))
        item.flags = flags
        self.dataChanged.emit(index, index, [Qt.FontRole])
        self.edited.emit()
        return True

    def set_colour(self, index, colour) -> bool:
        """Set the entry's colour, or None for the viewer's default."""
        item = self.bookmark(index)
        if item is None or item.colour == colour:
            return False
        self.about_to_edit.emit(_("Bookmark Colour"))
        item.colour = colour
        self.dataChanged.emit(index, index, [Qt.ForegroundRole])
        self.edited.emit()
        return True

    def rehome(self, index, uid) -> bool:
        """Point an entry at a different page, **keeping its title**.

        The title is not touched: it may have been edited into something that
        matches nothing on the new page, and re-homing is how a dangling entry
        is repaired -- replacing the title would throw away the reason it was
        worth keeping.
        """
        item = self.bookmark(index)
        if item is None or uid is None or item.uid == uid:
            return False
        self.about_to_edit.emit(_("Re-home Bookmark"))
        item.uid = uid
        item.wanted_target = True
        # A position on the old page means nothing on the new one, and an
        # external target has just been replaced by a local one.
        item.view = None
        item.external = None
        self.dataChanged.emit(index, index,
                              [Qt.ForegroundRole, Qt.ToolTipRole])
        self.edited.emit()
        return True

    def delete_bookmark(self, index) -> bool:
        """Remove an entry; its children are promoted into its place.

        Promoted rather than deleted with it: that is what makes the Handbook's
        "1" wrapper removable in one operation without taking the 800 entries
        under it, which is the case this whole feature started from.
        """
        if self.bookmark(index) is None:
            return False
        self.about_to_edit.emit(_("Delete Bookmark"))
        self._remove_promoting(self.bookmark(index))
        self.edited.emit()
        return True

    def delete_subtree(self, index) -> bool:
        """Remove an entry and everything under it.

        The other half of Delete. Promotion is what unwraps a container node;
        this is what throws a chapter away with its sections, and doing that by
        promoting and then deleting each child would be one undo entry per
        bookmark.
        """
        item = self.bookmark(index)
        if item is None:
            return False
        parent_item = self._parents.get(id(item))
        siblings = (self._outline.roots if parent_item is None
                    else parent_item.children)
        try:
            row = siblings.index(item)
        except ValueError:
            return False
        self.about_to_edit.emit(_("Delete Bookmark and Children"))
        self.beginRemoveRows(self.index_of(parent_item), row, row)
        siblings.pop(row)
        self._reindex()
        self.endRemoveRows()
        self.edited.emit()
        return True

    def delete_dangling(self) -> int:
        """Remove every entry whose page has gone. Returns how many.

        Dangling only -- a *heading* points nowhere on purpose and must survive
        this. The two are told apart by whether the entry ever declared a
        destination, which is why `Bookmark.wanted_target` exists.

        One undo entry for the lot: it is one command, however many it removes.
        """
        lost = self._outline.dangling()
        if not lost:
            return 0
        self.about_to_edit.emit(_("Delete Dangling Bookmarks"))
        for item in lost:
            # Looked up afresh each time: removing a dangling parent promotes
            # its children, so an entry's position -- and its parent -- may have
            # moved since the list was taken. The entries themselves are all
            # still in the tree, promotion being a move rather than a delete.
            self._remove_promoting(item)
        self.edited.emit()
        return len(lost)

    def _remove_promoting(self, item):
        """The row surgery behind Delete, without the undo bracket.

        Two operations, because that is what the view has to be told: the
        children move out to stand where their parent stood, and then the parent
        goes. Doing it as a reset instead would lose the tree's expansion.
        """
        parent_item = self._parents.get(id(item))
        parent_index = self.index_of(parent_item)
        siblings = (self._outline.roots if parent_item is None
                    else parent_item.children)
        try:
            row = siblings.index(item)
        except ValueError:
            return False
        children = len(item.children)
        if children:
            self.beginMoveRows(self.index_of(item), 0, children - 1,
                               parent_index, row)
            siblings[row:row] = item.children
            item.children = []
            self._reindex()
            self.endMoveRows()
        # The promotion pushed it down by as many rows as it had children.
        self.beginRemoveRows(parent_index, row + children, row + children)
        siblings.pop(row + children)
        self._reindex()
        self.endRemoveRows()
        return True
