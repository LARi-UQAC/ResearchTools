/**
 * deck_skeleton.js - the PowerPoint renderer of a talk_model.json.
 *
 * This is a commented starting point, not a finished generator: copy it next to the
 * deck being built, adjust the layout functions to the brand contract that
 * talk_template.py emitted, and run it. Everything brand-specific is READ, never
 * hardcoded - the palette comes from the model, the canvas and the content band
 * come from brand.json. There is no LAR.i constant anywhere in this file, because
 * the lab PowerPoint gabarit is still being prepared and any .pptx must work.
 *
 *   node deck_skeleton.js talk_model.json brand.json out.pptx
 *
 * Requires pptxgenjs. It resolves node_modules by walking UP from this script, so a
 * build run outside the tree that holds the install needs NODE_PATH set explicitly:
 *
 *   NODE_PATH=/path/to/node_modules node deck_skeleton.js ...
 *
 * Footguns that cost a pass each in the CASE 2026 session, all handled below:
 *
 *   - Colors are six hex digits with NO leading '#' and NO alpha channel.
 *   - One `new PptxGenJS()` per file. A second one silently writes an empty deck.
 *   - `rectRadius` applies to ROUNDED_RECTANGLE only; on a plain rect it is ignored.
 *   - Body text inside a card needs `valign: "top"`. pptxgenjs centres vertically by
 *     default, which is what left the ragged column tops in the first pass.
 *   - The property is `charSpacing`, not `letterSpacing`.
 *   - `rowH` in addTable is a MINIMUM, not a height. A two-line cell grows the row
 *     and the table runs past its planned bottom - two v4 tables overflowed, one
 *     under the takeaway band and one into the wordmark. Bound the cell text and
 *     look at the rendered page; never trust rowH.
 *   - Charts: `lineDataSymbol: "none"`, explicit `valAxisMaxVal` / `valAxisMinVal`,
 *     `catGridLine: { style: "none" }`, and never `secondaryValAxis` - pptxgenjs
 *     writes undeclared axis ids and PowerPoint calls the file corrupt.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const PptxGenJS = require("pptxgenjs");

// Every block kind talk_model.json can carry. A kind that is not in here must
// raise: a renderer that silently drops a block ships a deck that looks finished
// and is missing an argument.
const SUPPORTED = new Set([
  "bullets", "figure", "takeaway", "cards", "chips",
  "stats", "table", "matrix", "zoneband", "chart", "equation",
]);

const TFONT = "Cambria"; // titles, equations, stat numbers
const BFONT = "Calibri"; // body; both ship with Office and render true-to-width

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

/** Layout numbers derived from the brand contract, in inches. */
function geometry(brand, aspect) {
  const canvas = (brand && brand.canvas) || {};
  const w = canvas.w_in || (aspect === "16:9" ? 13.333 : aspect === "9:16" ? 7.5 : 10);
  const h = canvas.h_in || (aspect === "9:16" ? 13.333 : 7.5);
  // The content band is bounded by whatever the master background bakes in. On the
  // CASE stand-in the UQAC wordmark sits at x 7.97-9.4, y 6.7-7.17 in a 10 x 7.5
  // canvas, so nothing may go below y 6.55. Read the real numbers out of brand.json
  // rather than reusing these.
  const band = (brand && brand.content_band) || {};
  return {
    w, h,
    ml: band.left != null ? band.left : 0.5,
    top: band.top != null ? band.top : 2.06,
    bottom: band.bottom != null ? band.bottom : h - 0.95,
    cw: (band.right != null ? band.right : w - 0.5) -
        (band.left != null ? band.left : 0.5),
  };
}

/** Font sizes, floored by the audience answer (see talk_rules.py). */
function fonts(audience) {
  const floor = audience === "public" ? 20 : 16;
  return {
    title: audience === "public" ? 26 : 24,
    body: floor,
    // Captions and references may sit at the caption floor; nothing else may.
    caption: audience === "public" ? 18 : 14,
    // The section eyebrow is a label, not a caption, so it stays at the body
    // floor - talk_validate.py exempts captions (italic) and would flag it.
    eyebrow: floor,
    floor,
  };
}

function build(model, brand, outPath) {
  const meta = model.meta || {};
  const aspect = meta.aspect || "4:3";
  const G = geometry(brand, aspect);
  const F = fonts(meta.audience || "field");
  const P = Object.assign(
    { brand: "5A7210", ink: "23262A", muted: "6B6F63", card: "F1F2EC",
      cardDk: "E4E7DA", white: "FFFFFF", s1: "2E7D32", s2: "C57A00", s3: "B3221F" },
    model.palette || {}
  );

  const pres = new PptxGenJS(); // exactly one, for the whole file
  if (aspect === "16:9") {
    pres.layout = "LAYOUT_WIDE";
  } else if (aspect === "9:16") {
    // Portrait. No lab gabarit ships a background for it, so the master below has
    // to be given its own asset before this branch produces a branded deck.
    pres.defineLayout({ name: "PORTRAIT", width: G.w, height: G.h });
    pres.layout = "PORTRAIT";
  } else {
    pres.layout = "LAYOUT_4x3";
  }
  pres.author = (meta.authors || []).join("; ");
  pres.company = meta.company || "";
  pres.title = meta.title || "";

  const masterObjects = [];
  if (brand && brand.logo) {
    masterObjects.push({ image: Object.assign({ path: brand.logo }, brand.logo_box || {}) });
  }
  pres.defineSlideMaster({
    title: "TALK",
    background: brand && brand.master_background_path
      ? { path: brand.master_background_path }
      : { color: P.white },
    objects: masterObjects,
    slideNumber: { x: 0.3, y: G.h - 0.55, w: 0.6, h: 0.35,
                   fontFace: BFONT, fontSize: F.caption, color: P.muted },
  });

  const shadow = () => ({ type: "outer", angle: 90, blur: 8, offset: 2,
                          color: "9AA08F", opacity: 0.35 });

  function card(slide, x, y, w, h, fill) {
    slide.addShape(pres.ShapeType.roundRect, {
      x, y, w, h,
      rectRadius: 0.06,                       // roundRect only
      fill: { color: fill || P.card },
      line: { color: fill || P.card },
      shadow: shadow(),
    });
  }

  /** Numbered eyebrow + action title. The title states the claim, never the topic. */
  function head(slide, num, section, title) {
    if (num != null) {
      slide.addShape(pres.ShapeType.roundRect, {
        x: G.ml, y: 1.42, w: 0.46, h: 0.46, rectRadius: 0.09,
        fill: { color: P.brand }, line: { color: P.brand },
      });
      slide.addText(String(num), {
        x: G.ml, y: 1.42, w: 0.46, h: 0.46, align: "center", valign: "middle",
        margin: 0, fontFace: TFONT, fontSize: 20, bold: true, color: P.white,
      });
    }
    if (section) {
      slide.addText(String(section).toUpperCase(), {
        x: G.ml + 0.62, y: 1.1, w: G.cw - 0.62, h: 0.24, margin: 0,
        fontFace: BFONT, fontSize: F.eyebrow, bold: true,
        charSpacing: 1.6,                     // charSpacing, not letterSpacing
        color: P.brand,
      });
    }
    slide.addText(title || "", {
      x: G.ml + 0.62, y: 1.36, w: G.cw - 0.62, h: 0.62, margin: 0, valign: "top",
      fontFace: TFONT, fontSize: F.title, bold: true, color: P.ink,
    });
  }

  function bullets(slide, x, y, w, h, items, size) {
    slide.addText(
      items.map((t, i) => ({
        text: String(t),
        options: { bullet: { code: "25AA" }, breakLine: i < items.length - 1 },
      })),
      { x, y, w, h, margin: 0, valign: "top", fontFace: BFONT,
        fontSize: size || F.body, color: P.ink,
        lineSpacingMultiple: 1.02, paraSpaceAfter: 5 }
    );
  }

  function caption(slide, x, y, w, txt) {
    slide.addText(txt, { x, y, w, h: 0.26, margin: 0, fontFace: BFONT,
                         fontSize: F.caption, italic: true, color: P.muted });
  }

  /** Semantic chip: the colour IS the class, which is why the disc survives the
   *  reference skills' ban on ornament. Drop any chip whose colour means nothing. */
  function chip(slide, x, y, color, glyph, label, sub, wide) {
    const d = 0.44;
    slide.addShape(pres.ShapeType.ellipse,
      { x, y, w: d, h: d, fill: { color }, line: { color } });
    slide.addText(glyph || "", { x, y, w: d, h: d, align: "center", valign: "middle",
      margin: 0, fontFace: TFONT, fontSize: F.body, bold: true, color: P.white });
    slide.addText(label, { x: x + d + 0.14, y: sub ? y - 0.05 : y, w: wide || 2.0,
      h: sub ? 0.28 : d, margin: 0, valign: sub ? "top" : "middle",
      fontFace: BFONT, fontSize: F.body, bold: true, color: P.ink });
    if (sub) {
      slide.addText(sub, { x: x + d + 0.14, y: y + 0.26, w: wide || 2.0, h: 0.3,
        margin: 0, valign: "top", fontFace: BFONT, fontSize: F.body, color: P.muted });
    }
  }

  function stat(slide, x, y, w, value, label) {
    slide.addText(String(value), { x, y, w, h: 0.5, margin: 0, align: "center",
      fontFace: TFONT, fontSize: 30, bold: true, color: P.brand });
    slide.addText(label, { x, y: y + 0.5, w, h: 0.4, margin: 0, align: "center",
      valign: "top", fontFace: BFONT, fontSize: F.body, color: P.ink });
  }

  function takeaway(slide, y, claim, support) {
    const h = support ? 1.12 : 0.66;
    card(slide, G.ml, y, G.cw, h, P.cardDk);
    slide.addText(claim, { x: G.ml + 0.26, y: y + (support ? 0.11 : 0.08),
      w: G.cw - 0.52, h: support ? 0.4 : 0.5, margin: 0, valign: "middle",
      fontFace: TFONT, fontSize: F.body + 1, bold: true, color: P.brand });
    if (support) {
      slide.addText(support, { x: G.ml + 0.26, y: y + 0.54, w: G.cw - 0.52, h: 0.5,
        margin: 0, valign: "top", fontFace: BFONT, fontSize: F.body, color: P.ink });
    }
  }

  /** House-style table: bold header on a tint, bold first column. rowH is a
   *  minimum - bound the cell text and inspect the rendered page. */
  function tbl(slide, x, y, w, rows, colW) {
    const body = rows.map((row, r) =>
      row.map((cell, c) => ({
        text: String(cell),
        options: {
          bold: r === 0 || c === 0,
          fill: r === 0 ? { color: P.cardDk } : undefined,
          color: P.ink, fontFace: BFONT, fontSize: F.body,
          valign: "middle", margin: 0.06,
        },
      }))
    );
    slide.addTable(body, {
      x, y, w, colW, border: { pt: 0.75, color: "C9CDBE" },
      autoPage: false,
    });
  }

  /** A matrix of shapes encodes a quantity, so it counts as an exhibit. */
  function matrix(slide, x, y, cell, rows, labels) {
    rows.forEach((row, r) => {
      row.forEach((v, c) => {
        const t = Math.max(0, Math.min(1, Number(v) || 0));
        slide.addShape(pres.ShapeType.rect, {
          x: x + c * cell, y: y + r * cell, w: cell, h: cell,
          fill: { color: P.brand, transparency: Math.round((1 - t) * 100) },
          line: { color: P.white },
        });
        slide.addText(String(v), { x: x + c * cell, y: y + r * cell, w: cell, h: cell,
          align: "center", valign: "middle", margin: 0, fontFace: BFONT,
          fontSize: F.body, color: t > 0.55 ? P.white : P.ink });
      });
    });
    if (labels) {
      labels.forEach((lab, i) => slide.addText(lab,
        { x: x + i * cell, y: y - 0.28, w: cell, h: 0.26, align: "center",
          margin: 0, fontFace: BFONT, fontSize: F.body, color: P.muted }));
    }
  }

  /** Banded axis: a scaled quantity drawn as zones, also an exhibit. */
  function zoneBand(slide, x, y, w, h, zones) {
    let cursor = x;
    zones.forEach((z) => {
      const zw = w * (Number(z.fraction) || 0);
      slide.addShape(pres.ShapeType.rect, { x: cursor, y, w: zw, h,
        fill: { color: z.color || P.brand }, line: { color: P.white } });
      slide.addText(z.label || "", { x: cursor, y, w: zw, h, align: "center",
        valign: "middle", margin: 0, fontFace: BFONT, fontSize: F.body,
        bold: true, color: P.white });
      cursor += zw;
    });
  }

  function chart(slide, x, y, w, h, block) {
    // The model carries a series as { name, points: [[x, y], ...] }, which is the
    // shape the Beamer and web renderers also read. pptxgenjs wants labels and
    // values split, so convert here rather than teaching the model a third shape.
    const series = block.series.map((s) => (
      s.points
        ? { name: s.name, labels: s.points.map((p) => String(p[0])),
            values: s.points.map((p) => Number(p[1])) }
        : s
    ));
    slide.addChart(pres.ChartType[block.chartType || "line"], series, {
      x, y, w, h,
      lineDataSymbol: "none",
      valAxisMinVal: block.min != null ? block.min : 0,
      valAxisMaxVal: block.max != null ? block.max : 1,
      catGridLine: { style: "none" },
      showLegend: block.legend !== false,
      legendPos: "b",
      chartColors: block.colors || [P.s1, P.s2, P.s3],
      fontFace: BFONT, fontSize: F.caption,
      // No secondaryValAxis, ever: pptxgenjs writes undeclared axis ids and
      // PowerPoint then reports the file as corrupt.
    });
  }

  /** Equations have no native form here: pptxgenjs carries no LaTeX. A run with
   *  superscript/subscript is the honest fallback, an exported image is the other.
   *  For an equation-dense in-field talk, recommend the Beamer target instead. */
  function equation(slide, x, y, w, block) {
    if (block.image) {
      slide.addImage({ path: block.image, x, y, w, h: block.h || 0.6 });
    } else {
      slide.addText(block.runs || [{ text: block.tex }], {
        x, y, w, h: block.h || 0.5, margin: 0, valign: "middle",
        fontFace: TFONT, fontSize: F.body + 2, color: P.ink,
      });
    }
  }

  function drawBlock(slide, block, cursor) {
    if (!SUPPORTED.has(block.kind)) {
      throw new Error(
        `deck_skeleton: block kind "${block.kind}" is not implemented; implement it ` +
        "or change the block. Dropping it would hide a missing argument."
      );
    }
    const x = G.ml;
    const w = G.cw;
    switch (block.kind) {
      case "bullets":
        bullets(slide, x, cursor, w, block.h || 2.2, block.items, block.size);
        return cursor + (block.h || 2.2) + 0.1;
      case "figure":
        slide.addImage({ path: block.asset, x: block.x != null ? block.x : x,
          y: cursor, w: block.w || w, h: block.h || 3.0, sizing: { type: "contain",
          w: block.w || w, h: block.h || 3.0 } });
        if (block.caption || block.cite) {
          caption(slide, x, cursor + (block.h || 3.0) + 0.04, w,
            [block.caption, block.cite].filter(Boolean).join("  "));
        }
        return cursor + (block.h || 3.0) + 0.34;
      case "takeaway":
        takeaway(slide, cursor, block.text, block.support);
        return cursor + (block.support ? 1.12 : 0.66) + 0.1;
      case "cards":
        block.items.forEach((it, i) => {
          const cw = (w - 0.2 * (block.items.length - 1)) / block.items.length;
          const cx = x + i * (cw + 0.2);
          card(slide, cx, cursor, cw, block.h || 1.6);
          slide.addText(it.title || "", { x: cx + 0.16, y: cursor + 0.12,
            w: cw - 0.32, h: 0.3, margin: 0, fontFace: BFONT, fontSize: F.body,
            bold: true, color: P.brand });
          slide.addText(it.text || "", { x: cx + 0.16, y: cursor + 0.46,
            w: cw - 0.32, h: (block.h || 1.6) - 0.6, margin: 0,
            valign: "top",                    // pptxgenjs centres by default
            fontFace: BFONT, fontSize: F.body, color: P.ink });
        });
        return cursor + (block.h || 1.6) + 0.16;
      case "chips":
        block.items.forEach((it, i) => chip(slide, x + i * (block.step || 3.0),
          cursor, it.color || P.brand, it.glyph, it.label, it.sub, block.labelW));
        return cursor + 0.7;
      case "stats":
        block.items.forEach((it, i) => {
          const sw = w / block.items.length;
          stat(slide, x + i * sw, cursor, sw, it.value, it.label);
        });
        return cursor + 1.0;
      case "table":
        tbl(slide, x, cursor, w, block.rows, block.colW);
        return cursor + (block.h || 2.2) + 0.14;
      case "matrix":
        matrix(slide, block.x != null ? block.x : x, cursor, block.cell || 0.7,
          block.rows, block.labels);
        return cursor + (block.rows.length * (block.cell || 0.7)) + 0.3;
      case "zoneband":
        zoneBand(slide, x, cursor, w, block.h || 0.5, block.zones);
        return cursor + (block.h || 0.5) + 0.3;
      case "chart":
        chart(slide, block.x != null ? block.x : x, cursor, block.w || w,
          block.h || 3.0, block);
        return cursor + (block.h || 3.0) + 0.2;
      case "equation":
        equation(slide, x, cursor, w, block);
        return cursor + (block.h || 0.5) + 0.16;
      default:
        return cursor;
    }
  }

  (model.slides || []).forEach((s) => {
    const slide = pres.addSlide({ masterName: "TALK" });
    head(slide, s.num, s.section, s.title);
    let cursor = G.top;
    (s.blocks || []).forEach((b) => {
      cursor = drawBlock(slide, b, cursor);
      if (cursor > G.bottom) {
        console.warn(
          `[DECK] slide ${s.n} runs past the content band (${cursor.toFixed(2)} > ` +
          `${G.bottom.toFixed(2)} in). Inspect the rendered page: a table row grew.`
        );
      }
    });
    // Speaker notes live in the notes pane, never in a text box on the slide.
    if (s.notes) slide.addNotes(s.notes);
  });

  return pres.writeFile({ fileName: outPath }).then(() => {
    console.log(`[DECK] wrote ${outPath} (${(model.slides || []).length} slides)`);
  });
}

if (require.main === module) {
  const [modelPath, brandPath, outPath] = process.argv.slice(2);
  if (!modelPath || !outPath) {
    console.error("usage: node deck_skeleton.js talk_model.json brand.json out.pptx");
    process.exit(2);
  }
  const brand = brandPath && fs.existsSync(brandPath) ? loadJson(brandPath) : {};
  build(loadJson(modelPath), brand, path.resolve(outPath)).catch((err) => {
    console.error(String(err.message || err));
    process.exit(1);
  });
}

module.exports = { build, SUPPORTED };
