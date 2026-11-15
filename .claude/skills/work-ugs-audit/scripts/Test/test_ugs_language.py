import sys
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Add parent folder to sys.path to import the module under test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ugs_language
from ugs_bridge import NotRun
from ugs_text import StepContext


class FakeCall:
    """
    Purpose: Simulate a model call.
    """
    def __init__(self, responses: List[Any]):
        self.responses = responses
        self.calls = []

    def __call__(self, prompt: str, schema: Dict[str, Any], images: Optional[List[str]] = None) -> Any:
        self.calls.append(prompt)
        if not self.responses:
            raise NotRun("unreachable", "No response left")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_ctx(retries: int = 2) -> StepContext:
    return StepContext(
        prompts={"language": "Prompt {{LANGUAGE_TABLE}} {{SECTION}} {{LANGUAGE_OF_REPORT}}"},
        schemas={"language": {}},
        levels={},
        window_tokens=1000,
        reserve_tokens=100,
        count=lambda x: 1,
        grade_retries=retries,
        audit_retries=0,
        min_word_len=3
    )


class TestLoadTable(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path("./tmp_test_data")
        self.tmp_dir.mkdir(exist_ok=True)
        self.table_path = self.tmp_dir / "table.json"

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_load_table_keeps_both_scope_entries_only(self):
        data = {
            "entries": [
                {"code": "SP", "scope": "both", "label_fr": "Ortho", "label_en": "Spelling"},
                {"code": "AV", "scope": "research", "label_fr": "Voix", "label_en": "Voice"}
            ]
        }
        self.table_path.write_text(__import__('json').dumps(data))
        entries = ugs_language.load_table(self.table_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["code"], "SP")

    def test_load_table_names_a_missing_key(self):
        data = {"wrong_key": []}
        self.table_path.write_text(__import__('json').dumps(data))
        with self.assertRaises(ValueError) as ctx:
            ugs_language.load_table(self.table_path)
        self.assertIn("entries", str(ctx.exception))


class TestTableText(unittest.TestCase):
    def test_table_text_uses_the_report_language(self):
        entries = [
            {"code": "SP", "label_fr": "Ortho", "label_en": "Spelling", "severity": "minor"},
            {"code": "AV", "label_fr": "Voix", "label_en": "Voice", "severity": "major"}
        ]
        text_fr = ugs_language.table_text(entries, "fr")
        self.assertIn("SP - Ortho - minor", text_fr)
        self.assertIn("AV - Voix - major", text_fr)
        
        text_en = ugs_language.table_text(entries, "en")
        self.assertIn("SP - Spelling - minor", text_en)
        self.assertIn("AV - Voice - major", text_en)


class TestLanguageReport(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()
        self.entries = [
            {"code": "SP", "label_fr": "Ortho", "label_en": "Spelling", "severity": "minor"}
        ]
        self.pages = [
            "The cat sat on the mat.",
            "A page with an error: recieve is wrong."
        ]

    def test_a_valid_finding_becomes_a_language_annotation(self):
        response = {
            "findings": [
                {
                    "code": "SP",
                    "quote": "recieve",
                    "proposed": "receive",
                    "reason": "Spelling"
                }
            ]
        }
        call = FakeCall([response])
        
        # The call is made for each non-blank page. 
        # Page 1: no finding. Page 2: finding.
        # We need to provide responses for both pages if the code calls for both.
        # The plan says "one grader call per page whose text is not blank".
        # So we need 2 responses.
        call.responses.insert(0, {"findings": []}) 
        
        result = ugs_language.language_report(self.pages, call, self.ctx, self.entries, "en")
        
        self.assertEqual(len(result["annotations"]), 1)
        ann = result["annotations"][0]
        self.assertEqual(ann["page"], 2)
        self.assertEqual(ann["code"], "SP")
        self.assertEqual(ann["quote"], "recieve")
        self.assertEqual(ann["comment"], "receive - Spelling")
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(result["not_run"], [])

    def test_unknown_code_is_rejected_and_counted(self):
        response_page1 = {"findings": []}
        response_page2 = {
            "findings": [
                {
                    "code": "UNKNOWN",
                    "quote": "recieve",
                    "proposed": "receive",
                    "reason": "Bad code"
                }
            ]
        }
        call = FakeCall([response_page2, response_page1])
        result = ugs_language.language_report(self.pages, call, self.ctx, self.entries, "en")
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(len(result["annotations"]), 0)

    def test_quote_not_on_the_page_is_rejected_and_counted(self):
        response_page1 = {"findings": []}
        response_page2 = {
            "findings": [
                {
                    "code": "SP",
                    "quote": "not_in_text",
                    "proposed": "fix",
                    "reason": "Missing"
                }
            ]
        }
        call = FakeCall([response_page2, response_page1])
        result = ugs_language.language_report(self.pages, call, self.ctx, self.entries, "en")
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(len(result["annotations"]), 0)

    def test_accented_quote_with_a_typographic_apostrophe_is_accepted(self):
        # The page has a straight apostrophe, the quote a typographic one, in the same case
        pages = ["Voici l'erreur dans le texte."]
        response = {
            "findings": [
                {
                    "code": "SP",
                    "quote": "l’erreur", # Typographic apostrophe
                    "proposed": "la faute",
                    "reason": "Typo"
                }
            ]
        }
        call = FakeCall([response])
        result = ugs_language.language_report(pages, call, self.ctx, self.entries, "fr")
        self.assertEqual(len(result["annotations"]), 1)
        self.assertEqual(result["rejected"], 0)

    def test_blank_page_makes_no_call(self):
        pages = ["", "Valid page"]
        response_valid = {"findings": []}
        call = FakeCall([response_valid])
        result = ugs_language.language_report(pages, call, self.ctx, self.entries, "en")
        self.assertEqual(len(call.calls), 1) # Only one call for the non-blank page

    def test_a_failed_page_is_listed_and_the_others_still_run(self):
        pages = ["Page 1", "Page 2"]
        # Page 1 fails with unreachable (not retryable)
        # Page 2 succeeds
        call = FakeCall([
            NotRun("unreachable", "Server down"),
            {"findings": []}
        ])
        with self.assertRaises(NotRun):
            ugs_language.language_report(pages, call, self.ctx, self.entries, "en")
            
        # Now test retryable failure
        call2 = FakeCall([
            NotRun("unparsable", "Bad JSON"),
            NotRun("unparsable", "Bad JSON"),
            NotRun("unparsable", "Bad JSON"), # 3 attempts (1 + 2 retries)
            {"findings": []}
        ])
        result = ugs_language.language_report(pages, call2, self.ctx, self.entries, "en")
        self.assertIn(1, result["not_run"])
        self.assertEqual(len(result["annotations"]), 0)
        # Page 2 should still have run
        self.assertEqual(len(call2.calls), 4) # 3 for page 1, 1 for page 2

    def test_duplicate_finding_is_kept_once(self):
        pages = ["Error here"]
        response = {
            "findings": [
                {"code": "SP", "quote": "Error", "proposed": "Err", "reason": "1"},
                {"code": "SP", "quote": "Error", "proposed": "Err", "reason": "2"}
            ]
        }
        call = FakeCall([response])
        result = ugs_language.language_report(pages, call, self.ctx, self.entries, "en")
        self.assertEqual(len(result["annotations"]), 1)

    def test_unreachable_propagates(self):
        pages = ["Page"]
        call = FakeCall([NotRun("unreachable", "Down")])
        with self.assertRaises(NotRun):
            ugs_language.language_report(pages, call, self.ctx, self.entries, "en")

    def test_comment_without_a_proposal_is_the_reason_alone(self):
        pages = ["Error"]
        response = {
            "findings": [
                {"code": "SP", "quote": "Error", "proposed": "", "reason": "Just reason"}
            ]
        }
        call = FakeCall([response])
        result = ugs_language.language_report(pages, call, self.ctx, self.entries, "en")
        self.assertEqual(result["annotations"][0]["comment"], "Just reason")


if __name__ == "__main__":
    unittest.main()
