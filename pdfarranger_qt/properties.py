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

"""The properties form on one mark: *Comment properties*.

Three tabs and a footer, which is Acrobat's shape. **One form, not one per
kind**: the tabs are the same for a highlight and for a reply, and what
differs is the appearance a kind has to offer -- colour and opacity for a
highlight, the same for a note's icon. Measured on both forms in Acrobat on
2026-11-03.

What it writes is three keys and one flag: `/T`, `/Subj`, and `/F` bit 8.
Everything else it shows is read: `/M`, `/CreationDate` and the status
chain, which is a history and is appended to from the menu rather than
edited here.

Nothing in this file reads or writes a document. It is given what the mark
says and reports what was changed, which is the division the note window
and the colour popup already use.
"""

from typing import NamedTuple, Optional, Tuple

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .i18n import gettext_ as _
from .toolstrip import ColourPopup


class Properties(NamedTuple):
    """What a mark says about itself, as the form shows it."""

    #: Who made it: `/T`. Editable.
    author: str = ""
    #: What it is called: `/Subj`, which starts as the name of the tool that
    #: made the mark. Editable, and free text once it is.
    subject: str = ""
    #: `/M` and `/CreationDate`, already in words. Read.
    when: str = ""
    created: str = ""
    #: `/C` and `/CA`, for the appearance tab.
    colour: Optional[Tuple[float, ...]] = None
    opacity: Optional[float] = None
    #: `/F` bit 8.
    locked: bool = False
    #: The status chain, oldest first: ``(author, state, when)`` per link,
    #: already in words. Read -- a status is appended from the menu.
    history: Tuple[Tuple[str, str, str], ...] = ()
    #: Whether this kind has a colour at all. A mark that draws nothing of
    #: its own would show an empty tab.
    has_colour: bool = True
    #: The mark's style, for a kind that has two of them, else None. An
    #: underline is straight or squiggly, and **the style is the subtype**
    #: -- so choosing one here rewrites what the annotation *is*, which no
    #: other control in this form does.
    style: Optional[str] = None
    #: The styles this kind offers, as ``(value, label)`` with the label
    #: already translated. Empty for a kind with one appearance.
    styles: Tuple[Tuple[str, str], ...] = ()


class _Swatch(QPushButton):
    """The colour, shown as the thing you press to change it."""

    SIDE = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colour = None
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setFlat(True)

    def set_colour(self, colour) -> None:
        self._colour = colour
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inner = self.rect().adjusted(5, 5, -5, -5)
        painter.setPen(self.palette().mid().color())
        if self._colour is None:
            painter.drawRect(inner)
            painter.drawLine(inner.topLeft(), inner.bottomRight())
            return
        painter.setBrush(QColor.fromRgbF(*self._colour[:3]))
        painter.drawRect(inner)


class MarkProperties(QDialog):
    """Acrobat's *Comment properties*, for one mark.

    Opened from *Properties...* in the mark's menu and in a reply's. It is
    modal, as Acrobat's is: what it changes is the mark under it, and the
    thread it belongs to is showing behind.
    """

    #: The appearance as it is being changed: ``(colour, opacity)``.
    #: **Live**, as Acrobat's is -- the slider shows on the page while it
    #: is dragged, not when the form is accepted. The window above applies
    #: it; Cancel undoes whatever was applied.
    previewed = Signal(object, object)

    def __init__(self, props: Properties, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Comment properties"))
        self.setModal(True)
        self._was = props
        #: What the appearance tab is holding, which the popup changes as it
        #: is used rather than when it closes.
        self._colour = props.colour
        self._opacity = props.opacity
        #: Set by *Make Properties Default*, which writes nothing to the
        #: file: it is this application's own preference for the next mark.
        self.make_default = False

        outer = QVBoxLayout(self)
        tabs = QTabWidget(self)
        if props.has_colour:
            tabs.addTab(self._appearance(), _("Appearance"))
        tabs.addTab(self._general(props), _("General"))
        tabs.addTab(self._history(props), _("Review History"))
        outer.addWidget(tabs)

        footer = QHBoxLayout()
        self.locked = QCheckBox(_("Locked"), self)
        self.locked.setChecked(props.locked)
        self.locked.toggled.connect(self._lock_changed)
        footer.addWidget(self.locked)
        default = QPushButton(_("Make Properties Default"), self)
        default.clicked.connect(self._make_default)
        footer.addWidget(default)
        footer.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        outer.addLayout(footer)
        self._lock_changed(props.locked)

    # -- the tabs ---------------------------------------------------------

    def _appearance(self) -> QWidget:
        """Colour and opacity, through the palette the rest of this uses.

        **The same popup as the swatch in the tool strip**, rather than a
        second palette of its own: Acrobat's form holds the colours inline,
        but two pickers that have to agree about twenty-one colours and a
        slider are two things to keep in step.
        """
        page = QWidget(self)
        form = QFormLayout(page)
        self.swatch = _Swatch(page)
        self.swatch.set_colour(self._colour)
        self.swatch.clicked.connect(self._pick_colour)
        form.addRow(_("Colour"), self.swatch)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal, page)
        self.slider.setRange(0, 100)
        self.slider.setValue(self._as_percent())
        self.slider.valueChanged.connect(self._slid)
        row.addWidget(self.slider, 1)
        self.percent = QLabel(self._percent(), page)
        self.percent.setMinimumWidth(44)
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.percent)
        form.addRow(_("Opacity"), row)

        if self._was.styles:
            # Beside Colour, as Reader puts it. The entries are the kind's
            # own, because only the kind knows what its styles are.
            self.style = QComboBox(page)
            for value, label in self._was.styles:
                self.style.addItem(label, value)
            at = self.style.findData(self._was.style)
            if at >= 0:
                self.style.setCurrentIndex(at)
            form.addRow(_("Style"), self.style)

        self.palette_popup = ColourPopup(self)
        self.palette_popup.chosen.connect(self._coloured)
        # The popup carries a slider of its own, because it is the strip's
        # picker as well. The two are kept in step rather than one of them
        # being hidden: whichever is used, the other reads the same.
        self.palette_popup.faded.connect(
            lambda value: self.slider.setValue(round(value * 100)))
        return page

    def _general(self, props: Properties) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        self.author = QLineEdit(props.author, page)
        form.addRow(_("Author"), self.author)
        self.subject = QLineEdit(props.subject, page)
        form.addRow(_("Subject"), self.subject)
        form.addRow(_("Date modified"), QLabel(props.when, page))
        form.addRow(_("Created"), QLabel(props.created, page))
        return page

    def _history(self, props: Properties) -> QWidget:
        """The chain, read back. **Composed, not stored**: Acrobat prints
        ``{author}: {state}, {when}`` and the `/Contents` each link carries
        is a sentence it generates for other viewers and does not show."""
        page = QWidget(self)
        box = QVBoxLayout(page)
        rows = QListWidget(page)
        for author, state, when in props.history:
            rows.addItem("%s: %s, %s" % (author, state, when))
        box.addWidget(rows)
        box.addWidget(QLabel(
            _("The Review History lists any change of status for this "
              "comment."), page))
        return page

    # -- what it holds ----------------------------------------------------

    def _as_percent(self) -> int:
        value = 100 if self._opacity is None else round(self._opacity * 100)
        return max(0, min(100, int(value)))

    def _percent(self) -> str:
        return "%d%%" % self._as_percent()

    def _slid(self, value: int) -> None:
        self._opacity = value / 100.0
        self.percent.setText(self._percent())
        self.previewed.emit(self._colour, self._opacity)

    def _pick_colour(self) -> None:
        below = self.swatch.mapToGlobal(QPoint(0, self.swatch.height() + 2))
        self.palette_popup.show_for(self._colour, self._opacity, below)

    def _coloured(self, colour) -> None:
        self._colour = tuple(colour)
        self.swatch.set_colour(self._colour)
        self.previewed.emit(self._colour, self._opacity)

    def _lock_changed(self, on: bool) -> None:
        """A locked mark offers nothing but the way to unlock it.

        **The form is where a lock comes off**, so it opens on a locked
        mark where everything else refuses -- and everything in it that
        would change the mark is refused in turn until the box is cleared.
        Clearing it makes them live without closing the form: the lock is
        a property like the others and changing it here is one action.
        """
        self.author.setEnabled(not on)
        self.subject.setEnabled(not on)
        if self._was.has_colour:
            self.swatch.setEnabled(not on)
            self.slider.setEnabled(not on)
        if self._was.styles:
            self.style.setEnabled(not on)

    def _make_default(self) -> None:
        self.make_default = True

    def changed(self) -> dict:
        """What the form was given and what it holds now, where they differ.

        **Only what changed.** A mark whose colour was touched keeps the
        author and the subject the producer gave it, which is what lets this
        patch a dictionary rather than replace one.
        """
        now = {}
        if self.author.text() != self._was.author:
            now["author"] = self.author.text()
        if self.subject.text() != self._was.subject:
            now["subject"] = self.subject.text()
        if self.locked.isChecked() != self._was.locked:
            now["locked"] = self.locked.isChecked()
        if self._was.has_colour:
            if self._colour != self._was.colour:
                now["colour"] = self._colour
            if self._opacity != self._was.opacity:
                now["opacity"] = self._opacity
        if self._was.styles:
            picked = self.style.currentData()
            if picked != self._was.style:
                now["style"] = picked
        return now

    def keyPressEvent(self, event):
        """Escape closes it, as every dialog does; Return does not accept
        it, because the author and subject boxes are the ones being typed
        in and a stray Return would commit the form under the caret."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)
