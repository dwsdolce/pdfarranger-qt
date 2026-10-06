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

"""Text search with options, over a document's own text layer.

``QPdfSearchModel`` finds text and takes no options at all -- its only input is
``setSearchString``. Measured against an 84-page manual, it is always
case-insensitive and always a substring match::

    'Taps' -> 44 hits   'taps' -> 44   'TAPS' -> 44     (case never matters)
    'tap'  -> 450 hits                                  (never a whole word)

PDFium underneath does support MATCHCASE and MATCHWHOLEWORD, but Qt exposes
neither, so "case sensitive" and "whole words only" cannot be configuration --
they need a different engine. This is it: the page's own text, the same string
`PageText` hands the selection code, searched with `re`.

Highlighting is unaffected. The two index spaces agree exactly, so a hit found
here resolves to the rectangle Qt would have reported::

    getAllText(7).text() == getSelectionAtIndex(7, 0, ALL).text()   on 84/84 pages
    regex finds "taps" at index 972 -> getSelectionAtIndex(7, 972, 4)
        text 'taps', bounds (90, 342)
    QPdfSearchModel's own hit for the same word -> rects (90, 342)

Rectangles are resolved lazily, and that is the one thing here worth knowing.
Extracting a page's text costs about 1.6 ms, so searching all 84 pages takes
132 ms against QPdfSearchModel's 139 ms -- parity. But turning a character
offset back into a rectangle is a separate PDFium lookup at about 1.5 ms, and
doing that eagerly for every hit of a three-letter word costs 700 ms. So a
`Hit` knows where it is in the text and works out where it is on the page only
when somebody asks, which in practice is the page being painted and the one hit
being scrolled to.
"""

import re
from typing import List, Optional

from PySide6.QtCore import QObject, QRectF, Signal

#: Larger than any page's character count; getSelectionAtIndex clamps. The same
#: trick `PageText` uses, for the same reason.
ALL = 10_000_000

#: How much of the surrounding line to keep either side of a hit, for the
#: results list. Enough to tell two hits apart, short enough to fit a row.
CONTEXT = 40


class Query:
    """What to look for, and how to match it.

    Value-like on purpose: the window compares the query it last ran against
    the one the dialog is asking for, and re-runs only when they differ. A
    keystroke that changes nothing -- typing and deleting a letter -- then
    costs nothing.
    """

    __slots__ = ("phrase", "case_sensitive", "whole_word", "regex")

    def __init__(self, phrase="", case_sensitive=False, whole_word=False,
                 regex=False):
        self.phrase = phrase or ""
        self.case_sensitive = bool(case_sensitive)
        self.whole_word = bool(whole_word)
        self.regex = bool(regex)

    def __bool__(self):
        return bool(self.phrase)

    def __eq__(self, other):
        if not isinstance(other, Query):
            return NotImplemented
        return (self.phrase == other.phrase
                and self.case_sensitive == other.case_sensitive
                and self.whole_word == other.whole_word
                and self.regex == other.regex)

    def __hash__(self):
        return hash((self.phrase, self.case_sensitive, self.whole_word,
                     self.regex))

    def __repr__(self):  # pragma: no cover - debugging aid
        flags = [name for name in ("case_sensitive", "whole_word", "regex")
                 if getattr(self, name)]
        return f"Query({self.phrase!r}{''.join(', ' + f for f in flags)})"

    def compile(self):
        """``(pattern, error)``. Exactly one of the two is None.

        Whole words are bounded with lookarounds rather than ``\\b``, which is
        defined against the *pattern's* neighbouring character and so does the
        wrong thing whenever a phrase starts or ends with punctuation: ``\\b``
        around "(tap" asks for a word boundary before "(" -- true in the middle
        of a word, false after a space -- and matches backwards. The
        lookarounds ask the question that was actually meant, which is whether
        a word character abuts the match.
        """
        if not self.phrase:
            return None, None
        body = self.phrase if self.regex else re.escape(self.phrase)
        if self.whole_word:
            body = r"(?<!\w)(?:" + body + r")(?!\w)"
        try:
            return re.compile(body, 0 if self.case_sensitive else re.IGNORECASE), None
        except re.error as problem:
            # Half-typed patterns are the normal case, not an exception: the
            # counter says so quietly instead of anyone raising.
            return None, str(problem)


class Hit:
    """One match: where it is in the text, and where that is on the page."""

    __slots__ = ("page", "start", "length", "_search", "_rects")

    def __init__(self, search, page: int, start: int, length: int):
        self._search = search
        self.page = page
        self.start = start
        self.length = length
        self._rects: Optional[List[QRectF]] = None

    def rectangles(self) -> List[QRectF]:
        """Where to draw, in the page's own points. Resolved once, then cached.

        Normalised, because a rotated page reports negative widths and nothing
        can draw those.
        """
        if self._rects is None:
            self._rects = self._search.rectangles_for(self.page, self.start,
                                                      self.length)
        return self._rects

    def text(self) -> str:
        """The matched text itself, from the page's text."""
        page_text = self._search.page_text(self.page)
        return page_text[self.start:self.start + self.length]

    def context(self) -> str:
        """The match with its surroundings, as one line, for the results list.

        Line breaks become spaces: a PDF's text layer breaks every display
        line, so the raw string would arrive as three short fragments stacked
        in a table cell.
        """
        page_text = self._search.page_text(self.page)
        begin = max(0, self.start - CONTEXT)
        end = min(len(page_text), self.start + self.length + CONTEXT)
        snippet = page_text[begin:end]
        snippet = " ".join(snippet.split())
        if begin > 0:
            snippet = "…" + snippet
        if end < len(page_text):
            snippet = snippet + "…"
        return snippet

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Hit(page={self.page}, start={self.start}, length={self.length})"


class TextSearch(QObject):
    """Every match for a query, in reading order, over one document.

    Not a QAbstractItemModel. The canvas only ever asks "what is on this page"
    and "which one is current", and a flat list answers both without the model
    plumbing -- and without `QPdfSearchModel`'s asynchronous `rowCount`, which
    reports nothing for the first few hundred milliseconds and is why
    `SearchIndex` counts pages by hand to this day.
    """

    #: The hits changed. The canvas repaints; the dialog re-reads the count.
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document = None
        self._query = Query()
        self._hits: List[Hit] = []
        self._by_page: dict = {}
        self._texts: dict = {}
        self._error: Optional[str] = None

    # -- document ----------------------------------------------------------

    def set_document(self, document):
        """Point at a document, dropping everything known about the last one."""
        self._document = document
        self._texts.clear()
        self._run()

    def document(self):
        return self._document

    def page_count(self) -> int:
        if self._document is None:
            return 0
        try:
            return self._document.pageCount()
        except RuntimeError:  # pragma: no cover - document already deleted
            return 0

    def page_text(self, page: int) -> str:
        """A page's text, in the index space `getSelection` reports.

        The same call `PageText.text` makes, deliberately: sharing the index
        space with the selection code is what lets a hit be turned into a
        selection later without a translation step.
        """
        cached = self._texts.get(page)
        if cached is not None:
            return cached
        text = ""
        if self._document is not None:
            try:
                text = self._document.getSelectionAtIndex(page, 0, ALL).text() or ""
            except Exception:  # pragma: no cover - PDFium can be unhappy
                text = ""
        self._texts[page] = text
        return text

    def rectangles_for(self, page: int, start: int, length: int) -> List[QRectF]:
        """Character range to rectangles. The expensive call; see the module docstring."""
        if self._document is None:
            return []
        try:
            selection = self._document.getSelectionAtIndex(page, start, length)
            return [polygon.boundingRect().normalized()
                    for polygon in selection.bounds()]
        except Exception:  # pragma: no cover - PDFium can be unhappy
            return []

    # -- query -------------------------------------------------------------

    def set_query(self, query: Query):
        self._query = query or Query()
        self._run()

    def query(self) -> Query:
        return self._query

    @property
    def error(self) -> Optional[str]:
        """Why the query matched nothing, when the reason is the query itself."""
        return self._error

    def _run(self):
        self._hits = []
        self._by_page = {}
        pattern, self._error = self._query.compile()
        if pattern is not None:
            for page in range(self.page_count()):
                text = self.page_text(page)
                if not text:
                    continue
                for match in pattern.finditer(text):
                    length = match.end() - match.start()
                    if not length:
                        # A regex can match nothing at all ("x*"), and an
                        # empty highlight is a rectangle of no width at every
                        # character of the page.
                        continue
                    hit = Hit(self, page, match.start(), length)
                    self._by_page.setdefault(page, []).append(hit)
                    self._hits.append(hit)
        self.changed.emit()

    # -- results -----------------------------------------------------------

    def hits(self) -> List[Hit]:
        return self._hits

    def count(self) -> int:
        return len(self._hits)

    def hits_on_page(self, page: int) -> List[Hit]:
        return self._by_page.get(page, [])

    def pages(self) -> List[int]:
        """Which pages contain a hit, in order."""
        return sorted(self._by_page)

    def hit(self, index: int) -> Optional[Hit]:
        if 0 <= index < len(self._hits):
            return self._hits[index]
        return None

    def index_of(self, page: int, start: int) -> int:
        """Which hit sits at this position, or -1.

        How the two engines stay in step. The window searches the edited
        document for the grid and the reader searches its own copy; the hit
        lists agree because the page list does, but they are separately built,
        so a cursor is carried across by *position* rather than by trusting two
        list indices to correspond.
        """
        for index, hit in enumerate(self._hits):
            if hit.page == page and hit.start == start:
                return index
        return -1

    def first_at_or_after(self, page: int) -> int:
        """Index of the first hit on ``page`` or later, else -1.

        What "find from here" means when a search begins while the reader is
        already somewhere in the middle of a document.
        """
        for index, hit in enumerate(self._hits):
            if hit.page >= page:
                return index
        return -1
