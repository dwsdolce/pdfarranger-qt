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

"""The document's own bookmark tree (D20).

Pure data, no pikepdf and no Qt, so the awkward questions -- what survives an
edit, what a dangling entry means, what happens to the children of a deleted
heading -- are answerable exactly rather than by poking a widget.
"""

import os
import unittest

from pdfarranger_qt.outline import Bookmark, Outline, from_pdf_outline
from support import HERE, settle

OUTLINE_PDF = os.path.join(HERE, "exporter", "outlines.pdf")


def sample() -> Outline:
    """Two chapters, the first with two sections, pointing at uids 1..5."""
    return Outline([
        Bookmark("Chapter 1", 1, [Bookmark("1.1", 2), Bookmark("1.2", 3)]),
        Bookmark("Chapter 2", 4, [Bookmark("2.1", 5)]),
    ])


def titles(outline):
    return [f"{'  ' * depth}{item.title}" for depth, item in outline.walk()]


class TestShape(unittest.TestCase):

    def test_walk_is_reading_order(self):
        self.assertEqual(titles(sample()),
                         ["Chapter 1", "  1.1", "  1.2", "Chapter 2", "  2.1"])

    def test_length_counts_every_entry(self):
        self.assertEqual(len(sample()), 5)

    def test_an_empty_outline_is_falsey(self):
        self.assertFalse(Outline())
        self.assertTrue(sample())

    def test_parent_and_siblings(self):
        outline = sample()
        chapter = outline.roots[0]
        section = chapter.children[0]
        self.assertIs(outline.parent_of(section), chapter)
        self.assertIsNone(outline.parent_of(chapter))
        self.assertIs(outline.siblings_of(chapter), outline.roots)
        self.assertIs(outline.siblings_of(section), chapter.children)

    def test_siblings_of_a_stranger_is_none(self):
        self.assertIsNone(sample().siblings_of(Bookmark("elsewhere", 9)))


class TestCopying(unittest.TestCase):
    """The undo snapshot takes one of these beside the page list."""

    def test_a_copy_is_independent(self):
        original = sample()
        copy = original.duplicate()
        copy.roots[0].title = "changed"
        copy.roots[0].children.pop()
        self.assertEqual(original.roots[0].title, "Chapter 1")
        self.assertEqual(len(original.roots[0].children), 2)

    def test_a_copy_keeps_the_targets(self):
        """Restoring a snapshot must reattach bookmarks to the same pages."""
        self.assertEqual([b.uid for _d, b in sample().duplicate().walk()],
                         [1, 2, 3, 4, 5])


class TestEditing(unittest.TestCase):

    def test_adding_at_the_root(self):
        outline = sample()
        added = outline.add("Chapter 3", 6)
        self.assertIs(outline.roots[-1], added)

    def test_adding_under_a_parent_at_a_position(self):
        outline = sample()
        chapter = outline.roots[0]
        outline.add("1.0", 9, parent=chapter, index=0)
        self.assertEqual([c.title for c in chapter.children], ["1.0", "1.1", "1.2"])

    def test_removing_promotes_the_children(self):
        """Deleting a heading should not silently discard its sections."""
        outline = sample()
        self.assertTrue(outline.remove(outline.roots[0]))
        self.assertEqual(titles(outline), ["1.1", "1.2", "Chapter 2", "  2.1"])

    def test_removing_a_stranger_says_so(self):
        self.assertFalse(sample().remove(Bookmark("elsewhere", 9)))

    def test_remove_subtree_takes_the_children_with_it(self):
        """The other half of remove: throwing a chapter away with its sections."""
        outline = sample()
        self.assertTrue(outline.remove_subtree(outline.roots[0]))
        self.assertEqual(titles(outline), ["Chapter 2", "  2.1"])

    def test_remove_subtree_works_on_a_child(self):
        outline = sample()
        outline.remove_subtree(outline.roots[0].children[0])
        self.assertEqual(titles(outline),
                         ["Chapter 1", "  1.2", "Chapter 2", "  2.1"])

    def test_remove_subtree_refuses_an_entry_that_is_not_there(self):
        self.assertFalse(sample().remove_subtree(Bookmark("Elsewhere", 9)))

    def test_moving_to_another_parent(self):
        outline = sample()
        section = outline.roots[0].children[0]
        self.assertTrue(outline.move(section, outline.roots[1], 0))
        self.assertEqual(titles(outline),
                         ["Chapter 1", "  1.2", "Chapter 2", "  1.1", "  2.1"])

    def test_moving_carries_the_children(self):
        outline = sample()
        chapter = outline.roots[0]
        self.assertTrue(outline.move(chapter, outline.roots[1], 0))
        self.assertEqual(titles(outline),
                         ["Chapter 2", "  Chapter 1", "    1.1", "    1.2", "  2.1"])

    def test_moving_to_the_root(self):
        outline = sample()
        section = outline.roots[0].children[1]
        self.assertTrue(outline.move(section, None, 0))
        self.assertEqual(titles(outline)[0], "1.2")

    def test_reordering_among_siblings(self):
        outline = sample()
        chapter = outline.roots[0]
        self.assertTrue(outline.move(chapter.children[0], chapter, 2))
        self.assertEqual([c.title for c in chapter.children], ["1.2", "1.1"])

    def test_an_entry_cannot_be_moved_into_itself(self):
        """It would detach the subtree from the tree and lose it."""
        outline = sample()
        chapter = outline.roots[0]
        self.assertFalse(outline.move(chapter, chapter, 0))
        self.assertFalse(outline.move(chapter, chapter.children[0], 0))
        self.assertEqual(len(outline), 5)


class TestThreeStates(unittest.TestCase):
    """Targeted, heading, and dangling.

    The last two both point nowhere and must not be confused: a heading does so
    deliberately -- the Handbook's "1" wrapper is one -- and Delete Dangling
    would eat it if the two were the same thing.
    """

    def test_a_targeted_entry(self):
        item = Bookmark("Ch 1", 1)
        self.assertFalse(item.dangling)
        self.assertFalse(item.heading)

    def test_a_heading_points_nowhere_on_purpose(self):
        item = Bookmark("Part One", None)
        self.assertTrue(item.heading)
        self.assertFalse(item.dangling)

    def test_a_dangling_entry_asked_for_a_page(self):
        item = Bookmark("Broken", None, wanted_target=True)
        self.assertTrue(item.dangling)
        self.assertFalse(item.heading)

    def test_orphaning_makes_a_targeted_entry_dangle(self):
        outline = sample()
        lost = outline.orphan({1, 2, 4, 5})            # page 3 deleted
        self.assertEqual([b.title for b in lost], ["1.2"])
        item = outline.roots[0].children[1]
        self.assertTrue(item.dangling)
        self.assertIsNone(item.uid)

    def test_an_orphan_is_kept_not_removed(self):
        """Its title may have been edited, and undo has to bring it back."""
        outline = sample()
        outline.orphan({1})
        self.assertEqual(len(outline), 5)

    def test_dangling_lists_only_broken_entries(self):
        outline = sample()
        outline.roots.append(Bookmark("Part Two", None))    # a heading
        outline.orphan({1, 2, 3, 4})                         # loses uid 5
        self.assertEqual([b.title for b in outline.dangling()], ["2.1"])

    def test_nothing_dangles_when_every_page_is_there(self):
        outline = sample()
        outline.orphan({1, 2, 3, 4, 5})
        self.assertEqual(outline.dangling(), [])

    def test_the_state_survives_a_copy(self):
        outline = sample()
        outline.orphan({1, 2, 3, 4})
        copy = outline.duplicate()
        self.assertEqual([b.title for b in copy.dangling()], ["2.1"])


class TestBuilding(unittest.TestCase):

    class FakeItem:
        def __init__(self, title, dest, children=()):
            self.title, self.dest, self.children = title, dest, list(children)

    def test_it_resolves_each_destination(self):
        items = [self.FakeItem("A", 10, [self.FakeItem("A.1", 11)]),
                 self.FakeItem("B", 12)]
        outline = from_pdf_outline(items, lambda item: item.dest)
        self.assertEqual(titles(outline), ["A", "  A.1", "B"])
        self.assertEqual([b.uid for _d, b in outline.walk()], [10, 11, 12])

    def test_an_unresolvable_destination_becomes_no_destination(self):
        items = [self.FakeItem("Outside", None)]
        outline = from_pdf_outline(items, lambda item: item.dest)
        self.assertIsNone(outline.roots[0].uid)

    def test_a_missing_title_is_empty_rather_than_absent(self):
        outline = from_pdf_outline([self.FakeItem(None, 1)], lambda i: i.dest)
        self.assertEqual(outline.roots[0].title, "")


class TestOutlineThroughEditing(unittest.TestCase):
    """The outline through a document's life (D20).

    The behaviour David asked for: edits, including undo, keep the bookmarks
    right. Driven through a real window, because the interesting part is the
    interaction between the page list, the undo stack and the outline, and a
    unit test of any one of them would miss it.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def outline(self):
        return self.win.model.outline

    def titles(self):
        return [b.title for _d, b in self.outline().walk()]

    def test_the_outline_is_read_from_the_loaded_file(self):
        self.assertEqual(self.titles(), ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_every_bookmark_points_at_a_page(self):
        uids = {p.uid for p in self.win.model.pages}
        for _depth, item in self.outline().walk():
            self.assertIn(item.uid, uids, item.title)

    def test_reordering_pages_leaves_the_bookmarks_alone(self):
        """Nothing here refers to a position, so there is nothing to remap."""
        before = [(b.title, b.uid) for _d, b in self.outline().walk()]
        self.win.model.move_rows([0], 4)
        settle(timeout_ms=200)
        self.assertEqual([(b.title, b.uid) for _d, b in self.outline().walk()], before)

    def test_deleting_a_page_leaves_its_bookmark_dangling(self):
        target = self.win.model.pages[1].uid
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=200)
        dangling = self.outline().dangling()
        self.assertEqual([b.title for b in dangling], ["Page 2"])
        self.assertNotIn(target, {p.uid for p in self.win.model.pages})

    def test_the_dangling_bookmark_is_kept_not_removed(self):
        """Its title may have been edited, and it has to be re-homable."""
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=200)
        self.assertEqual(len(self.outline()), 4)

    def test_undoing_the_delete_reattaches_the_bookmark(self):
        """One snapshot covers both, so the page and its bookmark come back together."""
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=200)
        self.assertEqual(len(self.outline().dangling()), 1)

        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.outline().dangling(), [],
                         "the bookmark did not find its page again")
        self.assertEqual(len(self.win.model.pages), 4)

    def test_duplicating_a_page_does_not_duplicate_its_bookmarks(self):
        """The copy is a new page with its own identity (D20)."""
        self.win.view.set_selected_rows([0])
        self.win.model.undo.commit("Duplicate")
        self.win.model.duplicate([0])
        settle(timeout_ms=200)
        self.assertEqual(self.titles().count("Page 1"), 1)
        self.assertEqual(len(self.win.model.pages), 5)

    def test_importing_a_second_file_concatenates_at_the_root(self):
        """No wrapper node per file: that is the shape a merged book has.

        A *copy* of the fixture, because importing the same path again reuses
        the document already loaded -- one source, one outline read, and the
        second set of pages are duplicates whose bookmarks stay with the first
        (D20). Two different files is the case this is about.
        """
        import shutil
        import tempfile

        second = os.path.join(tempfile.mkdtemp(), "second.pdf")
        shutil.copy(OUTLINE_PDF, second)
        self.addCleanup(shutil.rmtree, os.path.dirname(second), ignore_errors=True)

        self.win._load_paths([second])
        settle(timeout_ms=400)
        self.assertEqual(self.titles(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"] * 2)
        self.assertEqual(len(self.win.model.pages), 8)

    def test_importing_the_same_file_again_does_not_duplicate_bookmarks(self):
        """The second copy's pages are duplicates; bookmarks stay with the first."""
        self.win._load_paths([OUTLINE_PDF])
        settle(timeout_ms=400)
        self.assertEqual(len(self.win.model.pages), 8)
        self.assertEqual(self.titles(), ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_the_sidebar_shows_the_documents_outline(self):
        """End to end: the file's bookmarks reach the reader's tree."""
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.assertEqual(self.win.reader.outline_labels(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_a_dangling_bookmark_is_marked_in_the_tree(self):
        """Marked rather than hidden, so a delete does not silently lose it."""
        from PySide6.QtCore import QModelIndex, Qt

        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=300)

        model = self.win.reader.bookmarks
        titles = [model.index(r, 0, QModelIndex()).data() for r in range(4)]
        self.assertEqual(titles, ["Page 1", "Page 2", "Page 3", "Page 4"])
        greyed = [model.index(r, 0, QModelIndex()).data(Qt.ForegroundRole)
                  is not None for r in range(4)]
        self.assertEqual(greyed, [False, True, False, False],
                         "the orphaned entry is not distinguished")

    def test_the_tree_follows_an_undo(self):
        from PySide6.QtCore import QModelIndex, Qt

        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=300)
        self.win.undo()
        settle(timeout_ms=400)
        model = self.win.reader.bookmarks
        self.assertEqual(model.rowCount(QModelIndex()), 4)
        self.assertIsNone(model.index(1, 0, QModelIndex()).data(Qt.ForegroundRole),
                          "still marked dangling after undo")

    def test_clicking_a_bookmark_navigates_to_its_page(self):
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        from PySide6.QtCore import QModelIndex
        index = self.win.reader.bookmarks.index(2, 0, QModelIndex())
        self.win.reader._go_to_bookmark(index)
        settle(timeout_ms=300)
        self.assertEqual(self.win.reader.current_page(), 2)


class TestBookmarkCommands(unittest.TestCase):
    """The commands on the outline tree's context menu.

    Through a real window again, and for the same reason: a command is a
    snapshot on the page list's undo stack, a change to the tree the reader
    shows, and a document that now needs saving. Testing the `Outline`
    operations alone would prove none of that.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.set_read_mode(True)
        settle(timeout_ms=500)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    # -- helpers -----------------------------------------------------------

    def reader(self):
        return self.win.reader

    def outline(self):
        return self.win.model.outline

    def titles(self):
        return [f"{'  ' * depth}{item.title}" for depth, item in self.outline().walk()]

    def index_of_root(self, row):
        from PySide6.QtCore import QModelIndex
        return self.win.reader.bookmarks.index(row, 0, QModelIndex())

    def set_outline(self, outline):
        """Replace the document's outline, the way a load would."""
        self.win.model.outline = outline
        self.win.model.outline_changed.emit()
        settle(timeout_ms=200)

    def uid(self, page):
        return self.win.model.pages[page].uid

    # -- add ---------------------------------------------------------------

    def test_add_puts_a_sibling_after_the_selected_entry(self):
        self.reader().canvas.clear_selection()
        self.reader().go_to_page(2)
        settle(timeout_ms=300)
        self.assertTrue(self.reader().add_bookmark(self.index_of_root(0)))
        self.assertEqual(self.titles(),
                         ["Page 1", "Page 3", "Page 2", "Page 3", "Page 4"],
                         "the new entry is not the second one")

    def test_the_new_entry_points_at_the_page_being_read(self):
        self.reader().go_to_page(2)
        settle(timeout_ms=300)
        self.reader().add_bookmark(self.index_of_root(0))
        self.assertEqual(self.outline().roots[1].uid, self.uid(2))

    def test_add_with_nothing_selected_goes_to_the_end(self):
        from PySide6.QtCore import QModelIndex
        self.reader().add_bookmark(QModelIndex())
        self.assertEqual(len(self.outline().roots), 5)
        self.assertEqual(self.titles()[:4],
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_add_child_nests_under_the_selected_entry(self):
        self.reader().add_bookmark(self.index_of_root(0), as_child=True)
        self.assertEqual(len(self.outline().roots), 4)
        self.assertEqual(len(self.outline().roots[0].children), 1)

    def test_add_child_needs_something_to_nest_under(self):
        from PySide6.QtCore import QModelIndex
        self.assertFalse(self.reader().add_bookmark(QModelIndex(), as_child=True))
        self.assertEqual(len(self.outline()), 4)

    def test_the_title_comes_from_the_selected_text(self):
        """Which is why text selection had to be built first."""
        self.reader().canvas.select_all_on(0)
        settle(timeout_ms=300)
        self.assertTrue(self.reader().has_selection())
        self.reader().add_bookmark(self.index_of_root(0))
        self.assertTrue(self.outline().roots[1].title.startswith("Page 1"))

    def test_a_selection_crossing_lines_arrives_as_one_line(self):
        self.reader().canvas.select_all_on(0)
        settle(timeout_ms=300)
        title = self.reader().title_here()
        self.assertNotIn("\n", title)
        self.assertNotIn("\r", title)

    def test_the_title_falls_back_to_the_page_label(self):
        self.reader().canvas.clear_selection()
        self.reader().go_to_page(3)
        settle(timeout_ms=300)
        self.assertEqual(self.reader().title_here(), "Page 4")

    def test_adding_marks_the_document_modified(self):
        """The outline is part of the document, so a save has to write it."""
        self.reader().add_bookmark(self.index_of_root(0))
        self.assertTrue(self.win.modified)

    def test_adding_takes_one_undo_entry(self):
        self.reader().add_bookmark(self.index_of_root(0))
        self.assertEqual(self.win.model.undo.undo_label(), "Add Bookmark")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.titles(), ["Page 1", "Page 2", "Page 3", "Page 4"])

    # -- re-home -----------------------------------------------------------

    def test_rehome_points_the_entry_at_the_current_page(self):
        self.reader().go_to_page(3)
        settle(timeout_ms=300)
        self.assertTrue(self.reader().rehome_bookmark(self.index_of_root(0)))
        self.assertEqual(self.outline().roots[0].uid, self.uid(3))

    def test_rehome_keeps_the_title(self):
        """It may have been edited, and need not match anything on the page."""
        self.outline().roots[0].title = "Something I typed"
        self.reader().go_to_page(3)
        settle(timeout_ms=300)
        self.reader().rehome_bookmark(self.index_of_root(0))
        self.assertEqual(self.outline().roots[0].title, "Something I typed")

    def test_rehoming_repairs_a_dangling_entry(self):
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=300)
        self.assertEqual(len(self.outline().dangling()), 1)

        self.reader().go_to_page(0)
        settle(timeout_ms=300)
        self.reader().rehome_bookmark(self.index_of_root(1))
        self.assertEqual(self.outline().dangling(), [])
        self.assertEqual(self.outline().roots[1].title, "Page 2")

    def test_rehoming_to_the_same_page_is_not_an_edit(self):
        self.reader().go_to_page(0)
        settle(timeout_ms=300)
        self.assertFalse(self.reader().rehome_bookmark(self.index_of_root(0)))
        self.assertFalse(self.win.modified)

    # -- rename ------------------------------------------------------------

    def test_rename_is_one_act_and_one_undo_entry(self):
        from PySide6.QtCore import Qt
        model = self.win.reader.bookmarks
        self.assertTrue(model.setData(self.index_of_root(0), "Preface", Qt.EditRole))
        self.assertEqual(self.outline().roots[0].title, "Preface")
        self.assertEqual(self.win.model.undo.undo_label(), "Rename Bookmark")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.outline().roots[0].title, "Page 1")

    def test_a_rename_that_changed_nothing_takes_no_undo_entry(self):
        from PySide6.QtCore import Qt
        model = self.win.reader.bookmarks
        self.assertFalse(model.setData(self.index_of_root(0), "Page 1", Qt.EditRole))
        self.assertFalse(self.win.model.undo.can_undo)
        self.assertFalse(self.win.modified)

    # -- delete ------------------------------------------------------------

    def test_delete_promotes_the_children(self):
        """The Handbook's "1" wrapper, removable without its 800 entries."""
        self.set_outline(Outline([
            Bookmark("1", None, [Bookmark("Handbook", self.uid(0),
                                          [Bookmark("Chapter 1", self.uid(1))]),
                                 Bookmark("Index", self.uid(2))]),
        ]))
        self.assertTrue(self.reader().delete_bookmark(self.index_of_root(0)))
        self.assertEqual(self.titles(), ["Handbook", "  Chapter 1", "Index"])

    def test_the_tree_follows_a_delete_without_being_reset(self):
        """Row signals, not a reset: a reset collapses an 807-entry tree."""
        from PySide6.QtCore import QModelIndex
        self.set_outline(Outline([
            Bookmark("1", None, [Bookmark("Handbook", self.uid(0))]),
        ]))
        model = self.win.reader.bookmarks
        resets = []
        model.modelAboutToBeReset.connect(lambda: resets.append(1))
        self.reader().delete_bookmark(self.index_of_root(0))
        self.assertEqual(model.rowCount(QModelIndex()), 1)
        self.assertEqual(self.index_of_root(0).data(), "Handbook")
        self.assertEqual(model.rowCount(self.index_of_root(0)), 0)
        self.assertEqual(resets, [], "the tree was reset instead of updated")

    def test_a_bookmark_edit_does_not_date_the_rendered_document(self):
        """Only the outline changed. Re-exporting 1590 pages would be absurd."""
        self.assertFalse(self.win._reader_stale)
        self.reader().add_bookmark(self.index_of_root(0))
        self.assertTrue(self.win.modified)
        self.assertFalse(self.win._reader_stale)

    def test_deleting_is_undoable(self):
        self.reader().delete_bookmark(self.index_of_root(1))
        self.assertEqual(self.titles(), ["Page 1", "Page 3", "Page 4"])
        self.assertEqual(self.win.model.undo.undo_label(), "Delete Bookmark")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.titles(), ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_delete_with_children_takes_the_whole_subtree(self):
        self.set_outline(Outline([
            Bookmark("Chapter 1", self.uid(0),
                     [Bookmark("1.1", self.uid(1)), Bookmark("1.2", self.uid(2))]),
            Bookmark("Chapter 2", self.uid(3)),
        ]))
        self.assertTrue(self.reader().delete_bookmark_tree(self.index_of_root(0)))
        self.assertEqual(self.titles(), ["Chapter 2"])
        self.assertEqual(self.win.model.undo.undo_label(),
                         "Delete Bookmark and Children")

    def test_delete_with_children_is_undoable(self):
        self.set_outline(Outline([
            Bookmark("Chapter 1", self.uid(0), [Bookmark("1.1", self.uid(1))]),
        ]))
        self.reader().delete_bookmark_tree(self.index_of_root(0))
        self.assertEqual(self.titles(), [])
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.titles(), ["Chapter 1", "  1.1"])

    def test_delete_and_delete_with_children_differ_only_in_the_children(self):
        """Which is the whole point of having both."""
        def fresh():
            self.set_outline(Outline([
                Bookmark("1", None, [Bookmark("Handbook", self.uid(0))]),
            ]))
        fresh()
        self.reader().delete_bookmark(self.index_of_root(0))
        self.assertEqual(self.titles(), ["Handbook"])
        fresh()
        self.reader().delete_bookmark_tree(self.index_of_root(0))
        self.assertEqual(self.titles(), [])

    def test_delete_with_children_is_off_on_a_leaf(self):
        """There it would be Delete under another name."""
        self.set_outline(Outline([
            Bookmark("Leaf", self.uid(0)),
            Bookmark("Branch", self.uid(1), [Bookmark("Twig", self.uid(2))]),
        ]))
        for row, expected in ((0, False), (1, True)):
            menu = self.reader().build_outline_menu(self.index_of_root(row))
            self.addCleanup(menu.deleteLater)
            action = [a for a in menu.actions()
                      if a.text() == "Delete with Children"][0]
            self.assertEqual(action.isEnabled(), expected)

    # -- delete dangling ---------------------------------------------------

    def test_delete_dangling_leaves_headings_alone(self):
        """A heading points nowhere on purpose. Eating it would be the bug."""
        self.set_outline(Outline([
            Bookmark("Part One", None),
            Bookmark("Lost", None, wanted_target=True),
            Bookmark("Page 1", self.uid(0)),
        ]))
        self.assertEqual(self.reader().delete_dangling_bookmarks(), 1)
        self.assertEqual(self.titles(), ["Part One", "Page 1"])

    def test_delete_dangling_promotes_children_too(self):
        self.set_outline(Outline([
            Bookmark("Lost", None, wanted_target=True,
                     children=[Bookmark("Kept", self.uid(0))]),
        ]))
        self.reader().delete_dangling_bookmarks()
        self.assertEqual(self.titles(), ["Kept"])

    def test_nested_dangling_entries_all_go(self):
        self.set_outline(Outline([
            Bookmark("Lost", None, wanted_target=True,
                     children=[Bookmark("Also lost", None, wanted_target=True),
                               Bookmark("Kept", self.uid(0))]),
        ]))
        self.assertEqual(self.reader().delete_dangling_bookmarks(), 2)
        self.assertEqual(self.titles(), ["Kept"])

    def test_delete_dangling_is_one_undo_entry_for_the_lot(self):
        self.win.view.set_selected_rows([1, 2])
        self.win.delete_selected()
        settle(timeout_ms=300)
        self.assertEqual(self.reader().delete_dangling_bookmarks(), 2)
        self.assertEqual(self.titles(), ["Page 1", "Page 4"])
        self.assertEqual(self.win.model.undo.undo_label(),
                         "Delete Dangling Bookmarks")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(len(self.outline()), 4)

    def test_delete_dangling_does_nothing_when_nothing_dangles(self):
        self.assertEqual(self.reader().delete_dangling_bookmarks(), 0)
        self.assertFalse(self.win.modified)

    # -- the menu ----------------------------------------------------------

    def test_the_menu_offers_the_commands(self):
        menu = self.reader().build_outline_menu(self.index_of_root(0))
        self.addCleanup(menu.deleteLater)
        self.assertEqual([a.text() for a in menu.actions() if not a.isSeparator()],
                         ["Add Bookmark Here", "Add Child Bookmark Here",
                          "Re-home to This Page", "Rename", "Delete",
                          "Delete with Children", "Delete Dangling Bookmarks"])

    def test_commands_needing_an_entry_are_off_over_empty_space(self):
        from PySide6.QtCore import QModelIndex
        menu = self.reader().build_outline_menu(QModelIndex())
        self.addCleanup(menu.deleteLater)
        enabled = {a.text(): a.isEnabled()
                   for a in menu.actions() if not a.isSeparator()}
        self.assertTrue(enabled["Add Bookmark Here"])
        self.assertFalse(enabled["Add Child Bookmark Here"])
        self.assertFalse(enabled["Re-home to This Page"])
        self.assertFalse(enabled["Rename"])
        self.assertFalse(enabled["Delete"])

    def test_delete_dangling_is_off_until_something_dangles(self):
        menu = self.reader().build_outline_menu(self.index_of_root(0))
        self.addCleanup(menu.deleteLater)
        off = [a for a in menu.actions()
               if a.text() == "Delete Dangling Bookmarks"][0]
        self.assertFalse(off.isEnabled())

        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=300)
        menu = self.reader().build_outline_menu(self.index_of_root(0))
        self.addCleanup(menu.deleteLater)
        on = [a for a in menu.actions()
              if a.text() == "Delete Dangling Bookmarks"][0]
        self.assertTrue(on.isEnabled())


class TestOutlineSurvivesASave(unittest.TestCase):
    """Edit, save, reload: the tree comes back (D20, step 8).

    The test the whole design exists for. Until the outline was written on save
    every bookmark command worked, marked the document modified, undid
    correctly -- and was discarded by the next save, which rebuilt the outline
    from the source files. A feature that lies is worse than one that is
    missing, so this is an end-to-end round trip rather than a unit test of the
    writer.
    """

    def setUp(self):
        import tempfile
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, ignore_errors=True)
        self.out = os.path.join(self.dir, "saved.pdf")
        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def save(self):
        self.assertTrue(self.win._write([self.out], self.win.model.pages,
                                        outline=self.win.model.outline),
                        "the save failed")

    def reload(self):
        """Open the saved file in a fresh window and return its outline."""
        from pdfarranger_qt.mainwindow import MainWindow
        second = MainWindow()
        self.addCleanup(second.close)
        second.modified = False
        second.open_paths([self.out])
        settle(timeout_ms=400)
        self.addCleanup(setattr, second, "modified", False)
        return second.model.outline

    def titles(self, outline):
        return [f"{'  ' * d}{b.title}" for d, b in outline.walk()]

    def test_an_unedited_outline_round_trips(self):
        self.save()
        self.assertEqual(self.titles(self.reload()),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_a_rename_survives(self):
        from PySide6.QtCore import QModelIndex, Qt
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        index = self.win.reader.bookmarks.index(0, 0, QModelIndex())
        self.win.reader.bookmarks.setData(index, "Preface", Qt.EditRole)
        self.save()
        self.assertEqual(self.titles(self.reload())[0], "Preface")

    def test_a_delete_survives(self):
        self.win.model.outline.remove(self.win.model.outline.roots[1])
        self.save()
        self.assertEqual(self.titles(self.reload()),
                         ["Page 1", "Page 3", "Page 4"])

    def test_nesting_survives(self):
        outline = self.win.model.outline
        second = outline.roots[1]
        outline.move(second, outline.roots[0], 0)
        self.save()
        self.assertEqual(self.titles(self.reload()),
                         ["Page 1", "  Page 2", "Page 3", "Page 4"])

    def test_each_bookmark_still_points_at_its_own_page(self):
        """A uid became a position; the position has to be the right one."""
        outline = self.win.model.outline
        outline.move(outline.roots[0], None, len(outline.roots))   # goes last
        self.save()
        reloaded = self.reload()
        self.assertEqual([b.title for _d, b in reloaded.walk()],
                         ["Page 2", "Page 3", "Page 4", "Page 1"])
        # Reading the saved file back resolves each destination afresh, so a
        # bookmark that came back with a uid at all landed on a real page.
        for _depth, item in reloaded.walk():
            self.assertIsNotNone(item.uid, item.title)

    def test_the_within_page_position_is_kept(self):
        """Dropping it would flatten every bookmark to the top of its page."""
        outline = self.win.model.outline
        outline.roots[0].view = ("XYZ", 100.0, 700.0, None)
        self.save()
        reloaded = self.reload()
        self.assertEqual(reloaded.roots[0].view[0], "XYZ")
        self.assertEqual(reloaded.roots[0].view[1], 100.0)
        self.assertEqual(reloaded.roots[0].view[2], 700.0)

    def test_a_heading_comes_back_as_a_heading(self):
        from pdfarranger_qt.outline import Bookmark
        self.win.model.outline.roots.insert(0, Bookmark("Part One", None))
        self.save()
        reloaded = self.reload()
        self.assertEqual(reloaded.roots[0].title, "Part One")
        self.assertTrue(reloaded.roots[0].heading)
        self.assertFalse(reloaded.roots[0].dangling)

    def test_a_dangling_entry_comes_back_as_a_heading(self):
        """The one loss the design accepts, pinned down so it stays narrow.

        There is no valid way to write "points at a page that no longer
        exists", so it is written without a destination -- which is what a
        heading is. The title survives, which is the part worth keeping.
        """
        self.win.view.set_selected_rows([1])
        self.win.delete_selected()
        settle(timeout_ms=300)
        self.assertEqual([b.title for b in self.win.model.outline.dangling()],
                         ["Page 2"])
        self.save()
        reloaded = self.reload()
        entry = [b for _d, b in reloaded.walk() if b.title == "Page 2"][0]
        self.assertTrue(entry.heading)
        self.assertEqual(reloaded.dangling(), [])

    def test_an_exported_selection_keeps_only_what_it_can(self):
        """Pruned: the entries whose pages went, and their edits, come along."""
        from PySide6.QtCore import QModelIndex, Qt
        self.win.set_read_mode(True)
        settle(timeout_ms=400)
        index = self.win.reader.bookmarks.index(0, 0, QModelIndex())
        self.win.reader.bookmarks.setData(index, "Preface", Qt.EditRole)

        part = os.path.join(self.dir, "part.pdf")
        self.win._write([part], self.win.model.pages[:2], mark_saved=False,
                        outline=self.win.model.outline)
        from pdfarranger_qt.mainwindow import MainWindow
        second = MainWindow()
        self.addCleanup(second.close)
        second.modified = False
        second.open_paths([part])
        settle(timeout_ms=400)
        self.addCleanup(setattr, second, "modified", False)
        self.assertEqual(len(second.model.pages), 2)
        self.assertEqual(self.titles(second.model.outline), ["Preface", "Page 2"],
                         "a selection kept a bookmark with nowhere to point, "
                         "or exported a stale title")


class TestDragToReNest(unittest.TestCase):
    """Drag inside the outline tree (D20, the ninth step).

    Driven through the model's drop handler rather than by synthesising drag
    events: what is worth testing is where an entry lands and that one drag is
    one undo entry, and Qt's drag machinery is not ours to prove.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.set_read_mode(True)
        settle(timeout_ms=500)
        self.win.modified = False
        self.model = self.win.reader.bookmarks

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def outline(self):
        return self.win.model.outline

    def titles(self):
        return [f"{'  ' * d}{b.title}" for d, b in self.outline().walk()]

    def root(self, row):
        from PySide6.QtCore import QModelIndex
        return self.model.index(row, 0, QModelIndex())

    def drop(self, source_row, row, parent):
        """Drag the root entry at ``source_row`` to ``(row, parent)``."""
        from PySide6.QtCore import Qt
        data = self.model.mimeData([self.root(source_row)])
        return self.model.dropMimeData(data, Qt.MoveAction, row, 0, parent)

    # -- what a drop carries -----------------------------------------------

    def test_a_path_survives_the_round_trip(self):
        from PySide6.QtCore import Qt
        self.outline().move(self.outline().roots[1], self.outline().roots[0], 0)
        self.model.set_outline(self.outline())
        nested = self.model.index(0, 0, self.root(0))
        data = self.model.mimeData([nested])
        self.assertEqual(self.model._dragged(data).title, "Page 2")
        del Qt

    # -- nesting -----------------------------------------------------------

    def test_dropping_onto_an_entry_nests_it(self):
        """row < 0 is Qt for "onto this one rather than between two"."""
        self.assertTrue(self.drop(1, -1, self.root(0)))
        self.assertEqual(self.titles(),
                         ["Page 1", "  Page 2", "Page 3", "Page 4"])

    def test_dropping_between_siblings_reorders(self):
        from PySide6.QtCore import QModelIndex
        self.assertTrue(self.drop(0, 3, QModelIndex()))
        self.assertEqual(self.titles(), ["Page 2", "Page 3", "Page 1", "Page 4"])

    def test_a_drag_forward_lands_where_it_was_dropped(self):
        """beginMoveRows and Outline.move both adjust; doing it twice was a bug
        waiting to happen, and this is the case that would have caught it."""
        from PySide6.QtCore import QModelIndex
        self.drop(0, 4, QModelIndex())
        self.assertEqual(self.titles(), ["Page 2", "Page 3", "Page 4", "Page 1"])

    def test_a_nested_entry_can_come_back_out(self):
        from PySide6.QtCore import QModelIndex
        self.drop(1, -1, self.root(0))
        self.assertEqual(self.titles()[1], "  Page 2")
        data = self.model.mimeData([self.model.index(0, 0, self.root(0))])
        from PySide6.QtCore import Qt
        self.assertTrue(self.model.dropMimeData(data, Qt.MoveAction, 1, 0,
                                                QModelIndex()))
        self.assertEqual(self.titles(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_children_travel_with_their_parent(self):
        self.drop(1, -1, self.root(0))          # Page 2 under Page 1
        self.assertTrue(self.drop(0, -1, self.root(1)))   # Page 1 under Page 3
        self.assertEqual(self.titles(),
                         ["Page 3", "  Page 1", "    Page 2", "Page 4"])

    # -- what is refused ---------------------------------------------------

    def test_an_entry_cannot_be_dropped_into_its_own_subtree(self):
        """It would detach the subtree from the tree and lose it."""
        from PySide6.QtCore import Qt
        self.drop(1, -1, self.root(0))          # Page 2 under Page 1
        child = self.model.index(0, 0, self.root(0))
        data = self.model.mimeData([self.root(0)])
        self.assertFalse(self.model.canDropMimeData(data, Qt.MoveAction, -1, 0,
                                                    child))
        self.assertFalse(self.model.dropMimeData(data, Qt.MoveAction, -1, 0,
                                                 child))
        self.assertEqual(self.titles()[:2], ["Page 1", "  Page 2"])

    def test_dropping_an_entry_where_it_already_is_does_nothing(self):
        from PySide6.QtCore import Qt, QModelIndex
        data = self.model.mimeData([self.root(1)])
        for row in (1, 2):
            self.assertFalse(self.model.canDropMimeData(data, Qt.MoveAction,
                                                        row, 0, QModelIndex()))
        self.assertFalse(self.win.modified, "a no-op drop marked the document")

    # -- the document ------------------------------------------------------

    def test_a_drag_is_one_undo_entry(self):
        self.drop(1, -1, self.root(0))
        self.assertEqual(self.win.model.undo.undo_label(), "Move Bookmark")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.titles(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_a_drag_marks_the_document_modified(self):
        self.drop(1, -1, self.root(0))
        self.assertTrue(self.win.modified)

    def test_the_tree_is_not_reset_by_a_drag(self):
        resets = []
        self.model.modelAboutToBeReset.connect(lambda: resets.append(1))
        self.drop(1, -1, self.root(0))
        self.assertEqual(resets, [], "the tree was reset instead of moved")


class TestClosingADocument(unittest.TestCase):
    """The outline goes with the document it came from.

    It is not derived from the page list any more (D20), so emptying the pages
    does not empty it: closing a file left its whole tree sitting in the
    sidebar, still editable, still saveable into the next document opened.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        self.win.set_read_mode(True)
        settle(timeout_ms=500)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_the_fixture_has_an_outline_to_begin_with(self):
        self.assertEqual(len(self.win.model.outline), 4)
        self.assertEqual(self.win.reader.outline_labels(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_closing_empties_the_outline(self):
        self.win.close_document()
        settle(timeout_ms=300)
        self.assertEqual(len(self.win.model.outline), 0)

    def test_closing_empties_the_sidebar(self):
        from PySide6.QtCore import QModelIndex
        self.win.close_document()
        settle(timeout_ms=300)
        self.assertEqual(self.win.reader.outline_labels(), [])
        self.assertEqual(self.win.reader.bookmarks.rowCount(QModelIndex()), 0)
        self.assertFalse(self.win.reader.has_outline())

    def test_opening_another_document_replaces_the_outline(self):
        """Not concatenates -- open replaces, import is what adds."""
        self.win.open_paths([OUTLINE_PDF])
        settle(timeout_ms=500)
        self.assertEqual(self.win.reader.outline_labels(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])
        self.assertEqual(len(self.win.model.outline), 4)


class TestMovingPagesALongWay(unittest.TestCase):
    """Move to Start / End / Page, and why they are not cut and paste.

    David's case: relocating one page in a 1300 page book without scrolling to
    the far end. Cut and paste can do the move, but a pasted page is a *new*
    page with a new uid (D20) -- so its bookmarks stay behind, dangling, which
    is what he found. These commands move the pages themselves, so identity and
    bookmarks survive. That is the property worth testing, not the arithmetic.
    """

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(900, 700)
        self.win.show()
        self.win.open_paths([OUTLINE_PDF])
        settle(timeout_ms=400)
        self.win.modified = False

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def uids(self):
        return [p.uid for p in self.win.model.pages]

    def titles(self):
        return [b.title for _d, b in self.win.model.outline.walk()]

    # -- where the pages land ---------------------------------------------

    def test_move_to_start(self):
        before = self.uids()
        self.win.view.set_selected_rows([3])
        self.win.move_to_start()
        self.assertEqual(self.uids(),
                         [before[3], before[0], before[1], before[2]])

    def test_move_to_end(self):
        before = self.uids()
        self.win.view.set_selected_rows([0])
        self.win.move_to_end()
        self.assertEqual(self.uids(),
                         [before[1], before[2], before[3], before[0]])

    def test_a_page_becomes_the_number_asked_for(self):
        """Forwards, where "becomes page N" and "lands before page N" differ."""
        before = self.uids()
        self.win.view.set_selected_rows([0])
        self.win._move_selection_to(2)          # becomes page 3
        self.assertEqual(self.uids().index(before[0]), 2)

    def test_it_becomes_that_number_going_backwards_too(self):
        before = self.uids()
        self.win.view.set_selected_rows([3])
        self.win._move_selection_to(1)          # becomes page 2
        self.assertEqual(self.uids().index(before[3]), 1)

    def test_a_block_stays_together_and_in_order(self):
        before = self.uids()
        self.win.view.set_selected_rows([0, 1])
        self.win.move_to_end()
        self.assertEqual(self.uids()[-2:], [before[0], before[1]])

    def test_asking_past_the_end_lands_at_the_end(self):
        before = self.uids()
        self.win.view.set_selected_rows([0])
        self.win._move_selection_to(999)
        self.assertEqual(self.uids()[-1], before[0])

    # -- the point of the exercise ----------------------------------------

    def test_the_bookmarks_come_along(self):
        """The reason these exist rather than cut and paste."""
        self.win.view.set_selected_rows([3])
        self.win.move_to_start()
        settle(timeout_ms=200)
        self.assertEqual(self.win.model.outline.dangling(), [],
                         "moving a page stranded its bookmark")
        self.assertEqual(self.titles(),
                         ["Page 1", "Page 2", "Page 3", "Page 4"])

    def test_a_page_through_the_clipboard_is_a_new_page(self):
        """Which is why cut and paste is not a move.

        Driven through the clipboard *codec* and the model, not through
        QClipboard: the offscreen platform does not keep what is put on it, so
        `copy_selected` fails and `cut_selected` never gets as far as the part
        under test. The path exercised here is the one paste actually uses.
        """
        from pdfarranger_qt import clipboard
        original = self.win.model.pages[3]
        rebuilt = self.win.docs.pages_from_clipboard(
            clipboard.parse(clipboard.serialize([original])))
        self.assertEqual(len(rebuilt), 1)
        self.assertNotEqual(rebuilt[0].uid, original.uid,
                            "a pasted page kept the original's identity")

    def test_so_a_cut_and_paste_leaves_the_bookmark_behind(self):
        """The behaviour David hit, on record.

        Not a complaint about cut and paste: a pasted page really is a new page
        (D20), the clipboard is a cross-process byte format (D5), and bookmarks
        staying with the original is the same rule that stops Duplicate
        duplicating them. It is simply not a move -- and on a document too long
        to scroll, a move is what you wanted.
        """
        from pdfarranger_qt import clipboard
        original = self.win.model.pages[3]
        rebuilt = self.win.docs.pages_from_clipboard(
            clipboard.parse(clipboard.serialize([original])))

        self.win.view.set_selected_rows([3])
        self.win.delete_selected()               # what a cut does to the list
        settle(timeout_ms=200)
        self.assertEqual([b.title for b in self.win.model.outline.dangling()],
                         ["Page 4"])

        self.win.model.insert_pages(0, rebuilt)  # and what a paste does
        settle(timeout_ms=200)
        self.assertEqual(len(self.win.model.pages), 4)
        self.assertEqual([b.title for b in self.win.model.outline.dangling()],
                         ["Page 4"], "the pasted page reconnected the bookmark")

    # -- the document ------------------------------------------------------

    def test_a_move_is_one_undo_entry(self):
        before = self.uids()
        self.win.view.set_selected_rows([3])
        self.win.move_to_start()
        self.assertEqual(self.win.model.undo.undo_label(), "Move")
        self.win.undo()
        settle(timeout_ms=300)
        self.assertEqual(self.uids(), before)

    def test_moving_marks_the_document_modified(self):
        self.win.view.set_selected_rows([3])
        self.win.move_to_start()
        self.assertTrue(self.win.modified)

    def test_moving_a_page_to_where_it_already_is_does_nothing(self):
        self.win.view.set_selected_rows([1])
        self.win._move_selection_to(1)
        self.assertFalse(self.win.modified)
        self.assertFalse(self.win.model.undo.can_undo)

    def test_the_commands_need_a_selection(self):
        self.win.view.set_selected_rows([])
        self.win.move_to_start()
        self.win.move_to_end()
        self.assertFalse(self.win.modified)

    def test_they_are_on_the_grids_context_menu(self):
        """Right-click is where the selection already is."""
        labels = [a.text() for a in self.win.view.actions()]
        for wanted in ("Move to Start", "Move to End", "Move to Page…"):
            self.assertIn(wanted, labels)
