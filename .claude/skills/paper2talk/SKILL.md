---
name: paper2talk
description: "Turn an accepted paper into a conference talk: slides on the lab gabarit plus timed speaker notes, in PowerPoint, LaTeX Beamer, or a self-contained web deck. Use when the user asks to build a presentation, a deck, slides, or a talk from a paper or an article; for /talk; for 'prepare the presentation for <conference>', 'my paper was accepted, I need the slides', 'speaker notes', 'presentation from this accepted paper', 'passer de l article a la presentation'. Asks the six questions that set the rules before reading the paper (audience, duration, output target, aspect ratio, PDF format, how the deck ends), then builds one deck model and renders it, measures the spoken budget at 130 wpm, and gates on a visual QA loop. Delegates the build-render-inspect-fix loop to the talk-builder agent. Does NOT cover posters, and does not cover the submission package (that is cover-paper)."
allowed-tools: [Read, Write, Edit, Bash, Skill, AskUserQuestion]
permissions: [read, write]
---

# paper2talk - accepted paper to conference talk

The repo takes a paper to submission (`submit-checker`, `cover-paper`) and stops. The talk is
the next deliverable of every accepted paper. This skill covers that step: the deck, the
figures at projector resolution, the timed speaker notes, and the printable PDF.

Posters are out of scope, and so is the submission package.

## 1. Opening questions - ask first, always

Before reading the paper, before touching a template, before naming an output file. There
are **six**, and `AskUserQuestion` caps a call at four, so this is **two consecutive calls,
the agent's first two actions**. Nothing downstream can be chosen without the answers: each
one changes the rule set, the geometry, the renderer, or the word budget.

Call 1 - the four that set the rules and the geometry:

| # | Question | Header | Options |
| --- | --- | --- | --- |
| 1 | Target audience | `Public` | scientists in the field (professors, researchers, students) / academics outside the field / general public and media |
| 2 | Talk duration and target conference | `Duree` | e.g. 12-13 min for IEEE CASE; a per-section split if the professor has one |
| 3 | Output target | `Cible` | LaTeX Beamer on the lab gabarit / PowerPoint on the lab gabarit / interactive web |
| 4 | Slide aspect ratio | `Ratio` | `16:9` widescreen (13.33 x 7.5 in, the lab Beamer gabarit's `aspectratio=169`) / `4:3` (10 x 7.5 in) / `9:16` vertical |

Call 2 - immediately after:

| # | Question | Header | Options |
| --- | --- | --- | --- |
| 5 | PDF output format | `PDF` | slide-size (projector) / `A4` / `Letter`, plus orientation and whether a printable handout is wanted |
| 6 | How the deck ends | `Fin` | conclusions last, contact and DOI folded into it, no thank-you slide / conclusions, then a thank-you slide, then references |

**What each answer computes.** These are not preferences collected for politeness. Every one
is an input to a number the build cannot invent.

| Answer | Determines |
| --- | --- |
| **Duration** (Q2) | `n_content` through the three-tier formula of section 4; the word budget `(minutes - 1.5) x 130`; the per-section split; therefore how much of the paper survives the cut |
| **Audience** (Q1) | the body font floor (16 / 16 / 20 pt); whether equations are kept, halved or replaced by prose; jargon policy; citation density; the preferred-form ranking of section 5 - and, through the font floor, how much text physically fits, which feeds back into `n_content` |
| **Output target** (Q3) | which renderer runs (`talk_pptx.py` on the gabarit, `beamer_skeleton.tex.j2`, `web_skeleton.html.j2`); which gabarit is read; whether LaTeX equations are available at all; the QA loop (PowerPoint COM, `latexmk`, or headless Chromium) |
| **Aspect ratio** (Q4) | the canvas in inches; the content band under the banner; the column grid; whether the master background can be reused or a new asset is required (`9:16` needs one) |
| **PDF format** (Q5) | the `talk_render.py --paper` reflow and whether a handout is produced; never the slide size itself |
| **Deck ending** (Q6) | whether a thank-you slide exists, which costs 0.5 min of chrome and therefore one content slide near the boundary |

Two of these interact and the skill says so out loud: a **larger font floor** (public
audience) fits less text per slide, which pushes content onto more slides, which the
**duration** then caps. When they collide the duration wins and the content is cut, never the
font floor, because an unreadable slide is worse than a missing one.

### Echo a build contract before writing any slide

Once the answers are in, compute the contract and show it. A misunderstanding caught here
costs a message; caught after twelve slides exist it costs the whole build.

```bash
python .claude/skills/paper2talk/scripts/talk_rules.py   # import-only module; see below
```

```python
from talk_rules import build_contract, format_contract
print(format_contract(build_contract("field", 13, "pptx", "4:3", "a4",
                                     n_title=1, n_thanks=0, n_dividers=0)))
```

```text
audience field | 13 min | pptx | 4:3 | a4
  -> n_content   = 12  (title 1, thanks 0, dividers 0, backup 0; total 13)
  -> words       = 1495 aimed (11.5 min at 130 wpm), 1690 is the raw slot
  -> font floor  = 16 pt body, 14 pt captions and references
  -> form        = figure > table > equation > prose; equations: allowed in quantity ...
```

### Rules for asking

- **Question 1 first**, because it parameterises every typography and density rule in
  section 8. Answer it wrong and the whole deck is built to the wrong standard.
- **Recommend, do not decide.** Put the recommended option first and label it. For a
  conference projector that is `16:9`; the CASE 2026 deck stayed `4:3` only because the
  professor chose to keep the existing gabarit.
- **`9:16` is portrait**, not a typo for `16:9`. It is 7.5 x 13.33 in and belongs to a
  vertical screen or a lobby display. Offer it, say plainly what it is, and warn that a 4:3
  master background cannot be reflowed into it: a portrait build needs its own asset.
- **Question 5 is independent of question 4.** A 4:3 deck can produce an A4 PDF and a 16:9
  deck a slide-size one. The reflow happens after rendering, never by changing the slide size
  (`talk_render.py --paper`, which delegates to `to_a4.py`).
- **On question 2, if only a total duration comes back**, apply the default split 20 / 8 /
  20 / 32 / 20 percent across introduction, objective, methodology, results, conclusion,
  state the resulting word budget and slide count out loud, and proceed. Do not ask twice.
- **If the answers to 1 and 3 conflict, say so before building.** An equation-dense talk to
  scientists in the field is where PowerPoint is the weak target: it has no LaTeX, so a slide
  carrying seven or eight numbered equations has to be dropped in as exported images or set as
  plain text. Recommend Beamer for that combination and let the professor override.
- **Do not ask anything else in those two calls.** Rebuild-versus-edit is not a professor
  decision once the target is known: all three targets are builds. The PowerPoint build is not
  a re-creation, though - `talk_pptx.py` opens the lab gabarit and adds slides from ITS
  layouts, so the branding is used rather than imitated.
- Notes language, figure questions, whether the deck will also be read afterwards, and the
  optional style preview belong to a **third, later** call, once the paper has been read.

## 2. Preflight and inputs

Run the preflight once, before anything else, so a missing toolchain is a message rather than
a discovery halfway through a build:

```bash
python .claude/skills/paper2talk/scripts/talk_doctor.py --target pptx
```

It reports, per dependency, whether it is present, which target it serves, and what degrades
without it. It installs nothing.

Then read the paper into an inventory rather than by eye:

```bash
python .claude/skills/paper2talk/scripts/paper_extract.py main.tex --out inventory.json
```

**LaTeX source is the preferred input, by a wide margin.** `paper_extract.py` flattens every
`\input`, `\include` and `\subfile` (three levels deep, circular includes terminate), then
lists the sections with their word counts, the figures and tables with their labels, captions
and asset paths, the numbered equations, the citation keys, and **every number the paper
states**. A chapter that is never opened is a results section that never reaches the deck,
which is exactly what a hand-read of a multi-file thesis misses.

A `.pdf` is best effort and says so: two-column layout, maths and tables extract unreliably.
Two cases are refused rather than half-read, because both produce plausible rubbish - an
encrypted file, and a scan with no text layer (OCR it, or find the source).

The extraction reports itself when it looks too thin to trust (under 500 words, under three
sections). Treat that as a broken `\input` path until proven otherwise.

Also gathered: the gabarit for the chosen target (section 3) and the figure inventory - vector
sources, never the paper's `.png` exports.

## 3. The gabarits, and the brand contract

All lab gabarits live in `../gabarit_these_maitrise_DSA_UQAC/src/slides/`, relative to this
repository (workspace-relative: `gabarit_these_maitrise_DSA_UQAC/src/slides/`). Paths in this
skill are always relative - the workspace root differs from machine to machine.

| Aspect answer (Q4) | File | Canvas | Layouts |
| --- | --- | --- | --- |
| `16:9` | `Gabarit169.pptx` | 10 x 5.625 in | 18 named (`1- Titre` … `8- Titre`, `Programme`, `Page separatrice`, `Vide`, `1- Contenu` … `6- Contenu`, `Fin`) |
| `4:3` | `Gabarit43.pptx` | 10 x 7.5 in | 11 standard, brand carried by the master background |
| Beamer | `main.tex` in the same folder | `aspectratio=169` | see `references/renderer-contracts.md` |

**`Gabarit43.ppt` is legacy binary** (OLE compound document), which no Python OOXML reader
opens. `Gabarit43.pptx` is the converted copy beside it; the original is left untouched. If a
future gabarit arrives in the old format, `talk_template.py` says so and
`talk_template.py <file.ppt> --convert` writes the `.pptx` through PowerPoint COM.

**Which gabarit for a paper deliverable.** The 4:3 file is the one to reach for when the
professor asks for an A4 handout: 4:3 fills an A4 sheet with far less white than 16:9. A
projector still wants 16:9. Question 5 does not change the slide size either way - the reflow
happens on the PDF (`talk_render.py --paper`).

Read the contract before generating anything, and never re-create branding by eye:

```bash
python .claude/skills/paper2talk/scripts/talk_template.py \
       ../gabarit_these_maitrise_DSA_UQAC/src/slides/Gabarit169.pptx \
       --out brand.json --extract-media assets/
python .claude/skills/paper2talk/scripts/talk_pptx.py --list-layouts \
       --template ../gabarit_these_maitrise_DSA_UQAC/src/slides/Gabarit169.pptx
```

`talk_template.py` emits the canvas, the layouts, the master background, and every picture and
text box of the sample slides in inches, with `srcRect` already converted to a keep-fraction.

**The PowerPoint deck is built ON the gabarit, not in its image.** `talk_pptx.py` opens the
gabarit with python-pptx, drops the sample slides the file ships (six of them in the 16:9), and
adds each slide on the layout its tier selects, filling the real placeholders. The content band
comes from the layout's own body placeholder, so the lab's clearance around the banner and the
wordmark is respected without a single hardcoded number. `assets/deck_skeleton.js` (pptxgenjs)
remains the fallback for a deck with **no** gabarit at all, since pptxgenjs cannot read another
file's layouts.

Full renderer contracts, layout mapping, and the two-greens problem:
`references/renderer-contracts.md`.

## 4. Slide budget - one slide per minute, three chrome tiers

Professor's rule, 2026-08-11. The cadence counts **content** slides. Chrome is not one price:
a section transition is far cheaper than a title slide, so **a 13-minute talk is not 13
slides**.

| Tier | Cost | What it is |
| --- | --- | --- |
| Content | 60 s | anything the speaker argues from |
| Title, thank-you | 20-30 s, budget 0.5 min | opening and closing chrome |
| Section divider | under 20 s, budget 0.33 min | a section name, traversed almost without stopping |
| References, appendix, backup | 0 | never traversed inside the slot |

```text
n_content = floor(minutes - 0.5 * (title + thanks) - 0.33 * n_dividers)
n_total   = n_content + title + thanks + n_dividers + n_backup
```

Worked at 13 minutes, and the difference is the point:

| Deck shape | Arithmetic | Content | Total |
| --- | --- | --- | --- |
| No dividers (title + thanks + refs) | `13 - 1.0` | 12 | **15** |
| Five section dividers | `13 - 1.0 - 5 x 0.33` | 10 | **18** |

The divider-bearing deck runs *fewer* content slides and *more* slides overall. Both are
legal; the choice is rhetorical. `talk_notes.py` reports the cadence next to the word count as
a **warning, not a gate**: a dense technical deck may legitimately run faster than a minute a
slide, and the professor should see the number rather than discover it in the room.

## 5. Content hierarchy - a picture is worth a thousand words

Professor's rule, 2026-08-11. This outranks every layout preference below it. When the same
point can be made in more than one form, choose in this order and stop at the first that
works:

```text
figure  >  table  >  equation  >  prose
```

Prose is the **last** resort, and that includes bullets: a bulleted list is prose with
markers. An equation is preferred over the sentence describing it, because in an in-field
talk the equation *is* the precise statement and the sentence is a lossy paraphrase. That is
why the audience table allows seven or eight equations on one slide: they are not a density
problem, they are the preferred form.

Two consequences the skill enforces rather than recommends:

- **No text-only content slide.** A content slide with neither figure, table, equation,
  native chart nor quantity-bearing diagram is a defect. Cards, chips and bullets do not
  count - they are prose in boxes. `talk_validate.py` counts them and names the offenders.
- **Say what you show.** Everything on a slide is discussed in that slide's own speaker
  notes, and nothing sits on a slide the speaker never addresses. `talk_notes.py` checks it
  against the per-exhibit keywords in `talk_model.json`, matching subjects and never
  filenames. This is why the notes and the slide are authored together, not in two passes.

## 6. Content rules

Adopted from `github.com/Gabberflast/academic-pptx-skill`, re-expressed here; see
`docs/superpowers/notes/2026-08-11-reference-skill-harvest.md` for what was rejected and why.

- **Action titles.** Every title is a claim, not a topic label: "Six models reach 95.2 %, one
  of them is usable", never "Classification results".
- **The ghost-deck test.** Reading only the titles, in order, must tell the whole argument.
  Run it before rendering.
- **One exhibit per results slide**, annotated directly on the exhibit.
- **A conclusions slide, not a bare thank-you.** Keep the takeaway visible during questions;
  the open-data DOI belongs there.
- **Every borrowed figure carries its citation**, and rebuilt figures beat screenshots of the
  paper.
- **Every number carries its comparison.** "95.2 %" states nothing on its own; "95.2 % against
  a 25.6 % baseline" is a result. A number with no reference point is a number the audience
  cannot judge.
- **The narrative spine is Situation, Complication, Resolution.** Where the field stands; what
  gap or contradiction breaks it; what this work contributes. The default outline shape
  (1-2 / 1 / 1-2 / n / 1-2 / 1 slides per phase) is that spine, and a deck whose titles do not
  traverse it in order will not survive the ghost-deck test either.
- **Prepare the questions.** A backup-tier slide carrying three to five anticipated questions
  with a two-sentence answer each costs nothing in the slot (backup slides are never
  traversed) and is the difference between a fluent answer and a scramble. Draw them from the
  five that always come: why this method rather than that one, how do you know the gain is not
  confounded, does it scale, how does it compare to the recent work, and what would you do
  differently.

## 7. Number integrity

Never put a number on a slide that is not in the paper. When the paper contradicts itself, do
not silently pick one: build the slide on the value the results section validates, and report
the contradiction to the professor.

This one is mechanical rather than a matter of care:

```bash
python .claude/skills/paper2talk/scripts/talk_model.py talk_model.json \
       --check-numbers inventory.json
```

Every number on every slide is compared against the numbers the paper states, on normalised
values - "1 950", "1950", and "95,2" against "95.2", all compare equal, so a French manuscript
and an English slide raise no false alarm. Bare small integers (up to twelve) are not treated
as claims. Whatever is left is a number that entered the deck from nowhere. The CASE paper had three (seven algorithms in the
abstract against thirty-two in the results; `Sp` about 941 mm in the methodology against 960
mm in the results; `k` up to 10 against up to 8).

## 8. Design system, parameterised by the audience

Constant across audiences: one dominant brand colour, a semantic triad reused as the deck's
motif, cards with a subtle tint and shadow, never an accent stripe or an underline below a
title, never a text-only slide. Titles Cambria, body Calibri - both ship with Office and
render true-to-width in the QA renderer, which Aptos does not. Labels follow
`.claude/rules/code-style.md`.

What the audience changes (professor's calibration, 2026-08-11):

| | Scientists in the field | Academics outside the field | General public and media |
| --- | --- | --- | --- |
| **Body text floor** | **16 pt**, 14 pt for references and captions | 16 to 18 pt | 20 pt |
| **Text volume** | no bullet cap; the gate is legibility and overflow, and prose is the last resort | ~5 bullets, prefer a figure | ~40 words, 3 to 5 bullets |
| **Equations** | allowed in quantity; 7 to 8 on one slide is legitimate when each is labelled and cited | one or two, also stated in words | none; state the mechanism in words |
| **Jargon** | field terms used directly | expanded on first use | avoided or replaced |
| **Method detail** | full, including parameter values | the shape of the method | the intuition only |
| **Citation density** | every borrowed figure and claim | on figures | source line only |
| **Cadence** | may exceed one slide per minute when equation-dense | one per minute | slower |
| **Word budget** | 130 words per content slide | 130 | 110 to 120 |

The rule this encodes: **the 20 pt floor and the 3-to-5-bullet cap are executive and marketing
conventions**, not scientific ones, and they apply to the general-public column only. For an
in-field talk they force out exactly the detail the audience came for. The legibility gate
that replaces the cap is mechanical: nothing below the floor, no text overflowing its shape,
no overlap, no scroll - and `talk_validate.py --audience` measures it.

## 9. Speaker notes

Every target carries them, and never as a text box on the slide: the PowerPoint notes pane via
`addNotes`, Beamer `\note{}` with `\setbeameroption{show notes on second screen=right}`, and an
`<aside class="notes">` in the web target. English by default for an international conference,
French only if the professor asks.

The budget is **`(minutes - 1.5) x 130` words**, at the 130 wpm technical-talk rate - never
150, which is conversational speech and silently buys the deck two minutes it does not have.
Per slide: 130 words of content, 65 for a title or thank-you, 43 for a divider.

Write them to this template. The labels are scaffolding for the speaker and `talk_notes.py`
strips them before counting, so the structure costs nothing against the budget:

```text
WHAT TO SAY:            two or three sentences, in the words you will actually use
KEY POINT:              the one thing that must land
TIMING:                 the seconds this slide owns
TRANSITION:             the sentence that carries you to the next slide
ANTICIPATED QUESTIONS:  what this slide invites, and the short answer
```

**Deck language and figure-label language are separate choices.** A French talk keeps its
figure axes, variable names and units in English, which is what the audience of a scientific
figure expects; references stay in their original language. State both in `meta`
(`notes_lang`, `figure_lang`) rather than assuming they match.

```bash
python .claude/skills/paper2talk/scripts/talk_notes.py deck.pptx --minutes 13 \
       --model talk_model.json --tolerance 5
```

Iterate until every section is within 5 %. Aim under the slot, not at it.

## 10. QA gate - not optional, and it is a loop

```bash
python .claude/skills/paper2talk/scripts/talk_validate.py deck.pptx --original gabarit.pptx \
       --audience field --model talk_model.json
python .claude/skills/paper2talk/scripts/talk_render.py deck.pptx --dpi 100 --paper a4
```

`talk_validate.py` also reports what a reading pass misses: **shapes that overlap** (a caption
under a logo, a heading colliding with the row beneath it - the two most frequent defects of
the origin session), a deck over 50 MB, and a **semantic triad too close in lightness** to
survive colour blindness or a washed-out projector.

Then look at **every** page. Ship only on a clean pass. The backends, the defects that
actually occurred, and the per-target gates are in `references/qa-loop.md`.

**Leave the working parts beside the deck**, not the deck alone: the figure PNGs (so one
figure can be re-exported without re-running the build), `talk_model.json`, the QA page
images, and a short run log naming what succeeded, what fell back and what was skipped. A deck
whose provenance is gone is a deck nobody can revise six months later.

## 11. Scripts

| Script | Job |
| --- | --- |
| `scripts/talk_doctor.py` | preflight: which targets this machine can build, and what degrades without each missing tool |
| `scripts/paper_extract.py` | read the paper: `\input` flattening, sections, floats, equations, citations, and the number inventory the deck is checked against |
| `scripts/talk_rules.py` | audience profiles, tier costs, cadence formula, word budget, build contract (import-only) |
| `scripts/talk_model.py` | the deck as data: block vocabulary, validation, budget aggregation, Jinja rendering for the Beamer and web targets |
| `scripts/talk_template.py` | read a template `.pptx`, emit the brand contract as JSON, extract media |
| `scripts/fig_export.py` | re-export a figure through the draw.io CLI at scale 3, with `--fix-text` label repair into a copy |
| `scripts/talk_render.py` | deck to PDF (soffice, else PowerPoint COM) to page images, page-count gate, `--paper` reflow |
| `scripts/talk_notes.py` | spoken budget, per-slide and per-section drift, cadence block, exhibit coverage |
| `scripts/to_a4.py` | reflow a slide-sized PDF onto A4 or Letter, with `--handout 2\|4\|6` |
| `scripts/talk_validate.py` | package checks (plugin validator, located not hardcoded), legibility gate, text-only-slide check, web self-containment |
| `scripts/talk_pptx.py` | **the PowerPoint renderer**: opens the lab gabarit, drops its sample slides, adds each slide on one of its own layouts, fills the placeholders, writes the notes pane |
| `assets/deck_skeleton.js` | pptxgenjs fallback for a deck with no gabarit; carries the design system as functions |
| `assets/beamer_skeleton.tex.j2` | Beamer renderer on the canonical lab gabarit |
| `assets/web_skeleton.html.j2` | one self-contained HTML file, fixed stage, presenter notes, print path |

Dependencies: `scripts/requirements.txt` (pypdf, python-pptx, defusedxml, jinja2), optional
`pymupdf` for PDF input (already a dependency of `extract-statistic`), plus Poppler
and PowerPoint or LibreOffice for the render loop, and pptxgenjs (npm) only for the
no-gabarit fallback.

## 12. Out of scope

Posters. The submission package - that is `cover-paper`. Beamer is **in** scope as an output
target, but the LaTeX prose itself still follows `.claude/rules/` and the `scientific-writing`
skill; when a Beamer build needs authored scientific prose rather than slide fragments, hand
that part to `latex-writer`.

## Prior art

Two MIT-licensed skills were read in full and re-expressed, never copied:

- `github.com/Gabberflast/academic-pptx-skill` (MIT, Gabberflast 2026) - content and
  structure rules. Its frontmatter claims a proprietary licence pointing at a `LICENSE.txt`
  that does not exist in the repository; the file that does exist is MIT. Because that
  contradiction is unresolved upstream, every rule taken from it is re-expressed in our own
  words and the repository is cited.
- `github.com/zarazhangrui/frontend-slides` (MIT, Zara Zhang 2025) - the web target's fixed
  stage, the slide-switching constraint, the `@media print` PDF path, and the preview
  authenticity rules.

- `github.com/PHY041/claude-skill-academic-ppt` - its README states MIT but the repository
  ships no `LICENSE` file, so, as above, its rules are re-expressed and cited rather than
  copied. Taken from it: the dependency preflight with a per-tool degradation statement, the
  LaTeX `\input` flattening and the extraction-sanity check, the number cross-reference
  against the source, the structured speaker-notes template, the Q&A preparation slide, the
  Situation-Complication-Resolution spine, the "every number carries its comparison" rule, the
  shape-overlap check, and the discipline of saving the working parts beside the deck.

Full harvest, licence findings, and the conflicts with the professor's decision on each:
`docs/superpowers/notes/2026-08-11-reference-skill-harvest.md`.

## See also

- Agent: `.claude/agents/talk-builder.md` - runs the build-render-inspect-fix loop
- Command: `.claude/commands/talk.md` - `/talk <paper>`; a flag pre-answers its question
- `references/renderer-contracts.md` - the deck model, the three renderers, the gabarits
- `references/qa-loop.md` - render backends, footguns, the inspection checklist
