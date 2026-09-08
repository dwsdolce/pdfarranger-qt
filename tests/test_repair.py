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

"""Finding and undoing damage in a PDF."""

import os
import shutil
import tempfile
import unittest

import pikepdf
from support import TEST_PDF, temp_path

from pdfarranger_qt import repair

#: A file with a proper cross-reference table, unlike TEST_PDF.
HEALTHY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "test_metadata1.pdf")


def damaged(source=HEALTHY):
    """A copy of ``source`` whose startxref points nowhere.

    The classic recoverable damage, and the thing qpdf reconstructs: the
    objects are all still there, the table saying where they are is wrong.
    """
    path = temp_path("damaged.pdf")
    shutil.copyfile(source, path)
    with open(path, "r+b") as handle:
        data = handle.read()
        at = data.rfind(b"startxref")
        handle.seek(at)
        handle.write(b"startxref\n999999\n%%EOF\n")
        handle.truncate()
    return path


class TestDiagnose(unittest.TestCase):
    def test_a_healthy_file_needs_nothing(self):
        found = repair.diagnose(HEALTHY)
        self.assertTrue(found.readable)
        self.assertFalse(found.needed_recovery)
        self.assertEqual(found.pages, 1)
        self.assertEqual(found.detail, "")

    def test_damage_is_found(self):
        found = repair.diagnose(damaged())
        self.assertTrue(found.readable)
        self.assertTrue(found.needed_recovery)
        self.assertEqual(found.pages, 1)
        self.assertTrue(found.detail, "qpdf's account of the damage is missing")

    def test_a_silent_recovery_is_what_makes_this_necessary(self):
        """The measurement the module is built on.

        pikepdf's default open repairs the file and says nothing, so a plain
        read cannot be used to detect damage at all.
        """
        path = damaged()
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 1)
        with self.assertRaises(pikepdf.PdfError):
            pikepdf.open(path, attempt_recovery=False)

    def test_the_project_fixture_is_damaged_too(self):
        """It has a stub xref table; worth knowing, and it exercises the path."""
        self.assertTrue(repair.diagnose(TEST_PDF).needed_recovery)

    def test_garbage_is_not_readable(self):
        path = temp_path("garbage.pdf")
        with open(path, "wb") as handle:
            handle.write(b"this is not a PDF at all\n" * 10)
        found = repair.diagnose(path)
        self.assertFalse(found.readable)
        self.assertTrue(found.detail)

    def test_a_missing_file_is_not_readable(self):
        found = repair.diagnose(os.path.join(tempfile.mkdtemp(), "absent.pdf"))
        self.assertFalse(found.readable)

    def test_every_diagnosis_can_be_described(self):
        for found in (repair.diagnose(HEALTHY), repair.diagnose(damaged()),
                      repair.diagnose(__file__)):
            with self.subTest(found=found):
                self.assertTrue(found.summary())


class TestRepair(unittest.TestCase):
    def test_the_repaired_copy_opens_strictly(self):
        source = damaged()
        out = temp_path("fixed.pdf")
        found = repair.repair(source, out)
        self.assertTrue(found.needed_recovery)
        # The point of the whole exercise: no recovery needed the second time.
        with pikepdf.open(out, attempt_recovery=False) as pdf:
            self.assertEqual(len(pdf.pages), 1)
        self.assertFalse(repair.diagnose(out).needed_recovery)

    def test_a_healthy_file_is_copied_unharmed(self):
        out = temp_path("copy.pdf")
        found = repair.repair(HEALTHY, out)
        self.assertFalse(found.needed_recovery)
        with pikepdf.open(out, attempt_recovery=False) as pdf:
            self.assertEqual(len(pdf.pages), 1)

    def test_it_can_linearize_on_the_way_out(self):
        out = temp_path("web.pdf")
        repair.repair(damaged(), out, linearize=True)
        with pikepdf.open(out) as pdf:
            self.assertTrue(pdf.is_linearized)

    def test_unreadable_input_raises_rather_than_writing_a_stub(self):
        path = temp_path("garbage.pdf")
        with open(path, "wb") as handle:
            handle.write(b"not a PDF")
        out = temp_path("never.pdf")
        with self.assertRaises(pikepdf.PdfError):
            repair.repair(path, out)
        self.assertFalse(os.path.exists(out))


class TestIsLinearized(unittest.TestCase):
    def test_a_plain_file_is_not(self):
        self.assertIs(repair.is_linearized(HEALTHY), False)

    def test_a_linearized_file_is(self):
        out = temp_path("web.pdf")
        repair.repair(HEALTHY, out, linearize=True)
        self.assertIs(repair.is_linearized(out), True)

    def test_an_unreadable_file_gives_no_answer(self):
        self.assertIsNone(repair.is_linearized(__file__))
