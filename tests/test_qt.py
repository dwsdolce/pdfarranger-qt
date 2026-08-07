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

"""Tests for the PySide6 port.

Run with ``python -m pytest tests/test_qt.py``. They drive a real (offscreen)
QApplication, so they exercise the render thread and the item model rather than
mocking them -- the interesting bugs in this layer are all timing and
Qt-semantics bugs that a mock would hide.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pikepdf
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pdfarranger_qt.core import Dims, DocumentSet, Page, Sides
from pdfarranger_qt.export import export
from pdfarranger_qt.model import PageListModel, contiguous_blocks
from pdfarranger_qt.render import Renderer, ThumbnailCache

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_PDF = os.path.join(HERE, "test.pdf")

_app = QApplication.instance() or QApplication(sys.argv[:1])

# A modal QMessageBox blocks forever under the offscreen platform, so a single
# unexpected warning hangs the whole run rather than failing a test. Replace the
# static helpers with recorders; tests can assert on what would have been shown.
MESSAGE_BOXES = []


def _record_message_box(kind, default):
    def handler(_parent, title, text, *args, **kwargs):
        MESSAGE_BOXES.append((kind, title, text))
        return default

    return handler


def _install_message_box_recorders():
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.warning = _record_message_box("warning", QMessageBox.Ok)
    QMessageBox.information = _record_message_box("information", QMessageBox.Ok)
    QMessageBox.critical = _record_message_box("critical", QMessageBox.Ok)
    # Discard keeps _confirm_discard() from trying to save during teardown.
    QMessageBox.question = _record_message_box("question", QMessageBox.Discard)
    QMessageBox.about = _record_message_box("about", None)


_install_message_box_recorders()


def settle(condition=None, timeout_ms=8000, step_ms=50):
    """Spin the event loop until ``condition`` holds or the timeout expires."""
    elapsed = 0
    while elapsed < timeout_ms:
        if condition is not None and condition():
            return True
        loop = QEventLoop()
        QTimer.singleShot(step_ms, loop.quit)
        loop.exec()
        elapsed += step_ms
    return condition is None or condition()


def load_tests(loader, tests, ignore):
    """Run core's doctests as part of the suite.

    The Sides/Dims arithmetic came across from upstream verbatim, doctests and
    all; this is what carries the coverage that `tests/test_core.py` used to
    provide before it was retired.
    """
    import doctest

    from pdfarranger_qt import core, i18n

    tests.addTests(doctest.DocTestSuite(core))
    tests.addTests(doctest.DocTestSuite(i18n))
    return tests


class TestGeometry(unittest.TestCase):
    def test_sides_rotated_is_cyclic(self):
        s = Sides(9, 3, 12, 6)
        self.assertEqual(s.rotated(4), s)
        self.assertEqual(s.rotated(-3), s.rotated(1))

    def test_page_rotate_swaps_size(self):
        page = Page(1, 1, "x.pdf", size_orig=Dims(612, 792))
        self.assertTrue(page.rotate(90))
        self.assertEqual(page.size, Dims(792, 612))
        self.assertEqual(page.angle, 90)
        self.assertFalse(page.rotate(0))
        page.rotate(270)
        self.assertEqual(page.angle, 0)
        self.assertEqual(page.size, Dims(612, 792))

    def test_render_key_tracks_every_visible_property(self):
        page = Page(1, 1, "x.pdf", size_orig=Dims(612, 792))
        before = page.render_key(100)
        page.rotate(90)
        self.assertNotEqual(before, page.render_key(100))
        self.assertNotEqual(page.render_key(100), page.render_key(200))

    def test_contiguous_blocks(self):
        self.assertEqual(contiguous_blocks([1, 2, 3, 7, 8]), [(1, 3), (7, 8)])
        self.assertEqual(contiguous_blocks([]), [])
        self.assertEqual(contiguous_blocks([5]), [(5, 5)])


class TestCache(unittest.TestCase):
    def test_evicts_by_pixel_budget(self):
        from PySide6.QtGui import QImage

        cache = ThumbnailCache(max_pixels=100 * 100 * 2)
        for i in range(5):
            cache.put(i, QImage(100, 100, QImage.Format_ARGB32))
        self.assertLessEqual(len(cache), 2)
        self.assertIsNotNone(cache.get(4))  # most recent survives
        self.assertIsNone(cache.get(0))


class QtDocumentTestCase(unittest.TestCase):
    def setUp(self):
        self.docs = DocumentSet()
        self.renderer = Renderer()
        self.model = PageListModel(self.renderer)
        self.model.doc_password = lambda page: self.docs.docs[page.nfile - 1].password
        self.model.set_pages(self.docs.add_file(TEST_PDF))

    def tearDown(self):
        self.renderer.shutdown()
        self.docs.cleanup()

    def render_all(self):
        self.model.ensure_rendered(0, self.model.rowCount() - 1)
        settle(lambda: all(
            self.model.data(self.model.index(r, 0), self.model.ImageRole) is not None
            for r in range(self.model.rowCount())
        ))
        return [self.model.data(self.model.index(r, 0), self.model.ImageRole)
                for r in range(self.model.rowCount())]


class TestLoading(QtDocumentTestCase):
    def test_loads_pages_with_sizes(self):
        self.assertEqual(self.model.rowCount(), 2)
        self.assertEqual(self.model.pages[0].size_orig, Dims(612.0, 792.0))

    def test_source_file_is_copied_not_referenced(self):
        doc = self.docs.docs[0]
        self.assertNotEqual(doc.copyname, doc.filename)
        self.assertTrue(os.path.isfile(doc.copyname))

    def test_reloading_the_same_file_reuses_the_document(self):
        self.docs.add_file(TEST_PDF)
        self.assertEqual(len(self.docs.docs), 1)


class TestRendering(QtDocumentTestCase):
    @staticmethod
    def ink_profile(image):
        """Return (widest row, tallest column) as fractions of the image.

        test.pdf is a triangle standing on its base, so this says which way the
        content is facing without needing a pixel-exact reference image.
        """
        w, h = image.width(), image.height()

        def ink(x, y):
            c = image.pixelColor(x, y)
            return (c.alpha() > 128 and max(c.red(), c.green()) > 140
                    and min(c.red(), c.green()) < 120)

        rows = [sum(1 for x in range(w) if ink(x, y)) for y in range(h)]
        cols = [sum(1 for y in range(h) if ink(x, y)) for x in range(w)]
        assert max(rows) > 0, "no ink found in rendered page"
        return rows.index(max(rows)) / (h - 1), cols.index(max(cols)) / (w - 1)

    def test_renders_every_page(self):
        images = self.render_all()
        self.assertTrue(all(img is not None and not img.isNull() for img in images))
        self.assertAlmostEqual(images[0].width() / images[0].height(), 612 / 792, delta=0.02)

    def test_rotation_reaches_the_pixels(self):
        """Regression: setScaledClipRect made QtPdf drop the rotation."""
        upright = self.ink_profile(self.render_all()[0])
        self.assertGreater(upright[0], 0.6, "base should be near the bottom")

        self.model.rotate([0], 90)
        rotated_img = self.render_all()[0]
        self.assertGreater(rotated_img.width(), rotated_img.height())
        sideways = self.ink_profile(rotated_img)
        self.assertLess(sideways[1], 0.4, "base should have moved to the left")

    def test_crop_shrinks_the_result(self):
        full = self.render_all()[0]
        self.model.pages[0].crop = Sides(0.25, 0.25, 0, 0)
        cropped = self.render_all()[0]
        # Same requested width, so cropping shows less page at higher detail:
        # the aspect ratio must get taller.
        self.assertGreater(cropped.height() / cropped.width(), full.height() / full.width())


class TestUndo(QtDocumentTestCase):
    def test_undo_redo_round_trip(self):
        original = [p.npage for p in self.model.pages]
        self.model.undo.commit("Delete")
        self.model.remove_rows([0])
        self.assertEqual(self.model.rowCount(), 1)

        self.model.undo.undo()
        self.assertEqual([p.npage for p in self.model.pages], original)
        self.model.undo.redo()
        self.assertEqual(self.model.rowCount(), 1)

    def test_labels_name_the_action(self):
        self.model.undo.commit("Rotate")
        self.model.rotate([0], 90)
        self.assertEqual(self.model.undo.undo_label(), "Rotate")
        self.model.undo.undo()
        self.assertEqual(self.model.undo.redo_label(), "Rotate")

    def test_undo_restores_rotation(self):
        self.model.undo.commit("Rotate")
        self.model.rotate([0], 90)
        self.model.undo.undo()
        self.assertEqual(self.model.pages[0].angle, 0)
        self.model.undo.redo()
        self.assertEqual(self.model.pages[0].angle, 90)

    def test_commit_truncates_the_redo_branch(self):
        self.model.undo.commit("A")
        self.model.remove_rows([0])
        self.model.undo.undo()
        self.assertTrue(self.model.undo.can_redo)
        self.model.undo.commit("B")
        self.model.remove_rows([0])
        self.assertFalse(self.model.undo.can_redo)


class TestReorder(QtDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.model.set_pages(self.docs.add_file(TEST_PDF) * 1)
        # Give ourselves four distinguishable pages.
        self.model.duplicate([0, 1])
        for i, page in enumerate(self.model.pages):
            page.description = str(i)

    def order(self):
        return [p.description for p in self.model.pages]

    def test_move_forward(self):
        self.model.move_rows([0], 3)
        self.assertEqual(self.order(), ["1", "2", "0", "3"])

    def test_move_backward(self):
        self.model.move_rows([3], 1)
        self.assertEqual(self.order(), ["0", "3", "1", "2"])

    def test_move_block_keeps_relative_order(self):
        self.model.move_rows([0, 2], 4)
        self.assertEqual(self.order(), ["1", "3", "0", "2"])

    def test_move_to_end(self):
        self.model.move_rows([0], 4)
        self.assertEqual(self.order(), ["1", "2", "3", "0"])


class TestDragReorder(unittest.TestCase):
    """Drives the grid with real mouse events.

    Reordering is implemented in PageView rather than via Qt's item-view drag
    and drop, so it is only meaningfully covered by pushing mouse events at the
    viewport and reading back the page order.
    """

    def setUp(self):
        from PySide6.QtCore import QPointF
        from pdfarranger_qt.mainwindow import MainWindow

        self.QPointF = QPointF
        self.win = MainWindow()
        # Pin the layout: the window otherwise restores the user's saved zoom
        # and geometry, which would move the cells this test aims at.
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.view.selectAll()
        self.win.duplicate_selected()
        for i, page in enumerate(self.win.model.pages):
            page.description = str(i)
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def order(self):
        return [p.description for p in self.win.model.pages]

    def rect(self, row):
        return self.win.view.visualRect(self.win.model.index(row, 0))

    def drag(self, start, end, steps=6, ctrl=False):
        """Press at start, move to end in increments, release.

        ``ctrl`` is applied to the moves and the release only -- ctrl on the
        *press* would toggle the item's selection, which is why the real code
        samples the modifier at the drop.
        """
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QMouseEvent

        vp = self.win.view.viewport()
        held = Qt.ControlModifier if ctrl else Qt.NoModifier

        def send(kind, pos, button, buttons, modifiers=Qt.NoModifier):
            _app.sendEvent(vp, QMouseEvent(kind, pos, pos, button, buttons, modifiers))

        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        for i in range(1, steps + 1):
            send(QEvent.MouseMove, start + (end - start) * i / steps,
                 Qt.NoButton, Qt.LeftButton, held)
        send(QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton, held)

    def drag_row(self, row, target_row, after=False):
        start = self.QPointF(self.rect(row).center())
        target = self.rect(target_row)
        end = (self.QPointF(target.center()) + self.QPointF(target.width(), 0) if after
               else self.QPointF(target.left() + 4, target.center().y()))
        self.win.view.set_selected_rows(sorted(set(self.win.view.selected_rows()) | {row}))
        self.drag(start, end)

    def test_drag_to_end(self):
        self.win.view.set_selected_rows([0])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.order(), ["1", "2", "3", "0"])
        self.assertTrue(self.win.modified)

    def test_drag_backwards(self):
        self.win.view.set_selected_rows([3])
        self.drag_row(3, 1)
        self.assertEqual(self.order(), ["0", "3", "1", "2"])

    def test_drag_is_undoable(self):
        self.win.view.set_selected_rows([0])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.win.act_undo.text(), "&Undo Move")
        self.win.undo()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_multi_select_drag_keeps_relative_order(self):
        self.win.view.set_selected_rows([0, 2])
        self.drag_row(0, 3, after=True)
        self.assertEqual(self.order(), ["1", "3", "0", "2"])

    def test_drop_in_place_is_not_undoable(self):
        before = len(self.win.model.undo.states)
        self.win.view.set_selected_rows([1])
        self.drag_row(1, 1)
        self.assertEqual(self.order(), ["0", "1", "2", "3"])
        self.assertEqual(len(self.win.model.undo.states), before)

    def test_dragging_an_unselected_page_drags_only_it(self):
        self.win.view.set_selected_rows([2])
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0))
        self.assertEqual(self.order(), ["1", "2", "3", "0"])

    def test_ctrl_drag_duplicates_instead_of_moving(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.assertEqual(len(self.win.model.pages), 5, "ctrl+drag should copy")
        self.assertEqual(self.order(), ["0", "1", "2", "3", "0"])
        self.assertEqual(self.win.act_undo.text(), "&Undo Copy")

    def test_ctrl_drag_in_place_still_duplicates(self):
        """A plain move onto itself is a no-op; a ctrl-drop is still a copy."""
        before = len(self.win.model.pages)
        rect = self.rect(1)
        self.win.view.set_selected_rows([1])
        self.drag(self.QPointF(rect.center()),
                  self.QPointF(rect.left() + 4, rect.center().y()), ctrl=True)
        self.assertEqual(len(self.win.model.pages), before + 1)

    def test_ctrl_drag_of_a_multi_selection_copies_all(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0, 2])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.assertEqual(self.order(), ["0", "1", "2", "3", "0", "2"])

    def test_ctrl_drag_is_undoable(self):
        start = self.QPointF(self.rect(0).center())
        target = self.rect(3)
        self.win.view.set_selected_rows([0])
        self.drag(start, self.QPointF(target.center()) + self.QPointF(target.width(), 0),
                  ctrl=True)
        self.win.undo()
        self.assertEqual(self.order(), ["0", "1", "2", "3"])

    def test_short_press_does_not_reorder(self):
        """A click must not be mistaken for a drag."""
        start = self.QPointF(self.rect(0).center())
        self.drag(start, start + self.QPointF(2, 0), steps=1)
        self.assertEqual(self.order(), ["0", "1", "2", "3"])


class TestLayout(unittest.TestCase):
    """Cell geometry has to follow the pages when a page changes shape."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.view.selectAll()
        self.win.duplicate_selected()
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def overlaps(self):
        """Pairs of neighbouring cells whose rects intersect."""
        bad = []
        for row in range(self.win.model.rowCount() - 1):
            a = self.win.view.visualRect(self.win.model.index(row, 0))
            b = self.win.view.visualRect(self.win.model.index(row + 1, 0))
            if a.intersects(b):
                bad.append((row, row + 1))
        return bad

    def test_rotate_relayouts_the_row(self):
        """Regression: a rotated cell grew but its neighbours stayed put.

        QListView resized the rotated item and left the rest of the row where
        it was, so the wider landscape cell painted on top of the portrait one
        beside it and both orientations showed at once.
        """
        self.assertEqual(self.overlaps(), [])
        self.win.view.set_selected_rows([1])
        self.win.rotate(90)
        settle(timeout_ms=400)
        rect = self.win.view.visualRect(self.win.model.index(1, 0))
        self.assertGreater(rect.width(), rect.height(), "cell did not become landscape")
        self.assertEqual(self.overlaps(), [])

    def test_zoom_relayouts(self):
        self.win._zoom_by(1.6)
        settle(timeout_ms=400)
        self.assertEqual(self.overlaps(), [])

    def test_visible_range_follows_the_scrollbar(self):
        """Regression: probing one corner landed between cells and reported row 0.

        That pinned relayout anchoring and thumbnail prefetching to the top of
        the document however far down the user had scrolled.
        """
        self.win.model.set_pages(self.win.model.pages * 12)
        settle(timeout_ms=400)
        bar = self.win.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        settle(timeout_ms=200)
        first, last = self.win.view._visible_range()
        self.assertGreater(first, 0)
        self.assertGreaterEqual(last, first)

    def test_rotate_keeps_the_view_where_it_was(self):
        self.win.model.set_pages(self.win.model.pages * 12)
        settle(timeout_ms=400)
        bar = self.win.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        settle(timeout_ms=200)
        before = self.win.view._visible_range()[0]
        self.win.view.set_selected_rows([before + 1])
        self.win.rotate(90)
        settle(timeout_ms=400)
        self.assertLessEqual(abs(self.win.view._visible_range()[0] - before), 1)


class TestExport(QtDocumentTestCase):
    def out(self, name="out.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_round_trip_preserves_page_count(self):
        path = self.out()
        self.assertEqual(export(self.docs.files_for_export(), self.model.pages, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_rotation_is_written(self):
        self.model.rotate([0], 90)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(int(pdf.pages[0].obj.get("/Rotate", 0)), 90)
            self.assertEqual(int(pdf.pages[1].obj.get("/Rotate", 0)), 0)

    def test_reorder_is_written(self):
        self.model.move_rows([0], 2)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_duplicate_is_written(self):
        self.model.duplicate([0])
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 3)

    def test_crop_narrows_the_mediabox(self):
        before = float(self.model.pages[0].width_in_points())
        self.model.pages[0].crop = Sides(0.25, 0.25, 0, 0)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            box = [float(v) for v in pdf.pages[0].obj.MediaBox]
            self.assertAlmostEqual(box[2] - box[0], before * 0.5, delta=1.0)


class TestI18n(unittest.TestCase):
    """Reusing the upstream catalogue depends on msgids surviving intact."""

    def test_mnemonic_conversion(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("_Open"), "&Open")
        self.assertEqual(menu_label("Save _As…"), "Save &As…")

    def test_literal_underscore_survives(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("Rock __Roll"), "Rock _Roll")

    def test_literal_ampersand_is_escaped_for_qt(self):
        from pdfarranger_qt.i18n import menu_label

        self.assertEqual(menu_label("Fish & Chips"), "Fish && Chips")

    def test_setup_is_safe_without_catalogues(self):
        from pdfarranger_qt import i18n

        i18n.setup()
        self.assertEqual(i18n.gettext_("Unknown file format"), "Unknown file format")

    #: Labels with no upstream equivalent, so no translation to inherit. Adding
    #: to this list should be a deliberate act: check `po/` for an existing
    #: msgid first, because a near-miss silently orphans 33 translations.
    NEW_MSGIDS = {
        "_File",      # menubar titles: upstream is a hamburger popover
        "_Page",
        "_Help",
        "_Duplicate",   # upstream has the action but no translated label
        "_Reset Zoom",  # upstream has Zoom _Fit / Fit _One Page instead
    }

    def test_menu_labels_come_from_upstream_msgids(self):
        """Guard against reworded labels silently orphaning 33 translations."""
        import re

        po = os.path.join(os.path.dirname(HERE), "po", "de.po")
        if not os.path.isfile(po):
            self.skipTest("po/ not present")
        with open(po, encoding="utf-8") as fh:
            msgids = set(re.findall(r'^msgid "(.*)"$', fh.read(), re.M))

        source = os.path.join(os.path.dirname(HERE), "pdfarranger_qt", "mainwindow.py")
        with open(source, encoding="utf-8") as fh:
            used = re.findall(r'_m\("([^"]+)"\)', fh.read())
        self.assertTrue(used, "no menu labels found to check")
        unknown = [u for u in used if u not in msgids and u not in self.NEW_MSGIDS]
        self.assertEqual(
            unknown, [],
            f"msgids absent from po/de.po: {unknown}. Check po/ for an existing "
            f"label before adding these to NEW_MSGIDS.")


class TestBlankPages(QtDocumentTestCase):
    def test_creates_a_blank_document(self):
        size = Dims(612, 792)
        name, nfile = self.docs.get_blank_doc(size)
        self.assertTrue(os.path.isfile(name))
        self.assertEqual(self.docs.docs[nfile - 1].blank_size, size)
        with pikepdf.open(name) as pdf:
            self.assertEqual(len(pdf.pages), 1)

    def test_reuses_an_existing_blank_of_the_same_size(self):
        size = Dims(612, 792)
        first, nfile1 = self.docs.get_blank_doc(size)
        second, nfile2 = self.docs.get_blank_doc(size)
        self.assertEqual((first, nfile1), (second, nfile2))

    def test_different_sizes_get_different_documents(self):
        a, _n1 = self.docs.get_blank_doc(Dims(612, 792))
        b, _n2 = self.docs.get_blank_doc(Dims(842, 1191))
        self.assertNotEqual(a, b)

    def test_multi_page_blank(self):
        name, _nfile = self.docs.get_blank_doc(Dims(612, 792), npages=3)
        with pikepdf.open(name) as pdf:
            self.assertEqual(len(pdf.pages), 3)


class TestHideAtExport(QtDocumentTestCase):
    def out(self, name="hidden.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_no_hide_leaves_pages_untouched(self):
        pages = [p.duplicate() for p in self.model.pages]
        before = [(p.copyname, p.npage, len(p.layerpages)) for p in pages]
        self.docs.apply_hide(pages)
        after = [(p.copyname, p.npage, len(p.layerpages)) for p in pages]
        self.assertEqual(before, after)

    def test_hide_rewrites_the_page_as_blank_plus_overlay(self):
        pages = [p.duplicate() for p in self.model.pages]
        original = pages[0].copyname
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        self.docs.apply_hide(pages)

        page = pages[0]
        self.assertNotEqual(page.copyname, original, "page should now be the blank sheet")
        self.assertEqual(page.npage, 1)
        self.assertEqual(page.hide, Sides())
        self.assertEqual(page.angle, 0)
        self.assertEqual(len(page.layerpages), 1)
        layer = page.layerpages[0]
        self.assertEqual(layer.copyname, original, "old content becomes the overlay")
        self.assertEqual(layer.crop, Sides(0.1, 0.1, 0.1, 0.1))
        self.assertEqual(layer.offset, Sides(0.1, 0.1, 0.1, 0.1))

    def test_hide_survives_a_save(self):
        pages = [p.duplicate() for p in self.model.pages]
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        self.docs.apply_hide(pages)
        path = self.out()
        # files_for_export() must come after apply_hide: it appended a document
        self.assertEqual(export(self.docs.files_for_export(), pages, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_hide_within_crop_is_a_no_op(self):
        """Upstream skips when hide is already covered by crop."""
        pages = [p.duplicate() for p in self.model.pages]
        pages[0].crop = Sides(0.2, 0.2, 0.2, 0.2)
        pages[0].hide = Sides(0.1, 0.1, 0.1, 0.1)
        original = pages[0].copyname
        self.docs.apply_hide(pages)
        self.assertEqual(pages[0].copyname, original)
        self.assertEqual(pages[0].layerpages, [])


class TestInMemoryPdf(QtDocumentTestCase):
    def test_round_trips_through_a_qpdfdocument(self):
        from pdfarranger_qt.export import get_in_memory_pdf
        from pdfarranger_qt.render import MemoryDocument

        data = get_in_memory_pdf(self.model.pages, self.docs.files_for_export())
        self.assertTrue(data.startswith(b"%PDF"))
        with MemoryDocument(data) as doc:
            self.assertTrue(doc.ok, f"QPdfDocument refused the buffer: {doc.error}")
            self.assertEqual(doc.page_count(), 2)

    def test_reflects_edits_not_the_source(self):
        """The point of the helper: it renders the edited document."""
        from pdfarranger_qt.export import get_in_memory_pdf
        from pdfarranger_qt.render import MemoryDocument

        self.model.rotate([0], 90)
        data = get_in_memory_pdf(self.model.pages[:1], self.docs.files_for_export())
        with MemoryDocument(data) as doc:
            size = doc.document.pagePointSize(0)
            self.assertGreater(size.width(), size.height(), "rotation not applied")

    def test_only_opens_referenced_documents(self):
        from pdfarranger_qt.export import get_in_memory_pdf

        self.docs.get_blank_doc(Dims(200, 200))  # a second, unreferenced document
        data = get_in_memory_pdf(self.model.pages, self.docs.files_for_export())
        self.assertTrue(data.startswith(b"%PDF"))


class TestExportJobPath(QtDocumentTestCase):
    def out(self, name="job.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_job_path_produces_the_same_page_count(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path],
               preserve_first_document=True)
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_job_path_applies_rotation(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        self.model.rotate([0], 90)
        path = self.out()
        export(self.docs.files_for_export(), self.model.pages, {}, [path],
               preserve_first_document=True)
        with pikepdf.open(path) as pdf:
            self.assertEqual(int(pdf.pages[0].obj.get("/Rotate", 0)), 90)

    def test_both_paths_agree_on_page_count(self):
        from pdfarranger_qt.export import HAS_PIKEPDF8

        if not HAS_PIKEPDF8:
            self.skipTest("pikepdf < 8")
        a, b = self.out("a.pdf"), self.out("b.pdf")
        files = self.docs.files_for_export()
        export(files, self.model.pages, {}, [a], preserve_first_document=False)
        export(files, self.model.pages, {}, [b], preserve_first_document=True)
        with pikepdf.open(a) as pa, pikepdf.open(b) as pb:
            self.assertEqual(len(pa.pages), len(pb.pages))


class TestClipboardFormat(unittest.TestCase):
    """D5: the wire format is upstream's, so both versions can interoperate."""

    def roundtrip(self, pages):
        from pdfarranger_qt import clipboard

        text = clipboard.serialize(pages)
        return text, clipboard.parse(text)

    def test_header_and_hash(self):
        from pdfarranger_qt import clipboard

        page = Page(1, 3, "a.pdf", description="d", size_orig=Dims(612, 792))
        text, parsed = self.roundtrip([page])
        self.assertTrue(text.startswith("pdfarranger-clipboard\n"))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0][0], "a.pdf")
        self.assertEqual(parsed[0][1], 3)

    def test_round_trip_preserves_geometry(self):
        page = Page(1, 1, "a.pdf", angle=90, scale=1.5,
                    crop=Sides(0.1, 0.2, 0.3, 0.4), hide=Sides(0.05, 0, 0, 0),
                    description="hello", size_orig=Dims(612, 792))
        _text, parsed = self.roundtrip([page])
        _f, _n, description, angle, scale, crop, hide, layers = parsed[0]
        self.assertEqual(description, "hello")
        self.assertEqual(angle, 90)
        self.assertEqual(scale, 1.5)
        self.assertEqual(tuple(crop), (0.1, 0.2, 0.3, 0.4))
        self.assertEqual(tuple(hide), (0.05, 0, 0, 0))
        self.assertEqual(layers, [])

    def test_round_trip_preserves_layers(self):
        from pdfarranger_qt.core import LayerPage

        layer = LayerPage(1, 2, "b.pdf", 180, 1.0, Sides(0.1, 0, 0, 0),
                          Sides(0, 0.2, 0, 0), "OVERLAY", Dims(612, 792))
        page = Page(1, 1, "a.pdf", description="d", size_orig=Dims(612, 792),
                    layerpages=[layer])
        _text, parsed = self.roundtrip([page])
        layers = parsed[0][7]
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0][0], "b.pdf")
        self.assertEqual(layers[0][4], "OVERLAY")

    def test_multiple_pages(self):
        pages = [Page(1, i, "a.pdf", description=str(i), size_orig=Dims(612, 792))
                 for i in range(1, 4)]
        _text, parsed = self.roundtrip(pages)
        self.assertEqual([p[1] for p in parsed], [1, 2, 3])

    def test_foreign_text_is_rejected(self):
        from pdfarranger_qt import clipboard

        self.assertIsNone(clipboard.parse("just some text"))
        self.assertIsNone(clipboard.parse(""))
        self.assertFalse(clipboard.is_page_data("hello"))

    def test_tampered_payload_is_rejected(self):
        from pdfarranger_qt import clipboard

        page = Page(1, 1, "a.pdf", description="d", size_orig=Dims(612, 792))
        text = clipboard.serialize([page])
        self.assertIsNone(clipboard.parse(text + "trailing"))


class TestBooklet(unittest.TestCase):
    def test_crops_from_tiles_two_columns(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        self.assertEqual(crops_from_tiles([[1, 50], [2, 50]]), [(0, 0.5), (0.5, 1.0)])

    def test_crops_from_tiles_single(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        self.assertEqual(crops_from_tiles([[1, 100]]), [(0, 1.0)])

    def test_crops_from_tiles_overlapping(self):
        from pdfarranger_qt.booklet import crops_from_tiles

        crops = crops_from_tiles([[1, 60], [2, 60]])
        self.assertAlmostEqual(crops[0][1], 0.6)
        self.assertAlmostEqual(crops[-1][0], 0.4)

    def test_split_restores_reading_order(self):
        """A 2-sheet booklet holds [4|1] and [2|3]; unimposing gives 1 2 3 4."""
        from pdfarranger_qt.booklet import split

        sheets = []
        for i, (left, right) in enumerate([("4", "1"), ("2", "3")]):
            page = Page(1, i + 1, "a.pdf", size_orig=Dims(1224, 792))
            page.description = f"{left}|{right}"
            sheets.append(page)
        result = split(sheets)
        self.assertEqual(len(result), 4)
        # Halves come back as (left-crop, right-crop) pairs of their sheet
        labels = [p.description for p in result]
        self.assertEqual(labels, ["4|1", "2|3", "2|3", "4|1"])
        # Reading order: sheet0-right, sheet1-left, sheet1-right, sheet0-left
        self.assertAlmostEqual(result[0].crop.left, 0.5)   # "1" is the right half
        self.assertAlmostEqual(result[1].crop.left, 0.0)   # "2" is the left half
        self.assertAlmostEqual(result[2].crop.left, 0.5)   # "3" is the right half
        self.assertAlmostEqual(result[3].crop.left, 0.0)   # "4" is the left half

    def test_can_split_requires_uniform_size(self):
        from pdfarranger_qt.booklet import can_split

        a = Page(1, 1, "a.pdf", size_orig=Dims(1224, 792))
        b = Page(1, 2, "a.pdf", size_orig=Dims(612, 792))
        self.assertTrue(can_split([a, a.duplicate()]))
        self.assertFalse(can_split([a, b]))
        self.assertFalse(can_split([]))


class TestListOperations(QtDocumentTestCase):
    def setUp(self):
        super().setUp()
        self.model.duplicate([0, 1])
        for i, page in enumerate(self.model.pages):
            page.description = str(i)

    def order(self):
        return [p.description for p in self.model.pages]

    def test_reverse(self):
        self.model.reverse_rows([0, 1, 2, 3])
        self.assertEqual(self.order(), ["3", "2", "1", "0"])

    def test_reverse_a_subrange_leaves_the_rest(self):
        self.model.reverse_rows([1, 2])
        self.assertEqual(self.order(), ["0", "2", "1", "3"])

    def test_swap_odd_even(self):
        self.model.swap_odd_even([0, 1, 2, 3])
        self.assertEqual(self.order(), ["1", "0", "3", "2"])

    def test_swap_ignores_a_trailing_odd_page(self):
        self.model.swap_odd_even([0, 1, 2])
        self.assertEqual(self.order(), ["1", "0", "2", "3"])

    def test_interleave_before(self):
        extra = [self.model.pages[0].duplicate() for _ in range(2)]
        for i, page in enumerate(extra):
            page.description = f"x{i}"
        self.model.insert_interleaved(0, extra, after=False)
        self.assertEqual(self.order(), ["x0", "0", "x1", "1", "2", "3"])

    def test_interleave_after(self):
        extra = [self.model.pages[0].duplicate() for _ in range(2)]
        for i, page in enumerate(extra):
            page.description = f"x{i}"
        self.model.insert_interleaved(0, extra, after=True)
        self.assertEqual(self.order(), ["0", "x0", "1", "x1", "2", "3"])

    def test_rows_matching_same_file(self):
        self.assertEqual(self.model.rows_matching([0], "copyname"), [0, 1, 2, 3])

    def test_rows_matching_same_format(self):
        self.model.pages[2].scale = 2.0  # a different size in points
        matched = self.model.rows_matching([0], "size_in_points")
        self.assertIn(0, matched)
        self.assertNotIn(2, matched)

    def test_replace_rows(self):
        replacement = [self.model.pages[0].duplicate()]
        replacement[0].description = "new"
        self.model.replace_rows([1, 2], replacement)
        self.assertEqual(self.order(), ["0", "new", "3"])


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


class TestRubberBandScroll(unittest.TestCase):
    """Scrolling with the button held keeps extending the rubber band (§8)."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(700, 500)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.model.set_pages(self.win.model.pages * 24)  # enough to scroll
        self.win.modified = False
        settle(timeout_ms=600)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def band(self):
        """Start a rubber band in the empty gutter and sweep it across items."""
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        viewport = self.win.view.viewport()

        def send(kind, pos, button, buttons):
            _app.sendEvent(viewport, QMouseEvent(kind, QPointF(pos), QPointF(pos),
                                                 button, buttons, Qt.NoModifier))

        start = QPoint(viewport.width() - 24, 3)
        self.assertFalse(self.win.view.indexAt(start).isValid(),
                         "band must start on empty space, not an item")
        send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, QPoint(400, 150), Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseMove, QPoint(100, 205), Qt.NoButton, Qt.LeftButton)
        return QPoint(100, 205)

    def scroll(self, at, notches=-2):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        event = QWheelEvent(QPointF(at), QPointF(at), QPoint(0, 0),
                            QPoint(0, notches * 120), Qt.LeftButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        _app.sendEvent(self.win.view.viewport(), event)
        settle(timeout_ms=200)

    def test_band_selects_items_it_sweeps(self):
        self.band()
        self.assertEqual(self.win.view.selected_rows(), [0, 1, 2, 3])

    def test_scrolling_extends_the_band_without_a_mouse_move(self):
        """Regression: Qt moves the band with the content but only recomputes
        the selection on the next mouse move, so the selection went stale."""
        at = self.band()
        before = self.win.view.selected_rows()
        self.scroll(at)
        after = self.win.view.selected_rows()
        self.assertGreater(len(after), len(before),
                           "selection should grow as the view scrolls under the band")
        self.assertEqual(after[:len(before)], before, "earlier pages stay selected")

    def test_scroll_outside_a_band_does_not_select(self):
        from PySide6.QtCore import QPoint

        self.win.view.clearSelection()
        self.scroll(QPoint(100, 205))
        self.assertEqual(self.win.view.selected_rows(), [])


class TestDragPayload(unittest.TestCase):
    """The drag payload is upstream's MODEL_ROW_EXTERN: records, no hash."""

    def pages(self):
        return [Page(1, i, "a.pdf", description=str(i), size_orig=Dims(612, 792))
                for i in (1, 2)]

    def test_drag_payload_has_no_marker_or_hash(self):
        from pdfarranger_qt import clipboard

        payload = clipboard.serialize_for_drag(self.pages())
        self.assertFalse(payload.startswith(clipboard.MARKER))
        self.assertTrue(payload.startswith("a.pdf///1///"))

    def test_drag_payload_is_the_clipboard_body(self):
        from pdfarranger_qt import clipboard

        pages = self.pages()
        clip = clipboard.serialize(pages)
        drag = clipboard.serialize_for_drag(pages)
        self.assertTrue(clip.endswith(drag), "drag payload should be the clipboard body")

    def test_parse_records_round_trip(self):
        from pdfarranger_qt import clipboard

        entries = clipboard.parse_records(clipboard.serialize_for_drag(self.pages()))
        self.assertEqual([e[1] for e in entries], [1, 2])

    def test_parse_records_rejects_rubbish(self):
        from pdfarranger_qt import clipboard

        self.assertIsNone(clipboard.parse_records(""))
        self.assertIsNone(clipboard.parse_records("nonsense"))

    def test_mime_name_matches_upstream_target(self):
        from pdfarranger_qt import clipboard

        self.assertEqual(clipboard.MIME_PAGES, "MODEL_ROW_EXTERN")


class TestCrossInstanceDrop(unittest.TestCase):
    """Dropping a page payload onto the grid, as another instance would."""

    def setUp(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1100, 760)
        self.win.model.zoom = 0.22
        self.win.show()
        self.win.open_paths([TEST_PDF])
        self.win.modified = False
        settle(timeout_ms=400)

    def tearDown(self):
        self.win.modified = False
        self.win.close()

    def payload(self):
        from pdfarranger_qt import clipboard

        return clipboard.serialize_for_drag(self.win.model.pages[:1])

    def drop(self, payload, pos=None):
        """Send the full enter/move/drop sequence a real drag produces.

        Qt will not deliver a bare QDropEvent: the widget has to have accepted a
        drag-enter first, so a drop-only harness silently tests nothing.
        """
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from pdfarranger_qt import clipboard

        mime = QMimeData()
        mime.setData(clipboard.MIME_PAGES, payload.encode("utf-8"))
        point = pos or QPointF(self.win.view.viewport().rect().center())
        viewport = self.win.view.viewport()

        for factory in (QDragEnterEvent, QDragMoveEvent):
            event = factory(point.toPoint(), Qt.CopyAction, mime,
                            Qt.LeftButton, Qt.NoModifier)
            event.setDropAction(Qt.CopyAction)
            _app.sendEvent(viewport, event)

        event = QDropEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.setDropAction(Qt.CopyAction)
        _app.sendEvent(viewport, event)
        return event

    def test_dropped_pages_are_added(self):
        before = self.win.model.rowCount()
        event = self.drop(self.payload())
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.win.model.rowCount(), before + 1)
        self.assertTrue(self.win.modified)

    def test_drop_is_undoable(self):
        before = self.win.model.rowCount()
        self.drop(self.payload())
        self.assertEqual(self.win.act_undo.text(), "&Undo Paste")
        self.win.undo()
        self.assertEqual(self.win.model.rowCount(), before)

    def test_drop_does_not_remove_from_the_source(self):
        """A cross-instance drag is a copy; the sender keeps its pages."""
        pages_before = list(self.win.model.pages)
        self.drop(self.payload())
        for page in pages_before:
            self.assertIn(page, self.win.model.pages)

    def test_payload_from_a_foreign_temp_dir_is_copied_locally(self):
        """Pasting another instance's file must not depend on it staying alive."""
        import shutil
        import tempfile

        foreign_dir = tempfile.mkdtemp()
        foreign = os.path.join(foreign_dir, "other.pdf")
        shutil.copy(TEST_PDF, foreign)

        page = Page(1, 1, foreign, description="from elsewhere",
                    size_orig=Dims(612, 792))
        from pdfarranger_qt import clipboard

        self.drop(clipboard.serialize_for_drag([page]))
        added = self.win.model.pages[-1]
        self.assertTrue(added.copyname.startswith(self.win.docs.tmp_dir),
                        f"{added.copyname} should live in our own temp dir")
        # The source can now disappear without breaking us.
        shutil.rmtree(foreign_dir)
        self.assertTrue(os.path.isfile(added.copyname))

    def test_garbage_payload_is_ignored(self):
        before = self.win.model.rowCount()
        self.drop("not a page record at all")
        self.assertEqual(self.win.model.rowCount(), before)

    def test_file_dropped_on_a_page_inserts_there(self):
        """Regression: the viewport did not accept drops, so file drops fell
        through to the main window, which can only append at the end."""
        from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

        self.assertTrue(self.win.view.viewport().acceptDrops())
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(TEST_PDF)])
        rect = self.win.view.visualRect(self.win.model.index(0, 0))
        point = QPointF(rect.center())
        viewport = self.win.view.viewport()
        for factory in (QDragEnterEvent, QDragMoveEvent):
            event = factory(point.toPoint(), Qt.CopyAction, mime,
                            Qt.LeftButton, Qt.NoModifier)
            event.setDropAction(Qt.CopyAction)
            _app.sendEvent(viewport, event)
        event = QDropEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.setDropAction(Qt.CopyAction)
        _app.sendEvent(viewport, event)
        settle(timeout_ms=300)
        self.assertEqual(self.win.model.rowCount(), 4)
        # Inserted at row 0, not appended at the end.
        self.assertEqual(self.win.view.selected_rows(), [0, 1])

    def test_dragging_out_and_back_moves_rather_than_duplicates(self):
        """Regression: a page dragged out of the window and back in was pasted.

        Once the gesture escalates to a QDrag it carries page data, so on the
        way back it looks exactly like a foreign drop. Without checking the
        source, the page silently duplicated instead of moving.
        """
        self.win.model.duplicate([0])
        for i, page in enumerate(self.win.model.pages):
            page.description = str(i)
        before = self.win.model.rowCount()

        view = self.win.view
        view.set_selected_rows([0])
        view._dragged_rows = [0]  # as _escalate_to_system_drag() records
        view.handle_page_drop(self.payload(), before, internal=True)

        self.assertEqual(self.win.model.rowCount(), before, "page was duplicated")
        self.assertEqual([p.description for p in self.win.model.pages][-1], "0")

    def test_ctrl_on_a_returning_drag_copies(self):
        """Out of the window and back with ctrl held: duplicate, not reorder."""
        before = self.win.model.rowCount()
        view = self.win.view
        view.set_selected_rows([0])
        view._dragged_rows = [0]
        view.handle_page_drop(self.payload(), before, internal=True, copy=True)
        self.assertEqual(self.win.model.rowCount(), before + 1)

    def test_ctrl_makes_no_difference_to_a_foreign_drop(self):
        """Between instances it is already a copy, so ctrl changes nothing."""
        before = self.win.model.rowCount()
        view = self.win.view
        view._dragged_rows = []
        view.handle_page_drop(self.payload(), before, internal=False, copy=False)
        plain = self.win.model.rowCount()
        view.handle_page_drop(self.payload(), plain, internal=False, copy=True)
        self.assertEqual(plain, before + 1)
        self.assertEqual(self.win.model.rowCount(), plain + 1)

    def test_a_foreign_drop_still_copies(self):
        before = self.win.model.rowCount()
        view = self.win.view
        view._dragged_rows = [0]
        view.handle_page_drop(self.payload(), before, internal=False)
        self.assertEqual(self.win.model.rowCount(), before + 1)

    def test_internal_drop_without_recorded_rows_falls_back_to_copy(self):
        """Defensive: never silently drop pages if the drag state was lost."""
        before = self.win.model.rowCount()
        view = self.win.view
        view._dragged_rows = []
        view.handle_page_drop(self.payload(), before, internal=True)
        self.assertEqual(self.win.model.rowCount(), before + 1)

    def test_view_advertises_the_page_format(self):
        from PySide6.QtCore import QMimeData
        from pdfarranger_qt import clipboard

        mime = QMimeData()
        mime.setData(clipboard.MIME_PAGES, b"x")
        self.assertTrue(self.win.view._accepts(mime))
        self.assertFalse(self.win.view._accepts(QMimeData()))


class TestLayers(QtDocumentTestCase):
    """Compositing pages onto pages -- the basis of Merge, booklets and margins."""

    def out(self, name="layers.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def entry(self, page):
        from pdfarranger_qt.layers import entry_from_page

        return entry_from_page(page)

    def test_pasting_a_page_adds_one_layer(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(dest.layerpages), 1)
        self.assertEqual(dest.layerpages[0].laypos, OVERLAY)

    def test_same_size_paste_covers_the_page(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        offset = dest.layerpages[0].offset
        for side in offset:
            self.assertAlmostEqual(side, 0.0, places=6,
                                   msg=f"equal sizes should sit flush: {offset}")

    def test_offset_places_the_layer_left_or_right(self):
        from pdfarranger_qt.core import OVERLAY, Dims, Page
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        src = self.model.pages[0]
        wide = Dims(src.size_in_points().width * 2, src.size_in_points().height)
        name, nfile = self.docs.get_blank_doc(wide)

        left_sheet = Page(nfile, 1, name, size_orig=wide)
        right_sheet = Page(nfile, 1, name, size_orig=wide)
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([left_sheet], stacks, OVERLAY, (0, 0.5), self.docs)
        paste_as_layer([right_sheet], stacks, OVERLAY, (1, 0.5), self.docs)

        self.assertAlmostEqual(left_sheet.layerpages[0].offset.left, 0.0, places=6)
        self.assertAlmostEqual(left_sheet.layerpages[0].offset.right, 0.5, places=6)
        self.assertAlmostEqual(right_sheet.layerpages[0].offset.left, 0.5, places=6)
        self.assertAlmostEqual(right_sheet.layerpages[0].offset.right, 0.0, places=6)

    def test_nested_layers_are_carried_across(self):
        """A page that already has a layer keeps it when pasted onto another."""
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        a, b, = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(b)], OVERLAY, self.docs)
        paste_as_layer([a], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(a.layerpages), 1)

        target = a.duplicate()
        target.layerpages = []
        stacks = layer_stacks_from_entries([self.entry(a)], OVERLAY, self.docs)
        paste_as_layer([target], stacks, OVERLAY, (0.5, 0.5), self.docs)
        self.assertEqual(len(target.layerpages), 2, "nested layer was lost")

    def test_composited_page_exports(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([self.entry(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        path = self.out()
        self.assertEqual(
            export(self.docs.files_for_export(), [dest], {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 1, "the layer must not become a page")

    def test_center_on_blank_pages_adds_margins(self):
        from pdfarranger_qt.core import Dims
        from pdfarranger_qt.layers import center_on_blank_pages

        bigger = Dims(842, 1191)  # A3-ish, larger than the test page
        out = center_on_blank_pages([self.model.pages[0]], bigger, self.docs)
        self.assertEqual(out[0].size_in_points(), bigger)
        self.assertEqual(len(out[0].layerpages), 1)
        offset = out[0].layerpages[0].offset
        self.assertAlmostEqual(offset.left, offset.right, places=6, msg="not centred")
        self.assertAlmostEqual(offset.top, offset.bottom, places=6, msg="not centred")

    def test_center_leaves_matching_sizes_alone(self):
        from pdfarranger_qt.layers import center_on_blank_pages

        page = self.model.pages[0]
        out = center_on_blank_pages([page], page.size_in_points(), self.docs)
        self.assertIs(out[0], page)


class TestBookletGenerate(QtDocumentTestCase):
    def pages(self, n):
        base = self.model.pages[0]
        out = []
        for i in range(n):
            page = base.duplicate()
            page.description = str(i + 1)
            out.append(page)
        return out

    def test_four_pages_make_two_sheets(self):
        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(4), self.docs)
        self.assertEqual(len(sheets), 2)

    def test_sheets_are_double_width(self):
        from pdfarranger_qt.booklet import generate

        src = self.pages(4)
        sheets = generate(src, self.docs)
        self.assertAlmostEqual(sheets[0].size_in_points().width,
                               src[0].size_in_points().width * 2, places=3)
        self.assertAlmostEqual(sheets[0].size_in_points().height,
                               src[0].size_in_points().height, places=3)

    def test_each_sheet_carries_two_pages(self):
        from pdfarranger_qt.booklet import generate

        for sheet in generate(self.pages(4), self.docs):
            self.assertEqual(len(sheet.layerpages), 2)

    def test_page_count_is_padded_to_a_multiple_of_four(self):
        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(5), self.docs)
        self.assertEqual(len(sheets), 4, "5 pages pad to 8, giving 4 sheets")
        carried = sum(len(s.layerpages) for s in sheets)
        self.assertEqual(carried, 5, "only the real pages are composited")

    def test_round_trip_generate_then_split(self):
        """Impose then unimpose should give the pages back in order."""
        from pdfarranger_qt.booklet import generate, split

        src = self.pages(4)
        sheets = generate(src, self.docs)
        restored = split([s.duplicate() for s in sheets])
        self.assertEqual(len(restored), 4)

    def test_imposed_booklet_exports(self):
        import tempfile

        from pdfarranger_qt.booklet import generate

        sheets = generate(self.pages(4), self.docs)
        path = os.path.join(tempfile.mkdtemp(), "booklet.pdf")
        self.assertEqual(
            export(self.docs.files_for_export(), sheets, {}, [path]), "")
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], 1224, delta=1)


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


class TestPageOperations(QtDocumentTestCase):
    def test_scale_relative(self):
        self.assertTrue(self.model.set_scale([0], 1.5))
        self.assertAlmostEqual(self.model.pages[0].scale, 1.5, places=6)

    def test_scale_to_fit_a_paper_size(self):
        target = Dims(595.27, 841.89)  # A4 in points
        self.assertTrue(self.model.set_scale([0], target))
        size = self.model.pages[0].size_in_points()
        self.assertLessEqual(size.width, target.width + 0.5)
        self.assertLessEqual(size.height, target.height + 0.5)

    def test_scale_clamps_to_the_pdf_limits(self):
        """PDF requires page sides between 72 and 14400 points."""
        self.model.set_scale([0], 0.0001)
        size = self.model.pages[0].size_in_points()
        self.assertGreaterEqual(min(size), 72 - 0.001)

    def test_scale_moves_layers_with_the_page(self):
        from pdfarranger_qt.core import OVERLAY
        from pdfarranger_qt.layers import entry_from_page, layer_stacks_from_entries, paste_as_layer

        dest, src = self.model.pages[0], self.model.pages[1]
        stacks = layer_stacks_from_entries([entry_from_page(src)], OVERLAY, self.docs)
        paste_as_layer([dest], stacks, OVERLAY, (0.5, 0.5), self.docs)
        before = dest.layerpages[0].scale
        self.model.set_scale([0], 2.0)
        self.assertAlmostEqual(dest.layerpages[0].scale, before * 2 / 1.0, places=6)

    def test_set_crop(self):
        self.assertTrue(self.model.set_margins([0], Sides(0.1, 0.1, 0, 0), hide=False))
        self.assertEqual(self.model.pages[0].crop, Sides(0.1, 0.1, 0, 0))
        self.assertEqual(self.model.pages[0].hide, Sides())

    def test_set_hide(self):
        self.assertTrue(self.model.set_margins([0], Sides(0, 0, 0.2, 0), hide=True))
        self.assertEqual(self.model.pages[0].hide, Sides(0, 0, 0.2, 0))
        self.assertEqual(self.model.pages[0].crop, Sides())

    def test_setting_the_same_margins_is_a_no_op(self):
        self.model.set_margins([0], Sides(0.1, 0, 0, 0), hide=False)
        self.assertFalse(self.model.set_margins([0], Sides(0.1, 0, 0, 0), hide=False))

    def test_crop_narrows_the_exported_mediabox(self):
        import tempfile

        before = float(self.model.pages[0].width_in_points())
        self.model.set_margins([0], Sides(0.25, 0.25, 0, 0), hide=False)
        path = os.path.join(tempfile.mkdtemp(), "cropped.pdf")
        export(self.docs.files_for_export(), self.model.pages[:1], {}, [path])
        with pikepdf.open(path) as pdf:
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], before * 0.5, delta=1.0)

    def test_split_into_two_columns(self):
        added = self.model.split_pages([0], columns=2, row_count=1)
        self.assertEqual(added, 1)
        self.assertEqual(self.model.rowCount(), 3)
        self.assertAlmostEqual(self.model.pages[0].crop.right, 0.5, places=6)
        self.assertAlmostEqual(self.model.pages[1].crop.left, 0.5, places=6)

    def test_split_into_a_grid(self):
        added = self.model.split_pages([0], columns=2, row_count=2)
        self.assertEqual(added, 3, "a 2x2 grid yields three extra pages")
        self.assertEqual(self.model.rowCount(), 5)

    def test_split_of_one_by_one_does_nothing(self):
        self.assertEqual(self.model.split_pages([0], 1, 1), 0)
        self.assertEqual(self.model.rowCount(), 2)

    def test_split_multiple_rows_keeps_order(self):
        for i, page in enumerate(self.model.pages):
            page.description = str(i)
        self.model.split_pages([0, 1], columns=2, row_count=1)
        self.assertEqual([p.description for p in self.model.pages],
                         ["0", "0", "1", "1"])

    def test_split_pages_export(self):
        import tempfile

        self.model.split_pages([0], columns=2, row_count=1)
        path = os.path.join(tempfile.mkdtemp(), "split.pdf")
        export(self.docs.files_for_export(), self.model.pages, {}, [path])
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 3)
            box = [float(v) for v in pdf.pages[0].MediaBox]
            self.assertAlmostEqual(box[2] - box[0], 306, delta=1)


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


class TestRaster(QtDocumentTestCase):
    def files(self):
        return self.docs.files_for_export()

    def test_render_pages_matches_page_geometry(self):
        from pdfarranger_qt import raster

        images = list(raster.render_pages(self.model.pages, self.files(), 72))
        self.assertEqual(len(images), 2)
        self.assertEqual((images[0].width(), images[0].height()), (612, 792))

    def test_render_honours_ppi(self):
        from pdfarranger_qt import raster

        images = list(raster.render_pages(self.model.pages[:1], self.files(), 144))
        self.assertEqual(images[0].width(), 1224)

    def test_render_reflects_edits_not_the_source(self):
        from pdfarranger_qt import raster

        self.model.rotate([0], 90)
        image = next(raster.render_pages(self.model.pages[:1], self.files(), 72))
        self.assertGreater(image.width(), image.height())

    def test_renders_are_flattened_onto_white(self):
        """Regression: transparent renders made greyscale see every pixel as ink."""
        from pdfarranger_qt import raster

        image = next(raster.render_pages(self.model.pages[:1], self.files(), 72))
        corner = image.pixelColor(2, 2)
        self.assertGreater(corner.lightness(), 200, "page background should be white")

    def test_white_border_detection_finds_margins(self):
        from pdfarranger_qt import raster

        crops = raster.white_border_crops(self.model.pages, self.files())
        self.assertEqual(len(crops), 2)
        for sides in crops:
            self.assertGreater(sum(sides), 0, "test.pdf has visible white margins")
            self.assertLess(sides.left + sides.right, 1.0)
            self.assertLess(sides.top + sides.bottom, 1.0)

    def test_white_border_detection_is_idempotent(self):
        """Running it twice must not creep further into the content."""
        from pdfarranger_qt import raster

        first = raster.white_border_crops(self.model.pages[:1], self.files())[0]
        self.model.set_margins([0], first, hide=False)
        second = raster.white_border_crops(self.model.pages[:1], self.files())[0]
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, delta=0.02)

    def test_blank_page_is_left_alone(self):
        from pdfarranger_qt import raster
        from pdfarranger_qt.core import Dims, Page

        name, nfile = self.docs.get_blank_doc(Dims(612, 792))
        blank = Page(nfile, 1, name, size_orig=Dims(612, 792))
        crops = raster.white_border_crops([blank], self.docs.files_for_export())
        self.assertEqual(crops[0], Sides(), "a blank page must not be cropped away")

    def test_export_images(self):
        import tempfile

        from pdfarranger_qt import raster

        target = tempfile.mkdtemp()
        paths = [os.path.join(target, f"p{i}.png") for i in range(2)]
        written = raster.export_images(self.model.pages, self.files(), paths, ppi=72)
        self.assertEqual(written, 2)
        for path in paths:
            self.assertGreater(os.path.getsize(path), 0)

    def test_export_images_greyscale(self):
        import tempfile

        from PySide6.QtGui import QImage
        from pdfarranger_qt import raster

        target = tempfile.mkdtemp()
        path = os.path.join(target, "grey.png")
        raster.export_images(self.model.pages[:1], self.files(), [path],
                             ppi=72, greyscale=True)
        loaded = QImage(path)
        self.assertTrue(loaded.isGrayscale() or loaded.allGray())

    def test_export_rasterised_pdf(self):
        import tempfile

        from pdfarranger_qt import raster

        path = os.path.join(tempfile.mkdtemp(), "flat.pdf")
        self.assertTrue(raster.export_rasterised_pdf(
            self.model.pages, self.files(), path, ppi=72))
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_rasterised_pdf_has_no_text(self):
        """The point of rasterising: nothing is extractable any more."""
        import tempfile

        from pdfarranger_qt import raster
        from pdfarranger_qt.core import DocumentSet

        source = DocumentSet()
        self.addCleanup(source.cleanup)
        pages = source.add_file(TEXT_PDF)
        before = raster.page_text(pages[:1], source.files_for_export())
        self.assertTrue(before.strip(), "fixture should have text to begin with")

        path = os.path.join(tempfile.mkdtemp(), "flat.pdf")
        raster.export_rasterised_pdf(pages[:1], source.files_for_export(),
                                     path, ppi=72)
        flat = DocumentSet()
        self.addCleanup(flat.cleanup)
        flat_pages = flat.add_file(path)
        after = raster.page_text(flat_pages[:1], flat.files_for_export())
        self.assertFalse(after.strip(), "rasterised output should have no text layer")

    def test_page_text_on_a_graphic_only_page(self):
        from pdfarranger_qt import raster

        self.assertEqual(raster.page_text(self.model.pages[:1], self.files()).strip(), "")


class TestEmbeddedImages(unittest.TestCase):
    """Extract and Explode work off the embedded images, not a render."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.addCleanup(self.docs.cleanup)
        # A scanned page is one big image; build one by rasterising a fixture.
        from pdfarranger_qt import raster

        source = DocumentSet()
        self.addCleanup(source.cleanup)
        pages = source.add_file(TEST_PDF)
        import tempfile

        self.scan = os.path.join(tempfile.mkdtemp(), "scan.pdf")
        raster.export_rasterised_pdf(pages[:1], source.files_for_export(),
                                     self.scan, ppi=72)
        self.pages = self.docs.add_file(self.scan)

    def files(self):
        return self.docs.files_for_export()

    def test_counts_the_embedded_images(self):
        from pdfarranger_qt import raster

        self.assertEqual(raster.count_embedded_images(self.pages[0], self.files()), 1)

    def test_extracts_the_image(self):
        from pdfarranger_qt import raster

        images = raster.embedded_images(self.pages[0], self.files())
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].size, (612, 792))

    def test_a_vector_page_has_no_embedded_images(self):
        from pdfarranger_qt import raster
        from pdfarranger_qt.core import DocumentSet

        plain = DocumentSet()
        self.addCleanup(plain.cleanup)
        pages = plain.add_file(TEST_PDF)
        self.assertEqual(
            raster.count_embedded_images(pages[0], plain.files_for_export()), 0)

    def test_explode_writes_one_file_per_image(self):
        from pdfarranger_qt import raster

        paths = raster.explode_to_files(self.pages[0], self.files(), self.docs.tmp_dir)
        self.assertEqual(len(paths), 1)
        self.assertTrue(os.path.getsize(paths[0]) > 0)

    def test_pil_to_qimage_preserves_size(self):
        from pdfarranger_qt import raster

        image = raster.embedded_images(self.pages[0], self.files())[0]
        qimage = raster.pil_to_qimage(image)
        self.assertEqual((qimage.width(), qimage.height()), image.size)
        self.assertFalse(qimage.isNull())


class TestPrinting(QtDocumentTestCase):
    """QPrinter can write a PDF with no dialog or spooler, so this is testable."""

    def printer(self, path):
        """A PDF-writing QPrinter: no dialog, no spooler, no printer needed.

        Constructing one under the offscreen platform raises a harmless
        first-chance COM exception (REGDB_E_IIDNOTREG) because there is no print
        subsystem to query. It does not stop anything, but faulthandler prints
        a stack trace for each one, so it is muted just around the call.
        """
        import faulthandler

        from PySide6.QtPrintSupport import QPrinter

        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            printer = QPrinter(QPrinter.HighResolution)
        finally:
            if was_enabled:
                faulthandler.enable()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        return printer

    def out(self, name="print.pdf"):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), name)

    def test_prints_every_page(self):
        from pdfarranger_qt import printing

        path = self.out()
        printed = printing.print_pages(self.model.pages, self.docs.files_for_export(),
                                       self.printer(path), dpi=72)
        self.assertEqual(printed, 2)
        with pikepdf.open(path) as pdf:
            self.assertEqual(len(pdf.pages), 2)

    def test_auto_rotate_does_not_change_the_sheet_mid_job(self):
        """Regression: setPageOrientation() between pages wedged the native
        Windows engine after the output had already been written."""
        from PySide6.QtGui import QPageLayout
        from pdfarranger_qt import printing

        self.model.rotate([1], 90)  # one landscape page among portrait ones
        path = self.out()
        printer = self.printer(path)
        printing.prepare(printer, self.model.pages, auto_rotate=True)
        before = printer.pageLayout().orientation()
        printing.print_pages(self.model.pages, self.docs.files_for_export(),
                             printer, dpi=72, auto_rotate=True)
        self.assertEqual(printer.pageLayout().orientation(), before,
                         "the sheet orientation must be fixed for the whole job")

    def test_dominant_orientation(self):
        from PySide6.QtGui import QPageLayout
        from pdfarranger_qt import printing

        self.assertEqual(printing.dominant_orientation(self.model.pages),
                         QPageLayout.Portrait)
        for page in self.model.pages:
            page.rotate(90)
        self.assertEqual(printing.dominant_orientation(self.model.pages),
                         QPageLayout.Landscape)

    def test_mismatched_pages_are_rotated_to_fit(self):
        from pdfarranger_qt import printing
        from PySide6.QtGui import QImage

        portrait = QImage(100, 200, QImage.Format_RGB32)
        turned = printing._match_orientation(portrait, sheet_is_landscape=True)
        self.assertGreater(turned.width(), turned.height())
        # A page that already matches is handed back untouched.
        same = printing._match_orientation(portrait, sheet_is_landscape=False)
        self.assertIs(same, portrait)

    def test_progress_starts_before_any_page_is_rendered(self):
        """The first tick fires right after QPainter.begin() returns.

        That is when the spooler's own save dialog has been answered, and just
        before the render -- the long stretch that previously had no feedback.
        """
        from pdfarranger_qt import printing

        seen = []
        printing.print_pages(self.model.pages, self.docs.files_for_export(),
                             self.printer(self.out()), dpi=72,
                             progress=lambda done, total: seen.append((done, total)) or True)
        self.assertEqual(seen[0], (0, 2))
        self.assertEqual(seen[-1], (2, 2))

    def test_progress_callback_can_cancel(self):
        from pdfarranger_qt import printing

        seen = []

        def stop_after_one(done, total):
            seen.append((done, total))
            return done < 1  # let the initial tick through, stop after page 1

        printed = printing.print_pages(
            self.model.pages, self.docs.files_for_export(),
            self.printer(self.out()), dpi=72, progress=stop_after_one)
        self.assertEqual(printed, 1)
        self.assertEqual(seen, [(0, 2), (1, 2)])

    def test_finalise_runs_before_the_painter_ends(self):
        """Regression: the progress dialog auto-closed on reaching its maximum,
        so the app went dark for exactly the slowest part of the job."""
        from pdfarranger_qt import printing

        order = []
        printing.print_pages(
            self.model.pages, self.docs.files_for_export(),
            self.printer(self.out()), dpi=72,
            progress=lambda done, total: order.append(f"page {done}") or True,
            on_finalise=lambda: order.append("finalise"))
        self.assertEqual(order[-1], "finalise",
                         "finalise must come after every page, before end()")

    def test_prepare_sets_the_document_name(self):
        from pdfarranger_qt import printing

        printer = self.printer(self.out())
        printing.prepare(printer, self.model.pages, doc_name="Hopwell.pdf")
        self.assertEqual(printer.docName(), "Hopwell.pdf")


class TestSearch(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt.core import DocumentSet
        from pdfarranger_qt.search import SearchIndex

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(TEXT_PDF)
        self.index = SearchIndex()

    def tearDown(self):
        self.index.invalidate()
        self.docs.cleanup()

    def files(self):
        return self.docs.files_for_export()

    def test_finds_a_phrase(self):
        """Regression: rowCount() populates asynchronously and reported nothing."""
        matches = self.index.search("tests", self.pages, self.files())
        self.assertEqual(matches, [0])

    def test_missing_phrase_finds_nothing(self):
        self.assertEqual(self.index.search("zzzznotpresent", self.pages, self.files()), [])

    def test_empty_phrase_finds_nothing(self):
        self.assertEqual(self.index.search("", self.pages, self.files()), [])

    def test_next_wraps_around(self):
        self.index.search("tests", self.pages, self.files())
        first = self.index.next()
        self.assertEqual(self.index.next(), first, "one match should wrap to itself")

    def test_previous_without_matches_is_none(self):
        self.index.search("zzzz", self.pages, self.files())
        self.assertIsNone(self.index.previous())

    def test_invalidate_allows_a_rebuild(self):
        self.index.search("tests", self.pages, self.files())
        self.index.invalidate()
        self.assertEqual(self.index.search("tests", self.pages, self.files()), [0])


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


def dialogs_defaults():
    from pdfarranger_qt import dialogs

    return dict(dialogs.PREFERENCES)


def color_schemes_supported() -> bool:
    """The offscreen platform has no colour scheme; it always reports Unknown.

    Verified on a real windows platform that setColorScheme() does take effect
    there (Light -> Dark, palette windowText #000000 -> #ffffff), so these
    assertions are skipped rather than weakened.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Unknown


class TestTheme(unittest.TestCase):
    """Name mapping is always checked; the Qt effect only where the platform has one."""

    def tearDown(self):
        from pdfarranger_qt import theme

        theme.apply(theme.SYSTEM)

    def test_apply_returns_the_scheme_it_set(self):
        from pdfarranger_qt import theme

        self.assertEqual(theme.apply(theme.DARK), theme.DARK)
        self.assertEqual(theme.apply(theme.LIGHT), theme.LIGHT)

    def test_unknown_name_falls_back_to_system(self):
        from pdfarranger_qt import theme

        self.assertEqual(theme.apply("chartreuse"), theme.SYSTEM)

    def test_system_hands_control_back(self):
        from pdfarranger_qt import theme

        theme.apply(theme.DARK)
        self.assertEqual(theme.apply(theme.SYSTEM), theme.SYSTEM)

    def test_dark_reaches_qt(self):
        if not color_schemes_supported():
            self.skipTest("platform has no colour scheme (offscreen)")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        theme.apply(theme.DARK)
        self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                         Qt.ColorScheme.Dark)
        self.assertEqual(theme.current(), theme.DARK)

    def test_light_reaches_qt(self):
        if not color_schemes_supported():
            self.skipTest("platform has no colour scheme (offscreen)")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from pdfarranger_qt import theme

        theme.apply(theme.LIGHT)
        self.assertEqual(QGuiApplication.styleHints().colorScheme(),
                         Qt.ColorScheme.Light)

    def test_preferences_apply_the_theme_without_a_restart(self):
        from pdfarranger_qt import dialogs, theme
        from pdfarranger_qt.mainwindow import MainWindow

        applied = []
        original_apply = theme.apply
        theme.apply = lambda name: applied.append(name) or original_apply(name)
        self.addCleanup(setattr, theme, "apply", original_apply)

        win = MainWindow()
        self.addCleanup(win.close)

        class Stub:
            def __init__(self, *a, **k):
                pass

            def get_value(self):
                return {**dict(dialogs.PREFERENCES), "theme": "dark", "shortcuts": {}}

        original = dialogs.PreferencesDialog
        dialogs.PreferencesDialog = Stub
        self.addCleanup(setattr, dialogs, "PreferencesDialog", original)

        applied.clear()
        win.edit_preferences()
        self.assertIn("dark", applied, "the theme should be applied, not just stored")
        self.assertEqual(win._preference("theme"), "dark")

    def test_theme_is_applied_at_startup(self):
        from pdfarranger_qt import theme
        from pdfarranger_qt.mainwindow import MainWindow

        applied = []
        original_apply = theme.apply
        theme.apply = lambda name: applied.append(name) or original_apply(name)
        self.addCleanup(setattr, theme, "apply", original_apply)

        win = MainWindow()
        self.addCleanup(win.close)
        self.assertTrue(applied, "startup should apply the stored theme")


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


class TestTranslations(unittest.TestCase):
    """The catalogues have to actually load, not just be present.

    Run `python tools/build_mo.py` first; these skip if build/mo is absent.
    """

    def setUp(self):
        from pdfarranger_qt import i18n

        self.i18n = i18n
        root = os.path.dirname(HERE)
        if not os.path.isdir(os.path.join(root, "build", "mo", "de")):
            self.skipTest("catalogues not compiled (run tools/build_mo.py)")

    def tearDown(self):
        self.i18n.setup(None)

    def test_german_translates(self):
        """Regression: setup() reported success while translating nothing.

        GNUTranslations subclasses NullTranslations, so an isinstance check
        could not tell a loaded catalogue from a failed one.
        """
        self.assertEqual(self.i18n.setup("de"), "de")
        self.assertEqual(self.i18n.gettext_("_Save"), "_Speichern")

    def test_mnemonic_conversion_survives_translation(self):
        self.i18n.setup("de")
        self.assertEqual(self.i18n.menu_label("_Save"), "&Speichern")

    def test_translator_may_move_the_mnemonic(self):
        """CJK catalogues put the accelerator in brackets after the word."""
        self.i18n.setup("zh_CN")
        label = self.i18n.menu_label("_Save")
        self.assertIn("&S", label)
        self.assertNotIn("_", label)

    def test_several_languages_load(self):
        for language in ("fr", "sv", "ru", "ja", "pt_BR"):
            self.assertEqual(self.i18n.setup(language), language, language)
            self.assertNotEqual(self.i18n.gettext_("_Open"), "_Open",
                                f"{language} did not translate")

    def test_unknown_language_falls_back_to_msgids(self):
        self.assertEqual(self.i18n.setup("xx"), "")
        self.assertEqual(self.i18n.gettext_("_Open"), "_Open")

    def test_untranslated_string_returns_its_msgid(self):
        self.i18n.setup("de")
        self.assertEqual(self.i18n.gettext_("Arrange"), "Arrange")

    def test_window_builds_translated(self):
        from pdfarranger_qt.mainwindow import MainWindow

        self.i18n.setup("de")
        win = MainWindow()
        self.addCleanup(win.close)
        self.assertEqual(win.act_save.text(), "&Speichern")


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


class TestPackaging(unittest.TestCase):
    """The project metadata has to match what the code actually needs."""

    def pyproject(self):
        import tomllib

        path = os.path.join(os.path.dirname(HERE), "pyproject.toml")
        with open(path, "rb") as handle:
            return tomllib.load(handle)

    def test_declares_every_runtime_import(self):
        data = self.pyproject()
        names = " ".join(data["project"]["dependencies"]).lower()
        for package in ("pyside6", "pikepdf", "img2pdf", "python-dateutil", "packaging"):
            self.assertIn(package, names, f"{package} is imported but not declared")

    def test_entry_point_resolves(self):
        data = self.pyproject()
        target = data["project"]["gui-scripts"]["pdfarranger-qt"]
        module, _sep, function = target.partition(":")
        imported = __import__(module, fromlist=[function])
        self.assertTrue(callable(getattr(imported, function)))

    def test_version_matches_the_package(self):
        """Two places declare the version; they must not drift apart."""
        from pdfarranger_qt import __version__

        self.assertEqual(self.pyproject()["project"]["version"], __version__)

    def test_the_gtk_application_is_gone(self):
        """Phase 5 removed it; nothing may quietly import it again."""
        root = os.path.dirname(HERE)
        self.assertFalse(os.path.isdir(os.path.join(root, "pdfarranger")),
                         "the GTK package should have been removed")
        with self.assertRaises(ImportError):
            __import__("pdfarranger.core")

    def test_only_the_qt_package_is_shipped(self):
        """The GTK package must not be swept into the wheel."""
        data = self.pyproject()
        include = data["tool"]["setuptools"]["packages"]["find"]["include"]
        self.assertEqual(include, ["pdfarranger_qt*"])


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
