# GitHub Repository Presentation Playbook

**Audience:** a Claude Code session setting up (or overhauling) a GitHub repository's public
presentation for a lab project — README, documentation structure, community files, and repo
settings. This is a procedure to execute, not a narrative to read once.

**Reference implementation:** `LARi-UQAC/ResearchTools`, built through this exact sequence.
Where a step needs a concrete example, this file points at the real file in that repo rather
than inventing one — read the cited file, don't guess its shape.

**Scope:** this playbook covers *presentation and process* (how the repo looks, how docs are
organized, how contributions flow). It does NOT cover the lab's language/style/security rules
for the *content* of the code or prose itself — those live in `.claude/rules/*.md` of each
project and are out of scope here. If the target repo has its own `.claude/rules/`, read it
first; nothing in this playbook overrides it.

**Do not fabricate.** Every badge, count, and claim below must be verified against the actual
repo before being written (file counts, chapter counts, license, existing assets). A number
copied from this playbook without checking is exactly the kind of stale claim this whole
process exists to prevent.

---

## Phase 0 — Prerequisites

Check before starting, don't assume:

```bash
gh auth status          # needs at least: repo, project scopes. Re-check — scopes drift.
gh api user --jq .login # confirms which account is actually authenticated
```

- `gh` CLI installed and authenticated with `repo` scope (repo settings, badges data) and
  `project` scope (Phase 7 board) — see `gh auth status`. If a scope is missing:
  `gh auth refresh -s <scope>`.
- If the plan includes generating a GIF/image asset: `ffmpeg` on PATH (`ffmpeg -version`). On
  Windows with `scoop` available: `scoop install ffmpeg-essentials`.
- If the plan includes a themed documentation site: Python 3 for a **dedicated** virtualenv
  (never reuse a project's own test/runtime venv for doc tooling — see Phase 5).
- Ask the user, don't guess, before starting: does this repo already have a `CONTRIBUTING.md`,
  design assets, or a documented brand? Overwriting existing work without checking is worse
  than a slow start.

---

## Phase 1 — Find or define the brand

**Do not invent colors.** Before picking any palette:

1. Search the repo for existing design assets — a `post-media/`, `assets/`, `brand/`, or
   `design/`-named folder, any `.html` design template, any style guide doc. This is worth a
   real search (`find . -iname "*brand*" -o -iname "*template*.html" -o -iname "*.dc.html"`),
   not a quick glance — the ResearchTools reference implementation had a full brand system
   sitting in `post-media/Series Template.dc.html` (a Claude Design export) that nobody had
   surfaced into the README before this process ran.
2. If found: extract the exact hex values (background, primary accent, secondary accent,
   text color) and the font family. Do not approximate ("looks like teal") — read the CSS
   values directly.
3. If genuinely nothing exists: ask the user for 2-3 brand colors, or propose a minimal
   palette (one dark neutral, one accent) and get explicit sign-off before applying it
   everywhere. Do not default to a generic palette (a framework's default blue, shields.io's
   default colors) and call it "the brand."
4. Record the palette once, in one place (see Phase 5's `extra.css` for where), and reuse it
   everywhere — badges, diagrams, the doc site theme. A repo with five different accent colors
   across its README, its Architecture doc, and its badges looks like nobody is driving.

---

## Phase 2 — Documentation structure

### 2a. Decide: does the README need to split?

Rule of thumb, not a hard number: past roughly 400-500 lines or when a single `README.md`
covers more than 4-5 genuinely distinct topics (installation, every skill/feature, every
command, architecture, file layout...), split it. Below that, a single well-organized README
is fine and a split is over-engineering.

If splitting: the reference pattern is `docs/manual/`, one file per topic, numbered for a
stable read order:

```
docs/manual/
  00-purpose.md          # mission, roadmap, this manual's own conventions
  01-installation.md
  02-<topic>.md
  ...
  NN-file-locations.md   # or whatever the last natural topic is
```

Chapter file template (every chapter, no exceptions):

```markdown
# <Chapter Title>

Chapter NN of the <Project> manual. Back to [table of contents](../../README.md).

<content>

---
[← <prev-num> <prev-title>](<prev-file>.md) | [Table of contents](../../README.md) | [<next-num> <next-title> →](<next-file>.md)
```

- First chapter: no "← previous" link. Last chapter: no "next →" link.
- **Before moving content out of the root README, grep the project's own test suite for
  hardcoded reads of that file.** A test can assert that specific literal substrings exist in
  `README.md` by path (`Path(__file__)... / "README.md"`), and content moved into a chapter
  file will fail that test silently — no compile error, just a red test run later. Search
  `Test/*.py`, `Test/*.ps1`, or equivalent, for the literal string `"README.md"` before
  restructuring, and either keep the required substrings in the thinned root file (in a
  pointer/quickstart section) or update the test.
- If any chapter grows long (over ~300 lines) and has multiple `###`-level subsections, add an
  in-chapter mini table of contents right after the intro, with anchor links to each
  subsection. **Compute the anchors mechanically, do not hand-guess them** — GitHub's heading
  slug algorithm removes em-dashes and slashes entirely (it does not turn them into hyphens),
  which produces double-hyphens in places a hand guess will get wrong:

  ```python
  import re
  def gfm_slug(heading_text):
      s = heading_text.lower()
      s = re.sub(r'[^\w\- ]', '', s)   # strip everything except word chars, spaces, hyphens
      return s.replace(' ', '-')
  ```

  This is GitHub's own algorithm specifically. If the repo will also be served through MkDocs,
  Sphinx, or any other renderer, know that **their slugifiers are not the same algorithm** —
  an anchor correct on GitHub can silently fail to jump inside a different renderer's build.
  Verify per target, don't assume portability.

### 2b. Root README.md becomes the entry point, not the whole story

Once split, the root `README.md` is a slim landing page: title, badges, a hero visual, a short
pitch, a table of contents, and links to every chapter — not the chapter content itself. See
Phase 4 for the exact template.

### 2c. A `docs/index.md` for an optional documentation site

Add this even before deciding on Phase 5, since it costs nothing: a plain landing page
listing every chapter and every deep-dive reference doc, so the `docs/` folder itself makes
sense to a browsing human even without any site generator running.

---

## Phase 3 — Community health files

GitHub recognizes a specific set of files and reports their presence under
Insights → Community Standards. Add each one, adapted to the project (never copy the reference
implementation's own contact email, license holder, or project-specific rules verbatim):

| File | Purpose | Notes |
|---|---|---|
| `CONTRIBUTING.md` (root) | How to contribute | Point to existing detailed docs rather than duplicating install/test steps; keep it thin |
| `CODE_OF_CONDUCT.md` (root) | Community standard | Contributor Covenant v2.1 is a reasonable default; needs a real contact (email or a person), not a placeholder |
| `SECURITY.md` (root) | Vulnerability reporting | State the REAL threat model (a local research tool with no exposed service is not "enterprise compliance scenarios" — don't cargo-cult SOC2/HIPAA language that doesn't apply) |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist | Mirror the project's OWN existing rules (test command, doc-update requirement) rather than a generic checklist — see Phase 7 |
| `.github/ISSUE_TEMPLATE/bug_report.md`, `feature_request.md`, `config.yml` | Structured issues | `config.yml` with `blank_issues_enabled: false` if you want to force template use |
| `.github/CODEOWNERS` | Default reviewers | One line minimum: `* @<owner>` |
| `.gitattributes` | Line-ending normalization | `* text=auto eol=lf` plus explicit `binary` markers for every image/video/document extension in the repo — a binary file with no `binary` marker risks silent corruption from text normalization |
| `.editorconfig` | Cross-editor formatting | Standard template; exclude `.md` from `trim_trailing_whitespace` (Markdown's hard-line-break convention uses a trailing double-space) |
| `.github/FUNDING.yml` | Native GitHub Sponsor button | Only if the project actually has a funding link; check it doesn't already exist before adding |
| `CHANGELOG.md` (root) | User-facing version history | Distinct audience from an engineering decision log if one exists (e.g. this repo's `IMPROVEMENTS.md`) — a CHANGELOG answers "what changed for someone using this," a decision log answers "why, for whoever maintains it." Don't merge the two. |

**Check first, every time:** `.github/FUNDING.yml` and similar files may already exist and be
correctly configured. Read before writing.

---

## Phase 4 — README.md template

Order that worked, annotated. Adapt content, keep the shape:

```markdown
# <Project Name>

[![License](...)] [![Language/Platform](...)] [![Docs](...)] [![Stars](...)]
[![Last commit](...)] [![Contributors](...)] [![Open issues](...)]

<!-- Banner: a real rendered image carrying the project's identity + one-line pitch.
     Not the bare logo alone — see Phase 4a on how to actually render one. -->
<p align="center"><img src="path/to/banner.png" alt="..." width="900"></p>

<!-- Logo + a short demo (GIF or screenshot) side by side, in an HTML table for
     GitHub-reliable side-by-side layout (plain adjacent <img> tags wrap unpredictably): -->
<table align="center" border="0" cellspacing="0" cellpadding="0">
<tr>
<td align="center"><img src="logo.png" width="200"></td>
<td align="center"><img src="demo.gif" width="420"></td>
</tr>
</table>

<details>
<summary><b>Table of contents</b></summary>

- [links to every section below]

</details>

<!-- 1-2 sentence pitch, then 3-4 bullets of what it actually does. Bullets should read as
     genuinely distinct capabilities, not a padded, suspiciously symmetric list — vary
     sentence length and structure, or it reads as AI-generated filler. -->

## Why <Project>
<!-- A short before/after table beats a feature list for selling the value proposition.
     Ground every row in a real, named capability — never a generic claim. -->

## See it in action
<!-- A real screenshot or GIF of the actual running tool. Not a mockup. -->

## Quickstart
<!-- The minimum commands to get running. Link to a full install chapter for the rest. -->

## Manual chapters
<!-- If split (Phase 2): a small "at a glance" diagram (Mermaid, in the SAME brand colors
     as everything else — see Phase 1) plus the chapter table. -->

## Supported harnesses / platforms
<!-- If relevant: a row of badges for what's supported, in ONE consistent color rather than
     a different hue per badge — a uniform color reads as "one coherent set," a rainbow
     reads as unplanned. -->

## Support this project
<!-- Sponsor/donate links, star ask — near the BOTTOM, not competing with the pitch at the
     top for the reader's first few seconds of attention. -->
```

### 4a. Actually rendering a banner (not just describing one)

A banner built as static HTML/CSS (for precise brand control) needs to be rendered to an
image before it's useful in a README — an unrendered `.html` source file wired nowhere is not
a banner, it's a draft. If the session's tools include a headless browser (e.g. a Playwright
MCP) but `file://` navigation is refused and starting a local server is denied by a permission
classifier (both are legitimate safety gates — don't try to bypass either):

1. Commit the HTML file (and any local image assets it references) to the repo, pushed to
   GitHub.
2. Navigate the headless browser to
   `https://htmlpreview.github.io/?https://github.com/<owner>/<repo>/blob/<branch>/<path-to-file>.html`
   — a free public service that serves a GitHub-hosted HTML file back with the correct
   `text/html` content type (GitHub's own `raw.githubusercontent.com` serves it as
   `text/plain`, which is why a browser won't render it there) and rewrites the file's
   relative asset links to resolve against the same repo.
3. Screenshot the rendered page, save the result as a real PNG asset in the repo, and
   reference THAT image from the README — not the HTML source.

This only works for a file already pushed to a reachable GitHub location; it does not help
preview *uncommitted* local changes to the HTML.

### 4b. If the hero is a GIF made from an existing video

**Check the first frame before finalizing.** A source clip with an intro/background-only
lead-in produces a GIF whose resting frame (what a slow-loading page, or any static-preview
context, shows) is blank or content-free — this is invisible until checked directly against
the live page, not just a local preview. Extract candidate start frames as stills
(`ffmpeg -ss <t> -i input.mp4 -frames:v 1 probe.png`) and look at them before committing to a
start offset; don't assume the source "probably starts fine."

Two-pass palette technique for a compact, high-quality GIF:

```bash
ffmpeg -ss <offset> -i input.mp4 -vf "fps=12,scale=480:-1:flags=lanczos,palettegen" palette.png
ffmpeg -ss <offset> -i input.mp4 -i palette.png \
  -filter_complex "fps=12,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse" output.gif
```

---

## Phase 5 — Optional: a themed documentation site (MkDocs Material)

Only worth it once `docs/manual/` (Phase 2) exists with real content — theming an empty
folder is wasted effort.

1. **Dedicated environment**, never the project's own test/runtime venv:
   ```bash
   python -m venv .venv-docs
   .venv-docs/Scripts/python.exe -m pip install mkdocs-material
   ```
   Audit it (`pip install pip-audit && pip_audit --strict`), then remove `pip-audit` and its
   own transitive dependencies from the pinned requirements file — they were a one-off audit
   tool, not a doc-site dependency. Pin what's left with `pip freeze`.

2. **`mkdocs.yml`** at the repo root, `docs_dir: docs`, explicit `nav:` (don't rely on
   auto-discovery — it will include scratch/plan-authoring content you don't want on a public
   site), and the brand palette from Phase 1 applied via `extra_css` overriding Material's CSS
   variables (`--md-primary-fg-color`, `--md-accent-fg-color`, etc.) rather than settling for
   Material's nearest built-in named color.

3. **`exclude_docs:` for anything under `docs/` that isn't meant for the site** (a
   plan-authoring scratch folder, work-in-progress notes). **`not_in_nav:` is NOT an
   exclusion** — it only hides a file from the sidebar while still building it, and a
   malformed file that GitHub's renderer tolerates can still crash MkDocs's own build (a
   Python-Markdown/HTML-parser edge case is a measured example). Use `exclude_docs:` for
   anything that must not be processed at all.

4. **Build locally and read the warnings**, don't just trust the source: `mkdocs build`
   (add `--strict` to fail on any warning, useful for a first pass, but expect and accept two
   categories of warning as informational rather than bugs — see the gotchas below).

5. **No CI/CD if the project has a "no automated pipeline" policy**: publish with a manual
   `mkdocs gh-deploy` (pushes a `gh-pages` branch by hand) rather than a GitHub Actions
   workflow. Document the manual command in `docs/index.md`. Enabling the Pages *setting*
   itself (Settings → Pages → Deploy from branch → `gh-pages`) is a repo-settings change for
   the human to make, not something to script.

**Known, acceptable gaps to document rather than "fix" into a bigger scope:**
- A link from inside `docs/` to a file OUTSIDE `docs_dir` (e.g. the root `README.md`,
  `Architecture.md`) resolves fine on GitHub's own browser but not inside the MkDocs build,
  since its `docs_dir` only knows about `docs/`. State this, don't silently break the
  GitHub-browsing experience trying to force both to work identically.
- GitHub's own heading-slug algorithm and MkDocs/Python-Markdown's slugifier diverge (see
  Phase 2a) — an in-page anchor correct on GitHub can fail inside the built site.

---

## Phase 6 — GitHub repository settings (via `gh`, verify before and after)

All of these are real API calls with real effects — read the current state first, and read it
back after to confirm, rather than trusting a silent success:

```bash
# Current state, before touching anything
gh api repos/<owner>/<repo> --jq '{description, has_wiki, has_projects, has_discussions, topics}'

# Description + topics ("About" section — the first thing a visitor sees, before README)
gh repo edit <owner>/<repo> --description "<one sentence>" \
  --add-topic <topic1> --add-topic <topic2> ...

# Discussions on, if useful for informal Q&A separate from Issues
gh api -X PATCH repos/<owner>/<repo> -f has_discussions=true

# Wiki off, IF genuinely redundant with docs/manual/ + a doc site — ask first, don't assume
gh api -X PATCH repos/<owner>/<repo> -f has_wiki=false

# Verify
gh api repos/<owner>/<repo> --jq '{description, has_wiki, has_projects, has_discussions, topics}'
```

**Social preview image and enabling the Pages setting itself are web-UI-only** — no API path
for either as of this writing. Prepare the asset (Phase 4a's banner is a better fit than a
bare logo for the image, given GitHub's ~1280×640 social-card aspect ratio), then hand the
human the exact setting path (Settings → Social preview / Settings → Pages).

**First version tag**, once content is in a shippable state — don't invent a version number
unilaterally, it's a public-facing decision:

```bash
git tag -a v0.1.0 -m "<summary>"     # ask the user for the actual number, don't assume 0.1.0 fits
git push origin v0.1.0               # a push — confirm the project's own git-ownership norms first (Phase 8 note)
gh release create v0.1.0 --title "..." --notes "..."
```

---

## Phase 7 — Process rules: Issue/board/PR/docs discipline

If the target project has its own numbered-rule convention (like `.claude/rules/*.md` R-numbers
in this codebase), ADD to that sequence — check the current highest number first
(`grep -rhoE "\*\*R[0-9]+" .claude/rules/*.md | sort -t R -k2 -n -u | tail -5`) and update any
index/cross-reference that states the old bound in the SAME edit (see the gotcha below). If the
project has no such convention, write these as plain prose policy in `CONTRIBUTING.md` instead
of inventing a numbering scheme it doesn't otherwise use.

**Pattern 1 — a PR needs a linked Issue and a board card before it opens.** Reference
implementation: `.claude/rules/workflows.md` R30 in `LARi-UQAC/ResearchTools`. Steps: open an
Issue naming the problem → add it to the repo's own GitHub Project board
(`gh project item-add <project-number> --owner <owner> --url <issue-url>`) → open the PR
referencing the Issue (`Closes #<N>`). Exempt trivial fixes (typo, broken link) from the
ceremony.

**Pattern 2 — a PR does not merge until the documentation it touches is updated, in the same
PR.** Reference implementation: R31 in the same file. This is a merge-time gate the reviewer
checks, complementing Pattern 1's open-time gate — "will fix docs later" is not an approval.

**Setting up the board**, if one doesn't exist for the repo yet:

```bash
gh project create --owner <owner> --title "<Project> Roadmap"
gh project link <number> --owner <owner> --repo <owner>/<repo>
# Seed it with existing open issues:
gh project item-add <number> --owner <owner> --url <issue-url>
# And with draft cards for anything already written as a prose roadmap somewhere in the docs:
gh project item-create <number> --owner <owner> --title "<item>" --body "<context>"
```

**Gotcha, measured on this exact playbook's own reference implementation:** a rule file that
lists a numeric range or count another file also states (e.g. "rules R0 to R27", "18 skills")
WILL drift the next time a new item is added, unless updating every place that states the old
bound is treated as part of the same edit — not a follow-up. This repo's own
`.claude/rules/code-style.md` "Rule identifiers" index had silently stopped naming two rules
for an unknown number of sessions before this playbook's authoring cycle caught and fixed it.
Grep for the old bound and fix every hit, every time.

**Gotcha — junction/symlink propagation:** if the rules directory being edited is shared
across multiple projects via a symlink or directory junction (check the project's own install
docs), an edit here goes live EVERYWHERE that junction reaches, immediately, with no sync step
and no guard rail. A rule drafted with a concrete example from the current repo (a literal
project-board URL, a literal owner name) will read wrong the moment another project's session
reads it. Phrase the generalizable rule generically ("the repo's own board") and cite the
concrete example separately, clearly marked as one instance rather than the universal target.

---

## Phase 8 — Verification checklist (run before handing back)

- [ ] Every internal markdown link resolves — script it, don't eyeball a 100+-line README:
  ```python
  import re, os
  # walk every changed .md file, regex for ']( ... )', skip http(s) and '#'-only anchors,
  # os.path.normpath+exists() the rest relative to the file's own directory
  ```
- [ ] If the project has an offline test suite that reads `README.md` or another doc file by
      literal path for required substrings (see Phase 2a), re-run it after every doc edit —
      not just once at the end.
- [ ] After pushing: compare the local committed blob SHA against what GitHub actually serves
      (`git rev-parse HEAD:<path>` vs `gh api repos/<owner>/<repo>/contents/<path> --jq .sha`)
      for anything that "should just work" but is easy to get wrong (binary assets especially).
      A byte-for-byte cached CDN response can look like a bug that isn't one — check this
      before assuming a push failed.
- [ ] Actually LOOK at the live rendered page (a headless-browser screenshot of the real
      `https://github.com/<owner>/<repo>` URL) at least once — a markdown source that "should"
      render correctly can still surprise you (an animated GIF's static first frame, a badge
      that silently fails to fetch its logo, a collapsed `<details>` block that looks broken
      collapsed). Don't declare success from source inspection alone.
- [ ] Clean up debug artifacts before finishing: screenshots taken for verification, headless
      browser snapshot files (check for a stray directory left behind, e.g.
      `.playwright-mcp/`), temp probe frames. Add a `.gitignore` entry for the tool's own debug
      output directory if this is a recurring pattern, so it can't be accidentally committed
      again — this repo found one such file that had been sitting committed since an earlier,
      unrelated session.
- [ ] Respect the project's own git-ownership norm. Some projects want the session to commit
      and push freely; others want every commit/push left to the human. This is NOT
      universal and can change mid-session — if told "let me commit and push myself," that
      applies from that point forward, including for work already staged. Don't assume a
      general "yes, go ahead" from earlier in a session extends to git operations unless it
      was said about git specifically.

---

## Appendix — Things this playbook got wrong the first time (keep this section growing)

Real, measured mistakes from building the reference implementation, so the next run doesn't
repeat them:

- Assumed a video file's opening frame was representative without checking — it was a
  content-free background blur, invisible until verified against the actual live page.
- Assumed `file://` rendering was categorically blocked with no alternative, and told the user
  so — a working `https://` route (`htmlpreview.github.io`) existed and was found only after
  being asked to try again.
- Hardcoded a specific repo's project-board URL directly into a rule meant to generalize
  across every project a shared rule file reaches.
- Left a stale "R0 to R27" bound in a cross-reference index for at least two rule additions
  before it was caught.
- Assumed a differently-named file (`LogoLARI_FINAL.png` vs `LogoLARI_trim.png`) sitting at
  the repo root was dead duplicate weight without checking — it was referenced by a separate
  pipeline. Grep before proposing a deletion, every time.
