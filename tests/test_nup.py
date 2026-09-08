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

"""Pages per sheet.

The geometry claims are checked by *rendering* the result and looking at where
the ink is, because that is the only question that matters and offsets can be
plausibly wrong in ways arithmetic assertions agree with. The fixture is two
full-page triangles, page 1 red and page 2 green, which makes "which page
landed in which cell" a colour lookup.
"""

import unittest

from support import QtDocumentTestCase

from pdfarranger_qt import nup, raster
from pdfarranger_qt.core import Dims

#: Rendering resolution. Low on purpose: the tests ask which quadrant is red,
#: not how well an edge is anti-aliased, and every one of them renders.
PPI = 36


class NUpTestCase(QtDocumentTestCase):
    def sheets(self, pages, columns, rows, **kwargs):
        return nup.generate(pages, columns, rows, self.docs, **kwargs)

    def render(self, sheets):
        return list(raster.render_pages(sheets, self.docs.files_for_export(),
                                        ppi=PPI))

    def colour_of(self, image, x0, y0, x1, y1):
        """"red", "green" or "blank" for a rectangle of the rendered sheet."""
        red = green = 0
        for y in range(int(y0), int(y1), 2):
            for x in range(int(x0), int(x1), 2):
                pixel = image.pixelColor(x, y)
                if pixel.red() > 200 and pixel.green() < 200:
                    red += 1
                elif pixel.green() > 200 and pixel.red() < 200:
                    green += 1
        if red == green == 0:
            return "blank"
        return "red" if red > green else "green"

    def quadrants(self, image):
        w, h = image.width(), image.height()
        return {
            "top left": self.colour_of(image, 0, 0, w / 2, h / 2),
            "top right": self.colour_of(image, w / 2, 0, w, h / 2),
            "bottom left": self.colour_of(image, 0, h / 2, w / 2, h),
            "bottom right": self.colour_of(image, w / 2, h / 2, w, h),
        }

    def four_pages(self):
        """Red, green, red, green."""
        return self.model.pages + [p.duplicate() for p in self.model.pages]


class TestTheFixture(NUpTestCase):
    """Every geometry test below reads colours; this is what they mean."""

    def test_page_one_is_red_and_page_two_is_green(self):
        images = self.render(self.model.pages)
        w, h = images[0].width(), images[0].height()
        self.assertEqual(self.colour_of(images[0], 0, 0, w, h), "red")
        self.assertEqual(self.colour_of(images[1], 0, 0, w, h), "green")


class TestCanGenerate(NUpTestCase):
    def test_nothing_cannot_be_tiled(self):
        self.assertFalse(nup.can_generate([]))

    def test_equal_pages_can(self):
        self.assertTrue(nup.can_generate(self.model.pages))

    def test_mixed_sizes_cannot(self):
        pages = self.model.pages
        pages[1].scale = 0.5
        self.assertFalse(nup.can_generate(pages))


class TestGrid(NUpTestCase):
    def test_reading_order_across_then_down(self):
        sheet = self.render(self.sheets(self.four_pages(), 2, 2))[0]
        self.assertEqual(self.quadrants(sheet), {
            "top left": "red", "top right": "green",
            "bottom left": "red", "bottom right": "green",
        })

    def test_a_single_column_runs_down_the_page(self):
        sheets = self.sheets(self.model.pages, 1, 2, orientation=nup.PORTRAIT)
        image = self.render(sheets)[0]
        w, h = image.width(), image.height()
        self.assertEqual(self.colour_of(image, 0, 0, w, h / 2), "red")
        self.assertEqual(self.colour_of(image, 0, h / 2, w, h), "green")

    def test_a_single_row_runs_across_the_page(self):
        sheets = self.sheets(self.model.pages, 2, 1)
        image = self.render(sheets)[0]
        w, h = image.width(), image.height()
        self.assertEqual(self.colour_of(image, 0, 0, w / 2, h), "red")
        self.assertEqual(self.colour_of(image, w / 2, 0, w, h), "green")

    def test_every_cell_gets_ink(self):
        """A tile placed off the sheet would leave a quadrant blank."""
        sheet = self.render(self.sheets(self.four_pages(), 2, 2))[0]
        self.assertNotIn("blank", self.quadrants(sheet).values())

    def test_one_sheet_per_full_group(self):
        self.assertEqual(len(self.sheets(self.four_pages(), 2, 2)), 1)
        self.assertEqual(len(self.sheets(self.four_pages(), 2, 1)), 2)

    def test_the_last_sheet_is_short_not_padded(self):
        """Unlike a booklet: nothing here has to fold, so nothing is padded."""
        sheets = self.sheets(self.four_pages() + [self.model.pages[0].duplicate()],
                             2, 2)
        self.assertEqual(len(sheets), 2)
        self.assertEqual(len(sheets[-1].layerpages), 1)

    def test_a_short_last_sheet_leaves_the_empty_cells_blank(self):
        sheets = self.sheets(self.model.pages, 2, 2, orientation=nup.PORTRAIT)
        quadrants = self.quadrants(self.render(sheets)[0])
        self.assertEqual(quadrants["top left"], "red")
        self.assertEqual(quadrants["top right"], "green")
        self.assertEqual(quadrants["bottom left"], "blank")
        self.assertEqual(quadrants["bottom right"], "blank")

    def test_a_grid_needs_a_column_and_a_row(self):
        for columns, rows in ((0, 1), (1, 0), (-1, 2)):
            with self.subTest(columns=columns, rows=rows):
                with self.assertRaises(ValueError):
                    self.sheets(self.model.pages, columns, rows)


class TestOrientation(NUpTestCase):
    def portrait(self):
        return self.model.pages[0].size_in_points()

    def test_two_up_turns_the_sheet_sideways(self):
        """Two portrait pages side by side want a landscape sheet."""
        width, height = self.portrait()
        sheet = self.sheets(self.model.pages, 2, 1)[0].size_in_points()
        self.assertEqual(sheet, Dims(height, width))

    def test_four_up_keeps_the_orientation(self):
        """A 2x2 grid is the same shape as the page, so nothing turns."""
        sheet = self.sheets(self.four_pages(), 2, 2)[0].size_in_points()
        self.assertEqual(sheet, Dims(*self.portrait()))

    def test_an_explicit_orientation_is_obeyed(self):
        width, height = self.portrait()
        forced = self.sheets(self.model.pages, 2, 1,
                             orientation=nup.PORTRAIT)[0].size_in_points()
        self.assertEqual(forced, Dims(width, height))

    def test_automatic_never_scales_smaller_than_the_alternative(self):
        """The claim the AUTO branch is making, checked as arithmetic."""
        size = self.portrait()
        for columns, rows, _label in nup.PRESETS:
            with self.subTest(columns=columns, rows=rows):
                chosen = nup.sheet_size(size, columns, rows, nup.AUTO)
                other = Dims(chosen[1], chosen[0])
                self.assertGreaterEqual(
                    nup._fit(chosen, size, columns, rows),
                    nup._fit(other, size, columns, rows))

    def test_an_explicit_size_overrides_the_orientation(self):
        wanted = Dims(1000.0, 500.0)
        sheet = self.sheets(self.model.pages, 2, 1, size=wanted)[0]
        self.assertEqual(sheet.size_in_points(), wanted)


class TestMargin(NUpTestCase):
    """The gap is measured by where the ink stops, not by probing the seam.

    The fixture's triangles do not reach the page edges, so the middle of a
    two-up sheet is white whether there is a gap or not -- a seam probe passes
    for the wrong reason. What a gap actually does is draw everything smaller
    and further in, and that is what these measure.
    """

    def ink_box(self, image, colour):
        """The bounding box of one colour, as (left, top, right, bottom)."""
        xs, ys = [], []
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                pixel = image.pixelColor(x, y)
                red = pixel.red() > 200 and pixel.green() < 200
                green = pixel.green() > 200 and pixel.red() < 200
                if (colour == "red" and red) or (colour == "green" and green):
                    xs.append(x)
                    ys.append(y)
        self.assertTrue(xs, f"no {colour} ink on the sheet at all")
        return min(xs), min(ys), max(xs), max(ys)

    def two_up(self, margin):
        return self.render(self.sheets(self.model.pages, 2, 1, margin=margin))[0]

    def test_a_gap_draws_the_tiles_smaller(self):
        without = self.ink_box(self.two_up(0.0), "red")
        with_gap = self.ink_box(self.two_up(0.2), "red")
        self.assertLess(with_gap[2] - with_gap[0], without[2] - without[0])
        self.assertLess(with_gap[3] - with_gap[1], without[3] - without[1])

    def test_a_gap_moves_the_tiles_inward(self):
        """The left tile leaves the left edge; the right tile leaves the right."""
        image = self.two_up(0.2)
        plain = self.two_up(0.0)
        self.assertGreater(self.ink_box(image, "red")[0],
                           self.ink_box(plain, "red")[0])
        self.assertLess(self.ink_box(image, "green")[2],
                        self.ink_box(plain, "green")[2])

    def test_the_gap_does_not_push_anything_off_the_sheet(self):
        image = self.two_up(0.45)
        for colour in ("red", "green"):
            left, top, right, bottom = self.ink_box(image, colour)
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLess(right, image.width())
            self.assertLess(bottom, image.height())

    def test_the_tiles_are_still_in_order_with_a_gap(self):
        image = self.two_up(0.2)
        w, h = image.width(), image.height()
        self.assertEqual(self.colour_of(image, 0, 0, w / 2, h), "red")
        self.assertEqual(self.colour_of(image, w / 2, 0, w, h), "green")

    def test_each_tile_stays_in_its_own_half(self):
        """The strongest statement of "in the right cell" available here."""
        image = self.two_up(0.1)
        self.assertLess(self.ink_box(image, "red")[2], image.width() / 2)
        self.assertGreater(self.ink_box(image, "green")[0], image.width() / 2)


class TestPresets(unittest.TestCase):
    def test_each_preset_says_what_it_does(self):
        for columns, rows, label in nup.PRESETS:
            with self.subTest(label=label()):
                self.assertIn(str(columns * rows), label())

    def test_none_of_them_is_one_up(self):
        for columns, rows, _label in nup.PRESETS:
            self.assertGreater(columns * rows, 1)
