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

"""Annotations are drawn.

They were not, and nothing said so: a highlight, a sticky note, a stamp and a
freehand scribble all live in the page's ``/Annots`` rather than in its content
stream, and PDFium draws none of them unless asked. A document somebody had
commented on arrived looking pristine.

The fixtures are built here rather than checked in, because what each one has
to contain is the point of the test and a binary fixture hides it.
"""

import io
import unittest

import pikepdf
from PySide6.QtCore import QBuffer, QByteArray, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

from pdfarranger_qt.render import ANNOTATIONS


def document_with_annotation(subtype, matrix=None, bbox=(0, 0, 200, 100),
                             rect=(100, 150, 300, 250), flags=4):
    """One blank page carrying one annotation with a blue appearance.

    The blue fills the whole BBox, so that counting it says where the
    appearance was placed and at what size. Nothing else on the page is blue.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(400, 400))
    page = pdf.pages[0]
    fill = (f"0 0 1 rg {bbox[0]} {bbox[1]} "
            f"{bbox[2] - bbox[0]} {bbox[3] - bbox[1]} re f\n").encode()
    appearance = pikepdf.Stream(pdf, fill)
    appearance[pikepdf.Name.Type] = pikepdf.Name.XObject
    appearance[pikepdf.Name.Subtype] = pikepdf.Name.Form
    appearance[pikepdf.Name.BBox] = pikepdf.Array(list(bbox))
    if matrix is not None:
        appearance[pikepdf.Name.Matrix] = pikepdf.Array(list(matrix))
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name(subtype),
        Rect=pikepdf.Array(list(rect)),
        F=flags,
        AP=pikepdf.Dictionary(N=appearance))
    if subtype == "/Widget":
        annot[pikepdf.Name.FT] = pikepdf.Name.Tx
        annot[pikepdf.Name.T] = pikepdf.String("a field")
        annot[pikepdf.Name.V] = pikepdf.String("a value")
        pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
            Fields=pikepdf.Array([annot]))
    page[pikepdf.Name.Annots] = pikepdf.Array([annot])
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def blue_pixels(data, flag=ANNOTATIONS, page=0, size=400):
    """How much of the annotation's blue made it onto the page."""
    document = QPdfDocument()
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QBuffer.ReadOnly)
    document.load(buffer)
    options = QPdfDocumentRenderOptions()
    if flag is not None:
        options.setRenderFlags(flag)
    image = document.render(page, QSize(size, size), options)
    # PDFium leaves the paper transparent, so composite before counting or
    # every pixel reads as ink.
    flat = QImage(image.size(), QImage.Format_RGB32)
    flat.fill(0xFFFFFFFF)
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    found = 0
    for y in range(0, flat.height(), 2):
        for x in range(0, flat.width(), 2):
            colour = flat.pixelColor(x, y)
            if colour.blue() > 150 and colour.red() < 100:
                found += 1
    return found


class TestTheFlagIsWhatDrawsThem(unittest.TestCase):
    """Established by measurement before the flag was set anywhere."""

    def test_an_annotation_is_invisible_without_the_flag(self):
        data = document_with_annotation("/Square")
        self.assertEqual(blue_pixels(data, flag=None), 0)

    def test_and_visible_with_it(self):
        data = document_with_annotation("/Square")
        self.assertGreater(blue_pixels(data), 0)

    def test_a_widget_is_invisible_either_way(self):
        """PDFium excludes form fields from page rendering by design.

        It leaves them to a form-fill module QtPdf never initialises, so the
        same appearance stream under /Subtype /Widget draws nothing whatever
        the flag says. This is why showing a filled form needs more than a
        render flag, and the test exists so that stops being a surprise.
        """
        data = document_with_annotation("/Widget")
        self.assertEqual(blue_pixels(data, flag=None), 0)
        self.assertEqual(blue_pixels(data), 0)

    def test_a_hidden_annotation_stays_hidden(self):
        """Bit 2 of /F is Hidden, and honouring it is the renderer's job."""
        data = document_with_annotation("/Square", flags=2)
        self.assertEqual(blue_pixels(data), 0)


class TestTheGridDrawsThem(unittest.TestCase):
    """End to end through the thumbnail pipeline, not a flag inspected."""

    def thumbnail(self, data):
        import os

        from support import temp_path

        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.render import FileDocuments, RenderTask

        path = temp_path("annotated.pdf")
        with open(path, "wb") as handle:
            handle.write(data)
        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        page = docs.add_file(path)[0]
        provider = FileDocuments()
        self.addCleanup(provider.close)
        task = RenderTask(("k",), page.copyname, None, page.npage, page.angle,
                          page.crop, page.hide, 400)
        image = task.render(provider)
        self.assertIsNotNone(image, f"nothing rendered from {os.path.basename(path)}")
        return image

    def blue(self, image):
        flat = QImage(image.size(), QImage.Format_RGB32)
        flat.fill(0xFFFFFFFF)
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        found = 0
        for y in range(0, flat.height(), 2):
            for x in range(0, flat.width(), 2):
                colour = flat.pixelColor(x, y)
                if colour.blue() > 150 and colour.red() < 100:
                    found += 1
        return found

    def test_a_thumbnail_shows_an_annotation(self):
        image = self.thumbnail(document_with_annotation("/Square"))
        self.assertGreater(self.blue(image), 0,
                           "the grid draws pages through RenderTask, so a "
                           "commented document must show its comments there")

    def test_a_thumbnail_does_not_invent_one(self):
        """A page with no annotation has no blue, so the check above means
        something."""
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(400, 400))
        out = io.BytesIO()
        pdf.save(out)
        self.assertEqual(self.blue(self.thumbnail(out.getvalue())), 0)


class TestAppearanceGeometryIsTheRenderersJob(unittest.TestCase):
    """Why the appearance is not stamped into the content stream by hand.

    An appearance stream is placed by transforming its BBox by its Matrix and
    fitting the result to the annotation's Rect. Of the 74 appearances in the
    form that prompted this work, every one had a Matrix and 45 had a BBox that
    did not match the Rect -- one 18.2pt tall in an 11.5pt box. Translating the
    stream to the corner of the Rect, which is the obvious thing to write,
    draws those at the wrong size.
    """

    def test_an_oversized_appearance_is_fitted_to_the_rectangle(self):
        """The blue fills the Rect rather than spilling past it."""
        # A BBox twice the Rect: fitted, it still covers exactly the Rect.
        data = document_with_annotation(
            "/Square", bbox=(0, 0, 400, 200), rect=(100, 150, 300, 250))
        fitted = blue_pixels(data)
        # The Rect is 200x100 of a 400x400 page, sampled every other pixel.
        expected = (200 / 400 * 400 / 2) * (100 / 400 * 400 / 2)
        self.assertAlmostEqual(fitted, expected, delta=expected * 0.1,
                               msg="the appearance should fill its Rect")

    def test_a_matrix_does_not_move_it_off_the_rectangle(self):
        """A rotating Matrix changes what is drawn, never where it lands."""
        upright = blue_pixels(document_with_annotation("/Square"))
        turned = blue_pixels(document_with_annotation(
            "/Square", matrix=(0, 1, -1, 0, 0, 0)))
        self.assertGreater(upright, 0)
        self.assertGreater(turned, 0,
                           "a rotated appearance is still inside its Rect")


class TestTheFormSurvivesASave(unittest.TestCase):
    """Export built a new document and left /AcroForm behind.

    The widgets travelled with their pages; the form dictionary they belong to
    hangs off the document root and nothing copied it. A filled insurance form
    came out with all 23 of its answers still in the annotations and nothing
    interactive able to reach them -- 82 fields in, none out, with pikepdf
    warning as it happened.
    """

    def saved(self, *documents, keep=None):
        """Put ``documents`` through a real export and reopen the result."""
        from support import temp_path

        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = []
        for n, data in enumerate(documents):
            path = temp_path(f"form-{n}.pdf")
            with open(path, "wb") as handle:
                handle.write(data)
            pages.extend(docs.add_file(path))
        if keep is not None:
            pages = [pages[i] for i in keep]
        out = get_in_memory_pdf(pages, docs.files_for_export())
        return pikepdf.open(io.BytesIO(out))

    def form(self, pdf):
        return pdf.Root.get(pikepdf.Name.AcroForm)

    def test_the_form_dictionary_comes_back(self):
        saved = self.saved(document_with_annotation("/Widget"))
        self.assertIsNotNone(self.form(saved))
        self.assertEqual(len(self.form(saved).Fields), 1)

    def test_the_field_keeps_its_value(self):
        saved = self.saved(document_with_annotation("/Widget"))
        field = self.form(saved).Fields[0]
        self.assertEqual(str(field.V), "a value")
        self.assertEqual(str(field.T), "a field")

    def test_the_widget_is_reachable_from_the_form(self):
        """What pikepdf warned about, and what Acrobat needs to display it."""
        saved = self.saved(document_with_annotation("/Widget"))
        field = self.form(saved).Fields[0]
        on_page = list(saved.pages[0].Annots)
        self.assertIn(field.objgen, [a.objgen for a in on_page])

    def test_a_document_with_no_fields_gets_no_form(self):
        """Inventing an empty /AcroForm would claim every PDF is a form."""
        saved = self.saved(document_with_annotation("/Square"))
        self.assertIsNone(self.form(saved))

    def test_an_export_of_a_selection_keeps_only_the_fields_it_kept(self):
        """/Fields naming a widget that is not in the document points nowhere."""
        saved = self.saved(document_with_annotation("/Widget"),
                           document_with_annotation("/Widget"),
                           keep=[0])
        self.assertEqual(len(self.form(saved).Fields), 1)

    def test_merged_forms_keep_both_fields(self):
        saved = self.saved(document_with_annotation("/Widget"),
                           document_with_annotation("/Widget"))
        self.assertEqual(len(self.form(saved).Fields), 2)


class TestSharedFieldNamesAreReported(unittest.TestCase):
    """Two fields with one name are one field, and merging can create that.

    A value is keyed by the fully qualified name, so merging two copies of a
    form gives one field with two widgets: type into one and the other follows.
    Acrobat renames on import; saying so is cheaper and less surprising than
    renaming somebody's fields silently.
    """

    def export_two(self, second_name):
        from support import temp_path

        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import export

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = []
        for n, name in enumerate(("a field", second_name)):
            data = document_with_annotation("/Widget")
            pdf = pikepdf.open(io.BytesIO(data))
            pdf.pages[0].Annots[0][pikepdf.Name.T] = pikepdf.String(name)
            path = temp_path(f"named-{n}.pdf")
            pdf.save(path)
            pages.extend(docs.add_file(path))
        return export(docs.files_for_export(), pages, {},
                      [temp_path("merged.pdf")])

    def test_a_clash_is_reported(self):
        self.assertIn("share a name", self.export_two("a field"))

    def test_distinct_names_are_not(self):
        self.assertNotIn("share a name", self.export_two("another field"))
