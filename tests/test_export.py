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
import pikepdf

from pdfarranger_qt.core import Dims, Sides
from pdfarranger_qt.export import export

from support import QtDocumentTestCase


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
