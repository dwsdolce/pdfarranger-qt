# Copyright (C) 2008-2025 pdfarranger contributors
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

"""Booklet imposition.

Imposition arranges linear pages onto folded sheets so a stapled booklet reads
in order; unimposition is the inverse, for a booklet someone scanned as spreads::

     1                                    1
     2          .-------.                 2
     3   ---->  | 4 | 1 |   ---->         3
     4  impose  '-------'  unimpose       4
                | 2 | 3 |
                '-------'

Both directions live here. Imposition builds on ``layers.paste_as_layer``: each
sheet is a blank double-width page with two source pages composited onto it,
flush left and flush right.
"""

from typing import List, Optional, Tuple

from .core import OVERLAY, Dims, DocumentSet, Page
from .layers import entry_from_page, layer_stacks_from_entries, paste_as_layer

#: Tile layout for a two-up spread: two equal columns, one row.
_TWO_COLUMNS = [[1, 50], [2, 50]]
_ONE_ROW = [[1, 100]]


def crops_from_tiles(linear_tiles) -> List[Tuple[float, float]]:
    """Convert tile percentages into ``(start, end)`` fractions.

    Ported from ``splitter._crops``. Tiles summing to more than 100% overlap,
    which is how the split dialog offers overlapping tiles; the overlap is
    distributed evenly between them.
    """
    num_splits = len(linear_tiles)
    crops = [(0, 0.01 * linear_tiles[0][1])] * num_splits
    crop_sum = 0.01 * linear_tiles[0][1]
    for i in range(1, num_splits):
        size = 0.01 * linear_tiles[i][1]
        crop_sum += size
        crops[i] = (crops[i - 1][1], crops[i - 1][1] + size)

    crops = [t for t in crops if t[0] < t[1]]  # drop zero-sized tiles

    overlap = crop_sum - 1.0  # nonnegative
    if overlap == 0.0:
        return crops

    # 35,35,35 => [0,35],[32.5,67.5],[65,100]; overlap = 5
    # 60,60    => [0,60],[40,100];            overlap = 20
    overlap_per_tile = overlap / (num_splits - 1)
    size = 0.01 * linear_tiles[0][1]  # overlap is only defined for equal tiles
    crops[0] = (0, size)
    for i in range(1, num_splits - 1):
        start = crops[i - 1][1] - overlap_per_tile
        crops[i] = (start, start + size)
    crops[-1] = (1.0 - size, 1.0)
    return crops


def can_generate(pages: List[Page]) -> bool:
    """Imposing needs at least one page, all the same size."""
    if not pages:
        return False
    first = pages[0].size_in_points()
    return all(p.size_in_points() == first for p in pages)


def generate(pages: List[Page], docs: DocumentSet) -> List[Page]:
    """Impose pages onto double-width sheets ready for folding.

    Padded to a multiple of four with blanks, then sheet *i* takes the page
    counted from the end and the page counted from the start, swapping sides
    each sheet so fronts and backs line up when printed double-sided.
    """
    n_src = len(pages)
    padding = 0 if n_src % 4 == 0 else 4 - n_src % 4
    total = n_src + padding
    n_sheets = total // 2

    width, height = pages[0].size_in_points()
    sheet_size = Dims(width * 2, height)
    blank_name, nfile = docs.get_blank_doc(sheet_size, n_sheets)

    entries = [entry_from_page(p) for p in pages]
    sheets = []
    for i in range(n_sheets):
        sheet = Page(nfile, i + 1, blank_name, size_orig=sheet_size,
                     description=f"booklet\nsheet {i + 1}")
        # Sheet 0 is [last | first], sheet 1 is [second | second-to-last], and
        # so on inward; the sides alternate so the folded stack reads in order.
        even = i % 2 == 0
        left_id = (-i - 1) if even else i
        right_id = i if even else (-i - 1)
        if left_id < 0:
            left_id += total
        if right_id < 0:
            right_id += total
        for source, offset in ((left_id, (0, 0.5)), (right_id, (1, 0.5))):
            if source < n_src:  # the padding slots stay blank
                stacks = layer_stacks_from_entries([entries[source]], OVERLAY, docs)
                paste_as_layer([sheet], stacks, OVERLAY, offset, docs)
        sheets.append(sheet)
    return sheets


def can_split(pages: List[Page]) -> bool:
    """Unimposing needs at least one sheet, all the same size."""
    if not pages:
        return False
    first = pages[0].size_in_points()
    return all(p.size_in_points() == first for p in pages)


def split(pages: List[Page]) -> List[Page]:
    """Unimpose two-up sheets back into single pages in reading order.

    ``pages`` must be a contiguous run of equally-sized sheets. Returns twice as
    many pages; the inputs are cropped in place to their left halves, so pass
    duplicates if the originals matter.
    """
    leftcrops = crops_from_tiles(_TWO_COLUMNS)
    topcrops = crops_from_tiles(_ONE_ROW)

    halves = len(pages) * 2
    result: List[Page] = [None] * halves  # type: ignore[list-item]
    for count, page in enumerate(pages):
        # split() crops the page to its left half and returns the right half
        splits = page.split(leftcrops, topcrops)
        assert len(splits) == 1, "a two-column split must yield exactly one extra page"
        right = splits[0]
        # Sheet 0 holds [last, first], sheet 1 holds [second, second-to-last],
        # and so on inward -- so the halves alternate which end they belong to.
        if count % 2 == 0:
            result[halves - count - 1] = page
            result[count] = right
        else:
            result[count] = page
            result[halves - count - 1] = right
    return result
