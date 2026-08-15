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

- **`kind` on the slide** is its chrome tier (`content`, `title`, `thanks`, `divider`,
  `backup`). It is declared, never inferred from position: a deck reordered by hand keeps its
  declarations and loses its positions. `talk_notes.py --model` reads the tiers from here
  instead of taking four command-line lists.
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

A Jinja renderer declares what it implements on its first line, which is what
`talk_model.py --render` checks before writing anything:

```jinja
{# supported-blocks: bullets figure takeaway cards chips stats table matrix zoneband chart equation #}
```

## The three renderers

| Renderer | File | Produces | Aspect handling |
| --- | --- | --- | --- |
| **PowerPoint** | `scripts/talk_pptx.py` (python-pptx) | `.pptx` built **on** the lab gabarit, using its layouts | inherited from the gabarit: `Gabarit169.pptx` is 10 x 5.625 in, `Gabarit43.pptx` is 10 x 7.5 in |
| PowerPoint, no gabarit | `assets/deck_skeleton.js` (pptxgenjs) | `.pptx` generated from scratch | `pres.layout` from `meta.aspect`; 4:3 = 10 x 7.5, 16:9 = 13.33 x 7.5, 9:16 = 7.5 x 13.33 via `defineLayout` |
| **Beamer** | `assets/beamer_skeleton.tex.j2` | `.tex` + compiled PDF on the lab theme | `\documentclass[aspectratio=169]` / `43`; 9:16 needs `\geometry{papersize={...}}` |
| **Web** | `assets/web_skeleton.html.j2` | one self-contained `.html` | CSS custom properties `--slide-w` / `--slide-h` on a fixed stage |

```bash
python scripts/talk_pptx.py talk_model.json \
       --template ../gabarit_these_maitrise_DSA_UQAC/src/slides/Gabarit169.pptx \
       --out out/deck.pptx
node assets/deck_skeleton.js talk_model.json brand.json out/deck.pptx     # no gabarit only
python scripts/talk_model.py talk_model.json --render assets/beamer_skeleton.tex.j2 --out out/main.tex
python scripts/talk_model.py talk_model.json --render assets/web_skeleton.html.j2 --out out/deck.html
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
2. **Pick the layout per tier**, by name. Explicit wins (`layout` on the slide, or
   `--layout-map`), then ordered patterns per tier - the branded `1- Contenu` before a generic
   `Titre et contenu`:

   | Tier | Preferred layouts |
   | --- | --- |
   | `title` | `1- Titre` … `8- Titre`, `Diapositive de titre`, `Title Slide` |
   | `content` | `1- Contenu` … `6- Contenu`, `Titre et contenu`, `Title and Content` |
   | `divider` | `Page separatrice`, `En-tete de section`, `Section Header` |
   | `thanks` | `Fin`, `Merci`, `Thank …` |
   | `backup` | `Vide`, `Blank`, then the content layouts |

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

Borrowed from `github.com/zarazhangrui/frontend-slides` (MIT) and reimplemented:

- **Fixed stage.** One stage of fixed pixel size, scaled by a single CSS transform on resize.
  Letterbox and pillarbox are fine; content never re-lays out, and there are no responsive
  breakpoints inside a slide. An aspect change touches `--slide-w` / `--slide-h` and nothing
  else.
- **Slide switching** uses `visibility` / `opacity` / `pointer-events`. Never `display: none`
  / `display: block`: a later `display: flex` on the slide content overrides the `none` and
  every slide becomes visible at once.
- **A negated CSS function is silently ignored** - `-clamp()`, `-min()`, `-max()` do nothing.
  Write `calc(-1 * clamp(...))`.
- **`prefers-reduced-motion`** is honoured on every animation.
- **Self-contained or nothing.** Inline CSS and JS, images as `data:` URIs, safe-list fonts.
  No CDN, no build step; `talk_validate.py --web` fails the deck on any external `http(s)`
  reference, because a conference laptop has no network.
- **PDF from the print path**, not from screenshots: the `@media print` block lays each slide
  out as its own page, so headless Chromium gives one page per slide with selectable vector
  text. Hand that PDF to `to_a4.py` when paper output was asked for.
- **Style previews**, when offered, must look like a real first slide of this deck and must
  never render internal workflow text - no option letters, no preset names, no file paths, no
  notes such as "safe option" or "audience: ...". Those belong in the message, not on a slide.
