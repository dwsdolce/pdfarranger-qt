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
- **markup** — 31 translated entries carry a tag, 0 disagree. Hard failure.
- **plural forms** — every plural entry already has the count its locale
  declares. Hard failure.
- **mnemonics kept** — 97 of 2359 are dropped, in 13 of the 33 languages;
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

#: Markup, in the user guide and nine shorter strings besides. Counted rather
#: than compared in order: a translation may reorder what it emphasises, but it
#: may not lose a closing tag or translate a tag name.
TAG = re.compile(r"<[a-zA-Z/][^>]*>")

#: Dropped accelerators per language, as of 2026-09-07. May fall, must not rise.
MNEMONICS_LOST = {
    "ar": 1, "ca": 38, "ca@valencia": 21, "da": 2, "de": 2,
    "es": 13, "eu": 5, "hu": 1, "ka": 3,
    "nl": 2, "pl_PL": 6, "sl": 2, "uk": 1,
}

#: Within-menu accelerator collisions per language, as of 2026-09-07. English
#: is in here because English collides too -- this is not a translation fault.
CLASHES = {
    "ar": 2, "ca": 2, "ca@valencia": 2, "cs": 2, "da": 2, "de": 10,
    "el": 2, "en": 5, "es": 5, "eu": 8, "fi": 6, "fr": 4,
    "he": 3, "hr": 3, "hu": 3, "id": 11, "is": 3, "it": 7,
    "ja": 4, "ka": 4, "ko": 4, "nl": 6, "oc": 11, "pl_PL": 2,
    "pt_BR": 7, "pt_PT": 5, "ru": 5, "sl": 2, "sv": 4, "tr": 8,
    "uk": 5, "vi": 12, "zh_CN": 5, "zh_TW": 4,
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


class TestMarkup(CatalogueTestCase):
    """A lost `</b>` renders the rest of a help paragraph in bold, or as text.

    Only a person opening Help in that language would ever see it, which is
    the whole reason this is mechanical. 38 messages carry markup and 29 of
    them are the user guide, so this matters most exactly where review is
    least likely.
    """

    def test_every_translation_keeps_its_tags(self):
        checked = 0
        for language in self.languages:
            for message in catalogue(language):
                if not message.id:
                    continue
                ids, got = translated(message)
                if not got:
                    continue
                want = collections.Counter(TAG.findall(" ".join(ids)))
                if not want:
                    continue
                checked += 1
                for one in got:
                    if not one:
                        continue
                    with self.subTest(language=language, msgid=ids[0][:40]):
                        self.assertEqual(collections.Counter(TAG.findall(one)), want)
        self.assertGreater(checked, 25, "the check stopped finding markup")

    def test_reordering_is_allowed(self):
        """A translation may emphasise the same things in a different order."""
        a = collections.Counter(TAG.findall("<b>A</b> and <i>B</i>"))
        b = collections.Counter(TAG.findall("<i>B</i> und <b>A</b>"))
        self.assertEqual(a, b)

    def test_a_lost_closing_tag_is_not(self):
        a = collections.Counter(TAG.findall("<b>A</b>"))
        b = collections.Counter(TAG.findall("<b>A"))
        self.assertNotEqual(a, b)


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


class TestThePreferenceOffersWhatExists(CatalogueTestCase):
    """The Language menu in Preferences, against the catalogues on disk.

    The menu used to be a hand-written table of thirty, and it drifted from the
    thirty-three catalogues beside it: seven translated languages could not be
    selected at all, and three entries pointed at nothing. The worst of them
    was Polish, offered as `pl` while the catalogue is `pl_PL` -- choosing it
    loaded no catalogue and silently left the application in English, with no
    other way to reach the Polish translation.

    The list is read off the disk now, so most of that cannot recur. What can
    still rot is the handful of names where Qt's CLDR answer is not the one to
    show, so those are checked one by one against what Qt says today.

    `en` is the exception that is meant to be here: English is the msgid, so
    selecting it loads nothing and shows the source strings.
    """

    def offered(self):
        from pdfarranger_qt.dialogs import languages

        return languages()

    def test_the_check_can_see_a_catalogue(self):
        """An empty list would pass every comparison below."""
        if not os.path.isdir(os.path.join(ROOT, "build", "mo")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        self.assertGreater(len(self.offered()), 30)

    def test_every_catalogue_can_be_chosen(self):
        if not os.path.isdir(os.path.join(ROOT, "build", "mo")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        codes = {code for code, _name in self.offered()}
        missing = sorted(set(self.languages) - codes)
        self.assertEqual(missing, [],
                         "these are translated but cannot be selected in "
                         "Preferences: " + ", ".join(missing))

    def test_nothing_offered_is_missing_its_catalogue(self):
        """An entry with no catalogue is a menu item that does nothing."""
        dead = sorted(code for code, _name in self.offered()
                      if code != "en" and code not in self.languages)
        self.assertEqual(dead, [],
                         "these are offered but have no catalogue: "
                         + ", ".join(dead))

    def test_no_code_or_name_appears_twice(self):
        """Two rows reading the same is a menu you cannot choose from.

        This is what `ca` and `ca@valencia` do without their override: Qt drops
        the modifier and answers "catala" to both.
        """
        codes = [code for code, _name in self.offered()]
        names = [name for _code, name in self.offered()]
        self.assertEqual(sorted(codes), sorted(set(codes)), "duplicate code")
        self.assertEqual(sorted(names), sorted(set(names)),
                         "two languages are shown under one name")

    def test_every_name_says_something(self):
        """Falling back to the code means Qt did not recognise it."""
        nameless = sorted(code for code, name in self.offered()
                          if not name or name == code)
        self.assertEqual(nameless, [],
                         "Qt has no name for these, so the menu shows the "
                         "bare code: " + ", ".join(nameless))

    def test_every_override_is_still_needed(self):
        """The one hand-written thing left, kept from rotting.

        An override that now agrees with Qt is a line to delete: it looks like
        a decision and is really just a stale copy.
        """
        from PySide6.QtCore import QLocale

        from pdfarranger_qt.dialogs import _NAME_OVERRIDES

        pointless = {}
        for code, name in _NAME_OVERRIDES.items():
            if QLocale(code.split("@")[0]).nativeLanguageName() == name:
                pointless[code] = name
        self.assertEqual(pointless, {},
                         "Qt now says this itself -- drop the override")

    def test_choosing_each_one_actually_loads_it(self):
        """The check `pl` would have failed: a code that resolves to nothing.

        Comparing lists is not enough on its own -- it says the strings match,
        not that gettext can find a catalogue under that name.
        """
        if not os.path.isdir(os.path.join(ROOT, "build", "mo")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        from pdfarranger_qt import i18n

        try:
            for code, _name in self.offered():
                if code == "en":
                    continue
                with self.subTest(language=code):
                    self.assertEqual(i18n.setup(code), code,
                                     f"{code} is offered but loads nothing")
        finally:
            i18n.setup(None)


class TestNoWordMixesTwoScripts(CatalogueTestCase):
    """A Latin `o` inside a Cyrillic word, and everything like it.

    Russian carried `% oт высоты` -- Latin U+006F where Cyrillic U+043E
    belongs. It renders identically, it survived every check in this file, and
    it came in with a human translation rather than a machine one. The same
    slip nearly reached Croatian from this side: `visеće` with a Cyrillic `е`.

    Whole strings mix scripts all the time and must: `PDF`, `Ctrl+G` and `GNU
    General Public License` appear in every catalogue. So the rule is per
    *word* -- but only across the three alphabets that share letterforms.

    **Latin, Cyrillic and Greek are the confusable set.** `a o e p x` are drawn
    the same in all three, so a word mixing two of them is a typo essentially
    every time. Nothing else is confusable with anything: no Arabic letter can
    be mistaken for a Latin one, and no Hebrew letter for a Greek one.

    That distinction is what makes the check usable, because plenty of
    languages join a foreign word to a native particle with no space at all --
    Arabic writes `وPage` and `لـPDF`, Korean writes `Arranger는`, Japanese
    runs kanji into kana. A rule that flagged any mix would have called all of
    those defects; the first draft did, and the Arabic catalogue is what
    proved it wrong.
    """

    #: The alphabets that share letterforms. Anything outside this is safe to
    #: sit inside a word with anything else.
    CONFUSABLE = frozenset({"LATIN", "CYRILLIC", "GREEK"})

    SCRIPTS = ("LATIN", "CYRILLIC", "GREEK", "HEBREW", "ARABIC", "HAN",
               "HIRAGANA", "KATAKANA", "HANGUL", "GEORGIAN", "ARMENIAN")

    #: A run of letters. `\d` and `_` are excluded so that `Ctrl+G` and
    #: `HKEY_CURRENT_USER` split into their parts rather than reading as one
    #: mixed word.
    WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

    def script_of(self, character):
        import unicodedata

        name = unicodedata.name(character, "")
        for script in self.SCRIPTS:
            if name.startswith(script):
                return script
        return None

    def mixed_words(self, text):
        found = []
        for word in self.WORD.findall(text):
            scripts = {s for s in map(self.script_of, word) if s}
            confusable = sorted(scripts & self.CONFUSABLE)
            if len(confusable) > 1:
                found.append((word, confusable))
        return found

    def test_the_detector_fires_on_a_known_homoglyph(self):
        """Without this, a check measuring nothing would pass forever."""
        cyrillic_o = "% oт высоты"
        self.assertEqual(self.mixed_words(cyrillic_o),
                         [("oт", ["CYRILLIC", "LATIN"])],
                         "the Latin o that was really in ru.po")
        self.assertEqual(self.mixed_words("Izbriši visеće"),
                         [("visеće", ["CYRILLIC", "LATIN"])],
                         "the Cyrillic e that nearly reached hr.po")
        self.assertEqual(self.mixed_words("μίaς"),
                         [("μίaς", ["GREEK", "LATIN"])],
                         "a Latin a in a Greek word")

    def test_it_does_not_fire_on_a_language_that_joins_words(self):
        """The exceptions are orthography, and there are more than one.

        Every one of these was written by hand into a catalogue in this
        repository, and a rule that rejected any mixed word rejected them all.
        """
        for text in ("Arranger는 pikepdf의",       # Korean particles
                     "وPage وHome وEnd",   # Arabic wa-
                     "لـPDF",                    # Arabic li-
                     "PDF Arranger, Ctrl+G",
                     "HKEY_CURRENT_USER"):
            with self.subTest(text=text):
                self.assertEqual(self.mixed_words(text), [])

    def test_no_translation_mixes_scripts_inside_one_word(self):
        for language in self.languages:
            for message in catalogue(language):
                if not message.id:
                    continue
                forms = (message.string
                         if isinstance(message.string, (list, tuple))
                         else [message.string])
                for form in forms:
                    if not form:
                        continue
                    found = self.mixed_words(form)
                    if found:
                        with self.subTest(language=language):
                            self.fail(
                                f"{language}: {found} in {form!r} -- one word "
                                f"drawn from two alphabets that share "
                                f"letterforms, which is a homoglyph typo")
