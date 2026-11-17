"""
test_rt_view_local_actions - the steps of a local role's lane in the page (plan 11, Task 2, R11).

The owner asked that a local role such as the grader show what it did, the way a Claude Code
session shows its tool calls. The collector (plan 11, Task 1) gives each role an `actions` list;
this suite checks that the page turns that list into steps of the kind a tool call already is,
and that the state label of the hexagon is not cut.

The functions are cut out of the REAL page and run under node, so the assertions are about
behaviour and not about the text of the source. Skipped where node is absent (R11). Fictitious
roles, plans and targets only (R34).
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL_ROOT = SCRIPTS.parent
PAGE = SKILL_ROOT / "assets" / "rt_state.html"


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class LocalLaneSteps(unittest.TestCase):
    FUNCTIONS = ("clock", "escapeText", "callLines", "laneEvents", "localLanes")

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("node is not on PATH; the page functions cannot run")
        self.page = read(PAGE)
        self.script = re.search(r"<script>\n(.*?)</script>", self.page, re.S).group(1)
        parts = ["var sessionFilter = {active: true, idle: true, noflow: true};"]
        for name in self.FUNCTIONS:
            body = re.search(r"function %s\(.*?\n\}" % name, self.script, re.S)
            self.assertIsNotNone(body, "%s is not declared" % name)
            parts.append(body.group(0))
        self.prelude = "\n".join(parts)

    def run_js(self, expression):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.js"
            path.write_text(self.prelude + "\nconsole.log(JSON.stringify("
                            + expression + "));\n", encoding="utf-8")
            done = subprocess.run([self.node, str(path)], capture_output=True,
                                  text=True, errors="replace", timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    @staticmethod
    def state(actions=None, with_key=True):
        """A healthy local_calls section with one generating grader role. Fictitious (R34)."""
        role = {"tag": "vendor-a:9b", "num_ctx": 16384, "calls": 2,
                "prompt_tokens": 9000, "completion_tokens": 900,
                "last_at": "2026-11-16T11:59:30+00:00", "age_seconds": 30,
                "active": True, "generating": True,
                "plan": "C:\\tmp\\proj\\plans\\plan1.md"}
        if with_key:
            role["actions"] = actions if actions is not None else []
        return {"local_calls": {"status": "ok", "roles": {"grader": role},
                                "recent": []}}

    @staticmethod
    def action(name, target=None, at="2026-11-16T11:58:00+00:00"):
        item = {"at": at, "action": name, "target": target,
                "report_id": None, "detail": None}
        return item

    def grader_lane(self, state):
        lanes = self.run_js("localLanes(%s)" % json.dumps(state))
        return {lane["id"]: lane for lane in lanes}["l:grader"]

    def test_local_lane_has_steps_from_actions(self):
        state = self.state([self.action("read", "p12-15 R04"),
                            self.action("write", "plan1.md")])
        steps = self.grader_lane(state)["steps"]
        self.assertEqual(2, len(steps))
        self.assertEqual("read p12-15 R04", steps[0]["name"])
        self.assertEqual("write plan1.md", steps[1]["name"])
        for step in steps:
            with self.subTest(step=step["name"]):
                self.assertEqual("tool", step["kind"],
                                 "a local action is drawn as a tool call")
                self.assertEqual("no", step["network"],
                                 "a local role leaves the machine through no tool")

    def test_an_action_without_a_target_is_named_by_its_action_alone(self):
        steps = self.grader_lane(self.state([self.action("audit")]))["steps"]
        self.assertEqual(["audit"], [step["name"] for step in steps])

    def test_repeated_step_counts(self):
        state = self.state([self.action("read", "p12-15 R04"),
                            self.action("read", "p12-15 R04"),
                            self.action("read", "p12-15 R04")])
        groups = self.run_js(
            "laneEvents(localLanes(%s)[0].steps).map(function (g) "
            "{ return {name: g.name, count: g.count}; })" % json.dumps(state))
        self.assertEqual([{"name": "read p12-15 R04", "count": 3}], groups,
                         "a repeated identical step is one box with a count")

    def test_lane_without_actions_has_no_steps(self):
        for state in (self.state(with_key=False), self.state([])):
            with self.subTest(actions="absent" if "actions" not in
                              state["local_calls"]["roles"]["grader"] else "empty"):
                lane = self.grader_lane(state)
                self.assertEqual([], lane["steps"],
                                 "a role with no actions keeps its lane with no step")
                self.assertTrue(lane["id"], "the lane itself is still drawn")

    def test_step_name_is_escaped(self):
        """A target holding markup stays text. The step name is kept raw as data, and
        the drawing writes it through escapeText, which the next two checks prove."""
        hostile = '<img src=x onerror="alert(1)">'
        steps = self.grader_lane(self.state([self.action("read", hostile)]))["steps"]
        self.assertEqual("read " + hostile, steps[0]["name"])
        escaped = self.run_js("escapeText(%s)" % json.dumps(steps[0]["name"]))
        self.assertNotIn("<", escaped)
        self.assertNotIn('"', escaped)
        self.assertIn("&lt;img", escaped)
        self.assertIn("&quot;alert(1)&quot;", escaped)

    def test_the_drawing_escapes_the_step_name(self):
        """The step element is written into svg.innerHTML. Both places that carry the
        name must go through escapeText, or the earlier check proves nothing about the page."""
        self.assertIn("escapeText(event.name)", self.script)
        self.assertIn("escapeText(event.name.length", self.script)

    def test_generating_label_is_not_cut(self):
        """The state word of a generating hexagon is shown whole. The old page cut it to
        eight characters, so `generating` read `generat`. The hexagon is pointy-top, about
        52 pixels wide at its centre line, so the fit comes from the font (letter spacing
        off), not from a shorter word."""
        # The policy-hash prefix elsewhere in the page is a fingerprint, not a label, so
        # the finder is the state expression itself (the old form was `lane.state ...slice`).
        self.assertIsNone(re.search(r"lane\.state[^;\n]*\.slice\(", self.script),
                          "the state label must not be truncated")
        self.assertIsNotNone(re.search(r'escapeText\(lane\.state \|\| ""\)', self.script),
                             "the state label is drawn whole")
        # Anchored to the line start: the voice panel's `.voice-graph svg.flowgraph ...`
        # override (12px) carries the same selector tail and is a different panel.
        rule = re.search(r"^svg\.flowgraph \.fx-agent-state \{(.*?)\}", self.page,
                         re.S | re.M)
        self.assertIsNotNone(rule, "the state label rule is not found")
        spacing = re.search(r"letter-spacing:\s*([0-9.]+)", rule.group(1))
        self.assertTrue(spacing is None or float(spacing.group(1)) == 0.0,
                        "letter spacing widens the label past the hexagon")
        self.assertIn("font-size: 10px", rule.group(1),
                      "the state label stays at the page's ten-pixel floor")


if __name__ == "__main__":
    unittest.main()
