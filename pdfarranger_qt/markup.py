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

The same shape as `forms.FormValues`, for the same reasons: the state
lives in memory, rides the undo stack beside the pages and the outline, and is
written only at export. Nothing is added to a source document, which stays the
immutable copy everything else reads.

**Keyed by page uid, not by index** -- the lesson bookmarks taught, and
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
import itertools
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

#: How big a sticky note's icon is, in points. A `/Text` annotation is the one
#: mark whose size is not its author's to choose: measured against PDFium, the
#: icon comes out **20 by 20 points from the lower left corner of `/Rect`,
#: upward and to the right** -- for a `/Rect` of 20x20, of 60x60, of 60x24 and
#: of no size at all, and at `/Rotate` 0, 90, 180 and 270, which all put it on
#: the same page-space box. 1327 coloured pixels every time.
#:
#: The lower left, not the upper: a 24 point tall rectangle gets an icon 20
#: tall sitting on its *bottom* edge. A square rectangle of exactly this size
#: cannot tell the two apart, which is what made the first reading of this
#: "the top left" -- the box is the same either way.
#:
#: The rectangle is written at that size anyway, so that what the file says is
#: there is where the icon is drawn, and a click lands on a note in this
#: reader exactly where it would in any other.
NOTE_SIZE = 20.0


def icon_box(rect) -> "tuple[float, float, float, float]":
    """The box a note's icon is actually drawn in, given its rectangle.

    `NOTE_SIZE` square from the rectangle's lower left corner, which is what
    a viewer draws whatever the rectangle says -- so this is what to hit-test
    and what to draw, rather than the rectangle itself. The two are the same
    box for a note placed here and different for one whose page has since been
    resized, because the resize multiplies the rectangle and leaves the icon
    the size it was.
    """
    left, bottom = rect[0], rect[1]
    return (left, bottom, left + NOTE_SIZE, bottom + NOTE_SIZE)


def note_rect(x: float, top: float,
              size: float = NOTE_SIZE) -> "tuple[float, float, float, float]":
    """The rectangle a note placed at ``(x, top)`` is stored with.

    ``top`` is the top of the icon as drawn, so the rectangle runs down from
    it: a viewer anchors the icon to the rectangle's *lower* left and draws
    upward, and a rectangle of exactly the icon's size therefore is the icon's
    box. Measured from the pointer rather than centred on it, because a note
    that appears half its own height above the click is a note placed
    somewhere you did not click.

    ``size`` is the icon's size *in the space this rectangle is in*. The icon
    is `NOTE_SIZE` on the page a reader draws, so on a page resized to half
    the mark holds twice that: the source page's space is the output's divided
    by the resize, and the resize multiplies it back on the way out.
    """
    return (x, top - size, x + size, top)


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


def scaled(annotation: Annotation, factor: float) -> Annotation:
    """``annotation`` with every coordinate multiplied by ``factor``.

    A mark is kept in the source page's space and a resized page's space
    is that one multiplied, so this is what turns the one into the other on
    the way out. Both the rectangle and the quadrilaterals, because they are
    in the same space and scaling one without the other puts the box in the
    right place around a shape still drawn at the old size -- which is the
    same mistake `export._scale_annotation` exists to avoid for the marks the
    file already carries.
    """
    if factor == 1:
        return annotation
    copy_of = annotation.duplicate()
    copy_of.rect = tuple(v * factor for v in annotation.rect)
    copy_of.quads = tuple(tuple(v * factor for v in quad)
                          for quad in annotation.quads)
    return copy_of


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
        # The icon a viewer draws. /Note is the one every viewer has, and
        # PDFium draws the same glyph whatever this says -- measured, the
        # same 1327 pixels for /Comment, /Help, /Key, /Star, for no /Name at
        # all and for a name that is not in the specification. It is written
        # for the viewers that do look at it.
        entry[pikepdf.Name.Name] = pikepdf.Name("/Note")
        # No appearance stream, and this is the one mark where that is a
        # decision rather than a shortcut. A highlight carries one because a
        # viewer is only recommended to draw the quadrilaterals; a note's
        # appearance is an *icon*, and every viewer already has one its users
        # recognise. Measured: PDFium draws a note with no /AP in 1327 pixels
        # and one with an /AP of ours in 1600 -- the stream does not rescue a
        # file, it replaces a familiar balloon with our rounded box.
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


def add_to_page(pdf, page, marks, factor: float = 1.0) -> int:
    """Write ``marks`` onto one output page. Returns how many.

    ``factor`` is the page's resize, which the marks are *not* in: they are in
    the source page's space, so a page written at half size takes its
    marks multiplied by a half.
    """
    written = 0
    for annotation in marks:
        entry = to_dictionary(pdf, scaled(annotation, factor))
        if pikepdf.Name.Annots not in page:
            page[pikepdf.Name.Annots] = pdf.make_indirect(pikepdf.Array([]))
        page[pikepdf.Name.Annots].append(entry)
        written += 1
    return written


#: Identity for a mark the file brought, handed out as a page's annotations
#: are first read. Session-local on purpose: a change to one of these is held
#: as an overlay until the document is saved, and once it is saved the change
#: is in the file and there is nothing left to key. So nothing is written to a
#: document somebody only looked at.
#:
#: Not the position in `/Annots`, which our own edits invalidate -- deleting a
#: mark takes its status chain and its replies with it, everything after
#: shifts, and undo shifts them back, so a position names a different mark in
#: between. The same reasoning as `Page.uid`, for the same reason.
_mark_uids = itertools.count(1)

#: Bit 2 of `/F`, Hidden. A status change carries it and a reply does not,
#: which is why one of them draws a comment icon on the page and the other
#: never appears.
HIDDEN = 2


class Mark:
    """One annotation the document already had, as this application sees it.

    Deliberately *not* an `Annotation`. That is the overlay of what the user
    made; this is a reading of what was there, and the dictionary it was read
    from stays the source of truth for every key nobody has touched.
    """

    __slots__ = ("uid", "page", "subtype", "rect", "quads", "colour",
                 "opacity", "contents", "name", "parent", "state", "hidden")

    def __init__(self, page, subtype, rect, quads=(), colour=None,
                 opacity=None, contents="", name=None, parent=None,
                 state=None, hidden=False):
        self.uid = next(_mark_uids)
        self.page = page
        self.subtype = subtype
        self.rect = tuple(rect)
        self.quads = tuple(tuple(q) for q in quads)
        self.colour = colour
        self.opacity = opacity
        self.contents = contents
        #: `/NM`, when the producer wrote one. Not used for identity -- see
        #: `_mark_uids` -- but it is how a child names its parent.
        self.name = name
        #: The `/NM` of the mark this one hangs off, for a reply or a status.
        self.parent = parent
        #: `/State`, which is what tells a status change from a reply. `/RT`
        #: does not: it is absent on both, which the format reads as a reply.
        self.state = state
        self.hidden = hidden

    def is_status(self) -> bool:
        return self.state is not None

    def is_reply(self) -> bool:
        return self.parent is not None and self.state is None

    def __repr__(self):  # pragma: no cover - debugging aid
        return (f"Mark({self.subtype}, page={self.page}, uid={self.uid}, "
                f"rect={self.rect})")


def _number(value, default=None):
    try:
        return float(value)
    except Exception:  # noqa: BLE001 - a key we cannot read is a key we skip
        return default


def marks_in(pdf) -> "list[Mark]":
    """Every annotation in a document, as `Mark`s, in page order.

    Form widgets are left out: a field is an annotation, but it is the forms
    layer's business and it is reached by a different click.
    """
    found = []
    for number, page in enumerate(pdf.pages, start=1):
        for annot in page.obj.get(pikepdf.Name.Annots) or []:
            try:
                subtype = str(annot.get(pikepdf.Name.Subtype, ""))
                if subtype in ("/Widget", "/Popup", "/Link"):
                    continue
                rect = [_number(v, 0.0) for v in
                        annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
                raw = annot.get(pikepdf.Name.QuadPoints) or []
                quads = [tuple(_number(v, 0.0) for v in raw[at:at + 8])
                         for at in range(0, len(raw) - 7, 8)]
                colour = annot.get(pikepdf.Name.C)
                parent = annot.get(pikepdf.Name.IRT)
                found.append(Mark(
                    page=number,
                    subtype=subtype,
                    rect=rect,
                    quads=quads,
                    colour=(tuple(_number(v, 0.0) for v in colour)
                            if colour is not None else None),
                    opacity=_number(annot.get(pikepdf.Name.CA)),
                    contents=str(annot.get(pikepdf.Name.Contents, "")),
                    name=(str(annot[pikepdf.Name.NM])
                          if pikepdf.Name.NM in annot else None),
                    parent=(str(parent[pikepdf.Name.NM])
                            if parent is not None
                            and pikepdf.Name.NM in parent else None),
                    state=(str(annot[pikepdf.Name.State])
                           if pikepdf.Name.State in annot else None),
                    hidden=bool(int(annot.get(pikepdf.Name.F, 0)) & HIDDEN),
                ))
            except Exception:  # noqa: BLE001 - one bad mark is not the page
                continue
    return found


class MarkMap:
    """Which mark is under a point, per page of one source document.

    Built once per document and kept, for the reason `forms.FieldMap` is:
    a click asks on every press, and the markup sample carries 180
    annotations on four pages.

    The document is *not* held open. Unlike a field, nothing here renders an
    appearance out of it -- the reader draws the marks from the copy it is
    showing -- so the file is read once and let go.
    """

    __slots__ = ("_by_page",)

    def __init__(self, marks=()):
        self._by_page: Dict[int, List[Mark]] = {}
        for mark in marks:
            self._by_page.setdefault(mark.page, []).append(mark)

    @classmethod
    def read(cls, source) -> "MarkMap":
        """From a path. An empty map if it cannot be read."""
        try:
            with pikepdf.open(source) as pdf:
                return cls(marks_in(pdf))
        except Exception:  # noqa: BLE001 - a click simply finds nothing
            return cls()

    def for_page(self, page: int) -> List[Mark]:
        """Every mark on a 1-based page of the source, drawable ones first."""
        return list(self._by_page.get(page, ()))

    def visible(self, page: int) -> List[Mark]:
        """The ones a click could plausibly be aimed at.

        A status change is hidden by its `/F` and draws nothing, so it can
        never be what was clicked -- it is reached through the mark it hangs
        off instead.
        """
        return [m for m in self.for_page(page) if not m.hidden]

    def by_uid(self, uid: int) -> Optional[Mark]:
        for marks in self._by_page.values():
            for mark in marks:
                if mark.uid == uid:
                    return mark
        return None

    def children(self, mark: Mark) -> List[Mark]:
        """The replies and status changes hanging off ``mark``.

        Follows the chain rather than taking one step: the first status
        change points at the mark, and each later one points at *the link
        before it*, so a single step finds the first and misses the rest.
        """
        if mark.name is None:
            return []
        found, frontier = [], {mark.name}
        while frontier:
            names = set()
            for marks in self._by_page.values():
                for other in marks:
                    if other.parent in frontier and other not in found:
                        found.append(other)
                        if other.name is not None:
                            names.add(other.name)
            frontier = names
        return found

    def __len__(self):
        return sum(len(v) for v in self._by_page.values())
