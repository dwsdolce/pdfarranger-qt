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

"""Every markup tool, declared once.

The strip, its flyouts, the tick on the armed tool and -- later -- the tail of
attribute controls are all generated from this list. Nothing about a tool is
written twice, because using Reader turns up new attributes faster than they
can be designed and each one has to be a row here rather than a panel
somewhere.

**A declaration is not an implementation.** Every tool below can be armed and
none of them does anything yet: what a tool *makes* is decided one tool at a
time, starting at step 4.3, and a tool arrives with its gesture and its
attributes together. So there is no attribute column here. Adding twenty
tools' worth of attributes before building one would be deciding what nobody
is building.

Families are Reader's own grouping, which groups by **what the gesture is**
rather than by what the mark carries. That is why `Text callout` sits with the
shapes while `Add text comment` sits with the comments, though both write
`/FreeText`: the tool is the unit, and a family is not a subtype.

The signature family is not here. Reader offers stored signatures and
initials; this application does not sign, so there is no such tool.

Icons are Material Design Icons through ``qtawesome``, named as it names them.
The same set and the same library as the other Qt application in this family,
chosen there because Qt's own ``SP_*`` standard pixmaps render blank on macOS.
"""

from typing import List, NamedTuple

from .i18n import N_

#: Families, in strip order. The value is the msgid of the family's label,
#: shown as the flyout's heading and as the button's tooltip prefix.
POINTER = "pointer"
COMMENT = "comment"
TEXT_MARKUP = "text markup"
DRAWING = "drawing"

FAMILIES = (POINTER, COMMENT, TEXT_MARKUP, DRAWING)

#: Family labels, kept beside the identifiers rather than derived from them so
#: that a translator sees a word and not a key.
FAMILY_LABELS = {
    POINTER: N_("Pointer"),
    COMMENT: N_("Comment"),
    TEXT_MARKUP: N_("Text markup"),
    DRAWING: N_("Drawing"),
}


class Tool(NamedTuple):
    """One tool, as the strip needs to know it.

    ``name`` is the identifier used in code and settings and is never shown.
    ``label`` is the msgid the user sees. ``icon`` is a qtawesome name without
    its prefix. ``writes`` is what the tool will put in the file, carried here
    only so the declaration stays the single place a tool is described; it is
    documentation until the tool is built.

    ``colour`` is the name of the `markup.PALETTE` entry a mark of this tool
    is made in before anybody chooses otherwise. **A name, and per tool.**
    Read off Reader on 2026-11-04 from a document made after its settings
    were reset, so these are its own defaults rather than one user's habits,
    and made in Reader's own tool order so each annotation names its tool.
    Per tool rather than per subtype, because one subtype can carry two of
    them: `/Caret` starts Light Red for *Replace selected text* and Fuchsia
    for *Insert text*. Empty for a tool that makes no mark.
    """

    name: str
    family: str
    label: str
    icon: str
    writes: str = ""
    colour: str = "Red"
    #: `/Subj` and `/IT`, where a tool needs them to say which tool it was.
    #: **A subtype is not always a tool.** *Add note to text* writes a
    #: `/Highlight` like the Highlight tool and is told apart by these two:
    #: `/Subj Comment on Text` and `/IT /HighlightNote`, measured 2026-11-04
    #: on `Markup Underline Write.pdf`. Empty means the subtype's own
    #: subject and no intent.
    subject: str = ""
    intent: str = ""


#: Every tool, in the order each family shows them. Reader's order, which is
#: the order a user of Reader will look for them in.
TOOLS: List[Tool] = [
    Tool("select", POINTER, N_("Select"), "cursor-default-outline",
         colour=''),
    Tool("pan", POINTER, N_("Pan"), "hand-back-right-outline",
         colour=''),

    # **It writes two kinds.** An icon where it is clicked, and a
    # `/Highlight` over a run of selected words -- which is what the
    # right-click menu's *Add note to text* reaches. That second mark was
    # briefly a tool of its own here, in the strip, which it never was in
    # Reader. What it writes over words is `markup.COMMENT_ON_TEXT`.
    Tool("comment", COMMENT, N_("Add a comment"), "comment-plus-outline",
         "/Text with /Name, or /Highlight /IT /HighlightNote over words",
         colour='Purple'),
    # The comment tool's twin, and everything about them is shared but the
    # subtype: this one writes a `/Stamp`, which is ink on the page rather
    # than a marker fixed to it, so it scales, resizes and turns.
    Tool("scalable_comment", COMMENT, N_("Add a scalable comment"),
         "comment-plus", "/Stamp with /Name, or /Highlight over words",
         colour='Purple'),
    Tool("replace_text", COMMENT, N_("Replace selected text"), "find-replace",
         "/Caret /IT /Replace and /StrikeOut, joined by /IRT + /RT /Group",
         colour='Light Red'),
    Tool("insert_text", COMMENT, N_("Insert text"), "cursor-text",
         "/Caret",
         colour='Fuchsia'),
    Tool("text_comment", COMMENT, N_("Add text comment"), "text-box-outline",
         "/FreeText",
         colour='White'),
    Tool("attach_file", COMMENT, N_("Attach file"), "paperclip",
         "/FileAttachment, /Name /Paperclip, /FS /EF",
         colour='Red'),

    Tool("highlight", TEXT_MARKUP, N_("Highlight"), "format-color-highlight",
         "/Highlight, /QuadPoints, /CA",
         colour='Orange'),
    Tool("underline", TEXT_MARKUP, N_("Underline"), "format-underline",
         "/Underline, /QuadPoints",
         colour='Blue'),
    Tool("strikethrough", TEXT_MARKUP, N_("Strikethrough"),
         "format-strikethrough", "/StrikeOut, /QuadPoints",
         colour='Light Red'),

    Tool("draw", DRAWING, N_("Draw"), "draw", "/Ink, /InkList, /BS /W"),
    Tool("line", DRAWING, N_("Line"), "minus", "/Line, /L"),
    Tool("arrow", DRAWING, N_("Arrow"), "arrow-top-right",
         "/Line /IT /LineArrow, /LE [/None /OpenArrow], /BS /W"),
    Tool("rectangle", DRAWING, N_("Rectangle"), "square-outline", "/Square, /RD"),
    Tool("circle", DRAWING, N_("Circle"), "circle-outline", "/Circle, /RD"),
    Tool("callout", DRAWING, N_("Text callout"), "comment-text-outline",
         "/FreeText /IT /FreeTextCallout, /CL, /LE /OpenArrow",
         colour='White'),
    Tool("polygon", DRAWING, N_("Polygon"), "pentagon-outline",
         "/Polygon, /Vertices"),
    Tool("cloud", DRAWING, N_("Cloud"), "cloud-outline",
         "/Polygon /IT /PolygonCloud, /BE /I"),
    Tool("connected_lines", DRAWING, N_("Connected lines"), "vector-polyline",
         "/PolyLine, /Vertices"),
    Tool("stamps", DRAWING, N_("Stamps palette"), "stamper",
         "/Stamp, /Name, and an /AP we do not draw"),
]

#: The tool armed when there is nothing else to be armed. Reader's too: a
#: pointer is what a document does when nobody has asked for a tool.
DEFAULT = "select"

_BY_NAME = {tool.name: tool for tool in TOOLS}


def by_name(name: str) -> Tool:
    """The tool with this identifier. Raises for one that does not exist.

    Loudly, because a name that does not resolve is a typo in code and not a
    condition to recover from -- the alternative is a strip quietly missing a
    button.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no such tool: {name!r}") from None


def in_family(family: str) -> List[Tool]:
    """Every tool of one family, in the order the strip shows them."""
    return [tool for tool in TOOLS if tool.family == family]
