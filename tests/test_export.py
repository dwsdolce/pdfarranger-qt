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

"""Writing PDFs back out, including the pikepdf Job path."""

import os
import unittest

import pikepdf
from support import TEST_PDF, QtDocumentTestCase

from pdfarranger_qt.core import Dims, Sides
from pdfarranger_qt.export import export


class TestExport(QtDocumentTestCase):
    def out(self, name="out.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_round_trip_preserves_page_count(self):
        path = self.out()
        self.assertEqual(export(self.docs.files_for_export(), self.model.pages, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_rotation_is_written(self):
        self.model.rotate([0], 90)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(int(pdf.pages[0].obj.get("/Rotate", 0)), 90)
            self.assertEqual(int(pdf.pages[1].obj.get("/Rotate", 0)), 0)

    def test_reorder_is_written(self):
        self.model.move_rows([0], 2)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_duplicate_is_written(self):
        self.model.duplicate([0])
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 3)

    def test_crop_narrows_the_mediabox(self):
        before = float(self.model.pages[0].width_in_points())
        self.model.pages[0].crop = Sides(0.25, 0.25, 0, 0)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            box = [float(v) for v in pdf.pages[0].obj.MediaBox]
            self.assertAlmostEqual(box[2] - box[0], before * 0.5, delta=1.0)

class TestHideAtExport(QtDocumentTestCase):
    def out(self, name="hidden.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_no_hide_leaves_pages_untouched(self):
        pages = [p.duplicate() for p in self.model.pages]
        before = [(p.copyname, p.npage, len(p.layerpages)) for p in pages]
        self.docs.apply_hide(pages)
        after = [(p.copyname, p.npage, len(p.layerpages)) for p in pages]
        self.assertEqual(before, after)

    def test_hide_rewrites_the_page_as_blank_plus_overlay(self):
        pages = [p.duplicate() for p in self.model.pages]
        original = pages[0].copyname
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        self.docs.apply_hide(pages)

        page = pages[0]
        self.assertNotEqual(page.copyname, original, "page should now be the blank sheet")
        self.assertEqual(page.npage, 1)
        self.assertEqual(page.hide, Sides())
        self.assertEqual(page.angle, 0)
        self.assertEqual(len(page.layerpages), 1)
        layer = page.layerpages[0]
        self.assertEqual(layer.copyname, original, "old content becomes the overlay")
        self.assertEqual(layer.crop, Sides(0.1, 0.1, 0.1, 0.1))
        self.assertEqual(layer.offset, Sides(0.1, 0.1, 0.1, 0.1))

    def test_hide_survives_a_save(self):
        pages = [p.duplicate() for p in self.model.pages]
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        self.docs.apply_hide(pages)
        path = self.out()
        # files_for_export() must come after apply_hide: it appended a document
        self.assertEqual(export(self.docs.files_for_export(), pages, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_hide_within_crop_is_a_no_op(self):
        """Upstream skips when hide is already covered by crop."""
        pages = [p.duplicate() for p in self.model.pages]
        pages[0].crop = Sides(0.2, 0.2, 0.2, 0.2)
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        original = pages[0].copyname
        self.docs.apply_hide(pages)
        self.assertEqual(pages[0].copyname, original)
        self.assertEqual(pages[0].layerpages, [])

class TestInMemoryPdf(QtDocumentTestCase):
    def test_round_trips_through_a_qpdfdocument(self):
        from pdfarranger_qt.export import get_in_memory_pdf
        from pdfarranger_qt.render import MemoryDocument

        data = get_in_memory_pdf(self.model.pages, self.docs.files_for_export())
        self.assertTrue(data.startswith(b"%PDF"))
        with MemoryDocument(data) as doc:
            self.assertTrue(doc.ok, f"QPdfDocument refused the buffer: {doc.error}")
            self.assertEqual(doc.page_count(), 2)

    def test_reflects_edits_not_the_source(self):
        """The point of the helper: it renders the edited document."""
        from pdfarranger_qt.export import get_in_memory_pdf
        from pdfarranger_qt.render import MemoryDocument

        self.model.rotate([0], 90)
        data = get_in_memory_pdf(self.model.pages[:1], self.docs.files_for_export())
        with MemoryDocument(data) as doc:
            size = doc.document.pagePointSize(0)
            self.assertGreater(size.width(), size.height(), "rotation not applied")

    def test_only_opens_referenced_documents(self):
        from pdfarranger_qt.export import get_in_memory_pdf

        self.docs.get_blank_doc(Dims(200, 200))  # a second, unreferenced document
        data = get_in_memory_pdf(self.model.pages, self.docs.files_for_export())
        self.assertTrue(data.startswith(b"%PDF"))

class TestExportJobPath(QtDocumentTestCase):
    def out(self, name="job.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_job_path_produces_the_same_page_count(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path],
               preserve_first_document=True)
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_job_path_applies_rotation(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        self.model.rotate([0], 90)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path],
               preserve_first_document=True)
        with pikepdf.open(path) as pdf:
            self.assertEqual(int(pdf.pages[0].obj.get("/Rotate", 0)), 90)

    def test_both_paths_agree_on_page_count(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        a, b = self.out("a.pdf"), self.out("b.pdf")
        files = self.docs.files_for_export()
        export(files, self.model.pages, {}, [a], preserve_first_document=False)
        export(files, self.model.pages, {}, [b], preserve_first_document=True)
        with pikepdf.open(a) as pa, pikepdf.open(b) as pb:
            self.assertEqual(len(pa.pages), len(pb.pages))


class TestThePageTreeIsBalanced(unittest.TestCase):
    """qpdf writes every page as a direct child of one /Pages node.

    Legal and pessimal: a reader finding page N walks that array, so reading
    every page costs O(n squared). Measured with QtPdf on a 1,590-page book,
    the flat tree we wrote against the balanced one it arrived with -- 0.55 ms
    a page rising to 4.21 ms by the end, against 0.18 rising to 0.53. The
    document we had just written was slower to open than its own source.
    """

    def shape(self, pdf):
        """``(intermediate nodes, widest /Kids, depth)``."""
        found = {"nodes": 0, "widest": 0, "depth": 0}

        def walk(node, depth=0):
            kids = node.get("/Kids")
            if kids is None:
                found["depth"] = max(found["depth"], depth)
                return
            found["nodes"] += 1
            found["widest"] = max(found["widest"], len(kids))
            for kid in kids:
                walk(kid, depth + 1)

        walk(pdf.Root.Pages)
        return found

    def document(self, pages=95):
        pdf = pikepdf.Pdf.new()
        for _ in range(pages):
            pdf.add_blank_page(page_size=(612, 792))
        return pdf

    def test_a_long_document_gets_a_tree(self):
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document()
        self.assertEqual(self.shape(pdf)["widest"], 95, "qpdf starts flat")
        balance_page_tree(pdf)
        found = self.shape(pdf)
        self.assertLessEqual(found["widest"], 10)
        self.assertGreater(found["nodes"], 1)
        self.assertGreater(found["depth"], 1)

    def test_the_pages_stay_in_order(self):
        """The one thing a tree rewrite must not get wrong."""
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document(pages=0)
        for number in range(40):
            page = pdf.add_blank_page(page_size=(612, 792))
            page.UserUnit = number          # a label that survives the move
        balance_page_tree(pdf)
        self.assertEqual([int(page.UserUnit) for page in pdf.pages],
                         list(range(40)))

    def test_every_node_counts_the_leaves_below_it(self):
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document()
        balance_page_tree(pdf)

        def check(node):
            kids = node.get("/Kids")
            if kids is None:
                return 1
            below = sum(check(kid) for kid in kids)
            self.assertEqual(int(node.Count), below)
            return below

        self.assertEqual(check(pdf.Root.Pages), 95)

    def test_every_page_knows_its_parent(self):
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document()
        balance_page_tree(pdf)
        for page in pdf.pages:
            self.assertIn("/Parent", page.obj)

    def test_a_short_document_is_left_alone(self):
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document(pages=6)
        balance_page_tree(pdf)
        self.assertEqual(self.shape(pdf)["nodes"], 1)

    def test_it_survives_the_write(self):
        """qpdf flattens the tree it builds; it keeps one that is given to it."""
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document()
        balance_page_tree(pdf)
        out = os.path.join(os.path.dirname(TEST_PDF), "..", "balanced-tmp.pdf")
        out = os.path.abspath(out)
        self.addCleanup(lambda: os.path.exists(out) and os.remove(out))
        pdf.save(out)
        with pikepdf.open(out) as written:
            self.assertLessEqual(self.shape(written)["widest"], 10)
            self.assertEqual(len(written.pages), 95)

    def test_inherited_attributes_still_resolve(self):
        """The new nodes define none, so inheritance passes through them."""
        from pdfarranger_qt.export import balance_page_tree

        pdf = self.document()
        for page in pdf.pages:
            del page.obj["/MediaBox"]
        pdf.Root.Pages.MediaBox = [0, 0, 612, 792]
        balance_page_tree(pdf)
        self.assertEqual([float(v) for v in pdf.pages[50].mediabox],
                         [0, 0, 612, 792])
