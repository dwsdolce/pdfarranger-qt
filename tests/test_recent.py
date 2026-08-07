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

"""The recent-files list and the menu built from it."""

import os
import unittest

from support import MESSAGE_BOXES, TEST_PDF, TEXT_PDF, settle


class TestRecentFiles(unittest.TestCase):
    """Ordering, de-duplication and capping, without building a window."""

    def store(self, max_entries=10):
        from PySide6.QtCore import QSettings
        from pdfarranger_qt.recent import RecentFiles

        settings = QSettings("pdfarranger-test", f"recent-{id(self)}")
        settings.clear()
        self.addCleanup(settings.clear)
        return RecentFiles(settings, max_entries=max_entries)

    def test_starts_empty(self):
        self.assertEqual(self.store().paths(), [])

    def test_most_recent_first(self):
        recent = self.store()
        recent.add(r"C:\a.pdf")
        recent.add(r"C:\b.pdf")
        self.assertEqual([os.path.basename(p) for p in recent.paths()],
                         ["b.pdf", "a.pdf"])

    def test_reopening_moves_to_the_top_without_duplicating(self):
        recent = self.store()
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            recent.add(os.path.join("C:\\", name))
        recent.add(r"C:\a.pdf")
        self.assertEqual([os.path.basename(p) for p in recent.paths()],
                         ["a.pdf", "c.pdf", "b.pdf"])

    def test_capped(self):
        recent = self.store(max_entries=3)
        for i in range(6):
            recent.add(os.path.join("C:\\", f"f{i}.pdf"))
        paths = recent.paths()
        self.assertEqual(len(paths), 3)
        self.assertEqual(os.path.basename(paths[0]), "f5.pdf")

    def test_paths_are_absolute(self):
        recent = self.store()
        recent.add("relative.pdf")
        self.assertTrue(os.path.isabs(recent.paths()[0]))

    def test_same_file_by_a_different_spelling_is_not_duplicated(self):
        """Windows treats C:\\A.PDF and c:\\a.pdf as one file."""
        recent = self.store()
        recent.add(r"C:\Docs\A.pdf")
        recent.add(r"c:\docs\a.pdf")
        expected = 1 if os.path.normcase("A") == os.path.normcase("a") else 2
        self.assertEqual(len(recent.paths()), expected)

    def test_remove_and_clear(self):
        recent = self.store()
        recent.add(r"C:\a.pdf")
        recent.add(r"C:\b.pdf")
        recent.remove(r"C:\a.pdf")
        self.assertEqual(len(recent.paths()), 1)
        recent.clear()
        self.assertEqual(recent.paths(), [])

    def test_a_single_entry_survives_the_round_trip(self):
        """QSettings collapses one-element lists to a bare string."""
        recent = self.store()
        recent.add(TEST_PDF)
        self.assertEqual(recent.paths(), [os.path.normpath(TEST_PDF)])

    def test_prune_missing(self):
        recent = self.store()
        recent.add(TEST_PDF)
        recent.add(r"C:\definitely\not\here.pdf")
        gone = recent.prune_missing()
        self.assertEqual(len(gone), 1)
        self.assertEqual(recent.paths(), [os.path.normpath(TEST_PDF)])

    def test_empty_path_is_ignored(self):
        recent = self.store()
        recent.add("")
        self.assertEqual(recent.paths(), [])

class TestRecentFilesMenu(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)
        self.win.recent.clear()
        self.addCleanup(self.win.recent.clear)

    def test_menu_says_so_when_empty(self):
        self.win._rebuild_recent_menu()
        actions = [a for a in self.win.recent_menu.actions() if not a.isSeparator()]
        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].isEnabled())

    def test_opening_a_file_records_it(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.assertEqual(self.win.recent.paths(), [os.path.normpath(TEST_PDF)])

    def test_opening_several_records_all_of_them(self):
        self.win.open_paths([TEST_PDF, TEXT_PDF])
        settle(timeout_ms=300)
        self.assertEqual(len(self.win.recent.paths()), 2)

    def test_menu_lists_entries_numbered(self):
        self.win.recent.add(r"C:\one.pdf")
        self.win.recent.add(r"C:\two.pdf")
        self.win._rebuild_recent_menu()
        labels = [a.text() for a in self.win.recent_menu.actions()
                  if not a.isSeparator()]
        self.assertTrue(labels[0].startswith("&1"))
        self.assertIn("two.pdf", labels[0])
        self.assertIn("Clear", labels[-1])

    def test_full_path_is_the_tooltip(self):
        self.win.recent.add(TEST_PDF)
        self.win._rebuild_recent_menu()
        action = self.win.recent_menu.actions()[0]
        self.assertEqual(action.toolTip(), os.path.normpath(TEST_PDF))

    def test_clear_menu_empties_it(self):
        self.win.recent.add(TEST_PDF)
        self.win.clear_recent()
        self.assertEqual(self.win.recent.paths(), [])

    def test_clearing_through_the_menu_item_empties_it(self):
        """Drive the action, not the method behind it.

        The test above calls clear_recent() directly, so it would still pass if
        the menu entry were wired to nothing at all. This one triggers the
        QAction the user actually clicks, and then rebuilds the menu the way
        aboutToShow does, to check the entries are really gone.
        """
        self.win.recent.add(TEST_PDF)
        self.win.recent.add(TEXT_PDF)
        self.win.recent_menu.aboutToShow.emit()

        clear = [a for a in self.win.recent_menu.actions()
                 if not a.isSeparator() and a.text() == "Clear Menu"]
        self.assertEqual(len(clear), 1, "no Clear Menu entry")
        clear[0].trigger()
        self.assertEqual(self.win.recent.paths(), [])

        self.win.recent_menu.aboutToShow.emit()
        labels = [a.text() for a in self.win.recent_menu.actions()
                  if not a.isSeparator()]
        self.assertEqual(labels, ["No recent files"])

    def test_opening_a_missing_file_warns_and_drops_it(self):
        missing = r"C:\definitely\not\here.pdf"
        self.win.recent.add(missing)
        MESSAGE_BOXES.clear()
        self.win.open_recent(missing)
        self.assertEqual(MESSAGE_BOXES[-1][0], "warning")
        self.assertEqual(self.win.recent.paths(), [])

    def test_open_recent_loads_the_document(self):
        self.win.modified = False
        self.win.open_recent(TEST_PDF)
        settle(timeout_ms=300)
        self.assertEqual(self.win.model.rowCount(), 2)
