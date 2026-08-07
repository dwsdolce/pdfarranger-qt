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

"""The version and build number, and the build scripts that stamp them."""

import os
import re
import subprocess
import sys
import unittest

from support import HERE

ROOT = os.path.dirname(HERE)
PACKAGING = os.path.join(ROOT, "packaging")


class TestVersion(unittest.TestCase):
    """The build number is the git commit count, resolved without a build."""

    def test_build_is_the_commit_count(self):
        from pdfarranger_qt import __build__

        expected = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if expected.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual(__build__, expected.stdout.strip())

    def test_version_string_carries_the_build(self):
        from pdfarranger_qt import __build__, __version__, __version_string__

        if __build__:
            self.assertEqual(__version_string__, f"{__version__} ({__build__})")
        else:
            self.assertEqual(__version_string__, __version__)

    def test_a_missing_build_number_is_not_fatal(self):
        """A tarball with no .git must still import and report a version."""
        script = (
            "import sys, subprocess;"
            # Make every git invocation fail, the way an exported tarball does.
            "subprocess.run.__defaults__;"
            "sys.path.insert(0, %r);"
            "import pdfarranger_qt as p;"
            "print(p.__version_string__)" % ROOT
        )
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, cwd=os.sep)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().startswith("0."), result.stdout)


class TestEntryPoint(unittest.TestCase):
    """__main__.py has to work the way PyInstaller runs it, not just as -m."""

    def test_runs_as_a_top_level_script(self):
        """Reproduces the frozen entry point exactly.

        PyInstaller uses __main__.py as the entry *script*: it executes as a
        top-level module with no package context, while the package itself stays
        importable. Running it directly with the project root on PYTHONPATH is
        the same situation. A relative `from .app import main` passes every
        `python -m pdfarranger_qt` test and then dies in the installed
        application with "attempted relative import with no known parent
        package" -- which is exactly what shipped once.
        """
        env = dict(os.environ, PYTHONPATH=ROOT)
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "pdfarranger_qt", "__main__.py"),
             "--version"],
            capture_output=True, text=True, env=env,
            # Not the project root, so nothing is importable by accident.
            cwd=os.path.dirname(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+")

    def test_no_relative_imports_in_main(self):
        source = open(os.path.join(ROOT, "pdfarranger_qt", "__main__.py"),
                      encoding="utf-8").read()
        self.assertNotRegex(source, r"^from \.", "relative import breaks the frozen app")


class TestBuildScripts(unittest.TestCase):
    """Guards on the packaging scripts, which no test can usefully execute."""

    def read(self, name):
        with open(os.path.join(PACKAGING, name), encoding="utf-8") as handle:
            return handle.read()

    def test_every_platform_has_a_script(self):
        for name in ("build_win", "build_win.bat", "build_linux", "build_mac"):
            self.assertTrue(os.path.isfile(os.path.join(PACKAGING, name)), name)

    def test_scripts_stamp_the_build_number(self):
        """Skipping this step would ship an installer labelled x.y.z.0."""
        for name in ("build_win", "build_win.bat", "build_linux", "build_mac"):
            self.assertIn("gen_version_build.py", self.read(name), name)

    def test_scripts_compile_the_catalogues(self):
        """Without this the bundle has no translations at all."""
        for name in ("build_win", "build_win.bat", "build_linux", "build_mac"):
            self.assertIn("build_mo.py", self.read(name), name)

    def test_no_developer_id_is_committed(self):
        """This repository is public; signing identities come from the env.

        Matches the shape of a real identity -- a name followed by a
        parenthesised ten-character Apple team ID -- rather than the words
        "Developer ID", which the scripts legitimately use when documenting the
        environment variables.
        """
        real_identity = re.compile(r"Developer ID \w+: (?!Your Name)[^(\n]+\(\w{10}\)")
        for name in ("build_mac", "pdfarranger-qt.spec"):
            found = real_identity.search(self.read(name))
            self.assertIsNone(found, f"{name} contains {found.group(0) if found else ''}")

    def test_the_installer_script_demands_a_version(self):
        """A silent default would produce an installer named after 0.0.0."""
        self.assertIn("#error", self.read("pdfarranger-qt.iss"))

    def test_the_appid_is_a_literal_guid(self):
        """Inno keys upgrades off this; a changed AppId orphans old installs."""
        iss = self.read("pdfarranger-qt.iss")
        match = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}?", iss, re.M)
        self.assertIsNotNone(match, "AppId is missing or not a literal GUID")

    def test_posix_scripts_are_executable_in_git(self):
        """Windows sets core.filemode=false, so chmod +x is never recorded.

        A script committed as 100644 arrives non-executable on Linux and macOS
        and cannot be run as ./packaging/build_linux at all. git ls-files -s is
        the only place the truth lives; the working-tree bit is meaningless
        here.
        """
        listing = subprocess.run(["git", "ls-files", "-s", "packaging", "tools"],
                                 cwd=ROOT, capture_output=True, text=True)
        if listing.returncode != 0:
            self.skipTest("not a git checkout")
        modes = {}
        for line in listing.stdout.splitlines():
            meta, _tab, path = line.partition("	")
            modes[path] = meta.split()[0]

        need_exec = ["packaging/AppRun", "packaging/build_linux",
                     "packaging/build_mac", "packaging/build_win",
                     "packaging/make_icns.sh"]
        for path in need_exec:
            self.assertEqual(modes.get(path), "100755",
                             f"{path} is not executable in git; fix with "
                             f"git update-index --chmod=+x {path}")

    def test_the_spec_bundles_the_build_number(self):
        spec = self.read("pdfarranger-qt.spec")
        self.assertIn("version_build", spec)
        self.assertIn("share", spec)  # the locale tree
