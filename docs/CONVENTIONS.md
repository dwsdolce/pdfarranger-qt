# Conventions

How the project is laid out and built: how one thing refers to another, where
tests live, how they are kept from touching a real settings store, where
temporary files go, and how the installers are produced.

## How to refer to things

Four numbering systems are in play, two of them spelled with a `#`, and nothing
in the notation says which is which. "Phase 8", "Issue #8", "D8" and
"Pull Request #8" can appear in one paragraph and look alike. So each is named
in full, every time.

| Thing | Written as | Notes |
|---|---|---|
| A GitHub issue | `Issue #12` | Never a bare `#12`. The `#` stays so GitHub still links it. |
| A pull request | `Pull Request #2`, then `PR #2` | The long form on first mention in a document, the short one after. |
| A decision | `D20` | An identifier, not a position — it keeps its number for ever, even when superseded. |
| A phase of the port | `phase 5` | **Only 0–7, and only as a date.** See below. |

**Work after the port is named, not numbered.** It used to be "phase 8" and
"phase 9". Once each had a file of its own the ordinal earned nothing, and it
collided with GitHub the moment Issue #8 existed alongside phase 8. So: *the
PDF24 comparison*, *the internationalisation work* — the human name in a
sentence, the filename in a link.

Phases 0–7 survive, but only in the sense a **date** does. *"`hide` is
implemented as of phase 0"*, *"the package phase 5 deleted"*, *"has produced
layer-only sheets since phase 2"* — these say **when**, and they are as true and
as fixed as any other historical fact. What is not allowed is a phase number as
the **name** of a body of work, or as somewhere to go and look, which is what
phases 8 and 9 had become.

**Documents cite each other by title, never by position.**
`[FINDINGS.md](FINDINGS.md), *Owning the reader's view*`. Numbers move when
anything is inserted above them; titles move with the thing they name. This was
learned the expensive way — nine comments cited "section 6" for material that
had drifted into section 7, silently, for months.

**Code cites nothing.** Not a document, not a section. A comment has to stand on
its own, because documentation is ephemeral and source is not: where a
measurement justifies a decision the number goes in the docstring — *"the worst
page costs 247 ms"* — rather than a pointer to where it was written down. The
one exception is a decision number, which is a name rather than a location.

Each of these is enforced by `tests/test_docs.py`. A convention with no check is
a wish, and this project has watched two of them rot.

## Temp files

Each instance gets its own `tempfile.TemporaryDirectory`, removed on clean shutdown
(verified). A hard kill skips `closeEvent` and leaves copies of the opened PDFs
behind. Inherent, not a regression — but worth a startup sweep eventually, since the
leftovers are copies of user documents.

---
## Test layout

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
| `test_nup.py` | pages per sheet: grid order, orientation, gaps |
| `test_stamp.py` | page numbers and watermarks, and the text primitive |
| `test_save_options.py` | linearize, strip metadata, compress, viewer prefs |
| `test_viewer_prefs.py` · `test_repair.py` | as named |
| `test_pdf24_ui.py` | the window's end of the PDF24-comparison features |

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
## Building installers

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
## Test settings: isolated from the user, and from each other

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
