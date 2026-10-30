# Copyright (C) 2026 pdfarranger-qt contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Step 2.11: Tab walks a form in the order the file declares.

Tab used to do something worse than nothing. The editor is a real QLineEdit,
so Qt's focus traversal took the key first: the value was committed, the
editor closed, and focus landed back on the canvas, out of the form, with the
next field needing a click.
"""

import io
import os
import unittest

import pikepdf
from support import HERE, settle

FORMS = os.path.join(HERE, "exporter", "forms.pdf")


def form_with(order=None, places=((10, 300), (10, 200), (200, 300))):
    """One page of widgets at known places, with a declared order or none.

    ``places`` are the lower-left corners, deliberately not in array order:
    a test that cannot tell row order from array order proves nothing, and
    the corpus shows array order is close to random on four of nine forms.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(400, 400))
    page = pdf.pages[0]
    annots = []
    for index, (x, y) in enumerate(places):
        annots.append(pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            FT=pikepdf.Name.Tx, T=pikepdf.String(f"f{index}"),
            Rect=pikepdf.Array([x, y, x + 100, y + 20]), F=4)))
    page.Annots = pdf.make_indirect(pikepdf.Array(annots))
    pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
        Fields=pikepdf.Array(annots))
    if order is not None:
        page.obj[pikepdf.Name.Tabs] = pikepdf.Name(order)
    return pdf, annots


def tagged_form(sequence=(2, 0, 1)):
    """Widgets whose structure tree names them in ``sequence``."""
    pdf, annots = form_with()
    page = pdf.pages[0]
    kids = [pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name("/OBJR"), Obj=annots[at], Pg=page.obj))
        for at in sequence]
    element = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.StructElem, S=pikepdf.Name("/Sect"),
        Pg=page.obj, K=pikepdf.Array(kids)))
    pdf.Root[pikepdf.Name.StructTreeRoot] = pdf.make_indirect(
        pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot,
                           K=pikepdf.Array([element])))
    page.obj[pikepdf.Name.Tabs] = pikepdf.Name.S
    return pdf


def names(pdf):
    from pdfarranger_qt import forms

    fields = forms.fields_in(pdf)
    return [f.name for f in forms.tab_order(pdf, fields)]


class TestTheOrderTheFileDeclares(unittest.TestCase):
    """Three orders live in a file and they need not agree: the `/Annots`
    array, the `/AcroForm` field tree, and the page's `/Tabs`, which is the
    one that declares traversal. `/Annots` order is what this used to hold,
    and it is close to random on four of nine corpus forms.
    """

    def test_structure_order_is_followed(self):
        """What eight of the nine corpus forms that say anything declare."""
        pdf = tagged_form(sequence=(2, 0, 1))
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f2", "f0", "f1"])

    def test_row_order_where_nothing_is_declared(self):
        """Acrobat falls back to a preference here, so two installations tab
        the same file differently. Row order instead: down the page, then
        across it. The widgets are at (10,300), (10,200), (200,300)."""
        pdf, _annots = form_with(order=None)
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f0", "f2", "f1"])

    def test_row_order_when_it_is_declared(self):
        pdf, _annots = form_with(order="/R")
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f0", "f2", "f1"])

    def test_column_order(self):
        """Across, then down: the two at x=10 before the one at x=200."""
        pdf, _annots = form_with(order="/C")
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f0", "f1", "f2"])

    def test_array_order_is_honoured_when_declared(self):
        """A declaration to follow, never a fallback."""
        pdf, _annots = form_with(order="/A")
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f0", "f1", "f2"])

    def test_an_unreadable_declaration_falls_back_to_rows(self):
        pdf, _annots = form_with(order="/Nonsense")
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f0", "f2", "f1"])

    def test_a_widget_outside_the_tree_is_not_dropped(self):
        """Unreachable by keyboard is worse than out of sequence."""
        pdf = tagged_form(sequence=(2, 0))
        self.addCleanup(pdf.close)
        self.assertEqual(names(pdf), ["f2", "f0", "f1"])

    def test_pages_never_interleave(self):
        from pdfarranger_qt import forms

        pdf, _annots = form_with()
        self.addCleanup(pdf.close)
        pdf.add_blank_page(page_size=(400, 400))
        second = pdf.pages[1]
        second.Annots = pdf.make_indirect(pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
                FT=pikepdf.Name.Tx, T=pikepdf.String("later"),
                Rect=pikepdf.Array([10, 390, 110, 399]), F=4))]))
        fields = forms.fields_in(pdf)
        pages = [f.page for f in forms.tab_order(pdf, fields)]
        self.assertEqual(pages, sorted(pages))
        self.assertEqual(pages[-1], 1)


class TestTabWalksTheForm(unittest.TestCase):
    """The behaviour as the keyboard meets it."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([FORMS])
        settle(timeout_ms=800)
        self.win.set_read_mode(True)
        settle(timeout_ms=1000)
        self.canvas = self.win.reader.canvas
        self.canvas.setFocus()
        settle(timeout_ms=150)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def tab(self, back=False):
        """Through Qt's own dispatch, never by calling `keyPressEvent`.

        Calling it directly tests a path the keyboard never uses: Qt takes
        Tab in `QWidget.event()` for focus traversal before any key handler
        runs, so the first version of these tests passed while Tab in the
        real window moved between the canvas and the page number box and
        never touched the form at all.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        target = QApplication.focusWidget() or self.canvas
        QTest.keyClick(target, Qt.Key_Backtab if back else Qt.Key_Tab)
        settle(timeout_ms=150)

    def order(self):
        return self.canvas.fields().in_tab_order()

    def test_tab_reaches_the_first_field(self):
        self.assertIsNone(self.canvas.focused_field())
        self.tab()
        self.assertIs(self.canvas.focused_field(), self.order()[0])

    def test_tab_advances_and_shift_tab_goes_back(self):
        self.tab()
        self.tab()
        self.assertIs(self.canvas.focused_field(), self.order()[1])
        self.tab(back=True)
        self.assertIs(self.canvas.focused_field(), self.order()[0])

    def test_it_wraps_at_the_end(self):
        self.canvas.focus_field(self.order()[-1])
        self.tab()
        self.assertIs(self.canvas.focused_field(), self.order()[0])

    def test_arriving_at_a_text_field_lets_you_type(self):
        """Not needing a click first, which is what it does anywhere else."""
        text = [f for f in self.order() if f.kind == "/Tx"][0]
        self.canvas.focus_field(text)
        self.assertIsNotNone(self.canvas.editing())

    def test_typing_then_tab_keeps_the_value_and_moves_on(self):
        """The reported fault. Tab used to commit, close the editor and drop
        focus back on the canvas, out of the form."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        text = [f for f in self.order() if f.kind == "/Tx"][0]
        self.canvas.focus_field(text)
        editor = self.canvas._editing[1]
        editor.setText("typed here")
        QTest.keyClick(editor, Qt.Key_Tab)
        settle(timeout_ms=300)
        page = self.win._page_for_field(text)
        self.assertEqual(
            self.win.model.form_values.get(page.nfile, text.name, None),
            "typed here")
        self.assertIsNot(self.canvas.focused_field(), text)

    def test_space_presses_the_box_tab_reached(self):
        """That the key reaches the field is what 2.11 adds; what a press
        then *does* is 2.3's and is tested there. Asserting the value changed
        was wrong: the fixture's buttons are a radio group, and pressing the
        member already chosen correctly leaves it chosen."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        pressed = []
        self.canvas.field_pressed.connect(pressed.append)
        box = [f for f in self.order() if f.kind == "/Btn"][0]
        self.canvas.focus_field(box)
        self.canvas.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key_Space, Qt.NoModifier))
        settle(timeout_ms=200)
        self.assertEqual(pressed, [box])

    def test_a_key_that_is_not_ours_is_left_alone(self):
        """Focus on a field must not swallow the reader's own keys."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        self.tab()
        at = self.canvas.focused_field()
        self.canvas.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key_Down, Qt.NoModifier))
        settle(timeout_ms=150)
        self.assertIs(self.canvas.focused_field(), at)

    def test_escape_leaves_the_form(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        self.tab()
        self.canvas.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertIsNone(self.canvas.focused_field())

    def test_a_document_with_no_fields_lets_tab_alone(self):
        """So that Tab goes on meaning what it usually means."""
        self.canvas.set_field_map(None)
        self.assertFalse(self.canvas.focus_step())


class TestTheReaderSeesTheSameOrderAsTheFile(unittest.TestCase):
    """The reader shows an export of the edited page list (D15), so the order
    it computes comes from that export's structure tree -- which is why 2.11
    needed 2.10 first."""

    def test_the_order_survives_the_export(self):
        from support import temp_path

        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import get_in_memory_pdf

        source = temp_path("tabbed.pdf")
        built = tagged_form(sequence=(2, 0, 1))
        built.save(source)
        built.close()

        docs = DocumentSet()
        self.addCleanup(docs.cleanup)
        pages = docs.add_file(source)
        data = get_in_memory_pdf(list(pages), docs.files_for_export())
        with pikepdf.open(io.BytesIO(data)) as out:
            self.assertEqual(names(out), ["f2", "f0", "f1"])


class TestTheFaultsFoundInUse(unittest.TestCase):
    """Three reported from the real window, each invisible to a test that
    called `keyPressEvent` directly."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([FORMS])
        settle(timeout_ms=800)
        self.win.set_read_mode(True)
        settle(timeout_ms=1000)
        self.canvas = self.win.reader.canvas
        self.canvas.setFocus()
        settle(timeout_ms=150)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def press_tab(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        QTest.keyClick(QApplication.focusWidget() or self.canvas, Qt.Key_Tab)
        settle(timeout_ms=150)

    def click(self, field):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        height = self.canvas._layout.page_height(field.page)
        left, bottom, right, top = field.rect
        where = self.canvas.to_viewport(self.canvas._layout.from_page(
            field.page, QPointF((left + right) / 2,
                                height - (bottom + top) / 2)))
        self.canvas.mousePressEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(where),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(where.x()), int(where.y()))),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=200)

    def test_tab_reaches_the_form_at_all(self):
        """It did not. Qt took the key for focus traversal, so Tab moved
        between the canvas and the page number box."""
        self.press_tab()
        self.assertIsNotNone(self.canvas.focused_field())

    def test_it_does_not_stop_at_a_box_with_no_editor(self):
        """Reported: tabs through text fields, then sticks.

        Arrived at from a *text* field, so the keyboard starts on the
        editor's line edit and has to come back to the canvas -- asserting
        that it did is the whole test. Starting from the box instead proves
        nothing, because the canvas already had the focus.
        """
        from PySide6.QtWidgets import QApplication

        order = self.canvas.fields().in_tab_order()
        text = [f for f in order if f.kind == "/Tx"][0]
        self.canvas.focus_field(text)
        settle(timeout_ms=150)
        self.assertIsNot(QApplication.focusWidget(), self.canvas,
                         "the editor should hold the keyboard")

        self.press_tab()
        box = self.canvas.focused_field()
        self.assertEqual(box.kind, "/Btn")
        self.assertTrue(self.canvas.hasFocus(),
                        "a box has no editor, so nothing else holds the keys")
        self.press_tab()
        self.assertIsNot(self.canvas.focused_field(), box)

    def test_clicking_a_field_is_arriving_at_it(self):
        """Reported: click into a field on a later page, press Tab, and it
        jumped to the first field in the document -- because a click opened
        the editor without ever setting the focus, so the step began from
        nothing."""
        order = self.canvas.fields().in_tab_order()
        start = order[2]
        self.click(start)
        self.assertIs(self.canvas.focused_field(), start)
        self.press_tab()
        self.assertIs(self.canvas.focused_field(), order[3])

    def test_one_tab_is_one_field(self):
        """Closing the editor makes Qt run focus traversal, which comes back
        here: one Tab stepped four fields before that was guarded."""
        order = self.canvas.fields().in_tab_order()
        text = [f for f in order if f.kind == "/Tx"][0]
        self.canvas.focus_field(text)
        at = order.index(text)
        self.press_tab()
        self.assertIs(self.canvas.focused_field(),
                      order[(at + 1) % len(order)])
