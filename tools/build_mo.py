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

**This refuses to compile catalogues that have rotted**, and that is
deliberate. Every packaging script, the PyInstaller spec and both CI workflows
already run this one command, so it is the only place a single check reaches
both a local build and CI -- and it is the last moment before a half-empty
catalogue is sealed into an installer. Both faults the packaging workflow was
written for shipped, and one of them was exactly unreachable catalogues.

Two things stop a build:

- **a string in the source that never reached the template.** Caught at the
  commit that added it rather than whenever somebody next regenerates, which
  is the whole point; the cost is that adding a `_("...")` now means running
  `update_pot.py` in the same change.
- **a catalogue that is not fully translated.** All 33 stood at 426 of 426
  when this landed, so "complete" is a real invariant rather than an
  aspiration. Adding a msgid breaks every catalogue at once, which is the
  intended pressure: the string and its translations arrive together.

`--allow-drift` turns both into warnings, for the obvious case of wanting a
binary while a change is half-finished. Nothing in CI or in `packaging/` passes
it, so the override is local and visible in the command that used it. It is on
trial: if it proves too restrictive in practice the coverage half is the part
to soften first, to a floor per language rather than completeness.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO_DIR = os.path.join(ROOT, "po")
TEMPLATE = os.path.join(PO_DIR, "pdfarranger.pot")

#: Spelled out because a literal newline inside an f-string is a syntax
#: error and the escape is easy to lose to a shell heredoc.
NEWLINE = chr(10)
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


def _messages(catalog):
    """Every msgid, a plural pair reduced to its singular.

    Same reduction `update_pot.messages` makes, and for the same reason: a
    plural id is a tuple, and a set holding both tuples and strings will not
    sort.
    """
    return {m.id[0] if isinstance(m.id, tuple) else m.id for m in catalog if m.id}


def strings_missing_from_the_template():
    """Msgids the source asks for that `po/pdfarranger.pot` does not carry."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import update_pot
    from babel.messages.pofile import read_po

    wanted = _messages(update_pot.build())
    if not os.path.exists(TEMPLATE):
        return sorted(wanted)
    with open(TEMPLATE, encoding="utf-8") as handle:
        return sorted(wanted - _messages(read_po(handle)))


def gaps(language):
    """`(missing, untranslated)` for one catalogue, against the template.

    Missing means the template has a msgid and the catalogue has no entry for
    it at all -- a sync has not been run. Untranslated means the entry is
    there and empty.
    """
    from babel.messages.pofile import read_po

    if not os.path.exists(TEMPLATE):
        return 0, 0
    with open(TEMPLATE, encoding="utf-8") as handle:
        wanted = _messages(read_po(handle))
    with open(os.path.join(PO_DIR, f"{language}.po"), encoding="utf-8") as handle:
        catalogue = read_po(handle)

    have, empty = set(), 0
    for message in catalogue:
        if not message.id:
            continue
        have.add(message.id[0] if isinstance(message.id, tuple) else message.id)
        string = message.string
        blank = not any(string) if isinstance(string, (list, tuple)) else not string
        if blank:
            empty += 1
    return len(wanted - have), empty


def rot(languages):
    """Why these catalogues must not be compiled, or an empty list."""
    complaints = []

    absent = strings_missing_from_the_template()
    if absent:
        shown = ", ".join(repr(m) for m in absent[:3])
        complaints.append(
            f"{len(absent)} string(s) in the source never reached "
            f"po/pdfarranger.pot: {shown}"
            f"{', …' if len(absent) > 3 else ''}"
            + NEWLINE + "    fix: python tools/update_pot.py")

    short = []
    for language in languages:
        missing, empty = gaps(language)
        if missing or empty:
            short.append(f"{language} ({missing} absent, {empty} untranslated)")
    if short:
        complaints.append(
            f"{len(short)} catalogue(s) are not fully translated: "
            + ", ".join(short[:6])
            + (", …" if len(short) > 6 else "")
            + NEWLINE
            + "    fix: python tools/merge_translations.py <lang> --sync, "
              "then fill it")
    return complaints


def available_languages():
    return sorted(name[:-3] for name in os.listdir(PO_DIR) if name.endswith(".po"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("languages", nargs="*",
                        help="languages to build (default: all in po/)")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--allow-drift", action="store_true",
                        help="report rot instead of refusing to build "
                             "(never passed by CI or packaging/)")
    args = parser.parse_args(argv)

    languages = args.languages or available_languages()

    # The gate. Only the languages actually being compiled are checked, so
    # `build_mo.py de` while working on German does not fail over Georgian --
    # every real build passes no arguments and therefore checks all 33.
    complaints = rot(languages)
    if complaints:
        label = "WARNING" if args.allow_drift else "REFUSING TO BUILD"
        for complaint in complaints:
            print(f"{label}: {complaint}", file=sys.stderr)
        if not args.allow_drift:
            print("  pass --allow-drift to compile anyway", file=sys.stderr)
            return 1

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
