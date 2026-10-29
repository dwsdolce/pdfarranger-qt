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

"""Making filled form fields visible.

A filled form opened here and came up blank. The answers were all in the file
-- 23 of them, each with an appearance stream ready to draw -- and no renderer
in this application would draw any of them.

Setting ``RenderFlag.Annotations`` does not fix it. PDFium excludes *widget*
annotations from page rendering by design: it draws the page, then leaves form
fields to a form-fill module (``FPDFDOC_InitFormFillEnvironment`` and
``FPDF_FFLDraw``) that QtPdf never initialises and does not expose. Measured on
one page carrying one annotation with the same appearance stream, differing
only in subtype: ``/Square`` draws with the flag, ``/Widget`` draws neither
with it nor without.

So the fix is to stop the annotation looking like a form field to the renderer.
Changing ``/Subtype`` from ``/Widget`` to ``/Stamp`` is the whole of it: the
appearance stream, its ``/Matrix``, its ``/BBox`` and the ``/AS`` that chooses a
tick box's state are all general annotation machinery, and PDFium applies the
specification's placement rules to any annotation it is willing to draw.

**Why not stamp the appearance into the page content**, which is the obvious
thing to write and what a "flatten" command would do. An appearance is placed
by transforming its BBox by its Matrix and fitting the result to the
annotation's Rect. Of the 74 appearances in the form this was built for, every
single one carried a Matrix and 45 had a BBox that did not match the Rect --
one of them 18.2pt tall in an 11.5pt box. Translating the stream to the corner
of the Rect, which is what the obvious implementation does, draws 61% of them
at the wrong size. Placing an appearance is the renderer's job, and PDFium
already does it correctly.

**This never reaches a saved file.** The rewritten document is for rendering
only: the grid, the reader and nothing else. Export reads the real copy, which
still has its widgets and, since the form dictionary is rebuilt there, still
has a working ``/AcroForm``.
"""

import os
import re
import tempfile
from typing import Dict, Optional, Tuple

import pikepdf


def has_widgets(pdf) -> bool:
    """Whether any page carries a form field with something to draw.

    The question the whole feature is gated on. A document with no fields --
    which is nearly all of them -- must not pay for a second copy, and D19's
    fast path into read mode has to survive untouched for those.
    """
    for page in pdf.pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            if (annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget
                    and pikepdf.Name.AP in annot):
                return True
    return False


def show_widgets(pdf) -> int:
    """Rewrite form fields so a page renderer will draw them. Returns how many.

    Only those with an appearance: one without is invisible in any viewer, and
    leaving it alone keeps this consistent with `has_widgets`.

    A hidden field stays hidden. Bit 2 of ``/F`` is honoured by the renderer
    for every annotation, so a field the document says not to show is still not
    shown -- which is correct, and would not be if the appearance were stamped
    into the page content instead.
    """
    changed = 0
    for page in pdf.pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            if (annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget
                    and pikepdf.Name.AP in annot):
                annot[pikepdf.Name.Subtype] = pikepdf.Name.Stamp
                changed += 1
    return changed


def rendered_copy(source: str, password: str, tmp_dir: str,
                  values: Optional[Dict[str, str]] = None) -> Optional[str]:
    """A copy of ``source`` whose fields will draw, or None if it has none.

    None rather than a copy of an unchanged file, so that the caller can go on
    using the original path and nothing is written for the documents that do
    not need it.

    ``values`` are written in first, so that what the grid's thumbnails draw is
    what has been filled in rather than what the file came with. The reader
    does not come here -- it draws the fields itself, over the page -- so this
    is for the renderers that cannot.
    """
    try:
        with pikepdf.open(source, password=password or "") as pdf:
            if not has_widgets(pdf):
                return None
            if values:
                apply_values(pdf.pages, values,
                             pdf.Root.get(pikepdf.Name.AcroForm), pdf)
            show_widgets(pdf)
            fd, path = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
            os.close(fd)
            pdf.save(path)
            return path
    except Exception:  # noqa: BLE001 - rendering falls back to the original
        return None


def rendered_bytes(data: bytes) -> bytes:
    """The same, for the export read mode builds when pages have been edited.

    Returns ``data`` unchanged when there is nothing to rewrite, so the caller
    can hand the result straight on without asking which it got.
    """
    try:
        import io

        with pikepdf.open(io.BytesIO(data)) as pdf:
            if not has_widgets(pdf):
                return data
            show_widgets(pdf)
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except Exception:  # noqa: BLE001 - rendering falls back to the original
        return data


class FormValues:
    """What the user has typed or ticked, and nothing else.

    A sparse overlay. The source document already holds the values it came
    with; this records only what has been *changed*, so an untouched form stores
    nothing, and undoing every edit leaves an empty overlay which is by
    definition the original document. The same shape as a `Page`, which holds a
    rotation and a crop rather than a copy of the page.

    **Keyed by document and fully qualified field name, never by page.** A value
    belongs to the field, and a field's widgets can sit on more than one page --
    the I-9 has such a field, though the insurance form that prompted this work
    has none of its 82 there. Key by page and there is no answer to which page
    owns the value, and duplicating a page would make two fields of one name
    hold two values, which PDF forbids: one qualified name is one field with one
    value, however many widgets draw it.

    Everything else then falls out. Reordering costs nothing, because nothing
    refers to position. Deleting a page leaves a value with no widget, which the
    export simply does not write, since `/Fields` is rebuilt from the widgets
    that survived -- dangling rather than destroyed, the same choice the outline
    makes for a bookmark whose page has gone, and undoable for the same reason.
    Duplicating a page gives one field two widgets and one value, which is what
    PDF says.

    A plain container, like `Outline`: it knows nothing about pikepdf or Qt, so
    what survives an edit can be tested without either.
    """

    __slots__ = ("_values",)

    def __init__(self, values=None):
        #: ``(nfile, qualified name) -> str``. For a text or choice field the
        #: string is its text; for a button it is the state name to show. The
        #: writer decides which PDF type that becomes, because that depends on
        #: the field and the field is not here.
        self._values: Dict[Tuple[int, str], str] = dict(values or {})

    def duplicate(self) -> "FormValues":
        """A copy, for the undo snapshot the page list is taking anyway."""
        return FormValues(self._values)

    def __bool__(self):
        return bool(self._values)

    def __len__(self):
        return len(self._values)

    def __eq__(self, other):
        if not isinstance(other, FormValues):
            return NotImplemented
        return self._values == other._values

    def get(self, nfile: int, name: str, default=None):
        """The edited value, or ``default`` when this field was never touched.

        The default matters: absent means "ask the document", not "empty". A
        field the user has deliberately emptied holds ``""``, which is an edit.
        """
        return self._values.get((nfile, name), default)

    def edited(self, nfile: int, name: str) -> bool:
        return (nfile, name) in self._values

    def set(self, nfile: int, name: str, value: str):
        self._values[(nfile, name)] = value

    def revert(self, nfile: int, name: str):
        """Forget an edit, so the document's own value applies again."""
        self._values.pop((nfile, name), None)

    def clear(self):
        self._values.clear()

    def items(self):
        """``((nfile, name), value)`` for every edit, in insertion order."""
        return self._values.items()

    def for_document(self, nfile: int) -> Dict[str, str]:
        """Every edit belonging to one source document, by qualified name."""
        return {name: value for (file, name), value in self._values.items()
                if file == nfile}

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"FormValues({len(self._values)} edited)"


class Field:
    """One widget, and the identity of the field it draws.

    A widget rather than a field, because a click lands on a widget: two of
    them can belong to one field, and ticking either sets the one value they
    share. `name` is what identifies the field; `rect` is where this particular
    drawing of it sits.
    """

    __slots__ = ("page", "rect", "name", "kind", "flags", "states", "value",
                 "hidden", "annot", "drawn", "rotation")

    def __init__(self, page, rect, name, kind, flags, states, value, hidden,
                 annot=None, drawn=False, rotation=0):
        self.page = page
        #: ``(left, bottom, right, top)`` in PDF points, y measured upward,
        #: **in the frame a reader lays the page out in** -- cropped, and
        #: turned by `/Rotate`. Not the frame the `/Rect` was written in.
        #:
        #: The two differ whenever a page carries a rotation, which scanned
        #: documents very often do and which this application's own Rotate
        #: command produces. Everything downstream of here works in viewport
        #: coordinates derived from the layout, and the layout shows the page
        #: turned, so a rectangle straight out of the file lands somewhere
        #: else entirely: mirrored across the page at 180 degrees.
        self.rect = rect
        #: The fully qualified name -- the ``/T`` chain from the root down.
        self.name = name
        #: ``/Tx``, ``/Btn``, ``/Ch`` or ``/Sig``.
        self.kind = kind
        self.flags = flags
        #: For a button, the states its appearance can draw, "/Off" excluded.
        self.states = states
        #: What the *document* says, before any edit of ours.
        self.value = value
        self.hidden = hidden
        #: The widget itself, for the layer that draws it. Opaque here: this
        #: class answers what a field *is*, and holding the object is what
        #: lets something else render it without reading the file twice.
        self.annot = annot
        #: Whether the file carries a drawing for this field. Most text fields
        #: do not even when they hold a value, so something has to decide
        #: between showing what is there and making what is missing.
        self.drawn = drawn
        #: The page's `/Rotate`, needed by whatever draws the appearance: the
        #: stream is written in the page's own frame, so it has to be turned
        #: by the same amount to come out the right way up.
        self.rotation = rotation

    # -- what the field is -------------------------------------------------

    @property
    def read_only(self) -> bool:
        return bool(self.flags & 1)

    @property
    def is_radio(self) -> bool:
        return self.kind == "/Btn" and bool(self.flags & (1 << 15))

    @property
    def is_pushbutton(self) -> bool:
        return self.kind == "/Btn" and bool(self.flags & (1 << 16))

    @property
    def is_checkbox(self) -> bool:
        return (self.kind == "/Btn" and not self.is_radio
                and not self.is_pushbutton)

    @property
    def fillable(self) -> bool:
        """Whether this is something a click should do anything with.

        A pushbutton runs an action rather than holding a value, a signature
        needs a certificate, and a read-only field is the document saying no.
        """
        return (not self.read_only and not self.is_pushbutton
                and not self.hidden and self.kind in ("/Tx", "/Btn", "/Ch"))

    def state_for(self, value: Optional[str]) -> Optional[str]:
        """Which appearance this *widget* shows when the field holds ``value``.

        A field has one value and may have many widgets. A tick box shows its
        on-state when the value names it and "/Off" otherwise, which is also
        what makes a radio group work: the value names one member's state, so
        that member draws itself on and every other draws itself off, without
        anything having to clear them.
        """
        if self.kind != "/Btn":
            return None             # not state-keyed; the one appearance
        if value is not None and value in self.states:
            return value
        return "/Off"

    def contains(self, x: float, y: float) -> bool:
        """Whether a point in PDF space, y upward, is on this widget."""
        left, bottom, right, top = self.rect
        return left <= x <= right and bottom <= y <= top

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Field({self.name!r}, {self.kind}, page {self.page})"


def _qualified(annot) -> str:
    parts, node, depth = [], annot, 0
    while node is not None and depth < _FIELD_DEPTH:
        if pikepdf.Name.T in node:
            parts.append(str(node[pikepdf.Name.T]))
        node = node.get(pikepdf.Name.Parent)
        depth += 1
    return ".".join(reversed(parts))


def _inherited(annot, key):
    """The nearest value of an inheritable key, walking up from the widget.

    Up from the widget and stopping at the first hit, not down from the root:
    `/FT` can sit between the two. In sf86.pdf it is two levels above the
    widget, under three naming subforms, and reading it off the root called
    1,053 radio buttons typeless.
    """
    node, depth = annot, 0
    while node is not None and depth < _FIELD_DEPTH:
        if key in node:
            return node[key]
        node = node.get(pikepdf.Name.Parent)
        depth += 1
    return None


#: How far up a field tree to look. Eight is past any real form and stops a
#: /Parent cycle in a damaged file spinning for ever.
_FIELD_DEPTH = 8


def signatures_in(pdf) -> "list[str]":
    """The qualified names of signature fields that have actually been signed.

    Signed means a ``/V``. An empty ``/Sig`` field is a *placeholder* for a
    future signer and locks nothing: the insurance form that began this work
    carries two of them and is perfectly fillable.
    """
    found, seen = [], set()

    def walk(node, prefix="", depth=0):
        if depth > _FIELD_DEPTH:
            return
        name = (str(node[pikepdf.Name.T])
                if pikepdf.Name.T in node else "")
        qualified = f"{prefix}.{name}" if prefix and name else (name or prefix)
        kids = node.get(pikepdf.Name.Kids)
        if kids is not None and any(
                pikepdf.Name.T in kid or pikepdf.Name.Kids in kid
                for kid in kids):
            for kid in kids:
                walk(kid, qualified, depth + 1)
            return
        if _inherited(node, pikepdf.Name.FT) != pikepdf.Name.Sig:
            return
        if node.get(pikepdf.Name.V) is None:
            return
        if qualified not in seen:
            seen.add(qualified)
            found.append(qualified)

    try:
        acroform = pdf.Root.get(pikepdf.Name.AcroForm)
        fields = (acroform.get(pikepdf.Name.Fields, [])
                  if acroform is not None else [])
        for field in fields:
            walk(field)
    except Exception:  # noqa: BLE001 - an unreadable tree is not a signature
        return found
    return found


def is_signed(pdf) -> bool:
    """Whether this document carries a signature that saving would break.

    Two things count. A ``/Sig`` field with a ``/V``: something has been
    signed. ``/Perms /DocMDP``: a certification, which also carries the
    permission level its author set.

    Three plausible ones deliberately do not, each measured against the
    corpus. **``/SigFlags``** is a hint about what the file contains and real
    forms set it wrongly -- five of them declare AppendOnly while holding no
    signature field at all, and the insurance form declares SignaturesExist
    with two empty placeholders. **``/Perms /UR3``** is a usage-rights
    signature, which Reader-enables a form rather than attesting to its
    content; refusing on it would refuse to fill the 1040, the W-4, the W-9,
    the 1099-MISC and SF-3107. **An empty ``/Sig`` field** is an invitation to
    sign, not a signature.

    Asked of the *source* document, never of what the reader shows. The reader
    is shown an export, and export strips the remains of a signature rather
    than carrying them, so by then there is nothing left to find.
    """
    try:
        perms = pdf.Root.get(pikepdf.Name.Perms)
        if perms is not None and pikepdf.Name.DocMDP in perms:
            return True
    except Exception:  # noqa: BLE001 - a damaged root is not a certification
        return False
    return bool(signatures_in(pdf))


def displayed_box(page) -> "tuple[float, float, float, float, int]":
    """``(left, bottom, width, height, rotation)`` as a reader lays the page out.

    The same rule as `core._displayed_size`, and it has to be: the canvas sizes
    its pages from there, so a rectangle has to be expressed against the same
    box or it is measured from a different origin. The CropBox where there is
    one, clipped to the MediaBox because a CropBox outside it means nothing.
    """
    try:
        media = [float(v) for v in page.mediabox]
        box = [float(v) for v in page.cropbox]
    except Exception:           # noqa: BLE001 - a page without usable boxes
        return (0.0, 0.0, 0.0, 0.0, 0)
    left = max(min(box[0], box[2]), min(media[0], media[2]))
    bottom = max(min(box[1], box[3]), min(media[1], media[3]))
    right = min(max(box[0], box[2]), max(media[0], media[2]))
    top = min(max(box[1], box[3]), max(media[1], media[3]))
    try:
        rotation = int(page.obj.get(pikepdf.Name.Rotate, 0) or 0) % 360
    except Exception:           # noqa: BLE001 - a rotation we cannot read
        rotation = 0
    return (left, bottom, abs(right - left), abs(top - bottom),
            rotation - rotation % 90)


def to_displayed(rect, box) -> "tuple[float, float, float, float]":
    """A ``/Rect`` from the file, in the frame the page is laid out in.

    A ``/Rect`` is written in the page's own space. `/Rotate` says how far
    clockwise a reader turns the page before showing it, so the two frames
    agree only at zero -- and disagree most visibly at 180, where a rectangle
    taken straight from the file lands mirrored across both axes.

    Derived from where the corners go rather than from a matrix, because there
    are only four cases and each one is checkable by eye: turning a sheet
    clockwise sends its bottom-left corner to the top-left.
    """
    left, bottom, width, height, rotation = box
    x0, y0 = rect[0] - left, rect[1] - bottom
    x1, y1 = rect[2] - left, rect[3] - bottom
    if rotation == 90:
        corners = ((y0, width - x0), (y1, width - x1))
    elif rotation == 180:
        corners = ((width - x0, height - y0), (width - x1, height - y1))
    elif rotation == 270:
        corners = ((height - y0, x0), (height - y1, x1))
    else:
        corners = ((x0, y0), (x1, y1))
    (ax, ay), (bx, by) = corners
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def fields_in(pdf) -> "list[Field]":
    """Every widget in a document, in page order then drawing order.

    Read from the document the *reader is showing*, so the rectangles are in
    the coordinates on screen: a rotated or cropped page has already been
    through the export by then, and asking the source would give a rectangle
    in a space nothing is drawn in.
    """
    found = []
    for index, page in enumerate(pdf.pages):
        box = displayed_box(page)
        for annot in page.get(pikepdf.Name.Annots, []):
            # Widgets only. `/Stamp` was accepted here while body 1 showed the
            # reader the copy with the widgets rewritten into stamps; it is
            # shown the export or the source file now, both of which carry
            # real widgets, so all the exception still caught was *genuine*
            # stamps. Two documents in the corpus have one -- Apple's markup
            # titles everything it writes with the device's user name -- and
            # each surfaced as a phantom field named "Mobile User".
            if annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Widget:
                continue
            name = _qualified(annot)
            if not name:
                continue            # nothing to key a value on
            kind = _inherited(annot, pikepdf.Name.FT)
            rect = [float(v) for v in annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
            states = []
            appearance = annot.get(pikepdf.Name.AP)
            normal = appearance.get(pikepdf.Name.N) if appearance else None
            drawn = normal is not None
            if isinstance(normal, pikepdf.Dictionary) and not isinstance(
                    normal, pikepdf.Stream):
                states = [str(k) for k in normal.keys() if str(k) != "/Off"]
            value = _inherited(annot, pikepdf.Name.V)
            found.append(Field(
                page=index,
                rect=to_displayed(
                    (min(rect[0], rect[2]), min(rect[1], rect[3]),
                     max(rect[0], rect[2]), max(rect[1], rect[3])), box),
                name=name,
                kind=str(kind) if kind is not None else "None",
                flags=int(_inherited(annot, pikepdf.Name.Ff) or 0),
                states=states,
                value=str(value) if value is not None else None,
                hidden=bool(int(annot.get(pikepdf.Name.F, 0)) & 2),
                annot=annot, drawn=drawn, rotation=box[4]))
    return found


class FieldMap:
    """Which field is under a point, per page.

    Built once per document shown and kept, because a click asks on every
    press and a form can carry thousands of widgets -- sf86.pdf has 6,852.
    """

    __slots__ = ("_by_page", "_pdf")

    def __init__(self, fields=(), pdf=None):
        self._by_page: Dict[int, list] = {}
        #: The document the fields were read from, held *open*. The layer that
        #: draws them renders each appearance out of it, so closing it here
        #: would mean reading the file again for every widget on screen.
        self._pdf = pdf
        for item in fields:
            self._by_page.setdefault(item.page, []).append(item)

    @classmethod
    def read(cls, source) -> "FieldMap":
        """From a path or bytes. An empty map if it cannot be read."""
        try:
            if isinstance(source, (bytes, bytearray)):
                import io

                pdf = pikepdf.open(io.BytesIO(source))
            else:
                pdf = pikepdf.open(source)
            return cls(fields_in(pdf), pdf)
        except Exception:  # noqa: BLE001 - a click simply finds nothing
            return cls()

    def close(self):
        """Let the document go. The fields are unusable afterwards."""
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:  # pragma: no cover - already gone
                pass
            self._pdf = None
        self._by_page.clear()

    def __len__(self):
        return sum(len(v) for v in self._by_page.values())

    @property
    def pdf(self):
        """The document the fields were read from, for rendering out of."""
        return self._pdf

    @property
    def acroform(self):
        """Its form dictionary, which holds the fonts a `/DA` names."""
        if self._pdf is None:
            return None
        try:
            return self._pdf.Root.get(pikepdf.Name.AcroForm)
        except Exception:  # pragma: no cover - a document without one
            return None

    def on_page(self, page: int) -> list:
        return self._by_page.get(page, [])

    def at(self, page: int, x: float, y: float) -> Optional[Field]:
        """The widget under a point in PDF space, y upward, or None.

        Last match wins: annotations are drawn in array order, so the one
        later in the array is the one on top, and that is the one a click
        should reach.
        """
        found = None
        for item in self._by_page.get(page, ()):
            if item.contains(x, y):
                found = item
        return found


def _field_node(annot):
    """The node a value belongs on: the nearest ancestor carrying ``/FT``.

    Not the widget and not the root. A value lives on the field, and in a deep
    tree the field sits between the two -- which is the same lesson `fields_in`
    learned, and the same one that made a coverage tool call 1,053 radio
    buttons typeless.
    """
    node, depth = annot, 0
    while node is not None and depth < _FIELD_DEPTH:
        if pikepdf.Name.FT in node:
            return node
        node = node.get(pikepdf.Name.Parent)
        depth += 1
    return annot


def apply_values(pages, values: Dict[str, str], acroform=None,
                 pdf=None) -> int:
    """Write ``{qualified name: value}`` into some pages. Returns how many.

    ``pdf`` is the document those pages belong to, needed because a generated
    appearance stream must be created in the file it will be drawn from and a
    pikepdf object will not say which that is.

    Pages rather than a document, because a name identifies a field only
    within the document it came from. An export can hold pages from several,
    so the caller applies one source's values to that source's pages and no
    others.

    Buttons only, for now: their appearance for every state is already in the
    file, so setting the value and the state a widget shows is the whole of it
    and nothing has to be drawn. A text field needs an appearance generated,
    which is a different piece of work.

    ``/V`` goes on the field and ``/AS`` on each widget, which is what makes a
    radio group behave: the value names one member's state, so that member
    draws itself on and the others draw themselves off, with nothing having to
    clear them.
    """
    written = 0
    for page in pages:
        for annot in page.get(pikepdf.Name.Annots, []):
            # Widgets only, for the reason given in `fields_in`. Nothing is
            # lost by it: the one caller that rewrites -- `rendered_copy` --
            # writes the values *before* `show_widgets`, while they are still
            # widgets.
            if annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Widget:
                continue
            name = _qualified(annot)
            if name not in values:
                continue
            kind = str(_inherited(annot, pikepdf.Name.FT))
            value = values[name]
            if kind in ("/Tx", "/Ch"):
                # Text has no ready-made drawing to choose between, so one is
                # made. Without it the value is in the file and invisible,
                # which is the fault this whole body of work began with.
                field_node = _field_node(annot)
                field_node[pikepdf.Name.V] = pikepdf.String(value)
                drawn = (text_appearance(pdf, annot, value, acroform)
                         if pdf is not None else None)
                if drawn is not None:
                    annot[pikepdf.Name.AP] = pikepdf.Dictionary(N=drawn)
                written += 1
                continue
            if kind != "/Btn":
                continue
            appearance = annot.get(pikepdf.Name.AP)
            normal = appearance.get(pikepdf.Name.N) if appearance else None
            states = ([str(k) for k in normal.keys()]
                      if isinstance(normal, pikepdf.Dictionary)
                      and not isinstance(normal, pikepdf.Stream) else [])
            # What this widget shows: the value when it names one of its own
            # states, and off otherwise.
            shown = value if value in states else "/Off"
            annot[pikepdf.Name.AS] = pikepdf.Name(shown)
            _field_node(annot)[pikepdf.Name.V] = pikepdf.Name(value)
            written += 1
    return written


#: A ``/DA`` is a tiny content stream: a font and size, then a colour. Only
#: those two matter here, and both are optional.
_DA_FONT = re.compile(r"/([^\s/]+)\s+([\d.]+)\s+Tf")
_DA_COLOUR = re.compile(r"((?:[\d.]+\s+){1,4})(g|rg|k)\b")

#: Inset of the text from the widget's edge, and of the clip from the BBox.
#: Both are what Acrobat writes.
_TEXT_INSET = 2.0
_CLIP_INSET = 1.0


def _escape(text: str) -> bytes:
    """A PDF literal string. The three characters that end one, escaped."""
    out = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return out.encode("latin-1", "replace")


def default_appearance(annot, acroform=None) -> tuple:
    """``(font name, size, colour operators)`` from the nearest ``/DA``.

    Inherited like everything else in a field tree, and falling back to the
    form's own. The colour is carried because it is part of the string and
    forms use it: four of the nine in the corpus write their fields in dark
    blue, and a generated appearance that ignores it puts black text in a form
    that expects blue.
    """
    da = _inherited(annot, pikepdf.Name.DA)
    if da is None and acroform is not None:
        da = acroform.get(pikepdf.Name.DA)
    da = str(da) if da is not None else ""
    font = _DA_FONT.search(da)
    colour = _DA_COLOUR.search(da)
    return (font.group(1) if font else "Helv",
            float(font.group(2)) if font else 0.0,
            (colour.group(0) if colour else "0 g"))


def _font_metrics(resources, name: str) -> tuple:
    """``(ascent, descent)`` as fractions of the size, or a usable guess.

    From the font's own descriptor where there is one. The fallback is the
    proportions of Helvetica, which is what a form naming a standard font
    means anyway and is close enough for the rest.
    """
    try:
        font = resources[pikepdf.Name.Font][pikepdf.Name("/" + name)]
        descriptor = font.get(pikepdf.Name.FontDescriptor)
        ascent = float(descriptor[pikepdf.Name.Ascent]) / 1000.0
        descent = float(descriptor[pikepdf.Name.Descent]) / 1000.0
        if ascent > 0 and descent < 0:
            return ascent, descent
    except Exception:  # noqa: BLE001 - any gap falls back
        pass
    return 0.718, -0.207


def text_baseline(height: float, size: float, ascent: float,
                  descent: float) -> float:
    """Where the text sits in a single-line field, centred the way Acrobat
    centres it.

    Derived from an appearance Acrobat itself wrote rather than guessed: a
    25.2pt box at 12pt in a font of ascent 989 and descent -360 put the
    baseline at 8.826, and this gives 8.826 exactly. An earlier version of
    this work used ``(height - size * 0.72) / 2 + size * 0.18``, which looks
    right at one size and drifts at others.
    """
    return (height - (ascent - descent) * size) / 2.0 - descent * size


def _string_width(resources, name: str, size: float, text: str):
    """How wide ``text`` is, or None when the font will not say.

    From the font's own ``/Widths``, which is the only honest source: a form's
    font is often a subset with its own metrics, and guessing from a standard
    table would be wrong by exactly the amount that makes centred text look
    wrong.
    """
    try:
        font = resources[pikepdf.Name.Font][pikepdf.Name("/" + name)]
        widths = font[pikepdf.Name.Widths]
        first = int(font[pikepdf.Name.FirstChar])
        total = 0.0
        for character in text.encode("latin-1", "replace"):
            index = character - first
            if not 0 <= index < len(widths):
                return None
            total += float(widths[index])
        return total / 1000.0 * size
    except Exception:  # noqa: BLE001 - no metrics is an answer, not a failure
        return None


def resources_for(annot, acroform=None):
    """The resource dictionary a generated appearance should name.

    The form's ``/DR`` where there is one -- that is what a ``/DA`` naming
    ``/Helv`` is referring to -- and otherwise whatever the widget's existing
    appearance used.
    """
    if acroform is not None:
        resources = acroform.get(pikepdf.Name.DR)
        if resources is not None:
            return resources
    existing = annot.get(pikepdf.Name.AP)
    normal = existing.get(pikepdf.Name.N) if existing else None
    if isinstance(normal, pikepdf.Stream):
        return normal.get(pikepdf.Name.Resources)
    return None


def text_appearance(pdf, annot, value: str, acroform=None, resources=None):
    """An appearance stream drawing ``value`` in ``annot``, or None.

    Single line, which is what a text field is unless it says otherwise. The
    shape is Acrobat's own, read out of a form it had filled: mark the content
    as a text field, clip to the box, set the font and colour from the ``/DA``,
    place the baseline, and show the string.

    Most text fields in real forms have **no** appearance to start from -- 0 of
    164 in one corpus form, 3 of 126 in another -- so this draws from nothing
    rather than editing what is there. Buttons are the opposite and need none
    of this: their drawings for every state are already in the file.
    """
    rect = [float(v) for v in annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
    width = abs(rect[2] - rect[0])
    height = abs(rect[3] - rect[1])
    if width <= 0 or height <= 0:
        return None
    if resources is None:
        resources = resources_for(annot, acroform)
    if resources is None:
        return None

    name, size, colour = default_appearance(annot, acroform)
    ascent, descent = _font_metrics(resources, name)
    if size <= 0:
        # Auto-size: the field says "fit it". Start from the box and come down
        # until the line fits, which is what a viewer does and what six to
        # eight per cent of real fields ask for.
        size = max(4.0, min(12.0, (height - 2 * _CLIP_INSET) / (ascent - descent)))
        measured = _string_width(resources, name, size, value)
        room = width - 2 * _TEXT_INSET
        if measured and measured > room > 0:
            size = max(4.0, size * room / measured)
    baseline = text_baseline(height, size, ascent, descent)

    # Left unless the field asks otherwise, and only when the font will say how
    # wide the string is -- a centred line placed from a guess is worse than a
    # left-aligned one that is right.
    x = _TEXT_INSET
    quadding = int(_inherited(annot, pikepdf.Name.Q) or 0)
    if quadding in (1, 2):
        measured = _string_width(resources, name, size, value)
        if measured is not None:
            spare = max(0.0, width - 2 * _TEXT_INSET - measured)
            x = _TEXT_INSET + (spare / 2.0 if quadding == 1 else spare)

    content = (
        b"/Tx BMC\nq\n"
        + f"{_CLIP_INSET} {_CLIP_INSET} "
          f"{width - 2 * _CLIP_INSET:.4f} {height - 2 * _CLIP_INSET:.4f} re\n"
          "W\nn\nBT\n".encode()
        + f"/{name} {size:g} Tf\n{colour}\n{x:.4f} {baseline:.4f} Td\n".encode()
        + b"(" + _escape(value) + b") Tj\nET\nQ\nEMC\n")

    stream = pikepdf.Stream(pdf, content)
    stream[pikepdf.Name.Type] = pikepdf.Name.XObject
    stream[pikepdf.Name.Subtype] = pikepdf.Name.Form
    stream[pikepdf.Name.BBox] = pikepdf.Array([0, 0, width, height])
    stream[pikepdf.Name.Resources] = resources
    return stream
