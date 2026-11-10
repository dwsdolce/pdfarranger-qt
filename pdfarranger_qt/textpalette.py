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

"""The text palette: what styles the words of a text box being typed in.

Acrobat's, read off its panel: the font, the size beside a colour, four
alignments, bold, italic, underline and strikethrough, superscript and
subscript. It opens by itself beside the strip when a box can be typed in,
stays open while the box is being edited, and closes when the editing ends.

**It tells the truth about the selection.** Every control shows what the
selected words have -- a size off the list as its number, a font this
computer lacks by name with "(missing)" -- and is empty where the selection
mixes them; a style is lit only when all of the selection has it. Acrobat
shows the next size up on its list instead, which says the words are a size
they are not.

**It never takes the keyboard from the words.** Its buttons take no focus,
and after a font or size is typed the cursor goes back to the box.
"""

from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
)

from . import fonts, markup, textbox
from .i18n import N_
from .i18n import gettext_ as _
from .toolstrip import ColourPopup, _Swatch, icon_for

#: The alignments, in Acrobat's order, as ``(name, icon, tooltip msgid)``.
ALIGN_BUTTONS = (
    ("left", "format-align-left", N_("Left")),
    ("center", "format-align-center", N_("Centre")),
    ("right", "format-align-right", N_("Right")),
    ("justify", "format-align-justify", N_("Justify")),
)

#: The styles, two rows of them, as ``(how, icon, tooltip msgid)``; ``how``
#: is what the editor's `restyle` takes and `selection_state` reports.
STYLE_ROWS = (
    (("bold", "format-bold", N_("Bold")),
     ("italic", "format-italic", N_("Italic")),
     ("underline", "format-underline", N_("Underline")),
     ("strike", "format-strikethrough", N_("Strikethrough"))),
    (("super", "format-superscript", N_("Superscript")),
     ("sub", "format-subscript", N_("Subscript"))),
)


class TextPalette(QFrame):
    """The panel, working on one editor at a time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._editor = None
        self._colours: Optional[ColourPopup] = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        self.font_box = fonts.FontChooser(self)
        self.font_box.setToolTip(_("Font"))
        # Applied only when a family is picked or a listed name entered:
        # showing the selection's font sets the box too, and that must not
        # restyle anything.
        self.font_box.activated.connect(self._family_chosen)
        outer.addWidget(self.font_box)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.size_box = QComboBox(self)
        self.size_box.setEditable(True)
        self.size_box.setInsertPolicy(QComboBox.NoInsert)
        self.size_box.setToolTip(_("Size"))
        for size in textbox.SIZES:
            self.size_box.addItem(str(size))
        self.size_box.activated.connect(self._size_chosen)
        self.size_box.lineEdit().editingFinished.connect(self._size_typed)
        row.addWidget(self.size_box, 1)
        self.colour = _Swatch((0.0, 0.0, 0.0), _("Text Colour"), self)
        self.colour.setFixedSize(_Swatch.TAIL + 6, _Swatch.TAIL + 6)
        self.colour.clicked.connect(self._open_colours)
        row.addWidget(self.colour)
        outer.addLayout(row)

        self.buttons = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for column, (how, icon, tip) in enumerate(ALIGN_BUTTONS):
            button = self._button(icon, tip)
            button.clicked.connect(lambda _c=False, h=how: self._align(h))
            grid.addWidget(button, 0, column)
            self.buttons[how] = button
        for line, styles in enumerate(STYLE_ROWS, start=1):
            for column, (how, icon, tip) in enumerate(styles):
                button = self._button(icon, tip)
                button.clicked.connect(lambda _c=False, h=how: self._restyle(h))
                grid.addWidget(button, line, column)
                self.buttons[how] = button
        outer.addLayout(grid)
        self.hide()

    def _button(self, icon: str, tip: str) -> QToolButton:
        """A checkable button whose glyph turns the accent colour when lit,
        as Acrobat's do."""
        button = QToolButton(self)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip(_(tip))
        palette = self.palette()
        glyph = QIcon()
        size = 20
        glyph.addPixmap(icon_for(icon, palette.buttonText().color()).pixmap(size),
                        QIcon.Normal, QIcon.Off)
        glyph.addPixmap(icon_for(icon, palette.highlight().color()).pixmap(size),
                        QIcon.Normal, QIcon.On)
        button.setIcon(glyph)
        return button

    # -- following an editor ------------------------------------------------

    def attach(self, editor) -> None:
        """Work on ``editor``, showing what its selection has."""
        self.detach()
        self._editor = editor
        editor.cursorPositionChanged.connect(self.refresh)
        editor.selectionChanged.connect(self.refresh)
        editor.currentCharFormatChanged.connect(self.refresh)
        editor.textChanged.connect(self.refresh)
        editor.destroyed.connect(self._gone)
        self.refresh()

    def detach(self) -> None:
        editor, self._editor = self._editor, None
        if editor is None:
            return
        for signal in (editor.cursorPositionChanged, editor.selectionChanged,
                       editor.currentCharFormatChanged, editor.textChanged):
            try:
                signal.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        if self._colours is not None:
            self._colours.hide()

    def _gone(self, *_args) -> None:
        self._editor = None

    def refresh(self) -> None:
        """Show what the selection has."""
        if self._editor is None:
            return
        state = self._editor.selection_state()
        family = state["family"]
        self.font_box.blockSignals(True)
        if family is None:
            self.font_box.setEditText("")
        elif family in fonts.embeddable_families():
            self.font_box.setCurrentFont(QFont(family))
        else:
            # Shown by name, not replaced by the substitute that draws it.
            self.font_box.setEditText(_("%s (missing)") % family)
        self.font_box.blockSignals(False)
        size = state["size"]
        self.size_box.blockSignals(True)
        self.size_box.setEditText("" if size is None else f"{size:g}")
        self.size_box.blockSignals(False)
        colour = state["colour"]
        self.colour.set_colour(colour if colour is not None else (1.0, 1.0, 1.0))
        self.colour.setToolTip(_("Text Colour"))
        for how, button in self.buttons.items():
            lit = (state["align"] == how if how in textbox.ALIGNMENTS
                   else bool(state.get(how)))
            button.setChecked(lit)

    # -- what the controls do -----------------------------------------------

    def _back_to_the_words(self) -> None:
        if self._editor is not None:
            self._editor.setFocus()
        self.refresh()

    def _family_chosen(self, index: int) -> None:
        if self._editor is None or index < 0:
            return
        self._editor.set_family(self.font_box.itemText(index))
        self._back_to_the_words()

    def _size_chosen(self, index: int) -> None:
        if self._editor is None or index < 0:
            return
        self._editor.set_size(float(textbox.SIZES[index]))
        self._back_to_the_words()

    def _size_typed(self) -> None:
        """A typed size counts only if it is on the list; anything else goes
        back to what the selection has."""
        if self._editor is None:
            return
        typed = self.size_box.currentText().strip()
        try:
            size = float(typed)
        except ValueError:
            size = None
        current = self._editor.selection_state()["size"]
        if size in textbox.SIZES and size != current:
            self._editor.set_size(size)
            self._back_to_the_words()
        else:
            self.refresh()

    def _open_colours(self) -> None:
        if self._editor is None:
            return
        if self._colours is None:
            self._colours = ColourPopup(self, opacity=False)
            self._colours.chosen.connect(self._colour_chosen)
        at = self.colour.mapToGlobal(QPoint(self.colour.width() + 4, 0))
        state = self._editor.selection_state()
        self._colours.show_for(state["colour"] or markup.swatch("Green"),
                               None, at)

    def _colour_chosen(self, colour) -> None:
        if self._editor is not None:
            self._editor.recolour(colour)
            self._back_to_the_words()

    def _align(self, how: str) -> None:
        if self._editor is not None:
            self._editor.align(how)
            self._back_to_the_words()

    def _restyle(self, how: str) -> None:
        if self._editor is None:
            return
        # Superscript and subscript exclude each other without help: both
        # are the one vertical alignment, so setting either replaces the
        # other.
        self._editor.restyle(how)
        self._back_to_the_words()
