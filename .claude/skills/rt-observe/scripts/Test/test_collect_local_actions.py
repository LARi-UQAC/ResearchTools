"""
test_collect_local_actions - the action records of a local role, in the `local_calls` section
(work-ugs-audit extraction fixes, plan 11, task 1).

A grading step writes one action record per page read, per item mark, per output file and per
model call (ugs_events.py). The collector lists them per role, oldest first, capped by
`caps.local_actions_per_role`, and never counts them as calls, starts or ends.

Offline. Every case writes a fictitious bridge log under a temporary home and injects `now`
(R19, R21). Test data is fictitious (R34). The negative cases are the point: an action is not a
call, an old line with no event key is still a call, a log with no action records is unchanged,
a missing cap is named, and a non-string target or detail is dropped rather than raised.

Run:
    python .claude/skills/rt-observe/scripts/Test/test_collect_local_actions.py
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_local  # noqa: E402

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
SHIPPED_CONFIG = Path(__file__).resolve().parents[2] / "observe-config.json"
CALL_KEYS = {"calls", "prompt_tokens", "completion_tokens", "last_at", "tag", "num_ctx",
             "plan", "age_seconds", "generating", "active"}


def entry(value):
    """Wrap a value the way observe-config.json does."""
    return {"value": value, "provenance": "test fixture"}


def make_config(actions=None):
    """A fixture config carrying the keys the collector reads; the action cap only when given."""
    caps = {"local_calls_tail_bytes": entry(100000), "local_calls_recent": entry(3)}
    if actions is not None:
        caps["local_actions_per_role"] = entry(actions)
    return {"paths": {"bridge_log": entry("~/.claude/loop-bridge-log.jsonl")},
            "caps": caps,
            "staleness_seconds": {"local_active": entry(60),
                                  "local_generating_max": entry(1800)}}


def record(role="coder", at="2026-10-17T11:59:30+00:00", tag="vendor-a:9b", num_ctx=16384,
           plan=None, prompt_tokens=10, completion_tokens=5):
    """One enriched call record, as the bridge writes it (no event key: an old-style call)."""
    return {"at": at, "role": role, "tag": tag, "num_ctx": num_ctx, "plan": plan,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "attempt": 1, "accepted": True}


def action(role="coder", at="2026-10-17T11:59:00+00:00", act="read", target="p12-15",
           report_id="R04", detail=None):
    """One action record, as ugs_events.action_record writes it."""
    return {"event": "action", "at": at, "role": role, "action": act, "target": target,
            "report_id": report_id, "detail": detail}


class LogCase(unittest.TestCase):
    """Writes the fixture log under a temporary home and collects from it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.log = self.home / ".claude" / "loop-bridge-log.jsonl"
        self.log.parent.mkdir(parents=True)

    def write(self, lines):
        """Write records (dicts) as JSON lines, oldest first."""
        self.log.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    def collect(self, config=None):
        """Collect the section from the fixture log."""
        return collect_local.collect(config or make_config(actions=20), self.home, NOW)


class TestActionsListed(LogCase):
    def test_actions_are_listed_per_role_oldest_first(self):
        self.write([record(at="2026-10-17T11:50:00+00:00"),
                    action(at="2026-10-17T11:51:00+00:00", act="read", target="p12-15"),
                    action(at="2026-10-17T11:52:00+00:00", act="mark", target="Analyse",
                           detail="done")])
        row = self.collect()["roles"]["coder"]
        self.assertEqual([a["action"] for a in row["actions"]], ["read", "mark"])
        self.assertEqual(row["actions"][0], {"at": "2026-10-17T11:51:00+00:00", "action": "read",
                                             "target": "p12-15", "report_id": "R04",
                                             "detail": None})
        self.assertEqual(row["actions"][1]["detail"], "done")
        self.assertEqual(row["actions_dropped"], 0)

    def test_actions_stay_with_their_own_role(self):
        self.write([record(role="coder"), record(role="session"),
                    action(role="coder", target="p1"), action(role="session", target="p9")])
        roles = self.collect()["roles"]
        self.assertEqual([a["target"] for a in roles["coder"]["actions"]], ["p1"])
        self.assertEqual([a["target"] for a in roles["session"]["actions"]], ["p9"])

    def test_a_role_with_no_action_in_a_log_that_has_some_gets_an_empty_list(self):
        self.write([record(role="coder"), action(role="session", target="p2")])
        row = self.collect()["roles"]["coder"]
        self.assertEqual(row["actions"], [])
        self.assertEqual(row["actions_dropped"], 0)


class TestActionIsNotACall(LogCase):
    def test_action_is_not_a_call_and_does_not_move_last_at(self):
        self.write([record(at="2026-10-17T11:50:00+00:00"),
                    action(at="2026-10-17T11:59:00+00:00")])
        row = self.collect()["roles"]["coder"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["prompt_tokens"], 10)
        self.assertEqual(row["last_at"], "2026-10-17T11:50:00+00:00")

    def test_action_is_not_a_start_and_does_not_end_a_generation(self):
        start = {"event": "start", "at": "2026-10-17T11:50:00+00:00", "role": "coder",
                 "tag": "vendor-a:9b", "num_ctx": 16384, "plan": None}
        self.write([start, action(at="2026-10-17T11:55:00+00:00")])
        row = self.collect()["roles"]["coder"]
        self.assertTrue(row["generating"])
        self.assertEqual(row["calls"], 0)

    def test_an_old_line_with_no_event_key_is_still_a_call(self):
        self.write([record(role="coder"), action(role="coder", target="p3")])
        row = self.collect()["roles"]["coder"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(len(row["actions"]), 1)

    def test_a_role_with_only_actions_appears_with_no_calls(self):
        self.write([action(role="coder", target="p4")])
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        row = state["roles"]["coder"]
        self.assertEqual(row["calls"], 0)
        self.assertFalse(row["active"])
        self.assertEqual([a["target"] for a in row["actions"]], ["p4"])


class TestCap(LogCase):
    def test_cap_keeps_the_newest_and_counts_the_dropped(self):
        self.write([record()] + [action(target="p%d" % i, at="2026-10-17T11:5%d:00+00:00" % i)
                                 for i in range(5)])
        row = self.collect(make_config(actions=3))["roles"]["coder"]
        self.assertEqual([a["target"] for a in row["actions"]], ["p2", "p3", "p4"])
        self.assertEqual(row["actions_dropped"], 2)
        self.assertIs(type(row["actions_dropped"]), int)

    def test_a_cap_that_is_not_a_positive_integer_is_named(self):
        self.write([action()])
        for bad in (0, -1, "3", True):
            state = self.collect(make_config(actions=bad))
            self.assertEqual(state["status"], "unavailable", bad)
            self.assertIn("local_actions_per_role", state["reason"], bad)


class TestUnchangedWithoutActions(LogCase):
    def test_log_without_actions_is_unchanged_and_needs_no_cap(self):
        self.write([record(role="coder"), record(role="session", num_ctx=262144)])
        state = self.collect(make_config(actions=None))
        self.assertEqual(state["status"], "ok")
        self.assertEqual(set(state["roles"]["coder"]), CALL_KEYS)
        self.assertNotIn("actions", json.dumps(state["roles"]))
        self.assertNotIn("actions_dropped", json.dumps(state["roles"]))


class TestMissingCap(LogCase):
    def test_missing_cap_key_is_named_with_its_file(self):
        self.write([record(), action()])
        state = self.collect(make_config(actions=None))
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("caps.local_actions_per_role", state["reason"])
        self.assertIn("observe-config.json", state["reason"])


class TestMalformedActions(LogCase):
    def test_a_non_string_target_or_detail_is_dropped_never_raised(self):
        self.write([record(), action(target=None), action(target="p5", detail=7),
                    action(target="p6", detail="done")])
        state = self.collect()
        self.assertEqual(state["status"], "ok")
        self.assertEqual([a["target"] for a in state["roles"]["coder"]["actions"]], ["p6"])


class TestRedaction(LogCase):
    def test_a_path_inside_an_action_is_redacted(self):
        path = str(self.home / "proj" / "notes.md")
        self.write([record(), action(detail=path)])
        state = self.collect()
        text = json.dumps(state)
        self.assertNotIn(str(self.home), text)
        self.assertNotIn(str(self.home).replace("\\", "/"), text)
        self.assertTrue(state["roles"]["coder"]["actions"][0]["detail"].startswith("~"))

    def test_a_target_is_an_identifier_passed_through_unchanged(self):
        self.write([record(), action(target="p12-15")])
        self.assertEqual(self.collect()["roles"]["coder"]["actions"][0]["target"], "p12-15")


class TestShippedConfig(unittest.TestCase):
    def test_the_shipped_config_declares_the_cap_with_provenance(self):
        shipped = json.loads(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        cap = shipped["caps"]["local_actions_per_role"]
        self.assertIsInstance(cap["value"], int)
        self.assertGreater(cap["value"], 0)
        self.assertTrue(cap["provenance"])


if __name__ == "__main__":
    unittest.main()
