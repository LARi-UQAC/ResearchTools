"""Offline tests for pdf2md_vlmfix. No model, PDF render or network is used: the
renderer and the HTTP caller are injected (R20, R21) and every text is
fictitious (R34).

What is proven is what a model cannot be trusted with: which of its proposals
are allowed into the text (syntax, length, verbatim and unique quote), that an
equation lands where the model said and is marked as a model transcription,
that a correction the model still reports wrong is undone, and that the loop
stops on the three conditions it promises. The model's own judgement is faked."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdf2md_fidelity as fidelity
import pdf2md_vlmcheck as vlmcheck
import pdf2md_vlmfix as fix

FIDELITY = {
    "min_prose_tokens": 12,
    "min_token_letters": 3,
    "min_prose_ratio": 0.6,
    "ngram_chars": 12,
    "paragraph_missing_below": 0.5,
    "locate_chunk_words": 40,
    "locate_secondary_vote_share": 0.5,
    "locate_max_span_paragraphs": 12,
    "duplicate_vote_tolerance": 0.9,
    "out_of_order_min_displacement": 3,
    "running_header_min_repeats": 3,
    "running_header_min_letters": 15,
    "caption_sentence_words": ["presents", "illustrates", "shows", "and"],
    "figure_image_window_lines": 30,
    "citation_min_letters": 2,
    "title_match_ratio": 0.8,
    "pdf_noise_markers": ["<br>", "----- Start of picture text -----"],
    "html_residue_pattern": r"<(?:span|small|div)\b",
    "unnumbered_heading_severity": "warning",
}
VLM = {
    "base_url": "http://localhost:11434",
    "timeout_s": 7,
    "dpi": 150,
    "num_ctx": 4096,
    "think": False,
    "temperature": 0,
    "seed": 0,
    "pages_per_chapter": 2,
    "excerpt_margin_lines": 1,
    "max_markdown_chars": 4000,
    "max_formulas": 5,
}
CONFIG = {
    "max_rounds": 3,
    "target_remaining_issues": 0,
    "gap_pages_tried": 2,
    "gap_margin_lines": 200,
    "candidate_paragraph_chars": 40,
    "max_candidates": 40,
    "max_length_ratio": 2.0,
    "max_latex_chars": 400,
    "verify_corrections": True,
    "changes_file": "vlm_changes.json",
}

P1 = "The orchard keepers measured rainfall across every terrace during the long dry season and recorded each reading in a shared notebook."
P2 = "Beekeepers later compared those notebooks against hive weights, which showed that honey production fell sharply whenever the terraces stayed dry."
P3 = "A second survey asked neighbouring villages whether irrigation channels had been repaired, and most replied that volunteers had cleared the stones."
P4 = "Finally the committee summarised its findings in a short report, recommending that the notebooks be digitised before the next harvest begins."
P5 = "Several families also described how the old wells recovered slowly after the first autumn storms, although none of them kept written records."


def eq(n, body=None):
    return f"$$\n{body or f'x _ {{{n}}} = y _ {{{n}}}'}, \\tag {{4.{n}}}\n$$"


TEXT = "\n\n".join([P1, eq(1), P2, eq(2), P3, eq(3), P4, eq(4), P5, eq(6)]) + "\n"
PAGES = [P1 + " " + P2 + " " + P3, P4 + " " + P5]
PAGE_RANGE = (0, 1)


def envelope(answer) -> bytes:
    return json.dumps({"response": json.dumps(answer)}).encode("utf-8")


def fake_renderer(_pdf, index, _dpi, directory):
    path = directory / f"page_{index + 1}.png"
    path.write_bytes(b"PNG")
    return path


class FakeModel:
    """Stands in for the vision model. `equation` and `check` are functions
    that build the answer; every call is recorded."""

    def __init__(self, equation=None, check=None):
        self.equation, self.check, self.calls = equation, check, []

    def __call__(self, _url, data, _timeout):
        body = json.loads(data)
        schema = body["format"]
        if "formulas" in schema["properties"]:
            self.calls.append("check")
            return envelope(self.check(body["prompt"]) if self.check else {"formulas": []})
        self.calls.append("equation")
        return envelope(self.equation(body["prompt"]))


def index_of(prompt, start):
    for line in prompt.splitlines():
        head, _, rest = line.partition(": ")
        if head.isdigit() and rest.startswith(start):
            return int(head)
    raise AssertionError(f"no candidate starts with {start!r} in:\n{prompt}")


def shown(prompt):
    """The markdown excerpt of a formula-check prompt: all a real model sees of the text."""
    return prompt.split("Markdown:", 1)[1]


def formula(label, markdown, corrected, same=False, present=True, problem="p"):
    return {"label": label, "in_markdown": present, "same_as_page": same, "problem": problem, "markdown_latex": markdown, "corrected_latex": corrected}


class TestConfig(unittest.TestCase):
    def test_shipped_config_has_every_key(self):
        self.assertEqual(set(fix.load_vlmfix_config()), set(CONFIG))

    def test_a_missing_key_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"max_rounds": {"value": 1, "provenance": "t"}}), encoding="utf-8")
            with self.assertRaises(KeyError) as context:
                fix.load_vlmfix_config(path)
            self.assertIn("target_remaining_issues", str(context.exception))

    def test_an_absent_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            fix.load_vlmfix_config(Path("absent.json"))


class TestLatexIsSane(unittest.TestCase):
    def test_ordinary_formulas_pass(self):
        for latex in (r"x ^ {i} (k + 1) = \sum_ {j = 1} ^ {n} a _ {j}", r"\left[ \begin{array}{c} a \\ b \end{array} \right]", r"\{ 1 , 2 \}"):
            self.assertTrue(fix.latex_is_sane(latex, CONFIG), latex)

    def test_broken_or_runaway_formulas_are_refused(self):
        for latex in ("", "   ", "x ^ {i", "x }", r"\left( a", r"\begin{array} a", "a $ b", "x" * 401):
            self.assertFalse(fix.latex_is_sane(latex, CONFIG), latex)


class TestApplyFormulaCorrections(unittest.TestCase):
    TEXT = "before $$ \\Delta w _ {c} $$ middle $$ y = z $$ after"

    def apply(self, before, after, text=None):
        return fix.apply_formula_corrections(text or self.TEXT, [{"kind": "formula_differs", "label": "(3.15)", "detail": "d", "markdown_latex": before, "corrected_latex": after}], CONFIG)

    def test_a_unique_verbatim_formula_is_replaced(self):
        new, applied, skipped = self.apply(r"\Delta w _ {c}", r"\Delta w _ {c j}")
        self.assertEqual(new, self.TEXT.replace(r"\Delta w _ {c}", r"\Delta w _ {c j}"))
        self.assertEqual((applied, skipped), ([{"label": "(3.15)", "before": r"\Delta w _ {c}", "after": r"\Delta w _ {c j}"}], []))

    def test_every_refusal_leaves_the_text_untouched_and_says_why(self):
        cases = {
            "not in the text verbatim": (r"\Delta w _ {d}", r"\Delta w _ {d j}", None),
            "occurs more than once": ("y", "y2", "y and y"),
            "correction equals the formula": (r"y = z", r"y = z", None),
            "fails the syntax check": (r"y = z", r"y = {z", None),
            "much longer or shorter": (r"y = z", r"y = z + " + "a + " * 10 + "b", None),
            "no formula or no correction": ("", "x", None),
        }
        for reason, (before, after, text) in cases.items():
            new, applied, skipped = self.apply(before, after, text or self.TEXT)
            self.assertEqual(new, text or self.TEXT, reason)
            self.assertEqual(applied, [], reason)
            self.assertIn(reason.split()[0], skipped[0]["reason"], reason)


class TestEquationAnswer(unittest.TestCase):
    GOOD = {"found": True, "latex": "a = b", "after_paragraph": 2}

    def test_a_valid_answer_passes_and_minus_one_means_cannot_tell(self):
        self.assertEqual(fix.validate_equation_answer(self.GOOD, 5), self.GOOD)
        self.assertEqual(fix.validate_equation_answer({**self.GOOD, "after_paragraph": -1}, 5)["after_paragraph"], -1)

    def test_a_missing_key_a_wrong_type_or_an_index_outside_the_list_is_refused(self):
        for bad in ({}, {**self.GOOD, "latex": 3}, {**self.GOOD, "found": "yes"}, {**self.GOOD, "after_paragraph": True}, {**self.GOOD, "after_paragraph": 5}, {**self.GOOD, "after_paragraph": -2}, [], None):
            with self.assertRaises(vlmcheck.VlmAnswerError):
                fix.validate_equation_answer(bad, 5)

    def test_the_prompt_lists_every_candidate_and_names_the_equation(self):
        prompt = fix.build_equation_prompt("4.5", ["first one", "second one"])
        self.assertIn("(4.5)", prompt)
        self.assertIn("0: first one", prompt)
        self.assertIn("1: second one", prompt)
        self.assertIn("IMMEDIATELY BEFORE", prompt)

    def test_the_request_carries_the_equation_schema_not_the_formula_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "p.png"
            image.write_bytes(b"x")
            seen = {}

            def caller(_url, data, _timeout):
                seen["format"] = json.loads(data)["format"]
                return envelope(TestEquationAnswer.GOOD)

            fix.ask_equation(image, "4.5", ["a", "b", "c"], model_tag="t", vlm_config=VLM, caller=caller)
        self.assertEqual(seen["format"], fix.equation_schema())


class TestInsertEquation(unittest.TestCase):
    def test_the_equation_goes_after_the_given_line_marked_as_a_transcription_and_numbered(self):
        text = "line one\nline two\n\nline four\n"
        new = fix.insert_equation(text, 2, "a = b", "4.5", page=112)
        lines = new.split("\n")
        self.assertEqual(lines[:2], ["line one", "line two"])
        self.assertIn("transcribed by a vision model from PDF page 112", lines[3])
        self.assertEqual(lines[4:7], ["$$", "a = b \\tag {4.5}", "$$"])
        self.assertEqual(lines[-3:], ["", "line four", ""])

    def test_the_comment_is_not_chapter_content_for_the_text_comparison(self):
        new = fix.insert_equation("alpha beta gamma delta\n", 1, "a = b", "4.5", page=3)
        self.assertNotIn("transcribed", fidelity.strip_math_and_images(new))

    def test_inserting_the_missing_number_closes_the_gap(self):
        self.assertEqual(fidelity.equation_gaps(TEXT), [(4, 5)])
        new = fix.insert_equation(TEXT, TEXT.split("\n").index(P5) + 1, "a = b", "4.5", page=2)
        self.assertEqual(fidelity.equation_gaps(new), [])


class TestReplaceOrphanNumber(unittest.TestCase):
    TEXT = "The i-th row of the matrix is\n\n(4.5)\n\nThis is the weighted sum.\n"

    def test_the_lone_number_line_becomes_the_equation(self):
        new = fix.replace_orphan_number(self.TEXT, "4.5", "a = b = c", page=112)
        self.assertIn("a = b = c \\tag {4.5}", new)
        self.assertIn("transcribed by a vision model from PDF page 112", new)
        self.assertNotIn("\n(4.5)\n", new)
        self.assertIn("The i-th row of the matrix is", new)
        self.assertIn("This is the weighted sum.", new)

    def test_no_such_line_gives_none(self):
        self.assertIsNone(fix.replace_orphan_number("alpha beta\n", "4.5", "a = b", page=1))

    def test_a_number_inside_a_sentence_is_not_an_orphan(self):
        self.assertIsNone(fix.replace_orphan_number("as shown in (4.5) above\n", "4.5", "a = b", page=1))

    def test_two_orphans_are_ambiguous_and_left_alone(self):
        self.assertIsNone(fix.replace_orphan_number(self.TEXT + "\n(4.5)\n", "4.5", "a = b", page=1))


class TestGapCandidates(unittest.TestCase):
    def test_the_nearest_paragraphs_are_kept_in_document_order_and_the_cap_is_honoured(self):
        text = "\n\n".join(f"paragraph number {n} " + "word " * 5 for n in range(30)) + "\n"
        chosen = fix.gap_candidates(text, (30, 34), [], {**CONFIG, "gap_margin_lines": 100, "max_candidates": 5})
        self.assertEqual(len(chosen), 5)
        self.assertEqual([p.line for p in chosen], sorted(p.line for p in chosen))
        self.assertTrue(all(abs(p.line - 32) <= 6 for p in chosen))

    def test_a_located_page_adds_paragraphs_far_from_the_gap(self):
        text = "\n\n".join(f"paragraph number {n} " + "word " * 5 for n in range(60)) + "\n"
        near = fix.gap_candidates(text, (10, 12), [], {**CONFIG, "gap_margin_lines": 5})
        added = fix.gap_candidates(text, (10, 12), [(100, 106)], {**CONFIG, "gap_margin_lines": 5})
        self.assertTrue(set(p.line for p in added) > set(p.line for p in near))


class TestFixEquationGaps(unittest.TestCase):
    def run_fix(self, model, text=TEXT):
        with tempfile.TemporaryDirectory() as tmp:
            return fix.fix_equation_gaps(
                4, text, pdf_path="x.pdf", page_texts=PAGES, page_range=PAGE_RANGE, model_tag="t", vlm_config=VLM, fidelity_config=FIDELITY,
                config=CONFIG, scratch_dir=Path(tmp), renderer=fake_renderer, caller=model,
            )

    def test_the_lost_equation_is_inserted_after_the_paragraph_the_model_names_and_the_gap_closes(self):
        model = FakeModel(equation=lambda prompt: {"found": True, "latex": "a = b", "after_paragraph": index_of(prompt, "Several families")})
        new, records = self.run_fix(model)
        self.assertEqual([(r["kind"], r["label"]) for r in records], [(fix.KIND_EQUATION_INSERTED, "4.5")])
        self.assertEqual(fidelity.equation_gaps(new), [])
        self.assertIn(P5 + "\n\n<!-- pdf2md: equation (4.5)", new)
        self.assertEqual(records[0]["latex"], "a = b")

    def test_a_text_without_a_gap_is_returned_unchanged_and_the_model_is_never_asked(self):
        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        model = FakeModel(equation=lambda _p: self.fail("asked"))
        self.assertEqual(self.run_fix(model, complete), (complete, []))
        self.assertEqual(model.calls, [])

    def test_every_way_the_model_can_fail_leaves_the_text_untouched_and_names_the_reason(self):
        scenarios = {
            "does not see": lambda _p: {"found": False, "latex": "", "after_paragraph": -1},
            "syntax check": lambda _p: {"found": True, "latex": "a = {b", "after_paragraph": 0},
            "could not say which paragraph": lambda _p: {"found": True, "latex": "a = b", "after_paragraph": -1},
        }
        for reason, answer in scenarios.items():
            new, records = self.run_fix(FakeModel(equation=answer))
            self.assertEqual(new, TEXT, reason)
            self.assertEqual((records[0]["kind"], records[0]["label"]), ("needs_review", "4.5"))
            self.assertIn(reason, records[0]["reason"])

    def test_a_timeout_and_an_invalid_answer_are_needs_review_not_exceptions(self):
        def timeout(*_a):
            raise TimeoutError("timed out")

        for caller in (timeout, lambda *_a: envelope({"found": "maybe"})):
            new, records = self.run_fix(caller)
            self.assertEqual((new, records[0]["kind"]), (TEXT, "needs_review"))

    def test_a_failed_transcription_keeps_the_proposed_formula_for_the_person(self):
        new, records = self.run_fix(FakeModel(equation=lambda _p: {"found": True, "latex": "a = {b", "after_paragraph": 0}))
        self.assertEqual(records[0]["proposed"], "a = {b")


class TestRunCorrectionLoop(unittest.TestCase):
    PDF = {4: ("", "\n\n".join([P1, P2, P3, P4, P5]))}

    def loop(self, model, text=TEXT, config=None, vlm=None, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            return fix.run_correction_loop(
                pdf_path="x.pdf", chapters={4: ("chapitre4", text)}, pdf_chapters=self.PDF, chapter_ranges={4: PAGE_RANGE}, page_texts=PAGES,
                model_tag="t", vlm_config=vlm or VLM, fidelity_config=FIDELITY, config=config or CONFIG, math_symbol_chars="=+*/^_<>", scratch_dir=Path(tmp),
                renderer=fake_renderer, caller=model, **extra,
            )

    def clean_check(self, _prompt):
        return {"formulas": [formula("(1)", "x _ {1} = y _ {1}", "", same=True)]}

    def test_a_lost_equation_is_recovered_and_the_loop_stops_on_the_target(self):
        model = FakeModel(equation=lambda prompt: {"found": True, "latex": "a = b", "after_paragraph": index_of(prompt, "Several families")}, check=self.clean_check)
        result = self.loop(model)
        self.assertEqual((result["stopped"], result["remaining"]), ("target reached", 0))
        self.assertEqual([c["kind"] for c in result["changes"]], [fix.KIND_EQUATION_INSERTED])
        self.assertEqual(fidelity.equation_gaps(result["texts"][4]), [])
        self.assertEqual(len(result["history"]), 1)

    def test_equations_only_recovers_the_equation_and_never_checks_or_rewrites_a_formula(self):
        model = FakeModel(equation=lambda prompt: {"found": True, "latex": "a = b", "after_paragraph": index_of(prompt, "Several families")}, check=self.clean_check)
        result = self.loop(model, equations_only=True)
        self.assertEqual([c["kind"] for c in result["changes"]], [fix.KIND_EQUATION_INSERTED])
        self.assertEqual(model.calls.count("check"), 0)
        self.assertEqual(result["stopped"], "target reached")

    def test_equations_only_leaves_a_wrong_formula_alone(self):
        wrong = "x _ {1} = y _ {1}"
        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        model = FakeModel(check=lambda _p: {"formulas": [formula("(1)", wrong, "x _ {1} = z _ {1}")]})
        result = self.loop(model, complete, equations_only=True)
        self.assertEqual(result["texts"][4], complete)
        self.assertEqual(result["changes"], [])
        self.assertEqual(model.calls.count("check"), 0)

    def test_a_wrong_formula_is_corrected_and_the_correction_is_verified_on_the_page(self):
        wrong = "x _ {1} = y _ {1}"

        def check(prompt):
            excerpt = shown(prompt)
            if wrong in excerpt:
                return {"formulas": [formula("(1)", wrong, "x _ {1} = z _ {1}")]}
            if "x _ {1} = z _ {1}" in excerpt:
                return {"formulas": [formula("(1)", "x _ {1} = z _ {1}", "", same=True)]}
            return {"formulas": []}

        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        model = FakeModel(check=check)
        result = self.loop(model, complete)
        self.assertEqual((result["stopped"], result["remaining"]), ("target reached", 0))
        self.assertIn("x _ {1} = z _ {1}", result["texts"][4])
        self.assertEqual([c["kind"] for c in result["changes"]], [fix.KIND_FORMULA_CORRECTED])
        # two pages checked, then the one page that was corrected shown again
        self.assertEqual(model.calls.count("check"), 3)

    def test_a_correction_the_model_still_reports_wrong_is_undone(self):
        def check(prompt):
            excerpt = shown(prompt)
            if "x _ {1} = y _ {1}" in excerpt:
                return {"formulas": [formula("(1)", "x _ {1} = y _ {1}", "x _ {1} = z _ {1}")]}
            if "x _ {1} = z _ {1}" in excerpt:
                return {"formulas": [formula("(1)", "x _ {1} = z _ {1}", "x _ {1} = w _ {1}")]}
            return {"formulas": []}

        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        result = self.loop(FakeModel(check=check), complete)
        self.assertEqual(result["texts"][4], complete)
        self.assertEqual(result["changes"], [])
        self.assertIn("still reports", result["needs_review"][0]["reason"])

    def test_a_missing_formula_with_no_numbering_gap_is_left_for_a_person_and_the_loop_stops(self):
        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        model = FakeModel(check=lambda _p: {"formulas": [formula("(9)", "", "q = r", present=False)]})
        result = self.loop(model, complete, vlm={**VLM, "pages_per_chapter": 1})
        self.assertEqual((result["stopped"], result["remaining"], result["texts"][4]), ("no change", 1, complete))

    def test_the_loop_never_runs_more_rounds_than_the_limit(self):
        # A gap is fixed (a change is made) but a formula issue stays: the
        # first round cannot reach the target, and one round is all that is allowed.
        model = FakeModel(
            equation=lambda prompt: {"found": True, "latex": "a = b", "after_paragraph": index_of(prompt, "Several families")},
            check=lambda _p: {"formulas": [formula("(9)", "", "q = r", present=False)]},
        )
        result = self.loop(model, config={**CONFIG, "max_rounds": 1})
        self.assertEqual((result["stopped"], len(result["history"])), ("round limit", 1))

    def test_a_remainder_that_did_not_fall_stops_the_loop_as_no_progress(self):
        calls = {"n": 0}

        def check(_prompt):
            calls["n"] += 1
            return {"formulas": [formula("(9)", "", "q = r", present=False)]}

        text = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        # round 1 makes a change through a correction of another formula, round 2 has none
        def check2(prompt):
            current = prompt.split("Markdown:", 1)[1]
            out = [formula("(9)", "", "q = r", present=False)]
            if "y _ {2}" in current:
                out.append(formula("(2)", "x _ {2} = y _ {2}", "x _ {2} = z _ {2}"))
            return {"formulas": out}

        result = self.loop(FakeModel(check=check2), text, config={**CONFIG, "verify_corrections": False})
        self.assertIn(result["stopped"], ("no change", "no progress"))
        self.assertGreaterEqual(result["remaining"], 1)

    def test_progress_is_handed_to_the_caller_after_every_round(self):
        seen = []
        model = FakeModel(equation=lambda prompt: {"found": True, "latex": "a = b", "after_paragraph": index_of(prompt, "Several families")}, check=self.clean_check)
        self.loop(model, on_round=lambda number, texts, changes: seen.append((number, sorted(texts), len(changes))))
        self.assertEqual(seen, [(1, [4], 1)])

    def test_all_pages_asks_the_check_for_every_located_page(self):
        model = FakeModel(check=self.clean_check)
        complete = TEXT.replace(eq(6), eq(5) + "\n\n" + eq(6))
        self.loop(model, complete, all_pages=True)
        self.assertEqual(model.calls.count("check"), 2)


class TestChangesFile(unittest.TestCase):
    def test_changes_are_merged_across_runs_without_duplicates_and_review_items_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "assets" / "vlm_changes.json"
            first = {"chapter": 4, "kind": fix.KIND_EQUATION_INSERTED, "label": "4.5", "page": 112}
            fix._write_changes_file(path, [first], [{"chapter": 3, "label": "x"}])
            fix._write_changes_file(path, [first, {"chapter": 3, "kind": fix.KIND_FORMULA_CORRECTED, "label": "(3.15)", "page": 80}], [])
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([c["label"] for c in data["changes"]], ["4.5", "(3.15)"])
        self.assertEqual(data["needs_review"], [])


class TestCommandLine(unittest.TestCase):
    def test_a_missing_model_tag_is_refused_with_exit_2_before_anything_is_read(self):
        import io
        from contextlib import redirect_stderr

        with redirect_stderr(io.StringIO()) as err:
            code = fix._main(["x.pdf", "-o", "nowhere"])
        self.assertEqual(code, 2)
        self.assertIn("--model", err.getvalue())

    def test_an_existing_backup_makes_a_writing_run_refuse(self):
        import io
        from contextlib import redirect_stderr

        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "pdf2md-backup-vlm"
            backup.mkdir()
            (backup / "chapitre4.md").write_text("an earlier original", encoding="utf-8")
            with redirect_stderr(io.StringIO()) as err:
                code = fix._main(["x.pdf", "-o", tmp, "--model", "t", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("earlier run", err.getvalue())


if __name__ == "__main__":
    unittest.main()
