"""
Offline tests for latexmk_engine.pl (word2latex): which engine latexmk runs for a .tex.

Each case loads the Perl file with `perl -e` and asks word2latex_engine_for() about a
fictitious .tex in a temporary folder; no TeX engine is ever started. Skipped, not failed,
when perl is not on PATH (latexmk itself needs perl, so a machine without it cannot use
the file either).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ENGINE_FILE = Path(__file__).resolve().parents[1] / "latexmk_engine.pl"
PERL = shutil.which("perl")
PERL_TIMEOUT_S = 30  # one perl start; measured well under 1 s on 2026-10-30


def engine_for(tex_path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the Perl file which engine it would run for a source file.

    Inputs:
        tex_path (str): path given to word2latex_engine_for, quoted or not.

    Outputs:
        engine (str): 'xelatex' or 'pdflatex' as printed by perl.

    Raises:
        subprocess.CalledProcessError: perl failed to load the file.
    --------------------------------------------------------------------------
    """
    script = 'do $ARGV[0] or die "load: $@ $!"; print word2latex_engine_for($ARGV[1]);'
    res = subprocess.run([PERL, "-e", script, str(ENGINE_FILE), tex_path],
                         capture_output=True, text=True, timeout=PERL_TIMEOUT_S, check=True)
    return res.stdout.strip()


@unittest.skipUnless(PERL, "perl is not on PATH")
class EngineChoice(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _tex(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_magic_comment_selects_xelatex(self):
        p = self._tex("form v2.tex", "% !TEX program = xelatex\n\\documentclass{article}\n")
        self.assertEqual(engine_for(str(p)), "xelatex")

    def test_quoted_path_with_spaces_is_read(self):
        p = self._tex("a b c.tex", "%!TEX TS-program = XeLaTeX\n")
        self.assertEqual(engine_for('"%s"' % p), "xelatex")

    def test_no_magic_comment_keeps_pdflatex(self):
        p = self._tex("v1.tex", "\\documentclass{article}\n% xelatex mentioned in prose\n")
        self.assertEqual(engine_for(str(p)), "pdflatex")

    def test_magic_comment_past_the_header_is_ignored(self):
        p = self._tex("late.tex", "%\n" * 25 + "% !TEX program = xelatex\n")
        self.assertEqual(engine_for(str(p)), "pdflatex")

    def test_other_program_is_not_xelatex(self):
        p = self._tex("lua.tex", "% !TEX program = lualatex\n")
        self.assertEqual(engine_for(str(p)), "pdflatex")

    def test_utf8_bom_before_the_magic_comment_is_ignored(self):
        # Review round 1 (2026-11-04): a .tex saved by Notepad or PowerShell starts with a
        # BOM, and the ^\s*% anchor missed the comment, building with pdflatex silently.
        p = self.dir / "bom.tex"
        p.write_bytes(b"\xef\xbb\xbf% !TEX program = xelatex\n\\documentclass{article}\n")
        self.assertEqual(engine_for(str(p)), "xelatex")

    def test_unreadable_file_falls_back_to_pdflatex(self):
        self.assertEqual(engine_for(str(self.dir / "absent.tex")), "pdflatex")

    def test_file_sets_the_latexmk_pdflatex_command(self):
        script = 'do $ARGV[0] or die "load: $@ $!"; print $main::pdflatex;'
        res = subprocess.run([PERL, "-e", script, str(ENGINE_FILE)], capture_output=True,
                             text=True, timeout=PERL_TIMEOUT_S, check=True)
        self.assertIn("internal word2latex_engine", res.stdout)
        self.assertIn("%O %S", res.stdout)

    def test_options_of_the_users_pdflatex_command_are_kept(self):
        # Review round 2 (2026-11-04): the file replaced $pdflatex whole, so a
        # -shell-escape set in ~/.latexmkrc was lost for every build of the folder.
        script = ('$main::pdflatex = q{pdflatex -shell-escape -synctex=1 %O %S};'
                  ' do $ARGV[0] or die "load: $@ $!"; print $main::pdflatex;')
        res = subprocess.run([PERL, "-e", script, str(ENGINE_FILE)], capture_output=True,
                             text=True, timeout=PERL_TIMEOUT_S, check=True)
        self.assertEqual(res.stdout, "internal word2latex_engine -shell-escape -synctex=1 %O %S")


if __name__ == "__main__":
    unittest.main()
