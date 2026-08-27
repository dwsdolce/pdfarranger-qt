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

    def test_the_toolbar_offers_the_mode(self):
        """Menu-only would leave it undiscoverable, and it must be in both."""
        for bar in (self.win.toolbar, self.win.reader_toolbar):
            self.assertIn(self.win.act_read_mode, bar.actions())
        self.assertTrue(self.win.act_read_mode.isCheckable())

    def test_the_status_bar_says_which_mode(self):
        """showMessage() expires; this must not."""
        self.assertEqual(self.win.status_mode.text(), "")
        self.win.set_read_mode(True)
        self.assertEqual(self.win.status_mode.text(), "Reading")
        self.win.set_read_mode(False)
        self.assertEqual(self.win.status_mode.text(), "")

    def test_the_toolbars_swap_with_the_mode(self):
        """One toolbar per mode, rather than one full of dead buttons.

        Asserted on the toolbars' own visibility. An earlier version of this
        test asked widgetForAction(...).isVisibleTo(), which reports what
        *would* be shown and so passed against a toolbar that was visibly
        greyed out rather than hidden.
        """
        self.assertTrue(self.win.toolbar.isVisible())
        self.assertFalse(self.win.reader_toolbar.isVisible())
        self.win.set_read_mode(True)
        self.assertFalse(self.win.toolbar.isVisible())
        self.assertTrue(self.win.reader_toolbar.isVisible())
        self.win.set_read_mode(False)
        self.assertTrue(self.win.toolbar.isVisible())
        self.assertFalse(self.win.reader_toolbar.isVisible())

    def test_editing_commands_are_only_on_the_arrange_toolbar(self):
        for action in (self.win.act_rotate_left, self.win.act_delete,
                       self.win.act_undo, self.win.act_duplicate):
            self.assertIn(action, self.win.toolbar.actions(), action.text())
            self.assertNotIn(action, self.win.reader_toolbar.actions(),
                             action.text())

    def test_open_and_save_are_on_both(self):
        """The way out of a mode should not move."""
        for action in (self.win.act_open, self.win.act_save,
                       self.win.act_read_mode):
            for bar in (self.win.toolbar, self.win.reader_toolbar):
                self.assertIn(action, bar.actions(), action.text())

    def test_swapping_toolbars_does_not_empty_the_menus(self):
        """Menus grey rather than hide; only the toolbars swap."""
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

class TestContinuousScroll(unittest.TestCase):
    """One page at a time, or a continuous scroll.

    Not merely a preference. QPdfView renders a page on demand at full display
    resolution and draws nothing until that render arrives -- measured at
    48-58ms a page on a dense 1590-page book, so roughly 17-20 pages a second.
    Scroll faster and pages go blank until it catches up. Showing one page at a
    time renders one page at a time, which does not.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.settings.setValue("reader/continuous", True)
        self.win.modified = False
        self.win.close()

    def test_continuous_by_default(self):
        self.assertTrue(self.win.reader.continuous())

    def test_the_toggle_switches_the_page_mode(self):
        from PySide6.QtPdfWidgets import QPdfView

        self.win.set_continuous_scroll(False)
        self.assertFalse(self.win.reader.continuous())
        self.assertEqual(self.win.reader.pdf_view.pageMode(),
                         QPdfView.PageMode.SinglePage)
        self.win.set_continuous_scroll(True)
        self.assertEqual(self.win.reader.pdf_view.pageMode(),
                         QPdfView.PageMode.MultiPage)

    def test_the_action_follows_the_state(self):
        self.win.set_continuous_scroll(False)
        self.assertFalse(self.win.act_continuous.isChecked())
        self.win.set_continuous_scroll(True)
        self.assertTrue(self.win.act_continuous.isChecked())

    def test_it_only_applies_while_reading(self):
        self.assertFalse(self.win.act_continuous.isEnabled())
        self.win.set_read_mode(True)
        self.assertTrue(self.win.act_continuous.isEnabled())
        self.win.set_read_mode(False)
        self.assertFalse(self.win.act_continuous.isEnabled())

    def test_the_choice_is_remembered(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win.set_continuous_scroll(False)
        other = MainWindow()
        self.addCleanup(other.close)
        other.modified = False
        self.assertFalse(other.reader.continuous())
        self.assertFalse(other.act_continuous.isChecked())

    def test_paging_still_works_in_single_page_mode(self):
        self.win.set_read_mode(True)
        self.win.set_continuous_scroll(False)
        self.win.reader.go_to_page(2)
        self.assertEqual(self.win.reader.current_page(), 2)

class TestPageNavigation(unittest.TestCase):
    """QPdfView only scrolls; a reader has to actually turn pages.

    In SinglePage mode there is nowhere to scroll, so before this every key did
    nothing at all and the mode was unusable. Home and End were unhandled in
    both modes.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])      # four pages
        self.win.modified = False
        settle(timeout_ms=300)
        self.win.set_read_mode(True)

    def tearDown(self):
        self.win.settings.setValue("reader/continuous", True)
        self.win.modified = False
        self.win.close()

    def press(self, key):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        view = self.win.reader.pdf_view
        for kind in (QKeyEvent.KeyPress, QKeyEvent.KeyRelease):
            QApplication.sendEvent(view, QKeyEvent(kind, key, Qt.NoModifier))

    def test_the_keys_turn_pages_in_single_page_mode(self):
        from PySide6.QtCore import Qt

        self.win.set_continuous_scroll(False)
        self.win.reader.go_to_page(0)
        self.press(Qt.Key_PageDown)
        self.assertEqual(self.win.reader.current_page(), 1)
        self.press(Qt.Key_PageUp)
        self.assertEqual(self.win.reader.current_page(), 0)

    def test_home_and_end_work_in_both_modes(self):
        from PySide6.QtCore import Qt

        for continuous in (True, False):
            with self.subTest(continuous=continuous):
                self.win.set_continuous_scroll(continuous)
                self.win.reader.go_to_page(1)
                self.press(Qt.Key_End)
                self.assertEqual(self.win.reader.current_page(),
                                 self.win.reader.page_count() - 1)
                self.press(Qt.Key_Home)
                self.assertEqual(self.win.reader.current_page(), 0)

    def test_navigation_clamps_at_both_ends(self):
        self.win.reader.first_page()
        self.win.reader.previous_page()
        self.assertEqual(self.win.reader.current_page(), 0)
        self.win.reader.last_page()
        self.win.reader.next_page()
        self.assertEqual(self.win.reader.current_page(),
                         self.win.reader.page_count() - 1)

    def test_the_menu_commands_navigate(self):
        self.win.reader.go_to_page(0)
        self.win.act_next_page.trigger()
        self.assertEqual(self.win.reader.current_page(), 1)
        self.win.act_prev_page.trigger()
        self.assertEqual(self.win.reader.current_page(), 0)
        self.win.act_last_page.trigger()
        self.assertEqual(self.win.reader.current_page(), 3)
        self.win.act_first_page.trigger()
        self.assertEqual(self.win.reader.current_page(), 0)

    def test_navigation_is_disabled_outside_read_mode(self):
        self.win.set_read_mode(False)
        for action in (self.win.act_next_page, self.win.act_prev_page,
                       self.win.act_first_page, self.win.act_last_page,
                       self.win.act_go_to_page):
            self.assertFalse(action.isEnabled(), action.text())

    def test_the_page_shortcuts_are_not_taken_from_the_grid(self):
        """Bare PageUp/PageDown belong to whichever view has focus."""
        from PySide6.QtGui import QKeySequence

        for action in (self.win.act_next_page, self.win.act_prev_page):
            sequence = action.shortcut().toString()
            self.assertTrue(sequence.startswith("Ctrl+"), sequence)
        self.assertEqual(self.win.act_next_page.shortcut(),
                         QKeySequence("Ctrl+PgDown"))

    def test_go_to_page_jumps(self):
        from PySide6.QtWidgets import QInputDialog

        original = QInputDialog.getInt
        QInputDialog.getInt = lambda *a, **k: (3, True)
        self.addCleanup(setattr, QInputDialog, "getInt", original)
        self.win.go_to_page()
        self.assertEqual(self.win.reader.current_page(), 2)   # 1-based in the UI

    def test_go_to_page_cancelled_stays_put(self):
        from PySide6.QtWidgets import QInputDialog

        self.win.reader.go_to_page(1)
        original = QInputDialog.getInt
        QInputDialog.getInt = lambda *a, **k: (4, False)
        self.addCleanup(setattr, QInputDialog, "getInt", original)
        self.win.go_to_page()
        self.assertEqual(self.win.reader.current_page(), 1)

class TestPageSelector(unittest.TestCase):
    """The page box on the toolbar: where you are, and where to go."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])      # four pages
        self.win.modified = False
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_it_lives_on_the_reader_toolbar(self):
        self.assertFalse(self.win.reader_toolbar.isVisible())
        self.assertEqual(self.win.toolbar_page_total.text(), "")

    def test_it_appears_while_reading(self):
        self.win.set_read_mode(True)
        self.assertTrue(self.win.reader_toolbar.isVisible())
        self.assertTrue(self.win.reader.page_selector.isVisible())
        self.assertEqual(self.win.toolbar_page_total.text(), "of 4")

    def test_it_follows_the_view(self):
        self.win.set_read_mode(True)
        self.win.reader.go_to_page(2)
        self.assertEqual(self.win.reader.page_selector.currentPage(), 2)

    def test_the_view_follows_it(self):
        """Typing a page number is the point of having the box."""
        self.win.set_read_mode(True)
        self.win.reader.page_selector.setCurrentPage(3)
        self.assertEqual(self.win.reader.current_page(), 3)

    def test_it_does_not_bounce(self):
        """View and box each follow the other; neither may loop."""
        self.win.set_read_mode(True)
        self.win.reader.go_to_page(1)
        self.assertEqual(self.win.reader.current_page(), 1)
        self.assertEqual(self.win.reader.page_selector.currentPage(), 1)

    def test_the_total_tracks_the_document(self):
        self.win.set_read_mode(True)
        self.assertEqual(self.win.toolbar_page_total.text(), "of 4")
        self.win.set_read_mode(False)
        self.win.view.set_selected_rows([0])
        self.win.delete_selected()
        self.win.set_read_mode(True)
        self.assertEqual(self.win.toolbar_page_total.text(), "of 3")

    def test_the_label_can_differ_from_the_number(self):
        """Page labels are why this is Qt's widget and not a spin box."""
        self.win.set_read_mode(True)
        self.assertIsInstance(self.win.reader.page_label(), str)


class TestModeChangeKeepsYourPlace(unittest.TestCase):
    """Switching modes used to dump you back at the start.

    `currentPage()` went on reporting the old page while the scrollbar was
    reset near the top, so nothing in the interface admitted the view had
    moved.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.modified = False
        settle(timeout_ms=300)
        self.win.set_read_mode(True)

    def tearDown(self):
        self.win.settings.setValue("reader/continuous", True)
        self.win.modified = False
        self.win.close()

    def scroll(self):
        return self.win.reader.pdf_view.verticalScrollBar().value()

    def test_the_page_survives_both_directions(self):
        self.win.reader.go_to_page(2)
        self.win.set_continuous_scroll(False)
        self.assertEqual(self.win.reader.current_page(), 2)
        self.win.set_continuous_scroll(True)
        self.assertEqual(self.win.reader.current_page(), 2)

    def test_the_scroll_position_comes_back(self):
        """The page number alone was never the problem; this is."""
        self.win.reader.go_to_page(2)
        settle(timeout_ms=200)
        before = self.scroll()
        self.assertGreater(before, 0, "page 2 should not be at the very top")
        self.win.set_continuous_scroll(False)
        settle(timeout_ms=200)
        self.win.set_continuous_scroll(True)
        settle(timeout_ms=200)
        self.assertEqual(self.scroll(), before)

    def test_setting_the_same_mode_twice_does_nothing(self):
        self.win.reader.go_to_page(2)
        settle(timeout_ms=200)
        before = self.scroll()
        self.win.set_continuous_scroll(True)
        self.assertEqual(self.scroll(), before)

    def test_the_first_page_is_not_a_special_case(self):
        self.win.reader.go_to_page(0)
        self.win.set_continuous_scroll(False)
        self.assertEqual(self.win.reader.current_page(), 0)
        self.win.set_continuous_scroll(True)
        self.assertEqual(self.win.reader.current_page(), 0)

class TestZoomFollowsTheMode(unittest.TestCase):
    """The zoom commands have to drive whichever view is showing.

    They were wired straight to the grid, so in read mode Fit One Page, Fit
    Width, Zoom In/Out and Reset Zoom all silently rescaled thumbnails nobody
    could see. Two of them are on the reader's own toolbar.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1100, 800)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.modified = False
        settle(timeout_ms=300)
        self.win.set_read_mode(True)
        settle(timeout_ms=200)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def mode(self):
        return self.win.reader.pdf_view.zoomMode()

    def test_fit_one_page(self):
        from PySide6.QtPdfWidgets import QPdfView

        self.win.act_zoom_fit.trigger()
        self.assertEqual(self.mode(), QPdfView.ZoomMode.FitInView)

    def test_fit_width(self):
        from PySide6.QtPdfWidgets import QPdfView

        self.win.act_zoom_fit.trigger()
        self.win.act_zoom_fit_width.trigger()
        self.assertEqual(self.mode(), QPdfView.ZoomMode.FitToWidth)

    def test_zoom_in_and_out(self):
        self.win.act_zoom_in.trigger()
        zoomed = self.win.reader.zoom()
        self.assertGreater(zoomed, 1.0)
        self.win.act_zoom_out.trigger()
        self.assertLess(self.win.reader.zoom(), zoomed)

    def test_reset_zoom(self):
        self.win.act_zoom_in.trigger()
        self.win.act_zoom_reset.trigger()
        self.assertAlmostEqual(self.win.reader.zoom(), 1.0, places=3)

    def test_ctrl_wheel_zooms(self):
        """The grid zooms on ctrl+wheel; the same gesture must work here."""
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication

        view = self.win.reader.pdf_view
        before = view.zoomFactor()
        event = QWheelEvent(QPointF(100, 100), view.mapToGlobal(QPoint(100, 100)),
                            QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                            Qt.ControlModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view.viewport(), event)
        self.assertGreater(view.zoomFactor(), before)

    def test_the_grid_zoom_is_left_alone(self):
        """Zooming the reader must not quietly rescale the thumbnails."""
        before = self.win.model.zoom
        self.win.act_zoom_in.trigger()
        self.win.act_zoom_fit.trigger()
        self.win.act_zoom_fit_width.trigger()
        self.assertAlmostEqual(self.win.model.zoom, before, places=9)

    def test_fit_multiple_pages_is_grid_only(self):
        """QPdfView has FitInView, FitToWidth and Custom. No columns."""
        self.assertFalse(self.win.act_zoom_fit_multi.isEnabled())
        self.win.set_read_mode(False)
        self.assertTrue(self.win.act_zoom_fit_multi.isEnabled())

    def test_the_grid_still_zooms_when_it_is_showing(self):
        self.win.set_read_mode(False)
        before = self.win.model.zoom
        self.win.act_zoom_in.trigger()
        self.assertGreater(self.win.model.zoom, before)

    def test_the_reader_toolbar_carries_the_fit_commands(self):
        for action in (self.win.act_zoom_fit, self.win.act_zoom_fit_width):
            self.assertIn(action, self.win.reader_toolbar.actions(), action.text())


class TestReaderFastPath(unittest.TestCase):
    """Phase 6a: an unmodified page list opens the source, not an export.

    The export costs 3.6 s and peaks at 1.7 GB on a 1590 page book to reproduce
    a file that is already on disk -- see PORTING-NOTES.md section 6. These
    assert the two paths are interchangeable, and that the fast one is given up
    the moment anything is edited.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.reader = ReaderView()
        self.addCleanup(self.docs.cleanup)
        self.addCleanup(self.reader.clear)

    def test_unmodified_list_offers_the_source(self):
        pages = self.docs.add_file(TEST_PDF)
        source = self.docs.source_if_unmodified(pages)
        self.assertIsNotNone(source)
        copyname, _password = source
        # The working copy, never the original: PDFDoc leaves the copy alone,
        # which is what makes saving over the opened file safe.
        self.assertEqual(copyname, self.docs.docs[0].copyname)
        self.assertNotEqual(copyname, self.docs.docs[0].filename)

    def test_one_rotation_gives_up_the_fast_path(self):
        pages = self.docs.add_file(TEST_PDF)
        self.assertIsNotNone(self.docs.source_if_unmodified(pages))
        pages[0].rotate(90)
        self.assertIsNone(self.docs.source_if_unmodified(pages))

    def test_reordering_gives_up_the_fast_path(self):
        pages = self.docs.add_file(TEST_PDF)
        self.assertIsNone(self.docs.source_if_unmodified(list(reversed(pages))))

    def test_a_missing_page_gives_up_the_fast_path(self):
        pages = self.docs.add_file(TEST_PDF)
        self.assertIsNone(self.docs.source_if_unmodified(pages[:1]))

    def test_two_files_give_up_the_fast_path(self):
        pages = self.docs.add_file(TEST_PDF)
        pages += self.docs.add_file(TEXT_PDF)
        self.assertIsNone(self.docs.source_if_unmodified(pages))

    def test_an_empty_list_offers_nothing(self):
        self.assertIsNone(self.docs.source_if_unmodified([]))

    def test_both_paths_agree_on_the_document(self):
        """The point of the whole exercise: same document either way."""
        pages = self.docs.add_file(TEXT_PDF)
        files = self.docs.files_for_export()

        self.assertTrue(self.reader.load(pages, files))          # export path
        exported = (self.reader.page_count(),
                    self.reader._document.document.pagePointSize(0))

        fast = ReaderView()
        self.addCleanup(fast.clear)
        self.assertTrue(fast.load(pages, files,
                                  source=self.docs.source_if_unmodified(pages)))
        direct = (fast.page_count(),
                  fast._document.document.pagePointSize(0))

        self.assertEqual(exported[0], direct[0])
        self.assertEqual(round(exported[1].width(), 2), round(direct[1].width(), 2))
        self.assertEqual(round(exported[1].height(), 2), round(direct[1].height(), 2))

    def test_an_unopenable_source_falls_back_to_the_export(self):
        """A source that will not open costs a slow read mode, not a broken one."""
        pages = self.docs.add_file(TEST_PDF)
        ok = self.reader.load(pages, self.docs.files_for_export(),
                              source=(os.path.join(HERE, "no-such-file.pdf"), ""))
        self.assertTrue(ok)
        self.assertEqual(self.reader.page_count(), 2)
