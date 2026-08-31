"""
test_rt_mirrors - the mirror matrix tells a deliberate gap from a lost one.

Offline. Every case builds its own repository under tempfile and never reads the
live tree, so the suite passes or fails on its fixtures rather than on the state
of this machine (R21). No install is run and no PowerShell is invoked.

The failure paths are the tests that matter (R20), and the first two are the
whole product: a by-design skip reported as lost would send someone chasing a
mirror that was never meant to exist, and a lost mirror softened into by-design
is the defect the panel was built to expose. Both are asserted in both
directions, because a check that can only fire one way proves half a rule.
"""
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_mirrors as cm  # noqa: E402
import rt_state  # noqa: E402

FIXED_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

MINIMAL_POLICY = {
    "version": 1,
    "thresholds": {
        "copilot_stub_threshold": {"value": 100},
        "copilot_hard_limit": {"value": 300},
        "codex_skill_list_budget": {"value": 8000},
        "codex_doc_max_bytes": {"value": 32768},
    },
    "skips": {
        "session_mode_commands": {"values": ["concis", "slim"]},
    },
    "orphans_by_design": {},
    "targets": [
        {
            "id": "copilot-agents",
            "harness": "GitHub Copilot",
            "scope": "repo",
            "source": "agents",
            "path": ".github/agents/{name}.agent.md",
            "cardinality": "per-definition",
            "requires_flag": None,
            "degrades_to": "stubbed",
        },
        {
            "id": "copilot-prompts",
            "harness": "GitHub Copilot",
            "scope": "repo",
            "source": "commands",
            "path": ".github/prompts/{name}.prompt.md",
            "cardinality": "per-definition",
            "requires_flag": None,
            "skip_list": "session_mode_commands",
        },
        {
            "id": "copilot-cli-agents",
            "harness": "GitHub Copilot CLI",
            "scope": "user",
            "source": "agents",
            "path": "~/.copilot/agents/{name}.agent.md",
            "cardinality": "per-definition",
            "requires_flag": "-Personal",
        },
    ],
}


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    return path


def agent_file(name, body="body\n"):
    return "---\nname: %s\ndescription: \"a %s\"\n---\n\n%s" % (name, name, body)


class MatrixFixture:
    """A repository and a home, both disposable, both complete enough to matrix."""

    def __init__(self, tmp, policy=None):
        self.repo = Path(tmp) / "repo"
        self.home = Path(tmp) / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.policy = json.loads(json.dumps(policy or MINIMAL_POLICY))

    def save_policy(self):
        write(self.repo / "mirror-policy.json",
              json.dumps(self.policy, indent=2) + "\n")

    def add_agent(self, name, body="body\n"):
        write(self.repo / ".claude" / "agents" / (name + ".md"),
              agent_file(name, body))

    def add_command(self, name):
        write(self.repo / ".claude" / "commands" / (name + ".md"),
              "# %s\n\ndo the thing\n" % name)

    def mirror_agent(self, name, body="body\n"):
        write(self.repo / ".github" / "agents" / (name + ".agent.md"),
              agent_file(name, body))

    def mirror_prompt(self, name):
        write(self.repo / ".github" / "prompts" / (name + ".prompt.md"),
              "---\ndescription: \"x\"\n---\n\nbody\n")

    def mirror_cli_agent(self, name, body="body\n"):
        write(self.home / ".copilot" / "agents" / (name + ".agent.md"),
              agent_file(name, body))

    def collect(self):
        return cm.collect(self.repo, self.home, now=FIXED_NOW)


def cell(snapshot, target, name):
    for row in snapshot["rows"]:
        if row["target"] == target and row["name"] == name:
            return row
    raise AssertionError("no cell for %s / %s" % (target, name))


class MirrorMatrixTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.fx = MatrixFixture(self.tmp)

    # --- the two states the whole matrix exists to keep apart ---------------

    def test_a_by_design_skip_is_never_reported_as_lost(self):
        """The defect the matrix exists to prevent. `concis` has no prompt mirror
        and never should have one; calling that a loss sends someone hunting for
        a file the generator deliberately never wrote."""
        self.fx.add_command("concis")
        self.fx.add_command("auditpaper")
        self.fx.mirror_prompt("auditpaper")
        self.fx.save_policy()
        snap = self.fx.collect()
        self.assertEqual(cell(snap, "copilot-prompts", "concis")["state"]["value"],
                         cm.BY_DESIGN)
        self.assertIn("mirror-policy.json",
                      cell(snap, "copilot-prompts", "concis")["state"]["proven_by"])

    def test_a_lost_cell_is_never_softened_into_by_design(self):
        """The other direction, which matters more: a command the policy does NOT
        name is missing its mirror, and that is a real loss."""
        self.fx.add_command("auditpaper")          # no mirror written
        self.fx.save_policy()
        snap = self.fx.collect()
        row = cell(snap, "copilot-prompts", "auditpaper")
        self.assertEqual(row["state"]["value"], cm.LOST)
        self.assertIn("no file at", row["reason"])

    def test_removing_a_name_from_the_skip_list_turns_the_cell_lost(self):
        """Proves the by-design verdict is driven by the policy rather than by the
        collector's own opinion: same tree, edited policy, opposite verdict."""
        self.fx.add_command("concis")
        self.fx.save_policy()
        self.assertEqual(
            cell(self.fx.collect(), "copilot-prompts", "concis")["state"]["value"],
            cm.BY_DESIGN)
        self.fx.policy["skips"]["session_mode_commands"]["values"] = []
        self.fx.save_policy()
        self.assertEqual(
            cell(self.fx.collect(), "copilot-prompts", "concis")["state"]["value"],
            cm.LOST)

    # --- the fresh-clone case, which is most other users --------------------

    def test_the_matrix_is_complete_from_the_policy_alone(self):
        """No manifest, no install ever run, no user-scoped dialect present. The
        matrix must still carry every definition against every column."""
        self.fx.add_agent("alpha")
        self.fx.add_command("auditpaper")
        self.fx.save_policy()
        snap = self.fx.collect()
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["counts"]["agents"], 1)
        targets = {row["target"] for row in snap["rows"]}
        self.assertIn("copilot-agents", targets)
        self.assertIn("copilot-prompts", targets)
        self.assertIn("copilot-cli-agents", targets)

    def test_a_missing_manifest_degrades_only_the_drift_column_and_says_so(self):
        """It must never read as 'all fine'. The matrix is complete without a
        manifest; what becomes unanswerable is drift SINCE an install, and an
        unanswerable question is printed as unavailable with its reason."""
        self.fx.add_agent("alpha")
        self.fx.save_policy()
        snap = self.fx.collect()
        self.assertEqual(snap["manifest"]["status"], "unavailable")
        self.assertIn("install.ps1 -Manifest", snap["manifest"]["reason"])
        self.assertEqual(snap["status"], "ok")

    def test_a_manifest_written_under_another_policy_is_flagged(self):
        """A manifest whose policy hash no longer matches describes rules that
        have since changed, so its verdicts cannot be trusted silently."""
        self.fx.add_agent("alpha")
        self.fx.mirror_agent("alpha")
        self.fx.save_policy()
        write(self.fx.repo / ".rt-mirrors.json", json.dumps({
            "generated": "2026-01-01T00:00:00",
            "policy_hash": "NOT-THE-CURRENT-HASH",
            "personal_run": False,
            "verdicts": [],
        }))
        snap = self.fx.collect()
        self.assertEqual(snap["manifest"]["status"], "ok")
        self.assertFalse(snap["manifest"]["policy_matches"])
        self.assertIn("different mirror-policy.json", snap["manifest"]["reason"])

    # --- an absent user-scoped dialect is not seventeen losses --------------

    def test_an_uninstalled_dialect_is_unknown_rather_than_lost(self):
        """A user who never ran -Personal has no ~/.copilot at all. Reporting
        every agent as lost there would bury the real losses in noise."""
        self.fx.add_agent("alpha")
        self.fx.save_policy()
        row = cell(self.fx.collect(), "copilot-cli-agents", "alpha")
        self.assertEqual(row["state"]["value"], cm.UNKNOWN)
        self.assertIn("-Personal", row["reason"])

    def test_the_six_agent_copilot_cli_gap_reproduces_as_lost(self):
        """The measured 2026-08-30 defect, rebuilt from fixtures: the directory
        EXISTS, so the dialect is installed, and the agents added since the last
        -Personal run are genuinely absent from it."""
        for name in ("alpha", "beta", "gamma"):
            self.fx.add_agent(name)
        self.fx.mirror_cli_agent("alpha")          # only one of three copied
        self.fx.save_policy()
        snap = self.fx.collect()
        self.assertEqual(cell(snap, "copilot-cli-agents", "alpha")["state"]["value"],
                         cm.OK)
        for missing in ("beta", "gamma"):
            row = cell(snap, "copilot-cli-agents", missing)
            self.assertEqual(row["state"]["value"], cm.LOST)
            self.assertIn("-Personal", row["reason"])

    # --- degradation stays distinguishable from ok -------------------------

    def test_a_stub_is_reported_stubbed_and_not_ok(self):
        """A stub carries none of the agent's instructions. Reporting it green is
        how local-writer.md mirrored as a pointer for three regenerations."""
        self.fx.add_agent("alpha", body="x" * 4000)
        self.fx.mirror_agent("alpha", body="read the real file\n")
        self.fx.save_policy()
        row = cell(self.fx.collect(), "copilot-agents", "alpha")
        self.assertEqual(row["state"]["value"], cm.STUBBED)

    def test_a_full_mirror_of_a_large_agent_is_not_called_a_stub(self):
        """The negative control for the size heuristic: a big agent mirrored in
        full must stay ok, or every long agent reads as degraded."""
        self.fx.add_agent("alpha", body="x" * 4000)
        self.fx.mirror_agent("alpha", body="x" * 4000)
        self.fx.save_policy()
        row = cell(self.fx.collect(), "copilot-agents", "alpha")
        self.assertEqual(row["state"]["value"], cm.OK)

    def test_the_manifest_verdict_outranks_the_heuristic(self):
        """install.ps1 decided the verdict at generation time and recorded it.
        A recorded 'stubbed' wins over anything inferred from file sizes."""
        self.fx.add_agent("alpha", body="x" * 4000)
        self.fx.mirror_agent("alpha", body="x" * 4000)
        self.fx.save_policy()
        policy_hash = cm.policy_hash(self.fx.repo)
        write(self.fx.repo / ".rt-mirrors.json", json.dumps({
            "generated": "2026-08-30T12:00:00",
            "policy_hash": policy_hash,
            "personal_run": True,
            "verdicts": [{"target": "copilot-agents", "name": "alpha",
                          "state": "stubbed", "body_chars": 4000}],
        }))
        row = cell(self.fx.collect(), "copilot-agents", "alpha")
        self.assertEqual(row["state"]["value"], cm.STUBBED)
        self.assertEqual(row["state"]["proven_by"], ".rt-mirrors.json")

    def test_a_mirror_older_than_its_source_is_stale_not_ok(self):
        self.fx.add_agent("alpha")
        self.fx.mirror_agent("alpha")
        self.fx.save_policy()
        mirror = self.fx.repo / ".github" / "agents" / "alpha.agent.md"
        source = self.fx.repo / ".claude" / "agents" / "alpha.md"
        import os
        os.utime(mirror, (1000, 1000))
        os.utime(source, (900000, 900000))
        row = cell(self.fx.collect(), "copilot-agents", "alpha")
        self.assertEqual(row["state"]["value"], cm.STALE)

    # --- orphans -----------------------------------------------------------

    def test_a_mirror_with_no_canonical_source_is_an_orphan(self):
        self.fx.add_agent("alpha")
        self.fx.mirror_agent("alpha")
        self.fx.mirror_agent("ghost")             # nothing canonical named ghost
        self.fx.save_policy()
        row = cell(self.fx.collect(), "copilot-agents", "ghost")
        self.assertEqual(row["state"]["value"], cm.ORPHAN)

    def test_an_orphan_named_in_the_policy_is_by_design(self):
        """The mermaid case: a hand-maintained instructions file with no rule
        behind it, which is deliberate and must not read as debris."""
        self.fx.add_agent("alpha")
        self.fx.mirror_agent("alpha")
        self.fx.mirror_agent("ghost")
        self.fx.policy["orphans_by_design"] = {"copilot-agents": {"values": ["ghost"]}}
        self.fx.save_policy()
        row = cell(self.fx.collect(), "copilot-agents", "ghost")
        self.assertEqual(row["state"]["value"], cm.BY_DESIGN)

    # --- refusals ----------------------------------------------------------

    def test_a_missing_policy_is_a_named_refusal_not_a_guess(self):
        """No silent default (R3, R8): a matrix built on an invented policy would
        report by-design and lost interchangeably, which is worse than nothing."""
        self.fx.add_agent("alpha")                # policy deliberately not saved
        with self.assertRaises(cm.PolicyError) as caught:
            self.fx.collect()
        self.assertIn("mirror-policy.json", str(caught.exception))

    def test_an_unparsable_policy_is_a_named_refusal(self):
        self.fx.add_agent("alpha")
        write(self.fx.repo / "mirror-policy.json", "{ this is not json ")
        with self.assertRaises(cm.PolicyError):
            self.fx.collect()

    def test_a_corrupt_manifest_degrades_rather_than_raising(self):
        """The manifest is an enrichment. A damaged one must cost its own column
        and nothing else."""
        self.fx.add_agent("alpha")
        self.fx.mirror_agent("alpha")
        self.fx.save_policy()
        write(self.fx.repo / ".rt-mirrors.json", "{ broken ")
        snap = self.fx.collect()
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["manifest"]["status"], "unavailable")

    # --- receipts ----------------------------------------------------------

    def test_every_cell_carries_a_receipt(self):
        """No bare badges. A state with no provenance cannot be judged stale, and
        'green from three days ago' would read as 'green now'."""
        self.fx.add_agent("alpha")
        self.fx.add_command("concis")
        self.fx.save_policy()
        for row in self.fx.collect()["rows"]:
            self.assertIn("proven_by", row["state"], row)
            self.assertTrue(row["state"]["proven_by"], row)
            self.assertEqual(row["state"]["proven_at"],
                             FIXED_NOW.isoformat(timespec="seconds"))

    def test_the_snapshot_is_reproducible_for_a_fixed_clock(self):
        """R19: the timestamp is injected, never read inside the collector, so
        two runs over an unchanged tree are byte-identical."""
        self.fx.add_agent("alpha")
        self.fx.save_policy()
        first = json.dumps(self.fx.collect(), sort_keys=True)
        second = json.dumps(self.fx.collect(), sort_keys=True)
        self.assertEqual(first, second)


class SnapshotAssemblyTest(unittest.TestCase):
    """rt_state's own contract, separately from the collector's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = MatrixFixture(self._tmp.name)
        self.config = rt_state.load_config()

    def test_a_policy_failure_degrades_the_panel_not_the_snapshot(self):
        """One collector failing must never take the page down: the section says
        unavailable with its reason and the rest of the snapshot survives."""
        self.fx.add_agent("alpha")                # no policy written
        snap = rt_state.build_snapshot(self.fx.repo, self.fx.home,
                                       now=FIXED_NOW, config=self.config)
        self.assertEqual(snap["mirrors"]["status"], "unavailable")
        self.assertIn("mirror-policy.json", snap["mirrors"]["reason"])
        self.assertEqual(snap["generated"], FIXED_NOW.isoformat(timespec="seconds"))
        self.assertEqual(snap["repo"]["root"], str(self.fx.repo))

    def test_a_missing_config_key_is_named_rather_than_defaulted(self):
        with self.assertRaises(rt_state.ConfigError) as caught:
            rt_state.config_value(self.config, "server", "no_such_key")
        self.assertIn("server.no_such_key", str(caught.exception))

    def test_the_shipped_config_declares_the_values_the_code_reads(self):
        """A config that parses but declares nothing would disable every limit in
        silence. Each key the code depends on is asserted present here."""
        self.assertEqual(rt_state.config_value(self.config, "server", "bind_host"),
                         "127.0.0.1")
        for path in (("server", "port"),
                     ("ttl_seconds", "mirrors"),
                     ("timeouts_seconds", "subprocess_default"),
                     ("caps", "prompt_chars"),
                     ("paths", "action_log")):
            self.assertIsNotNone(rt_state.config_value(self.config, *path), path)

    def test_the_server_never_binds_a_routable_interface(self):
        """security.md: bind a specific interface, never 0.0.0.0. Asserted on the
        shipped config so a later edit cannot quietly widen it."""
        self.assertNotEqual(rt_state.config_value(self.config, "server", "bind_host"),
                            "0.0.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
