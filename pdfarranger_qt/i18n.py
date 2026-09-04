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

"""Translation, on gettext (decision D2).

The upstream `po/` catalogue is reused as-is -- 33 languages -- so message ids
must stay byte-identical to the GTK application's wherever a string is unchanged.
Check `po/` before rewording anything: a reworded string silently loses its
translations in every language.

Unlike upstream this does not touch `libintl`. That dance exists only to bind
GTK's own C-side catalogues; a pure-Python Qt application needs nothing but
`gettext.translation()`.
"""

import gettext
import os
import sys
from typing import List, Optional

DOMAIN = "pdfarranger"

_translation = gettext.NullTranslations()


def locale_dirs() -> List[str]:
    """Candidate locations for compiled catalogues, most specific first."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks datas under sys._MEIPASS -- the `_internal`
        # directory beside the exe in a onedir build, a temporary directory in a
        # onefile one. The exe's own directory holds no catalogues.
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [
        os.path.join(base, "share", "locale"),
        os.path.join(base, "build", "mo"),  # development: `setup.py build` output
    ]


def setup(language: Optional[str] = None) -> str:
    """Install the translation. Returns the language actually used.

    ``language`` of None or "" means follow the environment, which is what the
    "System setting" entry in Preferences will select.
    """
    global _translation
    languages = [language] if language else None
    for directory in locale_dirs():
        if not os.path.isdir(directory):
            continue
        try:
            # No fallback=True here: it returns a NullTranslations on failure,
            # and since GNUTranslations *subclasses* NullTranslations there is
            # then no way to tell success from failure by type. Letting it raise
            # is the only honest signal.
            _translation = gettext.translation(DOMAIN, directory, languages=languages)
        except FileNotFoundError:
            continue
        return language or _translation.info().get("language", "")
    _translation = gettext.NullTranslations()
    return ""


def gettext_(message: str) -> str:
    """Translate. Aliased to ``_`` at every call site."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware translation. Needed for the page counts in the status bar."""
    return _translation.ngettext(singular, plural, n)


def menu_label(message: str) -> str:
    """Translate a GTK-style label and convert its mnemonic to Qt's.

    Upstream msgids carry GTK mnemonics — ``_Open``, ``Save _As…`` — so reusing
    the catalogue means translating the GTK string and rewriting the marker,
    rather than inventing new msgids and abandoning 33 languages of menu
    translations.

    >>> menu_label("Save _As…") == "Save &As…"
    True
    >>> menu_label("Rock __Roll") == "Rock _Roll"
    True
    >>> menu_label("Fish & Chips") == "Fish && Chips"
    True
    """
    text = gettext_(message)
    text = text.replace("&", "&&")     # Qt: literal ampersand
    text = text.replace("__", "\0")    # GTK: literal underscore
    text = text.replace("_", "&")      # GTK mnemonic -> Qt mnemonic
    return text.replace("\0", "_")


#: The conventional short alias. Import as ``from .i18n import gettext_ as _``.
_ = gettext_
