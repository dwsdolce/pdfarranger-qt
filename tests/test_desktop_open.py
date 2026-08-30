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

"""Opening a document from the desktop.

macOS does not put the file on the command line. Setting this application as the
PDF handler and double-clicking one sends an Apple Event, delivered by Qt as a
`QFileOpenEvent` -- and nothing listened for it, so the association worked and
the file was silently dropped. The bundle's own spec said those arrivals came in
"as command-line arguments", which is how it went unnoticed.
"""

import os
import unittest

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from support import HERE, settle

PDF = os.path.join(HERE, "exporter", "outlines.pdf")


class TestTheApplicationHearsTheDesktop(unittest.TestCase):
    """`Application.event` is what was missing entirely."""

    def application(self):
        """The real subclass, without a second QApplication.

        Qt permits only one per process and conftest owns it, so the handler is
        exercised against the class rather than an instance of it.
        """
        from pdfarranger_qt.app import Application

        return Application

    def test_a_file_open_event_is_remembered(self):
        from pdfarranger_qt.app import Application

        seen = []
        held = []
        Application.event(
            _Recorder(held, seen), QFileOpenEvent(QUrl.fromLocalFile(PDF)))
        self.assertEqual(held, [PDF])
        self.assertEqual(seen, [PDF])

    def test_an_empty_path_is_ignored(self):
        from pdfarranger_qt.app import Application

        held, seen = [], []
        Application.event(_Recorder(held, seen),
                          QFileOpenEvent(QUrl.fromLocalFile("")))
        self.assertEqual(held, [])

    def test_the_event_is_swallowed_not_passed_on(self):
        from pdfarranger_qt.app import Application

        handled = Application.event(
            _Recorder([], []), QFileOpenEvent(QUrl.fromLocalFile(PDF)))
        self.assertTrue(handled)


class _Recorder:
    """Stands in for the Application instance, recording what it was told."""

    def __init__(self, pending, emitted):
        self.pending = pending
        self.file_opened = _Signal(emitted)


class _Signal:
    def __init__(self, into):
        self._into = into

    def emit(self, value):
        self._into.append(value)


class TestWhereADesktopDocumentLands(unittest.TestCase):
    """An empty untouched window takes it; anything else gets its own.

    macOS will not launch a second copy of a bundled application, so the event
    arrives in the running one. Opening in place would discard whatever is on
    screen, unsaved work included.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)
        self.win.resize(900, 700)
        self.win.show()
        self.spawned = []
        self.win.new_window = lambda paths=None: self.spawned.append(list(paths or []))
        self.addCleanup(setattr, self.win, "modified", False)

    def open(self, path=PDF):
        from pdfarranger_qt.app import open_from_desktop

        open_from_desktop(self.win, path)
        settle(timeout_ms=400)

    def test_an_empty_window_takes_the_document(self):
        self.assertEqual(self.win.model.rowCount(), 0)
        self.open()
        self.assertEqual(self.win.model.rowCount(), 4)
        self.assertEqual(self.spawned, [], "it opened a second window instead")

    def test_a_window_with_a_document_gets_a_new_one(self):
        self.win.open_paths([PDF])
        settle(timeout_ms=400)
        self.win.modified = False
        self.open()
        self.assertEqual(self.spawned, [[PDF]])
        self.assertEqual(self.win.model.rowCount(), 4,
                         "the open document was replaced")

    def test_an_edited_but_empty_window_is_not_reused(self):
        """Emptiness alone is not enough; the window must be untouched."""
        self.win.modified = True
        self.open()
        self.assertEqual(self.spawned, [[PDF]])

    def test_a_path_that_is_not_there_does_nothing(self):
        self.open(os.path.join(HERE, "no-such-file.pdf"))
        self.assertEqual(self.win.model.rowCount(), 0)
        self.assertEqual(self.spawned, [])


class TestNewWindowCarriesPaths(unittest.TestCase):
    """`new_window` had no way to say what to open, which this needed."""

    def test_the_menu_command_passes_no_paths(self):
        """`triggered` hands the slot the action's checked state.

        With `paths` now a parameter that arrives as `new_window(False)`, which
        is harmless only because the action is not checkable. The connection is
        wrapped so it cannot start depending on that.
        """
        from PySide6.QtCore import QProcess
        from pdfarranger_qt.mainwindow import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(setattr, window, "modified", False)

        captured = []
        original = QProcess.startDetached
        QProcess.startDetached = staticmethod(
            lambda *a, **k: captured.append(a) or (True, 0))
        self.addCleanup(setattr, QProcess, "startDetached", original)

        window.act_new_window.trigger()
        self.assertEqual(len(captured), 1)
        _program, arguments, _cwd = captured[0]
        self.assertNotIn("False", arguments)
        self.assertTrue(all(isinstance(a, str) for a in arguments))

    def test_paths_reach_the_command_line(self):
        import inspect

        from pdfarranger_qt.mainwindow import MainWindow

        signature = inspect.signature(MainWindow.new_window)
        self.assertIn("paths", signature.parameters)
        source = inspect.getsource(MainWindow.new_window)
        self.assertIn("arguments = arguments + ", source)
