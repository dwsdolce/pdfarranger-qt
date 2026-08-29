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

import contextlib
import unittest


def color_schemes_supported() -> bool:
    """Whether this platform has a colour scheme at all.

    The offscreen plugin the suite runs under does not: it reports Unknown and
    ignores the setter. Real platforms honour it -- verified on Windows, where
    Light becomes Dark and the palette's windowText flips #000000 to #ffffff,
    and on macOS, where all of these pass under QT_QPA_PLATFORM=cocoa.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Unknown


class RecordingHints:
    """A stand-in for QStyleHints that remembers what it was asked for."""

    def __init__(self):
        from PySide6.QtCore import Qt

        self.calls = []
        self._scheme = Qt.ColorScheme.Unknown

    def setColorScheme(self, scheme):
        self.calls.append(scheme)
        self._scheme = scheme

    def unsetColorScheme(self):
        from PySide6.QtCore import Qt

        self.calls.append(None)          # None is "hand it back to the OS"
        self._scheme = Qt.ColorScheme.Unknown

    def colorScheme(self):
        return self._scheme


@contextlib.contextmanager
def recording_hints():
    """Run `theme.apply` against a stand-in, on any platform.

    These assertions used to be skipped wherever the platform had no colour
    scheme, which is every ordinary run of this suite -- so the two tests that
    mattered most never ran. The fix is the same one the flaky render timing
    got: assert the part that is *ours*.

    What is ours is the call. DARK asks Qt for Qt.ColorScheme.Dark, SYSTEM
    unsets it. Whether the platform then honours that is the platform's
    business, genuinely not this module's, and the tests below still check it
    for real wherever it can be checked.
    """
    from unittest import mock

    from pdfarranger_qt import theme

    hints = RecordingHints()
    stand_in = mock.Mock()
    stand_in.styleHints.return_value = hints
    with mock.patch.object(theme, "QGuiApplication", stand_in):
        yield hints


class TestTheme(unittest.TestCase):
    """What `apply` asks Qt for, checked everywhere; what Qt does with it, where it can be."""

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
        """DARK asks Qt for a dark scheme, and gets one where that is possible."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        with recording_hints() as hints:
            self.assertEqual(theme.apply(theme.DARK), theme.DARK)
            self.assertEqual(hints.calls, [Qt.ColorScheme.Dark])
            self.assertEqual(theme.current(), theme.DARK)

        if color_schemes_supported():
            theme.apply(theme.DARK)
            self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                             Qt.ColorScheme.Dark)
            self.assertEqual(theme.current(), theme.DARK)

    def test_light_reaches_qt(self):
        """And the same for light, which is a different enum and a real mistake."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        with recording_hints() as hints:
            self.assertEqual(theme.apply(theme.LIGHT), theme.LIGHT)
            self.assertEqual(hints.calls, [Qt.ColorScheme.Light])
            self.assertEqual(theme.current(), theme.LIGHT)

        if color_schemes_supported():
            theme.apply(theme.LIGHT)
            self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                             Qt.ColorScheme.Light)

    def test_system_unsets_rather_than_choosing(self):
        """The third branch, which nothing checked before.

        "System" is not a scheme Qt can be set to -- it is `unsetColorScheme`,
        after which Qt follows the OS on its own. Setting Light and calling it
        system would look right in every other test here.
        """
        from pdfarranger_qt import theme

        with recording_hints() as hints:
            self.assertEqual(theme.apply(theme.SYSTEM), theme.SYSTEM)
            self.assertEqual(hints.calls, [None])

    def test_an_unknown_name_also_unsets(self):
        from pdfarranger_qt import theme

        with recording_hints() as hints:
            self.assertEqual(theme.apply("chartreuse"), theme.SYSTEM)
            self.assertEqual(hints.calls, [None])

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
