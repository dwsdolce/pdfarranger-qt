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

import unittest

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF

from pdfarranger_qt.canvas import (
    DEFAULT_MARGIN, DEFAULT_SPACING, PageCanvas, PageLayout, SynchronousPages,
)
from pdfarranger_qt.core import DocumentSet
from pdfarranger_qt.export import get_in_memory_pdf
from pdfarranger_qt.render import MemoryDocument
from support import TEXT_PDF, settle

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

    def test_the_bitmap_cache_is_bounded(self):
        source = SynchronousPages(self.memory.document)
        size = QSize(80, 100)
        for i in range(SynchronousPages.KEEP + 3):
            source.page_image(i % self.memory.page_count(), size)
        self.assertLessEqual(len(source._cache), SynchronousPages.KEEP)

    def test_a_missing_bitmap_is_not_fatal(self):
        source = SynchronousPages(None)
        self.assertIsNone(source.page_image(0, QSize(10, 10)))
