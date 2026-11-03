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

#: A highlight Acrobat wrote, carrying a note with a reply and a status
#: chain, beside two that carry nothing. Produced by marking up a document
#: in Reader rather than assembled here: a fixture built from this
#: application's own understanding of `/IRT` and `/State` could only confirm
#: that its reader agrees with its writer.
NOTED = os.path.join(FIXTURES, "markup_highlight.pdf")


class SelectionCase(unittest.TestCase):
    """A window reading the markup sample, which carries 180 annotations."""

    #: Which document to read. A case that needs a particular shape of mark
    #: builds its own rather than hoping the sample has one.
    def document(self):
        return PDF

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([self.document()])
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
        """Acrobat's answer. The outline says how far a mark reaches, which
        does not change according to whether you have committed to it --
        what tells the two apart is the bar of buttons and the grips.

        Rendered rather than reasoned about: a faded hover was what this
        replaced, and only the pixels can say the fade is gone.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QMouseEvent, QPainter

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

        # The grips are the other thing the two states are supposed to
        # differ by, and unlike the bar they are painted by the canvas
        # rather than being a child widget, so they cannot be hidden. They
        # are blanked out of both images instead. Everything outside them
        # must still match: that is where a fade would show.
        for image in (hovered, selected):
            painter = QPainter(image)
            for grip in self.canvas.grips():
                painter.fillRect(grip.adjusted(-2, -2, 2, 2), Qt.black)
            painter.end()
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

    def test_all_three_are_there(self):
        buttons = self.win.mark_buttons.buttons
        self.assertEqual(list(buttons), ["comment", "colour", "delete"])

    def test_only_the_ones_with_a_step_behind_them_act(self):
        """Each is turned on by the step that builds it. One that acted
        before then would be a second, half-built way into work that step
        has to do properly.

        Colour was turned on by the step that built the palette, and the
        trash by the one that takes a mark with its status chain and its
        replies. Comment still waits for the note work, so it is drawn and
        refused.
        """
        buttons = self.win.mark_buttons.buttons
        for name in ("colour", "delete"):
            with self.subTest(button=name, acts=True):
                self.assertTrue(buttons[name].isEnabled())
        self.assertFalse(buttons["comment"].isEnabled())

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


class TestAMarkThatCarriesANote(SelectionCase):
    """Selecting a mark means being able to see what it is.

    A highlight somebody has written about must not look like one nobody
    has. Reader draws a badge at its top left whether or not it is picked,
    and shows the note at the pointer. This step was marked done without
    either, which made a note invisible until you happened to hover.
    """

    def document(self):
        return NOTED

    def a_noted_mark(self):
        for mark, mine in self.canvas.marks_on(0):
            if not mine and mark.has_note():
                return mark
        self.fail("the fixture is supposed to carry a noted mark")

    def test_the_model_knows_a_note_is_there(self):
        mark = self.a_noted_mark()
        self.assertTrue(mark.contents)
        self.assertFalse(mark.parent, "a reply is not a note of its own")

    def test_a_reply_is_not_mistaken_for_a_note(self):
        """A reply and a status change carry contents too -- 'Completed set
        by dws' -- so a mark is only noted when nothing is above it."""
        found = self.canvas._file_marks.for_page(1)
        children = [m for m in found if m.parent]
        self.assertTrue(children, "the fixture has no chain to test")
        for child in children:
            with self.subTest(contents=child.contents[:20]):
                self.assertFalse(child.has_note())

    def test_the_badge_sits_off_the_marks_corner(self):
        mark = self.a_noted_mark()
        badge = self.canvas._badge_rect(0, mark)
        self.assertIsNotNone(badge)
        top = max(self.canvas.mark_boxes(mark), key=lambda q: q[3])
        where = self.canvas.quad_on_screen(0, top, scaled=False)
        self.assertLess(badge.left(), where.left())
        self.assertLess(badge.top(), where.top())

    def test_the_badge_can_be_pointed_at(self):
        mark = self.a_noted_mark()
        badge = self.canvas._badge_rect(0, mark)
        found = self.canvas.note_badge_at(badge.center())
        self.assertIsNotNone(found)
        self.assertIs(found[1], mark)

    def test_a_mark_with_no_note_has_no_badge(self):
        for mark, mine in self.canvas.marks_on(0):
            if mine or mark.has_note():
                continue
            with self.subTest(index=mark.index):
                badge = self.canvas._badge_rect(0, mark)
                if badge is not None:
                    self.assertIsNone(
                        self.canvas.note_badge_at(badge.center()))

    def test_the_counts_read_the_current_status(self):
        """A chain of Accepted then a reply then Completed is one reply and
        one status, not two: the chain is a history and the status is the
        state it arrived at."""
        mark = self.a_noted_mark()
        chain = self.canvas._file_marks.children(mark)
        statuses = [m for m in chain if m.is_status()]
        replies, current = self.canvas._file_marks.thread(mark)
        self.assertGreaterEqual(len(statuses), 1)
        self.assertEqual(current, statuses[-1].state)
        self.assertEqual(len(replies),
                         len([m for m in chain if m.is_reply()]))

    def test_the_summary_says_who_and_what(self):
        mark = self.a_noted_mark()
        summary = self.canvas.note_summary(mark)
        self.assertIn(mark.author, summary)
        self.assertIn(mark.contents, summary)
        _replies, current = self.canvas._file_marks.thread(mark)
        if current:
            self.assertIn("1", summary.splitlines()[0])

    def inside(self, mark):
        return self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()

    def test_pointing_at_the_mark_shows_the_note(self):
        """Over the whole mark, not only the badge, because that is where
        the pointer goes."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_noted_mark()
        self.send(QMouseEvent.Type.MouseMove, self.inside(mark))
        self.assertIsNotNone(self.canvas._note_panel)
        self.assertIs(self.canvas._note_panel[0], mark)

    def test_leaving_the_mark_takes_it_away(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        mark = self.a_noted_mark()
        at = self.inside(mark)
        self.send(QMouseEvent.Type.MouseMove, at)
        self.assertIsNotNone(self.canvas._note_panel)
        self.send(QMouseEvent.Type.MouseMove,
                  QPointF(at.x(), at.y() + 300))
        self.assertIsNone(self.canvas._note_panel)

    def test_a_mark_with_no_note_shows_no_panel(self):
        from PySide6.QtGui import QMouseEvent

        bare = [m for m, mine in self.canvas.marks_on(0)
                if not mine and not m.has_note()]
        for mark in bare:
            with self.subTest(index=mark.index):
                self.send(QMouseEvent.Type.MouseMove, self.inside(mark))
                self.assertIsNone(self.canvas._note_panel)

    def test_the_panel_is_drawn_rather_than_left_to_a_tooltip(self):
        """A tooltip waits for the pointer to settle and then vanishes on
        its own, which is why the note appeared to show nothing at all.
        Rendered rather than reasoned about: only the pixels can say it is
        on screen."""
        from PySide6.QtGui import QImage, QMouseEvent

        mark = self.a_noted_mark()
        viewport = self.canvas.viewport()

        def painted():
            image = QImage(viewport.size(), QImage.Format_ARGB32)
            image.fill(0xFFFFFFFF)
            viewport.render(image)
            return image

        self.send(QMouseEvent.Type.MouseMove, self.inside(mark))
        settle(timeout_ms=150)
        with_panel = painted()
        self.canvas._show_note_panel(None, self.inside(mark))
        settle(timeout_ms=150)
        without = painted()
        self.assertNotEqual(with_panel, without,
                            "the panel left no mark on the viewport")


class TestTheGripsOnASelectedMark(SelectionCase):
    """Two grips, and dragging one rebuilds the run from the text.

    A highlight is a run of text and not a box, so a resize is not a scale:
    moving a grip re-runs the selection between the new pair of points and
    asks the text what is now covered. Stretching the quadrilaterals would
    give a mark that no longer lines up with any words.
    """

    def document(self):
        return NOTED

    def a_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark to pick")
        return found[0]

    def uid(self):
        return self.win.model.pages[0].uid

    def test_a_mark_only_has_grips_when_it_is_selected(self):
        """Hovering one never shows them, which is what separates the two
        states along with the bar."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark()
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.send(QMouseEvent.Type.MouseMove, at)
        self.assertIsNotNone(self.canvas.hovered_mark())
        self.assertEqual(self.canvas.grips(), [])
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        self.assertEqual(len(self.canvas.grips()), 2)

    def test_they_sit_at_the_ends_of_the_run(self):
        """Not at the corners of the bounding box: a highlight over three
        lines starts at the left of its first and ends at the right of its
        last, and a box's corners are nowhere near either."""
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        start, end = self.canvas.grips()
        boxes = self.canvas.mark_boxes(mark)
        first = self.canvas.quad_on_screen(0, boxes[0], scaled=False)
        last = self.canvas.quad_on_screen(0, boxes[-1], scaled=False)
        self.assertAlmostEqual(start.center().x(), first.left(), delta=2)
        self.assertAlmostEqual(end.center().x(), last.right(), delta=2)
        self.assertLess(start.center().y(), end.center().y())

    def test_a_grip_can_be_pointed_at(self):
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        for n, where in enumerate(self.canvas.grips()):
            with self.subTest(grip=n):
                self.assertEqual(self.canvas.grip_at(where.center()), n)

    def drag_the_end_grip(self, by):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        end = self.canvas.grips()[1].center()
        moved = QPointF(end.x(), end.y() + by)
        self.send(QMouseEvent.Type.MouseButtonPress, end, Qt.LeftButton)
        self.send(QMouseEvent.Type.MouseMove, moved, Qt.LeftButton)
        shown = self.canvas._preview
        self.send(QMouseEvent.Type.MouseButtonRelease, moved, Qt.LeftButton)
        settle(timeout_ms=300)
        return mark, shown

    def test_dragging_a_grip_rebuilds_the_run(self):
        before = len(self.a_mark().boxes())
        mark, _shown = self.drag_the_end_grip(-60)
        kept = self.win.model.mark_edits.of(self.uid(), mark.index)
        self.assertIn("quads", kept)
        self.assertLess(len(kept["quads"]), before)

    def test_the_mark_itself_reports_its_new_run(self):
        """`Mark.quads` holds `/QuadPoints` corner groups, not rectangles.
        Assigning rectangles makes `boxes()` fall through to `/Rect`, so the
        mark reports one box where it has a run -- and its grips, outline
        and badge all follow that wrong answer."""
        mark, _shown = self.drag_the_end_grip(-60)
        kept = self.win.model.mark_edits.of(self.uid(), mark.index)
        self.assertEqual(len(mark.boxes()), len(kept["quads"]))
        self.assertEqual(len(self.canvas.grips()), 2)

    def test_it_is_a_re_run_and_not_a_stretch(self):
        """Shortening by sixty pixels drops whole lines from the run. A
        scaled set of quadrilaterals would keep every one of them and simply
        make them smaller, which would no longer line up with any words."""
        before = len(self.a_mark().boxes())
        mark, shown = self.drag_the_end_grip(-60)
        self.assertLess(len(shown), before)
        for quad in shown:
            with self.subTest(quad=tuple(round(v) for v in quad)):
                self.assertGreater(quad[3] - quad[1], 1.0)

    def a_character_clear_of(self, boxes):
        """Where a real glyph is that the mark does not cover.

        A point guessed below the mark is not the same thing: off the text
        it reports the default cursor, so the I-beam leg would pass for the
        wrong reason. The text layer is asked instead.
        """
        covered = [self.canvas.quad_on_screen(0, b, scaled=False)
                   for b in boxes]
        for box in self.canvas._glyphs.boxes(0):
            if box[4]:
                continue
            at = self.canvas.quad_on_screen(0, box[:4], scaled=False).center()
            if not any(r.adjusted(-4, -4, 4, 4).contains(at) for r in covered):
                return at
        self.skipTest("the page has no glyph outside the mark")

    def test_the_pointer_says_which_hold_it_has(self):
        """Three answers over three places. The grip resizes, so it gets a
        diagonal resize arrow; the body of the mark is a thing to pick up, so it gets
        a plain arrow; bare text is still text, so it keeps the I-beam. An
        I-beam over any part of the mark would promise a text selection that
        pressing there does not give."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        boxes = self.canvas.mark_boxes(mark)
        body = self.canvas.quad_on_screen(0, boxes[0], scaled=False).center()
        grip = self.canvas.grips()[0].center()
        bare = self.a_character_clear_of(boxes)
        for where, want, what in (
                (grip, Qt.SizeFDiagCursor, "a grip"),
                (body, Qt.ArrowCursor, "the mark"),
                (bare, Qt.IBeamCursor, "bare text")):
            with self.subTest(over=what):
                self.send(QMouseEvent.Type.MouseMove, where)
                self.assertEqual(self.canvas.viewport().cursor().shape(), want)

    def test_the_band_being_dragged_is_not_the_mark_s_own_colour(self):
        """A highlight is drawn by multiplying and the original is still in
        the page bitmap, so a band in the mark's colour multiplies with
        itself: orange over orange comes out a red that belongs to neither.
        A neutral band cannot take a colour from what it crosses."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        end = self.canvas.grips()[1].center()
        moved = QPointF(end.x(), end.y() - 40)
        self.send(QMouseEvent.Type.MouseButtonPress, end, Qt.LeftButton)
        self.send(QMouseEvent.Type.MouseMove, moved, Qt.LeftButton)
        band = self.canvas._preview_marks(0)[0]
        self.send(QMouseEvent.Type.MouseButtonRelease, moved, Qt.LeftButton)
        settle(timeout_ms=300)
        self.assertNotEqual(tuple(band.colour), tuple(mark.colour))
        self.assertEqual(len(set(round(v, 1) for v in band.colour)), 1)

    def test_the_selection_survives_the_drag(self):
        self.drag_the_end_grip(-60)
        self.assertIsNotNone(self.canvas.selected_mark())

    def test_a_grip_takes_the_press_from_the_mark_under_it(self):
        """Or grabbing the end of a highlight would select it again and
        start a text selection across it."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=150)
        end = self.canvas.grips()[1].center()
        self.send(QMouseEvent.Type.MouseButtonPress, end, Qt.LeftButton)
        self.assertIsNotNone(self.canvas._dragging_grip)
        self.assertFalse(self.canvas.has_selection(),
                         "the press started a text selection as well")
        self.send(QMouseEvent.Type.MouseButtonRelease, end, Qt.LeftButton)

    def test_the_thread_survives_a_resize(self):
        """It is the same mark, differently sized."""
        noted = [m for m, mine in self.canvas.marks_on(0)
                 if not mine and m.has_note()]
        if not noted:
            self.fail("the fixture is supposed to carry a noted mark")
        mark = noted[0]
        replies, status = self.canvas._file_marks.thread(mark)
        self.win.mark_resized(0, mark, mark.boxes()[:4])
        settle(timeout_ms=300)
        again, now = self.canvas._file_marks.thread(mark)
        self.assertEqual((len(again), now), (len(replies), status))
        self.assertEqual(mark.contents, "Highlight Note")


if __name__ == "__main__":
    unittest.main()


class TestDeletingAMark(SelectionCase):
    """The mark goes, and so does what hangs off it.

    **Which is not what Reader does.** Reader deletes the replies, keeps
    the status annotations and strips the `/IRT` off the one
    that pointed at the mark: measured on a file it wrote, two `/F`-hidden
    `/Text` annotations are left recording that someone Accepted and then
    Completed a comment that no longer exists. Unreachable in Reader's own
    comment panel -- the owner confirmed a deleted comment no longer appears
    in Review History -- and unreachable here, because `MarkMap.visible`
    drops hidden marks. So they go.
    """

    def document(self):
        return NOTED

    def uid(self):
        return self.win.model.pages[0].uid

    def a_reviewed_mark(self):
        """The highlight that carries a reply and a status chain."""
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark to delete")
        mark = found[0]
        chain = self.canvas.chain_of(mark)
        self.assertTrue(any(m.is_reply() for m in chain[1:]),
                        "the fixture's mark has no reply, so the dialog "
                        "and the chain cannot be tested")
        self.assertTrue(any(m.is_status() for m in chain[1:]),
                        "the fixture's mark has no status chain")
        return mark

    def answering(self, button):
        """Answer the confirmation, and record what it was asked.

        `QMessageBox.question` is replaced rather than
        `_confirm_mark_delete`: standing in for our own method would leave
        the thing being tested unrun, and a test that never reaches the
        dialog cannot notice it asking the wrong question or defaulting to
        the wrong button.
        """
        from PySide6.QtWidgets import QMessageBox

        asked = []
        original = QMessageBox.question

        def question(*args, **kwargs):
            asked.append(args)
            return button

        QMessageBox.question = staticmethod(question)
        self.addCleanup(setattr, QMessageBox, "question", original)
        return asked

    def test_the_chain_is_walked_and_not_stepped(self):
        """A status change points at the link before it, so one step finds
        the first and misses the rest."""
        mark = self.a_reviewed_mark()
        chain = self.canvas.chain_of(mark)
        self.assertEqual(len(chain), 4)
        self.assertEqual(sum(1 for m in chain[1:] if m.is_status()), 2)
        self.assertEqual(sum(1 for m in chain[1:] if m.is_reply()), 1)

    def test_every_link_is_recorded_as_deleted(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        self.answering(QMessageBox.Yes)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=400)
        recorded = self.win.model.mark_edits.for_page(self.uid())
        self.assertEqual(len(recorded), 4)
        for index, edit in recorded.items():
            with self.subTest(index=index):
                self.assertTrue(edit.get("deleted"))

    def test_a_mark_with_replies_asks_first(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        asked = self.answering(QMessageBox.Yes)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=400)
        self.assertTrue(asked, "a mark with replies went without asking")
        # The text, and the button the dialog lands on: Cancel, because the
        # replies are somebody else's words and a stray Return must not take
        # them.
        text = asked[0][2]
        self.assertIn("replies", text)
        self.assertEqual(asked[0][4], QMessageBox.Cancel)

    def test_cancelling_keeps_everything(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        before = len(self.canvas.marks_on(0))
        self.answering(QMessageBox.Cancel)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=400)
        self.assertEqual(len(self.canvas.marks_on(0)), before)
        self.assertFalse(self.win.model.mark_edits.for_page(self.uid()))

    def test_it_stops_being_drawn_and_stops_being_hit(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.answering(QMessageBox.Yes)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=600)
        self.assertEqual(
            [m for m, mine in self.canvas.marks_on(0) if not mine], [])
        self.assertIsNone(self.canvas.selected_mark())

    def test_the_delete_key_takes_the_selected_mark(self):
        """And the window's own Delete, which removes *pages*, keeps the key
        whenever no mark is selected."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        pages = len(self.win.model.pages)
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.answering(QMessageBox.Yes)
        self.canvas.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        settle(timeout_ms=600)
        self.assertTrue(self.win.model.mark_edits.for_page(self.uid()))
        self.assertEqual(len(self.win.model.pages), pages,
                         "the page went as well as the mark")

    def test_the_key_is_left_alone_when_no_mark_is_selected(self):
        """Otherwise deleting pages would lose its shortcut while reading."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        self.canvas.select_mark(None)
        settle(timeout_ms=150)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        self.canvas.keyPressEvent(event)
        self.assertFalse(event.isAccepted(),
                         "the canvas swallowed Delete with nothing selected")
        self.assertFalse(self.win.model.mark_edits.for_page(self.uid()))

    def test_the_trash_button_is_live(self):
        mark, where = self.a_mark()
        self.click(where.center())
        settle(timeout_ms=200)
        self.assertTrue(self.win.mark_buttons.buttons["delete"].isEnabled())

    def test_undo_brings_it_back(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        before = len([m for m, mine in self.canvas.marks_on(0) if not mine])
        self.answering(QMessageBox.Yes)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=600)
        self.win.undo()
        settle(timeout_ms=1200)
        self.assertFalse(self.win.model.mark_edits.for_page(self.uid()))
        self.assertEqual(
            len([m for m, mine in self.win.reader.canvas.marks_on(0)
                 if not mine]), before)
