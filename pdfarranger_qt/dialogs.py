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
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import nup, stamp, viewer
from .core import Dims, Sides
from .i18n import N_
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


class NUpDialog(BaseDialog):
    """Tile several pages onto one sheet.

    The presets are the whole point for most people, so they come first and
    drive the two spin boxes; the spin boxes stay editable for the layouts no
    preset covers.
    """

    #: Percent of each cell left empty around its page.
    DEFAULT_GAP = 0

    def __init__(self, parent=None):
        super().__init__(_("Pages per Sheet"), parent)

        # The combo is built first: the spin boxes drive it, so it has to
        # exist before their first setValue fires the handler.
        self.preset = QComboBox()
        self.preset.addItem(_("Custom"), "")
        for columns, rows, label in nup.PRESETS:
            # A string, not a tuple: Qt round-trips item data through QVariant,
            # so findData on a tuple never matches what addItem stored.
            self.preset.addItem(label(), self._key(columns, rows))

        self.columns = QSpinBox()
        self.rows = QSpinBox()
        for spin in (self.columns, self.rows):
            spin.setRange(1, 20)
        self.columns.setValue(2)
        self.rows.setValue(1)
        for spin in (self.columns, self.rows):
            spin.valueChanged.connect(self._match_preset)
        self.preset.currentIndexChanged.connect(self._apply_preset)

        self.orientation = QComboBox()
        for value, label in ((nup.AUTO, _("Automatic")),
                             (nup.PORTRAIT, _("Portrait")),
                             (nup.LANDSCAPE, _("Landscape"))):
            self.orientation.addItem(label, value)
        self.orientation.setToolTip(
            _("Automatic turns the sheet sideways when that lets the pages "
              "come out larger."))

        self.gap = QSpinBox()
        self.gap.setRange(0, 45)
        self.gap.setSuffix(" %")
        self.gap.setValue(self.DEFAULT_GAP)
        self.gap.setToolTip(_("Empty space left around each page."))

        form = QFormLayout()
        form.addRow(_("Layout"), self.preset)
        form.addRow(_("Columns"), self.columns)
        form.addRow(_("Rows"), self.rows)
        form.addRow(_("Sheet"), self.orientation)
        form.addRow(_("Gap"), self.gap)
        box = QGroupBox()
        box.setLayout(form)
        self.add(box)

        self._match_preset()
        self.finish()

    @staticmethod
    def _key(columns: int, rows: int) -> str:
        return f"{columns}x{rows}"

    def _apply_preset(self):
        chosen = self.preset.currentData()
        if not chosen:
            return
        columns, rows = (int(part) for part in chosen.split("x"))
        # Blocked so setting the boxes does not immediately reset the combo to
        # Custom on the way past the first one.
        for spin, value in ((self.columns, columns), (self.rows, rows)):
            was = spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(was)

    def _match_preset(self):
        index = self.preset.findData(self._key(self.columns.value(),
                                               self.rows.value()))
        was = self.preset.blockSignals(True)
        self.preset.setCurrentIndex(index if index >= 0 else 0)
        self.preset.blockSignals(was)

    def value(self) -> dict:
        return {
            "columns": self.columns.value(),
            "rows": self.rows.value(),
            "orientation": self.orientation.currentData(),
            "margin": self.gap.value() / 100.0,
        }


class _StampStyleWidget(QGroupBox):
    """The half of a stamp dialog that is the same for both features.

    Font, size, colour, weight and opacity say nothing about *what* is being
    stamped, so page numbers and watermarks share them; only the position
    defaults and the text field differ.
    """

    def __init__(self, style: "stamp.Style", positions=True, rotation=False):
        super().__init__(_("Appearance"))
        self._colour = QColor(style.colour)

        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(style.font))

        self.size = QDoubleSpinBox()
        self.size.setRange(1.0, 400.0)
        self.size.setSuffix(" pt")
        self.size.setValue(style.size)

        self.bold = QCheckBox(_("Bold"))
        self.bold.setChecked(style.bold)
        self.italic = QCheckBox(_("Italic"))
        self.italic.setChecked(style.italic)
        weights = QHBoxLayout()
        weights.addWidget(self.bold)
        weights.addWidget(self.italic)
        weights.addStretch(1)

        self.colour = QPushButton()
        self.colour.clicked.connect(self._pick_colour)
        self._show_colour()

        self.opacity = QSpinBox()
        self.opacity.setRange(1, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(round(style.opacity * 100))

        form = QFormLayout()
        form.addRow(_("Font"), self.font)
        form.addRow(_("Size"), self.size)
        form.addRow("", weights)
        form.addRow(_("Colour"), self.colour)
        form.addRow(_("Opacity"), self.opacity)

        self.position = None
        if positions:
            self.position = QComboBox()
            for key, label, _flags in stamp.POSITIONS:
                self.position.addItem(label(), key)
            index = self.position.findData(style.position)
            self.position.setCurrentIndex(max(index, 0))
            form.addRow(_("Position"), self.position)

        self.rotation = None
        if rotation:
            self.rotation = QSpinBox()
            self.rotation.setRange(-180, 180)
            self.rotation.setSuffix(" °")
            self.rotation.setValue(round(style.rotation))
            form.addRow(_("Angle"), self.rotation)

        self.setLayout(form)

    def _pick_colour(self):
        chosen = QColorDialog.getColor(self._colour, self, _("Colour"))
        if chosen.isValid():
            self._colour = chosen
            self._show_colour()

    def _show_colour(self):
        self.colour.setText(self._colour.name())
        # A swatch rather than a bare hex code: nobody reads #808080 as grey.
        self.colour.setStyleSheet(
            f"background-color: {self._colour.name()};"
            f" color: {'#000000' if self._colour.lightness() > 127 else '#ffffff'};")

    def value(self) -> "stamp.Style":
        return stamp.Style(
            font=self.font.currentFont().family(),
            size=self.size.value(),
            colour=self._colour.name(),
            opacity=self.opacity.value() / 100.0,
            bold=self.bold.isChecked(),
            italic=self.italic.isChecked(),
            position=(self.position.currentData() if self.position
                      else stamp.Style.position),
            rotation=(float(self.rotation.value()) if self.rotation else 0.0),
        )


class PageNumbersDialog(BaseDialog):
    """Stamp a number onto each selected page."""

    def __init__(self, parent=None):
        super().__init__(_("Add Page Numbers"), parent)

        self.template = QLineEdit(stamp.PAGE_TOKEN)
        self.template.setToolTip(
            _("%s is replaced by the page number, %s by the number of pages.")
            % (stamp.PAGE_TOKEN, stamp.TOTAL_TOKEN))

        self.start = QSpinBox()
        self.start.setRange(-9999, 99999)
        self.start.setValue(1)

        self.skip_first = QCheckBox(_("Leave the first page unnumbered"))
        self.skip_first.setToolTip(_("It is still counted; a title page just "
                                     "does not carry a number."))

        form = QFormLayout()
        form.addRow(_("Format"), self.template)
        form.addRow(_("Start at"), self.start)
        form.addRow("", self.skip_first)
        box = QGroupBox(_("Numbering"))
        box.setLayout(form)
        self.add(box)

        self.style = _StampStyleWidget(stamp.NUMBER_STYLE)
        self.add(self.style)
        self.finish()

    def value(self) -> dict:
        return {
            "template": self.template.text() or stamp.PAGE_TOKEN,
            "start": self.start.value(),
            "skip_first": self.skip_first.isChecked(),
            "style": self.style.value(),
        }


class WatermarkDialog(BaseDialog):
    """Stamp the same text across each selected page."""

    def __init__(self, parent=None):
        super().__init__(_("Add Watermark"), parent)

        self.text = QLineEdit()
        self.text.setPlaceholderText(_("DRAFT"))
        form = QFormLayout()
        form.addRow(_("Text"), self.text)
        box = QGroupBox(_("Watermark"))
        box.setLayout(form)
        self.add(box)

        self.style = _StampStyleWidget(stamp.WATERMARK_STYLE, rotation=True)
        self.add(self.style)

        # A watermark that says nothing is not a watermark, and an empty one
        # would raise out of stamp.add_watermark.
        self.ok = self.buttons.button(QDialogButtonBox.Ok)
        self.text.textChanged.connect(
            lambda value: self.ok.setEnabled(bool(value.strip())))
        self.ok.setEnabled(False)
        self.finish()

    def value(self) -> dict:
        return {"text": self.text.text(), "style": self.style.value()}


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
    "export/linearize": False,
    "export/compress": False,
    "image/ppi": 300,
    "image/greyscale": False,
}

#: Marked with N_ so the names reach the template; the combo box below
#: translates them with _() when it is filled.
THEMES = [("system", N_("System")), ("light", N_("Light")), ("dark", N_("Dark"))]


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
        general.addRow(_("Language"), self.language)
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
        self.linearize = QCheckBox(_("Optimize for the web (linearize)"))
        self.linearize.setChecked(bool(current["export/linearize"]))
        self.linearize.setToolTip(
            _("Lay the file out so a browser can show page one "
              "before the rest has downloaded."))

        self.compress = QCheckBox(_("Compress"))
        self.compress.setChecked(bool(current["export/compress"]))
        self.compress.setToolTip(
            _("Recompress the file's streams and pack its objects together.")
            + "\n"
            + _("How much this saves depends on the file: one full of "
                "already-compressed images will barely shrink."))

        saving = QVBoxLayout()
        saving.addWidget(self.preserve_first)
        saving.addWidget(self.linearize)
        saving.addWidget(self.compress)
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
            "export/linearize": self.linearize.isChecked(),
            "export/compress": self.compress.isChecked(),
            "image/ppi": self.ppi.value(),
            "image/greyscale": self.greyscale.isChecked(),
            "shortcuts": dict(self._shortcuts),
        }


class ViewerPreferencesDialog(BaseDialog):
    """How a viewer should open the saved document.

    Separate from Preferences: these are properties *of the document*, saved
    into the file, not settings of this application. They sit with Properties
    and Encrypt for that reason.
    """

    def __init__(self, prefs, parent=None):
        super().__init__(_("Viewer Preferences"), parent)

        self.page_mode = QComboBox()
        for value, label in viewer.PAGE_MODES:
            self.page_mode.addItem(label(), value)
        self._select(self.page_mode, prefs.page_mode)

        self.page_layout = QComboBox()
        for value, label in viewer.PAGE_LAYOUTS:
            self.page_layout.addItem(label(), value)
        self._select(self.page_layout, prefs.page_layout)

        form = QFormLayout()
        form.addRow(_("Open showing:"), self.page_mode)
        form.addRow(_("Page layout:"), self.page_layout)
        box = QGroupBox(_("On opening"))
        box.setLayout(form)
        self.add(box)

        self.flags = {}
        flags = QVBoxLayout()
        for name, label in viewer.FLAGS:
            check = QCheckBox(label())
            check.setChecked(name in prefs.flags)
            self.flags[name] = check
            flags.addWidget(check)
        box = QGroupBox(_("Window"))
        box.setLayout(flags)
        self.add(box)

        note = QLabel(_("Readers are free to ignore all of this."))
        note.setWordWrap(True)
        self.add(note)

        self.finish()

    @staticmethod
    def _select(combo, data):
        index = combo.findData(data)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def value(self) -> "viewer.Preferences":
        return viewer.Preferences(
            page_mode=self.page_mode.currentData(),
            page_layout=self.page_layout.currentData(),
            flags=frozenset(name for name, check in self.flags.items()
                            if check.isChecked()),
        )


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
        (_("Reading"), [
            _("The application opens in <b>read mode</b>: a continuous page "
              "view for reading the document rather than rearranging it. "
              "<b>View ▸ Arrange Mode</b> (Ctrl+E) swaps to the thumbnail grid "
              "and back."),
            _("Reading shows the document <i>as edited</i>: rotations, crops, "
              "deletions and reordering are all applied, so what you read is "
              "what you would get if you saved. Page-editing commands are "
              "disabled while reading — bookmarks are the exception, and are "
              "edited here and nowhere else."),
            _("The page you are on follows you between the two modes. "
              "Switching to read mode opens at the page selected in the grid, "
              "the first of them if several are selected; switching back "
              "scrolls the grid to the page you were reading, without "
              "disturbing what you had selected. With nothing selected, "
              "reading resumes where you left off — your place in each "
              "document is remembered between visits."),
            _("The toolbar shows which page you are on and how many there are; "
              "type a number into it to jump there, or use <b>Ctrl+G</b>."),
            _("<b>View ▸ Continuous Scroll</b> is on by default; turning it "
              "off shows one page at a time. <b>View ▸ Facing Pages</b> puts "
              "two pages side by side, the way a book falls open. Both "
              "settings are remembered."),
        ]),
        (_("Moving around a document"), [
            _("One rule for the arrow keys: <b>the modifier decides what "
              "moves</b>. Nothing scrolls the view, Option (Alt) moves the "
              "text cursor, Shift extends the selection, Command (Ctrl) jumps "
              "to an edge, and Fn — Page Up, Page Down, Home and End — jumps "
              "further. None of it changes according to whether a text cursor "
              "happens to be on the page."),
            "<table border='1' cellpadding='4' cellspacing='0' width='100%'>"
            "<tr><th align='left'>" + _("Keys") + "</th>"
            "<th align='left'>" + _("Continuous") + "</th>"
            "<th align='left'>" + _("One page at a time") + "</th></tr>"
            "<tr><td>↑ ↓</td><td>" + _("scroll one line") + "</td>"
            "<td>—</td></tr>"
            "<tr><td>← →</td><td>" + _("top of the previous / next page") +
            "</td><td>" + _("previous / next page") + "</td></tr>"
            "<tr><td>Page Up / Page Down</td><td>" + _("scroll one screen") +
            "</td><td>" + _("previous / next page") + "</td></tr>"
            "<tr><td>Home / End</td><td colspan='2'>" +
            _("start / end of the document") + "</td></tr>"
            "<tr><td>Option + arrow</td><td colspan='2'>" +
            _("move the text cursor, by character or line") + "</td></tr>"
            "<tr><td>Shift + arrow</td><td colspan='2'>" +
            _("extend the selection, by character or line") + "</td></tr>"
            "<tr><td>Command + Option + ← →</td><td colspan='2'>" +
            _("move the text cursor one word") + "</td></tr>"
            "<tr><td>Shift + Option + ← →</td><td colspan='2'>" +
            _("extend the selection one word") + "</td></tr>"
            "<tr><td>Command + ← →</td><td colspan='2'>" +
            _("cursor to the start / end of the line") + "</td></tr>"
            "<tr><td>Command + ↑ ↓</td><td colspan='2'>" +
            _("cursor to the start / end of the document") + "</td></tr>"
            "</table>",
            _("Add Shift to a Command or Option combination to extend the "
              "selection instead of moving — <b>Shift+Command+→</b> selects to "
              "the end of the line. Adding Option works by the word rather "
              "than the character. On Windows and Linux, read Command as Ctrl "
              "and Option as Alt; the table is the same everywhere."),
        ]),
        (_("Selecting and copying text"), [
            _("Drag across the page to select text, across page boundaries if "
              "you keep going. <b>Double-click</b> selects a word. "
              "<b>Ctrl/Cmd+C</b> copies, <b>Ctrl/Cmd+A</b> selects the text of "
              "the page you are on, and <b>Esc</b> clears the selection. The "
              "same commands are on the right-click menu."),
            _("<b>Shift+click</b> extends an existing selection to where you "
              "clicked. The end you are moving grows out to a whole word, "
              "because a single click is an imprecise way to point at one "
              "character; the end you started from stays exactly where you put "
              "it. Dragging selects by character throughout, since you can "
              "watch it and stop where you like."),
            _("Clicking on text leaves a blinking <b>text cursor</b>. That is "
              "what Shift+arrow extends from, and what the Option and Command "
              "combinations above move. It stays where you put it — scrolling, "
              "paging and clicking off the page all leave it alone — until you "
              "press Esc or open another document."),
        ]),
        (_("Following links"), [
            _("Click a link to follow it. Links to a page in the same document "
              "jump there; links to the web open in your browser. Hovering "
              "over one shows where it goes, which is worth reading before you "
              "click: many links in a PDF are not written by its author at all "
              "but inferred from the text, so what a link points at is not "
              "always what the words appear to say."),
            _("Only ordinary web and mail links are handed to the system — "
              "http, https, mailto and ftp. A document is a file that arrived "
              "from somewhere, and anything else it asks to open is refused "
              "and reported rather than acted on."),
            _("Right-clicking a link offers <b>Open Link</b> and <b>Copy Link "
              "Address</b>."),
        ]),
        (_("Bookmarks"), [
            _("The sidebar shows the document's bookmarks. Click one to jump "
              "to it. Everything below is on the sidebar's right-click menu, "
              "and every command can be undone."),
            _("<b>Add Bookmark Here</b> makes one pointing at the page you are "
              "reading, named after whatever text you have selected — so "
              "select a heading, then add. With nothing selected it is named "
              "after the page. <b>Add Child Bookmark Here</b> does the same, "
              "nested under the entry you clicked."),
            _("<b>Rename</b> edits the title in place. <b>Re-home to This "
              "Page</b> points an existing bookmark at the page you are on, "
              "keeping its title. <b>Delete</b> removes an entry and "
              "<i>promotes</i> its children into its place; <b>Delete with "
              "Children</b> removes the whole branch."),
            _("Drag entries within the sidebar to re-nest or reorder them. "
              "<b>Expand All Children</b> and <b>Collapse All Children</b> "
              "open or shut a whole branch at once."),
            _("<b>Style</b> sets a bookmark bold or italic, or gives it a "
              "colour, as the tree shows."),
            _("A bookmark whose page has been deleted is <b>greyed out</b> "
              "rather than removed: its title may still be worth keeping, and "
              "you can point it somewhere else with Re-home. Undoing the "
              "deletion reconnects it. <b>Delete Dangling Bookmarks</b> clears "
              "them all out; it leaves alone any entry that points nowhere on "
              "purpose, which is a legitimate way to write a heading."),
            _("Bookmark edits are part of the document and are written when "
              "you save, along with each entry's colour and style and which "
              "branches are left open. The one thing that cannot be saved is a "
              "bookmark with no page: there is no way to record \u201cpoints at "
              "a page that is gone\u201d, so it comes back as a heading with its "
              "title intact."),
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
            _("To move pages a long way, use <b>Move to Start</b>, <b>Move to "
              "End</b> or <b>Move to Page…</b> rather than dragging — in a "
              "long document the far end is a great deal of scrolling away. "
              "They are on the Edit menu and on the right-click menu, and "
              "<b>Move to Page…</b> asks for the number the page should "
              "<i>become</i>."),
            _("Prefer these to cut and paste for moving. A pasted page is a "
              "<i>new</i> page as far as the document is concerned, so any "
              "bookmarks pointing at the original are left behind with nowhere "
              "to go. Moving keeps the page itself, and its bookmarks come "
              "with it."),
        ]),
        (_("Stamping and tiling"), [
            _("<b>Page ▸ Add Page Numbers…</b> and <b>Page ▸ Add Watermark…</b> "
              "draw text onto the selected pages. Both add a <i>layer</i> "
              "rather than rewriting the page, so both can be undone and "
              "neither touches the file you opened."),
            _("Page numbers follow the arrangement, not the source document: "
              "they are numbered in the order the pages are in now. "
              "<code>{n}</code> in the format is the page number and "
              "<code>{total}</code> the number of pages, so "
              "<code>Page {n} of {total}</code> does what it looks like."),
            _("<b>Arrange ▸ Pages per Sheet…</b> tiles several pages onto one, "
              "in reading order — the printer's <i>N-up</i>. The sheet turns "
              "sideways when that lets the pages come out larger, which is why "
              "two-up gives a landscape sheet and four-up does not."),
        ]),
        (_("Saving a document"), [
            _("<b>Optimize for the web</b> in Preferences lays the saved file "
              "out so a browser can show the first page before the rest has "
              "arrived. <b>Compress</b> repacks its streams and objects; how "
              "much that saves depends entirely on the file, and one full of "
              "photographs will barely move."),
            _("<b>File ▸ Remove All Metadata</b> is a switch, like Password: "
              "turn it on and the next save writes a document with no title, "
              "no author and no record of what produced it. Edit Properties "
              "greys out while it is on, because there would be nothing to "
              "edit."),
            _("<b>File ▸ Viewer Preferences…</b> is how the saved document asks "
              "a reader to open it — with the bookmarks showing, two pages at "
              "a time, and so on. Readers are free to ignore all of it. The "
              "settings are read from the file you opened, so a document that "
              "already had them keeps them."),
            _("<b>File ▸ Repair Document…</b> rebuilds a damaged PDF. It works "
              "on a file you pick rather than the one on screen, because the "
              "file worth repairing is usually one this application cannot "
              "open properly either. It reports what it found before writing "
              "anything."),
        ]),
        (_("Mouse"), [
            _("<b>Ctrl + scroll</b> — zoom"),
            _("<b>Shift + scroll</b> — scroll sideways"),
            _("<b>Alt + scroll</b> — scroll exactly one row"),
            _("<b>Double-click</b> — fit the page to the window, and back"),
            _("<b>Click and drag</b> on empty space — rubber-band select; keep "
              "scrolling to extend it"),
        ]),
        (_("Moving around the grid"), [
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
        blocks = ("<table", "<ul", "<ol", "<pre")
        for heading, paragraphs in help_sections():
            parts.append(f"<h3>{heading}</h3>")
            for text in paragraphs:
                # A table is a block in its own right; wrapping it in <p> nests
                # a block inside a paragraph, which renders unpredictably.
                stripped = text.lstrip()
                if stripped.startswith(blocks):
                    parts.append(text)
                else:
                    parts.append(f"<p>{text}</p>")
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
