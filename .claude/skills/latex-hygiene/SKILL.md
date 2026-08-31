---
name: latex-hygiene
description: "Measure LaTeX manuscript hygiene mechanically: forbidden characters, an AI-usage risk score, prose and track-changed word counts, abstract length, brace balance, par-inside-changes-argument corruption, and citation-key coverage between a .tex and its .bib. Backs the /texcheck command and the aiscan / wc checks that paper-auditor and submit-checker already describe in prose. Trigger on: /texcheck, LaTeX hygiene, AI-usage score, word count, brace balance, citation coverage, forbidden characters, track-changed word count."
allowed-tools: [Read, Bash]
---

# LaTeX hygiene

A reusable measurement capability for LaTeX manuscripts. ResearchTools describes these checks in
prose today: `paper-auditor.md` Step 7.5 states the AI-usage signal table and score formula
signal by signal, `submit-checker.md` Step 2 states the prose word count and page-estimate
heuristics, and the "Style hygiene" section of `.claude/CLAUDE.md` states the forbidden-character
list. None of it was measured; it was computed by hand each audit, which is not reproducible and
drifts between sessions. This skill turns each of those descriptions into a script call that
returns the same number every time.

## When to use

- Mid-audit, invoked by `paper-auditor` (Step 7.5, AI-usage score), `submit-checker` (Step 2 word
  and page count, Step 7 abstract length), and `thesis-auditor` (LLM-style table).
- Mid-authoring, invoked by `latex-writer` before delivering a `.tex` edit (`chars --strict`) and
  by `reviewer-response` before emitting `changes` track-change markup (`par`, `braces`).
- Directly, through `/texcheck`, when a user wants a hygiene reading on a manuscript without
  running a full audit.

## When NOT to use

- LaTeX build errors (missing packages, `\resizebox`/`tikzpicture` conflicts, compile failures):
  that is `/latex`.
- TikZ geometry validation (anchoring, arrow angles, overlaps): that is `/tikz`.
- Reference validity: `citecov` only checks whether a `\cite` key has a matching `.bib` entry and
  whether a `.bib` entry is ever cited, not whether the reference itself is real or well-formed.
  Existence and quality validation is the `scopus` skill and `bib-cleaner`.

## Subcommands

One script, `tex_check.py`, with subcommands rather than eight throwaway files. Every subcommand
takes paths or globs as arguments, never an absolute constant or a working-directory assumption,
and accepts `--json` for machine consumption.

| Subcommand | Input | Output |
|---|---|---|
| `chars` | `.tex` files/globs | per file: line number and forbidden-character name; total count |
| `aiscan` | `.tex` files/globs | `risk_score`, weighted count per signal, lowest-deviation sentence window, a 15-word excerpt per hit |
| `wc` | `.tex` files/globs | prose word count per file (floats and comments excluded), float count, total, page estimate |
| `wc --accepted` | `.tex` files/globs, optional `--before <dir>` | word count of the accepted text (`changes` macros resolved); with `--before`, a before/after/delta/percent table |
| `abstract` | main `.tex` | abstract word count, keyword count |
| `braces` | `.tex` files/globs | two balance classes, each with line numbers: curly-brace depth (final depth per file, first negative line) and `\begin`/`\end` environment balance (an `\end` with no open `\begin`, an `\end{a}` closing a `\begin{b}`, any environment left open at end of file) |
| `par` | `.tex` files/globs | occurrences of `\added`/`\deleted`/`\replaced` whose argument crosses a blank line (the package macros are not `\long`, so this breaks a build) |
| `citecov` | `--tex <globs> --bib <file>` | cited keys absent from the `.bib` (dangling), and `.bib` entries never cited |
| `refcov` | `.tex` files/globs | labels never referenced (uncited label), `\ref`/`\eqref`/`\cref`/`\autoref` keys with no matching `\label` (dangling reference), and duplicate `\label{}` keys with both line numbers |
| `patch` | `--plan <audit_plan.md> --target <file.tex>`, optional `--author <id>`, `--dry-run`, `--init` | applies an audit plan to the target by exact-match substitution, one occurrence required per edit; collects failures into a `FAILS:` list and exits non-zero on any 0-match or 2+-match edit (deliberately not gated by `--strict`); `--init` emits the `changes` preamble with colour-only deleted markup, never `ulem`'s `\sout` |
| `scan` | `.tex` files/globs, optional `--bib <file>`, `--fail-on-markers` | post-write guard: control characters including TAB, damaged control-sequence residue (`extbf`, `ewline`, `pprox`, ...), a `changes` macro crossing a `tabular`/`tabularx`/`table`/`figure` boundary, a `%` comment that swallowed a row-terminating `\\`, a `\cite` to a missing key inside a deleted span, and live `\hl{}`/`\todo{}`/`TODO(author)` markers |
| `accept` | `--target <file.tex>`, optional `--out <path>`, `--resolve` | writes the accepted source with `[final]{changes}` and `[disable]{todonotes}`, generated from the tracked source so the two never diverge |
| `build` | `--target <file>`, optional `--outdir out`, `--both` | pdflatex, bibtex, pdflatex, pdflatex, with mandatory `BIBINPUTS=".."` on bibtex, refusing to run if a `.bib` sits inside the output directory; reports `errors= undefined= doi_links= pages` |
| `all` | files/globs | the aggregate of the nine read-side subcommands above |

`aiscan` reproduces the High/Medium signal weights and the
`risk_score = min(100, round(raw_count / total_prose_sentences * 100))` formula stated in
`paper-auditor.md` Step 7.5, plus three checks folded in from a second implementation written for
single-file manuscripts: section attribution for `\section`/`\subsection` (falling back to
per-file reporting when more than one file is passed), a first-person pronoun scan, and detection
of `itemize`/`enumerate`/`description` lists, which `.claude/CLAUDE.md` forbids in produced prose.
`chars` checks the ten forbidden characters from that same style-hygiene section plus three
observed in production LaTeX that must be typeset as math (`x` MULT SIGN, `deg` DEGREE, `-` MINUS
SIGN). `wc` carries the page-estimate heuristics of `submit-checker.md` Step 2, including
font-size detection from the `\documentclass` options, so the agent stops recomputing it by hand.
`refcov` exists because `.claude/CLAUDE.md` requires every figure, table, and equation to carry a
label and be cited in the text, and nothing in the repo measured that until now; `citecov` checks
only `\cite` coverage against the `.bib`, not `\ref`/`\eqref`/`\cref`/`\autoref` coverage against
`\label`.

The read side and the write side answer different questions. The nine subcommands above (`chars`
through `all`) answer "is this `.tex` clean": they measure and report, and every one exits 0 even
on a defect so an audit can keep going. `patch`, `scan`, `accept`, and `build` answer "apply this
audit plan without breaking the `.tex`": `patch` writes the edits, `scan` is the post-write guard
that must run after any edit whether by `patch` or by hand, and `accept`/`build` turn the tracked
source into the artifact that actually compiles.

## Guards

Each `scan` check exists because it cost a debugging cycle in the 2026-08-26 session that first
applied track-change markup to a real manuscript at scale.

- A literal TAB can silently turn `\textbf` into TAB + `extbf`; `scan` flags every control
  character, TAB included, because none is legal in body text.
- `changes` deleted markup must be colour-only, never `ulem`'s `\sout`, because `\sout` breaks
  inside `\cite`, math mode, and `\newline`.
- No `changes` macro inside a `tabularx` cell or a float: `tabularx` re-scans the cell body, and
  the macro fails only on that second pass, under `[final]`, far from the edit that caused it.
- An inline `%` comment on the same line as a row-terminating `\\` swallows it; the build reports
  `Misplaced \noalign` two hundred lines later, nowhere near the missing `\\`.
- A `\cite` retracted inside a `\deleted{}` span is still resolved by BibTeX at build time, so a
  citation that looks gone in the diff still needs a valid key.
- `bibtex` needs `BIBINPUTS=".."` in its own environment, or it reports a missing `.bib` as a mere
  warning and every citation renders as a question mark.
- A stale `.bib` left inside the output directory shadows the real one with no warning at all;
  `build` refuses to run against an output directory that contains one.

## Prerequisites

None. The script is pure Python standard library (`re`, `glob`, `statistics`, `argparse`, `json`,
`bisect`). There is no `requirements.txt` and therefore no `pip-audit` surface for this skill.

## Outputs

Human-readable by default (aligned text for a person reading the terminal); pass `--json` on any
subcommand for a machine-readable payload an agent can fold into its plan. Every subcommand exits
0 even when it finds a defect, so it stays usable mid-audit without breaking the calling agent's
chain; pass `--strict` to turn a defect into a non-zero exit for a gate (for example `latex-writer`
calling `chars --strict` before declaring an edit finished).

## Invocation

```powershell
python ".claude/skills/latex-hygiene/scripts/tex_check.py" aiscan "<manuscript>/sections/*.tex" --json
python ".claude/skills/latex-hygiene/scripts/tex_check.py" wc "<manuscript>/sections/*.tex" --json
python ".claude/skills/latex-hygiene/scripts/tex_check.py" wc --accepted "<manuscript>/sections/*.tex" --before "<pre-trim dir>"
python ".claude/skills/latex-hygiene/scripts/tex_check.py" citecov --tex "<manuscript>/sections/*.tex" --bib "<manuscript>/references.bib"
python ".claude/skills/latex-hygiene/scripts/tex_check.py" all "<manuscript>/sections/*.tex" --json
```

## Resources

- `scripts/tex_check.py`: the nine read-side subcommands above.
- `scripts/Test/test_tex_check.py`: offline synthetic-string tests, no real file, no network.
- `scripts/tex_patch.py`, `scripts/tex_scan.py`, `scripts/tex_build.py`: the four write-side
  subcommands (`patch`, `scan`, `accept`, `build`), dispatched from the same `tex_check.py` CLI.
- `scripts/Test/test_tex_patch.py`, `scripts/Test/test_tex_build.py`: offline tests for the write
  side, no real LaTeX build, no network.

## Deferred candidates

On 2026-08-27 this skill's design was compared against three public LaTeX skills:
`hameefy/claude-latex-skill` (MIT), `ndpvt-web/latex-document-skill` (MIT), and the lobehub
listing `flonat-claude-research-latex` (license not stated). Nothing was copied from any of the
three; only ideas were carried over, and most were re-scoped or declined. This section records
what was examined and why it was left out, so a later session does not re-litigate the same
ground.

Deferred, with the reason each was deferred rather than rejected:

- **TikZ scope checks** (`\node`, `\draw`, `\path` used outside a `tikzpicture`; a `\node` with
  no body). Belongs to the `tikz-figure` skill that
  `docs/superpowers/todo/2026-08-04-latex-hygiene-skill.md` explicitly descoped, not to
  `tex_check.py`.
- **Beamer-specific hygiene** (footnotemark/footnotetext pairing, packages incompatible under
  `beamer`, itemize-depth and frame-length heuristics). Real, but narrow to hand-authored Beamer
  outside the `paper2talk` pipeline. Not worth a subcommand until a session measures a defect
  from it.
- **A broader style-phrase list for `aiscan`** (contractions, exclamation marks, rhetorical
  questions, vague intensifiers, noun stacking). Any change to the signal set moves the
  `paper-auditor.md` Step 7.5 table with it, in the same commit; that is a deliberate arbitration,
  not an incremental addition.
- **`latexdiff` two-version diff.** A different mechanism from the reviewer-attributed `changes`
  macros this repo uses, and it needs an external Perl toolchain, so it breaks the stdlib-only
  contract.

Rejected outright, one line each, so they are not re-proposed:

- Stray `&` outside an alignment environment: too many false positives on `\&` and on URLs inside
  `\href`.
- A curated list of known-conflicting package pairs: a hand-maintained list is data that rots, and
  `/latex` already diagnoses the build failure it would predict.
- Anything requiring `chktex`, `detex`, `kpsewhich`, `pandas`, `matplotlib` or `jinja2`: the skill
  is stdlib-only by contract.
- BibTeX fetching or DOI verification: already covered, and more strictly, by the mandatory
  `scopus` validation policy and `bib-cleaner`.

## Key rules

- No `os.chdir` and no hardcoded manuscript path: every subcommand takes its files as arguments.
- `--json` is available on every subcommand; an agent consumes JSON, not aligned columns.
- Never fabricate a count. A subcommand that cannot parse a file reports the parse failure rather
  than silently returning zero.
