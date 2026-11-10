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

**Qt lays the lines out, by its own rules, everywhere.** Each line is
`LINE_SPACING` times its natural height -- 14.4 points for 12 point
Helvetica, as Acrobat sets it -- and a line holding a bigger word or a
taller font grows by that font's own measure. The editor on the canvas is
spaced the same way, so what is typed is what is shown and written.
Acrobat's own spacing was copied for a while and given up: its numbers are
per font and cannot be derived, it ignores justify in what it draws, and a
fixed line height in Qt is scaled by the main screen's resolution, which put
lines 14.4 points apart offscreen and 19.2 on a Mac. A percentage is not.

**The rich text is the text.** A box's words are its `/RC`, run by run --
font, size, colour, bold, italic, underline, strikethrough, superscript,
subscript, and each paragraph's alignment -- read into the document here and
written back from it in the shape Acrobat writes. A box with no `/RC` is its
`/Contents` in its default style.

`markup` stays free of Qt; this is the half that needs it.
"""

import io
import re
from html import escape
from typing import List, NamedTuple, Optional, Tuple
from xml.etree import ElementTree

import pikepdf
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextOption,
)

from . import markup

#: Each line is this many times its natural height: 14.4 points for 12 point
#: Helvetica, which is what Acrobat's text boxes have.
LINE_SPACING = 1.2

#: The sizes the palette offers, read off Acrobat's list. Only these can be
#: chosen; a box can still carry another, from a file, and keeps it.
SIZES = (6, 8, 9, 10, 12, 14, 18, 20, 22, 24, 26, 28, 36, 48, 72)

ALIGNMENTS = ("left", "center", "right", "justify")
_QT_ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
             "right": Qt.AlignRight, "justify": Qt.AlignJustify}

_LAYOUT_DEVICE: Optional[QImage] = None


class Style(NamedTuple):
    """What one run of a box's text looks like."""

    family: str
    size: float
    colour: Tuple[float, ...]
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    #: "super", "sub" or None.
    shift: Optional[str] = None


class Content(NamedTuple):
    """Everything a box's words are made from: its `/RC`, if it has one,
    its plain text, and its default style, which is `/DS`."""

    rich: Optional[str]
    text: str
    family: str
    size: float
    colour: Tuple[float, ...]

    @property
    def empty(self) -> bool:
        return not self.text and not self.rich


def content_of(mark) -> Content:
    family, size, colour = markup.text_style_of(mark)
    return Content(getattr(mark, "rich", None) or None,
                   getattr(mark, "contents", "") or "", family, size, colour)


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


# -- reading /RC --------------------------------------------------------------

def _declarations(style: str) -> dict:
    found = {}
    for part in (style or "").split(";"):
        name, _, value = part.partition(":")
        if value.strip():
            found[name.strip().lower()] = value.strip()
    return found


def _family(value: str) -> str:
    """The first family of a CSS list, unquoted: `'Courier Std'`,
    `Helvetica,sans-serif`."""
    return value.split(",")[0].strip().strip("'\"").strip()


def _restyled(style: Style, declared: dict) -> Style:
    """``style`` with what ``declared`` sets put over it."""
    changes = {}
    if "font-family" in declared and _family(declared["font-family"]):
        changes["family"] = _family(declared["font-family"])
    size = declared.get("font-size", "")
    match = re.match(r"\s*([\d.]+)", size)
    # A negative size is Acrobat's way of saying "not set".
    if match and not size.strip().startswith("-"):
        changes["size"] = float(match.group(1))
    colour = re.match(r"\s*#([0-9A-Fa-f]{6})", declared.get("color", ""))
    if colour:
        changes["colour"] = tuple(int(colour.group(1)[k:k + 2], 16) / 255.0
                                  for k in (0, 2, 4))
    weight = declared.get("font-weight", "").lower()
    if weight:
        changes["bold"] = weight == "bold" or (weight.isdigit() and int(weight) >= 600)
    slant = declared.get("font-style", "").lower()
    if slant:
        changes["italic"] = slant in ("italic", "oblique")
    decoration = declared.get("text-decoration", "").lower().split()
    if decoration:
        # Acrobat writes underline as "word".
        changes["underline"] = "underline" in decoration or "word" in decoration
        changes["strike"] = "line-through" in decoration
    shift = declared.get("vertical-align", "").lower()
    if shift:
        # Acrobat writes only the sign, "+0.0pt" and "-0.0pt".
        changes["shift"] = ("super" if shift.startswith(("+", "super")) else
                            "sub" if shift.startswith(("-", "sub")) else None)
    return style._replace(**changes) if changes else style


def _alignment(declared: dict) -> Optional[str]:
    value = declared.get("text-align", "").lower()
    return value if value in ALIGNMENTS else None


def paragraphs_of(content: Content) -> List[Tuple[str, List[Tuple[str, Style]]]]:
    """The box's words as paragraphs of ``(alignment, runs)``, each run
    ``(text, Style)``: from `/RC` where it parses, otherwise the plain
    text in the default style."""
    base = Style(content.family, float(content.size), tuple(content.colour))
    found = _rich_paragraphs(content.rich, base) if content.rich else None
    if found is not None:
        return found
    return [("left", [(line, base)] if line else [])
            for line in (content.text or "").split("\n")]


def _rich_paragraphs(rich: str, base: Style):
    try:
        root = ElementTree.fromstring(rich)
    except ElementTree.ParseError:
        return None
    if _tag(root) != "body":
        root = next((node for node in root.iter() if _tag(node) == "body"), root)
    declared = _declarations(root.get("style", ""))
    body = _restyled(base, declared)
    body_align = _alignment(declared) or "left"
    paragraphs = []

    def walk(node, style, runs, aligns):
        if node.text:
            runs.append((node.text, style))
        for child in node:
            tag = _tag(child)
            if tag == "br":
                runs.append(("\n", style))
            else:
                here = style
                if tag == "span":
                    found = _declarations(child.get("style", ""))
                    here = _restyled(style, found)
                    if _alignment(found):
                        aligns.append(_alignment(found))
                elif tag == "b":
                    here = style._replace(bold=True)
                elif tag == "i":
                    here = style._replace(italic=True)
                elif tag == "u":
                    here = style._replace(underline=True)
                walk(child, here, runs, aligns)
            if child.tail:
                runs.append((child.tail, style))

    for node in root:
        if _tag(node) != "p":
            continue
        declared = _declarations(node.get("style", ""))
        style = _restyled(body, declared)
        runs, aligns = [], []
        walk(node, style, runs, aligns)
        align = _alignment(declared) or (aligns[0] if aligns else body_align)
        # A <br> inside a paragraph starts another with the same alignment.
        line = []
        for text, run_style in runs:
            pieces = text.replace("​", "").split("\n")
            for n, piece in enumerate(pieces):
                if n:
                    paragraphs.append((align, line))
                    line = []
                if piece:
                    line.append((piece, run_style))
        paragraphs.append((align, line))
    return paragraphs or None


def _tag(node) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


# -- the document -------------------------------------------------------------

def char_format(style: Style, factor: float = 1.0) -> QTextCharFormat:
    """A run's style as Qt's, its size times ``factor``."""
    fmt = QTextCharFormat()
    fmt.setFontFamilies([style.family])
    fmt.setFontPointSize(max(float(style.size) * factor, 0.5))
    fmt.setForeground(QColor.fromRgbF(*style.colour[:3]))
    fmt.setFontWeight(QFont.Weight.Bold if style.bold else QFont.Weight.Normal)
    fmt.setFontItalic(style.italic)
    fmt.setFontUnderline(style.underline)
    fmt.setFontStrikeOut(style.strike)
    fmt.setVerticalAlignment(
        QTextCharFormat.VerticalAlignment.AlignSuperScript if style.shift == "super"
        else QTextCharFormat.VerticalAlignment.AlignSubScript if style.shift == "sub"
        else QTextCharFormat.VerticalAlignment.AlignNormal)
    return fmt


def style_of(fmt: QTextCharFormat, default: Style, factor: float = 1.0) -> Style:
    """A run's Qt format as a `Style`, its size divided by ``factor``;
    what the format does not set is ``default``'s."""
    families = fmt.fontFamilies() if fmt.hasProperty(QTextFormat.Property.FontFamilies) else None
    family = (families[0] if families else None) or default.family
    size = (round(fmt.fontPointSize() / factor, 2)
            if fmt.hasProperty(QTextFormat.Property.FontPointSize)
            and fmt.fontPointSize() > 0 else default.size)
    colour = (tuple(fmt.foreground().color().getRgbF()[:3])
              if fmt.hasProperty(QTextFormat.Property.ForegroundBrush)
              else default.colour)
    where = fmt.verticalAlignment()
    shift = ("super" if where == QTextCharFormat.VerticalAlignment.AlignSuperScript
             else "sub" if where == QTextCharFormat.VerticalAlignment.AlignSubScript
             else None)
    return Style(family, float(size), colour,
                 fmt.fontWeight() >= QFont.Weight.DemiBold, fmt.fontItalic(),
                 fmt.fontUnderline(), fmt.fontStrikeOut(), shift)


def alignment_of(block_format: QTextBlockFormat) -> str:
    align = block_format.alignment()
    if align & Qt.AlignJustify:
        return "justify"
    if align & Qt.AlignHCenter:
        return "center"
    if align & Qt.AlignRight:
        return "right"
    return "left"


def block_format(align: str) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setAlignment(_QT_ALIGN.get(align, Qt.AlignLeft))
    fmt.setLineHeight(LINE_SPACING * 100.0,
                      QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    return fmt


def fill(document: QTextDocument, content: Content, factor: float = 1.0) -> None:
    """Put the box's words into ``document``, every size times ``factor``."""
    base = Style(content.family, float(content.size), tuple(content.colour))
    document.clear()
    document.setDefaultFont(font_for(content.family, float(content.size) * factor))
    cursor = QTextCursor(document)
    for n, (align, runs) in enumerate(paragraphs_of(content) or [("left", [])]):
        if n:
            cursor.insertBlock(block_format(align))
        else:
            cursor.setBlockFormat(block_format(align))
        # What is typed into an empty paragraph, or at its start, takes its
        # first run's style, or the box's.
        cursor.setBlockCharFormat(char_format(runs[0][1] if runs else base, factor))
        for text, style in runs:
            cursor.insertText(text, char_format(style, factor))


def apply_spacing(document: QTextDocument) -> None:
    """Make every line of ``document`` `LINE_SPACING` times its natural
    height. Called again as the editor's text changes, so that pasted text
    is spaced as typed text is."""
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    block = QTextBlockFormat()
    block.setLineHeight(LINE_SPACING * 100.0,
                        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    cursor.mergeBlockFormat(block)


def layout(content: Content, width: float, device=None) -> QTextDocument:
    """The box's words laid out ``width`` points wide.

    ``device`` is what the layout is measured against; points by default.
    """
    document = QTextDocument()
    document.documentLayout().setPaintDevice(device or _layout_device())
    document.setDocumentMargin(0)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    fill(document, content)
    document.setTextWidth(max(float(width), 1.0))
    return document


# -- writing /RC --------------------------------------------------------------

def _css_family(family: str) -> str:
    return f"'{family}'" if " " in family else family


def rich_of(document: QTextDocument, content: Content,
            factor: float = 1.0) -> Tuple[Optional[str], str]:
    """``(rich, text)``: the document as `/RC` in the shape Acrobat writes,
    and as plain text for `/Contents`. ``content`` gives the box's default
    style, which goes on the body; sizes are divided by ``factor``. Both
    None and empty for an empty box."""
    base = Style(content.family, float(content.size), tuple(content.colour))
    text = document.toPlainText()
    if not text:
        return None, ""
    body = (f"font-size:{base.size:.1f}pt;text-align:left;"
            f"color:{markup._hex(base.colour)};font-weight:normal;"
            f"font-style:normal;font-family:{_css_family(base.family)};"
            "font-stretch:normal")
    out = [markup.RICH_HEAD.replace("<body ", f'<body style="{body}" ', 1)]
    block = document.begin()
    while block.isValid():
        align = alignment_of(block.blockFormat())
        out.append('<p dir="ltr">')
        wrote = False
        piece = block.begin()
        while not piece.atEnd():
            fragment = piece.fragment()
            if fragment.isValid() and fragment.text():
                style = style_of(fragment.charFormat(), base, factor)
                out.append('<span style="%s">%s</span>' % (
                    _span_style(style, align), escape(fragment.text())))
                wrote = True
            piece += 1
        if not wrote:
            out.append("&#8203;")
        out.append("</p>")
        block = block.next()
    out.append("</body>")
    return "".join(out), text


def _span_style(style: Style, align: str) -> str:
    parts = [f"font-size:{style.size:g}pt" if style.size != int(style.size)
             else f"font-size:{style.size:.1f}pt"]
    if align != "left":
        parts.append(f"text-align:{align}")
    decoration = " ".join(word for word, on in (("word", style.underline),
                                                 ("line-through", style.strike)) if on)
    if decoration:
        parts.append(f"text-decoration:{decoration}")
    if style.shift:
        parts.append("vertical-align:%s" % ("+0.0pt" if style.shift == "super"
                                            else "-0.0pt"))
    parts.append(f"color:{markup._hex(style.colour)}")
    if style.bold:
        parts.append("font-weight:bold")
    if style.italic:
        parts.append("font-style:italic")
    parts.append(f"font-family:{_css_family(style.family)}")
    return ";".join(parts)


# -- measuring and drawing ----------------------------------------------------

def needed_height(content: Content, width: float) -> float:
    """How tall the words are, in points, laid out ``width`` points wide --
    one line's height for an empty box, which still has a line to type on."""
    if content.empty:
        content = content._replace(text=" ", rich=None)
    return layout(content, width).size().height()


def text_form(pdf: pikepdf.Pdf, content: Content,
              width: float) -> Optional[pikepdf.Stream]:
    """The words, as a form XObject ``width`` points wide, their own height
    tall.

    Drawn by `QPdfWriter`, which embeds a subset of each font used and takes
    any language, then lifted out of the page it drew into: the page's
    content becomes the form's, its resources -- the embedded fonts -- the
    form's resources. Its origin is the bottom left of the text, so it is
    placed by its top left less its height. None when there is nothing to
    draw.
    """
    if content.empty:
        return None
    height = needed_height(content, width)
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
        layout(content, width).drawContents(painter)
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


def paint(painter: QPainter, content: Content, width: float,
          clip_height: float) -> None:
    """Paint the words at the painter's origin, in points, as the file draws
    them; the caller scales the painter to the zoom."""
    if content.empty:
        return
    document = layout(content, width)
    document.drawContents(painter, QRectF(0, 0, float(width), float(clip_height)))
