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

"""Write the in-memory page list back out as PDF.

This is the GTK-free half of the original ``exporter.py``.  The pikepdf logic is
kept verbatim wherever possible -- it is the part of PDF Arranger that is
hardest to get right and easiest to break, so it is deliberately not "improved"
during the port.  What was dropped is the GTK plumbing: the warning dialogs, the
print operation, and the multiprocessing wrapper.
"""

import collections
import dataclasses
import io
import locale
import os
import traceback
import warnings
from typing import Any, Dict, List, Optional, Tuple

import packaging.version
import pikepdf

from . import forms, markup, metadata, structure
from .core import Page, Sides
from .i18n import gettext_ as _

#: export_doc_job() uses the pikepdf Job interface, added in pikepdf 8.
HAS_PIKEPDF8 = packaging.version.parse(pikepdf.__version__) >= packaging.version.Version("8.0")

# pikepdf.Page.add_overlay()/add_underlay() cannot place a page exactly
# if for example LC_NUMERIC=fi_FI
try:
    locale.setlocale(locale.LC_NUMERIC, "C")
except locale.Error:
    pass

if os.name == "nt":
    # Work around https://github.com/pdfarranger/pdfarranger/issues/1110
    locale.setlocale(locale.LC_COLLATE, "C")


def _normalize_rectangle(rect):
    """
    PDF Specification 1.7, 7.9.5, although rectangles are conventionally
    specified by their lower-left and upper-right corners, it is acceptable to
    specify any two diagonally opposite corners. Applications that process PDF
    should be prepared to normalize such rectangles in situations where
    specific corners are required.
    """
    rect = [float(x) for x in rect]
    if rect[0] > rect[2]:
        rect[0], rect[2] = rect[2], rect[0]
    if rect[1] > rect[3]:
        rect[1], rect[3] = rect[3], rect[1]
    return rect


def _intersect_rectangle(rect1, rect2):
    return [
        max(rect1[0], rect2[0]),
        max(rect1[1], rect2[1]),
        min(rect1[2], rect2[2]),
        min(rect1[3], rect2[3]),
    ]


def _mediabox(page, crop=Sides()):
    """Return the media box for a given page."""
    # PDF files which do not have mediabox default to Portrait Letter / ANSI A
    cmb = page.MediaBox if "/MediaBox" in page else [0, 0, 612, 792]
    cmb = _normalize_rectangle(cmb)
    if "/CropBox" in page:
        # PDF specification 14.11.2.1: a CropBox is effectively reduced to its
        # intersection with the media box.
        cmb = _intersect_rectangle(cmb, _normalize_rectangle(page.CropBox))

    if crop == Sides():
        return cmb
    angle = page.Rotate if "/Rotate" in page else 0
    rotate_times = int(round(((angle) % 360) / 90) % 4)
    crop_init = crop
    if rotate_times != 0:
        perm = [0, 2, 1, 3]
        for _ in range(rotate_times):
            perm.append(perm.pop(0))
        perm.insert(1, perm.pop(2))
        crop = Sides(*(crop_init[perm[side]] for side in range(4)))
    x1, y1, x2, y2 = [float(x) for x in cmb]
    x1_new = x1 + (x2 - x1) * crop.left
    x2_new = x2 - (x2 - x1) * crop.right
    y1_new = y1 + (y2 - y1) * crop.bottom
    y2_new = y2 - (y2 - y1) * crop.top
    return [x1_new, y1_new, x2_new, y2_new]


@dataclasses.dataclass
class SaveOptions:
    """Document-wide choices that only apply when writing a real file.

    Gathered into one object rather than four more keyword arguments: `export`
    already takes nine, and these four belong together -- they are all things
    the *document* is, rather than things the pages are.

    None of them mean anything for an in-memory export (a preview, a search
    index, the reader's snapshot), which is why `to_file` still gates them.
    """

    #: Rewrite for byte-serving, so a viewer can show page one before the whole
    #: file has arrived. PDF24 calls this "web optimize".
    linearize: bool = False
    #: Write no author, title, producer or XMP at all.
    strip_metadata: bool = False
    #: Recompress streams and pack objects. Modest on its own: what people
    #: usually mean by "compress" is image downsampling, which this is not.
    compress: bool = False
    #: How a viewer should open the document: `viewer.Preferences`, or None to
    #: say nothing and let the viewer decide.
    viewer: Optional[Any] = None

    def save_kwargs(self) -> Dict[str, Any]:
        """The pikepdf `save` arguments these options imply.

        Object streams are not among the options: they are written always.
        They pack the small objects -- page dictionaries, annotations, the
        outline -- into compressed streams, which makes a file both smaller
        and faster to read, and neither of those is something to ask a user
        about. Measured on a 1,590-page book: 155.3 MB without them against
        151.0 MB with, and reading every page's size 1,955 ms against 1,411.
        The source document it was made from has 1,928 of them.

        They were tied to the Compress checkbox, so a document that had its
        images compressed and was then saved with that box unticked lost the
        packing on the way out -- which is how the measurement above came to
        be taken in the first place.
        """
        kwargs: Dict[str, Any] = {
            "object_stream_mode": pikepdf.ObjectStreamMode.generate,
        }
        if self.linearize:
            kwargs["linearize"] = True
        if self.compress:
            kwargs["compress_streams"] = True
            kwargs["recompress_flate"] = True
        return kwargs


#: Used when a caller says nothing, so every path can read `options.` safely.
DEFAULT_SAVE_OPTIONS = SaveOptions()


def _strip_metadata(pdf_output):
    """Leave no author, title, producer or XMP behind.

    pikepdf writes a Producer of its own unless told not to, and the fresh
    output document inherits nothing else, so this is mostly about *not*
    calling `_set_meta` -- plus removing what pikepdf would otherwise add.
    """
    with pdf_output.open_metadata(set_pikepdf_as_editor=False) as meta:
        for key in list(meta.keys()):
            del meta[key]
    if pikepdf.Name.Metadata in pdf_output.Root:
        del pdf_output.Root[pikepdf.Name.Metadata]
    if pikepdf.Name.Info in pdf_output.trailer:
        del pdf_output.trailer[pikepdf.Name.Info]


def _set_meta(mdata, pdf_input, pdf_output):
    ppae = metadata.PRODUCER not in mdata
    with pdf_output.open_metadata(set_pikepdf_as_editor=ppae) as outmeta:
        if len(pdf_input) > 0:
            metadata.load_from_docinfo(outmeta, pdf_input[0])
        for k, v in mdata.items():
            outmeta[k] = v


#: Annotation entries holding coordinates in the page's own space, each a
#: flat array of numbers. `/InkList` is handled apart because it nests.
_ANNOT_GEOMETRY = ("/Rect", "/QuadPoints", "/L", "/Vertices", "/CL", "/RD")

#: Entries holding a length rather than a position -- border widths and the
#: dash patterns beside them. A border drawn at its old width on a page half
#: the size is twice as heavy as it was.
_ANNOT_WIDTHS = ("/Border",)


def _scale_annotation(annot, factor):
    """Multiply every page-space coordinate in one annotation.

    `/Rect` alone is not enough, and the ways it is not are not exotic. The
    coordinates held *beside* the rectangle -- `/QuadPoints` for a highlight,
    `/InkList` for a drawing, `/L` for a line, `/RD` for a square's inset --
    are in the same space, and scaling the rectangle while leaving them puts
    the box in the right place around a shape still drawn at the old size.

    Measured, not guessed: pypdf 6.21.4 scaling the same page by half scales
    every `/Rect` and leaves every `/QuadPoints`, `/InkList`, `/L` and `/RD`
    exactly where it was.

    `/AP` streams need nothing. A viewer maps an appearance's `/BBox` through
    its `/Matrix` and fits the result to `/Rect`, which is the mechanism that
    lets an annotation be resized at all, so a scaled rectangle rescales the
    appearance with it.
    """
    for name in _ANNOT_GEOMETRY:
        value = annot.get(pikepdf.Name(name))
        if value is not None:
            annot[pikepdf.Name(name)] = pikepdf.Array(
                [factor * float(v) for v in value])
    inklist = annot.get(pikepdf.Name.InkList)
    if inklist is not None:
        annot[pikepdf.Name.InkList] = pikepdf.Array(
            [pikepdf.Array([factor * float(v) for v in stroke])
             for stroke in inklist])
    for name in _ANNOT_WIDTHS:
        value = annot.get(pikepdf.Name(name))
        if value is not None:
            # `/Border` is [hr vr w] and may carry a dash array after it.
            annot[pikepdf.Name(name)] = pikepdf.Array(
                [pikepdf.Array([factor * float(v) for v in item])
                 if isinstance(item, pikepdf.Array)
                 else factor * float(item) for item in value])
    border = annot.get(pikepdf.Name.BS)
    if border is not None and pikepdf.Name.W in border:
        border[pikepdf.Name.W] = factor * float(border[pikepdf.Name.W])


#: Page entries that survive a resize unchanged, because the resize does not
#: mean anything to them. `/UserUnit` needs more than copying and is handled
#: below. `/Tabs` became meaningful again when the annotations it orders came
#: back.
_PAGE_KEPT = ("/Group", "/Tabs", "/AA", "/B", "/Metadata")

#: Boxes in the space being multiplied, so they are scaled rather than copied.
#: `/CropBox` and `/TrimBox` are not here: `_apply_geom_transform` deletes
#: those on purpose, having folded the crop into the MediaBox already.
_PAGE_SCALED_BOXES = ("/BleedBox", "/ArtBox")

#: Deliberately *not* carried. `/PieceInfo` is the private cache of whichever
#: application wrote the file, describing content this function has just
#: rewritten, so keeping it hands the next tool a description of a page that
#: no longer exists.
#:
#: `/StructParents` is left behind for a harder reason: it indexes the
#: structure tree's parent tree for marked content in the page's *own* content
#: stream, and that content now lives inside a form XObject, which needs its
#: own key and a matching tree entry. Copying the number across would point
#: the tag tree at content that is not there, which is worse than dropping it.
#: Tagged structure does not survive a resize, and saying so is honest where
#: a copied key would not be.
_PAGE_DROPPED = ("/PieceInfo", "/StructParents")


def _scale(doc, page, factor):
    """Scale a page."""
    if factor == 1:
        return page
    rotate = 0
    if "/Rotate" in page:
        # The rotate attribute is set on the resulting page, so it must be
        # unset on the input page first.
        rotate = page.Rotate
        page.Rotate = 0
    page_id = len(doc.pages)
    newmediabox = [factor * float(x) for x in page.MediaBox]
    content = "q {} 0 0 {} 0 0 cm /p{} Do Q".format(factor, factor, page_id)
    xobject = pikepdf.Page(page).as_form_xobject()
    # `as_form_xobject` adds a `/Matrix` for `/UserUnit` and for nothing else,
    # baking the page's unit scale into the content. Carrying `/UserUnit` on
    # as well would then apply it twice: measured on a 600x400 page at
    # UserUnit 2.5 scaled by half, a box at x=100..300 drew at x=125..375 on a
    # 300pt page instead of x=50..150. Dropping `/UserUnit` instead is not the
    # answer either, since it exists to describe pages past the 14400pt the
    # format allows, and flattening one can put it over that limit. So the
    # conversion is undone and the unit kept.
    if "/UserUnit" in page and pikepdf.Name.Matrix in xobject:
        del xobject[pikepdf.Name.Matrix]
    # Carried across by hand, because this builds a *new* page and anything
    # not named here is left on the old one. Annotations and the widgets of a
    # filled form live beside the content rather than in it, so a resized page
    # used to come back with the comments and the form gone -- measured as 8
    # annotations in and 0 out. The objects themselves are reused rather than
    # copied, which is what keeps the AcroForm's `/Fields` pointing at the
    # same widgets.
    annots = page.get(pikepdf.Name.Annots) if "/Annots" in page else None
    new_page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=newmediabox,
        Contents=doc.make_stream(content.encode()),
        Resources={"/XObject": {"/p{}".format(page_id): xobject}},
        Rotate=rotate,
    )
    for name in _PAGE_KEPT:
        if name in page:
            new_page[pikepdf.Name(name)] = page[pikepdf.Name(name)]
    for name in _PAGE_SCALED_BOXES:
        if name in page:
            new_page[pikepdf.Name(name)] = pikepdf.Array(
                [factor * float(v) for v in page[pikepdf.Name(name)]])
    if "/UserUnit" in page:
        new_page[pikepdf.Name.UserUnit] = page[pikepdf.Name.UserUnit]
    # Needed for pikepdf <= 2.6.0 and again for 8.8.
    # See https://github.com/pikepdf/pikepdf/issues/174
    indirect = doc.make_indirect(new_page)
    if annots is not None:
        for annot in annots:
            _scale_annotation(annot, factor)
            # `/P` names the page an annotation is on. Left alone it points at
            # the page this one replaced, which is no longer in the document.
            if pikepdf.Name.P in annot:
                annot[pikepdf.Name.P] = indirect
        indirect[pikepdf.Name.Annots] = annots
    return indirect


def _update_angle(model_page, source_page, output_page):
    angle = model_page.angle
    angle0 = source_page.Rotate if "/Rotate" in source_page else 0
    if angle != 0:
        new_angle = angle + angle0
        if new_angle >= 360:
            new_angle -= 360
        output_page.Rotate = new_angle


def _apply_geom_transform(pdf_output, new_page, row):
    _update_angle(row, new_page, new_page)
    new_page.MediaBox = _mediabox(new_page, row.crop)
    # add_overlay() & add_underlay() will use TrimBox or CropBox if they exist
    if "/TrimBox" in new_page:
        del new_page.TrimBox
    if "/CropBox" in new_page:
        del new_page.CropBox
    return pikepdf.Page(_scale(pdf_output, new_page, row.scale))


#: Children per node in the page tree we write. Ten is what well-made
#: documents use -- the 1,590-page handbook this was measured on came with
#: 358 intermediate nodes five deep, widest /Kids of ten.
PAGE_TREE_FANOUT = 10


def balance_page_tree(pdfdoc, fanout: int = PAGE_TREE_FANOUT):
    """Give the document a tree of pages rather than one flat list.

    qpdf writes `/Pages` with every page as a direct child, which is legal and
    pessimal: a reader finding page N walks the array, so reading every page
    costs O(n²). Measured with QtPdf on a 1,590-page book, flat against the
    balanced tree it arrived with:

    ======================  ==================  =============
    pages                   balanced (depth 5)  flat
    ======================  ==================  =============
    0-200                   0.18 ms each        0.55 ms each
    700-900                 0.34 ms each        1.00 ms each
    1390-1590               0.53 ms each        4.21 ms each
    ======================  ==================  =============

    That rising cost is the walk. It made a document we had just written
    slower to open than the one it came from -- in our own reader and in
    anything else that asks for pages by number.

    Built bottom-up, so the intermediate nodes define none of the inheritable
    attributes and `/Resources`, `/MediaBox` and `/Rotate` still resolve from
    wherever they were. Left alone when it cannot help.
    """
    try:
        leaves = [page.obj for page in pdfdoc.pages]
    except Exception:       # pragma: no cover - a document we cannot walk
        return
    if len(leaves) <= fanout:
        return

    level = leaves
    while len(level) > fanout:
        parents = []
        for start in range(0, len(level), fanout):
            group = level[start:start + fanout]
            node = pdfdoc.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Pages,
                Kids=pikepdf.Array(group),
                Count=sum(int(kid.Count) if "/Kids" in kid else 1
                          for kid in group)))
            for kid in group:
                kid.Parent = node
            parents.append(node)
        level = parents

    root = pdfdoc.Root.Pages
    root.Kids = pikepdf.Array(level)
    root.Count = len(leaves)
    for kid in level:
        kid.Parent = root


def _remove_unreferenced_resources(pdfdoc):
    try:
        pdfdoc.remove_unreferenced_resources()
    except RuntimeError:
        # Catches "operation for dictionary attempted on object of type null"
        # seen with old pikepdf. Blindly catching every RuntimeError is
        # dangerous, so print it rather than swallow it.
        print(traceback.format_exc())


def _record_trail(trail, source_page, index) -> None:
    """Note where this copy of a page landed. See `_copy_n_transform`.

    By *position*, not by object. `_apply_geom_transform` runs afterwards and
    replaces every page: recording the objects instead put the whole trail out
    of date before anything could read it, and the structure tree came out
    with no page in it at all.
    """
    pages, annots = trail
    pages[source_page.obj.objgen] = index
    for at, annot in enumerate(source_page.get(pikepdf.Name.Annots, [])):
        if annot.is_indirect:
            annots[annot.objgen] = (index, at)


def _append_page(current_page, copied_pages, pdf_output, row):
    """Add a page to the output pdf. A page that already exists is duplicated.

    Annotations are copied rather than referenced, or editing one copy of a
    duplicated page changed the other (upstream's issue 437). The copy is made
    two different ways, because two requirements pull against each other.

    *Different pages that share a field must go on sharing it.* A radio group
    puts one widget on each page and hangs both off one parent; copy them
    separately and the group becomes two groups, so selecting an option stops
    clearing the other. `copy_foreign` keeps a map per source document, so
    copying each annotation straight across gets this right for nothing: the
    parent is copied the first time it is reached and found again after.

    *A duplicated page must not share with its own copy*, which is 437 and the
    reason the detour through a temporary document exists -- it defeats that
    same map deliberately. So it is kept, for the second and later copies of a
    page only.
    """
    key = (row.nfile, row.npage)
    duplicate = key in copied_pages
    new_page = copied_pages.get(key)
    if new_page is None:
        new_page = current_page
    # let pdf_output adopt new_page
    pdf_output.pages.append(new_page)
    new_page = pdf_output.pages[-1]
    copied_pages[key] = new_page
    if pikepdf.Name.Annots not in current_page:
        return
    annots = current_page.Annots
    if not duplicate and all(a.is_indirect for a in annots):
        new_page.Annots = pikepdf.Array(
            [pdf_output.copy_foreign(a) for a in annots])
        return
    # A duplicate, or a page whose annotations are written inline and so
    # cannot be copied one at a time.
    pdf_temp = pikepdf.Pdf.new()
    pdf_temp.pages.append(current_page)
    indirect_annots = pdf_temp.make_indirect(pdf_temp.pages[0].Annots)
    new_page.Annots = pdf_output.copy_foreign(indirect_annots)


#: How deep a field tree is walked looking for the root. A widget is often its
#: own field, a kid of one, or a kid of a radio group; eight is far beyond any
#: real form and stops a /Parent cycle in a damaged file spinning for ever.
_FIELD_DEPTH = 8


def _root_field(annot):
    """The top-level field a widget belongs to, which may be the widget."""
    node, depth = annot, 0
    while pikepdf.Name.Parent in node and depth < _FIELD_DEPTH:
        node = node[pikepdf.Name.Parent]
        depth += 1
    return node


#: Keys that make an annotation part of a form. Taken off a signature widget
#: that is kept for its drawing, so that what remains is a picture and not a
#: field.
_FORM_KEYS = (pikepdf.Name.FT, pikepdf.Name.T, pikepdf.Name.V,
              pikepdf.Name.DV, pikepdf.Name.Ff, pikepdf.Name.AS,
              pikepdf.Name.Parent, pikepdf.Name.Lock, pikepdf.Name.SV)


def _strip_signatures(pdf_output) -> int:
    """Take the remains of a signature out of the output. Returns how many.

    Export builds a new document, so a signature in it can only ever be a
    corpse: the bytes its ``/ByteRange`` names are gone, the ``/Perms`` entry a
    viewer reads to find a certification does not survive the new root, and the
    ``/DSS`` holding the validation data does not either. What used to survive
    was the signature field itself, with 32,767 bytes of PKCS#7 and -- on a
    certified document -- a ``/Reference`` still declaring ``DocMDP P=1``, no
    changes permitted, over a file that was never the one it was computed from.
    A viewer opening that reports a broken signature, which is indistinguishable
    from tampering, and whether it happened at all depended on whether the page
    the widget sat on was in the selection.

    A *visible* signature keeps its drawing, as a ``/Stamp``. The appearance is
    page content the user can see and expects to still be there, and it makes
    no claim by itself -- it is the signature dictionary that asserts validity,
    and that is what goes. An invisible one, which is what both real samples
    are, has nothing to keep and the annotation goes with it.
    """
    stripped = 0
    for page in pdf_output.pages:
        annots = page.get(pikepdf.Name.Annots)
        if annots is None:
            continue
        kept = []
        for annot in annots:
            if (annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Widget
                    or _field_kind(annot) != pikepdf.Name.Sig):
                kept.append(annot)
                continue
            stripped += 1
            _blank_signature(annot)
            if _has_drawing(annot):
                annot[pikepdf.Name.Subtype] = pikepdf.Name.Stamp
                for key in _FORM_KEYS:
                    if key in annot:
                        del annot[key]
                kept.append(annot)
        if len(kept) != len(annots):
            page[pikepdf.Name.Annots] = pikepdf.Array(kept)
    return stripped


def _blank_signature(annot) -> None:
    """Empty the signature dictionary this widget points at.

    Dropping the reference is not enough. qpdf does not collect unreferenced
    objects, so the dictionary stays in the output -- unreachable, and so
    harmless to any viewer, but carrying the signer's certificate chain and
    several kilobytes of PKCS#7 into a document that has nothing to do with
    it. Measured on the certified sample: 6,453 bytes and a full chain up to
    the Adobe root, in a file whose signature had supposedly been taken out.

    Emptying it is safe because the output's objects are its own. An export
    leaves the source document it copied from untouched, which is checked.
    """
    node, depth = annot, 0
    while node is not None and depth < _FIELD_DEPTH:
        value = node.get(pikepdf.Name.V)
        if isinstance(value, pikepdf.Dictionary):
            for key in list(value.keys()):
                del value[key]
            return
        node = node.get(pikepdf.Name.Parent)
        depth += 1


def _field_kind(annot):
    """``/FT`` for a widget, which can sit anywhere above it."""
    node, depth = annot, 0
    while node is not None and depth < _FIELD_DEPTH:
        if pikepdf.Name.FT in node:
            return node[pikepdf.Name.FT]
        node = node.get(pikepdf.Name.Parent)
        depth += 1
    return None


def _has_drawing(annot) -> bool:
    """Whether this widget puts anything on the page.

    Both real samples answer no: an invisible signature is the normal shape
    for one applied by an e-signature service, and carries ``/Rect [0 0 0 0]``.
    """
    appearance = annot.get(pikepdf.Name.AP)
    if appearance is None or pikepdf.Name.N not in appearance:
        return False
    rect = [float(v) for v in annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
    return abs(rect[2] - rect[0]) > 0 and abs(rect[3] - rect[1]) > 0


def _surviving_fields(pdf_output):
    """Top-level fields of the widgets that landed in the output, in order.

    Read off the output rather than copied from the input because the output
    is a different set of pages: an export of a selection keeps only the
    widgets on the pages it kept, and /Fields naming the others would point at
    annotations that are not in the document.
    """
    seen, fields = set(), []
    for page in pdf_output.pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            if annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Widget:
                continue
            field = _root_field(annot)
            try:
                key = field.objgen
            except Exception:  # pragma: no cover - a direct field dictionary
                key = None
            if key is None or key == (0, 0):
                fields.append(field)       # cannot be identified, so not merged
                continue
            if key not in seen:
                seen.add(key)
                fields.append(field)
    return fields


def _restore_acroform(pdf_input, pdf_output):
    """Give the output back the form dictionary the page copy left behind.

    Export builds a new document and copies pages into it. Widget annotations
    travel with their page; /AcroForm does not, because it hangs off the
    document root -- so a filled form came out with all 23 of its answers still
    in the annotations and nothing interactive able to reach them. pikepdf says
    so as it happens: "86 form widget annotation(s) that are not reachable from
    /AcroForm; they may not display in Adobe Acrobat."

    The form-wide settings are carried from whichever inputs have them. /DR in
    particular is not optional: it holds the fonts an appearance stream names,
    and without it a viewer regenerating an appearance has nothing to draw with.
    """
    fields = _surviving_fields(pdf_output)
    if not fields:
        return                       # not a form; do not invent one
    acroform = pikepdf.Dictionary(Fields=pikepdf.Array(fields))
    resources = pikepdf.Dictionary()
    for pdf in pdf_input:
        # _open_inputs leaves a None for every source these pages do not
        # reference, which is most of them when exporting a selection.
        if pdf is None:
            continue
        source = pdf.Root.get(pikepdf.Name.AcroForm)
        if source is None:
            continue
        # Not /SigFlags. It says a signature exists and that the file should
        # be saved by appending, and neither is true of a document built from
        # scratch with the signatures taken out of it (D5).
        for key in (pikepdf.Name.DA, pikepdf.Name.Q,
                    pikepdf.Name.NeedAppearances):
            if key in source and key not in acroform:
                acroform[key] = source[key]
        for name, value in source.get(pikepdf.Name.DR, pikepdf.Dictionary()).items():
            # One level down, because /DR is a resource dictionary: its entries
            # are themselves dictionaries of named fonts and so on, and
            # replacing /Font wholesale would drop the first document's.
            if isinstance(value, pikepdf.Dictionary):
                into = resources.get(name)
                if into is None:
                    into = resources[name] = pikepdf.Dictionary()
                for key, entry in value.items():
                    if key not in into:
                        into[key] = pdf_output.copy_foreign(
                            pdf.make_indirect(entry))
            elif name not in resources:
                resources[name] = value
    if len(resources):
        acroform[pikepdf.Name.DR] = resources
    pdf_output.Root[pikepdf.Name.AcroForm] = pdf_output.make_indirect(acroform)
    _warn_about_shared_names(fields)


def _warn_about_shared_names(fields):
    """Two fields with one name are one field, which merging can create.

    A field's value is keyed by its fully qualified name, so two documents each
    carrying a "Name" field become a single field with two widgets once they
    are in the same document: type into one and the other changes with it.
    Acrobat renames on import. Detecting it and saying so is honest and cheap;
    renaming silently would be a different surprise.
    """
    counts = collections.Counter(
        str(field[pikepdf.Name.T]) for field in fields
        if pikepdf.Name.T in field)
    shared = sorted(name for name, n in counts.items() if n > 1)
    if shared:
        warnings.warn(
            _("Merged form fields share a name, so they will share a value: ")
            + ", ".join(shared[:5]) + ("…" if len(shared) > 5 else ""),
            stacklevel=2)


def _write_form_values(pdf_output, pages, form_values):
    """Put what has been filled in into the document being written.

    Page by page rather than document-wide, because a field name identifies a
    field only within the document it came from: an export can hold pages from
    several, and a "Name" field in each is two fields until they are merged.
    Output page *i* is ``pages[i]``, which knows its source, so each page gets
    its own document's values and no others.
    """
    if not form_values:
        return
    for index, row in enumerate(pages):
        if index >= len(pdf_output.pages):
            break
        wanted = form_values.for_document(row.nfile)
        if wanted:
            forms.apply_values([pdf_output.pages[index]], wanted,
                               pdf_output.Root.get(pikepdf.Name.AcroForm),
                               pdf_output)


def _write_annotations(pdf_output, pages, annotations) -> int:
    """Put the marks the user added onto the pages being written.

    Looked up by page uid, which is what makes this need no tidying up
    elsewhere: a mark whose page is not among the ones being written is simply
    not asked for. That covers a deleted page and an export of a selection
    with the same rule, and it is why nothing prunes `Annotations` when the
    page list shrinks.
    """
    if not annotations:
        return 0
    written = 0
    for index, row in enumerate(pages):
        if index >= len(pdf_output.pages):
            break
        marks = annotations.for_page(row.uid)
        if marks:
            written += markup.add_to_page(
                pdf_output, pdf_output.pages[index], marks)
    return written


def _copy_n_transform(pdf_input, pdf_output, pages, quit_flag=None,
                      trail=None):
    # All pages must be copied to pdf_output BEFORE applying geometrical
    # transformation. See https://github.com/pikepdf/pikepdf/issues/271
    copied_pages = {}
    mediaboxes = []
    # Copy pages from the input PDF files to the output PDF file
    for row in pages:
        if quit_flag is not None and quit_flag.is_set():
            return
        current_page = pdf_input[row.nfile - 1].pages[row.npage - 1]
        mediaboxes.append(_mediabox(current_page))
        _append_page(current_page, copied_pages, pdf_output, row)
        if trail is not None:
            # Which source object became which output object, recorded here
            # because this is the only place the two are side by side. The
            # structure tree needs it: an element names its page in /Pg and an
            # /OBJR names its annotation, and both have to be pointed at what
            # the export actually wrote. Annotations are copied in order by
            # `_append_page`, so they pair off by position.
            _record_trail(trail, current_page, len(pdf_output.pages) - 1)
        # Layer pages are temporarily added after the page they belong to
        for lprow in row.layerpages:
            layer_page = pdf_input[lprow.nfile - 1].pages[lprow.npage - 1]
            _append_page(layer_page, copied_pages, pdf_output, lprow)

    # Apply geometrical transformations in the output PDF file
    i = 0
    for row in pages:
        if quit_flag is not None and quit_flag.is_set():
            return
        pdf_output.pages[i] = _apply_geom_transform(pdf_output, pdf_output.pages[i], row)
        for lprow in row.layerpages:
            i += 1
            pdf_output.pages[i] = _apply_geom_transform(pdf_output, pdf_output.pages[i], lprow)
        i += 1

    # Add overlays and underlays
    for i, row in enumerate(pages):
        # The dest page coordinates and size before geometrical transformations
        dx1, dy1, dx2, dy2 = mediaboxes[i]
        dw, dh = dx2 - dx1, dy2 - dy1

        dpage = pdf_output.pages[i]
        dangle0 = dpage.Rotate if "/Rotate" in dpage else 0
        rotate_times = int(round(((dangle0) % 360) / 90) % 4)
        for lprow in row.layerpages:
            # Rotate the offsets so they are relative to dest page
            offset = lprow.offset.rotated(rotate_times)
            offs_left, offs_right, offs_top, offs_bottom = offset
            x1 = row.scale * (dx1 + dw * offs_left)
            y1 = row.scale * (dy1 + dh * offs_bottom)
            x2 = row.scale * (dx1 + dw * (1 - offs_right))
            y2 = row.scale * (dy1 + dh * (1 - offs_top))
            rect = pikepdf.Rectangle(x1, y1, x2, y2)

            layer_page = pdf_output.pages[i + 1]
            if lprow.laypos == "OVERLAY":
                pdf_output.pages[i].add_overlay(layer_page, rect)
            else:
                pdf_output.pages[i].add_underlay(layer_page, rect)
            # Remove the temporarily added page
            del pdf_output.pages[i + 1]


def get_max_pdf_version(pdf_list: List[pikepdf.Pdf]) -> str:
    """Return the highest pdf version used in pdf_list."""
    versions = [pdf.pdf_version for pdf in pdf_list if pdf is not None]
    return max(versions) if versions else "1.4"


def export_doc(pdf_input, pages, mdata, files_out, quit_flag=None,
               test_mode=False, output_password=None, with_outlines=False,
               options: "SaveOptions" = None, source_names=None, outline=None,
               prune_outline=False, form_values=None, annotations=None):
    """Same as export() but taking already-opened pikepdf.Pdf objects.

    ``outline`` is the document's own bookmark tree (D20). When given it is
    written as it stands, which is what makes a bookmark edit survive a save;
    without it the outline is rebuilt from the source files as it always was, so
    every caller that has no such tree behaves exactly as before.
    """
    pdf_output = pikepdf.Pdf.new()
    max_version = get_max_pdf_version([pdf_output, *pdf_input])
    trail = ({}, {})
    _copy_n_transform(pdf_input, pdf_output, pages, quit_flag, trail)
    if quit_flag is not None and quit_flag.is_set():
        return
    # Before the form is rebuilt, so that what is rebuilt cannot name a
    # signature field: a document assembled here is a new one, and the only
    # honest thing it can say about a signature is nothing (D5).
    _strip_signatures(pdf_output)
    # After the pages, because it is built from the widgets that actually
    # arrived rather than from the ones the inputs had.
    _restore_acroform(pdf_input, pdf_output)
    _write_form_values(pdf_output, pages, form_values)
    # After the form, because a mark is added to the page rather than to the
    # form, and the page's /Annots must already hold whatever travelled with it.
    _write_annotations(pdf_output, pages, annotations)
    # Last of all, because it indexes the annotations that actually arrived:
    # a signature taken out above must not leave an /OBJR naming it, and a
    # mark added above has no structure and should gain none.
    structure.carry(pdf_input, pdf_output, pages, *trail)

    # files_out entries are paths when saving and file-like objects when
    # rendering to memory (previews, printing). Metadata and encryption are only
    # meaningful for a real save.
    to_file = isinstance(files_out[0], str)
    # Outlines used to be gated the same way, on the grounds that the in-memory
    # callers -- white-border detection, image export, printing, search -- have
    # no use for them. Read mode does: its sidebar is the outline. It is opt-in
    # so those callers keep paying nothing for it. `rebuild_outlines` already
    # skips `None` entries in pdf_input, so the in-memory case is safe.
    password = None
    if (to_file or with_outlines) and len(files_out) == 1:
        # Imported here to avoid a circular import with exporter_outlines
        from . import exporter_outlines

        if outline is not None:
            exporter_outlines.write_outline(pdf_output, outline, pages,
                                            source_names, prune=prune_outline)
        else:
            exporter_outlines.rebuild_outlines(pdf_input, pdf_output, pages,
                                               source_names)
    # Always, and regardless of outlines: a saved file whose internal links
    # all point at nothing is broken however it was produced.
    from . import exporter_outlines as _links

    _links.remap_link_annotations(pdf_input, pdf_output, pages, source_names)

    options = options or DEFAULT_SAVE_OPTIONS
    if to_file:
        if not options.strip_metadata:
            mdata = metadata.merge_doc(mdata, pdf_input)
        password = output_password
        if options.viewer is not None:
            options.viewer.write(pdf_output)
    if password:
        encryption = pikepdf.Encryption(user=password, owner=password, R=6)
    else:
        encryption = False

    if len(files_out) > 1:
        for n, page in enumerate(pdf_output.pages):
            if quit_flag is not None and quit_flag.is_set():
                return
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            # works without make_indirect as already applied to this page
            outpdf.pages.append(page)
            _remove_unreferenced_resources(outpdf)
            if options.strip_metadata:
                _strip_metadata(outpdf)
            outpdf.save(files_out[n], min_version=max_version,
                        encryption=encryption, **options.save_kwargs())
        return

    if to_file:
        if options.strip_metadata:
            _strip_metadata(pdf_output)
        elif not test_mode:
            _set_meta(mdata, pdf_input, pdf_output)
        _remove_unreferenced_resources(pdf_output)
    # Before the write, and only for the single-file path: splitting gives one
    # page per file, where there is no tree to balance.
    balance_page_tree(pdf_output)
    if test_mode:
        pdf_output.save(
            files_out[0],
            qdf=True,
            static_id=True,
            compress_streams=False,
            stream_decode_level=pikepdf.StreamDecodeLevel.all,
            min_version=max_version,
            encryption=encryption,
        )
    else:
        pdf_output.save(files_out[0], min_version=max_version,
                        encryption=encryption, **options.save_kwargs())


def _open_inputs(files, pages) -> List[Optional[pikepdf.Pdf]]:
    """Open only the documents these pages actually reference."""
    needed = {p.nfile for p in pages}
    for page in pages:
        for lpage in page.layerpages:
            needed.add(lpage.nfile)
    pdf_input: List[Optional[pikepdf.Pdf]] = [None] * len(files)
    for nfile in needed:
        copyname, password = files[nfile - 1]
        pdf_input[nfile - 1] = pikepdf.open(copyname, password=password)
    return pdf_input


def get_in_memory_pdf(pages: List[Page], files: List[Tuple[str, str]],
                      outlines: bool = False,
                      source_names: Optional[List[str]] = None) -> bytes:
    """Render ``pages`` to a PDF in memory, with all their edits applied.

    Several features need to look at the *result* of the edits rather than the
    source: detecting white borders, exporting images, previewing a crop. This
    is the Qt replacement for upstream's ``get_in_memory_poppler_doc()``; pair
    it with ``open_pdf_bytes()`` to get a QPdfDocument.

    ``outlines`` rebuilds the bookmark tree as well. Off by default because
    remapping outlines costs real work and only read mode wants them.
    """
    pdf_input = _open_inputs(files, pages)
    buf = io.BytesIO()
    try:
        export_doc(pdf_input, pages, {}, [buf], None, with_outlines=outlines,
                   source_names=source_names)
    finally:
        for pdf in pdf_input:
            if pdf is not None:
                pdf.close()
    return buf.getvalue()


def _create_job(files: List[List[str]], pages: List[Page], files_out: List[str],
                quit_flag=None, test_mode: bool = False, output_password=None,
                options: "SaveOptions" = None):
    """Build the pikepdf Job that copies pages. Requires pikepdf >= 8.

    The Job interface copies pages and their annotations for us, so unlike
    ``_copy_n_transform`` there is no explicit append step; media boxes are
    left until the transformation stage.
    """
    json = dict(outputFile=files_out[0], pages=[], removeUnreferencedResources="yes")
    options = options or DEFAULT_SAVE_OPTIONS
    # qpdf's job JSON spells a bare flag as an empty string.
    if options.linearize and not test_mode:
        json["linearize"] = ""
    if options.compress and not test_mode:
        json["compressStreams"] = "y"
        json["objectStreams"] = "generate"
    if test_mode:
        json.update(qdf="", staticId="", compressStreams="n", decodeLevel="all")
    if len(files) > 0 and len(files[0][0]) > 0:
        json["inputFile"] = files[0][0]  # files[0] is treated as the main document
        if len(files[0][1]) > 0:
            json["password"] = files[0][1]
    else:
        json["inputFile"] = "."

    for page in pages:
        if quit_flag is not None and quit_flag.is_set():
            return None
        _add_json_entries(json, files, page)
        for lpage in page.layerpages:
            # Layer pages are temporarily added after the page they belong to
            _add_json_entries(json, files, lpage)
    if output_password:
        json["encrypt"] = {
            "userPassword": output_password,
            "ownerPassword": output_password,
            "256bit": {},
        }
    else:
        json["decrypt"] = ""
    return pikepdf.Job(json)


def _add_json_entries(json: Dict[str, Any], files: List[List[str]], page) -> None:
    """Create an entry for the job json "pages" list."""
    pages_entry = {"file": files[page.nfile - 1][0],  # copyname
                   "range": str(page.npage)}
    if len(files[page.nfile - 1][1]) > 0:
        pages_entry["password"] = files[page.nfile - 1][1]
    json["pages"].append(pages_entry)


def _apply_geom_transform_job(pdf_output: pikepdf.Pdf, new_page, page) -> None:
    new_page.rotate(page.angle, relative=True)
    new_page.MediaBox = _mediabox(new_page, page.crop)
    # add_overlay() & add_underlay() will use TrimBox or CropBox if they exist
    if "/TrimBox" in new_page:
        del new_page.TrimBox
    if "/CropBox" in new_page:
        del new_page.CropBox
    if page.scale != 1:
        pdf_output.pages.append(new_page)
        new_page.obj.emplace(_scale(pdf_output, pdf_output.pages[-1], page.scale))
        del pdf_output.pages[-1]


def _transform_job(pdf_output: pikepdf.Pdf, pages: List[Page], quit_flag=None) -> None:
    """Same as _copy_n_transform, except it does not copy. Requires pikepdf >= 8."""
    # Fix missing MediaBoxes
    for page in pdf_output.pages:
        if page.mediabox is None:
            page.mediabox = pikepdf.Array((0, 0, 612, 792))

    mediaboxes: List[pikepdf.Rectangle] = []
    i = 0
    for page in pages:
        if quit_flag is not None and quit_flag.is_set():
            return
        mediaboxes.append(pikepdf.Rectangle(pdf_output.pages[i].mediabox))
        _apply_geom_transform_job(pdf_output, pdf_output.pages[i], page)
        for lpage in page.layerpages:
            i += 1
            _apply_geom_transform_job(pdf_output, pdf_output.pages[i], lpage)
        i += 1

    # Add overlays and underlays
    for i, page in enumerate(pages):
        # The dest page coordinates and size before geometrical transformations
        mb = mediaboxes[i]
        # rotate() in _apply_geom_transform_job ensures /Rotate exists
        rotate_times = int(round((pdf_output.pages[i].Rotate % 360) / 90) % 4)
        for lpage in page.layerpages:
            # Rotate the offsets so they are relative to dest page
            offset = lpage.offset.rotated(rotate_times)
            offs_left, offs_right, offs_top, offs_bottom = offset
            x1 = page.scale * (mb.llx + mb.width * offs_left)
            y1 = page.scale * (mb.lly + mb.height * offs_bottom)
            x2 = page.scale * (mb.llx + mb.width * (1 - offs_right))
            y2 = page.scale * (mb.lly + mb.height * (1 - offs_top))
            rect = pikepdf.Rectangle(x1, y1, x2, y2)

            if lpage.laypos == "OVERLAY":
                pdf_output.pages[i].add_overlay(pdf_output.pages[i + 1], rect)
            else:
                pdf_output.pages[i].add_underlay(pdf_output.pages[i + 1], rect)
            # Remove the temporarily added page
            del pdf_output.pages[i + 1]


def _ensure_trailer_size(pdf_output: pikepdf.Pdf) -> None:
    """Put /Size back in a trailer that arrived without one.

    This path preserves the first document, and it preserves its faults too: a
    file whose trailer is missing /Size -- which qpdf reconstructs on the way in
    and warns about -- produces an output trailer missing it as well. With a
    plain cross-reference table that stays merely untidy, because every reader
    reconstructs. With a cross-reference *stream*, which compressing forces,
    there is nothing left to reconstruct from and the file will not open at all.

    So a damaged input plus Compress used to mean an unreadable output. qpdf
    renumbers objects contiguously from 1 as it writes, which is what makes the
    count the right answer here.
    """
    if pikepdf.Name.Size not in pdf_output.trailer:
        pdf_output.trailer[pikepdf.Name.Size] = len(pdf_output.objects) + 1


def export_doc_job(pdf_input, files, pages, mdata, files_out, quit_flag=None,
                   test_mode: bool = False, output_password=None,
                   options: "SaveOptions" = None) -> None:
    """Same as export_doc() but via the pikepdf Job interface.

    This is the "preserve document information from the first file opened"
    behaviour; ``export_doc`` is the "merge bookmarks from all documents" one.
    Requires pikepdf >= 8.
    """
    if not isinstance(files_out[0], str):
        # Do not encrypt when printing
        output_password = None
    options = options or DEFAULT_SAVE_OPTIONS
    job = _create_job(files, pages, files_out, quit_flag, test_mode,
                      output_password=output_password, options=options)
    if job is None:
        return

    pdf_output = job.create_pdf()
    _ensure_trailer_size(pdf_output)
    max_version = get_max_pdf_version([pdf_output, *pdf_input])

    _transform_job(pdf_output, pages, quit_flag)
    if quit_flag is not None and quit_flag.is_set():
        return

    if isinstance(files_out[0], str) and not options.strip_metadata:
        # Only needed when saving to file, not when printing
        mdata = metadata.merge_doc(mdata, pdf_input)
    if isinstance(files_out[0], str) and options.viewer is not None:
        options.viewer.write(pdf_output)
    if len(files_out) > 1:
        if output_password:
            encryption = pikepdf.Encryption(user=output_password,
                                            owner=output_password, R=6)
        else:
            encryption = False
        for n, page in enumerate(pdf_output.pages):
            if quit_flag is not None and quit_flag.is_set():
                return
            outpdf = pikepdf.Pdf.new()
            _set_meta(mdata, pdf_input, outpdf)
            outpdf.pages.append(page)
            _remove_unreferenced_resources(outpdf)
            outpdf.save(files_out[n], min_version=max_version, encryption=encryption)
        return

    if isinstance(files_out[0], str) and options.strip_metadata:
        _strip_metadata(pdf_output)
    elif isinstance(files_out[0], str) and not test_mode:
        _set_meta(mdata, [pdf_output], pdf_output)
    job.write_pdf(pdf_output)


def export(files: List[Tuple[str, str]], pages: List[Page], mdata: dict,
           files_out: List[str], quit_flag=None, test_mode: bool = False,
           output_password: Optional[str] = None,
           preserve_first_document: bool = False,
           source_names: Optional[List[str]] = None,
           outline=None, prune_outline: bool = False,
           options: Optional["SaveOptions"] = None, form_values=None,
           annotations=None) -> str:
    """Write ``pages`` to ``files_out``.

    ``files`` is the ``(copyname, password)`` list from ``DocumentSet``; a page's
    ``nfile`` indexes into it.  Returns collected warning text, which the caller
    can show the user; an empty string means a clean run.

    ``preserve_first_document`` picks between the two export implementations, and
    is the "Saving/exporting to single file" preference: False merges bookmarks
    from every document, True keeps the first document's information via the
    pikepdf Job interface. Ignored on pikepdf < 8.

    ``outline`` is the document's edited bookmark tree (D20), written in place
    of one rebuilt from the sources. It reaches only the merging path: the
    ``preserve_first_document`` path hands the whole job to pikepdf, which keeps
    the first document's outline and gives us nowhere to put ours. That
    preference and edited bookmarks are therefore mutually exclusive, and the
    window says so rather than saving an outline the user cannot see.

    ``annotations`` are the marks the user has added, and reach only the same
    merging path, for the same reason.
    """
    collected = []

    def _show(message, category, filename, lineno, file=None, line=None):
        collected.append(str(message))
        print(warnings.formatwarning(message, category, filename, lineno, line))

    pdf_input = [pikepdf.open(copyname, password=password) for copyname, password in files]
    backup = warnings.showwarning
    warnings.showwarning = _show
    try:
        if preserve_first_document and HAS_PIKEPDF8:
            export_doc_job(pdf_input, files, pages, mdata, files_out, quit_flag,
                           test_mode, output_password=output_password,
                           options=options)
        else:
            export_doc(pdf_input, pages, mdata, files_out, quit_flag, test_mode,
                       output_password=output_password, options=options,
                       source_names=source_names, outline=outline,
                       prune_outline=prune_outline, form_values=form_values,
                       annotations=annotations)
    finally:
        warnings.showwarning = backup
        for pdf in pdf_input:
            pdf.close()
    return "\n".join(collected)


def num_pages(filepath) -> Optional[int]:
    """Return the number of pages of a PDF, or None if it cannot be read."""
    try:
        pdf = pikepdf.open(filepath)
    except (pikepdf.PasswordError, pikepdf.PdfError):
        return None
    with pdf:
        return len(pdf.pages)
