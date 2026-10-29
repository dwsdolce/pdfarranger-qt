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

## The files

| File | Pages | Producer | Exercises | SHA-256 (first 16) |
|---|---|---|---|---|
| [fw9.pdf](https://www.irs.gov/pub/irs-pdf/fw9.pdf) | 6 | Designer 6.5 | XFA hybrid; 15 text fields with no appearance, 8 buttons with one | `2d420cbb4123dcf1` |
| [fw4.pdf](https://www.irs.gov/pub/irs-pdf/fw4.pdf) | 5 | Designer 6.5 | XFA hybrid; deep field tree | `92444d8856ce55d9` |
| [f1040.pdf](https://www.irs.gov/pub/irs-pdf/f1040.pdf) | 2 | Designer 6.5 | XFA hybrid; 199 widgets under one root field, tree five deep | `3d31c226df0d189c` |
| [f1099msc.pdf](https://www.irs.gov/pub/irs-pdf/f1099msc.pdf) | 6 | Designer 6.5 | XFA hybrid; 164 text fields, none with an appearance | `38051fe1cdce8fac` |
| [i-9.pdf](https://www.uscis.gov/sites/default/files/document/forms/i-9.pdf) | 4 | Acrobat Distiller 23.0 | **a field whose widgets span pages**; duplicate qualified names; 10 auto-sized fields | `780f348c34df694b` |
| [sf3107.pdf](https://www.opm.gov/forms/pdf_fill/sf3107.pdf) | 14 | Acrobat Distiller 7.0.5 | 470 fields, one widget each; 30 auto-sized | `849fb67a65a37171` |

Checked 2026-10-29. All six round-trip this application's export with their
field and widget counts unchanged, and none produces a spurious warning.

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

**Four of the six are XFA hybrids**, all from Adobe Designer. XFA is out of
scope, and these still carry a working AcroForm layer, so they display and
round-trip. The open question is what happens when one is *filled*: a viewer
that prefers the XFA layer may show an empty form while the AcroForm holds the
value. Nothing here answers that; it is a question for the work that writes
values.
