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

"""Rebuild ``po/pdfarranger.pot`` from the strings this application asks for.

Run from the repository root::

    python tools/update_pot.py            # rewrite the template
    python tools/update_pot.py --check    # report drift, change nothing

The template that came with the port was upstream's: 243 msgids, every
reference pointing into ``pdfarranger/`` -- a package phase 5 deleted. So it
described a program that no longer exists, and none of this port's own strings
were in it. That is the mechanical half of why no catalogue covers more than a
third of the interface: a string that never reaches the template can never be
handed to a translator.

Babel rather than a ``xgettext`` binary, for the same reason ``build_mo.py``
uses it: GNU gettext tools are not generally present on Windows, and this has
to work on the machine the port is developed on. ``po/POTFILES.in`` is not
consulted -- it lists the GTK files -- the package is walked instead.

Keywords worth knowing about:

``_`` / ``gettext_``
    the ordinary case.
``_m`` / ``menu_label``
    a GTK-style label whose mnemonic is converted for Qt. Same msgid.
``ngettext``
    singular and plural, both extracted.
``N_``
    marks a string that is *translated somewhere else*, with ``_(variable)``.
    That call works at runtime and is invisible here, so without the mark the
    msgid never reaches the template. See `i18n.N_`.
"""

import argparse
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.join(ROOT, "pdfarranger_qt")
TEMPLATE = os.path.join(ROOT, "po", "pdfarranger.pot")

#: What counts as a translatable call, and which arguments hold the messages.
KEYWORDS = {
    "_": None,
    "_m": None,
    "N_": None,
    "gettext_": None,
    "menu_label": None,
    "ngettext": (1, 2),
    # The window builds its actions and menus through these, which take the
    # msgid rather than a translated string so that `retranslate` can produce
    # it again in another language. Without them here every menu label would
    # silently drop out of the template.
    "_action": None,
    "_menu": (2,),
}


def build():
    """The catalogue this application's source implies."""
    from babel.messages.catalog import Catalog
    from babel.messages.extract import extract_from_dir

    catalog = Catalog(
        project="pdfarranger-qt",
        copyright_holder="pdfarranger-qt contributors",
        msgid_bugs_address="https://github.com/dwsdolce/pdfarranger-qt/issues",
        charset="UTF-8",
        creation_date=datetime.datetime.now(datetime.timezone.utc),
    )
    for filename, lineno, message, comments, context in extract_from_dir(
            PACKAGE, keywords=KEYWORDS, method_map=[("**.py", "python")]):
        # Recorded relative to the repository root, so a reference reads the
        # same as the path a developer would open.
        where = os.path.join("pdfarranger_qt", filename).replace(os.sep, "/")
        catalog.add(message, locations=[(where, lineno)],
                    auto_comments=comments, context=context)
    return catalog


def write(catalog, path):
    from babel.messages.pofile import write_po

    with open(path, "wb") as handle:
        # No line numbers in the references: they move on every edit, which
        # turns an unrelated commit into a rewrite of the whole template and
        # buries the strings that actually changed.
        write_po(handle, catalog, include_lineno=False, width=79)


def messages(catalog):
    """Every msgid, with a plural pair reduced to its singular.

    A plural message's id is a (singular, plural) tuple, and mixing those with
    plain strings in one set makes it unsortable.
    """
    return {m.id[0] if isinstance(m.id, tuple) else m.id
            for m in catalog if m.id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report what would change, and write nothing")
    args = parser.parse_args(argv)

    try:
        catalog = build()
    except ImportError:
        sys.exit("update_pot: babel is required - pip install -e \".[dev]\"")

    wanted = messages(catalog)
    if os.path.exists(TEMPLATE):
        from babel.messages.pofile import read_po

        with open(TEMPLATE, encoding="utf-8") as handle:
            have = messages(read_po(handle))
    else:
        have = set()

    added, gone = sorted(wanted - have), sorted(have - wanted)
    print(f"{len(wanted)} messages in pdfarranger_qt/")
    if added:
        print(f"  {len(added)} not in the template yet, first few:")
        for message in added[:5]:
            print(f"    + {message!r}")
    if gone:
        print(f"  {len(gone)} in the template that nothing asks for any more")

    if args.check:
        # Drift is the normal state between releases, so this reports rather
        # than fails. It is a report for a person, not a gate for CI.
        return 0

    write(catalog, TEMPLATE)
    print(f"wrote {os.path.relpath(TEMPLATE, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
