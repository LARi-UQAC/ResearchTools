"""
Rex, the watchdog dog, in the page (2026-11-09, R15, R20, R21, R34).

Rex lives inside the agent graph, in a gutter on its left, level with the agent he
watches, about a third of an agent's size. The functions are cut out of the REAL page
and run under node, so the assertions are about behaviour and not about the text of
the source. Skipped where node is absent (R11). Fictitious agent names only. His pose
is checked from his markup: asleep has no arc, awake has three rings in the agents'
colours, the CPU ring is the whole machine (the number a task manager shows) and the
model server's own share sits in the line under him.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL = SCRIPTS.parent
PAGE = SKILL / "assets" / "rt_state.html"
sys.path.insert(0, str(SCRIPTS))


def page_text():
    return PAGE.read_text(encoding="utf-8")


def page_script():
    return re.search(r"<script>\n(.*?)</script>", page_text(), re.S).group(1)


class RexPage(unittest.TestCase):

    FUNCTIONS = ("thousands", "tokenNote", "escapeText", "ringPath", "rexWord", "rexCtx",
                 "rexTarget", "rexModel", "rexRing", "rexPercent", "rexDogArt",
                 "rexSleepingArt", "rexFigure", "rexNote")
    VARS = ("AIDER_MODE", "AIDER_ENDED", "REX_FIG", "REX_SHIELD", "REX_DOG", "REX_CROWN")

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("node is not on PATH; the page functions cannot run")
        script = page_script()
        parts = ["var CFG = {rex_watch_seconds: 8};"]
        for name in self.VARS:
            body = re.search(r"var %s = .*?;\n" % name, script, re.S)
            self.assertIsNotNone(body, "%s is not declared" % name)
            parts.append(body.group(0))
        for name in self.FUNCTIONS:
            body = re.search(r"function %s\(.*?\n\}" % name, script, re.S)
            self.assertIsNotNone(body, "%s is not declared" % name)
            parts.append(body.group(0))
        self.prelude = "\n".join(parts)

    def js(self, expression):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.js"
            path.write_text(self.prelude + "\nconsole.log(JSON.stringify(" + expression
                            + "));\n", encoding="utf-8")
            done = subprocess.run([self.node, str(path)], capture_output=True, text=True,
                                  errors="replace", timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    @staticmethod
    def session(name, state="writing", live=True, index=1, total=3):
        return {"session_id": name, "project": "C:\\work\\" + name, "live": live,
                "progress": {"plan_index": index, "plans_total": total, "round": 2},
                "flow": {"state": state, "tokens": {"live_context": 11000, "window": 49152,
                                                    "window_of": "reviewer"}}}

    def model(self, rex, sessions, hash_="", now=0):
        state = {"rex": rex, "fleet": {"harnesses": {"aider": {"sessions": sessions}}}}
        return self.js("rexModel(%s, %s, %d)" % (json.dumps(state), json.dumps(hash_), now))

    # -- the model -----------------------------------------------------------
    def test_no_rex_section_and_no_demo_draws_nothing(self):
        self.assertIsNone(self.js("rexModel({}, '', 0)"))

    def test_the_watchdog_not_running_leaves_rex_asleep(self):
        got = self.model({"active": False}, [self.session("uwd")])
        self.assertFalse(got["awake"])
        self.assertEqual(-1, got["index"])

    def test_a_running_watchdog_wakes_rex_and_he_watches_a_live_agent(self):
        got = self.model({"active": True}, [self.session("uwd")])
        self.assertTrue(got["awake"])
        self.assertEqual(["uwd"], [t["name"] for t in got["targets"]])
        self.assertEqual("CODING", got["targets"][0]["mode"])
        self.assertEqual("ctx 11K / 49K reviewer", got["targets"][0]["ctx"])

    def test_finished_and_dead_runs_are_not_watched(self):
        got = self.model({"active": True}, [self.session("a", state="done"),
                                            self.session("b", live=False), self.session("c")])
        self.assertEqual(["c"], [t["name"] for t in got["targets"]])

    def test_he_turns_to_the_next_agent_every_configured_period(self):
        sessions = [self.session("a"), self.session("b")]
        picks = [self.model({"active": True}, sessions, now=ms)["index"]
                 for ms in (0, 7999, 8000, 16000)]
        self.assertEqual([0, 0, 1, 0], picks)

    def test_the_model_carries_the_clock_for_the_graph_to_pick_among_drawn_agents(self):
        got = self.model({"active": True}, [self.session("a")], now=12345)
        self.assertEqual((8000, 12345), (got["watchMs"], got["nowMs"]))

    def test_the_sleep_hash_forces_the_sleeping_pose_even_with_a_running_watchdog(self):
        self.assertFalse(self.model({"active": True}, [self.session("a")], "#rex-sleep")["awake"])

    def test_the_demo_hash_wakes_rex_with_three_agents_when_none_runs(self):
        got = self.js("rexModel({}, '#rex-demo', 0)")
        self.assertTrue(got["awake"])
        self.assertEqual(3, len(got["targets"]))

    def test_the_demo_keeps_the_real_agents_when_there_are_some(self):
        got = self.model({}, [self.session("real")], "#rex-demo")
        self.assertEqual(["real"], [t["name"] for t in got["targets"]])

    # -- the figure ----------------------------------------------------------
    def fig(self, model, focus=None):
        return self.js("rexFigure(%s, 100, 200, %s)" % (json.dumps(model), json.dumps(focus)))

    TARGET = {"id": "a", "name": "uwd", "mode": "AUDITING", "plan": "plan 2 of 6, round 1",
              "context": "context 11K of the 49K reviewer window (the last request)",
              "ctx": "ctx 11K / 49K reviewer"}

    def awake(self, **loads):
        base = {"cpu_percent": 54, "machine_cpu_percent": 80, "vram_percent": 61,
                "cuda_percent": 38, "vram_used_mb": 3706, "vram_total_mb": 6144}
        base.update(loads)
        return {"awake": True, "targets": [self.TARGET], "index": 0, "loads": base}

    def test_asleep_has_no_arc_and_says_why(self):
        out = self.fig({"awake": False, "targets": [], "index": -1, "loads": {}})
        self.assertIn("rex-asleep", out)
        self.assertNotIn("rex-arc", out)
        self.assertIn("REX - asleep", out)
        self.assertIn("the watchdog is not running", out)

    def test_awake_draws_three_rings_in_the_agents_colours(self):
        out = self.fig(self.awake(), self.TARGET)
        for cls in ("rex-arc--cpu", "rex-arc--vram", "rex-arc--cuda"):
            self.assertIn(cls, out)
        self.assertIn("rex-awake", out)

    def test_the_cpu_ring_is_the_whole_machine_and_the_server_share_is_named(self):
        out = self.fig(self.awake(), self.TARGET)
        self.assertIn("CPU 80%", out)
        self.assertIn("model server 54%", out)
        self.assertIn("machine CPU 80%, model server 54%", out)

    def test_an_unread_machine_load_falls_back_to_the_server_share(self):
        self.assertIn("CPU 54%", self.fig(self.awake(machine_cpu_percent=None), self.TARGET))

    def test_the_watched_agent_is_named_under_the_dog_with_mode_plan_and_context(self):
        out = self.fig(self.awake(), self.TARGET)
        self.assertIn("REX - watching uwd", out)
        self.assertIn("AUDITING - plan 2 of 6, round 1", out)
        self.assertIn("ctx 11K / 49K reviewer", out)
        self.assertIn("VRAM 3706/6144 MB", out)

    def test_the_hover_carries_the_full_sentence(self):
        out = self.fig(self.awake(), self.TARGET)
        self.assertIn("context 11K of the 49K reviewer window", out)
        self.assertIn("(3706 of 6144 MB)", out)

    def test_a_ring_near_full_turns_to_the_warning_colour(self):
        self.assertIn("rex-arc--hot", self.fig(self.awake(cuda_percent=95), self.TARGET))
        self.assertNotIn("rex-arc--hot", self.fig(self.awake(), self.TARGET))

    def test_awake_with_no_agent_says_he_is_on_guard(self):
        out = self.fig(self.awake())
        self.assertIn("REX - on guard", out)
        self.assertIn("no agent to watch", out)

    def test_he_is_placed_where_the_graph_says(self):
        self.assertIn("translate(100px, 200px)", self.fig(self.awake(), self.TARGET))

    def test_an_agent_name_cannot_inject_markup(self):
        target = dict(self.TARGET, name="<img src=x onerror=alert(1)>")
        out = self.fig(self.awake(), target)
        self.assertNotIn("<img", out)

    def test_a_missing_load_is_a_dash_not_a_zero(self):
        out = self.fig({"awake": False, "targets": [], "index": -1,
                        "loads": {"cpu_percent": None}})
        self.assertIn("CPU -", out)
        self.assertNotIn("CPU 0%", out)

    def test_the_dog_is_about_a_third_of_an_agent(self):
        sizes = self.js("[REX_FIG.dog, REX_FIG.rings]")
        dog_height = 240 * sizes[0]
        agent_ring_diameter = 2 * 42
        self.assertLessEqual(dog_height, agent_ring_diameter / 2.5)
        self.assertGreater(dog_height, agent_ring_diameter / 4)


class RexInTheAgentGraph(unittest.TestCase):

    def test_the_graph_widens_its_left_gutter_only_when_rex_is_drawn(self):
        self.assertIn("var colX = 300 + (rex ? REX_FIG.gutter : 0);", page_script())

    def test_rex_is_drawn_by_the_graph_level_with_the_agent_he_watches(self):
        body = re.search(r"function agentGraph\(.*?\n\}\n", page_script(), re.S).group(0)
        self.assertIn("rexFigure(rex, REX_FIG.cx, rexY, focus)", body)
        self.assertIn('rowOf["s:" + t.id]', body)
        self.assertIn("centre(focus ? rowOf", body)

    def test_the_graph_receives_the_model_and_a_lone_figure_covers_no_agent(self):
        body = re.search(r"function renderLive\(state\) \{(.*?)\n\}\n", page_script(), re.S).group(1)
        self.assertIn("sharedState(state), rexModelNow)", body)
        self.assertIn("rexAlone(rexModelNow)", body)

    def test_there_is_no_separate_strip_and_no_marker_row_any_more(self):
        text = page_text()
        for gone in ("rexStrip", "rexSvg", "rexgraph"):
            self.assertNotIn(gone, text)

    def test_the_view_config_carries_the_watch_period(self):
        import rt_state
        config = rt_state.load_config(SKILL)
        self.assertIsInstance(rt_state.view_config(config)["rex_watch_seconds"], int)

    def test_motion_is_switched_off_under_reduced_motion(self):
        block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*svg\.flowgraph \.rex-walker(.*?)\}\s*\}",
                          page_text(), re.S)
        self.assertIsNotNone(block)
        self.assertIn("animation: none", block.group(1))
        self.assertIn("transition: none", block.group(1))

    def test_the_walk_is_a_slow_transition_on_the_walker_only(self):
        self.assertRegex(page_text(), r"svg\.flowgraph \.rex-walker \{ transition: transform 4s")

    def test_the_small_dog_keeps_pixel_strokes(self):
        self.assertIn("vector-effect: non-scaling-stroke", page_text())


if __name__ == "__main__":
    unittest.main()
