"""Offline tests for pdf2md_vlmcheck. No model, PDF render or network is used:
the renderer and the HTTP caller are injected (R20, R21), and every text
fixture is fictitious (R34).

What is proven is the part a model cannot be trusted with: which pages are
chosen, what the request carries (reasoning off, bounded context, schema,
fixed sampling), and that an answer that does not fit the schema is an error
row and never a pass. The earlier --vlm-check accepted an empty {} as a
success, which is the regression pinned here."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf2md_vlmcheck import (
    KIND_DIFFERS,
    KIND_MISSING,
    STATUS_ERROR,
    STATUS_NO_FORMULA,
    STATUS_OK,
    PageChoice,
    VlmAnswerError,
    answer_schema,
    ask_model,
    build_excerpt,
    build_prompt,
    build_request_body,
    check_page,
    load_vlmcheck_config,
    render_vlm_md,
    run_vlm_fidelity,
    select_pages,
    validate_answer,
)

FIDELITY = {
    "min_prose_tokens": 12,
    "min_token_letters": 3,
    "min_prose_ratio": 0.6,
    "ngram_chars": 12,
    "paragraph_missing_below": 0.5,
    "locate_chunk_words": 40,
    "locate_secondary_vote_share": 0.5,
    "locate_max_span_paragraphs": 12,
}
CONFIG = {
    "base_url": "http://localhost:11434",
    "timeout_s": 7,
    "dpi": 150,
    "num_ctx": 4096,
    "think": False,
    "temperature": 0,
    "seed": 0,
    "pages_per_chapter": 2,
    "excerpt_margin_lines": 1,
    "max_markdown_chars": 200,
    "max_formulas": 5,
}
MATH_SYMBOLS = "=+*/^_<>"

P1 = "The orchard keepers measured rainfall across every terrace during the long dry season and recorded each reading in a shared notebook."
P2 = "Beekeepers later compared those notebooks against hive weights, which showed that honey production fell sharply whenever the terraces stayed dry."
P3 = "A second survey asked neighbouring villages whether irrigation channels had been repaired, and most replied that volunteers had cleared the stones."
OUTPUT = "\n\n".join(["intro", P1, "$$\ny = x + 1\n$$", P2, "$$\nz = a * b\n$$", P3]) + "\n"
# Page 0: prose only. Page 1: P2 plus many math symbols. Page 2: P3 plus a few.
PAGES = [P1, P2 + " = + * / ^ _ < > = + * / ^ _ < >", P3 + " = + *"]

GOOD_ANSWER = {"formulas": [{"label": "(1)", "in_markdown": True, "same_as_page": True, "problem": "", "markdown_latex": "y = x + 1", "corrected_latex": ""}]}


def envelope(answer) -> bytes:
    return json.dumps({"response": json.dumps(answer)}).encode("utf-8")


def fake_renderer(_pdf, index, _dpi, directory):
    path = directory / f"page_{index + 1}.png"
    path.write_bytes(b"PNGDATA")
    return path


class TestConfig(unittest.TestCase):
    def test_shipped_config_has_every_key(self):
        self.assertEqual(set(load_vlmcheck_config()), set(CONFIG))

    def test_reasoning_is_off_and_context_is_bounded_in_the_shipped_config(self):
        config = load_vlmcheck_config()
        self.assertIs(config["think"], False)
        self.assertLess(config["num_ctx"], 262144)

    def test_missing_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"dpi": {"value": 1, "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(KeyError) as context:
                load_vlmcheck_config(path)
            self.assertIn("num_ctx", str(context.exception))

    def test_absent_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            load_vlmcheck_config(Path("absent.json"))

    # L4 of the 2026-10-15 review: page images and thesis text go to base_url.
    def _config_with_base_url(self, url):
        import tempfile

        data = {key: {"value": value, "provenance": "t"} for key, value in CONFIG.items()}
        data["base_url"]["value"] = url
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "c.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_a_loopback_base_url_is_accepted(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"):
            self.assertEqual(load_vlmcheck_config(self._config_with_base_url(url))["base_url"], url)

    def test_a_remote_base_url_is_refused_by_name(self):
        for url in ("http://192.0.2.10:11434", "https://ollama.example.org", "http://localhost.example.org:11434"):
            with self.assertRaises(ValueError) as context:
                load_vlmcheck_config(self._config_with_base_url(url))
            self.assertIn("base_url", str(context.exception))
            self.assertIn("loopback", str(context.exception))

    def test_the_default_caller_uses_no_proxy_and_no_redirect(self):
        import urllib.request
        from unittest import mock

        import pdf2md_vlmcheck as module

        seen = {}

        class FakeOpener:
            def open(self, request, timeout=None):
                class R:
                    def __enter__(s): return s
                    def __exit__(s, *a): return False
                    def read(s): return json.dumps({"response": "{}"}).encode()
                return R()

        def fake_build_opener(*handlers):
            seen["handlers"] = handlers
            return FakeOpener()

        with mock.patch.object(urllib.request, "build_opener", fake_build_opener):
            module.post_to_model(b"{}", {"base_url": "http://localhost:11434", "timeout_s": 1})
        kinds = [type(h).__name__ for h in seen["handlers"]]
        self.assertIn("ProxyHandler", kinds)
        proxy = next(h for h in seen["handlers"] if isinstance(h, urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        redirect = next(h for h in seen["handlers"] if isinstance(h, urllib.request.HTTPRedirectHandler))
        self.assertIsNone(redirect.redirect_request(None, None, 302, "", {}, "http://elsewhere.example.org"))

    def test_a_non_http_scheme_is_refused(self):
        with self.assertRaises(ValueError):
            load_vlmcheck_config(self._config_with_base_url("file://localhost/etc/passwd"))


class TestValidateAnswer(unittest.TestCase):
    def test_a_valid_answer_returns_its_formulas(self):
        self.assertEqual(validate_answer(GOOD_ANSWER), GOOD_ANSWER["formulas"])

    def test_an_empty_object_is_refused_not_accepted(self):
        # The earlier check read {} as a success.
        with self.assertRaises(VlmAnswerError):
            validate_answer({})

    def test_a_non_object_and_a_non_list_are_refused(self):
        for bad in ([], "text", None, {"formulas": "none"}):
            with self.assertRaises(VlmAnswerError):
                validate_answer(bad)

    def test_a_formula_with_a_missing_or_mistyped_key_is_refused(self):
        for bad in (
            {"formulas": [{"label": "a", "in_markdown": True, "same_as_page": True}]},
            {"formulas": [{"label": "a", "in_markdown": "yes", "same_as_page": True, "problem": ""}]},
            {"formulas": ["not an object"]},
        ):
            with self.assertRaises(VlmAnswerError):
                validate_answer(bad)

    def test_the_markdown_formula_and_its_correction_are_required(self):
        # They are what lets a correction be applied: without the verbatim
        # markdown formula there is nothing to find, without the correction
        # nothing to put in its place.
        for missing in ("markdown_latex", "corrected_latex"):
            formula = {"label": "a", "in_markdown": True, "same_as_page": False, "problem": "p", "markdown_latex": "x", "corrected_latex": "y"}
            del formula[missing]
            with self.assertRaises(VlmAnswerError) as context:
                validate_answer({"formulas": [formula]})
            self.assertIn(missing, str(context.exception))

    def test_an_empty_formula_list_is_structurally_valid(self):
        self.assertEqual(validate_answer({"formulas": []}), [])


class TestSelectPages(unittest.TestCase):
    def pick(self, count=2, texts=PAGES):
        return select_pages(texts, (0, 2), OUTPUT, count=count, math_symbol_chars=MATH_SYMBOLS, fidelity_config=FIDELITY)

    def test_the_richest_pages_in_math_symbols_are_chosen_in_page_order(self):
        self.assertEqual([choice.page_index for choice in self.pick(count=2)], [1, 2])

    def test_count_limits_the_choice_to_the_richest(self):
        self.assertEqual([choice.page_index for choice in self.pick(count=1)], [1])

    def test_a_page_whose_prose_is_not_in_the_output_is_skipped(self):
        unrelated = "Several families also described how the old wells recovered slowly after the first autumn storms, although none of them kept written records. = + * / ^ _ < > = + * / ^"
        texts = [P1, unrelated, P3 + " = +"]
        self.assertEqual([choice.page_index for choice in self.pick(count=1, texts=texts)], [2])

    def test_the_output_lines_hold_the_page_prose(self):
        (choice,) = self.pick(count=1)
        lines = OUTPUT.splitlines()
        self.assertTrue(lines[choice.output_lines[0] - 1].startswith("Beekeepers later"))


class TestExcerptAndPrompt(unittest.TestCase):
    def test_excerpt_takes_the_given_lines(self):
        self.assertEqual(build_excerpt("a\nb\nc\nd", (2, 3), margin=0, max_chars=100), ("b\nc", False))

    def test_the_margin_adds_lines_on_each_side_and_stops_at_the_file_edges(self):
        text = "\n".join("abcdefgh")
        self.assertEqual(build_excerpt(text, (4, 5), margin=1, max_chars=100), ("c\nd\ne\nf", False))
        self.assertEqual(build_excerpt(text, (1, 2), margin=5, max_chars=100)[0], "\n".join("abcdefg"))
        self.assertEqual(build_excerpt(text, (7, 8), margin=5, max_chars=100)[0], "\n".join("bcdefgh"))

    def test_an_equation_just_outside_the_located_lines_is_inside_the_margin(self):
        text = "\n".join(["prose before", "$$ y = x $$", "located prose", "$$ z = 1 $$", "prose after"])
        self.assertIn("$$ z = 1 $$", build_excerpt(text, (3, 3), margin=1, max_chars=200)[0])
        self.assertNotIn("$$ z = 1 $$", build_excerpt(text, (3, 3), margin=0, max_chars=200)[0])

    def test_a_long_excerpt_is_cut_and_says_so(self):
        excerpt, truncated = build_excerpt("x" * 50, (1, 1), margin=0, max_chars=10)
        self.assertEqual((len(excerpt), truncated), (10, True))

    def test_prompt_carries_the_excerpt_the_limit_and_the_json_instruction(self):
        prompt = build_prompt("MARKDOWN-HERE", max_formulas=5)
        self.assertIn("MARKDOWN-HERE", prompt)
        self.assertIn("at most 5", prompt)
        self.assertIn("JSON only", prompt)


class TestRequest(unittest.TestCase):
    def test_body_turns_reasoning_off_bounds_context_forces_schema_and_fixes_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "p.png"
            image.write_bytes(b"PNGDATA")
            body = json.loads(build_request_body(image, "PROMPT", model_tag="some-tag", config=CONFIG))
        self.assertEqual(body["model"], "some-tag")
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], answer_schema())
        self.assertEqual(body["options"], {"num_ctx": 4096, "temperature": 0, "seed": 0})
        self.assertEqual(len(body["images"]), 1)

    def test_the_caller_gets_the_generate_url_and_the_configured_timeout(self):
        seen = {}

        def caller(url, data, timeout):
            seen.update(url=url, timeout=timeout)
            return envelope(GOOD_ANSWER)

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "p.png"
            image.write_bytes(b"x")
            formulas = ask_model(image, "P", model_tag="t", config=CONFIG, caller=caller)
        self.assertEqual(seen, {"url": "http://localhost:11434/api/generate", "timeout": 7})
        self.assertEqual(formulas, GOOD_ANSWER["formulas"])

    def test_a_reply_that_is_not_the_envelope_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "p.png"
            image.write_bytes(b"x")
            for raw in (b"not json", b'{"no_response": 1}', json.dumps({"response": "not json"}).encode()):
                with self.assertRaises(VlmAnswerError):
                    ask_model(image, "P", model_tag="t", config=CONFIG, caller=lambda *_a, raw=raw: raw)


class TestCheckPage(unittest.TestCase):
    def check(self, caller):
        with tempfile.TemporaryDirectory() as tmp:
            return check_page("x.pdf", PageChoice(1, (4, 4)), OUTPUT, model_tag="t", config=CONFIG, scratch_dir=Path(tmp), renderer=fake_renderer, caller=caller)

    def test_a_clean_answer_is_ok_with_no_issue(self):
        row = self.check(lambda *_a: envelope(GOOD_ANSWER))
        self.assertEqual((row["status"], row["formulas"], row["issues"], row["page"]), (STATUS_OK, 1, [], 2))

    def test_a_missing_and_a_differing_formula_become_issues(self):
        answer = {"formulas": [
            {"label": "(2)", "in_markdown": False, "same_as_page": False, "problem": "not converted", "markdown_latex": "", "corrected_latex": ""},
            {"label": "(3)", "in_markdown": True, "same_as_page": False, "problem": "index i became j", "markdown_latex": "", "corrected_latex": ""},
        ]}
        row = self.check(lambda *_a: envelope(answer))
        self.assertEqual([issue["kind"] for issue in row["issues"]], [KIND_MISSING, KIND_DIFFERS])
        self.assertEqual(row["issues"][1]["detail"], "index i became j")

    def test_an_issue_carries_the_markdown_formula_and_the_proposed_correction(self):
        answer = {"formulas": [{"label": "(3.15)", "in_markdown": True, "same_as_page": False, "problem": "index j lost", "markdown_latex": "\\Delta w _ {c}", "corrected_latex": "\\Delta w _ {c j}"}]}
        row = self.check(lambda *_a: envelope(answer))
        self.assertEqual(row["issues"], [{"kind": KIND_DIFFERS, "label": "(3.15)", "detail": "index j lost", "markdown_latex": "\\Delta w _ {c}", "corrected_latex": "\\Delta w _ {c j}"}])

    def test_the_prompt_asks_for_the_verbatim_markdown_formula_and_the_correction(self):
        prompt = build_prompt("MD", max_formulas=3)
        self.assertIn("markdown_latex", prompt)
        self.assertIn("corrected_latex", prompt)
        self.assertIn("character for", prompt)

    def test_an_empty_formula_list_is_its_own_status_not_a_pass(self):
        row = self.check(lambda *_a: envelope({"formulas": []}))
        self.assertEqual(row["status"], STATUS_NO_FORMULA)

    def test_an_empty_object_reply_is_an_error_row(self):
        row = self.check(lambda *_a: envelope({}))
        self.assertEqual(row["status"], STATUS_ERROR)
        self.assertIn("formulas", row["error"])

    def test_a_timeout_is_an_error_row_not_an_exception(self):
        def caller(*_a):
            raise TimeoutError("timed out")

        row = self.check(caller)
        self.assertEqual((row["status"], row["error"]), (STATUS_ERROR, "timed out"))

    def test_a_render_failure_is_an_error_row(self):
        def renderer(*_a):
            raise RuntimeError("render fault")

        with tempfile.TemporaryDirectory() as tmp:
            row = check_page("x.pdf", PageChoice(1, (4, 4)), OUTPUT, model_tag="t", config=CONFIG, scratch_dir=Path(tmp), renderer=renderer, caller=lambda *_a: envelope(GOOD_ANSWER))
        self.assertEqual(row["status"], STATUS_ERROR)

    def test_the_excerpt_is_marked_when_it_was_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = check_page("x.pdf", PageChoice(1, (1, 9)), OUTPUT, model_tag="t", config={**CONFIG, "max_markdown_chars": 10}, scratch_dir=Path(tmp), renderer=fake_renderer, caller=lambda *_a: envelope(GOOD_ANSWER))
        self.assertIs(row["excerpt_truncated"], True)


class TestRun(unittest.TestCase):
    def run_all(self, caller, ranges=None):
        with tempfile.TemporaryDirectory() as tmp:
            return run_vlm_fidelity(
                "x.pdf", {4: ("chapitre4", OUTPUT), 5: ("chapitre5", OUTPUT)}, ranges if ranges is not None else {4: (0, 2)}, PAGES,
                model_tag="t", config=CONFIG, math_symbol_chars=MATH_SYMBOLS, fidelity_config=FIDELITY, scratch_dir=Path(tmp), renderer=fake_renderer, caller=caller,
            )

    def test_pages_are_checked_and_a_chapter_without_a_page_range_is_listed_not_skipped(self):
        report = self.run_all(lambda *_a: envelope(GOOD_ANSWER))
        self.assertEqual([row["page"] for row in report["chapters"]["4"]], [2, 3])
        self.assertEqual(report["unchecked_chapters"], {"5": "chapter heading not found on any PDF page"})
        self.assertEqual((report["issue_count"], report["error_count"]), (0, 0))

    def test_issues_and_errors_are_counted_across_pages(self):
        answers = iter([envelope({"formulas": [{"label": "a", "in_markdown": False, "same_as_page": False, "problem": "lost", "markdown_latex": "", "corrected_latex": ""}]}), envelope({})])
        report = self.run_all(lambda *_a: next(answers))
        self.assertEqual((report["issue_count"], report["error_count"]), (1, 1))

    def test_a_chapter_whose_pages_cannot_be_located_is_listed_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_vlm_fidelity(
                "x.pdf", {4: ("chapitre4", "nothing alike here at all")}, {4: (0, 2)}, PAGES,
                model_tag="t", config=CONFIG, math_symbol_chars=MATH_SYMBOLS, fidelity_config=FIDELITY, scratch_dir=Path(tmp), renderer=fake_renderer, caller=lambda *_a: envelope(GOOD_ANSWER),
            )
        self.assertEqual(report["unchecked_chapters"], {"4": "no page of the chapter could be located in the output"})

    def test_render_lists_each_page_and_each_unchecked_chapter(self):
        rendered = render_vlm_md(self.run_all(lambda *_a: envelope({"formulas": [{"label": "(7)", "in_markdown": True, "same_as_page": False, "problem": "sign flipped", "markdown_latex": "", "corrected_latex": ""}]})))
        self.assertIn("formula_differs: (7) - sign flipped", rendered)
        self.assertIn("| 5 | - | - | unchecked |", rendered)


if __name__ == "__main__":
    unittest.main()
