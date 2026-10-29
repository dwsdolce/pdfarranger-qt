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
