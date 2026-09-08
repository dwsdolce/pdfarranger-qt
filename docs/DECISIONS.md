# Decisions

Settled decisions and why, numbered in the order they were taken. **The numbers
are identifiers, not positions** — code cites `D13` and `D20` directly, so a
decision keeps its number for ever, even when it is superseded.

Anything not here is still open.

## Decisions

Settled decisions and why, numbered in the order they were taken. Anything
not here is still open.

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Package name | **`pdfarranger_qt`**, permanently | Locked so the `QSettings` scope never has to move. Renaming later would silently orphan saved window geometry and zoom. |
| D2 | i18n | **Keep gettext, reuse `po/`. Wrap strings in `_()` as they are written.** | 33 catalogues at ~239 msgids each. Nothing forces a PySide6 app onto Qt's `tr()`/`.ts`; Python `gettext` works fine in a Qt app, so unchanged strings carry straight over. Wrapping as we go is nearly free; retrofitting across 25 actions and a dozen dialogs is not. |
| D3 | Menu structure | **Settle the full mapping before building dialogs** — see the menu map in [PORTING-NOTES.md](PORTING-NOTES.md) | 25 more actions are coming. Deciding placement once beats reshuffling a menubar twelve times. |
| D4 | Settings store | **`QSettings`**, everything exposed in the UI | The old `config.ini` held window geometry, print settings and accelerators; Qt has native mechanisms for all three. Carrying the format forward would mean carrying `Gtk.accelerator_parse` with it. Consequence: no ini file to point users at, so Preferences must expose every setting — including shortcuts (D11). |
| D5 | Clipboard format | **Keep upstream's serialisation byte-for-byte** | Free, and lets the Qt and GTK versions interoperate via copy/paste during the transition. Constrains `Page.serialize()`, which is already ported. |
| D6 | Packaging / installer | **Defer until GTK is gone** — now done | A Qt PyInstaller spec is a different beast from the GTK one; maintaining both in parallel while things churn is wasted effort. Delivered once GTK was removed: see [CONVENTIONS.md](CONVENTIONS.md), *Building installers*. |
| D7 | Booklets | **In scope** — both generate and split | Cheaper than first assessed: built entirely from blank pages, overlay layers and `Page.split()`, all of which are already ported or already planned. Neither needs a dialog. |
| D8 | Rendering backend | **`QPdfDocument` (PDFium)** replaces poppler-glib + cairo | Wholesale replacement, not a translation. Confirmed the old path was `Poppler.Document.new_from_file` → `cairo.ImageSurface`. |
| D9 | Reordering | **Hand-rolled drag in `PageView`**, not Qt item-view DnD | See [FINDINGS.md](FINDINGS.md), *Reordering does not use Qt's item-view drag and drop*. Qt's IconMode DnD answers "dropped onto which item"; page arranging is about the gaps between items. |
| D10 | CLI surface | **Match upstream exactly**: `[files...]` and `--version` | Already implemented. The man page says "PDF Arranger doesn't receive any options"; nothing more is expected. |
| D11 | Customisable shortcuts | **Yes — a shortcut editor in Preferences** | Upstream supports them but only via hand-editing `config.ini`, documented nowhere in the app or man page (see the upstream wiki notes in [PORTING-NOTES.md](PORTING-NOTES.md)). D4 removed the ini, so the capability has to move into the UI. |
| D12 | Phase 7 (split view, dual-pane, undo history) | **Deprioritised — last, and optional** | Not important to the user; they can live without them. This removes the sequencing risk that made D3 urgent: parity work can proceed without fear of reworking the window later. |
| D13 | Application name and project identity | **"PDF Arranger Qt"**; distribution `pdfarranger-qt`; **new standalone repository keeping the full git history**, with upstream added as a read-only `upstream` remote — not a GitHub fork | A distinct name avoids passing this off as upstream's application, and had to be settled *before* anyone else runs it because D1 locked the `QSettings` scope. That scope is deliberately **left as `("pdfarranger", "pdfarranger_qt")`** despite the rename: moving it is exactly the orphaning D1 exists to prevent. Not a fork because GitHub disables code search in forks, the "forked from" banner would misrepresent a Qt rewrite of a deleted GTK app, and there is nothing to contribute back. History is kept because this is a real derivative work — `exporter_outlines.py` verbatim, geometry and pikepdf logic verbatim, 33 translation catalogues, upstream artwork — and the history is the provenance record behind those attribution claims. |
| D14 | Read mode | **In scope, as a second view mode** — `QPdfView` swapped into the central widget, arrange actions disabled while it is showing | `QtPdf` is already a dependency for thumbnails, and `QPdfView` is a finished continuous-scroll widget on the same PDFium backend. The gap between "has a reader" and "has no reader" is wiring, not rendering. Reading is why the document was opened; making the user leave for a separate viewer is the PDF24 complaint the port exists to fix. |
| D15 | What Read mode displays | **The edited page list, via an in-memory export** — *not* the renderer's `QPdfDocument` | Forced, not preferred. See [FINDINGS.md](FINDINGS.md), *Read mode: what QtPdf actually gives you*: the edits do not live in the `QPdfDocument`, and that document belongs to a worker thread. `SearchIndex` already does exactly this, so the machinery exists. |
| D16 | Text selection and link following | **Out of the first cut** | Neither is exposed by `QPdfView` in 6.11.1 — verified against the installed API, not assumed. Both are buildable on `QPdfDocument.getSelection()` and `QPdfLinkModel`, but they are hand-written features, not wiring, and they do not block a usable reader. |
| D17 | Annotation and markup | **Out of scope, permanently** | Tier 2 by another name. Qt exposes no annotation authoring, and adding it would mean owning an annotation model, hit-testing and appearance-stream generation. |
| D18 | PDF engine for the reader | **QtPdf — stay on it** | Settled when phase 7 was picked up. Neither library provides a view widget, so that work is identical either way and the choice only decides what backs it. Measured: PyMuPDF renders 9–17% faster, but links come out *equivalent* — both give rect and target page, and both return (0,0) for a `/FitR` position — so the feature that raised the question is a wash. PyMuPDF's two real advantages, `set_toc()` and per-word text geometry, are precisely the ones bookmark editing and text selection would use, which is why this was left open until those items began. `set_toc()` round-trips an ordinary outline intact (807 of 807, nesting preserved) but **raises** on the Handbook's `/GoToR` bookmarks — a PyMuPDF bug — and bookmarks are written by `exporter_outlines.py` at export in any case, which handles `/GoToR`, named destinations and cross-file repair correctly. That leaves word-level geometry as the only surviving advantage, a refinement on `QPdfDocument.getSelection()`, bought for 55.5 MB against QtPdf's 5.7 MB already shipped, a third engine beside pikepdf and PDFium, and AGPL — permitted with GPL-3 (§13) but it would stop that code going back upstream. A judgement about *this* codebase and these documents, not a claim that QtPdf is the better library; on the merits PyMuPDF is. Re-test the `/GoToR` bug if bookmark editing ever stalls on outline writing. See §6. |
| D19 | Read mode's document when nothing has been edited | **Open the source file directly, skipping the export** | D15 has read mode show an in-memory export of the edited page list, which is right when there are edits and pure cost when there are not: entering read mode on a 1590 page book took 3.6 s and peaked at 1.7 GB to reproduce a file already on disk. `DocumentSet.source_if_unmodified()` returns the source when the list is one document, whole, in order and unmodified, and None otherwise, so the export stays the default and the fast path is the exception. Measured end to end: 639 ms and 746 MB against 4190 ms and 2226 MB. Verified equivalent before building, not after: same page count, same page sizes, an 807-entry outline with identical titles and nesting, and a search giving 156 hits at identical coordinates on both documents. The *working copy* rather than the original, because `PDFDoc` never touches the copy again and that is what makes saving over the opened file safe. Does not weaken D15 -- the export remains what read mode does whenever a page has been touched. |
| D20 | What a bookmark points at, and how it survives editing | **A stable page id, assigned once and copied by `Page.duplicate()`; the outline lives in the undo state beside the page list** | The outline has to survive operations that move, delete and duplicate the pages it targets, so the question is what a bookmark holds. *Object identity* is out: `UndoManager.snapshot` rebuilds every page with `duplicate()`, so one undo would leave every bookmark pointing at an orphan. *Page indices* are out too — every reorder, delete and insert would have to remap them, which is `OutlineRemapper`'s export-time work happening continuously and getting it wrong once is silent corruption. A **uid on the page**, preserved by `duplicate()` and therefore by undo, costs one field and makes reordering free: nothing to remap, because nothing refers to position. Deleting a page leaves its bookmarks *dangling* rather than deleting them — they are skipped on export and reconnect on undo, which is what makes the pair undoable together. The user-facing Duplicate command assigns fresh uids to its copies, so bookmarks stay with the original page rather than following both. And the outline is snapshotted with the pages, so there is one history rather than two that can disagree: undoing a rename and undoing a rotation come off the same stack. |

| D21 | Which of PDF24's tools belong here | **In: page-level composition. Out: authoring, converting, annotating, signing, comparing, OCR, redaction** | PDF24 Toolbox is named in [the port's goal](PORTING-NOTES.md) as the reason this project exists, so its list is the yardstick — and most of what it does is not what this is. Converting to and from PDF needs LibreOffice or Word, which is exactly the native dependency the port shed (README: "no system package to install on any platform"). Invoices, job applications and fillable forms are document *authoring* — Tier 2 under another name. Annotating and editing text are D17 and Tier 2. Signing needs certificate handling pikepdf does not do. Comparing is a different application. OCR needs tesseract or ocrmypdf. Redaction is refused on safety grounds, not effort: see the PDF24 comparison. What is left — N-up, page numbers, watermarks, linearising, metadata, viewer preferences — is all page-level, which is Tier 1 and in scope. |

| D22 | Filling 33 catalogues | **Machine translation, marked as such, never over a human's work** | 10,387 missing strings is not hand-writable, and an untranslated interface is worse for a Catalan speaker than an imperfect Catalan one — that is the whole of the argument for it. What the decision buys is honesty about the result: every generated entry carries a comment saying it was generated, so a reviewer can find all of them; `Last-Translator` keeps the name of the person who last did the work by hand, because putting a translator's name on machine output is a misattribution; and a language is filled in *around* its existing human translations rather than over them, which is also why Pull Request #2's Russian is taken before any of this runs. The two failure modes that matter are mechanical rather than linguistic — a `%d` that comes back as `%s` crashes at runtime in a language the developer cannot read, and a dropped `_` mnemonic silently removes keyboard access — so both get a test rather than a reviewer. |
## Still open

Nothing is open. D18, the reader's PDF engine, was the last one before D22 and
is settled above: QtPdf, decided when phase 7 was picked up. D22 is a decision
taken, not a question — what remains under it is work, tracked as issues under the
internationalisation milestone.

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
## Notes on D11

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
## Which PDF engine — and why not to change it

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
## If PyMuPDF is ever chosen: the licensing, in plain terms

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
