"""
test_tex_patch.py - offline unit tests for tex_patch.py (subcommand `patch`)
and tex_scan.py (subcommand `scan`) of the latex-hygiene skill.

No LaTeX install, no network: synthetic plan/target strings and tempfile
only. Regression fixture named per the spec each guard traces back to:
conference_101719.tex, article/Penelope_Allan, Assistive-feeding-robot
project, 653 lines, 106 track-changed edits, 2026-08-26 (see
docs/superpowers/todo/2026-08-26-latex-trackchanges-patcher.md).

Run:
    cd .claude/skills/latex-hygiene/scripts
    python Test/test_tex_patch.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import tex_patch  # noqa: E402
import tex_scan  # noqa: E402


def _write(dirpath: Path, name: str, content: str) -> str:
    path = dirpath / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _patch_args(**overrides) -> SimpleNamespace:
    defaults = dict(
        plan=None, target=None, author=None, dry_run=False, init=False,
        author_name="Author", author_color="blue", added_color="blue", deleted_color="red",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestPatchMatchCount(unittest.TestCase):
    """patch1.py::rep()'s count-then-substitute contract: exactly 1 match required."""

    def test_pattern_occurring_twice_fails_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            original = "duplicate line\nduplicate line\n"
            target = _write(d, "t.tex", original)
            plan = _write(d, "plan.md", (
                "## Section A\n\n"
                "```latex\n"
                r"\deleted[id=AU]{duplicate line}" + "\n"
                "```\n"
            ))
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target))
            self.assertFalse(result["written"])
            self.assertEqual(len(result["fails"]), 1)
            self.assertEqual(result["fails"][0]["count"], 2)
            self.assertEqual(Path(target).read_text(encoding="utf-8"), original)

    def test_pattern_occurring_zero_times_fails_and_names_section(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", "some other text\n")
            plan = _write(d, "plan.md", (
                "## Missing Anchor\n\n"
                "```latex\n"
                r"\deleted[id=AU]{text that is not present}" + "\n"
                "```\n"
            ))
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target))
            self.assertFalse(result["written"])
            self.assertEqual(result["fails"][0]["count"], 0)
            self.assertEqual(result["fails"][0]["heading"], "Missing Anchor")


class TestPatchAuthorRewrite(unittest.TestCase):

    def test_author_flag_rewrites_all_three_macro_forms(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", "alpha beta gamma\n")
            plan_text = (
                "## Replaced\n\n"
                "```latex\n"
                r"\replaced[id=AU]{ALPHA}{alpha}" + "\n"
                "```\n\n"
                "## Deleted\n\n"
                "```latex\n"
                r"\deleted[id=AU]{ beta}" + "\n"
                "```\n\n"
                "## Added\n\n"
                "```latex\n"
                "% after: gamma\n"
                r"\added[id=AU]{ delta}" + "\n"
                "```\n"
            )
            plan = _write(d, "plan.md", plan_text)
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target, author="MO"))
            self.assertEqual(result["fails"], [])
            out = Path(target).read_text(encoding="utf-8")
            self.assertNotIn("id=AU", out)
            self.assertEqual(out.count("id=MO"), 3)


class TestPatchMalformedBlock(unittest.TestCase):

    def test_two_macros_in_one_block_is_malformed_others_still_apply(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", "one two three\n")
            plan_text = (
                "## Bad\n\n"
                "```latex\n"
                r"\deleted[id=AU]{one}\deleted[id=AU]{two}" + "\n"
                "```\n\n"
                "## Good\n\n"
                "```latex\n"
                r"\deleted[id=AU]{three}" + "\n"
                "```\n"
            )
            plan = _write(d, "plan.md", plan_text)
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target, dry_run=True))
            self.assertEqual(len(result["fails"]), 1)
            self.assertEqual(result["fails"][0]["heading"], "Bad")
            self.assertEqual(result["edits_applied"], 1)

    def test_added_without_anchor_comment_is_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", "one two three\n")
            plan = _write(d, "plan.md", (
                "## No Anchor\n\n"
                "```latex\n"
                r"\added[id=AU]{ four}" + "\n"
                "```\n"
            ))
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target, dry_run=True))
            self.assertEqual(len(result["fails"]), 1)
            self.assertIn("added", result["fails"][0]["pattern"])


class TestPatchInit(unittest.TestCase):

    def test_init_emits_colour_only_deleted_markup_no_sout(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", "\\documentclass{article}\n\\begin{document}\nbody\n\\end{document}\n")
            plan = _write(d, "plan.md", "")
            result = tex_patch.run_patch(_patch_args(plan=plan, target=target, init=True))
            self.assertTrue(result["written"])
            out = Path(target).read_text(encoding="utf-8")
            self.assertIn(r"\setdeletedmarkup{\color{red}[#1]}", out)
            self.assertNotIn(r"\sout", out)
            self.assertIn(r"\usepackage{changes}", out)


class TestScanControlChars(unittest.TestCase):

    def test_tab_inside_textbf_caught(self):
        """Guard 2: the exact regression that escaped the first scan class
        [\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f], which excludes \\x09 (TAB). A
        non-raw replacement string turns \\t into a real tab here, producing
        <TAB>extbf{bold} instead of \\textbf{bold}."""
        with tempfile.TemporaryDirectory() as d:
            corrupted = "line one\n\textbf{bold}\nline three\n"
            target = _write(Path(d), "t.tex", corrupted)
            result = tex_scan.scan_files([target], None, False)
            self.assertGreater(result["totals"]["control_chars"], 0)
            self.assertGreater(result["totals"]["damaged_residue"], 0)


class TestScanFloatBoundary(unittest.TestCase):

    def test_replaced_inside_tabularx_cell(self):
        tex = (
            "\\begin{tabularx}{\\linewidth}{lX}\n"
            "a & " + r"\replaced[id=MO]{new}{old}" + " " + r"\\" + "\n"
            "\\end{tabularx}\n"
        )
        with tempfile.TemporaryDirectory() as d:
            target = _write(Path(d), "t.tex", tex)
            result = tex_scan.scan_files([target], None, False)
            self.assertGreater(result["totals"]["float_boundary"], 0)


class TestScanTableComment(unittest.TestCase):

    def test_comment_swallows_row_terminator(self):
        tex = "a & b % [MO] was: c " + "\\" + "\\" + "\n"
        with tempfile.TemporaryDirectory() as d:
            target = _write(Path(d), "t.tex", tex)
            result = tex_scan.scan_files([target], None, False)
            self.assertGreater(result["totals"]["table_comment"], 0)


class TestScanDanglingCite(unittest.TestCase):

    def test_cite_to_renamed_key_inside_deleted(self):
        tex = r"\deleted[id=MO]{see \cite{oldkey}}" + "\n"
        bib = "@article{newkey,\n  title={x},\n}\n"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = _write(d, "t.tex", tex)
            bib_path = _write(d, "refs.bib", bib)
            result = tex_scan.scan_files([target], bib_path, False)
            self.assertGreater(result["totals"]["dangling_cite"], 0)
            hit = result["files"][target]["dangling_cite"][0]
            self.assertEqual(hit["key"], "oldkey")


if __name__ == "__main__":
    unittest.main()
