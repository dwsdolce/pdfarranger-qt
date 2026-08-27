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
    APPLICATION, ORGANISATION, TEST_SUFFIX, app_settings, scratch_path,
    under_test,
)


def scope_file(organisation: str) -> str:
    """Where the running platform keeps the settings for an organisation.

    The three platforms spell a scope differently and only Linux spells it with
    the organisation in it verbatim, as ~/.config/<organisation>/<app>.conf.
    Windows uses a registry key, and macOS a plist named after a bundle
    identifier -- so the test organisation "pdfarranger.tests" arrives as
    com.pdfarranger-tests, its inner dot rewritten to a hyphen because the dot
    is what separates identifier components. Asking Qt for the name keeps these
    tests about which scope the accessor picked rather than about how Qt spells
    it; a literal fragment only matched on two platforms out of three.
    """
    return QSettings(organisation, APPLICATION).fileName()


class TestSettingsScope(unittest.TestCase):

    def test_pytest_is_detected(self):
        self.assertTrue(under_test(), "PYTEST_CURRENT_TEST should be set here")

    def test_settings_are_redirected(self):
        store = app_settings()
        self.assertEqual(store.fileName(), scratch_path())

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
        self.assertEqual(window.settings.fileName(), scratch_path())

    def test_the_scope_is_private_to_this_process(self):
        """Two runs at once must not share a store.

        They did, and it showed up as a flake rather than as anything
        obviously about settings: a suite running in the background made a
        foreground run of the recent-files tests fail, because both were
        clearing and filling the same list. Four concurrent runs, one failure,
        reproducibly.
        """
        import os
        self.assertIn(str(os.getpid()), scratch_path())
        self.assertTrue(os.path.basename(scratch_path())
                        .startswith(ORGANISATION + TEST_SUFFIX))
        self.assertNotEqual(os.path.dirname(scratch_path()), "")

    def test_a_script_can_opt_in_without_pytest(self):
        """The hole that put a fixture in the real recent-files list.

        `under_test` keys off PYTEST_CURRENT_TEST, which only pytest sets, so a
        script run by hand gets the *installed* application's store and writes
        to it on close. This is the deliberate way in.
        """
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(under_test())
            os.environ["PDFARRANGER_QT_TEST_SETTINGS"] = "1"
            self.assertTrue(under_test())

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
