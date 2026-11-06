"""
test_local_coder_driver - offline suite for the local-coder driver (Issue #104, plan 13).

The driver must put in front of the coder model exactly the files aider-plan.ps1 hands aider
(conventions, rules, spec, plan, skill stage, progress, plan targets, message), call the model once
per plan, and run every plan of progress.md. Everything is fictitious (R34) and built in TEMP; the
model, the window and the test runner are fakes (R21), so no daemon and no process is used.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import local_coder_driver as lcd  # noqa: E402

FENCE = "`" * 3
CONFIG = lcd.load_config()
BUDGET = {
    "always_on_files": ["{{HOME}}/.config/aider/conventions.md", "{{HOME}}/.config/aider/rules.md"],
    "reserve": {"reply_tokens": 3000},
    "ceilings": {"conventions.md": 500, "rules.md": 500, "spec.md": 500, "plan.md": 500,
                 "progress.md": 500, "code_file": 800},
    "tests": {"max_fix_attempts": 2},
}
SKILLS = {"stages": {
    "write": {"bundle": "{{HOME}}/.config/aider/skills/tdd", "ceiling": 400},
    "reopen": {"files": ["{{HOME}}/.config/aider/skills/receiving.md"], "ceiling": 400},
}}

PLAN = """---
executor: local-coder
tier: standard
bounds:
  max_rounds: 1
  max_tokens: 1000
  plateau: 1
---

# Plan {n}

**Files:**
- Create: `pkg/mod{n}.py`
- Test: `pkg/Test/test_mod{n}.py`

- [ ] Step 1: write the module.
"""


class FakeDeps:
    """Purpose: stand in for the model, the window and the test runner. Inputs: replies (list of
    str), test results (list of int). Outputs: records every prompt and every test command."""

    def __init__(self, replies, results, executor="local-coder", window=20000):
        self.replies = list(replies)
        self.results = list(results)
        self.executor = executor
        self.window_value = window
        self.prompts = []
        self.reserves = []
        self.commands = []

    def contract(self, plan):
        return {"executor": self.executor, "role": "coder"}

    def tag(self, role):
        return "vendor-a:9b"

    def window(self, tag, role):
        return self.window_value

    def count(self, text):
        return len(text) // 4

    def generate(self, prompt, tag, window, reserve, timeout):
        self.prompts.append(prompt)
        self.reserves.append(reserve)
        return self.replies.pop(0)

    def runner(self, command, cwd, timeout):
        self.commands.append(command)
        code = self.results.pop(0)
        return code, "1 test OK" if code == 0 else "FAIL: test_x\nAssertionError: 1 != 2"


def _reply(*names):
    """Purpose: a model reply carrying one fenced file per name. Inputs: names (str). Outputs: str."""
    return "".join(f"{FENCE}python\n# file: {name}\nX = 1\n{FENCE}\n" for name in names)


class World:
    """Purpose: build a fictitious repository with the aider config, an effort and n plans."""

    def __init__(self, plans=1):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        config = self.home / ".config" / "aider"
        (config / "skills" / "tdd").mkdir(parents=True)
        (config / "conventions.md").write_text("CONVENTIONS-MARKER\n", encoding="utf-8")
        (config / "rules.md").write_text("RULES-MARKER\n", encoding="utf-8")
        (config / "skills" / "tdd" / "SKILL.md").write_text("TDD-MARKER see helper.md\n", encoding="utf-8")
        (config / "skills" / "tdd" / "helper.md").write_text("HELPER-MARKER\n", encoding="utf-8")
        (config / "skills" / "receiving.md").write_text("REOPEN-MARKER\n", encoding="utf-8")
        self.root = base / "repo"
        self.effort = self.root / "docs" / "effort"
        self.effort.mkdir(parents=True)
        (self.effort / "spec.md").write_text("SPEC-MARKER é\n", encoding="utf-8")
        ledger = ["# Progress", ""]
        for n in range(1, plans + 1):
            (self.effort / f"plan{n}.md").write_text(PLAN.replace("{n}", str(n)), encoding="utf-8")
            ledger += [f"## plan{n}.md", "", f"- [ ] T1 module {n}", ""]
        self.progress = self.effort / "progress.md"
        self.progress.write_text("\n".join(ledger), encoding="utf-8")

    def run(self, deps):
        return lcd.run(self.progress, self.root, deps, BUDGET, SKILLS, CONFIG, self.home)

    def close(self):
        self.tmp.cleanup()


class FileSetTests(unittest.TestCase):
    def setUp(self):
        self.world = World()

    def tearDown(self):
        self.world.close()

    def test_the_file_set_is_aider_setup_s_in_order(self):
        w = self.world
        (w.root / "pkg").mkdir()
        (w.root / "pkg" / "mod1.py").write_text("OLD = 0\n", encoding="utf-8")
        files = lcd.file_set(w.effort / "plan1.md", w.root, BUDGET, SKILLS, "write", CONFIG,
                             w.home, lambda t: len(t) // 4)
        names = [Path(path).name for _, path in files]
        self.assertEqual(names, ["conventions.md", "rules.md", "spec.md", "plan1.md", "SKILL.md",
                                 "helper.md", "progress.md", "mod1.py"])

    def test_the_prompt_holds_every_file_whole_then_the_message(self):
        w = self.world
        deps = FakeDeps([_reply("pkg/mod1.py", "pkg/Test/test_mod1.py")], [0])
        w.run(deps)
        prompt = deps.prompts[0]
        markers = ["CONVENTIONS-MARKER", "RULES-MARKER", "SPEC-MARKER é", "# Plan 1", "TDD-MARKER",
                   "HELPER-MARKER", "## plan1.md", "Execute plan1.md", "# file:"]
        positions = [prompt.index(m) for m in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("pkg/mod1.py", prompt)

    def test_a_missing_always_on_file_is_refused_by_name(self):
        w = self.world
        (w.home / ".config" / "aider" / "rules.md").unlink()
        with self.assertRaises(lcd.DriverError) as ctx:
            lcd.file_set(w.effort / "plan1.md", w.root, BUDGET, SKILLS, "write", CONFIG,
                         w.home, lambda t: 1)
        self.assertIn("rules.md", str(ctx.exception))

    def test_a_file_over_its_ceiling_is_refused(self):
        w = self.world
        (w.effort / "spec.md").write_text("word " * 3000, encoding="utf-8")
        with self.assertRaises(lcd.DriverError) as ctx:
            lcd.file_set(w.effort / "plan1.md", w.root, BUDGET, SKILLS, "write", CONFIG,
                         w.home, lambda t: len(t) // 4)
        self.assertIn("spec.md", str(ctx.exception))

    def test_targets_skip_the_front_matter_and_stay_inside_the_root(self):
        w = self.world
        plan = w.effort / "plan9.md"
        plan.write_text("---\nexecutor: local-coder\nnote: header.py\n---\n- Create: `a/b.py`\n"
                        "- Modify: `../../evil.py` and data `c.json`\n", encoding="utf-8")
        targets = [p.relative_to(w.root).as_posix() for p in lcd.plan_targets(plan, w.root, CONFIG)]
        self.assertEqual(targets, ["a/b.py", "c.json"])


    def test_a_target_under_a_dot_folder_keeps_its_leading_dot(self):
        """Get-PlanTargets trims dots on both sides, so `.claude/x.py` became `claude/x.py`
        (found 2026-11-05 on plan 4); the driver trims trailing dots only."""
        w = self.world
        (w.root / ".claude").mkdir()
        (w.root / ".claude" / "x.py").write_text("X = 1\n", encoding="utf-8")
        plan = w.effort / "plan8.md"
        plan.write_text("- Test: `.claude/x.py`. Then `y.py`.\n", encoding="utf-8")
        targets = [p.relative_to(w.root).as_posix() for p in lcd.plan_targets(plan, w.root, CONFIG)]
        self.assertEqual(targets, [".claude/x.py", "y.py"])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.world = World(plans=2)

    def tearDown(self):
        self.world.close()

    def test_two_plans_run_in_one_call_and_are_ticked(self):
        w = self.world
        deps = FakeDeps([_reply("pkg/mod1.py", "pkg/Test/test_mod1.py"),
                         _reply("pkg/mod2.py", "pkg/Test/test_mod2.py")], [0, 0])
        report = w.run(deps)
        self.assertEqual([p["status"] for p in report["plans"]], ["done", "done"])
        self.assertTrue((w.root / "pkg" / "mod2.py").is_file())
        ledger = w.progress.read_text(encoding="utf-8")
        self.assertIn("- [x] T1 module 1", ledger)
        self.assertIn("- [x] T1 module 2", ledger)
        self.assertEqual(len(deps.prompts), 2)

    def test_the_reply_reserve_is_reply_tokens(self):
        deps = FakeDeps([_reply("pkg/mod1.py"), _reply("pkg/mod2.py")], [0, 0])
        self.world.run(deps)
        self.assertEqual(deps.reserves, [3000, 3000])

    def test_a_failing_plan_is_retried_with_reopen_then_blocked_and_the_next_plan_runs(self):
        w = self.world
        deps = FakeDeps([_reply("pkg/mod1.py")] * 2 + [_reply("pkg/mod2.py")], [1, 1, 0])
        report = w.run(deps)
        self.assertEqual([p["status"] for p in report["plans"]], ["blocked", "done"])
        self.assertIn("REOPEN-MARKER", deps.prompts[1])
        self.assertIn("AssertionError", deps.prompts[1])
        ledger = w.progress.read_text(encoding="utf-8")
        self.assertIn("- [!] T1 module 1", ledger)
        self.assertIn("- [x] T1 module 2", ledger)

    def test_a_path_outside_the_root_or_not_named_by_the_plan_is_refused(self):
        w = self.world
        deps = FakeDeps([_reply("../outside.py"), _reply("pkg/other.py"),
                         _reply("pkg/mod2.py")], [0])
        report = w.run(deps)
        self.assertEqual(report["plans"][0]["status"], "blocked")
        self.assertFalse((w.root.parent / "outside.py").exists())
        self.assertFalse((w.root / "pkg" / "other.py").exists())

    def test_a_prompt_over_the_window_is_refused_before_any_call(self):
        deps = FakeDeps([], [], window=3100)
        report = self.world.run(deps)
        self.assertEqual(deps.prompts, [])
        self.assertEqual(report["plans"][0]["status"], "refused")

    def test_a_plan_not_for_local_coder_is_skipped(self):
        deps = FakeDeps([], [], executor="cloud")
        report = self.world.run(deps)
        self.assertEqual({p["status"] for p in report["plans"]}, {"skipped"})
        self.assertEqual(deps.prompts, [])

    def test_the_tests_run_are_the_plan_test_files(self):
        deps = FakeDeps([_reply("pkg/mod1.py"), _reply("pkg/mod2.py")], [0, 0])
        self.world.run(deps)
        self.assertTrue(deps.commands[0][-1].endswith("test_mod1.py"))


class CliTests(unittest.TestCase):
    def test_dry_run_writes_nothing_and_counts_tokens(self):
        world = World()
        try:
            before = world.progress.read_text(encoding="utf-8")
            report = lcd.dry_run(world.progress, world.root, BUDGET, SKILLS, CONFIG,
                                 world.home, lambda t: len(t) // 4)
            self.assertEqual(world.progress.read_text(encoding="utf-8"), before)
            self.assertGreater(report["plans"][0]["prompt_tokens"], 0)
            self.assertFalse((world.root / "pkg").exists())
        finally:
            world.close()

    def test_a_missing_config_key_is_named(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "c.json"
            path.write_text(json.dumps({"code_extensions": {"value": [".py"], "provenance": "x"}}),
                            encoding="utf-8")
            with self.assertRaises(lcd.DriverError) as ctx:
                lcd.load_config(path)
        self.assertIn("data_extensions", str(ctx.exception))

    def test_every_shipped_value_carries_provenance(self):
        raw = json.loads(lcd.DEFAULT_CONFIG.read_text(encoding="utf-8"))
        for key, entry in raw.items():
            if not key.startswith("_"):
                self.assertTrue(entry.get("provenance"), key)


if __name__ == "__main__":
    unittest.main()
