#!/usr/bin/env python3
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

"""How much of the interactive-form specification a set of PDFs exercises.

    python tools/form_coverage.py corpus/*.pdf

"Do we have enough test files?" is otherwise a matter of taste. The form part
of the specification is a closed list -- four field types, about twenty flag
bits, a handful of appearance shapes -- so it can be enumerated once and the
files measured against it. What comes back is which cells are covered, by which
file, and which are not: the uncovered ones are the only reason to go looking
for another PDF.

It measures the corpus, not this application. A covered cell means a real file
contains that construct, not that anything here handles it correctly.
"""

import collections
import os
import re
import sys

import pikepdf

#: Field-type-specific /Ff bits, numbered as the specification numbers them
#: (bit 1 is the low bit), with the type they belong to.
FLAGS = [
    ("any", 1, "read-only"),
    ("any", 2, "required"),
    ("any", 3, "no-export"),
    ("/Btn", 15, "no-toggle-to-off"),
    ("/Btn", 16, "radio"),
    ("/Btn", 17, "pushbutton"),
    ("/Btn", 26, "radios-in-unison"),
    ("/Tx", 13, "multiline"),
    ("/Tx", 14, "password"),
    ("/Tx", 21, "file-select"),
    ("/Tx", 24, "do-not-scroll"),
    ("/Tx", 25, "comb"),
    ("/Tx", 26, "rich-text"),
    ("/Ch", 18, "combo"),
    ("/Ch", 19, "editable"),
    ("/Ch", 20, "sorted"),
    ("/Ch", 22, "multi-select"),
]

#: Everything else worth knowing a real file does, as (group, cell).
STRUCTURE = [
    ("field type", "/Tx"), ("field type", "/Btn"),
    ("field type", "/Ch"), ("field type", "/Sig"),
    ("appearance", "none"), ("appearance", "stream"),
    ("appearance", "state dictionary"), ("appearance", "down (/D)"),
    ("appearance", "rollover (/R)"),
    ("alignment", "left"), ("alignment", "centre"), ("alignment", "right"),
    ("font size", "explicit"), ("font size", "auto (0 Tf)"),
    ("/DA", "on the widget"), ("/DA", "inherited"), ("/DA", "with a colour"),
    ("tree", "widget is the field"), ("tree", "kids on one page"),
    ("tree", "kids across pages"),
    ("names", "unique"), ("names", "shared by widgets"), ("names", "untitled"),
    ("document", "/NeedAppearances"), ("document", "/XFA hybrid"),
    ("document", "encrypted"),
    ("other", "/MaxLen"), ("other", "/Opt choices"),
    ("other", "hidden (/F bit 2)"), ("other", "/MK characteristics"),
]


def root_of(annot):
    node, depth = annot, 0
    while "/Parent" in node and depth < 8:
        node = node.Parent
        depth += 1
    return node


def qualified(annot):
    parts, node, depth = [], annot, 0
    while node is not None and depth < 8:
        if "/T" in node:
            parts.append(str(node.T))
        node = node.get("/Parent")
        depth += 1
    return ".".join(reversed(parts))


def inherited(annot, key):
    """``(value, where)`` for a key the field tree inherits down."""
    node, depth = annot, 0
    while node is not None and depth < 8:
        if key in node:
            return node[key], ("on the widget" if depth == 0 else "inherited")
        node = node.get("/Parent")
        depth += 1
    return None, None


def measure(path, hit):
    """Record every cell this file exercises. ``hit(group, cell)``."""
    try:
        pdf = pikepdf.open(path)
    except pikepdf.PasswordError:
        hit("document", "encrypted")
        return
    acroform = pdf.Root.get("/AcroForm")
    if acroform is None:
        return
    if acroform.get("/NeedAppearances"):
        hit("document", "/NeedAppearances")
    if "/XFA" in acroform:
        hit("document", "/XFA hybrid")
    if pdf.is_encrypted:
        hit("document", "encrypted")

    pages_of = collections.defaultdict(set)
    names = collections.Counter()
    for index, page in enumerate(pdf.pages):
        for annot in page.get("/Annots", []):
            if annot.get("/Subtype") != "/Widget":
                continue
            name = qualified(annot)
            if name:
                names[name] += 1
                pages_of[name].add(index)
            else:
                hit("names", "untitled")

            # /FT is inherited, and in a deep tree it sits on neither the
            # widget nor the root but somewhere between: a radio group in
            # sf86.pdf keeps it two levels up, under three naming subforms.
            # Reading it off the root reported those 1053 radios as typeless
            # and showed the specification's commonest button as uncovered.
            kind, _ = inherited(annot, "/FT")
            kind = str(kind) if kind is not None else "None"
            if kind in ("/Tx", "/Btn", "/Ch", "/Sig"):
                hit("field type", kind)

            flags, _ = inherited(annot, "/Ff")
            flags = int(flags or 0)
            for owner, bit, label in FLAGS:
                if owner in ("any", kind) and flags & (1 << (bit - 1)):
                    hit(f"flag {owner}", label)

            appearance = annot.get("/AP")
            if appearance is None:
                hit("appearance", "none")
            else:
                normal = appearance.get("/N")
                if isinstance(normal, pikepdf.Stream):
                    hit("appearance", "stream")
                elif isinstance(normal, pikepdf.Dictionary):
                    hit("appearance", "state dictionary")
                if "/D" in appearance:
                    hit("appearance", "down (/D)")
                if "/R" in appearance:
                    hit("appearance", "rollover (/R)")

            quadding, _ = inherited(annot, "/Q")
            hit("alignment", {0: "left", 1: "centre", 2: "right"}.get(
                int(quadding or 0), "left"))

            da, where = inherited(annot, "/DA")
            da = str(da) if da is not None else str(acroform.get("/DA") or "")
            if where:
                hit("/DA", where)
            size = re.search(r"([\d.]+)\s+Tf", da)
            if size:
                hit("font size",
                    "auto (0 Tf)" if float(size.group(1)) == 0 else "explicit")
            if re.search(r"\b(rg|g|k)\b", da) and not re.search(r"\b0 g\b", da):
                hit("/DA", "with a colour")

            if "/Parent" not in annot:
                hit("tree", "widget is the field")
            if inherited(annot, "/MaxLen")[0] is not None:
                hit("other", "/MaxLen")
            if inherited(annot, "/Opt")[0] is not None:
                hit("other", "/Opt choices")
            if int(annot.get("/F", 0)) & 2:
                hit("other", "hidden (/F bit 2)")
            if "/MK" in annot:
                hit("other", "/MK characteristics")

    for name, count in names.items():
        hit("names", "shared by widgets" if count > 1 else "unique")
    for name, pages in pages_of.items():
        if len(pages) > 1:
            hit("tree", "kids across pages")
        elif names[name] > 1:
            hit("tree", "kids on one page")


def main(paths):
    covered = collections.defaultdict(set)
    for path in paths:
        measure(path, lambda group, cell, p=path: covered[(group, cell)].add(
            os.path.basename(p)))

    cells = list(STRUCTURE) + [(f"flag {owner}", label)
                               for owner, _bit, label in FLAGS]
    groups = []
    for group, cell in cells:
        if group not in groups:
            groups.append(group)

    done = sum(1 for key in cells if covered.get(key))
    print(f"{len(paths)} file(s), {done} of {len(cells)} cells covered "
          f"({done * 100 // len(cells)}%)\n")
    for group in groups:
        print(group)
        for g, cell in cells:
            if g != group:
                continue
            files = sorted(covered.get((g, cell), ()))
            mark = "yes" if files else " - "
            where = ", ".join(f[:-4] for f in files[:3])
            if len(files) > 3:
                where += f" +{len(files) - 3}"
            print(f"   {mark}  {cell:24} {where}")
        print()
    missing = [f"{g}: {c}" for g, c in cells if not covered.get((g, c))]
    if missing:
        print("Not exercised by any file here —")
        for item in missing:
            print(f"   {item}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
