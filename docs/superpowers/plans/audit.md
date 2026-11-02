# Audit - Issue #53, paper2talk LARI web deck (R35)

Review target: `git diff dbe3058` (the merge base with `main`): commits `2dd3a20`, `e2f24ef`,
`c8e9af8` and the working tree. Each round ran `/security-review` and `/code-review` at high
effort. A finding is classed A (fixed, with a test that failed on the code before the fix where
the behaviour is testable), B (pre-existing at `dbe3058`, or an item the operator accepted as
out of scope), C (false positive, or settled by the approved spec or plan), or D (excluded from
the MVP by an operator decision). Fixes are listed per round in `progress.md`, Task 14; this
file records every finding that was NOT fixed, with the evidence for leaving it.

## Security review

Rounds 1 to 3 reported two issues, both fixed (class A) in round 1: a model key named `lab`,
`web`, `sections` or `pacing` replaced the value the render computes, and `check_web` missed an
`http(s)` reference written with an uppercase scheme or a leading space. Round 3 found that the
round-2 `url()` scoping missed a tag spread over several lines; fixed in round 3. Rounds 4 to 17
reported no qualifying finding.

Who can bypass the stricter `--web` check or the `--open` gate: no model, figure or flag
combination. `--open` is refused without `--web` or beside `--beamer`, and it runs only after a
clean `check_web` on the same path, through a `file://` URI built from that path.

| Finding | Class | Evidence |
| --- | --- | --- |
| A `url()`, `image-set()` or `@import` placed in an unvalidated colour or palette value (`c.color`, `z.color`, `z.fraction`, `serie.color`, `palette.*`) loads a remote image, and `check_web` does not report every such form | B | The sinks are in the template at `dbe3058` (round 1 and round 9 reviews); the branch reports more of them than the base did, never fewer (round 4 to 5 differential, 132 cases). Recommended follow-up, outside #53: accept only six-digit hex colours and a numeric `fraction` in `validate_model`. |
| An SVG figure whose own content references external fonts or images | C | A figure is embedded only as `<img src="data:...">`; an SVG in an `<img>` runs no script and fetches nothing (rounds 2 and 8). A degraded rendering is caught by the Step 6 inspection. |
| `BROWSER` set by the user to a blocking opener | C | The environment is trusted, `BROWSER` is the standard library's documented choice, and the user chose it (round 11). |
| A deck edited between the check and the open | C | Needs local write access, outside the threat model (rounds 6 and 10). |

## Code review: findings not fixed

| Round | Finding | Class | Evidence |
| --- | --- | --- | --- |
| 1 | Footer cap of 48 characters does not adapt to aspect ratio or audience font size | C | 48 characters is the operator-approved value (spec, Task 0); overflow clipping is an accepted known item. |
| 1 | Templates compare the raw `s.kind` while validation lowercases it | B | Raw comparisons are in both templates at `dbe3058` (web line 122). |
| 1 | `slide_pacing` gives a wrong value on duplicate slide numbers | C | Only on a model `validate_model` already reports as invalid ("appears twice"); rendering such a model is base behaviour. |
| 1 | `check_web` does not scan `srcset`, `@import`, unquoted attributes, `meta refresh` | C | The template emits none of them and autoescape stops a model from creating markup; the check's contract is `src`, `href` and `url()`. |
| 2 | The web title slide shows `meta.date`, not `meta.venue`; no section eyebrow on content slides | C | Approved spec, title slide and frame-title band (spec MVP scope). |
| 2 | Kind variable reused in the `talk_pptx` render loop | C | No slide-level use after the block loop; no misbehaviour. |
| 2 | `requested_layout` tier fallback generality | C | No defect today; outline is the only kind whose tier differs. |
| 2 | Whole data URI lowercased in `check_web`; `_embed_figures` deep-copies the whole model | C | Performance only, bounded by the 10 MiB asset cap. |
| 3 | `NOTES` built with `tojson` fails when a slide has no `notes` key | B | Same expression at `dbe3058` (web line 200). |
| 3 | `0.68` presenter-view literal in `fit()` | B | Same literal at `dbe3058` (web line 209). |
| 3 | `url("a b.png")` and `a[href]` selectors inside `<style>` | B / C | Reachable only through the pre-existing colour sinks or hand-written CSS. |
| 3 | Lowercase `<!doctype` before `<svg>` refused | C | Not valid XML; SVG tools write `<!DOCTYPE`. |
| 3 | A prose `url(https://...)` is reported | B | Whole-line external check behaves as at `dbe3058`. |
| 4 | `src=` with its value on another line | C | The template never emits it; autoescape stops a model from creating attributes. |
| 4 | Template header parsed twice | C | Simplification, no defect. |
| 4 | Performance of the per-reference line count | C | Superseded by the round-4 bisect fix. |
| 5 | Swipe threshold divided by the stage scale on a phone | C | Approved spec: "40 px at stage scale" (spec constants table, line 87). |
| 5 | The web template rendered to a non-`.html` output | C | Escaping by output suffix is base behaviour (`dbe3058` line 477); the output name is a trusted CLI choice; documented commands write `.html`. |
| 5 | The divider draws its title while the outline lists sections | C | Approved spec (outline from the model's sections); divider title drawing is base behaviour. |
| 5 | Counter and progress bar over the notes panel | B | Accepted known item (chrome at the top edge). |
| 6 | `--web` beside `--beamer` without `--open`; positional deck beside `--web` | B | Flag precedence is at `dbe3058`; `--open` beside `--beamer` was fixed in round 5. |
| 6 | `go()` and `show()` both clamp | C | Maintenance only. |
| 7 | pptxgenjs fallback (`deck_skeleton.js`) ignores slide kinds, outline included | B | At `dbe3058` the fallback drew every kind as a title over blocks; the spec names `talk_pptx` as the PowerPoint renderer; `node` is not available to test a change. |
| 7 | A long outline is clipped | B | Accepted known item (overflow clipping). |
| 7 | A model with no slides throws in the deck script | C | `validate_model` already reports "the model declares no slides". |
| 8 | Tags inside HTML comments are scanned | C | Latent only: no template comment carries a style or `url()`, and model text cannot create a comment. |
| 8 | Web target detected by output suffix in three places | C | See round 5; trusted CLI. |
| 9 | Figure paths resolved per target (model folder for web, CWD for PPTX, output folder for Beamer) | C | Web resolution is the approved design; the other two are base behaviour. |
| 9 | Kind normalisation repeated in four places | C | Maintenance only. |
| 9 | README.md has no paper2talk entry | D | Pre-existing omission; the operator decided README.md and docs/index.md stay unchanged. |
| 10 | `alt="x"src=...` with no space before `src` | C | Hand-edited form; the template never emits it and model text cannot create attributes. |
| 11 | Two comments on one header line | C | Documented convention: one declaration per line; the template is trusted. |
| 11 | Hash navigation while the screen is black | C | Deliberate navigation by the presenter, visible on the same screen, recoverable with one key. |
| 12 | `NAV_KEYS` repeats the navigation key list | C | Maintenance only. |
| 12 | plan4.md names `.opencode/agents/` | D | Operator decision: do not edit plan4.md for its historical path. |
| 12 | Declined findings not in `audit.md` | Resolved | This file. |
| 14 | `<title>` and the slide `<h2>` print a null title | B | Same expressions at `dbe3058` (web lines 6 and 130). |
| 14 | The CASE example palette turns a web deck olive | C | `palette.brand` overriding the lab green is the approved, documented design. |
| 15 | The `talk_notes.py` gate reads only a `.pptx` | B | Accepted cross-target limitation; the gate wording predates the branch. |
| 16 | `--web` reports an empty or non-HTML file clean | C | `check_web` is a self-containment check; a stale or truncated deck is caught by the Step 6 inspection. |
| 16 | Footer shows the short author without the institute (spec MVP scope, original wording "author (institute)") | Resolved | Operator decision: spec amended to the approved plan2 behaviour; footer unchanged. |
| 16 | Gabarit secondary, accent and risk colours not selectable by name from a block (spec MVP scope, "available to blocks") | Resolved | Operator decision: spec clarified, "available" means defined in the template's design system; no named-colour syntax. |
| 16 | `_footer_problems` has one caller behind a public wrapper | C | Simplification, no defect. |

## Verdict

Clean. Round 17, the final round after the operator's round-16 decisions, returned no security
finding and no code defect; its six findings were all in the planning records themselves (this
file's spec citations, the spec's colour sentence and process section, and the Task 14 entry of
`progress.md`), and were corrected. Round 18 re-ran both reviews on the corrected branch; its
result is recorded in `progress.md`, Task 14.

This file is gitignored with the rest of `docs/superpowers/` and must be force-added
(`git add -f`) with the final commit, as the other planning files were.
