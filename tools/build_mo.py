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

"""Compile ``po/*.po`` into the ``build/mo`` tree the application reads.

Run from the repository root::

    python tools/build_mo.py            # every language
    python tools/build_mo.py de fr      # just these

Output goes to ``build/mo/<lang>/LC_MESSAGES/pdfarranger.mo``, which is the
development location ``i18n.locale_dirs()`` looks in after ``share/locale``.

Uses Babel rather than a `msgfmt` binary, because GNU gettext tools are not
generally present on Windows and this has to work on the machine the port is
being developed on.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_DIR = os.path.join(ROOT, "po")
OUT_DIR = os.path.join(ROOT, "build", "mo")
DOMAIN = "pdfarranger"


def compile_catalogue(language: str, verbose: bool = True) -> int:
    """Compile one language. Returns the number of translated messages."""
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po

    source = os.path.join(PO_DIR, f"{language}.po")
    with open(source, encoding="utf-8") as handle:
        catalogue = read_po(handle, locale=language, domain=DOMAIN)

    target_dir = os.path.join(OUT_DIR, language, "LC_MESSAGES")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, f"{DOMAIN}.mo")
    with open(target, "wb") as handle:
        write_mo(handle, catalogue)

    translated = sum(1 for message in catalogue
                     if message.id and message.string and not message.fuzzy)
    if verbose:
        print(f"  {language:<12} {translated:>4} messages -> "
              f"{os.path.relpath(target, ROOT)}")
    return translated


def available_languages():
    return sorted(name[:-3] for name in os.listdir(PO_DIR) if name.endswith(".po"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("languages", nargs="*",
                        help="languages to build (default: all in po/)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    languages = args.languages or available_languages()
    if not args.quiet:
        print(f"Compiling {len(languages)} catalogue(s) into "
              f"{os.path.relpath(OUT_DIR, ROOT)}")
    total = 0
    failed = []
    for language in languages:
        try:
            total += compile_catalogue(language, verbose=not args.quiet)
        except (OSError, ValueError) as error:
            failed.append(f"{language}: {error}")
    if not args.quiet:
        print(f"{total} translated messages in {len(languages) - len(failed)} "
              f"catalogue(s)")
    for problem in failed:
        print(f"FAILED {problem}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
