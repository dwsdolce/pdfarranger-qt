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

"""Application entry point."""

import argparse
import os
import sys

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__, __version_string__


class Application(QApplication):
    """A QApplication that hears the desktop asking it to open a document.

    On macOS the Finder does **not** put the file on the command line. Opening a
    PDF with this application, dropping one on the Dock icon, or setting it as
    the default handler all send an Apple Event, which Qt delivers as
    `QFileOpenEvent`. Nothing listened for it, so a double-click in the Finder
    did nothing at all -- the bundle declared `CFBundleDocumentTypes` correctly
    and the association worked, and then the file was dropped on the floor.

    (The spec's comment claimed those arrive "as command-line arguments", which
    is how the gap survived being read.)

    The event can arrive before there is a window to put the file in, so paths
    are collected here and the caller takes them when it is ready.
    """

    #: A document the desktop asked for after start-up.
    file_opened = Signal(str)

    def __init__(self, argv):
        super().__init__(argv)
        #: Paths that arrived before anyone was listening.
        self.pending = []

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                self.pending.append(path)
                self.file_opened.emit(path)
            return True
        return super().event(event)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pdfarranger-qt", description=APP_NAME)
    parser.add_argument("files", nargs="*", help="PDF or image files to open")
    parser.add_argument("--version", action="version", version=__version_string__)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    app = Application(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("pdfarranger")

    # Translations must be installed before any widget is built: menu labels and
    # dialog text are translated once, at construction. Hence also why changing
    # the language in Preferences asks for a restart.
    from . import i18n
    from .settings import app_settings

    settings = app_settings()
    i18n.setup(settings.value("language", "") or None)

    # Imported after QApplication exists so QtPdf initialises against a live
    # GUI application object, and after i18n.setup() so its strings are translated.
    from .mainwindow import MainWindow

    window = MainWindow()
    window.show()

    paths = [os.path.abspath(f) for f in args.files if os.path.isfile(f)]
    # Anything the desktop asked for while the window was being built.
    paths += [p for p in app.pending if os.path.isfile(p) and p not in paths]
    app.pending.clear()
    if paths:
        window.open_paths(paths)

    app.file_opened.connect(lambda path: open_from_desktop(window, path))
    return app.exec()


def open_from_desktop(window, path: str):
    """Put a document the Finder handed over somewhere sensible.

    An empty, untouched window takes it; anything else gets a window of its own.
    macOS will not launch a second copy of a bundled application -- it sends the
    event to the one already running -- so opening in place would discard
    whatever was on screen, unsaved work included.

    The empty case is not merely tidiness: at start-up the event can arrive
    after the first window has been built, and this is what puts the document
    the user actually double-clicked into it rather than into a second window
    beside an empty one.
    """
    if not os.path.isfile(path):
        return
    if window.model.rowCount() == 0 and not window.modified:
        window.open_paths([path])
    else:
        window.new_window([path])


if __name__ == "__main__":
    sys.exit(main())
