# Annotations

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

## The shape of the work

Four bodies of work, in the order that makes each one useful on its own. The
trackable items belong in a tracking issue rather than here, per
[README.md](README.md); what follows is the reasoning for the order.

**Showing what is in the file.** The render flag, form values flattened into the
copy the renderer opens, and `/AcroForm` preserved on export. These are one
change in spirit — the application currently does not show what the document
says — and the export half can cost a user data today. This is worth doing
whatever is decided about authoring, and it is the floor for calling the
application a reader.

Flattening for display interacts with D19, which has read mode open the source
file directly when nothing has been edited. That fast path would need the
flattened copy too, which partly undoes what D19 bought. Whether to flatten
always, flatten only when the document has widgets with values, or cache the
flattened copy is an open question and is the one piece of this wave that is not
obvious.

**Filling fields.** Tick boxes first, since they need no appearance generation
and cover most of a real form; then single-line text at an explicit size. This
is where the model work lands: field values have to be owned the way D20 owns
the outline, so that filling is undoable and is written on save.

**Markup.** Highlight, note, strikethrough, free text and freehand. A larger
piece than it sounds — it needs an annotation model, a tool mode in the canvas,
and appearance generation per annotation type — and it is the part D17 was right
to be wary of. It should not start until filling has proved the model.

**The rest of the reader.** An attachments panel, signature status, a thumbnail
panel while reading, view-only rotation, a dark mode. Wanted, but none of it is
a correctness problem and the user has ranked it below authoring.

### Settled

**Filling a field is an edit to the document.** It goes on the undo stack, marks
the document modified and is written on save, exactly as rotating a page is.
That is what Acrobat does and it is the only model that does not require the
user to hold two ideas about what "save" means.

The consequence has to be designed for rather than discovered: every edit
currently invalidates the reader's snapshot, which is rebuilt in full. Ten
highlights on an eighty-page document would mean ten full rebuilds. Annotation
and field edits need a narrower invalidation path than a page edit, because they
change what is drawn on a page without changing which pages exist.

### Still open

- Whether to flatten always or conditionally, and what that does to D19.
- Whether `/AcroForm` is carried across only when the output has a single source
  document — merging two forms is genuinely ambiguous — and what the user is
  told in the ambiguous case.
- Whether a signed document refuses field editing outright or warns. Signature
  *validation* is out, but noticing `/SigFlags` and declining to invalidate
  somebody's signature silently is a guard, not a feature.
- Whether this application's name still describes it. Not part of this work, but
  it is the same premise change, and D1 and D13 deliberately pinned the
  `QSettings` scope so that a rename cannot orphan saved state. A rename would
  also move the macOS bundle identifier, which carries the Finder association.

## What stays out

Unchanged from D21, and reaffirmed rather than revisited: converting to and from
other formats, OCR, redaction, document comparison, portfolios, and editing page
text — which is Tier 2 on the real definition, and stays out for the reason the
definition gives.

Added to that list by this analysis:

- **Signature validation.** Certificate chains and trust stores are a
  cryptographic sub-project, and a half-built one that says "valid" when it
  means "parsed" is worse than silence.
- **XFA**, which is a different form technology that happens to live in PDF
  files, is deprecated by its own vendor, and is not present here.
- **JavaScript in forms.** Real forms carry format, validate and calculate
  scripts. Not running them is a visible gap; running some of them is an
  invisible one, where a total silently fails to update. Of the two, the visible
  gap is the safer failure.
- **Read aloud, split view, loupe and measuring tools**, which were considered
  and ranked below everything above.

## Decisions this needs

D17 and D21 both need superseding, and the numbers stay with them — they are
identifiers, not positions. What replaces them should record the two arguments
separately, because they are independent and one of them survives even if the
goal changes back: that the yardstick is now a reader rather than a converter,
and that filling a field was never Tier 2 on the definition the project uses.
