"""
Purpose: Offline tests of the annex labels and of the annex layout (spec R8, plan 7 task 1).
Details: Fictitious report PDFs and fictitious grade data only (R34). Layout numbers are read from
    annex_labels.json, never restated here (R0). Word boxes come from PyMuPDF get_text("words").
"""
import ast
import html as html_lib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ASSETS = SCRIPTS.parent / "assets"
LABELS_FILE = ASSETS / "annex_labels.json"
GRADE_FILE = SCRIPTS / "ugs_grade.py"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts" / "Test"))

import fitz  # noqa: E402
import pdf_annex  # noqa: E402
from _pdf_fixtures import make_report  # noqa: E402

PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
TOLERANCE = 0.5


def _layout_margin() -> float:
    """
    Purpose: Read the page margin from the labels file, the one place the layout numbers live.
    Inputs: none.
    Outputs:
        float - The page margin in points.
    """
    data = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    return float(data["layout"]["page_margin"])


def _fixture_rubric() -> dict:
    """
    Purpose: Build a fictitious rubric with three items.
    Inputs: none.
    Outputs:
        dict - A rubric with the keys items (id, title, max_points).
    """
    return {"items": [
        {"id": "I01", "title": "Critère alpha", "max_points": 1.0},
        {"id": "I02", "title": "Critère beta", "max_points": 2.0},
        {"id": "I03", "title": "Critère gamma", "max_points": 1.0},
    ]}


def _fixture_grade() -> dict:
    """
    Purpose: Build fictitious grade data: one rated, one not run, one with a refused proof.
    Inputs: none.
    Outputs:
        dict - A grade with the key items.
    """
    return {"items": [
        {"item_id": "I01", "status": "rated", "score": 0.5, "comment": "Bon départ.",
         "validation": "ok"},
        {"item_id": "I02", "status": "not_run", "score": None, "comment": ""},
        {"item_id": "I03", "status": "rated", "score": 0.0, "comment": "Citation absente.",
         "validation": "quote_not_found"},
    ]}


def _fixture_totals() -> dict:
    """
    Purpose: Build fictitious totals.
    Inputs: none.
    Outputs:
        dict - Totals with the key total.
    """
    return {"total": "0.5", "by_item": {"I01": 0.5, "I02": None, "I03": 0.0}}


class TestAnnexLayout(unittest.TestCase):
    """
    Purpose: Labels by language, refused-proof labels, excluded note and the layout of the annex.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmpdir.name)
        self.pdf_path = self.test_dir / "report.pdf"
        make_report(self.pdf_path, [{"text": "Page 1 content", "font_size": 12}])
        self.fr = pdf_annex.load_labels(LABELS_FILE, "fr")
        self.en = pdf_annex.load_labels(LABELS_FILE, "en")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _html(self, labels, grade=None, excluded_note="", template=None):
        """
        Purpose: Render the complete annex HTML for the fixtures with the given labels.
        Inputs:
            labels: dict - The labels of one language.
            grade: dict or None - The grade data; the fixture when None.
            excluded_note: str - The excluded-pages note.
            template: str or None - The template text; the shipped template when None.
        Outputs:
            str - The final HTML.
        """
        grade = grade or _fixture_grade()
        if template is None:
            template = (ASSETS / "annex.template.html").read_text(encoding="utf-8")
        rows = pdf_annex.render_rows(_fixture_rubric(), grade, _fixture_totals(), labels)
        return pdf_annex.build_html(template, rows, "R01", 1, "0.5", labels, excluded_note)

    def _added_words(self, long_comment=None, grade=None):
        """
        Purpose: Append the annex to the fixture PDF and return the word boxes of the added pages.
        Inputs:
            long_comment: str or None - Replaces the comment of item I01 when given.
            grade: dict or None - Replaces the grade data when given.
        Outputs:
            tuple - (pages_added, list of (x0, y0, x1, y1, word), the page rectangle).
        """
        grade = grade or _fixture_grade()
        if long_comment is not None:
            grade["items"][0]["comment"] = long_comment
        html_text = self._html(self.fr, grade)
        pages_added = pdf_annex.append_annex(self.pdf_path, html_text)
        doc = fitz.open(str(self.pdf_path))
        words = []
        for index in range(doc.page_count - pages_added, doc.page_count):
            for word in doc[index].get_text("words"):
                words.append((word[0], word[1], word[2], word[3], word[4]))
        rect = doc[doc.page_count - 1].rect
        doc.close()
        return pages_added, words, rect

    def _assert_inside_margins(self, words, rect):
        """
        Purpose: Assert that every word box lies inside the page minus the margin.
        Inputs:
            words: list - The word boxes (x0, y0, x1, y1, word).
            rect: fitz.Rect - The page rectangle.
        Outputs: none. Fails the test on the first word outside the margins.
        """
        margin = _layout_margin()
        self.assertTrue(words, "no word was rendered on the annex pages")
        for x0, y0, x1, y1, word in words:
            self.assertGreaterEqual(x0, margin - TOLERANCE, word)
            self.assertLessEqual(x1, rect.x1 - margin + TOLERANCE, word)
            self.assertGreaterEqual(y0, margin - TOLERANCE, word)
            self.assertLessEqual(y1, rect.y1 - margin + TOLERANCE, word)

    # Labels by language

    def test_french_labels_only_in_the_html(self):
        html_text = self._html(self.fr)
        self.assertIn(html_lib.escape(self.fr["title"]), html_text)
        self.assertIn(html_lib.escape(self.fr["comment"]), html_text)
        self.assertNotIn("Completed rubric", html_text)
        self.assertNotIn("Commentaire / Comment", html_text)
        self.assertNotIn("Élément / Item", html_text)

    def test_english_labels_only_in_the_html(self):
        html_text = self._html(self.en)
        self.assertIn(html_lib.escape(self.en["title"]), html_text)
        self.assertIn(html_lib.escape(self.en["comment"]), html_text)
        self.assertNotIn(self.fr["title"], html_text)
        self.assertNotIn("Élément", html_text)
        self.assertNotIn("Commentaire", html_text)

    def test_unknown_language_is_named(self):
        with self.assertRaises(pdf_annex.AnnexError) as ctx:
            pdf_annex.load_labels(LABELS_FILE, "de")
        self.assertIn("de", str(ctx.exception))

    def test_missing_key_is_named_with_its_file(self):
        broken = self.test_dir / "labels.json"
        data = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
        del data["fr"]["comment"]
        broken.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(pdf_annex.AnnexError) as ctx:
            pdf_annex.load_labels(broken, "fr")
        self.assertIn("comment", str(ctx.exception))
        self.assertIn("labels.json", str(ctx.exception))

    def test_validation_labels_cover_every_refusal_code(self):
        tree = ast.parse(GRADE_FILE.read_text(encoding="utf-8"))
        codes = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "GRADE_CODES" for t in node.targets
            ):
                codes = [elt.value for elt in node.value.elts]
        self.assertIsNotNone(codes)
        refusals = [code for code in codes if code != "ok"]
        for labels in (self.fr, self.en):
            self.assertEqual(sorted(labels["validation_values"]), sorted(refusals))
            self.assertNotIn("ok", labels["validation_values"])

    def test_status_label_is_translated(self):
        fr_html = self._html(self.fr)
        en_html = self._html(self.en)
        self.assertIn(html_lib.escape(self.fr["status_values"]["rated"]), fr_html)
        self.assertNotIn(">rated<", fr_html)
        self.assertIn(html_lib.escape(self.en["status_values"]["rated"]), en_html)
        self.assertNotIn(">évalué<", en_html)

    def test_not_run_is_shown_by_its_label(self):
        fr_html = self._html(self.fr)
        self.assertIn(html_lib.escape(self.fr["status_values"]["not_run"]), fr_html)
        self.assertNotIn("not_run", fr_html)

    def test_refused_proof_shows_its_label_under_the_comment(self):
        rows = pdf_annex.render_rows(_fixture_rubric(), _fixture_grade(), _fixture_totals(), self.fr)
        label = html_lib.escape(self.fr["validation_values"]["quote_not_found"])
        self.assertEqual(rows.count(label), 1)
        self.assertIn(f"Citation absente.", rows)
        self.assertLess(rows.index("Citation absente."), rows.index(label))

    def test_ok_or_absent_validation_shows_no_label(self):
        grade = _fixture_grade()
        grade["items"][2]["validation"] = "ok"
        rows = pdf_annex.render_rows(_fixture_rubric(), grade, _fixture_totals(), self.fr)
        for code, label in self.fr["validation_values"].items():
            self.assertNotIn(html_lib.escape(label), rows, code)

    def test_excluded_note_is_shown_when_given(self):
        html_text = self._html(self.fr, excluded_note="Page de garde exclue")
        self.assertIn("Page de garde exclue", html_text)
        self.assertNotIn("{{EXCLUDED}}", html_text)

    def test_no_placeholder_left(self):
        for labels in (self.fr, self.en):
            self.assertIsNone(PLACEHOLDER.search(self._html(labels)))

    def test_labels_none_keeps_the_previous_rendering(self):
        rows = pdf_annex.render_rows(_fixture_rubric(), _fixture_grade(), _fixture_totals())
        self.assertIn("not_run", rows)
        self.assertIn("0.5 / 1", rows)

    # Layout

    def test_no_word_outside_the_margins_for_a_long_comment(self):
        long_comment = "Cette remarque est très longue et doit se replier sur plusieurs lignes. " * 20
        _, words, rect = self._added_words(long_comment=long_comment)
        self._assert_inside_margins(words, rect)

    def test_long_unbroken_string_stays_inside(self):
        address = "https://exemple.invalide/" + "a" * 300
        _, words, rect = self._added_words(long_comment=address)
        self._assert_inside_margins(words, rect)

    def test_table_continues_on_the_next_page(self):
        grade = _fixture_grade()
        grade["items"][0]["comment"] = "Commentaire de longueur moyenne pour tester la pagination. " * 6
        rubric = {"items": [
            {"id": f"J{n:03d}", "title": f"Critère numéro {n}", "max_points": 1.0} for n in range(80)
        ]}
        grade = {"items": [
            {"item_id": f"J{n:03d}", "status": "rated", "score": 1.0, "comment": grade["items"][0]["comment"],
             "validation": "ok"} for n in range(80)
        ]}
        rows = pdf_annex.render_rows(rubric, grade, _fixture_totals(), self.fr)
        html_text = pdf_annex.build_html(
            (ASSETS / "annex.template.html").read_text(encoding="utf-8"),
            rows, "R01", 1, "0.5", self.fr, "")
        pages_added = pdf_annex.append_annex(self.pdf_path, html_text)
        self.assertGreaterEqual(pages_added, 2)
        full = ""
        doc = fitz.open(str(self.pdf_path))
        for index in range(doc.page_count - pages_added, doc.page_count):
            full += doc[index].get_text()
        doc.close()
        self.assertIn("Critère numéro 79", full)

    def test_french_annex_fits_the_page(self):
        _, words, rect = self._added_words()
        self._assert_inside_margins(words, rect)


if __name__ == "__main__":
    unittest.main()
