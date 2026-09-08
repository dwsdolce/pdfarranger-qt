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

"""Page numbers and watermarks -- the two users of the text primitive.

A caveat that shapes every test here: the offscreen Qt platform the suite runs
under has an **empty font database**, so drawn text comes out as the empty box
a missing glyph produces. Those boxes are drawn where the glyphs would be, so
*position* and *presence* are measurable exactly as usual; whether the result
is real, selectable text is not, and the tests that ask are guarded by
`stamp.has_fonts()` so they run wherever fonts exist and skip where they do
not. Saying so beats a suite that quietly proves less than it appears to.
"""

import os
import tempfile
import unittest

import pikepdf
from support import QtDocumentTestCase

from pdfarranger_qt import raster, stamp

PPI = 72


def out(name="stamp.pdf"):
    return os.path.join(tempfile.mkdtemp(), name)


class TestFormatNumber(unittest.TestCase):
    def test_the_page_number(self):
        self.assertEqual(stamp.format_number("{n}", 3, 10), "3")

    def test_both_tokens(self):
        self.assertEqual(stamp.format_number("Page {n} of {total}", 3, 10),
                         "Page 3 of 10")

    def test_a_template_with_no_tokens_is_left_alone(self):
        self.assertEqual(stamp.format_number("Draft", 3, 10), "Draft")

    def test_a_stray_brace_is_not_an_error(self):
        """str.format would raise here; that is why this is not str.format."""
        self.assertEqual(stamp.format_number("{n} of {", 2, 5), "2 of {")

    def test_an_unknown_placeholder_survives_as_itself(self):
        self.assertEqual(stamp.format_number("{page} {n}", 2, 5), "{page} 2")

    def test_repeated_tokens(self):
        self.assertEqual(stamp.format_number("{n}/{n}", 4, 9), "4/4")


class TestStyle(unittest.TestCase):
    def test_the_named_family_comes_first(self):
        style = stamp.Style(font="Comic Sans MS")
        self.assertEqual(style.qfont().families()[0], "Comic Sans MS")

    def test_fallbacks_follow_and_are_not_duplicated(self):
        families = stamp.Style(font="Arial").qfont().families()
        self.assertEqual(families.count("Arial"), 1)
        self.assertIn("DejaVu Sans", families)

    def test_a_size_of_zero_is_refused_rather_than_drawn(self):
        """QFont treats 0 as invalid and silently keeps the old size."""
        self.assertGreater(stamp.Style(size=0).qfont().pointSizeF(), 0)

    def test_the_two_presets_differ_where_they_should(self):
        self.assertEqual(stamp.NUMBER_STYLE.opacity, 1.0)
        self.assertLess(stamp.WATERMARK_STYLE.opacity, 0.5)
        self.assertEqual(stamp.WATERMARK_STYLE.position, "centre")
        self.assertGreater(stamp.WATERMARK_STYLE.size, stamp.NUMBER_STYLE.size)

    def test_every_position_has_a_label_and_flags(self):
        for key, label, flags in stamp.POSITIONS:
            with self.subTest(position=key):
                self.assertTrue(label())
                self.assertTrue(int(flags))


class TestRenderStamps(unittest.TestCase):
    def test_one_page_per_text(self):
        path = stamp.render_stamps(out(), [(612, 792)] * 3, ["a", "b", "c"],
                                   stamp.Style())
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 3)

    def test_the_page_is_exactly_the_size_asked_for(self):
        path = stamp.render_stamps(out(), [(200, 400)], ["x"], stamp.Style())
        with pikepdf.open(path) as pdf:
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], 200, delta=1.0)
            self.assertAlmostEqual(box[3] - box[1], 400, delta=1.0)

    def test_pages_may_differ_in_size(self):
        path = stamp.render_stamps(out(), [(200, 400), (600, 300)], ["a", "b"],
                                   stamp.Style())
        with pikepdf.open(path) as pdf:
            first = [float(v) for v in pdf.pages[0].MediaBox]
            second = [float(v) for v in pdf.pages[1].MediaBox]
            self.assertAlmostEqual(first[2], 200, delta=1.0)
            self.assertAlmostEqual(second[2], 600, delta=1.0)

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(ValueError):
            stamp.render_stamps(out(), [(612, 792)], ["a", "b"], stamp.Style())

    def test_nothing_to_stamp_is_refused(self):
        with self.assertRaises(ValueError):
            stamp.render_stamps(out(), [], [], stamp.Style())

    def test_an_unknown_position_is_refused(self):
        with self.assertRaises(ValueError):
            stamp.render_stamps(out(), [(612, 792)], ["x"],
                                stamp.Style(position="nowhere"))

    @unittest.skipUnless(stamp.has_fonts(), "this Qt platform has no fonts")
    def test_the_result_is_real_text(self):
        """Not an image and not outlines: it can be selected and searched."""
        from PySide6.QtPdf import QPdfDocument

        path = stamp.render_stamps(out(), [(612, 792)], ["Page 1 of 2"],
                                   stamp.Style())
        document = QPdfDocument()
        document.load(path)
        self.assertEqual(document.getAllText(0).text().strip(), "Page 1 of 2")


class StampTestCase(QtDocumentTestCase):
    def ink_box(self, image):
        """Bounding box of anything darker than the page, or None."""
        xs, ys = [], []
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                pixel = image.pixelColor(x, y)
                if pixel.red() < 160 and pixel.green() < 160 and pixel.blue() < 160:
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def render(self, pages=None):
        pages = self.model.pages if pages is None else pages
        return list(raster.render_pages(pages, self.docs.files_for_export(),
                                        ppi=PPI))


class TestApply(StampTestCase):
    def test_a_stamp_is_a_layer_not_a_new_page(self):
        before = len(self.model.pages)
        stamp.add_page_numbers(self.model.pages, self.docs)
        self.assertEqual(len(self.model.pages), before)
        self.assertEqual([len(p.layerpages) for p in self.model.pages], [1, 1])

    def test_stamps_accumulate(self):
        stamp.add_page_numbers(self.model.pages, self.docs)
        stamp.add_watermark(self.model.pages, self.docs, "DRAFT")
        self.assertEqual([len(p.layerpages) for p in self.model.pages], [2, 2])

    def test_it_survives_an_export(self):
        stamp.add_page_numbers(self.model.pages, self.docs)
        path = self.out("numbered.pdf")
        from pdfarranger_qt.export import export

        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(ValueError):
            stamp.apply(self.model.pages, ["only one"], self.docs)

    def test_an_empty_text_leaves_the_page_untouched(self):
        stamp.apply(self.model.pages, ["", "here"], self.docs)
        self.assertEqual([len(p.layerpages) for p in self.model.pages], [0, 1])


class TestPageNumbers(StampTestCase):
    def texts(self, **kwargs):
        """What add_page_numbers would stamp, without stamping it."""
        recorded = []
        real = stamp.apply

        def capture(pages, texts, docs, style=None):
            recorded.extend(texts)

        stamp.apply = capture
        try:
            stamp.add_page_numbers(self.model.pages, self.docs, **kwargs)
        finally:
            stamp.apply = real
        return recorded

    def test_numbered_from_one(self):
        self.assertEqual(self.texts(), ["1", "2"])

    def test_a_starting_number(self):
        self.assertEqual(self.texts(start=7), ["7", "8"])

    def test_the_total_counts_the_pages_stamped(self):
        self.assertEqual(self.texts(template="{n}/{total}"), ["1/2", "2/2"])

    def test_skipping_the_first_page_still_counts_it(self):
        """A title page carries no number, but page two is still page two."""
        self.assertEqual(self.texts(skip_first=True), ["", "2"])

    def test_the_stamp_lands_near_the_bottom(self):
        stamp.add_page_numbers(self.model.pages, self.docs,
                               style=stamp.Style(position="bottom-centre"))
        image = self.render()[0]
        # The fixture's triangle stops well short of the bottom edge, so ink
        # in the bottom eighth can only be the stamp.
        strip = image.copy(0, int(image.height() * 0.875),
                           image.width(), int(image.height() * 0.125))
        self.assertIsNotNone(self.ink_box(strip),
                             "nothing was drawn at the bottom of the page")

    def test_the_position_is_obeyed(self):
        """Top and bottom must not come out in the same place."""
        top = self.model.pages[0]
        bottom = self.model.pages[1]
        stamp.apply([top], ["X"], self.docs, stamp.Style(position="top-centre"))
        stamp.apply([bottom], ["X"], self.docs,
                    stamp.Style(position="bottom-centre"))
        images = self.render()
        strip_h = int(images[0].height() * 0.1)
        top_strip = images[0].copy(0, 0, images[0].width(), strip_h)
        bottom_strip = images[1].copy(0, images[1].height() - strip_h,
                                      images[1].width(), strip_h)
        self.assertIsNotNone(self.ink_box(top_strip))
        self.assertIsNotNone(self.ink_box(bottom_strip))
        # And the converse: neither ended up at the other end.
        self.assertIsNone(self.ink_box(
            images[0].copy(0, images[0].height() - strip_h,
                           images[0].width(), strip_h)))

    @unittest.skipUnless(stamp.has_fonts(), "this Qt platform has no fonts")
    def test_the_numbers_are_extractable_text_after_export(self):
        from pdfarranger_qt.export import export

        stamp.add_page_numbers(self.model.pages, self.docs,
                               template="Page {n} of {total}")
        path = self.out("numbered.pdf")
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        from PySide6.QtPdf import QPdfDocument

        document = QPdfDocument()
        document.load(path)
        self.assertIn("Page 1 of 2", document.getAllText(0).text())


class TestWatermark(StampTestCase):
    def test_every_page_gets_the_same_text(self):
        stamp.add_watermark(self.model.pages, self.docs, "DRAFT")
        self.assertEqual([len(p.layerpages) for p in self.model.pages], [1, 1])

    def test_an_empty_watermark_is_refused(self):
        with self.assertRaises(ValueError):
            stamp.add_watermark(self.model.pages, self.docs, "")

    def test_it_lands_in_the_middle_of_the_page(self):
        page = self.model.pages[0]
        stamp.add_watermark([page], self.docs, "DRAFT",
                            style=stamp.Style(size=64, position="centre",
                                              opacity=1.0, colour="#000000"))
        image = self.render([page])[0]
        box = self.ink_box(image)
        self.assertIsNotNone(box)
        # Dark ink at all is the stamp: the fixture's triangle is pure red.
        middle_y = (box[1] + box[3]) / 2
        self.assertAlmostEqual(middle_y, image.height() / 2,
                               delta=image.height() * 0.2)

    def test_rotation_changes_the_shape_of_what_is_drawn(self):
        """A turned watermark is taller relative to its width than a flat one.

        Measured on the stamp sheet alone rather than on a stamped page: the
        fixture's triangle is *stroked in black*, so a "find the dark ink"
        probe over a stamped page finds the triangle's outline and reports the
        same box whatever the stamp does. That probe passed identically for
        both rotations, which is how this was caught.
        """
        common = dict(size=48, position="centre", opacity=1.0, colour="#000000")
        flat = self.stamp_ink(stamp.Style(rotation=0, **common))
        turned = self.stamp_ink(stamp.Style(rotation=45, **common))
        self.assertGreater(self.aspect(turned), self.aspect(flat))

    def test_a_flat_watermark_is_wider_than_it_is_tall(self):
        """The premise of the test above: one line of text is a wide box."""
        box = self.stamp_ink(stamp.Style(size=48, position="centre"))
        self.assertGreater(box[2] - box[0], box[3] - box[1])

    @staticmethod
    def aspect(box):
        return (box[3] - box[1]) / max(box[2] - box[0], 1)

    def stamp_ink(self, style, text="WATERMARK", size=(612, 792)):
        """Where the ink is on a stamp sheet of its own, with nothing else on it."""
        from pdfarranger_qt.core import DocumentSet

        path = stamp.render_stamps(out(), [size], [text], style)
        docs = DocumentSet()
        try:
            pages = docs.add_file(path)
            image = list(raster.render_pages(pages, docs.files_for_export(),
                                             ppi=PPI))[0]
        finally:
            docs.cleanup()
        box = self.ink_box(image)
        self.assertIsNotNone(box, "the stamp sheet came out blank")
        return box
