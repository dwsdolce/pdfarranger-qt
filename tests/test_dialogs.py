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

"""The dialog widgets and the values they hand back."""

import unittest

from pdfarranger_qt.core import Dims, Page, Sides


class TestPageRangeParsing(unittest.TestCase):
    def parse(self, text, count=10):
        from pdfarranger_qt.dialogs import parse_page_range

        return parse_page_range(text, count)

    def test_single_numbers(self):
        self.assertEqual(self.parse("1,3,5"), [0, 2, 4])

    def test_ranges(self):
        self.assertEqual(self.parse("5-7"), [4, 5, 6])

    def test_mixed_example_from_the_hint(self):
        self.assertEqual(self.parse("1,3,5-7,9"), [0, 2, 4, 5, 6, 8])

    def test_whitespace_and_duplicates(self):
        self.assertEqual(self.parse(" 1 , 1 , 2 "), [0, 1])

    def test_reversed_range_is_accepted(self):
        self.assertEqual(self.parse("7-5"), [4, 5, 6])

    def test_out_of_range_is_dropped(self):
        self.assertEqual(self.parse("9-20", count=10), [8, 9])

    def test_rubbish_is_ignored(self):
        self.assertEqual(self.parse("abc,,-,2"), [1])

    def test_empty(self):
        self.assertEqual(self.parse(""), [])

class TestPaperSizeWidget(unittest.TestCase):
    def widget(self, size=None):
        from pdfarranger_qt.dialogs import PaperSizeWidget

        return PaperSizeWidget(size)

    def test_defaults_to_a4_when_no_size_given(self):
        w = self.widget()
        self.assertAlmostEqual(w.width.value(), 210.0, places=1)
        self.assertAlmostEqual(w.height.value(), 297.0, places=1)

    def test_recognises_a_known_paper_size(self):
        w = self.widget((210.0, 297.0))
        self.assertEqual(w.combo.currentText(), "A4")

    def test_custom_size_selects_custom(self):
        w = self.widget((123.0, 456.0))
        self.assertEqual(w.combo.currentIndex(), 0)

    def test_choosing_a_preset_sets_the_values(self):
        w = self.widget((123.0, 456.0))
        w.combo.setCurrentIndex(1 + [p[0] for p in
                                     __import__("pdfarranger_qt.dialogs",
                                                fromlist=["x"]).PAPER_SIZES].index("A3"))
        self.assertAlmostEqual(w.width.value(), 297.0, places=1)
        self.assertAlmostEqual(w.height.value(), 420.0, places=1)

    def test_orientation_swaps_the_sides(self):
        w = self.widget((210.0, 297.0))
        w.landscape.setChecked(True)
        self.assertAlmostEqual(w.width.value(), 297.0, places=1)
        self.assertAlmostEqual(w.height.value(), 210.0, places=1)

    def test_aspect_lock_drives_the_other_side(self):
        w = self.widget((100.0, 200.0))
        self.assertTrue(w.lock_ratio.isChecked())
        w.width.setValue(150.0)
        self.assertAlmostEqual(w.height.value(), 300.0, places=1)

    def test_points_conversion(self):
        w = self.widget((25.4, 25.4))
        size = w.size_points()
        self.assertAlmostEqual(size.width, 72.0, places=3)
        self.assertAlmostEqual(size.height, 72.0, places=3)

class TestPhase2DialogValues(unittest.TestCase):
    """Dialogs are modal, so drive the widgets and read value() directly."""

    def test_crop_dialog_returns_fractions(self):
        from pdfarranger_qt.dialogs import CropHideDialog

        d = CropHideDialog(Sides(), hide=False)
        d.spins["left"].setValue(10.0)
        d.spins["bottom"].setValue(25.0)
        sides = d.value()
        self.assertAlmostEqual(sides.left, 0.10, places=6)
        self.assertAlmostEqual(sides.bottom, 0.25, places=6)

    def test_crop_dialog_prefills_from_the_page(self):
        from pdfarranger_qt.dialogs import CropHideDialog

        d = CropHideDialog(Sides(0.1, 0.2, 0.3, 0.4), hide=True)
        self.assertAlmostEqual(d.spins["right"].value(), 20.0, places=3)

    def test_crop_dialog_rejects_cropping_everything_away(self):
        from pdfarranger_qt.dialogs import CropHideDialog

        d = CropHideDialog(Sides(), hide=False)
        d.spins["left"].setValue(60.0)
        d.spins["right"].setValue(50.0)
        self.assertIsNone(d.value(), "a page cropped to nothing must be refused")

    def test_crop_dialog_uniform_mirrors_all_sides(self):
        from pdfarranger_qt.dialogs import CropHideDialog

        d = CropHideDialog(Sides(), hide=False)
        d.spins["left"].setValue(12.0)
        d.uniform.setChecked(True)
        sides = d.value()
        self.assertEqual(len(set(round(s, 6) for s in sides)), 1)

    def test_scale_dialog_relative_mode(self):
        from pdfarranger_qt.dialogs import ScaleDialog

        page = Page(1, 1, "a.pdf", size_orig=Dims(612, 792))
        d = ScaleDialog(page)
        d.rel_radio.setChecked(True)
        d.percent.setValue(150.0)
        target, mode = d.value()
        self.assertEqual(mode, ScaleDialog.MODE_SCALE)
        self.assertAlmostEqual(target, 1.5, places=6)

    def test_scale_dialog_fit_mode_returns_points(self):
        from pdfarranger_qt.dialogs import ScaleDialog

        page = Page(1, 1, "a.pdf", size_orig=Dims(612, 792))
        d = ScaleDialog(page)
        d.fit_radio.setChecked(True)
        d.paper.lock_ratio.setChecked(False)
        d.paper.width.setValue(210.0)
        d.paper.height.setValue(297.0)
        target, mode = d.value()
        self.assertEqual(mode, ScaleDialog.MODE_SCALE)
        self.assertAlmostEqual(target.width, 595.27, places=1)

    def test_split_dialog_defaults_to_two_columns(self):
        from pdfarranger_qt.dialogs import SplitDialog

        self.assertEqual(SplitDialog().value(), (2, 1))

    def test_merge_dialog_offsets(self):
        from pdfarranger_qt.dialogs import MergeDialog

        d = MergeDialog("UNDERLAY")
        laypos, offset, rescale = d.value()
        self.assertEqual(laypos, "UNDERLAY")
        self.assertEqual(offset, (0.5, 0.5))
        self.assertAlmostEqual(rescale, 1.0, places=6)

class TestPreferencesDialogWidget(unittest.TestCase):
    def test_reads_back_what_it_was_given(self):
        from pdfarranger_qt.dialogs import PreferencesDialog

        given = {"language": "fr", "theme": "light", "print/scale-mode": "actual",
                 "print/auto-rotate": False,
                 "export/preserve-first-document": True,
                 "image/ppi": 200, "image/greyscale": True}
        d = PreferencesDialog(given, [])
        out = d.value()
        for key, expected in given.items():
            self.assertEqual(out[key], expected, key)

    def test_unknown_language_falls_back_to_system(self):
        from pdfarranger_qt.dialogs import PreferencesDialog

        d = PreferencesDialog({"language": "xx"}, [])
        self.assertEqual(d.value()["language"], "")

    def test_preferences_reports_no_shortcut_changes_by_default(self):
        from PySide6.QtGui import QAction, QKeySequence
        from pdfarranger_qt.dialogs import PreferencesDialog

        action = QAction("&Duplicate")
        action.setObjectName("duplicate")
        action.setShortcut(QKeySequence("Ctrl+D"))
        d = PreferencesDialog({}, [action])
        self.assertEqual(d.value()["shortcuts"], {},
                         "untouched shortcuts must not be rewritten")

class TestShortcutsDialog(unittest.TestCase):
    """Shortcuts live in their own scrollable window (60+ actions)."""

    def actions(self):
        from PySide6.QtGui import QAction, QKeySequence

        made = []
        for name, label, keys in (("duplicate", "&Duplicate", "Ctrl+D"),
                                  ("delete", "&Delete", "Del"),
                                  ("save", "&Save", "Ctrl+S")):
            action = QAction(label)
            action.setObjectName(name)
            action.setShortcut(QKeySequence(keys))
            made.append(action)
        return made

    def test_lists_every_action_with_its_current_binding(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions())
        self.assertEqual(set(d.edits), {"duplicate", "delete", "save"})
        self.assertEqual(d.edits["duplicate"].keySequence().toString(), "Ctrl+D")

    def test_editing_a_binding_is_reported(self):
        from PySide6.QtGui import QKeySequence
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions())
        d.edits["duplicate"].setKeySequence(QKeySequence("Ctrl+J"))
        self.assertEqual(d.value()["duplicate"], "Ctrl+J")

    def test_clearing_a_binding_drops_it(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions())
        d.edits["delete"].clear()
        self.assertNotIn("delete", d.value())

    def test_reset_clears_everything(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions())
        d._clear_all()
        self.assertEqual(d.value(), {})

    def test_duplicate_actions_are_listed_once(self):
        """The same action can sit in a menu and a context menu."""
        from pdfarranger_qt.dialogs import ShortcutsDialog

        actions = self.actions()
        d = ShortcutsDialog(actions + actions)
        self.assertEqual(len(d.edits), 3)

    def test_overrides_take_precedence_over_the_action(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions(), {"duplicate": "Ctrl+9"})
        self.assertEqual(d.edits["duplicate"].keySequence().toString(), "Ctrl+9")

    def test_body_is_scrollable(self):
        from PySide6.QtWidgets import QScrollArea
        from pdfarranger_qt.dialogs import ShortcutsDialog

        d = ShortcutsDialog(self.actions())
        self.assertTrue(d.findChildren(QScrollArea),
                        "the list must scroll; there are sixty-odd actions")


if __name__ == "__main__":
    unittest.main()

class TestHelpDialog(unittest.TestCase):
    """The in-app user guide replaces the man page."""

    def test_sections_are_present(self):
        from pdfarranger_qt.dialogs import help_sections

        headings = [heading for heading, _body in help_sections()]
        self.assertIn("Description", headings)
        self.assertIn("Mouse", headings)
        self.assertIn("Credits", headings)

    def test_every_section_has_content(self):
        from pdfarranger_qt.dialogs import help_sections

        for heading, body in help_sections():
            self.assertTrue(body, f"{heading} has no text")

    def test_documents_the_mouse_gestures(self):
        """These are the least discoverable part of the app; help must cover them."""
        from pdfarranger_qt.dialogs import help_sections

        text = " ".join(t for _h, body in help_sections() for t in body)
        for gesture in ("Ctrl + scroll", "Shift + scroll", "Alt + scroll",
                        "Double-click"):
            self.assertIn(gesture, text)

    def test_documents_the_duplex_scan_workflow(self):
        from pdfarranger_qt.dialogs import help_sections

        text = " ".join(t for _h, body in help_sections() for t in body)
        self.assertIn("Reverse Order", text)
        self.assertIn("double-sided", text)

    def test_renders_as_html(self):
        from pdfarranger_qt.dialogs import HelpDialog

        dialog = HelpDialog()
        self.addCleanup(dialog.close)
        body = dialog.browser.toPlainText()
        self.assertIn("PDF Arranger", body)
        self.assertGreater(len(body), 500)

    def test_help_action_opens_it_non_modally(self):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        self.addCleanup(win.close)
        win.show_help()
        self.assertIsNotNone(win._help_dialog)
        self.assertFalse(win._help_dialog.isModal(),
                         "help should be readable while working")
        # Opening twice reuses the same window rather than stacking them up.
        first = win._help_dialog
        win.show_help()
        self.assertIs(win._help_dialog, first)


class TestShortcutOrdering(unittest.TestCase):
    """The editor listed 73 actions in QObject construction order.

    findChildren(QAction) returns children in the order they were built, not
    menu order, so the list was unscannable: submenu entries scattered through
    it and no relationship to where a command lives.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_groups_follow_the_menu_bar(self):
        titles = [t for t, _actions in self.win._shortcut_groups()]
        self.assertEqual(titles, ["File", "Edit", "Page", "Arrange", "View", "Help"])

    def test_first_group_starts_with_the_first_menu_entry(self):
        _title, actions = self.win._shortcut_groups()[0]
        self.assertEqual(actions[0].text().replace("&", ""), "New Window")

    def test_submenu_entries_are_included(self):
        """Paste As Odd Pages lives in a submenu and must still be rebindable."""
        labels = [a.text().replace("&", "") for a in self.win._shortcut_actions()]
        self.assertIn("Paste As Odd Pages", labels)
        self.assertIn("Export Selection to PNG Images…", labels)

    def test_no_duplicates(self):
        names = [a.objectName() or a.text() for a in self.win._shortcut_actions()]
        self.assertEqual(len(names), len(set(names)))

    def test_dialog_renders_the_groups(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        groups = self.win._shortcut_groups()
        dialog = ShortcutsDialog(groups)
        self.assertEqual(len(dialog.edits), sum(len(a) for _t, a in groups))

    def test_dialog_still_accepts_a_flat_list(self):
        from pdfarranger_qt.dialogs import ShortcutsDialog

        actions = self.win._shortcut_actions()
        dialog = ShortcutsDialog(actions)
        self.assertEqual(len(dialog.edits), len(actions))
