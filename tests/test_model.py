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

"""The item model: undo, reordering, list ops and page geometry edits."""

import os
import pikepdf

from pdfarranger_qt.core import Dims, Sides
from pdfarranger_qt.export import export

from support import QtDocumentTestCase, TEST_PDF


class TestUndo(QtDocumentTestCase):
    def test_undo_redo_round_trip(self):
        original = [p.npage for p in self.model.pages]
        self.model.undo.commit("Delete")
        self.model.remove_rows([0])
        self.assertEqual(self.model.rowCount(), 1)

        self.model.undo.undo()
        self.assertEqual([p.npage for p in self.model.pages], original)
        self.model.undo.redo()
        self.assertEqual(self.model.rowCount(), 1)

    def test_labels_name_the_action(self):
        self.model.undo.commit("Rotate")
        self.model.rotate([0], 90)
        self.assertEqual(self.model.undo.undo_label(), "Rotate")
        self.model.undo.undo()
        self.assertEqual(self.model.undo.redo_label(), "Rotate")

    def test_undo_restores_rotation(self):
        self.model.undo.commit("Rotate")
        self.model.rotate([0], 90)
        self.model.undo.undo()
        self.assertEqual(self.model.pages[0].angle, 0)
        self.model.undo.redo()
        self.assertEqual(self.model.pages[0].angle, 90)

    def test_commit_truncates_the_redo_branch(self):
        self.model.undo.commit("A")
        self.model.remove_rows([0])
        self.model.undo.undo()
        self.assertTrue(self.model.undo.can_redo)
        self.model.undo.commit("B")
        self.model.remove_rows([0])
        self.assertFalse(self.model.undo.can_redo)

class TestReorder(QtDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.model.set_pages(self.docs.add_file(TEST_PDF) * 1)
        # Give ourselves four distinguishable pages.
        self.model.duplicate([0, 1])
        for i, page in enumerate(self.model.pages):
            page.description = str(i)

    def order(self):
        return [p.description for p in self.model.pages]

    def test_move_forward(self):
        self.model.move_rows([0], 3)
        self.assertEqual(self.order(), ["1", "2", "0", "3"])

    def test_move_backward(self):
        self.model.move_rows([3], 1)
        self.assertEqual(self.order(), ["0", "3", "1", "2"])

    def test_move_block_keeps_relative_order(self):
        self.model.move_rows([0, 2], 4)
        self.assertEqual(self.order(), ["1", "3", "0", "2"])

    def test_move_to_end(self):
        self.model.move_rows([0], 4)
        self.assertEqual(self.order(), ["1", "2", "3", "0"])

class TestListOperations(QtDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.model.duplicate([0, 1])
        for i, page in enumerate(self.model.pages):
            page.description = str(i)

    def order(self):
        return [p.description for p in self.model.pages]

    def test_reverse(self):
        self.model.reverse_rows([0, 1, 2, 3])
        self.assertEqual(self.order(), ["3", "2", "1", "0"])

    def test_reverse_a_subrange_leaves_the_rest(self):
        self.model.reverse_rows([1, 2])
        self.assertEqual(self.order(), ["0", "2", "1", "3"])

    def test_swap_odd_even(self):
        self.model.swap_odd_even([0, 1, 2, 3])
        self.assertEqual(self.order(), ["1", "0", "3", "2"])

    def test_swap_ignores_a_trailing_odd_page(self):
        self.model.swap_odd_even([0, 1, 2])
        self.assertEqual(self.order(), ["1", "0", "2", "3"])

    def test_interleave_before(self):
        extra = [self.model.pages[0].duplicate() for _ in range(2)]
        for i, page in enumerate(extra):
            page.description = f"x{i}"
        self.model.insert_interleaved(0, extra, after=False)
        self.assertEqual(self.order(), ["x0", "0", "x1", "1", "2", "3"])

    def test_interleave_after(self):
        extra = [self.model.pages[0].duplicate() for _ in range(2)]
        for i, page in enumerate(extra):
            page.description = f"x{i}"
        self.model.insert_interleaved(0, extra, after=True)
        self.assertEqual(self.order(), ["0", "x0", "1", "x1", "2", "3"])

    def test_rows_matching_same_file(self):
        self.assertEqual(self.model.rows_matching([0], "copyname"), [0, 1, 2, 3])

    def test_rows_matching_same_format(self):
        self.model.pages[2].scale = 2.0  # a different size in points
        matched = self.model.rows_matching([0], "size_in_points")
        self.assertIn(0, matched)
        self.assertNotIn(2, matched)

    def test_replace_rows(self):
        replacement = [self.model.pages[0].duplicate()]
        replacement[0].description = "new"
        self.model.replace_rows([1, 2], replacement)
        self.assertEqual(self.order(), ["0", "new", "3"])

class TestPageOperations(QtDocumentTestCase):
    def test_scale_relative(self):
        self.assertTrue(self.model.set_scale([0], 1.5))
        self.assertAlmostEqual(self.model.pages[0].scale, 1.5, places=6)

    def test_scale_to_fit_a_paper_size(self):
        target = Dims(595.27, 841.89)  # A4 in points
        self.assertTrue(self.model.set_scale([0], target))
        size = self.model.pages[0].size_in_points()
        self.assertLessEqual(size.width, target.width + 0.5)
        self.assertLessEqual(size.height, target.height + 0.5)

    def test_scale_clamps_to_the_pdf_limits(self):
        """PDF requires page sides between 72 and 14400 points."""
        self.model.set_scale([0], 0.0001)
        size = self.model.pages[0].size_in_points()
        self.assertGreaterEqual(min(size), 72 - 0.001)

    def test_scale_moves_layers_with_the_page(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import entry_from_page, layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([entry_from_page(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        before = dest.layerpages[0].scale
        self.model.set_scale([0], 2.0)
        self.assertAlmostEqual(dest.layerpages[0].scale, before * 2 / 1.0, places=6)

    def test_set_crop(self):
        self.assertTrue(self.model.set_margins([0], Sides(0.1, 0.1, 0, 0), hide=False))
        self.assertEqual(self.model.pages[0].crop, Sides(0.1, 0.1, 0, 0))
        self.assertEqual(self.model.pages[0].hide, Sides())

    def test_set_hide(self):
        self.assertTrue(self.model.set_margins([0], Sides(0, 0, 0.2, 0), hide=True))
        self.assertEqual(self.model.pages[0].hide, Sides(0, 0, 0.2, 0))
        self.assertEqual(self.model.pages[0].crop, Sides())

    def test_setting_the_same_margins_is_a_no_op(self):
        self.model.set_margins([0], Sides(0.1, 0, 0, 0), hide=False)
        self.assertFalse(self.model.set_margins([0], Sides(0.1, 0, 0, 0), hide=False))

    def test_crop_narrows_the_exported_mediabox(self):
        import tempfile

        before = float(self.model.pages[0].width_in_points())
        self.model.set_margins([0], Sides(0.25, 0.25, 0, 0), hide=False)
        path = os.path.join(tempfile.mkdtemp(), "cropped.pdf")
        export(self.docs.files_for_export(), self.model.pages[:1], {}, [path])
        with pikepdf.open(path) as pdf:
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], before * 0.5, delta=1.0)

    def test_split_into_two_columns(self):
        added = self.model.split_pages([0], columns=2, row_count=1)
        self.assertEqual(added, 1)
        self.assertEqual(self.model.rowCount(), 3)
        self.assertAlmostEqual(self.model.pages[0].crop.right, 0.5, places=6)
        self.assertAlmostEqual(self.model.pages[1].crop.left, 0.5, places=6)

    def test_split_into_a_grid(self):
        added = self.model.split_pages([0], columns=2, row_count=2)
        self.assertEqual(added, 3, "a 2x2 grid yields three extra pages")
        self.assertEqual(self.model.rowCount(), 5)

    def test_split_of_one_by_one_does_nothing(self):
        self.assertEqual(self.model.split_pages([0], 1, 1), 0)
        self.assertEqual(self.model.rowCount(), 2)

    def test_split_multiple_rows_keeps_order(self):
        for i, page in enumerate(self.model.pages):
            page.description = str(i)
        self.model.split_pages([0, 1], columns=2, row_count=1)
        self.assertEqual([p.description for p in self.model.pages],
                         ["0", "0", "1", "1"])

    def test_split_pages_export(self):
        import tempfile

        self.model.split_pages([0], columns=2, row_count=1)
        path = os.path.join(tempfile.mkdtemp(), "split.pdf")
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 3)
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], 306, delta=1)
