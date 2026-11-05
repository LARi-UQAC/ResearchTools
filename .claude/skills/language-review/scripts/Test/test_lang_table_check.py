"""
test_lang_table_check - offline suite for the language-review table checker (Issue #104, plan 1).

Proves the shipped table loads, that a malformed table is refused by name (R3, R20), that the
content codes of reviewer-response never become language entries (spec D9), that accented French
labels survive a round trip, and that each of the five research agents prints no language flag the
table lacks (the guard plan 2 relies on). Fixture agent text is fictitious (R34).
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
SKILL = SCRIPTS.parent
REPO = SKILL.parents[2]
sys.path.insert(0, str(SCRIPTS))

import lang_table_check as ltc  # noqa: E402

TABLE = SKILL / "assets" / "language_categories.json"
AGENTS = ("paper-auditor", "thesis-auditor", "thesis-proposal-auditor", "scopus-auditor",
          "reviewer-response")
CONTENT_CODES = {"SC", "M", "R", "D", "FT", "EQ", "REF", "Q", "MAJ"}

FIXTURE_AGENT = """# Fictitious agent

### Step 3 - Composition and register audit

Flag `[SEMICOLON IN PROSE: line N]` for every semicolon.
Flag `[DANGLING MODIFIER: line N]` for a modifier with no subject.

### Step 4 - Results audit

Flag `[NO BASELINE]` when nothing is compared.
"""


def _write_table(data: dict) -> Path:
    """Purpose: write a table fixture to a temp file. Inputs: data (dict). Outputs: Path."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def _shipped() -> dict:
    """Purpose: read the shipped table as raw JSON. Inputs: None. Outputs: dict."""
    return json.loads(TABLE.read_text(encoding="utf-8"))


class TableTests(unittest.TestCase):
    def test_shipped_table_loads_and_codes_are_unique(self) -> None:
        table = ltc.load_table(TABLE)
        codes = [entry["code"] for entry in table]
        self.assertGreater(len(codes), 0)
        self.assertEqual(len(codes), len(set(codes)))

    def test_every_entry_has_both_actions_and_both_labels(self) -> None:
        for entry in ltc.load_table(TABLE):
            self.assertTrue(entry["label_fr"] and entry["label_en"], entry["code"])
            self.assertIn(entry["latex_action"], ("direct_fix", "replaced"))
            self.assertTrue(entry["pdf_action"]["color"] and entry["pdf_action"]["prefix"])

    def test_a_duplicate_code_is_refused_naming_it(self) -> None:
        data = _shipped()
        data["entries"].append(dict(data["entries"][0]))
        with self.assertRaises(ltc.TableError) as ctx:
            ltc.load_table(_write_table(data))
        self.assertIn(data["entries"][0]["code"], str(ctx.exception))

    def test_a_missing_key_is_refused_naming_entry_and_key(self) -> None:
        data = _shipped()
        victim = data["entries"][2]
        del victim["pdf_action"]
        with self.assertRaises(ltc.TableError) as ctx:
            ltc.load_table(_write_table(data))
        self.assertIn(victim["code"], str(ctx.exception))
        self.assertIn("pdf_action", str(ctx.exception))

    def test_an_empty_pdf_prefix_is_refused(self) -> None:
        data = _shipped()
        data["entries"][0]["pdf_action"]["prefix"] = ""
        with self.assertRaises(ltc.TableError):
            ltc.load_table(_write_table(data))

    def test_content_codes_are_not_language_entries(self) -> None:
        codes = {entry["code"] for entry in ltc.load_table(TABLE)}
        self.assertFalse(codes & CONTENT_CODES)
        data = _shipped()
        data["entries"][0]["code"] = "SC"
        with self.assertRaises(ltc.TableError):
            ltc.load_table(_write_table(data))

    def test_accented_labels_round_trip(self) -> None:
        data = _shipped()
        data["entries"][0]["label_fr"] = "Accord à revoir, ça déçoit"
        table = ltc.load_table(_write_table(data))
        self.assertEqual(table[0]["label_fr"], "Accord à revoir, ça déçoit")
        shipped = {e["code"]: e for e in ltc.load_table(TABLE)}
        self.assertEqual(shipped["AV"]["label_fr"], "Voix active non justifiée")


class AgentFlagTests(unittest.TestCase):
    def test_flags_in_finds_a_planted_flag_and_unknown_flags_finds_a_new_one(self) -> None:
        table = ltc.load_table(TABLE)
        self.assertEqual(ltc.flags_in(FIXTURE_AGENT, table), {"SEMICOLON IN PROSE"})
        self.assertEqual(ltc.unknown_flags(FIXTURE_AGENT, table), {"DANGLING MODIFIER"})

    def test_each_of_the_five_agents_has_no_unknown_language_flag(self) -> None:
        table = ltc.load_table(TABLE)
        for name in AGENTS:
            text = (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            self.assertEqual(ltc.unknown_flags(text, table), set(), name)

    def test_the_four_auditors_print_every_composition_flag(self) -> None:
        table = ltc.load_table(TABLE)
        wanted = {e["flag"] for e in table if e["flag"]}
        for name in AGENTS[:4]:
            text = (REPO / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            self.assertEqual(ltc.flags_in(text, table), wanted, name)


class CliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = ltc.main(argv)
        return code, out.getvalue()

    def test_cli_exit_codes(self) -> None:
        clean = REPO / ".claude" / "agents" / "paper-auditor.md"
        code, out = self._run(["--table", str(TABLE), "--agent", str(clean), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["unknown"], {})
        fixture = Path(tempfile.mkdtemp()) / "fixture-agent.md"
        fixture.write_text(FIXTURE_AGENT, encoding="utf-8")
        code, out = self._run(["--table", str(TABLE), "--agent", str(fixture), "--json"])
        self.assertEqual(code, 1)
        self.assertIn("DANGLING MODIFIER", out)
        code, _ = self._run(["--table", str(TABLE) + ".missing", "--agent", str(clean)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
