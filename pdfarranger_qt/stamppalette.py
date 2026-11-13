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
not Acrobat's, which is Adobe's design -- and then your own, with no
categories, which are Acrobat's own arrangement. It opens beside the strip
while the tool is armed; the stamp picked in it is the one a click or a
drag places, and *Stamp with date and time* adds the line under the words
of one that has words.

**Your own** are added from *Add Stamp*: a text stamp in the presets'
frame, a picture, or the pages of a PDF; and deleted from a right-click,
which is offered on them alone.
"""

import base64

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import markup, stampart
from .i18n import N_
from .i18n import gettext_ as _


def art_picture(art: bytes, height: int) -> QPixmap:
    """A stamp's drawing, ``height`` pixels tall, as the palette shows it."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(art)
    page = document[0]
    _wide, tall = page.get_size()
    picture = page.render(scale=height / tall if tall else 1.0,
                          fill_color=(255, 255, 255, 0)).to_pil().convert("RGBA")
    document.close()
    image = QImage(picture.tobytes(), picture.width, picture.height,
                   picture.width * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(image)


def preset_picture(name: str, height: int) -> QPixmap:
    """A preset drawn ``height`` pixels tall."""
    return art_picture(stampart.preset_art(name), height)


def own_art(record: dict, line: str = "") -> bytes:
    """One of your own stamps' drawing: a text stamp drawn afresh, with
    ``line`` under its words; a picture or a page as it was kept."""
    if record.get("kind") == "text":
        return stampart.framed_art(record.get("words", ""),
                                   tuple(record.get("colour") or markup.swatch("Red")),
                                   line)
    return base64.b64decode(record.get("art", ""))


#: The categories that are always there, as ``(id, label msgid)``; one
#: more is added for each PDF stamps are imported from, named for the file.
CATEGORIES = (("predefined", N_("Predefined")), ("text", N_("Text")),
              ("images", N_("Images")))


def category_of(record: dict) -> str:
    """Which category one of your stamps is in: Text, Images, or the PDF it
    came from -- ``pdf:`` and the file's name."""
    kind = record.get("kind")
    if kind == "text":
        return "text"
    if kind == "image":
        return "images"
    return "pdf:" + (record.get("group") or "PDF")


class _Grip(QWidget):
    """The palette's corner, dragged to resize it. **Not `QSizeGrip`**,
    which resizes the window it is in and on a Mac is not shown at all
    inside one: the palette is a panel in the window, not a window."""

    SIZE = 14

    def __init__(self, palette):
        super().__init__(palette)
        self._palette = palette
        self._start = None
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setToolTip(_("Resize"))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(self.palette().mid().color(), 1.2))
        s = self.SIZE
        for k in (3, 7, 11):
            painter.drawLine(QPointF(s - 1, s - 1 - k), QPointF(s - 1 - k, s - 1))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = (event.globalPosition(), self._palette.size())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._start is None:
            return
        at, size = self._start
        moved = event.globalPosition() - at
        wide = max(self._palette.minimumSizeHint().width(), round(size.width() + moved.x()))
        tall = max(self._palette.minimumSizeHint().height(), round(size.height() + moved.y()))
        host = self._palette.parentWidget()
        if host is not None:
            wide = min(wide, host.width() - self._palette.x())
            tall = min(tall, host.height() - self._palette.y())
        self._palette.resize(wide, tall)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._start = None
        event.accept()


class StampPalette(QFrame):
    """The stamps of one category at a time, as many to a row as its width
    holds, and the date.

    **In categories**, as Acrobat's is -- otherwise a few imported files
    bury the presets: Predefined, Text, Images, and one for each PDF
    imported, named for the file. **Resizable** by its corner, the stamps
    wrapping into as many columns as it is wide."""

    #: The stamp now picked: a preset's `/Name`, or ``own:`` and the id of
    #: one of yours.
    chosen = Signal(str)
    #: *Add Stamp*'s three: "text", "image" or "pdf".
    add_wanted = Signal(str)
    #: Delete on one of yours, by its id.
    delete_wanted = Signal(str)
    #: Delete Category on a PDF's, by its category.
    delete_category_wanted = Signal(str)

    #: How tall a stamp is drawn in the list, in pixels.
    PICTURE = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAutoFillBackground(True)
        self._own = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)
        self.category = QComboBox(self)
        self.category.setFocusPolicy(Qt.NoFocus)
        self.category.setContextMenuPolicy(Qt.CustomContextMenu)
        self.category.customContextMenuRequested.connect(self._category_menu)
        self.category.currentIndexChanged.connect(lambda _k: self._fill())
        layout.addWidget(self.category)
        self.stamps = QListWidget(self)
        # **A grid that wraps**: one column when narrow, as many as fit
        # when the palette is pulled wider.
        self.stamps.setViewMode(QListWidget.IconMode)
        self.stamps.setFlow(QListWidget.LeftToRight)
        self.stamps.setWrapping(True)
        self.stamps.setResizeMode(QListWidget.Adjust)
        self.stamps.setMovement(QListWidget.Static)
        self.stamps.setSpacing(4)
        self.stamps.setFocusPolicy(Qt.NoFocus)
        self.stamps.setMinimumSize(180, self.PICTURE * 4)
        # The stamp picked shown by its whole cell: a stamp has no label,
        # and Qt's own mark of the pick is a bar where the label would be.
        self.stamps.setStyleSheet(
            "QListWidget::item { border-radius: 4px; padding: 2px; }"
            "QListWidget::item:selected { background: palette(highlight); }")
        self.stamps.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stamps.customContextMenuRequested.connect(self._menu)
        self.stamps.currentItemChanged.connect(
            lambda row, _was: row is not None and self.chosen.emit(
                row.data(Qt.UserRole)))
        layout.addWidget(self.stamps, 1)
        self.add = QToolButton(self)
        self.add.setText(_("Add Stamp"))
        self.add.setPopupMode(QToolButton.InstantPopup)
        self.add.setFocusPolicy(Qt.NoFocus)
        adding = QMenu(self.add)
        for how, label in (("text", _("Text...")), ("image", _("Image...")),
                           ("pdf", _("Import from PDF..."))):
            adding.addAction(label).triggered.connect(
                lambda _c=False, h=how: self.add_wanted.emit(h))
        self.add.setMenu(adding)
        layout.addWidget(self.add)
        foot = QHBoxLayout()
        self.dated = QCheckBox(_("Stamp with date and time"), self)
        self.dated.setFocusPolicy(Qt.NoFocus)
        foot.addWidget(self.dated, 1)
        foot.addWidget(_Grip(self), 0, Qt.AlignBottom | Qt.AlignRight)
        layout.addLayout(foot)
        self.show_stamps(())
        self.resize(240, 420)
        self.hide()

    def show_stamps(self, own, category: str = "") -> None:
        """Take ``own``, your stamps' records, into the categories, and show
        ``category`` -- or the one shown, while it is still there."""
        self._own = tuple(own)
        was = category or self.current_category()
        found = [cid for cid, _label in CATEGORIES]
        for record in self._own:
            cid = category_of(record)
            if cid.startswith("pdf:") and cid not in found:
                found.append(cid)
        labels = dict(CATEGORIES)
        self.category.blockSignals(True)
        self.category.clear()
        for cid in found:
            self.category.addItem(_(labels[cid]) if cid in labels else cid[4:], cid)
        at = self.category.findData(was)
        self.category.setCurrentIndex(at if at >= 0 else 0)
        self.category.blockSignals(False)
        self._fill()

    def current_category(self) -> str:
        return self.category.currentData() or "predefined"

    def _fill(self) -> None:
        """The stamps of the category shown, keeping the one picked where
        it is among them."""
        was = self.current() if self.stamps.count() else None
        cid = self.current_category()
        self.stamps.blockSignals(True)
        self.stamps.clear()
        widest = 60
        if cid == "predefined":
            for name, title, _colour, _shape in markup.STAMP_PRESETS:
                widest = max(widest, self._row(
                    name, preset_picture(name, self.PICTURE * 2), _(title)))
        for record in self._own:
            if category_of(record) != cid:
                continue
            try:
                picture = art_picture(own_art(record), self.PICTURE * 2)
            except Exception:  # noqa: BLE001 - a stamp that will not draw
                continue
            widest = max(widest, self._row("own:" + record["id"], picture,
                                           record.get("title", "")))
        widest = min(widest, 240)
        self.stamps.setIconSize(QSize(widest, self.PICTURE))
        self.stamps.setGridSize(QSize(widest + 12, self.PICTURE + 12))
        self.stamps.blockSignals(False)
        keys = [self.stamps.item(k).data(Qt.UserRole) for k in range(self.stamps.count())]
        if keys:
            self.stamps.setCurrentRow(keys.index(was) if was in keys else 0)

    def _row(self, key: str, picture: QPixmap, title: str) -> int:
        """Add a stamp; answer how wide it is drawn, in pixels."""
        row = QListWidgetItem(QIcon(picture), "", self.stamps)
        row.setData(Qt.UserRole, key)
        # The words are in the picture; the title is said for a screen
        # reader and shown on hover.
        row.setToolTip(title)
        row.setData(Qt.AccessibleTextRole, title)
        ratio = picture.devicePixelRatio() or 1.0
        tall = picture.height() / ratio or 1
        return round(picture.width() / ratio * self.PICTURE / tall)

    def _menu(self, at) -> None:
        """Delete, on one of yours alone: the presets cannot be removed."""
        row = self.stamps.itemAt(at)
        key = row.data(Qt.UserRole) if row is not None else ""
        if not key.startswith("own:"):
            return
        menu = QMenu(self)
        menu.addAction(_("Delete")).triggered.connect(
            lambda: self.delete_wanted.emit(key[4:]))
        menu.exec(self.stamps.mapToGlobal(at))

    def _category_menu(self, at) -> None:
        """Delete Category, on a PDF's alone: the others are always there."""
        cid = self.current_category()
        if not cid.startswith("pdf:"):
            return
        menu = QMenu(self)
        menu.addAction(_("Delete Category")).triggered.connect(
            lambda: self.delete_category_wanted.emit(cid))
        menu.exec(self.category.mapToGlobal(at))

    def current(self) -> str:
        """The stamp picked: a preset's `/Name` or ``own:`` and an id."""
        row = self.stamps.currentItem()
        return row.data(Qt.UserRole) if row is not None else markup.STAMP_PRESETS[0][0]

    def with_date(self) -> bool:
        return self.dated.isChecked()


class TextStampDialog(QDialog):
    """A text stamp: your words and a colour from the palette, drawn in
    the presets' frame as they are typed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .toolstrip import ColourPopup, _Swatch

        self.setWindowTitle(_("New Text Stamp"))
        self.colour = markup.swatch("Red")
        form = QFormLayout(self)
        self.words = QLineEdit(self)
        self.words.textChanged.connect(self._preview)
        form.addRow(_("Text"), self.words)
        self.swatch = _Swatch(self.colour, _("Colour"), self)
        self.swatch.clicked.connect(self._pick)
        form.addRow(_("Colour"), self.swatch)
        self.sample = QLabel(self)
        self.sample.setMinimumSize(260, 70)
        self.sample.setAlignment(Qt.AlignCenter)
        form.addRow(self.sample)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        form.addRow(buttons)
        self.popup = ColourPopup(self, opacity=False)
        self.popup.chosen.connect(self._coloured)
        self._preview()

    def _pick(self) -> None:
        below = self.swatch.mapToGlobal(self.swatch.rect().bottomLeft())
        self.popup.show_for(self.colour, None, below, _("Colour"))

    def _coloured(self, colour) -> None:
        if colour:
            self.colour = tuple(colour)
            self.swatch.set_colour(self.colour)
            self._preview()

    def _preview(self) -> None:
        words = self.words.text().strip()
        self.ok.setEnabled(bool(words))
        if not words:
            self.sample.clear()
            return
        self.sample.setPixmap(art_picture(
            stampart.framed_art(words, self.colour), 60))

    def stamp(self) -> dict:
        return {"kind": "text", "words": self.words.text().strip(),
                "colour": list(self.colour), "title": self.words.text().strip()}


class PdfStampsDialog(QDialog):
    """The pages of a PDF as stamps, every one ticked, to keep those
    still ticked."""

    def __init__(self, found, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Import from PDF"))
        self._found = found
        layout = QVBoxLayout(self)
        self.pages = QListWidget(self)
        self.pages.setIconSize(QSize(180, 40))
        for k, (_name, title, art) in enumerate(found):
            try:
                picture = art_picture(art, 80)
            except Exception:  # noqa: BLE001 - a page that will not draw
                continue
            row = QListWidgetItem(QIcon(picture), title, self.pages)
            row.setData(Qt.UserRole, k)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked)
        layout.addWidget(self.pages, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(360, 480)

    def kept(self):
        """``(name, title, drawing)`` for every page left ticked."""
        rows = (self.pages.item(k) for k in range(self.pages.count()))
        return [self._found[row.data(Qt.UserRole)] for row in rows
                if row.checkState() == Qt.Checked]
