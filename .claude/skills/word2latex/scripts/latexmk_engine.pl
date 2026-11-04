# latexmk_engine.pl - engine choice for a word2latex output compiled by latexmk.
#
# Purpose: a form converted with word2latex must look like the Word original, which needs
# the real Windows fonts without kerning (Arial, Calibri, Segoe UI Symbol). pdflatex cannot
# load them, XeLaTeX can. This file lets latexmk run xelatex for a .tex that declares
# "% !TEX program = xelatex" in its first lines, and pdflatex for every other .tex, so one
# project folder can hold both kinds.
#
# Use: a project folder holds a latexmkrc of ONE line (no logic of its own):
#     do "$ENV{USERPROFILE}/.claude/skills/word2latex/scripts/latexmk_engine.pl";
# latexmk reads that latexmkrc after ~/.latexmkrc, so out/, bibtex and every other
# setting stay those of ~/.latexmkrc; only the engine command changes.
#
# Subroutines:
#   word2latex_engine_for($path) -> 'xelatex' or 'pdflatex'
#       Inputs: path of the .tex (quotes allowed). Outputs: the engine name. Reads at most
#       $word2latex_magic_lines lines; an unreadable file gives 'pdflatex' (the default
#       engine of ~/.latexmkrc), never a guess.
#   word2latex_engine(@args) -> exit status of the engine
#       Inputs: the arguments latexmk passes, source file last. Runs the chosen engine.

use strict;
use warnings;

# How many leading lines may hold the magic comment. TeXworks and LaTeX Workshop read the
# magic comment only near the top of the file; 20 lines covers a header block.
our $word2latex_magic_lines = 20;

sub word2latex_engine_for {
    my ($src) = @_;
    $src =~ s/^"(.*)"$/$1/;
    open(my $fh, '<', $src) or return 'pdflatex';
    my $n = 0;
    while (my $line = <$fh>) {
        last if ++$n > $word2latex_magic_lines;
        # A UTF-8 BOM (Notepad, PowerShell Out-File) would hide the comment from ^\s*%.
        $line =~ s/^\xEF\xBB\xBF// if $n == 1;
        if ($line =~ /^\s*%\s*!TEX\s+(?:TS-)?program\s*=\s*xelatex\b/i) {
            close $fh;
            return 'xelatex';
        }
    }
    close $fh;
    return 'pdflatex';
}

sub word2latex_engine {
    my @args = @_;
    my $engine = word2latex_engine_for($args[-1]);
    print "word2latex latexmk_engine: $engine\n";
    return system($engine, @args);
}

# latexmk: replace only the engine token of the pdflatex command (pdf_mode = 1 in
# ~/.latexmkrc), so the options ~/.latexmkrc gave it (-shell-escape, -synctex, ...) stay.
# xelatex writes a PDF directly, so latexmk's pdf_mode = 1 bookkeeping is unchanged.
# Outside latexmk $pdflatex is undefined, and latexmk's own default is used.
my $word2latex_cmd = defined $main::pdflatex ? $main::pdflatex : 'pdflatex %O %S';
$word2latex_cmd =~ s/^\s*(?:internal\s+\S+|"[^"]*"|\S+)/internal word2latex_engine/;
$main::pdflatex = $word2latex_cmd;

1;
