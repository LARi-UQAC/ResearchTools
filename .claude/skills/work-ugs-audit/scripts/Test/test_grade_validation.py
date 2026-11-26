"""
Tests of the grade record and its validation codes (ugs_grade.py), driven through check_grade_answer and grade_item.

The model names the elements a rubric item asks for and a verdict on each (present, partial or absent); the code
computes the level from the verdicts and the points from the level (review round 1 of plan 25). Every fixture is
fictitious (R34). The model is a scripted call, so no model runs (R21). The level scale is built in the test from
fixed numbers, not read from the shipped file, so the tests pin the rules and not the chosen values.
"""

import json
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import ugs_grade  # noqa: E402
from ugs_grade import GRADE_CODES, GradeScale, grade_item  # noqa: E402
from ugs_text import StepContext  # noqa: E402
from ugs_bridge import NotRun  # noqa: E402
import grade_total  # noqa: E402
from ugs_run import _grade_mark  # noqa: E402

PAGES = ["Page 1 text", "Page 2 text"]
PROMPTS_DIR = SCRIPTS.parent / "prompts"
ASSETS_DIR = SCRIPTS.parent / "assets"

# The scale of the tests: the fractions of the shipped file, the partial weight 0.5 and two bands (fixed here).
TEST_SCALE = GradeScale(
    fractions={"absent": Decimal("0"), "attempted": Decimal("0.5"), "partial": Decimal("0.75"),
               "complete_correct": Decimal("0.88"), "exemplary": Decimal("1.0")},
    partial_weight=Decimal("0.5"),
    bands=((Decimal("0.75"), "partial"), (Decimal("0"), "attempted")),
)
STEP = Decimal("0.25")


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
            "grade_item": "Grade {{ITEM}} on {{SECTIONS}}. Elements: {{LEVELS}}. Lang: {{LANGUAGE_OF_REPORT}}. Note: {{CALIBRATION_NOTE}}",
            "rubric_normalize": "Normalize {{RUBRIC_TEXT}} for {{ASSESSMENT_TYPE}}",
            "retry_grade_item": (
                "## fr_elements\nListe les éléments demandés.\n\n"
                "## en_elements\nList the elements the item asks for.\n\n"
                "## fr_exceptional\nLe rapport exceptionnel n'est pas justifié.\n\n"
                "## en_exceptional\nThe exceptional claim is not supported.\n\n"
                "## fr_not_applicable\nCet élément n'est pas facultatif.\n\n"
                "## en_not_applicable\nThis item is not optional.\n"
            ),
        },
        schemas={"grade_item": {"type": "object"}, "rubric": {"type": "object"}},
        levels={"absent": 0, "attempted": 0.5, "partial": 0.75, "complete_correct": 0.88, "exemplary": 1.0},
        window_tokens=1000,
        reserve_tokens=100,
        count=lambda text: len(text.split()),
        grade_retries=1,
        audit_retries=1,
        min_word_len=3,
    )


def _el(verdict, page=None, quote=None, name="element"):
    """Return one fictitious element entry of an answer."""
    entry = {"element": name, "verdict": verdict}
    if page is not None:
        entry["page"] = page
    if quote is not None:
        entry["quote"] = quote
    return entry


def _rated(elements, exceptional=False, comment="Fictitious comment.", missing=""):
    """Return a fictitious rated answer with its elements."""
    answer = {"status": "rated", "elements": elements, "comment": comment}
    if exceptional:
        answer["exceptional"] = True
    if missing:
        answer["missing"] = missing
    return answer


def _present(page=1, quote="Page 1 text", name="element"):
    """Return a present element with a quote that is on its page."""
    return _el("present", page, quote, name)


class TestCheckGradeAnswer(unittest.TestCase):
    """The validation codes of one answer, judged against the page texts (fictitious)."""

    def check(self, answer, optional=False):
        """Run check_grade_answer with the test scale and a fictitious item."""
        item = {"id": "I01", "title": "Intro", "max_points": 10, "optional": optional}
        return ugs_grade.check_grade_answer(answer, item, PAGES, TEST_SCALE)

    def test_a_verified_present_element_is_ok(self):
        self.assertEqual(self.check(_rated([_present()]))[0], "ok")

    def test_a_verified_partial_element_is_ok(self):
        self.assertEqual(self.check(_rated([_el("partial", 2, "Page 2 text")]))[0], "ok")

    def test_all_absent_is_refused_as_missing_evidence(self):
        self.assertEqual(self.check(_rated([_el("absent"), _el("absent")]))[0], "evidence_missing")

    def test_an_empty_element_list_is_elements_missing(self):
        self.assertEqual(self.check(_rated([]))[0], "elements_missing")

    def test_a_present_element_without_a_page_is_incomplete(self):
        self.assertEqual(self.check(_rated([_el("present", None, "Page 1 text")]))[0], "evidence_incomplete")

    def test_a_present_element_without_a_quote_is_incomplete(self):
        self.assertEqual(self.check(_rated([_el("present", 1, None)]))[0], "evidence_incomplete")

    def test_a_quote_not_on_its_page_is_refused(self):
        self.assertEqual(self.check(_rated([_el("present", 1, "NOT IN PAGE")]))[0], "quote_not_found")

    def test_a_page_out_of_range_is_refused(self):
        self.assertEqual(self.check(_rated([_el("present", 9, "Page 1 text")]))[0], "evidence_page_out_of_range")

    def test_an_unknown_verdict_is_schema_invalid(self):
        self.assertEqual(self.check(_rated([{"element": "x", "verdict": "great"}]))[0], "schema_invalid")

    def test_an_element_without_a_name_is_schema_invalid(self):
        self.assertEqual(self.check(_rated([{"verdict": "absent"}]))[0], "schema_invalid")

    def test_elements_must_be_a_list(self):
        self.assertEqual(self.check({"status": "rated", "elements": "present", "comment": ""})[0], "schema_invalid")

    def test_an_unknown_status_is_refused(self):
        self.assertEqual(self.check({"status": "maybe", "elements": [], "comment": ""})[0], "unknown_status")

    def test_not_applicable_is_allowed_only_for_an_optional_item(self):
        na = {"status": "not_applicable", "elements": [], "comment": ""}
        self.assertEqual(self.check(na)[0], "not_applicable_not_allowed")
        self.assertEqual(self.check(na, optional=True)[0], "ok")

    def test_an_exceptional_report_needs_every_element_present(self):
        self.assertEqual(self.check(_rated([_present(), _el("partial", 2, "Page 2 text")], exceptional=True))[0],
                         "exceptional_unsupported")
        self.assertEqual(self.check(_rated([_present(), _present(2, "Page 2 text")], exceptional=True))[0], "ok")

    def test_a_level_outside_the_injected_scale_is_unknown_level(self):
        answer = _rated([_present()])
        answer["level"] = "great"
        self.assertEqual(self.check(answer)[0], "unknown_level")

    def test_every_code_returned_is_in_the_table_and_snake_case(self):
        answers = [_rated([_present()]), _rated([]), _rated([_el("absent")]), _rated([_el("present", 1, "NOT IN PAGE")]),
                   _rated([{"verdict": "absent"}]), {"status": "maybe", "elements": [], "comment": ""},
                   {"status": "not_applicable", "elements": [], "comment": ""}]
        for answer in answers:
            code, _message = self.check(answer)
            self.assertIn(code, GRADE_CODES)
            self.assertEqual(code, code.lower())
            self.assertLessEqual(len(code), 30)

    def test_the_message_never_contains_the_quote(self):
        code, message = self.check(_rated([_el("present", 1, "SECRET PHRASE")]))
        self.assertEqual(code, "quote_not_found")
        self.assertNotIn("SECRET", message)


class TestLevelFromElements(unittest.TestCase):
    """The level is computed from the verdicts (review round 1, decision 1)."""

    def test_every_element_present_is_complete_correct(self):
        elements = [_el("present")] * 3
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "complete_correct")

    def test_two_present_and_one_partial_is_partial_by_the_band(self):
        elements = [_el("present"), _el("present"), _el("partial")]
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "partial")

    def test_two_absent_and_one_partial_is_attempted(self):
        elements = [_el("absent"), _el("absent"), _el("partial")]
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "attempted")

    def test_none_present_or_partial_is_absent(self):
        self.assertEqual(ugs_grade.level_for_elements([_el("absent")] * 2, False, TEST_SCALE), "absent")

    def test_a_share_exactly_on_a_band_takes_that_band(self):
        # 3 present, 1 absent: share 0.75 reaches the partial band exactly.
        elements = [_el("present")] * 3 + [_el("absent")]
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "partial")

    def test_the_explicit_exceptional_claim_gives_exemplary(self):
        self.assertEqual(ugs_grade.level_for_elements([_el("present")], True, TEST_SCALE), "exemplary")

    def test_points_never_exceed_the_maximum_for_any_level(self):
        for level in TEST_SCALE.fractions:
            for maximum in (0.1, 0.5, 1, 3, 10):
                self.assertLessEqual(ugs_grade.points_for_level(level, maximum, TEST_SCALE.fractions, STEP), maximum)

    def test_complete_correct_on_a_half_point_item_is_half_a_point(self):
        self.assertEqual(ugs_grade.points_for_level("complete_correct", 0.5, TEST_SCALE.fractions, STEP), 0.5)

    def test_complete_correct_on_ten_points_is_eight_and_three_quarters(self):
        self.assertEqual(ugs_grade.points_for_level("complete_correct", 10, TEST_SCALE.fractions, STEP), 8.75)


class TestGradeItemFlow(unittest.TestCase):
    """grade_item builds the record from the element verdicts, with the retries of the refusals."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def grade(self, responses, language="en", optional=False):
        """Grade the item with the scripted responses; the shipped scale equals TEST_SCALE (checked in its own class)."""
        item = dict(self.item, optional=optional)
        return grade_item(item, PAGES, FakeCall(responses), self.ctx, language, "")

    def test_all_present_gives_complete_correct_points_and_the_element_summary(self):
        record = self.grade([_rated([_present(), _present(2, "Page 2 text", "other")])])
        self.assertEqual(record["validation"], "ok")
        self.assertEqual(record["level"], "complete_correct")
        self.assertEqual(record["score"], 8.75)
        self.assertEqual(record["model_score"], "present 2, partial 0, absent 0")

    def test_the_evidence_is_built_from_the_present_and_partial_elements_only(self):
        record = self.grade([_rated([_present(), _el("absent", name="other"), _el("partial", 2, "Page 2 text", "third")])])
        self.assertEqual(record["evidence"], [{"page": 1, "quote": "Page 1 text"},
                                              {"page": 2, "quote": "Page 2 text"}])
        self.assertEqual([entry["verdict"] for entry in record["elements"]], ["present", "absent", "partial"])

    def test_a_rated_item_with_no_verified_evidence_is_refused_at_any_level(self):
        # The I08 case: a full score on an item whose elements carry no quote is refused, never graded.
        record = self.grade([_rated([_el("present")]), _rated([_el("present")])])
        self.assertEqual(record["validation"], "evidence_incomplete")
        self.assertEqual(record["status"], "rated")
        self.assertIs(record["flag"], True)

    def test_elements_missing_is_asked_again_then_not_run(self):
        record = self.grade([_rated([]), _rated([])])
        self.assertEqual((record["status"], record["validation"], record["score"]), ("not_run", "elements_missing", None))
        self.assertEqual(record["attempts"], 2)

    def test_the_retry_after_elements_missing_asks_for_the_elements(self):
        call = FakeCall([_rated([]), _rated([_present()])])
        record = grade_item(self.item, PAGES, call, self.ctx, "fr", "")
        self.assertEqual(record["validation"], "ok")
        self.assertIn("Liste les éléments demandés.", call.calls[1])

    def test_a_quote_refusal_keeps_the_level_and_the_points_and_is_flagged(self):
        bad = _rated([_el("present", 1, "NOT IN PAGE")])
        record = self.grade([bad, bad])
        self.assertEqual((record["status"], record["validation"]), ("rated", "quote_not_found"))
        self.assertEqual(record["score"], 8.75)
        self.assertEqual(record["level"], "complete_correct")
        self.assertEqual(record["attempts"], 2)
        self.assertIs(record["flag"], True)

    def test_an_exceptional_claim_without_support_is_asked_again(self):
        call = FakeCall([_rated([_present(), _el("partial", 2, "Page 2 text")], exceptional=True),
                         _rated([_present()])])
        record = grade_item(self.item, PAGES, call, self.ctx, "en", "")
        self.assertEqual(record["validation"], "ok")
        self.assertIn("The exceptional claim is not supported.", call.calls[1])

    def test_a_required_item_answered_not_applicable_is_asked_again_with_the_elements_note(self):
        na = {"status": "not_applicable", "elements": [], "comment": ""}
        call = FakeCall([na, na])
        record = grade_item(self.item, PAGES, call, self.ctx, "en", "")
        self.assertEqual(record["validation"], "not_applicable_not_allowed")
        self.assertEqual(record["status"], "not_run")
        self.assertIn("This item is not optional.", call.calls[1])

    def test_an_optional_item_answered_not_applicable_is_accepted(self):
        na = {"status": "not_applicable", "elements": [], "comment": ""}
        record = self.grade([na], optional=True)
        self.assertEqual((record["status"], record["validation"]), ("not_applicable", "ok"))

    def test_over_budget_and_unparsable_keep_their_codes(self):
        def refuse(prompt, schema, images=None):
            raise NotRun("over_budget", "Too big")
        record = grade_item(self.item, PAGES, refuse, self.ctx, "en", "")
        self.assertEqual(record["validation"], "over_budget")
        record = self.grade([NotRun("unparsable", "Failed to parse JSON"), NotRun("unparsable", "Failed to parse JSON")])
        self.assertEqual((record["status"], record["validation"], record["model_score"]),
                         ("not_run", "unparsable_answer", None))


class TestSecurityReviewRound1(unittest.TestCase):
    """Security review of round 1: a refused proof never keeps exemplary points, and a not_applicable answer never
    carries its score or evidence into the record."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def test_an_exceptional_claim_with_one_unverifiable_quote_never_gets_exemplary_points(self):
        bad = _rated([_present(), _present(2, "NOT IN PAGE", "second")], exceptional=True)
        record = grade_item(self.item, PAGES, FakeCall([bad, bad]), self.ctx, "en", "")
        self.assertEqual(record["validation"], "quote_not_found")
        self.assertEqual(record["level"], "complete_correct")
        self.assertEqual(record["score"], 8.75)

    def test_an_exceptional_claim_with_every_quote_verified_gets_exemplary(self):
        good = _rated([_present(), _present(2, "Page 2 text", "second")], exceptional=True)
        record = grade_item(self.item, PAGES, FakeCall([good]), self.ctx, "en", "")
        self.assertEqual(record["validation"], "ok")
        self.assertEqual(record["level"], "exemplary")
        self.assertEqual(record["score"], 10)

    def test_a_not_applicable_record_holds_no_score_and_no_evidence(self):
        na = {"status": "not_applicable", "elements": [], "comment": "N/A"}
        record = grade_item(dict(self.item, optional=True), PAGES, FakeCall([na]), self.ctx, "en", "")
        self.assertEqual(record["status"], "not_applicable")
        self.assertIsNone(record["score"])
        self.assertEqual(record["evidence"], [])
        self.assertIsNone(record["model_score"])

    def test_a_not_applicable_answer_carrying_a_score_is_refused_and_not_copied(self):
        na = {"status": "not_applicable", "elements": [], "comment": "N/A", "score": 5}
        record = grade_item(dict(self.item, optional=True), PAGES, FakeCall([na, na]), self.ctx, "en", "")
        self.assertEqual(record["validation"], "not_applicable_with_score")
        self.assertEqual(record["status"], "not_run")
        self.assertIsNone(record["score"])

    def test_a_not_applicable_answer_carrying_evidence_is_refused_and_not_copied(self):
        na = {"status": "not_applicable", "elements": [], "comment": "N/A",
              "evidence": [{"page": 1, "quote": "Page 1 text"}]}
        record = grade_item(dict(self.item, optional=True), PAGES, FakeCall([na, na]), self.ctx, "en", "")
        self.assertEqual(record["validation"], "not_applicable_with_score")
        self.assertEqual(record["evidence"], [])


class TestMissingField(unittest.TestCase):
    """The record carries `missing`: kept as the model gave it, empty at the full points, cut to the limit."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def grade(self, answer):
        """Grade the item once with the answer."""
        return grade_item(self.item, PAGES, FakeCall([answer]), self.ctx, "en", "")

    def test_missing_is_kept_when_an_element_is_partial(self):
        answer = _rated([_el("partial", 1, "Page 1 text")], missing="Fictitious gap.")
        self.assertEqual(self.grade(answer)["missing"], "Fictitious gap.")

    def test_missing_is_empty_at_full_points(self):
        answer = _rated([_present()], missing="Should not be kept.")
        self.assertEqual(self.grade(answer)["missing"], "")

    def test_a_non_text_missing_is_empty(self):
        answer = _rated([_el("partial", 1, "Page 1 text")])
        answer["missing"] = 5
        self.assertEqual(self.grade(answer)["missing"], "")

    def test_missing_is_trimmed_to_the_limit(self):
        answer = _rated([_el("partial", 1, "Page 1 text")], missing="x" * 500)
        record = grade_item(self.item, PAGES, FakeCall([answer]), self.ctx, "en", "", missing_max_chars=20)
        self.assertEqual(len(record["missing"]), 20)

    def test_record_key_order_is_saved(self):
        record = self.grade(_rated([_present()]))
        self.assertEqual(list(record.keys()), ["item_id", "status", "score", "comment", "evidence", "missing", "audit",
                                               "flag", "model_score", "validation", "attempts", "level", "elements"])


class TestGradeScaleFile(unittest.TestCase):
    """The shipped scale file: fractions, partial weight and bands with provenance; a broken file is a named error."""

    def test_the_shipped_scale_loads_with_its_bands_and_weight(self):
        scale = ugs_grade.load_grade_scale(ASSETS_DIR / "grade_levels.json")
        self.assertEqual(scale.bands[-1][0], Decimal("0"))
        self.assertEqual(scale.partial_weight, Decimal("0.5"))
        self.assertEqual(sorted(scale.fractions), ["absent", "attempted", "complete_correct", "exemplary", "partial"])

    def test_descriptions_are_not_in_the_scale_file(self):
        data = json.loads((ASSETS_DIR / "grade_levels.json").read_text(encoding="utf-8"))
        for name, entry in data["levels"].items():
            self.assertEqual(set(entry), {"fraction"}, name)

    def test_a_band_naming_no_known_level_is_a_named_error(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "levels.json"
        path.write_text(json.dumps({"levels": {"absent": {"fraction": 0}}, "partial_weight": {"value": 0.5},
                                    "bands": {"list": [{"min_share": 0, "level": "ghost"}]}}), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            ugs_grade.load_grade_scale(path)
        self.assertIn("names no known level", str(raised.exception))

    def test_the_last_band_must_reach_a_share_of_zero(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "levels.json"
        path.write_text(json.dumps({"levels": {"absent": {"fraction": 0}}, "partial_weight": {"value": 0.5},
                                    "bands": {"list": [{"min_share": 0.5, "level": "absent"}]}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            ugs_grade.load_grade_scale(path)


class TestNoPromptStatesANumber(unittest.TestCase):
    """No prompt carries a fraction the model could copy as a score (plan 25, Task 1)."""

    def test_the_prompts_state_no_decimal_fraction(self):
        for name in ("levels.md", "grade_item.md", "audit_item.md", "retry_grade_item.md"):
            text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b0[.,]\d+\b|\b1\.0\b", text), name)

    def test_the_check_can_fail_on_a_prompt_with_a_fraction(self):
        self.assertIsNotNone(re.search(r"\b0[.,]\d+\b", "complete and correct = 0.88 of max_points"))


class TestRetryWording(unittest.TestCase):
    """The retry templates ask for the elements and name no score (review round 1, decision 3)."""

    def test_no_retry_section_names_a_score(self):
        text = (PROMPTS_DIR / "retry_grade_item.md").read_text(encoding="utf-8")
        self.assertNotIn("score", text.lower())
        self.assertNotIn("SCORE", text)

    def test_every_refusal_that_retries_has_its_section(self):
        text = (PROMPTS_DIR / "retry_grade_item.md").read_text(encoding="utf-8")
        for section in ugs_grade.RETRY_SECTION_BY_CODE.values():
            self.assertIn(f"## fr_{section}", text)
            self.assertIn(f"## en_{section}", text)


class TestTotals(unittest.TestCase):
    """A refused proof keeps its points in the totals."""

    def test_a_refused_proof_keeps_its_points_in_the_totals(self):
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        ctx = make_ctx()
        bad = _rated([_el("present", 1, "NOT IN PAGE")])
        record = grade_item(item, PAGES, FakeCall([bad, bad]), ctx, "en", "")
        result = grade_total.compute({"assessment_type": "lab_report", "total_points": 10, "items": [item]},
                                     {"report_id": "R01", "items": [record]})
        self.assertEqual(float(result["total"]), 8.75)


if __name__ == "__main__":
    unittest.main()
