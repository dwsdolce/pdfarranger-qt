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

import io
import locale
import os
import traceback
import warnings
from typing import Any, Dict, List, Optional, Tuple

import packaging.version
import pikepdf

from . import metadata
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


def _set_meta(mdata, pdf_input, pdf_output):
    ppae = metadata.PRODUCER not in mdata
    with pdf_output.open_metadata(set_pikepdf_as_editor=ppae) as outmeta:
        if len(pdf_input) > 0:
            metadata.load_from_docinfo(outmeta, pdf_input[0])
        for k, v in mdata.items():
            outmeta[k] = v


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
    new_page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=newmediabox,
        Contents=doc.make_stream(content.encode()),
        Resources={"/XObject": {"/p{}".format(page_id): xobject}},
        Rotate=rotate,
    )
    # Needed for pikepdf <= 2.6.0 and again for 8.8.
    # See https://github.com/pikepdf/pikepdf/issues/174
    return doc.make_indirect(new_page)


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


def _remove_unreferenced_resources(pdfdoc):
    try:
        pdfdoc.remove_unreferenced_resources()
    except RuntimeError:
        # Catches "operation for dictionary attempted on object of type null"
        # seen with old pikepdf. Blindly catching every RuntimeError is
        # dangerous, so print it rather than swallow it.
        print(traceback.format_exc())


def _append_page(current_page, copied_pages, pdf_output, row):
    """Add a page to the output pdf. A page that already exists is duplicated."""
    new_page = copied_pages.get((row.nfile, row.npage))
    if new_page is None:
        new_page = current_page
    # let pdf_output adopt new_page
    pdf_output.pages.append(new_page)
    new_page = pdf_output.pages[-1]
    copied_pages[(row.nfile, row.npage)] = new_page
    # Ensure annotations are copied rather than referenced
    # https://github.com/pdfarranger/pdfarranger/issues/437
    if pikepdf.Name.Annots in current_page:
        pdf_temp = pikepdf.Pdf.new()
        pdf_temp.pages.append(current_page)
        indirect_annots = pdf_temp.make_indirect(pdf_temp.pages[0].Annots)
        new_page.Annots = pdf_output.copy_foreign(indirect_annots)


def _copy_n_transform(pdf_input, pdf_output, pages, quit_flag=None):
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
               test_mode=False, output_password=None, with_outlines=False):
    """Same as export() but taking already-opened pikepdf.Pdf objects."""
    pdf_output = pikepdf.Pdf.new()
    max_version = get_max_pdf_version([pdf_output, *pdf_input])
    _copy_n_transform(pdf_input, pdf_output, pages, quit_flag)
    if quit_flag is not None and quit_flag.is_set():
        return

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

        exporter_outlines.rebuild_outlines(pdf_input, pdf_output, pages)
    # Always, and regardless of outlines: a saved file whose internal links
    # all point at nothing is broken however it was produced.
    from . import exporter_outlines as _links

    _links.remap_link_annotations(pdf_input, pdf_output, pages)

    if to_file:
        mdata = metadata.merge_doc(mdata, pdf_input)
        password = output_password
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
            outpdf.save(files_out[n], min_version=max_version, encryption=encryption)
        return

    if to_file:
        if not test_mode:
            _set_meta(mdata, pdf_input, pdf_output)
        _remove_unreferenced_resources(pdf_output)
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
        pdf_output.save(files_out[0], min_version=max_version, encryption=encryption)


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
                      outlines: bool = False) -> bytes:
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
        export_doc(pdf_input, pages, {}, [buf], None, with_outlines=outlines)
    finally:
        for pdf in pdf_input:
            if pdf is not None:
                pdf.close()
    return buf.getvalue()


def _create_job(files: List[List[str]], pages: List[Page], files_out: List[str],
                quit_flag=None, test_mode: bool = False, output_password=None):
    """Build the pikepdf Job that copies pages. Requires pikepdf >= 8.

    The Job interface copies pages and their annotations for us, so unlike
    ``_copy_n_transform`` there is no explicit append step; media boxes are
    left until the transformation stage.
    """
    json = dict(outputFile=files_out[0], pages=[], removeUnreferencedResources="yes")
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


def export_doc_job(pdf_input, files, pages, mdata, files_out, quit_flag=None,
                   test_mode: bool = False, output_password=None) -> None:
    """Same as export_doc() but via the pikepdf Job interface.

    This is the "preserve document information from the first file opened"
    behaviour; ``export_doc`` is the "merge bookmarks from all documents" one.
    Requires pikepdf >= 8.
    """
    if not isinstance(files_out[0], str):
        # Do not encrypt when printing
        output_password = None
    job = _create_job(files, pages, files_out, quit_flag, test_mode,
                      output_password=output_password)
    if job is None:
        return

    pdf_output = job.create_pdf()
    max_version = get_max_pdf_version([pdf_output, *pdf_input])

    _transform_job(pdf_output, pages, quit_flag)
    if quit_flag is not None and quit_flag.is_set():
        return

    if isinstance(files_out[0], str):
        # Only needed when saving to file, not when printing
        mdata = metadata.merge_doc(mdata, pdf_input)
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

    if isinstance(files_out[0], str) and not test_mode:
        _set_meta(mdata, [pdf_output], pdf_output)
    job.write_pdf(pdf_output)


def export(files: List[Tuple[str, str]], pages: List[Page], mdata: dict,
           files_out: List[str], quit_flag=None, test_mode: bool = False,
           output_password: Optional[str] = None,
           preserve_first_document: bool = False) -> str:
    """Write ``pages`` to ``files_out``.

    ``files`` is the ``(copyname, password)`` list from ``DocumentSet``; a page's
    ``nfile`` indexes into it.  Returns collected warning text, which the caller
    can show the user; an empty string means a clean run.

    ``preserve_first_document`` picks between the two export implementations, and
    is the "Saving/exporting to single file" preference: False merges bookmarks
    from every document, True keeps the first document's information via the
    pikepdf Job interface. Ignored on pikepdf < 8.
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
                           test_mode, output_password=output_password)
        else:
            export_doc(pdf_input, pages, mdata, files_out, quit_flag, test_mode,
                       output_password=output_password)
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
