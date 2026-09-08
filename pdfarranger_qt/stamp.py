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

"""Drawing text onto pages: page numbers and watermarks.

One primitive, two features. Page numbers and watermarks differ in what the
text says, where it sits and how loud it is -- not in how it gets there -- so
both are `apply()` with a different `Style`.

**Nothing here writes into the source document.** A stamp is a generated PDF,
one page per stamped page and exactly its size, composited as an overlay by
`layers.paste_as_layer` -- the same route Merge Pages and booklet imposition
take. That is what makes stamping undoable, removable and safe on a file this
application never modifies in place. It also means a stamp behaves
like any other layer: rotate the page afterwards and the number rotates with
it.

The text is drawn with **QPdfWriter**, not by hand-assembling a content stream.
Writing `BT /F1 12 Tf ... Tj ET` against one of the base-14 fonts looks like the
smaller dependency until the text has to be *placed*: centring needs the string's
width, which needs font metrics, which means shipping an AFM table -- and it is
Latin-1 only, so a document numbered in Greek or Japanese would come out as
mojibake. QPdfWriter has the metrics and the font already, embeds a subset of
whatever was used, and takes Unicode. Resolution is fixed at 72 dpi so that one
Qt logical unit is one PDF point and no conversion is needed anywhere.

One consequence worth knowing: the **offscreen** Qt platform does not use the
system's font machinery, it replaces it, and its own fallback reads only what
``QT_QPA_FONTDIR`` names. On Linux the generic Unix path finds fontconfig and
needs no help; on Windows nothing looks anywhere, so
``QFontDatabase.families()`` is empty and text comes out as the boxes a missing
glyph draws -- paths rather than text. `has_fonts()` says which world the
caller is in.
"""

import dataclasses
import os
import tempfile
from typing import List, Optional, Sequence

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPageSize, QPainter, QPdfWriter

from .core import OVERLAY, DocumentSet, Page
from .i18n import gettext_ as _
from .layers import layer_stacks_from_entries, paste_as_layer

#: Where a stamp sits on the page, as (horizontal, vertical) alignment flags.
#: The keys are stable identifiers; the labels are for the dialog.
POSITIONS = [
    ("top-left", lambda: _("Top left"), Qt.AlignLeft | Qt.AlignTop),
    ("top-centre", lambda: _("Top centre"), Qt.AlignHCenter | Qt.AlignTop),
    ("top-right", lambda: _("Top right"), Qt.AlignRight | Qt.AlignTop),
    ("centre", lambda: _("Centre"), Qt.AlignHCenter | Qt.AlignVCenter),
    ("bottom-left", lambda: _("Bottom left"), Qt.AlignLeft | Qt.AlignBottom),
    ("bottom-centre", lambda: _("Bottom centre"), Qt.AlignHCenter | Qt.AlignBottom),
    ("bottom-right", lambda: _("Bottom right"), Qt.AlignRight | Qt.AlignBottom),
]

#: Placeholders accepted in a page-number format string.
PAGE_TOKEN, TOTAL_TOKEN = "{n}", "{total}"

#: Tried in order after whatever the style names. "Helvetica" is not a font on
#: Windows -- Qt resolves it to Tahoma, which is nobody's idea of Helvetica --
#: so the classic name is followed by what each platform actually ships.
FALLBACK_FAMILIES = ["Helvetica", "Arial", "Liberation Sans", "DejaVu Sans",
                     "Segoe UI", "Noto Sans"]


def has_fonts() -> bool:
    """Whether this Qt platform can draw actual glyphs.

    False under the offscreen platform used for testing, where every string
    becomes a row of empty boxes. See the module docstring.
    """
    return bool(QFontDatabase.families())


def _alignment(position: str):
    for key, _label, flags in POSITIONS:
        if key == position:
            return flags
    raise ValueError(f"unknown position: {position}")


@dataclasses.dataclass
class Style:
    """How a stamp looks and where it goes."""

    font: str = "Helvetica"
    size: float = 10.0
    colour: str = "#000000"
    #: 1.0 is solid. A watermark wants roughly 0.15; a page number wants 1.
    opacity: float = 1.0
    bold: bool = False
    italic: bool = False
    position: str = "bottom-centre"
    #: Degrees anticlockwise. Only meaningful for a centred watermark; a
    #: rotated corner stamp mostly falls off the page.
    rotation: float = 0.0
    #: Points of clear space between the text and the page edge. Ignored for a
    #: centred stamp, which has no edge to stand off from.
    margin: float = 24.0

    def qfont(self) -> QFont:
        font = QFont()
        families = [self.font] + [f for f in FALLBACK_FAMILIES if f != self.font]
        font.setFamilies(families)
        font.setStyleHint(QFont.SansSerif)
        font.setPointSizeF(max(self.size, 0.1))
        font.setBold(self.bold)
        font.setItalic(self.italic)
        return font


#: What a page number looks like unless the user says otherwise.
NUMBER_STYLE = Style()

#: A watermark: large, faint, across the middle at the usual angle.
WATERMARK_STYLE = Style(size=64.0, colour="#808080", opacity=0.18,
                        position="centre", rotation=45.0)


def format_number(template: str, number: int, total: int) -> str:
    """Fill ``{n}`` and ``{total}`` in a page-number template.

    Deliberately not ``str.format``: the template is user input, and
    ``format`` would treat a stray brace as a syntax error and any other name
    as a missing key -- turning a typo into an exception in the middle of a
    document-wide operation. Two replacements cannot fail.
    """
    return (template.replace(PAGE_TOKEN, str(number))
                    .replace(TOTAL_TOKEN, str(total)))


def render_stamps(path: str, sizes: Sequence, texts: Sequence[str],
                  style: Style) -> str:
    """Write a PDF with one page per entry, each carrying its text.

    ``sizes`` and ``texts`` are parallel: page *i* of the result is ``sizes[i]``
    points with ``texts[i]`` drawn on it. An empty string leaves the page blank,
    which is how "skip the first page" is expressed.
    """
    if len(sizes) != len(texts):
        raise ValueError("one text per page size is required")
    if not sizes:
        raise ValueError("nothing to stamp")

    writer = QPdfWriter(path)
    # One logical unit per PDF point, so nothing here converts units.
    writer.setResolution(72)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setPageSize(QPageSize(QSizeF(float(sizes[0][0]), float(sizes[0][1])),
                                 QPageSize.Point))

    painter = QPainter(writer)
    try:
        for index, (size, text) in enumerate(zip(sizes, texts)):
            if index:
                writer.setPageSize(QPageSize(
                    QSizeF(float(size[0]), float(size[1])), QPageSize.Point))
                writer.newPage()
            if text:
                _draw(painter, float(size[0]), float(size[1]), text, style)
    finally:
        painter.end()
    return path


def _draw(painter: QPainter, width: float, height: float, text: str,
          style: Style) -> None:
    painter.save()
    painter.setFont(style.qfont())
    painter.setPen(QColor(style.colour))
    painter.setOpacity(max(0.0, min(1.0, style.opacity)))

    if style.rotation:
        # Rotate about the middle of the page and draw into a box centred
        # there, so the text turns on the spot rather than swinging away from
        # wherever it started.
        painter.translate(width / 2, height / 2)
        painter.rotate(-style.rotation)
        reach = max(width, height)
        painter.drawText(QRectF(-reach, -reach, reach * 2, reach * 2),
                         Qt.AlignCenter, text)
    else:
        margin = style.margin if style.position != "centre" else 0.0
        box = QRectF(margin, margin,
                     max(width - 2 * margin, 1.0), max(height - 2 * margin, 1.0))
        painter.drawText(box, _alignment(style.position), text)
    painter.restore()


def apply(pages: List[Page], texts: Sequence[str], docs: DocumentSet,
          style: Optional[Style] = None) -> None:
    """Composite one text per page onto ``pages``, in place.

    The pages keep their identity -- this adds a layer, it does not replace
    them -- so the caller does not have to touch the page list, and undo gets
    the whole operation from the snapshot it already takes.
    """
    if len(pages) != len(texts):
        raise ValueError("one text per page is required")
    style = style or NUMBER_STYLE
    wanted = [(page.width_in_points(), page.height_in_points()) for page in pages]

    handle, path = tempfile.mkstemp(suffix=".pdf", dir=docs.tmp_dir)
    os.close(handle)
    render_stamps(path, wanted, texts, style)
    _doc, nfile, _created = docs.get_doc(path)
    copyname = docs.docs[nfile - 1].copyname

    for index, page in enumerate(pages):
        if not texts[index]:
            continue
        # The stamp page is exactly the size of the page it goes on, so there
        # is no slack for the offset to distribute and any offset would do.
        entry = (copyname, index + 1, "", 0, 1.0, (0, 0, 0, 0), (0, 0, 0, 0), [])
        stacks = layer_stacks_from_entries([entry], OVERLAY, docs)
        paste_as_layer([page], stacks, OVERLAY, (0.5, 0.5), docs)


def add_page_numbers(pages: List[Page], docs: DocumentSet,
                     template: str = PAGE_TOKEN, start: int = 1,
                     skip_first: bool = False,
                     style: Optional[Style] = None) -> None:
    """Number ``pages`` from ``start``, in the order given.

    ``skip_first`` leaves the first page unstamped but still counted, which is
    what a title page wants.
    """
    total = len(pages)
    texts = []
    for index in range(total):
        if skip_first and index == 0:
            texts.append("")
        else:
            texts.append(format_number(template, start + index, start + total - 1))
    apply(pages, texts, docs, style or NUMBER_STYLE)


def add_watermark(pages: List[Page], docs: DocumentSet, text: str,
                  style: Optional[Style] = None) -> None:
    """Put the same text on every page."""
    if not text:
        raise ValueError("a watermark needs some text")
    apply(pages, [text] * len(pages), docs, style or WATERMARK_STYLE)
