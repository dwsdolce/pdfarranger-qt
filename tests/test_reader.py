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

"""Read mode (phase 6).

The reader is a Qt widget over PDFium, so the assertions worth making are about
wiring rather than pixels — above all that what it shows is the *edited* page
list and not the source file, which is what D15 turns on.
"""

import os
import unittest

from pdfarranger_qt.core import DocumentSet
from pdfarranger_qt.reader import ReaderView

from support import HERE, MESSAGE_BOXES, TEST_PDF, TEXT_PDF, settle

#: Four pages, and the only fixture with a real bookmark tree.
OUTLINE_PDF = os.path.join(HERE, "exporter", "outlines.pdf")


class TestReaderView(unittest.TestCase):
    """The widget on its own, without a window around it."""

    def setUp(self):
        self.docs = DocumentSet()
        self.reader = ReaderView()
        self.addCleanup(self.docs.cleanup)
        self.addCleanup(self.reader.clear)

    def load(self, path):
        pages = self.docs.add_file(path)
        self.assertTrue(self.reader.load(pages, self.docs.files_for_export()))
        return pages

    def test_loads_a_document(self):
        self.load(TEST_PDF)
        self.assertEqual(self.reader.page_count(), 2)

    def test_clear_is_idempotent(self):
        self.load(TEST_PDF)
        self.reader.clear()
        self.reader.clear()
        self.assertEqual(self.reader.page_count(), 0)

    def test_reloading_replaces_the_document(self):
        """The old MemoryDocument must not be closed while the view holds it."""
        self.load(TEST_PDF)
        pages = self.docs.add_file(OUTLINE_PDF)
        self.assertTrue(self.reader.load(pages, self.docs.files_for_export()))
        self.assertEqual(self.reader.page_count(), 4)

    def test_navigation_clamps(self):
        self.load(TEST_PDF)
        self.reader.go_to_page(99)
        self.assertEqual(self.reader.current_page(), 1)
        self.reader.go_to_page(-5)
        self.assertEqual(self.reader.current_page(), 0)

    def test_zoom_is_bounded(self):
        from pdfarranger_qt.reader import ZOOM_LIMITS

        self.load(TEST_PDF)
        self.reader.set_zoom(1000)
        self.assertLessEqual(self.reader.zoom(), ZOOM_LIMITS[1])
        self.reader.set_zoom(0.0001)
        self.assertGreaterEqual(self.reader.zoom(), ZOOM_LIMITS[0])

    def test_outline_populates(self):
        """Needs get_in_memory_pdf(outlines=True); it is off by default."""
        self.load(OUTLINE_PDF)
        self.assertTrue(self.reader.has_outline())
        self.assertEqual(self.reader.outline_labels(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_no_outline_when_the_document_has_none(self):
        self.load(TEST_PDF)
        self.assertFalse(self.reader.has_outline())
        self.assertEqual(self.reader.outline_labels(), [])

    def test_clicking_a_bookmark_jumps(self):
        from PySide6.QtCore import QModelIndex

        self.load(OUTLINE_PDF)
        index = self.reader.bookmarks.index(2, 0, QModelIndex())
        self.reader._go_to_bookmark(index)
        self.assertEqual(self.reader.current_page(), 2)

    def test_search_highlights_in_place(self):
        self.load(TEXT_PDF)
        self.reader.search("tests")
        self.assertEqual(self.reader.search_phrase(), "tests")
        self.assertGreater(self.reader.matches_on_page(0), 0)

    def test_search_for_nothing_finds_nothing(self):
        self.load(TEXT_PDF)
        self.reader.search("zzzznotpresent")
        self.assertEqual(self.reader.matches_on_page(0), 0)

    def test_describe_reports_the_position(self):
        self.load(OUTLINE_PDF)
        self.reader.go_to_page(2)
        self.assertIn("3", self.reader.describe())
        self.assertIn("4", self.reader.describe())


class TestReaderShowsTheEdits(unittest.TestCase):
    """D15: the reader renders the page list, not the file on disk."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_deleted_pages_are_not_in_the_reader(self):
        """The source file still has two pages; the reader must show one."""
        self.win.view.set_selected_rows([0])
        self.win.delete_selected()
        self.assertEqual(self.win.model.rowCount(), 1)
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.page_count(), 1)

    def test_rotation_reaches_the_reader(self):
        """A rotated page swaps width and height in the rendered document."""
        from PySide6.QtCore import QSizeF

        self.win.set_read_mode(True)
        before = self.win.reader._document.document.pagePointSize(0)
        self.win.set_read_mode(False)

        self.win.view.set_selected_rows([0])
        self.win.rotate(90)
        self.win.set_read_mode(True)
        after = self.win.reader._document.document.pagePointSize(0)

        self.assertIsInstance(before, QSizeF)
        self.assertAlmostEqual(after.width(), before.height(), places=1)
        self.assertAlmostEqual(after.height(), before.width(), places=1)

    def test_an_edit_while_reading_rebuilds_the_snapshot(self):
        """Otherwise the reader would silently disagree with the document."""
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.page_count(), 2)
        self.win.model.set_pages(self.win.model.pages[:1])
        settle(timeout_ms=200)
        self.assertEqual(self.win.reader.page_count(), 1)

    def test_an_edit_in_the_grid_dates_the_snapshot(self):
        self.win.set_read_mode(True)
        self.win.set_read_mode(False)
        self.win.view.set_selected_rows([0])
        self.win.duplicate_selected()
        self.assertTrue(self.win._reader_stale)
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.page_count(), 3)


class TestReadModeSwitch(unittest.TestCase):
    """The mode itself: gating, focus, and refusing to read nothing."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_grid_is_the_default(self):
        self.assertFalse(self.win.read_mode)
        self.assertIs(self.win.stack.currentWidget(), self.win.view)

    def test_switching_swaps_the_central_widget(self):
        self.win.set_read_mode(True)
        self.assertIs(self.win.stack.currentWidget(), self.win.reader)
        self.win.set_read_mode(False)
        self.assertIs(self.win.stack.currentWidget(), self.win.view)

    def test_editing_actions_are_disabled_while_reading(self):
        editing = [self.win.act_rotate_left, self.win.act_delete,
                   self.win.act_duplicate, self.win.act_crop,
                   self.win.act_reverse, self.win.act_merge_pages,
                   self.win.act_paste, self.win.act_password]
        self.win.set_read_mode(True)
        for action in editing:
            self.assertFalse(action.isEnabled(), action.text())
        self.win.set_read_mode(False)
        self.assertTrue(self.win.act_rotate_left.isEnabled())

    def test_harmless_actions_stay_enabled(self):
        """Find and Preferences change nothing, so reading should not stop them."""
        self.win.set_read_mode(True)
        for action in (self.win.act_find, self.win.act_preferences,
                       self.win.act_copy):
            self.assertTrue(action.isEnabled(), action.text())

    def test_the_gate_is_derived_not_hand_listed(self):
        """A new editing command must be disabled without anyone remembering."""
        names = {a.text() for a in self.win._editing_actions()}
        for expected in ("Rotate &Left", "&Delete", "Reverse Order"):
            self.assertIn(expected, names)
        for never in ("&Find…", "Preferences", "&About"):
            self.assertNotIn(never, names)

    def test_read_mode_refuses_an_empty_document(self):
        self.win.close_document()
        self.win.act_read_mode.setChecked(True)
        self.win.set_read_mode(True)
        self.assertFalse(self.win.read_mode)
        self.assertFalse(self.win.act_read_mode.isChecked())

    def test_search_phrase_carries_into_read_mode(self):
        self.win.open_paths([TEXT_PDF])
        self.win._run_search("tests")
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.search_phrase(), "tests")


class TestReadingPosition(unittest.TestCase):
    """Where you were, per document."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_position_survives_leaving_and_returning(self):
        self.win.set_read_mode(True)
        self.win.reader.go_to_page(2)
        self.win.set_read_mode(False)
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.current_page(), 2)

    def test_position_is_keyed_on_the_document(self):
        key = self.win._reading_key()
        self.assertIsNotNone(key)
        self.assertTrue(key.startswith("reading/"))
        self.assertIn("outlines.pdf", key.lower())

    def test_an_unsaved_document_has_nowhere_to_remember(self):
        self.win.current_path = None
        self.assertIsNone(self.win._reading_key())
        self.win.set_read_mode(True)      # must not raise
        self.win.set_read_mode(False)

    def test_a_stored_page_past_the_end_is_clamped(self):
        """An edit can delete the page you were on since you last read it."""
        self.win.settings.setValue(self.win._reading_key(), 99)
        self.win.set_read_mode(True)
        self.assertEqual(self.win.reader.current_page(),
                         self.win.reader.page_count() - 1)

class TestModeAffordances(unittest.TestCase):
    """A mode needs to be findable, and visibly on once you are in it."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def button(self, action):
        widget = self.win.toolbar.widgetForAction(action)
        return None if widget is None else widget.isVisibleTo(self.win.toolbar)

    def test_the_toolbar_offers_the_mode(self):
        """Menu-only would leave it undiscoverable."""
        self.assertIn(self.win.act_read_mode, self.win.toolbar.actions())
        self.assertTrue(self.win.act_read_mode.isCheckable())

    def test_the_status_bar_says_which_mode(self):
        """showMessage() expires; this must not."""
        self.assertEqual(self.win.status_mode.text(), "")
        self.win.set_read_mode(True)
        self.assertEqual(self.win.status_mode.text(), "Reading")
        self.win.set_read_mode(False)
        self.assertEqual(self.win.status_mode.text(), "")

    def test_editing_buttons_are_hidden_while_reading(self):
        self.assertTrue(self.button(self.win.act_rotate_left))
        self.win.set_read_mode(True)
        self.assertFalse(self.button(self.win.act_rotate_left))
        self.assertFalse(self.button(self.win.act_undo))
        # Open and Save still make sense in a reader.
        self.assertTrue(self.button(self.win.act_open))
        self.win.set_read_mode(False)
        self.assertTrue(self.button(self.win.act_rotate_left))

    def test_hiding_buttons_does_not_empty_the_menus(self):
        """QAction.setVisible(False) hides it everywhere, including Page."""
        self.win.set_read_mode(True)
        for top in self.win.menuBar().actions():
            if "Page" in top.text():
                labels = [a.text() for a in top.menu().actions()
                          if not a.isSeparator() and a.isVisible()]
                self.assertTrue(any("Rotate" in x for x in labels), labels)
                return
        self.fail("no Page menu")


class TestStatusPath(unittest.TestCase):
    """Where the open document is. Neither the title nor Open Recent says."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_empty_with_no_document(self):
        self.assertEqual(self.win.status_path.text(), "")
        self.assertEqual(self.win.status_path.toolTip(), "")

    def test_shows_the_full_path_as_a_tooltip(self):
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        self.assertEqual(self.win.status_path.toolTip(), os.path.abspath(TEST_PDF))

    def test_visible_text_is_elided_not_truncated(self):
        """Elided in the middle, so the drive and the filename both survive."""
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        text = self.win.status_path.text()
        self.assertTrue(text)
        self.assertTrue(text.endswith("test.pdf"), text)

    def test_it_updates_when_the_document_changes(self):
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        first = self.win.status_path.toolTip()
        self.win.open_paths([TEXT_PDF])
        self.win.modified = False
        self.assertNotEqual(self.win.status_path.toolTip(), first)
        self.assertEqual(self.win.status_path.toolTip(), os.path.abspath(TEXT_PDF))

    def test_it_is_selectable(self):
        """So the path can be copied out, which is half the point of showing it."""
        from PySide6.QtCore import Qt

        self.assertTrue(self.win.status_path.textInteractionFlags()
                        & Qt.TextSelectableByMouse)
