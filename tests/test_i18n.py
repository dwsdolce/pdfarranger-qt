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

"""Translation lookup and the msgid guard."""

import os
import unittest

from support import HERE


class TestI18n(unittest.TestCase):
    """Reusing the upstream catalogue depends on msgids surviving intact."""

    def test_mnemonic_conversion(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("_Open"), "&Open")
        self.assertEqual(menu_label("Save _As…"), "Save &As…")

    def test_literal_underscore_survives(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("Rock __Roll"), "Rock _Roll")

    def test_literal_ampersand_is_escaped_for_qt(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("Fish & Chips"), "Fish && Chips")

    def test_setup_is_safe_without_catalogues(self):
        from pdfarranger_qt import i18n

        i18n.setup()
        self.assertEqual(i18n.gettext_("Unknown file format"), "Unknown file format")

    #: Labels with no upstream equivalent, so no translation to inherit. Adding
    #: to this list should be a deliberate act: check `po/` for an existing
    #: msgid first, because a near-miss silently orphans 33 translations.
    NEW_MSGIDS = {
        "_File",      # menubar titles: upstream is a hamburger popover
        "_Page",
        "_Help",
        "_Duplicate",   # upstream has the action but no translated label
        "_Reset Zoom",  # upstream has no equivalent
        # In upstream's menu.ui but in none of the 33 catalogues:
        # untranslated there too, so nothing is being orphaned.
        "Pass_word",
        # Phase 8: upstream has no equivalent command at all.
        "_Viewer Preferences…",
        "Remove All _Metadata",
        "_Repair Document…",
        "Pages per S_heet…",
        # Upstream builds these two labels as f-strings, so there is no msgid
        # to inherit -- which was the bug: the verb could not be translated.
        "_Undo %s",
        "_Redo %s",
        "Add Page N_umbers…",
        "Add _Watermark…",
    }

    def test_menu_labels_come_from_upstream_msgids(self):
        """Guard against reworded labels silently orphaning the translations.

        Checks every catalogue, not just de.po. A msgid upstream added recently
        may be translated in only a handful of languages -- `Fit _One Page` is
        in six -- and rejecting it because German has not caught up would push
        the label onto NEW_MSGIDS, where it stops being checked at all. The
        question this asks is "does upstream use this string anywhere?".
        """
        import glob
        import re

        catalogues = sorted(glob.glob(
            os.path.join(os.path.dirname(HERE), "po", "*.po")))
        if not catalogues:
            self.skipTest("po/ not present")
        msgids = set()
        for path in catalogues:
            with open(path, encoding="utf-8") as fh:
                msgids |= set(re.findall(r'^msgid "(.*)"$', fh.read(), re.M))

        source = os.path.join(os.path.dirname(HERE), "pdfarranger_qt", "mainwindow.py")
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        # Three shapes, because the window builds its labels three ways: a
        # bare `_m()`, and the `_action`/`_menu` helpers that take the msgid so
        # `retranslate` can produce it again. Watching only `_m()` after that
        # change left this guard checking four labels out of ninety-seven,
        # which is the sort of thing a guard is supposed to prevent, not do.
        used = (re.findall(r'_m\("([^"]+)"\)', text)
                + re.findall(r'_action\("([^"]+)"(?![^)]*mnemonic=False)', text)
                + re.findall(r'_menu\((?:bar|m), "([^"]+)"(?![^)]*mnemonic=False)',
                             text))
        # A floor, not a count: 75 today. It exists so that a refactor which
        # moves the labels somewhere this does not look fails here rather than
        # passing quietly on whatever handful is left.
        self.assertGreater(len(used), 70,
                           f"the label guard found only {len(used)} labels")
        unknown = [u for u in used if u not in msgids and u not in self.NEW_MSGIDS]
        self.assertEqual(
            unknown, [],
            f"msgids absent from every catalogue in po/: {unknown}. Check po/ "
            f"for an existing label before adding these to NEW_MSGIDS.")

class TestTranslations(unittest.TestCase):
    """The catalogues have to actually load, not just be present.

    Run `python tools/build_mo.py` first; these skip if build/mo is absent.
    """

    def setUp(self):
        from pdfarranger_qt import i18n

        self.i18n = i18n
        root = os.path.dirname(HERE)
        if not os.path.isdir(os.path.join(root, "build", "mo", "de")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")

    def tearDown(self):
        self.i18n.setup(None)

    def test_german_translates(self):
        """Regression: setup() reported success while translating nothing.

        GNUTranslations subclasses NullTranslations, so an isinstance check
        could not tell a loaded catalogue from a failed one.
        """
        self.assertEqual(self.i18n.setup("de"), "de")
        self.assertEqual(self.i18n.gettext_("_Save"), "_Speichern")

    def test_mnemonic_conversion_survives_translation(self):
        self.i18n.setup("de")
        self.assertEqual(self.i18n.menu_label("_Save"), "&Speichern")

    def test_translator_may_move_the_mnemonic(self):
        """CJK catalogues put the accelerator in brackets after the word."""
        self.i18n.setup("zh_CN")
        label = self.i18n.menu_label("_Save")
        self.assertIn("&S", label)
        self.assertNotIn("_", label)

    def test_several_languages_load(self):
        for language in ("fr", "sv", "ru", "ja", "pt_BR"):
            self.assertEqual(self.i18n.setup(language), language, language)
            self.assertNotEqual(self.i18n.gettext_("_Open"), "_Open",
                                f"{language} did not translate")

    def test_unknown_language_falls_back_to_msgids(self):
        self.assertEqual(self.i18n.setup("xx"), "")
        self.assertEqual(self.i18n.gettext_("_Open"), "_Open")

    def test_untranslated_string_returns_its_msgid(self):
        """Per-string fallback: a gap shows English, not a blank.

        The msgid is invented rather than borrowed from the interface. This
        test used to assert that "Arrange" was untranslated in German, which
        was true until German reached 100% -- and every real string picked
        instead would fail the same way as the catalogues fill. A string no
        catalogue will ever contain cannot go stale.
        """
        self.i18n.setup("de")
        self.assertEqual(self.i18n.gettext_("Nothing Translates This"),
                         "Nothing Translates This")

    def test_window_builds_translated(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.i18n.setup("de")
        win = MainWindow()
        self.addCleanup(win.close)
        self.assertEqual(win.act_save.text(), "&Speichern")


class TestDoctests(unittest.TestCase):
    def test_i18n_doctests(self):
        import doctest

        from pdfarranger_qt import i18n

        result = doctest.testmod(i18n, verbose=False)
        self.assertEqual(result.failed, 0)
        self.assertGreater(result.attempted, 0, "no doctests found in i18n")


class TestTranslatedInterface(unittest.TestCase):
    """The parts of the interface a catalogue alone does not reach.

    Reported by Lumenman in dwsdolce/pdfarranger-qt#1, which is where these
    three faults were found. Each one made the application *less* usable in a
    language than in English, so each is worth a test that fails without it.
    """

    def tearDown(self):
        from pdfarranger_qt import i18n

        i18n.setup(None)

    def test_a_frozen_build_looks_where_pyinstaller_unpacks(self):
        """Regression: the Windows bundle found no catalogue at all.

        PyInstaller puts datas under sys._MEIPASS -- `_internal/` beside the
        exe -- never in the exe's own directory, so picking any language in
        Preferences silently did nothing in the bundle while working from
        source, which is why nothing caught it.
        """
        import sys
        import unittest.mock

        from pdfarranger_qt import i18n

        meipass = os.path.join("X", "_internal")
        with unittest.mock.patch.object(sys, "frozen", True, create=True), \
             unittest.mock.patch.object(sys, "_MEIPASS", meipass, create=True):
            self.assertEqual(i18n.locale_dirs()[0],
                             os.path.join(meipass, "share", "locale"))

    def test_read_mode_leaves_the_file_menu_alone_when_retitled(self):
        """Regression: a translated window greyed out Open, Save and Quit.

        Retitling the menus stands in for a catalogue, so this needs none
        installed and fails on any machine if the gate goes back to matching
        titles.
        """
        from support import TEST_PDF, settle

        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        self.addCleanup(win.close)
        win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        for action in win.menuBar().actions():
            if action.menu() is not None:
                action.setText(action.text() + " (nicht Englisch)")
        win.set_read_mode(True)
        win._refresh_state()
        for action in (win.act_open, win.act_save, win.act_quit, win.act_repair):
            with self.subTest(action=action.objectName() or action.text()):
                self.assertTrue(action.isEnabled(),
                                "a translated title disabled a File command")
        win.modified = False

    def test_the_menu_roles_are_untranslated(self):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        self.addCleanup(win.close)
        self.assertEqual([role for role, _actions in win._shortcut_groups()],
                         ["File", "Edit", "Page", "Arrange", "View", "Help"])

    def test_the_shortcut_editor_still_shows_translated_headings(self):
        """The role is for deciding; the title is for reading."""
        from pdfarranger_qt import i18n
        from pdfarranger_qt.mainwindow import MainWindow

        root = os.path.dirname(HERE)
        if not os.path.isdir(os.path.join(root, "build", "mo", "de")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")
        i18n.setup("de")
        win = MainWindow()
        self.addCleanup(win.close)
        # Both are translated in German now. When this was written "_File" was
        # not -- it is one of this port's own msgids and no catalogue had it --
        # which is the gap the internationalisation work exists to close.
        self.assertEqual(win._menu_titles["Edit"], "Bearbeiten")
        self.assertEqual(win._menu_titles["File"], "Datei")

    def test_qt_supplies_its_own_buttons_translated(self):
        """OK and Cancel come from Qt, not from the catalogue here."""
        from PySide6.QtWidgets import QApplication

        from pdfarranger_qt.app import install_qt_translations

        app = QApplication.instance()
        if not install_qt_translations(app, "ru"):
            self.skipTest("Qt's own catalogues are not installed")
        self.addCleanup(app.removeTranslator, app._qt_translator)
        self.assertEqual(app.translate("QPlatformTheme", "Cancel"), "Отмена")


class TestExtractable(unittest.TestCase):
    """A string can be translated at runtime and still never be translatable.

    ``_(label)`` on a variable works perfectly and is invisible to the
    extractor, so the msgid never reaches the template and no catalogue can
    ever carry it. `i18n.N_` marks those; this is the guard that they stay
    marked.
    """

    def msgids(self):
        try:
            from babel.messages.extract import extract_from_dir
        except ImportError:
            self.skipTest("babel is not installed")
        root = os.path.join(os.path.dirname(HERE), "pdfarranger_qt")
        keywords = {"_": None, "_m": None, "N_": None, "gettext_": None,
                    "menu_label": None, "ngettext": (1, 2),
                    "_action": None, "_menu": (2,)}
        found = set()
        for _f, _l, message, _c, _x in extract_from_dir(
                root, keywords=keywords, method_map=[("**.py", "python")]):
            for one in (message if isinstance(message, tuple) else (message,)):
                if one:
                    found.add(one)
        return found

    def test_the_theme_names_reach_the_template(self):
        from pdfarranger_qt.dialogs import THEMES

        found = self.msgids()
        for _value, label in THEMES:
            with self.subTest(theme=label):
                self.assertIn(label, found)

    def test_the_strings_that_were_bare_english_are_marked_now(self):
        found = self.msgids()
        for message in ("Untitled", "Rotate", "Duplicate", "Import", "Delete"):
            with self.subTest(message=message):
                self.assertIn(message, found)


class TestQtsOwnTranslations(unittest.TestCase):
    """OK and Cancel come from Qt, and have to follow a language change too."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication

        from pdfarranger_qt.app import install_qt_translations

        self.app = QApplication.instance()
        self.install = install_qt_translations
        if not install_qt_translations(self.app, "ru"):
            self.skipTest("Qt's own catalogues are not installed")
        self.addCleanup(install_qt_translations, self.app, "")

    def cancel(self):
        return self.app.translate("QPlatformTheme", "Cancel")

    def test_a_language_reaches_qts_own_buttons(self):
        self.assertEqual(self.cancel(), "Отмена")

    def test_switching_back_to_english_does_not_leave_the_old_one(self):
        """Regression: Cancel stayed "Отмена" after switching to English.

        Qt consults its translators newest-first and installing another does
        not retire the one underneath. English is the case that shows it,
        because Qt's own strings *are* English -- its catalogue for them
        changes nothing, so there was nothing to paint over the Russian.
        """
        self.install(self.app, "en")
        self.assertEqual(self.cancel(), "Cancel")

    def test_switching_between_two_languages(self):
        self.install(self.app, "de")
        self.assertEqual(self.cancel(), "Abbrechen")
        self.install(self.app, "fr")
        self.assertEqual(self.cancel(), "Annuler")

    def test_only_one_translator_is_ever_installed(self):
        for language in ("ru", "de", "en", "fr", "ru"):
            self.install(self.app, language)
        self.install(self.app, "en")
        self.assertEqual(self.cancel(), "Cancel")


class TestApplicationIcon(unittest.TestCase):
    """The window and taskbar icon, which nothing used to set.

    Without `install_icon` the window inherited whatever the *executable*
    carried: the interpreter's icon when running from source, and a PE resource
    plus Windows' icon cache when frozen. The artwork was bundled by the
    PyInstaller spec all along and never asked for at runtime.
    """

    def test_the_artwork_is_found(self):
        from pdfarranger_qt.app import icon_path

        path = icon_path()
        self.assertIsNotNone(path, "the icon is missing from the source tree")
        self.assertTrue(os.path.isfile(path))

    def test_it_loads_and_is_not_empty(self):
        from PySide6.QtGui import QIcon

        from pdfarranger_qt.app import icon_path

        icon = QIcon(icon_path())
        self.assertFalse(icon.isNull())
        self.assertTrue(icon.availableSizes(), "the .ico carries no images")

    def test_a_window_gets_it(self):
        from PySide6.QtWidgets import QApplication

        from pdfarranger_qt.app import install_icon
        from pdfarranger_qt.mainwindow import MainWindow

        app = QApplication.instance()
        before = app.windowIcon()
        self.addCleanup(app.setWindowIcon, before)
        self.assertTrue(install_icon(app))
        win = MainWindow()
        self.addCleanup(win.close)
        self.assertFalse(win.windowIcon().isNull(),
                         "the window inherited no icon")

    def test_the_frozen_build_looks_where_pyinstaller_puts_it(self):
        import sys
        import unittest.mock

        from pdfarranger_qt.app import icon_path

        with unittest.mock.patch.object(sys, "frozen", True, create=True), \
             unittest.mock.patch.object(sys, "_MEIPASS", "X", create=True):
            # Missing there, so None -- but the point is *where* it looked.
            self.assertIsNone(icon_path())
