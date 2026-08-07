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

from pdfarranger_qt.core import DocumentSet

from support import TEXT_PDF


class TestSearch(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.core import DocumentSet
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

    def test_next_wraps_around(self):
        self.index.search("tests", self.pages, self.files())
        first = self.index.next()
        self.assertEqual(self.index.next(), first, "one match should wrap to itself")

    def test_previous_without_matches_is_none(self):
        self.index.search("zzzz", self.pages, self.files())
        self.assertIsNone(self.index.previous())

    def test_invalidate_allows_a_rebuild(self):
        self.index.search("tests", self.pages, self.files())
        self.index.invalidate()
        self.assertEqual(self.index.search("tests", self.pages, self.files()), [0])
