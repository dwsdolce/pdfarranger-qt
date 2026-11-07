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

"""Changing a mark's colour and opacity, including one the file brought.

The half that is new here is editing something this application did not
make. A mark the user drew lives in the model and can simply be altered; a
mark the document arrived with keeps its own dictionary, and only a handful
of keys are rewritten over the top of it -- so what these tests mostly check
is what is *not* touched.
"""

import io
import os
import unittest

import pikepdf
from support import FIXTURES, settle

from pdfarranger_qt import markup

PDF = os.path.join(FIXTURES, "markup.pdf")
#: A highlight over a run of thirteen lines, made in Acrobat. `markup.pdf`
#: has one of every kind but each covers a single line, so it cannot say
#: whether a resize shortened a run or did nothing at all.
RUN = os.path.join(FIXTURES, "markup_highlight.pdf")


class TestThePalette(unittest.TestCase):
    """Twenty-one colours, sampled from Reader's picker.

    The values are the point of this: they were read off a screenshot that
    carried a Display P3 profile, and reading such a screenshot as though it
    were sRGB is wrong by up to 59 of 255. These check the converted values
    rather than the raw ones, against documents Reader itself wrote.
    """

    #: Colours that appear in Reader-written documents in the validation
    #: corpus, and the name of the swatch each came from. The corpus is not
    #: part of this suite -- these are the measurements it yielded, written
    #: down, so the palette cannot drift away from them unnoticed.
    FROM_READER = {
        "Blue": (0x13, 0x73, 0xE8),
        "Fuchsia": (0xC0, 0x37, 0xC4),
        "Purple": (0x96, 0x43, 0xFC),
        "Light Blue": (0x38, 0xE5, 0xFF),
        "Red": (0xDB, 0x34, 0x25),
        "Orange": (0xFF, 0x62, 0x00),
        "Light Red": (0xF8, 0x64, 0x64),
        "Light Green": (0xC5, 0xFB, 0x72),
    }

    def test_it_is_three_rows_of_seven(self):
        self.assertEqual(len(markup.PALETTE), 21)
        self.assertEqual(markup.PALETTE_COLUMNS, 7)
        self.assertEqual(len(markup.PALETTE) % markup.PALETTE_COLUMNS, 0)

    def test_the_second_row_lightens_the_first(self):
        """Reader's own naming, and the structure behind it."""
        width = markup.PALETTE_COLUMNS
        for n in range(width):
            hue = markup.PALETTE[n][0]
            light = markup.PALETTE[n + width][0]
            with self.subTest(hue=hue):
                self.assertEqual(light, f"Light {hue}")

    def test_the_third_row_runs_white_to_black(self):
        width = markup.PALETTE_COLUMNS
        greys = markup.PALETTE[2 * width:]
        self.assertEqual(greys[0][1], (1.0, 1.0, 1.0))
        self.assertEqual(greys[-1][1], (0.0, 0.0, 0.0))
        levels = [sum(colour) for _name, colour in greys]
        self.assertEqual(levels, sorted(levels, reverse=True))
        for _name, (r, g, b) in greys:
            self.assertEqual((r, r), (g, b), "a grey with a hue in it")

    def test_it_matches_what_reader_writes(self):
        """Eight independent confirmations that the sampling was right.

        Each of these appears in a document Reader produced, so the palette
        can be checked against the format rather than against a screenshot.
        Read without converting out of Display P3, Light Blue alone would be
        out by 59 of 255.
        """
        by_name = {name: colour for name, colour in markup.PALETTE}
        for name, expected in self.FROM_READER.items():
            with self.subTest(swatch=name):
                got = tuple(round(v * 255) for v in by_name[name])
                off = max(abs(a - b) for a, b in zip(got, expected))
                self.assertLessEqual(
                    off, 1,
                    f"{name} is #{got[0]:02X}{got[1]:02X}{got[2]:02X}, "
                    f"Reader writes #{expected[0]:02X}{expected[1]:02X}"
                    f"{expected[2]:02X}")

    def test_the_tick_lands_on_the_nearest_swatch(self):
        """A mark may be any colour at all -- Reader has a wheel behind the
        same button, and other producers have their own -- so the popup
        marks the nearest cell rather than only an exact one."""
        by_name = {name: colour for name, colour in markup.PALETTE}
        for name in ("Orange", "Blue", "Black", "Light Green"):
            with self.subTest(swatch=name):
                nudged = tuple(min(1.0, v + 0.01) for v in by_name[name])
                found = markup.PALETTE[markup.nearest_swatch(nudged)][0]
                self.assertEqual(found, name)

    def test_nothing_is_nearest_to_nothing(self):
        self.assertIsNone(markup.nearest_swatch(None))


class TestHowSolidAMarkIs(unittest.TestCase):

    def test_a_kind_has_an_opacity_of_its_own(self):
        """A highlight has to be seen through or it hides the words."""
        mark = markup.Annotation(markup.HIGHLIGHT, 1, (0, 0, 10, 10))
        self.assertEqual(markup.solidity(mark),
                         markup.TRANSPARENCY[markup.HIGHLIGHT])
        line = markup.Annotation(markup.STRIKEOUT, 1, (0, 0, 10, 10))
        self.assertEqual(markup.solidity(line),
                         markup.TRANSPARENCY[markup.STRIKEOUT])

    def test_a_mark_can_say_otherwise(self):
        mark = markup.Annotation(markup.HIGHLIGHT, 1, (0, 0, 10, 10),
                                 opacity=0.25)
        self.assertEqual(markup.solidity(mark), 0.25)

    def test_it_reaches_the_dictionary(self):
        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(200, 200))
        mark = markup.Annotation(markup.HIGHLIGHT, 1, (0, 0, 10, 10),
                                 quads=[(0, 0, 10, 10)], opacity=0.25)
        entry = markup.to_dictionary(pdf, mark)
        self.assertAlmostEqual(float(entry["/CA"]), 0.25, places=4)


class TestWhatIsChangedAboutTheFilesOwnMarks(unittest.TestCase):
    """`MarkEdits`: a few keys held beside a dictionary, not a copy of it."""

    @staticmethod
    def changed(edit):
        """An edit without its timestamp.

        Every edit records when it happened, so an assertion against the
        whole dictionary would be an assertion against the clock.
        """
        return {k: v for k, v in edit.items() if k != "modified"}

    def test_it_records_what_was_changed(self):
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        self.assertEqual(self.changed(edits.of(7, 2)),
                         {"colour": (1.0, 0.0, 0.0)})

    def test_the_edit_records_when_it_happened(self):
        """`/M` is what a reader shows beside a comment, and a mark
        whose date never moved would claim it had not been touched."""
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        self.assertRegex(edits.of(7, 2)["modified"], r"^D:\d{14}")

    def test_a_second_change_joins_the_first(self):
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        edits.change(7, 2, opacity=0.3)
        self.assertEqual(self.changed(edits.of(7, 2)),
                         {"colour": (1.0, 0.0, 0.0), "opacity": 0.3})

    def test_only_the_attributes_it_knows(self):
        """Anything not named here is the producer's and is left alone, so
        accepting it silently would promise an edit that never happens.

        `contents` was the example of something refused, and then `subject`
        was; both are fields now -- the first because a note is the mark's
        own text and the second because the properties form writes `/Subj`.
        The principle is unchanged: what is refused is a key nothing
        writes, and the example moves as the writer grows.
        """
        edits = markup.MarkEdits()
        with self.assertRaises(ValueError):
            edits.change(7, 2, border="hello")
        self.assertEqual(edits.for_page(7), {})

    def test_it_is_kept_per_page(self):
        """By page uid, so a reorder cannot move an edit to another page and
        a duplicated page is not recoloured along with its original."""
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        self.assertEqual({at: self.changed(e)
                          for at, e in edits.for_page(7).items()},
                         {2: {"colour": (1.0, 0.0, 0.0)}})
        self.assertEqual(edits.for_page(8), {})

    def test_forgetting_the_last_one_forgets_the_page(self):
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        edits.forget(7, 2)
        self.assertFalse(edits)
        self.assertEqual(list(edits.pages()), [])

    def test_a_copy_does_not_share(self):
        """Which is what undo does to it on every commit."""
        edits = markup.MarkEdits()
        edits.change(7, 2, colour=(1.0, 0.0, 0.0))
        copy = edits.duplicate()
        copy.change(7, 2, colour=(0.0, 0.0, 1.0))
        self.assertEqual(self.changed(edits.of(7, 2)),
                         {"colour": (1.0, 0.0, 0.0)})
        self.assertEqual(self.changed(copy.of(7, 2)),
                         {"colour": (0.0, 0.0, 1.0)})


class TestWhereAMarkSitsAmongItsNeighbours(unittest.TestCase):
    """The index an edit is keyed by, and what it counts.

    A position is the wrong name for a mark in a list this application
    edits -- deleting one shifts everything after it. This is a position in
    the *source*, which is never edited, and export enumerates it the same
    way. What matters is that both ends count the same things.
    """

    def test_it_counts_markup_and_nothing_else(self):
        """Widgets, popups and links are skipped. A widget can be removed on
        the way out, and an index that counted it would then name the mark
        next door."""
        with pikepdf.open(PDF) as pdf:
            marks = markup.marks_in(pdf)
            for number in {m.page for m in marks}:
                on = [m for m in marks if m.page == number]
                with self.subTest(page=number):
                    self.assertEqual([m.index for m in on],
                                     list(range(len(on))))

    def test_a_page_with_widgets_still_starts_at_zero(self):
        with pikepdf.open(PDF) as pdf:
            widgets = [a for a in (pdf.pages[0].get("/Annots") or [])
                       if str(a.get("/Subtype")) == "/Widget"]
            self.assertTrue(widgets, "the fixture has no widgets to skip")
            first = [m for m in markup.marks_in(pdf) if m.page == 1][0]
            self.assertEqual(first.index, 0)


class TestADeletedMarkLeavesTheFile(unittest.TestCase):
    """What a deleted mark leaves behind in the written file.

    Measured against a file Reader wrote after the same delete: it keeps
    both status annotations and both their popups, stripping the `/IRT` off
    the one that pointed at the mark. This takes them, so the counts below
    differ from Reader's deliberately -- `/Text 2  /Popup 2` there, none
    here.
    """

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(RUN)
        with pikepdf.open(RUN) as pdf:
            self.marks = [m for m in markup.marks_in(pdf) if m.page == 1]

    def written(self, going):
        from pdfarranger_qt.export import export

        edits = markup.MarkEdits()
        for mark in going:
            edits.change(self.pages[0].uid, mark.index, deleted=True)
        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               mark_edits=edits)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    @staticmethod
    def kinds(pdf):
        found = {}
        for annot in pdf.pages[0].obj.get("/Annots") or []:
            name = str(annot.get("/Subtype"))
            found[name] = found.get(name, 0) + 1
        return found

    def test_the_mark_and_its_popup_both_go(self):
        with pikepdf.open(RUN) as before:
            was = self.kinds(before)
        with self.written(self.marks[:1]) as after:
            now = self.kinds(after)
        self.assertEqual(now.get("/Highlight", 0), was["/Highlight"] - 1)
        self.assertEqual(now.get("/Popup", 0), was["/Popup"] - 1,
                         "the popup the mark owned stayed behind")

    def test_the_chain_goes_when_every_link_is_recorded(self):
        """The writer derives nothing: it deletes what it is told, and the
        chain was walked once, where the marks are."""
        with self.written(self.marks) as after:
            now = self.kinds(after)
        self.assertEqual(now.get("/Highlight", 0), 0)
        self.assertEqual(now.get("/Text", 0), 0)
        self.assertEqual(now.get("/Popup", 0), 0)

    def test_nothing_else_on_the_page_is_touched(self):
        """A deletion rebuilds `/Annots`, so everything it is not about has
        to come through: the widgets and the links are most of the page."""
        with pikepdf.open(RUN) as before:
            was = self.kinds(before)
        with self.written(self.marks) as after:
            now = self.kinds(after)
        for name in ("/Widget", "/Link"):
            with self.subTest(subtype=name):
                self.assertEqual(now.get(name, 0), was[name])

    def test_a_mark_that_is_not_deleted_keeps_its_own_dictionary(self):
        """Deleting one mark must not disturb another on the same page."""
        with self.written(self.marks[:1]) as after:
            left = [m for m in markup.marks_in(after) if m.page == 1]
        self.assertEqual(len(left), len(self.marks) - 1)
        for mark in left:
            with self.subTest(subtype=mark.subtype):
                self.assertIsNotNone(mark.name, "/NM was lost")


class TestShowingAChangeWithoutRebuilding(unittest.TestCase):
    """`one_page_with_edits`: one page lifted out and patched.

    The marks a document arrived with are drawn into the page bitmap, so a
    recoloured one cannot be painted over the old one -- the page has to be
    rendered from a document that carries the change. Doing that to the
    whole document costs 1180 ms on a 1590-page book against 1.1 to 6.5 ms
    for one page, which is the whole reason this exists.
    """

    def setUp(self):
        with open(PDF, "rb") as handle:
            self.data = handle.read()
        with pikepdf.open(PDF) as pdf:
            self.mark = [m for m in markup.marks_in(pdf) if m.page == 1][0]

    def test_nothing_to_show_is_no_document(self):
        """So the caller can put the page back on the ordinary render path
        rather than keep one that says the same as the original."""
        self.assertIsNone(markup.one_page_with_edits(self.data, 0, {}))

    def test_an_edit_for_a_mark_that_is_not_there_changes_nothing(self):
        self.assertIsNone(markup.one_page_with_edits(
            self.data, 0, {9999: {"colour": (1.0, 0.0, 0.0)}}))

    def test_the_page_comes_back_with_the_change_in_it(self):
        patched = markup.one_page_with_edits(
            self.data, 0, {self.mark.index: {"colour": (0.0, 1.0, 1.0),
                                             "opacity": 0.25}})
        self.assertIsNotNone(patched)
        with pikepdf.open(io.BytesIO(patched)) as one:
            self.assertEqual(len(one.pages), 1)
            got = markup.marks_in(one)[self.mark.index]
            self.assertEqual(got.colour, (0.0, 1.0, 1.0))
            self.assertAlmostEqual(got.opacity, 0.25, places=4)

    def a_run_of_lines(self):
        """The thirteen-line highlight, with the file it came out of.

        Every mark in `markup.pdf` covers one line, so shortening one there
        leaves the count where it was and the test passes whatever the code
        does.
        """
        with open(RUN, "rb") as handle:
            data = handle.read()
        with pikepdf.open(RUN) as pdf:
            mark = [m for m in markup.marks_in(pdf) if m.page == 1][0]
        self.assertGreater(len(mark.boxes()), 1)
        return data, mark

    def test_a_resized_mark_comes_back_with_its_new_run(self):
        """What a resize is *for*. This path applied colour and opacity and
        had no case for `quads` at all, so the page was re-rendered from a
        document that still held the old run -- a resize was written to the
        file correctly and never once seen on screen. The export patcher,
        which did handle it, is now the same code."""
        data, mark = self.a_run_of_lines()
        shorter = mark.boxes()[:4]
        patched = markup.one_page_with_edits(
            data, 0, {mark.index: {"quads": shorter}})
        self.assertIsNotNone(patched)
        with pikepdf.open(io.BytesIO(patched)) as one:
            got = markup.marks_in(one)[mark.index]
            self.assertEqual(len(got.boxes()), len(shorter))
            self.assertLess(len(got.boxes()), len(mark.boxes()))
            for want, mine in zip(shorter, got.boxes()):
                with self.subTest(box=tuple(round(v) for v in want)):
                    for a, b in zip(want, mine):
                        self.assertAlmostEqual(a, b, places=3)

    def test_a_resize_moves_the_rectangle_that_has_to_contain_it(self):
        """`/Rect` has to contain every quadrilateral. Left where it was, it
        would be a rectangle around text the mark no longer covers."""
        data, mark = self.a_run_of_lines()
        shorter = mark.boxes()[:4]
        patched = markup.one_page_with_edits(
            data, 0, {mark.index: {"quads": shorter}})
        with pikepdf.open(io.BytesIO(patched)) as one:
            got = markup.marks_in(one)[mark.index]
            self.assertEqual(tuple(round(v, 3) for v in got.rect),
                             tuple(round(v, 3)
                                   for v in markup.bounding_rect(shorter)))

    def test_the_appearance_the_producer_wrote_goes_with_it(self):
        """It still draws the old colour, and a stream that disagrees with
        `/C` is worse than none: every reader falls back to the
        quadrilaterals when there is no stream to prefer."""
        patched = markup.one_page_with_edits(
            self.data, 0, {self.mark.index: {"colour": (0.0, 1.0, 1.0)}})
        with pikepdf.open(io.BytesIO(patched)) as one:
            annots = [a for a in (one.pages[0].get("/Annots") or [])
                      if str(a.get("/Subtype"))
                      not in ("/Widget", "/Popup", "/Link")]
            self.assertNotIn("/AP", annots[self.mark.index])

    def test_the_widgets_come_with_the_page(self):
        """The one-page copy has no `/AcroForm`, which pikepdf warns about
        and which costs nothing here: the widgets travel with the page and
        keep their appearance streams, and this document is rasterised once
        and thrown away rather than shown to Acrobat."""
        patched = markup.one_page_with_edits(
            self.data, 0, {self.mark.index: {"colour": (0.0, 1.0, 1.0)}})
        with pikepdf.open(io.BytesIO(patched)) as one, \
                pikepdf.open(PDF) as whole:
            def widgets(pdf):
                return [a for a in (pdf.pages[0].get("/Annots") or [])
                        if str(a.get("/Subtype")) == "/Widget"]
            self.assertEqual(len(widgets(one)), len(widgets(whole)))
            self.assertTrue(all("/AP" in a for a in widgets(one)))

    def test_it_says_nothing_on_the_console(self):
        """The warning it provokes is understood and silenced where it is
        raised; a reader of this application's output should not see it."""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            markup.one_page_with_edits(
                self.data, 0, {self.mark.index: {"colour": (0.0, 1.0, 1.0)}})
        self.assertEqual([c.category.__name__ for c in caught], [])


class TestItReachesTheSavedFile(unittest.TestCase):
    """Export rewrites three keys and leaves the rest of the dictionary."""

    def setUp(self):
        from pdfarranger_qt.core import DocumentSet

        self.docs = DocumentSet()
        self.pages = self.docs.add_file(PDF)
        with pikepdf.open(PDF) as pdf:
            self.mark = [m for m in markup.marks_in(pdf) if m.page == 1][0]

    def saved(self, edits):
        from pdfarranger_qt.export import export

        out = io.BytesIO()
        export(self.docs.files_for_export(), list(self.pages), {}, [out],
               mark_edits=edits)
        return pikepdf.open(io.BytesIO(out.getvalue()))

    def changed(self, **fields):
        edits = markup.MarkEdits()
        edits.change(self.pages[0].uid, self.mark.index, **fields)
        return self.saved(edits)

    def test_the_colour_is_written(self):
        with self.changed(colour=(0.0, 1.0, 1.0)) as pdf:
            got = [m for m in markup.marks_in(pdf) if m.page == 1]
            self.assertEqual(got[self.mark.index].colour, (0.0, 1.0, 1.0))

    def test_the_opacity_is_written(self):
        with self.changed(opacity=0.25) as pdf:
            got = [m for m in markup.marks_in(pdf) if m.page == 1]
            self.assertAlmostEqual(got[self.mark.index].opacity, 0.25,
                                   places=4)

    def test_every_other_key_is_the_producer_s(self):
        """The whole reason this patches rather than replaces. Writing a
        fresh annotation from what this application models would drop every
        key it does not model, which is most of them."""
        with pikepdf.open(PDF) as before:
            was = self.keys_of(before)
        with self.changed(colour=(0.0, 1.0, 1.0)) as after:
            now = self.keys_of(after)
        self.assertTrue(was - {"/AP"} <= now,
                        f"keys lost: {sorted(was - {'/AP'} - now)}")

    def keys_of(self, pdf):
        annots = [a for a in (pdf.pages[0].get("/Annots") or [])
                  if str(a.get("/Subtype"))
                  not in ("/Widget", "/Popup", "/Link")]
        return {str(k) for k in annots[self.mark.index].keys()}

    def test_only_the_mark_named_is_touched(self):
        with pikepdf.open(PDF) as before:
            was = [(m.colour, m.opacity)
                   for m in markup.marks_in(before) if m.page == 1]
        with self.changed(colour=(0.0, 1.0, 1.0)) as after:
            now = [(m.colour, m.opacity)
                   for m in markup.marks_in(after) if m.page == 1]
        self.assertEqual(len(was), len(now))
        for n, (old, new) in enumerate(zip(was, now)):
            if n == self.mark.index:
                continue
            with self.subTest(mark=n):
                self.assertEqual(old, new)

    def test_no_edits_changes_nothing(self):
        with pikepdf.open(PDF) as before:
            was = [(m.colour, m.opacity)
                   for m in markup.marks_in(before) if m.page == 1]
        with self.saved(markup.MarkEdits()) as after:
            now = [(m.colour, m.opacity)
                   for m in markup.marks_in(after) if m.page == 1]
        self.assertEqual(was, now)


class ColourCase(unittest.TestCase):
    """A window reading the markup sample with the strip open."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication  # noqa: F401

        from pdfarranger_qt.mainwindow import MainWindow

        self.win = MainWindow()
        self.win.resize(1000, 800)
        self.win.show()
        self.win.open_paths([PDF])
        settle(timeout_ms=1200)
        self.win.set_read_mode(True)
        settle(timeout_ms=1600)
        self.win.show_markup_tools(True)
        settle(timeout_ms=200)
        self.canvas = self.win.reader.canvas
        self.strip = self.win.tool_strip
        self.canvas.verticalScrollBar().setValue(0)
        settle(timeout_ms=250)

    def tearDown(self):
        self.win.modified = False
        self.win.close()
        for key in ("reader/markup-tools", "reader/markup-tools-at"):
            self.win.settings.remove(key)

    def a_mark(self):
        found = [m for m, mine in self.canvas.marks_on(0) if not mine]
        self.assertTrue(found, "the page carries no mark to pick")
        return found[0]

    def uid(self):
        return self.win.model.pages[0].uid


class TestTheSwatchInTheTail(ColourCase):
    """It does two jobs, and which one depends on what is selected."""

    def test_the_tail_shows_what_is_being_worked_on(self):
        """**The armed tool's attributes, or the selected annotation's.**

        A pointer makes nothing and has no attributes of its own, so with
        one armed the tail is empty -- until a mark is selected, when it
        shows that mark's, which is the swatch's second job. It was shown
        under every tool for a while, on the reasoning that the swatch has
        that second job at all times; that substituted a rule of its own
        for the one the owner asked for.
        """
        for name in ("highlight", "draw", "comment"):
            with self.subTest(tool=name):
                self.strip.arm(name)
                settle(timeout_ms=60)
                self.assertTrue(self.strip.tail.isVisible())
        for name in ("select", "pan"):
            with self.subTest(tool=name):
                self.canvas.select_mark(None)
                self.strip.arm(name)
                settle(timeout_ms=60)
                self.assertFalse(self.strip.tail.isVisible(),
                                 "a pointer has no attributes of its own")
        mark = self.a_mark()
        self.strip.arm("select")
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=250)
        self.assertTrue(self.strip.tail.isVisible(),
                        "a selected mark has attributes to show")

    def test_with_nothing_selected_it_arms_the_next_mark(self):
        from pdfarranger_qt import markup as m

        self.strip.arm("highlight")
        self.canvas.select_mark(None)
        self.strip._colour_picked((0.0, 1.0, 1.0))
        self.strip._opacity_picked(0.25)
        self.canvas.mark_drawn.emit("highlight", 0, [(60.0, 700.0, 300.0, 714.0)])
        settle(timeout_ms=250)
        made = self.win.model.annotations.for_page(self.uid())[-1]
        self.assertEqual(made.colour, (0.0, 1.0, 1.0))
        self.assertEqual(m.solidity(made), 0.25)

    def test_with_a_mark_selected_it_changes_that_mark(self):
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.strip._colour_picked((0.0, 1.0, 1.0))
        settle(timeout_ms=300)
        self.assertEqual(
            self.win.model.mark_edits.of(self.uid(), mark.index).get("colour"),
            (0.0, 1.0, 1.0))

    def test_changing_a_selected_mark_does_not_arm_the_next_one(self):
        """Or recolouring one highlight would quietly recolour every mark
        made afterwards."""
        mark = self.a_mark()
        self.strip._colour_picked((1.0, 0.0, 1.0))
        armed = self.win.armed_colour
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.strip._colour_picked((0.0, 1.0, 1.0))
        settle(timeout_ms=300)
        self.assertEqual(self.win.armed_colour, armed)

    def test_it_shows_the_selected_mark_and_puts_it_back(self):
        """So the tick in the popup marks what the mark is rather than what
        the next one would be."""
        self.strip._colour_picked((1.0, 0.0, 1.0))
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.assertEqual(self.strip.swatch.colour, mark.colour)
        self.canvas.select_mark(None)
        settle(timeout_ms=200)
        self.assertEqual(self.strip.swatch.colour, (1.0, 0.0, 1.0))


class TestTheBarsSwatchDoesTheSame(ColourCase):

    def test_either_route_changes_the_selected_mark(self):
        """And under either tool: selecting with Select and selecting with
        Highlight are the same thing, so what you can then do must be too."""
        for tool in ("select", "highlight"):
            for route in ("tail", "bar"):
                with self.subTest(tool=tool, route=route):
                    self.win.model.mark_edits.clear()
                    self.strip.arm(tool)
                    settle(timeout_ms=80)
                    mark = self.a_mark()
                    self.canvas.select_mark(None)
                    self.canvas.select_mark((0, mark))
                    settle(timeout_ms=200)
                    if route == "tail":
                        self.strip._colour_picked((0.0, 1.0, 1.0))
                    else:
                        self.win.mark_recoloured((0.0, 1.0, 1.0))
                    settle(timeout_ms=300)
                    self.assertEqual(
                        self.win.model.mark_edits.of(
                            self.uid(), mark.index).get("colour"),
                        (0.0, 1.0, 1.0))

    def test_the_popup_ticks_the_selected_mark_s_colour(self):
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        bar = self.win.mark_buttons
        bar.palette_popup.show_for(bar._colour, bar._opacity,
                                   bar.mapToGlobal(bar.rect().topLeft()))
        ticked = [n for n, cell in enumerate(bar.palette_popup.cells)
                  if cell._chosen]
        bar.palette_popup.hide()
        self.assertEqual(ticked, [markup.nearest_swatch(mark.colour)])


class TestItIsAllOneHistory(ColourCase):

    def test_a_change_can_be_undone_and_redone(self):
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.win.mark_recoloured((0.0, 1.0, 1.0))
        settle(timeout_ms=300)
        self.win.mark_faded(0.25)
        settle(timeout_ms=300)
        self.assertEqual(
            {k: v for k, v in self.win.model.mark_edits.of(
                self.uid(), mark.index).items()
             if k != "modified"},
            {"colour": (0.0, 1.0, 1.0), "opacity": 0.25})
        self.win.model.undo.undo()
        settle(timeout_ms=250)
        self.assertEqual(
            {k: v for k, v in self.win.model.mark_edits.of(
                self.uid(), mark.index).items()
             if k != "modified"},
            {"colour": (0.0, 1.0, 1.0)})
        self.win.model.undo.undo()
        settle(timeout_ms=250)
        self.assertEqual(
            {k: v for k, v in self.win.model.mark_edits.of(
                self.uid(), mark.index).items()
             if k != "modified"},
            {})
        self.win.model.undo.redo()
        settle(timeout_ms=250)
        self.assertEqual(
            {k: v for k, v in self.win.model.mark_edits.of(
                self.uid(), mark.index).items()
             if k != "modified"},
            {"colour": (0.0, 1.0, 1.0)})

    def test_the_page_is_rendered_from_its_own_document(self):
        """A recoloured mark is already in the page bitmap, so the page has
        to come from a document that carries the change.

        The page it is *replaced* with is what matters, not whether there
        was one before: a page carrying replies is already rendered from a
        document of its own, because the replies are left out of it.
        """
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        was = self.canvas._pages._edited.get(0)
        self.win.mark_recoloured((0.0, 1.0, 1.0))
        settle(timeout_ms=400)
        self.assertIn(0, self.canvas._pages._edited)
        self.assertNotEqual(self.canvas._pages._edited.get(0), was,
                            "the page was not rendered again")

    def test_the_selection_survives_the_change(self):
        """Recolouring used to rebuild the reader, which threw away both the
        re-rendered page and the mark that was picked."""
        mark = self.a_mark()
        self.canvas.select_mark((0, mark))
        settle(timeout_ms=200)
        self.win.mark_recoloured((0.0, 1.0, 1.0))
        settle(timeout_ms=400)
        self.assertIsNotNone(self.canvas.selected_mark())


if __name__ == "__main__":
    unittest.main()


class TestEachToolKeepsItsOwnColour(ColourCase):
    """**The swatch shows what the next mark will be.** Each tool keeps a
    colour of its own, as Reader does, so arming one has to bring that
    colour with it -- a swatch that disagrees with the mark it makes is
    worse than no swatch."""

    def made_with(self, tool):
        """Arm ``tool``, make a mark, and report (swatch, mark) colours."""
        self.strip.arm(tool)
        settle(timeout_ms=120)
        swatch = self.strip.swatch.colour
        self.canvas.mark_drawn.emit(
            self.win.CANVAS_TOOLS[tool], 0, [(60.0, 700.0, 300.0, 714.0)])
        settle(timeout_ms=250)
        return swatch, self.win.model.annotations.for_page(self.uid())[-1].colour

    def test_the_swatch_and_the_mark_agree(self):
        """They did not: a new underline came out in the tool's own default
        while the swatch still showed the last tool's."""
        for tool in ("highlight", "underline", "strikethrough"):
            with self.subTest(tool=tool):
                swatch, made = self.made_with(tool)
                self.assertEqual(tuple(round(v, 4) for v in swatch),
                                 tuple(round(v, 4) for v in made))

    def test_each_starts_in_what_its_declaration_names(self):
        from pdfarranger_qt import markup as m
        from pdfarranger_qt import tools

        for tool in ("highlight", "underline", "strikethrough"):
            with self.subTest(tool=tool):
                self.assertEqual(
                    self.win.colour_for(tool),
                    m.swatch(tools.by_name(tool).colour))

    def test_choosing_one_leaves_the_other_tools_alone(self):
        """Picking a colour with Underline armed does not recolour the next
        highlight."""
        was = self.win.colour_for("highlight")
        self.strip.arm("underline")
        settle(timeout_ms=120)
        self.canvas.select_mark(None)
        self.win._colour_armed((0.0, 1.0, 0.0))
        self.assertEqual(self.win.colour_for("underline"), (0.0, 1.0, 0.0))
        self.assertEqual(self.win.colour_for("highlight"), was)

    def test_arming_brings_the_colour_back(self):
        self.strip.arm("underline")
        settle(timeout_ms=120)
        self.canvas.select_mark(None)
        self.win._colour_armed((0.0, 1.0, 0.0))
        self.strip.arm("highlight")
        settle(timeout_ms=120)
        self.assertNotEqual(tuple(self.strip.swatch.colour), (0.0, 1.0, 0.0))
        self.strip.arm("underline")
        settle(timeout_ms=120)
        self.assertEqual(tuple(self.strip.swatch.colour), (0.0, 1.0, 0.0))
