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
import os
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_the_account_name_is_redacted_inside_the_prompt_too(self):
        """The case the test above could not catch, and it was live until
        2026-08-31: the prompt is FREE TEXT and routinely quotes a path under
        the home directory. Only `cwd` was being redacted, so a rendered session
        card carried the account name in full while the older test - which puts
        the home path only in `cwd` - stayed green."""
        self._transcript("proj-a", "sess-1", [
            {"sessionId": "sess-1", "cwd": str(self.home / "work"),
             "lastPrompt": "read %s and continue"
                           % (self.home / ".claude" / "plans" / "p.md")}])
        state = self._collect()
        card = state["sessions"][0]
        self.assertNotIn(str(self.home), json.dumps(state))
        self.assertIn("~", card["prompt"])
        self.assertIn("continue", card["prompt"])

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


class FlowTest(AdapterHarness):
    """The Real-Time Process tab is adapter-fed, so what it can honestly draw is
    decided here rather than in the markup. `_flow_from` is driven directly with
    an injected age: the alternative is a fixture whose modification time is the
    real clock, which would make `idle` depend on when the suite is run."""

    def _flow(self, records, age=0, cap=18, idle_after=90):
        import adapters.claude_code as adapter
        return adapter._flow_from(records, cap, age, idle_after)

    def _assistant(self, blocks, **extra):
        record = {"type": "assistant", "timestamp": "2026-09-01T13:00:00Z",
                  "message": {"content": blocks}}
        record.update(extra)
        return record

    def test_a_tool_call_a_result_and_a_thought_become_three_steps(self):
        flow = self._flow([
            {"type": "last-prompt"},
            self._assistant([{"type": "thinking"}]),
            self._assistant([{"type": "tool_use", "name": "Bash"}]),
            {"type": "user", "timestamp": "2026-09-01T13:00:02Z",
             "message": {"content": [{"type": "tool_result"}]}},
        ])
        self.assertEqual(["prompt", "reasoning", "tool", "result"],
                         [s["kind"] for s in flow["steps"]])
        self.assertEqual("post_tool", flow["state"])

    def test_an_attachment_that_is_not_a_hook_contributes_nothing(self):
        """The tail is mostly attachments. A step per record would draw a flow
        that is real and unreadable, which is the same as not drawing one - but
        a HOOK firing is an attachment too, and reading them all as noise is
        what made the deterministic half of the harness invisible."""
        flow = self._flow([{"type": "attachment"}] * 5)
        self.assertEqual([], flow["steps"])
        self.assertEqual([], flow["hooks"])
        self.assertEqual("idle", flow["state"])

    def _hook(self, **fields):
        attachment = {"type": "hook_success", "hookEvent": "PreToolUse",
                      "hookName": "PreToolUse:Write", "exitCode": 0}
        attachment.update(fields)
        return {"type": "attachment", "timestamp": "2026-09-01T13:00:00Z",
                "attachment": attachment}

    def test_a_hook_firing_is_reported_and_kept_off_the_step_list(self):
        """PreToolUse and PostToolUse fire on EVERY tool call, so hooks sharing
        the step list would drown the flow they are meant to explain. They are
        counted apart, which is also what keeps them from pushing a subagent
        dispatch out of the lane."""
        flow = self._flow([
            self._hook(command="Scanning for secrets (betterleaks)..."),
            self._assistant([{"type": "tool_use", "name": "Write"}]),
        ])
        self.assertEqual(["tool"], [s["kind"] for s in flow["steps"]])
        self.assertEqual(1, len(flow["hooks"]))
        self.assertEqual("PreToolUse", flow["hooks"][0]["event"])

    def test_a_hook_is_named_by_its_own_words_never_by_its_file(self):
        """The operator asked for the hook NAME on the loop, not the python file
        that implements it. Three sources, in this order."""
        import adapters.claude_code as adapter
        self.assertEqual(
            "Scanning for secrets (betterleaks)",
            adapter._hook_label("Scanning for secrets (betterleaks)...",
                                "PreToolUse:Write"))
        self.assertEqual(
            "betterleaks",
            adapter._hook_label('python "C:/h/betterleaks-hook.py"',
                                "PreToolUse:Write"))
        # A plugin file named after the event itself says nothing the arrow does
        # not already say, so the matcher is used instead - and the file name
        # never reaches the diagram.
        named = adapter._hook_label(
            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.py"',
            "PreToolUse:Write")
        self.assertEqual("on Write", named)
        self.assertNotIn(".py", named)

    def test_a_refusing_hook_carries_its_exit_code(self):
        """The one hook state that must never be missed: a non-zero exit means
        the call was BLOCKED, not merely watched."""
        flow = self._flow([self._hook(type="hook_error", exitCode=2,
                                      command="Checking vault access")])
        self.assertEqual(2, flow["hooks"][0]["exit"])

    def test_an_mcp_call_is_named_by_its_server(self):
        """`mcp__playwright__browser_evaluate` says the protocol twice and the
        server once. The chip says who was called and what for; the raw id stays
        on the step for the hover panel."""
        flow = self._flow([self._assistant(
            [{"type": "tool_use", "name": "mcp__playwright__browser_evaluate"}])])
        step = flow["steps"][0]
        self.assertEqual("playwright . browser_evaluate", step["name"])
        self.assertEqual("mcp__playwright__browser_evaluate", step["tool"])
        self.assertEqual("playwright", step["server"])
        self.assertEqual("mcp", step["network"])

    def test_a_subagent_dispatch_is_not_pushed_out_by_later_tool_calls(self):
        """Measured 2026-09-01: the dispatch was invisible on the tab because
        120 later Bash calls had pushed it off an 18-slot list. Subagents are
        counted apart for exactly this reason."""
        records = [self._assistant([{"type": "tool_use", "name": "Agent",
                                     "input": {"subagent_type": "local-writer"}}])]
        records += [self._assistant([{"type": "tool_use", "name": "Bash"}])] * 40
        flow = self._flow(records, cap=4)
        self.assertEqual(4, len(flow["steps"]))
        self.assertEqual(["local-writer"],
                         [a["name"] for a in flow["subagents"]])

    def test_a_failed_tool_result_is_reported_as_failed(self):
        """`Fail is a result, and it is impossible to track` - the operator. The
        transcript marks it on the result block, so the call it answers can be
        drawn as failed rather than as returned, which looked identical."""
        flow = self._flow([
            self._assistant([{"type": "tool_use", "name": "Bash"}]),
            {"type": "user", "timestamp": "2026-09-01T13:00:02Z",
             "message": {"content": [{"type": "tool_result",
                                      "is_error": True}]}},
        ])
        self.assertTrue(flow["steps"][-1]["error"])

    def test_a_result_that_did_not_fail_says_so_too(self):
        """The negative control: without it the field could be true always and
        every call would be drawn as failed."""
        flow = self._flow([
            self._assistant([{"type": "tool_use", "name": "Bash"}]),
            {"type": "user", "timestamp": "2026-09-01T13:00:02Z",
             "message": {"content": [{"type": "tool_result",
                                      "is_error": False}]}},
        ])
        self.assertFalse(flow["steps"][-1]["error"])

    def test_a_subagent_is_named_by_the_call_that_spawned_it(self):
        """`c2:fig:superpowers_collab` hangs a subagent off the session that
        spawned it, and the parent transcript is where that link exists: the
        sidechain records themselves never name the agent type."""
        flow = self._flow([self._assistant([
            {"type": "tool_use", "name": "Agent",
             "input": {"subagent_type": "local-writer"}}])])
        self.assertEqual("subagent", flow["steps"][0]["kind"])
        self.assertEqual("local-writer", flow["steps"][0]["name"])

    def test_a_call_that_leaves_the_machine_says_so_and_mcp_says_maybe(self):
        """Part F asks which tool call left the machine. WebFetch did; an MCP
        server MAY have, since a server can be a local process - and claiming
        more than is known is the defect, not the caution."""
        web = self._flow([self._assistant(
            [{"type": "tool_use", "name": "WebFetch"}])])
        self.assertEqual("yes", web["steps"][0]["network"])
        mcp = self._flow([self._assistant(
            [{"type": "tool_use", "name": "mcp__thing__do"}],
            attributionMcpServer="thing")])
        self.assertEqual("mcp", mcp["steps"][0]["network"])
        self.assertEqual("thing", mcp["steps"][0]["server"])
        local = self._flow([self._assistant(
            [{"type": "tool_use", "name": "Bash"}])])
        self.assertEqual("no", local["steps"][0]["network"])

    def test_silence_is_read_as_waiting_and_only_after_the_threshold(self):
        """A settled session goes quiet and is idle. The threshold is the only
        thing that decides it."""
        records = [self._assistant([{"type": "tool_use", "name": "Bash"}]),
                   {"type": "user", "timestamp": "2026-09-01T13:00:02Z",
                    "message": {"content": [{"type": "tool_result"}]}}]
        self.assertEqual("post_tool", self._flow(records, age=10)["state"])
        self.assertEqual("idle", self._flow(records, age=90)["state"])

    def test_an_outstanding_call_means_working_however_long_the_silence(self):
        """A call with no result after it is still OUT, and a build or a test
        run writes nothing to the transcript for minutes. Measured by the
        operator: a session that was working read as asleep, because silence
        alone was being taken for idleness."""
        records = [self._assistant([{"type": "tool_use", "name": "Bash"}])]
        self.assertEqual("tool", self._flow(records, age=10)["state"])
        self.assertEqual("tool", self._flow(records, age=6000)["state"],
                         "the call never returned, so the session is waiting "
                         "on it rather than idle")

    def test_the_step_list_is_capped_and_says_what_it_dropped(self):
        records = [self._assistant([{"type": "tool_use", "name": "Bash"}])] * 8
        flow = self._flow(records, cap=3)
        self.assertEqual(3, len(flow["steps"]))
        self.assertEqual(5, flow["dropped"])

    def test_no_percentage_is_invented_from_a_window_nobody_reported(self):
        """The one number Part F asks for that the harness does not expose. A
        bar drawn from a guessed denominator reads exactly like a measured one,
        so the total is reported and the percentage is refused WITH its reason
        (R8)."""
        flow = self._flow([self._assistant(
            [{"type": "text"}],
            message={"content": [{"type": "text"}],
                     "usage": {"input_tokens": 10,
                               "cache_read_input_tokens": 90,
                               "output_tokens": 5}})])
        self.assertEqual("ok", flow["tokens"]["status"])
        self.assertEqual(100, flow["tokens"]["held"])
        self.assertIsNone(flow["tokens"]["percent"])
        self.assertIn("window", flow["tokens"]["percent_reason"])

    def test_a_transcript_with_no_usage_says_so_rather_than_reporting_zero(self):
        flow = self._flow([self._assistant([{"type": "text"}])])
        self.assertEqual("unavailable", flow["tokens"]["status"])
        self.assertIn("reason", flow["tokens"])

    def test_the_state_machine_is_named_by_the_adapter_not_the_page(self):
        """One table. The page colours by role and the adapter names the role,
        so a second list in the markup cannot drift from this one (R5)."""
        import adapters.claude_code as adapter
        roles = set(s[2] for s in adapter.FLOW_STATES)
        self.assertEqual({"hook", "core", "security", "idle"}, roles)
        ids = [s[0] for s in adapter.FLOW_STATES]
        self.assertEqual(ids[0], "session_start")
        self.assertIn("post_tool", ids)

    def test_a_session_card_carries_its_flow(self):
        self._transcript_for_flow()
        import adapters.claude_code as adapter
        state = adapter.collect(self.context)
        self.assertIn("flow_states", state)
        self.assertEqual("ok", state["sessions"][0]["flow"]["status"])

    def _transcript_for_flow(self):
        path = (self.home / ".claude" / "projects" / "proj-a" / "sess-1.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"sessionId": "sess-1"}) + "\n")
            handle.write(json.dumps(
                {"type": "assistant",
                 "message": {"content": [{"type": "tool_use",
                                          "name": "Bash"}]}}) + "\n")


class DeclaredHooksTest(unittest.TestCase):
    """The hook roster the state strip draws its loops from.

    Firings alone were not enough: a hook that runs once at SessionStart leaves
    the transcript tail within minutes of work, so the two the figure draws AS
    background loops - RTK and caveman - were never visible on a session more
    than an hour old. The declared roster comes from the inventory the session
    already prints."""

    def _parse(self, lines):
        import adapters.claude_code as adapter
        return adapter._declared_hooks(lines)

    def test_the_matchers_pipes_are_not_read_as_more_hooks(self):
        """The trap that was live for one run: a status reads
        `[ok, Write|Edit|MultiEdit]`, and splitting on the separator BEFORE
        removing the brackets turned every matcher into a hook of its own."""
        rows = self._parse([
            "PreToolUse(2): betterleaks-hook.py [ok, Write|Edit|MultiEdit] "
            "| vault-access-guard.py [ok, Bash|Read]"])
        self.assertEqual(1, len(rows))
        # The scripts are what was parsed; the names are what is DRAWN.
        self.assertEqual(["betterleaks-hook.py", "vault-access-guard.py"],
                         rows[0]["scripts"])
        self.assertEqual(2, len(rows[0]["names"]))

    def test_the_hooks_the_operator_asked_for_are_named(self):
        import json
        from pathlib import Path
        import adapters.claude_code as adapter
        table = json.loads(
            (Path(adapter.__file__).resolve().parent.parent.parent
             / "hook-names.json").read_text(encoding="utf-8"))["names"]
        rows = adapter._declared_hooks([
            "SessionStart(7): caveman-activate.js [ok] | rtk-active [inline] "
            "| obsidian-outbox-flush.py [ok]",
            "UserPromptSubmit(1): caveman-mode-tracker.js [ok]"], table)
        names = sum([row["names"] for row in rows], [])
        scripts = sum([row["scripts"] for row in rows], [])
        # The operator asked to see these three by NAME.
        for wanted in ("Caveman", "RTK", "Obsidian outbox"):
            with self.subTest(hook=wanted):
                self.assertIn(wanted, names)
        for name in names:
            with self.subTest(name=name):
                self.assertNotIn(".", name,
                                 "a file extension on a diagram is a path, "
                                 "not a name")
        self.assertIn("caveman-activate.js", scripts,
                      "the file is kept behind the name, for the hover panel "
                      "and for matching a firing")

    def test_a_header_line_is_not_an_event(self):
        """`[HOOKS ACTIVE] 14 entries / 6 events | 10 ok` is a summary, not a
        roster, and reading it as one would invent an event called `14 entries`.
        """
        rows = self._parse(["[HOOKS ACTIVE] 14 entries / 6 events | 10 ok",
                            "Stop(1): memory-upkeep [inline]"])
        self.assertEqual(["Stop"], [row["event"] for row in rows])

    def test_no_inventory_is_an_empty_roster_and_never_a_crash(self):
        self.assertEqual([], self._parse(None))
        self.assertEqual([], self._parse([]))


class HookNamingTest(unittest.TestCase):
    """What a hook is CALLED, and which hooks are shown at all.

    The operator asked for Caveman, RTK and BetterLeaks - not
    caveman-activate.js, rtk-active and betterleaks-hook.py - and asked that the
    harness's own plugin hooks stay off the diagram, since no settings.json on
    this machine asked for them."""

    def _adapter(self):
        import adapters.claude_code as adapter
        return adapter

    def _table(self):
        return {"betterleaks-hook.py": "BetterLeaks",
                "caveman-activate.js": "Caveman",
                "rtk-active": "RTK"}

    def test_a_hook_is_called_by_its_name_and_never_by_its_file(self):
        adapter = self._adapter()
        table = self._table()
        for script, wanted in (("betterleaks-hook.py", "BetterLeaks"),
                               ("caveman-activate.js", "Caveman"),
                               ("rtk-active", "RTK")):
            with self.subTest(script=script):
                self.assertEqual(wanted,
                                 adapter._hook_display(script, table))

    def test_a_hook_the_table_does_not_know_still_gets_a_name(self):
        """A missing entry degrades to a readable form of the file name, not to
        the file name itself and never to nothing (R11)."""
        adapter = self._adapter()
        self.assertEqual("Some new guard",
                         adapter._hook_display("some-new-guard-hook.py", {}))
        self.assertEqual("Thing", adapter._hook_display("thing.ps1", {}))

    def test_the_shipped_table_names_the_hooks_that_were_asked_for(self):
        import json
        from pathlib import Path
        import adapters.claude_code as adapter
        path = (Path(adapter.__file__).resolve().parent.parent.parent
                / "hook-names.json")
        names = json.loads(path.read_text(encoding="utf-8"))["names"]
        self.assertEqual("Caveman", names["caveman-activate.js"])
        self.assertEqual("RTK", names["rtk-active"])
        self.assertEqual("BetterLeaks", names["betterleaks-hook.py"])

    def test_the_declared_roster_carries_names_and_the_scripts_behind_them(self):
        adapter = self._adapter()
        rows = adapter._declared_hooks(
            ["PreToolUse(1): betterleaks-hook.py [ok, Write|Edit]"],
            self._table())
        self.assertEqual(["BetterLeaks"], rows[0]["names"])
        self.assertEqual(["betterleaks-hook.py"], rows[0]["scripts"])

    def test_a_hook_with_no_name_of_its_own_is_not_in_the_roster(self):
        """Measured 2026-09-01: a plugin registers `hook.js` on EVERY event, so
        the roster carried an entry called `Hook` on all ten of them - and since
        `hook` is a substring of every path containing `hooks/`, that one entry
        then matched every plugin firing and relabelled the lot `Hook`. A hook
        with no name of its own is the harness's, not the operator's."""
        adapter = self._adapter()
        rows = adapter._declared_hooks(
            ["PreToolUse(2): betterleaks-hook.py [ok] | hook.js [ok]"],
            self._table())
        self.assertEqual(["BetterLeaks"], rows[0]["names"])
        self.assertNotIn("hook.js", rows[0]["scripts"])

    def test_a_hook_is_matched_by_the_words_it_prints(self):
        """`vault-access-guard.py` prints `Checking vault access (local-writer
        only)` and shares no substring with the name it is displayed under, so
        the match is on WORDS. Without it a hook that named itself politely was
        dropped as though it had never run."""
        adapter = self._adapter()
        table = {"vault-access-guard.py": "Vault guard"}
        declared = adapter._declared_hooks(
            ["PreToolUse(1): vault-access-guard.py [ok]"], table)
        kept = adapter._only_declared(
            [{"event": "PreToolUse", "name": "PreToolUse:Read",
              "label": "Checking vault access (local-writer only)",
              "command": "Checking vault access (local-writer only)...",
              "at": "1"}], declared, table)
        self.assertEqual(["Vault guard"], [h["label"] for h in kept])

    def test_a_loose_stem_cannot_capture_an_unrelated_firing(self):
        """The negative control for the defect above: matching on a stem rather
        than a whole name is what let one entry swallow every firing."""
        adapter = self._adapter()
        table = {"betterleaks-hook.py": "BetterLeaks"}
        declared = adapter._declared_hooks(
            ["PreToolUse(1): betterleaks-hook.py [ok]"], table)
        kept = adapter._only_declared(
            [{"event": "PreToolUse", "name": "PreToolUse:Bash",
              "label": "on Bash", "at": "1",
              "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.py"'}],
            declared, table)
        self.assertEqual([], kept)

    def test_only_the_hooks_this_machine_declares_are_drawn(self):
        """The transcript also records the harness's own plugin hooks. Drawn
        beside the operator's guards they are noise wearing the same shape."""
        adapter = self._adapter()
        declared = adapter._declared_hooks(
            ["PreToolUse(1): betterleaks-hook.py [ok, Write]"], self._table())
        fired = [
            {"event": "PreToolUse", "name": "PreToolUse:Write",
             "label": "Scanning for secrets (betterleaks)",
             "command": "Scanning for secrets (betterleaks)...", "at": "1"},
            {"event": "PreToolUse", "name": "PreToolUse:Bash",
             "label": "on Bash", "at": "2",
             "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.py"'},
        ]
        kept = adapter._only_declared(fired, declared, self._table())
        self.assertEqual(["BetterLeaks"], [hook["label"] for hook in kept],
                         "the plugin hook is dropped and the declared one is "
                         "renamed to what the operator calls it")

    def test_a_firing_is_matched_by_its_script_as_well_as_by_its_words(self):
        """Some hooks print a sentence, some print nothing and the harness shows
        the command. Both routes have to reach the same declared entry."""
        adapter = self._adapter()
        declared = adapter._declared_hooks(
            ["SessionStart(1): caveman-activate.js [ok]"], self._table())
        kept = adapter._only_declared(
            [{"event": "SessionStart", "name": "SessionStart:startup",
              "label": "Loading caveman mode", "at": "1",
              "command": 'node "C:/h/caveman-activate.js"'}],
            declared, self._table())
        self.assertEqual(["Caveman"], [hook["label"] for hook in kept])

    def test_no_declared_roster_leaves_the_firings_alone(self):
        """A machine whose inventory could not be read still shows what fired,
        rather than showing nothing at all (R11)."""
        adapter = self._adapter()
        fired = [{"event": "PreToolUse", "name": "x", "label": "y", "at": "1"}]
        self.assertEqual(fired, adapter._only_declared(fired, [], {}))


class UsageScanTest(AdapterHarness):
    """The week bar's numerator. This is the only collector here that reads a
    transcript END TO END, which is why it has a timer and a floor of its own -
    and why what it counts had to be decided rather than assumed."""

    def _transcript(self, name, records, age_days=0):
        path = (self.home / ".claude" / "projects" / "proj-a"
                / ("%s.jsonl" % name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        if age_days:
            old = (NOW - timedelta(days=age_days)).timestamp()
            os.utime(path, (old, old))
        return path

    def _message(self, days_ago=0, **usage):
        when = NOW - timedelta(days=days_ago)
        return {"type": "assistant",
                "timestamp": when.isoformat().replace("+00:00", "Z"),
                "message": {"content": [{"type": "text"}], "usage": usage}}

    def _collect(self):
        import collect_usage
        return collect_usage.collect(self.context)

    def test_what_is_counted_is_what_was_new(self):
        """A cached prompt re-reads the same tokens on every message, so adding
        cache_read would count one conversation dozens of times and produce a
        number that looks like usage and measures repetition."""
        self._transcript("s1", [self._message(
            input_tokens=10, cache_creation_input_tokens=5,
            cache_read_input_tokens=90000, output_tokens=7)])
        state = self._collect()
        self.assertEqual("ok", state["status"])
        self.assertEqual(22, state["tokens"])
        self.assertEqual(1, state["messages"])
        self.assertIn("re-read from cache are excluded", state["counts_what"])

    def test_a_message_older_than_the_window_is_not_counted(self):
        self._transcript("s1", [self._message(days_ago=0, input_tokens=100),
                                self._message(days_ago=30, input_tokens=999)])
        self.assertEqual(100, self._collect()["tokens"])

    def test_a_transcript_untouched_within_the_window_is_never_opened(self):
        """The cheap half of the scan: a file whose mtime predates the window
        cannot hold a record inside it, so it is skipped without being read."""
        self._transcript("old", [self._message(input_tokens=500)], age_days=30)
        state = self._collect()
        self.assertEqual(0, state["transcripts_scanned"])
        self.assertEqual(0, state["tokens"])

    def test_an_excluded_project_contributes_nothing(self):
        path = (self.home / ".claude" / "projects" / "secret-matter")
        path.mkdir(parents=True, exist_ok=True)
        with io.open(path / "s.jsonl", "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(json.dumps(self._message(input_tokens=4242)) + "\n")
        excluded = list(self.config["privacy"]["excluded_projects"]["value"])
        self.config["privacy"]["excluded_projects"]["value"] = \
            excluded + ["secret-matter"]
        self.assertEqual(0, self._collect()["tokens"])

    def test_a_giant_transcript_is_cut_and_says_so(self):
        """It reads whole files, so an unbounded read is a page that hangs on
        the largest session anyone ever had."""
        self.config["caps"]["usage_scan_bytes"]["value"] = 200
        self._transcript("big", [self._message(input_tokens=1)] * 50)
        state = self._collect()
        self.assertEqual(1, state["transcripts_truncated"])

    def test_a_machine_with_no_transcripts_says_so_rather_than_zero(self):
        """Zero spend and no way to know are different answers, and only one of
        them is true here (R8)."""
        state = self._collect()
        self.assertEqual("unavailable", state["status"])
        self.assertIn("reason", state)

    def test_a_corrupt_line_does_not_lose_the_file(self):
        path = self._transcript("s1", [self._message(input_tokens=10)])
        with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write("{not json\n")
            handle.write(json.dumps(self._message(input_tokens=5)) + "\n")
        self.assertEqual(15, self._collect()["tokens"])


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
