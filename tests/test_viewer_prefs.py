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

"""Reading and writing the keys that say how a document should be opened."""

import unittest

import pikepdf

from pdfarranger_qt import viewer


def blank():
    """A one-page document with nothing to say about how it opens."""
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    return pdf


class TestRead(unittest.TestCase):
    def test_a_plain_document_expresses_nothing(self):
        prefs = viewer.Preferences.read(blank())
        self.assertTrue(prefs.is_empty())
        self.assertIsNone(prefs.page_mode)
        self.assertIsNone(prefs.page_layout)
        self.assertEqual(prefs.flags, frozenset())

    def test_names_arrive_without_their_slash(self):
        pdf = blank()
        pdf.Root[pikepdf.Name.PageMode] = pikepdf.Name.UseOutlines
        pdf.Root[pikepdf.Name.PageLayout] = pikepdf.Name.TwoPageRight
        prefs = viewer.Preferences.read(pdf)
        self.assertEqual(prefs.page_mode, "UseOutlines")
        self.assertEqual(prefs.page_layout, "TwoPageRight")

    def test_only_true_flags_count(self):
        """An explicit false is the default, so it is not a preference."""
        pdf = blank()
        pdf.Root[pikepdf.Name.ViewerPreferences] = pikepdf.Dictionary(
            HideToolbar=True, HideMenubar=False)
        self.assertEqual(viewer.Preferences.read(pdf).flags,
                         frozenset({"HideToolbar"}))

    def test_a_junk_viewerpreferences_value_is_survived(self):
        pdf = blank()
        pdf.Root[pikepdf.Name.ViewerPreferences] = pikepdf.Name.Nonsense
        self.assertEqual(viewer.Preferences.read(pdf).flags, frozenset())


class TestWrite(unittest.TestCase):
    def round_trip(self, prefs):
        pdf = blank()
        prefs.write(pdf)
        return viewer.Preferences.read(pdf)

    def test_everything_comes_back(self):
        prefs = viewer.Preferences(
            page_mode="UseThumbs", page_layout="OneColumn",
            flags=frozenset({"CenterWindow", "DisplayDocTitle"}))
        self.assertEqual(self.round_trip(prefs), prefs)

    def test_an_empty_preference_writes_nothing(self):
        pdf = blank()
        viewer.Preferences().write(pdf)
        for key in (pikepdf.Name.PageMode, pikepdf.Name.PageLayout,
                    pikepdf.Name.ViewerPreferences):
            self.assertNotIn(key, pdf.Root)

    def test_clearing_removes_the_keys(self):
        """The point of removal: a setting that could never be turned off."""
        pdf = blank()
        viewer.Preferences(page_mode="UseOutlines", page_layout="SinglePage",
                           flags=frozenset({"HideMenubar"})).write(pdf)
        viewer.Preferences().write(pdf)
        self.assertTrue(viewer.Preferences.read(pdf).is_empty())
        self.assertNotIn(pikepdf.Name.ViewerPreferences, pdf.Root)

    def test_clearing_one_flag_keeps_the_others(self):
        pdf = blank()
        viewer.Preferences(flags=frozenset({"HideToolbar", "HideMenubar"})).write(pdf)
        viewer.Preferences(flags=frozenset({"HideMenubar"})).write(pdf)
        self.assertEqual(viewer.Preferences.read(pdf).flags,
                         frozenset({"HideMenubar"}))

    def test_a_junk_viewerpreferences_value_is_replaced(self):
        pdf = blank()
        pdf.Root[pikepdf.Name.ViewerPreferences] = pikepdf.Name.Nonsense
        viewer.Preferences(flags=frozenset({"HideToolbar"})).write(pdf)
        self.assertEqual(viewer.Preferences.read(pdf).flags,
                         frozenset({"HideToolbar"}))

    def test_it_survives_a_save(self):
        """In the file, not just in the in-memory object."""
        import io

        pdf = blank()
        wanted = viewer.Preferences(page_mode="UseOutlines",
                                    flags=frozenset({"DisplayDocTitle"}))
        wanted.write(pdf)
        buffer = io.BytesIO()
        pdf.save(buffer)
        buffer.seek(0)
        with pikepdf.open(buffer) as saved:
            self.assertEqual(viewer.Preferences.read(saved), wanted)


class TestChoices(unittest.TestCase):
    """The dialog builds itself from these lists."""

    def test_every_offered_mode_round_trips(self):
        for value, label in viewer.PAGE_MODES:
            with self.subTest(value=value):
                self.assertTrue(label())
                pdf = blank()
                viewer.Preferences(page_mode=value).write(pdf)
                self.assertEqual(viewer.Preferences.read(pdf).page_mode, value)

    def test_every_offered_layout_round_trips(self):
        for value, label in viewer.PAGE_LAYOUTS:
            with self.subTest(value=value):
                self.assertTrue(label())
                pdf = blank()
                viewer.Preferences(page_layout=value).write(pdf)
                self.assertEqual(viewer.Preferences.read(pdf).page_layout, value)

    def test_every_flag_round_trips(self):
        for name, label in viewer.FLAGS:
            with self.subTest(flag=name):
                self.assertTrue(label())
                pdf = blank()
                viewer.Preferences(flags=frozenset({name})).write(pdf)
                self.assertEqual(viewer.Preferences.read(pdf).flags,
                                 frozenset({name}))

    def test_full_screen_is_not_offered(self):
        """Deliberately omitted: taking over the screen is hostile."""
        self.assertNotIn("FullScreen", [v for v, _label in viewer.PAGE_MODES])

    def test_the_first_choice_of_each_list_means_no_preference(self):
        self.assertIsNone(viewer.PAGE_MODES[0][0])
        self.assertIsNone(viewer.PAGE_LAYOUTS[0][0])
