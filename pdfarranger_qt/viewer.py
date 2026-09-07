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

"""How a viewer should open the document.

Three separate things in the PDF catalogue, which readers treat as one setting:

- ``/PageMode`` — what panel is showing: nothing, bookmarks, thumbnails
- ``/PageLayout`` — one page, continuous, or two up
- ``/ViewerPreferences`` — a dictionary of hints, of which the ones anybody
  acts on are hiding the toolbar and menu bar, centring the window, and
  showing the document's title instead of its filename

A document that says nothing is the common case and stays the default: every
value here is optional, and an unset one is removed rather than written as a
default, so opening and saving a file does not silently give it opinions it
did not have.

This pairs with D20. Having made the outline editable, "open with the
bookmarks showing" is the setting that makes an authored outline visible
without the reader hunting for it.
"""

import dataclasses
from typing import Optional

import pikepdf

from .i18n import gettext_ as _

#: ``/PageMode`` values worth offering, with how to describe them. Attachments
#: and full-screen are omitted deliberately: the first is rare, and the second
#: is a hostile thing to do to someone opening a file.
PAGE_MODES = [
    (None, lambda: _("Viewer default")),
    ("UseNone", lambda: _("No side panel")),
    ("UseOutlines", lambda: _("Bookmarks panel")),
    ("UseThumbs", lambda: _("Page thumbnails")),
]

#: ``/PageLayout`` values. The "first page on the right" variants are the ones
#: that matter for a book, where page 1 is a right-hand page.
PAGE_LAYOUTS = [
    (None, lambda: _("Viewer default")),
    ("SinglePage", lambda: _("One page at a time")),
    ("OneColumn", lambda: _("Continuous scroll")),
    ("TwoColumnLeft", lambda: _("Two pages, odd on the left")),
    ("TwoColumnRight", lambda: _("Two pages, odd on the right")),
    ("TwoPageLeft", lambda: _("Facing pages, odd on the left")),
    ("TwoPageRight", lambda: _("Facing pages, odd on the right")),
]

#: The ``/ViewerPreferences`` booleans readers actually honour.
FLAGS = [
    ("HideToolbar", lambda: _("Hide the viewer's toolbar")),
    ("HideMenubar", lambda: _("Hide the viewer's menu bar")),
    ("CenterWindow", lambda: _("Centre the window on screen")),
    ("DisplayDocTitle", lambda: _("Show the title rather than the filename")),
]


@dataclasses.dataclass
class Preferences:
    """What the document asks a viewer to do when it is opened."""

    page_mode: Optional[str] = None
    page_layout: Optional[str] = None
    #: Only the flags that are switched *on*; an absent one means "not set",
    #: which is not the same as False and is written as an absence.
    flags: frozenset = frozenset()

    def is_empty(self) -> bool:
        """True when the document expresses no preference at all."""
        return (self.page_mode is None and self.page_layout is None
                and not self.flags)

    # -- reading -----------------------------------------------------------

    @classmethod
    def read(cls, pdf) -> "Preferences":
        """What a document already asks for."""
        root = pdf.Root
        mode = root.get(pikepdf.Name.PageMode)
        layout = root.get(pikepdf.Name.PageLayout)
        prefs = root.get(pikepdf.Name.ViewerPreferences)
        flags = set()
        if isinstance(prefs, pikepdf.Dictionary):
            for name, _label in FLAGS:
                value = prefs.get(pikepdf.Name("/" + name))
                # Only an explicit true counts; the default for all of these is
                # false, so an absent key is not a preference.
                if value is True:
                    flags.add(name)
        return cls(
            page_mode=str(mode).lstrip("/") if mode is not None else None,
            page_layout=str(layout).lstrip("/") if layout is not None else None,
            flags=frozenset(flags),
        )

    # -- writing -----------------------------------------------------------

    def write(self, pdf) -> None:
        """Apply to a document being saved, removing what is not asked for.

        Removal matters: a document that had `/PageMode /UseOutlines` and has
        had it turned off must lose the key, not keep it with a different
        value, or the setting could never be cleared.
        """
        root = pdf.Root
        self._set_or_remove(root, pikepdf.Name.PageMode, self.page_mode)
        self._set_or_remove(root, pikepdf.Name.PageLayout, self.page_layout)

        if not self.flags:
            if pikepdf.Name.ViewerPreferences in root:
                del root[pikepdf.Name.ViewerPreferences]
            return
        prefs = root.get(pikepdf.Name.ViewerPreferences)
        if not isinstance(prefs, pikepdf.Dictionary):
            prefs = pikepdf.Dictionary()
            root[pikepdf.Name.ViewerPreferences] = prefs
        for name, _label in FLAGS:
            key = pikepdf.Name("/" + name)
            if name in self.flags:
                prefs[key] = True
            elif key in prefs:
                del prefs[key]

    @staticmethod
    def _set_or_remove(root, key, value) -> None:
        if value:
            root[key] = pikepdf.Name("/" + value)
        elif key in root:
            del root[key]
