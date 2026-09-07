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

"""A pseudolocale: every message translated, by machine, to itself plus a mark.

Real catalogues cannot answer "is this string translated at all?", because none
of them is complete -- so a string still in English is indistinguishable from a
call site that was never wired up. A pseudolocale has **100% coverage by
construction**: it is generated from the template, so every msgid the extractor
can see has an entry, and any string that comes out unmarked is a bug rather
than a gap.

It is also stronger than a finished catalogue would be, because a real
translation that happens to match its English msgid -- "PDF", "%" -- cannot be
told apart from a missed one.

The mark goes on the **front**, and callers assert `startswith`. Asserting the
mark appears anywhere is not enough, and that is not a theoretical worry: with
the old ``f"&Undo {label}"`` the text came out ``&Undo <mark>Rotate`` -- marked,
because the label was translated, while the verb welded in front of it never
was. Position is what distinguishes the two.
"""

import os
import tempfile

#: Prefixed to every message. A character no msgid contains, and one that
#: survives the mnemonic conversion `_m` does.
MARK = "»"

#: An unused ISO code, so nothing can confuse it with a language someone speaks.
LOCALE = "zz"

#: Texts that are *not* meant to be translated, and would fail an otherwise
#: total assertion. Hand-maintained, which is the one cost of this technique.
#:
#: A window title is a filename and a proper noun; a page-number box holds a
#: number. Anything added here needs a reason in this list, not just a fix.
EXEMPT_EXACT = {
    "",
    "PDF Arranger Qt",
}


def build(directory=None) -> str:
    """Compile the pseudolocale from ``po/pdfarranger.pot``. Returns its root.

    Built from the *template* rather than from the source, so it inherits the
    extractor's view of what is translatable -- which is the same view
    ``tools/update_pot.py`` and every real catalogue have.
    """
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po

    here = os.path.dirname(os.path.abspath(__file__))
    template = os.path.join(os.path.dirname(here), "po", "pdfarranger.pot")
    with open(template, encoding="utf-8") as handle:
        pot = read_po(handle)

    catalog = Catalog(locale=LOCALE)
    for message in pot:
        if not message.id:
            continue
        if isinstance(message.id, tuple):
            catalog.add(message.id, tuple(MARK + one for one in message.id))
        else:
            catalog.add(message.id, MARK + message.id)

    root = directory or tempfile.mkdtemp(prefix="pseudolocale-")
    messages = os.path.join(root, LOCALE, "LC_MESSAGES")
    os.makedirs(messages, exist_ok=True)
    with open(os.path.join(messages, "pdfarranger.mo"), "wb") as handle:
        write_mo(handle, catalog)
    return root


def install(test_case) -> str:
    """Point i18n at a fresh pseudolocale for the duration of one test."""
    from pdfarranger_qt import i18n

    root = build()
    real = i18n.locale_dirs
    i18n.locale_dirs = lambda: [root]

    def restore():
        i18n.locale_dirs = real
        i18n.setup(None)

    test_case.addCleanup(restore)
    return root


def unmarked(window):
    """Every visible string in ``window`` that did not come from a catalogue.

    Returns a sorted list of ``(what, text)``, empty when the whole window is
    translated. Dynamic text -- a page count, a filename -- is exempt by the
    list above rather than by being skipped, so a new untranslated label shows
    up here instead of hiding.
    """
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMenu

    found = []
    for action in window.findChildren(QAction):
        text = action.text()
        if text and text not in EXEMPT_EXACT and not text.startswith(MARK):
            found.append(("action", text))
    for menu in window.findChildren(QMenu):
        title = menu.title()
        if title and title not in EXEMPT_EXACT and not title.startswith(MARK):
            found.append(("menu", title))
    return sorted(set(found))
