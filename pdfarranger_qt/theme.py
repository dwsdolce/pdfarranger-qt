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

"""Light/dark colour scheme.

Qt follows the operating system by itself, which is what "free in Qt" in the
notes meant -- but only for the *System* setting. Overriding it needs
``QStyleHints.setColorScheme()``, added in Qt 6.8.

The page thumbnails deliberately stay white in dark mode: they are paper, and
the delegate paints the sheet explicitly rather than from the palette. Only the
surrounding chrome follows the scheme.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"

_SCHEMES = {
    LIGHT: Qt.ColorScheme.Light,
    DARK: Qt.ColorScheme.Dark,
}


def apply(name: str) -> str:
    """Apply a colour scheme by name. Returns the name actually applied."""
    hints = QGuiApplication.styleHints()
    if hints is None:  # no GUI application yet
        return SYSTEM
    if name in _SCHEMES:
        hints.setColorScheme(_SCHEMES[name])
        return name
    # Anything unrecognised, including "system", hands control back to the OS.
    hints.unsetColorScheme()
    return SYSTEM


def current() -> str:
    """The scheme in effect, resolving "system" to what the OS chose."""
    hints = QGuiApplication.styleHints()
    if hints is None:
        return SYSTEM
    scheme = hints.colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return DARK
    if scheme == Qt.ColorScheme.Light:
        return LIGHT
    return SYSTEM
