# ResearchTools improvements

What the toolkit has learned, newest last. Appended automatically whenever a ResearchTools
weakness is fixed from inside another project, and whenever an attempt is abandoned.

There is no git in that loop, so this file is the record: it answers "what has my toolkit
learned" and "when did this behaviour change". The full rule is the RT-CONTRACT block in
`~/.claude/CLAUDE.md`, whose source is `CLAUDE.template.md`.

Format: one entry per fix. Date, owning skill or agent, what changed, where it was found,
and how it was proven. An abandoned attempt is marked ABANDONED and names the failing test,
its error, and any file left behind skip-marked.


## 2026-09-26 — Architecture.md diagram palette recolored; graphify deferral (markdown)

**Change:** Three diagram elements in Architecture.md recolored to the project's brand palette (teal `#1F9E8F` and amber `#C9762F` against generic defaults). Routine application of existing palette knowledge, no new learning.

**Deliberately NOT changed:** NEW_ARCHITECTURE.md's 13 diagrams remain untouched — that file is shared with ThesisTracker and not yet finalized. Recoloring would fork the synced copies; consolidation is planned later.

**Graphify:** AST-only refresh at repository root. File is Markdown (documentation), not code. Semantic pass deferred — no code structure or content semantics changed, only visual formatting applied. Cost-benefit: AST sufficient to track presence and dependency links; semantic pass would cost a model call for no structural gain.

**Project log:** appended entry to `10_Projets/Logiciels/ResearchTools/Decisions.md` via outbox.

## 2026-09-26 — MkDocs Material GitHub Pages asset-path fix; semantic pass deferred to vault note

**Defect found and fixed on live site:** MkDocs Material's `theme.logo` and `theme.favicon` configuration references can reach assets outside `docs_dir` via parent-relative paths (e.g., `../ResearchToolsLogo.png` at the repository root). This pattern works in `mkdocs serve` (local domain root, no path prefix) but breaks silently on GitHub Pages PROJECT pages (`https://<user>.github.io/<repo>/`): Material emits root-absolute hrefs (`/ResearchToolsLogo.png`) instead of repo-relative ones, missing the `/<repo>/` prefix and returning 404. Discovered 2026-09-26 by navigating the live site and checking the browser console.

**Fix:** copied logo to `docs/assets/ResearchToolsLogo.png` and updated `mkdocs.yml` `theme.logo` and `theme.favicon` to use relative paths (`assets/ResearchToolsLogo.png`). Redeployed with `mkdocs gh-deploy`.

**Durable learning:** atomic note `30_Ressources/Publication/mkdocs-github-pages-asset-path-guard.md` documenting the root cause, guard rule, and reusability across static-site generators on PROJECT pages. Key: LOCAL PREVIEW CANNOT CATCH THIS — the bug is invisible until live deploy. Verification: browser console check on the real URL.

**Project log:** appended 2026-09-26 entry to `10_Projets/Logiciels/ResearchTools/Decisions.md`.

**Graphify:** AST-only refresh at repository root (`graphify update .`). Semantic pass deferred: changed files are config (`mkdocs.yml`) and image (`docs/assets/ResearchToolsLogo.png`), neither code. No semantic extraction justifies the model cost; AST-only sufficient to track dependencies and file presence.

## 2026-09-26 — MkDocs landing page built; base64 context-cost lesson captured; graphify deferral
