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
import getpass
import itertools
import uuid
from typing import Dict, List, Optional, Tuple

import pikepdf

from .i18n import N_

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

#: What a reader calls each kind in a comment list. Not translated: these are
#: the strings producers actually write, read out of the corpus rather than
#: invented -- `/Highlight` is "Highlight" in seven files, `/StrikeOut` is
#: "Cross-Out" in four and `/Text` is "Sticky Note" in seven. A reader groups
#: and filters its comment list by this, so a translated one would sort into
#: a category of its own in every other language.
SUBJECTS = {HIGHLIGHT: "Highlight", STRIKEOUT: "Cross-Out",
            TEXT: "Sticky Note"}

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


def default_author() -> str:
    """Who to put on a mark: the account making it.

    The login name, because the document has nothing better to offer -- the
    `/Info` dictionary of the files in the corpus is empty, so there is no
    name in the document to inherit. Acrobat has an identity setting of its
    own and falls back the same way.

    Tolerant of having no answer: `getpass.getuser` reads four environment
    variables before it asks the password database, and raises if none of
    them has anything. A mark with no author is a mark; a traceback while
    placing one is not.
    """
    try:
        return getpass.getuser() or ""
    except Exception:       # noqa: BLE001 - no login name is not an error
        return ""


class Annotation:
    """One mark, in the page coordinates of the page it belongs to."""

    __slots__ = ("kind", "page", "rect", "quads", "contents", "colour",
                 "opacity", "author", "created", "name")

    def __init__(self, kind: str, page: int, rect: Tuple[float, ...],
                 contents: str = "", colour=None, author: Optional[str] = None,
                 created: Optional[str] = None, quads=(),
                 name: Optional[str] = None, opacity=None):
        if kind not in KINDS:
            raise ValueError(f"unknown annotation kind: {kind}")
        self.kind = kind
        self.page = page
        self.rect = tuple(float(v) for v in rect)
        #: The mark's `/NM`, its name within the file. Made here rather than
        #: at export so that it survives a save: a name minted on the way out
        #: would be a different one every time, and anything pointing at the
        #: mark -- a reply, a status change -- would be pointing at a name
        #: that no longer exists. `duplicate` copies it, so undo and redo
        #: carry the same mark rather than a succession of new ones.
        self.name = name or str(uuid.uuid4())
        #: One rectangle per run of text, for the subtypes that mark text.
        #: Empty for the rest. A highlight over three lines is three quads,
        #: not one box round the paragraph -- which would cover the margins
        #: and the lines between.
        self.quads = tuple(tuple(float(v) for v in quad) for quad in quads or ())
        self.contents = contents
        self.colour = tuple(colour) if colour is not None else None
        #: How solid this one mark is. None means "whatever this kind is
        #: usually drawn at", which is what every mark made before the tail
        #: had an opacity slider meant and still means.
        self.opacity = float(opacity) if opacity is not None else None
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


def apply_edit(annot, edit) -> None:
    """Write one mark's edits onto the dictionary it arrived with.

    **Shared by the preview and the export, because they drifted.** They
    were near-copies of each other; the export grew a case for `quads` and
    the preview did not, so a resize was written to the file correctly and
    never shown on screen -- the page was re-rendered from a document that
    still held the old run. One mark's worth of patching in one place is
    what stops the next field reaching only one of them.

    Patched and not replaced: everything the producer put in the dictionary
    stays -- the thread, the author, the dates, the status chain -- and only
    the keys named here are rewritten.
    """
    colour = edit.get("colour")
    if colour is not None:
        annot[pikepdf.Name.C] = pikepdf.Array([*colour])
    opacity = edit.get("opacity")
    if opacity is not None:
        annot[pikepdf.Name.CA] = float(opacity)
    quads = edit.get("quads")
    if quads:
        annot[pikepdf.Name.QuadPoints] = pikepdf.Array(
            [v for quad in quads for v in _quad_points(quad)])
        annot[pikepdf.Name.Rect] = pikepdf.Array([*bounding_rect(quads)])
    if pikepdf.Name.AP in annot:
        # The stream the producer wrote still draws the old colour over the
        # old run, and every reader falls back to `/QuadPoints` when there
        # is none.
        del annot[pikepdf.Name.AP]


def one_page_with_edits(data, index: int, edits) -> "Optional[bytes]":
    """``data``'s page ``index`` on its own, with ``edits`` applied.

    For showing a change at once. The page a reader is looking at has its
    annotations baked into the bitmap PDFium draws, so a recoloured mark
    cannot be painted over the old one -- the page has to be rendered from a
    document that carries the change. Rewriting the whole document to do that
    is what makes it slow: measured on a 1590-page book, patching and saving
    the file costs 1180 ms against 1.1 to 6.5 ms for lifting the one page out
    and patching that.

    Returns None when there is nothing to show differently, so the caller can
    put the page back on the ordinary render path rather than keeping a
    document that says the same as the original.
    """
    import io
    import warnings

    if not edits:
        return None
    try:
        with pikepdf.open(io.BytesIO(data)) as whole:
            if not 0 <= index < len(whole.pages):
                return None
            one = pikepdf.Pdf.new()
            one.pages.append(whole.pages[index])
            page = one.pages[0].obj
            at, changed = 0, 0
            for annot in page.get(pikepdf.Name.Annots) or []:
                try:
                    subtype = str(annot.get(pikepdf.Name.Subtype, ""))
                except Exception:  # noqa: BLE001 - unreadable is not markup
                    continue
                if subtype in ("/Widget", "/Popup", "/Link"):
                    continue
                edit = edits.get(at)
                at += 1
                if not edit:
                    continue
                apply_edit(annot, edit)
                changed += 1
            if not changed:
                return None
            out = io.BytesIO()
            with warnings.catch_warnings():
                # `PageCopyWarning`, raised by `save`: the widgets travel
                # with the page but this document has no `/AcroForm` for them
                # to hang off, and Acrobat may not display them. Acrobat
                # never sees it. It is rasterised once, here, and thrown
                # away -- and the page comes out *identical*: rendered from
                # the whole document and from this copy, 0 of 484,704 pixels
                # differ, with all 15 widgets and all 15 of their appearance
                # streams present either way.
                #
                # pikepdf names `add_pages_from` as the remedy and neither of
                # its modes serves. The default raises "stream objects cannot
                # be cloned" against a document whose form resources hold a
                # stream, the same shape as the `/DR` pattern that once broke
                # export. `forms="strip"` succeeds and removes all 15
                # widgets, so the page would render without its fields --
                # worse than the warning it silences.
                warnings.simplefilter("ignore", pikepdf.PageCopyWarning)
                one.save(out)
            one.close()
            return out.getvalue()
    except Exception:  # noqa: BLE001 - a page that will not patch is shown
        return None    # as it was, which is better than not shown at all


class MarkEdits:
    """Changes to the marks a document arrived with, by page.

    `Annotations` holds what the user *made*; this holds what the user
    *changed* about what was already there, and the two are deliberately
    different things. A mark the file brought keeps its own dictionary as the
    source of truth for every key nobody has touched -- `/NM`, `/Popup`,
    `/RC`, `/Subj`, `/T`, the `/IRT` chains, the lot -- and export rewrites
    only the handful of keys named here. Replacing the mark instead would
    lose every key this application does not model, which is most of them.

    **Keyed by `(page uid, index)`**, where the index counts the markup
    annotations on that page in the order the file has them. The page uid for
    the reason `Annotations` uses it: a reorder or an undo must not move an
    edit onto a different page, and a duplicated page gets a uid of its own,
    so recolouring a mark on one copy leaves the other alone.

    The index is a position, and a position is the wrong name for a *mark*:
    deleting one takes its status chain and its replies with it, everything
    after shifts, and an undo shifts them back, so the same number means a
    different mark from one moment to the next. This is not that. It is a
    position in the source document, which this application never edits, so
    nothing renumbers it. Export reads the same pages in the same order and
    `marks_in` enumerates them the same way, which is measured
    -- the markup sample comes through an export with its annotations in the
    same order and the same count, 64, 64, 27 and 25 across its four pages.

    Widgets, popups and links are not counted, so stripping an unsigned
    signature widget on the way out cannot shift an edit onto its neighbour.
    """

    __slots__ = ("_by_page",)

    #: What may be changed about a mark the file brought. Anything not here
    #: is left exactly as the producer wrote it.
    #:
    #: `quads` carries geometry, and geometry is the same problem as colour:
    #: `/QuadPoints` and `/Rect` are rewritten and the appearance dropped,
    #: while `/NM`, `/Popup`, `/RC` and the `/IRT` chains stay the
    #: producer's. A resized highlight is the same mark, with the same
    #: comment thread hanging off it.
    FIELDS = ("colour", "opacity", "quads")

    def __init__(self, by_page=None):
        self._by_page: Dict[int, Dict[int, dict]] = {}
        for uid, marks in (by_page or {}).items():
            kept = {n: dict(edit) for n, edit in marks.items() if edit}
            if kept:
                self._by_page[uid] = kept

    def duplicate(self) -> "MarkEdits":
        return MarkEdits(self._by_page)

    def change(self, uid: int, index: int, **fields) -> None:
        """Record ``fields`` against one mark, merging with what is there."""
        unknown = set(fields) - set(self.FIELDS)
        if unknown:
            raise ValueError(f"not an editable attribute: {sorted(unknown)}")
        edit = self._by_page.setdefault(uid, {}).setdefault(index, {})
        edit.update({k: v for k, v in fields.items() if v is not None})
        if not edit:
            self.forget(uid, index)

    def forget(self, uid: int, index: int) -> None:
        marks = self._by_page.get(uid)
        if not marks or index not in marks:
            return
        del marks[index]
        if not marks:
            del self._by_page[uid]

    def of(self, uid: int, index: int) -> dict:
        """What has been changed about one mark. Empty when nothing has."""
        return dict(self._by_page.get(uid, {}).get(index, {}))

    def for_page(self, uid: int) -> Dict[int, dict]:
        return {n: dict(edit)
                for n, edit in self._by_page.get(uid, {}).items()}

    def pages(self):
        return self._by_page.keys()

    def clear(self):
        self._by_page.clear()

    def __bool__(self):
        return bool(self._by_page)

    def __len__(self):
        return sum(len(marks) for marks in self._by_page.values())

    def __eq__(self, other):
        if not isinstance(other, MarkEdits):
            return NotImplemented
        return self._by_page == other._by_page

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"MarkEdits({len(self)} on {len(self._by_page)} page(s))"


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


def to_dictionary(pdf, annotation: Annotation, page=None) -> pikepdf.Dictionary:
    """``annotation`` as a PDF annotation dictionary in ``pdf``.

    Indirect, because a page's ``/Annots`` is an array of references and an
    inline dictionary there is reachable only through that one page -- which
    stops working the moment anything wants to point at the mark.

    ``page`` is the output page object this mark is going onto, for `/P`.
    Optional so that a caller only interested in the dictionary -- a test
    comparing what a mark writes -- need not build a page to get one.
    """
    entry = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name(annotation.kind),
        Rect=pikepdf.Array([*annotation.rect]),
        F=PRINTABLE,
        M=pikepdf.String(annotation.created),
        # When the mark was made, as against `/M`, when it was last touched.
        # A reader sorts its comment list by one and shows the other, and
        # with only `/M` written both answers were the same.
        CreationDate=pikepdf.String(annotation.created),
        # The mark's name in the file. A reply or a status change is a
        # separate annotation that refers to the mark it answers, so a mark
        # that cannot be named cannot be replied to.
        NM=pikepdf.String(annotation.name),
    )
    subject = SUBJECTS.get(annotation.kind)
    if subject:
        entry[pikepdf.Name.Subj] = pikepdf.String(subject)
    if annotation.contents:
        # Only when there is something to say. Written unconditionally, an
        # uncommented highlight carries an empty `/Contents`, and a reader
        # that lists comments lists it -- an empty note against a mark whose
        # whole point was that it had nothing to add.
        entry[pikepdf.Name.Contents] = pikepdf.String(annotation.contents)
    if page is not None:
        # The page the mark is on. Readers use it to answer "which page is
        # this comment on" without searching every `/Annots`, and ours has
        # to be right: `export._repoint_annotations` rewrites `/P` on every
        # annotation that has one, after the transform passes have replaced
        # the page objects, so a mark without `/P` is simply left out of the
        # fixing rather than left correct.
        #
        # Only when it is a reference. `/P` written as a direct object is
        # not a pointer at the page, it is a *copy* of the page's whole
        # dictionary inside the annotation -- which qpdf refuses to save, so
        # every mark silently failed to reach the file. `add_to_page` is
        # handed a `pikepdf.Page` wrapper rather than the object underneath
        # it, which is where the direct copy came from.
        if getattr(page, "is_indirect", False):
            entry[pikepdf.Name.P] = page
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
        entry[pikepdf.Name.CA] = solidity(annotation)
        entry[pikepdf.Name.AP] = pikepdf.Dictionary(
            N=_appearance(pdf, annotation))
    if annotation.author:
        entry[pikepdf.Name.T] = pikepdf.String(annotation.author)
    if annotation.colour is not None:
        entry[pikepdf.Name.C] = pikepdf.Array([*annotation.colour])
    return pdf.make_indirect(entry)


#: The colours a mark can be given, as Acrobat offers them: seven hues, the
#: same seven lightened, and a greyscale row, laid out three rows of seven.
#:
#: **Sampled from the picker itself, after converting it out of Display P3.**
#: A screenshot taken on a Mac carries a P3 profile, and reading its pixels as
#: though they were sRGB is wrong by up to 59 of 255 -- Light blue samples
#: `#73E2FB` raw against the `#38E5FF` Acrobat actually writes. Converted, the
#: eight of these that appear in Acrobat-written documents in the corpus match
#: what is in those files to within one unit, four of them exactly: Blue,
#: Magenta, Purple and Light blue land on the nose, and Red, Orange, Light red
#: and Light green are one off in a single channel. Eight confirmations that
#: the other thirteen are right too.
#:
#: The names are Reader's own, read off its tooltips rather than guessed:
#: the second row is "Light" plus the hue above it throughout, the sixth hue
#: is Fuchsia and not Magenta, and the greys run White, Pale, Light, Medium,
#: Dark, Darker, Black. Shown as tooltips here too, and therefore translated.
#:
#: They were taken out once, on the reasoning that Reader shows no name *on*
#: a swatch and nobody would ever see them, and put back when it turned out
#: Reader does put one in its tooltip. Both the removal and the first set of
#: names were assumptions that reading the tooltips replaced.
PALETTE = (
    (N_("Blue"), (0.0745, 0.4510, 0.9098)),
    (N_("Green"), (0.0235, 0.5412, 0.1059)),
    (N_("Yellow"), (1.0, 0.7569, 0.0118)),
    (N_("Orange"), (1.0, 0.3804, 0.0039)),
    (N_("Red"), (0.8588, 0.2000, 0.1490)),
    (N_("Fuchsia"), (0.7529, 0.2157, 0.7686)),
    (N_("Purple"), (0.5882, 0.2627, 0.9882)),

    (N_("Light Blue"), (0.2196, 0.8980, 1.0)),
    (N_("Light Green"), (0.7725, 0.9843, 0.4431)),
    (N_("Light Yellow"), (0.9922, 0.9569, 0.5216)),
    (N_("Light Orange"), (1.0, 0.6627, 0.4824)),
    (N_("Light Red"), (0.9686, 0.3961, 0.3922)),
    (N_("Light Fuchsia"), (0.9843, 0.5333, 1.0)),
    (N_("Light Purple"), (0.8627, 0.6667, 1.0)),

    (N_("White"), (1.0, 1.0, 1.0)),
    (N_("Pale Grey"), (0.8, 0.8, 0.8)),
    (N_("Light Grey"), (0.6667, 0.6667, 0.6667)),
    (N_("Medium Grey"), (0.4627, 0.4627, 0.4627)),
    (N_("Dark Grey"), (0.2667, 0.2667, 0.2667)),
    (N_("Darker Grey"), (0.2, 0.2, 0.2)),
    (N_("Black"), (0.0, 0.0, 0.0)),
)

#: How the palette is laid out, which the popup follows and nothing else
#: depends on.
PALETTE_COLUMNS = 7


def nearest_swatch(colour):
    """The index of the palette entry closest to ``colour``, or None.

    A mark the file brought may be any colour at all -- Acrobat has a wheel
    and sliders behind the same button, and other producers have their own --
    so the tick in the popup marks the nearest cell rather than only an exact
    one. Compared as plain distance in RGB, which is enough to pick the right
    cell out of twenty-one that are far apart.
    """
    if colour is None:
        return None
    best, distance = None, None
    for n, (_name, swatch) in enumerate(PALETTE):
        span = sum((a - b) ** 2 for a, b in zip(colour, swatch))
        if distance is None or span < distance:
            best, distance = n, span
    return best


#: How solid each kind is drawn when nobody has said otherwise. A highlight
#: has to be seen through or it hides the words it marks; a line drawn over
#: them does not.
TRANSPARENCY = {HIGHLIGHT: 0.4, STRIKEOUT: 1.0}


def solidity(annotation) -> float:
    """``/CA`` for a mark: its own, or what its kind is usually drawn at."""
    if getattr(annotation, "opacity", None) is not None:
        return float(annotation.opacity)
    return TRANSPARENCY.get(annotation.kind, 1.0)


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
            ca=solidity(annotation))))
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
    # The object, not the `pikepdf.Page` wrapper around it: `/P` has to be a
    # reference to the page, and a wrapper assigned into a dictionary writes
    # the page out again inside the annotation.
    target = getattr(page, "obj", page)
    for annotation in marks:
        entry = to_dictionary(pdf, scaled(annotation, factor), page=target)
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

    __slots__ = ("uid", "page", "index", "subtype", "rect", "quads", "colour",
                 "opacity", "contents", "author", "name", "parent", "state",
                 "hidden")

    def __init__(self, page, subtype, rect, quads=(), colour=None,
                 opacity=None, contents="", name=None, parent=None,
                 state=None, hidden=False, index=-1, author=""):
        self.uid = next(_mark_uids)
        #: Where this mark sits among the markup annotations on its page, in
        #: the order the file has them. What `MarkEdits` keys an edit by, and
        #: the one thing about a mark that export can find again: it reads
        #: the same pages with the same enumeration.
        self.index = index
        self.page = page
        self.subtype = subtype
        self.rect = tuple(rect)
        self.quads = tuple(tuple(q) for q in quads)
        self.colour = colour
        self.opacity = opacity
        self.contents = contents
        #: `/T`, who made it. Shown beside a note's text, as Reader shows it.
        self.author = author
        #: `/NM`, when the producer wrote one. Not used for identity -- see
        #: `_mark_uids` -- but it is how a child names its parent.
        self.name = name
        #: The `/NM` of the mark this one hangs off, for a reply or a status.
        self.parent = parent
        #: `/State`, which is what tells a status change from a reply. `/RT`
        #: does not: it is absent on both, which the format reads as a reply.
        self.state = state
        self.hidden = hidden

    def boxes(self) -> "list[tuple]":
        """The quadrilaterals as ``(left, bottom, right, top)`` rectangles.

        `/QuadPoints` is eight numbers -- four corners -- and is kept that way
        above, because that is what the file says and a corner is not ours to
        throw away. This is the reading of them that drawing and clicking
        want, and it is the bounding box of each: a quadrilateral may in
        principle lean, though no producer in the corpus writes one that
        does, and a box round a leaning one is still the right thing to aim a
        click at.

        Falls back to `/Rect` for the kinds that have no quadrilaterals, so a
        caller can ask any mark where it is without asking what kind it is.
        """
        found = []
        for quad in self.quads:
            if len(quad) < 8:
                continue
            xs, ys = quad[0::2], quad[1::2]
            found.append((min(xs), min(ys), max(xs), max(ys)))
        return found or [self.rect]

    def has_note(self) -> bool:
        """Whether this mark carries a popup note of its own.

        The text is `/Contents` on the mark; a mark with none is a mark
        nobody has written anything about. A reply or a status change has
        contents too -- "Completed set by dws" -- which is why this is only
        ever asked of a mark that is neither.
        """
        return bool(self.contents) and not self.parent

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
        at = 0
        for annot in page.obj.get(pikepdf.Name.Annots) or []:
            try:
                subtype = str(annot.get(pikepdf.Name.Subtype, ""))
            except Exception:  # noqa: BLE001 - unreadable is not markup
                continue
            if subtype in ("/Widget", "/Popup", "/Link"):
                # Not counted. A widget can be removed on the way out --
                # `export._strip_signatures` does exactly that -- and an
                # index that counted it would then name the mark next door.
                continue
            try:
                rect = [_number(v, 0.0) for v in
                        annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
                raw = annot.get(pikepdf.Name.QuadPoints) or []
                quads = [tuple(_number(v, 0.0) for v in raw[at:at + 8])
                         for at in range(0, len(raw) - 7, 8)]
                colour = annot.get(pikepdf.Name.C)
                parent = annot.get(pikepdf.Name.IRT)
                found.append(Mark(
                    page=number,
                    index=at,
                    subtype=subtype,
                    rect=rect,
                    quads=quads,
                    colour=(tuple(_number(v, 0.0) for v in colour)
                            if colour is not None else None),
                    opacity=_number(annot.get(pikepdf.Name.CA)),
                    contents=str(annot.get(pikepdf.Name.Contents, "")),
                    author=str(annot.get(pikepdf.Name.T, "")),
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
            finally:
                # Counted even when reading the mark failed, so that one
                # unreadable annotation does not slide every mark after it
                # one place along and hand their edits to their neighbours.
                at += 1
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

    def thread(self, mark: Mark) -> "tuple":
        """``(replies, status)`` for a mark, as a reader counts them.

        **The chain is a history and the status is a state.** A mark whose
        chain reads `Accepted` then a reply then `Completed` has *one*
        status, Completed, and one reply -- which is what Reader says, "(1
        Reply / 1 Status)", against the two status changes the chain
        actually holds. Each later change points at the one before it, so
        the last is the current one and the rest are how it got there.

        The whole chain is still `children`, and the properties form shows
        it as Review History.
        """
        found = self.children(mark)
        replies = [m for m in found if m.is_reply()]
        statuses = [m for m in found if m.is_status()]
        return replies, (statuses[-1].state if statuses else None)

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
