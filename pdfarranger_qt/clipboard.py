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

"""The page clipboard format.

Byte-for-byte the GTK application's (decision D5), so the Qt and GTK versions can
copy and paste pages to each other while both exist. The payload is plain text::

    pdfarranger-clipboard\\n
    <sha256 of everything below>\\n
    <page>\\n;\\n<page>\\n;\\n...

Each page is ``///``-separated fields ending in zero or more 13-field layer
records -- see ``Page.serialize()``. The hash is not security, it guards against
a half-copied or re-wrapped payload being parsed as pages.

Note the references are *file paths* into the originating instance's temporary
directory, so a paste only resolves while that instance is still alive. That is
upstream behaviour, not an accident of this port.
"""

import hashlib
from typing import List, Optional, Tuple

MARKER = "pdfarranger-clipboard\n"
PAGE_SEPARATOR = "\n;\n"
FIELD_SEPARATOR = "///"
#: Fields per page before the layer records begin, and per layer record.
_PAGE_FIELDS = 13
_LAYER_FIELDS = 13

#: Drag-and-drop format name, matching the GTK application's target so that a
#: drag between a Qt and a GTK instance has at least a chance of being understood.
#: Its payload is the bare records -- no marker line, no hash.
MIME_PAGES = "MODEL_ROW_EXTERN"


def _records(pages) -> str:
    return PAGE_SEPARATOR.join(page.serialize() for page in pages)


def serialize(pages) -> str:
    """Render pages as clipboard text: marker, hash, then the records."""
    data = _records(pages)
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return MARKER + digest + "\n" + data


def serialize_for_drag(pages) -> str:
    """Render pages as a drag payload.

    Upstream's ``MODEL_ROW_EXTERN`` target carries ``copy_pages(add_hash=False)``
    -- the same records as the clipboard but with neither the marker nor the
    hash, because the drag target name already identifies the payload.
    """
    return _records(pages)


def is_page_data(text: str) -> bool:
    return bool(text) and text.startswith(MARKER)


def parse(text: str) -> Optional[List[tuple]]:
    """Parse clipboard text into page tuples, or None if it is not ours.

    Returns a list of
    ``(filename, npage, description, angle, scale, crop, hide, layerdata)``,
    matching what the GTK application's ``deserialize()`` produces.
    """
    if not is_page_data(text):
        return None
    body = text[len(MARKER):]
    newline = body.find("\n")
    if newline < 0:
        return None
    digest, data = body[:newline], body[newline + 1:]
    if hashlib.sha256(data.encode("utf-8")).hexdigest() != digest:
        return None
    return parse_records(data)


def parse_records(data: str) -> Optional[List[tuple]]:
    """Parse bare page records -- the drag payload, or the body of clipboard text."""
    if not data:
        return None
    entries = []
    for chunk in data.split(PAGE_SEPARATOR):
        if not chunk:
            continue
        parsed = _parse_page(chunk)
        if parsed is None:
            return None
        entries.append(parsed)
    return entries or None


def _parse_page(chunk: str) -> Optional[tuple]:
    field = chunk.split(FIELD_SEPARATOR)
    try:
        filename = field[0]
        npage = int(field[1])
        if len(field) < 3:
            # Short form, used only when interleaving whole files
            return (filename, npage)
        description = field[2]
        angle = int(field[3])
        scale = float(field[4])
        crop = [float(s) for s in field[5:9]]
        hide = [float(s) for s in field[9:13]]
        layerdata = []
        i = _PAGE_FIELDS
        while i < len(field):
            layerdata.append([
                field[i],                                   # filename
                int(field[i + 1]),                          # npage
                int(field[i + 2]),                          # angle
                float(field[i + 3]),                        # scale
                field[i + 4],                               # OVERLAY / UNDERLAY
                [float(s) for s in field[i + 5:i + 9]],     # crop
                [float(s) for s in field[i + 9:i + 13]],    # offset
            ])
            i += _LAYER_FIELDS
    except (IndexError, ValueError):
        return None
    return (filename, npage, description, angle, scale, crop, hide, layerdata)
