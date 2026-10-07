"""Tests for daemon_ask.py, the vault daemon's read-only ask queue."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class DaemonConfigCase(unittest.TestCase):
    def test_ask_keys_are_declared_in_daemon_config(self):
        config_path = SCRIPTS.parent / "daemon-config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        daemon = config["daemon"]
        for key in ("ask_poll_interval_s", "ask_request_ttl_s",
                    "ask_max_vault_notes", "ask_note_excerpt_chars",
                    "ask_context_snapshot_max_chars", "ask_search_roots",
                    "ask_keywords_max", "ask_graph_budget_tokens",
                    "ask_graph_max_chars", "ask_graph_timeout_s",
                    "ask_graph_sentences"):
            self.assertIn(key, daemon, f"daemon-config.json is missing {key}")
        for outcome in ("skipped", "error"):
            for language in ("fr", "en"):
                self.assertIn(
                    language, daemon["ask_graph_sentences"][outcome],
                    f"ask_graph_sentences.{outcome} is missing {language}")


class ReadRequestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, payload):
        path = self.tmp / "req.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_a_well_formed_request(self):
        import daemon_ask
        path = self._write({
            "id": "abc123", "from": "rt-dashboard",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale",
            "context_snapshot": {"repo_green": "green"},
        })
        request = daemon_ask.read_request(path)
        self.assertEqual(request["question"], "is this repo stale")
        self.assertEqual(request["context_snapshot"]["repo_green"], "green")

    def test_refuses_a_request_not_from_rt_dashboard(self):
        import daemon_ask
        path = self._write({
            "id": "abc123", "from": "some-other-caller",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "anything",
        })
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_refuses_a_request_with_no_question(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00"})
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_refuses_unparsable_json(self):
        import daemon_ask
        path = self.tmp / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)

    def test_defaults_to_auto_when_language_is_absent(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00",
                            "question": "anything"})
        self.assertEqual(daemon_ask.read_request(path)["language"], "auto")

    def test_refuses_an_unsupported_language(self):
        import daemon_ask
        path = self._write({"id": "abc123", "from": "rt-dashboard",
                            "asked_at": "2026-09-26T12:00:00+00:00",
                            "question": "anything", "language": "de"})
        with self.assertRaises(daemon_ask.AskRefused):
            daemon_ask.read_request(path)


class SearchVaultCase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        (self.vault / "30_Ressources" / "Python" / "context-budget.md").write_text(
            "type: apprentissage\n\ncontext budget truncation was measured "
            "against Ollama num_ctx clamping silently.\n", encoding="utf-8")
        (self.vault / "30_Ressources" / "Python" / "unrelated.md").write_text(
            "type: apprentissage\n\nsomething about pip-audit and CVE scans.\n",
            encoding="utf-8")

    ROOTS = ["30_Ressources", "10_Projets"]

    def test_scores_the_note_sharing_more_keywords_higher(self):
        import daemon_ask
        hits = daemon_ask.search_vault(
            self.vault, "why does context budget truncation clamp num_ctx",
            max_notes=5, excerpt_chars=200, search_roots=self.ROOTS)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["rel"], "30_Ressources/Python/context-budget.md")

    def test_bounds_the_result_count(self):
        import daemon_ask
        for i in range(10):
            (self.vault / "30_Ressources" / "Python" / f"note{i}.md").write_text(
                "type: apprentissage\n\ncontext budget note number "
                f"{i}.\n", encoding="utf-8")
        hits = daemon_ask.search_vault(self.vault, "context budget",
                                       max_notes=3, excerpt_chars=200,
                                       search_roots=self.ROOTS)
        self.assertLessEqual(len(hits), 3)

    def test_no_vault_folder_returns_empty(self):
        import daemon_ask
        empty = Path(tempfile.mkdtemp())
        hits = daemon_ask.search_vault(empty, "anything", max_notes=5,
                                       excerpt_chars=200,
                                       search_roots=self.ROOTS)
        self.assertEqual(hits, [])

    def test_zero_overlap_scores_nothing(self):
        import daemon_ask
        hits = daemon_ask.search_vault(
            self.vault, "zzzznonexistentword qqqqanotherword",
            max_notes=5, excerpt_chars=200, search_roots=self.ROOTS)
        self.assertEqual(hits, [])

    def test_search_roots_are_config_driven_not_hardcoded(self):
        import daemon_ask
        hits = daemon_ask.search_vault(
            self.vault, "context budget truncation",
            max_notes=5, excerpt_chars=200, search_roots=["10_Projets"])
        self.assertEqual(hits, [])

    def test_tokenize_folds_accents_both_ways(self):
        import daemon_ask
        # "l'etat", no accent in the source: the word folds to itself, so
        # both spellings being present is a no-op here, but "etat" must be
        # the actual tokenized word (apostrophe is a separator).
        unaccented = daemon_ask._tokenize("Quel est l'etat du projet")
        self.assertIn("etat", unaccented)
        # "l'état", written WITH its real accent: the folded spelling
        # "etat" must be present too, so a question typed without accents
        # still overlaps a note that carries them.
        accented = daemon_ask._tokenize("l'état du système")
        self.assertIn("état", accented)
        self.assertIn("etat", accented)

    def test_a_named_folder_ranks_above_an_equal_scoring_hit(self):
        import daemon_ask
        (self.vault / "10_Projets" / "Logiciels" / "DemoRepo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "DemoRepo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        (self.vault / "10_Projets" / "Logiciels" / "OtherRepo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "OtherRepo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        hits = daemon_ask.search_vault(
            self.vault, "context budget note in DemoRepo",
            max_notes=5, excerpt_chars=200, search_roots=self.ROOTS)
        rels = [h["rel"] for h in hits]
        demo_idx = next(i for i, r in enumerate(rels) if "DemoRepo" in r)
        other_idx = next(i for i, r in enumerate(rels) if "OtherRepo" in r)
        self.assertLess(demo_idx, other_idx)

    def test_no_folder_named_leaves_order_unchanged(self):
        import daemon_ask
        (self.vault / "10_Projets" / "Logiciels" / "AlphaRepo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "AlphaRepo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        (self.vault / "10_Projets" / "Logiciels" / "BetaRepo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "BetaRepo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        hits = daemon_ask.search_vault(
            self.vault, "context budget note",
            max_notes=5, excerpt_chars=200, search_roots=self.ROOTS)
        rels = [h["rel"] for h in hits if "AlphaRepo" in h["rel"]
               or "BetaRepo" in h["rel"]]
        self.assertEqual(rels, sorted(rels))

    def test_folder_name_boost_reads_hyphen_or_underscore_as_space(self):
        import daemon_ask
        (self.vault / "10_Projets" / "Logiciels" / "Demo_Repo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "Demo_Repo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        (self.vault / "10_Projets" / "Logiciels" / "OtherRepo").mkdir(
            parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "OtherRepo" / "n.md"
         ).write_text("type: logiciel\n\ncontext budget note.\n",
                     encoding="utf-8")
        hits = daemon_ask.search_vault(
            self.vault, "context budget note in Demo Repo",
            max_notes=5, excerpt_chars=200, search_roots=self.ROOTS)
        rels = [h["rel"] for h in hits]
        demo_idx = next(i for i, r in enumerate(rels) if "Demo_Repo" in r)
        other_idx = next(i for i, r in enumerate(rels) if "OtherRepo" in r)
        self.assertLess(demo_idx, other_idx)


class GraphSentenceCase(unittest.TestCase):
    def setUp(self):
        self.config = {"daemon": {"ask_graph_sentences": {
            "skipped": {"fr": "Enfin, je n'ai pas trouvé de graph.",
                       "en": "Finally, I did not find a graph."},
            "error": {"fr": "Enfin, je n'ai pas pu consulter le graphe.",
                     "en": "Finally, I could not query the graph."},
        }}}

    def test_skipped_sentences(self):
        import daemon_ask
        self.assertEqual(
            daemon_ask.graph_sentence("skipped", "fr", self.config),
            "Enfin, je n'ai pas trouvé de graph.")
        self.assertEqual(
            daemon_ask.graph_sentence("skipped", "en", self.config),
            "Finally, I did not find a graph.")

    def test_error_sentences(self):
        import daemon_ask
        self.assertEqual(
            daemon_ask.graph_sentence("error", "fr", self.config),
            "Enfin, je n'ai pas pu consulter le graphe.")
        self.assertEqual(
            daemon_ask.graph_sentence("error", "en", self.config),
            "Finally, I could not query the graph.")

    def test_reads_from_config_not_a_literal(self):
        import daemon_ask
        config = {"daemon": {"ask_graph_sentences": {
            "skipped": {"fr": "autre phrase", "en": "another sentence"}}}}
        self.assertEqual(
            daemon_ask.graph_sentence("skipped", "fr", config),
            "autre phrase")

    def test_unknown_language_raises_config_error(self):
        import daemon_ask
        import outbox_io
        with self.assertRaises(outbox_io.ConfigError) as caught:
            daemon_ask.graph_sentence("skipped", "de", self.config)
        self.assertIn("de", str(caught.exception))


class AnswerCase(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        (self.vault / "30_Ressources" / "Python" / "note.md").write_text(
            "type: apprentissage\n\ncontext budget clamps num_ctx silently.\n",
            encoding="utf-8")
        self.config = {"daemon": {
            "ask_request_ttl_s": 90, "ask_max_vault_notes": 5,
            "ask_note_excerpt_chars": 1200,
            "ask_context_snapshot_max_chars": 4000,
            "ask_search_roots": ["30_Ressources", "10_Projets"],
            "ask_keywords_max": 12, "ask_graph_budget_tokens": 1500,
            "ask_graph_max_chars": 4000, "ask_graph_timeout_s": 20,
            "ask_graph_sentences": {
                "skipped": {"fr": "Enfin, je n'ai pas trouvé de graph.",
                           "en": "Finally, I did not find a graph."},
                "error": {"fr": "Enfin, je n'ai pas pu consulter le graphe.",
                         "en": "Finally, I could not query the graph."},
            }}}

    def _request(self, asked_at="2026-09-26T12:00:00+00:00"):
        return {"id": "abc123", "from": "rt-dashboard", "asked_at": asked_at,
                "question": "why does context budget clamp num_ctx",
                "context_snapshot": {"repo_green": "green"}}

    def test_answers_ok_with_the_model_reply(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="It clamps to avoid an oversized prompt."):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["status"], "ok")
        self.assertIn("clamps", result["answer_text"])
        self.assertIn("30_Ressources/Python/note.md",
                      result["sources"]["vault_notes"])

    def test_expires_a_stale_request(self):
        import daemon_ask
        result = daemon_ask.answer(
            self._request(asked_at="2026-09-26T10:00:00+00:00"),
            self.vault, "a-tag", 16384, 5.0, self.config,
            today="2026-09-26T12:00:00+00:00")
        self.assertEqual(result["status"], "expired")

    def test_reports_bridge_error_as_status_error(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=daemon_ask.daemon_states.ob.BridgeError(
                            "no qualified model")):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["status"], "error")
        self.assertIn("no qualified model", result["reason"])

    def test_truncates_an_oversized_context_snapshot(self):
        # captured as a LIST: the first call_model call is the vault
        # answer, whose prompt embeds the (truncated) snapshot; later
        # calls (keyword extraction) carry no snapshot at all and would
        # pass this assertion trivially, proving nothing.
        import daemon_ask
        big = {"repo_green": "x" * 10000}
        request = self._request()
        request["context_snapshot"] = big
        prompts = []

        def fake_call_model(prompt, *a, **kw):
            prompts.append(prompt)
            return "answer"

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake_call_model):
            daemon_ask.answer(request, self.vault, "a-tag", 16384, 5.0,
                              self.config, today="2026-09-26T12:00:03+00:00")
        self.assertLess(len(prompts[0]), 10500)

    def test_language_selection_reaches_the_prompt(self):
        # answer() now makes more than one call_model call (vault answer,
        # then the keyword extraction) - captured here as a LIST so the
        # test checks the first (vault) prompt, not whichever call
        # happened last.
        import daemon_ask
        request = self._request()
        request["language"] = "fr"
        prompts = []

        def fake_call_model(prompt, *a, **kw):
            prompts.append(prompt)
            return "reponse"

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake_call_model):
            daemon_ask.answer(request, self.vault, "a-tag", 16384, 5.0,
                              self.config, today="2026-09-26T12:00:03+00:00")
        self.assertIn("Reponds en francais", prompts[0])

    def test_survives_a_bare_date_today_against_an_aware_asked_at(self):
        # Production default (daemon_outbox.OutboxLayout, before this fix)
        # constructs `today` from date.today().isoformat() - a bare date,
        # no time, no tz - while asked_at is always a full aware ISO
        # datetime (voice_ask.write_ask_request). Subtracting an aware
        # datetime from a naive one raises TypeError, uncaught, which used
        # to kill the daemon on its first real ask request.
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="fine"):
            result = daemon_ask.answer(
                self._request(asked_at="2026-09-26T12:00:00+00:00"),
                self.vault, "a-tag", 16384, 5.0, self.config,
                today="2026-09-26")
        self.assertEqual(result["status"], "ok")


class GraphPartCase(unittest.TestCase):
    """answer()'s part 2: vault published first, then the matched
    project's code graph, or a stated reason it could not be reached."""

    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        proj = self.vault / "10_Projets" / "Logiciels" / "DemoRepo"
        proj.mkdir(parents=True)
        (proj / "note.md").write_text(
            "type: logiciel\n\ncontext budget clamps num_ctx silently.\n",
            encoding="utf-8")
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "graphify-out").mkdir()
        (self.repo / "graphify-out" / "graph.json").write_text(
            "{}", encoding="utf-8")
        (proj / "index.md").write_text(
            f"---\nrepo: {self.repo}\n---\n\nbody\n", encoding="utf-8")
        self.config = {"daemon": {
            "ask_request_ttl_s": 90, "ask_max_vault_notes": 5,
            "ask_note_excerpt_chars": 1200,
            "ask_context_snapshot_max_chars": 4000,
            "ask_search_roots": ["30_Ressources", "10_Projets"],
            "ask_keywords_max": 12, "ask_graph_budget_tokens": 1500,
            "ask_graph_max_chars": 4000, "ask_graph_timeout_s": 20,
            "ask_graph_sentences": {
                "skipped": {"fr": "Enfin, je n'ai pas trouvé de graph.",
                           "en": "Finally, I did not find a graph."},
                "error": {"fr": "Enfin, je n'ai pas pu consulter le graphe.",
                         "en": "Finally, I could not query the graph."},
            }}}

    def _request(self, language="auto"):
        return {"id": "abc123", "from": "rt-dashboard",
                "asked_at": "2026-09-26T12:00:00+00:00",
                "question": "why does DemoRepo clamp num_ctx",
                "language": language, "context_snapshot": {}}

    def _keywords_reply(self, language="en"):
        import json
        return json.dumps({"keywords_en": ["clamp", "num_ctx"],
                           "question_language": language})

    def test_happy_path_makes_three_calls_and_both_parts_ok(self):
        import daemon_ask
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "It clamps to avoid an oversized prompt."
            if len(calls) == 2:
                return self._keywords_reply()
            return "The code splits this into three functions."

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.shutil.which",
                          return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=mock.Mock(
                              returncode=0, stdout="three functions",
                              stderr="")):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["parts"]), 2)
        self.assertEqual(result["model_calls"], 3)
        self.assertEqual(result["sources"]["graph"]["status"], "ok")
        self.assertEqual(len(calls), 3)

    def test_publish_is_called_once_before_query_graph(self):
        import daemon_ask
        order = []
        publish_calls = []
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            order.append("call_model")
            if len(calls) == 1:
                return "vault answer text"
            return self._keywords_reply()

        def fake_publish(partial):
            publish_calls.append(partial)
            order.append("publish")

        def fake_query(*a, **kw):
            order.append("query_graph")
            return {"text": None, "reason": "no graph"}

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.query_graph",
                          side_effect=fake_query):
            daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00",
                publish=fake_publish)
        self.assertEqual(len(publish_calls), 1)
        self.assertEqual(publish_calls[0]["status"], "partial")
        self.assertEqual(len(publish_calls[0]["parts"]), 1)
        self.assertLess(order.index("publish"), order.index("query_graph"))

    def test_entity_repo_failure_is_skipped_not_error(self):
        import daemon_ask
        empty_vault = Path(tempfile.mkdtemp())
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "vault answer"
            return self._keywords_reply()

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.query_graph") as query:
            result = daemon_ask.answer(
                self._request(), empty_vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["parts"][1]["status"], "skipped")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("skipped", "en", self.config))
        self.assertFalse(query.called)

    def test_keyword_extraction_failure_is_error_not_skipped(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="vault answer, not JSON"), \
                mock.patch("daemon_graph.entity_repo") as entity, \
                mock.patch("daemon_graph.query_graph") as query:
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["parts"][1]["status"], "error")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("error", "fr", self.config))
        self.assertFalse(entity.called)
        self.assertFalse(query.called)

    def test_query_graph_failure_is_error_and_skips_the_second_answer_call(self):
        import daemon_ask
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "vault answer"
            return self._keywords_reply()

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.query_graph",
                          return_value={"text": None, "reason": "timed out"}):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["parts"][1]["status"], "error")
        self.assertEqual(len(calls), 2)

    def test_second_answer_call_bridge_error_is_error_not_the_raw_exception(self):
        import daemon_ask
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "vault answer"
            if len(calls) == 2:
                return self._keywords_reply()
            raise daemon_ask.daemon_states.ob.BridgeError("no qualified model")

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.query_graph",
                          return_value={"text": "some graph text",
                                       "built": None}):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(result["parts"][1]["status"], "error")
        # request language is "auto" and the keyword call succeeded with
        # question_language "en" (the default of _keywords_reply), so the
        # sentence follows that detection, per _graph_language's rule.
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("error", "en", self.config))
        self.assertNotIn("no qualified model", result["parts"][1]["text"])

    def test_second_prompt_carries_already_said_not_the_vault_excerpts(self):
        import daemon_ask
        (self.vault / "10_Projets" / "Logiciels" / "DemoRepo" / "note.md"
         ).write_text(
            "type: logiciel\n\na very distinctive vault excerpt marker "
            "ZQXJ clamps num_ctx silently.\n", encoding="utf-8")
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "vault answer mentions clamping"
            if len(calls) == 2:
                return self._keywords_reply()
            return "graph answer"

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.query_graph",
                          return_value={"text": "some graph text",
                                       "built": None}):
            daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
        self.assertIn("vault answer mentions clamping", calls[2])
        self.assertNotIn("ZQXJ", calls[2])
        self.assertIn("ZQXJ", calls[0])

    def test_language_fr_drives_the_graph_sentence(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="vault answer, not JSON"):
            result = daemon_ask.answer(
                self._request(language="fr"), self.vault, "a-tag", 16384,
                5.0, self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("error", "fr", self.config))

    def test_language_en_drives_the_graph_sentence(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="vault answer, not JSON"):
            result = daemon_ask.answer(
                self._request(language="en"), self.vault, "a-tag", 16384,
                5.0, self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("error", "en", self.config))

    def test_auto_language_follows_the_keyword_calls_own_detection(self):
        import daemon_ask
        empty_vault = Path(tempfile.mkdtemp())
        calls = []

        def fake(prompt, *a, **kw):
            calls.append(prompt)
            if len(calls) == 1:
                return "vault answer"
            return self._keywords_reply(language="fr")

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake):
            result = daemon_ask.answer(
                self._request(language="auto"), empty_vault, "a-tag",
                16384, 5.0, self.config,
                today="2026-09-26T12:00:03+00:00")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("skipped", "fr", self.config))

    def test_auto_language_defaults_to_french_on_a_failed_keyword_call(self):
        import daemon_ask
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="vault answer, not JSON"):
            result = daemon_ask.answer(
                self._request(language="auto"), self.vault, "a-tag", 16384,
                5.0, self.config, today="2026-09-26T12:00:03+00:00")
        self.assertEqual(
            result["parts"][1]["text"],
            daemon_ask.graph_sentence("error", "fr", self.config))

    def test_part1_failure_never_calls_publish_and_carries_no_parts_key(self):
        import daemon_ask
        published = []
        with mock.patch(
                "daemon_ask.daemon_states.call_model",
                side_effect=daemon_ask.daemon_states.ob.BridgeError("down")):
            result = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00",
                publish=lambda partial: published.append(partial))
        self.assertEqual(result["status"], "error")
        self.assertNotIn("parts", result)
        self.assertEqual(published, [])

    def test_a_second_requests_answer_survives_the_firsts_graph_timeout(self):
        # Review Focus: one request's graph part timing out must not
        # corrupt or block the request that follows it in the same poll.
        import subprocess
        import daemon_ask

        def fake(prompt, *a, **kw):
            if "keywords_en" not in prompt:
                return "vault answer"
            return self._keywords_reply()

        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=fake), \
                mock.patch("daemon_graph.shutil.which",
                          return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          side_effect=subprocess.TimeoutExpired(
                              cmd="graphify", timeout=20.0)):
            first = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:03+00:00")
            second = daemon_ask.answer(
                self._request(), self.vault, "a-tag", 16384, 5.0,
                self.config, today="2026-09-26T12:00:04+00:00")
        self.assertEqual(first["parts"][1]["status"], "error")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["parts"][1]["status"], "error")


class RunAskOnceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Python").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"
        (self.outbox / "ask" / "requests").mkdir(parents=True)
        (self.outbox / "ask" / "answers").mkdir(parents=True)
        self.config = {
            "lock": {"acquire_timeout_s": 1, "stale_after_s": 300,
                     "poll_interval_s": 0.01, "boot_skew_tolerance_s": 0},
            "probe": {"request_timeout_s": 5},
            "daemon": {"poll_interval_s": 0.01, "classify_confidence_min": 0.7,
                      "draft_max_attempts": 2, "drain_idle_s": 900,
                      "consolidate_top_n": 15, "judge_edge_max_pairs": 15,
                      "queue_max_entries": 500, "phantom_max_per_drain": 10,
                      "ask_poll_interval_s": 1, "ask_request_ttl_s": 90,
                      "ask_max_vault_notes": 5, "ask_note_excerpt_chars": 1200,
                      "ask_context_snapshot_max_chars": 4000,
                      "ask_search_roots": ["30_Ressources", "10_Projets"],
                      "ask_keywords_max": 12, "ask_graph_budget_tokens": 1500,
                      "ask_graph_max_chars": 4000, "ask_graph_timeout_s": 20,
                      "ask_graph_sentences": {
                          "skipped": {"fr": "Enfin, je n'ai pas trouvé de graph.",
                                     "en": "Finally, I did not find a graph."},
                          "error": {"fr": "Enfin, je n'ai pas pu consulter le graphe.",
                                   "en": "Finally, I could not query the graph."},
                      }},
        }
        import vault_daemon
        self.daemon = vault_daemon.VaultDaemon(
            self.vault, self.outbox, self.config, today="2026-09-26T12:00:00+00:00")

    def _request(self, name="abc123", from_="rt-dashboard"):
        path = self.outbox / "ask" / "requests" / f"{name}.json"
        path.write_text(json.dumps({
            "id": name, "from": from_,
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale", "context_snapshot": {}}),
            encoding="utf-8")
        return path

    def test_answers_a_valid_request_and_removes_it(self):
        self._request()
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="No, the suite is green."):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertFalse(
            (self.outbox / "ask" / "requests" / "abc123.json").exists())
        answer_path = self.outbox / "ask" / "answers" / "abc123.json"
        self.assertTrue(answer_path.exists())
        answer = json.loads(answer_path.read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "ok")

    def test_refused_request_still_gets_an_answer_file(self):
        self._request(from_="someone-else")
        self.daemon.run_ask_once("a-tag", 16384)
        answer = json.loads(
            (self.outbox / "ask" / "answers" / "abc123.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "refused")

    def test_a_malformed_request_does_not_block_a_good_one(self):
        (self.outbox / "ask" / "requests" / "bad.json").write_text(
            "{not json", encoding="utf-8")
        self._request(name="good1")
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="fine"):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "good1.json").exists())
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "bad.json").exists())

    def test_a_malicious_payload_id_cannot_escape_the_answers_dir(self):
        # R24: the answer file's identity comes from the REQUEST FILE'S OWN
        # name, never from the untrusted payload's declared "id" - the
        # request file's name is already constrained by the glob that found
        # it, the payload's "id" is not.
        path = self.outbox / "ask" / "requests" / "abc123.json"
        path.write_text(json.dumps({
            "id": "../../evil", "from": "rt-dashboard",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale", "context_snapshot": {}}),
            encoding="utf-8")
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="fine"):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "abc123.json").exists())
        self.assertFalse((self.tmp / "evil.json").exists())
        self.assertFalse((self.outbox / "evil.json").exists())

    def test_an_absent_payload_id_still_names_the_answer_after_the_request(self):
        path = self.outbox / "ask" / "requests" / "abc123.json"
        path.write_text(json.dumps({
            "from": "rt-dashboard",
            "asked_at": "2026-09-26T12:00:00+00:00",
            "question": "is this repo stale", "context_snapshot": {}}),
            encoding="utf-8")
        with mock.patch("daemon_ask.daemon_states.call_model",
                        return_value="fine"):
            self.daemon.run_ask_once("a-tag", 16384)
        self.assertTrue(
            (self.outbox / "ask" / "answers" / "abc123.json").exists())
        self.assertFalse((self.outbox / "ask" / "answers" / "None.json").exists())

    def test_an_orphaned_answer_older_than_the_ttl_is_pruned(self):
        import os
        answer_path = self.outbox / "ask" / "answers" / "orphan.json"
        answer_path.write_text('{"id": "orphan", "status": "ok"}',
                               encoding="utf-8")
        old = time.time() - (self.config["daemon"]["ask_request_ttl_s"] + 30)
        os.utime(answer_path, (old, old))
        self.daemon.run_ask_once("a-tag", 16384)
        self.assertFalse(answer_path.exists())

    def test_a_fresh_orphaned_answer_is_kept(self):
        answer_path = self.outbox / "ask" / "answers" / "fresh.json"
        answer_path.write_text('{"id": "fresh", "status": "ok"}',
                               encoding="utf-8")
        self.daemon.run_ask_once("a-tag", 16384)
        self.assertTrue(answer_path.exists())

    def test_a_model_resolution_failure_answers_every_waiting_request(self):
        """Measured 2026-09-26: the worktree lacked local-model-config.json,
        context_window() raised before run_ask_once ever ran, the daemon only
        printed it to its own console, and the dashboard sat on 'thinking'
        until its own timeout blamed a daemon that WAS running. The waiting
        caller must get the real reason instead."""
        self._request(name="q1")
        self._request(name="q2")

        def failing_resolve(role):
            raise RuntimeError("no state file at local-model-state.json")

        self.daemon.answer_pending_asks(
            "2026-09-26T12:00:05+00:00", resolve=failing_resolve)
        for name in ("q1", "q2"):
            answer = json.loads((self.outbox / "ask" / "answers" / f"{name}.json")
                                .read_text(encoding="utf-8"))
            self.assertEqual(answer["status"], "error")
            self.assertIn("local-model-state.json", answer["reason"])
            self.assertFalse(
                (self.outbox / "ask" / "requests" / f"{name}.json").exists())

    def test_a_window_lookup_failure_also_answers_the_request(self):
        self._request(name="q1")
        self.daemon.answer_pending_asks(
            "2026-09-26T12:00:05+00:00", resolve=lambda role: "a-tag",
            window_of=lambda tag: (_ for _ in ()).throw(
                KeyError("no retained_num_ctx for a-tag")))
        answer = json.loads((self.outbox / "ask" / "answers" / "q1.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "error")
        self.assertIn("retained_num_ctx", answer["reason"])

    def test_an_empty_queue_never_resolves_a_model(self):
        calls = []
        self.daemon.answer_pending_asks(
            "2026-09-26T12:00:05+00:00",
            resolve=lambda role: calls.append(role) or "a-tag")
        self.assertEqual(calls, [])

    def test_an_unexpected_exception_becomes_an_error_answer_not_a_crash(self):
        self._request(name="good1")
        with mock.patch("daemon_ask.daemon_states.call_model",
                        side_effect=RuntimeError("boom")):
            self.daemon.run_ask_once("a-tag", 16384)
        answer = json.loads(
            (self.outbox / "ask" / "answers" / "good1.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(answer["status"], "error")
        self.assertIn("boom", answer["reason"])


if __name__ == "__main__":
    unittest.main()
