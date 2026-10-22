# Security audit and guards

Chapter 13 of the ResearchTools manual. Back to [table of contents](../../README.md).

Every skill under `.claude/skills/` is scanned with **SkillSpector v2.2.3** in static-only mode
(`skillspector scan <skill> --no-llm`), and every dependency finding is cross-checked against
`pip-audit`. The scan is rerun by hand: nothing schedules it.

## Skill scan of 2026-10-22 (all 25 skills)

The first scan, on 2026-06-18, covered the eight skills that existed then. The repository now holds
25, so the scan was rerun on all of them on 2026-10-22. Result: 289 findings, 3 critical, 135 high, 136 medium and 15 low.

| Skill | Findings | Critical | High | Medium | Low | SkillSpector verdict |
|---|---|---|---|---|---|---|
| `aider-setup` | 56 | 0 | 39 | 17 | 0 | DO_NOT_INSTALL |
| `deliberation` | 13 | 0 | 5 | 5 | 3 | DO_NOT_INSTALL |
| `drawio2tikz` | 0 | 0 | 0 | 0 | 0 | SAFE |
| `extract-contributions` | 1 | 0 | 0 | 1 | 0 | SAFE |
| `extract-futureworks` | 0 | 0 | 0 | 0 | 0 | SAFE |
| `extract-paper-idea` | 2 | 0 | 0 | 2 | 0 | CAUTION |
| `extract-statistic` | 7 | 0 | 6 | 1 | 0 | DO_NOT_INSTALL |
| `form-service` | 2 | 0 | 0 | 1 | 1 | SAFE |
| `geolocalisation` | 9 | 1 | 6 | 1 | 1 | DO_NOT_INSTALL |
| `latex-hygiene` | 4 | 0 | 2 | 2 | 0 | DO_NOT_INSTALL |
| `loop-engineer` | 29 | 1 | 14 | 11 | 3 | DO_NOT_INSTALL |
| `narrative-cv` | 5 | 0 | 1 | 1 | 3 | DO_NOT_INSTALL |
| `obsidian-cli` | 28 | 0 | 6 | 22 | 0 | DO_NOT_INSTALL |
| `opt-local-stt-vram` | 4 | 0 | 3 | 0 | 1 | DO_NOT_INSTALL |
| `opt-local-vram-llm` | 10 | 0 | 5 | 5 | 0 | DO_NOT_INSTALL |
| `paper2talk` | 21 | 0 | 11 | 9 | 1 | DO_NOT_INSTALL |
| `pdf2md` | 8 | 0 | 6 | 2 | 0 | DO_NOT_INSTALL |
| `professor-expertise-finder` | 4 | 0 | 0 | 3 | 1 | CAUTION |
| `recommendation-letter` | 3 | 0 | 1 | 2 | 0 | DO_NOT_INSTALL |
| `rt-observe` | 25 | 0 | 8 | 16 | 1 | DO_NOT_INSTALL |
| `scholar-evaluation` | 0 | 0 | 0 | 0 | 0 | SAFE |
| `scientific-writing` | 1 | 0 | 0 | 1 | 0 | SAFE |
| `scopus` | 41 | 1 | 14 | 26 | 0 | DO_NOT_INSTALL |
| `word2latex` | 0 | 0 | 0 | 0 | 0 | SAFE |
| `wp-portfolio-sync` | 16 | 0 | 8 | 8 | 0 | DO_NOT_INSTALL |

Seven skills are rated SAFE, two CAUTION and sixteen DO_NOT_INSTALL. That last verdict is a measure
of how many patterns matched, not of intent. A static scan with no model cannot tell that a skill
runs a subprocess, reads its own API key or writes a file **because that is its job**. The findings
fall into two groups.

**Expected by design, judged by rule family.** Each family was judged from its rule name and the
purpose of the skill, as in June. The 289 findings were not each opened one by one, so a real defect
hiding inside a family is not excluded. `AST3`, `AST4` and `AST7` (a subprocess, a dynamic
import or `getattr`) are the scripts and their tests. `E1`, `E2`, `TT2` and `TT3` are a skill reading
its own configured key and querying its own research API: the critical `TT3` on `scopus` is the
Elsevier key sent as a header to Elsevier. `RA1`, `RA2`, `EA1` to `EA4`, `OH1`, `OH3`, `P2`, `P6`,
`PE3`, `TM1`, `TM3` and `YR1` or `YR4` match words in documentation prose and prompts, or the
`aider-setup`, `rt-observe` and `loop-engineer` code that drives other processes. The two critical
`SC4` (`pillow` in `geolocalisation`, `claude-agent-sdk` in `loop-engineer`) flag a package by name,
and `pip-audit` reports no known vulnerability for either file.

**Real, open, and not fixed by the documentation change that recorded them.**

| Finding | Where | Measured |
|---|---|---|
| `LP3`, no permission declaration in the skill frontmatter | `extract-contributions`, `extract-paper-idea`, `form-service`, `latex-hygiene`, `obsidian-cli`, `professor-expertise-finder`, `recommendation-letter`, `rt-observe`, `wp-portfolio-sync` | the June scan fixed this for six older skills by adding `permissions:` and `allowed-tools:`, and these nine were added later |
| Advisories on `pypdf` 6.19.0, fixed in 6.21.1 | `form-service`, `narrative-cv`, `paper2talk` | `pip-audit` on 2026-10-22 |
| Advisories on `pillow` 12.3.0, fixed in 13.0.0 | `extract-statistic`, `pdf2md` | `pip-audit` on 2026-10-22 |
| Advisories on `docling` and `docling-slim` 2.103.0 | `extract-statistic` | `pip-audit` on 2026-10-22 |
| `SC1`, unpinned `claude-agent-sdk>=0.1.0` | `loop-engineer` | the requirements file itself asks for an exact pin after the first install |

The dependency advisories appeared after the last pins (2026-10-16), which is why a pinned and
clean requirements file goes stale without any edit. Raising a pin is a change to code that needs the
offline suite, so it is a separate change from this one.

The June scan found the same kinds of false positive and its true positives were corrected then:
the `permissions:` declarations, and exact `==` pins in the `scopus` and `extract-statistic`
requirements. `geolocalisation` declares `permissions: [read]` and fetches only public-domain
Natural Earth basemaps, TLS-verified and cached.

The security hooks that run in every session (secret scanning, vault access, prompt-injection
warnings) are described in [chapter 07](07-hooks.md).

## Worktree link guard (`git worktree remove`)

A third, narrow layer: the `worktree-link-guard.py` hook refuses `git worktree remove` when the
worktree holds a junction or a symbolic link. Measured 2026-10-16 on a throwaway copy: with a
link that git ignores, which is the real case since `.gitignore` carries `.venv*/`, even a plain
`git worktree remove` with no `--force` follows the link and empties the folder it points at.
That is how the main clone's `.venv-skills` was lost on 2026-10-06 (rule R37).

The refusal lists each link and gives the command that deletes the link and never its target
(`cmd /c rmdir "<link>"`). Its limits are stated rather than hidden: it judges that one command
through the Bash and PowerShell tools only, so it does not see `rm -rf` or `Remove-Item
-Recurse`, and it cannot resolve a path held in a variable or a command substitution. A scan
that reaches `max_entries` (`.claude/hooks/worktree-link-guard.json`) before finishing is
refused too, since a link could hide in the part not reached. A missing or broken config
disables the gate in silence and never blocks a tool (R11). The hook is declared in
`.claude/settings.template.json`. `install-junctions.ps1 -Sync` copies the script and its
config once the offline suite is green: the green stamp hashes the hook `.json` files as
well as the `.py` ones (before 2026-10-16 it hashed `.py` only, so every hook config was
held forever and had to be copied by hand). The entry reaches a live `settings.json` through
the default flow of `setup.ps1`, which adds the entries that are missing and touches nothing
else. `setup.ps1 -InstallJunctions` alone does not edit `settings.json`.

## Personal-data guard (every git repository, this machine)

A second, separate layer from the SkillSpector scan above: a global git hook, installed once
for every repository on this machine (`core.hooksPath`, via
`.claude/hooks/git/install-git-hooks.ps1`), that blocks three different things in the staged
or pushed diff before they reach a remote:

- **Secrets**, via betterleaks' own rule shapes (keys, tokens, credentials).
- **Personal-data shapes**, via `privacy-rules.toml` (account paths, Quebec code permanent,
  `@etu.uqac.ca` addresses, FRQ ids). This machine's own account name is NOT a `toml` rule: it
  is a separate dynamic check in pre-commit (reads `USERNAME`/`USER`, whole-token match in
  added lines and staged paths), since a static rules file cannot know the account name of
  whoever runs it.
- **Real names**, via a machine-local **deny list** - students, co-authors - extended for
  each new student with
  `install-git-hooks.ps1 -TermsFrom <student folders> [-TermsDepth N]`: the installer only
  appends names it does not already have, never rewrites the list, into `private-terms.txt`
  (generated), alongside `private-terms.extra.txt` (hand-added terms) and
  `private-terms.excluded.txt` (fragments the extractor set aside: common words, or shorter
  than the configured length floor). It also refuses to write the list into a
  OneDrive/Dropbox/network-synced folder. A name has no detectable SHAPE the way a secret
  or an account path does, which is why this deny list exists as its own layer.

Three layers, in order: a `pre-commit` hook (the staged diff), a `pre-push` hook (every commit
a push would publish, including one made with `--no-verify` or by a rebase/cherry-pick that
never ran `pre-commit`), and CI's `privacy-scan` workflow as a last, SHAPE-only backstop - it
runs on every push AND pull request, with its verdict taken from the rules committed on `main`
so a pull request cannot weaken them, but it cannot hold the machine-local deny list, since
that list is deliberately never committed - see below.

**What this does not cover, stated plainly:**

- **The deny list never leaves this machine**, by design (an operator ruling, 2026-10-15): it
  is machine-local, outside every repository, so CI's own `privacy-scan` workflow enforces
  secret/shape rules only, never the real-name list. A name caught locally is NOT re-checked
  in CI.
- **GitHub comments, PR bodies, and issues have no automatic control at all.** A real name
  typed into a PR description or a review comment is not scanned by anything in this guard.
- **A determined bypass still exists.** `--no-verify` at commit skips only pre-commit;
  pre-push still scans every outgoing commit, so evading both needs `--no-verify` at BOTH
  commit AND push. A repository-local `core.hooksPath` override, or
  `git config privacyguard.enabled false`, also skips the check - the global hook is a
  convenience, not a technical guarantee a determined commit cannot evade.

Full detail, including the three settings (`privacyguard.enabled`,
`privacyguard.absolutePaths`, `privacyguard.minTermLength`) and every installed file:
[01-installation.md, Step 6](01-installation.md) and
[`.claude/rules/security.md`](../../.claude/rules/security.md)'s "Personal-data guard" section.
File locations: [18-file-locations.md](18-file-locations.md).

## Automated pull-request review (billed, optional)

A second workflow, `.github/workflows/review.yml` (Issue #65, PR #67), asks a headless Claude Code
session to run two built-in review skills, `security-review` and `code-review`, on every pull
request opened from a branch of this repository. It posts ONE consolidated list, Critical to Low,
as a single pull-request comment that is updated on each push, and copies it onto the Issue named
by a `Fixes #N` line in the PR description. Unlike `privacy-scan` it is **not free**: each run
spends Anthropic API tokens, capped per run by `MAX_BUDGET_USD` in the workflow (a number the
operator chose, not measured, to be set to fit the account). It needs the repository secret
`ANTHROPIC_API_KEY`, which only the repository owner adds. Without it the check ends neutral and
nothing is billed. A fork or a Dependabot pull request is skipped, and so is a pull request that
changes only regenerated files.

What protects the key, since the session reads an untrusted diff:

- The session has four tools only (`Skill`, `Read`, `Grep`, `Glob`): no shell, no file writes, no
  sub-agent, no plugin, no project settings. After the run, a guard reads the session's own tool
  list and fails the job if anything else is there or the list cannot be read.
- The session posts nothing. A later step with no key sanitises its reply (no mention, no issue
  or pull-request reference, no link, no image, no raw HTML, no math, no invisible character) and
  writes the comment, so a crafted line in a diff cannot ping anyone or leak a secret.
- The job that writes to Issues holds no key, and the job that holds the key cannot write to
  Issues.

**What this does not cover, stated plainly:**

- **A collaborator with write access can run a modified copy of the workflow with the secret.**
  The `Main protection` ruleset requires a code-owner review for a merge into `main`, not for the
  run. The first run therefore uses a throwaway key with a low spend limit, which is rotated
  afterwards.
- **Three behaviours are unverified until that first run:** that the pinned Claude Code honours
  the tool restriction, that the two skills run in a headless session, and that the `/proc` read
  denial is accepted. The workflow header lists them, and the guard fails closed on the first.
- **It is advisory.** It does not replace a human review, and it is not a required check.
- `tech-debt` and `ai-firstify` are not run in CI: the action cannot pin a plugin source, so third
  party code could change unreviewed beside the key. They remain available in a local session.

**Using AugureAI instead of Anthropic (planned rework, about one month out, not done yet).** The
workflow is written for Anthropic only. Switching to AugureAI would need these changes, none made:

- A repository secret `AUGUREAI_API_KEY`, read in the key check and in the action's key input
  instead of `ANTHROPIC_API_KEY`.
- The variable `ANTHROPIC_BASE_URL` set to `https://api.augureai.ca/v1` in the agent step. That is
  the endpoint the local `claude-augure` function already uses for a Claude Code session.
- The header comment, the CI section of `testing.md`, the playbook and `test_review_workflow.py`
  updated to the new secret name, since the test pins where the secret may be named.

Three points are unverified: whether the action passes `ANTHROPIC_BASE_URL` through to Claude
Code, whether AugureAI honours the tool restriction and the spend cap, and whether the execution
file keeps the same shape for the tool-list guard. The first throwaway-key run would answer them.

Full detail, with every finding and decision of the review that shaped it:
[`.claude/rules/testing.md`](../../.claude/rules/testing.md)'s "CI" section and
[`docs/github-repo-setup-playbook.md`](../github-repo-setup-playbook.md) Phase 6d, which tells you
how to set the same workflow up in another repository.

---
[← 14 Aider nightly pipeline](14-aider-pipeline.md) | [Table of contents](../../README.md) | [16 Maintenance, checks and CI →](16-maintenance.md)
