"""
Offline tests of the report language (plan 6, Task 1, R6): the language comes from report_meta.json when it is
present and valid, falls back to the existing detector when it is absent, and reaches the audit prompt, which
must carry no placeholder left unfilled. Fictitious text only (R34); no model, no network.
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
_LOOP_ENGINEER_SCRIPTS = _SCRIPTS_DIR.parent.parent / "loop-engineer" / "scripts"
if _LOOP_ENGINEER_SCRIPTS.exists() and str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from ugs_run import report_language, LanguageError
from ugs_audit import audit_item
from ugs_bridge import NotRun
from ugs_text import StepContext, PromptError

PROMPT_PATH = _SCRIPTS_DIR.parent / "prompts" / "audit_item.md"
META_NAME = "report_meta.json"

HINTS = {
    "fr": ["le", "la", "les", "des", "et", "une"],
    "en": ["the", "and", "of", "to", "is", "with"],
}
FRENCH_PAGE = "Le rapport présente la méthode et les résultats des essais, et la conclusion des mesures."
ENGLISH_PAGE = "The report shows the method and the results of the tests, with the conclusion of the measures."


class FakeCall:
    """Records every prompt it is given and answers with a fixed verdict."""

    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, schema, images=None):
        self.prompts.append(prompt)
        return {"verdict": "agree", "reason": "ok"}


def make_ctx(template):
    return StepContext(
        prompts={"audit_item": template},
        schemas={"audit_item": {"type": "object"}},
        levels={"absent": 0, "complete": 0.88},
        window_tokens=100000,
        reserve_tokens=100,
        count=lambda text: len(text) // 4,
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


class TestReportLanguage(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work_dir = self.tmp / "work"
        (self.work_dir / "R01").mkdir(parents=True)
        self.meta_path = self.work_dir / "R01" / META_NAME

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_language_read_from_meta(self):
        """The metadata wins over the detector: English-looking pages with a French metadata answer French."""
        self.meta_path.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
        result = report_language(self.work_dir, "R01", [ENGLISH_PAGE], HINTS)
        self.assertEqual(result, "fr")

    def test_language_falls_back_to_detector(self):
        """Without the metadata file the detector decides exactly as before, and an empty hint set gives English."""
        self.assertFalse(self.meta_path.exists())
        self.assertEqual(report_language(self.work_dir, "R01", [FRENCH_PAGE], HINTS), "fr")
        self.assertEqual(report_language(self.work_dir, "R01", [ENGLISH_PAGE], HINTS), "en")
        self.assertEqual(report_language(self.work_dir, "R01", [FRENCH_PAGE], {}), "en")

    def test_invalid_language_is_named(self):
        """A value other than fr or en is a named error naming the value and the file, never a silent English."""
        self.meta_path.write_text(json.dumps({"language": "de"}), encoding="utf-8")
        with self.assertRaises(LanguageError) as ctx:
            report_language(self.work_dir, "R01", [FRENCH_PAGE], HINTS)
        message = str(ctx.exception)
        self.assertIn("de", message)
        self.assertIn(META_NAME, message)
        self.assertNotIn("Le rapport", message)

    def test_missing_language_key_is_named(self):
        """A metadata file with no language key is refused by name (R3), not read as the detector's answer."""
        self.meta_path.write_text(json.dumps({"excluded_pages": []}), encoding="utf-8")
        with self.assertRaises(LanguageError) as ctx:
            report_language(self.work_dir, "R01", [FRENCH_PAGE], HINTS)
        self.assertIn("language", str(ctx.exception))
        self.assertIn(META_NAME, str(ctx.exception))


class TestAuditPromptLanguage(unittest.TestCase):

    def setUp(self):
        self.template = PROMPT_PATH.read_text(encoding="utf-8")
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.record = {"item_id": "I01", "status": "rated", "score": 8.0, "comment": "Bonne introduction",
                       "evidence": [{"page": 1, "quote": "text"}], "audit": "not_run", "flag": False}
        self.pages = ["page one text", "page two text"]

    def test_audit_prompt_carries_the_language_and_no_placeholder_is_left(self):
        """The language is filled, the sentence about it is present, and no placeholder of the prompt remains."""
        call = FakeCall()
        audit_item(self.item, self.record, self.pages, call, make_ctx(self.template), "fr")
        self.assertEqual(len(call.prompts), 1)
        prompt = call.prompts[0]
        self.assertIn("fr", prompt)
        self.assertIn("comment of the grade and your reason are written in fr", prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("}}", prompt)
        self.assertNotIn("LANGUAGE_OF_REPORT", prompt)
        self.assertNotIn("EVIDENCE_PAGES", prompt)
        self.assertNotIn("GRADE_RECORD", prompt)
        self.assertNotIn("ITEM}}", prompt)

    def test_template_with_language_slot_refuses_a_missing_language(self):
        """A template that asks for the language but is given none is refused, not filled with an empty value."""
        with self.assertRaises(PromptError):
            audit_item(self.item, self.record, self.pages, FakeCall(), make_ctx(self.template), None)

    def test_template_without_language_slot_still_works_without_language(self):
        """A template with no language slot is filled as before, with no language argument (the existing contract)."""
        call = FakeCall()
        ctx = make_ctx("AUDIT {{ITEM}} {{GRADE_RECORD}} {{EVIDENCE_PAGES}}")
        audit_item(self.item, self.record, self.pages, call, ctx)
        self.assertNotIn("{{", call.prompts[0])


if __name__ == "__main__":
    unittest.main()
