# The QA loop: render it, look at it, fix it

Visual QA is mandatory for slide work, and every finding below was paid for once already in
the CASE 2026 session (2026-08-11). The loop is `talk_validate.py`, then `talk_render.py`,
then read every page, then fix and repeat. Ship on a clean pass only.

## Rendering on Windows

The `document-skills:pptx` skill prescribes `scripts/office/soffice.py --headless
--convert-to pdf`. On this workstation that fails with:

```text
module 'socket' has no attribute 'AF_UNIX'
```

The wrapper assumes a POSIX socket, and there is no LibreOffice installed behind it anyway.
The measured working pipeline is PowerPoint COM, then Poppler (which ships with the MiKTeX
install already on the machine):

```powershell
$pp = New-Object -ComObject PowerPoint.Application
$deck = $pp.Presentations.Open($path, $true, $false, $false)   # read-only, no title, no window
$deck.SaveAs($pdf, 32)                                         # 32 = ppSaveAsPDF
$deck.Close(); $pp.Quit()
```

```bash
pdftoppm -jpeg -r 100 deck.pdf qa
```

`talk_render.py` does both, tries `soffice` first when it is on PATH, and prints which backend
ran - a silent substitution changes what the images prove.

Two gates in that script:

- **`pdftoppm` zero-pads page numbers by page count**, so a 22-slide deck yields `qa-01.jpg`,
  not `qa-1.jpg`. Glob the results; never construct the name.
- **Page count must equal slide count.** A silent short render is how a broken slide gets
  shipped, so the mismatch exits non-zero.

## Paper output

A slide-sized PDF is what a projector wants; a printable handout needs a real sheet. Do
**not** get there by changing the slide size: PowerPoint's "A4 Paper" preset is 10.83 x 7.5
in, a 1.444 ratio against 4:3's 1.333, so it stretches a branded master background by 8 % and
visibly distorts a logo. Reflow at the PDF stage instead (`to_a4.py`, called by
`talk_render.py --paper`).

Measured on the CASE deck: 720 x 540 pt scaled 1.0499 onto A4 landscape, 15.2 mm side
margins, nothing clipped. Verify with `pdfinfo`, which prints the literal token `(A4)` next to
the page size when the box matches 841.89 x 595.276 pt - assert on the token, not on the
numbers. Margins default to 5 mm because no desk printer reaches the edge.

## Validation gates, per target

| Target | Gate |
| --- | --- |
| PowerPoint | `talk_validate.py deck.pptx --original gabarit.pptx --audience <a> --model talk_model.json` |
| Beamer | the LaTeX log: compile, then `/latex` |
| Web | `talk_validate.py --web deck.html` - no external `http(s)` in `src`, `href` or `url(...)` |

`talk_validate.py` locates the `document-skills:pptx` validator rather than copying it: the
plugin lives at a cache path carrying a hash (`f17010c9bb48` on 2026-08-11) that changes on
every plugin update. It reads `$DOCUMENT_SKILLS_PPTX`, else globs
`~/.claude/plugins/cache/anthropic-agent-skills/document-skills/*/skills/pptx/scripts/office/validate.py`
and takes the newest match. With no match it runs its own checks: every `r:embed` resolves in
the matching `_rels`, every part has a content-type override, `<p:sldIdLst>` matches the slide
files present, and no chart declares `secondaryValAxis` without both `<c:valAx>` and
`<c:catAx>` - that last one is the failure that makes PowerPoint call the file corrupt while
python-pptx, LibreOffice and the XSD all accept it.

**Always pass `--original` for a gabarit-derived deck.** The lab template contains parts the
XSD already rejects, so a bare run reports failures nobody caused and buries the real
regression.

## pptxgenjs footguns

Each of these cost a pass:

- Colors are six hex digits, **no** leading `#`, **no** alpha.
- One `new PptxGenJS()` per file. A second one writes an empty deck.
- `rectRadius` applies to `ROUNDED_RECTANGLE` only.
- Body text inside a card needs `valign: "top"`; pptxgenjs centres vertically by default,
  which is what left the ragged column tops in the first pass.
- The property is `charSpacing`, not `letterSpacing`.
- **`rowH` in `addTable` is a minimum, not a height.** A two-line cell grows the row and the
  table runs past its planned bottom - two v4 tables overflowed, one under the takeaway band
  and one into the UQAC wordmark. Bound the cell text and inspect the page; never trust
  `rowH`.
- pptxgenjs resolves `node_modules` by walking **up from the script**, so a build run outside
  the tree that holds the install needs `NODE_PATH` set explicitly. This bit on the first v3
  build.
- Chart contract that passes validation: `lineDataSymbol: "none"`, explicit `valAxisMaxVal` /
  `valAxisMinVal`, `catGridLine: { style: "none" }`, and **no** `secondaryValAxis` anywhere.

## Speaker-note measurement

- Notes text lives in `ppt/notesSlides/notesSlideN.xml`; concatenate the `<a:t>` runs.
- The slide-number placeholder sits in an `<a:fld>` at the head of the notes and must be
  dropped, or every slide reads one word long.
- **Map notes to slides through `ppt/slides/_rels/slideN.xml.rels`**, never by matching
  `notesSlideN` to `slideN`. PowerPoint does not guarantee the two numberings agree; the CASE
  deck happened to align, and relying on that is how the next deck reports the wrong numbers.

## Figures

The `.png` exports beside a paper are the sizes the Word document needed (571 x 358 for the
Smart Safety Helmet figure), unusable at five inches on a projector. The `.svg` beside them is
usually a draw.io wrapper, and pulling its embedded base64 raster gives only the photo layer
(425 x 567), worse than the PNG and with every vector label lost - that path is **not** a
fallback.

Re-export the vector source through the draw.io CLI at scale 3, which produced 4663 x 2435 and
3095 x 1551 on the CASE figures:

```bash
python scripts/fig_export.py fig1.svg --out assets/fig1_station.png --scale 3 \
       --fix-text typos.json
```

The CLI is asynchronous on Windows: it returns before the file is flushed, so `fig_export.py`
polls until the size is stable rather than sleeping a fixed interval. `--fix-text` applies
`{"wrong": "right"}` to the mxfile inside a **copy** under `figsrc/`, never the figure the
paper cites, and prints each substitution with its count (this is how "vonyeyor" became
"conveyor", "compartiments" became "compartments", "Processus module" became "Process module",
and "eye-blenk" became "eye-blink"). After export the script reports the pixel size and the
implied DPI at the placed width, and warns below 150 DPI.

## What the validator catches before you look

Three checks exist because reading a deck does not reveal them:

- **Shape overlap.** Bounding-box intersection per slide, reported when it covers more than
  15 % of the smaller shape (a text frame is wider than its glyphs, so a few percent is
  normal). The three most frequent defects of the origin session - a caption under a logo, a
  two-line heading colliding with the row beneath it, a table running into the wordmark - are
  all this one check.
- **Semantic-triad lightness.** Roughly one man in twelve cannot separate red from green, and
  a washed-out projector separates nothing by hue. The triad must differ in relative
  luminance, not only in hue. **Measured on the delivered CASE deck**: green `#2E7D32` at
  0.155, amber `#C57A00` at 0.258, red `#B3221F` at 0.108 - the green and the red sit 0.047
  apart, so the two classes that matter most (safe against danger) are exactly the pair a
  colour-blind viewer loses. A triad such as `#2E7D32` / `#F1C40F` / `#7B1E1E` (0.155 / 0.582 /
  0.052) passes.
- **Deck size.** Past 50 MB a deck is slow to open on a shared conference laptop and awkward to
  send. Re-export the heaviest figures rather than dropping content.

## Inspect every page - the defects that actually occurred

In frequency order, from the CASE 2026 session:

1. Body text vertically centred instead of top-aligned.
2. A caption or legend running under a logo baked into the master background.
3. A two-line heading colliding with the row beneath it.
4. An empty decorative shape left where a value was optional.
5. A figure's own low-resolution label typo.
6. A large empty region on a slide whose neighbour is crowded.
7. A table that grew past its planned bottom because `rowH` was trusted.

Then the content gates: no text-only content slide, every exhibit discussed in its own notes,
every section within 5 % of its word target, and the total landing under the slot rather than
at it.
