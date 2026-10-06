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

"""Find that goes somewhere.

The bug these exist for: searching an 84-page manual reported "22 pages match"
and then went nowhere, because `find_step` moved a selection in the *grid* --
which is not on screen while reading -- and `ReaderView.show_search_result`,
the method that scrolls the reader to a hit, had had no caller since the day it
was written. The canvas layer was tested, so the suite was green; the gap was
one layer up.

``exporter/outlines.pdf`` has four pages, each reading "Page N" followed by a
list of all four. So "Page" is twenty hits, five to a page, and "Page 4" is
five on pages [0, 1, 2, 3, 3] -- once in each page's list and again as the last
page's own heading. A hit list that walks the document and then stays put,
which is a better test than one hit per page would have been.
"""

import os
import unittest

from support import HERE, settle

from pdfarranger_qt.find import Query

MANY_PAGES = os.path.join(HERE, "exporter", "outlines.pdf")


class FindWindow(unittest.TestCase):
    """A window with the fixture open. Subclasses pick the mode."""

    read_mode = True

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        for key in ("find/case-sensitive", "find/whole-word", "find/regex"):
            self.win.settings.setValue(key, False)
        self.win.settings.setValue("find/wrap", True)
        self.win.set_read_mode(self.read_mode)
        settle(timeout_ms=300)
        # The reading position is remembered per document, so without this the
        # page one test left the reader on decides where the next one's "find
        # from here" starts.
        self.win.reader.go_to_page(0)
        settle(timeout_ms=200)
        self.win.modified = False

    def tearDown(self):
        if self.win._find_dialog is not None:
            self.win._find_dialog.close()
        self.win.modified = False
        self.win.close()

    def search(self, phrase="Page 4", **options):
        self.win._run_search(Query(phrase, **options))
        return self.win.search.count()


class TestReadingModeNavigates(FindWindow):
    """The reported bug: 22 pages matched and nothing moved."""

    read_mode = True

    def test_a_search_finds_every_hit_not_just_the_pages(self):
        """The old message said "4 pages match" and stopped there."""
        self.assertEqual(self.search("Page 4"), 5)
        self.assertEqual(self.win.search.matches, [0, 1, 2, 3])
        self.assertEqual([hit.page for hit in self.win.search.hits()],
                         [0, 1, 2, 3, 3])
        self.assertEqual(self.search("Page"), 20, "five per page")

    def test_find_next_moves_the_reader(self):
        self.search("Page 4")
        self.win.find_step(forward=True)
        settle(timeout_ms=200)
        self.assertEqual(self.win._find_cursor, 0)
        self.win.find_step(forward=True)
        settle(timeout_ms=300)
        self.assertEqual(self.win._find_cursor, 1)
        self.assertEqual(self.win.reader.current_page(), 1,
                         "the second hit is on page 2, and the reader should be there")

    def test_find_next_walks_the_whole_document(self):
        self.search("Page 4")
        seen = []
        for _ in range(5):
            self.win.find_step(forward=True)
            settle(timeout_ms=200)
            seen.append(self.win.reader.current_page())
        self.assertEqual(seen, [0, 1, 2, 3, 3])

    def test_the_reader_is_told_which_hit_is_current(self):
        """Painted differently from the rest, which is what picks it out."""
        self.search("Page 4")
        self.win.find_step(forward=True)
        self.win.find_step(forward=True)
        settle(timeout_ms=200)
        self.assertGreaterEqual(self.win.reader.canvas._search_result, 0)

    def test_the_two_engines_agree_about_where_a_hit_is(self):
        """The window searches the edited document; the reader searches its own.

        The cursor is carried across by position rather than by index, so the
        lookup has to find something -- if it does not, the reader highlights
        nothing and the bug is back.
        """
        self.search("Page 4")
        for index in range(self.win.search.count()):
            hit = self.win.search.hit(index)
            self.assertGreaterEqual(
                self.win.reader.index_of_hit(hit.page, hit.start), 0,
                f"hit {index} on page {hit.page} is unknown to the reader")

    def test_find_previous_goes_back(self):
        self.search("Page 4")
        self.win._find_go(2)
        settle(timeout_ms=300)
        self.win.find_step(forward=False)
        settle(timeout_ms=200)
        self.assertEqual(self.win._find_cursor, 1)
        self.assertEqual(self.win.reader.current_page(), 1)

    def test_a_search_starts_from_the_page_being_read(self):
        """Not from the top: find means find from here."""
        self.win.reader.go_to_page(2)
        settle(timeout_ms=300)
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.assertEqual(self.win._find_cursor, 2,
                         "the first hit on page 3 or later")

    def test_selecting_a_row_leaves_arranging_mode_on_the_right_page(self):
        self.search("Page 4")
        self.win._find_go(2)
        settle(timeout_ms=200)
        self.assertEqual(self.win.view.selected_rows(), [2])


class TestArrangingModeNavigates(FindWindow):
    read_mode = False

    def test_find_next_selects_the_page(self):
        self.search("Page 4")
        self.win.find_step(forward=True)
        self.win.find_step(forward=True)
        self.assertEqual(self.win.view.selected_rows(), [1])

    def test_stepping_through_hits_on_one_page_stays_there(self):
        """Five hits a page, so four of five steps do not change the selection."""
        self.search("Page")
        pages = []
        for _ in range(6):
            self.win.find_step(forward=True)
            pages.append(self.win.view.selected_rows())
        self.assertEqual(pages, [[0], [0], [0], [0], [0], [1]])

    def test_find_all_selects_every_matching_page(self):
        self.win._run_search(Query("Page 4"))
        self.win.find_all()
        self.assertEqual(self.win.view.selected_rows(), [0, 1, 2, 3])

    def test_the_grid_resolves_rectangles_only_for_rows_it_is_asked_about(self):
        """Lazy by design: 1.5 ms a hit is 700 ms for a common word."""
        self.search("Page")
        self.assertEqual(self.win.model._matches, {},
                         "a search alone should resolve nothing")
        rects = self.win.model.data(self.win.model.index(0, 0),
                                    self.win.model.MatchRole)
        self.assertTrue(rects)
        self.assertEqual(list(self.win.model._matches), [0],
                         "and only the row that was asked for")


class TestTheCursor(FindWindow):
    read_mode = False

    def test_wrapping_carries_on_from_the_other_end(self):
        self.search("Page 4")
        self.win._find_go(4)              # the last of five
        self.win.find_step(forward=True)
        self.assertEqual(self.win._find_cursor, 0)

    def test_wrapping_backwards_too(self):
        self.search("Page 4")
        self.win._find_go(0)
        self.win.find_step(forward=False)
        self.assertEqual(self.win._find_cursor, 4)

    def test_without_wrapping_it_stops(self):
        self.win.settings.setValue("find/wrap", False)
        self.search("Page 4")
        self.win._find_go(4)
        self.win.find_step(forward=True)
        self.assertEqual(self.win._find_cursor, 4, "stays on the last match")

    def test_an_edit_drops_the_cursor_but_keeps_the_query(self):
        self.search("Page 4")
        self.win._find_go(2)
        self.win.view.set_selected_rows([0])
        self.win.duplicate_selected()
        settle(timeout_ms=200)
        self.assertEqual(self.win._find_cursor, -1)
        self.assertEqual(self.win.search.phrase, "Page 4",
                         "the search survives; only the positions are gone")

    def test_find_next_after_an_edit_rebuilds_and_carries_on(self):
        """The index is gone, so Find Next has to rebuild it before it can step.

        Where it lands is "from here", and duplicating leaves the selection on
        the new page, so it resumes from there rather than from the top.
        """
        self.search("Page 4")
        self.win.view.set_selected_rows([0])
        self.win.duplicate_selected()
        settle(timeout_ms=300)
        self.assertEqual(self.win.search.count(), 0, "the index was dropped")
        self.win.find_step(forward=True)
        self.assertEqual(self.win.search.count(), 6,
                         "page 1 was duplicated, and it held one of the five")
        self.assertEqual(self.win._find_cursor,
                         self.win.search.first_at_or_after(
                             self.win.view.selected_rows()[0]))

    def test_a_fruitless_search_leaves_the_cursor_nowhere(self):
        self.search("zzzznotpresent")
        self.win.find_step(forward=True)
        self.assertEqual(self.win._find_cursor, -1)


class TestOptionsReachTheSearch(FindWindow):
    read_mode = False

    def test_case_sensitivity(self):
        self.assertEqual(self.search("page 4"), 5)
        self.assertEqual(self.search("page 4", case_sensitive=True), 0)
        self.assertEqual(self.search("Page 4", case_sensitive=True), 5)

    def test_whole_words(self):
        self.assertEqual(self.search("Pag"), 20)
        self.assertEqual(self.search("Pag", whole_word=True), 0)
        self.assertEqual(self.search("Page", whole_word=True), 20)

    def test_a_regular_expression(self):
        self.assertEqual(self.search("Page [13]", regex=True), 10,
                         "Page 1 and Page 3 in every list, plus two headings")

    def test_a_broken_pattern_is_reported_not_raised(self):
        self.search("Page (", regex=True)
        self.assertEqual(self.win.search.count(), 0)
        self.assertIsNotNone(self.win.search.error)

    def test_the_options_are_remembered(self):
        self.win._dialog_asked(Query("Page", case_sensitive=True, whole_word=True))
        self.assertTrue(self.win.settings.value("find/case-sensitive", type=bool))
        self.assertTrue(self.win.settings.value("find/whole-word", type=bool))
        self.assertFalse(self.win.settings.value("find/regex", type=bool))


class TestTheDialog(FindWindow):
    read_mode = True

    def dialog(self):
        self.win.find_text()
        return self.win._find_dialog

    def test_it_is_modeless(self):
        """So that Next can move the document behind it."""
        self.assertFalse(self.dialog().isModal())

    def test_it_is_reused_rather_than_stacked(self):
        first = self.dialog()
        self.assertIs(self.dialog(), first)

    def test_typing_runs_a_search(self):
        dialog = self.dialog()
        dialog.field.setText("Page 4")
        dialog._announce()          # the typing pause, without waiting for it
        settle(timeout_ms=200)
        self.assertEqual(self.win.search.count(), 5)

    def test_every_hit_is_listed_with_its_page_and_context(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.assertEqual(dialog.results.topLevelItemCount(), 5)
        first = dialog.results.topLevelItem(0)
        self.assertEqual(first.text(0), "1", "pages are numbered from one")
        self.assertIn("Page 4", first.text(1))

    def test_the_counter_says_where_you_are(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.assertIn("1", dialog.status.text())
        self.win.find_step(forward=True)
        settle(timeout_ms=200)
        self.assertIn("2", dialog.status.text())
        self.assertIn("5", dialog.status.text(), "of five")

    def test_the_counter_says_when_there_is_nothing(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("zzzznotpresent"))
        settle(timeout_ms=200)
        self.assertEqual(dialog.status.text(), "No matches")

    def test_a_broken_pattern_is_said_quietly(self):
        dialog = self.dialog()
        dialog.regex.setChecked(True)
        self.win._dialog_asked(Query("Page (", regex=True))
        settle(timeout_ms=200)
        self.assertIn("valid", dialog.status.text())
        self.assertEqual(dialog.results.topLevelItemCount(), 0)

    def test_choosing_a_row_goes_to_that_hit(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        dialog.results.setCurrentItem(dialog.results.topLevelItem(2))
        settle(timeout_ms=300)
        self.assertEqual(self.win._find_cursor, 2)
        self.assertEqual(self.win.reader.current_page(), 2)

    def test_the_list_follows_the_cursor(self):
        """Stepping with F3 must move the highlight in the list too."""
        dialog = self.dialog()
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.win.find_step(forward=True)
        settle(timeout_ms=200)
        self.assertEqual(dialog.results.indexOfTopLevelItem(
            dialog.results.currentItem()), self.win._find_cursor)

    def test_a_regex_takes_over_the_whole_word_option(self):
        dialog = self.dialog()
        self.assertTrue(dialog.whole_word.isEnabled())
        dialog.regex.setChecked(True)
        self.assertFalse(dialog.whole_word.isEnabled(),
                         "a pattern states its own boundaries")
        dialog.regex.setChecked(False)
        self.assertTrue(dialog.whole_word.isEnabled())

    def test_it_opens_with_the_previous_search_in_it(self):
        self.win._run_search(Query("Page 4"))
        self.assertEqual(self.dialog().field.text(), "Page 4")

    def test_clearing_the_field_clears_the_highlights(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.assertTrue(self.win.search.count())
        self.win._dialog_asked(Query(""))
        settle(timeout_ms=200)
        self.assertEqual(self.win.search.count(), 0)
        self.assertEqual(dialog.results.topLevelItemCount(), 0)

    def test_an_empty_list_disables_the_buttons(self):
        dialog = self.dialog()
        self.win._dialog_asked(Query("zzzznotpresent"))
        settle(timeout_ms=200)
        self.assertFalse(dialog.next_button.isEnabled())
        self.assertFalse(dialog.previous_button.isEnabled())
        self.win._dialog_asked(Query("Page 4"))
        settle(timeout_ms=200)
        self.assertTrue(dialog.next_button.isEnabled())
