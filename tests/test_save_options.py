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

"""The options that change how a document is written, not what is in it.

Both export paths get the same tests: `export_doc` builds the file itself and
`export_doc_job` hands it to qpdf, and the two apply these options by entirely
different means.
"""

import os
import unittest

import pikepdf
from support import QtDocumentTestCase, temp_path

from pdfarranger_qt import viewer
from pdfarranger_qt.export import HAS_PIKEPDF8, SaveOptions, export

#: Something to put in the file, so a metadata test has something to remove.
#: XMP tags, which is what the properties dialog deals in; the Info dictionary
#: is written from them on the way out.
METADATA = {
    "{http://purl.org/dc/elements/1.1/}title": "A Title",
    "{http://purl.org/dc/elements/1.1/}creator": ["An Author"],
}


class SaveOptionsTestCase(QtDocumentTestCase):
    """Runs an export with options, on whichever path the subclass names."""

    #: True for the pikepdf Job path, which is what "preserve first" selects.
    job_path = False

    def setUp(self):
        super().setUp()
        if self.job_path and not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8 has no Job interface")

    def save(self, options=None, mdata=None, name="out.pdf"):
        path = self.out(name)
        export(self.docs.files_for_export(), self.model.pages, mdata or {},
               [path], preserve_first_document=self.job_path, options=options)
        return path


class TestLinearize(SaveOptionsTestCase):
    def test_off_by_default(self):
        with pikepdf.open(self.save()) as pdf:
            self.assertFalse(pdf.is_linearized)

    def test_on_when_asked(self):
        with pikepdf.open(self.save(SaveOptions(linearize=True))) as pdf:
            self.assertTrue(pdf.is_linearized)


class TestLinearizeJob(TestLinearize):
    job_path = True


class TestStripMetadata(SaveOptionsTestCase):
    def test_kept_by_default(self):
        with pikepdf.open(self.save(mdata=METADATA)) as pdf:
            self.assertEqual(str(pdf.docinfo.get("/Title", "")), "A Title")

    def test_removed_when_asked(self):
        path = self.save(SaveOptions(strip_metadata=True), mdata=METADATA)
        with pikepdf.open(path) as pdf:
            # The old Info dictionary and the XMP packet are two separate
            # places to hide a name; both have to go.
            self.assertEqual(len(pdf.docinfo), 0)
            self.assertNotIn(pikepdf.Name.Metadata, pdf.Root)
            with pdf.open_metadata() as meta:
                self.assertEqual(len(list(meta.keys())), 0)

    def test_the_file_still_opens(self):
        """Stripping must not leave a document nothing will read."""
        path = self.save(SaveOptions(strip_metadata=True), mdata=METADATA)
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)


class TestStripMetadataJob(TestStripMetadata):
    job_path = True


class TestCompress(SaveOptionsTestCase):
    def test_the_file_still_opens(self):
        path = self.save(SaveOptions(compress=True))
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_it_is_not_larger(self):
        """The one claim worth making: compressing never costs space here.

        Not "it is smaller": how much a real file shrinks depends entirely on
        what is in it, and one already full of compressed images will not move.
        """
        plain = os.path.getsize(self.save(name="plain.pdf"))
        small = os.path.getsize(self.save(SaveOptions(compress=True), name="small.pdf"))
        self.assertLessEqual(small, plain)

    def test_object_streams_are_generated(self):
        """The measurable half of it, on a fixture that has none to begin with."""
        with pikepdf.open(self.save(SaveOptions(compress=True))) as pdf:
            kinds = {obj.get("/Type") for obj in pdf.objects
                     if isinstance(obj, pikepdf.Stream)}
            self.assertIn(pikepdf.Name.ObjStm, kinds)


class TestCompressJob(TestCompress):
    job_path = True


class TestViewerPreferences(SaveOptionsTestCase):
    def test_nothing_written_by_default(self):
        with pikepdf.open(self.save()) as pdf:
            self.assertTrue(viewer.Preferences.read(pdf).is_empty())

    def test_round_trip(self):
        wanted = viewer.Preferences(
            page_mode="UseOutlines",
            page_layout="TwoColumnRight",
            flags=frozenset({"HideToolbar", "DisplayDocTitle"}),
        )
        with pikepdf.open(self.save(SaveOptions(viewer=wanted))) as pdf:
            self.assertEqual(viewer.Preferences.read(pdf), wanted)


class TestViewerPreferencesJob(TestViewerPreferences):
    job_path = True


class TestOptionsCombine(SaveOptionsTestCase):
    """The options are independent; asking for all of them must still work."""

    def test_all_at_once(self):
        options = SaveOptions(
            linearize=True, strip_metadata=True, compress=True,
            viewer=viewer.Preferences(page_mode="UseThumbs"),
        )
        with pikepdf.open(self.save(options, mdata=METADATA)) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            self.assertTrue(pdf.is_linearized)
            self.assertEqual(len(pdf.docinfo), 0)
            self.assertEqual(viewer.Preferences.read(pdf).page_mode, "UseThumbs")


class TestOptionsCombineJob(TestOptionsCombine):
    job_path = True


class TestDamagedSource(SaveOptionsTestCase):
    """Compressing must not turn a recoverable file into an unopenable one."""

    job_path = True

    def test_the_fixture_is_still_damaged(self):
        """The premise of the next test, which is worthless without it."""
        from support import TEST_PDF

        with self.assertRaises(pikepdf.PdfError):
            pikepdf.open(TEST_PDF, attempt_recovery=False)

    def test_compressing_it_produces_a_file_that_opens_strictly(self):
        path = self.save(SaveOptions(compress=True))
        with pikepdf.open(path, attempt_recovery=False) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_the_output_trailer_has_a_size(self):
        with pikepdf.open(self.save(), attempt_recovery=False) as pdf:
            self.assertIn(pikepdf.Name.Size, pdf.trailer)


class TestObjectStreamsAreAlwaysWritten(unittest.TestCase):
    """Not an option: smaller files that readers open faster.

    Object streams pack the small objects -- page dictionaries, annotations,
    the outline -- into compressed streams. Measured on a 1,590-page book,
    155.3 MB without them against 151.0 MB with, and reading every page's
    size 1,955 ms against 1,411. The document it was made from has 1,928.

    They used to be tied to the Compress checkbox, so a book whose images had
    just been compressed lost the packing when it was saved with that box
    unticked.
    """

    def test_they_are_written_whatever_else_is_asked_for(self):
        from pdfarranger_qt.export import SaveOptions

        for options in (SaveOptions(), SaveOptions(compress=True),
                        SaveOptions(linearize=True),
                        SaveOptions(compress=False, strip_metadata=True)):
            with self.subTest(options=options):
                self.assertEqual(
                    options.save_kwargs().get("object_stream_mode"),
                    pikepdf.ObjectStreamMode.generate)

    def test_compress_still_only_means_recompressing(self):
        """The checkbox keeps its own meaning, which is now its whole meaning."""
        from pdfarranger_qt.export import SaveOptions

        plain = SaveOptions().save_kwargs()
        self.assertNotIn("compress_streams", plain)
        self.assertNotIn("recompress_flate", plain)

        compressed = SaveOptions(compress=True).save_kwargs()
        self.assertTrue(compressed["compress_streams"])
        self.assertTrue(compressed["recompress_flate"])

    def test_a_saved_document_really_has_them(self):
        """The kwargs are a claim; the file is the evidence."""
        from pdfarranger_qt.export import SaveOptions, balance_page_tree

        pdf = pikepdf.Pdf.new()
        for number in range(300):
            page = pdf.add_blank_page(page_size=(612, 792))
            page.UserUnit = number
        balance_page_tree(pdf)
        out = temp_path("objstm.pdf")
        pdf.save(out, **SaveOptions().save_kwargs())

        with pikepdf.open(out) as written:
            streams = sum(1 for obj in written.objects
                          if isinstance(obj, pikepdf.Stream)
                          and str(obj.get("/Type", "")) == "/ObjStm")
        self.assertGreater(streams, 0, "no object streams were written")
