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
from PySide6.QtGui import QImage
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

    def test_an_unmodified_form_is_read_from_the_working_copy(self):
        """D19's fast path, pointed at the document as it really is.

        It used to hand over the rewritten copy, because the page renderer
        would draw no field otherwise. The reader draws them itself now, over
        the page, so it wants the widgets intact -- the rewrite is for the
        renderers that cannot, which is the grid and the output paths.
        """
        win = self.window(document_with_annotation("/Widget"))
        source = win.docs.source_if_unmodified(win.model.pages)
        self.assertIsNotNone(source, "one unedited document should qualify")
        self.assertEqual(source[0], win.docs.docs[0].copyname)

    def test_the_reader_has_the_fields_to_draw(self):
        """What replaced it: the canvas holds the widgets and paints them."""
        win = self.window(document_with_annotation("/Widget"))
        win.set_read_mode(True)
        settle(timeout_ms=600)
        fields = win.reader.canvas.fields()
        self.assertIsNotNone(fields)
        self.assertEqual(len(fields), 1)

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


class TestTheOutputPathsShowThemToo(unittest.TestCase):
    """Printing a filled form printed it blank.

    Display was fixed first and every output path was left blind: printing,
    image export and rasterising all go through `raster.render_pages`, which
    built the real export and rendered it with no options at all. On the form
    that prompted this work, none of the fifteen answers on page three
    appeared. A blank screen is noticed; a blank printout gets posted.

    `render_pages` is the single funnel for everything that leaves as pixels,
    so the fix belongs there and reaches all four callers at once.
    """

    def pages(self, data):
        from pdfarranger_qt.core import DocumentSet

        path = temp_path("printed-form.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        return docs.add_file(path), docs

    def blue_in_render(self, data, ppi=144):
        from pdfarranger_qt.raster import render_pages

        pages, docs = self.pages(data)
        images = list(render_pages(pages, docs.files_for_export(), ppi=ppi))
        self.assertTrue(images, "nothing rendered")
        image = images[0]
        found = 0
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                colour = image.pixelColor(x, y)
                if colour.blue() > 150 and colour.red() < 100:
                    found += 1
        return found

    def test_a_form_field_is_printed(self):
        self.assertGreater(self.blue_in_render(
            document_with_annotation("/Widget")), 0)

    def test_an_annotation_is_printed(self):
        """A colleague's highlight should reach the paper as well."""
        self.assertGreater(self.blue_in_render(
            document_with_annotation("/Square")), 0)

    def test_a_hidden_field_is_not(self):
        """Bit 2 of /F is Hidden, and that has to survive into the output."""
        self.assertEqual(self.blue_in_render(
            document_with_annotation("/Widget", flags=2)), 0)

    def test_the_source_is_not_modified_by_rendering(self):
        """Rendering reads; it must not leave the widgets rewritten on disk."""
        pages, docs = self.pages(document_with_annotation("/Widget"))
        from pdfarranger_qt.raster import render_pages

        list(render_pages(pages, docs.files_for_export(), ppi=72))
        with pikepdf.open(docs.docs[0].copyname) as pdf:
            self.assertEqual(str(pdf.pages[0].Annots[0].Subtype), "/Widget")


def radio_across_pages():
    """One radio field with a widget on each of two pages.

    The case the form that prompted this work does not contain -- all 82 of its
    fields sit on a single page -- and the one that showed export splitting a
    field in two. Built from the specification rather than found, which is the
    only way to meet a case nobody has sent you yet.
    """
    def tick(pdf, on):
        stream = pikepdf.Stream(pdf, b"0 0 1 rg 0 0 12 12 re f\n" if on else b"\n")
        stream[pikepdf.Name.Type] = pikepdf.Name.XObject
        stream[pikepdf.Name.Subtype] = pikepdf.Name.Form
        stream[pikepdf.Name.BBox] = pikepdf.Array([0, 0, 12, 12])
        return stream

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 300))
    pdf.add_blank_page(page_size=(300, 300))
    field = pdf.make_indirect(pikepdf.Dictionary(
        FT=pikepdf.Name.Btn, T=pikepdf.String("choice"),
        Ff=1 << 15, V=pikepdf.Name("/yes")))
    kids = []
    for index, page in enumerate(pdf.pages):
        widget = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            Rect=pikepdf.Array([50, 50 + index * 20, 62, 62 + index * 20]),
            F=4, Parent=field,
            AS=pikepdf.Name("/yes") if index == 0 else pikepdf.Name.Off,
            # A positional dict, not keywords: pikepdf prefixes a slash to a
            # keyword, so **{"/yes": ...} builds a state called "//yes".
            AP=pikepdf.Dictionary(N=pikepdf.Dictionary(
                {"/yes": tick(pdf, True), "/Off": tick(pdf, False)}))))
        kids.append(widget)
        page[pikepdf.Name.Annots] = pikepdf.Array([widget])
    field[pikepdf.Name.Kids] = pikepdf.Array(kids)
    pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
        Fields=pikepdf.Array([field]))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestAFieldIsNotSplitAcrossPages(unittest.TestCase):
    """Two requirements that pull against each other.

    Pages sharing a field must keep sharing it, or a radio group becomes two
    groups and selecting one option stops clearing the other. But *duplicated*
    pages must get independent annotations, which is why the per-page copy
    exists at all -- without it, editing one copy's annotation changed the
    other (upstream's issue 437).

    A fix that satisfies only the first reintroduces that bug, so both are
    checked here and neither may be traded for the other.
    """

    def exported(self, data, order=None):
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        path = temp_path("across-pages.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(path)
        if order is not None:
            pages = [pages[i] for i in order]
        return pikepdf.open(io.BytesIO(
            get_in_memory_pdf(pages, docs.files_for_export())))

    def shape(self, pdf):
        """``(fields, widgets, distinct parents)`` of the output."""
        acroform = pdf.Root.get("/AcroForm")
        fields = len(acroform.get("/Fields", [])) if acroform is not None else 0
        widgets, parents = 0, set()
        for page in pdf.pages:
            for annot in page.get("/Annots", []):
                if annot.get("/Subtype") != "/Widget":
                    continue
                widgets += 1
                if "/Parent" in annot:
                    parents.add(annot.Parent.objgen)
        return fields, widgets, len(parents)

    def test_one_field_stays_one_field(self):
        self.assertEqual(self.shape(self.exported(radio_across_pages())),
                         (1, 2, 1))

    def test_and_after_reordering(self):
        self.assertEqual(
            self.shape(self.exported(radio_across_pages(), order=[1, 0])),
            (1, 2, 1))

    def test_dropping_a_page_keeps_the_field_for_the_other(self):
        fields, widgets, _parents = self.shape(
            self.exported(radio_across_pages(), order=[0]))
        self.assertEqual((fields, widgets), (1, 1))

    def test_no_merge_warning_for_a_document_nobody_merged(self):
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import export

        path = temp_path("across-pages.pdf")
        with open(path, "wb") as handle:
            handle.write(radio_across_pages())
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(path)
        warning = export(docs.files_for_export(), pages, {},
                         [temp_path("out.pdf")])
        self.assertNotIn("share a name", warning)

    def test_a_duplicated_page_still_gets_its_own_annotations(self):
        """Upstream's issue 437, which the per-page copy exists to prevent."""
        exported = self.exported(radio_across_pages(), order=[0, 0, 1])
        first = exported.pages[0].Annots[0].objgen
        second = exported.pages[1].Annots[0].objgen
        self.assertNotEqual(first, second,
                            "two copies of one page must not share a widget")


class TestTheOverlayItself(unittest.TestCase):
    """What has been typed, as a container, with no Qt and no document."""

    def values(self):
        from pdfarranger_qt.forms import FormValues

        return FormValues()

    def test_an_untouched_form_stores_nothing(self):
        """Sparse on purpose: the document already holds what it came with."""
        self.assertFalse(self.values())
        self.assertEqual(len(self.values()), 0)

    def test_absent_is_not_empty(self):
        """"Never touched" and "deliberately emptied" are different answers.

        The first means ask the document; the second is an edit to empty, and
        must survive a save as one.
        """
        values = self.values()
        self.assertIsNone(values.get(1, "name"))
        self.assertFalse(values.edited(1, "name"))
        values.set(1, "name", "")
        self.assertEqual(values.get(1, "name"), "")
        self.assertTrue(values.edited(1, "name"))

    def test_reverting_forgets_the_edit(self):
        values = self.values()
        values.set(1, "name", "typed")
        values.revert(1, "name")
        self.assertFalse(values.edited(1, "name"))
        self.assertIsNone(values.get(1, "name"))

    def test_the_same_name_in_two_documents_is_two_fields(self):
        """Merging two forms that both have a "name" field keeps them apart
        here; they only become one field once they are in one document, which
        is what the save warns about."""
        values = self.values()
        values.set(1, "name", "from the first")
        values.set(2, "name", "from the second")
        self.assertEqual(values.get(1, "name"), "from the first")
        self.assertEqual(values.get(2, "name"), "from the second")

    def test_a_copy_is_independent(self):
        values = self.values()
        values.set(1, "name", "typed")
        copy = values.duplicate()
        copy.set(1, "other", "later")
        self.assertEqual(len(values), 1)
        self.assertEqual(len(copy), 2)

    def test_one_document_can_be_read_out(self):
        values = self.values()
        values.set(1, "a", "x")
        values.set(2, "b", "y")
        values.set(1, "c", "z")
        self.assertEqual(values.for_document(1), {"a": "x", "c": "z"})
        self.assertEqual(values.for_document(3), {})


class TestAValueSurvivesEditing(unittest.TestCase):
    """2.1's done-when: a value survives undo, redo and a page reorder.

    The point of putting it on the same stack as the pages. A value keyed by
    page would not survive the reorder; one on a stack of its own could
    disagree with the page list about what the document is.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=400)
        self.win.modified = False
        self.addCleanup(self.win.close)
        self.addCleanup(lambda: setattr(self.win, "modified", False))
        self.model = self.win.model

    def typed(self):
        return self.model.form_values.get(1, "a.field")

    def type_something(self):
        self.model.undo.commit("Fill")
        self.model.form_values.set(1, "a.field", "typed")

    def test_a_value_is_remembered(self):
        self.type_something()
        self.assertEqual(self.typed(), "typed")

    def test_undo_takes_it_back(self):
        self.type_something()
        self.win.undo()
        settle(timeout_ms=200)
        self.assertIsNone(self.typed())

    def test_redo_brings_it_back(self):
        self.type_something()
        self.win.undo()
        settle(timeout_ms=200)
        self.win.redo()
        settle(timeout_ms=200)
        self.assertEqual(self.typed(), "typed")

    def test_a_reorder_leaves_it_alone(self):
        """Nothing in the key refers to a position, so this is free."""
        self.type_something()
        self.win.view.set_selected_rows([1])
        self.win.move_to_start()
        settle(timeout_ms=200)
        self.assertEqual(self.typed(), "typed")

    def test_undoing_a_page_edit_does_not_lose_it(self):
        """One stack: a rotation's undo must not take the typing with it.

        Both halves are asserted. Checking only that the value survived would
        pass with the whole mechanism switched off, since a value that is never
        snapshotted is also never restored.
        """
        self.type_something()
        before = self.model.pages[0].angle
        self.win.view.set_selected_rows([0])
        self.win.rotate(90)
        settle(timeout_ms=200)
        self.assertNotEqual(self.model.pages[0].angle, before, "it should rotate")
        self.win.undo()
        settle(timeout_ms=200)
        self.assertEqual(self.model.pages[0].angle, before,
                         "the rotation should be undone")
        self.assertEqual(self.typed(), "typed",
                         "and only the rotation")

    def test_a_value_set_before_a_page_edit_is_restored_with_it(self):
        """The discriminating case: undo must put back the value that was in
        the snapshot, not merely leave the live one alone."""
        self.type_something()
        self.model.undo.commit("Rotate")
        self.model.form_values.set(1, "a.field", "changed later")
        self.win.view.set_selected_rows([0])
        self.win.undo()
        settle(timeout_ms=200)
        self.assertEqual(self.typed(), "typed",
                         "undo should restore the snapshotted value")

    def test_deleting_the_page_leaves_the_value_dangling(self):
        """Not destroyed: undo restores the page, and the value is still there
        to go with it. The export writes only the fields whose widgets
        survived, so a dangling value reaches no file."""
        self.type_something()
        self.win.view.set_selected_rows([0])
        self.win.delete_selected()
        settle(timeout_ms=200)
        self.assertEqual(self.typed(), "typed")
        self.win.undo()
        settle(timeout_ms=200)
        self.assertEqual(self.typed(), "typed")


class TestReadingTheFieldsOfADocument(unittest.TestCase):
    """What the fields are, read with pikepdf and no canvas in sight."""

    def map_of(self, data):
        from pdfarranger_qt.forms import FieldMap

        return FieldMap.read(data)

    def test_a_widget_is_found_with_its_identity(self):
        fields = self.map_of(document_with_annotation("/Widget"))
        self.assertEqual(len(fields), 1)
        only = fields.on_page(0)[0]
        self.assertEqual(only.name, "a field")
        self.assertEqual(only.kind, "/Tx")
        self.assertEqual(only.value, "a value")

    def test_a_plain_annotation_is_not_a_field(self):
        self.assertEqual(len(self.map_of(document_with_annotation("/Square"))), 0)


    def test_a_radio_group_is_recognised_as_one(self):
        fields = self.map_of(radio_across_pages())
        self.assertEqual(len(fields), 2, "one widget on each page")
        for page in (0, 1):
            found = fields.on_page(page)[0]
            self.assertEqual(found.name, "choice",
                             "both widgets name the same field")
            self.assertTrue(found.is_radio)
            self.assertFalse(found.is_checkbox)
            self.assertEqual(found.states, ["/yes"])

    def test_rubbish_reads_as_nothing(self):
        self.assertEqual(len(self.map_of(b"not a pdf")), 0)

    # -- what a click should and should not act on -------------------------

    def field(self, **kwargs):
        from pdfarranger_qt.forms import Field

        base = dict(page=0, rect=(0, 0, 10, 10), name="f", kind="/Tx",
                    flags=0, states=[], value=None, hidden=False)
        base.update(kwargs)
        return Field(**base)

    def test_an_ordinary_field_is_fillable(self):
        self.assertTrue(self.field().fillable)

    def test_a_read_only_field_is_not(self):
        """The document saying no."""
        self.assertFalse(self.field(flags=1).fillable)

    def test_a_pushbutton_is_not(self):
        """It runs an action; it holds no value."""
        self.assertFalse(self.field(kind="/Btn", flags=1 << 16).fillable)

    def test_a_signature_is_not(self):
        self.assertFalse(self.field(kind="/Sig").fillable)

    def test_a_hidden_field_is_not(self):
        self.assertFalse(self.field(hidden=True).fillable)

    def test_a_radio_is_not_mistaken_for_a_tick_box(self):
        radio = self.field(kind="/Btn", flags=1 << 15)
        self.assertTrue(radio.is_radio)
        self.assertFalse(radio.is_checkbox)
        box = self.field(kind="/Btn")
        self.assertTrue(box.is_checkbox)
        self.assertFalse(box.is_radio)


def stamp_titled(name="Mobile User", kind=None):
    """A genuine stamp annotation that carries a title.

    Which is what Apple's markup leaves behind: every annotation it writes is
    titled with the device's user name, and alongside the ``/FreeText`` boxes
    it adds one ``/Stamp``. Two documents in the corpus carry exactly this.
    """
    data = document_with_annotation("/Stamp")
    pdf = pikepdf.open(io.BytesIO(data))
    annot = pdf.pages[0].Annots[0]
    annot[pikepdf.Name.T] = pikepdf.String(name)
    if kind is not None:
        annot[pikepdf.Name.FT] = pikepdf.Name(kind)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestAStampIsNotAField(unittest.TestCase):
    """A drawing is a drawing, however it is titled.

    ``show_widgets`` turns widgets into stamps so that PDFium will draw them,
    and body 1 showed the reader that rewritten copy -- so reading a stamp as
    a field was right then. The reader is not shown that copy any more: it
    composites the fields over the page itself, and is handed either the
    export or the source file, both carrying real widgets. All the exception
    still caught was genuine stamps, and real documents have them.
    """

    def test_a_titled_stamp_is_not_read_as_a_field(self):
        self.assertEqual(len(forms.FieldMap.read(stamp_titled())), 0)

    def test_a_widget_still_is(self):
        """The other half: the change must not cost us real fields."""
        self.assertEqual(
            len(forms.FieldMap.read(document_with_annotation("/Widget"))), 1)

    def test_a_stamp_is_not_written_to(self):
        """Even one carrying the type and name of a field that is being filled.

        A stamp sharing a field's name would otherwise take its value, and the
        phantom would be saved into the document.
        """
        pdf = pikepdf.open(io.BytesIO(stamp_titled("box", kind="/Btn")))
        self.assertEqual(forms.apply_values(pdf.pages, {"box": "/Yes"}), 0)
        self.assertNotIn(pikepdf.Name.V, pdf.pages[0].Annots[0])


class TestWhichFieldIsUnderAPoint(unittest.TestCase):
    def map_of(self, *rects):
        from pdfarranger_qt.forms import Field, FieldMap

        return FieldMap(
            Field(page=0, rect=r, name=f"f{i}", kind="/Tx", flags=0,
                  states=[], value=None, hidden=False)
            for i, r in enumerate(rects))

    def test_a_point_inside_finds_it(self):
        found = self.map_of((10, 10, 50, 30)).at(0, 20, 20)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "f0")

    def test_a_point_outside_finds_nothing(self):
        self.assertIsNone(self.map_of((10, 10, 50, 30)).at(0, 5, 5))

    def test_the_edge_counts_as_inside(self):
        fields = self.map_of((10, 10, 50, 30))
        for x, y in ((10, 10), (50, 30), (10, 30), (50, 10)):
            self.assertIsNotNone(fields.at(0, x, y), f"({x}, {y})")

    def test_another_page_finds_nothing(self):
        self.assertIsNone(self.map_of((10, 10, 50, 30)).at(1, 20, 20))

    def test_the_one_on_top_wins(self):
        """Annotations draw in array order, so the later one is on top and is
        what a click should reach."""
        found = self.map_of((0, 0, 100, 100), (10, 10, 50, 50)).at(0, 20, 20)
        self.assertEqual(found.name, "f1")


class TestClickingAField(unittest.TestCase):
    """2.2's done-when: clicking a widget identifies its field; clicking
    elsewhere does not.

    Through the real canvas, because the y axis is the whole of the work: a
    page point here is measured down from the top, a PDF rectangle up from the
    bottom, and nothing but a round trip proves the flip is right.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("clickable.pdf")
        with open(path, "wb") as handle:
            handle.write(document_with_annotation("/Widget"))
        self.win = MainWindow()
        self.win.resize(700, 760)
        self.win.show()
        self.win.open_paths([path])
        settle(timeout_ms=600)
        self.win.set_read_mode(True)
        settle(timeout_ms=800)
        self.addCleanup(self.win.close)
        self.addCleanup(lambda: setattr(self.win, "modified", False))
        self.canvas = self.win.reader.canvas

    def viewport_point(self, x_pt, y_pt_from_top):
        """A page point, in the viewport coordinates a click arrives in."""
        from PySide6.QtCore import QPointF

        document = self.canvas.layout.from_page(
            0, QPointF(x_pt, y_pt_from_top))
        return document - self.canvas.offset()

    def test_the_widget_is_found_where_it_is_drawn(self):
        """The fixture's widget is Rect 100,150 to 300,250 on a 400pt page,
        so its centre is 100pt down from the top."""
        found = self.win.reader.field_at(self.viewport_point(200, 200))
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "a field")

    def test_above_it_finds_nothing(self):
        """Proves the y flip. Without it this point would be the hit and the
        one inside would not."""
        self.assertIsNone(self.win.reader.field_at(self.viewport_point(200, 20)))

    def test_beside_it_finds_nothing(self):
        self.assertIsNone(self.win.reader.field_at(self.viewport_point(20, 200)))

    def test_every_corner_of_the_rectangle_is_inside(self):
        for x, y in ((101, 151), (299, 151), (101, 249), (299, 249)):
            self.assertIsNotNone(
                self.win.reader.field_at(self.viewport_point(x, y)),
                f"page point ({x}, {y}) should be on the widget")

    def test_closing_the_document_forgets_the_fields(self):
        """A raw viewport point, because once the document has gone there are
        no pages left to map one through."""
        from PySide6.QtCore import QPointF

        inside = self.viewport_point(200, 200)
        self.assertIsNotNone(self.win.reader.field_at(inside))
        self.win.reader.clear()
        settle(timeout_ms=100)
        self.assertIsNone(self.win.reader.field_at(inside))
        self.assertIsNone(self.win.reader.field_at(QPointF(10, 10)))

    def test_a_document_with_no_fields_finds_nothing(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=600)
        self.win.modified = False
        self.assertIsNone(self.win.reader.field_at(self.viewport_point(100, 100)))


def tickable(name="box", on="/Yes", value=None, radio=False, pages=1):
    """A document of tick boxes, one per page, sharing one field."""
    def drawing(pdf, filled):
        stream = pikepdf.Stream(
            pdf, b"0 0 1 rg 0 0 14 14 re f\n" if filled else b"1 1 1 rg 0 0 14 14 re f\n")
        stream[pikepdf.Name.Type] = pikepdf.Name.XObject
        stream[pikepdf.Name.Subtype] = pikepdf.Name.Form
        stream[pikepdf.Name.BBox] = pikepdf.Array([0, 0, 14, 14])
        return stream

    pdf = pikepdf.new()
    field = pdf.make_indirect(pikepdf.Dictionary(
        FT=pikepdf.Name.Btn, T=pikepdf.String(name),
        Ff=(1 << 15) if radio else 0))
    if value is not None:
        field[pikepdf.Name.V] = pikepdf.Name(value)
    kids = []
    for _ in range(pages):
        pdf.add_blank_page(page_size=(200, 200))
        page = pdf.pages[-1]
        widget = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            Rect=pikepdf.Array([50, 50, 64, 64]), F=4, Parent=field,
            AS=pikepdf.Name(value if value in (on,) else "/Off"),
            AP=pikepdf.Dictionary(N=pikepdf.Dictionary(
                {on: drawing(pdf, True), "/Off": drawing(pdf, False)}))))
        kids.append(widget)
        page[pikepdf.Name.Annots] = pikepdf.Array([widget])
    field[pikepdf.Name.Kids] = pikepdf.Array(kids)
    pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
        Fields=pikepdf.Array([field]))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestDrawingOneAppearance(unittest.TestCase):
    """The layer's engine: one widget's appearance, on its own."""

    def renderer(self):
        from pdfarranger_qt.fieldlayer import AppearanceRenderer

        return AppearanceRenderer()

    def widget(self, data=None):
        pdf = pikepdf.open(io.BytesIO(data or tickable()))
        self.addCleanup(pdf.close)
        return pdf.pages[0].Annots[0]

    def blue(self, image):
        if image is None:
            return 0
        return sum(1 for y in range(image.height()) for x in range(image.width())
                   if image.pixelColor(x, y).blue() > 150
                   and image.pixelColor(x, y).red() < 100)

    def test_the_on_state_draws_and_the_off_state_does_not(self):
        renderer, widget = self.renderer(), self.widget()
        self.assertGreater(self.blue(renderer.image(widget, "/Yes", 40, 40)), 0)
        self.assertEqual(self.blue(renderer.image(widget, "/Off", 40, 40)), 0)

    def test_a_state_the_widget_has_no_drawing_for_is_nothing(self):
        renderer, widget = self.renderer(), self.widget()
        self.assertIsNone(renderer.image(widget, "/Maybe", 40, 40))

    def test_an_appearance_is_rendered_once(self):
        renderer, widget = self.renderer(), self.widget()
        first = renderer.image(widget, "/Yes", 40, 40)
        self.assertIs(renderer.image(widget, "/Yes", 40, 40), first)
        self.assertEqual(len(renderer), 1)

    def test_a_different_size_is_a_different_image(self):
        renderer, widget = self.renderer(), self.widget()
        renderer.image(widget, "/Yes", 40, 40)
        renderer.image(widget, "/Yes", 80, 80)
        self.assertEqual(len(renderer), 2)

    def test_a_widget_scaled_to_nothing_is_not_drawn(self):
        renderer, widget = self.renderer(), self.widget()
        self.assertIsNone(renderer.image(widget, "/Yes", 1, 1))

    def test_clearing_forgets_everything(self):
        renderer, widget = self.renderer(), self.widget()
        renderer.image(widget, "/Yes", 40, 40)
        renderer.clear()
        self.assertEqual(len(renderer), 0)


class TestWhichAppearanceAWidgetShows(unittest.TestCase):
    """One field, one value, many widgets -- which draws itself on."""

    def field(self, states, kind="/Btn", flags=0):
        from pdfarranger_qt.forms import Field

        return Field(page=0, rect=(0, 0, 10, 10), name="f", kind=kind,
                     flags=flags, states=states, value=None, hidden=False)

    def test_a_box_is_on_when_the_value_names_its_state(self):
        box = self.field(["/Yes"])
        self.assertEqual(box.state_for("/Yes"), "/Yes")
        self.assertEqual(box.state_for("/Off"), "/Off")
        self.assertEqual(box.state_for(None), "/Off")

    def test_a_radio_member_is_off_when_another_is_chosen(self):
        """How a group clears itself: nothing has to, because the value names
        one member's state and the others simply do not match it."""
        first = self.field(["/first"], flags=1 << 15)
        second = self.field(["/second"], flags=1 << 15)
        self.assertEqual(first.state_for("/second"), "/Off")
        self.assertEqual(second.state_for("/second"), "/second")

    def test_a_text_field_has_no_state(self):
        self.assertIsNone(self.field([], kind="/Tx").state_for("anything"))


class TestTickingABox(unittest.TestCase):
    """2.3's done-when: clicking one toggles it on screen and after a save."""

    def window(self, data=None):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("tickable.pdf")
        with open(path, "wb") as handle:
            handle.write(data or tickable())
        win = MainWindow()
        win.resize(700, 640)
        win.show()
        win.open_paths([path])
        settle(timeout_ms=600)
        win.set_read_mode(True)
        settle(timeout_ms=600)
        win.modified = False
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def only_field(self, win, page=0):
        return win.reader.canvas.fields().on_page(page)[0]

    def held(self, win, field):
        page = win.model.pages[field.page]
        return win.model.form_values.get(page.nfile, field.name)

    def blue_on_screen(self, win):
        """How much of the layer's blue is painted. Nothing else is blue."""
        canvas = win.reader.canvas
        shot = QImage(canvas.viewport().size(), QImage.Format_RGB32)
        shot.fill(0xFFFFFFFF)
        canvas.viewport().render(shot)
        return sum(1 for y in range(0, shot.height(), 2)
                   for x in range(0, shot.width(), 2)
                   if shot.pixelColor(x, y).blue() > 150
                   and shot.pixelColor(x, y).red() < 100)

    # -- on screen ---------------------------------------------------------

    def test_an_empty_box_shows_nothing_and_a_click_fills_it(self):
        win = self.window()
        field = self.only_field(win)
        self.assertEqual(self.blue_on_screen(win), 0, "nothing ticked yet")
        win.field_pressed(field)
        settle(timeout_ms=200)
        self.assertGreater(self.blue_on_screen(win), 0, "it should show")

    def test_clicking_again_clears_it(self):
        win = self.window()
        field = self.only_field(win)
        win.field_pressed(field)
        settle(timeout_ms=150)
        win.field_pressed(field)
        settle(timeout_ms=150)
        self.assertEqual(self.held(win, field), "/Off")
        self.assertEqual(self.blue_on_screen(win), 0)

    def test_a_radio_does_not_turn_itself_off(self):
        """Pressing the chosen member of a group leaves it chosen, which is
        what every radio group anywhere does."""
        win = self.window(tickable(radio=True))
        field = self.only_field(win)
        win.field_pressed(field)
        settle(timeout_ms=150)
        first = self.held(win, field)
        win.field_pressed(field)
        settle(timeout_ms=150)
        self.assertEqual(self.held(win, field), first)

    def test_a_box_the_document_already_ticked_clears(self):
        win = self.window(tickable(value="/Yes"))
        field = self.only_field(win)
        self.assertGreater(self.blue_on_screen(win), 0, "it starts ticked")
        win.field_pressed(field)
        settle(timeout_ms=150)
        self.assertEqual(self.blue_on_screen(win), 0)

    # -- and it is an edit --------------------------------------------------

    def test_it_marks_the_document_modified(self):
        win = self.window()
        win.field_pressed(self.only_field(win))
        self.assertTrue(win.modified)

    def test_undo_takes_the_tick_back(self):
        win = self.window()
        field = self.only_field(win)
        win.field_pressed(field)
        settle(timeout_ms=150)
        win.undo()
        settle(timeout_ms=200)
        self.assertIsNone(self.held(win, field))
        self.assertEqual(self.blue_on_screen(win), 0)

    # -- and after a save ---------------------------------------------------

    def saved(self, win):
        out = temp_path("ticked.pdf")
        self.assertTrue(win._write([out], win.model.pages))
        return pikepdf.open(out)

    def test_the_tick_reaches_the_file(self):
        win = self.window()
        win.field_pressed(self.only_field(win))
        settle(timeout_ms=150)
        saved = self.saved(win)
        widget = saved.pages[0].Annots[0]
        self.assertEqual(str(widget.AS), "/Yes")
        self.assertEqual(str(widget.Parent.V), "/Yes")

    def test_an_untouched_form_is_written_unchanged(self):
        win = self.window(tickable(value="/Yes"))
        saved = self.saved(win)
        self.assertEqual(str(saved.pages[0].Annots[0].AS), "/Yes")

    def test_every_widget_of_the_field_follows_the_value(self):
        """Two pages, one field: ticking reaches both drawings of it."""
        win = self.window(tickable(pages=2))
        win.field_pressed(self.only_field(win))
        settle(timeout_ms=150)
        saved = self.saved(win)
        self.assertEqual([str(p.Annots[0].AS) for p in saved.pages],
                         ["/Yes", "/Yes"])

    # -- and what a click must not do ---------------------------------------

    def test_a_read_only_field_does_not_move(self):
        win = self.window()
        field = self.only_field(win)
        field.flags = 1                      # the document saying no
        win.field_pressed(field)
        self.assertIsNone(self.held(win, field))
        self.assertFalse(win.modified)

    def test_a_text_field_is_left_for_later(self):
        win = self.window(document_with_annotation("/Widget"))
        field = self.only_field(win)
        self.assertEqual(field.kind, "/Tx")
        win.field_pressed(field)
        self.assertIsNone(self.held(win, field))


def typable(value=None, size=12, quadding=None, name="text"):
    """One page, one single-line text field, with a font it can be drawn in.

    `/Helv` with no descriptor on purpose: it is a standard-14 name, which is
    what a real form's `/DA` usually says, and it exercises the fallback
    metrics rather than a font that carries its own.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 120))
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica))
    widget = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
        FT=pikepdf.Name.Tx, T=pikepdf.String(name), F=4,
        Rect=pikepdf.Array([20, 40, 280, 70]),
        DA=pikepdf.String(f"/Helv {size} Tf 0 g")))
    if value is not None:
        widget[pikepdf.Name.V] = pikepdf.String(value)
    if quadding is not None:
        widget[pikepdf.Name.Q] = quadding
    pdf.pages[0][pikepdf.Name.Annots] = pikepdf.Array([widget])
    pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
        Fields=pikepdf.Array([widget]),
        DR=pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font)))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestGeneratingATextAppearance(unittest.TestCase):
    """Drawing a value that is not in the file.

    Most text fields in real forms have no appearance at all -- 0 of 164 in
    one corpus form -- so this draws from nothing rather than editing what is
    there, which is the opposite of a tick box.
    """

    def opened(self, data=None):
        pdf = pikepdf.open(io.BytesIO(data or typable()))
        self.addCleanup(pdf.close)
        return pdf, pdf.pages[0].Annots[0], pdf.Root.AcroForm

    def content(self, value, **kwargs):
        pdf, widget, acroform = self.opened(typable(**kwargs))
        stream = forms.text_appearance(pdf, widget, value, acroform)
        self.assertIsNotNone(stream)
        return bytes(stream.read_bytes()).decode("latin-1")

    def test_the_value_is_shown(self):
        self.assertIn("(hello) Tj", self.content("hello"))

    def test_the_font_and_size_come_from_the_da(self):
        self.assertIn("/Helv 12 Tf", self.content("x"))
        self.assertIn("/Helv 9 Tf", self.content("x", size=9))

    def test_the_colour_comes_from_the_da_too(self):
        """Four of the nine forms in the corpus write their fields in dark
        blue; black text in one of those reads as a rendering bug."""
        pdf, widget, acroform = self.opened()
        widget[pikepdf.Name.DA] = pikepdf.String("/Helv 10 Tf 0 0 .5 rg")
        stream = forms.text_appearance(pdf, widget, "x", acroform)
        self.assertIn("0 0 .5 rg", bytes(stream.read_bytes()).decode("latin-1"))

    def test_brackets_in_the_value_do_not_end_the_string(self):
        """`(`, `)` and `\\` are what ends a PDF literal string."""
        body = self.content(r"a (b) c \ d")
        self.assertIn(r"(a \(b\) c \\ d) Tj", body)

    def test_it_is_marked_as_a_text_field(self):
        """`/Tx BMC` is how a viewer knows this drawing is a field's, and may
        replace it."""
        self.assertTrue(self.content("x").startswith("/Tx BMC"))

    def test_it_is_clipped_to_the_box(self):
        """A long value stays inside its field rather than running across the
        page."""
        self.assertIn("re\nW\nn", self.content("x" * 200))

    def test_the_baseline_is_acrobats(self):
        """Taken from an appearance Acrobat wrote: a 25.2pt box at 12pt in a
        font of ascent 989 and descent -360 put it at 8.826."""
        self.assertAlmostEqual(
            forms.text_baseline(25.2, 12, 0.989, -0.360), 8.826, places=3)

    def test_an_empty_value_still_draws_nothing_visible(self):
        self.assertIn("() Tj", self.content(""))

    def test_a_field_with_no_resources_is_declined(self):
        """Rather than written with a font the viewer cannot resolve."""
        pdf, widget, _acroform = self.opened()
        del pdf.Root.AcroForm[pikepdf.Name.DR]
        self.assertIsNone(forms.text_appearance(pdf, widget, "x",
                                                pdf.Root.AcroForm))

    def test_auto_size_picks_something_that_fits(self):
        """A /DA size of 0 means fit the text to the box, which 6 to 8% of
        real fields ask for."""
        body = self.content("x", size=0)
        self.assertNotIn("/Helv 0 Tf", body)
        self.assertRegex(body, r"/Helv [\d.]+ Tf")


class TestTypingIntoAField(unittest.TestCase):
    """2.5's done-when: typing shows, survives undo, and saves."""

    def window(self, data=None):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("typable.pdf")
        with open(path, "wb") as handle:
            handle.write(data or typable())
        win = MainWindow()
        win.resize(700, 560)
        win.show()
        win.open_paths([path])
        settle(timeout_ms=600)
        win.set_read_mode(True)
        settle(timeout_ms=700)
        win.modified = False
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def field(self, win):
        return win.reader.canvas.fields().on_page(0)[0]

    def held(self, win, field):
        page = win.model.pages[field.page]
        return win.model.form_values.get(page.nfile, field.name)

    def ink(self, win):
        """Dark pixels on screen. The fixture's page is otherwise blank, so
        every one of them is the field's text."""
        canvas = win.reader.canvas
        shot = QImage(canvas.viewport().size(), QImage.Format_RGB32)
        shot.fill(0xFFFFFFFF)
        canvas.viewport().render(shot)
        return sum(1 for y in range(0, shot.height(), 2)
                   for x in range(0, shot.width(), 2)
                   if shot.pixelColor(x, y).red() < 120)

    def type_into(self, win, field, text):
        canvas = win.reader.canvas
        canvas.edit_field(field)
        settle(timeout_ms=120)
        self.assertIsNotNone(canvas.editing(), "an editor should have opened")
        canvas._editing[1].setText(text)
        canvas.finish_editing()
        settle(timeout_ms=250)

    # -- it shows ----------------------------------------------------------

    def test_an_empty_field_shows_nothing_until_it_is_typed_into(self):
        win = self.window()
        self.assertEqual(self.ink(win), 0, "a blank page and an empty field")
        self.type_into(win, self.field(win), "Hello")
        self.assertGreater(self.ink(win), 0)

    def test_what_was_typed_is_what_is_held(self):
        win = self.window()
        field = self.field(win)
        self.type_into(win, field, "Hello")
        self.assertEqual(self.held(win, field), "Hello")

    def test_clearing_a_field_is_an_edit_rather_than_a_reset(self):
        """"Never touched" and "deliberately emptied" must not look alike: the
        second has to keep the field empty, not fall back to the file."""
        win = self.window(typable(value="From the file"))
        field = self.field(win)
        self.assertGreater(self.ink(win), 0, "the file's value shows")
        self.type_into(win, field, "")
        self.assertEqual(self.held(win, field), "")
        self.assertEqual(self.ink(win), 0)

    def test_closing_the_editor_unchanged_is_not_an_edit(self):
        win = self.window(typable(value="From the file"))
        field = self.field(win)
        self.type_into(win, field, "From the file")
        self.assertIsNone(self.held(win, field))
        self.assertFalse(win.modified)

    # -- it survives undo ---------------------------------------------------

    def test_undo_takes_the_typing_back(self):
        win = self.window()
        field = self.field(win)
        self.type_into(win, field, "Hello")
        self.assertTrue(win.modified)
        win.undo()
        settle(timeout_ms=250)
        self.assertIsNone(self.held(win, field))
        self.assertEqual(self.ink(win), 0)

    def test_one_edit_is_one_undo(self):
        """`editingFinished` arrives again as the editor is taken away, and
        without a guard the value is committed twice."""
        win = self.window()
        field = self.field(win)
        self.type_into(win, field, "Hello")
        win.undo()
        settle(timeout_ms=250)
        self.assertIsNone(self.held(win, field),
                          "one undo should be enough")

    # -- and it saves -------------------------------------------------------

    def test_the_text_reaches_the_file_with_something_to_draw_it(self):
        win = self.window()
        field = self.field(win)
        self.type_into(win, field, "Hello")
        out = temp_path("typed.pdf")
        self.assertTrue(win._write([out], win.model.pages))
        saved = pikepdf.open(out)
        widget = saved.pages[0].Annots[0]
        self.assertEqual(str(widget.V), "Hello")
        self.assertIn(pikepdf.Name.AP, widget,
                      "a value with no appearance is invisible, which is the "
                      "fault this work began with")
        self.assertIn("(Hello) Tj",
                      bytes(widget.AP.N.read_bytes()).decode("latin-1"))

    def test_a_tick_box_still_does_not_open_an_editor(self):
        win = self.window(tickable())
        canvas = win.reader.canvas
        canvas.field_pressed.emit(self.field(win))
        self.assertIsNone(canvas.editing())


def signed(data=None, certify=False, placeholder=False, flags_only=False,
           usage_rights=False, visible=False):
    """``typable()`` with a signature field added to it.

    Structural rather than cryptographic. What the application reads is a
    ``/Sig`` field carrying a ``/V``, and nothing here validates a
    certificate: doing that is a sub-project that stays out, and refusing an
    edit does not need it.

    The keyword arguments build the near misses as well as the hit, because
    the near misses are what the corpus says real forms are full of.
    """
    pdf = pikepdf.open(io.BytesIO(data or typable()))
    acroform = pdf.Root[pikepdf.Name.AcroForm]
    if flags_only:
        # What five corpus forms do: declare AppendOnly with no signature
        # field anywhere in them.
        acroform[pikepdf.Name.SigFlags] = 2
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()
    value = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Sig,
        Filter=pikepdf.Name("/Adobe.PPKLite"),
        SubFilter=pikepdf.Name("/adbe.pkcs7.detached"),
        ByteRange=pikepdf.Array([0, 100, 200, 300]),
        Contents=pikepdf.String(b"\x00" * 16)))
    if usage_rights:
        # Reader-enabling, which five corpus forms carry. It grants rights
        # rather than attesting to content, and must not count.
        pdf.Root[pikepdf.Name.Perms] = pikepdf.Dictionary(UR3=value)
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()
    field = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
        FT=pikepdf.Name.Sig, T=pikepdf.String("signature"), F=132,
        Rect=pikepdf.Array([0, 0, 0, 0])))
    if visible:
        # A signature that puts something on the page, which an invisible one
        # -- the shape both real samples take -- does not.
        drawing = pikepdf.Stream(pdf, b"0 0 1 rg 0 0 80 20 re f\n")
        drawing[pikepdf.Name.Type] = pikepdf.Name.XObject
        drawing[pikepdf.Name.Subtype] = pikepdf.Name.Form
        drawing[pikepdf.Name.BBox] = pikepdf.Array([0, 0, 80, 20])
        field[pikepdf.Name.Rect] = pikepdf.Array([200, 10, 280, 30])
        field[pikepdf.Name.AP] = pikepdf.Dictionary(N=drawing)
    if not placeholder:
        field[pikepdf.Name.V] = value
        if certify:
            value[pikepdf.Name.Reference] = pikepdf.Array([pikepdf.Dictionary(
                Type=pikepdf.Name.SigRef,
                TransformMethod=pikepdf.Name.DocMDP,
                TransformParams=pikepdf.Dictionary(
                    Type=pikepdf.Name.TransformParams, P=1))])
            pdf.Root[pikepdf.Name.Perms] = pikepdf.Dictionary(DocMDP=value)
    pdf.pages[0][pikepdf.Name.Annots].append(field)
    acroform[pikepdf.Name.Fields].append(field)
    acroform[pikepdf.Name.SigFlags] = 3
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestWhetherADocumentIsSigned(unittest.TestCase):
    """The predicate, and the three near misses that must not trip it.

    Every one of the misses is something a real form in the corpus does, and
    reading any of them as a signature would refuse to fill documents that
    every other viewer fills happily.
    """

    def pdf(self, data):
        return pikepdf.open(io.BytesIO(data))

    def test_a_signed_field_counts_and_is_named(self):
        pdf = self.pdf(signed())
        self.assertTrue(forms.is_signed(pdf))
        self.assertEqual(forms.signatures_in(pdf), ["signature"])

    def test_a_certification_counts(self):
        pdf = self.pdf(signed(certify=True))
        self.assertTrue(forms.is_signed(pdf))

    def test_an_empty_signature_field_does_not(self):
        """A placeholder is an invitation to sign, not a signature.

        The insurance form that began this work carries two of them, and it
        has to stay fillable.
        """
        pdf = self.pdf(signed(placeholder=True))
        self.assertFalse(forms.is_signed(pdf))
        self.assertEqual(forms.signatures_in(pdf), [])

    def test_sigflags_alone_does_not(self):
        self.assertFalse(forms.is_signed(self.pdf(signed(flags_only=True))))

    def test_a_usage_rights_signature_does_not(self):
        """`/Perms /UR3` Reader-enables a form; it says nothing about content.

        Five corpus forms carry one, the 1040 and the W-9 among them.
        """
        self.assertFalse(forms.is_signed(self.pdf(signed(usage_rights=True))))

    def test_a_plain_form_does_not(self):
        self.assertFalse(forms.is_signed(self.pdf(typable())))

    def test_rubbish_is_not_a_signature(self):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(100, 100))
        self.assertFalse(forms.is_signed(pdf))


class TestASignedDocumentRefusesAFill(unittest.TestCase):
    """2.7's done-when: a signed form says why rather than being quietly inert.

    Refused in both directions a click can go -- the editor must not open over
    a text field, and a tick box must not toggle -- because the canvas decides
    which of those to do before the window hears about the click at all.
    """

    def window(self, data):
        from pdfarranger_qt.mainwindow import MainWindow

        path = temp_path("signed.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        win = MainWindow()
        win.resize(700, 560)
        win.show()
        win.open_paths([path])
        settle(timeout_ms=600)
        win.set_read_mode(True)
        settle(timeout_ms=700)
        win.modified = False
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def text_field(self, win):
        for field in win.reader.canvas.fields().on_page(0):
            if field.kind == "/Tx":
                return field
        self.fail("the fixture should have a text field")

    def click(self, win, field):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        canvas = win.reader.canvas
        where = canvas._field_rect(field)
        self.assertIsNotNone(where, "the field should be on screen")
        point = where.center()
        QApplication.sendEvent(canvas.viewport(), QMouseEvent(
            QEvent.MouseButtonPress, point,
            canvas.viewport().mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=200)

    def test_an_unsigned_document_still_opens_an_editor(self):
        """The control. Without it the rest passes on a broken canvas."""
        win = self.window(typable())
        self.click(win, self.text_field(win))
        self.assertIsNotNone(win.reader.canvas.editing())

    def test_a_signed_document_opens_no_editor(self):
        win = self.window(signed())
        self.click(win, self.text_field(win))
        self.assertIsNone(win.reader.canvas.editing())

    def test_a_certified_document_opens_no_editor(self):
        win = self.window(signed(certify=True))
        self.click(win, self.text_field(win))
        self.assertIsNone(win.reader.canvas.editing())

    def test_a_placeholder_signature_does_not_refuse(self):
        """The case that must keep working: unsigned signature fields."""
        win = self.window(signed(placeholder=True))
        self.click(win, self.text_field(win))
        self.assertIsNotNone(win.reader.canvas.editing())

    def test_the_refusal_says_why(self):
        win = self.window(signed())
        self.click(win, self.text_field(win))
        self.assertIn("signed", win.statusBar().currentMessage())

    def test_a_tick_box_in_a_signed_document_does_not_toggle(self):
        win = self.window(signed(data=tickable()))
        field = next(f for f in win.reader.canvas.fields().on_page(0)
                     if f.kind == "/Btn")
        page = win.model.pages[field.page]
        self.click(win, field)
        self.assertIsNone(win.model.form_values.get(page.nfile, field.name))

    def test_the_value_is_unchanged_even_if_a_handler_is_reached(self):
        """The window guards as well as the canvas.

        Belt and braces on purpose: the canvas stops the gesture, and the
        handlers refuse the value, so neither alone is the only thing
        standing between a signed document and a broken signature.
        """
        win = self.window(signed())
        field = self.text_field(win)
        page = win.model.pages[field.page]
        win.field_edited(field, "typed anyway")
        self.assertIsNone(win.model.form_values.get(page.nfile, field.name))
        self.assertFalse(win.modified)


class TestExportLeavesNoSignatureBehind(unittest.TestCase):
    """2.8's done-when, and a bug that was there whichever way D5 had gone.

    A document built by export is a new one. The bytes a `/ByteRange` names
    are gone, `/Perms` does not survive a new root and neither does `/DSS` --
    so a signature carried into it asserts something about a file that never
    existed, which a viewer reports as a broken signature and a reader cannot
    tell from tampering. Worse on a certified document: the `/Reference`
    declaring `DocMDP P=1`, no changes permitted, travelled while the
    `/Perms` entry naming it did not.
    """

    def exported(self, data, order=None):
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        path = temp_path("signed-export.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(path)
        if order is not None:
            pages = [pages[i] for i in order]
        self.raw = get_in_memory_pdf(pages, docs.files_for_export())
        return pikepdf.open(io.BytesIO(self.raw))

    def signature_fields(self, pdf):
        acroform = pdf.Root.get(pikepdf.Name.AcroForm)
        return [f for f in (acroform.get(pikepdf.Name.Fields, [])
                            if acroform is not None else [])
                if f.get(pikepdf.Name.FT) == pikepdf.Name.Sig]

    def test_no_signature_field_survives(self):
        out = self.exported(signed())
        self.assertEqual(self.signature_fields(out), [])

    def test_a_certification_does_not_survive_either(self):
        """The one that mattered most: it claimed no changes were permitted."""
        out = self.exported(signed(certify=True))
        self.assertEqual(self.signature_fields(out), [])
        self.assertNotIn(pikepdf.Name.Perms, out.Root)
        self.assertNotIn(b"DocMDP", self.raw)

    def test_sigflags_is_not_carried(self):
        """It says a signature exists and that the file is append-only.

        Neither is true of a document assembled from scratch.
        """
        out = self.exported(signed())
        acroform = out.Root.get(pikepdf.Name.AcroForm)
        if acroform is not None:
            self.assertNotIn(pikepdf.Name.SigFlags, acroform)

    def test_the_signature_dictionary_is_emptied_not_just_unhooked(self):
        """Unreferenced is not the same as gone.

        qpdf does not collect unreachable objects. Dropping the reference
        alone left the whole signature in the output of the certified sample
        -- 6,453 bytes of PKCS#7 and the signer's certificate chain up to the
        Adobe root -- unreachable, so harmless to a viewer, but carried into a
        document that has nothing to do with it.

        Asserted on the dictionary rather than on the saved bytes, because
        whether the orphan is written at all turns out to depend on qpdf: it
        keeps one for that sample and collects one from a fixture built here.
        What this code does is empty it, so that is what is checked.
        """
        from pdfarranger_qt.export import _blank_signature

        pdf = pikepdf.open(io.BytesIO(signed()))
        widget = next(a for a in pdf.pages[0][pikepdf.Name.Annots]
                      if a.get(pikepdf.Name.FT) == pikepdf.Name.Sig)
        value = widget[pikepdf.Name.V]
        self.assertIn(pikepdf.Name.Contents, value)
        _blank_signature(widget)
        self.assertEqual(len(value.keys()), 0,
                         "nothing of the signature should be left in it")

    def test_nothing_of_the_signature_reaches_the_saved_bytes(self):
        self.exported(signed())
        self.assertNotIn(b"adbe.pkcs7", self.raw)

    def test_an_invisible_signature_takes_its_annotation_with_it(self):
        out = self.exported(signed())
        widgets = [a for page in out.pages
                   for a in page.get(pikepdf.Name.Annots, [])
                   if a.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget]
        self.assertEqual(len(widgets), 1, "only the text field should remain")
        self.assertEqual(str(widgets[0].get(pikepdf.Name.FT)), "/Tx")

    def test_a_visible_signature_keeps_its_drawing(self):
        """The appearance is page content; it is the dictionary that lied.

        Deleting what the user can see would be a different kind of wrong.
        """
        out = self.exported(signed(visible=True))
        stamps = [a for page in out.pages
                  for a in page.get(pikepdf.Name.Annots, [])
                  if a.get(pikepdf.Name.Subtype) == pikepdf.Name.Stamp]
        self.assertEqual(len(stamps), 1)
        self.assertIn(pikepdf.Name.AP, stamps[0])
        for key in (pikepdf.Name.FT, pikepdf.Name.V, pikepdf.Name.T):
            self.assertNotIn(key, stamps[0], "a picture, not a field")

    def test_an_ordinary_form_is_untouched(self):
        """The control. Stripping signatures must not cost a form its fields."""
        out = self.exported(typable())
        acroform = out.Root.get(pikepdf.Name.AcroForm)
        self.assertIsNotNone(acroform)
        self.assertEqual(len(acroform.get(pikepdf.Name.Fields, [])), 1)

    def test_the_source_document_is_not_damaged(self):
        """The strip edits the output in place, so this is worth holding.

        A source is reused for every later export; emptying its signature
        instead of the copy's would break the second save in a session.
        """
        import warnings

        path = temp_path("signed-source.pdf")
        with open(path, "wb") as handle:
            handle.write(signed())
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            get_in_memory_pdf(pages, docs.files_for_export())
            unreachable = [w for w in caught
                           if "not reachable" in str(w.message)]
        self.assertEqual(unreachable, [], "no orphaned widgets")
        with pikepdf.open(path) as source:
            self.assertTrue(forms.is_signed(source),
                            "the original must still be signed")

