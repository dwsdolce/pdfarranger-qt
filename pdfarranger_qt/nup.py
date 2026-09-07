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

"""Pages per sheet: several pages tiled onto one, in reading order.

The same machinery as booklet imposition, pointed at a grid instead of a pair.
``booklet.generate`` is exactly the two-up case with the sides swapped for
folding; this is the general one, and neither knows about the other because the
folding rule is the whole of the difference::

     1 2 3 4        .---------.
     5 6 7 8  --->  | 1  |  2 |   2x2, one sheet per four pages
                    |----+----|
                    | 3  |  4 |
                    '---------'

The sheet is the size of the first page by default, and its orientation is
chosen to waste the least: two portrait pages side by side on a portrait sheet
come out a quarter of the size they need to be, and turning the sheet on its
side is what everybody means by "2 pages per sheet". `AUTO` picks whichever way
round scales the pages larger, which for a 1x2 grid of portrait pages is
landscape and for a 2x2 grid is the original orientation.
"""

import math
from typing import List, Optional, Tuple

from .core import OVERLAY, Dims, DocumentSet, Page
from .i18n import gettext_ as _
from .layers import entry_from_page, layer_stacks_from_entries, paste_as_layer

#: Sheet orientations. AUTO means "whichever fits the pages larger".
AUTO, PORTRAIT, LANDSCAPE = "auto", "portrait", "landscape"

#: The layouts worth offering as one click, as (columns, rows). Ordered the way
#: a print dialog orders them.
PRESETS = [
    (2, 1, lambda: _("2 pages per sheet")),
    (2, 2, lambda: _("4 pages per sheet")),
    (3, 2, lambda: _("6 pages per sheet")),
    (4, 2, lambda: _("8 pages per sheet")),
    (3, 3, lambda: _("9 pages per sheet")),
    (4, 4, lambda: _("16 pages per sheet")),
]


def can_generate(pages: List[Page]) -> bool:
    """Tiling needs at least one page, all the same size.

    The same rule as booklet imposition, and for the same reason: the cells are
    equal, so pages of different sizes would be scaled by different amounts and
    the sheet would not line up.
    """
    if not pages:
        return False
    first = pages[0].size_in_points()
    return all(p.size_in_points() == first for p in pages)


def sheet_size(page_size, columns: int, rows: int,
               orientation: str = AUTO) -> Dims:
    """The sheet a grid of ``page_size`` pages should be laid out on."""
    width, height = float(page_size[0]), float(page_size[1])
    portrait = Dims(min(width, height), max(width, height))
    landscape = Dims(portrait[1], portrait[0])
    if orientation == PORTRAIT:
        return portrait
    if orientation == LANDSCAPE:
        return landscape
    # AUTO: keep whichever way round lets the pages come out bigger. Ties go to
    # the orientation the pages already have, so a 2x2 grid does not turn the
    # document sideways for nothing.
    upright = Dims(width, height)
    turned = Dims(height, width)
    if _fit(upright, page_size, columns, rows) >= _fit(turned, page_size, columns, rows):
        return upright
    return turned


def _fit(sheet, page_size, columns: int, rows: int) -> float:
    """How large a page can be drawn in one cell of this sheet, as a scale."""
    cell_w = float(sheet[0]) / columns
    cell_h = float(sheet[1]) / rows
    return min(cell_w / float(page_size[0]), cell_h / float(page_size[1]))


def generate(pages: List[Page], columns: int, rows: int, docs: DocumentSet,
             orientation: str = AUTO, margin: float = 0.0,
             size: Optional[Dims] = None) -> List[Page]:
    """Tile ``pages`` ``columns`` x ``rows`` to a sheet, in reading order.

    ``margin`` is a fraction of the cell left empty around each page, so 0.05
    keeps the tiles from touching. The last sheet is short rather than padded
    with blanks: unlike a booklet, nothing has to fold.
    """
    if columns < 1 or rows < 1:
        raise ValueError("a grid needs at least one column and one row")
    per_sheet = columns * rows
    source = pages[0].size_in_points()
    target = Dims(*size) if size else sheet_size(source, columns, rows, orientation)

    n_sheets = math.ceil(len(pages) / per_sheet)
    blank_name, nfile = docs.get_blank_doc(target, n_sheets)
    scale = _fit(target, source, columns, rows) * (1.0 - margin)

    entries = [entry_from_page(p) for p in pages]
    sheets = []
    for index in range(n_sheets):
        sheet = Page(nfile, index + 1, blank_name, size_orig=target,
                     description=f"{columns}x{rows}\nsheet {index + 1}")
        group = entries[index * per_sheet:(index + 1) * per_sheet]
        for cell, entry in enumerate(group):
            stacks = layer_stacks_from_entries([entry], OVERLAY, docs)
            offset = cell_offset(target, source, columns, rows,
                                 cell % columns, cell // columns, scale)
            paste_as_layer([sheet], stacks, OVERLAY, offset, docs, rescale=scale)
        sheets.append(sheet)
    return sheets


def cell_offset(sheet, page_size, columns: int, rows: int,
                column: int, row: int, scale: float) -> Tuple[float, float]:
    """Where to put one tile, in the fractions ``paste_as_layer`` wants.

    Those fractions are of the *slack* -- the difference between the sheet and
    the scaled page -- not of the sheet, so 0 is flush left and 1 is flush
    right whatever the sizes are. That makes this a conversion rather than a
    calculation: work out where the tile's left edge belongs in points, then
    express it as a fraction of the room there is to move it.

    When there is no slack, every fraction means the same place, and 0 is as
    good an answer as any.
    """
    def axis(sheet_len, page_len, count, index):
        sheet_len, page_len = float(sheet_len), float(page_len)
        drawn = page_len * scale
        cell = sheet_len / count
        want = index * cell + (cell - drawn) / 2
        slack = sheet_len - drawn
        return 0.0 if slack <= 0 else want / slack

    return (axis(sheet[0], page_size[0], columns, column),
            axis(sheet[1], page_size[1], rows, row))
