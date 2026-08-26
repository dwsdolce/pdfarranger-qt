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

"""Compositing pages onto other pages as overlays and underlays.

This is the keystone of the dialog phase: Merge Pages, Paste As
Overlay/Underlay, booklet imposition, and two of the three Page Size modes are
all this one operation with different offsets.

The arithmetic is ported from the GTK application essentially unchanged. It is
fiddly because a pasted page may itself already carry layers, which have to be
re-cropped and re-offset into the destination page's coordinate space -- and
because ``offset`` is expressed as fractions of the *destination* page, so every
nested layer needs rescaling by the ratio between the two.

Nothing here touches page content: layers become overlay/underlay entries that
the exporter turns into `add_overlay`/`add_underlay` calls.
"""

from typing import List, Optional, Sequence, Tuple

from .core import (
    OVERLAY,
    Dims,
    DocumentSet,
    LayerPage,
    Page,
    Sides,
    hide_layer_margins,
)


def _apply_hide_to_layer_stack(layerpages: List[LayerPage], hide: Sides,
                               docs: DocumentSet):
    """Bake a pasted page's own hidden margins into its layer stack.

    Same trick as ``DocumentSet.apply_hide``: a full-size blank sheet goes under
    the stack, and everything above is cropped and inset so nothing shows in the
    hidden margin.
    """
    first = layerpages[0]
    if all(hide[i] <= first.crop[i] for i in range(4)):
        return
    hide_layer_margins(first, layerpages[1:], hide)
    blank_name, _nfile = docs.get_blank_doc(first.size)
    blank = docs.make_layerpage(blank_name, 1, 0, first.scale, OVERLAY,
                                first.crop, Sides())
    first.crop = Sides(*hide)
    first.offset = Sides(*hide)
    layerpages.insert(0, blank)


def entry_from_page(page: Page) -> tuple:
    """Describe a Page in the same shape ``clipboard.parse`` produces.

    Compositing works off those entries, so anything that wants to paste a page
    that is already in the document goes through here rather than a clipboard
    round trip.
    """
    return (
        page.copyname, page.npage, page.description, page.angle, page.scale,
        tuple(page.crop), tuple(page.hide),
        [(lp.copyname, lp.npage, lp.angle, lp.scale, lp.laypos,
          tuple(lp.crop), tuple(lp.offset)) for lp in page.layerpages],
    )


def layer_stacks_from_entries(entries, laypos: str, docs: DocumentSet
                              ) -> Optional[List[List[LayerPage]]]:
    """Turn clipboard page entries into layer stacks, one per pasted page.

    Each stack is ``[the page itself, then its own layers]``, all as LayerPage
    objects in the pasted page's own coordinate space.
    """
    stacks = []
    for filename, npage, _description, angle, scale, crop, hide, layerdata in entries:
        described = [[filename, npage, angle, scale, laypos, crop, Sides()]] + list(layerdata)
        stack = []
        for lfile, lnpage, langle, lscale, lpos, lcrop, loffset in described:
            stack.append(docs.make_layerpage(lfile, lnpage, langle, lscale, lpos,
                                             Sides(*lcrop), Sides(*loffset)))
        _apply_hide_to_layer_stack(stack, Sides(*hide), docs)
        stacks.append(stack)
    return stacks or None


def paste_as_layer(dest_pages: Sequence[Page], stacks: List[List[LayerPage]],
                   laypos: str, offset_xy: Tuple[float, float],
                   docs: DocumentSet, rescale: float = 1.0):
    """Composite ``stacks`` onto ``dest_pages`` in place.

    ``offset_xy`` is a fraction of the *size difference* between destination and
    pasted page, so (0, 0.5) is flush left and vertically centred, (0.5, 0.5) is
    dead centre, and (1, 0.5) is flush right. That is what makes booklet
    imposition just two calls with (0, 0.5) and (1, 0.5).

    Destination pages are walked in reverse and the stacks cycle, matching the
    GTK version: pasting two pages onto six alternates them.
    """
    off_x, off_y = offset_xy
    for num, dpage in enumerate(reversed(list(dest_pages))):
        stack = stacks[num % len(stacks)]

        # The pasted page itself.
        lp0 = stack[0].duplicate()
        lp0.scale *= rescale
        dwidth = dpage.size[0] * dpage.scale
        dheight = dpage.size[1] * dpage.scale
        scalex = (dpage.width_in_points() - lp0.width_in_points()) / dwidth
        scaley = (dpage.height_in_points() - lp0.height_in_points()) / dheight
        left = dpage.crop.left + off_x * scalex
        top = dpage.crop.top + off_y * scaley
        lp0.offset = Sides(
            left=left,
            right=1 - left - lp0.width_in_points() / dwidth,
            top=top,
            bottom=1 - top - lp0.height_in_points() / dheight,
        )
        if docs.docs[lp0.nfile - 1].blank_size is None:
            # A blank sheet contributes nothing but its geometry, so it is used
            # to position the stack and then dropped.
            dpage.layerpages.append(lp0)

        # Then the layers the pasted page was already carrying.
        nfirst = len(dpage.layerpages) - 1
        scalex = (lp0.size[0] * lp0.scale) / (dpage.size[0] * dpage.scale)
        scaley = (lp0.size[1] * lp0.scale) / (dpage.size[1] * dpage.scale)
        sm1 = Sides(scalex, scalex, scaley, scaley)
        for layer in stack[1:]:
            lp = layer.duplicate()
            lp.scale *= rescale
            scalex = (lp0.size[0] * lp0.scale) / (lp.size[0] * lp.scale)
            scaley = (lp0.size[1] * lp0.scale) / (lp.size[1] * lp.scale)
            sm2 = Sides(scalex, scalex, scaley, scaley)
            # Crop the part of the layer that fell outside its old parent.
            outside = Sides(*(max(0, lp0.crop[i] - lp.offset[i]) for i in range(4)))
            lp.crop += outside * sm2
            lp.offset += outside
            # Re-express the offset against the new destination page.
            lp.offset = lp0.offset + (lp.offset - lp0.crop) * sm1
            if lp.crop.left + lp.crop.right > 1 or lp.crop.top + lp.crop.bottom > 1:
                continue  # entirely outside the visible area
            if lp.laypos != laypos:
                lp.laypos = laypos
                dpage.layerpages.insert(nfirst, lp)
            else:
                dpage.layerpages.append(lp)


def center_on_blank_pages(pages: List[Page], size, docs: DocumentSet) -> List[Page]:
    """Return new pages of ``size`` with each input centred on top as a layer.

    This is "add margins": the page keeps its own dimensions and gains
    whitespace around it, rather than being stretched. ``size`` is in points.
    """
    target = Dims(*size)
    blank_name, nfile = docs.get_blank_doc(target)
    out = []
    for page in pages:
        if page.size_in_points() == target:
            out.append(page)
            continue
        stacks = layer_stacks_from_entries([entry_from_page(page)], OVERLAY, docs)
        sheet = Page(nfile, 1, blank_name, size_orig=target,
                     description=page.description)
        paste_as_layer([sheet], stacks, OVERLAY, (0.5, 0.5), docs)
        out.append(sheet)
    return out
