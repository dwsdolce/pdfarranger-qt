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

"""Text search across the document."""

import unittest

from support import TEXT_PDF

from pdfarranger_qt.core import DocumentSet


class TestSearch(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.search import SearchIndex

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(TEXT_PDF)
        self.index = SearchIndex()

    def tearDown(self):
        self.index.invalidate()
        self.docs.cleanup()

    def files(self):
        return self.docs.files_for_export()

    def test_finds_a_phrase(self):
        """Regression: rowCount() populates asynchronously and reported nothing."""
        matches = self.index.search("tests", self.pages, self.files())
        self.assertEqual(matches, [0])

    def test_missing_phrase_finds_nothing(self):
        self.assertEqual(self.index.search("zzzznotpresent", self.pages, self.files()), [])

    def test_empty_phrase_finds_nothing(self):
        self.assertEqual(self.index.search("", self.pages, self.files()), [])

    def test_hits_are_addressable_one_at_a_time(self):
        """The cursor lives in the window now; the index serves hits by number."""
        self.index.search("tests", self.pages, self.files())
        self.assertGreater(self.index.count(), 0)
        first = self.index.hit(0)
        self.assertIsNotNone(first)
        self.assertEqual(first.page, 0)
        self.assertEqual(first.text().lower(), "tests")

    def test_a_hit_past_the_end_is_none(self):
        self.index.search("tests", self.pages, self.files())
        self.assertIsNone(self.index.hit(self.index.count()))

    def test_no_hits_without_a_match(self):
        self.index.search("zzzznotpresent", self.pages, self.files())
        self.assertEqual(self.index.count(), 0)
        self.assertIsNone(self.index.hit(0))

    def test_first_at_or_after_finds_the_page_to_start_from(self):
        self.index.search("tests", self.pages, self.files())
        self.assertEqual(self.index.first_at_or_after(0), 0)
        self.assertEqual(self.index.first_at_or_after(99), -1,
                         "nothing on or after a page past the end")

    def test_options_reach_the_engine(self):
        """The reason this engine exists: QPdfSearchModel took no options."""
        from pdfarranger_qt.find import Query

        hits = self.index.search(Query("tests", case_sensitive=True),
                                 self.pages, self.files())
        self.assertEqual(hits, [0])
        self.assertEqual(self.index.search(Query("TESTS", case_sensitive=True),
                                           self.pages, self.files()), [],
                         "case-sensitive search should not match the wrong case")
        self.assertEqual(self.index.search(Query("TESTS"), self.pages,
                                           self.files()), [0],
                         "and should match it again when case is ignored")

    def test_invalidate_allows_a_rebuild(self):
        self.index.search("tests", self.pages, self.files())
        self.index.invalidate()
        self.assertEqual(self.index.search("tests", self.pages, self.files()), [0])
