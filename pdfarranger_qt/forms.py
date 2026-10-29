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

"""Making filled form fields visible.

A filled form opened here and came up blank. The answers were all in the file
-- 23 of them, each with an appearance stream ready to draw -- and no renderer
in this application would draw any of them.

Setting ``RenderFlag.Annotations`` does not fix it. PDFium excludes *widget*
annotations from page rendering by design: it draws the page, then leaves form
fields to a form-fill module (``FPDFDOC_InitFormFillEnvironment`` and
``FPDF_FFLDraw``) that QtPdf never initialises and does not expose. Measured on
one page carrying one annotation with the same appearance stream, differing
only in subtype: ``/Square`` draws with the flag, ``/Widget`` draws neither
with it nor without.

So the fix is to stop the annotation looking like a form field to the renderer.
Changing ``/Subtype`` from ``/Widget`` to ``/Stamp`` is the whole of it: the
appearance stream, its ``/Matrix``, its ``/BBox`` and the ``/AS`` that chooses a
tick box's state are all general annotation machinery, and PDFium applies the
specification's placement rules to any annotation it is willing to draw.

**Why not stamp the appearance into the page content**, which is the obvious
thing to write and what a "flatten" command would do. An appearance is placed
by transforming its BBox by its Matrix and fitting the result to the
annotation's Rect. Of the 74 appearances in the form this was built for, every
single one carried a Matrix and 45 had a BBox that did not match the Rect --
one of them 18.2pt tall in an 11.5pt box. Translating the stream to the corner
of the Rect, which is what the obvious implementation does, draws 61% of them
at the wrong size. Placing an appearance is the renderer's job, and PDFium
already does it correctly.

**This never reaches a saved file.** The rewritten document is for rendering
only: the grid, the reader and nothing else. Export reads the real copy, which
still has its widgets and, since the form dictionary is rebuilt there, still
has a working ``/AcroForm``.
"""

import os
import tempfile
from typing import Optional

import pikepdf


def has_widgets(pdf) -> bool:
    """Whether any page carries a form field with something to draw.

    The question the whole feature is gated on. A document with no fields --
    which is nearly all of them -- must not pay for a second copy, and D19's
    fast path into read mode has to survive untouched for those.
    """
    for page in pdf.pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            if (annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget
                    and pikepdf.Name.AP in annot):
                return True
    return False


def show_widgets(pdf) -> int:
    """Rewrite form fields so a page renderer will draw them. Returns how many.

    Only those with an appearance: one without is invisible in any viewer, and
    leaving it alone keeps this consistent with `has_widgets`.

    A hidden field stays hidden. Bit 2 of ``/F`` is honoured by the renderer
    for every annotation, so a field the document says not to show is still not
    shown -- which is correct, and would not be if the appearance were stamped
    into the page content instead.
    """
    changed = 0
    for page in pdf.pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            if (annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget
                    and pikepdf.Name.AP in annot):
                annot[pikepdf.Name.Subtype] = pikepdf.Name.Stamp
                changed += 1
    return changed


def rendered_copy(source: str, password: str, tmp_dir: str) -> Optional[str]:
    """A copy of ``source`` whose fields will draw, or None if it has none.

    None rather than a copy of an unchanged file, so that the caller can go on
    using the original path and nothing is written for the documents that do
    not need it.
    """
    try:
        with pikepdf.open(source, password=password or "") as pdf:
            if not has_widgets(pdf):
                return None
            show_widgets(pdf)
            fd, path = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
            os.close(fd)
            pdf.save(path)
            return path
    except Exception:  # noqa: BLE001 - rendering falls back to the original
        return None


def rendered_bytes(data: bytes) -> bytes:
    """The same, for the export read mode builds when pages have been edited.

    Returns ``data`` unchanged when there is nothing to rewrite, so the caller
    can hand the result straight on without asking which it got.
    """
    try:
        import io

        with pikepdf.open(io.BytesIO(data)) as pdf:
            if not has_widgets(pdf):
                return data
            show_widgets(pdf)
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except Exception:  # noqa: BLE001 - rendering falls back to the original
        return data
