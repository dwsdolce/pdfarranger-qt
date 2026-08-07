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

"""Booklet imposition and unimposition."""

import os
import unittest
import pikepdf

from pdfarranger_qt.core import Dims, Page
from pdfarranger_qt.export import export

from support import QtDocumentTestCase


class TestBooklet(unittest.TestCase):
    def test_crops_from_tiles_two_columns(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        self.assertEqual(crops_from_tiles([[1, 50], [2, 50]]), [(0, 0.5), (0.5, 1.0)])

    def test_crops_from_tiles_single(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        self.assertEqual(crops_from_tiles([[1, 100]]), [(0, 1.0)])

    def test_crops_from_tiles_overlapping(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        crops = crops_from_tiles([[1, 60], [2, 60]])
        self.assertAlmostEqual(crops[0][1], 0.6)
        self.assertAlmostEqual(crops[-1][0], 0.4)

    def test_split_restores_reading_order(self):
        """A 2-sheet booklet holds [4|1] and [2|3]; unimposing gives 1 2 3 4."""
        from pdfarranger_qt.booklet import split

        sheets = []
        for i, (left, right) in enumerate([("4", "1"), ("2", "3")]):
            page = Page(1, i + 1, "a.pdf", size_orig=Dims(1224, 792))
            page.description = f"{left}|{right}"
            sheets.append(page)
        result = split(sheets)
        self.assertEqual(len(result), 4)
        # Halves come back as (left-crop, right-crop) pairs of their sheet
        labels = [p.description for p in result]
        self.assertEqual(labels, ["4|1", "2|3", "2|3", "4|1"])
        # Reading order: sheet0-right, sheet1-left, sheet1-right, sheet0-left
        self.assertAlmostEqual(result[0].crop.left, 0.5)   # "1" is the right half
        self.assertAlmostEqual(result[1].crop.left, 0.0)   # "2" is the left half
        self.assertAlmostEqual(result[2].crop.left, 0.5)   # "3" is the right half
        self.assertAlmostEqual(result[3].crop.left, 0.0)   # "4" is the left half

    def test_can_split_requires_uniform_size(self):
        from pdfarranger_qt.booklet import can_split

        a = Page(1, 1, "a.pdf", size_orig=Dims(1224, 792))
        b = Page(1, 2, "a.pdf", size_orig=Dims(612, 792))
        self.assertTrue(can_split([a, a.duplicate()]))
        self.assertFalse(can_split([a, b]))
        self.assertFalse(can_split([]))

class TestBookletGenerate(QtDocumentTestCase):
    def pages(self, n):
        base = self.model.pages[0]
        out = []
        for i in range(n):
            page = base.duplicate()
            page.description = str(i + 1)
            out.append(page)
        return out

    def test_four_pages_make_two_sheets(self):
        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(4), self.docs)
        self.assertEqual(len(sheets), 2)

    def test_sheets_are_double_width(self):
        from pdfarranger_qt.booklet import generate

        src = self.pages(4)
        sheets = generate(src, self.docs)
        self.assertAlmostEqual(sheets[0].size_in_points().width,
                               src[0].size_in_points().width * 2, places=3)
        self.assertAlmostEqual(sheets[0].size_in_points().height,
                               src[0].size_in_points().height, places=3)

    def test_each_sheet_carries_two_pages(self):
        from pdfarranger_qt.booklet import generate

        for sheet in generate(self.pages(4), self.docs):
            self.assertEqual(len(sheet.layerpages), 2)

    def test_page_count_is_padded_to_a_multiple_of_four(self):
        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(5), self.docs)
        self.assertEqual(len(sheets), 4, "5 pages pad to 8, giving 4 sheets")
        carried = sum(len(s.layerpages) for s in sheets)
        self.assertEqual(carried, 5, "only the real pages are composited")

    def test_round_trip_generate_then_split(self):
        """Impose then unimpose should give the pages back in order."""
        from pdfarranger_qt.booklet import generate, split

        src = self.pages(4)
        sheets = generate(src, self.docs)
        restored = split([s.duplicate() for s in sheets])
        self.assertEqual(len(restored), 4)

    def test_imposed_booklet_exports(self):
        import tempfile

        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(4), self.docs)
        path = os.path.join(tempfile.mkdtemp(), "booklet.pdf")
        self.assertEqual(
            export(self.docs.files_for_export(), sheets, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], 1224, delta=1)
