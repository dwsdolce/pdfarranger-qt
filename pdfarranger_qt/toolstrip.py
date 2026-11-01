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

"""The floating strip the markup tools are chosen from.

A menu cannot hold twenty tools, the attributes each carries, or which one is
armed, and the one this replaces was swept into ``_editing_actions`` -- so it
was disabled in read mode, the only mode its tools act in.

Reader's tool list is permanent furniture because marking up is what Reader is
for. Here the strip is a guest: this application is a page arranger, so it is
summoned from a toolbar button, floats over the reader and can be moved out of
the way of whatever it is covering.

**Nothing here does anything to a document.** A tool can be armed and that is
all; what each one *makes* arrives one tool at a time from step 4.3, together
with its gesture and its attributes. The tail below the family buttons is the
place those attributes will appear and is empty until the first tool brings
some.
"""

from typing import Dict, Optional

import qtawesome as qta
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyleOptionToolButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import tools
from .i18n import gettext_ as _

#: Where the glyphs come from. Material Design Icons, as qtawesome names them.
ICON_SET = "mdi6"

#: The strip's own margin from the corner it first appears in.
INSET = 16

#: Air between the strip and a flyout, so the two read as separate things.
GAP = 4


def icon_for(name: str, colour):
    """One tool's icon, in a colour.

    qtawesome paints the glyph into the image rather than leaving it to the
    style, so the colour has to be supplied and the icon has to be made again
    when the palette changes. `ToolStrip.changeEvent` is where that happens.
    """
    return qta.icon(f"{ICON_SET}.{name}", color=colour)


class FamilyButton(QToolButton):
    """One family, as a split button.

    The button carries the icon of the tool last used in that family and
    re-arms it; the arrow beside it opens the family with a tick on the
    current choice. Read off Reader, which is the only shipping answer to
    "how do twenty tools fit in a row".
    """

    def __init__(self, family: str, parent=None):
        super().__init__(parent)
        self.family = family
        self.setPopupMode(QToolButton.MenuButtonPopup)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setAutoRaise(True)
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        self.actions_by_tool: Dict[str, QAction] = {}

    def add(self, action: QAction) -> None:
        self._menu.addAction(action)
        self.actions_by_tool[action.data()] = action
        if self.defaultAction() is None:
            self.setDefaultAction(action)

    def _arrow_rect(self):
        """Where the style put the menu arrow, which is what opens the flyout."""
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.CC_ToolButton, option, QStyle.SC_ToolButtonMenu, self)

    def mousePressEvent(self, event):
        """Open the flyout ourselves when the arrow is pressed.

        `showMenu` is not virtual, so overriding it does nothing: Qt's own
        implementation runs and places the menu under the button, on top of
        the families below it. Catching the press before Qt sees it is the
        only way to choose where the menu goes.
        """
        if (event.button() == Qt.LeftButton
                and self._arrow_rect().contains(event.position().toPoint())):
            self.open_flyout()
            event.accept()
            return
        super().mousePressEvent(event)

    def open_flyout(self) -> None:
        """Put the family beside the strip, clear of it.

        Beside the *strip* and not beside the button: the button sits inside
        the frame and its margins, so a menu at the button's edge still lands
        on the column it is an alternative to.
        """
        strip = self.parentWidget()
        if strip is None:
            self._menu.popup(self.mapToGlobal(self.rect().topRight()))
            return
        top = self.mapToGlobal(self.rect().topLeft()).y()
        right = strip.mapToGlobal(strip.rect().topRight()).x()
        self._menu.popup(QPoint(right + GAP, top))


class Grip(QWidget):
    """The part of the strip you drag it by.

    The whole frame was draggable before this, which works and tells nobody:
    a panel that can be moved has to say so. Two rows of dots in the style's
    own mid colour, and a move cursor over them, which is what every floating
    palette uses because it is what people already recognise.
    """

    #: Thick enough to hit without aiming, thin enough not to be a title bar.
    EXTENT = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self._from: Optional[QPoint] = None
        self.setCursor(Qt.SizeAllCursor)
        # The strip runs down, so its handle runs across the top.
        self.setFixedHeight(self.EXTENT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._from = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        strip = self.parentWidget()
        if self._from is None or strip is None:
            super().mouseMoveEvent(event)
            return
        where = strip.pos() + event.position().toPoint() - self._from
        host = strip.parentWidget()
        if host is not None:
            # Kept inside the reader. A strip dragged off the edge cannot be
            # dragged back, and there is no other way to move it.
            where.setX(max(0, min(where.x(), host.width() - strip.width())))
            where.setY(max(0, min(where.y(), host.height() - strip.height())))
        strip.move(where)
        event.accept()

    def mouseReleaseEvent(self, event):
        dragging, self._from = self._from is not None, None
        strip = self.parentWidget()
        if dragging and strip is not None:
            strip.moved.emit(strip.pos())
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().mid())
        step, radius = 4, 1.1
        rect = self.rect()
        columns = max(1, (rect.width() - 8) // step)
        x0 = rect.center().x() - (columns - 1) * step / 2
        for row in (-1, 1):
            y = rect.center().y() + row * 2
            for column in range(columns):
                painter.drawEllipse(QPointF(x0 + column * step, y),
                                    radius, radius)

class ToolStrip(QFrame):
    """The strip itself: families across, attributes below, draggable.

    Emits `armed_changed` with the name of the tool now armed. It drives
    nothing by itself -- the window decides what being armed means, and today
    the answer is nothing.
    """

    armed_changed = Signal(str)
    #: Where the strip was left, once a drag finishes. The window remembers
    #: it; the strip does not know what settings are.
    moved = Signal(QPoint)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAutoFillBackground(True)
        # Over the page rather than beside it, and out of the tab order: the
        # reader's own keys must keep working while the strip is up.
        self.setFocusPolicy(Qt.NoFocus)
        self._armed = tools.DEFAULT
        self._drag_from: Optional[QPoint] = None

        #: One group across every family, because arming is exclusive over the
        #: whole strip and not within a family. Without this the tick would
        #: survive in a family nobody is using any more.
        self._group = QActionGroup(self)
        self._group.setExclusive(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(4)

        self.grip = Grip(self)
        outer.addWidget(self.grip)
        self._row = QVBoxLayout()
        self._row.setSpacing(2)
        outer.addLayout(self._row)

        #: Where a tool's own controls will go. Present from the start so the
        #: strip does not change shape the first time a tool brings one.
        self.tail = QWidget(self)
        self.tail_layout = QHBoxLayout(self.tail)
        self.tail_layout.setContentsMargins(0, 0, 0, 0)
        self.tail_layout.setSpacing(4)
        self.tail.setVisible(False)
        outer.addWidget(self.tail)

        if parent is not None:
            parent.installEventFilter(self)
        self.buttons: Dict[str, FamilyButton] = {}
        self._actions: Dict[str, QAction] = {}
        #: One icon per tool per state, because the colour is painted in.
        self._resting: Dict[str, object] = {}
        self._armed_icons: Dict[str, object] = {}
        self._build()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.arm(tools.DEFAULT)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        for family in tools.FAMILIES:
            button = FamilyButton(family, self)
            for tool in tools.in_family(family):
                action = QAction(self)
                action.setData(tool.name)
                action.setCheckable(True)
                action.triggered.connect(
                    lambda _checked=False, name=tool.name: self.arm(name))
                self._group.addAction(action)
                self._actions[tool.name] = action
                button.add(action)
            self._row.addWidget(button)
            self.buttons[family] = button
        self.retranslate()
        self._restyle()

    def retranslate(self) -> None:
        """Labels again, in the language now in force.

        Separate from building because the strip outlives a language change:
        Preferences switches language with the window open.
        """
        for tool in tools.TOOLS:
            self._actions[tool.name].setText(_(tool.label))
        for family, button in self.buttons.items():
            button.setToolTip(_(tools.FAMILY_LABELS[family]))
            default = button.defaultAction()
            if default is not None:
                button.setToolTip(
                    f"{_(tools.FAMILY_LABELS[family])} — {default.text()}")

    def _restyle(self) -> None:
        """Make every icon again in the current palette, and say what is armed.

        Two icons per tool, not one. The armed family is filled with the
        accent colour the way Reader fills it -- otherwise, with the flyouts
        closed, nothing on screen says which tool a drag would use -- and a
        glyph painted in the ordinary foreground disappears against it.
        qtawesome bakes the colour in, so the second colour means a second
        icon.
        """
        palette = self.palette()
        resting = palette.buttonText().color()
        armed = palette.highlightedText().color()
        for tool in tools.TOOLS:
            self._resting[tool.name] = icon_for(tool.icon, resting)
            self._armed_icons[tool.name] = icon_for(tool.icon, armed)
            self._actions[tool.name].setIcon(self._resting[tool.name])
        self.setStyleSheet(
            "QToolButton { border: none; border-radius: 4px; padding: 3px; }"
            "QToolButton:checked { background: %s; }"
            "QToolButton:hover:!checked { background: %s; }"
            % (palette.highlight().color().name(),
               palette.alternateBase().color().name()))
        self._show_armed()

    def _show_armed(self) -> None:
        """Each family button in the colour its state calls for."""
        for family, button in self.buttons.items():
            default = button.defaultAction()
            if default is None:
                continue
            name = default.data()
            icons = self._armed_icons if button.isChecked() else self._resting
            button.setIcon(icons[name])

    def changeEvent(self, event):
        """Rebuild the icons when the palette or the language changes.

        Both arrive as events rather than as signals, and a baked-in colour
        does not follow a switch to dark on its own.
        """
        if event.type() == QEvent.PaletteChange:
            self._restyle()
        elif event.type() == QEvent.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    # -- arming ------------------------------------------------------------

    def armed(self) -> str:
        """Which tool is armed. Never empty: Select is a tool like any other."""
        return self._armed

    def arm(self, name: str) -> None:
        """Arm a tool, and leave it armed.

        A tool is a mode: it stays until another is chosen or Escape is
        pressed, so that marking up twice is two gestures and not four.
        """
        tool = tools.by_name(name)
        action = self._actions[name]
        action.setChecked(True)
        button = self.buttons[tool.family]
        # The family button shows what it will re-arm, which is the last tool
        # used from it rather than a fixed emblem for the family.
        button.setDefaultAction(action)
        self._show_armed()
        self.retranslate()
        if name != self._armed:
            self._armed = name
            self.armed_changed.emit(name)

    def disarm(self) -> None:
        """Back to the pointer, which is what Escape means here."""
        self.arm(tools.DEFAULT)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.disarm()
            return
        super().keyPressEvent(event)

    # -- being a floating thing --------------------------------------------

    def place(self, at: Optional[QPoint] = None) -> None:
        """Put the strip where it goes: where it was left, or inset.

        The default corner is the top left. Not centred, and not over the
        middle of the page: the strip is a guest over somebody's document,
        and the top left is the corner least likely to be the part they are
        reading.
        """
        self.adjustSize()
        self.move(self.clamped(at if at is not None
                               else QPoint(INSET, INSET)))

    def clamped(self, where: QPoint) -> QPoint:
        """``where``, moved until the whole strip is inside the reader.

        A remembered position is a position in a window of some other size:
        a strip dragged to the bottom right of a full-screen window is off
        the edge of a small one, and a strip nobody can see cannot be dragged
        back. So the stored point is a preference and this is the rule.
        """
        host = self.parentWidget()
        if host is None:
            return where
        x = min(max(0, where.x()), max(0, host.width() - self.width()))
        y = min(max(0, where.y()), max(0, host.height() - self.height()))
        return QPoint(x, y)

    def eventFilter(self, watched, event):
        """Follow the reader when it shrinks, for the same reason.

        Watching the parent rather than ourselves: making the window smaller
        can put a strip that was comfortably inside it outside it, and that
        happens without the strip changing size or anybody dragging it.
        """
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.move(self.clamped(self.pos()))
        return super().eventFilter(watched, event)
