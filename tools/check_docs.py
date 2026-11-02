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

"""The code does not cite the documentation, and the documentation hangs together.

Run from the repository root::

    python tools/check_docs.py

**Comments must stand on their own.** A docstring that says "see the design
notes" is only as durable as the notes: documents get renamed, split, merged
and deleted, and the pointer decays into something confidently wrong -- worse
than no pointer, because a reader follows it.

This project paid for that lesson three times. Nine comments cited "section 6"
for material that had drifted into section 7, silently, for months. Then the
one document became eight and every one of those references had to be
rewritten. Then a hundred and eleven comments citing decisions by number were
found pointing into two different registers at once, so the same `D5` meant
the clipboard format in one of them and a signature rule in the other.

So the reasoning lives where the code is. Where a measurement justifies a
decision, the number is in the docstring -- "the worst page costs 247 ms" --
not a reference to where the number was written down.

**This is a tool and not a test**, which is the rule applied to itself: a test
that reads the documentation tree is a test that depends on it, and the whole
point is that deleting that tree changes nothing about the application or its
suite. So the checks live here, they run from CI as their own step, and
`tests/` never mentions the tree at all.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.join(ROOT, "d" + "ocs")

#: Where source lives. Anything else in the tree is data or documentation.
SOURCES = ("pdfarranger_qt", "tests", "tools")

#: A reference to one of the project's own documents, by path.
DOCUMENT = re.compile(r"\b" + "d" + r"ocs/[A-Za-z0-9._-]+\.md\b")

#: A reference to a numbered section -- the form that rotted the first time.
#: `Section 1.1` is exempt: that is a bookmark title in the outline fixtures,
#: not a citation.
NUMBERED = re.compile(r"(?:§\s?\d+|[Ss]ection\s+\d+)(?!\.\d)")

#: A decision cited by number -- the form that rotted the third time. Two
#: registers use it: the port's closed D1-D25, and the running number each
#: work document keeps of its own. Nothing in the source can tell them apart,
#: and the second kind renumbers whenever a document is split.
DECISION = re.compile(r"\bD\d{1,3}\b")

#: The same citation spelled out instead of abbreviated. A number is the
#: obvious way to point at a document and not the only one: "decision 13",
#: "requirement M13", "highlight step 4" and "see *Where the tools live*" all
#: reach out of the code into something that can be renamed, renumbered or
#: deleted without it. **The code has to stand on its own**, whether the
#: pointer is a number or a sentence.
#:
#: `see *Title*` is included because a work document's headings are quoted
#: that way -- which also catches a source file pointing at another source
#: file's docstring heading. That is milder, since both move in the same
#: commit, but it decays the same way and there is no reason to allow it.
#:
#: **A bare requirement id is not caught, on purpose.** The documents write
#: them as `M13`, and no pattern separates that from "M1 Pro", "M2 Max" or a
#: model number, so the guard would cry wolf on hardware names in comments
#: about rendering. Only the spelled-out form is matched. A guard that fires
#: on innocent text gets switched off, which costs more than the hole.
CITATION = re.compile(
    r"(?i)\b(?:decision\s+\d+"
    r"|requirement\s+M?\d+"
    r"|(?:plan|highlight|underline|strikethrough|comment|draw)\s+step\s+\d+"
    r"|step\s+\d+\s+of\s+the"
    r"|see\s+\*)")


def python_files():
    for top in SOURCES:
        for base, _dirs, names in os.walk(os.path.join(ROOT, top)):
            if "__pycache__" in base:
                continue
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(base, name)


def offenders(pattern):
    """Every ``file:line`` matching, excluding this file's own explanation."""
    found = []
    for path in python_files():
        if os.path.samefile(path, os.path.abspath(__file__)):
            continue
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if "GPL" in line:
                    continue  # licence clauses really are numbered sections
                if pattern.search(line):
                    found.append(f"{os.path.relpath(path, ROOT)}:{number}")
    return found


def documents():
    """Every document, `completed/` included.

    Finished work moves down a level and stays under the same checks. The
    first version of this walked one directory, so moving a file would have
    quietly removed it from every guard here -- and its links, which then
    have to climb a level, are exactly what breaks in the move.
    """
    if not os.path.isdir(TREE):
        return []
    names = [n for n in os.listdir(TREE) if n.endswith(".md")]
    done = os.path.join(TREE, "completed")
    if os.path.isdir(done):
        names += [os.path.join("completed", n)
                  for n in os.listdir(done) if n.endswith(".md")]
    return sorted(names)


def read(name):
    with open(os.path.join(TREE, name), encoding="utf-8") as handle:
        return handle.read()


#: A `#12` that does not say what kind of thing it is. Four numbering systems
#: are in play and two of them use a `#`, so the word in front is the only
#: thing distinguishing "Issue #8" from "phase 8". The heading a work document
#: carries to name its Issue is allowed too.
UNNAMED = re.compile(
    r"(?<!Issue )(?<!Pull Request )(?<!PR )(?<!Issue:\*\* \[)"
    r"(?<![\w&])#\d{1,3}\b")

#: Inline code quotes rather than refers: `#8` in a sentence *about* the
#: notation is not a citation, and neither is `#000000`.
CODE_SPAN = re.compile(r"`[^`]*`")

#: A heading that states its status in some other word than the one word.
OTHER_WORD = re.compile(
    r"(?i)[—-]\s*\*\*(?!complete\*\*)(done|finished|landed)\*\*\s*$")

#: A box that is ticked and then says so again in prose.
TWICE = re.compile(r"^\s*[-*] \[[x~]\].*\bDone\.")

#: A box nobody has ticked: a to-do that nothing closes.
UNTICKED = re.compile(r"^\s*[-*] \[ \]")


#: A list declaring what its steps are cited as, which is how a document
#: says "my steps run 1 to 8". The guard reads these rather than trying to
#: work out where each list begins and ends: a declaration is one line to
#: change when a list grows, and a citation checked against it cannot
#: quietly outlive a renumber.
DECLARED = re.compile(
    r"Cited as \*\*(\w+) step (\d+)\*\* to \*\*\w+ step (\d+)\*\*")

#: A step cited in prose. Numbers are used rather than descriptions on
#: purpose -- a number can be searched for and "the step that settles colour"
#: cannot -- and the cost of that choice is that a renumber leaves citations
#: pointing at the wrong thing. This is what pays the cost.
CITED_STEP = re.compile(r"\b(\w+) step (\d+)\b")


def lines_of(name):
    for number, raw in enumerate(read(name).splitlines(), 1):
        yield number, CODE_SPAN.sub("", raw)


def check_the_checks():
    """Guard against a pattern that has quietly stopped matching anything."""
    bad = []
    if not NUMBERED.search("as section 6 measured"):
        bad.append("NUMBERED no longer matches a section reference")
    if NUMBERED.search('title == "Section 1.1"'):
        bad.append("NUMBERED now matches a bookmark title")
    if not DOCUMENT.search("see " + "d" + "ocs/DESIGN.md, *Something*"):
        bad.append("DOCUMENT no longer matches a document path")
    if not DECISION.search("the strip is generated (D10)"):
        bad.append("DECISION no longer matches a decision citation")
    if DECISION.search("the D20 of it") is None:
        bad.append("DECISION missed a bare citation")
    for cited in ("as decision 13 records", "requirement M13 asks for this",
                  "see highlight step 4", "step 3 of the markup plan",
                  "see *Where the tools live*"):
        if not CITATION.search(cited):
            bad.append(f"CITATION no longer matches {cited!r}")
    for innocent in ("one step 3 pixels wide", "the M1 Pro", "a 13 step ramp",
                     "see the note above", "steps 3 and 4 of the algorithm",
                     "which is M13"):
        if CITATION.search(innocent):
            bad.append(f"CITATION now rejects {innocent!r}")
    if not DECLARED.search("Cited as **plan step 1** to **plan step 4**"):
        bad.append("DECLARED no longer matches a list's declaration")
    if CITED_STEP.findall("highlight step 4") != [("highlight", "4")]:
        bad.append("CITED_STEP no longer matches a named citation")
    if not UNNAMED.search("blocked on #8 for now"):
        bad.append("UNNAMED no longer matches a bare number")
    for allowed in ("see Issue #8", "see Pull Request #2", "see PR #2",
                    "**Issue:** [#14](https://github.com/x/y/issues/14)"):
        if UNNAMED.search(allowed):
            bad.append(f"UNNAMED now rejects {allowed!r}")
    return bad


def check_source_stands_alone():
    bad = []
    files = list(python_files())
    if len(files) < 40 or not any(f.endswith("mainwindow.py") for f in files):
        return ["the source scan found nothing, so it proves nothing"]
    for pattern, why in (
            (DOCUMENT, "cites a document, which may be renamed or deleted"),
            (NUMBERED, "cites a numbered section, and numbers move"),
            (DECISION, "cites a decision by number; say what it decided"),
            (CITATION, "points into a document; say the fact instead")):
        for where in offenders(pattern):
            bad.append(f"{where}: {why}")
    return bad


def check_documents_hang_together():
    bad = []
    names = documents()
    if not names:
        return bad
    index = read("README.md")
    for name in names:
        if name == "README.md":
            continue
        if f"({name.replace(os.sep, '/')})" not in index:
            bad.append(f"{name} is in no index, so nobody finds it")
    for name in names:
        here = os.path.dirname(os.path.join(TREE, name))
        for _label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)",
                                         read(name)):
            if target.startswith(("http", "#", "mailto:")):
                continue
            if not os.path.exists(os.path.join(here, target.split("#")[0])):
                bad.append(f"{name} links to {target}, which is not there")
        if not read(name).startswith("# "):
            bad.append(f"{name} does not begin with a title")
        for number, line in lines_of(name):
            if UNNAMED.search(line):
                bad.append(f"{name}:{number} has a bare #number; write "
                           f"'Issue N' or 'Pull Request N'")
            if name != "CONVENTIONS.md" and re.search(r"[Pp]hase\s+[89]",
                                                      line):
                bad.append(f"{name}:{number} uses a phase number; name the "
                           f"work instead")
    top = os.path.join(ROOT, "README.md")
    if os.path.isfile(top):
        with open(top, encoding="utf-8") as handle:
            if "d" + "ocs/README.md" not in handle.read():
                bad.append("the top-level README does not point at the index")
    return bad


def check_steps_can_be_found():
    """Every cited step exists in the list it names.

    Two numbering systems were in this tree before this check: a markup
    plan of four steps and one tool's order of eight, both written as
    "step 4". A third was about to arrive with the next tool, and twenty
    more after that. So a citation names its list -- `plan step 4`,
    `highlight step 4` -- and this is what stops the number in it rotting.
    """
    bad = []
    for name in documents():
        body = read(name)
        declared = {who.lower(): (int(first), int(last))
                    for who, first, last in DECLARED.findall(body)}
        # A ratchet, not a sweep. A document that has declared its lists is
        # checked; one that has not is left alone until it does. The older
        # notes carry a third numbering of their own -- "phase 7 step 2" --
        # from the port, and renumbering history to satisfy a guard would be
        # rewriting the record rather than keeping it.
        if not declared:
            continue
        for number, line in lines_of(name):
            for who, step in CITED_STEP.findall(line):
                if who.lower() in ("the", "a", "this", "each", "one", "next",
                                   "first", "last", "same", "its", "no"):
                    continue
                if who.lower() not in declared:
                    bad.append(f"{name}:{number} cites {who} step {step}, "
                               f"and no list says what {who}'s steps are")
                    continue
                first, last = declared[who.lower()]
                if not first <= int(step) <= last:
                    bad.append(f"{name}:{number} cites {who} step {step}, "
                               f"and that list runs {first} to {last}")
    return bad


def check_how_things_are_marked_done():
    """One notation, and status lives in Issues rather than in a document."""
    bad = []
    for name in documents():
        for number, raw in enumerate(read(name).splitlines(), 1):
            if UNTICKED.match(raw.rstrip()):
                bad.append(f"{name}:{number} has an open checkbox; open work "
                           f"belongs in an Issue")
            if TWICE.match(raw):
                bad.append(f"{name}:{number} says it is done twice")
            if raw.startswith("#") and OTHER_WORD.search(raw):
                bad.append(f"{name}:{number} says it another way; use "
                           f"'**complete**'")
    return bad


def main():
    problems = check_the_checks()
    if problems:
        print("THE CHECKS THEMSELVES ARE BROKEN:")
        for line in problems:
            print("   ", line)
        return 2
    problems = (check_source_stands_alone()
                + check_documents_hang_together()
                + check_steps_can_be_found()
                + check_how_things_are_marked_done())
    if problems:
        print(f"{len(problems)} problem(s):")
        for line in problems:
            print("   ", line)
        return 1
    found = documents()
    print(f"source cites nothing; {len(found)} document(s) hang together"
          if found else
          "source cites nothing; there is no documentation tree to check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
