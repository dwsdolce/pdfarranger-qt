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

from PySide6.QtCore import QPoint, QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import markup
from .i18n import N_
from .i18n import gettext_ as _
from .toolstrip import ColourPopup

#: What a mark is called in the form's title bar: **the name of the tool
#: that makes it**, which is the only name of it the user has ever seen.
#: `/Subj` never reaches the screen, so a form headed *Cross-Out* names
#: the mark after a word found nowhere in the interface.
#:
#: Reader says Cross-Out there and we say Strikethrough. Deliberate, taken
#: from the owner on 2026-11-06 -- the one place this departs from Reader
#: on purpose rather than for want of a measurement.
#:
#: **By kind and not by tool**, because one tool can make two kinds: the
#: comment tool makes a `/Text` on a point and a `/Highlight` over a run
#: of words, and the second is a Highlight to the user, who sees nothing
#: to tell it from one the highlight tool made. Measured 2026-11-06.
#:
#: **Capitalised throughout**, which Reader is not: it writes a small p on
#: the comment's form alone.
KIND_LABELS = {
    "/Highlight": N_("Highlight"),
    "/Underline": N_("Underline"),
    "/Squiggly": N_("Underline"),
    "/StrikeOut": N_("Strikethrough"),
    "/Text": N_("Comment"),
    # Named apart from the comment mark, because what you can do to it
    # differs:
    # this one has handles and that one does not, and a form headed the
    # same for both would leave you guessing which you had hold of.
    "/Stamp": N_("Scalable Comment"),
    # Not a subtype: *Replace Selected Text* is a strikeout and a caret
    # joined as one mark, and its form is the strikeout's under the mark's
    # own name.
    "replace_text": N_("Replace Selected Text"),
    # A caret on its own is Insert Text; the caret of a Replace pair never
    # opens a form, being reached through its strikeout.
    "/Caret": N_("Insert Text"),
    # What Add Text Comment makes, under Acrobat's name for it.
    "/FreeText": N_("Text Box"),
}


class Properties(NamedTuple):
    """What a mark says about itself, as the form shows it."""

    #: Which kind of annotation it is, for the title. Not `/Subj`, which
    #: the General tab makes free text: renaming a mark does not change
    #: what it *is*, and Reader's title does not follow the renaming.
    kind: str = ""
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
    #: The icon a comment is drawn with, as `/Name`, and the icons it may
    #: be given, as ``(value, label)``. Empty for every kind but `/Text`,
    #: which is the only one with an icon to choose.
    icon: str = ""
    #: Whether the icon list is there to read rather than to change. A
    #: reply has one because it is a `/Text` like the mark it answers, and
    #: changing it would change nothing: the icon drawn on the page is the
    #: comment's, and a reply draws nothing at all.
    icons_fixed: bool = False
    icons: Tuple[Tuple[str, str], ...] = ()
    #: Whether this is a text box, whose Appearance tab is its own: Style,
    #: Border Color and Opacity, then Thickness and Fill Color, laid out as
    #: Acrobat lays them. Its colour is the border's.
    box: bool = False
    fill: Optional[Tuple[float, ...]] = None
    thickness: float = 1.0
    border_style: str = "straight"
    #: Whether the mark grows with the page. Offered only where an icon
    #: is: it is the one place the size is the mark's rather than the
    #: text's. Reader always fixes it and never offers the choice.


def _icon_badge(icon: str, colour) -> QIcon:
    """A comment's icon, small, for the list in the form.

    Drawn from the same paths the file gets -- `canvas` walks them for the
    page and this walks them for the list, so an icon cannot look like one
    thing where it is chosen and another where it lands.
    """
    from .canvas import PageCanvas

    side = 20
    image = QImage(side, side, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    shown = QColor.fromRgbF(*colour[:3]) if colour else QColor(150, 67, 252)
    for path, fill, stroke, width in PageCanvas._icon_drawing(
            None, icon, QRectF(1, 1, side - 2, side - 2), shown):
        painter.setBrush(fill if fill is not None else Qt.NoBrush)
        if stroke is None:
            painter.setPen(Qt.NoPen)
        else:
            pen = QPen(stroke)
            pen.setWidthF(width)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
        painter.drawPath(path)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def _as_number(text: str):
    """``text`` as a percentage from 0 to 100, or None if it is not one."""
    try:
        value = int(text.strip().rstrip("%").strip() or "")
    except ValueError:
        return None
    return max(0, min(100, value))


class _PercentValidator(QValidator):
    """Lets a percentage be typed, and nothing else.

    Intermediate rather than Invalid for an empty field and a bare `%`,
    because a field you cannot clear is a field you cannot retype.
    """

    def validate(self, text: str, position: int):
        stripped = text.strip().rstrip("%").strip()
        if not stripped:
            return (QValidator.Intermediate, text, position)
        if not stripped.isdigit():
            return (QValidator.Invalid, text, position)
        if int(stripped) > 100:
            return (QValidator.Invalid, text, position)
        return (QValidator.Acceptable, text, position)


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
    #: A text box's border and fill as they are being changed, live in the
    #: same way: ``{"fill", "thickness", "border_style"}``.
    restyled = Signal(dict)

    def __init__(self, props: Properties, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title_for(props.kind))
        self.setModal(True)
        self._was = props
        #: What the appearance tab is holding, which the popup changes as it
        #: is used rather than when it closes.
        self._colour = props.colour
        self._opacity = props.opacity
        self._fill = props.fill

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
        #: *Make Properties Default*: a checkbox, beside Locked, which
        #: writes nothing to the file. **Ticking it does nothing by
        #: itself** -- on OK the form's appearance becomes the defaults of
        #: the tool that made the mark, and the box is gone with the
        #: dialog. Cancel does nothing at all. It was a push button that
        #: armed itself the instant it was clicked, so a click followed by
        #: Cancel still changed the defaults, and nothing showed whether
        #: it had been pressed.
        #:
        #: The lock does not disable it: it changes no mark, and Reader
        #: leaves it live too.
        self.make_default_box = QCheckBox(_("Make Properties Default"), self)
        footer.addWidget(self.make_default_box)
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
        if self._was.box:
            return self._box_appearance(page)
        form = QFormLayout(page)
        self.swatch = _Swatch(page)
        self.swatch.set_colour(self._colour)
        self.swatch.clicked.connect(self._pick_colour)
        form.addRow(_("Colour"), self.swatch)

        # **A field you can type into and a slider under it**, both live
        # and both showing the same number, which is how Reader has it.
        # The percentage used to be a label beside the slider, so a mark
        # could only be faded by dragging -- no way to ask for 50 exactly.
        column = QVBoxLayout()
        self.percent = QLineEdit(self._percent(), page)
        self.percent.setValidator(_PercentValidator(self.percent))
        self.percent.setMinimumWidth(80)
        self.percent.editingFinished.connect(self._typed)
        self.percent.textEdited.connect(self._typing)
        column.addWidget(self.percent)
        self.slider = QSlider(Qt.Horizontal, page)
        self.slider.setRange(0, 100)
        self.slider.setValue(self._as_percent())
        self.slider.valueChanged.connect(self._slid)
        column.addWidget(self.slider)
        form.addRow(_("Opacity"), column)

        if self._was.icons:
            # **Above Colour**, as Reader's comment form has it: a list to
            # scroll rather than a drop-down, because seventeen icons are
            # told apart by their drawing and not by their names.
            self.icons = QListWidget(page)
            self.icons.setMaximumHeight(140)
            for value, label in self._was.icons:
                row = QListWidgetItem(label, self.icons)
                row.setData(Qt.UserRole, value)
                row.setIcon(_icon_badge(value, self._colour))
                if value == self._was.icon:
                    self.icons.setCurrentItem(row)
            self.icons.setEnabled(not self._was.icons_fixed)
            form.addRow(_("Icon"), self.icons)

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

    def _opacity_column(self, page) -> QVBoxLayout:
        """The percentage you can type into and the slider under it."""
        column = QVBoxLayout()
        self.percent = QLineEdit(self._percent(), page)
        self.percent.setValidator(_PercentValidator(self.percent))
        self.percent.setMinimumWidth(80)
        self.percent.editingFinished.connect(self._typed)
        self.percent.textEdited.connect(self._typing)
        column.addWidget(self.percent)
        self.slider = QSlider(Qt.Horizontal, page)
        self.slider.setRange(0, 100)
        self.slider.setValue(self._as_percent())
        self.slider.valueChanged.connect(self._slid)
        column.addWidget(self.slider)
        return column

    def _box_appearance(self, page) -> QWidget:
        """A text box's: Style, Border Color and Opacity on the left,
        Thickness and Fill Color on the right, as Acrobat's form has them.

        **Both colours are the twenty-one swatches**, the border's being
        the mark's colour. Acrobat's Fill Color opens the system's colour
        picker, with sliders, a hex value, an opacity of its own and a
        Transparent box -- too much for the fill of a box, and a second
        opacity beside the mark's.
        """
        grid = QGridLayout(page)
        grid.setHorizontalSpacing(24)
        left, right = QFormLayout(), QFormLayout()
        grid.addLayout(left, 0, 0, Qt.AlignTop)
        grid.addLayout(right, 0, 1, Qt.AlignTop)
        self.border_style = QComboBox(page)
        self.border_style.setIconSize(_StyleSample.SIZE)
        for name in markup.BORDER_STYLES:
            if name == "none":
                self.border_style.addItem(_("No Border"), name)
            else:
                self.border_style.addItem(_StyleSample.icon(name, self), "", name)
        at = self.border_style.findData(self._was.border_style)
        self.border_style.setCurrentIndex(max(0, at))
        self.border_style.currentIndexChanged.connect(self._box_changed)
        left.addRow(_("Style"), self.border_style)
        self.swatch = _Swatch(page)
        self.swatch.set_colour(self._colour)
        self.swatch.clicked.connect(self._pick_colour)
        left.addRow(_("Border Colour"), self.swatch)
        left.addRow(_("Opacity"), self._opacity_column(page))
        self.thickness = QSpinBox(page)
        self.thickness.setRange(1, 12)
        self.thickness.setSuffix(" pt")
        self.thickness.setValue(max(1, min(12, round(self._was.thickness or 1))))
        self.thickness.valueChanged.connect(self._box_changed)
        right.addRow(_("Thickness"), self.thickness)
        self.fill_swatch = _Swatch(page)
        self.fill_swatch.set_colour(self._fill)
        self.fill_swatch.clicked.connect(self._pick_fill)
        right.addRow(_("Fill Colour"), self.fill_swatch)
        self.palette_popup = ColourPopup(self)
        self.palette_popup.chosen.connect(self._coloured)
        self.palette_popup.faded.connect(
            lambda value: self.slider.setValue(round(value * 100)))
        self.fill_popup = ColourPopup(self, opacity=False)
        self.fill_popup.chosen.connect(self._filled)
        self._thickness_matters()
        return page

    def _thickness_matters(self) -> None:
        """No Border has no thickness to set."""
        self.thickness.setEnabled(self.border_style.currentData() != "none"
                                  and not self.locked_now())

    def locked_now(self) -> bool:
        box = getattr(self, "locked", None)
        return bool(box is not None and box.isChecked())

    def _box_state(self) -> dict:
        return {"fill": self._fill,
                "thickness": float(self.thickness.value()),
                "border_style": self.border_style.currentData()}

    def _box_changed(self, *_args) -> None:
        self._thickness_matters()
        self.restyled.emit(self._box_state())

    def _pick_fill(self) -> None:
        below = self.fill_swatch.mapToGlobal(
            QPoint(0, self.fill_swatch.height() + 2))
        self.fill_popup.show_for(self._fill or (1.0, 1.0, 1.0), None, below)

    def _filled(self, colour) -> None:
        self._fill = tuple(colour)
        self.fill_swatch.set_colour(self._fill)
        self.restyled.emit(self._box_state())

    @staticmethod
    def title_for(kind: str) -> str:
        """What the title bar says, for a mark of ``kind``.

        The generic name for a kind this application has no name for --
        one read out of somebody else's file, from a tool not built here.
        """
        known = KIND_LABELS.get(kind)
        if known is None:
            # Deliberately the same message as the undo entry for a change
            # made here: the same two words in the same sense, and a string
            # only a mark from a tool we have not built can reach.
            return _("Mark Properties")
        return _("%s Properties") % _(known)

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
        """The slider moved: the field follows and the page previews."""
        self._opacity = value / 100.0
        if self.percent.text() != self._percent():
            self.percent.setText(self._percent())
        self.previewed.emit(self._colour, self._opacity)

    def _typing(self, text: str) -> None:
        """A digit went into the field.

        Live, as the slider is, but without rewriting what is being typed:
        setting the text back would move the cursor and fight the typist.
        A field left half-finished -- empty, or just "%" -- changes
        nothing until it is a number again.
        """
        value = _as_number(text)
        if value is None:
            return
        self._opacity = value / 100.0
        with QSignalBlocker(self.slider):
            self.slider.setValue(value)
        self.previewed.emit(self._colour, self._opacity)

    def _typed(self) -> None:
        """Focus left the field, or Return was pressed: tidy what is in it.

        Whatever was typed is shown back as a percentage -- so `50`
        becomes `50%` and something unreadable becomes the value the mark
        still has, rather than being left looking like it meant something.
        """
        self.percent.setText(self._percent())

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
            # The field as well as the slider: either one of them fades
            # the mark, so leaving it live would leave a way through.
            self.percent.setEnabled(not on)
        if self._was.styles:
            self.style.setEnabled(not on)
        if self._was.icons:
            self.icons.setEnabled(not on and not self._was.icons_fixed)
        if self._was.box:
            self.border_style.setEnabled(not on)
            self.fill_swatch.setEnabled(not on)
            self._thickness_matters()

    @property
    def make_default(self) -> bool:
        """Whether the form was asked to set the tool's defaults."""
        return self.make_default_box.isChecked()

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
        if self._was.box:
            state = self._box_state()
            if state["fill"] != self._was.fill:
                now["fill"] = state["fill"]
            if state["border_style"] != self._was.border_style:
                # With its thickness, which the old style may have had none
                # of: No Border is a width of 0.
                now["border_style"] = state["border_style"]
                now["thickness"] = state["thickness"]
            elif (state["border_style"] != "none"
                  and state["thickness"] != float(self._was.thickness)):
                now["thickness"] = state["thickness"]
        if self._was.icons:
            row = self.icons.currentItem()
            picked = row.data(Qt.UserRole) if row is not None else None
            if picked is not None and picked != self._was.icon:
                now["icon"] = picked
        return now

    def keyPressEvent(self, event):
        """Escape closes it, as every dialog does; Return does not accept
        it, because the author and subject boxes are the ones being typed
        in and a stray Return would commit the form under the caret."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)


class _StyleSample:
    """A border style drawn as a sample, for the Style list -- Acrobat's
    list shows each style as a line and names only No Border."""

    SIZE = QSize(96, 16)

    @staticmethod
    def icon(name: str, widget) -> QIcon:
        style = markup.BORDER_STYLES.get(name, {})
        scale = 2
        pixmap = QPixmap(_StyleSample.SIZE * scale)
        pixmap.fill(Qt.transparent)
        pixmap.setDevicePixelRatio(scale)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(widget.palette().text().color())
        pen.setWidthF(1.2)
        width, height = _StyleSample.SIZE.width(), _StyleSample.SIZE.height()
        middle = height / 2.0
        if "cloud" in style:
            # Scallops along the line, bigger for the large cloud.
            radius = 3.0 if style["cloud"] == 1 else 5.0
            painter.setPen(pen)
            x = 4.0
            while x + 2 * radius <= width - 4:
                painter.drawArc(QRectF(x, middle - radius, 2 * radius,
                                       2 * radius), 0, 180 * 16)
                x += 2 * radius
        else:
            if "dash" in style:
                pen.setDashPattern([v / pen.widthF() for v in style["dash"]])
            painter.setPen(pen)
            painter.drawLine(QPointF(4, middle), QPointF(width - 4, middle))
        painter.end()
        return QIcon(pixmap)
