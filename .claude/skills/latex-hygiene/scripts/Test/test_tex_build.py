"""
test_tex_build.py - offline unit tests for tex_build.py (subcommands `accept`
and `build` of the latex-hygiene skill).

No LaTeX installation required: subprocess.run and shutil.which are patched,
so no pdflatex/bibtex process is ever spawned. Every case builds its .tex
source as a synthetic Python string in a tempfile.TemporaryDirectory().
Modeled on .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
and this skill's own Test/test_tex_check.py.

Regression fixture named for the record (not replayed here - see the module
docstring of tex_build.py and the TODO's own acceptance note): the four
counters below come from a real run against conference_101719.tex, the
Assistive-feeding-robot 653-line IEEE manuscript, 2026-08-26 -
errors=0 undefined=0 doi_links=21, 17 pages tracked, 16 pages accepted.

Run:
    cd .claude/skills/latex-hygiene/scripts
    python Test/test_tex_build.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import tex_build  # noqa: E402


def _write(tmp_dir: str, name: str, content: str) -> str:
    path = os.path.join(tmp_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


class TestBuildGuards(unittest.TestCase):
    """Cases 1 and 5: refuse before spawning a single subprocess."""

    def test_refuses_when_stray_bib_in_outdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, "out")
            os.makedirs(outdir)
            _write(outdir, "references.bib", "@article{x,}\n")
            target = _write(tmp, "paper.tex", "\\documentclass{article}\n")

            with patch("tex_build.shutil.which", return_value="/usr/bin/tool"):
                with self.assertRaises(RuntimeError) as ctx:
                    tex_build.run_build(target, outdir)
            self.assertIn("references.bib", str(ctx.exception))

    def test_fails_with_named_message_when_pdflatex_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, "out")
            target = _write(tmp, "paper.tex", "\\documentclass{article}\n")

            with patch("tex_build.shutil.which", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    tex_build.run_build(target, outdir)
            self.assertIn("pdflatex", str(ctx.exception))


class TestBuildSequence(unittest.TestCase):
    """Cases 2, 3, 4: the four-command run and its BIBINPUTS/counters."""

    def _run_mocked(self, tmp, log_text="", bbl_text=""):
        outdir = os.path.join(tmp, "out")
        target = _write(tmp, "paper.tex", "\\documentclass{article}\n")
        if log_text:
            os.makedirs(outdir, exist_ok=True)
            _write(outdir, "paper.log", log_text)
        if bbl_text:
            os.makedirs(outdir, exist_ok=True)
            _write(outdir, "paper.bbl", bbl_text)

        with patch("tex_build.shutil.which", return_value="/usr/bin/tool"):
            with patch("tex_build.subprocess.run") as mock_run:
                mock_run.return_value = None
                result = tex_build.run_build(target, outdir)
        return result, mock_run, outdir, target

    def test_command_order_is_pdflatex_bibtex_pdflatex_pdflatex(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, mock_run, _, _ = self._run_mocked(tmp)
        names = [call.args[0][0] for call in mock_run.call_args_list]
        self.assertEqual(names, ["pdflatex", "bibtex", "pdflatex", "pdflatex"])

    def test_bibtex_call_carries_bibinputs_dotdot(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, mock_run, outdir, _ = self._run_mocked(tmp)
        bibtex_call = next(c for c in mock_run.call_args_list if c.args[0][0] == "bibtex")
        self.assertEqual(bibtex_call.kwargs["env"]["BIBINPUTS"], "..")
        self.assertEqual(bibtex_call.kwargs["cwd"], outdir)

    def test_reports_all_four_counters(self):
        log_text = (
            "! Undefined control sequence.\n"
            "! Emergency stop.\n"
            "LaTeX Warning: Citation `x' undefined on page 3.\n"
            "LaTeX Warning: Reference `y' undefined on page 4.\n"
            "Output written on out/paper.pdf (21 pages, 900000 bytes).\n"
        )
        bbl_text = "\\bibitem{a} \\url{https://doi.org/10.1/a}\n" \
                   "\\bibitem{b} \\url{https://doi.org/10.1/b}\n"
        with tempfile.TemporaryDirectory() as tmp:
            result, _, _, _ = self._run_mocked(tmp, log_text=log_text, bbl_text=bbl_text)
        self.assertEqual(result["errors"], 2)
        # "undefined" (case-insensitive) hits 3 times: the control-sequence
        # error line plus the two Citation/Reference warning lines.
        self.assertEqual(result["undefined"], 3)
        self.assertEqual(result["doi_links"], 2)
        self.assertEqual(result["pages"], 21)


class TestAccept(unittest.TestCase):
    """Cases 6 and 7: the accept subcommand, package-switch and --resolve."""

    def test_default_switches_package_options_and_nothing_else(self):
        source = (
            "\\documentclass{article}\n"
            "\\usepackage{changes}\n"
            "\\usepackage[textsize=footnotesize]{todonotes}\n"
            "\\begin{document}\n"
            "Body text unrelated to markup.\n"
            "\\end{document}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "paper.tex", source)
            info = tex_build.write_accepted(target)
            with open(info["out"], encoding="utf-8") as handle:
                out_text = handle.read()

        self.assertIn("\\usepackage[final]{changes}", out_text)
        self.assertIn("\\usepackage[disable]{todonotes}", out_text)
        before_lines = source.splitlines()
        after_lines = out_text.splitlines()
        changed = sum(1 for a, b in zip(before_lines, after_lines) if a != b)
        self.assertEqual(changed, 2)
        self.assertIn("Body text unrelated to markup.", out_text)

    def test_resolve_flag_resolves_replaced_and_drops_deleted(self):
        source = (
            "Keep \\replaced[id=MO]{new text}{old text} here. "
            "\\deleted[id=MO]{gone text} Also keep this."
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = _write(tmp, "paper.tex", source)
            info = tex_build.write_accepted(target, resolve=True)
            with open(info["out"], encoding="utf-8") as handle:
                out_text = handle.read()

        self.assertIn("new text", out_text)
        self.assertNotIn("old text", out_text)
        self.assertNotIn("gone text", out_text)
        self.assertIn("Also keep this", out_text)


if __name__ == "__main__":
    unittest.main()
