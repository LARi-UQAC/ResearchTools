"""
Offline tests for front_pages.py (Issue 126, plan 10 task 1, requirement F1).

Every text is fictitious (R34). No PDF is opened and no model is called (R21): the page texts and the
small-image counts are given directly.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import front_pages  # noqa: E402

COVER = "Université Exemple\nFaculté des sciences\nRapport présenté à Madame Test\nAutomne 2026"
TOC = "Table des matières\n1 Introduction ........ 3\n2 Méthodes ........ 5\n3 Résultats ........ 9\n4 Conclusion ........ 12"
LIST_FIG = "Liste des figures\nFigure 1 Schéma du montage ........ 4\nFigure 2 Courbe mesurée ........ 6\nFigure 3 Bloc ........ 8"
LIST_TAB = "Liste des tableaux\nTableau 1 Paramètres ........ 5\nTableau 2 Résultats ........ 7"
SUMMARY = "Sommaire exécutif\nCe rapport décrit un montage fictif et ses mesures."
INTRO = "1 Introduction\n" + " ".join(["mot"] * 150)
VERSION = "Historique des versions\nVersion 1.0 signature approuvée"
LONG_BODY_WITH_VERSION = " ".join(["mot"] * 160) + " version signature approuvée"


def _data() -> dict:
    """
    Purpose:
        Load the shipped front-matter data file, as the caller of front_pages does.

    Inputs:
        None.

    Outputs:
        dict: the result of front_pages.load_front_matter on the shipped file.

    Raises:
        front_pages.FrontMatterConfigError: when the shipped file is incomplete.
    """
    return front_pages.load_front_matter()


def _roles(pages: list, language: str = "fr", small: list = None) -> dict:
    """
    Purpose:
        Run find_front_roles on a list of fictitious page texts with the shipped data.

    Inputs:
        pages (list): the text of each page, in order.
        language (str): "fr" or "en".
        small (list): small-image counts per page, or None for none.

    Outputs:
        dict: the result of front_pages.find_front_roles.

    Raises:
        front_pages.FrontMatterConfigError: when the data file is incomplete.
    """
    counts = small if small is not None else [0] * len(pages)
    return front_pages.find_front_roles(pages, language, _data(), counts)


class FrenchFrontMatterTests(unittest.TestCase):
    """The French report: cover, contents, two lists, summary and body."""

    def test_toc_and_lists_found_in_french(self):
        roles = _roles([COVER, TOC, LIST_FIG, LIST_TAB, SUMMARY, INTRO], "fr")
        self.assertEqual(roles["cover"], [1])
        self.assertEqual(roles["table_of_contents"], [2])
        self.assertEqual(roles["list_of_figures"], [3])
        self.assertEqual(roles["list_of_tables"], [4])
        self.assertEqual(roles["executive_summary"], [5])
        self.assertEqual(roles["body_start"], 6)

    def test_joined_text_layer_is_still_read(self):
        """Regression (Issue 126): the text layer of a real page is one joined line, not one line per entry."""
        joined = "Liste des figures Figure 1 Schema du montage ........ 4 Figure 2 Courbe mesuree ........ 6 Figure 3 Bloc ........ 8 "
        continuation = "Figure 4 Diagramme ........ 10 Figure 5 Mesure ........ 11 Figure 6 Courbe ........ 12 "
        roles = _roles([COVER, joined, continuation, INTRO], "fr")
        self.assertEqual(roles["list_of_figures"], [2, 3])
        self.assertEqual(roles["body_start"], 4)

    def test_plural_headings_of_a_real_report_are_found(self):
        """Regression (Issue 126, real report R01): the headings read 'Tables des matieres' and 'Tables des figures'."""
        toc = "Tables des matieres\n1. Introduction ........ 3\n2. Methodes ........ 5\n3. Resultats ........ 9"
        figures = "Tables des figures\nFigure 1 Schema ........ 12\nFigure 2 Courbe ........ 14\nFigure 3 Bloc ........ 16"
        roles = _roles([COVER, toc, figures, INTRO], "fr")
        self.assertEqual(roles["table_of_contents"], [2])
        self.assertEqual(roles["list_of_figures"], [3])

    def test_summary_page_does_not_swallow_following_entry_pages(self):
        """Regression (Issue 126, real report R01): the summary is one page; entry pages after it are not its own."""
        entries = "1. Introduction ........ 3 2. Methodes ........ 5 3. Resultats ........ 9 4. Conclusion ........ 12"
        roles = _roles([COVER, SUMMARY, entries, INTRO], "fr")
        self.assertEqual(roles["executive_summary"], [2])
        self.assertEqual(roles["body_start"], 3)

    def test_last_page_with_two_entries_continues_the_list(self):
        """Review round 1 I2 (Issue 126): a list ends at its last entry, however few entries that page holds."""
        last = "Figure 4 Diagramme ........ 10 Figure 5 Mesure ........ 11 "
        roles = _roles([COVER, LIST_FIG, last, INTRO], "fr")
        self.assertEqual(roles["list_of_figures"], [2, 3])
        self.assertEqual(roles["body_start"], 4)

    def test_chapter_only_toc_is_not_a_list_of_figures(self):
        roles = _roles([COVER, TOC, INTRO], "fr")
        self.assertEqual(roles["table_of_contents"], [2])
        self.assertIsNone(roles["list_of_figures"])
        self.assertIsNone(roles["list_of_tables"])

    def test_list_over_two_pages_has_both_pages(self):
        continuation = "Figure 4 Diagramme ........ 10\nFigure 5 Mesure ........ 11\nFigure 6 Courbe ........ 12"
        roles = _roles([COVER, LIST_FIG, continuation, INTRO], "fr")
        self.assertEqual(roles["list_of_figures"], [2, 3])
        self.assertEqual(roles["body_start"], 4)

    def test_missing_executive_summary_is_none(self):
        roles = _roles([COVER, TOC, INTRO], "fr")
        self.assertIsNone(roles["executive_summary"])

    def test_body_start_is_page_after_front_matter(self):
        roles = _roles([COVER, TOC, LIST_FIG, INTRO], "fr")
        self.assertEqual(roles["body_start"], 4)

    def test_no_front_matter_starts_at_page_one(self):
        roles = _roles([INTRO, INTRO], "fr")
        self.assertEqual(roles["body_start"], 1)
        self.assertIsNone(roles["cover"])

    def test_version_page_with_long_body_not_matched(self):
        roles = _roles([COVER, LONG_BODY_WITH_VERSION], "fr")
        self.assertIsNone(roles["version_signature"])
        self.assertEqual(roles["body_start"], 2)

    def test_version_page_found(self):
        roles = _roles([COVER, VERSION, INTRO], "fr")
        self.assertEqual(roles["version_signature"], [2])
        self.assertEqual(roles["body_start"], 3)


class EnglishFrontMatterTests(unittest.TestCase):
    """The English markers are read only for an English report."""

    def test_english_lists_found(self):
        cover = "University Example\nFaculty of science\nReport submitted to Ms Test\nFall 2026"
        figures = "List of figures\nFigure 1 Circuit ........ 3\nFigure 2 Curve ........ 4\nFigure 3 Block ........ 5"
        tables = "List of tables\nTable 1 Parameters ........ 6\nTable 2 Results ........ 7"
        roles = _roles([cover, figures, tables, INTRO], "en")
        self.assertEqual(roles["list_of_figures"], [2])
        self.assertEqual(roles["list_of_tables"], [3])
        self.assertEqual(roles["body_start"], 4)

    def test_french_heading_not_read_in_english_report(self):
        roles = _roles([COVER, LIST_FIG, INTRO], "en")
        self.assertIsNone(roles["list_of_figures"])


class ConfigurationTests(unittest.TestCase):
    """A missing key is a named error that names the key and the file (R3)."""

    def _write(self, data: dict) -> Path:
        """
        Purpose:
            Write a data file in a temporary folder.

        Inputs:
            data (dict): the JSON object to write.

        Outputs:
            Path: the written file (inside a directory kept alive by the caller).

        Raises:
            OSError: when the folder cannot be written.
        """
        folder = Path(tempfile.mkdtemp())
        path = folder / "front_matter.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_missing_marker_key_is_named(self):
        data = json.loads((SCRIPTS.parent / "assets" / "front_matter.json").read_text(encoding="utf-8"))
        del data["figure_list_markers"]
        path = self._write(data)
        with self.assertRaises(front_pages.FrontMatterConfigError) as ctx:
            front_pages.load_front_matter(path)
        self.assertIn("figure_list_markers", str(ctx.exception))
        self.assertIn(str(path), str(ctx.exception))

    def test_missing_language_is_named(self):
        data = json.loads((SCRIPTS.parent / "assets" / "front_matter.json").read_text(encoding="utf-8"))
        del data["table_list_markers"]["en"]
        path = self._write(data)
        with self.assertRaises(front_pages.FrontMatterConfigError) as ctx:
            front_pages.load_front_matter(path)
        self.assertIn("en", str(ctx.exception))

    def test_unknown_language_refused(self):
        with self.assertRaises(front_pages.FrontMatterConfigError):
            _roles([COVER], "de")


class LanguageModeTests(unittest.TestCase):
    """Issue 126 plan 16 N3: the correction mode of each front role comes from the data file."""

    def test_page_modes_map_each_front_role(self):
        roles = _roles([COVER, TOC, LIST_FIG, SUMMARY, INTRO], "fr")
        modes = front_pages.page_modes(roles, _data())
        self.assertEqual(modes[1], "none")
        self.assertEqual(modes[2], "spelling_only")
        self.assertEqual(modes[3], "spelling_only")
        self.assertEqual(modes[4], "full")
        self.assertNotIn(5, modes)

    def test_unknown_mode_is_named_error(self):
        data = json.loads((SCRIPTS.parent / "assets" / "front_matter.json").read_text(encoding="utf-8"))
        data["language_mode"]["value"]["cover"] = "judge"
        path = Path(tempfile.mkdtemp()) / "front_matter.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(front_pages.FrontMatterConfigError) as ctx:
            front_pages.load_front_matter(path)
        self.assertIn("judge", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
