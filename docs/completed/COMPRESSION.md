# Compression

**Complete** — [Issue #8](https://github.com/dwsdolce/pdfarranger-qt/issues/8)
is closed. This is the feature set that issue built, the numbers behind it,
and the trade-offs that decided the defaults. Scope reasoning for the
surrounding work is [D21](../DECISIONS.md); where a compressed page lands is
[D25](../DECISIONS.md); the score that raised it is
[PDF24-COMPARISON.md](PDF24-COMPARISON.md).

Everything below was measured on this machine with pikepdf 10.11 and Pillow
12.3. The defaults come from synthetic corpora built to be typical rather than
flattering — eight letter pages of rendered text on off-white paper at 300
ppi, which is what a scanner or a phone hands you — and the results at the end
come from a real 1,590-page technical handbook, which behaved nothing like the
corpora and is the reason CMYK and indexed images are supported at all.

## The word means two different things

To a user, "compress this PDF" means *make the file smaller*, and the file is
big because it is full of images. To a PDF library, `compress` means *deflate
the streams and pack the objects*, which is a different operation on a
different part of the file. We shipped the second one under the first one's
name.

## What the option does today

`SaveOptions.compress` sets `compress_streams`, `recompress_flate` and
`ObjectStreamMode.generate`. Measured:

| Document | As written | Compress ticked | Saved |
|---|---|---|---|
| Eight-page 300 ppi colour scan | 8.09 MB | 8.08 MB | **0.0%** |
| Eight pages of vector text from QPdfWriter | 0.75 MB | 0.75 MB | **0.6%** |
| The same text, written with streams uncompressed | 3.78 MB | 0.75 MB | **80.2%** |
| `tests/exporter/outlines.pdf` | 8,901 B | 1,824 B | 79.5% |
| `tests/exporter/forms.pdf` | 3,620 B | 1,639 B | 54.7% |

Read the first two rows against the last three. The option is not weak; it is
**a recovery of bytes some other generator left on the table**. When a producer
wrote its streams uncompressed it wins enormously, and on files with many small
objects the object stream packing is worth half the size. But almost every PDF
in circulation already arrives Flate-compressed, and no amount of deflating
touches a DCTDecode stream. On the documents people actually want compressed
it recovers nothing, and it is honest about that only in the sense that the
label promises nothing.

Two conclusions, and they are separable: the existing behaviour is worth
keeping and worth **renaming**, and the thing it is currently named after still
has to be built.

## What everyone else offers

**PDF24** — three knobs and a filename suffix, initialised from four registry
values (`compress.dpi`, `compress.imageQuality`, `compress.colorModel`,
`compress.saveFileSuffix`): DPI defaulting to 144, image quality 1-100
defaulting to 75, and a colour model of unchanged, `rgb`, `cmyk` or `gray`.
That is the entire feature. No presets, no per-image analysis.

**Acrobat** offers it at two levels. One-click *Compress PDF* takes a strength
and nothing else. *PDF Optimizer* is the workbench: an **Images** panel with
three independent image classes — colour, greyscale, monochrome — each with a
resampling method (bicubic, average, subsampling), a target ppi, a
**threshold** (*downsample to 150 ppi for images above 225 ppi*), a codec
(JPEG, JPEG2000, ZIP, retain existing) and a quality band; then Fonts
(un-embedding), Transparency (flattening), Discard Objects, Discard User Data,
Clean Up — which is roughly our current checkbox in its entirety — and **Audit
Space Usage**, a report of where the bytes are.

**Ghostscript** exposes four named presets: `/screen` at 72 ppi, `/ebook` at
150, `/printer` and `/prepress` at 300, the last colour-preserving.

Three products, three shapes: a level, a level plus an escape hatch, and a
workbench. All three agree on the substance — **target resolution, image
quality, colour model** — and disagree only on how much of it to show.

## What the numbers say

### Resolution against quality, on a colour scan

Eight pages, 8.09 MB as written. Each cell is the whole file after
re-encoding every image at that resolution and JPEG quality:

| Target | q90 | q75 | q60 |
|---|---|---|---|
| 300 ppi (re-encode only) | 8.08 MB | 5.65 MB | 4.84 MB |
| 200 ppi | 4.56 MB | 3.14 MB | 2.58 MB |
| 150 ppi | 2.95 MB | 2.00 MB | 1.62 MB |
| 144 ppi (PDF24's default) | 2.87 MB | **1.98 MB** | 1.61 MB |
| 100 ppi | 1.62 MB | 1.12 MB | 0.90 MB |
| 72 ppi | 0.93 MB | 0.63 MB | 0.51 MB |

The top row is the interesting one: **quality alone, at full resolution, is
worth 40%**. A user who wants a smaller file but will not accept a softer page
has an option that costs them no pixels, and neither PDF24 nor a preset ladder
offers it separately. The rest is the expected quadratic — halving the
resolution quarters the pixels — and 150 ppi at q75 is where the curve stops
paying: below it the file shrinks by less than the page degrades.

### Bilevel pages, where JPEG is simply the wrong answer

The same eight pages, treated as line art:

| Encoding | Size | Saved |
|---|---|---|
| 300 ppi colour JPEG q90 — as scanners write it | 8.08 MB | — |
| 300 ppi JPEG q60 | 4.80 MB | 40.6% |
| 144 ppi JPEG q75 — PDF24's defaults | 1.98 MB | 75.4% |
| 300 ppi greyscale, Flate only, no downsampling | 2.22 MB | 72.5% |
| **300 ppi CCITT Group 4, full resolution kept** | **0.52 MB** | **93.6%** |
| 144 ppi CCITT Group 4 | 0.25 MB | 96.9% |

Group 4 at *full* resolution beats the industry-default downsample by a factor
of four while throwing away no pixels at all. This is the largest single win
available anywhere in this document, and it is invisible to a design that has
one image path. It is also the win most likely to be missed, because the
document that benefits — a black-and-white scan — looks to a naive walk like an
ordinary RGB image and gets sent down the JPEG path.

One caveat that cost a measurement to find: Group 4's performance depends
entirely on the input being **thresholded, not dithered**. Pillow's
`convert("1")` applies Floyd-Steinberg by default, and the resulting noise
inflated the same page from 0.52 MB to 4.60 MB — a nine-fold penalty, and the
first version of this measurement reported it as fact.

### The small-image trap

A 200x80 logo placed at 96 ppi, stored as Flate:

| Treatment | Size |
|---|---|
| Left alone | 1,662 B |
| "Resampled" to 144 ppi, JPEG q75 | 5,868 B |
| "Resampled" to 300 ppi, JPEG q75 | 12,638 B |

A blind *resample everything to N* makes this **three to seven times bigger**
and lossy in the same stroke. This is what Acrobat's threshold field exists to
prevent, and it is not an edge case: business documents are mostly text with a
logo.

### Images shared between pages

An image referenced by eight pages is visited eight times by a per-page walk
and is one object. Re-encoding it on each visit produced a worst-pixel
difference of **23/255** against a single pass — visible banding in flat
areas, for eight times the work and no fewer bytes.

### Where the bytes actually are

Acrobat's *Audit Space Usage* question, asked of the 1,590-page handbook
before and after compressing it. Every stream counted once by object number,
against the category its own dictionary declares:

| | as published | compressed |
|---|---|---|
| page content streams | 96.6 MB — 37.8% | **81.1 MB — 57.2%** |
| images | 150.2 MB — 58.7% | 54.1 MB — 38.2% |
| fonts | 3.9 MB — 1.5% | 3.9 MB — 2.7% |
| object streams, metadata, forms, other | 4.9 MB | 2.7 MB |

Two things fall out of it, and neither was obvious beforehand.

**Compression moves the problem rather than finishing it.** Images were the
majority of that book and are now the minority; what remains is 81 MB of page
content streams, 51 KB a page. That is not text — it is the schematics. A
technical handbook is full of circuit diagrams drawn as vectors, and vector
content is the one thing a page arranger has no business re-encoding. So the
honest answer for this document, having taken 41.8% off it, is that there is
very little left to take.

**The cheap half is not always cheap.** Recompressing streams took content
from 96.6 MB to 81.1 MB — 15.5 MB, on a file where the measurement that opens
this document predicted almost nothing. That book was carrying a great deal of
loosely compressed vector data, which is exactly the case the option was
written for and exactly the case that never shows up on a scan.

This is also the argument for the report being part of the feature rather than
a nicety. "Your 8 MB is 7.9 MB of JPEG" and "your 151 MB is 81 MB of vector
drawings" are the same question answered, and only one of them means *run this
again with a lower setting*.

### What a pass costs

Eight pages at 300 ppi, halved and re-encoded, by resampling method:

| Method | Time | Per page |
|---|---|---|
| Lanczos | 0.88 s | 110 ms |
| Bicubic | 0.69 s | 87 ms |
| Nearest (subsampling) | 0.28 s | 35 ms |

Acrobat exposes this choice. **We should not.** The gap between the best
method and the fastest is 75 ms a page, which buys nothing a user would trade
image quality for; a 200-page scan is 22 seconds either way and needs a
progress dialog either way. Always Lanczos, and spend the knob elsewhere.

## The feature set worth building

A dialog with four fields, a preset row, and a report.

**Presets**, because most people want a level rather than a specification:
*Screen* (100 ppi, q60), *Balanced* (150 ppi, q75), *Print* (quality 90 with
the resolution left alone — the 40%-for-free row above). The names say the
destination, not the strength, so the choice can be made without knowing what
a ppi is.

**Fields**, always visible, with the preset falling back to *Custom* the
moment one is edited. Hiding them behind a Custom mode was the first plan;
this is what the N-up dialog already does, and it lets somebody see what a
preset actually means rather than only its name:

- **Target resolution**, in ppi. Default 150.
- **Only images above**, in ppi. Default 1.5x the target. This is the
  threshold, and it is what keeps the logo intact.
- **Image quality**, 1-100. Default 75. Usable on its own with resolution set
  to *unchanged*, which is the 40%-for-free row in the table above.
- **Colour**: leave alone, or convert to greyscale.

**Bilevel is automatic and not exposed.** An image that is already 1-bit, or
that is 8-bit but provably two-valued, goes to CCITT Group 4 at its existing
resolution. Nobody should have to know to ask for the biggest win in the
feature.

**A report**, before and after: how many images, what they cost now, what they
will cost. Half of why the current checkbox reads as broken is that a user has
no way to learn that their 8 MB is 7.9 MB of JPEG.

**And the audit under it** — the document's bytes as images, drawings and
text, fonts, and everything else. This is Acrobat's *Audit Space Usage*, cut
to four buckets because the question being answered is only "is it worth
running this again": the difference between an object stream and a
cross-reference stream is noise at that scale. It costs a walk over the
object numbers rather than a read — 2.7 seconds on the 1,590-page book — and
it is done while the progress dialog is still up, so it does not become
another small silence.

It earns its place most where there is nothing to do. *"The selected pages
contain no images to compress"* on its own sounds like a refusal; followed by
*drawings and text 81 MB (57%)* it is an answer, and the answer is that this
command cannot help with that document.

## The trade-offs, one at a time

**It is lossy and irreversible, so it cannot be a preference.** Every other
save option we have — linearize, strip metadata, the password — is a decision
about how to *write* a file that is still fully present in memory. Ticking a
box that silently degrades every subsequent save is a different kind of thing,
and the difference is that you cannot get the pixels back. It belongs on a
command with a dialog and a stated result, asked each time, not on a sticky
setting. The corollary is that the existing checkbox should be renamed to what
it does — *Recompress streams and pack objects* — and the word *Compress* left
for the command that earns it.

**Where the change lands — [D25](../DECISIONS.md): a new temporary document.** The re-encoded
pages are written to a fresh temp PDF, registered through
`DocumentSet.get_doc`, and each affected page has its `nfile` and `copyname`
repointed at it. This is what `stamp.py`, `nup.py`, `booklet.py` and
`layers.py` already do with generated content, and it is the only one of the
three plausible designs that is honestly undoable.

The reason it has to be that one is not obvious, and the obvious
implementation is a trap:

- **At save time**, inside `export_doc`. Costs no temp space and matches
  Export ▸ Rasterized PDF, but leaves the user looking at thumbnails that are
  not what gets written, and puts a lossy operation somewhere undo cannot see
  it at all.
- **In the document, in place** — open the page's `copyname`, rewrite its
  image XObjects, save it back. **This silently breaks undo.** A snapshot is a
  shallow copy of every `Page`, and a `Page` is a *reference* into one of
  `DocumentSet`'s immutable temporary files plus a handful of numbers; no
  snapshot holds a single pixel. Every state on the stack, before and after,
  names that same path. Undo would faithfully restore page order, rotations
  and crops while the images stayed degraded — with the menu still offering
  "Undo Compress". For a lossy operation that is the worst failure available,
  and it is the version that gets written first.
- **In the document, as a new temporary document.** The snapshot's old
  `copyname` still names a file that is still there, so undo restores the
  pixels because it restores the reference. Chosen.

What it costs: **the original temporary file stays on disk for as long as any
undo state references it.** Compressing a 200 MB scan means both copies live
in the per-window temporary directory until the history is cleared. Disk
rather than memory, in a directory that is cleaned on exit — but it is real,
and it is the one argument the save-time design has going for it.

The gain is that "I can see it got worse" and "I can undo it" become the same
gesture, which is the whole reason a destructive operation is allowed near
this application at all.

Two details that fall out of the choice. **One new document per affected
source, with page indices preserved** — pages the user did not select are
copied across untouched — so `npage` needs no remapping and a partial
selection stays possible. And read mode shows the result either way: compress
a whole document and nothing else is edited, so `source_if_unmodified` still
recognises a 1:1 view and hands the reader the new temporary file directly;
compress part of one and the pages now span two documents, so the reader falls
back to exporting the edited list, as it does after any other edit. Both paths
show the compressed images, which is what someone checking the result is
looking for.

**Cancelling leaves the document entirely alone**, rather than compressed as
far as it got. Half a document lossy and half not is a state nobody asked for
and cannot be undone selectively, and refusing it costs nothing here: the work
exists only in memory until a new temporary document is written, so a cancel
is simply a decision not to write one. It follows from the choice above — the
save-time design would have had no such moment to stop at.

**Never make it bigger, and never make it worse for nothing.** Two rules the
implementation must carry, because the measurements show both failing
naturally: skip any image already at or below the target resolution, and if the
re-encoded stream is larger than the original, keep the original. A compressor
that can enlarge a file is worse than no compressor.

**Greyscale conversion is a real saving and a real risk.** It is the one
colour-model change worth offering. **CMYK is not** — converting to or from it
without an ICC path shifts colour in ways a page arranger has no business
causing, and PDF24 offering it does not make it wise.

**Formats that must be left alone rather than mangled.** JPXDecode, where a
re-encode needs a JPEG2000 encoder we would rather not depend on;
`/ImageMask true` stencils, which are tied to the fill colour and are not
images in the ordinary sense; DeviceN and Separation, which are ink channels
rather than colour; and any image with an `/SMask`, which either scales with
its parent or is left untouched with it. The correct behaviour for everything
in this list is to skip it and say so in the report, not to guess.
`pikepdf.PdfImage` exposes `indexed`, `is_device_n`, `is_separation`,
`image_mask` and `mode` precisely so this can be decided rather than assumed.

**CMYK and indexed images were on that list, and came off it by
measurement.** A 1,590-page technical handbook turned out to be four-fifths
those two — 2,031 CMYK JPEGs, 961 indexed palettes and 671 CMYK Flate images
in its first 400 pages — so skipping them meant touching 527 of its 34,390
images and leaving most of the document alone.

- **CMYK is re-encoded as CMYK**, so no colour space is converted and no ICC
  path is needed. The hazard was that Adobe stores CMYK JPEGs inverted, which
  fails as a colour negative rather than as an error, so ten images from that
  book were decoded, re-encoded and compared: worst channel drift 12 to 16 of
  255 at quality 90, mean under 1. Ordinary JPEG quantisation. An inversion
  would have read about 255. This is not the same thing as *converting* to
  CMYK, which stays out for the reason above.
- **Indexed images go back as indexed**, re-quantised and deflated, never as
  JPEG. They are nearly always diagrams, rules and flat colour, and JPEG rings
  around a hard edge. Measured on that book: a 1053×705 diagram 189,423 →
  129,739 bytes as a palette against 27,656 as JPEG, and a 945×1234 one
  112,897 → 23,973 against 8,814. JPEG is three to five times smaller and
  wrong for the content — and the same document holds thousands of 1036×4
  rules where JPEG turns 29 bytes into 759.

Together, on the whole book: **34,390 images, 141.4 MB down to 45.5 MB, 68%
smaller** — and the file itself from 260,688 KB to 151,712 KB, **41.8% off**.
19,759 images were re-encoded and 14,631 left alone, which sums to exactly the
34,390 the survey counted before any work began. The first 400 pages,
measured on their own beforehand, predicted 68% to the percentage point.

**Widen before resampling.** Pillow silently forces nearest-neighbour for
`P` and `1` images, because there is no meaningful average of two palette
indices — halfway between index 7 and index 9 is index 8, an unrelated
colour. Resizing one directly looks like it worked and quietly returns
nearest-neighbour, so an indexed image is converted to RGB first and a bilevel
one to grey, and only then resampled.

**Shared images are deduplicated by `objgen`, not by page.** Measured above:
eight visits, one object, 23/255 of avoidable generational loss.

**Rasterising the page is the wrong tool, and the issue says otherwise.**
[Issue #8](https://github.com/dwsdolce/pdfarranger-qt/issues/8) notes that "the
raster machinery is already here", which is true and misleading: `raster.py`
renders whole *pages*, so using it would convert vector text into pixels —
turning a crisp 0.75 MB text document into a fuzzy several-megabyte one, the
exact opposite of the request. This work is a per-image walk over XObject
resources with `pikepdf.PdfImage` and Pillow. The two share nothing but the
word *raster*.

## What this is deliberately not

Font un-embedding, which breaks documents on machines that lack the font.
Transparency flattening, which is a prepress operation. Discarding form fields
or annotations, which is data loss dressed as compression. OCR, which is
[D21](../DECISIONS.md) out of scope. All four are in Acrobat's Optimizer and none
belongs in a page arranger.
