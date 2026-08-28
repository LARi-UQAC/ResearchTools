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
- Agent, skill and command definition files are English-only (`R22`). French appears only in
  the strings a deliverable emits and in the repo-root `CLAUDE.md`; a definition file mixing
  the two makes a rule unsearchable in either language.

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

## Reuse over reinvention

- Prefer existing agents, skills, and commands (see the routing table in `.claude/CLAUDE.md`)
  over ad hoc scripts.
- Reuse existing utilities and patterns in a project before adding new code.
- Search the "ResearchTools script surface" inventory in `.claude/rules/testing.md` before
  writing any new script, and extend an existing script with a flag or a subcommand rather
  than forking it.
