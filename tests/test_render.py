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

from pdfarranger_qt.core import Sides
from pdfarranger_qt.render import ThumbnailCache

from support import QtDocumentTestCase


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
