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

"""A signed document is read, and nothing else.

Nothing this application writes can carry a signature over: a document
assembled here is a new one, and a signature is a statement about the exact
bytes of the file it was computed from. So rather than hand back a copy whose
signature is broken -- which no reader can tell from tampering -- a signed
document opens as a reader and every command that would write is refused.

It is also never in company. The three routes that put a second file into a
session each refuse a signed one, so the question "is this session signed?"
is in practice about a single document.
"""

import os
import unittest

from support import FIXTURES, MESSAGE_BOXES, settle, temp_path
from test_forms import signed

PLAIN = os.path.join(FIXTURES, "exporter", "outlines.pdf")


def a_signed_file(name="signed.pdf", **kwargs):
    path = temp_path(name)
    with open(path, "wb") as handle:
        handle.write(signed(**kwargs))
    return path


class SignedWindowCase(unittest.TestCase):
    """A window with one signed document open in it."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.path = a_signed_file()
        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([self.path])
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()


class TestTheDocumentIsRecognised(SignedWindowCase):

    def test_the_session_is_read_only(self):
        self.assertTrue(self.win.read_only)

    def test_a_plain_document_is_not(self):
        self.win.open_paths([PLAIN])
        settle(timeout_ms=400)
        self.assertFalse(self.win.read_only)

    def test_it_opens_in_the_reader(self):
        """Opened for reading, which is the only thing left to do with it."""
        self.assertTrue(self.win.read_mode)


class TestNothingCanBeWritten(SignedWindowCase):

    def test_save_is_refused(self):
        self.assertFalse(self.win.act_save.isEnabled())

    def test_save_as_is_refused(self):
        """The escape hatch is closed too: a reader writes nothing at all."""
        self.assertFalse(self.win.act_save_as.isEnabled())

    def test_every_export_is_refused(self):
        for name in ("act_export_sel", "act_export_sel_multi",
                     "act_export_all_multi", "act_export_png",
                     "act_export_jpg", "act_export_raster_pdf",
                     "act_export_raster_pdf_jpg"):
            with self.subTest(action=name):
                self.assertFalse(getattr(self.win, name).isEnabled())

    def test_the_document_cannot_be_rearranged(self):
        """Arrange mode is the way to every page command, so it goes."""
        self.assertFalse(self.win.act_arrange_mode.isEnabled())

    def test_metadata_cannot_be_edited(self):
        self.assertFalse(self.win.act_properties.isEnabled())

    def test_nothing_can_be_imported_into_it(self):
        self.assertFalse(self.win.act_import.isEnabled())

    def test_the_status_bar_says_why(self):
        self.assertIn("read only", self.win.status_mode.text().lower())


class TestWhatIsStillAllowed(SignedWindowCase):
    """Read-only is not useless: a reader still reads."""

    def test_the_file_can_still_be_opened_and_closed(self):
        self.assertTrue(self.win.act_open.isEnabled())
        self.assertTrue(self.win.act_close.isEnabled())

    def test_it_can_still_be_printed(self):
        """A reader prints. Acrobat Reader prints a signed document too."""
        self.assertTrue(self.win.act_print.isEnabled())

    def test_text_can_still_be_searched(self):
        self.assertTrue(self.win.act_find.isEnabled())

    def test_a_new_window_is_still_offered(self):
        self.assertTrue(self.win.act_new_window.isEnabled())


class TestASignedDocumentIsNeverInCompany(unittest.TestCase):
    """The three routes that would put another file beside it."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.signed_path = a_signed_file("company.pdf")
        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def pages(self):
        return self.win.model.rowCount()

    def test_opening_it_alone_is_allowed(self):
        """The premise: refusing company is not refusing the document."""
        self.assertTrue(self.win.open_paths([self.signed_path]))
        settle(timeout_ms=400)
        self.assertGreater(self.pages(), 0)

    def test_a_merge_that_includes_it_is_refused(self):
        MESSAGE_BOXES.clear()
        opened = self.win.open_paths([PLAIN, self.signed_path])
        self.assertFalse(opened)
        self.assertTrue(MESSAGE_BOXES, "the user was told nothing")

    def test_a_refused_merge_leaves_what_was_open_alone(self):
        """Refused before the reset, so the previous document survives."""
        self.win.open_paths([PLAIN])
        settle(timeout_ms=400)
        before = self.pages()
        MESSAGE_BOXES.clear()
        self.win.open_paths([PLAIN, self.signed_path])
        self.assertEqual(self.pages(), before)
        self.assertFalse(self.win.read_only)

    def test_importing_it_is_refused(self):
        self.win.open_paths([PLAIN])
        settle(timeout_ms=400)
        before = self.pages()
        MESSAGE_BOXES.clear()
        self.win._import_files_at([self.signed_path], -1)
        self.assertEqual(self.pages(), before)
        self.assertTrue(MESSAGE_BOXES, "the user was told nothing")

    def test_dropping_it_is_refused(self):
        """A drop does not go through the menu, so the greyed-out action
        would not have stopped it."""
        self.win.open_paths([PLAIN])
        settle(timeout_ms=400)
        before = self.pages()
        MESSAGE_BOXES.clear()
        self.win._import_files_at([self.signed_path], 0)
        self.assertEqual(self.pages(), before)

    def test_nothing_can_be_added_to_a_signed_session(self):
        """The other direction: the signed one is already open."""
        self.win.open_paths([self.signed_path])
        settle(timeout_ms=400)
        before = self.pages()
        MESSAGE_BOXES.clear()
        self.win._import_files_at([PLAIN], -1)
        self.assertEqual(self.pages(), before)
        self.assertTrue(MESSAGE_BOXES, "the user was told nothing")

    def test_two_plain_documents_still_merge(self):
        """The rule must not have closed the ordinary case."""
        self.assertTrue(self.win.open_paths([PLAIN, PLAIN]))
        settle(timeout_ms=400)
        self.assertGreater(self.pages(), 0)


if __name__ == "__main__":
    unittest.main()
