# Annotations

**Issue:** [#14](https://github.com/dwsdolce/pdfarranger-qt/issues/14)

**Status:** IN PROGRESS — body 1 **complete**, body 2 at six of nine. Tick
boxes and single-line text fields can both be filled in; what is typed shows,
survives undo and reaches the saved file with a drawing for it. Only the guard
against filling a signed document, the export strip and the save guard are
left before markup.

A filled insurance form was opened in this application and came up blank. Every
answer typed into it was missing — text, ticks, the lot — with nothing on screen
to say anything had been left out. The same file in Acrobat shows all of it.

This document is the analysis of why, and what it would take to not only show
what the file says but let the user write it. It argues for reversing two
standing decisions, D17 and D21, and says what should replace them.

The unifying fact, which is what makes this one subject rather than two: **a
form field is an annotation**. A text box, a tick box and a highlighter stroke
are all entries in a page's `/Annots` array, differing by `/Subtype`. They are
drawn the same way, from an appearance stream. Showing a filled form and showing
a colleague's comments are the same problem, and filling a field and adding a
highlight are the same problem a second time.

## Where this stands

| | State |
|---|---|
| 1. Show what is in the file | **complete** — drawn, saved, printed, and measured against real forms |
| 2. Fill fields | in progress — six of nine; the signed-document guard, the export strip and the save guard are left |
| 3. Markup | after filling, which proves the model it needs |

The first was correctness and needed no decision reversed: the application did
not draw what the document said, and damaged a form on save. Both were bugs
under the scope as it stood. The other two are features, and the decisions that
forbade them are superseded by this document's own — see *Decisions*, below.

Reader features that came up in the same conversation — attachments, signature
status, a thumbnail panel, view-only rotation, dark mode — are
[Issue #15](https://github.com/dwsdolce/pdfarranger-qt/issues/15); they have
nothing to do with annotations.

What "complete" means for the first, concretely: a filled form that displayed
blank now shows all of it. Measured on the four-page insurance form that
prompted this, through the application's own reader -- 15 of 15 filled fields
on its third page draw, and a ticked box carries four times the ink of an
unticked one.

## What the renderer leaves out

Three kinds of content in a PDF are invisible in this application today, and
none of them announces itself.

**No annotation of any kind is drawn.** `QPdfDocumentRenderOptions` has a
`RenderFlag.Annotations`; the renderer sets rotation and nothing else. So
highlights, sticky notes, stamps, strikethrough and freehand drawing are all
silently dropped. A document someone has commented on arrives looking pristine.

**Form field values are not drawn either**, and that one does not yield to the
flag. PDFium excludes widget annotations from page rendering by design — it
renders the page, then leaves form fields to its form-fill module
(`FPDFDOC_InitFormFillEnvironment` and `FPDF_FFLDraw`), which QtPdf never
initialises and does not expose. Measured on one blank page carrying one
annotation with the same blue-box appearance stream, differing only in
`/Subtype`:

| `/Subtype` | without the flag | with `RenderFlag.Annotations` |
|---|---|---|
| `/Square` | 0 blue pixels | 5000 blue pixels |
| `/Widget` | 0 blue pixels | **0 blue pixels** |

The flag does reach PDFium — `RenderFlag.Grayscale` changes the rendered image
and `RenderFlag.Annotations` does not change it by a single pixel. So widgets
are not an oversight on Qt's part; they are PDFium's documented division of
labour, and it is a division QtPdf only implements half of.

**Attachments are invisible.** Nothing in the source touches `/EmbeddedFiles`.
A PDF can carry files; Acrobat shows a paperclip; this shows nothing.

### And one that loses data rather than hiding it

Export builds a fresh document with `pikepdf.Pdf.new()` and copies pages into
it. The widget annotations come across on the page; the `/AcroForm` dictionary
they belong to does not, because nothing copies it. Measured on the form that
prompted all this:

| | `/AcroForm` | `/Fields` | widgets | with a value |
|---|---|---|---|---|
| original | present | 82 | 86 | 23 |
| after our export | **absent** | **0** | 86 | 23 |

pikepdf says so out loud while it happens: *"86 form widget annotation(s) that
are not reachable from `/AcroForm`; they may not display in Adobe Acrobat."*
The values survive inside the annotation dictionaries, so this is not silent
data loss — but `/Fields`, `/DR` and `/DA` are gone, the fields stop being
interactive, and the form may stop displaying in the application it was made
for. Saving a completed form through this application degrades it.

That is a bug under any scope, including the scope as it stands today. It wants
fixing whatever is decided below.

## Why this was ruled out, and what changed

Two decisions cover this ground and both say no.

**D17, annotation and markup** — *"Out of scope, permanently. Tier 2 by another
name. Qt exposes no annotation authoring, and adding it would mean owning an
annotation model, hit-testing and appearance-stream generation."*

**D21, which of PDF24's tools belong here** — *"Invoices, job applications and
fillable forms are document authoring — Tier 2 under another name."*

Two things have changed since those were written, one about the goal and one
about the cost.

### The yardstick moved

D21 reasons from PDF24: *"PDF24 Toolbox is named in the port's goal as the
reason this project exists, so its list is the yardstick — and most of what it
does is not what this is."* That was sound when the comparison was against a
collection of conversion tools.

The application is now being used as a primary PDF reader, in place of both
Acrobat and PDF24, and the standard asked of it is a high-quality Acrobat Reader
replacement that also carries the arranging features. Against that yardstick the
three omissions above are not missing features. They are a reader that does not
show what is in the file.

This is less of a reversal than it looks. The scope boundary in
[PORTING-NOTES.md](PORTING-NOTES.md) already admits reading on exactly this
reasoning — Tier 3 is in scope *"because the Acrobat-like model in the
background note above means opening a document and reading it, not only
rearranging it."* Showing the whole document is the same argument applied to the
same premise.

### The tier classification was wrong

The more interesting point is that D17 and D21 both file this under Tier 2, and
on the definition in [PORTING-NOTES.md](PORTING-NOTES.md) it does not belong
there. Tier 2 is *"content-level editing (retype text, move graphics, reflow)"*,
and it is out of scope for a stated reason: *"PDF has no concept of paragraphs
or text flow, only glyphs at coordinates with subset fonts."*

That reason does not apply to a form field. A field is a first-class PDF object
with a defined value, a defined rectangle, a defined font and a defined
appearance stream. Filling one writes a string into `/V` and generates a short
appearance — there is no paragraph model to invent, no reflow, no subset-font
surgery, nothing reconstructed. It is manipulation of well-defined PDF objects,
which is what Tier 1 is.

The same holds for markup. A highlight is a dictionary with a rectangle and an
appearance stream; adding one does not touch page content at all.

So the exclusion rests on the cost argument in D17 rather than the tier
argument, and the cost argument is now out of date by three pieces of machinery
the project has built since:

- **Hit-testing and coordinate mapping.** Text selection needed a point on
  screen turned into a position on a page and back. `PageCanvas` has it.
- **An owned model that survives undo.** D20 settled how the outline is owned in
  the undo state beside the page list, keyed by a stable page id so that
  reordering costs nothing. Form state needs the same treatment and now has a
  worked precedent rather than a design problem.
- **Appearance-stream generation**, which D17 named as an obstacle and which has
  since been demonstrated. See below.

None of that was true when D17 was written. The decision was right on the
information it had.

## What a form actually needs

Surveyed on the form that prompted this — four pages, 82 fields, 86 widgets, 23
already filled, `/NeedAppearances` absent and every value-bearing field carrying
a real appearance stream:

| kind | count | what it takes |
|---|---|---|
| `/Btn` tick boxes | 58 | `/V` and `/AS` set to the state name |
| `/Tx` text fields | 26 | a generated appearance stream |
| `/Sig` signature | 2 | leave alone |

**Two thirds of that form needs no appearance generation at all.** A tick box
already carries an appearance for each of its states — `{/Off, /Yes}`, or named
states for a radio group. Ticking it is setting `/V` on the field and `/AS` on
the widget to the state's name; the drawing already exists in the file.

The text fields are the easy end of the generated case: every one is
single-line, left-aligned (`/Q` absent), with an explicit size in its `/DA`
(`/MinionPro-Regular 12 Tf`) and no `/MaxLen`, so no comb cells. Left-aligned
text at a fixed size needs no font metrics — the appearance is
`BT /MinionPro-Regular 12 Tf 0 g 2 <baseline> Td (text) Tj ET`, and the font is
already in the form's `/DR`.

Demonstrated end to end on a scratch copy: a value written to an empty field, a
77-byte appearance generated for it, the appearances flattened into page
content, and the result rendered by this application's own renderer — 0 ink in
that field's rectangle before, 4814 after, reading correctly in the form's own
embedded font. A tick box set the same way went from 0 to 278.

### Where it gets hard

None of these occur in the form at hand, which is luck rather than
representativeness:

- **Auto-size** — a `/DA` with size `0` means fit the text to the box, which
  needs real font metrics. Worth noting the form's *default* `/DA` is
  `/Helv 0 Tf`; the fields override it, but plenty of forms will not.
- **Centre and right alignment** (`/Q` 1 and 2) need string widths, so metrics
  again. Two of the three `/DR` fonts here are the standard-14 — `/Helv` and
  `/ZaDb` — which are not embedded, so their metrics have to come from built-in
  tables rather than the file.
- **Multiline wrapping**, **comb fields**, **choice and list boxes**.
- **A baseline that is right rather than close.** The demonstration used
  `(height − size × 0.72) / 2 + size × 0.18`, which looks correct at 12pt in a
  26pt box and is a fudge. Acrobat derives it from the font's ascent and
  descent, which means reading the `/FontDescriptor`.

## Plan

Three bodies of work. Each step is useful on its own, and the risky ones come
after the model they depend on is proved.

### 1. Show what is in the file

Correctness, not a feature: the application did not draw what the document said,
and damaged a form on save.

| # | Step | State |
|---|---|---|
| 1.1 | Draw annotations — the render flag, in all three render paths | **complete** |
| 1.2 | Rebuild `/AcroForm` on export, so a saved form keeps its fields | **complete** |
| 1.3 | Draw form fields | **complete** — from a render-only copy, until 2.3 made the reader composite them instead |
| 1.4 | Draw both in the output paths — printing, image export, rasterising | **complete** |
| 1.5 | Stop export splitting a field whose widgets span pages | **complete** |
| 1.6 | A validation corpus: public PDFs this has been checked against | **complete** |

1.5 is a defect found by building the fixture 1.1–1.4 were never tested
against. A radio group with a widget on each of two pages comes out of export as
*two* fields: `_append_page` copies each page's `/Annots` through its own
temporary document, so the shared parent is copied once per page. The group
stops behaving as one, and the merge warning fires on a document nobody merged.
The splitting is old — it is how upstream stopped duplicated pages sharing an
annotation — and only became visible when `/AcroForm` started being rebuilt.
Filling makes it worse: a value written to a field split in two reaches half of
it.

1.6 is the other half of the lesson, and it changed three assumptions this
document had made from a single form — see
[VALIDATION-CORPUS.md](VALIDATION-CORPUS.md) for the measurements. An empty text
field usually has **no** appearance stream at all (0 of 164 in one form), so
2.5 generates one from nothing rather than editing one. Auto-sized fields are 6
to 8% of real forms, so 2.5 cannot simply refuse them. And `/DA` carries colour
as well as font and size, inherited from an ancestor, so a generated appearance
that ignores it writes black into a form expecting blue.

A fourth, from going after the gaps the coverage tool named:
`/NeedAppearances` is set in none of the nine, from four producers. The flag
tells a viewer to generate the appearances itself, so its absence means a
filled field without one is blank in a conforming viewer — generation is
mandatory for 2.5, not a nicety. The inverse is a fallback worth remembering:
setting the flag on a document we have filled but could not draw accurately,
an auto-sized field being the case, lets a viewer that honours it repair the
gap. That is 2.5's decision to take, not an assumption to make now. A fixture built from the specification is
what finds a case like 1.5; a corpus of real files is what says whether we are
wrong about the real world, and the two are not substitutes. The corpus is a
*document* listing public PDFs — a US federal form is public domain, most others
are not — each with what it exercises, a hash, and what was observed when. Links
rather than files: a committed binary hides what it is testing, which is why
every fixture in this project is built in code. It is standing reference, not
part of this work, so it will live beside `FINDINGS.md` once it has entries.

1.4 was missed when 1.1–1.3 landed, and is the reason to distrust "display
works" as a finishing condition: everything that leaves as pixels goes through
`raster.render_pages`, which built the real export and rendered it with no
options, so the form printed blank — none of the fifteen answers on page three.

Two things about how this was done differ from what was first proposed here.

*Not flattened.* Stamping the appearance into the page content stream is the
obvious implementation and it is wrong. An appearance is placed by transforming
its BBox by its Matrix and fitting the result to the annotation's Rect; of the
74 appearances in the form that prompted this, **every one had a Matrix and 45
had a BBox that did not match the Rect** — one 18.2pt tall in an 11.5pt box. A
translate to the corner of the Rect draws 61% of them at the wrong size.
Rewriting `/Subtype` from `/Widget` to `/Stamp` leaves the placement to PDFium,
which already implements the rule, and is three times faster.

*Conditional for display, unconditional for output.* The rewritten copy is built
only for a document that has fields, and only when one is first wanted, so D19's
fast entry into read mode is untouched. In `render_pages` the same rewrite is
applied every time: 4 ms with nothing to do and 10 ms with, against 95 ms to
render four pages at 300 dpi — below the noise of the render it precedes, and
cheaper than a flag every caller has to remember.

### 2. Fill fields

| # | Step | Depends on | Done when | State |
|---|---|---|---|---|
| 2.1 | Own field values in the model | — | a value survives undo, redo and a page reorder | **complete** |
| 2.2 | Find the field under a click | — | clicking a widget identifies its field; clicking elsewhere does not | **complete** |
| 2.3 | Tick boxes | 2.1, 2.2 | clicking one toggles it on screen and after a save | **complete** |
| 2.4 | Write values on save | 2.1 | a saved file opens in Acrobat with the value in the field | **complete** |
| 2.5 | Text fields, single-line, explicit size | 2.1, 2.2, 2.4 | typing shows, survives undo, and saves | **complete** |
| 2.6 | Narrow the snapshot invalidation | — | ten fills do not rebuild the reader ten times | **complete** with 2.3, by leaving nothing to rebuild |
| 2.7 | Refuse to fill a field in a signed document | 2.3 | a signed form says why rather than invalidating a signature | next |
| 2.8 | Strip the remains of a signature on export | -- | a derived document is honestly unsigned instead of claiming a signature over bytes that are gone | |
| 2.9 | Refuse to save over a signed source, and say the signature will not carry | 2.7, 2.8 | Save on a signed document offers Save As; a derived save says the signature is gone | |

**2.1 has a precedent.** D20 settled how the outline is owned in the undo state
beside the page list, keyed by a stable page id so reordering costs nothing and
a deleted page leaves its entries dangling rather than destroyed. Field values
want the same treatment, keyed by the page uid plus the field's fully qualified
name.

**2.3 before 2.5** because a tick box carries an appearance for every state
already, so setting `/V` and `/AS` is the whole of it — 58 of 86 widgets on the
form that prompted this, with nothing generated. A text field needs an
appearance built, which is different work.

**2.4 before 2.5** so that writing is proved on the values that need no
generation. A tick that saves correctly means the export path is right; adding
text then only has to get the drawing right.

**Where the baseline came from.** Acrobat had filled a field in the form that
prompted this work, so what it wrote could simply be read: a 25.2pt box at 12pt
in a font of ascent 989 and descent -360 put the baseline at 8.826, and
`(height - (ascent - descent) x size) / 2 - descent x size` gives 8.826 exactly.
An earlier sketch used `(height - size x 0.72) / 2 + size x 0.18`, which looks
right at one size and drifts at every other.

**Typing goes into a real editor**, a `QLineEdit` over the field, which is what
pdf.js does with its annotation layer of HTML inputs. Nothing is generated per
keystroke -- the appearance is made once, on commit -- and selection, the
clipboard, input methods and right-to-left text are the editor's problem rather
than something to rebuild on top of an appearance stream.

**A value the file never drew is drawn too.** Most text fields in real forms
carry no appearance at all: 0 of 164 in one corpus form, 3 of 126 in another.
Showing nothing for those would be the very fault this work began with, so a
drawing is generated whenever the file lacks one -- not only when the field has
been typed into.

**2.6 was answered by changing where the fields are drawn**, which is worth
more than narrowing the invalidation would have been. Form fields are no longer
baked into the document the reader opens; they are composited over the page
from state held in memory, so a tick invalidates nothing at all. The page
bitmap does not change — only which appearance is drawn on top of it.

That is also how every other implementation does it. PDFium renders a page
*without* its form fields in `FPDF_RenderPageBitmap` and draws them afterwards
in `FPDF_FFLDraw`, from a form-fill environment holding the state; QtPdf calls
the first and not the second, which is why a filled form came up blank here.
pdf.js puts an annotation layer of real HTML inputs over a rendered canvas.
Acrobat regenerates appearances on commit, not per keystroke.

The measurement that forced it: changing a value in the file costs 1 ms, and
re-saving the document to show it costs 682 ms on sf86.pdf. A tick could just
about afford that; a keystroke cannot, and 2.5 is typing. Compositing costs
0.4 ms per appearance, cached by appearance and size, and a tick box's drawings
are shared -- sf86's 2,846 buttons have a handful of distinct images between
them.

### 3. Markup

Not started, and not before 2 has proved the model: it needs the same ownership,
the same undo behaviour and the same save path.

| # | Step | Depends on | Done when | State |
|---|---|---|---|---|
| 3.1 | An annotation model | 2.1, 2.4 | an added note survives undo and a save | |
| 3.2 | A tool mode in the canvas | 3.1 | the pointer selects, highlights or draws as chosen | |
| 3.3 | Highlight and strikethrough | 3.2 | a selection becomes a mark the file keeps | |
| 3.4 | Sticky note | 3.2 | a note can be placed, read and edited | |
| 3.5 | Free text and freehand | 3.3, 3.4 | both draw, save and reopen | |

Highlight first of the marks because its geometry already exists — text
selection produces the quadrilaterals a `/Highlight` wants, so it needs no new
hit-testing. Freehand last because it is the only one whose appearance is not
derived from something already on the page.

### Not here

**Reader features** — attachments, signature status, a thumbnail panel, view-only
rotation, dark mode — are [Issue #15](https://github.com/dwsdolce/pdfarranger-qt/issues/15).
They came up in the same conversation as this work but have nothing to do with
annotations.

**A flatten command** was considered and dropped. It is an Acrobat *Pro* feature,
not a Reader one — Reader saves a filled form with its fields intact and reaches
the same end by printing to PDF — so it is out by the same line that excludes
OCR, redaction and compare. The reason it looked necessary was that a recipient
might not see the answers, and the application was itself that recipient until
step 1.4; printing now carries them.

### What a signed form means, and what Acrobat does with one

Acrobat has four behaviours here, not one, and which one you get is state this
application does not currently read:

- **An unsigned signature field** locks nothing. It is a placeholder for a
  future signer, so the form fills normally.
- **An approval signature** (a `/Sig` field with a `/V`, no certification)
  restricts nothing either. Acrobat keeps filling fields and saves
  *incrementally*, appending a revision so the signature stays valid over the
  bytes it covers; the Signatures panel then reports it as valid but modified
  since signing, and offers to show the signed version.
- **A certification signature**, `/Perms /DocMDP`, carries the permission level:
  `P=1` no changes, `P=2` form filling and signing, `P=3` filling, signing and
  annotation. Acrobat makes the fields uneditable where the level forbids it.
- **A field-level lock**, `/Lock` on a signature field (FieldMDP), makes the
  named fields read-only once that field is signed.

So Acrobat refuses at the *field* when permissions forbid the edit, and
otherwise permits it and keeps the signature by appending rather than
rewriting. qpdf, under pikepdf, always rewrites, so the second half is not
available here at any permission level.

Two measurements decide what "signed" has to mean in the code. **Nothing we
have is signed**: of the nine corpus forms and the insurance form that prompted
this work, none has a `/Sig` field carrying a `/V` and none has `/Perms
/DocMDP`. The insurance form's two signature fields are empty placeholders, and
its `/SigFlags 1` says only that signature fields exist. **And `/SigFlags` and
`/Perms` are both traps**: five corpus forms set `/SigFlags 2` (AppendOnly)
while having no signature field at all, and five carry `/Perms /UR3` -- a
usage-rights signature, which Reader-enables the form rather than attesting to
its content. Treating either as "signed" would refuse to fill the 1040, the
W-4, the W-9, the 1099-MISC and SF-3107. The test is a `/Sig` field with a
`/V`, or `/Perms /DocMDP`; nothing else.

**A real signed document, measured.** A 43-page DocuSign envelope, held
locally and deliberately not published (see
[VALIDATION-CORPUS.md](VALIDATION-CORPUS.md)). One signature field,
`adbe.pkcs7.detached` under `Adobe.PPKMS`, `/SigFlags 3` (SignaturesExist and
AppendOnly), and a `/DSS` carried in a revision appended *after* the signature
so that long-term validation data does not disturb the bytes it covers. The
important part is what it does **not** have: no `/Perms`, no DocMDP, no
`/Lock`. The commonest kind of signed document in existence carries an
*approval* signature, which restricts nothing -- so "signed" does not mean the
author forbade editing, and a rule phrased that way would be guessing at an
intent the file does not express.

**Acrobat, watched rather than described.** Opening that document shows a blue
bar reading only *"At least one signature requires validating"* -- no
certification banner, no permissions notice -- with **Edit and E-Sign both
enabled**. Acrobat does not lock a document carrying an approval signature.
Editing is disabled in exactly one place: *View Signed Version*, which says
*"You are currently viewing a signed version. All editing and interactive
features are disabled. Save a copy and reopen to edit this document."* That is
a historical revision being shown read-only, and Acrobat's own instruction for
how to proceed is to **derive a new document**. Adobe's answer to "may I
rearrange a signed form" is "yes, on a copy."

Saving that signed version also demonstrates the incremental-update model
exactly. The file Acrobat wrote is **byte-for-byte the first 1,809,095 bytes of
the original** -- the prefixes are identical -- which is the file truncated at
the end of the signature's `/ByteRange`:

| | as delivered | signed version |
| --- | --- | --- |
| bytes | 1,847,081 | 1,809,095 |
| revisions | 3 | 2 |
| `/DSS`, `/Extensions` | present | gone |
| `/ByteRange` covers | 1,809,095 of 1,847,081 | the whole file |

`/DSS` and `/Extensions` disappear because they existed only in the revision
appended after signing. Rolling back to the signed revision drops them without
disturbing a byte the signature covers, which is the whole point of appending
rather than rewriting. The two files are kept as a pair: the delivered one
tests the appended-revision case, and the extracted one is self-consistent --
its signature covers the entire file -- which makes it the better fixture for
detection and for proving the export strip.

Acrobat's Appearance Integrity Report on the same document returns 2013 (text
appearance may silently change), 4002 (content contains errors) and 4000
(unrecognized content), so the producer's output is structurally sloppy. Both
files parse here without complaint.

**A certified document, and the pair that settles the predicate.** A second
private sample, a two-page form put through Adobe Acrobat Sign, carries what
the first does not: `/Perms /DocMDP` with **`P = 1`, no changes permitted**.
Its certification covers the whole file in a single revision, and the one
field in the document is the invisible `ES_CERTIFYING_SIGNATURE` at
`/Rect [0 0 0 0]`. Acrobat's signature panel says "No changes are allowed" and
greys out Edit and E-Sign; on the approval-signed file it greys out nothing.

| | approval-signed | certified |
| --- | --- | --- |
| `/Perms` | none | `/DocMDP` |
| permission level | -- | **P=1, no changes** |
| `/ByteRange` | all but the appended `/DSS` revision | the whole file |
| Acrobat's Edit / E-Sign | enabled | greyed out |

Acrobat's behaviour tracks `/Perms /DocMDP` and its `P` value, not the mere
presence of a signature. So "a signature makes this read-only" and "the
author's permissions make this read-only" are not the same rule applied to
real files: one of these two documents is locked by its author and the other
is not.

**What a conforming tool does on save**, measured rather than assumed. Saving
that certified document from Acrobat produced a file **byte-for-byte identical
to the original** -- 513,598 bytes in, 513,598 out, every byte the same.
Acrobat did not re-serialise it: not a renumbered object, not a recompressed
stream. Together with the appended `/DSS` revision on the other sample, that
is the whole rule:

- a permitted change -> **append** a revision, leaving the signed bytes alone
- no change -> **copy the bytes**
- rebuild from scratch -> **never**

Export here only knows the third. That is why a signed document cannot survive
a save, and why 2.8's strip is not a workaround but the honest form of the one
thing this application can do.

**Exporting the certified file is worse than exporting the approval-signed
one.** `/Perms` is dropped, because it hangs off the document root and the
export builds a new one -- so the entry a viewer reads to find the
certification is gone -- while `/SigFlags 3` is carried across and the
signature field survives with its `/Reference` still declaring `DocMDP P=1`,
over a `/ByteRange` naming 513,598 bytes of a file that is nothing like that
size. The output is an incoherent half-certified document asserting that no
changes were permitted. Exporting the page the signature widget is *not* on
comes out clean, which is the same accident as before.

**Neither platform leaves a fillable field.** Acrobat Sign and DocuSign both
flatten the form before signing: one `/Sig` field each and nothing else. The
signed-*and*-fillable case does not occur in anything found, which settles that
it has to be a generated fixture.

It is also no use for testing the fill guard. The only field in its 43 pages is
the signature itself, invisible at `/Rect [0 0 0 0]`, and `FieldMap.read` finds
zero fields in it. A case that is both signed *and* fillable is a rarer animal
and still wanted.

**Export carries a corpse, and that is a bug under any rule.** Run through the
real export path, the signature field travels with its page, `_surviving_fields`
picks it up and `_restore_acroform` carries `/SigFlags` across:

| Exported | `/AcroForm` | `/SigFlags` | Signature | `/DSS` |
| --- | --- | --- | --- | --- |
| all 43 pages | rebuilt | `3` carried | survives; `/ByteRange` claims 1,809,095 bytes of a 1,563,238-byte file | dropped |
| pages 1-3 | rebuilt | `3` carried | survives, same `/ByteRange`, in a 691 KB file | dropped |
| pages 5-8 | none | none | gone | -- |

The output announces a signature over bytes that do not exist, keeps 32,767
bytes of PKCS#7 that cannot verify, and loses the `/DSS` that would let anyone
check -- and whether it lies at all depends on whether page 1 happened to be in
the selection. That is an accident, not a policy, and stripping the remains is
needed whichever way the arrange question goes. Step 2.8.

## Still open

- **Whether this application's name still describes it.** Not part of this work,
  but it is the same premise change, and D1 and D13 deliberately pinned the
  `QSettings` scope so a rename cannot orphan saved state. A rename would also
  move the macOS bundle identifier, which carries the Finder association.

## Decisions (owner, 2026-10-28)

Taken for this work and recorded with it. Numbered within this document, not in
the port's register — that closed at D25, and a decision taken for a piece of
work now lives with the work. Nothing in the source cites these by number; where
one of them matters to understanding the code, the fact is in the comment.

**1. Showing and authoring annotations and form fields are in scope.**
Superseding D17, which put annotation and markup out of scope *permanently*, and
D21, which named fillable forms as Tier 2 authoring. Two arguments, independent
of one another, and one of them survives even if the goal changes back.

*The yardstick moved.* D21 reasons from PDF24 — *"PDF24 Toolbox is named in the
port's goal as the reason this project exists, so its list is the yardstick"* —
and that is no longer what this is measured against. It is now a primary PDF
reader in place of Acrobat and PDF24 both, and against that a document whose
highlights, comments and filled-in answers are invisible is not a reader. The
scope boundary already admits reading on exactly this reasoning: Tier 3 is in
scope *"because the Acrobat-like model in the background note above means
opening a document and reading it, not only rearranging it"*.

*The Tier 2 classification was wrong.* Tier 2 is excluded because *"PDF has no
concept of paragraphs or text flow, only glyphs at coordinates with subset
fonts"*, and none of that describes a form field — a first-class object with a
defined value, rectangle, font and appearance stream. Filling one writes a
string into `/V` and generates a short appearance: no paragraph model invented,
no reflow, no subset-font surgery. That is manipulation of well-defined PDF
objects, which is Tier 1. A highlight is the same: a dictionary with a rectangle
and an appearance, touching no page content.

What is left of D17 is its cost argument — *"adding it would mean owning an
annotation model, hit-testing and appearance-stream generation"* — and that is
out of date by three things built since. Hit-testing and coordinate mapping
exist from text selection. D20 is a worked precedent for owning a model through
undo. Appearance generation is demonstrated above.

**What stays out is unchanged**: converting to and from other formats, OCR,
redaction, document comparison, portfolios, and editing page text, which is
Tier 2 on the real definition. Added to that list by this work: signature
*validation*, because a half-built trust store that says "valid" when it means
"parsed" is worse than silence; XFA, a different form technology deprecated by
its own vendor; and JavaScript in forms, where failing to run a calculation is a
visible gap and running some of them is an invisible one. And ranked out rather
than ruled out, after being weighed: read aloud, split view, a loupe and
measuring tools.

**2. Filling a field or adding a mark is a document edit.** On the undo stack,
marking the document modified, written on save — the same as rotating a page.
Acrobat's model, and the only one that does not ask the user to hold two ideas
about what saving means. A separate annotation layer with its own save semantics
buys nothing here: there is already one undo stack covering page order,
rotation, crop and the outline, and a second history that can disagree with the
first is what D20 exists to avoid.

The consequence is recorded with the decision rather than left to be found. An
edit invalidates the reader's snapshot, which is then rebuilt in full; ten
highlights on an eighty-page document would be ten full rebuilds. An annotation
edit changes what is drawn on a page without changing which pages exist, so it
needs a narrower invalidation path — which is why that is a numbered step of the
plan and not an optimisation to notice later.

Field values are owned the way D20 owns the outline: in the undo state beside
the page list, keyed by the page's stable uid plus the field's fully qualified
name, so reordering costs nothing and a deleted page leaves its values dangling
rather than destroyed.

**3. `/AcroForm` is rebuilt from the output, always, and a name clash is
reported.** Rebuilt rather than copied because the output is a different set of
pages: an export of a selection keeps only the widgets on the pages it kept, and
`/Fields` naming the others would point at annotations not in the document.
Always rather than only for a single source, because what merging cannot resolve
is narrower than it first appeared — two fields with the same name, which in PDF
are one field with two widgets, so typing in one changes the other. Acrobat
renames on import; this says so through the warning the save already has,
because renaming somebody's fields silently is a different surprise.

**4. The rewritten copy is for rendering only.** A document with form fields
gets a second temporary copy with `/Subtype` rewritten; export reads the real
one. A field drawn into a saved file is no longer a field, so `DocumentSet` has
two views of itself — `files_for_export` and `render_file` — and the tests hold
that line for an unedited document and for an edited one, which takes the other
path.

**5. A signature stops an edit in place, not the derivation of a new
document.** Taken on the evidence of the two signed samples rather than on the
principle that a signature means hands off, which the files do not support: one
of them carries an approval signature that restricts nothing and that Acrobat
leaves fully editable, and Acrobat's own instruction for editing a signed
document is *"Save a copy and reopen."* A blanket read-only rule would block
extracting three pages from a 43-page envelope whose signer never asked for
that protection, and this application's reason to exist is rearranging pages.

So the line is drawn where the harm is, which is leaving a broken signature
where a good one was -- not at whether the operation is a fill or a rearrange:

- **Filling a field** in a signed document is refused. It is always an edit in
  place, and the saved file would present itself as the same signed record
  with content that no longer verifies.
- **Arranging** is allowed, because export writes a new file and the signed
  original stays on disk untouched.
- **Saving over the signed source** is refused, and offers Save As instead.
  `save()` writes to `current_path` where `save_as()` prompts, so the two are
  already distinct.
- **The derived document is honestly unsigned.** The remains of the signature
  are stripped on export rather than carried, and the save says that the
  signature has not come across.

What is *not* claimed: that any of this preserves a signature. Nothing here
can, because qpdf rewrites and a signature survives only an append or a byte
copy. The decision is about which lie not to tell.

## Done

**2026-10-28 — body 1, steps 1.1 to 1.3.** Annotations drawn in all three render
paths; form fields visible through the rewritten copy; `/AcroForm` rebuilt
on export so a saved form keeps its fields. Verified on the four-page insurance
form that prompted the work: 15 of 15 filled fields on page three draw, a ticked
box carries four times the ink of an unticked one, and the form round-trips a
save with 82 fields, 86 widgets and 23 values intact. A Qt warning on every
document close was fixed alongside it, being in the same code.

**2026-10-28 — step 1.4.** The output paths were still blind: printing and image
export go through `raster.render_pages`, which rendered the real export with no
options, so the same form printed none of its fifteen answers. Now 15 of 15.
Found by asking whether a flatten command was worth having — it was not, and the
question exposed the gap it would have papered over.

**2026-10-29 — steps 2.1 to 2.3.** Field values are owned in the model, keyed
by source document and qualified name, and ride the undo stack beside the
outline. A click finds the field under it. Tick boxes fill in, undo, and reach
the saved file with `/V` on the field and `/AS` on every widget of it.

Form fields are now drawn as a layer over the page instead of being rewritten
into the document -- which supersedes how body 1 displayed them, for a reason
that is about 2.5 rather than 2.3: the state has to live in memory, because a
keystroke cannot cost a 682 ms re-save. The `/Subtype` rewrite stays where
there is no canvas to composite in: the grid's thumbnails and the output paths.

One bug of mine, worth the note: `QPdfDocument.load` has two overloads and the
one taking a device returns *void*. Comparing its result with `Error.None_`
therefore fails for every document ever loaded, silently, and the layer drew
nothing with nothing to say why. The existing code gets this right in all four
places it loads a document; only the new code had it wrong.

**2026-10-29 — steps 1.5 and 1.6.** Export no longer splits a field whose
widgets span pages; a real government form turned out to contain one. A
validation corpus of six public forms from three producers is recorded in
[VALIDATION-CORPUS.md](VALIDATION-CORPUS.md), and measuring it corrected three
assumptions body 2 would otherwise have been built on.

**2026-10-29 — the corpus, extended.** Nine forms from four producers, measured
against an enumeration of the specification's form surface by
`tools/form_coverage.py`: 35 of 47 cells, 74%. Three files were added to fill
named gaps rather than for bulk — a real radio group, signature fields, and a
form with many widgets per field. The tool found its own bug on the way: `/FT`
is inherited and can sit between the widget and the root, so reading it off the
root called 1,053 radio buttons typeless.

**2026-10-29 — a stamp is not a field.** `fields_in` accepted `/Stamp` as well
as `/Widget`, which was right while body 1 showed the reader the copy with the
widgets rewritten into stamps. The reader composites the fields itself now and
is handed the export or the source file, both carrying real widgets, so the
only thing that exception still caught was *genuine* stamp annotations. Two
documents in the corpus have one -- Apple's markup titles everything it writes
with the device's user name -- and each read as a phantom field called "Mobile
User". Harmless by luck in those two, whose stamp has a degenerate rectangle at
the integer limits and so falls under the two-pixel floor; with an ordinary
rectangle the annotation would be drawn twice, once by PDFium and once by the
field layer over the top, and a stamp sharing a real field's name would have
shared its value. Dropped from `apply_values` for the same reason, where it
cost nothing: the one caller that rewrites writes its values first.

**2026-10-29 — steps 2.4 and 2.5.** Single-line text fields can be filled in.
Typing goes into a real editor over the field and the appearance is generated
once, on commit, from the `/DA`'s font, size and colour, with the baseline rule
read out of one Acrobat had written rather than guessed at. A value reaches the
saved file with a drawing for it, and a value the file never drew gets one too,
which most text fields in the corpus need. Verified on the insurance form:
typed into an empty field, saw it, saved it, read back `/V` and a generated
`/AP`, and undo removed it.
