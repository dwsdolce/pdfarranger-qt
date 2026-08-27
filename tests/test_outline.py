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
