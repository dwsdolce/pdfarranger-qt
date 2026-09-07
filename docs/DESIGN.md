# Design records

What the application was decided to do, and why — the reasoning behind behaviour
that is not obvious from the code, and would otherwise be re-litigated every
time somebody reads it.

The measurements these decisions rest on are in [FINDINGS.md](FINDINGS.md).

## Editing bookmarks — the design

Settled with David before building, and worth reading before changing any of it:
several of these look arbitrary and are not.

**Where.** Read mode, in the outline sidebar that is already there. Bookmarks
are a reading construct -- you notice you want one while reading -- and the
tree, its navigation and its selection all exist. Arrange mode gets nothing: the
one operation that would suit it, picking a target page out of the grid, is
covered by "re-home to the page I am on".

**What a bookmark points at** is D20: a page uid, not an index and not the
object. See there.

**The outline comes from the file that was loaded**, once, on open --
`read_outline()` in `exporter_outlines.py`, the counterpart to
`rebuild_outlines()`. That matters more than it sounds. Read mode shows an
in-memory *export* of the page list (D15) whenever anything has been edited, and
the D19 fast path shows the source file when nothing has; so the sidebar's
outline came from one document or the other depending on edit state, and was a
*reconstruction* in the first case. Owning it removes the question.

`deduplicate_outlines()` runs at read time rather than at export. A book shipped
one chapter per file repeats its whole outline in each -- the Handbook has 45 --
and collapsing them where the user can see and edit the result is better than
doing it invisibly on save.

**Importing a second file concatenates its outline at the root.** No wrapper
node per file: that is exactly the shape the Handbook already has, and its `1`
wrapper is the first thing anyone would want to delete.

**The commands**, on the tree's context menu:

| command | behaviour |
| --- | --- |
| Add | Sibling *after* the selected entry, or end of root; title from the selected text, else the page label. What Acrobat's Ctrl+B does |
| Add Child | The same, nested. Free to offer here, and easier than dragging |
| Re-home | Target becomes the current page. **The title is kept** -- it may have been edited, and need not match anything in the document |
| Rename | One act, one undo entry: undo returns to before the rename began, not to a half-typed state |
| Delete | Children are **promoted** into its place, not deleted with it |
| Delete with Children | The subtree, all of it. Off on a leaf, where it would be Delete under another name |
| Delete Dangling | Every dangling entry, however it came to dangle. **Headings are left alone** -- that is what the third state is for. One undo entry for the lot, and children are promoted as above |

Deleting a node promoting its children is what makes the Handbook's `1` wrapper
removable in one operation, which is the case that prompted all of this. Delete
with Children is the opposite job -- throwing a chapter away along with its
sections -- and it is a separate command rather than a modifier because doing it
by promoting and then deleting each child in turn is one undo entry per bookmark
and a great deal of clicking.

Three things about the commands that the design above does not decide, settled
while building them:

*They bracket themselves.* `OutlineModel` emits `about_to_edit(label)` before it
touches anything and `edited` afterwards; `ReaderView` forwards both, and the
window turns the first into `undo.commit(label)` and the second into "modified".
The reader never touches the undo stack, which belongs to the page list -- and
the snapshot has to be taken *before* the change, because undo restores the
state a command started from.

*They move rows rather than resetting the model.* A reset is four lines shorter
and collapses the tree and drops the selection every time -- on 807 entries,
finding your place again is the entire cost of the command. Delete is the awkward
one, because promoting children is two operations as far as a view is concerned:
the children move out to stand where their parent stood, then the parent goes.
Resets are left to the two things that really are wholesale, a newly loaded
document and an undo.

*An outline edit does not date the rendered document.* Only the outline changed,
so the reader's in-memory export is still current. Re-exporting 1590 pages
because a bookmark was renamed would be a strange way to spend four seconds.

One deliberate omission: Add does not open the rename editor on the entry it
just made. Acrobat does, and it saves a step -- but Add and Rename are separate
acts with separate undo entries, and starting an editor here would make one
command look like two on the stack. Cheap to change if it turns out to grate.

Until the outline is written on save (the next step), these edits live in the
document and its undo history but not in the file: a save still rebuilds the
outline from the sources the way it always has.

**Editing bookmarks marks the document modified.** The outline is part of the
document; a save writes it.

**Dangling bookmarks.** A bookmark whose page has gone is *kept*, marked, and
re-homable, rather than deleted. The rule everything follows from: **whatever is
in the outline gets saved, so a reload looks the same.**

Three states, and the difference is worth keeping straight:

- *targeted* -- resolves to a page in the document
- *heading* -- no destination at all, which is legal and deliberate. The
  Handbook's `1` is one
- *dangling* -- declared a target that cannot be honoured

Both of the last two arrive with no page. They are still distinguishable **on
load**: a heading has no destination in the file, a dangling entry has one that
does not resolve. So the tree can mark them correctly on open without guessing,
and Delete Dangling can leave real headings alone.

The one thing that cannot survive is *our own* dangling through a save. Once the
page is gone there is no valid way to write "points at a page that no longer
exists", so it is written without a destination and comes back as a heading. A
narrow loss, and the alternative -- a private key in the PDF -- is worse.
## Double-click selects a word

PDFium has no "which character is at this point". What it has is
`getSelection(page, from, to)`, which needs a glyph under *both* ends -- the
same fussiness `PageText` already snaps around for dragging. So the character
index under the pointer is found the roundabout way: select from the start of
the page's text up to the point, and ask how long that came out. A page-wide
selection thrown away immediately, which is fine once per click -- this is the
machinery shift+click extension uses too -- and would not be once per mouse
move, which is why dragging does not use it.

Which glyph that index names -- the one under the pointer or the one before it
-- depends on where in the glyph the pointer sat, because characters are not
equally wide. Rather than trying to be exact, `word_bounds` tries both, word
first. That makes the boundary cases behave: clicking the first letter of a word
finds the word rather than the space in front of it.

A word is alphanumerics and the underscore. A hyphen breaks one, so
double-clicking in "pdfarranger-qt" gets you one half -- deliberate, because the
other rule makes selecting one half of a compound impossible. A click that lands
on no word selects the single character it hit, the way a text view does.

**A double-click on a link follows the link.** Qt delivers the first click's
release before it can know a second is coming, and that release is what follows
a link. Deferring it behind `doubleClickInterval` would put 400 ms of latency on
every link in the document to rescue a gesture nobody makes on a link. So the
click wins, which is what every PDF reader does -- and it is why the fixture for
these tests is `test_raster_image_text.pdf`: it is the only one with a line of
prose that PDFium does not infer a link from.
## The window title belongs to the platform

It was `*name - PDF Arranger Qt` on all three platforms. That is the *Windows*
convention: on macOS the application's name is already in the menu bar, so
repeating it in every window title is noise, and Acrobat shows the document and
nothing else. `DOCUMENT_ONLY_TITLE` picks the form; `title_for` takes the
convention as an argument rather than reading the platform, so all three shapes
are testable from any one of them -- the lesson the theme tests taught.

The modified marker was a hand-rolled leading asterisk, which is again the
Windows signal drawn everywhere. It is Qt's `[*]` placeholder now, with
`setWindowModified`: the dot in the close button on macOS, an asterisk on
Windows and Linux, and no string handling of our own. Note that `windowTitle()`
still returns the placeholder -- Qt substitutes it on the way to the window
manager -- so a test asserting on the *displayed* title would be asserting on
something it cannot see. `isWindowModified()` is the thing to check.

`setWindowFilePath` gives macOS the proxy icon: the small document in the title
bar that can be dragged out or command-clicked for the folder holding it.
Ignored where there is no such thing. The title still wins for the text, since
Qt only falls back to the path when no title has been set.
## Opening a document from the Finder

The bundle declares `CFBundleDocumentTypes` for `com.adobe.pdf`, so macOS offers
the application under *Open With* and lets it be set as the default handler.
That part always worked. Double-clicking a PDF then did **nothing at all**,
which is the worst shape a bug can take: the association is visibly correct, so
nothing points at the application.

macOS does not put the file on the command line. The Finder sends an Apple
Event, which Qt delivers as a `QFileOpenEvent` to the `QApplication`, and
nothing listened for it. The spec's own comment asserted the opposite -- that
opening one made it "arrive as command-line arguments" -- which is how the gap
survived being read more than once. It is corrected there now.

`app.Application` handles the event. It collects paths rather than acting on
them directly, because the event can arrive **before there is a window** to put
a document in; `main()` drains what accumulated during start-up into the first
window, and listens for later ones.

**Where a later document lands.** A document this window already holds is
ignored. Otherwise an empty, untouched window takes it, and anything else gets a
window of its own -- two documents open at once is the point, since that is how
you compare them. macOS will not launch a second copy of a bundled application;
it sends the event to the process already running.

**The first version of this had to be stopped with a forced reboot**, and the
reason is worth keeping. It asked only whether the window was empty:

    if window.model.rowCount() == 0 and not window.modified:
        window.open_paths([path])
    else:
        window.new_window([path])          # launches a process

A process launched to open a document fills its window from the command line
*before* the open-event reaches it. So in every launched process the answer was
"not empty" and the branch taken was the one that launches another process --
which did the same. The guard was not merely weak, it was **inverted for exactly
the case that recurses**: false by construction in every child. Hundreds of
processes, and no way to stop them from inside the application.

`MainWindow.holds` is the fix: the window has to *recognise* the document, not
merely notice that it has one. Paths are resolved with `realpath` before
comparing, because `/tmp` is a symlink on macOS and a guard that compares the
path as given can be walked around by the same file under another name.

`Application.may_spawn` sits behind that as an absolute backstop -- at most four
windows for desktop documents in ten seconds. It is not the mechanism and is not
expected to fire: it exists because `holds` compares paths, a comparison can be
fooled, and this is a code path that *creates processes*. Anything fallible
guarding process creation wants something inarguable behind it. Four in ten
seconds is far beyond what anyone does by hand and stops a runaway in under a
second.

`MainWindow.new_window` gained a `paths` argument for it, which suits the
NON_UNIQUE design (see the upstream wiki notes in [PORTING-NOTES.md](PORTING-NOTES.md)): a second document really is a second process, exactly as
*New Window* has always been.

**Windows and Linux are untouched by this**, and for a reason worth writing
down: on both, a document opened from the desktop really *does* arrive as a
command-line argument -- Linux through `Exec=pdfarranger-qt %U` with
`MimeType=application/pdf` in the desktop entry, Windows through the installer's
`"{app}\{exe}" "%1"` -- which `main()` has always handled. `QEvent.FileOpen` is
never emitted there at all, so the new handler is inert. macOS was the odd one
out and the only one that needed anything.

One trap this opened, caught before it could bite. `new_window` gained a `paths`
parameter, and `QAction.triggered` passes the action's *checked state* to its
slot -- so *New Window* from the menu began calling `new_window(False)`. It is
harmless only because the action is not checkable and `False or []` is empty;
make it checkable one day and it is a `TypeError`. The connection is wrapped in
a lambda now, with a test that the menu command passes no paths.

Not verifiable from the suite, and worth saying so: these tests drive the event
handler and the placement rule, but whether the Finder actually reaches them can
only be seen in a built and installed bundle.
## The arrow keys — one table, no modes

Settled with David after he tested Acrobat properly and found it
indefensible. His notes, in continuous mode alone: with no caret, `↑`/`↓`
scroll a line, `←`/`→` jump to the previous or next page top, Shift+`↑`/`↓`
scroll a screen but Shift+`←`/`→` does what unmodified does, Cmd does page
tops, Fn+`←`/`→` is home/end and Fn+`↑`/`↓` is a screen. *With* a caret nearly
every one of those changes meaning, and "Cmd arrow sometimes moves the caret and
sometimes pages". Five different ways to scroll, and a mapping that depends on
whether you happened to click on some text earlier.

So this is ours, not Acrobat's. **The modifier alone decides the verb, and
nothing changes depending on whether a caret exists:**

> nothing = scroll · Option = move the caret · Shift = extend the selection ·
> Cmd = jump to an edge · Fn = a bigger jump

| chord | continuous | single page |
| --- | --- | --- |
| `↑` `↓` | scroll one line | — |
| `←` `→` | top of previous / next page | previous / next page |
| Fn+`↑` `↓` | scroll one screen | previous / next page |
| Fn+`←` `→` | start / end of document | same |
| Opt+arrow | move the caret, by line or character | same |
| Shift+arrow | extend the selection, by line or character | same |
| Cmd+`←` `→` | caret to start / end of line | same |
| Cmd+`↑` `↓` | caret to start / end of document | same |
| Cmd+Opt+`←` `→` | move the caret one word | same |
| Shift+Opt+`←` `→` | extend the selection one word | same |

Adding Shift to a Cmd or Option chord extends instead of moving, and adding
Option works by the word: Shift+Cmd+`→` extends to the end of the line,
Shift+Opt+`→` extends one word.

The word rows came later -- they fell out when the `QKeySequence` handler was
replaced by this table, and `_step_word` sat uncalled until David noticed. They
cost the table's one inelegance: **Option does double duty**, meaning "move the
caret" on its own and "by the word" when added to Shift or Cmd. The alternative
was Option meaning word outright, which is tidier and macOS's own convention but
gives up moving the caret a character at a time. Both granularities were wanted,
and losing a capability is the larger cost.

**Option moves the caret, not the bare arrow.** The one deliberate departure
from a text editor, and it is what buys the whole scheme: bare arrows always
scroll, so *reading* never behaves differently because you clicked on a word ten
minutes ago. With no caret placed, the Option, Shift and Cmd chords do nothing
at all rather than falling through to scrolling -- which is what makes the table
true as written, and what stops a shift+arrow quietly turning into a scroll.

**Control appears nowhere.** macOS takes Ctrl+`↑`/`↓` for Mission Control and
App Exposé, so the application never sees them; Qt's own `MoveToNextPage`
binding of `Meta+Down` is dead on that platform. Worth knowing before wondering
why it is unused.

**The same table on every platform**, rather than each platform's own text
conventions. On Windows and Linux Ctrl+`←` conventionally means word-left, and
here it means start-of-line. One table everywhere is the simplicity that was
asked for, and mapping the *same* verbs onto different chords per platform would
undo it. This is why these are explicit modifiers rather than `QKeySequence`
standard keys, unlike Copy and Select All -- the scheme is ours, so no platform
has an opinion about it.

**Caret lifetime, simplified with it.** Placed by a click on text; cleared by
Escape and by a new document; and it survives everything else -- scrolling,
paging, and clicking off the page. Clicking off the page still clears the
*selection*, which is David's rule and Acrobat's. The earlier "dies on a page
turn" is gone: it was the source of the bug where scrolling to look at a
selection made the next shift+arrow scroll instead of extend, and with the table
above there is no longer any reason for a position in the document to evaporate
because the view moved.
## Keyboard text selection — the design

Settled with David before building, from his testing of Acrobat rather than
from documentation. The short version: **this is Acrobat's model, and it costs
us nothing**, which is not what the tracker entry expected.

**Plain arrow keys are not involved.** The tracker warned that the arrows
"currently own scrolling and page navigation outright and would have to be
shared". They do not have to be. In Acrobat, with a cursor placed, an unmodified
arrow key does *nothing* -- click to place, shift+arrow to extend, and that is
the entire keyboard story. So the arrows go on scrolling in continuous mode and
turning pages in single page mode, which is more than Acrobat offers, and
shift+arrow was unbound anyway. The conflict this step was waiting on turned out
not to exist.

Worth recording what the arrows actually did, since it was mis-stated once:
`←`/`→` scroll *horizontally*, and there is no horizontal range at fit width --
0 at fit width, 1235 at 3x -- so they appear dead in the mode people read in.

**Keys come from `QKeySequence`, not from us.** The module already does this for
Copy and Select All, and it is the only way to be right on three platforms:
extend-by-word is `Alt+Shift+Arrow`, which on macOS is Option+Shift, and
start-of-line is `Ctrl+Left`, which Qt maps to Cmd. An earlier draft of this
section proposed Ctrl+Left/Right for word-wise, which is simply wrong on macOS.
It also settles Home/End without a judgement call: they keep meaning first and
last *page*, which is consistent with macOS, where Home/End already mean start
and end of document rather than of line.

**Granularity is exact**, unlike the mouse. Section *Extending a selection* has
the mouse snapping the moving end to a whole word because a click is one
imprecise shot; a keypress is not, so shift+arrow moves by exactly one
character, one word or one line. Same rule stated once: granularity follows the
precision of the gesture.

| decision | choice |
| --- | --- |
| the caret | a **blinking** vertical bar, as Acrobat draws it |
| shift+`←`/`→` | one character |
| Opt+shift+`←`/`→` | one word |
| shift+`↑`/`↓` | one line, and **across page boundaries**, as a drag already runs |
| lifetime | dies on a page turn, a mode change, or a reload -- Acrobat's behaviour |
| Escape | clears the caret **and** the selection |

Two of those were argued rather than copied.

*Escape* clears both. Acrobat clears the caret and leaves the selection; ours
already cleared the selection and had a test for it, and taking that away to
match Acrobat would have removed working behaviour to gain nothing.

*Moving a line follows the document's text order*, not the geometry of the page.
David found that Acrobat on a multi-column page walks column 1, then column 3,
then column 2 -- and called it weird twice, which it is. It is the *document's*
weirdness rather than Acrobat's: the text stream is ordered that way and Acrobat
follows it faithfully. We follow it too, for the same reason indices rather than
geometry decide which end of a shift+click moves (see *Extending a selection*):
geometry is what gets two-column pages wrong, and having the keyboard disagree
with the mouse about the same text would be worse than either being odd on its
own. Consistency with ourselves beats being locally clever.

A consequence worth knowing: because lines come from the page's text with its
newlines in it, moving up and down needs no geometry at all. The column position
is an offset within the line, which is what a text editor does on a plain
string. The trap in that, found by a failing test: `line_bounds` stops *before*
the carriage return, so stepping one character past the end of a line lands on
the `\r` or the `\n`, both of which resolve back to the line just left. Moving
down has to jump past the break, not onto it.

**Scrolling is not turning the page, and the difference is load-bearing.**
"The caret dies on a page turn" was first written as "dies when the current page
changes" -- which in continuous mode is simply what scrolling does. David found
it immediately: extend a selection onto the next page, scroll to look at it, and
the next shift+arrow scrolled the view instead of extending, because going to
find the selection had destroyed the caret and the key fell through to the
scroll area. The rule now hangs off `go_to_page`, which is the funnel for every
deliberate move -- next, previous, first, last, the page box, a bookmark -- so
turning the page still drops the caret and scrolling does not.

The same report had a second fault in it: extending did not scroll the view at
all, so a keyboard selection walked off the bottom of the window and had to be
chased. `ensure_caret_visible` now follows the moving end by as little as will
do, rather than centring it, so the text being selected stays where the eye
already is. The two faults compounded -- the first made you scroll, and the
second punished you for it.

**The offscreen platform does not agree with macOS about what the keys are.**
`SelectNextWord` is `Alt+Shift+Right` under cocoa and `Ctrl+Shift+Right` under
the offscreen plugin the suite runs on. That is the whole argument for asking
`QKeySequence` rather than naming keys -- and it applies to the *tests* as well,
which is where it was found: a test pressing Alt+Shift+Right passed by hand and
failed under pytest. It now asks for the platform's own binding, exactly as the
implementation does. Same lesson as the theme tests in [FINDINGS.md](FINDINGS.md), *Colour schemes do not exist under the offscreen platform*: never assert
against something the environment defines differently.
## Extending a selection, and why it is not Acrobat's rule

Shift+click extends the selection from the anchor to the click. Shift's only job
is to say "keep the anchor" rather than "start again" -- it does not change how
the selection is measured. The anchor outlives the drag that set it, because
extending from a position placed earlier is the entire point; a plain click that
selects nothing still leaves one behind, which is Acrobat's insertion point
under another name.

**The rule: granularity follows the precision of the gesture.**

| gesture | granularity |
| --- | --- |
| drag | character, both ends. It is continuous -- you watch it and stop where you like |
| shift+click | the anchor end keeps its character; the moving end grows outward to a whole word. One discrete shot at a position, so snapping the end it moves is help rather than interference |
| double-click | the word, by definition |
| shift+drag | a drag whose anchor came from earlier, so: character |

**Acrobat does the opposite and we deliberately did not copy it.** Measured in
Acrobat, by David, on real documents: dragging inside the starting word selects
by character; crossing out of that word selects the starting word *whole* and
every subsequent word whole; dragging back in returns the first word to
characters but leaves the rest by word; and moving *towards* the anchor gives
characters again until the direction reverses. Hyphens and punctuation split the
added words but not the starting one -- which is not a separate rule, it is the
same fact, since the starting word is never word-segmented at all.

The direction dependence is the disqualifying part: the same two endpoints give
different selections depending on the path the mouse took to reach them, so the
gesture cannot be described, only demonstrated. Here a selection is a function
of its two ends and nothing else, which is what most of
`TestExtendingASelection` checks.

**Indices, not points.** The drag path stays point-based and untouched.
Extension is index-based, because deciding which end moves means asking which
comes first in *reading* order, and comparing geometrically -- page, then y,
then x -- gets that wrong on a two-column page like the Handbook's, where the
top of the right column follows the bottom of the left one. PDFium's character
indices are already in reading order. The index of a point costs one page-wide
`getSelection`, which is why an ordinary press does not pay for it: the anchor
records a point, and the index is worked out only when a later shift+click
actually reads it.

**A shifted press does not follow the link under it.** Most of these documents'
text is link as far as PDFium is concerned (see *Most of a document's links are
not in the document*), so without that exemption the gesture would fail on
exactly the documents it exists for.

Still to come, as its own step: a painted caret and shift+arrow, which is how
Acrobat does character-exact keyboard extension. It needs a visible insertion
point and it collides with the arrow keys, which currently scroll and change
pages.
## Shift-click selects a rectangle, not a range

Reported by David with a screenshot: shift-clicking across the grid selected
pages 1-2 and 5-17 but not 3, 4 or 18. Not a range, and not obviously anything.

`ExtendedSelection` on a `QListView` in **IconMode** selects by *rectangle* --
Qt takes the box spanned between the anchor and the clicked item and selects
what it touches. In a single column that is indistinguishable from a range,
which is why this is not a famous problem. On a wrapped grid it is a block; on a
wrapped grid of pages that are *not all the same width*, with the delegate
placing the items itself, it is neither the range you asked for nor anything you
could predict, and often it selects only the page clicked.

So the range is computed in `mousePressEvent`, which was ours already (D9), from
the last page clicked without a modifier. Shift+ctrl extends without dropping
what is already selected. Extending deliberately does not scroll -- you clicked
the far end, so it is on screen, and `set_selected_rows` would otherwise jump
the view back to the anchor, which is why it grew a `scroll` parameter.

**Handling the press is not enough, and this is the part that cost two rounds.**
Qt has to be kept out of the whole gesture, press to release, because it will
undo the range in two more places:

- On **release**, it redoes the selection from the position it recorded at the
  last press it saw. Our handler returns before Qt sees the shifted press, so
  that position is still the plain click that set the anchor -- and Qt draws its
  rectangle between exactly the two pages we had just handled properly.
- On **mouse move**, it treats a held button as a drag-selection and rewrites
  the range on the first twitch of the pointer.

Both depend on where the pointer happens to land, which is why the bug was
intermittent rather than reliable -- "sometimes works and sometimes does not",
which is a much worse thing to debug than "never works". An `_extending` flag
now owns the gesture until the button comes up.

Qt's rubber band is left alone. Selecting a rectangle is exactly right when the
user is dragging one out; it is only wrong as an interpretation of shift.
## Opening a document selects nothing

`insert_pages` selects what it inserted. That is right for **Import** and
**Paste** -- it shows you where the pages landed in a document too long to scan
and lets you act on them straight away -- and meaningless for **Open**, where
every page is new and selecting every page points out nothing.

Nobody had noticed because nothing depended on it, until a selection began
telling the reader where to open (above): a document that arrived with all of
itself selected would always have sent the reader to page 1, and the stored
reading position could never apply again. The first fix was a special case in
the reader rule -- "unless everything is selected" -- which David rightly asked
about, because the real question was why opening selected everything at all. It
is fixed where it happens instead, and the special case is gone.

Two tests in `test_reader.py` were relying on it for a selection they needed but
never asked for. Both now say what they want, and one of them got stronger for
it: "editing actions are disabled while reading" means more when there *is*
something selected to edit.
## The status bar has to keep saying where you are

Read mode showed "Page 14 of 1590" through `showMessage(..., 3000)`, emitted
only from `_reader_page_changed`. So it said nothing at all until you scrolled,
and nothing again three seconds later -- and switching modes left whatever had
been there before. The comment on the mode label two lines above it in
`_build_statusbar` already said why that mechanism is wrong; the page position
had simply not been given the same treatment.

It is now the same permanent label that counts the document, because in read
mode the two say the same thing: "Page 14 of 1590" carries the total as well.
`_refresh_state` sets it, so a mode switch updates it like everything else, and
`_reader_page_changed` keeps it current while scrolling.
## The current page follows you between the modes

Switching to read mode reads the **selected** page, the first of them when
several are selected. Switching back **scrolls** the grid to the page you were
reading and leaves the selection exactly as it was.

The asymmetry is deliberate, and it is David's: *selection means something when
arranging and nothing when reading*. Going in, a selection is the clearest
possible statement of which page you want; coming back, restealing the selection
would destroy something the reader never had any use for. So one direction reads
the selection and the other only scrolls.

No special case for a multi-page selection. "Start here" is the only reading of
it, and a rule with no "unless" beats one that tries to guess what several
selected pages might have meant.

Because nothing marks the page once the grid scrolls to it -- that being the
point of leaving the selection alone -- `scroll_to_row` centres it rather than
merely making it visible. At the edge of the viewport it would be showing you
the page without telling you which one it is.

**What this displaced.** Entering read mode used to restore `reading/<path>`, a
position persisted per document and written on the way out. That still happens
when nothing is selected, which is its real job: reopening a document where you
left it. A selection is something the user just did, and wins.

Worth keeping straight, because the two are not symmetric: the reader's page is
persisted across sessions, and the arranger's selection is not persisted at all.
It survives a mode switch only because nothing clears it, and it is restored by
*undo* -- `UndoState.selection` -- and by nothing else.
## Moving a page a long way, and why cut and paste is not a move

David's case: relocate one page in a 1300 page book without scrolling to the far
end. The obvious answer is cut and paste, and he tried it -- the page moved and
its bookmark was left behind, dangling.

That is D20 doing exactly what it says. `pages_from_clipboard` rebuilds pages
through `add_file`, so a pasted page is a **new page with a new uid**; the
bookmarks stayed with the original, and the original had gone. `Page.duplicate`
names paste as a new-identity case in as many words. It is the same rule that
stops the Duplicate command duplicating bookmarks, and it cannot be otherwise
while the clipboard is a cross-process byte format (D5): a paste can happen in
another process, or twice.

So cut and paste is a copy-and-delete. **Move to Start**, **Move to End** and
**Move to Page…** are the move -- they reorder the page list, so a page keeps
its identity and everything pointing at it comes along for free. That makes them
more than a convenience: they are the only way to relocate a page without
breaking its bookmarks.

`move_rows_to(rows, position)` takes the position the pages should *end up* at,
counted with the moved rows already lifted out. `move_rows(rows, dest)` -- what
a drop calls -- now converts into it. The two differ by exactly the number of
moved rows in front of the destination, which is nothing when moving backwards
and off by one when moving forwards: the sort of error that is invisible until
someone moves a page the other way.

"Becomes page N", not "lands in front of what is page N now". Settled with
David before building, because the two differ by one whenever the move goes
forwards, and picking wrong is obvious to whoever wrote it and to nobody else.
## Closing a document has to empty the outline

Found by David immediately after the save work landed: open a file, edit its
bookmarks, save, close -- and the whole tree stayed in the sidebar.

The cause is the point of D20. The outline used to be *derived*, so emptying the
page list emptied it by construction. Now the document owns it, and
`_reset_document` cleared the pages, the undo stack, the document set, the path,
the metadata and the search index -- everything except the one thing that had
just stopped being derived. Nothing in the old arrangement could have gone
wrong here, which is exactly why nothing checked it.

Worth stating what the bug actually risked, because "a stale sidebar" undersells
it: the entries were still live. They were editable, they were in the undo
state, and they would have been written into the *next* document saved from that
window.
## How a bookmark looks, and who decides when it is collapsed

A PDF outline item has exactly three presentation attributes beside its title
and its target. All three were being thrown away on save, and the test that was
supposed to cover them had never once run the code it named.

| attribute | key | note |
| --- | --- | --- |
| colour | `/C` | RGB, 0..1. pikepdf has **no API for it** -- `OutlineItem` offers `bold`, `italic`, `is_closed` and nothing else -- so it is written into the dictionary directly |
| bold / italic | `/F` | a bitfield: **1 italic, 2 bold**, so 3 is both. Those two bits are all the spec defines |
| collapsed | sign of `/Count` | negative closed, positive open. Not a key of its own, which is why it used to survive an export by accident while the other two did not |

**Why the old test proved nothing.** It built its fixture with `parent.obj =
pikepdf.Dictionary()` and set `/C` and `/F` on that. pikepdf discards a
hand-assigned `obj` when `open_outline()` writes the tree back, so the styles
never entered the source document and the test failed in its own setup. It was
marked xfail against pikepdf, which hid that completely. The lesson is the same
one the skipped theme tests taught: a test that never runs the code it names is
worse than no test, because it reads like coverage.

The blamed cause was real, though, and applies to `rebuild_outlines`: that hands
`OutlineItem` a `copy_foreign`'d dictionary, and pikepdf rebuilds the dictionary
from its own fields on write, dropping anything it does not know about.
`write_outline` sidesteps it -- bold and italic through pikepdf's API, `/C`
written afterwards by walking the tree just written alongside the one it came
from. `rebuild_outlines` was left alone: since D20 it is on no path that saves a
file, because every save and export supplies the document's own outline.

**Collapsed state follows Acrobat, deliberately.** The panel's shape is written
when the document is saved, and toggling it is *not* itself a modification. So
reading a document and opening a chapter costs nothing -- no dirty flag, no undo
entry -- and if you save for any other reason, the shape you left it in goes
with it. David's argument, and it is the right one: if you never save, expansion
cannot affect anything; if you are saving, it is because something really
changed, and the panel may as well come along.

Acrobat's own version has a trap that ours does not inherit. Its Save does
nothing on an unmodified document, so people resort to Save As, or to adding an
annotation and deleting it, purely to make the save happen -- there are forum
threads about little else. Our Save writes whenever it is asked, so the state
goes out without the trick.

This forced one change with visible consequences: the sidebar no longer opens at
`expandToDepth(1)`. It opens the way the *document* says, because "what you see
is what gets saved" would otherwise mean any save at all -- for a rotation, for
anything -- silently rewriting the collapse state to two levels deep. A book
that ships collapsed opens collapsed; one that says nothing opens expanded,
which is what an absent or positive `/Count` means. Faithful rather than
friendly, because the friendly fallback reintroduces the silent rewrite in a
smaller form.

**Editing.** Bold, Italic, Colour and Default Colour are on the tree's context
menu, and unlike expanding they *are* edits: undo entry, document modified. The
tree draws all three, since an attribute you cannot see is a strange thing to be
able to change -- with one precedence rule, that the grey of a dangling entry
beats the entry's own colour. A state the reader needs beats a decoration they
chose.

Expand All Children and Collapse All Children work on any node and reach the
whole subtree, not one level. They go through the same `expanded` and
`collapsed` signals as clicking the arrows, so they are recorded the same way
and are not edits either.
## Dragging in the outline tree

`Outline.move` already existed and was tested, so this is Qt plumbing, with two
things in it worth remembering.

**What a drop carries is a path, not an index.** Qt's own
`x-qabstractitemmodeldatalist` encodes a row and a column, and a position in a
tree is neither; turning one back into "which bookmark" means guessing. The mime
type here carries the entry's path from the root -- `0/2/1` -- which decodes
without ambiguity.

**Both halves adjust, so only one of them may.** `beginMoveRows` and
`Outline.move` each take the destination in *pre-move* coordinates and each do
their own shifting for the case where an entry travels forward among its own
siblings. Adjusting it in the drop handler as well lands the entry one place
short, every time, in exactly that case and no other -- which is the sort of
thing that ships. Two tests cover it, and both fail if the adjustment is added
back.

Refusals are made in `canDropMimeData` as well as in the move itself, so the
view greys a drop that would put an entry inside its own subtree while the drag
is still in the air rather than swallowing it on release. A drop where the entry
already sits is refused the same way: it is not an edit, and it should not mark
the document modified or take an undo entry.
## Saving the outline

The step the other eight were waiting on. Until it landed, every bookmark
command worked, marked the document modified and undid correctly -- and was
thrown away by the next save, which rebuilt the outline from the source files.
A feature that lies is worse than one that is missing.

Three things had to be preserved on the way, none of them obvious from the
model alone. `rebuild_outlines` does four jobs, not one.

**Within-page position.** A destination is not a page, it is a page *and a
view*: `/XYZ 100 700` lands part-way down. `read_outline` resolved to a page and
kept nothing else, so writing our tree back would have flattened every bookmark
in the Handbook to the top of its page. `Bookmark.view` now keeps the
destination's tail as plain values -- the page still comes from the uid, so
reordering stays free (D20), and only the position on it is remembered.
Re-homing clears it, because a position on the old page means nothing on the
new one, and Add sets it from the selection, so a bookmark made from a selected
heading lands on that heading.

**Targets outside the document.** `/GoToR`, `/URI`, `/Launch`, `/GoToE`. There
is nothing here to resolve, but they are perfectly good bookmarks -- treating
"no in-document destination" as "no destination" once deleted 18,131 of the
Handbook's 18,179. `Bookmark.external` keeps the action opaquely and writes it
back verbatim. Opaque on purpose: `outline.py` never looks inside it, which is
what keeps that module free of pikepdf.

This also fixed a display bug nobody had reported. Before `external` existed,
every cross-file bookmark arrived with no uid and a declared destination -- the
definition of *dangling* -- so the sidebar greyed them all and said their page
was gone, which was never true.

**Cross-file repair, and why it moved.** A `/GoToR` naming a file that is *also*
being loaded is a local jump once merged, and `external_target` already knew how
to spot one. That repair now happens in `read_outline` rather than at export,
because deduplication depends on it: the 45 copies of a chaptered book's outline
only become identical once their cross-file links resolve to the same pages.
Which is the other half --

**Deduplication moved to read time**, as the progress tracker in [PORTING-NOTES.md](PORTING-NOTES.md) always said it should. It is
an `Outline` method now, the same rule as `deduplicate_outlines` applied to our
own tree: a top-level subtree goes only if its whole shape -- every descendant's
depth, title and target -- repeats one already kept. It runs only when several
files contributed, because one document repeating a subtree is doing so on
purpose.

**Exporting a selection prunes.** The tree belongs to the document, so most of
it points at pages a subset does not contain. The rule: keep an entry only if it
has a destination in the file or a kept descendant. That way a deliberate
heading survives if anything under it did, the crowd of empty headings does not
arrive, and -- the reason for doing this rather than falling back to
`rebuild_outlines` -- an exported selection carries your *edits*, so a renamed
bookmark exports under the name you gave it.

**What still cannot survive** is our own dangling. There is no valid way to
write "points at a page that no longer exists", so it is written without a
destination and comes back as a heading. The title survives, which is the part
worth keeping.

One thing got cheaper on the way: read mode's export no longer asks for
outlines. The sidebar reads the document's own tree, so building one into a
throwaway export was work discarded on every mode switch -- and on a 1590 page
book that is not free.
## Owning the reader's view — the plan

Phase 7's largest item, and the prerequisite for two of the three things wanted
from phase 7: text selection and link following (D16) both need control of
painting and of mapping a screen point into page space. Bookmark *editing* does
not depend on this — the outline tree already exists — but bookmark *authoring*
gets much better with it, because a selection supplies both the title and an
`/XYZ` destination point instead of a bare page number.

**What is being replaced, and what is not.** Only `QPdfView`. `ReaderView` keeps
its splitter, the `QTreeView` outline over `QPdfBookmarkModel`, the
`QPdfPageSelector` with its page labels, and the `QPdfSearchModel`. The engine is
unchanged (D18). This is a widget swap, not a rewrite of read mode.

**Reuse rather than invention.** Three pieces of this already exist:

- `PageView` in `view.py` is a hand-rolled scrolling grid with its own
  `paintEvent`, `resizeEvent`, `wheelEvent` and mouse handling, built because
  Qt's item-view DnD answers the wrong question (D9). The reader's canvas is the
  same shape of widget with a simpler layout, and the cell-geometry trap in
  *Cell geometry must be relaid out by hand* applies unchanged.
- `Renderer` and `ThumbnailCache` in `render.py` already do asynchronous
  rendering with an LRU cache off the GUI thread.
- `QPdfLinkModel` gives `Rectangle`, `Page`, `Url`, `Location` and `linkAt()`,
  and `QPdfDocument.getSelection()`/`getSelectionAtIndex()` give text. Both were
  verified against the repaired Handbook: 20 links on page 0, correct rectangles
  and targets, `linkAt(centre)` hitting the right one.

**Measured before deciding.** Every page of two documents rendered once, cold,
on a 1512x982 screen at device pixel ratio 2 -- so 2000 px is roughly what a
maximised window asks for and 1000 px a half-width one.

| Document | Width | median | p90 | p99 | max | over 16.7 ms |
| --- | --- | --- | --- | --- | --- | --- |
| Manual, 80 pp | 1000 | 2.7 ms | 23.4 ms | 61.1 ms | 61.1 ms | 18% |
| Manual, 80 pp | 2000 | 6.0 ms | 43.0 ms | 80.4 ms | 80.4 ms | 28% |
| Handbook, 1590 pp | 1000 | 7.2 ms | 19.1 ms | 88.3 ms | 248.2 ms | 13% |
| Handbook, 1590 pp | 2000 | 11.4 ms | 24.9 ms | 103.9 ms | 247.4 ms | 25% |

Read the median and the tail separately: the distribution is bimodal, so the
mean describes no actual page. Text pages cost 2-11 ms; plates and schematics
cost 40-250 ms, and they are the same pages at every size (Handbook pages
1426, 1328, 1326 and 1489 as the application numbers them).

**Page numbers here are the application's, counting from 1.** The benchmarks
report them that way too, since they did not always: the tool named page 1425,
the app showed plain text at 1425, and the slow page was 1426. A tool whose
output cannot be matched against the window is a trap, and this is the second
time the two conventions have caused confusion -- bookmark targets being the
first.

**The tail does not scale with resolution.** The Handbook's worst page costs
248.2 ms at 1000 px and 247.4 ms at 2000 px -- four times the pixels, no extra
cost -- while the median rises only 1.6x. The expensive pages are bound by
parsing and image decoding, not by rasterising.

Two decisions follow, and the second is the one that would not have been
guessed:

1. **Rendering is asynchronous, and the reader gets its own cache** -- the
   hybrid of the two approaches first considered. A quarter-second stall is
   plainly visible and a quarter of the Handbook's pages miss a frame at 2000
   px, so rendering on the GUI thread is out. But the reader's bitmaps are
   21.2 MB each at that size, and `DEFAULT_CACHE_PIXELS` is 96 MB, so a shared
   cache holds **four reader pages** and evicts every one of the ~575
   thumbnails the grid keeps. Share the thread, the queue and the lifecycle;
   give each consumer its own document provider (file-backed with edit
   geometry for the grid, bytes-backed for the reader's export) and its own
   `ThumbnailCache`. The class already takes `max_pixels`, so per-consumer
   budgets need no new code.

   Size the reader's budget as *a number of pages at the current zoom* --
   `max_pixels = k * current_page_pixels`, recomputed when zoom changes --
   rather than a fixed pixel count. Per-page cost swings by two orders of
   magnitude across the zoom range, so a fixed budget holds forty pages at one
   end and two at the other. The grid keeps a fixed budget, where it is right,
   because thumbnails are all roughly one size.

2. **A placeholder can only be a bitmap that already exists.** The obvious
   design -- render something small and quick, replace it when the real one
   arrives -- does not work here, because for precisely the pages that need a
   placeholder, rendering small costs the same as rendering large. So the
   placeholder is the grid's existing thumbnail scaled up, or the previous
   zoom level's bitmap where there is one, and never a render issued for the
   purpose.

**Prefetch is the only mitigation**, since the slow pages cannot be made fast.
At ~250 ms for a heavy page, current +/- 2 buys about two seconds of lead at
reading pace, which is enough; a fast flick outruns any prefetch, which is
exactly when the placeholders above have to carry it.

**Order of work.** Each step should leave read mode usable:

1. **Canvas with layout and scrolling only** — one column of pages at a fixed
   zoom, painted from bitmaps, with a page-geometry model mapping document
   coordinates to viewport coordinates and back. That mapping is the whole
   foundation: selection, links and destinations are all built on it.
2. **Parity with what `QPdfView` did** — continuous and single-page modes, fit
   page and fit width, zoom in and out with the anchor under the cursor,
   PageUp/PageDown/Home/End, the page selector, and search highlighting through
   the existing `QPdfSearchModel`. Nothing new is visible to the user yet, and
   this is the step that can regress behaviour, so it is where the existing
   reader tests earn their keep.
3. **Link following** — draw nothing, hit-test on click through `linkAt()`,
   navigate for an internal target and hand a URL to the desktop for an external
   one. Cheapest new feature, and it proves the coordinate mapping.
4. **Text selection** — drag to select, paint the selection, copy to clipboard.
   Word and line snapping via `getSelectionAtIndex()`.
5. **Placeholders and prefetch**, once the render source is settled.
6. **Facing pages**, which is a layout change and nothing more by this point.

**What must not regress.** The reader has accumulated behaviour that is easy to
lose in a swap: the event filter that makes PageUp/PageDown work at all (the
wheel arrives at the viewport, not the view), page *labels* rather than indices
in the selector, the stale-snapshot rebuild on entering read mode, and the
separate search model over the reader's own document — pointing one view at the
other's document highlights with the wrong geometry.
## One toolbar per mode, and why the first attempt did not work

Read mode swaps the whole toolbar: **Arrange** carries Undo/Redo, Rotate,
Duplicate and Delete; **Read** carries the page box, Previous/Next Page and the
fit commands. Open, Save and Read Mode are on both, so the way out of a mode
never moves. Only one is visible at a time.

The first attempt kept a single toolbar and hid the editing buttons while
reading. **It silently did nothing.** `QToolBar` drives its buttons' visibility
from the *action*, so `widgetForAction(...).setVisible(False)` is undone at the
next layout; and `QAction.setVisible(False)` — which does stick — takes the
command out of the **menus** as well, which is what the whole exercise was
trying to avoid. What shipped was a toolbar of dead buttons beside a page box
that appeared and vanished: two paradigms at once, which is exactly how it was
reported.

> **`isVisibleTo()` is not "is it visible".** It answers "would this be shown if
> its parent were", so it returns True for a widget that is merely greyed. The
> test written to guard the hiding used it, passed, and asserted nothing. Ask
> `isVisible()` or `isHidden()`; both were confirmed against the running
> application before this was rewritten.

Menus are left greying rather than hiding, which is the usual convention and was
never in question.

> **A command on two toolbars still needs to know which view it is driving.**
> Fit One Page and Fit Width went onto the reader's toolbar while still wired to
> `self.model.zoom`, so in read mode they rescaled thumbnails nobody could see
> and appeared to do nothing. Zoom In/Out and Reset Zoom had the same fault.
> They now dispatch on `self.read_mode`. Fit Multiple Pages is disabled while
> reading instead: `QPdfView.ZoomMode` is `FitInView`, `FitToWidth` or `Custom`,
> with no multi-column layout to fit to.
>
> Two `_zoom_by` definitions had also accumulated in the class, the later
> grid-only one silently winning. Worth grepping for duplicate `def`s after a
> session of patching.
>
> `QPdfView` does not zoom on ctrl+wheel either, and the grid does — the same
> gesture doing nothing in one of two views is worse than not offering it — so
> the reader filters wheel events on its **viewport**, which is where they
> arrive, not on the view.

Adding the page box to the single toolbar had also pushed Delete into the
overflow chevron at 1100 px wide. Neither mode now carries both sets, so it
fits.
