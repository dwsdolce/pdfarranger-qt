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

"""Step 3.1: a mark the user adds is owned, undoable and saved.

The model only. What puts a mark on the page is 3.2 onwards; what matters
first is that it belongs to a *page* rather than to a position, survives the
undo stack, and reaches the file -- which is the same ground body 2 covered
for form values, and the same answer.
"""

import os
import unittest

import pikepdf
from support import TEST_PDF, settle, temp_path

from pdfarranger_qt import markup
from pdfarranger_qt.markup import TEXT, Annotation, Annotations


def note(uid, text="a note", rect=(72, 700, 92, 720), **kw):
    return Annotation(TEXT, uid, rect, text, **kw)


class TestTheModel(unittest.TestCase):
    def test_a_mark_belongs_to_a_page(self):
        marks = Annotations()
        marks.add(note(7))
        self.assertEqual(len(marks.for_page(7)), 1)
        self.assertEqual(marks.for_page(8), [])

    def test_an_empty_one_is_falsey(self):
        """A document nobody has marked must cost nothing to snapshot."""
        self.assertFalse(Annotations())
        self.assertEqual(len(Annotations()), 0)

    def test_removing_the_last_mark_removes_the_page(self):
        marks = Annotations()
        only = marks.add(note(3))
        self.assertTrue(marks.remove(only))
        self.assertFalse(marks)
        self.assertFalse(marks.remove(only), "removing it twice is not an error")

    def test_a_duplicate_is_independent(self):
        """Undo snapshots it, so sharing a list would make undo a no-op."""
        marks = Annotations()
        marks.add(note(1, "first"))
        copy = marks.duplicate()
        marks.add(note(1, "second"))
        self.assertEqual(len(copy), 1)
        self.assertEqual(len(marks), 2)
        copy.for_page(1)[0].contents = "changed"
        self.assertEqual(marks.for_page(1)[0].contents, "first",
                         "the marks themselves must be copied too")

    def test_an_unknown_kind_is_refused(self):
        """Better a failure here than a dictionary a viewer silently drops."""
        with self.assertRaises(ValueError):
            Annotation("/Spaceship", 1, (0, 0, 1, 1))

    def test_the_date_is_in_the_form_pdf_wants(self):
        self.assertRegex(markup.pdf_date(),
                         r"^D:\d{14}[+-]\d{2}'\d{2}'$")


class TestTheDictionaryItWrites(unittest.TestCase):
    def built(self, annotation=None):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(300, 300))
        return pdf, markup.to_dictionary(pdf, annotation or note(1))

    def test_it_is_an_annotation_of_the_right_subtype(self):
        _pdf, entry = self.built()
        self.assertEqual(str(entry.get("/Type")), "/Annot")
        self.assertEqual(str(entry.get("/Subtype")), "/Text")

    def test_it_prints(self):
        """Without bit 3 of /F a mark shows on screen and vanishes on paper,
        which is not what anybody means by annotating a document."""
        _pdf, entry = self.built()
        self.assertTrue(int(entry.get("/F")) & markup.PRINTABLE)

    def test_it_is_indirect(self):
        """/Annots is an array of references; an inline dictionary there can
        never be pointed at by anything else."""
        _pdf, entry = self.built()
        self.assertTrue(entry.is_indirect)

    def test_the_optional_parts_are_only_there_when_given(self):
        _pdf, bare = self.built(note(1))
        self.assertNotIn("/T", bare)
        self.assertNotIn("/C", bare)
        _pdf, dressed = self.built(note(1, author="David", colour=(1, 1, 0)))
        self.assertEqual(str(dressed.get("/T")), "David")
        self.assertEqual([float(v) for v in dressed.get("/C")], [1.0, 1.0, 0.0])


class TestItReachesTheSavedFile(unittest.TestCase):
    """Export writes the marks of the pages it is writing, and no others."""

    def window(self):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        win.resize(600, 400)
        win.show()
        win.open_paths([TEST_PDF])
        settle(timeout_ms=600)
        win.modified = False
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def saved(self, win, pages=None, name="marked.pdf"):
        out = temp_path(name)
        self.assertTrue(win._write([out], pages or win.model.pages))
        return pikepdf.open(out)

    def texts_on(self, pdf, index):
        return [str(a.get("/Contents"))
                for a in pdf.pages[index].get("/Annots", [])
                if str(a.get("/Subtype")) == "/Text"]

    def test_a_mark_lands_on_its_own_page(self):
        win = self.window()
        win.model.annotations.add(note(win.model.pages[1].uid, "on page two"))
        with self.saved(win) as pdf:
            self.assertEqual(self.texts_on(pdf, 0), [])
            self.assertEqual(self.texts_on(pdf, 1), ["on page two"])

    def test_it_follows_its_page_when_the_order_changes(self):
        """The whole reason for keying by uid rather than by index."""
        win = self.window()
        first, second = win.model.pages[0], win.model.pages[1]
        win.model.annotations.add(note(second.uid, "on page two"))
        win.model.pages[0], win.model.pages[1] = second, first
        with self.saved(win, name="reordered.pdf") as pdf:
            self.assertEqual(self.texts_on(pdf, 0), ["on page two"],
                             "the mark moved with its page, not with the slot")
            self.assertEqual(self.texts_on(pdf, 1), [])

    def test_a_copied_page_does_not_inherit_the_marks(self):
        """Page.duplicate(new_identity=True) is what the Duplicate command
        uses, and a fresh uid is exactly what stops the notes being copied."""
        win = self.window()
        original = win.model.pages[0]
        win.model.annotations.add(note(original.uid, "only on the original"))
        copy = original.duplicate(new_identity=True)
        self.assertEqual(win.model.annotations.for_page(copy.uid), [])

    def test_an_export_of_a_selection_leaves_the_rest_behind(self):
        """Which falls out of looking marks up by the pages being written."""
        win = self.window()
        win.model.annotations.add(note(win.model.pages[0].uid, "page one"))
        win.model.annotations.add(note(win.model.pages[1].uid, "page two"))
        with self.saved(win, [win.model.pages[1]], "selection.pdf") as pdf:
            self.assertEqual(len(pdf.pages), 1)
            self.assertEqual(self.texts_on(pdf, 0), ["page two"])

    def test_an_unmarked_document_gains_nothing(self):
        win = self.window()
        with self.saved(win, name="plain.pdf") as pdf:
            self.assertEqual(self.texts_on(pdf, 0), [])
            self.assertEqual(self.texts_on(pdf, 1), [])


class TestItSurvivesUndo(unittest.TestCase):
    """3.1's done-when, on the same stack as everything else (D2)."""

    def window(self):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        win.resize(600, 400)
        win.show()
        win.open_paths([TEST_PDF])
        settle(timeout_ms=600)
        win.modified = False
        self.addCleanup(win.close)
        self.addCleanup(lambda: setattr(win, "modified", False))
        return win

    def test_undo_takes_a_note_away_and_redo_brings_it_back(self):
        win = self.window()
        uid = win.model.pages[0].uid
        win.model.undo.commit("Add Note")
        win.model.annotations.add(note(uid, "remember this"))
        self.assertEqual(len(win.model.annotations), 1)
        win.undo()
        self.assertEqual(len(win.model.annotations), 0)
        win.redo()
        self.assertEqual(len(win.model.annotations), 1)
        self.assertEqual(win.model.annotations.for_page(uid)[0].contents,
                         "remember this")

    def test_the_note_and_the_pages_come_off_one_stack(self):
        """One history, not two that can disagree -- the reason the marks are
        in the same snapshot as the pages rather than beside them.

        Walked back two steps, because only the second one distinguishes a
        shared stack from a note that merely happens to still be there: undo
        the delete and the page returns with the uid its note is keyed by;
        undo again and the note itself goes.
        """
        win = self.window()
        uid = win.model.pages[0].uid
        win.model.undo.commit("Add Note")
        win.model.annotations.add(note(uid, "with its page"))
        win.model.undo.commit("Delete")
        del win.model.pages[0]

        win.undo()
        self.assertEqual(len(win.model.pages), 2, "the page is back")
        self.assertEqual(win.model.pages[0].uid, uid,
                         "with the identity the note is keyed by")
        self.assertEqual(len(win.model.annotations), 1, "and still its note")

        win.undo()
        self.assertEqual(len(win.model.pages), 2, "the pages are untouched")
        self.assertEqual(len(win.model.annotations), 0,
                         "and the note is gone, off the same stack")


if __name__ == "__main__":
    unittest.main()


FORMS = os.path.join(os.path.dirname(TEST_PDF), "exporter", "forms.pdf")
MANY_PAGES = os.path.join(os.path.dirname(TEST_PDF), "exporter", "outlines.pdf")


class TestFromThePointerToThePage(unittest.TestCase):
    """The seam a mark is placed through (3.2).

    A drag happens in viewport pixels; a mark is kept in the page's own space
    (D6). Three frames are crossed between them, and the one that used to be
    missing is the turn: a widget's rectangle and the canvas's frame agree
    only at `/Rotate` zero.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def reading(self, angle=0):
        self.win.open_paths([FORMS])
        settle(timeout_ms=800)
        if angle:
            self.win.model.rotate([0], angle)
            settle(timeout_ms=400)
        self.win.set_read_mode(True)
        settle(timeout_ms=1000)
        return self.win.reader.canvas

    def drag_over(self, canvas, field):
        """The two viewport corners of a field, by the forward path."""
        from PySide6.QtCore import QPointF

        height = canvas._layout.page_height(field.page)
        left, bottom, right, top = field.rect
        return (canvas.to_viewport(
                    canvas._layout.from_page(field.page,
                                             QPointF(left, height - top))),
                canvas.to_viewport(
                    canvas._layout.from_page(field.page,
                                             QPointF(right, height - bottom))))

    def test_a_drag_comes_back_in_the_coordinates_the_file_uses(self):
        """Dragged over a widget, so there is a rectangle in the file to check
        against rather than one this computed for itself."""
        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle):
                canvas = self.reading(angle)
                field = canvas.fields().on_page(0)[0]
                page, rect = canvas.mark_rect(*self.drag_over(canvas, field))
                self.assertEqual(page, 0)
                for got, want in zip(rect, (150.0, 550.0, 298.0, 570.0)):
                    self.assertAlmostEqual(got, want, delta=1.5)
                self.win.set_read_mode(False)
                settle(timeout_ms=200)

    def test_every_page_has_a_box(self):
        canvas = self.reading()
        self.assertEqual(len(canvas._boxes), canvas._layout.page_count)
        self.assertIsNotNone(canvas.page_box(0))

    def test_the_boxes_outlive_the_field_map(self):
        """D7: a box is five numbers and nothing invalidates it. Closing the
        map must not take the geometry with it."""
        canvas = self.reading()
        before = canvas.page_box(0)
        canvas.fields().close()
        self.assertEqual(canvas.page_box(0), before)

    def test_a_drag_that_starts_off_a_page_places_nothing(self):
        from PySide6.QtCore import QPointF

        canvas = self.reading()
        self.assertIsNone(canvas.mark_rect(QPointF(-50, -50), QPointF(10, 10)))

    def test_a_page_past_the_end_has_no_box(self):
        canvas = self.reading()
        self.assertIsNone(canvas.page_box(canvas._layout.page_count + 5))

    def test_the_drag_belongs_to_the_page_it_began_on(self):
        """A selection dragged onto the *next* page stays on the one it
        started from. Needs more than one page to say anything: ending in the
        margin proves nothing, because there is no page under the end either
        way, which is how the first version of this test passed against the
        bug it was written for."""
        from PySide6.QtCore import QPointF

        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=800)
        self.win.set_read_mode(True)
        settle(timeout_ms=1000)
        canvas = self.win.reader.canvas
        self.assertGreater(canvas._layout.page_count, 1)

        start = canvas.to_viewport(
            canvas._layout.from_page(0, QPointF(50, 50)))
        end = canvas.to_viewport(
            canvas._layout.from_page(1, QPointF(60, 60)))
        self.assertEqual(canvas.page_at(end), 1, "the drag must end elsewhere")
        page, _rect = canvas.mark_rect(start, end)
        self.assertEqual(page, 0)


class TestTheToolDecidesWhatThePointerDoes(unittest.TestCase):
    """Step 3.2b. The canvas reports a gesture and keeps none of it; what a
    mark *is* belongs to 3.3 onwards.

    The precedence is the owner's: over a field there is no markup, the field
    takes the press and is edited. A widget that cannot be filled falls
    through to the tool, because a field you may not fill is no reason to
    refuse a mark on the page around it.
    """

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
        self.marks = []
        self.canvas.mark_drawn.connect(
            lambda tool, page, rect: self.marks.append((tool, page, rect)))

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def send(self, kind, point):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            kind, QPointF(point),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(point.x()), int(point.y()))),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        if kind == QMouseEvent.Type.MouseButtonPress:
            self.canvas.mousePressEvent(event)
        elif kind == QMouseEvent.Type.MouseMove:
            self.canvas.mouseMoveEvent(event)
        else:
            self.canvas.mouseReleaseEvent(event)

    def drag(self, start, end):
        from PySide6.QtGui import QMouseEvent

        self.send(QMouseEvent.Type.MouseButtonPress, start)
        self.send(QMouseEvent.Type.MouseMove, end)
        self.send(QMouseEvent.Type.MouseButtonRelease, end)

    def viewport_point(self, x, y_up):
        from PySide6.QtCore import QPointF

        height = self.canvas._layout.page_height(0)
        return self.canvas.to_viewport(
            self.canvas._layout.from_page(0, QPointF(x, height - y_up)))

    def the_field(self):
        return self.canvas.fields().on_page(0)[0]

    def test_the_pointer_reads_until_a_tool_is_chosen(self):
        from pdfarranger_qt.canvas import PageCanvas

        self.assertEqual(self.canvas.tool(), PageCanvas.SELECT)
        self.assertFalse(self.canvas.marking())

    def test_a_drag_under_a_tool_reports_where_it_was(self):
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        # Clear of the widget at (150, 550, 298, 570), so the field does not
        # take the press instead.
        self.drag(self.viewport_point(150, 690), self.viewport_point(298, 670))
        self.assertEqual(len(self.marks), 1)
        tool, page, rect = self.marks[0]
        self.assertEqual((tool, page), (PageCanvas.HIGHLIGHT, 0))
        for got, want in zip(rect, (150.0, 670.0, 298.0, 690.0)):
            self.assertAlmostEqual(got, want, delta=1.5)

    def test_over_a_field_there_is_no_markup(self):
        """The owner's rule: the field takes the press and is edited."""
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        field = self.the_field()
        left, bottom, right, top = field.rect
        middle = self.viewport_point((left + right) / 2, (bottom + top) / 2)
        self.drag(middle, middle)
        self.assertEqual(self.marks, [])
        self.assertIsNotNone(self.canvas.editing())

    def test_a_click_is_a_rectangle_with_no_width(self):
        """Which is what placing a sticky note is."""
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        where = self.viewport_point(200, 690)
        self.drag(where, where)
        self.assertEqual(len(self.marks), 1)
        _tool, _page, rect = self.marks[0]
        self.assertAlmostEqual(rect[0], rect[2], delta=1.0)
        self.assertAlmostEqual(rect[1], rect[3], delta=1.0)

    def test_escape_puts_the_pointer_back_to_reading(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.DRAW)
        self.canvas.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertEqual(self.canvas.tool(), PageCanvas.SELECT)

    def test_the_menu_follows_the_canvas(self):
        """Escape changes the tool without going through the menu, so the
        menu cannot be the only place the choice lives."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        checked = [a for a in self.win.markup_tools.actions() if a.isChecked()]
        self.assertEqual([a.data() for a in checked], [PageCanvas.HIGHLIGHT])
        self.canvas.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        checked = [a for a in self.win.markup_tools.actions() if a.isChecked()]
        self.assertEqual([a.data() for a in checked], [PageCanvas.SELECT])

    def test_reading_is_untouched_while_no_tool_is_chosen(self):
        """The whole of body 1 and 2 happens in this mode, so a drag here must
        still select text rather than report a mark."""
        self.drag(self.viewport_point(150, 690), self.viewport_point(298, 670))
        self.assertEqual(self.marks, [])
