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

"""Painting pages onto a QPrinter."""

import os
import pikepdf

from support import QtDocumentTestCase


class TestPrinting(QtDocumentTestCase):
    """QPrinter can write a PDF with no dialog or spooler, so this is testable."""

    def printer(self, path):
        """A PDF-writing QPrinter: no dialog, no spooler, no printer needed.

        Constructing one under the offscreen platform raises a harmless
        first-chance COM exception (REGDB_E_IIDNOTREG) because there is no print
        subsystem to query. It does not stop anything, but faulthandler prints
        a stack trace for each one, so it is muted just around the call.
        """
        import faulthandler

        from PySide6.QtPrintSupport import QPrinter

        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            printer = QPrinter(QPrinter.HighResolution)
        finally:
            if was_enabled:
                faulthandler.enable()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        return printer

    def out(self, name="print.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_prints_every_page(self):
        from pdfarranger_qt import printing

        path = self.out()
        printed = printing.print_pages(self.model.pages, self.docs.files_for_export(),
                                       self.printer(path), dpi=72)
        self.assertEqual(printed, 2)
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_auto_rotate_does_not_change_the_sheet_mid_job(self):
        """Regression: setPageOrientation() between pages wedged the native
        Windows engine after the output had already been written."""
        from PySide6.QtGui import QPageLayout
        from pdfarranger_qt import printing

        self.model.rotate([1], 90)  # one landscape page among portrait ones
        path = self.out()
        printer = self.printer(path)
        printing.prepare(printer, self.model.pages, auto_rotate=True)
        before = printer.pageLayout().orientation()
        printing.print_pages(self.model.pages, self.docs.files_for_export(),
                             printer, dpi=72, auto_rotate=True)
        self.assertEqual(printer.pageLayout().orientation(), before,
                         "the sheet orientation must be fixed for the whole job")

    def test_dominant_orientation(self):
        from PySide6.QtGui import QPageLayout
        from pdfarranger_qt import printing

        self.assertEqual(printing.dominant_orientation(self.model.pages),
                         QPageLayout.Portrait)
        for page in self.model.pages:
            page.rotate(90)
        self.assertEqual(printing.dominant_orientation(self.model.pages),
                         QPageLayout.Landscape)

    def test_mismatched_pages_are_rotated_to_fit(self):
        from pdfarranger_qt import printing
        from PySide6.QtGui import QImage

        portrait = QImage(100, 200, QImage.Format_RGB32)
        turned = printing._match_orientation(portrait, sheet_is_landscape=True)
        self.assertGreater(turned.width(), turned.height())
        # A page that already matches is handed back untouched.
        same = printing._match_orientation(portrait, sheet_is_landscape=False)
        self.assertIs(same, portrait)

    def test_progress_starts_before_any_page_is_rendered(self):
        """The first tick fires right after QPainter.begin() returns.

        That is when the spooler's own save dialog has been answered, and just
        before the render -- the long stretch that previously had no feedback.
        """
        from pdfarranger_qt import printing

        seen = []
        printing.print_pages(self.model.pages, self.docs.files_for_export(),
                             self.printer(self.out()), dpi=72,
                             progress=lambda done, total: seen.append((done, total)) or True)
        self.assertEqual(seen[0], (0, 2))
        self.assertEqual(seen[-1], (2, 2))

    def test_progress_callback_can_cancel(self):
        from pdfarranger_qt import printing

        seen = []

        def stop_after_one(done, total):
            seen.append((done, total))
            return done < 1  # let the initial tick through, stop after page 1

        printed = printing.print_pages(
            self.model.pages, self.docs.files_for_export(),
            self.printer(self.out()), dpi=72, progress=stop_after_one)
        self.assertEqual(printed, 1)
        self.assertEqual(seen, [(0, 2), (1, 2)])

    def test_finalise_runs_before_the_painter_ends(self):
        """Regression: the progress dialog auto-closed on reaching its maximum,
        so the app went dark for exactly the slowest part of the job."""
        from pdfarranger_qt import printing

        order = []
        printing.print_pages(
            self.model.pages, self.docs.files_for_export(),
            self.printer(self.out()), dpi=72,
            progress=lambda done, total: order.append(f"page {done}") or True,
            on_finalise=lambda: order.append("finalise"))
        self.assertEqual(order[-1], "finalise",
                         "finalise must come after every page, before end()")

    def test_prepare_sets_the_document_name(self):
        from pdfarranger_qt import printing

        printer = self.printer(self.out())
        printing.prepare(printer, self.model.pages, doc_name="Hopwell.pdf")
        self.assertEqual(printer.docName(), "Hopwell.pdf")
