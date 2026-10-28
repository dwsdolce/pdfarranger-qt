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

"""Where the file dialogs start.

There used to be one folder, set only when a document loaded and never written
to settings -- so a fresh launch always offered home, and a save never taught it
anything. Two now: the place documents come from and the place they go to, kept
in the settings so a second window starts where the first left off.

The dialogs themselves are never shown here. What is checked is the directory
they would be *given*, which is the half that was wrong.
"""

import os
import unittest

from support import TEST_PDF, settle, temp_path


class FolderWindow(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        for key in (MainWindow.SOURCE_FOLDER, MainWindow.OUTPUT_FOLDER):
            self.win.settings.remove(key)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def home(self):
        return os.path.expanduser("~")


class TestTheDefaults(FolderWindow):
    def test_both_start_at_home(self):
        self.assertEqual(self.win.source_dir, self.home())
        self.assertEqual(self.win.output_dir, self.home())

    def test_a_folder_that_has_gone_away_falls_back_to_home(self):
        """A disk that is no longer mounted would open the dialog nowhere."""
        self.win.settings.setValue(self.win.SOURCE_FOLDER,
                                   "/nowhere/in/particular/at/all")
        self.assertEqual(self.win.source_dir, self.home())

    def test_a_folder_that_exists_is_used(self):
        here = os.path.dirname(os.path.abspath(TEST_PDF))
        self.win.settings.setValue(self.win.SOURCE_FOLDER, here)
        self.assertEqual(self.win.source_dir, here)


class TestOpeningRemembers(FolderWindow):
    def test_opening_a_document_sets_the_source_folder(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.assertEqual(self.win.source_dir,
                         os.path.dirname(os.path.abspath(TEST_PDF)))

    def test_opening_does_not_touch_the_output_folder(self):
        """The two are separate so that neither retargets the other."""
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.assertEqual(self.win.output_dir, self.home())

    def test_a_file_that_fails_to_load_is_not_remembered(self):
        missing = os.path.join(self.home(), "no-such-document-here.pdf")
        self.win.open_paths([missing])
        settle(timeout_ms=200)
        self.assertEqual(self.win.source_dir, self.home(),
                         "a folder you could not open anything from is not "
                         "where you want the next dialog")


class TestSavingRemembers(FolderWindow):
    def setUp(self):
        super().setUp()
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win.settings.remove(self.win.SOURCE_FOLDER)
        self.win.settings.remove(self.win.OUTPUT_FOLDER)

    def test_saving_sets_the_output_folder(self):
        out = temp_path("saved-here.pdf")
        self.assertTrue(self.win._write([out], self.win.model.pages))
        self.assertEqual(self.win.output_dir, os.path.dirname(out))

    def test_saving_does_not_touch_the_source_folder(self):
        out = temp_path("saved-here.pdf")
        self.win._write([out], self.win.model.pages)
        self.assertEqual(self.win.source_dir, self.home())

    def test_the_two_do_not_fight(self):
        """The whole reason there are two.

        Open from one place and save to another, and both are still right --
        with a single folder each use would retarget the other.
        """
        source = os.path.dirname(os.path.abspath(TEST_PDF))
        out = temp_path("elsewhere.pdf")
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win._write([out], self.win.model.pages)
        self.assertEqual(self.win.source_dir, source)
        self.assertEqual(self.win.output_dir, os.path.dirname(out))
        self.assertNotEqual(self.win.source_dir, self.win.output_dir,
                            "the fixture and the temp dir should differ, "
                            "or this test proves nothing")

    def test_a_failed_write_is_not_remembered(self):
        """A folder that exists, holding a name that cannot be written.

        Not a path in a directory that is missing: that would be caught by the
        check for a folder that has gone away, and this is meant to exercise
        the write failing rather than the folder being absent.
        """
        out = temp_path("in-the-way.pdf")
        os.mkdir(out)                      # the target name is a directory
        self.assertTrue(os.path.isdir(os.path.dirname(out)),
                        "the folder must exist, or this proves nothing")
        self.assertFalse(self.win._write([out], self.win.model.pages))
        self.assertEqual(self.win.output_dir, self.home(),
                         "nothing was written, so nothing should be remembered")


class TestSharedBetweenWindows(FolderWindow):
    def test_a_new_window_starts_where_the_last_one_left_off(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        second = MainWindow()
        self.addCleanup(second.close)
        self.assertEqual(second.source_dir, self.win.source_dir)


class TestWhatEachDialogWouldBeGiven(FolderWindow):
    """The mapping from a command to the folder its dialog opens at."""

    def setUp(self):
        super().setUp()
        self.source = os.path.dirname(os.path.abspath(TEST_PDF))
        self.output = os.path.dirname(temp_path("x.pdf"))
        self.win.settings.setValue(self.win.SOURCE_FOLDER, self.source)
        self.win.settings.setValue(self.win.OUTPUT_FOLDER, self.output)

    def test_save_as_offers_the_output_folder_for_a_new_document(self):
        self.win.current_path = None
        start = self.win.current_path or os.path.join(self.win.output_dir,
                                                      "output.pdf")
        self.assertTrue(start.startswith(self.output))

    def test_save_as_offers_the_document_itself_when_it_has_one(self):
        """macOS's rule, and the right one: Save As on a saved document starts
        at that document, not at wherever you last wrote something else."""
        self.win.current_path = TEST_PDF
        start = self.win.current_path or os.path.join(self.win.output_dir,
                                                      "output.pdf")
        self.assertEqual(start, TEST_PDF)

    def test_the_two_folders_are_different_settings(self):
        self.assertNotEqual(self.win.SOURCE_FOLDER, self.win.OUTPUT_FOLDER)
        self.assertEqual(self.win.source_dir, self.source)
        self.assertEqual(self.win.output_dir, self.output)
