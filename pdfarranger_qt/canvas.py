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

Phase 7 step 1. `QPdfView` exposes neither text selection nor link following
(D16), and both need to turn a point on screen into a point on a page. So does
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
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtPdf import QPdfDocumentRenderOptions
from PySide6.QtWidgets import QAbstractScrollArea, QFrame

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
    """A single column of pages, centred, with a gap between each.

    Sizes are in PDF points and may differ per page -- a book with one landscape
    plate in it is the case that breaks a layout assuming a uniform size, and
    the Handbook has several.

    Offsets are precomputed and searched with ``bisect``: ``pages_in()`` runs on
    every paint and every scroll, and a linear scan over 1590 pages is a cost
    that grows with the document for no reason.
    """

    def __init__(self, sizes: Sequence[QSizeF], zoom: float = 1.0,
                 spacing: float = DEFAULT_SPACING, margin: float = DEFAULT_MARGIN):
        self._sizes = [QSizeF(s) for s in sizes]
        self._spacing = float(spacing)
        self._margin = float(margin)
        self._zoom = 1.0
        self._tops: List[float] = []
        self._height = 0.0
        self._width = 0.0
        self.set_zoom(zoom)

    # -- geometry ----------------------------------------------------------

    def set_zoom(self, zoom: float):
        """Re-lay out at a new scale. Cheap enough to call while dragging."""
        self._zoom = max(0.01, float(zoom))
        gap = self._spacing * self._zoom
        margin = self._margin * self._zoom
        y = margin
        self._tops = []
        widest = 0.0
        for size in self._sizes:
            self._tops.append(y)
            y += size.height() * self._zoom + gap
        for size in self._sizes:
            widest = max(widest, size.width() * self._zoom)
        # The trailing gap is not part of the content; the bottom margin is.
        self._height = (y - gap + margin) if self._sizes else 0.0
        self._width = widest + 2 * margin

    @property
    def zoom(self) -> float:
        return self._zoom

    def margin_px(self) -> float:
        """The margin at the current zoom, which callers need to place a page."""
        return self._margin * self._zoom

    @property
    def page_count(self) -> int:
        return len(self._sizes)

    def content_size(self) -> QSizeF:
        """The whole scrolled column, in document pixels."""
        return QSizeF(self._width, self._height)

    def page_rect(self, index: int) -> QRectF:
        """Where page ``index`` sits in document pixels."""
        size = self._sizes[index]
        w = size.width() * self._zoom
        h = size.height() * self._zoom
        return QRectF((self._width - w) / 2.0, self._tops[index], w, h)

    def pages_in(self, top: float, bottom: float) -> range:
        """Indices whose rectangles intersect the band ``top``..``bottom``.

        A half-open range, empty when nothing intersects. Touching edges do not
        count as intersecting, so a page exactly one pixel above the viewport is
        not rendered.
        """
        if not self._sizes or bottom <= top:
            return range(0, 0)
        # First page whose bottom edge is past `top`.
        first = bisect.bisect_right(self._tops, top)
        first = max(0, first - 1)
        while first < len(self._sizes) and self._bottom(first) <= top:
            first += 1
        # One past the last page whose top edge is before `bottom`.
        last = bisect.bisect_left(self._tops, bottom)
        return range(first, max(first, last))

    def _bottom(self, index: int) -> float:
        return self._tops[index] + self._sizes[index].height() * self._zoom

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
        if not self._sizes:
            raise ValueError("no pages")
        index = bisect.bisect_right(self._tops, y) - 1
        return min(max(index, 0), len(self._sizes) - 1)

    # -- fitting -----------------------------------------------------------

    def zoom_for_width(self, viewport_width: float) -> float:
        """The zoom at which the content is exactly ``viewport_width`` wide.

        The margins scale with the zoom, so they belong *inside* the division:
        subtracting them first and dividing by the page alone overshoots, and
        fit-width then raises the horizontal scroll bar it exists to avoid.
        """
        widest = max((s.width() for s in self._sizes), default=0.0)
        if widest <= 0:
            return 1.0
        return max(0.01, viewport_width / (widest + 2 * self._margin))

    def zoom_for_page(self, viewport: QSizeF, index: int = 0) -> float:
        """The zoom at which one whole page fits, both dimensions.

        Margins inside the division for the same reason as ``zoom_for_width``.
        The vertical margin is counted once above and once below, matching the
        content height for a single page.
        """
        if not self._sizes:
            return 1.0
        size = self._sizes[index]
        if size.width() <= 0 or size.height() <= 0:
            return 1.0
        return max(0.01, min(viewport.width() / (size.width() + 2 * self._margin),
                             viewport.height() / (size.height() + 2 * self._margin)))


def sizes_from_document(document, count: Optional[int] = None) -> List[QSizeF]:
    """Page sizes off a `QPdfDocument`, in points.

    Read once and kept: `pagePointSize` is cheap but not free, and the layout
    consults every size on each zoom change.
    """
    n = document.pageCount() if count is None else count
    return [document.pagePointSize(i) for i in range(n)]


class SynchronousPages:
    """Renders a page on demand, on the calling thread, with a small cache.

    Step 1's bitmap source, and deliberately the simplest thing that works.
    Section 6 settles that the reader needs an asynchronous render with a cache
    of its own -- a quarter of the Handbook's pages miss a 60 Hz frame at 2000 px
    and the worst takes 247 ms -- but that is step 5, and nothing above this line
    should have to change when it arrives. Hence the seam: the canvas asks for a
    bitmap and gets one or None, and never learns which.

    The budget is a number of *pages* at the current width rather than a fixed
    pixel count, per section 6: per-page cost swings two orders of magnitude
    across the zoom range, so a fixed budget holds forty pages at one end and two
    at the other.
    """

    #: Pages to keep. Current, plus a screenful either side.
    KEEP = 5

    def __init__(self, document=None):
        self._document = document
        self._cache = collections.OrderedDict()

    def set_document(self, document):
        self._document = document
        self._cache.clear()

    def clear(self):
        self._cache.clear()

    def page_image(self, index: int, size: QSize) -> Optional[QImage]:
        """A bitmap of ``index`` at ``size``, or None if it cannot be had."""
        if self._document is None or size.width() <= 0 or size.height() <= 0:
            return None
        key = (index, size.width(), size.height())
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            return image
        options = QPdfDocumentRenderOptions()
        options.setScaledSize(size)
        try:
            image = self._document.render(index, size, options)
        except Exception:  # pragma: no cover - PDFium can be unhappy
            return None
        if image.isNull():
            return None
        self._cache[key] = image
        while len(self._cache) > self.KEEP:
            self._cache.popitem(last=False)
        return image


class PageCanvas(QAbstractScrollArea):
    """The reader's page view: a scrolling column that we own.

    Phase 7 step 1. Replaces `QPdfView`, which is a closed widget exposing
    neither selection nor links (D16) and no way to control what it caches. The
    engine underneath is unchanged (D18) -- this is a widget, not a renderer.

    Everything here is a thin layer over `PageLayout`. The widget's job is to
    turn a scroll position into a band of document pixels, ask the layout which
    pages are in it, and paint them; and to convert a point under the mouse into
    document space so the layout can say which page it landed on. Steps 3 and 4
    build links and selection on that second half.
    """

    #: The page occupying most of the viewport changed.
    current_page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = PageLayout([])
        self._pages = SynchronousPages()
        self._current = -1
        self._fit = FitMode.NONE
        self._continuous = True
        self._single = 0
        self._search = None
        self._search_result = -1
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(True)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # -- document ----------------------------------------------------------

    def set_document(self, document):
        """Show ``document``, a QPdfDocument, or None to show nothing."""
        sizes = sizes_from_document(document) if document is not None else []
        self._layout = PageLayout(sizes, zoom=self._layout.zoom)
        self._pages.set_document(document)
        self._current = -1
        self._update_ranges()
        self.viewport().update()
        if sizes:
            self._emit_current()

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

    def zoom_to_width(self):
        """Fit the width, and keep fitting it as the window changes."""
        self.set_zoom(self._layout.zoom_for_width(self.viewport().width()),
                      fit=FitMode.WIDTH)

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
        """Put the top of ``index`` at the top of the viewport, clamped."""
        if not self._layout.page_count:
            return
        index = min(max(index, 0), self._layout.page_count - 1)
        if not self._continuous and index != self._single:
            # Move the window before scrolling into it, or the scrollbar is
            # clamped to the page we are leaving.
            self._single = index
            self._update_ranges()
        top = self._layout.page_rect(index).top() - self._layout.margin_px()
        self.verticalScrollBar().setValue(int(round(top)))
        self._emit_current()

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

    def _scrolled(self, _value):
        self._emit_current()
        self.viewport().update()

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

    # -- search ------------------------------------------------------------

    def set_search_model(self, model):
        """Highlight this model's hits. `QPdfView` drew these for us."""
        if self._search is not None:
            try:
                self._search.dataChanged.disconnect(self._search_changed)
            except (RuntimeError, TypeError):  # already gone, or never connected
                pass
        self._search = model
        if model is not None:
            model.dataChanged.connect(self._search_changed)
        self.viewport().update()

    def _search_changed(self, *_args):
        self.viewport().update()

    def set_current_search_result(self, index: int):
        """Emphasise one hit among the highlights, and scroll it into view."""
        self._search_result = index
        if self._search is None or index < 0:
            self.viewport().update()
            return
        link = self._search.resultAtIndex(index)
        if link is None:
            self.viewport().update()
            return
        rects = link.rectangles()
        if rects:
            self.go_to(link.page(), rects[0].topLeft())
        self.viewport().update()

    def _paint_search(self, painter, index: int, offset: QPointF):
        """Draw this page's hits, the current one picked out.

        Translucent fill rather than an outline, so a hit inside dense text is
        visible without hiding the word it found.
        """
        if self._search is None:
            return
        try:
            links = self._search.resultsOnPage(index)
        except (RuntimeError, AttributeError):  # pragma: no cover - model gone
            return
        if not links:
            return
        current = None
        if self._search_result >= 0:
            found = self._search.resultAtIndex(self._search_result)
            if found is not None and found.page() == index:
                current = [QRectF(r) for r in found.rectangles()]
        for link in links:
            for rect in link.rectangles():
                drawn = self._layout.rect_from_page(index, rect)
                drawn.translate(-offset)
                is_current = current is not None and any(
                    abs(rect.x() - c.x()) < 0.01 and abs(rect.y() - c.y()) < 0.01
                    for c in current)
                painter.fillRect(drawn, SEARCH_CURRENT if is_current else SEARCH_HIT)

    # -- input -------------------------------------------------------------

    def keyPressEvent(self, event):
        """Page keys navigate rather than merely scroll.

        Carried over from the event filter read mode needed around `QPdfView`,
        which is a scroll area and nothing more: PageUp and PageDown moved the
        scrollbar, which did nothing at all when one page filled the view, and
        Home and End were unhandled in both modes. A reader is expected to have
        all four.
        """
        key = event.key()
        if key == Qt.Key_Home:
            self.first_page()
            return
        if key == Qt.Key_End:
            self.last_page()
            return
        if not self._continuous:
            if key in (Qt.Key_PageDown, Qt.Key_Down, Qt.Key_Right, Qt.Key_Space):
                self.next_page()
                return
            if key in (Qt.Key_PageUp, Qt.Key_Up, Qt.Key_Left, Qt.Key_Backspace):
                self.previous_page()
                return
        super().keyPressEvent(event)

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
        for index in self._layout.pages_in(top, bottom):
            rect = self._layout.page_rect(index)
            target = QRectF(rect.topLeft() - offset, rect.size())
            size = QSize(max(1, int(round(rect.width()))),
                         max(1, int(round(rect.height()))))
            # White paper first, always. PDFium renders with an alpha channel
            # and leaves the page itself transparent, so drawing the bitmap
            # straight onto the viewport shows the grey through it and a page
            # never looks like a page. Nothing offscreen catches this: the
            # geometry is right either way, and only the pixels are wrong.
            painter.fillRect(target, Qt.white)
            image = self._pages.page_image(index, size)
            if image is not None:
                painter.drawImage(target, image)
            # Blank paper is also what shows while there is no bitmap yet. Step
            # 5 draws the grid's thumbnail there instead, once there is an
            # asynchronous render worth waiting for.
            self._paint_search(painter, index, offset)
        painter.end()
