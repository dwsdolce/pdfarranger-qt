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

"""Which fonts may travel with a document, and the one picker that offers them.

Wherever the application lets you choose a font, the text is drawn with the
font embedded, so that the document reads the same on a machine without it.
A font whose licence forbids embedding has no place in that list. Every
TrueType and OpenType font says so itself, in the ``fsType`` field of its
OS/2 table, and Qt hands over the table for any font it offers -- so the
check needs no font library.

Measured on a Mac with 227 families and 730 faces: three faces are
restricted -- Ayuthaya, GB18030 Bitmap and the Black weight of Songti SC --
and Acrobat's font list leaves out exactly those. Qt's own picker shows them
all.
"""

import struct
from typing import Optional, Set

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontDatabase, QRawFont
from PySide6.QtWidgets import QComboBox, QFontComboBox

#: `fsType` bits. *Restricted* forbids embedding unless one of the two that
#: permit it is also set; a font with none of them set is free to embed.
RESTRICTED = 0x0002
PREVIEW_AND_PRINT = 0x0004
EDITABLE = 0x0008

#: The families that may be embedded, worked out once and kept: reading
#: every face is most of a second on a well-stocked machine, and the fonts
#: installed do not change under a running application often enough to
#: notice.
_embeddable: Optional[Set[str]] = None


def face_may_be_embedded(raw: QRawFont) -> bool:
    """Whether one face's licence lets it be embedded.

    A face with no readable OS/2 table states no restriction, and is
    allowed.
    """
    try:
        table = bytes(raw.fontTable("OS/2"))
    except Exception:  # noqa: BLE001 - an unreadable table states nothing
        return True
    if len(table) < 10:
        return True
    flags = struct.unpack(">H", table[8:10])[0]
    return not (flags & RESTRICTED) or bool(flags & (PREVIEW_AND_PRINT
                                                     | EDITABLE))


def family_may_be_embedded(family: str) -> bool:
    """Whether any face of ``family`` may be embedded.

    **By family, because a picker offers families.** One restricted face
    does not take the family with it: Songti SC's Black weight is
    restricted and its others are not, and the picker reaches regular and
    bold, never Black.
    """
    styles = QFontDatabase.styles(family) or [""]
    for style in styles:
        raw = QRawFont.fromFont(QFontDatabase.font(family, style, 12))
        if not raw.isValid() or face_may_be_embedded(raw):
            return True
    return False


def embeddable_families() -> Set[str]:
    """Every installed family with a face that may be embedded."""
    global _embeddable
    if _embeddable is None:
        _embeddable = {family for family in QFontDatabase.families()
                       if family_may_be_embedded(family)}
    return _embeddable


#: Where to go when the font asked for may not be embedded, in order: the
#: same faces the page-number stamp falls back through.
FALLBACKS = ("Helvetica", "Arial", "Liberation Sans", "DejaVu Sans",
             "Segoe UI", "Noto Sans")


class FontChooser(QFontComboBox):
    """The font picker, everywhere one is offered.

    Qt's own, less the families that may not be embedded. Keeping Qt's
    widget keeps what it already does well -- each name drawn in its own
    face, typing to find one -- and filtering its list is all that changes.

    **Filtered again whenever Qt rebuilds the list**, which it does from
    every installed font each time the current font is set; filtering once
    was undone the moment a dialog set the font it opened with. And it is
    editable, so a typed name has to be one of the listed ones too.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filtering = False
        self.setInsertPolicy(QComboBox.NoInsert)
        self.model().modelReset.connect(self._filter)
        self._filter()
        self._kept = self.currentFont()
        if self.lineEdit() is not None:
            self.lineEdit().installEventFilter(self)
            self.lineEdit().editingFinished.connect(self._keep_to_the_list)

    def _filter(self) -> None:
        """Drop the families that may not be embedded from Qt's list."""
        if self._filtering:
            return
        allowed = embeddable_families()
        model = self.model()
        families = model.stringList()
        kept = [family for family in families if family in allowed]
        if len(kept) == len(families):
            return
        # Replacing the list resets the choice to its first entry, so the
        # family that was current is put back -- by row, because setting the
        # font would have Qt rebuild the list all over again.
        current = self.currentText()
        self._filtering = True
        try:
            model.setStringList(kept)
            if current in kept:
                self.setCurrentIndex(kept.index(current))
        finally:
            self._filtering = False

    def setCurrentFont(self, font: QFont) -> None:
        """Show ``font``, or the first fallback that may be embedded.

        A remembered choice can name a font that is no longer offered --
        chosen before this rule, or one restricted on this machine.
        """
        if font.family() not in embeddable_families():
            font = QFont(font)
            font.setFamily(next(
                (f for f in FALLBACKS if f in embeddable_families()),
                next(iter(sorted(embeddable_families())), font.family())))
        super().setCurrentFont(font)
        self._filter()
        self._kept = self.currentFont()

    def eventFilter(self, watched, event) -> bool:
        """Remember the font as it was when typing began: completion
        changes the current font with every letter typed."""
        if event.type() == QEvent.FocusIn and watched is self.lineEdit():
            self._kept = self.currentFont()
        return super().eventFilter(watched, event)

    def _keep_to_the_list(self) -> None:
        """A typed name that is not in the list goes back to the last one
        that was, rather than becoming a font nobody could have chosen."""
        if self.currentText() not in self.model().stringList():
            self.setCurrentFont(self._kept)
