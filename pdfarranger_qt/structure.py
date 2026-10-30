# Copyright (C) 2026 pdfarranger-qt contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Carry a document's tagged structure through an export, or take the claim off.

The export composes a new document, so `/StructTreeRoot` -- which hangs off the
catalogue rather than off a page -- was left behind on every save. The pages
kept their `/Tabs` and their `/StructParents`, so the output went on declaring
that its tab order came from a structure that was no longer in the file: an
honest loss would be bad, a dangling claim is worse, because a checker and a
screen reader both believe it.

Copying the tree is not `copy_foreign` on the root. Every element names its
page in `/Pg`, so following the root would copy the *source* pages too, as
objects nothing points at, and leave `/Pg` aimed at those orphans rather than
at the pages the export actually wrote. The tree is rebuilt element by element
instead, with `/Pg` taken from a map of the pages that were copied.

What is not attempted is said plainly rather than half done. A page whose
content has been scaled is wrapped in a form XObject, which takes its marked
content with it and needs its own `/StructParents` entry; a document merged
from several sources would need its role maps reconciled; and a page that
appears twice cannot say which copy an element belongs to. In each of those
the claim is removed instead, which is what `_make_honest` is for.
"""

import pikepdf

#: How deep the tree is walked. Real documents nest six or seven levels; this
#: is far past that and stops a damaged file with a cycle in it spinning.
MAX_DEPTH = 64

#: Entries that are the element's own and are copied as they stand. `/K`,
#: `/P` and `/Pg` are rebuilt, and `/ID` is dropped with the `/IDTree`.
_SKIPPED = ("/K", "/P", "/Pg", "/ID")


def flatten_number_tree(node, into=None) -> dict:
    """A number tree's mappings, however it is split.

    `/ParentTree` is a number tree, and a real one is not a flat `/Nums`: the
    four page form measured here holds its 419 entries under `/Kids`, so a
    reader that only looks at `/Nums` finds nothing at all.
    """
    into = {} if into is None else into
    nums = node.get(pikepdf.Name.Nums)
    if nums is not None:
        for index in range(0, len(nums) - 1, 2):
            into[int(nums[index])] = nums[index + 1]
    for kid in node.get(pikepdf.Name.Kids, []):
        flatten_number_tree(kid, into)
    return into


def _make_honest(pdf_output) -> None:
    """Take off what claims a structure the output does not have.

    `/Tabs /S` says "tab order comes from the structure tree" and
    `/StructParents` is an index into a parent tree. With no tree both are
    promises about something absent, and a viewer or a checker will act on
    them. Removing them loses nothing that was working.

    Only `/S`. Row, column, article and widget order are all self-contained:
    they say nothing about a structure tree and go on meaning exactly what
    they meant. Taking those off as well threw away a working declaration --
    one corpus form orders its 196 widgets by row and said so.
    """
    for page in pdf_output.pages:
        if page.obj.get(pikepdf.Name.Tabs) == pikepdf.Name.S:
            del page.obj[pikepdf.Name.Tabs]
        if pikepdf.Name.StructParents in page.obj:
            del page.obj[pikepdf.Name.StructParents]
        for annot in page.get(pikepdf.Name.Annots, []):
            if pikepdf.Name.StructParent in annot:
                del annot[pikepdf.Name.StructParent]


def _eligible(pdf_input, pages) -> "tuple":
    """``(source, pdf)`` when the tree can be carried, or ``(None, None)``.

    One source, tagged, nothing scaled, no page used twice. Each exclusion is
    a thing this does not know how to do rather than a thing that cannot be
    done; see the module docstring.
    """
    if not pages:
        return (None, None)
    nfile = pages[0].nfile
    seen = set()
    for row in pages:
        if row.nfile != nfile or row.scale != 1 or row.layerpages:
            return (None, None)
        if row.npage in seen:
            return (None, None)
        seen.add(row.npage)
    if not 0 < nfile <= len(pdf_input):
        return (None, None)
    pdf = pdf_input[nfile - 1]
    if pdf is None or pikepdf.Name.StructTreeRoot not in pdf.Root:
        return (None, None)
    return (nfile, pdf)


class _Builder:
    """One pass over a source tree, writing the output's."""

    def __init__(self, source, output, page_map, annot_map):
        self.source = source
        self.output = output
        self.page_map = page_map
        self.annot_map = annot_map
        self.count = 0
        #: output page objgen -> {mcid: owning element}
        self.content = {}
        #: output annotation object -> owning element
        self.annotations = {}

    def _page_of(self, node):
        page = node.get(pikepdf.Name.Pg)
        if page is None:
            return None
        return self.page_map.get(page.objgen)

    def _copy_value(self, value):
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Array,
                              pikepdf.Stream)):
            return self.output.copy_foreign(self.source.make_indirect(value))
        return value

    def build(self, node, page, parent, depth=0):
        """An output element, or None when nothing of it survived."""
        if depth > MAX_DEPTH:
            return None
        if isinstance(node, pikepdf.Array):
            kids = [self.build(k, page, parent, depth + 1) for k in node]
            kids = [k for k in kids if k is not None]
            if not kids:
                return None
            return kids[0] if len(kids) == 1 else pikepdf.Array(kids)
        if isinstance(node, int):
            # A marked-content id, which means something only against a page.
            if page is None:
                return None
            self.content.setdefault(page.objgen, {})[int(node)] = parent
            return node
        if not isinstance(node, pikepdf.Dictionary):
            return None
        if node.get(pikepdf.Name.Type) == pikepdf.Name("/OBJR"):
            target = node.get(pikepdf.Name.Obj)
            copied = (self.annot_map.get(target.objgen)
                      if target is not None else None)
            if copied is None:
                return None          # its annotation did not survive
            self.annotations[copied.objgen] = parent
            entry = pikepdf.Dictionary(Type=pikepdf.Name("/OBJR"), Obj=copied)
            if page is not None:
                entry[pikepdf.Name.Pg] = page
            return self.output.make_indirect(entry)

        here = self._page_of(node) or page
        element = pikepdf.Dictionary()
        for key, value in node.items():
            if str(key) not in _SKIPPED:
                element[key] = self._copy_value(value)
        made = self.output.make_indirect(element)
        kids = node.get(pikepdf.Name.K)
        built = self.build(kids, here, made, depth + 1) if kids is not None \
            else None
        if kids is not None and built is None:
            return None              # every child was on a page that is gone
        if built is not None:
            element[pikepdf.Name.K] = built
        if here is not None:
            element[pikepdf.Name.Pg] = here
        if parent is not None:
            element[pikepdf.Name.P] = parent
        self.count += 1
        return made


def _resolve(pdf_output, page_map, annot_map) -> "tuple":
    """The trail's positions turned into the objects that are there now.

    Recorded as positions because `_apply_geom_transform` replaces every page
    after the copy; resolved here, once nothing more will move.
    """
    count = len(pdf_output.pages)
    resolved_pages = {}
    for objgen, index in page_map.items():
        if 0 <= index < count:
            resolved_pages[objgen] = pdf_output.pages[index].obj
    resolved_annots = {}
    for objgen, (index, at) in annot_map.items():
        if not 0 <= index < count:
            continue
        annots = pdf_output.pages[index].get(pikepdf.Name.Annots, [])
        if at < len(annots) and annots[at].is_indirect:
            resolved_annots[objgen] = annots[at]
    return resolved_pages, resolved_annots


def carry(pdf_input, pdf_output, pages, page_map, annot_map) -> int:
    """Rebuild the source's structure tree in the output.

    Returns how many elements were carried. Zero means the output was made
    honest instead: the claim is taken off rather than left pointing at
    nothing.
    """
    _nfile, source = _eligible(pdf_input, pages)
    if source is None:
        _make_honest(pdf_output)
        return 0
    page_map, annot_map = _resolve(pdf_output, page_map, annot_map)
    src_root = source.Root[pikepdf.Name.StructTreeRoot]
    builder = _Builder(source, pdf_output, page_map, annot_map)
    root = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot)
    new_root = pdf_output.make_indirect(root)
    top = builder.build(src_root.get(pikepdf.Name.K), None, new_root)
    if top is None:
        _make_honest(pdf_output)
        return 0
    root[pikepdf.Name.K] = top
    for key in (pikepdf.Name.RoleMap, pikepdf.Name.ClassMap):
        if key in src_root:
            root[key] = pdf_output.copy_foreign(
                source.make_indirect(src_root[key]))
    _write_parent_tree(pdf_output, root, builder)
    pdf_output.Root[pikepdf.Name.StructTreeRoot] = new_root
    return builder.count


def _write_parent_tree(pdf_output, root, builder) -> None:
    """The map back from a page or an annotation to its structure.

    Written flat. The source's own tree was split across `/Kids` because it
    had grown by revision; one written in a single pass has no reason to be,
    and a flat `/Nums` is what every reader handles first.

    The keys are assigned here rather than carried, because the source's are
    indices into *its* tree and the pages have been renumbered.
    """
    nums = []
    key = 0
    for page in pdf_output.pages:
        owners = builder.content.get(page.obj.objgen)
        if owners:
            highest = max(owners)
            entry = pikepdf.Array(
                [owners.get(mcid, pikepdf.Name("/Null"))
                 for mcid in range(highest + 1)])
            nums.extend([key, pdf_output.make_indirect(entry)])
            page.obj[pikepdf.Name.StructParents] = key
            key += 1
        elif pikepdf.Name.StructParents in page.obj:
            del page.obj[pikepdf.Name.StructParents]
        for annot in page.get(pikepdf.Name.Annots, []):
            owner = builder.annotations.get(annot.objgen)
            if owner is None:
                if pikepdf.Name.StructParent in annot:
                    del annot[pikepdf.Name.StructParent]
                continue
            nums.extend([key, owner])
            annot[pikepdf.Name.StructParent] = key
            key += 1
    root[pikepdf.Name.ParentTree] = pdf_output.make_indirect(
        pikepdf.Dictionary(Nums=pikepdf.Array(nums)))
    root[pikepdf.Name("/ParentTreeNextKey")] = key
