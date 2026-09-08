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

"""Re-encoding the images inside a PDF.

The repository has no image fixtures -- every test PDF in it is vector -- which
is the immediate reason none of this was noticed before, so these build their
own. A page of rendered text on off-white paper at 300 ppi is what a scanner
or a phone hands you, and it is what the numbers in ``compress.py`` were
measured on.
"""

import io
import os
import unittest

import pikepdf
from PIL import Image, ImageDraw
from support import TEST_PDF, QtDocumentTestCase, temp_path

from pdfarranger_qt import compress
from pdfarranger_qt.core import OVERLAY, Sides

LETTER = (612.0, 792.0)


def text_page(ppi=300, size=LETTER, seed=0):
    """A page that looks like a scan: dark text on off-white paper."""
    width = int(size[0] * ppi / 72)
    height = int(size[1] * ppi / 72)
    image = Image.new("RGB", (width, height), (250, 249, 245))
    draw = ImageDraw.Draw(image)
    scale = ppi / 72
    y = int(40 * scale)
    while y < height - int(40 * scale):
        draw.text((int(40 * scale), y),
                  "the quick brown fox jumps over a lazy dog " * 2,
                  fill=(24, 24, 28))
        draw.line((int(40 * scale), y + int(6 * scale),
                   width - int(40 * scale), y + int(6 * scale)),
                  fill=(24, 24, 28), width=max(1, int(scale)))
        y += int(9 * scale) + seed % 3
    return image


def jpeg(image, quality=90):
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def flate(image):
    """Raw samples with no filter, so pikepdf deflates them on save."""
    return image.tobytes()


def embed(pdf, data, image, filter_=None, colorspace=None, bpc=8, **extra):
    """An image XObject, indirect so that several pages can share it."""
    stream = pikepdf.Stream(pdf, data)
    stream.Type = pikepdf.Name.XObject
    stream.Subtype = pikepdf.Name.Image
    stream.Width, stream.Height = image.width, image.height
    stream.BitsPerComponent = bpc
    if colorspace is not None:
        stream.ColorSpace = colorspace
    elif image.mode == "RGB":
        stream.ColorSpace = pikepdf.Name.DeviceRGB
    else:
        stream.ColorSpace = pikepdf.Name.DeviceGray
    if filter_ is not None:
        stream.Filter = filter_
    for key, value in extra.items():
        setattr(stream, key, value)
    return pdf.make_indirect(stream)


def page_with(pdf, entries, size=LETTER):
    """A page painting ``(stream, x, y, width, height)`` entries, in points."""
    content = []
    xobjects = {}
    for number, (stream, x, y, width, height) in enumerate(entries):
        name = f"/Im{number}"
        xobjects[name[1:]] = stream
        content.append(f"q {width} 0 0 {height} {x} {y} cm {name} Do Q")
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, size[0], size[1]],
        Contents=pikepdf.Stream(pdf, " ".join(content).encode()),
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(**xobjects)),
    )
    pdf.pages.append(pikepdf.Page(pdf.make_indirect(page)))
    return pdf.pages[-1]


def full_page_scan(pdf, ppi=300, quality=90, pages=1):
    """``pages`` pages, each a JPEG of the whole sheet at ``ppi``."""
    streams = []
    for number in range(pages):
        image = text_page(ppi, seed=number)
        stream = embed(pdf, jpeg(image, quality), image,
                       filter_=pikepdf.Name.DCTDecode)
        page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        streams.append(stream)
    return streams


def saved_size(pdf):
    buffer = io.BytesIO()
    pdf.save(buffer)
    return len(buffer.getvalue())


class TestMeasuringAPlacement(unittest.TestCase):
    """Resolution is a property of the placement, not of the image.

    A thousand pixels across half a page is twice the resolution of the same
    thousand across all of it, so the threshold cannot be applied without
    walking the content stream.
    """

    def test_multiply_composes_the_way_cm_does(self):
        """`cm` prepends: the new matrix applies before what is already there."""
        scale = (2.0, 0, 0, 2.0, 0, 0)
        move = (1.0, 0, 0, 1.0, 10.0, 5.0)
        # Scale, then translate: the translation is not scaled.
        self.assertEqual(compress.multiply(scale, move),
                         (2.0, 0.0, 0.0, 2.0, 10.0, 5.0))
        # Translate, then scale: it is.
        self.assertEqual(compress.multiply(move, scale),
                         (2.0, 0.0, 0.0, 2.0, 20.0, 10.0))

    def test_identity_leaves_a_matrix_alone(self):
        matrix = (3.0, 1.0, -1.0, 2.0, 7.0, 9.0)
        self.assertEqual(compress.multiply(matrix, compress.IDENTITY), matrix)
        self.assertEqual(compress.multiply(compress.IDENTITY, matrix), matrix)

    def test_drawn_size_measures_the_edges_not_the_diagonal(self):
        self.assertEqual(compress.drawn_size((100, 0, 0, 50, 0, 0)),
                         (100.0, 50.0))

    def test_a_rotated_placement_still_measures_its_edges(self):
        """A quarter turn: the painted rectangle is the same size, turned."""
        turned = compress.multiply((100, 0, 0, 50, 0, 0),
                                   (0, 1, -1, 0, 0, 0))
        width, height = compress.drawn_size(turned)
        self.assertAlmostEqual(width, 100.0)
        self.assertAlmostEqual(height, 50.0)

    def test_a_full_page_image_is_found_at_page_size(self):
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf)
        found = compress.placements(pdf.pages[0])
        self.assertEqual(found[streams[0].objgen], LETTER)

    def test_a_half_width_placement_doubles_the_resolution(self):
        pdf = pikepdf.Pdf.new()
        image = text_page(150)
        stream = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        page_with(pdf, [(stream, 0, 0, LETTER[0] / 2, LETTER[1] / 2)])
        width, _height = compress.placements(pdf.pages[0])[stream.objgen]
        self.assertAlmostEqual(width, LETTER[0] / 2)
        self.assertAlmostEqual(compress.effective_ppi(image.width, width),
                              300.0, places=1)

    def test_the_largest_use_of_a_shared_image_wins(self):
        """Shrinking to suit the small copy would wreck the big one."""
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        stream = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        page_with(pdf, [(stream, 0, 0, 100, 100), (stream, 0, 200, 400, 400)])
        self.assertEqual(compress.placements(pdf.pages[0])[stream.objgen],
                         (400.0, 400.0))

    def test_an_image_inside_a_form_is_found_through_its_matrix(self):
        """Scanners and composition tools alike nest images in forms."""
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        inner = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        form = pikepdf.Stream(pdf, b"q 1 0 0 1 0 0 cm /ImA Do Q")
        form.Type = pikepdf.Name.XObject
        form.Subtype = pikepdf.Name.Form
        form.BBox = [0, 0, 1, 1]
        # The form halves everything drawn inside it.
        form.Matrix = [0.5, 0, 0, 0.5, 0, 0]
        form.Resources = pikepdf.Dictionary(
            XObject=pikepdf.Dictionary(ImA=inner))
        form = pdf.make_indirect(form)
        page_with(pdf, [(form, 0, 0, 400, 400)])
        found = compress.placements(pdf.pages[0])
        self.assertIn(inner.objgen, found)
        self.assertEqual(found[inner.objgen], (200.0, 200.0))

    def test_an_unpainted_image_is_not_placed(self):
        """It has no resolution, so there is nothing to judge it against."""
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        stream = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        page_with(pdf, [])
        pdf.pages[0].Resources = pikepdf.Dictionary(
            XObject=pikepdf.Dictionary(Im0=stream))
        self.assertEqual(compress.placements(pdf.pages[0]), {})
        outcome = compress.compress(pdf).outcomes[0]
        self.assertEqual(outcome.action, compress.KEPT)
        self.assertEqual(outcome.reason, compress.NOT_PLACED)


class TestSurveyingWhatIsThere(unittest.TestCase):
    def test_counts_each_image_once_however_often_it_is_drawn(self):
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        stream = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        for _ in range(8):
            page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        images, size = compress.survey(pdf)
        self.assertEqual(images, 1)
        self.assertEqual(size, len(stream.read_raw_bytes()))

    def test_a_page_range_limits_the_survey(self):
        pdf = pikepdf.Pdf.new()
        full_page_scan(pdf, pages=3)
        self.assertEqual(compress.survey(pdf)[0], 3)
        self.assertEqual(compress.survey(pdf, pages=[0])[0], 1)

    def test_a_vector_page_has_nothing_to_survey(self):
        pdf = pikepdf.Pdf.new()
        page_with(pdf, [])
        self.assertEqual(compress.survey(pdf), (0, 0))


class TestDownsampling(unittest.TestCase):
    def test_a_300_ppi_scan_comes_down_to_the_target(self):
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf)
        result = compress.compress(pdf, compress.Settings(ppi=150, quality=75))
        outcome = result.outcomes[0]
        self.assertEqual(outcome.action, compress.DOWNSAMPLED)
        self.assertAlmostEqual(outcome.ppi, 150, delta=1)
        self.assertEqual(int(streams[0].Width), outcome.size[0])
        self.assertAlmostEqual(outcome.size[0], 612 * 150 / 72, delta=1)

    def test_the_file_actually_gets_smaller(self):
        """The end that matters, measured on the file rather than the plan."""
        pdf = pikepdf.Pdf.new()
        full_page_scan(pdf, pages=4)
        before = saved_size(pdf)
        result = compress.compress(pdf, compress.PRESETS[compress.BALANCED])
        after = saved_size(pdf)
        self.assertLess(after, before * 0.5)
        self.assertGreater(result.fraction, 0.5)
        self.assertEqual(result.changed, 4)

    def test_quality_alone_keeps_every_pixel(self):
        """Worth 40% on its own, which is why ppi is allowed to be None."""
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf, quality=95)
        width = int(streams[0].Width)
        result = compress.compress(pdf, compress.Settings(ppi=None, quality=60))
        outcome = result.outcomes[0]
        self.assertEqual(outcome.action, compress.RECODED)
        self.assertEqual(outcome.size[0], width)
        self.assertGreater(outcome.saved, 0)

    def test_an_image_below_the_target_is_left_alone(self):
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf, ppi=100, quality=90)
        raw = bytes(streams[0].read_raw_bytes())
        result = compress.compress(pdf, compress.Settings(ppi=150))
        self.assertEqual(result.outcomes[0].reason, compress.BELOW_TARGET)
        self.assertEqual(bytes(streams[0].read_raw_bytes()), raw)

    def test_the_threshold_keeps_a_logo_intact(self):
        """A 96 ppi logo blindly resampled to 144 grows three and a half times.

        The threshold is the whole reason business documents -- text with a
        logo on them -- survive this feature.
        """
        pdf = pikepdf.Pdf.new()
        logo = Image.new("RGB", (200, 80), (255, 255, 255))
        ImageDraw.Draw(logo).rectangle((10, 10, 190, 70),
                                       outline=(20, 60, 140), width=6)
        drawn = (200 * 72 / 96, 80 * 72 / 96)
        stream = embed(pdf, flate(logo), logo)
        page_with(pdf, [(stream, 20, 700, drawn[0], drawn[1])])
        raw = bytes(stream.read_raw_bytes())
        result = compress.compress(pdf, compress.Settings(ppi=144, above=216))
        outcome = result.outcomes[0]
        self.assertEqual(outcome.action, compress.KEPT)
        self.assertEqual(outcome.reason, compress.BELOW_TARGET)
        self.assertAlmostEqual(outcome.ppi, 96, delta=1)
        self.assertEqual(bytes(stream.read_raw_bytes()), raw)

    def test_a_default_threshold_is_one_and_a_half_times_the_target(self):
        self.assertEqual(compress.Settings(ppi=150).threshold, 225)
        self.assertEqual(compress.Settings(ppi=150, above=200).threshold, 200)
        self.assertIsNone(compress.Settings(ppi=None).threshold)

    def test_an_image_that_would_grow_keeps_its_original_bytes(self):
        """A compressor that can enlarge a file is worse than no compressor."""
        pdf = pikepdf.Pdf.new()
        tiny = Image.new("RGB", (4, 4), (128, 200, 30))
        stream = embed(pdf, flate(tiny), tiny)
        page_with(pdf, [(stream, 0, 0, 1, 1)])   # 288 ppi in one point
        raw = bytes(stream.read_raw_bytes())
        result = compress.compress(pdf, compress.Settings(ppi=150))
        outcome = result.outcomes[0]
        self.assertEqual(outcome.reason, compress.WOULD_GROW)
        self.assertEqual(outcome.before, outcome.after)
        self.assertEqual(bytes(stream.read_raw_bytes()), raw)


class TestBilevelPages(unittest.TestCase):
    """Where JPEG is simply the wrong answer.

    Group 4 at full resolution is 0.52 MB against 1.98 MB for the industry
    default downsample -- four times smaller with nothing thrown away.
    """

    def bilevel_scan(self, pdf, ppi=300):
        image = text_page(ppi).convert("L")
        image = image.point(lambda v: 255 if v >= 128 else 0, mode="L")
        stream = embed(pdf, flate(image), image,
                       colorspace=pikepdf.Name.DeviceGray)
        page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        return stream, image

    def test_line_art_goes_to_group_4_at_full_resolution(self):
        pdf = pikepdf.Pdf.new()
        stream, image = self.bilevel_scan(pdf)
        result = compress.compress(pdf, compress.Settings(ppi=None))
        outcome = result.outcomes[0]
        self.assertEqual(outcome.action, compress.GROUP4)
        self.assertEqual(outcome.size, (image.width, image.height))
        self.assertEqual(str(stream.Filter), "/CCITTFaxDecode")
        self.assertEqual(int(stream.BitsPerComponent), 1)
        self.assertGreater(outcome.saved, 0)

    def test_group_4_beats_a_downsampled_jpeg_of_the_same_page(self):
        """The measured claim, re-measured rather than asserted."""
        with pikepdf.Pdf.new() as one, pikepdf.Pdf.new() as two:
            self.bilevel_scan(one)
            self.bilevel_scan(two)
            group4 = compress.compress(one, compress.Settings(ppi=None)).after
            # What a design with a single image path would have done.
            page = two.pages[0]
            for obj in compress.images_of(page).values():
                image = pikepdf.PdfImage(obj).as_pil_image()
                small = image.resize((image.width // 2, image.height // 2),
                                     compress.RESAMPLE)
                buffer = io.BytesIO()
                small.convert("L").save(buffer, "JPEG", quality=75)
                obj.write(buffer.getvalue(), filter=pikepdf.Name.DCTDecode)
                jpeg_bytes = len(buffer.getvalue())
        self.assertLess(group4, jpeg_bytes)

    def test_the_pixels_survive_the_round_trip(self):
        """Size proves compression, not correctness -- read it back.

        A Group 4 payload written with the wrong `BlackIs1` compresses just as
        well and renders as a photographic negative, which no size assertion
        would ever notice.
        """
        pdf = pikepdf.Pdf.new()
        stream, image = self.bilevel_scan(pdf, ppi=150)
        expected = compress.to_bilevel(image)
        compress.compress(pdf, compress.Settings(ppi=None))
        restored = pikepdf.PdfImage(stream).as_pil_image().convert("1")
        self.assertEqual(restored.size, expected.size)
        # tobytes() rather than getdata(): the latter is deprecated in Pillow
        # 12 and its replacement does not exist in the versions we allow.
        self.assertEqual(restored.tobytes(), expected.tobytes())

    def test_eight_bit_grey_that_is_really_two_valued_counts_as_bilevel(self):
        pdf = pikepdf.Pdf.new()
        _stream, image = self.bilevel_scan(pdf)
        self.assertEqual(image.mode, "L")
        self.assertEqual(compress.compress(
            pdf, compress.Settings(ppi=None)).outcomes[0].action,
            compress.GROUP4)

    def test_a_photograph_is_not_mistaken_for_line_art(self):
        pdf = pikepdf.Pdf.new()
        full_page_scan(pdf)
        self.assertEqual(compress.compress(
            pdf, compress.Settings(ppi=150)).outcomes[0].action,
            compress.DOWNSAMPLED)

    def test_thresholding_not_dithering(self):
        """Pillow dithers by default, and the noise costs nine times the size.

        A gradient thresholded has exactly one dark-to-light transition down a
        column; Floyd-Steinberg scatters dozens.
        """
        # `linear_gradient` runs top to bottom, so the varying axis is a
        # column. Reading a row instead gives a constant and no transitions at
        # all, which is a test that passes for the wrong reason.
        gradient = Image.linear_gradient("L")
        column = compress.to_bilevel(gradient).crop((4, 0, 5, 256))
        values = list(column.convert("L").tobytes())
        self.assertEqual(
            sum(1 for a, b in zip(values, values[1:]) if a != b), 1)
        scattered = list(gradient.convert("1").crop((4, 0, 5, 256))
                         .convert("L").tobytes())
        self.assertGreater(
            sum(1 for a, b in zip(scattered, scattered[1:]) if a != b), 20)


class TestWhatMustBeLeftAlone(unittest.TestCase):
    """Skipped and reported, never guessed at."""

    def placed(self, pdf, stream):
        page_with(pdf, [(stream, 0, 0, 72, 72)])

    def test_a_stencil_mask_is_never_even_offered(self):
        """`Page.get_images()` does not report image masks, and that is right.

        A stencil is a shape painted in the current fill colour rather than a
        picture, so it has no colour of its own to re-encode. Asserted because
        the guard in ``_skip_reason`` would otherwise look like the thing
        protecting these, when in fact pikepdf never hands one over.
        """
        pdf = pikepdf.Pdf.new()
        mask = Image.new("1", (600, 600), 0)
        stream = pikepdf.Stream(pdf, mask.tobytes())
        stream.Type, stream.Subtype = (pikepdf.Name.XObject,
                                       pikepdf.Name.Image)
        stream.Width, stream.Height = mask.width, mask.height
        stream.BitsPerComponent = 1
        stream.ImageMask = True
        stream = pdf.make_indirect(stream)
        self.placed(pdf, stream)
        raw = bytes(stream.read_raw_bytes())
        self.assertEqual(compress.images_of(pdf.pages[0]), {})
        self.assertEqual(compress.compress(pdf).outcomes, [])
        self.assertEqual(bytes(stream.read_raw_bytes()), raw)

    def test_a_stencil_is_refused_if_one_ever_reaches_the_encoder(self):
        """pikepdf 8's `Page.images` does hand them over."""
        pdf = pikepdf.Pdf.new()
        mask = Image.new("1", (64, 64), 0)
        stream = pikepdf.Stream(pdf, mask.tobytes())
        stream.Type, stream.Subtype = (pikepdf.Name.XObject,
                                       pikepdf.Name.Image)
        stream.Width, stream.Height = mask.width, mask.height
        stream.BitsPerComponent = 1
        stream.ImageMask = True
        self.assertEqual(
            compress._skip_reason(stream, pikepdf.PdfImage(stream)),
            compress.STENCIL)

    def test_jpeg_2000_needs_an_encoder_we_do_not_carry(self):
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        stream = embed(pdf, b"not really jpeg2000", image,
                       filter_=pikepdf.Name.JPXDecode)
        self.placed(pdf, stream)
        outcome = compress.compress(pdf).outcomes[0]
        self.assertEqual(outcome.reason, compress.UNSUPPORTED_FILTER)

    def test_an_indexed_palette_would_interpolate_into_nonsense(self):
        pdf = pikepdf.Pdf.new()
        palette = Image.new("P", (300, 300))
        palette.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0] + [0] * (768 - 9))
        lookup = pikepdf.String(bytes(palette.getpalette()[:9]))
        stream = embed(pdf, palette.tobytes(), palette,
                       colorspace=pikepdf.Array(
                           [pikepdf.Name.Indexed, pikepdf.Name.DeviceRGB,
                            2, lookup]))
        self.placed(pdf, stream)
        outcome = compress.compress(pdf).outcomes[0]
        self.assertEqual(outcome.reason, compress.INDEXED)

    def test_an_image_with_a_soft_mask_scales_with_it_or_not_at_all(self):
        pdf = pikepdf.Pdf.new()
        image = text_page(150)
        alpha = Image.new("L", (image.width, image.height), 128)
        mask = embed(pdf, flate(alpha), alpha,
                     colorspace=pikepdf.Name.DeviceGray)
        stream = embed(pdf, jpeg(image), image,
                       filter_=pikepdf.Name.DCTDecode, SMask=mask)
        page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        reasons = {o.reason for o in compress.compress(pdf).outcomes}
        self.assertIn(compress.SOFT_MASK, reasons)

    def test_ink_channels_are_not_colour(self):
        pdf = pikepdf.Pdf.new()
        image = Image.new("L", (300, 300), 200)
        tint = pikepdf.Stream(pdf, b"{ }")
        tint.FunctionType = 4
        tint.Domain = [0, 1]
        tint.Range = [0, 1, 0, 1, 0, 1, 0, 1]
        stream = embed(pdf, flate(image), image,
                       colorspace=pikepdf.Array([
                           pikepdf.Name.Separation, pikepdf.Name("/Spot"),
                           pikepdf.Name.DeviceCMYK, pdf.make_indirect(tint)]))
        self.placed(pdf, stream)
        outcome = compress.compress(pdf).outcomes[0]
        self.assertEqual(outcome.reason, compress.INK_CHANNELS)

    def test_a_skipped_image_is_still_reported(self):
        """The report is half the feature: silence reads as "broken"."""
        pdf = pikepdf.Pdf.new()
        image = text_page(72)
        stream = embed(pdf, b"junk", image, filter_=pikepdf.Name.JPXDecode)
        self.placed(pdf, stream)
        result = compress.compress(pdf)
        self.assertEqual(result.images, 1)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.saved, 0)


class TestSharedImages(unittest.TestCase):
    def test_an_image_on_eight_pages_is_re_encoded_once(self):
        """Eight visits, one object: doing it per page costs 23/255 of loss."""
        pdf = pikepdf.Pdf.new()
        image = text_page(300)
        stream = embed(pdf, jpeg(image), image, filter_=pikepdf.Name.DCTDecode)
        for _ in range(8):
            page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        result = compress.compress(pdf, compress.Settings(ppi=150))
        self.assertEqual(result.images, 1)
        self.assertEqual(result.outcomes[0].action, compress.DOWNSAMPLED)

    def test_only_the_named_pages_are_touched(self):
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf, pages=3)
        raw = bytes(streams[2].read_raw_bytes())
        result = compress.compress(pdf, compress.Settings(ppi=150),
                                   pages=[0, 1])
        self.assertEqual(result.images, 2)
        self.assertEqual(bytes(streams[2].read_raw_bytes()), raw)


class TestColour(unittest.TestCase):
    def test_greyscale_conversion_says_so_in_the_colour_space(self):
        pdf = pikepdf.Pdf.new()
        streams = full_page_scan(pdf)
        compress.compress(pdf, compress.Settings(ppi=150, greyscale=True))
        self.assertEqual(str(streams[0].ColorSpace), "/DeviceGray")
        self.assertEqual(
            pikepdf.PdfImage(streams[0]).as_pil_image().mode, "L")

    def test_an_icc_profile_is_kept_rather_than_flattened(self):
        """The samples are still RGB, so the space still describes them."""
        pdf = pikepdf.Pdf.new()
        image = text_page(300)
        profile = pikepdf.Stream(pdf, b"\0" * 128)
        profile.N = 3
        space = pikepdf.Array([pikepdf.Name.ICCBased, pdf.make_indirect(profile)])
        stream = embed(pdf, jpeg(image), image,
                       filter_=pikepdf.Name.DCTDecode, colorspace=space)
        page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        compress.compress(pdf, compress.Settings(ppi=150))
        self.assertEqual(str(stream.ColorSpace[0]), "/ICCBased")

    def test_a_stale_decode_array_is_removed(self):
        """It inverts the *old* samples; left behind it shows a negative."""
        pdf = pikepdf.Pdf.new()
        image = text_page(300)
        stream = embed(pdf, jpeg(image), image,
                       filter_=pikepdf.Name.DCTDecode,
                       Decode=[1, 0, 1, 0, 1, 0])
        page_with(pdf, [(stream, 0, 0, LETTER[0], LETTER[1])])
        compress.compress(pdf, compress.Settings(ppi=150))
        self.assertNotIn("/Decode", stream)


class TestThePresets(unittest.TestCase):
    def test_each_preset_names_a_destination(self):
        self.assertEqual(set(compress.PRESETS),
                         {compress.SCREEN, compress.BALANCED, compress.PRINT})

    def test_print_keeps_the_resolution_and_only_re_encodes(self):
        self.assertIsNone(compress.PRESETS[compress.PRINT].ppi)
        self.assertEqual(compress.PRESETS[compress.PRINT].quality, 90)

    def test_they_get_progressively_smaller(self):
        pdf = pikepdf.Pdf.new()
        sizes = {}
        for name in (compress.PRINT, compress.BALANCED, compress.SCREEN):
            with pikepdf.Pdf.new() as one:
                full_page_scan(one, pages=2)
                compress.compress(one, compress.PRESETS[name])
                sizes[name] = saved_size(one)
        pdf.close()
        self.assertLess(sizes[compress.SCREEN], sizes[compress.BALANCED])
        self.assertLess(sizes[compress.BALANCED], sizes[compress.PRINT])


class TestTheResultAddsUp(unittest.TestCase):
    def test_totals_are_the_sum_of_the_parts(self):
        pdf = pikepdf.Pdf.new()
        full_page_scan(pdf, pages=3)
        result = compress.compress(pdf, compress.Settings(ppi=150))
        self.assertEqual(result.before,
                         sum(o.before for o in result.outcomes))
        self.assertEqual(result.saved, result.before - result.after)
        self.assertTrue(0 < result.fraction < 1)

    def test_nothing_to_do_is_not_a_division_by_zero(self):
        pdf = pikepdf.Pdf.new()
        page_with(pdf, [])
        result = compress.compress(pdf)
        self.assertEqual(result.images, 0)
        self.assertEqual(result.fraction, 0.0)


class TestWhereTheResultLands(QtDocumentTestCase):
    """D25: a new temporary document, with the pages moved to it.

    The test that matters here is the undo one. It fails against the obvious
    implementation -- rewriting the images inside the file the page already
    points at -- because a snapshot holds page references and no pixels, so
    Undo would restore order and rotation over degraded images.
    """

    def setUp(self):
        super().setUp()
        self.scan = temp_path("scan.pdf")
        with pikepdf.Pdf.new() as pdf:
            full_page_scan(pdf, pages=3)
            pdf.save(self.scan)
        self.model.set_pages(self.docs.add_file(self.scan))
        self.pages = self.model.pages

    def image_bytes(self, copyname, number=1):
        with pikepdf.open(copyname) as pdf:
            page = pdf.pages[number - 1]
            obj = next(iter(compress.images_of(page).values()))
            return bytes(obj.read_raw_bytes())

    def balanced(self, pages=None):
        return compress.apply(pages if pages is not None else self.pages,
                              self.docs, compress.PRESETS[compress.BALANCED])

    def test_the_pages_move_to_a_document_that_did_not_exist_before(self):
        was = len(self.docs.docs)
        before = {page.copyname for page in self.pages}
        result = self.balanced()
        self.assertEqual(len(self.docs.docs), was + 1)
        self.assertEqual(result.changed, 3)
        now = {page.copyname for page in self.pages}
        self.assertEqual(len(now), 1)
        self.assertFalse(now & before)
        self.assertTrue(os.path.exists(next(iter(now))))
        self.assertEqual({page.nfile for page in self.pages},
                         {len(self.docs.docs)})

    def test_the_new_document_is_smaller_and_still_opens(self):
        old = self.pages[0].copyname
        self.balanced()
        new = self.pages[0].copyname
        self.assertLess(os.path.getsize(new), os.path.getsize(old) * 0.6)
        with pikepdf.open(new) as pdf:
            self.assertEqual(len(pdf.pages), 3)

    def test_undo_restores_the_pixels(self):
        """The whole reason for D25, and it fails against an in-place rewrite."""
        original = self.image_bytes(self.pages[0].copyname)
        self.model.undo.commit("Compress")
        self.balanced()
        self.assertNotEqual(self.image_bytes(self.pages[0].copyname), original)

        self.model.undo.undo()

        self.assertEqual(self.image_bytes(self.model.pages[0].copyname),
                         original)

    def test_the_file_undo_needs_is_still_on_disk(self):
        """Nothing may delete the original while a snapshot names it."""
        old = self.pages[0].copyname
        self.balanced()
        self.assertTrue(os.path.exists(old))
        self.assertNotEqual(old, self.pages[0].copyname)

    def test_redo_puts_the_compressed_pages_back(self):
        self.model.undo.commit("Compress")
        self.balanced()
        compressed = self.pages[0].copyname
        self.model.undo.undo()
        self.model.undo.redo()
        self.assertEqual(self.model.pages[0].copyname, compressed)

    def test_only_the_pages_given_are_moved(self):
        """Page indices are preserved, so a partial selection needs no remap."""
        old = self.pages[0].copyname
        self.balanced(self.pages[:1])
        self.assertNotEqual(self.pages[0].copyname, old)
        self.assertEqual(self.pages[1].copyname, old)
        self.assertEqual(self.pages[2].copyname, old)
        self.assertEqual(self.pages[0].npage, 1)
        with pikepdf.open(self.pages[0].copyname) as pdf:
            self.assertEqual(len(pdf.pages), 3)

    def test_the_pages_left_behind_keep_their_own_images(self):
        untouched = self.image_bytes(self.pages[1].copyname, 2)
        self.balanced(self.pages[:1])
        self.assertEqual(self.image_bytes(self.pages[1].copyname, 2),
                         untouched)

    def test_a_document_with_nothing_to_compress_gains_no_file(self):
        """The two-page vector document loaded by the base class."""
        was = len(self.docs.docs)
        vector = self.docs.add_file(TEST_PDF)
        result = compress.apply(vector, self.docs,
                                compress.PRESETS[compress.BALANCED])
        self.assertEqual(result.images, 0)
        self.assertEqual(len(self.docs.docs), was)

    def test_a_layer_from_the_same_file_moves_with_its_page(self):
        """A layer left behind would paint the original over the new page."""
        page = self.pages[0]
        page.layerpages.append(self.docs.make_layerpage(
            page.copyname, 2, 0, 1.0, OVERLAY, Sides(), Sides()))
        old = page.copyname
        self.balanced(self.pages)
        self.assertNotEqual(page.copyname, old)
        self.assertEqual(page.layerpages[0].copyname, page.copyname)
        self.assertEqual(page.layerpages[0].nfile, page.nfile)
        self.assertEqual(page.layerpages[0].npage, 2)

    def test_a_layer_from_elsewhere_is_left_where_it_is(self):
        page = self.pages[0]
        elsewhere = self.docs.docs[0].copyname      # the vector document
        page.layerpages.append(self.docs.make_layerpage(
            elsewhere, 1, 0, 1.0, OVERLAY, Sides(), Sides()))
        self.balanced(self.pages)
        self.assertEqual(page.layerpages[0].copyname, elsewhere)

    def test_read_mode_still_takes_the_shortcut(self):
        """A whole document compressed is still a 1:1 view of one file."""
        self.balanced()
        found = self.docs.source_if_unmodified(self.pages)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], self.pages[0].copyname)

    def test_a_partial_compress_sends_read_mode_the_long_way_round(self):
        """Two documents now, so the export path takes over, as after any edit."""
        self.balanced(self.pages[:1])
        self.assertIsNone(self.docs.source_if_unmodified(self.pages))

    def test_progress_is_told_which_half_of_the_work_is_running(self):
        """Both halves report: measuring the images is the slow one on a book."""
        seen = []
        compress.apply(self.pages, self.docs,
                       compress.PRESETS[compress.BALANCED],
                       progress=lambda phase, done, total:
                           seen.append((phase, done, total)))
        scanning = [row for row in seen if row[0] == compress.SCANNING]
        encoding = [row for row in seen if row[0] == compress.ENCODING]
        # Three pages to measure, then the three images they hold to encode.
        self.assertEqual(scanning, [(compress.SCANNING, n, 3) for n in range(3)])
        self.assertEqual(encoding, [(compress.ENCODING, n, 3) for n in range(3)])

    def test_a_scan_that_is_stopped_stops_before_any_encoding(self):
        seen = []

        def watch(phase, done, total):
            seen.append(phase)
            return phase != compress.SCANNING or done < 1

        result = compress.apply(self.pages, self.docs,
                                compress.PRESETS[compress.BALANCED],
                                progress=watch)
        self.assertTrue(result.stopped)
        self.assertNotIn(compress.ENCODING, seen)
        self.assertEqual(result.images, 0)

    def test_cancelling_leaves_the_document_alone(self):
        """Half a document compressed is not a state to leave somebody in."""
        was = len(self.docs.docs)
        before = [page.copyname for page in self.pages]
        original = self.image_bytes(self.pages[0].copyname)

        result = compress.apply(self.pages, self.docs,
                                compress.PRESETS[compress.BALANCED],
                                progress=lambda phase, done, total:
                                    phase != compress.ENCODING or done < 1)

        self.assertTrue(result.stopped)
        self.assertEqual(len(self.docs.docs), was)
        self.assertEqual([page.copyname for page in self.pages], before)
        self.assertEqual(self.image_bytes(self.pages[0].copyname), original)


if __name__ == "__main__":
    unittest.main()
