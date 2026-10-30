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

        # An *area* tool: highlight marks text now and so selects instead.
        self.win.set_tool(PageCanvas.NOTE)
        # Clear of the widget at (150, 550, 298, 570), so the field does not
        # take the press instead.
        self.drag(self.viewport_point(150, 690), self.viewport_point(298, 670))
        self.assertEqual(len(self.marks), 1)
        tool, page, rects = self.marks[0]
        self.assertEqual((tool, page), (PageCanvas.NOTE, 0))
        # Always a list: an area tool sends the one rectangle it dragged out,
        # a text tool one per run of text it covered.
        self.assertEqual(len(rects), 1)
        for got, want in zip(rects[0], (150.0, 670.0, 298.0, 690.0)):
            self.assertAlmostEqual(got, want, delta=1.5)

    def test_over_a_field_there_is_no_markup(self):
        """The owner's rule: the field takes the press and is edited."""
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
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
        _tool, _page, rects = self.marks[0]
        self.assertEqual(len(rects), 1)
        self.assertAlmostEqual(rects[0][0], rects[0][2], delta=1.0)
        self.assertAlmostEqual(rects[0][1], rects[0][3], delta=1.0)

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


TEXTED = os.path.join(os.path.dirname(TEST_PDF), "text_and_link.pdf")


def three_lines(path):
    """A page of three separate lines of real, selectable text.

    Built rather than taken from a fixture because the point being tested is
    that a highlight is one rectangle per *line*: `text_and_link.pdf` has a
    single run, so against it "one box round the paragraph" and "one per run"
    are the same answer, and the test proved nothing.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(400, 400))
    page = pdf.pages[0]
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
        Encoding=pikepdf.Name.WinAnsiEncoding))
    lines = ("The first line of the paragraph",
             "the second line of the paragraph",
             "and the third line here")
    page.Contents = pdf.make_stream("\n".join(
        "BT /F1 14 Tf 40 %d Td (%s) Tj ET" % (330 - i * 24, text)
        for i, text in enumerate(lines)).encode())
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.save(path)
    pdf.close()
    return path


class TestAHighlightIsASelection(unittest.TestCase):
    """Step 3.3. Highlight comes before the other marks because its geometry
    already exists: a text selection produces the quadrilaterals a
    `/Highlight` wants, so it needs no new hit-testing.

    One rectangle per *run*, not one round the paragraph. A box spanning
    three lines covers the margins and the gaps between them, and a highlight
    that does that is worse than none.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([TEXTED])
        settle(timeout_ms=1000)
        self.win.set_read_mode(True)
        settle(timeout_ms=1200)
        self.canvas = self.win.reader.canvas

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def drag_over_text(self, tool):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        self.win.set_tool(tool)

        def at(x, y_down):
            return self.canvas.to_viewport(
                self.canvas._layout.from_page(0, QPointF(x, y_down)))

        def send(kind, point):
            event = QMouseEvent(
                kind, QPointF(point),
                self.canvas.viewport().mapToGlobal(
                    QPoint(int(point.x()), int(point.y()))),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
             QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
             QMouseEvent.Type.MouseButtonRelease:
                 self.canvas.mouseReleaseEvent}[kind](event)

        send(QMouseEvent.Type.MouseButtonPress, at(70, 85))
        send(QMouseEvent.Type.MouseMove, at(260, 92))
        send(QMouseEvent.Type.MouseButtonRelease, at(260, 92))
        settle(timeout_ms=400)

    def held(self):
        return self.win.model.annotations.for_page(self.win.model.pages[0].uid)

    def test_a_highlight_tool_selects_rather_than_drags_a_box(self):
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        self.assertTrue(self.canvas.marks_text())
        self.assertFalse(self.canvas.marks_area())

    def test_the_selection_becomes_a_mark(self):
        from pdfarranger_qt import markup
        from pdfarranger_qt.canvas import PageCanvas

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        marks = self.held()
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0].kind, markup.HIGHLIGHT)
        self.assertTrue(marks[0].quads)

    def test_strikethrough_is_the_same_gesture(self):
        from pdfarranger_qt import markup
        from pdfarranger_qt.canvas import PageCanvas

        self.drag_over_text(PageCanvas.STRIKEOUT)
        self.assertEqual(self.held()[0].kind, markup.STRIKEOUT)

    def test_the_rectangle_contains_every_quad(self):
        """`/Rect` has to: a viewer that does not understand the subtype
        falls back to it."""
        from pdfarranger_qt.canvas import PageCanvas

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        mark = self.held()[0]
        for quad in mark.quads:
            self.assertGreaterEqual(quad[0], mark.rect[0] - 0.01)
            self.assertGreaterEqual(quad[1], mark.rect[1] - 0.01)
            self.assertLessEqual(quad[2], mark.rect[2] + 0.01)
            self.assertLessEqual(quad[3], mark.rect[3] + 0.01)

    def test_the_selection_is_let_go_afterwards(self):
        """The words are marked now; leaving them selected as well says the
        gesture has not finished."""
        from pdfarranger_qt.canvas import PageCanvas

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        self.assertFalse(self.canvas.has_selection())

    def test_marking_does_not_rebuild_the_reader(self):
        """The canvas draws the mark from what the window holds, so the
        document on screen does not have to be made again -- the same 682 ms
        the form work went to such lengths to avoid."""
        from pdfarranger_qt.canvas import PageCanvas

        rebuilds = []
        real = self.win._load_reader
        self.win._load_reader = lambda *a, **k: (rebuilds.append(1),
                                                 real(*a, **k))[1]
        self.drag_over_text(PageCanvas.HIGHLIGHT)
        self.assertEqual(rebuilds, [])

    def test_it_is_drawn_before_anything_is_exported(self):
        from PySide6.QtGui import QImage

        from pdfarranger_qt.canvas import PageCanvas

        def yellow():
            shot = QImage(self.canvas.viewport().size(), QImage.Format_RGB32)
            shot.fill(0xFFFFFFFF)
            self.canvas.viewport().render(shot)
            return sum(1 for y in range(0, shot.height(), 2)
                       for x in range(0, shot.width(), 2)
                       if shot.pixelColor(x, y).red() > 200
                       and shot.pixelColor(x, y).blue() < 120)

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=250)
        self.assertGreater(yellow(), 100)

    def test_undo_takes_the_mark_back(self):
        from pdfarranger_qt.canvas import PageCanvas

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        self.assertEqual(len(self.held()), 1)
        self.win.model.undo.undo()
        settle(timeout_ms=250)
        self.assertEqual(len(self.held()), 0)

    def test_it_reaches_the_saved_file(self):
        import io

        from pdfarranger_qt.canvas import PageCanvas
        from pdfarranger_qt.export import export

        self.drag_over_text(PageCanvas.HIGHLIGHT)
        out = io.BytesIO()
        export(self.win.docs.files_for_export(), list(self.win.model.pages),
               {}, [out], annotations=self.win.model.annotations)
        with pikepdf.open(io.BytesIO(out.getvalue())) as written:
            marks = [a for a in written.pages[0].get(pikepdf.Name.Annots, [])
                     if str(a.get(pikepdf.Name.Subtype)) == "/Highlight"]
            self.assertEqual(len(marks), 1)
            self.assertIn("/QuadPoints", marks[0])
            self.assertIn("/AP", marks[0])
            self.assertAlmostEqual(float(marks[0].CA), 0.4, places=3)


class TestAHighlightFollowsTheLines(unittest.TestCase):
    """One rectangle per run, not one round the paragraph.

    A box spanning three lines covers the margins and the gaps between them.
    `text_and_link.pdf` could not show this: it holds a single run, so both
    answers look alike against it.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([three_lines(temp_path("threelines.pdf"))])
        settle(timeout_ms=1000)
        self.win.set_read_mode(True)
        settle(timeout_ms=1200)
        self.canvas = self.win.reader.canvas

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def select_two_lines(self):
        from PySide6.QtCore import QPointF

        self.canvas._anchor = (0, QPointF(45, 60))
        self.canvas._extend_selection(0, QPointF(300, 130))
        settle(timeout_ms=200)

    def test_two_lines_give_two_quads(self):
        self.select_two_lines()
        page, quads = self.canvas.selection_quads()
        self.assertEqual(page, 0)
        self.assertEqual(len(quads), 2)

    def test_the_gap_between_the_lines_is_not_covered(self):
        """Which is the whole difference between this and one box: the second
        line's top is below the first line's bottom, and nothing reaches
        across."""
        self.select_two_lines()
        _page, quads = self.canvas.selection_quads()
        ordered = sorted(quads, key=lambda q: -q[3])
        upper, lower = ordered[0], ordered[1]
        self.assertGreater(upper[1], lower[3],
                           "the quads overlap, so one spans the gap")

    def test_the_mark_keeps_every_quad(self):
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        self.select_two_lines()
        page, quads = self.canvas.selection_quads()
        self.canvas.mark_drawn.emit(PageCanvas.HIGHLIGHT, page, quads)
        settle(timeout_ms=200)
        marks = self.win.model.annotations.for_page(self.win.model.pages[0].uid)
        self.assertEqual(len(marks), 1)
        self.assertEqual(len(marks[0].quads), 2)
