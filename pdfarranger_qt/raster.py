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

"""Things that need pages turned into pixels.

Detecting white borders, exporting images, and rasterising back into a PDF all
work the same way: export the *edited* pages to an in-memory PDF, render them
with QtPdf, then look at or write out the result. That means every edit --
crop, rotation, layers -- is already baked in, which is why this cannot simply
render the source file.

Replaces upstream's ``pageutils.white_borders`` and ``image_exporter``, which
went through poppler and cairo.
"""

import io
import os
from typing import Iterator, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from .core import Page, Sides
from .export import get_in_memory_pdf
from .render import MemoryDocument

#: Grey level at or above which a pixel counts as blank when trimming borders.
WHITE_THRESHOLD = 250
#: One extra pixel is kept on each side, matching the GTK version.
_MARGIN_PX = 1


def _threshold_table(level: int) -> bytes:
    """Map greys to 0xFF (blank) or 0x00 (ink) so scanning can use bytes.find."""
    return bytes(0xFF if value >= level else 0x00 for value in range(256))


def flatten_onto_white(image: QImage) -> QImage:
    """Composite a rendered page onto white.

    QtPdf renders with a transparent background. Left alone that produces
    PNGs with see-through paper, and -- worse -- a greyscale conversion turns
    transparent into *black*, so every pixel reads as ink and border detection
    finds nothing to trim.
    """
    if image.isNull() or not image.hasAlphaChannel():
        return image
    from PySide6.QtGui import QPainter

    flat = QImage(image.size(), QImage.Format_RGB32)
    flat.fill(0xFFFFFFFF)
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    return flat


def render_pages(pages: Sequence[Page], files, ppi: float = 72.0,
                 greyscale: bool = False) -> Iterator[QImage]:
    """Render the edited pages at the given resolution, in order.

    Always flattened onto white -- see ``flatten_onto_white``.
    """
    data = get_in_memory_pdf(list(pages), files)
    with MemoryDocument(data) as doc:
        if not doc.ok:
            return
        scale = ppi / 72.0
        for index in range(doc.page_count()):
            size = doc.document.pagePointSize(index)
            target = QSize(max(1, round(size.width() * scale)),
                           max(1, round(size.height() * scale)))
            image = flatten_onto_white(doc.document.render(index, target))
            if greyscale and not image.isNull():
                image = image.convertToFormat(QImage.Format_Grayscale8)
            yield image


def white_border_crops(pages: Sequence[Page], files,
                       threshold: int = WHITE_THRESHOLD) -> List[Sides]:
    """Find the blank margin around the content of each page.

    Returns one Sides per page, as fractions, ready to hand to
    ``PageListModel.set_margins``. Pages that are entirely blank get no crop --
    trimming a blank page to nothing helps nobody.

    Existing crop and hide are honoured: the search happens inside whatever the
    page already shows, so running this twice does not creep inwards.
    """
    # Scan the pages as they are *displayed*, but without their crop, so the
    # existing crop can be used as the search window like the GTK version does.
    probes = []
    windows = []
    for page in pages:
        probe = page.duplicate()
        windows.append(probe.crop.max(probe.hide))
        probe.crop = Sides()
        probe.hide = Sides()
        probes.append(probe)

    table = _threshold_table(threshold)
    crops: List[Sides] = []
    for image, window in zip(render_pages(probes, files, 72.0, greyscale=True),
                             windows):
        crops.append(_scan_borders(image, window, table))
    # A render failure leaves the remaining pages uncropped rather than wrong.
    while len(crops) < len(pages):
        crops.append(Sides())
    return crops


def _scan_borders(image: QImage, window: Sides, table: bytes) -> Sides:
    if image.isNull():
        return Sides()
    if image.format() != QImage.Format_Grayscale8:
        image = image.convertToFormat(QImage.Format_Grayscale8)
    width, height = image.width(), image.height()
    if width < 3 or height < 3:
        return Sides()
    stride = image.bytesPerLine()
    data = bytes(image.constBits())

    first_col = int(width * window.left)
    last_col = min(width, int(width * (1 - window.right)) + 1)
    first_row = int(height * window.top)
    last_row = min(height, int(height * (1 - window.bottom)) + 1)
    if last_col <= first_col or last_row <= first_row:
        return Sides()

    left, right = width, -1
    top, bottom = height, -1
    for row in range(first_row, last_row):
        start = row * stride
        marked = data[start + first_col:start + last_col].translate(table)
        ink = marked.find(b"\x00")
        if ink < 0:
            continue
        left = min(left, first_col + ink)
        right = max(right, first_col + marked.rfind(b"\x00"))
        top = min(top, row)
        bottom = max(bottom, row)

    if right < 0:
        return Sides()  # nothing but blank: leave the page alone
    return Sides(
        left=max(0.0, (left - _MARGIN_PX) / width),
        right=max(0.0, (width - right - 1 - _MARGIN_PX) / width),
        top=max(0.0, (top - _MARGIN_PX) / height),
        bottom=max(0.0, (height - bottom - 1 - _MARGIN_PX) / height),
    )


def export_images(pages: Sequence[Page], files, paths: Sequence[str],
                  ppi: float = 300.0, greyscale: bool = False,
                  quality: int = -1) -> int:
    """Write one image per page. Returns how many were written."""
    written = 0
    for image, path in zip(render_pages(pages, files, ppi, greyscale), paths):
        if image.isNull():
            continue
        if image.save(path, quality=quality):
            written += 1
    return written


def export_rasterised_pdf(pages: Sequence[Page], files, path: str,
                          ppi: float = 300.0, greyscale: bool = False,
                          image_format: str = "png") -> bool:
    """Render every page to an image and wrap them back into a PDF.

    Flattens everything -- text becomes pixels -- which is the point: it is how
    the GTK version produces a document nothing can reflow or re-extract.
    """
    try:
        import img2pdf
    except ImportError:
        return False

    blobs = []
    sizes = []
    for page, image in zip(pages, render_pages(pages, files, ppi, greyscale)):
        if image.isNull():
            continue
        buffer = io.BytesIO()
        # Round-trip through Pillow so img2pdf sees a format it understands.
        _save_qimage(image, buffer, image_format)
        blobs.append(buffer.getvalue())
        sizes.append(page.size_in_points())
    if not blobs:
        return False

    layout = None
    if sizes:
        width, height = sizes[0]
        layout = img2pdf.get_layout_fun((img2pdf.mm_to_pt(width * 25.4 / 72),
                                         img2pdf.mm_to_pt(height * 25.4 / 72)))
    try:
        data = img2pdf.convert(blobs, layout_fun=layout)
    except Exception:
        data = img2pdf.convert(blobs)
    with open(path, "wb") as handle:
        handle.write(data)
    return True


def _save_qimage(image: QImage, buffer, image_format: str):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    array = QByteArray()
    qbuf = QBuffer(array)
    qbuf.open(QIODevice.WriteOnly)
    image.save(qbuf, image_format.upper())
    qbuf.close()
    buffer.write(bytes(array))


def embedded_images(page: Page, files) -> List["object"]:
    """Return the images embedded in a page, as PIL images.

    Reads the *source* file rather than a render, so the images come out at
    their stored resolution and encoding rather than resampled. Nested images
    inside form XObjects are included, which is where scanners often put them.
    """
    import pikepdf

    copyname, password = files[page.nfile - 1]
    out = []
    with pikepdf.open(copyname, password=password) as pdf:
        if not 0 < page.npage <= len(pdf.pages):
            return out
        target = pikepdf.Page(pdf.pages[page.npage - 1])
        try:
            found = target.get_images()
        except AttributeError:  # pikepdf < 9
            found = target.images
        for _name, obj in found.items():
            try:
                out.append(pikepdf.PdfImage(obj).as_pil_image())
            except Exception:
                continue  # unsupported filter or colourspace; skip it
    return out


def count_embedded_images(page: Page, files) -> int:
    import pikepdf

    copyname, password = files[page.nfile - 1]
    with pikepdf.open(copyname, password=password) as pdf:
        if not 0 < page.npage <= len(pdf.pages):
            return 0
        target = pikepdf.Page(pdf.pages[page.npage - 1])
        try:
            return len(target.get_images())
        except AttributeError:
            return len(target.images)


def explode_to_files(page: Page, files, tmp_dir: str) -> List[str]:
    """Write each embedded image of a page to its own PNG. Returns the paths."""
    import tempfile

    paths = []
    for image in embedded_images(page, files):
        handle, path = tempfile.mkstemp(suffix=".png", dir=tmp_dir)
        os.close(handle)
        if image.mode not in ("RGB", "RGBA", "L", "1"):
            image = image.convert("RGB")
        image.save(path)
        paths.append(path)
    return paths


def pil_to_qimage(image) -> QImage:
    """Convert a PIL image to a QImage, for putting on the clipboard."""
    converted = image.convert("RGBA")
    data = converted.tobytes("raw", "RGBA")
    qimage = QImage(data, converted.width, converted.height, QImage.Format_RGBA8888)
    # tobytes() gives a temporary buffer, so hand back an owned copy.
    return qimage.copy()


def page_text(pages: Sequence[Page], files, index: int = 0) -> str:
    """All the text on one edited page, for Extract > Copy Text."""
    data = get_in_memory_pdf(list(pages), files)
    with MemoryDocument(data) as doc:
        if not doc.ok or not 0 <= index < doc.page_count():
            return ""
        return doc.document.getAllText(index).text()
