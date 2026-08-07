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

"""The clipboard wire format and drops from another instance."""

import os
import unittest

from pdfarranger_qt.core import Dims, Page, Sides

from support import QT_APP, TEST_PDF, settle


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
            QT_APP.sendEvent(viewport, event)

        event = QDropEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.setDropAction(Qt.CopyAction)
        QT_APP.sendEvent(viewport, event)
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
            QT_APP.sendEvent(viewport, event)
        event = QDropEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event.setDropAction(Qt.CopyAction)
        QT_APP.sendEvent(viewport, event)
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
