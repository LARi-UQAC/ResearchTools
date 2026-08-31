# Preferences

General working preferences for any project in this workspace. Project-specific docs and
conventions take precedence where they exist.

## Documentation structure

- Keep an authoritative inventory in `README.md` and, for relationships, `Architecture.md`.
- Cross-layer context lives in `.claude/CLAUDE.md`; do not duplicate it elsewhere.
- Code rules and style live in `.claude/rules/` (this folder), not in end-user docs.
- When documenting a feature, update the relevant doc and link it from the index rather than
  scattering notes.
- A change to a script's CLI surface (a new flag, a renamed subcommand, a changed default)
  updates that script's line in the "ResearchTools script surface" inventory of
  `.claude/rules/testing.md` in the same commit (`R23`). That inventory is the only discovery
  path a skill has, so one that lags is worse than none.

## Language

- Two languages: French (default) and English.
- For academic work: French by default for a UQAC thesis, English for scientific papers.
- Keep user-facing strings centralized (a single localization source) rather than inline.
- Agent, skill and command definition files are English-only (`R22`), and since 2026-08-30 so
  is every `CLAUDE*.md` in this repository, `CLAUDE.template.md` included. French appears only
  in the strings a deliverable emits, such as the `ALERTE: behind=N commits` line the git-sync
  rule prints; a definition file mixing the two makes a rule unsearchable in either language.
  The exemption that used to cover the repo-root `CLAUDE.md` was revoked when U5 translated the
  template: the live `~/.claude/CLAUDE.md` stays French until the operator installs the
  translation deliberately, and `check-claude-template.ps1` reports that gap by comparing the
  two files' top-level titles rather than trying to classify a whole-file difference.

## Output and token habits

- Start sessions lean: `/slim` for quick tasks, `/concis` for exploratory work.
- Scope long sessions with `/focus <topic>`; check pressure with `/ctx` before `/compact`.
- Prefix shell commands with `rtk`; caveman style is expected in chat.

## Working norm (academic)

- Never accept the first idea; verify it against validated references via the `scopus` skill,
  weighing disadvantages almost as much as advantages.
- Never fabricate references or DOIs. Webfetch may confirm a fact but cannot be a citation.
- Use the reference-label convention `firstauthor-year-keyword` and the `fig:`/`tab:`/`eq:`
  label conventions from `code-style.md`.
- Ask (AskUserQuestion) when a concept or requirement is unclear.

## Verified claims

- **R14 - no invented API, flag, path or file name.** The standard that forbids a fabricated
  DOI applies to code: check that a command, an option, a module or a file exists before
  recommending it. Measured 2026-08-14: a local model answered a documented LaTeX question
  with a command that does not exist, which is why the bridge now refuses to run without a
  vault consultation. A structural gate does not catch an untrue answer.
- **R15 - a documented claim about behaviour names the test that proves it, or is marked
  unverified.** The offline-test block of `testing.md` reads that way on purpose, one line
  saying what each suite proves. A claim with no test and no marker is read as verified by
  the next session.

## Asking the user

**R25 - a question put to the user states the origin of the choice, what each option does,
and what it costs.** `AskUserQuestion` is the only moment where the work stops and a person
has to decide, so the question has to be answerable by someone who has not read the code.
Four parts, all of them required:

1. **Origin.** What produced the choice, named concretely: the file and line, the flag, the
   measurement, the failing case. "Which approach do you prefer" with no origin asks the user
   to reconstruct the problem before they can answer it.
2. **Behaviour per option.** What actually happens if that option is taken, in the
   `description`, not in the `label`. A label is a name, never an explanation.
3. **Consequence.** What the option costs, forecloses, or leaves unfixed. An option with only
   upsides is an option that has not been thought through, and the user cannot weigh two
   options whose costs are unstated.
4. **Recommendation first.** The recommended option is option 1 and its label ends with
   `(Recommended)`. Having an opinion is part of the work; a flat menu pushes a judgment back
   onto the user that the session was better placed to make.

Forbidden: an option whose `label` is a bare noun (`Option A`, `Strict`, `YAML`) with a
`description` that restates it; a question that names no file, no measurement and no error; a
set of options whose descriptions state no cost. When nothing has a real cost, the choice was
not the user's to make and should have been decided in the session instead.

This rule is enforced mechanically, not only in prose. `askuserquestion-clarity.py` is a
`PreToolUse` hook on `AskUserQuestion` that refuses a call whose options carry no description,
whose descriptions merely restate their labels, or whose recommended option is not first, and
returns the reason so the question can be rewritten rather than dropped. It checks the
structural minima only: a hook can prove that a description exists and is longer than its
label, and cannot prove that it is true or useful. The four parts above remain the standard;
the hook catches the cases where the standard was not even attempted. Thresholds live in
`askuserquestion-clarity.json` beside it (R0), and a missing or unparsable config disables the
gate in silence rather than refusing every question (R11). Proven by
`.claude/hooks/Test/test_askuserquestion_clarity.py` (R15).

Measured 2026-08-30 on this machine: `PreToolUse` does fire on `AskUserQuestion`, which the
Claude Code hook documentation does not state either way - it names only `EndConversation` as
excluded. A probe hook recorded `tool_name: "AskUserQuestion"`, `hook_event_name:
"PreToolUse"`, and a `tool_input` carrying one key, `questions`, whose entries hold
`question`, `header`, `multiSelect` and `options[].label` / `options[].description` (R13).

## Reuse over reinvention

- Prefer existing agents, skills, and commands (see the routing table in `.claude/CLAUDE.md`)
  over ad hoc scripts.
- Reuse existing utilities and patterns in a project before adding new code.
- Search the "ResearchTools script surface" inventory in `.claude/rules/testing.md` before
  writing any new script, and extend an existing script with a flag or a subcommand rather
  than forking it.
