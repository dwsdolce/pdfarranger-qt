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

"""The recently-opened files list.

Kept apart from the window so the ordering and de-duplication rules can be
tested without building a UI. Paths are stored absolute and normalised;
comparison is case-insensitive on Windows, where ``C:\\A.pdf`` and ``c:\\a.pdf``
are the same file and would otherwise both accumulate in the list.
"""

import os
from typing import List

#: How many entries to keep. Ten is the usual convention, and the menu
#: numbers them 1-9 then 0.
MAX_ENTRIES = 10

SETTINGS_KEY = "recent/files"


def _key(path: str) -> str:
    """Comparison key: absolute, normalised, and case-folded where the OS is."""
    resolved = os.path.normpath(os.path.abspath(path))
    return os.path.normcase(resolved)


class RecentFiles:
    """An ordered, de-duplicated, capped list of paths backed by QSettings."""

    def __init__(self, settings, max_entries: int = MAX_ENTRIES):
        self.settings = settings
        self.max_entries = max_entries

    def paths(self) -> List[str]:
        """Most recently opened first."""
        stored = self.settings.value(SETTINGS_KEY, [])
        if isinstance(stored, str):  # QSettings collapses a one-item list
            stored = [stored]
        return [p for p in (stored or []) if p]

    def _store(self, paths: List[str]):
        self.settings.setValue(SETTINGS_KEY, paths[: self.max_entries])

    def add(self, path: str):
        """Put a path at the top, removing any earlier mention of it."""
        if not path:
            return
        resolved = os.path.normpath(os.path.abspath(path))
        target = _key(resolved)
        kept = [p for p in self.paths() if _key(p) != target]
        self._store([resolved] + kept)

    def remove(self, path: str):
        target = _key(path)
        self._store([p for p in self.paths() if _key(p) != target])

    def clear(self):
        self.settings.remove(SETTINGS_KEY)

    def prune_missing(self) -> List[str]:
        """Drop entries whose file has gone. Returns the paths removed.

        Not called on every menu build: hitting the filesystem for ten paths
        each time the File menu opens would stall on a disconnected network
        drive, which is exactly where stale entries come from.
        """
        present, gone = [], []
        for path in self.paths():
            (present if os.path.isfile(path) else gone).append(path)
        if gone:
            self._store(present)
        return gone
