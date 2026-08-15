"""
test_obsidian_outbox_flush - offline checks for the vault write path.

No network, no Obsidian, no real vault: every case runs against a temporary tree.
The four cases are the ones that used to fail in production (see
docs/superpowers/plans/2026-08-13-obsidian-vault-divergence-analysis.md section 2).
"""
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOOK = Path(__file__).resolve().parents[1] / "obsidian-outbox-flush.py"


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

    def test_missing_vault_leaves_the_outbox_intact(self):
        self.mod.VAULT_DEFAULT = self.tmp / "no-such-vault"
        p = self._note("keep.md",
                       '<!-- obsidian: create path="30_Ressources/Obsidian/k.md" -->',
                       "payload")
        self.assertEqual(self.mod.main(), 0)
        self.assertTrue(p.exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
