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
- Editing bookmarks at all, which upstream cannot do — *todo, phase 7*
- Read mode: continuous-scroll page view with outline and go-to-page — **done**

---

## 2. Decisions

Settled decisions and why, numbered in the order they were taken. Anything
not here is still open.

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
| D18 | PDF engine for the reader | **QtPdf — stay on it** | Settled when phase 7 was picked up. Neither library provides a view widget, so that work is identical either way and the choice only decides what backs it. Measured: PyMuPDF renders 9–17% faster, but links come out *equivalent* — both give rect and target page, and both return (0,0) for a `/FitR` position — so the feature that raised the question is a wash. PyMuPDF's two real advantages, `set_toc()` and per-word text geometry, are precisely the ones bookmark editing and text selection would use, which is why this was left open until those items began. `set_toc()` round-trips an ordinary outline intact (807 of 807, nesting preserved) but **raises** on the Handbook's `/GoToR` bookmarks — a PyMuPDF bug — and bookmarks are written by `exporter_outlines.py` at export in any case, which handles `/GoToR`, named destinations and cross-file repair correctly. That leaves word-level geometry as the only surviving advantage, a refinement on `QPdfDocument.getSelection()`, bought for 55.5 MB against QtPdf's 5.7 MB already shipped, a third engine beside pikepdf and PDFium, and AGPL — permitted with GPL-3 (§13) but it would stop that code going back upstream. A judgement about *this* codebase and these documents, not a claim that QtPdf is the better library; on the merits PyMuPDF is. Re-test the `/GoToR` bug if bookmark editing ever stalls on outline writing. See §6. |
| D19 | Read mode's document when nothing has been edited | **Open the source file directly, skipping the export** | D15 has read mode show an in-memory export of the edited page list, which is right when there are edits and pure cost when there are not: entering read mode on a 1590 page book took 3.6 s and peaked at 1.7 GB to reproduce a file already on disk. `DocumentSet.source_if_unmodified()` returns the source when the list is one document, whole, in order and unmodified, and None otherwise, so the export stays the default and the fast path is the exception. Measured end to end: 639 ms and 746 MB against 4190 ms and 2226 MB. Verified equivalent before building, not after: same page count, same page sizes, an 807-entry outline with identical titles and nesting, and a search giving 156 hits at identical coordinates on both documents. The *working copy* rather than the original, because `PDFDoc` never touches the copy again and that is what makes saving over the opened file safe. Does not weaken D15 -- the export remains what read mode does whenever a page has been touched. |

### Still open

Nothing is open. D18, the reader's PDF engine, was the last one and is settled
above: QtPdf, decided when phase 7 was picked up.

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

**View** — Read Mode · Continuous Scroll ‖ Previous/Next/First/Last Page ·
Go to Page… ‖ Zoom In · Zoom Out · Fit One Page · Fit Multiple Pages ·
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
section 6, *Entering read mode costs more than reading does*. When the page list
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
      at identical page and rectangle on both. Checked because section 6
      *Read mode* warns about pointing a view at another document's geometry,
      and because the outline is what `/GoToR` has broken before
- [x] An unmodified page list can be recognised cheaply. `Page.unmodified()`
      already existed for the per-page half — angle, crop, hide, scale and
      layers — and was used nowhere; the list-level half is one pass checking
      a single `nfile`, contiguous `npage`, and a count matching the document

**Build**

- [x] `DocumentSet.source_if_unmodified()`, asked at *entry to read mode*
      rather than at open time. The choice is a property of the current page
      list, not an intention the user declared — the reasoning is in section 6
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
that way. The last two do not: owning the reader's view and editing bookmarks
are what was actually wanted from phase 7, and are active work as of phase 6a
above. The reader's view comes first because text selection and link following
are built on it (D16), and bookmark authoring is much better with a selection to
take a title and an `/XYZ` destination from.

- [ ] Split view with full-page preview
- [ ] Dual-pane merging
- [ ] Visible undo history
- [ ] **Own the reader's view, on the engine we already have.** The single
      largest item here, and the one that unblocks most of the rest. Every
      reader limitation met so far traces to `QPdfView` being a closed widget,
      not to the engine underneath it — see *Which PDF engine* below. Replacing
      it with a scroll area of our own, laying out pages rendered through
      `QPdfDocument` and the existing `Renderer`/`ThumbnailCache`, would deliver
      in one go:

      - **link following**, internal and external — `QPdfLinkModel` already
        supplies rectangles, target pages, URLs and `linkAt()` hit-testing
      - **text selection and copy** — `QPdfDocument.getSelection()` is there
      - **placeholders while scrolling**, so pages never go blank: the grid's
        thumbnail cache already holds a bitmap of every page
      - **a cache and prefetch policy we control**, which `QPdfView` does not
        expose at all
      - **facing pages**, which `QPdfView.PageMode` has no setting for

      The cost is real and should not be understated: page layout, scrolling,
      zoom anchoring, hit-testing and keyboard navigation all become ours to
      get right, and `QPdfView` does them for free today. Comparable in size to
      phase 6 itself. **View ▸ Continuous Scroll** is the cheap workaround in
      the meantime. Planned in §6 *Owning the reader's view*.

      Steps, each leaving read mode usable. Detail in section 6:

      - [x] Canvas: page layout, scrolling, and the coordinate mapping
            everything else is built on. `canvas.py`: `PageLayout` for the
            geometry, `PageCanvas` for the widget, `SynchronousPages` as the
            bitmap seam step 5 replaces
      - [x] Parity with what `QPdfView` did — continuous and single page, fit
            page and width, zoom with the anchor under the cursor, keyboard
            navigation, the page selector, search highlighting. `QPdfView` is
            gone from read mode; one page at a time is the scroll range
            restricted to one page's extent rather than a second layout, so
            hit testing behaves identically in both modes
      - [ ] Link following, internal and external
      - [ ] Text selection and copy
      - [ ] Placeholders and prefetch
      - [ ] Facing pages
- [ ] **Edit bookmarks — create, delete, rename, re-target, re-nest.** Upstream
      has none of this: its `exporter_outlines.py` only *preserves* an outline
      through an export, and neither its menu nor its window has a single
      bookmark command. Nothing to port, so this is new work.

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

      Worth doing after the phase 4 highlighting item, which pushes on the same
      geometry, and worth its own decision entry when it is picked up: whether
      an edited outline survives a page edit that deletes its target, and
      whether a bookmark is undoable separately from the pages.

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


### Read mode goes blank when you scroll fast, and cannot be tuned

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


### Entering read mode costs more than reading does

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
it today. And the refresh policy recorded in section 2 has an edit made *while*
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

### Owning the reader's view — the plan

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
cost 40-250 ms, and they are the same pages at every size (Handbook p1425,
p1327, p1325, p1488).

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

### One toolbar per mode, and why the first attempt did not work

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


### Which PDF engine — and why not to change it

Asked because read mode cannot follow links. Measured before answering: **QtPdf
is not the limitation. `QPdfView` is.**

`QPdfDocument` and its models already expose everything a full reader needs:

| Need | Available today |
| --- | --- |
| Rendering | `QPdfDocument.render()` — already drives the thumbnails |
| Text | `getAllText()` |
| Selection | `getSelection()`, `getSelectionAtIndex()` |
| Links | `QPdfLinkModel` — `Rectangle`, `Page`, `Url`, `Location`, `linkAt()` |
| Search | `QPdfSearchModel` — already wired to both views |
| Bookmarks | `QPdfBookmarkModel` — already wired |

Verified against the repaired ARRL Handbook: page 0 reports 20 links with correct
rectangles and target pages, and `linkAt(centre)` hit-tests to the right one. The
`qt.pdf.links: link with invalid location and/or zoom` warnings cost only the
precise *point* within the target page — `Location` comes back as (0, 0) — because
`QPdfLinkModel` understands only `/XYZ` destinations. Tested all six: `/XYZ` is
accepted, `/Fit`, `/FitH`, `/FitV`, `/FitR` and `/FitB` each warn. The Handbook's
links are `/FitR` and `/FitH`, which are perfectly legal; the warning count is
identical before and after our repair, so it is the document's, not ours.

`QPdfView` uses none of it. That is the whole gap.

**The alternatives, and why each was set aside**

| Option | Verdict |
| --- | --- |
| **pypdfium2** | The same engine QtPdf wraps, so identical rendering. Gains direct PDFium access, loses Qt integration. No reason. |
| **PyMuPDF** | Genuinely richer and faster, but **AGPL** — see below. |
| **Poppler** | Good link support, and what upstream used. Reintroduces the native dependency the port deliberately shed; "no GTK, no poppler, no system package on any platform" is a stated selling point in the README. |
| **pdf.js in QtWebEngine** | A complete viewer, for a ~150 MB dependency the PyInstaller spec excludes on purpose. |

**Neither library ships a view widget**, so the scroll area, layout, zoom
anchoring, hit-testing and keyboard navigation are the same work under both. The
engine choice does not change the large cost; it only decides what backs it.

Measured on the repaired Handbook:

| | QtPdf | PyMuPDF |
| --- | --- | --- |
| render, 900 px | 13.5 ms/page | 11.2 ms/page |
| render, thumbnail | 9.1 ms/page | 8.3 ms/page |
| link rect and target page | yes | yes |
| link position within the page | `(0,0)` on `/FitR` | **also `(0,0)`** |
| per-word text geometry | no | 762 words in 254 ms |
| write an outline | rebuild via pikepdf | `set_toc()` |
| packaging | 5.7 MB, already shipped | 55.5 MB |

**Links come out equivalent**, which is worth recording because it was expected to
be PyMuPDF's advantage and is not: neither library turns a `/FitR` rectangle into
a point. PyMuPDF's genuine advantages — `set_toc()` and word-level geometry —
serve *bookmark editing* and *text selection*, neither of which has been started.

**The outline round trip, tested** — because bookmark editing is the phase 7 item
that would justify the switch, and `set_toc()` is the reason to want it.

- On the **repaired** Handbook, whose bookmarks are local: `get_toc(simple=False)`
  → `set_toc()` → save preserves **807 of 807** bookmarks, all still resolving,
  nesting unchanged at depths 2/45/402/358. It rewrites `/Dest` arrays as
  `/A /GoTo` actions, which is equivalent.
- On the **original**, whose 18,131 bookmarks are `/GoToR`: **`set_toc()` raises**
  `AttributeError: 'tuple' object has no attribute 'x'`. That is a PyMuPDF bug,
  not the document's: `set_toc` replaces `dest_dict["to"]` with a tuple
  (`__init__.py`, "transform target to PDF coordinates"), and `getDestStr`'s
  `LINK_GOTOR` branch then reads `ddict["to"].x`. The `LINK_GOTO` branch unpacks
  the tuple and survives, so the failure is specific to external bookmarks with a
  page number.

So `set_toc()` is a real convenience for ordinary documents and unusable on one
of the two real files to hand. Working around it means pre-processing the TOC to
avoid the broken branch — at which point the gap against the pikepdf machinery
already written narrows considerably.

The leaning is therefore to stay on QtPdf: it is already integrated, and
`exporter_outlines.py` handles `/GoToR`, named destinations and cross-file repair
that `set_toc()` currently crashes on. That is a reason about *this* codebase and
these documents, not a claim that QtPdf is the better library — on the merits
PyMuPDF is. Worth re-testing when bookmark editing starts, in case the `/GoToR`
bug is fixed upstream by then.

### If PyMuPDF is ever chosen: the licensing, in plain terms

*Not legal advice — this is a reading of the licence texts, and worth confirming
before it matters.*

- Upstream PDF Arranger is **GPL-3.0-or-later**. This port is a derivative work,
  so it stays GPL-3.0-or-later. That is settled and does not change.
- PyMuPDF is offered under the **AGPL** or a commercial licence. Confirm the
  current version and terms at the time of the decision rather than trusting this
  note.
- **The two combine legally, in one direction** — and this is the part that
  looks wrong until you read the clause. GPLv3 §7 forbids adding "further
  restrictions", and the AGPL's network requirement plainly is one, so the
  natural conclusion is that the combination is impossible. **GPLv3 §13 is an
  explicit carve-out from exactly that rule**, and it is in this repository's
  own `COPYING`:

  > **13. Use with the GNU Affero General Public License.**
  >
  > *Notwithstanding any other provision of this License*, you have permission
  > to link or combine any covered work with a work licensed under version 3 of
  > the GNU Affero General Public License into a single combined work, and to
  > convey the resulting work. The terms of this License will continue to apply
  > to the part which is the covered work, but the special requirements of the
  > GNU Affero General Public License, section 13, concerning interaction
  > through a network will apply to the combination as such.

  The FSF added it in v3 for this purpose. Note the condition: it is **GPL-3**
  that grants this. **GPL-2.0-only** code has no such clause and genuinely
  cannot be combined with AGPLv3. Upstream is GPL-3.0-**or-later**, so the
  carve-out applies here.

What that means concretely:

- **Nothing is relicensed.** Upstream's code stays GPL-3; PyMuPDF stays AGPL;
  ours stays GPL-3. You cannot "replace the AGPL with the GPL" — that is not a
  thing either party can do to the other's code, and it is not required.
- **Upstream's licence is not violated**, because GPLv3 itself permits the
  combination. The relationship with the original project is legally unaffected.
- **The practical obligation is close to inert here.** The AGPL's extra
  requirement is to offer source to users who interact with the software *over a
  network*. A desktop page arranger has no such users. It would bind anyone who
  later turned this into a web service — which is exactly what the clause exists
  for.
- **The one real cost is contribution back.** Code of ours that depends on
  PyMuPDF could not be handed to upstream without imposing the network clause on
  them. D13 already records that there is nothing to contribute back and no fork
  relationship, so this is a small cost — but it is the one that touches the
  relationship with the original, which is the part worth thinking about.

Given the recommendation above is to keep QtPdf and own the view, this decision
should not need making at all.


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
