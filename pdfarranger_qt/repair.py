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

"""Rewrite a damaged PDF so other software will read it.

Every save already goes through qpdf, which rebuilds the cross-reference table
and object streams on the way out -- so opening a broken file in this
application and saving it has always repaired it. What was missing was any way
to *say* so, or to do it without arranging the pages first.

The damage is found by opening twice. pikepdf recovers silently by default: a
file with a corrupt cross-reference table opens, reports the right page count
and warns about nothing at all. Opening with ``attempt_recovery=False`` is what
makes it admit the problem, and the exception carries qpdf's description of it.

There is no ``Pdf.check()`` in pikepdf 10 to ask instead; this was measured
rather than assumed.
"""

import dataclasses
from typing import Optional

import pikepdf

from .i18n import gettext_ as _


@dataclasses.dataclass
class Diagnosis:
    """What was found when the file was opened."""

    #: False when the file cannot be read even with recovery. Nothing can be
    #: done for it here.
    readable: bool
    #: True when a strict read failed and a recovering read succeeded -- that
    #: is, the file is damaged but salvageable.
    needed_recovery: bool
    pages: int = 0
    #: qpdf's account of the damage, or of why the file could not be read.
    detail: str = ""

    def summary(self) -> str:
        if not self.readable:
            return _("This file cannot be read, even with recovery.")
        if not self.needed_recovery:
            return _("No damage found; the file reads cleanly.")
        return _("Damaged, and recoverable.")


def diagnose(path: str, password: str = "") -> Diagnosis:
    """Open ``path`` strictly, then leniently, and report the difference."""
    strict_error = ""
    try:
        with pikepdf.open(path, password=password, attempt_recovery=False):
            pass
        strict_ok = True
    except Exception as exc:  # noqa: BLE001 - any failure means "not strictly readable"
        strict_ok = False
        strict_error = str(exc)

    try:
        with pikepdf.open(path, password=password) as pdf:
            pages = len(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - unreadable even with recovery
        return Diagnosis(readable=False, needed_recovery=True, detail=str(exc))

    return Diagnosis(readable=True, needed_recovery=not strict_ok, pages=pages,
                     detail="" if strict_ok else strict_error)


def repair(path: str, out_path: str, password: str = "",
           linearize: bool = False) -> Diagnosis:
    """Write a clean copy of ``path`` to ``out_path``.

    Returns what was wrong with the original. Raises if it cannot be read at
    all, because there is then nothing to write.
    """
    found = diagnose(path, password)
    if not found.readable:
        raise pikepdf.PdfError(found.detail or _("The file cannot be read."))
    with pikepdf.open(path, password=password) as pdf:
        kwargs = {"linearize": True} if linearize else {}
        pdf.save(out_path, **kwargs)
    return found


def is_linearized(path: str, password: str = "") -> Optional[bool]:
    """Whether the file is already laid out for byte-serving, or None if unread."""
    try:
        with pikepdf.open(path, password=password) as pdf:
            return pdf.is_linearized
    except Exception:  # noqa: BLE001 - the caller only wants a hint
        return None
