# Progress - Issue #53, paper2talk web deck LARI MVP

Marks: `- [ ]` not done, `- [x]` done with a short result, `- [!]` blocked with one line of
reason. One section per plan file. Updated by the executing model only.

## plan1.md

- [x] Task 0 - operator confirmed the four values on 2026-10-08 (provenance: chosen by the
  operator, R4): swipe threshold 40 px; maximum embedded asset size 10 MiB per file; footer
  field cap 48 characters; lab asset filenames `en-tete1260.jpg` (banner) and
  `LogoLARI_FINAL.png` (logo). Execution method approved: native, sequential.
- [x] Task 1 - check_web flags relative references (2026-10-08). 7 tests added to
  `TestWebTarget` in `test_talk_validate.py`. RED: 25 -> 32 tests, 6 failures (relative img,
  relative stylesheet, relative CSS url() x3 quoting forms, protocol-relative `//`); the 3
  negative controls (data:/#/mailto: pass, `src=` in script text ignored, external URL
  reported once) passed before and after. GREEN: `talk_validate.py` adds `_RE_ATTR_REF`,
  `_RE_CSS_URL`, `_INLINE_PREFIXES`, `_EXTERNAL_PREFIXES` and a second pass in `check_web`;
  http(s) keeps its original message. `test_talk_validate.py`: Ran 32, OK. Other paper2talk
  suites unchanged (test_talk_pptx / test_to_a4 error only on missing `pptx` / `pypdf`,
  pre-existing, NOT RUN under the suite runner). Known effect: until Task 2, a rendered web
  deck whose figure has no `data_uri` is now reported, by design.
- [x] Task 2 - figures embedded as data URIs for HTML output (2026-10-08). 12 tests added
  in `TestAssetEmbedding` (`test_talk_model.py`), fictitious fixtures only. RED: 13 -> 25
  tests, failures=1 errors=15 (missing `AssetError`, `embed_asset`, `WEB_ASSET_MAX_BYTES`,
  `model_dir`; CLI returned 0 instead of 2). GREEN: `talk_rules.py` adds
  `WEB_ASSET_MAX_BYTES` (10 MiB, operator), `IMAGE_SIGNATURES`, `SVG_MIME`; `talk_model.py`
  adds `AssetError`, `_image_mime`, `embed_asset` (resolve then contain, R24),
  `_embed_figures` (deep copy) and `render_template(..., model_dir=)`; `main()` passes the
  model's folder and maps `AssetError` to exit 2. `test_talk_model.py` Ran 25 OK;
  `test_talk_validate.py` (Task 1) Ran 32 OK. Probe replay: missing figure -> exit 2 naming
  it; present figure -> data:image/png in the deck and `--web` clean.
- [x] Task 3 - lab assets via --lab-dir (2026-10-08). 9 tests in new class `TestLabAssets`
  plus 2 Task 2 edge-case tests in `TestAssetEmbedding` (`test_talk_model.py`), fictitious
  fixtures generated in the tests, no lab asset copied into the repository. RED pass 1:
  25 -> 36 tests, errors=11 (9 at setUp on missing `LAB_ASSET_FILES`; 2 `KeyError: 'asset'`).
  RED pass 2, after adding only the data constant: errors=9 (`template_requirements` and
  `load_lab_assets` missing; argparse `SystemExit: 2` on unknown `--lab-dir`; Jinja
  `UndefinedError: 'lab'` because `requires` was not enforced; the 2 `KeyError`s). GREEN:
  `talk_rules.LAB_ASSET_FILES` (banner `en-tete1260.jpg`, logo `LogoLARI_FINAL.png`,
  operator); `talk_model.template_requirements` (header comment lines, both delimiters),
  `supported_blocks` now delegates to it with its contract unchanged; `load_lab_assets`
  through `embed_asset`; `render_template(..., lab_dir=)` adds `lab` only for a template
  declaring `requires: lab-assets` and refuses with `AssetError` without it; CLI
  `--lab-dir`. Edge case: a web figure with no `asset` now raises `AssetError` naming the
  slide (CLI exit 2) instead of `KeyError`. One test corrected during GREEN: it expected exit
  0, but the fixture's text-only slide is a content rule (exit 1, by design); it now asserts
  "not refused" (exit != 2) plus both data URIs. Results: `test_talk_model.py` 36 OK,
  `test_talk_validate.py` 32 OK; real web and Beamer templates declare no requirement and
  render as before.
- [x] Task 4 - outline kind with divider timing (2026-10-08). Tests: `test_talk_model.py`
  new class `TestOutlineKind` (12) plus a budget-agreement test with an outline;
  `test_talk_notes.py` 1; `test_talk_pptx.py` 3 layout tests on a fake presentation (run
  without python-pptx) plus 1 render test that needs python-pptx. RED: model 36 -> 49 tests,
  failures=3 errors=7 (missing `KIND_TIER`, `KINDS`, `tier_of`, `slide_kind`,
  `outline_sections`; `ValueError ... declares tier 'outline'`; RendererGap not raised;
  Beamer sections absent; no missing-section report); notes 1 failure; pptx 5 layout
  failures. One RED test was tightened first: it passed on the old unknown-kind message.
  GREEN: `talk_rules.KIND_TIER = {"outline": "divider"}`, `KINDS`, `tier_of()`; 1/3 min
  stays only in `TIER_MINUTES` (single literal, `talk_rules.py`). `talk_model.slide_kind`,
  `slide_tier = tier_of(slide_kind)`, `outline_sections`, an outline with no section is
  reported, `assert_renderable(..., kinds)` honours `supported-kinds`, context gains
  `sections`. `talk_notes.tiers_from_model` uses `rules.TIERS` and `tier_of`. `talk_pptx`:
  outline patterns (programme, sommaire, outline, agenda, then content), layout chosen by
  kind, body lists the sections. `beamer_skeleton.tex.j2`: `supported-kinds` line and an
  outline frame listing sections, no list when there is none. Two wording fixes during GREEN
  (a test assertion and a template comment). Results: model 49 OK, notes 14 OK, validate 32
  OK, pptx 3 runnable outline tests OK. BLOCKED: `test_an_outline_slide_lists_the_sections_in_order`
  needs python-pptx (not installed, not installed by design); the pptx render path is
  unverified here.

## plan2.md

- [x] Task 5 - template context: pacing, web constants, footer check (2026-10-08). 13 tests
  in `test_talk_model.py`: `TestTemplateContext` (6) and `TestFooterFields` (7), fictitious
  data. RED: 49 -> 62 tests, failures=3 errors=7 (missing `WEB_INTERACTION`,
  `FOOTER_FIELD_MAX_CHARS`, `wpm`; `pacing` Undefined in the context; no footer report); one
  probe bug fixed first (it wrote `.tex`, which switches Jinja delimiters). GREEN:
  `talk_rules.WEB_INTERACTION = {"swipe_threshold_px": 40}` and `FOOTER_FIELD_MAX_CHARS = 48`
  (operator, 2026-10-08); `talk_model.slide_pacing` (budget_rows seconds, aligned with the
  model's own slide order); `render_template(..., wpm=)` adds `pacing` and `web`; CLI passes
  `--wpm`; `_footer_problems` in `validate_model` checks the shown field (short form when
  given) against the cap. Results: model 62 OK, validate 32 OK, notes 14 OK, 8 other suites
  OK, 3 runnable pptx outline tests OK. The web template does not consume `pacing`/`web`
  yet (Tasks 6-7).
- [x] Task 6 - lab layouts per kind (2026-10-08). New `Test/test_web_skeleton.py`, 17 tests,
  real template, generated images, fictitious metadata; imports jinja2 at the top so the
  runner reports it NOT RUN without it. RED: 16 tests, failures=12 errors=1 (no `#006341`,
  `supported-kinds` None, no `layout-<kind>`/`frametitle`/`footline`, no banner or logo,
  `Cambria` present, no alert block, no outline list, no `1 / 1`); escaping, no-external-ref
  and offline-check controls passed. `web_skeleton.html.j2` rewritten: header declares
  `supported-kinds` (six) and `requires: lab-assets`; gabarit colour tokens, brand default
  `#006341`, retired `5A7210` fallbacks gone; sans-serif only; per-kind layouts (title:
  banner, rounded green box, subtitle, authors, institute, date, logo; outline: numbered
  sections; divider: centred green title, no band; thanks: large green headline; backup and
  content: title band); footer row of its own on every NON-title slide (spec.md) with `short_author` or authors
  joined ", " (the Task 5 rule), `short_title` or title, date, `n / N`; figures `data_uri`
  only. One later RED/GREEN pair after a visual check: the closing slide's block drawn as a
  large green headline. Five accepted Task 2/3 web tests in `test_talk_model.py` given a
  generated lab folder (the template now requires it); the two that would otherwise have
  passed on the lab-folder refusal now assert their own message. Results: web 17 OK, model
  62 OK, validate 32 OK, notes 14 OK, 8 other suites OK, 3 runnable pptx outline tests OK.
  Informal visual check (headless Edge print, scratchpad only): 7 pages for 7 slides,
  layouts close to compiled reference pages 1, 2, 3, 5, 12, 21.
  Review correction (2026-10-08): the footer had also been rendered on the title slide.
  Footer test now requires no footer on the title slide and exactly one on every other
  slide (one-slide and footer-row tests adjusted to non-title slides). RED: 17 tests,
  failures=1 (title slide held a footer). GREEN: footer rendered only when kind != "title";
  web 17 OK, model 62 OK, validate 32 OK, notes 14 OK; probe: title 0 footers, the 6 others
  1 each, 7 pages printed, `--web` clean.
- [x] Task 7 - interactions and accessibility (2026-10-08). 13 tests in new class
  `TestInteractions` (`test_web_skeleton.py`), structural markers on the rendered HTML. RED:
  17 -> 30 tests, failures=10 errors=2 (no `DECK` config, guard, counter, progress,
  `slideFromHash`, fullscreen, blackout, help dialog, click/touch handlers, `announce`,
  `pacing`, print rules); reduced-motion already passed. GREEN: `web_skeleton.html.j2` adds
  `DECK` (a `tojson` literal of `web.swipe_threshold_px` and `pacing`, inside the deck's one
  script), typing/modifier guard, counter and progress bar on the viewport (outside the
  stage), `#/n` read on load (clamped 1..N, anything else ignored) and written with
  `replaceState`, `hashchange`, F fullscreen, B/. blackout, `?` help dialog (role dialog,
  aria-modal, Escape closes, focus restored), click advance with an interactive-element and
  text-selection guard, single-touch swipe at the threshold measured at stage scale with a
  multi-touch guard, `aria-live` announcement and `aria-hidden` on inactive slides, pacing in
  the notes panel (elapsed against cumulative `pacing`, clock from the first move), print
  hides the chrome. A browser check found the print path at 8 pages for 7 slides (the
  `#announce` region printed); a new RED/GREEN pair added it to the print-hidden chrome, back
  to 7 pages. Results: web 30 OK, model 62 OK, validate 32 OK, notes 14 OK, 8 other suites
  OK, 3 runnable pptx outline tests OK; probe `--web` clean, title 0 footers, others 1.
  Browser smoke (installed Edge, headless `--dump-dom`): no hash -> 1, `#/4` -> 4 (`4 / 7`,
  bar 50%), `#/99` -> 7, `#/0` -> 1, `#/abc` and `#/-2` ignored -> 1; announce text updates.
  Keyboard, click and touch not exercised in the browser (no automation tool). Found,
  pre-existing at e2f24ef and not fixed: in a window smaller than the stage the scaled
  stage is offset and cropped (grid centring of an oversized item), unchanged since then.
  Post-review responsive fix (2026-10-08): root cause, `#viewport` centred `#stage` with
  CSS grid; a grid item larger than its track starts at the container's corner, so after
  `scale()` about its centre the stage landed at 960*(1-s), 540*(1-s) (measured in Edge:
  left 403 at 1280x720, right edge 1517 past a 1254 px viewport; cropped at all four sizes
  tested). New class `TestStageFit` (4 tests). RED: 34 tests, failures=3 (stage not
  absolutely centred, `fit()` without the -50% translate, print not resetting position).
  GREEN: `#stage` absolute at left/top 50%, `fit()` applies `translate(-50%, -50%)
  scale(min(vw/1920, vh/1080))`, print sets `position: static`; canvas still 1920x1080.
  Edge measurements at `#/4` (stage inside the viewport and centred within 1 px, ratio
  1.778, slide 4, `4 / 7`, bar 50%): 1920x1080 window (viewport 1894x987) 70,0 1755x987;
  1280x720 (1254x627) 70,0 1115x627; 1366x768 (1340x675) 70,0 1200x675; 1024x768
  (998x675) 0,57 998x561. Print 7 pages; probe `--web` clean, title 0 footers + logo,
  others 1 footer. Web 34 OK, model 62 OK, validate 32 OK, notes 14 OK.
- [x] Task 8 - open only after a clean check (2026-10-08). 7 tests in `test_talk_validate.py`:
  new class `TestOpenAfterCheck` (6, `webbrowser.open` patched in every case) and one
  `--web`-without-`--open` control in `TestMainDispatch`. RED pass 1: 32 -> 39 tests,
  errors=6 (`talk_validate` had no `webbrowser`); RED pass 2 after adding only the import:
  errors=6, `SystemExit: 2` (argparse did not know `--open`); both no-open controls passed.
  GREEN: `--open` flag; after a clean `--web` check `open_in_browser()` hands
  `pathlib.Path(...).as_uri()` to the standard-library `webbrowser.open` once; findings exit
  1 and never open; an unreadable deck exits 2 and never opens; `--open` without `--web` is
  a usage refusal (exit 2); a browser that does not start (`False` or `webbrowser.Error`)
  is reported on stderr with the file to open by hand and leaves exit 0. Suppression is the
  absence of `--open` (the `/talk --no-open` opt-out is documentation, Plan 3). No browser
  is named. Results: validate 39 OK, web 34 OK, model 62 OK, notes 14 OK, 8 other suites OK.
  Integration (real CLI, probe, opener replaced by a recorder, no browser launched): clean
  + `--open` exit 0 opened once (`file:///...deck.html`); deck with one relative `src` +
  `--open` exit 1 opened 0; clean without `--open` opened 0; probe has no http, script src
  or @import.

## plan3.md

- [x] Task 9 - SKILL.md and renderer-contracts.md (2026-10-08). Documentation only, no new
  test. `SKILL.md`: section 3 gains a Web row (banner and logo from the same gabarit folder via
  `--lab-dir`, stage sizes, six kinds) and a "web deck is the LARI deck" block (render and
  `--web --open` commands with relative paths, identity, the six kinds, footer rule, embedding
  and the strict offline check, the opening contract, keys and `#/n`); section 4 states that
  `outline` is timed as a divider through `talk_rules.KIND_TIER` and counts in `n_dividers`,
  no new timing value; section 11 rows for `talk_rules`, `talk_model`, `talk_validate` and the
  web template. `renderer-contracts.md`: `kind` is no longer called the tier (six kinds,
  `KIND_TIER`, `tier_of`); template headers `supported-kinds` and `requires: lab-assets`; a
  "What a template receives" table (`sections`, `pacing`, `web`, `lab`, figure `data_uri`);
  the web render command now carries `--lab-dir` (relative) followed by `--web --open`; web
  target mechanics state the rendered-Beamer source, logo on the title slide only, stage
  centring, embedding refusals, the strict reference check, opening only what passed, print
  chrome and the interaction contract. Checks: `description:` line sha256 identical to HEAD
  (e73780a5cd252d3b); every named constant, function, flag and file present in code; no
  deferred feature, absolute user path, real name or email in the added lines; `git diff
  --check` clean. Carried forward: `docs/index.md` was reviewed and is to be left unchanged
  (no existing paper2talk capability entry), README.md likewise unless Task 11 finds an entry;
  for plan 4 Task 12 the OpenCode mirror is `.opencode/agent/talk-builder.md`, not
  `.opencode/agents/talk-builder.md`.
- [x] Task 10 - talk-builder.md and talk.md (2026-10-08). Documentation only, no new test.
  `talk-builder.md`: Step 3 "Web: none needed" replaced by the lab folder passed as
  `--lab-dir` (template `requires: lab-assets`, banner and logo embedded, exit 2 without them),
  and the ask-for-the-path rule extended to the lab folder and its two images; Step 5 gains the
  web render command (relative `--lab-dir`), the web gate `talk_validate.py --web out/deck.html
  --open` by default or without `--open` on `/talk --no-open`, stated as the deck's only
  opening path (findings exit 1, unreadable exit 2, never opened), and the `talk_render.py`
  page-count gate is now PowerPoint-only. `talk.md`: `[--no-open]` in the synopsis, defined as
  web-only and answering no opening question; step 3 states it adds no question; step 5's
  page-count gate is PowerPoint-only; a web paragraph requires the lab folder (`--lab-dir`, ask
  for the path, no substitute template) and states render -> validate -> open only if clean.
  `/talk` exposes no `--open` flag. Checks: agent `description:` sha256 identical to HEAD
  (d5ef46bbd7711726); Step 1 two calls / six questions unchanged; no `webbrowser` or other
  browser mechanism in either file; `--lab-dir` in talk_model.py, `--open` gated after
  `check_web` in talk_validate.py, `requires: lab-assets` in the web template; no deferred
  feature, absolute user path, real name or email added; `git diff --check` clean. Mirrors
  intentionally left stale until plan 4 Task 12.
- [x] Task 11 - testing.md, docs/manual/04-skills.md, README.md (2026-10-08). Documentation
  only, no test or source change. `testing.md` (R23): paper2talk script-surface line extended
  for `talk_rules.py` (`KIND_TIER`/`tier_of`, web constants), `talk_model.py` (six kinds and
  `supported-kinds`, footer cap, `--lab-dir` and `requires: lab-assets` with exit 2, figure
  embedding and its refusals, the template context), `talk_pptx.py` (outline layout) and
  `talk_validate.py` (strict `--web` reference check, `--open` only for a clean deck, refusal
  without `--web`); offline block gains measured counts (`test_talk_model.py` 62,
  `test_talk_validate.py` 39, `test_talk_notes.py` 14) and a `test_web_skeleton.py` line (34);
  "thirteen" -> "fourteen" paper2talk suites in the current-inventory paragraph only, the dated
  2026-08-29 "thirteen paper2talk cases" left as it was. `docs/manual/04-skills.md` (R33):
  summary row says PowerPoint on the gabarit via `talk_pptx.py` with pptxgenjs only as the
  no-gabarit fallback (verified in `talk_doctor.py` and SKILL.md) plus the LARI web deck;
  render row adds `--lab-dir`; gates row adds `--web --open` and marks `talk_render.py`
  PowerPoint-only; gabarit bullet names the two web images; new "LARI web deck" bullet
  (identity, six kinds with outline timed as a divider, `--lab-dir` and ask-for-the-path,
  offline output, default validate-then-open, `/talk --no-open`, keys); files list updated and
  "fourteen offline suites, 284 tests" (measured: 14 suites, 284 tests by `Ran`, two of them
  NOT RUN here for missing optional packages; 182 before Issue #53 + 102 added). R33 decisions:
  README.md reviewed and intentionally left unchanged - no existing paper2talk capability
  entry; docs/index.md reviewed and intentionally left unchanged - no existing paper2talk
  capability entry. Checks: every path, script and flag named exists; section anchor unchanged,
  no link added; no deferred feature, absolute user path, real name or email added; `git diff
  --check` clean; no diff in README.md, docs/index.md, paper2talk scripts or assets. The
  `testing.md` mirror is intentionally stale until plan 4 Task 12.

## plan4.md

- [x] Task 12 - mirrors regenerated (2026-10-08). Command: `.\install.ps1 -Profile engineering`
  (no `-Personal`, no `-Manifest`), log ends "Done. Commit the regenerated mirrors.", no error;
  the seven `[STUB]` lines are the known long agents. Mapping: `talk-builder.md` ->
  `.github/agents/talk-builder.agent.md` and `.opencode/agent/talk-builder.md` (the plan's
  `.opencode/agents/` path does not exist); `talk.md` -> `.github/prompts/talk.prompt.md`;
  `testing.md` -> `.github/instructions/testing.instructions.md`; `SKILL.md` ->
  `.agents/skills/paper2talk/SKILL.md` (frontmatter-only, description unchanged so unchanged);
  `renderer-contracts.md`, `docs/manual/04-skills.md`, `progress.md` have no mirror. Of 105
  fingerprinted generator outputs exactly those four changed (+80 / -26), none created. Sync:
  agent mirrors carry the canonical body (one trailing blank line, as at HEAD); the prompt
  applies the documented H1 -> description and `$ARGUMENTS` rewrite, as at HEAD; the
  instructions mirror holds the rule body in its `applyTo` wrapper. A second run changed no
  file (idempotent). Unchanged vs HEAD: `.agents/skills/paper2talk/SKILL.md`, `AGENTS.md`,
  `CONVENTIONS.md`, `.github/copilot-instructions.md`, `.continue/rules/researchtools.md`,
  `.claude/skills/AGENTS.md`, `CLAUDE.template.md`, `.claude/CLAUDE.md`; SKILL `description:`
  sha256 e73780a5cd252d3b as at HEAD; no source, test, README.md or docs/index.md change; no
  untracked file, no `.rt-mirrors.json`; no private data in the mirror diffs; `git diff
  --check` clean.
- [x] Task 13 - full suite, offline render, manual visual check (2026-10-08). Verification
  only, no source, test, template or doc change. Focused paper2talk suites green (talk_model
  62, talk_validate 39, web_skeleton 34, talk_notes 14 and the other eight); talk_pptx and
  to_a4 not runnable here (`pptx`, `pypdf` absent). `run-offline-tests.ps1`: exit 0, 106
  suites, 101 passed, 0 failed, 5 not run (pypdf x3, pyhanko, pptx), `.rt-green.json`
  rewritten. `install.ps1 -Profile engineering` re-run: 0 of 105 outputs changed. Fictitious
  10-slide fixture (all six kinds, PNG and SVG figures, cards, alert, table, matrix) outside
  the repository: render without `--lab-dir` exit 2 and no file; with `--lab-dir` rendered,
  `talk_validate.py --web` clean (no `--open`); 0 external, protocol-relative or relative
  reference, every image a data URI. Offline headless Edge (unresolvable hosts, dead proxy):
  10 screenshots match the gabarit (banner and logo on the title only, #006341, footer on
  slides 2-10, nothing under the footer); interaction probe 57/57 at 1894x940 and 998x628
  (keys, modifier and typing guards, hash clamp, click and its guards, 40 px swipe, vertical
  and multi-touch ignored, help, blackout, F calls requestFullscreen, notes and pacing,
  centred scale); print-to-PDF 10 pages for 10 slides, chrome hidden. `git diff --check`
  clean, nothing staged or untracked, no personal data in the diff. Known: the repository's
  `verify-no-personal-data.ps1` exits 1 on 6 pre-existing substring hits of this machine's
  account name in files this branch does not touch.
- [x] Task 14 - R35 loop run to round 18, clean: security clean from round 4 to 18, the last
  code-review round left two doc items, fixed (see R18 below). Target: `git diff dbe3058` (3 commits plus
  the working tree), `/security-review` and `/code-review` at high effort each round. Classes:
  A fixed (a test failing first where testable), B pre-existing or accepted, C false positive or
  scoped by the approved spec/plan, D excluded. Security: rounds 1-3 found the two issues below,
  rounds 4-16 clean (13 in a row). Who can bypass `--web`/`--open`: no model, figure or flag
  combination; `--open` runs only after a clean check on the same path. Fixes per round (A):
  - R1: a model key (`lab`, `web`, `sections`, `pacing`) overrode computed context; `check_web`
    missed an uppercase or space-prefixed scheme; SVG behind a DOCTYPE/comment refused; header
    `{#-` ignored; footer cap failed Beamer/PPTX models (moved to the web render); outline took
    the PPTX `divider` map entry (`requested_layout`).
  - R2: Beamer outline dropped its blocks; prose/notes `url()` failed the deck; stale footer
    docs. R3: R2 scoping missed multi-line tags (regression, fixed whole-document); swipe also
    fired a click; outline listed backup sections; click behind the open help turned the page.
  - R4: swipe on help/notes; pacing counted the start slide; no-op move started the clock; two
    line counts; null date printed None; outline listed its own section; `--layout-map` help.
    R5: backward-start pacing; `--open` beside `--beamer`; per-char newline loop (2.81 s ->
    0.026 s on 40 MB). R6: pacing after a backward start then forward (`startFirst`); footer
    check out of the gates; null footer title. R7: `url()` in alt/aria-label; non-string asset
    traceback; paper-PDF gate lost; backup slides paced. R8: refusal message cause. R9: `--open`
    could block with no display (R10); blank line in header failed open; docstring. R10: BOM
    header; BROWSER honoured; repeated header key merged; navigation on the black screen;
    doubled tag. R11: R21 test dependency on BROWSER; open once on the final clean pass; help
    text. R12: platform pinned in tests (R21); `--web is missing` test; dead `SLIDE_TIERS`;
    SKILL/agent opening wording. R13: Cygwin guarded; outline refusal wording; inventory.
    R14: comment, SKILL example, talk.md, testing.md wording. R15: `--render --json` stdout
    parseable; module usage; qa-loop gate row; outline layout row; checklist item 7.
    R16: usage line break; R23 inventory line.
  - B/C/D (evidence in the round reviews): pre-existing colour/palette CSS sinks
    (`image-set`, `@import` reachable only there); base `<title>`/`<h2>` None, NOTES|tojson,
    0.68, raw `s.kind`, `--beamer`/`--web` precedence, pptxgenjs fallback ignoring kinds,
    talk_notes .pptx-only (accepted); approved spec: swipe at stage scale, title date not venue,
    no section eyebrow, palette.brand override, asset paths per target; C: srcset/unquoted/
    split attributes, comments, SVG internals, BROWSER blocking opener, hashchange on black,
    empty or non-deck file passing `--web`, perf and simplification items; D: plan4.md
    OpenCode path, README/index unchanged (operator decisions).
  - Operator decisions after R16 (Option 1 both): R16-2 footer keeps the short author, spec
    amended; R16-3 "available to blocks" means defined in the template design system, no
    named-colour syntax. Declined findings recorded in `audit.md`.
  - R17: doc findings in the planning records (audit.md citations, spec colour sentence and
    process section, this entry), fixed. R18: two C (undeclared supported-kinds accept
    `outline`, by design and tested; n / N counts backup slides) and two doc items fixed:
    "per tier" became "by kind, then tier" in SKILL.md and renderer-contracts.md, and the web
    stage size now says 1920 x 1440 for 4:3 or any other `meta.aspect` value, a missing one
    included, as the template computes it.
  - Final verification 2026-11-02: `run-offline-tests.ps1` exit 0, 101 passed, 0 failed, 5 not
    run (pypdf x3, pyhanko, pptx), green stamp rewritten.
  - Tests added: talk_model 62 -> 80, talk_validate 39 -> 52, web_skeleton 34 -> 43, talk_pptx
    21 -> 24 (outline-layout cases run without python-pptx). Paper2talk total 284 -> 327.
  - Verification: every runnable paper2talk suite green; `run-offline-tests.ps1` exit 0, 101
    passed, 0 failed, 5 not run (pypdf x3, pyhanko, pptx), green stamp rewritten; offline headless
    Edge probes 67/67 and pacing 5/5 at 1920x1080 and 1024x768; QA deck `--web` clean; mirrors
    regenerated after each canonical change, final regeneration idempotent; `git diff --check`
    clean; no personal data in the branch diff; nothing staged, nothing untracked; README.md and
    docs/index.md untouched. Per the operator, declines are recorded here, not in `audit.md`.
