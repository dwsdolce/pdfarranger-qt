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

"""Where the application's settings live.

One accessor, so the scope is decided in exactly one place. Every other module
calls :func:`app_settings` rather than constructing ``QSettings`` itself.
"""

import os

from PySide6.QtCore import QSettings

#: Unchanged from before the rename (decision D1): moving it would orphan saved
#: window geometry, zoom and shortcuts. On Windows this is
#: ``HKEY_CURRENT_USER\\Software\\pdfarranger``.
ORGANISATION = "pdfarranger"
APPLICATION = "pdfarranger_qt"

#: Suffix for the scope the tests get. Kept beside the real one so it is obvious
#: they are siblings and neither can be changed without the other.
TEST_SUFFIX = ".tests"


def under_test() -> bool:
    """True while pytest is running a test.

    pytest sets ``PYTEST_CURRENT_TEST`` for the duration of each test's setup,
    call and teardown, which covers every point at which a window is built.
    """
    return "PYTEST_CURRENT_TEST" in os.environ


def app_settings() -> QSettings:
    """The settings store, redirected to a scratch scope under pytest.

    The redirect is here, in the application, rather than in the test harness
    because ``QSettings.setDefaultFormat`` does not affect the
    ``QSettings(organisation, application)`` constructor -- it applies only to
    the argument-less one -- so a conftest cannot take these writes away from
    the registry.

    Without this the suite writes straight into the store the *installed*
    application reads: the preferences round-trip test set the real app to
    German in a dark theme, rebound Duplicate to Ctrl+Shift+K, and the recent
    files tests kept refilling a list the user had just cleared.
    """
    if under_test():
        return QSettings(ORGANISATION + TEST_SUFFIX, APPLICATION)
    return QSettings(ORGANISATION, APPLICATION)
