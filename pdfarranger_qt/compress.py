# Copyright (C) 2026 pdfarranger-qt contributors
#
# pdfarranger is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""Making a PDF smaller by re-encoding the images inside it.

The save option that recompresses streams is a different operation and barely
moves a scanned document: measured, it recovers 0.0% on eight pages of 300 ppi
JPEG and 0.6% on a page of vector text, because both arrive already
compressed. What it *does* recover is what some other producer left
uncompressed -- 80% on the same text written with loose streams. This module
is the other half, the one people mean: re-encoding the images.

The numbers that set the defaults, all measured on eight letter pages of
rendered text at 300 ppi:

- 150 ppi at quality 75 takes 8.09 MB to 2.00 MB, and is where the curve stops
  paying -- below it the file shrinks by less than the page degrades.
- Quality alone at full resolution is worth 40%, which is why the target
  resolution is allowed to be None.
- A bilevel page as CCITT Group 4 is 0.52 MB at its full 300 ppi, against
  1.98 MB for the industry-default downsample to 144 ppi. Four times smaller,
  nothing thrown away. Nobody would think to ask for that, so it is automatic.
- A 96 ppi logo "resampled" to 144 ppi grows from 1,662 to 5,868 bytes and
  becomes lossy. Hence a threshold rather than a flat target, and hence the
  rule that an image is never replaced by a larger one.
- Resampling costs 110 ms a page with Lanczos against 35 ms with subsampling,
  so the resampling method is not a choice worth offering: always the best one.

Nothing here writes a file or touches the page list. It re-encodes image
XObjects inside a `pikepdf.Pdf` that the caller owns, and reports what it did.
Where the result lands is the caller's problem, and the answer is a new
temporary document, because an undo snapshot holds page references rather than
pixels: rewriting the file a page already points at would leave "Undo
Compress" restoring page order while the images stayed degraded.
"""

import io
import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pikepdf
from PIL import Image

from .core import DocumentSet, Page

#: The one resampling filter, per the measurement above.
RESAMPLE = Image.LANCZOS

#: What happened to an image.
DOWNSAMPLED = "downsampled"
RECODED = "recoded"          # same pixels, cheaper encoding
GROUP4 = "group4"            # bilevel, sent to CCITT Group 4
KEPT = "kept"

#: Why an image was kept. Symbols rather than sentences: this module has no
#: business owning translatable text, and the dialog has to phrase them for a
#: report anyway.
BELOW_TARGET = "below-target"
WOULD_GROW = "would-grow"
NOT_PLACED = "not-placed"
STENCIL = "stencil"
INK_CHANNELS = "ink-channels"
INDEXED = "indexed"
SOFT_MASK = "soft-mask"
UNSUPPORTED_FILTER = "unsupported-filter"
UNSUPPORTED_MODE = "unsupported-mode"
DECODE_FAILED = "decode-failed"

#: Pillow modes this knows how to re-encode. CMYK is deliberately absent:
#: Adobe's inverted CMYK JPEGs round-trip badly, and shifting colour is not
#: something a page arranger should do to somebody's document by accident.
ENCODABLE = ("RGB", "L", "1")

#: Preset names.
SCREEN, BALANCED, PRINT = "screen", "balanced", "print"

#: The two halves of the work, told apart so a caller can say which is
#: happening. They take wildly different times on different documents: a book
#: of many small images is nearly all scanning, a handful of full-page scans
#: nearly all encoding.
SCANNING, ENCODING, WRITING = "scanning", "encoding", "writing"


@dataclass(frozen=True)
class Settings:
    """What to do to each image.

    ``ppi`` of None means "leave the resolution alone and only re-encode",
    which is the 40%-for-free case.
    """

    ppi: Optional[int] = 150
    #: Only touch images above this many ppi. None means 1.5x ``ppi`` -- the
    #: threshold exists so that a logo placed at its natural size is left
    #: alone rather than made larger and lossy.
    above: Optional[float] = None
    quality: int = 75
    greyscale: bool = False

    @property
    def threshold(self) -> Optional[float]:
        if self.above is not None:
            return self.above
        return None if self.ppi is None else self.ppi * 1.5


#: The levels worth offering as one click. Named for the destination rather
#: than the strength, so the choice can be made without knowing what a ppi is.
PRESETS = {
    SCREEN: Settings(ppi=100, quality=60),
    BALANCED: Settings(ppi=150, quality=75),
    PRINT: Settings(ppi=None, quality=90),
}


@dataclass
class Outcome:
    """What became of one image object."""

    objgen: Tuple[int, int]
    before: int
    after: int
    action: str
    reason: str = ""
    #: Pixel size as it now stands.
    size: Tuple[int, int] = (0, 0)
    #: The largest size it is drawn at, in points, and the resolution that
    #: implies. Zero when the image is never actually painted.
    drawn: Tuple[float, float] = (0.0, 0.0)
    ppi: float = 0.0

    @property
    def saved(self) -> int:
        return self.before - self.after


@dataclass
class Result:
    outcomes: List[Outcome] = field(default_factory=list)
    #: The caller's progress callback asked to stop. Nothing is applied when
    #: this is set: a cancelled compression leaves the document alone rather
    #: than half done, because "some of your pages are now lossy" is not a
    #: state anybody asked for.
    stopped: bool = False

    @property
    def images(self) -> int:
        return len(self.outcomes)

    @property
    def changed(self) -> int:
        return sum(1 for o in self.outcomes if o.action != KEPT)

    @property
    def before(self) -> int:
        return sum(o.before for o in self.outcomes)

    @property
    def after(self) -> int:
        return sum(o.after for o in self.outcomes)

    @property
    def saved(self) -> int:
        return self.before - self.after

    @property
    def fraction(self) -> float:
        """Saved, as a fraction of what the images cost to begin with."""
        return self.saved / self.before if self.before else 0.0


# --------------------------------------------------------------- placement
#
# An image's resolution is not a property of the image: 1000 pixels drawn
# across half a page is twice the resolution of the same 1000 pixels drawn
# across all of it. So the threshold cannot be applied without knowing how big
# each image is *painted*, which means walking the content stream and keeping
# the transformation matrix as the page does.
#
# Matrices are plain 6-tuples here rather than `pikepdf.Matrix`, so that the
# multiplication order is written down in one place and can be tested, instead
# of being an assumption about somebody else's operator overloading.

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: Deep enough for real documents; a cycle would otherwise be unbounded.
_MAX_FORM_DEPTH = 12


def multiply(m: Sequence[float], n: Sequence[float]) -> Tuple[float, ...]:
    """``m`` then ``n``, which is the order `cm` composes in."""
    a, b, c, d, e, f = (float(x) for x in m)
    a2, b2, c2, d2, e2, f2 = (float(x) for x in n)
    return (a * a2 + b * c2,
            a * b2 + b * d2,
            c * a2 + d * c2,
            c * b2 + d * d2,
            e * a2 + f * c2 + e2,
            e * b2 + f * d2 + f2)


def drawn_size(ctm: Sequence[float]) -> Tuple[float, float]:
    """How big the unit square comes out, in points.

    An image is always drawn into the unit square, so its painted size is
    whatever the matrix does to that square's edges. Lengths rather than the
    raw a and d, so a rotated placement measures correctly.
    """
    a, b, c, d = (float(x) for x in ctm[:4])
    return math.hypot(a, b), math.hypot(c, d)


def _resources(obj) -> Optional[pikepdf.Dictionary]:
    try:
        resources = obj.Resources
    except (AttributeError, KeyError):
        return None
    return resources if isinstance(resources, pikepdf.Dictionary) else None


def placements(page, depth: int = 0, ctm: Sequence[float] = IDENTITY,
               resources=None, found: Optional[Dict] = None) -> Dict:
    """The largest painted size of every image on ``page``, by ``objgen``.

    Largest, because an image drawn twice has to survive its most demanding
    use: shrinking it to suit the thumbnail would wreck the full-page copy.

    Recurses into form XObjects, which is where scanners and page-composition
    tools alike put images, applying each form's own `/Matrix` on the way in.
    """
    if found is None:
        found = {}
    if depth > _MAX_FORM_DEPTH:
        return found
    if resources is None:
        resources = _resources(page)
    xobjects = None
    if resources is not None:
        try:
            xobjects = resources.XObject
        except (AttributeError, KeyError):
            xobjects = None

    stack: List[Sequence[float]] = []
    current = tuple(float(x) for x in ctm)
    try:
        instructions = pikepdf.parse_content_stream(page)
    except (pikepdf.PdfError, ValueError, TypeError):
        return found  # a malformed content stream tells us nothing

    for operands, operator in instructions:
        op = str(operator)
        if op == "q":
            stack.append(current)
        elif op == "Q":
            current = stack.pop() if stack else tuple(float(x) for x in ctm)
        elif op == "cm" and len(operands) == 6:
            current = multiply([float(x) for x in operands], current)
        elif op == "Do" and operands and xobjects is not None:
            name = str(operands[0])
            try:
                target = xobjects[name]
            except (KeyError, TypeError):
                continue
            subtype = str(target.get("/Subtype", ""))
            if subtype == "/Image":
                width, height = drawn_size(current)
                previous = found.get(target.objgen, (0.0, 0.0))
                found[target.objgen] = (max(previous[0], width),
                                        max(previous[1], height))
            elif subtype == "/Form":
                inner = current
                matrix = target.get("/Matrix")
                if matrix is not None and len(matrix) == 6:
                    inner = multiply([float(x) for x in matrix], current)
                placements(target, depth + 1, inner,
                           _resources(target) or resources, found)
    return found


def effective_ppi(pixels: int, points: float) -> float:
    """Resolution as painted: pixels across, over inches across."""
    if points <= 0:
        return 0.0
    return pixels * 72.0 / points


# ------------------------------------------------------------------ images


def images_of(page) -> Dict[str, pikepdf.Object]:
    try:
        return dict(page.get_images())
    except AttributeError:      # pikepdf < 9
        return dict(page.images)
    except (pikepdf.PdfError, ValueError):
        return {}


def _stream_length(obj) -> int:
    """How many bytes this stream occupies, from `/Length` where possible.

    Reading the raw bytes to measure them means pulling every image in the
    document off disk: on a 1,590-page book with 34,390 images that is 141 MB
    of I/O to answer a question the dictionary already answers.
    """
    try:
        return int(obj.Length)
    except Exception:
        pass
    try:
        return len(obj.read_raw_bytes())
    except Exception:
        return 0


def survey(pdf: pikepdf.Pdf,
           pages: Optional[Iterable[int]] = None) -> Tuple[int, int]:
    """``(images, bytes)`` as things stand -- no decoding, no re-encoding.

    Cheap enough to run while a dialog is opening, which is the point: half of
    why a compress option looks broken is that nobody can see their 8 MB is
    7.9 MB of JPEG.
    """
    seen: Dict[Tuple[int, int], int] = {}
    for number in _page_numbers(pdf, pages):
        for obj in images_of(pdf.pages[number]).values():
            seen.setdefault(obj.objgen, _stream_length(obj))
    return len(seen), sum(seen.values())


def _page_numbers(pdf, pages) -> List[int]:
    if pages is None:
        return list(range(len(pdf.pages)))
    return [n for n in pages if 0 <= n < len(pdf.pages)]


def _bilevel(image: Image.Image, pdf_image) -> bool:
    """Two colours and nothing between them.

    One bit deep says so outright. An 8-bit greyscale scan of line art is the
    interesting case: it is bilevel in everything but storage, and it is where
    Group 4 turns 1.98 MB into 0.52 MB.
    """
    if pdf_image.bits_per_component == 1 or image.mode == "1":
        return True
    if image.mode != "L":
        return False
    colours = image.getcolors(maxcolors=2)
    return colours is not None and len(colours) <= 2


def to_bilevel(image: Image.Image) -> Image.Image:
    """Threshold, never dither.

    `convert("1")` applies Floyd-Steinberg, and that noise is the worst input
    Group 4 can be given: the same page came out at 4.60 MB dithered against
    0.52 MB thresholded, a nine-fold penalty for a one-word default.
    """
    grey = image if image.mode == "L" else image.convert("L")
    return grey.point(lambda value: 255 if value >= 128 else 0, mode="1")


def group4(image: Image.Image) -> bytes:
    """CCITT Group 4 payload, taken out of a TIFF Pillow writes for us.

    Pillow has no PDF-shaped Group 4 encoder, but its libtiff does, and the
    strip of a single-strip TIFF *is* the CCITTFaxDecode payload. The wheel
    carries its own libtiff, so this survives freezing.

    ``RowsPerStrip`` is forced to the full height, and that is not tidiness.
    Left alone, libtiff writes strips of about 8 KB -- five of them for a
    letter page at 300 ppi, breaking at row 409 -- and **every strip restarts
    the Group 4 coder with a fresh reference line**. Concatenated, the first
    strip decodes perfectly and everything after it is noise, which is a
    failure no size assertion can see: the payload compresses exactly as well
    either way. One strip, one continuous coding, one payload.
    """
    buffer = io.BytesIO()
    image.save(buffer, "TIFF", compression="group4",
               tiffinfo={278: image.height})
    written = buffer.getvalue()
    tiff = Image.open(io.BytesIO(written))
    offsets = tiff.tag_v2[273]
    counts = tiff.tag_v2[279]
    return b"".join(written[o:o + c] for o, c in zip(offsets, counts))


#: `/BlackIs1` for a payload from `group4`, determined by decoding one back
#: rather than by reading the specification.
#:
#: The TIFF Pillow writes tags itself PhotometricInterpretation 1, BlackIsZero,
#: which says a zero sample is black and therefore says `BlackIs1` should be
#: false. Decoded, that comes out as a photographic negative: with the flag
#: true a black top half reads back as a black top half, and with it false the
#: image inverts. libtiff's fax codec works in the fax convention whatever the
#: tag claims. A wrong value here compresses exactly as well and renders
#: inside out, which is why a round-trip test guards it rather than a size
#: assertion.
BLACK_IS_1 = True


def raw_filters(obj) -> List[str]:
    """The `/Filter` entry as a list of names, without decoding anything.

    Read straight off the dictionary because `pikepdf.PdfImage` refuses to be
    constructed on some of what it will find -- a JPEG 2000 stream among them
    -- and "this filter is not one we handle" has to be answerable before that
    point or it comes back as a decode failure and tells the user nothing.
    """
    entry = obj.get("/Filter")
    if entry is None:
        return []
    if isinstance(entry, pikepdf.Array):
        return [str(name) for name in entry]
    return [str(entry)]


def _skip_reason(obj, pdf_image) -> Optional[str]:
    """Why this image must be left alone, or None if it may be touched."""
    if pdf_image.image_mask:
        # Belt and braces: `Page.get_images()` does not offer image masks at
        # all, so this is only reachable through pikepdf 8's `Page.images`.
        return STENCIL          # tied to the fill colour; not an image as such
    if pdf_image.is_device_n or pdf_image.is_separation:
        return INK_CHANNELS     # ink channels, not colour
    if pdf_image.indexed:
        return INDEXED          # resampling would interpolate palette indices
    if "/SMask" in obj or "/Mask" in obj:
        return SOFT_MASK        # scales with its parent or not at all
    return None


def _target_pixels(width: int, drawn: Tuple[float, float],
                   settings: Settings) -> Optional[int]:
    """The width this image should come out at, or None to leave it.

    Answered from the stored pixel width and the painted size, so that an
    image already below the target never has to be decoded to find that out.
    """
    if settings.ppi is None or not drawn or drawn[0] <= 0:
        return None
    current = effective_ppi(width, drawn[0])
    threshold = settings.threshold
    if threshold is not None and current <= threshold:
        return None
    if settings.ppi >= current:
        return None
    return max(1, round(width * settings.ppi / current))


def _may_be_bilevel(obj, pdf_image) -> bool:
    """Whether Group 4 is worth decoding this image to consider.

    One bit deep says so outright. Eight-bit grey might be line art in
    disguise -- the case Group 4 turns 1.98 MB into 0.52 MB -- and only a
    decode can tell, so grey is admitted and colour is not. An image already
    stored as Group 4 has nowhere better to go.
    """
    if "/CCITTFaxDecode" in raw_filters(obj):
        return False
    if pdf_image.bits_per_component == 1:
        return True
    try:
        return pdf_image.mode in ("L", "1")
    except Exception:
        return False


def _target_size(image: Image.Image, drawn: Tuple[float, float],
                 settings: Settings) -> Optional[Tuple[int, int]]:
    """The pixel size this image should come out at, or None to leave it."""
    if settings.ppi is None:
        return None
    width_pt, height_pt = drawn
    if width_pt <= 0 or height_pt <= 0:
        return None
    current = effective_ppi(image.width, width_pt)
    threshold = settings.threshold
    if threshold is not None and current <= threshold:
        return None
    scale = settings.ppi / current
    if scale >= 1.0:
        return None
    return (max(1, round(image.width * scale)),
            max(1, round(image.height * scale)))


def compress(pdf: pikepdf.Pdf, settings: Settings = Settings(),
             pages: Optional[Iterable[int]] = None,
             progress: Optional[Callable[[str, int, int], bool]] = None
             ) -> Result:
    """Re-encode the images in ``pdf``, in place, and say what happened.

    ``pages`` is a list of zero-based page numbers, or None for all of them.
    Images shared between pages are done once: they are deduplicated by
    ``objgen``, because doing it per page re-encodes the same picture eight
    times for eight pages and costs 23/255 of avoidable generational loss.

    ``progress`` is called as ``(phase, done, total)`` and may return False to
    stop. **Both** phases report, and that is not decoration: finding out how
    large each image is painted means parsing every page's content stream, and
    on a 1,590-page book that is 155 seconds before a single image has been
    touched. Reporting only the second phase leaves the window saying "Not
    Responding" for two and a half minutes with nothing drawn, because a
    progress dialog that never gets its first value is never shown.
    """
    result = Result()
    numbers = _page_numbers(pdf, pages)

    where: Dict[Tuple[int, int], Tuple[float, float]] = {}
    todo = []
    done = set()
    for index, number in enumerate(numbers):
        if progress is not None and progress(SCANNING, index, len(numbers)) is False:
            result.stopped = True
            return result
        page = pdf.pages[number]
        images = images_of(page)
        if not images:
            continue        # nothing to place, so nothing to parse it for
        for objgen, size in placements(page).items():
            previous = where.get(objgen, (0.0, 0.0))
            where[objgen] = (max(previous[0], size[0]),
                             max(previous[1], size[1]))
        for obj in images.values():
            if obj.objgen not in done:
                done.add(obj.objgen)
                todo.append(obj)

    for index, obj in enumerate(todo):
        if progress is not None and progress(ENCODING, index, len(todo)) is False:
            result.stopped = True
            break
        result.outcomes.append(_one(obj, where.get(obj.objgen), settings))
    return result


def _one(obj, drawn: Optional[Tuple[float, float]],
         settings: Settings) -> Outcome:
    before = _stream_length(obj)
    outcome = Outcome(obj.objgen, before, before, KEPT,
                      drawn=drawn or (0.0, 0.0))

    if "/JPXDecode" in raw_filters(obj):
        outcome.reason = UNSUPPORTED_FILTER
        return outcome

    try:
        pdf_image = pikepdf.PdfImage(obj)
    except Exception:
        outcome.reason = DECODE_FAILED
        return outcome

    outcome.size = (pdf_image.width, pdf_image.height)
    if drawn and drawn[0] > 0:
        outcome.ppi = effective_ppi(pdf_image.width, drawn[0])

    reason = _skip_reason(obj, pdf_image)
    if reason:
        outcome.reason = reason
        return outcome
    if not drawn or drawn[0] <= 0:
        # Never painted, so there is no resolution to judge it against.
        outcome.reason = NOT_PLACED
        return outcome

    # Decide from the dictionary before decoding anything. A document can hold
    # tens of thousands of small images -- 34,390 in a 1,590-page handbook --
    # and decoding every one of them to discover it is already smaller than
    # the target is most of the cost of the whole operation.
    # Only when a resolution was actually asked for: with ppi None every image
    # is re-encoded where it stands, which is the 40%-for-free case and must
    # not be skipped for having nothing to shrink.
    wanted = _target_pixels(pdf_image.width, drawn, settings)
    if (settings.ppi is not None and wanted is None
            and not _may_be_bilevel(obj, pdf_image)):
        outcome.reason = BELOW_TARGET
        return outcome

    try:
        image = pdf_image.as_pil_image()
        image.load()
    except Exception:
        outcome.reason = DECODE_FAILED
        return outcome

    if image.mode not in ENCODABLE:
        outcome.reason = UNSUPPORTED_MODE
        return outcome

    target = _target_size(image, drawn, settings)
    bilevel = _bilevel(image, pdf_image)

    if target is None and not bilevel and settings.ppi is not None:
        # Already at or below what was asked for, and no cheaper encoding to
        # move it to.
        outcome.reason = BELOW_TARGET
        return outcome

    if target is not None:
        image = image.resize(target, RESAMPLE)

    if bilevel:
        data, encoding = _encode_group4(image)
    else:
        data, encoding = _encode_jpeg(image, settings)
    if data is None:
        outcome.reason = DECODE_FAILED
        return outcome

    if len(data) >= before:
        # A compressor that can enlarge a file is worse than no compressor.
        outcome.reason = WOULD_GROW
        return outcome

    _write(obj, data, encoding, image)
    outcome.after = len(data)
    outcome.size = (image.width, image.height)
    outcome.ppi = effective_ppi(image.width, drawn[0])
    if encoding[0] == GROUP4:
        outcome.action = GROUP4
    elif target is not None:
        outcome.action = DOWNSAMPLED
    else:
        outcome.action = RECODED
    return outcome


def _encode_group4(image: Image.Image):
    bilevel = to_bilevel(image)
    try:
        return group4(bilevel), (GROUP4, bilevel)
    except Exception:
        return None, None


def _encode_jpeg(image: Image.Image, settings: Settings):
    if settings.greyscale and image.mode != "L":
        image = image.convert("L")
    elif image.mode == "1":
        image = image.convert("L")
    buffer = io.BytesIO()
    try:
        image.save(buffer, "JPEG", quality=settings.quality, optimize=True)
    except Exception:
        return None, None
    return buffer.getvalue(), (RECODED, image)


def _write(obj, data: bytes, encoding, image: Image.Image):
    """Replace the stream and the keys that describe it.

    `/Decode` has to go: it is an inversion or remapping of the *old* samples,
    and applying it to newly encoded ones would show a negative.
    """
    kind, encoded = encoding
    if kind == GROUP4:
        obj.write(data, filter=pikepdf.Name.CCITTFaxDecode,
                  decode_parms=pikepdf.Dictionary(
                      K=-1, Columns=encoded.width, Rows=encoded.height,
                      BlackIs1=BLACK_IS_1))
        obj.Width, obj.Height = encoded.width, encoded.height
        obj.ColorSpace = pikepdf.Name.DeviceGray
        obj.BitsPerComponent = 1
    else:
        obj.write(data, filter=pikepdf.Name.DCTDecode)
        obj.Width, obj.Height = encoded.width, encoded.height
        obj.BitsPerComponent = 8
        if encoded.mode == "L":
            obj.ColorSpace = pikepdf.Name.DeviceGray
        elif encoded.mode == "RGB" and _colourspace_components(obj) != 3:
            # Only overwrite a colour space that no longer describes the
            # samples: an ICCBased RGB space still does, and replacing it with
            # /DeviceRGB would throw the profile away for nothing.
            obj.ColorSpace = pikepdf.Name.DeviceRGB
    if "/Decode" in obj:
        del obj["/Decode"]


# ------------------------------------------------------- the page list (D25)


def apply(pages: Sequence[Page], docs: DocumentSet,
          settings: Settings = Settings(),
          progress: Optional[Callable[[int, int], bool]] = None) -> Result:
    """Compress the images ``pages`` use, and point those pages at the result.

    The re-encoded pages go into a **new** temporary document, registered with
    the document set, and each page has its ``nfile`` and ``copyname`` moved to
    it. That is not bookkeeping: an undo snapshot is a shallow copy of `Page`
    objects, and a `Page` is a reference into an immutable temporary file plus
    a handful of numbers, so it holds no pixels. Rewriting the images inside
    the file a page already points at would leave every state on the undo
    stack naming that same path -- Undo would restore page order, rotation and
    crop while the images stayed degraded, with the menu still offering "Undo
    Compress". Writing a new file and moving the reference is what makes undo
    restore the pixels, and it is what `stamp`, `nup`, `booklet` and `layers`
    already do with content they generate.

    The cost is disk: the original stays for as long as an undo state names
    it, so this is two copies in the temporary directory until the history is
    cleared.

    One new document per source document, page indices preserved -- pages the
    caller did not pass are copied across untouched -- so ``npage`` needs no
    remapping and compressing part of a document works.

    Mutates ``pages`` in place, like `stamp.apply`. The caller commits an undo
    state first.
    """
    from .export import SaveOptions  # heavy, and only needed here

    total = Result()
    by_source: Dict[int, List[Page]] = {}
    for page in pages:
        by_source.setdefault(page.nfile, []).append(page)

    for nfile, group in sorted(by_source.items()):
        if not 0 < nfile <= len(docs.docs):
            continue
        doc = docs.docs[nfile - 1]
        wanted = sorted({page.npage - 1 for page in group})
        with pikepdf.open(doc.copyname, password=doc.password) as pdf:
            result = compress(pdf, settings, pages=wanted, progress=progress)
            total.outcomes.extend(result.outcomes)
            if result.stopped:
                # Cancelled: write nothing and move nothing, here or for any
                # document after this one. Half a document compressed is not
                # a state to leave somebody in, and it is only avoidable
                # because the work so far exists in memory rather than on disk.
                total.stopped = True
                return total
            if not result.changed:
                continue        # nothing to point at a new file for
            # Announced, because it is not instant and it is the last thing
            # that happens: writing a 141 MB book with every stream
            # recompressed takes long enough that a bar frozen at its last
            # image reads as a hang. Not cancellable -- the pages are already
            # re-encoded in memory, and there is nothing to gain by throwing
            # the work away at the door.
            if progress is not None:
                progress(WRITING, 0, 1)
            handle, path = tempfile.mkstemp(suffix=".pdf", dir=docs.tmp_dir)
            os.close(handle)
            pdf.save(path, **SaveOptions(compress=True).save_kwargs())

        # Already inside tmp_dir, so `PDFDoc` adopts it rather than copying.
        # Also not instant: it reopens the file to read every page's size.
        if progress is not None:
            progress(WRITING, 1, 1)
        _doc, new_nfile, _created = docs.get_doc(path)
        _repoint(group, doc.copyname, new_nfile,
                 docs.docs[new_nfile - 1].copyname)
    return total


def survey_pages(pages: Sequence[Page], docs: DocumentSet) -> Tuple[int, int]:
    """``(images, bytes)`` for what ``pages`` use, without re-encoding a thing.

    What the dialog opens with. Keyed by document *and* object, because an
    object number means nothing outside the file it came from.
    """
    seen: Dict[Tuple[int, Tuple[int, int]], int] = {}
    by_source: Dict[int, List[Page]] = {}
    for page in pages:
        by_source.setdefault(page.nfile, []).append(page)

    for nfile, group in sorted(by_source.items()):
        if not 0 < nfile <= len(docs.docs):
            continue
        doc = docs.docs[nfile - 1]
        try:
            pdf = pikepdf.open(doc.copyname, password=doc.password)
        except pikepdf.PdfError:
            continue
        with pdf:
            for number in sorted({page.npage - 1 for page in group}):
                if not 0 <= number < len(pdf.pages):
                    continue
                for obj in images_of(pdf.pages[number]).values():
                    seen.setdefault((nfile, obj.objgen), _stream_length(obj))
    return len(seen), sum(seen.values())


def human_size(count: int) -> str:
    """Bytes as somebody would say them.

    The units are left untranslated: kB and MB are written the same way in
    every language this ships in, and three msgids for them would cost 99
    translations to say nothing.
    """
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} MB"
    if count >= 1_000:
        return f"{count / 1_000:.0f} kB"
    return f"{count} B"


def _repoint(pages: Iterable[Page], old: str, nfile: int, copyname: str):
    """Move pages, and any layers drawn from the same file, to the new one.

    A layer is a reference of the same shape, so one left behind would keep
    painting the uncompressed original on top of the compressed page.
    """
    for page in pages:
        page.nfile = nfile
        page.copyname = copyname
        for layer in page.layerpages:
            if layer.copyname == old:
                layer.nfile = nfile
                layer.copyname = copyname


def _colourspace_components(obj) -> int:
    """How many channels the declared colour space has, or 0 if unreadable."""
    space = obj.get("/ColorSpace")
    if space is None:
        return 0
    name = str(space)
    if name in ("/DeviceRGB", "/CalRGB"):
        return 3
    if name in ("/DeviceGray", "/CalGray"):
        return 1
    if name == "/DeviceCMYK":
        return 4
    try:
        if str(space[0]) == "/ICCBased":
            return int(space[1].N)
    except Exception:
        pass
    return 0
