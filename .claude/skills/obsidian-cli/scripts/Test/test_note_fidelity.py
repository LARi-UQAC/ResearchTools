"""The fidelity check a drafted vault note must pass before it is staged.

Measured 2026-09-26: local-writer's local model turned a precise brief into five notes that
all carried facts the brief never gave - an unmeasured "1405 MiB", functions from an
unrelated module (get_store(), load_oo_config()), a wrong [[project]] link - and the wrapper
reported them as correct, since every existing check proved only that the files existed.
The regression cases below use that day's REAL draft and brief, verbatim.

What this check can and cannot see is asserted, not merely documented: it catches a token the
brief never gave; it cannot catch a claim re-worded into its opposite with no new token, and
the last case pins that limit so no document claims more (R15).
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import note_fidelity  # noqa: E402

CONFIG = {"min_integer_digits": {"value": 2},
          "unchecked_frontmatter_keys": {"value": ["type", "domaine", "tags"]}}

REAL_BRIEF = (
    "CUDA caching allocator contaminates sequential VRAM measurements: measuring several "
    "models one after another in ONE Python process under-reports every model after the first, "
    "because freed memory stays reserved by the allocator and inflates the \"before\" reading. "
    "Measure each candidate in a fresh child process. projet \"[[ResearchTools]]\", date 2026-09-26.")

REAL_DRAFT = """<!-- obsidian: create path="30_Ressources/Ollama/cuda-allocator-contamination.md" -->
---
type: apprentissage
projet: "[[feat-voice-memory-query]]"
domaine: logiciel
date: 2026-09-26
tags: [gpu, vram, measurement, llm, stt]
---

# CUDA allocator contamination of sequential VRAM measurements

**Root cause:** Ollama daemon reuses one process. Model N unloads, blocks return to allocator cache.

**Consequence:** Whisper large-v3-turbo on A1000 requires 1405 MiB fresh, but after writer model residency shows higher.
"""


def check(note, brief, config=CONFIG):
    return note_fidelity.check(note, brief, config)


class TokensCase(unittest.TestCase):
    def test_the_real_draft_is_refused_for_what_it_invented(self):
        verdict = check(REAL_DRAFT, REAL_BRIEF)
        self.assertEqual(verdict["status"], "unfaithful")
        self.assertIn("1405", verdict["unsupported"])
        self.assertIn("[[feat-voice-memory-query]]", verdict["unsupported"])

    def test_a_note_built_from_the_brief_passes(self):
        note = ('<!-- obsidian: create path="30_Ressources/Python/x.md" -->\n---\ntype: apprentissage\n'
                'projet: "[[ResearchTools]]"\ndate: 2026-09-26\ntags: [cuda]\n---\n'
                'Measure each candidate in a fresh child process.\n')
        self.assertEqual(check(note, REAL_BRIEF)["status"], "faithful")

    def test_a_function_the_brief_never_named_is_refused(self):
        verdict = check("The fix uses `get_store()` and load_oo_config().", "The daemon answers errors.")
        self.assertIn("get_store()", verdict["unsupported"])
        self.assertIn("load_oo_config()", verdict["unsupported"])

    def test_a_commit_hash_and_a_file_name_must_come_from_the_brief(self):
        verdict = check("Commit 06093d9 edits stt_bench.py and gpu_memory.py.",
                        "Commit 515dd1d edits stt_bench.py.")
        self.assertEqual(sorted(verdict["unsupported"]), ["06093d9", "gpu_memory.py"])

    def test_the_decimal_comma_equals_the_point(self):
        self.assertEqual(check("It moved 0.5 rad per second.", "tourne a 0,5 rad")["status"],
                         "faithful")

    def test_the_directive_path_and_unchecked_frontmatter_are_not_facts(self):
        note = ('<!-- obsidian: create path="30_Ressources/Methode/y_2.md" -->\n---\n'
                'type: apprentissage\ntags: [stt_bench, v3_2]\n---\nPlain prose.\n')
        self.assertEqual(check(note, "Plain prose.")["status"], "faithful")

    def test_single_digits_are_ignored_by_configuration_not_by_accident(self):
        self.assertEqual(check("Five notes, 3 of them wrong.", "Five notes.")["status"], "faithful")
        strict = {**CONFIG, "min_integer_digits": {"value": 1}}
        self.assertIn("3", check("Five notes, 3 of them wrong.", "Five notes.", strict)["unsupported"])

    def test_a_missing_config_key_is_named(self):
        with self.assertRaises(KeyError) as ctx:
            check("x", "x", {"min_integer_digits": {"value": 2}})
        self.assertIn("unchecked_frontmatter_keys", str(ctx.exception))

    def test_known_limit_an_inverted_claim_with_no_new_token_passes(self):
        """Pinned on purpose: the 2026-09-26 WDDM draft inverted the finding ('counters may be
        unreliable') using only words the brief contained. This check cannot see that, and must
        never be described as if it could; reading the staged note is still required."""
        brief = "The per-process counters are reliable; nvidia-smi totals are not."
        self.assertEqual(check("The per-process counters are not reliable.", brief)["status"],
                         "faithful")


class CliCase(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = note_fidelity.main(argv, config=CONFIG)
        return code, out.getvalue()

    def files(self, tmp, note, brief):
        (tmp / "draft.md").write_text(note, encoding="utf-8")
        (tmp / "brief.txt").write_text(brief, encoding="utf-8")
        return str(tmp / "draft.md"), str(tmp / "brief.txt")

    def test_a_faithful_note_is_staged_with_its_directive(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            draft, brief = self.files(tmp, '<!-- obsidian: create path="30_Ressources/Python/a.md" -->\n'
                                           'Measure in a fresh child process.\n', REAL_BRIEF)
            code, out = self.run_cli(["--brief", brief, "--note", draft, "--stage", "a",
                                      "--outbox", str(tmp / "outbox")])
            staged = (tmp / "outbox" / "a.md").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertTrue(staged.startswith('<!-- obsidian: create path="30_Ressources/Python/a.md" -->'))
        self.assertEqual(json.loads(out)["status"], "faithful")

    def test_an_unfaithful_note_is_refused_and_nothing_is_staged(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            draft, brief = self.files(tmp, REAL_DRAFT, REAL_BRIEF)
            code, out = self.run_cli(["--brief", brief, "--note", draft, "--stage", "b",
                                      "--outbox", str(tmp / "outbox")])
            self.assertFalse((tmp / "outbox").exists())
        self.assertEqual(code, 2)
        self.assertIn("1405", json.loads(out)["unsupported"])

    def test_dry_run_stages_nothing_even_when_faithful(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            draft, brief = self.files(tmp, '<!-- obsidian: create path="30_Ressources/Python/c.md" -->\n'
                                           'Measure in a fresh child process.\n', REAL_BRIEF)
            code, out = self.run_cli(["--brief", brief, "--note", draft, "--stage", "c",
                                      "--outbox", str(tmp / "outbox"), "--dry-run"])
            self.assertFalse((tmp / "outbox").exists())
        self.assertEqual(code, 0)
        self.assertIn("would_stage", json.loads(out))

    def test_staging_needs_a_directive_line(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            draft, brief = self.files(tmp, "Measure in a fresh child process.\n", REAL_BRIEF)
            code, _ = self.run_cli(["--brief", brief, "--note", draft, "--stage", "d",
                                    "--outbox", str(tmp / "outbox")])
            self.assertFalse((tmp / "outbox").exists())
        self.assertEqual(code, 2)

    def test_a_missing_brief_is_a_failure_not_a_pass(self):
        with tempfile.TemporaryDirectory() as t:
            code, _ = self.run_cli(["--brief", str(Path(t) / "none.txt"), "--note", REAL_BRIEF])
        self.assertEqual(code, 1)

    def test_the_shipped_config_is_read_by_the_real_entry_point(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            draft, brief = self.files(tmp, "Measure in a fresh child process.\n", REAL_BRIEF)
            out = subprocess.run([sys.executable, str(SCRIPTS / "note_fidelity.py"),
                                  "--brief", brief, "--note", draft],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
