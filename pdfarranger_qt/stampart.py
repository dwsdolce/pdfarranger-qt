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

"""A Stamp's drawing, made here: a PDF of one page, the form `markup`
writes into a file as the stamp's appearance and the canvas draws.

**Words as outlines.** A stamp's words are drawn as shapes, made by Qt from
a font on the computer -- as Acrobat's stamps are, which carry no font,
each language edition having its own files -- so a word in any script is
drawn by every reader, with nothing embedded. That is why this needs Qt
and lives apart from `markup`, which does not.

The presets and text stamps share one design, our own: the words in bold
italic in a rounded frame in their colour, lightly filled. Pictures and
pages from a PDF are taken as they are.
"""

import io
import re
from typing import List, Optional, Tuple

import pikepdf
from PySide6.QtGui import QFont, QPainterPath

from . import markup
from .i18n import gettext_ as _

#: A stamp's height in points, its words' size, and the date line's.
HEIGHT = 30.0
WORD = 17.0
LINE = 6.5
#: How much a date line adds to the height.
DATED = 8.0
#: A picture's longer side when placed by a click, in points.
PICTURE = 120.0

#: The size the outlines are made at, and scaled from: a font's size in
#: pixels is a whole number, and the date line is 6.5.
_MADE_AT = 100


def _font() -> QFont:
    font = QFont("Helvetica")
    font.setStyleHint(QFont.SansSerif)
    font.setBold(True)
    font.setItalic(True)
    font.setPixelSize(_MADE_AT)
    return font


def _outline(text: str) -> QPainterPath:
    path = QPainterPath()
    path.addText(0.0, 0.0, _font(), text)
    return path


def text_width(text: str, size: float) -> float:
    """How wide ``text`` is drawn at ``size`` points."""
    if not text:
        return 0.0
    box = _outline(text).boundingRect()
    return box.right() * size / _MADE_AT


def text_ops(text: str, size: float, x: float, y: float) -> List[str]:
    """``text`` as PDF path operators, its baseline starting at ``x``,
    ``y`` and ``size`` points tall, filled in the colour already set --
    the letters' holes left by the even-odd rule, as Qt makes them."""
    path = _outline(text)
    scale = size / _MADE_AT
    ops = []
    k = 0
    count = path.elementCount()
    while k < count:
        e = path.elementAt(k)
        px, py = x + e.x * scale, y - e.y * scale
        if e.type == QPainterPath.MoveToElement:
            ops.append(f"{px:.3f} {py:.3f} m")
        elif e.type == QPainterPath.LineToElement:
            ops.append(f"{px:.3f} {py:.3f} l")
        elif e.type == QPainterPath.CurveToElement and k + 2 < count:
            c2, end = path.elementAt(k + 1), path.elementAt(k + 2)
            ops.append("{:.3f} {:.3f} {:.3f} {:.3f} {:.3f} {:.3f} c".format(
                px, py, x + c2.x * scale, y - c2.y * scale,
                x + end.x * scale, y - end.y * scale))
            k += 2
        k += 1
    if ops:
        ops.append("f*")
    return ops


def _words(name: str) -> Optional[str]:
    """A preset's word in the language the application is shown in."""
    preset = markup.preset_of(name)
    return _(preset[1]) if preset else None


def framed_size(words: str, line: str = "", shape: str = "frame") -> Tuple[float, float]:
    """The size of a stamp in our frame: 30 tall -- 38 with a date line --
    and as wide as its words, or square for a check mark or a cross."""
    tall = HEIGHT + (DATED if line else 0.0)
    if shape in ("check", "cross"):
        return (tall, tall)
    wide = max(text_width(words, WORD), text_width(line, LINE)) + 24.0
    if shape == "arrow":
        wide += tall * 0.45
    return (round(wide, 2), tall)


def preset_size(name: str, line: str = "") -> Tuple[float, float]:
    preset = markup.preset_of(name)
    if preset is None:
        return (120.0, HEIGHT)
    return framed_size(_words(name), line, preset[3])


def preset_art(name: str, line: str = "") -> Optional[bytes]:
    """A preset's drawing, its word in the application's language."""
    preset = markup.preset_of(name)
    if preset is None:
        return None
    _name, _title, colour, shape = preset
    return framed_art(_words(name), markup.swatch(colour), line, shape)


def framed_art(words: str, colour, line: str = "", shape: str = "frame") -> bytes:
    """A stamp in our design -- a preset's or a text stamp's -- as a PDF of
    one page: a rounded frame 2.5 points wide in ``colour``, filled with it
    at a tenth, the words outlined in bold italic, centred, and under them
    ``line`` when given; the frame's left end an arrow for ``"arrow"``; or
    a check mark or a cross drawn as strokes."""
    wide, tall = framed_size(words, line, shape)
    ink = "{:.4g} {:.4g} {:.4g}".format(*colour[:3])
    tint = tuple(0.9 + 0.1 * v for v in colour[:3])
    lines = [f"{ink} RG", f"{ink} rg"]
    if shape == "check":
        lines += ["3.5 w 1 J 1 j",
                  f"{tall * 0.18:.2f} {tall * 0.5:.2f} m",
                  f"{tall * 0.42:.2f} {tall * 0.22:.2f} l",
                  f"{tall * 0.84:.2f} {tall * 0.82:.2f} l S"]
    elif shape == "cross":
        lines += ["3.5 w 1 J",
                  f"{tall * 0.2:.2f} {tall * 0.2:.2f} m {tall * 0.8:.2f} {tall * 0.8:.2f} l S",
                  f"{tall * 0.2:.2f} {tall * 0.8:.2f} m {tall * 0.8:.2f} {tall * 0.2:.2f} l S"]
    else:
        half, r = 1.25, 5.0
        left = tall * 0.45 if shape == "arrow" else 0.0
        x0, y0, x1, y1 = left + half, half, wide - half, tall - half
        k = r * markup._KAPPA
        path = [f"{x0 + r:.2f} {y0:.2f} m", f"{x1 - r:.2f} {y0:.2f} l",
                f"{x1 - r + k:.2f} {y0:.2f} {x1:.2f} {y0 + r - k:.2f} {x1:.2f} {y0 + r:.2f} c",
                f"{x1:.2f} {y1 - r:.2f} l",
                f"{x1:.2f} {y1 - r + k:.2f} {x1 - r + k:.2f} {y1:.2f} {x1 - r:.2f} {y1:.2f} c"]
        if shape == "arrow":
            path += [f"{x0:.2f} {y1:.2f} l", f"{half:.2f} {tall / 2:.2f} l",
                     f"{x0:.2f} {y0:.2f} l h"]
        else:
            path += [f"{x0 + r:.2f} {y1:.2f} l",
                     f"{x0 + r - k:.2f} {y1:.2f} {x0:.2f} {y1 - r + k:.2f} "
                     f"{x0:.2f} {y1 - r:.2f} c",
                     f"{x0:.2f} {y0 + r:.2f} l",
                     f"{x0:.2f} {y0 + r - k:.2f} {x0 + r - k:.2f} {y0:.2f} "
                     f"{x0 + r:.2f} {y0:.2f} c h"]
        lines += ["{:.4g} {:.4g} {:.4g} rg".format(*tint), "2.5 w 1 j"]
        lines += path + ["B", f"{ink} rg"]
        across = left + (wide - left - text_width(words, WORD)) / 2.0
        base = (tall - WORD * 0.72) / 2.0 + (4.0 if line else 0.0)
        lines += text_ops(words, WORD, across, base)
        if line:
            lines += text_ops(line, LINE,
                              left + (wide - left - text_width(line, LINE)) / 2.0, 5.5)
    return _one_page(("\n".join(lines) + "\n").encode("latin-1"), wide, tall)


def _one_page(content: bytes, wide: float, tall: float, resources=None,
              out=None) -> bytes:
    """``content`` as a form ``wide`` by ``tall``, on a page it fills."""
    out = out or pikepdf.new()
    form = out.make_stream(content)
    form[pikepdf.Name.Type] = pikepdf.Name.XObject
    form[pikepdf.Name.Subtype] = pikepdf.Name.Form
    form[pikepdf.Name.BBox] = pikepdf.Array([0, 0, wide, tall])
    if resources is not None:
        form[pikepdf.Name.Resources] = resources
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page, MediaBox=pikepdf.Array([0, 0, wide, tall]),
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Art=form)),
        Contents=out.make_stream(b"/Art Do"))
    out.pages.append(pikepdf.Page(page))
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


def image_art(path: str) -> Optional[bytes]:
    """A PNG or a JPEG as a stamp's drawing, its longer side 120 points
    and its transparency kept. None if it cannot be read."""
    try:
        from PIL import Image

        picture = Image.open(path)
        picture.load()
    except Exception:  # noqa: BLE001 - a file that is not a picture
        return None
    picture = picture.convert("RGBA")
    width, height = picture.size
    if not width or not height:
        return None
    scale = PICTURE / max(width, height)
    wide, tall = round(width * scale, 2), round(height * scale, 2)
    out = pikepdf.new()
    import zlib

    rgb = picture.convert("RGB").tobytes()
    alpha = picture.getchannel("A")
    image = out.make_stream(zlib.compress(rgb))
    image[pikepdf.Name.Type] = pikepdf.Name.XObject
    image[pikepdf.Name.Subtype] = pikepdf.Name.Image
    image[pikepdf.Name.Width] = width
    image[pikepdf.Name.Height] = height
    image[pikepdf.Name.ColorSpace] = pikepdf.Name.DeviceRGB
    image[pikepdf.Name.BitsPerComponent] = 8
    image[pikepdf.Name.Filter] = pikepdf.Name.FlateDecode
    if alpha.getextrema() != (255, 255):
        mask = out.make_stream(zlib.compress(alpha.tobytes()))
        mask[pikepdf.Name.Type] = pikepdf.Name.XObject
        mask[pikepdf.Name.Subtype] = pikepdf.Name.Image
        mask[pikepdf.Name.Width] = width
        mask[pikepdf.Name.Height] = height
        mask[pikepdf.Name.ColorSpace] = pikepdf.Name.DeviceGray
        mask[pikepdf.Name.BitsPerComponent] = 8
        mask[pikepdf.Name.Filter] = pikepdf.Name.FlateDecode
        image[pikepdf.Name.SMask] = mask
    resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
    return _one_page(f"q {wide:.2f} 0 0 {tall:.2f} 0 0 cm /Im Do Q\n".encode(),
                     wide, tall, resources, out)


#: A page's name in a stamp file's `/Names /Pages` tree: Acrobat's are
#: ``SBApproved=Approved``, the stamp's `/Name` and its title.
_PAGE_NAME = re.compile(r"^#?([^=]+)=(.+)$")


def _drawn_box(path: str, index: int, margin: float = 2.0):
    """The box round what is drawn on page ``index`` of a PDF, in its
    points, a little margin round it -- found by drawing the page once on a
    clear background -- or None for a page with nothing on it."""
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(path)
        page = document[index]
        left, bottom, right, top = page.get_mediabox()
        picture = page.render(scale=1.0, fill_color=(255, 255, 255, 0),
                              draw_annots=False).to_pil().convert("RGBA")
        document.close()
    except Exception:  # noqa: BLE001 - a page we cannot draw is taken whole
        return None
    found = picture.getchannel("A").getbbox()
    if not found:
        return None
    x0, y0, x1, y1 = found
    return [max(left, left + x0 - margin), max(bottom, top - y1 - margin),
            min(right, left + x1 + margin), min(top, top - y0 + margin)]


def pdf_stamps(path: str) -> List[Tuple[str, str, bytes]]:
    """Every page of a PDF as a stamp: ``(name, title, drawing)``, named as
    the file names its pages where it does, else by the file's name and the
    page's number. Empty if it cannot be read."""
    import os

    found = []
    try:
        with pikepdf.open(path) as pdf:
            named = {}
            names = pdf.Root.get(pikepdf.Name.Names)
            tree = names.get(pikepdf.Name.Pages) if names is not None else None

            def leaves(node):
                if node is None:
                    return
                pairs = node.get(pikepdf.Name.Names)
                if pairs is not None:
                    for k in range(0, len(pairs) - 1, 2):
                        try:
                            named[pairs[k + 1].objgen] = str(pairs[k])
                        except Exception:  # noqa: BLE001 - an odd entry
                            continue
                for kid in node.get(pikepdf.Name.Kids) or []:
                    leaves(kid)

            leaves(tree)
            stem = os.path.splitext(os.path.basename(path))[0]
            for number, page in enumerate(pdf.pages, start=1):
                label = named.get(page.obj.objgen, "")
                match = _PAGE_NAME.match(label)
                if match:
                    name, title = match.group(1), match.group(2)
                else:
                    name, title = f"{stem}{number}", f"{stem} {number}"
                name = "/" + (re.sub(r"[^A-Za-z0-9_.-]", "", name)
                              or f"Stamp{number}")
                # **Its art box, where it has one**: Acrobat's stamp files
                # put each stamp on a page the size of a letter, and mark
                # the stamp itself with `/ArtBox`.
                box = None
                for key in (pikepdf.Name.ArtBox, pikepdf.Name.TrimBox):
                    found_box = page.obj.get(key)
                    if found_box is not None and len(found_box) == 4:
                        box = [float(v) for v in found_box]
                        break
                # **Else what is drawn on it**: Acrobat's Standard stamps
                # mark no art box, and taken whole, a stamp in the middle
                # of a letter-sized page was too small to read.
                box = box or _drawn_box(path, number - 1) or [
                    float(v) for v in (page.obj.get(pikepdf.Name.CropBox)
                                       or page.mediabox)]
                wide, tall = box[2] - box[0], box[3] - box[1]
                if wide <= 0 or tall <= 0:
                    continue
                out = pikepdf.new()
                form = out.copy_foreign(page.as_form_xobject())
                form[pikepdf.Name.BBox] = pikepdf.Array(box)
                page_dict = pikepdf.Dictionary(
                    Type=pikepdf.Name.Page,
                    MediaBox=pikepdf.Array(box),
                    Resources=pikepdf.Dictionary(
                        XObject=pikepdf.Dictionary(Art=form)),
                    Contents=out.make_stream(b"/Art Do"))
                out.pages.append(pikepdf.Page(page_dict))
                buffer = io.BytesIO()
                out.save(buffer)
                found.append((name, title, buffer.getvalue()))
    except Exception:  # noqa: BLE001 - a file that is not a PDF
        return []
    return found


def art_size(art: bytes) -> Tuple[float, float]:
    """A stamp's drawing's size in points: its page's."""
    with pikepdf.open(io.BytesIO(art)) as pdf:
        box = [float(v) for v in pdf.pages[0].mediabox]
    return (box[2] - box[0], box[3] - box[1])
