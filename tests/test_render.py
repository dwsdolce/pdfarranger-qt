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

"""The render worker, the thumbnail cache and MemoryDocument."""

import unittest

from support import QtDocumentTestCase

from pdfarranger_qt.core import Sides
from pdfarranger_qt.render import ThumbnailCache


class TestCache(unittest.TestCase):
    def test_evicts_by_pixel_budget(self):
        from PySide6.QtGui import QImage

        cache = ThumbnailCache(max_pixels=100 * 100 * 2)
        for i in range(5):
            cache.put(i, QImage(100, 100, QImage.Format_ARGB32))
        self.assertLessEqual(len(cache), 2)
        self.assertIsNotNone(cache.get(4))  # most recent survives
        self.assertIsNone(cache.get(0))

class TestRendering(QtDocumentTestCase):
    @staticmethod
    def ink_profile(image):
        """Return (widest row, tallest column) as fractions of the image.

        test.pdf is a triangle standing on its base, so this says which way the
        content is facing without needing a pixel-exact reference image.
        """
        w, h = image.width(), image.height()

        def ink(x, y):
            c = image.pixelColor(x, y)
            return (c.alpha() > 128 and max(c.red(), c.green()) > 140
                    and min(c.red(), c.green()) < 120)

        rows = [sum(1 for x in range(w) if ink(x, y)) for y in range(h)]
        cols = [sum(1 for y in range(h) if ink(x, y)) for x in range(w)]
        assert max(rows) > 0, "no ink found in rendered page"
        return rows.index(max(rows)) / (h - 1), cols.index(max(cols)) / (w - 1)

    def test_renders_every_page(self):
        images = self.render_all()
        self.assertTrue(all(img is not None and not img.isNull() for img in images))
        self.assertAlmostEqual(images[0].width() / images[0].height(), 612 / 792, delta=0.02)

    def test_rotation_reaches_the_pixels(self):
        """Regression: setScaledClipRect made QtPdf drop the rotation."""
        upright = self.ink_profile(self.render_all()[0])
        self.assertGreater(upright[0], 0.6, "base should be near the bottom")

        self.model.rotate([0], 90)
        rotated_img = self.render_all()[0]
        self.assertGreater(rotated_img.width(), rotated_img.height())
        sideways = self.ink_profile(rotated_img)
        self.assertLess(sideways[1], 0.4, "base should have moved to the left")

    def test_crop_shrinks_the_result(self):
        full = self.render_all()[0]
        self.model.pages[0].crop = Sides(0.25, 0.25, 0, 0)
        cropped = self.render_all()[0]
        # Same requested width, so cropping shows less page at higher detail:
        # the aspect ratio must get taller.
        self.assertGreater(cropped.height() / cropped.width(), full.height() / full.width())


class TestCompositedThumbnails(QtDocumentTestCase):
    """A page whose content lives in layers has to appear in the grid.

    The bug this guards: the render task carried only the page's own source,
    angle, crop and hide, so a page built out of layers -- an N-up sheet, a
    booklet sheet -- drew as an empty page in the grid while read mode, which
    goes through the exporter, drew it correctly.
    """

    def setUp(self):
        super().setUp()
        self.model.doc_files = self.docs.files_for_export

    def thumbnail(self, pages):
        from support import settle

        self.model.set_pages(pages)
        self.model.ensure_rendered(0, self.model.rowCount() - 1)
        settle(lambda: self.model.data(self.model.index(0, 0),
                                       self.model.ImageRole) is not None,
               timeout_ms=8000)
        return self.model.data(self.model.index(0, 0), self.model.ImageRole)

    @staticmethod
    def colours(image):
        """Which of the fixture's two triangles appear, by their colour."""
        found = set()
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() < 128:
                    continue
                if pixel.red() > 180 and pixel.green() < 120:
                    found.add("red")
                elif pixel.green() > 180 and pixel.red() < 120:
                    found.add("green")
        return found

    def four_pages(self):
        return self.model.pages + [p.duplicate() for p in self.model.pages]

    def test_a_plain_page_still_shows_its_own_content(self):
        """The fast path is untouched: page one is the red triangle."""
        image = self.thumbnail(self.model.pages)
        self.assertEqual(self.colours(image), {"red"})

    def test_an_nup_sheet_shows_the_pages_tiled_onto_it(self):
        from pdfarranger_qt import nup

        sheets = nup.generate(self.model.pages, 2, 1, self.docs)
        self.assertEqual(len(sheets), 1)
        image = self.thumbnail(sheets)
        self.assertEqual(self.colours(image), {"red", "green"},
                         "the tiled pages are missing from the thumbnail")

    def test_a_four_up_sheet_shows_all_four(self):
        from pdfarranger_qt import nup

        image = self.thumbnail(nup.generate(self.four_pages(), 2, 2, self.docs))
        self.assertEqual(self.colours(image), {"red", "green"})

    def test_a_booklet_sheet_is_not_blank_either(self):
        """Pre-existing: imposition has produced layer-only sheets since phase 2."""
        from pdfarranger_qt import booklet

        image = self.thumbnail(booklet.generate(self.model.pages, self.docs))
        self.assertTrue(self.colours(image), "the booklet sheet drew as blank")

    def test_the_key_changes_when_a_layer_is_added(self):
        """Otherwise the cache keeps answering with the pre-layer bitmap."""
        from pdfarranger_qt import stamp

        page = self.model.pages[0]
        before = page.render_key(120)
        stamp.add_watermark([page], self.docs, "DRAFT")
        self.assertNotEqual(page.render_key(120), before)

    def test_the_key_is_still_hashable(self):
        """It is a dict key in the cache; an unhashable member breaks every lookup."""
        from pdfarranger_qt import nup

        sheet = nup.generate(self.model.pages, 2, 1, self.docs)[0]
        self.assertIsInstance(hash(sheet.render_key(120)), int)

    def test_a_plain_page_asks_for_no_files(self):
        """The composited path is the exception, not the rule.

        A page with no layers must not drag the exporter into every thumbnail.
        """
        asked = []
        self.model.doc_files = lambda: asked.append(1) or []
        self.model.ensure_rendered(0, self.model.rowCount() - 1)
        self.assertEqual(asked, [])
