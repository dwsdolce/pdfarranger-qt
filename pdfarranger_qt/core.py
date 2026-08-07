# Copyright (C) 2020 pdfarranger contributors
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

"""Toolkit-free page model.

``Sides``, ``Dims``, ``BasePage``, ``Page`` and ``LayerPage`` are carried over
from the GTK application essentially unchanged -- they are pure geometry and
bookkeeping.  ``PDFDoc`` is reimplemented on QtPdf instead of poppler-glib, and
``DocumentSet`` replaces the ``pdfqueue`` list plus the parts of ``PageAdder``
that were not entangled with GtkListStore.
"""

__all__ = [
    "Sides",
    "Dims",
    "BasePage",
    "Page",
    "LayerPage",
    "PDFDoc",
    "PDFDocError",
    "PasswordRequired",
    "DocumentSet",
    "img2pdf_supported_img",
]

import copy
import mimetypes
import os
import pathlib
import shutil
import tempfile
from typing import Callable, List, NamedTuple, Optional, Tuple, Union

import pikepdf
from PySide6.QtPdf import QPdfDocument

from .i18n import gettext_ as _

try:
    import img2pdf

    img2pdf.Image.init()
    img2pdf_supported_img = [
        i for i in img2pdf.Image.MIME.values() if i.split("/")[0] == "image"
    ]
except ImportError:  # pragma: no cover - optional dependency
    img2pdf_supported_img = []
    img2pdf = None

IMG2PDF_VERSION = "0.0.0" if img2pdf is None else img2pdf.__version__

Numeric = Union[float, int]

OVERLAY = "OVERLAY"
UNDERLAY = "UNDERLAY"


class Sides(NamedTuple):
    left: Numeric = 0
    right: Numeric = 0
    top: Numeric = 0
    bottom: Numeric = 0

    def __neg__(self) -> "Sides":
        """
        Pointwise unary minus

        Example:

        >>> -Sides(9, 3, 12, 6)
        Sides(left=-9, right=-3, top=-12, bottom=-6)
        """
        return Sides(*(-self[i] for i in range(4)))

    def __add__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise addition

        Example:

        >>> Sides(9, 3, 12, 6) + Sides(1, 2, 3, 4)
        Sides(left=10, right=5, top=15, bottom=10)
        >>> Sides(9, 3, 12, 6) + 1
        Sides(left=10, right=4, top=13, bottom=7)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] + other[i] for i in range(4)))
        return Sides(*(self[i] + other for i in range(4)))

    def __sub__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise subtraction

        Example:

        >>> Sides(9, 3, 12, 6) - Sides(1, 2, 3, 4)
        Sides(left=8, right=1, top=9, bottom=2)
        >>> Sides(9, 3, 12, 6) - 3
        Sides(left=6, right=0, top=9, bottom=3)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] - other[i] for i in range(4)))
        return Sides(*(self[i] - other for i in range(4)))

    def __mul__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise multiplication

        Example:

        >>> Sides(9, 3, 12, 6) * Sides(1, 2, 3, 4)
        Sides(left=9, right=6, top=36, bottom=24)
        >>> Sides(9, 3, 12, 6) * 3
        Sides(left=27, right=9, top=36, bottom=18)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] * other[i] for i in range(4)))
        return Sides(*(self[i] * other for i in range(4)))

    def __truediv__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise division

        Example:

        >>> Sides(9, 3, 12, 6) / Sides(1, 2, 3, 4)
        Sides(left=9.0, right=1.5, top=4.0, bottom=1.5)
        >>> Sides(9, 3, 12, 6) / 3
        Sides(left=3.0, right=1.0, top=4.0, bottom=2.0)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] / other[i] for i in range(4)))
        return Sides(*(self[i] / other for i in range(4)))

    def rotated(self, times: int) -> "Sides":
        """
        Rotate 90 degrees counter-clockwise 'times' times

        Examples:

        >>> Sides(9,3,12,6).rotated(1)
        Sides(left=12, right=6, top=3, bottom=9)
        >>> Sides(9,3,12,6).rotated(-3) == Sides(9,3,12,6).rotated(1)
        True
        """
        perm = (0, 2, 1, 3)
        return Sides(*(self[perm[(x + times) % 4]] for x in perm))

    def max(self, other: "Sides") -> "Sides":
        """
        Pointwise max

        Example:

        >>> Sides(1, 2, 3, 4).max(Sides(4, 3, 2, 1))
        Sides(left=4, right=3, top=3, bottom=4)
        """
        return Sides(*(max(self[i], other[i]) for i in range(4)))


class Dims(NamedTuple):
    width: Numeric
    height: Numeric

    def __neg__(self) -> "Dims":
        """
        Pointwise unary minus

        Example:

        >>> -Dims(612, 792)
        Dims(width=-612, height=-792)
        """
        return Dims(*(-self[i] for i in range(2)))

    def __add__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise addition

        Example:

        >>> Dims(612, 792) + Dims(612, 792)
        Dims(width=1224, height=1584)
        >>> Dims(612, 792) + 100
        Dims(width=712, height=892)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] + other[i] for i in range(2)))
        return Dims(*(self[i] + other for i in range(2)))

    def __sub__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise subtraction

        Example:

        >>> Dims(612, 792) - Dims(306, 396)
        Dims(width=306, height=396)
        >>> Dims(612, 792) - 100
        Dims(width=512, height=692)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] - other[i] for i in range(2)))
        return Dims(*(self[i] - other for i in range(2)))

    def __mul__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise multiplication

        Example:

        >>> Dims(612, 792) * Dims(0.5, 0.25)
        Dims(width=306.0, height=198.0)
        >>> Dims(612, 792) * 2
        Dims(width=1224, height=1584)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] * other[i] for i in range(2)))
        return Dims(*(self[i] * other for i in range(2)))

    def __truediv__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise division

        Example:

        >>> Dims(612, 792) / Dims(2, 4)
        Dims(width=306.0, height=198.0)
        >>> Dims(612, 792) / 2
        Dims(width=306.0, height=396.0)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] / other[i] for i in range(2)))
        return Dims(*(self[i] / other for i in range(2)))

    def flipped(self) -> "Dims":
        """Swap height and width"""
        return Dims(self.height, self.width)

    def scaled(self, factor: float) -> "Dims":
        """Scale by factor"""
        return Dims(self.width * factor, self.height * factor)

    def int_scaled(self, factor: float) -> "Dims":
        """Scale by factor and round to nearest int"""
        return Dims(int(self.width * factor + 0.5), int(self.height * factor + 0.5))

    def cropped(self, crop: Sides) -> "Dims":
        """Crop using crop array"""
        return Dims(
            self.width * (1 - crop.left - crop.right),
            self.height * (1 - crop.top - crop.bottom),
        )


class BasePage:
    """Common base class for Page and LayerPage"""

    def __init__(self, nfile, npage, copyname, angle, scale, crop: Sides, size_orig: Dims):
        self.nfile = nfile
        """The ID (from 1 to n) of the PDF file owning the page"""
        self.npage = npage
        """The ID (from 1 to n) of the page in its owner PDF document"""
        self.copyname = copyname
        """Filepath to the temporary stored file"""
        self.angle = angle
        self.scale = scale
        self.crop = crop
        """Left, right, top, bottom crop"""
        self.size_orig = size_orig
        """Width and height of the original page"""
        self.size = size_orig if angle in [0, 180] else size_orig.flipped()
        """Width and height"""

    def width_in_points(self) -> Numeric:
        """Return the page width in PDF points."""
        return self.size_in_points().width

    def height_in_points(self) -> Numeric:
        """Return the page height in PDF points."""
        return self.size_in_points().height

    def size_in_points(self) -> Dims:
        """Return the page size in PDF points."""
        return self.size.scaled(self.scale).cropped(self.crop)

    def size_in_mm(self) -> Dims:
        """Return the page size in mm."""
        return self.size_in_points() * 25.4 / 72

    @staticmethod
    def rotate_times(angle: int) -> int:
        """Convert an angle in degree to a number of 90 degree rotations."""
        return round((-angle / 90) % 4)


class Page(BasePage):
    """A page of the document being edited.

    A Page is a *reference* into one of the immutable temporary files held by
    ``DocumentSet``, plus the geometric edits applied to it.  Nothing is written
    until export, so every operation here is cheap.
    """

    def __init__(
        self,
        nfile,
        npage,
        copyname,
        angle=0,
        scale=1.0,
        crop: Sides = Sides(),
        hide: Sides = Sides(),
        size_orig: Dims = Dims(612, 792),
        description="",
        layerpages=(),
    ):
        super().__init__(nfile, npage, copyname, angle, scale, Sides(*crop), size_orig)
        self.hide = Sides(*hide)
        """Left, right, top, bottom hide"""
        self.description = description
        """The text under the thumbnail"""
        self.layerpages: List["LayerPage"] = list(layerpages)

    def __repr__(self):
        return (
            f"Page({self.nfile}, {self.npage}, '{self.copyname}', "
            f"{self.angle}, {self.scale}, {self.crop}, {self.hide}, "
            f"{self.size_orig}, '{self.description}', {self.layerpages})"
        )

    def rotate(self, angle: int) -> bool:
        rt = self.rotate_times(angle)
        if rt == 0:
            return False
        self.crop = self.crop.rotated(rt)
        self.hide = self.hide.rotated(rt)
        self.angle = (self.angle + int(angle)) % 360
        self.size = self.size_orig if self.angle in [0, 180] else self.size_orig.flipped()
        for lp in self.layerpages:
            lp.rotate(rt)
        return True

    def unmodified(self) -> bool:
        return (
            self.angle == 0
            and self.crop == Sides()
            and self.hide == Sides()
            and self.scale == 1
            and len(self.layerpages) == 0
        )

    def render_key(self, width: int) -> tuple:
        """Cache key identifying a rendered bitmap of this page."""
        return (self.copyname, self.npage, self.angle, self.crop, self.hide, width)

    def serialize(self) -> str:
        """Convert to string for copy/paste operations."""
        lpdata = [lp.serialize() for lp in self.layerpages]
        ts = [self.copyname, self.npage, self.description, self.angle, self.scale]
        ts += list(self.crop) + list(self.hide) + list(lpdata)
        return "///".join([str(v) for v in ts])

    def duplicate(self) -> "Page":
        r = copy.copy(self)
        r.layerpages = [lp.duplicate() for lp in r.layerpages]
        return r

    def split(self, vcrops, hcrops) -> List["Page"]:
        """Split this page into a grid and return all but the top-left page."""
        newpages = []
        left, right, top, bottom = self.crop
        # If the page is cropped, adjust the new crop for the visible part of the page.
        hscale = 1 - (left + right)
        vscale = 1 - (top + bottom)
        vcrops = [(l * hscale, r * hscale) for (l, r) in vcrops]
        hcrops = [(t * vscale, b * vscale) for (t, b) in hcrops]

        for (t, b) in reversed(hcrops):
            topcrop = top + t
            row_height = b - t
            bottomcrop = 1 - (topcrop + row_height)
            for (l, r) in reversed(vcrops):
                leftcrop = left + l
                col_width = r - l
                rightcrop = 1 - (leftcrop + col_width)
                crop = Sides(leftcrop, rightcrop, topcrop, bottomcrop)
                if l == 0.0 and t == 0.0:
                    # Update the original page
                    self.crop = crop
                else:
                    new = self.duplicate()
                    new.crop = crop
                    newpages.append(new)
        return newpages


class LayerPage(BasePage):
    """Page added as overlay or underlay on a Page."""

    def __init__(self, nfile, npage, copyname, angle, scale, crop, offset, laypos, size_orig: Dims):
        super().__init__(nfile, npage, copyname, angle, scale, Sides(*crop), size_orig)
        self.offset = Sides(*offset)
        """Left, right, top, bottom offset from dest page edges"""
        self.laypos = laypos
        """OVERLAY or UNDERLAY"""

    def __repr__(self):
        return (
            f"LayerPage({self.nfile}, {self.npage}, '{self.copyname}', {self.angle}, "
            f"{self.scale}, {self.crop}, {self.offset}, '{self.laypos}', {self.size_orig})"
        )

    def rotate(self, times: int):
        if times != 0:
            self.crop = self.crop.rotated(times)
            self.offset = self.offset.rotated(times)
            self.angle = (self.angle - 90 * times) % 360
            self.size = self.size if times % 2 == 0 else self.size.flipped()

    def serialize(self) -> str:
        ts = [self.copyname, self.npage, self.angle, self.scale, self.laypos]
        ts += list(self.crop) + list(self.offset)
        return "///".join([str(v) for v in ts])

    def duplicate(self) -> "LayerPage":
        return copy.copy(self)


class PDFDocError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class PasswordRequired(PDFDocError):
    """Raised when a document needs a password and none was supplied."""


def _img_to_pdf(images, tmp_dir, page_size=None) -> str:
    """Wrap img2pdf.convert and write the result to a temporary PDF."""
    if img2pdf is None:
        raise PDFDocError(_("Image files are only supported with img2pdf"))
    kwargs = {"rotation": img2pdf.Rotation.ifvalid}
    if page_size is not None:
        kwargs["layout_fun"] = img2pdf.get_layout_fun(page_size)
    try:
        pdf = img2pdf.convert(images, **kwargs)
    except ValueError as e:
        # Too small or too large image
        raise PDFDocError(str(e)) from e
    fd, pdf_file = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
    os.close(fd)
    with open(pdf_file, "wb") as f:
        f.write(pdf)
    return pdf_file


def make_tmp_file(tmp_dir) -> Tuple[pikepdf.Pdf, str]:
    """A new empty pikepdf document and the temporary path to save it under."""
    fd, filename = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
    os.close(fd)
    return pikepdf.Pdf.new(), filename


def create_blank_page(tmp_dir, size: Dims, npages: int = 1) -> str:
    """Write a temporary PDF of ``npages`` blank pages. Size is in PDF points."""
    pdf, filename = make_tmp_file(tmp_dir)
    pdf.add_blank_page(page_size=(size.width, size.height))
    for _i in range(npages - 1):
        pdf.pages.append(pdf.pages[0])
    pdf.save(filename)
    return filename


def hide_layer_margins(page: "Page", layerpages, hide: Sides):
    """Crop and offset layers that fall inside the hidden margin.

    Ported unchanged from the GTK application. Layers pushed entirely outside
    the visible area are dropped.
    """
    fully_hidden_layers = []
    for num, lp in enumerate(layerpages):
        scalex = (page.size.width * page.scale) / (lp.size.width * lp.scale)
        scaley = (page.size.height * page.scale) / (lp.size.height * lp.scale)
        sm = Sides(scalex, scalex, scaley, scaley)
        outside = Sides(*(max(0, hide[i] - lp.offset[i]) for i in range(4)))
        lp.crop += outside * sm
        lp.offset = Sides(*(max(lp.offset[i], hide[i]) for i in range(4)))
        if lp.crop.left + lp.crop.right >= 1 or lp.crop.top + lp.crop.bottom >= 1:
            fully_hidden_layers.append(num)
    for num in reversed(fully_hidden_layers):
        layerpages.pop(num)


_QPDF_ERRORS = {
    QPdfDocument.Error.FileNotFound: _("File not found"),
    QPdfDocument.Error.InvalidFileFormat: _("Invalid file format"),
    QPdfDocument.Error.DataNotYetAvailable: _("Data not yet available"),
    QPdfDocument.Error.UnsupportedSecurityScheme: _("Unsupported security scheme"),
}


class PDFDoc:
    """One source document.

    The source file is copied to a temporary directory on load and never
    touched again.  Both the export (pikepdf) and the render worker (QtPdf) read
    that copy, which is what makes it safe to overwrite the original on save.
    """

    def __init__(self, filename, tmp_dir, description=None, password="",
                 stat=None, blank_size=None):
        self.filename = os.path.abspath(filename)
        self.stat = stat
        self.blank_size = blank_size
        self.password = password or ""
        if description is None:  # When importing files
            self.basename = os.path.basename(filename)
        else:  # When copy-pasting
            self.basename = description.split("\n")[0]

        # MIME type for jp2 is missing in Python prior to 3.14
        mimetypes.add_type("image/jp2", ".jp2", strict=True)
        filemime = mimetypes.guess_type(self.filename, strict=False)[0]
        if not filemime:
            raise PDFDocError(_("Unknown file format") + ": " + filename)

        if filemime == "application/pdf":
            if self.filename.startswith(str(tmp_dir)) and description is None:
                # Already a file we own (e.g. an inserted blank page)
                self.copyname = self.filename
                self.basename = ""
            else:
                fd, self.copyname = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
                os.close(fd)
                shutil.copy(self.filename, self.copyname)
        elif filemime.split("/")[0] == "image":
            if img2pdf is None:
                raise PDFDocError(_("Image files are only supported with img2pdf") + ": " + filename)
            if mimetypes.guess_type(filename, strict=False)[0] not in img2pdf_supported_img:
                raise PDFDocError(_("Image format is not supported by img2pdf") + ": " + filename)
            self.copyname = _img_to_pdf([filename], tmp_dir)
        else:
            raise PDFDocError(_("File is neither pdf nor image") + ": " + filename)

        self.page_sizes: List[Dims] = []
        self._probe()

    def _probe(self):
        """Read page count and page sizes, validating the password."""
        doc = QPdfDocument(None)
        try:
            if self.password:
                doc.setPassword(self.password)
            err = doc.load(self.copyname)
            if err == QPdfDocument.Error.IncorrectPassword:
                raise PasswordRequired(self.copyname)
            if err != QPdfDocument.Error.None_:
                raise PDFDocError(
                    _QPDF_ERRORS.get(err, _("Cannot open document")) + ": " + self.filename
                )
            self.page_sizes = [
                Dims(s.width(), s.height())
                for s in (doc.pagePointSize(i) for i in range(doc.pageCount()))
            ]
        finally:
            doc.close()

    @property
    def n_pages(self) -> int:
        return len(self.page_sizes)


class DocumentSet:
    """Owns the temporary directory and the list of loaded source documents.

    Replaces the GTK application's ``pdfqueue`` list plus the file-handling half
    of ``PageAdder``.  Page ``nfile`` values are 1-based indexes into ``docs``.
    """

    def __init__(self):
        self._tmp_dir_obj = tempfile.TemporaryDirectory(prefix="pdfarranger-qt-")
        self.tmp_dir = self._tmp_dir_obj.name
        self.docs: List[PDFDoc] = []
        self._stat_cache = {}

    def cleanup(self):
        self.docs.clear()
        self._stat_cache.clear()
        try:
            self._tmp_dir_obj.cleanup()
        except OSError:
            pass

    def reset(self):
        """Drop all loaded documents but keep the temporary directory."""
        self.docs.clear()
        self._stat_cache.clear()

    def _file_key(self, filename):
        if filename not in self._stat_cache:
            s = os.stat(filename)
            self._stat_cache[filename] = (s.st_dev, s.st_ino, s.st_mtime)
        return self._stat_cache[filename]

    def get_doc(self, filename, description=None, blank_size=None,
                ask_password: Optional[Callable[[str], Optional[str]]] = None
                ) -> Tuple[PDFDoc, int, bool]:
        """Return ``(doc, nfile, created)`` for filename, loading it if needed.

        ``ask_password`` is called with the file's basename each time the
        password is rejected; returning None aborts with PasswordRequired.
        """
        for i, doc in enumerate(self.docs):
            if filename == doc.copyname:
                # A copy-pasted page: files in tmp_dir are never modified, so
                # matching names means matching content.
                return doc, i + 1, False

        key = self._file_key(filename)
        for i, doc in enumerate(self.docs):
            if key == doc.stat:
                return doc, i + 1, False

        password = ""
        while True:
            try:
                doc = PDFDoc(filename, self.tmp_dir, description=description,
                             password=password, stat=key, blank_size=blank_size)
                break
            except PasswordRequired:
                if ask_password is None:
                    raise
                password = ask_password(os.path.basename(filename))
                if password is None:
                    raise
        self.docs.append(doc)
        return doc, len(self.docs), True

    def add_file(self, filename, first=1, last=-1, description=None,
                 ask_password=None) -> List[Page]:
        """Load a file and return Page objects for the requested page range."""
        doc, nfile, _created = self.get_doc(filename, description,
                                            ask_password=ask_password)
        n_end = doc.n_pages
        n_start = min(n_end, max(1, first))
        if last != -1:
            n_end = max(n_start, min(n_end, last))

        shortname = os.path.splitext(doc.basename)[0]
        pages = []
        for npage in range(n_start, n_end + 1):
            desc = description if description is not None else f"{shortname}\npage {npage}"
            pages.append(
                Page(
                    nfile,
                    npage,
                    doc.copyname,
                    size_orig=doc.page_sizes[npage - 1],
                    description=desc,
                )
            )
        return pages

    def get_blank_doc(self, size: Dims, npages: int = 1) -> Tuple[str, int]:
        """Return ``(copyname, nfile)`` for a document of blank pages that size.

        Reuses an existing one if the set already holds a match, so hiding the
        margins of fifty same-sized pages creates one blank file, not fifty.
        """
        for i, doc in enumerate(self.docs):
            if doc.blank_size == size and doc.n_pages == npages:
                return doc.copyname, i + 1
        filename = create_blank_page(self.tmp_dir, size, npages)
        doc, nfile, _created = self.get_doc(filename, blank_size=size)
        return doc.copyname, nfile

    def make_layerpage(self, filename, npage, angle, scale, laypos,
                       crop: Sides, offset: Sides) -> LayerPage:
        """Build a LayerPage, loading its source document if necessary."""
        doc, nfile, _created = self.get_doc(filename)
        return LayerPage(nfile, npage, doc.copyname, angle, scale, crop, offset,
                         laypos, doc.page_sizes[npage - 1])

    def apply_hide(self, pages: List[Page]):
        """Turn each page's ``hide`` margins into real geometry, in place.

        Hiding is done without touching page content: the page *becomes* a
        full-size blank sheet, and its former content is laid on top as an
        overlay, cropped and inset by the hidden amount. Existing layers are
        cropped to match first.

        Mutates ``pages``, so callers must pass duplicates -- the GTK version
        does the same, immediately before export.
        """
        for page in pages:
            if all(page.hide[i] <= page.crop[i] for i in range(4)):
                continue
            hide_layer_margins(page, page.layerpages, page.hide)
            blank_name, nfile = self.get_blank_doc(page.size)
            # The old page content becomes the topmost layer. Its crop is the
            # hidden amount rather than page.crop: page.crop still applies, to
            # the blank sheet that is now the page itself.
            content = self.make_layerpage(page.copyname, page.npage, page.angle,
                                          page.scale, OVERLAY, page.hide, page.hide)
            page.layerpages.insert(0, content)
            page.nfile = nfile
            page.npage = 1
            page.copyname = blank_name
            page.hide = Sides()
            page.angle = 0

    def pages_from_clipboard(self, entries, ask_password=None) -> List[Page]:
        """Rebuild Page objects from parsed clipboard entries.

        Entries reference the originating instance's temporary files by path;
        loading them copies those files into this instance's own directory, so
        the pasted pages keep working after the other instance exits.
        """
        pages = []
        for entry in entries:
            if len(entry) == 2:  # short form: whole file, used when interleaving
                filename, npage = entry
                pages.extend(self.add_file(filename, npage, npage,
                                           ask_password=ask_password))
                continue
            filename, npage, description, angle, scale, crop, hide, layerdata = entry
            doc, nfile, _created = self.get_doc(filename, description=description,
                                                ask_password=ask_password)
            if not 0 < npage <= doc.n_pages:
                continue
            layerpages = [
                self.make_layerpage(lfile, lnpage, langle, lscale, laypos,
                                    Sides(*lcrop), Sides(*loffset))
                for lfile, lnpage, langle, lscale, laypos, lcrop, loffset in layerdata
            ]
            pages.append(Page(nfile, npage, doc.copyname, angle, scale,
                              Sides(*crop), Sides(*hide),
                              doc.page_sizes[npage - 1], description, layerpages))
        return pages

    def files_for_export(self) -> List[Tuple[str, str]]:
        """Return ``(copyname, password)`` pairs indexed by ``nfile - 1``.

        Call this *after* ``apply_hide()``: hiding can append a blank document.
        """
        return [(d.copyname, d.password) for d in self.docs]

    def source_names(self) -> List[str]:
        """Original basenames, indexed by ``nfile - 1``.

        Only the name, not the path: it exists to match the `/F` of a `/GoToR`
        link, which is relative to wherever the file used to live.
        """
        return [d.basename or "" for d in self.docs]

    def uri(self, nfile: int) -> str:
        return pathlib.Path(self.docs[nfile - 1].copyname).as_uri()
