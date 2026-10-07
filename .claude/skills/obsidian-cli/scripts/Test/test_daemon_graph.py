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
        self.allowed_roots = [self.repo.resolve()]

    def _hit(self, rel):
        return {"rel": rel, "score": 1, "excerpt": ""}

    def test_resolves_a_note_inside_the_project_folder(self):
        import daemon_graph
        hits = [self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots,
                                          self.allowed_roots)
        self.assertEqual(result["entity"], "DemoRepo")
        self.assertEqual(Path(result["repo"]), self.repo)

    def test_an_orphan_note_with_no_project_above_it_is_not_an_exception(self):
        import daemon_graph
        hits = [self._hit("30_Ressources/Python/orphan.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertIsNone(result["entity"])
        self.assertIn("repo:", result["reason"])

    def test_a_repo_pointing_nowhere_names_the_reason(self):
        """The ghost path is deliberately ADDED to the allowlist, so the
        reason asserted is the existence check, not the allowlist refusal -
        an allowlisted root can still be absent (removed, or misconfigured),
        and that case must still be distinguishable.

        PR #49 third re-review: a literal Windows-style string
        (r"C:\\does\\not\\exist\\anywhere") is not absolute on POSIX, so this
        test failed there with "is not absolute" instead of "does not
        exist". Built from tempfile.mkdtemp() plus a child name that is
        never created, so the path is absolute AND nonexistent on every
        platform the suite runs on (R21 spirit)."""
        import daemon_graph
        ghost = Path(tempfile.mkdtemp()) / "never-created"
        proj = self.vault / "10_Projets" / "Logiciels" / "Ghost"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            f"---\nrepo: {ghost}\n---\n\nbody\n", encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/Ghost/note.md")]
        result = daemon_graph.entity_repo(
            self.vault, hits, self.roots, self.allowed_roots + [ghost.resolve()])
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
        result = daemon_graph.entity_repo(
            self.vault, hits, self.roots,
            self.allowed_roots + [no_graph_repo.resolve()])
        self.assertIsNone(result["entity"])
        self.assertIn("no graph", result["reason"])

    def test_a_relative_repo_path_is_rejected_as_not_absolute(self):
        """Checked before the allowlist, so an empty allowlist still names
        the right reason rather than a generic refusal."""
        import daemon_graph
        proj = self.vault / "10_Projets" / "Logiciels" / "Rel"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            "---\nrepo: ..\\Rel\n---\n\nbody\n", encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/Rel/note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots, [])
        self.assertIsNone(result["entity"])
        self.assertIn("not absolute", result["reason"])

    def test_tries_hits_in_order_and_returns_the_first_resolving_one(self):
        import daemon_graph
        hits = [self._hit("30_Ressources/Python/orphan.md"),
                self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots,
                                          self.allowed_roots)
        self.assertEqual(result["entity"], "DemoRepo")

    def test_no_hits_at_all(self):
        import daemon_graph
        result = daemon_graph.entity_repo(self.vault, [], self.roots,
                                          self.allowed_roots)
        self.assertIsNone(result["entity"])
        self.assertIn("no vault hit", result["reason"])

    # ---------- R24: the allowlist itself ----------

    def test_a_repo_outside_the_allowlist_is_refused_even_though_it_exists_and_has_a_graph(self):
        """The core H3 fix: a repo: value naming a real, graph-bearing
        directory that is NOT in the allowlist must still be refused -
        existence and a graph.json are necessary but no longer sufficient."""
        import daemon_graph
        hits = [self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots, [])
        self.assertIsNone(result["entity"])
        self.assertIn("no repository is allowlisted", result["reason"])

    def test_the_refusal_reason_names_the_path_plainly_not_via_repr(self):
        """PR #49 third re-review, F1 (Medium-High): the refusal reason used
        to interpolate the raw repo: value with `!r`, which on Windows
        DOUBLES every backslash in the printed text (repr escaping). The
        reason is later redacted by rt_state.redact_json/home_tilde, a plain
        substring replace of the operator's home path - a doubled-backslash
        rendering is not a substring match for the single-backslash home
        text, so the account path would survive redaction and reach a
        browser. A real, OS-native absolute path (not a literal Windows-style
        string) is used so the "outside the allowlist" branch - the one that
        actually interpolates the value - fires on every platform the suite
        runs on, rather than "is not absolute" on POSIX or "no repository is
        allowlisted" (which embeds nothing) on Windows."""
        import daemon_graph
        outside = Path(tempfile.mkdtemp())
        not_this_one = Path(tempfile.mkdtemp())
        result = daemon_graph._resolve_repo_claim(
            str(outside), [not_this_one.resolve()])
        self.assertIn(str(outside), result["reason"])
        self.assertNotIn(repr(str(outside)), result["reason"])

    def test_an_empty_allowlist_names_itself_rather_than_the_target_path(self):
        import daemon_graph
        hits = [self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        result = daemon_graph.entity_repo(
            self.vault, hits, self.roots,
            [Path(tempfile.mkdtemp()).resolve()])
        self.assertIsNone(result["entity"])
        self.assertIn("outside the configured allowlist", result["reason"])

    def test_a_dot_dot_escape_past_an_allowed_root_is_refused(self):
        """A naive startswith() containment check would be fooled by a
        textual prefix match; resolve()-then-equality is not, since the
        escaped path resolves to a directory that is not itself an
        allowlisted root (R24: resolve first, then compare, never clamp)."""
        import daemon_graph
        sibling = Path(tempfile.mkdtemp(dir=self.repo.parent))
        (sibling / "graphify-out").mkdir()
        (sibling / "graphify-out" / "graph.json").write_text(
            "{}", encoding="utf-8")
        escaped = str(self.repo / ".." / sibling.name)
        proj = self.vault / "10_Projets" / "Logiciels" / "Escape"
        proj.mkdir(parents=True)
        (proj / "index.md").write_text(
            f"---\nrepo: {escaped}\n---\n\nbody\n", encoding="utf-8")
        (proj / "note.md").write_text("body\n", encoding="utf-8")
        hits = [self._hit("10_Projets/Logiciels/Escape/note.md")]
        result = daemon_graph.entity_repo(self.vault, hits, self.roots,
                                          self.allowed_roots)
        self.assertIsNone(result["entity"])
        self.assertIn("outside the configured allowlist", result["reason"])

    def test_a_sibling_directory_sharing_a_string_prefix_is_refused(self):
        """PR #49 third re-review mutation S1 (survived): replacing the
        resolved EQUALITY check with a string prefix test (startswith)
        would let a SIBLING directory whose name merely starts with the
        allowed root's own name pass, since '<repo>' is a string-prefix of
        '<repo>-evil'. Resolved equality has no such hole."""
        import daemon_graph
        sibling = Path(str(self.repo) + "-evil")
        sibling.mkdir()
        (sibling / "graphify-out").mkdir()
        (sibling / "graphify-out" / "graph.json").write_text(
            "{}", encoding="utf-8")
        result = daemon_graph._resolve_repo_claim(
            str(sibling), self.allowed_roots)
        self.assertIsNone(result.get("repo"))
        self.assertIn("outside the configured allowlist", result["reason"])

    def test_a_trailing_dot_spelling_of_an_allowed_root_still_resolves(self):
        """PR #49 third re-review mutation S2 (survived): if the CLAIM's
        own path were compared WITHOUT resolve(), an equivalent-but-
        differently-spelled path to an allowed root (here, a trailing '.')
        would be refused instead of accepted, since the raw strings differ
        even though they name the same directory."""
        import daemon_graph
        dotted = str(self.repo / ".")
        result = daemon_graph._resolve_repo_claim(dotted, self.allowed_roots)
        self.assertEqual(result.get("repo"), self.repo.resolve())

    def test_load_allowed_roots_resolves_a_trailing_dot_entry(self):
        """PR #49 third re-review mutation S3 (survived): if
        load_allowed_roots stored its entries RAW (no resolve()), an
        operator-configured root spelled with a trailing '.' would never
        equal a plain, cleanly-spelled claim for the same directory."""
        import daemon_graph
        config_path = Path(tempfile.mkdtemp()) / "local-ask-graph-roots.json"
        config_path.write_text(
            json.dumps({"allowed_roots": [str(self.repo / ".")]}),
            encoding="utf-8")
        roots = daemon_graph.load_allowed_roots(config_path)
        result = daemon_graph._resolve_repo_claim(str(self.repo), roots)
        self.assertEqual(result.get("repo"), self.repo.resolve())

    def test_entity_repo_with_no_allowed_roots_argument_loads_the_real_file(self):
        """The default (omitted) allowed_roots argument calls
        load_allowed_roots() rather than silently allowing everything."""
        import daemon_graph
        hits = [self._hit("10_Projets/Logiciels/DemoRepo/some-note.md")]
        with mock.patch("daemon_graph.load_allowed_roots",
                        return_value=self.allowed_roots) as loader:
            result = daemon_graph.entity_repo(self.vault, hits, self.roots)
        self.assertTrue(loader.called)
        self.assertEqual(result["entity"], "DemoRepo")

    def test_read_repo_property_on_a_frontmatter_less_file_is_none(self):
        import daemon_graph
        p = self.vault / "plain.md"
        p.write_text("no frontmatter here\n", encoding="utf-8")
        self.assertIsNone(daemon_graph.read_repo_property(p))

    def test_read_repo_property_on_a_missing_file_is_none(self):
        import daemon_graph
        self.assertIsNone(
            daemon_graph.read_repo_property(self.vault / "absent.md"))


class LoadAllowedRootsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "local-ask-graph-roots.json"

    def test_a_missing_file_is_an_empty_allowlist(self):
        import daemon_graph
        self.assertEqual(daemon_graph.load_allowed_roots(self.path), [])

    def test_unparsable_json_is_an_empty_allowlist_not_an_exception(self):
        import daemon_graph
        self.path.write_text("not json at all", encoding="utf-8")
        self.assertEqual(daemon_graph.load_allowed_roots(self.path), [])

    def test_a_json_value_that_is_not_an_object_is_an_empty_allowlist(self):
        import daemon_graph
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(daemon_graph.load_allowed_roots(self.path), [])

    def test_a_non_list_allowed_roots_value_is_an_empty_allowlist(self):
        import daemon_graph
        self.path.write_text(
            json.dumps({"allowed_roots": "not-a-list"}), encoding="utf-8")
        self.assertEqual(daemon_graph.load_allowed_roots(self.path), [])

    def test_a_valid_file_returns_resolved_paths(self):
        import daemon_graph
        repo_a = self.tmp / "RepoA"
        repo_a.mkdir()
        self.path.write_text(
            json.dumps({"allowed_roots": [str(repo_a)]}), encoding="utf-8")
        roots = daemon_graph.load_allowed_roots(self.path)
        self.assertEqual(roots, [repo_a.resolve()])

    def test_non_string_and_blank_entries_are_dropped(self):
        import daemon_graph
        self.path.write_text(
            json.dumps({"allowed_roots": [123, "", "   ", None]}),
            encoding="utf-8")
        self.assertEqual(daemon_graph.load_allowed_roots(self.path), [])

    def test_the_default_path_sits_beside_local_model_config(self):
        import daemon_graph
        self.assertEqual(daemon_graph.allowed_roots_path().name,
                         "local-ask-graph-roots.json")
        self.assertEqual(daemon_graph.allowed_roots_path().parent.name,
                         ".claude")


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

    def test_a_leading_dash_keyword_never_reaches_argv(self):
        """PR #49 third re-review L8: a keyword beginning with '-' could be
        read as an option by whatever parser graphify uses, even as a single
        joined token (true of argparse positionals). Unverifiable without
        the real CLI (R14), so this refuses rather than guesses at a `--`
        separator - cheap, and needs no knowledge of graphify's own
        parsing."""
        import daemon_graph
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run") as run:
            result = daemon_graph.query_graph(
                self.repo, ["-rf", "--budget=0"], 1500, 4000, 20.0)
        self.assertIsNone(result["text"])
        self.assertIn("begins with '-'", result["reason"])
        self.assertFalse(run.called)

    def test_a_mix_of_safe_and_dashed_keywords_drops_only_the_dashed_ones(self):
        import daemon_graph
        fake = mock.Mock(returncode=0, stdout="x", stderr="")
        with mock.patch("daemon_graph.shutil.which",
                        return_value="/usr/bin/graphify"), \
                mock.patch("daemon_graph.subprocess.run",
                          return_value=fake) as run:
            daemon_graph.query_graph(
                self.repo, ["-rf", "vault", "lock"], 1500, 4000, 20.0)
        args, kwargs = run.call_args
        self.assertEqual(args[0][2], "vault lock")

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
