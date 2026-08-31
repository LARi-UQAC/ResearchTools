# LaTeX hygiene check

Measure LaTeX manuscript hygiene mechanically, via the `latex-hygiene` skill: forbidden
characters, AI-usage risk score, prose and track-changed word counts, abstract length, brace
balance, `\par`-inside-`changes`-argument corruption, and citation-key coverage between a `.tex`
and its `.bib`. It also applies a machine-readable audit plan to the source (`patch`), scans it
for post-write corruption (`scan`), and resolves and builds the tracked or accepted PDF
(`accept`, `build`).

Procedure:

1. Resolve the target `.tex` file(s) from `$ARGUMENTS` (a path, a glob, a `sections/*.tex`
   directory, or the file open in the IDE). Resolve the sibling `.bib` file when `citecov` is
   needed.
2. If `$ARGUMENTS` names one check (`chars`, `aiscan`, `wc`, `abstract`, `braces`, `par`,
   `citecov`), run only that subcommand of
   `.claude/skills/latex-hygiene/scripts/tex_check.py` on the resolved files; otherwise run `all`.
   ```
   python ".claude/skills/latex-hygiene/scripts/tex_check.py" <subcommand> <files> --json
   ```
3. For `wc --accepted`, add `--before <dir>` only when the user names a pre-trim snapshot to
   compare against; otherwise report the accepted count alone.
4. Read the JSON output and report it in aligned, human-readable form: pass/fail per subcommand,
   the AI-usage risk score against the 10% target from `.claude/CLAUDE.md`, the word count against
   the venue's page estimate, and every dangling or uncited key from `citecov`.
5. This command measures; it does not fix. Hand a found defect to the matching agent
   (`latex-writer` for a hygiene fix, `paper-auditor` / `/auditpaper` for a full content audit)
   rather than editing the manuscript here.
6. If `$ARGUMENTS` names `patch` with a `--plan <audit_plan.md>` and a `--target <file.tex>`,
   apply the audit plan:
   ```
   python ".claude/skills/latex-hygiene/scripts/tex_check.py" patch --plan <audit_plan.md> --target <file.tex> [--author <id>] [--dry-run] [--init]
   ```
   Every edit is matched exact-string, one occurrence required; a 0-match or 2+-match edit is
   collected into a `FAILS:` list and the exit is non-zero, deliberately not gated by `--strict`.
   Pass `--init` once, before the first patch, to emit the `changes` preamble with colour-only
   deleted markup.
7. After a `patch` (or any manual edit), run the post-write guard before declaring the `.tex`
   clean:
   ```
   python ".claude/skills/latex-hygiene/scripts/tex_check.py" scan <files> [--bib <file>] [--fail-on-markers]
   ```
8. If `$ARGUMENTS` names `accept`, resolve the tracked source to the accepted text
   (`[final]{changes}`, `[disable]{todonotes}`), generated from the tracked source so the two
   never diverge:
   ```
   python ".claude/skills/latex-hygiene/scripts/tex_check.py" accept --target <file.tex> [--out <path>] [--resolve]
   ```
9. If `$ARGUMENTS` names `build`, run the pdflatex/bibtex build sequence on the tracked or
   accepted target, or both:
   ```
   python ".claude/skills/latex-hygiene/scripts/tex_check.py" build --target <file> [--outdir out] [--both]
   ```

Read only the files necessary for the check. Respond in French unless the active file is in
English.

$ARGUMENTS
