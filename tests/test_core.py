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

"""Geometry, the Page/DocumentSet model and blank pages."""

import os
import unittest

import pikepdf
from support import TEST_PDF, QtDocumentTestCase

from pdfarranger_qt.core import Dims, Page, Sides
from pdfarranger_qt.model import contiguous_blocks


class TestGeometry(unittest.TestCase):
    def test_sides_rotated_is_cyclic(self):
        s = Sides(9, 3, 12, 6)
        self.assertEqual(s.rotated(4), s)
        self.assertEqual(s.rotated(-3), s.rotated(1))

    def test_page_rotate_swaps_size(self):
        page = Page(1, 1, "x.pdf", size_orig=Dims(612, 792))
        self.assertTrue(page.rotate(90))
        self.assertEqual(page.size, Dims(792, 612))
        self.assertEqual(page.angle, 90)
        self.assertFalse(page.rotate(0))
        page.rotate(270)
        self.assertEqual(page.angle, 0)
        self.assertEqual(page.size, Dims(612, 792))

    def test_render_key_tracks_every_visible_property(self):
        page = Page(1, 1, "x.pdf", size_orig=Dims(612, 792))
        before = page.render_key(100)
        page.rotate(90)
        self.assertNotEqual(before, page.render_key(100))
        self.assertNotEqual(page.render_key(100), page.render_key(200))

    def test_contiguous_blocks(self):
        self.assertEqual(contiguous_blocks([1, 2, 3, 7, 8]), [(1, 3), (7, 8)])
        self.assertEqual(contiguous_blocks([]), [])
        self.assertEqual(contiguous_blocks([5]), [(5, 5)])

class TestLoading(QtDocumentTestCase):
    def test_loads_pages_with_sizes(self):
        self.assertEqual(self.model.rowCount(), 2)
        self.assertEqual(self.model.pages[0].size_orig, Dims(612.0, 792.0))

    def test_source_file_is_copied_not_referenced(self):
        doc = self.docs.docs[0]
        self.assertNotEqual(doc.copyname, doc.filename)
        self.assertTrue(os.path.isfile(doc.copyname))

    def test_reloading_the_same_file_reuses_the_document(self):
        self.docs.add_file(TEST_PDF)
        self.assertEqual(len(self.docs.docs), 1)

class TestBlankPages(QtDocumentTestCase):
    def test_creates_a_blank_document(self):
        size = Dims(612, 792)
        name, nfile = self.docs.get_blank_doc(size)
        self.assertTrue(os.path.isfile(name))
        self.assertEqual(self.docs.docs[nfile - 1].blank_size, size)
        with pikepdf.open(name) as pdf:
            self.assertEqual(len(pdf.pages), 1)

    def test_reuses_an_existing_blank_of_the_same_size(self):
        size = Dims(612, 792)
        first, nfile1 = self.docs.get_blank_doc(size)
        second, nfile2 = self.docs.get_blank_doc(size)
        self.assertEqual((first, nfile1), (second, nfile2))

    def test_different_sizes_get_different_documents(self):
        a, _n1 = self.docs.get_blank_doc(Dims(612, 792))
        b, _n2 = self.docs.get_blank_doc(Dims(842, 1191))
        self.assertNotEqual(a, b)

    def test_multi_page_blank(self):
        name, _nfile = self.docs.get_blank_doc(Dims(612, 792), npages=3)
        with pikepdf.open(name) as pdf:
            self.assertEqual(len(pdf.pages), 3)


class TestDoctests(unittest.TestCase):
    """The Sides/Dims arithmetic came across from upstream verbatim, doctests
    and all. Run as a real test rather than through unittest's load_tests hook,
    which pytest does not implement -- under it the hook collected nothing and
    the doctests silently never ran.
    """

    def test_core_doctests(self):
        import doctest

        from pdfarranger_qt import core

        result = doctest.testmod(core, verbose=False)
        self.assertEqual(result.failed, 0)
        self.assertGreater(result.attempted, 0, "no doctests found in core")


class TestPageIdentity(unittest.TestCase):
    """A page keeps an identity that survives editing (D20).

    Bookmarks need something to point at. Not the index, which every reorder
    invalidates; not the object, because UndoManager.snapshot rebuilds the whole
    list with duplicate() and one undo would leave every reference an orphan.
    """

    def page(self):
        return Page(1, 1, "x.pdf")

    def test_pages_have_distinct_identities(self):
        self.assertNotEqual(self.page().uid, self.page().uid)

    def test_a_snapshot_copy_keeps_the_identity(self):
        """What makes undo reconnect a bookmark rather than orphan it."""
        page = self.page()
        self.assertEqual(page.duplicate().uid, page.uid)

    def test_a_new_page_gets_a_new_identity(self):
        """The Duplicate command, so a bookmark does not follow both copies."""
        page = self.page()
        self.assertNotEqual(page.duplicate(new_identity=True).uid, page.uid)

    def test_the_copy_is_otherwise_the_same(self):
        page = self.page()
        page.rotate(90)
        copy = page.duplicate(new_identity=True)
        self.assertEqual(copy.angle, page.angle)
        self.assertEqual(copy.npage, page.npage)


class TestPageSizesAreReadTheFastWay(unittest.TestCase):
    """`QPdfDocument.pagePointSize` once per page is most of a large open.

    1,941 ms for a 1,590-page book, against 23 ms to read the same boxes off
    the page dictionaries with pikepdf -- which is already a dependency and
    already open on the file everywhere else.

    The equivalence is the part to be careful about. A reader shows the
    CropBox where there is one, clipped to the MediaBox, turned by /Rotate.
    Taking the MediaBox alone disagreed with QtPdf on 18 pages of that book.
    """

    def make(self, path, boxes):
        """``boxes`` is ``(media, crop or None, rotate)`` per page."""
        pdf = pikepdf.Pdf.new()
        for media, crop, rotate in boxes:
            page = pdf.add_blank_page(page_size=(media[2] - media[0],
                                                 media[3] - media[1]))
            page.MediaBox = list(media)
            if crop is not None:
                page.CropBox = list(crop)
            if rotate:
                page.Rotate = rotate
        pdf.save(path)
        pdf.close()

    def test_it_agrees_with_the_renderer(self):
        from PySide6.QtPdf import QPdfDocument

        from pdfarranger_qt.core import DocumentSet

        path = os.path.join(os.path.dirname(TEST_PDF), "boxes-tmp.pdf")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.make(path, [
            ((0, 0, 612, 792), None, 0),            # plain
            ((0, 0, 612, 792), (10, 20, 500, 700), 0),   # cropped
            ((0, 0, 612, 792), None, 90),           # turned
            ((0, 0, 612, 792), (10, 20, 500, 700), 270),  # both
            ((0, 0, 800, 600), (0, 0, 2000, 2000), 0),   # crop beyond media
        ])

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        docs.add_file(path)
        ours = docs.docs[0].page_sizes

        doc = QPdfDocument(None)
        doc.load(path)
        theirs = [doc.pagePointSize(i) for i in range(doc.pageCount())]
        doc.close()

        self.assertEqual(len(ours), len(theirs))
        for index, (mine, real) in enumerate(zip(ours, theirs)):
            with self.subTest(page=index):
                self.assertAlmostEqual(mine.width, real.width(), places=2)
                self.assertAlmostEqual(mine.height, real.height(), places=2)

    def test_it_falls_back_when_the_two_disagree_on_the_count(self):
        """Trust the renderer: it is what will actually draw the pages."""
        from pdfarranger_qt.core import DocumentSet

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        docs.add_file(TEST_PDF)
        doc = docs.docs[0]
        self.assertIsNone(doc._sizes_with_pikepdf(doc.n_pages + 1))
