"""Tests for daemon_graph.py - keyword extraction, repository resolution via
a vault project's `repo:` property, and the read-only `graphify query`
subprocess the voice-ask queue runs against it."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class ExtractKeywordsCase(unittest.TestCase):
    def test_returns_the_models_own_keywords_and_language(self):
        import daemon_graph
        reply = json.dumps({"keywords_en": ["vault", "lock", "daemon"],
                            "question_language": "fr"})
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value=reply):
            result = daemon_graph.extract_keywords(
                "pourquoi le verrou echoue", "a-tag", 16384, 5.0,
                max_keywords=12)
        self.assertEqual(result, {"keywords_en": ["vault", "lock", "daemon"],
                                  "question_language": "fr"})

    def test_truncates_to_max_keywords_in_the_models_own_order(self):
        import daemon_graph
        reply = json.dumps({"keywords_en": ["a", "b", "c"],
                            "question_language": "en"})
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value=reply):
            result = daemon_graph.extract_keywords(
                "question", "a-tag", 16384, 5.0, max_keywords=2)
        self.assertEqual(result["keywords_en"], ["a", "b"])

    def test_a_bridge_error_becomes_graph_refused(self):
        import daemon_graph
        with mock.patch(
                "daemon_graph.daemon_states.call_model",
                side_effect=daemon_graph.daemon_states.ob.BridgeError(
                    "model down")):
            with self.assertRaises(daemon_graph.GraphRefused) as caught:
                daemon_graph.extract_keywords(
                    "question", "a-tag", 16384, 5.0, max_keywords=12)
        self.assertIn("model down", str(caught.exception))

    def test_a_non_json_reply_is_refused(self):
        import daemon_graph
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value="not json at all"):
            with self.assertRaises(daemon_graph.GraphRefused) as caught:
                daemon_graph.extract_keywords(
                    "question", "a-tag", 16384, 5.0, max_keywords=12)
        self.assertIn("not JSON", str(caught.exception))

    def test_an_empty_keyword_list_is_refused(self):
        import daemon_graph
        reply = json.dumps({"keywords_en": [], "question_language": "fr"})
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value=reply):
            with self.assertRaises(daemon_graph.GraphRefused) as caught:
                daemon_graph.extract_keywords(
                    "question", "a-tag", 16384, 5.0, max_keywords=12)
        self.assertIn("no keywords", str(caught.exception))

    def test_a_language_outside_the_schema_is_refused(self):
        import daemon_graph
        reply = json.dumps({"keywords_en": ["x"], "question_language": "de"})
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value=reply):
            with self.assertRaises(daemon_graph.GraphRefused) as caught:
                daemon_graph.extract_keywords(
                    "question", "a-tag", 16384, 5.0, max_keywords=12)
        self.assertIn("de", str(caught.exception))

    def test_the_call_uses_the_keywords_schema_and_carries_the_question(self):
        import daemon_graph
        reply = json.dumps({"keywords_en": ["x"], "question_language": "en"})
        with mock.patch("daemon_graph.daemon_states.call_model",
                        return_value=reply) as call:
            daemon_graph.extract_keywords(
                "a very specific question", "a-tag", 16384, 5.0,
                max_keywords=12)
        args, kwargs = call.call_args
        self.assertIn("a very specific question", args[0])
        self.assertEqual(kwargs.get("fmt"), daemon_graph.keywords_schema())


class EntityRepoCase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "graphify-out").mkdir()
        (self.repo / "graphify-out" / "graph.json").write_text(
            "{}", encoding="utf-8")
        proj = self.vault / "10_Projets" / "Logiciels" / "DemoRepo"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            f"---\nrepo: {self.repo}\ntype: logiciel\n---\n\nbody\n",
            encoding="utf-8")
        (proj / "some-note.md").write_text("note body\n", encoding="utf-8")
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        (self.vault / "30_Ressources" / "Python" / "orphan.md").write_text(
            "orphan note, no project above it\n", encoding="utf-8")
        self.roots = ["30_Ressources", "10_Projets"]

    def _hit(self, rel):
        return {"rel": rel, "score": 1, "excerpt": ""}

    def test_resolves_a_note_inside_the_project_folder(self):
        import daemon_graph
        hits = [self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertEqual(result["entity"], "DemoRepo")
        self.assertEqual(Path(result["repo"]), self.repo)

    def test_an_orphan_note_with_no_project_above_it_is_not_an_exception(self):
        import daemon_graph
        hits = [self._hit("30_Ressources/Python/orphan.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("repo:", result["reason"])

    def test_a_repo_pointing_nowhere_names_the_reason(self):
        import daemon_graph
        proj = self.vault / "10_Projets" / "Logiciels" / "Ghost"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            "---\nrepo: C:\\does\\not\\exist\\anywhere\n---\n\nbody\n",
            encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/Ghost/note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("does not exist", result["reason"])

    def test_a_repo_with_no_graph_names_the_reason(self):
        import daemon_graph
        no_graph_repo = Path(tempfile.mkdtemp())
        proj = self.vault / "10_Projets" / "Logiciels" / "NoGraph"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            f"---\nrepo: {no_graph_repo}\n---\n\nbody\n", encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/NoGraph/note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("no graph", result["reason"])

    def test_a_relative_repo_path_is_rejected_as_not_absolute(self):
        import daemon_graph
        proj = self.vault / "10_Projets" / "Logiciels" / "Rel"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            "---\nrepo: ..\\Rel\n---\n\nbody\n", encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/Rel/note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("not absolute", result["reason"])

    def test_tries_hits_in_order_and_returns_the_first_resolving_one(self):
        import daemon_graph
        hits = [self._hit("30_Ressources/Python/orphan.md"),
                self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertEqual(result["entity"], "DemoRepo")

    def test_no_hits_at_all(self):
        import daemon_graph
        result = daemon_graph.entity_repo(self.vault, [], self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("no vault hit", result["reason"])

    def test_read_repo_property_on_a_frontmatter_less_file_is_none(self):
        import daemon_graph
        p = self.vault / "plain.md"
        p.write_text("no frontmatter here\n", encoding="utf-8")
        self.assertIsNone(daemon_graph.read_repo_property(p))

    def test_read_repo_property_on_a_missing_file_is_none(self):
        import daemon_graph
        self.assertIsNone(
            daemon_graph.read_repo_property(self.vault / "absent.md"))


class QueryGraphCase(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "graphify-out").mkdir()
        (self.repo / "graphify-out" / "graph.json").write_text(
            "{}", encoding="utf-8")

    def test_missing_binary_never_spawns_a_process(self):
        import daemon_graph
        with mock.patch("daemon_graph.shutil.which", return_value=None), \
                mock.patch("daemon_graph.subprocess.run") as run:
            result = daemon_graph.query_graph(
                self.repo, ["vault", "lock"], 1500, 4000, 20.0)
        self.assertIsNone(result["text"])
        self.assertIn("not found", result["reason"])
        self.assertFalse(run.called)

    def test_a_successful_run_returns_text_and_built(self):
        import daemon_graph
        fake = mock.Mock(returncode=0, stdout="some graph output", stderr="")
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=fake) as run:
            result = daemon_graph.query_graph(
                self.repo, ["vault", "lock"], 1500, 4000, 20.0)
        self.assertEqual(result["text"], "some graph output")
        self.assertIsNotNone(result["built"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["/usr/bin/graphify", "query",
                                   "vault lock", "--budget", "1500"])
        self.assertEqual(kwargs["cwd"], self.repo)
        self.assertEqual(kwargs["timeout"], 20.0)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs.get("text"), True)
        self.assertEqual(kwargs.get("errors"), "replace")

    def test_a_timeout_names_the_configured_value(self):
        import daemon_graph
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          side_effect=subprocess.TimeoutExpired(
                              cmd="graphify", timeout=20.0)):
            result = daemon_graph.query_graph(
                self.repo, ["x"], 1500, 4000, 20.0)
        self.assertIsNone(result["text"])
        self.assertIn("timed out", result["reason"])
        self.assertIn("20", result["reason"])

    def test_a_nonzero_exit_names_the_tail_of_stderr(self):
        import daemon_graph
        import outbox_io
        stderr = "Traceback (most recent call last):\n" + "x" * 900 + \
            "\nRuntimeError: boom"
        fake = mock.Mock(returncode=1, stdout="", stderr=stderr)
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=fake):
            result = daemon_graph.query_graph(
                self.repo, ["x"], 1500, 4000, 20.0)
        self.assertIn(outbox_io.tail(stderr), result["reason"])
        self.assertNotIn("Traceback (most recent", result["reason"])

    def test_empty_output_names_no_output(self):
        import daemon_graph
        fake = mock.Mock(returncode=0, stdout="   ", stderr="")
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=fake):
            result = daemon_graph.query_graph(
                self.repo, ["x"], 1500, 4000, 20.0)
        self.assertIsNone(result["text"])
        self.assertIn("no output", result["reason"])

    def test_output_is_truncated_to_max_chars(self):
        import daemon_graph
        marker = "... (truncated at 10 chars)"
        stdout = marker + ("z" * 100)
        fake = mock.Mock(returncode=0, stdout=stdout, stderr="")
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=fake):
            result = daemon_graph.query_graph(
                self.repo, ["x"], 1500, len(marker) + 5, 20.0)
        self.assertEqual(len(result["text"]), len(marker) + 5)
        self.assertTrue(result["text"].startswith(marker))

    def test_argv_never_names_update_or_save_result(self):
        import daemon_graph
        fake = mock.Mock(returncode=0, stdout="x", stderr="")
        calls = []
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          side_effect=lambda *a, **kw: (
                              calls.append(a[0]), fake)[1]):
            daemon_graph.query_graph(self.repo, ["x", "y"], 1500, 4000, 20.0)
            daemon_graph.query_graph(self.repo, ["a"], 500, 100, 5.0)
        for argv in calls:
            self.assertNotIn("update", argv)
            self.assertNotIn("save-result", argv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
