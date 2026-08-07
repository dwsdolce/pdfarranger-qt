# Copyright (C) 2026 pdfarranger-qt contributors
# Copyright (C) 2008-2025 pdfarranger contributors
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

"""PDF Arranger Qt.

A PySide6 port of PDF Arranger (https://github.com/pdfarranger/pdfarranger).
The PDF model and pikepdf export logic derive from the original GTK
application; the view layer is a rewrite.
"""

__version__ = "0.1.0"
APP_NAME = "PDF Arranger Qt"

#: Where this port lives. Shown in Help > About and opened by Help > Project on
#: GitHub. pyproject.toml's Homepage must agree; tests/test_packaging.py checks.
PROJECT_URL = "https://github.com/dwsdolce/pdfarranger-qt"

#: The GTK application this is a port of, credited in Help > About.
UPSTREAM_URL = "https://github.com/pdfarranger/pdfarranger"


def _read_build() -> str:
    """The build number: the git commit count for HEAD.

    Two sources, in order:

    1. A frozen build, where ``tools/gen_version_build.py`` wrote ``version_build``
       and the PyInstaller spec bundled it next to the package.
    2. A source checkout, where git can simply be asked.

    Neither is fatal -- an empty build number just means the version renders as
    ``0.1.0`` rather than ``0.1.0 (37)``.
    """
    import os
    import sys

    bundled = getattr(sys, "_MEIPASS", None)
    here = os.path.dirname(os.path.abspath(__file__))
    if bundled:
        try:
            with open(os.path.join(bundled, "version_build"), encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            # Anchored to the package, not the process cwd: the app may well have
            # been launched from the directory of the PDF being opened.
            cwd=os.path.dirname(here),
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


#: Git commit count, or "" when neither a bundle nor a checkout is available.
__build__ = _read_build()

#: What the About box and --version show, e.g. "0.1.0 (37)".
__version_string__ = f"{__version__} ({__build__})" if __build__ else __version__
