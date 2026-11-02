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

"""Where a text mark's quadrilaterals come from.

The rules in `textlayer` were settled by measuring Acrobat's own highlights,
and that measurement cannot live here: the documents it was taken from are
validation material, not fixtures. So the page below is built to put each
rule on its own -- two sizes of type on one line, a stretch of empty page
mid-line, and a trailing space at the end of a line -- and the assertions
state what the rule *is* rather than repeating a number read off a corpus.

The one thing a built page cannot show is the whole reason the module exists,
because a generated fixture has the same font throughout: that the box a mark
covers comes from the font's ascent and descent rather than from the ink. So
that is tested directly, against the ink-tight box PDFium will also hand out.
"""

import unittest

import pikepdf
from support import temp_path

from pdfarranger_qt.textlayer import TextLayer

#: Where each line of the fixture sits, in page coordinates. Written down
#: because every expectation below is relative to one of them.
TOP_LINE = 330
GAP_LINE = 300
TAIL_LINE = 270
SIZED_LINE = 240


def a_page_of_cases(path):
    """One page holding a case for each rule, and nothing else.

    `/F1` is Helvetica at 14 point throughout except on the last line, which
    changes to 24 half way along so that a size change can be told apart from
    a line change.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(500, 400))
    page = pdf.pages[0]
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
        Encoding=pikepdf.Name.WinAnsiEncoding))
    content = "\n".join((
        # An ordinary line, for the cases that need a plain one.
        f"BT /F1 14 Tf 40 {TOP_LINE} Td (Hamburgefonstiv quick brown) Tj ET",
        # Two runs with 200 points of empty page between them: not spaces,
        # which have boxes of their own, but nothing at all.
        f"BT /F1 14 Tf 40 {GAP_LINE} Td (left side) Tj ET",
        f"BT /F1 14 Tf 300 {GAP_LINE} Td (right side) Tj ET",
        # A line ending in a space, which a quad must stop short of.
        f"BT /F1 14 Tf 40 {TAIL_LINE} Td (ends with a space ) Tj ET",
        # One line, two sizes.
        f"BT /F1 14 Tf 40 {SIZED_LINE} Td (small) Tj ET",
        f"BT /F1 24 Tf 100 {SIZED_LINE} Td (BIG) Tj ET",
    ))
    page.Contents = pdf.make_stream(content.encode())
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.save(path)
    pdf.close()
    return path


class LayerCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = a_page_of_cases(temp_path("textlayer-cases.pdf"))
        with open(cls.path, "rb") as handle:
            cls.data = handle.read()

    def setUp(self):
        self.layer = TextLayer()
        self.layer.set_document(self.data)

    def tearDown(self):
        self.layer.close()

    def across(self, line, left=0.0, right=500.0):
        """The quads a drag along ``line`` from ``left`` to ``right`` makes."""
        return self.layer.quads(0, (left, line + 4), (right, line + 4))

    def on_line(self, line):
        """Every character box sitting on ``line``."""
        return [box for box in self.layer.boxes(0)
                if box[1] <= line + 4 <= box[3]]


class TestTheBoxIsTheFontsAndNotTheInks(LayerCase):
    """The whole reason for a second PDFium.

    Qt gives the ink-tight box, and a mark built from it is shorter than the
    line and a different height for every run -- taller where a descender
    happens to fall, shorter where none does. The loose box is the font's
    ascent to its descent, so it is the same for every character in a run
    whatever letters are in it.
    """

    def ink_on(self, line):
        """The ink-tight boxes of the characters sitting on ``line``.

        Found through the loose boxes rather than by their own geometry: a
        glyph with no descender does not reach the bottom of its line, which
        is the very thing being measured, so a band drawn round the ink would
        decide what counts as the line by the answer.
        """
        wanted = {round(box[0], 3) for box in self.on_line(line)}
        page = self.layer._page.get_textpage()
        try:
            return [page.get_charbox(n) for n in range(page.count_chars())
                    if round(page.get_charbox(n, loose=True)[0], 3) in wanted]
        finally:
            page.close()

    def test_a_quad_is_taller_than_the_ink_under_it(self):
        quads = self.across(TOP_LINE)
        self.assertEqual(len(quads), 1)
        tallest = max(top - bottom for _l, bottom, _r, top
                      in self.ink_on(TOP_LINE))
        self.assertGreater(quads[0][3] - quads[0][1], tallest,
                           "the quad is no taller than the tallest glyph on "
                           "the line, so it is being built from the ink")

    def test_the_ink_is_ragged_where_the_quad_is_not(self):
        """The defect in one assertion. Every loose box on a line is the same
        height whatever letters are in it; the ink under them is not, and a
        band built from the ink steps up and down along the line."""
        loose = {round(box[3] - box[1], 3) for box in self.on_line(TOP_LINE)}
        ink = {round(top - bottom, 3)
               for _l, bottom, _r, top in self.ink_on(TOP_LINE)}
        self.assertEqual(len(loose), 1, loose)
        self.assertGreater(len(ink), 1, ink)


class TestWhereAQuadEnds(LayerCase):

    def test_one_line_of_one_size_is_one_quad(self):
        self.assertEqual(len(self.across(TOP_LINE)), 1)

    def test_empty_page_mid_line_ends_a_quad(self):
        """Not spaces -- nothing at all. Acrobat breaks a highlight where the
        page is blank and runs straight through the spaces between words."""
        quads = self.across(GAP_LINE)
        self.assertEqual(len(quads), 2)
        left, right = sorted(quads)
        self.assertLess(left[2], right[0], "the quads touch, so neither ended")

    def test_a_change_of_size_ends_a_quad(self):
        quads = self.across(SIZED_LINE)
        self.assertEqual(len(quads), 2)
        small, big = sorted(quads)
        self.assertGreater(big[3] - big[1], small[3] - small[1],
                           "both quads are the same height, so the size "
                           "change was not noticed")

    def test_a_quad_stops_at_the_last_glyph_and_not_the_last_character(self):
        """A trailing space has a box like any other character, and a quad
        that takes it in runs past the words into the margin."""
        quads = self.across(TAIL_LINE)
        self.assertEqual(len(quads), 1)
        spaces = [box for box in self.on_line(TAIL_LINE) if box[4]]
        self.assertTrue(spaces, "the fixture has no space to leave out")
        self.assertLessEqual(quads[0][2], max(box[0] for box in spaces),
                             "the quad reaches into the trailing space")

    def test_two_lines_are_two_quads_with_the_gap_left_clear(self):
        quads = self.layer.quads(0, (40, TOP_LINE + 4), (400, GAP_LINE + 4))
        self.assertGreaterEqual(len(quads), 2)
        upper, lower = max(quads, key=lambda q: q[3]), min(quads,
                                                           key=lambda q: q[1])
        self.assertGreater(upper[1], lower[3],
                           "a quad spans the gap between the lines")


class TestWhatTheDragIsGiven(LayerCase):

    def test_a_point_off_the_text_takes_the_nearest_line(self):
        """Nobody drags onto a glyph. Pressing in the margin beside a line
        means that line, as it does in every other reader."""
        quads = self.layer.quads(0, (5, TOP_LINE + 4), (495, TOP_LINE + 4))
        self.assertEqual(len(quads), 1)
        self.assertAlmostEqual(quads[0][3],
                               max(b[3] for b in self.on_line(TOP_LINE)),
                               places=3)

    def test_a_page_with_no_text_marks_nothing(self):
        blank = pikepdf.new()
        blank.add_blank_page(page_size=(200, 200))
        path = temp_path("textlayer-blank.pdf")
        blank.save(path)
        blank.close()
        with open(path, "rb") as handle:
            layer = TextLayer()
            layer.set_document(handle.read())
        try:
            self.assertEqual(layer.boxes(0), [])
            self.assertEqual(layer.quads(0, (10, 10), (190, 190)), [])
        finally:
            layer.close()

    def test_a_page_that_is_not_there_marks_nothing(self):
        self.assertEqual(self.layer.boxes(9), [])
        self.assertEqual(self.layer.quads(9, (10, 10), (100, 100)), [])

    def test_holding_no_document_marks_nothing(self):
        self.layer.set_document(None)
        self.assertEqual(self.layer.boxes(0), [])
        self.assertEqual(self.layer.quads(0, (10, 10), (100, 100)), [])

    def test_only_one_page_is_held_at_a_time(self):
        """A thousand-page book costs one page's glyphs, not the book's."""
        self.layer.boxes(0)
        self.assertEqual(self.layer._index, 0)
        self.layer.boxes(9)
        self.assertEqual(self.layer._index, -1, "the page was not released")


if __name__ == "__main__":
    unittest.main()
