"""
Offline tests of plan_clean.py: the mechanical cleaning of a spec or a plan for the local writer model.
Fixtures are fictitious text written to a temporary folder. No model, no network.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plan_clean  # noqa: E402

PLAN = """---
executor: local-coder
tier: standard
---

# Plan 3 - Something

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every file.

**Spec:** `spec.md` D6, D14, "Data shapes" (the record); design section 7.

## Global Constraints

Every output path is resolved inside the folder (R24). Pure functions (R21, R6). Local only (D2).
"""


class CleanTextTests(unittest.TestCase):
    """Substitutions, front matter and what is left over."""

    def setUp(self):
        self.rules = plan_clean.load_rules(plan_clean.RULES_FILE)

    def test_front_matter_is_removed(self):
        cleaned, _, _ = plan_clean.clean_text(PLAN, self.rules)
        self.assertNotIn("executor", cleaned)
        self.assertTrue(cleaned.startswith("# Plan 3"))

    def test_rule_and_decision_numbers_in_parentheses_are_removed(self):
        cleaned, changes, hits = plan_clean.clean_text(PLAN, self.rules)
        self.assertIn("resolved inside the folder.", cleaned)
        self.assertIn("Pure functions.", cleaned)
        self.assertIn("Local only.", cleaned)
        self.assertEqual(hits, [])
        self.assertTrue(changes)

    def test_spec_line_loses_decision_numbers_and_design_sections_but_keeps_named_sections(self):
        cleaned, _, _ = plan_clean.clean_text(PLAN, self.rules)
        spec_line = [line for line in cleaned.split("\n") if line.startswith("**Spec:**")][0]
        self.assertEqual(spec_line, '**Spec:** `spec.md` "Design choices", "Data shapes" (the record).')

    def test_reader_label_and_runner_sentence_are_neutral(self):
        cleaned, _, _ = plan_clean.clean_text(PLAN, self.rules)
        self.assertIn("**How to answer:** Return every file.", cleaned)

    def test_a_step_never_tells_the_model_to_run_a_file(self):
        text = ("- [ ] Step 1: write the tests, run the file, they fail (module absent).\n"
                "- [ ] Step 2: write the module, run the file, every test passes.\n"
                "- [ ] Step 3: write the helper, run the file, every test passes.\n")
        cleaned, _, _ = plan_clean.clean_text(text, self.rules)
        self.assertNotIn("run the file", cleaned)
        self.assertIn("write the tests; they must fail while the module is absent", cleaned)
        self.assertIn("write the module so that every test passes", cleaned)
        self.assertIn("write the helper so that every test passes", cleaned)

    def test_a_sentence_that_is_not_a_run_instruction_is_left_alone(self):
        text = "- [ ] Step 1: write the tests and keep the file small.\n"
        cleaned, _, _ = plan_clean.clean_text(text, self.rules)
        self.assertEqual(cleaned, text)

    def test_a_second_pass_changes_nothing(self):
        once, _, _ = plan_clean.clean_text(PLAN, self.rules)
        twice, changes, _ = plan_clean.clean_text(once, self.rules)
        self.assertEqual(once, twice)
        self.assertEqual(changes, {})

    def test_what_cannot_be_fixed_by_pattern_is_reported_with_its_line(self):
        text = "Fine line.\nThe owner decided this on 2026-11-05.\nA report id R01 and thesis-proposal-auditor stay.\n"
        _, _, hits = plan_clean.clean_text(text, self.rules)
        self.assertEqual([number for number, _ in hits], [2])

    def test_no_cloud_fallback_is_a_constraint_not_a_hit_but_the_cloud_is(self):
        _, _, ok = plan_clean.clean_text("No cloud fallback is allowed.\n", self.rules)
        _, _, bad = plan_clean.clean_text("The cloud installs it.\n", self.rules)
        self.assertEqual(ok, [])
        self.assertEqual(len(bad), 1)


class CommandTests(unittest.TestCase):
    """The command line: dry run, write, exit codes, refusals."""

    def make_project(self, directory: str) -> Path:
        folder = Path(directory)
        (folder / "spec.md").write_text("# Spec\n\nApproved by the owner.\n", encoding="utf-8")
        (folder / "plan1.md").write_text(PLAN, encoding="utf-8")
        return folder

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make_project(tmp)
            code = plan_clean.main([str(folder)])
            self.assertEqual((folder / "plan1.md").read_text(encoding="utf-8"), PLAN)
            self.assertEqual(code, plan_clean.EXIT_HITS)

    def test_write_cleans_the_plan_and_leaves_a_hand_fix_exit_code_for_the_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make_project(tmp)
            code = plan_clean.main([str(folder), "--write"])
            self.assertNotIn("R24", (folder / "plan1.md").read_text(encoding="utf-8"))
            self.assertEqual(code, plan_clean.EXIT_HITS)

    def test_clean_files_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.make_project(tmp)
            (folder / "spec.md").write_text("# Spec\n\nBuild a thing.\n", encoding="utf-8")
            plan_clean.main([str(folder), "--write"])
            self.assertEqual(plan_clean.main([str(folder)]), plan_clean.EXIT_CLEAN)

    def test_a_missing_target_is_refused(self):
        self.assertEqual(plan_clean.main(["no-such-folder-anywhere"]), plan_clean.EXIT_REFUSED)

    def test_a_rules_file_without_a_key_is_refused_naming_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "rules.json"
            bad.write_text(json.dumps({"strip_front_matter": True, "substitutions": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "detect"):
                plan_clean.load_rules(bad)

    def test_the_shipped_rules_file_loads_and_every_substitution_has_a_name(self):
        rules = plan_clean.load_rules(plan_clean.RULES_FILE)
        self.assertTrue(rules["substitutions"])
        self.assertTrue(all(sub["name"] for sub in rules["substitutions"]))


if __name__ == "__main__":
    unittest.main()
