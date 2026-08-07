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

"""The suite must never write to the settings the installed application reads.

It did, for a while: running the tests set the real app to German in a dark
theme, rebound Duplicate to Ctrl+Shift+K, and refilled the recent files list
after the user had cleared it. These are the guards.
"""

import unittest

from PySide6.QtCore import QSettings

from pdfarranger_qt import settings as app_settings_module
from pdfarranger_qt.settings import (
    APPLICATION, ORGANISATION, TEST_SUFFIX, app_settings, under_test,
)


class TestSettingsScope(unittest.TestCase):

    def test_pytest_is_detected(self):
        self.assertTrue(under_test(), "PYTEST_CURRENT_TEST should be set here")

    def test_settings_are_redirected(self):
        store = app_settings()
        self.assertIn(ORGANISATION + TEST_SUFFIX, store.fileName())

    def test_the_real_store_is_untouched(self):
        """Write through the accessor, then read the real scope directly."""
        real = QSettings(ORGANISATION, APPLICATION)
        before = real.value("language")

        store = app_settings()
        store.setValue("language", "zz-sentinel")
        store.sync()
        self.addCleanup(store.remove, "language")

        real.sync()
        self.assertEqual(real.value("language"), before,
                         "the tests wrote into the installed application's settings")
        self.assertNotEqual(real.fileName(), store.fileName())

    def test_the_window_uses_the_accessor(self):
        """A window built in a test must not reach the real store either."""
        from pdfarranger_qt.mainwindow import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        self.assertIn(ORGANISATION + TEST_SUFFIX, window.settings.fileName())

    def test_production_scope_is_unchanged(self):
        """Decision D1: the real scope must not move, or settings are orphaned."""
        self.assertEqual(ORGANISATION, "pdfarranger")
        self.assertEqual(APPLICATION, "pdfarranger_qt")

    def test_no_module_constructs_qsettings_directly(self):
        """One accessor, or the redirect has a hole in it."""
        import os
        import re

        package = os.path.dirname(app_settings_module.__file__)
        offenders = []
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py") or name == "settings.py":
                continue
            with open(os.path.join(package, name), encoding="utf-8") as handle:
                if re.search(r"QSettings\(\s*[\"']", handle.read()):
                    offenders.append(name)
        self.assertEqual(offenders, [],
                         "these build QSettings themselves instead of calling "
                         "settings.app_settings()")
