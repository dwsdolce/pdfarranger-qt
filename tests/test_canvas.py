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

"""The reader's page geometry (phase 7 step 1).

Pure arithmetic, so these are exact rather than about wiring. The mapping is
what link following, text selection and search highlighting are all built on:
if it is half a page out, every one of them is.
"""

import os
import unittest

from PySide6.QtCore import (
    QEvent, QModelIndex, QPointF, QRectF, QSize, QSizeF, Qt, QUrl,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtPdf import QPdfLinkModel, QPdfSearchModel
from PySide6.QtWidgets import QApplication

from pdfarranger_qt.canvas import (
    DEFAULT_MARGIN, DEFAULT_SPACING, ZOOM_LIMITS, FitMode, PageCanvas, PageLayout,
    AsynchronousPages, PageText,
)
from pdfarranger_qt.core import DocumentSet
from pdfarranger_qt.export import get_in_memory_pdf
from pdfarranger_qt.render import MemoryDocument
from support import HERE, TEXT_PDF, settle

OUTLINE_PDF = os.path.join(HERE, "exporter", "outlines.pdf")
LINK_PDF = os.path.join(HERE, "text_and_link.pdf")

LETTER = QSizeF(612, 792)
A4 = QSizeF(595, 842)
LANDSCAPE = QSizeF(792, 612)


def letters(n):
    return [QSizeF(LETTER) for _ in range(n)]


class TestLayout(unittest.TestCase):

    def test_empty_document_has_no_content(self):
        layout = PageLayout([])
        self.assertEqual(layout.page_count, 0)
        self.assertEqual(layout.content_size().height(), 0)
        self.assertEqual(list(layout.pages_in(0, 1000)), [])

    def test_pages_stack_with_a_gap_between(self):
        layout = PageLayout(letters(3), zoom=1.0)
        first, second = layout.page_rect(0), layout.page_rect(1)
        self.assertEqual(first.top(), DEFAULT_MARGIN)
        self.assertEqual(second.top() - first.bottom(), DEFAULT_SPACING)

    def test_content_height_has_a_margin_at_each_end_and_no_trailing_gap(self):
        layout = PageLayout(letters(3), zoom=1.0)
        expected = (2 * DEFAULT_MARGIN
                    + 3 * LETTER.height()
                    + 2 * DEFAULT_SPACING)
        self.assertAlmostEqual(layout.content_size().height(), expected)

    def test_pages_are_centred_on_the_widest(self):
        layout = PageLayout([LETTER, LANDSCAPE], zoom=1.0)
        narrow, wide = layout.page_rect(0), layout.page_rect(1)
        self.assertAlmostEqual(narrow.center().x(), wide.center().x())
        self.assertGreater(narrow.left(), wide.left())

    def test_zoom_scales_geometry_and_spacing_together(self):
        one = PageLayout(letters(3), zoom=1.0)
        two = PageLayout(letters(3), zoom=2.0)
        self.assertAlmostEqual(two.content_size().height(),
                               one.content_size().height() * 2)
        self.assertAlmostEqual(two.page_rect(2).top(), one.page_rect(2).top() * 2)

    def test_set_zoom_matches_construction(self):
        layout = PageLayout(letters(4), zoom=1.0)
        layout.set_zoom(1.7)
        fresh = PageLayout(letters(4), zoom=1.7)
        for i in range(4):
            self.assertAlmostEqual(layout.page_rect(i).top(), fresh.page_rect(i).top())

    def test_zoom_cannot_reach_zero(self):
        """A zero zoom would divide by zero in every mapping below."""
        layout = PageLayout(letters(2), zoom=0)
        self.assertGreater(layout.zoom, 0)


class TestVisibility(unittest.TestCase):

    def setUp(self):
        self.layout = PageLayout(letters(10), zoom=1.0)

    def test_a_band_over_one_page_finds_only_it(self):
        rect = self.layout.page_rect(3)
        found = list(self.layout.pages_in(rect.top() + 1, rect.bottom() - 1))
        self.assertEqual(found, [3])

    def test_a_band_spanning_a_gap_finds_both_neighbours(self):
        rect = self.layout.page_rect(3)
        found = list(self.layout.pages_in(rect.bottom() - 1, rect.bottom() + DEFAULT_SPACING + 1))
        self.assertEqual(found, [3, 4])

    def test_a_band_inside_a_gap_finds_nothing(self):
        rect = self.layout.page_rect(3)
        found = list(self.layout.pages_in(rect.bottom() + 1, rect.bottom() + DEFAULT_SPACING - 1))
        self.assertEqual(found, [])

    def test_touching_edges_do_not_count(self):
        rect = self.layout.page_rect(3)
        self.assertNotIn(3, self.layout.pages_in(rect.bottom(), rect.bottom() + 5))

    def test_the_whole_document_finds_every_page(self):
        height = self.layout.content_size().height()
        self.assertEqual(list(self.layout.pages_in(0, height)), list(range(10)))

    def test_an_inverted_band_is_empty(self):
        self.assertEqual(list(self.layout.pages_in(500, 100)), [])

    def test_visibility_agrees_with_brute_force(self):
        """bisect is an optimisation; it has to agree with the obvious answer."""
        layout = PageLayout([LETTER, A4, LANDSCAPE, LETTER, A4] * 4, zoom=1.3)
        height = layout.content_size().height()
        for top in range(0, int(height), 37):
            band = (float(top), float(top) + 200)
            fast = list(layout.pages_in(*band))
            slow = [i for i in range(layout.page_count)
                    if layout.page_rect(i).top() < band[1]
                    and layout.page_rect(i).bottom() > band[0]]
            self.assertEqual(fast, slow, f"disagreed over band {band}")


class TestMapping(unittest.TestCase):

    def setUp(self):
        self.layout = PageLayout([LETTER, A4, LANDSCAPE], zoom=1.4)

    def test_a_point_on_a_page_maps_to_that_page(self):
        rect = self.layout.page_rect(1)
        found = self.layout.to_page(rect.center())
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 1)

    def test_a_point_in_a_gap_maps_to_no_page(self):
        rect = self.layout.page_rect(0)
        point = QPointF(rect.center().x(), rect.bottom() + DEFAULT_SPACING / 2)
        self.assertIsNone(self.layout.to_page(point))
        self.assertIsNone(self.layout.page_at(point))

    def test_a_point_beside_a_narrow_page_maps_to_no_page(self):
        """The margin beside a portrait page next to a landscape one."""
        narrow = self.layout.page_rect(0)
        self.assertIsNone(self.layout.page_at(QPointF(narrow.left() - 5, narrow.center().y())))

    def test_page_origin_is_its_top_left(self):
        """PDF puts the origin bottom-left; QtPdf hands out top-left rectangles,
        and matching QtPdf is what stops callers flipping y twice."""
        rect = self.layout.page_rect(2)
        _, point = self.layout.to_page(rect.topLeft() + QPointF(0.5, 0.5))
        self.assertAlmostEqual(point.x(), 0.5 / self.layout.zoom, places=6)
        self.assertAlmostEqual(point.y(), 0.5 / self.layout.zoom, places=6)

    def test_mapping_round_trips(self):
        """The property the whole class exists for."""
        for index in range(self.layout.page_count):
            for px, py in ((0, 0), (10, 20), (300, 500), (100.25, 700.75)):
                page_point = QPointF(px, py)
                doc = self.layout.from_page(index, page_point)
                back = self.layout.point_in_page(index, doc)
                self.assertAlmostEqual(back.x(), px, places=6)
                self.assertAlmostEqual(back.y(), py, places=6)

    def test_round_trip_survives_a_zoom_change(self):
        doc = self.layout.from_page(1, QPointF(120, 340))
        self.layout.set_zoom(0.6)
        moved = self.layout.from_page(1, QPointF(120, 340))
        self.assertNotAlmostEqual(doc.y(), moved.y())
        back = self.layout.point_in_page(1, moved)
        self.assertAlmostEqual(back.x(), 120, places=6)
        self.assertAlmostEqual(back.y(), 340, places=6)

    def test_a_page_rectangle_scales_and_moves(self):
        """What a link rectangle needs before it can be drawn."""
        link = QRectF(72, 144, 100, 20)
        drawn = self.layout.rect_from_page(1, link)
        self.assertAlmostEqual(drawn.width(), 100 * self.layout.zoom)
        self.assertAlmostEqual(drawn.height(), 20 * self.layout.zoom)
        self.assertAlmostEqual(drawn.topLeft().x(),
                               self.layout.from_page(1, link.topLeft()).x())

    def test_nearest_page_always_answers(self):
        layout = PageLayout(letters(5), zoom=1.0)
        self.assertEqual(layout.nearest_page(-1000), 0)
        self.assertEqual(layout.nearest_page(1e9), 4)
        rect = layout.page_rect(2)
        self.assertEqual(layout.nearest_page(rect.center().y()), 2)

    def test_nearest_page_needs_pages(self):
        with self.assertRaises(ValueError):
            PageLayout([]).nearest_page(0)


class TestFitting(unittest.TestCase):

    def test_fit_width_makes_the_content_exactly_the_viewport_width(self):
        """The assertion that matters: no horizontal scroll bar afterwards.

        Written loosely the first time -- with the margin term on both sides,
        where it cancelled -- and it passed while the content came out 1005.6 px
        wide in a 1000 px viewport, because the margins scale with the zoom and
        were being subtracted before the division rather than inside it.
        """
        for viewport in (400.0, 1000.0, 2560.0):
            layout = PageLayout([LETTER, LANDSCAPE], zoom=1.0)
            layout.set_zoom(layout.zoom_for_width(viewport))
            self.assertAlmostEqual(layout.content_size().width(), viewport, places=6)

    def test_fit_page_fits_both_dimensions_including_the_margins(self):
        layout = PageLayout([LETTER], zoom=1.0)
        viewport = QSizeF(500, 400)
        layout.set_zoom(layout.zoom_for_page(viewport))
        content = layout.content_size()
        self.assertLessEqual(content.width(), viewport.width() + 1e-6)
        self.assertLessEqual(content.height(), viewport.height() + 1e-6)
        # And it is the tighter dimension that is snug, not merely smaller.
        self.assertAlmostEqual(max(content.width() / viewport.width(),
                                   content.height() / viewport.height()), 1.0, places=6)

    def test_fit_page_is_limited_by_the_tighter_dimension(self):
        layout = PageLayout([LETTER])
        wide = layout.zoom_for_page(QSizeF(5000, 400))
        tall = layout.zoom_for_page(QSizeF(500, 5000))
        self.assertLess(wide, tall)

    def test_fitting_an_empty_document_is_harmless(self):
        layout = PageLayout([])
        self.assertEqual(layout.zoom_for_width(800), 1.0)
        self.assertEqual(layout.zoom_for_page(QSizeF(800, 600)), 1.0)


class TestPageCanvas(unittest.TestCase):
    """The widget over the geometry: scroll ranges, painting, and hit testing.

    Driven through a real document under the offscreen platform, because the
    bugs worth catching here are about the two coordinate spaces disagreeing,
    which a stubbed layout would hide.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(TEXT_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(600, 500)
        # Shown, because a QAbstractScrollArea does not propagate a resize to
        # its viewport until it is laid out: before this the widget is 600x500
        # while the viewport is still 638x478, and every geometry assertion
        # below would be measuring the wrong rectangle.
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 600)
        self.canvas.set_document(self.memory.document)

    def test_it_takes_the_documents_pages(self):
        self.assertEqual(self.canvas.page_count(), self.memory.page_count())

    def test_scroll_range_covers_the_content_beyond_the_viewport(self):
        content = self.canvas.layout.content_size().height()
        expected = max(0, content - self.canvas.viewport().height())
        self.assertAlmostEqual(self.canvas.verticalScrollBar().maximum(),
                               expected, delta=1)

    def test_an_empty_document_has_no_scroll_range(self):
        self.canvas.set_document(None)
        self.assertEqual(self.canvas.page_count(), 0)
        self.assertEqual(self.canvas.verticalScrollBar().maximum(), 0)

    def test_viewport_and_document_spaces_round_trip(self):
        for point in (QPointF(0, 0), QPointF(123, 45), QPointF(599, 499)):
            back = self.canvas.to_viewport(self.canvas.to_document(point))
            self.assertAlmostEqual(back.x(), point.x(), places=6)
            self.assertAlmostEqual(back.y(), point.y(), places=6)

    def test_round_trip_survives_scrolling(self):
        self.canvas.verticalScrollBar().setValue(
            self.canvas.verticalScrollBar().maximum() // 2)
        point = QPointF(200, 200)
        back = self.canvas.to_viewport(self.canvas.to_document(point))
        self.assertAlmostEqual(back.y(), point.y(), places=6)

    def test_a_narrow_document_is_centred_and_still_maps(self):
        """Centring shifts the origin; forgetting it puts hit tests a margin out."""
        self.canvas.set_zoom(0.2)                       # far narrower than 600
        self.assertLess(self.canvas.layout.content_size().width(), 600)
        rect = self.canvas.layout.page_rect(0)
        middle = self.canvas.to_viewport(rect.center())
        self.assertAlmostEqual(middle.x(), self.canvas.viewport().width() / 2, delta=1)
        self.assertEqual(self.canvas.page_at(middle), 0)

    def test_a_click_on_a_page_finds_it(self):
        rect = self.canvas.layout.page_rect(0)
        found = self.canvas.to_page(self.canvas.to_viewport(rect.center()))
        self.assertIsNotNone(found)
        index, point = found
        self.assertEqual(index, 0)
        size = self.canvas.layout._sizes[0]
        self.assertAlmostEqual(point.x(), size.width() / 2, delta=1)
        self.assertAlmostEqual(point.y(), size.height() / 2, delta=1)

    def test_a_click_in_the_margin_finds_nothing(self):
        self.assertIsNone(self.canvas.to_page(QPointF(1, 1)))

    def test_go_to_page_scrolls_to_it(self):
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.go_to_page(1)
        rect = self.canvas.layout.page_rect(1)
        self.assertAlmostEqual(self.canvas.to_viewport(rect.topLeft()).y(),
                               DEFAULT_MARGIN * self.canvas.zoom(), delta=2)

    def test_go_to_page_clamps(self):
        self.canvas.go_to_page(10_000)
        self.assertLessEqual(self.canvas.verticalScrollBar().value(),
                             self.canvas.verticalScrollBar().maximum())

    def test_current_page_follows_the_scroll(self):
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        seen = []
        self.canvas.current_page_changed.connect(seen.append)
        self.canvas.go_to_page(1)
        self.assertEqual(self.canvas.current_page(), 1)
        self.assertIn(1, seen)

    def test_zoom_keeps_the_anchored_point_still(self):
        """Zooming about a point is the whole reason the mapping is invertible."""
        anchor = QPointF(300, 250)
        before = self.canvas.to_page(anchor)
        self.assertIsNotNone(before)
        self.canvas.set_zoom(self.canvas.zoom() * 2.0, anchor=anchor)
        after = self.canvas.to_page(anchor)
        self.assertIsNotNone(after)
        self.assertEqual(before[0], after[0])
        self.assertAlmostEqual(before[1].x(), after[1].x(), delta=2)
        self.assertAlmostEqual(before[1].y(), after[1].y(), delta=2)

    def test_zoom_to_width_fills_the_viewport(self):
        self.canvas.zoom_to_width()
        self.assertAlmostEqual(self.canvas.layout.content_size().width(),
                               self.canvas.viewport().width(), delta=1)

    def test_painting_does_not_raise(self):
        """Offscreen still executes paintEvent, so this exercises the real path."""
        self.canvas.viewport().repaint()
        self.canvas.go_to_page(self.canvas.page_count() - 1)
        self.canvas.viewport().repaint()

    def test_a_missing_bitmap_is_not_fatal(self):
        source = AsynchronousPages()
        self.addCleanup(source.shutdown)
        self.assertIsNone(source.page_image(0, QSize(10, 10)))


class TestCanvasParity(unittest.TestCase):
    """What QPdfView did for read mode, and now has to be done here.

    These are the regressions the swap could introduce silently: a fit that
    stops fitting after a resize, page keys that only scroll, a mode change that
    loses the reader's place.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(TEXT_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(600, 500)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 600)
        self.canvas.set_document(self.memory.document)

    def resize_to(self, width, height):
        """Resize and wait for the viewport to follow.

        Not `settle(lambda: viewport().width() == width)`: a document means a
        scroll bar, so the viewport is a dozen pixels narrower than the widget
        and that predicate is never true. It waited out its whole timeout
        instead -- eight seconds a call, a sixth of the suite across two tests.
        """
        before = (self.canvas.viewport().width(), self.canvas.viewport().height())
        self.canvas.resize(width, height)
        settle(lambda: (self.canvas.viewport().width(),
                        self.canvas.viewport().height()) != before)

    # -- fit modes ---------------------------------------------------------

    def test_fit_width_survives_a_resize(self):
        """The reason the mode is remembered and not just its result."""
        self.canvas.zoom_to_width()
        self.resize_to(900, 500)
        self.assertAlmostEqual(self.canvas.layout.content_size().width(),
                               self.canvas.viewport().width(), delta=1)

    def test_fit_page_survives_a_resize(self):
        """One *page* fits, not the whole column: content_size() is every page."""
        self.canvas.zoom_to_page()
        self.resize_to(400, 700)
        rect = self.canvas.layout.page_rect(max(0, self.canvas.current_page()))
        margins = 2 * self.canvas.layout.margin_px()
        self.assertLessEqual(rect.width() + margins, self.canvas.viewport().width() + 1)
        self.assertLessEqual(rect.height() + margins, self.canvas.viewport().height() + 1)

    def test_an_explicit_zoom_does_not_re_fit(self):
        """Zooming by hand means the window resizing should not undo it."""
        self.canvas.zoom_to_width()
        self.canvas.set_zoom(1.0)
        self.assertEqual(self.canvas.fit_mode(), FitMode.NONE)
        self.resize_to(900, 500)
        self.assertAlmostEqual(self.canvas.zoom(), 1.0, places=6)

    def test_zoom_is_clamped(self):
        self.canvas.set_zoom(1000)
        self.assertLessEqual(self.canvas.zoom(), ZOOM_LIMITS[1])
        self.canvas.set_zoom(0.0001)
        self.assertGreaterEqual(self.canvas.zoom(), ZOOM_LIMITS[0])

    def test_zoom_in_and_out_are_inverse(self):
        before = self.canvas.zoom()
        self.canvas.zoom_in()
        self.assertGreater(self.canvas.zoom(), before)
        self.canvas.zoom_out()
        self.assertAlmostEqual(self.canvas.zoom(), before, places=6)

    # -- single page -------------------------------------------------------

    def test_single_page_restricts_the_scroll_range_to_one_page(self):
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.set_zoom(1.0)
        continuous_max = self.canvas.verticalScrollBar().maximum()
        self.canvas.set_continuous(False)
        self.assertLess(self.canvas.verticalScrollBar().maximum()
                        - self.canvas.verticalScrollBar().minimum(),
                        continuous_max)

    def test_changing_mode_keeps_the_reader_on_the_same_page(self):
        """QPdfView dropped you at the top of the document on a mode change."""
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.go_to_page(1)
        self.canvas.set_continuous(False)
        self.assertEqual(self.canvas.current_page(), 1)
        self.canvas.set_continuous(True)
        self.assertEqual(self.canvas.current_page(), 1)

    def test_next_and_previous_move_the_window_in_single_page(self):
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.set_continuous(False)
        self.canvas.go_to_page(0)
        self.canvas.next_page()
        self.assertEqual(self.canvas.current_page(), 1)
        self.canvas.previous_page()
        self.assertEqual(self.canvas.current_page(), 0)

    def test_navigation_clamps_at_both_ends(self):
        self.canvas.first_page()
        self.canvas.previous_page()
        self.assertEqual(self.canvas.current_page(), 0)
        self.canvas.last_page()
        self.canvas.next_page()
        self.assertEqual(self.canvas.current_page(), self.canvas.page_count() - 1)

    def test_single_page_paints_only_that_page(self):
        self.canvas.set_continuous(False)
        self.canvas.viewport().repaint()          # must not raise

    # -- keyboard ----------------------------------------------------------

    def _key(self, key):
        QApplication.sendEvent(
            self.canvas, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

    def test_home_and_end_navigate(self):
        self._key(Qt.Key_End)
        self.assertEqual(self.canvas.current_page(), self.canvas.page_count() - 1)
        self._key(Qt.Key_Home)
        self.assertEqual(self.canvas.current_page(), 0)

    def test_page_keys_turn_the_page_when_showing_one(self):
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.set_continuous(False)
        self.canvas.go_to_page(0)
        self._key(Qt.Key_PageDown)
        self.assertEqual(self.canvas.current_page(), 1)
        self._key(Qt.Key_PageUp)
        self.assertEqual(self.canvas.current_page(), 0)

    # -- search ------------------------------------------------------------

    def test_search_highlights_paint_without_a_model(self):
        self.canvas.set_search_model(None)
        self.canvas.viewport().repaint()

    def test_a_search_model_can_be_attached_and_replaced(self):
        first = QPdfSearchModel()
        first.setDocument(self.memory.document)
        self.canvas.set_search_model(first)
        second = QPdfSearchModel()
        second.setDocument(self.memory.document)
        self.canvas.set_search_model(second)      # must disconnect the first
        self.canvas.viewport().repaint()

    def test_search_highlights_are_drawn(self):
        """Painted by us now: QPdfView used to do this and no longer will.

        "tests" rather than a common word because this fixture's only text is
        its own filename -- searching for "the" skipped the test, which meant
        the painting it exists to exercise was never running.
        """
        model = QPdfSearchModel()
        model.setDocument(self.memory.document)
        model.setSearchString("tests")
        settle(lambda: model.rowCount(QModelIndex()) > 0, timeout_ms=5000)
        self.assertGreater(model.rowCount(QModelIndex()), 0,
                           "fixture text changed; pick another phrase")
        self.canvas.set_search_model(model)

        hits = model.resultsOnPage(0)
        self.assertTrue(hits, "the hit should be on page 0")
        self.canvas.set_current_search_result(0)
        self.canvas.viewport().repaint()
        self.assertEqual(self.canvas._search_result, 0)

        # The highlight lands on the page, in document space, where the layout
        # says the hit is -- the mapping and the drawing agreeing is the point.
        rect = hits[0].rectangles()[0]
        drawn = self.canvas.layout.rect_from_page(0, rect)
        self.assertTrue(self.canvas.layout.page_rect(0).intersects(drawn))

    def test_a_current_result_out_of_range_is_harmless(self):
        self.canvas.set_current_search_result(9999)
        self.canvas.viewport().repaint()


class TestCanvasPixels(unittest.TestCase):
    """What the canvas actually draws, not merely where it says pages are.

    Added after a bug no geometry assertion could see: PDFium renders with an
    alpha channel and leaves the paper transparent, so the pages were drawn in
    exactly the right places and the viewport's grey showed straight through
    them. Every existing test passed. Only a pixel does.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(TEXT_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(500, 400)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 500)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)

    def grab(self):
        self.canvas.viewport().repaint()
        return self.canvas.viewport().grab().toImage()

    def on_page(self, index=0):
        """A viewport point that is on the page *and* on screen.

        The page is taller than the viewport, so its centre is below the visible
        band; sampling there reads an out-of-range pixel, which comes back black
        and fails for the wrong reason.
        """
        rect = self.canvas.layout.page_rect(index)
        in_view = QRectF(self.canvas.to_viewport(rect.topLeft()), rect.size())
        visible = in_view.intersected(QRectF(self.canvas.viewport().rect()))
        self.assertFalse(visible.isEmpty(), "no part of the page is on screen")
        return visible.center().toPoint()

    def test_the_page_is_paper_coloured_not_the_background(self):
        """The one that would have caught the transparent-paper bug."""
        shot = self.grab()
        point = self.on_page()
        colour = shot.pixelColor(point)
        self.assertGreater(colour.lightness(), 200,
                           f"page is {colour.name()} at {point}, not paper")

    def test_the_gap_between_pages_is_not_paper(self):
        """The inverse, or a viewport painted entirely white would also pass.

        Scrolled to put the gap on screen rather than skipped when it is not:
        a skipped test here would leave the assertion above unbalanced, which is
        exactly how the transparent paper survived in the first place.
        """
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        rect = self.canvas.layout.page_rect(0)
        gap_y = rect.bottom() + DEFAULT_SPACING * self.canvas.zoom() / 2
        # Put the gap in the middle of the viewport.
        self.canvas.verticalScrollBar().setValue(
            int(round(gap_y - self.canvas.viewport().height() / 2)))
        settle(timeout_ms=200)
        point = self.canvas.to_viewport(QPointF(rect.center().x(), gap_y)).toPoint()
        self.assertTrue(self.canvas.viewport().rect().contains(point),
                        "the gap should now be on screen")
        colour = self.grab().pixelColor(point)
        self.assertLess(colour.lightness(), 200,
                        f"the gap is {colour.name()}; pages are not distinguishable")

    def test_a_page_with_no_bitmap_still_draws_paper(self):
        """The column has to keep its shape while a render is outstanding."""
        point = self.on_page()
        self.canvas._pages.set_document(None)      # every request now misses
        self.assertGreater(self.grab().pixelColor(point).lightness(), 200)


class TestLinks(unittest.TestCase):
    """Following links: the first thing the reader can do that QPdfView could not.

    outlines.pdf is the fixture because its pages carry real internal links -- a
    "Page N" list that jumps -- so the hit testing runs against a document
    rather than a constructed one.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(OUTLINE_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(700, 600)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 700)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)

    def links_on(self, page=0):
        model = QPdfLinkModel()
        model.setDocument(self.memory.document)
        model.setPage(page)
        return [model.index(r, 0).data(QPdfLinkModel.Role.Link.value)
                for r in range(model.rowCount(QModelIndex()))]

    def a_link(self, page=0):
        """The first link on a page, straight from the model."""
        links = self.links_on(page)
        self.assertTrue(links, "fixture has no links")
        return links[0]

    def a_link_elsewhere(self, page=0):
        """A link that actually goes somewhere else.

        The first link on page 0 of this fixture points at page 0, so asking for
        "the first link" and skipping when it does not navigate quietly turned
        three of the tests below into no-ops.
        """
        for link in self.links_on(page):
            if link.page() != page:
                return link
        self.fail("no link on this page goes to another page")

    def test_the_fixture_has_links(self):
        """Guard: if this fails the rest are vacuous."""
        model = QPdfLinkModel()
        model.setDocument(self.memory.document)
        model.setPage(0)
        self.assertGreater(model.rowCount(QModelIndex()), 0)

    def test_a_point_on_a_link_finds_it(self):
        """Hit testing end to end: viewport point, through the layout, to a link."""
        link = self.a_link(0)
        centre = link.rectangles()[0].center()
        viewport_point = self.canvas.to_viewport(
            self.canvas.layout.from_page(0, centre))
        found = self.canvas.link_at(viewport_point)
        self.assertIsNotNone(found, "no link found where the model says one is")
        self.assertEqual(found.page(), link.page())

    def test_a_point_off_any_link_finds_nothing(self):
        rect = self.canvas.layout.page_rect(0)
        # Bottom of the page, well below the link list at the top.
        low = QPointF(rect.center().x(), rect.bottom() - 5)
        self.assertIsNone(self.canvas.link_at(self.canvas.to_viewport(low)))

    def test_a_point_in_the_margin_finds_nothing(self):
        self.assertIsNone(self.canvas.link_at(QPointF(2, 2)))

    def test_following_an_internal_link_navigates(self):
        link = self.a_link_elsewhere(0)
        target = link.page()
        self.assertTrue(self.canvas.follow(link))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), target)

    def test_following_an_external_link_emits_rather_than_opening(self):
        """The widget must not decide what the desktop opens."""
        seen = []
        self.canvas.external_link_activated.connect(seen.append)

        class FakeLink:
            def url(self): return QUrl("https://example.com/x")
            def page(self): return 0
            def location(self): return QPointF(0, 0)
            def isValid(self): return True

        self.assertTrue(self.canvas.follow(FakeLink()))
        self.assertEqual([u.toString() for u in seen], ["https://example.com/x"])

    def test_following_nothing_is_harmless(self):
        self.assertFalse(self.canvas.follow(None))

    def test_a_link_to_a_page_that_is_not_there_is_refused(self):
        class Bogus:
            def url(self): return QUrl()
            def page(self): return 9999
            def location(self): return QPointF(0, 0)
            def isValid(self): return True

        self.assertFalse(self.canvas.follow(Bogus()))

    def test_a_click_on_a_link_follows_it(self):
        """Through the real mouse events, not by calling follow() directly."""
        link = self.a_link_elsewhere(0)
        target = link.page()
        point = self.canvas.to_viewport(
            self.canvas.layout.from_page(0, link.rectangles()[0].center()))
        self.click(point, point)
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), target)

    def test_a_drag_does_not_follow_a_link(self):
        """Step 4 selects text by dragging; it must not fire links off."""
        link = self.a_link_elsewhere(0)
        start = self.canvas.to_viewport(
            self.canvas.layout.from_page(0, link.rectangles()[0].center()))
        far = QPointF(start.x() + 120, start.y() + 90)
        self.click(start, far)
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 0, "a drag followed a link")

    def click(self, press_at, release_at):
        for kind, point, button in (
                (QEvent.MouseButtonPress, press_at, Qt.LeftButton),
                (QEvent.MouseButtonRelease, release_at, Qt.LeftButton)):
            QApplication.sendEvent(self.canvas.viewport(), QMouseEvent(
                kind, point, self.canvas.viewport().mapToGlobal(point.toPoint()),
                button, button, Qt.NoModifier))


class TestExternalLinksAreFound(unittest.TestCase):
    """External links must hit-test, which they did not.

    `QPdfLink.isValid()` requires a page, and an external link has page -1
    because it does not point into this document -- so filtering hits on
    isValid() threw away every http and mailto link while leaving internal ones
    working. The whole suite passed: outlines.pdf's links are all internal, so
    nothing exercised the case.

    text_and_link.pdf therefore has one of each.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(LINK_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(700, 600)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 700)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)

    def links(self):
        model = QPdfLinkModel()
        model.setDocument(self.memory.document)
        model.setPage(0)
        return [model.index(r, 0).data(QPdfLinkModel.Role.Link.value)
                for r in range(model.rowCount(QModelIndex()))]

    def test_the_fixture_has_an_external_link(self):
        """Guard: without one, the test below proves nothing."""
        external = [link for link in self.links() if not link.url().isEmpty()]
        self.assertTrue(external, "fixture has no external link")
        self.assertFalse(external[0].isValid(),
                         "isValid() is now True for an external link; the "
                         "usable_link() comment needs revisiting")

    def test_an_external_link_hit_tests(self):
        for link in self.links():
            if link.url().isEmpty():
                continue
            point = self.canvas.to_viewport(
                self.canvas.layout.from_page(0, link.rectangles()[0].center()))
            found = self.canvas.link_at(point)
            self.assertIsNotNone(
                found, f"external link {link.url().toString()} was not found")
            self.assertEqual(found.url().toString(), link.url().toString())

    def test_usable_link_accepts_both_kinds(self):
        for link in self.links():
            self.assertTrue(PageCanvas.usable_link(link),
                            f"rejected {link.url().toString()!r} page={link.page()}")

    def test_usable_link_rejects_nothing_useful(self):
        self.assertFalse(PageCanvas.usable_link(None))

        class Empty:
            def url(self): return QUrl()
            def page(self): return -1

        self.assertFalse(PageCanvas.usable_link(Empty()))


class TestBadDestinations(unittest.TestCase):
    """Links whose destination QtPdf could not parse.

    It logs "invalid location and/or zoom" and hands back what it managed --
    which for the Handbook's bookmarks is "nan nan nan". NaN compares false
    against everything including zero, so it slips past a check for the default
    (0, 0) and only fails later, inside int(round(...)), which raises ValueError
    and kills the click that got there.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(OUTLINE_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(600, 500)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 600)
        self.canvas.set_document(self.memory.document)

    def link_to(self, x, y, page=1):
        class Link:
            def url(self): return QUrl()
            def page(self): return page
            def location(self): return QPointF(x, y)
            def isValid(self): return True
        return Link()

    def test_a_nan_destination_still_goes_to_the_page(self):
        nan = float("nan")
        self.assertTrue(self.canvas.follow(self.link_to(nan, nan)))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 1)

    def test_one_nan_coordinate_is_enough_to_fall_back(self):
        self.assertTrue(self.canvas.follow(self.link_to(100.0, float("nan"))))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 1)

    def test_an_infinite_destination_falls_back_too(self):
        self.assertTrue(self.canvas.follow(self.link_to(float("inf"), 10.0)))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 1)

    def test_a_real_destination_is_still_used(self):
        """The fallback must not swallow the good case."""
        self.assertTrue(self.canvas.follow(self.link_to(50.0, 300.0)))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 1)

    def test_go_to_survives_a_nan_point(self):
        nan = float("nan")
        self.canvas.go_to(1, QPointF(nan, nan))     # must not raise
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.current_page(), 1)


class TestLinkTooltips(unittest.TestCase):
    """Hovering a link says where it goes.

    Worth more here than in most readers: most of this document's links are
    inferred by PDFium from the text rather than declared by the document, so
    the words under the cursor are not reliably the target.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(LINK_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(700, 600)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 700)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)

    def links(self):
        model = QPdfLinkModel()
        model.setDocument(self.memory.document)
        model.setPage(0)
        return [model.index(r, 0).data(QPdfLinkModel.Role.Link.value)
                for r in range(model.rowCount(QModelIndex()))]

    def hover(self, point):
        QApplication.sendEvent(self.canvas.viewport(), QMouseEvent(
            QEvent.MouseMove, point,
            self.canvas.viewport().mapToGlobal(point.toPoint()),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier))

    def point_on(self, link):
        return self.canvas.to_viewport(
            self.canvas.layout.from_page(0, link.rectangles()[0].center()))

    def test_an_external_link_shows_its_url(self):
        for link in self.links():
            if link.url().isEmpty():
                continue
            self.hover(self.point_on(link))
            self.assertEqual(self.canvas.viewport().toolTip(),
                             link.url().toString())
            return
        self.fail("fixture has no external link")

    def test_an_internal_link_shows_its_page(self):
        for link in self.links():
            if not link.url().isEmpty():
                continue
            self.hover(self.point_on(link))
            tip = self.canvas.viewport().toolTip()
            self.assertIn(str(link.page() + 1), tip,
                          f"tooltip {tip!r} should name the target page")
            return
        self.fail("fixture has no internal link")

    def test_the_cursor_becomes_a_hand_over_a_link(self):
        self.hover(self.point_on(self.links()[0]))
        self.assertEqual(self.canvas.viewport().cursor().shape(),
                         Qt.PointingHandCursor)

    def test_moving_off_a_link_clears_both(self):
        self.hover(self.point_on(self.links()[0]))
        self.assertNotEqual(self.canvas.viewport().toolTip(), "")
        self.hover(QPointF(3, 3))                      # the margin
        self.assertEqual(self.canvas.viewport().toolTip(), "")
        self.assertNotEqual(self.canvas.viewport().cursor().shape(),
                            Qt.PointingHandCursor)

    def test_a_link_going_nowhere_describes_nothing(self):
        class Nowhere:
            def url(self): return QUrl()
            def page(self): return -1
        self.assertEqual(PageCanvas.link_description(Nowhere()), "")
        self.assertEqual(PageCanvas.link_description(None), "")


class TestSelection(unittest.TestCase):
    """Selecting and copying text (phase 7 step 4).

    QPdfView exposed none of this (D16). The awkward part is not the dragging
    but QPdfDocument.getSelection, which wants a glyph under *both* ends: the
    exact box of a line selects it, a generous rectangle around the same line
    selects nothing. Points are snapped onto the nearest run first, so these
    tests mostly probe that the snapping holds where a real drag would land.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(OUTLINE_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(700, 900)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 700)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)
        QApplication.clipboard().clear()

    def text_box(self, page=0):
        return self.memory.document.getSelectionAtIndex(
            page, 0, PageText.ALL).boundingRectangle()

    def viewport_point(self, page, x, y):
        return self.canvas.to_viewport(
            self.canvas.layout.from_page(page, QPointF(x, y)))

    def drag(self, start, end):
        QApplication.sendEvent(self.canvas.viewport(), QMouseEvent(
            QEvent.MouseButtonPress, start,
            self.canvas.viewport().mapToGlobal(start.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        # Two moves: the first crosses the drag threshold, the second selects.
        for point in (QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2), end):
            QApplication.sendEvent(self.canvas.viewport(), QMouseEvent(
                QEvent.MouseMove, point,
                self.canvas.viewport().mapToGlobal(point.toPoint()),
                Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(self.canvas.viewport(), QMouseEvent(
            QEvent.MouseButtonRelease, end,
            self.canvas.viewport().mapToGlobal(end.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    # -- snapping ----------------------------------------------------------

    def test_snapping_rescues_a_point_off_the_text(self):
        """The whole reason PageText exists."""
        text = PageText(self.memory.document)
        box = self.text_box()
        stray = QPointF(box.left() - 30, box.top() - 20)
        snapped = text.snap(0, stray)
        self.assertIsNotNone(snapped)
        self.assertTrue(any(r.contains(snapped) for r in text.runs(0)),
                        "snapped point is still not on any run")

    def test_snapping_leaves_a_point_already_on_text_alone(self):
        text = PageText(self.memory.document)
        inside = text.runs(0)[0].center()
        snapped = text.snap(0, inside)
        self.assertAlmostEqual(snapped.x(), inside.x(), delta=1)
        self.assertAlmostEqual(snapped.y(), inside.y(), delta=1)

    def test_a_page_without_text_snaps_to_nothing(self):
        text = PageText(None)
        self.assertIsNone(text.snap(0, QPointF(10, 10)))
        self.assertEqual(text.runs(0), [])

    def test_runs_are_cached(self):
        text = PageText(self.memory.document)
        self.assertIs(text.runs(0), text.runs(0))

    # -- selecting ---------------------------------------------------------

    def test_a_drag_selects_text(self):
        box = self.text_box()
        self.drag(self.viewport_point(0, box.left() - 20, box.top() - 10),
                  self.viewport_point(0, box.right() + 20, box.center().y()))
        self.assertTrue(self.canvas.has_selection(), "the drag selected nothing")
        self.assertIn("Page", self.canvas.selected_text())

    def test_a_click_does_not_select(self):
        box = self.text_box()
        point = self.viewport_point(0, box.center().x(), box.center().y())
        self.drag(point, point)
        self.assertFalse(self.canvas.has_selection())

    def test_selecting_across_a_page_boundary(self):
        """getSelection is per page; a reader that stops at the break is no use."""
        if self.canvas.page_count() < 2:
            self.skipTest("needs a multi-page fixture")
        self.canvas.set_zoom(0.35)          # two pages visible at once
        settle(timeout_ms=200)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)
        first, second = self.text_box(0), self.text_box(1)
        self.drag(self.viewport_point(0, first.center().x(), first.top() + 2),
                  self.viewport_point(1, second.center().x(), second.bottom() - 2))
        self.assertTrue(self.canvas.has_selection())
        self.assertGreaterEqual(len(self.canvas._selection), 2,
                                "the selection stopped at the page break")

    def test_select_all_takes_the_page(self):
        self.canvas.select_all_on(0)
        self.assertTrue(self.canvas.has_selection())
        self.assertIn("Page 1", self.canvas.selected_text())

    def test_a_new_press_clears_the_previous_selection(self):
        self.canvas.select_all_on(0)
        self.assertTrue(self.canvas.has_selection())
        point = self.viewport_point(0, 5, 5)
        self.drag(point, point)
        self.assertFalse(self.canvas.has_selection())

    def test_escape_clears_the_selection(self):
        self.canvas.select_all_on(0)
        QApplication.sendEvent(self.canvas, QKeyEvent(
            QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertFalse(self.canvas.has_selection())

    # -- copying -----------------------------------------------------------

    def test_copy_puts_the_selection_on_the_clipboard(self):
        self.canvas.select_all_on(0)
        self.assertTrue(self.canvas.copy())
        self.assertIn("Page 1", QApplication.clipboard().text())

    def test_copying_nothing_says_so(self):
        self.assertFalse(self.canvas.copy())
        self.assertEqual(QApplication.clipboard().text(), "")

    def test_ctrl_c_copies(self):
        self.canvas.select_all_on(0)
        QApplication.sendEvent(self.canvas, QKeyEvent(
            QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier))
        self.assertIn("Page 1", QApplication.clipboard().text())

    def test_painting_a_selection_does_not_raise(self):
        self.canvas.select_all_on(0)
        self.canvas.viewport().repaint()


class TestContextMenu(unittest.TestCase):
    """The right-button menu, built from whatever is under the pointer.

    Tested by calling the builder rather than by opening the menu: exec() spins
    a nested event loop and would hang the suite. The actions are the thing
    worth asserting anyway -- which ones appear, and whether they are enabled.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(LINK_PDF)
        self.memory = MemoryDocument(
            get_in_memory_pdf(list(pages), self.docs.files_for_export()))
        self.addCleanup(self.memory.close)
        self.canvas = PageCanvas()
        self.addCleanup(self.canvas.deleteLater)
        self.addCleanup(self.canvas.shutdown)
        self.canvas.resize(700, 600)
        self.canvas.show()
        settle(lambda: self.canvas.viewport().width() == 700)
        self.canvas.set_document(self.memory.document)
        self.canvas.go_to_page(0)
        settle(timeout_ms=200)
        QApplication.clipboard().clear()

    def menu_at(self, point):
        """Build the menu without showing it.

        build_context_menu() exists precisely so this is possible: exec() spins
        a nested event loop that never returns without a user, so a test that
        opens the menu hangs the suite instead of failing it. Patching exec()
        was the first attempt and it did not take -- it hung for five minutes.
        """
        menu = self.canvas.build_context_menu(point)
        self.addCleanup(menu.deleteLater)
        labels = [a.text() for a in menu.actions() if a.text()]
        return {"labels": labels,
                "actions": {a.text(): a for a in menu.actions() if a.text()}}

    def links(self):
        model = QPdfLinkModel()
        model.setDocument(self.memory.document)
        model.setPage(0)
        return [model.index(r, 0).data(QPdfLinkModel.Role.Link.value)
                for r in range(model.rowCount(QModelIndex()))]

    def point_on(self, link):
        return self.canvas.to_viewport(
            self.canvas.layout.from_page(0, link.rectangles()[0].center()))

    def test_over_a_page_it_offers_copy_and_select_all(self):
        menu = self.menu_at(QPointF(350, 300))
        self.assertIn("Copy", menu["labels"])
        self.assertIn("Select All", menu["labels"])

    def test_copy_is_disabled_with_nothing_selected(self):
        menu = self.menu_at(QPointF(350, 300))
        self.assertFalse(menu["actions"]["Copy"].isEnabled())

    def test_copy_is_enabled_inside_a_selection(self):
        self.canvas.select_all_on(0)
        runs = self.canvas._text.runs(0)
        inside = self.canvas.to_viewport(
            self.canvas.layout.from_page(0, runs[0].center()))
        menu = self.menu_at(inside)
        self.assertTrue(menu["actions"]["Copy"].isEnabled())

    def test_right_clicking_the_page_away_from_the_selection_drops_it(self):
        """Offering to copy a selection somewhere else is worse than no menu."""
        self.canvas.select_all_on(0)
        self.assertTrue(self.canvas.has_selection())
        rect = self.canvas.layout.page_rect(0)
        blank = self.canvas.to_viewport(
            QPointF(rect.center().x(), rect.bottom() - 10))   # on the page, no text
        self.assertIsNotNone(self.canvas.to_page(blank))
        self.menu_at(blank)
        self.assertFalse(self.canvas.has_selection())

    def test_right_clicking_the_margin_keeps_the_selection(self):
        """Off the page is not "somewhere else on the page".

        Right-clicking the grey around a page should still offer to copy what is
        selected; destroying the selection because the pointer left the paper is
        the annoying half of the rule above, without the useful half.
        """
        self.canvas.select_all_on(0)
        self.menu_at(QPointF(3, 3))
        self.assertTrue(self.canvas.has_selection())
        menu = self.menu_at(QPointF(3, 3))
        self.assertTrue(menu["actions"]["Copy"].isEnabled())

    def test_over_an_external_link_it_offers_the_link_commands(self):
        for link in self.links():
            if link.url().isEmpty():
                continue
            menu = self.menu_at(self.point_on(link))
            self.assertIn("Open Link", menu["labels"])
            self.assertIn("Copy Link Address", menu["labels"])
            return
        self.fail("fixture has no external link")

    def test_copy_link_address_puts_the_url_on_the_clipboard(self):
        for link in self.links():
            if link.url().isEmpty():
                continue
            menu = self.menu_at(self.point_on(link))
            menu["actions"]["Copy Link Address"].trigger()
            self.assertEqual(QApplication.clipboard().text(),
                             link.url().toString())
            return
        self.fail("fixture has no external link")

    def test_over_an_internal_link_it_names_the_target(self):
        for link in self.links():
            if not link.url().isEmpty():
                continue
            menu = self.menu_at(self.point_on(link))
            self.assertTrue(any(label.startswith("Go to") for label in menu["labels"]),
                            f"expected a 'Go to ...' entry, got {menu['labels']}")
            return
        self.fail("fixture has no internal link")

    def test_no_link_commands_over_plain_text(self):
        menu = self.menu_at(QPointF(350, 400))
        self.assertNotIn("Open Link", menu["labels"])
        self.assertNotIn("Copy Link Address", menu["labels"])


class TestAsynchronousPages(unittest.TestCase):
    """Rendering off the GUI thread, with placeholders (phase 7 step 5).

    Section 6 measured why this is not optional: a quarter of the Handbook's
    pages miss a 60 Hz frame at 2000 px and the worst takes 247 ms, so painting
    and rendering cannot share a thread. The interface is unchanged from the
    synchronous source step 1 left as a seam -- page_image() answers with what
    it has and asks for what it does not.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        pages = self.docs.add_file(OUTLINE_PDF)
        self.data = get_in_memory_pdf(list(pages), self.docs.files_for_export())
        self.memory = MemoryDocument(self.data)
        self.addCleanup(self.memory.close)
        self.source = AsynchronousPages()
        self.addCleanup(self.source.shutdown)
        self.source.set_document(self.memory.document, self.data)

    def wait_for(self, index, size):
        settle(lambda: self.source._renderer.get(
            (index, size.width(), size.height())) is not None, timeout_ms=5000)

    def test_the_first_ask_does_not_block(self):
        """It returns immediately, with nothing or a stand-in -- never a render."""
        size = QSize(200, 260)
        import time
        start = time.perf_counter()
        self.source.page_image(0, size)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertLess(elapsed, 50, "page_image looks like it rendered inline")

    def test_the_page_arrives_and_is_then_returned(self):
        size = QSize(200, 260)
        self.assertIsNone(self.source.page_image(0, size))
        self.wait_for(0, size)
        image = self.source.page_image(0, size)
        self.assertIsNotNone(image)
        self.assertEqual(image.size(), size)

    def test_it_says_when_a_page_arrives(self):
        seen = []
        self.source.page_ready.connect(seen.append)
        size = QSize(160, 200)
        self.source.page_image(1, size)
        settle(lambda: 1 in seen, timeout_ms=5000)
        self.assertIn(1, seen)

    def test_another_size_of_the_same_page_stands_in(self):
        """The only placeholder available: rendering a quick small one is not.

        Section 6: the Handbook's worst page costs 248 ms at 1000 px and 247 ms
        at 2000 px, because the cost is parsing and image decode rather than
        rasterising. So a cheap low-resolution pass does not exist.
        """
        small = QSize(120, 155)
        self.source.page_image(0, small)
        self.wait_for(0, small)

        big = QSize(400, 515)
        stand_in = self.source.page_image(0, big)
        self.assertIsNotNone(stand_in, "no stand-in offered for a cached page")
        self.assertEqual(stand_in.size(), small, "should be the cached bitmap")

    def test_a_page_never_rendered_has_no_stand_in(self):
        self.assertIsNone(self.source.page_image(3, QSize(200, 260)))

    def test_the_budget_holds_a_screenful_of_pages(self):
        size = QSize(300, 390)
        self.source.prefetch(0, size, 4)
        expected = size.width() * size.height() * AsynchronousPages.KEEP
        self.assertEqual(self.source._renderer.cache.max_pixels, expected)

    def test_the_budget_follows_the_zoom(self):
        """A fixed pixel budget holds forty pages at one zoom and two at another."""
        small, large = QSize(100, 130), QSize(800, 1040)
        self.source.prefetch(0, small, 4)
        at_small = self.source._renderer.cache.max_pixels
        self.source.prefetch(0, large, 4)
        self.assertGreater(self.source._renderer.cache.max_pixels, at_small)

    def test_prefetch_asks_for_the_neighbours(self):
        size = QSize(150, 195)
        self.source.prefetch(1, size, 4)
        for index in (0, 2, 3):
            settle(lambda i=index: self.source._renderer.get(
                (i, size.width(), size.height())) is not None, timeout_ms=5000)
        for index in (0, 2, 3):
            self.assertIsNotNone(
                self.source._renderer.get((index, size.width(), size.height())),
                f"page {index} was not prefetched")

    def test_prefetch_stays_inside_the_document(self):
        self.source.prefetch(0, QSize(150, 195), 4)      # would ask for -1, -2
        settle(timeout_ms=400)                            # must not raise

    def test_clearing_drops_everything(self):
        size = QSize(200, 260)
        self.source.page_image(0, size)
        self.wait_for(0, size)
        self.source.clear()
        self.assertIsNone(self.source._renderer.get((0, size.width(), size.height())))

    def test_a_source_with_no_bytes_renders_nothing(self):
        """Without the bytes the render thread has no document of its own."""
        source = AsynchronousPages()
        self.addCleanup(source.shutdown)
        source.set_document(self.memory.document, None)
        self.assertIsNone(source.page_image(0, QSize(100, 130)))
        settle(timeout_ms=300)
        self.assertIsNone(source._renderer.get((0, 100, 130)))
