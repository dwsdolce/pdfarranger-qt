# Annotations

**Issue:** [#14](https://github.com/dwsdolce/pdfarranger-qt/issues/14)

**Status:** IN PROGRESS — showing what is in the file is **complete**; filling
fields is next, and nothing blocks it.

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
| Showing what is in the file | **complete** — annotations drawn, form fields visible, `/AcroForm` kept on save |
| Filling fields | next; the plan is below and nothing blocks it |
| Markup | after filling, which proves the model it needs |
| The rest of the reader | last; ranked below authoring |

The first is pure correctness and needed no decision reversed: the application
was not showing what the document said, and was damaging a form on save. Both
were bugs under the scope as it stood.

The other three are features, and the decisions that forbade them are now
superseded — **D26** puts showing and authoring annotations and form fields in
scope, and **D27** settles that filling a field is a document edit. The case
that led to both is argued below; what remains is work.

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

## The shape of the work

Four bodies of work, in the order that makes each one useful on its own. The
trackable items belong in a tracking issue rather than here, per
[README.md](README.md); what follows is the reasoning for the order.

**Showing what is in the file** — **complete**. The render flag, form fields
made visible, and `/AcroForm` preserved on export. These were one change in
spirit — the application did not show what the document said — and the export
half could cost a user data. Worth doing whatever is decided about authoring,
and the floor for calling the application a reader.

Two things about how it was done differ from what this document first proposed.

*Not flattened.* Stamping the appearance into the page content stream is the
obvious implementation and it is wrong. An appearance is placed by transforming
its BBox by its Matrix and fitting the result to the annotation's Rect; of the
74 appearances in the form that prompted this, **every one had a Matrix and 45
had a BBox that did not match the Rect** — one 18.2pt tall in an 11.5pt box. A
translate to the corner of the Rect, which is what the obvious code does, draws
61% of them at the wrong size. Rewriting `/Subtype` from `/Widget` to `/Stamp`
instead leaves the placement to PDFium, which already implements the rule. It is
also three times faster and leaves the file size unchanged.

*Conditional, so D19 is untouched.* The rewritten copy is built only for a
document that actually has fields with appearances, which is almost none of
them, and only the first time one is wanted. `PDFDoc` learns the answer during
the probe that already opens the file to read page sizes, so the check is free.
Everything without fields keeps returning the working copy, nothing extra is
written, and the fast entry into read mode behaves exactly as it did.

### Filling fields

Ordered so that each step is useful on its own and the risky parts come after
the model they depend on is proved. Nothing here is blocked: D26 and D27 are
taken.

| # | Step | Depends on | Done when |
|---|---|---|---|
| 1 | Own field values in the model | — | a value survives undo, redo and a page reorder |
| 2 | Find the field under a click | — | clicking a widget identifies its field; clicking elsewhere does not |
| 3 | Tick boxes | 1, 2 | clicking one toggles it on screen and after a save |
| 4 | Write values on save | 1 | a saved file opens in Acrobat with the value in the field |
| 5 | Text fields, single-line, explicit size | 1, 2, 4 | typing shows, survives undo, and saves |
| 6 | Narrow the snapshot invalidation | 3 or 5 | ten fills do not rebuild the reader ten times |
| 7 | Refuse to edit a signed document | 3 | a signed form says why rather than invalidating a signature |

**Step 1 is the one with a precedent.** D20 settled how the outline is owned in
the undo state beside the page list, keyed by a stable page id so that
reordering costs nothing, and dangling when its page goes. Field values want
exactly that treatment and exactly that keying, which is why the outline is
worth reading before writing any of this. The difference is that an outline
entry names a page while a field value names a *field*, which a page carries —
so the key is the page uid plus the field's fully qualified name.

**Step 3 before step 5 because tick boxes are nearly free.** Their appearance
for every state is already in the file, so setting `/V` on the field and `/AS`
on the widget is the whole of it, with nothing generated. On the form that
prompted this that is 58 of 86 widgets. Text fields need an appearance built,
which is step 5 and a different kind of work.

**Step 4 before step 5** so that writing is proved on the values that need no
generation. A tick that saves correctly means the export path is right; adding
text then only has to get the drawing right.

**Step 6 is not optional and is why it is listed.** Filling is a document edit
(see *Settled*), and an edit today rebuilds the reader's whole snapshot. Ten
fills on an eighty-page form would be ten full rebuilds. An annotation edit
changes what is drawn on a page without changing which pages exist, so it can
invalidate one page rather than the document — but only if that path is built.

### Markup

Not started, and should not start until filling has proved the model: it needs
the same ownership, the same undo behaviour and the same save path, plus two
things filling does not.

| # | Step | Depends on | Done when |
|---|---|---|---|
| 1 | An annotation model | filling, steps 1 and 4 | an added note survives undo and a save |
| 2 | A tool mode in the canvas | 1 | the pointer selects, highlights or draws as chosen |
| 3 | Highlight and strikethrough | 2 | a selection becomes a mark the file keeps |
| 4 | Sticky note | 2 | a note can be placed, read and edited |
| 5 | Free text and freehand | 3, 4 | both draw, save and reopen |

Highlight is first of the marks because its geometry already exists: text
selection produces the quadrilaterals a `/Highlight` annotation wants, so it is
the one mark that needs no new hit-testing. Freehand is last because it is the
only one whose appearance is not derived from something already on the page.

### The rest of the reader

Not started, and ranked below authoring by the user. An attachments panel —
nothing today touches `/EmbeddedFiles`, so a PDF carrying a file shows nothing;
signature status; a thumbnail panel while reading; view-only rotation; a dark
mode. None is a correctness problem, which is why they come last.

### A deliberate flatten

Separate from all of the above and useful on its own: a command that turns
filled values into permanent page content, which is what you want before
sending a completed form on. It cannot take the shortcut the display path took
— it writes a file, so it must implement the real placement rule, transforming
the appearance's BBox by its Matrix and fitting the result to the annotation's
Rect. That rule is the one piece of PDF geometry this work has deliberately
avoided writing so far.

### Settled

**`/AcroForm` is rebuilt from the output, always, and a name clash is
reported.** Rebuilt rather than copied because the output is a different set of
pages: an export of a selection keeps only the widgets on the pages it kept, and
`/Fields` naming the others would point at annotations that are not in the
document. Always rather than only for one source, because what merging cannot
resolve is narrower than it first appeared — two fields with the same name,
which in PDF are one field with two widgets, so typing in one changes the other.
Acrobat renames on import; this says so through the warning the save already
has, because renaming somebody's fields silently is a different surprise.

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

- How a *deliberate* flatten should work, for the command that makes filled
  values permanent page content before sending a form on. That one writes a
  file, so it cannot take the shortcut above: it has to implement the
  BBox-by-Matrix-fitted-to-Rect rule properly.
- Whether a signed document refuses field editing outright or warns. Signature
  *validation* is out, but noticing `/SigFlags` and declining to invalidate
  somebody's signature silently is a guard, not a feature.
- Whether this application's name still describes it. Not part of this work, but
  it is the same premise change, and D1 and D13 deliberately pinned the
  `QSettings` scope so that a rename cannot orphan saved state. A rename would
  also move the macOS bundle identifier, which carries the Finder association.

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

**3. The rewritten copy is for rendering only.** A document with form fields
gets a second temporary copy with `/Subtype` rewritten; export reads the real
one. A field drawn into a saved file is no longer a field, so `DocumentSet` has
two views of itself — `files_for_export` and `render_file` — and the tests hold
that line for an unedited document and for an edited one, which takes the other
path.

## Done

**2026-10-28 — showing what is in the file.** Annotations drawn in all three
render paths; form fields visible through the rewritten copy; `/AcroForm` rebuilt
on export so a saved form keeps its fields. Verified on the four-page insurance
form that prompted the work: 15 of 15 filled fields on page three draw, a ticked
box carries four times the ink of an unticked one, and the form round-trips a
save with 82 fields, 86 widgets and 23 values intact. A Qt warning on every
document close was fixed alongside it, being in the same code.
