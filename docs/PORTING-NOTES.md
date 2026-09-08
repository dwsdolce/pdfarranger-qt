# PDF Arranger → PySide6 Port

How the GTK application became a Qt one: what the port set out to do, how far it
got, and what the result is built from. Started 2026-08-06.

Work done *after* the port, and everything learned along the way, lives beside
this file — see [README.md](README.md) for what is where.

- **Run:** `python -m pdfarranger_qt [files...]`
- **Test:** `pytest tests`
- **Code:** `pdfarranger_qt/` — the whole application. The GTK `pdfarranger/`
  package was removed in phase 5; `git log` has it if it is ever needed again.
- **Translations:** `python tools/build_mo.py` before running, to compile `po/`

## Goal

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
editing. [PDF24-COMPARISON.md](PDF24-COMPARISON.md) scores this boundary
against PDF24's own tool list, since that
application is the reason given below for starting; D21 records what of it is in
and what is out.
### Beyond parity — the reason for the port

- Async thumbnail rendering with caching (PDF Arranger bogs down on large documents) — **done**
- Real multi-select: rubber-band, shift-range, ctrl-toggle, ops across selection — **done**
- Native drag-and-drop from Explorer, including images — **done**
- Native dark mode — **free in Qt**
- Split view: thumbnail grid alongside a full-page preview of the selection — *todo, phase 7*
- Dual-pane merging: two documents side by side, drag pages across — *todo, phase 7*
- Visible undo history rather than blind Ctrl-Z — *todo, phase 7*
- Editing bookmarks at all, which upstream cannot do — *todo, phase 7*
- Read mode: continuous-scroll page view with outline and go-to-page — **done**

---
## Menu map (D3)

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

**View** — Read Mode · Continuous Scroll ‖ Previous/Next/First/Last Page ·
Go to Page… ‖ Zoom In · Zoom Out · Fit One Page · Fit Multiple Pages ·
Fit Width · Reset Zoom ‖ Show Page Numbers\* ·
Preview Pane\* ‖ Fullscreen

**Help** — User Guide ‖ Project on GitHub · About

**Arrange** is a new top-level menu with no upstream equivalent. It separates
operations *on a page* (Page) from operations *on document order and composition*
(Arrange), which is the distinction the app's own name turns on.

---
## Progress tracker

Legend: `[x]` done and tested · `[~]` partially done · `[ ]` not started

Ordered by dependency, not by date, so the numbers do not run in the order the
work happened — phase 5 retired GTK and shipped installers before phase 4 had
finished closing the parity gaps, and that was the point. Everything through
phase 6a is complete. What is left is the three items D12
deprioritised in phase 7.
### Phase 0 — shared plumbing — **complete**

- [x] `export.get_in_memory_pdf()` + `render.MemoryDocument` — render the *edited*
      document to memory and open it as a `QPdfDocument`. Unblocks white-borders,
      explode-images, crop preview
- [x] `DocumentSet.get_blank_doc()` / `core.create_blank_page()`, with reuse so
      hiding fifty same-sized pages makes one blank file, not fifty
- [x] **`hide` at export time** — `DocumentSet.apply_hide()`; the warning in [FINDINGS.md](FINDINGS.md) is resolved
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
- [x] Mouse gestures (see *Behaviour documented only in the wiki* below), all of them: Shift+scroll horizontal, Alt+scroll one
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
### Phase 4 — remaining parity gaps — **complete**

Everything upstream's menu offers that this does not. Found by diffing the GTK
upstream's `data/menu.ui` against `MainWindow._shortcut_groups()`. The GTK
files were removed from the working tree once the port was done, so that
reference lives in history: `git show d2c7b917:data/menu.ui`, the last commit
before `pdfarranger/` was deleted. Result:
72 upstream entries, 4 with no equivalent here, plus one behaviour gap behind an
action that does exist. Small, and unglamorous, but this is the list that decides
whether someone can switch.

- [x] **Highlight search matches inside the thumbnail.** Find selected the
      matching *pages*; upstream draws rectangles around the hits
      (`show_find_results` → "Draw rectangles around found text").
      `SearchIndex.rectangles(row)` returns them and `PageDelegate` boxes them
      over the thumbnail.

      **Far easier than this entry predicted**, and worth recording why. The
      note assumed the rectangles would have to be mapped through the crop and
      rotation the thumbnail applies. They do not: `SearchIndex` builds its
      document with `get_in_memory_pdf`, so it searches the **edited** pages —
      measured, `pagePointSize` equals `Page.width_in_points()` under rotation
      and cropping alike, and the rectangles move with the page. The delegate
      only scales points to pixels. The one catch is that a rotated hit comes
      back with **negative** width and height, so the rectangles are normalised
      before anyone tries to draw them.

      Highlights are dropped on any edit: rows move when pages do, and a stale
      box drawn in the right place on the wrong page is worse than none.
- [x] **New Window** — `QProcess.startDetached` on the interpreter (or the frozen
      exe), *not* a second `MainWindow`: the app is `NON_UNIQUE` by design (see the wiki notes below),
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
      `QTreeView` on `QPdfBookmarkModel`, in a `QSplitter`, with Qt's own
      `QPdfPageSelector` on the toolbar. That widget rather than a spin box
      because it understands page *labels*: a book numbered i, ii, iii, 1, 2
      reads the way it is printed instead of by index
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

> **Superseded by phase 7 step 2, and kept because the ordering it explains is
> still load-bearing.** `PageCanvas` only *borrows* the document, so the
> destruction below no longer happens -- but it holds a reference, and closing a
> document it still points at crashes PDFium on the next paint. Same teardown
> order, different reason. What follows was true of `QPdfView`:
>
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
### Phase 6a — entering read mode without the export — **complete**

Read mode pays 3.6 seconds and peaks at 1.7 GB to open a 255 MB book, because
D15 has it export the edited page list before it shows anything. Measured in
[FINDINGS.md](FINDINGS.md), *Entering read mode costs more than reading does*. When the page list
is unmodified that export reproduces the file already on disk, and can be
skipped for the price of a 63 ms parse.

Not beyond-parity work, and not part of phase 7: this is a defect in what phase 6
shipped. It is first because it is small, independent of the reader rewrite, and
fixes the case D14 says the reader exists for — reading a book that has not been
edited.

**Check before building.** The fast path is only viable if both hold, and
neither is assumed:

- [x] Search, bookmarks and page numbering line up when `ReaderView` holds the
      source document rather than an export. Verified on the Handbook: same
      1590 pages, no page differing in size, an outline of 807 entries with
      identical titles and nesting, and a search for "antenna" giving 156 hits
      at identical page and rectangle on both. Checked because [FINDINGS.md](FINDINGS.md)
      *Read mode* warns about pointing a view at another document's geometry,
      and because the outline is what `/GoToR` has broken before
- [x] An unmodified page list can be recognised cheaply. `Page.unmodified()`
      already existed for the per-page half — angle, crop, hide, scale and
      layers — and was used nowhere; the list-level half is one pass checking
      a single `nfile`, contiguous `npage`, and a count matching the document

**Build**

- [x] `DocumentSet.source_if_unmodified()`, asked at *entry to read mode*
      rather than at open time. The choice is a property of the current page
      list, not an intention the user declared — the reasoning is in [DESIGN.md](DESIGN.md)
      and is the part worth not re-deriving. Returns the working copy, never
      the original
- [x] `ReaderView.load` takes an optional `source` and opens it through
      `MemoryDocument.from_file`, falling back to the export if it will not
      open — a source that cannot be read costs a slow read mode, not a broken
      one. Both paths end in one `_show()`, so the fast one cannot drift out of
      step with what the models are bound to. It degrades on its own: one edit
      and the next entry falls back, with no state to track.
      **Measured end to end on the Handbook: 639 ms and 746 MB peak, against
      4190 ms and 2226 MB for the export.**
- [x] D19 records it: the fast path changes what the reader is looking at,
      which D15 deliberately settled the other way

**Tests.** That an unmodified list yields a reader document with the same page
count and page sizes as the source; that a single rotation sends the next entry
back through the export; that search and the outline still resolve on the fast
path; and that both paths agree on page numbering. The timing is not a test —
`tools/bench_export.py` measures it, and no assertion should depend on a wall
clock.

**Left for later.** The edited case keeps the 3.6 seconds, and the first edit
gives up the fast path for the rest of the session. Moving the export off the
GUI thread is the general fix and a much larger change, since it makes the
reader's document asynchronous.
### Phase 7 — UI rework (beyond parity) — *deprioritised, see D12*

D12 deprioritised this phase as optional, and the first three items below stay
that way. The last two did not: owning the reader's view and editing bookmarks
are what was actually wanted from phase 7, and **both are now done**. The
reader's view came first because text selection and link following are built on
it (D16), and bookmark authoring turned out to want a selection for exactly the
predicted reason -- Add takes both its title and its `/XYZ` destination point
from one.

What remains is the three D12 items and nothing else. They are optional by
David's own decision, not blocked.

They stay **open** rather than closed, as issues, because a decision not to do
something can change and closing it is how the item would be lost:

- [Issue #10](https://github.com/dwsdolce/pdfarranger-qt/issues/10) — split view with full-page preview
- [Issue #11](https://github.com/dwsdolce/pdfarranger-qt/issues/11) — dual-pane merging
- [Issue #12](https://github.com/dwsdolce/pdfarranger-qt/issues/12) — visible undo history
- [x] **Own the reader's view, on the engine we already have.** Cost about
      what was predicted --
      comparable in size to phase 6. Every reader limitation met until then
      traced to `QPdfView` being a closed widget rather than to the engine
      underneath, so replacing it with a scroll area of our own delivered link
      following, text selection and copy, a cache and prefetch policy we
      control, and facing pages, none of which `QPdfView` exposed at all.


      Page layout, scrolling, zoom anchoring, hit-testing and keyboard
      navigation duly became ours to get right. The thing that made that
      tractable was putting the geometry in `PageLayout` and keeping the widget
      thin: single-page mode is a restricted scroll range and facing pages is
      two indices to a row, so neither is a second layout, and hit testing,
      selection and links work the same in every mode.

      One prediction was wrong. "Placeholders while scrolling, so pages never
      go blank: the grid's thumbnail cache already holds a bitmap of every
      page" -- it does not, it holds the thumbnails the grid has displayed, and
      a cheap low-resolution render does not exist besides (see *Why Acrobat is
      smoother*). What shipped is a proxy tier of the reader's own, and pages
      still blank on a first visit.

      - [x] Canvas: page layout, scrolling, and the coordinate mapping
            everything else is built on. `canvas.py`: `PageLayout` for the
            geometry, `PageCanvas` for the widget, and a synchronous
            bitmap source as a deliberate seam, which step 5 replaced and
            deleted
      - [x] Parity with what `QPdfView` did — continuous and single page, fit
            page and width, zoom with the anchor under the cursor, keyboard
            navigation, the page selector, search highlighting. `QPdfView` is
            gone from read mode; one page at a time is the scroll range
            restricted to one page's extent rather than a second layout, so
            hit testing behaves identically in both modes
      - [x] Link following, internal and external. Hit-tested through the
            layout's mapping, which is what it was built for; verified against
            the Handbook, where all 20 links on page 0 resolve. A `/FitR`
            destination reports (0, 0), as [FINDINGS.md](FINDINGS.md) measured, so those land at
            the top of the right page rather than nowhere. External links are
            emitted rather than opened: `ReaderView.SAFE_SCHEMES` decides what a
            document may hand to the desktop, because a widget is the wrong
            place for that question and `file://` is the wrong answer
      - [x] Text selection and copy. Drag to select, across page boundaries;
            Ctrl+C, Ctrl+A, Escape; I-beam over text. The awkward part is
            `getSelection`, which wants a glyph under *both* ends -- the exact
            box of a line selects it, a generous rectangle around the same line
            selects nothing -- so `PageText` snaps each end onto the nearest run
            of text first, from one `getSelectionAtIndex` per page, cached.

            Since extended with **double-click to select a word** and
            **shift+click to extend**, both of which need a character index
            under the pointer that PDFium does not offer directly. The rule the
            two follow -- granularity follows the precision of the gesture, and
            a selection is a function of its two ends and never of the route
            taken to them -- is [DESIGN.md](DESIGN.md), *Extending a selection*, along with
            what Acrobat does instead and why it was not copied
      - [x] **Keyboard text selection: an insertion caret and shift+arrow.**
            A blinking bar placed by a click, extended by character, word or
            line, across page boundaries, always exact -- the keyboard never
            snaps to a word the way the mouse does. Design and the reasoning in
            [DESIGN.md](DESIGN.md), *Keyboard text selection*.

            One of the three things this entry said had to be settled turned
            out not to exist. "The arrow keys have to be shared with scrolling
            and page navigation, which they currently own outright" -- they do
            not: in Acrobat an unmodified arrow does nothing once a cursor is
            placed, so shift+arrow was all that was needed and nothing had to be
            given up. The keys themselves come from `QKeySequence`, which is the
            only way to be right on three platforms and which the offscreen test
            plugin promptly proved by disagreeing with macOS about them
      - [x] Placeholders and prefetch. The hybrid [DESIGN.md](DESIGN.md) settled: the
            worker keeps the queue, the drain loop and the thread, while *what*
            a task renders moved into the task and *where its document comes
            from* into a provider -- `FileDocuments` for the grid, keyed by temp
            copy, and `BytesDocument` for the reader, parsing its own copy on
            the render thread because QPdfDocument is not thread-safe. Separate
            caches, the reader's budget sized as `KEEP` pages at the current
            zoom. Placeholders are the same page at another zoom, scaled, since
            a cheap low-resolution pass does not exist. Painting a heavy
            Handbook page went from a 247 ms block to 1.2 ms
      - [x] Facing pages — the one thing `QPdfView.PageMode` had no setting
            for. Done as *rows* in `PageLayout` rather than a mode in the
            widget, so hit testing, selection, links and the coordinate mapping
            work unchanged; a cover sits alone so the spreads that follow fall
            (2,3), (4,5), the way a book opens. Fit measures the widest row, or
            a fit-one-page would show half a spread
- [x] **Edit bookmarks — create, delete, rename, re-target, re-nest.** Done:
      nine steps, all below. Upstream has none of this -- its
      `exporter_outlines.py` only *preserves* an outline through an export, and
      neither its menu nor its window has a single bookmark command. Nothing to
      port, so this was new work throughout.

      **The architectural catch.** The outline is not part of the document
      model. A `Page` is a reference plus geometry, and the outline is *derived*
      at export time by `rebuild_outlines()` reading it back out of the source
      files. There is nowhere to put an edit. Making bookmarks editable means
      the document owning an outline tree of its own — built on open, carried
      through every page edit, and written on save *instead of* being rebuilt
      from source. That is a second model beside the page list, with its own
      undo entries, and it has to survive operations that move the pages it
      points at. Reordering, deleting and duplicating pages all have to drag
      the bookmarks along, which is exactly the remapping `OutlineRemapper`
      does today at export — it would have to happen continuously instead.

      Read mode already renders the outline in a `QTreeView`
      (`ReaderView.outline`), which is the obvious place to edit it: rename in
      place, drag to re-nest, delete, and "add a bookmark here" from the page
      view. The tree widget is done; the model underneath it is the work.

      Both questions this was to answer are answered, in **D20** and in section
      6 *Editing bookmarks*: an edited outline survives a page edit as a
      *dangling* entry, and bookmarks share the page list's undo stack rather
      than having one of their own.

      Steps. Detail in [DESIGN.md](DESIGN.md):

      - [x] The model. `outline.py`: a `Bookmark` tree the document owns, free
            of Qt and pikepdf so the awkward questions -- what a delete does to
            children, what dangling means -- are testable exactly
      - [x] Page identity. `Page.uid`, carried across `duplicate()` so undo
            keeps a bookmark attached, and reassigned by the Duplicate command
            so a copy does not inherit one (D20)
      - [x] Undo. The outline is in `UndoState` beside the pages, so one stack
            covers both and a delete and its bookmarks are restored together
      - [x] Reading it from the loaded file. `read_outline()`, the counterpart
            to `rebuild_outlines()`, resolving each destination to a uid and
            telling a heading from a dangling entry on load
      - [x] Keeping it right through editing: reorder is free, delete leaves
            entries dangling, import concatenates at the root
      - [x] Showing it. `OutlineModel` in `reader.py` replaces
            `QPdfBookmarkModel` in the sidebar; dangling entries are greyed with
            a tooltip saying why, and following one resolves a uid to the page's
            current position rather than trusting an index. A parent map is
            cached, since `Outline.parent_of` walks the tree and Qt asks for
            parents constantly -- quadratic over the Handbook's 807 entries
      - [x] The commands: Add, Add Child, Re-home, Rename, Delete, Delete
            Dangling — on the tree's context menu. Each snapshots first, through
            the reader's `outline_edit_begun`, so a bookmark edit and a page
            edit come off one stack; each updates its own rows rather than
            resetting the model, which would collapse an 807-entry tree on every
            command. Only a load and an undo reset it
      - [x] Writing it on save, in place of rebuilding from source. The step
            the rest was waiting on: until it landed every command worked,
            marked the document modified and undid correctly, and was discarded
            by the next save. `write_outline` is the counterpart of
            `read_outline`; `export_doc` takes the tree and falls back to
            `rebuild_outlines` when it has none, so every in-memory caller is
            untouched. See [DESIGN.md](DESIGN.md), *Saving the outline*
      - [x] Drag to re-nest within the tree. `InternalMove` over a mime type
            of our own carrying the entry's path from the root, because Qt's
            own encoding is a row and a column and a tree position is neither.
            One drag, one undo entry; refused into an entry's own subtree, and
            a no-op when dropped where it already was
## Architecture
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
## Behaviour documented only in the wiki

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
