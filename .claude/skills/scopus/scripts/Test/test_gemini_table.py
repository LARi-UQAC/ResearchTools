"""
test_gemini_table.py — offline unit tests for the comparison-table enrichment helper.

run_gemini and count_gemini_tokens are patched on the gemini_table module, so no API key,
no google-genai install, and no network are needed.

Run:
    cd .claude/skills/scopus/scripts
    python -m pytest Test/test_gemini_table.py -v
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import gemini_table  # noqa: E402

AXES = {"concepts": ["C1", "C2"], "parameters": ["P1", "P2", "P3"],
        "context": "ctx-line", "refs": [{"key": "smith2023", "title": "Title T"}]}
RESULT = {"rows": [{"parameter": "P1", "cells": {"C1": "a", "C2": "b"}}], "notes": "ok"}


class TestEnrich(unittest.TestCase):

    def test_calls_gemini_with_compact_prompt_and_scaled_output(self):
        rg = mock.Mock(return_value=RESULT)
        with mock.patch.object(gemini_table, "run_gemini", rg), \
             mock.patch.object(gemini_table, "count_gemini_tokens", lambda t, m: 1):
            out = gemini_table.enrich(AXES, "g", 0.3, 4000)

        self.assertEqual(out, RESULT)
        prompt, model, temperature, max_out = rg.call_args.args
        self.assertEqual(model, "g")
        self.assertEqual(max_out, max(1024, len(AXES["parameters"]) * len(AXES["concepts"]) * 24))
        self.assertIn("C1", prompt)
        self.assertIn("P1", prompt)
        self.assertIn("caveman-terse", prompt)

    def test_trims_refs_then_context_when_over_budget(self):
        rg = mock.Mock(return_value=RESULT)
        with mock.patch.object(gemini_table, "run_gemini", rg), \
             mock.patch.object(gemini_table, "count_gemini_tokens", lambda t, m: 999999):
            gemini_table.enrich(AXES, "g", 0.3, 100)

        prompt = rg.call_args.args[0]
        self.assertNotIn("Title T", prompt)   # ref title dropped first
        self.assertNotIn("ctx-line", prompt)  # then free-text context dropped


class TestMainSkip(unittest.TestCase):

    def test_skips_gracefully_when_gemini_unavailable(self):
        with mock.patch.object(gemini_table, "gemini_available", lambda: False), \
             mock.patch.object(sys, "argv", ["gemini_table.py", "--stdin"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                gemini_table.main()
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["skipped"])
        self.assertIn("unavailable", payload["reason"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
