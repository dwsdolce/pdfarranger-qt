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

"""What has to be true of a catalogue, whoever or whatever wrote it.

Built before any machine translation exists, because these are the failures a
reviewer does not catch and a native speaker cannot be asked to look for: a
`%d` that came back as `%s` is a crash, and a dropped accelerator is invisible
until somebody reaches for the key. Nobody here reads 33 languages, so the
checks have to be mechanical.

Run against the 33 existing catalogues first, which is how the shape of each
one was decided. Two came out clean and stay hard failures; two did not, and
became ratchets instead:

- **format specifiers** — 107 entries carry one, 0 disagree. Hard failure.
- **plural forms** — every plural entry already has the count its locale
  declares. Hard failure.
- **mnemonics kept** — 106 of 2036 are dropped, in 16 of the 33 languages;
  Catalan loses 38 of 46. Upstream's translations, and adding an accelerator to
  Catalan is a translation decision rather than a repair. Ratchet.
- **mnemonics unique within a menu** — every language collides, *including
  English*: `&Print…` and `Edit &Properties` both want P. The accelerator lives
  inside the msgid, so moving it orphans every translation of that string.
  Ratchet.

A ratchet is a recorded count that may fall and must not rise. It is worth more
than a hard failure nobody can make pass, and worth more than a report nobody
reads: the numbers below can only come down.
"""

import collections
import glob
import os
import re
import unittest

from support import HERE

ROOT = os.path.dirname(HERE)
PO = os.path.join(ROOT, "po")

#: A real format placeholder. Deliberately *not* allowing the space flag: with
#: it, "% of height" parses as a `%o` conversion and 56 innocent labels are
#: reported as broken. That was the first version of this check.
SPEC = re.compile(r"%(?:\([^)]+\))?[-#0+]*[0-9*]*(?:\.[0-9*]+)?[hlL]?[diouxXeEfFgGcrsa%]")

#: A GTK-style accelerator: the underscore before the key.
MNEMONIC = re.compile(r"_[A-Za-z]")

#: Dropped accelerators per language, as of 2026-09-08. May fall, must not rise.
MNEMONICS_LOST = {
    "ar": 3, "ca": 38, "ca@valencia": 21, "da": 3, "de": 2,
    "es": 15, "eu": 5, "he": 1, "hu": 1, "ka": 3,
    "nl": 2, "pl_PL": 7, "pt_PT": 1, "sl": 2, "uk": 1,
    "zh_TW": 1,
}

#: Within-menu accelerator collisions per language, as of 2026-09-08. English
#: is in here because English collides too -- this is not a translation fault.
CLASHES = {
    "ar": 3, "ca": 2, "ca@valencia": 2, "cs": 4, "da": 4, "de": 10,
    "el": 3, "en": 5, "es": 5, "eu": 8, "fi": 8, "fr": 4,
    "he": 4, "hr": 7, "hu": 4, "id": 11, "is": 6, "it": 9,
    "ja": 5, "ka": 4, "ko": 4, "nl": 8, "oc": 11, "pl_PL": 4,
    "pt_BR": 8, "pt_PT": 7, "ru": 5, "sl": 5, "sv": 5, "tr": 9,
    "uk": 5, "vi": 12, "zh_CN": 5, "zh_TW": 5,
}


def languages():
    return sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(PO, "*.po")))


def catalogue(language):
    from babel.messages.pofile import read_po

    with open(os.path.join(PO, f"{language}.po"), encoding="utf-8") as handle:
        return read_po(handle)


def translated(message):
    """(msgids, translations) for a message that actually has one."""
    ids = list(message.id) if isinstance(message.id, tuple) else [message.id]
    got = (list(message.string) if isinstance(message.string, tuple)
           else [message.string])
    return (ids, got) if any(got) else (ids, [])


class CatalogueTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import babel.messages.pofile  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("babel is not installed")
        cls.languages = languages()
        if not cls.languages:
            raise unittest.SkipTest("po/ is not present")


class TestTheChecksWork(CatalogueTestCase):
    """Each pattern, against text where the answer is known."""

    def test_the_specifier_pattern_finds_placeholders(self):
        self.assertEqual(SPEC.findall("%d page of %s"), ["%d", "%s"])
        self.assertEqual(SPEC.findall("%(count)d files"), ["%(count)d"])

    def test_it_does_not_find_a_literal_percent(self):
        """The bug in the first version: "% of height" is a label, not a format."""
        self.assertEqual(SPEC.findall("% of height"), [])
        self.assertEqual(SPEC.findall("Width in %"), [])

    def test_the_mnemonic_pattern(self):
        self.assertTrue(MNEMONIC.search("_Open"))
        self.assertTrue(MNEMONIC.search("Save _As…"))
        self.assertIsNone(MNEMONIC.search("Open Recent"))

    def test_there_are_catalogues_to_check(self):
        self.assertGreater(len(self.languages), 30)


class TestFormatSpecifiers(CatalogueTestCase):
    """A `%d` that returns as `%s` crashes, in a language nobody here reads."""

    def test_every_translation_keeps_its_placeholders(self):
        checked = 0
        for language in self.languages:
            for message in catalogue(language):
                if not message.id:
                    continue
                ids, got = translated(message)
                if not got:
                    continue
                want = set(SPEC.findall(" ".join(ids)))
                if want:
                    checked += 1
                for one in got:
                    if not one:
                        continue
                    with self.subTest(language=language, msgid=ids[0]):
                        self.assertEqual(set(SPEC.findall(one)), want)
        self.assertGreater(checked, 90, "the check stopped finding placeholders")


class TestPluralForms(CatalogueTestCase):
    """Too few forms and gettext indexes past the end for some counts."""

    def test_every_plural_has_the_number_its_locale_declares(self):
        checked = 0
        for language in self.languages:
            cat = catalogue(language)
            for message in cat:
                if not isinstance(message.id, tuple):
                    continue
                _ids, got = translated(message)
                if not got:
                    continue
                checked += 1
                with self.subTest(language=language, msgid=message.id[0]):
                    self.assertEqual(len(got), cat.num_plurals)
        # Five today, all Russian, from Pull Request #2 -- every other catalogue
        # predates this port's plural strings and has none at all. Low, but not
        # nothing, which is what a sanity check has to establish. It rises as
        # the catalogues fill.
        self.assertGreaterEqual(checked, 5, "the check stopped finding plurals")


class TestMnemonicsKept(CatalogueTestCase):
    """A translation that drops the `_` leaves the entry with no accelerator."""

    def lost(self, language):
        out = []
        for message in catalogue(language):
            if not message.id or isinstance(message.id, tuple):
                continue
            ids, got = translated(message)
            if got and MNEMONIC.search(ids[0]) and "_" not in got[0]:
                out.append(ids[0])
        return out

    def test_no_language_drops_more_than_it_does_today(self):
        for language in self.languages:
            with self.subTest(language=language):
                self.assertLessEqual(
                    len(self.lost(language)), MNEMONICS_LOST.get(language, 0),
                    f"{language} lost an accelerator it used to keep")

    def test_the_baseline_is_not_stale(self):
        """A ratchet nobody tightens is a ratchet that stops meaning anything."""
        actual = {lang: len(self.lost(lang)) for lang in self.languages}
        overstated = {lang: (MNEMONICS_LOST[lang], actual.get(lang, 0))
                      for lang in MNEMONICS_LOST
                      if actual.get(lang, 0) < MNEMONICS_LOST[lang]}
        self.assertEqual(overstated, {},
                         "these have improved -- lower MNEMONICS_LOST to match")

    def test_seventeen_languages_carry_every_accelerator(self):
        """The premise of the ratchet: this is fixable, not inherent."""
        clean = [lang for lang in self.languages if not self.lost(lang)]
        self.assertGreaterEqual(len(clean), 17)


class TestMnemonicsAreUniqueInAMenu(CatalogueTestCase):
    """Two entries claiming one key means the key activates neither reliably.

    The only check here that needs the application: which entries share a menu
    is a fact about the window, not about the catalogue.

    A ratchet rather than a hard failure, because **English collides too** --
    `&Print…` sits beside `Edit &Properties`, `&Duplicate` beside `&Delete`.
    The accelerator is written into the msgid, so moving one mints a new msgid
    and orphans every translation of the old one. That is a deliberate,
    expensive change, not something to force on a Tuesday.

    Note what this reads. The window loads *compiled* catalogues, so this sees
    `build/mo`, while every other check in this file parses `po/*.po`. Editing
    a `.po` changes nothing here until `tools/build_mo.py` runs -- which is how
    a first attempt at breaking this check on purpose came up green, and is
    worth knowing before trusting a green run after a translation edit.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import support  # noqa: F401 - imports conftest, which makes the app

    def clashes(self, language):
        """Menus where two entries want the same key, for one language."""
        import re as _re

        from PySide6.QtWidgets import QMenu

        from pdfarranger_qt import i18n
        from pdfarranger_qt.mainwindow import MainWindow

        # "xx" has no catalogue, so it is how the untranslated msgids are asked
        # for -- the English baseline.
        self.assertEqual(i18n.setup("xx" if language == "en" else language),
                         "" if language == "en" else language,
                         f"{language} did not load")
        window = MainWindow()
        try:
            found = []
            for menu in window.findChildren(QMenu):
                keys = collections.defaultdict(list)
                for action in menu.actions():
                    if action.isSeparator() or action.menu() is not None:
                        continue
                    hit = _re.search(r"&(\w)", action.text())
                    if hit:
                        keys[hit.group(1).lower()].append(action.text())
                found += [(menu.objectName() or menu.title(), key, labels)
                          for key, labels in keys.items() if len(labels) > 1]
            return found
        finally:
            window.close()
            i18n.setup(None)

    def test_no_language_collides_more_than_it_does_today(self):
        for language in ["en"] + self.languages:
            with self.subTest(language=language):
                found = self.clashes(language)
                self.assertLessEqual(
                    len(found), CLASHES.get(language, 0),
                    f"{language} gained a collision: "
                    + "; ".join(f"{m}/{k}" for m, k, _l in found))

    def test_the_baseline_is_not_stale(self):
        overstated = {}
        for language in ["en"] + self.languages:
            actual = len(self.clashes(language))
            if actual < CLASHES.get(language, 0):
                overstated[language] = (CLASHES[language], actual)
        self.assertEqual(overstated, {},
                         "these have improved -- lower CLASHES to match")

    def test_english_collides_too(self):
        """The premise for this being a ratchet rather than a failure.

        If English ever comes up clean, this check can become a hard failure
        for every language, and should.
        """
        self.assertTrue(self.clashes("en"),
                        "English is clean now -- make this a hard failure")


class TestEveryCatalogueCompiles(CatalogueTestCase):
    """A `.po` that does not compile ships as a language that does nothing."""

    def test_they_all_build(self):
        import io as _io

        from babel.messages.mofile import write_mo

        for language in self.languages:
            with self.subTest(language=language):
                buffer = _io.BytesIO()
                write_mo(buffer, catalogue(language))
                self.assertGreater(len(buffer.getvalue()), 100,
                                   f"{language} compiled to nothing")

    def test_the_compiled_tree_matches_the_sources(self):
        """`tools/build_mo.py` output, when it has been run."""
        built = os.path.join(ROOT, "build", "mo")
        if not os.path.isdir(built):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        missing = [lang for lang in self.languages
                   if not os.path.isfile(os.path.join(
                       built, lang, "LC_MESSAGES", "pdfarranger.mo"))]
        self.assertEqual(missing, [], "these have no compiled catalogue")


class TestTheCompiledTreeIsCurrent(CatalogueTestCase):
    """`build/mo` is what the application reads, and it can fall behind.

    Only one check in this file goes through the running window, and it
    therefore tests the compiled catalogues rather than the sources everything
    else parses. A stale `build/mo` makes that check quietly meaningless -- it
    would still pass while measuring a catalogue nobody has any more.
    """

    def test_no_catalogue_source_is_newer_than_its_compiled_form(self):
        built = os.path.join(ROOT, "build", "mo")
        if not os.path.isdir(built):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        stale = []
        for language in self.languages:
            source = os.path.join(PO, f"{language}.po")
            compiled = os.path.join(built, language, "LC_MESSAGES", "pdfarranger.mo")
            if (os.path.isfile(compiled)
                    and os.path.getmtime(source) > os.path.getmtime(compiled) + 1):
                stale.append(language)
        self.assertEqual(stale, [],
                         "these .po files are newer than their .mo: "
                         "run tools/build_mo.py")
