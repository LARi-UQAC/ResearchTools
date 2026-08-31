# Workflows

Common task flows in this workspace. Each maps a goal to the command, the agent it drives,
and the output produced. Full arguments are in `README.md`.

## Research and writing flows

| Goal | Command | Agent / skill | Output |
|---|---|---|---|
| Literature review on a topic | `/litreview <topic>` | `scopus-researcher` | Structured review, PRISMA + gap/coverage/Pareto matrices, hypotheses, BibTeX |
| Incrementally update an existing review with new papers | `/litupdate <review.tex>` | `litreview-updater` | Dated `\added{}` copy `_up_YYYYMMDD.tex` + CHANGELOG; preemption verdict (gaps/hypotheses still novel?); schedulable (draft + REVIEW REQUIRED unattended) |
| Find or validate one reference | `/scopus`, `/ref` | `scopus` skill | Validated metadata, formatted reference, clickable DOI |
| Audit an existing review | `/auditreview [file]` | `scopus-auditor` | Reference validation + executable improvement plan |
| Audit a complete paper | `/auditpaper [file]` | `paper-auditor` (+ `scholar-evaluation`) | Track-change markup plan + ScholarEval score |
| Audit a UQAC thesis | `/auditthesis [main.tex]` | `thesis-auditor` | Front-matter, hypothesis-flow, and formatting audit plan |
| Audit a UQAC thesis proposal | by name | `thesis-proposal-auditor` | Proposal-specific audit plan (<=35 pages body) |
| Clean a `.bib` | `/bibclean [file.bib]` | `bib-cleaner` | Cleaned `.bib` + report (dedup, DOI enrichment, SJR) |
| Respond to reviewers | `/replyreviewer ...` | `reviewer-response` | One letter per reviewer + traceable `changes` markup |
| Check submission readiness | `/submitcheck <tex> <journal>` | `submit-checker` | Pass/fail submission checklist |
| Build a submission package | by name | `cover-paper` | Hidden cover letter, title page PDF, author profile PDF, graphical abstract (Canva MCP + FigureLabs prompt) |
| Integrate a thesis + conference papers into one journal manuscript | by name / "extend this paper to a journal version" | `thesis-to-paper` | Submission-ready journal `.tex` (+ sections, refs, PDF), content-delta matrix, disclosure letter; multi-session checkpoint protocol |
| Iterate a manuscript/review to a target ScholarEval score under a budget | by name / "improve this to a ScholarEval target" | `authoring-loop` (author on Fable 5, audit with `scholar-evaluation` on Sonnet/Haiku) | Improved `.tex` + per-iteration ScholarEval scores, `authoring-loop-log.md`, learnings written to memory by `local-writer` |
| Build the conference talk from an accepted paper | `/talk <paper>` | `paper2talk` skill / `talk-builder` | Deck (PowerPoint, Beamer, or self-contained web) on the lab gabarit + timed speaker notes, projector-grade figures, slide-size and paper PDFs |
| Convert Word to LaTeX | `/word2latex <docx>` | `word2latex` skill / `word-to-latex` | Faithful `.tex` matching the `.docx` |
| Draft a recommendation / support / appreciation / acceptance / dispense letter | `/recommendation-letter` | `recommendation-letter` skill | LaTeX letter(s) compiled to PDF in `out/` |
| Measure LaTeX manuscript hygiene (forbidden characters, AI-usage score, word count, brace balance, citation coverage) | `/texcheck` | `latex-hygiene` skill | Hygiene report / AI-usage score / word count |
| Ask whether the toolkit is correctly deployed to every harness, and which empty mirror cells are deliberate | `python .claude/skills/rt-observe/scripts/rt_state.py` | `rt-observe` skill | Mirror matrix (canonical definitions x harness dialects, eight states), registry integrity, repo green stamp and profile, plan progression, MCP roster, local models, vault daemon, sessions |
| Apply an audit plan to a `.tex`, post-write scan, resolve and build the PDF | `/texcheck patch` / `scan` / `accept` / `build` | `latex-hygiene` skill | Patched `.tex` + `FAILS:` list, scan report, accepted `[final]` source, build report (`errors= undefined= doi_links= pages`) |

## Local delegation flows

Keep the top cloud model as orchestrator and push token-heavy generation to local models on
the GPU. Each local agent runs on a cheap cloud model (Haiku) that frames the task and drives
a local model over `ollama_bridge.py` (Ollama's HTTP API); the bulk output is generated
locally and free. No gateway; cloud stays on the normal subscription auth.

| Goal | Agent | Model | Output |
|---|---|---|---|
| Docstrings, code comments, Markdown docs, CHANGELOG, Obsidian summaries | `local-writer` | haiku wrapper + the resolver's writer-role model (bridge) | Rule-compliant text written to the target file |
| Code against a spec/failing test, refactor snippets, scaffolds | `local-coder` | haiku wrapper + the resolver's coder-role model (bridge) | Minimal, style-matched code edits |
| Tune a local Ollama model's context window and KV cache type for this GPU | `opt-local-vram-llm` skill (`/opt-local-vram-llm`) | measured sweep against `optimize_ollama.evaluate_rung` | Tuned `-gpu` tag, `local-model-config.json` measurement, candidate declared in `local-models.json` |
| Budget-bounded develop-and-improve loop | `loop-engineer` skill (`/loopdev`) | Fable 5 orchestrates; Opus plans; Sonnet executes/reviews; local agents generate | Branch + PR at the human merge gate, `PROCESS.md` + score ledger |
| Persist and reuse learnings in the Obsidian vault (during a loop) | `local-writer` (write) + `local-coder` (read) | haiku wrappers + bridge | Atomic notes in `30_Ressources/`, project logs in `10_Projets/`, no daily note; single serialized writer, the outbox is the write path, not a fallback |

The KV cache type is a daemon-wide environment variable that Ollama reads only at daemon
start, not per request. `opt-local-vram-llm` therefore restarts the daemon once for each
value it sweeps, proves the restart actually took the new value by reading `server.log`
rather than trusting the restart script's exit code, and restores the original value if the
sweep fails or is interrupted, so the machine is never left on a value chosen by a search
that did not complete.

Bridge rule: the local model sees only the prompt (no repo, no conversation), so every rule
constraint and input must be in the prompt; write it to a scratchpad file and hand that file
to `ollama_bridge.py --prompt-file <file> --role <writer|coder>`, which speaks Ollama's HTTP
API. Never `ollama run`, and never a model name: the bridge asks `model_resolver.py`, the
only thing that names a tag, and a resolver naming no qualified model is an explicit stop -
there is NO fallback tag. `--role` decides which qualified tag comes back, so the coder
agent stops being served the writer model. LiteLLM (`~/.litellm/ollama.yaml`) is optional
(keep-alive / context tuning only).

Restarting the daemon (after any `OLLAMA_*` change, since it reads them once at start):
`.\.claude\skills\opt-local-vram-llm\scripts
estart-ollama.ps1`, which lives inside the
skill that owns the daemon axis. Never `Stop-Process -Name "ollama*"` by hand - Ollama
runs the model in a CHILD process named `llama-server.exe`, which that pattern does not
match, so the child survives and keeps its slice of VRAM. Up to three orphaned instances
were seen this way, and they produced a false throughput measurement before anyone noticed
the card was shared. The script kills both names, verifies against `nvidia-smi` that the
memory actually came back, and prints the `OLLAMA_*` values the restarted daemon now has.

LaTeX boundary: `local-writer` may add `%` comments in a `.tex` file but never authors
LaTeX or scientific prose - that stays with `latex-writer` + `scientific-writing` on the
latest cloud Claude model.

Memory rule, both memories: during a loop, `local-writer` is the single serialized writer of the
vault AND the single caller allowed to consult or refresh the graphify graph, both enforced by
`vault-access-guard.py` at the tool boundary. For the vault specifically, `local-writer` and
`local-coder` reads only (task start, checkpoints, error recovery); plan-time reads are baked in
by `brainstorming` / `writing-plans`. Requires Obsidian open with the CLI on; deferred writes
flush via the outbox hook. Full design in [../../docs/contributor-notes.md](../../docs/contributor-notes.md)
section 5 for the vault and section 6 for the code graph, which is governed identically and by the
same guard.

Loop-engineering stop gate (default, composite): tests green AND no CRITICAL/HIGH review
finding AND aggregate score `>=` min_score (default 90). Hard stops: budget cap
(`--budget`), max iterations, or a no-progress plateau. Security is a hard floor (any
CRITICAL fails the gate). Merge to a protected branch is human-gated; local agents never
merge on their own. See `Architecture.md` "Layer 5 - Loop engineering" for the loop and
use-case diagrams.

Talk rendering on Windows: `paper2talk` converts a deck to PDF through **PowerPoint COM**
(`SaveAs(..., 32)`), not LibreOffice. The `document-skills:pptx` wrapper
(`scripts/office/soffice.py`) assumes a POSIX socket and fails here with
`module 'socket' has no attribute 'AF_UNIX'`; `soffice` is tried first only when it is on
`PATH`. Page images come from Poppler's `pdftoppm`, which ships with the MiKTeX install.

## LaTeX maintenance

- Validate TiKZ figures with `/tikz` before committing them (anchoring, perpendicular
  arrows, no overlaps, TiKZiT compatibility).
- Diagnose and fix LaTeX build errors with `/latex` (reads `out/*.log` first, cites the
  failing line, states whether a two-pass recompilation is needed).

## Calling an agent explicitly

Agents are normally triggered by context. To invoke one directly, address it by name, for
example: "Use the `scopus-auditor` agent to audit the review in `literature_review.tex`."
The slash commands are thin wrappers over these agents.

## Documentation maintenance

After a substantive change, update the relevant doc and verify that links resolve. Keep
`README.md` and `Architecture.md` as the authoritative inventory; do not duplicate their
tables into `.claude/CLAUDE.md`.

## Where code belongs

Any code written while operating on this repo lives inside ResearchTools. Not only scripts:
modules, helper libraries, hooks, test fixtures, generators, and the small pieces of glue
that end up mattering. Never in the session scratchpad, and never in the manuscript, thesis,
or grant directory being worked on. This is what makes the repository improve itself rather
than the same work being redone next session in a directory that gets archived.

Language is not a criterion, and neither is size. Python, PowerShell, shell, and anything
else follow the same rule. The default home is the owning skill's
`.claude/skills/<skill>/scripts/` directory, with an offline test beside it in `Test/`. Code
the whole repo owns rather than one skill has its own established homes - `.claude/hooks/`
for hooks, `profiles/` for domain profiles, `install.ps1` and `setup.ps1` at the root - and
belongs there instead; a repository-wide `scripts/` directory is not a home for code that
exactly one skill drives.

The test of ownership is who calls it. Measured 2026-08-28: a PowerShell script restarting a
local daemon sat in `scripts/dev/` although exactly one module called it, and the earlier
wording of this rule said "Python script", so nothing flagged it; it now lives beside its
only caller. A skill that cannot find the code it drives is a broken skill, not a broken
repository layout. Before writing any of it, search the "ResearchTools script
surface" inventory in `.claude/rules/testing.md` for code or a subcommand that already does
the job, and extend it with a flag or a subcommand rather than forking it.

Stated as a citable rule: **R18** - a script lives beside its only caller. One caller means
the owning skill's `scripts/` directory; several callers mean one of the repository-wide homes
named above.

1. **Look before writing.** Search `.claude/skills/*/scripts/` for an existing script or
   subcommand. `.claude/rules/testing.md` carries the full inventory of the script surface,
   one line per script, and is the fastest way to check.

2. **Extend before creating.** Add a subcommand to a neighbouring skill's script rather than
   a second script. A new skill needs a reason beyond convenience.

3. **Write it in ResearchTools, with a test.** English names, a module or header docstring
   stating purpose and pipeline stage, type hints in signatures where the language has them,
   and at least one offline test under `scripts/Test/` needing no network, no API key and no
   model load. A script whose effect is a machine state change (a daemon restart, an
   environment variable) is tested through the module that drives it, with the process call
   patched, rather than left untested because it is not Python. Add the test to the
   offline-test block of `.claude/rules/testing.md` in the same commit.

4. **Register it.** Codex is the ONE harness with a native skill convention, so a skill
   does get a mirror there: `install.ps1` writes a frontmatter-only pointer to
   `.agents/skills/<name>/SKILL.md`, with the description trimmed to whole sentences against
   Codex's list budget. For every OTHER harness a skill has no mirror, so the routing table in
   `.claude/CLAUDE.md` plus `README.md`, `Architecture.md` and this file are the only discovery
   paths. Because that Codex description is trimmed, a skill's trigger vocabulary must sit in
   its FIRST sentence, the one guaranteed to survive. Follow `docs/authoring-and-mirrors.md`.

5. **Then call it from the project directory.** A manuscript directory may hold a thin shell
   wrapper that calls the ResearchTools script with project-specific paths. It must hold no
   logic.

Exemption test: genuine one-off exploration (a count, a grep, a shape check that will never
be re-run) stays in the session scratchpad and is deleted. A one-off edit applied through an
interpreter counts as exploration; a function or a rule someone would want again does not,
however few lines it is. The test is whether a second paper, or a second session, would want
it; if yes, or even probably, promote it before the session closes. A
session that ends with code that should have been promoted deposits it in
`docs/superpowers/todo/<date>-<name>-src/` with a TODO so the debt is recorded rather than
lost.

Anti-pattern to name explicitly: a patch script whose body is one long list of literal
find-and-replace pairs for a single manuscript. That is data wearing a script's clothes. The
harness goes to ResearchTools; the pairs belong in the audit plan the agent already emits,
in a form the harness can read.

## Adding or editing an agent, skill, or command

Follow the turnkey guide `docs/authoring-and-mirrors.md`: it names the canonical source
for each kind (`.claude/agents|skills|commands/`), the per-type doc-update checklist
(README, Architecture, the `.claude/CLAUDE.md` routing table, this file), and the mirror
regeneration. After editing any agent, command, or rule, re-run `.\install.ps1 -Profile
<active>` and commit the regenerated `.github/`, `.opencode/`, `.continue/`,
`CONVENTIONS.md`, and `AGENTS.md` mirrors together with the canonical change.

**`-Personal` is not optional when an agent was added.** The ordinary run never touches
`~/.copilot/agents`; only `.\install.ps1 -Personal` does, and it also copies the generated
prompt and instruction files into the VS Code user profile. Every agent or command added since
the last such run is invisible to those two targets. Measured 2026-08-30: six agents had no
Copilot CLI mirror and seven commands had never reached the VS Code user profile, with nothing
reporting either gap. `rt-observe` reports both as `lost`.

Skills have a mirror in exactly one harness - Codex, at `.agents/skills/<name>/SKILL.md`. In
every other harness a user-invoked skill is discoverable only via the routing table.

## Environments

Use the correct virtual environment for the layer you are working in, and run the relevant
tests manually before pushing (see `testing.md`). There is no CI/CD pipeline.
