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

"""Compositing one page on top of another."""

import os
import pikepdf

from pdfarranger_qt.core import Dims, Page
from pdfarranger_qt.export import export

from support import QtDocumentTestCase


class TestLayers(QtDocumentTestCase):
    """Compositing pages onto pages -- the basis of Merge, booklets and margins."""

    def out(self, name="layers.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def entry(self, page):
        from pdfarranger_qt.layers import entry_from_page

        return entry_from_page(page)

    def test_pasting_a_page_adds_one_layer(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(dest.layerpages), 1)
        self.assertEqual(dest.layerpages[0].laypos, OVERLAY)

    def test_same_size_paste_covers_the_page(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        offset = dest.layerpages[0].offset
        for side in offset:
            self.assertAlmostEqual(side, 0.0, places=6,
                                   msg=f"equal sizes should sit flush: {offset}")

    def test_offset_places_the_layer_left_or_right(self):
        from pdfarranger_qt.core import OVERLAY, Dims, Page
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        src = self.model.pages[0]
        wide = Dims(src.size_in_points().width * 2, src.size_in_points().height)
        name, nfile = self.docs.get_blank_doc(wide)

        left_sheet = Page(nfile, 1, name, size_orig=wide)
        right_sheet = Page(nfile, 1, name, size_orig=wide)
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([left_sheet], stacks, OVERLAY, (0, 0.5), self.docs)
        paste_as_layer([right_sheet], stacks, OVERLAY, (1, 0.5), self.docs)

        self.assertAlmostEqual(left_sheet.layerpages[0].offset.left, 0.0, places=6)
        self.assertAlmostEqual(left_sheet.layerpages[0].offset.right, 0.5, places=6)
        self.assertAlmostEqual(right_sheet.layerpages[0].offset.left, 0.5, places=6)
        self.assertAlmostEqual(right_sheet.layerpages[0].offset.right, 0.0, places=6)

    def test_nested_layers_are_carried_across(self):
        """A page that already has a layer keeps it when pasted onto another."""
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        a, b, = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(b)], OVERLAY, self.docs)
        paste_as_layer([a], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(a.layerpages), 1)

        target = a.duplicate()
        target.layerpages = []
        stacks = layer_stacks_from_entries([self.entry(a)], OVERLAY, self.docs)
        paste_as_layer([target], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(target.layerpages), 2, "nested layer was lost")

    def test_composited_page_exports(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        path = self.out()
        self.assertEqual(
            export(self.docs.files_for_export(), [dest], {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 1, "the layer must not become a page")

    def test_center_on_blank_pages_adds_margins(self):
        from pdfarranger_qt.core import Dims
        from pdfarranger_qt.layers import center_on_blank_pages

        bigger = Dims(842, 1191)  # A3-ish, larger than the test page
        out = center_on_blank_pages([self.model.pages[0]], bigger, self.docs)
        self.assertEqual(out[0].size_in_points(), bigger)
        self.assertEqual(len(out[0].layerpages), 1)
        offset = out[0].layerpages[0].offset
        self.assertAlmostEqual(offset.left, offset.right, places=6, msg="not centred")
        self.assertAlmostEqual(offset.top, offset.bottom, places=6, msg="not centred")

    def test_center_leaves_matching_sizes_alone(self):
        from pdfarranger_qt.layers import center_on_blank_pages

        page = self.model.pages[0]
        out = center_on_blank_pages([page], page.size_in_points(), self.docs)
        self.assertIs(out[0], page)
