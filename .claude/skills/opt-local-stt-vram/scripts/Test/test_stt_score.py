"""Scoring of the STT benchmark: transcript error, live-caption speed, the LLM VRAM gate.

Offline and pure: no model, no GPU, no network. The regression case replays the real
measurements of 2026-09-26 (Test/fixtures/session_2026_09_26.json) and must reproduce the
table the operator chose from, so a change to the scoring rule shows up as a changed verdict
rather than as a silently different number.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import stt_score  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "session_2026_09_26.json")
                     .read_text(encoding="utf-8"))
CONFIG = {
    "live_budget_ms": {"value": 1000},
    "gate": {"max_llm_demoted_pct": {"value": 10}},
    "weights": {"accuracy": {"value": 0.5}, "speed": {"value": 0.5}},
}


def raw(candidates=None):
    report = copy.deepcopy({k: v for k, v in FIXTURE.items() if k != "reference"})
    if candidates is not None:
        report["candidates"] = candidates
    return report


class NormalizeCase(unittest.TestCase):
    def test_decimal_comma_equals_point(self):
        self.assertEqual(stt_score.normalize("0,5 rad"), stt_score.normalize("0.5 rad"))

    def test_case_punctuation_and_apostrophe_are_ignored(self):
        self.assertEqual(stt_score.normalize("J’accepte."), "j'accepte")
        self.assertEqual(stt_score.normalize("Ensuite, avance."), "ensuite avance")

    def test_accents_are_kept(self):
        """'mètre' and 'metre' are different words to a French reader."""
        self.assertNotEqual(stt_score.normalize("mètre"), stt_score.normalize("metre"))


class EditsCase(unittest.TestCase):
    def test_identical_has_no_edit(self):
        self.assertEqual(stt_score.edits(["a", "b"], ["a", "b"]), (0, []))

    def test_substitution_deletion_insertion_are_named(self):
        dist, found = stt_score.edits(["a", "rad", "c"], ["a", "grades", "c", "d"])
        self.assertEqual(dist, 2)
        self.assertEqual(found, ["rad->grades", "(extra)->d"])
        dist, found = stt_score.edits(["a", "b"], ["a"])
        self.assertEqual((dist, found), (1, ["b->(missing)"]))


class TranscriptErrorCase(unittest.TestCase):
    def test_micro_average_over_recordings(self):
        refs = {"x": "un deux trois quatre", "y": "cinq six"}
        texts = {"x": "un deux trois quatre", "y": "cinq sept"}
        err = stt_score.transcript_error(refs, texts)
        self.assertAlmostEqual(err["wer_pct"], 100 * 1 / 6, places=2)
        self.assertEqual(err["word_errors"], ["six->sept"])

    def test_a_recording_with_no_transcript_counts_every_word_wrong(self):
        err = stt_score.transcript_error({"x": "un deux"}, {})
        self.assertEqual(err["wer_pct"], 100.0)

    def test_an_empty_reference_is_refused(self):
        with self.assertRaises(ValueError):
            stt_score.transcript_error({"x": " . "}, {"x": "bonjour"})


class ScoreCase(unittest.TestCase):
    def test_the_session_table_is_reproduced(self):
        scored = stt_score.score_report(raw(), FIXTURE["reference"], CONFIG)
        by = {r["model"]: r for r in scored}
        self.assertEqual([r["model"] for r in scored],
                         ["large-v3-turbo", "small", "medium", "large-v3"])
        self.assertAlmostEqual(by["large-v3-turbo"]["score"], 98.75, places=2)
        self.assertAlmostEqual(by["small"]["score"], 95.0, places=2)
        self.assertAlmostEqual(by["medium"]["score"], 86.6, places=1)
        self.assertEqual(by["large-v3"]["status"], "gated")
        self.assertNotIn("score", by["large-v3"])
        self.assertEqual(by["large-v3-turbo"]["word_errors"], ["rad->grades"])

    def test_speed_is_full_inside_the_budget_and_proportional_outside(self):
        scored = {r["model"]: r for r in stt_score.score_report(raw(), FIXTURE["reference"], CONFIG)}
        self.assertEqual(scored["small"]["speed"], 100.0)
        self.assertAlmostEqual(scored["medium"]["speed"], 100 * 1.0 / 1.24, places=1)

    def test_the_gate_names_the_demoted_share(self):
        gated = [r for r in stt_score.score_report(raw(), FIXTURE["reference"], CONFIG)
                 if r["status"] == "gated"][0]
        self.assertIn("24.0%", gated["reason"])
        loose = copy.deepcopy(CONFIG)
        loose["gate"]["max_llm_demoted_pct"]["value"] = 30
        statuses = {r["model"]: r["status"]
                    for r in stt_score.score_report(raw(), FIXTURE["reference"], loose)}
        self.assertEqual(statuses["large-v3"], "ranked")

    def test_a_failed_candidate_is_not_runnable_and_never_scored(self):
        rows = raw()["candidates"] + [{"engine": "faster-whisper", "model": "ghost",
                                       "compute_type": "int8", "error": "download refused"}]
        scored = stt_score.score_report(raw(rows), FIXTURE["reference"], CONFIG)
        last = scored[-1]
        self.assertEqual((last["model"], last["status"]), ("ghost", "not runnable"))
        self.assertEqual(last["reason"], "download refused")
        self.assertNotIn("score", last)

    def test_weights_must_sum_to_one(self):
        bad = copy.deepcopy(CONFIG)
        bad["weights"]["speed"]["value"] = 0.7
        with self.assertRaises(ValueError):
            stt_score.score_report(raw(), FIXTURE["reference"], bad)

    def test_a_missing_config_key_is_named(self):
        bad = copy.deepcopy(CONFIG)
        del bad["gate"]
        with self.assertRaises(KeyError) as ctx:
            stt_score.score_report(raw(), FIXTURE["reference"], bad)
        self.assertIn("gate", str(ctx.exception))


class TableCase(unittest.TestCase):
    def test_the_table_lists_winner_first_and_explains_every_unranked_row(self):
        rows = raw()["candidates"] + [{"engine": "faster-whisper", "model": "ghost",
                                       "compute_type": "int8", "error": "download refused"}]
        scored = stt_score.score_report(raw(rows), FIXTURE["reference"], CONFIG)
        table = stt_score.render_table(scored)
        lines = [ln for ln in table.splitlines() if ln.startswith("|")]
        self.assertIn("large-v3-turbo", lines[2])
        self.assertIn("98.8", lines[2])
        self.assertIn("gated", table)
        self.assertIn("download refused", table)


if __name__ == "__main__":
    unittest.main()
