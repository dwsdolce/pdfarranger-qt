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

"""The pop-up note on a mark: a thread, shown and edited in place.

**It is a list, not a text box.** The first item is the mark's own note and
the rest are the replies, each with an author, a time and its text. Only the
item you have selected shows an editor, and the rest are read. That is what
Reader does, and it is why this cannot be a line edit beside the mark: a
highlight with two replies is three authors and three editable texts in one
window.

The window belongs to the mark and shows what the mark already says. Nothing
here reads or writes a document -- it reports what was typed and the window
above it decides what that means, the same division the colour popup and the
bar of buttons use.
"""

import datetime
from html import escape
from typing import List, NamedTuple, Optional

from PySide6.QtCore import (
    QDate,
    QDateTime,
    QEvent,
    QLocale,
    QRect,
    QSize,
    Qt,
    QTime,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPixmap,
    QTextCharFormat,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOption,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .i18n import N_
from .i18n import gettext_ as _
from .markup import PALETTE, parse_pdf_date


def when_text(value, now=None) -> str:
    """How a note's header says when: a clock today, a date before that.

    Reader's own forms, read off a thread whose note said `10:13 PM` and
    whose reply from the day before said `Nov 1`.

    **Through `QLocale`, not through the catalogues.** Writing the month
    names out would be twelve more strings in each of 33 catalogues for
    something every system already knows -- and it would name the months in
    the application's language rather than the reader's, which is not the
    same thing for a date.
    """
    when = parse_pdf_date(value)
    if when is None:
        return ""
    locale = QLocale()
    stamp = QDateTime(QDate(when.year, when.month, when.day),
                      QTime(when.hour, when.minute, when.second))
    today = (now or datetime.datetime.now()).date()
    if when.date() == today:
        return locale.toString(stamp.time(), QLocale.FormatType.ShortFormat)
    return "%s %d" % (locale.monthName(when.month,
                                       QLocale.FormatType.ShortFormat),
                      when.day)


class Item(NamedTuple):
    """One line of the thread: the note itself, or one reply."""

    #: Who wrote it. The login name for anything this application makes.
    author: str
    #: When, already in the form it should read: a clock for today and a
    #: date for anything older, which is how Reader shows them.
    when: str
    #: What it says.
    text: str
    #: The current status, or None when it has none.
    status: Optional[str] = None
    #: What the item says *with its styling*, as Qt rich text, when the
    #: file carried a `/RC` that styles anything. None when it does not,
    #: and then `text` is the whole of what it says.
    rich: Optional[str] = None
    #: Whether this item is locked -- `/F` bit 8 on its own annotation. A
    #: locked item is read: its editor does not open, however it is
    #: reached. The rest of the thread is unaffected.
    locked: bool = False
    #: The item's own `/C`, as an ``(r, g, b)`` of floats, or None. Each
    #: reply carries one and nothing on the page shows it -- so it is shown
    #: here, on the line that names who wrote it.
    colour: Optional[tuple] = None


class Grip(QWidget):
    """The corner the window is resized by.

    **Not `QSizeGrip`.** That one resizes the top level *window*, which it
    finds by walking up the parents -- and this panel's parents lead to the
    application window, so dragging it aimed at that instead and the panel
    itself could not be resized at all.
    """

    #: How big the corner is, in pixels.
    SIDE = 14

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel
        self._from = None
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.SizeFDiagCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._from = (event.globalPosition().toPoint(),
                          self._panel.size())
            self._panel.being_sized()

    def mouseMoveEvent(self, event):
        if self._from is None:
            return
        start, size = self._from
        moved = event.globalPosition().toPoint() - start
        self._panel.resize(size.width() + moved.x(),
                           size.height() + moved.y())

    def mouseReleaseEvent(self, event):
        self._from = None

    def paintEvent(self, event):
        """Three short strokes across the corner, as every other one is."""
        painter = QPainter(self)
        painter.setPen(self.palette().mid().color())
        for step in (4, 8, 12):
            painter.drawLine(self.SIDE - step, self.SIDE - 2,
                             self.SIDE - 2, self.SIDE - step)


class NoteEditor(QTextEdit):
    """The box one item is written in.

    **Rich, not plain.** A note carries limited styling -- bold, italic,
    underline, super and subscript -- and the file keeps it in `/RC` beside
    the plain `/Contents`. A `QPlainTextEdit` cannot hold any of it, so
    text that arrived styled would have been flattened the first time
    anybody posted an edit to it.
    """

    #: What *Text Style* can set, as ``(msgid, shortcut, how)``. The three
    #: with shortcuts are the ones Qt binds itself, and the entries say so
    #: rather than binding them again.
    STYLES = (
        (N_("Bold"), "Ctrl+B", "bold"),
        (N_("Italic"), "Ctrl+I", "italic"),
        (N_("Underline"), "Ctrl+U", "underline"),
        (N_("Superscript"), "", "super"),
        (N_("Subscript"), "", "sub"),
    )

    def contextMenuEvent(self, event):
        """Qt's own editing menu, with *Text Style* under it.

        Undo, Cut, Copy, Paste and Select All come from Qt and are the
        same entries every other text box in the application has. Spelling
        and dictionary entries are not here: they are services of the
        platform's own text system, which Qt does not hand us.
        """
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        styles = menu.addMenu(_("Text Style"))
        for msgid, shortcut, how in self.STYLES:
            act = styles.addAction(_(msgid))
            if shortcut:
                act.setShortcut(shortcut)
            act.setCheckable(True)
            act.setChecked(self._is(how))
            act.triggered.connect(
                lambda _checked=False, which=how: self.restyle(which))
        styles.addSeparator()
        # **A colour for the words, not for the mark.** Reader sets this
        # from the note's own properties form, over whatever text is
        # selected; here it belongs beside the other things that style a
        # run. It is the one entry in this menu Reader does not have in
        # this place, which the owner settled on 2026-11-03.
        inks = styles.addMenu(_("Text Colour"))
        for name, rgb in PALETTE:
            ink = inks.addAction(_swatch_icon(rgb), _(name))
            ink.triggered.connect(
                lambda _checked=False, colour=rgb: self.recolour(colour))
        styles.addSeparator()
        clear = styles.addAction(_("Clear Formatting"))
        clear.triggered.connect(lambda: self.restyle("clear"))
        menu.exec(event.globalPos())

    def recolour(self, rgb) -> None:
        """Colour the selection, or what is typed next."""
        fmt = QTextCharFormat()
        fmt.setForeground(QColor.fromRgbF(*rgb[:3]))
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    def _is(self, how: str) -> bool:
        """Whether what is selected already carries this."""
        fmt = self.currentCharFormat()
        if how == "bold":
            return fmt.fontWeight() >= QFont.Weight.Bold
        if how == "italic":
            return fmt.fontItalic()
        if how == "underline":
            return fmt.fontUnderline()
        if how == "strike":
            return fmt.fontStrikeOut()
        if how == "super":
            return (fmt.verticalAlignment()
                    == QTextCharFormat.VerticalAlignment.AlignSuperScript)
        if how == "sub":
            return (fmt.verticalAlignment()
                    == QTextCharFormat.VerticalAlignment.AlignSubScript)
        return False

    def restyle(self, how: str) -> None:
        """Turn one style on or off over the selection.

        With nothing selected it sets what the *next* thing typed carries,
        which is how every editor behaves and what `mergeCharFormat` on an
        empty cursor does for nothing.
        """
        fmt = QTextCharFormat()
        on = not self._is(how)
        if how == "bold":
            fmt.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        elif how == "italic":
            fmt.setFontItalic(on)
        elif how == "underline":
            fmt.setFontUnderline(on)
        elif how == "strike":
            fmt.setFontStrikeOut(on)
        elif how in ("super", "sub"):
            fmt.setVerticalAlignment(
                (QTextCharFormat.VerticalAlignment.AlignSuperScript
                 if how == "super"
                 else QTextCharFormat.VerticalAlignment.AlignSubScript)
                if on else QTextCharFormat.VerticalAlignment.AlignNormal)
        elif how == "clear":
            # Replaced rather than merged: merging only applies what a
            # format *sets*, so a merge can turn a style on and never off
            # again -- the colour especially, which has no "none" to set.
            bare = QTextCharFormat()
            cursor = self.textCursor()
            if cursor.hasSelection():
                cursor.setCharFormat(bare)
            self.setCurrentCharFormat(bare)
            return
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    def runs(self):
        """What is written here, as lines of ``(text, style)``.

        The style names only what is set, so a run with nothing on it comes
        back with an empty one -- which is what tells `rich_from_runs` that
        a note has no styling and belongs in `/Contents` alone.
        """
        lines = []
        block = self.document().begin()
        while block.isValid():
            line = []
            piece = block.begin()
            while not piece.atEnd():
                fragment = piece.fragment()
                if fragment.isValid() and fragment.text():
                    line.append((fragment.text(),
                                 _style_of(fragment.charFormat())))
                piece += 1
            lines.append(line)
            block = block.next()
        return lines


def _swatch_icon(rgb) -> QIcon:
    """A filled square, so a colour's name is not the only way to tell."""
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor.fromRgbF(*rgb[:3]))
    return QIcon(pixmap)


def html_of(runs) -> Optional[str]:
    """Styled runs as the fragment an item is drawn with.

    The same shape `markup.rich_to_html` makes of `/RC`, from the other
    side: what was just typed, for the item it was typed into. Without it
    a posted item was redrawn from the rich text it arrived with -- which
    for a note that arrived plain is none, so styling a note and pressing
    Post showed the words going back to plain.

    None when nothing is styled, which leaves the item plain text.
    """
    lines, styled = [], False
    for line in runs:
        out = []
        for text, style in line:
            said = escape(text)
            if style:
                styled = True
                out.append('<span style="%s">%s</span>' % (
                    ";".join("%s:%s" % pair for pair in sorted(style.items())),
                    said))
            else:
                out.append(said)
        lines.append("".join(out))
    return "<br>".join(lines) if styled else None


def _style_of(fmt) -> dict:
    """One run's character format as the properties `/RC` names them."""
    style = {}
    if fmt.fontWeight() >= QFont.Weight.Bold:
        style["font-weight"] = "bold"
    if fmt.fontItalic():
        style["font-style"] = "italic"
    decoration = " ".join(word for word, on in (
        ("underline", fmt.fontUnderline()), ("line-through", fmt.fontStrikeOut()))
        if on)
    if decoration:
        style["text-decoration"] = decoration
    where = fmt.verticalAlignment()
    if where == QTextCharFormat.VerticalAlignment.AlignSuperScript:
        style["vertical-align"] = "super"
    elif where == QTextCharFormat.VerticalAlignment.AlignSubScript:
        style["vertical-align"] = "sub"
    if fmt.hasProperty(QTextFormat.Property.ForegroundBrush):
        # **Kept even though nothing here can set it.** Reader colours the
        # words you have selected from the note's own properties form; this
        # window has no way to ask for that, but it has every way to lose
        # it -- the colours would go the first time anybody posted an edit
        # to a reply that had them.
        style["color"] = fmt.foreground().color().name().upper()
    return style


class NotePanel(QWidget):
    """The thread on one mark, floating over the page.

    Opened from *Open Pop-Up Note*. **The item selected on opening is always
    the first**, the note itself, however many replies are under it -- which
    is Reader's behaviour and is not what a chat window would do.
    """

    #: An item was posted: ``(which, text)``. Never empty -- Post is refused
    #: on an empty editor, so a note cannot be emptied by posting nothing.
    posted = Signal(int, str)
    #: The window was closed, by the cross or by Escape.
    closed = Signal()
    #: A context menu was asked for: ``(which, where)``, the item it was
    #: asked over -- `NOTHING` for the window's own background -- and the
    #: screen point to put it at. **The window above decides what goes in
    #: it**, because what the entries do is delete marks and set statuses,
    #: which is not this window's business.
    menu_wanted = Signal(int, object)

    #: The box at the end of a thread was clicked. The same thing the
    #: menu's *Reply* asks for, so it is answered in the same place.
    reply_here = Signal()

    #: The window was moved or resized, and where to: a viewport rectangle.
    #: Unlike opening it, this *is* a change to the document -- Reader keeps
    #: the geometry in `/Popup /Rect` -- so the window above records it.
    placed = Signal(object)

    #: How wide the window is made when nobody has said otherwise, in
    #: pixels. Reader's is 184 points parked off the page; this one floats
    #: over it, so it is sized for reading rather than for the paper.
    WIDTH = 300

    #: What separates one item from the next, in pixels, on top of the
    #: spacing every row gets. An author and their own text belong
    #: together and the next reply is a different thing being said, which
    #: is what Reader shows: with one gap for both, three replies read as
    #: six loose lines.
    BETWEEN = 8

    #: How narrow it may be dragged, and how narrow a window the *file* asks
    #: for is honoured down to. Not `WIDTH`: a window somebody sized in
    #: Reader is often narrower than that -- the one in the corpus is 166
    #: points -- and clamping it to our default would ignore the geometry we
    #: went to the trouble of reading.
    MIN_WIDTH = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._items: List[Item] = []
        self._selected = 0
        self._styling = False
        #: Where a drag of the header began, relative to the window, and
        #: None when no drag is in flight.
        self._dragging = None
        #: Which item the last post was made on, so that closing its
        #: editor does not close one something else has opened since.
        self._posting = self.NOTHING
        #: Whether the pointer has moved since it went down on a header,
        #: which is what tells a drag of the window from a click on an item.
        self._moved = False
        #: True while the geometry is being set by this application rather
        #: than by the user, so that putting the window where the file says
        #: it belongs is not reported as somebody moving it.
        self._placing = False
        #: True once the window has a size or place of somebody's choosing,
        #: after which rebuilding its contents must not undo that.
        self._sized = False
        self._editor: Optional["NoteEditor"] = None
        self._post: Optional[QPushButton] = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 10)
        self._layout.setSpacing(4)
        self._restyle()
        self.hide()

    # -- what it shows ----------------------------------------------------

    def show_thread(self, items, open_on: int = 0) -> None:
        """Show these items, with one of them open for editing.

        The first by default, which is what *opening* a thread does
        whatever is under it. ``open_on`` is for redrawing one that is
        already showing -- a status set on a reply changes the thread, and
        reopening it on the note would move the editor out from under
        whoever was using it.
        """
        self._items = [Item(*item) if not isinstance(item, Item) else item
                       for item in items]
        self._selected = (open_on if 0 <= open_on < len(self._items)
                          and not self._items[open_on].locked
                          else self.NOTHING)
        self._rebuild()
        self.show()
        self.raise_()
        self._settle()
        if self._editor is not None:
            self._editor.setFocus()

    def add_blank(self, author: str, when: str) -> int:
        """Append an empty item and open it. Returns which one it is.

        **A reply is this and nothing else** -- the same window with one
        more line in it, waiting for words. Post stays refused until there
        are some.
        """
        self._items.append(Item(author, when, ""))
        self._selected = len(self._items) - 1
        self._rebuild()
        self._settle()
        if self._editor is not None:
            self._editor.setFocus()
        return self._selected

    def drop_blank(self) -> None:
        """Take back an empty item nobody filled in."""
        if self._items and not self._items[-1].text:
            self._items.pop()
            self._selected = min(self._selected, len(self._items) - 1)
            self._rebuild()
            self._settle()

    def items(self) -> List[Item]:
        return list(self._items)

    def selected(self) -> int:
        return self._selected

    def select(self, which: int) -> None:
        """Open an item for editing, keeping the rest read-only.

        A locked item is not opened: clicking it, or its author line, does
        nothing rather than offering a box that cannot be posted.
        """
        if not 0 <= which < len(self._items) or which == self._selected:
            return
        if self._items[which].locked:
            return
        self._selected = which
        self._rebuild()
        self._settle()
        if self._editor is not None:
            self._editor.setFocus()

    def runs_of(self, which: int):
        """The styled runs of the item open for editing, or nothing.

        Asked for by the window when a post is kept, rather than sent with
        `posted`: what the file wants is `/RC`, and turning Qt's character
        formats into that is the data layer's business, not this window's.
        """
        if which == self._selected and self._editor is not None:
            return self._editor.runs()
        return []

    def text_of(self, which: int) -> str:
        """What the editor holds, for the open one; the stored text for the
        rest."""
        if which == self._selected and self._editor is not None:
            return self._editor.toPlainText()
        return self._items[which].text if 0 <= which < len(self._items) else ""

    def room_for(self, width: int) -> QSize:
        """The smallest this window may be and still be read.

        A window the file sized is a window somebody sized for *Reader's*
        text in *Reader's* fonts, which is not this one's. Honoured as a
        floor to grow from rather than as the size, because a thread that
        does not fit is not shown smaller -- Qt squashes whatever will
        squash, and the header rows and the editor go into their own
        margins.
        """
        width = max(int(width), self.MIN_WIDTH)
        need = self._layout.totalMinimumSize().height()
        if self._layout.hasHeightForWidth():
            need = max(need, self._layout.totalHeightForWidth(width))
        return QSize(width, need)

    def resize_to(self, rect) -> None:
        """Put the window where the file says it was left.

        Not a move: this is the window arriving where it already was, so it
        reports nothing and the document stays clean. Opening a note to read
        it must never be a change.

        **Grown to fit and pulled inside the view.** The file's geometry is
        where the window goes, not a box to cram it into: one that hung over
        the top of the viewport took its own header with it, and the header
        is what the window is dragged by -- so the geometry that cannot be
        honoured is the half that would put the window out of reach.
        """
        rect = QRect(rect)
        rect.setSize(rect.size().expandedTo(self.room_for(rect.width())))
        room = self.parentWidget().rect() if self.parentWidget() else None
        if room is not None:
            rect.moveLeft(max(room.left(),
                              min(rect.left(), room.right() - rect.width())))
            rect.moveTop(max(room.top(),
                             min(rect.top(), room.bottom() - rect.height())))
        self._placing = True
        try:
            self._sized = True
            self.setGeometry(rect)
        finally:
            self._placing = False

    def being_sized(self) -> None:
        """A drag of the corner has begun, so the size is now somebody's
        choosing and rebuilding the thread must not undo it."""
        self._sized = True

    def _settle(self) -> None:
        """Size to the items, now rather than whenever events next run.

        Every nested layout, not only the outer one: each item is a header,
        a text and sometimes a status row, each with a layout of its own.
        """
        for child in self.findChildren(QWidget):
            layout = child.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        self._layout.invalidate()
        self._layout.activate()
        self._placing = True
        try:
            # A minimum *width* on its own is enough to stop Qt applying the
            # layout's own minimum to the window -- it takes one having been
            # set as the window knowing its own mind -- so the two are set
            # together, here, where the layout has just been measured. Until
            # they were, the grip could squash the thread and so could the
            # file: a 131 point window folded a note and two replies into
            # 28 pixel rows.
            # The floor on the width is the fixed one: a window the
            # file sized narrow is honoured, and only the height has
            # to follow what the thread holds.
            self.setMinimumSize(self.MIN_WIDTH,
                                self.room_for(self.width()).height())
            if not self._sized:
                # Only while the window is still the size this made it. Once
                # it has been given one of somebody's choosing, adding a
                # reply must not snap it back.
                self.resize(self.WIDTH, self.sizeHint().height())
        finally:
            self._placing = False

    # -- building it ------------------------------------------------------

    def _rebuild(self) -> None:
        while self._layout.count():
            taken = self._layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                # Unparented *now*, not merely scheduled: `deleteLater` alone
                # leaves the old widgets parented until the event loop next
                # runs, and a rebuild that happens before then sizes itself
                # against them -- a three-item thread came out 18 pixels
                # tall where it needed 309.
                widget.setParent(None)
                widget.deleteLater()
        self._editor = None
        self._post = None
        for which, item in enumerate(self._items):
            if which:
                self._layout.addSpacing(self.BETWEEN)
            self._add_item(which, item)
        if self._selected == self.NOTHING and self._items and any(
                item.text for item in self._items):
            self._add_reply_box()
        # Room given away at the bottom, so that dragging the window
        # taller does not pour the extra height into the editor -- the one
        # thing in here that will stretch, which made a resize look like a
        # resize of the note being written.
        self._layout.addStretch(1)
        grip = Grip(self)
        corner = QHBoxLayout()
        corner.setContentsMargins(0, 0, 0, 0)
        corner.addStretch(1)
        corner.addWidget(grip)
        holder = QWidget(self)
        holder.setLayout(corner)
        self._layout.addWidget(holder)
        if self.isVisible():
            # A child added to a visible parent is shown on the next pass of
            # the event loop, and a layout measures a widget that has not
            # been shown as nothing. So a thread rebuilt in an open window
            # reported the height of its own margins -- 18 pixels -- until
            # the loop next ran, which is after the window has been placed.
            for child in self.findChildren(QWidget):
                child.show()

    #: What `_selected` is when no item is open for editing, which is how
    #: a thread stands after something has been posted into it.
    NOTHING = -1

    def _add_item(self, which: int, item: Item) -> None:
        head = QHBoxLayout()
        # No margins of its own. A layout takes a nine pixel margin on every
        # side unless told otherwise, and a row of two labels was spending
        # 18 pixels of height and indenting the author past the text under
        # it -- four rows of that is most of why this window stood taller
        # than Reader's for the same thread.
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        who = QLabel(item.author, self)
        who.setProperty("role", "author")
        when = QLabel(item.when, self)
        when.setProperty("role", "when")
        if item.colour:
            # **In the item's own colour.** A reply's `/C` colours its icon
            # and its pop-up's title bar, neither of which exists here, so
            # without this the colour each reply carries is invisible.
            tint = QColor.fromRgbF(*item.colour[:3]).darker(115).name()
            who.setStyleSheet("color: %s" % tint)
            when.setStyleSheet("color: %s" % tint)
        head.addWidget(who)
        head.addWidget(when)
        head.addStretch(1)
        if which == 0:
            # The cross belongs to the window, and the window's header is
            # the first item's: Reader has no separate title bar.
            shut = QPushButton("✕", self)
            shut.setFlat(True)
            # Big enough to hit without aiming. It is the only way to put
            # the window away with the mouse, and at a label's height it
            # was a 22 by 15 pixel target.
            shut.setFixedSize(26, 26)
            shut.setProperty("role", "close")
            shut.clicked.connect(self._shut)
            head.addWidget(shut)
        holder = QWidget(self)
        holder.setLayout(head)
        holder.setProperty("item", which)
        who.setProperty("item", which)
        when.setProperty("item", which)
        # An item's author line opens it, as its text does: the line and the
        # words under it are the same item, and after a post nothing is open
        # at all, so the line is how the note is reached again.
        #
        # The first item's header is also the window's title bar, so it is
        # what the window is dragged by -- which is why a click here is told
        # from a drag by whether the pointer moved rather than by which item
        # it was on.
        holder.mousePressEvent = lambda event, n=which: self._press_head(
            event, n)
        holder.mouseMoveEvent = self._drag
        holder.mouseReleaseEvent = lambda event, n=which: self._release_head(
            event, n)
        holder.setCursor(Qt.OpenHandCursor if which == 0
                         else Qt.PointingHandCursor)
        self._layout.addWidget(holder)

        if which == self._selected and not item.locked:
            self._layout.addWidget(self._editor_for(item))
        else:
            said = QLabel(item.text, self)
            if item.rich:
                # What the file styled, shown styled. `/RC` is the rich
                # version of the text and the one Reader draws.
                said.setTextFormat(Qt.TextFormat.RichText)
                said.setText(item.rich)
            said.setWordWrap(True)
            said.setProperty("role", "said")
            said.setProperty("item", which)
            said.mousePressEvent = (
                lambda _event, n=which: self.select(n))
            self._layout.addWidget(said)

        if item.status:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            label = QLabel(_("Status"), self)
            label.setProperty("role", "when")
            row.addWidget(label)
            value = QLabel(item.status, self)
            value.setProperty("role", "status")
            row.addWidget(value)
            row.addStretch(1)
            holder = QWidget(self)
            holder.setLayout(row)
            holder.setProperty("item", which)
            label.setProperty("item", which)
            value.setProperty("item", which)
            self._layout.addWidget(holder)

    def _add_reply_box(self) -> None:
        """The quiet box at the end of a thread that says *Add a reply*.

        **At the end, and always there.** A reply is the next thing anyone
        would write, so the place to write it is the bottom of what has
        been written -- not a menu command that appends a line with a box
        already open on it, which is what this had instead.

        Quiet until it is used: no buttons, no focus. Clicking it is what
        asks for a reply, and that is the same thing the menu asks for, so
        it goes through the same signal.
        """
        box = QLabel(_("Add a reply"), self)
        box.setProperty("role", "addreply")
        box.setWordWrap(True)
        box.setCursor(Qt.IBeamCursor)
        box.mousePressEvent = lambda event: self.reply_here.emit()
        self._layout.addWidget(box)

    def _editor_for(self, item: Item) -> QWidget:
        box = QFrame(self)
        box.setProperty("role", "editor")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(6, 6, 6, 6)
        inner.setSpacing(4)
        self._editor = NoteEditor(box)
        if item.rich:
            self._editor.setHtml(item.rich)
        else:
            self._editor.setPlainText(item.text)
        self._editor.setFrameShape(QFrame.NoFrame)
        self._editor.setFixedHeight(64)
        self._editor.textChanged.connect(self._typed)
        inner.addWidget(self._editor)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(_("Cancel"), box)
        cancel.setFlat(True)
        cancel.clicked.connect(self._cancel)
        buttons.addWidget(cancel)
        self._post = QPushButton(_("Post"), box)
        self._post.setFlat(True)
        self._post.setDefault(True)
        self._post.clicked.connect(self._post_it)
        buttons.addWidget(self._post)
        inner.addLayout(buttons)
        self._typed()
        return box

    # -- what it does -----------------------------------------------------

    def _typed(self) -> None:
        """Post is refused on an empty editor, which is how Reader stops a
        note being emptied: there is no way to post nothing."""
        if self._post is not None and self._editor is not None:
            self._post.setEnabled(bool(self._editor.toPlainText().strip()))

    def _post_it(self) -> None:
        if self._editor is None:
            return
        said = self._editor.toPlainText().strip()
        if not said:
            return
        self._items[self._selected] = self._items[self._selected]._replace(
            text=said, rich=html_of(self._editor.runs()))
        self._posting = self._selected
        self.posted.emit(self._selected, said)
        # Deferred, because this is running inside the Post button's own
        # click and closing the editor takes that button apart.
        QTimer.singleShot(0, self._posted_it)

    def _posted_it(self) -> None:
        """Close the editor on what was just posted.

        **The feedback that it was kept.** Reader turns the box into an
        item like the others; ours left the same words in the same open
        box, so pressing Post changed nothing you could see and there was
        no telling a posted reply from one still being typed.

        Unless something else has opened an item since. A post made on the
        way to another action -- *Reply*, a status -- is followed by that
        action, and what *it* opened is what should stay open.
        """
        if self._selected != self._posting or self._selected == self.NOTHING:
            return
        self._selected = self.NOTHING
        self._rebuild()
        self._settle()

    def post_now(self) -> bool:
        """Keep what the open editor holds, if it says something new.

        **Acrobat treats setting a status, or starting a reply, as a post
        of whatever is in the box** -- not as a cancel -- so the window
        above asks for this before doing either.
        """
        if self._editor is None or self._selected == self.NOTHING:
            return False
        said = self._editor.toPlainText().strip()
        if not said:
            # There is no posting nothing, which is also why Post is
            # refused on an empty editor.
            return False
        item = self._items[self._selected]
        if said == (item.text or "") and html_of(self._editor.runs()) == item.rich:
            return False
        self._post_it()
        return True

    def _cancel(self) -> None:
        """Put back what the item said, rather than closing the window: the
        editor is one item of several and the rest are untouched.

        **Cancelling a reply closes the reply, not the window.** The box at
        the end is a thing you opened on top of a thread that was already
        there, so taking it back leaves the thread showing with the quiet
        box at the end again. Cancelling the *note* is different: there is
        nothing underneath it, so the window goes.
        """
        if self._editor is not None:
            self._editor.setPlainText(self._items[self._selected].text)
        replying = (self._selected > 0 and self._items
                    and not self._items[self._selected].text)
        self.drop_blank()
        if replying:
            self._selected = self.NOTHING
            self._rebuild()
            self._settle()
            return
        self._shut()

    def _shut(self) -> None:
        self._hand_the_focus_back()
        self.hide()
        self.closed.emit()

    def _hand_the_focus_back(self) -> None:
        """Give the focus to what is behind before going away.

        **Hiding a widget that holds the focus runs Qt's own traversal.**
        It looks for the next widget in the chain, and the canvas this
        floats over reads that traversal as Tab -- so closing the window
        put the caret in the next field of the form, and closing it again
        put it in the one after that. Handing the focus back deliberately
        means there is nothing for Qt to go looking for.
        """
        if self.focusWidget() is None and not self.hasFocus():
            return
        behind = self.parentWidget()
        while behind is not None and behind.focusPolicy() == Qt.NoFocus:
            behind = behind.parentWidget()
        if behind is None:
            self.clearFocus()
        else:
            behind.setFocus(Qt.OtherFocusReason)

    def _press_head(self, event, which: int) -> None:
        self._moved = False
        if which == 0 and event.button() == Qt.LeftButton:
            self._dragging = event.globalPosition().toPoint() - self.pos()

    def _drag(self, event) -> None:
        if self._dragging is not None:
            self._moved = True
            self.move(event.globalPosition().toPoint() - self._dragging)

    def _release_head(self, event, which: int) -> None:
        """A drag ends; a click opens the item.

        Only a drag that *moved* is reported: a click on the first item's
        header would otherwise write a new `/Popup /Rect` identical to the
        old one and mark the document dirty for nothing.
        """
        dragged = self._dragging is not None and self._moved
        self._dragging = None
        if dragged:
            self._sized = True
            self.placed.emit(self.geometry())
            return
        # Deferred: opening an item rebuilds the window, and this is running
        # inside the handler of a widget the rebuild takes apart.
        QTimer.singleShot(0, lambda: self.select(which))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible() and self._sized and not self._placing:
            self.placed.emit(self.geometry())

    def contextMenuEvent(self, event):
        """Ask for a menu over whatever is under the pointer.

        The editor is not here: a `QTextEdit` has a menu of its own and
        keeps the event, which is the one place the standard editing
        entries belong.
        """
        self.menu_wanted.emit(self._item_at(event.pos()), event.globalPos())
        event.accept()

    def _item_at(self, where) -> int:
        """Which item a point is in, or `NOTHING` for the background."""
        widget = self.childAt(where)
        while widget is not None and widget is not self:
            which = widget.property("item")
            if which is not None:
                return int(which)
            widget = widget.parentWidget()
        return self.NOTHING

    def mousePressEvent(self, event):
        """Swallow it.

        **Qt passes a mouse event the widget ignores up to its parent**,
        and this window's parent is the page it floats over -- so a click
        on the part of a thread that is not a label or a box went straight
        through and picked the mark underneath, buttons and all.
        """
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._shut()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- looks ------------------------------------------------------------

    def _restyle(self) -> None:
        # Guarded, because setting a stylesheet that names colours changes
        # the widget's effective palette, which arrives back here as another
        # PaletteChange -- restyling until the stack runs out.
        if self._styling:
            return
        self._styling = True
        try:
            self._apply_style()
        finally:
            self._styling = False

    def _apply_style(self) -> None:
        palette = self.palette()
        faint = palette.placeholderText().color().name()
        line = palette.mid().color().name()
        self.setStyleSheet(
            "NotePanel { background: %s; border: 1px solid %s;"
            " border-radius: 6px; }"
            "QLabel[role=\"author\"] { font-weight: bold; }"
            "QLabel[role=\"when\"] { color: %s; }"
            "QLabel[role=\"status\"] { font-weight: bold; }"
            "QLabel[role=\"addreply\"] { color: %s; border: 1px solid %s;"
            " border-radius: 4px; padding: 8px 10px; }"
            "QFrame[role=\"editor\"] { border: 1px solid %s;"
            " border-radius: 4px; }"
            "QPushButton { border: none; font-weight: bold; padding: 2px 6px; }"
            "QPushButton[role=\"close\"] { font-size: 15px; padding: 0px; }"
            "QPushButton:disabled { color: %s; }"
            % (palette.base().color().name(), line, faint,
               faint, line,
               palette.highlight().color().name(), faint))

    def paintEvent(self, event):
        """Paint the background and border the stylesheet asks for.

        **A plain `QWidget` subclass does not do this for itself.** Qt's
        stylesheets reach the widgets Qt knows how to draw; a custom one
        gets its rules parsed and never painted, so this panel came out
        completely transparent -- the page showing through the window, its
        replies colliding with the text underneath. `PE_Widget` is the
        primitive that draws what the sheet asked for.
        """
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

    def changeEvent(self, event):
        if event.type() == QEvent.PaletteChange:
            self._restyle()
        super().changeEvent(event)
