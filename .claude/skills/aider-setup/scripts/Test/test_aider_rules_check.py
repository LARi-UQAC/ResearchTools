"""
Offline tests of aider-rules-check.py (2026-11-11, R15, R20, R21, R34).

The token counter is injected as a word count, so no package is needed. One case runs the shipped
rules.md through the real counter and is skipped where tiktoken is absent.
"""
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rules_check", SKILL / "scripts" / "aider-rules-check.py")
rules_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules_check)


def words(text: str) -> int:
    return len(text.split())


def file_of(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


GOOD = "# Coding rules\n\nThese rules bind.\n\n---\n\n**R0 - one.** Say it once.\n\n**R1 - two.** Say it twice now.\n"


class Check(unittest.TestCase):

    def test_a_valid_file_has_no_problem_and_a_summary(self):
        problems, summary = rules_check.check(GOOD, 20, words)
        self.assertEqual([], problems)
        self.assertEqual((2, 0, 1, 1), (summary["rules"], summary["first"], summary["last"], summary["longest"]))

    def test_a_file_with_no_rule_is_refused(self):
        problems, _ = rules_check.check("# Coding rules\n\nNothing here.\n", 20, words)
        self.assertEqual(1, len(problems))
        self.assertIn("no rule found", problems[0])

    def test_a_number_defined_twice_is_named(self):
        text = GOOD + "\n**R1 - again.** Twice.\n"
        problems, _ = rules_check.check(text, 20, words)
        self.assertIn("R1 is defined twice", problems)

    def test_a_gap_in_the_numbering_is_named(self):
        text = "**R0 - a.** x\n\n**R2 - b.** y\n"
        problems, _ = rules_check.check(text, 20, words)
        self.assertTrue(any("missing: R1" in p for p in problems))

    def test_numbering_must_start_at_zero(self):
        problems, _ = rules_check.check("**R1 - a.** x\n", 20, words)
        self.assertTrue(any("missing: R0" in p for p in problems))

    def test_a_far_off_number_does_not_drown_the_report(self):
        problems, _ = rules_check.check("**R0 - a.** x\n\n**R99 - b.** y\n", 20, words)
        text = " ".join(problems)
        self.assertIn("and 90 more", text)
        self.assertLess(len(text), 400)

    def test_a_rule_over_the_cap_is_refused_with_its_count_and_never_cut(self):
        long_rule = "**R1 - long.** " + "word " * 30 + "\n"
        problems, _ = rules_check.check("**R0 - a.** x\n\n" + long_rule, 10, words)
        self.assertTrue(any(p.startswith("R1 is 33 tokens, over the cap of 10") for p in problems))

    def test_a_rule_exactly_at_the_cap_passes(self):
        problems, _ = rules_check.check("**R0 - a b c.**\n", 5, words)
        self.assertEqual([], problems)


class Main(unittest.TestCase):

    def run_main(self, path, cap="20", counter=words):
        original = rules_check.load_counter
        rules_check.load_counter = lambda: counter
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = rules_check.main([str(path), "--max-rule-tokens", cap])
        finally:
            rules_check.load_counter = original
        return code, out.getvalue(), err.getvalue()

    def test_a_valid_file_exits_0_with_one_summary_line(self):
        code, out, _ = self.run_main(file_of(GOOD))
        self.assertEqual(0, code)
        self.assertIn("2 rules R0-R1, longest R1 at 7 of 20 tokens", out)

    def test_an_invalid_file_exits_2_and_names_the_rule(self):
        code, _, err = self.run_main(file_of(GOOD), cap="3")
        self.assertEqual(2, code)
        self.assertIn("REFUSED", err)
        self.assertIn("R1 is 7 tokens", err)

    def test_a_missing_file_exits_2(self):
        code, _, err = self.run_main(Path(tempfile.gettempdir()) / "no-such-rules-file.md")
        self.assertEqual(2, code)
        self.assertIn("does not exist", err)

    def test_no_token_counter_exits_1_and_says_why(self):
        code, _, err = self.run_main(file_of(GOOD), counter=None)
        self.assertEqual(1, code)
        self.assertIn("tiktoken", err)


class Shipped(unittest.TestCase):

    def test_the_shipped_rules_file_is_valid_under_the_shipped_cap(self):
        counter = rules_check.load_counter()
        if counter is None:
            self.skipTest("tiktoken is not installed in this interpreter")
        import json
        budget = json.loads((SKILL / "config" / "context-budget.json").read_text(encoding="utf-8-sig"))
        cap = budget["ceilings"]["rule_body_tokens"]
        problems, summary = rules_check.check(
            (SKILL / "config" / "rules.md").read_text(encoding="utf-8"), cap, counter)
        self.assertEqual([], problems)
        self.assertEqual(0, summary["first"])


if __name__ == "__main__":
    unittest.main()
