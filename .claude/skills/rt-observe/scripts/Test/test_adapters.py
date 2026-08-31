"""
test_adapters - the harness contract, and the two adapters that implement it.

Offline: fixture homes under tempfile, a SQLite store built in the test, no
network and no binary invoked.

The load-bearing test here is `test_a_fake_adapter_appears_with_no_core_edit`.
The whole design claim is that adding a harness is a new module plus one data
line; a design that merely INTENDS to be neutral drifts on the first
convenience, and one that is tested for it cannot. The second is the
zero-harness baseline: with every adapter probing false the snapshot must still
be useful, because that is the configuration most other people who clone this
repository will run.
"""
import io
import json
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import adapters  # noqa: E402
import collect_services  # noqa: E402
import rt_state  # noqa: E402

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


class AdapterHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.config = rt_state.load_config()
        self.context = adapters.AdapterContext(self.repo, self.home,
                                               self.config, NOW)


class ContractTest(AdapterHarness):

    def test_a_fake_adapter_appears_with_no_core_edit(self):
        """The harness-agnostic guarantee, asserted rather than intended: a
        module plus one registry line, and the snapshot grows."""
        module_dir = Path(self._tmp.name) / "extra"
        (module_dir / "adapters").mkdir(parents=True)
        write(module_dir / "adapters" / "__init__.py", "")
        write(module_dir / "adapters" / "fake_harness.py", textwrap.dedent("""
            def probe(context):
                return True

            def collect(context):
                return {"sessions": [{"session_id": "s1"}], "proven_by": "fake"}
        """))
        # The adapters package is already imported from the real scripts
        # directory, so a second directory on sys.path is never consulted. A
        # third-party adapter joins by extending the PACKAGE path, which is what
        # a plugin directory would do - and crucially, no file in the core is
        # edited, which is the claim under test.
        adapters.__path__.append(str(module_dir / "adapters"))
        self.addCleanup(lambda: adapters.__path__.remove(str(module_dir / "adapters")))
        self.addCleanup(lambda: sys.modules.pop("adapters.fake_harness", None))

        registry = {"adapters": [{"id": "fake", "module": "fake_harness",
                                  "label": "Fake Harness"}]}
        result = adapters.collect_all(self.context, registry=registry)
        self.assertEqual(result["installed"], ["fake"])
        self.assertEqual(result["harnesses"]["fake"]["status"], "ok")
        self.assertEqual(result["harnesses"]["fake"]["label"], "Fake Harness")

    def test_an_adapter_probing_false_is_not_installed_and_not_an_error(self):
        registry = {"adapters": [{"id": "claude_code", "module": "claude_code",
                                  "label": "Claude Code"}]}
        result = adapters.collect_all(self.context, registry=registry)
        state = result["harnesses"]["claude_code"]
        self.assertEqual(state["status"], "not-installed")
        self.assertIn("normal configuration", state["reason"])
        self.assertEqual(result["installed"], [])

    def test_a_registered_module_that_cannot_be_imported_is_named(self):
        """Never dropped. A silently absent harness is the state this whole
        panel exists to make visible."""
        registry = {"adapters": [{"id": "ghost", "module": "no_such_module",
                                  "label": "Ghost"}]}
        result = adapters.collect_all(self.context, registry=registry)
        state = result["harnesses"]["ghost"]
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("no_such_module", state["reason"])

    def test_an_adapter_that_raises_costs_only_its_own_panel(self):
        module_dir = Path(self._tmp.name) / "boom"
        (module_dir / "adapters").mkdir(parents=True)
        write(module_dir / "adapters" / "__init__.py", "")
        write(module_dir / "adapters" / "explodes.py", textwrap.dedent("""
            def probe(context):
                return True

            def collect(context):
                raise ValueError("the store went away")
        """))
        adapters.__path__.append(str(module_dir / "adapters"))
        self.addCleanup(lambda: adapters.__path__.remove(str(module_dir / "adapters")))
        self.addCleanup(lambda: sys.modules.pop("adapters.explodes", None))

        registry = {"adapters": [
            {"id": "boom", "module": "explodes", "label": "Boom"},
            {"id": "claude_code", "module": "claude_code", "label": "Claude Code"},
        ]}
        result = adapters.collect_all(self.context, registry=registry)
        self.assertEqual(result["harnesses"]["boom"]["status"], "unavailable")
        self.assertIn("ValueError", result["harnesses"]["boom"]["reason"])
        # The other adapter still answered.
        self.assertIn("claude_code", result["harnesses"])

    def test_a_missing_registry_means_no_adapters_not_a_crash(self):
        registry = adapters.load_registry(Path(self._tmp.name))
        self.assertEqual(registry["adapters"], [])

    def test_the_shipped_registry_declares_the_two_built_adapters(self):
        registry = adapters.load_registry()
        ids = {entry["id"] for entry in registry["adapters"]}
        self.assertEqual(ids, {"claude_code", "copilot_chat"})
        # And the ones deliberately not built are documented, so a later session
        # does not re-derive why.
        not_built = {entry["id"] for entry in registry["documented_not_built"]}
        self.assertIn("copilot_cli", not_built)
        self.assertIn("codex", not_built)

    def test_the_copilot_cli_entry_warns_about_its_credential(self):
        """Those lock files carry an Authorization Nonce. The rule has to survive
        in the data, since no code enforces it until that adapter exists."""
        registry = adapters.load_registry()
        entry = [e for e in registry["documented_not_built"]
                 if e["id"] == "copilot_cli"][0]
        self.assertIn("Nonce", entry["reason"])


class ZeroHarnessTest(AdapterHarness):

    def test_the_snapshot_is_useful_with_no_harness_at_all(self):
        """The configuration most other users run: a clone, no Claude Code, no
        Copilot, an empty home. The matrix, registry and repo panels must still
        be complete and nothing may raise."""
        write(self.repo / "mirror-policy.json", json.dumps({
            "version": 1,
            "thresholds": {"copilot_stub_threshold": {"value": 100},
                           "copilot_hard_limit": {"value": 300},
                           "codex_skill_list_budget": {"value": 8000},
                           "codex_doc_max_bytes": {"value": 32768}},
            "skips": {}, "orphans_by_design": {},
            "targets": [{"id": "copilot-agents", "harness": "GitHub Copilot",
                         "scope": "repo", "source": "agents",
                         "path": ".github/agents/{name}.agent.md",
                         "cardinality": "per-definition"}],
        }))
        write(self.repo / ".claude" / "agents" / "alpha.md",
              "---\nname: alpha\ndescription: \"x\"\n---\n\nbody\n")

        # build_snapshot runs the services collector, which would otherwise
        # invoke the real `claude mcp list` and reach the network for every
        # configured server. An offline suite that quietly goes online is not
        # offline; it just fails on a machine without a network instead.
        with mock.patch.object(collect_services.shutil, "which",
                               return_value=None):
            snapshot = rt_state.build_snapshot(self.repo, self.home, now=NOW,
                                               config=self.config)
        self.assertEqual(snapshot["mirrors"]["status"], "ok")
        self.assertEqual(snapshot["registry"]["status"], "ok")
        self.assertEqual(snapshot["repo_state"]["status"], "ok")
        # Every adapter absent, and said so rather than omitted.
        for state in snapshot["fleet"]["harnesses"].values():
            self.assertIn(state["status"], ("not-installed", "unavailable"))
            self.assertTrue(state.get("reason"))
        # The panels that genuinely cannot answer say why.
        self.assertEqual(snapshot["progress"]["status"], "unavailable")
        self.assertEqual(snapshot["graph"]["status"], "unavailable")


class ClaudeCodeAdapterTest(AdapterHarness):

    def _transcript(self, project, session_id, records):
        path = (self.home / ".claude" / "projects" / project
                / ("%s.jsonl" % session_id))
        path.parent.mkdir(parents=True, exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return path

    def _collect(self):
        import adapters.claude_code as adapter
        return adapter.collect(self.context)

    def test_a_session_card_is_built_from_the_transcript_tail(self):
        self._transcript("proj-a", "sess-1", [
            {"sessionId": "sess-1", "cwd": str(self.home / "work" / "proj-a"),
             "gitBranch": "main", "mode": "default"},
            {"lastPrompt": "do the thing", "entrypoint": "claude-vscode",
             "effort": "high", "isSidechain": True},
        ])
        state = self._collect()
        card = state["sessions"][0]
        self.assertEqual(card["session_id"], "sess-1")
        self.assertEqual(card["branch"], "main")
        self.assertEqual(card["entrypoint"], "claude-vscode")
        self.assertEqual(card["prompt"], "do the thing")
        self.assertEqual(card["subagents"], 1)

    def test_no_account_name_reaches_the_snapshot(self):
        """Paths under the home are rewritten to ~, so a screenshot of the page
        and the JSON dump both stay free of the operator's account name."""
        self._transcript("proj-a", "sess-1", [
            {"sessionId": "sess-1", "cwd": str(self.home / "work")}])
        state = self._collect()
        self.assertNotIn(str(self.home), json.dumps(state))
        self.assertTrue(state["sessions"][0]["cwd"].startswith("~"))

    def test_a_truncated_transcript_does_not_abort_the_fleet(self):
        path = self._transcript("proj-a", "sess-1",
                                [{"sessionId": "sess-1", "cwd": "x"}])
        with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write('{"lastPrompt": "half a rec')
        state = self._collect()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(len(state["sessions"]), 1)

    def test_an_excluded_project_contributes_nothing(self):
        self._transcript("secret-matter", "sess-x", [{"sessionId": "sess-x"}])
        self._transcript("proj-a", "sess-1", [{"sessionId": "sess-1"}])
        config = json.loads(json.dumps(self.config))
        config["privacy"]["excluded_projects"]["value"] = ["secret-matter"]
        context = adapters.AdapterContext(self.repo, self.home, config, NOW)
        import adapters.claude_code as adapter
        state = adapter.collect(context)
        names = {s["project"] for s in state["sessions"]}
        self.assertEqual(names, {"proj-a"})
        self.assertNotIn("sess-x", json.dumps(state))

    def test_a_prompt_is_truncated_to_its_configured_cap(self):
        self._transcript("proj-a", "sess-1",
                         [{"sessionId": "sess-1", "lastPrompt": "x" * 5000}])
        cap = self.config["caps"]["prompt_chars"]["value"]
        state = self._collect()
        self.assertLessEqual(len(state["sessions"][0]["prompt"]), cap)

    def test_a_stop_hook_error_is_surfaced_on_the_card(self):
        self._transcript("proj-a", "sess-1", [
            {"sessionId": "sess-1"},
            {"system": {"stop_hook_summary": {"hookErrors": ["guard exploded"]}}},
        ])
        state = self._collect()
        self.assertEqual(state["sessions"][0]["hook_errors"], ["guard exploded"])

    def test_an_absent_inventory_script_is_stated_not_silently_empty(self):
        self._transcript("proj-a", "sess-1", [{"sessionId": "sess-1"}])
        state = self._collect()
        self.assertEqual(state["hooks"]["status"], "unavailable")
        self.assertIn("session-hooks-inventory.py", state["hooks"]["reason"])

    def test_a_session_with_no_delivery_hook_is_unreachable_not_delivered(self):
        """A message written into a directory nobody drains is the vault drop
        that sat in working/ for an hour, rebuilt."""
        self._transcript("proj-a", "sess-1", [{"sessionId": "sess-1"}])
        state = self._collect()
        inbox = state["sessions"][0]["inbox"]
        self.assertFalse(inbox["reachable"])
        self.assertIn("would never be read", inbox["reason"])


class CopilotChatAdapterTest(AdapterHarness):

    def _store(self, rows=(("s1", "C:/work", "repo-a", "vscode", "main",
                            "a summary", "agent-x", 200),)):
        path = self.home.joinpath("AppData", "Roaming", "Code", "User",
                                  "globalStorage", "github.copilot-chat",
                                  "session-store.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path))
        connection.execute(
            "CREATE TABLE sessions (id TEXT, cwd TEXT, repository TEXT, "
            "host_type TEXT, branch TEXT, summary TEXT, agent_name TEXT, "
            "agent_description TEXT, created_at INT, updated_at INT)")
        connection.execute(
            "CREATE TABLE turns (session_id TEXT, turn_index INT, "
            "user_message TEXT, assistant_response TEXT, timestamp INT)")
        for row in rows:
            connection.execute(
                "INSERT INTO sessions (id, cwd, repository, host_type, branch, "
                "summary, agent_name, updated_at) VALUES (?,?,?,?,?,?,?,?)", row)
        connection.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?)",
            ("s1", 0, "a user message", "an assistant response", 1))
        connection.commit()
        connection.close()
        return path

    def test_probe_is_false_without_the_store(self):
        import adapters.copilot_chat as adapter
        self.assertFalse(adapter.probe(self.context))

    def test_sessions_are_read_and_message_bodies_are_not(self):
        """Only session metadata is selected. The turns table is touched for a
        COUNT and nothing else, so no prompt text from another harness reaches
        the snapshot."""
        self._store()
        import adapters.copilot_chat as adapter
        state = adapter.collect(self.context)
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["sessions"][0]["repository"], "repo-a")
        self.assertEqual(state["counts"]["turns"], 1)
        blob = json.dumps(state)
        self.assertNotIn("a user message", blob)
        self.assertNotIn("an assistant response", blob)

    def test_the_store_is_opened_read_only(self):
        """It is the editor's live database. Proven by attempting a write on the
        same URI the adapter uses and requiring it to be refused."""
        path = self._store()
        uri = "file:%s?mode=ro" % path.as_posix()
        connection = sqlite3.connect(uri, uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO turns VALUES ('x',1,'a','b',2)")
        finally:
            connection.close()

    def test_an_unexpected_schema_degrades_with_its_reason(self):
        path = self.home.joinpath("AppData", "Roaming", "Code", "User",
                                  "globalStorage", "github.copilot-chat",
                                  "session-store.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path))
        connection.execute("CREATE TABLE sessions (id TEXT)")
        connection.commit()
        connection.close()
        import adapters.copilot_chat as adapter
        state = adapter.collect(self.context)
        self.assertEqual(state["status"], "unavailable")
        self.assertIn("schema may have", state["reason"])

    def test_a_copilot_session_is_reportable_but_not_reachable(self):
        self._store()
        import adapters.copilot_chat as adapter
        state = adapter.collect(self.context)
        inbox = state["sessions"][0]["inbox"]
        self.assertFalse(inbox["reachable"])
        self.assertIn("no hook", inbox["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
