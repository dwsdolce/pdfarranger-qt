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

"""Form fields drawn as a layer over the page, not baked into it.

Which is how every implementation of this does it, and PDFium most of all:
``FPDF_RenderPageBitmap`` draws a page *without* its form fields and
``FPDF_FFLDraw`` draws them afterwards, from state held in memory rather than
in the file. QtPdf calls the first and not the second, which is why a filled
form came up blank here; this is the second half, in Python. pdf.js makes the
same split with an annotation layer of real HTML inputs over a rendered canvas,
and Acrobat regenerates appearances on commit rather than per keystroke.

The alternative, which body 1 shipped and this supersedes, was to rewrite each
widget into something PDFium would draw and let it render the page with the
fields in it. That is correct and it does not scale to *editing*: the state
lives in the file, so changing a tick means rewriting the document. Measured on
the corpus -- 682 ms to re-save sf86.pdf, against 1 ms to patch the value. A
keystroke cannot cost that, and 2.5 is typing.

Here a tick is a repaint. The page image never changes; only which appearance
is drawn over it. One widget's appearance renders in about 0.4 ms and is cached
by appearance, state and size, so a page of fifty costs twenty milliseconds
once -- and a tick box's drawings are shared between widgets, so sf86's 2,846
buttons have a handful of distinct images between them.
"""

import io
from typing import Dict, Optional

import pikepdf
from PySide6.QtCore import QBuffer, QByteArray, QSize
from PySide6.QtGui import QImage, QTransform
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

from . import forms
from .render import ANNOTATIONS

#: Nothing is drawn below this; a widget scaled to nothing is not worth a
#: document, and a zero-sized render is an error rather than an empty image.
_MINIMUM_PX = 2


def _appearance_for(annot, state: Optional[str]):
    """The appearance stream this widget would draw in ``state``, or None."""
    appearance = annot.get(pikepdf.Name.AP)
    if appearance is None:
        return None
    normal = appearance.get(pikepdf.Name.N)
    if isinstance(normal, pikepdf.Stream):
        return normal
    if isinstance(normal, pikepdf.Dictionary):
        if state is not None and state in normal:
            return normal.get(state)
        return None
    return None


class AppearanceRenderer:
    """Renders one widget's appearance, on its own, at a size.

    A one-page document the size of the widget, carrying the widget as a stamp
    filling the page. PDFium then does the placement -- transform the
    appearance's BBox by its Matrix and fit the result to the Rect -- which is
    the rule that must not be reimplemented: of the 74 appearances in the form
    this work began with, every one had a Matrix and 45 had a BBox that did not
    match its Rect.
    """

    def __init__(self):
        #: ``(appearance id, state, width, height) -> QImage``. Keyed on the
        #: appearance rather than the widget, because a tick box's drawings are
        #: shared: one image serves every box in the form.
        self._cache: Dict[tuple, QImage] = {}
        #: The rendered documents, kept alive. A QPdfDocument that is collected
        #: takes the bitmap it lent us with it.
        self._documents: list = []

    def clear(self):
        self._cache.clear()
        self._documents.clear()

    def __len__(self):
        return len(self._cache)

    def text_image(self, annot, value: str, acroform, source, width: int,
                   height: int, rotation: int = 0) -> Optional[QImage]:
        """A text field drawn with ``value``, which is not in the file.

        The appearance is generated rather than looked up, because a field the
        user has just typed into has none that matches -- and most text fields
        in real forms have none at all to begin with. Cached by the widget and
        the string, so holding a key down costs one render per character and
        nothing thereafter.
        """
        if width < _MINIMUM_PX or height < _MINIMUM_PX:
            return None
        try:
            key = ("text", annot.objgen, value, width, height, rotation)
        except Exception:  # pragma: no cover - a direct annotation
            key = ("text", id(annot), value, width, height, rotation)
        found = self._cache.get(key)
        if found is not None:
            return found
        image = self._render(annot, None, width, height, text=value,
                             acroform=acroform, source=source,
                             rotation=rotation)
        if image is not None:
            self._cache[key] = image
        return image

    def image(self, annot, state: Optional[str], width: int,
              height: int, rotation: int = 0) -> Optional[QImage]:
        """``annot`` drawn in ``state`` at this pixel size, or None.

        None when there is nothing to draw -- an empty text field, a state the
        widget has no appearance for -- which is not a failure: a viewer shows
        nothing there either.
        """
        if width < _MINIMUM_PX or height < _MINIMUM_PX:
            return None
        appearance = _appearance_for(annot, state)
        if appearance is None:
            return None
        try:
            key = (appearance.objgen, state, width, height, rotation)
        except Exception:  # pragma: no cover - a direct appearance stream
            key = (id(appearance), state, width, height, rotation)
        found = self._cache.get(key)
        if found is not None:
            return found
        image = self._render(annot, state, width, height, rotation=rotation)
        if image is not None:
            self._cache[key] = image
        return image

    def _render(self, annot, state, width, height, text=None,
                acroform=None, source=None, rotation=0) -> Optional[QImage]:
        """``width`` and ``height`` are the size wanted on screen.

        On a page the reader turns, that is not the size to render at: the
        appearance is written in the page's own frame, so it is drawn at the
        unturned size -- the two swapped for a quarter turn -- and the result
        is turned to match. Rendering at the on-screen size instead would
        squash the drawing into the wrong aspect ratio before turning it.
        """
        quarter = (rotation // 90) % 4
        if quarter % 2:
            width, height = height, width
        try:
            rect = [float(v) for v in annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
            points_wide = abs(rect[2] - rect[0])
            points_high = abs(rect[3] - rect[1])
            if points_wide <= 0 or points_high <= 0:
                return None
            page = pikepdf.new()
            page.add_blank_page(page_size=(points_wide, points_high))
            copy = page.copy_foreign(annot)
            copy[pikepdf.Name.Rect] = pikepdf.Array(
                [0, 0, points_wide, points_high])
            # A stamp rather than a widget: PDFium excludes form fields from
            # page rendering by design, which is the whole reason this module
            # exists. Only the subtype changes; the appearance, its Matrix and
            # its BBox are untouched, so the placement is still PDFium's.
            copy[pikepdf.Name.Subtype] = pikepdf.Name.Stamp
            if state is not None:
                copy[pikepdf.Name.AS] = pikepdf.Name(state)
            if text is not None:
                # Built here rather than in the document being read: a stream
                # has to belong to the file it is drawn from, and the one on
                # screen is not ours to add objects to.
                resources = forms.resources_for(annot, acroform)
                if resources is None or source is None:
                    return None
                # Indirect first: copy_foreign will only take an object that
                # has an identity in its own document, and a /DR written
                # inline has none. The owning document has to be passed in
                # because a pikepdf object does not know which one it is in.
                drawn = forms.text_appearance(
                    page, copy, text,
                    resources=page.copy_foreign(
                        source.make_indirect(resources)))
                if drawn is None:
                    return None
                copy[pikepdf.Name.AP] = pikepdf.Dictionary(N=drawn)
            page.pages[0][pikepdf.Name.Annots] = pikepdf.Array([copy])
            data = io.BytesIO()
            page.save(data)

            document = QPdfDocument()
            buffer = QBuffer()
            buffer.setData(QByteArray(data.getvalue()))
            buffer.open(QBuffer.ReadOnly)
            # The device overload of load() returns *void*; only the one
            # taking a file name returns an error. Comparing its result with
            # Error.None_ therefore fails for every document ever loaded, and
            # silently -- which is exactly what it did here until the page
            # stayed blank with nothing to say why.
            document.load(buffer)
            if document.pageCount() < 1:
                return None
            options = QPdfDocumentRenderOptions()
            options.setRenderFlags(ANNOTATIONS)
            image = document.render(0, QSize(width, height), options)
            if image.isNull():
                return None
            # The document owns the bitmap; a copy outlives it.
            image = image.copy()
            if quarter:
                # Clockwise, which is what /Rotate means and which is the
                # direction a positive angle turns in Qt's y-down frame.
                image = image.transformed(QTransform().rotate(quarter * 90))
            return image
        except Exception:  # noqa: BLE001 - a field that will not draw is blank
            return None
