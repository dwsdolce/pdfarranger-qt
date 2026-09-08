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

"""Merge generated translations into a catalogue, without touching human work.

Run from the repository root::

    python tools/merge_translations.py de --sync
    python tools/merge_translations.py de --from build/translations/de.json
    python tools/merge_translations.py de --from ... --dry-run

Nothing hand-writes a ``.po``. Escaping and plural arrays are where that goes
quietly wrong, and a broken catalogue is a language that silently does nothing
for people who cannot read the language it broke in.

**--sync comes first, and usually matters more than the fill.** A catalogue
holds only the messages somebody once put in it: German has 238 of the
template's 427, so two thirds of the interface is not merely untranslated
there, it is *absent*, and there is nothing for a translation to attach to.
Syncing adds what the template has and retires what it no longer mentions, the
way ``msgmerge`` would.

Three rules, from D22:

**Human translation always wins.** Only an empty message is ever filled. A
string somebody wrote is never replaced, reworded or reordered -- which is why
Lumenman's Russian was merged before any of this ran.

**Every generated entry says so**, as a translator comment. That makes *show me
the unreviewed Russian* a grep, and a native-speaker review pass something that
can be started and finished rather than merely intended.

**``Last-Translator`` is left alone.** It names a person; machine output does
not go under their name. ``X-Generator`` records what actually did the work.

The input is ``{msgid: translation}``, with a list for a plural::

    {"_Open": "Öffnen", "%d page selected": ["...", "...", "..."]}

Candidates are checked before they are written -- placeholders must survive, a
plural must have the number of forms the locale declares, and an accelerator in
the msgid must still be there. A translation that fails is reported and
dropped, not written and left for the guards to find later.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PO = os.path.join(ROOT, "po")
TEMPLATE = os.path.join(PO, "pdfarranger.pot")

#: Marks a generated entry. Deliberately plain text: it has to survive a
#: round trip through every .po editor anybody might open the file with.
MARK = "machine translation, unreviewed"

#: What this writes into the catalogue header.
GENERATOR = "pdfarranger-qt tools/merge_translations.py"

#: A real format placeholder. The space flag is excluded on purpose: with it,
#: "% of height" parses as a %o conversion. See tests/test_catalogues.py.
SPEC = re.compile(r"%(?:\([^)]+\))?[-#0+]*[0-9*]*(?:\.[0-9*]+)?[hlL]?[diouxXeEfFgGcrsa%]")

MNEMONIC = re.compile(r"_[A-Za-z]")


def load(path):
    from babel.messages.pofile import read_po

    with open(path, encoding="utf-8") as handle:
        return read_po(handle)


def header_fields(text):
    """The `"Name: value"` lines of a catalogue header, in order."""
    fields = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("msgid") and fields:
            break
        if stripped.startswith('"') and ":" in stripped:
            name = stripped[1:].split(":", 1)[0]
            if name.replace("-", "").isalnum():
                fields.append((name, stripped))
    return fields


def save(catalog, path, original):
    """Write the catalogue, keeping the header fields babel does not model.

    ``write_po`` rebuilds the header from the fields it knows about, and
    silently drops the rest -- ``X-Generator`` among them, which is exactly the
    field this tool has to set. So the header is repaired afterwards rather
    than trusted.
    """
    import io as _io

    from babel.messages.pofile import write_po

    buffer = _io.BytesIO()
    # Line numbers are left out for the same reason the template leaves them
    # out: they move on every edit and bury the real change.
    write_po(buffer, catalog, include_lineno=False, width=79,
             sort_output=False, ignore_obsolete=False)
    text = buffer.getvalue().decode("utf-8")

    kept = dict(header_fields(original))
    present = {name for name, _line in header_fields(text)}
    restore = [line for name, line in kept.items()
               if name not in present and name.lower().startswith("x-")
               and name.lower() != "x-generator"]
    # A literal backslash-n, which is how a .po header ends every field.
    generator = '"X-Generator: ' + GENERATOR + chr(92) + 'n"'

    lines, done = text.splitlines(), False
    for index, line in enumerate(lines):
        if not done and line.strip().startswith('"Content-Transfer-Encoding'):
            lines[index] = "\n".join([line] + restore + [generator])
            done = True
    if not done:
        raise AssertionError("no Content-Transfer-Encoding line to anchor to")

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def is_empty(message) -> bool:
    got = list(message.string) if isinstance(message.string, tuple) else [message.string]
    return not any(got)


def problems(message, translation, nplurals):
    """Why this translation must not be written, or an empty list."""
    ids = list(message.id) if isinstance(message.id, tuple) else [message.id]
    forms = translation if isinstance(translation, list) else [translation]
    out = []

    if isinstance(message.id, tuple):
        if len(forms) != nplurals:
            out.append(f"{len(forms)} plural forms, the locale declares {nplurals}")
    elif len(forms) != 1:
        out.append("a list of forms for a message that has no plural")

    if not all(isinstance(f, str) and f.strip() for f in forms):
        out.append("empty or non-text")

    want = set(SPEC.findall(" ".join(ids)))
    for form in forms:
        if isinstance(form, str) and set(SPEC.findall(form)) != want:
            out.append(f"placeholders {sorted(want)} became "
                       f"{sorted(set(SPEC.findall(form)))}")
            break

    if MNEMONIC.search(ids[0]) and isinstance(forms[0], str) and "_" not in forms[0]:
        out.append("the accelerator was dropped")
    return out


def sync(catalog, template):
    """Add what the template has and retire what it no longer mentions."""
    before = {m.id for m in catalog if m.id}
    catalog.update(template, no_fuzzy_matching=True, update_header_comment=False)
    after = {m.id for m in catalog if m.id}
    return len(after - before), len(before - after)


def fill(catalog, translations):
    """Write the translations that are allowed to be written."""
    written, refused, occupied, unknown = 0, [], 0, []
    known = {}
    for message in catalog:
        if not message.id:
            continue
        key = message.id[0] if isinstance(message.id, tuple) else message.id
        known[key] = message

    for key, value in translations.items():
        message = known.get(key)
        if message is None:
            unknown.append(key)
            continue
        if not is_empty(message):
            occupied += 1
            continue
        bad = problems(message, value, catalog.num_plurals)
        if bad:
            refused.append((key, "; ".join(bad)))
            continue
        message.string = tuple(value) if isinstance(value, list) else value
        if MARK not in message.user_comments:
            message.user_comments = list(message.user_comments) + [MARK]
        written += 1
    return written, refused, occupied, unknown


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("language", help="the catalogue to merge into, e.g. de")
    parser.add_argument("--from", dest="source", metavar="FILE",
                        help="JSON of {msgid: translation}")
    parser.add_argument("--sync", action="store_true",
                        help="bring the catalogue up to the template first")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, and write nothing")
    args = parser.parse_args(argv)

    path = os.path.join(PO, f"{args.language}.po")
    if not os.path.isfile(path):
        sys.exit(f"no catalogue at {os.path.relpath(path, ROOT)}")
    original = open(path, encoding="utf-8").read()
    try:
        catalog = load(path)
    except ImportError:
        sys.exit('merge_translations: babel is required - pip install -e ".[dev]"')

    if args.sync:
        added, retired = sync(catalog, load(TEMPLATE))
        print(f"sync: {added} messages added, {retired} retired")

    if args.source:
        with open(args.source, encoding="utf-8") as handle:
            translations = json.load(handle)
        written, refused, occupied, unknown = fill(catalog, translations)
        print(f"fill: {written} written, {occupied} already translated "
              f"(left alone), {len(refused)} refused, {len(unknown)} unknown")
        for key, why in refused[:20]:
            print(f"  refused {key!r}: {why}")
        for key in unknown[:10]:
            print(f"  not in the catalogue: {key!r}")

    if not args.sync and not args.source:
        sys.exit("nothing to do: pass --sync, --from, or both")

    if args.dry_run:
        print("dry run: nothing written")
        return 0

    # X-Generator records what did the work. Last-Translator is left exactly as
    # it was: it names a person, and this is not their work.
    save(catalog, path, original)
    print(f"wrote {os.path.relpath(path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
