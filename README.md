<p align="center">
  <img src="data/icons/hicolor/scalable/apps/com.github.jeromerobert.pdfarranger.svg" width="120" alt="PDF Arranger Qt icon">
</p>

<h1 align="center">PDF Arranger Qt</h1>

<p align="center">
  <b>Open a PDF, rearrange it, and save once — merge, split, reorder, rotate, crop and impose pages against a live thumbnail grid.</b>
</p>

---

PDF Arranger Qt opens one or more PDFs as a single working document and lets you edit it as a
whole: drag pages into order, rotate and crop them, split a page into tiles, lay one page
over another, build a folded booklet, then write the result out once. Every change is made
against an in-memory model with undo — nothing touches disk until you save.

It is a **PySide6/Qt port** of [PDF Arranger](https://github.com/pdfarranger/pdfarranger),
which is itself derived from PDF-Shuffler. The PDF work is done by
[pikepdf](https://github.com/pikepdf/pikepdf); page rendering uses Qt's own PDFium-based
`QtPdf`. Page *content* is never rewritten — only page order, geometry and composition.

## Features

- **Arrange** — drag to reorder within the window or between running copies, with an
  insertion caret; ctrl-drag to copy. Reverse a range, swap odd and even pages.
- **Combine** — open several files as one document, import more at any point, paste pages
  as odd or even to interleave two single-sided scans back together.
- **Transform** — rotate, crop margins, hide margins, resize to any paper size, and trim
  white borders automatically.
- **Compose** — split a page into a grid, merge one page onto another as an overlay or
  underlay, generate a folded booklet (imposition) or take one apart.
- **Export** — save to one file or one file per page, to PNG or JPEG, or to a rasterised
  PDF. Print, with a resolution setting. Edit document properties.
- **Find** text across the document; extract a page's text or embedded image.
- Asynchronous thumbnail rendering with an LRU cache, so large documents stay responsive.
- Native light/dark theme, and every keyboard shortcut is rebindable.

## Running from source

### 1. Prerequisites

- Install Python 3.14 or later from <https://www.python.org/>.
- Clone the repository:
  - `git clone https://github.com/dwsdolce/pdfarranger-qt`
  - `cd pdfarranger-qt`

### 2. System dependencies

None. Qt, pikepdf and img2pdf all ship as wheels — there is no GTK, no PyGObject, no
poppler and no system package to install on any platform.

### 3. Create a virtual environment (recommended)

- `python3.14 -m venv .venv`
- Activate it:
  - Linux/macOS: `source .venv/bin/activate`
  - Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
  - Windows (Git Bash): `source .venv/Scripts/activate` (note `Scripts`, not `bin`)

### 4. Install the project

All dependencies are declared in [pyproject.toml](pyproject.toml).

- Run-only install: `pip install -e .`
- Developer install (adds pytest and ruff): `pip install -e ".[dev]"`

### 5. Launch

- `python -m pdfarranger_qt` — or `pdfarranger-qt` once installed
- Optionally with files: `python -m pdfarranger_qt one.pdf two.pdf`

## Testing

```bash
pytest tests
```

The suite drives a real Qt application under the **offscreen** platform, so it exercises
the render thread, the item model and the export path rather than mocking them. A couple
of colour-scheme assertions need a real windowing system and skip by default; run them
with:

```bash
QT_QPA_PLATFORM=windows pytest tests/test_theme.py
```

Modal message boxes are replaced with recorders during the run — under the offscreen
platform a single unexpected dialog would otherwise block the whole suite instead of
failing one test.

The test files mirror the package: `test_core.py`, `test_render.py`, `test_model.py`,
`test_view.py`, `test_export.py` and so on, plus `test_window.py` for the menu actions
and `test_packaging.py` for the project metadata. `tests/conftest.py` holds the
once-per-process setup — the offscreen platform, the single `QApplication`, the
message-box recorders — and `tests/support.py` the shared helpers and fixture paths.

## Documentation

**Help ▸ User Guide** inside the application covers the page operations, the mouse
gestures and where settings are kept.

[PORTING-NOTES.md](PORTING-NOTES.md) is the project document for the port: the decisions
and why they were made, the menu design, a phase-by-phase tracker, and the implementation
traps worth knowing about.

## Configuration

Settings are stored through `QSettings` in the per-user location for the platform — on
Windows, the registry under `HKEY_CURRENT_USER\Software\pdfarranger`. That scope is
deliberately unchanged from before the rename (decision D1): moving it would orphan
saved window geometry, zoom and shortcuts. There is no
configuration file to edit by hand; everything, including keyboard shortcuts, is in
**Edit ▸ Preferences**.

## License

PDF Arranger Qt is free software, licensed under the GNU General Public License version 3 or
later — see [COPYING](COPYING).

Copyright © 2008–2017 Konstantinos Poulios, 2018–2025 Jerome Robert and contributors,
2026 David Smith.
