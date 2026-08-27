# Preferences

General working preferences for any project in this workspace. Project-specific docs and
conventions take precedence where they exist.

## Documentation structure

- Keep an authoritative inventory in `README.md` and, for relationships, `Architecture.md`.
- Cross-layer context lives in `.claude/CLAUDE.md`; do not duplicate it elsewhere.
- Code rules and style live in `.claude/rules/` (this folder), not in end-user docs.
- When documenting a feature, update the relevant doc and link it from the index rather than
  scattering notes.

## Language

- Two languages: French (default) and English.
- For academic work: French by default for a UQAC thesis, English for scientific papers.
- Keep user-facing strings centralized (a single localization source) rather than inline.

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

## Reuse over reinvention

- Prefer existing agents, skills, and commands (see the routing table in `.claude/CLAUDE.md`)
  over ad hoc scripts.
- Reuse existing utilities and patterns in a project before adding new code.
- Search the "ResearchTools script surface" inventory in `.claude/rules/testing.md` before
  writing any new script, and extend an existing script with a flag or a subcommand rather
  than forking it.
