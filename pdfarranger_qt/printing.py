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

"""Printing.

Nothing from upstream is reusable here: its ``PrintOperation`` is a
``Gtk.PrintOperation`` driving cairo. Qt has its own print stack, so this is a
replacement built on ``QPrinter`` plus the same in-memory render everything else
in this phase uses -- meaning what prints is the edited document, with crops,
rotations and layers applied.

**The page layout is fixed before painting starts and never touched again.**
Calling ``setPageOrientation()`` between pages makes the native Windows engine
reinitialise its device context mid-job, which can wedge the print job after the
output has already been written. Pages that do not match the sheet are rotated
as *images* instead, which looks the same on paper and never touches the engine.
"""

import os
import sys
import tempfile
import time
from typing import Callable, Optional, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPageLayout, QPainter, QTransform
from PySide6.QtPrintSupport import QPrinter

from .core import Page
from .raster import render_pages

#: Resolution pages are rasterised at before being sent to the printer.
#: Deliberately not the printer's own resolution -- a 600 dpi A4 page is a
#: 35 megapixel image per sheet, and the printer scales it up perfectly well.
DEFAULT_PRINT_DPI = 200

SCALE_FIT = "fit"
SCALE_ACTUAL = "actual"

#: Per-phase print timings are printed to stdout and appended here, always and
#: immediately. Printing is one synchronous call into a platform print engine,
#: so when it appears to hang the only useful record is the one written *before*
#: the phase that hangs -- a log flushed at the end of the job says nothing
#: about a job that never ends.
TIMING_LOG = os.path.join(tempfile.gettempdir(), "pdfarranger-qt-print-timing.log")


class _Timing:
    """Records and reports elapsed time between named phases of a print job."""

    def __init__(self):
        self.start = self.last = time.perf_counter()
        self._emit("--- print job start ---")

    def _emit(self, line: str):
        print(f"[print] {line}", flush=True)
        try:
            with open(TIMING_LOG, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError:
            pass

    def mark(self, label: str):
        now = time.perf_counter()
        self._emit(f"{label}: {now - self.last:.2f}s "
                   f"(total {now - self.start:.2f}s)")
        self.last = now

    def about_to(self, label: str):
        """Record that a phase is *starting*, so a hang leaves a breadcrumb."""
        self._emit(f"starting: {label}")


def dominant_orientation(pages: Sequence[Page]) -> QPageLayout.Orientation:
    """Whichever way up most of the pages are.

    The sheet is set to this once, before printing begins; the minority get
    rotated to fit rather than the sheet being flipped mid-job.
    """
    landscape = sum(1 for p in pages
                    if p.size_in_points().width > p.size_in_points().height)
    return (QPageLayout.Landscape if landscape * 2 > len(pages)
            else QPageLayout.Portrait)


def prepare(printer: QPrinter, pages: Sequence[Page], auto_rotate: bool = True,
            doc_name: Optional[str] = None):
    """Set up the printer *before* any painting starts."""
    if doc_name:
        printer.setDocName(doc_name)
    if auto_rotate and pages:
        printer.setPageOrientation(dominant_orientation(pages))


def print_pages(pages: Sequence[Page], files, printer: QPrinter,
                dpi: int = DEFAULT_PRINT_DPI, scale_mode: str = SCALE_FIT,
                auto_rotate: bool = True,
                progress: Optional[Callable[[int, int], bool]] = None,
                on_finalise: Optional[Callable[[], None]] = None) -> int:
    """Paint pages onto ``printer``. Returns how many were printed.

    ``progress`` is called with ``(done, total)`` after each page and may return
    False to stop early -- printing is synchronous and a long document on a
    slow spooler would otherwise look like a hang.

    ``on_finalise`` is called immediately before ``QPainter.end()``, which is
    where the job is actually handed to the spooler and written. On a native
    Windows printer that single call can take far longer than all the painting
    put together, and it cannot be interrupted or reported on -- so the caller
    gets one chance to say so before the application goes unresponsive.
    """
    pages = list(pages)
    prepare(printer, pages, auto_rotate)

    timer = _Timing()
    painter = QPainter()
    timer.mark("setup")
    if not painter.begin(printer):
        return 0
    timer.mark("QPainter.begin (includes the spooler's save dialog)")
    printed = 0
    try:
        # Smooth scaling costs a great deal on a printer device context and buys
        # nothing: the image is being enlarged, not reduced.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        # The first callback goes here, immediately after begin() returned --
        # which is when the spooler's own save dialog has been answered, and
        # just before the render, the slowest part with no feedback of its own.
        if progress is not None and not progress(0, len(pages)):
            return 0
        sheet_is_landscape = (
            printer.pageLayout().orientation() == QPageLayout.Landscape)
        for image in render_pages(pages, files, dpi):
            if image.isNull():
                continue
            if printed:
                printer.newPage()
            if auto_rotate:
                image = _match_orientation(image, sheet_is_landscape)
            _draw(painter, printer, image, scale_mode)
            printed += 1
            if progress is not None and not progress(printed, len(pages)):
                break
        timer.mark(f"render and draw {printed} pages")
    finally:
        if on_finalise is not None:
            on_finalise()
        timer.mark("finalise callback")
        timer.about_to("QPainter.end (hands the job to the spooler)")
        painter.end()
        timer.mark("QPainter.end (hands the job to the spooler)")
    return printed


def _match_orientation(image, sheet_is_landscape: bool):
    """Turn a page to match the sheet, rather than turning the sheet."""
    page_is_landscape = image.width() > image.height()
    if page_is_landscape == sheet_is_landscape:
        return image
    return image.transformed(QTransform().rotate(90))


def _draw(painter: QPainter, printer: QPrinter, image, scale_mode: str):
    """Centre the page on the sheet, scaled to fit or at its true size."""
    target = QRectF(painter.viewport())
    size = image.size()
    if scale_mode == SCALE_ACTUAL:
        # Map image pixels to physical size via the printer's resolution.
        factor = printer.resolution() / float(DEFAULT_PRINT_DPI)
        size = size * factor
    else:
        size.scale(target.size().toSize(), Qt.KeepAspectRatio)
    rect = QRectF(0, 0, size.width(), size.height())
    rect.moveCenter(target.center())
    painter.drawImage(rect, image)
