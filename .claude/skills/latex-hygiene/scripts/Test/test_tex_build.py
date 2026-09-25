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


class TestArtifactDecoding(unittest.TestCase):
    """
    The 2026-09-16 defect: parse_counters read the .log with a strict UTF-8
    decode. MiKTeX under a French Windows writes paths and messages in the
    system codepage, so byte 0xe9 raised UnicodeDecodeError and `build`
    reported NOTHING although pdflatex and bibtex had both succeeded and the
    61-page PDF was on disk. A build whose result cannot be read looks exactly
    like a build that failed, which is why this is a defect and not a cosmetic
    issue.
    """

    @staticmethod
    def _write_bytes(tmp_dir: str, name: str, payload: bytes) -> None:
        with open(os.path.join(tmp_dir, name), "wb") as handle:
            handle.write(payload)

    def test_a_log_in_the_system_codepage_does_not_raise(self):
        # 0xe9 is a cp1252 "e acute" and is not a valid standalone UTF-8 byte.
        log = (
            b"This is pdfTeX\n"
            b"(C:\\Users\\prof\\Documents\\r\xe9f\xe9rences\\paper.tex)\n"
            b"Output written on paper.pdf (61 pages, 9787008 bytes).\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            self._write_bytes(tmp, "paper.log", log)
            counters = tex_build.parse_counters("paper", tmp)

        self.assertEqual(counters["pages"], 61)

    def test_counters_survive_a_replaced_byte_next_to_them(self):
        # Positive control: the four counters are pure ASCII, so a replaced
        # byte on the same line must neither create nor destroy one.
        log = (
            b"! Undefined control sequence.\n"
            b"LaTeX Warning: Citation `r\xe9f2026' on page 3 undefined.\n"
            b"! Missing $ inserted.\n"
            b"Output written on paper.pdf (12 pages, 100 bytes).\n"
        )
        bbl = b"\\bibitem{a} Auteur, \xe9t\xe9. https://doi.org/10.1000/x\n"
        with tempfile.TemporaryDirectory() as tmp:
            self._write_bytes(tmp, "paper.log", log)
            self._write_bytes(tmp, "paper.bbl", bbl)
            counters = tex_build.parse_counters("paper", tmp)

        self.assertEqual(counters["errors"], 2)
        self.assertEqual(counters["undefined"], 2)
        self.assertEqual(counters["doi_links"], 1)
        self.assertEqual(counters["pages"], 12)

    def test_a_clean_utf8_log_is_unchanged(self):
        # Negative control: the tolerant reader must not alter the ordinary
        # case, or every existing measurement would have moved with this fix.
        log = "! Error.\nCitation undefined.\nOutput written on p.pdf (7 pages, 1 bytes).\n"
        with tempfile.TemporaryDirectory() as tmp:
            self._write_bytes(tmp, "paper.log", log.encode("utf-8"))
            counters = tex_build.parse_counters("paper", tmp)

        self.assertEqual(counters["errors"], 1)
        self.assertEqual(counters["undefined"], 1)
        self.assertEqual(counters["pages"], 7)

    def test_source_files_keep_the_strict_decode(self):
        # The load-bearing negative control: the fix must NOT widen the source
        # reader. A .tex that is not UTF-8 is an authoring defect to surface,
        # and silently replacing bytes there would hide it.
        import tex_common

        with tempfile.TemporaryDirectory() as tmp:
            self._write_bytes(tmp, "paper.tex", b"Texte accentu\xe9.\n")
            path = os.path.join(tmp, "paper.tex")
            with self.assertRaises(UnicodeDecodeError):
                tex_common.read_text(path)
            self.assertIn("Texte accentu", tex_common.read_artifact_text(path))


if __name__ == "__main__":
    unittest.main()
