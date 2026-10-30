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
"""Step 2.10: a tagged document stays tagged, or stops claiming to be."""

import io
import unittest

import pikepdf
from support import temp_path

from pdfarranger_qt.structure import flatten_number_tree

OBJR = pikepdf.Name("/OBJR")


def tagged_form(pages=3, widgets_per_page=2):
    """A small tagged document: a heading and widgets, all in the tree.

    Built rather than taken from a fixture because the thing under test is
    the *shape* -- marked content on the page, `/OBJR` for the widgets, a
    `/ParentTree` keyed off `/StructParents` -- and a hand-built one can be
    read in full while a real government form cannot.
    """
    pdf = pikepdf.new()
    elements, nums, key = [], [], 0
    for index in range(pages):
        pdf.add_blank_page(page_size=(400, 400))
        page = pdf.pages[index]
        page.Contents = pdf.make_stream(
            b"/P <</MCID 0>> BDC BT ET EMC /P <</MCID 1>> BDC BT ET EMC")
        annots = []
        for n in range(widgets_per_page):
            annot = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
                FT=pikepdf.Name.Tx, T=pikepdf.String(f"f{index}_{n}"),
                Rect=pikepdf.Array([10, 10 + 40 * n, 200, 40 + 40 * n]), F=4))
            annots.append(annot)
        page.Annots = pdf.make_indirect(pikepdf.Array(annots))

        kids = [0, 1]
        for annot in annots:
            kids.append(pdf.make_indirect(pikepdf.Dictionary(
                Type=OBJR, Obj=annot, Pg=page.obj)))
        element = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name("/Sect"),
            Pg=page.obj, K=pikepdf.Array(kids)))
        elements.append(element)

        page.obj[pikepdf.Name.StructParents] = key
        nums.extend([key, pdf.make_indirect(
            pikepdf.Array([element, element]))])
        key += 1
        for annot in annots:
            annot[pikepdf.Name.StructParent] = key
            nums.extend([key, element])
            key += 1

    root = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructTreeRoot,
        K=pikepdf.Array(elements),
        ParentTree=pdf.make_indirect(
            pikepdf.Dictionary(Nums=pikepdf.Array(nums))),
        RoleMap=pikepdf.Dictionary(Sect=pikepdf.Name("/Div"))))
    root[pikepdf.Name("/ParentTreeNextKey")] = key
    pdf.Root[pikepdf.Name.StructTreeRoot] = root
    for page in pdf.pages:
        page.obj[pikepdf.Name.Tabs] = pikepdf.Name.S
    return pdf


def widget_order(pdf):
    """Every widget the structure tree names, in tree order, as rectangles."""
    where = {}
    for index, page in enumerate(pdf.pages):
        for annot in page.get(pikepdf.Name.Annots, []):
            if annot.is_indirect:
                where[annot.objgen] = (
                    index, tuple(round(float(v), 1) for v in annot.Rect))
    found, seen = [], set()

    def walk(node, depth=0):
        if depth > 60:
            return
        if isinstance(node, pikepdf.Array):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, pikepdf.Dictionary):
            return
        if node.get(pikepdf.Name.Type) == OBJR:
            target = node.get(pikepdf.Name.Obj)
            if target is not None and target.objgen in where \
                    and target.objgen not in seen:
                seen.add(target.objgen)
                found.append(where[target.objgen])
            return
        kids = node.get(pikepdf.Name.K)
        if kids is not None:
            walk(kids, depth + 1)

    walk(pdf.Root.StructTreeRoot.get(pikepdf.Name.K))
    return found


class StructureCase(unittest.TestCase):

    def exported(self, mutate=None, second=None):
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        source = temp_path("tagged.pdf")
        built = tagged_form()
        built.save(source)
        built.close()

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = list(docs.add_file(source))
        if second is not None:
            pages += list(docs.add_file(second))
        if mutate is not None:
            pages = mutate(pages)
        data = get_in_memory_pdf(list(pages), docs.files_for_export())
        out = pikepdf.open(io.BytesIO(data))
        self.addCleanup(out.close)
        return out

    def assertNothingDangles(self, pdf):
        """Every key a page or an annotation names must be in the tree."""
        root = pdf.Root.get(pikepdf.Name.StructTreeRoot)
        tree = flatten_number_tree(root[pikepdf.Name.ParentTree]) \
            if root is not None else {}
        for page in pdf.pages:
            if pikepdf.Name.StructParents in page.obj:
                self.assertIn(int(page.obj.StructParents), tree)
            for annot in page.get(pikepdf.Name.Annots, []):
                if pikepdf.Name.StructParent in annot:
                    self.assertIn(int(annot.StructParent), tree)


class TestATaggedDocumentStaysTagged(StructureCase):
    """The export composes a new document, so `/StructTreeRoot` -- which
    hangs off the catalogue, not off a page -- used to be left behind on
    every save. Measured on four real forms: tagged before, untagged after,
    while the pages went on declaring `/Tabs /S`.
    """

    def test_the_tree_arrives(self):
        out = self.exported()
        self.assertIn("/StructTreeRoot", out.Root)
        self.assertNothingDangles(out)

    def test_the_widgets_keep_their_order(self):
        """What `/Tabs /S` is *for*, and what step 2.11 needs from it."""
        source = tagged_form()
        self.addCleanup(source.close)
        self.assertEqual(widget_order(self.exported()), widget_order(source))

    def test_no_page_is_duplicated_by_copying_the_tree(self):
        """Every element names its page in `/Pg`, so following the root with
        `copy_foreign` would copy the source pages too, as objects nothing
        points at."""
        self.assertEqual(len(self.exported().pages), 3)

    def test_the_role_map_comes_too(self):
        """Without it a reader cannot tell what a custom tag means."""
        self.assertIn("/RoleMap", self.exported().Root.StructTreeRoot)

    def test_a_deleted_page_takes_its_structure_with_it(self):
        out = self.exported(mutate=lambda p: p[:1] + p[2:])
        self.assertEqual(len(out.pages), 2)
        self.assertEqual([page for page, _rect in widget_order(out)],
                         [0, 0, 1, 1])
        self.assertNothingDangles(out)

    def test_reordering_carries_the_tree(self):
        out = self.exported(mutate=lambda p: list(reversed(p)))
        self.assertIn("/StructTreeRoot", out.Root)
        self.assertNothingDangles(out)

    def test_the_parent_tree_is_rebuilt_against_the_new_pages(self):
        """The source's keys index *its* tree, and the pages have moved."""
        out = self.exported(mutate=lambda p: list(reversed(p)))
        tree = flatten_number_tree(out.Root.StructTreeRoot[
            pikepdf.Name.ParentTree])
        keys = [int(p.obj.StructParents) for p in out.pages]
        self.assertEqual(len(set(keys)), len(keys), "a key is used twice")
        for key in keys:
            self.assertIn(key, tree)


class TestWhatItWillNotDoItStopsClaiming(StructureCase):
    """An honest loss is bad; a dangling claim is worse, because a checker
    and a screen reader both believe it."""

    def assertHonest(self, pdf):
        self.assertNotIn("/StructTreeRoot", pdf.Root)
        for page in pdf.pages:
            self.assertNotEqual(page.obj.get(pikepdf.Name.Tabs),
                                pikepdf.Name.S)
            self.assertNotIn("/StructParents", page.obj)
            for annot in page.get(pikepdf.Name.Annots, []):
                self.assertNotIn("/StructParent", annot)

    def test_a_duplicated_page_cannot_say_which_copy_an_element_is_on(self):
        self.assertHonest(self.exported(mutate=lambda p: p + p[:1]))

    def test_a_scaled_page_moves_its_marked_content_into_an_xobject(self):
        def scale(pages):
            pages[0].scale = 0.5
            return pages

        self.assertHonest(self.exported(mutate=scale))

    def test_merging_two_documents_is_not_attempted(self):
        other = temp_path("other.pdf")
        built = tagged_form(pages=1)
        built.save(other)
        built.close()
        self.assertHonest(self.exported(second=other))

    def test_a_self_contained_tab_order_is_left_alone(self):
        """Row, column, article and widget order say nothing about a
        structure tree. Taking those off threw away a working declaration --
        one corpus form orders its 196 widgets by row and says so."""
        from pdfarranger_qt.structure import _make_honest

        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(400, 400))
        pdf.pages[0].obj[pikepdf.Name.Tabs] = pikepdf.Name.R
        self.addCleanup(pdf.close)
        _make_honest(pdf)
        self.assertEqual(pdf.pages[0].obj.Tabs, pikepdf.Name.R)


class TestTheParentTreeIsReadWhereverItIs(unittest.TestCase):
    """A real `/ParentTree` is not a flat `/Nums`: the four page form
    measured here holds its 419 entries under `/Kids`, so a reader that only
    looks at `/Nums` finds nothing at all."""

    def test_entries_under_kids_are_found(self):
        pdf = pikepdf.new()
        self.addCleanup(pdf.close)
        tree = pikepdf.Dictionary(Kids=pikepdf.Array([
            pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.String("a"),
                                                   1, pikepdf.String("b")])),
            pikepdf.Dictionary(Kids=pikepdf.Array([
                pikepdf.Dictionary(Nums=pikepdf.Array(
                    [2, pikepdf.String("c")]))])),
        ]))
        self.assertEqual(sorted(flatten_number_tree(tree)), [0, 1, 2])

    def test_a_flat_tree_still_works(self):
        tree = pikepdf.Dictionary(Nums=pikepdf.Array([7, pikepdf.String("x")]))
        self.assertEqual(list(flatten_number_tree(tree)), [7])
