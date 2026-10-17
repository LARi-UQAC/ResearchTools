"""
test_collect_local - the `local_calls` snapshot section, read from the bridge log
(local coding contract, plan 6, task 2).

Offline. Every case writes a fixture log under a temporary home and injects `now` (R19, R21),
with fictitious plan paths (R34). The recurring assertion is the degradation contract of every
section here: a thing that cannot be answered is `unavailable` WITH ITS REASON, never a zero
and never a blank (R8, R11). The negative cases are the point: an old line with no role, a cut
last line, a log larger than the bounded tail, a plan path under the home directory.

Run:
    python .claude/skills/rt-observe/scripts/Test/test_collect_local.py
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_local  # noqa: E402
import rt_server  # noqa: E402
import rt_state  # noqa: E402

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
SHIPPED_CONFIG = Path(__file__).resolve().parents[2] / "observe-config.json"


def entry(value):
    """Wrap a value the way observe-config.json does."""
    return {"value": value, "provenance": "test fixture"}


def make_config(tail_bytes=100000, recent=3, active=60):
    """A fixture config carrying exactly the keys the collector reads."""
    return {"paths": {"bridge_log": entry("~/.claude/loop-bridge-log.jsonl")},
            "caps": {"local_calls_tail_bytes": entry(tail_bytes),
                     "local_calls_recent": entry(recent)},
            "staleness_seconds": {"local_active": entry(active),
                                  "local_generating_max": entry(1800)}}


def record(role="coder", at="2026-10-17T11:59:30+00:00", tag="vendor-a:9b", num_ctx=16384,
           plan=None, prompt_tokens=10, completion_tokens=5, accepted=True):
    """One enriched bridge log record."""
    return {"at": at, "role": role, "tag": tag, "num_ctx": num_ctx, "plan": plan,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "attempt": 1, "accepted": accepted}


class LogCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.log = self.home / ".claude" / "loop-bridge-log.jsonl"
        self.log.parent.mkdir(parents=True)

    def write(self, lines, tail=""):
        """Write records (dicts or raw strings) as lines, plus an unterminated tail."""
        text = "\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines)
        self.log.write_text(text + ("\n" if lines else "") + tail, encoding="utf-8")

    def collect(self, config=None):
        return collect_local.collect(config or make_config(), self.home, NOW)


class TestRoles(LogCase):
    def test_roles_are_grouped_with_their_last_tag_window_and_totals(self):
        self.write([record(prompt_tokens=10, completion_tokens=5, at="2026-10-17T11:50:00+00:00"),
                    record(prompt_tokens=20, completion_tokens=None,
                           at="2026-10-17T11:55:00+00:00", tag="vendor-b:7b", num_ctx=8192),
                    record(prompt_tokens=30, completion_tokens=7),
                    record(role="session", num_ctx=262144, prompt_tokens=100,
                           completion_tokens=50, at="2026-10-17T11:00:00+00:00")])
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        coder = state["roles"]["coder"]
        self.assertEqual((coder["calls"], coder["prompt_tokens"], coder["completion_tokens"]),
                         (3, 60, 12))
        self.assertEqual(coder["last_at"], "2026-10-17T11:59:30+00:00")
        self.assertEqual((coder["tag"], coder["num_ctx"]), ("vendor-a:9b", 16384))
        self.assertEqual(state["roles"]["session"]["num_ctx"], 262144)
        self.assertEqual(sorted(state["roles"]), ["coder", "session"])
        for key in ("proven_by", "proven_at"):
            self.assertTrue(state[key])

    def test_a_role_younger_than_the_threshold_is_active_and_older_is_not(self):
        self.write([record(role="coder", at="2026-10-17T11:59:30+00:00"),
                    record(role="session", at="2026-10-17T11:00:00+00:00")])
        roles = self.collect()["roles"]
        self.assertTrue(roles["coder"]["active"])
        self.assertEqual(roles["coder"]["age_seconds"], 30)
        self.assertFalse(roles["session"]["active"])
        self.assertEqual(roles["session"]["age_seconds"], 3600)
        self.assertFalse(self.collect(make_config(active=30))["roles"]["coder"]["active"])

    def test_old_lines_without_a_role_are_skipped_and_counted_not_crashed(self):
        old = {"attempt": 1, "seed": 7, "accepted": True, "generation_s": 1.5}
        self.write([old, old, record(role=None), record(role="coder")])
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(sorted(state["roles"]), ["coder"])
        self.assertEqual(state["skipped_without_role"], 3)

    def test_a_cut_last_line_is_dropped(self):
        self.write([record(role="coder")], tail='{"role": "session", "at": "2026-10-17T11:')
        state = self.collect()
        self.assertEqual(sorted(state["roles"]), ["coder"])

    def test_only_the_bounded_tail_is_read(self):
        lines = [record(role="first", at="2026-10-17T10:00:00+00:00")]
        lines += [record(role="coder", plan="plans/plan%d.md" % i) for i in range(30)]
        self.write(lines)
        size = self.log.stat().st_size
        state = self.collect(make_config(tail_bytes=size // 3))
        self.assertNotIn("first", state["roles"])
        self.assertIn("coder", state["roles"])
        self.assertLess(state["roles"]["coder"]["calls"], 30)

    def test_recent_lists_the_last_calls_newest_first_and_is_capped(self):
        self.write([record(plan="plans/plan%d.md" % i, at="2026-10-17T11:5%d:00+00:00" % i)
                    for i in range(5)])
        recent = self.collect(make_config(recent=3))["recent"]
        self.assertEqual([r["plan"] for r in recent],
                         ["plans/plan4.md", "plans/plan3.md", "plans/plan2.md"])

    def test_a_plan_path_under_the_home_is_redacted(self):
        plan = str(self.home / "proj" / "plans" / "plan1.md")
        self.write([record(plan=plan)])
        state = self.collect()
        text = json.dumps(state)
        self.assertNotIn(str(self.home), text)
        self.assertNotIn(str(self.home).replace("\\", "/"), text)
        self.assertTrue(state["roles"]["coder"]["plan"].startswith("~"))
        self.assertTrue(state["recent"][0]["plan"].startswith("~"))


class TestGeneratingNow(LogCase):
    """R35 round 2: the bridge logs a generation only when it ENDS, so a role mid-generation
    read as idle. The bridge now logs a start record, and a role with a start newer than its
    last end is generating for up to the configured generation limit."""

    def start(self, at, role="coder"):
        return {"event": "start", "at": at, "role": role, "tag": "vendor-a:9b",
                "num_ctx": 16384, "plan": None}

    def test_a_start_newer_than_the_last_end_keeps_the_role_active_past_the_idle_window(self):
        self.write([record(at="2026-10-17T11:00:00+00:00"),
                    self.start("2026-10-17T11:50:00+00:00")])
        role = self.collect()["roles"]["coder"]
        self.assertTrue(role["active"])
        self.assertTrue(role["generating"])
        self.assertEqual(role["calls"], 1)  # a start record is not a call

    def test_a_start_older_than_the_generation_limit_is_a_dead_run_not_activity(self):
        self.write([record(at="2026-10-17T09:00:00+00:00"),
                    self.start("2026-10-17T10:00:00+00:00")])
        role = self.collect()["roles"]["coder"]
        self.assertFalse(role["active"])
        self.assertFalse(role["generating"])

    def test_an_end_after_the_start_clears_generating(self):
        self.write([self.start("2026-10-17T11:58:00+00:00"),
                    record(at="2026-10-17T11:59:30+00:00")])
        role = self.collect()["roles"]["coder"]
        self.assertFalse(role["generating"])
        self.assertTrue(role["active"])

    def test_a_failed_record_clears_generating_and_is_not_a_call(self):
        failed = {"event": "failed", "at": "2026-10-17T11:55:00+00:00", "role": "coder",
                  "tag": "vendor-a:9b", "error": "daemon is down"}
        self.write([record(at="2026-10-17T10:00:00+00:00"),
                    self.start("2026-10-17T11:50:00+00:00"), failed])
        role = self.collect()["roles"]["coder"]
        self.assertFalse(role["generating"])
        self.assertEqual(role["calls"], 1)
        self.assertEqual(role["last_at"], "2026-10-17T11:55:00+00:00")
        self.assertNotIn("failed", [r.get("event") for r in self.collect()["recent"]])

    def test_a_record_with_no_timestamp_keeps_the_last_valid_one(self):
        # R35 round 5: a null `at` overwrote a valid last_at, so the role read as never seen.
        nameless = record(at=None)
        failed = {"event": "failed", "role": "coder", "tag": "vendor-a:9b", "error": "down"}
        self.write([record(at="2026-10-17T11:59:00+00:00"), nameless, failed])
        role = self.collect()["roles"]["coder"]
        self.assertEqual(role["last_at"], "2026-10-17T11:59:00+00:00")
        self.assertEqual(role["age_seconds"], 60)

    def test_a_role_with_only_a_start_record_still_appears(self):
        self.write([self.start("2026-10-17T11:59:00+00:00", role="session")])
        self.assertIn("session", self.collect()["roles"])


class TestUnavailable(LogCase):
    def test_unavailable_reasons_name_the_cause(self):
        missing = self.collect()
        self.assertEqual(missing["status"], "unavailable")
        self.assertIn("not found", missing["reason"])
        self.log.write_text("", encoding="utf-8")
        self.assertIn("empty", self.collect()["reason"])
        self.write([{"attempt": 1, "accepted": True}])
        reason = self.collect()["reason"]
        self.assertIn("no record carries a role", reason)

    def test_a_missing_config_key_is_named_and_never_raises(self):
        config = make_config()
        del config["caps"]["local_calls_recent"]
        state = self.collect(config)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("local_calls_recent", state["reason"])


class TestRegistration(unittest.TestCase):
    def test_the_section_is_registered_and_has_its_ttl(self):
        builders = rt_state.section_builders(Path("."), Path("."), json.loads(
            SHIPPED_CONFIG.read_text(encoding="utf-8")))
        self.assertIn("local_calls", builders)
        self.assertEqual(rt_server.SECTION_TTL_KEY["local_calls"], "local_calls")
        shipped = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        for group, key in (("ttl_seconds", "local_calls"), ("caps", "local_calls_tail_bytes"),
                           ("caps", "local_calls_recent"),
                           ("staleness_seconds", "local_active"), ("paths", "bridge_log")):
            self.assertTrue(shipped[group][key]["provenance"], f"{group}.{key}")
            self.assertIn("value", shipped[group][key])


if __name__ == "__main__":
    unittest.main()
