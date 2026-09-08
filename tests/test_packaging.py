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

"""Project metadata, and a guard against GTK creeping back."""

import os
import unittest

from support import HERE


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
        # Pillow is in the list despite no `import PIL` anywhere: it reaches
        # the code as the return type of `pikepdf.PdfImage.as_pil_image()`,
        # which Extract Images calls and then saves. A dependency that is only
        # ever touched through another library's return value is exactly the
        # kind this check exists to catch, and it went undeclared for months.
        for package in ("pyside6", "pikepdf", "img2pdf", "pillow",
                        "python-dateutil", "packaging"):
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

    def test_pyinstaller_is_declared(self):
        """packaging/build_win runs pyinstaller out of the dev venv."""
        extras = self.pyproject()["project"]["optional-dependencies"]
        for group in ("dev", "packaging"):
            names = " ".join(extras[group]).lower()
            self.assertIn("pyinstaller", names, f"the {group} extra cannot build")

    def packaging_file(self, name):
        path = os.path.join(os.path.dirname(HERE), "packaging", name)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_windows_calls_the_application_by_its_name(self):
        """FileDescription is a name, not a sentence.

        Windows shows it in the "Open with" menu, in Task Manager and as the
        Description on the Properties tab, beside entries like "Acrobat" and
        "Notepad". It once held "Merge, split, rearrange, rotate and crop PDF
        documents", which is what the "Open with" menu then offered.
        """
        from pdfarranger_qt import APP_NAME

        spec = self.packaging_file("pdfarranger-qt.spec")
        self.assertIn(f'StringStruct("FileDescription", "{APP_NAME}")', spec)

    def test_the_open_with_entry_is_named_too(self):
        """Explorer prefers FriendlyAppName, and falls back to the exe's."""
        from pdfarranger_qt import APP_NAME

        setup = self.packaging_file("pdfarranger-qt.iss")
        self.assertIn(f'#define MyAppName "{APP_NAME}"', setup)
        self.assertEqual(setup.count('ValueName: "FriendlyAppName"'), 2,
                         "both the ProgId and the exe need naming")

    def test_babel_is_declared(self):
        """tools/build_mo.py imports it, and the build scripts run that first."""
        extras = self.pyproject()["project"]["optional-dependencies"]
        self.assertIn("babel", " ".join(extras["dev"]).lower())

    def test_project_url_matches_the_package(self):
        """Help > Project on GitHub and pyproject must point at one place."""
        from pdfarranger_qt import PROJECT_URL

        self.assertEqual(self.pyproject()["project"]["urls"]["Homepage"], PROJECT_URL)

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
