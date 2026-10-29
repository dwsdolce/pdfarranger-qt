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

    def test_a_rewritten_widget_is_still_a_field(self):
        """The reader shows the copy where widgets became stamps, and the
        click has to land on them there."""
        from pdfarranger_qt import forms

        data = forms.rendered_bytes(document_with_annotation("/Widget"))
        self.assertEqual(len(self.map_of(data)), 1)

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
