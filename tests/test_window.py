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

"""MainWindow actions, driven through the menu actions themselves."""

import os
import unittest
import pikepdf

from PySide6.QtWidgets import QApplication
from pdfarranger_qt.core import Dims, Sides

from support import HERE, MESSAGE_BOXES, TEST_PDF, TEXT_PDF, settle


class TestPhase1Actions(unittest.TestCase):
    """The new actions, driven through the window as the user would."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.view.selectAll()
        self.win.duplicate_selected()
        for i, page in enumerate(self.win.model.pages):
            page.description = str(i)
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def order(self):
        return [p.description for p in self.win.model.pages]

    def test_copy_then_paste_after(self):
        self.win.view.set_selected_rows([0])
        self.win.copy_selected()
        self.win.view.set_selected_rows([1])
        self.win.paste("AFTER")
        self.assertEqual(len(self.win.model.pages), 5)
        self.assertEqual(self.order()[2], "0")

    def test_paste_before(self):
        self.win.view.set_selected_rows([0])
        self.win.copy_selected()
        self.win.view.set_selected_rows([2])
        self.win.paste("BEFORE")
        self.assertEqual(self.order()[2], "0")

    def test_cut_removes_and_is_undoable(self):
        self.win.view.set_selected_rows([1])
        self.win.cut_selected()
        self.assertEqual(self.order(), ["0", "2", "3"])
        self.win.undo()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_paste_interleaved_odd(self):
        self.win.view.set_selected_rows([0, 1])
        self.win.copy_selected()
        self.win.view.set_selected_rows([0])
        self.win.paste("ODD")
        self.assertEqual(self.order(), ["0", "0", "1", "1", "2", "3"])

    def test_paste_is_disabled_without_page_data(self):
        QApplication.clipboard().setText("not pages")
        self.win._refresh_state()
        self.assertFalse(self.win.act_paste.isEnabled())

    def test_reverse_order_action(self):
        self.win.view.set_selected_rows([0, 1, 2, 3])
        self.win.reverse_order()
        self.assertEqual(self.order(), ["3", "2", "1", "0"])
        self.assertTrue(self.win.modified)

    def test_reverse_needs_contiguous_selection(self):
        self.win.view.set_selected_rows([0, 2])
        self.assertFalse(self.win.act_reverse.isEnabled())
        self.win.reverse_order()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_swap_odd_even_action(self):
        self.win.view.set_selected_rows([0, 1, 2, 3])
        self.win.swap_odd_even()
        self.assertEqual(self.order(), ["1", "0", "3", "2"])

    def test_select_odd_and_even(self):
        self.win.select_parity(1)
        self.assertEqual(self.win.view.selected_rows(), [0, 2])
        self.win.select_parity(0)
        self.assertEqual(self.win.view.selected_rows(), [1, 3])

    def test_select_same_file(self):
        self.win.view.set_selected_rows([0])
        self.win.select_matching("copyname")
        self.assertEqual(self.win.view.selected_rows(), [0, 1, 2, 3])

    def test_zoom_fit_uses_the_viewport_width(self):
        self.win.view.set_selected_rows([0])
        self.win.zoom_fit()
        page = self.win.model.pages[0]
        width = self.win.model.thumb_size(page)[0]
        self.assertLessEqual(width, self.win.view.viewport().width())
        self.assertGreater(width, self.win.view.viewport().width() * 0.7)

    def test_double_click_toggles_zoom_fit_and_back(self):
        before = self.win.model.zoom
        self.win.toggle_zoom_fit()
        self.assertNotAlmostEqual(self.win.model.zoom, before)
        self.win.toggle_zoom_fit()
        self.assertAlmostEqual(self.win.model.zoom, before)

    def test_explicit_zoom_cancels_the_fit_toggle(self):
        self.win.toggle_zoom_fit()
        self.win._zoom_by(1.5)
        self.assertIsNone(self.win._zoom_before_fit)

    def test_split_booklet_action(self):
        """Two 2-up sheets unimpose into four pages."""
        wide = Dims(1224, 792)
        for page in self.win.model.pages[:2]:
            page.size_orig = wide
            page.size = wide
        self.win.view.set_selected_rows([0, 1])
        self.win.split_booklet()
        self.assertEqual(len(self.win.model.pages), 6)  # 2 sheets -> 4, plus 2 untouched

    def test_export_multiple_writes_one_file_per_page(self):
        import tempfile

        target = tempfile.mkdtemp()
        pages = self.win.model.pages
        files = [os.path.join(target, f"p-{i + 1}.pdf") for i in range(len(pages))]
        self.assertTrue(self.win._write(files, pages, mark_saved=False))
        for path in files:
            with pikepdf.open(path) as pdf:
                self.assertEqual(len(pdf.pages), 1)

class TestPhase2WindowActions(unittest.TestCase):
    """Window handlers, with the modal dialogs stubbed out."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def stub(self, name, value):
        """Replace a dialog class with one whose get_value() returns ``value``."""
        from pdfarranger_qt import dialogs

        class Stub:
            MODE_SCALE = dialogs.ScaleDialog.MODE_SCALE
            MODE_SCALE_MARGINS = dialogs.ScaleDialog.MODE_SCALE_MARGINS
            MODE_CROP_MARGINS = dialogs.ScaleDialog.MODE_CROP_MARGINS

            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return value

        original = getattr(dialogs, name)
        setattr(dialogs, name, Stub)
        self.addCleanup(setattr, dialogs, name, original)

    def test_insert_blank_page(self):
        self.stub("BlankPageDialog", Dims(612, 792))
        before = self.win.model.rowCount()
        self.win.view.set_selected_rows([0])
        self.win.insert_blank_page()
        self.assertEqual(self.win.model.rowCount(), before + 1)
        self.assertEqual(self.win.act_undo.text(), "&Undo Insert Blank Page")

    def test_crop_action_is_undoable(self):
        self.stub("CropHideDialog", Sides(0.1, 0.1, 0, 0))
        self.win.view.set_selected_rows([0])
        self.win.edit_margins(hide=False)
        self.assertEqual(self.win.model.pages[0].crop, Sides(0.1, 0.1, 0, 0))
        self.win.undo()
        self.assertEqual(self.win.model.pages[0].crop, Sides())

    def test_page_size_relative(self):
        from pdfarranger_qt.dialogs import ScaleDialog

        self.stub("ScaleDialog", (0.5, ScaleDialog.MODE_SCALE))
        self.win.view.set_selected_rows([0])
        self.win.page_size()
        self.assertAlmostEqual(self.win.model.pages[0].scale, 0.5, places=6)

    def test_page_size_crop_and_add_margins_wraps_on_a_blank_sheet(self):
        from pdfarranger_qt.dialogs import ScaleDialog

        bigger = Dims(842, 1191)
        self.stub("ScaleDialog", (bigger, ScaleDialog.MODE_CROP_MARGINS))
        self.win.view.set_selected_rows([0])
        self.win.page_size()
        page = self.win.model.pages[0]
        self.assertEqual(page.size_in_points(), bigger)
        self.assertEqual(len(page.layerpages), 1, "original should ride as a layer")

    def test_split_pages_action(self):
        self.stub("SplitDialog", (2, 1))
        before = self.win.model.rowCount()
        self.win.view.set_selected_rows([0])
        self.win.split_pages()
        self.assertEqual(self.win.model.rowCount(), before + 1)

    def test_select_range_action(self):
        self.stub("RangeSelectDialog", [1])
        self.win.select_range()
        self.assertEqual(self.win.view.selected_rows(), [1])

    def test_merge_pages_composites_the_clipboard(self):
        from pdfarranger_qt import clipboard

        self.stub("MergeDialog", ("OVERLAY", (0.5, 0.5), 1.0))
        QApplication.clipboard().setText(
            clipboard.serialize(self.win.model.pages[1:2]))
        self.win.view.set_selected_rows([0])
        self.win.merge_pages()
        self.assertEqual(len(self.win.model.pages[0].layerpages), 1)
        self.assertTrue(self.win.modified)

    def test_generate_booklet_action(self):
        self.win.view.selectAll()
        self.win.duplicate_selected()  # 4 pages
        self.win.view.selectAll()
        self.win.generate_booklet()
        self.assertEqual(self.win.model.rowCount(), 2)
        for page in self.win.model.pages:
            self.assertEqual(len(page.layerpages), 2)

    def test_generate_booklet_refuses_mixed_sizes(self):
        self.win.model.set_scale([1], 2.0)
        self.win.view.selectAll()
        before = self.win.model.rowCount()
        MESSAGE_BOXES.clear()
        self.win.generate_booklet()
        self.assertEqual(self.win.model.rowCount(), before)
        self.assertTrue(MESSAGE_BOXES, "the user should be told why nothing happened")
        self.assertEqual(MESSAGE_BOXES[-1][0], "warning")

    def test_properties_round_trip_to_the_saved_file(self):
        import tempfile

        from pdfarranger_qt import metadata

        title_key = "{http://purl.org/dc/elements/1.1/}title"
        self.stub("PropertiesDialog", {title_key: "A Test Title"})
        self.win.edit_properties()
        self.assertEqual(self.win.metadata[title_key], "A Test Title")
        self.assertTrue(self.win.modified)

        path = os.path.join(tempfile.mkdtemp(), "titled.pdf")
        self.win.current_path = path
        self.assertTrue(self.win.save())
        with pikepdf.open(path) as pdf:
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                self.assertEqual(meta[title_key], "A Test Title")

    def test_properties_dialog_keeps_unknown_keys(self):
        from pdfarranger_qt.dialogs import PropertiesDialog

        exotic = {"{http://example.com/}custom": "keep me"}
        d = PropertiesDialog(dict(exotic))
        self.assertEqual(d.value(), exotic)

    def test_properties_dialog_prefills_and_drops_blanks(self):
        from pdfarranger_qt.dialogs import PropertiesDialog

        title_key = "{http://purl.org/dc/elements/1.1/}title"
        d = PropertiesDialog({title_key: "Hello"})
        self.assertEqual(d.fields[title_key].text(), "Hello")
        d.fields[title_key].setText("")
        self.assertNotIn(title_key, d.value())

    def test_closing_the_document_clears_properties(self):
        self.win.metadata = {"x": "y"}
        self.win.modified = False
        self.win.close_document()
        self.assertEqual(self.win.metadata, {})

    def test_merge_without_a_clipboard_explains_itself(self):
        QApplication.clipboard().setText("")
        MESSAGE_BOXES.clear()
        self.win.view.set_selected_rows([0])
        self.win.merge_pages()
        self.assertEqual(MESSAGE_BOXES[-1][0], "information")
        self.assertEqual(len(self.win.model.pages[0].layerpages), 0)


TEXT_PDF = os.path.join(HERE, "test_raster_image_text.pdf")

def dialogs_defaults():
    from pdfarranger_qt import dialogs

    return dict(dialogs.PREFERENCES)

class TestPhase3WindowActions(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def test_crop_white_borders_action(self):
        self.win.view.set_selected_rows([0])
        self.win.crop_white_borders()
        self.assertGreater(sum(self.win.model.pages[0].crop), 0)
        self.assertTrue(self.win.modified)
        self.assertEqual(self.win.act_undo.text(), "&Undo Crop White Borders")

    def test_crop_white_borders_is_undoable(self):
        self.win.view.set_selected_rows([0])
        self.win.crop_white_borders()
        self.win.undo()
        self.assertEqual(self.win.model.pages[0].crop, Sides())

    def test_copy_text_reports_an_empty_page(self):
        MESSAGE_BOXES.clear()
        self.win.view.set_selected_rows([0])
        self.win.copy_page_text()
        self.assertEqual(MESSAGE_BOXES[-1][0], "information")

    def test_copy_text_puts_text_on_the_clipboard(self):
        self.win.open_paths([TEXT_PDF])
        settle(timeout_ms=300)
        self.win.view.set_selected_rows([0])
        self.win.copy_page_text()
        self.assertIn("tests", QApplication.clipboard().text())

    def test_search_index_is_invalidated_by_an_edit(self):
        self.win.open_paths([TEXT_PDF])
        settle(timeout_ms=300)
        self.win._run_search("tests")
        self.assertEqual(self.win.search.matches, [0])
        self.win.view.set_selected_rows([0])
        self.win.rotate(90)
        self.assertEqual(self.win.search.matches, [],
                         "editing must drop the stale index")

    def test_find_step_selects_the_matching_page(self):
        self.win.open_paths([TEXT_PDF])
        settle(timeout_ms=300)
        self.win._run_search("tests")
        self.win.find_step(forward=True)
        self.assertEqual(self.win.view.selected_rows(), [0])

    def test_find_all_selects_every_match(self):
        self.win.open_paths([TEXT_PDF])
        settle(timeout_ms=300)
        self.win._run_search("tests")
        self.win.find_all()
        self.assertEqual(self.win.view.selected_rows(), [0])

    def test_copy_image_reports_a_page_without_one(self):
        MESSAGE_BOXES.clear()
        self.win.view.set_selected_rows([0])
        self.win.copy_page_image()
        self.assertEqual(MESSAGE_BOXES[-1][0], "information")

    def test_explode_replaces_a_scanned_page_with_its_image(self):
        import tempfile

        from pdfarranger_qt import raster

        scan = os.path.join(tempfile.mkdtemp(), "scan.pdf")
        raster.export_rasterised_pdf(self.win.model.pages[:1],
                                     self.win.docs.files_for_export(), scan, ppi=72)
        self.win.open_paths([scan])
        settle(timeout_ms=300)
        before = self.win.model.rowCount()
        self.win.view.set_selected_rows([0])
        self.win.explode_into_images()
        self.assertEqual(self.win.model.rowCount(), before)
        self.assertEqual(self.win.act_undo.text(), "&Undo Explode into Images")

    def test_explode_reports_a_page_with_no_images(self):
        MESSAGE_BOXES.clear()
        self.win.view.set_selected_rows([0])
        self.win.explode_into_images()
        self.assertEqual(MESSAGE_BOXES[-1][0], "information")

    def test_preferences_round_trip_through_settings(self):
        self.stub_preferences({
            "language": "de", "theme": "dark", "print/scale-mode": "actual",
            "print/auto-rotate": False, "export/preserve-first-document": True,
            "image/ppi": 150, "image/greyscale": True, "shortcuts": {},
        })
        self.win.edit_preferences()
        self.assertEqual(self.win._preference("image/ppi"), 150)
        self.assertIs(self.win._preference("image/greyscale"), True)
        self.assertIs(self.win._preference("print/auto-rotate"), False)
        self.assertEqual(self.win._preference("theme"), "dark")

    def test_preferences_can_rebind_a_shortcut(self):
        name = self.win.act_duplicate.objectName() or self.win.act_duplicate.text()
        self.stub_preferences({**dialogs_defaults(), "shortcuts": {name: "Ctrl+Shift+K"}})
        self.win.edit_preferences()
        self.assertEqual(self.win.act_duplicate.shortcut().toString(), "Ctrl+Shift+K")

    def stub_preferences(self, value):
        from pdfarranger_qt import dialogs

        class Stub:
            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return value

        original = dialogs.PreferencesDialog
        dialogs.PreferencesDialog = Stub
        self.addCleanup(setattr, dialogs, "PreferencesDialog", original)


class TestHelpMenu(unittest.TestCase):
    """The Help menu's outward links."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def help_menu(self):
        for action in self.win.menuBar().actions():
            if "Help" in action.text():
                return action.menu()
        self.fail("no Help menu")

    def test_help_menu_offers_the_project_page(self):
        labels = [a.text() for a in self.help_menu().actions() if not a.isSeparator()]
        self.assertIn("Project on GitHub", labels)
        self.assertIn("User Guide", labels)

    def test_project_action_opens_the_repository(self):
        """Patched rather than really opened: this must not launch a browser."""
        from PySide6.QtGui import QDesktopServices

        from pdfarranger_qt import PROJECT_URL, mainwindow

        opened = []
        original = mainwindow.QDesktopServices.openUrl
        mainwindow.QDesktopServices.openUrl = lambda url: opened.append(url.toString())
        self.addCleanup(setattr, mainwindow.QDesktopServices, "openUrl", original)
        self.assertIs(mainwindow.QDesktopServices, QDesktopServices)

        self.win.act_project.trigger()
        self.assertEqual(opened, [PROJECT_URL])

    def test_about_names_the_project_url(self):
        from pdfarranger_qt import PROJECT_URL, UPSTREAM_URL

        MESSAGE_BOXES.clear()
        self.win.act_about.trigger()
        self.assertEqual(len(MESSAGE_BOXES), 1, "About did not show a box")
        kind, title, text = MESSAGE_BOXES[0]
        self.assertEqual(kind, "about")
        self.assertIn(PROJECT_URL, text)
        # Upstream stays credited; this is a derivative work.
        self.assertIn(UPSTREAM_URL, text)
