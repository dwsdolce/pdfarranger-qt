# PDF Arranger → PySide6 Port

Project document: goal, decisions, menu design, progress tracker, and implementation
notes. Started 2026-08-06.

- **Run:** `python -m pdfarranger_qt [files...]`
- **Test:** `pytest tests`
- **Code:** `pdfarranger_qt/` — the whole application. The GTK `pdfarranger/`
  package was removed in phase 5; `git log` has it if it is ever needed again.
- **Translations:** `python tools/build_mo.py` before running, to compile `po/`

---

## 1. Goal

Port PDF Arranger to PySide6/Qt for a friendlier, more native-feeling UI on Windows.
The GTK interface is functional but dated and alien on Windows, and the interaction
model has room to improve.

**Background.** The starting point was dissatisfaction with **PDF24 Toolbox**: a
collection of disjoint tools, each requiring its own load → transform → save round
trip. The desired model is Acrobat-like — open a document, make many changes against
an in-memory model with undo, write to disk only on save. PDF Arranger already
implements roughly that model and is the closest free thing to it, which is why it
became the port target rather than a from-scratch build.

**Licensing.** PDF Arranger is GPL-3. A port is a derivative work, so this stays
GPL-3. Considered and accepted. Retain upstream copyright notices, keep `COPYING`,
credit the original project.

### Scope boundary

- **Tier 1 — page-level ops** (reorder, rotate, delete, insert, extract, split,
  merge, crop, images → PDF, imposition). Tractable. **This is the whole project.**
- **Tier 2 — content-level editing** (retype text, move graphics, reflow). PDF has
  no concept of paragraphs or text flow, only glyphs at coordinates with subset
  fonts. **Out of scope.** Use PDF-XChange Editor or Acrobat for the rare cases.

Everything still unported is Tier 1. Nothing remaining requires content editing.

### Beyond parity — the reason for the port

- Async thumbnail rendering with caching (PDF Arranger bogs down on large documents) — **done**
- Real multi-select: rubber-band, shift-range, ctrl-toggle, ops across selection — **done**
- Native drag-and-drop from Explorer, including images — **done**
- Native dark mode — **free in Qt**
- Split view: thumbnail grid alongside a full-page preview of the selection — *todo*
- Dual-pane merging: two documents side by side, drag pages across — *todo*
- Visible undo history rather than blind Ctrl-Z — *todo*

---

## 2. Decisions

Settled decisions and why. Anything not here is still open.

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Package name | **`pdfarranger_qt`**, permanently | Locked so the `QSettings` scope never has to move. Renaming later would silently orphan saved window geometry and zoom. |
| D2 | i18n | **Keep gettext, reuse `po/`. Wrap strings in `_()` as they are written.** | 33 catalogues at ~239 msgids each. Nothing forces a PySide6 app onto Qt's `tr()`/`.ts`; Python `gettext` works fine in a Qt app, so unchanged strings carry straight over. Wrapping as we go is nearly free; retrofitting across 25 actions and a dozen dialogs is not. |
| D3 | Menu structure | **Settle the full mapping before building dialogs** — see §3 | 25 more actions are coming. Deciding placement once beats reshuffling a menubar twelve times. |
| D4 | Settings store | **`QSettings`**, everything exposed in the UI | The old `config.ini` held window geometry, print settings and accelerators; Qt has native mechanisms for all three. Carrying the format forward would mean carrying `Gtk.accelerator_parse` with it. Consequence: no ini file to point users at, so Preferences must expose every setting — including shortcuts (D11). |
| D5 | Clipboard format | **Keep upstream's serialisation byte-for-byte** | Free, and lets the Qt and GTK versions interoperate via copy/paste during the transition. Constrains `Page.serialize()`, which is already ported. |
| D6 | Packaging / installer | **Defer until GTK is gone** | A Qt PyInstaller spec is a different beast from the GTK one; maintaining both in parallel while things churn is wasted effort. Run from the venv meanwhile. |
| D7 | Booklets | **In scope** — both generate and split | Cheaper than first assessed: built entirely from blank pages, overlay layers and `Page.split()`, all of which are already ported or already planned. Neither needs a dialog. |
| D8 | Rendering backend | **`QPdfDocument` (PDFium)** replaces poppler-glib + cairo | Wholesale replacement, not a translation. Confirmed the old path was `Poppler.Document.new_from_file` → `cairo.ImageSurface`. |
| D9 | Reordering | **Hand-rolled drag in `PageView`**, not Qt item-view DnD | See §6. Qt's IconMode DnD answers "dropped onto which item"; page arranging is about the gaps between items. |
| D10 | CLI surface | **Match upstream exactly**: `[files...]` and `--version` | Already implemented. The man page says "PDF Arranger doesn't receive any options"; nothing more is expected. |
| D11 | Customisable shortcuts | **Yes — a shortcut editor in Preferences** | Upstream supports them but only via hand-editing `config.ini`, documented nowhere in the app or man page (see §8). D4 removed the ini, so the capability has to move into the UI. |
| D12 | Phase 4 (split view, dual-pane, undo history) | **Deprioritised — last, and optional** | Not important to the user; they can live without them. This removes the sequencing risk that made D3 urgent: parity work can proceed without fear of reworking the window later. |
| D13 | Application name and project identity | **"PDF Arranger Qt"**; distribution `pdfarranger-qt`; **new standalone repository keeping the full git history**, with upstream added as a read-only `upstream` remote — not a GitHub fork | A distinct name avoids passing this off as upstream's application, and had to be settled *before* anyone else runs it because D1 locked the `QSettings` scope. That scope is deliberately **left as `("pdfarranger", "pdfarranger_qt")`** despite the rename: moving it is exactly the orphaning D1 exists to prevent. Not a fork because GitHub disables code search in forks, the "forked from" banner would misrepresent a Qt rewrite of a deleted GTK app, and there is nothing to contribute back. History is kept because this is a real derivative work — `exporter_outlines.py` verbatim, geometry and pikepdf logic verbatim, 33 translation catalogues, upstream artwork — and the history is the provenance record behind those attribution claims. |

### Still open

Repository housekeeping, once the new remote exists:

- `git remote rename origin upstream` — `origin` still points at
  `pdfarranger/pdfarranger` **for push as well as fetch**
- `git remote set-url --push upstream DISABLED`, then add the real `origin`
- Fix the `Homepage` placeholder in `pyproject.toml`

Otherwise nothing blocking. Remaining judgement calls are noted inline in the tracker.

### Notes on D11

Upstream's accelerator model, for reference when building the editor:

- 37 default bindings in `_DEFAULT_ACCELS` (`config.py`), written into the
  `[accelerators]` section of `config.ini` on every start **unless**
  `enable_custom = true`, which is what makes user edits stick.
- GTK syntax (`<Primary>s`, `<Shift>F10`, `Delete`) does **not** carry over —
  `QKeySequence` wants `Ctrl+S`. Existing user customisations will not migrate.
  Acceptable: the feature is undiscoverable enough that few will have any.
- Several actions bind **multiple alternatives**, e.g.
  `zoom-in = plus KP_Add <Primary>plus <Primary>KP_Add`. Maps cleanly onto
  `QAction.setShortcuts([...])`.
- Bindings exist for parameterised actions — `rotate(90)`, `paste(4)`,
  `select(1)`, `zoom-fit(0)` — so the editor keys off the concrete command, not
  the bare action name.

---

## 3. Menu map (D3)

Upstream uses a hamburger popover. This port uses a real menubar. `*` marks
not-yet-implemented.

**File** — New · Open… · Import… ‖ Save · Save As… ‖ Export ▸ (Selection to Single
File · Selection to Individual Files · All Pages to Individual Files · Selection to
PNG · Selection to JPEG · Selection to Rasterised PDF) ‖ Print… ‖
Properties… ‖ Close · Quit

Upstream's seven export modes are `ALL_TO_SINGLE`, `ALL_TO_MULTIPLE`,
`SELECTED_TO_MULTIPLE`, `SELECTED_TO_PNG`, `SELECTED_TO_JPG`,
`SELECTED_TO_PDF_PNG`, `SELECTED_TO_PDF_JPG`. The last two rasterise pages and wrap
them back into a PDF — a distinct output, not the same as image export.

**Edit** — Undo · Redo ‖ Cut · Copy · Paste After ▸ Paste Special (Before · As Odd
Pages · As Even Pages · As Overlay · As Underlay) ‖ Select ▸ (All · Deselect All ·
Invert · Odd · Even · Same File · Same Format · Range…) ‖ Find… · Find Next ·
Find Previous · Find All ‖ Preferences

**Page** — Rotate Left · Rotate Right ‖ Crop Margins… · Hide Margins… · Crop White
Borders ‖ Page Size… ‖ Duplicate · Delete · Insert Blank Page… ‖
Extract ▸ (Copy Text · Copy Image) · Explode into Images

**Arrange** — Reverse Order · Swap Odd/Even ‖ Split Pages… · Merge Pages… ‖
Booklet ▸ (Split (unimposition) · Generate (imposition))

**View** — Zoom In · Zoom Out · Zoom Fit · Reset Zoom ‖ Show Page Numbers\* ·
Preview Pane\* ‖ Fullscreen

**Help** — User Guide ‖ About

**Arrange** is a new top-level menu with no upstream equivalent. It separates
operations *on a page* (Page) from operations *on document order and composition*
(Arrange), which is the distinction the app's own name turns on.

---

## 4. Progress tracker

Legend: `[x]` done and tested · `[~]` partially done · `[ ]` not started

### Phase 0 — shared plumbing — **complete**

- [x] `export.get_in_memory_pdf()` + `render.MemoryDocument` — render the *edited*
      document to memory and open it as a `QPdfDocument`. Unblocks white-borders,
      explode-images, crop preview
- [x] `DocumentSet.get_blank_doc()` / `core.create_blank_page()`, with reuse so
      hiding fifty same-sized pages makes one blank file, not fifty
- [x] **`hide` at export time** — `DocumentSet.apply_hide()`; the §7 warning is resolved
- [x] `export_doc_job()` — the pikepdf `Job` path, selected by
      `export(preserve_first_document=True)`
- [x] gettext scaffolding (`i18n.py`) + all existing strings wrapped (D2)

### Phase 1 — model-only actions (no dialogs) — **complete**

- [x] Cut · Copy · Paste · Paste Before · Paste As Odd/Even (interleave), on
      upstream's clipboard format (D5) so both versions interoperate
- [x] Export Selection / All Pages to Individual Files
- [x] Reverse Order · Swap Odd/Even (both require a contiguous selection)
- [x] Select: Odd · Even · Same File · Same Format · Deselect All
- [x] Zoom to Fit · Fullscreen
- [x] Mouse gestures (§8), all of them: Shift+scroll horizontal, Alt+scroll one
      row, double-click toggles zoom-fit, scroll-while-dragging extends the band
- [x] Split Booklet (unimposition)
- [x] **Drag pages between instances** — the hand-rolled gesture (D9) owns the
      drag inside the viewport, drawing the insertion caret; when the pointer
      leaves, it escalates to a real `QDrag` carrying upstream's
      `MODEL_ROW_EXTERN` payload (the clipboard records without marker or hash).
      Dropping accepts that format alongside file URLs. What the drop *does*
      depends on where it came from and whether ctrl is held:

      | Drop | Result |
      |------|--------|
      | inside the window | move |
      | inside the window, ctrl held | copy |
      | left the window and came back | move |
      | left and came back, ctrl held | copy |
      | from another instance | copy — ctrl makes no difference |

      A drop from another instance never removes anything from the sender,
      matching upstream, which likewise does not delete on an external drag.

      The returning-drag case needs care: once escalated, a drag coming home is
      indistinguishable from a foreign one, so `dropEvent` compares
      `event.source()` with the view. Without that check it reads as a foreign
      paste and silently duplicates the page.

      Ctrl is read at the *drop*, never at the press: ctrl+press means "toggle
      this item" to an extended-selection view, so requiring it from the start
      would fight the selection model.

      Qt↔Qt works. **GTK↔Qt is still unverified**: drag targets are named
      formats both toolkits must agree on at the Windows level, unlike the
      plain-text clipboard.
- [x] Scroll-while-dragging extends the rubber-band selection. Qt moves the band
      with the content by itself, but only recomputes the selection on the next
      mouse move, so scrolling with the pointer held left it stale until you
      jiggled the mouse; `_extend_rubber_band_after_scroll()` replays a move at
      the last known position to settle it immediately.
- [x] **Interleave validated against a real duplex scan.** A 64-page, 12 MB
      music book was rebuilt from its two halves and came out *bit-for-bit
      identical* to the reference the user had produced with pypdf — same
      rotations, same image hashes, no JPEG re-encoding.

      The workflow that real scanner output needs: open the fronts, load the
      backs, **Reverse Order** on the backs, then Paste As Even Pages. The
      backs come off a duplex feeder in reverse (64, 62, … 2), so interleaving
      them straight yields a structurally valid but content-wrong book. Worth
      remembering when the crop/hide UI lands: the reverse step is easy to
      forget and the result looks plausible.

**Moved out of phase 1:**

- **Generate Booklet → phase 2.** Imposition composes pages as layers, which
  needs the same nested-layer helper (`paste_as_layer`) as Merge Pages. Building
  it once, with Merge, beats half-implementing it twice.
- **Extract → phase 3.** Not "extract pages to a file" as assumed: upstream's
  `extract` copies the *image or text content* of a page to the clipboard, so it
  needs image extraction and a text layer. Paste As Overlay/Underlay moved too —
  both need the layer-offset dialog.

### Phase 2 — dialogs over already-ported backends — **complete**

- [x] **`layers.paste_as_layer()`** — the keystone. Compositing a page onto a
      page, including re-cropping and re-offsetting any layers the pasted page
      already carried. Merge, Paste As Overlay/Underlay, booklet imposition and
      two of the three Page Size modes are all this one call with different
      offsets.
- [x] Crop Margins… and Hide Margins…
- [x] Page Size… — all three modes (Scale, Scale & Add margins, Crop & Add
      margins); the margin modes go through `layers.center_on_blank_pages()`
- [x] Split Pages… (grid of tiles)
- [x] Merge Pages… and Paste As Overlay/Underlay
- [x] **Generate Booklet** (imposition), which fell straight out of the layer helper
- [x] Insert Blank Page… · Select Range…
- [x] Edit Properties… — XMP metadata, round-tripped through
      `metadata._metatostr`/`_strtometa` and written on save

### Phase 3 — render-dependent features and Preferences — **complete**

Everything here works off `export.get_in_memory_pdf()` + `render.MemoryDocument`
from phase 0, so what is searched, printed, trimmed or exported is the *edited*
document -- crops, rotations and layers already applied -- not the source file.

- [x] Find · Find Next · Find Previous · Find All (`search.py`)
- [x] Crop White Borders (`raster.white_border_crops`)
- [x] Image export to PNG/JPEG, with the ppi and greyscale preferences
- [x] Rasterised-PDF export (flattens text to pixels, verified by round trip)
- [x] Extract ▸ Copy Text · Copy Image · Explode into Images (`raster`, via pikepdf)
- [x] Print (`printing.py`, `QPrinter`) — covered by tests: a `QPrinter` set to
      `PdfFormat` with an output file needs neither dialog nor spooler
- [x] Theme (`theme.py`) — light/dark/system, applied at startup and immediately
      when Preferences changes
- [x] Preferences — Language · Theme · Printing (incl. DPI) · Saving/exporting ·
      Image Export · **shortcut editor** (D11), in its own scrollable window

Preferences are stored in `QSettings` under the keys in `dialogs.PREFERENCES`;
rebound shortcuts live under `shortcuts/<action name>` and are reapplied at
startup by `_restore_shortcuts()`.

**Still bare:** search selects matching *pages* rather than highlighting the hit
inside the thumbnail — the delegate would need to draw match rectangles.

### Phase 4 — UI rework (beyond parity) — *deprioritised, see D12*

- [ ] Split view with full-page preview
- [ ] Dual-pane merging
- [ ] Visible undo history

### Phase 5 — finish the port — **complete**

- [x] Single `README.md`, project-setup style; `TESTING.md`, `Win32.md` and
      `macOS.md` folded in and removed (all GTK-era build instructions)
- [x] `pyproject.toml` — dependencies, dev/packaging extras, entry point,
      pytest/ruff/coverage config
- [x] **In-app user guide** (Help ▸ User Guide) instead of the man page, which
      documented GTK environment variables and a config file that no longer
      exist. The guide covers what it never did: the mouse gestures and the
      duplex-scan workflow
- [x] **Translations wired up.** `tools/build_mo.py` compiles all 33 catalogues
      (6,583 messages) with Babel — no `msgfmt` binary needed, which matters on
      Windows. `app.py` calls `i18n.setup()` *before* building any widget
- [x] PyInstaller spec at `packaging/pdfarranger-qt.spec`, bundling the compiled
      catalogues into `share/locale`
- [x] **GTK removed**: `pdfarranger/`, `setup.py`, `setup_win32.py`,
      `snapcraft.yaml`, `pdfarranger.spec` (an *RPM* spec, not PyInstaller),
      `doc/`, `.prospector.yaml`, and the GTK-only CI workflows

**Salvaged rather than deleted:** `tests/test_exporter_outlines.py` — 1,063 lines
covering outline rebuilding, repointed at `pdfarranger_qt.exporter_outlines`,
which `diff` confirms is byte-for-byte upstream's. `tests/test_core.py` was
retired because its `Page` tests target the `zoom` argument this port removed,
but its doctests now run from `tests/test_core.py`.

### Done

- [x] Environment: PySide6 6.11.1, pikepdf 10.11, img2pdf, python-dateutil in `.venv`
- [x] `core.py` — geometry verbatim, `PDFDoc` on QtPdf, `DocumentSet` replaces `PageAdder`
- [x] `export.py` — pikepdf logic verbatim, GTK plumbing dropped
- [x] `exporter_outlines.py` — drop-in copy · `metadata.py` — GUI half removed
- [x] `render.py` — render thread, LRU thumbnail cache, crop/hide masking
- [x] `model.py` — `QAbstractListModel` + memento undo with named actions
- [x] `view.py` — icon grid, delegate, hand-rolled drag reorder with insertion caret
- [x] `mainwindow.py` / `app.py` — menubar, toolbar, statusbar, 17 actions
- [x] Open · Import (multi-file merge) · Explorer drag-and-drop · encrypted-PDF password prompt
- [x] Save · Save As · Export Selection · Close · Quit
- [x] Rotate L/R · Duplicate · Delete · Undo/Redo · Select All · Invert Selection
- [x] Zoom in/out/reset (ctrl+wheel), window geometry + zoom persistence
- [x] `tests/` — 309 tests in per-module files, split out of `test_qt.py`

---

## 5. Architecture

### What ported, and how

Measured against the upstream checkout (~8,400 lines in `pdfarranger/`):

| Upstream module | Lines | Fate |
|-----------------|------:|------|
| `pdfarranger.py` | 3427 | rewritten as `mainwindow.py` + `model.py` |
| `pageutils.py` | 1168 | dialogs to be rewritten; geometry logic salvaged into `core.py` |
| `iconview.py` | 455 | rewritten as `view.py` |
| `core.py` | 979 | ported with surgery |
| `exporter.py` | 683 | ported with surgery → `export.py` |
| `config.py` | 421 | replaced by `QSettings` (D4) |
| `metadata.py` | 256 | non-GUI half copied |
| `search.py` | 240 | to be replaced by `QPdfSearchModel` |
| `splitter.py` | 211 | `_crops()` salvageable; dialog rewritten |
| `image_exporter.py` | 157 | to be replaced by `QPdfDocument` render |
| `exporter_outlines.py` | 241 | **drop-in, unmodified** |
| `undo.py` | 130 | reimplemented in `model.py` |

The PDF logic is largely separable from the toolkit — that is what made this
tractable. `core.py` and `exporter.py` had the lowest GTK density.

### Backend

- **pikepdf** is the PDF backend and stays. Toolkit-agnostic.
- **img2pdf** optional, for image import. Also `python-dateutil`, `packaging`.
- **QtPdf** (`QPdfDocument`, PDFium) for rendering.

### Model

A `Page` is a *reference* into an immutable temporary copy of a source file
(`DocumentSet` owns the temp dir), plus geometry: angle, scale, crop, hide, and
layer pages. Nothing is written until export, so every edit is cheap and undo
snapshots are nearly free.

---

## 6. Implementation notes

### Reordering does not use Qt's item-view drag and drop (D9)

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

### Drops go to the viewport, not the view

`QAbstractScrollArea` routes drag and drop through its **viewport**, and
`setAcceptDrops(True)` on the view does *not* propagate. Without an explicit
`self.viewport().setAcceptDrops(True)`, `PageView`'s drop handlers are never
called at all.

This hid itself for a while: `MainWindow` also accepts drops, so files dragged
from Explorer still imported — they just always appended at the end, because the
window has no idea which page the pointer was over. Both the cross-instance page
drop and drop-at-position for files depend on the viewport flag.

### An escalated drag has to remember it was ours

Escalating the in-window gesture to a `QDrag` is a one-way door unless the drop
handler checks `event.source()`. Dragging a page out of the window and back in
produces a drop carrying page data with no other marker of origin, so it reads as
a foreign paste and duplicates the page. `PageView.handle_page_drop()` takes an
explicit `internal` flag for this, and falls back to copying if the recorded rows
are somehow missing — duplicating is recoverable, losing pages is not.

### Printing is dominated by QPainter.end(), and scales with DPI squared

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

### Never change the page layout mid print job

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

### Colour schemes do not exist under the offscreen platform

`QStyleHints.setColorScheme()` (Qt 6.8+) is what overrides light/dark; "system"
is `unsetColorScheme()`, and Qt follows the OS by itself from there. That is all
"native dark mode is free in Qt" ever meant — the *System* case is free, an
explicit override is one call.

The offscreen platform used by the tests reports `ColorScheme.Unknown` and
ignores the setter, so the two tests that assert Qt actually changed skip there.
They pass under `QT_QPA_PLATFORM=windows`, where `Light` becomes `Dark` and the
palette's windowText flips `#000000` → `#ffffff`. Run
`QT_QPA_PLATFORM=windows pytest tests/test_theme.py` to exercise them.

Page thumbnails deliberately stay white in dark mode: the delegate paints the
sheet explicitly rather than from the palette, because a PDF page is paper.

### `pikepdf.open_metadata()` is not a read-only accessor

It defaults to `set_pikepdf_as_editor=True` and rewrites the Producer on context
exit. Inspection code that opens metadata and then reads `docinfo` will report
*its own* value — this cost real time once, concluding a user's file had been
written by this app when it had not. Pass `set_pikepdf_as_editor=False` for
anything that only wants to look.

`metadata.merge_doc()` keeps the default deliberately: it is upstream code, the
mutation is what carries the pikepdf Producer into the merged output, and
`_set_meta()` compensates via its `ppae` flag. Left alone rather than diverged.

### Mouse-gesture modifiers are sampled late

Ctrl+drag-to-copy cannot read the modifier at the press, because ctrl+press is
already the extended-selection "toggle this item" gesture. `mouseReleaseEvent`
samples it instead, matching how Explorer behaves: start the drag, then hold ctrl
before letting go. `mouseMoveEvent` switches the cursor to `DragCopyCursor` live
so the pending action is visible.

### Cell geometry must be relaid out by hand

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

### `setScaledClipRect()` cancels `setRotation()`

In Qt 6.11, setting `QPdfDocumentRenderOptions.setScaledClipRect()` makes PDFium
**silently ignore the rotation**: the page comes back upright inside a correctly-sized
sideways frame. `render.py` therefore renders the full page and crops the resulting
`QImage`. There is a regression test (`TestRendering.test_rotation_reaches_the_pixels`)
because the failure is easy to miss — the thumbnail has the right dimensions, just the
wrong pixels.

### Temp files

Each instance gets its own `tempfile.TemporaryDirectory`, removed on clean shutdown
(verified). A hard kill skips `closeEvent` and leaves copies of the opened PDFs
behind. Inherent, not a regression — but worth a startup sweep eventually, since the
leftovers are copies of user documents.

---

## 7. Known gaps and warnings

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
> (`export_doc_job`, needs pikepdf >= 8). The Preferences checkbox will drive it;
> meanwhile it reads `QSettings` key `export/preserve-first-document`.

> **Watch the msgids.** `tests/test_i18n.py::TestI18n` fails the build if a menu
> label uses a string absent from `po/de.po` and not explicitly listed as new.
> Rewording a label without checking `po/` silently orphans 33 translations.

### Test layout

One file per package module, so a failure names the layer it is in:

| File | Covers |
| --- | --- |
| `test_core.py` | geometry, `Page`, `DocumentSet`, blank pages, `core` doctests |
| `test_render.py` | render thread, thumbnail cache, `MemoryDocument` |
| `test_model.py` | undo, reordering, list ops, scale/crop/split |
| `test_view.py` | drag reorder, rubber band, relayout |
| `test_export.py` | export paths, hidden pages, the pikepdf `Job` path |
| `test_layers.py` | compositing one page onto another |
| `test_booklet.py` | imposition and unimposition |
| `test_clipboard.py` | wire format, drag payloads, cross-instance drops |
| `test_raster.py` | rasterising, white-border detection, embedded images |
| `test_search.py` · `test_printing.py` · `test_theme.py` · `test_recent.py` | as named |
| `test_dialogs.py` | dialog widgets and the values they hand back |
| `test_i18n.py` | msgid guard, translation loading, `i18n` doctests |
| `test_window.py` | `MainWindow` actions, driven through the actions themselves |
| `test_packaging.py` | project metadata, and a guard against GTK creeping back |
| `test_exporter_outlines.py` | salvaged from upstream, unchanged |

`tests/conftest.py` holds what must happen once per process and before any Qt
import — the offscreen platform, the single `QApplication`, the message-box
recorders. `tests/support.py` holds the shared helpers: `settle()`,
`QtDocumentTestCase`, the fixture paths. A `TestCase` base class is not a
pytest fixture, so it does not belong in a conftest.

Upstream's own tests are gone apart from `test_exporter_outlines.py`: the rest
imported the GTK modules, and `tests/test.py` was a dogtail GUI test that does
not survive the view rewrite. Upstream's `test_core.py` was retired because its
`Page` tests target the `zoom` argument this port removed.

> **Doctests need a real test.** They used to hang off unittest's `load_tests`
> hook, which pytest does not implement — under pytest the hook collected
> nothing and 24 doctests silently never ran. They are now plain test methods
> calling `doctest.testmod`, which both runners execute.

### A note on content streams

Scaling and overlay *do* synthesize a content stream — they wrap the page as a Form
XObject (`q s 0 0 s 0 0 cm /pN Do Q`). That wraps the page whole; it never parses or
rewrites what is inside it, so no glyph or font work is involved. Firmly Tier 1.

---

## 8. Behaviour documented only in the wiki

Source: <https://github.com/pdfarranger/pdfarranger/wiki/User-Manual> — the
authoritative user documentation. None of this is in the man page or discoverable
in the UI, and some of it is easy to miss in the code. Read it before assuming a
behaviour is incidental.

### Mouse gestures

Confirmed against `sw_scroll_event()` in `pdfarranger.py`:

| Gesture | Effect |
|---------|--------|
| Ctrl + scroll | Zoom — **implemented** |
| Shift + scroll | Scroll horizontally — **implemented** |
| Alt + scroll | Scroll exactly one row — **implemented** |
| Scroll with button 1 held | Continues a drag-selection — **implemented** |
| Double-click a page | Toggles zoom-fit — **implemented** |
| Click-drag between pages | Range-selects — **implemented** (rubber band) |

### Cross-instance page transfer

The app is `NON_UNIQUE`: every launch is a separate process. Pages move between
instances **both** by copy/paste and by drag-and-drop, carrying serialised page
references that point at the *source* instance's temp files. So the source must
still be running for a paste to resolve. This is why D5 keeps the serialisation
format, and why D9's hand-rolled drag has to grow a cross-window path.

### Outlines are expected to be lost by some operations

Documented as normal behaviour, not a bug — bookmarks do not survive:

- page size changes when the document contains links
- booklet generation
- merging
- margin hiding
- overlay/underlay pasting

Worth knowing so this is neither "fixed" nor treated as a porting regression.
`exporter_outlines.py` rebuilds outlines for the operations where it *can*.

### Config file locations (upstream, for reference)

- Linux: `~/.config/pdfarranger/config.ini`
- Windows installer: `%APPDATA%\pdfarranger\config.ini`
- Windows portable: alongside `pdfarranger.exe`

Superseded by `QSettings` per D4, but this is where a migrating user's existing
customisations live if we ever want to import them.
