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

"""Every visible string comes from a catalogue, and keeps doing so.

Two different claims, and the second is the one with teeth:

- a window *built* in a language is translated -- which was already true, and
  is here so that a failure of the harness is not mistaken for a failure of
  the feature;
- a window *already open* follows a language change, which is what Preferences
  promises and what used to need a restart.

See `pseudo` for why a generated locale rather than a real one.
"""

import unittest

import pseudo

from support import TEST_PDF, settle


class PseudolocaleTestCase(unittest.TestCase):
    def setUp(self):
        from pdfarranger_qt import i18n

        pseudo.install(self)
        i18n.setup(pseudo.LOCALE)

    def window(self, with_document=True):
        from pdfarranger_qt.mainwindow import MainWindow

        win = MainWindow()
        self.addCleanup(win.close)
        if with_document:
            win.open_paths([TEST_PDF])
            settle(timeout_ms=300)
        self.addCleanup(setattr, win, "modified", False)
        return win


class TestTheHarness(PseudolocaleTestCase):
    """If these fail, nothing below means anything."""

    def test_the_pseudolocale_covers_the_whole_template(self):
        import os

        from babel.messages.pofile import read_po

        from pdfarranger_qt import i18n

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "po", "pdfarranger.pot"), encoding="utf-8") as fh:
            ids = [m.id for m in read_po(fh) if m.id]
        self.assertGreater(len(ids), 400, "the template looks empty")
        for one in ids:
            single = one[0] if isinstance(one, tuple) else one
            with self.subTest(msgid=single):
                self.assertTrue(i18n.gettext_(single).startswith(pseudo.MARK))

    def test_an_untranslated_string_is_visible_as_such(self):
        """The assertion the tests below rely on can actually fail."""
        self.assertFalse(pseudo.MARK + "x" == "x")
        self.assertNotIn(pseudo.MARK, "Add Page Numbers…")


class TestBuiltInALanguage(PseudolocaleTestCase):
    def test_nothing_in_a_fresh_window_is_untranslated(self):
        missed = pseudo.unmarked(self.window())
        self.assertEqual(missed, [], f"{len(missed)} strings came from no catalogue")


class TestFollowsALanguageChange(PseudolocaleTestCase):
    """The window is already open when the language changes.

    This is what Preferences offers, and what used to require quitting the
    application -- while the theme control beside it applied at once.
    """

    def setUp(self):
        super().setUp()
        from pdfarranger_qt import i18n

        # Built in English, then switched: the reverse of the case above.
        i18n.setup("xx")

    def test_the_menu_bar_follows(self):
        win = self.window()
        before = [a.text() for a in win.menuBar().actions()]
        self.assertTrue(all(not t.startswith(pseudo.MARK) for t in before), before)

        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()

        after = [a.text() for a in win.menuBar().actions()]
        self.assertTrue(all(t.startswith(pseudo.MARK) for t in after), after)

    def test_every_string_follows(self):
        win = self.window()
        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        missed = pseudo.unmarked(win)
        self.assertEqual(missed, [],
                         f"{len(missed)} strings did not follow the change")

    def test_it_survives_being_done_twice(self):
        """Switching away and back must not leave a doubly-marked string."""
        win = self.window()
        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        i18n.setup("xx")
        win.retranslate()
        self.assertTrue(all(not a.text().startswith(pseudo.MARK)
                            for a in win.menuBar().actions()))
        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        for action in win.menuBar().actions():
            self.assertFalse(action.text().startswith(pseudo.MARK * 2),
                             f"marked twice: {action.text()!r}")

    def test_the_checked_state_of_a_toggle_survives(self):
        """Retranslating must not rebuild the actions out from under their state."""
        win = self.window()
        win.act_strip_metadata.setChecked(True)
        win.act_fullscreen.setChecked(False)
        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        self.assertTrue(win.act_strip_metadata.isChecked())
        self.assertFalse(win.act_fullscreen.isChecked())

    def test_a_shortcut_survives(self):
        from PySide6.QtGui import QKeySequence

        win = self.window()
        before = win.act_save.shortcut()
        self.assertFalse(before.isEmpty())
        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        self.assertEqual(win.act_save.shortcut(), QKeySequence(before))

    def test_the_actions_are_the_same_objects(self):
        """Rebuilding them would break every connection made to them."""
        win = self.window()
        same = win.act_save
        from pdfarranger_qt import i18n

        i18n.setup(pseudo.LOCALE)
        win.retranslate()
        self.assertIs(win.act_save, same)


if __name__ == "__main__":
    unittest.main()
