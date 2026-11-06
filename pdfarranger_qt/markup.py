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
import math
import uuid
from html import escape
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

import pikepdf

from .i18n import N_

#: Every subtype this module can write. Kept explicit so that an unknown kind
#: is a failed assertion here rather than a dictionary a viewer silently drops.
TEXT = "/Text"
HIGHLIGHT = "/Highlight"
STRIKEOUT = "/StrikeOut"
UNDERLINE = "/Underline"
#: The squiggly *is* the underline's other style. Reader's Underline tool
#: writes this subtype with `/IT /Underline` when the style is squiggly, so
#: a squiggly reads back as the Underline tool rather than as a kind of its
#: own, and the two are one tool here.
SQUIGGLY = "/Squiggly"

KINDS = (TEXT, HIGHLIGHT, STRIKEOUT, UNDERLINE, SQUIGGLY)

#: The two subtypes one tool writes, and which of them means what. A style
#: is not a value inside the dictionary: it is which dictionary gets
#: written.
UNDERLINE_STYLES = {"straight": UNDERLINE, "squiggly": SQUIGGLY}

#: Subtypes whose geometry is a run of text rather than a box, and which say
#: so with `/QuadPoints`. `/Rect` still has to be there and has to contain
#: them: a viewer that does not understand the subtype falls back to it.
QUADDED = (HIGHLIGHT, STRIKEOUT, UNDERLINE, SQUIGGLY)

#: What a reader calls each kind in a comment list. Not translated: these are
#: the strings producers actually write, read out of the corpus rather than
#: invented -- `/Highlight` is "Highlight" in seven files, `/StrikeOut` is
#: "Cross-Out" in four and `/Text` is "Sticky Note" in seven. A reader groups
#: and filters its comment list by this, so a translated one would sort into
#: a category of its own in every other language.
#: `/IT` for the subtypes that carry one whatever tool made them. A tool
#: with an intent of its own overrides this -- *Add note to text* writes
#: `/HighlightNote` on a `/Highlight`, which has none by default.
INTENTS = {SQUIGGLY: UNDERLINE}

SUBJECTS = {HIGHLIGHT: "Highlight", STRIKEOUT: "Cross-Out",
            TEXT: "Sticky Note",
            # Both styles say Underline, because both come from the one
            # tool -- read off `Markup Underline.pdf`, where the same words
            # were marked each way.
            UNDERLINE: "Underline", SQUIGGLY: "Underline"}

#: Bit 3 of `/F`, Print. Without it a mark shows on screen and vanishes from
#: paper, which is not what anybody means by annotating a document.
PRINTABLE = 4

#: Print, NoZoom and NoRotate: what Reader gives a reply, whose icon is
#: anchored to the mark it answers rather than drawn on the paper.
ANCHORED = 28

#: The same, with Hidden: what a status change carries. It never draws --
#: a status is read in the thread or in Review History, not on the page.
UNSEEN = 30

#: The five a mark can be given, as Reader's *Set status* offers them, with
#: None first and the rest alphabetical. **Written as they are**: `/State`
#: holds these keywords and a reader matches them, so a translated one is a
#: status no other application understands. The menu shows them translated
#: and writes these.
STATUSES = ("None", "Accepted", "Cancelled", "Completed", "Rejected")

#: The style properties a note's rich text keeps on the way in. `color`
#: is there because Reader sets it: selecting words inside a note and
#: opening its properties colours *those words*, which is a thing the
#: *Text Style* menu cannot do here -- measured 2026-11-03 on a reply
#: carrying `color:#0331FF` and `color:#FF3FFF`. Acrobat
#: writes a `<span>` round every run whether or not anything is styled, and
#: gives each one the whole set -- including `font-size:-14.0pt`, negative,
#: which reads as "not set", and an alignment that means nothing inside a
#: line. Neither of those survives the trip. What is left is what the *Text
#: Style* menu can say.
RICH_STYLES = ("font-weight", "font-style", "text-decoration",
               "vertical-align", "color")

#: The values that mean "nothing is set", per property. A span carrying only
#: these is a run with no styling, and is written out as bare text so that a
#: note nobody styled does not arrive as markup.
RICH_PLAIN = {"font-weight": "normal", "font-style": "normal",
              "text-decoration": "none", "vertical-align": "baseline"}


def rich_to_html(rich):
    """`/RC` as a fragment Qt can draw, or None when it says nothing.

    **`/RC` is the rich version of `/Contents` and viewers prefer it.** A
    note Acrobat styled reads plain here until this is used, which is what
    made the underlined reply in the corpus arrive as ordinary text.

    None when there is no rich content, when it will not parse, or when
    nothing in it is styled -- in each case `/Contents` is the better
    answer and the caller already has it.
    """
    if not rich:
        return None
    try:
        root = ElementTree.fromstring(rich)
    except ElementTree.ParseError:
        return None
    lines, styled = [], False
    for para in root.iter():
        if para.tag.rsplit("}", 1)[-1].lower() != "p":
            continue
        piece, found = _rich_piece(para)
        styled = styled or found
        lines.append(piece)
    if not styled:
        return None
    # Joined with breaks rather than left as paragraphs: a note is a few
    # lines and Qt gives a paragraph margins this window has no room for.
    return "<br>".join(line for line in lines if line)


def _rich_piece(node):
    """One element of `/RC` as Qt's rich text, and whether it styled
    anything."""
    inner = escape(node.text or "")
    styled = False
    for child in node:
        piece, found = _rich_piece(child)
        styled = styled or found
        inner += piece + escape(child.tail or "")
    tag = node.tag.rsplit("}", 1)[-1].lower()
    if tag == "br":
        return "<br>" + inner, styled
    if tag in ("b", "i", "u"):
        return "<%s>%s</%s>" % (tag, inner, tag), True
    if tag == "span":
        style = _kept_style(node.get("style", ""))
        if style:
            return '<span style="%s">%s</span>' % (style, inner), True
    return inner, styled


#: The shell Acrobat writes `/RC` in, less its own `xfa:APIVersion` -- that
#: names the Acrobat build that wrote the file, which this is not.
RICH_HEAD = ('<?xml version="1.0"?>'
             '<body xmlns="http://www.w3.org/1999/xhtml" '
             'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" '
             'xfa:spec="2.0.2">')


#: The property set Reader puts on a run that carries no styling: every
#: property at the value that means "not set", `font-size` negative. It
#: writes one of these round **every** run of a note somebody typed, so an
#: unstyled note is a span rather than bare text.
RICH_UNSET = ("font-size:-14.0pt;text-align:left;"
              "font-weight:normal;font-style:normal")


def rich_from_runs(paragraphs) -> str:
    """Styled runs as `/RC`.

    ``paragraphs`` is a list of lines, each a list of ``(text, style)``
    where the style names only what is set -- the shape `NotePanel.runs`
    reports. A run with nothing set still gets a span, carrying
    `RICH_UNSET`, because that is what Reader writes.

    **Always, even when nothing is styled.** It used to answer None there,
    on a reading of the fixture that counted the status links as unstyled
    notes: every bare `<p>` in the corpus belongs to a status change or a
    file attachment, and every note a person typed carries a span. So a
    note written here arrived without the `/RC` a reader prefers.
    """
    out = [RICH_HEAD]
    for line in paragraphs:
        out.append('<p dir="ltr">')
        for text, style in line:
            out.append('<span dir="ltr" style="%s">%s</span>' % (
                ";".join("%s:%s" % pair for pair in sorted(style.items()))
                if style else RICH_UNSET,
                escape(text)))
        out.append("</p>")
    out.append("</body>")
    return "".join(out)


def rich_from_text(text: str, generated: bool = False) -> str:
    """Plain text as `/RC`, for the marks that never saw the editor.

    ``generated`` for text this application composed rather than took from
    somebody -- a status change's "Completed set by dws". Reader writes
    those as a bare `<p>` with no span and no `dir`, and every typed note
    with both, so the distinction is the one the corpus draws.
    """
    out = [RICH_HEAD]
    for line in text.split("\n"):
        out.append("<p>%s</p>" % escape(line) if generated else
                   '<p dir="ltr"><span dir="ltr" style="%s">%s</span></p>'
                   % (RICH_UNSET, escape(line)))
    out.append("</body>")
    return "".join(out)


def _kept_style(style: str) -> str:
    """The declarations worth carrying over, in the order they were
    written."""
    kept = []
    for part in style.split(";"):
        name, _, value = part.partition(":")
        name, value = name.strip().lower(), value.strip()
        if (name in RICH_STYLES and value
                and value.lower() != RICH_PLAIN.get(name)
                and not value.startswith("-")):
            kept.append("%s:%s" % (name, value))
    return ";".join(kept)

#: The same five as a menu shows them. Separate from `STATUSES` because
#: these are read and those are written: a status translated into the file
#: is one no other application understands, and a status shown in English
#: to somebody reading in Finnish is a menu entry nobody asked for.
STATUS_LABELS = {
    "None": N_("None"),
    "Accepted": N_("Accepted"),
    "Cancelled": N_("Cancelled"),
    "Completed": N_("Completed"),
    "Rejected": N_("Rejected"),
}

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


def parse_pdf_date(value) -> "Optional[datetime.datetime]":
    """`D:YYYYMMDDHHmmSS` and whatever follows it, as a datetime.

    The zone suffix is ignored rather than applied: a note's header shows
    the time the file recorded, and shifting it into the reader's own zone
    would make a comment written at 10:13 read as some other hour.
    """
    if not value:
        return None
    digits = "".join(ch for ch in str(value).lstrip("D:") if ch.isdigit())
    if len(digits) < 8:
        return None
    digits = (digits + "000000")[:14]
    try:
        return datetime.datetime.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None


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
                 "opacity", "author", "created", "name", "irt",
                 "popup_rect", "state", "rich", "subject", "locked",
                 "intent")

    def __init__(self, kind: str, page: int, rect: Tuple[float, ...],
                 contents: str = "", colour=None, author: Optional[str] = None,
                 created: Optional[str] = None, quads=(),
                 name: Optional[str] = None, opacity=None,
                 irt: Optional[str] = None, popup_rect=None,
                 state: Optional[str] = None, rich: Optional[str] = None,
                 subject: Optional[str] = None, locked: bool = False,
                 intent: Optional[str] = None):
        if kind not in KINDS:
            raise ValueError(f"unknown annotation kind: {kind}")
        self.kind = kind
        self.page = page
        #: The `/NM` of the mark this answers, for a reply, and None for
        #: anything else. A reply is a mark in its own right -- it draws an
        #: icon, it can be selected and deleted -- and all that makes it a
        #: reply is pointing at what it answers.
        self.irt = irt
        #: Where this mark's window sits, once somebody has moved it. None
        #: until then, and the default beside the page is computed instead.
        self.popup_rect = tuple(popup_rect) if popup_rect else None
        #: The review state this link records, for a status change, and None
        #: for everything else. A status is an annotation like a reply --
        #: what makes it a status is carrying this.
        self.state = state
        #: `/RC`, this mark's text with its styling, or None when nothing
        #: in it is styled and `contents` says the whole of it.
        self.rich = rich
        #: `/Subj`, which starts as the name of the tool that made the mark
        #: and is the properties form's to change. None means the tool's.
        self.subject = subject
        #: `/F` bit 8: this mark is not to be changed. Set from the form.
        self.locked = locked
        #: `/IT`, which tool made the mark where the subtype alone does not
        #: say. None means the subtype's own, `INTENTS`, or none at all.
        self.intent = intent
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
        # Taken away at 1 rather than written as 1, so a mark turned fully
        # opaque here looks like one Reader made fully opaque.
        if float(opacity) != 1.0:
            annot[pikepdf.Name.CA] = float(opacity)
        elif pikepdf.Name.CA in annot:
            del annot[pikepdf.Name.CA]
    quads = edit.get("quads")
    if quads:
        annot[pikepdf.Name.QuadPoints] = pikepdf.Array(
            [v for quad in quads for v in _quad_points(quad)])
        annot[pikepdf.Name.Rect] = pikepdf.Array([*bounding_rect(quads)])
    popup = edit.get("popup")
    if popup:
        window = annot.get(pikepdf.Name.Popup)
        if window is not None:
            window[pikepdf.Name.Rect] = pikepdf.Array([*popup])
    contents = edit.get("contents")
    if contents is not None:
        # Removed rather than emptied when there is nothing to say: a reader
        # that lists comments lists an empty `/Contents` as a comment, which
        # is a note against a mark whose point was that it had none.
        if contents:
            annot[pikepdf.Name.Contents] = pikepdf.String(contents)
        elif pikepdf.Name.Contents in annot:
            del annot[pikepdf.Name.Contents]
        # **`/RC` is preferred over `/Contents` by every reader that
        # understands it**, so it is rewritten with the text or taken away
        # with it. Leaving the producer's rich text beside our new plain
        # text would show the words we just replaced.
        rich = edit.get("rich")
        if contents and rich:
            annot[pikepdf.Name.RC] = pikepdf.String(rich)
        elif pikepdf.Name.RC in annot:
            del annot[pikepdf.Name.RC]
    # What the properties form writes. Each is left alone unless the form
    # named it, so a mark whose colour was changed keeps the author and the
    # subject the producer gave it.
    author = edit.get("author")
    if author is not None:
        annot[pikepdf.Name.T] = pikepdf.String(author)
    subject = edit.get("subject")
    if subject is not None:
        annot[pikepdf.Name.Subj] = pikepdf.String(subject)
    style = edit.get("style")
    if style in UNDERLINE_STYLES:
        # **The one edit that changes what the annotation is.** An
        # underline's style is its subtype, so this rewrites `/Subtype`
        # -- and `/IT`, which says which tool a `/Squiggly` came from.
        # The appearance goes with it: a wave and a line are not the same
        # drawing, and the stream the producer wrote draws the old one.
        annot[pikepdf.Name.Subtype] = pikepdf.Name(UNDERLINE_STYLES[style])
        if UNDERLINE_STYLES[style] == SQUIGGLY:
            annot[pikepdf.Name.IT] = pikepdf.Name(UNDERLINE)
        elif pikepdf.Name.IT in annot:
            del annot[pikepdf.Name.IT]
    locked = edit.get("locked")
    if locked is not None:
        # One bit of `/F`, set or cleared: the rest of the flags are the
        # producer's -- Print, NoZoom, Hidden on a status link -- and are
        # nothing to do with whether the mark is locked.
        flags = int(annot.get(pikepdf.Name.F, 0))
        annot[pikepdf.Name.F] = (flags | LOCKED) if locked else (
            flags & ~LOCKED)
    if (colour is not None or opacity is not None or quads
            or style in UNDERLINE_STYLES) and (pikepdf.Name.AP in annot):
        # **Only when what it draws has changed.** The stream the producer
        # wrote still draws the old colour over the old run, and every
        # reader falls back to `/QuadPoints` when there is none.
        #
        # But for a `/Text` that stream *is* the icon, and nothing
        # regenerates one: the reader substitutes a default of its own, in
        # its own colour. Dropping it for a change to the text, the author,
        # the subject, the lock or the window's position threw away the
        # producer's artwork for a change that does not affect what is
        # drawn at all.
        del annot[pikepdf.Name.AP]


def patch_page_marks(page, edits) -> int:
    """Apply ``edits`` to one page's annotations. Returns how many were hit.

    Patch what changed and drop what was deleted, in one pass, because the
    two readers of `MarkEdits` -- the one-page re-render and the export --
    must not disagree about either. They were near-copies once and only one
    of them learned about `quads`, so a resize was written correctly to the
    file and never drawn.

    **The index counts markup annotations only**, skipping widgets, popups
    and links, which is the enumeration `marks_in` uses and the one
    `MarkEdits` is keyed by. A popup is therefore never numbered and can
    never carry an edit of its own: it goes when the mark that owns it goes.

    Dropping is decided first and applied afterwards, in a second pass,
    because `/Annots` does not promise that a popup follows its parent --
    deciding and removing in one pass would keep a popup whose owner had
    not been read yet.
    """
    annots = page.get(pikepdf.Name.Annots)
    if annots is None:
        return 0
    kept, dropped, at, changed = [], set(), 0, 0
    for annot in annots:
        try:
            subtype = str(annot.get(pikepdf.Name.Subtype, ""))
        except Exception:  # noqa: BLE001 - unreadable is not markup
            kept.append(annot)
            continue
        if subtype in ("/Widget", "/Popup", "/Link"):
            kept.append(annot)
            continue
        edit = edits.get(at)
        at += 1
        if not edit:
            kept.append(annot)
            continue
        if edit.get("deleted"):
            dropped.add(annot.objgen)
            popup = annot.get(pikepdf.Name.Popup)
            if popup is not None:
                try:
                    dropped.add(popup.objgen)
                except Exception:  # noqa: BLE001 - a direct popup owns nothing
                    pass
            changed += 1
            continue
        apply_edit(annot, edit)
        kept.append(annot)
        changed += 1
    if dropped:
        page[pikepdf.Name.Annots] = pikepdf.Array(
            [a for a in kept if a.objgen not in dropped])
    return changed


def drop_replies(page) -> int:
    """Take the replies off a page, for rendering only.

    **A reply is not page content.** Reader draws none of them, and a
    thread's replies all carry the same rectangle, so a renderer that
    honours their appearance streams stacks them into one opaque smudge at
    the corner of the mark. What a reply says belongs in the thread window
    and on the badge, both of which this application draws itself.

    Only for the page a reader is *shown*. The document that is written out
    keeps every one of them.
    """
    annots = page.get(pikepdf.Name.Annots)
    if annots is None:
        return 0
    kept = [a for a in annots
            if not (a.get(pikepdf.Name.Subtype) == pikepdf.Name.Text
                    and pikepdf.Name.IRT in a
                    and pikepdf.Name.State not in a)]
    if len(kept) == len(annots):
        return 0
    page[pikepdf.Name.Annots] = pikepdf.Array(kept)
    return len(annots) - len(kept)


def one_page_with_edits(data, index: int, edits,
                        hide_replies: bool = False) -> "Optional[bytes]":
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

    if not edits and not hide_replies:
        return None
    try:
        with pikepdf.open(io.BytesIO(data)) as whole:
            if not 0 <= index < len(whole.pages):
                return None
            one = pikepdf.Pdf.new()
            one.pages.append(whole.pages[index])
            page = one.pages[0].obj
            changed = patch_page_marks(page, edits)
            if hide_replies:
                changed += drop_replies(page)
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
    #: `popup` is where the mark's window sits, which Reader remembers for
    #: a window that has been moved or resized. It belongs to the `/Popup`
    #: object rather than to the mark, and it is the one edit here that is
    #: geometry without being the mark's own.
    #:
    #: `contents` is the note a mark carries -- what Reader calls its pop-up
    #: note, and which is the mark's own `/Contents` rather than an
    #: annotation of its own. A reply *is* an annotation of its own and is
    #: not this; it gets an entry under its own index, because each reply is
    #: a mark that can be edited like any other.
    #:
    #: `quads` carries geometry, and geometry is the same problem as colour:
    #: `/QuadPoints` and `/Rect` are rewritten and the appearance dropped,
    #: while `/NM`, `/Popup`, `/RC` and the `/IRT` chains stay the
    #: producer's. A resized highlight is the same mark, with the same
    #: comment thread hanging off it.
    #: `deleted` is not a key rewrite like the other three -- it removes the
    #: annotation from `/Annots` entirely, along with the `/Popup` it owns.
    #: It is recorded here anyway, and per mark, because everything that has
    #: to honour it already reads this: the one-page re-render, the export,
    #: and undo, which restores by dropping the delta with nothing else to
    #: put back. A mark's status chain and its replies each get an entry of
    #: their own rather than being re-derived from the parent, so the chain
    #: is walked once, where the marks are, and not again in the writer.
    #: `rich` travels with `contents` and never alone: it is the same
    #: words with their styling, and a reader prefers it, so the two have
    #: to be written in one go or not at all.
    FIELDS = ("colour", "opacity", "quads", "deleted", "contents", "popup",
              "rich", "author", "subject", "locked", "style")

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
        # A reply is NoZoom and NoRotate as well as Print, as Reader writes
        # them: its icon is interface furniture anchored to the mark it
        # answers, so it keeps its size when the page is zoomed or turned.
        F=((UNSEEN if annotation.state
            else ANCHORED if annotation.irt else PRINTABLE)
           | (LOCKED if annotation.locked else 0)),
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
    if annotation.state:
        # `/StateModel` says which vocabulary `/State` is drawn from. Review
        # is the one Reader writes and the only one this offers; the other,
        # Marked, is a flag rather than a workflow.
        entry[pikepdf.Name.State] = pikepdf.String(annotation.state)
        entry[pikepdf.Name.StateModel] = pikepdf.String("Review")
    # What the form was given, else the name of the tool that made it,
    # which is what Acrobat starts every mark's subject as.
    # **Which tool made it**, where the subtype does not say by itself.
    # Two tools write `/Highlight` and are told apart by this: a plain
    # highlight has no `/IT`, and *Add note to text* has `/HighlightNote`.
    # Reader also writes `/IT /Underline` on a squiggly, so the mark reads
    # back as the Underline tool rather than as a kind of its own -- the
    # one place `/IT` names a tool a *different* subtype came from.
    intent = annotation.intent or INTENTS.get(annotation.kind)
    if intent:
        entry[pikepdf.Name.IT] = pikepdf.Name(intent)
    subject = annotation.subject or SUBJECTS.get(annotation.kind)
    if subject:
        entry[pikepdf.Name.Subj] = pikepdf.String(subject)
    if annotation.contents:
        # Only when there is something to say. Written unconditionally, an
        # uncommented highlight carries an empty `/Contents`, and a reader
        # that lists comments lists it -- an empty note against a mark whose
        # whole point was that it had nothing to add.
        entry[pikepdf.Name.Contents] = pikepdf.String(annotation.contents)
        # **And always the same words as `/RC`**, which is what a reader
        # that understands it will show. `/Contents` stays beside it as the
        # plain reading, for the ones that do not. A note that never
        # reached the editor has no runs to write, so it is composed from
        # the text -- bare for a status change, which is text this
        # application wrote, and spanned for anything somebody typed.
        entry[pikepdf.Name.RC] = pikepdf.String(
            annotation.rich or rich_from_text(
                annotation.contents, generated=bool(annotation.state)))
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
        # **Only when it is not 1.** Reader leaves the key out of a fully
        # opaque mark rather than writing one, highlights included, and an
        # absent `/CA` already means 1 to every reader.
        if solidity(annotation) != 1.0:
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


def swatch(name: str):
    """A palette colour by its untranslated name.

    So that a default can be *named* rather than written out as three
    numbers nobody can check. Raises rather than guessing: a colour that is
    not in the palette is a mistake, not a shade.
    """
    for known, colour in PALETTE:
        if known == name:
            return colour
    raise KeyError("no palette colour called %r" % name)


#: What a mark is made in when nobody has said otherwise and no tool
#: declares one. Every tool does declare one -- see `tools.Tool.colour`,
#: where the defaults live, per *tool* rather than per subtype -- so this is
#: the floor under a caller that has no tool at all.
DEFAULT_COLOUR = swatch("Red")


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
TRANSPARENCY = {HIGHLIGHT: 0.4, STRIKEOUT: 1.0,
                UNDERLINE: 1.0, SQUIGGLY: 1.0}


def opacity_of(mark) -> float:
    """How solid ``mark`` **is**, as the file says.

    **An absent `/CA` means 1.** It does not mean "whatever that kind is
    usually drawn at": Reader omits the key entirely on a fully opaque
    mark, highlights included -- measured on `Markup Highlight.pdf`, where
    the 100% one carries neither `/CA` nor a `ca` in its appearance's
    `ExtGState`, only the blend mode. Asking `solidity` instead read that
    highlight as 40%, and on a `Mark`, which has no `kind`, it raised.
    """
    opacity = getattr(mark, "opacity", None)
    return 1.0 if opacity is None else float(opacity)


def solidity(annotation) -> float:
    """``/CA`` for a mark being made: its own, or its kind's starting point.

    **Not the same question as `opacity_of`.** This one is a default for
    something new, which is why a highlight answers 0.4; that one is what
    a mark in a file actually is, where the same silence means 1.
    """
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


# **Every one of these is a fraction of the type's height**, which is the
# quadrilateral's. They were constants here once, lifted from a single
# 12.991pt line, and so were right on that line and nowhere else. Fitted
# instead across five corpus files and six text heights -- 9.45, 12.99,
# 13.34, 14.17, 14.56 and 15.77 points -- where each agrees to five
# figures. The one disagreement is a 13.343pt run given the 12.991pt
# scale, so Reader works from the font size it believes the run is, in
# steps of its own, rather than from the quadrilateral exactly.

#: How thick an underline or a cross-out is. Reader *strokes* both, so
#: this is the width of a line centred on the offsets below -- not the
#: height of a filled rectangle sitting on the quadrilateral's edge,
#: which is what was drawn here before and put the line half a width low.
STROKE_THICKNESS = 1.0 / 16.0

#: Where that stroke's centre sits above the quadrilateral's bottom edge.
#: An underline is below the baseline rather than on the edge of the box,
#: and a cross-out is below the middle of the type rather than through it.
UNDERLINE_OFFSET = 1.0 / 7.0
STRIKEOUT_OFFSET = 3.0 / 7.0

#: The squiggly's wave. Reader fills the run with a tiling pattern whose
#: tile is ten wide by twelve tall and strokes `0 1 -> 5 11 -> 10 1`, and
#: places it through a `cm` that is *anisotropic*: it scales x by 1.8
#: times what it scales y. So the wave that lands is a quarter of the
#: type's height per cycle and a sixth of it tall.
SQUIGGLE_SCALE = 1.0 / 72.0
SQUIGGLE_ASPECT = 1.8
#: Where the tile's own origin sits above the quadrilateral's bottom edge,
#: so the wave runs from a sixteenth of the height above that edge to an
#: eighth of it. Measured 0.2320 and 0.2319 against 12.991pt runs.
SQUIGGLE_BASE = 1.0 / 56.0
#: The tile, in its own space: how far one cycle runs, how low and how
#: high the wave turns, and the stroke it is drawn with.
SQUIGGLE_CYCLE = 10.0
SQUIGGLE_LOW = 1.0
SQUIGGLE_HIGH = 11.0
SQUIGGLE_PEN = 1.0


def _stroke(left, right, y, thickness) -> str:
    """One line across a run, stroked rather than filled.

    Reader strokes both the underline and the cross-out, so the line is
    centred on ``y`` and covers half a thickness either side of it. Filling
    a rectangle *from* ``y`` instead -- which is what this did -- draws the
    same line half a thickness too high, and no amount of adjusting the
    thickness hides that at a size other than the one it was fitted to.
    """
    return "{} w\n{} {} m\n{} {} l\nS".format(thickness, left, y, right, y)


def _zigzag(left, bottom, right, top) -> str:
    """The squiggly style, as a stroked path along the quadrilateral.

    **Reader fills the quad with a tiling pattern** whose tile strokes
    `0 1 -> 5 11 -> 10 1` over ten points, repeating every ten. The wave is
    reproduced here as one path instead: a pattern would have to be a
    resource of the stream, and the shape it draws is six numbers.

    **Scaled to the type, not fixed.** The tile is placed through a `cm`
    that is a fraction of the run's height, so a wave on small print is a
    small wave -- which a pair of constants in points could not be, and was
    not: the one fitted to a 12.991pt line was half again too tall on the
    15.77pt heading two pages later.

    The pen is the awkward part. Reader's tile strokes `1 w` and is placed
    through a scale that is 1.8 times wider than it is tall, which strokes
    a line whose width varies with its direction. One number has to stand
    in for that, and the geometric mean of the two scales is what a
    rasteriser arrives at for a line running diagonally -- which is the
    whole of this wave.
    """
    height = top - bottom
    up = height * SQUIGGLE_SCALE
    along = up * SQUIGGLE_ASPECT
    base = bottom + height * SQUIGGLE_BASE
    low, high = base + up * SQUIGGLE_LOW, base + up * SQUIGGLE_HIGH
    cycle = along * SQUIGGLE_CYCLE
    pen = SQUIGGLE_PEN * math.sqrt(along * up)
    steps = ["{} w 1 J 1 j".format(pen), "{} {} m".format(left, low)]
    at = left
    while at < right:
        peak = min(at + cycle / 2.0, right)
        steps.append("{} {} l".format(peak, high))
        at = at + cycle
        if min(at, right) <= peak:
            # The run ended on a rise. Stopping here rather than adding a
            # trough at the same x, which draws a vertical tick.
            break
        steps.append("{} {} l".format(min(at, right), low))
    steps.append("S")
    return "\n".join(steps)


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
    # Both colours: every other kind fills, and the squiggly strokes.
    drawing = ["/GS gs", "{} {} {} rg".format(*colour[:3]),
               "{} {} {} RG".format(*colour[:3])]
    for quad in annotation.quads:
        left, bottom, right, top = quad
        if annotation.kind in (STRIKEOUT, UNDERLINE):
            # **Three sevenths of the way up for a cross-out, one seventh
            # for an underline, a sixteenth of the height thick, stroked.**
            # Not the middle of the box and not its bottom edge: Reader
            # draws both relative to the type, which is why these are
            # fractions rather than the points they used to be.
            height = top - bottom
            above = (STRIKEOUT_OFFSET if annotation.kind == STRIKEOUT
                     else UNDERLINE_OFFSET)
            drawing.append(_stroke(left, right, bottom + height * above,
                                   height * STROKE_THICKNESS))
        elif annotation.kind == SQUIGGLY:
            drawing.append(_zigzag(left, bottom, right, top))
        else:
            drawing.append("{} {} {} {} re f".format(
                left, bottom, right - left, top - bottom))
    stream = pikepdf.Stream(pdf, "\n".join(drawing).encode())
    stream[pikepdf.Name.Type] = pikepdf.Name.XObject
    stream[pikepdf.Name.Subtype] = pikepdf.Name.Form
    stream[pikepdf.Name.BBox] = pikepdf.Array([*annotation.rect])
    # The blend mode always, the alpha only when it is not 1 -- Reader's
    # fully opaque highlight carries `BM /Multiply` and nothing else.
    graphics = pikepdf.Dictionary(
        BM=(pikepdf.Name.Multiply if annotation.kind == HIGHLIGHT
            else pikepdf.Name.Normal))
    if solidity(annotation) != 1.0:
        graphics[pikepdf.Name.ca] = solidity(annotation)
    stream[pikepdf.Name.Resources] = pikepdf.Dictionary(
        ExtGState=pikepdf.Dictionary(GS=graphics))
    return pdf.make_indirect(stream)


def bounding_rect(quads) -> "tuple":
    """The box that contains every quad, which is what `/Rect` must be."""
    lefts = [q[0] for q in quads]
    bottoms = [q[1] for q in quads]
    rights = [q[2] for q in quads]
    tops = [q[3] for q in quads]
    return (min(lefts), min(bottoms), max(rights), max(tops))


#: The window a viewer opens to show a mark's note, in points. Measured on
#: 44 of Reader's own: 184 by 92, its left edge exactly at the page width --
#: parked *off* the page, to the right -- and its top aligned with the
#: parent's top. Nothing is clamped: where the mark sits low on the page,
#: Reader writes a popup whose bottom is negative.
POPUP_SIZE = (184.0, 92.0)


def popup_for(pdf, mark, rect, page_width: float,
              placed=None) -> pikepdf.Dictionary:
    """The `/Popup` object for ``mark``, placed the way Reader places one.

    **A popup is written whether or not the mark has a note.** It holds no
    text -- the words are the mark's `/Contents` -- and draws nothing; it is
    the window a viewer opens, and Reader gives one to every mark it makes.
    The proof is a highlight in the corpus that has never been commented and
    carries one anyway.

    Indirect and pointing back at the mark, which is why this takes the mark
    rather than making it: the two reference each other, so the mark has to
    exist first.
    """
    width, height = POPUP_SIZE
    top = float(rect[3])
    where = ([float(v) for v in placed] if placed else
             [page_width, top - height, page_width + width, top])
    return pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Popup,
        Rect=pikepdf.Array(where),
        # Print, NoZoom and NoRotate, as Reader writes them. Not Hidden: a
        # popup is not drawn in the page either way, and Reader leaves the
        # bit alone even on the window of a hidden status change.
        F=28,
        Open=False,
        Parent=mark,
    ))


def _popup_is_open(annot) -> bool:
    """Whether this mark's window was showing when the file was saved."""
    try:
        popup = annot.get(pikepdf.Name.Popup)
        return bool(popup is not None and popup.get(pikepdf.Name.Open, False))
    except Exception:  # noqa: BLE001 - an unreadable popup is a closed one
        return False


def _popup_rect(annot):
    """Where this mark's window sits, if it has one. Reader remembers a
    window that has been moved or resized by writing it here."""
    try:
        popup = annot.get(pikepdf.Name.Popup)
        if popup is None:
            return None
        raw = popup.get(pikepdf.Name.Rect)
        return tuple(_number(v, 0.0) for v in raw) if raw is not None else None
    except Exception:  # noqa: BLE001 - a mark without a readable window
        return None


def _named(page, name: str):
    """The annotation on ``page`` whose `/NM` is ``name``, or None."""
    for annot in (getattr(page, "obj", page).get(pikepdf.Name.Annots) or []):
        try:
            if pikepdf.Name.NM in annot and str(annot[pikepdf.Name.NM]) == name:
                return annot
        except Exception:  # noqa: BLE001 - an unreadable neighbour is not it
            continue
    return None


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
    media = [float(v) for v in target.get(pikepdf.Name.MediaBox,
                                          [0, 0, 612, 792])]
    for annotation in marks:
        placed = scaled(annotation, factor)
        entry = to_dictionary(pdf, placed, page=target)
        if pikepdf.Name.Annots not in page:
            page[pikepdf.Name.Annots] = pdf.make_indirect(pikepdf.Array([]))
        page[pikepdf.Name.Annots].append(entry)
        # Its window, which goes in `/Annots` beside it and is pointed at
        # from it. Written for every mark, commented or not, because that is
        # what Reader writes.
        if placed.irt:
            # Resolved here rather than in `to_dictionary`, because it points
            # at *another annotation on this page* and only the page knows
            # which: the mark answered may be one the file brought, written
            # long before this one existed.
            answered = _named(page, placed.irt)
            if answered is not None:
                entry[pikepdf.Name.IRT] = answered
        window = popup_for(pdf, entry, placed.rect, media[2],
                           placed.popup_rect)
        entry[pikepdf.Name.Popup] = window
        page[pikepdf.Name.Annots].append(window)
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

#: `/F` bit 8. **Locked**: the annotation's attributes and its own text are
#: not to be changed. Measured on a highlight locked in Acrobat, whose `/F`
#: went from 4 to 132, and on a reply, 28 to 156. The separate
#: `LockedContents` bit (512) is not used by Acrobat and is not read here.
#:
#: It is per annotation, so a locked mark leaves its replies editable and a
#: locked reply sits in a thread whose other items are not.
LOCKED = 128


class Mark:
    """One annotation the document already had, as this application sees it.

    Deliberately *not* an `Annotation`. That is the overlay of what the user
    made; this is a reading of what was there, and the dictionary it was read
    from stays the source of truth for every key nobody has touched.
    """

    __slots__ = ("uid", "page", "index", "subtype", "rect", "quads", "colour",
                 "opacity", "contents", "author", "name", "parent", "state",
                 "hidden", "when", "popup_open", "popup_rect", "rich",
                 "locked", "subject")

    def __init__(self, page, subtype, rect, quads=(), colour=None,
                 opacity=None, contents="", name=None, parent=None,
                 state=None, hidden=False, index=-1, author="", when="",
                 popup_open=False, popup_rect=None, rich="", locked=False,
                 subject=""):
        self.uid = next(_mark_uids)
        #: Where this mark sits among the markup annotations on its page, in
        #: the order the file has them. What `MarkEdits` keys an edit by, and
        #: the one thing about a mark that export can find again: it reads
        #: the same pages with the same enumeration.
        self.index = index
        #: Whether the window on this mark was showing when the file was
        #: saved, and where it was. A reader that honours `/Open` shows the
        #: thread rather than a summary, which is the one thing the flag is
        #: good for here.
        self.popup_open = popup_open
        self.popup_rect = popup_rect
        #: `/M` if the mark has one, else `/CreationDate`, as the file wrote
        #: it. Kept raw because a note's header shows it differently
        #: according to how old it is -- see `when_text`.
        self.when = when
        self.page = page
        self.subtype = subtype
        self.rect = tuple(rect)
        self.quads = tuple(tuple(q) for q in quads)
        self.colour = colour
        self.opacity = opacity
        self.contents = contents
        #: `/RC`, the rich version of `/Contents`, exactly as the file wrote
        #: it. Kept raw: `rich_to_html` is what turns it into something to
        #: draw, and a writer needs the original to know what it is
        #: replacing.
        self.rich = rich
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
        #: `/F` bit 8: the producer, or somebody using one, said this is not
        #: to be changed. Honoured rather than enforced -- the file cannot
        #: stop an editor, and this one chooses to be stopped.
        self.locked = locked
        #: `/Subj`, which Acrobat starts as the name of the tool that made
        #: the mark and the properties form can change to anything.
        self.subject = subject

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
        return has_note(self)

    def is_status(self) -> bool:
        return is_status(self)

    def is_reply(self) -> bool:
        return is_reply(self)

    def __repr__(self):  # pragma: no cover - debugging aid
        return (f"Mark({self.subtype}, page={self.page}, uid={self.uid}, "
                f"rect={self.rect})")


def _answers(mark):
    """What ``mark`` hangs off, whichever kind of mark it is.

    `Mark` reads `/IRT` into `parent` and `Annotation` holds the name it
    will be written as in `irt`, so a question asked of both has to look
    for either.
    """
    parent = getattr(mark, "parent", None)
    return parent if parent is not None else getattr(mark, "irt", None)


def is_status(mark) -> bool:
    """A review state recorded against something, rather than a mark."""
    return getattr(mark, "state", None) is not None


def is_reply(mark) -> bool:
    """An answer to another mark. A status change is not one."""
    return _answers(mark) is not None and not is_status(mark)


def has_note(mark) -> bool:
    """Whether ``mark`` carries a popup note of its own.

    Over either kind, because the badge has to be drawn on the marks this
    application made as well as the ones the file brought -- and the same
    question asked twice in two shapes is the same question answered two
    ways the first time one of them changes.
    """
    return bool(getattr(mark, "contents", "")) and _answers(mark) is None


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
                    rich=str(annot.get(pikepdf.Name.RC, "")),
                    subject=str(annot.get(pikepdf.Name.Subj, "")),
                    author=str(annot.get(pikepdf.Name.T, "")),
                    when=str(annot.get(pikepdf.Name.M,
                                       annot.get(pikepdf.Name.CreationDate,
                                                 ""))),
                    name=(str(annot[pikepdf.Name.NM])
                          if pikepdf.Name.NM in annot else None),
                    parent=(str(parent[pikepdf.Name.NM])
                            if parent is not None
                            and pikepdf.Name.NM in parent else None),
                    state=(str(annot[pikepdf.Name.State])
                           if pikepdf.Name.State in annot else None),
                    hidden=bool(int(annot.get(pikepdf.Name.F, 0)) & HIDDEN),
                    locked=bool(int(annot.get(pikepdf.Name.F, 0)) & LOCKED),
                    popup_open=_popup_is_open(annot),
                    popup_rect=_popup_rect(annot),
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

    def drop(self, marks) -> None:
        """Forget these marks, so nothing draws or hit-tests them again.

        A deleted mark is recorded in `MarkEdits` for the file that will be
        written, but the map was built from the document the reader is
        showing and still holds it. Re-reading the document would answer
        too, at the cost of rebuilding the reader -- 499 ms against the
        milliseconds a one-page re-render costs -- and undo rebuilds it
        anyway, which is what puts these back.
        """
        going = {id(mark) for mark in marks}
        for page, found in list(self._by_page.items()):
            left = [m for m in found if id(m) not in going]
            if left:
                self._by_page[page] = left
            else:
                del self._by_page[page]

    def __len__(self):
        return sum(len(v) for v in self._by_page.values())
