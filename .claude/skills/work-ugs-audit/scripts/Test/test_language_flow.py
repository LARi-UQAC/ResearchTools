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
from unittest.mock import patch

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


class PageFake:
    """
    A language call that answers one finding per page, quoting the page's own sentence, and that raises NotRun
    (unreachable) on the page given in `down_on` (no page when None). It records the page number of each call.
    """

    def __init__(self, down_on=None):
        self.down_on = down_on
        self.pages_called = []

    def __call__(self, prompt, schema, images=None):
        number = int(re.search(r"Fictitious page (\d)", prompt).group(1))
        self.pages_called.append(number)
        if number == self.down_on:
            raise NotRun("unreachable", "the daemon went away")
        return {"findings": [{"code": "SP", "quote": f"Fictitious page {number}", "proposed": "fix",
                              "reason": "fictitious"}]}


class TestLanguageResume(unittest.TestCase):
    """The language step saves each page as it is answered and resumes from the saved pages (Issue 122, defect 2)."""

    ENTRIES = [{"code": "SP", "severity": "minor", "label_en": "spelling", "label_fr": "orthographe", "scope": "both"}]

    def setUp(self):
        from ugs_ledger import add_report, new_ledger
        from ugs_text import StepContext
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="ugs-language-flow-"))
        self.work_dir = self.tmp_dir / "work"
        pages_dir = self.work_dir / "R01" / "pages"
        pages_dir.mkdir(parents=True)
        for number in (1, 2, 3):
            (pages_dir / f"p{number:03d}.md").write_text(f"Fictitious page {number} has one sentence.", encoding="utf-8")
        self.ledger_path = self.work_dir / "ledger.md"
        self.ledger_path.write_text(add_report(new_ledger("Test Ledger"), "R01", ["I01"]), encoding="utf-8")
        self.ctx = StepContext(
            prompts={"language": "Table {{LANGUAGE_TABLE}} Section {{SECTION}} Language {{LANGUAGE_OF_REPORT}}"},
            schemas={"language": {}}, levels={}, window_tokens=100000, reserve_tokens=100,
            count=lambda text: len(text) // 4, grade_retries=0, audit_retries=0, min_word_len=3)
        self.services = {"rubric": {"items": [{"id": "I01", "title": "Item 1", "max_points": 10}]},
                         "entries": self.ENTRIES, "criteria_doc": {}, "hints": {}, "vision_ok": True, "settings": {}}
        self.grade = {"report_id": "R01", "loop": 1, "items": [
            {"item_id": "I01", "status": "rated", "score": 10, "comment": "ok", "evidence": [], "audit": "not_run",
             "flag": False}]}
        self.pdf = self.tmp_dir / "report.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fictitious")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def run_it(self, call):
        from ugs_run import run_report
        patches = [patch("ugs_run.grade_report", return_value=self.grade),
                   patch("ugs_run.figures_report", return_value={"report_id": "R01", "figures": [],
                                                                  "report_criteria": {}}),
                   patch("ugs_run.audit_report", return_value=self.grade),
                   patch("ugs_run.assemble_report", return_value={"report_id": "R01", "placed": 0, "not_found": 0,
                                                                   "duplicates": 0, "annex_pages": 1,
                                                                   "complete": True, "percent": 100.0})]
        for patcher in patches:
            patcher.start()
        try:
            return run_report(self.work_dir, "R01", 1, self.pdf, call, self.ctx, self.services, "", None)
        finally:
            for patcher in patches:
                patcher.stop()

    def saved(self):
        return json.loads((self.work_dir / "loop-1" / "R01" / "language.json").read_text(encoding="utf-8"))

    def test_language_resumes_after_a_stop(self):
        """A stop on page 3 keeps pages 1 and 2; the second run asks the model for page 3 only and finishes."""
        first = PageFake(down_on=3)
        with self.assertRaises(NotRun):
            self.run_it(first)
        self.assertEqual(first.pages_called, [1, 2, 3])
        self.assertEqual(sorted(self.saved()["pages"]), ["1", "2"])

        second = PageFake()
        result = self.run_it(second)
        self.assertEqual(result["status"], "done")
        self.assertEqual(second.pages_called, [3])
        final = self.saved()
        self.assertEqual(sorted({annotation["page"] for annotation in final["annotations"]}), [1, 2, 3])
        self.assertEqual(final["not_run"], [])
        # N1: the result also counts the spelling findings refused as correct words (rejected_correct).
        # Plan 22 task 1: comment_language_replaced counts the comments replaced for their language
        self.assertEqual(set(final), {"annotations", "rejected", "rejected_correct", "dropped_scope",
                                      "comment_language_replaced", "not_run"})
        self.assertIn("- [x] language", self.ledger_path.read_text(encoding="utf-8"))

    def test_language_partial_is_saved_per_page(self):
        """After page 1 is answered the partial file already exists and holds page 1, before any later page."""
        with self.assertRaises(NotRun):
            self.run_it(PageFake(down_on=2))
        partial = self.saved()
        self.assertEqual(sorted(partial["pages"]), ["1"])
        self.assertEqual([a["page"] for a in partial["annotations"]], [1])


class TestFrontModesFromMeta(unittest.TestCase):
    """Issue 126 plan 16 N3: the language step reads the front roles of report_meta.json (fictitious roles)."""

    def test_modes_come_from_the_recorded_front_roles(self):
        import json
        import tempfile
        import ugs_run
        work = Path(tempfile.mkdtemp(prefix="ugs-modes-"))
        (work / "R01").mkdir()
        meta = {"front_roles": {"cover": [1], "version_signature": None, "table_of_contents": [2],
                                "list_of_figures": [3], "list_of_tables": None, "executive_summary": [4]}}
        (work / "R01" / "report_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        modes = ugs_run._page_modes(work, "R01")
        self.assertEqual(modes, {1: "none", 2: "spelling_only", 3: "spelling_only", 4: "full"})

    def test_no_front_roles_gives_no_map(self):
        import json
        import tempfile
        import ugs_run
        work = Path(tempfile.mkdtemp(prefix="ugs-modes-"))
        (work / "R01").mkdir()
        (work / "R01" / "report_meta.json").write_text(json.dumps({"language": "fr"}), encoding="utf-8")
        self.assertEqual(ugs_run._page_modes(work, "R01"), {})


if __name__ == "__main__":
    unittest.main()
