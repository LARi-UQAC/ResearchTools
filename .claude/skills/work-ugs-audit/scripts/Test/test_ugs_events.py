"""
Offline tests of ugs_events: the action records a local role writes to the bridge log (plan 10, task 1, R11).

Every value is fictitious (R34). No file is opened, no model is called (R21).
Run as: python <this file>
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add the parent folder of the Test folder to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ugs_events

NOW = "2026-11-16T10:00:00.000+00:00"
ROLE = "ugs-grader"


class TestActionRecord(unittest.TestCase):

    def test_unknown_action_is_dropped(self):
        self.assertIsNone(ugs_events.action_record(ROLE, "fly", "Item A", NOW))

    def test_every_declared_action_is_kept(self):
        for action in ugs_events.ACTIONS:
            with self.subTest(action=action):
                self.assertIsNotNone(ugs_events.action_record(ROLE, action, "Item A", NOW))

    def test_target_with_a_path_separator_or_colon_is_dropped(self):
        for target in ("sub/grade.json", "sub\\grade.json", "..\\grade.json", "C:grade.json", "a:b"):
            with self.subTest(target=target):
                self.assertIsNone(ugs_events.action_record(ROLE, "write", target, NOW))

    def test_long_or_odd_target_is_dropped(self):
        self.assertIsNone(ugs_events.action_record(ROLE, "read", "x" * 41, NOW))
        self.assertIsNone(ugs_events.action_record(ROLE, "read", "", NOW))
        self.assertIsNone(ugs_events.action_record(ROLE, "read", "Item #3", NOW))
        self.assertIsNone(ugs_events.action_record(ROLE, "read", "Item\nB", NOW))

    def test_label_of_exactly_the_limit_is_kept(self):
        label = "x" * 40
        record = ugs_events.action_record(ROLE, "read", label, NOW)
        self.assertIsNotNone(record)
        self.assertEqual(record["target"], label)

    def test_accented_label_is_kept(self):
        self.assertIsNotNone(ugs_events.action_record(ROLE, "read", "Rédaction des résultats", NOW))

    def test_page_range_and_bare_file_name_are_kept(self):
        self.assertIsNotNone(ugs_events.action_record(ROLE, "read", "p12-15", NOW))
        self.assertIsNotNone(ugs_events.action_record(ROLE, "read", "p3-5,9", NOW))
        self.assertIsNotNone(ugs_events.action_record(ROLE, "write", "grade.json", NOW))

    def test_detail_is_allow_listed_too(self):
        self.assertIsNotNone(ugs_events.action_record(ROLE, "mark", "Item A", NOW, detail="x"))
        self.assertIsNotNone(ugs_events.action_record(ROLE, "read", "Item A", NOW, detail="p3-5"))
        self.assertIsNone(ugs_events.action_record(ROLE, "mark", "Item A", NOW, detail="sub/x"))
        self.assertIsNone(ugs_events.action_record(ROLE, "mark", "Item A", NOW, detail=""))

    def test_detail_none_is_allowed(self):
        record = ugs_events.action_record(ROLE, "call", "Item A", NOW, detail=None)
        self.assertIsNotNone(record)
        self.assertIsNone(record["detail"])

    def test_record_has_the_event_action_key_and_only_the_listed_keys(self):
        record = ugs_events.action_record(ROLE, "call", "Item A", NOW, report_id="R01", detail="x")
        self.assertEqual(record, {
            "event": "action",
            "at": NOW,
            "role": ROLE,
            "action": "call",
            "target": "Item A",
            "report_id": "R01",
            "detail": "x",
        })


class TestPageRange(unittest.TestCase):

    def test_page_range_is_compact(self):
        self.assertEqual(ugs_events.page_range([3, 4, 5, 9]), "p3-5,9")

    def test_single_page_and_pair(self):
        self.assertEqual(ugs_events.page_range([9]), "p9")
        self.assertEqual(ugs_events.page_range([1, 2]), "p1-2")

    def test_empty_list_gives_empty_string(self):
        self.assertEqual(ugs_events.page_range([]), "")

    def test_duplicates_and_unsorted_input(self):
        self.assertEqual(ugs_events.page_range([9, 3, 4, 5, 5]), "p3-5,9")

    def test_output_is_accepted_as_a_target(self):
        self.assertIsNotNone(ugs_events.action_record(ROLE, "read", ugs_events.page_range([3, 4, 9]), NOW))

    def test_page_below_one_is_refused(self):
        with self.assertRaises(ValueError):
            ugs_events.page_range([0])
        with self.assertRaises(ValueError):
            ugs_events.page_range([True])


class TestMakeEmitter(unittest.TestCase):

    def test_emitter_passes_a_record_to_the_log(self):
        log = MagicMock()
        emit = ugs_events.make_emitter(log, lambda: ROLE, lambda: NOW)
        emit("read", "p1-2")
        log.assert_called_once()
        record = log.call_args[0][0]
        self.assertEqual(record["action"], "read")
        self.assertEqual(record["role"], ROLE)
        self.assertEqual(record["at"], NOW)

    def test_refused_record_reaches_neither_log_nor_lost(self):
        log = MagicMock()
        emit = ugs_events.make_emitter(log, lambda: ROLE, lambda: NOW)
        emit("fly", "Item A")
        emit("read", "sub/x")
        log.assert_not_called()
        self.assertEqual(emit.lost, 0)

    def test_emitter_swallows_a_failing_log_and_counts(self):
        log = MagicMock(side_effect=RuntimeError("disk full"))
        emit = ugs_events.make_emitter(log, lambda: ROLE, lambda: NOW)
        emit("read", "Item A")  # must not raise
        emit("write", "grade.json")  # must not raise
        self.assertEqual(emit.lost, 2)

    def test_lost_counter_starts_at_zero_and_counts_only_failures(self):
        calls = {"n": 0}

        def flaky(record):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("locked")

        emit = ugs_events.make_emitter(flaky, lambda: ROLE, lambda: NOW)
        self.assertEqual(emit.lost, 0)
        emit("read", "Item A")
        emit("read", "Item B")
        emit("read", "Item C")
        self.assertEqual(emit.lost, 1)
        self.assertEqual(calls["n"], 3)

    def test_emitter_never_raises_when_the_clock_fails(self):
        emit = ugs_events.make_emitter(MagicMock(), lambda: ROLE, MagicMock(side_effect=ValueError("clock")))
        emit("read", "Item A")  # must not raise
        self.assertEqual(emit.lost, 1)


if __name__ == "__main__":
    unittest.main()
