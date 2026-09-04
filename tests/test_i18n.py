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
import unittest.mock


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
        # Upstream builds this label as a Python f-string, so there is no msgid
        # to inherit -- which is the bug: the verb could not be translated.
        "_Undo %s",
        "_Redo %s",
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
            used = re.findall(r'_m\("([^"]+)"\)', fh.read())
        self.assertTrue(used, "no menu labels found to check")
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

    def test_frozen_looks_where_pyinstaller_unpacks(self):
        """Regression: the Windows bundle found no catalogue at all.

        PyInstaller puts datas under sys._MEIPASS (`_internal/` beside the exe),
        never in the exe's own directory, so every language silently did nothing.
        """
        import sys

        with unittest.mock.patch.object(sys, "frozen", True, create=True),                 unittest.mock.patch.object(sys, "_MEIPASS", os.path.join("X", "_internal"),
                                           create=True):
            self.assertEqual(self.i18n.locale_dirs()[0],
                             os.path.join("X", "_internal", "share", "locale"))

    def test_unknown_language_falls_back_to_msgids(self):
        self.assertEqual(self.i18n.setup("xx"), "")
        self.assertEqual(self.i18n.gettext_("_Open"), "_Open")

    def test_untranslated_string_returns_its_msgid(self):
        self.i18n.setup("de")
        self.assertEqual(self.i18n.gettext_("Arrange"), "Arrange")

    def test_window_builds_translated(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.i18n.setup("de")
        win = MainWindow()
        self.addCleanup(win.close)
        self.assertEqual(win.act_save.text(), "&Speichern")

    def test_qt_supplies_its_own_buttons_translated(self):
        """OK and Cancel come from Qt, not from the catalogue here."""
        from PySide6.QtWidgets import QApplication

        from pdfarranger_qt.app import install_qt_translations

        app = QApplication.instance()
        self.assertTrue(install_qt_translations(app, "ru"))
        self.addCleanup(app.removeTranslator, app._qt_translator)
        self.assertEqual(app.translate("QPlatformTheme", "Cancel"), "Отмена")

    def test_unknown_language_falls_back_to_msgids(self):
        self.assertEqual(self.i18n.setup("xx"), "")
        self.assertEqual(self.i18n.gettext_("_Open"), "_Open")

    def test_untranslated_string_returns_its_msgid(self):
        self.i18n.setup("de")
        self.assertEqual(self.i18n.gettext_("Arrange"), "Arrange")

    def test_window_builds_translated(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.i18n.setup("de")
        win = MainWindow()
        self.addCleanup(win.close)
        self.assertEqual(win.act_save.text(), "&Speichern")

    def test_qt_supplies_its_own_buttons_translated(self):
        """OK and Cancel come from Qt, not from the catalogue here."""
        from PySide6.QtWidgets import QApplication

        from pdfarranger_qt.app import install_qt_translations

        app = QApplication.instance()
        self.assertTrue(install_qt_translations(app, "ru"))
        self.addCleanup(app.removeTranslator, app._qt_translator)
        self.assertEqual(app.translate("QPlatformTheme", "Cancel"), "Отмена")

    def test_read_mode_still_leaves_the_file_menu_alone(self):
        """Regression: a translated window greyed out Open, Save and Quit.

        Read mode disables everything that edits, and the menus it spares were
        matched by their English titles -- which nothing matches once the menu
        bar is in Russian, the one catalogue that carries the Qt edition's own
        menu names.
        """
        from pdfarranger_qt.mainwindow import MainWindow

        self.i18n.setup("ru")
        win = MainWindow()
        self.addCleanup(win.close)
        win.set_read_mode(True)
        self.assertTrue(win.act_open.isEnabled())
        self.assertTrue(win.act_quit.isEnabled())
        self.assertFalse(win.act_rotate_left.isEnabled())


class TestDoctests(unittest.TestCase):
    def test_i18n_doctests(self):
        import doctest

        from pdfarranger_qt import i18n

        result = doctest.testmod(i18n, verbose=False)
        self.assertEqual(result.failed, 0)
        self.assertGreater(result.attempted, 0, "no doctests found in i18n")
