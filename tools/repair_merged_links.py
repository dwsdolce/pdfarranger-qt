#!/usr/bin/env python3
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

"""Repair cross-file links in a PDF that was merged by something else.

Some publishers ship a book as one PDF per chapter, each carrying the complete
outline with every other chapter as a `/GoToR` link into a sibling file. Merge
those with a tool that does not repoint the links -- Acrobat and PDF24 both
leave them alone -- and the result has a full bookmark tree in which nothing
navigates, because the files those links name are no longer beside it.

pdfarranger-qt repairs this when *it* does the merging. This repairs a merge
someone else already did, without needing to redo it.

It works by recovering where each original file's pages landed. Merge tools
normally add one top-level bookmark per input file, named after it, pointing at
that file's first page. Given the folder of originals, that is enough: the
bookmark gives the offset and the original gives the length.

    python tools/repair_merged_links.py MERGED.pdf ORIGINALS_DIR [-o OUT.pdf]
    python tools/repair_merged_links.py MERGED.pdf ORIGINALS_DIR --dry-run

Nothing is written without -o. The input is never modified in place.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pikepdf  # noqa: E402


def source_lengths(directory):
    """{basename: page count} for every PDF in the folder of originals."""
    lengths = {}
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(".pdf"):
            continue
        try:
            with pikepdf.open(os.path.join(directory, name)) as pdf:
                lengths[name] = len(pdf.pages)
        except pikepdf.PdfError as exc:
            print(f"   skipping {name}: {exc}")
    return lengths


def recover_offsets(pdf, lengths):
    """{basename: first page index in the merged file}.

    Read off the top-level bookmarks, whose titles are the original filenames
    (with or without the extension). Verified against the ARRL 2021 Handbook,
    where all 45 match one for one and the page counts add up exactly.
    """
    page_index = {page.obj.objgen: n for n, page in enumerate(pdf.pages)}
    stems = {os.path.splitext(name)[0].casefold(): name for name in lengths}
    offsets = {}
    with pdf.open_outline() as outline:
        for item in outline.root:
            name = stems.get(str(item.title).strip().casefold())
            if name is None:
                continue
            dest = item.destination
            if dest is None and item.action is not None:
                dest = item.action.get(pikepdf.Name.D)
            if not (isinstance(dest, pikepdf.Array) and len(dest)):
                continue
            start = page_index.get(getattr(dest[0], "objgen", None))
            if start is not None:
                offsets[name] = start
    return offsets


def check(offsets, lengths, total):
    """Are the recovered offsets consistent with a plain concatenation?"""
    problems = []
    ordered = sorted(offsets.items(), key=lambda kv: kv[1])
    for (name, start), (_next_name, next_start) in zip(ordered, ordered[1:]):
        if start + lengths[name] != next_start:
            problems.append(
                f"{name}: starts at {start}, is {lengths[name]} pages, but the "
                f"next file starts at {next_start}")
    if ordered:
        last, start = ordered[-1][0], ordered[-1][1]
        if start + lengths[last] != total:
            problems.append(
                f"{last}: starts at {start}, is {lengths[last]} pages, but the "
                f"document has {total}")
    return problems


def repair(pdf, offsets, lengths, dry_run=False):
    """Rewrite every /GoToR naming a known file into a local /GoTo."""
    repaired = out_of_range = unknown = 0

    def fix(obj):
        nonlocal repaired, out_of_range, unknown
        action = obj.get(pikepdf.Name.A)
        if action is None or action.get(pikepdf.Name.S) != pikepdf.Name.GoToR:
            return
        spec = action.get(pikepdf.Name.F)
        raw = None
        if isinstance(spec, pikepdf.Dictionary):
            raw = spec.get(pikepdf.Name.UF) or spec.get(pikepdf.Name.F)
        elif spec is not None:
            raw = spec
        if raw is None:
            return
        name = os.path.basename(str(raw).replace("\\", "/"))
        match = next((k for k in offsets if k.casefold() == name.casefold()), None)
        if match is None:
            unknown += 1
            return
        dest = action.get(pikepdf.Name.D)
        if not (isinstance(dest, pikepdf.Array) and len(dest) >= 2):
            return
        page_number = dest[0]
        if not isinstance(page_number, int):
            return
        if not 0 <= int(page_number) < lengths[match]:
            out_of_range += 1
            return
        target = offsets[match] + int(page_number)
        repaired += 1
        if dry_run:
            return
        new_dest = pikepdf.Array([pdf.pages[target].obj] + list(dest)[1:])
        obj[pikepdf.Name.Dest] = new_dest
        del obj[pikepdf.Name.A]

    # Walk the raw /Outlines tree, not pdf.open_outline(). That context manager
    # rebuilds the outline from its own OutlineItem objects when it exits, which
    # silently discards edits made to the underlying dictionaries -- the first
    # version of this script reported 18,089 repairs and changed nothing.
    root = pdf.Root.get(pikepdf.Name.Outlines)
    if root is not None:
        seen = set()

        def walk(node):
            child = node.get(pikepdf.Name.First)
            while child is not None:
                key = child.objgen
                if key in seen:
                    break           # malformed /Next chain; do not loop forever
                seen.add(key)
                fix(child)
                walk(child)
                child = child.get(pikepdf.Name.Next)

        walk(root)

    for page in pdf.pages:
        for annot in page.obj.get(pikepdf.Name.Annots, []) or []:
            if annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Link:
                fix(annot)

    return repaired, out_of_range, unknown


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("merged", help="the merged PDF to repair")
    parser.add_argument("originals", help="folder holding the original files")
    parser.add_argument("-o", "--output", help="where to write the repaired PDF")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change and write nothing")
    parser.add_argument("--force", action="store_true",
                        help="repair even if the layout check fails")
    args = parser.parse_args()

    if not args.output and not args.dry_run:
        parser.error("give -o OUT.pdf, or --dry-run to only look")
    if args.output and os.path.abspath(args.output) == os.path.abspath(args.merged):
        parser.error("refusing to overwrite the input; choose another -o")

    lengths = source_lengths(args.originals)
    if not lengths:
        sys.exit(f"no PDFs in {args.originals}")
    print(f"originals      : {len(lengths)} files, {sum(lengths.values())} pages")

    with pikepdf.open(args.merged) as pdf:
        print(f"merged file    : {len(pdf.pages)} pages")
        offsets = recover_offsets(pdf, lengths)
        print(f"located        : {len(offsets)} of {len(lengths)} originals "
              f"by their top-level bookmark")
        if not offsets:
            sys.exit("could not tell where any original file's pages landed; "
                     "re-merge from the originals instead")

        problems = check(offsets, lengths, len(pdf.pages))
        if problems:
            print("\nlayout does not look like a plain concatenation:")
            for line in problems[:5]:
                print(f"   {line}")
            if not args.force:
                sys.exit("\nstopping. Re-merge from the originals, or pass "
                         "--force if you are sure.")
            print("   continuing anyway (--force)\n")
        else:
            print("layout check  : every file's pages are exactly where its "
                  "bookmark says")

        repaired, out_of_range, unknown = repair(pdf, offsets, lengths,
                                                 dry_run=args.dry_run)
        print(f"\nrepairable links : {repaired}")
        print(f"page out of range: {out_of_range}")
        print(f"unknown target   : {unknown}  (left as they are)")

        if args.dry_run:
            print("\ndry run - nothing written")
            return
        pdf.save(args.output)
        print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
