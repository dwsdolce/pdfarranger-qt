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

"""Opening a file that is slow to read must not look like a hang.

Not because files are large. On a cloud-backed folder the bytes are not on
this machine, and the *first read* blocks while the provider fetches the whole
file -- measured at 11.4 seconds of an 11.5 second read for a 185 MB document,
with nothing appearing on disk until the final instant. So there is no
progress to poll and no chunked copy that could report any: the read has to
leave the GUI thread, and the only honest display is that something is
happening.

Nothing here detects a cloud file. `st_blocks` does not exist on Windows,
where the equivalent is a pair of `st_file_attributes` bits Python does not
name, and such a branch could never be exercised by a test. A timer needs none
of it and covers the slow network share and the spinning disk as well.
"""

import os
import shutil
import threading
import time
import unittest

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog
from support import TEST_PDF, settle, temp_path

from pdfarranger_qt.core import DocumentSet


class TestTheCopierSeam(unittest.TestCase):
    """Core takes the copier; it does not know what the window does with it."""

    def documents(self):
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        return docs

    def test_a_pdf_is_read_through_the_copier(self):
        used = []

        def copier(source, destination):
            used.append(source)
            return shutil.copy(source, destination)

        docs = self.documents()
        pages = docs.add_file(TEST_PDF, copier=copier)
        self.assertTrue(pages)
        self.assertEqual(used, [TEST_PDF])

    def test_an_image_is_read_through_it_too(self):
        """img2pdf reads the original, and that read blocks exactly as a copy
        would, so an image on a cloud folder must get the same treatment."""
        try:
            import img2pdf  # noqa: F401
        except ImportError:
            self.skipTest("img2pdf is not installed")
        from PySide6.QtGui import QImage

        source = temp_path("picture.png")
        image = QImage(40, 40, QImage.Format_RGB32)
        image.fill(0xFF336699)
        self.assertTrue(image.save(source))

        used = []

        def copier(src, dst):
            used.append(src)
            return shutil.copy(src, dst)

        docs = self.documents()
        self.assertTrue(docs.add_file(source, copier=copier))
        self.assertEqual(used, [source])

    def test_without_one_it_still_just_copies(self):
        """Everything with no window -- tests, anything headless -- must not
        acquire a dependency on a worker thread."""
        docs = self.documents()
        self.assertTrue(docs.add_file(TEST_PDF))


class TestTheWindowCopiesOffTheGuiThread(unittest.TestCase):
    """The whole point: the blocking read happens somewhere else."""

    def window(self):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        win.resize(600, 400)
        win.show()
        settle(timeout_ms=200)
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def dialogs_showing(self):
        return [w for w in QApplication.topLevelWidgets()
                if isinstance(w, QProgressDialog) and w.isVisible()]

    def test_the_copy_runs_on_another_thread(self):
        win = self.window()
        destination = temp_path("copied.pdf")
        where = {}
        original = shutil.copy

        def spy(source, target):
            where["thread"] = threading.get_ident()
            return original(source, target)

        shutil.copy = spy
        try:
            win._copy_source(TEST_PDF, destination)
        finally:
            shutil.copy = original
        self.assertIn("thread", where)
        self.assertNotEqual(where["thread"], threading.get_ident(),
                            "the read must not block the GUI thread")

    def test_the_file_actually_arrives(self):
        win = self.window()
        destination = temp_path("arrived.pdf")
        win._copy_source(TEST_PDF, destination)
        with open(TEST_PDF, "rb") as a, open(destination, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_a_failure_is_raised_where_the_caller_can_see_it(self):
        """It happens on the worker, so it has to be carried back by hand.

        PDFDoc turns an OSError here into the message the user is shown, and
        swallowing it on the thread would open a document with no file.
        """
        win = self.window()
        with self.assertRaises(OSError):
            win._copy_source(os.path.join(os.path.dirname(TEST_PDF),
                                          "no-such-file.pdf"),
                             temp_path("never.pdf"))

    def test_a_slow_open_says_something(self):
        """The dialog appears while the copy is still going.

        Observable because the wait is a nested event loop, so a timer set
        here still fires during it.
        """
        win = self.window()
        win.SLOW_OPEN_MS = 60
        seen = []
        QTimer.singleShot(300, lambda: seen.append(len(self.dialogs_showing())))
        original = shutil.copy

        def slow(source, target):
            time.sleep(0.6)
            return original(source, target)

        shutil.copy = slow
        try:
            win._copy_source(TEST_PDF, temp_path("slow.pdf"))
        finally:
            shutil.copy = original
        self.assertTrue(seen, "the timer should have fired during the copy")
        self.assertGreaterEqual(seen[0], 1, "a slow open should say so")
        self.assertEqual(self.dialogs_showing(), [],
                         "and should take it away afterwards")

    def test_a_fast_open_says_nothing(self):
        """An ordinary local file must not flash a dialog on every open."""
        win = self.window()
        win.SLOW_OPEN_MS = 2000
        seen = []
        QTimer.singleShot(0, lambda: seen.append(len(self.dialogs_showing())))
        win._copy_source(TEST_PDF, temp_path("fast.pdf"))
        settle(timeout_ms=120)
        self.assertEqual(self.dialogs_showing(), [])
        self.assertTrue(all(count == 0 for count in seen), seen)


if __name__ == "__main__":
    unittest.main()
