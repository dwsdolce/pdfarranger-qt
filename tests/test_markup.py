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

import math
import os
import re
import unittest

import pikepdf
from support import FIXTURES, TEST_PDF, settle, temp_path

from pdfarranger_qt import markup, noteicons
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

    def test_its_page_pointer_is_a_reference_to_that_page(self):
        """`/P` has to point at the page, not contain it.

        Written as a direct object it is a copy of the page's entire
        dictionary tucked inside the annotation, and qpdf refuses to save
        the result -- so every mark vanished, silently, from every export.
        Exercised through `_write` because the mistake was in the caller:
        `add_to_page` is handed a `pikepdf.Page` wrapper, and a unit test
        that passes the object underneath it cannot see this at all.
        """
        win = self.window()
        win.model.annotations.add(note(win.model.pages[1].uid, "on page two"))
        with self.saved(win) as pdf:
            marks = [a for a in pdf.pages[1].get("/Annots", [])
                     if str(a.get("/Subtype")) == "/Text"]
            self.assertEqual(len(marks), 1)
            self.assertIn("/P", marks[0])
            self.assertTrue(marks[0]["/P"].is_indirect,
                            "the page is copied into the mark, not pointed at")
            self.assertEqual(marks[0]["/P"].objgen,
                             pdf.pages[1].obj.objgen)

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
    """3.1's done-when, on the same stack as everything else."""

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


def two_pages_of_lines(path):
    """Two pages that both carry text, for the gesture to try to cross."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
        Encoding=pikepdf.Name.WinAnsiEncoding))
    for which in ("first", "second"):
        pdf.add_blank_page(page_size=(400, 300))
        page = pdf.pages[-1]
        page.Contents = pdf.make_stream("\n".join(
            "BT /F1 14 Tf 40 %d Td (the %s page line %d) Tj ET"
            % (240 - i * 24, which, i) for i in range(4)).encode())
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.save(path)
    pdf.close()
    return path


class TestAMarkBelongsToOnePage(unittest.TestCase):
    """With a markup tool armed, the selection stops at the page edge.

    Reader's behaviour, and the reason this is not a limitation: a mark is a
    thing *on a page* and has nowhere to go when the page ends, so dragging
    one past the bottom simply takes the rest of that page. Selecting first
    and applying a mark afterwards is the other case, where the selection
    may cross but then cannot be marked -- `TestTextIsMarkedOnePageAtATime`.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([two_pages_of_lines(temp_path("twopages.pdf"))])
        settle(timeout_ms=1000)
        self.win.set_read_mode(True)
        settle(timeout_ms=1400)
        self.canvas = self.win.reader.canvas
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=250)

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
        {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease:
             self.canvas.mouseReleaseEvent}[kind](event)

    def drag_off_the_bottom(self):
        """From the first page's top line to well below the page's last."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        first = self.canvas.to_viewport(
            self.canvas._layout.from_page(0, QPointF(45, 55)))
        page_rect = self.canvas._layout.page_rect(0)
        below = self.canvas.to_viewport(
            QPointF(page_rect.center().x(), page_rect.bottom() + 120))
        self.send(QMouseEvent.Type.MouseButtonPress, first)
        self.send(QMouseEvent.Type.MouseMove, below)
        # What the drag is showing: the selection it has made, which is what
        # the band on screen is drawn from. Read before the release, which
        # turns it into the mark and clears it.
        found = self.canvas.selection_quads_by_page()
        shown = found[0][1] if found else []
        self.send(QMouseEvent.Type.MouseButtonRelease, below)
        settle(timeout_ms=300)
        return shown, below

    def test_the_drag_leaves_the_page_and_the_mark_does_not(self):
        shown, below = self.drag_off_the_bottom()
        self.assertIsNotNone(self.canvas.page_at(below),
                             "the drag did not reach past the first page, so "
                             "this proves nothing about the boundary")
        self.assertNotEqual(self.canvas.page_at(below), 0,
                            "the pointer is still on the first page")
        self.assertTrue(shown, "the drag marked nothing at all")

    def test_every_quad_is_on_the_page_the_drag_began_on(self):
        self.drag_off_the_bottom()
        first = self.win.model.pages[0].uid
        second = self.win.model.pages[1].uid
        self.assertEqual(len(self.win.model.annotations.for_page(second)), 0,
                         "the second page took a mark from a drag that began "
                         "on the first")
        marks = self.win.model.annotations.for_page(first)
        self.assertEqual(len(marks), 1)
        height = float(self.win.model.pages[0].size[1])
        for quad in marks[0].quads:
            self.assertGreaterEqual(quad[1], 0.0)
            self.assertLessEqual(quad[3], height)

    def test_the_feedback_stops_where_the_mark_does(self):
        """What is shown while the pointer is past the page is exactly what
        is kept -- the band and the mark are one list of quadrilaterals."""
        shown, _below = self.drag_off_the_bottom()
        kept = self.win.model.annotations.for_page(
            self.win.model.pages[0].uid)[0]
        self.assertEqual([tuple(quad) for quad in shown],
                         [tuple(quad) for quad in kept.quads])


class TestTextIsMarkedOnePageAtATime(unittest.TestCase):
    """Select first, then apply a mark -- on one page only.

    The other case to `TestAMarkBelongsToOnePage`, where the tool is armed
    first. A selection made before any tool was chosen may still run across
    a page break, for reading; it cannot then be marked. It follows the
    order the file stores its text in, so it takes in whatever lies between
    -- footer, page number, header -- often off screen, and a mark made from
    it would cover text nobody meant to mark. While one exists the text
    tools are refused, and with the strip open the status bar says why.

    On one page, choosing the tool is itself what applies it, as in Reader.
    """

    #: The strip's tools that mark text, and so are refused for a selection
    #: across a page break.
    TEXT_TOOLS = ("highlight", "underline", "strikethrough", "comment",
                  "replace_text")

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([two_pages_of_lines(temp_path("perpage.pdf"))])
        settle(timeout_ms=1000)
        self.win.set_read_mode(True)
        settle(timeout_ms=1400)
        self.canvas = self.win.reader.canvas
        self.strip = self.win.tool_strip
        self.addCleanup(self.win.close)
        self.addCleanup(lambda: setattr(self.win, "modified", False))
        self.addCleanup(lambda: self.win.show_markup_tools(False))

    def counts(self):
        return [len(self.win.model.annotations.for_page(page.uid))
                for page in self.win.model.pages]

    def select_across(self):
        """Select from the first page's text into the second's."""
        self.canvas.select_between(0, 4, 1, 20)
        settle(timeout_ms=250)
        pages = sorted(self.canvas._selection)
        self.assertEqual(pages, [0, 1],
                         "the selection did not reach the second page, so "
                         "this proves nothing about refusing it")

    def select_on_one_page(self):
        self.canvas.select_between(0, 4, 0, 20)
        settle(timeout_ms=250)
        self.assertEqual(sorted(self.canvas._selection), [0])

    def choose(self, name):
        """Choose a tool the way the strip's flyout does: through its
        action, which a refused tool does not answer."""
        self.strip._actions[name].trigger()
        settle(timeout_ms=600)

    def enabled(self):
        return {name: self.strip._actions[name].isEnabled()
                for name in self.TEXT_TOOLS + ("select",)}

    def test_the_selection_may_cross_with_no_tool_armed(self):
        """The clamp belongs to the markup tools, not to selecting."""
        self.select_across()
        self.assertEqual(
            [page for page, _quads in self.canvas.selection_quads_by_page()],
            [0, 1])

    def test_a_selection_across_pages_is_not_marked(self):
        """Neither from the strip nor from the right-click menu's entries,
        which mark through `mark_the_selection`."""
        self.select_across()
        before = self.counts()
        self.choose("highlight")
        self.assertEqual(self.counts(), before)
        for tool in (self.canvas.HIGHLIGHT, self.canvas.UNDERLINE,
                     self.canvas.STRIKEOUT, self.canvas.NOTE_ON_TEXT,
                     self.canvas.REPLACE):
            self.assertFalse(self.canvas.mark_the_selection(tool), tool)
        self.assertEqual(self.counts(), before)

    def test_the_text_tools_are_refused_while_it_crosses(self):
        """And offered again once it no longer does -- cleared, or made on
        one page. Select is never refused: it makes no mark."""
        everything = dict.fromkeys(self.TEXT_TOOLS + ("select",), True)
        self.assertEqual(self.enabled(), everything)
        self.select_across()
        self.assertEqual(self.enabled(),
                         {**dict.fromkeys(self.TEXT_TOOLS, False),
                          "select": True})
        self.canvas.clear_selection()
        settle(timeout_ms=100)
        self.assertEqual(self.enabled(), everything)
        self.select_across()
        self.select_on_one_page()
        self.assertEqual(self.enabled(), everything)

    def test_the_message_is_shown_only_with_the_strip_open(self):
        """Somebody marking up is told why; somebody reading is not. And
        it goes with the selection it explained."""
        from pdfarranger_qt.i18n import _

        said = _("Text is marked one page at a time.")
        bar = self.win.statusBar()
        self.select_across()
        self.assertEqual(bar.currentMessage(), "",
                         "the strip is shut, so nobody is marking up")
        self.canvas.clear_selection()
        settle(timeout_ms=100)
        self.win.show_markup_tools(True)
        settle(timeout_ms=200)
        self.select_across()
        self.assertEqual(bar.currentMessage(), said)
        self.assertIn("color", bar.styleSheet(), "the warning is not red")
        self.canvas.clear_selection()
        settle(timeout_ms=100)
        self.assertEqual(bar.currentMessage(), "")
        self.assertEqual(bar.styleSheet(), "",
                         "the bar kept the warning's colour")

    def test_choosing_the_tool_is_what_applies_it(self):
        """Reader marks the words the moment the tool is chosen. There is no
        second action, and waiting for one left the selection wearing the
        tool's colour with no way to commit it."""
        self.select_on_one_page()
        before = self.counts()
        self.choose("underline")
        self.assertEqual([now - was for was, now in zip(before, self.counts())],
                         [1, 0])
        self.assertFalse(self.canvas.has_selection(),
                         "the selection outlived the mark made from it")
        self.assertEqual(self.strip.armed(), "underline",
                         "the tool should stay armed for the next run")

    def test_the_gesture_is_one_undo(self):
        self.select_on_one_page()
        before = self.counts()
        self.choose("highlight")
        self.assertEqual([now - was for was, now in zip(before, self.counts())],
                         [1, 0])
        self.win.undo()
        settle(timeout_ms=500)
        self.assertEqual(self.counts(), before)
        self.win.redo()
        settle(timeout_ms=500)
        self.assertEqual([now - was for was, now in zip(before, self.counts())],
                         [1, 0])

    def test_arming_a_tool_with_nothing_selected_marks_nothing(self):
        before = self.counts()
        self.choose("strikethrough")
        self.assertEqual(self.counts(), before)


class TestAMarkIsWrittenWithTheKeysAReaderExpects(unittest.TestCase):
    """Measured against the `/Highlight` Acrobat wrote into the Handbook.

    It carries `/AP /C /CA /Contents /CreationDate /F /M /NM /P /Popup
    /QuadPoints /RC /Rect /Subj /Subtype /T /Type`. Ours wrote ten of those,
    so a mark made here was missing who made it, when, what kind a reader
    should call it, and any name a reply could point at. `/Popup` and `/RC`
    are not here: both appear only when a mark has a comment.
    """

    def mark(self, **kwargs):
        from pdfarranger_qt import markup

        fields = dict(quads=[(36, 600, 300, 614)],
                      colour=(1.0, 0.92, 0.23),
                      author=markup.default_author())
        fields.update(kwargs)
        return markup.Annotation(markup.HIGHLIGHT, 1, (36, 600, 300, 614),
                                 **fields)

    def written(self, mark):
        """``(dictionary, page)``, with the document kept alive.

        Held on the case rather than dropped: the dictionary is an indirect
        object *in* that document, so letting it be collected destroys every
        object in it and the assertion fails against "object of type
        destroyed" rather than against a missing key.
        """
        from pdfarranger_qt import markup

        self.pdf = pikepdf.Pdf.new()
        self.pdf.add_blank_page(page_size=(612, 792))
        page = self.pdf.pages[0].obj
        return markup.to_dictionary(self.pdf, mark, page=page), page

    def test_it_says_who_made_it(self):
        entry, _page = self.written(self.mark())
        self.assertIn("/T", entry)
        self.assertTrue(str(entry["/T"]),
                        "the author key is there and empty, which is no "
                        "better than its being absent")

    def test_it_says_when_it_was_made_as_well_as_when_it_changed(self):
        """A reader sorts its comment list by one and shows the other."""
        entry, _page = self.written(self.mark())
        self.assertIn("/CreationDate", entry)
        self.assertIn("/M", entry)

    def test_it_says_what_a_reader_should_call_it(self):
        from pdfarranger_qt import markup

        for kind in markup.KINDS:
            with self.subTest(kind=kind):
                mark = markup.Annotation(kind, 1, (36, 600, 300, 614))
                entry, _page = self.written(mark)
                self.assertEqual(str(entry["/Subj"]), markup.SUBJECTS[kind])

    def test_it_points_at_the_page_it_is_on(self):
        entry, page = self.written(self.mark())
        self.assertEqual(entry["/P"], page)

    def test_it_can_be_named(self):
        """A reply and a status change are separate annotations that name the
        mark they answer, so a mark with no name cannot be replied to."""
        mark = self.mark()
        entry, _page = self.written(mark)
        self.assertTrue(str(entry["/NM"]))
        self.assertEqual(str(entry["/NM"]), mark.name)

    def test_two_marks_are_named_differently(self):
        self.assertNotEqual(self.mark().name, self.mark().name)

    def test_its_name_survives_being_copied(self):
        """Which is what undo does to every mark on every commit."""
        mark = self.mark()
        self.assertEqual(mark.duplicate().name, mark.name)

    def test_an_uncommented_mark_says_nothing(self):
        """Written unconditionally, `/Contents` is an empty note against a
        mark whose whole point was that it had nothing to add."""
        entry, _page = self.written(self.mark())
        self.assertNotIn("/Contents", entry)

    def test_a_commented_mark_says_what_was_typed(self):
        entry, _page = self.written(self.mark(contents="a note"))
        self.assertEqual(str(entry["/Contents"]), "a note")


class TestWhereAMarkTheFileBroughtIs(unittest.TestCase):
    """`Mark.quads` is not `Annotation.quads`, and that cost a gesture.

    `/QuadPoints` is four corners -- eight numbers -- and a `Mark` keeps them
    that way, because that is what the file says. An `Annotation` holds
    rectangles, because that is what this application makes. The first hit
    test treated the two alike and produced quadrilaterals of zero height,
    so nothing on any page was clickable and nothing said why.
    """

    def a_mark(self, **kwargs):
        from pdfarranger_qt.markup import Mark

        fields = dict(page=1, subtype="/Highlight", rect=(10, 20, 110, 40))
        fields.update(kwargs)
        return Mark(**fields)

    def test_four_corners_become_one_rectangle(self):
        # Upper-left, upper-right, lower-left, lower-right, as readers write
        # them -- and deliberately not in corner order, because the reading
        # must not depend on which corner comes first.
        mark = self.a_mark(quads=[(10, 40, 110, 40, 10, 20, 110, 20)])
        self.assertEqual(mark.boxes(), [(10, 20, 110, 40)])

    def test_every_quadrilateral_is_read(self):
        mark = self.a_mark(quads=[(0, 10, 50, 10, 0, 0, 50, 0),
                                  (0, 30, 80, 30, 0, 20, 80, 20)])
        self.assertEqual(mark.boxes(), [(0, 0, 50, 10), (0, 20, 80, 30)])

    def test_a_leaning_quadrilateral_gives_the_box_round_it(self):
        """No producer in the corpus writes one, and a box round it is still
        the right thing to aim a click at."""
        mark = self.a_mark(quads=[(12, 42, 110, 38, 10, 22, 108, 18)])
        self.assertEqual(mark.boxes(), [(10, 18, 110, 42)])

    def test_a_mark_with_no_quadrilaterals_falls_back_to_its_rectangle(self):
        """So a caller can ask any mark where it is without first asking
        what kind it is: a note and a stamp have no quadrilaterals at all."""
        self.assertEqual(self.a_mark(subtype="/Text").boxes(),
                         [(10, 20, 110, 40)])

    def test_the_two_kinds_are_read_by_one_piece_of_code(self):
        from pdfarranger_qt import markup
        from pdfarranger_qt.canvas import PageCanvas

        mine = markup.Annotation(markup.HIGHLIGHT, 1, (10, 20, 110, 40),
                                 quads=[(10, 20, 110, 40)])
        theirs = self.a_mark(quads=[(10, 40, 110, 40, 10, 20, 110, 20)])
        self.assertEqual(PageCanvas.mark_boxes(mine),
                         PageCanvas.mark_boxes(theirs))


if __name__ == "__main__":
    unittest.main()


FORMS = os.path.join(os.path.dirname(TEST_PDF), "exporter", "forms.pdf")
MANY_PAGES = os.path.join(os.path.dirname(TEST_PDF), "exporter", "outlines.pdf")


class TestFromThePointerToThePage(unittest.TestCase):
    """The seam a mark is placed through (3.2).

    A drag happens in viewport pixels; a mark is kept in the page's own space
   . Three frames are crossed between them, and the one that used to be
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
        """A box is five numbers and nothing invalidates it. Closing the
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
        """Draw's stroke, reported when the Pencil is finished: every point
        in one flat run, and how many each stroke has. It stood in for a
        tool that sent the rectangle it dragged out until Draw made a
        Pencil, and no tool sends one any more."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.DRAW)
        # Clear of the widget at (150, 550, 298, 570), so the field does not
        # take the press instead.
        self.drag(self.viewport_point(150, 690), self.viewport_point(298, 670))
        self.assertEqual(self.marks, [])     # nothing until it is finished
        QTest.keyClick(self.canvas.viewport(), Qt.Key_Return)
        self.assertEqual(len(self.marks), 1)
        tool, page, (points, counts) = self.marks[0]
        self.assertEqual((tool, page), (PageCanvas.DRAW, 0))
        self.assertEqual(counts, (2,))
        for got, want in zip(points, (150.0, 690.0, 298.0, 670.0)):
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

    def test_a_click_is_a_stroke_of_one_point(self):
        """What the canvas reports for a click under Draw: a stroke of one
        point, which the Pencil draws as a dot. It was a rectangle with no
        width while Draw stood in for a tool that sent rectangles."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.DRAW)
        where = self.viewport_point(200, 690)
        self.drag(where, where)
        QTest.keyClick(self.canvas.viewport(), Qt.Key_Return)
        self.assertEqual(len(self.marks), 1)
        _tool, _page, (points, counts) = self.marks[0]
        self.assertEqual(counts, (1,))
        self.assertAlmostEqual(points[0], 200.0, delta=1.0)
        self.assertAlmostEqual(points[1], 690.0, delta=1.0)

    def test_escape_puts_the_pointer_back_to_reading(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.DRAW)
        self.canvas.keyPressEvent(
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertEqual(self.canvas.tool(), PageCanvas.SELECT)

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
            """Pixels that are yellow-ish and not paper.

            **By the hue, not by a number.** A highlight is drawn at the
            opacity the file will carry -- 0.4 for one made here -- so
            yellow over white lands at a blue of 153 rather than 0, and a
            threshold tight enough for the undimmed colour counted none of
            it. What makes it a highlight is that blue is lower than green
            and the paper is no longer white, at whatever strength.
            """
            shot = QImage(self.canvas.viewport().size(), QImage.Format_RGB32)
            shot.fill(0xFFFFFFFF)
            self.canvas.viewport().render(shot)
            return sum(1 for y in range(0, shot.height(), 2)
                       for x in range(0, shot.width(), 2)
                       if shot.pixelColor(x, y).red() > 200
                       and shot.pixelColor(x, y).blue() < 220
                       and shot.pixelColor(x, y).blue()
                       < shot.pixelColor(x, y).green())

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

    def send(self, kind, point):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            kind, QPointF(point),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(point.x()), int(point.y()))),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease:
             self.canvas.mouseReleaseEvent}[kind](event)

    def highlight_two_lines(self):
        """Arm the highlighter and drag, and report what the drag showed.

        Through the mouse handlers rather than by calling the geometry
        directly, so that what is exercised is the path a pointer takes.
        What the drag shows is the selection it has made, which is what the
        band is drawn from and what the release turns into the mark.
        """
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.HIGHLIGHT)
        first, second = self.lines()[:2]
        self.send(QMouseEvent.Type.MouseButtonPress, self.on_line(first, 0.0))
        self.send(QMouseEvent.Type.MouseMove, self.on_line(second, 1.0))
        found = self.canvas.selection_quads_by_page()
        shown = found[0][1] if found else []
        self.send(QMouseEvent.Type.MouseButtonRelease,
                  self.on_line(second, 1.0))
        settle(timeout_ms=200)
        return shown

    def lines(self):
        """The page's lines of type, top down, as ``(left, bottom, right, top)``.

        Measured from the page rather than written down as viewport
        coordinates: a point that lands on the second line only because of
        where the window happened to open is a test of the window.
        """
        bands = []
        for left, bottom, right, top, _blank in self.canvas._glyphs.boxes(0):
            if bands and abs(bands[-1][3] - top) < 0.5:
                bands[-1] = (min(bands[-1][0], left), min(bands[-1][1], bottom),
                             max(bands[-1][2], right), max(bands[-1][3], top))
            else:
                bands.append((left, bottom, right, top))
        return sorted(bands, key=lambda b: -b[3])

    def on_line(self, band, across):
        """A viewport point on ``band``, ``across`` of the way along it."""
        from PySide6.QtCore import QPointF

        left, bottom, right, top = band
        x = left + (right - left) * across
        height = self.canvas._layout.page_height(0)
        return self.canvas.to_viewport(self.canvas._layout.from_page(
            0, QPointF(x, height - (bottom + top) / 2)))

    def test_two_lines_give_two_quads(self):
        self.assertEqual(len(self.highlight_two_lines()), 2)

    def test_the_gap_between_the_lines_is_not_covered(self):
        """Which is the whole difference between this and one box: the second
        line's top is below the first line's bottom, and nothing reaches
        across."""
        quads = self.highlight_two_lines()
        ordered = sorted(quads, key=lambda q: -q[3])
        upper, lower = ordered[0], ordered[1]
        self.assertGreater(upper[1], lower[3],
                           "the quads overlap, so one spans the gap")

    def test_the_mark_keeps_every_quad(self):
        self.highlight_two_lines()
        marks = self.win.model.annotations.for_page(self.win.model.pages[0].uid)
        self.assertEqual(len(marks), 1)
        self.assertEqual(len(marks[0].quads), 2)

    def test_what_the_drag_showed_is_what_it_kept(self):
        """The band and the mark come off the same measurement.

        The feedback is the selection and the mark is built from that same
        selection through `selection_quads_by_page`, which measures the
        loose boxes -- the font's ascent and descent -- rather than the
        ink Qt reports. So the band you drag is the band you get.
        """
        shown = self.highlight_two_lines()
        kept = self.win.model.annotations.for_page(
            self.win.model.pages[0].uid)[0]
        self.assertEqual([tuple(quad) for quad in shown],
                         [tuple(quad) for quad in kept.quads])



class TestAStickyNoteIsPlaced(unittest.TestCase):
    """Step 3.4. A note is placed rather than dragged out.

    A `/Text` annotation is the one mark whose size is not its author's to
    choose. Measured against PDFium, the icon is `markup.NOTE_SIZE` points
    square at the top left of `/Rect` -- for a `/Rect` of 20x20, of 60x60 and
    of no size at all, and the same 20 points whether the page is rendered at
    1x, 2x or 4x. So the gesture supplies a point, the rectangle is written
    at the size the icon will be, and the icon and the rectangle are one box.
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
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=200)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def at(self, x, y_down):
        from PySide6.QtCore import QPointF

        return self.canvas.to_viewport(
            self.canvas._layout.from_page(0, QPointF(x, y_down)))

    def send(self, kind, point):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            kind, QPointF(point),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(point.x()), int(point.y()))),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease:
             self.canvas.mouseReleaseEvent}[kind](event)

    def click(self, point):
        from PySide6.QtGui import QMouseEvent

        self.send(QMouseEvent.Type.MouseButtonPress, point)
        self.send(QMouseEvent.Type.MouseButtonRelease, point)
        settle(timeout_ms=250)

    def panel(self):
        return self.win.note_panel

    def writing(self):
        """Whether a note is open for *writing*, and on which mark.

        The window outlives the editor: posting closes the box and leaves
        the thread showing, so being visible is not the same as being open
        to type into.
        """
        if not (self.panel().isVisible() and self.win._noted is not None
                and self.panel()._editor is not None):
            return None
        return self.win._noted[0], self.win._noted[1][0]

    def reopen(self, x=125, y_down=210):
        """Let go of the mark, click its icon, then click its words.

        What a reader does. Letting go closes the thread and clicking the
        icon shows it again -- as text, because it has already been
        written. Clicking the words is what asks to change them, and
        `select` is what that click calls.
        """
        self.canvas.select_mark(None)
        settle(timeout_ms=150)
        self.click(self.at(x, y_down))
        settle(timeout_ms=250)
        self.assertIsNone(self.panel()._editor,
                          "a note already written opened in an editor")
        self.panel().select(0)
        settle(timeout_ms=150)

    def place(self, x=120, y_down=200, text="a note about this clause"):
        """Place a comment and write its note.

        The words are asked for in the window every other mark uses, not
        in a box drawn on the page: a comment *is* its note, so the two
        are one action. ``text=None`` cancels instead, which takes the
        mark with it -- a comment nobody wrote is a comment nobody made.
        """
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        self.click(self.at(x, y_down))
        if text is None:
            self.panel()._cancel()
        else:
            self.panel()._editor.setPlainText(text)
            self.panel()._post_it()
        settle(timeout_ms=250)

    def held(self):
        return self.win.model.annotations.for_page(self.win.model.pages[0].uid)

    def test_the_note_tool_marks_text_as_well_as_placing(self):
        """It is the one tool that does both. Over words it selects, as the
        highlighter does, and a click places its icon -- which is why it is
        not an area tool: an area tool drags out a box, and this drags out a
        selection or nothing at all."""
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        self.assertTrue(self.canvas.marks_text())
        self.assertFalse(self.canvas.marks_area())
        # And the gesture over words names the mark it makes, which is not
        # the tool's own name: a run of words is a `/Highlight`.
        self.assertEqual(PageCanvas.OVER_TEXT[PageCanvas.NOTE],
                         PageCanvas.NOTE_ON_TEXT)

    def test_a_click_places_a_note_of_the_icon_s_size(self):
        self.place(120, 200)
        marks = self.held()
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0].kind, markup.TEXT)
        left, bottom, right, top = marks[0].rect
        # The icon's own box, which Reader cuts to the glyph rather than
        # making every one a square.
        wide, tall = markup.icon_size(markup.DEFAULT_ICON)
        self.assertAlmostEqual(right - left, wide, places=3)
        self.assertAlmostEqual(top - bottom, tall, places=3)

    def test_the_point_clicked_is_the_icon_s_top_left(self):
        """Not its centre. Every viewer anchors the icon to that corner, so a
        note measured from anywhere else sits above where it was put."""
        self.place(120, 200)
        left, _bottom, _right, top = self.held()[0].rect
        height = self.canvas._layout.page_height(0)
        self.assertAlmostEqual(left, 120, delta=1.5)
        self.assertAlmostEqual(height - top, 200, delta=1.5)

    def test_placing_one_opens_its_editor(self):
        """A note with nothing in it is not a mark anyone meant to make, so
        the text is asked for as part of the same action."""
        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        self.click(self.at(120, 200))
        self.assertEqual(self.writing(), (0, self.held()[0]))

    def test_what_was_typed_is_kept(self):
        self.place(text="ask legal about this")
        self.assertEqual(self.held()[0].contents, "ask legal about this")

    def test_a_note_carries_no_quadrilaterals(self):
        """It marks a place, not a run of text, and `/QuadPoints` on a
        `/Text` would be a claim about text it does not cover."""
        self.place()
        self.assertEqual(self.held()[0].quads, ())

    def test_placing_and_writing_is_one_undo_step(self):
        """The entry pushed for placing it already holds the state from
        before the note existed, so one undo takes the note and its words
        together rather than leaving an empty icon behind."""
        before = self.win.model.undo.current
        self.place()
        self.assertEqual(self.win.model.undo.current, before + 1)
        self.win.model.undo.undo()
        settle(timeout_ms=250)
        self.assertEqual(len(self.held()), 0)

    def test_a_note_left_empty_leaves_nothing_behind(self):
        """Not even an undo step that undoes nothing: the mark goes and the
        entry placing it pushed is discarded."""
        before = self.win.model.undo.current
        self.place(text=None)
        self.assertEqual(len(self.held()), 0)
        self.assertEqual(self.win.model.undo.current, before)

    def test_clicking_the_icon_opens_the_note_again(self):
        """Letting go of the mark closes its thread; clicking the icon
        brings it back. Not a fresh editor -- the window outlives the box
        you typed into, and posting closes the box and leaves the thread."""
        self.place(text="the first draft")
        self.canvas.select_mark(None)
        settle(timeout_ms=200)
        self.assertIsNone(self.win._noted,
                          "letting go of the mark left its thread open")
        self.click(self.at(125, 210))
        self.assertIsNotNone(self.win._noted, "the icon opened nothing")
        self.assertIs(self.win._noted[1][0], self.held()[0])
        self.assertEqual(self.held()[0].contents, "the first draft")

    def test_the_icon_is_found_where_it_is_drawn(self):
        self.place(120, 200)
        found = self.canvas.note_at(self.at(125, 210))
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 0)
        self.assertEqual(found[1], 0)
        self.assertIsNone(self.canvas.note_at(self.at(125, 260)),
                          "a point well below the icon found one anyway")

    def test_hovering_reads_it_without_opening_anything(self):
        """A document covered in icons you have to click one at a time to
        read is a filing cabinet."""
        from PySide6.QtGui import QMouseEvent

        self.place(text="read me without clicking")
        self.send(QMouseEvent.Type.MouseMove, self.at(125, 210))
        settle(timeout_ms=200)
        self.assertEqual(self.canvas.viewport().toolTip(),
                         "read me without clicking")
        self.assertIsNone(self.writing())

    def test_editing_the_text_keeps_the_note_in_place(self):
        self.place(120, 200, "the first draft")
        rect = self.held()[0].rect
        self.reopen()
        self.panel()._editor.setPlainText("the second draft")
        self.panel()._post_it()
        settle(timeout_ms=250)
        self.assertEqual(self.held()[0].contents, "the second draft")
        self.assertEqual(self.held()[0].rect, rect)

    def test_an_existing_note_cannot_be_emptied(self):
        """Post is refused while the editor is empty, on every mark there
        is, so emptying one is no longer a way to take it back. Deleting
        the mark is, and it is a command of its own."""
        self.place(text="written, then thought better of")
        self.reopen()
        self.panel()._editor.setPlainText("   ")
        settle(timeout_ms=100)
        self.assertFalse(self.panel()._post.isEnabled(),
                         "Post offered itself on an empty note")
        self.panel()._post_it()
        settle(timeout_ms=250)
        self.assertEqual([m.contents for m in self.held()],
                         ["written, then thought better of"])

    def test_a_deleted_note_comes_back_with_its_words(self):
        self.place(text="do not lose this")
        self.win.delete_mark(0, self.held()[0])
        settle(timeout_ms=250)
        self.assertEqual(len(self.held()), 0)
        self.win.model.undo.undo()
        settle(timeout_ms=250)
        self.assertEqual([m.contents for m in self.held()],
                         ["do not lose this"])

    def test_escape_leaves_the_tool_and_takes_the_comment_with_it(self):
        """Escape on the canvas means "stop marking up". In the note window
        it means "never mind", and taking it there is what stops one
        keystroke doing both.

        **And never mind takes the comment.** A comment is its note, so
        abandoning the words abandons the mark -- what is typed and then
        escaped was never posted and never said.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        self.click(self.at(120, 200))
        self.panel()._editor.setPlainText("typed, then escaped")
        QTest.keyClick(self.panel(), Qt.Key_Escape)
        settle(timeout_ms=250)
        self.assertIsNone(self.writing())
        self.assertEqual(self.canvas.tool(), PageCanvas.NOTE)
        self.assertEqual(len(self.held()), 0)

    def test_placing_one_does_not_rebuild_the_reader(self):
        rebuilds = []
        real = self.win._load_reader
        self.win._load_reader = lambda *a, **k: (rebuilds.append(1),
                                                 real(*a, **k))[1]
        self.place()
        self.assertEqual(rebuilds, [])

    def test_it_is_drawn_before_anything_is_exported(self):
        """**In the colour the tool declares**, which the test asks for
        rather than naming: a note started amber here until Reader's own
        default was measured and it became Purple."""
        from PySide6.QtGui import QColor, QImage

        from pdfarranger_qt import tools

        want = QColor.fromRgbF(*markup.swatch(tools.by_name("comment").colour))

        def in_its_colour():
            shot = QImage(self.canvas.viewport().size(), QImage.Format_RGB32)
            shot.fill(0xFFFFFFFF)
            self.canvas.viewport().render(shot)
            return sum(
                1 for y in range(shot.height()) for x in range(shot.width())
                if max(abs(shot.pixelColor(x, y).red() - want.red()),
                       abs(shot.pixelColor(x, y).green() - want.green()),
                       abs(shot.pixelColor(x, y).blue() - want.blue())) < 40)

        blank = in_its_colour()
        self.place()
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=250)
        self.assertEqual(blank, 0)
        self.assertGreater(in_its_colour(), 100)

    def test_it_reaches_the_saved_file(self):
        import io

        from pdfarranger_qt.export import export

        self.place(text="for the record")
        out = io.BytesIO()
        export(self.win.docs.files_for_export(), list(self.win.model.pages),
               {}, [out], annotations=self.win.model.annotations)
        with pikepdf.open(io.BytesIO(out.getvalue())) as written:
            notes = [a for a in written.pages[0].get(pikepdf.Name.Annots, [])
                     if str(a.get(pikepdf.Name.Subtype)) == "/Text"]
            self.assertEqual(len(notes), 1)
            self.assertEqual(str(notes[0].Contents), "for the record")
            self.assertIn("/Name", notes[0])
            self.assertNotIn("/QuadPoints", notes[0])

    def test_the_saved_note_is_drawn_by_the_reader(self):
        """PDFium draws a `/Text` with no appearance stream of its own --
        measured, 1327 coloured pixels where a blank page has none -- which
        is why this writes no `/AP`: the icon is one every viewer's users
        already recognise, and ours would replace it with a rounded box."""
        from PySide6.QtCore import QPoint, QSize
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

        from pdfarranger_qt.canvas import ANNOTATIONS
        from pdfarranger_qt.export import export

        self.place(120, 200, "drawn by the reader")
        rect = self.held()[0].rect
        out = temp_path("note-rendered.pdf")
        export(self.win.docs.files_for_export(), list(self.win.model.pages),
               {}, [out], annotations=self.win.model.annotations)

        def ink(path):
            document = QPdfDocument()
            document.load(path)
            size = document.pagePointSize(0)
            pixels = QSize(int(size.width()), int(size.height()))
            options = QPdfDocumentRenderOptions()
            options.setScaledSize(pixels)
            options.setRenderFlags(ANNOTATIONS)
            raw = document.render(0, pixels, options)
            flat = QImage(raw.size(), QImage.Format_RGB32)
            flat.fill(0xFFFFFFFF)
            painter = QPainter(flat)
            painter.drawImage(QPoint(0, 0), raw)
            painter.end()
            return sum(
                1
                for y in range(int(size.height() - rect[3]),
                               int(size.height() - rect[1]))
                for x in range(int(rect[0]), int(rect[2]))
                if flat.pixelColor(x, y).red() < 245
                or flat.pixelColor(x, y).green() < 245
                or flat.pixelColor(x, y).blue() < 245)

        self.assertEqual(ink(TEXTED), 0,
                         "the fixture already has ink where the note goes")
        self.assertGreater(ink(out), 100)


class TestAScalableCommentIsWritten(unittest.TestCase):
    """The comment tool's twin, writing a `/Stamp`.

    Everything about the two is shared but the subtype, and the subtype is
    the whole difference: a `/Text` comment mark is fixed, anchored by its
    top left corner, while a stamp is ink on the page -- it scales, resizes,
    it turns, and it is placed by its centre.
    """

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()
        self.pdf.add_blank_page(page_size=(612, 792))

    def stamp(self, icon="/Comment", rotate=0.0, scale=1.0,
              centre=(300.0, 500.0)):
        mark = markup.Annotation(
            markup.STAMP, 1,
            markup.stamp_rect(centre[0], centre[1], icon, scale, rotate),
            contents="a scalable comment", icon=icon, colour=(1.0, 0.0, 0.0))
        mark.rotate = rotate
        return mark, markup.to_dictionary(self.pdf, mark)

    def test_it_is_page_content_and_asks_for_no_anchoring(self):
        """`/F 4`: Print and nothing else. NoZoom and NoRotate are what make
        a comment mark fixed to the page, and the whole point of this one
        is that it is not."""
        _mark, entry = self.stamp()
        self.assertEqual(int(entry["/F"]), markup.PRINTABLE)

    def test_it_is_placed_by_its_centre(self):
        """The fit to `/Rect` holds the artwork's centre at every angle and
        holds no corner at all, so a corner would walk across the page the
        first time the stamp was turned."""
        for angle in (0, 20, 45, 90, -30):
            with self.subTest(angle=angle):
                rect = markup.stamp_rect(300.0, 500.0, "/Comment", 2.0, angle)
                self.assertAlmostEqual((rect[0] + rect[2]) / 2, 300.0, places=6)
                self.assertAlmostEqual((rect[1] + rect[3]) / 2, 500.0, places=6)

    def test_the_rectangle_is_the_box_the_turned_artwork_needs(self):
        """Measured on Acrobat's own rotated stamp: artwork 99.69 by 30.34
        bounds 104.06 by 62.61 at twenty degrees. The same arithmetic."""
        wide, tall = markup.icon_size("/Key")
        for angle in (0, 20, 45, 90):
            with self.subTest(angle=angle):
                turned = math.radians(angle)
                across = abs(wide * math.cos(turned)) + abs(tall * math.sin(turned))
                down = abs(wide * math.sin(turned)) + abs(tall * math.cos(turned))
                rect = markup.stamp_rect(300.0, 500.0, "/Key", 1.0, angle)
                self.assertAlmostEqual(rect[2] - rect[0], across, places=6)
                self.assertAlmostEqual(rect[3] - rect[1], down, places=6)

    def test_the_scale_is_the_ratio_and_is_the_same_on_both_axes(self):
        """There is nowhere to write a scale. That the fit comes out equal
        on both axes is the aspect lock as the file records it."""
        mark, entry = self.stamp(icon="/Key", rotate=20.0, scale=2.2333)
        m = [float(v) for v in entry["/AP"]["/N"]["/Matrix"]]
        b = [float(v) for v in entry["/AP"]["/N"]["/BBox"]]
        r = [float(v) for v in entry["/Rect"]]
        corners = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
        moved = [(m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])
                 for x, y in corners]
        across = max(p[0] for p in moved) - min(p[0] for p in moved)
        down = max(p[1] for p in moved) - min(p[1] for p in moved)
        self.assertAlmostEqual((r[2] - r[0]) / across, 2.2333, places=4)
        self.assertAlmostEqual((r[3] - r[1]) / down, 2.2333, places=4)

    def test_a_turn_is_written_in_the_two_places_a_reader_looks(self):
        """`/Rotate` for this application to read back, and a pure rotation
        in the matrix for the reader that draws it."""
        _mark, entry = self.stamp(rotate=20.0)
        self.assertEqual(int(entry["/Rotate"]), 20)
        m = [float(v) for v in entry["/AP"]["/N"]["/Matrix"]]
        # Four places, not six: the matrix reaches the file through a
        # decimal and comes back a hair short of the angle it was built
        # from, which is the file's precision and not an error here.
        self.assertAlmostEqual(math.degrees(math.atan2(m[1], m[0])), 20.0,
                               places=4)
        self.assertAlmostEqual(math.hypot(m[0], m[1]), 1.0, places=4,
                               msg="the matrix carries a scale, which belongs "
                                   "in the rectangle")

    def test_an_unturned_stamp_writes_neither(self):
        _mark, entry = self.stamp(rotate=0.0)
        self.assertNotIn("/Rotate", entry)
        self.assertNotIn("/Matrix", entry["/AP"]["/N"])

    def test_the_size_it_was_given_can_be_read_back(self):
        """Nothing writes a scale, so a stamp that has been resized says so
        only through the ratio -- which is also how a change of icon can
        keep the size somebody chose."""
        for icon in ("/Comment", "/Key", "/RightPointer"):
            for angle in (0, 20, 90, -35):
                for scale in (1.0, 0.5, 3.25):
                    with self.subTest(icon=icon, angle=angle, scale=scale):
                        rect = markup.stamp_rect(300.0, 500.0, icon,
                                                 scale, angle)
                        self.assertAlmostEqual(
                            markup.stamp_scale(rect, icon, angle), scale,
                            places=9)

    def test_the_corners_turn_about_the_centre(self):
        """Where the handles go. They belong to the drawing, so at any angle
        but a right one they sit part way along the rectangle's edges rather
        than at its corners."""
        rect = markup.stamp_rect(300.0, 500.0, "/Key", 2.0, 20.0)
        corners = markup.stamp_corners(rect, "/Key", 20.0)
        self.assertEqual(len(corners), 4)
        middle = (sum(p[0] for p in corners) / 4, sum(p[1] for p in corners) / 4)
        self.assertAlmostEqual(middle[0], 300.0, places=6)
        self.assertAlmostEqual(middle[1], 500.0, places=6)
        for x, y in corners:
            self.assertGreaterEqual(x, rect[0] - 1e-6)
            self.assertLessEqual(x, rect[2] + 1e-6)
            self.assertGreaterEqual(y, rect[1] - 1e-6)
            self.assertLessEqual(y, rect[3] + 1e-6)
        self.assertFalse(
            any(abs(x - rect[0]) < 1e-6 and abs(y - rect[1]) < 1e-6
                for x, y in corners),
            "a turned stamp has a corner on the rectangle's corner")

    def test_a_turn_keeps_the_size_and_a_resize_keeps_the_angle(self):
        """The two handles say different things and neither says the
        other's: a corner moves the ratio, the fifth moves the angle."""
        rect = markup.stamp_rect(300.0, 500.0, "/Key", 2.5, 0.0)
        turned = markup.stamp_rect(300.0, 500.0, "/Key", 2.5, 40.0)
        self.assertAlmostEqual(markup.stamp_scale(turned, "/Key", 40.0), 2.5,
                               places=9)
        bigger = markup.stamp_rect(300.0, 500.0, "/Key", 4.0, 40.0)
        self.assertAlmostEqual(markup.stamp_scale(bigger, "/Key", 40.0), 4.0,
                               places=9)
        for box in (rect, turned, bigger):
            self.assertAlmostEqual((box[0] + box[2]) / 2, 300.0, places=9)
            self.assertAlmostEqual((box[1] + box[3]) / 2, 500.0, places=9)

    def test_changing_the_icon_keeps_the_size_it_was_given(self):
        """A stamp pulled to twice its size stays twice the size when its
        glyph changes. The factor is the ratio the rectangle records, and
        the new icon's own box times that is the rectangle it should have."""
        was = markup.stamp_rect(300.0, 500.0, "/Comment", 2.5, 20.0)
        factor = markup.stamp_scale(was, "/Comment", 20.0)
        now = markup.stamp_rect(300.0, 500.0, "/Key", factor, 20.0)
        self.assertAlmostEqual(markup.stamp_scale(now, "/Key", 20.0), 2.5,
                               places=9)
        wide, tall = markup.icon_size("/Key")
        self.assertNotAlmostEqual(now[2] - now[0], was[2] - was[0], places=1,
                                  msg="a narrower glyph kept the wider box")
        del wide, tall

    def test_a_turn_is_recordable_as_an_edit(self):
        """A stamp the file brought is reshaped through `MarkEdits`, so the
        angle has to travel that way -- and the appearance goes with it,
        because the matrix is the turn."""
        edits = markup.MarkEdits()
        edits.change(1, 0, rotate=35.0,
                     rect=markup.stamp_rect(300.0, 500.0, "/Key", 1.0, 35.0))
        _mark, entry = self.stamp(icon="/Key", rotate=0.0)
        self.assertNotIn("/Rotate", entry)
        markup.apply_edit(entry, edits.of(1, 0))
        self.assertEqual(int(entry["/Rotate"]), 35)
        self.assertNotIn("/AP", entry,
                         "the drawing was kept, so it still has the old turn")

    def test_the_comment_icon_is_the_balloon_and_not_the_square(self):
        """Acrobat substitutes its own glyph for a `/Text` comment, so what
        this application draws there is a display rule and the file keeps
        Acrobat's square. Nothing substitutes anything on a stamp, so the
        balloon has to be in the file for the two to agree."""
        _mark, entry = self.stamp(icon="/Comment")
        body = bytes(entry["/AP"]["/N"].read_bytes()).decode("latin-1")
        square = " ".join(noteicons.ICONS["/Comment"][2].split())
        self.assertNotIn(square[:40], " ".join(body.split()))
        self.assertIn(" re", body, "the two white bars are not in it")
        self.assertIn("1 1 1 rg", body, "the bars are not white")

    def test_every_other_icon_is_the_one_the_file_already_had(self):
        for icon in ("/Check", "/Key", "/Star", "/Help"):
            with self.subTest(icon=icon):
                _mark, entry = self.stamp(icon=icon)
                body = " ".join(
                    bytes(entry["/AP"]["/N"].read_bytes())
                    .decode("latin-1").split())
                want = " ".join(noteicons.ICONS[icon][2].split())
                self.assertEqual(
                    body.replace("1.0 0.0 0.0 rg", noteicons.FILL), want)
                # `/Name` is `/Comment` on every one of them, so that a
                # reader takes the mark for a comment and not for a rubber
                # stamp, and `/IT` says which icon it draws.
                self.assertEqual(str(entry["/Name"]), "/Comment")
                self.assertEqual(str(entry["/IT"]), icon)

    def test_text_note_is_named_in_full_because_its_own_name_is_empty(self):
        """It is the one icon written by leaving `/Name` out, so there is no
        name to carry over and `/IT` spells it instead."""
        _mark, entry = self.stamp(icon="")
        self.assertEqual(str(entry["/Name"]), "/Comment")
        self.assertEqual(str(entry["/IT"]), "/TextNote")


class TestAScalableCommentIsReshaped(unittest.TestCase):
    """Its five handles: four corners that scale it and one that turns it.

    Both work about the centre, which is the only point the fit to `/Rect`
    holds still, and the corners keep the aspect because one number does
    both axes -- 12.5.5 scales x and y independently, so a rectangle whose
    proportions do not match the artwork would skew it.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([TEXTED])
        settle(timeout_ms=1000)
        self.win.set_read_mode(True)
        settle(timeout_ms=1200)
        self.canvas = self.win.reader.canvas
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=200)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def send(self, kind, point, buttons=None):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        held = Qt.LeftButton if buttons is None else buttons
        event = QMouseEvent(
            kind, QPointF(point),
            self.canvas.viewport().mapToGlobal(
                QPoint(int(point.x()), int(point.y()))),
            Qt.LeftButton, held, Qt.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: self.canvas.mousePressEvent,
         QMouseEvent.Type.MouseMove: self.canvas.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease:
             self.canvas.mouseReleaseEvent}[kind](event)

    def a_stamp(self):
        """Place one, write its note, then take hold of it."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.STAMP)
        spot = self.canvas.to_viewport(
            self.canvas._layout.from_page(0, QPointF(200, 300)))
        self.send(QMouseEvent.Type.MouseButtonPress, spot)
        self.send(QMouseEvent.Type.MouseButtonRelease, spot)
        settle(timeout_ms=300)
        if self.win.note_panel._editor is not None:
            self.win.note_panel._editor.setPlainText("reshape me")
            self.win.note_panel._post_it()
        settle(timeout_ms=300)
        # The pointer, because a markup tool takes the press before a
        # handle does -- a drag with a tool armed means "make another one".
        self.canvas.set_tool(PageCanvas.SELECT)
        mark = self.win.model.annotations.for_page(
            self.win.model.pages[0].uid)[0]
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        return mark

    def shape(self, mark):
        return (markup.stamp_scale(mark.rect, mark.icon, mark.rotate),
                mark.rotate)

    def drag(self, which, by):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent

        start = self.canvas.grips()[which].center()
        end = QPointF(start.x() + by[0], start.y() + by[1])
        self.send(QMouseEvent.Type.MouseButtonPress, start)
        self.send(QMouseEvent.Type.MouseMove, end)
        self.send(QMouseEvent.Type.MouseButtonRelease, end)
        settle(timeout_ms=300)

    def hover(self, point):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QMouseEvent

        self.send(QMouseEvent.Type.MouseMove, point, buttons=Qt.NoButton)
        settle(timeout_ms=100)
        return self.canvas.viewport().cursor().shape()

    def test_the_pointer_says_what_it_can_do(self):
        """Over the stamp the move cursor, selected or not, because it can
        be moved either way; over a corner the arrow that points the way it
        would move; over the turning handle something of its own.

        Reader offers an arrow over an unselected stamp and a crosshair over
        a selected one. This application shows the move cursor over every
        mark that can be moved, the same for all of them."""
        from PySide6.QtCore import QPointF, Qt

        mark = self.a_stamp()
        middle = self.canvas.quad_on_screen(0, mark.rect, scaled=True).center()

        self.assertEqual(self.hover(middle), Qt.SizeAllCursor,
                         "a stamp you have hold of can be moved")
        corner = self.canvas.grips()[2].center()
        self.assertIn(self.hover(corner),
                      (Qt.SizeFDiagCursor, Qt.SizeBDiagCursor,
                       Qt.SizeVerCursor, Qt.SizeHorCursor),
                      "a corner should offer an arrow that resizes")
        turn = self.canvas.grips()[4].center()
        self.hover(turn)
        self.assertNotIn(self.canvas.viewport().cursor().shape(),
                         (Qt.CrossCursor, Qt.ArrowCursor, Qt.IBeamCursor),
                         "the turning handle should offer something of its own")

        self.canvas.select_mark(None)
        settle(timeout_ms=150)
        self.assertEqual(self.hover(middle), Qt.SizeAllCursor,
                         "a stamp nobody has hold of can be moved too")
        away = QPointF(middle.x(), middle.y() + 160)
        self.assertNotEqual(self.hover(away), Qt.CrossCursor,
                            "the crosshair followed the pointer off the stamp")

    def test_a_selected_stamp_offers_four_corners_and_a_turn(self):
        self.a_stamp()
        self.assertEqual(len(self.canvas.grips()), 5)

    def test_pulling_a_corner_scales_it_and_leaves_the_angle(self):
        mark = self.a_stamp()
        was, angle = self.shape(mark)
        self.drag(2, (40, -40))
        now, still = self.shape(mark)
        self.assertGreater(now, was * 1.5, "the corner did not take hold")
        self.assertEqual(still, angle)

    def test_turning_it_keeps_the_size_it_was_given(self):
        mark = self.a_stamp()
        self.drag(2, (40, -40))
        size, _angle = self.shape(mark)
        self.drag(4, (70, 30))
        now, turned = self.shape(mark)
        self.assertAlmostEqual(now, size, places=6,
                               msg="turning it changed its size")
        self.assertNotAlmostEqual(turned, 0.0, places=1,
                                  msg="the turn handle did not take hold")

    def test_the_centre_is_what_both_handles_hold_still(self):
        mark = self.a_stamp()
        middle = ((mark.rect[0] + mark.rect[2]) / 2,
                  (mark.rect[1] + mark.rect[3]) / 2)
        for which, by in ((2, (40, -40)), (4, (70, 30)), (0, (-25, 25))):
            with self.subTest(handle=which):
                self.drag(which, by)
                self.assertAlmostEqual(
                    (mark.rect[0] + mark.rect[2]) / 2, middle[0], delta=0.5)
                self.assertAlmostEqual(
                    (mark.rect[1] + mark.rect[3]) / 2, middle[1], delta=0.5)


class TestANoteLandsUnderThePointer(unittest.TestCase):
    """The turn is the whole of this.

    A viewer draws a note's icon at the top left of `/Rect` **in page space**
    and then turns the page, so a rectangle expanded in page space puts the
    icon wherever the turn happens to send it. Measured before the fix, for a
    click at the same spot on the same page: drawn 22 pixels to the *left* of
    the pointer at `/Rotate` 90, 28 up and to the left at 180, and 21 below it
    at 270. Only at zero was the pointer on the icon's corner -- which is
    exactly why a one-page upright fixture could not see this.
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

    def reading(self, angle):
        self.win.open_paths([TEXTED])
        settle(timeout_ms=900)
        if angle:
            self.win.model.rotate([0], angle)
            settle(timeout_ms=400)
        self.win.set_read_mode(True)
        settle(timeout_ms=1300)
        canvas = self.win.reader.canvas
        canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=200)
        return canvas

    def place_at(self, canvas, point):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        for kind in (QMouseEvent.Type.MouseButtonPress,
                     QMouseEvent.Type.MouseButtonRelease):
            event = QMouseEvent(
                kind, QPointF(point),
                canvas.viewport().mapToGlobal(
                    QPoint(int(point.x()), int(point.y()))),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            (canvas.mousePressEvent
             if kind == QMouseEvent.Type.MouseButtonPress
             else canvas.mouseReleaseEvent)(event)
        settle(timeout_ms=250)
        panel = self.win.note_panel
        if panel._editor is not None:
            panel._editor.setPlainText("under the pointer")
            panel._post_it()
            settle(timeout_ms=250)

    def test_the_icon_s_corner_is_where_the_pointer_was(self):
        from PySide6.QtCore import QPointF

        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle):
                canvas = self.reading(angle)
                self.assertEqual(canvas.page_box(0)[4], angle,
                                 "the reader's page is not turned, so this "
                                 "angle proves nothing")
                spot = canvas.to_viewport(
                    canvas._layout.from_page(0, QPointF(120, 200)))
                self.place_at(canvas, spot)
                marks = self.win.model.annotations.for_page(
                    self.win.model.pages[0].uid)
                self.assertEqual(len(marks), 1)
                icon = canvas.note_icon_rect(0, marks[0])
                self.assertAlmostEqual(icon.x(), spot.x(), delta=1.5)
                self.assertAlmostEqual(icon.y(), spot.y(), delta=1.5)
                self.win.modified = False
                self.win.close()
                self.setUp()

    def test_it_is_found_a_few_pixels_inside_whatever_the_turn(self):
        """Hit-tested in viewport pixels rather than page coordinates, because
        a point measured down the *page* moves in a different direction on
        screen once the page is turned -- which is how the first version of
        this test managed to fail against correct code."""
        from PySide6.QtCore import QPointF

        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle):
                canvas = self.reading(angle)
                spot = canvas.to_viewport(
                    canvas._layout.from_page(0, QPointF(120, 200)))
                self.place_at(canvas, spot)
                inside = QPointF(spot.x() + 4, spot.y() + 4)
                self.assertIsNotNone(
                    canvas.note_at(inside),
                    "the icon is not under the point that placed it")
                self.win.modified = False
                self.win.close()
                self.setUp()


class TestAMarkLivesInTheSourcePagesSpace(unittest.TestCase):
    """Written down and then not coded for a day.

    A mark is kept in the *source* page's space and multiplied by the page's
    resize on the way out, for a reason: a mark stored in output
    coordinates moves the next time its page is resized, because the space it
    was measured in is gone. `_write_annotations` did not multiply, so that is
    exactly what happened -- a note at (120, 572, 140, 592) on a page then
    scaled by half was written there onto paper 306 by 396.

    A crop and a turn really are free, and that is checked
    elsewhere: the reader's exported `/MediaBox` *is* the crop, in the original
    page's numbers, and `/Rotate` survives into the exported page.
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

    def reading(self, scale=None):
        self.win.open_paths([TEXTED])
        settle(timeout_ms=900)
        if scale is not None:
            self.win.model.pages[0].scale = scale
            self.win.model.touch([0])
            settle(timeout_ms=300)
        self.win.set_read_mode(True)
        settle(timeout_ms=1400)
        canvas = self.win.reader.canvas
        canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=200)
        return canvas

    def resize_to(self, scale):
        self.win.set_read_mode(False)
        settle(timeout_ms=300)
        self.win.model.pages[0].scale = scale
        self.win.model.touch([0])
        settle(timeout_ms=300)

    def place_note(self, canvas, x, y_down):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        self.win.set_tool(PageCanvas.NOTE)
        point = canvas.to_viewport(
            canvas._layout.from_page(0, QPointF(x, y_down)))
        for kind in (QMouseEvent.Type.MouseButtonPress,
                     QMouseEvent.Type.MouseButtonRelease):
            event = QMouseEvent(
                kind, QPointF(point),
                canvas.viewport().mapToGlobal(
                    QPoint(int(point.x()), int(point.y()))),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            (canvas.mousePressEvent
             if kind == QMouseEvent.Type.MouseButtonPress
             else canvas.mouseReleaseEvent)(event)
        settle(timeout_ms=250)
        panel = self.win.note_panel
        if panel._editor is not None:
            panel._editor.setPlainText("in the page's own space")
            panel._post_it()
            settle(timeout_ms=250)
        return point

    def held(self):
        return self.win.model.annotations.for_page(self.win.model.pages[0].uid)

    def written(self, subtype="/Text"):
        """``(mediabox, [rect, ...])`` for the marks of one subtype.

        Filtered by subtype, because `text_and_link.pdf` carries two `/Link`
        annotations of its own and they come out of the export first -- so
        taking "the first annotation" reads a link's rectangle and says
        nothing at all about the mark. Five of these tests asserted against a
        link before this filtered.
        """
        import io

        from pdfarranger_qt.export import export

        out = io.BytesIO()
        export(self.win.docs.files_for_export(), list(self.win.model.pages),
               {}, [out], annotations=self.win.model.annotations)
        with pikepdf.open(io.BytesIO(out.getvalue())) as doc:
            page = doc.pages[0]
            return ([float(v) for v in page.MediaBox],
                    [[float(v) for v in a[pikepdf.Name.Rect]]
                     for a in page.get(pikepdf.Name.Annots, [])
                     if str(a.get(pikepdf.Name.Subtype)) == subtype])

    def written_quadpoints(self, subtype="/Highlight"):
        """`/QuadPoints` of the first mark of ``subtype`` in a real export.

        Its own helper because `/Rect` cannot stand in for it: `to_dictionary`
        builds the rectangle from `Annotation.rect`, so a version that scales
        the rectangle and leaves the quadrilaterals writes a correct `/Rect`
        over a shape still drawn at the old size -- and a test that reads only
        the rectangle passes. That is what the first version of this did.
        """
        import io

        from pdfarranger_qt.export import export

        out = io.BytesIO()
        export(self.win.docs.files_for_export(), list(self.win.model.pages),
               {}, [out], annotations=self.win.model.annotations)
        with pikepdf.open(io.BytesIO(out.getvalue())) as doc:
            for annot in doc.pages[0].get(pikepdf.Name.Annots, []):
                if str(annot.get(pikepdf.Name.Subtype)) != subtype:
                    continue
                points = annot.get(pikepdf.Name.QuadPoints)
                return None if points is None else [float(v) for v in points]
        return None

    def test_a_note_stays_on_the_paper_when_its_page_is_resized(self):
        """The defect that keeping a mark in source space exists to prevent."""
        canvas = self.reading()
        self.place_note(canvas, 120, 200)
        self.assertEqual(len(self.held()), 1)
        self.resize_to(0.5)
        box, rects = self.written()
        self.assertEqual(len(rects), 1)
        left, bottom, right, top = rects[0]
        self.assertGreaterEqual(left, box[0])
        self.assertGreaterEqual(bottom, box[1])
        self.assertLessEqual(right, box[2])
        self.assertLessEqual(top, box[3],
                             "the mark is off the top of the resized page")

    def test_the_resize_moves_it_by_exactly_the_factor(self):
        canvas = self.reading()
        self.place_note(canvas, 120, 200)
        before = self.held()[0].rect
        self.resize_to(0.5)
        _box, rects = self.written()
        for got, want in zip(rects[0], [v * 0.5 for v in before]):
            self.assertAlmostEqual(got, want, delta=0.5)

    def test_the_mark_itself_is_not_touched_by_the_resize(self):
        """Source space is the point: the stored rectangle is what it was, and
        the arithmetic happens on the way out. Otherwise resizing twice
        compounds, and resizing back does not come back."""
        canvas = self.reading()
        self.place_note(canvas, 120, 200)
        before = self.held()[0].rect
        self.resize_to(0.5)
        self.assertEqual(self.held()[0].rect, before)
        self.resize_to(1.0)
        _box, rects = self.written()
        for got, want in zip(rects[0], before):
            self.assertAlmostEqual(got, want, delta=0.5)

    def test_a_note_placed_on_a_resized_page_is_stored_undone(self):
        """Placed on a page shown at half size, so what the canvas hands back
        is half -- and the mark has to hold the source page's numbers."""
        from pdfarranger_qt import markup

        canvas = self.reading(scale=0.5)
        self.assertEqual(canvas.page_scale(0), 0.5)
        self.place_note(canvas, 60, 100)
        left, bottom, right, top = self.held()[0].rect
        wide, tall = markup.icon_size(markup.DEFAULT_ICON)
        self.assertAlmostEqual(right - left, wide / 0.5, delta=0.5)
        self.assertAlmostEqual(top - bottom, tall / 0.5, delta=0.5)
        _box, rects = self.written()
        self.assertAlmostEqual(rects[0][2] - rects[0][0], wide, delta=0.5)

    def test_it_is_placed_under_the_pointer_on_a_resized_page(self):
        canvas = self.reading(scale=0.5)
        point = self.place_note(canvas, 60, 100)
        icon = canvas.note_icon_rect(0, self.held()[0])
        self.assertAlmostEqual(icon.x(), point.x(), delta=1.5)
        self.assertAlmostEqual(icon.y(), point.y(), delta=1.5)

    def test_the_icon_is_drawn_the_size_a_viewer_draws_it(self):
        """The rectangle's size in points, held whatever the magnification.

        NoZoom: the icon is `/Rect`'s width and height in default user
        space, drawn at that size however far the page is zoomed, so the
        zoom reaches only the corner it hangs from.

        A page *resized* is a different question, and the answer is that
        the icon goes with it: a mark is kept in the source page's space
        and multiplied by the resize on the way out, so halving the page
        halves the rectangle and the icon it describes. Asserted against
        what the export actually writes rather than against a number, so
        the screen and the file cannot drift apart.
        """
        from pdfarranger_qt import markup

        wide, _tall = markup.icon_size(markup.DEFAULT_ICON)
        canvas = self.reading()
        self.place_note(canvas, 120, 200)
        self.assertAlmostEqual(
            canvas.note_icon_rect(0, self.held()[0]).width(), wide, delta=0.5)
        was = canvas._layout.zoom
        canvas.set_zoom(was * 2.0)
        self.assertAlmostEqual(
            canvas.note_icon_rect(0, self.held()[0]).width(), wide, delta=0.5,
            msg="the page doubled under it and the icon went with it")
        canvas.set_zoom(was)
        self.resize_to(0.5)
        canvas = self.reading_again()
        _box, rects = self.written()
        self.assertAlmostEqual(
            canvas.note_icon_rect(0, self.held()[0]).width(),
            rects[0][2] - rects[0][0], delta=0.5,
            msg="the icon on screen is not the icon the file will hold")

    def reading_again(self):
        self.win.set_read_mode(True)
        settle(timeout_ms=1600)
        canvas = self.win.reader.canvas
        canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=250)
        return canvas

    def test_a_highlight_s_quadrilaterals_are_scaled_too(self):
        """Scaling the rectangle and leaving the quads puts the box in the
        right place around a shape still drawn at the old size, which is the
        mistake `_scale_annotation` exists to avoid for the marks a file
        already carries."""
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        from pdfarranger_qt.canvas import PageCanvas

        canvas = self.reading()
        self.win.set_tool(PageCanvas.HIGHLIGHT)

        def send(kind, point):
            event = QMouseEvent(
                kind, point,
                canvas.viewport().mapToGlobal(
                    QPoint(int(point.x()), int(point.y()))),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            {QMouseEvent.Type.MouseButtonPress: canvas.mousePressEvent,
             QMouseEvent.Type.MouseMove: canvas.mouseMoveEvent,
             QMouseEvent.Type.MouseButtonRelease:
                 canvas.mouseReleaseEvent}[kind](event)

        send(QMouseEvent.Type.MouseButtonPress, QPointF(70, 85))
        send(QMouseEvent.Type.MouseMove, QPointF(260, 92))
        self.assertTrue(canvas.selection_quads_by_page(),
                        "the drag selected nothing, so this proves nothing "
                        "about scaling quads")
        send(QMouseEvent.Type.MouseButtonRelease, QPointF(260, 92))
        settle(timeout_ms=250)
        mark = self.held()[0]
        self.assertTrue(mark.quads)
        before = mark.quads[0]
        self.resize_to(0.5)
        _box, rects = self.written("/Highlight")
        self.assertEqual(len(rects), 1)
        for got, want in zip(rects[0], [v * 0.5 for v in before]):
            self.assertAlmostEqual(got, want, delta=1.0)
        # And the quadrilaterals themselves, which the rectangle cannot stand
        # in for: see `written_quadpoints`.
        left, bottom, right, top = [v * 0.5 for v in before]
        points = self.written_quadpoints()
        self.assertIsNotNone(points, "the highlight was written without "
                                     "/QuadPoints, so this proves nothing")
        for got, want in zip(points, [left, top, right, top,
                                      left, bottom, right, bottom]):
            self.assertAlmostEqual(got, want, delta=1.0)


class TestTheTwoStylesOfUnderline(unittest.TestCase):
    """Reader's Underline tool writes two subtypes, and which one it writes
    *is* the style: `/Underline` straight, `/Squiggly` squiggly with
    `/IT /Underline` naming the tool it came from."""

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()

    def made(self, kind):
        mark = markup.Annotation(
            kind, 1, (36.0, 668.0, 196.0, 682.0),
            quads=[(36.0, 668.7, 196.0, 681.7)], colour=(0.0, 0.45, 0.9))
        return markup.to_dictionary(self.pdf, mark)

    def test_both_are_kinds_this_module_writes(self):
        for kind in (markup.UNDERLINE, markup.SQUIGGLY):
            with self.subTest(kind=kind):
                self.assertIn(kind, markup.KINDS)
                self.assertIn(kind, markup.QUADDED)
                self.assertEqual(markup.SUBJECTS[kind], "Underline")

    def test_a_squiggly_says_which_tool_made_it(self):
        """`/IT` names a *different* subtype's tool here, which is the one
        place it does that -- so a squiggly reads back as the Underline
        tool rather than as a kind of its own."""
        self.assertEqual(str(self.made(markup.SQUIGGLY)["/IT"]), "/Underline")
        self.assertNotIn("/IT", self.made(markup.UNDERLINE).keys())

    def over(self, annot, kind):
        """Our drawing for the run some Reader-written mark covers."""
        q = [float(v) for v in annot["/QuadPoints"]]
        quads = [tuple(q[n * 8 + i] for i in (0, 5, 2, 1))
                 for n in range(len(q) // 8)]
        mark = markup.Annotation(kind, 1, markup.bounding_rect(quads),
                                 quads=quads, colour=(0.0, 0.45, 0.9))
        return bytes(
            markup.to_dictionary(self.pdf, mark)["/AP"]["/N"].read_bytes()
        ).decode("latin-1")

    def readers(self, subtype):
        """Every mark of ``subtype`` the fixture's producer wrote."""
        with pikepdf.open(os.path.join(FIXTURES, "markup.pdf")) as pdf:
            for page in pdf.pages:
                for annot in page.get("/Annots", []):
                    if str(annot.get("/Subtype")) == subtype:
                        yield annot, bytes(
                            annot["/AP"]["/N"].read_bytes()).decode("latin-1")

    def test_the_sizes_are_fractions_of_the_type(self):
        """**Not points.** These were constants lifted from one 12.991pt
        line, so they were right on that line and nowhere else. Fitted
        across five corpus files and six text heights instead, each to
        five figures."""
        self.assertEqual(markup.STROKE_THICKNESS, 1 / 16)
        self.assertEqual(markup.UNDERLINE_OFFSET, 1 / 7)
        self.assertEqual(markup.STRIKEOUT_OFFSET, 3 / 7)
        self.assertEqual(markup.SQUIGGLE_SCALE, 1 / 72)
        self.assertEqual(markup.SQUIGGLE_BASE, 1 / 56)
        self.assertAlmostEqual(markup.SQUIGGLE_ASPECT, 1.8)

    def test_a_line_lands_where_reader_strokes_one(self):
        """Against the fixture's own marks, not against a number: for each
        underline and cross-out its producer wrote, ours is the same line
        at the same width. Both are *stroked* -- filling a rectangle from
        the quadrilateral's edge drew it half a width high."""
        seen = 0
        for subtype, kind in (("/Underline", markup.UNDERLINE),
                              ("/StrikeOut", markup.STRIKEOUT)):
            for annot, theirs in self.readers(subtype):
                width, y = re.search(
                    r"([\d.]+) w\s+[\d.]+ ([\d.]+) m", theirs).groups()
                ours = re.search(
                    r"([\d.]+) w\s+[\d.]+ ([\d.]+) m", self.over(annot, kind))
                self.assertIsNotNone(ours, "ours no longer strokes a line")
                with self.subTest(subtype=subtype, y=y):
                    self.assertAlmostEqual(float(ours.group(1)), float(width), 3)
                    self.assertAlmostEqual(float(ours.group(2)), float(y), 3)
                seen += 1
        self.assertGreaterEqual(seen, 3, "the fixture lost its marks")

    def test_a_wave_lands_where_readers_tile_does(self):
        """The fixture's squiggly places a 10-by-12 tile through a `cm`.
        Our wave has to reach the same trough, the same crest and the same
        cycle, which is what fixing the scale to points did not."""
        seen = 0
        for annot, theirs in self.readers("/Squiggly"):
            across, up, _x, base = (float(v) for v in re.search(
                r"([\d.]+) 0 0 ([\d.]+) ([\d.-]+) ([\d.-]+) cm",
                theirs).groups())
            ys = [float(m) for m in re.findall(
                r"[\d.]+ ([\d.]+) [ml]\b", self.over(annot, markup.SQUIGGLY))]
            with self.subTest(base=base):
                self.assertAlmostEqual(min(ys), base + up * 1.0, 3)
                self.assertAlmostEqual(max(ys), base + up * 11.0, 3)
                quad = [float(v) for v in annot["/QuadPoints"]]
                self.assertAlmostEqual(
                    markup.SQUIGGLE_ASPECT * markup.SQUIGGLE_SCALE
                    * (quad[1] - quad[5]) * markup.SQUIGGLE_CYCLE,
                    across * 10.0, 3)
            seen += 1
        self.assertGreaterEqual(seen, 1, "the fixture lost its squiggly")

    def test_the_squiggly_one_is_a_wave(self):
        body = bytes(self.made(markup.SQUIGGLY)["/AP"]["/N"].read_bytes())
        self.assertTrue(body.rstrip().endswith(b"S"),
                        "a wave is stroked, not filled")
        # Every turn of the wave is inside the run it marks.
        tops = [float(n) for n in re.findall(rb"[\d.]+ ([\d.]+) l", body)]
        self.assertTrue(tops)
        self.assertLessEqual(max(tops), 681.7)
        self.assertGreaterEqual(min(tops), 668.7)

    def test_changing_the_style_rewrites_the_subtype(self):
        """The one edit that changes what the annotation *is*. The stale
        appearance goes with it: a wave and a line are not the same
        drawing."""
        for was, becomes, style in ((markup.UNDERLINE, markup.SQUIGGLY, "squiggly"),
                                    (markup.SQUIGGLY, markup.UNDERLINE, "straight")):
            with self.subTest(style=style):
                entry = self.made(was)
                markup.apply_edit(entry, {"style": style})
                self.assertEqual(str(entry["/Subtype"]), becomes)
                self.assertNotIn("/AP", entry.keys())
                if becomes == markup.SQUIGGLY:
                    self.assertEqual(str(entry["/IT"]), "/Underline")
                else:
                    self.assertNotIn("/IT", entry.keys())

    def test_the_file_s_own_underlines_read_back_as_both(self):
        """The fixture carries one of each, written by Reader."""
        with pikepdf.open(os.path.join(FIXTURES, "markup.pdf")) as pdf:
            kinds = {m.subtype for m in markup.marks_in(pdf)}
        self.assertIn(markup.UNDERLINE, kinds)
        self.assertIn(markup.SQUIGGLY, kinds)


class TestANoteOnTheWordsIsStillAHighlight(unittest.TestCase):
    """*Add note to text* writes the `/Highlight` the Highlight tool writes.
    What tells the two apart in the file is `/Subj Comment on Text` and
    `/IT /HighlightNote` -- measured on `Markup Underline Write.pdf`, where
    four of them sit beside plain highlights written minutes apart.

    So a subtype is not a tool, and nothing here may key off `/Subtype`
    alone to decide which tool made a mark.
    """

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()

    def made(self, subject="", intent=""):
        mark = markup.Annotation(
            markup.HIGHLIGHT, 1, (36.0, 668.0, 196.0, 682.0),
            quads=[(36.0, 668.7, 196.0, 681.7)],
            subject=subject or None, intent=intent or None)
        return markup.to_dictionary(self.pdf, mark)

    def test_the_comment_tool_is_not_two_tools(self):
        """It had an entry of its own in the strip for two days. Reader
        never had one: *Add note to text* is in the right-click menu over a
        selection, and the toolbar tool it reaches is Add a comment."""
        from pdfarranger_qt import tools

        self.assertNotIn("note_on_text", [tool.name for tool in tools.TOOLS])
        with self.assertRaises(KeyError):
            tools.by_name("note_on_text")

    def test_it_writes_the_pair_that_names_it(self):
        entry = self.made(*markup.COMMENT_ON_TEXT)
        self.assertEqual(str(entry["/Subtype"]), markup.HIGHLIGHT)
        self.assertEqual(str(entry["/Subj"]), "Comment on Text")
        self.assertEqual(str(entry["/IT"]), "/HighlightNote")

    def test_a_plain_highlight_still_has_neither(self):
        """The generalisation that lets `/IT` be written must not start
        writing one on a highlight that has none."""
        entry = self.made()
        self.assertEqual(str(entry["/Subj"]), "Highlight")
        self.assertNotIn("/IT", entry.keys())

    def test_what_is_written_comes_back(self):
        """`/IT` was written and dropped on the way in, so a mark of ours
        could not say which tool made it after a round trip."""
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        markup.add_to_page(pdf, pdf.pages[0], [markup.Annotation(
            markup.HIGHLIGHT, 1, (36.0, 668.0, 196.0, 682.0),
            quads=[(36.0, 668.7, 196.0, 681.7)],
            subject=markup.COMMENT_ON_TEXT[0],
            intent=markup.COMMENT_ON_TEXT[1])])
        read = markup.marks_in(pdf)[0]
        self.assertEqual((read.subject, read.intent), markup.COMMENT_ON_TEXT)

    def test_an_intent_the_subtype_owns_is_still_written(self):
        """`/Squiggly` carries `/IT /Underline` whichever tool made it, and
        that default survives the move onto the annotation."""
        self.assertEqual(markup.INTENTS[markup.SQUIGGLY], markup.UNDERLINE)
        mark = markup.Annotation(
            markup.SQUIGGLY, 1, (36.0, 668.0, 196.0, 682.0),
            quads=[(36.0, 668.7, 196.0, 681.7)])
        self.assertEqual(
            str(markup.to_dictionary(self.pdf, mark)["/IT"]), markup.UNDERLINE)

    def test_a_mark_keeps_its_intent_through_a_copy(self):
        """`duplicate` is `copy.copy` over `__slots__`, so a field left out
        of the slots would be dropped on every scale and every undo."""
        mark = markup.Annotation(markup.HIGHLIGHT, 1, (0, 0, 10, 10),
                                 intent="/HighlightNote")
        self.assertEqual(mark.duplicate().intent, "/HighlightNote")
        self.assertEqual(mark, mark.duplicate())


class TestTheIconACommentCarries(unittest.TestCase):
    """Seventeen icons, Reader's drawings in Reader's boxes.

    Lifted from a file Reader wrote by `tools/extract_note_icons.py`, so
    a comment made here and one made there are the same comment. The
    numbers below are the measurement, written out rather than read back
    from the table they are checking.
    """

    #: What Reader gives each icon, measured on `Markup Comment.pdf`.
    #: The empty name is Text Note, which it writes by leaving `/Name`
    #: out rather than by writing the specification's `/Note`.
    BOXES = {
        "/Comment": (24.0, 24.0), "/Check": (19.0, 19.0),
        "/Checkmark": (20.0, 20.0), "/Circle": (20.0, 20.0),
        "/Cross": (19.0, 19.0), "/CrossHairs": (20.0, 20.0),
        "/Help": (20.0, 20.0), "/Insert": (17.0, 20.0),
        "/Key": (13.0, 18.0), "": (18.0, 20.0),
        "/Paragraph": (20.0, 20.0), "/RightArrow": (20.0, 20.0),
        "/RightPointer": (20.0, 17.0), "/Star": (20.0, 19.0),
        "/UpArrow": (17.0, 20.0), "/UpLeftArrow": (17.0, 17.0),
        "/NewParagraph": (13.0, 20.0),
    }

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()

    def made(self, icon):
        mark = markup.Annotation(markup.TEXT, 1,
                                 markup.note_rect(36.0, 700.0,
                                                  *markup.icon_size(icon)),
                                 contents="a note", icon=icon,
                                 colour=markup.swatch("Purple"))
        return markup.to_dictionary(self.pdf, mark)

    def test_there_are_seventeen_and_these_are_they(self):
        from pdfarranger_qt import noteicons

        self.assertEqual(set(noteicons.ICONS), set(self.BOXES))

    def test_each_box_is_the_one_reader_cuts(self):
        """Not a square each. A key is narrow and a right pointer is
        short, and the drawing is written for that box -- so taking the
        paths without the box stretches them."""
        for icon, box in self.BOXES.items():
            with self.subTest(icon=icon or "Text Note"):
                self.assertEqual(markup.icon_size(icon), box)

    def test_the_appearance_is_drawn_in_that_box(self):
        for icon, (wide, tall) in self.BOXES.items():
            with self.subTest(icon=icon or "Text Note"):
                entry = self.made(icon)
                self.assertEqual(
                    [float(v) for v in entry["/AP"]["/N"]["/BBox"]],
                    [0.0, 0.0, wide, tall])

    def test_text_note_is_written_by_leaving_the_key_out(self):
        self.assertNotIn("/Name", self.made("").keys())
        self.assertEqual(str(self.made("/Key")["/Name"]), "/Key")

    def test_every_icon_but_one_takes_the_mark_s_colour(self):
        """`/Checkmark` hard-codes its grey in defiance of `/C`. An Acrobat
        defect, reproduced so that the two files match."""
        from pdfarranger_qt import noteicons

        without = [icon for icon, (_w, _h, body) in noteicons.ICONS.items()
                   if noteicons.FILL not in body]
        self.assertEqual(without, ["/Checkmark"])
        grey = bytes(self.made("/Checkmark")["/AP"]["/N"].read_bytes())
        self.assertIn(b"0.396 0.396 0.396 rg", grey)
        star = bytes(self.made("/Star")["/AP"]["/N"].read_bytes())
        self.assertIn(b"0.5882", star)

    def test_none_of_them_needs_a_font(self):
        """Two declare one and never use it; the `NP` is drawn as curves.
        A drawing that needed a font would need the font in the file."""
        from pdfarranger_qt import noteicons

        for icon, (_w, _h, body) in noteicons.ICONS.items():
            with self.subTest(icon=icon or "Text Note"):
                self.assertNotIn(" Tj", body)
                self.assertNotIn(" TJ", body)


class TestHowSolidlyANoteIsPinned(unittest.TestCase):
    """`/F` on a comment's icon: Print, NoZoom and NoRotate, as Reader
    writes it -- fixed to the page rather than drawn on it. Both bits are
    false when `/F` is absent, so an annotation scales and turns unless it
    is told not to."""

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()

    def flags(self, **kwargs):
        mark = markup.Annotation(markup.TEXT, 1, (36, 700, 56, 720),
                                 contents="a note", **kwargs)
        return int(markup.to_dictionary(self.pdf, mark)["/F"])

    def test_an_icon_keeps_its_size_and_its_way_up(self):
        self.assertEqual(self.flags(), markup.ANCHORED)
        self.assertEqual(markup.ANCHORED,
                         markup.PRINTABLE | markup.NOZOOM | markup.NOROTATE)

    def test_nothing_here_can_ask_an_icon_to_scale(self):
        """Four readers give three answers to a cleared NoZoom bit, so this
        application never writes one. There is no attribute to set and no
        editable field to set it through."""
        made = markup.Annotation(markup.TEXT, 1, (36, 700, 56, 720))
        self.assertFalse(hasattr(made, "scales"))
        self.assertNotIn("scales", markup.MarkEdits.FIELDS)
        self.assertEqual(self.flags(), markup.ANCHORED)

    def test_the_lock_is_independent_of_both(self):
        self.assertEqual(self.flags(locked=True),
                         markup.ANCHORED | markup.LOCKED)

    def test_a_scaling_icon_the_file_carries_is_read_back(self):
        """Never written here, and not ignored either. Declining to offer a
        setting is not the same as deciding the file is wrong, so the bit is
        read off `/F` even though nothing here can put it there."""
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        markup.add_to_page(pdf, pdf.pages[0], [
            markup.Annotation(markup.TEXT, 1, (36, 700, 56, 720),
                              contents="fixed", icon="/Key"),
            markup.Annotation(markup.TEXT, 1, (80, 700, 100, 720),
                              contents="scaling", icon="/Star")])
        for annot in pdf.pages[0][pikepdf.Name.Annots]:
            if str(annot.get(pikepdf.Name.Contents, "")) == "scaling":
                annot[pikepdf.Name.F] = (
                    int(annot[pikepdf.Name.F]) & ~markup.NOZOOM)
        read = sorted(markup.marks_in(pdf), key=lambda m: m.contents)
        self.assertEqual([(m.icon, m.scales) for m in read],
                         [("/Key", False), ("/Star", True)])


class TestWhereTheInkIs(unittest.TestCase):
    """`markup.ink_box` says where a mark actually draws inside a quad.

    It exists so a mark can be hit by its ink rather than by the box its
    quadrilaterals describe. Which means it has to agree with what
    `_appearance` draws -- two statements of the same geometry, held
    together here.
    """

    QUAD = (36.0, 666.690, 195.916, 679.681)

    def setUp(self):
        self.pdf = pikepdf.Pdf.new()

    def drawn(self, kind):
        """The y values the appearance for ``kind`` actually strokes."""
        mark = markup.Annotation(kind, 1, markup.bounding_rect([self.QUAD]),
                                 quads=[self.QUAD], colour=(0.0, 0.45, 0.9))
        body = bytes(markup.to_dictionary(self.pdf, mark)["/AP"]["/N"]
                     .read_bytes()).decode("latin-1")
        width = float(re.search(r"([\d.]+) w\b", body).group(1))
        ys = [float(m) for m in re.findall(r"[\d.]+ ([\d.]+) [ml]\b", body)]
        return min(ys) - width / 2, max(ys) + width / 2

    def test_the_ink_is_what_the_appearance_draws(self):
        """Within a thousandth of a point, for every kind that strokes."""
        for kind in (markup.UNDERLINE, markup.STRIKEOUT, markup.SQUIGGLY):
            with self.subTest(kind=kind):
                low, high = self.drawn(kind)
                box = markup.ink_box(kind, self.QUAD)
                self.assertAlmostEqual(box[1], low, places=3)
                self.assertAlmostEqual(box[3], high, places=3)

    def test_a_highlight_fills_what_it_was_given(self):
        self.assertEqual(markup.ink_box(markup.HIGHLIGHT, self.QUAD),
                         self.QUAD)
        self.assertIn(markup.HIGHLIGHT, markup.FILLED)

    def test_a_stroke_is_a_fraction_of_the_box_it_sits_in(self):
        """The whole point: a cross-out claims four fifths of a point out of
        thirteen, so the box is sixteen times too much of the page."""
        box = markup.ink_box(markup.STRIKEOUT, self.QUAD)
        height = self.QUAD[3] - self.QUAD[1]
        self.assertAlmostEqual(box[3] - box[1],
                               height * markup.STROKE_THICKNESS, places=6)
        self.assertLess(box[3] - box[1], height / 15.0)

    def test_the_sides_are_the_quad_s_own(self):
        """Only the height narrows: a stroke runs the full width of the run
        it marks."""
        for kind in (markup.UNDERLINE, markup.STRIKEOUT, markup.SQUIGGLY,
                     markup.HIGHLIGHT):
            with self.subTest(kind=kind):
                box = markup.ink_box(kind, self.QUAD)
                self.assertEqual((box[0], box[2]),
                                 (self.QUAD[0], self.QUAD[2]))

    def test_a_kind_it_does_not_draw_is_taken_at_its_word(self):
        """Rather than shrunk to nothing, which would make it unhittable."""
        self.assertEqual(markup.ink_box(markup.TEXT, self.QUAD), self.QUAD)


class TestWhatColourEachToolStartsIn(unittest.TestCase):
    """A default belongs to a **tool**, and is named rather than numbered:
    one subtype can be two tools with two colours."""

    def test_every_tool_names_a_colour_in_the_palette(self):
        from pdfarranger_qt import tools

        for tool in tools.TOOLS:
            with self.subTest(tool=tool.name):
                if not tool.colour:
                    self.assertEqual(tool.family, tools.POINTER,
                                     "only a pointer makes no mark")
                    continue
                self.assertTrue(markup.swatch(tool.colour))

    def test_the_ones_read_off_reader(self):
        """Measured from a document made after Reader's settings were
        reset, in its own tool order."""
        from pdfarranger_qt import tools

        for name, colour in (("comment", "Purple"),
                             ("replace_text", "Light Red"),
                             ("insert_text", "Fuchsia"),
                             # Its border's; White was the box's fill.
                             ("text_comment", "Light Red"),
                             ("highlight", "Orange"),
                             ("underline", "Blue"),
                             ("strikethrough", "Light Red"),
                             # Its line's, as the Text Box's: the
                             # White was its fill again.
                             ("callout", "Light Red"),
                             ("draw", "Red"), ("stamps", "Red")):
            with self.subTest(tool=name):
                self.assertEqual(tools.by_name(name).colour, colour)

    def test_one_subtype_can_be_two_tools_with_two_colours(self):
        """Which is why the question is asked per tool: `/Caret` starts
        Light Red for one and Fuchsia for the other."""
        from pdfarranger_qt import tools

        self.assertNotEqual(tools.by_name("replace_text").colour,
                            tools.by_name("insert_text").colour)

    def test_a_name_that_is_not_a_colour_is_a_mistake(self):
        with self.assertRaises(KeyError):
            markup.swatch("Not A Colour")
