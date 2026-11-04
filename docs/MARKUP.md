# Markup

**Issue:** [#16](https://github.com/dwsdolce/pdfarranger-qt/issues/16)

Making a mark, changing one that is already there, and losing nothing on the
way. Showing what a file already carries is a different body of work with a
document of its own; this one begins where that ends.

The owner's standard, in his words: *make the markup and not lose anything
when it is opened in our tool.*

## Where this stands

A document goes through this application and comes out with every annotation
it went in with, measured on 8,697 annotations across the validation corpus.
Three defects were found proving it, each of them a change made by nothing
more than opening a file and saving it.

The strip the tools are chosen from is built, and every one of its twenty
tools can be armed. **No tool does anything yet.** What a tool makes is
decided one tool at a time, together with its gesture and its attributes,
starting with Highlight.


## The tools, and what each one writes

A user picks a *tool*, not a subtype, so this is the list that decides what
gets built; the subtype survey below is the evidence under it. The two are not
the same list and do not line up one to one. **Replace selected text** is one
tool that writes *two* annotations. **`/StrikeOut`** is one subtype serving two
tools. **`/FreeText`**, **`/Line`** and **`/Polygon`** each serve two.

What separates tools sharing a subtype is `/IT`, the intent, and Reader
writes the tool's own name into `/Subj` besides -- so a file records which tool
made each mark, and showing a document back with the right tool against each
mark is reading, not guessing. Every row below was read off the test document.

The state column says what the tool can do *here*, or else names the decision
or open item that governs it. It does not report which step shipped something:
that is the step table's job, and a step was never scoped as a whole tool.
**Writes only** means the tool can make its mark and save it, and nothing
after that.

| tool | `/Subj` it writes | what is written | state |
|---|---|---|---|
| Add a comment | Sticky Note | `/Text`, `/Name /Comment` | writes only |
| Insert text | Inserted Text | `/Caret` | decision 3, not started |
| Replace selected text | Inserted Text + Cross-Out | `/Caret` `/IT /Replace` **and** `/StrikeOut` `/IT /StrikeOutTextEdit`, joined by `/IRT` + `/RT /Group` | decision 3, not started |
| Add text comment | Text Box | `/FreeText` | not started |
| Text callout | Callout | `/FreeText` `/IT /FreeTextCallout`, `/CL`, `/LE /OpenArrow` | not started |
| Attach file | -- | `/FileAttachment`, `/Name /Paperclip`, `/FS /EF` | not started |
| Highlight | Highlight | `/Highlight`, `/QuadPoints`, `/CA` | writes only |
| Underline | Underline | `/Underline`, `/QuadPoints` | not started |
| Strikethrough | Cross-Out | `/StrikeOut`, `/QuadPoints`, no `/IT` | writes only |
| Draw | Pencil | `/Ink`, `/InkList`, `/BS /W` | not started |
| Line | Line | `/Line`, `/L` | not started |
| Arrow | Line | `/Line` `/IT /LineArrow`, `/LE [/None /OpenArrow]`, `/BS /W` | not started |
| Rectangle | Rectangle | `/Square`, `/RD` | not started |
| Circle | Oval | `/Circle`, `/RD` | not started |
| Polygon | Polygon | `/Polygon`, `/Vertices` | not started |
| Cloud | Polygon | `/Polygon` `/IT /PolygonCloud`, `/BE /I` | not started |
| Connected lines | Polygonal Line | `/PolyLine`, `/Vertices` | not started |
| Stamps palette | the stamp's name | `/Stamp`, `/Name`, and an `/AP` we do not draw | O4 |
| Add signature | -- | **page content, not an annotation** | not here |
| Add initials | -- | **page content, not an annotation** | not here |

Twenty tools, none of them finished. Three can write their mark and save
it -- the note, the highlight and the strikethrough -- which is one
requirement out of the fifteen below; what they make cannot afterwards be
selected, deleted or reopened, because M1 and M14 are shared by all twenty and
neither exists yet. Eighteen write an annotation; the last two do not, and
that is the whole of what makes them different. Placing a stored
signature or initials writes **page content**: measured on page 3 of the test
document, the signature is 1334 ink pixels with annotations off and 1334 with,
the initials 463 either way. That is why they already render here with no code
of ours, why they survived the owner's trip through a printer and a scanner,
and why nothing in M1 to M12 reaches them -- there is no annotation to select,
recolour or delete. Whether that would be the right way for *us* to write
them was once an open question, and it is moot: this application does not
sign, so the tool is not offered at all.

Signing with a digital ID is the one thing a user would call a tool that is
not here at all, and is out of scope under **Not here**.

Everything a tool needs *around* it -- selecting a mark, deleting it, its
colour, its author and times, its comment and replies, and the font and style
of the text-bearing ones -- is not per-tool and is M1 to M12 below.

## The evidence underneath

The same document counted the other way, by what is in the file rather than by
what made it. This is where the counts and the measurements live; the table
above is what they are for.

| kind | count | geometry | state |
|---|---|---|---|
| `/Widget` | 86 | -- | Parts 1 and 2 |
| `/Popup` | 41 | a rectangle beside its parent | no tool writes it; made with its parent, shown by M6 |
| `/Stamp` | 24 | a rectangle | not started |
| `/Link` | 5 | -- | drawn already |
| `/Text` | 2 | a point | writes only |
| `/FreeText` | 2 | a box; one of them with a `/CL` callout line | not started |
| `/Caret` | 3 | a point and `/RD` | not started |
| `/Line` | 2 | `/L`, and `/LE` endings for an arrow | not started |
| `/Polygon` | 2 | `/Vertices`, and `/BE` for a cloud | not started |
| `/Highlight` `/Underline` `/StrikeOut` | 4 | `/QuadPoints` | two of the three write only |
| `/Square` `/Circle` | 2 | `/Rect` and `/RD` | not started |
| `/Ink` | 1 | `/InkList` | not started |
| `/PolyLine` | 1 | `/Vertices` | not started |
| `/FileAttachment` | 1 | a point, and a file embedded in the document | not started |

**A second document, made to exercise the attributes.**
`corpus/Markup Test Case.pdf` is the first document with the owner's personal
information removed, and it carries variations the first did not. Four things
in it settle questions that were previously argued rather than measured.

*Thickness is written only when it is changed.* The arrow carries `/BS /W 5`;
the plain line carries no `/BS` at all. So an attribute at its default is
absent from the file, and reading a mark back has to treat a missing key as
the default rather than as zero.

*Opacity belongs to the highlight alone.* `/CA 0.4` on both highlights, and
nothing on the underline, the strikeout or the squiggly -- which is exactly
the split `markup.TRANSPARENCY` already encodes.

*Both meanings of `/IRT` are now in one file.* A `/Text` with `/IRT` and no
`/RT`, which is a reply; and a `/StrikeOut` with `/IRT` and `/RT /Group`,
which is half a Replace pair. M9's trap can now be tested rather than argued.

*A `/DA` names a font that is not one of the standard 14.* One `/FreeText`
carries `/Baskerville 20 Tf`, the callout `/Helv 12`. decision 2's embedding question
has a case waiting in the corpus, and `/DR` carries the font to resolve it
against.

**Seeing them is nearly free, and that is measured.** All 44 *marks* carry an
`/AP`, and PDFium draws from it. The 41 `/Popup` entries carry none and need
none; they are where a mark's words are shown, not a drawing of their own.
Page one through this application's own render flag comes to 335,231 ink
pixels without annotations and 395,184 with -- and what appears is the highlight, the
underline, the strikeouts, both note icons, the free text, the callout, the
ink, the arrow, the polygon, the cloud, the connected lines, the square, the
circle, the carets, the paperclip and all six stamps, with no new code at all.
The form *values* are the one exception and come out blank, which is the
PDFium behaviour the rewritten rendering copy already exists to answer.

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
work.

The rest is editing, and the plan currently names five of the fifteen markup
kinds.

## Where the tools live

A menu cannot hold this. The application has one today -- five actions in a
Markup menu -- and it is the wrong shape twice over. It is swept into
`_editing_actions`, so it is disabled in read mode, which is the only mode its
tools act in. And a flat list cannot express twenty tools, the attributes each
carries, or which one is armed. What follows was read off Reader and then
decided for here; where the two differ, the reason is given.

**A floating strip, summoned from the toolbar.** Reader's tool list is
permanent furniture because marking up is what Reader is for -- and cannot
reliably be put away: the preference that remembers a collapsed tools pane
has been broken in Reader's Modern Viewer since 2023 by Adobe's own
account, and *"permanently close tools pane"* is an open request on their
feature site. Here it is a guest: this application is a page arranger, so the
strip is opened and closed from a toolbar button, floats over the reader, and
can be moved. Open or closed, and where it was dragged to, are remembered
between sessions; a remembered position is clamped back inside the reader, so
shrinking the window cannot leave the strip somewhere nobody can reach it. The button is
disabled in arrange mode and enabled in read mode -- the opposite of what the
markup actions do today, so they have to stop being treated as document-editing
commands by `_editing_actions`.

**It is a column, and that is load-bearing.** Reader's strip runs *down* the
left edge, families open *sideways* from it, and the tail is the bottom of the
column. Written down because it was once left out of this section and then got
re-derived wrongly from the word "below": a tail is the *end* of the strip, and
only on a vertical strip is the end underneath. On a row the tail would be at
the right-hand end, and "grows below" would describe a second row instead.

A page is also taller than it is wide, so a column sits in a margin where a row
lies across the text, and a flyout that opens to the side never covers the
families it is an alternative to.

**Families, as split buttons.** Twenty tools do not fit in a row, so they are
grouped and each group is one button: the button carries the icon of the tool
last used in that family and re-arms it, while the arrow beside it opens a
flyout listing the family with a tick on the current choice. Reader's grouping,
read off its tool list:

| family | tools |
|---|---|
| pointer | Select, Pan |
| comment | Add a comment, Replace selected text, Insert text, Add text comment, Attach file |
| text markup | Highlight, Underline, Strikethrough |
| drawing | Draw, Line, Arrow, Rectangle, Circle, Text callout, Polygon, Cloud, Connected lines, Stamps palette |
| signature | a picker of stored signatures and initials |

Two things fall out of that table. It groups by **what the gesture is**, not by
what the mark carries or what it is anchored to -- a third answer to the
grouping question decision 4 left open, and the only one with a shipping product
behind it. And it puts **Text callout** among the shapes while **Add text
comment** sits with the comments, though both write `/FreeText`: the tool is
the unit, not the subtype, and a family is not a subtype either.

**Attributes in the tail.** Below the family buttons the strip grows the armed
tool's own controls -- a colour swatch for anything that makes a coloured mark,
a thickness button for the line-based ones, an `Aa` opening a font panel for
the text-bearing ones.

The swatch is shown under *every* tool, the pointer included. This said the
opposite at first -- with Select armed nothing is being made, so there is
nothing to set an attribute of -- and that is wrong because the swatch has a
second job: it changes the mark you have *selected*, which is what you do
with the pointer armed. Observed in Reader, 2026-11-02: the swatch is there
with Select armed and with a tool armed alike, and picking a colour while a
highlight is selected recolours that highlight rather than arming the next
one. The alternatives were weighed: a fixed options bar under the main
toolbar, as Inkscape and GIMP have it; a docked inspector, as Figma and
Illustrator have it; the controls inside the flyout; and a bar beside the mark,
as Word has it. The tail wins for *arming* because before the gesture there is
no mark to put a bar beside, and because a tool is a mode that persists -- so
its attributes persist with it, which is what a tail expresses and a transient
bar does not.

**A tool is a mode.** Choosing one arms it, and it stays armed through mark
after mark until another tool is chosen or Escape is pressed. *Armed* is a
word for this document and not for the interface: it means the mode is set
and the next gesture on the page will use that tool. Not *selected*, which
in this application already means selected pages, selected text and -- from
highlight step 3 -- a selected mark.

Because arming sets a mode rather than lighting up a panel, **Escape returns
to Select whether the strip is open or not.** Closing the strip does not
clear the mode, so a tool can be armed with nothing on screen saying so,
which is the state where a way out matters most.

**The armed family is filled with the accent colour**, as Reader fills it.
With every flyout shut, that is the only thing on screen saying which tool a
drag would use.

**One declaration behind all of it.** Each tool is described once -- family,
icon, label, what it writes, which attributes it carries -- and the strip, the
flyout, the tail and the controls on a selected mark are generated from that
description. This is not tidiness. Using Reader turns up new attributes faster
than they can be designed -- a squiggly underline, a fill behind a text box, a
dash pattern -- and the declaration is what makes each of those a row rather
than a panel. It is also what makes one tool at a time cheap: a tool becomes a
declaration plus a gesture.

**What we are not copying.** Reader offers four routes to a mark's colour: the
swatch on the floating toolbar over the selection, the swatch in the tail with
the mark selected, the right-click menu's *Properties*, and the properties
dialog itself. That is twenty years of accretion. The question here is which
one or two are canonical, and it is not yet decided.

**Reader's, and deliberately not in the plan:** a right-click menu on a mark, a
comment panel listing every mark in the document, and *Set status* with a
*Review History* tab -- accepted, rejected, completed. The last is not an
attribute but a review workflow between people, recorded here so that it does
not leak into the attribute design.

## What every mark needs, whatever kind it is

**M1. Selected by clicking its ink.** Every kind, not only the ones we
author: a mark that can be seen and not selected cannot be edited, recoloured
or removed. By the ink and not by `/Rect` -- on page 1 of the test document
the 25 marks make 25 overlapping pairs by bounding box and a handful by ink,
so the choice is between a thicket and something nearly unambiguous. An
unfilled shape is its outline, so the inside of an empty rectangle is not the
rectangle. Which gesture belongs to the mark and which to the text under it is
O5.

The same test runs on *hover*, and that is not a refinement -- it is what
makes O5's rule usable. The pointer says in advance what the next gesture will
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
in the plan today, and the note work shipped with emptying one as the only
way to
take one back. Reader puts delete in a small toolbar on the selected mark,
beside edit and colour. A mark joined to another by `/RT /Group` goes as a
unit: deleting a replacement takes its icon, its insertion mark and its
strikethrough together, which is what M9 describes and what makes the three
pieces read as one thing.

**M3. Attributes, chosen before or after.** Reader carries one current colour
at the foot of its tool list, and it colours the next mark of any kind -- icon,
strikeout, text box, shape. A selected mark's colour can be changed afterwards,
and the two are the same control appearing in two places. The palette is
fixed: twenty-one swatches, seven hues over a pastel row and a greyscale row,
with a tick on the current one. No picker, no hex entry.

Colour is not alone. A highlight also carries **opacity**, which Reader shows
as 40% and which is the `/CA` this application already writes as
`markup.TRANSPARENCY`. A mark can be **locked**, which refuses the handles and
the delete. A line-based mark carries **thickness**, behind its own button in
the tail. A text box carries a **fill**, which Reader ties to the box colour.
Which attributes a tool has is part of what the tool declares.

An attribute can change *what is written* rather than how it looks: Reader's
underline can be squiggly, and in the file that is not a styled `/Underline`
but the separate `/Squiggly` subtype. The declaration has to carry both kinds,
and a family's flyout may therefore list what are really sibling subtypes.

Measured in `corpus/Markup Test Case.pdf`, and it carries a twist worth having
before the declaration is designed. A squiggly underline is written
`/Subtype /Squiggly` with `/Subj Underline` **and `/IT /Underline`** -- so
`/IT` is doing the opposite of its usual job here. Everywhere else it
discriminates between tools that share a subtype; on a `/Squiggly` it names
the tool a *different* subtype came from. Either way the rule that holds is
the one that matters: the file records which tool made the mark, so a squiggly
reads back as the Underline tool rather than as a fourth entry in the
family.

**Where the defaults come from.** Reader's properties dialog carries *Make
Properties Default*, so the mark in front of you sets what the next one will
look like. That is one mechanism instead of a preferences page per tool, and
it is why the same control appears in the tail and on a selected mark.

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
are already on the page, so it has nothing to pop up. decision 2 settles how those
words are drawn; this is about the other fourteen kinds.

**M7. Replies.** One of the two `/Text` marks carries `/IRT`, and Reader's
popup offers "Add a reply" under the author's name. Comments are threads, not
single notes.

## What the text-bearing kinds need beyond that

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

## What sits in the same tools without being markup

**M10. A stamps palette.** 24 in the test file, carrying names like
`/SBApproved` and an `/AP` we would not be drawing ourselves.

**M11. Stored signatures and initials.** Reader keeps them and places them on
the page. Distinct from the signature work, which is about *not* breaking
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
icon moves but does not resize, since its size is not its author's (decision 1 and
`markup.NOTE_SIZE`). Moving a grouped mark moves the group, by the same
argument that deletes it as one (M2). What a move writes is already understood
-- `/Rect` and whichever of `/QuadPoints`, `/InkList`, `/L`, `/Vertices`,
`/CL` and `/RD` the kind carries, which is the same list the resize work of
2026-10-29 already scales.

A text markup is the awkward one. Reader puts two round grips on a selected
highlight, and dragging one does not stretch a rectangle: it re-runs the text
selection between the two points and rebuilds `/QuadPoints` from whatever is
now covered. So a resize is two different operations depending on the kind,
and only one of them is geometry.

**M15. Changing a mark uses the surface that made it.** Clicking a mark gives
back what its tool gave when it was made -- the same editor, the same
attribute controls -- and on a text-bearing mark a double click goes to the
text. There is no separate editing mode to design: M1's selection is a second
door into the tool's own surface. Seen in Reader on a text-bearing mark and on
a highlight, which has no text at all, so it is not a property of the
text-bearing kinds.
## The popup note

Every markup kind can carry one, and it works the same way for all of them.
Measured on a highlight with a note, a reply and two status changes.

**The text is `/Contents` on the mark**, not on the `/Popup`. The `/Popup`
object carries no appearance at all, is marked `/Open false`, and sits at
`/Rect [612, 539.9, 796, 631.9]` against a 612-wide page -- entirely off the
paper. It is a placeholder saying where Reader should put *its* window.

**The chain is a history and the status is a state.** Observed 2026-11-02 on
a highlight whose chain reads `Accepted` -> reply -> `Completed`: the panel
Reader shows at the pointer says "(1 Reply / 1 Status)", counting the
*current* status rather than the two in the chain, and the opened pop-up
shows one status row with a tick. Review History shows both, with times --
"dws: Accepted, 11/1/26, 2:33:27 PM" and "dws: Completed, 11/1/26,
2:37:03 PM". So three surfaces say three different true things: how many
statuses there are *now* (one), what it is (Completed), and how it got there
(the chain). The last is the properties form, highlight step 9.

**The pop-up is a thread, not a text box.** Author and time at the top, the
note's own text editable in place with Cancel and Post, the current status
on a row of its own, and then each reply beneath with its own author, date
and editor. Reply is reached from the note's menu or from the mark's
right-click menu, which also carries Delete Thread, Set status, Copy Text,
Enable Text Selection, Open comment panel, Open all Pop-Ups, Minimize
Pop-Ups, Make current properties default and Properties.

So **a popup note is viewer chrome, and no appearance-stream renderer will
ever draw it**. PDFium draws the highlight and nothing else, which is why a
noted mark looks unremarked here. Whatever shows it, we draw ourselves from
the parent's fields.

Reader writes the text twice: `/Contents` as plain text and `/RC` as rich
text, 306 characters of it for a fourteen-character note.

**`/RC` is XHTML, one `<span>` per run, and the file prefers it.** Measured
on 2026-11-03 against a corpus document styled in Reader, with the words
replaced by their lengths:

```xml
<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml"
      xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/"
      xfa:APIVersion="Acrobat:26.2.0" xfa:spec="2.0.2">
  <p dir="ltr">
    <span dir="ltr" style="font-size:-14.0pt;text-align:left;
          font-weight:normal;font-style:normal">[8 chars]</span>
    <span … font-weight:bold …>[7 chars]</span>
    <span … text-decoration:underline; font-weight:normal …>[14 chars]</span>
  </p>
</body>
```

Three things that shape what we do with it. **A note with any styling in
it gets one span per run, the plain runs included**, each carrying the
whole property set, so there is no "plain" run to detect -- only values to
compare against the defaults. A note with no styling anywhere gets no span
at all, just a bare `<p>`; measured across the twelve marks of the fixture,
where the unstyled notes and every status link are bare and the styled ones
run to three and four spans.
**The size is written negative**, `font-size:-14.0pt`, which reads as
"not set, and the default is 14"; it is copied rather than interpreted,
and dropped on the way in because a negative size is not a size. And
there is **no `/DS`** anywhere -- the styling is inline on the span. The
properties seen are `font-weight`, `font-style`, `text-decoration`,
`text-align` and `font-size`; of those only the first three say anything
a note's reader can see, and `vertical-align` joins them for super and
subscript.

Because a viewer that understands `/RC` prefers it, writing `/Contents`
and leaving the producer's `/RC` beside it shows the words that were
replaced. The two are written together or not at all.

The one-line summary under the pointer shows the styling as well, which
means it is drawn through a `QTextDocument` rather than with `drawText` --
and measured by the same document that draws it, so the box fits a note
that wraps.

**A reply carries a status of its own.** Measured 2026-11-03 on a corpus
document with three replies under one note: the note's chain reads
`Accepted -> Completed -> Accepted -> Completed`, and each reply has a
separate chain beside it -- `Completed -> Completed`, `Cancelled`,
`Cancelled`. Nothing in the format makes this special: a reply is a mark,
and a status points at whatever it answers, so the chain walk that finds
a mark's history finds a reply's too.

**Replies are visible marks in their own right.** A reply is a `/Text`
annotation with `/IRT` pointing at the mark and `/F 28` -- Print, NoZoom,
NoRotate -- so it draws a comment icon anchored to the top left of the
parent's rectangle. Adding one changed 72 pixels on the page. It is page
content, not chrome, and it has to survive and render whether or not we ever
let anyone write one.

**A status change is a hidden child.** Also a `/Text` annotation with
`/IRT`, but carrying `/State` and `/StateModel /Review`, and `/F 30` -- the
same flags *with* Hidden. It never draws.

**`/RT` does not tell the two apart.** It is absent on replies and on
statuses alike, which the specification reads as a reply. The discriminator
is the presence of `/State`.

**The status history is a chain, not a list.** The first change points at the
mark; each later one points at **the link before it**. Walking only the
mark's direct children finds the first change and misses every one after it.

```
/Highlight
  |-- /Text  /State Accepted    -> the highlight   hidden
  |     \-- /Text  /State Completed -> that link   hidden
  \-- /Text  reply              -> the highlight   visible, icon on the mark
```

## The properties form

Three tabs and a footer, and only one of the tabs varies by kind.

**Appearance** is the tool's own: colour and opacity for a highlight,
thickness for a line, a font panel for a text box. It is the only part a tool
supplies, which is what lets a new tool arrive as a few rows rather than a
dialog.

**General** is three keys, the same for every kind: Author is `/T`, Subject
is `/Subj`, Date modified is `/M`. `/CreationDate` sits beside them. **The
first two are editable**, measured 2026-11-03 on a corpus document whose
first highlight had both changed -- an earlier reading of this form as
read-only was wrong.

`/Subj` starts as the name of the tool that made the mark, and every kind
has one. Read off `Markup Test Case.pdf`:

    /Highlight  Highlight       /StrikeOut  Cross-Out    /Ink     Pencil
    /Text       Sticky Note     /Squiggly   Underline    /Circle  Oval
    /Caret      Inserted Text   /Square     Rectangle    /Line    Line
    /FreeText   Callout, or Text Box
    /Stamp      the stamp's own name -- Approved, Draft, Void, Sign Here

It is free text once the form is open. **Where it surfaces in Reader is
not known**: the owner looked in the Comments panel on 2026-11-03 and it is
not shown there, so a guess that it labels a comment in that list was
wrong.

**Review History** is the chain above, read back. Its rows are *derived*, not
stored: Reader composes `{/T}: {/State}, {/M}` and prints
*"dws: Accepted, 11/1/26, 2:33:27 PM"*. The `/Contents` each link carries --
19 and 20 characters in the sample, matching "Accepted set by dws" and
"Completed set by dws" -- is a sentence Reader generates for other viewers
and does not itself display. Nothing here is editable; the only writable
thing is setting a new status, which appends another link.

**The footer shows on all three tabs.** *Locked* is `/F` bit 8, taking `/F`
from 4 to 132 -- confirmed 2026-11-03 on a locked highlight. **`LockedContents`
(bit 10, 512) is not used**: the one checkbox sets the one flag, and nothing
in the corpus carries the contents lock at all. *Make Properties Default*
writes nothing to the file: it is the application's own preference for what
the next mark gets.

**A reply has a form of its own, with the same three tabs.** Measured on
the same document 2026-11-03, where one reply was locked and given its own
author and subject; its `/F` went from 28 to 156, the same bit on its own
annotation.

Its *Appearance* is the sticky note's, not the highlight's: an icon list --
Checkmark, Insert Text, Circle, Comment and the rest -- with Color and
Opacity beside it. The icon is `/Name`, and every `/Text` in the corpus
carries `/Name /Comment`, replies and status links alike. So a reply does
have an appearance to set; an earlier note here that it had none was
wrong.

Its *Review History* is **the reply's own**, and nothing else: on a reply
whose chain is one link, Reader shows that one line. Which is the same
rule the chain walk had to learn on the same day -- a reply's history
hangs off the reply, not off the mark.

So the two forms are not two models. **They write the same keys on
whichever annotation the form was opened on**, and what differs is which
appearance the kind has. Nothing reaches the thread: a locked mark leaves
its replies unlocked, a renamed author leaves theirs alone, and the subject
likewise -- not because of a rule about threads but because each reply is
an annotation with an `/F`, a `/T`, a `/Subj` and a `/Name` of its own.

**What a lock has to mean here** is a rule across the whole of highlight
step 8, not a checkbox in highlight step 9: on a locked item the editor, *Reply*, *Set status*,
*Delete*, the colour and the grips all have to refuse -- and per item, since
a locked reply sits in a thread whose other items are not.

## The right-click menu

One menu for every mark, in five groups. Read off Reader on 2026-11-02, in
all three of the states it has:

    no comment          comment, no reply   comment with replies
    ──────────────────  ──────────────────  ────────────────────
    Open Pop-Up Note    Open Pop-Up Note    Open Pop-Up Note
    ──────────────────  ──────────────────  ────────────────────
    Delete              Reply               Reply
    Set status      ▸   Delete              Delete Thread
                        Set status      ▸   Set status      ▸
    ──────────────────  ──────────────────  ────────────────────
    Copy Text           Copy Text           Copy Text
    Enable Text Sel.    Enable Text Sel.    Enable Text Sel.
    ──────────────────  ──────────────────  ────────────────────
    Make current properties default
    Properties...

So two things vary and nothing else does. **Reply appears when there is a
comment to reply to**, and *Open Pop-Up Note* stays above it either way --
it is how the note is reached whether or not one has been written, and it
does not turn into Reply. **Delete becomes Delete Thread when there are
replies**, not when there is a note, which is the same rule the deletion
dialog follows: the word changes when somebody else's writing is at stake.

*Set status* opens five, with the current one ticked, read off the owner's
own notes on Reader rather than guessed:

    None        ticked when the mark has no status
    Accepted
    Cancelled
    Completed
    Rejected

*None* first and the other four alphabetical. A status is not an attribute
of the mark: setting one appends a hidden `/Text` carrying `/State`,
`/StateModel /Review` and an `/IRT` pointing at the last link in the chain,
so the tick shows the *last* status rather than the only one.

*Copy Text* copies the text the mark covers -- what is under its
quadrilaterals, not whatever the page selection happens to be.

*Enable Text Selection* is the per-mark remedy for a highlight swallowing
clicks that were meant for the page, and **without it there is no way to
select text that a mark covers at all**. It is not a property of the mark
and nothing about it is written: it lets the *next* click through to the
words underneath, and lasts only until the next selection. Reader shows
this plainly -- after it is used, the right-click menu on that spot is the
ordinary text menu (Copy, Edit text, Export selected text, Redact text,
Highlight text, Strikethrough text, and the two that make a comment out of
a selection) rather than the mark's.

**Three of Reader's entries are deliberately left out**: *Open comment
panel*, *Open all Pop-Ups* and *Minimize Pop-Ups* (Cmd+7). There is no
comment panel here and no pop-up windows for one to manage, and an entry
for a feature with nothing behind it is not the same as a button waiting
for the step that turns it on. Taken by the owner on 2026-11-02. They come
back if a panel is ever wanted.

## The menus inside the pop-up window

Four of them, read off Reader on 2026-11-03, and they are not the same
menu as the one on the mark.

    on a reply's author line   on the first item, or the window's
                               own background
    ────────────────────────   ─────────────────────────────────
    Reply                      the mark's own menu, less *Open
    Delete                     Pop-Up Note*: Delete Thread, Copy
    Set status            ▸    Text, Enable Text Selection, Make
                               current properties default and
                               Properties...

*Open Pop-Up Note* is left out inside the window: the thread is already
showing, and Reader leaves it out there too.

**The first item is the comment, so its line gives the mark's menu.**
There is no deleting it on its own: the replies hang off it, and taking
it out is *Delete Thread*. Settled with the owner on 2026-11-03. On a
reply, *Delete* is the whole reply and the status chain under it -- not
the words in it, which are edited by clicking them.

The other two are the text's. Reader offers an editing menu over an
item's text whether or not that item is open for editing, with *Undo Text
Change*, *Paste Text*, *Delete Text*, the platform's spelling and
dictionary entries, and *Text Style* carrying Bold, Italic, Underline,
Superscript, Subscript and Clear Formatting. **Ours has no menu over text
that is not being edited**: clicking the text opens it, and the menu is
the editor's. Settled with the owner on 2026-11-03 -- the entries all act
on the text, and the text can always be reached by opening it.

Inside the editor the standard entries come from Qt and are the ones every
other text box in the application has. **The spelling and dictionary
entries are not ours to offer**: they are services of the platform's own
text system, which Qt does not hand us.

## Highlight

The first tool through, and the one plan step 3 builds. Everything here
was read off `corpus/Markup Highlight.pdf` and the owner's notes on Reader.

`/Subtype /Highlight` with `/QuadPoints` -- thirteen quads on the first
sample, because a highlight spans paragraphs and columns -- a `/Rect`
enclosing them, `/C` for colour, `/CA` for opacity, `/F 4` for Print, and
`/Subj Highlight`. It covers text only, never pictures.

### What a highlight can contain

**The tool is armed first and the drag makes the mark.** There is no step
where an existing selection becomes a highlight: Reader requires the tool
before the gesture, so a selection made while reading never turns into one.
That is also why the right-click menu offers *Enable Text Selection* -- once
marks are on a page they swallow clicks meant for the text underneath.

**A highlight is an index range on one page.** Both ends of the drag resolve
to character indices and everything between them is taken. The index order
is the order the text is *stored in*, which is not always the order it is
read in, and when the two differ the highlight covers text the eye did not
sweep.

Measured on page 7 of the ARRL Handbook, whose three columns are stored
**column 1, then column 3, then column 2**:

| the drag | what is highlighted | because |
|---|---|---|
| column 1 → column 2 | part of 1, **all of 3**, part of 2 | 3 lies between them in the index |
| column 1 → foot of column 3 | part of 1 and all of 3, **no** 2 | 2 comes after 3, so it is not in the range yet |
| the same, carried to the page end | 2 joins as well | the range now runs past 3's last character |
| column 1, straight down | column 1 alone, until the page end | then both other columns are inside the range |

A drag from the middle of column 1 to the middle of column 2 selects all 78
of column 3's runs along with the 36 and 28 it was asked for: 4,630
characters. **Reader does exactly the same on the same page**, which settles
that this is the file's own reading order and not a defect in either tool.
Reordering it would be overruling what the document says about itself, which
is wrong wherever that order is deliberate -- a sidebar, a caption, a pull
quote.

**Underline and Strikethrough behave identically.** Same gesture -- tool
armed, then drag -- same index range over the file's stored order, same clamp
to the page, same handles. They differ only in what they write: `/Underline`
and `/StrikeOut` over the same `/QuadPoints`, and no `/CA`, because opacity
belongs to the highlight alone.

**It stops at the page edge.** `/QuadPoints` live in one page's coordinate
space and the annotation lives in that page's `/Annots`, so a highlight
cannot span pages however anyone feels about it. The drag that makes one
therefore stops at the boundary rather than carrying on, and the handles that
reshape it cannot be dragged past either end of that page's text. Reader does
the same.

This is where the highlight gesture and ordinary text selection part company:
**text selection deliberately crosses page breaks** -- a reader that stops at
one is not much of a reader -- and the highlight tool's drag deliberately does
not.

**Its appearance is three forms deep.** The `/AP /N` sets the opacity and a
`/BM /Multiply` blend, calls a transparency-group form, which calls a third
holding the actual fills. The innermost form's `/BBox` is in *page*
coordinates with a `/Matrix` translating it to the origin, which is how the
chain lines up with `/Rect`. Worth knowing before anyone tries to write one.

**In the tool's Appearance tab:** colour from the twenty-one swatches, and
opacity by slider or by a percentage field. Reader's five colour pickers --
wheel, sliders, named colours, spectrum, crayons -- are the macOS picker and
are not copied; fixed swatches with no picker was settled earlier.

**Selected by clicking it with the tool armed**, which puts handles at the
extremes of the run. Dragging one re-runs the text selection and rebuilds
`/QuadPoints` rather than stretching the old quads, because a highlight is a
run of text and not a box.

**What a click produces depends on what is armed.** With Highlight armed,
clicking a mark raises a floating bar over it -- *add a comment*, a colour
swatch, *delete* -- the mini-toolbar pattern, and a shortcut to three things
the right-click menu also offers. With Select armed there is no bar, only the
selection. **Right-click works in both**, so the menu is the surface that is
always there.

That puts two of Reader's four routes to colour in from the start, and they
are the two worth having: the swatch in the strip's tail arms the *next*
mark, the swatch in the bar changes the one you clicked.

### Building it, in order

Each step is usable before the next, and each tells the next what it needs.
Cited as **highlight step 1** to **highlight step 9**.

1. **Hold the marks.** A page's annotations read into a session table with
   uids -- enough to hit-test and to know what is there. Nothing written.
   `markup.MarkMap` and `markup.marks_in`. **done 2026-11-01**
2. **Arm the canvas from the strip.** Highlight armed, drag over text, mark
   made. The strip drove nothing until now. **done 2026-11-01**

   Two things were found by using it rather than by planning it. The feedback
   was the reader's text selection, which runs across pages, while the mark
   it produced stopped at the page, so the band shown was never the band
   kept; marking up now has a gesture of its own and one list of
   quadrilaterals serves as both. And the band was too short, because Qt's
   selection bounds are tight to the ink, which is decision 11. Writing the
   mark with the keys a reader expects came out of the same session and is
   decision 10.
3. **Select an existing one**, including a mark the file brought, which is
   the first thing the uid table buys. The selected-mark border belongs
   here: Reader draws one round each quadrilateral, and drawing it needs a
   hit test, a selected-mark state and the rules for leaving it.

   **done 2026-11-02**

   It was marked done once before it was. A mark that carries a note was
   drawn exactly like one that does not, and Reader draws two things it did
   not: a badge at the mark's top left whenever there is a note, shown
   selected or not, and a panel at the pointer with the author, the counts
   and the text. That is *displaying* a mark correctly, which is this step,
   and not creating one, which is highlight step 8 -- selecting a mark you
   cannot tell has a note is half the step.

   Nothing new was needed to read it: `Mark.contents` holds the text and
   `MarkMap.children` walks the chain, both built in highlight step 1 and
   until then unused. `Mark` gained `/T` so the panel can say who wrote it,
   and `MarkMap.thread` answers the counts the way a reader states them.

   The panel is drawn rather than left to a tooltip. A tooltip waits for
   the pointer to settle and then vanishes on its own, and the first
   attempt used one -- which showed, in practice, nothing at all.

   Clicking a mark picks it up under the pointer and under any text-markup
   tool -- pressing on a highlight with the highlighter armed means *that
   highlight*, not the start of a second one over it. The area tools keep
   the press, because a rectangle or an arrow is drawn across whatever is
   underneath. Escape and a click on bare paper let go.

   The outline also appears when the pointer is merely over a mark, under
   every tool, which is decision 13. The three buttons beside a selected
   mark are drawn and disabled; each is turned on by the step that builds
   it, which is decision 14.
4. **Colour and opacity**, which is where our appearance replaces the one
   Reader wrote: an `/AP` that still draws the old colour is worse than one
   we generated. **done 2026-11-02**

   Twenty-one swatches and an opacity slider, reached from two places: the
   tail arms the next mark, the bar changes the one you picked, and both
   open the same popup. The ownership question this step was waiting on is
   decision 17, the palette is decision 18, and showing a change without
   rebuilding the document is decision 19.
5. **Open what was written in Reader.** Save a document this application
   has marked up -- one it created a highlight in, and one it recoloured a
   mark the file already had -- and open both in Reader. Check that the
   marks are there, in the right colour at the right opacity, that they are
   still selectable and editable *there*, that a comment thread on a
   recoloured mark still reads, and that nothing else about the document
   moved.

   **This cannot be automated here and should not be faked.** There is no
   Reader on the machines that run the suite, and the round trip that is
   automated -- plan step 1, every annotation out and back -- compares this
   application's output against this application's reading. That is exactly
   the comparison that cannot notice the two agreeing on something wrong.

   It belongs after colour because colour is the first step that changes a
   mark the document arrived with, and because it *removes the appearance
   stream the producer wrote*: the saved file now asks Reader to draw the
   mark from its quadrilaterals. Every reader is supposed to, and "supposed
   to" is why this step exists.

   **done 2026-11-02**, for colour and opacity. `Markup Highlight Write.pdf`
   carries both cases -- a highlight this application created, and three of
   Reader's recoloured by it -- and opens cleanly in Reader with the marks
   where they belong. The comment thread on a recoloured mark came through
   whole: same note, same reply, same current status, with only `/C`
   changed.

   **Repeated after every later step that writes**, rather than done once.
   Resizing rewrites `/QuadPoints`, deleting takes a status chain and its
   replies out of the file, and each of those is a new way for a document
   to come out subtly wrong in a tool this project cannot run.

   **Repeated 2026-11-02 for the resize**, and it reads correctly in
   Reader: a mark the file brought, resized here and written out, comes
   back covering the run it was dragged to.

   **Repeated 2026-11-02 for the delete**, and it opens as expected in
   Reader. A highlight carrying a reply and a two-step status chain was
   deleted here and the document written out: the page it was on came back
   with its two links and all fifteen widgets and nothing else -- no
   `/Highlight`, no `/Text`, none of the four `/Popup` objects -- while the
   highlights on the other two pages were untouched, popups and all. The
   deletion reached one page and stopped there.

6. **The handles, and resizing by them.** Two round grips, white with a
   blue ring, one at the start of the run and one at its end -- shown for a
   *selected* mark and never for a merely hovered one, which is the third
   state decision 13 now records. **done 2026-11-02**

   Dragging one re-runs the selection between the new pair of points and
   rebuilds `/QuadPoints` from whatever is now covered, rather than
   stretching the quads that are there -- a highlight is a run of text and
   not a box. This was in the plan's acceptance and in M13 from the start
   and was missing from this list, which is the omission, not the design.

   After colour rather than before it, although resizing raises no question
   of its own and colour does. Both change a mark that already exists, so
   whichever comes first has to answer what export writes from, and colour
   is the better place to answer it: it has to face replacing the `/AP` the
   producer wrote, so it settles the question completely instead of only as
   far as geometry. The work left here is then small, because dragging a
   grip is `textlayer.quads` recomputed from a new pair of points, and that
   is machinery highlight step 2 already built.

   What the drag looks like while it is in flight is decision 21. The
   resize was recorded and written correctly from the first day it worked
   and could not be *seen*: the one-page re-render of decision 19 applied
   colour and opacity and had no case for the quadrilaterals, so the page
   came back from a document that still held the old run. It and the export
   patcher were near-copies and only one of them grew the case. They are
   now one `markup.apply_edit`, which is the point: the next field cannot
   reach only one of them.
7. **Delete**, taking the status chain and the replies with it.
   **done 2026-11-02.** From the trash in the bar beside a selected mark,
   and from the Delete key, which Reader also gives to the selected mark --
   so the window's own Delete, which removes *pages*, keeps the key only
   while no mark is selected. A mark with replies asks first, in Reader's
   words and with Cancel as the default, because what is being warned about
   is somebody else's words going with yours; a status makes no difference
   to the dialog, and neither does a note nobody has answered. The dialog
   is not suppressible, as Reader's is not.

   *Delete Thread* belongs to the right-click menu in highlight step 8;
   this step is the button and the key.
8. **The right-click menu, and the pop-up note with it.** *Open Pop-Up
   Note* is one of its entries, so this is where a note on a mark is made
   rather than a step of its own: the note has no surface until the menu
   that opens it exists. The bar's comment button is the same action from
   the other direction and is turned on here too.

   This is the work three other places defer to. The bar's first button is
   drawn and disabled waiting for it; decision 10 leaves `/Popup` and `/RC`
   unwritten for it; decision 14 names it. What the format wants is already
   settled in *The popup note* -- the text is `/Contents` on the mark, the
   `/Popup` is viewer chrome with no appearance of its own -- and
   `canvas.edit_note` already edits a sticky note's text, so the editor
   exists.

   What it has to decide rather than inherit is whether `/RC` is written
   beside `/Contents`. That is the rich text question, and a comment is
   where it first bites.

   **Set status arrives with it**, settled with the owner on 2026-11-02:
   the menu is how it is reached, and a menu whose entries do nothing is
   not the menu. Both of those write to the file -- a note writes
   `/Contents`, a status appends a `/Text` carrying `/IRT` and `/State` --
   so each wants the Reader round trip of its own that the fifth step asks
   for. The menu itself writes nothing and lands first, carrying the
   entries already built: Delete and Delete Thread, Copy Text, and *Make
   current properties default*, which sets what the next mark is given and
   touches no document at all.

   **The properties form is not part of this**, by the same decision. The
   menu carries the entry that opens it and the form is built in the step
   after, so this step stays the menu, the note and the status.

   **The menu and the note are done, 2026-11-03.** The menu carries what
   acts and draws the rest; the note is a window over the page listing the
   mark's own text and each reply beneath it, with only the selected item
   editable and Post refused while it is empty. *Reply* adds an empty item
   and posting it writes a `/Text` carrying `/IRT`, `/F 28` and the parent's
   colour. `/Popup` is now written for every mark at the geometry Reader
   uses, a window the file left open opens on hover, and moving or resizing
   one is recorded to `/Popup /Rect`.

   **Set status is done too, 2026-11-03.** Five states, the current one
   ticked, and choosing one appends a hidden `/Text` carrying `/State`,
   `/StateModel /Review` and an `/IRT` pointing at *the link before it* --
   so a status is never overwritten and Review History keeps the sequence.
   The five are written as Reader writes them and shown translated: a
   `/State` in another language is a status no other application matches.

   **The rich text, the per-item menus and the per-reply status are done,
   2026-11-03**, after the owner found them in Reader while trying the
   step. `/RC` is read and shown, written with the text and dropped when
   there is none (decision 27); every item in the thread carries its own
   status row and menu (decision 24); and the window's menus are
   decision 30. The question this step "has to decide rather than inherit"
   is therefore decided: `/RC` *is* written beside `/Contents`.

   A note the *file* brought needs none of this and already survives: it
   comes through an export untouched because a mark is patched rather than
   replaced, which is decision 17 and is what highlight step 5 checks.
9. **The properties form**, last, because General and Review History are
   read-only views of what the earlier steps put in place. Reached from the
   menu above, which carries its entry from the start, and built separately
   afterwards.

   **Done 2026-11-03.** *Comment properties*: three tabs and a footer, one
   form for every kind, opened from *Properties...* in the mark's menu and
   in a reply's. It writes three keys and one flag -- `/T`, `/Subj` and
   `/F` bit 8 -- and only where they differ from what it was given, so a
   mark whose colour was touched keeps the author and the subject the
   producer gave it.

   Appearance reuses the palette the swatch in the tool strip opens, rather
   than a second one of its own: two pickers that have to agree about
   twenty-one colours and a slider are two things to keep in step. **The
   icon list Reader offers for a note is not built** -- it writes `/Name`,
   and an icon chooser that writes a name this reader does not draw would
   make the document say one thing and the page show another. It waits for
   the icons.

   General's Author and Subject are editable, which an earlier reading of
   this form had wrong. Review History is composed, not stored. The footer
   is *Locked* and *Make Properties Default*, the second of which writes
   nothing to the file.

   **A locked mark opens the form** -- it is where the lock comes off --
   and everything in it that would change the mark is refused until the box
   is cleared, which takes effect without closing it.

## The test

Load that document, see every annotation in it, and be able to edit every one.
Seeing it is measured above and nearly done. Editing it is M1 to M15, and the
user interface need not resemble Reader's -- only the functionality.

**And lose nothing.** The owner's standard, 2026-10-31: "I would just like to
be able to do the markup and not lose anything when it is opened in our tool."
That is stronger than editing, and it applies to every mark including the ones
no tool of ours will ever make. A document that goes through this application
and comes out with a mark changed, dropped or flattened has failed the test
even if every tool worked. It is also the one part of the test that can be
run without a user interface, which is why it is this plan's first step.

## Plan

What the earlier markup plan was trying to be, ordered so that nothing has
to be specified
before something needs it. Each step is useful alone, and each one tells the
next what it needs.

Cited as **plan step 1** to **plan step 4**. Each tool has an order of its
own, cited by the tool's name -- **highlight step 1** and so on -- because
"step 4" alone will mean one of twenty-odd different things before this is
finished. Numbers rather than descriptions, deliberately: a number can be
found in a document and "the step that settles colour" cannot, and the churn
of renumbering is cheaper than the search. `tools/check_docs.py` fails a
citation to a step that does not exist, which is what a renumber leaves
behind.

| # | Step | Depends on | Done when | State |
|---|---|---|---|---|
| 1 | Every mark in the test document survives a save | marks being drawn | every annotation in the document comes back from an export unchanged | **done 2026-10-31** |
| 2 | The tool surface | 1 | the strip opens from the toolbar, arms a tool, has a tail for the attributes to arrive in, and disarms on Escape | **done 2026-11-01** |
| 3 | One family through: Highlight, Underline, Strikethrough | 2 | all three make, select by clicking, recolour, resize, delete and reopen -- and those three kinds are in the model whether the user made them or the file arrived with them | |
| 4 | The remaining tools, one at a time | 3 | each tool brings its own kinds into the model as it arrives | |

**Plan step 1 first because it has no screen**, and it is done. A document that goes
through this application comes out with every annotation it went in with:
proved on all 180 marks in the test document, on every fixture, and on 8,697
annotations across the validation corpus. No window, no gesture, no model.

**Nothing is editable at the end of it, and that is the point.** The marks
survive because they *travel with the page* -- `copy_foreign` carries each one
across as the dictionary it already was, and at no point does this application
look at a mark, understand it or hold it. `markup.Annotations` is empty for
every document opened and `markup.Annotations.add` still has exactly one
caller, a user gesture. Editing begins at plan step 3.

**Which is what lets the work go one tool at a time.** A mark is modelled by
the step that gives it a tool: plan step 3 reads `/Highlight`, `/Underline` and
`/StrikeOut` into the model because recolouring one needs an object to
change, and plan step 4 does the same for each kind as its tool arrives. Everything
with no tool yet stays a passenger, written back as the dictionary it came in
as. The test document holds eighteen subtypes and `markup.KINDS` holds three;
the gap is not a backlog, it is the sixteen kinds that nothing is asking to
edit yet.

So *lose nothing* does not wait for the model to be finished -- it is already
true, and it stays true by construction while the model is widened one tool
at a time.

**There is an ownership question waiting at plan step 3.** `markup.add_to_page`
*appends* to a page's `/Annots`, and a page reaches export already carrying
the annotations it was copied with. The moment a mark is both in the file and
in the model it would be written twice, so the step that first reads a file's
marks in has to decide what export writes from. Not yet decided, and it does
not need to be until plan step 3.

**Plan step 1 has already found one thing, before any of it was built.** Round-tripping
`corpus/Markup Test Case.pdf` through `export()` failed outright -- qpdf
refusing the save with "unexpected object id encountered in
getCompressibleObjGens" -- for every page, while plain pikepdf saved the same
file without complaint. `_restore_acroform` copies `/DR` entries one level
down when they are dictionaries, and assigns anything else straight across
from the input document; a squiggly underline puts a tiling Pattern *stream*
in `/DR`, so the output ended up owning an object it did not own. Fixed by
copying it like the rest. With that done the round trip loses no markup at
all: all 44 marks come back with every attribute identical -- subtype, `/IT`,
`/Subj`, colour, opacity, quads, border, flags, `/IRT` and `/RT`.

The two `/Sig` widgets were a second finding and not, as first written here,
the signature rule
working correctly. They had never been signed, and turning them into read-only
`/Stamp` annotations destroyed two fields that were waiting for a signer. See
*What this application does with a signature*, below.

This is the shape plan step 1's test should take: load, export, and compare the
annotations on both sides key by key. No window, no gesture, and it would have
caught the bug above the first time a document with a pattern resource went
through.

**Plan step 3 is the text-markup family rather than Comment**, which amends decision 4; the
argument is recorded there.

**Plan step 4 is deliberately not a list.** What each tool needs is written down when
that tool is built, not before. The declaration in *Where the tools live* is
what keeps that honest: a tool that turns out to need an attribute nobody
anticipated costs a row, and the inventory can keep growing without becoming
a specification.

## Still open

Numbered within this document. A number is assigned once and never
reused: when an item is settled it leaves this list and becomes a
numbered decision below, so a gap means something was decided, not
lost.

- **O1. Whether free text is typed on the page or in a popup.** The note's
  editor is a fixed 240 by 120 panel beside the icon, which suits a mark whose
  content is hidden behind an icon, and it is written and works at any zoom.
  Free text is *on the page*, so the expectation is to see it at page size, in
  position, while typing -- a `QTextEdit` positioned and scaled to the box at
  the current zoom, which is more work and is the only one of the two that can
  show what the file will actually contain, now that decision 2 fixes the font and the
  size is ours. Either way the size is a length in the source page's space
  under decision 1, so it divides going in and multiplies coming out exactly as the
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
  changes, which is what Reader does. `/InkList` holds either -- measured,
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

- **O4. Which stamps, if any, this application offers.** Showing them is
  already free: 24 in the test document, every one with its own `/AP`, all
  drawn by our renderer with no code. Offering them is a different question.
  Reader's palette holds 22 in three families -- 13 Standard Business
  (Approved, Rejected, Not Approved, Draft, Final, Completed, Confidential, For
  Public Release, Not For Public Release, For Comment, Void, Preliminary
  Results, Information Only), 4 Sign Here (Sign Here, Initial Here, Witness,
  Accepted) and 5 Dynamic (Revised, Reviewed, Confidential, Received,
  Approved). Measured in `corpus/Markup Test Case.pdf`, where all 24 carry the
convention in `/Name` itself: `/SBApproved`, `/SHSignHere`, `/#DRevised` and
so on, so the family is readable off the name and a document's stamps can be
shown back by family without a lookup table. The names are a convention we can
follow, but the *artwork* is
  Adobe's and cannot be copied, so offering any stamp at all means drawing our
  own. The dynamic five need more than artwork: their appearance bakes in the
  author and the moment of placement -- the test document's read "REVISED 9:45
  pm, Oct 30, 2026" and "REVIEWED By ... at 9:45 pm, Oct 30, 2026" -- which is
  generated at placement, not picked from a palette. So the choice runs from
  none, through a small set of our own, to all three families. Not decided.

- **O6. Whether to offer a Fill in form fields family.** It appeared in
  Reader during this work -- not in any earlier run, so it arrived with a
  version update, 2026-11-02 -- as a sixth family button between the drawing
  tools and the signature pen. Its flyout holds six: **Type text** (the
  default, ticked), **Crossmark**, **Checkmark**, **Dot**, **Circle around**
  and **Cross out**.

  It is markup pretending to be form filling, which is why it is a question
  rather than an entry in *The tools*. The six are the marks somebody makes
  on a *printed* form -- an X in a box, a tick, a ring round a choice -- and
  Reader offers them for documents whose "fields" are lines on the paper
  rather than `/Widget` annotations. So it overlaps this application twice
  over: the five that are not Type text are ordinary drawing marks with
  fixed shapes, and the forms layer already fills the fields that really are
  fields.

  What makes it worth considering rather than dismissing: it is the honest
  answer to a form that has no fields, and this application meets those --
  the signature work turned up a disability form whose signature lines were
  drawn on, not declared. Whether that is a family of its own, or six stamps
  under *Stamps palette*, or nothing at all, is undecided. Nothing in the
  plan depends on it.

  **Reader shows it only on a document with no fillable fields**, which is
  the thing that makes it coherent. Observed 2026-11-02: the family is there
  on the Handbook and absent on the Devoted Health form. What separates
  them, measured, is not whether there is an `/AcroForm` -- both have one --
  but whether it holds anything::

      ARRL 2021 Handbook        /AcroForm, 0 fields,  0 widgets  -> shown
      Devoted Health C-SNP      /AcroForm, 82 fields, 86 widgets -> absent

  So the tool is offered exactly where clicking a field is impossible,
  which is the case it exists for. Reader is reported to withhold it on a
  signed or permission-restricted document too; that part is not verified
  here.

  **Nothing in the format restricts them**, and it is worth being clear
  that the rule is Reader's and not the PDF specification's. The six are
  ordinary resizable graphical annotations -- a checkmark and a crossmark
  are `/Stamp`, the ring is `/Square` or `/Circle`, the cross-out is
  `/Line`, the typed text is `/FreeText` -- and they sit perfectly happily
  beside fields. `markup.pdf` is the proof: 82 fields, and its first page
  carries 15 widgets alongside 25 markup annotations including `/Square`,
  `/Line`, `/FreeText`, `/Ink` and five `/Stamp`s. Reader opens it and draws
  all of it. What Reader declines to do is *create* them there.

  **The restriction makes sense as a guardrail.** On a form with real
  fields, drawing a tick beside a checkbox gives a page that looks filled in
  and holds no data -- the `/V` is still empty. Reader's business is getting
  that data back out, so it steers you to the field rather than letting you
  draw a picture of filling it. On a flat document there is no field to
  mislead anyone and the tools come back.

  So the open question is really two. Whether to offer the six at all, and
  whether to adopt the guardrail with them. The exposure here is the same --
  the forms layer fills real fields, and a checkmark drawn over a real
  checkbox would produce the same hollow document -- but the stakes are
  lower, because this is a page arranger that reads rather than a pipeline
  that harvests form data.

  That makes the first question sharper rather than easier. The six marks
  are only worth having on a document this application's forms layer can do
  nothing with, and the forms layer already answers for every document that
  has fields -- so the overlap is smaller than it first looked, and so is
  the audience. A page of boxes drawn in ink is still a page of boxes drawn
  in ink, and a rectangle tool plus a checkmark stamp would cover it without
  a family of its own.

- **O5. Whether to copy Reader's rule for what a click on the page means.** The
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

  What it costs: text whose every pixel lies under a mark cannot be selected,
  because there is nowhere to start -- a word inside a highlight is
  unreachable. Reader does not simply pay that, which is how this was first
  written here. A mark's right-click menu carries **Enable Text Selection**,
  which makes that one mark transparent to the pointer so the text under it
  can be taken. The cost is real but remediable, and the remedy is per mark
  rather than a mode.

  So this is no longer a question about how to build it but whether to copy it,
  and the cost above is the only reason not to. One thing stands either way:
  mark over mark needs its own rule, where topmost-first is what the note
  hit-testing already does.

  **The scrolling half of Pan has a reader after all.** It was written off
  here on the grounds that the wheel, the trackpad, the scrollbars and the
  keyboard already scroll in every mode. That holds for a mouse and not for a
  finger. A touchscreen has no wheel and no trackpad, and this app handles no
  touch at all -- nothing under `pdfarranger_qt/` mentions `QTouchEvent` or a
  gesture -- so a finger arrives as a synthesised left-button drag. Under the
  rule above that drag on bare page selects text, which leaves a touchscreen
  with no way to scroll the page by finger. Pan is that way. This is the
  owner's reason, 2026-10-31, and it is a reason to have the mode that does
  not depend on copying Reader: Pan earns its place as the touch scroll
  gesture whether or not the click rule is copied. What it leaves open is
  whether to answer touch with the mode or with real touch handling -- a
  one-finger drag that scrolls while Select stays Select -- which is now part
  of O5. Not decided.

## Decisions

Taken for this work and recorded with it, numbered within this
document. Nothing in the source cites them: where one matters to
understanding the code, the fact is in the comment.

**1. A mark is kept in the source page's space, and scaled on the way out.**
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

**2. A free text mark's appearance is drawn by `QPdfWriter`, which embeds the
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
comment in the user's own language is the same failure as a mark that does
not draw --
a document whose content is invisible -- and because the saving is bytes rather
than work, now that Qt does the subsetting.

Two consequences. `has_fonts()` is False under the offscreen platform, so a
free text appearance is tested in the world the stamp tests already live in.
And the appearance's font object must not alias an `/AcroForm /DR` font with an
identical `BaseFont` name and a different font program, or Acrobat Reader warns
that the embedded font cannot be extracted.

**3. Comment, Insert Text and Replace Text are all three offered.** Taken by
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
`/Name` -- measured, the same 1327 pixels for seven different values
and for none -- so offering a choice would mean drawing the icon ourselves,
and nothing in this decision needs that. The `/Name /Note` already written
stands.

**4. The work goes one tool at a time, starting with where the tools live
and then with Comment.** Taken by the owner on 2026-10-30, and it replaces
what O4 was asking. O4 weighed three orderings -- M6 first, free text
first, or
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

Two consequences. Free text and freehand as a single step, as the earlier
plan had it --
together, because both were cheap -- does not survive this, and the step table
below is rebuilt around tools once the grouping is known. And M14 comes with
Comment rather than after it: looking at Comment "in detail" means looking at
the two in the test document, and those are not in the model until something
reads them in.

**Amended 2026-10-31: Comment is not first after all.** Further use of Reader
turned up more of what a comment needs -- rich text with colour and size
varying inside one comment, a fill behind the text box, a popup carrying
author, time and replies -- while the text-markup family needs attributes and
nothing else. Highlight, Underline and Strikethrough go first, as
plan step 3. They exercise the whole spine: arming a tool, the attribute tail,
hit-testing by ink, selection, the grips, recolouring, deletion and reopening
-- with no text editor anywhere in it. Comment follows, against a spine that
already works.

What is written above about what Comment teaches still stands; it is the order
that changed, and for a reason the original argument did not weigh. A spine is
cheaper to prove with a tool that cannot hide a flaw behind an editor, and
Comment is the tool most able to hide one.

**5. Set status and Review History are in scope**, reversing the
2026-10-31 entry that put the review workflow out. What changed is the
measurement: a status is not a workflow, it is two keys. Setting one appends
a hidden `/Text` annotation carrying `/State` and `/StateModel /Review`, and
the history is that chain read back -- there is nothing to edit, nothing to
synchronise between people, and no round trip to run. Reader itself offers
no way to change a history, only to add to it.

Showing it is derived rather than stored: Reader's row is composed from the
annotation's own `/T`, `/State` and `/M`, which its properties dialog prints
as *"dws: Accepted, 11/1/26, 2:33:27 PM"*. The `/Contents` each link carries
is a sentence Reader generates for other viewers and does not itself
display, so none of this costs a translatable string in the history view.

**6. Deleting a mark deletes what hangs off it.** Its status chain, its
replies, and the `/Popup` object each of those owns. A status link points at
the link before it rather than at the mark, so removing one has to follow the
chain and not take a single step -- deleting the first link of a two-step
history would otherwise orphan the second. Taken by the owner on 2026-11-01,
with the alternative being annotations whose `/IRT` resolves to nothing,
which is what this project has already seen once with `/P`.

**Reader does otherwise, and the decision stands anyway.** Measured
2026-11-02 on a file Reader wrote after deleting a highlight that carried a
reply and a two-step status chain:

    before                                after
      Highlight ─ Popup                     Text "Accepted"  ─ Popup
      Text "Accepted"  IRT→Highlight        Text "Completed" IRT→"Accepted"
      Text "Completed" IRT→"Accepted"
      Text (reply)     IRT→Highlight

The highlight, its popup, the reply and the reply's popup went. Both status
annotations stayed, and the `/IRT` was stripped off the one that had pointed
at the mark -- so Reader avoids the dangling reference by cutting the link,
not by taking the annotation. What is left is two `/F`-hidden `/Text`
annotations (`/F 30`: Hidden, Print, NoZoom, NoRotate) recording that
somebody Accepted and then Completed a comment that no longer exists.

They cannot be reached. A status is shown as Review History *under the
comment it belongs to*, and the owner confirmed that a deleted comment no
longer appears there; hidden annotations are not drawn, and `MarkMap.visible`
drops them here too. Keeping them would write litter no user of either
application can read, correct or remove. So this takes them, and Reader's
own confirmation is honest about the difference: it promises only that
replies go.

**7. A mark the file brought is amended, never rebuilt.** The model owns the
kinds it understands and everything else rides through as the dictionary it
arrived as. An edit changes the keys the user changed -- set `/C`, regenerate
the `/AP` that would otherwise draw the old colour -- and leaves the rest
alone.

The alternative was to rebuild an annotation from our own fields once we
owned its kind. That is lossy for every mark it owns, in proportion to how
much of the format the model does not model: a highlight we fully support
still carries `/NM`, `/RC`, `/Subj`, `/CreationDate`, `/Popup` and whatever
its producer invented, and 306 characters of rich text have nowhere to live
in an `Annotation` that holds one string and one colour. Rebuilding also
makes the thing we are least ready to model -- `/RC` -- a precondition for
holding a mark that has one.

The two do not converge even at full coverage, because coverage is of
*kinds* and the loss is of *keys*. Taken 2026-11-01.

**8. The model holds the edits, not the marks.** An untouched annotation
stays in the file and is resolved on demand for drawing and hit-testing; the
model gains an entry only when something about it changes.

Undo decided this. `Annotations` is snapshotted onto the undo stack on every
edit of anything, and it is cheap because it is sparse -- a document nobody
has marked holds an empty one. Reading every annotation in would end that:
the markup sample would copy 180 entries per undo and the Handbook thousands.
Holding deltas keeps it sparse, makes undo of an edit mean *drop the delta*
with nothing to restore, and gives the overlay the same shape as the typed
form values it sits beside.

**9. A mark is identified by a uid this session assigns.** Allocated when a
page's annotations are first read, carried through a snapshot, exactly as
`Page.uid` works for pages.

Not `/NM`: a delta never has to outlive the session, because the moment the
document is saved the edit is in the file and there is nothing left to key.
So nothing is written to a document that was only looked at. Not position
either -- our own operations invalidate it, since deleting a mark takes its
status chain and its replies with it and everything after shifts, and undo
shifts them back, so a delta keyed by position names a different mark in
between.

If a delta ever has to survive a save and reopen -- pending edits, or marks
changed in one window and exported from another -- `/NM` becomes the answer
and we would be assigning one. Nothing in this plan needs that.

**10. A mark is written with the keys a reader expects, and `/NM` is one of
them.** Measured against the Reader highlight on page 15 of the Handbook,
which writes `/AP /C /CA /Contents /CreationDate /F /M /NM /P /Popup
/QuadPoints /RC /Rect /Subj /Subtype /T /Type`. Ours wrote ten of those; it
now writes `/CreationDate`, `/NM`, `/P`, `/Subj` and `/T` as well.

`/CreationDate` separately from `/M`, because a reader sorts its comment list
by one and shows the other, and with only `/M` written both answers were the
same. `/Subj` is the producer's own word for the kind, read out of the corpus
rather than invented -- "Highlight" in seven files, "Cross-Out" in four,
"Sticky Note" in seven -- and not translated, because a reader groups and
filters by it and a translated one sorts into a category of its own in every
other language. `/T` is the login name: the `/Info` dictionary of these
documents is empty, so there is no name in the document to inherit, and
Reader falls back the same way when its identity setting is unset. `/P`
because `export._repoint_annotations` rewrites `/P` on every annotation that
has one, after the transform passes have replaced the page objects, so a mark
without `/P` is left out of the fixing rather than left correct.

`/Contents` is now written only when there is something to say. Written
unconditionally, an uncommented highlight carried an empty one, and a reader
that lists comments listed it -- an empty note against a mark whose whole
point was that it had nothing to add.

This does not reopen decision 9. That decision is about what a *session
delta* is keyed by -- a change to a mark the file brought, held in memory
until the document is saved -- and the answer is still a session uid, with
nothing written to a document somebody only looked at. `/NM` here is the
identity of a mark we are writing, inside the file we are writing it into,
because a reply and a status change are separate annotations that name the
mark they answer: a mark that cannot be named cannot be replied to. It is
minted when the mark is made rather than on the way out, so that a save does
not rename it, and `duplicate()` carries it so undo and redo are the same
mark rather than a succession of new ones.

Still not written: `/Popup` and `/RC`. Both appear only because a mark has a
comment -- confirmed by adding one to the Handbook highlight, which brought
`/Contents`, `/RC` and a `/Popup` object with it -- so both arrive with the
note work rather than with the mark.


**11. A mark's quadrilaterals are built from PDFium's loose character box,
through a second copy of PDFium.** Qt's `QPdfSelection.bounds()` gives one
polygon per run, tight to the ink, so a line with no descender comes out
shorter than the line above it and a larger word makes its own run a
different height again. Reader uses the box built from the font's ascent and
descent instead: against the forty-two quadrilaterals it wrote into
`Markup Highlight.pdf`, the union of the loose boxes under each one matched
its `/QuadPoints` exactly, to the hundredth of a point, on every one. The
ink-tight boxes over the same characters ran 2 to 6 points short.

There is no single factor to apply instead, because a line may hold several
sizes of type and Reader gives each its own quadrilateral -- on one page its
quads are 12.99, 13.34, 14.56 and 26.69 points tall.

Qt PDF *is* PDFium, but it links it statically with hidden visibility: of the
232 symbols its framework exports, not one is an `FPDF_*` function, and the
nine that mention PDFium are Qt's own private methods taking PDFium handles
the public API never hands out. So the choice was a second PDFium that
exports its API, or parsing the content stream ourselves -- text matrices,
`/FontDescriptor` ascents, Type3 and CID fonts, and the standard 14 fonts
that carry no descriptor at all -- to recompute what PDFium has already
computed correctly. The dependency is `pypdfium2`, and the duplication is
only the library: it reads the same bytes the canvas already holds for its
render thread, because PDFium takes a pointer rather than a copy, and it
builds a text layer for the page being marked alone rather than for the
document.

Where the quadrilaterals break is in `textlayer`, with the measurements that
settled each rule. One consequence is visible: because only the armed page's
glyphs are loaded, the gesture stops at the page edge, which is what Reader
does for a highlight and the opposite of what it does for a selection.


**12. A mark is hit-tested against the document on screen, not correlated
back to the source.** The reader shows an export snapshot, and the canvas
already holds it as bytes for the render thread. Its annotations are in the
coordinates being drawn in, on the page indices being shown, so clicking one
needs no mapping in either direction -- `markup.MarkMap`, which had been
built and left without a caller, is pointed at those bytes.

The alternative was to read the *sources* and map back: a page-index to
`(nfile, npage)` table pushed into the canvas, a cached map per source
document, and the inverse of every transform export applies. Measured, the
two things that would have made it work do not. Only 43.1% of the markup
annotations across the fixtures and corpus carry a `/NM` of their own -- 128
of 297 -- so a name cannot be the key. Position does survive an export, with
count and order identical on all four pages of the markup sample, but that
is a 1:1 export: nothing shows it holds when `_strip_signatures` drops a
widget, and a duplicated page maps two output pages onto one source page,
which is the case `test_structure` already names as impossible to answer.

What makes the cheap answer correct is that **selecting changes no data**.
Nothing read from the snapshot has to outlive it, and when the document
changes the selection should go anyway -- the canvas already drops its
search hits on `contents_changed` for the same reason. The correlation is
not avoided, it is deferred to the step that first *edits* a mark the file
brought, which is the same ownership question highlight step 4 has to answer whatever
is decided here.

**13. The outline is the same whether a mark is hovered or selected.**
Reader draws one outline, and passing the pointer over a mark draws it
exactly as picking the mark up does. The outline answers "how far does this
mark reach", and that does not change according to whether you have
committed to it.

A faded version of it was tried first, on the reasoning that hovering is the
lesser state and should look lesser. Measured against Reader's own, ours
came out paler *and* wider -- a dominant (144, 176, 224) in 4 to 5 pixel
strokes against Reader's (32, 112, 192) in one -- and it read as a worse
selection rather than as a different thing.

**There are three states, and the outline is only one of the differences.**
Observed 2026-11-02 on the same mark in each::

    normal      the mark, and the badge if it carries a note
    hovered     and the outline, and the note panel at the pointer
    selected    and the grips at the ends of the run, the bar, and the
                note *editor* open -- the thread, not the read-only panel

So what tells hovered from selected is three things, not the bar alone,
which is what this said before the grips were seen. The panel and the
editor show the same note and are not the same thing: hovering gives a
read-only summary that follows the pointer, while selecting opens the
thread with its reply box.

The grips are highlight step 6. The editor is highlight step 8, so
*selected* is not fully realised until then -- a selected mark shows its
grips and its bar now, and will open its thread when there is one to open.

**14. The buttons beside a selected mark are drawn before they act.** Three
of them, as Reader shows: add a comment, a colour swatch, delete. Each
belongs to a later step -- the comment to the note work, the swatch to
colour and opacity, delete to the step that has to take a mark's status
chain and its replies with it -- so each is drawn and disabled, and the step
that builds one turns its own on.

Drawn now rather than added later because the bar is the feedback that tells
a selected mark from a hovered one under decision 13, so the selection is
not finished without it. A button that acted before its step existed would
be a second, half-built way into work that step has to do properly.

**15. The family buttons open their family from anywhere on the button.**
They began as split buttons -- the icon re-arming the tool last used from
that family, a narrow arrow beside it opening the family -- which is what
Reader does. Two targets in one 28-pixel button is a target you have to aim
at: the arrow is a few pixels wide, its edge is invisible, and missing it
arms a tool instead of showing you the choice.

So the whole button does the one thing, and the tool it would have re-armed
is the one already ticked when the family opens. Three consequences follow.
The popup mode is `InstantPopup`, because the divider a split button draws
is a promise that its two halves differ. Qt's menu indicator is painted out
and a small filled triangle drawn into the bottom right corner instead,
which is the mark Reader puts there. And the button filters events on its
own menu, so that a press landing on another family reaches *that* family:
an open menu grabs the mouse, and without this the press was swallowed to
close the menu and the next family needed a second click. Reacting after
the menu closed was tried and is too late twice over -- the click is spent,
and the release from it dismisses whatever the handler opened.

**16. A stamp is placed, not dragged out.** It has a size of its own, like a
sticky note's icon, so the gesture supplies a corner and nothing else. When
it is built it belongs in `PageCanvas.POINT_TOOLS` beside the note, and not
with the area tools -- which also means a press over a mark does not belong
to it, because there is no region being drawn across the mark. Its place in
the Drawing *family* is about where it sits in the strip, which is a
different question from what its gesture is.


**17. A mark the file brought is patched, never replaced.** The question
this step was waiting on: what export writes from once a mark is both in the
file and in the model. Export copies the page's annotations as it always
has, and afterwards rewrites `/C`, `/CA` and `/AP` on the ones that have
been changed. Everything else is the producer's and survives untouched --
`/NM`, `/Popup`, `/RC`, `/Subj`, `/T`, `/CreationDate`, the `/IRT` chains.

Writing a fresh annotation from what this application models instead would
drop every key it does not model, which is most of them, and the standard
this work is held to is that a document comes out with nothing lost. So
there was never really a choice, only a question badly asked.

**The change is keyed by `(page uid, index)`**, where the index counts the
markup annotations on the page in the order the file has them. Widgets,
popups and links are not counted, so stripping an unsigned signature widget
on the way out cannot slide a change onto the mark next door.

Decision 9 rejects a position as a mark's identity, and for a *mark* that
still holds: deleting one takes its status chain and its replies with it,
everything after shifts, and an undo shifts them back. This is a position in
the *source*, which this application never edits, so nothing renumbers it.
Export reads the same pages in the same order and `marks_in` enumerates them
the same way -- measured, the markup sample comes through an export with its
annotations in the same order and the same count, 64, 64, 27 and 25 across
its four pages.

The alternative keys were measured and do not work. Only 43.1% of the markup
annotations across the fixtures and corpus carry a `/NM` of their own, 128
of 297, so a name cannot be it.

**18. The palette is Reader's, sampled and converted.** Twenty-one colours:
seven hues, the same seven lightened, and a greyscale row. Taken from a
screenshot of the picker, and **converted out of Display P3 before being
read**, which is the whole of it: a screenshot taken on a Mac carries a P3
profile, and reading its pixels as sRGB is wrong by up to 59 of 255 -- Light
blue samples `#73E2FB` raw against the `#38E5FF` Reader actually writes.

Converted, the eight of these that appear in Reader-written documents in the
corpus match what is in those files to within one unit, four of them exactly:
Blue, Magenta, Purple and Light blue land on the nose, and Red, Orange,
Light red and Light green are one off in a single channel. Eight independent
confirmations that the other thirteen are right too -- and without the
conversion every colour this application wrote would have been visibly wrong.

The names are Reader's own, read off its tooltips rather than guessed: the
second row is "Light" plus the hue above it throughout, the sixth hue is
Fuchsia and not Magenta, and the greys run White, Pale, Light, Medium, Dark,
Darker, Black. Shown as tooltips here too, and therefore translated.

Three assumptions were corrected on the way. The names were taken out
entirely, on the reasoning that Reader shows no name *on* a swatch and
nobody would ever see them -- it puts one in the tooltip. Then the first set
of names was invented from the colours, and reading the tooltips replaced
most of the second and third rows. Only the first row survived guessing, and
even that had Magenta for Fuchsia.

**19. A change is shown by re-rendering one page, not the document.** The
marks a document arrived with are drawn into the page bitmap by PDFium --
page and annotations together -- so a recoloured mark cannot be painted over
the old one. The page has to come from a document that carries the change.

Rewriting the whole document to do that is what makes it slow. Measured on
the 1590-page Handbook: patching and saving the file to change one colour
costs 1180 ms, while lifting that one page into a document of its own,
patching it and saving costs 1.1 to 6.5 ms. So an edited page is rendered
from a one-page document built for it, and the rest of the book is never
touched. End to end, a colour change and the repaint that follows it measure
10 to 25 ms.

Reader does not do this -- it keeps the page raster and the annotations as
separate live objects and redraws the one object. That is not open to us:
PDFium bakes annotations into the page bitmap, and drawing them ourselves
instead would mean owning all eighteen subtypes, which is exactly what
*lose nothing* says we must not require. Making one page cheap enough to
redraw whole reaches the same place by a different road.

**20. One current colour, and the swatch does two jobs.** Reader carries a
single colour at the foot of its tool list and it colours whatever is made
next, of any kind -- not a palette per tool. Until the swatch is used each
tool keeps the colour readers expect of it, yellow for a highlight and red
for a strikeout, rather than everything starting out the same.

The same swatch also changes the mark you have *selected*, which is why it
is shown with the pointer armed and not only with a tool armed. While a mark
is selected the swatch shows that mark's colour, so the tick in the popup
marks what the mark is rather than what the next one would be, and letting
go puts back the colour armed for the next one. Observed in Reader and then
confirmed by the owner: selecting with Select and selecting with Highlight
behave identically, and changing the colour from either the tail or the bar
changes the selected mark whichever tool is armed.

`Annotation` grew an `opacity` of its own for this. `/CA` had been fixed per
kind, so the slider had nowhere to write -- and changing a mark's opacity
would have raised on `__slots__`.


**21. A drag shows the old run and the new one at once, and the new one is
neutral.** Observed in Reader by the owner: while a grip is being dragged,
the mark's own colour stays where it was and a grey band shows the run
being proposed. The highlight does not move until the drag is let go, and
then it shows exactly what the band covered.

This matters here because it is also what PDFium forces. The mark a
document arrived with is in the page bitmap for the whole drag under
decision 19, and it cannot be taken out -- so a band drawn in the mark's
own colour multiplies with itself, and `#FF6200` over `#FF6200` comes out a
red that belongs to neither. A neutral band cannot take a colour from what
it crosses. Reader's answer and the only one available are the same answer.

The pointer says which hold it has, and there are three:

    over bare text    an I-beam     a drag selects text
    over the mark     an arrow      a drag picks the mark up
    over a grip       a diagonal    a drag moves the end of the run

An I-beam over any part of the mark would promise a text selection that
pressing there does not give.



**22. Redaction is not supported, and not offered.** `/Redact` is the one
markup subtype Reader's own menus reach that this application will not make:
redaction is an Acrobat feature rather than a Reader one, and the owner ruled
it out on 2026-11-02 along with any menu entry for it. *Redact text* is
therefore absent from the selection menu, beside *Edit text*, *Bold, Italics
& more* and *Export selected text*, which have nothing behind them either.

It is the only gap in the test document's coverage. Measured on
`corpus/Markup Test Case.pdf`: 180 annotations over four pages in 18
subtypes -- the fifteen markup kinds plus `/Link`, `/Popup` and `/Widget`,
which is the eighteen this document refers to elsewhere. The ten subtypes
the specification lists and the file does not hold are `/Redact` and nine
that no comment tool creates: `/Sound`, `/Movie`, `/Screen`, `/RichMedia`,
`/3D`, `/Projection`, `/PrinterMark`, `/TrapNet` and `/Watermark`.

Not making one is not the same as not carrying one. A `/Redact` arriving in
somebody else's document still has to survive an export untouched, which is
what *lose nothing* requires of every subtype -- and the round trip that
proves it cannot prove it for this one, because the test document has none.



**23. An open pop-up is honoured on hover, and opening one changes
nothing.** `/Popup /Open` says a mark's window was showing when the file was
saved, and Reader shows that window as soon as the page is drawn. Verified in
the corpus on 2026-11-02: one highlight's popup reads `/Open true` with a
`/Rect` of `[57, 556, 223, 687]`, moved into the page and resized to 166 by
131, and both survive closing and reopening the file.

**Honoured on hover rather than on opening the page.** Hovering a mark whose
popup is open gives the thread; hovering one whose popup is closed gives the
one-line summary, which is the distinction Reader itself makes. Not shown
unbidden, for two reasons: the panel here is one widget, and a page carrying
three open popups would need three of them -- turning a window into a set --
and it is the case Reader renders worst, with a popup that stays
transparent until the pointer enters it.

**Opening a panel is not a change to the document.** `Save` is enabled by
there being pages, never by `modified`, so marking the document dirty would
not enable anything: all it would do is ask "save your changes?" on close
because somebody read a note. A panel left open when the document *is* saved
writes `/Open true`, so saving it open stays possible -- it is just never a
reason to save. Taken by the owner on 2026-11-02, against Reader, which also
declines to dirty the file and then will not let you save the open state at
all unless you move the window first.

**Moving or resizing the window is a change, and does mark the document
dirty.** That is the line between the two: opening a window writes nothing,
while moving it writes a new `/Popup /Rect` -- so one is reading and the
other is editing, and "save your changes?" is the right question after the
second and the wrong one after the first.

Built on 2026-11-03. The window is dragged by the first item's header and
resized by a corner of its own -- **not a `QSizeGrip`**, which resizes the
top level window it finds by walking up the parents, and from inside a panel
over the canvas that is the application window.

**The file's geometry is a floor, not a box.** A window Reader sized was
sized for Reader's text in Reader's fonts; taken as the size, a 166 by 131
point window folded a note and two replies into 28-pixel rows, because Qt
shrinks whatever will shrink. It is grown to what the thread needs, and the
half of the geometry that cannot be honoured is a position that would put
the window outside the view -- it is dragged by its own header, so a window
hanging over the top edge takes the handle with it.

**Closing the window is this session's own business.** The cross puts it
away and the mark goes back to its one-line summary under the pointer;
`/Popup /Open` in the file is untouched, by the same reasoning that makes
opening one write nothing. Without that the cross did nothing anybody could
see: the hover fires on every mouse move and brought the window straight
back.



**24. A reply carries its own status, and the window shows it.** The format
already allows it and the corpus uses it -- three replies under one note
with three separate chains, measured 2026-11-03 -- so this is a question of
what is *shown*, not of what can be stored.

**A chain is followed, not filtered.** Everything hanging off a mark
includes its replies and each of *their* histories, so taking every status
below a mark reads a reply's status as the mark's own: a note whose reply
was Cancelled reported Cancelled. The links that belong are the ones
reachable from the mark through statuses alone. Every item in the thread gets a
status row and *Set status* on its own menu. A status of `None` draws no
row at all: it is a link in the history like any other, which is how a
status is taken back, but the thread says what the item's status *is*, and
the answer there is that it has none.

**25. An appearance stream goes only when what it draws has changed.**
A text markup's can go freely: every reader falls back to `/QuadPoints`
and `/C` and redraws it, which is why a recoloured highlight drops the
producer's `/AP`. A `/Text`'s cannot -- that stream *is* the icon, nothing
regenerates one, and the reader substitutes a default of its own in its
own colour. Measured 2026-11-03: an edit to a reply's text dropped its
appearance and PDFium then drew a yellow note icon that ignored the
mark's colour entirely. So `/AP` is dropped for a colour, an opacity or a
resize, and kept for the text, the rich text, the author, the subject, the
lock and the window's position -- none of which change what is drawn.

**What a colour change on a `/Text` should leave behind is still open.**
Dropping the stream is right -- it has the old colour baked in -- but
there is then nothing to draw, and each reader's default differs. Reader
draws no replies at all so it does not care; PDFGear and PDF24 draw a box
in the annotation's colour; PDFium draws yellow.

**26. A reply is not page content, and the badge speaks for the thread.**
Measured against Reader on 2026-11-03, on a document whose three replies
were given three different colours and three different `/Name` icons:
Reader draws no reply at all -- not with its appearance stream, not
without one, under no icon name. The one thing it does draw at the mark's
corner is chrome of its own, which does not print. PDFGear and PDF24 draw
a box in the annotation's colour; PDFium draws the appearance stream, and
since a thread's replies all carry the same rectangle it stacks them into
one smudge.

So the replies are **dropped from the page this application renders** --
only from what is shown; the document written out keeps every one -- and
the badge at the mark's corner wears **the latest reply's colour and
opacity**, the one every renderer paints over the others. Hovering it
gives that reply's author, its text and its own status. The thread window
puts every item's author and date in that item's own colour, which is the
only place all of them can be seen at once.

**Nothing else shows a reply's colour.** `/C` is defined as the colour of
an annotation's icon when closed and of its pop-up's title bar; this
application draws neither, so without the badge and the window the colour
a reply carries would be invisible.

**27. `/RC` is read, written with the text, and never left stale.** The
rich text is the same words as `/Contents` with their runs marked up, and
every reader that understands it prefers it. So all three follow together:
a note that arrives styled is *shown* styled, an edit that carries styling
writes a new `/RC`, and an edit that carries none takes the producer's
`/RC` away rather than leaving it to contradict the new `/Contents`. The
styling kept is what *Text Style* can say -- bold, italic, underline,
superscript, subscript -- and the rest of what Reader writes on every span
is dropped on the way in: a negative font size is not a size, and an
alignment inside a line is not a style.

**The editor is a `QTextEdit`.** A plain one cannot hold any of this, so
text that arrived styled would have been flattened the first time anybody
posted an edit to it.

**28. A status or a reply keeps what is in the box.** Reader treats
setting a status, or pressing Reply, as a post of whatever has been typed
into the open editor and then the action -- not as a cancel. Taken from the
owner on 2026-11-03. So neither throws away an unposted edit, and a post
made on the way to an action does not close the item that action opened.
Nothing is posted when nothing was changed: every status change would
otherwise record an edit to the text that nobody made.

**29. A lock is honoured, per annotation, and refusals are visible.**
`/F` bit 8 says the attributes and the mark's own text are not to be
changed, and this reader chooses to be stopped by it -- no editor, no
colour, no opacity, no resize, no delete. Not `LockedContents` (512), which
Reader does not write. *Reply* and *Set status* stay available because
each writes a new annotation rather than changing the locked one, and
*Properties...* stays because that is where the lock comes off. What is
refused is greyed rather than removed, which is the owner's preference over
Reader's own behaviour, taken 2026-11-03.

**30. The window's own menus act on items, and the first item is the
mark.** Settled with the owner on 2026-11-03, against Reader. A reply's
line offers Reply, Delete and Set status, where Delete is the whole reply
and its status chain. The first item's line and the window's background
both give that mark's menu, less the entry that would open a window
already open, because the first item *is* the comment and there is no
deleting it on its own. An item's author line opens that item, as its text
does -- and after a post nothing is open at all, so the line is how an item
is reached again; on the first item, which is also the window's title bar,
a click is told from a drag by whether the pointer moved. There is no menu over text that is
not being edited: clicking it opens it, and every entry Reader offers
there acts on the text anyway. The platform's spelling and dictionary
entries are not offered, because Qt does not give them to us.

## Done

**2026-11-01 — plan step 2, the tool surface.** A floating column over the
reader, summoned from a toolbar button that is enabled while reading and
disabled while arranging. Twenty tools in four families, declared once in
`tools.py`; the strip, the flyouts and the tick are generated from that list.
Every tool can be armed and none of them does anything, which is the point:
what a tool makes arrives with its gesture and its attributes, one tool at a
time, from plan step 3.

The five-action Markup menu is gone. It was swept into `_editing_actions`, so
it was disabled in read mode -- the only mode its tools act in -- and a flat
list could not say which tool was armed or hold twenty of them.

Three things the building of it turned up. `QToolButton.showMenu` is **not
virtual**, so overriding it does nothing and Qt places a flyout under the
button, on top of the families below; the press has to be intercepted
instead. A label declared in a table reaches **no catalogue at all** unless it
is marked with `i18n.N_`, which is the trap `mainwindow` already carries a
comment about -- twenty tool labels were silently untranslatable until a
language-change test caught them. And the settings store is scoped to the
**process**, not to a test, so a strip left open in one test floats over the
top left of the reader in every window built afterwards, exactly where other
tests start the drags that make their marks.
