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

"""Where the reader's pages sit, and how to get between the two coordinate
spaces they live in.

Phase 7 step 1. `QPdfView` exposes neither text selection nor link
following, and both need to turn a point on screen into a point on a page. So does
scrolling to a bookmark, and so does drawing a search highlight. This is that
mapping, kept apart from the widget that will paint it because it is pure
arithmetic and worth testing as such.

Two spaces:

*Document* pixels -- the whole scrolled column, origin at its top left, y
growing downwards, already multiplied by the zoom. This is what a scroll bar
addresses.

*Page* points -- PDF's own units, origin at the page's top left, y growing
downwards. Note that PDF itself puts the origin at the *bottom* left; QtPdf
already hands out top-left rectangles (`QPdfLinkModel`, `getSelection`), so
matching it is what keeps callers from flipping y twice.

Device pixel ratio is deliberately absent. Everything here is logical pixels;
scaling a bitmap for a retina screen is the renderer's business, and mixing the
two is how a hit test ends up half a page out on an external monitor.
"""

import bisect
import collections
import io
import math
import time
from contextlib import contextmanager
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QIODevice,
    QObject,
    QPointF,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextOption,
)
from PySide6.QtPdf import (
    QPdfDocument,
    QPdfDocumentRenderOptions,
    QPdfLinkModel,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QLineEdit,
    QMenu,
    QStyle,
)

from . import forms as forms_module
from . import markup, noteicons, textbox
from .fieldlayer import AppearanceRenderer
from .i18n import N_
from .i18n import gettext_ as _
from .notepanel import NoteEditor
from .render import ANNOTATIONS, DEFAULT_CACHE_PIXELS, BytesDocument, Renderer
from .textlayer import TextLayer

#: Gap between consecutive pages, and around the column, in logical pixels at
#: zoom 1. Scaled with the zoom so the layout looks the same at every size.
DEFAULT_SPACING = 12.0
DEFAULT_MARGIN = 12.0

#: What a zoom step multiplies by, and how far zoom may go. Matched to the
#: values read mode already used, so the swap does not change how it feels.
ZOOM_STEP = 1.2
ZOOM_LIMITS = (0.1, 8.0)

#: Search highlights. Translucent so the word underneath stays readable, which
#: an opaque box or an outline both spoil in dense text.
SEARCH_HIT = QColor(255, 210, 0, 90)
SEARCH_CURRENT = QColor(255, 145, 0, 150)

#: Selected text. Translucent for the same reason as the search highlights.
SELECTION = QColor(60, 120, 220, 80)
#: The band dragged out by a markup tool. Not `SELECTION`: a selection is
#: something the document has and this is something about to be added to it,
#: and the two are visible at once when a drag starts over selected text.
#: The ring around the field Tab has reached. Drawn rather than relying on
#: the editor appearing, because a tick box gets focus with no editor.
FIELD_FOCUS = QColor(0, 120, 215)
MARKING = QColor(40, 40, 40, 200)
MARKING_FILL = QColor(60, 120, 220, 40)


class FitMode:
    """Whether a zoom was chosen or derived, and from what.

    `QPdfView` had this as ZoomMode and it has to survive a resize: a window
    dragged wider while fit-to-width is on should re-fit, not keep the old
    scale. A plain zoom factor cannot express that, which is why the mode is
    remembered rather than only its result.
    """

    NONE = "none"
    WIDTH = "width"
    PAGE = "page"


class PageLayout:
    """Pages in rows, centred, with a gap between each.

    One page per row ordinarily; two when facing pages are on, which is the only
    thing `QPdfView.PageMode` had no setting for at all. Rows rather than a
    special case, so page rectangles, hit testing and every coordinate mapping
    below work the same either way -- a second layout for facing pages would be
    a second set of geometry bugs, which is the reasoning that kept single-page
    mode out of here too.

    Sizes are in PDF points and may differ per page -- a book with one landscape
    plate in it is the case that breaks a layout assuming a uniform size, and
    the Handbook has several. A row is as tall as its tallest page.

    Row offsets are precomputed and searched with ``bisect``: ``pages_in()``
    runs on every paint and every scroll, and a linear scan over 1590 pages is
    a cost that grows with the document for no reason.
    """

    def __init__(self, sizes: Sequence[QSizeF], zoom: float = 1.0,
                 spacing: float = DEFAULT_SPACING, margin: float = DEFAULT_MARGIN,
                 facing: bool = False, cover: bool = True):
        self._sizes = [QSizeF(s) for s in sizes]
        self._spacing = float(spacing)
        self._margin = float(margin)
        self._facing = bool(facing)
        self._cover = bool(cover)
        self._zoom = 1.0
        self._rows: List[List[int]] = []
        self._row_of: List[int] = []
        self._tops: List[float] = []
        self._height = 0.0
        self._width = 0.0
        self.set_zoom(zoom)

    # -- rows --------------------------------------------------------------

    def _build_rows(self):
        """Group pages into rows: one each, or two when facing.

        ``cover`` puts page 1 alone on the first row, so the spreads that follow
        are (2,3), (4,5) and so on -- which is how a book actually falls open,
        and how every reader that offers this spells it. Without it the pairs
        start at the first page.
        """
        count = len(self._sizes)
        if not self._facing:
            self._rows = [[i] for i in range(count)]
        else:
            self._rows = []
            index = 0
            if self._cover and count:
                self._rows.append([0])
                index = 1
            while index < count:
                self._rows.append([i for i in (index, index + 1) if i < count])
                index += 2
        self._row_of = [0] * count
        for number, row in enumerate(self._rows):
            for page in row:
                self._row_of[page] = number

    def set_facing(self, facing: bool, cover: Optional[bool] = None):
        """Two pages to a row, or one. Re-lays out at the current zoom."""
        self._facing = bool(facing)
        if cover is not None:
            self._cover = bool(cover)
        self.set_zoom(self._zoom)

    @property
    def facing(self) -> bool:
        return self._facing

    @property
    def cover(self) -> bool:
        return self._cover

    def row_of(self, index: int) -> List[int]:
        """The pages sharing a row with ``index``, in order."""
        return list(self._rows[self._row_of[index]])

    # -- geometry ----------------------------------------------------------

    def set_zoom(self, zoom: float):
        """Re-lay out at a new scale. Cheap enough to call while dragging."""
        self._zoom = max(0.01, float(zoom))
        self._build_rows()
        gap = self._spacing * self._zoom
        margin = self._margin * self._zoom
        y = margin
        self._tops = []
        widest = 0.0
        for row in self._rows:
            self._tops.append(y)
            # As tall as the tallest page on it, and as wide as the sum plus the
            # gaps between: a landscape plate facing a portrait one is the case
            # that catches an assumption of uniform size.
            y += self._row_height(row) + gap
            widest = max(widest, self._row_width(row))
        # The trailing gap is not part of the content; the bottom margin is.
        self._height = (y - gap + margin) if self._rows else 0.0
        self._width = widest + 2 * margin

    def _row_height(self, row) -> float:
        return max(self._sizes[i].height() * self._zoom for i in row)

    def _row_width(self, row) -> float:
        gap = self._spacing * self._zoom
        return (sum(self._sizes[i].width() * self._zoom for i in row)
                + gap * (len(row) - 1))

    @property
    def zoom(self) -> float:
        return self._zoom

    def margin_px(self) -> float:
        """The margin at the current zoom, which callers need to place a page."""
        return self._margin * self._zoom

    def page_height(self, index: int):
        """A page's height in its own points, or None if there is no such page."""
        if 0 <= index < len(self._sizes):
            return self._sizes[index].height()
        return None

    @property
    def page_count(self) -> int:
        return len(self._sizes)

    def size_of(self, index: int) -> QSizeF:
        """This page's size in points, as the layout currently believes it."""
        return self._sizes[index]

    def set_size(self, index: int, size: QSizeF):
        """Correct one page's size, for the measuring pass that follows an open.

        Does not re-lay out: a caller correcting a run of pages wants one
        relayout at the end of it, not sixty-four.
        """
        self._sizes[index] = QSizeF(size)

    def content_size(self) -> QSizeF:
        """The whole scrolled column, in document pixels."""
        return QSizeF(self._width, self._height)

    def page_rect(self, index: int) -> QRectF:
        """Where page ``index`` sits in document pixels.

        The row is centred as a group and its pages laid left to right, so a
        spread stays centred even when its two pages differ in width. Pages are
        top-aligned within a row, which is what a book does.
        """
        row_number = self._row_of[index]
        row = self._rows[row_number]
        gap = self._spacing * self._zoom
        x = (self._width - self._row_width(row)) / 2.0
        for page in row:
            w = self._sizes[page].width() * self._zoom
            if page == index:
                h = self._sizes[page].height() * self._zoom
                return QRectF(x, self._tops[row_number], w, h)
            x += w + gap
        raise KeyError(index)  # pragma: no cover - _row_of guarantees the page

    def pages_in(self, top: float, bottom: float) -> List[int]:
        """Indices whose rows intersect the band ``top``..``bottom``, in order.

        Empty when nothing intersects. Touching edges do not count, so a page
        exactly one pixel above the viewport is not rendered. Whole rows: both
        halves of a spread are painted together, which is what makes facing
        pages a layout change and nothing more.
        """
        if not self._rows or bottom <= top:
            return []
        # First row whose bottom edge is past `top`.
        first = max(0, bisect.bisect_right(self._tops, top) - 1)
        while first < len(self._rows) and self._row_bottom(first) <= top:
            first += 1
        # One past the last row whose top edge is before `bottom`.
        last = bisect.bisect_left(self._tops, bottom)
        pages = []
        for number in range(first, max(first, last)):
            pages.extend(self._rows[number])
        return pages

    def _row_bottom(self, number: int) -> float:
        return self._tops[number] + self._row_height(self._rows[number])

    # -- mapping -----------------------------------------------------------

    def page_at(self, point: QPointF) -> Optional[int]:
        """The page under a document-space point, or None for a gap or margin."""
        for index in self.pages_in(point.y(), point.y() + 1e-6):
            if self.page_rect(index).contains(point):
                return index
        return None

    def to_page(self, point: QPointF) -> Optional[Tuple[int, QPointF]]:
        """Document pixels to ``(index, point in page points)``.

        None when the point is not on a page. Callers wanting the nearest page
        instead -- a drag that has wandered into the gap, say -- should use
        ``nearest_page()`` and clamp themselves, because "nearest" means
        different things to a selection and to a click.
        """
        index = self.page_at(point)
        if index is None:
            return None
        return index, self.point_in_page(index, point)

    def point_in_page(self, index: int, point: QPointF) -> QPointF:
        """Document pixels to page points, without asking whether it lands on it."""
        rect = self.page_rect(index)
        return QPointF((point.x() - rect.x()) / self._zoom,
                       (point.y() - rect.y()) / self._zoom)

    def from_page(self, index: int, point: QPointF) -> QPointF:
        """Page points to document pixels. The inverse of ``point_in_page``."""
        rect = self.page_rect(index)
        return QPointF(rect.x() + point.x() * self._zoom,
                       rect.y() + point.y() * self._zoom)

    def rect_from_page(self, index: int, rect: QRectF) -> QRectF:
        """A rectangle in page points to one in document pixels.

        What a link rectangle from `QPdfLinkModel` or a selection bound from
        `getSelection` needs before it can be drawn.
        """
        top_left = self.from_page(index, rect.topLeft())
        return QRectF(top_left,
                      QSizeF(rect.width() * self._zoom, rect.height() * self._zoom))

    def nearest_page(self, y: float) -> int:
        """The page nearest a document-space y, for a point in a gap.

        Never None, so callers scrolling or extending a selection always have
        somewhere to land. Clamps at both ends.
        """
        if not self._rows:
            raise ValueError("no pages")
        number = bisect.bisect_right(self._tops, y) - 1
        number = min(max(number, 0), len(self._rows) - 1)
        return self._rows[number][0]

    # -- fitting -----------------------------------------------------------

    def zoom_for_width(self, viewport_width: float) -> float:
        """The zoom at which the content is exactly ``viewport_width`` wide.

        The margins scale with the zoom, so they belong *inside* the division:
        subtracting them first and dividing by the page alone overshoots, and
        fit-width then raises the horizontal scroll bar it exists to avoid.

        Measured on the widest *row*, so a spread fits rather than each of its
        halves separately -- fitting a page and then showing two of them side by
        side is how facing pages would come out twice as wide as the window.
        """
        if not self._rows:
            return 1.0
        widest = max(
            (sum(self._sizes[i].width() for i in row) + self._spacing * (len(row) - 1))
            for row in self._rows)
        if widest <= 0:
            return 1.0
        return max(0.01, viewport_width / (widest + 2 * self._margin))

    def zoom_for_page(self, viewport: QSizeF, index: int = 0) -> float:
        """The zoom at which one whole row fits, both dimensions.

        The row rather than the page, for the same reason as ``zoom_for_width``:
        with facing pages on, "fit one page" means the spread you are looking
        at, not half of it.

        Margins inside the division, as above. The vertical margin is counted
        once above and once below, matching the content height for one row.
        """
        if not self._rows:
            return 1.0
        row = self._rows[self._row_of[index]]
        width = (sum(self._sizes[i].width() for i in row)
                 + self._spacing * (len(row) - 1))
        height = max(self._sizes[i].height() for i in row)
        if width <= 0 or height <= 0:
            return 1.0
        return max(0.01, min(viewport.width() / (width + 2 * self._margin),
                             viewport.height() / (height + 2 * self._margin)))


def sizes_from_document(document, count: Optional[int] = None) -> List[QSizeF]:
    """Page sizes off a `QPdfDocument`, in points.

    Read once and kept: the layout consults every size on each zoom change.

    Not cheap, which is the thing the comment here used to get wrong. It is
    1.8 ms a page on a 1,590-page book -- 2.9 seconds, against 0.7 s to parse
    the file and 20 ms to render a page -- so asking for every size before
    showing anything is most of what opening a large document costs. See
    `provisional_sizes`.
    """
    n = document.pageCount() if count is None else count
    return [document.pagePointSize(i) for i in range(n)]


def provisional_sizes(document) -> List[QSizeF]:
    """Every page the size of the first, pending the real measurements.

    Enough to lay out and paint immediately. A book is nearly but not quite
    uniform -- 1,550 of the Handbook's 1,590 pages share one size, and the
    other 40 are the plates -- so the guess is right for most of the document
    and wrong in exactly the places a layout would notice. `PageCanvas` then
    measures the rest a chunk at a time and corrects itself.
    """
    count = document.pageCount()
    if count <= 0:
        return []
    first = document.pagePointSize(0)
    return [QSizeF(first) for _ in range(count)]


def _is_finite_point(point) -> bool:
    """Whether a point is usable arithmetic rather than NaN or infinity.

    QtPdf reports an unparsable destination as NaN and says so in a warning. NaN
    compares false against every value, zero included, so it passes any "is this
    the default?" test and only fails later, in whatever first tries to make an
    integer of it.
    """
    return all(math.isfinite(v) for v in (point.x(), point.y()))


class PageText:
    """Where the text on a page is, so a stray click can find it.

    `QPdfDocument.getSelection` wants both ends to land on an actual glyph: the
    exact box of a line selects it, while a generous rectangle around the same
    line selects nothing at all. Nobody drags that precisely, so a point is
    snapped onto the nearest run of text first.

    The runs come from one `getSelectionAtIndex` over the whole page -- its
    `bounds()` is a polygon per run, 219 of them on a dense Handbook page
    against 5909 characters -- and are cached, because a drag asks on every
    mouse move.
    """

    #: Larger than any page's character count; getSelectionAtIndex clamps.
    ALL = 10_000_000

    def __init__(self, document=None):
        self._document = document
        self._runs: dict = {}
        self._texts: dict = {}

    def set_document(self, document):
        self._document = document
        self._runs.clear()
        self._texts.clear()

    def runs(self, page: int) -> List[QRectF]:
        """Bounding boxes of every run of text on ``page``."""
        cached = self._runs.get(page)
        if cached is not None:
            return cached
        boxes: List[QRectF] = []
        if self._document is not None:
            try:
                selection = self._document.getSelectionAtIndex(page, 0, self.ALL)
                boxes = [poly.boundingRect() for poly in selection.bounds()]
            except Exception:  # pragma: no cover - PDFium can be unhappy
                boxes = []
        self._runs[page] = boxes
        return boxes

    def snap(self, page: int, point: QPointF) -> Optional[QPointF]:
        """``point`` moved just inside the nearest run, or None if no text.

        Half a point inside rather than on the edge: a boundary coordinate is
        exactly the case getSelection rejects.
        """
        boxes = self.runs(page)
        if not boxes:
            return None
        best, best_distance = None, None
        for box in boxes:
            dx = max(box.left() - point.x(), 0.0, point.x() - box.right())
            dy = max(box.top() - point.y(), 0.0, point.y() - box.bottom())
            distance = dx * dx + dy * dy
            if best_distance is None or distance < best_distance:
                best, best_distance = box, distance
        return QPointF(min(max(point.x(), best.left() + 0.5), best.right() - 0.5),
                       min(max(point.y(), best.top() + 0.5), best.bottom() - 0.5))

    def contains_text(self, page: int, point: QPointF) -> bool:
        """Whether the point is actually on text, for the I-beam cursor."""
        return any(box.contains(point) for box in self.runs(page))

    def text(self, page: int) -> str:
        """The whole page's text, in the index space `getSelection` reports.

        Cached separately from the runs, and only filled when something asks --
        which is the click gestures, never a drag. The runs cache is populated
        by every drag across every page it passes, and carrying 5909 characters
        a page along with it would cost about 9 MB on the Handbook to serve
        features that only ever look at one page at a time.
        """
        cached = self._texts.get(page)
        if cached is not None:
            return cached
        text = ""
        if self._document is not None:
            try:
                text = self._document.getSelectionAtIndex(page, 0, self.ALL).text()
            except Exception:  # pragma: no cover - PDFium can be unhappy
                text = ""
        self._texts[page] = text
        return text

    @staticmethod
    def word_character(character: str) -> bool:
        """What counts as part of a word.

        Alphanumerics and the underscore, which is what every text view does. A
        hyphen breaks a word, so double-clicking in "pdfarranger-qt" gets you
        one half of it -- deliberate, because the other rule makes selecting one
        half of a hyphenated compound impossible.
        """
        return character.isalnum() or character == "_"

    @staticmethod
    def line_bounds(text: str, index: int):
        """``(start, end)`` of the line holding ``index``, newline excluded.

        Lines come from the page's own text, which arrives with its breaks in
        it, so moving up and down needs no geometry at all -- the column is an
        offset within the line, exactly as a text editor treats a plain string.

        That also means a line is whatever the *document's* text order says it
        is. On a multi-column page that can walk column 1, then column 3, then
        column 2; Acrobat does the same, because the stream really is ordered
        that way.
        """
        if not text:
            return None
        here = min(max(index, 0), len(text))
        start = text.rfind("\n", 0, here) + 1
        end = text.find("\n", here)
        if end == -1:
            end = len(text)
        # A line ending "\r\n" leaves the carriage return on the near side.
        if end > start and text[end - 1] == "\r":
            end -= 1
        return start, end

    @classmethod
    def word_bounds(cls, text: str, index: int):
        """``(start, end)`` of the word around ``index``, or None if there is none.

        ``index`` is where the click landed, to within a character: PDFium
        reports how many characters lie before a point, and whether that is the
        glyph under the cursor or the one before it depends on where in the
        glyph the pointer sat. So both are tried, word first -- which makes the
        boundary cases behave: clicking the first letter of a word finds the
        word rather than the space in front of it, and clicking the last letter
        finds it rather than the space behind.

        A click that is on no word at all selects the single character it hit,
        the way a text view does. Nothing at all would be indistinguishable
        from a double-click that failed.
        """
        if not text:
            return None
        here = min(max(index, 0), len(text) - 1)
        if not cls.word_character(text[here]) and here > 0 \
                and cls.word_character(text[here - 1]):
            here -= 1
        if not cls.word_character(text[here]):
            return here, here + 1
        start = here
        while start > 0 and cls.word_character(text[start - 1]):
            start -= 1
        end = here + 1
        while end < len(text) and cls.word_character(text[end]):
            end += 1
        return start, end


class _ThisThread:
    """A document provider that hands back one already-open document.

    `PageRenderTask.render` asks a provider for the document, because the
    worker parses its own from bytes. Rendering inline needs the opposite:
    the document already on this thread, and no parse at all.
    """

    __slots__ = ("_document",)

    def __init__(self, document):
        self._document = document

    def get(self, *_args):
        return self._document


class PageRenderTask:
    """One page of the reader's document at one size.

    No angle, crop or hide: the reader shows an export with the edits already
    applied, so there is nothing left to apply. That asymmetry with the
    grid's RenderTask is why the worker asks the *task* to render itself.
    """

    __slots__ = ("key", "page", "size")

    def __init__(self, key, page: int, size: QSize):
        self.key = key
        self.page = page
        self.size = size

    def render(self, documents) -> Optional[QImage]:
        document = documents.get()
        if document is None or not 0 <= self.page < document.pageCount():
            return None
        options = QPdfDocumentRenderOptions()
        options.setScaledSize(self.size)
        options.setRenderFlags(ANNOTATIONS)
        try:
            return document.render(self.page, self.size, options)
        except Exception:  # pragma: no cover - PDFium can be unhappy
            return None


class AsynchronousPages(QObject):
    """The reader's bitmaps, rendered off the GUI thread, with placeholders.

    Replaces the synchronous source step 1 left as a seam. A quarter of the
    Handbook's pages miss a 60 Hz frame at 2000 px and the
    worst takes 247 ms, so rendering where the painting happens stutters
    visibly. `page_image` therefore never blocks -- it answers with what it has
    and asks for what it does not.

    **A placeholder can only be a bitmap that already exists.** Rendering a
    quick small one is not an option: the expensive pages are bound by parsing
    and image decoding, not rasterising, so the Handbook's worst page costs
    248 ms at 1000 px and 247 ms at 2000 px. What is available is the same page
    at a *different* zoom, still in the cache, scaled to fit -- ugly, instant,
    and the right shape, which is all a placeholder has to be.

    The budget is a number of pages at the current size rather than a fixed
    pixel count, because per-page cost swings two orders of magnitude across the
    zoom range.
    """

    #: A page arrived; the canvas should repaint.
    page_ready = Signal(int)

    #: How many rows ahead and behind to render before anyone asks.
    PREFETCH_ROWS = 2
    #: Width of the low-resolution copy kept for every page ever rendered.
    #: 120 px is 75 KB a page, so the whole 1590-page Handbook is 116 MB --
    #: against 21 MB for a *single* page at 2000 px.
    PROXY_WIDTH = 120
    #: Proxies to keep. Enough for a large book; they are small enough that the
    #: number hardly matters, and a bound is better than none.
    PROXY_PAGES = 3000
    #: Spare room in the cache beyond what is visible and prefetched, so a
    #: bitmap is never evicted by the very request that will need it next.
    SLACK = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._documents = BytesDocument()
        # A real budget from the start. It was 1 pixel, on the theory that
        # prefetch() would size it properly on the first paint -- but that
        # leaves every render before the first paint evicted the instant it
        # arrives, and a source used without painting with no cache at all.
        # prefetch() still narrows this to a number of pages at the current
        # zoom; this is only the floor.
        self._renderer = Renderer(self, max_pixels=DEFAULT_CACHE_PIXELS,
                                  documents=self._documents, name="pdf-reader")
        self._renderer.ready.connect(self._arrived)
        self._sizes = {}          # page -> the size most recently asked for
        #: The GUI thread's document, for rendering a page while painting it.
        self._document = None
        #: Pages that took longer than `INLINE_BUDGET_MS` when rendered here,
        #: and go back to the worker next time rather than stalling a scroll.
        self._slow = set()
        #: Low-resolution copies, kept far longer than the full-size ones.
        #: Rendering small is not cheaper -- 40 pages cost 419 ms at 150 px and
        #: 436 ms at 300 px, because the time goes into parsing the page rather
        #: than rasterising it -- but *keeping* small is enormously cheaper, and
        #: that is the lever. These are now made by shrinking the bitmap a paint
        #: just produced rather than by a second render, and they stand in for
        #: the pages too slow to render inline.
        self._proxies: collections.OrderedDict = collections.OrderedDict()
        #: Pages whose marks have been changed, as a one-page document each.
        #: `{index: (bytes, QPdfDocument or None)}`.
        #:
        #: A change to a mark the file brought cannot be drawn over the page,
        #: because the mark is already *in* the bitmap: PDFium renders a page
        #: and its annotations together, so the old colour is underneath and
        #: nothing painted on top will hide it. The page has to be rendered
        #: again from a document that has the change in it.
        #:
        #: One page at a time rather than the whole document, which is the
        #: difference between imperceptible and not. Measured on the 1590-page
        #: Handbook: patching and saving the whole file to change one colour
        #: costs 1180 ms, while lifting that single page into a document of
        #: its own, patching it and saving costs 1.1 to 6.5 ms.
        self._edited: dict = {}
        #: What has been rendered for those pages, by `(index, w, h)`. Kept
        #: here rather than in the shared cache because the worker never sees
        #: these documents, and because an edit has to drop exactly one page's
        #: bitmaps without disturbing the pages around it.
        self._edited_images: dict = {}

    def set_edited(self, index: int, data: Optional[bytes]) -> None:
        """Render ``index`` from ``data``, a one-page document, or stop.

        Passing None puts the page back to being rendered from the document
        everything else comes from.
        """
        if data is None:
            self._edited.pop(index, None)
        else:
            self._edited[index] = (data, None)
        for key in [k for k in self._edited_images if k[0] == index]:
            del self._edited_images[key]

    def clear_edited(self) -> None:
        self._edited.clear()
        self._edited_images.clear()

    def _edited_image(self, index: int, size: QSize) -> Optional[QImage]:
        """The bitmap for an edited page, rendered from its own document."""
        held = self._edited.get(index)
        if held is None:
            return None
        key = (index, size.width(), size.height())
        image = self._edited_images.get(key)
        if image is not None:
            return image
        data, document = held
        if document is None:
            document = QPdfDocument()
            array = QByteArray(data)
            buffer = QBuffer(array)
            buffer.open(QIODevice.ReadOnly)
            # The device overload returns nothing -- only `load(str)` returns
            # an error -- so the document has to be asked afterwards. Checking
            # the return value treated every successful load as a failure and
            # silently dropped the page back to its old colour.
            document.load(buffer)
            if document.pageCount() < 1:
                self._edited.pop(index, None)
                return None
            # The buffer and the array have to outlive the document, which
            # reads from them lazily; QPdfDocument does not take a copy.
            self._edited[index] = (data, (document, array, buffer))
        else:
            document = document[0]
        image = PageRenderTask((0, size.width(), size.height()), 0, size) \
            .render(_ThisThread(document))
        if image is None or image.isNull():
            return None
        self._edited_images[key] = image
        return image

    def set_document(self, document, data: Optional[bytes] = None):
        """Point at a new document. ``data`` is what the render thread parses.

        ``document`` is the GUI thread's own copy, kept here so a page that is
        being painted *now* can be rendered inline rather than queued. Same
        object the search and the outline use; no second parse.
        """
        self._renderer.invalidate()
        self._sizes.clear()
        self._proxies.clear()
        self._slow.clear()
        self._document = document
        self._documents.set_data(data)
        self.clear_edited()

    def clear(self):
        self._renderer.invalidate()
        self._sizes.clear()
        self._proxies.clear()

    def shutdown(self):
        self._renderer.shutdown()

    def _arrived(self, key):
        page, width, _height = key
        if width == self.PROXY_WIDTH:
            image = self._renderer.get(key)
            if image is not None:
                self._keep_proxy(page, image)
            # Out of the shared cache once it is safely kept. That cache is
            # sized in full-size pages and holds only a handful of them, so a
            # proxy landing in it evicts a page somebody is looking at -- which
            # is exactly what happened the first time this was wired up.
            self._renderer.cache.discard(key)
        self.page_ready.emit(page)

    def _keep_proxy(self, page: int, image):
        self._proxies.pop(page, None)
        self._proxies[page] = image
        while len(self._proxies) > self.PROXY_PAGES:
            self._proxies.popitem(last=False)

    def page_image(self, index: int, size: QSize,
                   settled: bool = True) -> Optional[QImage]:
        """The page at this size: rendered here if it can be, else a stand-in.

        This used to never render, only queue. The round trip costs a median
        of 35 ms -- the render plus the queue, the thread hop, the signal and
        a second paint -- so every page not already cached was painted blank
        or blurred first and corrected two to five frames later. That is the
        white-then-fills-in a scrollbar drag shows, and the low-resolution
        proxy is the same thing on a page visited before.

        The asynchronous design was right when a page cost 134 ms. Measured on
        the same book today it costs 12 to 33 ms, median 20, because the pages
        that were expensive were full of the CMYK and indexed images that are
        now compressed. One dropped frame beats five blank ones, so a page
        being painted now is rendered now.

        The worker keeps prefetch, proxies, and any page that proves too slow
        to do inline.
        """
        if size.width() <= 0 or size.height() <= 0:
            return None
        edited = self._edited_image(index, size)
        if edited is not None:
            return edited
        key = (index, size.width(), size.height())
        image = self._renderer.get(key)
        if image is not None:
            return image
        self._sizes[index] = size
        aspect = size.height() / max(1, size.width())

        image = self._render_now(index, size, settled)
        if image is not None:
            self._renderer.cache.put(key, image)
            self._proxy_from(index, image)
            return image

        # Urgent: this page is being painted right now.
        self._request(index, size, urgent=True)
        self._request_proxy(index, aspect)
        return self._stand_in(index)

    #: Longer than this and a page is left to the worker from then on. Two
    #: frames at 60 Hz: enough for all but the heaviest pages measured, and
    #: short enough that one of them cannot be felt as a stutter.
    INLINE_BUDGET_MS = 33.0

    def _render_now(self, index: int, size: QSize,
                    settled: bool = True) -> Optional[QImage]:
        """Render on this thread, or None to let the worker have it.

        The same `PageRenderTask` the worker runs, against the GUI thread's
        document: identical pixels for an identical key, which matters because
        the two share one cache.

        ``settled`` is whether the viewport has stopped. The budget applies
        only while it is moving: the cover of a book measured 63 ms and its
        first page 127 ms, so the budget alone sent exactly the two pages a
        reader returns to most back to the worker for ever, and jumping to the
        front of the document faded in rather than appearing.
        """
        if self._document is None:
            return None
        if index in self._slow and not settled:
            return None
        key = (index, size.width(), size.height())
        started = time.perf_counter()
        image = PageRenderTask(key, index, size).render(_ThisThread(self._document))
        if image is None or image.isNull():
            return None
        if (time.perf_counter() - started) * 1000 > self.INLINE_BUDGET_MS:
            # Keep this one -- it is already paid for -- but do not stall a
            # scroll on it again once it has been evicted.
            self._slow.add(index)
        return image

    def _stand_in(self, index: int) -> Optional[QImage]:
        """The best bitmap we already hold for this page, at any size.

        The full-size cache first, since downscaling a page rendered for a
        bigger zoom beats upscaling anything; then the proxy, which is where a
        page that has been visited once and evicted since will be found. The
        proxy is why scrolling back over a chapter you have read does not blank
        the way it did.
        """
        best = None
        for (page, width, _height), image in self._renderer.cache.items():
            if page != index:
                continue
            if best is None or width > best[0]:
                best = (width, image)
        if best is not None:
            return best[1]
        return self._proxies.get(index)

    def _request(self, index: int, size: QSize, urgent: bool = False):
        self._renderer.request(
            [PageRenderTask((index, size.width(), size.height()), index, size)],
            urgent=urgent)

    def _proxy_from(self, index: int, image: QImage):
        """Shrink the bitmap we just made instead of rendering it again.

        Asking the worker for the proxy of a page rendered inline costs more
        than the proxy is worth: the two run at once and contend for the CPU,
        which measured as *double* the inline paint -- a median of 50 ms
        against 24 for the same pages with the proxy suppressed. Scaling an
        image already in hand is a fraction of a millisecond and gives the
        same picture.
        """
        if index in self._proxies:
            return
        self._keep_proxy(index, image.scaledToWidth(self.PROXY_WIDTH,
                                                    Qt.SmoothTransformation))

    def _request_proxy(self, index: int, aspect: float):
        """Queue the low-resolution copy, if this page has never had one.

        Never urgent: it exists so a *future* visit does not blank, and jumping
        the queue with it would delay the page being looked at now.
        """
        if index in self._proxies:
            return
        height = max(1, int(round(self.PROXY_WIDTH * aspect)))
        size = QSize(self.PROXY_WIDTH, height)
        self._renderer.request(
            [PageRenderTask((index, size.width(), size.height()), index, size)])

    def prefetch(self, pages, size: QSize, keep: int):
        """Render ``pages`` before they are asked for, and hold ``keep`` of them.

        The only mitigation there is: the slow pages cannot be made faster, so
        the answer is to have started them earlier. At ~250 ms for a heavy page,
        a couple of screenfuls either side buys about two seconds of lead at
        reading pace.

        ``keep`` comes from the caller because only the layout knows how many
        pages are on screen at once. Sizing it as a constant is what made facing
        pages flicker: four pages visible and four prefetched against a budget
        of five meant every paint evicted something still on screen, re-rendered
        it, and evicted its neighbour in turn.
        """
        if size.width() <= 0 or size.height() <= 0:
            return
        pixels = size.width() * size.height()
        self._renderer.set_budget(max(1, pixels * max(1, keep)))
        aspect = size.height() / max(1, size.width())
        for index in pages:
            key = (index, size.width(), size.height())
            if self._renderer.get(key) is None:
                self._request(index, size)
            self._request_proxy(index, aspect)


class PageCanvas(QAbstractScrollArea):
    """The reader's page view: a scrolling column that we own.

    Phase 7 step 1. Replaces `QPdfView`, which is a closed widget exposing
    neither selection nor links and no way to control what it caches. The
    engine underneath is unchanged -- this is a widget, not a renderer.

    Everything here is a thin layer over `PageLayout`. The widget's job is to
    turn a scroll position into a band of document pixels, ask the layout which
    pages are in it, and paint them; and to convert a point under the mouse into
    document space so the layout can say which page it landed on. Steps 3 and 4
    build links and selection on that second half.
    """

    #: The page occupying most of the viewport changed.
    current_page_changed = Signal(int)
    #: The text selection appeared or vanished, so a Copy command can follow it.
    selection_changed = Signal(bool)
    #: Whether the selection now runs across a page break. Such a selection
    #: cannot be marked: it follows the order the file stores its text in,
    #: so it takes in the footer, page number and header between, often off
    #: screen, and a mark made from it would cover text nobody meant to mark.
    selection_crosses_pages = Signal(bool)
    #: A link to somewhere outside the document was activated. Not opened here:
    #: what a PDF may ask the desktop to do is a policy question, and a widget
    #: is the wrong place to decide it. See ReaderView.
    external_link_activated = Signal(QUrl)
    #: A form field was pressed. Not acted on here: changing a value is a
    #: document edit, which belongs on the undo stack the window owns.
    field_pressed = Signal(object)
    #: A text field was typed into and the editor closed: ``(field, text)``.
    field_edited = Signal(object, str)

    #: A fillable field was clicked in a document that will not take the edit.
    field_refused = Signal(object)
    #: The pointer's job changed: the new tool's name.
    tool_changed = Signal(str)
    #: A markup gesture finished: ``(tool, page, rects)``, already in the
    #: page's own space. Always a *list*: an area tool sends the one it dragged
    #: out, a text tool one rectangle per run of text it covered. The canvas
    #: reports the gesture and keeps none of it.
    mark_drawn = Signal(str, int, object)
    #: A Pencil or a polygon being made has gained or lost a stroke or a
    #: point, or been finished or thrown away: whether Undo has something
    #: of its own to take back has changed.
    drawing_changed = Signal()
    #: *Properties...* in the menu of a mark being made: the armed tool's
    #: form, since there is no mark yet to have one.
    tool_form_wanted = Signal()
    #: A callout's box or leader reshaped by a handle, or its box dragged
    #: alone: ``(page, mark, box, points)``, both in the mark's own space.
    callout_reshaped = Signal(int, object, object, object)
    #: A Stamp resized by a corner: ``(page, mark, rect)``. Apart from a
    #: Scalable Comment's reshape, which carries an angle, and a new angle
    #: means a new drawing -- a Stamp keeps its own.
    stamp_resized = Signal(int, object, object)
    #: A gesture, as ``(tool, [(page, quads), ...])``. Text is marked one
    #: page at a time, so the list holds one page; it is a list so that a
    #: gesture is always one step to undo, however much it covered.
    marks_drawn = Signal(str, object)
    #: A note's text was typed and its editor closed: ``(page, which, text)``.
    #: The note is named by its *position* in that page's marks rather than by
    #: the object, for the reason `structure._resolve` records positions: an
    #: undo rebuilds every mark with `duplicate()`, so a reference held across
    #: one points at an annotation the document no longer has.
    #: Whether a mark is selected. The mark itself is not sent: what is
    #: selected is the canvas's own state and `selected_mark` answers for it,
    #: while this is what the buttons beside it listen to.
    mark_selected = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = PageLayout([])
        self._pages = AsynchronousPages(self)
        self._pages.page_ready.connect(self._page_arrived)
        self._current = -1
        self._fit = FitMode.NONE
        self._continuous = True
        self._single = 0
        self._search = None
        self._search_result = -1
        self._links = QPdfLinkModel(self)
        self._links_page = -1
        #: Handed to the link model in place of None when there is no document.
        #: `QPdfLinkModel.setDocument(None)` disconnects from the old document
        #: and then connects to the null one without checking, so Qt prints
        #: "QObject::connect(QPdfDocument, QPdfLinkModel): invalid nullptr
        #: parameter" every time a document is closed. An empty document is a
        #: real object with no pages: the model has nothing to find, `linkAt`
        #: returns an invalid link, and nothing is left pointing at the
        #: document that has just been closed.
        self._no_document = QPdfDocument(self)
        #: The document's form fields, for hit testing and for the layer that
        #: draws them. Set by the reader, which is the only thing that knows
        #: which document is showing.
        self._fields = None
        #: True while a step is in progress. Closing a field's editor makes
        #: Qt run focus traversal, which comes straight back here, so one Tab
        #: stepped four fields without this.
        self._stepping = False
        #: The field with keyboard focus, or None. Separate from `_editing`,
        #: which is a text field's editor: a tick box can be focused with no
        #: editor over it, and before this there was no way to be *at* one.
        self._focused = None
        #: What the pointer does. See `set_tool`.
        self._tool = self.SELECT
        #: ``(start, current)`` in viewport points while a mark is being drawn.
        self._marking = None
        #: Whether a shape is being made by clicks rather than a drag: the
        #: first click has landed and the band follows the pointer to the
        #: second.
        self._clicked_shape = False
        #: ``(mark, points)`` while one of a line's handles is dragged.
        self._line_shaping = None
        #: ``(page, [viewport points], pointer)`` while a polygon, a cloud or
        #: a polyline is being made, a point at each press.
        self._poly_drawing = None
        #: ``(mark, points)`` and ``(page, mark, which)`` while one of a
        #: polygon's or a polyline's vertices is dragged.
        self._poly_shaping = None
        self._dragging_vertex = None
        #: ``{"page", "strokes", "live", "last"}`` while a Pencil is being
        #: drawn: its strokes so far, each a list of points in the space a
        #: mark made here keeps, whether the button is down on the last of
        #: them, and where the pointer last added one.
        self._ink_drawing = None
        #: ``(page, mark, which, fixed)`` while a Pencil's corner is
        #: dragged, ``fixed`` the opposite corner of what it draws and the
        #: way from it to the corner held; the points go in `_poly_shaping`.
        self._ink_resizing = None
        #: ``(mark, box, points)`` while a callout's handle or box is
        #: dragged, and the drag itself: ``(page, mark, which, box, points,
        #: start)`` -- ``which`` a box handle 0 to 7, 8 the tip, 9 the knee,
        #: or "box" for the box dragged alone.
        self._callout_shaping = None
        self._callout_drag = None
        #: ``(page, mark, fixed, way)`` while a Stamp's corner is dragged:
        #: the opposite corner, which holds still, and the way from it to
        #: the corner held. The rectangle goes in `_shaping`.
        self._stamp_resizing = None
        #: A Stamp's drawing rendered at a size, ``{(uid, w, h): QImage}``.
        self._art_images = {}
        #: The line a mark made with a tool would have now, as ``(thickness,
        #: opacity)``, asked of the window as `mark_colour` is.
        self.mark_stroke = None
        #: The size in points of the stamp the palette has picked, asked of
        #: the window, for a drag to keep its proportions.
        self.stamp_size = None
        #: The picked stamp's drawing, a PDF of one page, asked of the
        #: window, to show under the pointer before it is placed.
        self.stamp_art = None
        #: Where the pointer is over the page while the Stamps palette tool
        #: is armed, for the stamp drawn under it; None off the canvas.
        self._stamp_hover = None
        #: Where the last context menu was asked for, for the entries that
        #: depend on it: Insert Vertex goes where it was clicked.
        self._menu_point = None
        #: ``(page, mark, which)`` for the handle being dragged.
        self._dragging_line_end = None
        #: One `forms.displayed_box` per page, for placing a mark. Plain data
        #: and separate from the field map, because a page with no widgets
        #: still has a box and a mark can be placed on it.
        self._boxes = []
        #: One resize factor per page, for the same reason and from a
        #: different place: the boxes come from the document being shown, and
        #: the scale is the *model's* -- the document on screen has it applied
        #: already, so nothing in the file can say what it was. See
        #: `set_page_scales`.
        self._scales = []
        #: Renders and caches one widget's appearance. Lives as long as the
        #: canvas: its cache is keyed by appearance, so it is worth keeping
        #: across documents that share one.
        self._appearances = AppearanceRenderer()
        #: Given a Field, what the application says it holds, or None to use
        #: what the document says. Set by the window, which owns the edits.
        self.field_values = None
        #: Set by the window: the marks on a page index, as `markup`
        #: annotations in the page's own space. Drawn here rather than waiting
        #: for the document to be exported again, for the same reason a tick
        #: is a repaint: a rebuild costs 682 ms and loses the reader's place.
        self.marks = None
        #: Set by the window: whether this field's document refuses to be
        #: filled in. Asked here rather than in the handler because the canvas
        #: decides whether to put an editor over the field, and an editor that
        #: opens and then refuses to commit is a worse answer than one that
        #: never opens.
        self.field_locked = None
        #: ``(field, editor)`` while a text field is being typed into.
        self._editing = None

        self._tooltip = ""
        self._text = PageText()
        self._document = None
        #: (page, point-in-page) where the current drag started, and where a
        #: shifted click extends *from*. Outlives the drag: shift+click's whole
        #: purpose is to extend from a position placed earlier.
        self._anchor = None
        #: The anchor as ``(page, low index, high index)`` when it covers a span
        #: rather than a position -- which is what a double-click leaves behind.
        #: None means "one position", worked out from `_anchor` when needed;
        #: doing it lazily keeps an ordinary press free of the page-wide lookup.
        self._anchor_span = None
        #: True between a shifted press and its release, so the release does not
        #: also follow a link.
        self._extending = False
        #: The insertion point, as ``(page, character index)``, or None. Placed
        #: by a plain click on text; what shift+arrow extends *from*. Acrobat's
        #: cursor, and like Acrobat's it does not survive a page turn, a mode
        #: change or a reload.
        self._caret = None
        #: Where the keyboard has moved the far end to, as ``(page, index)``.
        self._caret_focus = None
        #: Half of the blink. Qt's own flash time, so it matches the platform.
        self._caret_on = True
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._blink_caret)
        #: {page: QPdfSelection} for the pages the selection covers.
        self._selection: dict = {}
        self._selecting = False
        self._press = None
        #: The glyphs of the page being marked, at the height a mark wants.
        #: Separate from `_text` above, which is Qt's ink-tight boxes and is
        #: what *reading* selects by: a mark is not a selection and must not
        #: be built out of one. See `textlayer`.
        self._glyphs = TextLayer()
        #: A text markup gesture in progress, as ``(page, anchor, pointer)``
        #: with both points in the page's own space.
        #: Its quadrilaterals, recomputed as the pointer moves and drawn as
        #: the feedback. The *same* list the gesture emits when it ends, so
        #: what is shown and what is kept cannot drift apart.
        self._preview: tuple = ()
        #: {tool: (annotation kind, colour)}, pushed in by the window so the
        #: preview is drawn in the colour the finished mark will have.
        self._mark_styles: dict = {}
        #: What colour a mark of a given kind would be made in now. Set by
        #: the window, because the answer changes as a colour is picked.
        self.mark_colour = None
        #: What icon the next comment will carry, asked of the window --
        #: which keeps it, because it is one of the tool's defaults. Its
        #: *size* is what `icon_rect` needs: Reader cuts each icon's box
        #: to its glyph, and the corner that lands under the pointer is
        #: chosen here because only this knows how the page is turned.
        self.note_icon = None
        #: The marks the document on screen already carried, for clicking on.
        #: Read from *that* document rather than from the sources it was made
        #: from: its pages are the ones being shown, its coordinates are the
        #: ones drawn in, and no mapping is needed in either direction. The
        #: price is that nothing read here outlives the next export, which
        #: costs nothing while selecting changes no data -- and `clear_marks`
        #: drops it when the document does, exactly as the search hits are
        #: dropped for the same reason.
        self._file_marks = markup.MarkMap()
        #: One click's worth of reaching the text a mark covers. See
        #: `let_text_through`; cleared by the selection it allows.
        self._text_through = False
        #: The marks whose pop-up window has been closed by hand, by their
        #: `/NM`. The file says a window was open when it was saved and the
        #: pointer honours that, so without this the cross put a window
        #: away for exactly as long as it took to move the mouse.
        self._shut_notes = set()
        #: The three buttons shown beside a selected mark. Built by the
        #: window, as the tool strip is, and placed from here because only
        #: the canvas knows where the mark has got to after a scroll.
        self._mark_buttons = None
        #: What the pointer is over, as ``(page, mark)``. Outlined like a
        #: selection but not selected: it says "there is a mark here, and
        #: this is how far it reaches" before you commit to picking it up.
        self._hovered = None
        #: A grip being dragged, as ``(which, page, mark, anchor)`` -- the
        #: grip's index, and the page-space point the *other* grip sits at,
        #: which the run is rebuilt between.
        self._dragging_grip = None
        #: A comment's icon being dragged, as ``(page, mark, grabbed, moved)``:
        #: where the press landed, and whether it has yet travelled far enough
        #: to be a drag rather than a click. Reader lets an icon be moved and
        #: this application did not, so a press on one can no longer open its
        #: note outright -- which gesture it was is known only on release.
        self._dragging_note = None
        #: A stamp being reshaped, as ``(page, mark, which, centre)`` --
        #: which handle has hold of it and the point both the scaling and
        #: the turning happen about.
        self._dragging_stamp = None
        #: The text box being typed into: ``(page, mark, editor, began)``,
        #: ``began`` the rectangle it had when editing began. None when no
        #: box is being edited.
        self._text_editing = None
        #: ``(mark, rect, rotate)`` while a comment is being dragged or
        #: reshaped: the shape the gesture is asking for, which everything
        #: that draws the mark reads instead of what is on record. Nothing
        #: is written until the button comes up, so a gesture that goes
        #: nowhere costs nothing.
        self._shaping = None
        #: The note being shown beside the pointer, as ``(mark, point)``.
        self._note_panel = None
        #: What is selected, as ``(page, mark)``. A mark of the user's is an
        #: `Annotation`; one of the file's is a `Mark`; both have `rect` and
        #: `quads`, which is all selection needs of them.
        self._selected = None
        self.viewport().setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(True)
        #: Fires once the viewport has stopped, to repaint the pages that were
        #: too expensive to render while it was moving.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(lambda: self.viewport().update())
        #: Reads the real page sizes a chunk at a time, after the document is
        #: already on screen.
        self._measured = 0
        self._measure = QTimer(self)
        self._measure.timeout.connect(self._measure_some)
        #: True while the scrollbar is being moved by us rather than by the
        #: person reading, so that it does not read as scrolling.
        self._anchoring = False
        #: A position to hold while the page sizes are still being measured.
        self._anchor_position = None
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # -- document ----------------------------------------------------------

    def set_document(self, document, data: Optional[bytes] = None,
                     sizes: Optional[Sequence[QSizeF]] = None):
        """Show ``document``, a QPdfDocument, or None to show nothing.

        ``data`` is the same document as bytes, for the render thread to parse
        into one of its own: QPdfDocument is not thread-safe, and this one is
        bound to the search, bookmark and page-selector models on this thread.
        Without it prefetch and the slow-page fallback have nothing to work
        with, but pages still display: they are rendered on this thread from
        ``document`` as they are painted.
        """
        known = False
        if document is None:
            sizes = []
        elif sizes is not None and len(sizes) == document.pageCount():
            # The caller already knew them -- the page list does, on the 1:1
            # path -- so there is nothing to measure and nothing to correct.
            sizes = [QSizeF(size) for size in sizes]
            known = True
        else:
            sizes = provisional_sizes(document)
        # Carrying the zoom *and* the facing mode across: these belong to the
        # reader, not to the document, and a new document arrives every time an
        # edit makes the snapshot stale. Dropping facing here meant the setting
        # was restored at startup, applied to an empty layout, and thrown away
        # the moment a document loaded.
        self._layout = PageLayout(sizes, zoom=self._layout.zoom,
                                  facing=self._layout.facing,
                                  cover=self._layout.cover)
        self._pages.set_document(document, data)
        self._text.set_document(document)
        # The bytes, not the QPdfDocument: PDFium is handed a pointer to this
        # same buffer rather than a copy of the file, so a second reader of
        # the document on screen costs its parse structures and nothing more.
        self._glyphs.set_document(data)
        # What was selected, as `(page, index)`, so it can be found again in
        # the map about to be read. A snapshot is rebuilt whenever anything
        # is edited, and losing the mark you had picked because a *different*
        # page was rotated is the kind of thing nobody reports and everybody
        # notices.
        was = None
        if self._selected is not None:
            page, mark = self._selected
            if not isinstance(mark, markup.Annotation):
                was = (page, mark.index)
        self._selected = None
        self._hovered = None
        self._file_marks = (markup.MarkMap.read(io.BytesIO(data)) if data
                            else markup.MarkMap())
        if was is not None:
            for mark in self._file_marks.visible(was[0] + 1):
                if mark.index == was[1]:
                    self._selected = (was[0], mark)
                    break
        self._document = document
        self.clear_selection()
        self.clear_caret()
        self._links.setDocument(document or self._no_document)
        self._links_page = -1
        self._current = -1
        self._update_ranges()
        self.viewport().update()
        if sizes:
            self._emit_current()
        self._anchor_position = None
        self._start_measuring(len(sizes), known=known)

    #: Pages measured per tick while the real sizes are gathered. At 1.8 ms a
    #: page that is about 100 ms of work between turns of the event loop --
    #: long enough to get through a book quickly, short enough not to be felt.
    MEASURE_CHUNK = 64

    def _start_measuring(self, count: int, known: bool = False):
        """Replace the provisional sizes with the real ones, in the background.

        Reading all 1,590 of the Handbook's page sizes takes 2.9 seconds and
        used to happen before the first page could be drawn. Nothing about it
        has to be finished before the document is shown: the layout is right
        for the pages that match the first one, which is nearly all of them,
        and wrong only in its total height until this catches up.
        """
        self._measured = count if known else (1 if count else 0)
        self._measure.stop()
        if not known and count > 1 and self._document is not None:
            self._measure.start(0)

    def _measure_some(self):
        """One chunk of page sizes, then yield to the event loop."""
        document, layout = self._document, self._layout
        count = layout.page_count
        if document is None or self._measured >= count:
            self._measure.stop()
            return
        end = min(self._measured + self.MEASURE_CHUNK, count)
        changed = False
        for index in range(self._measured, end):
            size = document.pagePointSize(index)
            if size != layout.size_of(index):
                layout.set_size(index, size)
                changed = True
        self._measured = end
        if changed:
            # Re-laying out moves the scrollbar under the reader, so hold the
            # page they are on rather than the pixel offset -- but only when
            # they are still. Re-anchoring mid-scroll would snap the view to
            # the top of the current page and fight the drag, and a few pixels
            # of drift while moving is not noticeable.
            anchor = self._anchor_position
            page = -1 if anchor is not None else (
                self._page_filling_the_viewport() if self.settled() else -1)
            was_settled = self.settled()
            self._anchoring = True
            try:
                # Changing the range moves the value, which is the same signal
                # a drag sends.
                layout.set_zoom(layout.zoom)
                self._update_ranges()
            finally:
                self._anchoring = False
            if anchor is not None:
                self.go_to_position(anchor)
            elif page >= 0:
                self.go_to_page(page)
            if was_settled and self._settle.isActive():
                # Nothing the reader did; do not make them wait for a settle
                # that only this pass started.
                self._settle.stop()
            self.viewport().update()
        if end >= count:
            self._measure.stop()
            self._anchor_position = None

    def shutdown(self):
        """Stop the render thread and join it.

        Explicit, like the grid's renderer: Qt aborts the process outright if a
        QThread is destroyed while still running, so this cannot be left to
        garbage collection. Called from ReaderView, and from any test that
        builds a canvas of its own.
        """
        self._pages.shutdown()

    @property
    def layout(self) -> PageLayout:
        """The geometry. Public because links and selection will need it."""
        return self._layout

    def page_count(self) -> int:
        return self._layout.page_count

    # -- zoom --------------------------------------------------------------

    def zoom(self) -> float:
        return self._layout.zoom

    def set_zoom(self, zoom: float, anchor: Optional[QPointF] = None,
                 fit: str = FitMode.NONE):
        """Re-scale, keeping ``anchor`` (a viewport point) over the same spot.

        Without an anchor the viewport centre is held, which is what a menu
        zoom should do. Ctrl+wheel passes the cursor instead.

        Setting a zoom directly clears any fit mode, so a window resized after
        an explicit zoom keeps that zoom. ``fit`` is for the fit helpers below,
        which need the mode remembered rather than only its result.
        """
        zoom = max(ZOOM_LIMITS[0], min(float(zoom), ZOOM_LIMITS[1]))
        self._fit = fit
        if zoom == self._layout.zoom and self._layout.page_count:
            # Nothing to do, and *saying* so is what stops fit-to-width
            # oscillating. Re-laying out at the zoom already in force clears
            # the page cache and resets the scroll ranges, which can change
            # whether a scrollbar is wanted, which arrives back here as
            # another resize. The zoom is the same every time round, so the
            # cycle is invisible in the result and endless in the event
            # queue -- at some window sizes tight enough to starve the timer
            # that would have ended it, and the application simply stopped.
            return
        if not self._layout.page_count:
            self._layout.set_zoom(zoom)
            return
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2.0,
                             self.viewport().height() / 2.0)
        before = self.to_document(anchor)
        on_page = self._layout.page_at(before)
        page_point = (self._layout.point_in_page(on_page, before)
                      if on_page is not None else None)
        fraction = None
        if on_page is None:
            height = self._layout.content_size().height() or 1.0
            fraction = before.y() / height

        self._layout.set_zoom(zoom)
        self._pages.clear()
        self._update_ranges()

        if on_page is not None:
            after = self._layout.from_page(on_page, page_point)
        else:
            after = QPointF(before.x(), fraction * self._layout.content_size().height())
        self._scroll_so(after, anchor)
        self.viewport().update()
        # The mark is a different size and in a different place now, and the
        # bar beside it is neither: it is interface, drawn at one size over
        # whatever the page has become.
        self._place_mark_buttons()
        self._follow_editor()

    def zoom_to_width(self):
        """Fit the width, and keep fitting it as the window changes.

        The vertical scrollbar is *predicted* rather than reacted to, which is
        what stops this oscillating. Reacting looks simpler: fit the viewport
        as it is, and if a scrollbar then appears the resize it causes will
        fit again. Usually the second answer agrees with the first. In a
        narrow band it never does -- the zoom without a scrollbar makes the
        content just tall enough to need one, and the zoom with it makes the
        content just short enough not to. With a 400pt square page the window
        froze between 760 and 775 pixels tall and nowhere else, which is
        exactly why it went unnoticed: 700x600, 700x700, 900x700 and 1000x900
        are all fine.

        The resize that scrollbar causes arrives as a *posted* event rather
        than a nested call, so a re-entrancy guard does not see it and a depth
        counter is back at zero every time. Predicting is what converges:
        decide once whether the content will be taller than the viewport, take
        the scrollbar's width off before fitting if it will, and the answer is
        stable because nothing it depends on changes afterwards.
        """
        width = self.viewport().width()
        # Only when the bar is not already there. If it is, the viewport has
        # already lost its width and taking it off again fits to a window
        # narrower than any that exists -- which is the oscillation one step
        # removed: a zoom for width minus one bar and a zoom for width minus
        # two, alternating for ever.
        if (not self.verticalScrollBar().isVisible()
                and self._needs_vertical_bar(
                    self._layout.zoom_for_width(width))):
            width -= self._scrollbar_extent()
        self.set_zoom(self._layout.zoom_for_width(max(1, width)),
                      fit=FitMode.WIDTH)

    def _scrollbar_extent(self) -> int:
        """How much width a vertical scrollbar takes from the viewport."""
        bar = self.verticalScrollBar()
        width = bar.sizeHint().width()
        return width if width > 0 else self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent)

    def _needs_vertical_bar(self, zoom: float) -> bool:
        """Whether the content would be taller than the viewport at ``zoom``.

        Everything in the layout scales with the zoom, margins included, so the
        height at another zoom is the height now in proportion -- no relayout
        needed to ask.
        """
        if self.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff:
            return False
        current = self._layout.zoom
        if current <= 0:
            return False
        height = self._layout.content_size().height() / current * zoom
        return height > self.viewport().height()

    def zoom_to_page(self):
        """Fit a whole page, and keep fitting it as the window changes."""
        index = max(0, self.current_page())
        self.set_zoom(self._layout.zoom_for_page(QSizeF(self.viewport().size()), index),
                      fit=FitMode.PAGE)

    def fit_mode(self) -> str:
        return self._fit

    def zoom_in(self):
        self.set_zoom(self.zoom() * ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom() / ZOOM_STEP)

    def _reapply_fit(self):
        """Re-derive the zoom after a resize, if it was derived to begin with."""
        if self._fit == FitMode.WIDTH:
            self.zoom_to_width()
        elif self._fit == FitMode.PAGE:
            self.zoom_to_page()

    # -- navigation --------------------------------------------------------

    def facing(self) -> bool:
        return self._layout.facing

    def set_facing(self, on: bool, cover: Optional[bool] = None):
        """Two pages to a row, or one, keeping the reader's place.

        A relayout moves every page, so the page being read is put back where it
        was afterwards -- the same courtesy the continuous/single toggle gets,
        and for the same reason: a mode change that silently jumps to the front
        of the book is worse than not offering the mode.
        """
        if bool(on) == self._layout.facing and cover is None:
            return
        page = max(0, self.current_page())
        self._layout.set_facing(on, cover)
        self._pages.clear()
        self._reapply_fit()
        self._update_ranges()
        self.go_to_page(page)
        self.viewport().update()

    def continuous(self) -> bool:
        return self._continuous

    def set_continuous(self, on: bool):
        """Scroll the whole document, or show one page at a time.

        The layout does not change: the column is always the whole document, and
        single-page mode is the *scroll range* restricted to one page's extent.
        Keeping one layout means page rectangles, hit testing and every
        coordinate mapping behave identically in both modes -- a second layout
        for single-page would be a second set of geometry bugs.
        """
        on = bool(on)
        if on == self._continuous:
            return
        page = max(0, self.current_page())
        self._continuous = on
        self._single = page
        self._update_ranges()
        # The restricted range clamps the scrollbar somewhere arbitrary; put it
        # back on the page the reader was actually looking at.
        self.go_to_page(page)
        self.viewport().update()

    def current_page(self) -> int:
        return self._current

    def go_to_page(self, index: int):
        """Put the top of ``index`` at the top of the viewport, clamped.

        The caret is left alone. It used to die here, and before that whenever
        the current page changed -- which in continuous mode is simply what
        scrolling does, so extending a selection onto the next page and then
        scrolling to look at it killed the caret and the next shift+arrow
        scrolled instead of extending. With the arrow table there is no longer
        any reason for a position in the
        document to evaporate because the view moved: the caret is placed by a
        click and cleared by Escape or a new document, and survives everything
        else.
        """
        if not self._layout.page_count:
            return
        index = min(max(index, 0), self._layout.page_count - 1)
        if not self._continuous and index != self._single:
            # Move the window before scrolling into it, or the scrollbar is
            # clamped to the page we are leaving.
            self._single = index
            self._update_ranges()
        top = self._layout.page_rect(index).top() - self._layout.margin_px()
        # Not motion. Moving the scrollbar from code -- a jump to a bookmark,
        # restoring where you were, re-anchoring after the page sizes are
        # measured -- arrives through the same signal as a drag, and counting
        # it as scrolling made the arrival of a page blank it: the paint that
        # followed thought the view was moving, showed the proxy for anything
        # expensive, and corrected itself 120 ms later. Displayed, blanked,
        # displayed.
        self._anchoring = True
        try:
            self.verticalScrollBar().setValue(int(round(top)))
        finally:
            self._anchoring = False
        self._emit_current()

    def position(self) -> "Optional[Tuple[int, float]]":
        """Where the reader is: a page, and how far into it in page points.

        Against a page rather than as a scrollbar value, because the value
        does not survive a reload. A rebuilt document is laid out from
        `provisional_sizes` until the measuring pass catches up, and that
        layout is shorter than the real one, so the scrollbar range shrinks
        and Qt clamps the position to fit it -- to zero, from anywhere past
        the provisional end. The range comes back; the position does not.
        """
        if not self._layout.page_count:
            return None
        page = self._page_filling_the_viewport()
        if page < 0:
            return None
        into = (self.verticalScrollBar().value()
                - self._layout.page_rect(page).top()) / max(self._layout.zoom,
                                                            1e-9)
        return (page, into)

    def go_to_position(self, position) -> None:
        """Put the reader back where `position` says, as near as the layout allows.

        Approximate while the sizes are still provisional, and corrected by
        the measuring pass, which re-anchors on the page filling the viewport
        -- the page this just restored.
        """
        if position is None or not self._layout.page_count:
            return
        page, into = position
        page = min(max(page, 0), self._layout.page_count - 1)
        # First for its side effects: in single-page mode the window has to
        # move before the scrollbar can be set inside it.
        self.go_to_page(page)
        bar = self.verticalScrollBar()
        # Absolute rather than added to what `go_to_page` left, which is a
        # margin *above* the page top -- adding there lands a whole margin
        # short, and the margin grows with the zoom.
        where = self._layout.page_rect(page).top() + into * self._layout.zoom
        # Not motion, for the reason given in `go_to_page`.
        self._anchoring = True
        try:
            bar.setValue(int(round(where)))
        finally:
            self._anchoring = False
        self._emit_current()
        if self._measure.isActive():
            # The sizes are still provisional, so this landed on a guess: page
            # eight's top is not known until page eight has been measured.
            # Held as the anchor so the measuring pass restores it again on
            # every chunk, instead of re-anchoring on whichever page the guess
            # happened to leave under the viewport.
            self._anchor_position = position

    def next_page(self):
        self.go_to_page(max(0, self.current_page()) + 1)

    def previous_page(self):
        self.go_to_page(max(0, self.current_page()) - 1)

    def first_page(self):
        self.go_to_page(0)

    def last_page(self):
        self.go_to_page(self._layout.page_count - 1)

    def go_to(self, index: int, point: QPointF):
        """Scroll so a point on a page is visible, for a link or a search hit."""
        if not self._layout.page_count:
            return
        target = self._layout.from_page(index, point)
        if not _is_finite_point(target):
            self.go_to_page(index)
            return
        self.verticalScrollBar().setValue(int(round(target.y() - self.viewport().height() / 4)))
        self.horizontalScrollBar().setValue(
            int(round(target.x() - self.viewport().width() / 2)))

    # -- coordinate mapping ------------------------------------------------

    def offset(self) -> QPointF:
        """Document-space coordinate of the viewport's top left.

        Includes the centring shift applied when the content is narrower than
        the viewport -- forgetting that is what puts a hit test a margin's width
        out on a wide window.
        """
        content = self._layout.content_size()
        spare = self.viewport().width() - content.width()
        x = -spare / 2.0 if spare > 0 else self.horizontalScrollBar().value()
        return QPointF(x, float(self.verticalScrollBar().value()))

    def to_document(self, point: QPointF) -> QPointF:
        """Viewport point to document pixels."""
        return point + self.offset()

    def to_viewport(self, point: QPointF) -> QPointF:
        """Document pixels to viewport point. The inverse of ``to_document``."""
        return point - self.offset()

    def page_at(self, point: QPointF) -> Optional[int]:
        """The page under a *viewport* point, or None."""
        return self._layout.page_at(self.to_document(point))

    def to_page(self, point: QPointF) -> Optional[Tuple[int, QPointF]]:
        """Viewport point to ``(index, page point)``, or None off any page.

        What links, selection and "add a bookmark here" are all built on.
        """
        return self._layout.to_page(self.to_document(point))

    def _scroll_so(self, document_point: QPointF, viewport_point: QPointF):
        self.verticalScrollBar().setValue(
            int(round(document_point.y() - viewport_point.y())))
        self.horizontalScrollBar().setValue(
            int(round(document_point.x() - viewport_point.x())))

    # -- Qt ----------------------------------------------------------------

    def _band(self) -> Tuple[float, float]:
        """The scrollable extent, which is the document unless showing one page."""
        content = self._layout.content_size()
        if self._continuous or not self._layout.page_count:
            return 0.0, content.height()
        index = min(max(self._single, 0), self._layout.page_count - 1)
        rect = self._layout.page_rect(index)
        margin = self._layout.margin_px()
        return rect.top() - margin, rect.bottom() + margin

    def _update_ranges(self):
        content = self._layout.content_size()
        view = self.viewport().size()
        vbar, hbar = self.verticalScrollBar(), self.horizontalScrollBar()
        top, bottom = self._band()
        vbar.setRange(int(round(top)), max(int(round(top)),
                                           int(round(bottom - view.height()))))
        vbar.setPageStep(view.height())
        vbar.setSingleStep(max(1, view.height() // 12))
        hbar.setRange(0, max(0, int(round(content.width() - view.width()))))
        hbar.setPageStep(view.width())
        hbar.setSingleStep(max(1, view.width() // 12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_ranges()
        # A window dragged wider under fit-to-width should re-fit rather than
        # keep the old scale, which is why the mode is remembered.
        self._reapply_fit()
        self._place_mark_buttons()
        self._follow_editor()

    def _page_arrived(self, index: int):
        """A render finished. Repaint only if it is on screen."""
        top = self.offset().y()
        if index in self._layout.pages_in(top, top + self.viewport().height()):
            self.viewport().update()

    def _scrolled(self, _value):
        self._emit_current()
        self._moving()
        self.viewport().update()

    #: How long after the last scroll the view counts as settled. Long enough
    #: not to fire during a drag, short enough to feel like part of stopping.
    SETTLE_MS = 120

    def _moving(self):
        """Note that the viewport is in motion, and arrange to notice when it stops.

        A scrollbar moved from code is not motion -- see `go_to_page`.

        While it is moving, an expensive page is left to the worker: stalling a
        scroll for 127 ms is felt, and a stand-in for one frame is not. Once it
        has stopped, the opposite is true -- nobody perceives a render as a
        stall when they are sitting still, and a page left blurred is simply
        wrong. So the timer repaints once, settled, and the slow pages are
        rendered properly then.
        """
        if self._anchoring:
            return
        self._settle.start(self.SETTLE_MS)

    def settled(self) -> bool:
        return not self._settle.isActive()

    def _emit_current(self):
        page = self._page_filling_the_viewport()
        if page != self._current:
            self._current = page
            self.current_page_changed.emit(page)

    def _page_filling_the_viewport(self) -> int:
        """The page with most of the viewport, not merely the topmost.

        A page selector that flips over on the first pixel of the next page is
        worse than useless when scrolling; this changes when the new page has
        the larger share.
        """
        if not self._layout.page_count:
            return -1
        if not self._continuous:
            return min(max(self._single, 0), self._layout.page_count - 1)
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        best, best_share = -1, 0.0
        for index in self._layout.pages_in(top, bottom):
            rect = self._layout.page_rect(index)
            share = min(rect.bottom(), bottom) - max(rect.top(), top)
            if share > best_share:
                best, best_share = index, share
        return best if best >= 0 else self._layout.nearest_page(top)

    # -- selection ---------------------------------------------------------

    def clear_selection(self):
        if self._selection:
            crossed = self.selection_is_across_pages()
            self._selection = {}
            self.viewport().update()
            self.selection_changed.emit(False)
            if crossed:
                self.selection_crosses_pages.emit(False)
        self._anchor = None
        self._anchor_span = None

    def has_selection(self) -> bool:
        return bool(self._selection)

    def selection_is_across_pages(self) -> bool:
        """Whether the selection runs across a page break, and so cannot
        be marked."""
        return len(self._selection) > 1

    def selection_view(self):
        """A PDF destination view for where the selection starts, or None.

        ``("XYZ", left, top, None)`` in the page's own coordinate space, so a
        bookmark made from a selected heading lands on that heading rather than
        at the top of its page. The y axis is flipped: PDF measures from the
        bottom of the page and everything here measures from the top.
        """
        if not self._selection:
            return None
        page = min(self._selection)
        bounds = self._selection[page].bounds()
        if not bounds:
            return None
        box = bounds[0].boundingRect()
        height = self._layout.page_height(page)
        if height is None:
            return None
        return ("XYZ", float(box.left()), float(height - box.top()), None)

    def selected_text(self) -> str:
        """Everything selected, in page order, pages joined by a newline."""
        return "\n".join(self._selection[page].text()
                          for page in sorted(self._selection)
                          if self._selection[page].text())

    def copy(self) -> bool:
        """Put the selection on the clipboard. False if there was nothing."""
        text = self.selected_text()
        if not text:
            return False
        QApplication.clipboard().setText(text)
        return True

    def select_all_on(self, page: int):
        if self._document is None:
            return
        selection = self._document.getSelectionAtIndex(page, 0, PageText.ALL)
        self._set_selection({page: selection} if selection.isValid() else {})

    def index_at(self, page: int, point: QPointF):
        """Which character a point is on, or None if the page has no text.

        PDFium has no "what character is at this point"; what it has is
        `getSelection`, which needs a glyph under *both* ends. So the index is
        found the roundabout way -- select from the start of the page's text up
        to the point, and ask how long that came out. A page-wide selection,
        thrown away immediately, which is fine for something that happens once
        per click and would not be for something that happened per mouse move.
        That is why dragging does not use this.
        """
        if self._document is None:
            return None
        boxes = self._text.runs(page)
        if not boxes:
            return None
        start = self._text.snap(page, QPointF(boxes[0].left(), boxes[0].top()))
        here = self._text.snap(page, point)
        if start is None or here is None:
            return None
        lead = self._document.getSelection(page, start, here)
        # Invalid means the point is at the very beginning of the text, where
        # there is nothing in front of it to select.
        return lead.endIndex() if lead.isValid() else 0

    def word_at(self, page: int, point: QPointF):
        """``(start, end)`` of the word under a point, or None."""
        index = self.index_at(page, point)
        if index is None:
            return None
        return self._text.word_bounds(self._text.text(page), index)

    def select_word_at(self, page: int, point: QPointF) -> bool:
        """Select the word under a point. False if there is no text there."""
        bounds = self.word_at(page, point)
        if bounds is None:
            return False
        word = self._document.getSelectionAtIndex(page, bounds[0],
                                                  bounds[1] - bounds[0])
        if not word.isValid():
            return False
        self._set_selection({page: word})
        # The word becomes the anchor, so a shift+click after a double-click
        # extends from its far side and leaves the word itself whole.
        self._anchor = (page, point)
        self._anchor_span = (page, bounds[0], bounds[1])
        return True

    def _anchor_indices(self):
        """The anchor as ``(page, low, high)`` in character indices, or None.

        A double-click records its span exactly, for free. An ordinary press
        records only a point, and the index is worked out here rather than
        there: every press in the document would otherwise pay for a page-wide
        lookup that only a later shift+click will ever read.
        """
        if self._anchor_span is not None:
            return self._anchor_span
        if self._anchor is None:
            return None
        page, point = self._anchor
        index = self.index_at(page, point)
        return None if index is None else (page, index, index)

    def extend_to(self, page: int, point: QPointF) -> bool:
        """Extend the selection to a point, for a shifted click.

        **The anchor end stays exactly where it was put; the moving end grows
        outward to cover the whole word.** Granularity follows the precision of
        the gesture: a drag is continuous and you can watch it and stop where
        you like, so it selects by character (`_extend_selection`, untouched); a
        shifted click is one discrete shot at a position, so snapping the end it
        moves is real help rather than interference.

        Deliberately *not* Acrobat, which is the other way round -- it snaps a
        drag and does so with hysteresis, so the same two endpoints give
        different selections depending on the path the mouse took to reach them.
        Here the selection is a function of its two ends and nothing else.

        Indices rather than points, unlike the drag, because deciding which end
        moves means asking which comes first in *reading* order. Comparing
        geometrically -- page, then y, then x -- gets that wrong on a two-column
        page like the Handbook's, where the top of the right column is after the
        bottom of the left one. PDFium's indices are already in reading order.
        """
        if self._document is None:
            return False
        anchor = self._anchor_indices()
        if anchor is None:
            return False
        anchor_page, anchor_low, anchor_high = anchor
        moved = self.index_at(page, point)
        if moved is None:
            return False
        bounds = self._text.word_bounds(self._text.text(page), moved)
        if bounds is None:
            return False
        word_start, word_end = bounds

        # Which end of the anchor is the fixed one: extending forward keeps its
        # low end, backward its high end. For a press those are the same index,
        # and for a double-clicked word this is what leaves the word whole.
        if (page, moved) >= (anchor_page, anchor_high):
            return self.select_between(anchor_page, anchor_low, page, word_end)
        return self.select_between(page, word_start, anchor_page, anchor_high)

    # -- the caret ---------------------------------------------------------

    def caret(self):
        """``(page, index)`` of the insertion point, or None."""
        return self._caret

    def set_caret(self, page: int, index: int):
        """Put the insertion point on a character and start it blinking."""
        self._caret = (page, index)
        self._caret_focus = (page, index)
        self._caret_on = True
        interval = max(200, QApplication.cursorFlashTime() // 2)
        self._caret_timer.start(interval)
        self.viewport().update()

    def clear_caret(self):
        self._caret_timer.stop()
        if self._caret is not None:
            self._caret = None
            self._caret_focus = None
            self.viewport().update()

    def _blink_caret(self):
        self._caret_on = not self._caret_on
        self.viewport().update()

    def caret_rect(self):
        """Where to draw the bar, in *document* pixels, or None.

        The left edge of the character it sits before, and the height of the
        *line* -- not of the character. A glyph's own box is whatever that
        letter happens to occupy: 7 points before a lowercase "e" against 13 for
        the line, starting 3 points lower, so the bar changed size and position
        with every letter and was, in David's words, impossible to find on the
        page. Acrobat draws it past the top and bottom of a lowercase letter for
        exactly this reason.

        At the end of the text there is no character to sit before, so the right
        edge of the last one is used instead.
        """
        if self._caret is None or self._document is None:
            return None
        page, index = self._caret_focus or self._caret
        text = self._text.text(page)
        at, edge = (index, "left") if index < len(text) else (len(text) - 1, "right")
        if at < 0:
            return None
        try:
            selection = self._document.getSelectionAtIndex(page, at, 1)
        except Exception:  # pragma: no cover - PDFium can be unhappy
            return None
        bounds = selection.bounds() if selection is not None else None
        if not bounds:
            return None
        box = bounds[0].boundingRect()
        x = box.left() if edge == "left" else box.right()
        top, bottom = box.top(), box.bottom()
        line = self._text.line_bounds(text, at)
        if line is not None and line[1] > line[0]:
            try:
                whole = self._document.getSelectionAtIndex(
                    page, line[0], line[1] - line[0]).boundingRectangle()
            except Exception:  # pragma: no cover - PDFium can be unhappy
                whole = None
            if whole is not None and whole.height() > 0:
                top, bottom = whole.top(), whole.bottom()
        top_left = self._layout.from_page(page, QPointF(x, top))
        foot = self._layout.from_page(page, QPointF(x, bottom))
        return QRectF(top_left.x(), top_left.y(),
                      max(2.0, self._layout.zoom), foot.y() - top_left.y())

    def _page_text_length(self, page: int) -> int:
        return len(self._text.text(page))

    def _step_character(self, page: int, index: int, delta: int):
        """One character on, or back, crossing pages at the ends."""
        index += delta
        if index < 0:
            if page == 0:
                return page, 0
            page -= 1
            return page, max(0, self._page_text_length(page))
        if index > self._page_text_length(page):
            if page + 1 >= self._layout.page_count:
                return page, self._page_text_length(page)
            return page + 1, 0
        return page, index

    def _step_word(self, page: int, index: int, delta: int):
        """To the start of the next word, or of the one behind."""
        text = self._text.text(page)
        word = self._text.word_character
        if delta > 0:
            at = index
            while at < len(text) and word(text[at]):
                at += 1
            while at < len(text) and not word(text[at]):
                at += 1
            if at >= len(text) and page + 1 < self._layout.page_count:
                return page + 1, 0
            return page, at
        at = index
        while at > 0 and not word(text[at - 1]):
            at -= 1
        while at > 0 and word(text[at - 1]):
            at -= 1
        if at == 0 and index == 0 and page > 0:
            return page - 1, self._page_text_length(page - 1)
        return page, at

    def _step_line(self, page: int, index: int, delta: int):
        """One line on or back, keeping the column, and across pages.

        The column is an offset within the line, because lines here are the
        page text's own, split on its newlines. Which line comes next is
        therefore the *document's* text order -- on a multi-column page that can
        go from column one to column three. Acrobat does the same and for the
        same reason.
        """
        text = self._text.text(page)
        bounds = self._text.line_bounds(text, index)
        if bounds is None:
            return page, index
        start, end = bounds
        column = index - start
        if delta > 0:
            # Past the break, not onto it: `end` stops before the carriage
            # return, so stepping one character lands on the "\r" or the "\n"
            # and `line_bounds` resolves those back to the line just left.
            newline = text.find("\n", end)
            if newline == -1:
                if page + 1 >= self._layout.page_count:
                    return page, len(text)
                return self._line_on_page(page + 1, column, first=True)
            nxt = self._text.line_bounds(text, newline + 1)
        else:
            if start == 0:
                if page == 0:
                    return page, 0
                return self._line_on_page(page - 1, column, first=False)
            nxt = self._text.line_bounds(text, start - 1)
        if nxt is None:
            return page, index
        low, high = nxt
        return page, min(low + column, high)

    def _line_on_page(self, page: int, column: int, first: bool):
        """The first or last line of a neighbouring page, at the same column."""
        text = self._text.text(page)
        if not text:
            return page, 0
        bounds = self._text.line_bounds(text, 0 if first else len(text) - 1)
        if bounds is None:
            return page, 0
        low, high = bounds
        return page, min(low + column, high)

    def extend_caret(self, movement: str, delta: int) -> bool:
        """Move the far end of a keyboard selection and select up to it.

        ``movement`` is "character", "word" or "line". Exact in every case: a
        keypress is a precise gesture, so unlike the mouse it never snaps to a
        whole word.
        """
        if self._caret is None or self._document is None:
            return False
        page, index = self._caret_focus or self._caret
        step = {"character": self._step_character, "word": self._step_word,
                "line": self._step_line}[movement]
        return self._place_focus(step(page, index, delta), extend=True)

    def move_caret(self, movement: str, delta: int) -> bool:
        """Move the caret itself, dropping any selection. Option+arrow."""
        if self._caret is None or self._document is None:
            return False
        page, index = self._caret_focus or self._caret
        step = {"character": self._step_character, "word": self._step_word,
                "line": self._step_line}[movement]
        return self._place_focus(step(page, index, delta), extend=False)

    def caret_to_line_edge(self, end: bool, extend: bool) -> bool:
        """Cmd+left or right: the start or end of the caret's own line."""
        if self._caret is None:
            return False
        page, index = self._caret_focus or self._caret
        bounds = self._text.line_bounds(self._text.text(page), index)
        if bounds is None:
            return False
        return self._place_focus((page, bounds[1] if end else bounds[0]), extend)

    def caret_to_document_edge(self, end: bool, extend: bool) -> bool:
        """Cmd+up or down: the very start or end of the document."""
        if self._caret is None or not self._layout.page_count:
            return False
        if end:
            page = self._layout.page_count - 1
            return self._place_focus((page, self._page_text_length(page)), extend)
        return self._place_focus((0, 0), extend)

    def _place_focus(self, target, extend: bool) -> bool:
        """Put the moving end at ``target``; with ``extend``, select up to it.

        The single funnel for every caret movement in the table, so that "add
        Shift to extend instead of move" is one branch rather than a rule
        repeated in six places.
        """
        if self._caret is None:
            return False
        self._caret_focus = target
        self._caret_on = True
        if not extend:
            self._caret = target
            self._set_selection({})
        else:
            first, last = sorted((self._caret, target))
            if first == last:
                self._set_selection({})
            else:
                self.select_between(first[0], first[1], last[0], last[1])
        self.ensure_caret_visible()
        self.viewport().update()
        return True

    def ensure_caret_visible(self):
        """Scroll the moving end into view, by as little as will do.

        Without this a keyboard selection walks off the bottom of the window and
        you have to go and find it -- and going to find it used to cost you the
        caret. Minimal rather than centred: the text being selected should stay
        where the eye already is.
        """
        rect = self.caret_rect()
        if rect is None:
            return
        bar = self.verticalScrollBar()
        top, height = rect.top(), rect.height()
        if top < bar.value():
            bar.setValue(int(top))
        elif top + height > bar.value() + self.viewport().height():
            bar.setValue(int(top + height - self.viewport().height()))
        across = self.horizontalScrollBar()
        left, width = rect.left(), rect.width()
        if left < across.value():
            across.setValue(int(left))
        elif left + width > across.value() + self.viewport().width():
            across.setValue(int(left + width - self.viewport().width()))

    def select_between(self, first: int, low: int, last: int, high: int) -> bool:
        """Select from character ``low`` on page ``first`` to ``high`` on ``last``.

        Both ends as character indices, which is what makes this shareable: the
        mouse arrives here having snapped its moving end to a word, the keyboard
        having moved by exactly one character, word or line, and from here on
        they are the same selection.
        """
        if self._document is None:
            return False
        found = {}
        for index in range(first, last + 1):
            if first == last:
                selection = self._document.getSelectionAtIndex(
                    index, low, max(0, high - low))
            elif index == first:
                selection = self._document.getSelectionAtIndex(
                    index, low, PageText.ALL)
            elif index == last:
                selection = self._document.getSelectionAtIndex(index, 0, high)
            else:
                selection = self._document.getSelectionAtIndex(
                    index, 0, PageText.ALL)
            if selection is not None and selection.isValid():
                found[index] = selection
        self._set_selection(found)
        return bool(found)

    def _extend_selection(self, page: int, point: QPointF):
        """Select from the drag's anchor to ``point``.

        Runs across pages, because `getSelection` is per page and a reader that
        stops at a page break is not much of a reader: the first and last pages
        are selected from the anchor and to the cursor respectively, and every
        page between them entirely.

        **Except with a markup tool armed, when it stops at the page it
        started on**, because text is marked one page at a time. A selection
        made before the tool may still run across pages for reading, and
        cannot then be marked at all: it carries whatever the file stores
        between, often off screen.
        """
        if self._anchor is None or self._document is None:
            return
        anchor_page, anchor_point = self._anchor
        if self.marks_text() and page != anchor_page:
            page, point = anchor_page, None
        first, last = sorted((anchor_page, page))
        if point is None:
            # The drag left the page a markup tool anchored it to, so it
            # takes the rest of that page's text and no more.
            start, end = anchor_point, None
        else:
            start = anchor_point if anchor_page <= page else point
            end = point if anchor_page <= page else anchor_point

        found = {}
        for index in range(first, last + 1):
            if index == first == last:
                selection = self._selection_between(index, start, end)
            elif index == first:
                selection = self._selection_between(index, start, None)
            elif index == last:
                selection = self._selection_between(index, None, end)
            else:
                selection = self._document.getSelectionAtIndex(index, 0, PageText.ALL)
            if selection is not None and selection.isValid():
                found[index] = selection
        self._set_selection(found)

    def _set_selection(self, selection: dict):
        had = bool(self._selection)
        crossed = self.selection_is_across_pages()
        self._selection = selection
        self.viewport().update()
        if bool(selection) != had:
            self.selection_changed.emit(bool(selection))
        if self.selection_is_across_pages() != crossed:
            self.selection_crosses_pages.emit(not crossed)

    def _selection_between(self, page: int, start, end):
        """One page's worth, with a missing end meaning "to the edge of the text".

        Both ends are snapped onto the nearest run first: getSelection wants a
        glyph under each, and a drag does not oblige.
        """
        boxes = self._text.runs(page)
        if not boxes:
            return None
        if start is None:
            start = QPointF(boxes[0].left(), boxes[0].top())
        if end is None:
            last = boxes[-1]
            end = QPointF(last.right(), last.bottom())
        a = self._text.snap(page, start)
        b = self._text.snap(page, end)
        if a is None or b is None:
            return None
        return self._document.getSelection(page, a, b)

    @staticmethod
    def _device_size(rect, ratio: float) -> QSize:
        """How many real pixels a page laid out at ``rect`` covers.

        The layout is in logical pixels, and on a screen at 150% those are
        three quarters of the real ones. Rendering at the logical size and
        letting the painter stretch the result is a 1.5x upscale of every
        glyph -- measured at 1.1 to 2.2 times further from a reference render
        than rendering at the real size, worst on pages of text.

        It is not as expensive as the pixel count suggests: 1.47x the time on
        a page of dense schematics, and as little as 1.05x on the slowest
        pages, because most of what PDFium does is read the content stream,
        which does not care how many pixels come out of it.
        """
        return QSize(max(1, int(round(rect.width() * ratio))),
                     max(1, int(round(rect.height() * ratio))))

    def _prefetch_around(self, visible):
        """Ask for the rows around what was just painted.

        After painting rather than before: what is on screen is what the render
        thread should be working on first, and the queue moves a re-requested
        key to the back, so asking for neighbours first would delay the page the
        reader is actually looking at.

        Rows rather than pages, because with facing pages on, "the next two"
        means the next two *spreads* -- and because the cache has to be big
        enough for everything visible at once, which a page count cannot say.
        """
        if not visible or not self._layout.page_count:
            return
        middle = visible[len(visible) // 2]
        rect = self._layout.page_rect(middle)
        # The same size the paint asks for, to the pixel: the cache is keyed on
        # it, so a prefetch that rounded differently would render every page
        # twice and hit on neither.
        size = self._device_size(rect, self.devicePixelRatioF())

        wanted = list(visible)
        row = self._layout.row_of(middle)
        per_row = max(1, len(row))
        first, last = visible[0], visible[-1]
        for step in range(1, AsynchronousPages.PREFETCH_ROWS + 1):
            for index in (first - step * per_row, last + step * per_row):
                for page in self._pages_of_row(index):
                    if page not in wanted:
                        wanted.append(page)
        keep = len(wanted) + AsynchronousPages.SLACK
        self._pages.prefetch(wanted, size, keep)

    def _pages_of_row(self, index: int):
        """Every page sharing a row with ``index``, or nothing if out of range."""
        if not 0 <= index < self._layout.page_count:
            return []
        return self._layout.row_of(index)

    def _paint_selection(self, painter, index: int, offset: QPointF):
        selection = self._selection.get(index)
        if selection is None:
            return
        # **In the colour the mark will be made in**, when a markup tool is
        # armed: Reader tints the selection with the tool's own colour, so
        # what you are dragging out looks like what you will get. The
        # reader's own blue otherwise.
        band = SELECTION
        if self.marks_text() and self.mark_colour:
            # **The tool's name, not the subtype it writes.** `mark_colour`
            # is the window's `_colour_for_canvas_tool`, which looks a tool
            # up by the canvas's name for it; handed `/Underline` it finds
            # nothing and falls back to the default, so the band came out
            # red whatever colour the tool was armed in.
            colour = self.mark_colour(self._tool)
            if colour is not None:
                band = QColor.fromRgbF(*colour[:3])
                band.setAlpha(SELECTION.alpha())
        for polygon in selection.bounds():
            rect = self._layout.rect_from_page(index, polygon.boundingRect())
            rect.translate(-offset)
            painter.fillRect(rect, band)

    # -- links -------------------------------------------------------------

    @staticmethod
    def usable_link(link) -> bool:
        """Whether a link points somewhere we can go.

        **Not** `QPdfLink.isValid()`, which is the trap here. It requires a page,
        and an external link has `page() == -1` because it does not point into
        this document at all -- so `isValid()` is False for every http and
        mailto link even when the rectangles and the URL are perfectly good.
        Filtering on it silently discarded every external link in the Handbook:
        the pages that appeared to work were the ones whose links happen to be
        internal.
        """
        if link is None:
            return False
        url = link.url()
        return (url is not None and not url.isEmpty()) or link.page() >= 0

    def link_at(self, point: QPointF):
        """The link under a *viewport* point, or None.

        `QPdfLinkModel` is per page, so the page is set first; `linkAt` then
        takes a point in that page's own points, which is exactly what the
        layout hands back.

        The page the model is on is remembered because `setPage` resets the
        model, and this runs on every mouse move to decide the cursor.
        """
        found = self.to_page(point)
        if found is None:
            return None
        index, page_point = found
        if index != self._links_page:
            self._links.setPage(index)
            self._links_page = index
        link = self._links.linkAt(page_point)
        return link if self.usable_link(link) else None

    # -- form fields -------------------------------------------------------

    def edit_field(self, field):
        """Put a real editor over a text field, the way pdf.js does.

        Not a caret drawn by us over a generated appearance. A line edit
        already knows about selection, the clipboard, input methods, the
        platform's keyboard conventions and right-to-left text, and none of
        that is worth rewriting on top of a PDF appearance stream. It also
        means typing costs nothing: no appearance is generated until the
        value is committed, which is what Acrobat does too.
        """
        self.finish_editing()
        rect = self._field_rect(field)
        if rect is None:
            return
        editor = QLineEdit(self.viewport())
        editor.setFrame(False)
        editor.setText(self._value_of(field) or "")
        editor.setGeometry(rect.toRect())
        editor.setFont(self._editor_font(field, rect.height()))
        editor.selectAll()
        editor.show()
        editor.setFocus()
        editor.editingFinished.connect(self.finish_editing)
        # A line edit eats Tab for focus traversal, so the key never reaches
        # keyPressEvent above -- it leaves the editor, `editingFinished`
        # fires, and the form is behind you. Taken here instead.
        editor.installEventFilter(self)
        self._editing = (field, editor)

    # -- sticky notes ------------------------------------------------------

    def note_icon_rect(self, index: int, mark, offset=None):
        """Where a note's icon is in the viewport, or None if it is not drawn.

        From `markup.icon_box` rather than from the rectangle, because that is
        what is anchored: the icon's own size hung from the rectangle's *top*
        left, whatever size the rectangle is. For a note placed here the two
        are the same box; for one whose page has since been resized they are
        not, and following the rectangle would draw an icon half the size of
        the one the saved file shows.

        The icon's *page-space* box is what is turned, not its box on screen,
        which is what a viewer does -- it adds the points in page space and
        then turns the page. So every rotation comes out right with no case
        analysis here.

        **The size does not follow the zoom.** `/F` NoZoom says an icon holds
        its size while the page grows under it, and holds it about that top
        left corner, so the corner is placed at the zoom and the box is then
        laid out from it at the icon's own size. A mark told to scale --
        the form's checkbox, which clears the bit -- follows the zoom as
        everything else does.
        """
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return None
        rect, _angle = self._shape_of(mark)
        if (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype) in (markup.STAMP, markup.FREETEXT,
                                       *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK):
            # A stamp's box is its rectangle, at the page's own scale: it
            # is ink on the page, so none of the holding-still below
            # applies to it. Nor to a text box, a rectangle or an oval,
            # which are the same.
            return self.quad_on_screen(
                index, rect, offset,
                scaled=isinstance(mark, markup.Annotation))
        shown = forms_module.to_displayed(
            markup.icon_box(self.from_source(index, rect),
                            getattr(mark, "icon", markup.DEFAULT_ICON)), box)
        zoom = self._layout.zoom
        page = self._layout.page_rect(index)
        # The file's answer, not a setting of ours. Nothing here writes a
        # scaling icon -- measured on one `/Cross` with its NoZoom bit
        # cleared and nothing else changed, this application and Stirling
        # scale it, Acrobat leaves it fixed and PDFGear scales every icon
        # whatever the bit says, so four readers give three answers and the
        # bit is not one to create. A file that carries it is another
        # matter: it is saying something, and ignoring it would be this
        # application deciding the file is wrong.
        fixed = zoom if getattr(mark, "scales", False) else 1.0
        where = QRectF(page.x() + shown[0] * zoom,
                       page.y() + (height - shown[3]) * zoom,
                       (shown[2] - shown[0]) * fixed,
                       (shown[3] - shown[1]) * fixed)
        where.translate(-(self.offset() if offset is None else offset))
        return where

    def note_at(self, point: QPointF):
        """``(page, which, mark)`` for the note under a *viewport* point.

        The icon holds its size while the page grows under it, which is what
        `/F` NoZoom asks for, so this is in viewport units throughout and
        the zoom reaches only the corner it hangs from.

        Hit-tested through `note_icon_rect`, which is also what the painter
        uses, so what can be clicked is what can be seen by construction. Two
        ways of saying where a note is would drift -- and they would differ
        already, because the icon is not the mark's rectangle on a page that
        has been resized.
        """
        if self.marks is None:
            return None
        found = self.to_page(point)
        if found is None:
            return None
        index = found[0]
        try:
            marks = list(self.marks(index) or ())
        except Exception:       # noqa: BLE001 - a click must not raise
            marks = []
        # **The file's own comments too**, because this application draws
        # them: `_paint_marks` paints every note whoever made it, and an
        # icon that can be seen has to be one that can be picked up. Before
        # this a saved comment could not be opened or dragged at all.
        #
        # A reply is neither: it is drawn nowhere, so there is nothing here
        # to find. One made in this session sits at the corner of the mark
        # it answers, and finding it there put the pointer on a box that
        # nothing had drawn.
        marks = [m for m in marks
                 if not markup.is_reply(m) and not markup.is_status(m)]
        marks += self._file_notes(index)
        # And the other stamps the file brought, which `_file_notes` leaves
        # out because the renderer draws those -- they are page content.
        # They are still marks to take hold of.
        try:
            # (A Stamp now comes through `_file_notes`, which draws it.)
            # And the text boxes, which are taken hold of and dragged the
            # way a stamp is.
            marks += [m for m in self._file_marks.visible(index + 1)
                      if m.subtype == markup.FREETEXT]
        except Exception:       # noqa: BLE001 - a click must not raise
            pass
        # Last first: the most recently placed note is the one on top, which
        # is the one `_paint_marks` draws over the others.
        for which in range(len(marks) - 1, -1, -1):
            mark = marks[which]
            kind = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype)
            if kind not in (markup.TEXT, markup.STAMP, markup.FREETEXT,
                            *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK):
                continue
            if kind in markup.SHAPES:
                if self._shape_hit(index, mark, point):
                    return (index, which, mark)
                continue
            if kind == markup.LINE:
                if self._line_hit(index, mark, point):
                    return (index, which, mark)
                continue
            if kind in markup.POLYS:
                if self._poly_hit(index, mark, point):
                    return (index, which, mark)
                continue
            if markup.is_callout(mark):
                if self._callout_hit(index, mark, point):
                    return (index, which, mark)
                continue
            if kind == markup.INK:
                if self._ink_hit(index, mark, point):
                    return (index, which, mark)
                continue
            where = self.note_icon_rect(index, mark)
            if where is not None and where.contains(point):
                return (index, which, mark)
        return None

    def focusNextPrevChild(self, forward: bool) -> bool:
        """Tab steps through the form rather than out of the canvas.

        This hook and not `keyPressEvent`, which never sees the key: Qt takes
        Tab in `QWidget.event()` for focus traversal before any key handler
        runs. Handling it there looked right and did nothing -- Tab moved
        between the canvas and the page number box while the form sat
        untouched -- and the tests did not notice, because they called
        `keyPressEvent` directly and so tested a path the keyboard never uses.
        """
        if self._stepping:
            # Already moving: this is the traversal Qt runs as the old
            # editor goes away, not a key the reader pressed.
            return True
        if self._fields is not None and self.focus_step(forward=forward):
            return True
        return super().focusNextPrevChild(forward)

    def eventFilter(self, watched, event):
        """Tab out of a field editor steps to the next field.

        The editor is a real QLineEdit, which is what gives the selection,
        the clipboard, input methods and right-to-left text for nothing -- and
        it also means Qt's focus traversal gets Tab first unless it is taken
        here.
        """
        if (self._editing is not None and watched is self._editing[1]
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
            # Commit first: stepping closes the editor, and a value typed and
            # then tabbed away from is a value the user entered.
            self.finish_editing()
            self.focus_step(forward=event.key() == Qt.Key_Tab)
            return True
        return super().eventFilter(watched, event)

    def finish_editing(self):
        """Commit what was typed and take the editor away.

        A note's editor goes with it. Every caller means "nothing is being
        typed into the page any more", and there is nowhere that wants one of
        the two editors left open.

        Guarded against re-entry: `editingFinished` arrives again when the
        editor loses focus to its own removal, and without this the value
        would be committed twice -- two undo entries for one edit.

        Guarded against *traversal* for the same reason. Taking the editor
        away makes Qt look for somewhere else to put the keyboard, which
        reaches `focusNextPrevChild` and would step the form -- so merely
        clicking away from a field moved the focus to another one and drew a
        ring round it.
        """
        self.finish_text_box()
        if self._editing is None:
            return
        field, editor = self._editing
        self._editing = None
        text = editor.text()
        was, self._stepping = self._stepping, True
        try:
            editor.hide()
            editor.deleteLater()
        finally:
            self._stepping = was
        self.field_edited.emit(field, text)

    def editing(self):
        """The field being typed into, or None."""
        return self._editing[0] if self._editing else None

    def _field_rect(self, field):
        """Where a field is in the viewport, or None if it is not visible."""
        if self._layout.page_count <= field.page:
            return None
        height = self._layout.page_height(field.page)
        if height is None:
            return None
        zoom = self._layout.zoom
        page = self._layout.page_rect(field.page)
        left, bottom, right, top = field.rect
        where = QRectF(left * zoom + page.x(), (height - top) * zoom + page.y(),
                       (right - left) * zoom, (top - bottom) * zoom)
        where.translate(-self.offset())
        return where

    def _editor_font(self, field, height_px: float) -> QFont:
        """A screen font close to what the field will be written in.

        Close, not equal: the editor is a Qt widget and the appearance is a
        PDF font, and matching them exactly would mean embedding one in the
        other. What matters is that the text does not jump in size when the
        editor goes away, so the size is taken from the field and the family
        is left to the platform.
        """
        font = QFont(self.font())
        size = max(6.0, height_px * 0.62)
        font.setPixelSize(int(round(size)))
        return font

    def _refuses(self, field) -> bool:
        """Whether this field's document will not take an edit."""
        if self.field_locked is None:
            return False
        try:
            return bool(self.field_locked(field))
        except Exception:  # noqa: BLE001 - a click must not raise
            return False

    #: The reader's own behaviour: text selection, links, the caret.
    SELECT = "select"
    #: Markup tools. The canvas treats every one of them the same -- a drag
    #: that reports a rectangle -- so that what each *means* stays with the
    #: step that adds it rather than being decided here.
    HIGHLIGHT = "highlight"
    STRIKEOUT = "strikeout"
    UNDERLINE = "underline"
    NOTE = "note"
    #: **A gesture, not a tool.** The right-click menu's *Add note to
    #: text*: the comment tool marking a run of words rather than placing
    #: an icon, so it writes a `/Highlight`. It had an entry in the strip
    #: for two days, which Reader never had.
    NOTE_ON_TEXT = markup.NOTE_ON_TEXT
    #: *Draw*: a Pencil, a stroke at each press, drag and release, all of
    #: them one mark until it is finished by Complete, Return or another
    #: tool, and thrown away by Cancel or Escape.
    DRAW = "draw"

    #: *Replace Selected Text*: a strikeout over the words and a caret at
    #: their end, which the window writes as a pair. To the canvas it is a
    #: text tool like the strikeout it draws.
    REPLACE = "replace"
    #: *Insert Text*: a caret in the gap between two characters, carrying
    #: the words to insert. A text tool, so a drag selects as the others
    #: do -- and the caret goes at the end of what it selected -- but what
    #: it makes is a point, never a run.
    INSERT = "insert"
    #: *Add Text Comment*: a Text Box, made by a click -- a box of the
    #: standard size, its top left at the click -- or drawn by a drag from
    #: its top left to its bottom right.
    TEXTBOX = "textbox"
    #: *Rectangle/Square* and *Oval/Circle*: a box dragged out, or clicked
    #: out -- a click, a move and a second click -- from either corner;
    #: Shift makes it a square or a circle.
    RECTANGLE = "rectangle"
    OVAL = "oval"
    SHAPE_TOOLS = (RECTANGLE, OVAL)
    #: *Line* and *Arrow*: a line from its start to its end, dragged or
    #: clicked out the same way; Shift keeps it to steps of 45 degrees.
    LINE = "line"
    ARROW = "arrow"
    LINE_TOOLS = (LINE, ARROW)
    #: *Text Callout*: the tip of its leader, then the centre of its box,
    #: dragged or clicked out as a line is; Shift does nothing.
    CALLOUT = "callout"
    #: *Polygon*, *Cloud* and *Connected Lines*: a point at each press, the
    #: next segment following the pointer, finished by a double-click,
    #: Complete or Return and thrown away by Cancel or Escape.
    POLYGON = "polygon"
    CLOUD = "cloud"
    POLYLINE = "polyline"
    POLY_TOOLS = (POLYGON, CLOUD, POLYLINE)
    #: The tools that make a mark by two clicks as well as by a drag.
    CLICK_TOOLS = SHAPE_TOOLS + LINE_TOOLS + (CALLOUT,)

    #: The comment tool's twin, placing a `/Stamp` instead of a `/Text`.
    #: Its gesture is the same -- a point, and then the words -- and the
    #: only difference the canvas sees is where the point goes: a stamp is
    #: placed by its centre and a comment mark by its top left corner.
    STAMP = "stamp"
    #: *Stamps palette*: the stamp picked in the palette, placed centred on
    #: a click at its own size or sized by a drag, its proportions kept and
    #: its outline shown as it is dragged. Not `STAMP`, which places a
    #: Scalable Comment.
    STAMPS = "stamps"

    #: Tools whose geometry is a run of *text* rather than an area. They drag
    #: out a selection, exactly as reading does, because the quadrilaterals a
    #: `/Highlight` wants are what a text selection already produces -- which
    #: is why highlighting comes before the marks that need new hit-testing.
    TEXT_TOOLS = (HIGHLIGHT, STRIKEOUT, UNDERLINE, NOTE_ON_TEXT, NOTE,
                  REPLACE, INSERT)

    #: What a tool writes when its gesture turns out to be a run of words
    #: rather than a point. The comment tool is the only one with two, and
    #: the mark they make is a different subtype, so the gesture has to say
    #: which it was.
    OVER_TEXT = {NOTE: NOTE_ON_TEXT}

    #: Tools whose geometry is a point and a size of their own rather than an
    #: area dragged out. A sticky note's icon is the same size wherever it
    #: lands, so the gesture supplies a corner and nothing else -- and a
    #: scalable comment is placed the same way, except that the point it
    #: supplies is the centre rather than the corner. Which of the two it
    #: means is the window's business, not the canvas's: both arrive here
    #: as a point and a box of the icon's own size.
    #:
    #: The comment tool is in both: it marks text like the highlighter and
    #: places a point like this, and which it did is settled on release.
    POINT_TOOLS = (NOTE, STAMP)

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        """Choose what the pointer does. Markup tools draw; SELECT reads."""
        tool = tool or self.SELECT
        if tool == self._tool:
            return
        # A Pencil under way is kept, not lost, when another tool is chosen.
        self.finish_ink()
        self._tool = tool
        self._marking = None
        self._clicked_shape = False
        self._poly_drawing = None
        self._stamp_hover = None
        self.drawing_changed.emit()
        if (tool in self.CLICK_TOOLS or tool in self.POLY_TOOLS
                or tool in (self.DRAW, self.STAMPS)):
            # A shape or a line is drawn over the page, not over words: a
            # selection left from before is not what it is for.
            self.clear_selection()
        self._dragging_grip = None
        self._dragging_note = None
        self._preview = ()
        self.viewport().unsetCursor()
        self.viewport().update()
        self.tool_changed.emit(tool)

    def marking(self) -> bool:
        """Whether a markup tool is active, as against reading."""
        return self._tool != self.SELECT

    def marks_text(self) -> bool:
        """Whether the active tool marks text, and so selects rather than drags."""
        return self._tool in self.TEXT_TOOLS

    def marks_area(self) -> bool:
        """Whether the active tool drags out an area."""
        return self.marking() and not self.marks_text()

    def selection_quads(self):
        """The selection as ``(page, [rect, ...])`` in the page's own space.

        One rectangle per run, not one round the paragraph: a box spanning
        three lines would cover the margins and the gaps between them, and a
        highlight that does that is worse than none.

        **Measured by the text layer, not by the selection's own bounds.**
        Qt reports the glyphs' ink, which runs 2 to 6 points short of what a
        reader draws a highlight over; the loose boxes -- the font's ascent
        and descent -- are what Acrobat uses. Going through the same call
        the drag goes through also means a mark made from the menu is
        identical to one dragged out with the tool, rather than nearly so.

        The first page of the selection. `selection_quads_by_page` answers
        for every page it covers.
        """
        found = self.selection_quads_by_page()
        return found[0] if found else None

    def selection_quads_by_page(self) -> list:
        """The selection as ``[(page, [rect, ...]), ...]``, in page order.

        Every page it covers, for reading. Marking takes only a selection on
        one page: one that crosses a page break is refused, because it
        carries whatever the file stores between the two ends.
        """
        if not self._selection:
            return []
        return [found for page in sorted(self._selection)
                if (found := self._quads_on_page(page)) is not None]

    def _quads_on_page(self, page: int):
        """One page's worth of the selection, or None if it marks nothing."""
        box = self.page_box(page)
        height = self._layout.page_height(page)
        if box is None or height is None:
            return None
        runs = [polygon.boundingRect()
                for polygon in self._selection[page].bounds()]
        runs = [r for r in runs if r.width() > 0 and r.height() > 0]
        if not runs:
            return None

        def end(x: float, run) -> tuple:
            # Along the middle of the line, for the reason `mark_text` is: a
            # box's foot overlaps the line beneath it.
            middle = height - run.center().y()
            left, bottom, _right, _top = forms_module.from_displayed(
                (x, middle, x, middle), box)
            return (left, bottom)

        try:
            quads = tuple(self._glyphs.quads(
                page, end(runs[0].left(), runs[0]),
                end(runs[-1].right(), runs[-1])))
        except Exception:  # noqa: BLE001 - a page with no text layer marks nothing
            return None
        if not quads:
            return None
        return (page, [self.to_source(page, quad) for quad in quads])

    def insertion_point(self, point: QPointF):
        """``(page, box)`` for a caret at the gap nearest a viewport point.

        ``box`` is the character beside the gap, cut off at the gap, in the
        source page's space: its right-hand edge is where the caret goes and
        its height is the line's, which is what `markup.caret_rect` sizes a
        caret from -- the same loose box a Replace caret is sized from.

        None off the text: the point has to be level with a character and
        within one character's width of it.
        """
        found = self.to_page(point)
        if found is None:
            return None
        index = found[0]
        at = self.page_point(index, point)
        if at is None:
            return None
        x, y = at
        try:
            boxes = self._glyphs.boxes(index)
            nearest = self._glyphs.nearest(index, x, y)
        except Exception:  # noqa: BLE001 - a page with no text has no gap
            return None
        if nearest is None:
            return None
        left, bottom, right, top, _blank = boxes[nearest]
        width = right - left
        if not bottom <= y <= top or x < left - width or x > right + width:
            return None
        gap = left if abs(x - left) < abs(x - right) else right
        return (index, self.to_source(index, (left - width, bottom, gap, top)))

    def mark_the_selection(self, tool: str) -> bool:
        """Mark up the selected text with ``tool``. False if there is none.

        The selection goes once it has been marked: what was selected is now
        a mark, and leaving the blue over the top of it says there are two
        things there.
        """
        # Text is marked one page at a time: a selection across a page break
        # carries whatever lies between, often unseen.
        if self.selection_is_across_pages():
            return False
        found = self.selection_quads_by_page()
        if not found:
            return False
        if tool == self.INSERT:
            # A point, not a run: the caret goes at the end of what was
            # selected, which is the last quadrilateral's right-hand end.
            page, quads = found[-1]
            found = [(page, [quads[-1]])] if quads else []
            if not found:
                return False
        self.marks_drawn.emit(
            self.OVER_TEXT.get(tool, tool),
            [(page, list(quads)) for page, quads in found])
        self.clear_selection()
        return True

    def focused_field(self):
        """The field Tab has reached, or None."""
        return self._focused

    def focus_field(self, field) -> None:
        """Put keyboard focus on a field, scroll to it, and open it if it
        takes typing.

        Opening the editor is what makes tabbing through a form work the way
        it does anywhere else: arriving at a text field should leave you able
        to type, not needing to click first.
        """
        self.finish_editing()
        self._focused = field
        if field is None:
            self.viewport().update()
            return
        self._scroll_to_field(field)
        if field.fillable and not self._refuses(field) \
                and field.kind in ("/Tx", "/Ch"):
            self.edit_field(field)
        else:
            # A tick box has no editor, so nothing else would hold the
            # keyboard: without this the next Tab goes to whatever Qt thinks
            # is next -- the page number box -- and the form is left behind.
            self.setFocus()
        self.viewport().update()

    def focus_step(self, forward: bool = True) -> bool:
        """Move focus to the next field, or the previous one.

        False when the document has no fields, so the caller can let Tab mean
        what it usually means instead of swallowing it.
        """
        if self._fields is None or self._stepping:
            return False
        field = self._fields.step(self._focused, forward)
        if field is None:
            return False
        self._stepping = True
        try:
            self.focus_field(field)
        finally:
            self._stepping = False
        return True

    def _scroll_to_field(self, field) -> None:
        """Bring a field into view, without moving if it is already there."""
        rect = self._field_rect(field)
        viewport = self.viewport().rect()
        if rect is not None and viewport.contains(rect.toRect(), False):
            return
        height = self._layout.page_height(field.page)
        if height is None:
            return
        # A little above the field rather than flush with the top edge, so
        # that its label -- which is page content, not part of the field --
        # is on screen with it.
        into = min(height, field.rect[3] + 48)
        self.go_to_position((field.page, into))

    def set_page_boxes(self, boxes) -> None:
        """The laid-out box of every page, for placing a mark.

        Plain data, kept here rather than reached through the field map:
        a page with no widgets still needs its box, and closing the field map
        must not take the geometry with it.
        """
        self._boxes = list(boxes or ())

    def page_box(self, index: int):
        """``(left, bottom, width, height, rotation)`` for a page, or None."""
        if 0 <= index < len(self._boxes):
            return self._boxes[index]
        return None

    def set_page_scales(self, scales) -> None:
        """The resize factor of every page, as the page list holds it.

        A mark lives in the *source* page's space and the document on
        screen is an export with every resize already applied, so this is the
        one number that cannot be read back out of what is being shown. The
        page list is the only thing that still knows it, which is why it is
        pushed in here rather than computed from the document like the boxes.
        """
        self._scales = [float(s) if s else 1.0 for s in (scales or ())]

    def page_scale(self, index: int) -> float:
        """How much bigger the page on screen is than the page a mark is in."""
        if 0 <= index < len(self._scales):
            scale = self._scales[index]
            return scale if scale > 0 else 1.0
        return 1.0

    def to_source(self, index: int, rect):
        """A rectangle on the page being shown, in the source page's space.

        The *last* step of placing a mark, after the crop and the turn, and it
        is only a division because `export._scale` only multiplies: a resize
        scales the page's whole coordinate space, content and boxes together.

        Why source space rather than the space the canvas hands back, which
        would need no arithmetic at all: a mark stored in output coordinates
        moves the next time its page is resized, because the space it was
        measured in is gone. Keeping the mark in source space was settled
        early and then went uncoded for a while -- a note on a page later
        scaled by half was written at its old coordinates onto paper half the
        size, which is off the page entirely.
        """
        scale = self.page_scale(index)
        if scale == 1.0:
            return tuple(rect)
        return tuple(v / scale for v in rect)

    def from_source(self, index: int, rect):
        """The inverse: a mark's own rectangle, on the page being shown."""
        scale = self.page_scale(index)
        if scale == 1.0:
            return tuple(rect)
        return tuple(v * scale for v in rect)

    def mark_rect(self, start: QPointF, end: QPointF):
        """Two *viewport* points to ``(page, rect)`` in the page's own space.

        The rectangle a mark is stored with. Three frames are crossed on
        the way: viewport pixels to document pixels, document pixels to the
        laid-out page's frame -- which runs *down* from the top left, where a
        PDF rectangle runs up from the bottom -- and then back through the
        crop and the turn with `forms.from_displayed`.

        The page is the one the drag *began* on, so a selection that wanders
        off the bottom stays on the page it started on rather than jumping.
        None when it did not begin on a page at all.
        """
        index = self.page_at(start)
        if index is None:
            return None
        box = self.page_box(index)
        if box is None:
            return None
        height = self._layout.page_height(index)
        if height is None:
            return None
        first = self._layout.point_in_page(index, self.to_document(start))
        last = self._layout.point_in_page(index, self.to_document(end))
        # Up from the bottom, which is the frame `from_displayed` expects.
        shown = (first.x(), height - first.y(), last.x(), height - last.y())
        return index, self.to_source(
            index, forms_module.from_displayed(shown, box))

    def set_mark_styles(self, styles) -> None:
        """``{tool: kind}``, so a preview knows what it is previewing.

        The *colour* is asked for separately, through `mark_colour`: it is
        the window's to answer because it changes as the user picks one,
        and a copy kept here would be a copy that goes stale.
        """
        self._mark_styles = dict(styles or {})

    def page_point(self, index: int, point: QPointF):
        """One viewport point in ``index``'s own space, or None.

        The same three frames `mark_rect` crosses, for a point rather than a
        rectangle. Not clamped to the page, and deliberately: the text layer
        answers with the character nearest whatever it is given, so a drag
        that runs off the bottom takes the last line rather than stopping
        dead -- and cannot reach the page below, because that page's glyphs
        are not in this layer.
        """
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return None
        here = self._layout.point_in_page(index, self.to_document(point))
        flat = (here.x(), height - here.y(), here.x(), height - here.y())
        left, bottom, _right, _top = forms_module.from_displayed(flat, box)
        return (left, bottom)

    #: Subtypes a click can land on. The text markups are areas you can aim
    #: at; a note is reached by its icon, which `note_at` already answers for.
    SELECTABLE = ("/Highlight", "/StrikeOut", "/Underline", "/Squiggly",
                  markup.TEXT, markup.STAMP, markup.CARET, markup.FREETEXT,
                  *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK)

    #: Of those, the ones drawn *over* a run of words. A comment's icon is
    #: the odd one: it is placed rather than sized, so it has no run to
    #: take hold of and no badge to wear -- the icon is already the sign
    #: that there is something to read.
    QUADDED_SELECTABLE = ("/Highlight", "/StrikeOut", "/Underline",
                          "/Squiggly")

    def marks_on(self, index: int):
        """Every mark on a page that a click could be aimed at.

        Both kinds, in the order they are drawn: the document's own first and
        the user's over them, so that a mark made on top of one that was
        already there is the one a click finds.
        """
        found = [(mark, False) for mark in self._file_marks.visible(index + 1)
                 if mark.subtype in self.SELECTABLE
                 and not markup.is_reply(mark)
                 and not self._paired_caret(index, mark)]
        if self.marks is not None:
            try:
                mine = self.marks(index) or ()
            except Exception:   # noqa: BLE001 - a click must not raise
                mine = ()
            found += [(mark, True) for mark in mine
                      if mark.kind in self.SELECTABLE
                      and not markup.is_reply(mark)
                      and not markup.is_status(mark)
                      and not self._paired_caret(index, mark)]
        return found

    @staticmethod
    def mark_boxes(mark):
        """Where a mark is, as ``(left, bottom, right, top)`` rectangles.

        The one place that knows the two kinds carry their geometry
        differently: a mark of the user's is an `Annotation` whose quads are
        already rectangles, while one read out of the file is a `Mark` whose
        quads are the four corners `/QuadPoints` holds.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind == markup.TEXT:
            # **Where the icon is drawn**, which is its own size hung
            # from the rectangle's top left -- and once a page has been
            # resized the rectangle is not that box.
            return [markup.icon_box(mark.rect,
                                    getattr(mark, "icon",
                                            markup.DEFAULT_ICON))]
        if kind == markup.STAMP:
            # Its rectangle, and nothing cleverer: a stamp's box *is* the
            # bounding box of what it draws, at whatever size and angle it
            # has been given, which is what the fit to `/Rect` guarantees.
            return [tuple(mark.rect)]
        if kind in markup.SHAPES:
            # The box it is drawn in, without a cloud's reach: where its
            # badge hangs from.
            return [markup.shape_box(mark)]
        if isinstance(mark, markup.Annotation):
            return list(mark.quads) or [mark.rect]
        return mark.boxes()

    #: How far off a mark's ink a click may land and still take it, in
    #: *device* pixels. In points it would shrink with the zoom and a mark
    #: would get harder to grab the further out you were, which is the
    #: opposite of what a tolerance is for. A cross-out's stroke is under a
    #: point thick, so without this it is unhittable.
    INK_TOLERANCE = 3.0

    def mark_screen_boxes(self, index: int, mark, offset=None):
        """Where a mark is on screen, as viewport rectangles.

        **One answer for the outline, the hover and the hit-test**, because
        three ways of saying where a mark is are three ways to disagree.

        A note is the exception the other kinds do not have. Its icon holds
        its size while the page is zoomed, so its box comes from
        `note_icon_rect`; everything else is ink on the paper and grows with
        the page, which is what `quad_on_screen` does. Drawing the outline
        the second way round an icon drawn the first gave a box that was
        right at 100% and too big at every other zoom.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind in (markup.TEXT, markup.STAMP, markup.FREETEXT,
                    *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK):
            # Both comments, a text box, the shapes and a line, through one
            # call: it is the one that knows a comment mark holds its size
            # and a stamp does not, and the one that knows a gesture in
            # flight outranks what is on record.
            where = self.note_icon_rect(index, mark, offset)
            return [where] if where is not None else []
        is_mine = isinstance(mark, markup.Annotation)
        found = []
        for quad in self.mark_boxes(mark):
            where = self.quad_on_screen(index, quad, offset, scaled=is_mine)
            if where is not None:
                found.append(where)
        # A *Replace Selected Text* pair is outlined as one mark: the box
        # round the run's last line takes in the caret at its end.
        caret = self.caret_of(index, mark)
        if caret is not None and found:
            where = self.quad_on_screen(index, caret.rect, offset,
                                        scaled=is_mine)
            if where is not None:
                found[-1] = found[-1].united(where)
        return found

    def ink_on_screen(self, index: int, mark, quad, scaled: bool):
        """Where one of a mark's quadrilaterals is *drawn*, on screen.

        Grown by `INK_TOLERANCE`, which is the whole of what makes a stroke
        a target rather than a hairline.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind == markup.TEXT:
            # The icon, which is not the page's to scale. Measured the other
            # way a click landed on empty paper beside it at any zoom above
            # 100%, because the box had grown and the glyph had not.
            where = self.note_icon_rect(index, mark)
        else:
            where = self.quad_on_screen(
                index, markup.ink_box(kind, quad), scaled=scaled)
        if where is None:
            return None
        return where.adjusted(-self.INK_TOLERANCE, -self.INK_TOLERANCE,
                              self.INK_TOLERANCE, self.INK_TOLERANCE)

    def mark_at(self, point: QPointF):
        """The mark under a *viewport* point, or None.

        **By its ink, not by the box its quadrilaterals describe.** Over
        the words a cross-out runs through, but off the line itself, there
        is no mark -- which is Reader, and which is what keeps a page of
        overlapping marks from being a thicket.

        Last one first, so the topmost is found: marks are drawn in order and
        the one drawn last is the one a reader sees on top.
        """
        index = self.page_at(point)
        if index is None:
            return None
        for mark, is_mine in reversed(self.marks_on(index)):
            kind = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype)
            # **A drawing by what is drawn**: a line by its line and ends, a
            # rectangle or an oval by its outline, or its inside when filled
            # -- the test a drag already used. By its box, words under an
            # empty rectangle or inside a line's reach could not be
            # selected.
            if kind in markup.SHAPES:
                if self._shape_hit(index, mark, point):
                    return (index, mark)
                continue
            if kind == markup.LINE:
                if self._line_hit(index, mark, point):
                    return (index, mark)
                continue
            if kind in markup.POLYS:
                if self._poly_hit(index, mark, point):
                    return (index, mark)
                continue
            if markup.is_callout(mark):
                if self._callout_hit(index, mark, point):
                    return (index, mark)
                continue
            if kind == markup.INK:
                if self._ink_hit(index, mark, point):
                    return (index, mark)
                continue
            for quad in self.mark_boxes(mark):
                where = self.ink_on_screen(index, mark, quad, is_mine)
                if where is not None and where.contains(point):
                    return (index, mark)
            # The caret is part of the mark, so clicking it is clicking the
            # strikeout that stands for the pair.
            caret = self.caret_of(index, mark)
            if caret is not None:
                where = self.quad_on_screen(index, caret.rect,
                                            scaled=is_mine)
                if where is not None and where.adjusted(
                        -self.INK_TOLERANCE, -self.INK_TOLERANCE,
                        self.INK_TOLERANCE,
                        self.INK_TOLERANCE).contains(point):
                    return (index, mark)
        return None

    @staticmethod
    def _covers_text(found) -> bool:
        """Whether the mark in ``found`` hides the words it is on."""
        if found is None:
            return False
        mark = found[1]
        return (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype) in markup.FILLED

    def selected_mark(self):
        """``(page, mark)`` for what is selected, or None."""
        return self._selected

    def repaint_edited(self, index: int, data) -> None:
        """Show ``index`` as it is now, rendered from a one-page document.

        ``data`` is that document's bytes, or None to go back to rendering
        the page from the document everything else comes from. The window
        builds it, because only the window knows what has been changed; the
        canvas only knows where to put the result.
        """
        self._pages.set_edited(index, data)
        self.viewport().update()

    def set_mark_buttons(self, widget) -> None:
        """The bar to show beside a selected mark, or None for none."""
        self._mark_buttons = widget
        self._place_mark_buttons()

    def _place_mark_buttons(self) -> None:
        """Put the bar where the mark is now, or take it away.

        Called whenever the mark could have moved under it -- a scroll, a
        zoom, a resize -- because the bar floats over the viewport and the
        page underneath does not.
        """
        if self._mark_buttons is None:
            return
        if self._selected is None:
            self._mark_buttons.hide()
            return
        if self._shaping is not None:
            # **Out of the way while the mark is being moved or reshaped.**
            # The outline and the handles follow, because they say where
            # the mark is; three buttons are not a description of the mark
            # and chasing the pointer with them only makes them harder to
            # aim at when you let go. Acrobat hides its own.
            self._mark_buttons.hide()
            return
        # Above everything the selection shows, the turning handle
        # included: the bar is placed over the topmost box it is given, and
        # a stamp's fifth handle stands exactly where that put it.
        self._mark_buttons.show_for(self.selection_on_screen()
                                    + self.grips()[4:])

    def _hover_mark(self, found) -> None:
        """Note the mark under the pointer, repainting only when it changes.

        A move event arrives for every pixel, and the hit test runs over
        every quadrilateral on the page -- 180 marks on a page of the markup
        sample -- so repainting unconditionally would redraw the page
        continuously while the pointer merely crossed it.
        """
        if found == self._hovered:
            return
        self._hovered = found
        self.viewport().update()

    def hovered_mark(self):
        """``(page, mark)`` for what the pointer is over, or None."""
        return self._hovered

    def select_mark(self, found) -> None:
        """Select ``(page, mark)``, or None for nothing."""
        if found == self._selected:
            return
        self._selected = found
        self.viewport().update()
        self._place_mark_buttons()
        self.mark_selected.emit(found is not None)

    def clear_marks(self) -> None:
        """Forget the document's own marks and anything selected among them."""
        self._file_marks = markup.MarkMap()
        self._hovered = None
        # Which windows are shut is about the document that had them.
        self._shut_notes = set()
        self.select_mark(None)

    def selection_on_screen(self):
        """The selected mark's quadrilaterals as viewport rectangles.

        Empty when nothing is selected or its page is not laid out. What the
        border is drawn round and what the buttons are placed against, so
        that both are measured from one answer.
        """
        if self._selected is None:
            return []
        index, mark = self._selected
        return self.mark_screen_boxes(index, mark)

    def _preview_marks(self, index: int):
        """The gesture in flight, as a mark, so it is drawn like one.

        Through `_paint_marks` rather than a painter of its own. The feedback
        used to be the reader's text selection, which crosses pages and is
        drawn tight to the ink, while the mark it produced stopped at the
        page and covered the line: what you saw was never what you got. One
        list of quadrilaterals now, drawn by one piece of code, so the two
        cannot disagree again.
        """
        if self._preview and self._dragging_grip is not None:
            which, page, mark, _anchor = self._dragging_grip
            if page != index:
                return ()
            kind = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype)
            if kind not in markup.QUADDED:
                return ()
            quads = tuple(self.to_source(index, q) for q in self._preview)
            del which
            band = markup.Annotation(
                kind, index, markup.bounding_rect(quads),
                colour=self.DRAGGED, quads=quads,
                opacity=self.DRAGGED_OPACITY)
            if quads and self.caret_of(index, mark) is not None:
                # A pair's caret follows the end of the run being proposed,
                # in the same neutral grey, while the old one stays put.
                return (band, markup.Annotation(
                    markup.CARET, index, markup.caret_rect(quads[-1]),
                    colour=self.DRAGGED, opacity=self.DRAGGED_OPACITY))
            return (band,)
        # A markup tool in flight has no preview of its own: what it is
        # about to mark is the selection, drawn in the colour it will be
        # made in by `_paint_selection`.
        return ()

    def icon_rect(self, point: QPointF):
        """One viewport point to the page-space box of a fixed-size icon.

        Expanded on the *laid-out* page and only then turned back into the
        page's own space, so that the corner under the pointer is the icon's
        top left as drawn. Expanding it in page space instead looks right
        until the page is turned, and then which corner lands under the
        pointer is whatever the turn makes it: measured, the icon was drawn
        to the *left* of the click at `/Rotate` 90, above and to the left at
        180, and below it at 270.

        A viewer draws the icon at the top left of `/Rect` in page space and
        then turns the page, so a box chosen this way comes out under the
        pointer here and in every other reader alike.
        """
        index = self.page_at(point)
        if index is None:
            return None
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return None
        where = self._layout.point_in_page(index, self.to_document(point))
        # Up from the bottom, which is the frame `from_displayed` expects.
        # The icon's size is fixed on the page *as shown*, so it is expanded
        # here and divided afterwards: on a page resized to half, a note is
        # 40 points in the source space and comes back out at 20.
        icon = self.note_icon() if self.note_icon else markup.DEFAULT_ICON
        shown = markup.note_rect(where.x(), height - where.y(),
                                 *markup.icon_size(icon))
        return index, self.to_source(
            index, forms_module.from_displayed(shown, box))

    def set_field_map(self, fields):
        """The widgets of the document being shown, drawn and hit-tested."""
        self._fields = fields
        self.viewport().update()

    def fields(self):
        return self._fields

    def field_at(self, point: QPointF):
        """The form field under a *viewport* point, or None.

        The y axis is the whole of the work. A page point here is measured
        down from the top left, the way every other coordinate in this canvas
        is; a PDF rectangle is measured up from the bottom. Mapping one to the
        other needs the page's height, which the layout has and the field map
        deliberately does not -- `forms` stays in PDF coordinates so that it
        can be read and tested without a canvas.
        """
        if self._fields is None:
            return None
        found = self.to_page(point)
        if found is None:
            return None
        index, page_point = found
        height = self._layout.page_height(index)
        if height is None:
            return None
        return self._fields.at(index, page_point.x(), height - page_point.y())

    def follow(self, link) -> bool:
        """Go where ``link`` points, or emit it if that is outside the document.

        Returns False for a link that goes nowhere usable, so a caller can say
        so rather than appearing to do nothing.
        """
        if link is None:
            return False
        url = link.url()
        if url is not None and not url.isEmpty():
            self.external_link_activated.emit(url)
            return True
        page = link.page()
        if page < 0 or page >= self._layout.page_count:
            return False
        # `location` is (0, 0) for every destination type but /XYZ -- QtPdf
        # understands no other, verified across all six. So a
        # /FitR or /FitH link lands at the top of the right page rather than at
        # the right spot on it, which is the document's fault and not ours, and
        # is still better than not moving at all.
        #
        # It can also be NaN. QtPdf logs "invalid location and/or zoom" for
        # these and hands back what it parsed; the Handbook's bookmarks show
        # "nan nan nan" in that warning. NaN compares false against everything,
        # including zero, so it slips past a == 0 test and reaches
        # int(round(nan)), which raises ValueError and kills the click.
        where = link.location()
        if where is None or not _is_finite_point(where) or (
                where.x() == 0 and where.y() == 0):
            self.go_to_page(page)
        else:
            self.go_to(page, where)
        return True

    # -- search ------------------------------------------------------------

    def set_search_model(self, model):
        """Highlight this `find.TextSearch`'s hits. `QPdfView` drew these for us."""
        if self._search is not None:
            try:
                self._search.changed.disconnect(self._search_changed)
            except (RuntimeError, TypeError):  # already gone, or never connected
                pass
        self._search = model
        if model is not None:
            model.changed.connect(self._search_changed)
        self.viewport().update()

    def _search_changed(self, *_args):
        self.viewport().update()

    def set_current_search_result(self, index: int):
        """Emphasise one hit among the highlights, and scroll it into view."""
        self._search_result = index
        if self._search is None or index < 0:
            self.viewport().update()
            return
        hit = self._search.hit(index)
        if hit is None:
            self.viewport().update()
            return
        rects = hit.rectangles()
        if rects:
            self.go_to(hit.page, rects[0].topLeft())
        self.viewport().update()

    def _paint_search(self, painter, index: int, offset: QPointF):
        """Draw this page's hits, the current one picked out.

        Translucent fill rather than an outline, so a hit inside dense text is
        visible without hiding the word it found.
        """
        if self._search is None:
            return
        try:
            hits = self._search.hits_on_page(index)
        except (RuntimeError, AttributeError):  # pragma: no cover - model gone
            return
        if not hits:
            return
        current = None
        if self._search_result >= 0:
            found = self._search.hit(self._search_result)
            if found is not None and found.page == index:
                current = [QRectF(r) for r in found.rectangles()]
        for hit in hits:
            for rect in hit.rectangles():
                drawn = self._layout.rect_from_page(index, rect)
                drawn.translate(-offset)
                is_current = current is not None and any(
                    abs(rect.x() - c.x()) < 0.01 and abs(rect.y() - c.y()) < 0.01
                    for c in current)
                painter.fillRect(drawn, SEARCH_CURRENT if is_current else SEARCH_HIT)

    # -- input -------------------------------------------------------------

    @staticmethod
    def link_description(link) -> str:
        """Where a link goes, for a tooltip. Empty if it goes nowhere."""
        if link is None:
            return ""
        url = link.url()
        if url is not None and not url.isEmpty():
            return url.toString()
        page = link.page()
        return _("Page {}").format(page + 1) if page >= 0 else ""

    def mouseMoveEvent(self, event):
        """A pointing hand over a link, and a tooltip saying where it goes.

        The tooltip is worth more here than in most readers. Most of this
        document's links are not the document's at all -- PDFium infers them
        from the text -- so what a link points
        at is not always what the words under the cursor appear to say, and a
        truncated or rejoined URL is invisible until you have already followed
        it.

        Set as the viewport's tooltip rather than shown directly, so Qt supplies
        the usual hover delay and placement, and only when the target changes:
        re-setting the same text restarts that delay and the tooltip never
        appears while the pointer drifts inside one link.
        """
        position = QPointF(event.position())

        # Under every tool, and before anything else looks at the pointer:
        # knowing a mark is there does not depend on what you would do to it.
        # Not while a gesture is running, though -- a drag is making a mark,
        # and outlining the ones it passes over is noise.
        self._hover_mark(None if event.buttons() & Qt.LeftButton
                         else self.mark_at(position))

        if self._marking is not None and (
                event.buttons() & Qt.LeftButton or self._clicked_shape):
            self._marking = (self._marking[0], position)
            self.viewport().update()
            return

        if self._dragging_note is not None and event.buttons() & Qt.LeftButton:
            page, mark, grab, at, moved = self._dragging_note
            # A locked mark stays where it is, so the press is only ever a
            # click: it still selects the mark and opens its note.
            if not moved and not getattr(mark, "locked", False) and (
                    (position - at).manhattanLength()
                    > QApplication.startDragDistance()):
                moved = True
            if moved and self._callout_drag is not None:
                self._dragging_note = (page, mark, grab, position, True)
                self.viewport().setCursor(Qt.SizeAllCursor)
                self._callout_dragged(position)
                return
            if moved:
                self._dragging_note = (page, mark, grab, position, True)
                self.viewport().setCursor(Qt.SizeAllCursor)
                # Everything that draws this mark follows it, rather than
                # the glyph going on ahead and its outline staying behind.
                taken = self._note_rect_at(page, mark, position - grab)
                if taken is not None:
                    self._shaping = (
                        mark, tuple(taken),
                        float(getattr(mark, "rotate", 0.0) or 0.0))
                    self._place_mark_buttons()
                self.viewport().update()
            return

        if (self._callout_drag is not None and self._dragging_note is None
                and event.buttons() & Qt.LeftButton):
            self._callout_dragged(position)
            return

        if self._poly_drawing is not None:
            page, points, _pointer = self._poly_drawing
            self._poly_drawing = (page, points, position)
            self.viewport().update()
            return

        if self._ink_drawing is not None and self._ink_drawing["live"]:
            if event.buttons() & Qt.LeftButton:
                self._ink_add(position)
            return

        if self._ink_resizing is not None and event.buttons() & Qt.LeftButton:
            self._ink_resized(position)
            return

        if self._stamp_resizing is not None and event.buttons() & Qt.LeftButton:
            self._stamp_resized(position)
            return

        if self._dragging_vertex is not None and event.buttons() & Qt.LeftButton:
            page, mark, which = self._dragging_vertex
            points = list(self._poly_shaping[1])
            mine = isinstance(mark, markup.Annotation)
            target = self._vertex_snapped(page, mark, points, which, position)
            at = self._point_on(page, target, mine)
            if at is not None:
                points[2 * which:2 * which + 2] = at
                self._poly_shaping = (mark, tuple(points))
                self._place_mark_buttons()
                self.viewport().update()
            return

        if self._dragging_line_end is not None and event.buttons() & Qt.LeftButton:
            page, mark, which = self._dragging_line_end
            points = list(self._line_shaping[1])
            mine = isinstance(mark, markup.Annotation)
            # The other end holds still, and Shift turns this one to 45
            # degrees about it.
            other = (points[2], points[3]) if which == 0 else (points[0], points[1])
            held = self.quad_on_screen(page, (*other, *other), scaled=mine)
            target = position if held is None else self._angled(held.center(), position)
            at = self._point_on(page, target, mine)
            if at is not None:
                points[2 * which:2 * which + 2] = at
                self._line_shaping = (mark, tuple(points))
                self._place_mark_buttons()
                self.viewport().update()
            return

        if self._dragging_stamp is not None and event.buttons() & Qt.LeftButton:
            page, mark, which, centre = self._dragging_stamp
            kind = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype)
            if kind == markup.FREETEXT:
                shaped = self._text_box_shaped(page, mark, which, centre,
                                               position)
            elif kind in markup.SHAPES:
                shaped = self._shape_shaped(page, mark, which, centre,
                                            position)
            else:
                shaped = self._stamp_shaped(page, mark, which, centre,
                                            position)
            if shaped is not None and (
                    self._shaping is None or self._shaping[1:] != shaped):
                self._shaping = (mark, shaped[0], shaped[1])
                self._place_mark_buttons()
                self.viewport().update()
            return

        if self._dragging_grip is not None and event.buttons() & Qt.LeftButton:
            _which, page, _mark, anchor = self._dragging_grip
            quads = self._grip_quads(page, anchor, position)
            if quads != self._preview:
                self._preview = quads
                self.viewport().update()
            return

        if self._press is not None and event.buttons() & Qt.LeftButton:
            if (position - self._press).manhattanLength() > QApplication.startDragDistance():
                self._selecting = True
            if self._selecting:
                found = self.to_page(position)
                if found is None and self._layout.page_count:
                    # Dragged into a margin or a gap: carry on from the nearest
                    # page rather than stopping the selection dead.
                    document_point = self.to_document(position)
                    nearest = self._layout.nearest_page(document_point.y())
                    found = (nearest,
                             self._layout.point_in_page(nearest, document_point))
                if found is not None:
                    self._extend_selection(*found)
                super().mouseMoveEvent(event)
                return

        # A grip comes first, as it does on the press: it belongs to the
        # mark already picked up, and a comment's icon lying over it would
        # otherwise make the end of a highlight impossible to take hold of.
        over_handle = self.grip_at(position)
        shaped = self._shaping_cursor(over_handle)
        if shaped is not None:
            self.viewport().setCursor(shaped)
            self._set_tooltip("")
            super().mouseMoveEvent(event)
            return
        note = (None if over_handle is not None
                else self.note_at(position))
        named = False
        if note is not None:
            # Read without opening anything. A note's whole value is its text,
            # and a document covered in icons you have to click one at a time
            # to read is a filing cabinet. Before the tool branches below,
            # because reading a note does not depend on what the pointer is
            # for.
            #
            # **And it falls through to the panel below.** The tooltip is a
            # second way of saying the same thing and a poorer one -- it
            # waits for the pointer to settle, says nothing about replies
            # or status, and goes away on its own. An icon used to get it
            # instead of the panel every other mark gets, because it
            # returned here.
            # **A crosshair, which is what says "this can be dragged".**
            # The point you press is the point that lands where you let go,
            # so the pointer names a point rather than a thing. A comment's
            # icon shows one whenever the pointer is over it; a stamp shows
            # one once it has been picked up, and an arrow before that --
            # it is a thing on the page until you have hold of it.
            kind_here = (note[2].kind
                         if isinstance(note[2], markup.Annotation)
                         else note[2].subtype)
            # **The move cursor over anything that can be dragged**, held
            # or not, and over nothing that cannot: a locked mark stays put.
            # One rule for the comment, the scalable comment and the text
            # box, where Acrobat has three -- a crosshair over one, an arrow
            # until picked up over another, nothing until picked up over
            # the third.
            self.viewport().setCursor(
                Qt.ArrowCursor if getattr(note[2], "locked", False)
                else Qt.SizeAllCursor)
            named = True
            if kind_here == markup.TEXT or kind_here == markup.STAMP:
                self._set_tooltip(note[2].contents or _("Empty note"))

        # A note hanging off a highlight reads the same way. The badge is
        # what says there is one; this is what says what it says, and it
        # answers over the whole mark rather than only over the badge,
        # because that is where the pointer goes.
        # A grip, or the mark it belongs to, is a thing you take hold of.
        # The I-beam below promises that a drag here selects text, and over
        # a mark it does not: it picks the mark up, or moves its end.
        #
        # The two are not the same hold, so they do not get the same cursor.
        # Over the mark, an arrow -- this is a thing, not text. Over a grip,
        # a diagonal resize arrow, which is what Acrobat shows and which
        # suits where the two grips are: the start sits at the top left of
        # the run and the end at the bottom right, so both lie on the same
        # north-west to south-east diagonal.
        over_grip = self.grip_at(position) is not None
        found = None if self._text_through else self.mark_at(position)
        over_mark = not self._text_through and (over_grip or found is not None)
        if over_mark and not named and not (event.buttons() & Qt.LeftButton):
            # **An arrow only where the mark covers the words.** Over a
            # highlight there is no text left uncovered, so the pointer
            # says "this is a thing". Over a cross-out or an underline the
            # words are still there and still selectable, and Reader keeps
            # the I-beam -- taken from the owner on 2026-11-05, who has it
            # for highlight and not for the other two.
            self.viewport().setCursor(
                Qt.SizeFDiagCursor if over_grip
                else Qt.ArrowCursor if self._covers_text(found)
                else Qt.IBeamCursor)

        carried = self.note_badge_at(position) or self._marked_note_at(position)
        if carried is not None:
            if getattr(carried[1], "popup_open", False):
                # The file says this mark's window was showing when it was
                # saved, so hovering gives the thread rather than a summary
                # of it -- which is the whole of what the flag is used for
                # here. The window decides whether it is already showing.
                found = self.mark_at(position)
                if found is not None and not self.note_window_is_shut(*found):
                    self._show_note_panel(None, position)
                    self.note_wanted.emit(*found)
                    super().mouseMoveEvent(event)
                    return
            # Drawn, not a tooltip. Reader puts a panel at the pointer and
            # leaves it there; a tooltip waits for the pointer to settle,
            # vanishes on its own and is easy to miss entirely -- which is
            # what it did.
            self._show_note_panel(carried[1], position, carried[0])
            super().mouseMoveEvent(event)
            return
        self._show_note_panel(None, position)
        if over_mark:
            self._set_tooltip("")
            super().mouseMoveEvent(event)
            return

        if self.marks_area():
            # A crosshair everywhere, including over a field: the field still
            # takes the press, and a cursor that promised otherwise would be
            # the lie. The I-beam is wrong here either way.
            self._ink_cursor()
            if self._tool == self.STAMPS:
                # The stamp follows the pointer, under the crosshair.
                self._stamp_hover = position
                self.viewport().update()
            self._set_tooltip("")
            super().mouseMoveEvent(event)
            return
        if self.marks_text():
            # An I-beam, because this gesture *is* selecting text.
            self.viewport().setCursor(Qt.IBeamCursor)
            self._set_tooltip("")
            super().mouseMoveEvent(event)
            return

        link = self.link_at(position)
        if named:
            # A comment under the pointer already said what the cursor
            # should be, and it is not the text underneath it: setting one
            # here would undo that, which is how the crosshair over a
            # comment came and went within the same mouse move.
            pass
        elif link is not None:
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            found = self.to_page(position)
            if found is not None and self._text.contains_text(*found):
                self.viewport().setCursor(Qt.IBeamCursor)
            else:
                self.viewport().unsetCursor()
        if not named:
            self._set_tooltip(self.link_description(link))
        super().mouseMoveEvent(event)

    #: The eight compass directions a resize handle can point, and the
    #: cursor for each. A turned stamp's corners land between them, so the
    #: nearest is used -- which is what Acrobat does, there being only four
    #: resize cursors to choose from.
    SHAPING_CURSORS = (Qt.SizeHorCursor, Qt.SizeBDiagCursor,
                       Qt.SizeVerCursor, Qt.SizeFDiagCursor)

    def _shaping_cursor(self, which):
        """The cursor for a stamp's handle, or None if that is not what it is.

        A corner gets the arrow that points the way it would move: the
        handle's direction from the centre, rounded to the nearest of the
        four Qt offers. The turning handle gets a curved arrow, which Qt
        has none of, so one is drawn from the icon set the toolbar uses.
        """
        if which is None or self._selected is None:
            return None
        index, mark = self._selected
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind == markup.LINE or kind in markup.POLYS:
            return Qt.CrossCursor
        if markup.is_stamp(mark):
            # Its four corners, on the diagonals.
            return ((Qt.SizeFDiagCursor, Qt.SizeBDiagCursor)[which % 2]
                    if 0 <= which < 4 else None)
        if markup.is_callout(mark) and which >= 8:
            # The tip and the knee, which go anywhere.
            return Qt.CrossCursor
        if kind == markup.INK:
            # Its four corners, on the diagonals.
            return ((Qt.SizeFDiagCursor, Qt.SizeBDiagCursor)[which % 2]
                    if 0 <= which < 4 else None)
        if kind == markup.FREETEXT or kind in markup.SHAPES:
            # Corners on the diagonals, the middles of the sides across.
            return (Qt.SizeFDiagCursor, Qt.SizeBDiagCursor, Qt.SizeFDiagCursor,
                    Qt.SizeBDiagCursor, Qt.SizeVerCursor, Qt.SizeHorCursor,
                    Qt.SizeVerCursor, Qt.SizeHorCursor)[which] if 0 <= which < 8 else None
        if kind != markup.STAMP:
            return None
        if which == 4:
            return self._turning_cursor()
        handles = self.grips()
        if which >= len(handles):
            return None
        middle = QPointF(
            sum(h.center().x() for h in handles[:4]) / 4.0,
            sum(h.center().y() for h in handles[:4]) / 4.0)
        away = handles[which].center() - middle
        # Screen y runs down, so the angle is negated to read as compass
        # bearings do, and eighths of a turn are what the four cursors cut
        # the circle into.
        eighth = round(math.degrees(math.atan2(-away.y(), away.x())) / 45.0)
        return self.SHAPING_CURSORS[eighth % 4]

    def _turning_cursor(self):
        """A curved arrow, drawn once and kept.

        Qt has no cursor for turning something, so one is rendered from the
        same icon set the tool strip draws from rather than hand-drawn.
        """
        if getattr(self, "_turn_cursor", None) is None:
            try:
                import qtawesome

                pixmap = qtawesome.icon(
                    "mdi.rotate-right",
                    color=QColor(20, 20, 20)).pixmap(24, 24)
                self._turn_cursor = QCursor(pixmap, 12, 12)
            except Exception:  # noqa: BLE001 - a cursor must not fail
                # Nothing curved to be had: the open hand at least says
                # "take hold of this", which is nearer than an arrow.
                self._turn_cursor = QCursor(Qt.OpenHandCursor)
        return self._turn_cursor

    def _set_tooltip(self, text: str) -> None:
        """Set the viewport's tooltip, and only when it changes.

        Re-setting the same text restarts Qt's hover delay, so a tooltip set
        on every mouse move never appears at all -- which is why this is one
        place rather than four.
        """
        if text != self._tooltip:
            self._tooltip = text
            self.viewport().setToolTip(text)

    def mousePressEvent(self, event):
        """Plain press starts a selection here; shifted press extends to here.

        That is shift's only job -- it says "keep the anchor" rather than "start
        again". It does not change how the selection is measured: what it
        extends by is decided by whether the gesture turns out to be a click or
        a drag, which is `extend_to` and `_extend_selection` respectively.
        """
        if event.button() == Qt.LeftButton and self._ink_drawing is not None:
            # A Pencil on its way: every press starts its next stroke.
            self._ink_press(QPointF(event.position()))
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._poly_drawing is not None:
            # A polygon on its way: every press is its next point.
            page, points, _pointer = self._poly_drawing
            points.append(self._angled(points[-1], QPointF(event.position())))
            self._poly_drawing = (page, points, QPointF(event.position()))
            self.viewport().update()
            self.drawing_changed.emit()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            position = QPointF(event.position())
            # A form field takes the press before the text does. Clicking a
            # tick box is not the start of a selection, and treating it as one
            # would leave a stray caret in the middle of a form.
            field = self.field_at(position)
            if field is not None and field.fillable:
                # Clicking a field is also *arriving* at it, so Tab carries on
                # from there. Without this the focus stayed empty and the next
                # Tab went to the first field in the document -- so clicking
                # into page three and tabbing jumped back to page one.
                self._focused = field
                if self._refuses(field):
                    self.field_refused.emit(field)
                elif field.kind in ("/Tx", "/Ch"):
                    self.edit_field(field)
                else:
                    self.field_pressed.emit(field)
                    # Nothing else holds the keyboard for a tick box.
                    self.setFocus()
                self.viewport().update()
                event.accept()
                return
            # A press anywhere else ends the edit, as clicking away from a
            # field does in any form.
            self.finish_editing()
            # A handle first, as on the move: it belongs to the mark that
            # is already held, and a stamp's handles sit on top of its own
            # body -- so without this, grabbing one drags the whole stamp
            # instead of reshaping it.
            note = (None if self.grip_at(position) is not None
                    else self.note_at(position))
            if note is not None:
                # Taken, but not yet acted on. An icon that says "there is a
                # note here" has to open it, or the note is write-only -- and
                # it also has to be draggable, because Reader moves one and a
                # comment is placed by eye. The two gestures start with the
                # same press, so what this was is settled on release.
                held = self.note_icon_rect(note[0], note[2])
                grab = (position - held.topLeft() if held is not None
                        else QPointF())
                self._dragging_note = (note[0], note[2], grab, position, False)
                # **A callout's box drags alone**, its tip holding still;
                # its leader drags the whole mark.
                self._callout_drag = None
                if (markup.is_callout(note[2])
                        and not getattr(note[2], "locked", False)):
                    box = self._callout_box(note[2])
                    where = self.quad_on_screen(
                        note[0], box, scaled=isinstance(note[2], markup.Annotation))
                    if where is not None and where.contains(position):
                        self._callout_drag = self._callout_taken(
                            note[0], note[2], "box", position)
                event.accept()
                return
            # A grip takes the press before the mark it belongs to, and
            # before the tool: it belongs to the mark already held, so it
            # outranks "make another one". Below the tool branch, a handle
            # pressed while the tool that made the mark was still armed
            # placed a second mark instead of reshaping the first -- every
            # time, because on a small stamp the handles cover most of it.
            grip = self.grip_at(position)
            if (grip is not None and self._selected is not None
                    and markup.is_callout(self._selected[1])):
                if self._callout_press(grip, position):
                    event.accept()
                    return
            if grip is not None and self._selected is not None and (
                    self._selected[1].kind
                    if isinstance(self._selected[1], markup.Annotation)
                    else self._selected[1].subtype) == markup.INK:
                if self._ink_resize_from(grip):
                    self._place_mark_buttons()
                    self.viewport().update()
                    event.accept()
                    return
            if grip is not None and self._selected is not None and (
                    self._selected[1].kind
                    if isinstance(self._selected[1], markup.Annotation)
                    else self._selected[1].subtype) in markup.POLYS:
                page, mark = self._selected
                self._dragging_vertex = (page, mark, grip)
                self._poly_shaping = (mark, tuple(self._poly_vertices(mark)))
                # Where the vertex began, which Shift keeps it in line with.
                self._vertex_origin = self.grips()[grip].center()
                self._place_mark_buttons()
                self.viewport().update()
                event.accept()
                return
            if grip is not None and self._selected is not None and (
                    self._selected[1].kind
                    if isinstance(self._selected[1], markup.Annotation)
                    else self._selected[1].subtype) == markup.LINE:
                page, mark = self._selected
                self._dragging_line_end = (page, mark, grip)
                self._line_shaping = (mark, tuple(self._line_points(mark)))
                self._place_mark_buttons()
                self.viewport().update()
                event.accept()
                return
            if grip is not None and self._selected is not None and (
                    self._selected[1].kind
                    if isinstance(self._selected[1], markup.Annotation)
                    else self._selected[1].subtype) in (markup.FREETEXT,
                                                        *markup.SHAPES):
                page, mark = self._selected
                # The rectangle it started with, which each move of the
                # handle is measured from.
                self._dragging_stamp = (page, mark, grip, tuple(mark.rect))
                self._shaping = (mark, tuple(mark.rect), 0.0)
                self._place_mark_buttons()
                self.viewport().update()
                event.accept()
                return
            if (grip is not None and self._selected is not None
                    and markup.is_stamp(self._selected[1])):
                if self._stamp_resize_from(grip):
                    self._place_mark_buttons()
                    self.viewport().update()
                    event.accept()
                    return
            if grip is not None and self._selected is not None and (
                    self._selected[1].kind
                    if isinstance(self._selected[1], markup.Annotation)
                    else self._selected[1].subtype) == markup.STAMP:
                page, mark = self._selected
                self._dragging_stamp = (page, mark, grip,
                                        self._stamp_centre(page, mark))
                self._shaping = (mark, tuple(mark.rect),
                                 float(getattr(mark, "rotate", 0.0) or 0.0))
                self._place_mark_buttons()
                self.viewport().update()
                event.accept()
                return
            if grip is not None and self._selected is not None:
                page, mark = self._selected
                boxes = self.mark_boxes(mark)
                far = boxes[-1] if grip == 0 else boxes[0]
                anchor = ((far[2], (far[1] + far[3]) / 2) if grip == 0
                          else (far[0], (far[1] + far[3]) / 2))
                self._dragging_grip = (grip, page, mark, anchor)
                self._preview = self._grip_quads(page, anchor, position)
                self.viewport().update()
                event.accept()
                return
            if self._clicked_shape and self._marking is not None:
                # The second click of a shape or a line made by clicks.
                start = self._marking[0]
                self._marking = None
                self._clicked_shape = False
                self.viewport().update()
                placed = (self._line_made(start, position)
                          if self._tool in self.LINE_TOOLS
                          else self._callout_made(start, position)
                          if self._tool == self.CALLOUT
                          else self._shape_made(start, position))
                if placed is not None:
                    self.mark_drawn.emit(self._tool, placed[0], [placed[1]])
                event.accept()
                return
            if self._tool == self.DRAW:
                if self._ink_press(position):
                    event.accept()
                    return
            if self._tool in self.POLY_TOOLS:
                page = self.page_at(position)
                if page is not None:
                    # The first point; the release decides whether a drag
                    # made the second.
                    self._poly_drawing = (page, [position], position)
                    self._poly_pressed = position
                    self.drawing_changed.emit()
                    event.accept()
                    return
            if self.marks_area():
                # Only here, *after* the field check: over a field there is no
                # markup, the field takes the press and is edited. A widget
                # that cannot be filled falls through to this, because a field
                # you are not allowed to fill is no reason to refuse a mark on
                # the page around it.
                self._marking = (position, position)
                event.accept()
                return

            # A mark under the pointer takes the press, before reading or
            # marking does. A mark is not the page: clicking one picks it up,
            # in this reader and in every other, and that is as true with the
            # highlighter armed as with the pointer -- pressing on a
            # highlight means *that highlight*, not the start of a second one
            # over the top of it.
            #
            # Not under an area tool, which is the one case where a press
            # over a mark plausibly means the page beneath it: a rectangle or
            # an arrow is drawn across whatever happens to be there, so that
            # branch above has already taken the press.
            if self._text_through:
                # Spent by the press it was asked for, whether or not that
                # press goes on to select anything: "the next click", not
                # "the next click that lands on a word".
                self._text_through, picked = False, None
            else:
                picked = self.mark_at(position)
            self.select_mark(picked)
            if picked is not None:
                event.accept()
                return
            # **A markup tool selects text the way the reader does.** It had
            # a gesture of its own, decided on 2026-11-01 inside a commit
            # about something else and never recorded: it threw away the
            # selection and tracked the drag itself, so double-click,
            # shift-extend and scroll-past-the-edge did nothing, and a bare
            # click made a mark one character wide. `_extend_selection`
            # keeps it on one page; the release below turns it into a mark.
            self._press = position
            self._selecting = False
            found = self.to_page(self._press)
            extending = (bool(event.modifiers() & Qt.ShiftModifier)
                         and self._anchor is not None)
            self._extending = extending
            if extending:
                # No clear_selection() here: it would drop the anchor, which is
                # the one thing this gesture needs to keep.
                if found is not None:
                    self.extend_to(*found)
            else:
                # Anchored even when the press lands off the text: the drag may
                # arrive on some, and snapping will pull this end onto the
                # nearest run when it does.
                if self._selection:
                    self.clear_selection()
                self._anchor = found if found is not None else None
                self._anchor_span = None
                # And an insertion point, which is what the caret chords work
                # from. A click off the page clears the *selection* -- above --
                # but leaves the caret where it was, which is David's rule and
                # Acrobat's: only Escape and a new document take it away.
                if found is not None:
                    index = self.index_at(*found)
                    if index is not None:
                        self.set_caret(found[0], index)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Second click of a double: select the word under it.

        The press before it cleared the selection and set an anchor, and the
        release after it would follow a link -- so both are stood down here,
        or double-clicking a word inside a link would select it and then
        navigate away from it.
        """
        if event.button() == Qt.LeftButton and self._ink_drawing is not None:
            # Not a finish: a stroke ends at its release, so the second
            # press of a double-click starts another.
            self._ink_press(QPointF(event.position()))
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._poly_drawing is not None:
            # The double-click's own press already placed the last point.
            self.finish_poly()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            here = QPointF(event.position())
            note = self.note_at(here)
            if note is not None and (
                    note[2].kind if isinstance(note[2], markup.Annotation)
                    else note[2].subtype) == markup.FREETEXT:
                # Into the text, with the cursor where the double-click
                # landed -- unless the box is locked.
                if not getattr(note[2], "locked", False):
                    self.edit_text_box(note[0], note[2], here)
                self._press = None
                event.accept()
                return
            found = self.to_page(here)
            if found is not None and self.select_word_at(*found):
                # The anchor is left alone: select_word_at has just set it to
                # the word, so a shift+click after this extends from the word's
                # far side and leaves it whole.
                self._press = None
                self._selecting = False
                self._extending = False
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        """Follow a link on release, and only if the pointer stayed put.

        On release rather than press so a click can still be abandoned by moving
        away, and with a movement threshold so the drag that step 4 will use for
        selecting text does not also fire off a link.

        A shifted press is exempt: it was extending a selection, and following
        the link under it would throw that selection away and navigate. Most of
        this document's text is link as far as PDFium is concerned (see section
        6), so without this the gesture would barely work.
        """
        if event.button() == Qt.LeftButton and self._marking is not None:
            start, end = self._marking
            self._marking = None
            self.viewport().update()
            if self._tool in self.POINT_TOOLS:
                # **A point tool places on a click and on nothing else.**
                # A drag is not a point: it used to leave a mark at the
                # corner it started from, so an aimed drag made a mark
                # nobody had aimed. Over a run of words the comment tool
                # has something to do with the drag and this one has not,
                # so here it means nothing at all.
                if ((QPointF(event.position()) - start).manhattanLength()
                        > QApplication.startDragDistance()):
                    event.accept()
                    return
                placed = self.icon_rect(start)
            elif self._tool == self.TEXTBOX:
                placed = self._text_box_made(start, QPointF(event.position()))
            elif self._tool == self.STAMPS:
                placed = self._stamp_placed(start, QPointF(event.position()))
            elif self._tool in self.CLICK_TOOLS:
                end = QPointF(event.position())
                if ((end - start).manhattanLength()
                        <= QApplication.startDragDistance()):
                    # A click, not a drag: the first of two. The band now
                    # follows the pointer to the second click.
                    self._marking = (start, end)
                    self._clicked_shape = True
                    event.accept()
                    return
                placed = (self._line_made(start, end)
                          if self._tool in self.LINE_TOOLS
                          else self._callout_made(start, end)
                          if self._tool == self.CALLOUT
                          else self._shape_made(start, end))
            else:
                placed = self.mark_rect(start, QPointF(event.position()))
            if placed is not None:
                self.mark_drawn.emit(self._tool, placed[0], [placed[1]])
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._ink_drawing is not None:
            if self._ink_drawing["live"]:
                self._ink_add(QPointF(event.position()))
                self._ink_drawing["live"] = False
                self.viewport().update()
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._ink_resizing is not None:
            page, mark, _which, _fixed = self._ink_resizing
            shaped = self._poly_shaping
            self._ink_resizing = None
            self._poly_shaping = None
            self._shaping = None
            self._place_mark_buttons()
            self.viewport().update()
            if shaped is not None and tuple(shaped[1]) != tuple(mark.points):
                self.line_reshaped.emit(page, mark, tuple(shaped[1]))
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._poly_drawing is not None:
            page, points, _pointer = self._poly_drawing
            pressed = getattr(self, "_poly_pressed", None)
            end = QPointF(event.position())
            if (len(points) == 1 and pressed is not None
                    and (end - pressed).manhattanLength()
                    > QApplication.startDragDistance()):
                # A press, a drag and a release: the first segment.
                points.append(self._angled(points[0], end))
                self.drawing_changed.emit()
            self._poly_pressed = None
            self._poly_drawing = (page, points, end)
            self.viewport().update()
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._dragging_vertex is not None:
            page, mark, _which = self._dragging_vertex
            shaped = self._poly_shaping
            self._dragging_vertex = None
            self._poly_shaping = None
            self._place_mark_buttons()
            self.viewport().update()
            if shaped is not None and tuple(shaped[1]) != tuple(self._poly_vertices(mark)):
                self.line_reshaped.emit(page, mark, tuple(shaped[1]))
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._dragging_line_end is not None:
            page, mark, _which = self._dragging_line_end
            shaped = self._line_shaping
            self._dragging_line_end = None
            self._line_shaping = None
            self._place_mark_buttons()
            self.viewport().update()
            if shaped is not None and tuple(shaped[1]) != tuple(mark.points):
                self.line_reshaped.emit(page, mark, tuple(shaped[1]))
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._dragging_stamp is not None:
            page, mark, _which, _centre = self._dragging_stamp
            shaped = self._shaping
            self._dragging_stamp = None
            self._shaping = None
            self._place_mark_buttons()
            self.viewport().update()
            if shaped is not None:
                self.mark_reshaped.emit(page, mark,
                                        tuple(shaped[1]), float(shaped[2]))
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._dragging_note is not None:
            page, mark, grab, at, moved = self._dragging_note
            self._dragging_note = None
            self._shaping = None
            self.viewport().unsetCursor()
            self._place_mark_buttons()
            self.viewport().update()
            if not moved:
                # **The note window**, which is the one every other mark
                # opens. A comment used to get the bare text box on the page
                # instead, and it was the only mark that did.
                self.select_mark((page, mark))
                # A comment's note window opens on a click, being the
                # comment; a text box has none, and a shape's opens with its
                # selection when it has one, as a highlight's does -- and so
                # does a Stamp's, which is a `/Stamp` but not a comment.
                if ((mark.kind if isinstance(mark, markup.Annotation)
                        else mark.subtype) in (markup.TEXT, markup.STAMP)
                        and not markup.is_stamp(mark)):
                    self.note_wanted.emit(page, mark)
            elif self._callout_drag is not None:
                self._callout_let_go()
            else:
                rect = self._note_rect_at(page, mark, at - grab)
                if rect is not None:
                    self.mark_moved.emit(page, mark, rect)
            self._callout_drag = None
            self._callout_shaping = None
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._callout_drag is not None:
            self._callout_let_go()
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._stamp_resizing is not None:
            page, mark, _fixed, _way = self._stamp_resizing
            shaped = self._shaping
            self._stamp_resizing = None
            self._shaping = None
            self._place_mark_buttons()
            self.viewport().update()
            if (shaped is not None and shaped[0] is mark
                    and tuple(shaped[1]) != tuple(mark.rect)):
                self.stamp_resized.emit(page, mark, tuple(shaped[1]))
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._dragging_grip is not None:
            _which, page, mark, _anchor = self._dragging_grip
            quads = self._preview
            self._dragging_grip = None
            self._preview = ()
            self.viewport().update()
            if quads:
                self.mark_resized.emit(page, mark, [tuple(q) for q in quads])
            event.accept()
            return

        if (event.button() == Qt.LeftButton and self.marks_text()
                and self._selection):
            # Nothing selected makes nothing: a click is not a mark, which
            # is what let a stray press leave a five-point underline behind.
            self.mark_the_selection(self._tool)
            self._press = None
            self._selecting = False
            event.accept()
            return

        if (event.button() == Qt.LeftButton and self._tool == self.INSERT
                and not self._selection and self._press is not None):
            # A click puts the caret in the gap between two characters
            # nearest the pointer -- and only on text: a click in a margin
            # or on a picture has no gap to go in, and makes nothing.
            here = QPointF(event.position())
            still = ((here - self._press).manhattanLength()
                     <= QApplication.startDragDistance())
            at = self._press
            self._press = None
            self._selecting = False
            if still:
                placed = self.insertion_point(at)
                if placed is not None:
                    self.mark_drawn.emit(self._tool, placed[0], [placed[1]])
                event.accept()
                return

        if (event.button() == Qt.LeftButton and self._tool == self.NOTE
                and not self._selection and self._press is not None):
            # **The comment tool's other half.** It marks text like the
            # tools above, and a click -- a press that selected nothing and
            # went nowhere -- places its icon instead. A drag that selected
            # nothing is not a click and makes nothing, which is the owner's
            # answer: over a margin or a picture there is no comment to make.
            #
            # At the point pressed rather than the point released, so a
            # wobble inside the drag threshold does not move the icon.
            here = QPointF(event.position())
            still = ((here - self._press).manhattanLength()
                     <= QApplication.startDragDistance())
            at = self._press
            self._press = None
            self._selecting = False
            if still:
                placed = self.icon_rect(at)
                if placed is not None:
                    self.mark_drawn.emit(self._tool, placed[0], [placed[1]])
                event.accept()
                return

        if event.button() == Qt.LeftButton and self._press is not None:
            here = QPointF(event.position())
            moved = (here - self._press).manhattanLength()
            self._press = None
            was_selecting, self._selecting = self._selecting, False
            was_extending, self._extending = self._extending, False
            if (moved <= QApplication.startDragDistance()
                    and not was_selecting and not was_extending):
                link = self.link_at(here)
                if link is not None and self.follow(link):
                    event.accept()
                    return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        """Right button: build the menu for what is under the pointer, and show it.

        Building is separate from showing so it can be tested. `exec()` spins a
        nested event loop and never returns without a user, which hangs a test
        run rather than failing it -- and a hung suite is worse than a broken
        one, because it tells you nothing.
        """
        self._menu_point = QPointF(event.pos())
        menu = self.build_context_menu(QPointF(event.pos()))
        menu.exec(event.globalPos())
        event.accept()

    def build_context_menu(self, position: QPointF) -> QMenu:
        """The menu for a point, without showing it.

        Built here rather than handed to the window because what belongs on it
        depends on what the click landed on -- a link offers different commands
        from a paragraph -- and the canvas is the only thing that knows.

        A right-click on the page but outside the selection *moves* it, which is
        what every text view does: getting Copy for the paragraph you selected
        earlier, while pointing at a different one, is worse than no menu at
        all. A click off the page entirely leaves the selection alone -- the
        grey around a page is not "somewhere else on the page", and dropping a
        selection because the pointer left the paper is the annoying half of
        that rule without the useful half.
        """
        if self._ink_drawing is not None:
            # A Pencil on its way, as a polygon: Cancel throws its strokes
            # away and Complete keeps them.
            menu = QMenu(self)
            cancel = menu.addAction(_("Cancel"))
            cancel.triggered.connect(self.cancel_ink)
            back = menu.addAction(_("Remove Last Stroke"))
            back.setEnabled(self.can_take_back())
            back.triggered.connect(self.take_back)
            complete = menu.addAction(_("Complete"))
            complete.setEnabled(bool(self._ink_drawing["strokes"]))
            complete.triggered.connect(self.finish_ink)
            menu.addSeparator()
            menu.addAction(_("Properties...")).triggered.connect(
                self.tool_form_wanted.emit)
            return menu
        if self._poly_drawing is not None:
            # A polygon on its way: Cancel throws it away, Complete keeps the
            # points placed so far -- once there are enough of them.
            menu = QMenu(self)
            cancel = menu.addAction(_("Cancel"))
            cancel.triggered.connect(self.cancel_poly)
            back = menu.addAction(_("Remove Last Point"))
            back.setEnabled(self.can_take_back())
            back.triggered.connect(self.take_back)
            complete = menu.addAction(_("Complete"))
            complete.setEnabled(self._poly_enough())
            complete.triggered.connect(self.finish_poly)
            # The tool's form: what is changed there, the whole mark is
            # made with when it is completed.
            menu.addSeparator()
            menu.addAction(_("Properties...")).triggered.connect(
                self.tool_form_wanted.emit)
            return menu
        self._menu_point = position
        found = self.mark_at(position)
        if found is not None and not self._text_through and not (
                self._point_in_live_selection(position)):
            # A mark's own menu, instead of the page's and not above it:
            # Reader replaces the text menu with this one, and *Enable Text
            # Selection* is how the text menu is reached underneath.
            #
            # Unless there is text selected here. Once *Enable Text
            # Selection* has let a selection be made over a mark, a click
            # inside that selection is about the selection -- which is what
            # Reader shows, and what the first version of this got wrong by
            # ending the pass-through at the press that used it: by the time
            # the words were selected the mark had already taken the menu
            # back.
            return self.mark_menu(*found)

        menu = QMenu(self)
        link = self.link_at(position)
        if link is not None:
            url = link.url()
            if url is not None and not url.isEmpty():
                follow = menu.addAction(_("Open Link"))
                follow.triggered.connect(lambda: self.follow(link))
                copy_link = menu.addAction(_("Copy Link Address"))
                copy_link.triggered.connect(
                    lambda: QApplication.clipboard().setText(url.toString()))
            else:
                where = self.link_description(link)
                follow = menu.addAction(_("Go to {}").format(where) if where
                                        else _("Follow Link"))
                follow.triggered.connect(lambda: self.follow(link))
            menu.addSeparator()

        found = self.to_page(position)
        if found is not None and not self._point_in_selection(*found):
            # Outside the current selection: move it here first.
            self.clear_selection()

        copy = menu.addAction(_("Copy"))
        copy.setShortcut(QKeySequence.Copy)
        copy.setEnabled(self.has_selection())
        copy.triggered.connect(self.copy)

        if self.has_selection():
            # What is useful to do with words you have just selected,
            # wherever they are: this is the menu for any selection, not
            # only one made over a mark. Reader's others -- editing the
            # text, styling it, redacting it -- have nothing behind them
            # and are left out.
            menu.addSeparator()
            # Refused, and shown refused, for a selection across a page
            # break: text is marked one page at a time.
            markable = not self.selection_is_across_pages()
            # **Underline is here although Reader does not offer it.**
            # There is no reason for its absence: the tool exists, the
            # gesture is the same selection, and a reader that can
            # highlight or strike out a selection can underline it. Taken
            # from the owner on 2026-11-04.
            for tool, label in ((self.HIGHLIGHT, _("Highlight text")),
                                (self.UNDERLINE, _("Underline text")),
                                (self.STRIKEOUT, _("Strikethrough text"))):
                act = menu.addAction(label)
                act.setEnabled(markable)
                act.triggered.connect(
                    lambda _checked=False, t=tool: self.mark_the_selection(t))
            # A note on the words rather than a mark on them: the same
            # gesture, and then the editor opens, because the note is the
            # whole point of the mark.
            note = menu.addAction(_("Add note to text"))
            note.setEnabled(markable)
            note.triggered.connect(
                lambda: self.mark_the_selection(self.NOTE_ON_TEXT))
            # *Replace Selected Text*, reached from the words: a
            # strikeout grouped onto a caret that carries what should be
            # there instead.
            replace = menu.addAction(_("Add a comment to replace text"))
            replace.setEnabled(markable)
            replace.triggered.connect(
                lambda: self.mark_the_selection(self.REPLACE))
            menu.addSeparator()

        select_all = menu.addAction(_("Select All"))
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.setEnabled(self._document is not None and bool(self.page_count()))
        page = found[0] if found is not None else max(0, self.current_page())
        select_all.triggered.connect(lambda: self.select_all_on(page))

        return menu

    @classmethod
    def _is_over_text(cls, mark) -> bool:
        """Whether ``mark`` takes the menu for a mark over text, with *Copy
        Text* and *Enable Text Selection*. Not either comment, which the
        comment tool's highlight counts as, and not an Insert Text caret,
        which sits between two characters and covers none."""
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        return (not cls._is_a_comment(mark)
                and kind not in (markup.CARET, markup.FREETEXT, markup.STAMP,
                                 *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK))

    @staticmethod
    def _is_a_comment(mark) -> bool:
        """Whether a comment tool made this mark, either way it makes one.

        An icon placed on the page, a scalable comment, or a highlight laid
        over a run of words -- told apart from the highlight tool's by
        `/Subj` and `/IT`, which is what the file records.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind in (markup.TEXT, markup.STAMP):
            # A Stamp is a `/Stamp` too, and not a comment: its note is apart
            # from its artwork, as a shape's is.
            return not markup.is_stamp(mark)
        return kind == markup.HIGHLIGHT and (
            (getattr(mark, "subject", "") or "",
             getattr(mark, "intent", "") or "") == markup.COMMENT_ON_TEXT)

    def mark_menu(self, index: int, mark, inside: bool = False):
        """What a right-click on a mark offers.

        Five groups, as Reader has them, with two things conditional and
        nothing else: **Reply** appears once there is a comment to reply to,
        and **Delete** becomes **Delete Thread** once somebody has replied.
        A note's own entry is above both and is there either way -- it is
        how the note is reached whether or not one has been written.

        Reader's three comment-panel entries are deliberately absent. There
        is no panel here and no pop-up windows to manage, and an entry for
        something with nothing behind it is not the same as one waiting for
        the step that turns it on.
        """
        menu = QMenu(self)
        # Asked about from inside the note window, a pair arrives as the
        # caret its note is on; the menu is the strikeout's.
        mark = self.head_of(index, mark)
        # A pair's note, replies and statuses are on its caret.
        said = self.note_bearer(index, mark)
        children = [m for m in self.chain_of(said)[1:] if m is not mark]
        # A text box has no note: its words are on the page. So neither the
        # entry that opens a note nor the one that answers it.
        noteless = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype) == markup.FREETEXT
        has_note = (not noteless
                    and bool(getattr(said, "contents", "") or children))
        replied = any(getattr(m, "is_reply", bool) and m.is_reply()
                      for m in children)

        if not inside and not noteless:
            # Not inside the window itself: there is nothing to open, the
            # thread is already showing. Acrobat leaves it out there too.
            note = menu.addAction(_("Open Pop-Up Note"))
            note.triggered.connect(
                lambda: self.note_wanted.emit(index, mark))
            menu.addSeparator()

        if has_note:
            reply = menu.addAction(_("Reply"))
            reply.triggered.connect(
                lambda: self.reply_wanted.emit(index, said))
        remove = menu.addAction(_("Delete Thread") if replied else _("Delete"))
        remove.triggered.connect(
            lambda: self.mark_deleted.emit(index, mark))
        # Shown and disabled on a locked mark rather than left out. Acrobat
        # leaves it out; the owner prefers to see that it exists and is
        # refused, 2026-11-03.
        remove.setEnabled(not getattr(mark, "locked", False))
        status = menu.addMenu(_("Set status"))
        now = self.status_of(said, index)
        for state in markup.STATUSES:
            act = status.addAction(_(markup.STATUS_LABELS[state]))
            act.setCheckable(True)
            # The tick marks the *current* status, which is the last link in
            # the chain rather than the only one: a mark accepted and then
            # completed has one status, Completed.
            act.setChecked(state == now)
            act.triggered.connect(
                lambda _checked=False, m=said, st=state:
                self.status_wanted.emit(index, m, st))
        menu.addSeparator()

        # **Not on a comment**, and not on the highlight a comment makes
        # over words either -- photographed in the owner's notes on
        # 2026-11-06, where both menus run Open Pop-Up Note, Reply,
        # Delete, Set status, then the panel entries, then the two at the
        # foot. Reader offers these two on a highlight, an underline and a
        # cross-out and on nothing else. The second would be strange on an
        # icon in any case: there is no text under a glyph to let through.
        if self._is_over_text(mark):
            text = self.mark_text(index, mark)
            copy = menu.addAction(_("Copy Text"))
            copy.setEnabled(bool(text))
            copy.triggered.connect(
                lambda: QApplication.clipboard().setText(text))
            through = menu.addAction(_("Enable Text Selection"))
            through.triggered.connect(self.let_text_through)
            menu.addSeparator()

        default = menu.addAction(_("Make current properties default"))
        default.triggered.connect(
            lambda: self.mark_is_the_default.emit(mark))
        details = menu.addAction(_("Properties..."))
        details.triggered.connect(
            lambda: self.properties_wanted.emit(index, mark))
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        locked = bool(getattr(mark, "locked", False))
        if kind in markup.POLYS and getattr(mark, "points", None):
            self._add_vertex_entries(menu, index, mark, locked)
        if kind in (markup.LINE, markup.POLYLINE) and getattr(mark, "points", None):
            # At the foot, as Acrobat has it: the start becomes the end, so
            # the ends' styles change places -- the one change a flip makes
            # that can be seen.
            menu.addSeparator()
            flip = menu.addAction(_("Flip Line"))
            flip.setEnabled(not locked)
            pairs = list(zip(mark.points[0::2], mark.points[1::2]))[::-1]
            flipped = tuple(v for pair in pairs for v in pair)
            flip.triggered.connect(
                lambda: self.line_reshaped.emit(index, mark, flipped))
        return menu

    def status_chain(self, index: int, mark):
        """A mark's review history, in the order it was made.

        **The file's links and this session's together.** A status set here
        is an annotation in the model until the document is saved, so a
        chain read from the file alone stops at whatever the file knew.
        Each link points at the one before it, and only links reachable
        that way belong: a reply has a history of its own, hanging off the
        same mark.
        """
        waiting = []
        if not isinstance(mark, markup.Annotation):
            waiting += [m for m in self.chain_of(mark)[1:] if m.is_status()]
        waiting += [ours for ours in self._session_marks(index)
                    if getattr(ours, "state", None)
                    and getattr(ours, "irt", None)]
        names, links = {getattr(mark, "name", None)}, []
        while True:
            # **Followed link by link, not filtered out of the subtree.**
            # Everything under a mark includes its replies and each of
            # *their* status chains, so taking every status below it read
            # a reply's status as the mark's own -- and a note whose reply
            # was Cancelled reported Cancelled.
            for one in waiting:
                answers = (one.irt if isinstance(one, markup.Annotation)
                           else one.parent)
                if answers in names and not any(link is one for link in links):
                    links.append(one)
                    names.add(getattr(one, "name", None))
                    break
            else:
                return links

    def carries_note(self, index: int, mark) -> bool:
        """Whether ``mark`` has a note window worth opening.

        **Its note has text, or it has any reply.** A note emptied while a
        reply stands under it is still a thread to read -- Acrobat leaves
        such marks behind -- so it wears the badge, shows on hover and opens
        on selection like any other. Asked of the annotation the note is on,
        which for a Replace pair is its caret.

        **Never a text box**, even one Reader has given replies: its words
        are on the page, and Acrobat shows it no badge, no hover summary and
        no note window, whatever hangs off it. Its replies are kept and
        written back untouched, for a comments panel to show.
        """
        said = self.note_bearer(index, mark)
        if (said.kind if isinstance(said, markup.Annotation)
                else said.subtype) == markup.FREETEXT:
            return False
        if markup.is_reply(said) or markup.is_status(said):
            return False
        if markup.has_note(said):
            return True
        if not isinstance(said, markup.Annotation):
            try:
                if any(m.is_reply() for m in self._file_marks.children(said)):
                    return True
            except Exception:   # noqa: BLE001 - a mark with no chain has none
                pass
        return bool(self.replies_made_here(index, said))

    def replies_made_here(self, index, mark):
        """The replies to a mark that this session has added.

        Everything in the model that answers the mark and is not a status:
        a reply says something, a status records that something was
        decided, and only the first is part of what the thread reads.
        """
        if index is None:
            return []
        name = getattr(mark, "name", None)
        if not name:
            return []
        return [ours for ours in self._session_marks(index)
                if getattr(ours, "irt", None) == name
                and markup.is_reply(ours)]

    def _session_marks(self, index: int):
        """This session's own marks on a page, as the window supplies them.

        Everything the model holds for the page, drawn or not: a status
        draws nothing and is still a mark, which is the whole point of
        asking the model rather than asking what is on screen.
        """
        if self.marks is None:
            return ()
        try:
            return self.marks(index) or ()
        except Exception:   # noqa: BLE001 - reading a menu must not raise
            return ()

    def status_of(self, mark, index: Optional[int] = None) -> str:
        """The mark's current status, as one of `markup.STATUSES`.

        `None` when the chain is empty or ends in a link that says so --
        setting a mark back to None appends a link like any other change,
        so the absence of a status and a status *of* None are the same
        answer arrived at two ways.

        With a page, the chain includes the links made in this session; the
        file's alone without one.
        """
        if index is not None:
            chain = self.status_chain(index, mark)
            found = str(chain[-1].state).lstrip("/") if chain else "None"
            return found if found in markup.STATUSES else "None"
        if isinstance(mark, markup.Annotation):
            return "None"
        try:
            _replies, state = self._file_marks.thread(mark)
        except Exception:  # noqa: BLE001 - a mark with no chain has none
            return "None"
        found = str(state).lstrip("/") if state else "None"
        return found if found in markup.STATUSES else "None"

    def let_text_through(self) -> None:
        """Let the next click reach the words a mark covers.

        **Not a property of the mark and nothing is written.** Without it
        there is no way to select text a mark covers at all: a press on a
        mark takes the mark. Reader's lasts until the next selection and so
        does this: the press it was asked for spends it, whether or not that
        press ends up selecting a word.
        """
        self._text_through = True
        self.select_mark(None)

    def mark_text(self, index: int, mark) -> str:
        """The words a mark covers, a line to each of its quadrilaterals.

        Per quadrilateral rather than one sweep from the first to the last:
        a mark over one column of two would otherwise copy the other column
        as well, because the sweep crosses everything between its ends.

        **Taken along the middle of each box, not corner to corner.** A
        quadrilateral is a *loose* box -- the font's ascent and descent
        rather than the glyph's ink -- so its foot overlaps the line below,
        and a corner-to-corner selection picks that line up too: measured on
        a thirteen-line highlight, eight of the thirteen came back with two
        lines in them and the mark copied twenty. Along the middle each box
        returns its own line and nothing else.
        """
        if self._document is None:
            return ""
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return ""
        mine = isinstance(mark, markup.Annotation)
        lines = []
        for quad in self.mark_boxes(mark):
            shown = forms_module.to_displayed(
                self.from_source(index, quad) if mine else tuple(quad), box)
            middle = height - (shown[1] + shown[3]) / 2
            found = self._document.getSelection(
                index, QPointF(shown[0], middle), QPointF(shown[2], middle))
            if found is not None and found.isValid() and found.text():
                lines.append(found.text())
        return "\n".join(lines)

    def _point_in_live_selection(self, position: QPointF) -> bool:
        """Is a *viewport* point inside the text selection there now?"""
        where = self.to_page(position)
        return where is not None and self._point_in_selection(*where)

    def _point_in_selection(self, page: int, page_point: QPointF) -> bool:
        selection = self._selection.get(page)
        if selection is None:
            return False
        return any(polygon.boundingRect().contains(page_point)
                   for polygon in selection.bounds())

    #: Which way each arrow points, as ``(axis, delta)``.
    ARROWS = {
        Qt.Key_Up: ("vertical", -1), Qt.Key_Down: ("vertical", 1),
        Qt.Key_Left: ("horizontal", -1), Qt.Key_Right: ("horizontal", 1),
    }

    def keyPressEvent(self, event):
        """The arrow keys, by one table: the modifier decides the verb.

        A polygon on its way takes Return, which finishes it, and Escape,
        which throws it away -- before Escape leaves the tool.

        nothing = scroll, Option = move the caret, Shift = extend the selection,
        Cmd = jump to an edge, Fn = a bigger jump. Nothing here depends on
        whether a caret exists, which is the point: reading must not behave
        differently because you clicked on a word earlier. Acrobat behaves
        otherwise, and that was considered and not
        copied.

        Explicit modifiers rather than `QKeySequence` standard keys, unlike Copy
        and Select All above: this scheme is ours, so no platform has an opinion
        about it, and one table everywhere is the simplicity that was wanted.
        """
        key = event.key()
        if self._ink_drawing is not None and key in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_ink()
            return
        if self._ink_drawing is not None and key == Qt.Key_Escape:
            self.cancel_ink()
            return
        if self._poly_drawing is not None and key in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_poly()
            return
        if self._poly_drawing is not None and key == Qt.Key_Escape:
            self.cancel_poly()
            return
        if event.matches(QKeySequence.Copy):
            if self.copy():
                return
        if event.matches(QKeySequence.SelectAll):
            self.select_all_on(max(0, self.current_page()))
            return
        if self._focused is not None and key in (Qt.Key_Space, Qt.Key_Return,
                                                 Qt.Key_Enter):
            field = self._focused
            if field.fillable and field.kind == "/Btn":
                if self._refuses(field):
                    self.field_refused.emit(field)
                else:
                    self.field_pressed.emit(field)
                return
        if key == Qt.Key_Escape and self._focused is not None:
            self.focus_field(None)
            return

        if key == Qt.Key_Escape and self.marks_text() and self._selection:
            # With a markup tool armed, Escape gives up the words picked for
            # it before anything larger reads the key.
            self.clear_selection()
            return
        if key == Qt.Key_Escape and self._selected is not None:
            # Before the window gets the key: with a mark picked, Escape
            # means "not that one" rather than "put the pointer back", the
            # same way it clears a text selection before it does anything
            # larger.
            self.select_mark(None)
            event.accept()
            return
        if key == Qt.Key_Escape and self.marking():
            # Out of the tool first. Escape with a tool active means "stop
            # marking up", which is what it means in every editor; a selection
            # left behind from before is not what the key was pressed for.
            self._marking = None
            self.set_tool(self.SELECT)
            return

        if key == Qt.Key_Escape and (self._selection or self._caret is not None):
            # Both. Acrobat leaves the selection behind; ours already cleared it
            # and had a test for it, and matching Acrobat there would have lost
            # working behaviour to gain nothing.
            self.clear_caret()
            self.clear_selection()
            return

        shift = bool(event.modifiers() & Qt.ShiftModifier)
        # Qt spells the platforms differently: ControlModifier is Cmd on macOS
        # and Ctrl elsewhere, which is what this table wants in both cases.
        jump = bool(event.modifiers() & Qt.ControlModifier)
        option = bool(event.modifiers() & Qt.AltModifier)

        # Fn+arrow arrives as one of these; on keyboards that have them they are
        # keys in their own right.
        if key in (Qt.Key_PageDown, Qt.Key_PageUp):
            forward = key == Qt.Key_PageDown
            if not self._continuous:
                self.next_page() if forward else self.previous_page()
            else:
                self._scroll_by_screen(1 if forward else -1)
            event.accept()
            return
        if key in (Qt.Key_Home, Qt.Key_End):
            self.last_page() if key == Qt.Key_End else self.first_page()
            event.accept()
            return

        if key in self.ARROWS:
            axis, delta = self.ARROWS[key]
            if option and (shift or jump) and axis == "horizontal":
                # Option added to a caret chord works by the word. It does
                # double duty -- alone it moves by character -- which is the one
                # inelegance in the table, accepted because David wanted both
                # granularities and losing one is the larger cost.
                if shift:
                    self.extend_caret("word", delta)
                else:
                    self.move_caret("word", delta)
            elif jump:
                if axis == "horizontal":
                    self.caret_to_line_edge(end=delta > 0, extend=shift)
                else:
                    self.caret_to_document_edge(end=delta > 0, extend=shift)
            elif option or shift:
                movement = "character" if axis == "horizontal" else "line"
                if shift:
                    self.extend_caret(movement, delta)
                else:
                    self.move_caret(movement, delta)
            elif axis == "horizontal":
                # Bare left and right scroll to a page top rather than sideways.
                # Horizontal scrolling has no range at all until the zoom passes
                # the window width, so this is the useful thing to spend them on.
                self.go_to_page(max(0, self.current_page()) + delta)
            elif self._continuous:
                bar = self.verticalScrollBar()
                bar.setValue(bar.value() + delta * bar.singleStep())
            # Single page mode has no line to scroll by, so bare up and down do
            # nothing there -- and every chord above is swallowed either way, so
            # that a caret-less Shift+arrow cannot fall through to the scroll
            # area and look like a scrolling bug.
            event.accept()
            return

        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            # Before the page keys below, and before the window's own Delete,
            # which removes *pages*: a selected mark is the nearer thing and
            # Reader gives it the key. With nothing selected the event falls
            # through untouched, so deleting pages keeps the key it has.
            found = self.selected_mark()
            if found is not None:
                self.mark_deleted.emit(found[0], found[1])
                event.accept()
                return

        if not self._continuous:
            if key in (Qt.Key_Space,):
                self.next_page()
                return
            if key in (Qt.Key_Backspace,):
                self.previous_page()
                return
        super().keyPressEvent(event)

    def _scroll_by_screen(self, delta: int):
        """One viewport's worth, so a page part-shown at the edge leads."""
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + delta * self.viewport().height())

    def scrollContentsBy(self, dx: int, dy: int):
        """The page moved under the bar, so the bar moves with it -- and the
        editor of a box being typed in."""
        super().scrollContentsBy(dx, dy)
        self._place_mark_buttons()
        self._follow_editor()

    def wheelEvent(self, event):
        """Ctrl+wheel zooms about the cursor, as the grid does.

        The same gesture doing nothing in one of the two views is worse than not
        offering it at all, which is why read mode filtered for this around
        `QPdfView`. Here it is simply the widget's own event.
        """
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                self.set_zoom(self.zoom() * (1.1 ** steps),
                              anchor=QPointF(event.position()))
            event.accept()
            return
        if not self._continuous:
            # One page at a time: there is often nothing to scroll to, so the
            # wheel turns the page instead of doing nothing.
            steps = event.angleDelta().y()
            bar = self.verticalScrollBar()
            if steps < 0 and bar.value() >= bar.maximum():
                self.next_page()
                event.accept()
                return
            if steps > 0 and bar.value() <= bar.minimum():
                self.previous_page()
                event.accept()
                return
        super().wheelEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self.palette().brush(QPalette.Dark))
        if not self._layout.page_count:
            return
        offset = self.offset()
        top = offset.y()
        bottom = top + self.viewport().height()
        if not self._continuous:
            band_top, band_bottom = self._band()
            top, bottom = max(top, band_top), min(bottom, band_bottom)
        visible = list(self._layout.pages_in(top, bottom))
        ratio = self.devicePixelRatioF()
        settled = self.settled()
        for index in visible:
            rect = self._layout.page_rect(index)
            target = QRectF(rect.topLeft() - offset, rect.size())
            size = self._device_size(rect, ratio)
            # White paper first, always. PDFium renders with an alpha channel
            # and leaves the page itself transparent, so drawing the bitmap
            # straight onto the viewport shows the grey through it and a page
            # never looks like a page. Nothing offscreen catches this: the
            # geometry is right either way, and only the pixels are wrong.
            painter.fillRect(target, Qt.white)
            image = self._pages.page_image(index, size, settled)
            if image is not None:
                painter.drawImage(target, image)
            # Blank paper is also what shows while there is no bitmap yet. Step
            # 5 draws the grid's thumbnail there instead, once there is an
            # asynchronous render worth waiting for.
            self._paint_fields(painter, index, offset, ratio)
            self._paint_marks(painter, index, offset)
            # Over the marks, not among them: the outline belongs to the
            # interface and a mark drawn afterwards must not cover it.
            self._paint_selected(painter, index, offset)
            self._paint_note_badges(painter, index, offset)
            self._paint_grips(painter, index, offset)
            self._paint_selection(painter, index, offset)
            self._paint_search(painter, index, offset)
        self._paint_caret(painter, offset)
        self._paint_marking(painter)
        self._paint_poly_drawing(painter)
        self._paint_ink_drawing(painter)
        # Last, and outside the page loop: the panel sits at the pointer in
        # viewport coordinates and belongs over everything, including a mark
        # on the page below the one it describes.
        self._paint_note_panel(painter)
        painter.end()
        self._prefetch_around(visible)

    def _paint_marks(self, painter, index: int, offset: QPointF) -> None:
        """Draw the marks added to this page but not yet written out.

        From what the window holds rather than from the file: the document on
        screen is an export made before the mark existed, and rebuilding it
        for every highlight is the 682 ms the form work went to such lengths
        to avoid.

        **Comments are the exception and come from both.** Their icons are
        drawn here whoever made them, because the glyph is this
        application's choice rather than the file's -- `markup.blank_note_icons`
        takes the renderer's copy out of the document being shown, so if
        these were not painted a saved comment would vanish.
        """
        # **The file's first, then ours, then the one being made**: the
        # order a save writes them in, ours after the file's in `/Annots`,
        # and the order `mark_at` takes them in. Ours were painted first,
        # under every mark the file brought, so an opaque stroke made here
        # showed a faded one of the file's through it -- and Acrobat, given
        # the saved file, drew it the other way up.
        marks = list(self._file_notes(index))
        try:
            marks += list(self.marks(index) or ()) if self.marks else []
        except Exception:       # noqa: BLE001 - a repaint must not fail
            pass
        marks += self._preview_marks(index)
        if not marks:
            return
        painter.save()
        painter.setPen(Qt.NoPen)
        for mark in marks:
            if getattr(mark, "state", None) or markup.is_reply(mark):
                # A status draws nothing. It is written `/F 30`, Hidden, and
                # comes back from the file invisible -- so painting one made
                # the same document look different before a save and after
                # it.
                #
                # **Nor does a reply.** It belongs in the thread and not on
                # the paper. One made here is a `/Text` placed at the corner
                # of the mark it answers, so painting it put a second icon
                # over that mark's own -- a 20 point box from the old
                # constant on top of the icon's own 24 -- and the pointer
                # crossing between them made the outline change size and the
                # hover panel come and go.
                continue
            colour = QColor.fromRgbF(
                *(markup.shown_colour(mark) or (1.0, 1.0, 0.0)))
            kind = (mark.kind if isinstance(mark, markup.Annotation)
                    else mark.subtype)
            if kind == markup.TEXT:
                self._paint_note(painter, index, mark, colour)
                continue
            if markup.is_stamp(mark):
                self._paint_stamp_art(painter, index, mark, offset)
                continue
            if kind == markup.STAMP:
                self._paint_stamp(painter, index, mark, colour, offset)
                continue
            if kind == markup.CARET:
                self._paint_replace_caret(painter, index, mark, colour,
                                          offset)
                continue
            if kind == markup.FREETEXT:
                self._paint_text_box(painter, index, mark, offset)
                continue
            if kind in markup.SHAPES:
                self._paint_shape(painter, index, mark, offset)
                continue
            if kind == markup.LINE:
                self._paint_line(painter, index, mark, offset)
                continue
            if kind in markup.POLYS:
                self._paint_poly(painter, index, mark, offset)
                continue
            if kind == markup.INK:
                self._paint_ink(painter, index, mark, offset)
                continue
            # **At the solidity the file will show**, which the quadded
            # marks were drawn without: a highlight of ours is written
            # `/CA 0.4` and was painted at full strength, so it was darker
            # on screen than in every reader that opened it afterwards.
            # Per shape rather than as a group, which these can afford: a
            # run of words is one rectangle per line and they do not
            # overlap, so there is nothing for a group to protect.
            was = painter.opacity()
            painter.setOpacity(self._solidity(mark))
            for quad in (mark.quads or (mark.rect,)):
                where = self.quad_on_screen(index, quad, offset)
                if where is None:
                    continue
                if not where.intersects(QRectF(self.viewport().rect())):
                    continue
                if kind in (markup.STRIKEOUT, markup.UNDERLINE):
                    # The same fractions of the type's height the written
                    # appearance uses, so the screen and the file agree:
                    # a sixteenth thick, centred three sevenths up for a
                    # cross-out and one seventh up for an underline.
                    # Downwards here, because the screen's y grows that way.
                    above = (markup.STRIKEOUT_OFFSET
                             if mark.kind == markup.STRIKEOUT
                             else markup.UNDERLINE_OFFSET)
                    thickness = max(
                        1.0, where.height() * markup.STROKE_THICKNESS)
                    middle = where.bottom() - where.height() * above
                    painter.fillRect(
                        QRectF(where.x(), middle - thickness / 2,
                               where.width(), thickness), colour)
                elif mark.kind == markup.SQUIGGLY:
                    self._paint_squiggle(painter, where, colour)
                else:
                    # Multiplied, so the words underneath still read.
                    painter.save()
                    painter.setCompositionMode(
                        QPainter.CompositionMode_Multiply)
                    painter.fillRect(where, colour)
                    painter.restore()
            painter.setOpacity(was)
        painter.restore()

    #: The colour a selected mark is outlined in. Acrobat's, so that a
    #: document marked up here and opened there looks the same when something
    #: is picked: a blue border round every quadrilateral, not a box round the
    #: mark as a whole -- a highlight over three lines is outlined three
    #: times, and the margins between the lines stay outside it.
    SELECTED = (41, 115, 215)

    #: How thick that outline is, in pixels, and how round its corners are.
    #: Both are plain dials: nothing downstream depends on either.
    OUTLINE = 2.5
    OUTLINE_RADIUS = 3.0

    #: How big the badge on a mark carrying a note is, in pixels. A piece of
    #: interface rather than something on the paper, so it does not grow with
    #: the zoom -- the same reasoning as the selection outline.
    NOTE_BADGE = 13

    def _paint_note_badges(self, painter, index: int, offset: QPointF) -> None:
        """Mark every annotation that carries a note.

        At the top left of the mark, shown whether or not it is selected,
        which is what Reader does: a highlight somebody has written about
        must not look like one nobody has. Without it a note is invisible
        until the pointer happens to cross the mark.

        **The marks made here as well as the ones the file brought.** It
        was the file's alone, on the reasoning that nothing in this
        application wrote a note; the thread window does, so a note typed
        on a mark made in this session showed no badge until the document
        had been saved and opened again.

        `markup.has_note` rather than the method, because the model holds
        `Annotation` and the file holds `Mark` and only one of them has
        the method -- and the same question asked in two shapes is the
        same question answered two ways the first time one changes.
        """
        marks = self.noted_marks(index)
        if not marks:
            return
        viewport = QRectF(self.viewport().rect())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for mark in marks:
            where = self._badge_rect(index, mark, offset)
            if where is None or not where.intersects(viewport):
                continue
            # **The badge wears the latest reply's colour**, not the
            # mark's. A reply's `/C` colours an icon this reader does not
            # draw and a pop-up title bar it has not got, so the badge is
            # the one place on the page it can be seen -- and it is what
            # the hover then describes.
            # A mark the file brought can already have replies, and the
            # newest one's colour is what Reader shows. One made here
            # cannot be answered until it has been written, so it speaks
            # for itself.
            said = self.note_bearer(index, mark)
            speaks_for = (said if isinstance(said, markup.Annotation)
                          else self.latest_reply(said) or said)
            colour = QColor.fromRgbF(
                *(speaks_for.colour or mark.colour or (1.0, 0.82, 0.25)))
            faded = getattr(speaks_for, "opacity", None)
            if faded is not None:
                colour.setAlphaF(max(0.0, min(1.0, float(faded))))
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.setBrush(colour.darker(120))
            painter.drawEllipse(where)
            # Three lines, which is what a speech balloon reduces to at this
            # size: a drawn balloon at 13 pixels is a smudge.
            painter.setPen(QPen(QColor(255, 255, 255), 1.2))
            step = where.height() / 4.0
            for n in (1, 2, 3):
                y = where.top() + step * n
                inset = where.width() * (0.22 if n == 2 else 0.28)
                painter.drawLine(QPointF(where.left() + inset, y),
                                 QPointF(where.right() - inset, y))
        painter.restore()

    def pages_with_replies(self):
        """Which pages carry a reply, by index. Empty for most documents."""
        found = []
        for number in range(1, self.page_count() + 1):
            try:
                marks = self._file_marks.visible(number)
            except Exception:   # noqa: BLE001 - an unreadable page has none
                continue
            if any(m.is_reply() for m in marks):
                found.append(number - 1)
        return found

    def latest_reply(self, mark):
        """The last reply on a mark, or None where it has none.

        *Last* in the order the file holds them, which is the one every
        renderer paints over the others when they share a rectangle -- and
        the one whose colour therefore stands for the thread.
        """
        if isinstance(mark, markup.Annotation):
            return None
        try:
            answers = [m for m in self._file_marks.children(mark)
                       if m.is_reply()]
        except Exception:   # noqa: BLE001 - a repaint must not fail
            return None
        return answers[-1] if answers else None

    def _badge_rect(self, index: int, mark, offset=None):
        """Where a mark's note badge sits: off its top left corner."""
        boxes = self.mark_boxes(mark)
        if not boxes:
            return None
        top = max(boxes, key=lambda q: q[3])
        where = self.quad_on_screen(index, top, offset, scaled=False)
        if where is None:
            return None
        size = float(self.NOTE_BADGE)
        return QRectF(where.left() - size * 0.62, where.top() - size * 0.5,
                      size, size)

    def noted_marks(self, index: int) -> list:
        """The marks on a page that carry a note of their own.

        **The ones made here as well as the ones the file brought.** Three
        places asked this -- the badge painter, the badge's hit test and
        the hover -- and each asked the file alone, so a note typed in
        this session had no badge, could not be hovered, and appeared only
        once the document had been saved and opened again.
        """
        # Through `note_bearer`, because a *Replace Selected Text* pair
        # keeps its note on the caret and wears the badge on the strikeout.
        # An Insert Text caret wears one too: it is not a comment, so its
        # note needs the sign a strikethrough's does.
        badged = self.QUADDED_SELECTABLE + (markup.CARET, *markup.SHAPES,
                                            markup.LINE, *markup.POLYS,
                                            markup.INK)
        # And a Stamp, whose note is apart from its artwork.
        found = [m for m in self._file_marks.visible(index + 1)
                 if (m.subtype in badged or markup.is_stamp(m))
                 and not markup.is_reply(m)
                 and not self._paired_caret(index, m)
                 and self.carries_note(index, m)]
        try:
            if self.marks:
                found += [m for m in (self.marks(index) or ())
                          if (m.kind in badged or markup.is_stamp(m))
                          and not self._paired_caret(index, m)
                          and self.carries_note(index, m)]
        except Exception:       # noqa: BLE001 - a repaint must not fail
            pass
        return found

    def note_badge_at(self, point: QPointF):
        """The mark whose note badge is under a viewport point, or None."""
        index = self.page_at(point)
        if index is None:
            return None
        for mark in self.noted_marks(index):
            where = self._badge_rect(index, mark)
            if where is not None and where.contains(point):
                return (index, self.note_bearer(index, mark))
        return None

    def note_window_is_shut(self, index: int, mark) -> bool:
        """Whether this mark's window was closed by hand in this session."""
        return self._note_key(index, mark) in self._shut_notes

    def note_window_shut(self, index: int, mark, shut: bool = True) -> None:
        """Say that a mark's window has been closed, or opened again.

        **Closing it does not close it in the file.** `/Popup /Open` is
        what the document was saved with, and reading a note -- or putting
        one away -- is not an edit; it is this session's own notion of
        what is showing. So the mark goes back to its one line summary
        under the pointer rather than to nothing at all, and the file is
        unchanged either way.
        """
        key = self._note_key(index, mark)
        if shut:
            self._shut_notes.add(key)
        else:
            self._shut_notes.discard(key)

    def _note_key(self, index: int, mark):
        """What identifies a mark between one hover and the next: its `/NM`
        where it has one, and the object itself where it does not.

        The note's own annotation, so a pair is one window whether it was
        asked about by its strikeout or by the caret the note is on.
        """
        mark = self.note_bearer(index, mark)
        return (index, getattr(mark, "name", None) or id(mark))

    def _marked_note_at(self, point: QPointF):
        """The mark under a point, if it carries a note. Otherwise None.

        A mark made in this session counts. It used to be refused outright
        -- nothing here wrote notes when this was written -- so hovering an
        underline you had just commented on showed nothing at all.
        """
        found = self.mark_at(point)
        if found is None:
            return None
        said = self.note_bearer(*found)
        if not self.carries_note(found[0], found[1]):
            return None
        return (found[0], said)

    #: How wide the panel may get before its text wraps, in pixels.
    NOTE_PANEL_WIDTH = 260

    #: How much of the mark's colour the hover panel's paper takes, the
    #: rest being white. Measured off Reader, whose panel beside a red
    #: mark is a pale pink rather than red: enough to say which mark the
    #: note belongs to, little enough to read dark text on.
    NOTE_PANEL_WASH = 0.2

    def _show_note_panel(self, mark, at, index=None) -> None:
        """Show a mark's note beside the pointer, or take it away.

        The page comes too, because what the note *says* -- its replies and
        its status -- is partly in the model until the file is saved.
        """
        panel = None if mark is None else (mark, QPointF(at), index)
        was = self._note_panel
        self._note_panel = panel
        if (was is None) != (panel is None) or (
                panel is not None and was is not None and was[0] is not mark):
            self.viewport().update()
        elif panel is not None:
            self.viewport().update()

    def _paint_note_panel(self, painter) -> None:
        """Reader's hover panel: who wrote it, the counts, and the text.

        **The text is drawn through a `QTextDocument`**, not with
        `drawText`, so that a note the file styled is summarised styled.
        It measures the same text it draws, which is also why the box
        fits a wrapped and styled note rather than a guess at one.
        """
        if self._note_panel is None:
            return
        mark, at, index = self._note_panel
        head, _, body = self.note_summary(mark, index).partition("\n")
        said = QTextDocument()
        said.setDefaultFont(painter.font())
        said.setDocumentMargin(0)
        styled = markup.rich_to_html(
            getattr(self.latest_reply(mark) or mark, "rich", ""))
        if styled:
            said.setHtml(styled)
        else:
            said.setPlainText(body)
        bold = painter.font()
        bold.setBold(True)
        # The head is a document too, so that it *wraps*. Drawn as one
        # line it was simply cut off at the panel's width -- an author's
        # name and the counts are easily wider than 236 pixels.
        title = QTextDocument()
        title.setDefaultFont(bold)
        title.setDocumentMargin(0)
        title.setPlainText(head)
        # **The head sets the width; the body wraps within it.** The text
        # wraps at `NOTE_PANEL_WIDTH`, but a line of author and counts is
        # one line and there is room on the page for it -- wrapping it to
        # keep the box narrow spent two lines to save nothing.
        room = float(self.NOTE_PANEL_WIDTH - 24)
        said.setTextWidth(room)
        said.setTextWidth(min(said.idealWidth(), room))
        title.setTextWidth(-1)
        widest = float(max(self.viewport().width() - 32, self.NOTE_PANEL_WIDTH))
        # Rounded *up*: truncating left the head a pixel short of the width
        # it had just reported needing, so it wrapped anyway.
        width = int(math.ceil(min(widest,
                                  max(title.idealWidth(),
                                      said.textWidth()) + 24)))
        for piece in (title, said):
            piece.setTextWidth(width - 24)
        height = title.size().height() + said.size().height() + 22
        where = QRectF(at.x() + 16, at.y() + 16, width, height)
        viewport = QRectF(self.viewport().rect())
        if where.right() > viewport.right():
            where.moveLeft(max(0.0, at.x() - width - 16))
        if where.bottom() > viewport.bottom():
            where.moveTop(max(0.0, at.y() - height - 16))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        # **The mark's colour, washed for the paper and whole for the
        # edge.** Reader's panel is tinted by `/C`, which is what says
        # which mark the note belongs to when several are close together.
        # The newest reply's colour where there is one, as the badge does:
        # a reply is answered in its own colour and that is what the
        # window shows.
        speaks_for = self.latest_reply(mark) or mark
        tint = getattr(speaks_for, "colour", None) or getattr(
            mark, "colour", None)
        if tint:
            ink = QColor.fromRgbF(*tint[:3])
            painter.setPen(QPen(ink))
            painter.setBrush(QColor(
                *(round(255 + (band - 255) * self.NOTE_PANEL_WASH)
                  for band in (ink.red(), ink.green(), ink.blue()))))
        else:
            painter.setPen(QPen(QColor(0, 0, 0, 40)))
            painter.setBrush(QColor(255, 253, 240))
        painter.drawRoundedRect(where, 4, 4)
        inner = where.adjusted(12, 8, -12, -8)
        painter.setPen(QColor(90, 90, 90))
        painter.save()
        painter.translate(inner.left(), inner.top())
        title.drawContents(painter)
        painter.restore()
        painter.setPen(QColor(20, 20, 20))
        painter.translate(inner.left(),
                          inner.top() + title.size().height() + 4)
        # Drawn with the painter's pen as its text colour, which is what
        # `drawContents` does with it.
        said.drawContents(painter)
        painter.restore()

    def note_summary(self, mark, index: Optional[int] = None) -> str:
        """What a mark's note says, as Reader's panel puts it.

        Author and the counts on one line, the text beneath. The counts read
        the *current* status rather than every change in the chain, which is
        what Reader shows and what `MarkMap.thread` answers.

        **With a page, they count this session's replies and statuses too.**
        Both are annotations in the model until the document is saved, so
        counting the file's alone said "1 Reply" at a thread of three until
        it had been written out and read back.
        """
        replies, status = self._file_marks.thread(mark)
        replies = list(replies) + self.replies_made_here(index, mark)
        if index is not None:
            status = self.status_of(mark, index)
            status = None if status == "None" else status
        parts = []
        if replies:
            parts.append(_("%d Reply") % len(replies) if len(replies) == 1
                         else _("%d Replies") % len(replies))
        if status:
            parts.append(_("%d Status") % 1)
        speaks_for = self.latest_reply(mark) or mark
        who = (getattr(speaks_for, "author", None)
               or getattr(mark, "author", None) or "")
        head = who
        if parts:
            head = f"{who} ({' / '.join(parts)})" if who \
                else f"({' / '.join(parts)})"
        # **What it says is the item the badge is wearing the colour of.**
        # On a thread that is the latest reply, which is the one every
        # renderer paints over the others; on a mark with none it is the
        # mark's own note. Its author too: naming the mark's author over a
        # reply's words credits the wrong person.
        said = speaks_for.contents or ""
        if speaks_for is not mark and index is not None:
            state = self.status_of(speaks_for, index)
            if state and state != "None":
                said = "%s\n%s %s" % (said, _("Status"), state) if said \
                    else "%s %s" % (_("Status"), state)
        return f"{head}\n{said}" if head else said

    #: How big a grip is, in pixels. Interface rather than paper, so it does
    #: not grow with the zoom -- the same reasoning as the outline.
    GRIP = 11

    #: What the band being dragged is filled with, and how solid.
    #:
    #: **Neutral, not the mark's own colour.** A highlight is drawn by
    #: multiplying, and the original is already in the page bitmap -- it
    #: cannot be taken away while the drag is in flight, because PDFium drew
    #: it there. So a band in the mark's colour multiplies with itself:
    #: `#FF6200` over `#FF6200` comes out a deep red that belongs to
    #: neither. Grey is Acrobat's answer and it is the right one, because a
    #: neutral band cannot take a colour from whatever it is dragged over.
    DRAGGED = (0.55, 0.55, 0.58)
    DRAGGED_OPACITY = 0.45

    def grips(self, offset=None):
        """``(start, end)`` grips of the selected mark, as viewport circles.

        At the two ends of the *run*, not of the bounding box: a highlight
        over three lines starts at the left of its first line and ends at
        the right of its last, and a box's corners are nowhere near either.

        Empty when nothing is selected. Only a selected mark has them --
        hovering one never does, which is what separates the two states
        along with the bar.
        """
        if self._selected is None:
            return []
        index, mark = self._selected
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if kind == markup.STAMP:
            if getattr(mark, "locked", False):
                return []
            if markup.is_stamp(mark):
                return self._corner_grips(index, mark, offset)
            return self._stamp_grips(index, mark, offset)
        if kind == markup.FREETEXT:
            if getattr(mark, "locked", False):
                return []
            if markup.is_callout(mark):
                return self._callout_grips(index, mark, offset)
            return self._text_box_grips(index, mark, offset)
        if kind in markup.SHAPES:
            if getattr(mark, "locked", False):
                return []
            return self._shape_grips(index, mark, offset)
        if kind == markup.LINE:
            if getattr(mark, "locked", False):
                return []
            return self._line_grips(index, mark, offset)
        if kind in markup.POLYS:
            if getattr(mark, "locked", False):
                return []
            return self._poly_grips(index, mark, offset)
        if kind == markup.INK:
            if getattr(mark, "locked", False):
                return []
            return self._ink_grips(index, mark, offset)
        if kind not in self.QUADDED_SELECTABLE:
            # A comment's icon is placed, not sized: there is no run to
            # take hold of, and a handle on a glyph offers a drag that
            # means nothing.
            return []
        if getattr(mark, "locked", False):
            # A locked mark is not resized, so it is not offered handles to
            # resize it by. Nothing to take hold of says more than a handle
            # that refuses when pulled. It is still *selected*, with its
            # outline and its buttons -- only its ends are not draggable.
            return []
        is_mine = isinstance(mark, markup.Annotation)
        if self._dragging_grip is not None and self._preview:
            # While a grip is moving, both ends follow the run being built,
            # so the pair reads as one band being stretched rather than a
            # dot sliding along the edge of a shape that has not moved.
            boxes, is_mine = list(self._preview), False
        else:
            boxes = self.mark_boxes(mark)
        if not boxes:
            return []
        first, last = boxes[0], boxes[-1]
        # The *top* of the run's first line and the *bottom* of its last,
        # not the middle of either: a highlight runs from the start of some
        # text to the end of it, and grips on the outside corners say that.
        # Centred ones read as handles on a box being widened.
        ends = ((first[0], first[3]), (last[2], last[1]))
        found = []
        for n, (x, y) in enumerate(ends):
            quad = (x, y, x, y)
            where = self.quad_on_screen(index, quad, offset, scaled=is_mine)
            if where is None:
                return []
            size = float(self.GRIP)
            found.append(QRectF(where.center().x() - size / 2,
                                where.center().y() - size / 2, size, size))
            del n
        return found

    #: Emitted when a grip drag ends: ``(page, mark, quads)`` in the page's
    #: own space. The canvas reports the new run and keeps none of it, the
    #: same way `mark_drawn` reports a new one.
    mark_moved = Signal(int, object, object)
    #: A text box's editing ended: ``(page, mark, text, rich, rect)`` -- the
    #: plain text, the rich text as `/RC` (None for an empty box) and the
    #: rect the box has settled to. Sent only when something changed.
    text_box_edited = Signal(int, object, str, object, object)
    #: A text box can be typed in: the editor, for the text palette to
    #: work on. And the editing has ended.
    text_editing_started = Signal(object)
    text_editing_ended = Signal()

    #: A stamp's handle was let go: ``(page, mark, rect, rotate)`` in the
    #: page's own space and degrees. One signal for both handles, because
    #: both say the same thing -- this is the shape it is now.
    mark_reshaped = Signal(int, object, object, float)
    #: A line's end dragged, or the line flipped: ``(page, mark, points)``,
    #: its two points now, start first.
    line_reshaped = Signal(int, object, object)

    mark_resized = Signal(int, object, object)

    #: Emitted when the selected mark is to go: ``(page, mark)``. What goes
    #: with it -- the status chain, the replies, the popups -- is the
    #: window's business, because it owns the overlay that records it.
    mark_deleted = Signal(int, object)

    #: A mark's colour and opacity are to become what the next one gets.
    #: The window holds that, so the canvas only reports the mark.
    mark_is_the_default = Signal(object)

    #: The mark's note is to be opened: ``(page, mark)``. The thread it
    #: shows is assembled by the window, which owns the panel.
    note_wanted = Signal(int, object)


    #: A reply is to be written to this mark: ``(page, mark)``.
    reply_wanted = Signal(int, object)

    #: A status is to be set on this mark: ``(page, mark, state)``, where the
    #: state is one of `markup.STATUSES` as written, not as shown.
    status_wanted = Signal(int, object, str)

    #: The properties form is to be opened on this mark: ``(page, mark)``.
    #: Shown even on a locked one, which is where the lock is taken off.
    properties_wanted = Signal(int, object)

    def chain_of(self, mark):
        """``mark`` and everything hanging off it, in the order found.

        The status chain and the replies, which `MarkMap.children` walks
        transitively -- a status change points at the link before it, so one
        step finds the first and misses the rest. A mark of the user's own
        has nothing hanging off it yet and comes back alone.
        """
        if isinstance(mark, markup.Annotation):
            return [mark]
        caret = self.caret_of(mark.page - 1, mark)
        if caret is None:
            return [mark] + self._file_marks.children(mark)
        # **A pair goes as one**: the strikeout, the caret it is grouped
        # with, and everything hanging off the caret -- which is where the
        # note's replies and statuses are. The strikeout is among the
        # caret's children, being joined to it, and is not listed twice.
        return [mark, caret] + [m for m in self._file_marks.children(caret)
                                if m is not mark]

    def _everything_on(self, index: int):
        """Every mark on a page, the file's and this session's, hidden or not."""
        try:
            found = list(self._file_marks.for_page(index + 1))
        except Exception:   # noqa: BLE001 - a lookup must not raise
            found = []
        return found + list(self._session_marks(index))

    def caret_of(self, index: int, mark):
        """The caret a *Replace Selected Text* strikeout is grouped with.

        None for anything else. **The strikeout stands for the pair**: it is
        what is clicked, outlined, given handles and opened in the menu and
        the form, and this is how everything that needs the other half
        finds it -- by the name the strikeout's `/IRT` holds.
        """
        if mark is None or not getattr(mark, "group", False):
            return None
        name = markup._answers(mark)
        if not name:
            return None
        for other in self._everything_on(index):
            if other is not mark and getattr(other, "name", None) == name:
                return other
        return None

    def head_of(self, index: int, mark):
        """The strikeout a caret belongs to, or ``mark`` itself.

        For the places a caret can arrive from -- the note window lists it
        first, because the note is on it -- and has to be turned back into
        the mark that stands for the pair.
        """
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else getattr(mark, "subtype", None))
        name = getattr(mark, "name", None)
        if kind != markup.CARET or not name:
            return mark
        for other in self._everything_on(index):
            if (getattr(other, "group", False)
                    and markup._answers(other) == name):
                return other
        return mark

    def _paired_caret(self, index: int, mark) -> bool:
        """Whether ``mark`` is the caret of a Replace Selected Text pair,
        which is never a mark of its own -- its strikeout stands for both.
        An Insert Text caret is a mark by itself."""
        return self.head_of(index, mark) is not mark

    def note_bearer(self, index: int, mark):
        """The annotation that holds ``mark``'s note: its caret for a pair,
        where Acrobat puts the note, its replies and its statuses; else the
        mark itself."""
        return self.caret_of(index, mark) or mark

    def forget_marks(self, marks) -> None:
        """Stop drawing and hit-testing these, without rebuilding."""
        self._file_marks.drop(marks)
        found = self.selected_mark()
        if found is not None and any(found[1] is m for m in marks):
            self.select_mark(None)
        self.viewport().update()

    #: How far beyond the top edge a stamp's turning handle sits, in
    #: viewport pixels. Far enough not to be taken for a corner.
    TURN_REACH = 22.0

    def _stamp_grips(self, index: int, mark, offset=None):
        """A stamp's five handles: its four corners, then the one that turns.

        **On the drawing, not on the rectangle.** `/Rect` is the box that
        bounds the turned artwork, so at any angle but a right one its
        corners are out in the white -- the handles belong to the thing you
        can see. The fifth stands off the middle of the top edge, along the
        direction the stamp calls up, so it turns with it.
        """
        icon = getattr(mark, "icon", "")
        angle = float(getattr(mark, "rotate", 0.0) or 0.0)
        rect, angle = self._shape_of(mark)
        corners = markup.stamp_corners(rect, icon, angle)
        is_mine = isinstance(mark, markup.Annotation)
        found = []
        for x, y in corners:
            where = self.quad_on_screen(index, (x, y, x, y), offset,
                                        scaled=is_mine)
            if where is None:
                return []
            found.append(where.center())
        # The top edge is between the third and fourth corners, which are
        # the two the drawing calls its top.
        top = QPointF((found[2].x() + found[3].x()) / 2.0,
                      (found[2].y() + found[3].y()) / 2.0)
        middle = QPointF(sum(p.x() for p in found) / 4.0,
                         sum(p.y() for p in found) / 4.0)
        away = QPointF(top.x() - middle.x(), top.y() - middle.y())
        reach = math.hypot(away.x(), away.y()) or 1.0
        found.append(QPointF(top.x() + away.x() / reach * self.TURN_REACH,
                             top.y() + away.y() / reach * self.TURN_REACH))
        size = float(self.GRIP)
        return [QRectF(p.x() - size / 2, p.y() - size / 2, size, size)
                for p in found]

    def _text_box_made(self, start: QPointF, end: QPointF):
        """``(page, rect)`` for a text box made by a press and a release.

        **A click** makes the standard box, its top left at the click. **A
        drag** makes the box it drew, from the press to the release, which
        Acrobat takes as top left and bottom right whichever way it went.
        """
        if (end - start).manhattanLength() > QApplication.startDragDistance():
            found = self.mark_rect(start, end)
            if found is None:
                return None
            index, (x0, y0, x1, y1) = found
            return index, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        index = self.page_at(start)
        if index is None:
            return None
        at = self.page_point(index, start)
        if at is None:
            return None
        wide, tall = markup.TEXT_BOX_SIZE
        return index, self.to_source(
            index, (at[0], at[1] - tall, at[0] + wide, at[1]))

    @staticmethod
    def _shift_held() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)

    def _evened(self, start: QPointF, end: QPointF) -> QPointF:
        """``end``, moved to make a square with ``start`` while Shift is
        held: the side is the larger of the two distances, in the direction
        the pointer went."""
        if not self._shift_held():
            return end
        dx, dy = end.x() - start.x(), end.y() - start.y()
        side = max(abs(dx), abs(dy))
        return QPointF(start.x() + math.copysign(side, dx or 1.0),
                       start.y() + math.copysign(side, dy or 1.0))

    def _shape_made(self, start: QPointF, end: QPointF):
        """``(page, box)`` for a rectangle or an oval made from ``start`` to
        ``end``, either of which may be any corner; square with Shift.
        None when the two are too close to make anything."""
        end = self._evened(start, end)
        found = self.mark_rect(start, end)
        if found is None:
            return None
        index, (x0, y0, x1, y1) = found
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if box[2] - box[0] < 1.0 or box[3] - box[1] < 1.0:
            return None
        return index, box

    def _angled(self, start: QPointF, end: QPointF) -> QPointF:
        """``end``, turned to the nearest step of 45 degrees about
        ``start`` while Shift is held, at the same distance."""
        if not self._shift_held():
            return end
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy)
        turn = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        return QPointF(start.x() + length * math.cos(turn),
                       start.y() + length * math.sin(turn))

    def _point_on(self, index: int, point: QPointF, mine: bool):
        """A viewport point as a point on page ``index``, in the space a mark
        made here keeps -- the source page's -- or the shown page's."""
        at = self.page_point(index, point)
        if at is None:
            return None
        if mine:
            return tuple(self.to_source(index, (at[0], at[1], at[0], at[1]))[:2])
        return at

    #: How solid the stamp under the pointer is drawn, before it is placed.
    GHOST = 0.5

    def _paint_stamp_ghost(self, painter) -> None:
        """**The stamp under the crosshair**, faded, as Reader's cursor
        becomes the stamp: centred under the pointer at the size a click
        would place it, and while a drag sizes it, at the size it is being
        dragged to inside its dashed outline -- Acrobat shows nothing until
        the button is let go."""
        art = self.stamp_art() if self.stamp_art else None
        if not art:
            return
        if self._marking is not None:
            start, current = self._marking
            placed = self._stamp_placed(start, current)
            dragged = placed is not None and placed[1][0] != placed[1][2]
            point = start
        else:
            placed, dragged, point = None, False, self._stamp_hover
        if dragged:
            where = self.quad_on_screen(placed[0], placed[1])
        else:
            if point is None:
                return
            index = self.page_at(point)
            size = self.stamp_size() if self.stamp_size else None
            at = self._point_on(index, point, False) if index is not None else None
            if at is None or not size:
                return
            wide, tall = size
            where = self.quad_on_screen(
                index, (at[0] - wide / 2, at[1] - tall / 2,
                        at[0] + wide / 2, at[1] + tall / 2), scaled=False)
        if where is None or where.width() < 1:
            return
        ratio = max(float(painter.device().devicePixelRatioF()), 1.0)
        pixels = (max(1, round(where.width() * ratio)),
                  max(1, round(where.height() * ratio)))
        key = ("ghost", len(art), hash(art), pixels)
        image = self._art_images.get(key)
        if image is None:
            image = self._render_art(art, pixels)
            if len(self._art_images) > 64:
                self._art_images.clear()
            self._art_images[key] = image
        painter.save()
        if image is not None:
            painter.setOpacity(self.GHOST)
            painter.drawImage(where, image)
            painter.setOpacity(1.0)
        if dragged:
            pen = QPen(MARKING)
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(where)
        painter.restore()

    def viewportEvent(self, event):
        """The stamp under the pointer goes when the pointer leaves."""
        if event.type() == QEvent.Leave and self._stamp_hover is not None:
            self._stamp_hover = None
            self.viewport().update()
        return super().viewportEvent(event)

    def _stamp_placed(self, start: QPointF, end: QPointF):
        """``(page, rect)`` for a stamp: a bare point for a click, which the
        window centres the stamp on at its own size, or for a drag a
        rectangle from ``start`` keeping the stamp's proportions, as big as
        the further way the pointer has gone. None off every page."""
        index = self.page_at(start)
        if index is None:
            return None
        a = self._point_on(index, start, True)
        if a is None:
            return None
        if (end - start).manhattanLength() <= QApplication.startDragDistance():
            return index, (a[0], a[1], a[0], a[1])
        b = self._point_on(index, end, True)
        size = self.stamp_size() if self.stamp_size else None
        if b is None or not size or size[0] <= 0 or size[1] <= 0:
            return index, (a[0], a[1], a[0], a[1])
        wide, tall = size
        dx, dy = b[0] - a[0], b[1] - a[1]
        scale = max(abs(dx) / wide, abs(dy) / tall)
        x2 = a[0] + math.copysign(wide * scale, dx or 1.0)
        y2 = a[1] + math.copysign(tall * scale, dy or 1.0)
        return index, (min(a[0], x2), min(a[1], y2), max(a[0], x2), max(a[1], y2))

    def _callout_made(self, start: QPointF, end: QPointF):
        """``(page, (tip, centre))`` for a callout: the tip of its leader at
        ``start`` and the centre of its box at ``end``. Shift does nothing.
        None when the two are too close to make one."""
        index = self.page_at(start)
        if index is None:
            return None
        a = self._point_on(index, start, True)
        b = self._point_on(index, end, True)
        if a is None or b is None or math.dist(a, b) < 1.0:
            return None
        return index, (a[0], a[1], b[0], b[1])

    def _line_made(self, start: QPointF, end: QPointF):
        """``(page, points)`` for a line from ``start`` to ``end``, its
        start first; Shift keeps it to 45 degrees. None when the two are too
        close to make a line."""
        end = self._angled(start, end)
        index = self.page_at(start)
        if index is None:
            return None
        a = self._point_on(index, start, True)
        b = self._point_on(index, end, True)
        if a is None or b is None or math.dist(a, b) < 1.0:
            return None
        return index, (a[0], a[1], b[0], b[1])

    def _line_grips(self, index: int, mark, offset=None):
        """A line's two handles, one on each of its points."""
        points = self._line_points(mark)
        if not points:
            return []
        is_mine = isinstance(mark, markup.Annotation)
        size = float(self.GRIP)
        grips = []
        for x, y in ((points[0], points[1]), (points[2], points[3])):
            where = self.quad_on_screen(index, (x, y, x, y), offset,
                                        scaled=is_mine)
            if where is None:
                return []
            p = where.center()
            grips.append(QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
        return grips

    def _line_points(self, mark):
        """A line's two points as they are now: a handle's drag in flight,
        else a move in flight, else its own."""
        if self._line_shaping is not None and self._line_shaping[0] is mark:
            return self._line_shaping[1]
        points = getattr(mark, "points", None)
        if not points:
            return None
        rect, _angle = self._shape_of(mark)
        dx, dy = rect[0] - mark.rect[0], rect[1] - mark.rect[1]
        return (points[0] + dx, points[1] + dy, points[2] + dx, points[3] + dy)

    def _shape_grips(self, index: int, mark, offset=None):
        """A rectangle's or an oval's eight handles, on the box it is drawn
        in, as viewport squares."""
        found = self._shape_on_screen(index, mark, offset)
        if found is None:
            return []
        where = found[0]
        size = float(self.GRIP)
        grips = []
        for fx, fy in self.TEXT_BOX_HANDLES:
            p = QPointF(where.left() + where.width() * fx,
                        where.bottom() - where.height() * fy)
            grips.append(QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
        return grips

    def _shape_shaped(self, index: int, mark, which: int, start, point):
        """``(rect, 0)`` for a rectangle or an oval whose handle ``which`` is
        at ``point``, from the rectangle the drag began with.

        **The handle says whether the shape is kept.** On a square or a
        circle a corner keeps it so and a side stretches it into a rectangle
        or an oval; on a rectangle or an oval every handle is free, and
        Shift on a corner makes it a square or a circle -- the opposite
        corner held, the side the larger of the two distances to the
        pointer. The rectangle answered is the mark's own: for one the file
        brought, the box grown again by its `/RD`."""
        at = self.page_point(index, point)
        if at is None:
            return None
        x, y = at
        is_mine = isinstance(mark, markup.Annotation)
        if is_mine:
            x, y = self.to_source(index, (x, y, x, y))[:2]
        rd = (getattr(mark, "rd", None) or (0.0,) * 4) if not is_mine else (0.0,) * 4
        left, bottom, right, top = (start[0] + rd[0], start[1] + rd[1],
                                    start[2] - rd[2], start[3] - rd[3])
        fx, fy = self.TEXT_BOX_HANDLES[which]
        small = self.SMALLEST_TEXT_BOX
        even = abs((right - left) - (top - bottom)) <= markup.EVEN_WITHIN
        corner = fx != 0.5 and fy != 0.5
        if corner and (even or self._shift_held()):
            # The opposite corner holds still; the side follows the pointer.
            hold_x = right if fx == 0 else left
            hold_y = top if fy == 0 else bottom
            side = max(abs(x - hold_x), abs(y - hold_y), small)
            if fx == 0:
                left, right = hold_x - side, hold_x
            else:
                left, right = hold_x, hold_x + side
            if fy == 0:
                bottom, top = hold_y - side, hold_y
            else:
                bottom, top = hold_y, hold_y + side
        else:
            if fx == 0:
                left = min(x, right - small)
            elif fx == 1:
                right = max(x, left + small)
            if fy == 0:
                bottom = min(y, top - small)
            elif fy == 1:
                top = max(y, bottom + small)
        return ((left - rd[0], bottom - rd[1], right + rd[2], top + rd[3]), 0.0)

    def _text_area(self, index: int, mark, rect):
        """``(screen rect, width in points, border width)`` of the part of a
        text box its words go in: the box inset by twice the border."""
        is_mine = isinstance(mark, markup.Annotation)
        if not is_mine:
            rect = self._box_within(mark, rect)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness))
        pad = 2.0 * width
        left, bottom, right, top = rect
        area = (left + pad, bottom + pad, right - pad, top - pad)
        where = self.quad_on_screen(index, area, scaled=is_mine)
        return where, max(right - left - 2 * pad, 1.0), width

    def edit_text_box(self, index: int, mark, at: Optional[QPointF] = None):
        """Open a text box for typing: the cursor at ``at``, or at the end.

        **On the page**: an editor laid over the box at the zoom, in the
        box's font and laid out by the rules the file is, so what is typed
        is seen where and how it will be written. No handles while typing.
        """
        self.finish_editing()
        rect = tuple(mark.rect)
        where, wide, _width = self._text_area(index, mark, rect)
        if where is None:
            return
        content = textbox.content_of(mark)
        scale = where.width() / wide if wide else 1.0
        editor = _TextBoxEditor(self.viewport())
        # Points to the editor's own: the size times the zoom, by way of the
        # screen's dots an inch, which is what a font's point size means.
        editor.factor = scale * 72.0 / max(editor.logicalDpiY(), 1)
        editor.content = content
        editor.setFrameStyle(QFrame.NoFrame)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setStyleSheet("QTextEdit { background: transparent; }")
        editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        editor.document().setDocumentMargin(0)
        textbox.fill(editor.document(), content, editor.factor)
        editor.document().clearUndoRedoStacks()
        self.select_mark(None)
        self._text_editing = (index, mark, editor, rect)
        self._place_editor(editor, where)
        editor.textChanged.connect(self._text_box_changed)
        editor.finished.connect(self.finish_text_box)
        editor.show()
        editor.setFocus()
        if at is not None:
            editor.setTextCursor(editor.cursorForPosition(
                editor.mapFrom(self.viewport(), at.toPoint())))
        else:
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)
        self.viewport().update()
        self.text_editing_started.emit(editor)

    def _text_box_changed(self) -> None:
        """Grow the box as the text needs, never below where it began."""
        if self._text_editing is None:
            return
        index, mark, editor, began = self._text_editing
        where, wide, width = self._text_area(index, mark, began)
        if where is None:
            return
        needed = textbox.needed_height(editor.typed(), wide)
        left, bottom, right, top = began
        if markup.is_callout(mark) and not isinstance(mark, markup.Annotation):
            # A file's callout: its rectangle reaches round the leader, so
            # it grows by what the box inside it needs.
            box = self._box_within(mark, began)
            grow = max(0.0, needed + 4.0 * width - (box[3] - box[1]))
            rect = (left, bottom - grow, right, top)
        else:
            tall = max(top - bottom, needed + 4.0 * width
                       + 2.0 * float(getattr(mark, "inset", 0.0) or 0.0))
            rect = (left, top - tall, right, top)
        self._shaping = (mark, rect, 0.0)
        grown, _wide, _w = self._text_area(index, mark, rect)
        if grown is not None:
            self._place_editor(editor, grown)
        self.viewport().update()

    def _follow_editor(self) -> None:
        """Keep the editor over its box when the page moves under it.

        **Laid over the page, not part of it**, so a scroll, a zoom or a
        window resized moves the box and leaves the editor where it was --
        the words stayed put while their box scrolled away. Placed again
        from where the box is now; and after a zoom its words are put back
        at the new scale, from the box's words as they stand, the cursor
        and selection kept. The editor's own undo starts again at that
        point; the whole edit is still one step in the window's undo.
        """
        if self._text_editing is None:
            return
        index, mark, editor, began = self._text_editing
        rect = (tuple(self._shaping[1])
                if self._shaping is not None and self._shaping[0] is mark
                else began)
        where, wide, _width = self._text_area(index, mark, rect)
        if where is None:
            return
        factor = ((where.width() / wide if wide else 1.0)
                  * 72.0 / max(editor.logicalDpiY(), 1))
        if abs(factor - editor.factor) > 1e-6:
            typed = editor.typed()
            cursor = editor.textCursor()
            anchor, position = cursor.anchor(), cursor.position()
            editor.blockSignals(True)
            try:
                editor.factor = factor
                textbox.fill(editor.document(), typed, factor)
                editor.document().clearUndoRedoStacks()
                cursor = editor.textCursor()
                end = max(0, editor.document().characterCount() - 1)
                cursor.setPosition(min(anchor, end))
                cursor.setPosition(min(position, end), QTextCursor.KeepAnchor)
                editor.setTextCursor(cursor)
            finally:
                editor.blockSignals(False)
        self._place_editor(editor, where)

    @staticmethod
    def _place_editor(editor, where: QRectF) -> None:
        """Space the editor's lines as the drawn text's are and lay it over
        ``where``."""
        editor.blockSignals(True)
        try:
            textbox.apply_spacing(editor.document())
        finally:
            editor.blockSignals(False)
        editor.setGeometry(where.toAlignedRect())

    def finish_text_box(self) -> None:
        """End typing into a text box, keeping what was typed: a click
        outside it or Escape. The box settles to the larger of where it
        began and what its text needs, which is the shape typing left."""
        if self._text_editing is None:
            return
        index, mark, editor, began = self._text_editing
        self._text_editing = None
        typed = editor.typed()
        rect = (tuple(self._shaping[1])
                if self._shaping is not None and self._shaping[0] is mark
                else began)
        self._shaping = None
        editor.hide()
        editor.deleteLater()
        self.setFocus()
        self.viewport().update()
        self.text_editing_ended.emit()
        if typed[:2] != editor.content[:2] or rect != began:
            self.text_box_edited.emit(index, mark, typed.text, typed.rich, rect)

    #: A text box's handles, in order: the corners clockwise from the top
    #: left, then the middles of the top, right, bottom and left sides.
    TEXT_BOX_HANDLES = ((0, 1), (1, 1), (1, 0), (0, 0),
                        (0.5, 1), (1, 0.5), (0.5, 0), (0, 0.5))

    def _text_box_grips(self, index: int, mark, offset=None):
        """A text box's eight handles, as viewport squares."""
        rect, _angle = self._shape_of(mark)
        left, bottom, right, top = rect
        is_mine = isinstance(mark, markup.Annotation)
        size = float(self.GRIP)
        found = []
        for fx, fy in self.TEXT_BOX_HANDLES:
            x, y = left + (right - left) * fx, bottom + (top - bottom) * fy
            where = self.quad_on_screen(index, (x, y, x, y), offset,
                                        scaled=is_mine)
            if where is None:
                return []
            p = where.center()
            found.append(QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
        return found

    #: The smallest a text box can be pulled to, in points.
    SMALLEST_TEXT_BOX = 6.0

    def _text_box_shaped(self, index: int, mark, which: int, start, point):
        """``(rect, 0)`` for a text box whose handle ``which`` is at ``point``.

        **The opposite side holds still** and the proportions are free: a
        corner moves the two sides that meet there, a side's middle moves
        that side alone. Measured from the rectangle the drag began with.
        """
        at = self.page_point(index, point)
        if at is None:
            return None
        x, y = at
        if isinstance(mark, markup.Annotation):
            x, y = self.to_source(index, (x, y, x, y))[:2]
        left, bottom, right, top = start
        fx, fy = self.TEXT_BOX_HANDLES[which]
        small = self.SMALLEST_TEXT_BOX
        if fx == 0:
            left = min(x, right - small)
        elif fx == 1:
            right = max(x, left + small)
        if fy == 0:
            bottom = min(y, top - small)
        elif fy == 1:
            top = max(y, bottom + small)
        return ((left, bottom, right, top), 0.0)

    def _shape_of(self, mark):
        """``(rect, rotate)`` for a mark: the gesture's, or its own.

        **One answer for every painter.** The outline, the handles and the
        glyph all ask this, so a mark being dragged cannot have its box in
        one place and its drawing in another -- which is what it did, and
        what made a move look like two marks disagreeing.
        """
        if self._shaping is not None and self._shaping[0] is mark:
            return self._shaping[1], self._shaping[2]
        return tuple(mark.rect), float(getattr(mark, "rotate", 0.0) or 0.0)

    def _stamp_centre(self, index: int, mark):
        """The viewport point a stamp scales and turns about."""
        is_mine = isinstance(mark, markup.Annotation)
        where = self.quad_on_screen(index, mark.rect, scaled=is_mine)
        return where.center() if where is not None else QPointF()

    def _stamp_shaped(self, index: int, mark, which: int, centre, point):
        """``(rect, rotate)`` for a stamp whose handle is at ``point``.

        **Both handles work about the centre**, which is the only point the
        fit to `/Rect` holds still. A corner says how far out it is: the
        ratio of its distance from the centre now to what that distance was
        at the size the icon is drawn at, so the aspect can never change
        because one number does both axes. The fifth handle says which way
        is up, and the size it had is kept.
        """
        icon = getattr(mark, "icon", "")
        was = float(getattr(mark, "rotate", 0.0) or 0.0)
        middle = self.page_point(index, centre)
        here = self.page_point(index, point)
        if middle is None or here is None:
            return None
        across, down = here[0] - middle[0], here[1] - middle[1]
        if which == 4:
            # Turning. The handle stands off the top edge, so the angle it
            # reports is measured from straight up rather than from the
            # x axis, and the stamp keeps the size it had.
            angle = math.degrees(math.atan2(across, down))
            return (markup.stamp_rect(
                middle[0], middle[1], icon,
                markup.stamp_scale(mark.rect, icon, was), -angle), -angle)
        wide, tall = markup.icon_size(icon)
        half = math.hypot(wide, tall) / 2.0
        reach = math.hypot(across, down)
        if half <= 0:
            return None
        scale = max(reach / half, self.SMALLEST_STAMP / half)
        return (markup.stamp_rect(middle[0], middle[1], icon, scale, was), was)

    #: How small a stamp may be dragged, as the half-diagonal of its
    #: artwork in points. Below this it stops being something you can take
    #: hold of again.
    SMALLEST_STAMP = 6.0

    def grip_at(self, point: QPointF):
        """Which grip is under a viewport point: 0 for the start, 1 for the
        end, or None."""
        for n, where in enumerate(self.grips()):
            # A little slack: an 11-pixel circle is small to hit exactly,
            # and missing it starts a text selection instead of a resize.
            if where.adjusted(-3, -3, 3, 3).contains(point):
                return n
        return None

    def _grip_quads(self, index, anchor, point):
        """The run between ``anchor`` and a viewport ``point``.

        The same call the drag that *makes* a highlight uses, which is the
        whole reason a resize is cheap: a grip moves one end of the pair and
        the run is built again from the text, rather than the quadrilaterals
        being stretched. A highlight is a run of text and not a box.
        """
        here = self.page_point(index, point)
        if here is None:
            return ()
        try:
            return tuple(self._glyphs.quads(index, anchor, here))
        except Exception:       # noqa: BLE001 - a drag must not raise
            return ()

    def _paint_grips(self, painter, index: int, offset: QPointF) -> None:
        """Draw the selected mark's grips, if it is on this page."""
        if self._selected is None or self._selected[0] != index:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(*self.SELECTED))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255))
        for where in self.grips(offset):
            painter.drawEllipse(where)
        painter.restore()

    def _paint_selected(self, painter, index: int, offset: QPointF) -> None:
        """Outline the mark under the pointer, and the one that is selected.

        **The same outline for both**, which is Acrobat's answer and is the
        right one: the outline says how far the mark reaches, and that does
        not change according to whether you have committed to it. A faded
        version was tried first and reads as a worse selection rather than as
        a different state.

        What tells the two apart is the bar of buttons, which appears only
        for the mark that is actually selected.

        The same mark is drawn once when it is both, so two pens do not land
        on top of each other and come out heavier than either.
        """
        if self._dragging_grip is not None and self._preview:
            # The outline follows the run being built, so the whole band
            # redraws as the grip moves instead of the old shape sitting
            # there while a new one grows beside it.
            page = self._dragging_grip[1]
            if page != index:
                painter.save()
                painter.restore()
                return
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(Qt.NoBrush)
            pen = QPen(QColor(*self.SELECTED))
            pen.setWidthF(self.OUTLINE)
            painter.setPen(pen)
            viewport = QRectF(self.viewport().rect())
            for quad in self._preview:
                where = self.quad_on_screen(index, quad, offset, scaled=False)
                if where is None or not where.intersects(viewport):
                    continue
                painter.drawRoundedRect(where.adjusted(-1, -1, 1, 1),
                                        self.OUTLINE_RADIUS,
                                        self.OUTLINE_RADIUS)
            painter.restore()
            return

        marks = [m for m in (self._hovered, self._selected) if m is not None]
        if len(marks) == 2 and marks[0] == marks[1]:
            marks.pop()
        # **A drawing shows its box only once it is selected**, as Acrobat
        # does: a line's box, or a rectangle's or an oval's, drawn on hover
        # covered the words round it with a frame nobody had asked for.
        marks = [m for m in marks if m == self._selected or (
            m[1].kind if isinstance(m[1], markup.Annotation)
            else m[1].subtype) not in (*markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK)
            and not markup.is_stamp(m[1])]
        viewport = QRectF(self.viewport().rect())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(QColor(*self.SELECTED))
        # A width that does not grow with the zoom: this is a piece of the
        # interface drawn over the page, not something on the paper.
        pen.setWidthF(self.OUTLINE)
        painter.setPen(pen)
        for where_page, mark in marks:
            if where_page != index:
                continue
            for where in self.mark_screen_boxes(index, mark, offset):
                if not where.intersects(viewport):
                    continue
                painter.drawRoundedRect(where.adjusted(-1, -1, 1, 1),
                                        self.OUTLINE_RADIUS,
                                        self.OUTLINE_RADIUS)
        painter.restore()

    def quad_on_screen(self, index: int, quad, offset=None, scaled=True):
        """One of a mark's quadrilaterals as a viewport rectangle, or None.

        ``scaled`` says which space the quadrilateral arrived in, and it is
        not a detail: a mark the *user* made is kept in the source page's
        space and has to be multiplied by the page's resize, while a mark read
        out of the document on screen is already in that document's space --
        it went through the resize when the export was made. Putting the one
        through the other's path moves it by the resize factor, which is
        invisible at 100% and wrong everywhere else.

        Drawing and hit-testing share this so that what a click lands on is
        measured the same way as what was drawn. Factored out when selection
        arrived, because a second copy of this arithmetic is a second place
        for the two to disagree -- which is the mistake the drag's feedback
        had already made once.
        """
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return None
        zoom = self._layout.zoom
        page_rect = self._layout.page_rect(index)
        shown = forms_module.to_displayed(
            self.from_source(index, quad) if scaled else tuple(quad), box)
        where = QRectF(page_rect.x() + shown[0] * zoom,
                       page_rect.y() + (height - shown[3]) * zoom,
                       (shown[2] - shown[0]) * zoom,
                       (shown[3] - shown[1]) * zoom)
        where.translate(-(self.offset() if offset is None else offset))
        return where

    def _paint_squiggle(self, painter, where, colour) -> None:
        """The squiggly underline: a wave along the foot of the run.

        **A fraction of the run, not a fixed size.** Reader's tile is 10 by
        12 and is placed through a `cm` that is itself a fraction of the
        type's height, so the wave on a heading is bigger than the wave on
        a footnote. The same numbers `markup._zigzag` writes into the file,
        so what is on the screen is what will be in it.
        """
        up = where.height() * markup.SQUIGGLE_SCALE
        step = max(2.0, up * markup.SQUIGGLE_ASPECT * markup.SQUIGGLE_CYCLE)
        base = where.bottom() - where.height() * markup.SQUIGGLE_BASE
        low = base - up * markup.SQUIGGLE_LOW
        high = base - up * markup.SQUIGGLE_HIGH
        path = QPainterPath()
        path.moveTo(where.left(), low)
        at = where.left()
        while at < where.right():
            peak = min(at + step / 2.0, where.right())
            path.lineTo(peak, high)
            at += step
            if min(at, where.right()) <= peak:
                break
            path.lineTo(min(at, where.right()), low)
        pen = QPen(colour)
        pen.setWidthF(max(0.8, markup.SQUIGGLE_PEN * math.sqrt(
            up * up * markup.SQUIGGLE_ASPECT)))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def _icon_drawing(self, icon: str, where: QRectF, colour: QColor):
        """An icon's appearance stream as things a painter can draw.

        **The same paths the file gets**, read back rather than drawn
        again: `markup._icon_appearance` writes Reader's stream and this
        walks it, so the icon on screen and the icon in the document
        cannot drift. Yields ``(path, fill, stroke, width)``.

        The operators are only the ones these seventeen use -- `m l c v y
        h` for the outline, `f S B b` to paint it, `q Q cm w gs rg G` for
        the state -- and the stream is Reader's, so the set is closed. PDF
        counts y upward from the box's foot and Qt counts it down from the
        top, which is the flip in `place`.
        """
        found = noteicons.ICONS.get(icon or "")
        if found is None:
            found = noteicons.ICONS[markup.DEFAULT_ICON]
        wide, tall, body = found
        body = body.replace(noteicons.FILL, "FILL rg")
        sx, sy = where.width() / wide, where.height() / tall

        def place(x, y, ctm):
            at_x = ctm[0] * x + ctm[2] * y + ctm[4]
            at_y = ctm[1] * x + ctm[3] * y + ctm[5]
            return QPointF(where.x() + at_x * sx, where.bottom() - at_y * sy)

        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        fill, stroke, width, alpha = QColor(colour), None, 1.0, 1.0
        saved, numbers, path = [], [], QPainterPath()
        here = (0.0, 0.0)
        for token in body.replace("[", " [ ").replace("]", " ] ").split():
            try:
                numbers.append(float(token))
                continue
            except ValueError:
                pass
            if token == "m" and len(numbers) >= 2:
                here = (numbers[-2], numbers[-1])
                path.moveTo(place(*here, ctm))
            elif token == "l" and len(numbers) >= 2:
                here = (numbers[-2], numbers[-1])
                path.lineTo(place(*here, ctm))
            elif token == "c" and len(numbers) >= 6:
                a, b, c, d, e, f = numbers[-6:]
                path.cubicTo(place(a, b, ctm), place(c, d, ctm),
                             place(e, f, ctm))
                here = (e, f)
            elif token == "v" and len(numbers) >= 4:
                c, d, e, f = numbers[-4:]
                path.cubicTo(place(*here, ctm), place(c, d, ctm),
                             place(e, f, ctm))
                here = (e, f)
            elif token == "y" and len(numbers) >= 4:
                a, b, e, f = numbers[-4:]
                path.cubicTo(place(a, b, ctm), place(e, f, ctm),
                             place(e, f, ctm))
                here = (e, f)
            elif token == "h":
                path.closeSubpath()
            elif token == "cm" and len(numbers) >= 6:
                a, b, c, d, e, f = numbers[-6:]
                ctm = [a * ctm[0] + b * ctm[2], a * ctm[1] + b * ctm[3],
                       c * ctm[0] + d * ctm[2], c * ctm[1] + d * ctm[3],
                       e * ctm[0] + f * ctm[2] + ctm[4],
                       e * ctm[1] + f * ctm[3] + ctm[5]]
            elif token == "w" and numbers:
                width = numbers[-1]
            elif token == "q":
                saved.append((list(ctm), QColor(fill) if fill else None,
                              QColor(stroke) if stroke else None, width, alpha))
            elif token == "Q" and saved:
                ctm, fill, stroke, width, alpha = saved.pop()
                ctm = list(ctm)
            elif token == "gs":
                alpha = 0.6
            elif token == "FILL":
                fill = QColor(colour)
            elif token == "G" and numbers:
                grey = int(max(0.0, min(1.0, numbers[-1])) * 255)
                stroke = QColor(grey, grey, grey)
            elif token == "rg" and len(numbers) >= 3:
                fill = QColor.fromRgbF(*[max(0.0, min(1.0, v))
                                         for v in numbers[-3:]])
            elif token in ("f", "S", "B", "b"):
                if token == "b":
                    path.closeSubpath()
                shown = QColor(fill) if fill else None
                drawn = QColor(stroke) if stroke else None
                if shown is not None:
                    shown.setAlphaF(shown.alphaF() * alpha)
                if drawn is not None:
                    drawn.setAlphaF(drawn.alphaF() * alpha)
                yield (path,
                       shown if token in ("f", "B", "b") else None,
                       drawn if token in ("S", "B", "b") else None,
                       max(width * (sx + sy) / 2.0, 0.6))
                path = QPainterPath()
            if token not in ("[", "]"):
                numbers = []

    def _note_rect_at(self, index: int, mark, corner: QPointF):
        """``mark``'s rectangle with its icon's top left at a viewport point.

        The arithmetic `icon_rect` does for a note being placed, with the
        icon this one already has rather than the tool's. The top left
        because that is the corner a note is anchored by, which is what a
        drag therefore moves.
        """
        box = self.page_box(index)
        height = self._layout.page_height(index)
        if box is None or height is None:
            return None
        at = self._layout.point_in_page(index, self.to_document(corner))
        # The corner alone through the frames, then the mark's own size put
        # back on it in the space the rectangle is kept in. Carrying the size
        # through as well would run it through the page's resize twice.
        point = self.to_source(index, forms_module.from_displayed(
            (at.x(), height - at.y(), at.x(), height - at.y()), box))
        wide = mark.rect[2] - mark.rect[0]
        tall = mark.rect[3] - mark.rect[1]
        if wide <= 0 or tall <= 0:
            wide, tall = markup.icon_size(
                getattr(mark, "icon", markup.DEFAULT_ICON))
        if (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype) in (markup.STAMP, markup.FREETEXT,
                                       *markup.SHAPES, markup.LINE,
                                       *markup.POLYS, markup.INK):
            # Moved, not reshaped: the box keeps the size and the angle it
            # was given and only its corner changes, which is what dragging
            # the body of one means.
            return (point[0], point[3] - tall, point[0] + wide, point[3])
        return markup.note_rect(point[0], point[3], wide, tall)

    def _file_notes(self, index: int):
        """The comments this page arrived with, for `_paint_marks` to draw.

        Their icons only. Every other kind the file carries is still drawn by
        the renderer, and so were these until `markup.blank_note_icons` began
        emptying them out of the document being shown -- which it does so
        that one glyph answers for every comment, saved or not.

        **Scalable comments as well**, for a different reason: left to the
        renderer they are baked into the page, so dragging one moved its
        outline and left the glyph behind until the button came up. Drawn
        here they follow the gesture like everything else that asks
        `_shape_of`.

        **Replies are not among them.** A reply is a `/Text` like the mark
        it answers and carries `/F` the same way, so it reaches here and
        has to be turned away: it is seen in the thread, not on the paper.
        Measured on `corpus/Markup Highlight.pdf`, whose three visible
        `/Text` annotations are three replies to one highlight -- drawn,
        they are three icons on a page that should show none.
        """
        try:
            return [m for m in self._file_marks.visible(index + 1)
                    if (m.subtype == markup.TEXT
                        or markup.is_scalable_comment(m.subtype, m.icon)
                        or m.subtype == markup.FREETEXT
                        or m.subtype in markup.SHAPES
                        or m.subtype == markup.LINE
                        or m.subtype in markup.POLYS
                        or m.subtype == markup.INK
                        or markup.is_stamp(m))
                    and not m.is_reply()]
        except Exception:       # noqa: BLE001 - a repaint must not fail
            return []

    @staticmethod
    def _solidity(mark) -> float:
        """How solid to draw ``mark``, as the file will have it.

        **Two questions that look like one.** A mark the file brought with
        no `/CA` is fully solid -- Reader omits the key rather than writing
        1 -- while a mark being made here with nothing chosen is drawn at
        its kind's starting point, which is what the export will write for
        it. A highlight is the case that differs: 0.4 when it is ours and
        new, 1 when a file says nothing about it.
        """
        return (markup.solidity(mark) if isinstance(mark, markup.Annotation)
                else markup.opacity_of(mark))

    def _faded(self, painter, where, opacity, draw) -> None:
        """Run ``draw`` as **one** drawing, composited at ``opacity``.

        `/CA` is a constant alpha on the whole annotation, not on each
        shape in it, and the difference shows: seven of the icons have
        white interiors and the balloon has two white bars, all drawn over
        the body beneath them. Fading shape by shape -- which is what
        `QPainter.setOpacity` does -- lets the body show through its own
        bars. So the glyph goes onto a transparent image of its own and
        that image is composited once, which is what a reader does with
        the appearance stream.

        Opaque marks skip all of it and draw straight onto the page.
        """
        if opacity is None or float(opacity) >= 1.0:
            draw(painter)
            return
        # Room for the antialiased edge, which otherwise lands outside the
        # box and is clipped away.
        box = where.adjusted(-2.0, -2.0, 2.0, 2.0).toAlignedRect()
        if box.isEmpty():
            return
        ratio = self.devicePixelRatioF()
        image = QImage(QSize(max(1, int(box.width() * ratio)),
                             max(1, int(box.height() * ratio))),
                       QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.transparent)
        inner = QPainter(image)
        try:
            inner.setRenderHint(QPainter.Antialiasing, True)
            # The glyph is drawn in viewport coordinates, so the image is
            # shifted under it rather than the drawing moved into the image.
            inner.translate(-box.topLeft())
            draw(inner)
        finally:
            inner.end()
        was = painter.opacity()
        painter.setOpacity(max(0.0, min(1.0, float(opacity))))
        painter.drawImage(box.topLeft(), image)
        painter.setOpacity(was)

    def _corner_grips(self, index: int, mark, offset=None):
        """A handle on each corner of a mark's box: top left, top right,
        bottom right, bottom left -- a Stamp's four."""
        where = self.note_icon_rect(index, mark, offset)
        if where is None:
            return []
        size = float(self.GRIP)
        return [QRectF(p.x() - size / 2, p.y() - size / 2, size, size)
                for p in (where.topLeft(), where.topRight(),
                          where.bottomRight(), where.bottomLeft())]

    def _stamp_resize_from(self, grip: int) -> bool:
        """Take hold of a Stamp's corner: the opposite one holds still."""
        page, mark = self._selected
        if getattr(mark, "locked", False):
            return False
        grips = self.grips()
        if not 0 <= grip < 4 or len(grips) < 4:
            return False
        mine = isinstance(mark, markup.Annotation)
        held = self._point_on(page, grips[grip].center(), mine)
        fixed = self._point_on(page, grips[(grip + 2) % 4].center(), mine)
        if held is None or fixed is None:
            return False
        way = (1.0 if held[0] >= fixed[0] else -1.0,
               1.0 if held[1] >= fixed[1] else -1.0)
        self._stamp_resizing = (page, mark, fixed, way)
        self._shaping = (mark, tuple(mark.rect), 0.0)
        return True

    #: The smallest a Stamp's shorter side can be pulled to, in points.
    SMALLEST_STAMP = 8.0

    def _stamp_resized(self, position: QPointF) -> None:
        """A Stamp's corner dragged: **its proportions kept**, as every
        reader's fit of its drawing to `/Rect` keeps them, by whichever way
        the pointer has gone further; the opposite corner holds still."""
        page, mark, fixed, way = self._stamp_resizing
        at = self._point_on(page, position, isinstance(mark, markup.Annotation))
        if at is None:
            return
        left, bottom, right, top = (float(v) for v in mark.rect)
        wide, tall = right - left, top - bottom
        if wide <= 0 or tall <= 0:
            return
        # By the way the pointer has moved further, in proportion to the
        # side: the larger of the two scales grew a stamp dragged mostly
        # inwards and a little outwards.
        across = (at[0] - fixed[0]) * way[0] / wide
        up = (at[1] - fixed[1]) * way[1] / tall
        scale = across if abs(across - 1.0) >= abs(up - 1.0) else up
        scale = max(scale, self.SMALLEST_STAMP / min(wide, tall))
        x2, y2 = fixed[0] + way[0] * wide * scale, fixed[1] + way[1] * tall * scale
        rect = (min(fixed[0], x2), min(fixed[1], y2), max(fixed[0], x2), max(fixed[1], y2))
        self._shaping = (mark, rect, 0.0)
        self._place_mark_buttons()
        self.viewport().update()

    def _paint_stamp_art(self, painter, index: int, mark, offset) -> None:
        """Draw a Stamp: its own drawing, rendered at the size it is shown
        and fitted to its rectangle -- at the one a drag in flight has given
        it -- at its opacity. **Drawn here and not left to the renderer**,
        which baked it into the page so that a drag carried the outline
        away from it."""
        art = getattr(mark, "art", None)
        if not art:
            return
        rect, _angle = self._shape_of(mark)
        where = self.quad_on_screen(index, rect, offset,
                                    scaled=isinstance(mark, markup.Annotation))
        if where is None or where.width() < 1 or where.height() < 1:
            return
        if not where.intersects(QRectF(self.viewport().rect())):
            return
        ratio = max(float(painter.device().devicePixelRatioF()), 1.0)
        size = (max(1, round(where.width() * ratio)),
                max(1, round(where.height() * ratio)))
        key = (id(mark), art and len(art), size)
        image = self._art_images.get(key)
        if image is None:
            image = self._render_art(art, size)
            if len(self._art_images) > 64:
                self._art_images.clear()
            self._art_images[key] = image
        if image is None:
            return
        painter.save()
        painter.setOpacity(painter.opacity() * self._solidity(mark))
        painter.drawImage(where, image)
        painter.restore()

    @staticmethod
    def _render_art(art: bytes, size):
        """A Stamp's drawing, one page of PDF, rendered to ``size`` pixels
        with a clear background."""
        try:
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(art)
            page = document[0]
            width, height = page.get_size()
            bitmap = page.render(scale=size[0] / width if width else 1.0,
                                 fill_color=(255, 255, 255, 0),
                                 draw_annots=False)
            picture = bitmap.to_pil().convert("RGBA")
            data = picture.tobytes()
            image = QImage(data, picture.width, picture.height,
                           picture.width * 4, QImage.Format_RGBA8888).copy()
            document.close()
            return image
        except Exception:       # noqa: BLE001 - a repaint must not fail
            return None

    def _callout_box(self, mark):
        """A callout's box as it is now, in its own space: a handle's drag
        in flight, else its rectangle -- less `/RD` for a file's."""
        if self._callout_shaping is not None and self._callout_shaping[0] is mark:
            return self._callout_shaping[1]
        rect, _angle = self._shape_of(mark)
        if isinstance(mark, markup.Annotation):
            return tuple(rect)
        return self._box_within(mark, rect)

    def _callout_points_now(self, mark, box):
        """A callout's leader as it is now: a handle's drag in flight, else
        its points moved by the top left of a drag of the whole mark --
        which typing never moves, the box growing downwards -- and found
        afresh to the box while typing grows it."""
        if self._callout_shaping is not None and self._callout_shaping[0] is mark:
            return self._callout_shaping[2]
        points = getattr(mark, "points", None)
        if not points or len(points) < 4:
            return None
        rect, _angle = self._shape_of(mark)
        dx, dy = rect[0] - mark.rect[0], rect[3] - mark.rect[3]
        points = tuple(v + (dx if k % 2 == 0 else dy) for k, v in enumerate(points))
        if (self._shaping is not None and self._shaping[0] is mark
                and len(points) >= 6):
            points = markup.callout_points(
                points[:2], box, markup.callout_knee(mark.points))
        return points

    def _callout_grips(self, index: int, mark, offset=None):
        """A callout's ten handles: eight on its box, as a text box has,
        then its tip and its knee."""
        box = self._callout_box(mark)
        points = self._callout_points_now(mark, box)
        is_mine = isinstance(mark, markup.Annotation)
        size = float(self.GRIP)
        left, bottom, right, top = box
        spots = [(left + (right - left) * fx, bottom + (top - bottom) * fy)
                 for fx, fy in self.TEXT_BOX_HANDLES]
        if points and len(points) >= 6:
            spots += [(points[0], points[1]), (points[2], points[3])]
        found = []
        for x, y in spots:
            where = self.quad_on_screen(index, (x, y, x, y), offset, scaled=is_mine)
            if where is None:
                return []
            p = where.center()
            found.append(QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
        return found

    def _callout_taken(self, page: int, mark, which, position: QPointF):
        """The start of a drag of a callout's handle or its box, or None."""
        start = self._point_on(page, position, isinstance(mark, markup.Annotation))
        box = self._callout_box(mark)
        points = self._callout_points_now(mark, box)
        if start is None or not points or len(points) < 6:
            return None
        return (page, mark, which, tuple(box), tuple(points), start)

    def _callout_press(self, grip: int, position: QPointF) -> bool:
        page, mark = self._selected
        if getattr(mark, "locked", False):
            return False
        self._callout_drag = self._callout_taken(page, mark, grip, position)
        return self._callout_drag is not None

    def _callout_dragged(self, position: QPointF) -> None:
        """A callout's handle or box dragged to ``position``. **The tip**
        goes anywhere, the leader finding the side nearest it; **the knee**
        lengthens or shortens the last stretch, square to its side; **a box
        handle** moves the sides it is on, the opposite ones holding still;
        **the box** moves alone. The leader always ends at the middle of the
        nearest side."""
        page, mark, which, box, points, start = self._callout_drag
        at = self._point_on(page, position, isinstance(mark, markup.Annotation))
        if at is None:
            return
        tip = points[:2]
        knee = markup.callout_knee(points)
        left, bottom, right, top = box
        if which == "box":
            dx, dy = at[0] - start[0], at[1] - start[1]
            box = (left + dx, bottom + dy, right + dx, top + dy)
        elif which == 8:
            tip = at
        elif which == 9:
            end, out = points[4:6], (points[2] - points[4], points[3] - points[5])
            span = math.hypot(*out)
            if span < 1e-6:
                found = markup.callout_points(tip, box, 1.0)
                out, span = (found[2] - found[4], found[3] - found[5]), 1.0
            knee = max(0.0, ((at[0] - end[0]) * out[0] + (at[1] - end[1]) * out[1]) / span)
        else:
            fx, fy = self.TEXT_BOX_HANDLES[which]
            least = self.SMALLEST_TEXT_BOX
            if fx == 0:
                left = min(at[0], right - least)
            elif fx == 1:
                right = max(at[0], left + least)
            if fy == 0:
                bottom = min(at[1], top - least)
            elif fy == 1:
                top = max(at[1], bottom + least)
            box = (left, bottom, right, top)
        self._callout_shaping = (mark, tuple(box),
                                 markup.callout_points(tip, box, knee))
        self._place_mark_buttons()
        self.viewport().update()

    def _callout_let_go(self) -> None:
        """A callout's drag let go: its box and leader as they ended."""
        drag, shaped = self._callout_drag, self._callout_shaping
        self._callout_drag = None
        self._callout_shaping = None
        self._place_mark_buttons()
        self.viewport().update()
        if drag is None or shaped is None:
            return
        page, mark = drag[0], drag[1]
        if shaped[1] != drag[3] or shaped[2] != drag[4]:
            self.callout_reshaped.emit(page, mark, shaped[1], shaped[2])

    @staticmethod
    def _box_within(mark, rect):
        """A file's text box within its rectangle: less a cloud's reach, or
        a callout's `/RD` side by side, which reaches round its leader."""
        rd = getattr(mark, "rd", None) if markup.is_callout(mark) else None
        if rd:
            return (rect[0] + rd[0], rect[1] + rd[1],
                    rect[2] - rd[2], rect[3] - rd[3])
        inset = float(getattr(mark, "inset", 0.0) or 0.0)
        return (rect[0] + inset, rect[1] + inset,
                rect[2] - inset, rect[3] - inset)

    def _callout_leader(self, mark, at, width: float, box=None):
        """``(path, pieces, bounds)`` for a callout's leader on screen, as
        `_callout_points_now` has it, the first stretch pulled back for the
        end at its tip as a line's is -- or None."""
        points = self._callout_points_now(
            mark, box if box is not None else self._callout_box(mark))
        if not points or len(points) < 4:
            return None
        pairs = list(zip(points[0::2], points[1::2]))
        ends = getattr(mark, "ends", None) or ("/None", "/None")
        first, pieces = markup.line_end_drawing(
            (*pairs[0], *pairs[1]), (ends[0], "/None"), width)
        pairs[0] = (first[0], first[1])
        path = QPainterPath()
        path.moveTo(at(*pairs[0]))
        for pair in pairs[1:]:
            path.lineTo(at(*pair))
        bounds = path.boundingRect()
        for kind, data, _filled in pieces:
            for p in ([data[:2]] if kind == "circle" else data):
                bounds = bounds.united(QRectF(at(*p), QSizeF(1, 1)))
        return path, [(kind, data, filled, at) for kind, data, filled in pieces], bounds

    def _paint_leader(self, layer, leader, colour, fill, width, scale, style):
        """A callout's leader and the end at its tip: in the box's line
        colour and width, dashed as its border is but **never clouded** --
        a cloud is the box's alone -- and a closed end filled with the
        box's fill. At 0 the leader is the thinnest line there is and a
        closed end has no outline, as Acrobat draws it."""
        path, pieces, _bounds = leader
        plain = {k: v for k, v in style.items() if k != "cloud"}
        pen = self._line_pen(colour, width, scale, plain)
        layer.setPen(pen)
        layer.setBrush(Qt.NoBrush)
        layer.drawPath(path)
        for kind, data, filled, at in pieces:
            end = QPainterPath()
            if kind == "circle":
                cx, cy, r = data
                end.addEllipse(at(cx, cy), r * scale, r * scale)
            else:
                end.moveTo(at(*data[0]))
                for point in data[1:]:
                    end.lineTo(at(*point))
                if kind == "closed":
                    end.closeSubpath()
            if filled:
                layer.fillPath(end, fill)
            if width > 0 or not filled:
                layer.setPen(pen)
                layer.setBrush(Qt.NoBrush)
                layer.drawPath(end)

    def _callout_hit(self, index: int, mark, point: QPointF) -> bool:
        """Whether a viewport point takes hold of a callout: inside its box,
        or within the ink tolerance of its leader or the end at its tip --
        not anywhere in the rectangle that reaches round them."""
        is_mine = isinstance(mark, markup.Annotation)
        box = self._callout_box(mark)
        where = self.quad_on_screen(index, box, scaled=is_mine)
        left, bottom, right, top = (float(v) for v in box)
        if where is None or right <= left or top <= bottom:
            return False
        if where.contains(point):
            return True
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness) or 0.0)
        leader = self._callout_leader(mark, at, width, box)
        if leader is None:
            return False
        path, pieces, _bounds = leader
        stroker = QPainterPathStroker()
        stroker.setWidth(width * sx + 2 * self.INK_TOLERANCE)
        if stroker.createStroke(path).contains(point):
            return True
        for kind, data, _filled, _at in pieces:
            end = QPainterPath()
            if kind == "circle":
                cx, cy, r = data
                end.addEllipse(at(cx, cy), r * sx, r * sx)
            else:
                end.moveTo(at(*data[0]))
                for p in data[1:]:
                    end.lineTo(at(*p))
                end.closeSubpath()
            if end.contains(point) or stroker.createStroke(end).contains(point):
                return True
        return False

    def _paint_text_box(self, painter, index: int, mark, offset) -> None:
        """Draw a text box made in this session: its fill and its border.

        The same drawing `markup` writes into the file -- the fill, then the
        border inset by half its width, dashed or clouded as its style says
        -- mapped from the page to where the box is on screen, at the
        rectangle a drag in flight has given it.
        """
        rect, _angle = self._shape_of(mark)
        is_mine = isinstance(mark, markup.Annotation)
        callout = markup.is_callout(mark)
        if callout:
            rect = self._callout_box(mark)
        elif not is_mine:
            rect = self._box_within(mark, rect)
        where = self.quad_on_screen(index, rect, offset, scaled=is_mine)
        if where is None or (not callout and not where.intersects(
                QRectF(self.viewport().rect()))):
            return
        left, bottom, right, top = (float(v) for v in rect)
        if right <= left or top <= bottom:
            return
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness))
        fill = QColor.fromRgbF(*(mark.fill or (1.0, 1.0, 1.0))[:3])
        border = QColor.fromRgbF(*(mark.colour or markup.swatch("Light Red"))[:3])
        path = QPainterPath()
        if "cloud" in style:
            found = markup.cloud_path(rect, style["cloud"], width)
            if found is None:
                return
            begin, curves = found
            path.moveTo(at(*begin))
            for c in curves:
                path.cubicTo(at(c[0], c[1]), at(c[2], c[3]), at(c[4], c[5]))
            path.closeSubpath()
        else:
            half = width / 2.0
            path.addRect(QRectF(at(left + half, top - half),
                                at(right - half, bottom + half)))
        reach = width * sx + 2.0
        leader = self._callout_leader(mark, at, width, rect) if callout else None
        bounds = path.boundingRect()
        if leader is not None:
            bounds = bounds.united(leader[2])
            reach += 9 * max(width, 1.0) * sx
        with self._as_one(painter, bounds.adjusted(
                -reach, -reach, reach, reach), self._solidity(mark)) as layer:
            layer.setRenderHint(QPainter.Antialiasing, True)
            if leader is not None:
                self._paint_leader(layer, leader, border, fill, width, sx, style)
            layer.fillPath(path, fill)
            if width > 0:
                layer.strokePath(path, self._line_pen(border, width, sx, style))
            content = textbox.content_of(mark)
            editing = (self._text_editing is not None
                       and self._text_editing[1] is mark)
            if not content.empty and not editing:
                # The words, laid out as the file lays them out, inside the
                # border inset by twice its width; the editor shows them
                # while they are being typed.
                inset = 2.0 * width
                layer.save()
                layer.translate(at(left + inset, top - inset))
                layer.scale(sx, sy)
                textbox.paint(layer, content,
                              max(right - left - 2 * inset, 1.0),
                              max(top - bottom - 2 * inset, 0.0))
                layer.restore()

    def _shape_on_screen(self, index: int, mark, offset=None):
        """``(box, at, sx, sy)`` for a rectangle or an oval: the box it is
        drawn in on screen, a function from page space to screen, and the
        scale each way -- at the rectangle a drag in flight has given it."""
        rect, _angle = self._shape_of(mark)
        is_mine = isinstance(mark, markup.Annotation)
        rd = getattr(mark, "rd", None) if not is_mine else None
        if rd:
            rect = (rect[0] + rd[0], rect[1] + rd[1],
                    rect[2] - rd[2], rect[3] - rd[3])
        where = self.quad_on_screen(index, rect, offset, scaled=is_mine)
        left, bottom, right, top = (float(v) for v in rect)
        if where is None or right <= left or top <= bottom:
            return None
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        return where, rect, at, sx, sy

    def _shape_path(self, mark, rect, at) -> Optional[QPainterPath]:
        """The line a rectangle or an oval is drawn along, on screen: the
        box or the oval inset by half the line, or the cloud round it."""
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness))
        path = QPainterPath()
        if "cloud" in style:
            found = (markup.cloud_oval_path(rect, style["cloud"], width)
                     if kind == markup.CIRCLE
                     else markup.cloud_path(rect, style["cloud"], width))
            if found is None:
                return None
            begin, curves = found
            path.moveTo(at(*begin))
            for c in curves:
                path.cubicTo(at(c[0], c[1]), at(c[2], c[3]), at(c[4], c[5]))
            path.closeSubpath()
            return path
        left, bottom, right, top = rect
        half = width / 2.0
        box = QRectF(at(left + half, top - half), at(right - half, bottom + half))
        if kind == markup.CIRCLE:
            path.addEllipse(box)
        else:
            path.addRect(box)
        return path

    def _paint_shape(self, painter, index: int, mark, offset) -> None:
        """Draw a rectangle or an oval: its fill, then its line in its
        style -- dashed, or a cloud -- at the rectangle a drag in flight has
        given it. **One that draws nothing** -- no line and no fill, which
        a file can bring -- shows a thin dashed outline while it is under the
        pointer or selected, so that it can be found and deleted."""
        found = self._shape_on_screen(index, mark, offset)
        if found is None:
            return
        where, rect, at, sx, _sy = found
        if not where.adjusted(-40, -40, 40, 40).intersects(
                QRectF(self.viewport().rect())):
            return
        path = self._shape_path(mark, rect, at)
        if path is None:
            return
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness))
        was = painter.opacity()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if markup.draws_nothing(mark):
            held = [m for m in (self._hovered, self._selected)
                    if m is not None and m[1] is mark]
            if held:
                pen = QPen(QColor(*self.SELECTED))
                pen.setWidthF(1.0)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
            painter.restore()
            return
        painter.restore()
        fill = getattr(mark, "fill", None)
        reach = width * sx + 2.0
        with self._as_one(painter, path.boundingRect().adjusted(
                -reach, -reach, reach, reach), was * self._solidity(mark)) as layer:
            layer.setRenderHint(QPainter.Antialiasing, True)
            if fill is not None:
                layer.fillPath(path, QColor.fromRgbF(*fill[:3]))
            if width > 0:
                layer.setPen(self._line_pen(
                    QColor.fromRgbF(*(mark.colour or (1.0, 0.0, 0.0))[:3]),
                    width, sx, style))
                layer.setBrush(Qt.NoBrush)
                layer.drawPath(path)

    def _shape_hit(self, index: int, mark, point: QPointF) -> bool:
        """Whether a viewport point takes hold of a rectangle or an oval.

        **By its line**, within the ink tolerance, and anywhere inside as
        well when it is filled -- or when it draws nothing at all, which is
        then the only way to find it. A cloud's line is the band its
        scallops reach across. For an oval, the oval and not its box."""
        found = self._shape_on_screen(index, mark)
        if found is None:
            return False
        where, rect, _at, sx, _sy = found
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness))
        tolerance = self.INK_TOLERANCE
        inward = width * sx + tolerance
        outward = tolerance
        if "cloud" in style:
            reach = (markup.cloud_oval_radius(style["cloud"], width)
                     if kind == markup.CIRCLE
                     else markup.cloud_radius(style["cloud"], width))
            outward += reach * sx
            inward += reach * sx
        solid = (getattr(mark, "fill", None) is not None
                 or markup.draws_nothing(mark))
        if kind == markup.CIRCLE:
            cx, cy = where.center().x(), where.center().y()
            a, b = where.width() / 2.0, where.height() / 2.0
            dx, dy = point.x() - cx, point.y() - cy
            far = math.hypot(dx, dy)
            if a <= 0 or b <= 0:
                return False
            if far == 0:
                return solid or min(a, b) <= inward
            # The oval's own distance from its centre that way.
            edge = a * b / math.hypot(b * dx / far, a * dy / far)
            off = far - edge
            return off <= outward and (solid or off >= -inward)
        grown = where.adjusted(-outward, -outward, outward, outward)
        if not grown.contains(point):
            return False
        if solid:
            return True
        inner = where.adjusted(inward, inward, -inward, -inward)
        return not (inner.isValid() and inner.contains(point))

    def _line_on_screen(self, index: int, mark, offset=None):
        """``(segment, pieces, at, scale)`` for a line on screen: its own two
        points and its ends as `markup.line_end_drawing` gives them, a
        function from page space to screen, and the zoom -- moved with the
        rectangle a drag in flight has given it."""
        points = self._line_points(mark)
        if not points:
            return None
        if self._line_shaping is not None and self._line_shaping[0] is mark:
            rect = markup.line_rect(points, getattr(mark, "ends", None)
                                    or ("/None", "/None"),
                                    float(getattr(mark, "thickness", 1.0) or 0.0))
        else:
            rect, _angle = self._shape_of(mark)
        is_mine = isinstance(mark, markup.Annotation)
        left, bottom, right, top = (float(v) for v in rect)
        where = self.quad_on_screen(index, rect, offset, scaled=is_mine)
        if where is None or right <= left or top <= bottom:
            return None
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        segment, pieces = markup.line_end_drawing(
            points, getattr(mark, "ends", None) or ("/None", "/None"),
            float(getattr(mark, "thickness", 1.0) or 0.0))
        return segment, pieces, at, sx

    def _paint_line(self, painter, index: int, mark, offset) -> None:
        """Draw a line and its ends: the line in its colour, thickness and
        dash, each end in its style and the same dash -- a closed one filled
        with the line's fill -- at the place a drag in flight has carried it.
        A line of 0 is the thinnest that can be drawn, and its ends have no
        outline."""
        found = self._line_on_screen(index, mark, offset)
        if found is None:
            return
        segment, pieces, at, scale = found
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        colour = QColor.fromRgbF(*(mark.colour or (1.0, 0.0, 0.0))[:3])
        fill = getattr(mark, "fill", None)
        # Everything the line draws, to size the layer it is drawn in.
        spots = [at(segment[0], segment[1]), at(segment[2], segment[3])]
        for kind, data, _filled in pieces:
            if kind == "circle":
                cx, cy, r = data
                spots += [at(cx - r, cy - r), at(cx + r, cy + r)]
            else:
                spots += [at(*p) for p in data]
        reach = width * scale + 2.0
        bounds = QRectF(QPointF(min(p.x() for p in spots), min(p.y() for p in spots)),
                        QPointF(max(p.x() for p in spots), max(p.y() for p in spots)))
        with self._as_one(painter, bounds.adjusted(-reach, -reach, reach, reach),
                          painter.opacity() * self._solidity(mark)) as layer:
            layer.setRenderHint(QPainter.Antialiasing, True)
            layer.setPen(self._line_pen(colour, width, scale, style))
            layer.drawLine(at(segment[0], segment[1]), at(segment[2], segment[3]))
            # The ends take the line's dash, as Acrobat, PDFGear and Stirling
            # PDF all draw them; at 0 they have no outline.
            end_pen = self._line_pen(colour, width, scale, style)
            for kind, data, filled in pieces:
                path = QPainterPath()
                if kind == "circle":
                    cx, cy, r = data
                    path.addEllipse(at(cx, cy), r * scale, r * scale)
                else:
                    path.moveTo(at(*data[0]))
                    for point in data[1:]:
                        path.lineTo(at(*point))
                    if kind == "closed":
                        path.closeSubpath()
                if filled and fill is not None:
                    layer.fillPath(path, QColor.fromRgbF(*fill[:3]))
                if width > 0 or not filled:
                    layer.setPen(end_pen)
                    layer.setBrush(Qt.NoBrush)
                    layer.drawPath(path)

    def _poly_points(self, mark):
        """A polygon's or a polyline's points as they are now, a flat run:
        a vertex's drag in flight, else moved with the rectangle a drag in
        flight has given it."""
        if self._poly_shaping is not None and self._poly_shaping[0] is mark:
            return self._poly_shaping[1]
        points = getattr(mark, "points", None)
        if not points:
            return None
        rect, _angle = self._shape_of(mark)
        dx, dy = rect[0] - mark.rect[0], rect[1] - mark.rect[1]
        return tuple(v + (dx if k % 2 == 0 else dy) for k, v in enumerate(points))

    #: How few points a polygon and a polyline can have.
    FEWEST = {"polygon": 3, "cloud": 3, "polyline": 2}

    def _poly_enough(self) -> bool:
        if self._poly_drawing is None:
            return False
        _page, points, _pointer = self._poly_drawing
        distinct = [p for n, p in enumerate(points)
                    if n == 0 or (p - points[n - 1]).manhattanLength() > 1]
        return len(distinct) >= self.FEWEST.get(self._tool, 2)

    def finish_poly(self) -> None:
        """Keep the polygon, cloud or polyline being made, with the points
        placed so far -- a double-click, Complete or Return -- if there are
        enough of them; a polygon closes by itself."""
        if self._poly_drawing is None:
            return
        page, points, _pointer = self._poly_drawing
        enough = self._poly_enough()
        self._poly_drawing = None
        self.viewport().update()
        self.drawing_changed.emit()
        if not enough:
            return
        flat = []
        last = None
        for p in points:
            if last is not None and (p - last).manhattanLength() <= 1:
                continue
            at = self._point_on(page, p, True)
            if at is None:
                continue
            flat += [at[0], at[1]]
            last = p
        self.mark_drawn.emit(self._tool, page, [tuple(flat)])

    def cancel_poly(self) -> None:
        """Throw away the polygon being made -- Cancel or Escape."""
        self._poly_drawing = None
        self.viewport().update()
        self.drawing_changed.emit()

    def _paint_poly_drawing(self, painter) -> None:
        """The polygon being made: its segments so far and the next one to
        the pointer, dashed, and back to the first point for a polygon."""
        if self._poly_drawing is None:
            return
        _page, points, pointer = self._poly_drawing
        trail = list(points) + [self._angled(points[-1], pointer)]
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(MARKING)
        pen.setStyle(Qt.DashLine)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for a, b in zip(trail, trail[1:]):
            painter.drawLine(a, b)
        if self._tool != self.POLYLINE and len(trail) > 2:
            painter.drawLine(trail[-1], trail[0])
        painter.restore()

    @staticmethod
    def _poly_vertices(mark):
        """A mark's vertices as a flat run, a polygon's without the first
        point Acrobat repeats to close it."""
        points = list(getattr(mark, "points", None) or ())
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        if (kind == markup.POLYGON and len(points) >= 6
                and abs(points[0] - points[-2]) < 1e-6
                and abs(points[1] - points[-1]) < 1e-6):
            points = points[:-2]
        return tuple(points)

    def _poly_grips(self, index: int, mark, offset=None):
        """A handle on each vertex of a polygon or a polyline."""
        found = self._poly_on_screen(index, mark, offset)
        if found is None:
            return []
        _points, at, _scale = found
        shaped = (self._poly_shaping[1] if self._poly_shaping is not None
                  and self._poly_shaping[0] is mark else None)
        vertices = shaped or self._poly_vertices(mark)
        if shaped is None:
            rect, _angle = self._shape_of(mark)
            dx, dy = rect[0] - mark.rect[0], rect[1] - mark.rect[1]
            vertices = tuple(v + (dx if k % 2 == 0 else dy)
                             for k, v in enumerate(vertices))
        size = float(self.GRIP)
        grips = []
        for x, y in zip(vertices[0::2], vertices[1::2]):
            p = at(x, y)
            grips.append(QRectF(p.x() - size / 2, p.y() - size / 2, size, size))
        return grips

    def _vertex_snapped(self, index: int, mark, points, which: int,
                        pointer: QPointF) -> QPointF:
        """Where a dragged vertex goes: the pointer, or with Shift the
        pointer brought into line with where the vertex began -- straight
        across, straight up or down, or at 45 degrees.

        **The movement, not the segments**, as Illustrator, Figma, Sketch,
        PowerPoint and Blender constrain a dragged point. Holding both of a
        vertex's segments at 45 degrees was tried first and jumped the
        vertex away from the pointer, or held only one of them.

        **The nearest point on the line**, not the pointer's distance
        turned onto it: the vertex slides along the line under the pointer,
        and crossing to the next line steps across instead of swinging
        round an arc."""
        origin = getattr(self, "_vertex_origin", None)
        if not self._shift_held() or origin is None:
            return pointer
        dx, dy = pointer.x() - origin.x(), pointer.y() - origin.y()
        turn = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        along = dx * math.cos(turn) + dy * math.sin(turn)
        return QPointF(origin.x() + along * math.cos(turn),
                       origin.y() + along * math.sin(turn))

    def _add_vertex_entries(self, menu, index: int, mark, locked: bool) -> None:
        """Insert Vertex over a segment and Remove Vertex over a vertex --
        refused below a polygon's 3 points and a polyline's 2.

        **Only on the line itself**, within the reach that takes hold of it
        -- a cloud's being the band its scallops cross -- and the new vertex
        goes on the line where it was clicked, so the shape is unchanged
        until it is dragged. Offered anywhere off a vertex, it put the
        vertex at the click: a right-click in a polygon's fill pulled an
        edge into the middle of it."""
        here = self._menu_point
        found = self._poly_on_screen(index, mark)
        if here is None or found is None:
            return
        _points, at, _scale = found
        vertices = list(self._poly_vertices(mark))
        pairs = list(zip(vertices[0::2], vertices[1::2]))
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        fewest = 3 if kind == markup.POLYGON else 2
        reach = float(self.GRIP)
        near_vertex = next((n for n, p in enumerate(pairs)
                            if math.hypot(at(*p).x() - here.x(),
                                          at(*p).y() - here.y()) <= reach), None)
        menu.addSeparator()
        if near_vertex is not None:
            remove = menu.addAction(_("Remove Vertex"))
            remove.setEnabled(not locked and len(pairs) > fewest)
            left = pairs[:near_vertex] + pairs[near_vertex + 1:]
            remaining = tuple(v for pair in left for v in pair)
            remove.triggered.connect(
                lambda: self.line_reshaped.emit(index, mark, remaining))
            return
        segments = list(range(len(pairs) - (0 if kind == markup.POLYGON else 1)))
        best = None
        for n in segments:
            a, b = at(*pairs[n]), at(*pairs[(n + 1) % len(pairs)])
            dx, dy = b.x() - a.x(), b.y() - a.y()
            span = dx * dx + dy * dy or 1.0
            t = max(0.0, min(1.0, ((here.x() - a.x()) * dx + (here.y() - a.y()) * dy) / span))
            on = QPointF(a.x() + t * dx, a.y() + t * dy)
            distance = math.hypot(here.x() - on.x(), here.y() - on.y())
            if best is None or distance < best[0]:
                best = (distance, n, on)
        if best is None:
            return
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness) or 0.0)
        reach = width * _scale / 2.0 + self.INK_TOLERANCE
        if "cloud" in style and kind == markup.POLYGON:
            reach += 2 * markup.cloud_radius(style["cloud"], width) * _scale
        if best[0] > reach:
            return
        spot = self._point_on(index, best[2], isinstance(mark, markup.Annotation))
        if spot is None:
            return
        insert = menu.addAction(_("Insert Vertex"))
        insert.setEnabled(not locked)
        grown = pairs[:best[1] + 1] + [spot] + pairs[best[1] + 1:]
        added = tuple(v for pair in grown for v in pair)
        insert.triggered.connect(
            lambda: self.line_reshaped.emit(index, mark, added))

    def _poly_on_screen(self, index: int, mark, offset=None):
        """``(points, at, scale)`` for a polygon or a polyline on screen."""
        points = self._poly_points(mark)
        if not points or len(points) < 4:
            return None
        rect, _angle = self._shape_of(mark)
        is_mine = isinstance(mark, markup.Annotation)
        left, bottom, right, top = (float(v) for v in rect)
        where = self.quad_on_screen(index, rect, offset, scaled=is_mine)
        if where is None or right <= left or top <= bottom:
            return None
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        return points, at, sx

    def _poly_path(self, mark, points, at):
        """The line a polygon or a polyline is drawn along, on screen: the
        cloud along a polygon's edges when it has one, else its points,
        closed for a polygon -- with a polyline's first and last segments
        pulled back for its ends, as a line's are."""
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness) or 0.0)
        path = QPainterPath()
        if kind == markup.POLYGON:
            if "cloud" in style:
                found = markup.cloud_polygon_path(points, style["cloud"], width)
                if found is not None:
                    begin, curves = found
                    path.moveTo(at(*begin))
                    for c in curves:
                        path.cubicTo(at(c[0], c[1]), at(c[2], c[3]), at(c[4], c[5]))
                    path.closeSubpath()
                    return path, []
            corners = markup.polygon_corners(points)
            if len(corners) < 2:
                return path, []
            path.moveTo(at(*corners[0]))
            for corner in corners[1:]:
                path.lineTo(at(*corner))
            path.closeSubpath()
            return path, []
        pairs = list(zip(points[0::2], points[1::2]))
        ends = getattr(mark, "ends", None) or ("/None", "/None")
        first, start_pieces = markup.line_end_drawing(
            (*pairs[0], *pairs[1]), (ends[0], "/None"), width)
        last, end_pieces = markup.line_end_drawing(
            (*pairs[-2], *pairs[-1]), ("/None", ends[1]), width)
        pairs[0] = (first[0], first[1])
        pairs[-1] = (last[2], last[3])
        path.moveTo(at(*pairs[0]))
        for pair in pairs[1:]:
            path.lineTo(at(*pair))
        return path, start_pieces + end_pieces

    def _paint_poly(self, painter, index: int, mark, offset) -> None:
        """Draw a polygon or a polyline: a polygon's fill, then the line in
        its colour, thickness and dash -- a cloud along a polygon's edges --
        and a polyline's ends in their styles, as a line's are; faded as one
        piece. One that draws nothing shows its dashed outline while it is
        under the pointer or selected."""
        found = self._poly_on_screen(index, mark, offset)
        if found is None:
            return
        points, at, scale = found
        path, pieces = self._poly_path(mark, points, at)
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness) or 0.0)
        fill = getattr(mark, "fill", None)
        colour = QColor.fromRgbF(*(mark.colour or (1.0, 0.0, 0.0))[:3])
        # A polygon's 0 is No Border; a polyline's is the thinnest line.
        no_line = kind == markup.POLYGON and width <= 0
        if no_line and fill is None:
            held = [m for m in (self._hovered, self._selected)
                    if m is not None and m[1] is mark]
            if held:
                painter.save()
                pen = QPen(QColor(*self.SELECTED))
                pen.setWidthF(1.0)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
                painter.restore()
            return
        reach = width * scale + 2.0
        bounds = path.boundingRect()
        for _kind, data, _filled in pieces:
            for p in ([data[:2]] if _kind == "circle" else data):
                bounds = bounds.united(QRectF(at(*p), QSizeF(1, 1)))
        reach += 9 * max(width, 1.0) * scale if pieces else 0.0
        with self._as_one(painter, bounds.adjusted(-reach, -reach, reach, reach),
                          painter.opacity() * self._solidity(mark)) as layer:
            layer.setRenderHint(QPainter.Antialiasing, True)
            if kind == markup.POLYGON and fill is not None:
                layer.fillPath(path, QColor.fromRgbF(*fill[:3]))
            pen = self._line_pen(colour, width, scale, style)
            if not no_line:
                layer.setPen(pen)
                layer.setBrush(Qt.NoBrush)
                layer.drawPath(path)
            for piece_kind, data, filled in pieces:
                end = QPainterPath()
                if piece_kind == "circle":
                    cx, cy, r = data
                    end.addEllipse(at(cx, cy), r * scale, r * scale)
                else:
                    end.moveTo(at(*data[0]))
                    for point in data[1:]:
                        end.lineTo(at(*point))
                    if piece_kind == "closed":
                        end.closeSubpath()
                if filled and fill is not None:
                    layer.fillPath(end, QColor.fromRgbF(*fill[:3]))
                if width > 0 or not filled:
                    layer.setPen(pen)
                    layer.setBrush(Qt.NoBrush)
                    layer.drawPath(end)

    def _poly_hit(self, index: int, mark, point: QPointF) -> bool:
        """Whether a viewport point takes hold of a polygon or a polyline:
        within the ink tolerance of its line or a polyline's ends -- a
        cloud's line being the band its scallops cross -- or anywhere inside
        a polygon that is filled or draws nothing."""
        found = self._poly_on_screen(index, mark)
        if found is None:
            return False
        points, at, scale = found
        kind = (mark.kind if isinstance(mark, markup.Annotation)
                else mark.subtype)
        style = markup.BORDER_STYLES.get(mark.border_style, {})
        width = float(style.get("width", mark.thickness) or 0.0)
        reach = width * scale / 2.0 + self.INK_TOLERANCE
        if "cloud" in style and kind == markup.POLYGON:
            reach += 2 * markup.cloud_radius(style["cloud"], width) * scale
        if kind == markup.POLYGON:
            corners = [at(*c) for c in markup.polygon_corners(points)]
            if len(corners) < 2:
                return False
            if (getattr(mark, "fill", None) is not None or width <= 0) and \
                    QPolygonF(corners).containsPoint(point, Qt.OddEvenFill):
                return True
            corners.append(corners[0])
        else:
            corners = [at(x, y) for x, y in zip(points[0::2], points[1::2])]

        def near(a, b) -> bool:
            dx, dy = b.x() - a.x(), b.y() - a.y()
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, (
                (point.x() - a.x()) * dx + (point.y() - a.y()) * dy) / span))
            return math.hypot(point.x() - (a.x() + t * dx),
                              point.y() - (a.y() + t * dy)) <= reach

        if any(near(a, b) for a, b in zip(corners, corners[1:])):
            return True
        if kind == markup.POLYLINE:
            _path, pieces = self._poly_path(mark, points, at)
            for piece_kind, data, _filled in pieces:
                if piece_kind == "circle":
                    cx, cy, r = data
                    if math.hypot(point.x() - at(cx, cy).x(),
                                  point.y() - at(cx, cy).y()) <= r * scale + reach:
                        return True
                    continue
                spots = [at(*p) for p in data]
                if piece_kind == "closed" and QPolygonF(spots).containsPoint(
                        point, Qt.OddEvenFill):
                    return True
                if any(near(a, b) for a, b in zip(spots, spots[1:])):
                    return True
        return False

    def _ink_press(self, position: QPointF) -> bool:
        """Start a stroke of the Pencil being drawn, or of a new one; a
        press on another page finishes the one under way first. False off
        every page."""
        page = self.page_at(position)
        if page is None:
            return False
        if self._ink_drawing is not None and self._ink_drawing["page"] != page:
            self.finish_ink()
        if self._ink_drawing is None:
            self._ink_drawing = {"page": page, "strokes": [], "live": False,
                                 "last": None}
        at = self._point_on(page, position, True)
        if at is None:
            return False
        self._ink_drawing["strokes"].append([at])
        self._ink_drawing["live"] = True
        self._ink_drawing["last"] = position
        self._ink_cursor()
        self.viewport().update()
        self.drawing_changed.emit()
        return True

    #: The pencil the pointer becomes while a Pencil is under way, made on
    #: first use: a cursor needs the application up.
    _pencil = None

    def _ink_cursor(self) -> None:
        """The crosshair for a drawing tool, but **a pencil while a Pencil
        is under way**: the next stroke joins the mark being drawn, which
        Return leaves no other sign of, since the tool stays armed for the
        next one."""
        if not self.marks_area():
            return
        if self._tool != self.DRAW or self._ink_drawing is None:
            self.viewport().setCursor(Qt.CrossCursor)
            return
        if PageCanvas._pencil is None:
            from .toolstrip import icon_for

            size, ratio = 24, 2.0
            image = QPixmap(int(size * ratio), int(size * ratio))
            image.setDevicePixelRatio(ratio)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            # Dark with a light rim, to be seen on paper and on ink alike.
            rim = icon_for("pencil", QColor("white")).pixmap(size - 2)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawPixmap(1 + dx, 1 + dy, rim)
            painter.drawPixmap(1, 1, icon_for("pencil", QColor(30, 30, 30)).pixmap(size - 2))
            painter.end()
            # The tip, at the glyph's bottom left: measured on the glyph.
            PageCanvas._pencil = QCursor(image, 5, 18)
        self.viewport().setCursor(PageCanvas._pencil)

    def _ink_add(self, position: QPointF) -> None:
        """The pointer's next point on the stroke under way, once it has
        moved a pixel."""
        drawing = self._ink_drawing
        last = drawing["last"]
        if last is not None and (position - last).manhattanLength() < 1.0:
            return
        at = self._point_on(drawing["page"], position, True)
        if at is None:
            return
        drawing["strokes"][-1].append(at)
        drawing["last"] = position
        self.viewport().update()

    def _ink_made(self):
        """The Pencil under way as ``(page, points, counts)``: every point
        in one flat run and how many each stroke has, or None."""
        drawing = self._ink_drawing
        if drawing is None or not drawing["strokes"]:
            return None
        points, counts = [], []
        for stroke in drawing["strokes"]:
            for x, y in stroke:
                points += [float(x), float(y)]
            counts.append(len(stroke))
        return drawing["page"], tuple(points), tuple(counts)

    def finish_ink(self) -> None:
        """Keep the Pencil being drawn, with its strokes so far -- Complete,
        Return, another tool, or a press on another page."""
        made = self._ink_made()
        was = self._ink_drawing is not None
        self._ink_drawing = None
        self.viewport().update()
        if was:
            self._ink_cursor()
            self.drawing_changed.emit()
        if made is not None:
            page, points, counts = made
            self.mark_drawn.emit(self.DRAW, page, [points, counts])

    def cancel_ink(self) -> None:
        """Throw away the Pencil being drawn -- Cancel or Escape."""
        self._ink_drawing = None
        self._ink_cursor()
        self.viewport().update()
        self.drawing_changed.emit()

    def can_take_back(self) -> bool:
        """Whether a Pencil or a polygon being made has a stroke or a point
        to take back."""
        if self._ink_drawing is not None:
            return bool(self._ink_drawing["strokes"])
        return self._poly_drawing is not None

    def take_back(self) -> bool:
        """Remove the last stroke of the Pencil being drawn, or the last
        point of the polygon -- the menu's entry, and Undo while one is
        being made, which would otherwise take back whatever was done
        before it was begun. **The last one taken back ends it**, so Undo
        reaches what came before only once nothing is being made. False
        when there is nothing to take back."""
        if not self.can_take_back():
            return False
        if self._ink_drawing is not None:
            self._ink_drawing["strokes"].pop()
            self._ink_drawing["live"] = False
            if not self._ink_drawing["strokes"]:
                self._ink_drawing = None
                self._ink_cursor()
        else:
            page, points, pointer = self._poly_drawing
            points.pop()
            self._poly_drawing = (page, points, pointer) if points else None
        self.viewport().update()
        self.drawing_changed.emit()
        return True

    def _paint_ink_drawing(self, painter) -> None:
        """The Pencil being drawn, as it will be made: in the tool's colour,
        thickness and opacity, its strokes fitted as they are drawn."""
        made = self._ink_made()
        if made is None:
            return
        page, points, counts = made
        colour = self.mark_colour(self.DRAW) if self.mark_colour else None
        thickness, opacity = (self.mark_stroke(self.DRAW) if self.mark_stroke
                              else (1.0, 1.0))
        pencil = markup.Annotation(
            markup.INK, 0, markup.ink_rect(points, counts, thickness),
            colour=colour or markup.swatch("Red"), thickness=thickness,
            opacity=opacity, points=points, strokes=counts)
        self._paint_ink(painter, page, pencil, None)

    def _ink_grips(self, index: int, mark, offset=None):
        """A handle on each corner of a Pencil's box: top left, top right,
        bottom right, bottom left."""
        where = self.note_icon_rect(index, mark, offset)
        if where is None:
            return []
        size = float(self.GRIP)
        return [QRectF(p.x() - size / 2, p.y() - size / 2, size, size)
                for p in (where.topLeft(), where.topRight(),
                          where.bottomRight(), where.bottomLeft())]

    def _ink_resize_from(self, grip: int) -> bool:
        """Take hold of a Pencil's corner: the opposite corner of what it
        draws -- its box less the line's width -- holds still."""
        page, mark = self._selected
        grips = self.grips()
        if not 0 <= grip < 4 or len(grips) < 4 or not getattr(mark, "points", None):
            return False
        mine = isinstance(mark, markup.Annotation)
        held = self._point_on(page, grips[grip].center(), mine)
        fixed = self._point_on(page, grips[(grip + 2) % 4].center(), mine)
        if held is None or fixed is None:
            return False
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        way = (1.0 if held[0] >= fixed[0] else -1.0,
               1.0 if held[1] >= fixed[1] else -1.0)
        inner = (fixed[0] + width * way[0], fixed[1] + width * way[1])
        self._ink_resizing = (page, mark, grip, (inner, way))
        self._poly_shaping = (mark, tuple(mark.points))
        return True

    def _ink_resized(self, position: QPointF) -> None:
        """A Pencil's corner dragged: **every point scaled about the
        opposite corner by the same amount across and up**, so it keeps its
        proportions, by whichever way the pointer has moved further in
        proportion to the side; the line's width does not change."""
        page, mark, _which, (inner, way) = self._ink_resizing
        mine = isinstance(mark, markup.Annotation)
        at = self._point_on(page, position, mine)
        if at is None:
            return
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        points = mark.points
        xs, ys = points[0::2], points[1::2]
        rect = mark.rect
        wide = max(rect[2] - rect[0] - 2 * width, 0.0)
        tall = max(rect[3] - rect[1] - 2 * width, 0.0)
        if wide < 1e-6 and tall < 1e-6:
            return
        reach = ((at[0] - width * way[0] - inner[0]) * way[0],
                 (at[1] - width * way[1] - inner[1]) * way[1])
        # By the way the pointer has moved further, in proportion to the
        # side, as a Stamp's corner: the larger of the two scales grew a mark
        # dragged mostly inwards and a little outwards.
        scales = [r / span for r, span in zip(reach, (wide, tall)) if span >= 1e-6]
        smallest = 4.0 / max(wide, tall)
        scale = max(max(scales, key=lambda v: abs(v - 1.0)), smallest)
        scaled = []
        for x, y in zip(xs, ys):
            scaled += [inner[0] + (x - inner[0]) * scale,
                       inner[1] + (y - inner[1]) * scale]
        self._poly_shaping = (mark, tuple(scaled))
        # And its box with it, so the outline and the handles follow.
        counts = getattr(mark, "strokes", None) or (len(scaled) // 2,)
        self._shaping = (mark, markup.ink_rect(scaled, counts, width), 0.0)
        self._place_mark_buttons()
        self.viewport().update()

    def _ink_path(self, index: int, mark, offset=None):
        """``(curves, dots, scale)`` for a Pencil on screen: its strokes as
        the curves fitted to their points, and its clicks as the dots they
        fill, apart -- or None."""
        points = self._poly_points(mark)
        counts = getattr(mark, "strokes", None) or (
            (len(points) // 2,) if points else ())
        if not points or not counts:
            return None
        rect, _angle = self._shape_of(mark)
        left, bottom, right, top = (float(v) for v in rect)
        where = self.quad_on_screen(index, rect, offset,
                                    scaled=isinstance(mark, markup.Annotation))
        if where is None or right <= left or top <= bottom:
            return None
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        # **A dot is filled to its whole width**: Acrobat's circle of half a
        # point stroked with the line, drawn by Qt -- and by PDFium --
        # leaves a hole wherever the line is wider than the circle.
        radius = markup.INK_DOT + float(getattr(mark, "thickness", 1.0) or 0.0) / 2
        curves, dots = QPainterPath(), QPainterPath()
        dots.setFillRule(Qt.WindingFill)
        for stroke in markup.ink_strokes(points, counts):
            found = markup.ink_curves(stroke)
            if found is None:
                continue
            if found[0] == "dot":
                dots.addEllipse(at(*found[1]), radius * sx, radius * sy)
                continue
            _curves, begin, pieces = found
            curves.moveTo(at(*begin))
            for c in pieces:
                curves.cubicTo(at(c[0], c[1]), at(c[2], c[3]), at(c[4], c[5]))
        return curves, dots, sx

    def _paint_ink(self, painter, index: int, mark, offset) -> None:
        """Draw a Pencil: its strokes in its colour and thickness with
        **round ends and joins**, as Acrobat draws one -- unlike every other
        drawing's flat ones -- and a click as a dot, filled and stroked;
        faded as one piece."""
        found = self._ink_path(index, mark, offset)
        if found is None:
            return
        curves, dots, scale = found
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        colour = QColor.fromRgbF(*(mark.colour or (1.0, 0.0, 0.0))[:3])
        reach = width * scale + 2.0
        bounds = curves.boundingRect().united(dots.boundingRect())
        with self._as_one(painter, bounds.adjusted(-reach, -reach, reach, reach),
                          painter.opacity() * self._solidity(mark)) as layer:
            layer.setRenderHint(QPainter.Antialiasing, True)
            pen = self._line_pen(colour, width, scale, {})
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            layer.setPen(pen)
            layer.setBrush(Qt.NoBrush)
            layer.drawPath(curves)
            layer.fillPath(dots, colour)

    def _ink_hit(self, index: int, mark, point: QPointF) -> bool:
        """Whether a viewport point takes hold of a Pencil: within the ink
        tolerance of what it draws."""
        found = self._ink_path(index, mark)
        if found is None:
            return False
        curves, dots, scale = found
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        stroker = QPainterPathStroker()
        stroker.setWidth(width * scale + 2 * self.INK_TOLERANCE)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        return (stroker.createStroke(curves).contains(point)
                or stroker.createStroke(dots).contains(point)
                or dots.contains(point))

    @staticmethod
    def _line_pen(colour, width: float, scale: float, style: dict) -> QPen:
        """The pen a mark's line is drawn with, at ``scale`` pixels a point.

        **Flat ends and mitred joins**, as PDF draws: Qt's square ends grow
        every dash by half the line at each end, which closed a thick
        dash's gaps altogether. **The thinnest line -- Hairline, written 0
        or 0.01 -- is one device pixel** whatever the zoom, Qt's cosmetic
        pen, with its dash measured in pixels rather than in pen widths."""
        pen = QPen(colour)
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.MiterJoin)
        thin = markup.is_hairline(width) or width * scale < 1.0
        pen.setWidthF(0.0 if thin else width * scale)
        if "dash" in style:
            # Qt measures a dash in pen widths, the file in points.
            pen.setDashPattern([v * scale if thin else v / width
                                for v in style["dash"]])
        return pen

    @contextmanager
    def _as_one(self, painter, bounds: QRectF, opacity: float):
        """A painter to draw one mark on, which puts the mark on the page
        whole at ``opacity`` when it is done.

        **Faded as one piece, as PDF fades it.** A fill and a stroke from one
        path are a single unit in PDF -- the line knocks out the fill under
        it -- and Acrobat shows a mark at its opacity that way. Fading the
        fill and the line one after the other laid the line's inner half
        over the fill, and the two colours stacked into a darker band. So
        the mark is drawn solid into a layer, and the layer is faded once.
        At full opacity there is nothing to stack and no layer is made."""
        if opacity >= 0.999:
            painter.save()
            try:
                yield painter
            finally:
                painter.restore()
            return
        area = bounds.intersected(QRectF(self.viewport().rect()))
        ratio = max(float(painter.device().devicePixelRatioF()), 1.0)
        if area.isEmpty():
            area = QRectF(0, 0, 1, 1)
        image = QImage(max(1, math.ceil(area.width() * ratio)),
                       max(1, math.ceil(area.height() * ratio)),
                       QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.transparent)
        layer = QPainter(image)
        layer.translate(-area.topLeft())
        try:
            yield layer
        finally:
            layer.end()
            painter.save()
            painter.setOpacity(opacity)
            painter.drawImage(area.topLeft(), image)
            painter.restore()

    def _line_hit(self, index: int, mark, point: QPointF) -> bool:
        """Whether a viewport point takes hold of a line: within the ink
        tolerance of the line itself or of one of its ends."""
        found = self._line_on_screen(index, mark)
        if found is None:
            return False
        segment, pieces, at, scale = found
        width = float(getattr(mark, "thickness", 1.0) or 0.0)
        reach = width * scale / 2.0 + self.INK_TOLERANCE

        def near(a, b) -> bool:
            ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, (
                (point.x() - ax) * dx + (point.y() - ay) * dy) / span))
            return math.hypot(point.x() - (ax + t * dx),
                              point.y() - (ay + t * dy)) <= reach

        if near(at(segment[0], segment[1]), at(segment[2], segment[3])):
            return True
        for kind, data, _filled in pieces:
            if kind == "circle":
                cx, cy, r = data
                if math.hypot(point.x() - at(cx, cy).x(),
                              point.y() - at(cx, cy).y()) <= r * scale + reach:
                    return True
                continue
            corners = [at(*p) for p in data]
            if kind == "closed":
                if QPolygonF(corners).containsPoint(point, Qt.OddEvenFill):
                    return True
                corners.append(corners[0])
            if any(near(a, b) for a, b in zip(corners, corners[1:])):
                return True
        return False

    def _paint_replace_caret(self, painter, index: int, mark, colour,
                             offset) -> None:
        """Draw a caret made in this session, Replace's or Insert Text's.

        Acrobat's drawing, `markup.caret_path`, mapped from the caret's box
        on the page to where that box is on screen -- so what is shown is
        what will be written.
        """
        where = self.quad_on_screen(index, mark.rect, offset, scaled=True)
        if where is None or not where.intersects(QRectF(self.viewport().rect())):
            return
        left, bottom, right, top = (float(v) for v in mark.rect)
        if right <= left or top <= bottom:
            return
        sx = where.width() / (right - left)
        sy = where.height() / (top - bottom)

        def at(x, y):
            return QPointF(where.left() + (x - left) * sx,
                           where.bottom() - (y - bottom) * sy)

        path = QPainterPath()
        for op, values in markup.caret_path(mark.rect):
            points = [at(values[n], values[n + 1])
                      for n in range(0, len(values), 2)]
            if op == "m":
                path.moveTo(points[0])
            elif op == "l":
                path.lineTo(points[0])
            else:
                path.cubicTo(*points)
        path.closeSubpath()
        was = painter.opacity()
        painter.setOpacity(self._solidity(mark))
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(path, colour)
        painter.setOpacity(was)

    def _paint_stamp(self, painter, index: int, mark, colour, offset) -> None:
        """Draw a scalable comment: the same glyph, as ink on the page.

        **It scales and it turns**, which is the whole of what separates it
        from the comment mark. So the box comes from the page's own
        arithmetic --
        `quad_on_screen`, the zoom and the resize included -- rather than
        from `note_icon_rect`, which holds a size still.

        The rectangle is the *bounding box of the turned artwork*, so the
        artwork inside it is smaller the further round it goes. Its size is
        recovered the way a viewer recovers it: the box that bounds to this
        one at this angle. Qt turns clockwise where a page turns anti, so
        the angle changes sign on the way in.
        """
        is_mine = isinstance(mark, markup.Annotation)
        rect, angle = self._shape_of(mark)
        where = self.quad_on_screen(index, rect, offset, scaled=is_mine)
        if where is None or not where.intersects(QRectF(self.viewport().rect())):
            return
        # Whatever the mark says, with nothing substituted for it:
        # Text Note's name is the empty string, and a fallback for
        # a falsy icon drew it as the balloon.
        icon = getattr(mark, "icon", "")
        wide, tall = markup.icon_size(icon)
        turned = math.radians(angle)
        across = abs(wide * math.cos(turned)) + abs(tall * math.sin(turned))
        scale = where.width() / across if across else 1.0
        drawn = QRectF(0.0, 0.0, wide * scale, tall * scale)
        drawn.moveCenter(where.center())

        def glyph(target):
            target.save()
            if angle:
                target.translate(where.center())
                target.rotate(-angle)
                target.translate(-where.center())
            if icon == markup.DEFAULT_ICON:
                self._paint_balloon(target, drawn, colour)
            else:
                target.setRenderHint(QPainter.Antialiasing, True)
                for path, fill, stroke, width in self._icon_drawing(
                        icon, drawn, colour):
                    target.setBrush(fill if fill is not None else Qt.NoBrush)
                    if stroke is None:
                        target.setPen(Qt.NoPen)
                    else:
                        pen = QPen(stroke)
                        pen.setWidthF(width)
                        pen.setJoinStyle(Qt.RoundJoin)
                        target.setPen(pen)
                    target.drawPath(path)
            target.restore()

        self._faded(painter, where, self._solidity(mark), glyph)

    def _paint_note(self, painter, index: int, mark, colour) -> None:
        """Draw a sticky note's icon: a balloon, at a size the zoom sets.

        Drawn here even though PDFium draws one of its own, for the reason the
        other marks are: the bitmap on screen is an export made before the
        note existed. Once the file is saved it is PDFium's glyph that shows,
        so this is a balloon rather than a square -- the same thing, so that
        saving does not visibly change the page.
        """
        where = self.note_icon_rect(index, mark)
        if where is None:
            return
        drag = self._dragging_note
        if drag is not None and drag[4] and drag[1] is mark:
            # Shown where the pointer has taken it, not where the file still
            # says it is: the mark is not rewritten until the button comes up,
            # so that letting go outside the page costs nothing.
            where = QRectF(drag[3] - drag[2], where.size())
        if not where.intersects(QRectF(self.viewport().rect())):
            return
        icon = getattr(mark, "icon", markup.DEFAULT_ICON)
        box = where

        def glyph(target):
            target.save()
            target.setRenderHint(QPainter.Antialiasing, True)
            if icon == markup.DEFAULT_ICON:
                self._paint_balloon(target, box, colour)
                target.restore()
                return
            for path, fill, stroke, width in self._icon_drawing(
                    icon, box, colour):
                target.setBrush(fill if fill is not None else Qt.NoBrush)
                if stroke is None:
                    target.setPen(Qt.NoPen)
                else:
                    pen = QPen(stroke)
                    pen.setWidthF(width)
                    pen.setJoinStyle(Qt.RoundJoin)
                    target.setPen(pen)
                target.drawPath(path)
            target.restore()

        self._faded(painter, where, self._solidity(mark), glyph)

    def _paint_balloon(self, painter, where, colour) -> None:
        """A comment's icon: the balloon Reader shows, not the square it writes.

        Measured off Reader rather than drawn to taste. The silhouette is a
        circle of the whole box except its bottom right quadrant, which stays
        square and is what makes the shape a speech bubble; inside it are two
        white bars, the upper longer than the lower, at `markup.BALLOON_BARS`.

        Reader puts one picture in `/AP` -- a square carrying a white bubble --
        and draws this one instead, for this icon alone and no other. Drawing
        what it draws is also why `/Text` is kept out of the page render: a
        comment has to look the same before a save and after one.
        """
        scale = markup.BALLOON_SCALE
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        # Inside the box rather than filling it, which is where Reader puts
        # it. The box stays what is clicked and dragged.
        where = QRectF(where.center().x() - where.width() * scale / 2.0,
                       where.center().y() - where.height() * scale / 2.0,
                       where.width() * scale, where.height() * scale)
        painter.drawPath(self._balloon_path(where))
        painter.setBrush(QColor(255, 255, 255))
        for left, top, wide, tall in markup.BALLOON_BARS:
            painter.drawRect(QRectF(where.x() + left * where.width(),
                                    where.y() + top * where.height(),
                                    wide * where.width(),
                                    tall * where.height()))
        painter.restore()

    @staticmethod
    def _balloon_path(where: QRectF) -> QPainterPath:
        """The balloon's outline: a circle with one corner left square.

        Qt measures an arc anticlockwise from three o'clock, so the sweep runs
        from six round through nine and twelve to three, and the quadrant it
        leaves out is closed by the two straight lines that make the tail.
        """
        path = QPainterPath()
        path.arcMoveTo(where, 270.0)
        path.arcTo(where, 270.0, -270.0)
        path.lineTo(where.right(), where.bottom())
        path.lineTo(where.center().x(), where.bottom())
        path.closeSubpath()
        return path

    def _paint_marking(self, painter) -> None:
        """The rectangle being dragged out, while a markup tool is in use.

        In viewport coordinates and outside the per-page loop, because the
        band belongs to the gesture rather than to the page -- it has to stay
        under the pointer even where that has wandered into a margin.
        """
        if self._tool == self.STAMPS:
            self._paint_stamp_ghost(painter)
            return
        if self._marking is None:
            return
        if self._tool in self.POINT_TOOLS:
            # Nothing is being sized, so nothing is drawn: a band that
            # followed the pointer promised an area this tool would never
            # make anything of.
            return
        start, current = self._marking
        if self._tool in self.LINE_TOOLS or self._tool == self.CALLOUT:
            if self._tool != self.CALLOUT:
                current = self._angled(start, current)
            if (current - start).manhattanLength() < 1:
                return
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(MARKING)
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(start, current)
            painter.restore()
            return
        if self._tool in self.SHAPE_TOOLS:
            current = self._evened(start, current)
        band = QRectF(start, current).normalized()
        if band.width() < 1 and band.height() < 1:
            return
        if self._tool in self.SHAPE_TOOLS:
            # The shape itself, so a circle is seen as a circle while it is
            # drawn rather than as the box it will be drawn in.
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(MARKING)
            pen.setStyle(Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            if self._tool == self.OVAL:
                painter.drawEllipse(band)
            else:
                painter.drawRect(band)
            painter.restore()
            return
        painter.save()
        pen = QPen(MARKING)
        pen.setStyle(Qt.DashLine)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(MARKING_FILL)
        painter.drawRect(band)
        painter.restore()

    def _paint_fields(self, painter, index: int, offset: QPointF, ratio: float):
        """Draw this page's form fields over it.

        The page bitmap has none in it -- PDFium leaves form fields to a part
        of itself QtPdf does not call -- so they are composited here instead,
        from the state the application holds rather than from the file. A tick
        is then a repaint, which is what makes editing possible at all: the
        alternative is rewriting the document for every change, measured at
        682 ms on a large form against 1 ms to change the value.

        The y axis flips again. A page rectangle here runs down from the top
        left; a PDF rectangle runs up from the bottom.
        """
        if self._fields is None or self._appearances is None:
            return
        on_page = self._fields.on_page(index)
        if not on_page:
            return
        height = self._layout.page_height(index)
        if height is None:
            return
        zoom = self._layout.zoom
        focused = self._focused
        for field in on_page:
            if field.hidden:
                continue
            left, bottom, right, top = field.rect
            where = QRectF((left * zoom) + self._layout.page_rect(index).x(),
                           ((height - top) * zoom)
                           + self._layout.page_rect(index).y(),
                           (right - left) * zoom, (top - bottom) * zoom)
            where.translate(-offset)
            if not where.intersects(QRectF(self.viewport().rect())):
                continue
            wide = max(1, round(where.width() * ratio))
            high = max(1, round(where.height() * ratio))
            value = self._value_of(field)
            # A drawing is made rather than looked up when the file has
            # none that fits: because the field has just been typed into, or
            # because it holds a value the file never drew. Most text fields
            # are the second case -- 0 of 164 in one corpus form carried an
            # appearance -- and showing nothing there would be the very fault
            # this work began with.
            if field.kind in ("/Tx", "/Ch") and (
                    self._edited(field) or (value and not field.drawn)):
                image = self._appearances.text_image(
                    field.annot, value or "", self._fields.acroform,
                    self._fields.pdf, wide, high, field.rotation)
            else:
                image = self._appearances.image(
                    field.annot, field.state_for(value), wide, high,
                    field.rotation)
            if image is not None:
                painter.drawImage(where, image)
            if field is focused:
                # Outside the field rather than over it, so the ring does not
                # sit on top of what was typed.
                painter.save()
                pen = QPen(FIELD_FOCUS)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(where.adjusted(-1.5, -1.5, 1.5, 1.5))
                painter.restore()

    def _edited(self, field) -> bool:
        """Whether the application holds a value for this field.

        Distinct from holding an empty one: a field somebody has deliberately
        cleared must draw as empty rather than fall back to what the file
        says.
        """
        return (self.field_values is not None
                and self.field_values(field) is not None)

    def _value_of(self, field):
        """What the field holds now: the edit if there is one, else the file."""
        if self.field_values is not None:
            edited = self.field_values(field)
            if edited is not None:
                return edited
        return field.value

    def _paint_caret(self, painter, offset: QPointF):
        """The insertion point: a blinking vertical bar, as Acrobat draws it.

        Outside the per-page loop because it belongs to one page and the loop
        runs over all the visible ones; drawing it there would put a bar on
        every page on screen.
        """
        if self._caret is None or not self._caret_on:
            return
        rect = self.caret_rect()
        if rect is None:
            return
        painter.fillRect(rect.translated(-offset), self.palette().text().color())


class _TextBoxEditor(NoteEditor):
    """The editor laid over a text box while it is typed into.

    The note window's, which already styles runs and has the *Text Style*
    menu, with what a text box adds: strikethrough, the font, the size and
    alignment, which the text palette sets. It holds the box's words at the
    zoom -- every size times `factor` -- and hands them back in points.
    Escape ends the typing and keeps it, as a click outside the box does.
    """

    finished = Signal()

    STYLES = NoteEditor.STYLES[:3] + (
        (N_("Strikethrough"), "", "strike"),) + NoteEditor.STYLES[3:]

    #: Points to the editor's own sizes, and the box's words as they were
    #: when editing began; set by the canvas.
    factor = 1.0
    content = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.finished.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def typed(self) -> "textbox.Content":
        """What is in the box now, as a box's words."""
        rich, text = textbox.rich_of(self.document(), self.content, self.factor)
        return self.content._replace(rich=rich, text=text)

    def _default(self) -> "textbox.Style":
        c = self.content
        return textbox.Style(c.family, float(c.size), tuple(c.colour))

    def _formats(self):
        """The character formats of the selection, or the one at the cursor
        when nothing is selected."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return [self.currentCharFormat()]
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        found = []
        block = self.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            piece = block.begin()
            while not piece.atEnd():
                fragment = piece.fragment()
                if (fragment.isValid() and fragment.length()
                        and fragment.position() < end
                        and fragment.position() + fragment.length() > start):
                    found.append(fragment.charFormat())
                piece += 1
            block = block.next()
        return found or [self.currentCharFormat()]

    def selection_state(self) -> dict:
        """What the selection has, for the palette: each value, or None
        where the selection mixes them; each style True only when all of
        it has that style; the alignment None when its paragraphs differ."""
        styles = [textbox.style_of(f, self._default(), self.factor)
                  for f in self._formats()]

        def one(values):
            values = set(values)
            return values.pop() if len(values) == 1 else None

        cursor = self.textCursor()
        aligns = set()
        block = self.document().findBlock(cursor.selectionStart())
        last = self.document().findBlock(cursor.selectionEnd())
        while block.isValid():
            aligns.add(textbox.alignment_of(block.blockFormat()))
            if block == last:
                break
            block = block.next()
        return {
            "family": one(s.family for s in styles),
            "size": one(round(s.size, 1) for s in styles),
            "colour": one(tuple(round(v, 3) for v in s.colour) for s in styles),
            "bold": all(s.bold for s in styles),
            "italic": all(s.italic for s in styles),
            "underline": all(s.underline for s in styles),
            "strike": all(s.strike for s in styles),
            "super": all(s.shift == "super" for s in styles),
            "sub": all(s.shift == "sub" for s in styles),
            "align": aligns.pop() if len(aligns) == 1 else None,
        }

    def _is(self, how: str) -> bool:
        """Whether all of what is selected already carries this, so that
        a style is taken off only when every part of it had it."""
        state = self.selection_state()
        return bool(state.get(how, False))

    def _merge(self, fmt: QTextCharFormat) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    def set_family(self, family: str) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([family])
        self._merge(fmt)

    def set_size(self, points: float) -> None:
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(points) * self.factor)
        self._merge(fmt)

    def align(self, how: str) -> None:
        """Align the paragraphs the selection touches."""
        fmt = QTextBlockFormat()
        fmt.setAlignment(textbox.block_format(how).alignment())
        self.textCursor().mergeBlockFormat(fmt)

    def createMimeDataFromSelection(self):
        """What is copied, with its sizes in points rather than at this
        zoom, so it pastes the same size into a box at any zoom."""
        mime = super().createMimeDataFromSelection()
        copy = QTextDocument()
        QTextCursor(copy).insertFragment(self.textCursor().selection())
        cursor = QTextCursor(copy)
        block = copy.begin()
        while block.isValid():
            piece = block.begin()
            while not piece.atEnd():
                fragment = piece.fragment()
                if fragment.isValid() and fragment.charFormat().fontPointSize() > 0:
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(fragment.position() + fragment.length(),
                                       QTextCursor.KeepAnchor)
                    fmt = QTextCharFormat()
                    fmt.setFontPointSize(fragment.charFormat().fontPointSize()
                                         / self.factor)
                    cursor.mergeCharFormat(fmt)
                piece += 1
            block = block.next()
        mime.setHtml(copy.toHtml())
        return mime

    def insertFromMimeData(self, source):
        """Paste what a text box can hold.

        Every style a run can carry comes with it -- colour, size, bold,
        italic, underline, strikethrough, superscript and subscript -- and
        the font, when it is installed and may be embedded; otherwise the
        font at the cursor. Anything else -- capitals, shading, links,
        images, tables -- is left behind, and the words arrive as their
        text.
        """
        if not source.hasHtml():
            super().insertFromMimeData(source)
            return
        from . import fonts

        pasted = QTextDocument()
        pasted.setHtml(source.html())
        here = self.currentCharFormat()
        allowed = fonts.embeddable_families()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        block, first = pasted.begin(), True
        while block.isValid():
            if not block.next().isValid() and not block.text() and not first:
                break       # the empty paragraph a table leaves at the end
            if not first:
                cursor.insertBlock()
            first = False
            piece = block.begin()
            while not piece.atEnd():
                fragment = piece.fragment()
                if fragment.isValid():
                    words = fragment.text().replace("￼", "")
                    if words:
                        cursor.insertText(words, self._kept(
                            fragment.charFormat(), here, allowed))
                piece += 1
            block = block.next()
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _kept(self, given: QTextCharFormat, here: QTextCharFormat,
              allowed) -> QTextCharFormat:
        """A pasted run's format reduced to what a text box can hold, over
        the format at the cursor."""
        fmt = QTextCharFormat(here)
        families = (given.fontFamilies()
                    if given.hasProperty(QTextFormat.Property.FontFamilies) else None)
        if families and families[0] in allowed:
            fmt.setFontFamilies([families[0]])
        points = given.fontPointSize()
        if points <= 0 and given.hasProperty(QTextFormat.Property.FontPixelSize):
            points = given.intProperty(QTextFormat.Property.FontPixelSize) * 0.75
        if points > 0:
            fmt.setFontPointSize(points * self.factor)
        # A link arrives as its words: the blue and the underline are the
        # link's, not the text's.
        link = given.isAnchor()
        if given.hasProperty(QTextFormat.Property.ForegroundBrush) and not link:
            fmt.setForeground(given.foreground())
        fmt.setFontWeight(QFont.Weight.Bold if given.fontWeight() >= QFont.Weight.DemiBold
                          else QFont.Weight.Normal)
        fmt.setFontItalic(given.fontItalic())
        fmt.setFontUnderline(given.fontUnderline() and not link)
        fmt.setFontStrikeOut(given.fontStrikeOut())
        fmt.setVerticalAlignment(given.verticalAlignment())
        return fmt

