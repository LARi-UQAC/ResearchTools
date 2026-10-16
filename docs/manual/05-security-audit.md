# Security Audit (SkillSpector)

Chapter 05 of the ResearchTools manual. Back to [table of contents](../../README.md).

All eight skills under `.claude/skills/` were scanned with **SkillSpector v2.2.3** in
static-only mode (`skillspector scan <skill> --no-llm`) on **2026-06-18**, every dependency
finding cross-checked against `pip-audit`.

**True positives — corrected**

- **LP3 (missing permission declaration):** added to the frontmatter of `scopus`, `deliberation`,
  `extract-statistic`, `scholar-evaluation`, `word2latex`, and `drawio2tikz` a per-skill
  `permissions:` list declaring exactly the capabilities each skill's scripts use (e.g. `scopus`
  → `[env, read, write, network]`), plus an `allowed-tools: [Read, Write, Edit, Bash]` runtime
  restriction. Re-scan confirms LP3 cleared with no LP1/LP4 regression.
- **SC1 (unpinned dependencies):** pinned `>=` to exact `==` versions in
  `scopus/scripts/requirements.txt` (requests, google-genai, openai) and
  `extract-statistic/scripts/requirements.txt` (pymupdf4llm, pymupdf, docling, markitdown),
  using versions confirmed clean by `pip-audit`.

**False positives — reviewed and ignored**

- **SC4 (vulnerable dependency):** flagged by package name only; `pip-audit` resolves every
  declared `>=` floor to a patched release (`No known vulnerabilities found`).
- **E1 / E2 (external transmission / env harvesting):** skills reading their own configured API
  keys and querying their own research APIs (Elsevier, Unpaywall, Semantic Scholar).
- **TT2 (taint flow):** the https-only, redirect-disabled PDF download in `download_pdf.py`.
- **PE3 / RA2 / EA1 / EA2 / P6:** keyword matches inside docstrings/markdown (e.g. `SNIPList`,
  the `GITHUB_TOKEN` doc line, a `**…tool:**` bullet, a DOI-workflow description, a returned
  local prompt string).
- **AST4 (subprocess):** the test harness invoking the skill script with a fixed argument list.

`scientific-writing` and `extract-futureworks` required no changes.

The `geolocalisation` skill was added after this scan (2026-07) and should be scanned on the
next pass. Its declared dependencies pin exact/floor versions verified with `pip-audit`:
`matplotlib==3.9.2`, `pillow>=12.3.0` (fixes PYSEC-2026-2253..2257), and the optional
`folium==0.17.0` / `PyMuPDF==1.27.2`. It declares `permissions: [read]` and
`allowed-tools: [Read, Write, Edit, Bash]`, reuses the scopus skill's network I/O through
`download_pdf.py` rather than opening its own, and fetches only public-domain Natural Earth
basemaps (TLS-verified, cached).

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
`.claude/settings.template.json`; `install-junctions.ps1 -Sync` copies the script and its
config, and `setup.ps1` adds the entry to a live `settings.json` that lacks it.

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
File locations: [11-file-locations.md](11-file-locations.md).

---
[← 04 Skills](04-skills.md) | [Table of contents](../../README.md) | [06 Aider nightly pipeline →](06-aider-pipeline.md)
