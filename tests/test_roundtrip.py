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

"""Open a document, write a copy, and check that nothing changed.

The standard is the owner's: make the markup and lose nothing. Reading a
document and writing it back is the weakest thing this application can do to
a file, so any difference it produces is a difference nobody asked for. That
makes this a wider net than any test of a single tool -- it covers every
annotation in every fixture, including the kinds no tool of ours will ever
make -- and it needs no window and no gesture to run.

Every fixture under ``tests/fixtures`` goes through, recursively. A document
with no annotations still exercises the save; a document with 180 of them is
where the detail is.

Two kinds of difference are set aside as not being values at all:

``/StructParent`` is an index into the structure tree's number tree, and the
tree is rebuilt, so the index is renumbered by construction.

``/Length``, ``/Filter`` and ``/DecodeParms`` describe how a stream is
encoded, not what it draws. qpdf compresses what it writes, so an appearance
stream that came in uncompressed goes out Flate-encoded with a different
length and identical content. The comparison hashes *decoded* bytes, which is
the thing that has to survive.

``/P`` is *not* set aside, and was the reason this test was written. It is an
indirect reference to the annotation's own page, and until 2026-10-31 every
exported document got it wrong: 164 annotations across these fixtures arrived
with every ``/P`` resolving and left with all 164 aimed at an orphaned copy
of the page. Copying an annotation copies the page it names, and the
passenger that came with it was not the page the output's tree held. Since a
reference to a page is compared here by which page it is, a ``/P`` that lands
anywhere else now fails this test rather than being excused by it.

Nothing here prints what anybody wrote. The comparison reads every key,
including ``/Contents`` and field values, because a lost one is exactly what
this is looking for -- but a failure reports a page number, a subtype and a
digest, so a document with real names in it can be a fixture.
"""

import glob
import hashlib
import io
import os
import unittest

import pikepdf
from support import FIXTURES, temp_path

#: Not values at all: an index into a rebuilt tree, and stream encoding.
NOT_A_VALUE = ("/StructParent", "/Length", "/Filter", "/DecodeParms")

#: References that point back up the structure instead of down into it. A
#: page names its annotations and a field names its widgets; the annotation
#: and the widget name them straight back. Expanding one of these walks back
#: over everything the walk has already covered -- and from a widget it
#: climbs to the root field and then back down through every branch, so each
#: annotation ends up carrying a serialisation of the whole document. One
#: corpus form came to five megabytes per annotation and 32 GiB in all.
#: Compared by *which* object they name instead, which is the only thing they
#: are there to say.
UPWARD = ("/P", "/Parent")

#: A guard against a malformed document, not a working limit. With the
#: upward references compared by name the graph has no cycles left, so
#: nothing should come near this -- and a test below fails if anything does.
_MAX_DEPTH = 64


def _pages_by_object(pdf):
    """Which page index each page object is, so a reference can mean one."""
    return {page.obj.objgen: index for index, page in enumerate(pdf.pages)}


def _stream_digest(stream):
    """The bytes a stream means, not the bytes it is stored as.

    An image whose filter pikepdf cannot decode falls back to the stored
    bytes, which is still a fair comparison as long as both sides fall back
    the same way.
    """
    try:
        data = stream.read_bytes()
    except Exception:  # noqa: BLE001 - an undecodable filter is still data
        data = stream.read_raw_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


class Canon:
    """Canonical text for the objects of one document.

    Object numbers are assigned afresh by any save, so they cannot be
    compared. What can be compared is what an object *is*: its keys, by
    value, all the way down, with a reference to a page or a field rendered
    as which page or which field it names.

    Each object is reduced to a digest and composed by digest, so an
    annotation's text stays a few hundred bytes however large the document
    is, and every object is canonicalised once however many annotations
    reach it. Both of those were learned the hard way from a 136-page form:
    expanded in full and recomputed per annotation, the same comparison
    wanted 32 GiB and about three hours.
    """

    def __init__(self, pdf):
        self.pages = _pages_by_object(pdf)
        self.fields = self._fields_by_object(pdf)
        self._memo = {}
        #: Every place the guards fired. Expected to stay empty.
        self.guarded = []

    @staticmethod
    def _fields_by_object(pdf):
        """Each field object as its position in the document's field tree.

        Enumerated by climbing from the annotations in page order, so the
        numbering depends only on the order the document presents its marks
        in -- which is itself compared. Two widgets that shared a parent
        before the save share one after it if and only if they report the
        same number here, which is what keeps a radio group one group.
        """
        order = {}
        for page in pdf.pages:
            for annot in page.obj.get(pikepdf.Name.Annots) or []:
                node, climbed = annot, 0
                while climbed < _MAX_DEPTH:
                    parent = node.get(pikepdf.Name.Parent)
                    if parent is None:
                        break
                    order.setdefault(parent.objgen, len(order))
                    node, climbed = parent, climbed + 1
        return order

    def of(self, obj):
        """The canonical text of one object, as a digest of its contents."""
        return self._value(obj, frozenset(), 0)

    def _named(self, target):
        """An upward reference, as the thing it names rather than its value."""
        if target is None:
            return "null"
        identity = getattr(target, "objgen", (0, 0))
        if identity in self.pages:
            return f"page:{self.pages[identity]}"
        if identity in self.fields:
            return f"field:{self.fields[identity]}"
        # Neither a page of this document nor one of its fields. This is what
        # a dangling /P looked like: a reference that resolves to a perfectly
        # good dictionary which simply is not in the page tree any more.
        return "orphan"

    def _value(self, obj, seen, depth):
        if depth > _MAX_DEPTH:
            self.guarded.append("depth")
            return "<deep>"
        if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream,
                                pikepdf.Array)):
            try:
                return str(obj)
            except UnicodeDecodeError:
                # A PDF string is bytes. Most carry text in UTF-16 or PDFDoc
                # encoding, but nothing obliges one to, and a corpus form
                # held a byte that is neither -- which crashed this
                # comparison rather than failing it. A digest compares the
                # same way without having to be decodable.
                return "bytes:" + hashlib.sha256(bytes(obj)).hexdigest()[:16]
        identity = obj.objgen
        if identity != (0, 0):
            if identity in self.pages:
                return f"page:{self.pages[identity]}"
            if identity in seen:
                self.guarded.append("cycle")
                return "<cycle>"
            if identity in self._memo:
                return self._memo[identity]
            seen = seen | {identity}
        fired = len(self.guarded)
        body = self._body(obj, seen, depth)
        if identity == (0, 0):
            return body
        short = "obj:" + hashlib.sha256(body.encode()).hexdigest()[:24]
        if len(self.guarded) == fired:
            # Only a subtree that closed on its own account can be reused:
            # one that hit a guard depended on where the walk came from.
            self._memo[identity] = short
        return short

    def _body(self, obj, seen, depth):
        if isinstance(obj, pikepdf.Array):
            return "[" + ",".join(
                self._value(value, seen, depth + 1) for value in obj) + "]"
        parts = []
        for key in sorted(str(name) for name in obj.keys()):
            if key in NOT_A_VALUE:
                continue
            if key in UPWARD:
                parts.append(f"{key}={self._named(obj[key])}")
            else:
                parts.append(f"{key}={self._value(obj[key], seen, depth + 1)}")
        body = ",".join(parts)
        if isinstance(obj, pikepdf.Stream):
            return f"stream:{_stream_digest(obj)}{{{body}}}"
        return "{" + body + "}"


def annotations(pdf, canon=None):
    """Every annotation in the document as (page, subtype, canonical text)."""
    canon = canon or Canon(pdf)
    return [(index, str(annot.get(pikepdf.Name.Subtype, "")), canon.of(annot))
            for index, page in enumerate(pdf.pages)
            for annot in page.obj.get(pikepdf.Name.Annots) or []]


def fields(pdf, canon=None):
    """Every field object as (its position in the tree, canonical text).

    Compared separately from the annotations rather than through them. A
    widget names its field by number, so the field's own contents -- the
    ``/FT``, ``/T``, ``/Ff`` and ``/V`` it may be inheriting from, and the
    ``/Kids`` that make it a group -- would otherwise go unchecked.
    """
    canon = canon or Canon(pdf)
    by_index = {index: objgen for objgen, index in canon.fields.items()}
    found = []
    for index in sorted(by_index):
        try:
            field = pdf.get_object(by_index[index])
        except Exception:  # noqa: BLE001 - a field we cannot fetch is a change
            found.append((index, "<unreadable>"))
            continue
        found.append((index, canon.of(field)))
    return found


def reportable(annot):
    """A failure's description: where it was and what it was, never its text."""
    index, subtype, body = annot
    return f"page {index + 1} {subtype or '(no subtype)'} " \
           f"{hashlib.sha256(body.encode()).hexdigest()[:12]}"


def signature_widgets_export_rewrites(pdf):
    """What export will do to this document's signatures, as (stamps, gone).

    Export's own predicates rather than a copy of them, because a
    reimplementation here was wrong on the first document it met.

    Only a field that has *been signed* counts. An unsigned ``/Sig`` field is
    a placeholder for a signer, and since 2026-10-31 export leaves it exactly
    where it is -- so it is not a rewrite and must not be excused as one. A
    signed field keeps its drawing as a ``/Stamp`` if it has one, and
    otherwise goes, which is what all four signed documents in the validation
    corpus do: an invisible signature has no mark to keep.
    """
    from pdfarranger_qt.export import _field_kind, _has_drawing, _is_signed_field

    stamps = gone = 0
    for page in pdf.pages:
        for annot in page.obj.get(pikepdf.Name.Annots) or []:
            if annot.get(pikepdf.Name.Subtype) != pikepdf.Name.Widget:
                continue
            if (_field_kind(annot) != pikepdf.Name.Sig
                    or not _is_signed_field(annot)):
                continue
            if _has_drawing(annot):
                stamps += 1
            else:
                gone += 1
    return stamps, gone


def exported(path):
    """Run one document through the real export and reopen the result."""
    from pdfarranger_qt.core import DocumentSet
    from pdfarranger_qt.export import get_in_memory_pdf

    docs = DocumentSet()
    try:
        pages = docs.add_file(path)
        return pikepdf.open(io.BytesIO(
            get_in_memory_pdf(list(pages), docs.files_for_export())))
    finally:
        docs.cleanup()


def difference(before, after):
    """What went missing and what appeared, as multisets."""
    missing, remaining = [], list(after)
    for annot in before:
        if annot in remaining:
            remaining.remove(annot)
        else:
            missing.append(annot)
    return missing, remaining


class TestEveryFixtureKeepsItsAnnotations(unittest.TestCase):
    """Reading and writing a document changes nothing in it.

    The one exception is the signature rewrite, and it is not forgiven: the
    count that disappears and the count that appears must both equal what
    export's own predicates say it will convert, so a mark lost for any other
    reason still fails even in a document where a conversion happens.
    """

    def documents(self):
        return sorted(glob.glob(os.path.join(FIXTURES, "**", "*.pdf"),
                                recursive=True))

    def test_there_are_fixtures_to_check(self):
        """A glob that matches nothing would pass every assertion below."""
        self.assertGreater(len(self.documents()), 10)

    def test_nothing_is_lost_and_nothing_is_invented(self):
        for path in self.documents():
            name = os.path.relpath(path, FIXTURES)
            with self.subTest(document=name):
                try:
                    source = pikepdf.open(path)
                except pikepdf.PasswordError:
                    continue
                with source:
                    reading = Canon(source)
                    before = annotations(source, reading)
                    before_fields = fields(source, reading)
                    stamps, gone = signature_widgets_export_rewrites(source)
                    rewritten = stamps + gone
                with exported(path) as out:
                    writing = Canon(out)
                    after = annotations(out, writing)
                    after_fields = fields(out, writing)
                self.assertEqual(
                    (reading.guarded, writing.guarded), ([], []),
                    f"{name}: the comparison hit its own guards, so what it "
                    f"compared was not the whole object")
                if not rewritten:
                    self.assertEqual(
                        [text for _, text in after_fields],
                        [text for _, text in before_fields],
                        f"{name}: {len(before_fields)} field objects went in "
                        f"and {len(after_fields)} came out, not matching")
                missing, appeared = difference(before, after)
                self.assertEqual(
                    len(missing), rewritten,
                    f"{name}: {len(missing)} of {len(before)} annotations did "
                    f"not survive the save, and export rewrites {rewritten}: "
                    + "; ".join(reportable(a) for a in missing[:6]))
                self.assertEqual(
                    len(appeared), stamps,
                    f"{name}: {len(appeared)} annotations appeared and export "
                    f"turns {stamps} signature widgets into stamps")
                self.assertEqual(
                    [subtype for _, subtype, _ in appeared],
                    ["/Stamp"] * stamps,
                    f"{name}: what appeared was not the stamp a signed "
                    f"signature leaves behind")


class TestAnUnsignedSignatureFieldIsLeftAlone(unittest.TestCase):
    """A field waiting for a signer is a form field, and survives as one.

    Both fields in the fixture are *placeholders*: no ``/V``, so nothing has
    been signed, and no ``/Perms``, so nothing has been certified. Their
    appearance streams decode to zero bytes.

    Until 2026-10-31 export rewrote them anyway. Which of two wrong things
    happened turned on whether the widget had an appearance stream at all:
    these two, having one, came out as blank ``/Stamp`` annotations that
    could never be signed, while three visible signature lines on a VA
    disability form in the validation corpus, having none, were deleted
    outright. Neither document had been signed, so in both cases a save
    destroyed a form field to protect a signature that did not exist.

    What decides it now is ``/V``, which is the rule ``forms.signatures_in``
    has always stated and ``forms.is_signed`` has always used.
    """

    path = os.path.join(FIXTURES, "markup.pdf")

    def widgets(self, pdf):
        from pdfarranger_qt.export import _field_kind

        return [(index, annot)
                for index, page in enumerate(pdf.pages)
                for annot in page.obj.get(pikepdf.Name.Annots) or []
                if annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Widget
                and _field_kind(annot) == pikepdf.Name.Sig]

    def test_the_fixture_has_two_unsigned_placeholders(self):
        """The premise. Without it the tests below prove nothing."""
        with pikepdf.open(self.path) as pdf:
            found = self.widgets(pdf)
            self.assertEqual([index for index, _ in found], [2, 3])
            for _, annot in found:
                self.assertIsNone(annot.get(pikepdf.Name.V))
                self.assertEqual(
                    annot[pikepdf.Name.AP][pikepdf.Name.N].read_bytes(), b"")
            self.assertNotIn(pikepdf.Name.Perms, pdf.Root)

    def test_they_are_still_signature_widgets_afterwards(self):
        with exported(self.path) as out:
            self.assertEqual([index for index, _ in self.widgets(out)], [2, 3])

    def test_nothing_became_a_stamp(self):
        """The fixture already holds twenty-four stamps of its own.

        Acrobat's standard-business, sign-here and dynamic sets. So a
        conversion has to be read as a difference and not as a total.
        """
        def stamps(pdf):
            return sorted(
                index
                for index, page in enumerate(pdf.pages)
                for annot in page.obj.get(pikepdf.Name.Annots) or []
                if annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Stamp)

        with pikepdf.open(self.path) as pdf:
            before = stamps(pdf)
        with exported(self.path) as out:
            self.assertEqual(stamps(out), before)

    def test_the_fields_are_still_in_the_form(self):
        """A widget whose field is missing from /Fields is not fillable."""
        from pdfarranger_qt.export import _root_field

        with exported(self.path) as out:
            surviving = {
                field.objgen
                for field in out.Root.AcroForm.get(pikepdf.Name.Fields, [])}
            for _, annot in self.widgets(out):
                self.assertIn(_root_field(annot).objgen, surviving)

    def test_the_document_is_still_not_signed(self):
        """Keeping the placeholder must not amount to claiming a signature."""
        from pdfarranger_qt import forms

        with exported(self.path) as out:
            self.assertEqual(forms.signatures_in(out), [])
            self.assertFalse(forms.is_signed(out))


class TestAnAnnotationKnowsWhichPageItIsOn(unittest.TestCase):
    """``/P`` names a page in the document, not a copy left behind.

    The comparison above would catch this, because a page reference is read
    as a page index. This says it in its own right, because it was broken in
    every document this application wrote until 2026-10-31 and the symptom --
    a reference that resolves to a perfectly good dictionary that simply is
    not in the page tree -- is invisible to anything that only walks
    ``/Annots``.
    """

    def documents(self):
        return sorted(glob.glob(os.path.join(FIXTURES, "**", "*.pdf"),
                                recursive=True))

    def health(self, pdf):
        """How many page pointers resolve, dangle, or are not there."""
        tree = {page.obj.objgen for page in pdf.pages}
        resolves = dangling = absent = 0
        for page in pdf.pages:
            for annot in page.obj.get(pikepdf.Name.Annots) or []:
                target = annot.get(pikepdf.Name.P)
                if target is None:
                    absent += 1
                elif target.objgen in tree:
                    resolves += 1
                else:
                    dangling += 1
        return resolves, dangling, absent

    def test_none_dangles_and_none_is_invented(self):
        checked = 0
        for path in self.documents():
            name = os.path.relpath(path, FIXTURES)
            with self.subTest(document=name):
                try:
                    source = pikepdf.open(path)
                except pikepdf.PasswordError:
                    continue
                with source:
                    before = self.health(source)
                with exported(path) as out:
                    after = self.health(out)
                self.assertEqual(after[1], 0,
                                 f"{name}: {after[1]} page pointers dangle")
                self.assertEqual(
                    after, before,
                    f"{name}: page pointers went from {before} to {after} "
                    f"as (resolving, dangling, absent)")
                checked += 1
        self.assertGreater(checked, 10)

    def test_the_fixtures_are_worth_asking_about(self):
        """At least one document has to carry the key, or this proves nothing."""
        with_key = [path for path in self.documents()
                    if not path.endswith("test_encrypted.pdf")
                    and self.health(pikepdf.open(path))[0] > 0]
        self.assertTrue(with_key)


class TestALinkStillPointsWhereItDid(unittest.TestCase):
    """A destination survives the rebuild, read as a page and not a number.

    Object numbers are assigned afresh, so the only honest way to ask whether
    a link still works is to resolve it on both sides and compare the page it
    lands on.
    """

    path = os.path.join(FIXTURES, "exporter", "test20_8_out.pdf")

    def links(self, pdf):
        return [annot
                for page in pdf.pages
                for annot in page.obj.get(pikepdf.Name.Annots) or []
                if annot.get(pikepdf.Name.Subtype) == pikepdf.Name.Link]

    def destinations(self, pdf):
        pages = _pages_by_object(pdf)
        return [pages[annot[pikepdf.Name.Dest][0].objgen]
                for annot in self.links(pdf)]

    def test_the_fixture_has_links_that_resolve(self):
        """The premise: a dangling one here would make the test vacuous."""
        with pikepdf.open(self.path) as pdf:
            self.assertEqual(len(self.links(pdf)), 16)
            self.assertEqual(len(self.destinations(pdf)), 16)

    def test_every_destination_lands_on_the_same_page(self):
        with pikepdf.open(self.path) as pdf:
            before = self.destinations(pdf)
        with exported(self.path) as out:
            self.assertEqual(self.destinations(out), before)


def document_with_a_pattern_resource():
    """A form whose `/DR` holds a stream rather than a dictionary.

    Which is what Acrobat writes when a squiggly underline is made: `/DR`
    gains a `/squiggly` tiling Pattern. Everything else in the corpus had
    dictionaries only one level down, so the branch that copied those was the
    only one anybody exercised, and the branch beside it handed the output an
    object still owned by the input.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 300))
    pattern = pikepdf.Stream(pdf, b"0 0 1 RG 0 0 m 2 2 l S\n")
    pattern[pikepdf.Name.Type] = pikepdf.Name.Pattern
    pattern[pikepdf.Name.PatternType] = 1
    pattern[pikepdf.Name.PaintType] = 1
    pattern[pikepdf.Name.TilingType] = 1
    pattern[pikepdf.Name.BBox] = pikepdf.Array([0, 0, 4, 4])
    pattern[pikepdf.Name.XStep] = 4
    pattern[pikepdf.Name.YStep] = 4
    pattern[pikepdf.Name.Resources] = pikepdf.Dictionary()
    field = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
        FT=pikepdf.Name.Tx, T=pikepdf.String("answer"),
        Rect=pikepdf.Array([20, 20, 120, 40]), F=4))
    pdf.pages[0].obj[pikepdf.Name.Annots] = pikepdf.Array([field])
    pdf.Root[pikepdf.Name.AcroForm] = pikepdf.Dictionary(
        Fields=pikepdf.Array([field]),
        DA=pikepdf.String("/Helv 0 Tf 0 g"),
        # A stream one level down, beside the dictionaries that /DR usually
        # holds -- the shape that broke the save.
        DR=pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                Helv=pdf.make_indirect(pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica))),
            squiggly=pdf.make_indirect(pattern)))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class TestAPatternUnderDRSurvivesTheSave(unittest.TestCase):
    """The bug a squiggly underline found, 2026-10-31.

    `_restore_acroform` copied `/DR` entries that are dictionaries with
    `copy_foreign` and assigned everything else straight across, so the output
    held an object belonging to the input and qpdf refused the save with
    "unexpected object id encountered in getCompressibleObjGens". Every page
    of the document failed, not merely the one the pattern was used on.
    """

    def setUp(self):
        path = temp_path("pattern-resource.pdf")
        with open(path, "wb") as handle:
            handle.write(document_with_a_pattern_resource())
        self.path = path

    def test_the_document_can_be_saved_at_all(self):
        """Before the fix this raised rather than failing an assertion."""
        with exported(self.path) as out:
            self.assertEqual(len(out.pages), 1)

    def test_the_pattern_is_still_there(self):
        with exported(self.path) as out:
            resources = out.Root.AcroForm.DR
            self.assertIn("/squiggly", resources)
            self.assertEqual(str(resources["/squiggly"]["/Type"]), "/Pattern")

    def test_the_pattern_belongs_to_the_document_that_holds_it(self):
        """The actual defect: ownership, not presence.

        A foreign object reads back perfectly well through pikepdf; it is
        only writing that fails. Saving the output again is what proves the
        copy was real.
        """
        with exported(self.path) as out:
            again = io.BytesIO()
            out.save(again)
            self.assertGreater(len(again.getvalue()), 0)


if __name__ == "__main__":
    unittest.main()
