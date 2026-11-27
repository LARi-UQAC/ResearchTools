"""
Tests of the grade record and its validation codes (ugs_grade.py), review round 2.

The model names the elements a rubric item asks for and a verdict on each. Each present or partial element is verified
element by element (quote_match, three tiers); the level is computed from the effective verdicts (an unverified present
element counts as partial). Every fixture is fictitious (R34). The model is a scripted call, so no model runs (R21).
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
from ugs_grade import GRADE_CODES, GradeScale, grade_item, with_level_score, check_grade_answer  # noqa: E402
from ugs_text import StepContext  # noqa: E402
from ugs_bridge import NotRun  # noqa: E402
from ugs_config import default_path  # noqa: E402
import grade_total  # noqa: E402

PAGES = ["The first page describes the fictive engine test in detail.",
         "The second page gives the fictive conclusion of the study."]
PROMPTS_DIR = SCRIPTS.parent / "prompts"
ASSETS_DIR = SCRIPTS.parent / "assets"

# The scale and the settings of the tests, fixed here so the tests pin the rules and not the shipped values.
TEST_SCALE = GradeScale(
    fractions={"absent": Decimal("0"), "attempted": Decimal("0.5"), "partial": Decimal("0.75"),
               "complete_correct": Decimal("0.88"), "exemplary": Decimal("1.0")},
    partial_weight=Decimal("0.5"),
    bands=((Decimal("0.75"), "partial"), (Decimal("0"), "attempted")),
)
STEP = Decimal("0.25")
QUOTE = {"min_chars": 12, "min_words": 3, "min_word_share": 0.9, "window_factor": 1.3, "page_window": 1, "max_words": 24}
SETTINGS = {"quote": QUOTE, "unverified_as": "partial", "step": STEP, "max_elements": 12,
            "comment_openings": ["le rapport", "ce rapport", "the report", "this report"], "min_model_elements": 1}


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
                "## en_elements\nList the elements asked.\n\n"
                "## fr_evidence\nCite une preuve exacte.\n\n"
                "## en_evidence\nCite an exact quote.\n\n"
                "## fr_not_applicable\nNon facultatif.\n\n"
                "## en_not_applicable\nNot optional.\n\n"
                "## fr_mismatch\nMismatch.\n\n"
                "## en_mismatch\nMismatch.\n\n"
                "## fr_comment\nComment.\n\n"
                "## en_comment\nComment.\n\n"
                "## fr_few\nFew.\n\n"
                "## en_few\nFew.\n"
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


def _present(page=1, quote="The first page describes the fictive engine test", name="element"):
    """Return a present element whose quote is on its page."""
    return _el("present", page, quote, name)


def _prepared(answer, item=None):
    """Run the element verification and the level computation on a raw answer."""
    item = item or {"id": "I01", "title": "Intro", "max_points": 10}
    return with_level_score(answer, item, TEST_SCALE, STEP, PAGES, QUOTE, "partial", 12)


class TestCheckGradeAnswer(unittest.TestCase):
    """The validation codes of a prepared answer."""

    def check(self, answer, optional=False, item_extra=None):
        """Prepare and check one answer against a fictitious item."""
        item = {"id": "I01", "title": "Intro", "max_points": 10, "optional": optional}
        item.update(item_extra or {})
        prepared = with_level_score(answer, item, TEST_SCALE, STEP, PAGES, QUOTE, "partial", 12)
        return check_grade_answer(prepared, item, PAGES)

    def test_a_verified_present_element_is_ok(self):
        self.assertEqual(self.check(_rated([_present()]))[0], "ok")

    def test_a_verified_partial_element_is_ok(self):
        self.assertEqual(self.check(_rated([_el("partial", 2, "The second page gives the fictive conclusion")]))[0],
                         "ok")

    def test_an_empty_element_list_is_elements_missing(self):
        self.assertEqual(self.check(_rated([]))[0], "elements_missing")

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

    def test_not_applicable_carrying_a_score_or_evidence_is_refused(self):
        na = {"status": "not_applicable", "elements": [], "comment": "", "score": 5}
        self.assertEqual(self.check(na, optional=True)[0], "not_applicable_with_score")
        na = {"status": "not_applicable", "elements": [], "comment": "", "evidence": [{"page": 1, "quote": "x"}]}
        self.assertEqual(self.check(na, optional=True)[0], "not_applicable_with_score")

    def test_an_item_with_no_verified_element_is_evidence_missing(self):
        self.assertEqual(self.check(_rated([_present(quote="A sentence that no page holds at all")]))[0],
                         "evidence_missing")

    def test_all_absent_is_accepted_only_with_its_missing_text(self):
        absent = [_el("absent", name="a"), _el("absent", name="b")]
        self.assertEqual(self.check(_rated(absent, missing="The table of results is missing."))[0], "ok")
        self.assertEqual(self.check(_rated(absent))[0], "evidence_missing")

    def test_too_few_elements_for_the_checklist_are_refused(self):
        code = self.check(_rated([_present()]), item_extra={"checklist": ["one", "two", "three"]})[0]
        self.assertEqual(code, "elements_too_few")

    def test_repeated_elements_count_once_for_the_checklist(self):
        elements = [_present(name="Figure"), _present(name="figure"), _present(name="Table")]
        code = self.check(_rated(elements), item_extra={"checklist": ["Figure", "Table"]})[0]
        self.assertEqual(code, "ok")

    def test_every_code_returned_is_in_the_table_and_snake_case(self):
        answers = [_rated([_present()]), _rated([]), _rated([_el("absent")]),
                   _rated([_present(quote="NOT IN ANY PAGE HERE")]), _rated([{"verdict": "absent"}]),
                   {"status": "maybe", "elements": [], "comment": ""},
                   {"status": "not_applicable", "elements": [], "comment": ""}]
        for answer in answers:
            code, _message = self.check(answer)
            self.assertIn(code, GRADE_CODES)
            self.assertEqual(code, code.lower())
            self.assertLessEqual(len(code), 30)

    def test_the_removed_codes_are_gone(self):
        for code in ("quote_not_found", "evidence_incomplete", "evidence_page_out_of_range",
                     "exceptional_unsupported", "unknown_level", "score_above_max"):
            self.assertNotIn(code, GRADE_CODES)

    def test_the_message_never_contains_the_quote(self):
        code, message = self.check(_rated([_present(quote="SECRET PHRASE")]))
        self.assertEqual(code, "evidence_missing")
        self.assertNotIn("SECRET", message)


class TestLevelFromElements(unittest.TestCase):
    """The level is computed from the effective verdicts."""

    def test_every_element_present_is_complete_correct(self):
        self.assertEqual(ugs_grade.level_for_elements([{"verdict": "present", "effective": "present"}] * 3, False,
                                                      TEST_SCALE), "complete_correct")

    def test_two_present_and_one_partial_is_partial_by_the_band(self):
        elements = [{"effective": "present"}, {"effective": "present"}, {"effective": "partial"}]
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "partial")

    def test_a_single_partial_element_alone_is_attempted(self):
        # The prompt says so (levels.md): one partial element and nothing else gives attempted.
        self.assertEqual(ugs_grade.level_for_elements([{"effective": "partial"}], False, TEST_SCALE), "attempted")

    def test_none_present_or_partial_is_absent(self):
        self.assertEqual(ugs_grade.level_for_elements([{"effective": "absent"}] * 2, False, TEST_SCALE), "absent")

    def test_a_share_exactly_on_a_band_takes_that_band(self):
        elements = [{"effective": "present"}] * 3 + [{"effective": "absent"}]
        self.assertEqual(ugs_grade.level_for_elements(elements, False, TEST_SCALE), "partial")

    def test_points_never_exceed_the_maximum_for_any_level(self):
        for level in TEST_SCALE.fractions:
            for maximum in (0.1, 0.5, 1, 3, 10):
                self.assertLessEqual(ugs_grade.points_for_level(level, maximum, TEST_SCALE.fractions, STEP), maximum)

    def test_complete_correct_on_ten_points_is_eight_and_three_quarters(self):
        self.assertEqual(ugs_grade.points_for_level("complete_correct", 10, TEST_SCALE.fractions, STEP), 8.75)


class TestElementVerification(unittest.TestCase):
    """Each element is verified; an unverified present counts as partial; repeated names count once."""

    def test_an_unverified_present_element_counts_as_partial(self):
        prepared = _prepared(_rated([_present(quote="A sentence that no page holds at all")]))
        self.assertEqual(prepared["elements"][0]["effective"], "partial")
        self.assertFalse(prepared["elements"][0]["verified"])

    def test_a_verified_element_records_its_tier_and_the_tiers_tried(self):
        prepared = _prepared(_rated([_present()]))
        element = prepared["elements"][0]
        self.assertTrue(element["verified"])
        self.assertEqual(element["tier"], "key")
        self.assertEqual(element["tiers_tried"], ["key"])

    def test_a_quote_on_the_next_page_corrects_the_page(self):
        prepared = _prepared(_rated([_present(page=1, quote="The second page gives the fictive conclusion")]))
        self.assertEqual(prepared["elements"][0]["page"], 2)
        self.assertTrue(prepared["elements"][0]["page_corrected"])

    def test_a_repeated_element_name_is_counted_once(self):
        prepared = _prepared(_rated([_present(name="Figure"), _present(name="  figure ")]))
        self.assertEqual(len(prepared["elements"]), 1)

    def test_the_model_summary_counts_the_effective_verdicts(self):
        unverified = _rated([_present(quote="A sentence that no page holds at all")])
        record = grade_item({"id": "I01", "title": "Intro", "max_points": 10}, PAGES,
                            FakeCall([unverified, unverified]), make_ctx(), "en", "", settings=SETTINGS)
        self.assertEqual(record["model_score"], "present 0, partial 1, absent 0")


class TestSecurityAndRoundTwoFlow(unittest.TestCase):
    """The item flow: exemplary never from an unverified quote, the not_applicable record, the all-absent item, and the
    best answer across attempts."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def grade(self, responses, optional=False):
        """Grade the item with the scripted responses."""
        item = dict(self.item, optional=optional)
        return grade_item(item, PAGES, FakeCall(responses), self.ctx, "en", "", settings=SETTINGS)

    def test_an_exceptional_claim_with_one_unverifiable_quote_never_gets_exemplary_points(self):
        bad = _rated([_present(), _present(2, "A sentence that no page holds at all", "second")], exceptional=True)
        record = self.grade([bad])
        self.assertNotEqual(record["level"], "exemplary")
        self.assertLess(record["score"], 10)
        self.assertEqual(record["validation"], "ok")

    def test_an_exceptional_claim_with_every_quote_verified_gets_exemplary(self):
        good = _rated([_present(), _present(2, "The second page gives the fictive conclusion", "second")],
                      exceptional=True)
        record = self.grade([good])
        self.assertEqual(record["level"], "exemplary")
        self.assertEqual(record["score"], 10)

    def test_an_exceptional_claim_that_does_not_hold_is_dropped_not_refused(self):
        claim = _rated([_present(), _el("partial", 2, "The second page gives the fictive conclusion", "second")],
                       exceptional=True)
        record = self.grade([claim])
        self.assertEqual(record["validation"], "ok")
        self.assertNotEqual(record["level"], "exemplary")

    def test_a_not_applicable_record_holds_no_score_and_no_evidence(self):
        na = {"status": "not_applicable", "elements": [], "comment": "N/A"}
        record = self.grade([na], optional=True)
        self.assertEqual(record["status"], "not_applicable")
        self.assertIsNone(record["score"])
        self.assertEqual(record["evidence"], [])
        self.assertIsNone(record["model_score"])

    def test_a_not_applicable_answer_carrying_a_score_is_refused_and_not_copied(self):
        na = {"status": "not_applicable", "elements": [], "comment": "N/A", "score": 5}
        record = self.grade([na, na], optional=True)
        self.assertEqual(record["validation"], "not_applicable_with_score")
        self.assertEqual(record["status"], "not_run")
        self.assertIsNone(record["score"])

    def test_an_all_absent_item_with_its_missing_text_is_absent_with_zero_points(self):
        record = self.grade([_rated([_el("absent", name="a"), _el("absent", name="b")], missing="Fictive gap.")])
        self.assertEqual((record["validation"], record["level"], record["score"]), ("ok", "absent", 0.0))
        self.assertEqual(record["evidence"], [])

    def test_an_all_absent_item_without_its_missing_text_is_asked_again_then_not_run(self):
        absent = _rated([_el("absent")])
        record = self.grade([absent, absent])
        self.assertEqual((record["status"], record["validation"]), ("not_run", "evidence_missing"))
        self.assertEqual(record["attempts"], 2)

    def test_the_record_keeps_the_answer_with_the_most_verified_elements_across_attempts(self):
        # The checklist asks for three elements: both attempts are refused, the first one with one verified element.
        item = dict(self.item, checklist=["one", "two", "three"])
        one_verified = _rated([_present()])
        none_verified = _rated([_present(quote="fabricated words not here at all")])
        record = grade_item(item, PAGES, FakeCall([one_verified, none_verified]), self.ctx, "en", "",
                            settings=SETTINGS)
        self.assertEqual(record["validation"], "elements_too_few")
        self.assertTrue(record["elements"][0]["verified"])

    def test_a_retry_after_elements_too_few_asks_for_the_elements(self):
        call = FakeCall([_rated([_present()]), _rated([_present(), _present(2, "The second page gives the fictive conclusion", "b")])])
        item = dict(self.item, checklist=["one", "two"])
        record = grade_item(item, PAGES, call, self.ctx, "fr", "", settings=SETTINGS)
        self.assertEqual(record["validation"], "ok")
        self.assertIn("Liste les éléments demandés.", call.calls[1])

    def test_the_record_elements_carry_verified_tier_and_no_quote(self):
        record = self.grade([_rated([_present()])])
        element = record["elements"][0]
        self.assertEqual((element["verified"], element["tier"]), (True, "key"))
        self.assertNotIn("quote", element)


class TestRoundTwoCapsAndDowngrade(unittest.TestCase):
    """Security review of round 2: an unverified partial is absent; the element cap and the quote cap."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def test_an_unverified_partial_counts_as_absent(self):
        prepared = _prepared(_rated([_el("partial", 1, "A sentence that no page holds at all")]))
        self.assertEqual(prepared["elements"][0]["effective"], "absent")

    def test_an_item_whose_only_engaged_elements_are_unverified_partials_gets_no_credit(self):
        unverified = _rated([_el("partial", 1, "A sentence that no page holds at all")], missing="Fictive gap.")
        record = grade_item(self.item, PAGES, FakeCall([unverified]), self.ctx, "en", "", settings=SETTINGS)
        self.assertEqual((record["level"], record["score"]), ("absent", 0.0))
        bare = _rated([_el("partial", 1, "A sentence that no page holds at all")])
        record = grade_item(self.item, PAGES, FakeCall([bare, bare]), self.ctx, "en", "", settings=SETTINGS)
        self.assertEqual(record["validation"], "evidence_missing")

    def test_elements_beyond_the_cap_are_ignored_and_counted(self):
        elements = [_present(name="element %d" % n) for n in range(13)]
        record = grade_item(self.item, PAGES, FakeCall([_rated(elements)]), self.ctx, "en", "", settings=SETTINGS)
        self.assertEqual(len(record["elements"]), 12)
        self.assertEqual(record["elements_ignored"], 1)

    def test_an_over_long_element_quote_is_unverified_when_only_fuzzy_would_match(self):
        words = ["w%d" % n for n in range(30)]
        page = " ".join(words[:-1] + ["changed"])
        prepared = _prepared(_rated([_el("present", 1, " ".join(words), "long")]))
        self.assertFalse(prepared["elements"][0]["verified"])
        self.assertEqual(prepared["elements"][0]["effective"], "partial")


class TestMissingField(unittest.TestCase):
    """The record carries `missing`: kept as the model gave it, empty when every element is present, cut to the limit."""

    def setUp(self):
        self.ctx = make_ctx()
        self.item = {"id": "I01", "title": "Intro", "max_points": 10}

    def grade(self, answer, missing_max_chars=None):
        """Grade the item once with the answer."""
        return grade_item(self.item, PAGES, FakeCall([answer]), self.ctx, "en", "", missing_max_chars=missing_max_chars,
                          settings=SETTINGS)

    def test_missing_is_kept_when_an_element_is_partial(self):
        answer = _rated([_el("partial", 1, "The first page describes the fictive engine test")], missing="Fictive gap.")
        self.assertEqual(self.grade(answer)["missing"], "Fictive gap.")

    def test_missing_is_empty_when_every_element_is_present(self):
        self.assertEqual(self.grade(_rated([_present()], missing="Should not be kept."))["missing"], "")

    def test_a_non_text_missing_is_empty(self):
        answer = _rated([_el("partial", 1, "The first page describes the fictive engine test")])
        answer["missing"] = 5
        self.assertEqual(self.grade(answer)["missing"], "")

    def test_missing_is_trimmed_to_the_limit(self):
        answer = _rated([_el("partial", 1, "The first page describes the fictive engine test")], missing="x" * 500)
        self.assertEqual(len(self.grade(answer, missing_max_chars=20)["missing"]), 20)

    def test_record_key_order_is_saved(self):
        record = self.grade(_rated([_present()]))
        self.assertEqual(list(record.keys()), ["item_id", "status", "score", "comment", "evidence", "missing", "audit",
                                               "flag", "model_score", "validation", "attempts", "level", "elements_ignored", "losses", "elements"])


class TestGradeScaleFile(unittest.TestCase):
    """The shipped scale file: fractions, partial weight and bands; a broken file is a named error."""

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
        path = Path(tempfile.mkdtemp()) / "levels.json"
        path.write_text(json.dumps({"levels": {"absent": {"fraction": 0}}, "partial_weight": {"value": 0.5},
                                    "bands": {"list": [{"min_share": 0, "level": "ghost"}]}}), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            ugs_grade.load_grade_scale(path)
        self.assertIn("names no known level", str(raised.exception))

    def test_the_last_band_must_reach_a_share_of_zero(self):
        path = Path(tempfile.mkdtemp()) / "levels.json"
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

    def test_the_element_prompt_asks_for_quotes_of_twelve_words_at_most(self):
        text = (PROMPTS_DIR / "levels.md").read_text(encoding="utf-8")
        self.assertIn("twelve words at most", text)
        self.assertIn("no table bars", text)


class TestRetryWording(unittest.TestCase):
    """The retry templates ask for the elements and the evidence, and name no score."""

    def test_no_retry_section_names_a_number_to_copy(self):
        text = (PROMPTS_DIR / "retry_grade_item.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b0[.,]\d+\b|\b1\.0\b|\{\{SCORE\}\}", text))

    def test_every_refusal_that_retries_has_its_section(self):
        text = (PROMPTS_DIR / "retry_grade_item.md").read_text(encoding="utf-8")
        for section in set(ugs_grade.RETRY_SECTION_BY_CODE.values()):
            self.assertIn(f"## fr_{section}", text)
            self.assertIn(f"## en_{section}", text)


class TestTotals(unittest.TestCase):
    """A refused item keeps no points in the totals; a graded item counts its points."""

    def test_a_graded_item_counts_its_points_in_the_totals(self):
        item = {"id": "I01", "title": "Intro", "max_points": 10}
        record = grade_item(item, PAGES, FakeCall([_rated([_present()])]), make_ctx(), "en", "", settings=SETTINGS)
        result = grade_total.compute({"assessment_type": "lab_report", "total_points": 10, "items": [item]},
                                     {"report_id": "R01", "items": [record]})
        # One element present gives the whole maximum: the points come from the elements, not from a level (2026-11-27).
        self.assertEqual(float(result["total"]), 10.0)


FINE_STEP = Decimal("0.001")
OPENINGS = ["le rapport", "ce rapport", "the report", "this report"]
SETTINGS_FINE = dict(SETTINGS, step=FINE_STEP, comment_openings=OPENINGS, min_model_elements=1)
ITEM_FOUR = {"id": "I01", "title": "Intro", "max_points": 1,
             "elements": [{"id": "E1", "text": "Contexte"}, {"id": "E2", "text": "Objectif"},
                          {"id": "E3", "text": "Methode"}, {"id": "E4", "text": "Resultat"}]}
GOOD_QUOTE = "The first page describes the fictive engine test"
SECOND_QUOTE = "The second page gives the fictive conclusion"


def _rubric_element(identifier, verdict, page=1, quote=GOOD_QUOTE):
    """Return one element of an answer to an item that has rubric elements (fictitious)."""
    return {"id": identifier, "verdict": verdict, "page": page, "quote": quote}


def _four_answer(last_verdict="partial", comment="Cette section est presque complete."):
    """Return an answer naming E1 to E4, the last one with the given verdict."""
    last_page, last_quote = (2, SECOND_QUOTE) if last_verdict == "partial" else (1, GOOD_QUOTE)
    return {"status": "rated", "comment": comment, "elements": [
        _rubric_element("E1", "present"), _rubric_element("E2", "present"), _rubric_element("E3", "present"),
        _rubric_element("E4", last_verdict, last_page, last_quote)]}


class TestElementPoints(unittest.TestCase):
    """The points are the share of the maximum that the element credits give (owner, 2026-11-27)."""

    def test_four_elements_one_partial_on_one_point_is_0_875(self):
        elements = [{"effective": "present"}] * 3 + [{"effective": "partial"}]
        self.assertEqual(ugs_grade.points_for_elements(elements, Decimal(1), TEST_SCALE, FINE_STEP), Decimal("0.875"))

    def test_all_present_is_the_maximum_and_all_absent_is_zero(self):
        present = [{"effective": "present"}] * 4
        absent = [{"effective": "absent"}] * 4
        self.assertEqual(ugs_grade.points_for_elements(present, Decimal(1), TEST_SCALE, FINE_STEP), Decimal(1))
        self.assertEqual(ugs_grade.points_for_elements(absent, Decimal(1), TEST_SCALE, FINE_STEP), Decimal(0))

    def test_three_elements_one_absent_on_half_a_point_is_0_333(self):
        elements = [{"effective": "present"}] * 2 + [{"effective": "absent"}]
        self.assertEqual(ugs_grade.points_for_elements(elements, Decimal("0.5"), TEST_SCALE, FINE_STEP),
                         Decimal("0.333"))

    def test_a_partial_element_costs_half_its_share_and_the_loss_is_named(self):
        elements = [{"id": "E1", "element": "Contexte", "effective": "present"},
                    {"id": "E2", "element": "Objectif", "effective": "present"},
                    {"id": "E3", "element": "Methode", "effective": "present"},
                    {"id": "E4", "element": "Resultat", "effective": "partial"}]
        losses = ugs_grade.element_losses(elements, Decimal(1), TEST_SCALE)
        self.assertEqual(losses, [{"id": "E4", "text": "Resultat", "verdict": "partial", "lost": 0.125,
                                   "unverified": False}])

    def test_a_partial_whose_quote_did_not_verify_is_marked_unverified_in_its_loss(self):
        # Review round 1, finding 11: an engaged verdict (present or partial) whose quote did not verify is flagged.
        elements = [{"id": "E1", "element": "Contexte", "effective": "present", "verdict": "present", "verified": True},
                    {"id": "E2", "element": "Objectif", "effective": "absent", "verdict": "partial", "verified": False}]
        losses = ugs_grade.element_losses(elements, Decimal(1), TEST_SCALE)
        self.assertEqual(len(losses), 1)
        self.assertTrue(losses[0]["unverified"])

    def test_the_points_are_read_from_elements_not_from_the_level(self):
        record = grade_item(ITEM_FOUR, PAGES, FakeCall([_four_answer()]), make_ctx(), "fr", "",
                            settings=SETTINGS_FINE)
        self.assertEqual(record["score"], 0.875)
        self.assertEqual(record["losses"][0]["text"], "Resultat")
        self.assertEqual(record["losses"][0]["lost"], 0.125)

    def test_the_maximum_is_kept_when_every_element_is_present(self):
        answer = _four_answer(last_verdict="present")
        record = grade_item(ITEM_FOUR, PAGES, FakeCall([answer]), make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(record["score"], 1)
        self.assertEqual(record["losses"], [])

    def test_an_unverified_present_element_is_partial_and_is_flagged_in_its_loss(self):
        answer = _four_answer(last_verdict="present")
        answer["elements"][3]["quote"] = "Totally unrelated words appear in this quote"
        record = grade_item(ITEM_FOUR, PAGES, FakeCall([answer]), make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(record["score"], 0.875)
        self.assertTrue(record["losses"][0]["unverified"])


class TestRubricElementIds(unittest.TestCase):
    """An answer names exactly the element ids of its rubric item; a mismatch is asked again, then refused."""

    def test_a_wrong_id_set_is_elements_mismatch_before_any_score(self):
        answer = _four_answer()
        answer["elements"][3]["id"] = "E9"
        prepared = with_level_score(answer, ITEM_FOUR, TEST_SCALE, FINE_STEP, PAGES, QUOTE, "partial", 12)
        code, _ = check_grade_answer(prepared, ITEM_FOUR, PAGES)
        self.assertEqual(code, "elements_mismatch")

    def test_an_omitted_element_id_is_elements_mismatch(self):
        # Review round 1, group D: the answer omits E4 (it names E1 to E3 only), so the id set differs.
        answer = _four_answer()
        answer["elements"] = answer["elements"][:3]
        prepared = with_level_score(answer, ITEM_FOUR, TEST_SCALE, FINE_STEP, PAGES, QUOTE, "partial", 12)
        code, _ = check_grade_answer(prepared, ITEM_FOUR, PAGES)
        self.assertEqual(code, "elements_mismatch")

    def test_a_mismatch_is_asked_again_once_then_not_run(self):
        bad = _four_answer()
        bad["elements"][3]["id"] = "E9"
        call = FakeCall([bad, bad])
        record = grade_item(ITEM_FOUR, PAGES, call, make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(len(call.calls), 2)
        self.assertEqual(record["validation"], "elements_mismatch")
        self.assertEqual(record["status"], "not_run")
        self.assertIsNone(record["score"])

    def test_the_prompt_names_the_element_ids_and_the_real_prompt_asks_for_this_section(self):
        call = FakeCall([_four_answer()])
        grade_item(ITEM_FOUR, PAGES, call, make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertIn("E1: Contexte", call.calls[0])
        real = (PROMPTS_DIR / "grade_item.md").read_text(encoding="utf-8")
        self.assertIn("cette section", real.lower())
        self.assertIn("this section", real.lower())
        self.assertNotIn("le rapport est", real.lower())


class TestCommentScope(unittest.TestCase):
    """A comment opening on the whole report is asked again once, then its sentence is dropped."""

    def test_a_forbidden_opening_is_asked_again_then_the_sentence_is_dropped(self):
        bad = _four_answer(comment="Le rapport est complet.")
        call = FakeCall([bad, bad])
        record = grade_item(ITEM_FOUR, PAGES, call, make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(len(call.calls), 2)
        self.assertEqual(record["comment"], "")
        self.assertEqual(record["comment_code"], "comment_scope")
        self.assertEqual(record["validation"], "ok")
        self.assertEqual(record["status"], "rated")

    def test_a_second_answer_that_complies_keeps_its_comment(self):
        bad = _four_answer(comment="Le rapport est complet.")
        good = _four_answer(comment="Cette section est presque complete.")
        record = grade_item(ITEM_FOUR, PAGES, FakeCall([bad, good]), make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(record["comment"], "Cette section est presque complete.")
        self.assertNotIn("comment_code", record)

    def test_the_openings_come_from_the_configuration(self):
        openings = ugs_grade.read_comment_openings(default_path())
        self.assertIn("le rapport", openings)
        self.assertIn("the report", openings)
        self.assertIn("ce rapport", openings)


class TestGradeConfigPoints(unittest.TestCase):
    """The rounding step is the owner's 0.001 point, and the new codes are in the table."""

    def test_the_score_step_is_one_thousandth_of_a_point(self):
        self.assertEqual(ugs_grade.read_grade_step(default_path()), Decimal("0.001"))

    def test_the_new_codes_are_in_the_table(self):
        self.assertIn("elements_mismatch", GRADE_CODES)
        self.assertIn("comment_scope", GRADE_CODES)


SETTINGS_FEW = dict(SETTINGS_FINE, min_model_elements=3)
ITEM_MODEL = {"id": "I01", "title": "Intro", "max_points": 1}


def _model_answer(names, comment="Cette section est presque complete.", ids=None):
    """Return a rated answer naming the given model elements, all present and with a quote on page 1 (fictitious)."""
    return {"status": "rated", "comment": comment,
            "elements": [{"element": name, "verdict": "present", "page": 1, "quote": GOOD_QUOTE} for name in names]}


class TestCommentScopeFallbacks(unittest.TestCase):
    """Review round 1, group B, finding 3: a comment-scope answer is the fallback; it is never not_run."""

    def record(self, responses, retries):
        """Grade ITEM_FOUR with scripted answers and the given number of retries."""
        ctx = make_ctx()
        ctx.grade_retries = retries
        return grade_item(ITEM_FOUR, PAGES, FakeCall(responses), ctx, "fr", "", settings=SETTINGS_FINE)

    def test_scope_alone_with_no_retry_left_is_kept_with_its_sentence_dropped(self):
        record = self.record([_four_answer(comment="Le rapport est complet.")], retries=0)
        self.assertEqual(record["status"], "rated")
        self.assertEqual(record["comment"], "")
        self.assertEqual(record["comment_code"], "comment_scope")
        self.assertEqual(record["validation"], "ok")

    def test_mismatch_then_scope_returns_the_scope_answer_not_not_run(self):
        bad = _four_answer()
        bad["elements"][3]["id"] = "E9"
        record = self.record([bad, _four_answer(comment="Le rapport est complet.")], retries=1)
        self.assertEqual(record["status"], "rated")
        self.assertEqual(record["comment_code"], "comment_scope")

    def test_scope_then_mismatch_returns_the_scope_answer_not_not_run(self):
        bad = _four_answer()
        bad["elements"][3]["id"] = "E9"
        record = self.record([_four_answer(comment="Le rapport est complet."), bad], retries=1)
        self.assertEqual(record["status"], "rated")
        self.assertEqual(record["comment_code"], "comment_scope")
        self.assertEqual(record["comment"], "")


class TestRubricElementsPerId(unittest.TestCase):
    """Review round 1, group B, finding 5: rubric elements are prepared per id, never merged by name."""

    def test_two_identical_checklist_lines_are_two_elements(self):
        item = {"id": "I01", "title": "Intro", "max_points": 1,
                "elements": [{"id": "E1", "text": "Equipment is listed."},
                             {"id": "E2", "text": "Equipment is listed."}]}
        answer = {"status": "rated", "comment": "Cette section est presque complete.", "elements": [
            _rubric_element("E1", "present"), _rubric_element("E2", "absent", page=None, quote=None)]}
        record = grade_item(item, PAGES, FakeCall([answer]), make_ctx(), "fr", "", settings=SETTINGS_FINE)
        self.assertEqual(len(record["elements"]), 2)
        self.assertEqual(record["score"], 0.5)


class TestMinimumModelElements(unittest.TestCase):
    """Review round 1, group B, finding 7: a model-named item must name at least grade.min_model_elements."""

    def grade(self, responses):
        """Grade the model-named item with the given scripted answers."""
        call = FakeCall(responses)
        record = grade_item(ITEM_MODEL, PAGES, call, make_ctx(), "fr", "", settings=SETTINGS_FEW)
        return record, call

    def test_one_element_is_asked_again_then_rated_with_elements_few(self):
        record, call = self.grade([_model_answer(["Alpha"]), _model_answer(["Alpha"])])
        self.assertEqual(len(call.calls), 2)
        self.assertEqual(record["status"], "rated")
        self.assertEqual(record["validation"], "elements_few")
        self.assertEqual(record["score"], 1)

    def test_a_second_answer_with_enough_elements_is_kept_as_ok(self):
        record, call = self.grade([_model_answer(["Alpha"]), _model_answer(["Alpha", "Beta", "Gamma"])])
        self.assertEqual(record["validation"], "ok")

    def test_the_minimum_is_read_from_the_configuration(self):
        self.assertEqual(ugs_grade.read_min_model_elements(default_path()), 3)


class TestGroupBOpeningsAndRules(unittest.TestCase):
    """Review round 1, group B, finding 9: an opening is a whole word after the punctuation is stripped."""

    def test_a_word_that_only_starts_like_the_opening_is_not_forbidden(self):
        self.assertFalse(ugs_grade.opens_forbidden("The reported results are fine.", ["the report"]))

    def test_markdown_emphasis_and_guillemets_do_not_hide_the_opening(self):
        self.assertTrue(ugs_grade.opens_forbidden("**Le rapport** est complet.", ["le rapport"]))
        self.assertTrue(ugs_grade.opens_forbidden("« Le rapport est complet.", ["le rapport"]))
        self.assertTrue(ugs_grade.opens_forbidden("Le rapport est complet.", ["le rapport"]))


if __name__ == "__main__":
    unittest.main()
