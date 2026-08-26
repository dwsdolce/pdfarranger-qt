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

"""Helpers shared by the test modules.

Separate from ``conftest.py``, which is only for the things that must happen
once per process. These are ordinary importable helpers -- a TestCase base
class is not a pytest fixture and does not belong in a conftest.
"""

import os
import tempfile
import unittest

from PySide6.QtCore import QEventLoop, QTimer

# Re-exported so a test module needs only one import line, not two.
from conftest import MESSAGE_BOXES, QT_APP  # noqa: F401

from pdfarranger_qt.core import DocumentSet
from pdfarranger_qt.model import PageListModel
from pdfarranger_qt.render import Renderer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: Two pages of vector graphics: a green triangle and a red one.
TEST_PDF = os.path.join(HERE, "test.pdf")
#: Has a real text layer, for search and text extraction.
TEXT_PDF = os.path.join(HERE, "test_raster_image_text.pdf")


def settle(condition=None, timeout_ms=8000, step_ms=50):
    """Spin the event loop until ``condition`` holds or the timeout expires.

    Rendering happens on a worker thread, so most assertions about thumbnails
    need the main loop to turn over before they are true.
    """
    elapsed = 0
    while elapsed < timeout_ms:
        if condition is not None and condition():
            return True
        loop = QEventLoop()
        QTimer.singleShot(step_ms, loop.quit)
        loop.exec()
        elapsed += step_ms
    return condition is None or condition()


def temp_path(name):
    """A path in a fresh temporary directory, for export targets."""
    return os.path.join(tempfile.mkdtemp(), name)


def last_message_box():
    """The most recent recorded message box, or None."""
    return MESSAGE_BOXES[-1] if MESSAGE_BOXES else None


class QtDocumentTestCase(unittest.TestCase):
    """A loaded two-page document with a live renderer.

    Deliberately the real objects rather than mocks: the bugs worth catching in
    this layer are timing and Qt-semantics bugs, which a mock would hide.
    """

    def setUp(self):
        self.docs = DocumentSet()
        self.renderer = Renderer()
        self.model = PageListModel(self.renderer)
        self.model.doc_password = lambda page: self.docs.docs[page.nfile - 1].password
        self.model.set_pages(self.docs.add_file(TEST_PDF))

    def tearDown(self):
        self.renderer.shutdown()
        self.docs.cleanup()

    def files(self):
        return self.docs.files_for_export()

    def out(self, name="out.pdf"):
        return temp_path(name)

    def render_all(self):
        """Render every page and wait for the worker thread to deliver."""
        self.model.ensure_rendered(0, self.model.rowCount() - 1)
        settle(lambda: all(
            self.model.data(self.model.index(r, 0), self.model.ImageRole) is not None
            for r in range(self.model.rowCount())
        ))
        return [self.model.data(self.model.index(r, 0), self.model.ImageRole)
                for r in range(self.model.rowCount())]
