# File Locations Summary

Chapter 16 of the ResearchTools manual. Back to [table of contents](../../README.md).

The agents, commands, skills, hooks and rules live under this repository's `.claude/` directory. The tree below is a map of folders, checked 2026-10-22.

```
ResearchTools\
├── .claude\
│   ├── agents\               21 flat .md files, one per agent           (chapter 05)
│   ├── commands\             32 .md files, one per slash command        (chapter 04)
│   ├── skills\               25 folders: SKILL.md, scripts\, Test\      (chapter 06)
│   │   └── AGENTS.md         nested instructions that Codex reads
│   ├── hooks\                8 hook scripts with their JSON configs, Test\,
│   │   └── git\              the global personal-data guard             (chapters 07, 15)
│   ├── rules\                code-style, preferences, security, testing, workflows (chapter 08)
│   ├── settings.template.json  hook entries and env, merged into ~/.claude/settings.json
│   ├── settings.json         shared project settings, committed
│   └── CLAUDE.md             routing table, active profile, working protocols
├── .github\                 generated agents, prompts, instructions; workflows
│                             privacy-scan.yml and review.yml; issue and PR templates
├── .opencode\ .continue\ .agents\    generated mirrors for other harnesses (chapter 09)
├── docs\                    index.md, manual\ (the 19 chapters), deep-dive pages,
│                             superpowers\ (plans, specs, notes: not published)
├── scripts\                 audit\ ci\ docs\ lib\ local\ test\       (chapter 16)
├── deploy\                  form-service API, compose file, Caddyfile, initdb\
├── profiles\                engineering, cosmetic, _template            (chapter 02)
├── setup.ps1  install.ps1  install-junctions.ps1  rt-dashboard.(ps1|sh|bat)
├── mirror-policy.json  mkdocs.yml  requirements-docs.txt
└── README.md  Architecture.md  NEW_ARCHITECTURE.md  CLAUDE.template.md
    AGENTS.md  CONVENTIONS.md  CHANGELOG.md  IMPROVEMENTS.md
```

Four things sit in the clone and are never committed: the three Python environments `.venv-skills`,
`.venv-docs` and `.venv-pdf2md` (built in the main clone by `setup.ps1 -InstallPython`), the green stamp `.rt-green.json`, the undo copies in `.rt-undo/`, and the built site in
`site/`. The generated code graph folder is also local, and it is reached only through the
`local-writer` agent. The per-skill file lists that this chapter used to carry are gone: they went
stale as skills were added, and each skill's own `SKILL.md` and the [skills chapter](06-skills.md)
are the authority.

<!-- local-coding:begin -->
**Local coding contract files.** In the `loop-engineer` skill: `scripts/plan_contract.py`,
`scripts/loop_bounds.py`, `scripts/token_count.py` and the data file `plan-tiers.json`. In
`.claude/hooks/`: `review-loop-guard.py` and `local-coder-dispatch-guard.py`, each with a JSON
config beside it. The review-loop bounds of a worktree live in `rt-review-loop.json` inside that
worktree's git directory, so they are never committed and two worktrees never share them. The
chapter is `docs/manual/11-local-coding.md`, with its flowchart source under
`docs/manual/diagrams/`. See [chapter 11](11-local-coding.md).
<!-- local-coding:end -->

## Machine-local files (never committed)

The git privacy guard (`.claude/hooks/git/`, see [15-security-audit.md](15-security-audit.md)
and [`security.md`](../../.claude/rules/security.md)) is installed from repo-tracked source
into three places, neither of the latter two part of the repository tree above:

- **Repo-side source**, tracked: `.claude/hooks/git/` — `pre-commit`, `pre-push`,
  `privacy-lib.sh`, `privacy-extra.awk`, `privacy-guard.conf`, `fixture-path-allow.txt`,
  `privacy-rules.toml`, `install-git-hooks.ps1` (plus two files the installer reads here but
  never copies anywhere: `deny-term-stopwords.txt`, `sync-folder-markers.txt`).
- **Copied by the installer** to `~/.config/git/hooks/` (`core.hooksPath`): `pre-commit`,
  `pre-merge-commit` (a copy of `pre-commit`, since a clean merge runs only that one),
  `pre-push`, `_chain` (plus one copy per other chained hook name), `privacy-rules.toml`,
  `privacy-lib.sh`, `privacy-extra.awk`, `fixture-path-allow.txt`, `privacy-guard.conf`.
- **Machine-local, never committed, and not inside any repository at all**: live in the
  install folder, outside the tracked tree entirely, so they are not "gitignored files" so
  much as files no repository holds in the first place. What protects a stray copy pasted
  into a repository is the global git ignore the installer writes
  (`core.excludesFile`, else `<XDG_CONFIG_HOME or ~/.config>/git/ignore`), which also lists
  all three file names.
  - `private-terms.txt` — the generated deny list, extended for each new student
    (`-TermsFrom <folder>`): the installer only appends names it does not already have,
    never rewrites the list.
  - `private-terms.extra.txt` — hand-added terms.
  - `private-terms.excluded.txt` — fragments the extractor set aside (common words, or
    shorter than the configured length floor).

---
[← 17 ThesisTracker integration](17-thesistracker-integration.md) | [Table of contents](../../README.md)
