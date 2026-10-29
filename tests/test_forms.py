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

"""A filled form shows what is in it.

PDFium renders a page and then leaves form fields to a form-fill module QtPdf
never initialises, so every answer typed into a document was invisible here --
and ``RenderFlag.Annotations`` does not help, because the exclusion is of
widgets specifically. The documents a *renderer* opens therefore have their
fields rewritten into something it will draw.

The rewritten copy must never reach a saved file, which is what most of these
check: a field turned into a picture of itself is no longer a field.
"""

import io
import os
import unittest

import pikepdf
from support import TEST_PDF, settle, temp_path
from test_annotations import blue_pixels, document_with_annotation

from pdfarranger_qt import forms


class TestTheRewrite(unittest.TestCase):
    def pdf(self, data):
        return pikepdf.open(io.BytesIO(data))

    def test_a_form_is_recognised(self):
        self.assertTrue(forms.has_widgets(
            self.pdf(document_with_annotation("/Widget"))))

    def test_a_document_without_one_is_not(self):
        self.assertFalse(forms.has_widgets(
            self.pdf(document_with_annotation("/Square"))))

    def test_a_field_with_nothing_to_draw_does_not_count(self):
        """No appearance means invisible in every viewer, so nothing to show."""
        data = document_with_annotation("/Widget")
        pdf = self.pdf(data)
        del pdf.pages[0].Annots[0][pikepdf.Name.AP]
        self.assertFalse(forms.has_widgets(pdf))

    def test_the_rewrite_reports_what_it_changed(self):
        pdf = self.pdf(document_with_annotation("/Widget"))
        self.assertEqual(forms.show_widgets(pdf), 1)
        self.assertEqual(str(pdf.pages[0].Annots[0].Subtype), "/Stamp")

    def test_a_rewritten_field_is_drawn(self):
        """The whole point, measured the same way as everything else here."""
        data = document_with_annotation("/Widget")
        self.assertEqual(blue_pixels(data), 0, "invisible as a widget")
        pdf = self.pdf(data)
        forms.show_widgets(pdf)
        out = io.BytesIO()
        pdf.save(out)
        self.assertGreater(blue_pixels(out.getvalue()), 0,
                           "and visible once it is not one")

    def test_the_value_is_left_alone(self):
        """Only the subtype changes; this copy is still readable as a form."""
        pdf = self.pdf(document_with_annotation("/Widget"))
        forms.show_widgets(pdf)
        annot = pdf.pages[0].Annots[0]
        self.assertEqual(str(annot.V), "a value")
        self.assertEqual(str(annot.T), "a field")

    def test_bytes_without_fields_come_back_unchanged(self):
        data = document_with_annotation("/Square")
        self.assertIs(forms.rendered_bytes(data), data)

    def test_bytes_with_fields_come_back_drawable(self):
        data = document_with_annotation("/Widget")
        self.assertGreater(blue_pixels(forms.rendered_bytes(data)), 0)

    def test_rubbish_is_returned_rather_than_raised(self):
        """Rendering falls back to the original; it does not fail the open."""
        self.assertEqual(forms.rendered_bytes(b"not a pdf"), b"not a pdf")
        self.assertIsNone(forms.rendered_copy("/nowhere.pdf", "", "/tmp"))


class TestTheDocumentChoosesItsCopy(unittest.TestCase):
    def doc(self, data=None, path=None):
        from pdfarranger_qt.core import DocumentSet

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        if path is None:
            path = temp_path("form.pdf")
            with open(path, "wb") as handle:
                handle.write(data)
        docs.add_file(path)
        return docs, docs.docs[0]

    def test_a_plain_document_renders_from_its_working_copy(self):
        """Nothing extra is written for the documents that need nothing."""
        _docs, doc = self.doc(path=TEST_PDF)
        self.assertFalse(doc.has_form_widgets)
        self.assertEqual(doc.render_copyname, doc.copyname)

    def test_a_form_gets_a_second_copy(self):
        _docs, doc = self.doc(document_with_annotation("/Widget"))
        self.assertTrue(doc.has_form_widgets)
        self.assertNotEqual(doc.render_copyname, doc.copyname)
        self.assertTrue(os.path.exists(doc.render_copyname))

    def test_the_second_copy_is_built_once(self):
        _docs, doc = self.doc(document_with_annotation("/Widget"))
        self.assertEqual(doc.render_copyname, doc.render_copyname)

    def test_the_working_copy_still_has_its_fields(self):
        """What export reads. A rewritten copy here would be data loss."""
        _docs, doc = self.doc(document_with_annotation("/Widget"))
        with pikepdf.open(doc.copyname) as pdf:
            self.assertEqual(str(pdf.pages[0].Annots[0].Subtype), "/Widget")

    def test_the_render_copy_does_not(self):
        _docs, doc = self.doc(document_with_annotation("/Widget"))
        with pikepdf.open(doc.render_copyname) as pdf:
            self.assertEqual(str(pdf.pages[0].Annots[0].Subtype), "/Stamp")

    def test_the_set_knows_which_file_a_renderer_wants(self):
        """What the thumbnail path asks, once per page it draws."""
        docs, doc = self.doc(document_with_annotation("/Widget"))
        asked = docs.render_file(_FakePage(1, doc.copyname))
        self.assertEqual(asked, doc.render_copyname)
        self.assertNotEqual(asked, doc.copyname,
                            "a form must not be drawn from the file export reads")

    def test_a_page_from_no_known_document_falls_back_to_its_own_file(self):
        docs, doc = self.doc(document_with_annotation("/Widget"))
        stray = _FakePage(99, "/some/other/file.pdf")
        self.assertEqual(docs.render_file(stray), "/some/other/file.pdf")

    def test_export_is_unaffected(self):
        docs, doc = self.doc(document_with_annotation("/Widget"))
        self.assertEqual(docs.files_for_export()[0][0], doc.copyname)
        self.assertNotEqual(docs.files_for_export()[0][0], doc.render_copyname)


class _FakePage:
    """Only ``nfile`` and ``copyname`` are looked at."""

    def __init__(self, nfile, copyname):
        self.nfile = nfile
        self.copyname = copyname


class TestTheReaderShowsThem(unittest.TestCase):
    def window(self, data):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("reader-form.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        win = MainWindow()
        win.resize(700, 600)
        win.show()
        win.open_paths([path])
        settle(timeout_ms=800)
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def test_an_unmodified_form_is_read_from_the_rewritten_copy(self):
        """D19's fast path, pointed at the copy a renderer can draw."""
        win = self.window(document_with_annotation("/Widget"))
        source = win.docs.source_if_unmodified(win.model.pages)
        self.assertIsNotNone(source, "one unedited document should qualify")
        self.assertEqual(source[0], win.docs.docs[0].render_copyname)
        self.assertNotEqual(source[0], win.docs.docs[0].copyname,
                            "the reader would show a blank form otherwise")

    def test_a_plain_document_still_takes_the_fast_path_unchanged(self):
        """D19 must not pay for a feature it does not use."""
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        self.addCleanup(win.close)
        win.open_paths([TEST_PDF])
        settle(timeout_ms=600)
        win.modified = False
        source = win.docs.source_if_unmodified(win.model.pages)
        self.assertEqual(source[0], win.docs.docs[0].copyname)

    def test_the_window_knows_a_form_is_loaded(self):
        win = self.window(document_with_annotation("/Widget"))
        self.assertTrue(win.docs.has_form_widgets())


class TestItNeverReachesASavedFile(unittest.TestCase):
    """The one that matters. A field drawn into a file is not a field."""

    def saved(self, data, edit=False):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("source-form.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        win = MainWindow()
        self.addCleanup(win.close)
        win.open_paths([path])
        settle(timeout_ms=800)
        if edit:
            win.model.pages[0].rotate(90)
        out = temp_path("saved-form.pdf")
        self.assertTrue(win._write([out], win.model.pages))
        win.modified = False
        return pikepdf.open(out)

    def subtypes(self, pdf):
        return [str(a.get("/Subtype")) for page in pdf.pages
                for a in page.get("/Annots", [])]

    def test_a_saved_form_still_has_widgets(self):
        self.assertEqual(self.subtypes(
            self.saved(document_with_annotation("/Widget"))), ["/Widget"])

    def test_even_after_an_edit(self):
        """An edit sends read mode down the export path, which also rewrites."""
        self.assertEqual(self.subtypes(
            self.saved(document_with_annotation("/Widget"), edit=True)),
            ["/Widget"])

    def test_a_saved_form_still_has_its_form_dictionary(self):
        saved = self.saved(document_with_annotation("/Widget"))
        self.assertIsNotNone(saved.Root.get("/AcroForm"))
        self.assertEqual(len(saved.Root.AcroForm.Fields), 1)
