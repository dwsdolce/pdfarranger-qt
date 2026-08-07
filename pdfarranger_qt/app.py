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

from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__, __version_string__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pdfarranger-qt", description=APP_NAME)
    parser.add_argument("files", nargs="*", help="PDF or image files to open")
    parser.add_argument("--version", action="version", version=__version_string__)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    app = QApplication(sys.argv[:1])
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
    if paths:
        window.open_paths(paths)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
