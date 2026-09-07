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

"""Phase 8: the window's end of web-optimize, strip-metadata and viewer prefs.

The backends have their own tests. What is checked here is the wiring -- that
a checkbox in Preferences and a toggle in the File menu actually reach the
`SaveOptions` the save is given, which is the half that silently does nothing
when it is wrong.
"""

import unittest

import pikepdf

from pdfarranger_qt import dialogs, viewer

from support import TEST_PDF, settle, temp_path


def with_viewer_prefs(**kwargs):
    """A copy of the test document that asks to open a particular way."""
    path = temp_path("has_prefs.pdf")
    with pikepdf.open(TEST_PDF) as pdf:
        viewer.Preferences(**kwargs).write(pdf)
        pdf.save(path)
    return path


class WindowTestCase(unittest.TestCase):
    #: Settings this class writes, cleared again so the next test starts level.
    KEYS = ("export/linearize", "export/compress")

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)

    def tearDown(self):
        for key in self.KEYS:
            self.win.settings.remove(key)
        self.win.modified = False
        self.win.close()

    def captured_options(self):
        """The SaveOptions a save would be given, without writing anything."""
        from pdfarranger_qt import mainwindow

        seen = {}

        def fake_export(*args, **kwargs):
            seen["options"] = kwargs.get("options")
            return ""

        real = mainwindow.export
        mainwindow.export = fake_export
        try:
            self.win._write([temp_path("out.pdf")], self.win.model.pages)
        finally:
            mainwindow.export = real
        self.assertIn("options", seen, "the save never called export()")
        return seen["options"]


class TestSaveOptionsWiring(WindowTestCase):
    def test_nothing_is_asked_for_by_default(self):
        options = self.captured_options()
        self.assertFalse(options.linearize)
        self.assertFalse(options.compress)
        self.assertFalse(options.strip_metadata)
        self.assertTrue(options.viewer.is_empty())

    def test_the_preferences_reach_the_save(self):
        self.win.settings.setValue("export/linearize", True)
        self.win.settings.setValue("export/compress", True)
        options = self.captured_options()
        self.assertTrue(options.linearize)
        self.assertTrue(options.compress)

    def test_the_strip_toggle_reaches_the_save(self):
        self.win.act_strip_metadata.setChecked(True)
        self.assertTrue(self.captured_options().strip_metadata)

    def test_the_viewer_preferences_reach_the_save(self):
        self.win.viewer_prefs = viewer.Preferences(page_mode="UseOutlines")
        self.assertEqual(self.captured_options().viewer.page_mode, "UseOutlines")

    def test_a_real_save_honours_them(self):
        """End to end, with no stand-in for the exporter."""
        self.win.settings.setValue("export/linearize", True)
        self.win.viewer_prefs = viewer.Preferences(page_mode="UseThumbs")
        path = temp_path("real.pdf")
        self.assertTrue(self.win._write([path], self.win.model.pages))
        with pikepdf.open(path) as pdf:
            self.assertTrue(pdf.is_linearized)
            self.assertEqual(viewer.Preferences.read(pdf).page_mode, "UseThumbs")


class TestStripMetadataToggle(WindowTestCase):
    def test_it_is_a_toggle_not_a_command(self):
        self.assertTrue(self.win.act_strip_metadata.isCheckable())

    def test_turning_it_on_shuts_off_editing_properties(self):
        """Editing what is about to be discarded is a contradiction."""
        self.assertTrue(self.win.act_properties.isEnabled())
        self.win.act_strip_metadata.setChecked(True)
        self.win.set_strip_metadata(True)
        self.assertFalse(self.win.act_properties.isEnabled())
        self.win.act_strip_metadata.setChecked(False)
        self.win.set_strip_metadata(False)
        self.assertTrue(self.win.act_properties.isEnabled())

    def test_it_marks_the_document_modified(self):
        self.win.modified = False
        self.win.act_strip_metadata.setChecked(True)
        self.win.set_strip_metadata(True)
        self.assertTrue(self.win.modified)

    def test_closing_the_document_clears_it(self):
        self.win.act_strip_metadata.setChecked(True)
        self.win.modified = False
        self.win.close_document()
        self.assertFalse(self.win.act_strip_metadata.isChecked())


class TestViewerPreferencesFromTheFile(WindowTestCase):
    def test_opening_takes_what_the_file_asks_for(self):
        self.win.modified = False
        self.win.open_paths([with_viewer_prefs(
            page_mode="UseOutlines", flags=frozenset({"DisplayDocTitle"}))])
        settle(timeout_ms=300)
        self.assertEqual(self.win.viewer_prefs.page_mode, "UseOutlines")
        self.assertEqual(self.win.viewer_prefs.flags,
                         frozenset({"DisplayDocTitle"}))

    def test_a_plain_file_leaves_them_empty(self):
        self.assertTrue(self.win.viewer_prefs.is_empty())

    def test_importing_does_not_rewrite_them(self):
        """A file added to an open document does not get to decide this."""
        self.win.viewer_prefs = viewer.Preferences(page_mode="UseThumbs")
        self.win._load_paths([with_viewer_prefs(page_mode="UseOutlines")])
        settle(timeout_ms=300)
        self.assertEqual(self.win.viewer_prefs.page_mode, "UseThumbs")

    def test_a_round_trip_keeps_them(self):
        """The reason for reading at open: saving builds a brand new PDF."""
        self.win.modified = False
        self.win.open_paths([with_viewer_prefs(page_layout="TwoColumnRight")])
        settle(timeout_ms=300)
        path = temp_path("round.pdf")
        self.assertTrue(self.win._write([path], self.win.model.pages))
        with pikepdf.open(path) as pdf:
            self.assertEqual(viewer.Preferences.read(pdf).page_layout,
                             "TwoColumnRight")

    def test_closing_the_document_clears_them(self):
        self.win.viewer_prefs = viewer.Preferences(page_mode="UseThumbs")
        self.win.modified = False
        self.win.close_document()
        self.assertTrue(self.win.viewer_prefs.is_empty())


class TestMenu(WindowTestCase):
    def test_the_new_commands_are_in_the_file_menu(self):
        titles = [self.win.menuBar().actions()[i].text()
                  for i in range(len(self.win.menuBar().actions()))]
        self.assertIn("&File", titles)
        file_menu = self.win.menuBar().actions()[titles.index("&File")].menu()
        entries = [a for a in file_menu.actions() if not a.isSeparator()]
        for act in (self.win.act_viewer_prefs, self.win.act_strip_metadata,
                    self.win.act_repair):
            self.assertIn(act, entries)

    def test_repair_works_without_a_document(self):
        """It acts on a file chosen in the dialog, not on what is loaded."""
        self.win.modified = False
        self.win.close_document()
        self.assertTrue(self.win.act_repair.isEnabled())


class TestPreferencesDialog(unittest.TestCase):
    def test_the_new_keys_have_defaults(self):
        for key in ("export/linearize", "export/compress"):
            self.assertIn(key, dialogs.PREFERENCES)
            self.assertIs(dialogs.PREFERENCES[key], False)

    def test_the_dialog_hands_them_back(self):
        dialog = dialogs.PreferencesDialog({"export/linearize": True})
        self.assertTrue(dialog.linearize.isChecked())
        self.assertFalse(dialog.compress.isChecked())
        dialog.compress.setChecked(True)
        value = dialog.value()
        self.assertTrue(value["export/linearize"])
        self.assertTrue(value["export/compress"])

    def test_every_default_is_returned(self):
        """A key in PREFERENCES the dialog forgets would never be saved."""
        value = dialogs.PreferencesDialog({}).value()
        for key in dialogs.PREFERENCES:
            self.assertIn(key, value)


class TestViewerPreferencesDialog(unittest.TestCase):
    def test_it_shows_what_it_was_given(self):
        prefs = viewer.Preferences(page_mode="UseThumbs",
                                   page_layout="OneColumn",
                                   flags=frozenset({"HideToolbar"}))
        dialog = dialogs.ViewerPreferencesDialog(prefs)
        self.assertEqual(dialog.value(), prefs)

    def test_an_empty_preference_comes_back_empty(self):
        dialog = dialogs.ViewerPreferencesDialog(viewer.Preferences())
        self.assertTrue(dialog.value().is_empty())

    def test_a_flag_can_be_turned_off_again(self):
        dialog = dialogs.ViewerPreferencesDialog(
            viewer.Preferences(flags=frozenset({"HideMenubar"})))
        dialog.flags["HideMenubar"].setChecked(False)
        self.assertEqual(dialog.value().flags, frozenset())

    def test_an_unknown_value_falls_back_to_no_preference(self):
        dialog = dialogs.ViewerPreferencesDialog(
            viewer.Preferences(page_mode="FullScreen"))
        self.assertIsNone(dialog.value().page_mode)


class TestPageMenuCommands(WindowTestCase):
    """N-up, page numbers and watermarks, driven through the window."""

    def dialog_returns(self, name, value):
        """Make one dialog answer without showing it."""
        real = getattr(dialogs, name)

        class Fake:
            def __init__(self, *args, **kwargs):
                pass

            def get_value(self):
                return value

        setattr(dialogs, name, Fake)
        self.addCleanup(setattr, dialogs, name, real)

    def select_all(self):
        self.win.view.set_selected_rows(list(range(self.win.model.rowCount())))

    def entries(self, title):
        titles = [a.text() for a in self.win.menuBar().actions()]
        menu = self.win.menuBar().actions()[titles.index(title)].menu()
        return [a for a in menu.actions() if not a.isSeparator()]

    def test_stamping_lives_with_the_other_per_page_commands(self):
        page = self.entries("&Page")
        self.assertIn(self.win.act_page_numbers, page)
        self.assertIn(self.win.act_watermark, page)

    def test_pages_per_sheet_lives_with_split_and_merge(self):
        """It is composition, like the two commands it sits between."""
        arrange = self.entries("Arrange")
        self.assertIn(self.win.act_nup, arrange)
        self.assertIn(self.win.act_split_pages, arrange)

    def test_pages_per_sheet_replaces_the_selection_with_sheets(self):
        self.dialog_returns("NUpDialog", {"columns": 2, "rows": 1,
                                          "orientation": "auto", "margin": 0.0})
        self.select_all()
        self.win.pages_per_sheet()
        self.assertEqual(self.win.model.rowCount(), 1)
        self.assertEqual(len(self.win.model.pages[0].layerpages), 2)

    def test_a_one_up_grid_does_nothing(self):
        """Asking for one page per sheet is asking for what is already there."""
        self.dialog_returns("NUpDialog", {"columns": 1, "rows": 1,
                                          "orientation": "auto", "margin": 0.0})
        self.select_all()
        self.win.pages_per_sheet()
        self.assertEqual(self.win.model.rowCount(), 2)
        self.assertEqual(self.win.model.pages[0].layerpages, [])

    def test_cancelling_pages_per_sheet_changes_nothing(self):
        self.dialog_returns("NUpDialog", None)
        self.select_all()
        self.win.modified = False
        self.win.pages_per_sheet()
        self.assertEqual(self.win.model.rowCount(), 2)
        self.assertFalse(self.win.modified)

    def test_page_numbers_add_a_layer_without_adding_a_page(self):
        from pdfarranger_qt import stamp

        self.dialog_returns("PageNumbersDialog", {
            "template": "{n}", "start": 1, "skip_first": False,
            "style": stamp.NUMBER_STYLE})
        self.select_all()
        self.win.add_page_numbers()
        self.assertEqual(self.win.model.rowCount(), 2)
        self.assertEqual([len(p.layerpages) for p in self.win.model.pages], [1, 1])
        self.assertTrue(self.win.modified)

    def test_page_numbers_can_be_undone(self):
        from pdfarranger_qt import stamp

        self.dialog_returns("PageNumbersDialog", {
            "template": "{n}", "start": 1, "skip_first": False,
            "style": stamp.NUMBER_STYLE})
        self.select_all()
        self.win.add_page_numbers()
        self.win.model.undo.undo()
        self.assertEqual([len(p.layerpages) for p in self.win.model.pages], [0, 0])

    def test_a_watermark_needs_text(self):
        from pdfarranger_qt import stamp

        self.dialog_returns("WatermarkDialog",
                            {"text": "   ", "style": stamp.WATERMARK_STYLE})
        self.select_all()
        self.win.modified = False
        self.win.add_watermark()
        self.assertEqual([len(p.layerpages) for p in self.win.model.pages], [0, 0])
        self.assertFalse(self.win.modified)

    def test_a_watermark_lands_on_every_selected_page(self):
        from pdfarranger_qt import stamp

        self.dialog_returns("WatermarkDialog",
                            {"text": "DRAFT", "style": stamp.WATERMARK_STYLE})
        self.win.view.set_selected_rows([1])
        self.win.add_watermark()
        self.assertEqual([len(p.layerpages) for p in self.win.model.pages], [0, 1])

    def test_nothing_selected_does_nothing(self):
        self.win.view.set_selected_rows([])
        self.win.modified = False
        self.win.add_page_numbers()
        self.win.add_watermark()
        self.assertFalse(self.win.modified)


class TestStampDialogs(unittest.TestCase):
    def test_page_numbers_default_to_the_bare_number(self):
        from pdfarranger_qt import stamp

        value = dialogs.PageNumbersDialog().value()
        self.assertEqual(value["template"], stamp.PAGE_TOKEN)
        self.assertEqual(value["start"], 1)
        self.assertFalse(value["skip_first"])

    def test_an_empty_format_falls_back_to_the_page_number(self):
        from pdfarranger_qt import stamp

        dialog = dialogs.PageNumbersDialog()
        dialog.template.setText("")
        self.assertEqual(dialog.value()["template"], stamp.PAGE_TOKEN)

    def test_the_style_widget_hands_back_what_was_set(self):
        dialog = dialogs.PageNumbersDialog()
        dialog.style.size.setValue(18)
        dialog.style.bold.setChecked(True)
        dialog.style.opacity.setValue(50)
        style = dialog.value()["style"]
        self.assertEqual(style.size, 18)
        self.assertTrue(style.bold)
        self.assertAlmostEqual(style.opacity, 0.5)

    def test_a_watermark_dialog_starts_with_ok_disabled(self):
        """An empty watermark would raise; the button says so first."""
        from PySide6.QtWidgets import QDialogButtonBox

        dialog = dialogs.WatermarkDialog()
        button = dialog.buttons.button(QDialogButtonBox.Ok)
        self.assertFalse(button.isEnabled())
        dialog.text.setText("DRAFT")
        self.assertTrue(button.isEnabled())
        dialog.text.setText("   ")
        self.assertFalse(button.isEnabled())

    def test_only_the_watermark_dialog_offers_an_angle(self):
        """A rotated corner stamp mostly falls off the page."""
        self.assertIsNone(dialogs.PageNumbersDialog().style.rotation)
        self.assertIsNotNone(dialogs.WatermarkDialog().style.rotation)

    def test_the_nup_presets_drive_the_spin_boxes(self):
        dialog = dialogs.NUpDialog()
        index = dialog.preset.findData("2x2")
        self.assertGreater(index, 0)
        dialog.preset.setCurrentIndex(index)
        self.assertEqual(dialog.value()["columns"], 2)
        self.assertEqual(dialog.value()["rows"], 2)

    def test_an_unlisted_grid_shows_as_custom(self):
        dialog = dialogs.NUpDialog()
        dialog.columns.setValue(5)
        dialog.rows.setValue(3)
        self.assertFalse(dialog.preset.currentData())
        self.assertEqual(dialog.value()["columns"], 5)

    def test_setting_a_grid_that_matches_a_preset_selects_it(self):
        dialog = dialogs.NUpDialog()
        dialog.columns.setValue(3)
        dialog.rows.setValue(3)
        self.assertEqual(dialog.preset.currentData(), "3x3")

    def test_the_gap_is_returned_as_a_fraction(self):
        dialog = dialogs.NUpDialog()
        dialog.gap.setValue(20)
        self.assertAlmostEqual(dialog.value()["margin"], 0.2)


class TestNewCommandsAreEnabledSensibly(WindowTestCase):
    def test_stamping_needs_a_selection(self):
        self.win.view.set_selected_rows([])
        self.assertFalse(self.win.act_page_numbers.isEnabled())
        self.assertFalse(self.win.act_watermark.isEnabled())
        self.win.view.set_selected_rows([0])
        self.assertTrue(self.win.act_page_numbers.isEnabled())
        self.assertTrue(self.win.act_watermark.isEnabled())

    def test_pages_per_sheet_needs_a_contiguous_run(self):
        """It replaces the run it tiles, so a scattered selection has no home."""
        self.win._load_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.assertEqual(self.win.model.rowCount(), 4)
        self.win.view.set_selected_rows([0, 1])
        self.assertTrue(self.win.act_nup.isEnabled())
        self.win.view.set_selected_rows([0, 2])
        self.assertFalse(self.win.act_nup.isEnabled())

    def test_repair_does_not_need_a_document(self):
        self.win.modified = False
        self.win.close_document()
        self.assertTrue(self.win.act_repair.isEnabled())
        self.assertFalse(self.win.act_page_numbers.isEnabled())
