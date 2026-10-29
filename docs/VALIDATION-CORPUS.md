# Validation corpus

Real PDFs this application has been checked against, as links rather than
files. Nothing here is committed: the files are fetched into `corpus/`, which
is ignored.

**Why links.** A committed binary hides what it is testing. Every fixture in
this project is built in code for that reason — `tests/test_forms.py` makes a
radio group with a widget on each of two pages, and the thirty lines that build
it say exactly what the case is. Licensing is the second reason: most PDFs
worth testing against are not ours to redistribute. These are United States
federal forms, which are public domain as works of the US government.

**What this is for, and what it is not.** A fixture built from the
specification is what finds a case nobody has sent you — the cross-page field
below was found that way, not here. A corpus of real files tells you whether
you are wrong about the real world: which cases actually occur, how often, and
from which producers. The two are not substitutes, and neither is a regression
test. Regression tests live in `tests/`; this is a measurement, re-run by hand
when something about form handling changes.

## Fetching

    mkdir -p corpus && cd corpus
    curl -LO https://www.irs.gov/pub/irs-pdf/fw9.pdf
    …

Three of the URLs tried while assembling this returned 403 or 404; a government
form moves. The hash is how you tell whether the file behind a link is still
the one that was measured.

## The files

| File | Pages | Producer | Exercises | SHA-256 (first 16) |
|---|---|---|---|---|
| [fw9.pdf](https://www.irs.gov/pub/irs-pdf/fw9.pdf) | 6 | Designer 6.5 | XFA hybrid; 15 text fields with no appearance, 8 buttons with one | `2d420cbb4123dcf1` |
| [fw4.pdf](https://www.irs.gov/pub/irs-pdf/fw4.pdf) | 5 | Designer 6.5 | XFA hybrid; deep field tree | `92444d8856ce55d9` |
| [f1040.pdf](https://www.irs.gov/pub/irs-pdf/f1040.pdf) | 2 | Designer 6.5 | XFA hybrid; 199 widgets under one root field, tree five deep | `3d31c226df0d189c` |
| [f1099msc.pdf](https://www.irs.gov/pub/irs-pdf/f1099msc.pdf) | 6 | Designer 6.5 | XFA hybrid; 164 text fields, none with an appearance | `38051fe1cdce8fac` |
| [i-9.pdf](https://www.uscis.gov/sites/default/files/document/forms/i-9.pdf) | 4 | Acrobat Distiller 23.0 | **a field whose widgets span pages**; duplicate qualified names; 10 auto-sized fields | `780f348c34df694b` |
| [sf3107.pdf](https://www.opm.gov/forms/pdf_fill/sf3107.pdf) | 14 | Acrobat Distiller 7.0.5 | 470 fields, one widget each; 30 auto-sized; encrypted | `849fb67a65a37171` |
| [sf86.pdf](https://www.opm.gov/forms/pdf_fill/sf86.pdf) | 136 | LiveCycle Designer 11.0 | 6,852 widgets; 1,053 **radio** buttons; `/FT` two levels above the widget | `973e23e3ba1e30ef` |
| [vba-21-526ez-are.pdf](https://www.vba.va.gov/pubs/forms/VBA-21-526EZ-ARE.pdf) | 15 | Designer 6.5 | 3 **signature** fields; 66 radios | `48d87f2b679f61e4` |
| [ao239.pdf](https://www.uscourts.gov/sites/default/files/ao239.pdf) | 5 | Acrobat Distiller 11.0 | 68 fields, 196 widgets — many widgets per field | `670a3dbe41546b78` |

Checked 2026-10-29. All nine round-trip this application's export with their
field and widget counts unchanged — including sf86's 6,852 widgets — and none
produces a spurious warning.

### The signed sample, which is not here

None of the nine is signed, and a signature cannot be fetched from a link: a
public form is published *unsigned*, because signing is what the recipient
does. So the one genuinely signed document measured for this work — a 43-page
DocuSign envelope — is a private document. It stays in `corpus/`, which is
ignored, it is **not published and not described here**, and what was learned
from it is in [ANNOTATIONS.md](ANNOTATIONS.md) as structure only: an approval
signature with no `/Perms`, `/SigFlags 3`, a `/DSS` in an appended revision,
and no fillable field anywhere in it.

It is held as a set of five, none of them published:

| sample | signature | permission | what it is for |
|---|---|---|---|
| e-signed envelope, as delivered | approval | none | a `/DSS` revision appended after signing; a `/ByteRange` that does not reach the end of the file |
| the same, signed version | approval | none | self-consistent: the signature covers the whole file |
| certified form | certification | **`P=1`** | the locked case, and `/Perms /DocMDP` detection |
| the same, re-saved by Acrobat | certification | `P=1` | proof that a conforming save is a byte-for-byte copy |
| a marked-up copy | none | — | a flattened form, and a genuine `/Stamp` that read as a phantom field |

It is held as a pair. Acrobat's *View Signed Version* writes out the revision
the signature covers, which is the delivered file truncated at the end of its
`/ByteRange` — so the second file is self-consistent where the first is not,
and the two together cover both the appended-revision case and the plain one.

That last part is why the hunt continues. A document that is signed *and*
fillable is the case the fill guard needs, and it is not a thing governments
publish. Where real files run out, the answer is a generated fixture with real
cryptography — a self-signed certificate over a form built in code — which can
cover what no corpus will: certification at each `/DocMDP` level, and a `/Lock`
that names its fields.

## Coverage

    python tools/form_coverage.py corpus/*.pdf

"Are there enough files?" is otherwise a matter of taste. The form part of the
specification is a closed list — four field types, seventeen `/Ff` bits, a
handful of appearance shapes, three alignments — so it can be enumerated and
the files measured against it. These nine cover **35 of 47 cells (74%)**.

The tool measures the corpus, not this application: a covered cell means a real
file contains that construct, not that anything here handles it.

It also found its own bug, which is worth recording because it is the shape of
mistake this kind of tool invites. `/FT` is inherited, and in a deep tree sits
on neither the widget nor the root but somewhere between — sf86 keeps it two
levels up, under three naming subforms. Reading it off the root reported 1,053
radio buttons as typeless and showed the commonest button in the specification
as uncovered. A coverage number is only as good as the walk behind it.

**What is still uncovered**, after deliberately going looking for the gaps:

- `/NeedAppearances` — see below; nine files, four producers, never set.
- Untitled fields, rollover appearances, hidden fields, required, no-export,
  radios-in-unison, password, file-select, rich text, sorted and multi-select
  choice lists.

Those are better met by fixtures than by hunting files: `tests/test_forms.py`
already builds a radio group and a hidden field, which is two of them. A
fixture states what the case is in thirty readable lines; a file that happens
to contain it does not.

## What it told us

Measured across the six, against assumptions drawn from a single filled
insurance form — which had agreed with every one of them.

**A field really does span pages.** `i-9.pdf` has one, and two names used by
more than one widget. The insurance form has none: all 82 of its fields sit on
a single page. Export used to split such a field in two, so selecting one
option of a radio group stopped clearing the other. Fixed before this corpus
existed, but this is where it would have been caught.

**A value belongs to the field, not to the page.** Follows from the above, and
settles how field values are keyed: by source document and fully qualified
name, never by page. No file here has an untitled field, so a name is always
available, and within a document the qualified names behave as PDF says —
where two widgets share one, they are one field with one value.

**An empty text field usually has no appearance stream at all.** 0 of 164 in
`f1099msc.pdf`, 0 of 43 in `fw4.pdf`, 3 of 126 in `f1040.pdf`. Buttons always
have one — 73 of 73, 15 of 15 — because a tick box needs a drawing per state.
So filling a text field means *generating* an appearance from nothing, which is
the normal case rather than an edge case. The insurance form suggested
otherwise: its filled fields all had appearances, because Acrobat had written
them when they were filled.

**Auto-sized fields are a real minority.** `/DA` with a size of `0` means fit
the text to the box, which needs font metrics: 10 of 130 in `i-9.pdf`, 30 of
470 in `sf3107.pdf`, none in the Designer forms, none in the insurance form.
Six to eight per cent, so text filling cannot simply refuse them.

**`/DA` carries colour as well as font and size**, and is inherited from an
ancestor rather than sitting on the widget:
`/HelveticaLTStd-Bold 8.00 Tf 0.000 0.000 0.502 rg` — dark blue, in a font that
has to be resolvable from `/DR`. A generated appearance that ignores the colour
writes black text into a form that expects blue.

**`/NeedAppearances` is never set.** Not in any of the nine, from four
producers. The flag tells a viewer it must generate the appearance streams
itself, and its absence means a real form expects the appearances to be there
already — so filling a field and *not* generating one leaves it blank in a
conforming viewer. Generation is mandatory, not a nicety.

The inverse is worth keeping in mind as a fallback: this application could
*set* the flag on a document it has filled but could not draw accurately — an
auto-sized field needing font metrics it does not have — so that a viewer which
honours it repairs the gap. That is a decision for the work that writes values,
not an assumption to make now.

**Five of the nine are XFA hybrids**, all from Adobe Designer. XFA is out of
scope, and these still carry a working AcroForm layer, so they display and
round-trip. The open question is what happens when one is *filled*: a viewer
that prefers the XFA layer may show an empty form while the AcroForm holds the
value. Nothing here answers that; it is a question for the work that writes
values.
