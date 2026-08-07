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

- **Tier 3 — reading** (continuous scroll, outline, go-to-page, text search).
  Not editing at all, and not something upstream does — the GTK application is an
  arranger you look at through thumbnails. **In scope as phase 6**, because the
  Acrobat-like model in the background note above means opening a document and
  *reading* it, not only rearranging it. See D14–D17.

Everything still unported is Tier 1 or Tier 3. Nothing remaining requires content
editing.

### Beyond parity — the reason for the port

- Async thumbnail rendering with caching (PDF Arranger bogs down on large documents) — **done**
- Real multi-select: rubber-band, shift-range, ctrl-toggle, ops across selection — **done**
- Native drag-and-drop from Explorer, including images — **done**
- Native dark mode — **free in Qt**
- Split view: thumbnail grid alongside a full-page preview of the selection — *todo, phase 7*
- Dual-pane merging: two documents side by side, drag pages across — *todo, phase 7*
- Visible undo history rather than blind Ctrl-Z — *todo, phase 7*
- Read mode: continuous-scroll page view with outline and go-to-page — **done**

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
| D6 | Packaging / installer | **Defer until GTK is gone** — now done | A Qt PyInstaller spec is a different beast from the GTK one; maintaining both in parallel while things churn is wasted effort. Delivered once GTK was removed: see §6 *Building installers*. |
| D7 | Booklets | **In scope** — both generate and split | Cheaper than first assessed: built entirely from blank pages, overlay layers and `Page.split()`, all of which are already ported or already planned. Neither needs a dialog. |
| D8 | Rendering backend | **`QPdfDocument` (PDFium)** replaces poppler-glib + cairo | Wholesale replacement, not a translation. Confirmed the old path was `Poppler.Document.new_from_file` → `cairo.ImageSurface`. |
| D9 | Reordering | **Hand-rolled drag in `PageView`**, not Qt item-view DnD | See §6. Qt's IconMode DnD answers "dropped onto which item"; page arranging is about the gaps between items. |
| D10 | CLI surface | **Match upstream exactly**: `[files...]` and `--version` | Already implemented. The man page says "PDF Arranger doesn't receive any options"; nothing more is expected. |
| D11 | Customisable shortcuts | **Yes — a shortcut editor in Preferences** | Upstream supports them but only via hand-editing `config.ini`, documented nowhere in the app or man page (see §8). D4 removed the ini, so the capability has to move into the UI. |
| D12 | Phase 7 (split view, dual-pane, undo history) | **Deprioritised — last, and optional** | Not important to the user; they can live without them. This removes the sequencing risk that made D3 urgent: parity work can proceed without fear of reworking the window later. |
| D13 | Application name and project identity | **"PDF Arranger Qt"**; distribution `pdfarranger-qt`; **new standalone repository keeping the full git history**, with upstream added as a read-only `upstream` remote — not a GitHub fork | A distinct name avoids passing this off as upstream's application, and had to be settled *before* anyone else runs it because D1 locked the `QSettings` scope. That scope is deliberately **left as `("pdfarranger", "pdfarranger_qt")`** despite the rename: moving it is exactly the orphaning D1 exists to prevent. Not a fork because GitHub disables code search in forks, the "forked from" banner would misrepresent a Qt rewrite of a deleted GTK app, and there is nothing to contribute back. History is kept because this is a real derivative work — `exporter_outlines.py` verbatim, geometry and pikepdf logic verbatim, 33 translation catalogues, upstream artwork — and the history is the provenance record behind those attribution claims. |

| D14 | Read mode | **In scope, as a second view mode** — `QPdfView` swapped into the central widget, arrange actions disabled while it is showing | `QtPdf` is already a dependency for thumbnails, and `QPdfView` is a finished continuous-scroll widget on the same PDFium backend. The gap between "has a reader" and "has no reader" is wiring, not rendering. Reading is why the document was opened; making the user leave for a separate viewer is the PDF24 complaint the port exists to fix. |
| D15 | What Read mode displays | **The edited page list, via an in-memory export** — *not* the renderer's `QPdfDocument` | Forced, not preferred. See §6 *Read mode*: the edits do not live in the `QPdfDocument`, and that document belongs to a worker thread. `SearchIndex` already does exactly this, so the machinery exists. |
| D16 | Text selection and link following | **Out of the first cut** | Neither is exposed by `QPdfView` in 6.11.1 — verified against the installed API, not assumed. Both are buildable on `QPdfDocument.getSelection()` and `QPdfLinkModel`, but they are hand-written features, not wiring, and they do not block a usable reader. |
| D17 | Annotation and markup | **Out of scope, permanently** | Tier 2 by another name. Qt exposes no annotation authoring, and adding it would mean owning an annotation model, hit-testing and appearance-stream generation. |

### Still open

The repository housekeeping that used to sit here is done: `origin` is
`dwsdolce/pdfarranger-qt`, and `pyproject.toml` carries the real `Homepage`.

Phase 6 opened three questions; the answers, now that it is built:

- **Refresh policy** — lazy. An edit only marks the snapshot stale
  (`_reader_stale`), and the re-export happens on the next entry into read mode.
  The exception is an edit made *while* reading, which rebuilds immediately:
  leaving it stale would show a document that visibly disagrees with the one
  being edited.
- **Scroll position across a refresh** — keep the page number and clamp, as
  guessed. `go_to_page` bounds the request, so a stored page past the end lands
  on the last page rather than failing.
- **Find** — shared phrase, separate models. Running a search sets the phrase on
  both, and `QPdfView` highlights the hits itself. The models cannot be shared:
  `SearchIndex` builds its own in-memory copy for the grid, and a
  `QPdfSearchModel` over that document would highlight using the wrong
  geometry.

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
not-yet-implemented; the remaining ones are phase 7 (see D12).

**File** — New Window · Open… · Import… ‖ Save · Save As… ‖ Export ▸ (Selection to Single
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

**View** — Read Mode ‖ Zoom In · Zoom Out · Fit One Page · Fit Multiple Pages ·
Fit Width · Reset Zoom ‖ Show Page Numbers\* ·
Preview Pane\* ‖ Fullscreen

**Help** — User Guide ‖ Project on GitHub · About

**Arrange** is a new top-level menu with no upstream equivalent. It separates
operations *on a page* (Page) from operations *on document order and composition*
(Arrange), which is the distinction the app's own name turns on.

---

## 4. Progress tracker

Legend: `[x]` done and tested · `[~]` partially done · `[ ]` not started

Ordered by dependency, not by date, so the numbers do not run in the order the
work happened: **phase 4 is outstanding while phase 5 is complete**, and that is
the point. Phase 5 retired GTK and shipped installers — that is done. Finishing
the *feature* port is phase 4, and until those boxes are ticked this is not yet a
drop-in replacement for upstream. Phases 6 and 7 are additions on top, so they
follow.

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
      remembering whenever this workflow is touched: the reverse step is easy
      to forget and the result looks plausible without it.

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

- [x] Find · Find Next · Find Previous · Find All (`search.py`) — selects the
      matching *pages*; highlighting the hit inside the thumbnail is phase 4
- [x] Crop White Borders (`raster.white_border_crops`)
- [x] Image export to PNG/JPEG, with the ppi and greyscale preferences
- [x] Rasterised-PDF export (flattens text to pixels, verified by round trip)
- [x] Extract ▸ Copy Text · Copy Image · Explode into Images (`raster`, via pikepdf).
      **Not** "extract pages to a file", which is the natural reading and the
      wrong one: upstream's *extract* copies a page's image or text *content* to
      the clipboard, which is why it needed image extraction and a text layer
      rather than an export path
- [x] Print (`printing.py`, `QPrinter`) — covered by tests: a `QPrinter` set to
      `PdfFormat` with an output file needs neither dialog nor spooler
- [x] Theme (`theme.py`) — light/dark/system, applied at startup and immediately
      when Preferences changes
- [x] Preferences — Language · Theme · Printing (incl. DPI) · Saving/exporting ·
      Image Export · **shortcut editor** (D11), in its own scrollable window

Preferences are stored in `QSettings` under the keys in `dialogs.PREFERENCES`;
rebound shortcuts live under `shortcuts/<action name>` and are reapplied at
startup by `_restore_shortcuts()`.

### Phase 4 — remaining parity gaps — *one item left*

Everything upstream's menu offers that this does not. Found by diffing the GTK
`data/menu.ui` (recovered from `git log`) against `MainWindow._shortcut_groups()`:
72 upstream entries, 4 with no equivalent here, plus one behaviour gap behind an
action that does exist. Small, and unglamorous, but this is the list that decides
whether someone can switch.

- [ ] **Highlight search matches inside the thumbnail.** Find selects the
      matching *pages*; upstream draws rectangles around the hits
      (`show_find_results` → "Draw rectangles around found text"). `PageDelegate`
      needs per-match geometry from `QPdfSearchModel` via `QPdfLink.rectangles()`,
      mapped through the same crop and rotation the thumbnail already applies.
      Phase 6 gets in-place highlighting free from `QPdfView.setSearchModel()`,
      but that does not replace this: the grid is where multi-page results are read
- [x] **New Window** — `QProcess.startDetached` on the interpreter (or the frozen
      exe), *not* a second `MainWindow`: the app is `NON_UNIQUE` by design (§8),
      and two windows in one process would share the temp directory and the
      clipboard-owner checks that tell our drags from someone else's
- [x] **Set/change document password.** `export.py` had taken `output_password`
      through both export paths and built `pikepdf.Encryption(R=6)` all along;
      **nothing in the UI ever passed it.** Now a checkable **File ▸ Password**
      with a confirm-twice dialog. Cancelling leaves it off rather than
      checked-with-no-password, which would look encrypted and not be. Verified
      by round trip: the saved file raises `pikepdf.PasswordError` without it
- [x] **Export Selection to Rasterized PDF (jpg)** — `export_rasterised()` was
      already parameterised by format; only the action was missing
- [x] **Fit One Page / Fit Multiple Pages.** Upstream's `win.zoom-fit` takes a
      target, and the two differ **only in column count** — both use the same
      fit-the-whole-page scale, and `fit_one_page` pins `col_num = 1`. The port's
      Zoom Fit was therefore already the *multiple* variant; what was missing was
      the single-column pinning. `PageView.set_single_column()` supplies it, and
      any other zoom releases it

**Also fixed here:** the action was labelled `_("Swap Odd/Even Pages")` with a
plain `_()`, so the msgid guard never checked it and the string appeared in no
catalogue at all. It now uses `_m("Swap Odd/Even")` — upstream's msgid, which
five catalogues translate — and the undo label matches the menu label again.

With those done, diffing upstream's `menu.ui` against the port's actions leaves
**no missing commands**. The one item above is a behaviour gap behind a command
that does exist.

### Phase 5 — retire GTK, package and ship — **complete**

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
- [x] **Installers for all three platforms** (D6, deferred until GTK was gone):
      `packaging/build_win` + `.bat` (Inno Setup), `build_mac` (dmg/pkg),
      `build_linux` (AppImage). Build number stamped from `git rev-list --count`
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


### Phase 6 — Read mode (D14) — **complete**

A second view mode, not a second application: the same window, the same document,
a different central widget. Arrange stays the default.

**Build**

- [x] `pdfarranger_qt/reader.py` — `ReaderView`: a `QPdfView` beside a
      `QTreeView` on `QPdfBookmarkModel`, in a `QSplitter`
- [x] `MainWindow`: a `QStackedWidget` with the grid at index 0 and the reader
      at 1; **View ▸ Read Mode** (Ctrl+E), checkable. **Not** double-click —
      that already toggles Fit One Page, and silently reassigning it would
      break a documented, tested gesture
- [x] `reader.load(pages, files)` — `get_in_memory_pdf()` → `MemoryDocument` →
      `setDocument()` (D15). Verified by rotating a page and reading the
      rendered page size back: width and height swap
- [x] Action gating, **derived from the menus** rather than hand-listed:
      everything outside File/View/Help, less the commands that only look
      (Find, Preferences, the Select group, Copy). A new editing command is
      disabled in read mode without anyone remembering to add it
- [x] Per-document last page in `QSettings` under `reading/<path>`. An unsaved
      document has no key and does not try; a stored page past the end clamps,
      because an edit can delete the page you were on
- [x] The reader keeps **its own** `QPdfSearchModel` over its own document.
      `SearchIndex` builds a separate in-memory copy for the grid, and pointing
      `QPdfView` at that one would highlight using another document's geometry
- [x] Help ▸ User Guide: a Read mode section

**Zoom is not persisted.** `QPdfView` starts in `FitToWidth`, which is the right
answer at any window size; restoring a saved factor would override it with one
that suited a window you are no longer using.

> **`get_in_memory_pdf()` gained an `outlines` flag.** Outlines were gated behind
> `to_file` on the grounds that the in-memory callers — white-border detection,
> image export, printing, search — have no use for them. Read mode's sidebar *is*
> the outline, so it asks for them; the flag is off by default so nothing else
> pays. `rebuild_outlines` already skipped `None` entries in `pdf_input`, so the
> in-memory case needed no other change.

> **`QPdfView` owns the `QPdfDocument` you give it** and destroys it with itself,
> which leaves `MemoryDocument` holding a wrapper whose C++ side has gone. The
> navigator also emits `currentPageChanged` while a document is being swapped or
> dropped, so a handler that asks the reader anything during teardown gets
> "Internal C++ object (QPdfDocument) already deleted". `clear()` drops its
> reference *before* calling `setDocument(None)`, `closeEvent` clears the reader
> before the widgets go, and `page_count()` catches the `RuntimeError` as a last
> resort. Third instance of this ownership trap in the port; see also the
> `QMenu` one above.

**Deliberately not in the first cut** (D16, D17): text selection and copy, link
following, facing-page layout, annotations.

**Tests.** The reader is a Qt widget over PDFium, so the useful assertions are
about wiring, not pixels: that the document handed to `QPdfView` reflects the
edited page list rather than the original file (rotate a page, enter Read mode,
check the page count and size), that arrange actions are disabled while reading
and re-enabled on leaving, that the bookmark model populates for a document with
an outline and is empty for one without, and that last-position survives a
close/reopen. `tests/test_reader.py`.

### Phase 7 — UI rework (beyond parity) — *deprioritised, see D12*

- [ ] Split view with full-page preview
- [ ] Dual-pane merging
- [ ] Visible undo history

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
> (`export_doc_job`, needs pikepdf >= 8). Driven by the Preferences checkbox,
> stored as `QSettings` key `export/preserve-first-document`.

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

### Building installers

One script per platform in `packaging/`, all four steps the same: compile the
catalogues, stamp the build number, run PyInstaller, wrap the result. README.md
has the commands and the prerequisites; what follows is only the reasoning.

**The version is four parts, `0.1.0.1349`.** `0.1.0` is `__version__` in
`pdfarranger_qt/__init__.py` — the single place it is written down, with
`pyproject.toml` held to it by `tests/test_packaging.py`. `1349` is
`git rev-list --count HEAD`, so nothing is typed by hand and the number
identifies the commit an installer was cut from. This mirrors how the sibling
`guitar_tap` project does it.

`tools/gen_version_build.py` writes two generated, uncommitted files:
`pdfarranger_qt/version_build` (bundled, so the frozen app can report a build
number with no git and no `.git`) and `build/installer_version` (read by the
`.iss`). A source checkout needs neither — `_read_build()` asks git directly,
anchored to the package directory rather than the process cwd, because the app
may well have been launched from the directory of the PDF being opened.

> **Why the installer version comes from a file.** The obvious route is
> `ISCC /DMyAppVersion=…`, which is what `guitar_tap` does. It cannot be made to
> work in both Windows shells: **Git Bash rewrites any argument that looks like a
> Unix path**, so `/DMyAppVersion=0.1.0.1349` arrives as
> `C:\Program Files\Git\DMyAppVersion=0.1.0.1349` and ISCC reports *"You may not
> specify more than one script filename"*. The documented `//D` escape fixes Git
> Bash and breaks Cygwin, which passes arguments through untouched. A file is
> read identically by both, by cmd, and by the Inno Setup IDE.

`packaging/build_win` calls `.venv/Scripts/python.exe` and `pyinstaller.exe` by
path rather than sourcing `activate`, which does not work reliably under Cygwin:
it exports Unix-style paths the native Windows interpreter cannot read.

**The PDF association is an "Open with" entry, not the default handler.** This is
an editor, not a reader; silently taking over every PDF double-click is not a
decision an installer should make. The `.iss` registers a ProgId and adds it to
`.pdf\OpenWithProgids`, leaving the user's default alone.

**No Developer ID is committed.** The repository is public, so macOS signing and
notarisation read `CODESIGN_IDENTITY`, `INSTALLER_IDENTITY` and `NOTARY_PROFILE`
from the environment and are skipped when unset. `tests/test_version.py` fails
if an identity-shaped string ever lands in a tracked file.

> **`__main__.py` must use an absolute import.** PyInstaller uses it as the entry
> *script*, running it as a top-level module with no package context, so
> `from .app import main` dies at startup with *"attempted relative import with
> no known parent package"*. It passes every `python -m pdfarranger_qt` test,
> because `-m` sets `__package__`, and then fails only in the installed
> application. `tests/test_version.py::TestEntryPoint` reproduces the frozen
> execution model exactly -- run the file directly with the project root on
> `PYTHONPATH` -- and was confirmed to fail against the broken version.

> **A windowed PyInstaller app does not exit when it crashes.** It shows the
> traceback in a native message box and waits, so "the process is still alive
> after N seconds" is not evidence that it started: a crashed build looks
> identical to a healthy one. Check `MainWindowTitle` for the real window title
> instead. This is how the relative-import bug above got shipped and reported
> back rather than caught.


> **Tests must not share the user's settings scope.** `QSettings("pdfarranger",
> "pdfarranger_qt")` is the *installed application's* store, so a test that
> exercises the Preferences round trip wrote `language=de` and `theme=dark`
> straight into it, rebound Duplicate to Ctrl+Shift+K, and the recent-files
> tests refilled a list the user had just cleared. The redirect lives in
> `pdfarranger_qt/settings.py`, which switches to a `pdfarranger.tests`
> organisation whenever `PYTEST_CURRENT_TEST` is set — the same pattern the
> sibling `guitar_tap` project uses. It **cannot** be done from `conftest.py`:
> `QSettings.setDefaultFormat` affects only the argument-less constructor, so
> redirecting it there looks right and silently keeps writing to the registry.
> `tests/test_settings_scope.py` writes a value through the accessor and then
> reads the real scope to prove it did not move, and fails if any module
> constructs `QSettings` itself instead of calling `app_settings()`.

> **Test the action, not the method behind it.** `test_clear_menu_empties_it`
> called `clear_recent()` directly, so it would have passed with the menu entry
> wired to nothing. Where a bug report says "the menu item does nothing", the
> test has to `trigger()` the `QAction` the user clicks.


> **Never `parent.addMenu(title)`; always `QMenu(title, self)`.** PySide gives
> *Python* ownership of the QMenu returned by `addMenu(title)` and by
> `QAction.menu()`. So `_shortcut_groups()`, which walks the menu bar and calls
> `action.menu()` on every submenu, took a temporary reference to each one and
> destroyed it at the next garbage collection. The next File ▸ Open Recent then
> raised "Internal C++ object (QMenu) already deleted" from
> `_rebuild_recent_menu` — intermittently, since it depended on when the
> collector ran. `MainWindow._menu()` constructs every menu with the window as
> parent, which leaves ownership in C++, and keeps a reference in `self._menus`
> besides.
>
> This shipped, briefly, and is worth reading as a lesson in bad verification:
> the probe that declared the menus undamaged called `findChildren(QMenu)`
> first, which created wrappers that kept them alive and hid the very bug being
> looked for. `tests/test_window.py::TestMenuLifetime` forces a `gc.collect()`
> after the walk and was confirmed to fail against the unsafe form.

> **Shortcut order came from `findChildren(QAction)`**, which is QObject
> construction order, not menu order — despite the docstring claiming
> otherwise. 64 rebindable commands appeared in the order they happened to be
> built, submenu entries scattered through, so nothing could be found.
> `_shortcut_groups()` walks the menu bar instead and returns
> `[(menu title, [actions])]`, which the dialog renders with a heading per menu.

> **Zoom Fit fitted the width only.** A portrait page was therefore always
> taller than the viewport and a whole page could never be seen at once, which
> is the one thing the command is for. It now fits both dimensions, against the
> viewport less the delegate's `CELL_MARGIN`, the caption and the scrollbar
> width; `Fit Width` (Shift+F) keeps the across-the-window behaviour.
>
> That fixed the *scale* but not the *layout*, and this note originally claimed
> it amounted to upstream's **Fit One Page**. Checking upstream showed otherwise:
> its two fit commands share this exact scale and differ only in column count
> (`fit_one_page` pins `col_num = 1`), so what had been built was its **Fit
> Multiple Pages**. A portrait page fitted to the window's *height* leaves room
> for neighbours beside it, so without pinning you never get a page on its own.
> `PageView.set_single_column()` was added in phase 4.


### Read mode: what QtPdf actually gives you (D14–D16)

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


### Destinations do not survive a copy by themselves

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


### Repairing a book that was merged badly

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
