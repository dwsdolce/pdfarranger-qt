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

"""A text box's words: laid out once, drawn on the screen and into the file.

**One layout for both.** The canvas paints a text box's text and the file
carries a drawing of it, and if the two were laid out separately they would
break lines in different places. So both come from one `QTextDocument`,
laid out in points -- a paint device at 72 dots an inch, so one unit is one
point -- wrapping between words, breaking a word only when it is too long
for the line. The canvas paints it scaled to the zoom; `QPdfWriter` writes
it into a page whose content becomes the text's part of the box's
appearance, with the font embedded.

**The lines are placed here, not by Qt.** Qt breaks the lines and this
module puts them where Acrobat does: the first baseline `FIRST_BASELINE`
times the size below the top of the text, each next one `LINE_SPACING`
times the size below that. Qt's own fixed line height was tried first and
put the spare room above each line, so the text sat lower than Acrobat's;
and it scales that height by the main screen's resolution, so the lines came
out 14.4 points apart offscreen and 19.2 on a Mac.

`markup` stays free of Qt; this is the half that needs it.
"""

import io
from typing import Optional

import pikepdf
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QMarginsF,
    QPointF,
    QRectF,
    QSizeF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)

#: Lines are this many times the font size apart: 14.4 points at 12, read
#: off Acrobat's own text boxes.
LINE_SPACING = 1.2

#: The first baseline is this many times the font size below the top of the
#: text: 9.96 points at 12, the same in every box Acrobat drew in
#: `Markup Text Comment.pdf` whatever its border or cloud. Measured at 12
#: points only.
FIRST_BASELINE = 0.83

_LAYOUT_DEVICE: Optional[QImage] = None


def _layout_device() -> QImage:
    """A paint device at 72 dots an inch, so a layout is in points."""
    global _LAYOUT_DEVICE
    if _LAYOUT_DEVICE is None:
        image = QImage(1, 1, QImage.Format_ARGB32)
        dots = round(72 / 0.0254)
        image.setDotsPerMeterX(dots)
        image.setDotsPerMeterY(dots)
        _LAYOUT_DEVICE = image
    return _LAYOUT_DEVICE


def font_for(family: str, size: float) -> QFont:
    font = QFont(family)
    font.setPointSizeF(max(float(size), 0.5))
    return font


def layout(text: str, family: str, size: float, colour, width: float,
           device=None) -> QTextDocument:
    """``text`` laid out ``width`` points wide, in one font and colour.

    ``device`` is what the layout is measured against; points by default.
    The editor on the canvas lays its own document out against the screen,
    with the size scaled to the zoom, and the same rules.
    """
    document = QTextDocument()
    document.documentLayout().setPaintDevice(device or _layout_device())
    document.setDocumentMargin(0)
    document.setDefaultFont(font_for(family, size))
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    document.setPlainText(text)
    paint = QColor.fromRgbF(*colour[:3])
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    char = cursor.charFormat()
    char.setForeground(paint)
    cursor.mergeCharFormat(char)
    document.setTextWidth(max(float(width), 1.0))
    return document


def _lines(document: QTextDocument):
    """Every line of ``document``, in order, with the layout it is in."""
    block = document.firstBlock()
    while block.isValid():
        found = block.layout()
        for k in range(found.lineCount()):
            yield found, found.lineAt(k)
        block = block.next()


def place_lines(document: QTextDocument, size: float) -> int:
    """Put every line of a laid-out ``document`` where Acrobat would, and
    answer how many there are. A block with no text still has its line."""
    count = 0
    for found, line in _lines(document):
        baseline = (FIRST_BASELINE + count * LINE_SPACING) * float(size)
        line.setPosition(QPointF(line.x(), baseline - line.ascent()
                                 - found.position().y()))
        count += 1
    return count


def _draw(painter: QPainter, document: QTextDocument) -> None:
    """Draw a document whose lines `place_lines` has placed. A block's
    layout adds its own position to the one it is drawn at."""
    block = document.firstBlock()
    while block.isValid():
        block.layout().draw(painter, QPointF(0, 0))
        block = block.next()


def _qt_default_dpi() -> float:
    """The resolution Qt measures a fixed line height against: the main
    screen's -- 96 dots an inch offscreen, 72 on a Mac."""
    screen = QGuiApplication.primaryScreen()
    return float(screen.logicalDotsPerInchY()) if screen is not None else 96.0


def apply_spacing(document: QTextDocument, line: float, dpi: float) -> float:
    """Space an editor's lines ``line`` times `LINE_SPACING` apart, in the
    units of its device at ``dpi`` dots an inch, and answer how far below
    Acrobat's its first baseline then is, in those units.

    For the editor on the canvas, which lays its text out again at every
    key and so cannot have its lines placed. Qt scales a fixed line height
    by the device's resolution against `_qt_default_dpi`, so the height is
    converted first; and it puts the spare room above the line, which the
    answer measures so the editor can be raised by it.
    """
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    block = QTextBlockFormat()
    block.setLineHeight(float(line) * LINE_SPACING * _qt_default_dpi()
                        / max(float(dpi), 1.0),
                        QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    cursor.mergeBlockFormat(block)
    for found, first in _lines(document):
        return (found.position().y() + first.y() + first.ascent()
                - FIRST_BASELINE * float(line))
    return 0.0


def needed_height(text: str, family: str, size: float, width: float) -> float:
    """How tall ``text`` is, in points, laid out ``width`` points wide --
    one line's height for an empty box, which still has a line to type on."""
    document = layout(text or " ", family, size, (0, 0, 0), width)
    return max(1, place_lines(document, size)) * size * LINE_SPACING


def text_form(pdf: pikepdf.Pdf, text: str, family: str, size: float, colour,
              width: float) -> Optional[pikepdf.Stream]:
    """The text, as a form XObject ``width`` points wide, its own height tall.

    Drawn by `QPdfWriter`, which embeds a subset of the font used and takes
    any language, then lifted out of the page it drew into: the page's
    content becomes the form's, its resources -- the embedded font -- the
    form's resources. Its origin is the bottom left of the text, so it is
    placed by its top left less its height. None when there is nothing to
    draw.
    """
    if not text:
        return None
    height = needed_height(text, family, size, width)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(72)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))
    writer.setPageSize(QPageSize(QSizeF(float(width), float(height)),
                                 QPageSize.Point))
    painter = QPainter(writer)
    try:
        document = layout(text, family, size, colour, width)
        place_lines(document, size)
        _draw(painter, document)
    finally:
        painter.end()
    buffer.close()
    with pikepdf.open(io.BytesIO(bytes(data))) as drawn:
        page = drawn.pages[0]
        body = b"".join(part.read_bytes() for part in (
            page.obj.Contents if isinstance(page.obj.Contents, pikepdf.Array)
            else [page.obj.Contents]))
        resources = pdf.copy_foreign(page.obj.get(pikepdf.Name.Resources)
                                     or pikepdf.Dictionary())
    form = pikepdf.Stream(pdf, body)
    form[pikepdf.Name.Type] = pikepdf.Name.XObject
    form[pikepdf.Name.Subtype] = pikepdf.Name.Form
    form[pikepdf.Name.BBox] = pikepdf.Array([0, 0, float(width), float(height)])
    form[pikepdf.Name.Resources] = resources
    return pdf.make_indirect(form)


def paint(painter: QPainter, text: str, family: str, size: float, colour,
          width: float, clip_height: float) -> None:
    """Paint ``text`` at the painter's origin, in points, as the file draws
    it; the caller scales the painter to the zoom."""
    if not text:
        return
    document = layout(text, family, size, colour, width)
    place_lines(document, size)
    painter.save()
    painter.setClipRect(QRectF(0, 0, float(width), float(clip_height)),
                        Qt.IntersectClip)
    _draw(painter, document)
    painter.restore()
