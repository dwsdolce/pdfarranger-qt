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

"""Applying the colour-scheme preference."""

import unittest


def color_schemes_supported() -> bool:
    """The offscreen platform has no colour scheme; it always reports Unknown.

    Verified on a real windows platform that setColorScheme() does take effect
    there (Light -> Dark, palette windowText #000000 -> #ffffff), so these
    assertions are skipped rather than weakened.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Unknown

class TestTheme(unittest.TestCase):
    """Name mapping is always checked; the Qt effect only where the platform has one."""

    def tearDown(self):
        from pdfarranger_qt import theme

        theme.apply(theme.SYSTEM)

    def test_apply_returns_the_scheme_it_set(self):
        from pdfarranger_qt import theme

        self.assertEqual(theme.apply(theme.DARK), theme.DARK)
        self.assertEqual(theme.apply(theme.LIGHT), theme.LIGHT)

    def test_unknown_name_falls_back_to_system(self):
        from pdfarranger_qt import theme

        self.assertEqual(theme.apply("chartreuse"), theme.SYSTEM)

    def test_system_hands_control_back(self):
        from pdfarranger_qt import theme

        theme.apply(theme.DARK)
        self.assertEqual(theme.apply(theme.SYSTEM), theme.SYSTEM)

    def test_dark_reaches_qt(self):
        if not color_schemes_supported():
            self.skipTest("platform has no colour scheme (offscreen)")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        theme.apply(theme.DARK)
        self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                         Qt.ColorScheme.Dark)
        self.assertEqual(theme.current(), theme.DARK)

    def test_light_reaches_qt(self):
        if not color_schemes_supported():
            self.skipTest("platform has no colour scheme (offscreen)")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        theme.apply(theme.LIGHT)
        self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                         Qt.ColorScheme.Light)

    def test_preferences_apply_the_theme_without_a_restart(self):
        from pdfarranger_qt import dialogs, theme
        from pdfarranger_qt.mainwindow import MainWindow

        applied = []
        original_apply = theme.apply
        theme.apply = lambda name: applied.append(name) or original_apply(name)
        self.addCleanup(setattr, theme, "apply", original_apply)

        win = MainWindow()
        self.addCleanup(win.close)

        class Stub:
            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return {**dict(dialogs.PREFERENCES), "theme": "dark", "shortcuts": {}}

        original = dialogs.PreferencesDialog
        dialogs.PreferencesDialog = Stub
        self.addCleanup(setattr, dialogs, "PreferencesDialog", original)

        applied.clear()
        win.edit_preferences()
        self.assertIn("dark", applied, "the theme should be applied, not just stored")
        self.assertEqual(win._preference("theme"), "dark")

    def test_theme_is_applied_at_startup(self):
        from pdfarranger_qt import theme
        from pdfarranger_qt.mainwindow import MainWindow

        applied = []
        original_apply = theme.apply
        theme.apply = lambda name: applied.append(name) or original_apply(name)
        self.addCleanup(setattr, theme, "apply", original_apply)

        win = MainWindow()
        self.addCleanup(win.close)
        self.assertTrue(applied, "startup should apply the stored theme")
