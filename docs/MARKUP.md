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
**Mark** is the name of what the tool makes, and the properties form is
titled with it. It can differ from the tool's name: *Add text comment* makes
a Text Box. It is filled in when the tool is taken up, not guessed ahead of
time.

| Family | Tool | Mark | What it is for | State |
|---|---|---|---|---|
| Pointer | Select | -- | select text, and pick up marks | complete |
| | Pan | -- | drag the page to scroll it | not started; it behaves as Select |
| Comment | Add a comment | Comment, or Highlight | a note pinned to a point, or a note on a run of words | complete |
| | Add a scalable comment | Scalable Comment | a note icon that is part of the page: it scales, resizes and turns | complete |
| | Replace selected text | Replace Selected Text | propose new wording for words that are struck out | complete |
| | Insert text | Insert Text | propose words to insert at a point | complete |
| | Add text comment | Text Box | words written straight onto the page in a box | complete |
| | Attach file | File Attachment | a file carried in the document at a point | complete |
| Text markup | Highlight | Highlight | colour behind a run of words | complete |
| | Underline | Underline | a straight or wavy line under a run of words | complete |
| | Strikethrough | Strikethrough | a line through a run of words | complete |
| Drawing | Draw | Pencil | freehand ink, any number of strokes | complete |
| | Line | Line | a straight line, its ends styled | complete |
| | Arrow | Line | a line that starts with an open arrow at its end | complete |
| | Rectangle/Square | Rectangle/Square | a box, square with Shift | complete |
| | Oval/Circle | Oval/Circle | an oval, a circle with Shift | complete |
| | Text callout | Callout | a text box with a line pointing at something | complete |
| | Polygon | Polygon | a closed shape of straight sides | complete |
| | Cloud | Polygon | a polygon drawn with a scalloped edge | complete |
| | Connected lines | Polyline | an open run of straight lines | complete |
| | Stamps palette | Stamp | a ready-made stamp such as Approved or Draft, or one of your own | complete |

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
  covers its words, such as a highlight; and **the move cursor over any mark
  that can be dragged** -- a comment's icon, a scalable comment, a text box
  -- selected or not, unless it is locked.

  **Departure from Acrobat**, which has three rules for those three: a
  crosshair over a comment's icon, an arrow over a scalable comment until it
  is picked up, and no change over a text box until it is. One rule is
  easier to learn than three.
- Escape, or a click on bare page, lets go of the mark.
- **Selecting a mark placed on the page clears the text's insertion point
  and selection**: a comment's or a scalable comment's icon, a text box, a
  shape, a line, a polygon, a Pencil, a callout, a stamp, an attachment --
  none is made from the words, as the notes for their tools say, each
  clearing the selection when chosen. **A mark made from the words** -- a
  highlight, an underline, a strikethrough, Replace Selected Text's
  strikeout, an Insert Text caret -- **leaves both alone**: the text tools
  work from them. Agreed 2026-11-13; selecting any mark had left the caret
  where it was, so the arrow keys and Copy still worked on text left
  behind.
- **A double-click on a mark placed on the page does nothing** but hold it
  -- a text box or a callout aside, which it opens for typing. It selected
  the word behind the mark. One on a mark made from the words still
  selects the word, as it does in unmarked text.
- *Enable Text Selection* in a mark's menu lets the next click through to
  the words underneath, for text that is otherwise covered.

#### Plan

- `canvas.mark_at` hit-tests against the document on screen, topmost first.
  `markup.ink_box` says where each kind draws inside a quadrilateral, grown
  by `PageCanvas.INK_TOLERANCE` device pixels.

### Colour, opacity and defaults

#### Requirements

- Colour comes from a palette of twenty-one swatches: seven hues, the same
  seven lightened, and seven greys. Each swatch's name is its tooltip.
- **In the properties form, a second tab, More Colours**, on every colour
  picker there -- a mark's colour, a border's, a fill -- holds Qt's own
  colour dialog, embedded: a grid whose first colours are the swatches,
  hue and red-green-blue controls, a hex field and an eyedropper, for a
  colour the swatches do not have. Qt's and not Apple's: the Mac's colour
  panel is a window of its own and cannot sit in a tab, and Qt's is the
  same on every system. A colour picked there is sent as it is picked, and
  ticks a swatch only when it is one. **In the form it is a window, not a
  pop-up**: titled for what it colours -- Colour, Border Colour, Fill
  Colour -- dragged by its title bar off the form it would cover, and kept
  open until Done, its close button or Escape, each of which keeps what
  was picked. As a pop-up it could not be moved, and closed only on a
  click outside it that nothing pointed to. **The strip's and the
  selected mark's bar's are the swatches alone**, small pop-ups, as
  Acrobat's are. Decided 2026-11-11,
  after a fill Acrobat took from one of its form's pickers came out a pure
  blue none of the swatches is.
- **The palette is headed with the mark's name**, as Acrobat heads its own:
  "Oval/Circle Colour" for the selected mark, or the armed tool's mark for
  the next one; plain "Colour" where nothing names it, as in a properties
  form. **A gear** in its corner opens the selected mark's properties form.
  It was headed "Colour" alone from 2026-11-06 until Acrobat's own was
  looked at again.
- **With nothing selected, the gear opens the armed tool's form**, for its
  next mark: titled for the mark, holding the Appearance and General tabs
  with the tool's current defaults -- everything the mark's appearance has,
  and its Author and Subject. OK saves it all as the tool's defaults, kept
  between sessions; no mark changes and nothing goes on the undo stack.
  The dates, Review History, Locked and Make Properties Default are left
  out, since no mark exists for them -- a departure from Acrobat, which
  shows all three tabs.
- The tick is on the colour in use, and moves to a colour the moment it is
  picked; the palette stays open after a pick, so the slider can be used.
  **Only on a swatch the colour is**, within a rounding margin: a colour
  from another picker, such as the pure blue one of Acrobat's writes, opens
  with no swatch ticked, and More Colours shows its real value. A line
  under the swatches says so -- "The colour in use, #0000FF, is not one of
  these swatches" -- so an unticked palette is not taken for a fault. It ticked
  the nearest swatch until 2026-11-11, which called a colour Blue that was
  not, and made choosing that same ticked Blue change the mark.
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
  a comment's icon). It never sends the author or the subject: copying one
  mark's author is not a choice anyone made. Those become defaults only
  when typed into the tool's own form, where they are.
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

- **A mark carries a note when its note has text or it has any reply.** A
  mark whose note is empty but which has been replied to still has a thread
  to read: it wears the badge, shows the thread on hover, and opens its
  window when selected, with the empty note ready to type into. Acrobat
  leaves such marks behind -- see Undo -- and treats them the same way.
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
- **A mark that needs a note is one undo step until its note is posted.**
  Anything done to it while its note window waits for the first words --
  a colour, an opacity, the properties form -- folds into the step that
  placed it, as the first words do. One undo then takes the whole mark, and
  Cancel removes it leaving nothing behind in the history. Without this,
  undo could walk back to the mark with its note gone and its colours
  still being undone: a state the mark is never meant to be in. Acrobat
  does exactly that, measured by the owner on 2026-11-08 with the same
  steps, which is one way it leaves a caret with an empty note.

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
- Over the icon the pointer is the move cursor, and the icon can be dragged
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
- Pointer: the move cursor over it, selected or not; a resize arrow over a
  corner handle; a curved arrow over the turning handle.
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

## Text Box

Made by the Add Text Comment tool. Complete.

### Requirements

- A box of text placed anywhere on the page, its words written straight onto
  the page rather than kept in a note.
- **Two ways to make one.** A click makes a box 108 points wide and one line
  tall at the point clicked. A drag draws the box as it goes, and the drag
  is the box.
- **The text wraps at word boundaries where it can**; a word too long for the
  line is broken across lines. The width stays as made, and the box grows
  downward as the text wraps or Return is pressed.
- A box may be left empty: unlike a note, it needs no text to exist.
- Eight handles, resizing without keeping the proportions.
- **Dragged to move**, whether or not it is selected, as the comment marker
  is, and the pointer is the move cursor over it either way.
- **Three modes.** *Unselected.* *Selected*, with its handles. *Editing*,
  with no handles and a text cursor in the box, ready to type. A click on a
  box selects it; a double-click goes into the text with the cursor where
  the double-click landed. **A box just made opens in editing**, cursor in
  it, so a click with the tool is followed straight away by typing.
- **The text palette.** While editing, the strip's colour swatch is
  replaced by an **Aa** button, and the palette opens beside it by itself
  as soon as the box can be typed in -- opening the strip too if it was
  closed, which closes again when the editing ends. It stays open, and every control in
  it can be used again and again, for as long as the box is being edited;
  it closes when editing ends, or when Aa is clicked. It holds the font,
  the size and a colour; left, centre, right and justify; bold, italic,
  underline and strikethrough; superscript and subscript. Each applies to
  the selected words, or to what is typed next when nothing is selected,
  and alignment to whole paragraphs. Typing goes on in the box while it is
  open: the palette never takes the keyboard away from the text.
- **The palette tells the truth about the selection.** Each control shows
  what the selected text has: a style button is blue when all of it has
  that style, and the font, size and colour show their real value, even a
  size off the list or a font this computer does not have. A selection
  that mixes them shows the box empty. Choosing applies to all of it, and
  a style button removes the style when all of it already had it.
  Superscript and subscript exclude each other.
- **Sizes**: 6, 8, 9, 10, 12, 14, 18, 20, 22, 24, 26, 28, 36, 48 and 72,
  chosen from the list or typed; a typed size not on the list is not
  accepted.
- **A font the computer does not have** is drawn in a substitute, and the
  font box names it with "(missing)". The substitute is what is embedded
  if the box is changed.
- **Pasting** keeps every style a text box can hold -- colour, size, bold,
  italic, underline, strikethrough, superscript and subscript -- and the
  font, if it is installed and may be embedded; otherwise the font of the
  box at the cursor. Styles a text box cannot hold, such as all capitals,
  are dropped, and links, images and tables arrive as their text.
- Cmd+B, Cmd+I and Cmd+U work while editing. Undo while editing steps
  back through the changes in the box; once editing ends, the whole edit
  is one step in the window's undo.
- **Every font on the system that may be embedded** is offered -- the rule
  for every font picker, in [DESIGN.md](DESIGN.md). Acrobat's list leaves out
  the same fonts. Helvetica 12 point to start.
- **Three colours, one palette.** The border is the mark's colour -- the
  strip's swatch, as for every other mark -- and starts Light Red. The fill
  starts White and the text Green. All three come from the same twenty-one
  swatches; Acrobat's fuller colour pickers are not copied.
- Opacity, as for every other mark.
- **Status, but no notes.** A text box has no note window, no replies and no
  badge.
- **Two right-click menus.** On the mark: Delete, Set status, Make current
  properties default and Properties. Over selected text while editing: the
  editor's own -- Paste, Select All and the Text Style menu. The platform's
  spelling and dictionary entries are not offered, as for notes.
- **The properties form is *Text Box Properties*.** Appearance holds Style,
  Border Color, Opacity, Thickness and Fill Color, beside the standard tabs.
  Style is one of ten: No Border, Straight, Short, Medium and Long dotted,
  Short and Long Dash Dot, a dash of 8 on and 4 off then 4 on and 4 off,
  and a Small and a Large Cloud. The dash was missed at first -- the
  fixture's nine labelled boxes did not include it -- and found on a
  rectangle in `corpus/Markup Drawing.pdf`.

**Departure from Acrobat.** Acrobat writes Helvetica without embedding it.
Here the font used is embedded, as the page-number and watermark dialogs
already do, or a document written on one system cannot be read on another --
and with every system font on offer, most would not be there.

### Plan

The fixture is `corpus/Markup Text Comment.pdf`: on page 1, boxes made by a
click and by a drag, two left empty, one with a 3 point border and an orange
fill, and one of each border style, labelled with its name.

**What Acrobat writes**: a `/FreeText` with `/Subj Text Box`, `/F 4`, no
`/IT` and no `/Popup`. The three colours are in three places:

    fill          /C                                white  [1 1 1]
    border        the colour in /DA                  0.9725 0.3922 0.3922 rg
    text          /RC and /DS                        color:#058A1B

`/DA` names the font and size too, `/Helv 12 Tf`, against a Type 1 Helvetica
in the appearance's resources and not embedded. `/DS` is the default style,
and `/RC` the rich text, one span per run, as for notes. Thickness is
`/BS /W`, written only when it is not 1. An empty box has no `/Contents` and
no `/RC`.

**The drawing**: the fill and the border in one path, the border inset by
half its width; then the text, clipped to the box inset by twice the
border's width, in lines 1.2 times the size apart -- 14.4 points at 12.

**The click-made box** is 108 by 18.4 points: one 14.4 point line and 2
points above and below. **Each further line adds 12 points**, the font
size: a box with a second line, typed or made by Return, is 30.4 points.

**The border styles**, read off one box of each in the fixture, each
labelled with its style:

    No Border        /BS /W 0          filled, not stroked; text clipped
                                       to the whole box
    Straight         no /BS            /BS /W only for a thickness other
                                       than 1
    Short dotted     /BS /S /D /D [2 2]
    Medium dotted    /BS /S /D /D [3 3]
    Long dotted      /BS /S /D /D [4 4]
    Short Dash Dot   /BS /S /D /D [4 3 2 3]
    Long Dash Dot    /BS /S /D /D [4 3 16 3]
    Small Cloud      /BE /S /C /I 1    rectangle grown by /RD 5.09
    Large Cloud      /BE /S /C /I 2    rectangle grown by /RD 9.28

The drawing sets the same dash pattern in its own stream, and draws a cloud
as curves. No Border keeps the border colour in `/DA`, so it is there again
if a thickness is set.

**Ours**: fonts offered through `fonts.FontChooser`, the one picker every
font choice uses; drawn through `QPdfWriter`, which embeds a subset of each
font used and takes any language, and lifted into the appearance as the page
numbers and watermarks are. `/RC` records each run's font family and size
beside the styles notes already keep, so Acrobat reads back what was chosen.

The Add Text Comment tool's starting colour in `tools.py` is Light Red, the
border's: the mark's colour is the border's. The White read off Acrobat
earlier was the fill.

### Building it

Four stages, each one tried in the application before the next:

1. **The box.** Made, selected, moved and resized; its border, fill and
   style drawn and written; empty.
2. **Typing.** Editing mode, plain text wrapping and growing the box, drawn
   with its font embedded.
3. **The rich text.** Font, size, colour and styles per run, and the text
   palette that replaces the swatch while editing.
4. **The properties form**, with its five appearance items, and status.

**Stage 1.** What it builds, and what it leaves for later:

- **The kind.** `/FreeText` joins the kinds the model knows. A mark's
  *colour* is its border's, as for every other mark -- written into `/DA`,
  not `/C` -- and a text box adds three of its own: the fill (`/C`), the
  thickness (`/BS /W`) and the style, one of the nine. A colour edit on a
  text box therefore writes `/DA`, and a file's box is read the same way
  round.
- **Writing it** as Acrobat does: `/Subj Text Box`, `/F 4`, `/C`, `/DA` with
  the border colour and `/Helv 12 Tf` until stage 2 has a font, `/DS`, the
  style's `/BS` or `/BE` and `/RD`, and no `/Popup`. The appearance is ours:
  the fill, then the border in the style's dash pattern or cloud.
- **Making it.** A click makes a 108 by 18.4 point box with its top left at
  the click. A drag draws one from the press, its top left, to the release,
  its bottom right, shown as it is dragged. Until stage 2 a new box comes out selected rather
  than in editing, since there is nothing to type into yet.
- **Selecting and moving.** A click anywhere on the box selects it; a drag
  moves it, selected or not, with the move cursor over it either way.
- **Resizing.** Eight handles, corners and edge midpoints, with no
  proportion kept -- the handle machinery the scalable comment has, with four
  more handles and the aspect free.
- **While a box from the file is moved or resized** a grey outline shows the
  new place, and the box itself stays in the page image until the button is
  let go, as a highlight's run does. A box made this session is drawn by the
  canvas and moves with the pointer.
- **Its menu** is the one for a mark that covers no text, less the note
  entries: Delete, Set status, Make current properties default and
  Properties.
- **The tool's starting colour** in `tools.py` changes from White to Light
  Red, the border's.
- **The cloud.** The box is the rectangle less `/RD`, and the scallops lie
  outside it: 5.09 points deep at `/I 1` and 9.28 at `/I 2`, laid as short
  curves -- 196 about 2.3 points apart on the small cloud, 104 about 4.5
  apart on the large. Drawn by the method of Apache PDFBox's `CloudyBorder`,
  a reconstruction of Acrobat's own written to match it, and checked against
  the fixture's two clouds: Acrobat's curve lies a median 0.07 point from
  ours on the small cloud and 0.13 on the large. The one visible difference
  is at the corners, where Acrobat keeps a small curl on the scallop
  squeezed in before the corner and ours lets the two scallops meet.
- **A box the file brought with text in it keeps its look in stage 1.**
  Its words are in Acrobat's drawing, and this application cannot draw
  them until stage 2, so rebuilding the drawing for a new colour, fill or
  size would take them off the page. Such a box can be selected, moved --
  the drawing follows a move unchanged -- deleted and given a status, and
  shows no handles; its colour and size wait for stage 2. Empty boxes, and
  boxes made here, change freely.
- **A box from the file moves late.** It is part of the page image, so
  while it is dragged only its outline follows, and it shows in its new
  place once the page is redrawn. Boxes made here are drawn by the canvas
  and follow the pointer. Drawing the file's boxes on the canvas too waits
  for stage 2, so that boxes with text, which need their text drawn, change
  with the empty ones.
- **Left for later**: typing, the text palette and fonts (stages 2 and 3);
  the properties form, so fill, thickness and style can be read and drawn
  in stage 1 but changed only from stage 4.

**Stage 2.** Typing, in one font, size and colour -- the box's default --
with the per-run styling left for stage 3:

- **Editing mode.** A box just made opens in it, and a double-click on a
  box opens it with the cursor where the double-click landed. While editing
  the box shows no handles. Typing, Backspace, Delete, the arrow keys,
  selecting with the mouse and the keyboard, cut, copy, paste and select all
  work as in any text box. **A click outside the box or Escape ends
  editing**, and both keep what was typed.
- **The editor sits on the page**: a text editor laid over the box at the
  page's zoom, in the box's font, so what is typed is seen at the size and
  place it will have in the file.
- **Wrapping and growth.** Lines break between words, and a word too long
  for the line is broken across lines. The width stays as made; the box
  grows downward as the text wraps or Return is pressed, by the line
  spacing, so every line stays whole -- 14.4 points a line at 12 point.
  **Departure from Acrobat**, which grows it by the font size, 12 points,
  while setting the lines 14.4 apart, and so cuts off the bottom of the last
  line of a box of several.
- **Where the lines go: Qt lays them out, the same way everywhere.** The
  editor, the canvas and the file's drawing all use one rich text layout,
  each line 1.2 times its natural height -- 14.4 points for 12 point
  Helvetica -- so what is typed is exactly what is shown and written, in
  any font, at any size, and aligned however it is set. The box grows to
  that layout's height.
  **Departure from Acrobat**, decided 2026-11-09: do what is right rather
  than copy it. Acrobat's spacing is per font and cannot be derived from
  the fonts -- the gap into a line is the deepest reach below the line
  above plus the tallest reach above it, 0.83 and 0.37 times the size for
  Helvetica but 0.63 and 0.57 for Courier Std and about 0.86 and 0.46 for
  Songti SC, read off `corpus/Markup Text Comment Font Test.pdf` -- and its
  drawing ignores justify: the text is justified while it is typed and
  falls back to the left when editing ends, though `/RC` keeps
  `text-align:justify`. Ours sits about 0.7 point higher than Acrobat's in
  plain 12 point Helvetica, spaces mixed lines by each font's own measure,
  and justifies.
- **What it settles to when editing ends**: the larger of the height it had
  when the editing began and the height its text now needs. So lines added
  and then removed in the same editing give their growth back, while a box
  that was already that tall -- made so, or grown in an earlier editing --
  never shrinks below it.
- **The text is drawn by the canvas** while the box is shown, in this
  session's boxes and in the file's whose text is in one style, so such a
  box from the file moves with the pointer as a new one does. Those boxes
  are left out of the page image to make that possible, as comments and
  scalable comments are. **A box from the file whose text mixes styles
  still moves late**: it keeps Acrobat's drawing as part of the page image,
  shows in its new place only once the page is redrawn, and waits for
  stage 3.
- **Written as Acrobat writes it**: the text in `/Contents`, and in `/RC` as
  a single span in the box's default style, which is `/DS`; the appearance
  is the fill and border with the text drawn inside, through `QPdfWriter`
  with the font embedded, clipped to the box inset by twice the border's
  width as Acrobat clips it.
- **One undo step** for each time the box is edited, taken when editing
  ends.
- **A box from the file with text becomes editable** -- its look and its
  size too -- when its text is in one font, size and colour, which is all
  stage 2 can draw. One whose text mixes styles stays as stage 1 left it
  until stage 3.
- **The text's colour is read from the rich text.** When one span holds all
  of it, the span's colour is the text's, not the body's: Acrobat can leave
  the body red round a span it made blue, and draws the blue. Otherwise the
  body's, and failing that `/DS`.

**Stage 3.** The rich text and the text palette:

- **The rich text is the box's text.** `/RC` is read into a Qt text
  document run by run -- font, size, colour, weight, style, underline,
  strikethrough, superscript, subscript, and each paragraph's alignment --
  and that one document is what the editor edits, the canvas paints and
  `QPdfWriter` draws into the file, every font used embedded. A run takes
  what it does not say from the body's style, and the body from `/DS`.
- **Written as Acrobat writes it**: the box's default style on the body
  and in `/DS`; a `<p>` a paragraph; a span a run, carrying its font, size
  and colour and whichever styles it has. Underline is `text-decoration:
  word`, strikethrough `line-through`, both `word line-through`;
  superscript and subscript `vertical-align:+0.0pt` and `-0.0pt`, Acrobat
  recording only the sign; alignment `text-align` on the run, where
  Acrobat puts it. Read back from either the run or the paragraph.
  `/Contents` is the plain text.
- **No box is frozen any more.** Every box from the file is drawn by the
  canvas, so every one follows a drag, and every one can be edited,
  recoloured and resized.
- **The editor** is the note window's, which already styles runs, with
  strikethrough, size, font and alignment added; its right-click menu is
  that window's too -- Paste, Select All and *Text Style*. It holds the
  document at the zoom, every size scaled, and hands it back in points.
- **The palette** is a panel beside the strip, built from the strip's own
  parts: the font picker every font choice uses, a size box over the list
  above, the twenty-one swatches without the opacity slider, and buttons
  for the rest. It reads the editor's selection whenever it changes.
- **Pasting** reads what was pasted as rich text and keeps only what a run
  can hold, one run at a time, as the requirements say.
- **The editor follows its box.** It is laid over the page rather than part
  of it, so a scroll, a zoom or a resized window places it again over the
  box, and a zoom puts its words back at the new scale. The editor's own
  undo starts again after a zoom; the whole edit is still one step in the
  window's undo.
- **The strip opens for the palette.** A box double-clicked with the strip
  closed opens the strip with the palette, so the palette sits beside its
  Aa button rather than floating beside nothing; it is not written to the
  settings, and the strip closes again when the editing ends.

**Stage 4.** The properties form and status:

- **The Appearance tab** is laid out as Acrobat's: Style, Border Color and
  Opacity on the left, Thickness and Fill Color on the right, beside the
  standard General and Review History tabs.
- **Style** is a drop-down of the nine styles, each drawn as a sample line
  rather than named, No Border at the top in words.
- **Border Color** and **Fill Color** each open the twenty-one swatches;
  Border Color is the mark's colour, the one the strip's swatch shows.
  **Departure from Acrobat**: its Fill Color opens the system's full colour
  picker, with sliders, a hex value, its own opacity and a Transparent
  box -- too much for the fill of a text box, and a second opacity beside
  the mark's. Here the fill is one of the same swatches as every other
  colour, and a box is always filled.
  **Opacity** is the slider and percentage every mark has.
- Changes show on the page while the form is open, as colour does now.
- **Make Properties Default** sends the border colour, opacity, fill,
  thickness and style to the tool, for the next box.
- **Thickness** is whole points from 1 to 12, typed or stepped with the
  arrows, as Acrobat's. No Border is a style, not a thickness of 0, and
  the Thickness box is greyed while it is chosen.
- **The labels are this application's spelling**: Border Colour and Fill
  Colour, as Colour is spelled everywhere else here.
- **A restyle moves a file box's rectangle, not the box.** `/Rect` takes in
  a cloud's reach, which changes with the style and the thickness, so the
  window sends the new rectangle with every restyle and the box inside it
  stays where it was; `/BS`, `/BE` and `/RD` are written afresh for the
  new style, so a cloud changed to a dash keeps nothing of the cloud.
- **Status** was already there: the box's menu has had *Set status* since
  stage 1, with the history in the form's Review History tab.
- **No note, wherever it is asked for.** The selected mark's bar greys its
  Comment button on a text box, and the box shows no badge, no hover
  summary and no note window -- even one Reader has given replies, which
  its comments panel allows. Acrobat shows none of those on a text box
  either. Such replies are kept and written back untouched.
- **Open, for a comments panel**: whether a text box's words can be
  edited there. Either not at all, or with the same editing and palette
  as in the box -- and if so, the box would be treated like any other mark,
  with the hover summary, the note window and replies. Acrobat's panel
  edits them badly: changes take before they are posted, and changing
  the formatting does not work.

## Drawing

What every drawing tool shares. Each tool's own section adds to it.

### Requirements

- **Line thickness** is **Hairline**, then whole points from 1 to 12, on
  every mark with a line -- in the form and in the strip's slider. Hairline
  is the thinnest line the screen or printer can draw, always visible; the
  form and the slider show the word, never 0 or 0.01. **"No line" is a
  Style, not a thickness**: No Border, offered for a shape only when it has
  a fill, since a shape with neither draws nothing. Decided 2026-11-12, in
  place of "0 only with a fill", because Acrobat's 0 means two things -- no
  line on a rectangle or a polygon, whose drawing at 0 is not stroked, and
  the thinnest line on a line, whose drawing at 0 is -- and its polygon
  form stops at 0.01 to tell them apart. **Written** as Acrobat writes the
  thinnest line: `/BS /W 0` on a line or a polyline, `0.01` on a rectangle,
  an oval or a polygon, where 0 is No Border; **read** the same way back.
- **Colours**: the line's and the fill's both come from the twenty-one
  swatches, and the fill also offers **No Colour**, which leaves the shape
  see-through. Spelled Colour wherever the user sees it, as everywhere
  else here.
- **Line style** is the one the Text Box has: No Border, Straight, the
  three dotted, the two dash-dot and the two clouds.
- **The strip** adds a line thickness control to its tail, a slider from 0
  to 12 points, beside the colour swatch.
- **The right-click menu** is the one most marks have: Open Pop-Up Note,
  Delete, Set status, then the panel entries, then Make current
  properties default and Properties.
- **Notes, badges, the hover summary, the note window, replies and status**
  are as for most marks, unlike the Text Box.
- **Faded as one piece.** A mark at less than full opacity is drawn solid
  and then faded once, as PDF fades a fill and a stroke from one path --
  the line knocks out the fill under it. Fading the fill and the line one
  after the other laid the line's inner half over the fill, in a darker
  band Acrobat does not show. The drawing written into the file was right
  all along; the canvas was not.
- **Flat line ends**, as PDF draws them. Qt's default square ends grew
  each dash by half the line at both ends, which closed the gaps of a
  thick dash altogether -- a 4 point long dash dot showed solid.
- **Found by what is drawn, boxed only when selected.** A line is under
  the pointer only over its line or ends, and a rectangle or an oval only
  over its outline -- or anywhere inside when it is filled -- for hovering,
  for a press and for a drag alike, so words inside an empty shape or
  within a line's reach can be selected. Their box appears once they are
  selected, never on hover, as in Acrobat; the move cursor still shows over
  what is drawn. It was the whole box at first, for hovering and pressing,
  which left the words inside it unreachable.
- **A shape that draws nothing** -- a line of 0 and no fill, which a file
  can bring though the rule above stops one being made here -- is still
  found and selected by clicking inside it, and shows a thin dashed outline
  while it is under the pointer or selected, so it can be seen and
  deleted. Otherwise it is left as it is. **Departure from Acrobat**, where
  such a shape cannot be found or selected at all and stays in the file.
- **Stacked as the file stacks them.** The file's marks are painted first,
  then the ones made this session, then the one being made -- the order a
  save writes them in, new marks after the file's in `/Annots`, and the
  order a click takes them in. Ours were painted first until 2026-11-12,
  under every mark the file brought: an opaque Pencil stroke made here
  showed a faded one of Acrobat's through it, and Acrobat, given the saved
  file, drew them the other way up. Not only drawings: any mark made over
  one the file had.

## Rectangle/Square

Made by the Rectangle/Square tool. Complete.

### Requirements

- **One tool and one mark, two shapes.** The tool and the mark are both
  Rectangle/Square, and the properties form is *Rectangle/Square
  Properties*: what differs between a square and a rectangle is how its
  handles and Shift behave, not what it is called.
- **A square is a square by its shape**: the box inside the border has
  equal sides, to within half a point. Nothing else is written to say so,
  and a square that arrived from Acrobat is one exactly as a square made
  here is. A rectangle resized until its sides are equal becomes a square.
- **Making one.** Any text selection is cleared when the tool is chosen. A
  press, a drag and a release make it, or a click, a move and a second
  click; the first point is one corner and the second the opposite one,
  in any direction.
  **Shift makes a square**, its side the larger of the two distances from
  the first point to the pointer.
- **Handles.** Eight, on a rectangle and a square alike:
  - on a rectangle, every handle resizes freely; **Shift on a corner
    squares it**, the opposite corner staying put and the side being the
    larger of the two distances from it to the pointer -- so it becomes a
    square the size of its longest side and follows the pointer from there;
  - on a square, **a corner handle keeps it square**, and **a side handle
    stretches it into a rectangle**: which handle is grabbed is the way to
    keep the shape or change it.
  **Departure from the first notes**, which gave a square corner handles
  only, so that nothing could turn it back into a rectangle; decided
  2026-11-10, rather than writing an identifier only this application
  would know.
- **Moving.** Selecting it shows its handles and the selected mark's bar,
  and its note if it has one. Without a fill it is moved by its outline;
  with one, by the outline or anywhere inside.
- **The properties form**: colour, line thickness, line style, fill colour
  and opacity.

### Plan

The fixture is `corpus/Markup Drawing.pdf`: on page 1, four of these and
two of the Oval/Circle's. **What Acrobat writes** is a `/Square` with
`/Subj Rectangle` -- for the square too, which differs from the rectangles
in nothing but its equal sides -- and no `/IT`. The line's colour is `/C`,
the fill `/IC`, absent for No Colour; the thickness `/BS /W`, absent at
1; a cloud `/BE /S /C /I 1` or `2` with its reach in `/RD`, and `/RD` is
half the line on a plain box; opacity `/CA`. One of the four has a line
of 0 and no fill, and its drawing is a rectangle path neither stroked
nor filled: it draws nothing, in a corner of the page.

### Building them

**Both shapes at once**, the Rectangle/Square and the Oval/Circle, since
they differ in little but the curve drawn in the box. Three stages, each
tried in the application before the next:

1. **The marks.** `/Square` and `/Circle` become kinds this application
   knows. A file's are read -- line colour `/C`, fill `/IC`, thickness,
   style, a cloud's reach in `/RD`, opacity -- and drawn by the canvas,
   left out of the page image as comments and text boxes are, so that a
   drag carries them. They are selected and moved by the rules above --
   the outline, or anywhere inside when filled; for the oval, the oval and
   not its box -- and a shape that draws nothing shows its dashed outline.
   The selected mark's bar, the right-click menu, notes, replies, badges
   and status come from what every mark already has.
2. **Making and reshaping them.** The two tools, under their own names in
   the strip; made by a press, drag and release or by a click, move and
   click, Shift for a square or a circle; the eight handles with the
   square's and circle's own rules and Shift on a corner. Written as
   Acrobat writes them -- `/Subj Rectangle` or `Oval`, and the keys above
   -- with a drawing of their own: the fill, then the line in its style,
   the dash and the cloud as the Text Box draws them, the cloud following
   the oval where the shape is one.
3. **The properties form and the strip.** *Rectangle/Square Properties*
   and *Oval/Circle Properties*: Style, Colour, Thickness from 0 to 12 --
   0 only with a fill -- Fill Colour with No Colour, and Opacity, live as
   the Text Box's are; Make Properties Default for the next one. The
   strip's thickness slider beside the swatch.

**Stage 1, as built:**

- **The cloud round an oval is not the rectangle's.** Read off the
  fixture's oval: the scallops are larger, 4.75 points per step of
  intensity plus half the line -- 5.3 measured, the rule Apache PDFBox
  records -- their centres lie on the oval inset by half the line, as many
  as fit at 5/3 of a radius apart and then spaced to close up exactly (60
  at 8.85 points on the fixture's), and each meets the next where their
  circles cross, with no curl. Drawn so, ours reaches 4.75 points beyond
  the box on every side where Acrobat's reaches 4.85 to 5.09.
- **Taking hold.** Within the ink tolerance of the line -- a cloud's line
  being the band its scallops cross -- and anywhere inside a filled shape
  or one that draws nothing; an oval by the oval, so a corner of its box
  does not take it. A shape's note window opens with its selection when
  it has a note, as a highlight's does, not on every click as a
  comment's does.
- **A move** writes `/Rect` and leaves the producer's drawing, which is
  mapped onto the rectangle and so follows it.

**Stage 2, as built:**

- **Made** by a drag, or by a click and a second click with the band
  following the pointer between them; the preview is the shape itself, a
  dashed rectangle or oval. Shift squares it from the first point, the side
  the larger of the two distances. A press on a mark already there takes
  that mark, with the tool armed or not, as for every tool.
- **Written as Acrobat writes them**: `/Subj Rectangle` or `Oval`, `/C`,
  `/IC` for a fill, `/BS` for a line other than 1, `/BE` for a cloud, `/RD`
  half the line on a plain shape and the cloud's reach on a cloudy one,
  `/Rect` the box grown by `/RD`, `/CA` below full opacity; and a drawing
  of our own, the line inset by half its width inside the box, as the
  fixture's are. An oval is four Bezier curves.
- **A shape from the file is drawn afresh** when its colour, opacity or
  size changes -- a recolour from the selected mark's bar left Acrobat's
  drawing in the old colour until this -- and keeps Acrobat's drawing when
  it is only moved. A shape does not turn: the angle a handle's drag
  reports beside the rectangle is a stamp's, and is not written.

**Stage 3, as built:**

- **The form** is the Text Box's, titled *Rectangle/Square Properties* or
  *Oval/Circle Properties*, with Colour where the Text Box has Border
  Colour, and Fill Colour's swatches with **No Colour** beneath them.
  Thickness goes down to 0 only while there is a fill: choosing No Colour
  lifts a 0 back to 1. Every change shows live, as the Text Box's do.
- **A restyle moves a file shape's rectangle, not its box**: `/RD` is
  worked out again for the new style and thickness, side by side, and the
  rectangle is the box grown by it.
- **No Colour** is held in an edit as an empty colour, since None there
  means "not changed", and written as no `/IC`.
- **The strip's thickness** is a button beside the swatch, opening a
  slider from 1 -- or 0 for a filled shape -- to 12 points that reads out
  its value. With a shape selected it sets that shape's line; otherwise
  the next one the armed tool makes. Shown only for the two tools and a
  selected shape.
- **Make Properties Default** sends the fill, thickness and style, with
  the colour and opacity every mark sends, to the tool for its next shape.
- **The strip's tail is a column**, the thickness under the swatch, as
  Acrobat's is; and **the swatch is round**, as Acrobat's is, while the
  palette's cells stay square. The selected mark's bar shows its colour
  the same way, a round swatch in the mark's colour, where it had a
  palette glyph.

**Settled 2026-11-10:**

- **A cloud round an oval** is laid as round a rectangle, the scallops'
  points on the curve. The fixture's small-cloud oval has `/BE /S /C /I 1`
  and a reach in `/RD` of about 6 points, not quite even on every side
  as the rectangle's is, and its drawing is 300 curves.
- **Either corner can come first.** The first point is whichever corner
  the second point makes it -- top left, top right, bottom left or bottom
  right -- and the box is the two points' rectangle.

## Oval/Circle

Made by the Oval/Circle tool. Built with the Rectangle/Square, in the
stages given there. Complete.

### Requirements

- **One tool and one mark, two shapes**, as the Rectangle/Square: the tool
  and the mark are both Oval/Circle, and the form *Oval/Circle Properties*.
- **A circle is a circle by its shape**: the box it is drawn in has equal
  sides, to within half a point, as for a square.
- **Making one** is as for the Rectangle/Square, the oval drawn in the box
  the two points make; **Shift makes a circle**.
- **Handles** are as for the Rectangle/Square: eight on both; on an oval
  every handle resizes freely and Shift on a corner makes a circle the
  size of the box's longer side; on a circle a corner keeps it a circle
  and a side stretches it into an oval. Acrobat shows why: a circle
  resized there without Shift became an oval with no way back, since
  nothing in the file says it was a circle.
- **Moving.** Without a fill it is moved by its outline; with one, by the
  outline or anywhere inside -- the oval, not the box it is drawn in.
- **The properties form**: colour, line thickness, line style, fill colour
  and opacity.

### Plan

**What Acrobat writes** is a `/Circle` with `/Subj Oval` -- for the circle
too, which in the fixture is 143.48 points both ways and has nothing else
to tell it from the ovals -- and the same keys as the Rectangle/Square.

## Line

Made by the Line tool and the Arrow tool. Complete.

### Requirements

- **One mark, two tools.** The mark is a Line whichever tool made it, and
  the form is *Line Properties*. The Arrow tool's line starts with an open
  arrow at its end; otherwise the two are the same.
- **Making one.** Any text selection is cleared when the tool is chosen. A
  press, a drag and a release make it, or a click, a move and a second
  click; the first point is the start of the line and the second its end.
  **Shift keeps it to steps of 45 degrees.**
- **Handles**: one at each end. Dragging one moves that end, Shift keeping
  the line to steps of 45 degrees.
- **Moving.** Dragged by the line, whether or not it is selected, with the
  move cursor over it, as every other mark is. **Departure from Acrobat**,
  where a line has to be selected before it can be moved: one rule here
  for everything that moves.
- **The properties form**: Start and End, each from the same list -- None,
  Open, Closed, Open (Reverse), Closed (Reverse), Butt, Diamond, Round,
  Square and Slash; Style; Colour; Thickness, from 0 to 12, applying to the
  line and the outlines of its ends -- at 0 there is still a line, the
  thinnest that can be drawn, and the ends have no outline; Fill Colour,
  which fills the closed ends, with **No Colour**, which leaves them hollow
  and writes no `/IC`; and Opacity.
- **Line styles**: seven -- Straight, the three dotted and the two dash-dot
  the Text Box has, and a seventh, dashed 8 on and 4 off then 4 on and 4
  off, which only a line has. No No Border, since there is always a line,
  and no clouds.
- **The strip**: the colour swatch and the line thickness, as for the
  shapes.
- **The right-click menu** is the one most marks have, with **Flip Line**
  at its foot, which swaps the start and the end -- which matters only when
  the ends are styled.
- **Notes, badges, the hover summary, the note window, replies and status**
  are as for most marks.

### Plan

The fixture is page 2 of `corpus/Markup Drawing.pdf`: ten lines, one with
each end style. **What Acrobat writes** is a `/Line` with `/Subj Line`, its
two points in `/L`, the colour in `/C`, the fill in `/IC`, the thickness and
a dash in `/BS`, and the ends in `/LE`, in the order of the list above:

    None            /None             Butt          /Butt
    Open            /OpenArrow        Diamond       /Diamond
    Closed          /ClosedArrow      Round         /Circle
    Open (Reverse)  /ROpenArrow       Square        /Square
    Closed (Reverse) /RClosedArrow    Slash         /Slash

`/LE` is left out when both ends are None. There is no `/RD`; `/Rect` is the
line and its ends with a margin. A thickness of 0 is written `/BS /W 0`,
and a line of 0 can still carry `/IC`.

**Which tool made it** is in `/IT`: `/IT /LineArrow` for the Arrow tool's,
and none for the Line tool's -- kept by Acrobat whatever the ends become,
as the fixture's arrow with no ends shows. So it says which tool, not how
the line looks, and it is written and read here the same way: written by
the Arrow tool, kept, and read so that Make Properties Default on a line
sets the defaults of the tool that made it.

### Building it

Three stages, as for the shapes, each tried in the application before the
next:

1. **The mark.** `/Line` becomes a kind this application knows. A file's
   are read -- the two points, the ends, colour, fill, thickness, dash,
   opacity -- and drawn by the canvas, each end in its style, left out of
   the page image so a drag carries them; taken by the line or its ends
   within the ink tolerance, and moved. The menu, notes, replies, badges
   and status come from what every mark has.
2. **Making and reshaping.** The Line and Arrow tools; made by a drag or
   two clicks, Shift for 45 degrees; the two end handles, Shift for 45
   degrees; written as Acrobat writes them, with a drawing of our own and
   `/IT /LineArrow` from the Arrow tool; a file's line drawn afresh when it
   changes; Flip Line.
3. **The form and the strip.** Start, End, Style, Colour, Thickness, Fill
   Colour and Opacity, live; Make Properties Default for the tool that made
   the line; the strip's colour and thickness.

**Stage 1, as built:**

- **How the ends are drawn**, read off the fixture's drawings, in line
  widths, a width of 0 counted as 1: an arrow's arms 9 long at 30 degrees
  either side of the line, its tip pulled back by the width -- or, reversed,
  pushed out by it -- so the point lands on the line's end; a diamond 3
  from centre to point, a circle of radius 3, a square 6 a side, each
  centred on the end pulled back by the width and square to the page, not
  turned with the line; a butt 6 long across the line and a slash 18 long
  at 60 degrees to it, both centred on the end itself. Acrobat pulls an end
  back along the x axis only; here it is pulled back along the line, under
  a point from Acrobat's.
- **The ends take the line's dash**, as Acrobat, PDFGear and Stirling PDF
  all draw them. They were drawn solid at first, a choice made here
  without asking and taken back.
- **Taking hold**: within the ink tolerance of the line or of an end, or
  anywhere inside a closed end. **A move** writes `/L` and `/Rect` by the
  same amount and keeps the producer's drawing.

**Stage 2, as built:**

- **Made** by a drag or by two clicks, the band a dashed line from the
  start to the pointer; Shift turns the end to the nearest 45 degrees
  about the start, at the same length. The Arrow tool's line has an open
  arrow at its end and `/IT /LineArrow`; the Line tool's has neither.
- **The handles** sit on the line's own two points. Dragging one moves that
  end, the other holding still, Shift turning it to 45 degrees about the
  other; the cursor over one is a crosshair.
- **Written as Acrobat writes it**: `/L`, `/LE` only when an end is
  styled, `/IC`, `/BS` for a dash or a width other than 1, `/CA`, and
  `/Rect` the line and its ends grown by 5 points and half the line's
  width -- the margin every line in the fixture has -- with a drawing of
  our own: the line, then each end, all in the line's dash.
- **A line from the file is drawn afresh** when its look changes or its
  ends move apart, and keeps Acrobat's drawing when it is only moved.
- **Flip Line**, at the foot of a line's menu, swaps its two points, so
  the start becomes the end and the ends' styles change places.

**Stage 3, as built:**

- **The form** is laid out as Acrobat's: Start, Style, Colour and Opacity,
  then End, Thickness and Fill Colour. Thickness runs from 0 to 12 whatever
  the fill; Fill Colour has No Colour. Every change shows live, and a
  change of ends or thickness moves `/Rect` round the new ends.
- **"Open Arrow" and "Closed Arrow"**, with their reversed forms, where
  Acrobat's list says only "Open" and "Closed": "Open" is already in the
  catalogues as the File menu's verb, and with no context to tell them
  apart a translator would give the arrow the verb's word. Agreed
  2026-11-11.
- **The strip's thickness** reaches 0 for a line and for the Line and
  Arrow tools; the swatch is as for every mark.
- **Make Properties Default** sends the ends as well as the fill,
  thickness and style, to whichever tool made the line -- told by `/IT` --
  so an arrow's defaults never become the Line tool's.
- **A line of 0 keeps its dash** when it is read back, where a box's
  border of 0 is No Border.

## Polygon and Polyline

Made by the Polygon, Cloud and Connected Lines tools. Complete.

### Requirements

- **Two marks, three tools.** The Polygon and Cloud tools make a
  **Polygon** -- the Cloud tool's starting with the large cloud as its
  style -- and Connected Lines makes a **Polyline**. The forms are
  *Polygon Properties* and *Polyline Properties*.
- **Making one.** Any text selection is cleared when the tool is chosen.
  A press, a drag and a release make the first segment, or a click, a
  move and a click; on the release the next segment is already started,
  following the pointer, and each press adds a point. **Shift keeps a
  segment to 45 degrees.** It is finished by a double-click on the last
  point -- closing a polygon, ending a polyline -- or by **Complete** in
  the right-click menu, or **Return**, all of which keep the points placed
  so far; **Cancel** in that menu, or **Escape**, throws it away, and a
  second Escape leaves the tool. Complete is refused until a polygon has 3
  points and a polyline 2. **Remove Last Point** in that menu, or **Undo**,
  takes back the last point placed, and the first point taken back ends
  it: Undo reaches what was done before only once nothing is being made.
  Added 2026-11-12, with the Pencil's; a click in the wrong place meant
  starting again. **Properties...** in that menu opens the tool's own
  form, and the mark is made with what it holds when it is completed.
- **Handles** on every vertex. Dragging one moves it; **Shift keeps it
  moving in line with where it began** -- straight across, straight up or
  down, or at 45 degrees -- as Illustrator, Figma, Sketch, PowerPoint and
  Blender constrain a dragged point. **Departure from Acrobat**, where
  Shift does nothing to a vertex. Holding both its segments at 45 degrees
  was agreed and built first, and dropped on 2026-11-12: the vertex jumped
  away from the pointer to find such a spot, or held only one segment.
  The vertex goes to the **point on the line nearest the pointer**, so it
  slides along under the pointer. Turning the pointer's distance onto the
  line was built first and dropped on 2026-11-12: crossing to the next
  line swung the vertex round an arc and looked like a jump.
- **Moving and the cursor** as for every other mark: dragged by what is
  drawn, selected or not, with the move cursor over it. **Departure** from
  Acrobat, where it must be selected first unless it has a fill.
- **The right-click menu** is the one most marks have, and adds **Insert
  Vertex** over a segment and **Remove Vertex** over a vertex, refused below
  3 points on a polygon and 2 on a polyline. Insert Vertex is offered only
  on the line itself -- within the reach that takes hold of it, a cloud's
  being the band its scallops cross -- and the vertex goes on the line
  where it was clicked, so the shape is unchanged until it is dragged. It
  was offered anywhere off a vertex at first, and put the vertex at the
  click: a right-click in the fill pulled an edge into the middle.
  **Departure**: Acrobat cannot add or take away a vertex. A polyline's
  menu has **Flip Line**, as a line's does, which puts the ends' styles at
  the other ends -- the one change a flip makes that can be seen.
- **The properties form**: Colour, Thickness, Style, Fill Colour with No
  Colour, and Opacity; a polyline's adds Start and End, the line's ten end
  styles. A polygon's styles are the box styles, No Border only with a
  fill; a polyline's are the line styles. The fill fills a polygon, and a
  polyline's closed ends.
- **The strip**: the colour swatch and the line thickness.
- **Notes, badges, the hover summary, the note window, replies and status**
  as for most marks.

### Plan

The fixture is page 2 of `corpus/Markup Drawing.pdf`. **What Acrobat
writes**: a `/Polygon` with `/Subj Polygon`, or a `/PolyLine` with `/Subj
Polygonal Line` -- kept so in the file, Polyline being only what the mark
is called here -- the points in `/Vertices`, the line in `/C`, `/BS` and
`/BE`, the fill in `/IC`, and a polyline's ends in `/LE`. **The Cloud tool's
polygon carries `/IT /PolygonCloud`** and `/BE /S /C /I 2`; a polygon the
Polygon tool made and gave a cloud has `/BE` and no `/IT` -- the Arrow's
pattern again, `/IT` recording the tool. **None of the fixture's clouds
has `/RD`**, where a rectangle's has: the rectangle is the cloud's reach.

### Building them

Three stages, all three marks together, each tried in the application
before the next:

1. **The marks.** `/Polygon` and `/PolyLine` become kinds this application
   knows, read and drawn by the canvas -- the cloud along each edge, a
   polyline's ends as a line's -- found by what is drawn, and moved.
2. **Making and reshaping.** The three tools; making by clicks, Shift,
   Return, Escape and the menu; the vertex handles and their Shift; Insert
   and Remove Vertex; Flip Line; written as Acrobat writes them, with a
   drawing of our own.
3. **The form and the strip**, and **Hairline** for every mark with a line:
   the form's thickness, the strip's slider, the writing of the thinnest
   line and No Border as a style for the filled shapes, the rectangle and
   the oval included.

**Stage 1, as built:**

- **A cloud along a polygon**, read off the fixture's two: scallops the
  size a rectangle's are, 4 points per step of intensity plus half the
  line, centred on the polygon's own edges -- not inset as a rectangle's
  are -- 5/3 of a radius apart from each corner, the last on an edge
  squeezed in, and **no curls**, each meeting the next where their circles
  cross, as round an oval. Its rectangle is the cloud's ink grown by the
  line's width. Ours reaches about half a point further than Acrobat's.
- **Corners** are read once: Acrobat repeats the first at the end of
  `/Vertices`, and lays its points clockwise; a cloud is laid clockwise
  whichever way the points run.
- **A polyline's ends** are a line's, on its first and last segments, and
  its line of 0 is the thinnest there is; a polygon's 0 is No Border.
- **Taking hold**: within the ink tolerance of any segment or a
  polyline's end, a cloud by the band its scallops cross, and anywhere
  inside a polygon that is filled or draws nothing. **A move** shifts every
  point and `/Rect` by the same amount and keeps the producer's drawing.

**Stage 2, as built:**

- **Made** a point at each press, the next segment dashed to the pointer
  and, for a polygon, back to the first point; the first segment by a drag
  or a click. Once one is under way every press is its next point, over a
  mark or not. The Cloud tool's starts with the large cloud and `/IT
  /PolygonCloud`; a polyline the tool was not told otherwise about has no
  ends.
- **Written as Acrobat writes them**: a polygon's `/Vertices` closed with
  its first point again, `/LE` only when a polyline's end is styled, `/BE`
  only for a cloud, and `/Rect` what it draws grown by the line's width --
  the margin the fixture's polylines have as well as its clouds -- with a
  drawing of our own. A file's polygon or polyline is drawn afresh when its
  look changes or its points move apart, and keeps Acrobat's when only
  moved.
- **Flip Line** reverses a polyline's points, as it swaps a line's: the
  same thing seen, the ends' styles at the other ends.

**Stage 3, as built:**

- **The forms**: *Polygon Properties* is the Rectangle/Square's, with the
  box styles and No Border only with a fill; *Polyline Properties* is the
  Line's, with Start and End. Make Properties Default and the tool's own
  form keep a cloud's style and a polyline's ends for its next one.
- **Hairline, on every mark with a line** -- a text box, a rectangle, an
  oval, a line, a polygon, a polyline: the form's Thickness and the
  strip's slider read Hairline at their lowest step, and it is written
  `/BS /W 0` on a line or a polyline and `0.01` on the rest, and drawn one
  device pixel wide whatever the zoom. **No Border** is offered on a
  rectangle, an oval or a polygon only while it has a fill, and taking the
  fill away gives it a line again. This replaces the rectangle's and the
  oval's "0 only with a fill".

## Pencil

Made by the Draw tool. Complete.

### Requirements

- **One mark, one tool.** The Draw tool makes a **Pencil** -- Acrobat's
  name for it -- and its form is *Pencil Properties*.
- **One mark holds any number of strokes.** Any text selection is cleared
  when the tool is chosen. A press, a drag and a release make a stroke;
  the pointer can then move freely, and the next press, drag and release
  add another stroke to the same mark, apart from the first or not. The
  strokes drawn so far show while it is being made. It is finished as a
  polyline is: by **Complete** in the right-click menu, by **Return**, or
  by choosing another tool -- but not by a double-click, since a stroke
  ends at its release. **Cancel** in that menu, or **Escape**, throws away
  the strokes drawn so far, and a second Escape leaves the tool, as for a
  polyline. **Departure from Acrobat**, where Escape keeps them: the same
  key does the same thing on every mark made point by point. **Remove
  Last Stroke** in that menu, or **Undo**, takes back the last stroke --
  a dot is one -- and the last taken back ends the mark, as a polygon's
  points do. Once it is finished, the whole Pencil is one step to undo.
  **A change of colour, thickness or opacity** in the strip, or in the
  form that **Properties...** in that menu opens, is the whole mark's,
  seen on the strokes at once -- as on a polygon, whose mark is made with
  the tool's settings when it is completed. **Departure from Acrobat**,
  where a change of colour or thickness finishes the mark and the next
  stroke starts another, and opacity alone is the whole mark's; agreed on
  2026-11-12 for one rule on all four tools made point by point. It was
  built Acrobat's way first. **Shift does nothing.**
- **A click is a dot**: a stroke of one point, drawn as a round dot as
  wide as the line, as Acrobat draws it.
- **Smoothed**: each stroke is drawn as a chain of cubic Beziers fitted to
  its points within a tolerance, as Acrobat's are -- each curve beginning
  and ending on a point, every join smooth, a point at most about a point
  off the curve. The points themselves are kept as the mouse gave them.
- **Moving and the cursor** as for every other drawing: dragged by what is
  drawn, selected or not, with the move cursor over it.
- **Handles** on the four corners of its box, shown when it is selected.
  Dragging one **keeps the mark's proportions**, the opposite corner
  holding still, and Shift does nothing, as in Acrobat: a handwritten word
  stretched one way no longer looks like the one written. The strokes are
  scaled to the new box and **the thickness does not change**.
- **The properties form**: Colour, Thickness from 1 to 12 -- **no
  Hairline**, which is only for a mark with a fill -- and Opacity.
- **The strip**: the colour swatch and the line thickness.
- **The right-click menu** is the one most marks have.
- **Notes, badges, the hover summary, the note window, replies and status**
  as for most marks.

### Plan

The fixture is pages 2 and 3 of `corpus/Markup Drawing.pdf`. **What
Acrobat writes**: an `/Ink` with `/Subj Pencil`, each stroke one array of
points in `/InkList` -- one mark has three strokes, another two clicks --
the colour in `/C`, the width in `/BS /W` only when it is not 1, and
opacity in `/CA` with a graphics state in the drawing. No `/IT`, no dash,
no fill. The drawing is the strokes as curves with **round caps** (`1 J`),
unlike the flat ends of the other drawings; a stroke of one point is a
circle of radius 0.5 round it, filled and stroked, so the dot is the
line's width plus one point across.

### Building it

Three stages, each tried in the application before the next:

1. **The mark.** `/Ink` becomes a kind this application knows, read and
   drawn by the canvas -- the fitted curves, round caps, the dots -- found
   by what is drawn, and moved.
2. **Making and resizing.** The Draw tool; strokes gathered into one mark
   until it is finished; the four corner handles keeping the proportions;
   written as Acrobat writes it, with a drawing of our own.
3. **The form and the strip**: Colour, Thickness 1 to 12, Opacity, and the
   strip's swatch and slider.

**Stage 1, as built:**

- **Read** from `/InkList` as one flat run of points and how many each
  stroke has, so a move shifts them as it shifts a polygon's; the width
  from `/BS /W`, 1 when absent.
- **Drawn** by the canvas, Acrobat's drawing blanked as the other
  drawings' are: each stroke the curves Schneider's fit gives within 1
  point -- on the fixture a few fewer curves than Acrobat's, the points
  as near them -- with round ends and joins, faded as one piece.
- **A dot is filled to its whole width**, the line's and a point. Acrobat
  writes a circle of half a point stroked with the line, and Qt and
  PDFium both draw that as a ring, hollow wherever the line is wider than
  the circle -- PDFium shows the fixture's two dots as rings.
- **Taking hold** within the ink tolerance of what it draws; the box shows
  only once it is selected. **A move** shifts every point and `/Rect` by
  the same, writes `/InkList` back stroke by stroke and keeps Acrobat's
  drawing.

**Stage 2, as built:**

- **Made** a stroke at each press, drag and release, the points kept in the
  page's own space as they come so a scroll mid-way moves nothing; a click
  is a stroke of one point. Once one is under way every press is its next
  stroke, over a mark or not, and the second press of a double-click is
  one more. A press on another page finishes the one under way and starts
  another there. **Drawn as it will be made** -- in the tool's colour,
  thickness and opacity, each stroke fitted as it is drawn.
- **Finished** by Return, Complete, or choosing another tool, as one step
  to undo; **thrown away** by Escape or Cancel, and a second Escape leaves
  the tool. **Taken back a stroke at a time** by Remove Last Stroke or
  Undo -- and a polygon's points the same way, by Remove Last Point --
  Undo kept enabled while there is one to take back, even on a document
  with nothing else to undo.
- **The pointer is a pencil while a Pencil is under way**, from its first
  press until it is finished or thrown away, and the crosshair otherwise:
  the tool stays armed after Return, so the pencil is the one sign that
  the next stroke joins the mark being drawn. Acrobat shows a pencil too,
  but its Draw tool ends with the mark, so there it needs no such rule.
- **The corners**: dragging one scales every point about the opposite
  corner of what it draws -- its box less the line's width -- by the same
  amount across and up, by the way the pointer has moved further in
  proportion to the side, and never below 4 points; the box and handles
  follow, and the thickness does not change. It took the larger of the two
  scales until 2026-11-13, which grew a Pencil dragged mostly inwards; the
  Stamp's corners showed it, and both now follow the larger move.
- **Written as Acrobat writes it**: `/InkList` a stroke to an array,
  `/BS /W` only when it is not 1, `/Subj Pencil`, `/Rect` round the curves
  and dots grown by the line's width, and a drawing of our own -- the
  curves stroked with round ends and joins, each dot a circle filled to
  the line's width and a point. A file's Pencil is drawn afresh when it is
  resized or its look changes, and keeps Acrobat's when only moved.

**Stage 3, as built:**

- **The form**: *Pencil Properties*, Colour and Opacity on the left and
  Thickness, 1 to 12 with no Hairline, at the top of the right -- where
  every other drawing's form has them; it was one column at first, which
  put Thickness somewhere no other form does; the tool's own form the
  same, and Make Properties Default keeps the thickness for its next one.
  A new thickness puts `/Rect` round the line at its new width and gives a
  file's Pencil a drawing of our own.
- **The strip**: the colour swatch and the thickness, 1 to 12, for the
  armed tool and for a selected Pencil.
- **A Pencil under way takes every change** of colour, thickness or
  opacity, from the strip or the tool's form, on all its strokes at once.
  Built first to finish the mark on a colour or thickness change, as
  Acrobat does, and changed the same day for one rule with the polygon.
- **Properties...** in the menu of any mark being made -- a Pencil, a
  polygon, a cloud, a polyline -- opens the tool's own form.

## Callout

Made by the Text Callout tool. Complete.

### Requirements

- **One mark, one tool.** The Text Callout tool makes a **Callout**, and
  its form is *Callout Properties*. It is a Line mark and a Text Box mark
  joined: a leader with an end style at its tip, and a box of words.
- **Making one.** Any text selection is cleared when the tool is chosen.
  A press, a drag and a release, or a click, a move and a click: the first
  point is the tip of the leader, the second the centre of the box. The
  box is one line at 12 points, 108 by 14.4 -- the fixture's -- and is
  ready to type in at once, as a Text Box is. **Shift does nothing.**
- **The leader** runs from the tip to a knee, and from the knee square to
  the middle of one side of the box: **whichever of the four sides'
  middles is nearest the tip**, the last stretch 12 points long, as in
  every one of the fixture's.
- **Ten handles** when it is selected: eight on the box, one on the tip
  and one on the knee. **The tip's** goes anywhere, and the leader moves to
  whichever side is now nearest, so it never crosses the box. **The
  knee's** lengthens or shortens the last stretch, which stays square to
  its side. **The box's** resize the box, the leader staying at the middle
  of its side.
- **Taking hold**: by what is drawn, selected or not. **The box or its
  words** drag the box alone, the tip holding still; **the leader** drags
  the whole mark. A double-click in the box edits its words, as in a Text
  Box.
- **The properties form**: Line Ending, Style, Line Colour and Opacity on
  the left, Thickness and Fill Colour on the right -- where the other
  drawing forms have them. The words are styled with the text palette
  while they are being typed, as in a Text Box, not in the form.
  - **Line Colour** is the box's border, the leader and a closed end's
    outline -- Acrobat's "Border Color", renamed because it colours more
    than the border.
  - **Line Ending** is one of the ten line ends, at the tip.
  - **Style** is one of the box styles, No Border to the two clouds. A
    dash is the box's border's and the leader's; **a cloud is the box's
    alone**, the leader staying a plain line, and the leader runs through
    the scallops to the box inside them -- both as on the fixture's.
  - **Thickness** is Hairline to 12, the border's and the leader's alike:
    Hairline is the thinnest line on both, written 0.01, as on the other
    closed shapes.
  - **No Border** is written 0, as Acrobat writes it: no border on the
    box, the leader and the end's outline at the thinnest width there is.
    Thickness is greyed with it, as on the other box forms, but **Line
    Colour stays enabled**, since the leader is always drawn. **Departure
    from Acrobat**, which greys its Border Color too and leaves the leader
    in whatever colour it had, with no way to change it.
  - **Fill Colour** fills the box and a closed end, and has no No Colour,
    as a Text Box's has none.
- **The strip**: the colour swatch -- the Line Colour -- and the line
  thickness, Hairline to 12; the text palette while the words are typed.
- **The right-click menu** is the standard one: Delete, Set status, the
  panel entries, Make current properties default and Properties.
- **Notes as for a Text Box**: its `/Contents` is the words in the box, so
  it has Status but no note window, no replies and no badge.

### Plan

The fixture is page 3 of `corpus/Markup Drawing.pdf`: two callouts drawn
out, one with a 3 point dash and one at 0, and two at the default size,
one of them with the large cloud (`/BE /S /C /I 2`, its reach in `/RD`).
**What Acrobat writes**: a `/FreeText` with `/IT /FreeTextCallout` and
`/Subj Callout`; the leader in `/CL`, three points -- the tip, the knee,
and the middle of the side; the tip's style in `/LE`, a single name; the
fill in `/C` and the Line Colour in `/DA`, as on a Text Box; the width
and dash in `/BS`; and `/RD` giving `/Rect` room round the box for the
leader. At 0 Acrobat draws the box with no border, the leader at the
thinnest width and a closed arrow filled with no outline.

### Building it

Three stages, each tried in the application before the next:

1. **The mark.** A callout becomes a kind this application knows, read
   and drawn by the canvas -- the box as a Text Box's, the leader, the end
   -- found by what is drawn, and moved whole.
2. **Making and reshaping.** The Text Callout tool, made by two points
   and typed into; the ten handles, the leader finding its side; written
   as Acrobat writes it, with a drawing of our own.
3. **The form and the strip**: *Callout Properties* as above, Line
   Colour, Hairline and No Border, and the strip's swatch and thickness.

**Stage 1, as built:**

- **Told from a Text Box** by `/IT /FreeTextCallout`, and read as one with
  its leader from `/CL`, the end at its tip from `/LE`, and `/RD` side by
  side: the box is `/Rect` less `/RD`, which reaches round the leader and
  a cloud. A width of 0 reads as No Border.
- **Drawn** by the canvas as a Text Box with its leader under it, faded as
  one piece: the leader in the box's colour and width, dashed as its
  border is but never clouded, the end pulled back as a line's is and a
  closed one filled with the box's fill -- and at 0, the thinnest leader
  and a closed end with no outline. On the fixture's four it matches
  Acrobat's drawing by eye.
- **Taking hold** inside the box or within the ink tolerance of the leader
  or its end, not in the rest of the rectangle round them. **A move**
  shifts `/Rect` and `/CL` by the same and keeps Acrobat's drawing.
- **Until stage 2**: no handles, and no typing in its box; a change of
  look took Acrobat's drawing away. Stage 2 replaced all three.

**Stage 2, as built:**

- **Made** by the tip and then the centre of the box, dragged or clicked
  out as a line is but with no Shift: the box 108 by 14.4 at the page's
  own size, Light Red with a white fill and an open arrow at the tip, as
  the fixture's default ones are -- the tool started White, which would
  have drawn its leader invisibly -- and typed into at once. `/Subj
  Callout` and `/IT /FreeTextCallout`, the subject being Acrobat's.
- **Typing** grows the box downwards from its top, in a callout made here
  or one of Acrobat's, and the leader follows to the middle of its side.
- **The ten handles** as the requirements have them, and **the box dragged
  alone** from inside it, the tip holding still, while the leader drags
  the whole mark. A box handle stops at 6 points across, as a Text Box's
  does; the knee's at a last stretch of 0. Every one is one step to undo.
- **Written as Acrobat writes it**: `/CL` the tip, the knee and the middle
  of the side; `/LE` a single name; `/Rect` round the box -- grown by a
  cloud's reach or half the line -- and the leader and its end, half the
  line round them; `/RD` side by side from it to the box; and a drawing of
  our own, the leader first so the box covers its end. **A file's callout**
  keeps Acrobat's drawing when only moved, and is written afresh round its
  box and leader once reshaped, typed into or restyled.
- **A file's callout keeps its box as `rd`**: the box an edit records is
  where the box sits in its rectangle, so a rebuild of the reader -- an
  undo, a trip to Arrange -- turns it back into `rd` once the rectangle is
  set. It was set on the record as a field the record does not have, and
  the reader failed to load after a callout of Acrobat's was reshaped.

**Stage 3, as built:**

- ***Callout Properties***: Line Ending, Style, Line Colour and Opacity on
  the left, Thickness and Fill Colour on the right, in the two columns
  every drawing form has; the tool's own form the same, starting with an
  open arrow, and Make Properties Default keeping the end, style,
  thickness and fill for its next one.
- **Thickness** Hairline to 12, Hairline written 0.01; **No Border**
  written 0, greying Thickness while **Line Colour stays enabled**. The
  fill's picker offers no No Colour.
- **A file's callout restyled** -- its end, style or thickness -- has its
  rectangle and `/RD` worked out afresh round its box and leader, and a
  drawing of our own.
- **The strip**: the swatch and the thickness, Hairline to 12, for the
  armed tool and for a selected callout.

## Stamp

Made by the Stamps palette tool. Complete.

### Requirements

- **One mark, one tool.** The Stamps palette tool makes a **Stamp**, and
  its form is *Stamp Properties*. A Stamp is a `/Stamp` that is not a
  Scalable Comment, which is the `/Stamp` named `/Comment`.
- **Our own artwork, not Acrobat's.** Acrobat's stamp pictures are
  Adobe's design, shipped with Acrobat; this application does not copy
  them. A stamp a file already has keeps its own drawing, whoever made
  it, and is shown, moved and resized with it. New stamps are drawn to our
  own design, as PDFGear's are -- the word in bold italic in a rounded
  frame -- under the names the PDF standard gives them, so any reader
  knows what each one is.
- **The presets**, in a category of their own (see the palette, below): Approved, Not Approved, Draft, Final, Experimental,
  Confidential, Top Secret, For Comment, For Public Release, Not For
  Public Release, As Is, Expired, Departmental and Sold, the standard's
  fourteen; and Sign Here, Initial Here, Witness, a check mark and a
  cross, standing for Acrobat's Sign Here set. Coloured from the palette
  in three groups: green for approving, blue for work in progress, red for
  restricted or refused. Shown with their words spaced, "Not Approved".
- **Your own stamps**, as PDFGear makes them: **Text**, your words and a
  colour from the palette in the presets' frame, or **Image**, a PNG or a
  JPEG -- PDF and SVG perhaps later; a picture's transparency is its
  background, so there is no Remove background. Kept with the
  application's settings under your account, not in any document, each
  with its own copy of its picture, and listed after the presets in every
  document until deleted from the palette.
- **Stamp with date and time**: a choice in the palette that adds a second
  line as the stamp is placed -- the stamp tool's author and the date and
  time, "by David Smith, 13 Nov 2026 10:43" -- standing for Acrobat's
  Dynamic stamps, which fill theirs in with JavaScript.
- **Placing one.** Any text selection is cleared when the tool is chosen.
  The palette opens; a stamp picked from it is placed by a click, centred
  under the pointer at its own size -- a preset 30 points tall and as wide
  as its word, about 120 by 30 for Approved; a picture with its longer
  side 120 points -- or by a drag, which sizes it **with an outline shown
  as it is dragged**, keeping its proportions. **Departure from Acrobat**,
  which shows nothing until the button is let go.
- **Handles** on the four corners when it is selected, resizing it with
  its proportions kept, as the fixture's three Sign Here stamps have them;
  no turning.
- **Taking hold anywhere in its box**, with the move cursor over it, and
  the box shown only once it is selected, as the other drawings show
  theirs. Its box rather than what is drawn, since a stamp all but fills
  it and a check mark's stroke is a poor thing to aim at.
- **The properties form**: Colour and Opacity. The colour is the note's:
  it shows only as the note badge, the artwork keeping its own.
- **The strip**: the colour swatch, once a stamp is picked or selected.
- **The right-click menu** is the standard one, with the note entries.
- **Notes as for most marks**: a stamp's note is apart from its artwork --
  badge, hover summary, note window, replies and status.

### Plan

The fixture is page 3 of `corpus/Markup Drawing.pdf`: an Approved stamp
with a note and three Sign Here stamps at three sizes. **What Acrobat
writes**: a `/Stamp` with `/Name` the stamp's -- `/SBApproved`,
`/SHSignHere` -- and `/Subj` its title, the note's colour in `/C`,
opacity in `/CA`, a `/Popup`, and its artwork as the drawing, mapped onto
`/Rect`. **Ours** writes the standard's name for a preset -- `/Approved`,
`/NotApproved`, `/Draft` -- and a name of its own for one of yours, which
the standard allows; `/Subj` the stamp's title; and a drawing of our own,
a text stamp's words in an embedded font as a Text Box's are.

### Building it

Three stages, each tried in the application before the next:

1. **The mark.** A Stamp becomes a kind this application knows apart from
   the Scalable Comment: found by its box, selected, moved and resized by
   its corners with its proportions kept, its own drawing kept and fitted
   to its rectangle.
2. **The palette and the presets.** The Stamps palette, our nineteen
   presets drawn and written, placing by a click or a drag with its
   outline, and Stamp with date and time.
3. **Your own stamps, the form and the strip.** Text and Image stamps and
   stamps imported from a PDF, kept between sessions and deletable; the
   presets' words in the application's language; *Stamp Properties*, the
   strip's swatch, and notes.

**Agreed for stage 3** (2026-11-13):

- **Words as outlines, in the application's language.** A preset's word,
  and a text stamp's, is drawn as shapes made from a font on the computer
  -- as Acrobat's stamps are, which carry no font, each language edition
  having its own files -- so any script is drawn by every reader with
  nothing embedded. `/Name` stays the standard's, which is what a stamp
  means whatever it says.
- **Import from PDF**: any PDF, each page a stamp, offered in the palette
  to keep. Named from the file where it names its pages, as Acrobat's
  stamp files do -- `SBApproved=Approved` -- so one placed is written with
  that `/Name` and that title, and otherwise by the file's name and the
  page. A dynamic stamp's name and date are form fields and JavaScript,
  so it comes in as its fixed artwork alone. The application neither
  ships Acrobat's stamp files nor reads them from where Acrobat keeps
  them; opening one is the user's choice under their own licence.
- **Stamp with date and time** on text stamps too, the line under their
  words; not on image or imported stamps, which have no frame to hold it.
- **Deleting your own stamps**: Delete on a right-click in the palette,
  for your own only, asking first, since a deleted stamp's picture cannot
  be had back.

**Stage 1, as built:**

- **Told from a Scalable Comment** by its `/Name`: a `/Stamp` whose name is
  not one of the comment icons is a Stamp.
- **Drawn by the canvas from its own drawing**, so a drag carries it: the
  drawing is lifted out of the file as a PDF of one page that its box --
  `/BBox` through `/Matrix` -- exactly fills, rendered by PDFium at the
  size it is shown and fitted to the rectangle, at its opacity. On the
  copy that is shown its `/AP` is emptied, as a comment's is, and the
  drawing kept beside it for this. On the fixture's four it matches
  Acrobat's drawing by eye. It was left to the renderer before, baked into
  the page, so a drag moved its outline and left the stamp behind.
- **Taking hold anywhere in its box**; the box shows once it is selected,
  not on hover. **Four corner handles**, no turning: a corner's drag
  keeps the proportions, the opposite corner holding still, by **the way
  the pointer has moved further** in proportion to the side -- the larger
  of the two scales was taken at first, and grew a stamp dragged mostly
  inwards -- and never below 8 points on the shorter side.
- **Written**: a move or a resize changes `/Rect` and nothing else, so the
  stamp's own drawing is kept and fitted to it; no `/Rotate`, whose change
  would drop the drawing.
- **Not a comment.** Selecting a Stamp opens its note window only when it
  has a note, and its menu is a mark's with the note entries, without
  Copy Text. Both had taken any `/Stamp` for a Scalable Comment, which is
  its note: a click on a stamp with no note opened an empty note editor.

**Stage 2, as built:**

- **The palette** opens beside the strip while the tool is armed and
  closes with it: the nineteen drawn as they will be placed, one under
  another, their titles in the language shown as tooltips, and *Stamp
  with date and time* below. The stamp picked stays picked, and the tool
  stays armed for the next.
- **The presets' drawing**, ours: a rounded frame 2.5 points wide in the
  stamp's colour, filled with that colour at a tenth, the word in
  Helvetica Bold Oblique at 17 points -- one of the fonts every reader
  has, so nothing is embedded, measured by its published widths -- and
  for Sign Here, Initial Here and Witness the frame's left end an arrow; a
  check mark and a cross drawn as strokes, 30 points square. Approved is
  about 103 by 30. With the date, 38 tall, the line at 6.5 points under
  the word: "by" the stamp tool's author, the day, month, year and time.
- **The words were English** in stage 2, the standard's own: the font
  they were set in holds only Western European letters, and a word in
  another script would have been drawn as question marks. Stage 3 drew
  them as outlines in the application's language instead.
- **Placed** by a click, centred under the pointer at its own size at the
  page's own size, or by a drag from where it is pressed, as big as the
  further way the pointer has gone with its proportions kept, **its
  outline dashed as it is dragged**.
- **The stamp under the crosshair**, faded to half, as Reader's cursor
  becomes the stamp: centred under the pointer at the size a click would
  place it, and during a drag at the size it is being dragged to, inside
  its outline. The cursor stays the crosshair, as every drawing tool's
  is.
- **Written**: `/Name` the standard's for the fourteen and ours --
  `/SignHere`, `/InitialHere`, `/Witness`, `/Check`, `/Cross` -- for the
  rest, `/Subj` its English title, the drawing copied into the file as
  its appearance, faded there to its opacity, and a `/Popup` for its
  note. The canvas draws it from the same drawing as a file's stamp.

**Stage 3, as built:**

- **Words as outlines**, in `stampart`, apart from `markup` because it
  needs Qt: a stamp's words and its date line turned into paths by Qt
  from a sans serif in bold italic on the computer, any script it can
  draw -- Russian, Japanese, Arabic tried -- and written as filled shapes.
  The presets' words are in the application's language; `/Subj` is the
  title the stamp shows, as Acrobat writes its own. The date line is
  "by" the author and the date and time in the locale's short form.
- **Your own**, from *Add Stamp* under the list: **Text...**, your words
  and a colour from the palette, drawn in the presets' frame as they are
  typed, named `/` and the words run together; **Image...**, a PNG or a
  JPEG, its longer side 120 points and its transparency kept, named for
  the file; **Import from PDF...**, every page of a PDF offered with a
  tick to keep it, named as the file names its pages -- Acrobat's
  `SHWitness=Witness` -- or for the file and the page, and **sized by its
  `/ArtBox`**, where Acrobat's files mark the stamp on a letter-sized
  page; then its trim box; **then what is drawn on it**, found by drawing
  the page once on a clear background, with 2 points round it -- Acrobat's
  Standard file marks no art box, and taken whole each stamp was a speck
  in the palette; then the page.
- **Kept** with the application's settings as `markup/own-stamps`: a text
  stamp by its words and colour, so its date line is drawn afresh; a
  picture or a page by its drawing. Listed after the presets in every
  document; **Delete** on a right-click on one of them alone, asking
  first.
- ***Stamp Properties***: Colour and Opacity, no icons -- a stamp's look is
  its artwork -- for a stamp and for the tool's own form. **The note
  badge** is worn by a stamp with a note, as by the other marks.
- **The palette in categories**, agreed 2026-11-13 once a few imported
  files had buried the presets in one list: a drop-down of **Predefined**,
  **Text**, **Images**, and **one for each PDF imported**, named for the
  file, showing one at a time; a stamp added is shown in its category.
  **Delete Category** on a right-click on the drop-down, for a PDF's alone,
  asking first with how many stamps go with it; deleting a PDF's last
  stamp takes its category away too. The other three are always there.
- **Resizable** by a grip of our own in its corner -- Qt's `QSizeGrip`
  resizes the window it is in, and on a Mac is not shown inside one -- the stamps wrapping into as many
  columns as it is wide, each as wide as the widest stamp shown, as
  Acrobat's does. Its size and the category it showed are kept for next
  time. The stamp picked is shown by its whole cell: Qt's own mark of it
  was a bar where a label would be, and a stamp has none.

## File Attachment

Made by the Attach File tool. Complete.

### Requirements

- **One mark, one tool.** The Attach File tool makes a **File
  Attachment**, and its form is *File Attachment Properties*.
- **Placing one.** Any text selection is cleared when the tool is chosen,
  and the pointer becomes the icon the tool will place -- the one its
  defaults hold, the paperclip until another is chosen. A click opens a
  file dialog for one file; OK places the icon at the click, by its top
  left corner as a comment's icon is placed, in the strip's colour, and
  Cancel places nothing.
- **A large file is asked about.** Over **20 MB** a warning says how big
  it is and that the PDF will grow by that much and may be too large to
  send by email, with Attach and Cancel: 20 leaves room under the 25 MB
  most mail services take for the rest of the file. **Departure from
  Acrobat**, which attached 237 MB without a word.
- **The icon** is one of four, as Acrobat's: Graph, Paperclip, Attachment
  -- the standard's `/PushPin`, under Acrobat's name for it -- and Tag.
  **Drawn to our own design**, Acrobat's glyphs being Adobe's; an
  attachment a file already has keeps its drawing until its icon is
  changed. A fixed size on screen, as a comment's icon is: it does not
  grow with the zoom, and **is not resized**.
- **Moving and the cursor**: taken hold of by its icon, with the move
  cursor over it, and dragged; selected, it is outlined.
- **No Open File.** Acrobat's menu offers it and opens the file on a
  double-click; an attached file can be anything, and opening one is how
  a document delivers what it carries. **Departure from Acrobat**: the
  menu offers **Save Embedded File to Disk** and not Open File, and a
  double-click does nothing.
- **No notes and no replies**, as in Acrobat, whose menu for one has no
  note entries: `/Contents` is the file's name. Status as for a Text Box.
  The pointer over it shows the file's name and size.
- **The properties form**: Icon, Colour and Opacity, as Acrobat's -- the
  colour the icon's.
- **The strip**: the colour swatch.
- **Starting colour Purple**, read off Acrobat with its preferences
  cleared: `tools.py` had Red, which nothing had checked.

### Plan

The fixture is page 1 of `corpus/Markup Attach File.pdf`: two paperclips,
one carrying a 7 MB recording and one a PDF. **What Acrobat writes**: a
`/FileAttachment` with `/Name` the icon, `/Subj File Attachment`,
`/Contents` the file's name, `/C`, `/F 28` -- printed, not zoomed, not
turned -- a 7 by 17 point `/Rect` for the paperclip, no `/Popup`, and the
file in `/FS`: a file specification with `/F` and `/UF` its name and
`/EF /F` the embedded file, its size in `/Params`.

### Building it

Three stages, each tried in the application before the next:

1. **The mark.** An attachment a file has: found by its icon and drawn by
   the canvas, its own drawing kept, moved, and its file saved to disk
   from its menu; the pointer over it naming the file.
2. **Making one.** The Attach File tool, its cursor, the file dialog and
   the 20 MB warning; our four icons; written as Acrobat writes one.
3. **The form and the strip**: *File Attachment Properties*, the icon
   changed there, the strip's swatch, and Status.

**Stage 1, as built:**

- **Drawn by the canvas from its own drawing**, lifted out as a Stamp's is,
  in its own rectangle -- not a comment icon's box -- held at that size on
  screen whatever the zoom, as `/F` NoZoom asks and as a comment's is.
  PDFium ignores the flag and scales it with the page, so it is drawn
  larger there than here and in Acrobat.
- **Taken hold of by its icon**, with the move cursor, and **moved**:
  `/Rect` shifted at its size, its drawing and its file kept.
- **The pointer over it** names its file and its size, in MB and kB as the
  Finder gives them: it has no note, so no panel, and the tooltip stays.
- **Its menu**: Delete, Set status, Make current properties default and
  Properties, then **Save Embedded File to Disk...** in a group of its own
  at the foot, where Acrobat's menu has it, photographed in the notes --
  it was put first at first -- no note entries and no Copy Text. **Saved** byte for byte from the document being shown, which
  carries the file; never opened. A double-click does nothing.
- **No badge and no note window**: its `/Contents` is its file's name.

**Stage 2, as built:**

- **The tool**: its pointer the icon it will place, drawn half as large
  again so it can be seen, its hot spot the top left corner the icon is
  placed by. A click asks for the file; Cancel places nothing and takes
  no undo step. Over 20 MB a warning gives the file's size, with Attach
  and Cancel. The file is read then, as Acrobat embeds it then, and kept
  on the mark until it is written.
- **Placed** by its top left at the click, at its own size on the page a
  reader draws it on, in the tool's colour -- now Purple.
- **Our four icons**: a graph of three bars in a frame, 20 by 20; a
  paperclip, one wire running three lines side by side, 7 by 17 -- drawn
  first as two loops on top of each other, which read as a capsule; a
  push pin, 13 by 20; and a tag with its hole, 20 by 13. The push pin's
  and the tag's sizes are ours, Acrobat's fixture having neither. Each in
  its colour with a dark edge.
- **Written as Acrobat writes one**: `/Name` the icon, `/Subj File
  Attachment`, `/Contents` the file's name, `/F 28`, no `/Popup`, and the
  file in `/FS` -- `/F` and `/UF` its name, `/EF /F` the embedded file with
  its type, and its size, MD5 checksum and dates in `/Params`. The type's
  slash is pikepdf's to escape: escaping it first wrote `#232F`.
- **Save Embedded File to Disk** on one made here writes the bytes it
  carries.

**Stage 3, as built:**

- ***File Attachment Properties***: Colour, Opacity and Icon -- laid out as
  a comment's form is, the other form with an icon list, so the same
  control is in the same place -- the four icons drawn as the page gets
  them, each centred in one box so their names line up. The tool's own
  form the same: the icon chosen there is the one it places next, and its
  pointer.
- **A new icon or colour**, from the form or the strip's swatch, gives an
  attachment our drawing in it -- one the file brought as well -- a new
  icon its own size hung from the same top left corner; its file and its
  place kept.
- **Status** from its menu and the form's Review History, as a Text Box's.
