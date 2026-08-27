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

"""Asynchronous page rendering.

QtPdf replaces poppler/cairo.  ``QPdfDocument`` is not thread-safe and not
re-entrant, so the worker opens its *own* handles on the temporary copies rather
than sharing the ones the UI thread uses.  That is safe precisely because those
copies are never written to after import.

Only the visible range plus a margin is ever queued; the queue is dropped and
rebuilt when the viewport moves, so scrolling fast never backs up behind
thumbnails nobody is looking at any more.
"""

import collections
from typing import Dict, Optional

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QMetaObject,
    QMutex,
    QMutexLocker,
    QObject,
    QRect,
    QSize,
    Qt,
    QThread,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

_ROTATIONS = {
    0: QPdfDocumentRenderOptions.Rotation.None_,
    90: QPdfDocumentRenderOptions.Rotation.Clockwise90,
    180: QPdfDocumentRenderOptions.Rotation.Clockwise180,
    270: QPdfDocumentRenderOptions.Rotation.Clockwise270,
}

#: How many pixels' worth of thumbnails to keep before evicting the oldest.
DEFAULT_CACHE_PIXELS = 96 * 1024 * 1024 // 4  # ~96 MB of ARGB32


class MemoryDocument:
    """A QPdfDocument over an in-memory PDF, as produced by ``get_in_memory_pdf``.

    QtPdf reads lazily from the device, so the buffer and the bytes behind it
    must outlive the document -- hence holding all three together. Use as a
    context manager, or call ``close()``.
    """

    def __init__(self, data: bytes):
        self._array = QByteArray(data)
        self._buffer = QBuffer(self._array)
        self._buffer.open(QIODevice.ReadOnly)
        self.document = QPdfDocument(None)
        # The QIODevice overload of load() returns void, unlike the QString one,
        # so the outcome has to be read back off the document afterwards.
        self.document.load(self._buffer)
        self.error = self.document.error()

    @classmethod
    def from_file(cls, path: str, password: str = "") -> "MemoryDocument":
        """The same wrapper over a file on disk, with no bytes in memory.

        For read mode's fast path: when the page list is unmodified there is
        nothing to export, and PDFium reads the file lazily rather than holding
        it. Same interface so callers cannot tell the two apart -- there is no
        buffer here, and ``close()`` closes nothing extra.
        """
        self = cls.__new__(cls)
        self._array = None
        self._buffer = None
        self.document = QPdfDocument(None)
        if password:
            self.document.setPassword(password)
        # The QString overload does return the error, unlike the QIODevice one.
        self.error = self.document.load(path)
        return self

    @property
    def ok(self) -> bool:
        return (self.error == QPdfDocument.Error.None_
                and self.document.status() == QPdfDocument.Status.Ready)

    def page_count(self) -> int:
        return self.document.pageCount() if self.ok else 0

    def close(self):
        self.document.close()
        if self._buffer is not None:
            self._buffer.close()

    def __enter__(self) -> "MemoryDocument":
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


class RenderTask:
    """A self-contained render request.

    Holds plain values copied off the Page rather than the Page itself: the UI
    thread stays free to mutate or delete pages while a render is in flight.
    """

    __slots__ = ("key", "copyname", "password", "npage", "angle", "crop", "hide", "width")

    def __init__(self, key, copyname, password, npage, angle, crop, hide, width):
        self.key = key
        self.copyname = copyname
        self.password = password
        self.npage = npage
        self.angle = angle
        self.crop = crop
        self.hide = hide
        self.width = width


class _RenderWorker(QObject):
    """Lives on the render thread. Owns one QPdfDocument per source file."""

    rendered = Signal(object, QImage)  # key, image

    def __init__(self):
        super().__init__()
        self._docs: Dict[str, QPdfDocument] = {}
        self._mutex = QMutex()
        self._queue = collections.OrderedDict()
        self._stopping = False

    # -- called from the UI thread (guarded by the mutex) -------------------

    def push(self, tasks):
        with QMutexLocker(self._mutex):
            for task in tasks:
                # Re-requesting a key moves it to the back of the queue.
                self._queue.pop(task.key, None)
                self._queue[task.key] = task

    def clear(self):
        with QMutexLocker(self._mutex):
            self._queue.clear()

    def stop(self):
        with QMutexLocker(self._mutex):
            self._stopping = True
            self._queue.clear()

    # -- render thread -----------------------------------------------------

    @Slot()
    def process(self):
        while True:
            with QMutexLocker(self._mutex):
                if self._stopping or not self._queue:
                    return
                _key, task = self._queue.popitem(last=False)
            image = self._render(task)
            if image is not None and not image.isNull():
                self.rendered.emit(task.key, image)

    @Slot()
    def shutdown(self):
        for doc in self._docs.values():
            doc.close()
        self._docs.clear()

    def _document(self, copyname, password) -> Optional[QPdfDocument]:
        doc = self._docs.get(copyname)
        if doc is None:
            doc = QPdfDocument(None)
            if password:
                doc.setPassword(password)
            if doc.load(copyname) != QPdfDocument.Error.None_:
                doc.close()
                return None
            self._docs[copyname] = doc
        return doc

    def _render(self, task: RenderTask) -> Optional[QImage]:
        doc = self._document(task.copyname, task.password)
        if doc is None or not 0 < task.npage <= doc.pageCount():
            return None

        size = doc.pagePointSize(task.npage - 1)
        w, h = size.width(), size.height()
        if task.angle in (90, 270):
            w, h = h, w
        if w <= 0 or h <= 0:
            return None

        crop = task.crop
        visible_w = 1 - crop.left - crop.right
        visible_h = 1 - crop.top - crop.bottom
        if visible_w <= 0 or visible_h <= 0:
            return None
        # Scale so that the *cropped* result comes out at the requested width.
        scale = task.width / (w * visible_w)
        full = QSize(max(1, round(w * scale)), max(1, round(h * scale)))

        options = QPdfDocumentRenderOptions()
        options.setRotation(_ROTATIONS.get(task.angle % 360, _ROTATIONS[0]))
        options.setScaledSize(full)
        # Deliberately no setScaledClipRect: as of Qt 6.11 setting it makes
        # PDFium ignore the rotation, so the page comes back upright inside a
        # sideways frame. Render the whole page and cut the crop out below.

        try:
            image = doc.render(task.npage - 1, full, options)
        except Exception:  # pragma: no cover - defensive, PDFium can be unhappy
            return None
        if image.isNull():
            return None

        if any(crop):
            clip = QRect(
                round(image.width() * crop.left),
                round(image.height() * crop.top),
                max(1, round(image.width() * visible_w)),
                max(1, round(image.height() * visible_h)),
            )
            image = image.copy(clip.intersected(image.rect()))

        self._paint_hidden(image, task.hide)
        return image

    @staticmethod
    def _paint_hidden(image: QImage, hide):
        """Blank out the areas the user asked to hide, as the GTK version does."""
        if not any(hide):
            return
        w, h = image.width(), image.height()
        bands = [
            QRect(0, 0, round(w * hide.left), h),
            QRect(w - round(w * hide.right), 0, round(w * hide.right), h),
            QRect(0, 0, w, round(h * hide.top)),
            QRect(0, h - round(h * hide.bottom), w, round(h * hide.bottom)),
        ]
        painter = QPainter(image)
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(QColor(255, 255, 255))
        for band in bands:
            if band.width() > 0 and band.height() > 0:
                painter.drawRect(band)
        painter.end()


class ThumbnailCache:
    """Insertion-ordered LRU keyed by ``Page.render_key(width)``."""

    def __init__(self, max_pixels=DEFAULT_CACHE_PIXELS):
        self.max_pixels = max_pixels
        self._items = collections.OrderedDict()
        self._pixels = 0

    def get(self, key) -> Optional[QImage]:
        image = self._items.get(key)
        if image is not None:
            self._items.move_to_end(key)
        return image

    def put(self, key, image: QImage):
        if key in self._items:
            self._pixels -= self._items[key].width() * self._items[key].height()
            del self._items[key]
        self._items[key] = image
        self._pixels += image.width() * image.height()
        while self._pixels > self.max_pixels and len(self._items) > 1:
            _k, old = self._items.popitem(last=False)
            self._pixels -= old.width() * old.height()

    def clear(self):
        self._items.clear()
        self._pixels = 0

    def __contains__(self, key):
        return key in self._items

    def __len__(self):
        return len(self._items)


class Renderer(QObject):
    """UI-thread facade over the render thread and the thumbnail cache."""

    #: Emitted once a requested key has a bitmap available in the cache.
    ready = Signal(object)  # key
    #: Emitted when the queue empties (useful for a status indicator).
    idle = Signal()

    def __init__(self, parent=None, max_pixels=DEFAULT_CACHE_PIXELS):
        super().__init__(parent)
        self.cache = ThumbnailCache(max_pixels)
        self._pending = set()
        self._thread = QThread()
        self._thread.setObjectName("pdf-render")
        self._worker = _RenderWorker()
        self._worker.moveToThread(self._thread)
        self._worker.rendered.connect(self._on_rendered)
        self._thread.start()

    def get(self, key) -> Optional[QImage]:
        return self.cache.get(key)

    def request(self, tasks):
        """Queue tasks whose results are not cached yet."""
        wanted = [t for t in tasks if t.key not in self.cache and t.key not in self._pending]
        if not wanted:
            return
        self._pending.update(t.key for t in wanted)
        self._worker.push(wanted)
        self._kick()

    def _kick(self):
        """Wake the render thread; process() drains the queue and returns."""
        QMetaObject.invokeMethod(self._worker, "process", Qt.QueuedConnection)

    def cancel_pending(self):
        """Drop everything not started yet -- called when the viewport moves."""
        self._worker.clear()
        self._pending.clear()

    def invalidate(self):
        """Forget every rendered bitmap (after a zoom change, for instance)."""
        self.cancel_pending()
        self.cache.clear()

    @Slot(object, QImage)
    def _on_rendered(self, key, image):
        self.cache.put(key, image)
        self._pending.discard(key)
        self.ready.emit(key)
        if not self._pending:
            self.idle.emit()

    def shutdown(self):
        """Close every QPdfDocument on the render thread, then join it."""
        self._worker.stop()
        QMetaObject.invokeMethod(self._worker, "shutdown", Qt.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)
