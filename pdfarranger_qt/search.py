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

"""Text search across the document.

Upstream used Poppler's ``find_text``; this searches the page's own text layer
through `find.TextSearch`, which is what makes "case sensitive" and "whole
words only" possible -- see that module for why `QPdfSearchModel` cannot do
either.

Search runs against the *edited* document rendered to memory, so a page that has
been cropped, rotated or merged is searched as it will be saved -- not as it sits
in the source file. That does mean the index is rebuilt when the document
changes, which is why ``invalidate()`` exists.

Hit-granular since the find dialog arrived. It still reports which *rows* match,
because selecting pages is what the grid does, but the hits behind those rows
are now addressable individually: the dialog lists them, and one cursor steps
through them in both reading and arranging mode.
"""

from typing import TYPE_CHECKING, List, Optional

from .find import Query, TextSearch

if TYPE_CHECKING:
    # Only the annotation on `rectangles` needs it, and that is a string. Left
    # unimported the name was undefined, which costs nothing until something
    # resolves the annotation -- `typing.get_type_hints`, a documentation
    # generator -- and then raises NameError for a type that was there all along.
    from PySide6.QtCore import QRectF

from .export import get_in_memory_pdf
from .render import MemoryDocument


class SearchIndex:
    """Finds every occurrence of a phrase, and which pages hold them."""

    def __init__(self):
        self._doc: Optional[MemoryDocument] = None
        self._search: Optional[TextSearch] = None
        self.query = Query()

    @property
    def phrase(self) -> str:
        """What is being searched for. Read by the window and the dialog."""
        return self.query.phrase

    def invalidate(self):
        """Drop the index; the next search rebuilds it."""
        if self._search is not None:
            self._search.set_document(None)
        if self._doc is not None:
            self._doc.close()
        self._doc = None
        self._search = None

    def _ensure(self, pages, files) -> bool:
        if self._doc is not None:
            return True
        data = get_in_memory_pdf(list(pages), files)
        doc = MemoryDocument(data)
        if not doc.ok:
            doc.close()
            return False
        self._doc = doc
        self._search = TextSearch()
        self._search.set_document(doc.document)
        return True

    def search(self, query, pages, files) -> List[int]:
        """Return the rows whose page contains a match.

        ``query`` may be a `Query` or, for convenience at a call site that
        wants nothing but a phrase, a plain string.
        """
        if isinstance(query, str):
            query = Query(query)
        self.query = query
        if not query or not self._ensure(pages, files):
            if self._search is not None:
                self._search.set_query(Query())
            return []
        self._search.set_query(query)
        return self._search.pages()

    # -- results -----------------------------------------------------------

    @property
    def matches(self) -> List[int]:
        """Rows that contain at least one hit."""
        return [] if self._search is None else self._search.pages()

    @property
    def error(self) -> Optional[str]:
        return None if self._search is None else self._search.error

    def count(self) -> int:
        """How many individual hits, as against how many pages."""
        return 0 if self._search is None else self._search.count()

    def hits(self):
        return [] if self._search is None else self._search.hits()

    def hit(self, index: int):
        return None if self._search is None else self._search.hit(index)

    def first_at_or_after(self, page: int) -> int:
        return -1 if self._search is None else self._search.first_at_or_after(page)

    def rectangles(self, row: int) -> List["QRectF"]:
        """Where the hits are on one page, in that page's own points.

        The index is built from ``get_in_memory_pdf``, so its pages are the
        *edited* ones: crop, rotation and scale are already applied, and a
        rectangle needs no transforming beyond a scale into thumbnail pixels.
        Verified against rotated and cropped pages, where `pagePointSize`
        matches `Page.width_in_points()` exactly.

        Resolved on demand, and this is the call that makes it worth being lazy
        about: see `find`'s module docstring for the 700 ms it saves.
        """
        if self._search is None or self._doc is None:
            return []
        if not 0 <= row < self._doc.page_count():
            return []
        out: List["QRectF"] = []
        for hit in self._search.hits_on_page(row):
            out.extend(hit.rectangles())
        return out
