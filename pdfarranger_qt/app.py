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
import logging
import os
import sys
from typing import Optional

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QTranslator, Signal
from PySide6.QtGui import QIcon
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

    #: The most windows one process will open from desktop events, and the
    #: seconds that allowance covers.
    SPAWN_LIMIT = 4
    SPAWN_WINDOW = 10.0

    def __init__(self, argv):
        super().__init__(argv)
        #: Paths that arrived before anyone was listening.
        self.pending = []
        #: When this process last opened a window for a desktop document.
        self._spawns = []

    def may_spawn(self, now=None) -> bool:
        """Whether another window may be opened for a desktop document.

        A backstop, not the mechanism -- `MainWindow.holds` is what actually
        stops a document being reopened by the process launched to open it.
        This exists because that guard compares paths, and a guard that can be
        fooled sits on a path that creates processes.

        The first version of this had no such limit. A stale open-event reaching
        each newly launched process made every one of them launch another, and
        it took a forced reboot to stop. Four windows in ten seconds is far more
        than anyone opens by hand and stops a runaway in well under a second.
        """
        import time

        now = time.monotonic() if now is None else now
        self._spawns = [t for t in self._spawns if now - t < self.SPAWN_WINDOW]
        if len(self._spawns) >= self.SPAWN_LIMIT:
            return False
        self._spawns.append(now)
        return True

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                self.pending.append(path)
                self.file_opened.emit(path)
            return True
        return super().event(event)


def install_qt_translations(app, language: str = "") -> bool:
    """Translate the strings Qt itself supplies: OK, Cancel, Save, Discard.

    Every dialog button comes from Qt rather than from this application, so the
    gettext catalogue never sees them and they stayed English in an otherwise
    translated window. Qt ships catalogues of its own; they only have to be
    asked for.

    The one installed last time is removed first. Without that, switching from
    Russian back to English left "Отмена" on every Cancel button: Qt consults
    its translators newest-first, and installing another one does not retire
    the one underneath. English is the case that shows it, because Qt's own
    strings *are* English and its catalogue for them changes nothing -- so
    there was nothing to paint over the Russian.
    """
    previous = getattr(app, "_qt_translator", None)
    if previous is not None:
        app.removeTranslator(previous)
        app._qt_translator = None

    translator = QTranslator(app)
    locale = QLocale(language) if language else QLocale.system()
    directories = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    if getattr(sys, "frozen", False):
        # PyInstaller keeps them beside the PySide6 package it bundled.
        directories.append(os.path.join(sys._MEIPASS, "PySide6", "translations"))
    for directory in directories:
        if translator.load(locale, "qtbase", "_", directory):
            app.installTranslator(translator)
            # Held by the application: a translator that is garbage collected
            # takes its translations with it.
            app._qt_translator = translator
            return True
    return False


def icon_path() -> Optional[str]:
    """Where the application's artwork is, or None if it is not there.

    Beside the package when running from source or a wheel, and under
    ``sys._MEIPASS`` in a bundle -- the same two cases `i18n.locale_dirs`
    distinguishes, and for the same reason.
    """
    if getattr(sys, "frozen", False):
        candidates = [os.path.join(sys._MEIPASS, "pdfarranger.ico")]
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [os.path.join(root, "data", "pdfarranger.ico")]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def install_icon(app) -> bool:
    """Give the application its own icon, rather than inheriting one.

    Nothing ever called ``setWindowIcon``: on Windows the title bar and taskbar
    fell back to whatever icon the *executable* carried, which is the
    interpreter's when running from source and depends on a PE resource plus
    Windows' icon cache when frozen. The artwork was already being bundled by
    the PyInstaller spec and simply never asked for at runtime.
    """
    path = icon_path()
    if path is None:
        return False
    icon = QIcon(path)
    if icon.isNull():
        return False
    app.setWindowIcon(icon)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pdfarranger-qt", description=APP_NAME)
    parser.add_argument("files", nargs="*", help="PDF or image files to open")
    parser.add_argument("--version", action="version", version=__version_string__)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    app = Application(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("pdfarranger")
    install_icon(app)

    # Translations must be installed before any widget is built: menu labels and
    # dialog text are translated once, at construction. Hence also why changing
    # the language in Preferences asks for a restart.
    from . import i18n
    from .settings import app_settings

    settings = app_settings()
    language = i18n.setup(settings.value("language", "") or None)
    install_qt_translations(app, language)

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

    app.file_opened.connect(
        lambda path: open_from_desktop(window, path, app))
    return app.exec()


def open_from_desktop(window, path: str, app=None):
    """Put a document the Finder handed over somewhere sensible.

    An empty, untouched window takes it; anything else gets a window of its own,
    so that two documents can be read side by side -- which is the whole point
    of opening a second one. macOS will not launch a second copy of a bundled
    application; it sends the event to the process already running.

    **A document this window already holds is ignored**, and that is not a
    nicety. The first version asked only whether the window was empty, and a
    process launched to open a document fills its window from the command line
    before the event arrives -- so the answer was always "not empty", and every
    new process launched another. Hundreds of them, ended by a forced reboot.
    The window has to recognise the document, not merely notice it has one.

    `Application.may_spawn` is the backstop behind that, because this guard
    compares paths and a fallible guard on a path that creates processes wants
    something absolute behind it.
    """
    if not os.path.isfile(path):
        return
    if window.holds(path):
        return
    if window.model.rowCount() == 0 and not window.modified:
        window.open_paths([path])
        return
    if app is not None and not app.may_spawn():
        logging.getLogger(__name__).warning(
            "refusing to open more windows for desktop documents: %s", path)
        return
    window.new_window([path])


if __name__ == "__main__":
    sys.exit(main())
