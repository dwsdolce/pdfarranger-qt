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


def rendered_copy(source: str, password: str, tmp_dir: str) -> Optional[str]:
    """A copy of ``source`` whose fields will draw, or None if it has none.

    None rather than a copy of an unchanged file, so that the caller can go on
    using the original path and nothing is written for the documents that do
    not need it.
    """
    try:
        with pikepdf.open(source, password=password or "") as pdf:
            if not has_widgets(pdf):
                return None
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
                 "hidden")

    def __init__(self, page, rect, name, kind, flags, states, value, hidden):
        self.page = page
        #: ``(left, bottom, right, top)`` in PDF points, y measured upward.
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


def fields_in(pdf) -> "list[Field]":
    """Every widget in a document, in page order then drawing order.

    Read from the document the *reader is showing*, so the rectangles are in
    the coordinates on screen: a rotated or cropped page has already been
    through the export by then, and asking the source would give a rectangle
    in a space nothing is drawn in.
    """
    found = []
    for index, page in enumerate(pdf.pages):
        for annot in page.get(pikepdf.Name.Annots, []):
            if annot.get(pikepdf.Name.Subtype) not in (
                    pikepdf.Name.Widget, pikepdf.Name.Stamp):
                continue
            name = _qualified(annot)
            if not name:
                continue            # nothing to key a value on
            kind = _inherited(annot, pikepdf.Name.FT)
            rect = [float(v) for v in annot.get(pikepdf.Name.Rect, [0, 0, 0, 0])]
            states = []
            appearance = annot.get(pikepdf.Name.AP)
            normal = appearance.get(pikepdf.Name.N) if appearance else None
            if isinstance(normal, pikepdf.Dictionary) and not isinstance(
                    normal, pikepdf.Stream):
                states = [str(k) for k in normal.keys() if str(k) != "/Off"]
            value = _inherited(annot, pikepdf.Name.V)
            found.append(Field(
                page=index,
                rect=(min(rect[0], rect[2]), min(rect[1], rect[3]),
                      max(rect[0], rect[2]), max(rect[1], rect[3])),
                name=name,
                kind=str(kind) if kind is not None else "None",
                flags=int(_inherited(annot, pikepdf.Name.Ff) or 0),
                states=states,
                value=str(value) if value is not None else None,
                hidden=bool(int(annot.get(pikepdf.Name.F, 0)) & 2)))
    return found


class FieldMap:
    """Which field is under a point, per page.

    Built once per document shown and kept, because a click asks on every
    press and a form can carry thousands of widgets -- sf86.pdf has 6,852.
    """

    __slots__ = ("_by_page",)

    def __init__(self, fields=()):
        self._by_page: Dict[int, list] = {}
        for item in fields:
            self._by_page.setdefault(item.page, []).append(item)

    @classmethod
    def read(cls, source) -> "FieldMap":
        """From a path or bytes. An empty map if it cannot be read."""
        try:
            if isinstance(source, (bytes, bytearray)):
                import io

                with pikepdf.open(io.BytesIO(source)) as pdf:
                    return cls(fields_in(pdf))
            with pikepdf.open(source) as pdf:
                return cls(fields_in(pdf))
        except Exception:  # noqa: BLE001 - a click simply finds nothing
            return cls()

    def __len__(self):
        return sum(len(v) for v in self._by_page.values())

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
