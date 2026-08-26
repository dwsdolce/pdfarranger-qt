# Copyright (C) 2008-2025 pdfarranger contributors
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

"""Page-editing dialogs.

Each dialog is a thin front end over logic that already exists and is tested:
the geometry lives in ``core``, compositing in ``layers``, and export in
``export``. Every one exposes a ``get_value()`` returning None when cancelled,
so the window handlers stay uniform and the dialogs are testable without
showing them.
"""

import re
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QKeySequenceEdit,
    QPushButton,
    QScrollArea,
    QWidget,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
)

from .core import Dims, Sides
from .i18n import gettext_ as _

MM_PER_POINT = 25.4 / 72

#: Paper sizes in mm, matching the list the GTK version offers.
PAPER_SIZES = [
    ("A0", 841.0, 1189.0),
    ("A1", 594.0, 841.0),
    ("A2", 420.0, 594.0),
    ("A3", 297.0, 420.0),
    ("A4", 210.0, 297.0),
    ("A5", 148.0, 210.0),
    ("Letter", 215.9, 279.4),
    ("Legal", 215.9, 355.6),
    ("Ledger", 279.4, 431.8),
]


class BaseDialog(QDialog):
    """Modal dialog with OK/Cancel and a vertical body."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._layout = QVBoxLayout(self)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def finish(self):
        """Call once the body is built, to put the buttons last."""
        self._layout.addWidget(self.buttons)

    def add(self, widget):
        self._layout.addWidget(widget)
        return widget

    def get_value(self):
        """Show the dialog; return the value, or None if cancelled."""
        if self.exec() != QDialog.Accepted:
            return None
        return self.value()

    def value(self):
        raise NotImplementedError


# --------------------------------------------------------------------------
# Paper size


class PaperSizeWidget(QGroupBox):
    """Paper size in mm: preset, width/height, orientation, aspect lock."""

    #: PDF requires page sides between 1 inch and 200 inches.
    MIN_MM = 25.4
    MAX_MM = 5080.0

    def __init__(self, size_mm=None, parent=None):
        super().__init__(_("Paper size"), parent)
        self._updating = False
        grid = QGridLayout(self)

        self.combo = QComboBox()
        self.combo.addItem(_("Custom"))
        for name, _w, _h in PAPER_SIZES:
            self.combo.addItem(name)
        grid.addWidget(QLabel(_("Paper size")), 0, 0)
        grid.addWidget(self.combo, 0, 1, 1, 2)

        self.width = QDoubleSpinBox()
        self.height = QDoubleSpinBox()
        for box in (self.width, self.height):
            box.setDecimals(1)
            box.setRange(self.MIN_MM, self.MAX_MM)
            box.setSuffix(" " + _("mm"))
        grid.addWidget(QLabel(_("Width")), 1, 0)
        grid.addWidget(self.width, 1, 1)
        grid.addWidget(QLabel(_("Height")), 2, 0)
        grid.addWidget(self.height, 2, 1)

        self.lock_ratio = QCheckBox(_("Keep aspect ratio"))
        grid.addWidget(self.lock_ratio, 1, 2, 2, 1)

        self.portrait = QRadioButton(_("Portrait"))
        self.landscape = QRadioButton(_("Landscape"))
        group = QButtonGroup(self)
        group.addButton(self.portrait)
        group.addButton(self.landscape)
        row = QHBoxLayout()
        row.addWidget(self.portrait)
        row.addWidget(self.landscape)
        grid.addWidget(QLabel(_("Orientation")), 3, 0)
        grid.addLayout(row, 3, 1, 1, 2)

        if size_mm is None:
            size_mm = (210.0, 297.0)  # A4
            self.lock_ratio.setEnabled(False)
        else:
            self.lock_ratio.setChecked(True)
        self._ratio = size_mm[0] / size_mm[1] if size_mm[1] else 1.0
        self._set_size(size_mm)

        self.combo.currentIndexChanged.connect(self._preset_chosen)
        self.width.valueChanged.connect(self._width_changed)
        self.height.valueChanged.connect(self._height_changed)
        self.portrait.toggled.connect(self._orientation_changed)

    # -- internals ---------------------------------------------------------

    def _set_size(self, size_mm):
        self._updating = True
        self.width.setValue(size_mm[0])
        self.height.setValue(size_mm[1])
        self.portrait.setChecked(size_mm[1] >= size_mm[0])
        self.landscape.setChecked(size_mm[1] < size_mm[0])
        self._select_matching_preset()
        self._updating = False

    def _select_matching_preset(self):
        w, h = self.width.value(), self.height.value()
        for index, (_name, pw, ph) in enumerate(PAPER_SIZES, start=1):
            if ({round(w, 1), round(h, 1)} == {round(pw, 1), round(ph, 1)}):
                self.combo.setCurrentIndex(index)
                return
        self.combo.setCurrentIndex(0)

    def _preset_chosen(self, index):
        if self._updating or index == 0:
            return
        _name, w, h = PAPER_SIZES[index - 1]
        if self.landscape.isChecked():
            w, h = h, w
        self._updating = True
        self.width.setValue(w)
        self.height.setValue(h)
        self._updating = False

    def _width_changed(self, value):
        if self._updating:
            return
        self._updating = True
        if self.lock_ratio.isChecked() and self._ratio:
            self.height.setValue(min(self.MAX_MM, value / self._ratio))
        self._select_matching_preset()
        self._updating = False

    def _height_changed(self, value):
        if self._updating:
            return
        self._updating = True
        if self.lock_ratio.isChecked():
            self.width.setValue(min(self.MAX_MM, value * self._ratio))
        self._select_matching_preset()
        self._updating = False

    def _orientation_changed(self, _checked):
        if self._updating:
            return
        w, h = self.width.value(), self.height.value()
        wants_portrait = self.portrait.isChecked()
        if (h < w) == wants_portrait:  # currently the wrong way round
            self._updating = True
            self.width.setValue(h)
            self.height.setValue(w)
            self._updating = False

    # -- public ------------------------------------------------------------

    def size_mm(self) -> Dims:
        return Dims(self.width.value(), self.height.value())

    def size_points(self) -> Dims:
        return Dims(self.width.value() / MM_PER_POINT,
                    self.height.value() / MM_PER_POINT)


# --------------------------------------------------------------------------
# Select range


def parse_page_range(text: str, count: int) -> List[int]:
    """Parse "1,3,5-7,9" into 0-based rows, clamped to the document.

    Out-of-range and malformed pieces are skipped rather than raising: the entry
    is validated as you type, so the only way to get here with rubbish is a
    number past the end of the document.
    """
    rows = []
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", chunk)
        if not match:
            continue
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else first
        if last < first:
            first, last = last, first
        for page in range(first, last + 1):
            if 1 <= page <= count:
                rows.append(page - 1)
    return sorted(set(rows))


class RangeSelectDialog(BaseDialog):
    def __init__(self, count: int, parent=None):
        super().__init__(_("Range Select"), parent)
        self.count = count
        self.entry = QLineEdit()
        form = QFormLayout()
        form.addRow(_("Select range of pages: "), self.entry)
        holder = QGroupBox()
        holder.setLayout(form)
        self.add(holder)
        hint = QLabel(_('Use a comma to separate page numbers, '
                        'a dash to select a range of pages. \n'
                        'e.g. : "1,3,5-7,9"'))
        hint.setWordWrap(True)
        self.add(hint)
        self.finish()
        self.entry.textChanged.connect(self._sanitise)

    def _sanitise(self, text):
        cleaned = "".join(c for c in text if c in "0123456789,- ")
        if cleaned != text:
            self.entry.setText(cleaned)

    def value(self) -> List[int]:
        return parse_page_range(self.entry.text(), self.count)


# --------------------------------------------------------------------------
# Insert blank page


class BlankPageDialog(BaseDialog):
    def __init__(self, size_mm=None, parent=None):
        super().__init__(_("Insert Blank Page"), parent)
        self.paper = PaperSizeWidget(size_mm)
        self.add(self.paper)
        self.finish()

    def value(self) -> Dims:
        return self.paper.size_points()


# --------------------------------------------------------------------------
# Page size / scale


class ScaleDialog(BaseDialog):
    """Resize pages: fit to a paper size, or scale by a percentage."""

    MODE_SCALE = "SCALE"
    MODE_SCALE_MARGINS = "SCALE-ADD-MARG"
    MODE_CROP_MARGINS = "CROP-ADD-MARG"

    def __init__(self, page, parent=None):
        super().__init__(_("Page size"), parent)

        self.fit_radio = QRadioButton(_("Fit to paper"))
        self.rel_radio = QRadioButton(_("Relative"))
        self.fit_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.fit_radio)
        group.addButton(self.rel_radio)

        self.paper = PaperSizeWidget(tuple(page.size_in_mm()))
        self.mode = QComboBox()
        self.mode.addItem(_("Scale"), self.MODE_SCALE)
        self.mode.addItem(_("Scale & Add margins"), self.MODE_SCALE_MARGINS)
        self.mode.addItem(_("Crop & Add margins"), self.MODE_CROP_MARGINS)
        fit_form = QFormLayout()
        fit_form.addRow(_("Fit mode"), self.mode)

        self.percent = QDoubleSpinBox()
        self.percent.setDecimals(1)
        self.percent.setRange(1.0, 1000.0)
        self.percent.setValue(page.scale * 100)
        self.percent.setSuffix(" %")
        rel_form = QFormLayout()
        rel_form.addRow(_("Scale factor"), self.percent)

        self.add(self.fit_radio)
        self.add(self.paper)
        holder = QGroupBox()
        holder.setLayout(fit_form)
        self.add(holder)
        self.add(self.rel_radio)
        rel_box = QGroupBox()
        rel_box.setLayout(rel_form)
        self.add(rel_box)
        self.finish()

        self.fit_radio.toggled.connect(self._sync_enabled)
        self._sync_enabled()

    def _sync_enabled(self, *_a):
        fitting = self.fit_radio.isChecked()
        self.paper.setEnabled(fitting)
        self.mode.setEnabled(fitting)
        self.percent.setEnabled(not fitting)

    def value(self) -> Tuple[object, str]:
        """Return ``(target, mode)``.

        ``target`` is a Dims in points when fitting to paper, or a plain scale
        factor when scaling relatively.
        """
        if self.rel_radio.isChecked():
            return self.percent.value() / 100.0, self.MODE_SCALE
        return self.paper.size_points(), self.mode.currentData()


# --------------------------------------------------------------------------
# Crop and hide


class CropHideDialog(BaseDialog):
    """Trim margins off pages, or blank them out.

    Cropping shrinks the page; hiding keeps the page size and covers the margin.
    Values are percentages of each side, as upstream stores them.
    """

    def __init__(self, sides: Sides, hide: bool, parent=None):
        super().__init__(_("Hide Margins") if hide else _("Crop Margins"), parent)
        self.spins = {}
        form = QFormLayout()
        labels = (("left", _("Left")), ("right", _("Right")),
                  ("top", _("Top")), ("bottom", _("Bottom")))
        for attr, label in labels:
            spin = QDoubleSpinBox()
            spin.setDecimals(1)
            spin.setRange(0.0, 99.0)
            spin.setSuffix(" %")
            spin.setValue(getattr(sides, attr) * 100)
            form.addRow(label, spin)
            self.spins[attr] = spin
        box = QGroupBox(_("Margins"))
        box.setLayout(form)
        self.add(box)

        self.uniform = QCheckBox(_("Same for all sides"))
        self.add(self.uniform)
        self.finish()

        self.uniform.toggled.connect(self._apply_uniform)
        for spin in self.spins.values():
            spin.valueChanged.connect(self._maybe_mirror)
        self._mirroring = False

    def _apply_uniform(self, checked):
        if checked:
            self._mirroring = True
            value = self.spins["left"].value()
            for spin in self.spins.values():
                spin.setValue(value)
            self._mirroring = False

    def _maybe_mirror(self, value):
        if self._mirroring or not self.uniform.isChecked():
            return
        self._mirroring = True
        for spin in self.spins.values():
            spin.setValue(value)
        self._mirroring = False

    def value(self) -> Sides:
        sides = Sides(*(self.spins[a].value() / 100
                        for a in ("left", "right", "top", "bottom")))
        # A page cropped away entirely has no meaning and breaks the exporter.
        if sides.left + sides.right >= 1 or sides.top + sides.bottom >= 1:
            return None
        return sides


# --------------------------------------------------------------------------
# Split pages


class SplitDialog(BaseDialog):
    """Cut each page into a grid of equal tiles."""

    def __init__(self, parent=None):
        super().__init__(_("Split Pages"), parent)
        self.columns = QSpinBox()
        self.rows = QSpinBox()
        for spin in (self.columns, self.rows):
            spin.setRange(1, 20)
            spin.setValue(1)
        self.columns.setValue(2)
        form = QFormLayout()
        form.addRow(_("Vertical Splits"), self.columns)
        form.addRow(_("Horizontal Splits"), self.rows)
        box = QGroupBox()
        box.setLayout(form)
        self.add(box)
        self.finish()

    def value(self) -> Tuple[int, int]:
        return self.columns.value(), self.rows.value()


# --------------------------------------------------------------------------
# Merge / paste as layer


class MergeDialog(BaseDialog):
    """Place pages on top of (or under) other pages."""

    def __init__(self, laypos: str, parent=None):
        super().__init__(_("Merge Pages"), parent)
        self.laypos_combo = QComboBox()
        self.laypos_combo.addItem(_("Overlay"), "OVERLAY")
        self.laypos_combo.addItem(_("Underlay"), "UNDERLAY")
        self.laypos_combo.setCurrentIndex(0 if laypos == "OVERLAY" else 1)

        self.horizontal = QComboBox()
        for label, value in ((_("Left"), 0.0), (_("Centre"), 0.5), (_("Right"), 1.0)):
            self.horizontal.addItem(label, value)
        self.horizontal.setCurrentIndex(1)

        self.vertical = QComboBox()
        for label, value in ((_("Top"), 0.0), (_("Middle"), 0.5), (_("Bottom"), 1.0)):
            self.vertical.addItem(label, value)
        self.vertical.setCurrentIndex(1)

        self.rescale = QDoubleSpinBox()
        self.rescale.setDecimals(1)
        self.rescale.setRange(1.0, 1000.0)
        self.rescale.setValue(100.0)
        self.rescale.setSuffix(" %")

        form = QFormLayout()
        form.addRow(_("Position"), self.laypos_combo)
        form.addRow(_("Horizontal"), self.horizontal)
        form.addRow(_("Vertical"), self.vertical)
        form.addRow(_("Scale factor"), self.rescale)
        box = QGroupBox()
        box.setLayout(form)
        self.add(box)
        self.finish()

    def value(self):
        """Return ``(laypos, (off_x, off_y), rescale)``."""
        return (
            self.laypos_combo.currentData(),
            (self.horizontal.currentData(), self.vertical.currentData()),
            self.rescale.value() / 100.0,
        )


# --------------------------------------------------------------------------
# Document properties


class PropertiesDialog(BaseDialog):
    """Edit the document's XMP metadata.

    Values round-trip through ``metadata._metatostr`` / ``_strtometa`` so that
    list-valued fields (Creator) and dates keep the representation the exporter
    expects -- the same conversion the GTK dialog used.
    """

    def __init__(self, mdata: dict, parent=None):
        from . import metadata

        super().__init__(_("Edit properties"), parent)
        self._metadata = metadata
        self.fields = {}
        form = QFormLayout()
        for key, label in metadata._LABELS.items():
            edit = QLineEdit()
            if key in mdata:
                edit.setText(metadata._metatostr(mdata[key], key))
            form.addRow(label, edit)
            self.fields[key] = edit
        box = QGroupBox()
        box.setLayout(form)
        self.add(box)
        self.finish()
        #: Keys present on the document that this dialog does not show, so they
        #: survive an edit instead of being silently dropped.
        self._untouched = {k: v for k, v in mdata.items()
                           if k not in metadata._LABELS}

    def value(self) -> dict:
        out = dict(self._untouched)
        for key, edit in self.fields.items():
            text = edit.text().strip()
            if text:
                out[key] = self._metadata._strtometa(text, key)
        return out


# --------------------------------------------------------------------------
# Preferences


#: Settings keys and their defaults, so the dialog and the app agree.
PREFERENCES = {
    "language": "",
    "theme": "system",
    "print/scale-mode": "fit",
    "print/auto-rotate": True,
    "print/dpi": 200,
    "export/preserve-first-document": False,
    "image/ppi": 300,
    "image/greyscale": False,
}

THEMES = [("system", "System"), ("light", "Light"), ("dark", "Dark")]


class PreferencesDialog(BaseDialog):
    """Application preferences.

    Everything is here because decision D4 dropped the hand-edited ``config.ini``
    the GTK version pointed users at -- including the keyboard shortcuts, which
    upstream only exposed by editing that file (see D11).
    """

    def __init__(self, values: dict, actions=None, parent=None):
        super().__init__(_("Preferences"), parent)
        current = dict(PREFERENCES)
        current.update(values or {})

        self.language = QComboBox()
        self.language.addItem(_("System setting"), "")
        for code, name in _LANGUAGES:
            self.language.addItem(f"{name} [{code}]", code)
        self._select(self.language, current["language"])

        self.theme = QComboBox()
        for value, label in THEMES:
            self.theme.addItem(_(label), value)
        self._select(self.theme, current["theme"])

        general = QFormLayout()
        general.addRow(_("Language") + " " + _("(Requires restart)"), self.language)
        general.addRow(_("Theme"), self.theme)
        box = QGroupBox(_("General"))
        box.setLayout(general)
        self.add(box)

        self.scale_mode = QComboBox()
        self.scale_mode.addItem(_("Fit to page"), "fit")
        self.scale_mode.addItem(_("Actual size"), "actual")
        self._select(self.scale_mode, current["print/scale-mode"])
        self.auto_rotate = QCheckBox(_("Auto Rotate"))
        self.auto_rotate.setChecked(bool(current["print/auto-rotate"]))
        self.print_dpi = QSpinBox()
        self.print_dpi.setRange(72, 600)
        self.print_dpi.setSingleStep(50)
        self.print_dpi.setValue(int(current["print/dpi"]))
        self.print_dpi.setToolTip(
            _("Pages are rasterised at this resolution before being sent to the "
              "printer. Lower it if printing is slow: the printer driver has "
              "less to process."))
        printing = QFormLayout()
        printing.addRow(_("Scale mode"), self.scale_mode)
        printing.addRow(_("Pixels/inch:"), self.print_dpi)
        printing.addRow("", self.auto_rotate)
        box = QGroupBox(_("Printing"))
        box.setLayout(printing)
        self.add(box)

        self.preserve_first = QCheckBox(
            _("Preserve document information from the first file opened"))
        self.preserve_first.setChecked(bool(current["export/preserve-first-document"]))
        self.preserve_first.setToolTip(
            _("When checked: use document properties from the first file opened.")
            + "\n"
            + _("When unchecked: merge bookmarks from all documents."))
        saving = QVBoxLayout()
        saving.addWidget(self.preserve_first)
        box = QGroupBox(_("Saving/exporting to single file"))
        box.setLayout(saving)
        self.add(box)

        self.ppi = QSpinBox()
        self.ppi.setRange(1, 1200)
        self.ppi.setValue(int(current["image/ppi"]))
        self.greyscale = QCheckBox(_("Greyscale"))
        self.greyscale.setChecked(bool(current["image/greyscale"]))
        images = QFormLayout()
        images.addRow(_("Pixels/inch:"), self.ppi)
        images.addRow("", self.greyscale)
        box = QGroupBox(_("Image Export"))
        box.setLayout(images)
        self.add(box)

        # Shortcuts get their own window: there are sixty-odd actions, and
        # inlining them made the Preferences dialog taller than the screen.
        self._actions = list(actions or [])
        self._shortcuts: dict = {}
        button = QPushButton(_("Keyboard shortcuts") + "…")
        button.clicked.connect(self._edit_shortcuts)
        button.setEnabled(bool(self._actions))
        row = QHBoxLayout()
        row.addWidget(button)
        row.addStretch(1)
        box = QGroupBox(_("Keyboard shortcuts"))
        box.setLayout(row)
        self.add(box)

        self.finish()

    def _edit_shortcuts(self):
        dialog = ShortcutsDialog(self._actions, self._shortcuts, self)
        result = dialog.get_value()
        if result is not None:
            self._shortcuts = result

    @staticmethod
    def _select(combo, data):
        index = combo.findData(data)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def value(self) -> dict:
        return {
            "language": self.language.currentData(),
            "theme": self.theme.currentData(),
            "print/scale-mode": self.scale_mode.currentData(),
            "print/auto-rotate": self.auto_rotate.isChecked(),
            "print/dpi": self.print_dpi.value(),
            "export/preserve-first-document": self.preserve_first.isChecked(),
            "image/ppi": self.ppi.value(),
            "image/greyscale": self.greyscale.isChecked(),
            "shortcuts": dict(self._shortcuts),
        }


class EncryptionPasswordDialog(BaseDialog):
    """Ask for the password the saved document will be encrypted with.

    Two fields rather than one: the password is not shown, it is not stored
    anywhere recoverable, and getting it wrong makes the saved file unopenable.
    A typo here is unrecoverable data loss, so it is worth the extra field.
    """

    def __init__(self, current="", parent=None):
        super().__init__(_("Password"), parent)
        body = QWidget()
        form = QFormLayout(body)
        self.first = QLineEdit(current or "")
        self.first.setEchoMode(QLineEdit.Password)
        self.second = QLineEdit(current or "")
        self.second.setEchoMode(QLineEdit.Password)
        form.addRow(_("Password"), self.first)
        form.addRow(_("Confirm password"), self.second)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        form.addRow(self.message)
        self.add(body)
        self.finish()
        for edit in (self.first, self.second):
            edit.textChanged.connect(self._revalidate)
        self._revalidate()

    def _revalidate(self):
        ok = bool(self.first.text()) and self.first.text() == self.second.text()
        if not self.first.text():
            self.message.setText(_("Enter a password, or cancel to leave the "
                                   "document unencrypted."))
        elif not ok:
            self.message.setText(_("The passwords do not match."))
        else:
            self.message.setText("")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def value(self):
        return self.first.text()


class ShortcutsDialog(BaseDialog):
    """Editable list of action shortcuts (D11), in its own scrollable window.

    Keyed on the action's object name, so a rebinding survives the action being
    recreated. Qt's own ``QKeySequence`` text is stored, not the GTK
    ``<Primary>s`` syntax, so old ``config.ini`` customisations do not migrate.
    """

    def __init__(self, actions, overrides=None, parent=None):
        super().__init__(_("Keyboard shortcuts"), parent)
        overrides = overrides or {}
        self.edits = {}

        body = QWidget()
        form = QFormLayout(body)
        form.setLabelAlignment(Qt.AlignLeft)
        for title, group in self._grouped(actions):
            if title:
                form.addRow(self._heading(title, first=not self.edits))
            for action in group:
                name = action.objectName() or action.text()
                if name in self.edits:
                    continue  # the same action can appear in more than one menu
                current = overrides.get(name, action.shortcut().toString())
                edit = QKeySequenceEdit(QKeySequence(current))
                edit.setClearButtonEnabled(True)
                form.addRow(action.text().replace("&", ""), edit)
                self.edits[name] = edit

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(460, 420)
        self.add(scroll)

        reset = self.buttons.addButton(_("Reset"), QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._clear_all)
        self.finish()
        self.resize(520, 560)

    @staticmethod
    def _grouped(actions):
        """Accept either [(title, [action])] or a bare [action].

        The window passes the grouped form so the list reads in menu order;
        the flat form keeps this usable on its own, and in tests.
        """
        if actions and isinstance(actions[0], tuple):
            return list(actions)
        return [(None, list(actions))]

    @staticmethod
    def _heading(title, first=False):
        """A menu name, so the list can be scanned instead of read."""
        label = QLabel(f"<b>{title}</b>")
        margin = 0 if first else 12
        label.setContentsMargins(0, margin, 0, 2)
        return label

    def _clear_all(self):
        for edit in self.edits.values():
            edit.clear()

    def value(self) -> dict:
        """Only the bindings that are set; cleared ones fall back to defaults."""
        out = {}
        for name, edit in self.edits.items():
            text = edit.keySequence().toString()
            if text:
                out[name] = text
        return out


# --------------------------------------------------------------------------
# Help


def help_sections():
    """The user guide, as ``(heading, [paragraphs])`` pairs.

    This replaces the man page rather than duplicating it: the GTK-era page
    documented environment variables and a config file that no longer exist,
    and said nothing about the mouse gestures — which are the least
    discoverable part of the application and the main reason anyone opens help.
    """
    return [
        (_("Description"), [
            _("PDF Arranger merges, splits, rearranges, rotates and crops PDF "
              "documents. Everything happens in memory against the pages you "
              "can see; nothing is written until you save."),
            _("It is a front end for pikepdf. Page content is never rewritten — "
              "only page order, geometry and composition."),
        ]),
        (_("Command line"), [
            "<code>pdfarranger [file1] [file2] ...</code>",
            _("Files given on the command line are opened as one document. "
              "<code>--version</code> prints the version and exits."),
        ]),
        (_("Arranging pages"), [
            _("Drag pages to reorder them. Hold <b>Ctrl</b> while dropping to "
              "copy instead of move."),
            _("Drag pages onto another window of the application to copy them "
              "there, or use ordinary copy and paste."),
            _("<b>Paste As Odd/Even Pages</b> interleaves the clipboard with the "
              "document — this is how two single-sided scans of a double-sided "
              "original are recombined. If the second scan came off a duplex "
              "feeder it will be in reverse order; use <b>Arrange ▸ Reverse "
              "Order</b> on it first."),
        ]),
        (_("Mouse"), [
            _("<b>Ctrl + scroll</b> — zoom"),
            _("<b>Shift + scroll</b> — scroll sideways"),
            _("<b>Alt + scroll</b> — scroll exactly one row"),
            _("<b>Double-click</b> — fit the page to the window, and back"),
            _("<b>Click and drag</b> on empty space — rubber-band select; keep "
              "scrolling to extend it"),
        ]),
        (_("Moving around"), [
            _("<b>Arrow keys</b> move between pages, <b>Page Up</b> and "
              "<b>Page Down</b> move a screenful at a time, and <b>Home</b> "
              "and <b>End</b> jump to the first and last page. Hold "
              "<b>Shift</b> with any of them to extend the selection."),
            _("<b>Fit One Page</b> (F) scales so a whole page fits in the "
              "window and shows one page per row — use it to work on a single "
              "page at a time. <b>Fit Multiple Pages</b> (Shift+M) uses the "
              "same scale but lets as many pages sit side by side as the "
              "window takes. <b>Fit Width</b> (Shift+F) fills the window "
              "across instead, which shows the page wider but taller than the "
              "window. Double-clicking the grid toggles Fit One Page on and "
              "off."),
            _("With pages selected, all three fit the selection rather than "
              "the whole document."),
        ]),
        (_("Finding text"), [
            _("<b>Find</b> selects the pages that contain the phrase and boxes "
              "each hit on the thumbnail, so you can see where on the page it "
              "is. The boxes clear as soon as you change the document, since "
              "the pages they were drawn for may have moved."),
        ]),
        (_("Keyboard shortcuts"), [
            _("Every shortcut can be changed in "
              "<b>Edit ▸ Preferences ▸ Keyboard shortcuts</b>, where they are "
              "listed under the menu each one belongs to."),
        ]),
        (_("Read mode"), [
            _("<b>View ▸ Read Mode</b> (Ctrl+E) swaps the thumbnail grid for a "
              "continuous page view — for reading the document rather than "
              "rearranging it. Press it again to go back."),
            _("It shows the document <i>as edited</i>: rotations, crops, "
              "deletions and reordering are all applied, so what you read is "
              "what you would get if you saved. Editing commands are disabled "
              "while reading, and any change you make in the grid is picked up "
              "the next time you switch across."),
            _("The toolbar shows which page you are on and how many there are; "
              "type a number into it to jump there."),
            _("<b>Page Up</b> and <b>Page Down</b> turn pages, <b>Home</b> and "
              "<b>End</b> jump to the first and last, and <b>Ctrl+G</b> goes to "
              "a page by number. The same commands are in the <b>View</b> menu, "
              "where they can be given different keys."),
            _("<b>View ▸ Continuous Scroll</b> is on by default. On a long, "
              "densely illustrated document, scrolling quickly can outrun the "
              "renderer and leave pages blank until it catches up; turning it "
              "off shows one page at a time, which stays sharp as you page "
              "through with Page Up and Page Down."),
            _("The sidebar lists the document's bookmarks, if it has any; "
              "click one to jump to it. Find works here too and highlights the "
              "matches on the page rather than only selecting pages. Your "
              "place in each document is remembered between visits."),
        ]),
        (_("Passwords"), [
            _("Opening an encrypted document asks for its password, which is "
              "remembered until the document is closed."),
            _("<b>File ▸ Password</b> encrypts the document when it is next "
              "saved. It is a switch: turn it on and you are asked for a "
              "password, turn it off and the next save is unencrypted. The "
              "password is never written to your settings, so it applies to "
              "this session only — and if you forget it, the file cannot be "
              "recovered."),
        ]),
        (_("Files"), [
            _("Settings are stored by Qt in the per-user location for this "
              "platform; on Windows that is the registry under "
              "<code>HKEY_CURRENT_USER\\Software\\pdfarranger</code>. There is "
              "no configuration file to edit by hand."),
        ]),
        (_("Credits"), [
            _("PDF Arranger Qt is a PySide6 port of PDF Arranger, which is itself "
              "derived from PDF-Shuffler. It is a separate project and not "
              "affiliated with either."),
            _("Original authors: Konstantinos Poulios, Jerome Robert."),
            _("Licensed under the GNU General Public License version 3 or later."),
        ]),
    ]


class HelpDialog(QDialog):
    """Scrollable user guide. Not modal: it is meant to be read while working."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("User Guide"))
        layout = QVBoxLayout(self)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(self._html())
        layout.addWidget(self.browser)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)
        self.resize(620, 640)

    @staticmethod
    def _html() -> str:
        parts = []
        for heading, paragraphs in help_sections():
            parts.append(f"<h3>{heading}</h3>")
            parts.extend(f"<p>{text}</p>" for text in paragraphs)
        return "\n".join(parts)


#: Languages with a catalogue in po/, for the Language preference.
_LANGUAGES = [
    ("ar", "العربية"), ("ca", "Català"), ("cs", "Čeština"), ("da", "Dansk"),
    ("de", "Deutsch"), ("el", "Ελληνικά"), ("en", "English"), ("es", "Español"),
    ("fa", "فارسی"), ("fi", "Suomi"), ("fr", "Français"), ("he", "עברית"),
    ("hr", "Hrvatski"), ("hu", "Magyar"), ("id", "Indonesia"), ("it", "Italiano"),
    ("ja", "日本語"), ("ko", "한국어"), ("nl", "Nederlands"), ("pl", "Polski"),
    ("pt_BR", "Português do Brasil"), ("ro", "Română"), ("ru", "Русский"),
    ("sl", "Slovenščina"), ("sv", "Svenska"), ("tr", "Türkçe"),
    ("uk", "Українська"), ("vi", "Tiếng Việt"), ("zh_CN", "简体中文"),
    ("zh_TW", "繁體中文"),
]
