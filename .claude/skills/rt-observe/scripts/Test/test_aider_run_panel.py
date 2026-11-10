"""
The aider run block of the Plan panel and the live-context ring note, checked
against the real page (2026-11-09, R15, R20). Two cannot-disagree checks and one
behaviour check under node (skipped where node is absent, R11):

- every state the aider adapter can write has a mode in the page, so a state
  added to the driver cannot reach the panel as a blank word;
- the Plan panel draws the aider run before anything else and from the fleet
  section, so a machine with no aider shows the panel as before;
- the ring note says what the number is: the context of the last request, with
  the fixed reserve beside it, and keeps the old wording for a run that logs
  nothing yet.
"""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS / "adapters"))
import aider  # noqa: E402

PAGE = SCRIPTS.parent / "assets" / "rt_state.html"


def page_script():
    with io.open(PAGE, encoding="utf-8") as handle:
        return re.search(r"<script>\n(.*?)</script>", handle.read(), re.S).group(1)


class AiderModes(unittest.TestCase):

    def test_every_adapter_state_has_a_mode_in_the_page(self):
        block = re.search(r"var AIDER_MODE = \{(.*?)\n\};", page_script(), re.S)
        self.assertIsNotNone(block, "AIDER_MODE is not declared")
        keys = set(re.findall(r"^\s*([a-z_]+):", block.group(1), re.M))
        for state_id, _label, _role in aider.FLOW_STATES:
            self.assertIn(state_id, keys, "no mode for the state %r" % state_id)
        self.assertIn("idle", keys)

    def test_the_ended_states_are_the_adapters_terminal_states(self):
        block = re.search(r"var AIDER_ENDED = \{(.*?)\};", page_script(), re.S)
        ended = set(re.findall(r"([a-z_]+):\s*true", block.group(1)))
        self.assertEqual(set(aider.TERMINAL_STATES), ended)

    def test_the_plan_panel_draws_the_run_first_from_the_fleet(self):
        script = page_script()
        panel = re.search(r"function renderPlanPanel\(state\) \{(.*?)\n\}", script, re.S).group(1)
        self.assertLess(panel.index("appendAiderRuns(panel, state)"),
                        panel.index("state.progress"))
        runs = re.search(r"function appendAiderRuns\(.*?\n\}", script, re.S).group(0)
        self.assertIn("(state.fleet || {}).harnesses", runs)
        self.assertIn("AIDER_ENDED", runs)


class RunPlans(unittest.TestCase):

    def test_the_run_lists_its_own_plans_and_titles_the_repository_list(self):
        script = page_script()
        runs = re.search(r"function appendAiderRuns\(.*?\n\}", script, re.S).group(0)
        self.assertIn("s.plans", runs)
        self.assertIn("return runs.length", runs)
        panel = re.search(r"function renderPlanPanel\(state\) \{(.*?)\n\}", script, re.S).group(1)
        self.assertIn("repository plan (PROGRESS.md)", panel)
        self.assertLess(panel.index("if (drawn)"), panel.index('el("ul", "phases")'))

    def test_every_plan_state_the_adapter_writes_has_a_style_in_the_page(self):
        runs = re.search(r"function appendAiderRuns\(.*?\n\}", page_script(), re.S).group(0)
        for state in ("done", "blocked", "in-progress", "todo"):
            self.assertIn(state, runs)


class RingNote(unittest.TestCase):

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("node is not on PATH; the page functions cannot run")
        script = page_script()
        self.prelude = "\n".join(
            re.search(r"function %s\(.*?\n\}" % name, script, re.S).group(0)
            for name in ("thousands", "tokenNote"))

    def note(self, tokens):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.js"
            path.write_text(self.prelude + "\nconsole.log(JSON.stringify(tokenNote("
                            + json.dumps(tokens) + ")));\n", encoding="utf-8")
            done = subprocess.run([self.node, str(path)], capture_output=True,
                                  text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_live_context_is_named_with_its_fixed_reserve(self):
        text = self.note({"live_context": 14000, "window": 65536, "fixed_cost": 27473,
                          "task_budget": 38063, "held": 14000})
        self.assertEqual("context 14K of the 66K window (the last request; "
                         "fixed reserve 27K)", text)

    def test_a_run_with_no_request_yet_keeps_the_fixed_cost_wording(self):
        text = self.note({"window": 65536, "task_budget": 38063, "held": 27473})
        self.assertEqual("fixed cost 27K, task budget 38K of the 66K window", text)

    def test_a_zero_live_context_is_a_measurement_not_an_absence(self):
        text = self.note({"live_context": 0, "window": 65536, "fixed_cost": 27473})
        self.assertTrue(text.startswith("context 0K"))


if __name__ == "__main__":
    unittest.main()
