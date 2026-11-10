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

"""The pop-up note: the window it is read in, and what it writes.

A note is the mark's own `/Contents`, not an annotation of its own -- but a
*reply* is an annotation, pointing at what it answers with `/IRT`, and so is
each change of status. So a thread is one mark and a handful of others that
name it, which is why the panel is a list rather than a text box.
"""

import io
import os
import re
import unittest
from html import unescape

import pikepdf
from support import FIXTURES, settle

from pdfarranger_qt import markup
from pdfarranger_qt.notepanel import when_text

RUN = os.path.join(FIXTURES, "markup_highlight.pdf")


class TestWhenAThreadSaysItHappened(unittest.TestCase):
    """`when_text`: a clock for today, a date for anything older.

    Reader's two forms, read off a thread whose note said `10:13 PM` and
    whose reply from the day before said `Nov 1`.
    """

    def setUp(self):
        import datetime

        self.now = datetime.datetime(2026, 11, 2, 23, 0)

    def test_today_is_a_clock(self):
        """The locale decides how a clock reads -- `10:13 PM` here, `22:13`
        elsewhere -- so what is checked is that it is the time and not the
        date."""
        said = when_text("D:20261102221300-07'00'", now=self.now)
        self.assertIn(":", said)
        self.assertIn("13", said)

    def test_before_today_is_a_date(self):
        """A month and a day, in the reader's own language: `Nov 1` in
        English and something else elsewhere, which is why the month is not
        one of our strings."""
        said = when_text("D:20261101204500-07'00'", now=self.now)
        self.assertTrue(said.endswith("1"), said)
        self.assertNotIn(":", said)

    def test_midnight_and_noon_are_told_apart(self):
        """Whatever the locale's clock looks like, the two are not the same
        string -- which a twelve-hour clock with no AM or PM would make
        them."""
        self.assertNotEqual(when_text("D:20261102000500", now=self.now),
                            when_text("D:20261102120500", now=self.now))

    def test_nothing_readable_says_nothing(self):
        for raw in (None, "", "D:2026", "rubbish"):
            with self.subTest(raw=raw):
                self.assertEqual(when_text(raw, now=self.now), "")

    def test_the_zone_is_ignored_rather_than_applied(self):
        """A note written at 22:13 reads as 22:13 wherever it is opened.
        Shifting it into the reader's own zone would rename the moment."""
        said = [when_text("D:20261102221300" + zone, now=self.now)
                for zone in ("-07'00'", "+05'30'", "Z", "")]
        self.assertEqual(len(set(said)), 1, said)


class TestEveryMarkGetsAWindow(unittest.TestCase):
    """`/Popup`: the object a viewer opens to show a mark's note.

    **Written whether or not there is a note.** It holds no text and draws
    nothing; Reader gives one to every mark it makes, and the proof is a
    highlight in the corpus that has never been commented and carries one.
    """

    def page_with(self, annotation):
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        markup.add_to_page(pdf, pdf.pages[0], [annotation])
        return pdf

    def a_highlight(self, **fields):
        return markup.Annotation(
            markup.HIGHLIGHT, 0, (36.0, 600.0, 400.0, 640.0),
            quads=((36.0, 600.0, 400.0, 640.0),), **fields)

    @staticmethod
    def popups(pdf):
        return [a for a in pdf.pages[0].obj.get("/Annots") or []
                if str(a.get("/Subtype")) == "/Popup"]

    def test_an_uncommented_mark_still_gets_one(self):
        pdf = self.page_with(self.a_highlight())
        self.assertEqual(len(self.popups(pdf)), 1)

    def test_it_is_placed_the_way_reader_places_one(self):
        """Measured on 44 of Reader's own: 184 by 92, its left edge at the
        page width -- parked off the paper -- and its top at the parent's."""
        pdf = self.page_with(self.a_highlight())
        rect = [float(v) for v in self.popups(pdf)[0].get("/Rect")]
        self.assertEqual(rect, [612.0, 640.0 - 92.0, 612.0 + 184.0, 640.0])

    def test_nothing_is_clamped(self):
        """Reader writes a negative bottom for a mark low on the page rather
        than pushing the window up, so neither does this."""
        low = markup.Annotation(markup.HIGHLIGHT, 0, (36.0, 10.0, 400.0, 40.0),
                                quads=((36.0, 10.0, 400.0, 40.0),))
        pdf = self.page_with(low)
        rect = [float(v) for v in self.popups(pdf)[0]["/Rect"]]
        self.assertLess(rect[1], 0)

    def test_the_two_point_at_each_other(self):
        pdf = self.page_with(self.a_highlight())
        popup = self.popups(pdf)[0]
        mark = [a for a in pdf.pages[0].obj["/Annots"]
                if str(a.get("/Subtype")) == "/Highlight"][0]
        self.assertEqual(str(popup["/Parent"]["/NM"]), str(mark["/NM"]))
        self.assertEqual(str(mark["/Popup"]["/Subtype"]), "/Popup")

    def test_it_carries_the_keys_reader_writes_and_no_others(self):
        pdf = self.page_with(self.a_highlight())
        self.assertEqual(
            sorted(str(k) for k in self.popups(pdf)[0].keys()),
            ["/F", "/Open", "/Parent", "/Rect", "/Subtype", "/Type"])

    def test_a_window_somebody_moved_is_written_where_they_left_it(self):
        placed = (57.0, 556.0, 223.0, 687.0)
        pdf = self.page_with(self.a_highlight(popup_rect=placed))
        rect = tuple(float(v) for v in self.popups(pdf)[0]["/Rect"])
        self.assertEqual(rect, placed)


class TestAReplyIsAMarkOfItsOwn(unittest.TestCase):
    """What makes a reply a reply is `/IRT`, and nothing else."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(RUN)
        with pikepdf.open(RUN) as pdf:
            self.mark = [m for m in markup.marks_in(pdf) if m.page == 1][0]

    def written(self, reply):
        from pdfarranger_qt.export import export

        marks = markup.Annotations()
        marks.add(reply)
        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               annotations=marks)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    def a_reply(self, **fields):
        left, top = self.mark.rect[0], self.mark.rect[3]
        return markup.Annotation(
            markup.TEXT, self.pages[0].uid,
            markup.note_rect(left, top, markup.NOTE_SIZE),
            contents="An answer", colour=self.mark.colour,
            author="tester", irt=self.mark.name, **fields)

    def test_it_points_at_what_it_answers(self):
        with self.written(self.a_reply()) as got:
            ours = [a for a in got.pages[0].obj["/Annots"]
                    if str(a.get("/T", "")) == "tester"]
            self.assertEqual(len(ours), 1)
            self.assertEqual(str(ours[0]["/IRT"]["/NM"]), self.mark.name)

    def test_it_is_anchored_rather_than_merely_printable(self):
        """`/F 28` -- Print, NoZoom, NoRotate -- as Reader writes a reply,
        whose icon belongs to the mark rather than to the paper."""
        with self.written(self.a_reply()) as got:
            ours = [a for a in got.pages[0].obj["/Annots"]
                    if str(a.get("/T", "")) == "tester"][0]
            self.assertEqual(int(ours["/F"]), markup.ANCHORED)

    def test_it_reads_back_as_a_reply_and_not_as_a_status(self):
        with self.written(self.a_reply()) as got:
            ours = [m for m in markup.marks_in(got)
                    if m.author == "tester"][0]
            self.assertTrue(ours.is_reply())
            self.assertFalse(ours.is_status())

    def test_the_thread_it_joins_is_left_alone(self):
        """A reply is added to the file, and nothing already in it moves."""
        with pikepdf.open(RUN) as before:
            was = [(m.subtype, m.contents, m.state)
                   for m in markup.marks_in(before) if m.page == 1]
        with self.written(self.a_reply()) as got:
            now = [(m.subtype, m.contents, m.state)
                   for m in markup.marks_in(got) if m.page == 1]
        self.assertEqual(now[:len(was)], was)
        self.assertEqual(len(now), len(was) + 1)


class TestEditingWhatAThreadSays(unittest.TestCase):
    """A note is the mark's `/Contents`; a reply has `/Contents` of its own.
    Both are the same change to a different mark."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(RUN)
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]

    def saved(self, **by_index):
        from pdfarranger_qt.export import export

        edits = markup.MarkEdits()
        for index, fields in by_index.items():
            edits.change(self.pages[0].uid, int(index), **fields)
        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               mark_edits=edits)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    def test_a_note_is_written_on_the_mark_itself(self):
        mark = self.marks[0]
        with self.saved(**{str(mark.index): {"contents": "Rewritten"}}) as got:
            back = [m for m in markup.marks_in(got) if m.page == 1][0]
            self.assertEqual(back.contents, "Rewritten")

    def test_a_reply_is_edited_like_any_other_mark(self):
        reply = [m for m in self.marks if m.is_reply()][0]
        with self.saved(**{str(reply.index): {"contents": "Answered"}}) as got:
            back = [m for m in markup.marks_in(got)
                    if m.page == 1 and m.is_reply()]
            self.assertIn("Answered", [m.contents for m in back])

    def test_editing_one_leaves_the_status_chain_alone(self):
        mark = self.marks[0]
        was = [(m.state, m.contents) for m in self.marks if m.is_status()]
        with self.saved(**{str(mark.index): {"contents": "Rewritten"}}) as got:
            now = [(m.state, m.contents) for m in markup.marks_in(got)
                   if m.page == 1 and m.is_status()]
        self.assertEqual(now, was)

    def test_an_emptied_note_removes_the_key_rather_than_blanking_it(self):
        """A reader that lists comments lists an empty `/Contents` as one."""
        mark = self.marks[0]
        with self.saved(**{str(mark.index): {"contents": ""}}) as got:
            annots = [a for a in got.pages[0].obj["/Annots"]
                      if str(a.get("/Subtype")) == "/Highlight"]
            self.assertNotIn("/Contents", annots[0].keys())

    def test_a_moved_window_is_written_to_the_popup(self):
        """And nothing else about the window is touched -- whether it was
        left open is the file's to say, not a move's."""
        mark = self.marks[0]
        where = (77.0, 508.0, 313.0, 700.0)
        with self.saved(**{str(mark.index): {"popup": where}}) as got:
            back = [m for m in markup.marks_in(got) if m.page == 1][0]
            self.assertEqual(tuple(round(v, 3) for v in back.popup_rect),
                             where)
            self.assertEqual(back.popup_open, mark.popup_open,
                             "moving the window changed whether it is open")


class TestThePanelItself(unittest.TestCase):
    """The window, with no document behind it."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.notepanel import Item, NotePanel

        self.Item = Item
        self.panel = NotePanel()
        self.thread = [
            Item("dws", "10:13 PM", "Highlight Note", "Completed"),
            Item("dws", "Nov 1", "And this is a reply."),
            Item("dws", "10:27 PM", "This is another reply."),
        ]

    def tearDown(self):
        self.panel.deleteLater()

    def test_it_opens_on_the_note_however_many_replies(self):
        """Reader's behaviour, and not a chat window's."""
        self.panel.show_thread(self.thread)
        self.assertEqual(self.panel.selected(), 0)

    def test_an_empty_editor_cannot_be_posted(self):
        """Which is how a note cannot be emptied: there is no way to post
        nothing."""
        self.panel.show_thread(self.thread)
        self.panel._editor.setPlainText("   ")
        self.assertFalse(self.panel._post.isEnabled())
        self.panel._editor.setPlainText("something")
        self.assertTrue(self.panel._post.isEnabled())

    def test_replying_adds_an_empty_item_and_opens_it(self):
        self.panel.show_thread(self.thread)
        which = self.panel.add_blank("dws", "10:40 PM")
        self.assertEqual(which, len(self.thread))
        self.assertEqual(self.panel.selected(), which)
        self.assertEqual(self.panel.text_of(which), "")
        self.assertFalse(self.panel._post.isEnabled())

    def test_an_abandoned_reply_is_dropped(self):
        self.panel.show_thread(self.thread)
        self.panel.add_blank("dws", "10:40 PM")
        self.panel._cancel()
        self.assertEqual(len(self.panel.items()), len(self.thread))

    def test_it_grows_with_the_thread(self):
        self.panel.show_thread(self.thread[:1])
        short = self.panel.height()
        self.panel.show_thread(self.thread)
        self.assertGreater(self.panel.height(), short)

    def test_it_paints_its_own_background(self):
        """A plain `QWidget` subclass gets its stylesheet parsed and never
        painted, which left this window completely transparent -- the page
        reading through it and the replies colliding with the text.

        **Rendered over something, not on its own.** Rendering the panel by
        itself fills the background whether or not it paints one, so that
        version of this test passed with the painting removed -- it was
        measuring the harness. With a parent drawing behind it, as the
        canvas does, 6141 sampled pixels of that parent showed through.
        """
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtWidgets import QWidget

        class Page(QWidget):
            def paintEvent(self, event):
                QPainter(self).fillRect(self.rect(), QColor(255, 0, 0))

        page = Page()
        page.resize(600, 600)
        page.show()
        self.addCleanup(page.deleteLater)
        panel = type(self.panel)(page)
        panel.show_thread(self.thread)
        panel.move(20, 20)
        image = QImage(page.size(), QImage.Format_ARGB32)
        image.fill(0)
        page.render(image)
        area = panel.geometry()
        showing = sum(
            1 for y in range(area.top() + 6, area.bottom() - 6, 3)
            for x in range(area.left() + 6, area.right() - 6, 3)
            if QColor(image.pixel(x, y)) == QColor(255, 0, 0))
        self.assertEqual(showing, 0, "the page shows through the window")

    def test_being_put_where_the_file_says_is_not_a_move(self):
        """Opening a note to read it must never be a change to the
        document; only moving the window is."""
        from PySide6.QtCore import QRect

        moves = []
        self.panel.placed.connect(moves.append)
        self.panel.show_thread(self.thread)
        self.panel.resize_to(QRect(40, 50, 240, 200))
        self.assertEqual(moves, [])

    def test_a_resize_by_hand_is_a_move(self):
        from PySide6.QtCore import QRect

        self.panel.show_thread(self.thread)
        self.panel.resize_to(QRect(40, 50, 240, 200))
        moves = []
        self.panel.placed.connect(moves.append)
        self.panel.resize(260, 220)
        self.assertTrue(moves, "a resize went unrecorded")

    def over_a_view(self):
        """A panel floating over something, which is how it is used.

        **Not the parentless one `setUp` makes.** A top-level window is
        held to its own minimum size hint by Qt itself, so every test of
        what stops this one being squashed passed on a parentless panel
        whether or not the panel did anything -- it was measuring Qt.
        Over a parent, as it is over the canvas, nothing holds it but what
        it does here.
        """
        from PySide6.QtWidgets import QWidget

        view = QWidget()
        view.resize(500, 420)
        view.show()
        self.addCleanup(view.deleteLater)
        panel = type(self.panel)(view)
        panel.show_thread(self.thread)
        return view, panel

    def test_a_window_the_file_sized_small_is_grown_to_what_it_holds(self):
        """Reader sized its window for Reader's text in Reader's fonts.

        Taken as the size rather than as a floor, it squashed the thread:
        Qt shrinks whatever will shrink, so the header rows and the editor
        went into their own margins -- a note and two replies in a window
        the file left 131 points tall came out as five clipped lines, with
        the editor 28 pixels high and the text box inside it hanging out
        the bottom.
        """
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QFrame

        _view, panel = self.over_a_view()
        panel.resize_to(QRect(20, 20, 240, 80))
        box = next(w for w in panel.findChildren(QFrame)
                   if w.property("role") == "editor")
        self.assertGreaterEqual(box.height(), panel._editor.height(),
                                "the editor is shorter than the text box in it")

    def test_the_grip_cannot_squash_the_thread_either(self):
        """The same floor, from the other direction. A minimum *width* on
        its own is enough to stop Qt applying the layout's own minimum, so
        for a while nothing held either."""
        from PySide6.QtCore import QRect

        _view, panel = self.over_a_view()
        panel.resize_to(QRect(20, 20, 240, 400))
        panel.resize(200, 60)
        self.assertGreaterEqual(panel.height(), panel.room_for(200).height())

    def test_a_window_hanging_over_the_edge_is_pulled_back(self):
        """**It is dragged by its own header.** A window the file left over
        the top of the view took that header with it, so there was no way
        to move it back -- which is the half of the file's geometry that
        cannot be honoured."""
        from PySide6.QtCore import QRect

        view, panel = self.over_a_view()
        panel.resize_to(QRect(57, -60, 291, 230))
        self.assertTrue(view.rect().contains(panel.geometry()),
                        "the window is out of reach at %s" % (panel.geometry(),))

    def test_an_item_the_file_styled_is_drawn_styled(self):
        """`/RC` is what Reader draws. Shown as plain text, the underlined
        reply in the corpus arrived as ordinary words."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        said = self.Item("dws", "Nov 1", "bold here",
                         None, 'bold <span style="font-weight:bold">here'
                         "</span>")
        self.panel.show_thread([self.thread[0], said])
        labels = [lab for lab in self.panel.findChildren(QLabel)
                  if lab.property("role") == "said"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0].textFormat(), Qt.TextFormat.RichText)
        self.assertIn("font-weight:bold", labels[0].text())

    def test_the_editor_reports_what_it_holds_as_runs(self):
        """What `/RC` is written from. The style names only what is set, so
        a run with nothing on it is what says a note has no styling."""
        from PySide6.QtGui import QTextCursor

        self.panel.show_thread(self.thread)
        editor = self.panel._editor
        editor.setPlainText("plain and bold")
        cursor = editor.textCursor()
        cursor.setPosition(10)
        cursor.setPosition(14, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.restyle("bold")
        self.assertEqual(editor.runs(),
                         [[("plain and ", {}),
                           ("bold", {"font-weight": "bold"})]])

    def test_a_style_set_twice_is_a_style_taken_off(self):
        self.panel.show_thread(self.thread)
        editor = self.panel._editor
        editor.selectAll()
        editor.restyle("underline")
        self.assertEqual(editor.runs()[0][0][1],
                         {"text-decoration": "underline"})
        editor.selectAll()
        editor.restyle("underline")
        self.assertEqual(editor.runs()[0][0][1], {})

    def test_an_item_that_arrived_styled_is_edited_styled(self):
        """A plain editor would flatten it the first time anybody posted an
        edit to it."""
        said = self.Item("dws", "Nov 1", "bold here", None,
                         'bold <span style="font-weight:bold">here</span>')
        self.panel.show_thread([said])
        self.assertEqual(self.panel._editor.runs(),
                         [[("bold ", {}), ("here", {"font-weight": "bold"})]])

    def test_posting_closes_the_editor(self):
        """**The feedback that it was kept.** Pressing Post otherwise left
        the same words in the same open box, and there was no telling a
        posted reply from one still being typed."""
        self.panel.show_thread(self.thread)
        self.panel._editor.setPlainText("Said and meant")
        self.panel._post_it()
        settle(timeout_ms=200)
        self.assertIsNone(self.panel._editor)
        self.assertEqual(self.panel.selected(), self.panel.NOTHING)

    def test_what_was_styled_stays_styled_after_posting(self):
        """A posted item used to be redrawn from the rich text it *arrived*
        with -- which for a note that arrived plain is none, so styling a
        note and pressing Post put the words back to plain."""
        from PySide6.QtGui import QTextCursor

        self.panel.show_thread(self.thread)
        editor = self.panel._editor
        editor.setPlainText("Highlight Note")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.restyle("bold")
        self.panel._post_it()
        settle(timeout_ms=200)
        self.assertIn("font-weight:bold", self.panel.items()[0].rich or "")

    def test_an_item_can_be_opened_again_after_posting(self):
        self.panel.show_thread(self.thread)
        self.panel._post_it()
        settle(timeout_ms=200)
        self.panel.select(1)
        self.assertIsNotNone(self.panel._editor)
        self.assertEqual(self.panel.text_of(1), self.thread[1].text)

    def test_an_author_line_opens_its_own_item(self):
        """The line and the words under it are the same item -- and after a
        post nothing is open at all, so the line is how it is reached."""
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QLabel

        _view, panel = self.over_a_view()
        panel._post_it()
        settle(timeout_ms=200)
        self.assertEqual(panel.selected(), panel.NOTHING)
        line = [lab for lab in panel.findChildren(QLabel)
                if lab.property("role") == "author"][2].parentWidget()
        for kind, held in ((QEvent.Type.MouseButtonPress, Qt.LeftButton),
                           (QEvent.Type.MouseButtonRelease, Qt.NoButton)):
            QApplication.sendEvent(line, QMouseEvent(
                kind, QPointF(4, 4), QPointF(line.mapToGlobal(QPoint(4, 4))),
                Qt.LeftButton, held, Qt.NoModifier))
        settle(timeout_ms=250)
        self.assertEqual(panel.selected(), 2)

    def test_a_click_on_the_header_is_not_a_move(self):
        """It would write a `/Popup /Rect` identical to the old one and
        mark the document dirty for nothing."""
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        _view, panel = self.over_a_view()
        moves = []
        panel.placed.connect(moves.append)
        for kind, held in ((QEvent.Type.MouseButtonPress, Qt.LeftButton),
                           (QEvent.Type.MouseButtonRelease, Qt.NoButton)):
            QApplication.sendEvent(panel.childAt(QPoint(20, 14)), QMouseEvent(
                kind, QPointF(4, 4), QPointF(panel.mapToGlobal(QPoint(20, 14))),
                Qt.LeftButton, held, Qt.NoModifier))
        settle(timeout_ms=250)
        self.assertEqual(moves, [])

    def test_a_redraw_keeps_the_item_that_is_open(self):
        """Opening a thread opens the note, whatever is under it. Redrawing
        one that is already showing must not move the editor out from under
        whoever is using it."""
        self.panel.show_thread(self.thread)
        self.panel.select(2)
        self.panel.show_thread(self.thread, self.panel.selected())
        self.assertEqual(self.panel.selected(), 2)
        self.panel.show_thread(self.thread, self.panel.NOTHING)
        self.assertEqual(self.panel.selected(), self.panel.NOTHING)
        self.assertIsNone(self.panel._editor)

    def test_a_menu_knows_which_item_it_was_asked_over(self):
        """What makes the window's menus per item: a reply's line offers
        Delete, and the first item's gives the mark's menu entire."""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QLabel

        _view, panel = self.over_a_view()
        seen = []
        panel.menu_wanted.connect(lambda which, _at: seen.append(which))
        said = [lab for lab in panel.findChildren(QLabel)
                if lab.property("role") == "said"]
        self.assertEqual(panel._item_at(QPoint(20, 14)), 0)
        self.assertEqual(
            panel._item_at(said[0].mapTo(panel, QPoint(2, 2))), 1)
        self.assertEqual(
            panel._item_at(QPoint(panel.width() // 2, panel.height() - 20)),
            panel.NOTHING)

    def test_a_window_narrower_than_the_default_is_honoured(self):
        """One sized in Reader is often narrower -- the corpus has a 166
        point window -- and clamping it to our own width would throw away
        the geometry the file went to the trouble of recording."""
        from PySide6.QtCore import QRect

        self.panel.show_thread(self.thread)
        self.panel.resize_to(QRect(10, 10, 178, 160))
        self.assertEqual(self.panel.width(), 178)


class TestSettingAStatus(unittest.TestCase):
    """A status is a history, not a field.

    Each change is an annotation carrying `/State` and `/StateModel
    /Review`, whose `/IRT` points at *the link before it*. So the current
    status is the last link and the rest are how it got there -- which is
    what lets Review History show the sequence, and why setting one never
    overwrites another.
    """

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(RUN)
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]
        self.mark = self.marks[0]
        #: The *mark's own* history, walked as the application walks it.
        #: Not every status on the page: a reply carries a chain of its
        #: own, so the last status in the file is somebody else's link and
        #: a new one pointed at it joins the wrong history.
        self.chain = [m for m in markup.MarkMap(self.marks).children(self.mark)
                      if m.is_status()]

    def written(self, state, answering=None):
        from pdfarranger_qt.export import export

        ours = markup.Annotations()
        ours.add(markup.Annotation(
            markup.TEXT, self.pages[0].uid,
            markup.note_rect(self.mark.rect[0], self.mark.rect[3],
                             markup.NOTE_SIZE),
            contents="%s set by tester" % state, author="tester",
            colour=self.mark.colour,
            irt=answering or self.chain[-1].name, state=state))
        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               annotations=ours)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    def ours_in(self, pdf):
        return [a for a in pdf.pages[0].obj["/Annots"]
                if str(a.get("/T", "")) == "tester"][0]

    def test_it_says_which_vocabulary_the_state_belongs_to(self):
        with self.written("Rejected") as got:
            entry = self.ours_in(got)
            self.assertEqual(str(entry["/State"]), "Rejected")
            self.assertEqual(str(entry["/StateModel"]), "Review")

    def test_it_is_hidden_because_it_draws_nothing(self):
        with self.written("Rejected") as got:
            self.assertEqual(int(self.ours_in(got)["/F"]), markup.UNSEEN)

    def test_it_answers_the_link_before_it_and_not_the_mark(self):
        """Pointing a new status at the mark would start a second history
        beside the first rather than continuing it."""
        with self.written("Rejected") as got:
            answered = self.ours_in(got)["/IRT"]
            self.assertEqual(str(answered["/State"]), self.chain[-1].state)
            self.assertNotEqual(str(answered["/NM"]), self.mark.name)

    def test_the_last_link_is_the_one_a_reader_reports(self):
        with self.written("Rejected") as got:
            found = markup.MarkMap(markup.marks_in(got))
            mark = [m for m in found.for_page(1)
                    if m.subtype == "/Highlight"][0]
            _replies, state = found.thread(mark)
            self.assertEqual(str(state), "Rejected")

    def test_the_history_it_joins_is_kept_whole(self):
        was = [m.state for m in self.chain]
        with self.written("Rejected") as got:
            found = markup.MarkMap(markup.marks_in(got))
            mark = [m for m in found.for_page(1)
                    if m.subtype == "/Highlight"][0]
            now = [m.state for m in found.children(mark) if m.is_status()]
        self.assertEqual(now, was + ["Rejected"])

    def test_the_replies_are_not_disturbed(self):
        was = len([m for m in self.marks if m.is_reply()])
        with self.written("Rejected") as got:
            now = len([m for m in markup.marks_in(got)
                       if m.page == 1 and m.is_reply()])
        self.assertEqual(now, was)

    def test_the_five_are_reader_s_and_are_written_untranslated(self):
        """`/State` holds these keywords and a reader matches them, so a
        translated one is a status no other application understands."""
        self.assertEqual(markup.STATUSES,
                         ("None", "Accepted", "Cancelled", "Completed",
                          "Rejected"))


class TestTheRichVersionOfWhatANoteSays(unittest.TestCase):
    """`/RC` is the same words as `/Contents` with their runs marked up.

    **Every reader that understands it prefers it**, so the two are written
    together or not at all -- a new `/Contents` beside the producer's old
    `/RC` shows the words that were replaced.

    Read off the fixture, which Acrobat wrote. Nothing here builds a `/RC`
    by hand: what a producer actually writes is the whole question, and an
    example of my own would only agree with my own reading of it.
    """

    def setUp(self):
        with pikepdf.open(RUN) as pdf:
            marks = [m for m in markup.marks_in(pdf) if m.page == 1]
        self.styled = [m for m in marks if markup.rich_to_html(m.rich)]
        self.plain = [m for m in marks if m.rich and not
                      markup.rich_to_html(m.rich)]
        # **Which of them a producer wrote.** The fixture carries our own
        # `/RC` too now, on anything the owner edited here and saved, and
        # what Acrobat puts in one is not what we put in one -- so the
        # claims about Acrobat's shape are made about Acrobat's.
        self.theirs = [m for m in marks if "APIVersion" in (m.rich or "")]
        if not self.styled or not self.plain or not self.theirs:
            self.skipTest("the fixture carries no styled and plain pair")

    def test_the_fixture_is_what_these_tests_assume(self):
        """Styled runs in some marks and none in others, both with `/RC`.

        Two shapes, read off the file: a note with *any* styling gets one
        `<span>` per run, including the runs with nothing set, while a note
        with none gets no span at all -- a bare `<p>`.
        """
        self.assertTrue(self.styled)
        self.assertTrue(self.plain)
        self.assertTrue(
            any(markup.rich_to_html(m.rich) for m in self.theirs),
            "nothing Acrobat wrote in this fixture is styled")
        self.assertTrue(
            any("<span" not in m.rich for m in self.theirs),
            "nothing was left as a bare paragraph")
        self.assertTrue(
            any(m.rich.count("<span") > 1 for m in self.theirs
                if markup.rich_to_html(m.rich)),
            "no styled mark of Acrobat's has more than one run, so nothing "
            "here shows that it spans the unstyled ones too")

    def test_what_is_styled_comes_through(self):
        seen = set()
        for mark in self.styled:
            html = markup.rich_to_html(mark.rich)
            seen.update(re.findall(r"([a-z-]+):[^;\"]+", html))
        self.assertIn("font-weight", seen)
        self.assertIn("text-decoration", seen)

    def test_a_run_with_nothing_set_arrives_as_bare_text(self):
        """A note with styling in it spans *every* run, the plain ones too.
        Keeping those spans would mark up what nobody styled."""
        dropped = False
        for mark in self.theirs:
            was = mark.rich.count("<span")
            html = markup.rich_to_html(mark.rich) or ""
            with self.subTest(length=len(mark.contents)):
                self.assertLessEqual(html.count("<span"), was)
            dropped = dropped or html.count("<span") < was
        self.assertTrue(dropped, "no unstyled run was ever unwrapped")

    def test_the_negative_size_and_the_alignment_are_dropped(self):
        """A negative size is not a size, and an alignment inside a line is
        not a style."""
        for mark in self.theirs:
            html = markup.rich_to_html(mark.rich) or ""
            if "<span" not in mark.rich:
                # A note Acrobat styled nowhere is a bare paragraph: no
                # span, and so no size to drop.
                continue
            with self.subTest(length=len(mark.contents)):
                self.assertIn("font-size", mark.rich)
                self.assertNotIn("font-size", html)
                self.assertNotIn("text-align", html)

    def test_rich_text_that_styles_nothing_is_no_rich_text(self):
        """`/Contents` already says it, and the caller has that."""
        for mark in self.plain:
            with self.subTest(length=len(mark.contents)):
                self.assertIsNone(markup.rich_to_html(mark.rich))

    def test_nothing_of_the_words_is_lost(self):
        """The styling is dropped from the markup, never from the text."""
        for mark in self.styled:
            html = markup.rich_to_html(mark.rich)
            bare = unescape(re.sub(r"<[^>]+>", "", html))
            with self.subTest(length=len(mark.contents)):
                self.assertEqual(bare.split(), mark.contents.split())

    def test_rubbish_is_not_an_error(self):
        self.assertIsNone(markup.rich_to_html("<p>unclosed"))
        self.assertIsNone(markup.rich_to_html(""))

    def test_styled_runs_are_written_the_way_the_file_has_them(self):
        """What we write has to parse back the way the producer's does."""
        rich = markup.rich_from_runs(
            [[("plain ", {}), ("bold", {"font-weight": "bold"})]])
        self.assertIn('<span dir="ltr" style="font-weight:bold">bold</span>',
                      rich)
        self.assertIn('xmlns="http://www.w3.org/1999/xhtml"', rich)
        self.assertNotIn("APIVersion", rich,
                         "that names the Acrobat build that wrote the file")
        self.assertEqual(markup.rich_to_html(rich),
                         'plain <span style="font-weight:bold">bold</span>')

    def test_runs_with_no_styling_still_get_a_span(self):
        """**Reader writes one round every run**, carrying every property at
        the value that means "not set".

        This asserted None, on a reading of the fixtures that counted the
        status links among the unstyled notes. Every bare `<p>` in the
        corpus belongs to text a producer composed -- a status change, a
        file attachment -- and every note a person typed carries a span.
        """
        rich = markup.rich_from_runs([[("just words", {})]])
        self.assertIn('<span dir="ltr" style="%s">just words</span>'
                      % markup.RICH_UNSET, rich)
        # And it still reads back as saying nothing: every property in it
        # is at its unset value, so the editor shows plain words rather
        # than a note that has been styled to look exactly like one.
        self.assertIsNone(markup.rich_to_html(rich))

    def test_text_this_application_composed_is_written_bare(self):
        """A status change's words are not somebody's note. Reader writes
        those as a bare `<p>`, with no span and no `dir`."""
        self.assertIn("<p>Accepted set by dws</p>",
                      markup.rich_from_text("Accepted set by dws",
                                            generated=True))
        self.assertIn('<p dir="ltr"><span dir="ltr"',
                      markup.rich_from_text("Accepted set by dws"))

    def test_what_is_written_is_escaped(self):
        rich = markup.rich_from_runs([[("<b>&", {"font-style": "italic"})]])
        self.assertIn("&lt;b&gt;&amp;", rich)
        self.assertEqual(markup.rich_to_html(rich),
                         '<span style="font-style:italic">&lt;b&gt;&amp;</span>')


class TestWhatIsWrittenBesideTheText(unittest.TestCase):
    """The export half: `/RC` written with `/Contents`, or taken away."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(RUN)
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]

    def saved(self, **fields):
        from pdfarranger_qt.export import export

        edits = markup.MarkEdits()
        edits.change(self.pages[0].uid, self.marks[0].index, **fields)
        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               mark_edits=edits)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    def test_the_file_arrives_with_rich_text_to_lose(self):
        """The fixture is the evidence for the two tests under this one."""
        self.assertTrue(self.marks[0].rich,
                        "the fixture's mark carries no /RC")

    def test_styling_is_written_as_rich_text(self):
        rich = markup.rich_from_runs(
            [[("plain and ", {}), ("bold", {"font-weight": "bold"})]])
        with self.saved(contents="plain and bold", rich=rich) as got:
            back = [m for m in markup.marks_in(got) if m.page == 1][0]
            self.assertEqual(back.contents, "plain and bold")
            self.assertEqual(markup.rich_to_html(back.rich),
                             'plain and <span style="font-weight:bold">bold'
                             "</span>")

    def test_an_edit_with_no_styling_takes_the_old_rich_text_away(self):
        """Left behind, it is the words we just replaced -- and the one a
        reader shows."""
        with self.saved(contents="just plain", rich=None) as got:
            back = [m for m in markup.marks_in(got) if m.page == 1][0]
            self.assertEqual(back.contents, "just plain")
            self.assertFalse(back.rich, "the producer's /RC survived an edit")

    def test_a_mark_of_our_own_writes_its_own_rich_text(self):
        rich = markup.rich_from_runs([[("said", {"font-style": "italic"})]])
        mark = markup.Annotation(markup.TEXT, self.pages[0].uid,
                                 (10.0, 10.0, 34.0, 34.0),
                                 contents="said", rich=rich)
        pdf = pikepdf.Pdf.new()
        entry = markup.to_dictionary(pdf, mark)
        self.assertEqual(str(entry["/Contents"]), "said")
        self.assertIn("font-style:italic", str(entry["/RC"]))


class TestALockedMark(unittest.TestCase):
    """`/F` bit 8: the attributes and the mark's own text are not to be
    changed. Read off a corpus document locked in Acrobat, whose highlight
    went from `/F` 4 to 132 and whose first reply went from 28 to 156."""

    def setUp(self):
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]

    def test_the_flag_is_read(self):
        """A fixture with nothing locked would make every test under this
        one vacuous, so it is checked rather than assumed."""
        self.assertEqual(markup.LOCKED, 128)
        for mark in self.marks:
            with self.subTest(subtype=mark.subtype):
                self.assertIsInstance(mark.locked, bool)

    def test_a_locked_item_opens_no_editor(self):
        """However it is reached -- by clicking the text, by clicking the
        author line, or by the thread opening on it."""
        from pdfarranger_qt.notepanel import Item, NotePanel

        panel = NotePanel()
        self.addCleanup(panel.deleteLater)
        panel.show_thread([
            Item("dws", "Nov 1", "The note", None, None, True),
            Item("dws", "Nov 1", "A reply", None, None, False),
        ])
        self.assertEqual(panel.selected(), panel.NOTHING)
        self.assertIsNone(panel._editor)
        panel.select(0)
        self.assertEqual(panel.selected(), panel.NOTHING,
                         "a locked item was opened")
        panel.select(1)
        self.assertEqual(panel.selected(), 1)
        self.assertIsNotNone(panel._editor)

    def test_locking_is_one_bit_and_the_others_are_the_producer_s(self):
        """A status link is Hidden and a reply is NoZoom+NoRotate, and
        neither has anything to do with being locked."""
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.export import export

        docs = DocumentSet()
        pages = docs.add_file(RUN)
        reply = [m for m in self.marks if m.is_reply()][0]
        was = None
        with pikepdf.open(RUN) as pdf:
            for a in pdf.pages[0].obj["/Annots"]:
                if str(a.get("/NM") or "") == reply.name:
                    was = int(a.get("/F", 0))
        edits = markup.MarkEdits()
        edits.change(pages[0].uid, reply.index, locked=not reply.locked)
        out = io.BytesIO()
        export(docs.files_for_export(), list(pages), {}, [out],
               mark_edits=edits)
        with pikepdf.open(io.BytesIO(out.getvalue())) as got:
            now = [int(a.get("/F", 0)) for a in got.pages[0].obj["/Annots"]
                   if str(a.get("/NM") or "") == reply.name][0]
        self.assertEqual(now & ~markup.LOCKED, was & ~markup.LOCKED,
                         "the producer's other flags were disturbed")
        self.assertEqual(bool(now & markup.LOCKED), not reply.locked)


class TestWhatAnEditLeavesAlone(unittest.TestCase):
    """**An appearance stream is thrown away only when what it draws has
    changed.**

    For a text markup it can be thrown away freely: every reader falls back
    to `/QuadPoints` and `/C` and redraws it. For a `/Text` it *is* the
    icon and nothing regenerates one -- the reader substitutes a default of
    its own, in its own colour, which is where a yellow note icon came from
    after an edit that had nothing to do with the icon.
    """

    def setUp(self):
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]
        self.reply = [m for m in self.marks if m.is_reply()][0]

    def patched(self, **edit):
        """One reply's dictionary, after an edit, and whether it kept its
        appearance."""
        with pikepdf.open(RUN) as pdf:
            row = [a for a in pdf.pages[0].obj["/Annots"]
                   if str(a.get("/NM") or "") == self.reply.name][0]
            self.assertIn("/AP", row.keys(), "the fixture's reply has no /AP")
            markup.apply_edit(row, edit)
            return "/AP" in row.keys()

    def test_the_things_that_do_not_change_what_is_drawn(self):
        for name, edit in (("contents", {"contents": "Rewritten"}),
                           ("rich", {"contents": "x", "rich": None}),
                           ("author", {"author": "Someone"}),
                           ("subject", {"subject": "A subject"}),
                           ("locked", {"locked": True}),
                           ("popup", {"popup": (10.0, 10.0, 90.0, 90.0)})):
            with self.subTest(field=name):
                self.assertTrue(self.patched(**edit),
                                "%s threw the appearance away" % name)

    def test_the_things_that_do(self):
        for name, edit in (("colour", {"colour": (0.1, 0.8, 0.3)}),
                           ("opacity", {"opacity": 0.5}),
                           ("quads", {"quads": [(10.0, 10.0, 90.0, 30.0)]})):
            with self.subTest(field=name):
                self.assertFalse(self.patched(**edit),
                                 "%s kept a stale appearance" % name)


class TestTheFormOnOneMark(unittest.TestCase):
    """The mark's properties: three tabs and a footer, writing three keys
    and one flag."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.properties import MarkProperties, Properties

        self.MarkProperties = MarkProperties
        self.was = Properties(
            kind="/Highlight",
            author="dws", subject="Highlight", when="Nov 1",
            created="Nov 1", colour=(1.0, 0.92, 0.23), opacity=1.0,
            locked=False,
            history=(("dws", "Accepted", "Nov 1"),
                     ("dws", "Completed", "Nov 1")))

    def form(self, **fields):
        made = self.MarkProperties(self.was._replace(**fields))
        self.addCleanup(made.deleteLater)
        return made

    def test_it_is_titled_after_the_tool_that_makes_it(self):
        """The only name of a mark the user has ever seen. `/Subj` never
        reaches the screen, so Reader's *Cross-Out Properties* heads the
        form with a word found nowhere in its interface -- we say
        Strikethrough, which is the one deliberate departure.
        """
        for kind, expected in (("/Highlight", "Highlight Properties"),
                               ("/StrikeOut", "Strikethrough Properties"),
                               ("/Underline", "Underline Properties"),
                               ("/Squiggly", "Underline Properties"),
                               ("/Text", "Comment Properties")):
            with self.subTest(kind=kind):
                self.assertEqual(self.form(kind=kind).windowTitle(), expected)

    def test_every_title_names_a_mark_a_tool_makes(self):
        """A form is titled with the mark's name from the tools table, and
        a title naming a mark no tool makes is the defect this replaced --
        Reader's *Cross-Out*, which appears nowhere in its own interface.

        **The mark's name, not the tool's.** This used to look for the
        title in the tools' labels, which held only while every mark was
        named like its tool; *Add text comment* makes a Text Box.
        """
        from pdfarranger_qt import tools
        from pdfarranger_qt.properties import KIND_LABELS

        marks = {mark for tool in tools.TOOLS for mark in tool.marks}
        for shown in set(KIND_LABELS.values()):
            with self.subTest(title=shown):
                self.assertIn(shown, marks,
                              "no tool makes a mark called %r" % shown)

    def test_one_tool_making_two_kinds_titles_each_by_what_it_is(self):
        """The comment tool makes a `/Text` on a point and a `/Highlight`
        over words. The second is a Highlight to the user, who has nothing
        to tell it from one the highlight tool made."""
        self.assertEqual(self.form(kind="/Highlight",
                                   subject="Comment on Text").windowTitle(),
                         "Highlight Properties")

    def test_renaming_a_mark_does_not_rename_its_form(self):
        """The General tab makes `/Subj` free text, and what a mark is
        called is not what it *is*."""
        form = self.form(kind="/StrikeOut", subject="Chapter three")
        self.assertEqual(form.windowTitle(), "Strikethrough Properties")

    def test_a_kind_with_no_name_here_still_gets_a_title(self):
        """One out of somebody else's file, from a tool not built here."""
        self.assertEqual(self.form(kind="/Polygon").windowTitle(),
                         "Mark Properties")

    def test_every_mark_it_writes_has_a_name_for_the_title(self):
        """A mark this application makes and cannot name would fall back to
        the generic title on a form the user opens every day.

        **Every mark, not every annotation.** A mark annotates the document
        with one or more annotations, and the form belongs to the mark.
        Replace Selected Text is two annotations and has a title of its own;
        a caret on its own is Insert Text, and is titled as that.
        """
        from pdfarranger_qt import markup
        from pdfarranger_qt.properties import KIND_LABELS

        marks = set(markup.KINDS) | {"replace_text"}
        self.assertEqual(marks - set(KIND_LABELS), set())

    def test_the_opacity_is_a_field_as_well_as_a_slider(self):
        """**Both, and both live**, as Reader has it -- photographed in the
        owner's notes. It was a label beside the slider, so a mark could
        only be faded by dragging and there was no asking for 50 exactly.
        """
        from PySide6.QtWidgets import QLineEdit

        form = self.form(opacity=0.5)
        self.assertIsInstance(form.percent, QLineEdit)
        self.assertEqual(form.percent.text(), "50%")
        self.assertEqual(form.slider.value(), 50)

    def test_typing_a_number_moves_the_slider_and_shows_the_page(self):
        form = self.form(opacity=0.5)
        seen = []
        form.previewed.connect(lambda _colour, value: seen.append(value))
        form.percent.setText("22")
        form.percent.textEdited.emit("22")
        self.assertEqual(form.slider.value(), 22)
        self.assertEqual(seen, [0.22])
        self.assertEqual(form.changed().get("opacity"), 0.22)

    def test_dragging_the_slider_fills_the_field(self):
        form = self.form(opacity=0.5)
        form.slider.setValue(22)
        self.assertEqual(form.percent.text(), "22%")

    def test_a_field_being_retyped_changes_nothing_yet(self):
        """Empty, or a bare `%`, is somebody mid-edit -- not a request for
        a transparent mark. A field you cannot clear cannot be retyped."""
        form = self.form(opacity=0.5)
        for half_typed in ("", "%"):
            with self.subTest(text=half_typed):
                form.percent.setText(half_typed)
                form.percent.textEdited.emit(half_typed)
                self.assertEqual(form.changed().get("opacity"), None)

    def test_leaving_the_field_tidies_what_is_in_it(self):
        form = self.form(opacity=0.5)
        form.percent.setText("75")
        form.percent.textEdited.emit("75")
        form.percent.editingFinished.emit()
        self.assertEqual(form.percent.text(), "75%")

    def test_what_it_refuses_to_take(self):
        from PySide6.QtGui import QValidator

        check = self.form(opacity=0.5).percent.validator().validate
        for text, verdict in (("", QValidator.Intermediate),
                              ("%", QValidator.Intermediate),
                              ("5", QValidator.Acceptable),
                              ("100", QValidator.Acceptable),
                              ("101", QValidator.Invalid),
                              ("-3", QValidator.Invalid),
                              ("abc", QValidator.Invalid)):
            with self.subTest(text=text):
                self.assertEqual(check(text, 0)[0], verdict)

    def test_a_locked_mark_refuses_the_field_too(self):
        """Either control fades the mark, so leaving one live is a way
        through the lock."""
        form = self.form(locked=True)
        self.assertFalse(form.percent.isEnabled())
        self.assertFalse(form.slider.isEnabled())
        form.locked.setChecked(False)
        self.assertTrue(form.percent.isEnabled())

    def test_it_has_the_three_tabs(self):
        from PySide6.QtWidgets import QTabWidget

        form = self.form()
        tabs = form.findChild(QTabWidget)
        self.assertEqual([tabs.tabText(n) for n in range(tabs.count())],
                         ["Appearance", "General", "Review History"])

    def test_a_kind_with_no_colour_has_no_appearance_tab(self):
        from PySide6.QtWidgets import QTabWidget

        tabs = self.form(has_colour=False).findChild(QTabWidget)
        self.assertNotIn("Appearance",
                         [tabs.tabText(n) for n in range(tabs.count())])

    def test_the_history_is_composed_and_not_stored(self):
        """Acrobat prints `{author}: {state}, {when}` and does not show the
        sentence each link carries in `/Contents`."""
        from PySide6.QtWidgets import QListWidget

        rows = self.form().findChild(QListWidget)
        self.assertEqual([rows.item(n).text() for n in range(rows.count())],
                         ["dws: Accepted, Nov 1", "dws: Completed, Nov 1"])

    def test_it_reports_only_what_changed(self):
        """A mark whose colour was touched keeps the author and the subject
        the producer gave it, which is what lets this patch a dictionary
        rather than replace one."""
        form = self.form()
        self.assertEqual(form.changed(), {})
        form.subject.setText("Something else")
        self.assertEqual(form.changed(), {"subject": "Something else"})

    def test_a_locked_mark_offers_nothing_but_the_way_to_unlock_it(self):
        form = self.form(locked=True)
        self.assertFalse(form.author.isEnabled())
        self.assertFalse(form.subject.isEnabled())
        self.assertFalse(form.swatch.isEnabled())
        form.locked.setChecked(False)
        self.assertTrue(form.author.isEnabled())
        self.assertTrue(form.subject.isEnabled())
        self.assertTrue(form.swatch.isEnabled())
        self.assertEqual(form.changed(), {"locked": False})

    def test_making_it_the_default_is_not_a_change_to_the_file(self):
        """It is this application's own preference for the next mark.

        A checkbox, not a button: it reads false until it is ticked, and
        ticking it is not something the form has to write anywhere.
        """
        form = self.form()
        self.assertFalse(form.make_default)
        form.make_default_box.setChecked(True)
        self.assertTrue(form.make_default)
        self.assertEqual(form.changed(), {})


class TestTheColourOfWordsInANote(unittest.TestCase):
    """Reader colours the words you have selected, from the note's own
    properties form. It is a property of a *run*, not of the mark: `/C`
    colours an icon and a pop-up's title bar, and has nothing to do with
    this."""

    def setUp(self):
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]
        self.coloured = [m for m in self.marks
                         if "color:" in (markup.rich_to_html(m.rich) or "")]

    def test_the_fixture_carries_a_coloured_run(self):
        """Written in Reader, so what is read here is a producer's own."""
        self.assertTrue(self.coloured,
                        "no mark in the fixture has a coloured run")

    def test_it_comes_through_on_the_way_in(self):
        """It was dropped for a while: the list of properties kept from
        `/RC` had no `color` in it, so Reader's colours arrived plain."""
        for mark in self.coloured:
            html = markup.rich_to_html(mark.rich)
            with self.subTest(length=len(mark.contents)):
                self.assertRegex(html, r"color:#[0-9A-Fa-f]{6}")

    def test_the_editor_keeps_it(self):
        """**Nothing here can set a colour that the editor cannot keep.**
        The colours would otherwise go the first time anybody posted an
        edit to a reply that had them."""
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.notepanel import NoteEditor

        for mark in self.coloured:
            editor = NoteEditor()
            self.addCleanup(editor.deleteLater)
            editor.setHtml(markup.rich_to_html(mark.rich))
            inks = {style["color"] for line in editor.runs() for _t, style in line
                    if "color" in style}
            with self.subTest(length=len(mark.contents)):
                self.assertTrue(inks, "the editor lost every colour")
                written = markup.rich_from_runs(editor.runs())
                for ink in inks:
                    self.assertIn("color:%s" % ink, written)

    def test_text_colour_applies_to_the_selection(self):
        from PySide6.QtGui import QTextCursor
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.notepanel import NoteEditor

        editor = NoteEditor()
        self.addCleanup(editor.deleteLater)
        editor.setPlainText("Add some more text.")
        cursor = editor.textCursor()
        cursor.setPosition(4)
        cursor.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.recolour(markup.PALETTE[4][1])
        self.assertEqual(
            [(text, style.get("color")) for text, style in editor.runs()[0]],
            [("Add ", None), ("some", "#DB3326"), (" more text.", None)])

    def test_clearing_the_formatting_takes_the_colour_with_it(self):
        """A merge only applies what a format *sets*, and a colour has no
        "none" to set -- so clearing has to replace the format rather than
        merge one over it."""
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.notepanel import NoteEditor

        editor = NoteEditor()
        self.addCleanup(editor.deleteLater)
        editor.setPlainText("Add some more text.")
        editor.selectAll()
        editor.recolour(markup.PALETTE[4][1])
        editor.restyle("bold")
        self.assertTrue(editor.runs()[0][0][1])
        editor.selectAll()
        editor.restyle("clear")
        self.assertEqual(editor.runs()[0], [("Add some more text.", {})])
