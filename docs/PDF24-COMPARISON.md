# PDF24 comparison — phase 8

[The port's goal](PORTING-NOTES.md) names dissatisfaction with **PDF24 Toolbox**
as the reason this project exists, so its tool list is the fairest external
yardstick there is. This is the score against it, and the work that came out of
it. The scope reasoning itself is [D21](DECISIONS.md).

**Complete apart from [#8](https://github.com/dwsdolce/pdfarranger-qt/issues/8).**

Scored against the live menus on 2026-09-07: **17 of its 37 tools are already here**,
four more are cheap, three are real work worth doing, and thirteen are things a
page arranger should not be.

Everything from that list judged worth having is built, with one exception that
is marked `[~]` rather than `[x]`: **Compress** is two features wearing one
name, and only the cheap half exists. Image downsampling — what people usually
mean by the word — is [#8](https://github.com/dwsdolce/pdfarranger-qt/issues/8).

**Already covered.** Organize · Merge · Split · Extract pages · Remove pages ·
Rotate · Sort · Crop · Change page size · Images to PDF · PDF to images ·
Extract images · Overlay · Protect · Edit metadata · Edit bookmarks — and
**Unlock**, which is a side effect rather than a command: open with the password,
save without one, and `export_doc` writes `encryption = False`. Worth a menu
entry if it should be discoverable. *Flatten* is half done — Export ▸ Rasterized
PDF is the sledgehammer version; flattening form fields into static content is a
different job.

**Cheap, and in character** — each is pikepdf against machinery already here:

- [x] **Web optimize** — `pdf.save(linearize=True)`, one save option.
      A Preferences checkbox, applied to every save: `export.SaveOptions`
- [x] **Remove all metadata** — File ▸ Remove All Metadata, a toggle like the
      password, because it is a decision about what gets written rather than
      something that happens now. Both the XMP packet and the older Info
      dictionary go; Edit Properties greys out while it is on
- [x] **Edit viewer preferences** — `/ViewerPreferences`, `/PageLayout`,
      `/PageMode`, in `viewer.py`. Pairs with D20: having authored an outline,
      "open with the bookmarks pane showing" is its natural companion. Read from
      the file when one is *opened* — saving builds a brand new PDF, so without
      that every round trip would drop them
- [x] **Repair** — pikepdf already recovers on open; this is "save the recovery".
      `repair.py`. The damage is found by opening *twice*: pikepdf recovers
      silently by default, so `attempt_recovery=False` is the only thing that
      makes it admit the problem (measured; there is no `Pdf.check()` in
      pikepdf 10)

**Real work, but the right kind:**

- [x] **Pages per sheet (N-up).** The one worth arguing for. Tier 1 page
      composition, built from blank pages and `paste_as_layer` — the booklet
      imposition machinery pointed at a different arrangement — and upstream does
      not have it. `nup.py`, Arrange ▸ Pages per Sheet…, beside Split and Merge
      because it is the same kind of thing. Sheet orientation is chosen to waste
      the least: two portrait pages side by side want a landscape sheet, and a
      2x2 grid wants the orientation it already had
- [x] **Add page numbers** and **Add watermark** share one missing primitive:
      drawing text onto a page. Build it once and both follow; build it for
      neither and neither is possible. A *PDF* watermark is already Paste As
      Overlay; it is the text case that is missing. `stamp.py` builds it with
      **QPdfWriter** rather than by hand-writing a content stream — see
      [FINDINGS.md](FINDINGS.md), *Drawing text onto a page* — and
      both commands are one `Style` apart. A stamp is a generated one-page PDF
      composited as an overlay, so it is undoable and the source file is never
      touched
- [~] **Compress** — *partly*, and the box says so.
      Written as `[x]` at first with the caveat below it, which is precisely how
      it came to be believed finished: a checkbox holds one bit and "half done"
      does not fit in it. The rest is
      [#8](https://github.com/dwsdolce/pdfarranger-qt/issues/8).

      The trivial half is done. `compress_streams` plus object streams,
      a Preferences checkbox beside Web optimize. Gains little on a file full of
      already-compressed images, which is why the label promises nothing.
      Image **downsampling** — what people usually mean by the word — is still
      open, and is where the effort is; the raster machinery is already here

**Out of scope (D21).** Convert to/from PDF · Create invoice · Create job
application · Create fillable form · Annotate · Edit PDF · Sign · Compare · OCR ·
Blacken.

> **Blacken (redaction) deserves more than a shrug.** The naive implementation
> draws black rectangles, and the text underneath stays fully extractable — that
> has leaked real secrets from real documents. Correct redaction *removes* the
> content. The only version safe to build on this machinery is
> rasterise-then-black, which is lossy and slow. If it is ever wanted, ship it
> named **"Redact (rasterises the page)"** so the trade is in the label.

The screenshot scored from has a scrollbar, so there may be tiles below the fold
that were never seen.

---
