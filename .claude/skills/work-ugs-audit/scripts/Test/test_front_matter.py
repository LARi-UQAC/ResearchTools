"""
Offline tests for front_matter.py (Issue 126, plan 5 task 1, requirement E1).

Every text is fictitious (R34). No PDF is opened and no model is called (R21): the page texts and the front roles
are given directly.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import front_matter  # noqa: E402

FIG_LIST = ("Liste des figures\nFigure 1. Schema du montage ........ 4\nFigure 2. Courbe mesuree ........ 6\n"
            "Figure 3. Bloc de commande ........ 8")
TAB_LIST = "List of tables\nTable 1. Parameters ........ 5\nTable 2. Results ........ 7"
TOC = "Table des matieres\n1 Introduction ........ 3\n2 Methodes ........ 5"


def _roles(**kwargs) -> dict:
    """
    Purpose:
        Build a front-roles dict in the shape front_pages.find_front_roles returns, with the given pages.

    Inputs:
        kwargs: role name and its list of 1-based pages.

    Outputs:
        dict: every role of the shape, None unless given.

    Raises:
        None.
    """
    base = {"cover": None, "version_signature": None, "table_of_contents": None, "list_of_figures": None,
            "list_of_tables": None, "executive_summary": None, "body_start": 1}
    base.update(kwargs)
    return base


def _counts(pages, roles, language="fr", settings=None):
    """
    Purpose:
        Run declared_counts with the shipped entry settings unless some are given.

    Inputs:
        pages (list): the text of each page.
        roles (dict): the front roles.
        language (str): "fr" or "en".
        settings (dict or None): entry settings; None loads the shipped file.

    Outputs:
        dict: the result of front_matter.declared_counts.

    Raises:
        front_matter.FrontMatterEntryError: when the settings are incomplete.
    """
    loaded = settings if settings is not None else front_matter.load_entry_settings()
    return front_matter.declared_counts(pages, roles, language, loaded)


class CountTests(unittest.TestCase):
    """The declared counts of the lists, read from the printed entries."""

    def test_french_list_of_figures_counted(self):
        result = _counts([FIG_LIST], _roles(list_of_figures=[1]), "fr")
        self.assertEqual(result["declared_figures"], 3)
        self.assertEqual(result["declared_figure_numbers"], ["1", "2", "3"])
        self.assertEqual(result["declared_figure_pages"], [1, 1, 1])

    def test_english_list_of_tables_counted(self):
        result = _counts([TAB_LIST], _roles(list_of_tables=[1]), "en")
        self.assertEqual(result["declared_tables"], 2)
        self.assertEqual(result["declared_table_numbers"], ["1", "2"])

    def test_wrapped_entry_counted_once(self):
        text = "Liste des figures\nFigure 1. Long title that\ncontinues on the next line ........ 4"
        result = _counts([text], _roles(list_of_figures=[1]))
        self.assertEqual(result["declared_figures"], 1)

    def test_dot_leaders_and_page_read_not_counted(self):
        text = "Liste des figures\nFigure 1. Schema ........ 12"
        result = _counts([text], _roles(list_of_figures=[1]))
        self.assertEqual(result["declared_figure_numbers"], ["1"])

    def test_two_part_numbers_kept_as_printed(self):
        text = "Liste des figures\nFigure 2.1 Premier schema ........ 9\nFigure A.1 Annexe ........ 40"
        result = _counts([text], _roles(list_of_figures=[1]))
        self.assertEqual(result["declared_figure_numbers"], ["2.1", "A.1"])

    def test_missing_list_is_none_not_zero(self):
        result = _counts([TOC], _roles(table_of_contents=[1]))
        self.assertIsNone(result["declared_figures"])
        self.assertIsNone(result["declared_tables"])

    def test_list_heading_with_no_entry_is_zero(self):
        result = _counts(["Liste des figures\n"], _roles(list_of_figures=[1]))
        self.assertEqual(result["declared_figures"], 0)
        self.assertEqual(result["declared_figure_numbers"], [])

    def test_duplicate_number_is_listed_and_both_kept(self):
        text = "Liste des figures\nFigure 3. Premier ........ 4\nFigure 3. Second ........ 5"
        result = _counts([text], _roles(list_of_figures=[1]))
        self.assertEqual(result["declared_figures"], 2)
        self.assertEqual(result["duplicate_numbers"], ["figure 3"])

    def test_missing_entry_key_is_named(self):
        data = json.loads((SCRIPTS.parent / "assets" / "front_matter.json").read_text(encoding="utf-8"))
        del data["figure_entry_words"]
        path = Path(tempfile.mkdtemp()) / "front_matter.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(front_matter.FrontMatterEntryError) as ctx:
            front_matter.load_entry_settings(path)
        self.assertIn("figure_entry_words", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
