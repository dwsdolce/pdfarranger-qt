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

"""Find shows *where* on the page, not only which pages (phase 4).

Upstream draws rectangles around the hits (`show_find_results`, "Draw
rectangles around found text"); this port only selected the matching pages
until now, which was the last outstanding parity gap.
"""

import os
import unittest

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from pdfarranger_qt.core import DocumentSet, Sides
from pdfarranger_qt.search import SearchIndex

from support import TEST_PDF, TEXT_PDF, settle


class TestMatchRectangles(unittest.TestCase):
    """Geometry straight out of the search index."""

    def setUp(self):
        self.docs = DocumentSet()
        self.index = SearchIndex()
        self.addCleanup(self.docs.cleanup)
        self.addCleanup(self.index.invalidate)
        self.pages = self.docs.add_file(TEXT_PDF)

    def files(self):
        return self.docs.files_for_export()

    def search(self, phrase="tests"):
        return self.index.search(phrase, self.pages, self.files())

    def test_a_match_has_a_rectangle(self):
        self.assertEqual(self.search(), [0])
        rects = self.index.rectangles(0)
        self.assertTrue(rects)
        self.assertIsInstance(rects[0], QRectF)

    def test_the_rectangle_is_inside_the_page(self):
        self.search()
        page = self.pages[0]
        for rect in self.index.rectangles(0):
            self.assertGreaterEqual(rect.left(), 0)
            self.assertGreaterEqual(rect.top(), 0)
            self.assertLessEqual(rect.right(), page.width_in_points() + 1)
            self.assertLessEqual(rect.bottom(), page.height_in_points() + 1)

    def test_no_rectangles_without_a_match(self):
        self.index.search("zzzznotpresent", self.pages, self.files())
        self.assertEqual(self.index.rectangles(0), [])

    def test_rectangles_for_a_row_that_does_not_exist(self):
        self.search()
        self.assertEqual(self.index.rectangles(99), [])

    def test_rectangles_before_any_search(self):
        self.assertEqual(SearchIndex().rectangles(0), [])

    def test_rotation_moves_the_rectangle_with_the_page(self):
        """The searched document is the *edited* one, so this comes free.

        It is worth a test anyway: it is the assumption the delegate relies on
        to skip transforming the rectangle itself.
        """
        upright = self.search() and self.index.rectangles(0)[0]
        page = self.pages[0]
        wide = page.height_in_points()

        self.index.invalidate()
        page.rotate(90)
        self.assertEqual(self.search(), [0])
        rotated = self.index.rectangles(0)[0]

        self.assertAlmostEqual(page.width_in_points(), wide, places=0)
        # Upright x becomes rotated y, within a point of rounding.
        self.assertAlmostEqual(rotated.top(), upright.left(), delta=2)
        self.assertLessEqual(rotated.right(), page.width_in_points() + 1)

    def test_rectangles_are_normalised(self):
        """Rotation gives Qt back negative widths; nobody can draw those."""
        self.pages[0].rotate(90)
        self.search()
        for rect in self.index.rectangles(0):
            self.assertGreater(rect.width(), 0)
            self.assertGreater(rect.height(), 0)

    def test_cropping_moves_the_rectangle_with_the_page(self):
        self.pages[0].crop = Sides(0.1, 0.0, 0.2, 0.0)
        self.assertEqual(self.search(), [0])
        page = self.pages[0]
        for rect in self.index.rectangles(0):
            self.assertLessEqual(rect.right(), page.width_in_points() + 1)
            self.assertLessEqual(rect.bottom(), page.height_in_points() + 1)


class TestModelCarriesTheMatches(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([TEXT_PDF])
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def matches(self, row=0):
        return self.win.model.data(self.win.model.index(row, 0),
                                   self.win.model.MatchRole)

    def test_a_search_publishes_rectangles(self):
        self.assertIsNone(self.matches())
        self.win._run_search("tests")
        self.assertTrue(self.matches())

    def test_a_fruitless_search_publishes_nothing(self):
        self.win._run_search("zzzznotpresent")
        self.assertFalse(self.matches())

    def test_a_new_search_replaces_the_old_one(self):
        self.win._run_search("tests")
        self.assertTrue(self.matches())
        self.win._run_search("zzzznotpresent")
        self.assertFalse(self.matches())

    def test_an_edit_drops_the_highlights(self):
        """Rows move when pages do; stale boxes would be drawn in the wrong place."""
        self.win._run_search("tests")
        self.assertTrue(self.matches())
        self.win.view.set_selected_rows([0])
        self.win.duplicate_selected()
        settle(timeout_ms=200)
        self.assertFalse(self.matches())

    def test_matches_for_a_row_past_the_end_are_ignored(self):
        self.win.model.set_matches({99: [QRectF(0, 0, 10, 10)]})
        self.assertIsNone(self.matches())


class TestTheDelegateDrawsThem(unittest.TestCase):
    """The point of the exercise: something appears on the thumbnail."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([TEXT_PDF])
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def render(self, row=0):
        index = self.win.model.index(row, 0)
        option = QStyleOptionViewItem()
        rect = self.win.view.visualRect(index)
        option.font = self.win.view.font()
        option.palette = self.win.view.palette()
        option.rect = rect.translated(-rect.topLeft())
        image = QImage(rect.size(), QImage.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        painter = QPainter(image)
        self.win.view.itemDelegate().paint(painter, option, index)
        painter.end()
        return image

    def highlight_pixels(self, image):
        """Count pixels of the highlight's yellow."""
        found = 0
        for y in range(image.height()):
            for x in range(image.width()):
                colour = image.pixelColor(x, y)
                if (colour.red() > 180 and colour.green() > 140
                        and colour.blue() < 140):
                    found += 1
        return found

    def test_nothing_is_drawn_before_a_search(self):
        self.assertEqual(self.highlight_pixels(self.render()), 0)

    def test_the_hit_is_boxed_after_a_search(self):
        before = self.highlight_pixels(self.render())
        self.win._run_search("tests")
        self.assertGreater(self.highlight_pixels(self.render()), before)

    def test_the_box_goes_away_when_the_search_does(self):
        self.win._run_search("tests")
        self.assertGreater(self.highlight_pixels(self.render()), 0)
        self.win._run_search("zzzznotpresent")
        self.assertEqual(self.highlight_pixels(self.render()), 0)

    def test_a_page_with_no_text_is_left_alone(self):
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=400)
        self.win._run_search("tests")
        self.assertEqual(self.highlight_pixels(self.render()), 0)
