"""
test_context_budget.py - offline unit tests for the planning-time context-budget gate
(P4 Task 5).

Every test builds its OWN temporary local-model-config.json (via a
tempfile.TemporaryDirectory) and passes it through --config / config_path explicitly. No
test reads or writes the real, machine-local .claude/local-model-config.json, since another
machine running this suite before its own Task 4 sweep will not have one yet - that absence
is exactly what test_missing_config_is_explicit_error below exercises on purpose.

Thirteen cases:

  1.  test_compliant_task_returns_zero_and_prints_margin           -> brief test 1
  2.  test_oversized_task_returns_nonzero_and_names_heaviest_item  -> brief test 2
  3.  test_scan_sorts_descending_by_size                            -> brief test 3
  4.  test_missing_config_is_explicit_error                         -> brief test 4
  5.  test_missing_config_cli_error_for_task_and_scan                (CLI-level restatement of 4)
  6.  test_read_retained_num_ctx_empty_file_is_explicit_error
  7.  test_read_retained_num_ctx_invalid_json_is_explicit_error
  8.  test_read_retained_num_ctx_ambiguous_without_tag_is_explicit_error
  9.  test_read_retained_num_ctx_missing_field_is_explicit_error
  10. test_estimate_tokens_heuristic_and_empty_string
  11. test_load_task_items_from_path_and_inline_text
  12. test_scan_excludes_noise_directories_and_binary_extensions
  13. test_check_task_budget_margin_and_heaviest_item_selection

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_context_budget.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import context_budget as cb  # noqa: E402


def _write_config(dir_path: Path, retained_num_ctx: int, tag: str = "vendor-a:9b") -> Path:
    """Shared fixture: a minimal, valid local-model-config.json with one declared model."""
    config_path = dir_path / "local-model-config.json"
    config_path.write_text(
        json.dumps({"models": {tag: {"retained_num_ctx": retained_num_ctx}}}),
        encoding="utf-8",
    )
    return config_path


def _write_spec(dir_path: Path, items: list[dict]) -> Path:
    spec_path = dir_path / "task-spec.json"
    spec_path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return spec_path


class TestCompliantTaskReturnsZeroAndPrintsMargin(unittest.TestCase):
    def test_compliant_task_returns_zero_and_prints_margin(self):
        # Brief test 1: a compliant task returns zero and prints a margin.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_path = _write_config(d, retained_num_ctx=16384)
            spec_path = _write_spec(d, [
                {"name": "small-item", "text": "a" * 400},  # ~100 tokens
            ])

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cb.main([
                    "--task", str(spec_path),
                    "--config", str(config_path),
                ])

        self.assertEqual(rc, 0)
        self.assertIn("OK", buf.getvalue())
        self.assertIn("margin", buf.getvalue().lower())


class TestOversizedTaskNamesHeaviestItem(unittest.TestCase):
    def test_oversized_task_returns_nonzero_and_names_heaviest_item(self):
        # Brief test 2: an oversized task returns non-zero and names the heaviest item.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # A tiny window: budget = 40 - 1024 reserve is already negative, so any item
            # overflows it, and the item named "heavy-item" is unambiguously the largest.
            config_path = _write_config(d, retained_num_ctx=40)
            spec_path = _write_spec(d, [
                {"name": "light-item", "text": "b" * 40},       # ~10 tokens
                {"name": "heavy-item", "text": "c" * 4000},     # ~1000 tokens, the heaviest
                {"name": "medium-item", "text": "d" * 400},     # ~100 tokens
            ])

            buf_out, buf_err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                rc = cb.main([
                    "--task", str(spec_path),
                    "--config", str(config_path),
                ])

        self.assertNotEqual(rc, 0)
        combined = buf_out.getvalue() + buf_err.getvalue()
        self.assertIn("heavy-item", combined)
        self.assertNotIn("REFUSED: " + "light-item is the heaviest", combined)  # sanity guard


class TestScanSortsDescending(unittest.TestCase):
    def test_scan_sorts_descending_by_size(self):
        # Brief test 3: --scan sorts by descending size. The config lives OUTSIDE the
        # scanned tree (a sibling "config" directory), so its own small JSON body never
        # becomes a fourth, unintended entry in the corpus being measured.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_dir = d / "config"
            config_dir.mkdir()
            config_path = _write_config(config_dir, retained_num_ctx=40)  # threshold = 10 tokens

            corpus = d / "corpus"
            corpus.mkdir()
            (corpus / "small.md").write_text("e" * 60, encoding="utf-8")     # ~15 tokens
            (corpus / "medium.md").write_text("f" * 200, encoding="utf-8")   # ~50 tokens
            (corpus / "large.md").write_text("g" * 2000, encoding="utf-8")   # ~500 tokens

            entries = cb.scan_oversized_files(corpus, window=40)

            self.assertEqual(len(entries), 3)
            sizes = [entry.size_chars for entry in entries]
            self.assertEqual(sizes, sorted(sizes, reverse=True))
            self.assertEqual(entries[0].path.name, "large.md")
            self.assertEqual(entries[-1].path.name, "small.md")

            # Also exercise the CLI surface end to end, same ordering property.
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cb.main(["--scan", str(corpus), "--config", str(config_path)])
            self.assertEqual(rc, 0)
            lines = [ln for ln in buf.getvalue().splitlines() if "\t" in ln and not ln.startswith("path")]
            self.assertEqual(len(lines), 3)
            reported_sizes = [int(ln.split("\t")[1]) for ln in lines]
            self.assertEqual(reported_sizes, sorted(reported_sizes, reverse=True))


class TestMissingConfigIsExplicitError(unittest.TestCase):
    def test_missing_config_is_explicit_error(self):
        # Brief test 4: a missing config is an explicit error, never a silent default.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            nonexistent = d / "does-not-exist" / "local-model-config.json"

            with self.assertRaises(cb.ConfigError) as ctx:
                cb.read_retained_num_ctx(nonexistent)
            self.assertIn(str(nonexistent), str(ctx.exception))


class TestMissingConfigCliErrorForTaskAndScan(unittest.TestCase):
    def test_missing_config_cli_error_for_task_and_scan(self):
        # Same explicit-error requirement, exercised through the CLI for BOTH verbs: a
        # non-zero exit and a message naming the missing path, never a bare traceback.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            nonexistent = d / "missing-config.json"
            spec_path = _write_spec(d, [{"name": "x", "text": "hello"}])

            buf_err = io.StringIO()
            with redirect_stderr(buf_err):
                rc_task = cb.main(["--task", str(spec_path), "--config", str(nonexistent)])
            self.assertEqual(rc_task, 1)
            self.assertIn(str(nonexistent), buf_err.getvalue())

            buf_err2 = io.StringIO()
            with redirect_stderr(buf_err2):
                rc_scan = cb.main(["--scan", str(d), "--config", str(nonexistent)])
            self.assertEqual(rc_scan, 1)
            self.assertIn(str(nonexistent), buf_err2.getvalue())


class TestReadRetainedNumCtxEmptyFile(unittest.TestCase):
    def test_read_retained_num_ctx_empty_file_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_path = d / "local-model-config.json"
            config_path.write_text("", encoding="utf-8")
            with self.assertRaises(cb.ConfigError):
                cb.read_retained_num_ctx(config_path)


class TestReadRetainedNumCtxInvalidJson(unittest.TestCase):
    def test_read_retained_num_ctx_invalid_json_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_path = d / "local-model-config.json"
            config_path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(cb.ConfigError):
                cb.read_retained_num_ctx(config_path)


class TestReadRetainedNumCtxAmbiguous(unittest.TestCase):
    def test_read_retained_num_ctx_ambiguous_without_tag_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_path = d / "local-model-config.json"
            config_path.write_text(json.dumps({
                "models": {
                    "vendor-a:9b": {"retained_num_ctx": 16384},
                    "vendor:7b": {"retained_num_ctx": 8192},
                }
            }), encoding="utf-8")

            with self.assertRaises(cb.ConfigError):
                cb.read_retained_num_ctx(config_path)

            # An explicit tag resolves the ambiguity cleanly.
            self.assertEqual(cb.read_retained_num_ctx(config_path, model_tag="vendor:7b"), 8192)


class TestReadRetainedNumCtxMissingField(unittest.TestCase):
    def test_read_retained_num_ctx_missing_field_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            config_path = d / "local-model-config.json"
            config_path.write_text(json.dumps({
                "models": {"vendor-a:9b": {"kv_cache_type": "q8_0"}}
            }), encoding="utf-8")
            with self.assertRaises(cb.ConfigError):
                cb.read_retained_num_ctx(config_path)


class TestEstimateTokensHeuristic(unittest.TestCase):
    def test_estimate_tokens_heuristic_and_empty_string(self):
        self.assertEqual(cb.estimate_tokens(""), 0)
        self.assertEqual(cb.estimate_tokens("a"), 1)  # non-empty rounds up to at least 1
        self.assertEqual(cb.estimate_tokens("a" * 400), 100)  # 400 / 4.0 chars-per-token


class TestLoadTaskItems(unittest.TestCase):
    def test_load_task_items_from_path_and_inline_text(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            sibling = d / "sibling.md"
            sibling.write_text("h" * 800, encoding="utf-8")  # 200 tokens
            spec_path = _write_spec(d, [
                {"name": "inline", "text": "i" * 40},          # 10 tokens
                {"name": "from-file", "path": "sibling.md"},   # relative to spec's own dir
            ])

            items = cb.load_task_items(spec_path)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].name, "inline")
        self.assertEqual(items[0].tokens, 10)
        self.assertEqual(items[0].source, "inline text")
        self.assertEqual(items[1].name, "from-file")
        self.assertEqual(items[1].tokens, 200)
        self.assertTrue(items[1].source.endswith("sibling.md"))


class TestScanExcludesNoise(unittest.TestCase):
    def test_scan_excludes_noise_directories_and_binary_extensions(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # Well over threshold if scanned, but must be pruned/skipped.
            noise_dir = d / "__pycache__"
            noise_dir.mkdir()
            (noise_dir / "big.md").write_text("j" * 5000, encoding="utf-8")

            venv_dir = d / ".venv-skills"
            venv_dir.mkdir()
            (venv_dir / "big.md").write_text("k" * 5000, encoding="utf-8")

            (d / "asset.png").write_bytes(b"\x89PNG" + b"\x00" * 5000)  # binary extension

            kept = d / "kept.md"
            kept.write_text("m" * 5000, encoding="utf-8")

            entries = cb.scan_oversized_files(d, window=40)  # threshold 10 tokens

        names = {entry.path.name for entry in entries}
        self.assertEqual(names, {"kept.md"})


class TestCheckTaskBudgetMarginAndHeaviest(unittest.TestCase):
    def test_check_task_budget_margin_and_heaviest_item_selection(self):
        items = [
            cb.TaskItemSize(name="a", tokens=100, source="inline text"),
            cb.TaskItemSize(name="b", tokens=9000, source="inline text"),
            cb.TaskItemSize(name="c", tokens=50, source="inline text"),
        ]
        result = cb.check_task_budget(items, window=16384)

        self.assertEqual(result.total_tokens, 9150)
        self.assertEqual(result.budget_tokens, 16384 - cb.TASK_RESPONSE_RESERVE_TOKENS)
        self.assertEqual(result.margin_tokens, result.budget_tokens - 9150)
        self.assertTrue(result.compliant)
        self.assertEqual(result.heaviest.name, "b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
