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

"""The strip the markup tools are chosen from (step 4.2).

Every tool can be armed and none of them does anything: what a tool *makes*
arrives one at a time from 4.3. So what is tested here is the surface -- that
every declared tool is reachable, that arming is a mode which survives until
something ends it, and that the strip belongs to read mode and goes away when
the document is being arranged instead.
"""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from support import FIXTURES, settle

PDF = os.path.join(FIXTURES, "exporter", "outlines.pdf")


class StripCase(unittest.TestCase):
    """A window with a document open and the strip showing."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([PDF])
        settle(timeout_ms=400)
        self.strip = self.win.tool_strip

    def tearDown(self):
        self.win.modified = False
        self.win.close()
        # The settings store is scoped to the process rather than to a test,
        # so a strip left open here opens in every window built afterwards --
        # over the top left of the reader, where other tests start the drags
        # that make their marks.
        for key in ("reader/markup-tools", "reader/markup-tools-at"):
            self.win.settings.remove(key)

    def open_strip(self):
        self.win.act_markup_tools.setChecked(True)
        settle(timeout_ms=100)


class TestEveryToolIsReachable(StripCase):

    def test_each_family_has_a_button(self):
        from pdfarranger_qt import tools

        self.assertEqual(sorted(self.strip.buttons), sorted(tools.FAMILIES))

    def test_every_declared_tool_is_in_its_family(self):
        """The strip is generated, so a tool that is declared is offered.

        Which is the point of declaring them once: a tool nobody wired into a
        menu is the failure this replaces.
        """
        from pdfarranger_qt import tools

        for tool in tools.TOOLS:
            with self.subTest(tool=tool.name):
                button = self.strip.buttons[tool.family]
                self.assertIn(tool.name, button.actions_by_tool)

    def test_the_whole_declaration_is_offered_and_nothing_else(self):
        from pdfarranger_qt import tools

        offered = sorted(name for button in self.strip.buttons.values()
                         for name in button.actions_by_tool)
        self.assertEqual(offered, sorted(t.name for t in tools.TOOLS))

    def test_there_are_twenty_one_of_them(self):
        """The count the plan speaks of, so a quiet loss of one is visible.

        It read twenty-one for two days, while *Add note to text* had an
        entry here. It never had one in Reader: that is a right-click entry
        over a selection, and the tool it reaches is Add a comment. It is
        twenty-one again for a better reason: *Add a scalable comment*,
        which Reader does not have either but which is a tool here and not
        a gesture -- it writes a different subtype.
        """
        from pdfarranger_qt import tools

        self.assertEqual(len(tools.TOOLS), 21)

    def test_no_signature_tool_is_offered(self):
        """This application does not sign, so there is no such tool."""
        from pdfarranger_qt import tools

        names = " ".join(t.name + " " + t.label for t in tools.TOOLS).lower()
        self.assertNotIn("signature", names)
        self.assertNotIn("initials", names)

    def test_every_icon_resolves(self):
        """A missing glyph is a blank button, which reads as a broken one."""
        from pdfarranger_qt import tools

        for tool in tools.TOOLS:
            with self.subTest(tool=tool.name):
                icon = self.strip._actions[tool.name].icon()
                self.assertFalse(icon.isNull(), tool.icon)


class TestArmingIsAMode(StripCase):

    def test_select_is_armed_to_begin_with(self):
        from pdfarranger_qt import tools

        self.assertEqual(self.strip.armed(), tools.DEFAULT)

    def test_arming_sticks(self):
        """It stays until something ends it, which is what a mode means."""
        self.strip.arm("highlight")
        self.assertEqual(self.strip.armed(), "highlight")
        self.strip.arm("highlight")
        self.assertEqual(self.strip.armed(), "highlight")

    def test_only_one_tool_is_armed_across_the_whole_strip(self):
        """Exclusive over the strip, not within a family.

        Otherwise a tick survives in a family nobody is using any more, and
        two tools look armed at once.
        """
        self.strip.arm("highlight")
        self.strip.arm("arrow")
        checked = [name for name, action in self.strip._actions.items()
                   if action.isChecked()]
        self.assertEqual(checked, ["arrow"])

    def test_the_family_button_shows_what_it_will_re_arm(self):
        """Reader's behaviour: the button carries the last tool used from it."""
        self.strip.arm("cloud")
        button = self.strip.buttons["drawing"]
        self.assertEqual(button.defaultAction().data(), "cloud")

    def test_arming_is_announced_once(self):
        armed = []
        self.strip.armed_changed.connect(armed.append)
        self.strip.arm("underline")
        self.strip.arm("underline")
        self.strip.arm("circle")
        self.assertEqual(armed, ["underline", "circle"])

    def test_disarming_returns_to_the_pointer(self):
        from pdfarranger_qt import tools

        self.strip.arm("polygon")
        self.strip.disarm()
        self.assertEqual(self.strip.armed(), tools.DEFAULT)

    def escape(self):
        """Through the window, because the strip never takes focus."""
        self.win.keyPressEvent(QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))

    def test_escape_disarms(self):
        from pdfarranger_qt import tools

        self.open_strip()
        self.strip.arm("draw")
        self.escape()
        self.assertEqual(self.strip.armed(), tools.DEFAULT)

    def test_escape_disarms_with_the_strip_closed(self):
        """Closing the strip does not clear the mode, so Escape still must.

        Otherwise a tool stays armed with nothing on screen saying so, and
        the way out of it has gone with the panel.
        """
        from pdfarranger_qt import tools

        self.open_strip()
        self.strip.arm("draw")
        self.win.act_markup_tools.setChecked(False)
        settle(timeout_ms=100)
        self.assertFalse(self.strip.isVisible())
        self.assertEqual(self.strip.armed(), "draw")
        self.escape()
        self.assertEqual(self.strip.armed(), tools.DEFAULT)


class TestNothingHappensToTheDocument(StripCase):
    """4.2 builds the surface and no tool acts. 4.3 begins the actions."""

    def test_arming_marks_nothing(self):
        before = len(self.win.model.annotations)
        for name in ("highlight", "draw", "comment", "rectangle"):
            self.strip.arm(name)
            settle(timeout_ms=50)
        self.assertEqual(len(self.win.model.annotations), before)

    def test_arming_does_not_modify_the_document(self):
        self.win.modified = False
        self.strip.arm("highlight")
        self.assertFalse(self.win.modified)


class TestItBelongsToReadMode(StripCase):

    def test_the_toggle_is_offered_while_reading(self):
        self.assertTrue(self.win.read_mode)
        self.assertTrue(self.win.act_markup_tools.isEnabled())

    def test_and_not_while_arranging(self):
        """Arranging is not a mode its tools act in."""
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertFalse(self.win.act_markup_tools.isEnabled())

    def test_the_strip_opens_and_closes_from_the_toggle(self):
        self.open_strip()
        self.assertTrue(self.strip.isVisible())
        self.win.act_markup_tools.setChecked(False)
        settle(timeout_ms=100)
        self.assertFalse(self.strip.isVisible())

    def test_leaving_read_mode_puts_it_away(self):
        """Hidden, but still wanted.

        Checked is the preference and is remembered across sessions, so a
        trip to the grid must not throw it away: the strip goes off screen
        and comes back when reading resumes.
        """
        self.open_strip()
        self.assertTrue(self.strip.isVisible())
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertFalse(self.strip.isVisible())
        self.assertTrue(self.win.act_markup_tools.isChecked())

    def test_and_comes_back_when_reading_resumes(self):
        self.open_strip()
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.win.set_read_mode(True)
        settle(timeout_ms=200)
        self.assertTrue(self.strip.isVisible())

    def test_it_stays_inside_the_reader(self):
        """It is dragged by hand, and a strip dragged off the edge is lost."""
        self.open_strip()
        self.assertGreaterEqual(self.strip.x(), 0)
        self.assertGreaterEqual(self.strip.y(), 0)
        self.assertLessEqual(self.strip.x() + self.strip.width(),
                             self.win.reader.width())


class TestTheMenuIsGone(StripCase):
    """The five-action Markup menu it replaces.

    It was swept into `_editing_actions`, so it was disabled in read mode --
    the only mode its tools act in -- and a flat list could not say which tool
    was armed or hold twenty of them.
    """

    def test_no_markup_menu_remains(self):
        roles = [title for title, _actions in self.win._shortcut_groups()]
        self.assertNotIn("Markup", roles)

    def test_the_toggle_is_not_treated_as_a_document_edit(self):
        """It belongs to View. Swept into the editing actions it would be
        disabled in read mode, which is the bug the menu had."""
        self.assertNotIn(self.win.act_markup_tools,
                         self.win._editing_actions())


class TestTheStripAndTheCanvasAgree(StripCase):
    """What the strip shows and what the pointer does, kept in step.

    Two signals face each other: the strip tells the canvas which tool is
    armed, and the canvas tells the strip when it changes tool by itself,
    which it does when Escape ends a gesture. The canvas cannot tell those
    apart -- an unbuilt tool and a disarm both arrive as SELECT -- so arming
    Arrow used to send the canvas to SELECT and then be told by the canvas to
    go back to the pointer. The tool did not stay picked.
    """

    def canvas(self):
        return self.win.reader.canvas

    def test_a_built_tool_changes_what_the_pointer_does(self):
        self.strip.arm("highlight")
        self.assertEqual(self.canvas().tool(), "highlight")
        self.assertTrue(self.canvas().marking())

    def test_an_unbuilt_tool_stays_armed_and_leaves_the_canvas_reading(self):
        """The mode is set; there is simply nothing behind it yet.

        **Whichever tool is still unbuilt**, found rather than named: the
        one named here was built each time -- Cloud, then Stamps -- and the
        test failed for a tool that now worked. Skipped once all are."""
        from pdfarranger_qt import tools
        from pdfarranger_qt.canvas import PageCanvas

        unbuilt = next((t.name for t in tools.TOOLS
                        if t.family != tools.POINTER
                        and t.name not in self.win.CANVAS_TOOLS), None)
        if unbuilt is None:
            self.skipTest("every tool is built")
        self.strip.arm(unbuilt)
        self.assertEqual(self.strip.armed(), unbuilt)
        self.assertEqual(self.canvas().tool(), PageCanvas.SELECT)

    def test_the_canvas_disarming_itself_moves_the_strip(self):
        """Escape inside a gesture is the canvas's, so the strip cannot be
        the only place the armed tool lives."""
        from pdfarranger_qt import tools
        from pdfarranger_qt.canvas import PageCanvas

        self.strip.arm("highlight")
        self.canvas().set_tool(PageCanvas.SELECT)
        self.assertEqual(self.strip.armed(), tools.DEFAULT)

    def test_escape_puts_an_unbuilt_tool_back_too(self):
        """The case the canvas cannot report: it was never armed, so it has
        no change to announce, and only the window can answer the key."""
        from pdfarranger_qt import tools

        self.strip.arm("cloud")
        self.win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress,
                                         Qt.Key_Escape, Qt.NoModifier))
        self.assertEqual(self.strip.armed(), tools.DEFAULT)

    def test_every_unbuilt_tool_can_be_armed_and_stays(self):
        """All sixteen of them, because the defect was in the fallback that
        every unbuilt tool shares."""
        from pdfarranger_qt import tools

        for tool in tools.TOOLS:
            if tool.name in self.win.CANVAS_TOOLS:
                continue
            with self.subTest(tool=tool.name):
                self.strip.arm(tool.name)
                self.assertEqual(self.strip.armed(), tool.name)


class TestTheFamilyButtonIsOneTarget(StripCase):
    """It began as a split button and that is what made it hard to use.

    The icon re-armed the tool last used from the family and a narrow arrow
    beside it opened the family. Two targets in one 28-pixel button is a
    target you have to aim at: the arrow's edge is invisible, and missing it
    armed a tool instead of showing you the choice.
    """

    def press(self, button, where=None):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        if where is None:
            where = QPointF(button.width() / 2, button.height() / 2)
        button.mousePressEvent(QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, where,
            button.mapToGlobal(QPoint(int(where.x()), int(where.y()))),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=100)

    def setUp(self):
        super().setUp()
        # Shown, so the buttons have geometry of their own. Hidden, every one
        # of them reports the same rectangle and a point maps inside all four
        # -- which is not a thing that can happen on screen, but is exactly
        # how a test of "which button is under this point" lies to itself.
        self.open_strip()

    def tearDown(self):
        self.strip.close_flyouts()
        super().tearDown()

    def test_a_press_anywhere_on_it_opens_the_family(self):
        from PySide6.QtCore import QPointF

        button = self.strip.buttons["drawing"]
        for x, y, corner in ((1, 1, "top left"),
                             (button.width() / 2, button.height() / 2,
                              "middle"),
                             (button.width() - 2, button.height() - 2,
                              "bottom right")):
            with self.subTest(corner=corner):
                self.strip.close_flyouts()
                self.press(button, QPointF(x, y))
                self.assertTrue(button.menu().isVisible())

    def test_it_does_not_offer_a_second_target(self):
        """`MenuButtonPopup` draws a divider, and a divider is a promise that
        the two sides of the button do different things."""
        from PySide6.QtWidgets import QToolButton

        for family, button in self.strip.buttons.items():
            with self.subTest(family=family):
                self.assertEqual(button.popupMode(),
                                 QToolButton.InstantPopup)

    def test_only_one_family_is_open_at_a_time(self):
        first = self.strip.buttons["text markup"]
        second = self.strip.buttons["drawing"]
        self.press(first)
        self.assertTrue(first.menu().isVisible())
        second.open_flyout()
        settle(timeout_ms=100)
        self.assertFalse(first.menu().isVisible())
        self.assertTrue(second.menu().isVisible())

    def test_a_press_on_another_family_reaches_it(self):
        """An open menu grabs the mouse, so without the filter the press that
        lands on the next family down is swallowed to close the menu and the
        second family needs a second click.

        What is asserted is the handover -- the press taken, the open family
        closed, the other one asked to open -- and not that its menu is then
        on screen. Qt will not raise a second popup while the first is still
        tearing down under the offscreen platform the suite runs on, though
        it does on a real one; `test_only_one_family_is_open_at_a_time`
        covers the showing.
        """
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        first = self.strip.buttons["text markup"]
        second = self.strip.buttons["drawing"]
        asked = []
        second.open_flyout = lambda: asked.append(True)
        self.press(first)
        self.assertTrue(first.menu().isVisible())
        middle = QPointF(second.width() / 2, second.height() / 2)
        onto = second.mapToGlobal(QPoint(int(middle.x()), int(middle.y())))
        taken = first.eventFilter(first.menu(), QMouseEvent(
            QEvent.MouseButtonPress, QPointF(onto), QPointF(onto),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=100)
        self.assertTrue(taken, "the menu kept the press")
        self.assertFalse(first.menu().isVisible())
        self.assertEqual(asked, [True],
                         "the other family was never asked to open")

    def test_a_press_on_nothing_in_particular_is_left_alone(self):
        """Only a press over another family is taken. Anywhere else, the
        menu does what a menu does."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        button = self.strip.buttons["drawing"]
        self.press(button)
        far = QPointF(self.win.width() + 500, self.win.height() + 500)
        taken = button.eventFilter(button.menu(), QMouseEvent(
            QEvent.MouseButtonPress, far, far,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertFalse(taken)

    def test_pressing_the_open_family_closes_it(self):
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        button = self.strip.buttons["drawing"]
        self.press(button)
        self.assertTrue(button.menu().isVisible())
        middle = QPointF(button.width() / 2, button.height() / 2)
        onto = button.mapToGlobal(QPoint(int(middle.x()), int(middle.y())))
        taken = button.eventFilter(button.menu(), QMouseEvent(
            QEvent.MouseButtonPress, QPointF(onto), QPointF(onto),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        settle(timeout_ms=100)
        self.assertTrue(taken)
        self.assertFalse(button.menu().isVisible())


if __name__ == "__main__":
    unittest.main()
