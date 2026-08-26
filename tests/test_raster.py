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

"""Rasterising pages and the images embedded in them."""

import os
import unittest
import pikepdf

from pdfarranger_qt.core import Dims, DocumentSet, Page, Sides

from support import QtDocumentTestCase, TEST_PDF, TEXT_PDF


class TestRaster(QtDocumentTestCase):
    def files(self):
        return self.docs.files_for_export()

    def test_render_pages_matches_page_geometry(self):
        from pdfarranger_qt import raster

        images = list(raster.render_pages(self.model.pages, self.files(), 72))
        self.assertEqual(len(images), 2)
        self.assertEqual((images[0].width(), images[0].height()), (612, 792))

    def test_render_honours_ppi(self):
        from pdfarranger_qt import raster

        images = list(raster.render_pages(self.model.pages[:1], self.files(), 144))
        self.assertEqual(images[0].width(), 1224)

    def test_render_reflects_edits_not_the_source(self):
        from pdfarranger_qt import raster

        self.model.rotate([0], 90)
        image = next(raster.render_pages(self.model.pages[:1], self.files(), 72))
        self.assertGreater(image.width(), image.height())

    def test_renders_are_flattened_onto_white(self):
        """Regression: transparent renders made greyscale see every pixel as ink."""
        from pdfarranger_qt import raster

        image = next(raster.render_pages(self.model.pages[:1], self.files(), 72))
        corner = image.pixelColor(2, 2)
        self.assertGreater(corner.lightness(), 200, "page background should be white")

    def test_white_border_detection_finds_margins(self):
        from pdfarranger_qt import raster

        crops = raster.white_border_crops(self.model.pages, self.files())
        self.assertEqual(len(crops), 2)
        for sides in crops:
            self.assertGreater(sum(sides), 0, "test.pdf has visible white margins")
            self.assertLess(sides.left + sides.right, 1.0)
            self.assertLess(sides.top + sides.bottom, 1.0)

    def test_white_border_detection_is_idempotent(self):
        """Running it twice must not creep further into the content."""
        from pdfarranger_qt import raster

        first = raster.white_border_crops(self.model.pages[:1], self.files())[0]
        self.model.set_margins([0], first, hide=False)
        second = raster.white_border_crops(self.model.pages[:1], self.files())[0]
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, delta=0.02)

    def test_blank_page_is_left_alone(self):
        from pdfarranger_qt import raster
        from pdfarranger_qt.core import Dims, Page

        name, nfile = self.docs.get_blank_doc(Dims(612, 792))
        blank = Page(nfile, 1, name, size_orig=Dims(612, 792))
        crops = raster.white_border_crops([blank], self.docs.files_for_export())
        self.assertEqual(crops[0], Sides(), "a blank page must not be cropped away")

    def test_export_images(self):
        import tempfile

        from pdfarranger_qt import raster

        target = tempfile.mkdtemp()
        paths = [os.path.join(target, f"p{i}.png") for i in range(2)]
        written = raster.export_images(self.model.pages, self.files(), paths, ppi=72)
        self.assertEqual(written, 2)
        for path in paths:
            self.assertGreater(os.path.getsize(path), 0)

    def test_export_images_greyscale(self):
        import tempfile

        from PySide6.QtGui import QImage
        from pdfarranger_qt import raster

        target = tempfile.mkdtemp()
        path = os.path.join(target, "grey.png")
        raster.export_images(self.model.pages[:1], self.files(), [path],
                             ppi=72, greyscale=True)
        loaded = QImage(path)
        self.assertTrue(loaded.isGrayscale() or loaded.allGray())

    def test_export_rasterised_pdf(self):
        import tempfile

        from pdfarranger_qt import raster

        path = os.path.join(tempfile.mkdtemp(), "flat.pdf")
        self.assertTrue(raster.export_rasterised_pdf(
            self.model.pages, self.files(), path, ppi=72))
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_rasterised_pdf_has_no_text(self):
        """The point of rasterising: nothing is extractable any more."""
        import tempfile

        from pdfarranger_qt import raster
        from pdfarranger_qt.core import DocumentSet

        source = DocumentSet()
        self.addCleanup(source.cleanup)
        pages = source.add_file(TEXT_PDF)
        before = raster.page_text(pages[:1], source.files_for_export())
        self.assertTrue(before.strip(), "fixture should have text to begin with")

        path = os.path.join(tempfile.mkdtemp(), "flat.pdf")
        raster.export_rasterised_pdf(pages[:1], source.files_for_export(),
                                     path, ppi=72)
        flat = DocumentSet()
        self.addCleanup(flat.cleanup)
        flat_pages = flat.add_file(path)
        after = raster.page_text(flat_pages[:1], flat.files_for_export())
        self.assertFalse(after.strip(), "rasterised output should have no text layer")

    def test_page_text_on_a_graphic_only_page(self):
        from pdfarranger_qt import raster

        self.assertEqual(raster.page_text(self.model.pages[:1], self.files()).strip(), "")

class TestEmbeddedImages(unittest.TestCase):
    """Extract and Explode work off the embedded images, not a render."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        # A scanned page is one big image; build one by rasterising a fixture.
        from pdfarranger_qt import raster

        source = DocumentSet()
        self.addCleanup(source.cleanup)
        pages = source.add_file(TEST_PDF)
        import tempfile

        self.scan = os.path.join(tempfile.mkdtemp(), "scan.pdf")
        raster.export_rasterised_pdf(pages[:1], source.files_for_export(),
                                     self.scan, ppi=72)
        self.pages = self.docs.add_file(self.scan)

    def files(self):
        return self.docs.files_for_export()

    def test_counts_the_embedded_images(self):
        from pdfarranger_qt import raster

        self.assertEqual(raster.count_embedded_images(self.pages[0], self.files()), 1)

    def test_extracts_the_image(self):
        from pdfarranger_qt import raster

        images = raster.embedded_images(self.pages[0], self.files())
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].size, (612, 792))

    def test_a_vector_page_has_no_embedded_images(self):
        from pdfarranger_qt import raster
        from pdfarranger_qt.core import DocumentSet

        plain = DocumentSet()
        self.addCleanup(plain.cleanup)
        pages = plain.add_file(TEST_PDF)
        self.assertEqual(
            raster.count_embedded_images(pages[0], plain.files_for_export()), 0)

    def test_explode_writes_one_file_per_image(self):
        from pdfarranger_qt import raster

        paths = raster.explode_to_files(self.pages[0], self.files(), self.docs.tmp_dir)
        self.assertEqual(len(paths), 1)
        self.assertTrue(os.path.getsize(paths[0]) > 0)

    def test_pil_to_qimage_preserves_size(self):
        from pdfarranger_qt import raster

        image = raster.embedded_images(self.pages[0], self.files())[0]
        qimage = raster.pil_to_qimage(image)
        self.assertEqual((qimage.width(), qimage.height()), image.size)
        self.assertFalse(qimage.isNull())
