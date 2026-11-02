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

"""Where the glyphs are, at the height a mark wants them.

Qt's `QPdfSelection.bounds()` gives one polygon per run, tight to the ink: a
line with no descender in it comes out shorter than the line above, and a word
in a larger font makes its own run a different height again. A highlight built
from those is a ragged row of short boxes, and that is what this reader drew
until it was measured against Acrobat.

PDFium has the box we actually want -- `FPDFText_GetLooseCharBox`, built from
the font's ascent and descent rather than from the glyph -- and **Acrobat uses
it**. Against the forty-two highlight quads Acrobat itself wrote into
`Markup Highlight.pdf`, the union of the loose boxes under each quad matched
its `/QuadPoints` exactly, to the hundredth of a point, on every one: the
13.34 and 12.99 point lines of body text, the 15.77 point heading, and a
26.69 point quad over a single large character. The ink-tight boxes over the
same characters ran 2 to 6 points short and varied run by run.

So the height of a mark is not a factor applied to anything. A line may hold
several sizes of type, and Acrobat gives each its own quad -- which is why
there is no single number to tune here, and why this module exists at all.

**Why a second PDFium.** Qt PDF *is* PDFium, but it is linked statically with
hidden visibility: of the 232 symbols its framework exports, not one is an
`FPDF_*` function. There is nothing to call. The only alternative was to parse
the content stream ourselves -- text matrices, `/FontDescriptor` ascents,
Type3 and CID fonts, and the standard 14 fonts that carry no descriptor at all
-- to recompute what PDFium has already computed correctly.

**The bytes are the ones already on screen.** The canvas is handed the
document it shows as bytes, for its render thread, and this reads that same
buffer: PDFium takes a pointer and does not copy it, so a second document
handle costs its parse structures and nothing else. It also settles the
coordinates -- those bytes are the export, with every crop and resize already
in them, so a box from here is in the same space as a `/Rect` read out of the
same file, which is the space `forms.to_displayed` expects.

**One page at a time.** A text layer is built for the page being marked and
thrown away when the gesture moves to another, so reading a thousand-page
book costs one page's glyphs rather than the book's.
"""

from typing import List, Optional, Sequence, Tuple

import pypdfium2

#: How much of the shorter of two characters' heights has to be shared before
#: they count as the same line of type. A fraction rather than a distance
#: because the test has to hold for 8 point footnotes and 26 point drop caps
#: alike. Generous enough that a superscript stays on its line.
SAME_LINE = 0.5

#: How much two neighbours' heights may differ and still share a quad, in
#: points. Acrobat gives a larger word on a line its own quad, which is why
#: no single height can be computed for a line.
SIZE = 0.5

#: These three rules were not guessed. Every adjacent pair of glyphs under
#: Acrobat's own highlights in `Markup Highlight.pdf` was sorted into the
#: pairs it kept in one quad and the pairs it broke between -- 1722 against
#: 13 -- and the two groups separate cleanly on all three measures::
#:
#:     merged:  gap <= 5.97    height change <= 0.35    top moved <= 0.22
#:     split:   gap -240..-539 (seven line returns)
#:              gap    6.80    height change  1.60
#:              gap   20.42    height change 12.13
#:              gap  116..286  height change  0.00
#:
#: So a quad ends where the line does, where the size changes, or where the
#: page is empty for longer than the type is tall. The last of those is a
#: proportion rather than a measurement because a gap that reads as a gap in
#: 9 point type is nothing in 26 point type -- and it is the same test in
#: both directions, since a line return is a very large negative gap.

#: How much more a point's vertical distance from a character counts than its
#: horizontal one, when nothing is under the pointer. Dragging into the gutter
#: between two columns should take the line *beside* the pointer, not the line
#: above it in the column over; without this a two-column page jumps between
#: columns as the pointer crosses the gap.
TOWARDS_THE_LINE = 4.0


class TextLayer:
    """One page's characters, each with the box a mark would cover.

    Boxes are ``(left, bottom, right, top)`` in the page's own space, the
    frame `/QuadPoints` is written in.
    """

    def __init__(self):
        self._data: Optional[bytes] = None
        self._document = None
        self._index = -1
        self._page = None
        self._text = None
        self._boxes: List[Tuple[float, float, float, float]] = []

    # -- the document ------------------------------------------------------

    def set_document(self, data: Optional[bytes]) -> None:
        """Read ``data``, the document being shown, or None to hold nothing.

        A reference to the buffer is kept because PDFium does not take one:
        it is given a pointer, and freeing the bytes underneath it is a
        crash rather than an error.
        """
        self.close()
        self._data = data
        if not data:
            return
        try:
            self._document = pypdfium2.PdfDocument(data)
        except Exception:       # noqa: BLE001 - an unreadable document shows
            self._document = None   # without markup rather than not at all

    def close(self) -> None:
        self._release_page()
        if self._document is not None:
            try:
                self._document.close()
            except Exception:   # noqa: BLE001 - teardown must not raise
                pass
        self._document = None
        self._data = None

    def _release_page(self) -> None:
        for held in (self._text, self._page):
            if held is not None:
                try:
                    held.close()
                except Exception:   # noqa: BLE001 - teardown must not raise
                    pass
        self._text = None
        self._page = None
        self._index = -1
        self._boxes = []

    # -- one page ----------------------------------------------------------

    def boxes(self, index: int) -> Sequence[Tuple[float, float, float, float, bool]]:
        """Every character on ``index`` as ``(left, bottom, right, top, blank)``.

        In reading order, which is the file's order and not necessarily the
        page's: a three-column page stores its columns in whatever sequence
        the generator wrote them.

        Characters with no area are dropped. A line break is a character to
        PDFium, with a degenerate box wherever the line ended, and one left in
        would make two lines look contiguous.

        A space keeps its box and is flagged instead of dropped, because it
        has two jobs that pull opposite ways: it must not stretch a quad past
        the last glyph, and it must not look like empty page either, or every
        word would start a quad of its own.
        """
        if index == self._index:
            return self._boxes
        self._release_page()
        if self._document is None or not 0 <= index < len(self._document):
            return []
        try:
            self._page = self._document[index]
            self._text = self._page.get_textpage()
            count = self._text.count_chars()
            text = self._text.get_text_range(0, count) if count else ""
            boxes = []
            for n in range(count):
                left, bottom, right, top = self._text.get_charbox(n, loose=True)
                if right > left and top > bottom:
                    letter = text[n] if n < len(text) else " "
                    boxes.append((left, bottom, right, top, letter.isspace()))
        except Exception:       # noqa: BLE001 - PDFium can be unhappy
            self._release_page()
            return []
        self._index = index
        self._boxes = boxes
        return boxes

    def nearest(self, index: int, x: float, y: float) -> Optional[int]:
        """The character under ``(x, y)``, or the closest one to it.

        Closest rather than nothing, because a drag does not oblige: pressing
        in the margin beside a line means that line, the same way it does in
        every other reader.

        **The line the pointer is level with wins outright**, and is not
        merely preferred. Scoring both directions together looks reasonable
        and is wrong wherever a line is short: dragging off the end of a
        28-character line, the far end of it is hundreds of points away
        horizontally while the line *below* is twenty points away vertically,
        so no weighting that still lets a pointer reach the next line keeps
        the drag on the line it is level with. A reader extends to the end of
        the line you are on; it does not wrap to a nearer one underneath.
        """
        boxes = self.boxes(index)
        if not boxes:
            return None
        # Not `FPDFText_GetCharIndexAtPos`: it indexes every character and
        # this list holds only the ones with a box, so its answer would have
        # to be mapped back anyway -- and a point inside a box scores zero
        # here, so containment is the same search as proximity.
        level = [n for n, box in enumerate(boxes) if box[1] <= y <= box[3]]
        best, distance = None, None
        for n in level or range(len(boxes)):
            left, bottom, right, top, _blank = boxes[n]
            dx = max(left - x, 0.0, x - right)
            if level:
                span = dx * dx
            else:
                dy = max(bottom - y, 0.0, y - top)
                span = dx * dx + TOWARDS_THE_LINE * dy * dy
            if distance is None or span < distance:
                best, distance = n, span
        return best

    # -- what a mark covers ------------------------------------------------

    def quads(self, index: int, start, end) -> List[Tuple[float, ...]]:
        """The quadrilaterals covering the text between two page-space points.

        One per run of characters sharing a line and a size, which is how
        Acrobat writes them: a paragraph of body text with one word in a
        larger face is three quads, not one, and the larger word's is taller.

        Empty when the page holds no text, or when neither end of the drag
        can be put anywhere near a character.
        """
        boxes = self.boxes(index)
        if not boxes:
            return []
        first = self.nearest(index, start[0], start[1])
        last = self.nearest(index, end[0], end[1])
        if first is None or last is None:
            return []
        if first > last:
            first, last = last, first
        # Spaces are dropped rather than walked through. A quad ends where the
        # words do -- Acrobat's stop at the last glyph, leaving the trailing
        # space of a wrapped line uncoloured -- and the gap test has to see
        # the empty page a run of spaces sits in, which it cannot if the
        # spaces fill it.
        glyphs = [boxes[n] for n in range(first, last + 1) if not boxes[n][4]]
        quads: List[Tuple[float, ...]] = []
        run: List[Tuple[float, float, float, float, bool]] = []
        for char in glyphs:
            if run and self._breaks(run[-1], char):
                quads.append(self._quad(run))
                run = []
            run.append(char)
        if run:
            quads.append(self._quad(run))
        return quads

    @staticmethod
    def _breaks(previous, char) -> bool:
        """Whether ``char`` starts a new quad rather than continuing one."""
        _pleft, pbottom, pright, ptop, _ps = previous
        left, bottom, right, top, _blank = char
        height, pheight = top - bottom, ptop - pbottom
        shortest = min(height, pheight)
        if shortest <= 0:
            return True
        if min(top, ptop) - max(bottom, pbottom) < SAME_LINE * shortest:
            return True                     # the next line down
        if abs(height - pheight) > SIZE:
            return True                     # a different size beside it
        return abs(left - pright) > max(height, pheight)   # empty page

    @staticmethod
    def _quad(run) -> Tuple[float, ...]:
        return (min(c[0] for c in run), min(c[1] for c in run),
                max(c[2] for c in run), max(c[3] for c in run))
