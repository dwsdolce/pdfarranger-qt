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

import os
import sys
from typing import List, Optional

from PySide6.QtCore import QProcess, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QDesktopServices,
                           QFontMetrics,
                           QKeySequence)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QMessageBox,
    QProgressDialog,
    QStyle,
)

from . import APP_NAME, PROJECT_URL, UPSTREAM_URL, __version_string__
from .settings import app_settings
from . import (booklet, clipboard, dialogs, layers, printing, raster,
               reader, theme)
from .core import DocumentSet, PDFDocError, Page
from .i18n import gettext_ as _
from .i18n import menu_label as _m
from .i18n import ngettext
from .export import export
from .model import PageListModel
from .recent import RecentFiles
from .render import Renderer
from .search import SearchIndex
from .view import PageView

PDF_FILTER = "PDF files (*.pdf)"
IMPORT_FILTER = "PDF and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif);;PDF files (*.pdf);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Locked by decision D1 in PORTING-NOTES.md: this scope must not change,
        # or saved geometry and zoom are silently orphaned.
        self.settings = app_settings()
        self.docs = DocumentSet()
        self.renderer = Renderer(self)
        self.model = PageListModel(self.renderer, self)
        self.model.doc_password = self._password_for
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
        self.reader.set_facing(
            self.settings.value("reader/facing", False, type=bool))
        self.reader.set_continuous(
            self.settings.value("reader/continuous", True, type=bool))
        self.setAcceptDrops(True)

        self.current_path: Optional[str] = None
        self.modified = False
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

    def _build_actions(self):
        st = QStyle.StandardPixmap
        self.act_new_window = QAction(_m("_New Window"), self)
        self.act_new_window.setShortcut(QKeySequence.New)
        self.act_new_window.triggered.connect(self.new_window)

        self.act_open = QAction(self._icon(st.SP_DialogOpenButton), _m("_Open"), self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.open_file)

        self.act_import = QAction(_m("_Import"), self)
        self.act_import.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import.setStatusTip(_("Insert pages from another PDF or an image"))
        self.act_import.triggered.connect(self.import_files)

        self.act_save = QAction(self._icon(st.SP_DialogSaveButton), _m("_Save"), self)
        self.act_save.setShortcut(QKeySequence.Save)
        self.act_save.triggered.connect(self.save)

        self.act_save_as = QAction(_m("Save _As…"), self)
        self.act_save_as.setShortcut(QKeySequence.SaveAs)
        self.act_save_as.triggered.connect(self.save_as)

        self.act_export_sel = QAction(_m("E_xport Selection to a Single File…"), self)
        self.act_export_sel.triggered.connect(self.export_selection)

        self.act_close = QAction(_m("_Close"), self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close_document)

        self.act_quit = QAction(_m("_Quit"), self)
        self.act_quit.setShortcut(QKeySequence.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_undo = QAction(self._icon(st.SP_ArrowBack), _m("_Undo"), self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.triggered.connect(self.undo)

        self.act_redo = QAction(self._icon(st.SP_ArrowForward), _m("_Redo"), self)
        self.act_redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        self.act_redo.triggered.connect(self.redo)

        self.act_select_all = QAction(_m("Select _All"), self)
        self.act_select_all.setShortcut(QKeySequence.SelectAll)
        self.act_select_all.triggered.connect(self.select_all)

        self.act_invert = QAction(_m("_Invert Selection"), self)
        self.act_invert.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_invert.triggered.connect(self.invert_selection)

        self.act_delete = QAction(self._icon(st.SP_TrashIcon), _m("_Delete"), self)
        self.act_delete.setShortcut(QKeySequence.Delete)
        self.act_delete.triggered.connect(self.delete_selected)

        self.act_duplicate = QAction(_m("_Duplicate"), self)
        self.act_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self.act_duplicate.triggered.connect(self.duplicate_selected)

        self.act_rotate_left = QAction(_m("Rotate _Left"), self)
        self.act_rotate_left.setShortcut(QKeySequence("Ctrl+L"))
        self.act_rotate_left.triggered.connect(lambda: self.rotate(-90))

        self.act_rotate_right = QAction(_m("_Rotate Right"), self)
        self.act_rotate_right.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rotate_right.triggered.connect(lambda: self.rotate(90))

        self.act_zoom_in = QAction(_m("Zoom _In"), self)
        self.act_zoom_in.setShortcut(QKeySequence.ZoomIn)
        self.act_zoom_in.triggered.connect(lambda: self._zoom_by(1.25))

        self.act_zoom_out = QAction(_m("Zoom _Out"), self)
        self.act_zoom_out.setShortcut(QKeySequence.ZoomOut)
        self.act_zoom_out.triggered.connect(lambda: self._zoom_by(0.8))

        self.act_zoom_reset = QAction(_m("_Reset Zoom"), self)
        self.act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_reset.triggered.connect(self.reset_zoom)

        self.act_help = QAction(_("User Guide"), self)
        self.act_help.setShortcut(QKeySequence.HelpContents)
        self.act_help.triggered.connect(self.show_help)

        self.act_project = QAction(_("Project on GitHub"), self)
        self.act_project.triggered.connect(self.open_project_page)

        self.act_about = QAction(_m("_About"), self)
        self.act_about.triggered.connect(self.about)

        # -- clipboard ----------------------------------------------------
        self.act_cut = QAction(_m("Cu_t"), self)
        self.act_cut.setShortcut(QKeySequence.Cut)
        self.act_cut.triggered.connect(self.cut_selected)

        self.act_copy = QAction(_m("_Copy"), self)
        self.act_copy.setShortcut(QKeySequence.Copy)
        self.act_copy.triggered.connect(self.copy_selected)

        self.act_paste = QAction(_m("Paste _After"), self)
        self.act_paste.setShortcut(QKeySequence.Paste)
        self.act_paste.triggered.connect(lambda: self.paste("AFTER"))

        self.act_paste_before = QAction(_m("Paste _Before"), self)
        self.act_paste_before.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.act_paste_before.triggered.connect(lambda: self.paste("BEFORE"))

        self.act_paste_odd = QAction(_m("Paste As _Odd Pages"), self)
        self.act_paste_odd.triggered.connect(lambda: self.paste("ODD"))

        self.act_paste_even = QAction(_m("Paste As _Even Pages"), self)
        self.act_paste_even.triggered.connect(lambda: self.paste("EVEN"))

        # -- selection ----------------------------------------------------
        self.act_deselect = QAction(_m("_Deselect All"), self)
        self.act_deselect.triggered.connect(self.deselect)

        self.act_select_odd = QAction(_m("Select _Odd Pages"), self)
        self.act_select_odd.triggered.connect(lambda: self.select_parity(1))

        self.act_select_even = QAction(_m("Select _Even Pages"), self)
        self.act_select_even.triggered.connect(lambda: self.select_parity(0))

        self.act_select_same_file = QAction(_m("All From _Same File"), self)
        self.act_select_same_file.triggered.connect(
            lambda: self.select_matching("copyname"))

        self.act_select_same_format = QAction(_m("Same Page _Format"), self)
        self.act_select_same_format.triggered.connect(
            lambda: self.select_matching("size_in_points"))

        # -- arrange ------------------------------------------------------
        self.act_reverse = QAction(_("Reverse Order"), self)
        self.act_reverse.triggered.connect(self.reverse_order)

        self.act_swap = QAction(_m("Swap Odd/Even"), self)
        self.act_swap.triggered.connect(self.swap_odd_even)

        self.act_split_booklet = QAction(_m("_Split (unimposition)"), self)
        self.act_split_booklet.triggered.connect(self.split_booklet)

        # -- export -------------------------------------------------------
        self.act_export_all_multi = QAction(
            _m("Export _All Pages to Individual Files…"), self)
        self.act_export_all_multi.triggered.connect(
            lambda: self.export_multiple(all_pages=True))

        self.act_export_sel_multi = QAction(
            _m("Export Selection to _Individual Files…"), self)
        self.act_export_sel_multi.triggered.connect(
            lambda: self.export_multiple(all_pages=False))

        # -- page editing (phase 2 dialogs) --------------------------------
        self.act_crop = QAction(_m("_Crop Margins…"), self)
        self.act_crop.setShortcut(QKeySequence("C"))
        self.act_crop.triggered.connect(lambda: self.edit_margins(hide=False))

        self.act_hide = QAction(_m("_Hide Margins…"), self)
        self.act_hide.setShortcut(QKeySequence("H"))
        self.act_hide.triggered.connect(lambda: self.edit_margins(hide=True))

        self.act_page_size = QAction(_m("_Page Size…"), self)
        self.act_page_size.setShortcut(QKeySequence("S"))
        self.act_page_size.triggered.connect(self.page_size)

        self.act_insert_blank = QAction(_m("Insert Blan_k Page…"), self)
        self.act_insert_blank.triggered.connect(self.insert_blank_page)

        self.act_split_pages = QAction(_m("_Split Pages…"), self)
        self.act_split_pages.triggered.connect(self.split_pages)

        self.act_merge_pages = QAction(_m("_Merge Pages…"), self)
        self.act_merge_pages.triggered.connect(self.merge_pages)

        self.act_gen_booklet = QAction(_m("_Generate (imposition)"), self)
        self.act_gen_booklet.triggered.connect(self.generate_booklet)

        self.act_password = QAction(_m("Pass_word"), self)
        self.act_password.setCheckable(True)
        self.act_password.triggered.connect(self.set_password)

        self.act_properties = QAction(_m("Edit _Properties"), self)
        self.act_properties.setShortcut(QKeySequence("Alt+Return"))
        self.act_properties.triggered.connect(self.edit_properties)

        # -- phase 3: raster, search, print, preferences --------------------
        self.act_crop_white = QAction(_m("Crop White Borders"), self)
        self.act_crop_white.triggered.connect(self.crop_white_borders)

        self.act_export_png = QAction(_m("Export Selection to _PNG Images…"), self)
        self.act_export_png.triggered.connect(lambda: self.export_images("png"))

        self.act_export_jpg = QAction(_m("Export Selection to _JPG Images…"), self)
        self.act_export_jpg.triggered.connect(lambda: self.export_images("jpg"))

        self.act_export_raster_pdf = QAction(
            _m("Export Selection to _Rasterized PDF (png)…"), self)
        self.act_export_raster_pdf.triggered.connect(
            lambda: self.export_rasterised("png"))

        self.act_export_raster_pdf_jpg = QAction(
            _m("Export Selection to _Rasterized PDF (jpg)…"), self)
        self.act_export_raster_pdf_jpg.triggered.connect(
            lambda: self.export_rasterised("jpg"))

        self.act_copy_text = QAction(_("Copy Text"), self)
        self.act_copy_text.triggered.connect(self.copy_page_text)

        self.act_copy_image = QAction(_m("Copy _Image"), self)
        self.act_copy_image.triggered.connect(self.copy_page_image)

        self.act_explode = QAction(_m("_Explode into Images"), self)
        self.act_explode.triggered.connect(self.explode_into_images)

        self.act_print = QAction(_m("_Print…"), self)
        self.act_print.setShortcut(QKeySequence.Print)
        self.act_print.triggered.connect(self.print_document)

        self.act_find = QAction(_m("_Find…"), self)
        self.act_find.setShortcut(QKeySequence.Find)
        self.act_find.triggered.connect(self.find_text)

        self.act_find_next = QAction(_("Find Next"), self)
        self.act_find_next.setShortcut(QKeySequence("F3"))
        self.act_find_next.triggered.connect(lambda: self.find_step(forward=True))

        self.act_find_prev = QAction(_("Find Previous"), self)
        self.act_find_prev.setShortcut(QKeySequence("Shift+F3"))
        self.act_find_prev.triggered.connect(lambda: self.find_step(forward=False))

        self.act_find_all = QAction(_("Find All"), self)
        self.act_find_all.triggered.connect(self.find_all)

        self.act_preferences = QAction(_m("Preferences"), self)
        self.act_preferences.triggered.connect(self.edit_preferences)

        self.act_select_range = QAction(_m("Select _Range"), self)
        self.act_select_range.triggered.connect(self.select_range)

        self.act_paste_overlay = QAction(_m("Paste As O_verlay…"), self)
        self.act_paste_overlay.triggered.connect(lambda: self.paste_layer("OVERLAY"))

        self.act_paste_underlay = QAction(_m("Paste As _Underlay…"), self)
        self.act_paste_underlay.triggered.connect(lambda: self.paste_layer("UNDERLAY"))

        # -- view ---------------------------------------------------------
        self.act_zoom_fit = QAction(_m("Fit _One Page"), self)
        self.act_zoom_fit.setShortcut(QKeySequence("F"))
        self.act_zoom_fit.triggered.connect(self.zoom_fit)

        self.act_zoom_fit_multi = QAction(_m("Fit _Multiple Pages"), self)
        self.act_zoom_fit_multi.setShortcut(QKeySequence("Shift+M"))
        self.act_zoom_fit_multi.triggered.connect(self.zoom_fit_multiple)

        self.act_zoom_fit_width = QAction(_("Fit Width"), self)
        self.act_zoom_fit_width.setShortcut(QKeySequence("Shift+F"))
        self.act_zoom_fit_width.triggered.connect(self.zoom_fit_width)

        # Labelled for what it switches *to*, and checked while arranging:
        # reading is the default state now, so the command a reader wants is
        # "let me rearrange this", not "let me read it".
        self.act_arrange_mode = QAction(_("Arrange Mode"), self)
        self.act_arrange_mode.setCheckable(True)
        # Unchecked from the start: an empty window is a reader waiting for a
        # document. Keeps "checked means the grid is showing" true everywhere.
        self.act_arrange_mode.setChecked(False)
        self.act_arrange_mode.setShortcut(QKeySequence("Ctrl+E"))
        self.act_arrange_mode.triggered.connect(self.set_arrange_mode)

        self.act_facing = QAction(_("Facing Pages"), self)
        self.act_facing.setCheckable(True)
        self.act_facing.setChecked(
            self.settings.value("reader/facing", False, type=bool))
        self.act_facing.triggered.connect(self.set_facing_pages)

        self.act_continuous = QAction(_("Continuous Scroll"), self)
        self.act_continuous.setCheckable(True)
        self.act_continuous.setChecked(
            self.settings.value("reader/continuous", True, type=bool))
        self.act_continuous.triggered.connect(self.set_continuous_scroll)

        # Ctrl+PageUp/Down rather than the bare keys: those belong to whichever
        # view has focus -- the grid moves the selection with them, and the
        # reader handles them itself -- and a window-wide shortcut would take
        # them away from both.
        self.act_next_page = QAction(_("Next Page"), self)
        self.act_next_page.setShortcut(QKeySequence("Ctrl+PgDown"))
        self.act_next_page.triggered.connect(lambda: self.reader.next_page())

        self.act_prev_page = QAction(_("Previous Page"), self)
        self.act_prev_page.setShortcut(QKeySequence("Ctrl+PgUp"))
        self.act_prev_page.triggered.connect(lambda: self.reader.previous_page())

        self.act_first_page = QAction(_("First Page"), self)
        self.act_first_page.triggered.connect(lambda: self.reader.first_page())

        self.act_last_page = QAction(_("Last Page"), self)
        self.act_last_page.triggered.connect(lambda: self.reader.last_page())

        self.act_go_to_page = QAction(_("Go to Page…"), self)
        self.act_go_to_page.setShortcut(QKeySequence("Ctrl+G"))
        self.act_go_to_page.triggered.connect(self.go_to_page)

        self.act_fullscreen = QAction(_("Fullscreen"), self)
        self.act_fullscreen.setShortcut(QKeySequence("F11"))
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)

    def _menu(self, parent, title):
        """Create a menu owned by the window, and add it to ``parent``.

        Never `parent.addMenu(title)`. That returns a QMenu which PySide hands
        to Python, so anything that later calls `action.menu()` -- the shortcut
        editor walking the menu bar -- takes a temporary reference to it, and
        destroying that temporary destroys the menu itself. The symptom is
        "Internal C++ object (QMenu) already deleted" from an aboutToShow
        handler, at whatever point the garbage collector happens to run.

        Constructing it with the window as parent leaves ownership in C++,
        where it belongs, and self._menus keeps a Python reference besides.
        """
        menu = QMenu(title, self)
        self._menus.append(menu)
        parent.addMenu(menu)
        return menu

    def _build_menus(self):
        # Strong references to every menu; see _menu().
        self._menus = []
        bar = self.menuBar()
        m = self._menu(bar, _m("_File"))
        m.addAction(self.act_new_window)
        m.addAction(self.act_open)
        self.recent_menu = self._menu(m, _("Open Recent"))
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        m.addAction(self.act_import)
        m.addSeparator()
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        export_menu = self._menu(m, _m("E_xport"))
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
        m.addAction(self.act_password)
        m.addSeparator()
        m.addAction(self.act_close)
        m.addAction(self.act_quit)

        # Five permanently-greyed entries with no explanation is the most
        # confusing thing in this menu: they need *pages* on the clipboard, not
        # text, and nothing on screen says so until one is there to hover.
        needs_pages = _("Needs pages copied from a document")
        for act in (self.act_paste, self.act_paste_before, self.act_paste_odd,
                    self.act_paste_even, self.act_paste_overlay,
                    self.act_paste_underlay):
            act.setStatusTip(needs_pages)
            act.setToolTip(needs_pages)

        m = self._menu(bar, _m("_Edit"))
        m.addAction(self.act_undo)
        m.addAction(self.act_redo)
        m.addSeparator()
        m.addAction(self.act_cut)
        m.addAction(self.act_copy)
        m.addAction(self.act_paste)
        paste_menu = self._menu(m, _m("Past_e Special"))
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

        m = self._menu(bar, _m("_Page"))
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
        extract_menu = self._menu(m, _m("_Extract"))
        extract_menu.addAction(self.act_copy_text)
        extract_menu.addAction(self.act_copy_image)
        m.addAction(self.act_explode)

        m = self._menu(bar, _("Arrange"))
        select_menu = self._menu(m, _m("_Select"))
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
        m.addAction(self.act_reverse)
        m.addAction(self.act_swap)
        m.addSeparator()
        m.addAction(self.act_split_pages)
        m.addAction(self.act_merge_pages)
        m.addSeparator()
        booklet_menu = self._menu(m, _m("_Booklet"))
        booklet_menu.addAction(self.act_gen_booklet)
        booklet_menu.addAction(self.act_split_booklet)

        m = self._menu(bar, _m("_View"))
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

        m = self._menu(bar, _m("_Help"))
        m.addAction(self.act_help)
        m.addSeparator()
        m.addAction(self.act_project)
        m.addAction(self.act_about)

        # Right-click on the grid gets the page-level commands.
        self.view.setContextMenuPolicy(Qt.ActionsContextMenu)
        for act in (self.act_cut, self.act_copy, self.act_paste,
                    self.act_rotate_left, self.act_rotate_right,
                    self.act_duplicate, self.act_delete):
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
        self.toolbar = self.addToolBar(_("Arrange"))
        self.toolbar.setObjectName("main-toolbar")
        self.reader_toolbar = self.addToolBar(_("Read"))
        self.reader_toolbar.setObjectName("reader-toolbar")
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
        """
        never_edits = {"File", "View", "Help"}
        writes_in_file = {self.act_import, self.act_password}
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
        self.status_pages.setText(f"{n} page{'s' if n != 1 else ''}" if has_pages else "No document")
        for act in (self.act_save, self.act_save_as, self.act_import,
                    self.act_select_all, self.act_invert, self.act_close,
                    self.act_deselect, self.act_select_odd, self.act_select_even,
                    self.act_zoom_fit, self.act_zoom_fit_multi,
                    self.act_zoom_fit_width,
                    self.act_export_all_multi,
                    self.act_insert_blank, self.act_select_range,
                    self.act_properties, self.act_print, self.act_find,
                    self.act_find_next, self.act_find_prev, self.act_find_all):
            act.setEnabled(has_pages)
        for act in (self.act_paste, self.act_paste_before,
                    self.act_paste_odd, self.act_paste_even,
                    self.act_paste_overlay, self.act_paste_underlay):
            act.setEnabled(clipboard.is_page_data(QApplication.clipboard().text()))
        self.act_undo.setEnabled(self.model.undo.can_undo)
        self.act_redo.setEnabled(self.model.undo.can_redo)
        undo_label = self.model.undo.undo_label()
        self.act_undo.setText(f"&Undo {undo_label}" if undo_label else _m("_Undo"))
        redo_label = self.model.undo.redo_label()
        self.act_redo.setText(f"&Redo {redo_label}" if redo_label else _m("_Redo"))
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
                    self.act_crop_white, self.act_export_png, self.act_export_jpg,
                    self.act_export_raster_pdf,
                    self.act_export_raster_pdf_jpg, self.act_copy_text,
                    self.act_copy_image, self.act_explode):
            act.setEnabled(has_sel)
        # Reversing, swapping and unimposing all need a contiguous run.
        contiguous = self._is_contiguous(rows)
        for act in (self.act_reverse, self.act_swap, self.act_split_booklet,
                    self.act_gen_booklet):
            act.setEnabled(contiguous)
        self.status_selection.setText(
            ngettext("%d page selected", "%d pages selected", len(rows)) % len(rows)
            if has_sel else "")

    def _retitle(self):
        name = os.path.basename(self.current_path) if self.current_path else "Untitled"
        star = "*" if self.modified else ""
        self.setWindowTitle(f"{star}{name} - {APP_NAME}")
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
        self.model.undo.commit("Import")
        self.model.insert_pages(len(self.model.pages) if at is None else at, added)
        return len(added)

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
            self._restore_reading_position()
        else:
            self._store_reading_position()
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

    def _update_page_total(self):
        """"of 1590" beside the page box, so the number has a scale."""
        if not hasattr(self, "toolbar_page_total"):
            return
        total = self.reader.page_count() if self.read_mode else 0
        self.toolbar_page_total.setText(_("of {}").format(total) if total else "")

    def _reader_page_changed(self, page: int):
        # Also fires while the document is being swapped or dropped.
        if self.read_mode and self.reader.page_count():
            self.statusBar().showMessage(self.reader.describe(), 3000)
            self._update_page_total()

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

    def new_window(self):
        """Launch a second instance.

        The application is deliberately NON_UNIQUE (§8) — every launch is its own
        process, which is what makes dragging pages between windows work. So this
        starts a new process rather than constructing another MainWindow: two
        windows in one process would share the undo stack's temp directory and
        the clipboard-owner checks that tell "our" drags from someone else's.
        """
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, []
        else:
            # sys.executable is the interpreter; re-run the package entry point.
            program, arguments = sys.executable, ["-m", "pdfarranger_qt"]
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
        return self._write([self.current_path], self.model.pages)

    def save_as(self):
        start = self.current_path or os.path.join(self.import_dir, "output.pdf")
        path, _f = QFileDialog.getSaveFileName(self, _("Save As…"), start, PDF_FILTER)
        if not path:
            return False
        if self._write([path], self.model.pages):
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
            self._write([path], [self.model.pages[r] for r in rows], mark_saved=False)

    def _write(self, files_out, pages, mark_saved=True) -> bool:
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
        self.search.invalidate()

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
        self.model.undo.commit("Delete")
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

    def edit_properties(self):
        result = dialogs.PropertiesDialog(self.metadata, self).get_value()
        if result is None:
            return
        if result != self.metadata:
            self.metadata = result
            self._mark_modified()

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
                groups.append((top.text().replace("&", ""), actions))
        return groups

    def _shortcut_actions(self):
        """Every rebindable action, flattened out of :meth:`_shortcut_groups`."""
        return [a for _title, actions in self._shortcut_groups() for a in actions]

    def edit_preferences(self):
        current = {key: self._preference(key) for key in dialogs.PREFERENCES}
        result = dialogs.PreferencesDialog(
            current, self._shortcut_groups(), self).get_value()
        if result is None:
            return
        shortcuts = result.pop("shortcuts", {})
        for key, value in result.items():
            self.settings.setValue(key, value)
        # Applied immediately; unlike Language, this needs no restart.
        theme.apply(result.get("theme", theme.SYSTEM))
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
        self.model.undo.commit("Duplicate")
        self.model.duplicate(rows)
        self._mark_modified()

    def rotate(self, angle: int):
        rows = self.view.selected_rows()
        if not rows:
            return
        self.model.undo.commit("Rotate")
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
