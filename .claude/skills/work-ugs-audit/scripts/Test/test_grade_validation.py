"""test_grade_validation - the grade record keeps the model's fields and says why it was refused (R12, plan 12 task 1).

Every fixture is fictitious (R34). The checks are driven through ugs_grade.check_grade_answer and grade_item with a
scripted fake model call, so no network, no model and no report is read (R21). Each assertion reads a record field with
.get(), so a missing field is a FAIL with its name, never a KeyError.
"""
import json
import math
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import ugs_grade  # noqa: E402
from ugs_grade import grade_item  # noqa: E402
from ugs_text import StepContext  # noqa: E402
from ugs_bridge import NotRun  # noqa: E402
import grade_total  # noqa: E402
from ugs_run import _grade_mark  # noqa: E402

CODE_TABLE = (
    "ok", "quote_not_found", "evidence_missing", "evidence_incomplete", "evidence_page_out_of_range",
    "score_above_max", "unknown_level", "score_negative", "score_missing", "unknown_status", "not_applicable_with_score",
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
            "retry_grade_item": (
                "## fr_score\nLe score {{SCORE}} dépasse le maximum {{MAX}}. Réponds à nouveau avec un score entre 0 et {{MAX}}.\n\n"
                "## en_score\nThe score {{SCORE}} is above the maximum {{MAX}}. Answer again with a score between 0 and {{MAX}}.\n\n"
                "## fr_not_applicable\nCet élément n'est pas facultatif : réponds avec un score entre 0 et {{MAX}}.\n\n"
                "## en_not_applicable\nThis item is not optional: answer with a score between 0 and {{MAX}}.\n"
            ),
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
    """Return a fictitious rated answer with a valid level, for the direct checks of check_grade_answer."""
    return {"status": "rated", "level": "partial", "score": score, "comment": comment,
            "evidence": [] if evidence is None else evidence}


# Plan 25 Task 1: the level the model would name for each score of a maximum of 10 (fraction x 10). Any other score
# is a level the model cannot have named, so it is refused as unknown_level.
FLOW_LEVEL_FOR_SCORE = {0: "absent", 5: "attempted", 7.5: "partial", 10: "exemplary"}


def _flow(score, evidence=None, comment="Fictitious comment."):
    """Return a fictitious answer as the model now gives it: a level, and the score the level computes to."""
    level = FLOW_LEVEL_FOR_SCORE.get(score, "great")
    return {"status": "rated", "level": level, "score": score, "comment": comment,
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

    def test_a_not_applicable_without_score_is_ok_on_an_optional_item(self):
        self.item = dict(self.item, optional=True)
        self.assertEqual(self._check({"status": "not_applicable", "score": None, "comment": "", "evidence": []})[0], "ok")

    def test_a_not_applicable_on_a_required_item_is_refused(self):
        # Plan 22 task 2 (R01 case 4): not_applicable is an answer only when the rubric item allows it
        self.assertEqual(self._check({"status": "not_applicable", "score": None, "comment": "", "evidence": []}),
                         ("not_applicable_not_allowed", "not_applicable is allowed only for an optional item"))

    def test_score_above_max(self):
        self.assertEqual(self._check(_rated(11))[0], "score_above_max")

    def test_score_negative(self):
        self.assertEqual(self._check(_rated(-1))[0], "score_negative")

    def test_score_missing_on_a_rated_answer(self):
        self.assertEqual(self._check({"status": "rated", "level": "partial", "score": None, "comment": "", "evidence": []})[0], "score_missing")

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

    def test_non_list_evidence_at_max_is_refused(self):
        # A full score still needs evidence in the shape the audit reads: a string is refused at any score.
        self.assertEqual(self._check(_rated(10, "p. 3"))[0], "schema_invalid")

    def test_every_code_is_in_the_table_and_snake_case(self):
        answers = [
            _rated(10), _rated(11), _rated(-1), _rated(5, []), _rated(5, [_quote(1, "NOT IN PAGE")]),
            _rated(5, [_quote(9, "Page 1 text")]), _rated(5, "x"),
            {"status": "rated", "level": "partial", "score": None, "comment": "", "evidence": []},
            {"status": "rated", "level": "attempted", "score": 5, "comment": "", "evidence": []},
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


class TestLevelScoring(unittest.TestCase):
    """Plan 25 task 1: the grader names a level; the code computes the points (fraction x maximum, rounded to the
    configured step, ties up). Fictitious items and answers (R34); the levels are read from grade_levels.json."""

    PAGES = ["Page 1 text", "Page 2 text"]

    def setUp(self):
        """
        Purpose: Give each test a step context with the shipped level names, fictitious (R34).
        Inputs:
            None.
        Outputs:
            None. Sets self.ctx.
        Raises:
            None.
        """
        self.ctx = make_ctx()

    @staticmethod
    def _level(level, evidence=None):
        """
        Purpose: Build a fictitious rated answer with a level and no score, as the schema now asks.
        Inputs:
            level (str): the level name.
            evidence (list | None): the evidence entries.
        Outputs:
            dict: the answer.
        Raises:
            None.
        """
        return {"status": "rated", "level": level, "comment": "Fictitious comment.",
                "evidence": [] if evidence is None else evidence}

    def test_complete_correct_on_a_half_point_item_is_half_a_point(self):
        item = {"id": "I01", "title": "Intro", "max_points": 0.5}
        record = grade_item(item, self.PAGES, FakeCall([self._level("complete_correct")]), self.ctx, "en", "")
        self.assertEqual(record["score"], 0.5)
        self.assertEqual(record["validation"], "ok")

    def test_complete_correct_on_ten_points_is_eight_and_three_quarters(self):
        item = {"id": "I02", "title": "Method", "max_points": 10}
        answer = self._level("complete_correct", [_quote(1, "Page 1 text")])
        record = grade_item(item, self.PAGES, FakeCall([answer]), self.ctx, "en", "")
        self.assertEqual(record["score"], 8.75)
        self.assertEqual(record["model_score"], "complete_correct")

    def test_absent_is_zero_with_its_evidence(self):
        item = {"id": "I03", "title": "Table", "max_points": 4}
        record = grade_item(item, self.PAGES, FakeCall([self._level("absent", [_quote(2, "Page 2 text")])]),
                            self.ctx, "en", "")
        self.assertEqual(record["score"], 0.0)

    def test_an_unknown_level_is_asked_again_then_not_run(self):
        item = {"id": "I04", "title": "Intro", "max_points": 2}
        call = FakeCall([self._level("great"), self._level("great")])
        record = grade_item(item, self.PAGES, call, self.ctx, "en", "")
        self.assertEqual((record["status"], record["validation"], record["score"]), ("not_run", "unknown_level", None))
        self.assertEqual(record["attempts"], 2)

    def test_a_score_without_a_level_is_refused_as_unknown_level(self):
        item = {"id": "I05", "title": "Intro", "max_points": 0.5}
        answer = {"status": "rated", "score": 0.5, "comment": "x", "evidence": []}
        record = grade_item(item, self.PAGES, FakeCall([answer, answer]), self.ctx, "en", "")
        self.assertEqual(record["validation"], "unknown_level")
        self.assertIsNone(record["score"])

    def test_points_are_the_fraction_rounded_to_the_nearest_step_ties_up(self):
        levels = ugs_grade.load_grade_levels()
        step = Decimal("0.25")
        self.assertEqual(ugs_grade.points_for_level("complete_correct", 0.5, levels, step), 0.5)
        self.assertEqual(ugs_grade.points_for_level("complete_correct", 10, levels, step), 8.75)
        self.assertEqual(ugs_grade.points_for_level("partial", 10, levels, step), 7.5)
        self.assertEqual(ugs_grade.points_for_level("exemplary", 10, levels, step), 10.0)
        self.assertEqual(ugs_grade.points_for_level("attempted", 0.5, levels, step), 0.25)

    def test_no_prompt_states_a_numeric_fraction_the_model_could_copy(self):
        prompts = SCRIPTS.parent / "prompts"
        for name in ("levels.md", "grade_item.md", "audit_item.md"):
            text = (prompts / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b0[.,]\d+\b|\b1\.0\b", text), name)
        # Negative control: the check can fail on a prompt that carries a fraction.
        self.assertIsNotNone(re.search(r"\b0[.,]\d+\b", "complete and correct = 0.88 of max_points"))

    def test_the_level_names_match_the_schema_and_carry_provenance(self):
        data = json.loads((SCRIPTS.parent / "assets" / "grade_levels.json").read_text(encoding="utf-8"))
        schema = json.loads((SCRIPTS.parent / "prompts" / "schemas.json").read_text(encoding="utf-8"))
        names = [name for name in schema["grade_item"]["properties"]["level"]["enum"] if name is not None]
        self.assertEqual(sorted(data["levels"]), sorted(names))
        self.assertTrue(data["_provenance"].strip())
        for name, entry in data["levels"].items():
            self.assertIsInstance(entry["fraction"], (int, float), name)
            self.assertTrue(entry["fr"] and entry["en"], name)

    def test_the_step_is_read_from_the_configuration_and_a_missing_one_is_named(self):
        self.assertEqual(ugs_grade.read_grade_step(ugs_grade.default_path()), Decimal("0.25"))
        broken = Path(tempfile.mkdtemp()) / "config.json"
        broken.write_text(json.dumps({"grade.missing_max_chars": {"value": 300}}), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            ugs_grade.read_grade_step(broken)
        self.assertIn("grade.score_step", str(raised.exception))


class TestScoreRetry(unittest.TestCase):
    """Plan 22 task 2 (R01 case 4): a score above the maximum is asked again with the maximum named, in the report
    language, from a template of the prompts folder; not_applicable on a required item is refused and asked again.
    Fictitious items and answers (R34)."""

    def setUp(self):
        self.ctx = make_ctx()
        self.pages = ["Page 1 text", "Page 2 text"]

    def test_an_unknown_level_is_asked_again_and_the_repeat_is_kept(self):
        item = {"id": "I01", "title": "Intro", "max_points": 0.5}
        good = {"status": "rated", "level": "complete_correct", "comment": "Fictitious.", "evidence": []}
        record = grade_item(item, self.pages, FakeCall([{"status": "rated", "level": "great", "comment": ""}, good]),
                            self.ctx, "en", "")
        self.assertEqual(record.get("score"), 0.5)
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(record.get("attempts"), 2)

    def test_the_retry_prompt_carries_the_refusal_of_the_level(self):
        item = {"id": "I01", "title": "Intro", "max_points": 0.5}
        call = FakeCall([{"status": "rated", "level": "great", "comment": ""},
                         {"status": "rated", "level": "complete_correct", "comment": "", "evidence": []}])
        grade_item(item, self.pages, call, self.ctx, "fr", "")
        self.assertIn("Previous refusal: level must be one of", call.calls[1])

    def test_a_required_item_answered_not_applicable_is_refused_and_asked_once_more(self):
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        na = {"status": "not_applicable", "score": None, "comment": "", "evidence": []}
        call = FakeCall([na, na])
        record = grade_item(item, self.pages, call, self.ctx, "en", "")
        self.assertEqual(record.get("validation"), "not_applicable_not_allowed")
        self.assertEqual(record.get("status"), "not_run")
        self.assertEqual(record.get("attempts"), 2)
        self.assertIn("This item is not optional", call.calls[1])

    def test_an_optional_item_answered_not_applicable_is_accepted(self):
        item = {"id": "I01", "title": "Intro", "max_points": 10, "optional": True}
        na = {"status": "not_applicable", "score": None, "comment": "", "evidence": []}
        call = FakeCall([na])
        record = grade_item(item, self.pages, call, self.ctx, "en", "")
        self.assertEqual(record.get("status"), "not_applicable")
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(len(call.calls), 1)

    def test_two_unknown_levels_stay_not_run(self):
        item = {"id": "I01", "title": "Intro", "max_points": 0.5}
        bad = {"status": "rated", "level": "great", "comment": "", "evidence": []}
        record = grade_item(item, self.pages, FakeCall([bad, bad]), self.ctx, "en", "")
        self.assertEqual(record.get("validation"), "unknown_level")
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        self.assertEqual(record.get("attempts"), 2)


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
        bad = _flow(5, evidence, comment="Bad quote")
        record = self._grade([bad, bad])
        self.assertEqual(record.get("status"), "rated")
        self.assertEqual(record.get("score"), 5)
        self.assertEqual(record.get("model_score"), "attempted")
        self.assertEqual(record.get("validation"), "quote_not_found")
        self.assertIs(record.get("flag"), True)
        self.assertEqual(record.get("attempts"), 2)
        self.assertEqual(record.get("evidence"), evidence)

    def test_an_unknown_level_keeps_the_level_name_and_drops_the_score(self):
        bad = {"status": "rated", "level": "great", "comment": "", "evidence": []}
        record = self._grade([bad, bad])
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        self.assertEqual(record.get("model_score"), "great")
        self.assertEqual(record.get("validation"), "unknown_level")
        self.assertIs(record.get("flag"), True)
        self.assertEqual(record.get("attempts"), 2)

    def test_missing_evidence_below_max_keeps_the_score(self):
        record = self._grade([_flow(5, []), _flow(5, [])])
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
        good = _flow(5, [_quote(1, "Page 1 text")], comment="Good")
        record = self._grade([good])
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(record.get("attempts"), 1)
        self.assertIs(record.get("flag"), False)
        self.assertEqual(record.get("audit"), "not_run")
        self.assertEqual(record.get("comment"), "Good")

    def test_a_success_on_the_second_try_counts_two_attempts(self):
        record = self._grade([_flow(11), _flow(10)])
        self.assertEqual(record.get("validation"), "ok")
        self.assertEqual(record.get("attempts"), 2)
        self.assertIs(record.get("flag"), False)

    def test_the_model_comment_is_kept_on_a_refusal(self):
        record = self._grade([_flow(11, comment="Too generous"), _flow(11, comment="Too generous again")])
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


class TestMissingField(unittest.TestCase):
    """The grade record carries `missing`: the element that cost the points, kept as the model gave it.

    Fictitious data only (R34). The module ugs_grade is driven with a scripted call, so no model runs (R21).
    """

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["Page 1 text", "Page 2 text"]

    def _grade(self, responses):
        """Grade the item with the scripted responses and return the record."""
        return grade_item(self.item, self.pages, FakeCall(responses), self.ctx, "en", "")

    def test_record_has_missing_key_in_order(self):
        answer = {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.",
                  "evidence": [_quote(1, "Page 1 text")], "missing": "Fictitious gap."}
        record = self._grade([answer])
        self.assertEqual(
            list(record.keys())[:8],
            ["item_id", "status", "score", "comment", "evidence", "missing", "audit", "flag"],
        )
        self.assertEqual(list(record.keys())[8:], ["model_score", "validation", "attempts"])

    def test_missing_is_kept_as_given_below_the_maximum(self):
        answer = {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.",
                  "evidence": [_quote(1, "Page 1 text")], "missing": "Fictitious gap."}
        self.assertEqual(self._grade([answer]).get("missing"), "Fictitious gap.")

    def test_missing_is_empty_at_full_score(self):
        answer = {"status": "rated", "level": "exemplary", "score": 10, "comment": "Fictitious.", "evidence": [],
                  "missing": "Should not be kept."}
        self.assertEqual(self._grade([answer]).get("missing"), "")

    def test_missing_is_empty_when_the_answer_has_none(self):
        answer = {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.", "evidence": [_quote(1, "Page 1 text")]}
        self.assertEqual(self._grade([answer]).get("missing"), "")

    def test_a_non_text_missing_is_empty(self):
        answer = {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.",
                  "evidence": [_quote(1, "Page 1 text")], "missing": 5}
        self.assertEqual(self._grade([answer]).get("missing"), "")

    def test_missing_is_kept_from_the_last_answer_on_refusal(self):
        first = _flow(5, [_quote(1, "NOT IN PAGE")])
        first["missing"] = "First missing text."
        last = _flow(5, [_quote(1, "NOT IN PAGE")])
        last["missing"] = "Last missing text."
        record = self._grade([first, last])
        self.assertEqual(record.get("validation"), "quote_not_found")
        self.assertEqual(record.get("missing"), "Last missing text.")

    def test_missing_is_trimmed_to_the_maximum_length(self):
        # D2: the limit is read from configuration (grade.missing_max_chars), not from a constant of the module.
        from ugs_config import default_path
        limit = ugs_grade.read_missing_max_chars(default_path())
        answer = {"status": "rated", "level": "attempted", "score": 5, "comment": "Fictitious.",
                  "evidence": [_quote(1, "Page 1 text")], "missing": "x" * (limit + 50)}
        self.assertEqual(len(self._grade([answer]).get("missing")), limit)

    def test_a_record_with_no_answer_has_empty_missing(self):
        self.ctx.window_tokens = 10
        self.ctx.reserve_tokens = 5
        self.pages = ["Very long page text that definitely exceeds the tiny budget limit"]
        record = self._grade([])
        self.assertEqual(record.get("comment"), "no_fit")
        self.assertEqual(record.get("missing"), "")

    def test_ledger_note_never_contains_missing(self):
        marker = "SECRET MARKER SENTENCE"
        refused = _flow(5, [_quote(1, "NOT IN PAGE")])
        refused["missing"] = marker
        record = self._grade([refused, refused])
        mark, note = _grade_mark(record)
        self.assertEqual((mark, note), ("x", "quote_not_found"))
        self.assertNotIn("SECRET", str(note))
        blocked = {"status": "rated", "level": "great", "comment": "", "evidence": []}
        blocked["missing"] = marker
        mark, note = _grade_mark(self._grade([blocked, blocked]))
        self.assertEqual((mark, note), ("!", "unknown_level"))
        self.assertNotIn("MARKER", str(note))


class TestNanScoreAndNullEvidencePage(unittest.TestCase):
    """A non-finite score and an evidence page that is not an int are refused, and the audit never raises on them.

    json.loads accepts NaN, which passes every comparison of a range test; a null page reached audit_item and
    raised TypeError in page_blocks. Fictitious data only (R34); the model is a scripted fake call (R21).
    """

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}
        self.pages = ["Page 1 text", "Page 2 text"]

    def test_nan_score_is_refused_not_ok(self):
        nan_answer = _rated(float("nan"), [_quote(1, "Page 1 text")])
        code, _message = ugs_grade.check_grade_answer(nan_answer, self.item, self.pages)
        self.assertEqual(code, "score_missing")
        # Plan 25: the points come from the level, so a NaN score only reaches the record with no level at all.
        legacy_nan = {"status": "rated", "score": float("nan"), "comment": "", "evidence": []}
        record = grade_item(self.item, self.pages, FakeCall([legacy_nan, legacy_nan]), self.ctx, "en", "")
        self.assertEqual(record.get("status"), "not_run")
        self.assertIsNone(record.get("score"))
        # D1: model_score is strict JSON (null), the NaN text is kept in model_score_raw.
        self.assertIsNone(record.get("model_score"))
        self.assertEqual(record.get("model_score_raw"), "nan")
        self.assertEqual(record.get("validation"), "unknown_level")
        result = grade_total.compute({"assessment_type": "lab_report", "total_points": 10, "items": [self.item]},
                                     {"report_id": "R01", "items": [record]})
        self.assertIsNone(result.get("total"))
        self.assertFalse(result.get("complete"))

    def test_null_evidence_page_is_refused_and_audit_does_not_raise(self):
        import ugs_audit
        self.ctx.prompts["audit_item"] = "AUDIT {{ITEM}} {{GRADE_RECORD}} {{EVIDENCE_PAGES}}"
        self.ctx.schemas["audit_item"] = {"type": "object"}
        for score in (5, 10):
            answer = _rated(score, [{"page": None, "quote": "x"}])
            code, _message = ugs_grade.check_grade_answer(answer, self.item, self.pages)
            self.assertEqual(code, "evidence_incomplete", f"score {score}")
            record = grade_item(self.item, self.pages, FakeCall([answer, answer]), self.ctx, "en", "")
            self.assertEqual(record.get("validation"), "evidence_incomplete", f"score {score}")
            verdict = ugs_audit.audit_item(self.item, record, self.pages,
                                           FakeCall([{"verdict": "agree", "reason": "ok"}]), self.ctx)
            self.assertEqual(verdict.get("verdict"), "agree", f"score {score}")


class TestTimeoutCode(unittest.TestCase):
    def test_timeout_is_a_known_grade_code(self):
        self.assertIn("timeout", ugs_grade.GRADE_CODES)
        self.assertLessEqual(len("timeout"), 30)

    def test_a_timeout_that_exhausts_its_retries_is_a_timeout_record(self):
        ctx = make_ctx()
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        call = FakeCall([NotRun("timeout", "post timed out"), NotRun("timeout", "post timed out")])
        record = grade_item(item, ["Page 1"], call, ctx, "en", "")
        self.assertEqual(record["validation"], "timeout")
        self.assertEqual(record["status"], "not_run")
        self.assertIsNone(record["score"])


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
                           FakeCall([_flow(5, [_quote(1, "NOT IN PAGE")])] * 2),
                           self.ctx, "en", "")
        full = grade_item(self.rubric["items"][1], self.pages,
                          FakeCall([_flow(10, [_quote(2, "Page 2 text")])]), self.ctx, "en", "")
        result = grade_total.compute(self.rubric, {"report_id": "R01", "items": [proof, full]})
        self.assertTrue(result["complete"])
        self.assertEqual(result["by_item"]["I01"]["score"], "5")
        self.assertEqual(result["total"], "15")

    def test_an_unusable_score_is_left_out_as_not_run(self):
        proof = grade_item(self.rubric["items"][0], self.pages,
                           FakeCall([_flow(5, [_quote(1, "Page 1 text")])]), self.ctx, "en", "")
        unusable = grade_item(self.rubric["items"][1], self.pages,
                              FakeCall([_flow(11), _flow(11)]), self.ctx, "en", "")
        result = grade_total.compute(self.rubric, {"report_id": "R01", "items": [proof, unusable]})
        self.assertFalse(result["complete"])
        self.assertEqual(result["not_run"], ["I02"])
        self.assertIsNone(result["by_item"]["I02"]["score"])
        self.assertIsNone(result["total"])


if __name__ == "__main__":
    unittest.main()
