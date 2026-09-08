# Findings

What the libraries actually do, as opposed to what the documentation says — each
one measured, and most of them the hard way. This is the file to read before
assuming a behaviour is incidental, and the file to add to when something turns
out not to work the way anybody expected.

The rule for what belongs here rather than in [DESIGN.md](DESIGN.md): a finding
is *what happens when you try it*; a design record is *what we decided the
application should do*. Where an entry is both, it goes here.

Three standing notes that were once warnings and are now simply true:

> **`hide` is implemented as of phase 0.** `DocumentSet.apply_hide()` turns hidden
> margins into real geometry immediately before export, without touching page
> content: the page *becomes* a full-size blank sheet and its former content is
> laid on top as an overlay, cropped and inset by the hidden amount.
>
> It mutates the pages it is given, so callers must pass duplicates — `_write()`
> does — and `files_for_export()` must be called *after* it, because hiding can
> append a blank document to the set.

> **Both export paths now exist.** `export(preserve_first_document=...)` selects
> between them: False merges bookmarks from every document (`export_doc`), True
> keeps the first document's information via the pikepdf `Job` interface
> (`export_doc_job`, needs pikepdf >= 8). Driven by the Preferences checkbox,
> stored as `QSettings` key `export/preserve-first-document`.

> **Watch the msgids.** `tests/test_i18n.py::TestI18n` fails the build if a menu
> label uses a string absent from `po/de.po` and not explicitly listed as new.
> Rewording a label without checking `po/` silently orphans 33 translations.

## Reordering does not use Qt's item-view drag and drop (D9)

`QListView` in IconMode answers "which item did you drop *onto*"; arranging pages is
entirely about the gaps *between* items, and Qt's drop indicator there is a rectangle
around an item, not an insertion caret. Getting a drop to reach `dropMimeData()` at
all depends on a pile of interacting settings (`movement`, `dragDropMode`, per-index
`ItemIsDropEnabled`) that are opaque to debug — instrumenting the model showed Qt
rejecting drops without ever calling `mimeTypes()`.

So `PageView` tracks the gesture itself: press, drag threshold, insertion caret, edge
auto-scroll, escape to cancel, then `reorder_requested` → `model.move_rows`. External
file drops from Explorer still use ordinary Qt drag and drop, a separate path that
behaves fine. The model advertises no drag/drop flags.

**Consequence:** cross-window page dragging, when it arrives, must be built on this
path rather than inherited from Qt.
## Drops go to the viewport, not the view

`QAbstractScrollArea` routes drag and drop through its **viewport**, and
`setAcceptDrops(True)` on the view does *not* propagate. Without an explicit
`self.viewport().setAcceptDrops(True)`, `PageView`'s drop handlers are never
called at all.

This hid itself for a while: `MainWindow` also accepts drops, so files dragged
from Explorer still imported — they just always appended at the end, because the
window has no idea which page the pointer was over. Both the cross-instance page
drop and drop-at-position for files depend on the viewport flag.
## An escalated drag has to remember it was ours

Escalating the in-window gesture to a `QDrag` is a one-way door unless the drop
handler checks `event.source()`. Dragging a page out of the window and back in
produces a drop carrying page data with no other marker of origin, so it reads as
a foreign paste and duplicates the page. `PageView.handle_page_drop()` takes an
explicit `internal` flag for this, and falls back to copying if the recorded rows
are somehow missing — duplicating is recoverable, losing pages is not.
## Printing is dominated by QPainter.end(), and scales with DPI squared

Measured on a 64-page scanned book to "Microsoft Print to PDF":

```
QPainter.begin (includes the spooler's save dialog): 11.90s   <- the user typing a filename
render and draw 64 pages:                             6.39s   <- ours
QPainter.end (hands the job to the spooler):         29.02s   <- Qt's EndDoc()
```

`end()` is where Qt closes the document and the platform engine processes the
spool data. It is one synchronous, uninterruptible call, so the window shows
"Not Responding" for its duration however good the progress reporting is. The
output file is already complete before it starts, which makes the wait look like
a bug rather than work.

The only real lever is how much data the engine is handed, and that goes as the
square of the render resolution — for those 64 pages:

| DPI | per page | total | measured/expected `end()` |
|----:|---------:|------:|--------------------------:|
| 100 |   0.35 MP |  90 MB | ~7s |
| 150 |   0.79 MP | 202 MB | ~16s |
| 200 |   1.40 MP | 358 MB | 29s (measured) |
| 300 |   3.15 MP | 806 MB | ~65s |

**Adobe Acrobat behaves the same way** on the same document and printer, which
settles it: this is the Windows print pipeline, not something the port is doing
badly. Do not go looking for a bug here. The `print/dpi` preference exists so a
user who wants it faster than Acrobat has a lever; the default of 200 is a
deliberate quality/speed compromise, not an oversight.

Two structural options remain untried, and are only worth taking up if the
"Not Responding" title specifically matters -- neither makes the job faster: running
the job on a worker thread (Qt documents `QPainter` on `QPrinter` as usable off
the GUI thread, but the spooler's native save dialog comes out of `begin()` and
would then be raised from a non-GUI thread), or exporting to a temporary PDF and
handing it to the system print handler, which would send vector data instead of
sixty-four bitmaps.

**Instrumentation lesson:** the first version of this timing gated stdout on an
environment variable read at import, and only wrote its log at the end of the
job. Both are useless for a hang. It now prints every phase immediately, with a
`starting:` breadcrumb before the call that blocks.
## Never change the page layout mid print job

`QPrinter.setPageOrientation()` between pages makes the native Windows engine
reinitialise its device context, and printing to "Microsoft Print to PDF" would
write the output and then never return. `printing.prepare()` now fixes the sheet
orientation *before* `QPainter.begin()`, from whichever way up most pages are,
and pages that do not match are rotated as **images** instead. Same result on
paper, and the engine is never touched once the job starts.

Two related habits, both learned the same way:

- Do not hold a `setOverrideCursor` across printing. Printers like Print-to-PDF
  raise their own modal save dialog part-way through the job; a wait cursor held
  across that nested loop leaves the application looking dead afterwards. A
  `QProgressDialog` keeps events flowing and gives the user a cancel.
- Constructing a `QPrinter` under the offscreen platform raises a harmless
  first-chance COM exception (`REGDB_E_IIDNOTREG`) for want of a print
  subsystem. It changes nothing, but faulthandler prints a stack trace per
  occurrence, so the test helper mutes it around the constructor.
## Colour schemes do not exist under the offscreen platform

`QStyleHints.setColorScheme()` (Qt 6.8+) is what overrides light/dark; "system"
is `unsetColorScheme()`, and Qt follows the OS by itself from there. That is all
"native dark mode is free in Qt" ever meant — the *System* case is free, an
explicit override is one call.

The offscreen platform used by the tests reports `ColorScheme.Unknown` and
ignores the setter. The two tests that assert Qt actually changed therefore used
to *skip* on every ordinary run of the suite -- which meant the two tests that
mattered most here almost never ran, and a swapped light/dark mapping would have
sailed through.

They now assert the part that is ours: `apply(DARK)` asks Qt for
`Qt.ColorScheme.Dark`, `apply(SYSTEM)` calls `unsetColorScheme`. That is
checkable anywhere, against a stand-in for `QStyleHints`. Whether the platform
honours the request is the platform's business, and is still asserted for real
wherever it can be -- the same tests make the stronger assertion when
`color_schemes_supported()`. Zero skips, and swapping `Light` and `Dark` in
`_SCHEMES` now fails them under offscreen, which it did not before.

The same reasoning as the render-timing flake above: when an assertion
depends on something the environment may not provide, assert the call rather
than the consequence. It also closed a hole nobody had noticed -- nothing
verified that "system" *unsets* rather than picking a scheme, so setting Light
and calling it system would have passed every test here.

Verified on real platforms: `QT_QPA_PLATFORM=windows`, where `Light` becomes
`Dark` and the palette's windowText flips `#000000` → `#ffffff`, and
`QT_QPA_PLATFORM=cocoa`.

Page thumbnails deliberately stay white in dark mode: the delegate paints the
sheet explicitly rather than from the palette, because a PDF page is paper.
## `pikepdf.open_metadata()` is not a read-only accessor

It defaults to `set_pikepdf_as_editor=True` and rewrites the Producer on context
exit. Inspection code that opens metadata and then reads `docinfo` will report
*its own* value — this cost real time once, concluding a user's file had been
written by this app when it had not. Pass `set_pikepdf_as_editor=False` for
anything that only wants to look.

`metadata.merge_doc()` keeps the default deliberately: it is upstream code, the
mutation is what carries the pikepdf Producer into the merged output, and
`_set_meta()` compensates via its `ppae` flag. Left alone rather than diverged.
## Mouse-gesture modifiers are sampled late

Ctrl+drag-to-copy cannot read the modifier at the press, because ctrl+press is
already the extended-selection "toggle this item" gesture. `mouseReleaseEvent`
samples it instead, matching how Explorer behaves: start the drag, then hold ctrl
before letting go. `mouseMoveEvent` switches the cursor to `DragCopyCursor` live
so the pending action is visible.
## Cell geometry must be relaid out by hand

Rotating a page changes its delegate size hint. `QListView` resizes *that* cell but
leaves the rest of the row at their old positions, so a page that grew from portrait
to landscape paints straight over its neighbour and both orientations stay on screen.
`dataChanged` is not enough: the view schedules a `doItemsLayout()` — coalesced
through the same timer as the render queue, so rotating a large selection relays out
once — and re-anchors on the top visible row afterwards.

Relatedly, `_visible_range()` hit-tested a single viewport corner, which lands in the
gap between cells depending on scroll offset. A miss silently reported row 0, which
anchored relayouts to the top of the document and made the renderer prefetch from
page 1 no matter how far down the user had scrolled. It now probes a grid of points
and takes the extremes.
## `setScaledClipRect()` cancels `setRotation()`

In Qt 6.11, setting `QPdfDocumentRenderOptions.setScaledClipRect()` makes PDFium
**silently ignore the rotation**: the page comes back upright inside a correctly-sized
sideways frame. `render.py` therefore renders the full page and crops the resulting
`QImage`. There is a regression test (`TestRendering.test_rotation_reaches_the_pixels`)
because the failure is easy to miss — the thumbnail has the right dimensions, just the
wrong pixels.
## Read mode: what QtPdf actually gives you (D14–D16)

Measured against the installed **PySide6 6.11.1**, not inferred from the docs.
`QPdfView`'s entire own API, everything else being inherited from
`QAbstractScrollArea`:

```
setDocument · document/documentChanged
pageMode/setPageMode · PageMode {SinglePage, MultiPage}
zoomMode/setZoomMode · ZoomMode {Custom, FitInView, FitToWidth} · zoomFactor
pageNavigator · pageSpacing · documentMargins
searchModel/setSearchModel · currentSearchResultIndex
```

So continuous scroll, the three zoom modes, page navigation with back/forward
history (`QPdfPageNavigator.jump`), `QPdfBookmarkModel` bound to a `QTreeView`,
and **search highlighting in place** are all wiring.

Three things a first reading of the API promises but does not deliver:

- **No text selection or copy.** `QPdfView` has no `selectAll`, no `copy`, no
  selection property at all. `QPdfDocument.getSelection()` exists, so it can be
  built — drag hit-testing, highlight painting, clipboard — but that is a
  feature, not a connection.
- **No link handling.** `QPdfLinkModel` is in `QtPdf`, but `QPdfView` exposes no
  link property and no clicked signal. Internal links are not followed for you.
- **No facing-page layout.** `PageMode` is `SinglePage` or `MultiPage` only.

> **Read mode cannot share the renderer's `QPdfDocument`.** This is the tempting
> shortcut — one parse, one PDFium instance — and it is wrong here twice over.
>
> First, **the edits are not in that document**. A `Page` in this port is a
> *reference* into an immutable temp copy plus geometry: `angle`, `scale`,
> `crop`, `hide`, `layerpages`. Rotation, cropping, reordering, duplication,
> blank pages, imposition and layer compositing all live in the `Page` list.
> A `QPdfView` on the renderer's document shows the original file — original
> order, no rotations, no crops — silently disagreeing with the grid next to it.
>
> Second, **that document belongs to the render thread**. Handing it to a widget
> on the GUI thread is a data race.
>
> The route is the one `SearchIndex._ensure` already takes: `get_in_memory_pdf()`
> → `MemoryDocument` → `setDocument()`. One export per refresh, which is what
> Find already pays, and it is WYSIWYG by construction.
## Destinations do not survive a copy by themselves

Two defects, both inherited from upstream, both found only because Read mode
put a `QPdfView` in front of a real book — the ARRL 2021 Handbook, itself the
product of a merge that did not fix its cross-file links.

> **Link annotations were never remapped.** `_copy_n_transform` copies each
> page's `/Annots` with the page, but a link's `/Dest` still refers to a page
> *object in the source document*. After the copy that reference resolves to
> null: the array survives with a dead target. Every in-document link in every
> file this application saved did nothing, and PDFium said "skipping link with
> invalid page number -1" once per link. Bookmarks never had the problem
> because `rebuild_outlines` remaps them explicitly; nothing did the same for
> annotations. `remap_link_annotations()` now runs on every export, using the
> same `OutlineRemapper`. A link whose target page was deleted has its
> destination removed rather than left dangling — an inert annotation beats one
> aimed at whatever page took its place.

> **`/GoToR` bookmarks were deleted.** `_get_mapped_dest` recognised only
> `/GoTo`, so any bookmark pointing *outside* the document returned no
> destination, and `_build_valid_tree` prunes items with neither a destination
> nor surviving children. In the ARRL Handbook **18,131 of 18,179 bookmarks are
> `/GoToR`** — links into companion PDFs — so the whole tree below the top level
> vanished, and the 45 top-level entries were left as stubs. "No in-document
> destination" is not "no destination": `/GoToR`, `/URI`, `/Launch` and
> `/GoToE` are kept as they are, since there is nothing of ours to remap.

**Why no existing test caught either.** The fixtures are all well-behaved —
every destination resolves, so nothing is ever dropped and neither failure mode
can appear. `tests/test_export_destinations.py` builds a document to the shape
that broke: a mixed tree of internal and `/GoToR` bookmarks over pages carrying
internal link annotations. Verified to fail 11 of 11 against the unfixed code.

**What is still the document's fault.** The Handbook's `/GoToR` actions name
sibling PDFs that the merge folded in but never repointed, so Acrobat shows the
bookmarks and none of them jump. That is how the file arrived. After these
fixes our re-export reproduces it exactly — same tree, same Qt warning counts —
rather than adding damage or silently deleting the evidence. Repairing such
links would mean recognising that a `/GoToR` target is a file being merged in
the same operation, and is a feature, not a fix.
## Repairing a book that was merged badly

Publishers ship a book as one PDF per chapter, each carrying the **complete**
outline with every other chapter as a `/GoToR` link into a sibling file. The
ARRL 2021 Handbook is 45 files; `3.pdf` alone has 1 local bookmark and 402
remote ones into 44 siblings, 12 of them back to itself. Merge that with a tool
that does not repoint the links — Acrobat and PDF24 both leave them — and you
get a full bookmark tree in which **nothing navigates**, because the files those
links name are no longer beside the result.

Three pieces, all of which the port now has:

1. **Repair on merge.** `external_target()` reads a `/GoToR` action's `/F` and
   integer page number; when that basename is one of the documents in this
   export, `OutlineRemapper.remap_external_destination()` turns it into a real
   `/GoTo` at the page it now shares a document with. It goes through the same
   `page_index_map` as everything else, so it follows reordering and deletion
   rather than assuming concatenation. Opt-in: the caller passes
   `source_names`, which `DocumentSet.source_names()` supplies. A file outside
   the merge is left remote; a page left out of the export is not guessed at.
2. **Collapse the copies.** After repair the N copies of the outline are
   genuinely identical, so `deduplicate_outlines()` keeps the first and drops
   exact matches — same titles, same nesting, same destination pages. It runs
   only when more than one document contributed. A subtree is keyed on its
   descendants (each copy's own root points at its own file's first page, so the
   roots differ); a lone bookmark is keyed on title and target.
3. **Repair a merge someone else did.** `tools/repair_merged_links.py` recovers
   where each original landed from the merged file's own top-level bookmarks —
   merge tools name one per input file — and checks the result really is a plain
   concatenation before touching anything. On the Handbook: 45 of 45 files
   located, layout check clean, **18,089 links repaired**, 42 left remote because
   they name files outside the folder. It never writes in place.

> **Do not mutate an outline through `pdf.open_outline()`.** The context manager
> rebuilds the outline from its own `OutlineItem` objects when it exits, which
> discards edits made to the underlying dictionaries. The first version of the
> repair tool reported 18,089 repairs and changed absolutely nothing — the
> before-and-after check is the only reason that was caught. Walk `/Outlines`
> by `/First` and `/Next` instead, with a visited set: a malformed `/Next` chain
> will otherwise loop forever.

> **Qt reads a `/GoToR` page number as a local page.** The `/D` array's first
> element is an index into the *remote* file, but `QPdfBookmarkModel` treats it
> as a page of the current document — so unrepaired remote bookmarks appear to
> work and land on the wrong page, and every chapter's "section 1" collapses
> onto the same one. Acrobat is the one behaving correctly by refusing to jump.
> This is why the reader looked more broken than the file it was showing.
## Read mode goes blank when you scroll fast, and cannot be tuned

> **Superseded by phase 7 step 2.** This section is why the reader's view was
> replaced: every limitation in it is `QPdfView`'s, not the engine's. The canvas
> renders on the GUI thread today, so fast scrolling stutters rather than blanks,
> and step 5 answers it properly with prefetch and placeholders sized as a number
> of pages at the current zoom. Kept as the record of what forced the decision.

`QPdfView` renders each page on demand, at full display resolution, and draws
**nothing** until that render arrives. Measured on the ARRL Handbook — 1590
dense pages — at a reader-sized 900 to 1200 pixels wide:

| width | per page | pages/second |
| --- | --- | --- |
| 900 px | ~48 ms | ~21 |
| 1200 px | ~58 ms | ~17 |

Flick through a long document faster than that and you outrun it, so pages are
blank until you stop. It is worst exactly where a reader is most useful: a big
book, where nothing you scroll to is still cached.

**Not a misconfiguration.** The view's private `QPdfPageRenderer` is reachable
with `findChild` and is already `MultiThreaded`. And `QPdfView` exposes nothing
to tune — its entire own API is `setDocument`, `pageMode`, `zoomMode`,
`zoomFactor`, `pageNavigator`, `pageSpacing`, `documentMargins`, `searchModel`
and `currentSearchResultIndex`. No cache size, no prefetch, no render quality.

Acrobat stays continuous because it renders progressively (coarse first, then
sharp), keeps a cache measured in megabytes, and renders tiles at the visible
resolution. Qt does none of the three.

> **Superseded by phase 7 step 2.** The page keys are `PageCanvas`'s own
> handlers now, so the event filter described below is gone; the behaviour it
> describes is what the canvas implements deliberately, rather than a
> workaround bolted onto someone else's widget. What follows was true of
> `QPdfView`:
>
> **`QPdfView` scrolls; it does not turn pages.** PageUp and PageDown move its
> scrollbar, which happens to change page in a continuous view and does
> *nothing at all* in `SinglePage` mode — so the toggle above shipped, briefly,
> switching to a mode with no way to move through it. Home and End were
> unhandled in both modes. `ReaderView` filters the view's key events and
> navigates through `QPdfPageNavigator` instead, and the same commands are in
> the View menu. Their menu shortcuts are `Ctrl+PageUp`/`Ctrl+PageDown`, not the
> bare keys: those belong to whichever view has focus — the grid moves the
> selection with them — and a window-wide shortcut would take them from both.

> **Changing `pageMode` loses your place.** The layout is relaunched and the
> scrollbar lands near the top, while `QPdfPageNavigator` goes on reporting the
> page you were on — so the view shows the start of the document and nothing in
> the interface admits it moved. `set_continuous()` remembers the page and goes
> back to it. `jump()` to the page the navigator already believes it is on is a
> no-op, so it has to be nudged off and back.

**What was done:** **View ▸ Continuous Scroll**, on by default. Turning it off
puts `QPdfView` in `SinglePage` mode, which renders one page at a time, so
paging through with PageUp/PageDown stays sharp. It is a real command rather
than a preference because it is the workaround for a rendering limit, not a
matter of taste.

**What was not, and why.** The tempting fix is to paint an upscaled thumbnail
as a placeholder where the real render has not landed — Acrobat's perceptual
trick, and the grid's `Renderer` already holds a bitmap of every page. It needs
`paintEvent` overridden and the page rectangles computed by hand from
`pagePointSize`, `zoomFactor`, `pageSpacing` and `documentMargins`, because
`QPdfView` will not say where a page is. That means reimplementing Qt's page
layout and keeping it in step across upgrades — the same shape of bet as
`setScaledClipRect` and the `QMenu` ownership traps above, both of which broke
quietly. Left as a phase 7 item.
## Entering read mode costs more than reading does

Measured on the ARRL Handbook, 1590 pages, 255 MB on disk, with
`tools/bench_export.py`:

| Step | Time | Peak RSS |
| --- | --- | --- |
| `add_file`, including the working copy | 846 ms | 451 MB |
| `get_in_memory_pdf(outlines=False)` | 2938 ms | 1287 MB |
| `get_in_memory_pdf(outlines=True)` -- what read mode calls | **3572 ms** | **1724 MB** |
| `MemoryDocument` (QByteArray + PDFium parse) | 63 ms | +0 |

**3.6 seconds and 1.7 GB to open the reader**, against 247 ms for the slowest
single page render. Roughly seven times the file's size resident, and fourteen
times the cost of the thing the render benchmarks were about.

The cost is the export, not the document. `MemoryDocument` is 63 ms because
PDFium parses lazily, so the reader's `QPdfDocument` is nearly free; producing
the 254 MB of bytes it reads is not. Outline remapping is 634 ms of the total --
real, as `get_in_memory_pdf`'s docstring warns, but only 22%. The remaining 2.9 s
is spent writing out a document that already exists on disk, unchanged.

**This is current behaviour, not a property of the planned view.** Read mode does
it today. And the refresh policy recorded in [DECISIONS.md](DECISIONS.md) has an edit made *while*
reading rebuild immediately rather than lazily, so on a document this size that
is a 3.6 second freeze on the GUI thread, mid-read.

**The fast path, proposed.** D15 exports because the edits do not live in the
reader's `QPdfDocument`. When there are no edits, there is nothing to apply: a
page list that is one source file, in order, with no rotation, crop, hide, scale,
layers or inserted blanks is 1:1 with the file on disk, and the reader could open
that file directly for the price of the 63 ms parse.

That is not an edge case. It is D14's stated reason for having a reader at all --
*reading is why the document was opened* -- so someone who opens a book to read it
currently pays the whole 3.6 s and 1.7 GB for a transformation that changes
nothing.

**Note what the question is not.** It is tempting to ask how to tell, at open
time, whether a file is being opened to read or to arrange. That guess is not
needed and could not be made reliably: the choice belongs at *entry to read
mode*, where it is a property of the current page list rather than an intention.
Unmodified takes the source; anything else exports as it does now. It also
degrades correctly on its own -- make one edit and the next entry falls back to
the export, with no state to track.

**Still open.** Two things, if the fast path is taken:

- The edited case keeps the 3.6 s, and the first edit gives up the fast path for
  the rest of the session. Moving the export off the GUI thread, with the reader
  holding the previous document until the new one is ready, is the general fix
  and a larger change: it makes the reader's document asynchronous.
- Verify that search, bookmarks and page numbering line up when the reader holds
  the source rather than an export. They should, an unmodified list being 1:1,
  but *Read mode* above warns specifically about pointing a view at another
  document's geometry, and that warning is the reason to check rather than
  assume.

Worth its own decision entry when picked up: the fast path changes what the
reader is looking at, which D15 deliberately settled the other way.
## Most of a document's links are not in the document

Found while testing phase 7 step 3 against the Handbook, and worth knowing
before anyone reports a link as broken.

**PDFium invents links.** The ARRL Handbook carries 1009 real `/Link`
annotations, but on only **34 of its 1590 pages**. Every link on the other
1556 pages -- including all of the ones on the Resources pages that started this
-- has no annotation behind it at all: PDFium scans the page text for URL-shaped
strings and synthesises a link. Acrobat does the same thing, with its own
matcher. So two viewers can disagree about whether a piece of text is a link,
and both are right about their own inference.

This is why the same page can hold a link that works beside one that does not:

| text on the page | PDFium | Acrobat | why |
| --- | --- | --- | --- |
| `www.omikradio.org` | link | link | prefixed, on one line |
| `handiham.org` | plain | plain | no `www.` or `http`, so neither matcher fires |
| `www.arrl.org/part-97-amateur-radio` | plain | link | wrapped after `www.`; PDFium only rejoins a break that follows a **hyphen** |

**The matcher, read rather than guessed.** PDFium is BSD-3 and open, so the rule
is `CPDF_LinkExtract::ExtractLinks` in `core/fpdftext/cpdf_linkextract.cpp` --
*fpdftext*, not fpdfdoc, which is the whole finding stated in the engine's own
structure: this is text scanning, and `fpdfdoc` is where the real annotations
live. What it does:

- Two web prefixes only, `http` and `www.` (`kHttpScheme`, `kWWWAddrStart`), and
  a bare `www.` match gets `http://` prepended -- which is why a page reading
  `www.omikradio.org` yields a link whose URL is `http://www.omikradio.org`.
  Nothing without one of those prefixes is ever a link, so `handiham.org` cannot
  be one in any PDFium-based viewer.
- **A line break is only stitched across when it follows a hyphen.** The
  candidate is closed at any break unless `bAfterHyphen` is set, and only then
  are `\n` and `\r` removed and scanning continued. The Handbook wraps after
  `www.` -- a full stop, not a hyphen -- so the break ends the candidate, `www.`
  alone reaches `CheckWebLink`, and is rejected. Acrobat rejoins regardless of
  what precedes the break. Neither is wrong; they are different heuristics.
- Trailing `)`, `,`, `>` and `.` are stripped before matching, so a
  sentence-ending `arrl.org.` does not swallow the full stop.
- Its own comment: *"Ftp address, file system links, data, blob etc. are not
  checked."* PDFium never synthesises `ftp://`, `file://` or `data:`. So
  `ReaderView.SAFE_SCHEMES` is belt-and-braces for inferred links -- but not for
  the 1009 real annotations, which may carry any scheme at all, and are the
  reason the allow list exists.

`cpdf_linkextract_unittest.cpp` sits beside it and enumerates the accepted
shapes, if the exact boundaries ever matter more than they do here.

**Chrome behaves identically, because it is the same engine.** Chrome's PDF
viewer is PDFium, so a wrapped URL is not a link there either, and the same
report exists against Chrome upstream. The recommendation there is to fix the
PDF -- that is, to add real `/Link` annotations -- which is the correct answer
and confirms this is engine behaviour rather than anything to work around in a
viewer.

None of it is ours to fix and none of it is the document's fault either -- the
author never marked these up. Writing a better matcher is possible and is a
different feature: it would have to rejoin wrapped lines without linkifying a
section number like `1.21` or a sentence-ending `arrl.org.`, and it would still
disagree with somebody. The honest answer to "why is this not a link" is that no
one ever said it was one, and the fix that actually works is on the document
side: annotate it, and every viewer agrees.

**A synthesised link has no page, and `isValid()` says so.** `QPdfLink.isValid()`
requires a page, and a link to somewhere outside the document has `page() == -1`.
So every external link -- every one of these inferred ones included -- reports
`isValid() == False` while carrying a perfectly good rectangle and URL. Using it
as the "is this a real link?" filter silently drops all of them: the Handbook
hit-tested 45 of 68 links, and the 23 missing were exactly the external ones. Use
"has a URL, or has a page" instead; `PageCanvas.usable_link` is that, and
`tests/text_and_link.pdf` exists because every other link fixture in the suite is
internal and none of them could have caught it.

**And a destination can be NaN.** QtPdf logs `invalid location and/or zoom` and
hands back what it parsed; the Handbook's bookmarks produce `nan nan nan`. NaN
compares false against everything including zero, so it slips past a check for
the default (0, 0) and only fails later, inside `int(round(...))`, which raises
`ValueError` and kills the click that reached it.
## Why Acrobat is smoother, and what we did about it

David flung a freshly opened Handbook from page 1 to page 1590 in Acrobat and
every page he crossed was drawn. Ours blank and fill. Worth knowing why, because
the obvious explanations are all wrong.

**It is not a cache.** 1590 pages at 5.1 ms median is eight seconds of
rendering; the fling took a second. Acrobat did not render those pages.

**It is not embedded thumbnails.** A PDF may carry a `/Thumb` per page, and
Acrobat writes them. This document has **0 of 1590**.

**It is not scaled JPEG decoding**, which was the best remaining theory --
libjpeg decodes at 1/8 scale cheaply, so a proxy could be nearly free. The
expensive pages are not JPEG-bound. App page 1426 carries 6933 image XObjects of
which **6932 are one pixel tall**: a figure's gradient background drawn as
thousands of slivers, so the cost is per-object overhead. App page 1328 is the
other shape, 10.6 Mpx of Flate, which has no scaled-decode path at all. Neither
shrinks with output size, which is exactly the flat curve measured above.

**It is progressive rendering with a deadline** -- draw what completes, abandon
the rest, so a slow page looks nearly finished rather than blank. PDFium
supports it through `FPDF_RenderPageBitmap_Start`/`_Continue`; **QtPdf exposes
only an atomic render**. Measured with pypdfium2 at 1000 px and a 16 ms budget:

| app page | shape | atomic | first slice | what you would see |
| --- | --- | --- | --- | --- |
| 1426 | 6932 one-pixel slivers | 140 ms | **16 ms** | a complete, readable page |
| 1328 | 10.6 Mpx Flate image | 233 ms | **93 ms** | **blank** |
| 1326 | as above | 145 ms | 103 ms | blank |
| ordinary text | | 2-5 ms | one slice | complete anyway |

So it rescues one failure mode and not the other: PDFium checks the pause
callback between drawing operations, and a single large image decode is one
operation. Not enough to justify a second copy of PDFium in the bundle, 7.1 MB,
and a version that can drift from Qt's -- so D8 stands. Acrobat is evidently
doing more than this with its own decoder.

**What was done instead**, both cheap:

- **A proxy tier.** Every page rendered keeps a 120 px copy, in its own store
  rather than the full-size cache -- 75 KB a page against 21 MB, so the whole
  Handbook is 116 MB against 21 MB for a *single* page at 2000 px. It does not
  help a first fling over pages never seen; it means a page read once never
  blanks again, which is what most reading actually does. Measured: reading
  forward through fourteen pages and scrolling back over them gives **zero**
  blanks, where every one of them used to re-render.
- **Queue priority.** The queue drains from the front and a repeat request used
  to move a key to the *back*, so asking again for the page under the reader's
  eyes demoted it behind everything queued since. Visible pages are now urgent
  and jump; proxies never are. This is also what would stop a background pass
  starving the foreground, if one is ever added.

Two bugs found while wiring that up: proxies first shared the full-size cache
and evicted the very pages they were meant to stand in for, and the reader's
cache was constructed with a budget of *one pixel* on the theory that the first
paint would size it -- which left every render before that paint evicted the
instant it arrived.
## Drawing text onto a page, and why not by hand

`stamp.py` needs one thing PDF Arranger has never needed: text that is not
already in a document. Page numbers and watermarks are the same operation with
a different `Style`, so the question was only how to draw a string.

The obvious answer is to write the content stream directly — `BT /F1 12 Tf ...
Tj ET` against one of the base-14 fonts, which need no embedding. It looks like
the smaller dependency right up until the text has to be *placed*: centring a
string needs its width, which needs font metrics, which means shipping an AFM
widths table and maintaining it. And the base-14 encodings are Latin-1, so a
document numbered in Greek or Japanese comes out as mojibake — from an
application whose 33 translation catalogues are the reason D2 exists.

**QPdfWriter** has the metrics and the font already, embeds a subset of whatever
it used, and takes Unicode. Resolution is pinned to 72 dpi so one Qt logical
unit is one PDF point and nothing anywhere converts units. Verified: the output
carries a real `/Type0` font and `QPdfDocument.getAllText()` reads
"Page 1 of 2" back out — the numbers are selectable and searchable text, not
outlines and not an image.

Two things found while building it, both worth knowing:

- `QFont("Helvetica")` **is not Helvetica on Windows** — Qt resolves it to
  Tahoma. `Style.qfont()` sets a family *list* instead, so the classic name is
  tried first and each platform's real sans follows.
- The **offscreen platform has no fonts at all**: `QFontDatabase.families()` is
  empty, and every string draws as the box a missing glyph produces. That is
  the whole test suite's platform. The boxes land where the glyphs would, so
  position is still measurable, but "is this real text" is not — so
  `stamp.has_fonts()` gates the two tests that ask, and they run on any machine
  with fonts. A suite that silently proved less than it looked like it proved
  would have been the worse outcome.

One more trap, caught by a test rather than by reading: `QComboBox.addItem`
round-trips its item data through `QVariant`, so a tuple stored with `addItem`
does not come back equal to a tuple passed to `findData`. The N-up preset combo
stores `"2x2"` strings for that reason.
## A composited page drew as an empty page in the grid

Reported against Pages per Sheet: the sheets it produced were blank in the
thumbnail grid and correct in read mode.

The render task carried plain values copied off the `Page` -- source file, page
number, angle, crop, hide, width -- and nothing about `layerpages`. For most
pages that is invisible, because the base page holds the content and only an
overlay would be missing. For a page whose base is a *generated blank sheet*
the content is entirely in the layers, so there was nothing left to draw. Read
mode was right because it goes through the exporter (D15), which composites.

Pre-existing, and older than the feature that exposed it: booklet imposition
has produced layer-only sheets since phase 2, and Page Size ▸ Scale & Add
Margins does too. Pages per Sheet only made it unmissable, because *every*
sheet it produces is blank-based.

The fix does not paint the layers in the renderer. A layer stack carries an
offset, a crop and a rescaling for every nested layer, and that arithmetic is
already written once in `layers.py` and `export.py` -- writing it a second time
in the render worker would be a second thing to get wrong, and the two could
then disagree about what the page looks like. Instead a page *with* layers is
exported to memory as a single page and that is rendered, which is exactly what
read mode does. Pages without layers keep the direct path untouched, so the
common case pays nothing.

Two things had to move with it:

- `Page.render_key` now includes the layer stack. Without that the cache
  answers a stamped page with the bitmap it had before the stamp -- the same
  class of bug, one layer further along. The signature is built from plain
  hashable fields rather than `LayerPage.serialize()`, because the key is
  rebuilt on every paint of every visible cell: measured at 0.83 µs for a
  four-layer page, against 0.3 µs for a page with none.
- The model needed the `(copyname, password)` list to hand the exporter, so it
  gained a `doc_files` hook beside `doc_password`. It is asked for once per
  batch, and only when a page in that batch actually has layers.
## Compressing turned a damaged file into an unreadable one

Found while testing the PDF24-comparison save options, on the project's own
`test.pdf`.

The "preserve first document" save (`export_doc_job`) preserves the first
document's *faults* along with everything else. `tests/test.pdf` is hand-written
and ends `xref
trailer << /Root 1 0 R >>
startxref
0` — no `/Size`, and a
stub cross-reference table. qpdf reconstructs on the way in, warns, and carries
the trailer out as it found it.

With a plain cross-reference table that only made the output untidy: every
reader reconstructs, which is why nothing had ever noticed. Turning on
**Compress** switches the output to a cross-reference *stream*, and a stream
whose `/Size` is missing cannot be reconstructed from at all — pikepdf's own
message is `unable to find /Root dictionary`. A damaged input plus one checkbox
produced a file nothing would open.

`_ensure_trailer_size()` puts the key back before the write. qpdf renumbers
objects contiguously from 1 as it writes, which is what makes the object count
the right answer. It runs on every job-path save, not only when compressing:
the trailer was wrong either way.

Worth stating plainly because the obvious reading is that Compress broke it. It
did not — it removed the slack that had been hiding a pre-existing bug. Measured
before and after with `pikepdf.open(..., attempt_recovery=False)`, which is the
same trick `repair.py` is built on.
## A note on content streams

Scaling and overlay *do* synthesize a content stream — they wrap the page as a Form
XObject (`q s 0 0 s 0 0 cm /pN Do Q`). That wraps the page whole; it never parses or
rewrites what is inside it, so no glyph or font work is involved. Firmly Tier 1.

---
