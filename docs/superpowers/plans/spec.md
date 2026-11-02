# Spec - paper2talk web deck: LARI lab identity and offline interactions (MVP)

Issue: LARi-UQAC/ResearchTools#53. Branch: `feat/paper2talk-web-lari`.
Plans: `plan1.md` (offline and model), `plan2.md` (web template), `plan3.md` (docs),
`plan4.md` (mirrors, verification, R35 gate). Tracking: `progress.md`.

## Goal

The web target of `paper2talk` produces a single, offline, self-contained HTML deck that
carries the LARI/UQAC presentation identity of the canonical Beamer gabarit, with light
keyboard, pointer and accessibility interactions. Requested by the lab director (Issue #53).

## Decisions already taken (do not reopen)

1. Extend `paper2talk` and `talk-builder`. No new skill, agent, command or pipeline.
2. Visual source of truth: the canonical gabarit `gabarit_these_maitrise_DSA_UQAC/src/slides/main.tex`
   as it renders when compiled (Madrid theme, `uqacgreen` = `#006341`). Reference pages of that
   compilation: 1 title, 2 outline, 3 and 6 blocks, 5 figure, 9 text content, 12 table,
   15 diagram and table, 21 closing, 22 backup.
3. The LARI logo appears on the title slide only. No logo on content slides, matching the
   rendered reference.
4. The missing PowerPoint gabarits (`Gabarit169.pptx`, `Gabarit43.pptx`) do not block this work.
5. No CDN, Tailwind, web font, Node runtime, npm build or external runtime dependency.
6. No WebSlides, Marp, Marpit or Reveal.js code is copied. Ideas from the read-only study are
   re-expressed in our own code.
7. Beamer-sample defects are not reproduced: clipped footer text, content under the footer,
   overlapping navigation icons, overlapping matrix labels.

## Resolved conflicts with the repository

- a. Opening the browser lives in `talk_validate.py --web <deck> --open`, not in
  `talk_render.py`, which is PowerPoint-only. `/talk` and `talk-builder` pass `--open` by
  default; `/talk --no-open` is the opt-out. Tests never open a browser.
- b. `talk_notes.py` derives its tier set from `talk_rules` instead of hard-coding it.
- c. Outline cadence: `outline` is a presentation kind whose budget tier is `divider`. A single
  map `KIND_TIER` in `talk_rules.py` resolves kind to tier. The 1/3-minute value stays only in
  `TIER_MINUTES`; no second timing value exists anywhere.
- d. Outline content is rendered from the model's own `section` values in all three
  renderers. Beamer `\tableofcontents` is not used, since the skeleton emits no `\section`.
- e. The visual comparison against the Beamer reference is a manual browser check with the
  network off. No browser automation dependency is added.
- h. Lab assets are required only by a template that declares `requires: lab-assets` in its
  header. Beamer and PowerPoint flows keep working without the new flag.
- i. Presenter pacing uses `budget_rows()` per-slide `seconds` (spoken estimate of the notes).

## MVP scope

**Lab identity (web template).** Default brand `#006341`; the gabarit's `secondary`,
`accent1-3` and risk colours available to blocks, meaning defined in the template's design
system as named CSS colours. Block colour fields keep their existing forms (chips and zone
bands a hex value, a chart series any CSS colour, as at the base), and the model gains no
named-colour syntax (operator decision, R35 round 16). Layouts per kind: `title`, `outline`,
`content` (text, figure, table), `divider`, `thanks`, `backup`. Title slide: UQAC banner,
rounded green title box with subtitle, authors, institute, fixed `meta.date`, LARI logo.
Other slides: full-width green frame-title band, sans-serif type, green and red alert blocks.
Footer on every non-title slide: author, title, date, `n / N`, built from
`meta.short_author` and `meta.short_title` when present. The author field is the short author
alone, with no institute, as plan2 approved (operator decision, R35 round 16).

**Offline.** Every figure and both lab images embedded as `data:` URIs. A missing asset, an
asset resolving outside its root (R24), an unrecognised image type or an oversized file is a
refusal. `talk_validate.py --web` flags relative `src`, `href` and `url()` references, not
only `http(s)`.

**Interactions and accessibility.** Typing and modifier-key guard; `n / N` counter and
progress indicator; URL-hash deep link restored on load; fullscreen key; blackout key; click
and touch-swipe navigation with a threshold and a multi-touch guard; `?` help overlay;
`aria-live` slide announcement; reduced-motion respected; print hides interaction chrome and
keeps the footer.

**Delivery.** The deck opens in the browser only after a clean `--web` check, and only with
`--open`.

## Deferred (out of scope)

Project-folder input; project-overview profile; thesis-defence profile; `local-writer`
project memory; step-by-step reveals; overview mode and jump-to-slide; separate presenter
window; SVG equation rendering; automatic overflow measurement or shrinking; logo
downscaling.

## Values confirmed by the operator (R0, R4)

Confirmed on 2026-10-08 (plan1 Task 0). Each is recorded in `talk_rules.py` with this
provenance: chosen by the operator.

| Constant | Confirmed value | Origin of the proposal |
|---|---|---|
| swipe threshold | 40 px at stage scale | Reveal.js `SWIPE_THRESHOLD` (study, commit e240e17) |
| maximum embedded asset size | 10 MiB per file | operator choice |
| footer field cap | 48 characters per field | operator choice |
| lab asset filenames | `en-tete1260.jpg` (banner), `LogoLARI_FINAL.png` (logo) | the canonical gabarit folder |

Execution method: native, sequential.

## Constraints that bind every plan

- TDD: every behaviour starts as a failing test, each suite asserts a failure path (R20).
- Fixtures use fictitious identities only: no real person, email, account name or machine
  path (R34). Image fixtures are generated inside the tests; no lab asset is copied into the
  repository.
- No hard-coded path, numeric threshold or identifier outside `talk_rules.py` (R0, R1, R2).
- Plans describe intent, interfaces and tests, never code to transcribe (R29).
- A state-changing CLI path refuses with exit 2 and names what is missing (R8, R12).
- `.\scripts\test\run-offline-tests.ps1` stays green.
- The R35 security and code review loop is the last task before the pull request.

## Acceptance criteria

- A fixture deck rendered with the lab folder matches the reference pages by slide type, in a
  manual browser check with the network off.
- The logo appears on the title slide only; none of the four Beamer defects appears.
- A deck with figures passes `talk_validate.py --web` offline and holds no `http(s)` and no
  relative file reference.
- A web render without the lab folder exits 2 naming what is missing.
- `outline` is accepted, budgeted as a divider, and drawn by the web, Beamer and PowerPoint
  renderers; a template that cannot draw it fails loudly.
- The browser opens only for a clean deck and only with `--open`.
- Fixtures carry fictitious identities only (R34).
- The full offline suite passes; docs are updated in the same PR (R23, R31, R33).
- The R35 loop returns clean, and the PR body records each review round and its fixes.

## Process decisions

- `docs/superpowers/` is gitignored; the planning files are committed with `git add -f`, as
  `2dd3a20` did for this spec, the plans and `progress.md`. `audit.md` is force-added the same
  way with the final commit.
- The privacy git hooks (`install-git-hooks.ps1`, Betterleaks) were installed with operator
  approval before the first commit, through the global `core.hooksPath`.
