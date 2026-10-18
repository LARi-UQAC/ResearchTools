"""
test_token_count.py - offline tests for token_count.py, the one counter for any text source
(local coding contract, plan 1, task 3).

No network and no installed package is assumed (R21): the encoder and the daemon probe are
injected or patched. Fixtures are fictitious (R34). Failure paths sit beside happy paths (R20).

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_token_count.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import token_count as tc  # noqa: E402


def entry(value):
    """Wrap a value the way the shipped config does."""
    return {"value": value, "provenance": "test fixture"}


CONFIG = {
    "encoding": entry("cl100k_base"),
    "chars_per_token": entry(4.0),
    "estimate_margin": entry(1.25),
    "binary_probe_bytes": entry(64),
    "max_file_bytes": entry(1000),
    "skip_dir_names": entry([".git"]),
}


class WordEncoder:
    """A fake encoder whose token is one whitespace-separated word."""

    def encode(self, text):
        return text.split()


NO_ENCODER = (None, "tiktoken is not installed")


class TestCountText(unittest.TestCase):
    def test_auto_uses_the_encoder_when_it_loads_and_reports_exact(self):
        result = tc.count_text("one two three", encoder=WordEncoder(), config=CONFIG)
        self.assertEqual((result.tokens, result.method, result.exact), (3, "tiktoken", True))

    def test_auto_without_an_encoder_estimates_and_says_it_is_not_exact(self):
        with mock.patch.object(tc, "_load_encoder", return_value=NO_ENCODER):
            result = tc.count_text("a" * 40, config=CONFIG)
        self.assertEqual((result.tokens, result.method, result.exact), (10, "chars", False))
        self.assertIn("not installed", result.note)

    def test_method_tiktoken_without_an_encoder_is_a_refusal_not_a_fallback(self):
        with mock.patch.object(tc, "_load_encoder", return_value=NO_ENCODER):
            with self.assertRaises(tc.TokenCountError) as ctx:
                tc.count_text("abc", method="tiktoken", config=CONFIG)
        self.assertIn("not installed", str(ctx.exception))

    def test_an_unknown_method_is_refused(self):
        with self.assertRaises(tc.TokenCountError):
            tc.count_text("abc", method="guess", config=CONFIG)

    def test_the_ratio_and_the_margin_come_from_the_config(self):
        cfg = dict(CONFIG, chars_per_token=entry(2.0))
        with mock.patch.object(tc, "_load_encoder", return_value=NO_ENCODER):
            self.assertEqual(tc.count_text("abcd", config=cfg).tokens, 2)
            self.assertEqual(tc.count_text("abcd", config=CONFIG).tokens, 1)
        self.assertFalse(tc.within_ceiling(tc.TokenCount(81, "chars", False, None), 100, 1.25))
        self.assertTrue(tc.within_ceiling(tc.TokenCount(81, "chars", False, None), 100, 1.0))

    def test_an_empty_source_counts_zero(self):
        self.assertEqual(tc.count_text("", encoder=WordEncoder(), config=CONFIG).tokens, 0)
        with mock.patch.object(tc, "_load_encoder", return_value=NO_ENCODER):
            self.assertEqual(tc.count_text("", config=CONFIG).tokens, 0)

    def test_the_ollama_method_uses_the_probe_and_refuses_with_the_daemons_reason(self):
        ok = tc.count_text("hello", method="ollama", model_tag="tag:1b", config=CONFIG,
                           probe=lambda text, tag: 7)
        self.assertEqual((ok.tokens, ok.method, ok.exact), (7, "ollama", True))

        def down(text, tag):
            raise ConnectionError("daemon is down")

        with self.assertRaises(tc.TokenCountError) as ctx:
            tc.count_text("hello", method="ollama", model_tag="tag:1b", config=CONFIG,
                          probe=down)
        self.assertIn("daemon is down", str(ctx.exception))
        with self.assertRaises(tc.TokenCountError):
            tc.count_text("hello", method="ollama", config=CONFIG, probe=lambda t, g: 1)


class TestWithinCeiling(unittest.TestCase):
    def test_within_ceiling_at_the_boundary_both_ways(self):
        exact = lambda n: tc.TokenCount(n, "tiktoken", True, None)  # noqa: E731
        est = lambda n: tc.TokenCount(n, "chars", False, None)  # noqa: E731
        self.assertTrue(tc.within_ceiling(exact(100), 100, 1.25))
        self.assertFalse(tc.within_ceiling(exact(101), 100, 1.25))
        self.assertTrue(tc.within_ceiling(est(80), 100, 1.25))
        self.assertFalse(tc.within_ceiling(est(81), 100, 1.25))


class TestSources(unittest.TestCase):
    def collect(self, paths, glob=None, **kw):
        return {name: (text, why) for name, text, why in
                tc.iter_sources(paths, glob, config=CONFIG, **kw)}

    def test_a_binary_file_is_skipped_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            blob = Path(tmp) / "blob.dat"
            blob.write_bytes(b"ab\x00cd")
            found = self.collect([str(blob)])
            text, why = found[str(blob)]
            self.assertIsNone(text)
            self.assertIn("binary", why)

    def test_a_file_over_the_size_cap_is_skipped_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.txt"
            big.write_text("x" * 1001, encoding="utf-8")
            text, why = self.collect([str(big)])[str(big)]
            self.assertIsNone(text)
            self.assertIn("1000", why)

    def test_a_folder_is_walked_and_the_glob_filters_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("alpha", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.py").write_text("beta", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "c.py").write_text("hidden", encoding="utf-8")
            everything = self.collect([str(root)])
            self.assertEqual(sorted(Path(n).name for n in everything), ["a.md", "b.py"])
            only_py = self.collect([str(root)], "*.py")
            self.assertEqual([Path(n).name for n in only_py], ["b.py"])

    def test_stdin_and_a_missing_path_are_handled(self):
        found = self.collect(["-"], stdin=io.BytesIO(b"from stdin"))
        self.assertEqual(found["<stdin>"], ("from stdin", None))
        text, why = self.collect(["Z:/no/such/file.txt"])["Z:/no/such/file.txt"]
        self.assertIsNone(text)
        self.assertEqual(why, "not found")

    def test_invalid_utf8_is_counted_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "odd.txt"
            odd.write_bytes(b"caf\xe9 au lait")
            text, why = self.collect([str(odd)])[str(odd)]
            self.assertIsNone(why)
            self.assertIn("lait", text)
            self.assertGreater(tc.count_text(text, encoder=WordEncoder(), config=CONFIG).tokens, 0)


class TestCli(unittest.TestCase):
    def run_cli(self, *argv, stdin=None):
        buf = io.StringIO()
        with mock.patch.object(tc, "_load_encoder", return_value=(WordEncoder(), None)):
            with redirect_stdout(buf):
                code = tc.main(list(argv), config=CONFIG, stdin=stdin)
        return code, buf.getvalue()

    def test_text_and_stdin_are_sources_and_the_json_has_the_keys_a_caller_reads(self):
        code, out = self.run_cli("--text", "one two", "-", "--json",
                                 stdin=io.BytesIO(b"three four five"))
        report = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(report["total_tokens"], 5)
        self.assertTrue(report["all_exact"])
        names = [s["name"] for s in report["sources"]]
        self.assertEqual(names, ["<text 1>", "<stdin>"])
        for key in ("name", "tokens", "method", "exact", "note", "skipped", "over"):
            self.assertIn(key, report["sources"][0])

    def test_max_sets_exit_2_when_a_source_is_over_and_0_at_the_ceiling(self):
        code, out = self.run_cli("--text", "a b c", "--max", "3", "--json")
        self.assertEqual(code, 0)
        code, out = self.run_cli("--text", "a b c d", "--max", "3", "--json")
        report = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(report["over"], ["<text 1>"])

    def test_a_missing_path_exits_1_and_a_refused_method_exits_2(self):
        code, _ = self.run_cli("Z:/no/such/file.txt", "--json")
        self.assertEqual(code, 1)
        with mock.patch.object(tc, "_load_encoder", return_value=NO_ENCODER):
            with redirect_stdout(io.StringIO()):
                code = tc.main(["--text", "x", "--method", "tiktoken", "--json"], config=CONFIG)
        self.assertEqual(code, 2)


class TestCeilingGaps(unittest.TestCase):
    """Fixes for the code review of 2026-10-17 (R35 round 1)."""

    def run_cli(self, *argv):
        buf = io.StringIO()
        with mock.patch.object(tc, "_load_encoder", return_value=(WordEncoder(), None)):
            with redirect_stdout(buf):
                code = tc.main(list(argv), config=CONFIG)
        return code, json.loads(buf.getvalue())

    def test_a_source_that_could_not_be_counted_cannot_pass_a_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.txt"
            big.write_text("x" * 1001, encoding="utf-8")
            code, report = self.run_cli(str(big), "--max", "4000", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(report["unchecked"], [str(big)])
        # without --max the skipped file stays informational
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.txt"
            big.write_text("x" * 1001, encoding="utf-8")
            code, report = self.run_cli(str(big), "--json")
        self.assertEqual(code, 0)

    def test_a_missing_path_never_hides_an_over_ceiling_source(self):
        code, report = self.run_cli("--text", "a b c d", "Z:/no/such/file.txt", "--max", "3",
                                    "--json")
        self.assertEqual(code, 2)
        self.assertEqual(report["over"], ["<text 1>"])


class TestEncoderTimeout(unittest.TestCase):
    """R35 round 2 (R10): loading an encoder may download a file, so it is bounded."""

    def test_a_slow_encoder_load_is_a_stated_degradation_not_a_hang(self):
        import threading
        import types
        gate = threading.Event()

        def slow(name):
            gate.wait(5)
            return WordEncoder()

        fake = types.SimpleNamespace(get_encoding=slow)
        with mock.patch.dict(sys.modules, {"tiktoken": fake}):
            enc, reason = tc._load_encoder("cl100k_base", timeout_s=0.2)
        gate.set()
        self.assertIsNone(enc)
        self.assertIn("timed out", reason)

    def test_a_quick_load_still_returns_the_encoder(self):
        import types
        fake = types.SimpleNamespace(get_encoding=lambda name: WordEncoder())
        with mock.patch.dict(sys.modules, {"tiktoken": fake}):
            enc, reason = tc._load_encoder("cl100k_base", timeout_s=2)
        self.assertIsNotNone(enc)
        self.assertIsNone(reason)

    def test_the_timeout_comes_from_the_config(self):
        self.assertTrue(tc.load_config()["encoder_load_timeout_s"]["provenance"])


class TestConfig(unittest.TestCase):
    def test_a_missing_key_is_a_named_error_and_the_shipped_file_has_provenance(self):
        with self.assertRaises(KeyError) as ctx:
            tc.config_value({"encoding": entry("x")}, "estimate_margin")
        self.assertIn("estimate_margin", str(ctx.exception))
        shipped = tc.load_config()
        for key in CONFIG:
            self.assertTrue(shipped[key]["provenance"], key)
            tc.config_value(shipped, key)


if __name__ == "__main__":
    unittest.main()
