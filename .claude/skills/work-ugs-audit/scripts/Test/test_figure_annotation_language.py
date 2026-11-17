"""
Figure annotations in the report language (Issue 122, plan 6 task 2, spec R6).

A figure criterion judged by a script that fails gets its comment from the criteria data in the
report language (failure_comment of figure-review's figure_checks); a criterion judged by a model keeps
the reason the model wrote. Offline: the criteria and the figures are fictitious (R34), the PDF writers
are mocked, and the one real-data read is the shipped criteria file, which holds no report text.
Run as: python .claude/skills/work-ugs-audit/scripts/Test/test_figure_annotation_language.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts"))
sys.path.insert(0, str(SCRIPTS.parent.parent / "figure-review" / "scripts" / "Test"))

import ugs_assemble  # noqa: E402
from figure_checks import load_criteria  # noqa: E402
from _pdf_fixtures import make_report  # noqa: E402

SHIPPED_CRITERIA = SCRIPTS.parent.parent / "figure-review" / "assets" / "figure_criteria.json"

FAKE_CRITERIA = [
    {"id": "scr_fake", "judged_by": "script",
     "comment_fr": "Commentaire scripte FR", "comment_en": "Script comment EN"},
    {"id": "mod_fake", "judged_by": "model",
     "comment_fr": "Commentaire modele FR", "comment_en": "Model comment EN"},
]

FAKE_FIGURES = {
    "report_id": "R01",
    "figures": [
        {
            "figure_id": "F01",
            "page": 2,
            "rect": [1, 2, 3, 4],
            "criteria": {
                "scr_fake": {"verdict": "fail", "reason": "measured 40 percent"},
                "mod_fake": {"verdict": "fail", "reason": "Model wrote this"},
            },
        }
    ],
}


def _by_code(annotations, code):
    """
    Purpose: Pick the one annotation carrying a criterion code.
    Inputs:
        annotations: list - Annotation dictionaries.
        code: str - Criterion id.
    Outputs:
        dict - The matching annotation.
    Raises:
        AssertionError: If no annotation or more than one carries the code.
    """
    found = [a for a in annotations if a["code"] == code]
    assert len(found) == 1, f"expected one annotation for {code}, got {len(found)}"
    return found[0]


class TestFigureAnnotationLanguage(unittest.TestCase):
    def test_script_failure_uses_the_french_comment(self):
        annotations = ugs_assemble.figure_annotations(FAKE_FIGURES, FAKE_CRITERIA, "fr")
        self.assertEqual(_by_code(annotations, "scr_fake")["comment"], "Commentaire scripte FR")

    def test_script_failure_uses_the_english_comment(self):
        annotations = ugs_assemble.figure_annotations(FAKE_FIGURES, FAKE_CRITERIA, "en")
        self.assertEqual(_by_code(annotations, "scr_fake")["comment"], "Script comment EN")

    def test_model_reason_is_kept_in_both_languages(self):
        for language in ("fr", "en"):
            with self.subTest(language=language):
                annotations = ugs_assemble.figure_annotations(FAKE_FIGURES, FAKE_CRITERIA, language)
                self.assertEqual(_by_code(annotations, "mod_fake")["comment"], "Model wrote this")

    def test_without_criteria_nothing_changes(self):
        annotations = ugs_assemble.figure_annotations(FAKE_FIGURES)
        self.assertEqual(_by_code(annotations, "scr_fake")["comment"], "measured 40 percent")
        self.assertEqual(_by_code(annotations, "mod_fake")["comment"], "Model wrote this")

    def test_unknown_language_is_named(self):
        with self.assertRaises(ValueError) as ctx:
            ugs_assemble.figure_annotations(FAKE_FIGURES, FAKE_CRITERIA, "de")
        self.assertIn("de", str(ctx.exception))

    def test_unknown_language_is_refused_even_without_criteria(self):
        with self.assertRaises(ValueError):
            ugs_assemble.figure_annotations(FAKE_FIGURES, None, "de")


class TestAssembleReportLanguage(unittest.TestCase):
    """The shipped criteria and the report language reach the figure annotations."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        # Real layout: the work folder holds the report folder (R01) with its metadata, and the loop folder.
        source_dir = self.tmp_dir / "R01"
        source_dir.mkdir()
        (source_dir / "report_meta.json").write_text(
            json.dumps({"language": "en", "excluded_pages": [], "text_quality": {}}), encoding="utf-8")
        self.report_dir = self.tmp_dir / "loop-1" / "R01"
        self.report_dir.mkdir(parents=True)
        self.src_pdf = self.report_dir / "source.pdf"
        make_report(self.src_pdf, [{"text": "Figure text"}])
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 100,
            "items": [
                {"id": "I01", "title": "Intro", "max_points": 50, "criteria": [], "checklist": []},
                {"id": "I02", "title": "Body", "max_points": 50, "criteria": [], "checklist": []},
            ],
        }
        grade = {
            "report_id": "R01",
            "loop": 1,
            "items": [
                {"item_id": "I01", "status": "rated", "score": 45.0, "comment": "Good",
                 "evidence": [{"page": 1, "quote": "Figure"}]},
                {"item_id": "I02", "status": "not_run", "score": None, "comment": "", "evidence": []},
            ],
        }
        (self.report_dir / "grade.json").write_text(json.dumps(grade), encoding="utf-8")
        self.settings = {
            "colors": {"technical": "#0000ff", "figure": "#00ff00", "reference": "#ff0000",
                       "language": "#000000"},
            "author": "Prof. Test",
            "quote_chars": 10,
            "url_timeout_s": 5,
            "max_retries": 2,
            "patterns": [],
            "ref_comments": {
                "malformed": {"en": "Malformed", "fr": "Malforme"},
                "unreachable": {"en": "Unreachable", "fr": "Inaccessible"},
                "blocked": {"en": "Blocked", "fr": "Bloque"},
                "uncited": {"en": "Uncited", "fr": "Non cite"},
            },
            "annex_template": "<html><body>{{REPORT_ID}} {{LOOP}} {{ROWS}} {{TOTAL}}</body></html>",
        }

    def _run_assemble(self, language):
        """
        Purpose: Run assemble_report on the fixture folder with the PDF writers mocked.
        Inputs:
            language: str - Report language passed to assemble_report.
        Outputs:
            list - The annotations written to annotations.json.
        Raises:
            AssertionError: Propagated from the assertions of the caller only.
        """
        figures = {
            "report_id": "R01",
            "figures": [
                {"figure_id": "F01", "page": 1, "rect": [1, 1, 5, 5],
                 "criteria": {"space_used_over_70": {"verdict": "fail", "reason": "measured"}}}
            ],
        }
        (self.report_dir / "figures.json").write_text(json.dumps(figures), encoding="utf-8")

        def fake_annotate(src, items, dst, colors, author):
            Path(dst).write_bytes(Path(src).read_bytes())
            return {"placed": 1, "not_found": [], "duplicates": []}

        with patch.object(ugs_assemble, "annotate", side_effect=fake_annotate), \
                patch.object(ugs_assemble, "append_annex", return_value=1):
            ugs_assemble.assemble_report(
                self.src_pdf, self.report_dir, "R01", 1, self.rubric, ["Figure text"],
                language, self.settings, fetch=None,
            )
        return json.loads((self.report_dir / "annotations.json").read_text(encoding="utf-8"))

    def test_report_in_french_gets_the_french_script_comment(self):
        expected = _shipped_comment("space_used_over_70", "comment_fr")
        annotations = self._run_assemble("fr")
        self.assertEqual(_by_code(annotations, "space_used_over_70")["comment"], expected)

    def test_report_in_english_gets_the_english_script_comment(self):
        expected = _shipped_comment("space_used_over_70", "comment_en")
        annotations = self._run_assemble("en")
        self.assertEqual(_by_code(annotations, "space_used_over_70")["comment"], expected)

    def test_assemble_refuses_an_unknown_language_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            self._run_assemble("de")
        self.assertIn("de", str(ctx.exception))


def _shipped_comment(criterion_id, key):
    """
    Purpose: Read one comment of a shipped figure criterion, the expected value of a test.
    Inputs:
        criterion_id: str - Id of the criterion in the shipped criteria file.
        key: str - "comment_fr" or "comment_en".
    Outputs:
        str - The comment text.
    Raises:
        AssertionError: If the criterion is not in the shipped file.
    """
    for crit in load_criteria(SHIPPED_CRITERIA)["criteria"]:
        if crit["id"] == criterion_id:
            return crit[key]
    raise AssertionError(f"criterion {criterion_id} not in the shipped file")


if __name__ == "__main__":
    unittest.main()
