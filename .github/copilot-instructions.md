# ResearchTools - Copilot instructions

Academic toolkit: LaTeX writing, Scopus reference validation, paper/thesis
auditing, grant-template conversion. Authoritative academic standards (writing
rules, reference policy, approved publishers, figure/table/equation rules) live
in `.claude/CLAUDE.md` - read it before producing academic content.

Specialized custom agents (invoke from the agents panel, `/agent` in Copilot
CLI, or `copilot --agent <name>`):

- `authoring-loop`: see `.github/agents/authoring-loop.agent.md` (full definition in `.claude/agents/authoring-loop.md`)
- `bib-cleaner`: see `.github/agents/bib-cleaner.agent.md` (full definition in `.claude/agents/bib-cleaner.md`)
- `cover-paper`: see `.github/agents/cover-paper.agent.md` (full definition in `.claude/agents/cover-paper.md`)
- `latex-writer`: see `.github/agents/latex-writer.agent.md` (full definition in `.claude/agents/latex-writer.md`)
- `litreview-updater`: see `.github/agents/litreview-updater.agent.md` (full definition in `.claude/agents/litreview-updater.md`)
- `local-coder`: see `.github/agents/local-coder.agent.md` (full definition in `.claude/agents/local-coder.md`)
- `local-writer`: see `.github/agents/local-writer.agent.md` (full definition in `.claude/agents/local-writer.md`)
- `paper-auditor`: see `.github/agents/paper-auditor.agent.md` (full definition in `.claude/agents/paper-auditor.md`)
- `reviewer-response`: see `.github/agents/reviewer-response.agent.md` (full definition in `.claude/agents/reviewer-response.md`)
- `scopus-auditor`: see `.github/agents/scopus-auditor.agent.md` (full definition in `.claude/agents/scopus-auditor.md`)
- `scopus-researcher`: see `.github/agents/scopus-researcher.agent.md` (full definition in `.claude/agents/scopus-researcher.md`)
- `submit-checker`: see `.github/agents/submit-checker.agent.md` (full definition in `.claude/agents/submit-checker.md`)
- `talk-builder`: see `.github/agents/talk-builder.agent.md` (full definition in `.claude/agents/talk-builder.md`)
- `thesis-auditor`: see `.github/agents/thesis-auditor.agent.md` (full definition in `.claude/agents/thesis-auditor.md`)
- `thesis-proposal-auditor`: see `.github/agents/thesis-proposal-auditor.agent.md` (full definition in `.claude/agents/thesis-proposal-auditor.md`)
- `thesis-to-paper`: see `.github/agents/thesis-to-paper.agent.md` (full definition in `.claude/agents/thesis-to-paper.md`)
- `word-to-latex`: see `.github/agents/word-to-latex.agent.md` (full definition in `.claude/agents/word-to-latex.md`)

Task prompt files are available as slash commands in Copilot Chat (see
`.github/prompts/`). Helper skills (Scopus API scripts, statistics extraction,
scientific-writing rules, corpus study-location mapping, recommendation/support/
acceptance letters, Obsidian vault operations) are plain repo folders under
`.claude/skills/` - read the relevant `SKILL.md` when a task calls for it (e.g.
`geolocalisation` to map where a corpus's studies were conducted,
`recommendation-letter` to draft a support/recommendation/acceptance letter from
a candidate's files, `latex-hygiene` to score a manuscript's mechanical hygiene
(forbidden characters, AI-usage risk, word counts, brace and citation balance)
before applying an audit plan and building it, or `obsidian-cli` to read or
search the Obsidian vault through its allowed command surface, since skills have
no mirror of their own).

Hard rules: validate every reference against Scopus (scripts in
`.claude/skills/scopus/scripts/`); never fabricate references or DOIs; LaTeX
output goes to `out/`.

Obsidian vault writes go through the outbox only: deposit the note in
`~/.claude/obsidian-outbox/` with a first-line directive and let the
`obsidian-outbox-flush.py` hook write it through the filesystem. The Obsidian CLI
commands `create`, `append` and `prepend` are forbidden, together with
`eval`, `dev:*`, `plugin:install`, `theme:install` and every `sync*`
except read-only `sync:history`. The one exception is
`vault_consolidate.py --apply --yes`, an in-place link repair in notes that already
exist, dry-run until `--yes` is passed.

Local generation goes through `.claude/skills/loop-engineer/scripts/ollama_bridge.py`,
never `ollama run`. The bridge resolves the model itself through `model_resolver.py`
and refuses rather than substituting a weaker one, so no agent or script names a model
tag. `--role writer` or `--role coder` says WHICH work is being done, and the resolver
returns the tag qualified for that role; without it both roles share one tag.
`--vault-context <terms>` is MANDATORY: the bridge searches the vault itself and
exits 2 when neither it nor `--no-vault-context` is given, because a local model asked a
documented question with no context answers with a fluent invention that passes every
structural gate.

Any Python script an auditing or authoring agent needs is created inside
ResearchTools, under `.claude/skills/<skill>/scripts/`, with an offline test
beside it in `Test/` - never in the session scratchpad and never in the
manuscript, thesis, or grant directory being worked on. Search the
"ResearchTools script surface" inventory in `.claude/rules/testing.md` first,
and extend an existing script with a flag or a subcommand rather than forking
one; the manuscript directory may hold a thin wrapper that calls the
ResearchTools script by path, never logic of its own. Several of the largest
agents (`paper-auditor`, `scopus-auditor`, `scopus-researcher`,
`thesis-auditor`, `thesis-proposal-auditor`, `reviewer-response`,
`cover-paper`) are the very agents that write such scripts, and are delivered
above as stubs pointing back at `.claude/agents/<name>.md` - read the
canonical file when the stub is what you were given, since this rule lives in
the full body, not the stub.

This file is generated by `install.ps1` - edit the canonical sources,
not this mirror.
