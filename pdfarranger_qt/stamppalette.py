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

"""The stamps palette: what the Stamps palette tool places.

One list, the presets drawn as they will be placed -- **our own artwork**,
not Acrobat's, which is Adobe's design -- with no categories, which are
Acrobat's own arrangement. It opens beside the strip while the tool is
armed; the stamp picked in it is the one a click or a drag places, and
*Stamp with date and time* adds the line under its word as it is placed.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from . import markup
from .i18n import gettext_ as _


def preset_picture(name: str, height: int) -> QPixmap:
    """A preset drawn ``height`` pixels tall, as the palette shows it."""
    import pypdfium2 as pdfium

    art = markup.preset_art(name)
    document = pdfium.PdfDocument(art)
    page = document[0]
    _wide, tall = page.get_size()
    picture = page.render(scale=height / tall, fill_color=(255, 255, 255, 0)
                          ).to_pil().convert("RGBA")
    document.close()
    image = QImage(picture.tobytes(), picture.width, picture.height,
                   picture.width * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(image)


class StampPalette(QFrame):
    """The presets, one under another, and the date and time."""

    #: The stamp now picked, by its `/Name`.
    chosen = Signal(str)

    #: How tall a stamp is drawn in the list, in pixels.
    PICTURE = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.stamps = QListWidget(self)
        self.stamps.setIconSize(QSize(180, self.PICTURE))
        self.stamps.setSpacing(2)
        self.stamps.setFocusPolicy(Qt.NoFocus)
        for name, title, _colour, _shape in markup.STAMP_PRESETS:
            row = QListWidgetItem(QIcon(preset_picture(name, self.PICTURE * 2)),
                                  "", self.stamps)
            row.setData(Qt.UserRole, name)
            # The word is in the picture; the name is said for a screen
            # reader and shown on hover.
            row.setToolTip(_(title))
            row.setData(Qt.AccessibleTextRole, _(title))
        self.stamps.setCurrentRow(0)
        self.stamps.setMinimumWidth(200)
        self.stamps.setMinimumHeight(self.PICTURE * 8)
        self.stamps.currentItemChanged.connect(
            lambda row, _was: row is not None and self.chosen.emit(
                row.data(Qt.UserRole)))
        layout.addWidget(self.stamps, 1)
        self.dated = QCheckBox(_("Stamp with date and time"), self)
        self.dated.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.dated)
        self.resize(230, 420)
        self.hide()

    def current(self) -> str:
        """The `/Name` of the stamp picked."""
        row = self.stamps.currentItem()
        return row.data(Qt.UserRole) if row is not None else markup.STAMP_PRESETS[0][0]

    def with_date(self) -> bool:
        return self.dated.isChecked()
