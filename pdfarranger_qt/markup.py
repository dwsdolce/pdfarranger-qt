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

"""Marks the user adds to a document, owned by the application until it saves.

The same shape as `forms.FormValues`, for the same reasons (D2): the state
lives in memory, rides the undo stack beside the pages and the outline, and is
written only at export. Nothing is added to a source document, which stays the
immutable copy everything else reads.

**Keyed by page uid, not by index** -- D20's lesson, learned for bookmarks and
exactly as true here. An index is invalidated by every reorder, and an object
reference is invalidated by the next undo, because `UndoManager.snapshot`
rebuilds the page list with `duplicate()`. The uid survives both, and the
Duplicate *command* assigns a fresh one, so copying a page does not silently
copy somebody's notes onto the copy.

**Nothing is pruned when a page goes.** Export writes the marks belonging to
the pages it is writing and ignores the rest, so a note on a deleted page is
skipped without anyone having to tidy up -- and the same rule, unchanged, is
what makes exporting a *selection* leave the unselected pages' notes out.

Coordinates are in the page's own space, the one its `/MediaBox` is in, so a
mark travels with the content under every geometric edit: export turns a page
by `/Rotate` and crops it by rewriting boxes, and an annotation in page space
is carried by both exactly as the annotations already in the file are.
"""

import copy
import datetime
from typing import Dict, List, Optional, Tuple

import pikepdf

#: Every subtype this module can write. Kept explicit so that an unknown kind
#: is a failed assertion here rather than a dictionary a viewer silently drops.
TEXT = "/Text"
HIGHLIGHT = "/Highlight"
STRIKEOUT = "/StrikeOut"

KINDS = (TEXT, HIGHLIGHT, STRIKEOUT)

#: Subtypes whose geometry is a run of text rather than a box, and which say
#: so with `/QuadPoints`. `/Rect` still has to be there and has to contain
#: them: a viewer that does not understand the subtype falls back to it.
QUADDED = (HIGHLIGHT, STRIKEOUT)

#: Bit 3 of `/F`, Print. Without it a mark shows on screen and vanishes from
#: paper, which is not what anybody means by annotating a document.
PRINTABLE = 4


def pdf_date(when: Optional[datetime.datetime] = None) -> str:
    """`D:YYYYMMDDHHmmSS+HH'mm'`, which is what `/M` wants."""
    when = when or datetime.datetime.now().astimezone()
    offset = when.utcoffset() or datetime.timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return (when.strftime("D:%Y%m%d%H%M%S")
            + f"{sign}{minutes // 60:02d}'{minutes % 60:02d}'")


class Annotation:
    """One mark, in the page coordinates of the page it belongs to."""

    __slots__ = ("kind", "page", "rect", "quads", "contents", "colour",
                 "author", "created")

    def __init__(self, kind: str, page: int, rect: Tuple[float, ...],
                 contents: str = "", colour=None, author: Optional[str] = None,
                 created: Optional[str] = None, quads=()):
        if kind not in KINDS:
            raise ValueError(f"unknown annotation kind: {kind}")
        self.kind = kind
        self.page = page
        self.rect = tuple(float(v) for v in rect)
        #: One rectangle per run of text, for the subtypes that mark text.
        #: Empty for the rest. A highlight over three lines is three quads,
        #: not one box round the paragraph -- which would cover the margins
        #: and the lines between.
        self.quads = tuple(tuple(float(v) for v in quad) for quad in quads or ())
        self.contents = contents
        self.colour = tuple(colour) if colour is not None else None
        self.author = author
        self.created = created or pdf_date()

    def duplicate(self) -> "Annotation":
        return copy.copy(self)

    def __eq__(self, other):
        if not isinstance(other, Annotation):
            return NotImplemented
        return all(getattr(self, name) == getattr(other, name)
                   for name in self.__slots__)

    def __repr__(self):  # pragma: no cover - debugging aid
        return (f"Annotation({self.kind!r}, page={self.page}, "
                f"rect={self.rect}, contents={self.contents!r})")


class Annotations:
    """What has been added to the document, by page uid.

    Sparse: a document nobody has marked holds an empty one, which is what
    makes snapshotting it on every undo cost nothing.
    """

    __slots__ = ("_by_page",)

    def __init__(self, by_page: Optional[Dict[int, List[Annotation]]] = None):
        self._by_page: Dict[int, List[Annotation]] = {}
        for uid, marks in (by_page or {}).items():
            if marks:
                self._by_page[uid] = list(marks)

    def duplicate(self) -> "Annotations":
        return Annotations({uid: [m.duplicate() for m in marks]
                            for uid, marks in self._by_page.items()})

    def add(self, annotation: Annotation) -> Annotation:
        self._by_page.setdefault(annotation.page, []).append(annotation)
        return annotation

    def remove(self, annotation: Annotation) -> bool:
        marks = self._by_page.get(annotation.page)
        if not marks or annotation not in marks:
            return False
        marks.remove(annotation)
        if not marks:
            del self._by_page[annotation.page]
        return True

    def for_page(self, uid: int) -> List[Annotation]:
        return list(self._by_page.get(uid, ()))

    def pages(self):
        return self._by_page.keys()

    def clear(self):
        self._by_page.clear()

    def __bool__(self):
        return bool(self._by_page)

    def __len__(self):
        return sum(len(marks) for marks in self._by_page.values())

    def __eq__(self, other):
        if not isinstance(other, Annotations):
            return NotImplemented
        return self._by_page == other._by_page

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Annotations({len(self)} on {len(self._by_page)} page(s))"


def to_dictionary(pdf, annotation: Annotation) -> pikepdf.Dictionary:
    """``annotation`` as a PDF annotation dictionary in ``pdf``.

    Indirect, because a page's ``/Annots`` is an array of references and an
    inline dictionary there is reachable only through that one page -- which
    stops working the moment anything wants to point at the mark.
    """
    entry = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name(annotation.kind),
        Rect=pikepdf.Array([*annotation.rect]),
        Contents=pikepdf.String(annotation.contents),
        F=PRINTABLE,
        M=pikepdf.String(annotation.created),
    )
    if annotation.kind == TEXT:
        # The icon a viewer draws. /Note is the one every viewer has.
        entry[pikepdf.Name.Name] = pikepdf.Name("/Note")
    if annotation.kind in QUADDED:
        entry[pikepdf.Name.QuadPoints] = pikepdf.Array(
            [v for quad in annotation.quads for v in _quad_points(quad)])
        entry[pikepdf.Name.CA] = TRANSPARENCY[annotation.kind]
        entry[pikepdf.Name.AP] = pikepdf.Dictionary(
            N=_appearance(pdf, annotation))
    if annotation.author:
        entry[pikepdf.Name.T] = pikepdf.String(annotation.author)
    if annotation.colour is not None:
        entry[pikepdf.Name.C] = pikepdf.Array([*annotation.colour])
    return pdf.make_indirect(entry)


#: How solid each kind is drawn. A highlight has to be seen through or it
#: hides the words it marks; a line drawn over them does not.
TRANSPARENCY = {HIGHLIGHT: 0.4, STRIKEOUT: 1.0}


def _quad_points(quad) -> "list[float]":
    """One rectangle as the eight numbers `/QuadPoints` wants.

    Upper-left, upper-right, lower-left, lower-right. The specification's own
    wording describes a different order and every implementation ignores it,
    so this follows what readers actually read.
    """
    left, bottom, right, top = quad
    return [left, top, right, top, left, bottom, right, bottom]


def _appearance(pdf, annotation):
    """A drawing for a text mark, so the file does not depend on charity.

    PDFium draws a `/Highlight` from its `/QuadPoints` with no appearance at
    all -- measured, 1600 coloured pixels either way -- and so does Acrobat.
    But a viewer is only *recommended* to generate one, and the markup in the
    corpus that a real producer wrote carries one, so a file written here
    carries one too.

    Multiply, for a highlight, so the text underneath shows through rather
    than being painted over.
    """
    colour = annotation.colour or (1.0, 1.0, 0.0)
    drawing = ["/GS gs", "{} {} {} rg".format(*colour[:3])]
    for quad in annotation.quads:
        left, bottom, right, top = quad
        if annotation.kind == STRIKEOUT:
            # Through the middle, a fifteenth of the line's height thick,
            # which is about what a pen does.
            thickness = max(0.6, (top - bottom) / 15.0)
            middle = (top + bottom) / 2.0
            drawing.append("{} {} {} {} re f".format(
                left, middle - thickness / 2, right - left, thickness))
        else:
            drawing.append("{} {} {} {} re f".format(
                left, bottom, right - left, top - bottom))
    stream = pikepdf.Stream(pdf, "\n".join(drawing).encode())
    stream[pikepdf.Name.Type] = pikepdf.Name.XObject
    stream[pikepdf.Name.Subtype] = pikepdf.Name.Form
    stream[pikepdf.Name.BBox] = pikepdf.Array([*annotation.rect])
    stream[pikepdf.Name.Resources] = pikepdf.Dictionary(
        ExtGState=pikepdf.Dictionary(GS=pikepdf.Dictionary(
            BM=(pikepdf.Name.Multiply if annotation.kind == HIGHLIGHT
                else pikepdf.Name.Normal),
            ca=TRANSPARENCY[annotation.kind])))
    return pdf.make_indirect(stream)


def bounding_rect(quads) -> "tuple":
    """The box that contains every quad, which is what `/Rect` must be."""
    lefts = [q[0] for q in quads]
    bottoms = [q[1] for q in quads]
    rights = [q[2] for q in quads]
    tops = [q[3] for q in quads]
    return (min(lefts), min(bottoms), max(rights), max(tops))


def add_to_page(pdf, page, marks) -> int:
    """Write ``marks`` onto one output page. Returns how many."""
    written = 0
    for annotation in marks:
        entry = to_dictionary(pdf, annotation)
        if pikepdf.Name.Annots not in page:
            page[pikepdf.Name.Annots] = pdf.make_indirect(pikepdf.Array([]))
        page[pikepdf.Name.Annots].append(entry)
        written += 1
    return written
