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

"""Picking up a mark the document already had.

The marks here come out of the file rather than out of this session, which
is the half that had never been exercised: everything before this tested
marks the user had just made, and those are the easy ones -- they are in the
model, in the source page's space, and nothing had to find them.

What is tested is finding one under a pointer, what that does under each
kind of tool, and that the outline shown for a mark you are merely over is
the one shown for a mark you have picked.
"""

import os
import unittest

from support import FIXTURES, settle

PDF = os.path.join(FIXTURES, "markup.pdf")


class SelectionCase(unittest.TestCase):
    """A window reading the markup sample, which carries 180 annotations."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([PDF])
        settle(timeout_ms=1200)
        self.win.set_read_mode(True)
        settle(timeout_ms=1600)
        self.canvas = self.win.reader.canvas
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=300)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def a_mark(self):
        """A mark on the first page, with somewhere to click on it."""
        for mark, _mine in self.canvas.marks_on(0):
            for box in self.canvas.mark_boxes(mark):
                where = self.canvas.quad_on_screen(0, box, scaled=False)
                if where is None or where.width() < 4 or where.height() < 4:
                    continue
                if self.canvas.viewport().rect().contains(
                        where.center().toPoint()):
                    return mark, where
        self.fail("no mark on the first page is on screen to click")

    def send(self, kind, point, buttons=None):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        if buttons is None:
            buttons = (Qt.LeftButton if kind != QMouseEvent.Type.MouseMove
                       else Qt.NoButton)
        event = QMouseEvent(
            kind, QPointF(point),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(point.x()), int(point.y()))),
            Qt.LeftButton, buttons, Qt.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease:
             self.canvas.mouseReleaseEvent}[kind](event)

    def click(self, point):
        from PySide6.QtGui import QMouseEvent

        self.send(QMouseEvent.Type.MouseButtonPress, point)
        self.send(QMouseEvent.Type.MouseButtonRelease, point)


class TestTheFilesOwnMarksAreFound(SelectionCase):

    def test_the_document_on_screen_is_what_is_read(self):
        """Not the sources behind it. The snapshot's annotations are already
        in the coordinates being drawn in and on the pages being shown."""
        self.assertGreater(len(self.canvas._file_marks), 0,
                           "the reader found no marks in a document that "
                           "carries 180 of them")

    def test_only_the_kinds_a_click_can_be_aimed_at(self):
        """A note is reached by its icon and a popup is never drawn, so
        neither is something a click on the page lands on."""
        for mark, mine in self.canvas.marks_on(0):
            # Not `getattr(mark, "subtype", mark.kind)`: Python works out the
            # default before the lookup runs, so the fallback raises on every
            # mark that *has* a subtype.
            kind = mark.kind if mine else mark.subtype
            with self.subTest(kind=kind):
                self.assertIn(kind, self.canvas.SELECTABLE)

    def test_a_point_on_a_mark_finds_it(self):
        mark, where = self.a_mark()
        found = self.canvas.mark_at(where.center())
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 0)
        self.assertIs(found[1], mark)

    def test_a_point_off_every_mark_finds_nothing(self):
        from PySide6.QtCore import QPointF

        _mark, where = self.a_mark()
        for step in (200, 300, 400):
            point = QPointF(where.center().x(), where.center().y() + step)
            if not self.canvas.viewport().rect().contains(point.toPoint()):
                continue
            if self.canvas.mark_at(point) is None:
                return
        self.skipTest("every point tried still landed on a mark")


class TestWhatAClickDoes(SelectionCase):

    def test_the_pointer_picks_a_mark_up(self):
        _mark, where = self.a_mark()
        self.click(where.center())
        self.assertIsNotNone(self.canvas.selected_mark())

    def test_a_text_tool_picks_a_mark_up_rather_than_starting_another(self):
        """Pressing on a highlight with the highlighter armed means *that
        highlight*, not the beginning of a second one over the top of it."""
        from pdfarranger_qt.canvas import PageCanvas

        _mark, where = self.a_mark()
        self.canvas.set_tool(PageCanvas.HIGHLIGHT)
        self.click(where.center())
        self.assertIsNotNone(self.canvas.selected_mark())
        self.assertFalse(self.canvas._preview,
                         "the press started a mark as well as picking one up")

    def test_an_area_tool_keeps_the_press(self):
        """A rectangle or an arrow is drawn across whatever is underneath, so
        the mark below it is not what the press was aimed at."""
        from pdfarranger_qt.canvas import PageCanvas

        _mark, where = self.a_mark()
        self.canvas.set_tool(PageCanvas.DRAW)
        self.click(where.center())
        self.assertIsNone(self.canvas.selected_mark())

    def test_clicking_the_page_lets_go(self):
        from PySide6.QtCore import QPointF

        _mark, where = self.a_mark()
        self.click(where.center())
        self.assertIsNotNone(self.canvas.selected_mark())
        self.click(QPointF(where.center().x(), where.center().y() + 300))
        self.assertIsNone(self.canvas.selected_mark())

    def test_escape_lets_go(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        _mark, where = self.a_mark()
        self.click(where.center())
        self.canvas.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertIsNone(self.canvas.selected_mark())

    def test_it_says_so(self):
        from PySide6.QtCore import QPointF

        seen = []
        self.canvas.mark_selected.connect(seen.append)
        _mark, where = self.a_mark()
        self.click(where.center())
        self.click(QPointF(where.center().x(), where.center().y() + 300))
        self.assertEqual(seen, [True, False])


class TestTheOutlineUnderThePointer(SelectionCase):

    def test_the_pointer_notices_a_mark_under_every_tool(self):
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        _mark, where = self.a_mark()
        for tool in (PageCanvas.SELECT, PageCanvas.HIGHLIGHT,
                     PageCanvas.DRAW):
            with self.subTest(tool=tool):
                self.canvas.set_tool(tool)
                self.send(QMouseEvent.Type.MouseMove, where.center())
                self.assertIsNotNone(self.canvas.hovered_mark())

    def test_a_drag_does_not_light_up_what_it_crosses(self):
        """While a mark is being made, outlining the ones the pointer passes
        over is noise: the gesture is about the text, not about them."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        _mark, where = self.a_mark()
        self.send(QMouseEvent.Type.MouseMove, where.center())
        self.assertIsNotNone(self.canvas.hovered_mark())
        self.send(QMouseEvent.Type.MouseMove, where.center(),
                  buttons=Qt.LeftButton)
        self.assertIsNone(self.canvas.hovered_mark())

    def test_hovering_and_selecting_look_identical(self):
        """Acrobat's answer, and decision 13. The outline says how far a mark
        reaches, which does not change according to whether you have
        committed to it -- what tells the two apart is the bar of buttons.

        Rendered rather than reasoned about: a faded hover was what this
        replaced, and only the pixels can say the fade is gone.
        """
        from PySide6.QtGui import QImage, QMouseEvent

        mark, where = self.a_mark()
        viewport = self.canvas.viewport()

        def painted():
            image = QImage(viewport.size(), QImage.Format_ARGB32)
            image.fill(0)
            viewport.render(image)
            return image

        self.canvas.select_mark(None)
        self.send(QMouseEvent.Type.MouseMove, where.center())
        self.assertIsNotNone(self.canvas.hovered_mark())
        hovered = painted()

        self.canvas._hovered = None
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        # The bar is a child of the viewport and is what the two states are
        # *supposed* to differ by, so it is taken out of the comparison --
        # leaving it in would make this pass for the wrong reason and then
        # fail for the right one.
        self.win.mark_buttons.hide()
        selected = painted()
        self.assertEqual(hovered, selected,
                         "the two states are drawn differently")


class TestTheButtonsBesideIt(SelectionCase):

    def test_they_arrive_with_the_selection_and_leave_with_it(self):
        _mark, where = self.a_mark()
        self.assertFalse(self.win.mark_buttons.isVisible())
        self.click(where.center())
        settle(timeout_ms=150)
        self.assertTrue(self.win.mark_buttons.isVisible())
        self.canvas.select_mark(None)
        settle(timeout_ms=150)
        self.assertFalse(self.win.mark_buttons.isVisible())

    def test_all_three_are_there_and_none_of_them_acts(self):
        """Each is turned on by the step that builds it. One that acted now
        would be a second, half-built way into work that step has to do."""
        buttons = self.win.mark_buttons.buttons
        self.assertEqual(list(buttons), ["comment", "colour", "delete"])
        for name, button in buttons.items():
            with self.subTest(button=name):
                self.assertFalse(button.isEnabled())

    def test_it_sits_clear_of_the_mark(self):
        _mark, where = self.a_mark()
        self.click(where.center())
        settle(timeout_ms=150)
        bar = self.win.mark_buttons
        rects = self.canvas.selection_on_screen()
        self.assertTrue(rects)
        top = min(r.top() for r in rects)
        bottom = max(r.bottom() for r in rects)
        self.assertTrue(bar.y() + bar.height() <= top or bar.y() >= bottom,
                        "the bar is drawn over the mark it belongs to")

    def test_it_stays_inside_the_viewport(self):
        _mark, where = self.a_mark()
        self.click(where.center())
        settle(timeout_ms=150)
        bar = self.win.mark_buttons
        self.assertGreaterEqual(bar.x(), 0)
        self.assertGreaterEqual(bar.y(), 0)
        self.assertLessEqual(bar.x() + bar.width(),
                             self.canvas.viewport().width())

    def test_it_follows_the_page_when_it_scrolls(self):
        _mark, where = self.a_mark()
        self.click(where.center())
        settle(timeout_ms=150)
        before = self.win.mark_buttons.y()
        bar = self.canvas.verticalScrollBar()
        bar.setValue(bar.value() + 40)
        settle(timeout_ms=200)
        self.assertNotEqual(self.win.mark_buttons.y(), before,
                            "the bar stayed put while the page moved")


class TestADocumentChangeLetsGo(SelectionCase):

    def test_closing_the_document_drops_what_was_selected(self):
        """Nothing read from the snapshot outlives it, which is the whole
        reason the snapshot can be hit-tested in the first place."""
        _mark, where = self.a_mark()
        self.click(where.center())
        self.assertIsNotNone(self.canvas.selected_mark())
        self.canvas.set_document(None)
        self.assertIsNone(self.canvas.selected_mark())
        self.assertEqual(len(self.canvas._file_marks), 0)


if __name__ == "__main__":
    unittest.main()
