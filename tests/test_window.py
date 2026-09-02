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

from support import HERE, MESSAGE_BOXES, TEST_PDF, TEXT_PDF, settle, temp_path


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

        # These exercise the grid, and a window now opens into the reader.
        self.win.set_read_mode(False)
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

    def test_zoom_fit_shows_a_whole_page(self):
        """Both dimensions. Fitting the width alone never shows a whole page."""
        self.win.view.set_selected_rows([0])
        self.win.zoom_fit()
        page = self.win.model.pages[0]
        width, height = self.win.model.thumb_size(page)
        viewport = self.win.view.viewport()
        self.assertLessEqual(width, viewport.width())
        self.assertLessEqual(height, viewport.height())
        # And it fills one of the two, rather than being merely small enough.
        self.assertTrue(width > viewport.width() * 0.7
                        or height > viewport.height() * 0.7,
                        f"{width}x{height} in {viewport.width()}x{viewport.height()}")

    def test_fit_width_fills_the_window_across(self):
        self.win.view.set_selected_rows([0])
        self.win.zoom_fit_width()
        page = self.win.model.pages[0]
        width = self.win.model.thumb_size(page)[0]
        viewport = self.win.view.viewport()
        self.assertLessEqual(width, viewport.width())
        self.assertGreater(width, viewport.width() * 0.7)

    def test_fit_width_is_wider_than_fit_page(self):
        """The distinction is the whole point of having both."""
        self.win.view.set_selected_rows([0])
        self.win.zoom_fit()
        fit_page = self.win.model.zoom
        self.win.zoom_fit_width()
        self.assertGreater(self.win.model.zoom, fit_page)

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

    def help_menu_labels(self):
        """Read the entries inside the loop and return plain strings.

        Returning ``action.menu()`` does not work: PySide ties the QMenu's
        lifetime to the QAction wrapper it came from, so the menu is already
        destroyed by the time the caller touches it -- "Internal C++ object
        (QMenu) already deleted".
        """
        for action in self.win.menuBar().actions():
            if "Help" in action.text():
                return [a.text() for a in action.menu().actions()
                        if not a.isSeparator()]
        self.fail("no Help menu")

    def test_help_menu_offers_the_project_page(self):
        labels = self.help_menu_labels()
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


class TestMenuLifetime(unittest.TestCase):
    """Menus must outlive anything that merely looks at them.

    PySide hands Python ownership of the QMenu returned by
    QMenu.addMenu(title) and by QAction.menu(). Walking the menu bar - which
    the shortcut editor does - therefore used to take a temporary reference to
    every submenu and destroy it on the next garbage collection, so the next
    File > Open Recent raised "Internal C++ object (QMenu) already deleted"
    from _rebuild_recent_menu. Intermittent, because it depended on when the
    collector ran.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def alive(self, menu):
        import shiboken6

        return shiboken6.isValid(menu)

    def test_submenus_survive_walking_the_menu_bar(self):
        import gc

        groups = self.win._shortcut_groups()
        del groups
        gc.collect()
        self.assertTrue(self.alive(self.win.recent_menu),
                        "the shortcut editor destroyed the Open Recent menu")

    def test_recent_menu_still_rebuilds_afterwards(self):
        """The exact failure that was reported: aboutToShow after a walk."""
        import gc

        self.win._shortcut_groups()
        gc.collect()
        self.win.recent_menu.aboutToShow.emit()  # raised RuntimeError
        labels = [a.text() for a in self.win.recent_menu.actions()
                  if not a.isSeparator()]
        self.assertTrue(labels)

    def test_every_menu_survives(self):
        import gc

        menus = list(self.win._menus)
        self.win._shortcut_groups()
        gc.collect()
        dead = [i for i, menu in enumerate(menus) if not self.alive(menu)]
        self.assertEqual(dead, [], f"{len(dead)} of {len(menus)} menus destroyed")

    def test_menus_are_parented_to_the_window(self):
        """An explicit parent is what keeps ownership in C++."""
        for menu in self.win._menus:
            self.assertIs(menu.parent(), self.win, menu.title())

class TestPhase4Parity(unittest.TestCase):
    """The upstream features that were missing until phase 4."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 700)
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=300)

        # These exercise the grid, and a window now opens into the reader.
        self.win.set_read_mode(False)
    def tearDown(self):
        self.win.modified = False
        self.win.close()

    # -- New Window ----------------------------------------------------------

    def test_new_window_launches_a_separate_process(self):
        """A second process, not a second MainWindow.

        The app is NON_UNIQUE by design: cross-instance drag depends on the two
        windows genuinely being different processes.
        """
        from PySide6.QtCore import QProcess
        from pdfarranger_qt import mainwindow

        calls = []
        original = mainwindow.QProcess.startDetached
        mainwindow.QProcess.startDetached = (
            lambda program, args, cwd: calls.append((program, args)) or (True, 1))
        self.addCleanup(setattr, mainwindow.QProcess, "startDetached", original)
        self.assertIs(mainwindow.QProcess, QProcess)

        self.win.new_window()
        self.assertEqual(len(calls), 1)
        program, args = calls[0]
        self.assertTrue(program)
        # From source, re-run the package; frozen, the exe takes no arguments.
        self.assertIn(args, ([], ["-m", "pdfarranger_qt"]))

    def test_new_window_reports_a_failed_launch(self):
        from pdfarranger_qt import mainwindow

        original = mainwindow.QProcess.startDetached
        mainwindow.QProcess.startDetached = lambda *a: (False, 0)
        self.addCleanup(setattr, mainwindow.QProcess, "startDetached", original)
        MESSAGE_BOXES.clear()
        self.win.new_window()
        self.assertEqual(MESSAGE_BOXES[-1][0], "warning")

    # -- Password ------------------------------------------------------------

    def test_password_round_trips_through_the_saved_file(self):
        """The whole point: the file must actually be encrypted."""
        import pikepdf

        from pdfarranger_qt import dialogs

        class Stub:
            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return "s3cret"

        original = dialogs.EncryptionPasswordDialog
        dialogs.EncryptionPasswordDialog = Stub
        self.addCleanup(setattr, dialogs, "EncryptionPasswordDialog", original)

        self.win.act_password.setChecked(True)
        self.win.set_password(True)
        self.assertEqual(self.win.output_password, "s3cret")

        out = temp_path("encrypted.pdf")
        self.assertTrue(self.win._write([out], self.win.model.pages))
        with self.assertRaises(pikepdf.PasswordError):
            pikepdf.open(out)
        with pikepdf.open(out, password="s3cret") as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_cancelling_the_password_dialog_leaves_it_off(self):
        """Checked-but-empty would look encrypted and not be."""
        from pdfarranger_qt import dialogs

        class Stub:
            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return None

        original = dialogs.EncryptionPasswordDialog
        dialogs.EncryptionPasswordDialog = Stub
        self.addCleanup(setattr, dialogs, "EncryptionPasswordDialog", original)

        self.win.act_password.setChecked(True)
        self.win.set_password(True)
        self.assertIsNone(self.win.output_password)
        self.assertFalse(self.win.act_password.isChecked())

    def test_unchecking_clears_the_password(self):
        self.win.output_password = "s3cret"
        self.win.set_password(False)
        self.assertIsNone(self.win.output_password)

    def test_an_unencrypted_save_is_still_unencrypted(self):
        import pikepdf

        out = temp_path("plain.pdf")
        self.assertTrue(self.win._write([out], self.win.model.pages))
        with pikepdf.open(out) as pdf:      # no password required
            self.assertEqual(len(pdf.pages), 2)

    # -- Rasterised PDF (jpg) ------------------------------------------------

    def test_rasterised_pdf_offers_both_formats(self):
        labels = [a.text().replace("&", "") for a in self.win._shortcut_actions()]
        self.assertIn("Export Selection to Rasterized PDF (png)…", labels)
        self.assertIn("Export Selection to Rasterized PDF (jpg)…", labels)

    def test_rasterised_jpg_writes_a_pdf(self):
        from pdfarranger_qt import raster

        out = temp_path("raster.pdf")
        ok = raster.export_rasterised_pdf(
            self.win.model.pages, self.win.docs.files_for_export(), out,
            ppi=36, greyscale=False, image_format="jpg")
        if not ok:
            self.skipTest("img2pdf not available")
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(5), b"%PDF-")

    # -- Fit One Page / Fit Multiple Pages -----------------------------------

    def test_fit_one_page_pins_a_single_column(self):
        """Upstream's Fit One Page is the fit zoom plus col_num = 1."""
        self.win.zoom_fit()
        self.assertTrue(self.win.view._single_column)

    def test_fit_multiple_pages_lets_the_grid_flow(self):
        self.win.zoom_fit()
        self.win.zoom_fit_multiple()
        self.assertFalse(self.win.view._single_column)

    def test_both_fits_use_the_same_zoom(self):
        """They differ in column count, not scale."""
        self.win.zoom_fit()
        one = self.win.model.zoom
        self.win.zoom_fit_multiple()
        self.assertAlmostEqual(self.win.model.zoom, one, places=6)

    def test_fit_width_releases_the_pinning(self):
        self.win.zoom_fit()
        self.win.zoom_fit_width()
        self.assertFalse(self.win.view._single_column)

    def test_single_column_puts_pages_on_separate_rows(self):
        """The observable effect, not just the flag."""
        self.win.zoom_fit_multiple()
        self.win.model.set_zoom(0.05)     # tiny, so several would fit across
        settle(timeout_ms=200)
        self.win.view.set_single_column(True)
        settle(timeout_ms=200)
        view = self.win.view
        first = view.visualRect(view.page_model.index(0, 0))
        second = view.visualRect(view.page_model.index(1, 0))
        self.assertEqual(first.left(), second.left())
        self.assertGreater(second.top(), first.top())


class TestWindowTitle(unittest.TestCase):
    """The title follows each platform's convention, not one of them everywhere.

    It used to be "*name - PDF Arranger Qt" on all three. On macOS the
    application's name is in the menu bar, so repeating it in every window is a
    Windows convention applied in the wrong place -- Acrobat shows the document
    and nothing else. The modified marker was a hand-rolled leading asterisk,
    which is the Windows signal drawn on every platform.
    """

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.addCleanup(self.win.close)
        self.addCleanup(setattr, self.win, "modified", False)
        self.win.show()

    # -- the convention, checked from any platform -------------------------

    def test_a_document_only_title(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.assertEqual(MainWindow.title_for("book.pdf", True), "book.pdf[*]")

    def test_a_title_that_names_the_application(self):
        from pdfarranger_qt.mainwindow import APP_NAME, MainWindow

        self.assertEqual(MainWindow.title_for("book.pdf", False),
                         f"book.pdf[*] - {APP_NAME}")

    def test_macos_gets_the_document_only_form(self):
        import sys

        from pdfarranger_qt.mainwindow import MainWindow

        self.assertEqual(MainWindow.DOCUMENT_ONLY_TITLE,
                         sys.platform == "darwin")

    def test_the_marker_is_qts_placeholder_not_a_star(self):
        """`[*]` becomes the close-button dot on macOS and a star elsewhere."""
        from pdfarranger_qt.mainwindow import MainWindow

        for document_only in (True, False):
            title = MainWindow.title_for("book.pdf", document_only)
            self.assertIn("[*]", title)
            self.assertFalse(title.startswith("*"))

    # -- what the window actually does -------------------------------------

    def test_an_empty_window_is_untitled(self):
        self.assertIn("Untitled", self.win.windowTitle())

    def test_opening_names_the_document(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win.modified = False
        self.assertIn(os.path.basename(TEST_PDF), self.win.windowTitle())

    def test_editing_sets_the_modified_state(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win.modified = False
        self.win._refresh_state()
        self.assertFalse(self.win.isWindowModified())
        self.win._mark_modified()
        self.assertTrue(self.win.isWindowModified())

    def test_the_document_path_is_offered_for_the_proxy_icon(self):
        """macOS puts a draggable document icon in the title bar from this."""
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win.modified = False
        self.assertEqual(self.win.windowFilePath(), TEST_PDF)

    def test_closing_the_document_takes_the_path_away(self):
        self.win.open_paths([TEST_PDF])
        settle(timeout_ms=300)
        self.win.modified = False
        self.win.close_document()
        settle(timeout_ms=200)
        self.assertEqual(self.win.windowFilePath(), "")
        self.assertIn("Untitled", self.win.windowTitle())
