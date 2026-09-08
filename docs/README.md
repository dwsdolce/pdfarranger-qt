# Project documentation

**PDF Arranger Qt** — a PySide6 port of PDF Arranger. Start with
[PORTING-NOTES.md](PORTING-NOTES.md) for what this project is and how it got
here.

These files were one 3,144-line document until it stopped being readable. The
split is by *kind of knowledge*, because that is what decides where something
belongs when you come to add to it.

## The record

| File | What goes in it |
|---|---|
| [PORTING-NOTES.md](PORTING-NOTES.md) | The port: goal and scope, the menu map, phases 0–7, what the architecture is made of, and behaviour documented only in upstream's wiki. |
| [DECISIONS.md](DECISIONS.md) | D1–D22 and their reasoning. **The numbers are identifiers, not positions** — code cites `D13` and `D20`, so a decision keeps its number for ever. |
| [FINDINGS.md](FINDINGS.md) | What the libraries actually do, as opposed to what the documentation says. Each one measured, most the hard way. |
| [DESIGN.md](DESIGN.md) | What the application was decided to do and why — reasoning that is not obvious from the code and would otherwise be re-argued every time somebody reads it. |
| [CONVENTIONS.md](CONVENTIONS.md) | How the project is laid out and built: test layout, settings isolation, temporary files, installers. |

## Work after the port

| File | State |
|---|---|
| [PDF24-COMPARISON.md](PDF24-COMPARISON.md) | **Complete but for image downsampling** ([Issue #8](https://github.com/dwsdolce/pdfarranger-qt/issues/8)). Scored against PDF24 Toolbox's tool list; seven features built. |
| [I18N.md](I18N.md) | **Active** — the [Internationalisation milestone](https://github.com/dwsdolce/pdfarranger-qt/milestone/1). The translated interface that was not one, and what filling 33 catalogues takes. |

## Where to put a new thing

- *"The library does X, not Y — I measured it"* → **FINDINGS.md**
- *"We chose to behave this way because…"* → **DESIGN.md**, unless it is
  numbered, in which case **DECISIONS.md**
- *"Here is how you build/test/lay out…"* → **CONVENTIONS.md**
- A body of work with a beginning and an end → **its own file**, moved to
  `completed/` when it is done

Two rules learned by getting them wrong:

**The code does not cite these documents.** Not by number, not by title, not at
all. Nine comments once cited "section 6" for material that had drifted into
section 7, silently, for months — and then the one document became eight and
every reference had to be rewritten, which is when it became clear they should
not exist. Documentation is ephemeral; source outlives it. So the reasoning
lives in the comment, and where a measurement justifies a decision the number is
in the docstring — *"the worst page costs 247 ms"* — not a pointer to where the
number was written down. `tests/test_docs.py` enforces it.

These files are the long form: the argument behind a decision, the measurements
in full, the things that would bloat a docstring. Read them, and write them; do
not depend on them.

**Open work belongs in [Issues](https://github.com/dwsdolce/pdfarranger-qt/issues),
not here.** A checkbox in a document is a to-do list nobody is assigned to and
nothing closes. What these files are for is what was decided and what was
measured — the things that stay true.

Two consequences worth stating, because they are what makes the list trustworthy:

- **A deferred item stays open, with the `deferred` label.** Closing it is how
  it gets lost. A decision not to do something now is not a decision never to
  do it, and the three phase-7 items are open for exactly that reason — two of
  the original five were deprioritised and then built anyway.
- **A body of work too large to close gets a tracking issue**, whose body
  carries the plan and whose sub-issues are created per wave as waves start.
  Re-scoping then edits the body instead of losing the item.
