# One deck model, three renderers

The skill is not a PowerPoint generator with two bolted-on exports. The deck is built **once**
as data and rendered from there; otherwise the action titles, the numbers and the speaker
notes get written three times and drift three ways.

## `talk_model.json`

Produced from the paper and reviewed before any rendering.

```json
{
  "meta": { "title": "...", "authors": ["..."], "venue": "IEEE CASE 2026",
            "audience": "field", "aspect": "16:9", "minutes": 13,
            "notes_lang": "en", "ending": "conclusions-last" },
  "budget": { "1 Introduction": { "slides": [1, 5], "target_words": 375 } },
  "palette": { "brand": "5A7210", "ink": "23262A", "s1": "2E7D32",
               "s2": "C57A00", "s3": "B3221F" },
  "slides": [
    { "n": 3, "kind": "content", "section": "Introduction", "num": 1,
      "title": "Battery disassembly is a shared, hazardous cell",
      "blocks": [
        { "kind": "bullets", "items": ["..."] },
        { "kind": "figure", "asset": "fig1_station.png",
          "caption": "Fig. 1  ...", "cite": "[3, 18]",
          "keywords": ["station", "cell", "disassembly"] },
        { "kind": "takeaway", "text": "..." }
      ],
      "notes": "..." }
  ]
}
```

Two fields are load-bearing and easy to omit:

- **`kind` on the slide** is what the slide is, and through it what it costs. Six kinds exist:
  `title`, `outline`, `content`, `divider`, `thanks`, `backup`. Five of them are also the
  chrome tiers of `talk_rules.TIER_MINUTES`; `outline` is drawn as its own layout but timed as
  a divider, through `talk_rules.KIND_TIER = {"outline": "divider"}`, and `talk_rules.tier_of`
  resolves any kind to its tier (an unknown kind raises). The divider's cost therefore exists
  once, and an outline has no cost of its own. The kind is declared, never inferred from
  position: a deck reordered by hand keeps its declarations and loses its positions.
  `talk_notes.py --model` reads the tiers from here, through `tier_of`, instead of taking four
  command-line lists.
- **`keywords` on an exhibit** is what the say-what-you-show check matches on. A figure named
  `fig5_evolution.png` is covered when the notes mention its subject (`blink`, `interval`,
  `axis`), because no speaker reads a filename out loud. An exhibit with no keywords is
  reported as uncheckable rather than passed silently.

## Block kinds

The set the CASE 2026 deck actually needed, plus `equation`. Every renderer implements all of
them or **fails loudly** on the one it cannot draw. A silently dropped block is a hole in the
argument that nobody sees until the room does; `talk_model.assert_renderable` raises instead.

| Kind | Required fields | Counts as an exhibit |
| --- | --- | --- |
| `bullets` | `items` | no - prose with markers |
| `figure` | `asset` (+ `caption`, `cite`, `keywords`) | yes |
| `takeaway` | `text` (+ `support`) | no |
| `cards` | `items` (`title`, `text`) | no - prose in boxes |
| `chips` | `items` (`label`, `color`, `glyph`) | no |
| `stats` | `items` (`value`, `label`) | no |
| `table` | `rows` (first row is the header) | yes |
| `matrix` | `rows` of numbers in 0..1 | yes - it encodes a quantity |
| `zoneband` | `zones` (`fraction`, `label`, `color`) | yes - a scaled axis |
| `chart` | `series` | yes |
| `equation` | `tex` (+ `label`, `where`, `image`, `runs`) | yes |

A Jinja renderer declares what it implements in its header, the run of comment lines at the
top of the file (`{# ... #}` in HTML, `((# ... #))` in LaTeX), which is what
`talk_model.py --render` checks before writing anything. Blank lines, a byte-order mark and
Jinja's `-` whitespace control are allowed in it, and a key repeated on another line adds to
the first. The web template's header:

```jinja
{# supported-blocks: bullets figure takeaway cards chips stats table matrix zoneband chart equation #}
{# supported-kinds: title outline content divider thanks backup #}
{# requires: lab-assets #}
```

- `supported-blocks`: a block outside the list raises `RendererGap` before anything is written.
- `supported-kinds`: a slide whose kind is outside the list raises `RendererGap` the same way.
  A template that does not declare it accepts every known kind. The Beamer and web templates
  declare all six.
- `requires: lab-assets`: the render needs the lab gabarit folder (`--lab-dir`); without it,
  or with a folder that lacks the banner or the logo, `talk_model.py` refuses with exit 2. Only
  the web template declares it, so the Beamer and PowerPoint flows need no such flag.

### What a template receives

The model's own keys (`meta`, `palette`, `budget`, `slides`), plus four computed values:

| Key | Content | Source |
| --- | --- | --- |
| `sections` | the distinct `section` values of the slides, in first-seen order, from content and divider slides only (a backup, title, outline or thanks slide lists nothing): what an `outline` lists | `talk_model.outline_sections` |
| `pacing` | the spoken seconds of each slide, in the model's slide order, at the `--wpm` rate; a backup slide counts 0, being outside the slot | `talk_model.slide_pacing`, from `budget_rows` |
| `web` | the interaction values (`swipe_threshold_px`) | `talk_rules.WEB_INTERACTION` |
| `lab` | `banner` and `logo` as `data:` URIs, only for a template requiring `lab-assets` | `talk_model.load_lab_assets`, file names from `talk_rules.LAB_ASSET_FILES` |

A model key named `sections`, `pacing` or `web` never replaces the computed value, and neither
does `lab` for a template requiring `lab-assets`; `lab` is not computed for any other template.

For an `.html` output, every `figure` block also gains `data_uri`, its asset embedded by
`talk_model.embed_asset` (see "Web target mechanics"); the caller's model is not modified.

The web deck also reads `meta.subtitle`, `meta.institute`, `meta.date`, `meta.short_title`
and `meta.short_author`, none of them in the example above. None is required, but without
`meta.date` the title slide and every footer show no date.

## The three renderers

| Renderer | File | Produces | Aspect handling |
| --- | --- | --- | --- |
| **PowerPoint** | `scripts/talk_pptx.py` (python-pptx) | `.pptx` built **on** the lab gabarit, using its layouts | inherited from the gabarit: `Gabarit169.pptx` is 10 x 5.625 in, `Gabarit43.pptx` is 10 x 7.5 in |
| PowerPoint, no gabarit | `assets/deck_skeleton.js` (pptxgenjs) | `.pptx` generated from scratch | `pres.layout` from `meta.aspect`; 4:3 = 10 x 7.5, 16:9 = 13.33 x 7.5, 9:16 = 7.5 x 13.33 via `defineLayout` |
| **Beamer** | `assets/beamer_skeleton.tex.j2` | `.tex` + compiled PDF on the lab theme | `\documentclass[aspectratio=169]` / `43`; 9:16 needs `\geometry{papersize={...}}` |
| **Web** | `assets/web_skeleton.html.j2` | one self-contained `.html` in the LARI identity, the lab banner and logo read from `--lab-dir` | CSS custom properties `--slide-w` / `--slide-h` on a fixed stage: 1920 x 1080 px for 16:9, 1080 x 1920 for 9:16, 1920 x 1440 for 4:3 or any other `meta.aspect` value, a missing one included |

```bash
python scripts/talk_pptx.py talk_model.json \
       --template ../gabarit_these_maitrise_DSA_UQAC/src/slides/Gabarit169.pptx \
       --out out/deck.pptx
node assets/deck_skeleton.js talk_model.json brand.json out/deck.pptx     # no gabarit only
python scripts/talk_model.py talk_model.json --render assets/beamer_skeleton.tex.j2 --out out/main.tex
python scripts/talk_model.py talk_model.json --render assets/web_skeleton.html.j2 \
       --lab-dir ../gabarit_these_maitrise_DSA_UQAC/src/slides --out out/deck.html
python scripts/talk_validate.py --web out/deck.html --open
```

### Why the PowerPoint target opens the gabarit instead of imitating it

pptxgenjs builds a deck from scratch and has no way to read another file's `slideLayouts`. The
16:9 gabarit carries 18 named layouts, each with its own full-bleed brand picture and real
placeholders, and the 4:3 one carries eleven over a branded master. Generating a lookalike
would mean extracting each background, re-deriving each placeholder rectangle, and keeping that
copy in step with a template the lab will keep editing.

`talk_pptx.py` opens the gabarit with python-pptx instead:

1. **Drop the sample slides** the file ships (six in the 16:9), keeping masters, layouts, theme
   and media. Shipping the lab's example slides inside a conference deck is not a subtle
   defect.
2. **Pick the layout by kind, then tier**, by name. Explicit wins (`layout` on the slide, or
   `--layout-map`), then ordered patterns per tier - the branded `1- Contenu` before a generic
   `Titre et contenu`. An `outline` is timed as a divider but never takes the map's `divider`
   entry: without an `outline` entry it goes to the agenda patterns:

   | Tier | Preferred layouts |
   | --- | --- |
   | `title` | `1- Titre` … `8- Titre`, `Diapositive de titre`, `Title Slide` |
   | `content` | `1- Contenu` … `6- Contenu`, `Titre et contenu`, `Title and Content` |
   | `divider` | `Page separatrice`, `En-tete de section`, `Section Header` |
   | `thanks` | `Fin`, `Merci`, `Thank …` |
   | `backup` | `Vide`, `Blank`, then the content layouts |
   | `outline` (kind) | `Programme`, `Sommaire`, `Outline`, `Agenda`, then the content layouts |

3. **Fill the real placeholders** (title, body) and draw the remaining blocks inside the body
   placeholder's rectangle. That rectangle is the content band: the lab already positioned it
   clear of the banner and the wordmark, so no clearance number is hardcoded anywhere.
4. **Write the notes** into the notes pane, never onto the slide.

The gabarit file itself is opened read-only in effect - the deck is saved elsewhere and the
template's mtime and size are unchanged (asserted in `Test/test_talk_pptx.py`).

Known weakness, and it is the same one as before: PowerPoint has no LaTeX. An `equation` block
with an `image` is placed as a picture; a bare `tex` is set as text in the title face. An
equation-dense in-field talk belongs on the Beamer target, and the skill says so at question
time.

## Lab gabarits - use these, do not invent a theme

**Beamer, canonical** (settled by the professor, 2026-08-11):
`gabarit_these_maitrise_DSA_UQAC/src/slides/`. Its `main.tex` is
`\documentclass[aspectratio=169]{beamer}`, `\usetheme{Madrid}`, `\usecolortheme{default}`,
with `uqacgreen` = RGB(0,99,65) overriding Madrid's blue on `structure`, the four `palette`
levels, `frametitle`, `title`, `block title`, and the head and foot bands; `en-tete1260.jpg`
in `\titlegraphic`; `LogoLARI_FINAL.png` on the right of the frametitle. It predefines
`primary` / `secondary` / `accent1-3` and a `risklow` / `riskmed` / `riskhigh` / `riskcrit`
triad the Beamer target reuses instead of inventing a fourth palette, and it loads `tikz`
with `shapes, arrows, positioning, fit, backgrounds, calc, decorations.pathreplacing,
patterns, shadows, 3d, matrix`, plus `pgfplots` and `pgfgantt`.

The other copies in the workspace (`Assistive-feeding-robot/`,
`DigitalTwinFoodManufacturing/Thesis/proposal/`, `SimulationCuveAluminium/`) are **not** the
reference; read only the canonical path.

**PowerPoint - two files, in the same folder** (`../gabarit_these_maitrise_DSA_UQAC/src/slides/`
relative to this repository; paths stay relative, the workspace root differs per machine):

| Aspect | File | Canvas | Layouts | Where the brand lives |
| --- | --- | --- | --- | --- |
| `16:9` | `Gabarit169.pptx` | 10 x 5.625 in | 18 named | a full-bleed picture per layout, plus placeholders |
| `4:3` | `Gabarit43.pptx` | 10 x 7.5 in | 11 standard | the master background (`ppt/media/image1.jpeg`) |

The 4:3 file is the one to reach for when an **A4 handout** is the deliverable - 4:3 fills a
sheet with far less white than 16:9 - while a projector wants 16:9. The PDF paper format
(question 5) still never changes the slide size; the reflow happens on the PDF.

`Gabarit43.ppt`, the file originally in the folder, is a **legacy binary** PowerPoint document
(OLE compound, magic `D0 CF 11 E0`). No Python OOXML reader opens it. `Gabarit43.pptx` beside
it is the converted copy; the original is untouched. `talk_template.py` detects the format by
magic bytes and either says so or, with `--convert`, saves a `.pptx` through PowerPoint COM
(`SaveAs(..., 24)` = `ppSaveAsOpenXMLPresentation`).

Two properties of the code that must not regress:

- `talk_template.py` and `talk_pptx.py` accept **any** `.pptx` and derive everything from it.
  There is no LAR.i constant in either, and none may be added - the layout choice is by name
  pattern, the geometry by placeholder.
- If the gabarit is missing when the skill runs, **say so and ask for the path** rather than
  falling back to a stand-in. The CASE 2026 deck
  (`ExpertSystem/SmartSafetyHelmet/article/Presentation CASE2026 Raphael Feuku.pptx`) was the
  stand-in before the gabarits arrived and is no longer a reference for anything.

**Brand inconsistency, measured 2026-08-12.** The Beamer gabarit's `uqacgreen` is RGB(0,99,65)
= `#006341`. The CASE PowerPoint master background measures RGB(90,114,16) = `#5A7210`. The
PowerPoint gabarits settle nothing on their own: `Gabarit169.pptx` ships the **stock Office
colour scheme** (`dk2 #1F497D`, `accent1 #4F81BD`) and carries its green only inside the layout
pictures, so there is no theme value to compare against. Practical consequence: the green a
generated shape uses is whatever `talk_model.json.palette.brand` says, and it should be set
deliberately - `#006341` is the defensible default since it is the one value the lab states
explicitly anywhere. The Beamer template lets it override `uqacgreen`; `talk_pptx.py` uses it
for cards, chips, matrices and zone bands, while the layout artwork stays untouched.

## Reading the brand contract

`talk_template.py` emits it. Two conversions matter, both verified against the rendered
template:

- **EMU to inches**: `off` / `ext` divided by 914400.
- **`srcRect`**: `l/t/r/b` in thousandths of a percent, so `b="71648"` crops 71.648 % off the
  bottom and **keeps the top 28.352 %**. The script reports the keep-fraction, because the
  inversion is the step that goes backwards.

The **content band** is the usable rectangle left by whatever the master background bakes in.
Record it in `brand.json` as `content_band` (`left`, `top`, `right`, `bottom` in inches);
`deck_skeleton.js` reads it and warns when a slide's blocks run past the bottom.

## Web target mechanics

The look comes from the canonical Beamer gabarit **as it renders** when compiled: the green
frame-title band, the rounded green title box with the UQAC banner above it, green blocks and
red alert blocks, one green footer row. The source places the LARI logo beside every frame
title, but the compiled pages do not show it there, so the web deck carries the logo on the
title slide only. The sample's defects are not reproduced: the footer is a row of its own that
nothing sits under, a field longer than its box is reported by `talk_model.py` when it renders
the web deck (`footer_problems`), and there are no navigation icons.

The stage mechanics were borrowed from `github.com/zarazhangrui/frontend-slides` (MIT) and
reimplemented:

- **Fixed stage.** One stage of fixed pixel size, scaled by a single CSS transform on resize.
  Letterbox and pillarbox are fine; content never re-lays out, and there are no responsive
  breakpoints inside a slide. An aspect change touches `--slide-w` / `--slide-h` and nothing
  else. The stage centres itself: its centre is pinned to the viewport's centre and the
  transform is `translate(-50%, -50%) scale(min(vw / w, vh / h))`. Grid centring is not used,
  because a grid item larger than its container starts at the container's corner, and the
  scaled stage then lands off-centre and cropped on any screen smaller than the canvas.
- **Slide switching** uses `visibility` / `opacity` / `pointer-events`. Never `display: none`
  / `display: block`: a later `display: flex` on the slide content overrides the `none` and
  every slide becomes visible at once.
- **A negated CSS function is silently ignored** - `-clamp()`, `-min()`, `-max()` do nothing.
  Write `calc(-1 * clamp(...))`.
- **`prefers-reduced-motion`** is honoured on every animation.
- **Self-contained or nothing.** Inline CSS and JS, images as `data:` URIs, safe-list system
  fonts. No CDN, no webfont, no build step. `talk_model.embed_asset` embeds each figure,
  resolved relative to the folder of `talk_model.json`, and both lab images; it refuses a
  missing file, a path resolving outside its root, a file over
  `talk_rules.WEB_ASSET_MAX_BYTES`, and a file that is not an image by its content (the PNG,
  JPEG and GIF leading bytes of `talk_rules.IMAGE_SIGNATURES`, or an `<svg>` root element after
  an optional XML declaration, comments and DOCTYPE, as matplotlib, draw.io and Inkscape write
  them), so a renamed HTML or script file is never inlined.
  `talk_validate.py --web` then fails the deck on any `src`, `href` or CSS `url()` reference
  that is `http(s)`, protocol-relative (`//`) or relative, because a conference laptop has no
  network and a relative path breaks once the deck leaves the build machine. Only `data:`,
  `#fragment` and `mailto:` pass. A CSS `url()` counts where a browser resolves it: a `<style>`
  block, a `style` attribute, or an SVG attribute that takes a URL (`fill`, `stroke`, ...), a
  tag spread over several lines included; text that only mentions `url()` (slide text, notes,
  `alt`, `title` or `aria-label`) is not a reference.
- **Open only what passed.** `talk_validate.py --web <deck> --open` hands the deck to the
  system's default browser (Python's `webbrowser`, no browser named) only after a clean check.
  A deck with findings exits 1 and an unreadable one exits 2; neither is opened. `--open`
  without `--web`, or beside `--beamer`, is refused (exit 2). In a Unix session with no display
  no browser is started (the standard library would wait on a console browser with no
  timeout) unless the user set `BROWSER`; the deck is named to open by hand. A browser that fails to start is reported with the file
  to open by hand, and the clean verdict stands (exit 0).
- **PDF from the print path**, not from screenshots: the `@media print` block lays each slide
  out as its own page, so headless Chromium gives one page per slide with selectable vector
  text. The footer prints with its slide; the counter, progress bar, help, black screen,
  live-region and notes do not. Hand that PDF to `to_a4.py` when paper output was asked for.
- **Interaction.** The deck's own script reads one JSON literal (`DECK`: the swipe threshold
  and the per-slide pacing) and holds no copy of either. Keys are ignored while an input,
  textarea, select or editable element has focus and while Ctrl, Alt or Meta is held. The
  address `#/n` is read on load (clamped to the deck; anything that is not `#/` and digits is
  ignored) and kept current with `replaceState`. A click advances except on a link, button,
  form field, the help dialog or the notes, and never while the help dialog is open; a
  single-touch swipe at least the threshold long, measured at stage scale, moves and cancels
  the click the browser would synthesize for the same gesture, except on the open help or the
  notes; a second finger cancels the gesture. While the black screen is up, a navigation key or
  a swipe only brings the slide back, as a click does. The talk clock starts at the first move that
  changes the slide, and pacing compares the elapsed time with the budget of the slides from
  the one that move reached, in either direction, to the current one (the slide that move
  left was spoken before the clock ran). An `aria-live` region
  announces each slide and inactive slides carry `aria-hidden`.
- **Style previews**, when offered, must look like a real first slide of this deck and must
  never render internal workflow text - no option letters, no preset names, no file paths, no
  notes such as "safe option" or "audience: ...". Those belong in the message, not on a slide.
