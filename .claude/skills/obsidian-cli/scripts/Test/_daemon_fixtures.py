"""
_daemon_fixtures - the shared harness of the vault event daemon suites.

Not a suite itself: the offline runner discovers `test_*.py`, so this file is
imported and never executed on its own. It exists because the daemon's cases
split naturally in two - what the classifier DECIDES, and what the write path
DOES - and both halves need the same fixture vault, the same injected window and
the same patched network boundary. Duplicating that harness would let the two
suites drift apart while both kept passing.

Everything measured is INJECTED here (R21): the window, the tag, the thresholds.
Nothing reads .claude/local-model-config.json, which describes one GPU and is
gitignored, so no case can pass only on the machine that wrote it.
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


vd = _load("vault_daemon")
ds = _load("daemon_states")

WINDOW = 16384          # injected fixture, never read from the machine (R21)
TAG = "a-tag-from-the-resolver"
TODAY = "2026-08-28"
CONFIG = {
    "lock": {"acquire_timeout_s": 1, "stale_after_s": 300, "poll_interval_s": 0.01},
    "probe": {"request_timeout_s": 5},
    "daemon": {"poll_interval_s": 0.01, "classify_confidence_min": 0.7,
               "draft_max_attempts": 2, "drain_idle_s": 900,
               "consolidate_top_n": 15, "judge_edge_max_pairs": 15,
               "queue_max_entries": 500, "phantom_max_per_drain": 10},
}
GOOD_NOTE = "---\ntype: apprentissage\ndate: 2026-08-28\n---\n\n## Contexte\nUn cas.\n"


def reply(body):
    return {"response": body}


class DaemonCase(unittest.TestCase):
    """A fixture vault, an outbox, and one daemon wired to both."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        for folder in ("Ollama", "Python", "Logiciel"):
            (self.vault / "30_Ressources" / folder).mkdir(parents=True)
        (self.vault / "10_Projets" / "Logiciels" / "ResearchTools").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"
        self.daemon = vd.VaultDaemon(self.vault, self.outbox, CONFIG, today=TODAY)

    def _drop(self, name="a-lock-was-left-behind", subject="a lock was left behind",
              project=None, body="The holder died and the lock stayed."):
        front = f"---\nsource: local-coder\nsubject: {subject}\n"
        if project:
            front += f"project: {project}\n"
        path = self.outbox / "raw" / f"{name}.md"
        path.write_text(front + "---\n" + body + "\n", encoding="utf-8")
        return path

    def _run(self, drop, classification, draft=GOOD_NOTE):
        responses = [reply(json.dumps(classification)), reply(draft)]
        with mock.patch.object(vd.ob, "_post_generate", side_effect=responses):
            return self.daemon.handle(drop, TAG, WINDOW)

    def _note(self, rel, body="body\n"):
        target = self.vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target
