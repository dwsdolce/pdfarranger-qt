# Annotations

**Issue:** [#14](https://github.com/dwsdolce/pdfarranger-qt/issues/14)

**Status:** IN PROGRESS — bodies 1 and 2 **complete**, body 3 at one of five. Tick
boxes and single-line text fields can both be filled in; what is typed shows,
survives undo and reaches the saved file with a drawing for it. Only the guard
A signed document refuses to be filled in or saved over, and a document
derived from one is honestly unsigned. Body 3 has its model: a mark is owned,
undoable and saved. What puts one on the page is next.

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
| 2. Fill fields | **complete** — nine of nine |
| 3. Markup | in progress — the model is in; the canvas is next |

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

**The red glyph on an unsigned signature field is the viewer's own, and asks
nothing of us.** Looked into because it appeared to be something our rendering
was missing. It is not. Both `/Sig` widgets in the test document carry `/V`
absent, a `/MK` whose `/BC` and `/BG` are empty arrays, and an `/AP /N` of
**zero bytes** -- there is nothing in the file to draw. Two independent tests
agree: the appearance stream is empty, and the owner printed the form and
scanned it back, at which point the glyphs were gone, where content would have
printed. It is the same class as the tint Acrobat paints over fillable boxes.
**Nothing to do**, written down so it is not investigated a second time.

### Tab order is in the file, and it is not the order we hold

Raised from use: *is there an order to the fields, and should Tab navigate
them?* Yes to both, and the order we currently hold is the wrong one.

A file carries order in three places that need not agree. The `/Annots` array
on each page, which is creation order and is what `fields_in` returns. The
`/AcroForm /Fields` tree, which is the naming hierarchy. And the page's
`/Tabs`, which is the one that actually *declares* traversal: `/R` row, `/C`
column, `/S` structure, plus `/A` article and `/W` widget. Absent, the spec
leaves it to the viewer.

Acrobat reads `/Tabs` and follows it; Page Properties writes it. Where it is
absent Acrobat falls back to an accessibility preference, *"use document
structure for tab order when no explicit tab order is specified"*, so two
installations can tab the same file differently -- and a checker counts a page
that has annotations and no `/Tabs`, or a `/Tabs` that is not `/S`, as a
failure.

What the corpus declares, against how closely each page's `/Annots` order
matches plain reading order:

| file | `/Tabs` | tagged | widgets | `/Annots` order as reading order |
| --- | --- | --- | --- | --- |
| ao239 | `/R` | no | 196 | 96% |
| f1040 | `/S` | yes | 199 | 79% |
| fw4 | `/S` | yes | 48 | 95% |
| i-9 | `/S` | yes | 130 | 87% |
| fw9 | `/S` | yes | 23 | 70% |
| sf3107 | `/S` | yes | 470 | 46% |
| f1099msc | `/S` | yes | 179 | 9% |
| vba-21-526ez | `/S` | yes | 388 | 5% |
| sf86 | none | yes | 6,852 | 4% |

So `/Annots` order is not a usable fallback -- on four of these it is close to
random -- and `/S` is what real forms declare, which means the order lives in
the structure tree.

Measured on a four page insurance form from the owner's own records, which
declares `/Tabs /S` on every page and whose 86 widgets are *all* reachable
from the tag tree through `/OBJR`, so nothing has to be guessed. Structure
order equals `/Annots` order on three of its four pages and agrees 21% on the
fourth. The first eight fields of that page each way, as (y, x):

    /Annots    (583,41) (583,369) (535,41) (535,204) (535,369) (328,50) (312,50) (296,50)
    structure  (583,41) (583,369) (535,41) (535,204) (535,369) (440,50) (424,50) (408,50)

Identical for five fields, and then the array jumps down the page while the
structure carries on in reading order. Tabbing by the array would skip a block
of fields and return to them later -- on the one page where not noticing is
easiest.

**Today Tab does something worse than nothing.** There is no `Key_Tab`
handling anywhere; the editor is a bare `QLineEdit` over the field, so Tab
takes Qt's default focus-next-child, `editingFinished` fires, and the value is
committed and the editor closed. Measured: focus lands back on the canvas, out
of the form entirely, and the next field has to be clicked.

Doing it properly needs a *focused field* in the canvas -- there is only
`_editing` now, which exists for text fields alone, so Tab-to-a-tick-box has
nothing to hold -- the `/OBJR` walk above for `/S`, row order as the fallback
where nothing is declared, Shift+Tab, wrapping across pages, and scrolling the
target into view, which `go_to_position` now makes straightforward.

It is the same structure tree a resize cannot keep (`/StructParents`, recorded
under the resize work), so resizing one of these forms costs it its tab order
as well as its tagging. The two are one piece of work, not two.

### The export leaves a tagged form untagged

Found while sizing the tab-order work, and the reason it cannot be done yet.

Every tagged document loses `/StructTreeRoot` through the export. Not only
when a page is scaled -- that case was recorded with the resize work -- but on
a plain pass with no edits at all. Measured:

| file | tagged before | tagged after | still claims |
| --- | --- | --- | --- |
| i-9 | yes | **no** | `/Tabs /S` |
| f1040 | yes | **no** | `/Tabs /S` |
| fw4 | yes | **no** | `/Tabs /S` |
| sf3107 | yes | **no** | `/Tabs /S` |

On i-9 the 138 `/OBJR` references the tree used to make become none. The pages
keep their `/Tabs /S` and their `/StructParents`, so the output goes on
declaring that its tab order comes from a structure that is no longer in the
file. An honest loss would be bad; a dangling claim is worse, because a
checker and a screen reader both believe the declaration.

Two things follow. Tab order cannot be read from the document the reader is
showing once anything has been edited, which is what blocks 2.11. And --
much more than a tab-order problem -- **every form this application saves
comes out untagged**, which is the accessibility structure stripped from
exactly the government and insurance forms where it is expected of them.

It is real work rather than a line. Carrying a tree across a page list that
can be reordered, cut and merged means remapping the parent tree, renumbering
`/StructParents` as pages move, and pruning the elements belonging to pages
that did not survive -- the same shape of problem as D20's outline remapping,
and for the same reason: a structure that refers to pages by index cannot
simply be copied. Hence its own step rather than being dragged in behind a
feature it was hiding under.

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

## What markup actually needs

Surveyed on a test document written in Acrobat Reader for this purpose, using
every markup tool Reader offers -- four pages, 176 annotations. Reader rather
than Acrobat proper, because Reader is what this is replacing and its tool set
is the smaller one.

### The tools, and what each one writes

A user picks a *tool*, not a subtype, so this is the list that decides what
gets built; the subtype survey below is the evidence under it. The two are not
the same list and do not line up one to one. **Replace selected text** is one
tool that writes *two* annotations. **`/StrikeOut`** is one subtype serving two
tools. **`/FreeText`**, **`/Line`** and **`/Polygon`** each serve two.

What separates tools sharing a subtype is `/IT`, the intent, and Acrobat
writes the tool's own name into `/Subj` besides -- so a file records which tool
made each mark, and showing a document back with the right tool against each
mark is reading, not guessing. Every row below was read off the test document.

| tool | `/Subj` it writes | what is written | state |
|---|---|---|---|
| Add a comment | Sticky Note | `/Text`, `/Name /Comment` | **3.4, done** |
| Insert text | Inserted Text | `/Caret` | D9, not started |
| Replace selected text | Inserted Text + Cross-Out | `/Caret` `/IT /Replace` **and** `/StrikeOut` `/IT /StrikeOutTextEdit`, joined by `/IRT` + `/RT /Group` | D9, not started |
| Add text comment | Text Box | `/FreeText` | 3.5 |
| Text callout | Callout | `/FreeText` `/IT /FreeTextCallout`, `/CL`, `/LE /OpenArrow` | not started |
| Attach file | -- | `/FileAttachment`, `/Name /Paperclip`, `/FS /EF` | not started |
| Highlight | Highlight | `/Highlight`, `/QuadPoints`, `/CA` | **3.3, done** |
| Underline | Underline | `/Underline`, `/QuadPoints` | not started |
| Strikethrough | Cross-Out | `/StrikeOut`, `/QuadPoints`, no `/IT` | **3.3, done** |
| Draw | Pencil | `/Ink`, `/InkList`, `/BS /W` | 3.5 |
| Line | Line | `/Line`, `/L` | not started |
| Arrow | Line | `/Line` `/IT /LineArrow`, `/LE [/None /OpenArrow]`, `/BS /W` | not started |
| Rectangle | Rectangle | `/Square`, `/RD` | not started |
| Circle | Oval | `/Circle`, `/RD` | not started |
| Polygon | Polygon | `/Polygon`, `/Vertices` | not started |
| Cloud | Polygon | `/Polygon` `/IT /PolygonCloud`, `/BE /I` | not started |
| Connected lines | Polygonal Line | `/PolyLine`, `/Vertices` | not started |
| Stamps palette | the stamp's name | `/Stamp`, `/Name`, and an `/AP` we do not draw | O8 |
| Add signature | -- | **page content, not an annotation** | O7 |
| Add initials | -- | **page content, not an annotation** | O7 |

Twenty tools, three of them done. Eighteen write an annotation; the last two
do not, and that is the whole of what makes them different. Placing a stored
signature or initials writes **page content**: measured on page 3 of the test
document, the signature is 1334 ink pixels with annotations off and 1334 with,
the initials 463 either way. That is why they already render here with no code
of ours, why they survived the owner's trip through a printer and a scanner,
and why nothing in M1 to M12 reaches them -- there is no annotation to select,
recolour or delete. Whether that is the right way for *us* to write them is
O7.

Signing with a digital ID is the one thing a user would call a tool that is
not here at all, and is out of scope under **Not here**.

Everything a tool needs *around* it -- selecting a mark, deleting it, its
colour, its author and times, its comment and replies, and the font and style
of the text-bearing ones -- is not per-tool and is M1 to M12 below.

### The evidence underneath

The same document counted the other way, by what is in the file rather than by
what made it. This is where the counts and the measurements live; the table
above is what they are for.

| kind | count | geometry | state |
|---|---|---|---|
| `/Widget` | 86 | -- | bodies 1 and 2 |
| `/Popup` | 41 | a rectangle beside its parent | no tool writes it; made with its parent, shown by M6 |
| `/Stamp` | 24 | a rectangle | not started |
| `/Link` | 5 | -- | body 1 |
| `/Text` | 2 | a point | **3.4, done** |
| `/FreeText` | 2 | a box; one of them with a `/CL` callout line | 3.5 |
| `/Caret` | 3 | a point and `/RD` | not started |
| `/Line` | 2 | `/L`, and `/LE` endings for an arrow | not started |
| `/Polygon` | 2 | `/Vertices`, and `/BE` for a cloud | not started |
| `/Highlight` `/Underline` `/StrikeOut` | 4 | `/QuadPoints` | **3.3 covers two of three** |
| `/Square` `/Circle` | 2 | `/Rect` and `/RD` | not started |
| `/Ink` | 1 | `/InkList` | 3.5 |
| `/PolyLine` | 1 | `/Vertices` | not started |
| `/FileAttachment` | 1 | a point, and a file embedded in the document | not started |

**Seeing them is nearly free, and that is measured.** All 44 *marks* carry an
`/AP`, and PDFium draws from it. The 41 `/Popup` entries carry none and need
none; they are where a mark's words are shown, not a drawing of their own.
Page one through this application's own render flag comes to 335,231 ink
pixels without annotations and 395,184 with -- and what appears is the highlight, the
underline, the strikeouts, both note icons, the free text, the callout, the
ink, the arrow, the polygon, the cloud, the connected lines, the square, the
circle, the carets, the paperclip and all six stamps, with no new code at all.
The form *values* are the one exception and come out blank, which is the
PDFium behaviour D4's rewritten copy already exists to answer.

**But seeing a mark is not reading it, and that is measured too.** Seven
marks in that file carry words. Five of them paint nothing but an icon: both
`/Text` notes, both `/Caret` marks -- one an insertion, one the replacement
for a struck-out phrase -- and the `/FileAttachment`. Their words are in `/Contents` and `/RC`, which a viewer
shows in a popup, and PDFium draws no popups. Only the two `/FreeText` marks
put their words on the page -- the same split as M6, since free text is the
one kind with no `/Popup` to put them in.

| | marks | `/Contents` | where the words are |
| --- | --- | --- | --- |
| `/FreeText` | 2 | 17 and 19 characters | drawn on the page |
| `/Text` | 2 | 17 and 20 characters | **a popup we do not have** |
| `/Caret` | 2 | 21 and 22 characters | **a popup we do not have** |
| `/FileAttachment` | 1 | 39 characters | **a popup we do not have** |

So a document someone has commented on still arrives looking almost pristine:
the icons land in the right places and not one word of what was written can be
read. That is a *display* gap, not an editing one, and M6 is what closes it --
which makes it the first thing worth building rather than part of the editing
body.

The rest is editing, and the plan currently names five of the fifteen markup
kinds.

### What every mark needs, whatever kind it is

**M1. Selected by clicking its ink.** Every kind, not only the ones we
author: a mark that can be seen and not selected cannot be edited, recoloured
or removed. By the ink and not by `/Rect` -- on page 1 of the test document
the 25 marks make 25 overlapping pairs by bounding box and a handful by ink,
so the choice is between a thicket and something nearly unambiguous. An
unfilled shape is its outline, so the inside of an empty rectangle is not the
rectangle. Which gesture belongs to the mark and which to the text under it is
O9.

The same test runs on *hover*, and that is not a refinement -- it is what
makes O9's rule usable. The pointer says in advance what the next gesture will
do: an I-beam over text, an arrow over a mark. Without it, "start on the ink"
is a rule nobody can see. And the test needs a tolerance, because a hairline
`/Line` hit to the exact pixel is unhittable; Reader appears to have one. That
tolerance belongs in *device* pixels rather than page points, or it shrinks
with the zoom and a mark becomes harder to grab the further out you are.

`CanvasView.mouseMoveEvent` already has the shape of this -- it hit-tests on
hover and sets a pointing hand over a note, a crosshair under an area tool, an
I-beam where there is text. What changes is `note_at`, which today finds only
the notes *we* made, only `/Text`, and by rectangle.

**M2. Deleted, and a grouped mark deleted whole.** There is no delete anywhere
in the plan today, and 3.4 shipped with emptying a note as the only way to
take one back. Reader puts delete in a small toolbar on the selected mark,
beside edit and colour. A mark joined to another by `/RT /Group` goes as a
unit: deleting a replacement takes its icon, its insertion mark and its
strikethrough together, which is what M9 describes and what makes the three
pieces read as one thing.

**M3. A colour, chosen before or after.** Reader carries one current colour at
the foot of its tool list, and it colours the next mark of any kind -- icon,
strikeout, text box, shape. A selected mark's colour can be changed afterwards.

**M4. An author and two timestamps.** `/T`, `/CreationDate` and `/M` are on
every mark in the file, and Reader shows the author and the time beside the
text. `/NM` gives each one a name that survives a save.

**M5. Preserved when we cannot edit it.** Anything unrecognised keeps its
dictionary, its `/AP` and its geometry through a save and through rotate, crop,
resize and reorder. This is largely done -- the 2026-10-29 work carries
`/InkList`, `/L`, `/Vertices`, `/CL`, `/RD`, `/Border` and `/BS /W` through a
resize -- and it is what makes partial support honest rather than lossy.

**M6. A comment, opened and closed.** 39 `/Popup` annotations, one per markup
mark, each `/Open false`. Every kind carries one *except* `/FreeText` and
`/FileAttachment`, which is the format's own split: a free text mark's words
are already on the page, so it has nothing to pop up. D8 settles how those
words are drawn; this is about the other fourteen kinds.

**M7. Replies.** One of the two `/Text` marks carries `/IRT`, and Reader's
popup offers "Add a reply" under the author's name. Comments are threads, not
single notes.

### What the text-bearing kinds need beyond that

**M8. Rich text, not a string.** This is the largest gap between the plan and
the file. Reader sets font family, size, colour, bold, italic, underline,
strikethrough, superscript and subscript -- and it sets them *per run*: the
test document's free text reads "This **is** a" in three different styles and
ends with a letter in a different colour again. The file carries that as `/RC`,
an XHTML fragment, with `/DS` for the default style; the `/DA` on that mark is
`0.2196 0.898 1 rg /Baskerville 20 Tf`, a family that is not one of the base
14. The `Annotation` model holds one `contents` string and one colour, so it
cannot represent any of this.

**M9. Text marks built from a selection, one of which is a pair.** Insert
text is a single `/Caret` at a point. Replace selected text is *two*
annotations joined into one object: a `/Caret` with `/IT /Replace` carrying
the typed replacement, and a `/StrikeOut` with `/IT /StrikeOutTextEdit` whose
`/IRT` names that caret and whose `/RT` is `/Group`. Measured on a replacement
made for this purpose, both written in the same second.

`/RT` is what separates the two uses of `/IRT`, and both are in the file: with
`/RT /Group` it means one object, and with `/RT` absent -- the default `/R` --
it is a reply, which is how a `/Text` note in the same document hangs off a
`/Caret`. Reading `/IRT` without reading `/RT` would turn every grouped pair
into a thread. The icon is not what distinguishes these three tools; both
`/Text` marks carry `/Name /Comment` and the carets draw from their own `/AP`,
so what separates a comment, an insertion and a replacement is the extra
annotation and the grouping, not the glyph.

### What sits in the same tools without being markup

**M10. A stamps palette.** 24 in the test file, carrying names like
`/SBApproved` and an `/AP` we would not be drawing ourselves.

**M11. Stored signatures and initials.** Reader keeps them and places them on
the page. Distinct from body 2's signature work, which is about *not* breaking
a document someone else signed.

**M12. File attachments.** `/FileAttachment` with `/Name /Paperclip` and the
file itself embedded through `/FS /EF`.

**M14. The marks already in the document are read into the model.** Nothing
does this today. `forms.py` reads `/Annots` for widgets and `structure.py` for
tagging, the exporter copies them page by page, and the only
`annotations.add()` in the application is the handler for a mark drawn in this
session. So the 44 marks in the test document do not exist as objects here at
all: PDFium draws them from their `/AP` and we hold nothing. Observed in the
running application -- the pointer shows an I-beam over text and does not
change over an annotation, because there is nothing to hit-test against.

This is the prerequisite under M1, M2, M3, M6, M7 and M13. Every one of them
applies today only to marks made since the file was opened, which is to say
not to a document anybody sends you.

It is not a small read. `Annotation` holds `kind`, `page`, `rect`, `quads`,
`contents`, `colour`, `author` and `created`; the marks in that file carry
`/Vertices`, `/InkList`, `/L`, `/LE`, `/CL`, `/IT`, `/RT`, `/IRT`, `/RC`,
`/DA`, `/DS`, `/BE`, `/BS`, `/Name`, `/RD` and `/FS` besides. So either the
model grows a representation of every kind, or each mark keeps the dictionary
it came from and our edits overlay it. Only the second cannot lose a key we
never thought to model, which is M5's argument applied to the marks we *can*
edit rather than the ones we cannot.

**M13. Moved and resized after it is made.** Nothing above says a mark can be
repositioned, and without it a misplaced mark can only be deleted and drawn
again. Reader moves any of them and resizes the ones with a box; a `/Text`
icon moves but does not resize, since its size is not its author's (D6 and
`markup.NOTE_SIZE`). Moving a grouped mark moves the group, by the same
argument that deletes it as one (M2). What a move writes is already understood
-- `/Rect` and whichever of `/QuadPoints`, `/InkList`, `/L`, `/Vertices`,
`/CL` and `/RD` the kind carries, which is the same list the resize work of
2026-10-29 already scales.

### The test

Load that document, see every annotation in it, and be able to edit every one.
Seeing it is measured above and nearly done. Editing it is M1 to M12, and the
user interface need not resemble Reader's -- only the functionality.

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
| 2.7 | Refuse to fill a field in a signed document | 2.3 | a signed form says why rather than invalidating a signature | **complete** |
| 2.8 | Strip the remains of a signature on export | -- | a derived document is honestly unsigned instead of claiming a signature over bytes that are gone | **complete** |
| 2.9 | Refuse to save over a signed source, and say the signature will not carry | 2.7, 2.8 | Save on a signed document offers Save As; a derived save says the signature is gone | **complete** |
| 2.10 | Carry the structure tree through the export | -- | a tagged form saved from here is still tagged, and `/Tabs /S` still means something | **complete** |
| 2.11 | Tab between fields, in the order the file declares | 2.5, 2.10 | Tab and Shift+Tab walk a form the way Acrobat walks it, honouring `/Tabs` | **complete** |

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

Not before 2 had proved the model: it needs the same ownership, the same undo
behaviour and the same save path, and it got all three by following them.

**Keyed by page uid**, which is D20's answer for bookmarks and is as true
here. An index dies at the next reorder and an object reference dies at the
next undo, because `UndoManager.snapshot` rebuilds the page list with
`duplicate()`. The uid survives both, and the Duplicate *command* assigns a
fresh one, so copying a page does not quietly copy somebody's notes with it.

**Nothing prunes a mark when its page goes.** Export asks for the marks of
the pages it is writing and never sees the others, so a note on a deleted page
is skipped with no tidying up anywhere -- and the identical rule, unchanged,
is what makes an export of a *selection* leave the unselected pages' notes
out.

**Coordinates are the page's own**, the space its `/MediaBox` is in, so a mark
is carried by every geometric edit exactly as the annotations already in the
file are: export turns a page with `/Rotate` and crops it by rewriting boxes,
and both move page-space geometry together with the content. The conversion
from where the pointer actually is belongs to 3.2, which is where a pointer
first exists.

| # | Step | Depends on | Done when | State |
|---|---|---|---|---|
| 3.1 | An annotation model | 2.1, 2.4 | an added note survives undo and a save | **complete** |
| 3.2 | A tool mode in the canvas | 3.1 | the pointer selects, highlights or draws as chosen | **complete** |
| 3.3 | Highlight and strikethrough | 3.2 | a selection becomes a mark the file keeps | **complete** |
| 3.4 | Sticky note | 3.2 | a note can be placed, read and edited | **complete** |
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

**Applying a digital signature** was considered and dropped, by the owner, on
2026-10-30. Clicking a `/Sig` field in Reader offers to sign it with a
certificate from the platform's own store -- a real PKCS#7 signature over a
byte range, written as an incremental update, with a generated appearance.
Building that means reaching three different certificate stores, digesting the
right bytes, and writing an update that leaves the signed ones untouched; even
the first step is deeper than it looks, since what Reader offered on the
owner's machine was his *code-signing* Developer ID certificates, which would
produce a signature no document validator would trust.

Reader does do it, so this is a deliberate departure from the yardstick D1 sets
rather than a gap in it. Three reasons. It is a body of work the size of
bodies 1 and 2, not a step inside one. It is security-sensitive in a way
nothing else here is: a signature covering bytes other than the ones the
author saw is worse than no signature. And it is the counterpart of signature
*validation*, already out under D1 on the same shape of argument -- a
half-built trust store that says "valid" when it means "parsed" is worse than
silence, and a half-built signer is worse than sending the user to Acrobat.

What stays in is the other side of it: refusing to break a signature that
already exists, which is D5 and steps 2.7 to 2.9. This application declines to
damage a signature, and does not make one.

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

Numbered so they can be referred to without ambiguity. A number is assigned
once and never reused: when an item is settled it leaves this list and becomes
a numbered decision below, so a gap in the sequence means something was
decided, not lost.

- **O1. Whether free text is typed on the page or in a popup.** The note's
  editor is a fixed 240 by 120 panel beside the icon, which suits a mark whose
  content is hidden behind an icon, and it is written and works at any zoom.
  Free text is *on the page*, so the expectation is to see it at page size, in
  position, while typing -- a `QTextEdit` positioned and scaled to the box at
  the current zoom, which is more work and is the only one of the two that can
  show what the file will actually contain, now that D8 fixes the font and the
  size is ours. Either way the size is a length in the source page's space
  under D6, so it divides going in and multiplies coming out exactly as the
  note's icon does, or text drawn on a half-size page exports at half the point
  size.

  Every tool examined types on the page. Reader's own help says to click where
  you want the text and type, and to double-click the box to edit it again;
  pdf.js uses a `contentEditable` div whose padding is scaled by the page's
  zoom; Apple bakes the clip, the border and per-glyph positions into the
  `/AP`. The format leans the same way -- `/FreeText` is one of only two kinds
  in the test document with no `/Popup`, out of fifteen, because its words are
  already on the page. None of that settles where *typing* happens, which is
  ours to choose and reaches the file either way. Not decided.
- **O2. What one freehand mark is.** One drag, one `/Ink`, or a pencil that
  stays down and accumulates strokes into a single annotation until the tool
  changes, which is what Acrobat does. `/InkList` holds either -- measured,
  PDFium draws two strokes in one annotation at exactly twice the ink of one,
  3840 pixels against 1920 -- so this is a question about the gesture and the
  undo stack rather than about the format. Accumulating needs a notion of the
  mark currently being added to, and every mark so far is one gesture, one
  commit. Not decided.
- **O3. Whether a free text mark has a border.** PDFium draws one unasked-for:
  2064 pixels on a `/Rect` 180 by 80 with empty contents, its bounds exactly
  the rectangle. An `/AP` of ours replaces it, so the frame becomes ours to
  choose or to leave out, and a comment box with a visible frame reads as a
  form field where one without reads as writing on the page. Not decided.
- **O5. Whether this application's name still describes it.** Not part of this
  work, but it is the same premise change, and D1 and D13 deliberately pinned
  the `QSettings` scope so a rename cannot orphan saved state. A rename would
  also move the macOS bundle identifier, which carries the Finder association.
- **O7. Whether a signature or initials are written as page content, the way
  Acrobat writes them, or as an annotation.** Reader's Fill and Sign puts the
  drawing straight into the content stream -- measured above, and the reason
  the owner's printed-and-scanned copy still carried it. Content is what every
  other reader will show, and it cannot be lost by a viewer that ignores
  annotations. But it is also the one mark in the whole set that cannot be
  selected, recoloured, deleted or undone after a save, because there is no
  annotation there to act on, and it edits the page itself in an application
  whose entire premise is that it does not. A `/Stamp` with the drawing as its
  `/AP` would behave like every other mark and go through M1, M2 and M5 for
  free. Not decided.
- **O8. Which stamps, if any, this application offers.** Showing them is
  already free: 24 in the test document, every one with its own `/AP`, all
  drawn by our renderer with no code. Offering them is a different question.
  Reader's palette holds 22 in three families -- 13 Standard Business
  (Approved, Rejected, Not Approved, Draft, Final, Completed, Confidential, For
  Public Release, Not For Public Release, For Comment, Void, Preliminary
  Results, Information Only), 4 Sign Here (Sign Here, Initial Here, Witness,
  Accepted) and 5 Dynamic (Revised, Reviewed, Confidential, Received,
  Approved). The names are a convention we can follow, but the *artwork* is
  Adobe's and cannot be copied, so offering any stamp at all means drawing our
  own. The dynamic five need more than artwork: their appearance bakes in the
  author and the moment of placement -- the test document's read "REVISED 9:45
  pm, Oct 30, 2026" and "REVIEWED By ... at 9:45 pm, Oct 30, 2026" -- which is
  generated at placement, not picked from a palette. So the choice runs from
  none, through a small set of our own, to all three families. Not decided.
- **O9. Whether to copy Reader's rule for what a click on the page means.** The
  rule itself is now known, having been got wrong twice here first. It has two
  parts and they fit together.

  **Marks are hit by their drawn ink, not by `/Rect`.** To take an arrow you
  must click a pixel of the arrow. This matters more than it sounds: measured
  on page 1 of the test document, the 25 marks make 25 overlapping pairs by
  bounding box and at most a handful by ink -- four pairs found, sharing
  between 1 and 26 pixels, with two marks the per-mark isolation could not
  resolve, so four is a floor rather than a count. Bounding boxes would make
  the page a thicket; ink makes it nearly unambiguous. An unfilled shape is its
  outline, so the inside of an empty rectangle is not the rectangle.

  **Where the gesture starts decides what it is.** Start on a mark's ink and
  the gesture belongs to the mark -- select it, move it. Start anywhere else
  and it is a text selection, which then runs *through* marks freely: dragging
  across a highlight selects the words under it. The mode, Select against Pan,
  changes none of this; marks behave the same under both, and the mode governs
  only whether a drag on bare page selects text or scrolls.

  What it costs, and Reader pays it too: text whose every pixel lies under a
  mark cannot be selected at all, because there is nowhere to start. A word
  inside a highlight is unreachable.

  So this is no longer a question about how to build it but whether to copy it,
  and the cost above is the only reason not to. Two things stand either way:
  the scrolling half of Pan is not needed, since the wheel, the trackpad, the
  scrollbars and the keyboard already do it in every mode; and mark over mark
  needs its own rule, where topmost-first is what 3.4's note hit-testing
  already does. Not decided.

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

**6. A mark is kept in the source page's space, and scaled on the way out.**
`/Rotate` and a crop carry a page-space rectangle for free -- a turn changes
nothing in the space, and a crop only rewrites the box -- so a mark stored
there follows its content through both without being touched. A resize is the
exception, because `export._scale` multiplies the space by its factor, so
`_write_annotations` multiplies a mark's rectangle by `row.scale` as it writes.

The alternative was to store what the canvas hands back, which is the *output*
page's space, and that is wrong in a way that only shows up later: every mark
on a page moves the next time that page is resized. Storing in source space is
also what makes a mark behave exactly like the annotations the file already
carries, now that those survive a resize with their geometry scaled.

**7. A page's displayed box reaches the canvas as plain data, beside the field
map rather than through it.** `from_displayed` needs
`(left, bottom, width, height, rotation)` per page, and `fields_in` already
computes exactly that and throws it away, so the boxes are kept from that same
pass -- one open of the document, no extra cost.

They are *not* reached through a `FieldMap.box_of()`, although that is where
the open document lives. A box is five numbers. It needs no document open and
nothing invalidates it, so putting it behind `FieldMap` would let `close()`
destroy data that has no reason to die, and would make a page with no widgets
depend on a form-field object to place a mark. It would also turn the D19 fast
path's `set_field_map(None)` -- which means the bytes could not be read for the
*form* -- into marks silently not working.

**8. A free text mark's appearance is drawn by `QPdfWriter`, which embeds the
font it used.** The viewer cannot be left to draw it. Measured against PDFium
on a `/Rect` 180 by 80 whose border alone comes to 2064 pixels, its own
generated appearance draws Latin text at +954 and *nothing at all* for Greek,
Cyrillic, Hebrew, Arabic, Japanese, Chinese and Georgian -- +0, the border and
no more -- and every one of those has a catalogue in `po/`. Writing the stream
by hand against standard-14 Helvetica fails worse rather than better: WinAnsi
draws the bytes as Latin glyphs instead of dropping them, so eight Greek
letters sent as sixteen UTF-8 bytes come to 1876 pixels where eight letters
cost 1217, and the mark is silently *wrong* instead of silently absent.

`QPdfWriter` is the same answer `stamp.py` reached for the same reason, and the
reasoning is already in its docstring: placing text needs the string's width,
which needs font metrics, which means shipping an AFM table that is Latin-1
only. Qt has the metrics and the face, takes Unicode, and embeds a subset of
whatever was drawn, so no font library is needed -- `fontTools` is not a
dependency and is not installed. The work is lifting Qt's content stream and
font resources into a Form XObject whose `/BBox` and `/Matrix` fit `/Rect`,
which is close to what `layers.paste_as_layer` already does for a stamp.

The font is embedded **always**, not only when the text needs it. The
alternative was a base-14 Helvetica path for WinAnsi-encodable text and an
embedded subset for the rest, which is this plus a branch -- and that branch
has to be re-decided every time the text is *edited*, which is exactly where
pdf.js has an open bug: editing an annotation to text its font cannot encode
updates `/Contents` and leaves the old appearance behind. Regenerating through
`QPdfWriter` on every edit means that class of bug cannot happen. It is also
what Apple does, measured in the corpus: 14 `/FreeText` marks written by
`Quartz PDFContext`, every one carrying a subsetted `/AAAAAD+Helvetica` as
`/TrueType` with a `FontFile2` in its own `/AP`, even for plain ASCII. The only
unembedded base-14 in any of the evidence is `/AcroForm /DR /Font /Helv` as a
*form* default, in documents whose producer controls the content to Latin.

The other alternative was Latin-only for now, with non-Latin refused where it
is typed. Rejected because a reader that ships 33 catalogues and cannot take a
comment in the user's own language is the same failure body 1 exists to fix --
a document whose content is invisible -- and because the saving is bytes rather
than work, now that Qt does the subsetting.

Two consequences. `has_fonts()` is False under the offscreen platform, so a
free text appearance is tested in the world the stamp tests already live in.
And the appearance's font object must not alias an `/AcroForm /DR` font with an
identical `BaseFont` name and a different font program, or Acrobat Reader warns
that the embedded font cannot be extracted.

**9. Comment, Insert Text and Replace Text are all three offered.** Taken by
the owner on 2026-10-30: they are heavily used when reviewing a document and
their meaning is long established, so a reader that shows them and cannot make
them is a reader somebody has to leave to answer a review.

The question nearly went the wrong way, and the reason is worth keeping. From
the screen the three look like three icons, so it was first written down as
whether a note's icon is the author's to choose. They are not three icons:
both `/Text` marks in the test document carry `/Name /Comment`, the carets
draw from their own `/AP` and use no `/Name` at all, and what differs between
them on screen is the colour. The distinction is carried by *structure*, and
M9 records it -- a comment is one `/Text`; an insertion is one `/Caret`; a
replacement is **two** annotations, a `/Caret` with `/IT /Replace` holding the
typed text and a `/StrikeOut` with `/IT /StrikeOutTextEdit` whose `/IRT` names
it and whose `/RT` is `/Group`.

Two consequences fall out of that and are already in the requirements. The
model has to represent a *group*, not only a mark, because deleting a
replacement takes its icon, its insertion mark and its strikethrough together
(M2). And `/IRT` must never be read without `/RT`: the same key makes a reply
when `/RT` is absent, which is how a `/Text` note in the same file hangs off a
`/Caret`, so reading one without the other turns every grouped pair into a
thread (M9).

What this does not decide is the icon a note is written with. PDFium ignores
`/Name` -- measured in 3.4, the same 1327 pixels for seven different values
and for none -- so offering a choice would mean drawing the icon ourselves,
and nothing in this decision needs that. 3.4's `/Name /Note` stands.


**10. The work goes one tool at a time, starting with where the tools live
and then with Comment.** Taken by the owner on 2026-10-30, and it replaces
what O4 was asking. O4 weighed three orderings -- M6 first, 3.5 first, or
freehand alone -- and all three ranked the work by *cost*. This ranks it by
what each piece teaches, and does the cheap thing second.

First the place a user finds the tools at all, because a tool nobody can reach
is not a tool, and because twenty of them will not fit wherever the first one
goes. Then one tool at a time, or at least one class at a time -- the
text-related marks, the graphical ones, and so on -- rather than by subtype or
by what happens to be cheap.

Comment is first of the tools because it is the one that will surface the most
that is still unsettled: rich text (M8), how attributes are chosen and applied
(M3), the author and times shown beside it (M4), the popup it is read in (M6)
and the replies under it (M7). It is also the kind already furthest along, so
what it teaches is paid for once and spent on the other nineteen.

How the rest are grouped is deliberately not settled. Two splits present
themselves -- by what a mark is *anchored to*, which puts Highlight,
Underline, Strikethrough, Insert text and Replace text together because they
share a text selection and its hit-testing; or by what a mark *carries*, which
puts Comment with Add text comment and Text callout because they share the
rich-text machinery. Comment is first under either, so the question can wait
until Comment has been built and has shown which of the two it leaned on.

Two consequences. Step 3.5 as the plan has it -- free text and freehand
together, because both were cheap -- does not survive this, and the step table
below is rebuilt around tools once the grouping is known. And M14 comes with
Comment rather than after it: looking at Comment "in detail" means looking at
the two in the test document, and those are not in the model until something
reads them in.

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

**2026-10-29 — a form on a turned page was drawn in the wrong place.** Found
while preparing 3.2, and a fault in body 2 rather than a complication for body
3. A widget's `/Rect` is written in the page's own space; the canvas works in
the frame the page is *laid out* in, which is cropped and turned by `/Rotate`.
The two agree only at zero. Measured with a black square at a known coordinate
and compared against where it actually drew:

| `/Rotate` | the mapping predicted | where it drew |
| --- | --- | --- |
| 0 | (69, 112, 156, 199) | (69, 112, 155, 198) |
| 90 | (152, 197, 341, 386) | off screen entirely |
| 180 | (69, 112, 156, 199) | **(544, 112, 630, 198)** |
| 270 | (152, 197, 341, 386) | (246, 292, 435, 481) |

So on any page carrying a rotation the fields were drawn and clicked in the
wrong place, mirrored across both axes at 180 degrees. Not an exotic file
either: scanned documents carry `/Rotate` constantly, and this application's
own Rotate command produces one, so a form the user had just turned behaved
this way. Every body 2 test used an unturned page, which is why it went through
green CI.

The rectangles are now converted as they are read, against the same box the
layout sizes from -- the CropBox clipped to the MediaBox -- and the generated
appearance is turned to match, at the unturned size so that a quarter turn is
not squashed into the wrong aspect first. Verified the same way it was found:
all four angles now land within a pixel of the content.

One of the three new appearance tests earns its place. With the turning
removed, both of the *size* assertions still pass, because the renderer draws
at whatever size it is asked for; only comparing the pixels catches an image
that was squashed into the new shape rather than turned into it.

**2026-10-29 — filling a field threw the reader back to the top.** Reported
from use: every click on a tick box, and every text edit, jumped the view to
the start of the document.

The cause was worse than the symptom. `canvas._paint_fields` already says what
was meant to happen -- *"a tick is then a repaint, which is what makes editing
possible at all: the alternative is rewriting the document for every change,
measured at 682 ms on a large form against 1 ms to change the value"* -- and
the wiring defeated it. Both fill handlers call `model.touch`, which the
*grid* needs because its thumbnails come from a rewritten copy with the old
value baked in. Touching also emits `contents_changed`, `_invalidate_reader`
listens to that, and in read mode it rebuilt the whole in-memory export. So
every tick paid the 682 ms the design exists to avoid.

Losing the place was the visible half. A rebuilt document is laid out from
`provisional_sizes` until the measuring pass catches up, that layout is
shorter than the real one, and the scrollbar is clamped into it. Measured on a
form whose pages had been edited: 500 of 933 became 0 of 739, and when the
range came back to 933 the position stayed at 0. On an *unedited* document it
never showed, because D19's fast path hands the canvas known page sizes and
the range never moves -- which is why it looked fine on a form just opened.

Two fixes. A fill now goes through `_field_filled`, which marks the snapshot
stale and leaves the reader showing what it has; that is safe only because the
canvas composites fields from the values the window holds rather than from the
file, so the reader was never out of date to begin with. And `_load_reader`
now restores where the reader was, for the rebuilds that are real -- rotating
a page while reading should not send you to page one either.

The restore needed two corrections that only measurement found. It runs before
the pages have been measured, so it lands on a guess, and the measuring pass
then re-anchored on whichever page the guess left under the viewport: rotating
a page while reading page 8 of 14 ended on page 7 at a *negative* offset. The
pass now carries the restore target instead. And `go_to_page` lands a margin
*above* the page top, so adding the offset to it fell exactly one margin
short, by an amount that grows with the zoom; the restore is absolute. Page 8
at 230.1 points comes back as page 8 at 230.1 points across a rotate that
moved the scrollbar from 6055 of 9600 to 4592 of 7217.

**2026-10-29 — and the rest of what a resize dropped.** The annotations were
the bug worth naming; everything else on the page dictionary went the same way
and for the same reason. Measured: `/AA`, `/ArtBox`, `/B`, `/BleedBox`,
`/Group`, `/Metadata`, `/PieceInfo`, `/StructParents`, `/Tabs` and `/UserUnit`
all left behind.

The obvious fix -- stop rebuilding the page, mutate it instead, and everything
survives for free -- does not work, and finding that out was worth more than
the fix. `as_form_xobject` is bound to the page it came from: replace that
page's `/Contents` afterwards and the XObject is left holding the wrapper,
calling itself, and the page renders blank. Upstream's fresh dictionary is
load-bearing, not sloppiness.

So the entries are carried onto the new page, sorted by what is actually right
rather than copied wholesale:

- `/Group`, `/Tabs`, `/AA`, `/B`, `/Metadata` carried unchanged. `/Tabs` became
  meaningful again when the annotations it orders came back.
- `/BleedBox` and `/ArtBox` *scaled*, being in the space that was multiplied.
  `/CropBox` and `/TrimBox` are not here: `_apply_geom_transform` deletes those
  on purpose, having folded the crop into the MediaBox already.
- `/PieceInfo` deliberately dropped. It is the private cache of whichever
  application wrote the file, describing content this has just rewritten.
- `/StructParents` dropped and recorded. It indexes the structure tree's parent
  tree for marked content in the page's *own* stream, and that content now sits
  inside a form XObject, which needs its own key and a matching tree entry.
  Copying the number would point the tag tree at content that is not there.
  Tagged structure does not survive a resize; saying so is honest where a
  copied key would not be.

`/UserUnit` was the one that had to be measured rather than reasoned about.
`as_form_xobject` adds a `/Matrix` for it and for nothing else, baking the
unit scale into the content, so carrying the key as well applies it twice: on
a 600x400 page at `UserUnit` 2.5 scaled by half, a box at x=100..300 drew at
x=125..375 on a 300pt page. Dropping it is wrong too -- it exists to describe
pages past the 14400pt the format allows, and flattening one can put it over
that limit. The conversion is undone and the unit kept, which puts both the
plain and the `/UserUnit` page at x 50..149, y 100..149 exactly. A
`/UserUnit` page was already resizing wrong before today, so this repairs it
rather than preventing a regression -- `_scale` came over from the GTK
exporter unchanged in the port.

**2026-10-29 — a resized page threw every mark away.** `_scale` composes a
*new* page dictionary, and anything living beside the content rather than in
it stayed on the old one. A probe page carrying eight annotations, scaled by
half: eight in, none out -- the form field among them, so resizing a filled
form silently emptied it. Found while deciding which frame a mark should be
stored in, and a bug in the port rather than a question for body 3.

The same probe through three other implementations, each wrong a different
way:

| | kept | `/Rect` | `/QuadPoints` | `/InkList` | `/L` | `/RD` | form field |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PDF24 | 8/8 | **left behind** | left behind | left behind | left behind | left behind | kept, stranded |
| pypdf 6.21.4 | 8/8 | scaled | left behind | left behind | left behind | left behind | kept |
| Ghostscript | 7/8 | scaled | scaled | left behind | scaled | left behind | **dropped** |
| this, before | 0/8 | -- | -- | -- | -- | -- | dropped |
| this, after | 8/8 | scaled | scaled | scaled | scaled | scaled | kept |

So there was no precedent to copy, only a mapping to get right. PDF24 is the
one a user is likeliest to meet and the worst of them: it keeps every
annotation and scales none, which leaves marks floating in the wrong part of
the page or off it entirely. The quiet failure is the middle column -- the
coordinates held *beside* `/Rect`, which put a correctly placed box around a
shape still drawn at the old size.

Annotations are now carried across with every page-space coordinate scaled:
`/Rect`, `/QuadPoints`, `/InkList`, `/L`, `/Vertices`, `/CL`, `/RD`, and the
border widths in `/Border` and `/BS /W`, which are lengths in the same space.
`/AP` streams need nothing -- a viewer maps an appearance's `/BBox` through
its `/Matrix` and fits the result to `/Rect`, which is the mechanism that lets
an annotation be resized at all. The annotation *objects* are reused rather
than copied, which is what keeps the AcroForm's `/Fields` naming the same
widgets, and `/P` is repointed at the page that replaced the old one.

Acrobat could not be asked: page scaling is a Pro-only Preflight fixup, and
what Adobe does to annotation geometry there is undocumented -- three searches
found nothing either way.

Five neuterings, four of which bit at once. The fifth, `/P` left pointing at
the replaced page, passed: the fixture set no `/P` on any annotation, so the
test's loop body never ran and it asserted nothing. The fixture now names one,
as a real file does. That is the third no-op test in this work, and all three
had the same shape -- a test that iterates over something the fixture does not
have.

**2026-10-30 — decision 6, coded a day after it was written.** D6 says a mark
is kept in the *source* page's space and that `_write_annotations` multiplies
its rectangle by `row.scale` on the way out. It did not, and nothing else did:
`git log -S"row.scale" -- export.py` names only the original port. So marks
were stored and written in **output** coordinates -- the alternative D6
considered and rejected -- and they failed in precisely the way D6 predicted.

| | |
| --- | --- |
| a note placed at | `/Rect` (120, 572, 140, 592) |
| its page then resized by half | `/MediaBox` 306 x 396 |
| written, before | (120, 572, 140, 592) -- off the paper entirely |
| written, after | (60, 286, 70, 296) |

The order in git is the whole of how that happened: `ff75458` wrote
`_write_annotations` without the multiplication, and `e3fe8ed` recorded D6
five commits later, in the present tense, describing behaviour the code did
not have. A decision written as though it were done is worse than one left
open, because nothing goes looking for it.

**It is three places, not one, and that is why it was worth doing properly
rather than patching the writer.** Read mode shows the *export*, so what the
canvas hands back is already scaled: placement divides (`canvas.to_source`),
the export multiplies (`markup.scaled`, from `add_to_page`), and the canvas
multiplies again to draw (`canvas.from_source`). The scale reaches the canvas
as plain data beside the page boxes, which is D7's answer and for a sharper
reason here -- the boxes can be read out of the document being shown and the
resize cannot, because the document on screen has it applied already. The page
list is the only thing that still knows.

Two things fell out of it that the single-page unscaled case hid.

**A note's size is fixed on the page a reader draws, not in the source space**,
so the mark holds `NOTE_SIZE / scale` and the export multiplies it back. The
first version normalised to a flat 20 points in source space and quietly
halved every note placed on a page shown at half size.

**The icon is drawn from the rectangle's lower left, 20 points up and right,
whatever the rectangle says** -- so `markup.icon_box` is what to draw and
hit-test, and the rectangle is not. The two are the same box for a note placed
here and differ for one whose page has since been resized, where following the
rectangle drew an icon half the size of the one in the saved file.

Seven tests, seven neuterings, baseline recorded first -- and the baseline
earned its keep twice over.

**Five of the seven failed on their first run against the correct code**, all
for one reason: `written()` read "the first annotation", and
`text_and_link.pdf` carries two `/Link` annotations of its own which the
export writes before the marks. So five assertions were about a link's
rectangle. A fixture holding something nobody put there is the same family as
a fixture holding nothing -- in both the test is not about what its name says.

**And one neutering passed anyway**: scaling a highlight's rectangle while
leaving its quadrilaterals. The test read the written `/Rect`, and
`to_dictionary` builds that from `Annotation.rect` -- so the broken version
wrote a correct rectangle around a shape still drawn at the old size, which is
exactly the defect, and the test could not see it. It reads `/QuadPoints` now.
The comment claiming the rectangle would catch it was reasoning where a
measurement was wanted.

**2026-10-30 — step 3.4.** A note is *placed*, not dragged out, and it is the
one mark whose size is not its author's to choose.

Measured against PDFium, with the annotation render flag on and the page
composited onto white:

| | |
| --- | --- |
| a blank page | 0 ink pixels |
| a `/Text` with no `/AP` | **1327** ink pixels |
| the same with an `/AP` of ours | 1600 |
| `/Rect` 20x20, 60x60, 10x10, no size at all | the icon drawn 20 x 20 points every time |
| rendered at 1x, 2x, 4x | 20 x 20 points every time |
| `/Name` `/Comment`, `/Note`, `/Help`, `/Key`, `/Star`, absent, nonsense | the same 1327 pixels, every one |

Four decisions fall straight out of that table.

**The rectangle is written at the size the icon will be** -- 20 points square,
positioned so that the icon as drawn has its top left corner on the pointer,
which is a sentence the turn makes less obvious than it sounds; see below. The
specification says the size is ignored; a reader hit-tests `/Rect` all the
same, so a rectangle of no size is a note nothing can click, and one of 120 by
24 is a note you can click a centimetre away from.

**And the icon hangs off the rectangle's *lower* left, not its upper.** The
first reading of the measurement said upper, and a square rectangle of exactly
the icon's size cannot tell the two apart -- which is the only kind this
writes, so everything agreed. Re-measured against a `/Rect` 60 by 24: the icon
sits on its *bottom* edge, 20 points tall, and the same page-space box comes
out at `/Rotate` 0, 90, 180 and 270. A viewer adds the 20 points in page space
and then turns the page, which is why `note_icon_rect` turns the icon's box
rather than its own idea of a top left corner, and why no case analysis per
angle was needed.

**Nothing is written for the icon.** This is the only mark where leaving out
the appearance stream is a decision rather than a shortcut. A highlight
carries one because a viewer is merely *recommended* to draw the
quadrilaterals; a note's appearance is an icon every viewer's users already
recognise, and ours would replace a familiar balloon with a rounded box. The
measurement says it costs nothing: 1327 pixels either way.

**`/Name` is written anyway**, for the viewers that read it -- PDFium does not.

**The icon scales with the zoom**, because it is 20 points *on the page*. So
the mark's rectangle and the icon are one box, and there is one place that
says where a note is rather than two that can drift.

The text is asked for in a `QTextEdit` over the page, beside the icon rather
than over it, which is `edit_field`'s reasoning: a note is read and written
where it is in every other reader, and a widget already knows about wrapping,
the clipboard, input methods and right-to-left text. Escape is taken inside
the editor, because on the canvas it means *stop marking up* and one keystroke
should not do both. Hovering an icon shows its text without opening anything
-- a document covered in icons you have to click one at a time to read is a
filing cabinet.

**An empty note is removed, and a note nobody wrote leaves nothing behind.**
Acrobat and Preview both keep an empty one; this does not, because until there
is a command for deleting a mark, emptying one is the only way to take it
back, and an icon claiming there is a note where there is no text is a lie on
the page. Placed and then abandoned, the mark goes *and* the undo entry
pushed for placing it is discarded -- so the gesture leaves no step that
undoes nothing. The entry is taken back only when it is still the top of the
stack, so a command run from the keyboard while the editor was open cannot be
discarded in its place. The first text typed into a new note commits nothing
either: the placement's entry already holds the state from before the note
existed, so one undo takes the note and its words together.

Measured end to end on a real gesture:

| | |
| --- | --- |
| placed | `/Rect` (120, 572, 140, 592) from a click at page (120, 200) |
| reader rebuilt | no |
| undo entries for place-and-type | 1 |
| abandoned empty | 0 marks, undo depth back where it started |
| drawn on the canvas | 458 amber pixels, before anything was exported |
| saved | `/Subtype /Text`, `/Name /Note`, `/Contents`, no `/QuadPoints` |
| rendered from the file | 336 ink pixels where the note is, 0 there before |

Twenty-one tests and seventeen neuterings. **One earlier run reported "bites"
for a test that had never passed at all** -- worse than a test that passes
both ways, because the harness was observing only the broken half. Proving a
test fails against broken code proves nothing by itself; the clean run is the
other half of the evidence. The harness records it first now and refuses to
go on without it, and the result reads better for it: both neuterings of the
anchor fail six of the eight subtests and leave two passing, and the two are
the `/Rotate` zero pair, where the right answer and the wrong one are the
same numbers.

What it was failing about was real. At `/Rotate` zero a mark's rectangle and
its place on the laid-out page are the same numbers, so an upright one-page
fixture cannot see the turn at all -- and behind that, **a note was anchored
in the wrong frame.** A viewer draws the icon at the top left of `/Rect` *in
page space* and then turns the page, so expanding the rectangle in page space
puts the icon wherever the turn sends it. Measured, for a click at the same
spot on the same page:

| | |
| --- | --- |
| `/Rotate` 0 | drawn with its corner on the pointer |
| 90 | drawn **22 pixels to the left** of the pointer |
| 180 | drawn **28 up and to the left** |
| 270 | drawn **21 below** |

The rectangle is expanded on the laid-out page now and only then turned back
into the page's own space, which puts the corner under the pointer at every
angle -- here and in any other reader, because both start from the same
`/Rect` and the same `/Rotate`. `POINT_TOOLS` says in the canvas what that
means: a tool whose geometry is a corner and a size of its own rather than an
area dragged out.

The test went with it. Its hover point was measured *down the page*, which is
a different direction on screen once the page is turned -- which is how it
managed to fail against correct code and look like a bug in the code. It is
now four subtests, one per angle, each asserting the reader's page box
actually carries that angle before trusting anything, and hit-testing a few
*viewport* pixels in from the point that placed the note.

**2026-10-30 — step 3.3.** A highlight is a text *selection*, not a dragged
box. With the tool active the pointer behaves exactly as it does when reading
-- the same snapping, word and line extension, an I-beam cursor -- and on
release the selection's runs become `/QuadPoints`. That is why highlight came
first of the marks: the geometry already existed.

One rectangle per *run*, never one round the paragraph. A box spanning three
lines covers the margins and the gaps between them, and a highlight that does
that is worse than none.

Measured end to end on a real gesture:

| | |
| --- | --- |
| mark held | `/Highlight` rect (73, 697, 247, 710), one quad |
| reader rebuilt | no |
| saved `/QuadPoints` | 73 710 247 710 73 697 247 697 |
| saved `/AP`, `/CA`, `/F` | present, 0.4, 4 |
| rendered | 1232 yellow pixels |
| drawn on the canvas | 696 yellow pixels, before anything was exported |

**PDFium draws a `/Highlight` with no appearance stream at all** -- 1600
coloured pixels either way -- so the reader never needed one. A file written
here carries one regardless, because a viewer is only *recommended* to
generate one and every markup annotation in the corpus that a real producer
wrote has one. Multiply, so the words underneath still read; a strikethrough
is a line a fifteenth of the run's height through the middle.

The canvas draws pending marks itself rather than exporting the document
again, which is `_field_filled`'s reasoning applied to marks: 682 ms and the
reader's place, for something the canvas can draw from what the window already
holds.

`mark_drawn` now carries a *list* of rectangles rather than one. An area tool
sends the single rectangle it dragged out, a text tool one per run, so one
signal covers both without the payload changing shape by tool.

**The fifth no-op test of this work, and the same cause as the other four:
the fixture did not contain the thing the test was about.** `text_and_link.pdf`
holds a single text run, so "one box round the paragraph" and "one per line"
produce identical output against it, and the neutering passed. A three-line
fixture replaced it: a two-line selection gives quads at y 60--73 and 84--97,
and a test asserts nothing reaches across the gap between them. When a test
passes against both versions, suspect the fixture first.

**2026-10-30 — step 2.11.** Tab walks a form in the order the file declares.

The order follows `/Tabs`: `/S` through the structure tree, `/R` and `/C` by
row and column, `/A` by the array, `/W` by the field tree. Where nothing is
declared it falls back to **row order**, not array order -- Acrobat falls back
to an accessibility preference there, so two installations tab the same file
differently, and sf86 declares nothing while its 6,852 widgets sit in array
order only 4% like reading order. A field the declared order does not mention
goes after the ones it does rather than being dropped: unreachable by keyboard
is worse than out of sequence. Checked across the corpus -- nothing lost or
repeated, pages never interleave, and where `/S` is declared it is followed
exactly on every file.

The canvas gains a *focused field*, which did not previously exist: `_editing`
is a text field's editor, so a tick box could not be focused at all. It draws
a ring, scrolls into view, takes Space or Enter, and leaves on Escape.

**Four faults, and the tests saw none of them.** Three were reported from use
on a real form. All four were invisible because the tests called
`keyPressEvent` directly, which is a path the keyboard never uses: Qt takes
Tab in `QWidget.event()` for focus traversal *before* any key handler runs.
Eighteen tests passed while Tab in the real window moved between the canvas
and the page number box and never touched the form.

- **Tab never reached a field.** It belongs in `focusNextPrevChild`.
- **It stuck on a tick box.** A box has no editor, so once the line edit was
  gone nothing held the keyboard.
- **Clicking a field and then tabbing jumped to page one.** A click opened the
  editor without setting the focus, so the step began from nothing.
- **One Tab stepped four fields.** Taking the editor away makes Qt look for
  somewhere else to put the keyboard, which comes straight back to
  `focusNextPrevChild`. Guarded inside `finish_editing`, where it covers every
  caller: guarding only the two callers that seemed to matter left *clicking
  away* from a field moving the focus and drawing a ring round an unrelated
  one, which an existing ink-counting test caught.

Verified through Qt's own dispatch on i-9, 130 fields across text, choice and
button: 40 consecutive tabs, 0 wrong, across page boundaries, and Shift+Tab
correct going back. The tests drive `QTest.keyClick` now, and one of the four
regression tests did not bite at first either, because it let a fallback mask
the missing `setFocus`.

**2026-10-30 — step 2.10.** A tagged document stays tagged through a save,
and where it cannot, it stops claiming to be.

The thing this is *not* is `copy_foreign` on `/StructTreeRoot`. Every element
names its page in `/Pg`, so following the root copies the **source** pages in
as objects nothing points at, and leaves `/Pg` aimed at those orphans rather
than at the pages the export wrote. The tree is rebuilt element by element
with `/Pg` taken from a map of what was copied.

Tab order survives exactly, which is the whole point of carrying it -- the
widgets an `/OBJR` names, in tree order:

| | source | export |
| --- | --- | --- |
| i-9 | 138 | 138, identical |
| f1040 | 199 | 199, identical |
| fw4 | 48 | 48, identical |
| a four page insurance form | 91 | 91, identical |

What it will not attempt says so rather than leaving a dangling claim:

| | tagged | `/Tabs` | pages keyed | annotations keyed |
| --- | --- | --- | --- | --- |
| untouched | yes | `/S` | 4 | 138 |
| a page deleted | yes | `/S` | 3 | 134 |
| reversed | yes | `/S` | 4 | 138 |
| a page duplicated | no | none | 0 | 0 |
| a page scaled | no | none | 0 | 0 |
| merged with another file | no | none | 0 | 0 |

A duplicated page cannot say which copy an element belongs to; a scaled page
has had its marked content wrapped into a form XObject, which needs its own
key; merging would need two role maps reconciled. Each is a thing this does
not know how to do, and the honest answer is to take the claim off.

Two faults only measurement found. The trail recorded page *objects*, and
`_apply_geom_transform` replaces every page after the copy: objgens (3,0) to
(92,0) became (546,0) to (549,0), so every `/Pg` lookup missed and not one
page got a `/StructParents` -- while 373 elements still arrived, so the output
looked tagged and was not. It records positions now. And the first
`_make_honest` took `/Tabs` off unconditionally, which threw away ao239's
working `/Tabs /R`: row order is self-contained and says nothing about a
structure tree. Only `/S` is removed.

The `/ParentTree` is rebuilt flat. The source's is a number tree that a real
file splits across `/Kids` -- the four page form measured here holds its 419
entries that way -- so reading it needs a proper walk, but writing one in a
single pass has no reason to be split, and its keys index the *source's*
pages in any case.

**2026-10-30 — step 3.2.** The pointer has a job, and a drag reports where it
was in coordinates the file can keep.

Built in two halves because only one of them had anything left to decide. The
seam was settled already: D6 fixes the frame, D7 fixes how the page boxes
arrive, and `from_displayed` does the turn. Verified by dragging over a widget
rather than over blank paper, so there was a rectangle in the *file* to check
against instead of one this had computed for itself -- the canvas sees that
widget at four different rectangles depending on `/Rotate`, and all four come
back as the (150, 550, 298, 570) the file holds.

The tool mode had one real question, and it was the owner's to answer: **over
a field there is no markup.** The field takes the press and is edited. So the
tool is consulted only after the field check that `mousePressEvent` already
did, and the right button is untouched -- the context menu was already built
from whatever is under the pointer and has nothing to do with the tool.

Taken rather than asked, and recorded here instead: a widget that cannot be
filled falls through to the tool, because a field you are not allowed to fill
is no reason to refuse a mark on the page around it.

The canvas treats every markup tool the same -- a drag that reports a
rectangle -- so what each one *means* stays with the step that adds it. A
click rather than a drag arrives as a rectangle with no width, which is what
placing a sticky note is, so 3.4 needs no second path. Escape leaves the tool,
and the menu follows the canvas rather than the other way round, because
Escape changes it without going through the menu.

One menu cost three rounds of failures, and the first two were the catalogue
gate being necessary and not sufficient.

`Markup` was new, D23 refused the build, and it went into the template and
all 33 catalogues marked machine translation, unreviewed (D22). That looked
like the whole of it. It was not: `_Highlight`, `_Note` and `_Draw` were new
too and reached *nothing*, because the template is extracted by matching the
**called name** -- `update_pot` knows `_action` and `_menu` -- and they had
been passed to a new helper named `_tool_action`. A gate can only check the
strings it has been shown. `test_i18n` caught them because its own regex is
looser than the extractor's name match, finding three labels the extractor
could not. Fixed at the cause: the helper takes an already-built action, so
each label sits inside a `self._action(...)` call. Before, `update_pot` found
nothing; after, three.

Then the translations themselves collided. `test_catalogues` requires that no
two entries of one menu share an access key, and four new entries had to fit
around each catalogue's existing `_Select`, which the Arrange submenu shares
and which is not ours to move. Seven languages clashed -- and in Georgian and
Swedish the clash was that the *same word* had been given for Select and
Highlight, which no choice of letter would have fixed.

`merge_translations` then refused to apply the corrections, reporting them as
already translated and left alone. That is its guarantee against overwriting
human work, correctly applied; it also meant the first fix silently did
nothing. The seven entries were rewritten in place instead, being machine
strings written minutes earlier and still marked unreviewed.

Two separate tests also hold an inventory of the menu bar, in `test_i18n` and
in `test_dialogs`. A new menu belongs in both.

**2026-10-29 — the inverse, for 3.2.** `from_displayed` takes a rectangle in
the frame the page is laid out in back to the page's own space, which is the
direction a pointer needs: everything on screen is in the laid-out frame, and
anything written into the file is written in the page's own space. Written
beside `to_displayed` and derived the same way, from where the corners come
*from* rather than by inverting a matrix, so the two can be read against each
other -- and asserted against a table derived by hand from a 300x120 page, so
that the two cannot agree on the same mistake. It normalises, which is what a
drag gives: dragging up and to the left is the same rectangle, not a negative
one, and a click is simply a rectangle with no width.

Checked by neutering it three ways. Dropping the rotation branches fails ten;
dropping the crop origin fails five, including the one case with no rotation at
all; swapping width for height on the quarter turns -- the plausible mistake,
since the displayed box has them the other way round -- fails seven. A
round-trip test alone would have caught the first and third but not told them
apart, which is why the hand-derived table is there as well.

**2026-10-29 — step 3.1.** Marks added to a document are owned in the model,
keyed by page uid, and ride the same undo stack as the pages, the outline and
the form values. A note survives undo and redo, reaches the saved file with
its text, rectangle, author, colour and the Print flag, follows its page when
the order changes rather than staying in the slot, and is left behind by an
export of a selection that does not include its page. The two undo tests were
checked by neutering the restore: the first version of the second test passed
anyway, because undoing a *delete* never needed the note put back, so it now
walks back two steps instead of one.

**2026-10-29 — steps 2.8 and 2.9.** Export takes the remains of a signature
out instead of carrying them. The bug was there whichever way D5 had gone: a
signature field travelled with its page and `/SigFlags` was carried across, so
the output announced a signature over bytes that no longer existed -- and on
the certified sample kept a `/Reference` declaring `DocMDP P=1`, no changes
permitted, while the `/Perms` entry naming it did not survive the new root.
Whether the output lied at all depended on whether the widget's page was in
the selection.

Dropping the reference turned out not to be enough. qpdf does not collect
unreachable objects, so the signature dictionary stayed in the file -- 6,453
bytes of PKCS#7 and the signer's certificate chain up to the Adobe root,
unreachable and so harmless to a viewer, but carried into a document with
nothing to do with it. It is emptied before it is unhooked. A *visible*
signature keeps its drawing, as a `/Stamp`: the appearance is page content the
user can see, and it is the dictionary that made the claim.

With that, a save may happen but not over the signed file. `save()` writes to
`current_path` where `save_as()` prompts, so refusing the first and offering
the second is the whole of it -- which is also what Acrobat tells you to do,
"save a copy and reopen to edit this document". Either way the save says the
signature has not come with it, and a test opens the result to check that is
true rather than trusting the message.

**2026-10-29 — step 2.7.** A signed document refuses to have its fields
filled in, and says so rather than ignoring the click. The test is a `/Sig`
field carrying a `/V`, or `/Perms /DocMDP`; `/SigFlags`, `/Perms /UR3` and an
empty signature field are each rejected explicitly, because each of them
occurs in the corpus on a form that must stay fillable -- reading `/UR3` as a
signature alone would refuse the 1040, the W-4, the W-9, the 1099-MISC and
SF-3107.

Asked of the *source* document, where the probe already has it open with
pikepdf, and not of the document on screen: the reader is shown an export, and
2.8 will leave no signature in one. The canvas asks before deciding what a
click means, so no editor opens over a field it would then refuse to commit,
and the handlers refuse the value as well -- neither is the only thing between
a signed document and a broken signature. Checked by neutering each half
separately: without the detection seven tests fail, without the canvas guard
three, without the handler guard exactly one.

Classified correctly across every sample held: the four signed files, the nine
public forms, and the insurance form whose two empty signature fields leave it
fillable.

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
