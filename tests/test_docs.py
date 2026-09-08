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

**Comments must stand on their own.** A docstring that says "see the design
notes" is only as durable as the notes: documents get renamed, split, merged
and deleted, and the pointer decays into something confidently wrong -- worse
than no pointer, because a reader follows it.

This project paid for that lesson twice over. Nine comments cited "section 6"
for material that had drifted into section 7, silently, for months. Then the
one document became eight and every one of those references had to be rewritten
-- which is the moment it became obvious they should not exist. Traceability is
worth something when it is written and nothing a year later.

So the reasoning lives where the code is. Where a measurement justifies a
decision, the number is in the docstring -- "the worst page costs 247 ms" --
not a reference to where the number was written down.

The `docs/` tree still exists and is still worth reading. Nothing in the source
depends on it.
"""

import os
import re
import unittest

from support import HERE

ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")

#: Where source lives. Anything else in the tree is data or documentation.
SOURCES = ("pdfarranger_qt", "tests", "tools")

#: A reference to one of the project's own documents.
DOCUMENT = re.compile(r"\bdocs/[A-Za-z0-9._-]+\.md\b")

#: A reference to a numbered section -- the form that rotted the first time.
#: `Section 1.1` is exempt: that is a bookmark title in the outline fixtures,
#: not a citation.
NUMBERED = re.compile(r"(?:§\s?\d+|[Ss]ection\s+\d+)(?!\.\d)")


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
        if os.path.basename(path) == os.path.basename(__file__):
            continue
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if "GPL" in line:
                    continue  # licence clauses really are numbered sections
                if pattern.search(line):
                    found.append(f"{os.path.relpath(path, ROOT)}:{number}")
    return found


class TestCodeStandsAlone(unittest.TestCase):
    def test_the_check_can_see_the_source(self):
        """A file list that came back empty would pass everything below."""
        files = list(python_files())
        self.assertGreater(len(files), 40)
        self.assertTrue(any(f.endswith("mainwindow.py") for f in files))

    def test_no_comment_points_at_a_document(self):
        found = offenders(DOCUMENT)
        self.assertEqual(
            found, [],
            "these cite a document that may be renamed or deleted; put the "
            "reasoning in the comment instead: " + ", ".join(found))

    def test_no_comment_points_at_a_numbered_section(self):
        """Numbers are positions, and positions move without telling anyone."""
        found = offenders(NUMBERED)
        self.assertEqual(found, [], "numbered references have come back: "
                         + ", ".join(found))

    def test_the_patterns_match_what_they_claim_to(self):
        """Guard against a regex that has quietly stopped matching anything."""
        self.assertTrue(DOCUMENT.search("see docs/DESIGN.md, *Something*"))
        self.assertTrue(NUMBERED.search("as section 6 measured"))
        self.assertTrue(NUMBERED.search("the NON_UNIQUE design (§8)"))
        # The outline fixtures' bookmark titles are not citations.
        self.assertFalse(NUMBERED.search('title == "Section 1.1"'))


class TestTheDocumentsHangTogether(unittest.TestCase):
    """The documents may be ephemeral, but while they exist they should work."""

    def documents(self):
        return sorted(name for name in os.listdir(DOCS) if name.endswith(".md"))

    def test_the_index_lists_every_document(self):
        """A document nothing links to is a document nobody finds."""
        index = open(os.path.join(DOCS, "README.md"), encoding="utf-8").read()
        for name in self.documents():
            if name == "README.md":
                continue
            with self.subTest(document=name):
                self.assertIn(f"({name})", index,
                              f"docs/README.md does not link to {name}")

    def test_every_relative_link_resolves(self):
        for name in self.documents():
            text = open(os.path.join(DOCS, name), encoding="utf-8").read()
            for _label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text):
                if target.startswith(("http", "#", "mailto:")):
                    continue
                with self.subTest(f"{name} -> {target}"):
                    self.assertTrue(
                        os.path.exists(os.path.join(DOCS, target.split("#")[0])),
                        f"docs/{name} links to {target}, which is not there")

    def test_each_document_starts_with_a_title(self):
        for name in self.documents():
            with self.subTest(document=name):
                first = open(os.path.join(DOCS, name), encoding="utf-8").readline()
                self.assertTrue(first.startswith("# "),
                                f"docs/{name} does not begin with a title")

    #: A `#12` that does not say what kind of thing it is. Four numbering
    #: systems are in play and two of them use a `#`, so the word in front is
    #: the only thing distinguishing "Issue #8" from "phase 8".
    UNNAMED = re.compile(r"(?<!Issue )(?<!Pull Request )(?<!PR )(?<![\w&])#\d{1,3}\b")

    #: Inline code quotes rather than refers: `#8` in a sentence *about* the
    #: notation is not a citation, and neither is `#000000`. Stripped before
    #: the check, so the rule stays one rule instead of a rule plus exceptions.
    CODE_SPAN = re.compile(r"`[^`]*`")

    def lines_of(self, name):
        text = open(os.path.join(DOCS, name), encoding="utf-8").read()
        for number, raw in enumerate(text.splitlines(), 1):
            yield number, self.CODE_SPAN.sub("", raw)

    def test_every_github_reference_says_what_it_is(self):
        """`Issue #12` and `Pull Request #2`, never a bare `#12`."""
        for name in self.documents():
            for number, line in self.lines_of(name):
                with self.subTest(f"{name}:{number}"):
                    self.assertIsNone(
                        self.UNNAMED.search(line),
                        f"docs/{name}:{number} has a bare #number; write "
                        f"'Issue #N' or 'Pull Request #N'")

    def test_work_after_the_port_is_named_not_numbered(self):
        """Phases 0–7 are the port. Everything since has a name and a file.

        The ordinal earned nothing once each body of work had a document of its
        own, and it collided with GitHub the moment Issue #8 existed alongside
        phase 8.
        """
        for name in self.documents():
            if name == "CONVENTIONS.md":
                continue  # states the rule, so it has to name the thing
            for number, line in self.lines_of(name):
                with self.subTest(f"{name}:{number}"):
                    self.assertNotRegex(
                        line, r"[Pp]hase\s+[89]",
                        f"docs/{name}:{number} still uses a phase number; "
                        f"name the work instead")

    def test_those_patterns_match_what_they_claim_to(self):
        strip = self.CODE_SPAN.sub
        self.assertTrue(self.UNNAMED.search("blocked on #8 for now"))
        self.assertIsNone(self.UNNAMED.search("see Issue #8"))
        self.assertIsNone(self.UNNAMED.search("see Pull Request #2"))
        self.assertIsNone(self.UNNAMED.search("see PR #2"))
        # Quoted rather than cited, so both of these are allowed through.
        self.assertIsNone(self.UNNAMED.search(strip("", "colour `#000000`")))
        self.assertIsNone(self.UNNAMED.search(strip("", "never a bare `#8`")))

    def test_the_readme_points_at_the_documentation(self):
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("docs/README.md", readme)


class TestHowThingsAreMarkedDone(unittest.TestCase):
    """One notation, and status lives in Issues rather than here.

    Three notations were in use at once -- a ticked box, "**done**" appended to
    a heading, and "Done." after the box -- so what was finished could not be
    read off the page. See CONVENTIONS.md, *How to refer to things*.
    """

    def documents(self):
        return sorted(name for name in os.listdir(DOCS) if name.endswith(".md"))

    def test_no_document_holds_an_unticked_box(self):
        """`- [ ]` is a to-do nobody is assigned to and nothing closes."""
        for name in self.documents():
            text = open(os.path.join(DOCS, name), encoding="utf-8").read()
            for number, line in enumerate(text.splitlines(), 1):
                with self.subTest(f"{name}:{number}"):
                    self.assertNotRegex(
                        line.rstrip(), r"^\s*[-*] \[ \]",
                        f"docs/{name}:{number} has an open checkbox; "
                        f"open work belongs in an Issue")

    def test_a_section_heading_uses_one_word_for_it(self):
        """A heading may state the status of the section it names.

        What it may not do is pick a different word each time. `**complete**`
        throughout, because that is what the port's phase headings have always
        used and there are more of them than of anything else.
        """
        wrong = re.compile(r"(?i)[—-]\s*\*\*(?!complete\*\*)(done|finished|"
                           r"landed)\*\*\s*$")
        for name in self.documents():
            text = open(os.path.join(DOCS, name), encoding="utf-8").read()
            for number, line in enumerate(text.splitlines(), 1):
                if not line.startswith("#"):
                    continue
                with self.subTest(f"{name}:{number}"):
                    self.assertIsNone(
                        wrong.search(line),
                        f"docs/{name}:{number} says it another way; "
                        f"use '**complete**'")

    def test_a_ticked_box_does_not_also_say_done(self):
        pattern = re.compile(r"^\s*[-*] \[[x~]\].*\bDone\.")
        for name in self.documents():
            text = open(os.path.join(DOCS, name), encoding="utf-8").read()
            for number, line in enumerate(text.splitlines(), 1):
                with self.subTest(f"{name}:{number}"):
                    self.assertIsNone(pattern.match(line),
                                      f"docs/{name}:{number} says it twice")
