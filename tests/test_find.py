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

"""Search options, which QPdfSearchModel could not express at all.

The fixture's only text is its own filename, ``tests/test_raster_image_text.pdf``,
which happens to be an unusually good specimen: "test" occurs twice but never as
a whole word (once followed by "s", once by "_", and the underscore is a word
character), "text" occurs once, and "pdf" occurs once bounded by a dot and the
end of the string. So every option has something to prove here.
"""

import os
import unittest

from PySide6.QtCore import QRectF
from support import HERE, TEXT_PDF

from pdfarranger_qt.find import Query, TextSearch
from pdfarranger_qt.render import MemoryDocument

#: Two lines of text, so context has something to collapse and elide.
LINK_PDF = os.path.join(HERE, "text_and_link.pdf")


class TestQuery(unittest.TestCase):
    """The query compiles to a pattern, or says why it does not."""

    def test_a_plain_phrase_is_a_literal(self):
        pattern, error = Query("a.b").compile()
        self.assertIsNone(error)
        self.assertTrue(pattern.search("a.b"))
        self.assertFalse(pattern.search("axb"),
                         "a literal dot should not match any character")

    def test_a_regex_is_not_escaped(self):
        pattern, error = Query("a.b", regex=True).compile()
        self.assertIsNone(error)
        self.assertTrue(pattern.search("axb"))

    def test_case_is_ignored_by_default(self):
        pattern, _error = Query("abc").compile()
        self.assertTrue(pattern.search("ABC"))

    def test_case_can_be_demanded(self):
        pattern, _error = Query("abc", case_sensitive=True).compile()
        self.assertFalse(pattern.search("ABC"))

    def test_whole_words_use_lookarounds_not_word_boundaries(self):
        r"""``\b`` is defined against the pattern's own first character.

        Wrapping "(tap" in ``\b`` asks for a boundary *before the bracket*,
        which is true in the middle of a word and false after a space -- the
        exact opposite of the question. The lookarounds ask whether a word
        character abuts the match, which is what the checkbox claims.
        """
        pattern, _error = Query("(tap", whole_word=True).compile()
        self.assertTrue(pattern.search("a (tap here"))
        self.assertFalse(pattern.search("a (tapping here"))

    def test_an_empty_phrase_compiles_to_nothing(self):
        pattern, error = Query("").compile()
        self.assertIsNone(pattern)
        self.assertIsNone(error)

    def test_a_broken_pattern_reports_why(self):
        pattern, error = Query("tap(", regex=True).compile()
        self.assertIsNone(pattern)
        self.assertIn("missing )", error.lower())

    def test_a_broken_pattern_is_only_broken_as_a_regex(self):
        pattern, error = Query("tap(").compile()
        self.assertIsNone(error, "as a literal it is just four characters")
        self.assertTrue(pattern.search("tap("))

    def test_queries_compare_by_value(self):
        """The window re-runs only when the query differs; typing and deleting
        a letter must therefore come back equal."""
        self.assertEqual(Query("a"), Query("a"))
        self.assertNotEqual(Query("a"), Query("a", case_sensitive=True))
        self.assertNotEqual(Query("a"), Query("b"))

    def test_a_query_is_falsey_without_a_phrase(self):
        self.assertFalse(Query(""))
        self.assertTrue(Query("a"))


class TestTextSearch(unittest.TestCase):
    def setUp(self):
        with open(TEXT_PDF, "rb") as handle:
            self.memory = MemoryDocument(handle.read())
        self.addCleanup(self.memory.close)
        self.search = TextSearch()
        self.search.set_document(self.memory.document)

    def find(self, phrase, **options):
        self.search.set_query(Query(phrase, **options))
        return self.search.count()

    # -- the options -------------------------------------------------------

    def test_a_substring_matches_anywhere(self):
        self.assertEqual(self.find("test"), 2, "'tests/' and 'test_'")

    def test_whole_words_only_rejects_both_of_them(self):
        self.assertEqual(self.find("test", whole_word=True), 0)

    def test_whole_words_only_keeps_a_real_word(self):
        self.assertEqual(self.find("pdf", whole_word=True), 1,
                         "bounded by a dot and the end of the text")

    def test_an_underscore_is_part_of_a_word(self):
        """Which is why "test_raster" does not contain the whole word "test"."""
        self.assertEqual(self.find("raster", whole_word=True), 0)

    def test_case_insensitive_by_default(self):
        self.assertEqual(self.find("TEXT"), 1)

    def test_case_sensitive_when_asked(self):
        self.assertEqual(self.find("TEXT", case_sensitive=True), 0)
        self.assertEqual(self.find("text", case_sensitive=True), 1)

    def test_a_regex_can_match_alternatives(self):
        self.assertEqual(self.find("te(st|xt)", regex=True), 3,
                         "two 'test' and one 'text'")

    def test_a_regex_can_be_anchored(self):
        self.assertEqual(self.find("^tests", regex=True), 1)
        self.assertEqual(self.find("^raster", regex=True), 0)

    def test_a_broken_regex_finds_nothing_and_says_so(self):
        self.assertEqual(self.find("te(", regex=True), 0)
        self.assertIsNotNone(self.search.error)

    def test_a_good_query_clears_the_error(self):
        self.find("te(", regex=True)
        self.assertIsNotNone(self.search.error)
        self.find("test")
        self.assertIsNone(self.search.error)

    def test_a_regex_matching_nothing_is_not_a_hit_on_every_character(self):
        """``q*`` matches the empty string between every pair of characters.

        Each one would be a rectangle of no width, highlighted the length of
        the page, so zero-length matches are dropped. "q" rather than "x"
        because the fixture's "text" contains an x, which really is one hit.
        """
        self.assertEqual(self.find("q*", regex=True), 0)
        self.assertEqual(self.find("x*", regex=True), 1,
                         "the x of 'text' is a hit of length one")

    def test_an_empty_phrase_finds_nothing(self):
        self.assertEqual(self.find(""), 0)

    # -- the results -------------------------------------------------------

    def test_hits_arrive_in_reading_order(self):
        self.find("te(st|xt)", regex=True)
        starts = [hit.start for hit in self.search.hits()]
        self.assertEqual(starts, sorted(starts))

    def test_a_hit_knows_its_own_text(self):
        self.find("te(st|xt)", regex=True)
        self.assertEqual([hit.text() for hit in self.search.hits()],
                         ["test", "test", "text"])

    def test_a_hit_resolves_to_a_rectangle_on_the_page(self):
        self.find("text")
        rects = self.search.hit(0).rectangles()
        self.assertTrue(rects)
        self.assertIsInstance(rects[0], QRectF)
        self.assertGreater(rects[0].width(), 0)
        self.assertGreater(rects[0].height(), 0)

    def test_rectangles_are_resolved_once(self):
        """The whole reason they are lazy; see the module docstring's 700 ms."""
        self.find("text")
        hit = self.search.hit(0)
        self.assertIs(hit.rectangles(), hit.rectangles())

    def test_rectangles_are_not_resolved_by_searching(self):
        self.find("text")
        self.assertIsNone(self.search.hit(0)._rects,
                          "searching should not touch the expensive call")

    def test_pages_lists_only_pages_with_hits(self):
        self.find("test")
        self.assertEqual(self.search.pages(), [0],
                         "page 1 of this fixture has no text at all")

    def test_a_page_without_text_is_skipped(self):
        self.find("test")
        self.assertEqual(self.search.hits_on_page(1), [])

    def test_index_of_locates_a_hit_by_position(self):
        """How a cursor crosses between the reader's engine and the grid's."""
        self.find("test")
        hit = self.search.hit(1)
        self.assertEqual(self.search.index_of(hit.page, hit.start), 1)

    def test_index_of_a_position_with_no_hit_is_minus_one(self):
        self.find("test")
        self.assertEqual(self.search.index_of(0, 9999), -1)
        self.assertEqual(self.search.index_of(5, 0), -1)

    def test_first_at_or_after_a_page(self):
        self.find("test")
        self.assertEqual(self.search.first_at_or_after(0), 0)
        self.assertEqual(self.search.first_at_or_after(1), -1)

    def test_hit_out_of_range_is_none(self):
        self.find("test")
        self.assertIsNone(self.search.hit(-1))
        self.assertIsNone(self.search.hit(99))

    # -- lifecycle ---------------------------------------------------------

    def test_dropping_the_document_drops_the_hits(self):
        self.find("test")
        self.assertGreater(self.search.count(), 0)
        self.search.set_document(None)
        self.assertEqual(self.search.count(), 0)

    def test_no_document_is_harmless(self):
        empty = TextSearch()
        empty.set_query(Query("anything"))
        self.assertEqual(empty.count(), 0)
        self.assertEqual(empty.page_text(0), "")
        self.assertEqual(empty.rectangles_for(0, 0, 1), [])

    def test_a_change_is_announced(self):
        """The canvas repaints from this, and the dialog re-reads its count."""
        seen = []
        self.search.changed.connect(lambda: seen.append(True))
        self.find("test")
        self.assertTrue(seen)


class TestContext(unittest.TestCase):
    """The surrounding text, which is what makes a results list usable."""

    def setUp(self):
        with open(LINK_PDF, "rb") as handle:
            self.memory = MemoryDocument(handle.read())
        self.addCleanup(self.memory.close)
        self.search = TextSearch()
        self.search.set_document(self.memory.document)

    def test_context_includes_the_match(self):
        self.search.set_query(Query("page"))
        self.assertIn("page", self.search.hit(0).context())

    def test_context_is_one_line(self):
        """The fixture's text spans two lines; a table cell shows one."""
        self.search.set_query(Query("example"))
        context = self.search.hit(0).context()
        self.assertNotIn("\n", context)
        self.assertNotIn("\r", context)

    def test_short_text_is_not_elided(self):
        """This fixture is 42 characters, well inside the context window."""
        self.search.set_query(Query("page 2"))
        self.assertNotIn("…", self.search.hit(0).context())


class TestContextElision(unittest.TestCase):
    """The cut itself, which needs text longer than the window either side.

    No fixture is that long, and one made for it would be a PDF nobody could
    read to check. `Hit` asks its search for the page's text and nothing else,
    so the text is supplied directly.
    """

    class Page:
        def __init__(self, text):
            self.text = text

        def page_text(self, _page):
            return self.text

    def hit(self, text, start, length):
        from pdfarranger_qt.find import Hit

        return Hit(self.Page(text), 0, start, length)

    def test_both_ends_are_marked(self):
        context = self.hit("a" * 100 + "needle" + "b" * 100, 100, 6).context()
        self.assertTrue(context.startswith("…"))
        self.assertTrue(context.endswith("…"))
        self.assertIn("needle", context)

    def test_the_start_of_the_page_is_not_marked(self):
        context = self.hit("needle" + "b" * 100, 0, 6).context()
        self.assertFalse(context.startswith("…"))
        self.assertTrue(context.endswith("…"))

    def test_the_end_of_the_page_is_not_marked(self):
        context = self.hit("a" * 100 + "needle", 100, 6).context()
        self.assertTrue(context.startswith("…"))
        self.assertFalse(context.endswith("…"))
