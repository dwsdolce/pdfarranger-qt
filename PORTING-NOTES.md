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
| D20 | What a bookmark points at, and how it survives editing | **A stable page id, assigned once and copied by `Page.duplicate()`; the outline lives in the undo state beside the page list** | The outline has to survive operations that move, delete and duplicate the pages it targets, so the question is what a bookmark holds. *Object identity* is out: `UndoManager.snapshot` rebuilds every page with `duplicate()`, so one undo would leave every bookmark pointing at an orphan. *Page indices* are out too — every reorder, delete and insert would have to remap them, which is `OutlineRemapper`'s export-time work happening continuously and getting it wrong once is silent corruption. A **uid on the page**, preserved by `duplicate()` and therefore by undo, costs one field and makes reordering free: nothing to remap, because nothing refers to position. Deleting a page leaves its bookmarks *dangling* rather than deleting them — they are skipped on export and reconnect on undo, which is what makes the pair undoable together. The user-facing Duplicate command assigns fresh uids to its copies, so bookmarks stay with the original page rather than following both. And the outline is snapshotted with the pages, so there is one history rather than two that can disagree: undoing a rename and undoing a rotation come off the same stack. |

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
- [ ] **Own the reader's view, on the engine we already have.** The widget
      replacement itself is done, and cost about what was predicted --
      comparable in size to phase 6. Every reader limitation met until then
      traced to `QPdfView` being a closed widget rather than to the engine
      underneath, so replacing it with a scroll area of our own delivered link
      following, text selection and copy, a cache and prefetch policy we
      control, and facing pages, none of which `QPdfView` exposed at all.

      **Not complete.** One step below is open: keyboard text selection. Text
      selection is one of this item's own deliverables, and only the mouse half
      of it is built, so this stays unchecked until the caret and shift+arrow
      land. Everything else here is done.

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
            destination reports (0, 0), as section 6 measured, so those land at
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
            taken to them -- is section 6, *Extending a selection*, along with
            what Acrobat does instead and why it was not copied
      - [ ] **Keyboard text selection: an insertion caret and shift+arrow.**
            The one selection gesture Acrobat has that this does not. In
            Acrobat you click to place a caret and then extend by character or
            line with shift+arrow; here a click leaves an anchor but nothing
            visible, and the arrow keys scroll and change pages.

            Three things to settle before building it. The caret has to be
            *painted* -- an invisible one is why shift+click needed no caret
            and this does. The arrow keys have to be shared with scrolling and
            page navigation, which they currently own outright. And the
            keyboard stays character-granular, unlike the mouse, so
            `extend_to`'s word snapping is not reused: see section 6,
            *Extending a selection*, for why the two differ
      - [x] Placeholders and prefetch. The hybrid section 6 settled: the
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

      Steps. Detail in section 6:

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
            untouched. See section 6, *Saving the outline*
      - [x] Drag to re-nest within the tree. `InternalMove` over a mime type
            of our own carrying the entry's path from the root, because Qt's
            own encoding is a row and a column and a tree position is neither.
            One drag, one undo entry; refused into an entry's own subtree, and
            a no-op when dropped where it already was

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

### Most of a document's links are not in the document

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

### Why Acrobat is smoother, and what we did about it

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

### Editing bookmarks — the design

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

### Double-click selects a word

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

### Extending a selection, and why it is not Acrobat's rule

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

### Test settings: isolated from the user, and from each other

Two separate guarantees, and only the first one existed for a long time.

**From the user.** `settings.app_settings()` is the single accessor, and it
switches to a scratch store whenever `under_test()` says so. Without it the
suite wrote into the store the *installed* application reads: an earlier version
set the real app to German in a dark theme, rebound Duplicate, and refilled the
recent files list after the user had cleared it. `tests/test_settings_scope.py`
holds the line, including a test that greps the package to make sure no module
builds a `QSettings` of its own.

**The hole in it:** the trigger is `PYTEST_CURRENT_TEST`, which only pytest
sets. A script run by hand that imports the package gets the **real** store and
writes to it on close. One did: it put a test fixture into the user's recent
files and overwrote their saved window geometry, which looked for an afternoon
like a bug in geometry restoring. `PDFARRANGER_QT_TEST_SETTINGS` now exists so
such a script can opt in deliberately -- set it to anything before importing.

**From each other.** The scratch store is **one file per process**, because two
runs at once otherwise share it. That showed up as a flake with nothing about
settings in it: a suite running in the background made a foreground run of
`tests/test_recent.py` fail, since both were clearing and filling one
recent-files list. Reproducible at four concurrent runs; six now pass.

**Why an ini file under the temp directory** rather than the platform's native
scope: a scope per process means a file per process, and those have to be
removable. On macOS they are not, reliably -- the native store is written back
asynchronously, so deleting the plist at exit races the write and loses. 595
stray plists had accumulated in `~/Library/Preferences` before anyone counted.
An ini file deletes cleanly, and the temp directory is swept anyway if the
`atexit` hook does not run.

A related trap worth knowing about, because it wasted an afternoon: `conftest.py`
wipes the scratch store **at import**, and `tests/support.py` imports
`conftest`. So a hand-written probe that imports `support` to reuse `settle()`
clears the settings before it reads them, and any round-trip it is trying to
measure comes back empty.

### Shift-click selects a rectangle, not a range

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

### Opening a document selects nothing

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

### The status bar has to keep saying where you are

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

### The current page follows you between the modes

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

### Moving a page a long way, and why cut and paste is not a move

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

### Closing a document has to empty the outline

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

### Dragging in the outline tree

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

### Saving the outline

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

**Deduplication moved to read time**, as section 4 always said it should. It is
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
