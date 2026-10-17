"""
test_plan_contract.py - offline tests for plan_contract.py, which validates a plan header
(executor, tier, bounds), enforces the file limit and the size ceilings, and resolves a tier to
a resolver ROLE (local coding contract, plan 3, task 1).

No model is loaded and no machine-local file is read (R21): the resolver, the counter and the
ceilings are injected, every plan is a fictitious file in a temporary directory (R34). Failure
paths sit beside the happy paths (R20).

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_plan_contract.py
"""

from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plan_contract as pc  # noqa: E402
from token_count import TokenCount  # noqa: E402

TIERS = {"simple": {"role": "coder", "max_files": 3},
         "standard": {"role": "coder", "max_files": 10},
         "large": {"role": "session", "max_files": 10}}
GOOD_BOUNDS = {"max_rounds": "3", "max_tokens": "1500000", "plateau": "2"}


def plan_text(executor="local-coder", tier="simple", bounds=None, files=1, extra_header="",
              front_matter=True) -> str:
    """Build a fictitious plan; bound values are written RAW so a wrong type can be planted."""
    merged = dict(GOOD_BOUNDS, **(bounds or {}))
    rows = "".join(f"  {key}: {val}\n" for key, val in merged.items() if val is not None)
    head = (f"---\nexecutor: {executor}\ntier: {tier}\n{extra_header}bounds:\n{rows}---\n"
            if front_matter else "")
    listing = "".join(f"- Create: `src/mod{i}.py`\n" for i in range(files))
    return head + "# Plan 1 - fictitious\n\n### Task 1\n\n**Files:**\n" + listing


class PlanCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / "docs" / "plans"
        self.folder.mkdir(parents=True)

    def write(self, text, name="plan1.md") -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, text, **kw):
        return pc.validate(self.write(text), self.root, TIERS, **kw)


class TestHeader(PlanCase):
    def test_a_valid_header_parses_to_the_expected_values(self):
        header = self.check(plan_text())
        self.assertEqual(header["executor"], "local-coder")
        self.assertEqual(header["tier"], "simple")
        self.assertEqual(header["bounds"],
                         {"max_rounds": 3, "max_tokens": 1500000, "plateau": 2})

    def test_each_wrong_header_is_refused_naming_the_key(self):
        cases = [
            ("no front matter", plan_text(front_matter=False), "front matter"),
            ("missing executor", plan_text().replace("executor: local-coder\n", ""), "executor"),
            ("unknown key", plan_text(extra_header="colour: red\n"), "colour"),
            ("unknown executor", plan_text(executor="gpu"), "executor"),
            ("unknown tier", plan_text(tier="huge"), "tier"),
            ("missing bound", plan_text(bounds={"plateau": None}), "plateau"),
            ("string bound", plan_text(bounds={"max_rounds": '"3"'}), "max_rounds"),
            ("zero bound", plan_text(bounds={"max_tokens": "0"}), "max_tokens"),
            ("negative bound", plan_text(bounds={"plateau": "-1"}), "plateau"),
            ("bool bound", plan_text(bounds={"max_rounds": "true"}), "max_rounds"),
            ("list bound", plan_text(bounds={"max_tokens": "[1, 2]"}), "max_tokens"),
            ("unknown bound key", plan_text(bounds={"max_days": "3"}), "max_days"),
        ]
        for label, text, key in cases:
            with self.subTest(label):
                with self.assertRaises(pc.PlanError) as ctx:
                    self.check(text)
                self.assertIn(key, str(ctx.exception))

    def test_the_file_limit_follows_the_tier(self):
        self.check(plan_text(tier="simple", files=3))
        with self.assertRaises(pc.PlanError):
            self.check(plan_text(tier="simple", files=4))
        self.check(plan_text(tier="large", files=10))
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(plan_text(tier="large", files=11))
        self.assertIn("11", str(ctx.exception))

    def test_a_plan_outside_the_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "plan1.md"
            outside.write_text(plan_text(), encoding="utf-8")
            with self.assertRaises(pc.PlanError) as ctx:
                pc.validate(outside, self.root, TIERS)
            self.assertIn("outside", str(ctx.exception))
            ok = pc.validate(outside, [self.root, Path(other)], TIERS)
            self.assertEqual(ok["tier"], "simple")

    def test_a_dotdot_path_that_escapes_is_refused_after_resolution(self):
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "plan1.md").write_text(plan_text(), encoding="utf-8")
            sneaky = self.folder / ".." / ".." / ".." / Path(other).name / "plan1.md"
            with self.assertRaises(pc.PlanError):
                pc.validate(sneaky, self.root, TIERS)

    def test_a_missing_plan_is_refused(self):
        with self.assertRaises(pc.PlanError) as ctx:
            pc.validate(self.folder / "absent.md", self.root, TIERS)
        self.assertIn("not found", str(ctx.exception))


class TestFileLines(PlanCase):
    """Fixes for the code review of 2026-10-17 (R35 round 1): the file limit must not be
    skipped by a plan written in another notation."""

    def test_a_plan_that_names_no_file_in_the_known_form_is_refused(self):
        body = plan_text(files=0) + "- File: src/mod.py\n"
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(body)
        self.assertIn("no file", str(ctx.exception))

    def test_a_path_without_backticks_is_counted(self):
        text = plan_text(tier="simple", files=0) + "".join(
            "- Create: src/mod%d.py\n" % i for i in range(4))
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(text)
        self.assertIn("4", str(ctx.exception))
        ok = plan_text(tier="simple", files=0) + "- Create: src/mod.py\n- Modify: src/other.py\n"
        self.assertEqual(self.check(ok)["files"], 2)


class TestProseIsNotAFile(PlanCase):
    """R35 round 2: unquoted prose after `- Test:` must not be counted as a file."""

    def test_prose_and_trailing_punctuation_are_not_files(self):
        text = plan_text(tier="simple", files=1) + (
            "- Test: run the suite\n- Test: see below\n- Modify: src/mod0.py,\n")
        self.assertEqual(self.check(text)["files"], 1)


class TestCeilings(PlanCase):
    def counter(self, tokens, exact=True, method="tiktoken"):
        return lambda text: TokenCount(tokens, method, exact, None if exact else "estimate")

    def test_a_plan_over_its_ceiling_is_refused_naming_file_count_method_and_ceiling(self):
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(plan_text(), ceilings={"plan.md": 99}, counter=self.counter(100))
        message = str(ctx.exception)
        for fragment in ("plan1.md", "100", "tiktoken", "99"):
            self.assertIn(fragment, message)

    def test_a_file_exactly_at_the_ceiling_passes_and_one_token_over_fails(self):
        self.check(plan_text(), ceilings={"plan.md": 100}, counter=self.counter(100))
        with self.assertRaises(pc.PlanError):
            self.check(plan_text(), ceilings={"plan.md": 100}, counter=self.counter(101))

    def test_an_estimate_applies_the_margin(self):
        est = self.counter(80, exact=False, method="chars")
        self.check(plan_text(), ceilings={"plan.md": 100}, counter=est, margin=1.25)
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(plan_text(), ceilings={"plan.md": 99}, counter=est, margin=1.25)
        self.assertIn("estimate", str(ctx.exception))

    def test_spec_and_progress_use_their_own_ceilings(self):
        (self.folder / "spec.md").write_text("s" * 10, encoding="utf-8")
        (self.folder / "progress.md").write_text("p" * 21, encoding="utf-8")
        (self.folder / "audit.md").write_text("a" * 5, encoding="utf-8")

        def counter(text):
            return TokenCount(30 if text.startswith("---") else len(text), "tiktoken", True, None)

        ceilings = {"spec.md": 10, "progress.md": 20, "plan.md": 30, "audit.md": 5}
        with self.assertRaises(pc.PlanError) as ctx:
            self.check(plan_text(), ceilings=ceilings, counter=counter)
        self.assertIn("progress.md", str(ctx.exception))
        ceilings["progress.md"] = 21
        self.check(plan_text(), ceilings=ceilings, counter=counter)

    def test_the_ceilings_come_from_the_budget_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            low = Path(tmp) / "low.json"
            high = Path(tmp) / "high.json"
            body = {"plan.md": 50, "spec.md": 50, "progress.md": 50, "audit.md": 50,
                    "code_file": 50}
            low.write_text(json.dumps({"ceilings": body}), encoding="utf-8")
            high.write_text(json.dumps({"ceilings": dict(body, **{"plan.md": 500})}),
                            encoding="utf-8")
            counter = self.counter(100)
            with self.assertRaises(pc.PlanError):
                self.check(plan_text(), ceilings=pc.load_budget([low]), counter=counter)
            self.check(plan_text(), ceilings=pc.load_budget([high]), counter=counter)

    def test_a_missing_budget_names_every_candidate_tried(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "one.json", Path(tmp) / "two.json"
            with self.assertRaises(pc.PlanError) as ctx:
                pc.load_budget([one, two])
            self.assertIn("one.json", str(ctx.exception))
            self.assertIn("two.json", str(ctx.exception))
            partial = Path(tmp) / "partial.json"
            partial.write_text(json.dumps({"ceilings": {"plan.md": 1}}), encoding="utf-8")
            with self.assertRaises(pc.PlanError) as ctx:
                pc.load_budget([partial])
            self.assertIn("spec.md", str(ctx.exception))


class TestResolve(PlanCase):
    def header(self, executor="local-coder", tier="simple"):
        return self.check(plan_text(executor=executor, tier=tier))

    def test_local_coder_resolves_the_role_the_tier_names(self):
        calls = []

        def resolver(role):
            calls.append(role)
            return "vendor-a:9b"

        out = pc.resolve(self.header(tier="large"), TIERS, resolver)
        self.assertEqual(calls, ["session"])
        self.assertEqual((out["executor"], out["role"], out["tag"], out["fallback"]),
                         ("local-coder", "session", "vendor-a:9b", False))

    def test_a_refusing_resolver_gives_the_cloud_executor_with_its_reason(self):
        def resolver(role):
            raise RuntimeError("no qualified model for role coder")

        out = pc.resolve(self.header(), TIERS, resolver)
        self.assertEqual((out["executor"], out["fallback"], out["tag"]), ("cloud", True, None))
        self.assertIn("no qualified model", out["reason"])

    def test_a_simple_plan_never_falls_back_to_the_large_role(self):
        calls = []

        def resolver(role):
            calls.append(role)
            raise RuntimeError("refused")

        pc.resolve(self.header(tier="simple"), TIERS, resolver)
        self.assertEqual(calls, ["coder"])

    def test_aider_and_cloud_plans_do_not_call_the_resolver(self):
        def resolver(role):
            raise AssertionError("must not be called")

        for executor in ("aider", "cloud"):
            out = pc.resolve(self.header(executor=executor), TIERS, resolver)
            self.assertEqual(out["executor"], executor)
            self.assertFalse(out["fallback"])


class TestShippedFiles(unittest.TestCase):
    def test_the_shipped_tier_file_has_roles_and_provenance_and_no_model_tag(self):
        raw = pc.TIERS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        for name, tier in data["tiers"].items():
            for key in ("role", "max_files"):
                self.assertTrue(tier[key]["provenance"], f"{name}.{key}")
        self.assertTrue(data["budget_candidates"]["provenance"])
        tiers = pc.load_tiers(pc.TIERS_PATH)
        self.assertEqual({t["role"] for t in tiers.values()} - {"coder", "writer", "session"},
                         set())
        for value in re.findall(r'"value":\s*"([^"]+)"', raw):
            self.assertIsNone(re.fullmatch(r"[A-Za-z0-9._-]+:[A-Za-z0-9._-]+", value), value)

    def test_a_missing_tier_key_is_a_named_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "tiers.json"
            bad.write_text(json.dumps({"tiers": {"simple": {"role": {"value": "coder"}}}}),
                           encoding="utf-8")
            with self.assertRaises(pc.PlanError) as ctx:
                pc.load_tiers(bad)
            self.assertIn("max_files", str(ctx.exception))


class TestCli(PlanCase):
    def run_cli(self, *argv, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pc.main(list(argv), **kw)
        text = buf.getvalue().strip()
        return code, (json.loads(text) if text.startswith("{") else text)

    def test_cli_exit_codes_and_json_keys(self):
        tiers = self.root / "tiers.json"
        shipped = json.loads(pc.TIERS_PATH.read_text(encoding="utf-8"))
        tiers.write_text(json.dumps(shipped), encoding="utf-8")
        budget = self.root / "budget.json"
        budget.write_text(json.dumps({"ceilings": {k: 100000 for k in pc.CEILING_KEYS}}),
                          encoding="utf-8")
        plan = self.write(plan_text())
        base = ["--repo-root", str(self.root), "--tiers", str(tiers), "--budget", str(budget),
                "--json"]
        code, report = self.run_cli("validate", str(plan), *base)
        self.assertEqual(code, 0)
        for key in ("executor", "tier", "bounds", "files"):
            self.assertIn(key, report)
        code, report = self.run_cli("resolve", str(plan), *base,
                                    resolver=lambda role: "vendor-a:9b")
        self.assertEqual((code, report["tag"]), (0, "vendor-a:9b"))
        bad = self.write(plan_text(tier="huge"), "plan2.md")
        self.assertEqual(self.run_cli("validate", str(bad), *base)[0], 2)
        missing = ["validate", str(plan), "--repo-root", str(self.root), "--tiers",
                   str(self.root / "absent.json"), "--json"]
        self.assertEqual(self.run_cli(*missing)[0], 1)


if __name__ == "__main__":
    unittest.main()
