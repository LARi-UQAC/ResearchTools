"""
test_obsidian_outbox_flush - offline checks for the vault write path.

No network, no Obsidian, no real vault: every case runs against a temporary tree.
The four cases are the ones that used to fail in production (see
docs/superpowers/plans/2026-08-13-obsidian-vault-divergence-analysis.md section 2).
"""
import importlib.util
import io
import json
import os
import socket
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HOOK = Path(__file__).resolve().parents[1] / "obsidian-outbox-flush.py"
DIRECTIVE_N = '<!-- obsidian: create path="30_Ressources/Obsidian/n.md" -->'
DIRECTIVE_A = '<!-- obsidian: create path="30_Ressources/Obsidian/a.md" -->'


def load_hook(vault: Path, outbox: Path):
    spec = importlib.util.spec_from_file_location("flush", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUTBOX = outbox
    mod.SENT = outbox / "sent"
    mod.VAULT_DEFAULT = vault
    return mod


class OutboxFlushTest(unittest.TestCase):
    def setUp(self):
        # Isolate from a real OBSIDIAN_VAULT set on the host machine.
        # resolve_vault() gives the environment variable priority over
        # VAULT_DEFAULT, so a real value here would point this suite at the
        # professor's actual vault instead of the temporary one built below.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OBSIDIAN_VAULT", None)

        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "Vault"
        (self.vault / "30_Ressources" / "Obsidian").mkdir(parents=True)
        self.outbox = self.tmp / "outbox"
        self.outbox.mkdir()
        self.mod = load_hook(self.vault, self.outbox)

        # P12: PROVE the redirection took effect BEFORE any case writes a byte.
        # Twice in this programme a test aimed at a temporary vault reached the real
        # one - once in plan 1's RED phase, once on 2026-08-14 when the live hook was
        # still a pre-plan-1 copy that ignored OBSIDIAN_VAULT entirely and wrote a
        # stray note into the professor's vault. Redirecting is not isolating; only
        # the module under test can confirm where it will actually write, and the
        # cheapest moment to ask is before it has written anything.
        resolved = self.mod.resolve_vault()
        self.assertEqual(
            resolved, self.vault,
            f"vault redirection did not take effect: the hook would write to {resolved}. "
            "Refusing to run the case rather than risk touching a real vault.",
        )

    def _note(self, name, directive, body):
        p = self.outbox / name
        p.write_text(directive + "\n" + body, encoding="utf-8")
        return p

    def test_empty_outbox_is_a_noop(self):
        self.assertEqual(self.mod.main(), 0)

    def test_note_larger_than_the_cli_threshold_is_written(self):
        body = "x" * 6000
        self._note("big.md",
                   '<!-- obsidian: create path="30_Ressources/Obsidian/big.md" -->',
                   body)
        self.mod.main()
        target = self.vault / "30_Ressources/Obsidian/big.md"
        self.assertTrue(target.exists())
        self.assertGreater(target.stat().st_size, 4096)

    def test_replay_does_not_duplicate(self):
        directive = '<!-- obsidian: create path="30_Ressources/Obsidian/n.md" -->'
        self._note("n.md", directive, "body one")
        self.mod.main()
        size = (self.vault / "30_Ressources/Obsidian/n.md").stat().st_size
        self._note("n.md", directive, "body one")
        self.mod.main()
        self.assertEqual((self.vault / "30_Ressources/Obsidian/n.md").stat().st_size, size)

    def test_path_escaping_the_vault_is_refused(self):
        p = self._note("bad.md",
                       '<!-- obsidian: create path="../../escape.md" -->',
                       "payload")
        self.mod.main()
        self.assertTrue(p.exists(), "refused note must stay in the outbox")
        self.assertFalse((self.tmp / "escape.md").exists())

    def test_precondition_catches_a_redirection_that_did_not_take(self):
        """The guard in setUp is only worth having if it FAILS when the hook ignores
        the redirection. Simulated by pointing the module at a different vault."""
        self.mod.VAULT_DEFAULT = self.tmp / "some-other-vault"
        (self.tmp / "some-other-vault").mkdir()
        self.assertNotEqual(self.mod.resolve_vault(), self.vault)

    def test_unresolved_link_is_warned_about_but_still_written(self):
        """P14: the rule 'wrap an illustrative link in backticks' lived in an agent
        definition and was enforced nowhere, so the first note written after it was
        stated created three phantoms of its own. It is a warning, never a refusal: a
        link to a note that does not exist yet is legitimate in Obsidian."""
        self._note("n.md",
                   '<!-- obsidian: create path="30_Ressources/Obsidian/n.md" -->',
                   "prose with [[NoSuchNote]] and a backticked `[[Example]]`\n")
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.mod.main()
            messages = err.getvalue()
        self.assertTrue((self.vault / "30_Ressources/Obsidian/n.md").exists())
        self.assertIn("NoSuchNote", messages)
        self.assertNotIn("Example", messages, "a backticked link must not be flagged")

    def test_a_link_to_an_existing_note_is_not_flagged(self):
        (self.vault / "30_Ressources" / "Obsidian" / "Target.md").write_text(
            "body\n", encoding="utf-8")
        self._note("n.md",
                   '<!-- obsidian: create path="30_Ressources/Obsidian/n.md" -->',
                   "see [[Target]] and [[Obsidian/Target|the target]]\n")
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.mod.main()
            messages = err.getvalue()
        self.assertNotIn("resolve to nothing", messages)

    def test_parked_drops_are_reported_at_session_start(self):
        """A parked drop nobody is told about is a learning lost. Nothing else
        in the system mentions needs-review/, so the hook that already runs at
        SessionStart is what surfaces it."""
        parked = self.outbox / "needs-review"
        parked.mkdir()
        (parked / "a-lock-was-left.md").write_text("<!-- parked: low confidence -->",
                                                   encoding="utf-8")
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(self.mod.main(), 0)
            messages = err.getvalue()
        self.assertIn("1 drop(s) parked", messages)
        self.assertIn("a-lock-was-left.md", messages)
        self.assertIn("local-writer", messages)

    def test_an_empty_needs_review_folder_says_nothing(self):
        (self.outbox / "needs-review").mkdir()
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.mod.main()
        self.assertNotIn("parked", err.getvalue())

    def test_missing_vault_leaves_the_outbox_intact(self):
        self.mod.VAULT_DEFAULT = self.tmp / "no-such-vault"
        p = self._note("keep.md",
                       '<!-- obsidian: create path="30_Ressources/Obsidian/k.md" -->',
                       "payload")
        self.assertEqual(self.mod.main(), 0)
        self.assertTrue(p.exists())
    def test_a_raw_drop_is_not_flushed_by_the_hook(self):
        """Stage 0 boundary: outbox/raw/ carries UNROUTED drops with no directive.
        Routing them is the daemon's job, and the hook must leave them alone
        rather than skipping them noisily on every session start."""
        raw = self.outbox / "raw"
        raw.mkdir()
        drop = raw / "unrouted.md"
        drop.write_text("subject: something learned", encoding="utf-8")
        self.mod.main()
        self.assertTrue(drop.exists())

    def test_the_flush_never_creates_a_sent_folder_inside_raw(self):
        """raw/ is the daemon's INPUT queue and holds drops, nothing else.

        Measured 2026-08-30: an empty ~/.claude/obsidian-outbox/raw/sent/ existed,
        created 2026-08-28. Nothing in the design puts one there, so something ran
        the flush with raw/ as its outbox root, and an archive folder appeared one
        level too deep. Harmless that day, because it was empty; not harmless in
        general, since a note archived into raw/sent/ is filed nowhere and is also
        no longer a drop the daemon will see.

        Both directions are asserted. A sent/ must NOT appear inside raw/, and a
        sent/ MUST appear where it belongs for a routed note, or the first
        assertion would pass simply because the flush archives nothing at all.
        """
        drop = self._raw_drop()
        routed = self._note("routed.md", DIRECTIVE_N, "payload")

        self.assertEqual(self.mod.main(), 0)

        raw = self.outbox / "raw"
        self.assertFalse((raw / "sent").exists(),
                         "the flush created a sent/ inside the daemon's input queue")
        self.assertEqual([], [p.name for p in raw.iterdir() if p.is_dir()],
                         "raw/ holds drops only; no directory belongs in it")
        self.assertTrue(drop.exists(), "the raw drop must survive untouched")
        self.assertTrue((self.outbox / "sent" / routed.name).exists(),
                        "the routed note was not archived, so the negative "
                        "assertion above proves nothing")

    # Injected, never read from the shipped daemon-config.json, so the staleness
    # ceiling a case relies on cannot change under it (R21 in spirit).
    LOCK_FIXTURE = {"lock": {"stale_after_s": 300.0,
                             "hook_acquire_timeout_s": 0.2,
                             "acquire_timeout_s": 0.2,
                             "poll_interval_s": 0.01}}

    def _raw_drop(self, name="unrouted.md"):
        raw = self.outbox / "raw"
        raw.mkdir(exist_ok=True)
        drop = raw / name
        drop.write_text("---\nsource: local-coder\nsubject: something learned\n"
                        "---\nbody\n", encoding="utf-8")
        return drop

    def _run_with_fixture_config(self):
        """main() under an injected lock config, capturing stderr."""
        outbox_io, _ = self.mod._load()
        with mock.patch.object(outbox_io, "load_config",
                               return_value=self.LOCK_FIXTURE):
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                code = self.mod.main()
                return code, err.getvalue()

    def _write_daemon_lock(self, pid, age_s=0.0):
        stamp = datetime.now(timezone.utc).timestamp() - age_s
        self.mod._daemon_lock_path().write_text(json.dumps({
            "pid": pid, "host": socket.gethostname(), "token": "someone-elses",
            "at": datetime.fromtimestamp(stamp, timezone.utc)
                          .replace(microsecond=0).isoformat(),
        }), encoding="utf-8")

    def test_raw_drops_with_no_daemon_running_are_reported(self):
        """The gap this closes: local-writer hands an unrouted learning to raw/
        and stops. Nothing starts the daemon, so with no report the drop sits in
        a folder nobody opens - the same silence already fixed for
        needs-review/."""
        self._raw_drop()
        code, messages = self._run_with_fixture_config()
        self.assertEqual(code, 0)
        self.assertIn("1 raw drop(s) waiting", messages)
        self.assertIn("vault_daemon.py", messages)

    def test_a_live_daemon_lock_makes_the_report_silent(self):
        """A daemon IS running, so the drops are about to be consumed and there
        is nothing to say."""
        self._raw_drop()
        _, vault_lock = self.mod._load()
        holder = vault_lock.VaultLock(self.mod._daemon_lock_path(),
                                      acquire_timeout_s=0, stale_after_s=300,
                                      poll_interval_s=0.01)
        holder.acquire()
        self.addCleanup(holder.release)
        _, messages = self._run_with_fixture_config()
        self.assertNotIn("raw drop(s) waiting", messages)

    def test_a_lock_whose_holder_is_dead_counts_as_no_daemon(self):
        """The failure path (R20). A daemon killed mid-run leaves its singleton
        lock behind. Testing for the file alone would read that as a running
        daemon and stay silent exactly when the report is needed."""
        self._raw_drop()
        _, vault_lock = self.mod._load()
        self._write_daemon_lock(424242)
        with mock.patch.object(vault_lock, "pid_alive", return_value=False):
            _, messages = self._run_with_fixture_config()
        self.assertIn("1 raw drop(s) waiting", messages)
        self.assertTrue(self.mod._daemon_lock_path().exists(),
                        "reporting must not reclaim or delete the lock")

    def test_an_empty_raw_folder_says_nothing(self):
        (self.outbox / "raw").mkdir()
        _, messages = self._run_with_fixture_config()
        self.assertNotIn("raw drop(s) waiting", messages)

    def test_an_unusable_config_keeps_the_raw_report_silent(self):
        """R11 again: the hook degrades to silence rather than to a traceback,
        whatever is missing under it."""
        self._raw_drop()
        outbox_io, _ = self.mod._load()
        with mock.patch.object(outbox_io, "load_config",
                               side_effect=outbox_io.ConfigError("no config")):
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                self.assertEqual(self.mod.main(), 0)
        self.assertNotIn("raw drop(s) waiting", err.getvalue())

    def test_staging_is_atomic_for_a_md_glob(self):
        """A consumer globs *.md only, so the half-written .tmp is invisible."""
        outbox_io, _ = self.mod._load()
        seen = []
        real_replace = outbox_io.os.replace

        def spy(src, dst):
            seen.append(sorted(q.name for q in self.outbox.glob("*.md")))
            return real_replace(src, dst)

        with mock.patch.object(outbox_io.os, "replace", spy):
            staged = outbox_io.stage(self.outbox, "note", "body",
                                     directive=DIRECTIVE_A)
        self.assertEqual(seen, [[]], "the .tmp must not match a *.md glob")
        self.assertEqual(staged.name, "note.md")
        self.assertTrue(staged.read_text(encoding="utf-8").startswith("<!-- obsidian:"))

    def test_a_flush_is_journalled_with_the_size_before_the_write(self):
        self._note("n.md", DIRECTIVE_N, "first body")
        self.mod.main()
        self._note("n2.md", DIRECTIVE_N.replace("create", "append"), "second body")
        self.mod.main()
        records = [json.loads(line) for line
                   in self.mod._journal_path().read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["state"] for r in records],
                         ["PENDING", "WRITE", "PENDING", "WRITE"])
        created, appended = records[1], records[3]
        self.assertEqual(created["before"], 0)
        self.assertEqual(appended["before"], created["after"])
        self.assertGreater(appended["after"], appended["before"])

    def test_a_held_lock_keeps_the_notes_and_still_exits_zero(self):
        """The failure path (R20). A concurrent writer must not cost a note and
        must never block the session: the hook exits 0 and the note waits."""
        _, vault_lock = self.mod._load()
        holder = vault_lock.VaultLock(self.mod._lock_path(), acquire_timeout_s=0.2,
                                      stale_after_s=300, poll_interval_s=0.01)
        holder.acquire()
        self.addCleanup(holder.release)
        note = self._note("n.md", DIRECTIVE_N, "body")
        # A short timeout injected as a fixture, so the case proves the refusal
        # without paying the configured hook wait (R21: never read the live config).
        fast = {"lock": {"hook_acquire_timeout_s": 0.2, "stale_after_s": 300,
                         "poll_interval_s": 0.01}}
        outbox_io, _ = self.mod._load()
        with mock.patch.object(outbox_io, "load_config", return_value=fast):
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                self.assertEqual(self.mod.main(), 0)
                messages = err.getvalue()
        self.assertTrue(note.exists(), "a note must never be lost to lock contention")
        self.assertFalse((self.vault / "30_Ressources/Obsidian/n.md").exists())
        self.assertIn("Notes kept for the next run", messages)

    def test_a_missing_skill_makes_the_hook_a_silent_noop(self):
        """R11: a hook whose dependency is absent exits 0 and says nothing. A
        non-zero code here refuses every tool in the matcher, which is what cost
        four unusable turns on 2026-08-27."""
        note = self._note("n.md", DIRECTIVE_N, "body")
        with mock.patch.object(self.mod, "_load", return_value=None):
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                self.assertEqual(self.mod.main(), 0)
                self.assertEqual(err.getvalue(), "")
            self.assertIsNone(self.mod.resolve_vault())
        self.assertTrue(note.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
