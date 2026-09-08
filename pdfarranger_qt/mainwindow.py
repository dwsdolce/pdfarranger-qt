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

"""Main window: menu bar, tool bar, status bar, and the actions that drive them.

The GTK version put its commands behind a hamburger popover; here they live in a
real menu bar with a tool bar for the common ones, which is what the platform
expects.
"""

import logging
import os
import sys
from typing import List, Optional

from PySide6.QtCore import QProcess, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QStyle,
    QToolBar,
)

from . import (
    APP_NAME,
    PROJECT_URL,
    UPSTREAM_URL,
    __version_string__,
    booklet,
    clipboard,
    compress,
    dialogs,
    layers,
    nup,
    printing,
    raster,
    reader,
    repair,
    stamp,
    theme,
    viewer,
)
from .core import DocumentSet, Page, PDFDocError
from .export import SaveOptions, export
from .i18n import gettext_ as _
from .i18n import menu_label as _m
from .i18n import ngettext
from .model import PageListModel
from .outline import Outline
from .recent import RecentFiles
from .render import Renderer
from .search import SearchIndex
from .settings import app_settings
from .view import PageView

PDF_FILTER = "PDF files (*.pdf)"
IMPORT_FILTER = ("PDF and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif)"
                 ";;PDF files (*.pdf);;All files (*)")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Locked by decision D1: this scope must not change,
        # or saved geometry and zoom are silently orphaned.
        self.settings = app_settings()
        self.docs = DocumentSet()
        self.renderer = Renderer(self)
        self.model = PageListModel(self.renderer, self)
        self.model.doc_password = self._password_for
        self.model.doc_files = self.docs.files_for_export
        self.view = PageView(self.model, self)
        self.reader = reader.ReaderView(self)
        # One stack, two modes. The reader is what a window shows, opened or
        # empty; the grid is where you go to change the document you are
        # reading. That is the other way round from how this started -- it was
        # an arranger that could read -- and the grid keeps index 0 only because
        # moving it would churn every test that indexes the stack.
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.reader)
        # Reading is the default state, so a window that has never opened a
        # document still shows the reader rather than an arranger.
        self.stack.setCurrentWidget(self.reader)
        self.setCentralWidget(self.stack)
        self.reader.page_changed.connect(self._reader_page_changed)
        self.reader.selection_changed.connect(self._reader_selection_changed)
        # The sidebar shows the document's outline, not the reader document's
        # (D20), so the window keeps the two in step.
        self.model.outline_changed.connect(self._refresh_outline)
        self.reader.page_of_uid = self._page_of_uid
        self.reader.uid_of_page = self._uid_of_page
        # Bookmark commands live on the tree, undo lives here. The reader says
        # what it is about to do and the window records it, so a bookmark edit
        # and a page edit come off one stack (D20).
        self.reader.outline_edit_begun.connect(self.model.undo.commit)
        self.reader.outline_edited.connect(self._outline_edited)
        self.reader.set_facing(
            self.settings.value("reader/facing", False, type=bool))
        self.reader.set_continuous(
            self.settings.value("reader/continuous", True, type=bool))
        self.setAcceptDrops(True)

        self.current_path: Optional[str] = None
        self.modified = False
        #: The files this window was opened from, resolved. See `holds`.
        self.opened_paths: set = set()
        #: Document properties, merged with the sources' own metadata on export.
        self.metadata: dict = {}
        #: Text search; rebuilt lazily whenever the document changes.
        self.search = SearchIndex()
        self.recent = RecentFiles(self.settings)
        #: Encrypts the document on save when set. Deliberately not
        #: persisted anywhere: it is a property of this session's
        #: document, and writing it to QSettings would put a password
        #: in the registry in clear text.
        self.output_password = None
        #: What the saved document asks a viewer to do when it is opened.
        #: Read from the file when one is opened, so a plain round trip keeps
        #: what it already said; see `viewer`.
        self.viewer_prefs = viewer.Preferences()
        #: True while the reader is showing. The grid is always index 0.
        #: Reading is the default; an empty window is a reader with no document.
        self.read_mode = True
        #: Set when an edit happens while reading, so the snapshot is rebuilt
        #: on the next entry rather than on every keystroke.
        self._reader_stale = True
        #: Zoom to restore when double-click toggles fit back off.
        self._zoom_before_fit: Optional[float] = None
        self.import_dir = os.path.expanduser("~")

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.view.selection_changed.connect(self._on_selection_changed)
        self.view.zoom_requested.connect(self._zoom_by)
        self.view.files_dropped.connect(self._import_files_at)
        self.view.reorder_requested.connect(self.move_pages)
        self.view.zoom_fit_toggled.connect(self.toggle_zoom_fit)
        self.view.pages_dropped.connect(self.pages_dropped)
        QApplication.clipboard().dataChanged.connect(self._refresh_state)
        self.model.contents_changed.connect(self._refresh_state)
        # Any edit invalidates the search index, which is built from
        # a render of the *edited* document.
        self.model.contents_changed.connect(self.search.invalidate)
        # Rows move when pages do, so the highlights are stale the moment the
        # document changes. Drop them rather than draw them in the wrong place.
        self.model.contents_changed.connect(self.model.clear_matches)
        # The reader shows a snapshot of the page list, so an edit dates it.
        self.model.contents_changed.connect(self._invalidate_reader)

        self._restore_geometry()
        self._restore_shortcuts()
        theme.apply(self._preference("theme"))
        self._refresh_state()

    # -- construction ------------------------------------------------------

    def _icon(self, standard):
        return self.style().standardIcon(standard)

    #: Qt dynamic properties recording where a label came from, so it can be
    #: produced again in another language. See `retranslate`.
    MSGID = "pdfarranger_msgid"
    MNEMONIC = "pdfarranger_mnemonic"

    def _action(self, msgid, icon=None, mnemonic=True):
        """A QAction that remembers the msgid its label was made from.

        Recording the msgid rather than translating back from the label,
        because translating back is ambiguous: 22 of the 33 catalogues have at
        least one string that two different msgids share. Spanish renders both
        `Rotate Left` and `Rotate _Left` as "Rotar a la izquierda", so a
        reverse lookup would have to guess, and guessing wrong loses the
        keyboard accelerator without saying so.

        ``mnemonic`` picks the translator: menu labels carry a GTK-style
        underscore that `_m` converts for Qt; a tooltip or a toolbar label does
        not.
        """
        text = _m(msgid) if mnemonic else _(msgid)
        action = QAction(text, self) if icon is None else QAction(icon, text, self)
        action.setProperty(self.MSGID, msgid)
        action.setProperty(self.MNEMONIC, mnemonic)
        return action

    def retranslate(self):
        """Redo every label in the current language, in place.

        Called when the language changes. The actions themselves are kept --
        rebuilding them would drop every connection made to them and reset the
        checked state of every toggle -- so this only re-derives their text.

        Dialogs are built on demand and need nothing here; they come up in
        whatever language is current. What is stuck without this is the
        window's own chrome, which is built once and outlives the setting.
        """
        for action in self.findChildren(QAction):
            msgid = action.property(self.MSGID)
            if msgid:
                action.setText(_m(msgid) if action.property(self.MNEMONIC)
                               else _(msgid))
        self._menu_titles = {}
        for menu in self._menus:
            msgid = menu.property(self.MSGID)
            if msgid:
                title = _m(msgid) if menu.property(self.MNEMONIC) else _(msgid)
                menu.setTitle(title)
                if menu.objectName():
                    self._menu_titles[menu.objectName()] = title.replace("&", "")
        for bar in self.findChildren(QToolBar):
            msgid = bar.property(self.MSGID)
            if msgid:
                # setWindowTitle, because that is what a toolbar's own toggle
                # action shows; setting the action's text directly would be
                # overwritten the next time Qt rebuilt it.
                bar.setWindowTitle(_(msgid))
        self._apply_static_tips()
        # Everything derived rather than fixed -- the undo verb, the page
        # counts, the mode label -- is recomputed rather than translated.
        self._refresh_state()
        self._retitle()

    def _apply_static_tips(self):
        """Tips that are fixed text rather than derived from the document.

        Kept out of the menu builder so `retranslate` can run it again: an
        action's label is not the only thing a language change has to reach.
        """
        self.act_import.setStatusTip(
            _("Insert pages from another PDF or an image"))
        # Five permanently-greyed entries with no explanation is the most
        # confusing thing in that menu: they need *pages* on the clipboard, not
        # text, and nothing on screen says so until one is there to hover.
        needs_pages = _("Needs pages copied from a document")
        for act in (self.act_paste, self.act_paste_before, self.act_paste_odd,
                    self.act_paste_even, self.act_paste_overlay,
                    self.act_paste_underlay):
            act.setStatusTip(needs_pages)
            act.setToolTip(needs_pages)

    def _build_actions(self):
        st = QStyle.StandardPixmap
        self.act_new_window = self._action("_New Window")
        self.act_new_window.setShortcut(QKeySequence.New)
        # Wrapped, not connected directly: `triggered` passes the action's
        # checked state, which would arrive as `new_window(paths=False)`. That
        # happens to be harmless today only because the action is not checkable
        # and False is falsy.
        self.act_new_window.triggered.connect(lambda: self.new_window())

        self.act_open = self._action("_Open", icon=self._icon(st.SP_DialogOpenButton))
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.open_file)

        self.act_import = self._action("_Import")
        self.act_import.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import.triggered.connect(self.import_files)

        self.act_save = self._action("_Save", icon=self._icon(st.SP_DialogSaveButton))
        self.act_save.setShortcut(QKeySequence.Save)
        self.act_save.triggered.connect(self.save)

        self.act_save_as = self._action("Save _As…")
        self.act_save_as.setShortcut(QKeySequence.SaveAs)
        self.act_save_as.triggered.connect(self.save_as)

        self.act_export_sel = self._action("E_xport Selection to a Single File…")
        self.act_export_sel.triggered.connect(self.export_selection)

        self.act_close = self._action("_Close")
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close_document)

        self.act_quit = self._action("_Quit")
        self.act_quit.setShortcut(QKeySequence.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_undo = self._action("_Undo", icon=self._icon(st.SP_ArrowBack))
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.triggered.connect(self.undo)

        self.act_redo = self._action("_Redo", icon=self._icon(st.SP_ArrowForward))
        self.act_redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        self.act_redo.triggered.connect(self.redo)

        self.act_select_all = self._action("Select _All")
        self.act_select_all.setShortcut(QKeySequence.SelectAll)
        self.act_select_all.triggered.connect(self.select_all)

        self.act_invert = self._action("_Invert Selection")
        self.act_invert.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_invert.triggered.connect(self.invert_selection)

        self.act_delete = self._action("_Delete", icon=self._icon(st.SP_TrashIcon))
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self.delete_selected)

        self.act_duplicate = self._action("_Duplicate")
        self.act_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self.act_duplicate.triggered.connect(self.duplicate_selected)

        self.act_rotate_left = self._action("Rotate _Left")
        self.act_rotate_left.setShortcut(QKeySequence("Ctrl+L"))
        self.act_rotate_left.triggered.connect(lambda: self.rotate(-90))

        self.act_rotate_right = self._action("_Rotate Right")
        self.act_rotate_right.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rotate_right.triggered.connect(lambda: self.rotate(90))

        self.act_zoom_in = self._action("Zoom _In")
        self.act_zoom_in.setShortcut(QKeySequence.ZoomIn)
        self.act_zoom_in.triggered.connect(lambda: self._zoom_by(1.25))

        self.act_zoom_out = self._action("Zoom _Out")
        self.act_zoom_out.setShortcut(QKeySequence.ZoomOut)
        self.act_zoom_out.triggered.connect(lambda: self._zoom_by(0.8))

        self.act_zoom_reset = self._action("_Reset Zoom")
        self.act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_reset.triggered.connect(self.reset_zoom)

        self.act_help = self._action("User Guide", mnemonic=False)
        self.act_help.setShortcut(QKeySequence.HelpContents)
        self.act_help.triggered.connect(self.show_help)

        self.act_project = self._action("Project on GitHub", mnemonic=False)
        self.act_project.triggered.connect(self.open_project_page)

        self.act_about = self._action("_About")
        self.act_about.triggered.connect(self.about)

        # -- clipboard ----------------------------------------------------
        self.act_cut = self._action("Cu_t")
        self.act_cut.setShortcut(QKeySequence.Cut)
        self.act_cut.triggered.connect(self.cut_selected)

        self.act_copy = self._action("_Copy")
        self.act_copy.setShortcut(QKeySequence.Copy)
        self.act_copy.triggered.connect(self.copy_selected)

        self.act_paste = self._action("Paste _After")
        self.act_paste.setShortcut(QKeySequence.Paste)
        self.act_paste.triggered.connect(lambda: self.paste("AFTER"))

        self.act_paste_before = self._action("Paste _Before")
        self.act_paste_before.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.act_paste_before.triggered.connect(lambda: self.paste("BEFORE"))

        self.act_paste_odd = self._action("Paste As _Odd Pages")
        self.act_paste_odd.triggered.connect(lambda: self.paste("ODD"))

        self.act_paste_even = self._action("Paste As _Even Pages")
        self.act_paste_even.triggered.connect(lambda: self.paste("EVEN"))

        # -- selection ----------------------------------------------------
        self.act_deselect = self._action("_Deselect All")
        self.act_deselect.triggered.connect(self.deselect)

        self.act_select_odd = self._action("Select _Odd Pages")
        self.act_select_odd.triggered.connect(lambda: self.select_parity(1))

        self.act_select_even = self._action("Select _Even Pages")
        self.act_select_even.triggered.connect(lambda: self.select_parity(0))

        self.act_select_same_file = self._action("All From _Same File")
        self.act_select_same_file.triggered.connect(
            lambda: self.select_matching("copyname"))

        self.act_select_same_format = self._action("Same Page _Format")
        self.act_select_same_format.triggered.connect(
            lambda: self.select_matching("size_in_points"))

        # -- arrange ------------------------------------------------------
        # Moving a page a long way. Cut and paste can do it, but a pasted page
        # is a *new* page with a new uid (D20), so its bookmarks stay behind
        # dangling -- these keep the page itself and carry them along.
        self.act_move_to_start = self._action("Move to Start", mnemonic=False)
        self.act_move_to_start.setShortcut(QKeySequence("Ctrl+Shift+Home"))
        self.act_move_to_start.triggered.connect(self.move_to_start)

        self.act_move_to_end = self._action("Move to End", mnemonic=False)
        self.act_move_to_end.setShortcut(QKeySequence("Ctrl+Shift+End"))
        self.act_move_to_end.triggered.connect(self.move_to_end)

        self.act_move_to_page = self._action("Move to Page…", mnemonic=False)
        self.act_move_to_page.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.act_move_to_page.triggered.connect(self.move_to_page)

        self.act_reverse = self._action("Reverse Order", mnemonic=False)
        self.act_reverse.triggered.connect(self.reverse_order)

        self.act_swap = self._action("Swap Odd/Even")
        self.act_swap.triggered.connect(self.swap_odd_even)

        self.act_split_booklet = self._action("_Split (unimposition)")
        self.act_split_booklet.triggered.connect(self.split_booklet)

        # -- export -------------------------------------------------------
        self.act_export_all_multi = self._action(
            "Export _All Pages to Individual Files…")
        self.act_export_all_multi.triggered.connect(
            lambda: self.export_multiple(all_pages=True))

        self.act_export_sel_multi = self._action(
            "Export Selection to _Individual Files…")
        self.act_export_sel_multi.triggered.connect(
            lambda: self.export_multiple(all_pages=False))

        # -- page editing (phase 2 dialogs) --------------------------------
        self.act_crop = self._action("_Crop Margins…")
        self.act_crop.setShortcut(QKeySequence("C"))
        self.act_crop.triggered.connect(lambda: self.edit_margins(hide=False))

        self.act_hide = self._action("_Hide Margins…")
        self.act_hide.setShortcut(QKeySequence("H"))
        self.act_hide.triggered.connect(lambda: self.edit_margins(hide=True))

        self.act_page_size = self._action("_Page Size…")
        self.act_page_size.setShortcut(QKeySequence("S"))
        self.act_page_size.triggered.connect(self.page_size)

        self.act_insert_blank = self._action("Insert Blan_k Page…")
        self.act_insert_blank.triggered.connect(self.insert_blank_page)

        self.act_split_pages = self._action("_Split Pages…")
        self.act_split_pages.triggered.connect(self.split_pages)

        self.act_merge_pages = self._action("_Merge Pages…")
        self.act_merge_pages.triggered.connect(self.merge_pages)

        self.act_gen_booklet = self._action("_Generate (imposition)")
        self.act_gen_booklet.triggered.connect(self.generate_booklet)

        self.act_nup = self._action("Pages per S_heet…")
        self.act_nup.triggered.connect(self.pages_per_sheet)

        self.act_page_numbers = self._action("Add Page N_umbers…")
        self.act_page_numbers.triggered.connect(self.add_page_numbers)

        self.act_watermark = self._action("Add _Watermark…")
        self.act_watermark.triggered.connect(self.add_watermark)

        self.act_compress = self._action("Compress _Images…")
        self.act_compress.triggered.connect(self.compress_images)

        self.act_password = self._action("Pass_word")
        self.act_password.setCheckable(True)
        self.act_password.triggered.connect(self.set_password)
        self.act_unlock = self._action("_Unlock")
        self.act_unlock.triggered.connect(self.unlock)

        self.act_properties = self._action("Edit _Properties")
        self.act_properties.setShortcut(QKeySequence("Alt+Return"))
        self.act_properties.triggered.connect(self.edit_properties)

        self.act_viewer_prefs = self._action("_Viewer Preferences…")
        self.act_viewer_prefs.triggered.connect(self.edit_viewer_preferences)

        self.act_strip_metadata = self._action("Remove All _Metadata")
        self.act_strip_metadata.setCheckable(True)
        self.act_strip_metadata.triggered.connect(self.set_strip_metadata)

        self.act_repair = self._action("_Repair Document…")
        self.act_repair.triggered.connect(self.repair_document)

        # -- phase 3: raster, search, print, preferences --------------------
        self.act_crop_white = self._action("Crop White Borders")
        self.act_crop_white.triggered.connect(self.crop_white_borders)

        self.act_export_png = self._action("Export Selection to _PNG Images…")
        self.act_export_png.triggered.connect(lambda: self.export_images("png"))

        self.act_export_jpg = self._action("Export Selection to _JPG Images…")
        self.act_export_jpg.triggered.connect(lambda: self.export_images("jpg"))

        self.act_export_raster_pdf = self._action(
            "Export Selection to _Rasterized PDF (png)…")
        self.act_export_raster_pdf.triggered.connect(
            lambda: self.export_rasterised("png"))

        self.act_export_raster_pdf_jpg = self._action(
            "Export Selection to _Rasterized PDF (jpg)…")
        self.act_export_raster_pdf_jpg.triggered.connect(
            lambda: self.export_rasterised("jpg"))

        self.act_copy_text = self._action("Copy Text", mnemonic=False)
        self.act_copy_text.triggered.connect(self.copy_page_text)

        self.act_copy_image = self._action("Copy _Image")
        self.act_copy_image.triggered.connect(self.copy_page_image)

        self.act_explode = self._action("_Explode into Images")
        self.act_explode.triggered.connect(self.explode_into_images)

        self.act_print = self._action("_Print…")
        self.act_print.setShortcut(QKeySequence.Print)
        self.act_print.triggered.connect(self.print_document)

        self.act_find = self._action("_Find…")
        self.act_find.setShortcut(QKeySequence.Find)
        self.act_find.triggered.connect(self.find_text)

        self.act_find_next = self._action("Find Next", mnemonic=False)
        self.act_find_next.setShortcut(QKeySequence("F3"))
        self.act_find_next.triggered.connect(lambda: self.find_step(forward=True))

        self.act_find_prev = self._action("Find Previous", mnemonic=False)
        self.act_find_prev.setShortcut(QKeySequence("Shift+F3"))
        self.act_find_prev.triggered.connect(lambda: self.find_step(forward=False))

        self.act_find_all = self._action("Find All", mnemonic=False)
        self.act_find_all.triggered.connect(self.find_all)

        self.act_preferences = self._action("Preferences")
        self.act_preferences.triggered.connect(self.edit_preferences)

        self.act_select_range = self._action("Select _Range")
        self.act_select_range.triggered.connect(self.select_range)

        self.act_paste_overlay = self._action("Paste As O_verlay…")
        self.act_paste_overlay.triggered.connect(lambda: self.paste_layer("OVERLAY"))

        self.act_paste_underlay = self._action("Paste As _Underlay…")
        self.act_paste_underlay.triggered.connect(lambda: self.paste_layer("UNDERLAY"))

        # -- view ---------------------------------------------------------
        self.act_zoom_fit = self._action("Fit _One Page")
        self.act_zoom_fit.setShortcut(QKeySequence("F"))
        self.act_zoom_fit.triggered.connect(self.zoom_fit)

        self.act_zoom_fit_multi = self._action("Fit _Multiple Pages")
        self.act_zoom_fit_multi.setShortcut(QKeySequence("Shift+M"))
        self.act_zoom_fit_multi.triggered.connect(self.zoom_fit_multiple)

        self.act_zoom_fit_width = self._action("Fit Width", mnemonic=False)
        self.act_zoom_fit_width.setShortcut(QKeySequence("Shift+F"))
        self.act_zoom_fit_width.triggered.connect(self.zoom_fit_width)

        # Labelled for what it switches *to*, and checked while arranging:
        # reading is the default state now, so the command a reader wants is
        # "let me rearrange this", not "let me read it".
        self.act_arrange_mode = self._action("Arrange Mode", mnemonic=False)
        self.act_arrange_mode.setCheckable(True)
        # Unchecked from the start: an empty window is a reader waiting for a
        # document. Keeps "checked means the grid is showing" true everywhere.
        self.act_arrange_mode.setChecked(False)
        self.act_arrange_mode.setShortcut(QKeySequence("Ctrl+E"))
        self.act_arrange_mode.triggered.connect(self.set_arrange_mode)

        self.act_facing = self._action("Facing Pages", mnemonic=False)
        self.act_facing.setCheckable(True)
        self.act_facing.setChecked(
            self.settings.value("reader/facing", False, type=bool))
        self.act_facing.triggered.connect(self.set_facing_pages)

        self.act_continuous = self._action("Continuous Scroll", mnemonic=False)
        self.act_continuous.setCheckable(True)
        self.act_continuous.setChecked(
            self.settings.value("reader/continuous", True, type=bool))
        self.act_continuous.triggered.connect(self.set_continuous_scroll)

        # Ctrl+PageUp/Down rather than the bare keys: those belong to whichever
        # view has focus -- the grid moves the selection with them, and the
        # reader handles them itself -- and a window-wide shortcut would take
        # them away from both.
        self.act_next_page = self._action("Next Page", mnemonic=False)
        self.act_next_page.setShortcut(QKeySequence("Ctrl+PgDown"))
        self.act_next_page.triggered.connect(lambda: self.reader.next_page())

        self.act_prev_page = self._action("Previous Page", mnemonic=False)
        self.act_prev_page.setShortcut(QKeySequence("Ctrl+PgUp"))
        self.act_prev_page.triggered.connect(lambda: self.reader.previous_page())

        self.act_first_page = self._action("First Page", mnemonic=False)
        self.act_first_page.triggered.connect(lambda: self.reader.first_page())

        self.act_last_page = self._action("Last Page", mnemonic=False)
        self.act_last_page.triggered.connect(lambda: self.reader.last_page())

        self.act_go_to_page = self._action("Go to Page…", mnemonic=False)
        self.act_go_to_page.setShortcut(QKeySequence("Ctrl+G"))
        self.act_go_to_page.triggered.connect(self.go_to_page)

        self.act_fullscreen = self._action("Fullscreen", mnemonic=False)
        self.act_fullscreen.setShortcut(QKeySequence("F11"))
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)

    def _menu(self, parent, msgid, role=None, mnemonic=True):
        """Create a menu owned by the window, and add it to ``parent``.

        Takes the msgid rather than the translated title, for the same reason
        `_action` does: so `retranslate` can produce it again.

        ``role`` is the menu's untranslated name, kept as its object name, so
        that anything deciding *which* menu this is -- read mode's editing gate
        -- asks for that rather than matching the title. The title is
        translated; the role never is.

        Never `parent.addMenu(title)`. That returns a QMenu which PySide hands
        to Python, so anything that later calls `action.menu()` -- the shortcut
        editor walking the menu bar -- takes a temporary reference to it, and
        destroying that temporary destroys the menu itself. The symptom is
        "Internal C++ object (QMenu) already deleted" from an aboutToShow
        handler, at whatever point the garbage collector happens to run.

        Constructing it with the window as parent leaves ownership in C++,
        where it belongs, and self._menus keeps a Python reference besides.
        """
        title = _m(msgid) if mnemonic else _(msgid)
        menu = QMenu(title, self)
        menu.setProperty(self.MSGID, msgid)
        menu.setProperty(self.MNEMONIC, mnemonic)
        if role:
            menu.setObjectName(role)
            self._menu_titles[role] = title.replace("&", "")
        self._menus.append(menu)
        parent.addMenu(menu)
        return menu

    def _build_menus(self):
        # Strong references to every menu; see _menu().
        self._menus = []
        #: Untranslated menu role -> the label the user sees, for the shortcut
        #: editor's headings.
        self._menu_titles = {}
        bar = self.menuBar()
        m = self._menu(bar, "_File", role="File")
        m.addAction(self.act_new_window)
        m.addAction(self.act_open)
        self.recent_menu = self._menu(m, "Open Recent", mnemonic=False)
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        m.addAction(self.act_import)
        m.addSeparator()
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        export_menu = self._menu(m, "E_xport")
        export_menu.addAction(self.act_export_sel)
        export_menu.addAction(self.act_export_sel_multi)
        export_menu.addAction(self.act_export_all_multi)
        export_menu.addSeparator()
        export_menu.addAction(self.act_export_png)
        export_menu.addAction(self.act_export_jpg)
        export_menu.addAction(self.act_export_raster_pdf)
        export_menu.addAction(self.act_export_raster_pdf_jpg)
        m.addSeparator()
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addAction(self.act_properties)
        m.addAction(self.act_viewer_prefs)
        m.addAction(self.act_strip_metadata)
        m.addAction(self.act_password)
        m.addAction(self.act_unlock)
        m.addSeparator()
        m.addAction(self.act_repair)
        m.addSeparator()
        m.addAction(self.act_close)
        m.addAction(self.act_quit)

        self._apply_static_tips()

        m = self._menu(bar, "_Edit", role="Edit")
        m.addAction(self.act_undo)
        m.addAction(self.act_redo)
        m.addSeparator()
        m.addAction(self.act_cut)
        m.addAction(self.act_copy)
        m.addAction(self.act_paste)
        paste_menu = self._menu(m, "Past_e Special")
        paste_menu.addAction(self.act_paste_before)
        paste_menu.addAction(self.act_paste_odd)
        paste_menu.addAction(self.act_paste_even)
        paste_menu.addSeparator()
        paste_menu.addAction(self.act_paste_overlay)
        paste_menu.addAction(self.act_paste_underlay)
        m.addSeparator()
        # Select All and Deselect stay in Edit: they mean something in either
        # mode. The rest are page-selection commands and have moved to Arrange,
        # which is now a mode you deliberately enter rather than the default.
        m.addAction(self.act_select_all)
        m.addAction(self.act_deselect)
        m.addSeparator()
        m.addAction(self.act_find)
        m.addAction(self.act_find_next)
        m.addAction(self.act_find_prev)
        m.addAction(self.act_find_all)
        m.addSeparator()
        m.addAction(self.act_preferences)

        m = self._menu(bar, "_Page", role="Page")
        m.addAction(self.act_rotate_left)
        m.addAction(self.act_rotate_right)
        m.addSeparator()
        m.addAction(self.act_crop)
        m.addAction(self.act_hide)
        m.addAction(self.act_crop_white)
        m.addAction(self.act_page_size)
        m.addSeparator()
        m.addAction(self.act_duplicate)
        m.addAction(self.act_delete)
        m.addAction(self.act_insert_blank)
        m.addSeparator()
        extract_menu = self._menu(m, "_Extract")
        extract_menu.addAction(self.act_copy_text)
        extract_menu.addAction(self.act_copy_image)
        m.addAction(self.act_explode)
        m.addSeparator()
        m.addAction(self.act_page_numbers)
        m.addAction(self.act_watermark)
        m.addSeparator()
        m.addAction(self.act_compress)

        m = self._menu(bar, "Arrange", mnemonic=False, role="Arrange")
        select_menu = self._menu(m, "_Select")
        select_menu.addAction(self.act_select_all)
        select_menu.addAction(self.act_deselect)
        select_menu.addAction(self.act_invert)
        select_menu.addSeparator()
        select_menu.addAction(self.act_select_odd)
        select_menu.addAction(self.act_select_even)
        select_menu.addAction(self.act_select_same_file)
        select_menu.addAction(self.act_select_same_format)
        select_menu.addSeparator()
        select_menu.addAction(self.act_select_range)
        m.addSeparator()
        m.addAction(self.act_move_to_start)
        m.addAction(self.act_move_to_end)
        m.addAction(self.act_move_to_page)
        m.addSeparator()
        m.addAction(self.act_reverse)
        m.addAction(self.act_swap)
        m.addSeparator()
        m.addAction(self.act_split_pages)
        m.addAction(self.act_merge_pages)
        m.addAction(self.act_nup)
        m.addSeparator()
        booklet_menu = self._menu(m, "_Booklet")
        booklet_menu.addAction(self.act_gen_booklet)
        booklet_menu.addAction(self.act_split_booklet)

        m = self._menu(bar, "_View", role="View")
        m.addAction(self.act_arrange_mode)
        m.addAction(self.act_continuous)
        m.addAction(self.act_facing)
        m.addAction(self.act_prev_page)
        m.addAction(self.act_next_page)
        m.addAction(self.act_first_page)
        m.addAction(self.act_last_page)
        m.addAction(self.act_go_to_page)
        m.addSeparator()
        m.addAction(self.act_zoom_in)
        m.addAction(self.act_zoom_out)
        m.addAction(self.act_zoom_fit)
        m.addAction(self.act_zoom_fit_multi)
        m.addAction(self.act_zoom_fit_width)
        m.addAction(self.act_zoom_reset)
        m.addSeparator()
        m.addAction(self.act_fullscreen)

        m = self._menu(bar, "_Help", role="Help")
        m.addAction(self.act_help)
        m.addSeparator()
        m.addAction(self.act_project)
        m.addAction(self.act_about)

        # Right-click on the grid gets the page-level commands.
        self.view.setContextMenuPolicy(Qt.ActionsContextMenu)
        for act in (self.act_cut, self.act_copy, self.act_paste,
                    self.act_rotate_left, self.act_rotate_right,
                    self.act_duplicate, self.act_delete,
                    self.act_move_to_start, self.act_move_to_end,
                    self.act_move_to_page):
            self.view.addAction(act)

    def _build_toolbar(self):
        # Two toolbars, one per mode, rather than one that greys out.
        #
        # The first attempt kept a single toolbar and hid the editing buttons
        # while reading. It does not work: QToolBar drives its buttons'
        # visibility from the action, so widgetForAction(...).setVisible(False)
        # is undone at the next layout, and QAction.setVisible(False) would take
        # the command out of the menus as well. The result was a toolbar full of
        # dead buttons beside a page box that came and went -- two paradigms at
        # once, which is what prompted this.
        #
        # Menus still grey rather than hide: they are the inventory of what the
        # application can do, and a vanishing entry teaches nothing. A toolbar
        # is the opposite -- what is useful right now.
        # A toolbar's title is its window title, and it is what the
        # right-click "show this bar" entry is called -- so it is a visible
        # string like any other, and recorded the same way.
        self.toolbar = self.addToolBar(_("Arrange"))
        self.toolbar.setObjectName("main-toolbar")
        self.toolbar.setProperty(self.MSGID, "Arrange")
        self.reader_toolbar = self.addToolBar(_("Read"))
        self.reader_toolbar.setObjectName("reader-toolbar")
        self.reader_toolbar.setProperty(self.MSGID, "Read")
        for bar in (self.toolbar, self.reader_toolbar):
            bar.setIconSize(QSize(20, 20))
            bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            # Shared by both, so the way out of a mode is always in the same
            # place. One QAction can live in any number of widgets.
            bar.addAction(self.act_open)
            bar.addAction(self.act_save)
            bar.addSeparator()
            bar.addAction(self.act_arrange_mode)
            bar.addSeparator()

        self.toolbar.addAction(self.act_undo)
        self.toolbar.addAction(self.act_redo)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_rotate_left)
        self.toolbar.addAction(self.act_rotate_right)
        self.toolbar.addAction(self.act_duplicate)
        self.toolbar.addAction(self.act_delete)

        self.reader_toolbar.addAction(self.act_prev_page)
        self.reader_toolbar.addWidget(self.reader.page_selector)
        self.toolbar_page_total = QLabel("")
        self.toolbar_page_total.setContentsMargins(4, 0, 8, 0)
        self.reader_toolbar.addWidget(self.toolbar_page_total)
        self.reader_toolbar.addAction(self.act_next_page)
        self.reader_toolbar.addSeparator()
        self.reader_toolbar.addAction(self.act_zoom_fit)
        self.reader_toolbar.addAction(self.act_zoom_fit_width)
        self.reader_toolbar.setVisible(False)

    def _build_statusbar(self):
        self.status_pages = QLabel()
        # Where the open document actually is. The title bar and Open Recent
        # both show only the basename, so with several similarly-named files
        # there was nothing in the UI that answered "which one is this?".
        self.status_path = QLabel()
        self.status_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_selection = QLabel()
        #: Permanent, unlike showMessage(), which expires after a few seconds
        #: and would leave a mode with no visible indicator at all.
        self.status_mode = QLabel()
        self.statusBar().addWidget(self.status_pages)
        self.statusBar().addWidget(self.status_path, 1)
        self.statusBar().addPermanentWidget(self.status_mode)
        self.statusBar().addPermanentWidget(self.status_selection)

    def _update_status_path(self):
        """Show the document's directory, elided to whatever room there is."""
        if not self.current_path:
            self.status_path.setText("")
            self.status_path.setToolTip("")
            return
        full = os.path.abspath(self.current_path)
        self.status_path.setToolTip(full)
        metrics = QFontMetrics(self.status_path.font())
        # Half the window at most, so it never crowds out the page count.
        room = max(120, self.width() // 2)
        self.status_path.setText(
            metrics.elidedText(full, Qt.ElideMiddle, room))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_status_path()

    # -- state -------------------------------------------------------------

    def _password_for(self, page) -> str:
        doc = self.docs.docs[page.nfile - 1]
        return doc.password

    def _editing_actions(self):
        """Every action that changes the document.

        Derived from the menus rather than listed by hand: a new editing
        command added to Page or Arrange is disabled in read mode automatically,
        where a hand-kept list would quietly miss it. View and Help never edit,
        and File is filtered to the commands that write.

        Menus are matched by their *role*, not their title. Against the title
        this matched nothing as soon as the user picked a language, so read
        mode greyed out the whole File menu -- Open, Save and Quit included --
        in every language but English.
        """
        never_edits = {"File", "View", "Help"}  # roles, never titles
        writes_in_file = {self.act_import, self.act_password, self.act_unlock,
                          self.act_viewer_prefs, self.act_strip_metadata}
        out = []
        for title, actions in self._shortcut_groups():
            if title in never_edits:
                out.extend(a for a in actions if a in writes_in_file)
                continue
            out.extend(actions)
        # Find and Preferences live under Edit but change nothing. Copy,
        # Select All and Deselect are here because they mean something in both
        # modes -- text while reading, pages while arranging.
        #
        # The rest of the Select commands are deliberately *not* exempt. They
        # only ever act on the page grid, and while reading that grid is not on
        # screen: leaving them enabled meant Select Odd Pages quietly changed a
        # selection nobody could see, which is indistinguishable from the
        # command being broken. Greyed out, they say which mode they belong to.
        harmless = {self.act_find, self.act_find_next, self.act_find_prev,
                    self.act_find_all, self.act_preferences,
                    self.act_copy, self.act_select_all, self.act_deselect}
        return [a for a in out if a not in harmless]

    def _refresh_state(self):
        n = self.model.rowCount()
        has_pages = n > 0
        self._update_status_pages()
        for act in (self.act_save, self.act_save_as, self.act_import,
                    self.act_select_all, self.act_invert, self.act_close,
                    self.act_deselect, self.act_select_odd, self.act_select_even,
                    self.act_zoom_fit, self.act_zoom_fit_multi,
                    self.act_zoom_fit_width,
                    self.act_export_all_multi,
                    self.act_insert_blank, self.act_select_range,
                    self.act_viewer_prefs, self.act_strip_metadata,
                    self.act_print, self.act_find,
                    self.act_find_next, self.act_find_prev, self.act_find_all):
            act.setEnabled(has_pages)
        for act in (self.act_paste, self.act_paste_before,
                    self.act_paste_odd, self.act_paste_even,
                    self.act_paste_overlay, self.act_paste_underlay):
            act.setEnabled(clipboard.is_page_data(QApplication.clipboard().text()))
        # Editing the properties of a document that is about to have all of
        # them thrown away is a contradiction; the checkbox says which wins.
        self.act_properties.setEnabled(
            has_pages and not self.act_strip_metadata.isChecked())
        # Offered only when there is encryption to remove. Always enabled it
        # would claim to do something on every plain document and then do
        # nothing, which is the discoverability problem again with the sign
        # flipped.
        self.act_unlock.setEnabled(
            has_pages and (self.is_encrypted() or bool(self.output_password)))
        self.act_undo.setEnabled(self.model.undo.can_undo)
        self.act_redo.setEnabled(self.model.undo.can_redo)
        undo_label = self.model.undo.undo_label()
        # A msgid rather than an f-string: built by concatenation the verb
        # could not be translated at all, in any language.
        self.act_undo.setText(_m("_Undo %s") % undo_label if undo_label
                              else _m("_Undo"))
        redo_label = self.model.undo.redo_label()
        self.act_redo.setText(_m("_Redo %s") % redo_label if redo_label
                              else _m("_Redo"))
        self._on_selection_changed(self.view.selected_rows())
        if self.read_mode:
            # Last, so it overrides everything the calls above just enabled.
            for act in self._editing_actions():
                act.setEnabled(False)
        self.status_mode.setText(_("Reading") if self.read_mode else "")
        # Always available: switching view is not an edit, and with no document
        # both views are empty, so there is nothing to protect the user from.
        self.act_arrange_mode.setEnabled(True)
        for act in (self.act_continuous, self.act_facing, self.act_next_page,
                    self.act_prev_page, self.act_first_page, self.act_last_page,
                    self.act_go_to_page):
            # Pages as well as the mode: read mode is now the state an empty
            # window is in, and "Next Page" with no document is a button that
            # cannot do anything.
            act.setEnabled(self.read_mode and has_pages)
        if self.read_mode:
            # The grid's selection is still there behind the reader, and it is
            # not what Copy means now. Select All is always available; Copy
            # waits for something to be selected.
            self.act_copy.setEnabled(self.reader.has_selection())
            self.act_select_all.setEnabled(has_pages)
        # The reader lays out one column; facing pages is phase 7 step 6.
        # So this one is grid-only.
        self.act_zoom_fit_multi.setEnabled(has_pages and not self.read_mode)
        if hasattr(self, "reader_toolbar"):
            self.toolbar.setVisible(not self.read_mode)
            self.reader_toolbar.setVisible(self.read_mode)
        self._update_page_total()
        self._retitle()

    def _uid_of_page(self, page):
        """The identity of the page at a position, for a bookmark added there."""
        if 0 <= page < len(self.model.pages):
            return self.model.pages[page].uid
        return None

    def _page_of_uid(self, uid):
        """Where the page with this identity is *now*, or None if it has gone.

        A bookmark names a page rather than a position (D20), so following one
        is a lookup rather than an index.
        """
        for row, page in enumerate(self.model.pages):
            if page.uid == uid:
                return row
        return None

    def _refresh_outline(self):
        """Rebuild the sidebar's tree, for a load or an undo.

        A full reset, which collapses the tree -- right for a document that has
        just arrived or been restored wholesale, and wrong for a single command,
        which is why the commands update their rows themselves.
        """
        self.reader.set_outline(self.model.outline)

    def _outline_edited(self):
        """A bookmark command changed the outline.

        The outline is part of the document, so a save writes it -- but only the
        outline changed, so the reader's rendered document is still current and
        is deliberately *not* invalidated. Re-exporting 1590 pages because a
        bookmark was renamed would be a strange way to spend four seconds.
        """
        self._mark_modified()

    def _reader_selection_changed(self, has_selection: bool):
        """Copy follows the reader's selection, not the grid's, while reading."""
        if self.read_mode:
            self.act_copy.setEnabled(has_selection)

    def _on_selection_changed(self, rows: List[int]):
        has_sel = bool(rows)
        for act in (self.act_delete, self.act_duplicate, self.act_rotate_left,
                    self.act_rotate_right, self.act_export_sel, self.act_cut,
                    self.act_copy, self.act_export_sel_multi,
                    self.act_select_same_file, self.act_select_same_format,
                    self.act_crop, self.act_hide, self.act_page_size,
                    self.act_split_pages, self.act_merge_pages,
                    self.act_move_to_start, self.act_move_to_end,
                    self.act_move_to_page,
                    self.act_crop_white, self.act_export_png, self.act_export_jpg,
                    self.act_export_raster_pdf,
                    self.act_export_raster_pdf_jpg, self.act_copy_text,
                    self.act_copy_image, self.act_explode,
                    self.act_page_numbers, self.act_watermark,
                    self.act_compress):
            act.setEnabled(has_sel)
        # Reversing, swapping, unimposing and tiling all need a contiguous run.
        contiguous = self._is_contiguous(rows)
        for act in (self.act_reverse, self.act_swap, self.act_split_booklet,
                    self.act_gen_booklet, self.act_nup):
            act.setEnabled(contiguous)
        self.status_selection.setText(
            ngettext("%d page selected", "%d pages selected", len(rows)) % len(rows)
            if has_sel else "")

    #: Whether a window title should name the document and nothing else.
    #: macOS puts the application's name in the menu bar, so repeating it in
    #: every title is a Windows convention applied in the wrong place -- which
    #: is what this used to do everywhere. Windows and Linux keep it, because
    #: there it really is the convention.
    DOCUMENT_ONLY_TITLE = sys.platform == "darwin"

    @staticmethod
    def title_for(name: str, document_only: bool) -> str:
        """The window title for a document, by platform convention.

        The ``[*]`` is Qt's placeholder for the modified marker, not literal
        text: with `setWindowModified` it becomes the dot in the close button on
        macOS -- the native signal, and what Acrobat shows -- and an asterisk on
        Windows and Linux. It replaces a hand-rolled leading star, which drew
        the Windows marker on every platform.

        Taking the convention as an argument rather than reading the platform
        keeps this testable on all three from any one of them.
        """
        return f"{name}[*]" if document_only else f"{name}[*] - {APP_NAME}"

    def _retitle(self):
        name = (os.path.basename(self.current_path) if self.current_path
                else _("Untitled"))
        self.setWindowTitle(self.title_for(name, self.DOCUMENT_ONLY_TITLE))
        self.setWindowModified(self.modified)
        # The proxy icon: the little document in a macOS title bar that can be
        # dragged out or command-clicked for the folder it sits in. Ignored on
        # platforms that have no such thing. The title above still wins for the
        # text, since Qt only falls back to the path when no title is set.
        self.setWindowFilePath(self.current_path or "")
        self._update_status_path()

    def _mark_modified(self):
        self.modified = True
        self._refresh_state()

    # -- file commands -----------------------------------------------------

    def _ask_password(self, basename) -> Optional[str]:
        text, ok = QInputDialog.getText(
            self, _("Password required"),
            _("The document “{}” is locked and requires a password before "
              "it can be opened.").format(basename)
            + "\n\n"
            + _("The password will be remembered until you close PDF Arranger."),
            QLineEdit.Password,
        )
        return text if ok else None

    def _load_paths(self, paths, at: Optional[int] = None) -> int:
        """Load files and insert their pages. Returns the number of pages added."""
        added = []
        progress = None
        if len(paths) > 3:
            progress = QProgressDialog(_("Importing…"), _("Cancel"), 0, len(paths), self)
            progress.setWindowModality(Qt.WindowModal)
        try:
            for i, path in enumerate(paths):
                if progress is not None:
                    progress.setValue(i)
                    progress.setLabelText(os.path.basename(path))
                    if progress.wasCanceled():
                        break
                try:
                    added.extend(self.docs.add_file(path, ask_password=self._ask_password))
                except PDFDocError as e:
                    QMessageBox.warning(self, APP_NAME, str(e))
                except OSError as e:
                    QMessageBox.warning(self, APP_NAME, f"{path}: {e}")
                else:
                    self.import_dir = os.path.dirname(os.path.abspath(path))
        finally:
            if progress is not None:
                progress.setValue(len(paths))
        if not added:
            return 0
        self.model.undo.commit(_("Import"))
        # Inserting selects what arrived, so you can see where it landed in a
        # long document and act on it -- which is the point when importing or
        # pasting, and pointless when *opening*: every page is new, so selecting
        # every page says nothing. It also had a consequence, since a selection
        # now tells the reader where to open: a document that arrived with all
        # of itself selected could never resume where it was last read.
        whole_document = not self.model.pages
        self.model.insert_pages(len(self.model.pages) if at is None else at,
                                added, select=not whole_document)
        self._load_outline()
        if whole_document:
            self._load_viewer_prefs()
        return len(added)

    def _load_viewer_prefs(self):
        """Take the opened document's viewer preferences as this window's.

        Only when *opening*, not when importing: a file added to an existing
        document has no business rewriting how the whole thing opens.

        Saving builds a new PDF rather than editing the original, so these keys
        would otherwise be dropped by every round trip. Reading them here is
        what makes them survive one.
        """
        import pikepdf

        if not self.docs.docs:
            return
        try:
            with pikepdf.open(self.docs.docs[0].copyname,
                              password=self.docs.docs[0].password) as pdf:
                self.viewer_prefs = viewer.Preferences.read(pdf)
        except Exception:  # noqa: BLE001 - a file we cannot reopen keeps the default
            self.viewer_prefs = viewer.Preferences()

    def _load_outline(self):
        """Read the bookmarks out of the loaded files (D20).

        From the source documents, once, rather than from whatever the reader
        happens to be showing: read mode shows an in-memory export when anything
        has been edited and the file itself when nothing has, so deriving the
        outline from it would mean a different answer depending on edit state.

        Importing concatenates: a second file's bookmarks join at the root with
        no wrapper node, which is the shape a merged book already has.
        """
        import pikepdf

        from . import exporter_outlines

        opened = []
        try:
            for doc in self.docs.docs:
                try:
                    opened.append(pikepdf.open(doc.copyname))
                except Exception:  # noqa: BLE001 - a file we cannot read has no outline
                    opened.append(None)
            self.model.outline = exporter_outlines.read_outline(
                opened, self.model.pages, self.docs.source_names())
            # Collapse the repeated copies a chaptered book carries -- the
            # Handbook merged from 45 files has 45 copies of one tree. At read
            # time rather than at save, so the user sees and edits the
            # collapsed result instead of it happening invisibly underneath
            # them. Only across several files: one document repeating a subtree
            # is doing so on purpose.
            if len({p.nfile for p in self.model.pages}) > 1:
                removed = self.model.outline.deduplicate()
                if removed:
                    logging.getLogger(__name__).info(
                        "collapsed %d repeated outline copies", removed)
        finally:
            for pdf in opened:
                if pdf is not None:
                    pdf.close()
        self.model.outline_changed.emit()

    # -- recent files ------------------------------------------------------

    def _rebuild_recent_menu(self):
        """Rebuilt on aboutToShow, so it is never stale when it is looked at."""
        self.recent_menu.clear()
        paths = self.recent.paths()
        if not paths:
            empty = self.recent_menu.addAction(_("No recent files"))
            empty.setEnabled(False)
            return
        for index, path in enumerate(paths, start=1):
            # 1-9 then 0, matching the usual convention for ten entries.
            digit = index % 10
            action = self.recent_menu.addAction(
                f"&{digit}  {os.path.basename(path)}")
            action.setToolTip(path)
            action.setStatusTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_recent(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction(_("Clear Menu"), self.clear_recent)

    def open_recent(self, path: str):
        """Open a file from the list, dropping it if it has gone."""
        if not os.path.isfile(path):
            QMessageBox.warning(
                self, APP_NAME,
                _("This file is no longer there:") + f"\n{path}")
            self.recent.remove(path)
            return
        if self._confirm_discard():
            self.open_paths([path])

    def clear_recent(self):
        self.recent.clear()

    def open_paths(self, paths: List[str]) -> bool:
        """Replace the current document with ``paths``.

        Opening several files at once is a merge, so the result is marked
        modified: there is no single file it could be saved back to.
        """
        self._reset_document()
        if not self._load_paths(paths):
            return False
        # Remembered resolved, so "is this already open here?" cannot be fooled
        # by a symlink -- /tmp is one on macOS. That question is what stops a
        # document opened from the desktop being opened again by the very
        # process that was launched to open it.
        self.opened_paths = {os.path.realpath(os.path.abspath(p)) for p in paths}
        self.current_path = paths[0] if paths[0].lower().endswith(".pdf") else None
        self.modified = len(paths) > 1
        self.model.undo.clear()
        # Every file that went into this document, not just the first: opening
        # several at once is a merge, and any of them may be worth reopening.
        for path in paths:
            self.recent.add(path)
        self._refresh_state()
        # Reading is what a document is opened for; arranging is a thing you
        # then decide to do to it. Falls back to the grid on its own if the
        # document cannot be read, which set_read_mode reports.
        self.set_read_mode(True)
        return True

    # -- read mode (D14) ---------------------------------------------------

    def set_arrange_mode(self, on: bool):
        """The toggle the user sees: checked means arranging."""
        self.set_read_mode(not on)

    def set_read_mode(self, on: bool):
        """Swap the central widget between the grid and the reader.

        Entering re-exports the page list if anything changed since the last
        time (D15), so what is read always matches what would be saved.
        """
        if on and not self.model.rowCount():
            # Nothing to read, but reading is the mode this application is in:
            # an empty window should look like a reader waiting for a document,
            # not like an arranger nobody asked for. Just show it empty.
            self.reader.clear()
        elif on and self._reader_stale and not self._load_reader():
            self.act_arrange_mode.setChecked(True)
            QMessageBox.warning(self, APP_NAME, _("This document cannot be read."))
            return
        self.read_mode = on
        self.stack.setCurrentWidget(self.reader if on else self.view)
        if on:
            self._open_reader_at_selection()
        else:
            self._store_reading_position()
            # Show where you had got to, without touching the selection: it
            # means something in this mode and nothing in the reader, so a trip
            # to read something must not come back having changed it.
            self.view.scroll_to_row(self.reader.current_page())
        self.act_arrange_mode.setChecked(not on)
        self._refresh_state()
        (self.reader if on else self.view).setFocus()

    def go_to_page(self):
        """Jump to a page by number, counting from 1 as the user does."""
        total = self.reader.page_count()
        if not total:
            return
        number, ok = QInputDialog.getInt(
            self, _("Go to Page"), _("Page number:"),
            self.reader.current_page() + 1, 1, total)
        if ok:
            self.reader.go_to_page(number - 1)

    def set_continuous_scroll(self, on: bool):
        """Continuous scrolling in read mode, or one page at a time.

        Worth having as a real command rather than a preference. It began as a
        workaround: QPdfView rendered on demand and left pages blank when
        scrolling outran it. The reader's own view renders on the GUI thread
        instead, so fast scrolling stutters rather than blanks, and phase 7
        step 5 answers that properly with prefetch and placeholders. The mode
        stays because reading one page at a time is a preference in its own
        right, and it is a setting people already have.
        """
        self.settings.setValue("reader/continuous", bool(on))
        self.reader.set_continuous(bool(on))
        self.act_continuous.setChecked(bool(on))

    def set_facing_pages(self, on: bool):
        """Two pages side by side while reading, or one.

        Remembered like the scroll mode: it is a way of reading rather than a
        property of a document.
        """
        self.settings.setValue("reader/facing", bool(on))
        self.reader.set_facing(bool(on))
        self.act_facing.setChecked(bool(on))

    def _load_reader(self) -> bool:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self.reader.load(self.model.pages, self.docs.files_for_export(),
                                  self.docs.source_names(),
                                  self.docs.source_if_unmodified(self.model.pages))
        finally:
            QApplication.restoreOverrideCursor()
        self._reader_stale = not ok
        if ok:
            # Carry any active Find over, so entering read mode keeps the
            # highlights rather than silently dropping them.
            self.reader.search(self.search.phrase)
        return ok

    def _invalidate_reader(self):
        """An edit happened; the snapshot no longer matches the page list."""
        self._reader_stale = True
        if self.read_mode:
            # Showing right now, so it has to be rebuilt immediately or the
            # reader would silently disagree with the document.
            self._load_reader()

    def _update_status_pages(self):
        """How big the document is, or where you are in it while reading.

        One label, because in read mode the two say the same thing: "Page 14 of
        1590" carries the total as well. Permanent, unlike `showMessage`, which
        is what this used to be -- a three second message emitted only when the
        page *changed*, so the reader showed nothing at all until you scrolled
        and nothing again a moment later.
        """
        n = self.model.rowCount()
        if not n:
            self.status_pages.setText(_("No document"))
            return
        if self.read_mode and self.reader.page_count():
            self.status_pages.setText(self.reader.describe())
            return
        self.status_pages.setText(
            ngettext("%d page", "%d pages", n) % n)

    def _update_page_total(self):
        """"of 1590" beside the page box, so the number has a scale."""
        if not hasattr(self, "toolbar_page_total"):
            return
        total = self.reader.page_count() if self.read_mode else 0
        self.toolbar_page_total.setText(_("of {}").format(total) if total else "")

    def _reader_page_changed(self, page: int):
        # Also fires while the document is being swapped or dropped.
        if self.read_mode and self.reader.page_count():
            self._update_status_pages()
            self._update_page_total()

    def _open_reader_at_selection(self):
        """Read from the selected page, else resume where reading left off.

        A selection is something the user just did deliberately, so it wins over
        the stored position, whose job is to reopen a *document* where they left
        it. The first page of a multi-page selection: "start here" is the only
        reading of it, and a rule with no "unless" in it beats one that tries to
        be clever about what several selected pages might have meant.

        No "unless every page is selected" either, though it took a detour to
        avoid needing one: opening a document used to select the lot, which
        would have made this rule swallow the stored position entirely. That was
        a side effect of "inserting pages selects them" -- right for importing
        and pasting, meaningless for opening -- and it is fixed where it
        happens rather than worked around here.
        """
        rows = self.view.selected_rows()
        if rows:
            self.reader.go_to_page(rows[0])
        else:
            self._restore_reading_position()

    def _reading_key(self) -> Optional[str]:
        """Settings key for this document's reading position.

        Keyed on the path, so an unsaved document has nowhere to remember and
        deliberately does not try.
        """
        if not self.current_path:
            return None
        return "reading/" + os.path.normcase(os.path.abspath(self.current_path))

    def _store_reading_position(self):
        key = self._reading_key()
        if key is None or not self.reader.page_count():
            return
        self.settings.setValue(key, self.reader.current_page())

    def _restore_reading_position(self):
        key = self._reading_key()
        if key is None:
            return
        page = self.settings.value(key, 0, type=int)
        if page:
            # An edit may have removed pages since; go_to_page clamps.
            self.reader.go_to_page(page)

    def set_password(self, checked: bool):
        """Turn encryption on or off for the next save.

        A toggle, matching upstream: checking it asks for a password, unchecking
        it clears one. Cancelling the dialog leaves the action unchecked rather
        than silently on-with-no-password, which would look encrypted and not be.
        """
        if not checked:
            self.output_password = None
            self.statusBar().showMessage(_("The document will not be encrypted."), 4000)
            return
        password = dialogs.EncryptionPasswordDialog(
            self.output_password or "", self).get_value()
        if not password:
            self.act_password.setChecked(False)
            return
        self.output_password = password
        self._mark_modified()
        self.statusBar().showMessage(
            _("The document will be encrypted when it is saved."), 4000)

    def is_encrypted(self) -> bool:
        """Whether anything on screen came out of an encrypted file.

        A document's password is empty unless one was needed to open it, so
        this is also the answer to "would saving change the encryption".
        """
        return any(doc.password for doc in self.docs.docs)

    def unlock(self):
        """Drop the encryption, so the next save writes a plain document.

        The capability was already there and did nothing to announce itself:
        the password toggle starts unchecked, so opening an encrypted file and
        saving it has always produced an unencrypted one. That is a poor way
        to learn what a program has done to your document -- silently, and
        only if you thought to check.

        So this is a named command that does the same thing, out loud. PDF24
        calls the equivalent "Unlock PDF" and people look for the word; the
        toggle is only findable by somebody who already suspects encryption is
        a property of the file rather than a command.
        """
        self.act_password.setChecked(False)
        self.output_password = None
        self._mark_modified()
        self.statusBar().showMessage(
            _("The password will be removed when the document is saved."), 6000)

    def holds(self, path: str) -> bool:
        """Whether this window is already showing that file.

        The loop-breaker for documents opened from the desktop. A process
        launched to open one fills its window from the command line, so when the
        open-event arrives a moment later the window is merely *non-empty* --
        which was the condition for opening yet another window, in a process
        that then repeated the trick. Recognising the document as one we already
        hold is what stops it.
        """
        return os.path.realpath(os.path.abspath(path)) in self.opened_paths

    def new_window(self, paths=None):
        """Launch a second instance, optionally opening ``paths`` in it.

        The application is deliberately NON_UNIQUE — every launch is its own
        process, which is what makes dragging pages between windows work. So this
        starts a new process rather than constructing another MainWindow: two
        windows in one process would share the undo stack's temp directory and
        the clipboard-owner checks that tell "our" drags from someone else's.

        ``paths`` is how a document opened from the Finder while this window is
        busy gets one of its own, since macOS sends the event here rather than
        starting a second copy of the bundle.
        """
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, []
        else:
            # sys.executable is the interpreter; re-run the package entry point.
            program, arguments = sys.executable, ["-m", "pdfarranger_qt"]
        arguments = arguments + [str(path) for path in (paths or [])]
        if not QProcess.startDetached(program, arguments, os.getcwd())[0]:
            QMessageBox.warning(self, APP_NAME, _("Could not open a new window."))

    def open_file(self):
        if not self._confirm_discard():
            return
        paths, _f = QFileDialog.getOpenFileNames(
            self, _("Open"), self.import_dir, IMPORT_FILTER)
        if paths:
            self.open_paths(paths)

    def import_files(self):
        paths, _f = QFileDialog.getOpenFileNames(
            self, _("Import"), self.import_dir, IMPORT_FILTER)
        if paths:
            rows = self.view.selected_rows()
            at = rows[-1] + 1 if rows else None
            if self._load_paths(paths, at):
                self._mark_modified()

    def _import_files_at(self, paths, row):
        if self._load_paths(paths, row if row >= 0 else None):
            self._mark_modified()

    def save(self):
        if not self.current_path:
            return self.save_as()
        return self._write([self.current_path], self.model.pages,
                           outline=self.model.outline)

    def save_as(self):
        start = self.current_path or os.path.join(self.import_dir, "output.pdf")
        path, _f = QFileDialog.getSaveFileName(self, _("Save As…"), start, PDF_FILTER)
        if not path:
            return False
        if self._write([path], self.model.pages,
                       outline=self.model.outline):
            self.current_path = path
            self.recent.add(path)
            self._refresh_state()
            return True
        return False

    def export_selection(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        start = os.path.join(self.import_dir, "selection.pdf")
        path, _f = QFileDialog.getSaveFileName(self, _("Export…"), start, PDF_FILTER)
        if path:
            self._write([path], [self.model.pages[r] for r in rows],
                        mark_saved=False, outline=self.model.outline)

    def _write(self, files_out, pages, mark_saved=True, outline=None) -> bool:
        """Write ``pages`` out. ``outline`` is the document's bookmarks (D20).

        Given for a full save and for an export of a *selection* alike, so that
        a renamed bookmark exports under the name you gave it rather than the
        one it had in the source file. The difference is pruning: an export of a
        subset keeps only entries with a destination in it or a kept descendant,
        because most of the tree points at pages that are not there and would
        otherwise arrive as a crowd of empty headings.
        """
        if not pages:
            QMessageBox.information(self, APP_NAME, _("There is nothing to save."))
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # apply_hide() rewrites pages into a blank sheet plus an overlay, so
            # it must work on copies, and files_for_export() must come after it:
            # hiding can append a blank document to the set.
            pages = [p.duplicate() for p in pages]
            self.docs.apply_hide(pages)
            warning = export(
                self.docs.files_for_export(), pages, dict(self.metadata), files_out,
                preserve_first_document=self.settings.value(
                    "export/preserve-first-document", False, type=bool),
                output_password=self.output_password,
                # Lets a link into another file being saved alongside this one
                # be repointed at the page it now shares a document with.
                source_names=self.docs.source_names(),
                # The edited tree, in place of one rebuilt from the sources.
                # Without this every bookmark command is undone by the save.
                outline=outline,
                # A subset of the pages keeps only the bookmarks that still
                # have somewhere to point; a whole document keeps everything,
                # including the headings the user put there deliberately.
                prune_outline=len(pages) != len(self.model.pages),
                options=SaveOptions(
                    linearize=self._preference("export/linearize"),
                    compress=self._preference("export/compress"),
                    strip_metadata=self.act_strip_metadata.isChecked(),
                    viewer=self.viewer_prefs,
                ),
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the user
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP_NAME, _("Could not save:") + f"\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        if warning:
            QMessageBox.warning(self, APP_NAME, warning)
        if mark_saved:
            self.modified = False
            self._refresh_state()
        self.statusBar().showMessage(_("Saved") + f" {files_out[0]}", 4000)
        return True

    def close_document(self):
        if not self._confirm_discard():
            return
        self._reset_document()
        # The mode is kept. Closing a document does not change what the window
        # is for, and the reader shows empty rather than stranding anyone now
        # that the toggle stays enabled without pages.
        self.reader.clear()
        self._refresh_state()

    def _reset_document(self):
        self.model.undo.clear()
        self.model.set_pages([])
        self.renderer.invalidate()
        self.docs.reset()
        self.current_path = None
        self.modified = False
        self.metadata = {}
        self.viewer_prefs = viewer.Preferences()
        self.act_strip_metadata.setChecked(False)
        self.opened_paths = set()
        self.search.invalidate()
        # The outline goes with the document it came from. It is not derived
        # from the page list any more (D20), so emptying the pages does not
        # empty it, and closing a file used to leave its whole tree sitting in
        # the sidebar. Both callers want this: opening replaces it a moment
        # later, closing should end with nothing.
        self.model.outline = Outline()
        self.model.outline_changed.emit()

    def _confirm_discard(self) -> bool:
        if not self.modified:
            return True
        answer = QMessageBox.question(
            self, APP_NAME,
            _("This document has unsaved changes.")
            + "\n" + _("Save before continuing?"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save()
        return True

    # -- edit commands -----------------------------------------------------

    def undo(self):
        self.model.undo.undo()
        self._mark_modified()

    def redo(self):
        self.model.undo.redo()
        self._mark_modified()

    def invert_selection(self):
        selected = set(self.view.selected_rows())
        self.view.set_selected_rows(
            [r for r in range(self.model.rowCount()) if r not in selected])

    def delete_selected(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        self.model.undo.commit(_("Delete"))
        self.model.remove_rows(rows)
        self._mark_modified()

    # -- clipboard ---------------------------------------------------------

    def deselect(self):
        """Deselect: the reader's text while reading, the grid's pages otherwise.

        Selecting has a meaning in both modes, so clearing it does too.
        """
        if self.read_mode:
            self.reader.canvas.clear_selection()
            return
        self.view.clearSelection()

    def select_all(self):
        """Select All: the page's text while reading, every page otherwise."""
        if self.read_mode:
            self.reader.select_all()
            return
        self.view.selectAll()

    def copy_selected(self):
        """Copy: the reader's selected text while reading, pages otherwise.

        One command, two meanings, because the Edit menu belongs to whichever
        view is in front. Copying serialised *pages* while the user is looking
        at text they have just highlighted is the wrong answer to Ctrl+C, and
        the grid keeps its own selection while read mode is showing, so the
        action cannot simply be left to the grid.
        """
        if self.read_mode:
            return self.reader.copy()
        rows = self.view.selected_rows()
        if not rows:
            return False
        QApplication.clipboard().setText(
            clipboard.serialize([self.model.pages[r] for r in rows]))
        self._refresh_state()
        return True

    def cut_selected(self):
        rows = self.view.selected_rows()
        if not rows or not self.copy_selected():
            return
        self.model.undo.commit(_("Cut"))
        self.model.remove_rows(rows)
        self._mark_modified()

    def _paste_location(self, mode) -> int:
        """Row to paste at, following the GTK version's rules."""
        rows = self.view.selected_rows()
        n = self.model.rowCount()
        if n == 0:
            return 0
        if mode == "AFTER":
            return (rows[-1] + 1) if rows else n
        # BEFORE, ODD and EVEN all anchor on the first selected page
        return rows[0] if rows else 0

    def pages_dropped(self, payload: str, at: int):
        """Pages dragged in from another instance. Always a copy, never a move."""
        entries = clipboard.parse_records(payload)
        if not entries:
            return
        try:
            pages = self.docs.pages_from_clipboard(
                entries, ask_password=self._ask_password)
        except (PDFDocError, OSError) as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if not pages:
            return
        self.model.undo.commit(_("Paste"))
        self.model.insert_pages(max(0, at), pages)
        self._mark_modified()

    def paste(self, mode: str):
        entries = clipboard.parse(QApplication.clipboard().text())
        if not entries:
            return
        try:
            pages = self.docs.pages_from_clipboard(
                entries, ask_password=self._ask_password)
        except (PDFDocError, OSError) as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if not pages:
            return
        at = self._paste_location(mode)
        self.model.undo.commit(_("Paste"))
        if mode in ("ODD", "EVEN"):
            self.model.insert_interleaved(at, pages, after=(mode == "EVEN"))
        else:
            self.model.insert_pages(at, pages)
        self._mark_modified()

    # -- selection helpers -------------------------------------------------

    def select_parity(self, remainder: int):
        """Select pages whose 1-based number has the given parity."""
        self.view.set_selected_rows(
            [r for r in range(self.model.rowCount()) if (r + 1) % 2 == remainder])

    def select_matching(self, attribute: str):
        rows = self.view.selected_rows()
        if rows:
            self.view.set_selected_rows(self.model.rows_matching(rows, attribute))

    # -- arrange -----------------------------------------------------------

    @staticmethod
    def _is_contiguous(rows: List[int]) -> bool:
        return len(rows) > 1 and rows == list(range(rows[0], rows[-1] + 1))

    def move_to_start(self):
        """Selected pages become the first pages of the document."""
        self._move_selection_to(0)

    def move_to_end(self):
        """Selected pages become the last pages of the document."""
        self._move_selection_to(len(self.model.pages) - len(self.view.selected_rows()))

    def move_to_page(self):
        """Ask for a page number and move the selection there.

        "Becomes page N", counting from 1 as the user does: the first selected
        page ends up at that number. Not "lands in front of whatever is page N
        now", which differs by one whenever the move goes forwards and is the
        sort of off-by-one that is obvious to whoever wrote it and to nobody
        else.
        """
        rows = self.view.selected_rows()
        if not rows:
            return
        number, ok = QInputDialog.getInt(
            self, _("Move to Page"), _("Page number:"),
            rows[0] + 1, 1, len(self.model.pages))
        if ok:
            self._move_selection_to(number - 1)

    def _move_selection_to(self, position: int):
        """Move the selection so its first page becomes ``position``, 0-based.

        The point of these commands over cut and paste, on a document too long
        to scroll: they move the pages themselves, so a page keeps its identity
        and the bookmarks pointing at it come along (D20). A pasted page is a
        new page and leaves them behind dangling.
        """
        rows = self.view.selected_rows()
        if not rows:
            return
        position = max(0, min(position, len(self.model.pages) - len(rows)))
        if rows == list(range(position, position + len(rows))):
            return          # already there: not an edit
        self.model.undo.commit(_("Move"))
        self.model.move_rows_to(rows, position)
        self._mark_modified()

    def reverse_order(self):
        rows = self.view.selected_rows()
        if not self._is_contiguous(rows):
            return
        self.model.undo.commit(_("Reverse Order"))
        self.model.reverse_rows(rows)
        self._mark_modified()

    def swap_odd_even(self):
        rows = self.view.selected_rows()
        if not self._is_contiguous(rows):
            return
        self.model.undo.commit(_("Swap Odd/Even"))
        self.model.swap_odd_even(rows)
        self._mark_modified()

    def split_booklet(self):
        rows = self.view.selected_rows()
        if not self._is_contiguous(rows):
            QMessageBox.warning(
                self, APP_NAME,
                _("The page selection is not contiguous. Cannot unimpose."))
            return
        pages = [self.model.pages[r].duplicate() for r in rows]
        if not booklet.can_split(pages):
            QMessageBox.warning(self, APP_NAME, _("All pages must have the same size."))
            return
        self.model.undo.commit(_("Split Booklet"))
        self.model.replace_rows(rows, booklet.split(pages))
        self._mark_modified()

    # -- multi-file export -------------------------------------------------

    def export_multiple(self, all_pages: bool):
        pages = (self.model.pages if all_pages
                 else [self.model.pages[r] for r in self.view.selected_rows()])
        if not pages:
            return
        directory = QFileDialog.getExistingDirectory(
            self, _("Export…"), self.import_dir)
        if not directory:
            return
        stem = os.path.splitext(os.path.basename(self.current_path or "page"))[0]
        width = len(str(len(pages)))
        files_out = [os.path.join(directory, f"{stem}-{i + 1:0{width}d}.pdf")
                     for i in range(len(pages))]
        existing = [f for f in files_out if os.path.exists(f)]
        if existing and QMessageBox.question(
                self, APP_NAME,
                _("Overwrite existing files?") + f"\n{len(existing)}") != QMessageBox.Yes:
            return
        self._write(files_out, pages, mark_saved=False)

    # -- view --------------------------------------------------------------

    def _fit_reference(self):
        """The pages a fit is measured against: the selection, else everything."""
        return ([self.model.pages[r] for r in self.view.selected_rows()]
                or self.model.pages)

    def _fit_space(self):
        """Viewport size less the chrome the delegate draws around a page.

        The cell is the thumbnail plus CELL_MARGIN on every side plus the
        caption underneath, and the vertical scrollbar takes width whether or
        not it is showing at this zoom -- assume it will be.
        """
        from .view import CELL_MARGIN, LABEL_GAP

        viewport = self.view.viewport()
        caption = self.fontMetrics().height() + LABEL_GAP
        scrollbar = self.view.verticalScrollBar().sizeHint().width()
        return (viewport.width() - 2 * CELL_MARGIN - scrollbar,
                viewport.height() - 2 * CELL_MARGIN - caption)

    # -- zoom, in whichever view is showing --------------------------------

    def _zoom_by(self, factor: float):
        if self.read_mode:
            self.reader.set_zoom(self.reader.zoom() * factor)
            return
        self._set_zoom(self.model.zoom * factor)

    def reset_zoom(self):
        if self.read_mode:
            self.reader.set_zoom(1.0)
            return
        self._set_zoom(0.22)

    def zoom_fit(self, from_fit_toggle: bool = False):
        """Scale so one whole page fits in the window.

        Both dimensions, not just the width: fitting the width alone leaves a
        portrait page taller than the viewport, so you can never see a whole
        page at once -- which is the thing this is for. Fit Width is a separate
        command for when across-the-page is what you want.
        """
        if self.read_mode:
            # The reader fits against its own viewport; there is nothing here
            # to measure and no column count to pin.
            self.reader.fit_page()
            return
        pages = self._fit_reference()
        if not pages:
            return
        widest = max(p.width_in_points() for p in pages)
        tallest = max(p.height_in_points() for p in pages)
        space_w, space_h = self._fit_space()
        if widest <= 0 or tallest <= 0 or space_w <= 0 or space_h <= 0:
            return
        self._set_zoom(min(space_w / widest, space_h / tallest),
                       from_fit_toggle=from_fit_toggle)
        # Upstream's Fit One Page is this zoom *plus* a single column. Without
        # the pinning a portrait page fitted to the window height leaves room
        # for neighbours beside it, and you never see a page on its own.
        self.view.set_single_column(True)

    def zoom_fit_multiple(self):
        """Fit whole pages, as many across as the window takes.

        The same zoom as Fit One Page — upstream's two commands differ only in
        column count (`fit_one_page` pins `col_num = 1`), not in scale.
        """
        self.zoom_fit()
        self.view.set_single_column(False)

    def zoom_fit_width(self):
        """Scale so the widest page fills the window across."""
        if self.read_mode:
            self.reader.fit_width()
            return
        pages = self._fit_reference()
        if not pages:
            return
        widest = max(p.width_in_points() for p in pages)
        space_w, _space_h = self._fit_space()
        if widest > 0 and space_w > 0:
            self._set_zoom(space_w / widest)
            self.view.set_single_column(False)

    # -- page editing dialogs ----------------------------------------------

    def _selected_pages(self) -> List:
        return [self.model.pages[r] for r in self.view.selected_rows()]

    def edit_margins(self, hide: bool):
        rows = self.view.selected_rows()
        if not rows:
            return
        current = self.model.pages[rows[0]].hide if hide else self.model.pages[rows[0]].crop
        sides = dialogs.CropHideDialog(current, hide, self).get_value()
        if sides is None:
            return
        self.model.undo.commit(_("Hide Margins") if hide else _("Crop Margins"))
        if self.model.set_margins(rows, sides, hide):
            self._mark_modified()

    def page_size(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        result = dialogs.ScaleDialog(self.model.pages[rows[-1]], self).get_value()
        if result is None:
            return
        target, mode = result
        if mode == dialogs.ScaleDialog.MODE_SCALE:
            self.model.undo.commit(_("Page size"))
            if self.model.set_scale(rows, target):
                self._mark_modified()
            return
        self.model.undo.commit(_("Page size"))
        if mode == dialogs.ScaleDialog.MODE_SCALE_MARGINS:
            self.model.set_scale(rows, target)
        # Both margin modes wrap the pages onto blank sheets of the target size.
        pages = layers.center_on_blank_pages(
            [self.model.pages[r] for r in rows], target, self.docs)
        for row, page in zip(rows, pages):
            self.model.pages[row] = page
        self.model.set_pages(self.model.pages)
        self.view.set_selected_rows(rows)
        self._mark_modified()

    def insert_blank_page(self):
        rows = self.view.selected_rows()
        reference = self.model.pages[rows[-1]] if rows else (
            self.model.pages[-1] if self.model.pages else None)
        size_mm = tuple(reference.size_in_mm()) if reference else None
        size = dialogs.BlankPageDialog(size_mm, self).get_value()
        if size is None:
            return
        name, nfile = self.docs.get_blank_doc(size)
        page = Page(nfile, 1, name, size_orig=size, description=_("Blank page"))
        at = (rows[-1] + 1) if rows else self.model.rowCount()
        self.model.undo.commit(_("Insert Blank Page"))
        self.model.insert_pages(at, [page])
        self._mark_modified()

    def split_pages(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        result = dialogs.SplitDialog(self).get_value()
        if result is None:
            return
        columns, row_count = result
        self.model.undo.commit(_("Split Pages"))
        if self.model.split_pages(rows, columns, row_count):
            self._mark_modified()

    def _composite(self, entries, laypos_default):
        """Shared by Merge Pages and Paste As Overlay/Underlay."""
        rows = self.view.selected_rows()
        if not rows or not entries:
            return
        result = dialogs.MergeDialog(laypos_default, self).get_value()
        if result is None:
            return
        laypos, offset, rescale = result
        stacks = layers.layer_stacks_from_entries(entries, laypos, self.docs)
        if not stacks:
            return
        self.model.undo.commit(_("Merge Pages"))
        layers.paste_as_layer([self.model.pages[r] for r in rows], stacks,
                              laypos, offset, self.docs, rescale)
        self.model.set_pages(self.model.pages)
        self.view.set_selected_rows(rows)
        self._mark_modified()

    def merge_pages(self):
        """Composite the clipboard's pages onto the selected ones."""
        entries = clipboard.parse(QApplication.clipboard().text())
        if not entries:
            QMessageBox.information(
                self, APP_NAME,
                _("Copy the pages you want to merge in first."))
            return
        self._composite(entries, "OVERLAY")

    def paste_layer(self, laypos: str):
        entries = clipboard.parse(QApplication.clipboard().text())
        if entries:
            self._composite(entries, laypos)

    def generate_booklet(self):
        pages = self._selected_pages()
        rows = self.view.selected_rows()
        if not booklet.can_generate(pages):
            QMessageBox.warning(self, APP_NAME, _("All pages must have the same size."))
            return
        if not self._is_contiguous(rows):
            QMessageBox.warning(
                self, APP_NAME,
                _("The page selection is not contiguous. Cannot unimpose."))
            return
        self.model.undo.commit(_("Generate Booklet"))
        self.model.replace_rows(rows, booklet.generate(pages, self.docs))
        self._mark_modified()

    def pages_per_sheet(self):
        """Tile the selected pages onto sheets (N-up).

        The mirror image of Split Pages, and the same rule about sizes as
        booklet imposition: equal cells mean the pages have to be equal too.
        """
        pages = self._selected_pages()
        rows = self.view.selected_rows()
        if not nup.can_generate(pages):
            QMessageBox.warning(self, APP_NAME, _("All pages must have the same size."))
            return
        if not self._is_contiguous(rows):
            QMessageBox.warning(
                self, APP_NAME,
                _("The page selection is not contiguous."))
            return
        result = dialogs.NUpDialog(self).get_value()
        if result is None:
            return
        if result["columns"] * result["rows"] == 1:
            return  # one page per sheet is what it already is
        self.model.undo.commit(_("Pages per Sheet"))
        self.model.replace_rows(rows, nup.generate(
            pages, result["columns"], result["rows"], self.docs,
            orientation=result["orientation"], margin=result["margin"]))
        self._mark_modified()

    def add_page_numbers(self):
        """Stamp a number onto each selected page.

        Numbered in the order they are selected in, which is the order they
        are in: the number follows the arrangement, not the source document.
        """
        pages = self._selected_pages()
        if not pages:
            return
        result = dialogs.PageNumbersDialog(self).get_value()
        if result is None:
            return
        self.model.undo.commit(_("Add Page Numbers"))
        stamp.add_page_numbers(pages, self.docs, template=result["template"],
                               start=result["start"],
                               skip_first=result["skip_first"],
                               style=result["style"])
        self._stamped(pages)

    def add_watermark(self):
        """Stamp the same text across each selected page."""
        pages = self._selected_pages()
        if not pages:
            return
        result = dialogs.WatermarkDialog(self).get_value()
        if result is None or not result["text"].strip():
            return
        self.model.undo.commit(_("Add Watermark"))
        stamp.add_watermark(pages, self.docs, result["text"],
                            style=result["style"])
        self._stamped(pages)

    def compress_images(self):
        """Re-encode the images on the selected pages.

        A command rather than a save option, because it is lossy and cannot be
        reversed once written: the pages change in front of the user, and Undo
        puts the originals back. The save-time checkbox next to it does a
        different and much smaller job -- deflating streams -- which is why it
        no longer calls itself Compress.
        """
        pages = self._selected_pages()
        if not pages:
            return
        images, size = compress.survey_pages(pages, self.docs)
        if not images:
            QMessageBox.information(
                self, APP_NAME,
                _("The selected pages contain no images to compress."))
            return
        settings = dialogs.CompressDialog(images, size, self).get_value()
        if settings is None:
            return

        progress = QProgressDialog(_("Compressing…"), _("Cancel"), 0, images, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        # Reaching the maximum otherwise dismisses the dialog by itself, which
        # is exactly when the second phase starts.
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        # Shown before any work begins. A progress dialog that waits for its
        # first setValue is not drawn at all, and the scan can take minutes on
        # a large book -- which reads as the window having hung.
        progress.setValue(0)
        QApplication.processEvents()

        phase = None

        def tick(now, done, total):
            nonlocal phase
            if now != phase:
                phase = now
                progress.setLabelText({
                    compress.SCANNING: _("Measuring the images…"),
                    compress.ENCODING: _("Compressing…"),
                    compress.WRITING: _("Writing the compressed document…"),
                }[now])
                if now == compress.WRITING:
                    # One uninterruptible call into pikepdf, then another into
                    # QtPdf. Offering Cancel here would be a button that does
                    # nothing until the work it claims to stop has finished.
                    progress.setCancelButton(None)
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        # Committed before the work, because that is when the pages are still
        # the originals -- and taken back again if the work came to nothing,
        # so a cancelled compression does not leave an Undo entry that undoes
        # nothing.
        self.model.undo.commit(_("Compress Images"))
        try:
            result = compress.apply(pages, self.docs, settings, progress=tick)
        finally:
            progress.close()
        if result.stopped or not result.changed:
            self.model.undo.discard_last()
        if result.stopped:
            return

        self._stamped(pages)
        self._report_compression(result)

    def _report_compression(self, result):
        """Say what happened, in the two terms that mean anything.

        Images that could not be re-encoded are counted rather than listed:
        the reasons are technical -- JPEG 2000, ink channels, an indexed
        palette -- and what a user needs to know is that those pages were left
        exactly as they were.
        """
        untouched = result.images - result.changed
        lines = []
        if result.changed:
            lines.append(
                ngettext("%d image re-encoded", "%d images re-encoded",
                         result.changed) % result.changed)
            lines.append(
                _("%(before)s → %(after)s (%(percent)d%% smaller)")
                % {"before": compress.human_size(result.before),
                   "after": compress.human_size(result.after),
                   "percent": round(result.fraction * 100)})
        else:
            lines.append(_("Nothing was worth re-encoding."))
        if untouched:
            lines.append(
                ngettext("%d image was left as it was",
                         "%d images were left as they were",
                         untouched) % untouched)
        QMessageBox.information(self, APP_NAME, "\n".join(lines))

    def _stamped(self, pages):
        """Redraw the pages a stamp was just composited onto.

        The stamp is a layer on the existing Page objects rather than a new
        page, so nothing about the list changed and the model has no reason to
        know a repaint is due unless it is told.
        """
        self.model.touch([self.model.pages.index(page) for page in pages])
        self._mark_modified()

    def edit_properties(self):
        result = dialogs.PropertiesDialog(self.metadata, self).get_value()
        if result is None:
            return
        if result != self.metadata:
            self.metadata = result
            self._mark_modified()

    def edit_viewer_preferences(self):
        """How the saved document asks a reader to open it."""
        result = dialogs.ViewerPreferencesDialog(self.viewer_prefs, self).get_value()
        if result is None:
            return
        if result != self.viewer_prefs:
            self.viewer_prefs = result
            self._mark_modified()

    def set_strip_metadata(self, checked: bool):
        """Throw away every scrap of document information on the next save.

        A toggle rather than a command, like the password, because it is not
        something that happens now: it is a decision about what gets written.
        Both the XMP packet and the older Info dictionary go, along with the
        properties edited here -- the point is a file that says nothing about
        who made it or with what.
        """
        self._refresh_state()
        self._mark_modified()
        self.statusBar().showMessage(
            _("All metadata will be removed when the document is saved.")
            if checked else
            _("Metadata will be kept."), 4000)

    def repair_document(self):
        """Rebuild a damaged PDF, without having to arrange it first.

        Works on a file chosen here rather than on the loaded document,
        because the file worth repairing is usually one this application
        cannot open properly either.
        """
        path, _f = QFileDialog.getOpenFileName(
            self, _("Repair Document…"), self.import_dir, PDF_FILTER)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = repair.diagnose(path)
        finally:
            QApplication.restoreOverrideCursor()
        if not found.readable:
            QMessageBox.critical(
                self, APP_NAME, found.summary() + f"\n{found.detail}")
            return
        text = found.summary()
        text += "\n" + ngettext("%d page", "%d pages", found.pages) % found.pages
        if found.detail:
            text += "\n\n" + found.detail
        text += "\n\n" + _("Write a rebuilt copy?")
        if QMessageBox.question(self, APP_NAME, text) != QMessageBox.Yes:
            return
        stem = os.path.splitext(os.path.basename(path))[0]
        start = os.path.join(os.path.dirname(path), stem + "-repaired.pdf")
        out, _f = QFileDialog.getSaveFileName(
            self, _("Save Repaired Document"), start, PDF_FILTER)
        if not out:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            repair.repair(path, out,
                          linearize=self._preference("export/linearize"))
        except Exception as e:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, APP_NAME, _("Could not save:") + f"\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(_("Saved") + f" {out}", 4000)

    # -- phase 3 handlers --------------------------------------------------

    def _preference(self, key):
        default = dialogs.PREFERENCES[key]
        kind = type(default)
        if kind is bool:
            return self.settings.value(key, default, type=bool)
        if kind is int:
            return int(self.settings.value(key, default))
        return self.settings.value(key, default)

    def crop_white_borders(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        pages = [self.model.pages[r] for r in rows]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            crops = raster.white_border_crops(pages, self.docs.files_for_export())
        finally:
            QApplication.restoreOverrideCursor()
        self.model.undo.commit(_("Crop White Borders"))
        changed = False
        for row, sides in zip(rows, crops):
            if self.model.set_margins([row], sides, hide=False):
                changed = True
        if changed:
            self._mark_modified()

    def _image_targets(self, extension):
        rows = self.view.selected_rows()
        if not rows:
            return None, None
        directory = QFileDialog.getExistingDirectory(
            self, _("Export…"), self.import_dir)
        if not directory:
            return None, None
        pages = [self.model.pages[r] for r in rows]
        stem = os.path.splitext(os.path.basename(self.current_path or "page"))[0]
        width = len(str(len(pages)))
        paths = [os.path.join(directory, f"{stem}-{i + 1:0{width}d}.{extension}")
                 for i in range(len(pages))]
        return pages, paths

    def export_images(self, extension):
        pages, paths = self._image_targets(extension)
        if not pages:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            written = raster.export_images(
                pages, self.docs.files_for_export(), paths,
                ppi=self._preference("image/ppi"),
                greyscale=self._preference("image/greyscale"))
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            ngettext("%d image written", "%d images written", written) % written, 4000)

    def export_rasterised(self, image_format):
        rows = self.view.selected_rows()
        if not rows:
            return
        start = os.path.join(self.import_dir, "rasterised.pdf")
        path, _f = QFileDialog.getSaveFileName(self, _("Export…"), start, PDF_FILTER)
        if not path:
            return
        pages = [self.model.pages[r] for r in rows]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = raster.export_rasterised_pdf(
                pages, self.docs.files_for_export(), path,
                ppi=self._preference("image/ppi"),
                greyscale=self._preference("image/greyscale"),
                image_format=image_format)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            QMessageBox.warning(
                self, APP_NAME,
                _("Image files are only supported with img2pdf"))
        else:
            self.statusBar().showMessage(_("Saved") + f" {path}", 4000)

    def copy_page_text(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        text = raster.page_text([self.model.pages[rows[-1]]],
                                self.docs.files_for_export())
        if not text.strip():
            QMessageBox.information(self, APP_NAME, _("The page has no text."))
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(_("Copied"), 3000)

    def copy_page_image(self):
        """Put the page's embedded image on the clipboard."""
        rows = self.view.selected_rows()
        if not rows:
            return
        page = self.model.pages[rows[-1]]
        files = self.docs.files_for_export()
        count = raster.count_embedded_images(page, files)
        if count == 0:
            QMessageBox.information(self, APP_NAME, _("The page has no image."))
            return
        if count > 1:
            QMessageBox.information(
                self, APP_NAME,
                _('The page has several images. Use "Explode into Images" first."'))
            return
        images = raster.embedded_images(page, files)
        if not images:
            return
        QApplication.clipboard().setImage(raster.pil_to_qimage(images[0]))
        self.statusBar().showMessage(_("Copied"), 3000)

    def explode_into_images(self):
        """Replace each selected page with one page per embedded image."""
        rows = self.view.selected_rows()
        if not rows:
            return
        files = self.docs.files_for_export()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        replacements = {}
        try:
            for row in rows:
                paths = raster.explode_to_files(
                    self.model.pages[row], files, self.docs.tmp_dir)
                pages = []
                for path in paths:
                    pages.extend(self.docs.add_file(path))
                if pages:
                    replacements[row] = pages
        except (PDFDocError, OSError) as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not replacements:
            QMessageBox.information(self, APP_NAME, _("The page has no image."))
            return
        self.model.undo.commit(_("Explode into Images"))
        # Walk backwards so earlier rows keep their indices.
        for row in sorted(replacements, reverse=True):
            self.model.replace_rows([row], replacements[row])
        self._mark_modified()

    def print_document(self):
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        pages = self._selected_pages() or self.model.pages
        if not pages:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printing.prepare(printer, pages, self._preference("print/auto-rotate"),
                         doc_name=os.path.basename(self.current_path or APP_NAME))
        if QPrintDialog(printer, self).exec() != QDialog.Accepted:
            return

        # No override cursor: a wait cursor held across the spooler's own modal
        # dialog leaves the application looking dead once the job finishes.
        #
        # The progress dialog is created lazily, inside the first tick. Printers
        # such as "Microsoft Print to PDF" raise a native "Save Print Output As"
        # dialog from QPainter.begin(), i.e. at the *start* of the job -- so
        # anything shown beforehand lands on top of it and asks the user to wait
        # for a print they have not yet chosen a destination for. The first tick
        # only arrives once a page has actually been painted, which means that
        # dialog has been answered.
        progress = None

        def tick(done, total):
            nonlocal progress
            if progress is None:
                progress = QProgressDialog(_("Printing…"), _("Cancel"), 0, total, self)
                progress.setWindowModality(Qt.WindowModal)
                progress.setMinimumDuration(0)
                # Without these, reaching the maximum dismisses the dialog by
                # itself -- which is exactly when the slow part starts.
                progress.setAutoClose(False)
                progress.setAutoReset(False)
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        def finalising():
            """Painting is done; the spooler is about to do the real work."""
            if progress is not None:
                # end() is a single uninterruptible call into the platform
                # print engine and can take far longer than the painting.
                progress.setLabelText(
                    _("Finishing…") + "\n"
                    + _("The printer driver is processing the job."))
                progress.setCancelButton(None)  # end() cannot be interrupted
                QApplication.processEvents()

        try:
            printed = printing.print_pages(
                pages, self.docs.files_for_export(), printer,
                dpi=self._preference("print/dpi"),
                scale_mode=self._preference("print/scale-mode"),
                auto_rotate=self._preference("print/auto-rotate"),
                progress=tick, on_finalise=finalising)
        finally:
            if progress is not None:
                progress.close()
        self.statusBar().showMessage(
            ngettext("%d page printed", "%d pages printed", printed) % printed, 4000)

    # -- find --------------------------------------------------------------

    def find_text(self):
        phrase, ok = QInputDialog.getText(self, _("Find"), _("Find"),
                                          QLineEdit.Normal, self.search.phrase)
        if not ok or not phrase:
            return
        self._run_search(phrase)
        if self.search.matches:
            self.find_step(forward=True)

    def _run_search(self, phrase):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            matches = self.search.search(phrase, self.model.pages,
                                         self.docs.files_for_export())
        finally:
            QApplication.restoreOverrideCursor()
        count = len(matches)
        # The grid draws the hits itself, from rectangles in the edited page's
        # own points; the reader only needs the phrase, because it highlights
        # from its own search model over its own document.
        self.model.set_matches({row: self.search.rectangles(row) for row in matches})
        self.reader.search(phrase)
        self.statusBar().showMessage(
            ngettext("%d page matches", "%d pages match", count) % count, 5000)
        return matches

    def find_step(self, forward: bool):
        if not self.search.matches and self.search.phrase:
            self._run_search(self.search.phrase)
        row = self.search.next() if forward else self.search.previous()
        if row is not None:
            self.view.set_selected_rows([row])

    def find_all(self):
        if not self.search.phrase:
            self.find_text()
            return
        matches = self._run_search(self.search.phrase)
        if matches:
            self.view.set_selected_rows(matches)

    # -- preferences -------------------------------------------------------

    def _shortcut_groups(self):
        """Actions for the shortcut editor, grouped and ordered by menu.

        Walks the menu bar rather than calling findChildren(QAction), which
        returns QObject *creation* order -- so the editor used to list 73
        actions in the order they happened to be constructed, with submenu
        entries scattered through it and no way to find anything.
        """
        groups, seen = [], set()

        def collect(menu, into):
            for action in menu.actions():
                if action.isSeparator():
                    continue
                if action.menu():
                    collect(action.menu(), into)  # flatten submenus into the group
                    continue
                if not action.text():
                    continue
                name = action.objectName() or action.text()
                if name in seen:
                    continue  # the same action can appear in more than one menu
                seen.add(name)
                into.append(action)

        for top in self.menuBar().actions():
            menu = top.menu()
            if menu is None:
                continue
            actions = []
            collect(menu, actions)
            if actions:
                groups.append((menu.objectName() or top.text().replace("&", ""),
                               actions))
        return groups

    def _shortcut_actions(self):
        """Every rebindable action, flattened out of :meth:`_shortcut_groups`."""
        return [a for _title, actions in self._shortcut_groups() for a in actions]

    def edit_preferences(self):
        current = {key: self._preference(key) for key in dialogs.PREFERENCES}
        # Roles are what the groups are keyed by; the editor shows headings,
        # so they are turned back into the titles the user sees here.
        groups = [(self._menu_titles.get(role, role), actions)
                  for role, actions in self._shortcut_groups()]
        result = dialogs.PreferencesDialog(current, groups, self).get_value()
        if result is None:
            return
        shortcuts = result.pop("shortcuts", {})
        for key, value in result.items():
            self.settings.setValue(key, value)
        theme.apply(result.get("theme", theme.SYSTEM))
        # Applied immediately, like the theme beside it. Dialogs are built on
        # demand and come up in the new language by themselves; the window's
        # own chrome is what has to be told.
        if result.get("language", "") != current.get("language", ""):
            # Imported here, not at module scope: app imports this module.
            from . import i18n
            from .app import install_qt_translations

            language = i18n.setup(result.get("language") or None)
            install_qt_translations(QApplication.instance(), language)
            self.retranslate()
        for action in self._shortcut_actions():
            name = action.objectName() or action.text()
            if name in shortcuts:
                action.setShortcut(QKeySequence(shortcuts[name]))
                self.settings.setValue(f"shortcuts/{name}", shortcuts[name])

    def _restore_shortcuts(self):
        self.settings.beginGroup("shortcuts")
        saved = {key: self.settings.value(key) for key in self.settings.childKeys()}
        self.settings.endGroup()
        if not saved:
            return
        for action in self._shortcut_actions():
            name = action.objectName() or action.text()
            if name in saved and saved[name]:
                action.setShortcut(QKeySequence(saved[name]))

    def select_range(self):
        rows = dialogs.RangeSelectDialog(self.model.rowCount(), self).get_value()
        if rows:
            self.view.set_selected_rows(rows)

    def toggle_zoom_fit(self):
        """Double-click toggles fit on, and a second double-click restores."""
        if self._zoom_before_fit is None:
            self._zoom_before_fit = self.model.zoom
            self.zoom_fit(from_fit_toggle=True)
        else:
            self._set_zoom(self._zoom_before_fit, from_fit_toggle=True)
            self._zoom_before_fit = None

    def toggle_fullscreen(self, checked: bool):
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def move_pages(self, rows: List[int], dest: int, copy: bool = False):
        """Reorder after a drag, or duplicate at the drop point if ctrl was held."""
        rows = sorted(set(rows))
        if copy:
            # Nothing is removed, so the destination needs no adjustment -- and a
            # ctrl-drop in place still duplicates, unlike a move, which is a no-op.
            self.model.undo.commit(_("Copy"))
            self.model.insert_pages(
                dest, [self.model.pages[r].duplicate(new_identity=True)
                       for r in rows])
            self._mark_modified()
            return
        before = sum(1 for r in rows if r < dest)
        if rows == list(range(dest - before, dest - before + len(rows))):
            return  # a move that changes nothing is not undoable
        self.model.undo.commit(_("Move"))
        self.model.move_rows(rows, dest)
        self._mark_modified()

    def duplicate_selected(self):
        rows = self.view.selected_rows()
        if not rows:
            return
        self.model.undo.commit(_("Duplicate"))
        self.model.duplicate(rows)
        self._mark_modified()

    def rotate(self, angle: int):
        rows = self.view.selected_rows()
        if not rows:
            return
        self.model.undo.commit(_("Rotate"))
        if self.model.rotate(rows, angle):
            self._mark_modified()
        else:
            # Nothing actually turned; drop the snapshot we just pushed.
            self.model.undo.states.pop()
            self.model.undo.current -= 1

    # -- view commands -----------------------------------------------------

    def _set_zoom(self, zoom: float, from_fit_toggle: bool = False):
        if not from_fit_toggle:
            self._zoom_before_fit = None
        self.model.set_zoom(zoom)
        self.settings.setValue("view/zoom", self.model.zoom)

    def show_help(self):
        """The user guide. Kept non-modal so it can be read while working."""
        if getattr(self, "_help_dialog", None) is None:
            self._help_dialog = dialogs.HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def open_project_page(self):
        """Open the repository in the user's browser.

        A menu entry rather than only a link in the About box: the label in a
        QMessageBox is not a browser, so whether its links are followed depends
        on the style. QDesktopServices always works.
        """
        QDesktopServices.openUrl(QUrl(PROJECT_URL))

    def about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {__version_string__}</p>"
            f"<p><a href='{PROJECT_URL}'>{PROJECT_URL}</a></p>"
            "<p>A PySide6 port of "
            f"<a href='{UPSTREAM_URL}'>PDF Arranger</a>, "
            "which is itself derived from PDF-Shuffler.</p>"
            "<p>Licensed under the GNU General Public License v3 or later.</p>",
        )

    # -- drag and drop from the desktop ------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self._import_files_at(paths, -1)
            event.acceptProposedAction()

    # -- window lifetime ---------------------------------------------------

    def _restore_geometry(self):
        geom = self.settings.value("window/geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1100, 760)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        zoom = self.settings.value("view/zoom", type=float)
        if zoom:
            self.model.zoom = zoom

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        # Belt and braces, not a fix for anything observed: a normal quit does
        # flush these, because QSettings syncs from its destructor and from an
        # idle event loop. It is here for the exit that is not normal -- if the
        # process aborts during interpreter shutdown, as it does when a thread
        # outlives the window (see *Shutting down*), the destructor never runs.
        # Cheap, and the alternative is losing the window position to a crash.
        self.settings.sync()
        self.search.invalidate()
        # Before the widgets go. This used to be because QPdfView owned the
        # QPdfDocument handed to it and destroyed it on teardown; the canvas
        # only borrows it, but it does hold a reference, and closing a document
        # it still points at crashes PDFium on the next paint. The order is
        # still load-bearing, for a different reason than it was.
        self.reader.clear()
        self.reader.shutdown()
        self.renderer.shutdown()
        self.docs.cleanup()
        super().closeEvent(event)
