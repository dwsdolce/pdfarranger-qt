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

Upstream used Poppler's ``find_text``; QtPdf offers ``QPdfSearchModel``, which
searches a whole document and reports page numbers, so the port is a
replacement rather than a translation.

Search runs against the *edited* document rendered to memory, so a page that has
been cropped, rotated or merged is searched as it will be saved -- not as it sits
in the source file. That does mean the index is rebuilt when the document
changes, which is why ``invalidate()`` exists.
"""

from typing import List, Optional

from PySide6.QtPdf import QPdfSearchModel

from .export import get_in_memory_pdf
from .render import MemoryDocument


class SearchIndex:
    """Finds which pages contain a phrase, and steps through them.

    Deliberately page-granular: this application selects and arranges pages, so
    "which pages mention this" is the useful answer. Highlighting the individual
    hit inside a thumbnail would need the delegate to draw match rectangles, and
    is noted as a future refinement rather than attempted here.
    """

    def __init__(self):
        self._doc: Optional[MemoryDocument] = None
        self._model: Optional[QPdfSearchModel] = None
        self._pages: List[int] = []
        self._cursor = -1
        self.phrase = ""

    def invalidate(self):
        """Drop the index; the next search rebuilds it."""
        if self._doc is not None:
            self._doc.close()
        self._doc = None
        self._model = None
        self._pages = []
        self._cursor = -1

    def _ensure(self, pages, files) -> bool:
        if self._doc is not None:
            return True
        data = get_in_memory_pdf(list(pages), files)
        doc = MemoryDocument(data)
        if not doc.ok:
            doc.close()
            return False
        self._doc = doc
        self._model = QPdfSearchModel()
        self._model.setDocument(doc.document)
        return True

    def search(self, phrase: str, pages, files) -> List[int]:
        """Return the rows whose page contains ``phrase``."""
        self.phrase = phrase
        if not phrase or not self._ensure(pages, files):
            self._pages = []
            self._cursor = -1
            return []
        self._model.setSearchString(phrase)
        # resultsOnPage() computes on demand and answers immediately; the
        # model's own rowCount() fills in asynchronously over a few hundred
        # milliseconds, so reading it here would report no matches at all.
        self._pages = [page for page in range(self._doc.page_count())
                       if self._model.resultsOnPage(page)]
        self._cursor = -1
        return list(self._pages)

    @property
    def matches(self) -> List[int]:
        return list(self._pages)

    def rectangles(self, row: int) -> List["QRectF"]:
        """Where the hits are on one page, in that page's own points.

        The index is built from ``get_in_memory_pdf``, so its pages are the
        *edited* ones: crop, rotation and scale are already applied, and a
        rectangle needs no transforming beyond a scale into thumbnail pixels.
        Verified against rotated and cropped pages, where `pagePointSize`
        matches `Page.width_in_points()` exactly.

        Rotation gives back negative widths and heights, so the rectangles are
        normalised before anyone tries to draw them.
        """
        if self._model is None or self._doc is None:
            return []
        if not 0 <= row < self._doc.page_count():
            return []
        out = []
        for link in self._model.resultsOnPage(row):
            out.extend(rect.normalized() for rect in link.rectangles())
        return out

    def next(self) -> Optional[int]:
        """Row of the next matching page, wrapping around."""
        if not self._pages:
            return None
        self._cursor = (self._cursor + 1) % len(self._pages)
        return self._pages[self._cursor]

    def previous(self) -> Optional[int]:
        if not self._pages:
            return None
        self._cursor = (self._cursor - 1) % len(self._pages)
        return self._pages[self._cursor]
