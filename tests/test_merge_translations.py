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

"""The tool that writes generated translations into a catalogue.

The rules it has to keep are the ones nobody can check by reading the result:
32 catalogues in languages nobody here reads, filled by machine. So they are
checked here instead -- that a human's string is never overwritten, that a
broken translation is refused rather than written, and that the header survives
a round trip through babel, which drops fields it does not model.
"""

import io
import os
import sys
import unittest

from support import HERE

ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import merge_translations as merge  # noqa: E402


def catalogue(text):
    from babel.messages.pofile import read_po

    return read_po(io.StringIO(text))


HEADER = '''# Test translation.
# Translators:
# Someone <someone@example.com>, 2020
#
msgid ""
msgstr ""
"Project-Id-Version: test\\n"
"PO-Revision-Date: 2020-01-01 00:00+0000\\n"
"Last-Translator: Someone <someone@example.com>\\n"
"Language: de\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=utf-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"X-Generator: Poedit 3.0.1\\n"

msgid "_Open"
msgstr "_Öffnen"

msgid "_Close"
msgstr ""

msgid "%d page"
msgid_plural "%d pages"
msgstr[0] ""
msgstr[1] ""
'''


class MergeTestCase(unittest.TestCase):
    def setUp(self):
        try:
            import babel.messages.pofile  # noqa: F401
        except ImportError:
            self.skipTest("babel is not installed")
        self.catalog = catalogue(HEADER)

    def fill(self, translations):
        return merge.fill(self.catalog, translations)

    def string(self, msgid):
        for message in self.catalog:
            key = message.id[0] if isinstance(message.id, tuple) else message.id
            if key == msgid:
                return message.string
        raise AssertionError(f"{msgid!r} is not in the catalogue")


class TestHumanWorkIsNeverOverwritten(MergeTestCase):
    """The rule the whole exercise rests on -- see D22."""

    def test_an_existing_translation_is_left_alone(self):
        written, _refused, occupied, _unknown = self.fill({"_Open": "_Etwas anderes"})
        self.assertEqual(self.string("_Open"), "_Öffnen")
        self.assertEqual((written, occupied), (0, 1))

    def test_an_empty_one_is_filled(self):
        written, _r, _o, _u = self.fill({"_Close": "_Schließen"})
        self.assertEqual(self.string("_Close"), "_Schließen")
        self.assertEqual(written, 1)

    def test_a_msgid_the_catalogue_does_not_have_is_reported(self):
        _w, _r, _o, unknown = self.fill({"Not A Real Msgid": "x"})
        self.assertEqual(unknown, ["Not A Real Msgid"])


class TestBadTranslationsAreRefused(MergeTestCase):
    """Refused at the source, rather than written for a guard to find later."""

    def refuse(self, translations):
        _w, refused, _o, _u = self.fill(translations)
        self.assertEqual(len(refused), 1, f"expected one refusal, got {refused}")
        return refused[0][1]

    def test_a_dropped_accelerator(self):
        self.assertIn("accelerator", self.refuse({"_Close": "Schließen"}))
        self.assertEqual(self.string("_Close"), "")

    def test_a_changed_placeholder(self):
        why = self.refuse({"%d page": ["%s Seite", "%s Seiten"]})
        self.assertIn("placeholders", why)

    def test_the_wrong_number_of_plural_forms(self):
        why = self.refuse({"%d page": ["%d Seite"]})
        self.assertIn("plural forms", why)

    def test_an_empty_translation(self):
        self.assertIn("empty", self.refuse({"_Close": "   "}))

    def test_a_list_for_a_message_with_no_plural(self):
        self.assertIn("no plural", self.refuse({"_Close": ["_a", "_b"]}))

    def test_a_refusal_leaves_the_message_untouched(self):
        self.fill({"%d page": ["%s Seite", "%s Seiten"]})
        self.assertEqual(self.string("%d page"), ("", ""))


class TestGeneratedEntriesAreMarked(MergeTestCase):
    """So that "show me the unreviewed strings" is a grep."""

    def test_the_comment_is_added(self):
        self.fill({"_Close": "_Schließen"})
        for message in self.catalog:
            if message.id == "_Close":
                self.assertIn(merge.MARK, message.user_comments)
                return
        self.fail("_Close vanished")

    def test_it_is_not_added_twice(self):
        self.fill({"_Close": "_Schließen"})
        # A second run finds it occupied, so nothing is added again.
        self.fill({"_Close": "_Schließen"})
        for message in self.catalog:
            if message.id == "_Close":
                self.assertEqual(message.user_comments.count(merge.MARK), 1)

    def test_an_untouched_message_gets_no_comment(self):
        self.fill({"_Close": "_Schließen"})
        for message in self.catalog:
            if message.id == "_Open":
                self.assertNotIn(merge.MARK, message.user_comments)


class TestTheHeaderSurvives(unittest.TestCase):
    """`write_po` rebuilds the header and drops what it does not model."""

    def setUp(self):
        try:
            import babel.messages.pofile  # noqa: F401
        except ImportError:
            self.skipTest("babel is not installed")
        import tempfile

        self.path = os.path.join(tempfile.mkdtemp(), "de.po")
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(HEADER)

    def written(self):
        catalog = merge.load(self.path)
        merge.save(catalog, self.path, HEADER)
        return open(self.path, encoding="utf-8").read()

    def test_x_generator_names_this_tool(self):
        self.assertIn(f"X-Generator: {merge.GENERATOR}", self.written())

    def test_it_replaces_rather_than_repeats(self):
        text = self.written()
        self.assertEqual(text.count("X-Generator:"), 1)
        self.assertNotIn("Poedit", text)

    def test_last_translator_is_untouched(self):
        """It names a person. Machine output does not go under their name."""
        self.assertIn("Last-Translator: Someone <someone@example.com>",
                      self.written())

    def test_the_translator_credits_survive(self):
        self.assertIn("# Someone <someone@example.com>, 2020", self.written())

    def test_the_result_still_parses(self):
        catalog = catalogue(self.written())
        self.assertEqual(catalog.locale.language, "de")
        self.assertEqual(catalog.num_plurals, 2)

    def test_babel_alone_would_have_dropped_it(self):
        """The premise for repairing the header at all.

        If a future babel starts preserving unknown headers this fails, and the
        repair can be deleted rather than carried for ever.
        """
        from babel.messages.pofile import write_po

        buffer = io.BytesIO()
        write_po(buffer, merge.load(self.path), include_lineno=False)
        self.assertNotIn("X-Generator", buffer.getvalue().decode("utf-8"))


class TestSync(unittest.TestCase):
    def setUp(self):
        try:
            import babel.messages.pofile  # noqa: F401
        except ImportError:
            self.skipTest("babel is not installed")

    def test_it_adds_what_the_template_has_and_retires_the_rest(self):
        catalog = catalogue(HEADER)
        template = catalogue(
            'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
            'msgid "_Open"\nmsgstr ""\n\nmsgid "_Brand New"\nmsgstr ""\n')
        added, retired = merge.sync(catalog, template)
        self.assertEqual(added, 1)
        self.assertGreaterEqual(retired, 1)
        ids = {m.id for m in catalog if m.id}
        self.assertIn("_Brand New", ids)
        self.assertNotIn("_Close", ids)

    def test_a_translation_survives_the_sync(self):
        catalog = catalogue(HEADER)
        template = catalogue(
            'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
            'msgid "_Open"\nmsgstr ""\n')
        merge.sync(catalog, template)
        self.assertEqual(catalog.get("_Open").string, "_Öffnen")


class TestTheRealGermanCatalogue(unittest.TestCase):
    """What the round trip actually produced, as the issue asked for."""

    def setUp(self):
        try:
            import babel.messages.pofile  # noqa: F401
        except ImportError:
            self.skipTest("babel is not installed")
        path = os.path.join(ROOT, "po", "de.po")
        self.text = open(path, encoding="utf-8").read()
        self.catalog = catalogue(self.text)

    def test_it_was_written_by_this_tool(self):
        self.assertIn(f"X-Generator: {merge.GENERATOR}", self.text)

    def test_the_generated_entries_are_findable(self):
        marked = [m for m in self.catalog if merge.MARK in m.user_comments]
        self.assertGreaterEqual(len(marked), 10)

    def test_every_marked_entry_has_a_translation(self):
        for message in self.catalog:
            if merge.MARK in message.user_comments:
                got = (list(message.string) if isinstance(message.string, tuple)
                       else [message.string])
                with self.subTest(msgid=message.id):
                    self.assertTrue(all(got), "marked but empty")

    def test_the_human_translations_are_not_marked(self):
        """133 strings predate this tool; none of them should carry the mark."""
        for message in self.catalog:
            if message.id == "_Open":
                self.assertNotIn(merge.MARK, message.user_comments)
