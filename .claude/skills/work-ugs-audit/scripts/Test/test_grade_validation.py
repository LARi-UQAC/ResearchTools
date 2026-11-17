"""test_grade_validation - the grade record keeps the model's fields and says why it was refused (R12, plan 12 task 1).

Every fixture is fictitious (R34). The checks are driven through ugs_grade.check_grade_answer and grade_item with a
scripted fake model call, so no network, no model and no report is read (R21). Each assertion reads a record field with
.get(), so a missing field is a FAIL with its name, never a KeyError.
"""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import ugs_grade  # noqa: E402
from ugs_grade import grade_item  # noqa: E402
from ugs_text import StepContext  # noqa: E402
from ugs_bridge import NotRun  # noqa: E402
import grade_total  # noqa: E402

CODE_TABLE = (
    "ok", "quote_not_found", "evidence_missing", "evidence_incomplete", "evidence_page_out_of_range",
    "score_above_max", "score_negative", "score_missing", "unknown_status", "not_applicable_with_score",
    "unparsable_answer", "schema_invalid", "no_fit", "over_budget",
)


class FakeCall:
    """A scripted model call: each response is an answer dict, or an exception to raise."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, prompt, schema, images=None):
        self.calls.append(prompt)
        if not self.responses:
            raise NotRun("unreachable", "No more responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_ctx():
    """Return a fictitious step context with a word-count token proxy."""
    return StepContext(
        prompts={
            "grade_item": "Grade {{ITEM}} on {{SECTIONS}}. Levels: {{LEVELS}}. Lang: {{LANGUAGE_OF_REPORT}}. Note: {{CALIBRATION_NOTE}}",
            "rubric_normalize": "Normalize {{RUBRIC_TEXT}} for {{ASSESSMENT_TYPE}}",
        },
        schemas={"grade_item": {"type": "object"}, "rubric": {"type": "object"}},
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete": 0.88, "exemplary": 1.0},
        window_tokens=1000,
        reserve_tokens=100,
        count=lambda text: len(text.split()),
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


def _rated(score, evidence=None, comment="Fictitious comment."):
    """Return a fictitious rated answer."""
    return {"status": "rated", "score": score, "comment": comment,
            "evidence": [] if evidence is None else evidence}


def _quote(page, text):
    """Return one fictitious evidence entry."""
    return {"page": page, "quote": text}


class TestCheckGradeAnswer(unittest.TestCase):
    """check_grade_answer returns one code of the table and a short message."""

    def setUp(self):
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["Page 1 text", "Page 2 text"]

    def _check(self, answer):
        """Return the (code, message) pair, or fail by name when the function is missing."""
        self.assertTrue(hasattr(ugs_grade, "check_grade_answer"), "ugs_grade.check_grade_answer is missing")
        return ugs_grade.check_grade_answer(answer, self.item, self.pages)

    def test_a_full_score_without_evidence_is_ok(self):
        self.assertEqual(self._check(_rated(10))[0], "ok")

    def test_a_partial_score_with_a_found_quote_is_ok(self):
        self.assertEqual(self._check(_rated(5, [_quote(1, "Page 1 text")]))[0], "ok")

    def test_a_not_applicable_without_score_is_ok(self):
        self.assertEqual(self._check({"status": "not_applicable", "score": None, "comment": "", "evidence": []})[0], "ok")

    def test_score_above_max(self):
        self.assertEqual(self._check(_rated(11))[0], "score_above_max")

    def test_score_negative(self):
        self.assertEqual(self._check(_rated(-1))[0], "score_negative")

    def test_score_missing_on_a_rated_answer(self):
        self.assertEqual(self._check({"status": "rated", "score": None, "comment": "", "evidence": []})[0], "score_missing")

    def test_unknown_status(self):
        self.assertEqual(self._check({"status": "maybe", "score": 5, "comment": "", "evidence": []})[0], "unknown_status")

    def test_not_applicable_with_a_score(self):
        self.assertEqual(self._check({"status": "not_applicable", "score": 3, "comment": "", "evidence": []})[0],
                         "not_applicable_with_score")

    def test_evidence_missing_below_max(self):
        self.assertEqual(self._check(_rated(5, []))[0], "evidence_missing")

    def test_evidence_entry_without_a_quote(self):
        self.assertEqual(self._check(_rated(5, [{"page": 1}]))[0], "evidence_incomplete")

    def test_evidence_page_out_of_range(self):
        self.assertEqual(self._check(_rated(5, [_quote(9, "Page 1 text")]))[0], "evidence_page_out_of_range")

    def test_quote_not_found_on_its_page(self):
        self.assertEqual(self._check(_rated(5, [_quote(1, "NOT IN PAGE")]))[0], "quote_not_found")

    def test_evidence_that_is_not_a_list_is_schema_invalid(self):
        self.assertEqual(self._check(_rated(5, "Page 1 text"))[0], "schema_invalid")

    def test_every_code_is_in_the_table_and_snake_case(self):
        answers = [
            _rated(10), _rated(11), _rated(-1), _rated(5, []), _rated(5, [_quote(1, "NOT IN PAGE")]),
            _rated(5, [_quote(9, "Page 1 text")]), _rated(5, "x"),
            {"status": "rated", "score": None, "comment": "", "evidence": []},
            {"status": "maybe", "score": 5, "comment": "", "evidence": []},
            {"status": "not_applicable", "score": 3, "comment": "", "evidence": []},
        ]
        for answer in answers:
            code, message = self._check(answer)
            self.assertIn(code, CODE_TABLE)
            self.assertLessEqual(len(code), 30)
            self.assertEqual(code, code.lower())
            self.assertIsInstance(message, str)

    def test_message_never_contains_the_quote(self):
        code, message = self._check(_rated(5, [_quote(1, "SECRET PHRASE")]))
        self.assertEqual(code, "quote_not_found")
        self.assertTrue(message)
        self.assertNotIn("SECRET", message)
        self.assertNotIn("PHRASE", message)


class TestGradeRecord(unittest.TestCase):
    """grade_item returns a record built from the last answer, with its validation code."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["Page 1 text", "Page 2 text"]

    def _grade(self, responses):
        """Grade the item with the scripted responses and return the record."""
        return grade_item(self.item, self.pages, FakeCall(responses), self.ctx, "en", "")

    def test_quote_not_found_keeps_the_score_and_flags(self):
        evidence = [_quote(1, "NOT IN PAGE")]
        bad = _rated(5, evidence, comment="Bad quote")
        record = self._grade([bad, bad])
        self.assertEqual(record.get("status"), "rated")
        self.assertEqual(record.get("score"), 5)
        self.assertEqual(record.get("model_score"), 5)
        self.assertEqual(record.get("validation"), "quote_not_found")
        self.assertIs(record.get("flag"), True)
        self.assertEqual(record.get("attempts"), 2)
        self.assertEqual(record.get("evidence"), evidence)

    def test_score_above_max_keeps_model_score_and_drops_score(self):
        record = self._grade([_rated(11), _rated(11)])
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        self.assertEqual(record.get("model_score"), 11)
        self.assertEqual(record.get("validation"), "score_above_max")
        self.assertIs(record.get("flag"), True)
        self.assertEqual(record.get("attempts"), 2)

    def test_missing_evidence_below_max_keeps_the_score(self):
        record = self._grade([_rated(5, []), _rated(5, [])])
        self.assertEqual(record.get("status"), "rated")
        self.assertEqual(record.get("score"), 5)
        self.assertEqual(record.get("validation"), "evidence_missing")
        self.assertIs(record.get("flag"), True)

    def test_unknown_status_gives_not_run_and_its_code(self):
        bad = {"status": "maybe", "score": 4, "comment": "Odd", "evidence": []}
        record = self._grade([bad, bad])
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        self.assertEqual(record.get("model_score"), 4)
        self.assertEqual(record.get("validation"), "unknown_status")

    def test_a_success_has_ok_and_its_attempt_count(self):
        good = _rated(5, [_quote(1, "Page 1 text")], comment="Good")
        record = self._grade([good])
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(record.get("attempts"), 1)
        self.assertIs(record.get("flag"), False)
        self.assertEqual(record.get("audit"), "not_run")
        self.assertEqual(record.get("comment"), "Good")

    def test_a_success_on_the_second_try_counts_two_attempts(self):
        record = self._grade([_rated(11), _rated(10)])
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(record.get("attempts"), 2)
        self.assertIs(record.get("flag"), False)

    def test_the_model_comment_is_kept_on_a_refusal(self):
        record = self._grade([_rated(11, comment="Too generous"), _rated(11, comment="Too generous again")])
        self.assertEqual(record.get("comment"), "Too generous again")

    def test_no_fit_carries_its_code(self):
        self.ctx.window_tokens = 10
        self.ctx.reserve_tokens = 5
        self.pages = ["Very long page text that definitely exceeds the tiny budget limit"]
        record = self._grade([])
        self.assertEqual(record.get("comment"), "no_fit")
        self.assertEqual(record.get("validation"), "no_fit")
        self.assertIs(record.get("flag"), True)

    def test_over_budget_carries_its_code(self):
        def refuse(prompt, schema, images=None):
            raise NotRun("over_budget", "Too big")
        record = grade_item(self.item, self.pages, refuse, self.ctx, "en", "")
        self.assertEqual(record.get("comment"), "over_budget")
        self.assertEqual(record.get("validation"), "over_budget")

    def test_an_unparsable_reply_twice_gives_no_score_and_its_code(self):
        record = self._grade([NotRun("unparsable", "Failed to parse JSON"),
                              NotRun("unparsable", "Failed to parse JSON")])
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        self.assertIsNone(record.get("model_score"))
        self.assertEqual(record.get("validation"), "unparsable_answer")
        self.assertEqual(record.get("evidence"), [])
        self.assertIs(record.get("flag"), True)

    def test_a_schema_refusal_twice_gives_its_code(self):
        record = self._grade([NotRun("invalid", "score: wrong type"), NotRun("invalid", "score: wrong type")])
        self.assertEqual(record.get("validation"), "schema_invalid")
        self.assertIsNone(record.get("model_score"))


class TestTotals(unittest.TestCase):
    """grade_total accepts a refused proof and ignores only an unusable score."""

    def setUp(self):
        self.ctx = make_ctx()
        self.rubric = {
            "assessment_type": "lab_report",
            "total_points": 20,
            "items": [
                {"id": "I01", "title": "Fictitious one", "max_points": 10},
                {"id": "I02", "title": "Fictitious two", "max_points": 10},
            ],
        }
        self.pages = ["Page 1 text", "Page 2 text"]

    def test_a_refused_proof_keeps_its_score_in_the_totals(self):
        proof = grade_item(self.rubric["items"][0], self.pages,
                           FakeCall([_rated(5, [_quote(1, "NOT IN PAGE")])] * 2),
                           self.ctx, "en", "")
        full = grade_item(self.rubric["items"][1], self.pages,
                          FakeCall([_rated(10, [_quote(2, "Page 2 text")])]), self.ctx, "en", "")
        result = grade_total.compute(self.rubric, {"report_id": "R01", "items": [proof, full]})
        self.assertTrue(result["complete"])
        self.assertEqual(result["by_item"]["I01"]["score"], "5")
        self.assertEqual(result["total"], "15")

    def test_an_unusable_score_is_left_out_as_not_run(self):
        proof = grade_item(self.rubric["items"][0], self.pages,
                           FakeCall([_rated(5, [_quote(1, "Page 1 text")])]), self.ctx, "en", "")
        unusable = grade_item(self.rubric["items"][1], self.pages,
                              FakeCall([_rated(11), _rated(11)]), self.ctx, "en", "")
        result = grade_total.compute(self.rubric, {"report_id": "R01", "items": [proof, unusable]})
        self.assertFalse(result["complete"])
        self.assertEqual(result["not_run"], ["I02"])
        self.assertIsNone(result["by_item"]["I02"]["score"])
        self.assertIsNone(result["total"])


if __name__ == "__main__":
    unittest.main()
