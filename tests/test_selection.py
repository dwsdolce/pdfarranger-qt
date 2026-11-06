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
        if not self.LOCKS_MATTER:
            self.unlock_everything()
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=300)

    #: Whether this case is about the lock. The fixture's first highlight is
    #: locked -- the owner locked it in Reader so that honouring the flag
    #: could be measured -- and a locked mark refuses the editor, the
    #: colour, a resize and a delete. Every case about one of *those* needs
    #: a mark it can work on, so by default the flag is cleared in the map
    #: this session holds. **Nothing is written**: the file on disk still
    #: says locked, and `TestALockedMarkInTheWindow` turns this off to read
    #: it.
    LOCKS_MATTER = False

    def unlock_everything(self) -> None:
        """Clear `locked` on the marks this session is showing."""
        for number in range(1, self.canvas.page_count() + 1):
            for mark in self.canvas._file_marks.visible(number):
                mark.locked = False

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

        Colour was turned on by the step that built the palette, the trash
        by the one that takes a mark with its status chain and its replies,
        and Comment by the note work -- it opens the mark's thread, which
        is a step that exists.
        """
        buttons = self.win.mark_buttons.buttons
        for name in ("colour", "delete", "comment"):
            with self.subTest(button=name, acts=True):
                self.assertTrue(buttons[name].isEnabled())

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
        """**It speaks for the item the badge wears the colour of** -- the
        latest reply on a thread, the mark's own note where there is none.
        Naming the mark's author over a reply's words credits the wrong
        person."""
        mark = self.a_noted_mark()
        speaker = self.canvas.latest_reply(mark) or mark
        summary = self.canvas.note_summary(mark)
        self.assertIn(speaker.author, summary)
        self.assertIn(speaker.contents, summary)
        _replies, current = self.canvas._file_marks.thread(mark)
        if current:
            self.assertIn("1", summary.splitlines()[0])

    def inside(self, mark):
        return self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()

    def a_mark_whose_window_is_closed(self):
        """A noted mark that hovering should answer with the summary.

        **The summary is for a closed window.** A mark whose `/Popup` the
        file left open is answered with the thread itself instead, which is
        the distinction the flag carries -- so a test about the summary has
        to use a mark that is not in that state. The fixture's is open, so
        it is closed here rather than hunting for another document.
        """
        mark = self.a_noted_mark()
        mark.popup_open = False
        return mark

    def test_pointing_at_the_mark_shows_the_note(self):
        """Over the whole mark, not only the badge, because that is where
        the pointer goes."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark_whose_window_is_closed()
        self.send(QMouseEvent.Type.MouseMove, self.inside(mark))
        self.assertIsNotNone(self.canvas._note_panel)
        self.assertIs(self.canvas._note_panel[0], mark)

    def test_leaving_the_mark_takes_it_away(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark_whose_window_is_closed()
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

        mark = self.a_mark_whose_window_is_closed()
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
        the first and misses the rest.

        **Counted against one step, not against a number.** The fixture
        grows as the owner marks up more of it, and a test that knows how
        many links are in it is a test that breaks when he does.
        """
        mark = self.a_reviewed_mark()
        chain = self.canvas.chain_of(mark)
        direct = [m for m in chain[1:] if m.parent == mark.name]
        self.assertGreater(len(chain) - 1, len(direct),
                           "nothing in the fixture hangs off a link")
        self.assertTrue(any(m.is_status() for m in chain[1:]))
        self.assertTrue(any(m.is_reply() for m in chain[1:]))

    def test_every_link_is_recorded_as_deleted(self):
        from PySide6.QtWidgets import QMessageBox

        mark = self.a_reviewed_mark()
        # Before the delete: the canvas forgets the chain as it goes, so
        # asking afterwards asks about a mark with nothing left under it.
        going = sorted(m.index for m in self.canvas.chain_of(mark))
        self.answering(QMessageBox.Yes)
        self.win.delete_mark(0, mark)
        settle(timeout_ms=400)
        recorded = self.win.model.mark_edits.for_page(self.uid())
        self.assertEqual(sorted(recorded), going)
        self.assertGreater(len(going), 1, "the fixture's mark has no chain")
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


class TestTheMenuOnAMark(SelectionCase):
    """Right-clicking a mark offers the mark's menu, not the page's.

    Five groups, as Reader has them, with two entries conditional: *Reply*
    once there is a comment to reply to, and *Delete Thread* in place of
    *Delete* once somebody has replied. Reader's three comment-panel
    entries are left out, by the owner's decision, because there is no
    panel here for them to open.
    """

    def document(self):
        return NOTED

    def a_mark_on(self, page: int):
        found = [m for m, mine in self.canvas.marks_on(page) if not mine]
        if not found:
            self.skipTest(f"the fixture has no mark on page {page + 1}")
        return found[0]

    def menu_for(self, page: int, mark):
        return self.canvas.mark_menu(page, mark)

    @staticmethod
    def entries(menu):
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    @staticmethod
    def enabled(menu, text):
        for action in menu.actions():
            if action.text() == text:
                return action.isEnabled()
        return None

    def test_a_mark_with_replies_offers_delete_thread(self):
        mark = self.a_mark_on(0)
        chain = self.canvas.chain_of(mark)
        if not any(m.is_reply() for m in chain[1:]):
            self.skipTest("the fixture's first mark carries no reply")
        entries = self.entries(self.menu_for(0, mark))
        self.assertIn("Delete Thread", entries)
        self.assertNotIn("Delete", entries)
        self.assertIn("Reply", entries)

    def test_a_mark_with_no_comment_offers_delete_and_no_reply(self):
        for page in (1, 2):
            mark = self.a_mark_on(page)
            if mark.contents or self.canvas.chain_of(mark)[1:]:
                continue
            entries = self.entries(self.menu_for(page, mark))
            self.assertIn("Delete", entries)
            self.assertNotIn("Delete Thread", entries)
            self.assertNotIn("Reply", entries)
            return
        self.skipTest("every mark in the fixture carries a comment")

    def test_the_note_entry_is_there_either_way(self):
        """It does not turn into Reply: it is how the note is reached
        whether or not one has been written."""
        for page in (0, 1):
            mark = self.a_mark_on(page)
            with self.subTest(page=page + 1):
                self.assertEqual(
                    self.entries(self.menu_for(page, mark))[0],
                    "Open Pop-Up Note")

    def test_the_comment_panel_entries_are_not_offered(self):
        """There is no panel here and no pop-up windows to manage."""
        entries = self.entries(self.menu_for(0, self.a_mark_on(0)))
        for absent in ("Open comment panel", "Open all Pop-Ups",
                       "Minimize Pop-Ups", "Hide comment panel"):
            with self.subTest(entry=absent):
                self.assertNotIn(absent, entries)

    def test_what_acts_and_what_waits(self):
        """Each entry is turned on by the step that builds it, which is how
        the bar's buttons work too. **Nothing is waiting any more**: the
        properties form was the last of them, and the menu carried its
        entry disabled from the start until the step that built it."""
        menu = self.menu_for(0, self.a_mark_on(0))
        for text, acts in (("Delete Thread", True), ("Copy Text", True),
                           ("Enable Text Selection", True),
                           ("Make current properties default", True),
                           ("Open Pop-Up Note", True), ("Reply", True),
                           ("Set status", True), ("Properties...", True)):
            with self.subTest(entry=text):
                self.assertEqual(self.enabled(menu, text), acts)

    def test_copy_text_takes_what_the_mark_covers(self):
        """A line to each quadrilateral, and nothing from the line below:
        a quadrilateral is a loose box whose foot overlaps it."""
        mark = self.a_mark_on(0)
        quads = len(self.canvas.mark_boxes(mark))
        lines = self.canvas.mark_text(0, mark).splitlines()
        self.assertTrue(lines, "the mark covers text but none was found")
        self.assertLessEqual(len(lines), quads)

    def test_a_mark_over_no_text_offers_no_copy(self):
        from pdfarranger_qt import markup

        drawn = markup.Annotation(markup.TEXT, 0, (10.0, 10.0, 30.0, 30.0))
        menu = self.canvas.mark_menu(0, drawn)
        self.assertFalse(self.enabled(menu, "Copy Text"))

    def test_enabling_text_selection_gives_the_page_menu_back(self):
        mark = self.a_mark_on(0)
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.assertIn("Copy Text",
                      self.entries(self.canvas.build_context_menu(at)))
        self.canvas.let_text_through()
        entries = self.entries(self.canvas.build_context_menu(at))
        self.assertNotIn("Copy Text", entries)
        self.assertIn("Select All", entries)

    def test_it_lets_one_press_reach_the_text_and_no_more(self):
        """Reader's lasts until the next selection, and so does this."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_mark_on(0)
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.click(at)
        settle(timeout_ms=150)
        self.assertIsNotNone(self.canvas.selected_mark(),
                             "a press on a mark should take the mark")
        self.canvas.select_mark(None)
        self.canvas.let_text_through()
        self.send(QMouseEvent.Type.MouseButtonPress, at)
        self.assertIsNone(self.canvas.selected_mark(),
                          "the press was supposed to reach the text")
        self.send(QMouseEvent.Type.MouseButtonRelease, at)
        settle(timeout_ms=150)
        self.click(at)
        settle(timeout_ms=150)
        self.assertIsNotNone(self.canvas.selected_mark(),
                             "it outlasted the selection it allowed")

    def test_making_it_the_default_arms_what_the_next_mark_gets(self):
        from pdfarranger_qt import markup

        mark = self.a_mark_on(0)
        self.win.armed_colour = None
        self.win.armed_opacity = None
        self.win.mark_is_the_default(mark)
        self.assertEqual(self.win.armed_colour, tuple(mark.colour))
        self.assertAlmostEqual(self.win.armed_opacity,
                               markup.solidity(mark), places=4)


class TestTheNoteOnAMark(SelectionCase):
    """*Open Pop-Up Note*: the thread, shown and edited over the page.

    The note is the mark's own text and each reply is a mark of its own, so
    the panel is a list -- and the one it opens on is always the note,
    however many replies are under it, which is Reader's behaviour.
    """

    def document(self):
        return NOTED

    def uid(self):
        return self.win.model.pages[0].uid

    def a_noted_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark")
        mark = found[0]
        if not mark.contents:
            self.skipTest("the fixture's mark carries no note")
        return mark

    def test_the_entry_opens_the_thread(self):
        mark = self.a_noted_mark()
        menu = self.canvas.mark_menu(0, mark)
        entry = next(a for a in menu.actions()
                     if a.text() == "Open Pop-Up Note")
        self.assertTrue(entry.isEnabled())
        entry.trigger()
        settle(timeout_ms=250)
        self.assertTrue(self.win.note_panel.isVisible())

    def test_it_lists_the_note_and_then_the_replies(self):
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        items = self.win.note_panel.items()
        replies = [m for m in self.canvas.chain_of(mark)[1:] if m.is_reply()]
        self.assertEqual(len(items), 1 + len(replies))
        self.assertEqual(items[0].text, mark.contents)
        self.assertEqual(self.win.note_panel.selected(), 0)

    def test_every_item_shows_its_own_status(self):
        """**A reply carries a status of its own**, so the note's is the
        note's: each row is the last link of that item's own chain."""
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        items = self.win.note_panel.items()
        thread = self.win._noted[1]
        self.assertEqual(len(items), len(thread))
        for item, one in zip(items, thread):
            chain = self.canvas.status_chain(0, one)
            want = str(chain[-1].state).lstrip("/") if chain else None
            with self.subTest(length=len(item.text)):
                self.assertEqual(item.status,
                                 None if want == "None" else want)

    def test_posting_the_note_records_it(self):
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        self.win.note_panel._editor.setPlainText("Rewritten here")
        self.win.note_panel._post_it()
        settle(timeout_ms=500)
        self.assertEqual(
            self.win.model.mark_edits.of(self.uid(), mark.index).get("contents"),
            "Rewritten here")

    def test_a_reply_is_written_as_a_mark_of_its_own(self):
        mark = self.a_noted_mark()
        self.win.reply_to(0, mark)
        settle(timeout_ms=300)
        panel = self.win.note_panel
        self.assertFalse(panel._post.isEnabled(), "an empty reply could post")
        panel._editor.setPlainText("An answer")
        panel._post_it()
        settle(timeout_ms=600)
        ours = [a for a in self.win.model.annotations.for_page(self.uid())
                if a.irt]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].irt, mark.name)
        self.assertEqual(ours[0].contents, "An answer")

    def test_an_abandoned_reply_writes_nothing(self):
        mark = self.a_noted_mark()
        self.win.reply_to(0, mark)
        settle(timeout_ms=300)
        self.win.note_panel._cancel()
        settle(timeout_ms=200)
        self.assertEqual(self.win.model.annotations.for_page(self.uid()), [])

    def test_reading_a_note_does_not_change_the_document(self):
        """Save is enabled by there being pages, never by this, so marking
        the document dirty would do nothing but ask "save your changes?" on
        close because somebody read a note."""
        mark = self.a_noted_mark()
        self.win.modified = False
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.assertFalse(self.win.modified)

    def test_the_cross_puts_the_window_away_and_it_stays_away(self):
        """The pointer offers the window on a mark the file saved open, and
        offered it again on every mouse move -- so the cross used to put it
        away for exactly as long as it took to move the mouse."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_noted_mark()
        if not mark.popup_open:
            self.skipTest("the fixture's window was saved closed")
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.send(QMouseEvent.Type.MouseMove, at)
        settle(timeout_ms=400)
        self.assertTrue(self.win.note_panel.isVisible())
        self.win.note_panel._shut()
        settle(timeout_ms=200)
        self.send(QMouseEvent.Type.MouseMove, at)
        settle(timeout_ms=400)
        self.assertFalse(self.win.note_panel.isVisible(),
                         "hovering brought a closed window straight back")
        self.assertIsNotNone(self.canvas._note_panel,
                             "and the summary did not take its place")

    def test_the_entry_opens_a_window_that_was_closed_by_hand(self):
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        self.win.note_panel._shut()
        settle(timeout_ms=200)
        self.assertTrue(self.canvas.note_window_is_shut(0, mark))
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        self.assertTrue(self.win.note_panel.isVisible())
        self.assertFalse(self.canvas.note_window_is_shut(0, mark))

    def test_closing_the_window_does_not_step_the_form(self):
        """**Hiding a widget that holds the focus runs Qt's own traversal**,
        and this canvas reads that traversal as Tab -- so each close put the
        caret in the next field of the form, and the one after that."""
        mark = self.a_noted_mark()
        for _again in range(3):
            self.win.open_note(0, mark)
            settle(timeout_ms=250)
            self.win.note_panel._shut()
            settle(timeout_ms=250)
            self.assertIsNone(self.canvas.focused_field())

    def test_a_click_on_the_window_does_not_reach_the_page(self):
        """Qt passes a mouse event the widget ignores up to its parent, and
        this window's parent is the page it floats over."""
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        panel = self.win.note_panel
        self.canvas.select_mark(None)
        settle(timeout_ms=150)
        blank = QPoint(panel.width() // 2, panel.height() - 30)
        for kind in (QMouseEvent.Type.MouseButtonPress,
                     QMouseEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(panel, QMouseEvent(
                kind, QPointF(blank), QPointF(panel.mapToGlobal(blank)),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=250)
        self.assertIsNone(self.canvas.selected_mark(),
                          "the click went through the window")

    def test_a_status_posts_what_is_in_the_box_first(self):
        """**Acrobat treats setting a status as a post of whatever has been
        typed**, not as a cancel. Taken from the owner, 2026-11-03."""
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.win.note_panel._editor.setPlainText("Typed but never posted")
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=700)
        self.assertEqual(
            self.win.model.mark_edits.of(self.uid(), mark.index).get("contents"),
            "Typed but never posted")
        self.assertEqual(self.win.note_panel.items()[0].status, "Rejected")

    def test_reply_posts_what_is_in_the_box_first(self):
        """The same rule, and the new blank is what stays open -- closing
        the editor on what was posted must not close the one Reply made."""
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.win.note_panel._editor.setPlainText("Kept on the way to a reply")
        was = len(self.win.note_panel.items())
        self.win.reply_to(0, mark)
        settle(timeout_ms=700)
        self.assertEqual(
            self.win.model.mark_edits.of(self.uid(), mark.index).get("contents"),
            "Kept on the way to a reply")
        self.assertEqual(len(self.win.note_panel.items()), was + 1)
        self.assertEqual(self.win.note_panel.selected(), was)
        self.assertFalse(self.win.note_panel._post.isEnabled(),
                         "the new reply is not empty")

    def test_nothing_typed_posts_nothing(self):
        """Otherwise every status change would record an edit to the text
        that nobody made."""
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=700)
        self.assertNotIn(
            "contents", self.win.model.mark_edits.of(self.uid(), mark.index))

    def test_the_window_offers_no_entry_to_open_itself(self):
        """Inside the thread there is nothing to open: it is already
        showing, and Acrobat leaves the entry out there too."""
        mark = self.a_noted_mark()
        inside = [a.text() for a
                  in self.canvas.mark_menu(0, mark, inside=True).actions()]
        self.assertNotIn("Open Pop-Up Note", inside)
        self.assertIn("Open Pop-Up Note",
                      [a.text() for a in self.canvas.mark_menu(0, mark).actions()])
        self.assertIn("Delete Thread", inside)

    def test_the_summary_draws_what_the_file_styled(self):
        """Painted text, not a widget, so showing the styling means drawing
        it through a `QTextDocument`.

        **The same words twice, with the styling and without.** Rendering
        only the styled one measures the font, not the drawing: the
        comparison is the test.
        """
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QImage

        from pdfarranger_qt import markup

        mark = self.a_noted_mark()
        # The item the panel speaks for, which is the latest reply on a
        # thread. Blanking the mark's own rich text proves nothing when
        # what is drawn belongs to a reply.
        target = self.canvas.latest_reply(mark) or mark
        if not markup.rich_to_html(getattr(target, "rich", "")):
            self.skipTest(
                "the summary speaks for the thread's *last* reply, and that "
                "one carries no styling in this fixture -- style it in "
                "Reader and this runs")
        keep = target.rich
        self.addCleanup(setattr, target, "rich", keep)

        def shot():
            self.canvas._show_note_panel(None, QPointF(0, 0))
            settle(timeout_ms=150)
            self.canvas._show_note_panel(mark, QPointF(60, 60), 0)
            settle(timeout_ms=200)
            image = QImage(self.canvas.viewport().size(), QImage.Format_ARGB32)
            image.fill(0)
            self.canvas.viewport().render(image)
            return [image.pixel(x, y)
                    for y in range(60, 240) for x in range(60, 360)]

        # **Pixels that differ, not ink counted.** Counting dark pixels
        # assumed styling can only add -- true of bold and underline, false
        # of colour, which paints lighter than black and made the styled
        # version look like *less* drawing than the plain one.
        styled_shot = shot()
        target.rich = ""
        differ = sum(1 for a, b in zip(styled_shot, shot()) if a != b)
        self.assertGreater(differ, 50,
                           "the summary drew the same thing either way")

    def test_closing_the_document_takes_the_window_with_it(self):
        """The window belongs to the mark it was opened on, and closing the
        document leaves no mark. It used to stay floating over an empty
        reader, still offering to post a reply to something that was no
        longer there."""
        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=250)
        self.assertTrue(self.win.note_panel.isVisible())
        self.win.modified = False
        self.win.close_document()
        settle(timeout_ms=250)
        self.assertFalse(self.win.note_panel.isVisible())

    def test_an_open_window_in_the_file_shows_on_hover(self):
        """`/Popup /Open` says the window was showing when the file was
        saved. Hovering such a mark gives the thread; hovering one whose
        window is closed gives the one-line summary instead."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_noted_mark()
        if not mark.popup_open:
            self.skipTest("the fixture's window was saved closed")
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.send(QMouseEvent.Type.MouseMove, at)
        settle(timeout_ms=400)
        self.assertTrue(self.win.note_panel.isVisible())

    def test_hovering_again_does_not_throw_away_what_is_being_typed(self):
        """The hover asks for the thread on every mouse move, so the window
        has to notice it is already showing the one being asked for."""
        from PySide6.QtGui import QMouseEvent

        mark = self.a_noted_mark()
        if not mark.popup_open:
            self.skipTest("the fixture's window was saved closed")
        at = self.canvas.quad_on_screen(
            0, self.canvas.mark_boxes(mark)[0], scaled=False).center()
        self.send(QMouseEvent.Type.MouseMove, at)
        settle(timeout_ms=300)
        self.win.note_panel._editor.setPlainText("half a thought")
        for _again in range(3):
            self.send(QMouseEvent.Type.MouseMove, at)
        settle(timeout_ms=200)
        self.assertEqual(self.win.note_panel._editor.toPlainText(),
                         "half a thought")

    def test_moving_the_window_does_change_it(self):
        """The other side of the same line: this writes a new `/Popup
        /Rect`, and reading does not write anything."""
        from PySide6.QtCore import QRect

        mark = self.a_noted_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.win.modified = False
        panel = self.win.note_panel
        panel._sized = True
        panel.setGeometry(QRect(60, 70, 320, 240))
        settle(timeout_ms=300)
        self.assertTrue(self.win.modified)
        self.assertIn(
            "popup", self.win.model.mark_edits.of(self.uid(), mark.index))


class TestSettingTheStatus(SelectionCase):
    """*Set status*: five states, the current one ticked."""

    def document(self):
        return NOTED

    def a_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark")
        return found[0]

    def submenu(self, mark):
        menu = self.canvas.mark_menu(0, mark)
        return next(a.menu() for a in menu.actions()
                    if a.text() == "Set status")

    def test_it_offers_the_five_readers_offers(self):
        from pdfarranger_qt import markup

        entries = [a.text() for a in self.submenu(self.a_mark()).actions()]
        self.assertEqual(entries, list(markup.STATUSES))

    def test_the_tick_is_on_the_current_one(self):
        """The *last* link in the chain, not the only one: a mark accepted
        and then completed has one status, Completed."""
        mark = self.a_mark()
        ticked = [a.text() for a in self.submenu(mark).actions()
                  if a.isChecked()]
        self.assertEqual(ticked, [self.canvas.status_of(mark)])

    def test_choosing_one_appends_a_link_to_the_chain(self):
        mark = self.a_mark()
        before = self.canvas.status_of(mark)
        self.assertNotEqual(before, "Rejected")
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=600)
        uid = self.win.model.pages[0].uid
        ours = [a for a in self.win.model.annotations.for_page(uid) if a.state]
        self.assertEqual([a.state for a in ours], ["Rejected"])

    def test_it_answers_the_end_of_the_chain(self):
        mark = self.a_mark()
        chain = [m for m in self.canvas.chain_of(mark)[1:] if m.is_status()]
        if not chain:
            self.skipTest("the fixture's mark has no status chain")
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=600)
        uid = self.win.model.pages[0].uid
        ours = [a for a in self.win.model.annotations.for_page(uid) if a.state]
        self.assertEqual(ours[0].irt, chain[-1].name)

    def test_setting_the_one_it_already_has_writes_nothing(self):
        mark = self.a_mark()
        self.win.set_mark_status(0, mark, self.canvas.status_of(mark))
        settle(timeout_ms=400)
        uid = self.win.model.pages[0].uid
        self.assertEqual(
            [a for a in self.win.model.annotations.for_page(uid) if a.state],
            [])


class TestAStatusBeforeTheFileIsWritten(SelectionCase):
    """A status set here is an annotation in the model until the document is
    saved. **Read from the file alone, nothing you just did is there** -- the
    tick, the thread and the guard against setting the status it already has
    were all reading past it."""

    def document(self):
        return NOTED

    def a_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark")
        return found[0]

    def ticked(self, mark):
        menu = self.canvas.mark_menu(0, mark)
        sub = next(a.menu() for a in menu.actions() if a.text() == "Set status")
        return [a.text() for a in sub.actions() if a.isChecked()]

    def test_the_tick_follows_what_was_just_set(self):
        mark = self.a_mark()
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=600)
        self.assertEqual(self.ticked(mark), ["Rejected"])

    def test_the_thread_follows_it_while_it_is_open(self):
        """Otherwise the only way to see what you set is to close the window
        and open it again."""
        mark = self.a_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=600)
        self.assertEqual(self.win.note_panel.items()[0].status, "Rejected")

    def test_a_status_of_none_leaves_no_status_row(self):
        """It is a link in the history like any other -- that is how a status
        is taken back -- but the thread says what the status *is*."""
        from PySide6.QtWidgets import QLabel

        def rows():
            return len([lab for lab in self.win.note_panel.findChildren(QLabel)
                        if lab.property("role") == "status"])

        mark = self.a_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        self.assertIsNotNone(self.win.note_panel.items()[0].status,
                             "the fixture's note has no status to take back")
        before = rows()
        self.win.set_mark_status(0, mark, "None")
        settle(timeout_ms=600)
        self.assertIsNone(self.win.note_panel.items()[0].status)
        self.assertEqual(rows(), before - 1)

    def test_a_reply_carries_a_status_of_its_own(self):
        """Nothing in the format makes this special: a reply is a mark, and
        a status points at whatever it answers."""
        mark = self.a_mark()
        self.win.open_note(0, mark)
        settle(timeout_ms=300)
        replies = self.win._replies_to(0, mark)
        if not replies:
            self.skipTest("the fixture's mark has no reply")
        self.win.set_mark_status(0, replies[0], "Cancelled")
        settle(timeout_ms=600)
        items = self.win.note_panel.items()
        self.assertEqual(items[1].status, "Cancelled")
        self.assertNotEqual(items[0].status, "Cancelled",
                            "it was set on the note instead")

    def test_the_summary_counts_a_reply_written_here(self):
        """Counting the file's alone said one reply at a thread of two until
        the document had been written out and read back."""
        mark = self.a_mark()
        was = len(self.win._replies_to(0, mark))
        self.win._write_reply(0, mark, "Said here")
        settle(timeout_ms=600)
        self.assertIn("%d Replies" % (was + 1),
                      self.canvas.note_summary(mark, 0))


class TestTheMenusInsideTheWindow(SelectionCase):
    """The first item is the comment, so its line gives the mark's menu.
    A reply's line gives a menu of its own."""

    def document(self):
        return NOTED

    def setUp(self):
        super().setUp()
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark")
        self.mark = found[0]
        self.win.open_note(0, self.mark)
        settle(timeout_ms=300)
        if len(self.win.note_panel.items()) < 2:
            self.skipTest("the fixture's mark has no reply")

    def entries(self, which):
        self.win.note_menu(which, self.win.note_panel.mapToGlobal(
            self.win.note_panel.rect().center()))
        return which

    def test_a_replys_line_offers_reply_delete_and_status(self):
        menu = self.win._reply_menu(0, self.win._noted[1][1])
        names = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(names[:3], ["Reply", "Delete", "Set status"])
        self.assertIn("Properties...", names)
        self.assertNotIn("Delete Thread", names)

    def test_the_status_submenu_ticks_the_replys_own(self):
        reply = self.win._noted[1][1]
        self.win.set_mark_status(0, reply, "Cancelled")
        settle(timeout_ms=600)
        menu = self.win._reply_menu(0, reply)
        sub = next(a.menu() for a in menu.actions() if a.text() == "Set status")
        self.assertEqual([a.text() for a in sub.actions() if a.isChecked()],
                         ["Cancelled"])

    def test_deleting_a_reply_takes_its_line_and_leaves_the_rest(self):
        was = len(self.win.note_panel.items())
        self.win.delete_mark(0, self.win._noted[1][1])
        settle(timeout_ms=700)
        self.assertEqual(len(self.win.note_panel.items()), was - 1)
        self.assertTrue(self.win.note_panel.isVisible())

    def test_deleting_the_comment_takes_the_window_with_it(self):
        """There is no thread left to show. The confirmation is answered
        because the mark has a reply -- that is what it warns about."""
        from PySide6.QtWidgets import QMessageBox

        original = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        self.addCleanup(setattr, QMessageBox, "question", original)
        self.win.delete_mark(0, self.mark)
        settle(timeout_ms=700)
        self.assertFalse(self.win.note_panel.isVisible())


class TestALockedMarkInTheWindow(SelectionCase):
    """A lock is `/F` bit 8 on one annotation, so it is per item: a locked
    mark leaves its replies editable and a locked reply sits in a thread
    whose other items are not.

    What it refuses was taken from the owner against Acrobat on 2026-11-03:
    the editor, the colour, the opacity, a resize and a delete. Replying to
    a locked mark and setting a status on one are both still allowed --
    each is a *new* annotation, which the lock does not reach.
    """

    LOCKS_MATTER = True

    def document(self):
        return NOTED

    def uid(self):
        return self.win.model.pages[0].uid

    def a_locked_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0)
                 if not mine and m.locked]
        if not found:
            self.skipTest("nothing on the fixture's first page is locked")
        return found[0]

    def test_it_is_still_selected_and_outlined(self):
        """Only its ends are not draggable. A mark that cannot be picked up
        at all would be a different kind of object."""
        mark = self.a_locked_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=250)
        self.assertTrue(self.canvas.selection_on_screen())
        self.assertEqual(self.canvas.grips(), [],
                         "a locked mark offered handles to resize it by")

    def test_the_bar_greys_what_would_change_it(self):
        mark = self.a_locked_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=250)
        self.assertFalse(self.win.mark_buttons.buttons["colour"].isEnabled())
        self.assertFalse(self.win.mark_buttons.buttons["delete"].isEnabled())

    def test_a_colour_a_resize_and_a_delete_are_all_refused(self):
        """Refused where they are recorded, not only where they are
        offered: the Delete key reaches one of these too."""
        mark = self.a_locked_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=250)
        self.win.modified = False
        self.win.mark_recoloured((1.0, 0.0, 0.0))
        self.win.mark_resized(0, mark, [(10.0, 10.0, 90.0, 30.0)])
        self.win.delete_mark(0, mark)
        settle(timeout_ms=400)
        self.assertFalse(self.win.modified)
        self.assertEqual(self.win.model.mark_edits.for_page(self.uid()), {})

    def test_delete_is_shown_and_greyed_rather_than_left_out(self):
        """Acrobat leaves it out; the owner prefers to see that it exists
        and is refused."""
        mark = self.a_locked_mark()
        greyed = [a for a in self.canvas.mark_menu(0, mark).actions()
                  if a.text() in ("Delete", "Delete Thread")]
        self.assertTrue(greyed)
        self.assertFalse(greyed[0].isEnabled())

    def test_replying_and_setting_a_status_are_still_allowed(self):
        """Each is a new annotation pointing at the locked one, which the
        lock does not reach."""
        mark = self.a_locked_mark()
        self.win.reply_to(0, mark)
        settle(timeout_ms=400)
        self.win.note_panel._editor.setPlainText("An answer to a locked mark")
        self.win.note_panel._post_it()
        settle(timeout_ms=500)
        self.win.set_mark_status(0, mark, "Rejected")
        settle(timeout_ms=500)
        ours = self.win.model.annotations.for_page(self.uid())
        self.assertTrue(any(a.irt and not a.state for a in ours), "no reply")
        self.assertTrue(any(a.state == "Rejected" for a in ours), "no status")

    def test_the_form_opens_on_it_because_that_is_where_the_lock_comes_off(self):
        mark = self.a_locked_mark()
        entry = [a for a in self.canvas.mark_menu(0, mark).actions()
                 if a.text() == "Properties..."]
        self.assertTrue(entry)
        self.assertTrue(entry[0].isEnabled())

    def test_the_form_writes_the_three_keys_and_the_flag(self):
        from pdfarranger_qt.properties import MarkProperties

        mark = self.a_locked_mark()
        original = MarkProperties.exec

        def answer(form):
            form.locked.setChecked(False)
            form.author.setText("Someone Else")
            form.subject.setText("A subject")
            return MarkProperties.DialogCode.Accepted

        MarkProperties.exec = answer
        self.addCleanup(setattr, MarkProperties, "exec", original)
        self.win.show_mark_properties(0, mark)
        settle(timeout_ms=500)
        self.assertEqual(
            self.win.model.mark_edits.of(self.uid(), mark.index),
            {"author": "Someone Else", "subject": "A subject",
             "locked": False})


class TestUndoWhileReading(SelectionCase):
    """**Markup is an edit that happens in read mode.** Undo and redo live
    in the Edit menu, and read mode disables that menu because its other
    commands change the page list -- so they were swept up with the rest
    and a mark could not be taken back."""

    def uid(self):
        return self.win.model.pages[0].uid

    def test_it_is_offered_once_there_is_something_to_undo(self):
        self.assertFalse(self.win.act_undo.isEnabled(),
                         "nothing has been done yet")
        self.win.tool_strip.arm("underline")
        settle(timeout_ms=150)
        self.canvas.mark_drawn.emit("underline", 0,
                                    [(60.0, 700.0, 300.0, 714.0)])
        settle(timeout_ms=400)
        self.assertTrue(self.win.read_mode, "this is the mode markup is in")
        self.assertTrue(self.win.act_undo.isEnabled())
        self.assertIn("Add Mark", self.win.act_undo.text())

    def test_it_takes_the_mark_back_and_puts_it_again(self):
        self.win.tool_strip.arm("underline")
        settle(timeout_ms=150)
        self.canvas.mark_drawn.emit("underline", 0,
                                    [(60.0, 700.0, 300.0, 714.0)])
        settle(timeout_ms=400)
        self.assertEqual(len(self.win.model.annotations.for_page(self.uid())), 1)
        self.win.undo()
        settle(timeout_ms=400)
        self.assertEqual(self.win.model.annotations.for_page(self.uid()), [])
        self.assertTrue(self.win.act_redo.isEnabled())
        self.win.redo()
        settle(timeout_ms=400)
        self.assertEqual(len(self.win.model.annotations.for_page(self.uid())), 1)

    def test_the_rest_of_the_edit_menu_stays_shut(self):
        """Only these two are exempt: the others do change the page list."""
        for act in self.win._editing_actions():
            if act in (self.win.act_undo, self.win.act_redo):
                continue
            with self.subTest(action=act.text()):
                self.assertFalse(act.isEnabled())
