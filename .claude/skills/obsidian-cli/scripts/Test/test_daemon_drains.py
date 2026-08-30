"""
test_daemon_drains - offline checks for the deferred half of the vault daemon.

No model, no subprocess, no real vault: the bridge's network boundary and the
candidate computation are both patched, and the vault is a fixture tree. The
case that matters most is the REJECTION: a drain that accepts nearly every pair
builds a hairball, which looks healthier than disconnection while being worse.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dd = _load("daemon_drains")

WINDOW = 16384
TAG = "a-tag-from-the-resolver"
CONFIG = {"probe": {"request_timeout_s": 5},
          "daemon": {"consolidate_top_n": 15, "judge_edge_max_pairs": 15}}
A = "30_Ressources/Ollama/a.md"
B = "30_Ressources/Python/b.md"


def verdict(shares, mechanism="", sentence=""):
    return {"response": json.dumps({"shares_mechanism": shares,
                                    "mechanism": mechanism,
                                    "sentence": sentence})}


class DrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        self.journal = self.tmp / "vault-journal.jsonl"
        for rel in (A, B):
            path = self.vault / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {Path(rel).stem}\n\nun contenu.\n", encoding="utf-8")

    def _drain(self, responses, pairs=None):
        pairs = pairs if pairs is not None else [{"a": A, "b": B, "score": 4.2}]
        with mock.patch.object(dd, "candidate_pairs", return_value=pairs):
            with mock.patch.object(dd.ob, "_post_generate", side_effect=responses):
                return dd.drain_consolidation(self.vault, TAG, WINDOW, CONFIG,
                                              self.journal, None)

    def test_a_shared_mechanism_links_both_notes_reciprocally(self):
        report = self._drain([verdict(True, "un outil qui rend 0 en echec",
                                      "Les deux notes decrivent un outil qui rend 0 alors que rien n a ete ecrit.")])
        self.assertEqual(len(report["accepted"]), 1)
        self.assertIn("[[b]]", (self.vault / A).read_text(encoding="utf-8"))
        self.assertIn("[[a]]", (self.vault / B).read_text(encoding="utf-8"))

    def test_the_edge_carries_its_sentence_not_a_bare_link(self):
        sentence = "Les deux notes partagent le meme mode de defaillance."
        self._drain([verdict(True, "meme mode de defaillance", sentence)])
        self.assertIn(sentence, (self.vault / A).read_text(encoding="utf-8"))

    def test_a_topic_only_pair_is_rejected_with_its_reason(self):
        """Rejections are the valuable output. Sharing a tag is not a mechanism."""
        report = self._drain([verdict(False, "meme tag defaut-muet")])
        self.assertEqual(report["accepted"], [])
        self.assertEqual(len(report["rejected"]), 1)
        self.assertIn("defaut-muet", report["rejected"][0]["why"])
        self.assertNotIn("[[b]]", (self.vault / A).read_text(encoding="utf-8"))

    def test_an_acceptance_with_no_sentence_is_rejected(self):
        report = self._drain([verdict(True, "un mecanisme", "")])
        self.assertEqual(report["accepted"], [])
        self.assertIn("no sentence", report["rejected"][0]["why"])

    def test_both_edges_are_journalled(self):
        self._drain([verdict(True, "m", "Une phrase de justification.")])
        states = [json.loads(line)["state"] for line
                  in self.journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(states, ["PENDING", "EDGE", "PENDING", "EDGE"])

    def test_a_second_drain_does_not_double_an_existing_edge(self):
        payload = [verdict(True, "m", "Une phrase.")]
        self._drain(payload)
        size = (self.vault / A).stat().st_size
        report = self._drain([verdict(True, "m", "Une phrase.")])
        self.assertEqual((self.vault / A).stat().st_size, size)
        self.assertEqual(report["accepted"][0]["written"], [False, False])

    def test_an_unparsable_verdict_is_an_error_not_an_acceptance(self):
        report = self._drain([{"response": "I think they are related."}])
        self.assertEqual(report["accepted"], [])
        self.assertEqual(len(report["errors"]), 1)

    def test_a_missing_note_is_not_written_and_does_not_raise(self):
        (self.vault / B).unlink()
        report = self._drain([verdict(True, "m", "Une phrase.")])
        self.assertEqual(report["accepted"][0]["written"], [True, False])

    def test_the_pair_count_is_bounded(self):
        pairs = [{"a": A, "b": B} for _ in range(50)]
        config = {"probe": {"request_timeout_s": 5},
                  "daemon": {"consolidate_top_n": 15, "judge_edge_max_pairs": 2}}
        with mock.patch.object(dd, "candidate_pairs", return_value=pairs):
            with mock.patch.object(dd.ob, "_post_generate",
                                   side_effect=[verdict(False, "x")] * 2) as post:
                dd.drain_consolidation(self.vault, TAG, WINDOW, config,
                                       None, None)
        self.assertEqual(post.call_count, 2)

    def test_the_judged_prompt_carries_both_notes_and_asks_for_a_schema(self):
        with mock.patch.object(dd.ob, "_post_generate",
                               return_value=verdict(False, "x")) as post:
            dd.judge_edge(self.vault, {"a": A, "b": B}, TAG, WINDOW, 5.0, 3000)
        payload = post.call_args[0][0]
        self.assertEqual(payload["format"], dd.EDGE_SCHEMA)
        self.assertIn(A, payload["prompt"])
        self.assertIn(B, payload["prompt"])

    def test_graphify_is_skipped_without_a_graph_directory(self):
        report = dd.drain_graphify([A], self.tmp, 5.0)
        self.assertIn("no graphify-out", report["skipped"])

    def test_graphify_is_skipped_on_an_empty_queue(self):
        self.assertIn("nothing queued", dd.drain_graphify([], self.tmp, 5.0)["skipped"])

    def test_a_failing_candidate_computation_is_refused_not_guessed(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch.object(dd.subprocess, "run", return_value=completed):
            with self.assertRaises(dd.ds.EventRefused):
                dd.candidate_pairs(self.vault, 15, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
