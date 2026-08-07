#!/usr/bin/env python3
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

"""Write the git commit count to ``pdfarranger_qt/version_build``.

The build number is `git rev-list --count HEAD` -- monotonic, needs nothing
typed by hand, and identifies the exact commit an installer was cut from.
Combined with the base version in ``pdfarranger_qt/__init__.py`` it gives the
four-part version Windows wants: 0.1.0.37.

The generated file is deliberately not committed. In a source checkout the
package asks git directly; the file exists only so a frozen build, which has no
git and no .git directory, can still report the number.

Usage:

    python tools/gen_version_build.py            # write the file
    python tools/gen_version_build.py --print    # also print the full version

One Python script rather than a .sh and a .bat, because the build runs from
both Git Bash and cmd and there is no reason for the two to drift.
"""

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Just the build number. Bundled into the frozen app and read back at runtime.
TARGET = ROOT / "pdfarranger_qt" / "version_build"

#: The full four-part version, read by packaging/pdfarranger-qt.iss.
#: A file rather than an ISCC /D argument because Git Bash rewrites anything
#: that looks like a Unix path, so /DMyAppVersion=... arrives mangled there
#: while the // escape that fixes it is passed through literally by Cygwin.
#: Neither shell touches a file.
INSTALLER_TARGET = ROOT / "build" / "installer_version"


def commit_count() -> str:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"gen_version_build: git rev-list failed - is this a git checkout?\n"
                 f"{result.stderr.strip()}")
    count = result.stdout.strip()
    if not count.isdigit():
        sys.exit(f"gen_version_build: unexpected git output {count!r}")
    return count


def base_version() -> str:
    """The version from the package, which is its single source."""
    source = (ROOT / "pdfarranger_qt" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', source, re.M)
    if not match:
        sys.exit("gen_version_build: no __version__ in pdfarranger_qt/__init__.py")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print", dest="show", action="store_true",
                        help="print the full version to stdout, nothing else")
    args = parser.parse_args()

    build = commit_count()
    # No trailing newline: the spec and the .iss both read these raw.
    TARGET.write_text(build, encoding="utf-8")

    full = f"{base_version()}.{build}"
    INSTALLER_TARGET.parent.mkdir(parents=True, exist_ok=True)
    INSTALLER_TARGET.write_text(full, encoding="utf-8")

    if args.show:
        print(full)
    else:
        print(f"gen_version_build: version_build = {build} (version {full})")


if __name__ == "__main__":
    main()
