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
- Developer install (adds pytest, ruff, Babel and PyInstaller): `pip install -e ".[dev]"`

The `dev` extra is a superset — it covers running the tests *and* building installers.
A build machine that never runs the tests can use the smaller `packaging` extra instead.

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

## Building installers

One script per platform in [packaging/](packaging/). Each does the same four things —
compile the translation catalogues, stamp the build number from git, run PyInstaller,
then wrap the result in the platform's installer format.

| Platform | Command | Produces |
| --- | --- | --- |
| Windows | `packaging\build_win.bat` (cmd)<br>`packaging/build_win` (Cygwin, Git Bash) | `installer/PDF_Arranger_Qt_V<version>.exe` |
| macOS | `packaging/build_mac [dmg\|pkg]` | `PDF_Arranger_Qt_V<version>.dmg` |
| Linux | `packaging/build_linux` | `dist/pdfarranger-qt-<version>-<arch>.AppImage` |

All three need `pip install -e ".[dev]"` first. Each also needs one native tool that is
not a Python package:

- **Windows** — [Inno Setup 6](https://jrsoftware.org/isdl.php), expected at
  `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
- **macOS** — `create-dmg` (`brew install create-dmg`); `.icns` generation uses `sips`
  and `iconutil`, which ship with the system
- **Linux** — [appimagetool](https://github.com/AppImage/AppImageKit/releases), at
  `~/bin/appimagetool` or wherever `APPIMAGETOOL` points

### Version numbers

The version is four parts, `0.1.0.1349`:

- `0.1.0` is `__version__` in [pdfarranger_qt/\_\_init\_\_.py](pdfarranger_qt/__init__.py),
  the single place it is written down. `pyproject.toml` must agree, and
  `tests/test_packaging.py` fails if it drifts.
- `1349` is the build number: `git rev-list --count HEAD`. Nothing is typed by hand, and
  the number identifies the exact commit an installer was cut from.

[tools/gen_version_build.py](tools/gen_version_build.py) writes it to two generated,
uncommitted files — `pdfarranger_qt/version_build`, which PyInstaller bundles so the
frozen app can report a build number without git, and `build/installer_version`, which
the Inno Setup script reads. Running from a source checkout needs neither: the package
asks git directly. **Help ▸ About** shows `0.1.0 (1349)`.

The version reaches the installer through a file rather than an `ISCC /D` argument on
purpose. Git Bash rewrites any argument that looks like a Unix path, so
`/DMyAppVersion=…` arrives as `C:\Program Files\Git\DMyAppVersion=…`, while the `//`
escape that fixes that is passed through literally by Cygwin. A file works in both, in
cmd, and in the Inno Setup IDE.

### Code signing

macOS signing and notarisation are opt-in and read from the environment, so no Developer
ID is committed to this public repository:

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export NOTARY_PROFILE="notarytool-profile"
packaging/build_mac dmg
```

Without them the build succeeds unsigned, and Gatekeeper warns on first launch.
Windows builds are unsigned.

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
