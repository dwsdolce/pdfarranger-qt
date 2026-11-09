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

import json
import logging
import os
import shutil
import sys
from typing import List, Optional

from PySide6.QtCore import (
    QEventLoop,
    QPointF,
    QProcess,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFontMetrics,
    QKeySequence,
)
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
    markup,
    nup,
    printing,
    raster,
    reader,
    repair,
    stamp,
    theme,
    tools,
    viewer,
)
from .core import DocumentSet, Page, PDFDocError
from .export import SaveOptions, export
from .find import Query
from .i18n import N_, ngettext
from .i18n import gettext_ as _
from .i18n import menu_label as _m
from .model import PageListModel
from .notepanel import Item as NoteItem
from .notepanel import NotePanel, when_text
from .outline import Outline
from .properties import MarkProperties, Properties
from .recent import RecentFiles
from .render import Renderer
from .search import SearchIndex
from .settings import app_settings
from .toolstrip import MarkButtons, ToolStrip
from .view import PageView

PDF_FILTER = "PDF files (*.pdf)"
IMPORT_FILTER = ("PDF and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif)"
                 ";;PDF files (*.pdf);;All files (*)")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # The settings scope is fixed permanently: moving it would silently
        # orphan saved geometry and zoom.
        self.settings = app_settings()
        self.docs = DocumentSet()
        self.renderer = Renderer(self)
        self.model = PageListModel(self.renderer, self)
        self.model.doc_password = self._password_for
        self.model.doc_files = self.docs.files_for_export
        self.model.doc_render_file = self.docs.render_file
        self.docs.set_form_values(self.model.form_values)
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
        self.reader.canvas.selection_crosses_pages.connect(
            self._selection_crosses_pages)
        # What the canvas asks when it needs to know which appearance to draw,
        # and what it tells us when one is clicked.
        self.reader.canvas.field_values = self._field_value
        self.reader.canvas.field_locked = self._field_locked
        self.reader.field_pressed.connect(self.field_pressed)
        #: The markup tools, floating over the reader rather than docked
        #: beside it: this is a page arranger and the strip is a guest.
        self.tool_strip = ToolStrip(self.reader)
        self.tool_strip.hide()
        #: True while the strip is driving the canvas, so that the canvas's
        #: report of the change is not taken for a choice of its own.
        self._arming = False
        self.tool_strip.armed_changed.connect(self._tool_armed)
        self.reader.canvas.tool_changed.connect(self._canvas_tool_changed)
        # The strip sits over the reader, which scrolls by blitting, so it
        # has to be told to redraw itself when the page under it moves.
        self.reader.canvas.verticalScrollBar().valueChanged.connect(
            lambda _v: self.tool_strip.isVisible() and self.tool_strip.refresh())
        self.tool_strip.moved.connect(
            lambda where: self.settings.setValue(
                "reader/markup-tools-at", where))
        self.reader.mark_drawn.connect(self.mark_drawn)
        self.reader.marks_drawn.connect(self.marks_drawn)
        self.reader.mark_reshaped.connect(self.mark_reshaped)
        self.reader.mark_moved.connect(self.mark_moved)
        self.reader.mark_resized.connect(self.mark_resized)
        self.reader.mark_deleted.connect(self.mark_deleted)
        self.reader.mark_is_the_default.connect(self.mark_is_the_default)
        self.reader.note_wanted.connect(self.open_note)
        self.reader.reply_wanted.connect(self.reply_to)
        self.reader.status_wanted.connect(self.set_mark_status)
        self.reader.properties_wanted.connect(self.show_mark_properties)
        #: The thread on the selected mark, shown over the page. A child of
        #: the viewport for the reason the bar is: it is placed from the
        #: rectangles the canvas reports, and those are viewport ones.
        self.note_panel = NotePanel(self.reader.canvas.viewport())
        self.note_panel.posted.connect(self.note_posted)
        self.note_panel.placed.connect(self.note_panel_placed)
        self.note_panel.closed.connect(self.note_shut)
        self.note_panel.menu_wanted.connect(self.note_menu)
        # The box at the end of a thread asks for exactly what the menu's
        # *Reply* asks for, so it is answered in one place.
        self.note_panel.reply_here.connect(self._reply_to_the_open_thread)
        #: What that panel is showing: ``(page, [mark, reply, reply, ...])``,
        #: in the order the panel lists them, so a post knows which mark it
        #: belongs to.
        self._noted = None
        # So a gesture in flight is drawn in the colour it will be kept in:
        # the preview is the mark, before it is a mark.
        self.reader.canvas.set_mark_styles(self.MARK_KINDS)
        self.reader.canvas.mark_colour = self._colour_for_canvas_tool
        self.reader.canvas.note_icon = lambda: self._icon_for("comment")
        #: What you can do to the mark that is selected. A child of the
        #: viewport rather than of the reader, because it is placed from the
        #: rectangles the canvas reports and those are in viewport
        #: coordinates. Comment does not act yet; it is turned on by the
        #: step that builds it.
        self.mark_buttons = MarkButtons(self.reader.canvas.viewport())
        self.reader.canvas.set_mark_buttons(self.mark_buttons)
        self.mark_buttons.recoloured.connect(self.mark_recoloured)
        self.mark_buttons.faded.connect(self.mark_faded)
        self.mark_buttons.deleted.connect(self.delete_selected_mark)
        self.mark_buttons.commented.connect(self.comment_on_selected_mark)
        #: What the next mark will be made in, once the tail's swatch has
        #: been used. None until then, so each tool keeps the colour readers
        #: expect of it rather than everything starting out yellow.
        self.armed_colour = None
        #: The colour each *tool* makes its marks in now. One per tool, as
        #: Reader keeps them: picking a colour with Underline armed does
        #: not recolour the next highlight. Seeded from what the tool
        #: declares -- `tools.Tool.colour` -- the first time it is asked.
        self._colours: dict = {}
        #: And how solid each tool's marks are, the same way. A single
        #: value served every tool once, so fading a highlight set the
        #: next underline's opacity too.
        self._opacities: dict = {}
        #: And the style, for a tool whose kind has more than one. An
        #: underline starts straight; *Make Properties Default* on a
        #: squiggly is how that moves.
        self._styles: dict = {}
        #: And the icon a comment is made with. One more appearance
        #: attribute the properties form can send over as a default.
        self._icons: dict = {}
        self._load_tool_defaults()
        self.armed_opacity = None
        self.tool_strip.colour_armed.connect(self._colour_armed)
        self.tool_strip.opacity_armed.connect(self._opacity_armed)
        self.reader.canvas.mark_selected.connect(self._selected_mark_changed)
        self.reader.canvas.marks = self._marks_on_page
        self.reader.field_edited.connect(self.field_edited)
        self.reader.field_refused.connect(self.field_refused)
        # The sidebar shows the document's outline, not the reader document's
        #, so the window keeps the two in step.
        self.model.outline_changed.connect(self._refresh_outline)
        self.reader.page_of_uid = self._page_of_uid
        self.reader.uid_of_page = self._uid_of_page
        # Bookmark commands live on the tree, undo lives here. The reader says
        # what it is about to do and the window records it, so a bookmark edit
        # and a page edit come off one stack.
        self.reader.outline_edit_begun.connect(self.model.undo.commit)
        self.reader.outline_edited.connect(self._outline_edited)
        self.reader.set_outline_width(
            self.settings.value("reader/outline-width",
                                self.reader.OUTLINE_DEFAULT, type=int))
        self.reader.set_facing(
            self.settings.value("reader/facing", False, type=bool))
        self.reader.set_continuous(
            self.settings.value("reader/continuous", True, type=bool))
        self.setAcceptDrops(True)

        self.current_path: Optional[str] = None
        self.modified = False
        #: True when the panel was opened for a document that has no bookmarks.
        #: Lasts until another document is loaded: the panel follows the
        #: document, and this is the exception you asked for by hand.
        self._outline_asked_for = False
        #: The files this window was opened from, resolved. See `holds`.
        self.opened_paths: set = set()
        #: Document properties, merged with the sources' own metadata on export.
        self.metadata: dict = {}
        #: Text search; rebuilt lazily whenever the document changes.
        self.search = SearchIndex()
        #: The find dialog, built the first time it is asked for.
        self._find_dialog = None
        #: Which hit is current, as an index into the search index's
        #: hits. Lives here rather than in the dialog: Find Next keeps
        #: working when the dialog is closed, and one cursor has to serve
        #: both the reader and the grid.
        self._find_cursor = -1
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
        #: Set while an edit is one the reader can already show without being
        #: rebuilt. See `_field_filled`.
        self._reader_keeps_showing = False
        #: The undo depth just after a note was placed, or None. What makes a
        #: note abandoned with nothing in it leave no trace: the entry pushed
        #: for placing it is taken back only if it is still the top of the
        #: stack, so a command run from the keyboard while the editor was open
        #: cannot be the one discarded instead.
        self._placed_note = None
        #: A mark that **is** its note, made but not yet written: the
        #: thread window is open on it and nothing has been posted. If the
        #: window is cancelled or shut while it is still empty there was
        #: no comment, so the mark goes and the undo entry with it.
        #: ``(index, mark, undo point)``.
        self._awaiting_text = None
        #: Zoom to restore when double-click toggles fit back off.
        self._zoom_before_fit: Optional[float] = None

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
        # And so is the cursor, and so is whatever the dialog is listing.
        self.model.contents_changed.connect(self._find_invalidated)
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
        # The strip's tools are not built through `_action`, so they carry no
        # msgid property and the sweep above does not reach them. It labels
        # itself from its own declaration instead.
        self.tool_strip.retranslate()
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
        # is a *new* page with a new uid, so its bookmarks stay behind
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

        # The markup tools live in a floating strip of their own (4.2), not
        # in a menu: a flat list cannot say which tool is armed, what each one
        # carries, or group twenty of them. The strip is summoned from here.
        self.act_markup_tools = self._action("Markup _Tools")
        self.act_markup_tools.setCheckable(True)
        self.act_markup_tools.setChecked(
            self.settings.value("reader/markup-tools", False, type=bool))
        self.act_markup_tools.toggled.connect(self.show_markup_tools)

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

        self.act_bookmarks = self._action("Bookmarks", mnemonic=False)
        self.act_bookmarks.setCheckable(True)
        self.act_bookmarks.setShortcut(QKeySequence("F4"))
        self.act_bookmarks.setToolTip(_("Show or hide the bookmarks panel"))
        self.act_bookmarks.setChecked(
            self.settings.value("reader/outline", True, type=bool))
        self.act_bookmarks.triggered.connect(self.set_bookmarks_visible)

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

    #: Which annotation each markup tool writes, and the colour it starts
    #: out in. The colours are the ones every reader uses for these marks, so
    #: a document marked here looks like one marked anywhere else -- but only
    #: until the swatch in the strip's tail is used, after which there is one
    #: current colour and it colours whatever is made next, of any kind.
    #: Reader works the same way: a single colour at the foot of its tool
    #: list, not a palette per tool.
    #: Which annotation each markup tool writes. The colour each starts in
    #: is `markup.DEFAULT_COLOURS`, read off Reader with its settings reset
    #: -- it is not written here, because a colour written in two places is
    #: a colour that will disagree with itself.
    #:
    #: **Underline writes the straight style.** The other is the same tool
    #: writing `/Squiggly`, reached from the mark's properties form.
    MARK_KINDS = {
        "highlight": markup.HIGHLIGHT,
        "strikeout": markup.STRIKEOUT,
        "underline": markup.UNDERLINE,
        "note": markup.TEXT,
        # **A gesture, not a tool.** The right-click menu's *Add note to
        # text* is the comment tool marking a run of words instead of
        # placing an icon, so it writes a `/Highlight` and takes the
        # comment tool's colour. It was a tool in the strip for two days
        # and never should have been.
        markup.NOTE_ON_TEXT: markup.HIGHLIGHT,
        "stamp": markup.STAMP,
        # *Replace Selected Text* writes a strikeout and a caret, joined as
        # one mark; the strikeout is the kind named here because it is what
        # stands for the pair, and `_place_mark` adds its caret.
        "replace": markup.STRIKEOUT,
        # *Insert Text*: a caret on its own, between two characters.
        "insert": markup.CARET,
    }

    #: The gestures above that are not tools, and the tool each acts as --
    #: and the one tool that borrows another's answers. The two comment
    #: tools keep one set of properties between them: colour, opacity, the
    #: icon and the note are the same question whichever makes the mark,
    #: and two comment colours quietly drifting apart is the kind of thing
    #: nobody reports and everybody notices. What differs is the subtype,
    #: which is not a property anyone sets.
    GESTURE_TOOLS = {markup.NOTE_ON_TEXT: "comment",
                     "scalable_comment": "comment"}

    #: The marks that **are** their note. Cancelling the box, or leaving
    #: it empty, means there was no comment -- so the mark goes rather
    #: than staying behind with nothing to say. A highlight, an underline
    #: or a cross-out stands on its own and keeps its place.
    #:
    #: By the canvas's names, because that is what reports a finished
    #: gesture -- `"note"` is the comment tool placing its icon. The caret
    #: pair is here too: the replacement wording is the point of it.
    REQUIRES_TEXT = (markup.NOTE_ON_TEXT, "note", "stamp", "replace",
                     "insert")

    #: Strip tool -> the canvas's own name for it. Only the tools that have
    #: been built appear: the strip offers twenty and the canvas implements
    #: four, because a tool arrives with its gesture one at a time.
    CANVAS_TOOLS = {
        "highlight": "highlight",
        "strikethrough": "strikeout",
        "underline": "underline",
        "comment": "note",
        "scalable_comment": "stamp",
        "replace_text": "replace",
        "insert_text": "insert",
        "draw": "draw",
    }

    #: And back again, for the places that start from the canvas's name --
    #: a finished gesture, or a preview asking what colour it should be.
    CANVAS_TO_STRIP = {canvas: strip for strip, canvas in CANVAS_TOOLS.items()}

    def _tool_armed(self, name: str) -> None:
        """The strip armed a tool, so the pointer changes meaning.

        A tool nobody has built yet leaves the canvas reading, which is what
        it was doing before. The strip still shows it armed -- the mode is
        set, there is simply nothing behind it.

        The canvas's answer is ignored while this runs, because the canvas
        cannot distinguish "the strip chose me" from "I disarmed myself". It
        reports SELECT for both, and without this an unbuilt tool armed the
        strip, sent the canvas to SELECT, and was told by the canvas to go
        back to the pointer -- so the tool you picked did not stay picked.
        """
        from .canvas import PageCanvas

        self._arming = True
        try:
            self.reader.canvas.set_tool(
                self.CANVAS_TOOLS.get(name, PageCanvas.SELECT))
        finally:
            self._arming = False
        # The swatch follows the tool, because each tool keeps a colour of
        # its own and the swatch has to show what the next mark will be.
        if name in self.MARK_KINDS or name in self.CANVAS_TOOLS:
            self.tool_strip.arm_colour(self.colour_for(name))
        # **With text already selected, arming the tool is the gesture.**
        # Reader marks the selection the moment you choose the tool; there
        # is no second action to commit it, and waiting for one left the
        # words sitting there in the tool's colour with no way to apply it.
        # On one page only: a selection across a page break cannot be
        # marked, and `mark_the_selection` refuses it. The tool stays armed
        # afterwards, for the next run of words.
        canvas = self.reader.canvas
        if name == "insert_text" and canvas.has_selection():
            # *Insert Text* takes a point, never a range, so words already
            # selected are let go rather than marked: the caret is placed
            # by the next click.
            canvas.clear_selection()
        elif canvas.has_selection() and canvas.marks_text():
            # **The comment tool makes two kinds**, and reaches this the
            # same way the highlighter does: it marks text, so a selection
            # already made is marked at once and the canvas names the
            # gesture that writes it. A point has to be the other way
            # round -- there is nothing to mark until the click says where.
            canvas.mark_the_selection(canvas.tool())

    def _canvas_tool_changed(self, tool: str) -> None:
        """Keep the strip showing what the pointer is actually doing.

        The canvas disarms itself when Escape is pressed, so the strip cannot
        be the only place the choice lives. This is for *that* -- a change the
        canvas made on its own -- and `_tool_armed` shuts it off for the
        changes the strip asked for, which would otherwise come straight back
        as an instruction to undo them.
        """
        if self._arming:
            return
        for armed, canvas_name in self.CANVAS_TOOLS.items():
            if canvas_name == tool:
                self.tool_strip.arm(armed)
                return
        self.tool_strip.arm(tools.DEFAULT)

    def _marks_on_page(self, index: int):
        """The marks on a page of the *reader*, for it to draw.

        By index, because that is what the canvas has; the model keeps them by
        page uid, which is what survives a reorder.
        """
        if not 0 <= index < len(self.model.pages):
            return ()
        return self.model.annotations.for_page(self.model.pages[index].uid)

    def mark_drawn(self, tool: str, index: int, rects) -> None:
        """A markup gesture finished on one page: keep it."""
        self.marks_drawn(tool, [(index, rects)])

    def marks_drawn(self, tool: str, pages) -> None:
        """A markup gesture finished, over however many pages it covered.

        ``pages`` is ``[(index, rects), ...]``, the rectangles in each
        page's own space, so nothing here has to know about zoom, scroll
        or rotation.

        **One undo step for the gesture, not one per page.** Text is marked
        one page at a time, so a gesture reaching here covers one page; the
        list stays a list so that anything which ever covers more is still
        one action to take back, as it was one action to make.
        """
        subtype = self.MARK_KINDS.get(tool)
        if subtype is None:
            return
        # **The style is the subtype**, so a tool told to default to
        # squiggly makes a different annotation, not a differently drawn
        # one. Straight is where an underline starts, not where it is
        # pinned.
        style = self._styles.get(self.CANVAS_TO_STRIP.get(tool, tool))
        if style in markup.UNDERLINE_STYLES and (
                subtype in markup.UNDERLINE_STYLES.values()):
            subtype = markup.UNDERLINE_STYLES[style]
        wanted = [(index, rects) for index, rects in pages
                  if rects and 0 <= index < len(self.model.pages)]
        if not wanted:
            return
        self.model.undo.commit(_("Add Mark"))
        for index, rects in wanted:
            self._place_mark(tool, subtype, index, rects)
        self._mark_added()
        # The note tools open their editor on the last mark made, which for
        # a gesture over several pages is the one on the last page.
        index = wanted[-1][0]
        made = self._marks_on_page(index)
        if tool in self.REQUIRES_TEXT:
            # **The note window, which is the one every other mark uses.**
            # Author, time, Cancel and Post -- not the bare text box on the
            # page, which is what a comment opened before and was the only
            # mark in the application that did. Straight into it, because a
            # comment with nothing in it is not a mark anyone meant to
            # make, and asking for the words afterwards would be a second
            # gesture for one action.
            self._awaiting_text = (index, made[-1], self.model.undo.current)
            # **Held, before its window opens.** The thread belongs to the
            # selected mark and closes when the selection moves off it, so
            # a mark nobody has hold of would leave a window that clicking
            # away could not shut -- and clicking the icon again would find
            # it already showing and open no editor.
            #
            # The last mark made is a pair's caret, where its note goes;
            # what is held is the strikeout that stands for the pair.
            canvas = self.reader.canvas
            canvas.select_mark((index, canvas.head_of(index, made[-1])))
            self.open_note(index, made[-1])

    def _place_mark(self, tool: str, subtype: str, index: int, rects) -> None:
        """Add one mark to one page. The caller owns the undo step."""
        colour = self._colour_for_canvas_tool(tool)
        page = self.model.pages[index]
        rect = markup.bounding_rect(rects)
        quads = rects if subtype in markup.QUADDED else ()
        # Asked once, by the tool that is making the mark. Both comment
        # tools keep one icon between them, so a literal "comment" here
        # answers the same -- until the day it does not.
        chosen = self._icon_for(self.CANVAS_TO_STRIP.get(tool, tool))
        if subtype == markup.TEXT:
            # A note is placed, not sized: its icon is the same size wherever
            # it lands. The canvas has already chosen the corner, because
            # which corner the pointer ends up on is decided by the page's
            # turn and the turn is the canvas's business (`icon_rect`). This
            # only guarantees the size, and on a box that already has it the
            # call changes nothing -- so a caller that sends a bare point
            # still gets a note somebody can click.
            #
            # Divided by the page's resize, because the size that matters is
            # the icon's on the page a reader draws and the mark is kept in
            # the source page's space. Normalising to a flat 20 here
            # instead quietly halved a note placed on a page shown at half
            # size.
            # **Only a bare point.** The canvas sizes the box itself,
            # because the corner that lands under the pointer depends on
            # how the page is turned and only the canvas knows that.
            # Rebuilding it here from the source-space left and top put
            # the icon back where the turn had moved it.
            if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
                scale = page.scale if page.scale else 1.0
                wide, tall = markup.icon_size(chosen)
                rect = markup.note_rect(rect[0], rect[3],
                                        wide / scale, tall / scale)
        if subtype == markup.STAMP:
            # **Around the point, not down from it.** A stamp is page
            # content and is placed by its centre: the fit to `/Rect` holds
            # the artwork's centre whatever the angle, so a stamp anchored
            # by a corner would walk across the page the first time it was
            # turned. The comment mark above is the other way round, and
            # has to be:
            # NoZoom fixes its upper left.
            page_scale = page.scale if page.scale else 1.0
            centre = (rect[0], rect[3])
            rect = markup.stamp_rect(centre[0], centre[1], chosen,
                                     1.0 / page_scale)
        if subtype == markup.CARET:
            # *Insert Text*: the canvas sends the character beside the gap,
            # cut off at the gap, and the caret is sized from its height as
            # a Replace caret is from its run's.
            rect = markup.caret_rect(rects[-1])
        # **Which tool, not which subtype.** Two things make a
        # `/Highlight` -- the highlight tool, and the comment tool over a
        # run of words -- and what tells them apart in the file is the
        # subject and the intent.
        subject, intent = self._names_written_by(tool)
        opacity = self._opacity_for_canvas_tool(tool)
        made = self.model.annotations.add(markup.Annotation(
            subtype, page.uid, rect, colour=colour, quads=quads,
            opacity=opacity,
            subject=subject or None, intent=intent or None,
            icon=chosen,
            author=markup.default_author()))
        if tool == "replace" and quads:
            # **And its caret**, at the end of the run, in the same colour
            # and opacity. Added after the strikeout, which is the order
            # Acrobat writes the pair in; the strikeout names it, and that
            # is what makes the two one mark rather than a reply.
            subject, intent = markup.REPLACE_CARET
            caret = self.model.annotations.add(markup.Annotation(
                markup.CARET, page.uid, markup.caret_rect(quads[-1]),
                colour=colour, opacity=opacity, subject=subject,
                intent=intent, author=markup.default_author()))
            made.irt = caret.name
            made.group = True

    @staticmethod
    def _names_written_by(tool: str):
        """``(subject, intent)`` for a gesture, or ``("", "")`` for a tool
        whose subtype already says what it is."""
        if tool == markup.NOTE_ON_TEXT:
            return markup.COMMENT_ON_TEXT
        if tool == "replace":
            return markup.REPLACE_STRIKE
        return "", ""

    def colour_for(self, tool: str):
        """What a mark made with ``tool`` would be coloured now.

        **Per tool, not per kind.** The colour last chosen for that tool,
        else the one its declaration names -- and one subtype can be two
        tools with two colours, which is why the question is asked this
        way: `/Caret` starts Light Red for *Replace selected text* and
        Fuchsia for *Insert text*.
        """
        tool = self.GESTURE_TOOLS.get(tool, tool)
        if tool in self._colours:
            return self._colours[tool]
        try:
            named = tools.by_name(tool).colour
        except KeyError:
            return markup.DEFAULT_COLOUR
        return markup.swatch(named) if named else markup.DEFAULT_COLOUR

    #: Where the per-tool defaults are kept between runs. **Internal**:
    #: this is the application's own state, not something a user opens and
    #: edits, so the shape and the keys are ours to change. The keys are
    #: the `tools.py` identifiers, which exist for exactly this sort of
    #: thing and reach no screen.
    DEFAULTS_SETTING = "markup/tool-defaults"

    def _load_tool_defaults(self) -> None:
        """Read back the appearance each tool was last told to use.

        A default outlives the session: making a squiggly the default and
        restarting still gives a squiggly. Anything
        unreadable is dropped rather than raised on -- a preference file
        is not worth refusing to start over.
        """
        try:
            stored = json.loads(self.settings.value(
                self.DEFAULTS_SETTING, "", type=str) or "{}")
            self._colours.update(
                {k: tuple(v) for k, v in stored.get("colours", {}).items()})
            self._opacities.update(
                {k: float(v) for k, v in stored.get("opacities", {}).items()})
            self._styles.update(
                {k: str(v) for k, v in stored.get("styles", {}).items()})
            self._icons.update(
                {k: str(v) for k, v in stored.get("icons", {}).items()})
        except Exception:  # noqa: BLE001 - a bad preference is no preference
            logging.getLogger(__name__).debug(
                "tool defaults could not be read", exc_info=True)

    def _remember_tool_defaults(self) -> None:
        """Keep them for the next run. Called whenever one changes."""
        self.settings.setValue(self.DEFAULTS_SETTING, json.dumps({
            "colours": {k: list(v) for k, v in self._colours.items()},
            "opacities": dict(self._opacities),
            "styles": dict(self._styles),
            "icons": dict(self._icons),
        }))

    def _icon_for(self, tool: str) -> str:
        """The `/Name` a comment made with ``tool`` would carry now."""
        return self._icons.get(self.GESTURE_TOOLS.get(tool, tool),
                               markup.DEFAULT_ICON)

    def opacity_for(self, tool: str):
        """How solid a mark made with ``tool`` would be now.

        None where the tool has never been told, which leaves the kind to
        answer -- a highlight is drawn at 0.4 and the rest at 1.
        """
        return self._opacities.get(self.GESTURE_TOOLS.get(tool, tool))

    def _opacity_for_canvas_tool(self, tool: str):
        """The same question, asked with the canvas's name for a tool."""
        return self.opacity_for(self.CANVAS_TO_STRIP.get(tool, tool))

    def _colour_for_canvas_tool(self, tool: str):
        """The same question, asked with the canvas's name for a tool."""
        return self.colour_for(self.CANVAS_TO_STRIP.get(tool, tool))

    def _colour_armed(self, colour) -> None:
        """The tail's swatch was used.

        It does two jobs, and which one depends on whether a mark is picked.
        With one selected it changes *that* mark, which is what Reader does
        and is why the swatch is shown with the pointer armed at all. With
        nothing selected it arms the colour the next mark will be made in.
        """
        if self.reader.canvas.selected_mark() is not None:
            self._change_mark(colour=tuple(colour))
            return
        self.armed_colour = tuple(colour)
        # And against the armed tool, so the swatch and the mark it makes
        # cannot disagree -- which is what sent a new underline out in the
        # tool's own colour while the swatch showed another.
        self._colours[self.tool_strip.armed()] = tuple(colour)
        self._remember_tool_defaults()

    def _opacity_armed(self, opacity: float) -> None:
        if self.reader.canvas.selected_mark() is not None:
            self._change_mark(opacity=float(opacity))
            return
        self.armed_opacity = float(opacity)
        self._opacities[self.tool_strip.armed()] = float(opacity)
        self._remember_tool_defaults()

    def _selected_mark_changed(self, _selected: bool) -> None:
        """Tell the buttons, and the tail's swatch, what is selected.

        The swatch follows the selection so that the tick in the palette
        marks the colour of the mark you picked. Letting go puts back the
        colour armed for the next one.

        **And the note window goes with the selection.** It belongs to the
        mark it was opened on, so picking up another mark or clicking the
        bare page lets go of that one and takes the thread with it. Left
        open it describes a mark nobody has hold of any more.

        **And the new mark's note opens, whatever kind of mark it is.** A
        highlight somebody wrote about shows what they said, exactly as an
        icon does -- one rule, which is: pick up a mark, see what was said
        about it. An icon also asks through `note_wanted`, which arrives
        straight after this and finds the window already showing.
        """
        found = self.reader.canvas.selected_mark()
        # A pair's note is on its caret, so that is what the window holds.
        said = (None if found is None
                else self.reader.canvas.note_bearer(*found))
        if self._noted is not None and (
                found is None or said is not self._noted[1][0]):
            self.note_panel.hide()
            self._noted = None
        if found is not None and self.reader.canvas.carries_note(*found):
            self.open_note(*found)
        if found is None:
            self.tool_strip.unfollow()
            return
        mark = found[1]
        self.tool_strip.follow(
            mark.colour,
            markup.solidity(mark) if isinstance(mark, markup.Annotation)
            else mark.opacity)
        self.mark_buttons.set_mark(
            mark.colour,
            markup.solidity(mark) if isinstance(mark, markup.Annotation)
            else mark.opacity,
            bool(getattr(mark, "locked", False)))

    def mark_recoloured(self, colour) -> None:
        """A colour was picked for the selected mark."""
        self._change_mark(colour=tuple(colour))

    def mark_faded(self, opacity: float) -> None:
        """An opacity was set for the selected mark."""
        self._change_mark(opacity=float(opacity))

    def mark_resized(self, index: int, mark, quads) -> None:
        """A grip moved, so the mark covers a different run of text.

        The same route a colour change takes: a mark of the user's is
        altered where it lives, one the file brought is changed by an
        overlay beside its own dictionary. Geometry is no different from
        colour in that respect -- `/QuadPoints` and `/Rect` are rewritten
        and the appearance dropped, and the comment thread hanging off the
        mark is untouched, because it is the same mark.
        """
        if not quads or not 0 <= index < len(self.model.pages):
            return
        if getattr(mark, "locked", False):
            return
        # A pair's caret follows the end of the run, as one mark.
        caret = self.reader.canvas.caret_of(index, mark)
        if isinstance(mark, markup.Annotation):
            self._commit_mark_change(_("Resize Mark"), index, mark)
            mark.quads = tuple(tuple(q) for q in quads)
            mark.rect = markup.bounding_rect(mark.quads)
            mark.touch()
            if caret is not None:
                caret.rect = markup.caret_rect(mark.quads[-1])
                caret.touch()
            self._after_mark_change(index)
            return
        uid = self.model.pages[index].uid
        self._commit_mark_change(_("Resize Mark"), index, mark)
        boxes = tuple(tuple(q) for q in quads)
        self.model.mark_edits.change(uid, mark.index, quads=boxes)
        if caret is not None:
            moved = markup.caret_rect(boxes[-1])
            self.model.mark_edits.change(uid, caret.index, rect=moved)
            caret.rect = moved
        # Back into the shape a `Mark` holds: `/QuadPoints` corner groups,
        # not the rectangles the rest of this works in. Assigning the
        # rectangles made `boxes()` fall through to `/Rect`, so a resized
        # mark reported one box where it had a run -- and its grips, its
        # outline and its badge all followed that wrong answer.
        mark.quads = tuple(tuple(markup._quad_points(q)) for q in boxes)
        mark.rect = markup.bounding_rect(boxes)
        self._after_mark_change(index, uid)

    def mark_reshaped(self, index: int, mark, rect, rotate) -> None:
        """A stamp's handle let go: the size and angle it has now.

        One entry for both handles, because they are one gesture: a corner
        says how big and the fifth says which way up, and either way what
        is kept is the shape it ended at. The rectangle carries the size --
        there is nowhere to write a scale -- so the two travel together.
        """
        if getattr(mark, "locked", False):
            return
        rect = tuple(float(v) for v in rect)
        rotate = float(rotate)
        if isinstance(mark, markup.Annotation):
            self._commit_mark_change(_("Reshape Mark"), index, mark)
            mark.rect = rect
            mark.rotate = rotate
            mark.touch()
            self._after_mark_change(index)
            return
        uid = self.model.pages[index].uid
        self._commit_mark_change(_("Reshape Mark"), index, mark)
        self.model.mark_edits.change(uid, mark.index,
                                     rect=rect, rotate=rotate)
        mark.rect = rect
        mark.rotate = rotate
        self._after_mark_change(index, uid)

    def mark_moved(self, index: int, mark, rect) -> None:
        """A comment's icon dragged to somewhere else on its page.

        Reader allows this and nothing here did. A move writes the rectangle
        and the date and leaves everything else -- the size, the appearance,
        the thread, the popup's own window -- exactly as it was, which is
        what Reader writes when one is dragged.

        Not a locked one: a lock holds a mark where it is as well as the
        size it is.
        """
        if getattr(mark, "locked", False):
            return
        rect = tuple(float(v) for v in rect)
        if isinstance(mark, markup.Annotation):
            self._commit_mark_change(_("Move Mark"), index, mark)
            mark.rect = rect
            mark.touch()
            self._after_mark_change(index)
            return
        uid = self.model.pages[index].uid
        self._commit_mark_change(_("Move Mark"), index, mark)
        self.model.mark_edits.change(uid, mark.index, rect=rect)
        mark.rect = rect
        self._after_mark_change(index, uid)

    def mark_deleted(self, index: int, mark) -> None:
        """The Delete key, with a mark selected in the reader.

        The window's own Delete removes *pages* and keeps that key whenever
        no mark is selected; the canvas only emits this when one is, which
        is what Reader does and what makes the nearer thing win.
        """
        self.delete_mark(index, mark)

    def note_shut(self) -> None:
        """The window was closed, by the cross or by Escape.

        The mark keeps its badge and its one line summary under the
        pointer: what has been put away is the window, not the note. Told
        to the canvas because that is what the pointer asks -- it offers
        the window on a mark the file saved open, and offered it again on
        every mouse move, so the cross used to put the window away for
        exactly as long as it took to move the mouse.
        """
        if self._noted is not None:
            index, marks = self._noted
            self.reader.canvas.note_window_shut(index, marks[0])
        self._noted = None
        self._drop_a_mark_with_nothing_to_say()

    def _drop_a_mark_with_nothing_to_say(self) -> None:
        """Take back a mark that *is* its note and never got one.

        A comment cancelled, or shut while still empty, is a comment
        nobody made -- so the mark goes and the step that placed it goes
        with it, leaving no entry that undoes nothing. A highlight or an
        underline is not touched: the mark stands on its own and simply
        ends up without a note.
        """
        waiting, self._awaiting_text = self._awaiting_text, None
        if waiting is None:
            return
        index, mark, placed_at = waiting
        if (mark.contents or "").strip():
            return
        # A pair goes whole: the caret the note was for and its strikeout.
        head = self.reader.canvas.head_of(index, mark)
        for going in {id(m): m for m in (mark, head)}.values():
            self.model.annotations.remove(going)
        # **And let go of it.** It is held the moment it is placed, so that
        # its thread belongs to a selection; dropping it without letting go
        # left its outline, its handles and its buttons sitting over a mark
        # that was no longer there.
        found = self.reader.canvas.selected_mark()
        if found is not None and found[1] in (mark, head):
            self.reader.canvas.select_mark(None)
        if placed_at == self.model.undo.current:
            self.model.undo.discard_last()
        self._mark_added()

    def open_note(self, index: int, mark, open_on=None) -> None:
        """Show the thread on a mark: its note first, then its replies.

        **Nothing opens for editing unless there is nothing written.** A
        thread already written is shown, not reached for: opening an editor
        over somebody's words, with the focus in it, is not what asking to
        read them means. The empty case is a comment being made, which is
        the one thing here that wants typing into, and a reply is asked for
        by the box at the end.

        ``open_on`` overrides that, and is how a redraw keeps the editor
        somebody is using: a status set while a reply is being written
        rebuilds the thread, and the box must not close under them.
        """
        if not 0 <= index < len(self.model.pages):
            return
        # A *Replace Selected Text* pair's note is on its caret.
        mark = self.reader.canvas.note_bearer(index, mark)
        # Asked for, so closing it earlier says nothing any more: the
        # pointer offers the window again from here on.
        self.reader.canvas.note_window_shut(index, mark, False)
        if (self._noted is not None and self.note_panel.isVisible()
                and self._noted[0] == index and self._noted[1][0] is mark):
            # Already showing this one. Hovering a mark whose window the
            # file left open asks for it on every mouse move, and rebuilding
            # the thread under the pointer would throw away what is being
            # typed into it.
            return
        if open_on is None:
            open_on = (0 if not (getattr(mark, "contents", "") or "").strip()
                       else self.note_panel.NOTHING)
        replies = self._replies_to(index, mark)
        status = self._status_of(index, mark)
        items = [NoteItem(
            getattr(mark, "author", "") or markup.default_author(),
            when_text(getattr(mark, "when", "")),
            getattr(mark, "contents", "") or "",
            status,
            markup.rich_to_html(getattr(mark, "rich", "")),
            bool(getattr(mark, "locked", False)),
            getattr(mark, "colour", None))]
        for reply in replies:
            items.append(NoteItem(
                reply.author or markup.default_author(),
                when_text(getattr(reply, "when", None)
                                 or getattr(reply, "created", "")),
                reply.contents,
                # **A reply carries a status of its own.** It is a mark, so
                # it has a chain like any other, and the corpus has three
                # replies under one note with three separate histories.
                self._status_of(index, reply),
                markup.rich_to_html(getattr(reply, "rich", "")),
                bool(getattr(reply, "locked", False)),
                getattr(reply, "colour", None)))
        self._noted = (index, [mark] + replies)
        self.note_panel.show_thread(items, open_on)
        where = getattr(mark, "popup_rect", None)
        if where and self._panel_rect_for(index, where) is not None:
            self.note_panel.resize_to(self._panel_rect_for(index, where))
        else:
            self._place_note_panel(index, mark)

    def _replies_to(self, index: int, mark):
        """Everything that answers ``mark``, the file's and ours alike.

        A reply the file brought is a mark in the document; one written here
        is an `Annotation` in the model that will become one when the file
        is saved. Both point at the mark by its `/NM`, so both belong in the
        same thread, in the order they were made.
        """
        name = getattr(mark, "name", None)
        found = []
        if not isinstance(mark, markup.Annotation):
            found += [m for m in self.reader.canvas.chain_of(mark)[1:]
                      if m.is_reply()]
        if name:
            uid = self.model.pages[index].uid
            # **Not the statuses.** The first status set on a mark points
            # at the mark itself -- that is what starts the chain -- so
            # without this it arrived in the thread as a reply, and the
            # window listed "Completed set by dws" as something somebody
            # had written.
            found += [a for a in self.model.annotations.for_page(uid)
                      if a.irt == name and markup.is_reply(a)]
        return found

    def reply_to(self, index: int, mark) -> None:
        """*Reply*: the same window with one more line in it, open and empty.

        Nothing is written until it is posted. An empty one left behind is
        dropped rather than saved, which is also why Post is refused while
        the editor is empty: there is no way to make a reply that says
        nothing.
        """
        mark = self.reader.canvas.note_bearer(index, mark)
        if self._noted is None or self._noted[0] != index:
            self.open_note(index, mark)
        if self._noted is None:
            return
        # What is in the box is kept, not dropped: Acrobat treats Reply as
        # a post of whatever has been typed and then the reply.
        self.note_panel.post_now()
        self.note_panel.add_blank(markup.default_author(),
                                  when_text(markup.pdf_date()))

    def _reply_to_the_open_thread(self) -> None:
        """*Add a reply* clicked at the end of the window that is open."""
        if self._noted is None:
            return
        index, marks = self._noted
        self.reply_to(index, marks[0])

    def _status_of(self, index: int, mark):
        """The mark's current status, or None. The *last* link in the chain:
        a history of Accepted then Completed is one status, Completed."""
        chain = self.reader.canvas.status_chain(index, mark)
        state = str(chain[-1].state).lstrip("/") if chain else None
        # A status *of* None is the absence of one. It is a link like any
        # other in the history -- that is how a status is taken back -- but
        # the thread says what the mark's status is, and the answer here is
        # that it has none.
        return None if state == "None" else state

    def set_mark_status(self, index: int, mark, state: str) -> None:
        """*Set status*: append a link to the mark's review history.

        **A status is a history, not a field.** Each change is an annotation
        of its own carrying `/State` and `/StateModel /Review`, and its
        `/IRT` points at *the link before it* rather than at the mark -- so
        the current status is the last link, and the rest are how it got
        there. Setting one never overwrites another, which is what lets
        Review History show the whole sequence.

        It is hidden, `/F 30`, because a status draws nothing: it is read
        in the thread or in the properties form.
        """
        if not 0 <= index < len(self.model.pages) or state not in markup.STATUSES:
            return
        # The same rule as *Reply*: setting a status keeps what has been
        # typed into the open editor rather than throwing it away.
        if self._noted is not None and self._noted[0] == index:
            self.note_panel.post_now()
        canvas = self.reader.canvas
        # A pair's statuses hang off its caret, with its note.
        mark = canvas.note_bearer(index, mark)
        if canvas.status_of(mark, index) == state:
            return
        answered = self._last_link(index, mark)
        if answered is None:
            return
        uid = self.model.pages[index].uid
        self.model.undo.commit(_("Set Status"))
        left, top = mark.rect[0], mark.rect[3]
        self.model.annotations.add(markup.Annotation(
            markup.TEXT, uid,
            markup.note_rect(left, top, markup.NOTE_SIZE),
            contents=_("{state} set by {author}").format(
                state=state, author=markup.default_author()),
            colour=getattr(mark, "colour", None) or self.armed_colour,
            author=markup.default_author(),
            irt=answered, state=state))
        self._after_mark_change(index, uid)
        self._show_thread_again(index, mark)

    def show_mark_properties(self, index: int, mark) -> None:
        """*Properties...*: the form, and what it changed.

        **Offered on a locked mark**, because the form is where the lock
        comes off. Everything else it can change is refused while the lock
        is on, which `_change_mark` and `delete_mark` already see to.
        """
        if not 0 <= index < len(self.model.pages):
            return
        # A pair is the strikeout's form, titled for the pair, with the
        # caret's history -- which is where its statuses are.
        canvas = self.reader.canvas
        mark = canvas.head_of(index, mark)
        said = canvas.note_bearer(index, mark)
        mine = isinstance(mark, markup.Annotation)
        form = MarkProperties(Properties(
            kind=("replace_text" if said is not mark
                  else mark.kind if mine else mark.subtype),
            author=(getattr(mark, "author", "") or markup.default_author()),
            subject=(getattr(mark, "subject", "") or markup.SUBJECTS.get(
                mark.kind if mine else mark.subtype, "")),
            when=when_text(getattr(mark, "when", None)
                           or getattr(mark, "created", "")),
            created=when_text(getattr(mark, "created", None)
                              or getattr(mark, "when", "")),
            colour=getattr(mark, "colour", None),
            opacity=(markup.solidity(mark) if mine
                     else getattr(mark, "opacity", None)),
            locked=bool(getattr(mark, "locked", False)),
            history=self._history_of(index, said),
            style=self._style_of(mark),
            icon=getattr(mark, "icon", "") or "",
            icons=self._icons_for(mark.kind if mine else mark.subtype),
            icons_fixed=markup.is_reply(mark),
            styles=self._styles_for(mark.kind if mine else mark.subtype),
        ), self)
        # **The appearance is live, as Acrobat's is**: the slider shows on
        # the page while it is dragged rather than when the form is
        # accepted. So the undo entry is taken before the first preview and
        # Cancel is an undo of whatever was shown.
        taken = []
        was_modified = self.modified
        was = {"colour": getattr(mark, "colour", None),
               "opacity": getattr(mark, "opacity", None)}
        form.previewed.connect(
            lambda colour, opacity: self._preview_mark(
                index, mark, colour, opacity, taken))
        accepted = form.exec() == MarkProperties.DialogCode.Accepted
        if accepted and form.make_default:
            self.mark_is_the_default(mark)
        changed = form.changed() if accepted else {}
        if not changed:
            # Nothing stands. Either Cancel, or an accepted form whose
            # appearance was dragged and put back where it started -- and
            # an undo entry for a change nobody made is a change nobody
            # made. Undoing the preview also rebuilds the canvas's marks,
            # which is what puts the page back.
            if taken and taken[0]:
                self.model.undo.undo()
                self.modified = was_modified
            elif taken:
                # Folded into a new mark's placement, so there is no step
                # of its own to undo: what the preview showed is put back.
                self._write_mark_fields(index, mark, was, mine)
                self.modified = was_modified
            return
        self._commit_properties(taken, index, mark)
        self._write_mark_fields(index, mark, changed, mine)
        self._show_thread_again(index, mark)

    def _commit_properties(self, taken: list, index: int, mark) -> None:
        """One undo entry for the whole form, taken before the first thing
        it changes -- which may be a preview rather than the accepting.

        ``taken`` records whether one was: a new mark still waiting for its
        first words has none of its own, its changes folding into the step
        that placed it."""
        if not taken:
            taken.append(self._commit_mark_change(
                _("Mark Properties"), index, mark))

    def _mark_is_waiting(self, index: int, mark) -> bool:
        """Whether ``mark`` is a new mark still waiting for its first words
        -- or the strikeout of a Replace pair whose caret is."""
        if self._awaiting_text is None:
            return False
        waiting_index, waiting, _placed = self._awaiting_text
        if waiting_index != index:
            return False
        return (mark is waiting
                or self.reader.canvas.head_of(index, waiting) is mark)

    def _commit_mark_change(self, label: str, index: int, mark) -> bool:
        """Take an undo step for a change to ``mark``, and say whether one
        was taken.

        **None for a mark that needs a note and has not been given one.**
        Until its first words are posted, the mark and everything done to it
        are the step that placed it: one undo takes the lot, and Cancel
        leaves nothing behind. A step of its own would let undo walk back to
        the mark with its note gone -- a state it is never meant to be in,
        and one Acrobat reaches by exactly these steps.
        """
        if self._mark_is_waiting(index, mark):
            return False
        self.model.undo.commit(label)
        return True

    def _preview_mark(self, index: int, mark, colour, opacity, taken) -> None:
        """Show a colour or an opacity the form is still holding.

        Written through the same path as accepting it, because a mark the
        file brought is only *shown* changed by its overlay -- the page is
        re-rendered from a document patched with `mark_edits`, so a preview
        that only set the attribute would show nothing at all.
        """
        self._commit_properties(taken, index, mark)
        self._write_mark_fields(
            index, mark, {"colour": colour, "opacity": opacity},
            isinstance(mark, markup.Annotation))

    def _write_mark_fields(self, index: int, mark, fields: dict,
                           mine: bool) -> None:
        """Record fields on a mark of ours, or beside one the file brought,
        and re-render the page that shows it."""
        page = self.model.pages[index]
        scale = page.scale if page.scale else 1.0
        partner = self._partner_fields(index, mark, fields)
        if mine:
            for name, value in fields.items():
                self._set_mark_field(mark, name, value, scale)
            mark.touch()
            if partner is not None:
                for name, value in partner[1].items():
                    self._set_mark_field(partner[0], name, value, scale)
                partner[0].touch()
            self._after_mark_change(index)
            return
        uid = page.uid
        self.model.mark_edits.change(uid, mark.index, **fields)
        for name, value in fields.items():
            self._set_mark_field(mark, name, value, scale)
        if partner is not None:
            self.model.mark_edits.change(uid, partner[0].index, **partner[1])
            for name, value in partner[1].items():
                self._set_mark_field(partner[0], name, value, scale)
        self._after_mark_change(index, uid)

    #: What a *Replace Selected Text* caret takes from a change to its
    #: strikeout: the two are always one colour and one opacity, and a lock
    #: holds the whole mark.
    PAIRED_FIELDS = ("colour", "opacity", "locked")

    def _partner_fields(self, index: int, mark, fields: dict):
        """``(caret, fields)`` for the half of a pair a change also reaches,
        or None for a mark that is not one."""
        caret = self.reader.canvas.caret_of(index, mark)
        if caret is None:
            return None
        shared = {name: value for name, value in fields.items()
                  if name in self.PAIRED_FIELDS}
        return (caret, shared) if shared else None

    @staticmethod
    def _set_mark_field(mark, name: str, value, scale: float = 1.0) -> None:
        """Put one changed field on the mark the reader is showing.

        **A style is not a field on a mark**: it is which subtype the mark
        has, so it is written as that rather than stored beside it. **Nor
        is an icon only a field**: a note's rectangle is that icon's own
        box, so the two move together or the canvas draws the new glyph in
        the old one's box. The rest are set as they are named.
        """
        if name == "style":
            kind = markup.UNDERLINE_STYLES.get(value)
            if kind is None:
                return
            if isinstance(mark, markup.Annotation):
                mark.kind = kind
            else:
                mark.subtype = kind
            return
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        was = getattr(mark, "icon", "")
        setattr(mark, name, value)
        if name == "icon" and kind == markup.TEXT:
            mark.rect = markup.icon_rect(mark.rect, value, scale)
        if name == "icon" and kind == markup.STAMP:
            # **The size it was given, not the new icon's own.** A stamp
            # that has been pulled to twice its size stays twice the size
            # when its glyph changes: the factor is the ratio the rectangle
            # already records, and the new icon's box times that is the
            # rectangle it should have.
            angle = float(getattr(mark, "rotate", 0.0) or 0.0)
            factor = markup.stamp_scale(mark.rect, was, angle)
            middle = ((mark.rect[0] + mark.rect[2]) / 2.0,
                      (mark.rect[1] + mark.rect[3]) / 2.0)
            mark.rect = markup.stamp_rect(middle[0], middle[1], value,
                                          factor, angle)

    #: What each style is called, untranslated. Marked here and translated
    #: where it is used: a label in a table reaches no catalogue at all,
    #: and one translated at import time never changes language again.
    STYLE_LABELS = {"straight": N_("Straight"), "squiggly": N_("Squiggly")}

    #: What each icon is called in the form, in the order Reader's list
    #: has them. Its own list gets two of these wrong -- the row reading
    #: *Checkmark* writes `/Check`, and the row reading *Insert Text*
    #: writes `/Checkmark` and draws a tick -- and we do not copy that.
    ICON_LABELS = (
        ("/Check", N_("Check")),
        ("/Checkmark", N_("Checkmark")),
        ("/Circle", N_("Circle")),
        ("/Comment", N_("Comment")),
        ("/Cross", N_("Cross")),
        ("/CrossHairs", N_("Cross Hairs")),
        ("/Help", N_("Help")),
        ("/Insert", N_("Insert Text")),
        ("/Key", N_("Key")),
        ("/NewParagraph", N_("New Paragraph")),
        ("", N_("Text Note")),
        ("/Paragraph", N_("Paragraph")),
        ("/RightArrow", N_("Right Arrow")),
        ("/RightPointer", N_("Right Pointer")),
        ("/Star", N_("Star")),
        ("/UpArrow", N_("Up Arrow")),
        ("/UpLeftArrow", N_("Up-Left Arrow")),
    )

    def _icons_for(self, kind):
        """The icons a kind offers, as ``(value, label)``.

        The two comments have them, and nothing else does: they are the
        marks drawn as a glyph rather than over the words they mark, and
        they offer the same seventeen. What they differ in is the subtype,
        which is not something the form sets.
        """
        if kind not in (markup.TEXT, markup.STAMP):
            return ()
        return tuple((value, _(label)) for value, label in self.ICON_LABELS)

    def _styles_for(self, kind):
        """The styles a kind offers, as ``(value, label)``.

        **A style is the subtype**: an underline is `/Underline` straight
        and `/Squiggly` squiggly, so choosing one in the form rewrites what
        the annotation is. Empty for every kind with one appearance.
        """
        if kind not in markup.UNDERLINE_STYLES.values():
            return ()
        return tuple((style, _(self.STYLE_LABELS[style]))
                     for style in markup.UNDERLINE_STYLES)

    def _style_of(self, mark):
        """Which style a mark is in, or None for a kind with one."""
        for style, kind in markup.UNDERLINE_STYLES.items():
            if (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype) == kind:
                return style
        return None

    def _history_of(self, index: int, mark):
        """The mark's review history, as the form reads it out.

        **Composed, not stored.** Acrobat prints `{author}: {state}, {when}`
        and does not show the sentence each link carries in `/Contents`,
        which it generates for other viewers.
        """
        return tuple(
            (getattr(link, "author", "") or markup.default_author(),
             str(link.state).lstrip("/"),
             when_text(getattr(link, "when", None)
                       or getattr(link, "created", "")))
            for link in self.reader.canvas.status_chain(index, mark))

    def _show_thread_again(self, index: int, mark) -> None:
        """Rebuild the open window, where it is the one that just changed.

        A status is read in the thread, so setting one while the thread is
        showing has to reach it -- otherwise the only way to see what you
        just set is to close the window and open it again.

        **Any item of it, not only the note.** A reply has a status and can
        be deleted, and both change the thread the window is showing.
        """
        if not self.note_panel.isVisible() or self._noted is None:
            return
        shown, marks = self._noted
        if shown != index or not any(m is mark for m in marks):
            return
        root = marks[0]
        # Whatever was open stays open. This is a redraw, not an opening.
        open_on = self.note_panel.selected()
        self._noted = None
        self.open_note(index, root, open_on)

    def note_menu(self, which: int, at) -> None:
        """The menu asked for inside the thread window.

        **The first item is the mark**, so its line and the window's own
        background both give the mark's menu -- the one the page gives,
        with *Delete Thread* on it. There is no deleting the first item on
        its own: it is the comment, and the replies hang off it.
        """
        if self._noted is None:
            return
        index, marks = self._noted
        if which <= 0 or which >= len(marks):
            menu = self.reader.canvas.mark_menu(index, marks[0], inside=True)
        else:
            menu = self._reply_menu(index, marks[which])
        menu.exec(at)

    def _reply_menu(self, index: int, reply):
        """What can be done to one reply: answer it, take it out, judge it.

        *Delete* here is the whole reply and the status chain hanging off
        it, not the words in it -- the words are edited by clicking them.
        """
        menu = QMenu(self)
        answer = menu.addAction(_("Reply"))
        answer.triggered.connect(
            lambda: self.reply_to(index, self._noted[1][0])
            if self._noted else None)
        remove = menu.addAction(_("Delete"))
        remove.triggered.connect(lambda: self.delete_mark(index, reply))
        # Shown and disabled rather than left out: a locked reply is still
        # a reply, and an entry that vanishes makes it look like something
        # else. Taken from the owner on 2026-11-03, against Acrobat, which
        # leaves it out.
        remove.setEnabled(not getattr(reply, "locked", False))
        status = menu.addMenu(_("Set status"))
        now = self.reader.canvas.status_of(reply, index)
        for state in markup.STATUSES:
            act = status.addAction(_(markup.STATUS_LABELS[state]))
            act.setCheckable(True)
            act.setChecked(state == now)
            act.triggered.connect(
                lambda _checked=False, st=state:
                self.set_mark_status(index, reply, st))
        menu.addSeparator()
        details = menu.addAction(_("Properties..."))
        details.triggered.connect(
            lambda: self.show_mark_properties(index, reply))
        return menu

    def _last_link(self, index: int, mark):
        """The `/NM` the next status change should point at.

        The end of the chain, not the mark: a status points at the link
        before it, so pointing a new one at the mark would start a second
        history beside the first rather than continuing it.
        """
        name = getattr(mark, "name", None)
        if not name:
            return None
        chain = self.reader.canvas.status_chain(index, mark)
        return chain[-1].name if chain else name

    def _write_reply(self, index: int, mark, text: str, rich=None) -> None:
        """Keep a new reply to ``mark``, as a mark of its own.

        A reply is a `/Text` that answers another annotation: it draws its
        own icon, anchored to the top left of what it answers, and carries
        that mark's colour so the thread reads as one thing. What makes it a
        reply rather than a note somebody dropped there is `/IRT`, which is
        resolved on the way out from the name of the mark it answers.
        """
        name = getattr(mark, "name", None)
        if not name:
            return
        uid = self.model.pages[index].uid
        left, top = mark.rect[0], mark.rect[3]
        self.model.undo.commit(_("Reply"))
        reply = markup.Annotation(
            markup.TEXT, uid,
            markup.note_rect(left, top, markup.NOTE_SIZE),
            contents=text, rich=rich,
            colour=getattr(mark, "colour", None) or self.armed_colour,
            author=markup.default_author(),
            irt=name)
        self.model.annotations.add(reply)
        if self._noted is not None:
            # Only when the thread is the one showing. A reply can be
            # written with no window open -- the menu's *Reply* opens one,
            # but nothing else has to.
            self._noted = (index, list(self._noted[1]) + [reply])
        self._after_mark_change(index, uid)

    def _panel_rect_for(self, index: int, rect):
        """A window's rectangle in the page, as a viewport one.

        Reader parks a window it has never been given a place for *off* the
        paper, to the right, which has nowhere to go here -- there is no
        off-the-paper in a scrolling reader. One of those is ignored and the
        panel is put beside the mark instead; one somebody actually moved is
        honoured.
        """
        canvas = self.reader.canvas
        shown = canvas.quad_on_screen(index, rect, scaled=False)
        if shown is None:
            return None
        view = canvas.viewport().rect()
        if not view.intersects(shown.toRect()):
            return None
        return shown.toRect()

    def note_panel_placed(self, rect) -> None:
        """The window was moved or resized, which the document records.

        **This is an edit and it marks the document dirty**, unlike opening
        the window, which writes nothing. One writes a new `/Popup /Rect`
        and the other does not, so "save your changes?" is the right
        question after this and the wrong one after merely reading a note.
        """
        if self._noted is None:
            return
        index, marks = self._noted
        mark = marks[0]
        canvas = self.reader.canvas
        top_left = canvas.page_point(index, QPointF(rect.left(), rect.top()))
        bottom_right = canvas.page_point(
            index, QPointF(rect.right(), rect.bottom()))
        if top_left is None or bottom_right is None:
            return
        where = (top_left[0], bottom_right[1], bottom_right[0], top_left[1])
        if isinstance(mark, markup.Annotation):
            if mark.popup_rect == where:
                return
            mark.popup_rect = where
            mark.touch()
        else:
            uid = self.model.pages[index].uid
            if self.model.mark_edits.of(uid, mark.index).get("popup") == where:
                return
            self.model.mark_edits.change(uid, mark.index, popup=where)
        self._mark_modified()

    def _place_note_panel(self, index: int, mark) -> None:
        """Beside the mark, and inside the viewport.

        Reader parks its window off the right edge of the paper; there is no
        off-the-paper here, so it goes next to the mark and is pulled back
        when it would hang over an edge.
        """
        canvas = self.reader.canvas
        boxes = canvas.mark_boxes(mark)
        where = canvas.quad_on_screen(
            index, boxes[0], scaled=isinstance(mark, markup.Annotation))
        if where is None:
            return
        view = canvas.viewport().rect()
        panel = self.note_panel
        x = min(int(where.right()) + 8, view.right() - panel.width() - 8)
        y = min(int(where.top()), view.bottom() - panel.height() - 8)
        panel.move(max(8, x), max(8, y))

    def note_posted(self, which: int, text: str) -> None:
        """Keep what was typed on the item it was typed into.

        A note is the mark's own `/Contents`; a reply is a mark of its own
        with its own index, so both are the same change to a different mark.
        """
        if self._noted is None:
            return
        index, marks = self._noted
        # The styling goes with the words. `/RC` is the same text with its
        # runs marked up and a reader prefers it, so writing one without
        # the other leaves the file saying two different things.
        rich = markup.rich_from_runs(self.note_panel.runs_of(which))
        if which == len(marks):
            self._write_reply(index, marks[0], text, rich)
            return
        if not 0 <= which < len(marks):
            return
        target = marks[which]
        first_words = (self._awaiting_text is not None
                       and self._awaiting_text[1] is target)
        if first_words:
            # It said something, so it is a mark like any other now.
            self._awaiting_text = None
        # **No entry for the first words on a mark that was waiting for
        # them.** The one pushed when it was placed already holds the state
        # from before it existed, so a single undo takes the mark and its
        # words together rather than leaving an empty icon behind.
        if not first_words:
            self.model.undo.commit(_("Edit Note"))
        if isinstance(target, markup.Annotation):
            target.contents = text
            target.rich = rich
            self._after_mark_change(index)
            return
        uid = self.model.pages[index].uid
        self.model.mark_edits.change(uid, target.index,
                                     contents=text, rich=rich)
        target.contents = text
        target.rich = rich or ""
        self._after_mark_change(index, uid)

    def tool_that_made(self, mark) -> str:
        """Which tool made ``mark``, by the name `tools.py` knows it by.

        **The kind names the tool**, and `/Highlight` is the only kind two
        of them make: the highlight tool, and the comment tool over a run
        of words, which is told by `/Subj` and `/IT`. A mark whose kind
        cannot be named never reaches here -- it is not selectable, so no
        form opens on it.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind == markup.HIGHLIGHT:
            names = (getattr(mark, "subject", "") or "",
                     getattr(mark, "intent", "") or "")
            if names == markup.COMMENT_ON_TEXT:
                return "comment"
        if kind == markup.STRIKEOUT and getattr(mark, "group", False):
            # The other kind two tools make: a strikeout grouped with a
            # caret is half of *Replace Selected Text*. One that only says
            # it is a text edit, with no caret -- what Acrobat leaves on the
            # earlier page of a selection across a break -- is a
            # strikethrough.
            return "replace_text"
        if kind in markup.UNDERLINE_STYLES.values():
            # Both styles are the one tool: the style *is* the subtype, so
            # a squiggly is not a kind of its own to be traced back.
            kind = markup.UNDERLINE
        for tool, made in self.MARK_KINDS.items():
            if made == kind and tool not in self.GESTURE_TOOLS:
                return self.CANVAS_TO_STRIP.get(tool, tool)
        return ""

    def mark_is_the_default(self, mark) -> None:
        """*Make current properties default*: what the next mark gets.

        Writes nothing to any document. It sends this mark's appearance to
        the defaults of **the tool that made it**, which is what the
        checkbox in the properties form does and what the same entry in
        the right-click menu does -- one behaviour, two ways in.

        The author and the subject are not touched. They belong to the
        mark: who made it, and what this one is called.
        """
        tool = self.tool_that_made(mark)
        if not tool:
            return
        colour = getattr(mark, "colour", None)
        if colour is not None:
            self.armed_colour = tuple(colour)
            self._colours[tool] = tuple(colour)
        # A mark we made answers what its kind starts at when it has said
        # nothing; a mark the file brought answers 1, because that is what
        # an absent `/CA` means. Asking `solidity` for both raised on the
        # second -- a `Mark` has no `kind`.
        opacity = float(
            markup.solidity(mark) if isinstance(mark, markup.Annotation)
            else markup.opacity_of(mark))
        self.armed_opacity = opacity
        self._opacities[tool] = opacity
        style = self._style_of(mark)
        if style is not None:
            self._styles[tool] = style
        icon = getattr(mark, "icon", None)
        if icon is not None and (
                mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype) == markup.TEXT:
            self._icons[tool] = icon
        self._remember_tool_defaults()
        self.tool_strip.arm_colour(self.colour_for(self.tool_strip.armed()))

    def comment_on_selected_mark(self) -> None:
        """The first button in the bar: open the selected mark's thread.

        The same window *Open Pop-Up Note* opens, because it is the same
        thing -- the mark's own note with whatever has been said under it.
        Two ways in, one window.
        """
        found = self.reader.canvas.selected_mark()
        if found is not None:
            self.open_note(*found)

    def delete_selected_mark(self) -> None:
        """The trash in the bar beside the selected mark."""
        found = self.reader.canvas.selected_mark()
        if found is not None:
            self.delete_mark(*found)

    def delete_mark(self, index: int, mark) -> None:
        """Take a mark out, with everything that hangs off it.

        **Its status chain and its replies go with it**, which is not what
        Reader does: Reader deletes the replies, keeps the
        status annotations and strips the `/IRT` off the one that pointed at
        the mark. Measured on a file it wrote, that leaves two `/F`-hidden
        `/Text` annotations recording that someone Accepted and then
        Completed a comment that no longer exists -- unreachable in its own
        comment panel, where the owner confirmed a deleted comment no longer
        appears in Review History, and unreachable here, because
        `MarkMap.visible` drops hidden marks too. Litter nobody can read.

        A mark the file brought is recorded as deleted in the overlay rather
        than removed from anything: the source document is never edited, so
        the positions `MarkEdits` is keyed by do not move. One of the user's
        own is removed from the model, where it lives.

        The confirmation is Reader's, and only for replies -- a status
        makes no difference to it, and neither does a note with nobody's
        answer under it.
        """
        if not 0 <= index < len(self.model.pages):
            return
        canvas = self.reader.canvas
        # From inside the note window a pair arrives as its caret; it is
        # deleted as the strikeout that stands for it.
        mark = canvas.head_of(index, mark)
        if getattr(mark, "locked", False):
            # Locked is the one attribute that refuses here rather than in
            # the menu: the Delete key reaches this too.
            return
        going = canvas.chain_of(mark)
        # What hangs *off* it, not it. Deleting a reply is deleting one
        # reply, and warning that somebody else's answers will go with it
        # would be warning about itself.
        if any(not isinstance(m, markup.Annotation) and m.is_reply()
               for m in going[1:]) and not self._confirm_mark_delete():
            return
        self.model.undo.commit(_("Delete Mark"))
        said = canvas.note_bearer(index, mark)
        root = self._noted is not None and any(
            m is said for m in self._noted[1][:1])
        if isinstance(mark, markup.Annotation):
            self.model.annotations.remove(mark)
            if said is not mark:
                # A pair made here: its caret too, and whatever was written
                # under the caret's note in this session.
                for one in self._made_here_under(index, said):
                    self.model.annotations.remove(one)
                self.model.annotations.remove(said)
            canvas.select_mark(None)
            self._after_mark_change(index)
            self._thread_lost(index, mark, root)
            return
        uid = self.model.pages[index].uid
        for one in going:
            self.model.mark_edits.change(uid, one.index, deleted=True)
        # Before the re-render, so the page that comes back is drawn without
        # them *and* nothing hit-tests them any more. The map was built from
        # the document the reader is showing and still holds them.
        canvas.forget_marks(going)
        self._after_mark_change(index, uid)
        self._thread_lost(index, mark, root)

    def _made_here_under(self, index: int, mark) -> list:
        """This session's replies and statuses under ``mark``, followed
        link by link, as a status points at the link before it."""
        if not 0 <= index < len(self.model.pages):
            return []
        mine = self.model.annotations.for_page(self.model.pages[index].uid)
        found, names = [], {getattr(mark, "name", None)}
        while names:
            step = [a for a in mine if a.irt in names and a not in found
                    and not a.group]
            found += step
            names = {a.name for a in step}
        return found

    def _thread_lost(self, index: int, mark, root: bool) -> None:
        """Put the window right after something in it was deleted.

        The comment itself takes the window with it -- there is no thread
        left to show. A reply only takes its own line, so the rest is shown
        again without it.
        """
        if self._noted is None:
            return
        if root:
            self.note_panel.hide()
            self._noted = None
            return
        self._show_thread_again(index, mark)

    def _confirm_mark_delete(self) -> bool:
        """Reader's dialog, for a mark somebody has replied to.

        Not suppressible, as Reader's is not, and not shown for a mark that
        merely carries a note or a status: what is being warned about is
        somebody *else's* words going with yours.
        """
        return QMessageBox.question(
            self, APP_NAME,
            _("This mark has replies.")
            + "\n" + _("Deleting this mark will also delete any replies to it."),
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        ) == QMessageBox.Yes

    def _after_mark_change(self, index: int, uid=None) -> None:
        """Re-render the page and tell the rest, without rebuilding."""
        self._reader_keeps_showing = True
        try:
            self.model.touch([index])
        finally:
            self._reader_keeps_showing = False
        self._mark_modified()
        if uid is not None:
            self._show_mark_edits(index, uid)
        else:
            self.reader.canvas.viewport().update()

    def _change_mark(self, **fields) -> None:
        """Record a change to the selected mark and show it.

        A mark of the user's is changed where it lives, in the model. One the
        file brought is *not*: its own dictionary stays the producer's, and
        the change is held beside it in `mark_edits` until export patches the
        handful of keys it names.
        """
        found = self.reader.canvas.selected_mark()
        if found is None:
            return
        index, mark = found
        if not 0 <= index < len(self.model.pages):
            return
        if getattr(mark, "locked", False):
            # What a lock locks: the attributes and the mark's own text.
            # Refused here rather than only in the surfaces that offer it,
            # so a colour, an opacity and a resize are all one answer.
            return
        uid = self.model.pages[index].uid
        self._commit_mark_change(_("Change Mark"), index, mark)
        partner = self._partner_fields(index, mark, fields)
        if isinstance(mark, markup.Annotation):
            for name, value in fields.items():
                setattr(mark, name, value)
            mark.touch()
            if partner is not None:
                for name, value in partner[1].items():
                    setattr(partner[0], name, value)
                partner[0].touch()
            self.mark_buttons.set_mark(mark.colour, markup.solidity(mark))
            self._mark_added()
            return
        self.model.mark_edits.change(uid, mark.index, **fields)
        for name, value in fields.items():
            setattr(mark, name, value)
        if partner is not None:
            self.model.mark_edits.change(uid, partner[0].index, **partner[1])
            for name, value in partner[1].items():
                setattr(partner[0], name, value)
        self.mark_buttons.set_mark(mark.colour, mark.opacity)
        # Only this page: a mark changed on one page is not a reason to
        # re-render every thumbnail in the document, and `_mark_added` touches
        # them all because adding a mark was the only thing that got here.
        #
        # And without rebuilding the reader. Touching a page tells it the
        # snapshot is stale, which is true of a page's geometry and not of
        # this: the change is shown by re-rendering the one page below, and a
        # rebuild would throw that away along with the selection it belongs
        # to -- measured, 499 ms to undo work that cost 25.
        self._reader_keeps_showing = True
        try:
            self.model.touch([index])
        finally:
            self._reader_keeps_showing = False
        self._mark_modified()
        self._show_mark_edits(index, uid)

    def _show_mark_edits(self, index: int, uid: int) -> None:
        """Re-render one page so a change to its marks can be seen.

        The marks a document arrived with are drawn into the page bitmap by
        PDFium, so a recoloured one cannot be painted over: the page has to
        come from a document that carries the change. One page rather than
        the document, which is 1.1 to 6.5 ms against 1180 ms on a book of
        1590 pages.
        """
        data = self.reader.document_bytes()
        if data is None:
            return
        self.reader.canvas.repaint_edited(
            index, markup.one_page_with_edits(
                data, index, self.model.mark_edits.for_page(uid),
                hide_replies=True))

    def _mark_added(self) -> None:
        """Tell everything a mark was added, without rebuilding the reader.

        The same reasoning as `_field_filled`: the canvas draws the mark from
        what this holds, so the reader's document does not have to be made
        again to show it.
        """
        self._reader_keeps_showing = True
        try:
            self.model.touch(range(len(self.model.pages)))
        finally:
            self._reader_keeps_showing = False
        self._mark_modified()
        self.reader.canvas.viewport().update()

    def keyPressEvent(self, event):
        """Escape puts the pointer back, whether the strip is up or not.

        Arming a tool sets a mode. Closing the strip does not clear it, so a
        tool can be armed with nothing on screen saying so -- which is the
        state where a way out matters most. Tested on the mode rather than on
        the panel for that reason.

        It sees the key only when nothing nearer wanted it: the canvas takes
        Escape first when a field has focus, when a mark is being drawn, or
        when there is a selection to clear, each of which is what the key
        meant at that moment.
        """
        if (event.key() == Qt.Key_Escape
                and self.tool_strip.armed() != tools.DEFAULT):
            self.tool_strip.disarm()
            return
        super().keyPressEvent(event)

    def show_markup_tools(self, on: bool) -> None:
        """Open or close the strip.

        Placed on first opening rather than on construction, because where it
        goes depends on the size of a reader that has not been laid out yet.
        """
        self.settings.setValue("reader/markup-tools", bool(on))
        if on and self.act_markup_tools.isEnabled():
            self.tool_strip.place(
                self.settings.value("reader/markup-tools-at"))
            self.tool_strip.show()
            self.tool_strip.raise_()
        else:
            self.tool_strip.hide()

    def set_tool(self, tool: str) -> None:
        """Choose what the pointer does in the reader."""
        self.reader.canvas.set_tool(tool)

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
        m.addAction(self.act_bookmarks)
        m.addAction(self.act_prev_page)
        m.addAction(self.act_next_page)
        m.addAction(self.act_first_page)
        m.addAction(self.act_last_page)
        m.addAction(self.act_go_to_page)
        m.addSeparator()
        m.addAction(self.act_markup_tools)
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
        # On the toolbar as well as the View menu: creating bookmarks in a
        # document that has none is a real thing to want to do, and a panel that
        # only appears for documents that already have some has to be openable
        # without hunting through a menu.
        self.reader_toolbar.addAction(self.act_bookmarks)
        self.reader_toolbar.addAction(self.act_markup_tools)
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
        # A warning is shown in red and only while it is up: the bar goes
        # back to its own colour the moment its message changes or expires.
        self.statusBar().messageChanged.connect(self._status_message_changed)

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
        """The password for the document a page came from, or none.

        Tolerant of a page whose document is gone, because a lookup arriving
        after teardown has no correct answer and should not be an exception:
        it is reached from a queued render, so raising here prints a traceback
        from inside a Qt slot and is swallowed. `closeEvent` empties the page
        list before the documents to stop that state arising at all; this is
        the second lock on the same door.
        """
        if not 0 < page.nfile <= len(self.docs.docs):
            return ""
        return self.docs.docs[page.nfile - 1].password

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
            #
            # **Except undo and redo.** They are in the Edit menu, so they
            # were swept up with the commands that change the page list --
            # and markup is an edit that happens *in* read mode, so taking
            # a mark back was impossible: every markup command commits to
            # the same history and nothing could unwind it.
            for act in self._editing_actions():
                if act in (self.act_undo, self.act_redo):
                    continue
                act.setEnabled(False)
        self.status_mode.setText(_("Reading") if self.read_mode else "")
        # Always available: switching view is not an edit, and with no document
        # both views are empty, so there is nothing to protect the user from.
        self.act_arrange_mode.setEnabled(True)
        for act in (self.act_bookmarks,
                    self.act_continuous, self.act_facing, self.act_next_page,
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
        self.act_markup_tools.setEnabled(self.read_mode and has_pages)
        if self.act_markup_tools.isChecked():
            # Checked is the *preference*, kept across a trip to the grid and
            # across sessions. Whether the strip is on screen is a separate
            # question: arranging is not a mode its tools act in, and there is
            # nothing to mark up before a document is open.
            self.show_markup_tools(True)
        if self.read_only:
            # Last of all, because this is the stronger rule. Read mode above
            # says the grid is not on screen; this says the document will not
            # be written at all, which also takes away Save, the exports and
            # the way back to Arrange.
            for act in self._writing_actions():
                act.setEnabled(False)
            self.act_arrange_mode.setEnabled(False)
            self.status_mode.setText(_("Signed — read only"))

    @property
    def read_only(self) -> bool:
        """Whether this session refuses every change and every write.

        A signature, and nothing else so far. A document built here is a new
        one, so nothing we write can carry a signature over -- and rather
        than hand back a copy whose signature is broken, or silently gone,
        the application becomes a reader for as long as the document is open.

        A signed document is never in company: the three routes that would
        put another file beside it refuse to, so this is in practice a
        question about one document even though it is asked of the set.
        """
        return bool(self._signed_sources())

    def _writing_actions(self):
        """Every command a read-only document refuses.

        ``_editing_actions`` narrows File down to the few commands that
        write, because reading a document is no reason to stop saving it. A
        signed one is a different matter, so here the filter is inverted:
        every File command is refused except the few that plainly write
        nothing. Built as an exclusion rather than a list so that a command
        added later is refused by default -- the safe direction to be wrong
        in, for a rule whose whole purpose is to stop a file being written.
        """
        allowed = {self.act_new_window, self.act_open, self.act_print,
                   self.act_close, self.act_quit}
        allowed.update(self.recent_menu.actions())
        out = list(self._editing_actions())
        for title, actions in self._shortcut_groups():
            if title == "File":
                out.extend(a for a in actions if a not in allowed)
        return out

    def _uid_of_page(self, page):
        """The identity of the page at a position, for a bookmark added there."""
        if 0 <= page < len(self.model.pages):
            return self.model.pages[page].uid
        return None

    def _page_of_uid(self, uid):
        """Where the page with this identity is *now*, or None if it has gone.

        A bookmark names a page rather than a position, so following one
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

    def _selection_crosses_pages(self, crossing: bool) -> None:
        """A selection that runs across a page break cannot be marked.

        It follows the order the file stores its text in, so it takes in
        the footer, page number and header between -- often off screen --
        and a mark made from it would cover text nobody meant to mark. So
        the text tools are refused while it lasts, and with the strip open,
        where somebody is marking up, the status bar says why. Reading with
        the strip shut, there is nothing to explain.
        """
        from .canvas import PageCanvas

        # Not *Insert Text*: it never marks a selection made before it is
        # chosen -- choosing it lets the selection go -- so refusing it
        # would protect nothing and take away a way out.
        text_tools = [strip for strip, canvas in self.CANVAS_TOOLS.items()
                      if canvas in PageCanvas.TEXT_TOOLS
                      and canvas != PageCanvas.INSERT]
        self.tool_strip.set_tools_enabled(text_tools, not crossing)
        message = _("Text is marked one page at a time.")
        if crossing and self.tool_strip.isVisible():
            self._warn(message, 10000)
        elif not crossing and self.statusBar().currentMessage() == message:
            # Gone with what it was explaining.
            self.statusBar().clearMessage()

    def _warn(self, message: str, timeout: int) -> None:
        """Show ``message`` in the status bar in red, for ``timeout`` ms.

        Qt colours the whole bar rather than one message, so the bar's own
        text is turned red for this message and put back when it goes --
        "Saved" and "Copied" keep the bar's colour. Red on a light bar and
        the palette's Light Red on a dark one, where plain red is hard to
        read.
        """
        bar = self.statusBar()
        dark = bar.palette().window().color().lightness() < 128
        red = markup.swatch("Light Red" if dark else "Red")
        self._warning = message
        bar.setStyleSheet("QStatusBar {{ color: rgb({}, {}, {}); }}".format(
            *(round(255 * v) for v in red[:3])))
        bar.showMessage(message, timeout)

    def _status_message_changed(self, text: str) -> None:
        """Put the bar's colour back once the warning is no longer showing."""
        if getattr(self, "_warning", None) and text != self._warning:
            self._warning = None
            self.statusBar().setStyleSheet("")

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

    #: How long an open may take before it is worth saying something. Short
    #: enough that a freeze is never silent, long enough that an ordinary
    #: local file never flashes a dialog.
    SLOW_OPEN_MS = 400

    def _copy_source(self, source: str, destination: str):
        """`shutil.copy`, off the GUI thread, with a dialog if it is slow.

        Opening a file from a cloud-backed folder blocks on the *first read*
        while the provider fetches the whole thing -- measured at 11.4 of 11.5
        seconds for a 185 MB file, with nothing landing on disk until the very
        end. So there is no progress to report and no way to copy in chunks
        that would report any: the only honest answer is to get the blocking
        read off this thread and say that something is happening.

        Deliberately not gated on detecting a cloud file. `st_blocks` does not
        exist on Windows, where the equivalent is a pair of `st_file_attributes`
        bits that Python does not even name, and that branch could never be
        exercised by a test. A timer needs none of it, behaves the same on all
        three platforms, and also covers what detection would miss: a slow
        network share, a spinning disk, a very large local file.
        """
        failure = []

        class _Copy(QThread):
            def run(self):
                try:
                    shutil.copy(source, destination)
                except BaseException as error:   # noqa: BLE001 - re-raised below
                    failure.append(error)

        worker = _Copy()
        waiting = QEventLoop()
        worker.finished.connect(waiting.quit)
        dialog = QProgressDialog(
            _("Opening %s…") % os.path.basename(source), "", 0, 0, self)
        dialog.setCancelButton(None)        # a blocked read cannot be stopped
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.reset()                      # built hidden; the timer shows it
        later = QTimer(self)
        later.setSingleShot(True)
        later.timeout.connect(dialog.show)
        later.start(self.SLOW_OPEN_MS)
        try:
            worker.start()
            waiting.exec()
        finally:
            later.stop()
            dialog.close()
            worker.wait()
        if failure:
            raise failure[0]

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
                    added.extend(self.docs.add_file(
                        path, ask_password=self._ask_password,
                        copier=self._copy_source))
                except PDFDocError as e:
                    QMessageBox.warning(self, APP_NAME, str(e))
                except OSError as e:
                    QMessageBox.warning(self, APP_NAME, f"{path}: {e}")
                else:
                    self._remember_folder(self.SOURCE_FOLDER, path)
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
        """Read the bookmarks out of the loaded files.

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
        # Now that we know whether this document has any, the panel can decide
        # whether it belongs up. Covers importing as well as opening: a file
        # brought in may be the one that supplies the bookmarks.
        self._show_outline_for_document()

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
        if len(paths) > 1 and self._signed_paths(paths):
            # Before the reset, so a refused merge leaves what was open alone.
            self._refuses_company(paths)
            return False
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

    # -- read mode ---------------------------------------------------

    def set_arrange_mode(self, on: bool):
        """The toggle the user sees: checked means arranging."""
        self.set_read_mode(not on)

    def set_read_mode(self, on: bool):
        """Swap the central widget between the grid and the reader.

        Entering re-exports the page list if anything changed since the last
        time, so what is read always matches what would be saved.
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

    def set_bookmarks_visible(self, on: bool):
        """Show or hide the bookmarks panel, and remember that you want it.

        The preference is what you asked for in general; whether the panel is
        actually up also depends on the document having any (see
        `_show_outline_for_document`). Turning it on for a document with none --
        to start making some -- is therefore not recorded as a change of
        preference, only as a change for this document.
        """
        on = bool(on)
        self.reader.set_outline_visible(on)
        self.act_bookmarks.setChecked(on)
        if on and not self.reader.has_outline():
            # Asked for on an empty document: wanted here, not everywhere.
            self._outline_asked_for = True
            return
        self._outline_asked_for = False
        self.settings.setValue("reader/outline", on)

    def _show_outline_for_document(self):
        """Decide whether the panel belongs up, now that a document has loaded.

        The rule: it appears whenever the document has bookmarks and you have
        not turned it off; with none it waits until you ask. Asking holds for
        that document and no longer -- the panel follows the document, and the
        preference records whether you want it at all.
        """
        wanted = self.settings.value("reader/outline", True, type=bool)
        on = (wanted and self.reader.has_outline()) or self._outline_asked_for
        self.reader.set_outline_visible(on)
        self.act_bookmarks.setChecked(on)

    def set_facing_pages(self, on: bool):
        """Two pages side by side while reading, or one.

        Remembered like the scroll mode: it is a way of reading rather than a
        property of a document.
        """
        self.settings.setValue("reader/facing", bool(on))
        self.reader.set_facing(bool(on))
        self.act_facing.setChecked(bool(on))

    def _load_reader(self) -> bool:
        # Where the reader is, so that rebuilding does not also move it. Only
        # while reading: entering read mode has its own idea of where to open.
        where = self.reader.canvas.position() if self.read_mode else None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self.reader.load(self.model.pages, self.docs.files_for_export(),
                                  self.docs.source_names(),
                                  self.docs.source_if_unmodified(self.model.pages),
                                  forms_present=self.docs.has_form_widgets())
        finally:
            QApplication.restoreOverrideCursor()
        self._reader_stale = not ok
        if ok:
            # Carry any active Find over, so entering read mode keeps the
            # highlights rather than silently dropping them.
            self.reader.search(self.search.query)
            self.reader.canvas.go_to_position(where)
            # And the changes made to the marks the document arrived with.
            # The snapshot is built from the sources, so it shows those marks
            # exactly as the file has them; a recolour lives in the model and
            # has to be put back over the top every time the snapshot is
            # rebuilt, or the colour reverts whenever anything else is edited.
            self._show_all_mark_edits()
            self._put_edits_on_records()
        return ok

    def _put_edits_on_records(self) -> None:
        """Give the reader's record of each mark the edits held for it.

        **The picture and the record are rebuilt separately.** The reader
        reads its marks afresh from the snapshot, which is built from the
        sources and so holds every mark as the file has it; the page is
        re-rendered with the edits put back, but the records were left as
        read. So after a trip to Arrange, an undo or any other rebuild, a
        mark recoloured blue was drawn blue and remembered as red -- and the
        swatch, the properties form and a resize all started from red.

        Set from whatever edits are held *now*, so after an undo the records
        match the state the undo restored. A mark deleted this session is
        dropped from what can be clicked, as it was before the rebuild.
        """
        canvas = self.reader.canvas
        going = []
        for index, row in enumerate(self.model.pages):
            edits = self.model.mark_edits.for_page(row.uid)
            if not edits:
                continue
            scale = row.scale if row.scale else 1.0
            for mark in canvas._file_marks.for_page(index + 1):
                edit = edits.get(mark.index)
                if not edit:
                    continue
                if edit.get("deleted"):
                    going.append(mark)
                    continue
                for name, value in edit.items():
                    if name == "quads":
                        # Back into the shape a `Mark` holds, as a resize
                        # leaves it: `/QuadPoints` corners, not rectangles.
                        boxes = tuple(tuple(q) for q in value)
                        mark.quads = tuple(tuple(markup._quad_points(q))
                                           for q in boxes)
                        mark.rect = markup.bounding_rect(boxes)
                    elif name == "popup":
                        mark.popup_rect = tuple(value)
                    elif name == "rich":
                        mark.rich = value or ""
                    elif name == "modified":
                        mark.when = value
                    else:
                        self._set_mark_field(mark, name, value, scale)
        if going:
            canvas.forget_marks(going)

    def _show_all_mark_edits(self) -> None:
        """Re-render every page that needs to be shown differently.

        Two reasons a page does. Its marks have been changed, and the
        snapshot the reader was given shows them as the file has them. Or
        it carries **replies**, which are not page content: Reader draws
        none of them, and a file gives every reply in a thread the same
        rectangle, so a renderer that honours their appearance streams
        stacks them into one smudge at the corner of the mark. What a reply
        says is in the thread window and on the badge, both of which this
        application draws itself.

        Only what is *shown*. The document written out keeps every reply.
        """
        wanted = {index for index, row in enumerate(self.model.pages)
                  if self.model.mark_edits.for_page(row.uid)}
        wanted.update(self.reader.canvas.pages_with_replies())
        if not wanted:
            return
        data = self.reader.document_bytes()
        if data is None:
            return
        for index in sorted(wanted):
            if not 0 <= index < len(self.model.pages):
                continue
            uid = self.model.pages[index].uid
            self.reader.canvas.repaint_edited(
                index, markup.one_page_with_edits(
                    data, index, self.model.mark_edits.for_page(uid),
                    hide_replies=True))

    def _invalidate_reader(self):
        """An edit happened; the snapshot no longer matches the page list."""
        self._reader_stale = True
        if self.read_mode and not self._reader_keeps_showing:
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

    # -- where the file dialogs start --------------------------------------

    #: Settings keys for the two remembered folders. Two rather than one
    #: because the place documents come from and the place they are written to
    #: are usually different, and a single memory makes each use retarget the
    #: other: read a PDF from Downloads and the next save goes there, save to a
    #: project folder and the next open starts there. Splitting them is also
    #: what the platforms assume -- Windows persists this state per use of the
    #: dialog (IFileDialog::SetClientGuid) and KDE by named keyword.
    #:
    #: Kept here rather than left to the native dialog, which does remember by
    #: itself on Windows and macOS: passing an explicit directory overrides
    #: that, and Qt's own dialog on Linux would not persist across launches, so
    #: doing it ourselves is the only way all three behave alike.
    SOURCE_FOLDER = "files/source"
    OUTPUT_FOLDER = "files/output"

    def _folder(self, key: str) -> str:
        """A remembered folder, or home if it has gone away.

        Checked rather than trusted: a folder on a disk that is no longer
        mounted makes the dialog open somewhere arbitrary.
        """
        remembered = self.settings.value(key, "", type=str)
        if remembered and os.path.isdir(remembered):
            return remembered
        return os.path.expanduser("~")

    def _remember_folder(self, key: str, path: str):
        """Record where ``path`` is, for the next dialog of that kind.

        In the settings rather than on the window, so a second window starts
        where the first one left off.
        """
        folder = path if os.path.isdir(path) else os.path.dirname(
            os.path.abspath(path))
        if os.path.isdir(folder):
            self.settings.setValue(key, folder)

    @property
    def source_dir(self) -> str:
        """Where documents were last opened from."""
        return self._folder(self.SOURCE_FOLDER)

    @property
    def output_dir(self) -> str:
        """Where something was last written to."""
        return self._folder(self.OUTPUT_FOLDER)

    def open_file(self):
        if not self._confirm_discard():
            return
        paths, _f = QFileDialog.getOpenFileNames(
            self, _("Open"), self.source_dir, IMPORT_FILTER)
        if paths:
            self.open_paths(paths)

    def import_files(self):
        paths, _f = QFileDialog.getOpenFileNames(
            self, _("Import"), self.source_dir, IMPORT_FILTER)
        if paths:
            if self._refuses_company(paths):
                return
            rows = self.view.selected_rows()
            at = rows[-1] + 1 if rows else None
            if self._load_paths(paths, at):
                self._mark_modified()

    def _import_files_at(self, paths, row):
        # A drop does not go through the menu, so the action being greyed out
        # does not stop it. This is where that route is closed.
        if self._refuses_company(paths):
            return
        if self._load_paths(paths, row if row >= 0 else None):
            self._mark_modified()

    def _signed_sources(self, pages=None):
        """Open source documents that carry a signature.

        Narrowed to the ones the given pages come from, so that exporting a
        selection which does not touch the signed document says nothing about
        signatures.
        """
        wanted = ({page.nfile for page in pages} if pages is not None
                  else set(range(1, len(self.docs.docs) + 1)))
        return [doc for number, doc in enumerate(self.docs.docs, start=1)
                if number in wanted and getattr(doc, "signed", False)]

    def _signed_paths(self, paths):
        """Which of these files carry a signature, asked before loading.

        A file that cannot be read, or that wants a password, answers no: the
        loader is about to say so properly, and refusing it here would report
        the wrong reason.
        """
        import pikepdf

        from . import forms

        found = []
        for path in paths:
            try:
                with pikepdf.open(path) as pdf:
                    if forms.is_signed(pdf):
                        found.append(path)
            except Exception:  # noqa: BLE001 - the loader reports its own
                continue
        return found

    def _refuses_company(self, paths) -> bool:
        """Whether these files may not be loaded beside anything else.

        A signed document is read-only, so it can neither be merged with
        another nor have one added to it: either way the result would be a
        document that cannot be saved, assembled out of files that could.
        Refused at the point the user asks, rather than by greying out the
        commands afterwards, so the reason is given once in words.

        Says nothing about opening a signed document on its own, which is the
        supported way to read one.
        """
        signed = self._signed_paths(paths)
        if signed:
            QMessageBox.information(self, APP_NAME, _(
                "%s is signed. A signed document is read only and cannot be "
                "combined with another, so open it on its own.")
                % os.path.basename(signed[0]))
            return True
        if self.read_only:
            QMessageBox.information(self, APP_NAME, _(
                "This document is signed, so it is read only and nothing can "
                "be added to it."))
            return True
        return False

    def _signed_file_at(self, path) -> bool:
        """Whether ``path`` is the file one of the signed sources came from."""
        try:
            target = os.path.realpath(path)
        except OSError:
            return False
        for doc in self._signed_sources():
            try:
                if os.path.realpath(doc.filename) == target:
                    return True
            except OSError:
                continue
        return False

    def save(self):
        if not self.current_path:
            return self.save_as()
        # Saving over a signed file is the one case this refuses outright: a
        # document built here is a new one, so overwriting leaves a broken
        # signature where a good one was, which no reader can tell from
        # tampering. Deriving a new file is allowed, and is what Acrobat tells
        # you to do as well -- "save a copy and reopen".
        if self._signed_file_at(self.current_path):
            QMessageBox.information(self, APP_NAME, _(
                "This document is signed. Saving over it would leave a broken "
                "signature in its place, so save it under another name."))
            return self.save_as()
        return self._write([self.current_path], self.model.pages,
                           outline=self.model.outline)

    def save_as(self):
        start = self.current_path or os.path.join(self.output_dir, "output.pdf")
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
        start = os.path.join(self.output_dir, "selection.pdf")
        path, _f = QFileDialog.getSaveFileName(self, _("Export…"), start, PDF_FILTER)
        if path:
            self._write([path], [self.model.pages[r] for r in rows],
                        mark_saved=False, outline=self.model.outline)

    def _write(self, files_out, pages, mark_saved=True, outline=None) -> bool:
        """Write ``pages`` out. ``outline`` is the document's bookmarks.

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
                # And what has been filled into the form, for the same reason.
                form_values=self.model.form_values,
                # And the marks added to it, which are owned the same way.
                annotations=self.model.annotations,
                mark_edits=self.model.mark_edits,
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
        self._remember_folder(self.OUTPUT_FOLDER, files_out[0])
        self.statusBar().showMessage(_("Saved") + f" {files_out[0]}", 4000)
        # Said once the file is written, because it is a fact about the file
        # that was just written rather than a reason not to write it.
        if self._signed_sources(pages):
            QMessageBox.information(self, APP_NAME, _(
                "The signature has not been carried over. Only the original "
                "file is signed; this is a new document."))
        return True

    def close_document(self):
        if not self._confirm_discard():
            return
        self._reset_document()
        # The mode is kept. Closing a document does not change what the window
        # is for, and the reader shows empty rather than stranding anyone now
        # that the toggle stays enabled without pages.
        self.reader.clear()
        self._show_outline_for_document()
        self._refresh_state()

    def _reset_document(self):
        # First, while there is still a document to remember and a path to
        # remember it against. This is how every way of letting one go ends --
        # File ▸ Close, and opening another over it -- so putting it here
        # covers them all; `closeEvent` has to do it separately because
        # quitting does not come through here.
        self._store_reading_position()
        # The note window belongs to the mark it was opened on, and there is
        # about to be no mark: closing the document left a thread floating
        # over an empty reader, still offering to post a reply to something
        # that is no longer there.
        self.note_panel.hide()
        self._noted = None
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
        # A new document: the panel follows it again rather than staying open
        # because the last one was asked to show it.
        self._outline_asked_for = False
        self.search.invalidate()
        # The outline goes with the document it came from. It is not derived
        # from the page list any more, so emptying the pages does not
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
        and the bookmarks pointing at it come along. A pasted page is a
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
            self, _("Export…"), self.output_dir)
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
            # The audit earns its place most here: "no images" on its own
            # sounds like a refusal, and the breakdown turns it into an
            # answer -- the file is drawings, and this command cannot help.
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                where = compress.audit_pages(pages, self.docs)
            finally:
                QApplication.restoreOverrideCursor()
            told = [_("The selected pages contain no images to compress.")]
            QMessageBox.information(
                self, APP_NAME, "\n".join(told + self._audit_lines(where)))
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
            # While the dialog is still up: walking a 1,590-page document to
            # add up its streams is a couple of seconds, and a couple of
            # seconds after the dialog closes is another small silence.
            where = None if result.stopped else compress.audit_pages(
                pages, self.docs)
        finally:
            progress.close()
        if result.stopped or not result.changed:
            self.model.undo.discard_last()
        if result.stopped:
            return

        self._stamped(pages)
        self._report_compression(result, where)

    def _report_compression(self, result, where=None):
        """Say what happened, in the terms that mean anything.

        Images that could not be re-encoded are counted rather than listed:
        the reasons are technical -- JPEG 2000, ink channels, a soft mask --
        and what a user needs to know is that those pages were left exactly as
        they were.

        Then where the bytes are now, which is the half that says what to do
        next. A file that is still mostly images can be run again at a lower
        setting; one that has become mostly drawings cannot be helped by this
        command at all, and saying so is worth more than another percentage.
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
        lines += self._audit_lines(where)
        QMessageBox.information(self, APP_NAME, "\n".join(lines))

    @staticmethod
    def _audit_lines(where):
        """The document's bytes by kind, largest first, nothing empty."""
        if not where or not sum(where.values()):
            return []
        names = {
            compress.AUDIT_IMAGES: _("images"),
            compress.AUDIT_CONTENT: _("drawings and text"),
            compress.AUDIT_FONTS: _("fonts"),
            compress.AUDIT_OTHER: _("everything else"),
        }
        total = sum(where.values())
        lines = ["", _("Where the bytes are now:")]
        for kind, size in sorted(where.items(), key=lambda row: -row[1]):
            if size:
                # No msgid for the row: a name, a size and a percentage need
                # no grammar, and three more strings to translate would say
                # nothing that the layout does not.
                lines.append(f"    {names[kind]}  {compress.human_size(size)}"
                             f"  ({round(100 * size / total)}%)")
        return lines

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
            self, _("Repair Document…"), self.source_dir, PDF_FILTER)
        if not path:
            return
        self._remember_folder(self.SOURCE_FOLDER, path)
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
        self._remember_folder(self.OUTPUT_FOLDER, out)
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
            self, _("Export…"), self.output_dir)
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
        if written:
            self._remember_folder(self.OUTPUT_FOLDER, paths[0])
        self.statusBar().showMessage(
            ngettext("%d image written", "%d images written", written) % written, 4000)

    def export_rasterised(self, image_format):
        rows = self.view.selected_rows()
        if not rows:
            return
        start = os.path.join(self.output_dir, "rasterised.pdf")
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
            self._remember_folder(self.OUTPUT_FOLDER, path)
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

    # -- filling in a form -------------------------------------------------

    def _field_value(self, field):
        """What the application says this field holds, or None for the file.

        The canvas asks this to decide which appearance to draw, so an edit
        shows the moment it is made: nothing is written to any document until
        the save.
        """
        page = self._page_for_field(field)
        if page is None:
            return None
        return self.model.form_values.get(page.nfile, field.name)

    def _page_for_field(self, field):
        """Which of our pages the field's widget is drawn on.

        The reader shows one document made of our pages, so its page index is
        a row in the page list, and the row is what knows which *source*
        document the field belongs to. That is the other half of the key: a
        field name alone is only unique within a document.
        """
        if 0 <= field.page < len(self.model.pages):
            return self.model.pages[field.page]
        return None

    def _field_locked(self, field) -> bool:
        """Whether this field's document refuses to be filled in.

        A signature is the only reason so far. Asked of the source document
        rather than of the one on screen, because the one on screen is an
        export and export does not carry a signature over.
        """
        page = self._page_for_field(field)
        if page is None:
            return False
        if 0 < page.nfile <= len(self.docs.docs):
            return bool(self.docs.docs[page.nfile - 1].signed)
        return False

    def field_refused(self, field):
        """A field was clicked in a document that will not take the edit.

        Saying so beats doing nothing: a field that quietly ignores a click
        looks broken, and this one is refusing for a reason the user cannot
        otherwise see.
        """
        self.statusBar().showMessage(
            _("This document is signed. Filling a field would break the "
              "signature."), 6000)

    def field_edited(self, field, text: str):
        """A text field was typed into and the editor closed."""
        page = self._page_for_field(field)
        if page is None or not field.fillable or self._field_locked(field):
            return
        current = self.model.form_values.get(page.nfile, field.name,
                                             field.value)
        if text == (current or ""):
            return                      # closed without changing anything
        self.model.undo.commit(_("Fill Field"))
        self.model.form_values.set(page.nfile, field.name, text)
        if 0 < page.nfile <= len(self.docs.docs):
            self.docs.docs[page.nfile - 1].forget_render_copy()
        self._field_filled()
        self.reader.canvas.viewport().update()

    def field_pressed(self, field):
        """A form field was clicked. Tick boxes toggle; text opens an editor."""
        page = self._page_for_field(field)
        if page is None or not field.fillable or self._field_locked(field):
            return
        if field.kind != "/Btn":
            return          # text and choice go through the canvas's editor
        current = self.model.form_values.get(page.nfile, field.name, field.value)
        wanted = self._toggled(field, current)
        if wanted is None:
            return
        self.model.undo.commit(_("Fill Field"))
        self.model.form_values.set(page.nfile, field.name, wanted)
        # The grid draws from a rewritten copy with the old value baked in, so
        # it has to be rebuilt. Lazily: nothing happens until a thumbnail is
        # next wanted, and the reader never comes here at all.
        if 0 < page.nfile <= len(self.docs.docs):
            self.docs.docs[page.nfile - 1].forget_render_copy()
        self._field_filled()
        # The page bitmap is unchanged -- only which appearance is drawn over
        # it -- so a repaint is the whole of showing it.
        self.reader.canvas.viewport().update()

    def _field_filled(self):
        """Tell everything that a field's value changed.

        `model.touch` is what the *grid* needs: its thumbnails are drawn from
        a rewritten copy with the old value baked in. But touching also emits
        `contents_changed`, and the reader listens to that and rebuilds its
        whole document -- which it does not need. The canvas composites fields
        from the values held here rather than from the file, which is the
        entire reason a tick is a repaint: 1 ms against the 682 ms a rewrite
        costs on a large form. Rebuilding also lost the reader's place, since
        a fresh document is laid out from provisional page sizes and the
        scrollbar is clamped into the shorter range.

        So the reader is marked stale and left showing what it has. It is
        already right, because it draws the value itself; the snapshot is
        rebuilt on the next entry into read mode, or by the next edit that
        really does change the pages.
        """
        self._reader_keeps_showing = True
        try:
            self.model.touch(range(len(self.model.pages)))
        finally:
            self._reader_keeps_showing = False
        self._mark_modified()

    @staticmethod
    def _toggled(field, current):
        """The state this widget should show after being clicked, or None.

        A tick box turns itself off again; a radio button does not. Pressing
        the member of a group that is already chosen leaves it chosen, which
        is what every radio group anywhere does, and is why they are not the
        same gesture.
        """
        on = field.states[0] if field.states else None
        if on is None:
            return None
        showing = field.state_for(current)
        if field.is_radio:
            return on
        return "/Off" if showing == on else on

    # -- find --------------------------------------------------------------

    #: Where the options live between sessions, so a window opens how the last
    #: one was left.
    FIND_SETTINGS = {"case_sensitive": "find/case-sensitive",
                     "whole_word": "find/whole-word",
                     "regex": "find/regex"}

    def find_text(self):
        """Show the find dialog, or bring it back to the front.

        Modeless, so it is not shown with exec(): the window carries on, the
        dialog sits on top, and Next moves the document behind it.
        """
        if self._find_dialog is None:
            self._find_dialog = dialogs.FindDialog(self)
            self._find_dialog.set_query(self._stored_query())
            self._find_dialog.wrap.setChecked(
                self.settings.value("find/wrap", True, type=bool))
            self._find_dialog.query_changed.connect(self._dialog_asked)
            self._find_dialog.step.connect(self.find_step)
            self._find_dialog.go_to.connect(self._find_go)
            self._find_dialog.wrap.toggled.connect(
                lambda on: self.settings.setValue("find/wrap", bool(on)))
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.activateWindow()
        self._find_dialog.focus_field()

    def _stored_query(self) -> Query:
        return Query(self.search.phrase,
                     **{name: self.settings.value(key, False, type=bool)
                        for name, key in self.FIND_SETTINGS.items()})

    def _dialog_asked(self, query: Query):
        """The dialog's field or options changed."""
        for name, key in self.FIND_SETTINGS.items():
            self.settings.setValue(key, getattr(query, name))
        if not query:
            # Clearing the field clears the highlights, rather than leaving the
            # last search drawn over a document nobody is searching any more.
            self._run_search(query)
            return
        self._run_search(query)
        if self.search.count():
            self._find_go(self.search.first_at_or_after(self._page_now()))

    def _page_now(self) -> int:
        """Where "find from here" starts from, in either mode."""
        if self.read_mode:
            return self.reader.current_page()
        rows = self.view.selected_rows()
        return rows[0] if rows else 0

    def _run_search(self, query):
        """Build the index for a query and publish it to the grid and reader."""
        if isinstance(query, str):
            query = Query(query)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            matches = self.search.search(query, self.model.pages,
                                         self.docs.files_for_export())
        finally:
            QApplication.restoreOverrideCursor()
        self._find_cursor = -1
        # The grid draws the hits itself, from rectangles in the edited page's
        # own points, and asks for them a row at a time; the reader searches
        # its own document, because it highlights in that document's geometry.
        self.model.set_match_rows(matches, self.search.rectangles)
        self.reader.search(query)
        self._report_search(matches)
        self._refresh_find_dialog()
        return matches

    def _report_search(self, matches):
        count = self.search.count()
        error = self.search.error
        if error:
            self.statusBar().showMessage(_("Not a valid pattern: %s") % error, 5000)
        elif not self.search.phrase:
            self.statusBar().clearMessage()
        elif not count:
            self.statusBar().showMessage(_("No matches"), 5000)
        else:
            # Both numbers, because "22 pages match" was the thing that left
            # nowhere to go: it never said there were 44 places to look.
            self.statusBar().showMessage(
                _("%(matches)s on %(pages)s") % {
                    "matches": ngettext("%d match", "%d matches", count) % count,
                    "pages": ngettext("%d page", "%d pages",
                                      len(matches)) % len(matches)}, 5000)

    def _refresh_find_dialog(self):
        if self._find_dialog is None:
            return
        error = self.search.error
        if error:
            self._find_dialog.set_error(error, self.search.phrase)
            return
        self._find_dialog.set_results(self.search.hits(), self.search.count(),
                                      labels=self._page_label,
                                      phrase=self.search.phrase)
        self._find_dialog.set_position(self._find_cursor, self.search.count())

    def _page_label(self, page: int) -> str:
        """What to call a page in the results list."""
        return str(page + 1)

    def _find_invalidated(self):
        """An edit moved the pages; the hits no longer point anywhere.

        The phrase and the options survive, so Find Next rebuilds the index and
        carries on -- it is the positions that are gone, not the search.
        """
        self._find_cursor = -1
        if self._find_dialog is not None:
            self._find_dialog.set_results([], 0)

    def find_step(self, forward: bool):
        """Move to the next or previous hit, in whichever mode is showing."""
        if not self.search.count() and self.search.phrase:
            self._run_search(self.search.query)
        count = self.search.count()
        if not count:
            self._report_search(self.search.matches)
            return
        if self._find_cursor < 0:
            self._find_go(self.search.first_at_or_after(self._page_now()))
            return
        nxt = self._find_cursor + (1 if forward else -1)
        if not 0 <= nxt < count:
            if not self._find_wraps():
                self.statusBar().showMessage(
                    _("Last match") if forward else _("First match"), 3000)
                return
            nxt %= count
        self._find_go(nxt)

    def _find_wraps(self) -> bool:
        if self._find_dialog is not None:
            return self._find_dialog.wraps()
        return self.settings.value("find/wrap", True, type=bool)

    def _find_go(self, index: int):
        """Show one hit: scroll the reader to it, and select its page."""
        hit = self.search.hit(index)
        if hit is None:
            return
        self._find_cursor = index
        # The row is selected in both modes, so that leaving reading mode lands
        # on the page the hit was found on rather than wherever the grid was.
        self.view.set_selected_rows([hit.page])
        if self.read_mode:
            # Carried across by position: the reader searched its own copy of
            # the document, so its hit list is built separately from this one.
            self.reader.show_search_result(
                self.reader.index_of_hit(hit.page, hit.start))
        if self._find_dialog is not None:
            self._find_dialog.set_position(index, self.search.count())
        self.statusBar().showMessage(
            _("%(number)d of %(total)d") % {"number": index + 1,
                                            "total": self.search.count()}, 5000)

    def find_all(self):
        """Select every page that matches, which is the grid's own question."""
        if not self.search.phrase:
            self.find_text()
            return
        matches = self._run_search(self.search.query)
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
        self.settings.setValue("reader/outline-width", self.reader.outline_width())
        # Where you had got to, before the reader is torn down. Switching to
        # the grid used to be the only thing that stored it, so quitting from
        # read mode -- which is how reading ends -- saved nothing, and the next
        # open restored a position from whenever the view was last switched,
        # possibly sessions ago.
        self._store_reading_position()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        # Belt and braces, not a fix for anything observed: a normal quit does
        # flush these, because QSettings syncs from its destructor and from an
        # idle event loop. It is here for the exit that is not normal -- if the
        # process aborts during interpreter shutdown, as it does when a thread
        # outlives the window -- Qt calls qFatal from ~QThread for a thread
        # still running -- the destructor never runs.
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
        # The pages go before the documents they point into, the same order
        # and for the same reason as `_reset_document`. Dropping the documents
        # first leaves every Page naming an `nfile` with nothing behind it,
        # and any thumbnail request that then arrives -- a queued relayout, a
        # scroll callback -- looks it up and raises.
        self.model.set_pages([])
        self.docs.cleanup()
        super().closeEvent(event)
