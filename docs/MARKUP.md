# Markup

**Issue:** [#16](https://github.com/dwsdolce/pdfarranger-qt/issues/16)

Making a mark on a page, changing one that is already there, and losing
nothing on the way. The work goes one tool at a time: each tool gets its
requirements, written from what the user sees and does, and a plan, which is
how it is built and what it puts in the file.

Showing what a file already carries is a separate body of work with its own
document, [ANNOTATIONS.md](ANNOTATIONS.md).

## Terms

**A tool** is chosen from the toolbar, and decides what a click or a drag
on the page does. A tool becomes the current one when you choose it, and
also when you select a mark. A **markup tool** creates one or more marks,
and they need not all be of the same kind. **Select** and **Pan** are
tools that create no marks -- they change what the cursor does instead.
The toolbar holds other controls that are not tools, the appearance
controls among them.

**A mark** annotates the document with one or more annotations, where
*annotation* means the PDF object and not anything that annotates a
document. Most marks are one annotation; Replace Selected Text is two that
act as one mark. It shows on a page, it
carries notes and a review status, and it has attributes that decide its
appearance, along with metadata such as who made it and when. Notes and
status may be empty, and usually are. A mark is on one page, and is made
from text on one page. A mark can be changed or removed after it is made.

A mark's attributes can be set from three places: the appearance controls
in the toolbar, the floating context palette, and the properties form.

## The tools

In the order the strip shows them. **Tool** is the entry in the strip.
**Mark** is the name of the mark and of the tool that makes it, and it is the
name the properties form is titled with. It is filled in when the tool is
taken up, not guessed ahead of time.

| Family | Tool | Mark | What it is for | State |
|---|---|---|---|---|
| Pointer | Select | -- | select text, and pick up marks | complete |
| | Pan | -- | drag the page to scroll it | not started; it behaves as Select |
| Comment | Add a comment | Comment, or Highlight | a note pinned to a point, or a note on a run of words | complete |
| | Add a scalable comment | Scalable Comment | a note icon that is part of the page: it scales, resizes and turns | complete |
| | Replace selected text | Replace Selected Text | propose new wording for words that are struck out | complete |
| | Insert text | Insert Text | propose words to insert at a point | complete |
| | Add text comment | | words written straight onto the page in a box | not started |
| | Attach file | | a file carried in the document at a point | not started |
| Text markup | Highlight | Highlight | colour behind a run of words | complete |
| | Underline | Underline | a straight or wavy line under a run of words | complete |
| | Strikethrough | Strikethrough | a line through a run of words | complete |
| Drawing | Draw | | freehand ink | not started |
| | Line | | a straight line | not started |
| | Arrow | | a line with an arrowhead | not started |
| | Rectangle | | a box | not started |
| | Circle | | an oval | not started |
| | Text callout | | a text box with a line pointing at something | not started |
| | Polygon | | a closed shape of straight sides | not started |
| | Cloud | | a polygon drawn with a scalloped edge | not started |
| | Connected lines | | an open run of straight lines | not started |
| | Stamps palette | | a ready-made stamp such as Approved or Draft | not started; whether to offer it is undecided |

Reader's signature and initials tools are not offered: this application
does not sign documents.

## The tool strip

### Requirements

- A toolbar button opens and closes the strip. It is enabled while reading
  and disabled while arranging pages.
- The strip floats over the reader and can be dragged. Whether it is open
  and where it was put are remembered between sessions, and it is always
  brought back inside the window.
- It is a column. The tools are grouped into the four families in the table,
  one button per family. Clicking anywhere on a family's button opens a
  flyout listing its tools, with a tick on the current one.
- The family holding the current tool is filled with the accent colour, so
  the strip always says which tool a drag would use.
- A tool stays chosen through mark after mark until another is chosen or
  Escape is pressed. Escape returns to Select whether or not the strip is
  open.
- Below the families, the strip's tail holds the current tool's appearance
  controls. Today that is the colour swatch, which is shown under every tool,
  Select included, because it also recolours a selected mark. Other controls
  arrive with the tools that need them.

**Departures from Reader.** Reader's tool pane is permanent; here the strip
is put away when not wanted, because this is a page arranger first. Reader's
family buttons are split buttons; here the whole button opens the family,
because the arrow on a split button is too small a target.

### Plan

- Every tool is declared once in `tools.py`: family, label, icon and the
  colour its marks start in. The strip and its flyouts are generated from
  that list.
- Icons are Material Design Icons through `qtawesome`.
- A family button is a `QToolButton` in `InstantPopup` mode. It filters
  events on its own menu, so a press on another family opens that family
  instead of only closing the menu.
- Open, closed and position live in the application settings.

### Open

- **Touch.** A finger arrives as a left-button drag, which selects text, so
  on a touchscreen the page cannot be scrolled by finger. Pan was meant to
  answer that and is not built. Whether to build Pan or to add real touch
  handling is not decided.

## Shared by every mark

Everything here applies to every kind of mark that has been built, whether
this application made it or the file arrived with it. Each tool's section
says only where it differs.

### Losing nothing

#### Requirements

- A document that goes through this application comes out with every
  annotation it went in with, including kinds that no tool here makes.
- Changing a mark changes only what the user changed about it.
- A mark looks the same here as it will in Reader after saving: same place,
  colour and opacity.

#### Plan

- Annotations travel with their page through every arrange operation and
  are copied as the dictionaries they are. Measured on 8,697 annotations
  across the validation corpus.
- A mark the file brought is **patched, never rebuilt**. `markup.MarkEdits`
  holds only what changed, keyed by page uid and the mark's position among
  the page's markup annotations, and `markup.apply_edit` writes those keys
  onto the original dictionary, both for the on-screen preview and for the
  export.
- Marks made here are `markup.Annotation`s in `markup.Annotations`, written
  with the keys Reader writes: `/NM`, `/T`, `/Subj`, `/CreationDate`, `/M`,
  `/P`, `/F`, `/C`, and `/CA` only when it is not 1.
- An edited page is shown by rendering that one page from a one-page
  document carrying the change, not by rebuilding the whole document.

### Selecting a mark

#### Requirements

- A mark is picked up by clicking what it draws, not the box around it.
  Thin lines get a few pixels of slack, the same at every zoom.
- Where marks overlap, the one on top is picked.
- Passing over a mark outlines it, exactly as selecting it does. Selecting
  it adds its handles where it has any, the floating bar (comment, colour,
  delete) and its note window.
- The pointer says what a press will do: an I-beam over words, including
  words under an underline or a strikethrough; an arrow over a mark that
  covers its words, such as a highlight.
- Escape, or a click on bare page, lets go of the mark.
- *Enable Text Selection* in a mark's menu lets the next click through to
  the words underneath, for text that is otherwise covered.

#### Plan

- `canvas.mark_at` hit-tests against the document on screen, topmost first.
  `markup.ink_box` says where each kind draws inside a quadrilateral, grown
  by `PageCanvas.INK_TOLERANCE` device pixels.

### Colour, opacity and defaults

#### Requirements

- Colour comes from a fixed palette of twenty-one swatches: seven hues, the
  same seven lightened, and seven greys. Each swatch's name is its tooltip.
  No free colour picker.
- Opacity is a percentage field above a slider. Both are live and show the
  same value.
- **Changing a mark changes that mark.** The strip's swatch, the floating
  bar and the properties form all change the selected mark and nothing
  else. With a mark selected the strip's swatch shows that mark's colour;
  letting go puts the tool's colour back.
- With no mark selected, the strip's swatch sets the colour of the next mark
  the current tool makes.
- Each tool has its own defaults, starting at Reader's: Purple for both
  comment tools, Orange for Highlight, Blue for Underline, Light Red for
  Strikethrough and Replace selected text.
- *Make Properties Default* sends a mark's appearance to the tool that made
  it: colour, opacity, and whatever else the kind has (an underline's style,
  a comment's icon). Author and subject are never defaults.
- Defaults are kept between sessions.

**Departure from Reader.** In Reader, recolouring a mark also changes the
tool's default. Here it does not: fixing one mark and changing what the next
one looks like are two different intentions.

#### Plan

- `markup.PALETTE` was sampled from Reader's picker after converting the
  screenshot out of Display P3; eight colours found in Reader-written files
  match it to within one unit.
- Each tool names its starting colour in `tools.py`. The defaults are stored
  as JSON under `markup/tool-defaults` in the settings.
- Which tool made a mark comes from `/Subj` and `/IT`, which is how a
  highlight made by the comment tool is told from one the Highlight tool
  made.

### The note window

#### Requirements

- Selecting a mark that carries a note opens its window. Selecting another
  mark swaps it for that mark's window; selecting one with no note, or
  clicking bare page, closes it.
- A mark with nothing written opens ready to type. One with text shows the
  thread, with an *Add a reply* box at the end.
- The thread lists the note and each reply, each with its author and date in
  its own colour. Clicking an item's text or author line opens it for
  editing, with Cancel and Post. **Post is refused while the box is empty.**
- Each item can carry a review status: None, Accepted, Cancelled, Completed
  or Rejected. The current one shows on its own row; None shows nothing.
- Setting a status or pressing Reply first posts anything typed but not yet
  posted.
- The text can be styled: bold, italic, underline, superscript, subscript
  and text colour, from the editor's *Text Style* menu.
- The window can be moved and resized; doing so changes the document.
  Opening or closing it does not. Closing it with its cross keeps it closed
  for that mark for the session.
- A mark whose note was left open in the file shows its whole thread when the
  pointer is over it; otherwise hovering shows a summary panel with the
  author, the counts and the text.
- A mark that is not itself a comment wears a badge at its top left when it
  carries a note, in the colour of the latest reply.
- Replies are seen in the window, not on the page.

#### Plan

- The text is `/Contents` on the mark, always written together with `/RC`,
  in the form Reader writes it: one span per run for typed text, a bare
  paragraph for text this application composes.
- `/Popup` is written for every mark that has a note, at the geometry Reader
  uses; moving the window writes its `/Rect`, and a window saved open
  writes `/Open true`.
- A reply is a `/Text` with `/IRT` naming what it answers and `/F 28`.
- A status is a hidden `/Text` with `/State`, `/StateModel /Review` and
  `/F 30`, pointing at the previous link in that item's chain, so the
  history is a chain and is never overwritten. Its sentence ("Completed set
  by dws") is written in the user's language, as Reader does.
- A reply is told from a status by `/State`. **`/RT` is not yet read**: see
  Replace selected text.
- Replies are left out of the page this application renders, never out of
  the saved file.
- The editor is a `QTextEdit` in `notepanel.py`.

### The right-click menu

#### Requirements

One menu for every mark:

    Open Pop-Up Note
    ──────────────────
    Reply                 when the mark has a note
    Delete                Delete Thread when there are replies
    Set status        ▸   the five statuses, current one ticked
    ──────────────────
    Copy Text             only on a mark over text
    Enable Text Selection only on a mark over text
    ──────────────────
    Make current properties default
    Properties...

So there are two standard menus: one for a mark over text -- a highlight,
an underline, a strikethrough, Replace Selected Text -- and one for a mark
that covers no text, such as either comment or Insert Text, which has no
text to copy or to let through. The comment tool's highlight is over words
and still takes the second, as Acrobat has it.

Inside the note window, a reply's author line offers Reply, Delete and Set
status; the first item and the window's background give the mark's own menu,
less *Open Pop-Up Note*.

Over selected words, the menu offers *Highlight text*, *Underline text*,
*Strikethrough text*, *Add note to text* (the comment tool's highlight) and
*Add a comment to replace text*. All five are disabled when the selection
crosses a page, as Marking text says.

**Departures from Reader.** *Open comment panel*, *Open all Pop-Ups* and
*Minimize Pop-Ups* are left out, because there is no comment panel here.
*Underline text* is added to the selection menu, which Reader lacks for no
reason. Redaction is not offered at all.

### The properties form

#### Requirements

- Opened from *Properties...*, on a mark or on a reply.
- Titled with the mark's name from the tools table: Highlight, Underline,
  Strikethrough, Comment or Scalable Comment Properties. The comment tool's
  highlight is titled Highlight Properties.
- **Appearance** is the only tab that varies: colour and opacity always,
  plus whatever the kind adds.
- **General** has Author and Subject, both editable, and the dates.
- **Review History** lists every status change with who and when. It is
  read-only.
- The footer has **Locked** and **Make Properties Default**. The second
  opens unticked; ticking it does nothing until OK.

#### Plan

- One form for every kind, in `properties.py`. It writes `/T`, `/Subj` and
  the lock bit only where they changed, plus whatever Appearance changed.
- Review History rows are composed from each link's `/T`, `/State` and `/M`.

### Lock

#### Requirements

- A locked mark refuses editing, colour, opacity, moving, resizing,
  turning and deletion. Refused controls are greyed, not hidden; a locked
  mark shows no handles and cannot be dragged.
- Reply and Set status still work, because each adds something new.
- The properties form still opens, because that is where the lock comes off.
- A lock applies to one item: locking a mark leaves its replies unlocked.

#### Plan

- `/F` bit 8 (128). The contents-lock bit is not used, since Reader does
  not write it.

### Delete

#### Requirements

- From the bar's trash button or the Delete key. While a mark is selected,
  Delete removes the mark rather than pages.
- A mark with replies asks first, with Cancel as the default. A note or a
  status alone does not ask.
- The replies, the status history and their windows go with the mark.

**Departure from Reader.** Reader keeps a deleted mark's status history
behind as hidden annotations that nothing can reach. Here it goes.

### Undo

#### Requirements

- Undo and redo work while reading, for every markup action.
- One action is one undo step.

## Marking text

Shared by Highlight, Underline, Strikethrough and the comment tool's
highlight.

### Requirements

- **Tool first:** choose the tool, then drag across words. The selection
  stays on the page where it started.
- **Words first:** select words on one page, then choose the tool. The words
  are marked at once.
- **A selection that crosses a page cannot be marked.** While one exists,
  the text tools in the strip and the marking entries in the right-click
  menu are disabled -- all but Insert Text, which never marks a selection
  made before it is chosen: choosing it lets the selection go. While the tool strip is shown, making such a selection
  puts a message in the status bar saying that text is marked one page at a
  time; with the strip closed there is no message.

  The reason: a selection follows the order the file stores its text in,
  so one that crosses a page takes in whatever lies between -- the footer
  and page number at the bottom of one page, the header at the top of the
  next -- often off screen, where the person making it cannot see it. A
  mark made from it would cover text nobody meant to mark. Two marks made
  one page at a time are clearer than two made for you from a selection
  that may have picked up more than it showed. Acrobat marks across a page
  break and does it unreliably, which is why this departs from it.
- Double-click, shift-click and dragging past the edge to scroll work the
  same as in ordinary reading.
- The words taken are those between the two ends in the order the file
  stores them, which is not always reading order. Reader does the same.
- While dragging, the selection shows in the colour the mark will be made in.
- A selected mark has a round handle at each end. Dragging one re-runs the
  selection from that end, and a grey band shows the proposed run until the
  drag is released.

### Plan

- `/QuadPoints`, one quadrilateral per run, built from PDFium's loose
  character boxes through `pypdfium2`, which match Reader's to a hundredth of
  a point. Qt's own selection boxes fit the ink and come out short.
- A resize rebuilds the quadrilaterals from the new pair of ends.
- Line drawings are scaled to the type: stroke thickness is height / 16, and
  each kind's own ratio places the line.
- A selection crosses a page when its two ends are on different pages; the
  canvas says so whenever the selection changes, and the window disables
  the text tools, the menu entries and shows the message from that.
- The message is a status-bar message, `showMessage`, as the application
  already uses for "Saved" and "Copied".
- **Removed with this:** the words-first split across a page break -- a
  strikethrough on the earlier page and a Replace Selected Text pair on the
  last -- and Cancel keeping the undo step for it. Words-first marking of a
  multi-page selection, for every text tool, goes with it.
- A recolour drops the producer's appearance stream, so every reader redraws
  the mark from `/QuadPoints` and `/C`.

## Highlight

### Requirements

- Marks text as described in Marking text.
- Starts Orange at 40% opacity.
- Covers text only, never pictures, and never crosses a page.
- Appearance: colour and opacity.

### Plan

- `/Highlight` with `/QuadPoints`, `/CA 0.4`, `/Subj Highlight`, `/F 4`.
- A file mark with no `/CA` is fully opaque.

## Underline

### Requirements

- Marks text as described in Marking text.
- Two styles, straight and wavy, chosen only in the properties form. A new
  underline is straight unless a wavy one has been made the default.
- Starts Blue. Has opacity.

**Departure from Reader.** Reader has no handles on an underline; ours keeps
them, and the result reads back correctly in Reader.

### Plan

- Straight is `/Underline`. Wavy is `/Squiggly` with `/IT /Underline`, so
  changing style changes the subtype and rebuilds the appearance.
- The straight line is centred at bottom + height / 7. The wave is a stroked
  path whose tile is placed at height / 72 vertically and 1.8 times that
  horizontally, with its origin at bottom + height / 56.

## Strikethrough

### Requirements

- Marks text as described in Marking text.
- Starts Light Red. Has opacity. No style.
- The form is titled **Strikethrough Properties**, the word on the button.

**Departures from Reader.** Reader titles the form *Cross-Out Properties*,
a word found nowhere else in its interface. Reader has no handles here
either; ours keeps them.

### Plan

- `/StrikeOut`, `/Subj Cross-Out`, the line centred at bottom + 3 x height / 7.

## Comment

### Requirements

- One tool, two marks. **A click** places a comment icon anywhere on the
  page. **A drag over words**, or choosing the tool with words already
  selected, makes a highlight carrying the note. A drag that selects nothing
  makes nothing.
- The note window opens straight away. Cancelling it, or leaving it empty,
  removes the mark.
- The icon keeps its size as the page is zoomed and its way up as the page
  is turned. It has no handles and no badge, since the icon is already the
  sign of a note.
- Over the icon the pointer is a crosshair, and the icon can be dragged
  anywhere; the point grabbed is the point that lands.
- Changing the icon keeps its top left corner where it was.
- The menu has no Copy Text or Enable Text Selection, on the icon or on the
  comment's highlight.
- Appearance: one of seventeen icons, plus colour and opacity. A reply's form
  shows the icon list but cannot change it. The comment's highlight is titled
  *Highlight Properties* and looks like any other highlight.
- The icons: Check, Checkmark, Circle, Comment, Cross, Cross Hairs, Help,
  Insert Text, Key, New Paragraph, Text Note, Paragraph, Right Arrow, Right
  Pointer, Star, Up Arrow, Up-Left Arrow.

**Departure from Reader.** Reader labels the tick icon *Checkmark* and
labels a second tick *Insert Text*; ours names them Check and Checkmark, and
keeps *Insert Text* for the caret.

### Plan

- The icon is `/Text` with `/Name` the icon, or no `/Name` for Text Note;
  `/Subj Sticky Note`; `/F 28` (Print, NoZoom, NoRotate).
- Each icon has its own `/Rect`, Reader's size for that glyph, anchored at
  its top left (`markup.icon_rect`). A move writes `/Rect` and `/M` and
  nothing else.
- The seventeen drawings are Reader's appearance streams, kept in
  `noteicons.py` with the colour as a parameter. `/Checkmark` keeps
  Reader's hard-coded grey.
- Reader writes one drawing for `/Comment` and shows a different one, a
  small balloon. This application writes Reader's stream to the file and
  paints the balloon on screen. The page render hides every `/Text` and the
  canvas paints them all.
- NoZoom is never cleared here. A file mark with it cleared is drawn scaling,
  and editing it leaves `/F` alone.
- The highlight is `/Highlight` with `/Subj Comment on Text`,
  `/IT /HighlightNote` and `/CA 0.4`.

## Scalable Comment

### Requirements

- The same seventeen icons, colour, opacity and note as the comment. The two
  comment tools share one set of defaults.
- **Only this application changes a scalable comment's colour.** It is our
  own mark, and no other application can repaint it. Acrobat does not
  change a stamp's colour; the colour it lets you set on one is the colour
  of its notes, and the mark stays as it was drawn. Here, a colour change
  repaints the mark and its notes together. So a scalable comment can arrive
  with a note colour that is not the colour of the mark, and it is shown in
  the colour it is drawn in.
- A click places it **centred** on the pointer. A drag does nothing.
- The note window opens straight away; cancelling or leaving it empty
  removes it.
- It is part of the page: it scales with the zoom.
- When selected it has four corner handles, which resize it keeping its
  proportions, and a turning handle. Both work about its centre.
- Pointer: an arrow over it while unselected, a crosshair once selected
  (drag to move), a resize arrow over a corner handle, a curved arrow over
  the turning handle.
- No badge.
- The right-click menu is the comment's: no Copy Text and no Enable Text
  Selection.
- The form is titled *Scalable Comment Properties*.

### Plan

- `/Stamp` with `/Name /Comment`, so Reader treats it as a comment rather
  than a rubber stamp, and the icon in `/IT` (`/TextNote` for Text Note).
  Files written before this carry the icon in `/Name` and are still read.
  `/F 4`.
- The appearance is ours and always carries `/Resources`. Opacity goes both
  in the appearance (an ExtGState around a transparency group) and in `/CA`.
- A turn is written as `/Rotate` in degrees, a rotation in the appearance's
  `/Matrix`, and a `/Rect` that is the bounding box of the turned artwork.
  The size is not stored; it is the ratio of `/Rect` to the icon's own size.
- `/C` is the notes' colour. A colour chosen here writes `/C` and rebuilds
  the drawing in it; Acrobat writes `/C` alone.
- The canvas draws scalable comments from the file itself, as it draws
  comments, so a drag carries the glyph: `markup.blank_note_icons` empties
  their appearance in the copy used for display. It paints them in the colour
  the drawing uses (`markup.drawn_colour`, matched against our own icon
  stream), recorded on that copy before emptying it, and uses `/C` only once
  a colour has been chosen here. Any other stamp stays with the renderer.

## Replace Selected Text

### Requirements

- A strikethrough with a caret at the end of the selection, and in every
  respect it behaves as a strikethrough does: it marks text as described in
  Marking text, and it has the strikethrough's menu, notes, badge, opacity
  and resize handles. The caret follows the end of the selection, while a
  handle is being dragged as well as after.
- The caret is part of the mark and acts no differently from the rest of
  it: clicking it is clicking the mark.
- Selected, its outline is the strikethrough's box round the struck run,
  taking in the caret at its end.
- The note window opens when the mark is made, for the replacement wording.
  The note must have text for the mark to exist, as with a comment.
- The note can have replies. A note shows the badge, as on a strikethrough;
  it is not a comment.
- The strikethrough and the caret are always the same colour and the same
  opacity. Starts Light Red.
- The properties form is the Strikethrough form, titled with this mark's
  name.
- *Add a comment to replace text* in the selection menu reaches the same
  tool.

### Plan

The fixture is `tests/fixtures/markup_replace_text.pdf`, made in Acrobat.
On page 1: two pairs, one of them at 43% opacity with a reply on its caret,
a plain strikethrough, and the first part of a selection that crossed onto
page 2. On page 2: the pair that selection ended in, over three lines. Tests
count from what it holds.

**What Acrobat writes**, read off the fixture. Two annotations, the
strikeout first:

- a `/StrikeOut` with `/Subj Cross-Out`, `/IT /StrikeOutTextEdit`,
  `/QuadPoints`, `/IRT` naming the caret and `/RT /Group`, a `/Popup` and no
  `/Contents`;
- a `/Caret` with `/Subj Inserted Text` and `/IT /Replace`, carrying the note
  as `/Contents` and `/RC`, `/RD`, and a `/Popup` of its own.

Both carry the same `/C`, the same `/CA` when it is not 1, and `/F 4`.
Replies and statuses hang off the caret.

**Across a page break**, Acrobat writes the earlier page's part as a
`/StrikeOut` with `/IT /StrikeOutTextEdit` and nothing else of the pair: no
`/RT`, no `/IRT`, no caret and no note. Acrobat shows an empty note badge on
it. This application never makes one, since a selection that crosses a page
cannot be marked; one read from a file -- a text-edit strikeout with no
caret -- is treated as a plain strikethrough.

**The caret's geometry** comes from the struck run's last quadrilateral,
where h is the quadrilateral's height. It holds to four figures on both pairs:

- `/Rect` 0.810 h wide and 0.660 h tall, centred on the run's right-hand end;
- the bottom of `/Rect` one `/RD` below the bottom of the quadrilateral;
- `/RD` 0.055 h on every side, which is also the caret's line width.

**Reading it**

1. `markup.is_reply` reads `/RT`: `/IRT` with `/RT /Group` joins a pair and
   is not a reply. Today the grouped strikeout would show as an empty reply
   in the caret's thread. `Mark` gains the `/RT` it was read with.
2. `/Caret` joins `markup.KINDS`, with its subject.
3. **The strikeout stands for the pair.** It is what is hit-tested,
   outlined, given handles and a badge, and opened in the menu and the
   properties form. The caret is found through the strikeout's `/IRT` and
   is never selected or hit-tested separately; clicking it finds the
   strikeout. The outline takes in the caret's box as well as the
   strikeout's.
4. The note window shows the caret's thread: its note, its replies and its
   statuses. The badge is on the strikeout, as on any strikethrough.

**Changing it**

5. Colour, opacity and the lock are written to both annotations.
6. A resize rebuilds the strikeout's `/QuadPoints` as for a strikethrough,
   then moves and resizes the caret from the new last quadrilateral, using
   the geometry above.
7. Delete takes both annotations, their popups, and the caret's replies and
   status chain. One undo step brings it all back.
8. While a handle is dragged, a grey caret is drawn at the end of the
   proposed run beside the grey band; the old caret stays until the drag is
   let go, as the old strike line does.

**Making it**

9. The tool marks text as Strikethrough does, in both orders, on one page.
   `Annotations` holds the pair as two `Annotation`s, the strikeout naming
   the caret by `/NM` and written with `/RT /Group`.
10. The note window opens on the caret. The tool joins the tools whose mark
    needs text, so Cancel, or closing the window empty, removes both halves
    of the pair and the step that made it.
11. A strikeout is the pair's only when it is grouped with a caret. One with
    the text-edit intent and no caret is a Strikethrough: its form, its
    title, its menu, and the Strikethrough tool's defaults.
12. *Add a comment to replace text* in the selection menu is enabled and
    reaches the same tool.
13. The properties form is the Strikethrough form, titled *Replace Selected
    Text Properties*.

## Insert Text

### Requirements

- A caret placed between two characters, carrying the words to insert as its
  note.
- Placed only on text: a click goes to the nearest gap between two
  characters. A drag puts the caret at the end of the selection it makes; no
  range is kept. A click off the text makes nothing.
- Text selected before the tool is chosen is cleared when the tool is
  applied: the tool takes a point, never a range.
- The note window opens when the mark is made. The note must have text for
  the mark to exist, and cancelling it deletes the mark.
- It shows the note badge, as a strikethrough with a note does; with a note
  always required, it always has one.
- It cannot be moved: it marks a place in the text, and moving it would take
  it away from that place.
- The standard menu for a mark that covers no text: Open Pop-Up Note,
  Reply, Delete, Set status, Make current properties default and
  Properties.
- The properties form is titled *Insert Text Properties*, and its Appearance
  tab has colour and opacity only, beside the standard tabs and buttons.
- Starts Fuchsia.

**Departure from Acrobat.** Acrobat's menu for this mark has no *Open Pop-Up
Note* and no *Reply*, though the mark always has a note; every other mark
with a note offers both there. The standard menu is kept, for consistency.

### Plan

The fixture is `tests/fixtures/markup_insert_text.pdf`, made in Acrobat. Two
more are in the corpus: `Annotation Examples.pdf`, made with Acrobat's
default colours, and `Markup Test Case.pdf`.

**What Acrobat writes**, read off all three: a `/Caret` with
`/Subj Inserted Text`, `/F 4`, `/C`, `/RD`, the note as `/Contents` and
`/RC`, and a `/Popup` -- and **no `/IT`**, which is what tells it from the
caret of a Replace Selected Text pair, which has `/IT /Replace`. The default
colour is the palette's Fuchsia exactly.

**Where it goes**: centred on a character boundary, to within 0.1 to 0.3
points in all three. The box has Replace's caret proportions, 0.810 wide to
0.660 tall, and the same drawing.

**How big**: sized as Replace's caret is, from the height of the text line
it is placed on -- `/RD` 0.055 of it, `/Rect` 0.810 wide and 0.660 tall.
Acrobat's own Insert Text carets do not follow one rule: across five in the
corpus `/RD` runs from 0.055 to 0.061 of the line's height, and it is not
the font size and not the zoom -- `corpus/Markup Insert Text caret.pdf`
holds three in identical 12-point text, two placed at a large zoom, within
2.4% of each other. Replace's rule is consistent and lands within about a
point of Acrobat's, which is close enough: this does not have to match
Acrobat exactly.
