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

"""Process-wide test setup.

Everything here has to happen exactly once, and *before* any test module
imports Qt or builds a window. pytest imports conftest.py first by
construction, which is the only reason this is the right home for it:

- the offscreen platform, chosen before QApplication is constructed
- the single QApplication for the process
- the message-box recorders, installed before any window can raise one

Shared test *helpers* live in ``support.py`` instead; this file is only for
things that must be global and singular.
"""

import atexit
import os
import sys

# The package under test, importable without installing it.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must precede QApplication: Qt reads it at construction.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from pdfarranger_qt.settings import scratch_path  # noqa: E402

#: The one QApplication for the whole run. Qt permits only one, and creating it
#: lazily inside a test makes the first test that runs subtly different.
QT_APP = QApplication.instance() or QApplication(sys.argv[:1])

# Every test run starts from factory defaults.
#
# The redirect itself is in the application, not here: pdfarranger_qt.settings
# .app_settings() switches to a ".tests" organisation whenever
# PYTEST_CURRENT_TEST is set. It cannot be done from a conftest, because
# QSettings.setDefaultFormat has no effect on the
# QSettings(organisation, application) constructor -- an earlier attempt to
# redirect it here looked right and silently kept writing to the real store.
# This wipe is the part that does belong here: it has to happen once, before
# any test builds a window.
#
# The scope is per process (settings.scratch_organisation), so this wipe cannot
# pull the rug from under a second run happening at the same time -- which it
# used to: a suite running in the background made a foreground run of
# tests/test_recent.py fail, because both were clearing and filling one shared
# recent-files list.
_isolated = QSettings(scratch_path(), QSettings.IniFormat)
_isolated.clear()
_isolated.sync()


@atexit.register
def _remove_scratch_settings():
    """Take the process's scratch scope away with it.

    A scope per process means a file per process, and without this they pile up
    -- 595 stray plists accumulated in ~/Library/Preferences from an earlier
    version of this. clear() empties a store without removing it, so the file
    goes too. It is an ini under the temp directory precisely so that this can
    work: deleting a native macOS plist races the asynchronous write-back.
    """
    _isolated.clear()
    _isolated.sync()
    path = _isolated.fileName()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:            # a registry key on Windows, or already gone
        pass

#: Message boxes that would have been shown, as ``(kind, title, text)``.
#: Tests clear this and assert on it; see ``support.last_message_box``.
MESSAGE_BOXES = []


def _recorder(kind, default):
    def handler(_parent, title, text, *args, **kwargs):
        MESSAGE_BOXES.append((kind, title, text))
        return default

    return handler


def _install_message_box_recorders():
    """Stop modal dialogs from wedging the run.

    A modal QMessageBox blocks forever under the offscreen platform, so one
    unexpected warning hangs the entire suite instead of failing a single test.
    Recording them keeps the run alive *and* makes "the user was told why"
    something a test can assert.
    """
    QMessageBox.warning = _recorder("warning", QMessageBox.Ok)
    QMessageBox.information = _recorder("information", QMessageBox.Ok)
    QMessageBox.critical = _recorder("critical", QMessageBox.Ok)
    # Discard, so _confirm_discard() does not try to save during teardown.
    QMessageBox.question = _recorder("question", QMessageBox.Discard)
    QMessageBox.about = _recorder("about", None)


_install_message_box_recorders()
