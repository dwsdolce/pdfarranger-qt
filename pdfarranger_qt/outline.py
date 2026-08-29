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

"""An outline the document owns, so bookmarks can be edited (D20).

Upstream has none of this: `exporter_outlines.py` only *preserves* an outline
through an export, deriving it at save time by reading the source files back.
There is nowhere in that arrangement to put an edit, which is why this exists.

What a bookmark points at is the whole design. It holds a page **uid** -- an
identity assigned once and carried across `Page.duplicate()`, so it survives
the wholesale rebuild `UndoManager.snapshot` performs. Not an index, which every
reorder would invalidate and which would mean doing `OutlineRemapper`'s
export-time remapping continuously; not the object, which undo replaces.

Consequences worth stating, because they are the behaviour rather than an
implementation detail:

* Reordering pages costs nothing. Nothing here refers to a position.
* Deleting a page leaves its bookmarks **dangling** rather than deleting them.
  They are skipped when the outline is written, and reconnect if the delete is
  undone -- which is what lets one undo stack cover both.
* Duplicating a page does not duplicate its bookmarks: the copy gets a new uid.
"""

from typing import Iterator, List, Optional

#: Bits of a bookmark's `flags`, mirroring the PDF outline item's `/F`. Checked
#: against pikepdf rather than assumed: italic alone gives 1, bold alone 2, both
#: 3. These two are all the spec defines -- there is no third.
ITALIC = 1
BOLD = 2


class Bookmark:
    """One entry: a title, the page it points at, and its children."""

    __slots__ = ("title", "uid", "children", "wanted_target", "view", "external",
                 "colour", "flags", "closed")

    def __init__(self, title: str, uid: Optional[int] = None,
                 children: Optional[List["Bookmark"]] = None,
                 wanted_target: bool = False, view=None, external=None,
                 colour=None, flags: int = 0, closed: bool = False):
        self.title = title
        self.uid = uid
        """The page's identity, or None for an entry that points nowhere."""
        self.wanted_target = wanted_target or uid is not None
        """Whether this entry ever declared a destination.

        Four states now, and the differences matter: *targeted* has a uid;
        *external* has `external` set and points outside this document;
        *heading* has none of them, which is legal and deliberate -- the
        Handbook's "1" wrapper is one; *dangling* declared a target that is not
        there.

        A heading must not be swept up by Delete Dangling, and on load the two
        are told apart by whether the file's entry carried a destination at all.
        """
        self.view = view
        """Where on the page to land, as the destination's tail: ``("XYZ", x, y,
        zoom)``, ``("Fit",)`` and so on, or None for the top of the page.

        Kept because dropping it throws data away: a bookmark into the middle of
        a page comes back pointing at the top of it, on every bookmark in a book
        that had them. The *page* still comes from the uid, so reordering costs
        nothing (D20); only the position within it is remembered here.

        Re-homing clears it -- a position on the old page means nothing on the
        new one -- and Add sets it from the selection, so a bookmark made from a
        heading lands on that heading rather than at the top of its page.
        """
        self.external = external
        """An opaque destination *outside* this document, written back verbatim.

        `/GoToR` into a companion file, `/URI`, `/Launch`, `/GoToE`. There is
        nothing here to resolve and nothing to remap, but they are perfectly
        good bookmarks: treating "no in-document destination" as "no
        destination" once deleted 18,131 of the ARRL Handbook's 18,179
        bookmarks and took the tree structure with them.

        Opaque on purpose -- this module never looks inside it, which is what
        keeps the module free of pikepdf. The writer knows what it is.
        """
        self.colour = colour
        """``(r, g, b)`` in 0..1, or None for the viewer's default.

        The PDF outline item's `/C`. pikepdf has no API for it -- `OutlineItem`
        offers `bold`, `italic` and `is_closed` and nothing else -- so it has to
        be written into the raw dictionary, which is why it was the easiest of
        the three to lose.
        """
        self.flags = flags
        """`/F`, a bitfield: **1 is italic, 2 is bold**, so 3 is both.

        Those two bits are all the spec defines; there is no third.
        """
        self.closed = closed
        """Whether the entry is collapsed when the document is opened.

        Stored in the *sign* of `/Count`, not as a key of its own, which is why
        it used to survive an export by accident while colour and flags did not.

        This is the state the **file** carries, not what happens to be expanded
        in the sidebar. Browsing an outline must not modify the document.
        """
        self.children: List["Bookmark"] = list(children or [])

    @property
    def dangling(self) -> bool:
        """Declared a target that cannot be honoured.

        An external entry is *not* dangling: it points at another file, which is
        somewhere, and it resolves fine when followed. Before `external`
        existed they were indistinguishable, so every one of the Handbook's
        cross-file bookmarks showed greyed in the sidebar saying its page had
        gone -- which was never true.
        """
        return (self.uid is None and self.wanted_target
                and self.external is None)

    @property
    def heading(self) -> bool:
        """Points nowhere, and never did."""
        return (self.uid is None and not self.wanted_target
                and self.external is None)

    @property
    def points_outside(self) -> bool:
        """Targets another file, the web, or an application."""
        return self.external is not None

    def duplicate(self) -> "Bookmark":
        return Bookmark(self.title, self.uid,
                        [child.duplicate() for child in self.children],
                        self.wanted_target, self.view, self.external,
                        self.colour, self.flags, self.closed)

    def walk(self, depth: int = 0) -> Iterator[tuple]:
        """Every entry in reading order, as ``(depth, bookmark)``."""
        yield depth, self
        for child in self.children:
            yield from child.walk(depth + 1)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Bookmark({self.title!r}, uid={self.uid}, {len(self.children)} children)"


class Outline:
    """The document's bookmark tree.

    A plain container: the tree, and the operations that move parts of it about.
    It knows nothing about pikepdf or Qt, which keeps the awkward parts -- what
    survives an edit, what a dangling entry means -- testable without either.
    """

    def __init__(self, roots: Optional[List[Bookmark]] = None):
        self.roots: List[Bookmark] = list(roots or [])

    # -- copying -----------------------------------------------------------

    def duplicate(self) -> "Outline":
        """A deep copy, for the undo snapshot the page list is taking anyway."""
        return Outline([root.duplicate() for root in self.roots])

    def __bool__(self):
        return bool(self.roots)

    def __len__(self):
        return sum(1 for _ in self.walk())

    # -- reading -----------------------------------------------------------

    def walk(self) -> Iterator[tuple]:
        """Every entry in reading order, as ``(depth, bookmark)``."""
        for root in self.roots:
            yield from root.walk()

    def parent_of(self, target: Bookmark) -> Optional[Bookmark]:
        """The entry ``target`` hangs from, or None if it is a root."""
        for _depth, item in self.walk():
            if target in item.children:
                return item
        return None

    def siblings_of(self, target: Bookmark) -> Optional[List[Bookmark]]:
        """The list ``target`` lives in, roots included. None if it is absent."""
        if target in self.roots:
            return self.roots
        parent = self.parent_of(target)
        return parent.children if parent is not None else None

    def orphan(self, live_uids) -> List[Bookmark]:
        """Detach entries whose page has gone, and return them.

        Called after a page delete. The entry is *kept* -- marked dangling, so
        it can be re-homed -- because whatever is in the outline gets saved, and
        because its title may have been edited into something worth keeping.
        Undoing the delete restores the uid along with the page, since both come
        off the same snapshot.
        """
        live = set(live_uids)
        lost = [item for _depth, item in self.walk()
                if item.uid is not None and item.uid not in live]
        for item in lost:
            item.uid = None          # wanted_target stays True: now dangling
        return lost

    def dangling(self) -> List[Bookmark]:
        """Entries that asked for a page and did not get one.

        Not headings, which point nowhere on purpose -- Delete Dangling must
        leave those alone or it would eat the Handbook's "1" wrapper.
        """
        return [item for _depth, item in self.walk() if item.dangling]

    # -- editing -----------------------------------------------------------

    def add(self, title: str, uid: Optional[int], parent: Optional[Bookmark] = None,
            index: Optional[int] = None, view=None) -> Bookmark:
        """Insert a new entry and return it."""
        item = Bookmark(title, uid, view=view)
        siblings = self.roots if parent is None else parent.children
        siblings.insert(len(siblings) if index is None else index, item)
        return item

    def remove(self, target: Bookmark) -> bool:
        """Delete an entry. Its children are promoted into its place.

        Promoting rather than deleting: removing a chapter heading should not
        silently discard the sections under it, and a user who wants them gone
        can say so.
        """
        siblings = self.siblings_of(target)
        if siblings is None:
            return False
        at = siblings.index(target)
        siblings[at:at + 1] = target.children
        target.children = []
        return True

    def remove_subtree(self, target: Bookmark) -> bool:
        """Delete an entry *and everything under it*.

        The other half of `remove`, which promotes. Promotion is right for
        unwrapping -- lifting a book out of the container node it arrived in --
        and useless for the opposite job, throwing away a chapter along with its
        sections. Doing that by promoting first and then deleting each child in
        turn would be one undo entry per bookmark and a great deal of clicking.
        """
        siblings = self.siblings_of(target)
        if siblings is None:
            return False
        siblings.remove(target)
        return True

    def deduplicate(self) -> int:
        """Drop top-level subtrees that repeat one already kept. Returns how many.

        A book shipped one chapter per file puts the *complete* outline in every
        file, so the Handbook merged from 45 chapters carries 45 copies of the
        same tree. This is the same rule as `exporter_outlines.deduplicate_
        outlines`, moved to read time: collapsing them where the user can see
        and edit the result beats doing it invisibly on save, and once the
        outline is ours the save no longer rebuilds anything to dedupe.

        Only exact matches go. A subtree is compared on its whole shape -- every
        descendant's depth, title and target -- because the alternative is
        silently deleting a bookmark that pointed somewhere else.
        """
        def target(item):
            if item.uid is not None:
                return item.uid
            if item.external is not None:
                return ("outside", repr(item.external))
            return None

        def signature(item, depth=0):
            parts = [(depth, item.title, target(item))]
            for child in item.children:
                parts.extend(signature(child, depth + 1))
            return parts

        seen, keep = set(), []
        for item in self.roots:
            descendants = tuple(signature(item)[1:])
            if descendants:
                # Each copy's own root points at its own file's first page, so
                # it differs between copies even when everything below matches.
                # The body is what identifies the tree.
                key = ("tree", descendants)
            else:
                key = ("leaf", item.title, target(item))
            if key in seen:
                continue
            seen.add(key)
            keep.append(item)
        removed = len(self.roots) - len(keep)
        if removed:
            self.roots[:] = keep
        return removed

    def move(self, target: Bookmark, parent: Optional[Bookmark],
             index: int) -> bool:
        """Re-nest or reorder an entry, children and all.

        Refuses to move an entry into its own subtree, which would detach it
        from the outline entirely and lose it.
        """
        if parent is not None and any(item is parent
                                      for _d, item in target.walk()):
            return False
        siblings = self.siblings_of(target)
        if siblings is None:
            return False
        at = siblings.index(target)
        destination = self.roots if parent is None else parent.children
        if destination is siblings and at < index:
            index -= 1          # removing first shifts everything after it
        siblings.pop(at)
        destination.insert(max(0, min(index, len(destination))), target)
        return True


def from_pdf_outline(items, page_for_dest) -> Outline:
    """Build an Outline from a pikepdf outline, resolving each destination.

    ``page_for_dest`` turns one item into a page uid, or None when it points
    outside the document or nowhere resolvable. Kept as a callback so this
    module needs no pikepdf and no knowledge of how destinations are shaped.
    """
    def convert(item) -> Bookmark:
        return Bookmark(str(getattr(item, "title", "") or ""),
                        page_for_dest(item),
                        [convert(child) for child in getattr(item, "children", [])])

    return Outline([convert(item) for item in items])
