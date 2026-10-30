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

"""The current page follows you between the two modes.

The rule, settled with David: switching to read mode reads the selected page,
the first of them if several are selected; switching back scrolls the grid to
the page you were reading and **leaves the selection alone**. Selection means
something when arranging and nothing when reading, so a trip to the reader must
not come back having changed it.
"""

import os
import unittest

from support import HERE, settle

MANY_PAGES = os.path.join(HERE, "exporter", "outlines.pdf")


class TestTheCurrentPageFollows(unittest.TestCase):

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    # -- arrange to read ---------------------------------------------------

    def test_the_reader_opens_at_the_selected_page(self):
        self.win.view.set_selected_rows([2])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 2)

    def test_several_selected_pages_read_from_the_first(self):
        """"Start here" is the only reading of it."""
        self.win.view.set_selected_rows([1, 2, 3])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 1)

    def test_with_nothing_selected_the_reader_resumes(self):
        """The stored position keeps its real job: reopening a document."""
        self.win.view.set_selected_rows([3])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 3)

        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.win.view.set_selected_rows([])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 3,
                         "an empty selection did not fall back to where "
                         "reading left off")

    # -- read to arrange ---------------------------------------------------

    def test_coming_back_does_not_touch_the_selection(self):
        """The whole reason this direction only scrolls."""
        self.win.view.set_selected_rows([0, 1])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.reader.go_to_page(3)
        settle(timeout_ms=300)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertEqual(self.win.view.selected_rows(), [0, 1],
                         "reading stole the selection")

    def test_coming_back_with_no_selection_still_selects_nothing(self):
        self.win.view.set_selected_rows([])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.reader.go_to_page(2)
        settle(timeout_ms=300)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertEqual(self.win.view.selected_rows(), [])

    def test_the_grid_is_scrolled_to_the_page_that_was_read(self):
        """Scrolled, not selected -- so the assertion is about the viewport."""
        from PySide6.QtWidgets import QAbstractItemView
        scrolled = []
        original = self.win.view.scrollTo

        def record(index, hint=QAbstractItemView.EnsureVisible):
            scrolled.append(index.row())
            return original(index, hint)

        self.win.view.set_selected_rows([])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.reader.go_to_page(3)
        settle(timeout_ms=300)
        self.win.view.scrollTo = record
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertIn(3, scrolled, "the grid did not scroll to the page read")

    def test_scroll_to_row_ignores_a_row_that_is_not_there(self):
        self.win.view.scroll_to_row(999)
        self.win.view.scroll_to_row(-1)

    # -- the round trip ----------------------------------------------------

    def test_a_round_trip_keeps_you_on_the_same_page(self):
        self.win.view.set_selected_rows([2])
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 2)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.current_page(), 2)


class TestShiftClickSelectsARange(unittest.TestCase):
    """Shift-click selects page n through page m, and used to not.

    Qt's `ExtendedSelection` on a QListView in **IconMode** selects by
    *rectangle* -- what a box drawn between the two items happens to touch. On
    one column that is indistinguishable from a range, which is why it is not a
    famous problem; on a wrapped grid of pages that are not all the same width
    it is neither the range asked for nor anything predictable, and with the
    delegate placing items itself it frequently selected only the page clicked.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1200, 800)
        self.win.show()
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        # Enough pages that the grid wraps into several rows, which is the
        # case the rectangle got wrong.
        for _ in range(3):
            rows = list(range(len(self.win.model.pages)))
            self.win.view.set_selected_rows(rows)
            self.win.model.duplicate(rows)
            settle(timeout_ms=200)
        self.win.view.set_selected_rows([])
        settle(timeout_ms=300)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def click(self, row, modifiers=None):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        modifiers = Qt.NoModifier if modifiers is None else modifiers
        rect = self.win.view.visualRect(self.win.model.index(row, 0))
        point = QPointF(rect.center())
        viewport = self.win.view.viewport()
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            QApplication.sendEvent(viewport, QMouseEvent(
                kind, point, viewport.mapToGlobal(point.toPoint()),
                Qt.LeftButton, Qt.LeftButton, modifiers))

    def rows(self):
        return self.win.view.selected_rows()

    def test_the_grid_wraps_for_these_tests(self):
        self.assertGreaterEqual(len(self.win.model.pages), 24)

    def test_shift_click_selects_everything_between(self):
        from PySide6.QtCore import Qt
        self.click(2)
        self.click(16, Qt.ShiftModifier)
        self.assertEqual(self.rows(), list(range(2, 17)))

    def test_it_works_backwards(self):
        from PySide6.QtCore import Qt
        self.click(16)
        self.click(2, Qt.ShiftModifier)
        self.assertEqual(self.rows(), list(range(2, 17)))

    def test_a_second_shift_click_re_measures_from_the_same_anchor(self):
        """Shrinking the range must not leave the first one behind."""
        from PySide6.QtCore import Qt
        self.click(2)
        self.click(16, Qt.ShiftModifier)
        self.click(5, Qt.ShiftModifier)
        self.assertEqual(self.rows(), [2, 3, 4, 5])

    def test_a_plain_click_moves_the_anchor(self):
        from PySide6.QtCore import Qt
        self.click(2)
        self.click(16, Qt.ShiftModifier)
        self.click(20)
        self.click(22, Qt.ShiftModifier)
        self.assertEqual(self.rows(), [20, 21, 22])

    def test_ctrl_shift_adds_a_range_to_what_is_selected(self):
        from PySide6.QtCore import Qt
        self.click(1)
        self.click(3, Qt.ShiftModifier)
        self.click(10, Qt.ControlModifier)
        self.click(12, Qt.ShiftModifier | Qt.ControlModifier)
        self.assertEqual(self.rows(), [1, 2, 3, 10, 11, 12])

    def test_shift_clicking_one_page_selects_one_page(self):
        from PySide6.QtCore import Qt
        self.click(7)
        self.click(7, Qt.ShiftModifier)
        self.assertEqual(self.rows(), [7])

    def test_the_view_does_not_jump_back_to_the_anchor(self):
        """set_selected_rows scrolls to the first row; extending must not."""
        from PySide6.QtCore import Qt
        self.click(2)
        before = self.win.view.verticalScrollBar().value()
        self.win.view.verticalScrollBar().setValue(
            self.win.view.verticalScrollBar().maximum())
        settle(timeout_ms=200)
        moved = self.win.view.verticalScrollBar().value()
        self.assertNotEqual(moved, before, "the grid does not scroll; test is moot")
        last = self.win.model.rowCount() - 1
        self.click(last, Qt.ShiftModifier)
        self.assertEqual(self.win.view.verticalScrollBar().value(), moved,
                         "extending scrolled the view back to the anchor")

    def test_the_release_does_not_undo_the_range(self):
        """The half that made this intermittent for David.

        Qt redoes the selection on *release*, measuring from the position it
        recorded at the last press it saw. Our press handler returns before Qt
        sees it, so that position is still the plain click that set the anchor
        -- and Qt would draw its rectangle between exactly the two pages we had
        just selected properly. Whether it fires depends on where the release
        lands, which is why it worked sometimes and not others.

        Asserted as "the release changes nothing", which is the requirement.
        The offscreen platform may not reproduce the overwrite, so this guards
        the rule rather than the platform.
        """
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self.click(2)
        rect = self.win.view.visualRect(self.win.model.index(16, 0))
        point = QPointF(rect.center())
        viewport = self.win.view.viewport()
        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseButtonPress, point, viewport.mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier))
        after_press = self.rows()
        self.assertEqual(after_press, list(range(2, 17)))

        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseButtonRelease, point, viewport.mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier))
        self.assertEqual(self.rows(), after_press,
                         "releasing the button changed the selection")

    def test_a_shift_click_with_a_twitch_does_not_start_a_drag(self):
        """The press is a selection gesture, so it must not arm the reorder."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self.click(2)
        rect = self.win.view.visualRect(self.win.model.index(9, 0))
        point = QPointF(rect.center())
        viewport = self.win.view.viewport()
        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseButtonPress, point, viewport.mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier))
        moved = QPointF(point.x() + 40, point.y() + 40)
        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseMove, moved, viewport.mapToGlobal(moved.toPoint()),
            Qt.NoButton, Qt.LeftButton, Qt.ShiftModifier))
        self.assertFalse(self.win.view._dragging, "a shift-click began a drag")
        self.assertEqual(self.rows(), list(range(2, 10)))

    def test_extending_with_no_anchor_selects_the_clicked_page(self):
        from PySide6.QtCore import Qt
        self.win.view._anchor_row = -1
        self.click(4, Qt.ShiftModifier)
        self.assertEqual(self.rows(), [4])


class TestOpeningDoesNotSelectEverything(unittest.TestCase):
    """Inserting pages selects them; opening a document should not.

    "Select what just arrived" is right for Import and Paste -- it shows you
    where the pages landed in a long document and lets you act on them. On an
    open every page is new, so selecting every page points out nothing. It also
    had a consequence once a selection began telling the reader where to open:
    a document that arrived fully selected could never resume where it was
    last read.
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

    def test_opening_selects_nothing(self):
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        self.assertEqual(self.win.view.selected_rows(), [])

    def test_importing_still_selects_what_arrived(self):
        """The behaviour that rule exists for, kept."""
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        first = len(self.win.model.pages)
        self.win._load_paths([MANY_PAGES])
        settle(timeout_ms=400)
        self.assertEqual(self.win.view.selected_rows(),
                         list(range(first, len(self.win.model.pages))))


class TestTheStatusBarSaysWhereYouAre(unittest.TestCase):
    """Read mode shows "Page n of m", and keeps showing it.

    It used to be a `showMessage(..., 3000)` emitted only when the page
    *changed*: nothing at all until you scrolled, and nothing again three
    seconds later. The comment on the mode label two lines above it in
    `_build_statusbar` says exactly why that is the wrong mechanism.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        # These assert absolute page numbers, and the reading position is
        # stored per document *path* -- so an earlier test in this file that
        # read the same fixture would otherwise decide where this one starts.
        #
        # Cleared *before* the document is opened, not after. Opening ends in
        # read mode, which is where a stored position is applied, so clearing
        # it afterwards is too late: it only looked sufficient while the
        # position was written on a mode switch and never on close, which left
        # nothing behind for a window that was simply closed.
        self.win.current_path = os.path.abspath(MANY_PAGES)
        key = self.win._reading_key()
        if key:
            self.win.settings.remove(key)
        self.win.current_path = None

        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=400)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def text(self):
        return self.win.status_pages.text()

    def test_it_says_the_page_on_entering_read_mode(self):
        """Without scrolling first, which is what used to be required."""
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.text(), "Page 1 of 4")

    def test_it_follows_the_page(self):
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.reader.go_to_page(2)
        settle(timeout_ms=300)
        self.assertEqual(self.text(), "Page 3 of 4")

    def test_it_survives_a_trip_to_arrange_mode_and_back(self):
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.reader.go_to_page(2)
        settle(timeout_ms=300)
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertEqual(self.text(), "4 pages")
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.text(), "Page 3 of 4")

    def test_arrange_mode_counts_the_document(self):
        self.win.set_read_mode(False)
        settle(timeout_ms=200)
        self.assertEqual(self.text(), "4 pages")

    def test_it_is_permanent_not_a_timed_message(self):
        """A transient message is what made this come and go."""
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.statusBar().currentMessage(), "",
                         "the page position is a timed message again")
        self.assertIn("Page", self.text())

    def test_an_empty_window_says_so(self):
        self.win.close_document()
        settle(timeout_ms=300)
        self.assertEqual(self.text(), "No document")


FORMS = os.path.join(HERE, "exporter", "forms.pdf")


class TestFillingAFieldLeavesTheReaderAlone(unittest.TestCase):
    """Filling a field used to rebuild the reader's whole document.

    `model.touch` is what the grid needs -- its thumbnails are drawn from a
    rewritten copy with the old value baked in -- but it also emits
    `contents_changed`, which the reader rebuilt on. The canvas composites
    fields from the values the window holds rather than from the file, so the
    reader never needed one: the rebuild bought nothing and cost the 682 ms a
    rewrite takes on a large form.

    It also lost the reader's place. A fresh document is laid out from
    `provisional_sizes` until the measuring pass catches up, that layout is
    shorter than the real one, and the scrollbar is clamped into it -- from
    500 of 933 to 0 of 739, measured, and the range came back while the
    position did not.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([FORMS])
        settle(timeout_ms=600)
        self.win.set_read_mode(True)
        settle(timeout_ms=900)
        self.rebuilds = 0
        self._real_load = self.win._load_reader
        self.win._load_reader = self._counted

    def _counted(self, *args, **kwargs):
        self.rebuilds += 1
        return self._real_load(*args, **kwargs)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def scrolled_down(self):
        bar = self.win.reader.canvas.verticalScrollBar()
        bar.setValue(max(1, bar.maximum() // 2))
        settle(timeout_ms=300)
        return self.win.reader.canvas.position()

    def a_field(self, kind):
        fields = self.win.reader.canvas.fields()
        self.assertIsNotNone(fields, "the fixture has no form")
        found = [f for f in fields.on_page(0) if f.kind == kind]
        self.assertTrue(found, f"the fixture has no {kind} field")
        return found[0]

    def test_ticking_a_box_does_not_rebuild_the_document(self):
        self.win.field_pressed(self.a_field("/Btn"))
        settle(timeout_ms=600)
        self.assertEqual(self.rebuilds, 0)

    def test_typing_in_a_field_does_not_rebuild_the_document(self):
        self.win.field_edited(self.a_field("/Tx"), "something typed")
        settle(timeout_ms=600)
        self.assertEqual(self.rebuilds, 0)

    def test_the_reader_stays_where_it_was(self):
        before = self.scrolled_down()
        self.win.field_pressed(self.a_field("/Btn"))
        settle(timeout_ms=600)
        after = self.win.reader.canvas.position()
        self.assertEqual(after[0], before[0])
        self.assertAlmostEqual(after[1], before[1], delta=1.0)

    def test_the_new_value_is_what_the_canvas_draws(self):
        """Not rebuilding is only safe because the value never came from the
        document in the first place."""
        field = self.a_field("/Btn")
        canvas = self.win.reader.canvas
        before = canvas.field_values(field)
        self.win.field_pressed(field)
        settle(timeout_ms=600)
        self.assertNotEqual(canvas.field_values(field), before)

    def test_the_snapshot_is_marked_stale_all_the_same(self):
        """Left showing, not left pretending it is current: the next entry
        into read mode rebuilds it."""
        self.win.field_pressed(self.a_field("/Btn"))
        settle(timeout_ms=600)
        self.assertTrue(self.win._reader_stale)

    def test_an_edit_to_the_pages_still_rebuilds(self):
        """The suppression is for field values alone. A real page edit has to
        go through, or the reader would disagree with the document."""
        self.win.model.rotate([0], 90)
        settle(timeout_ms=900)
        self.assertEqual(self.rebuilds, 1)


class TestARebuildKeepsThePlace(unittest.TestCase):
    """And when a rebuild is genuine, it should still not move the reader."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([MANY_PAGES])
        settle(timeout_ms=600)
        self.win.set_read_mode(True)
        settle(timeout_ms=900)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_rotating_one_page_does_not_move_the_reader_off_another(self):
        """Rotating page one makes the widest page landscape, so fit-width
        drops the zoom and every page shrinks -- the scrollbar range moves
        under the reader even though the page being read did not change.
        Measured on a 14 page form: 6055 of 9600 became 4592 of 7217, the
        same 230 points into the same page.
        """
        canvas = self.win.reader.canvas
        canvas.go_to_page(2)
        settle(timeout_ms=400)
        bar = canvas.verticalScrollBar()
        bar.setValue(bar.value() + 120)
        settle(timeout_ms=400)
        before = canvas.position()

        self.win.model.rotate([0], 90)
        settle(timeout_ms=1200)

        after = canvas.position()
        self.assertEqual(after[0], before[0])
        self.assertAlmostEqual(after[1], before[1], delta=2.0)

    def test_the_position_survives_the_provisional_layout(self):
        """The restore runs before the pages have been measured, so it lands
        on a guess; the measuring pass has to carry it rather than re-anchor
        on whichever page the guess left under the viewport."""
        canvas = self.win.reader.canvas
        canvas.go_to_page(3)
        settle(timeout_ms=400)
        before = canvas.position()
        self.win.model.rotate([0], 90)
        settle(timeout_ms=1200)
        self.assertEqual(canvas.position()[0], before[0])
