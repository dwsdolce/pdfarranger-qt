# Copyright (C) 2008-2025 pdfarranger contributors
#
# Redistributed unmodified from the GTK application. `diff` against upstream's
# pdfarranger/exporter_outlines.py should report no differences; keep it that
# way so upstream fixes can be applied directly.
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

"""Rebuild PDF outlines after page reorder, subset, or merge."""

import warnings
import pikepdf
import decimal
import os


def external_target(action, source_names):
    """(file index, page number, dest array) for a repairable `/GoToR`.

    ``source_names`` is the basename of each document being exported, indexed
    the same way as ``pdf_input``. Matching is on the basename alone and case
    insensitive: the path in `/F` is relative to wherever the file used to sit,
    which is not where it sits now.

    Returns None when the action is not a remote jump, names a file that is not
    part of this export, or carries no usable page number.
    """
    if action is None or not source_names:
        return None
    if action.get(pikepdf.Name.S) != pikepdf.Name.GoToR:
        return None
    spec = action.get(pikepdf.Name.F)
    name = None
    if isinstance(spec, pikepdf.Dictionary):
        name = spec.get(pikepdf.Name.UF) or spec.get(pikepdf.Name.F)
    elif spec is not None:
        name = spec
    if name is None:
        return None
    wanted = os.path.basename(str(name).replace("\\", "/")).casefold()
    for idx, candidate in enumerate(source_names):
        if candidate and os.path.basename(candidate).casefold() == wanted:
            break
    else:
        return None
    dest = action.get(pikepdf.Name.D)
    if not isinstance(dest, pikepdf.Array) or len(dest) < 2:
        return None
    page = dest[0]
    if not isinstance(page, (int, decimal.Decimal, float)):
        return None
    return idx, int(page), dest


#: Actions that point somewhere other than a page of this document.
EXTERNAL_ACTIONS = (
    pikepdf.Name.GoToR, pikepdf.Name.URI,
    pikepdf.Name.Launch, pikepdf.Name.GoToE,
)


def action_of(item):
    """An outline item's action, or None."""
    try:
        return item.action
    except (AttributeError, ValueError):
        return None


def is_external_action(action) -> bool:
    """True for an action that leaves this document.

    `/GoToR` (another file), `/URI` (the web), `/Launch` (an application) and
    `/GoToE` (an embedded file) have nothing here to resolve -- but they are
    still perfectly good bookmarks. Treating "no in-document destination" as
    "no destination" once deleted 18,131 of the ARRL Handbook's 18,179
    bookmarks and took the tree structure with them.
    """
    if action is None:
        return False
    return action.get(pikepdf.Name.S) in EXTERNAL_ACTIONS


def view_of(dest):
    """A destination's view -- everything after the page -- as plain Python.

    ``("XYZ", 100.0, 700.0, None)``, ``("Fit",)`` and so on, or None when there
    is nothing to say. The *page* is not in here: that comes from the bookmark's
    page uid, so reordering stays free (D20) and only the position on the page
    is remembered.

    Plain values rather than pikepdf objects, so `outline.py` can hold one
    without importing pikepdf and an undo snapshot can copy it.
    """
    if not isinstance(dest, pikepdf.Array) or len(dest) < 2:
        return None
    tail = []
    for value in dest[1:]:
        if isinstance(value, pikepdf.Name):
            tail.append(str(value).lstrip("/"))
        else:
            try:
                tail.append(float(value))
            except (TypeError, ValueError):
                tail.append(None)
    return tuple(tail) or None


class OutlineRemapper:
    """
    Maps source-file bookmark destinations to their new locations in the output PDF.

    Constructed once per export with the full list of input PDFs and the output
    page sequence. Internally builds:
      - a reverse map from each source page's object identity to its source index
      - a forward map from (file_idx, source_page_idx, copy_number) to output page index
      - a cache of named destinations per source file

    When a source page appears multiple times in the output, bookmarks always
    resolve to the first copy (copy_number=0). Subsequent copies are not bookmarked.
    """

    def __init__(self, pdf_input, pdf_output, pages):
        """Build page index maps and destination caches from the input PDFs."""
        self.pdf_input = pdf_input
        self.pdf_output = pdf_output
        self.pages = pages  # Store pages to access geometry/scale later
        self.rev_maps = {}
        self.dest_caches = {}
        self.new_named_dests = []
        self.page_index_map = {}
        instance_counts = {}
        for out_idx, row in enumerate(pages):
            file_idx = row.nfile - 1
            src_page_idx = row.npage - 1
            key = (file_idx, src_page_idx)
            inst_num = instance_counts.get(key, 0)
            # Map (file_idx, source_page_idx, instance_num) -> output_page_index
            self.page_index_map[(key[0], key[1], inst_num)] = out_idx
            instance_counts[key] = inst_num + 1
        for file_idx, pdf in enumerate(pdf_input):
            if pdf is None:
                continue
            self.rev_maps[file_idx] = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
            dests = {}
            if pikepdf.Name.Dests in pdf.Root:
                for k, v in pdf.Root.Dests.items():
                    dests[str(k).lstrip("/")] = v
            if pikepdf.Name.Names in pdf.Root and pikepdf.Name.Dests in pdf.Root.Names:
                dests.update(dict(pikepdf.NameTree(pdf.Root.Names.Dests).items()))
            self.dest_caches[file_idx] = dests

    def remap_destination(self, file_idx, dest):
        """Remap a bookmark destination to its new location and scale coordinates."""
        original_name = None
        if isinstance(dest, (pikepdf.String, pikepdf.Name)):
            original_name = str(dest).lstrip("/")
            dest_obj = self.dest_caches[file_idx].get(original_name)
            if not dest_obj:
                return None
            try:
                dest_array = dest_obj.D
            except (AttributeError, ValueError):
                dest_array = dest_obj
        else:
            dest_array = dest
        if not isinstance(dest_array, pikepdf.Array) or len(dest_array) < 2:
            return None
        target_ref = dest_array[0]
        if not hasattr(target_ref, "objgen"):
            return None
        source_page_idx = self.rev_maps[file_idx].get(target_ref.objgen)
        if source_page_idx is None:
            return None
        # Target first copy (0) of each page. Other copies are not bookmarked.
        target_out_idx = self.page_index_map.get((file_idx, source_page_idx, 0))
        if target_out_idx is None:
            return None
        # Grab scale from the Row object to transform the bookmark coordinates
        target_page_obj = self.pdf_output.pages[target_out_idx].obj
        row = self.pages[target_out_idx]
        scale = getattr(row, "scale", 1.0)
        return self._new_dest_array(
            dest_array, target_page_obj, file_idx, scale, original_name
        )

    def remap_external_destination(self, target_file_idx, page_number, dest_array):
        """Turn a `/GoToR` destination into an in-document one.

        A remote destination names a *file* and gives a bare integer page index
        into it, rather than pointing at a page object. When that file is one
        of the documents being merged, the page it means is now in the output
        and the link can be repaired -- which is the whole point: publishers
        ship a book as one PDF per chapter, each carrying the complete outline
        with every other chapter as a remote link, so a naive merge leaves
        thousands of links pointing at files that are no longer beside it.

        Returns None when that page was not included in the output, leaving the
        caller to keep the remote link or drop the destination.
        """
        target_out_idx = self.page_index_map.get((target_file_idx, page_number, 0))
        if target_out_idx is None:
            return None
        target_page_obj = self.pdf_output.pages[target_out_idx].obj
        row = self.pages[target_out_idx]
        scale = getattr(row, "scale", 1.0)
        return self._new_dest_array(
            dest_array, target_page_obj, target_file_idx, scale, None
        )

    def _new_dest_array(
        self, dest_array, target_page_obj, file_idx, scale, original_name
    ):
        d_type = dest_array[1]
        coord_indices = []
        if d_type == pikepdf.Name.XYZ:
            coord_indices = [2, 3]  # left, top (zoom ratio at index 4 is not scaled)
        elif d_type in (
            pikepdf.Name.FitH,
            pikepdf.Name.FitBH,
            pikepdf.Name.FitV,
            pikepdf.Name.FitBV,
        ):
            coord_indices = [2]  # [top] or [left]
        elif d_type == pikepdf.Name.FitR:
            coord_indices = [2, 3, 4, 5]  # [left, bottom, right, top]

        items = [target_page_obj, d_type]
        for i in range(2, len(dest_array)):
            val = dest_array[i]
            if i in coord_indices and isinstance(val, (int, float, decimal.Decimal)):
                items.append(float(val) * scale)
            elif isinstance(val, pikepdf.Object) and val.is_indirect:
                items.append(self.pdf_output.copy_foreign(val))
            else:
                items.append(val)  # None (PDF null) is fine here

        new_dest_array = pikepdf.Array(items)
        if original_name:
            new_name_str = f"f{file_idx}-{original_name}"
            self.new_named_dests.append((new_name_str, new_dest_array))
            return pikepdf.String(new_name_str)
        return new_dest_array


class OutlineCopier:
    """Copy outline items from a source PDF, remapping destinations."""

    def __init__(self, remapper, file_idx, source_pdf, pdf_output,
                 source_names=None):
        """Initialize with a remapper and the source file index."""
        self.remapper = remapper
        self.file_idx = file_idx
        self.source_pdf = source_pdf
        self.pdf_output = pdf_output
        #: Basenames of the documents in this export, for repairing `/GoToR`.
        self.source_names = source_names or []

    def _get_mapped_dest(self, source_item):
        """Extract and remap the destination from a source outline item."""
        dest = source_item.destination
        if dest is None and source_item.action:
            if source_item.action.get(pikepdf.Name.S) == pikepdf.Name.GoTo:
                dest = source_item.action.get(pikepdf.Name.D)
        if dest is not None:
            return self.remapper.remap_destination(self.file_idx, dest)
        # A link into another file that is *also* being exported points at a
        # page we now own, so it can be made local.
        external = external_target(source_item.action, self.source_names)
        if external is not None:
            target_idx, page_number, dest_array = external
            return self.remapper.remap_external_destination(
                target_idx, page_number, dest_array)
        return None

    @staticmethod
    def _is_external(source_item):
        """True for bookmarks that point outside this document.

        `/GoToR` (another file), `/URI` (the web), `/Launch` (an application)
        and `/GoToE` (an embedded file) have nothing in this document to remap,
        so there is no destination to resolve -- but they are still perfectly
        good bookmarks and must be kept. Treating "no in-document destination"
        as "no destination" deleted 18,131 of the 18,179 bookmarks in the ARRL
        Handbook, whose subtree is entirely `/GoToR` links to companion PDFs,
        and took the tree structure with them.
        """
        return is_external_action(action_of(source_item))

    def _build_valid_tree(self, source_item):
        """Pass 1: Recursively filter and build a clean Python tree of surviving nodes."""
        final_dest = self._get_mapped_dest(source_item)

        valid_children = []
        for child in source_item.children:
            child_node = self._build_valid_tree(child)
            if child_node is not None:
                valid_children.append(child_node)

        # Kept if it has a valid target, points outside the document, or has
        # surviving children.
        if final_dest is not None or valid_children or self._is_external(source_item):
            return {
                "source_item": source_item,
                "destination": final_dest,
                "children": valid_children,
            }
        return None

    def _insert_tree_node(self, node, pikepdf_parent_list):
        """Pass 2: Insert nodes into the hierarchy using strict parent-first order."""
        source_item = node["source_item"]
        final_dest = node["destination"]

        # 1. Instantiate the temporary OutlineItem object
        copied = self.pdf_output.copy_foreign(
            self.source_pdf.make_indirect(source_item.obj)
        )
        if final_dest is not None and pikepdf.Name.A in copied:
            # pikepdf writes the resolved destination to /Dest. A surviving /A
            # takes precedence in most readers, so a repaired cross-file link
            # would still send them to the file it used to point at.
            del copied[pikepdf.Name.A]

        new_item = pikepdf.OutlineItem(
            title=source_item.title,
            destination=final_dest,
            obj=copied,
        )

        new_item.is_closed = (
            source_item.is_closed or pikepdf.Name.Count not in source_item.obj
        )

        # 3. Append to the parent list
        pikepdf_parent_list.append(new_item)

        # 4. Recursively insert children into the new item's children list
        for child_node in node["children"]:
            self._insert_tree_node(child_node, new_item.children)

    def copy_item(self, source_item, new_parent_list):
        """Copy a single outline item and its children, dropping invalid destinations."""
        node = self._build_valid_tree(source_item)
        if node is not None:
            self._insert_tree_node(node, new_parent_list)


def remap_link_annotations(pdf_input, pdf_output, pages, source_names=None):
    """Point copied link annotations back at pages in the output document.

    `_copy_n_transform` copies each page's `/Annots` along with the page, but a
    link's destination still refers to a page *object in the source document*.
    After the copy that reference resolves to null: the `/Dest` array survives
    with a dead target, which is what makes PDFium report "skipping link with
    invalid page number -1" and what makes every in-document link in a saved
    file do nothing.

    Bookmarks never had this problem because `rebuild_outlines` remaps them
    explicitly. Nothing did the same for annotations. The remapper is the same
    one, so the fix is to run each link's destination through it.

    External links (`/URI`, `/GoToR`) are left alone: they point outside this
    document and have nothing to remap. Links whose target page is not in the
    output -- it was deleted -- have their destination removed, leaving an
    inert annotation rather than one that jumps somewhere arbitrary.
    """
    remapper = OutlineRemapper(pdf_input, pdf_output, pages)
    remapped = dropped = 0

    for out_idx, row in enumerate(pages):
        file_idx = row.nfile - 1
        source_pdf = pdf_input[file_idx]
        if source_pdf is None:
            continue
        try:
            source_page = source_pdf.pages[row.npage - 1]
            out_page = pdf_output.pages[out_idx]
        except IndexError:
            continue
        source_annots = source_page.obj.get(pikepdf.Name.Annots)
        out_annots = out_page.obj.get(pikepdf.Name.Annots)
        if source_annots is None or out_annots is None:
            continue
        # Same page, copied whole, so the arrays correspond element for
        # element. If they somehow do not, leave the page alone rather than
        # rewriting the wrong annotation's destination.
        if len(source_annots) != len(out_annots):
            continue

        for source_annot, out_annot in zip(source_annots, out_annots):
            if source_annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Link:
                continue
            action = source_annot.get(pikepdf.Name.A)
            in_action = False
            dest = source_annot.get(pikepdf.Name.Dest)
            external = external_target(action, source_names)
            if external is not None:
                # A link into a file that is also part of this export.
                target_idx, page_number, dest_array = external
                new_dest = remapper.remap_external_destination(
                    target_idx, page_number, dest_array)
                if new_dest is not None:
                    out_annot.A = pikepdf.Dictionary(
                        S=pikepdf.Name.GoTo, D=new_dest)
                    if pikepdf.Name.Dest in out_annot:
                        del out_annot[pikepdf.Name.Dest]
                    remapped += 1
                continue
            if dest is None and action is not None:
                if action.get(pikepdf.Name.S) != pikepdf.Name.GoTo:
                    continue          # external: nothing of ours to fix
                dest = action.get(pikepdf.Name.D)
                in_action = True
            if dest is None:
                continue

            new_dest = remapper.remap_destination(file_idx, dest)
            if new_dest is None:
                # The target page is not in the output. An annotation pointing
                # at nothing is worse than one pointing nowhere.
                if in_action and pikepdf.Name.A in out_annot:
                    del out_annot[pikepdf.Name.A]
                if pikepdf.Name.Dest in out_annot:
                    del out_annot[pikepdf.Name.Dest]
                dropped += 1
                continue

            if in_action:
                out_annot.A = pikepdf.Dictionary(
                    S=pikepdf.Name.GoTo, D=new_dest)
                if pikepdf.Name.Dest in out_annot:
                    del out_annot[pikepdf.Name.Dest]
            else:
                out_annot.Dest = new_dest
                if pikepdf.Name.A in out_annot:
                    del out_annot[pikepdf.Name.A]
            remapped += 1

    write_named_dests(pdf_output, remapper.new_named_dests)
    return remapped, dropped


def deduplicate_outlines(pdf, titles_only=False):
    """Drop top-level bookmark subtrees that repeat one already kept.

    A book shipped as one PDF per chapter puts the *complete* outline in every
    file, so merging 45 chapters yields 45 copies of the same tree. Once
    `/GoToR` links have been repaired the copies become genuinely identical --
    same titles, same nesting, same destination pages -- and all but the first
    are noise.

    Only exact matches are removed. A subtree is compared on its whole shape:
    every descendant's depth, title and resolved destination page. Anything
    that differs anywhere, however slightly, is kept, because the alternative
    is silently deleting a bookmark that pointed somewhere else.

    ``titles_only`` compares structure and titles but not destinations. That is
    lossy -- two copies of a tree can disagree about where a given entry points,
    and this keeps whichever came first -- so it is never the default. It exists
    because a book can carry copies that agree on 401 of 403 entries, where
    holding on to five near-identical trees serves nobody.

    Returns the number of top-level subtrees removed.
    """
    pages = {page.obj.objgen: n for n, page in enumerate(pdf.pages)}

    def target(item):
        dest = item.destination
        if dest is None and item.action is not None:
            dest = item.action.get(pikepdf.Name.D)
        if isinstance(dest, pikepdf.Array) and len(dest):
            first = dest[0]
            if hasattr(first, "objgen"):
                return pages.get(first.objgen)
            return f"remote:{first}"
        return None

    def signature(item, depth=0):
        parts = [(depth, str(item.title),
                  None if titles_only else target(item))]
        for child in item.children:
            parts.extend(signature(child, depth + 1))
        return parts

    with pdf.open_outline() as outline:
        seen = set()
        keep = []
        for item in outline.root:
            descendants = tuple(signature(item)[1:])
            if descendants:
                # Each copy's own root points at its own file's first page, so
                # it differs between copies even when everything below is the
                # same. The body is what identifies the tree.
                key = ("tree", descendants)
            else:
                # A lone bookmark has no body to compare, so it has to match on
                # what it says and where it goes.
                key = ("leaf", str(item.title), target(item))
            if key in seen:
                continue
            seen.add(key)
            keep.append(item)
        removed = len(outline.root) - len(keep)
        if removed:
            outline.root[:] = keep
    return removed


def write_named_dests(pdf, named_dests):
    """Write a list of (name, dest_array) pairs into the PDF's name tree."""
    if not named_dests:
        return
    if pikepdf.Name.Names not in pdf.Root:
        pdf.Root.Names = pdf.make_indirect(pikepdf.Dictionary())
    if pikepdf.Name.Dests in pdf.Root.Names:
        nt = pikepdf.NameTree(pdf.Root.Names.Dests)
    else:
        nt = pikepdf.NameTree.new(pdf)
        pdf.Root.Names.Dests = nt.obj
    for name_str, dest_array in named_dests:
        nt[name_str] = dest_array


def rebuild_outlines(pdf_input, pdf_output, pages, source_names=None):
    """Rebuild outlines in pdf_output by remapping bookmarks from pdf_input."""
    remapper = OutlineRemapper(pdf_input, pdf_output, pages)
    # preserve first-appearance order of source files, deduplicated
    ordered_file_indices = list(dict.fromkeys(row.nfile - 1 for row in pages))
    with pdf_output.open_outline() as new_outline:
        for file_idx in ordered_file_indices:
            source_pdf = pdf_input[file_idx]
            if source_pdf is None or pikepdf.Name.Outlines not in source_pdf.Root:
                continue
            try:
                with source_pdf.open_outline() as source_outline:
                    copier = OutlineCopier(remapper, file_idx, source_pdf,
                                           pdf_output, source_names)
                    for item in source_outline.root:
                        copier.copy_item(item, new_outline.root)
            except pikepdf.PdfError as e:
                warnings.warn(
                    f"Failed to copy bookmarks from document {file_idx + 1}: {e}"
                )
    if remapper.new_named_dests:
        write_named_dests(pdf_output, remapper.new_named_dests)
    if source_names and len(ordered_file_indices) > 1:
        # Only when several documents contributed, and only for subtrees that
        # match exactly. A book shipped one chapter per file repeats its whole
        # outline in each; after the cross-file links above are repaired those
        # copies are identical, and keeping 45 of them helps nobody.
        deduplicate_outlines(pdf_output)


def read_outline(pdf_input, pages, source_names=None):
    """Read the outline out of the *source* documents, as an editable tree (D20).

    The counterpart of `rebuild_outlines`, which derives an outline at export
    time by reading the sources and remapping their destinations into the
    output. That is right for preserving an outline and useless for editing one:
    there is nowhere to put a change. This reads the same information once, when
    the document is opened, into a tree the document owns.

    Each destination is resolved to a **page uid** rather than a page number.
    See `outline.py`: a uid survives reordering, deleting and undo, and a number
    survives none of them.

    A bookmark whose target page is not in the list -- a page range was imported,
    or the target was deleted before this ran -- arrives with no uid and is
    *dangling*: kept, shown as such, and skipped when the outline is written.
    """
    from .outline import Bookmark, Outline

    # Where each source page ended up, if it did. First copy wins: a duplicated
    # page is a new page with its own identity, and bookmarks stay with the
    # original (D20).
    uid_of = {}
    for row in pages:
        uid_of.setdefault((row.nfile - 1, row.npage - 1), row.uid)

    roots = []
    for file_idx, pdf in enumerate(pdf_input):
        if pdf is None or pikepdf.Name.Outlines not in pdf.Root:
            continue
        rev_map = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
        dests = {}
        if pikepdf.Name.Dests in pdf.Root:
            for k, v in pdf.Root.Dests.items():
                dests[str(k).lstrip("/")] = v
        if pikepdf.Name.Names in pdf.Root and pikepdf.Name.Dests in pdf.Root.Names:
            dests.update(dict(pikepdf.NameTree(pdf.Root.Names.Dests).items()))

        def resolve_named(dest):
            """A named destination followed to the array it stands for."""
            if isinstance(dest, (pikepdf.String, pikepdf.Name)):
                found = dests.get(str(dest).lstrip("/"))
                if not found:
                    return None
                try:
                    return found.D
                except (AttributeError, ValueError):
                    return found
            return dest

        def page_index(dest):
            """The source page a destination names, or None."""
            dest = resolve_named(dest)
            if not isinstance(dest, pikepdf.Array) or len(dest) < 1:
                return None
            target = dest[0]
            if not hasattr(target, "objgen"):
                return None
            return rev_map.get(target.objgen)

        def destination_of(item):
            """The item's own destination, whether direct or inside a `/GoTo`."""
            try:
                dest = item.destination
            except (AttributeError, ValueError):
                dest = None
            if dest is not None:
                return dest
            action = action_of(item)
            if action is not None and action.get(pikepdf.Name.S) == pikepdf.Name.GoTo:
                return action.get(pikepdf.Name.D)
            return None

        def resolve(item, _file_idx=file_idx):
            """``(uid, view, external, declared)`` for one source item.

            Four outcomes, in the order they are tried: a destination in this
            file; a `/GoToR` into a file that is *also* being loaded, which is
            repaired into a local target here rather than at export; a target
            genuinely outside, kept opaquely; and nothing at all, a heading.
            """
            dest = destination_of(item)
            if dest is not None:
                array = resolve_named(dest)
                view = view_of(array)
                index = page_index(dest)
                if index is None:
                    return None, view, None, True     # declared, unresolvable
                return uid_of.get((_file_idx, index)), view, None, True

            action = action_of(item)
            # A jump into a companion file that is part of this document is a
            # local jump once merged. Repairing it *here* rather than at export
            # is what lets the 45 identical copies of a chaptered book's outline
            # be recognised as identical and collapsed -- they only match once
            # their cross-file links resolve to the same pages.
            found = external_target(action, source_names)
            if found is not None:
                target_idx, page_number, dest_array = found
                uid = uid_of.get((target_idx, page_number))
                if uid is not None:
                    return uid, view_of(dest_array), None, True

            if is_external_action(action):
                return None, None, action, True
            return None, None, None, False

        def presentation(item):
            """``(colour, flags, closed)`` -- how the entry is drawn.

            The three attributes a PDF outline item has besides its title and
            target, and all three were being thrown away. `/C` is an RGB triple;
            `/F` is a bitfield where 1 is italic and 2 is bold; collapsed is the
            *sign* of `/Count` rather than a key of its own, which is why it
            used to survive an export by accident while the other two did not.
            """
            colour, flags = None, 0
            obj = getattr(item, "obj", None)
            if obj is not None:
                raw = obj.get(pikepdf.Name.C)
                if isinstance(raw, pikepdf.Array) and len(raw) == 3:
                    try:
                        colour = tuple(float(v) for v in raw)
                    except (TypeError, ValueError):
                        colour = None
                try:
                    flags = int(obj.get(pikepdf.Name.F, 0))
                except (TypeError, ValueError):
                    flags = 0
            return colour, flags, bool(getattr(item, "is_closed", False))

        def convert(item):
            uid, view, external, declared = resolve(item)
            colour, flags, closed = presentation(item)
            return Bookmark(str(item.title or ""), uid,
                            [convert(child) for child in item.children],
                            declared, view, external, colour, flags, closed)

        try:
            with pdf.open_outline() as outline:
                roots.extend(convert(item) for item in outline.root)
        except pikepdf.PdfError as e:
            warnings.warn(f"Could not read bookmarks from document "
                          f"{file_idx + 1}: {e}")
    return Outline(roots)


def write_outline(pdf_output, outline, pages, source_names=None, prune=False):
    """Write the document's own outline into the output (D20).

    The counterpart of `read_outline`, and what replaces `rebuild_outlines`
    once the document owns its bookmarks: the outline that gets saved is the
    one the user edited, not one derived afresh from the source files. Without
    this every bookmark command is undone by the next save.

    Each entry is written from what it holds:

    * a **page uid** becomes that page's position in this export, plus the
      `view` remembered from where it was read -- so a bookmark into the middle
      of a page still lands there, and one that has been re-homed lands at the
      top of its new page because re-homing clears the view.
    * an **external** target is written back as it came. `/GoToR`, `/URI`,
      `/Launch` and `/GoToE` have nothing here to remap; the repairable kind was
      already turned into a local uid when the outline was read.
    * anything else is written **without a destination**, which covers both a
      deliberate heading and an entry whose page has gone. That is the one
      thing a dangling bookmark cannot survive: there is no valid way to write
      "points at a page that no longer exists", so it comes back as a heading.
      A narrow loss, and the alternative -- a private key in the PDF -- is
      worse.

    ``prune`` is for exporting a *subset* of the pages, where most of the tree
    points at pages that are not in the file. The rule: keep an entry only if
    it has a destination here or a kept descendant. So a deliberate heading
    survives if anything under it did, and the crowd of empty headings that
    would otherwise arrive does not. Off for a full save, where a heading is
    kept because the user put it there.
    """
    from . import outline as outline_module

    position = {}
    for index, row in enumerate(pages):
        position.setdefault(row.uid, index)

    def destination(item):
        """The destination array for a local target, or None."""
        index = position.get(item.uid)
        if index is None:
            return None
        array = [pdf_output.pages[index].obj]
        view = item.view or ("Fit",)
        for value in view:
            if isinstance(value, str):
                array.append(pikepdf.Name("/" + value))
            elif value is None:
                array.append(None)
            else:
                array.append(value)
        return pikepdf.Array(array)

    def survives(item):
        """Whether a pruned export keeps this entry."""
        if item.uid is not None and item.uid in position:
            return True
        if item.external is not None:
            return True
        return any(survives(child) for child in item.children)

    def build(item):
        dest, action = None, None
        if item.uid is not None:
            dest = destination(item)
        if dest is None and item.external is not None:
            # Copied rather than referenced: the action belongs to a source
            # document that this output knows nothing about.
            try:
                action = pdf_output.copy_foreign(item.external)
            except Exception:  # noqa: BLE001 - an action we cannot carry over
                action = None
        entry = pikepdf.OutlineItem(item.title, destination=dest, action=action)
        # Bold and italic pikepdf will write for us; the colour it will not, and
        # is dealt with below.
        entry.italic = bool(item.flags & outline_module.ITALIC)
        entry.bold = bool(item.flags & outline_module.BOLD)
        entry.is_closed = bool(item.closed)
        for child in item.children:
            if not prune or survives(child):
                entry.children.append(build(child))
        return entry

    # The tree as it will actually be written, decided once so the colours can
    # be applied afterwards by walking the same shape.
    def keep(items):
        return [(item, keep(item.children))
                for item in items if not prune or survives(item)]

    written = keep(outline.roots)

    with pdf_output.open_outline() as new_outline:
        del new_outline.root[:]
        for item, _children in written:
            new_outline.root.append(build(item))

    # `/C` has no pikepdf API -- OutlineItem offers bold, italic and is_closed
    # and nothing else -- so it goes straight into the dictionaries, walking the
    # tree just written alongside the one it came from.
    def paint(node, items):
        child = node.get(pikepdf.Name.First)
        for item, grandchildren in items:
            if child is None:
                return
            if item.colour is not None:
                child[pikepdf.Name.C] = pikepdf.Array(list(item.colour))
            paint(child, grandchildren)
            child = child.get(pikepdf.Name.Next)

    if pikepdf.Name.Outlines in pdf_output.Root:
        paint(pdf_output.Root.Outlines, written)
