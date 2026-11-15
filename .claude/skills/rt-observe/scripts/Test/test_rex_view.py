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
                 "rexTarget", "rexLocalTarget", "rexModel", "rexRing", "rexPercent", "rexDogArt",
                 "rexSleepingArt", "rexFigure", "rexNote", "rexFocus", "rexJudged", "rexMedian",
                 "rexMood", "rexRemember")
    VARS = ("AIDER_MODE", "AIDER_ENDED", "REX_FIG", "REX_SHIELD", "REX_INNER", "REX_DOG",
            "REX_EAR_INNER", "REX_EYE", "REX_BROW", "REX_CHEEK", "REX_MUZZLE", "REX_CHEST",
            "REX_COLLAR", "REX_MOUTH", "REX_DIMS", "REX_JUDGED_MODES", "rexHistory")

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("node is not on PATH; the page functions cannot run")
        script = page_script()
        parts = ["var CFG = {rex_watch_seconds: 8, rex_baseline_polls: 10, rex_restless_ratio: 0.6, rex_agitated_ratio: 0.3, rex_judged_percent: 10};"]
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

    # -- a local role that is generating (Issue 118) -------------------------
    @staticmethod
    def local_state(generating, rows, sessions=()):
        """A state with the rex section naming `generating` and a local_calls section of `rows`."""
        return {"rex": {"active": bool(generating), "local_generating": list(generating)},
                "local_calls": {"status": "ok", "roles": rows, "recent": []},
                "fleet": {"harnesses": {"aider": {"sessions": list(sessions)}}}}

    def local_model(self, state, now=0):
        return self.js("rexModel(%s, '', %d)" % (json.dumps(state), now))

    ROW = {"generating": True, "tag": "tag-a", "num_ctx": 262144, "plan": "C:\work\plan1.md"}

    def test_a_generating_local_role_is_a_target_in_the_generating_mode(self):
        got = self.local_model(self.local_state(["ugs-grader"], {"ugs-grader": self.ROW}))
        self.assertTrue(got["awake"])
        self.assertEqual(["ugs-grader"], [t["name"] for t in got["targets"]])
        target = got["targets"][0]
        self.assertEqual("GENERATING", target["mode"])
        self.assertEqual("l:ugs-grader", target["lane"])
        self.assertEqual("plan1.md", target["plan"])
        self.assertIn("262K", target["ctx"])

    def test_a_local_role_that_is_not_generating_is_no_target(self):
        row = dict(self.ROW, generating=False)
        got = self.local_model(self.local_state([], {"ugs-grader": row}))
        self.assertEqual([], got["targets"])

    def test_aider_targets_come_first_and_keep_their_lane(self):
        state = self.local_state(["ugs-grader"], {"ugs-grader": self.ROW},
                                 sessions=[self.session("uwd")])
        got = self.local_model(state)
        self.assertEqual(["uwd", "ugs-grader"], [t["name"] for t in got["targets"]])
        self.assertEqual("s:uwd", got["targets"][0]["lane"])
        self.assertEqual("CODING", got["targets"][0]["mode"])

    def test_the_generating_mode_is_judged_for_the_mood_and_testing_is_not(self):
        got = self.local_model(self.local_state(["ugs-grader"], {"ugs-grader": self.ROW}))
        got["index"] = 0
        self.assertTrue(self.js("rexJudged(%s)" % json.dumps(got)))
        tests = self.model({"active": True}, [self.session("t", state="testing")])
        tests["index"] = 0
        self.assertFalse(self.js("rexJudged(%s)" % json.dumps(tests)))

    def test_a_role_name_with_markup_never_reaches_the_figure_unescaped(self):
        name = "<img src=x onerror=alert(1)>"
        got = self.local_model(self.local_state([name], {name: self.ROW}))
        target = got["targets"][0]
        got["loads"] = {}
        fig = self.js("rexFigure(%s, 100, 200, %s)" % (json.dumps(got), json.dumps(target)))
        self.assertNotIn("<img", fig)

    def test_an_older_server_without_the_local_fields_gives_the_old_result(self):
        state = {"rex": {"active": True},
                 "fleet": {"harnesses": {"aider": {"sessions": [self.session("uwd")]}}}}
        got = self.local_model(state)
        self.assertEqual(["uwd"], [t["name"] for t in got["targets"]])

    def test_a_name_in_the_rex_list_without_a_local_row_still_gets_a_target(self):
        got = self.local_model(self.local_state(["ugs-grader"], {}))
        self.assertEqual(["ugs-grader"], [t["name"] for t in got["targets"]])
        self.assertEqual("", got["targets"][0]["ctx"])

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

    def test_the_awake_doberman_has_ears_eye_tan_marks_collar_and_is_clipped_to_the_shield(self):
        art = self.js("rexDogArt()")
        for part in ("rex-ear-in", "rex-tan", "rex-collar", "rex-tag", "rex-nose",
                     'clip-path="url(#rex-clip)"', "<clipPath"):
            self.assertIn(part, art)
        self.assertEqual(4, art.count('class="rex-tan"'))
        self.assertIn("rex-waft", art)

    def test_the_head_outline_is_drawn_with_many_points_not_a_handful(self):
        outline = self.js("REX_DOG")
        self.assertGreaterEqual(len(re.findall(r"[CL]", outline)), 20)

    def test_the_sleeping_dog_is_clipped_to_the_shield_too(self):
        art = self.js("rexSleepingArt()")
        self.assertIn('clip-path="url(#rex-clip)"', art)
        self.assertIn("rex-ear-in", art)
        self.assertIn("rex-z", art)

    def test_the_shield_line_and_the_clip_share_one_outline(self):
        out = self.fig({"awake": False, "targets": [], "index": -1, "loads": {}})
        outline = self.js("REX_INNER")
        self.assertIn('class="rex-shield-line" d="' + outline + '"', out)
        self.assertIn('<clipPath id="rex-clip"><path d="' + outline + '"/>', out)

    def test_the_dog_is_about_a_third_of_an_agent(self):
        sizes = self.js("[REX_FIG.dog, REX_FIG.rings]")
        dog_height = 240 * sizes[0]
        agent_ring_diameter = 2 * 42
        self.assertLessEqual(dog_height, agent_ring_diameter / 2.5)
        self.assertGreater(dog_height, agent_ring_diameter / 4)


class RexMood(unittest.TestCase):
    """Rex gets restless when a load falls well under its recent working level (2026-11-10)."""

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("node is not on PATH; the page functions cannot run")
        helper = RexPage("test_a_running_watchdog_wakes_rex_and_he_watches_a_live_agent")
        helper.setUp()
        self.page = helper

    def target(self, mode):
        return {"id": "a", "name": "uwd", "mode": mode, "plan": "plan 1 of 3", "context": "", "ctx": ""}

    def model(self, mode="CODING", awake=True, **loads):
        base = {"cpu_percent": 60, "vram_percent": 80, "cuda_percent": 6, "proven_at": "t1"}
        base.update(loads)
        return {"awake": awake, "targets": [self.target(mode)], "index": 0, "loads": base}

    def mood(self, model, cpu_history=(60,) * 10, **other):
        history = {"cpu": list(cpu_history), "vram": other.get("vram", [80] * 10),
                   "cuda": other.get("cuda", [6] * 10), "at": "", "mode": "CODING"}
        return self.page.js("rexMood(%s, %s)" % (json.dumps(model), json.dumps(history)))

    def test_a_steady_load_keeps_him_calm(self):
        self.assertEqual("calm", self.mood(self.model(cpu_percent=55))["level"])

    def test_a_fall_under_the_restless_share_makes_him_uneasy_and_names_the_load(self):
        got = self.mood(self.model(cpu_percent=30))
        self.assertEqual("restless", got["level"])
        self.assertEqual("CPU fell to 30% from about 60%", got["reason"])

    def test_a_fall_near_idle_makes_him_agitated(self):
        self.assertEqual("agitated", self.mood(self.model(cpu_percent=10))["level"])

    def test_the_memory_falling_counts_too(self):
        got = self.mood(self.model(vram_percent=10))
        self.assertEqual(("agitated", "VRAM fell to 10% from about 80%"), (got["level"], got["reason"]))

    def test_a_load_whose_working_level_is_negligible_is_not_judged(self):
        self.assertEqual("calm", self.mood(self.model(cuda_percent=0))["level"])

    def test_too_little_history_judges_nothing(self):
        self.assertEqual("calm", self.mood(self.model(cpu_percent=1), cpu_history=(60, 60))["level"])

    def test_only_coding_and_auditing_are_judged_never_the_tests_or_sleep(self):
        self.assertEqual("calm", self.mood(self.model("TESTING", cpu_percent=1))["level"])
        self.assertEqual("calm", self.mood(self.model(awake=False, cpu_percent=1))["level"])

    def test_a_server_without_the_settings_judges_nothing(self):
        self.page.prelude = self.page.prelude.replace("rex_restless_ratio: 0.6, ", "")
        self.assertEqual("calm", self.mood(self.model(cpu_percent=1))["level"])

    def test_a_missing_reading_is_not_a_fall(self):
        self.assertEqual("calm", self.mood(self.model(cpu_percent=None))["level"])

    def remember(self, model, mood_level="calm", history=None):
        history = history or {"cpu": [], "vram": [], "cuda": [], "at": "", "mode": "CODING"}
        return self.page.js("(function () { var h = %s; rexRemember(%s, {level: %s}, h); return h; })()"
                            % (json.dumps(history), json.dumps(model), json.dumps(mood_level)))

    def test_a_calm_reading_joins_the_working_level_once_per_collection(self):
        once = self.remember(self.model())
        self.assertEqual([60], once["cpu"])
        twice = self.remember(self.model(), history=once)
        self.assertEqual([60], twice["cpu"])

    def test_a_low_reading_does_not_become_the_new_normal(self):
        got = self.remember(self.model(cpu_percent=5), mood_level="agitated")
        self.assertEqual([], got["cpu"])

    def test_the_memory_is_trimmed_to_the_window(self):
        history = {"cpu": [1] * 10, "vram": [], "cuda": [], "at": "old", "mode": "CODING"}
        got = self.remember(self.model(), history=history)
        self.assertEqual(10, len(got["cpu"]))
        self.assertEqual(60, got["cpu"][-1])

    def test_a_change_of_mode_starts_the_memory_again(self):
        history = {"cpu": [60] * 5, "vram": [], "cuda": [], "at": "old", "mode": "CODING"}
        got = self.remember(self.model("AUDITING"), history=history)
        self.assertEqual("AUDITING", got["mode"])
        self.assertEqual([60], got["cpu"])

    def figure(self, level):
        model = dict(RexPage.awake(RexPage("test_asleep_has_no_arc_and_says_why")))
        model["mood"] = {"level": level, "reason": "CPU fell to 20% from about 60%"}
        return self.page.js("rexFigure(%s, 100, 200, %s)" % (json.dumps(model), json.dumps(RexPage.TARGET)))

    def test_a_calm_dog_wears_no_mood_class(self):
        self.assertNotIn("rex-mood--", self.figure("calm"))

    def test_an_agitated_dog_paces_and_says_why(self):
        out = self.figure("agitated")
        self.assertIn("rex-mood--agitated", out)
        self.assertIn("REX - agitated", out)
        self.assertIn("CPU fell to 20% from about 60%", out)
        self.assertIn('class="rex-pace"', out)

    def test_an_uneasy_dog_is_named_uneasy_and_the_hover_explains(self):
        out = self.figure("restless")
        self.assertIn("rex-mood--restless", out)
        self.assertIn("REX - uneasy", out)
        self.assertIn("he paces to show he has noticed", out)

    def test_pacing_is_a_css_animation_switched_off_under_reduced_motion(self):
        text = page_text()
        self.assertIn("@keyframes rex-pace {", text)
        self.assertIn("@keyframes rex-pace-hard", text)
        self.assertIn(".rex-mood--agitated .rex-pace { animation: rex-pace-hard", text)
        self.assertIn("svg.flowgraph .rex-walker, svg.flowgraph .rex-walker * { animation: none !important", text)

    def test_the_view_config_carries_the_mood_settings(self):
        import rt_state
        view = rt_state.view_config(rt_state.load_config(SKILL))
        self.assertIsInstance(view["rex_baseline_polls"], int)
        for key in ("rex_restless_ratio", "rex_agitated_ratio", "rex_judged_percent"):
            self.assertIsInstance(view[key], (int, float))
        self.assertLess(view["rex_agitated_ratio"], view["rex_restless_ratio"])


class RexInTheAgentGraph(unittest.TestCase):

    def test_the_graph_widens_its_left_gutter_only_when_rex_is_drawn(self):
        self.assertIn("var colX = 300 + (rex ? REX_FIG.gutter : 0);", page_script())

    def test_rex_is_drawn_by_the_graph_level_with_the_agent_he_watches(self):
        body = re.search(r"function agentGraph\(.*?\n\}\n", page_script(), re.S).group(0)
        self.assertIn("rexFigure(rex, REX_FIG.cx, rexY, focus)", body)
        self.assertIn('t.lane || ("s:" + t.id)', body)
        self.assertIn("rowOf[laneOf(t)]", body)
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
