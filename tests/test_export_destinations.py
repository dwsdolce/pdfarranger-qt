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

"""Destinations must survive a save: bookmarks *and* link annotations.

Both defects these cover were found in a real document -- the ARRL 2021
Handbook, itself the product of a bad merge -- and neither was caught by the
existing fixtures, because those documents are too well-behaved. Every page
target resolves, so nothing is ever dropped and the failure modes never appear.
The fixture here is built to the shape that broke: a mixed tree of in-document
`/GoTo` bookmarks and external `/GoToR` ones, plus internal link annotations.
"""

import os
import unittest

import pikepdf

from pdfarranger_qt.core import DocumentSet
from pdfarranger_qt.export import export

from support import temp_path


def build_fixture(path, pages=6, link_target=None):
    """A document shaped like the one that exposed both bugs."""
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(612, 792))

    def item(title, action):
        return pdf.make_indirect(
            pikepdf.Dictionary(Title=pikepdf.String(title), A=action))

    def goto(page):
        return pikepdf.Dictionary(
            S=pikepdf.Name.GoTo,
            D=pikepdf.Array([pdf.pages[page].obj, pikepdf.Name.FitH, 792]))

    def gotor(page, target="Supplement.pdf"):
        """A link into another file -- what a bad merge leaves behind."""
        return pikepdf.Dictionary(
            S=pikepdf.Name.GoToR,
            F=pikepdf.Dictionary(Type=pikepdf.Name.Filespec,
                                 F=pikepdf.String(target),
                                 UF=pikepdf.String(target)),
            D=pikepdf.Array([page, pikepdf.Name.XYZ, 0, 792, 0]))

    def chain(items, parent):
        for n, entry in enumerate(items):
            entry.Parent = parent
            if n:
                entry.Prev = items[n - 1]
            if n + 1 < len(items):
                entry.Next = items[n + 1]
        parent.First, parent.Last = items[0], items[-1]
        parent.Count = len(items)

    roots = []
    for r in range(2):
        root = item(f"Part {r + 1}", goto(r * 3))
        book = item("The Handbook", gotor(0))
        sections = [item(f"{r + 1}.{s + 1} Section", gotor(s)) for s in range(3)]
        chain(sections, book)
        chain([book], root)
        roots.append(root)
    outlines = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
    chain(roots, outlines)
    pdf.Root.Outlines = outlines

    for n, page in enumerate(pdf.pages):
        target = pdf.pages[link_target if link_target is not None
                           else (n + 1) % len(pdf.pages)]
        page.obj.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 100, 100]),
            Dest=pikepdf.Array([target.obj, pikepdf.Name.Fit])))])

    pdf.save(path)
    return path


def outline_tree(path):
    """(title, action type, target file) triples, depth-first."""
    out = []
    with pikepdf.open(path) as pdf:
        with pdf.open_outline() as ol:
            def walk(items, depth):
                for entry in items:
                    action = entry.obj.get("/A")
                    kind = str(action.get("/S")) if action is not None else "/Dest"
                    # /GoTo and a bare /Dest are the same thing said two ways,
                    # and pikepdf writes the canonical /Dest form. Only the
                    # in-document/external distinction matters here.
                    if kind in ("/GoTo", "/Dest"):
                        kind = "internal"
                    target = ""
                    if action is not None and "/F" in action:
                        target = str(action["/F"].get("/F", ""))
                    out.append((depth, str(entry.title), kind, target))
                    walk(entry.children, depth + 1)
            walk(ol.root, 0)
    return out


def link_health(path):
    """(resolvable, broken, inert) counts for the link annotations."""
    with pikepdf.open(path) as pdf:
        pages = {p.obj.objgen for p in pdf.pages}
        good = bad = inert = 0
        for page in pdf.pages:
            for annot in page.obj.get("/Annots", []) or []:
                if str(annot.get("/Subtype")) != "/Link":
                    continue
                dest = annot.get("/Dest")
                if dest is None and "/A" in annot:
                    dest = annot["/A"].get("/D")
                if dest is None:
                    inert += 1
                elif (isinstance(dest, pikepdf.Array) and len(dest)
                        and getattr(dest[0], "objgen", None) in pages):
                    good += 1
                else:
                    bad += 1
        return good, bad, inert


class DestinationCase(unittest.TestCase):
    def setUp(self):
        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        self.source = build_fixture(temp_path("source.pdf"))

    def save(self, keep=None):
        pages = self.docs.add_file(self.source)
        chosen = pages if keep is None else [pages[i] for i in keep]
        out = temp_path("saved.pdf")
        export(self.docs.files_for_export(),
               [p.duplicate() for p in chosen], {}, [out])
        return out


class TestExternalBookmarksSurvive(DestinationCase):
    """`/GoToR` has no in-document destination, which is not the same as none.

    Treating the two alike deleted 18,131 of the 18,179 bookmarks in the ARRL
    Handbook and flattened its tree, because every entry below the top level
    was a cross-file link left over from a merge.
    """

    def test_the_whole_tree_survives(self):
        self.assertEqual(outline_tree(self.save()), outline_tree(self.source))

    def test_external_bookmarks_are_not_dropped(self):
        saved = outline_tree(self.save())
        external = [e for e in saved if e[2] == "/GoToR"]
        self.assertEqual(len(external), 8)

    def test_the_target_file_is_preserved(self):
        for _depth, _title, kind, target in outline_tree(self.save()):
            if kind == "/GoToR":
                self.assertEqual(target, "Supplement.pdf")

    def test_nesting_depth_is_preserved(self):
        saved = outline_tree(self.save())
        self.assertEqual([d for d, _t, _k, _f in saved],
                         [0, 1, 2, 2, 2, 0, 1, 2, 2, 2])

    def test_internal_bookmarks_still_resolve(self):
        """The /GoTo ones must still be remapped, not merely preserved."""
        saved = self.save()
        with pikepdf.open(saved) as pdf:
            pages = {p.obj.objgen for p in pdf.pages}
            with pdf.open_outline() as ol:
                for root in ol.root:
                    dest = root.destination
                    self.assertIsInstance(dest, pikepdf.Array)
                    self.assertIn(dest[0].objgen, pages)


class TestLinkAnnotationsAreRemapped(DestinationCase):
    """Copied links kept pointing at the source document's page objects.

    The `/Dest` array survived the copy with a null target, so every in-document
    link in every saved file did nothing, and PDFium reported "skipping link
    with invalid page number -1" for each one.
    """

    def test_the_source_is_healthy_to_begin_with(self):
        self.assertEqual(link_health(self.source), (6, 0, 0))

    def test_links_still_resolve_after_a_save(self):
        self.assertEqual(link_health(self.save()), (6, 0, 0))

    def test_links_follow_reordered_pages(self):
        """Page 0's link pointed at page 1; reversed, it must still find it."""
        saved = self.save(keep=list(reversed(range(6))))
        good, bad, _inert = link_health(saved)
        self.assertEqual((good, bad), (6, 0))
        with pikepdf.open(saved) as pdf:
            index = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
            # Last output page is source page 0, whose link targeted source
            # page 1 -- now the second from last.
            annot = pdf.pages[5].obj["/Annots"][0]
            self.assertEqual(index[annot["/Dest"][0].objgen], 4)

    def test_a_link_to_a_dropped_page_becomes_inert(self):
        """Better no destination than one aimed at whatever took its place."""
        saved = self.save(keep=[0, 1])
        good, bad, inert = link_health(saved)
        self.assertEqual(bad, 0, "a dangling destination was left behind")
        self.assertEqual(good + inert, 2)
        self.assertEqual(inert, 1, "page 1's link targeted a page that is gone")

    def test_no_dangling_destinations_anywhere(self):
        for keep in (None, [0], [2, 0], list(range(6))):
            with self.subTest(keep=keep):
                self.assertEqual(link_health(self.save(keep=keep))[1], 0)


class TestExistingBehaviourIsUnchanged(DestinationCase):
    """The fixtures that always passed must keep passing."""

    def test_a_plain_document_round_trips(self):
        plain = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "exporter", "outlines.pdf")
        if not os.path.isfile(plain):
            self.skipTest("fixture missing")
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(plain)
        out = temp_path("plain.pdf")
        export(docs.files_for_export(), [p.duplicate() for p in pages], {}, [out])
        self.assertEqual(len(outline_tree(out)), len(outline_tree(plain)))
        self.assertEqual(link_health(out)[1], 0)
