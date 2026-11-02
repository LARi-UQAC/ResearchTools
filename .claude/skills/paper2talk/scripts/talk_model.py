"""
talk_model - the deck as data, before any renderer touches it.

The skill has three output targets (PowerPoint, Beamer, web). Writing the deck
three times means the action titles, the numbers and the speaker notes drift three
ways, so the deck is built once as `talk_model.json` and rendered from there.

This module owns the vocabulary that file speaks: the block kinds, which of them
count as an exhibit, what a slide must carry, and how the word budget aggregates.
It also owns the rule that keeps a renderer honest - a renderer that cannot draw a
block raises rather than silently dropping it, because a dropped block is a hole in
the argument that nobody sees until the room does.

Usage
-----
    python talk_model.py <talk_model.json> [--audience field] [--json]
    python talk_model.py <talk_model.json> --render ../assets/beamer_skeleton.tex.j2 \
           --out out/main.tex
    python talk_model.py <talk_model.json> --render ../assets/web_skeleton.html.j2 \
           --lab-dir <gabarit slides folder> --out out/deck.html

Prints the model's problems, the exhibit-coverage state, and the budget
aggregation. Exit 0 when the model is clean, 1 when it has problems (an .html
render adds a footer field over its box to them, and still writes the deck), 2 on
a file or usage error, or on a render refused (a template requiring the lab assets
given no usable --lab-dir, a figure that cannot be embedded, a renderer gap).
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import sys

import talk_rules as rules

TAG = "[MODEL]"

# Every block kind the CASE 2026 deck actually needed. A renderer implements all of
# them or fails loudly on the one it cannot draw.
BLOCK_KINDS: dict[str, tuple[str, ...]] = {
    "bullets": ("items",),
    "figure": ("asset",),
    "takeaway": ("text",),
    "cards": ("items",),
    "chips": ("items",),
    "stats": ("items",),
    "table": ("rows",),
    "matrix": ("rows",),
    "zoneband": ("zones",),
    "chart": ("series",),
    "equation": ("tex",),
}

# What counts as an exhibit for the content-hierarchy rule. A figure, a table, a
# chart, an equation, and the native diagrams that encode a quantity (a matrix of
# cells, a banded zone axis) are exhibits. Cards, chips, stats and bullets are not:
# they are prose in boxes, and a deck of tidy cards reads as designed while being
# pure prose.
EXHIBIT_KINDS = frozenset({"figure", "table", "chart", "matrix", "zoneband", "equation"})

# The slide kinds a model may declare: every tier of talk_rules.TIER_MINUTES plus the
# kinds talk_rules.KIND_TIER times as one of them. A tier is reached through
# talk_rules.tier_of, never validated against a second list here.
SLIDE_KINDS = frozenset(rules.KINDS)

# Jinja delimiters for a LaTeX target. The defaults collide with LaTeX braces -
# `\titlegraphic{%` reads as a Jinja block start and the template never compiles.
LATEX_DELIMITERS = {
    "block_start_string": "((*",
    "block_end_string": "*))",
    "variable_start_string": "(((",
    "variable_end_string": ")))",
    "comment_start_string": "((#",
    "comment_end_string": "#))",
}


class RendererGap(Exception):
    """A renderer was handed a block kind it cannot draw."""


class AssetError(ValueError):
    """An asset the web target must embed is missing, outside its root, too large, or not an image."""


def load(path: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a talk_model.json from disk with a message that names the file when
        the JSON is malformed, rather than a bare traceback.

    Inputs:
        path (str): path to the model file

    Outputs:
        model (dict): the parsed model
    --------------------------------------------------------------------------
    """
    try:
        with open(path, encoding="utf8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{TAG} {path} is not valid JSON: {exc}") from exc


def slide_kind(slide: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a slide's kind from the model: what the renderers draw. The kind is
        declared, never inferred from position: a deck reordered by hand keeps its
        declarations and loses its positions.

    Inputs:
        slide (dict): one entry of model["slides"]

    Outputs:
        kind (str): one of talk_rules.KINDS

    Raises:
        ValueError: the slide declares a kind that talk_rules does not know.
    --------------------------------------------------------------------------
    """
    kind = str(slide.get("kind", "content")).strip().lower()
    if kind not in SLIDE_KINDS:
        raise ValueError(
            f"{TAG} slide {slide.get('n')} declares kind {kind!r}; "
            f"expected one of {', '.join(sorted(SLIDE_KINDS))}"
        )
    return kind


def slide_tier(slide: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the budget tier a slide is timed as: its kind, resolved through
        talk_rules.tier_of (an outline is timed as a divider).

    Inputs:
        slide (dict): one entry of model["slides"]

    Outputs:
        tier (str): content, title, thanks, divider, or backup

    Raises:
        ValueError: the slide declares a kind that talk_rules does not know.
    --------------------------------------------------------------------------
    """
    return rules.tier_of(slide_kind(slide))


# The kinds whose section is part of the talk an outline announces.
_SECTION_KINDS = ("content", "divider")


def outline_sections(model: dict) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List what an outline slide shows: the distinct section names the model's
        slides declare, in the order they first appear. Only content and divider
        slides count: a backup slide sits outside the talk slot, and a title,
        outline or thanks slide is chrome that would otherwise list itself.

    Inputs:
        model (dict): a parsed talk_model.json

    Outputs:
        sections (list): distinct non-empty `section` values, first occurrence first
    --------------------------------------------------------------------------
    """
    sections: list[str] = []
    for slide in model.get("slides", []):
        # Read the declared kind directly: slide_kind raises on an unknown one, which
        # validate_model reports itself rather than crashing here.
        if str(slide.get("kind", "content")).strip().lower() not in _SECTION_KINDS:
            continue
        name = str(slide.get("section") or "").strip()
        if name and name not in sections:
            sections.append(name)
    return sections


def exhibits(slide: dict) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the blocks of a slide that count as visual evidence, which is what
        the no-text-only rule and the say-what-you-show check both operate on.

    Inputs:
        slide (dict): one entry of model["slides"]

    Outputs:
        blocks (list): the blocks whose kind is in EXHIBIT_KINDS
    --------------------------------------------------------------------------
    """
    return [b for b in slide.get("blocks", []) if b.get("kind") in EXHIBIT_KINDS]


def exhibit_keywords(block: dict) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the words that prove an exhibit was discussed. Coverage is matched
        on subject keywords, never on a filename: notes that say "the blink
        interval widens" cover fig5_evolution.png, and no author writes the file
        name out loud.

    Inputs:
        block (dict): an exhibit block, ideally carrying a "keywords" list

    Outputs:
        keywords (list): lowercased keywords; empty when the model declares none
    --------------------------------------------------------------------------
    """
    words = block.get("keywords") or []
    return [str(w).strip().lower() for w in words if str(w).strip()]


def _footer_problems(meta: dict) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report a footer field too long for its box, so it is shortened in the
        model instead of being clipped on every slide.

    Details:
        The field checked is the one the footer would show: meta.short_title in
        place of meta.title, and meta.short_author in place of the authors joined
        with ", ", whenever the short form is given. A short form that is itself
        over the cap is therefore reported too.

    Inputs:
        meta (dict): model["meta"]

    Outputs:
        problems (list): one line per field over talk_rules.FOOTER_FIELD_MAX_CHARS
    --------------------------------------------------------------------------
    """
    cap = rules.FOOTER_FIELD_MAX_CHARS
    authors = meta.get("authors") or []
    fields = (
        ("title", "short_title", meta.get("short_title") or meta.get("title") or ""),
        ("authors", "short_author",
         meta.get("short_author") or ", ".join(str(a) for a in authors)),
    )
    problems = []
    for name, short_key, shown in fields:
        shown = str(shown).strip()
        if len(shown) > cap:
            problems.append(f"{TAG} the footer {name} is {len(shown)} characters, over the "
                            f"{cap}-character footer box; give meta.{short_key} "
                            f"(at most {cap})")
    return problems


def footer_problems(model: dict) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The footer-field check for the web target, the one renderer whose footer
        reads meta.short_title and meta.short_author. Beamer and PowerPoint do not
        read them, so the check is not part of validate_model.

    Inputs:
        model (dict): a parsed talk_model.json

    Outputs:
        problems (list): one line per footer field over the cap, empty when clean
    --------------------------------------------------------------------------
    """
    return _footer_problems(model.get("meta") or {})


def validate_model(model: dict, audience: str | None = None) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check the model against the rules that can be judged before rendering:
        the block vocabulary, the required fields of each block, the declared
        tiers, the no-text-only-content-slide rule, and exhibit coverage in the
        speaker notes.

    Inputs:
        model (dict): a parsed talk_model.json
        audience (str): field, academic or public; defaults to model.meta.audience

    Outputs:
        problems (list): one human-readable line per problem, empty when clean
    --------------------------------------------------------------------------
    """
    problems: list[str] = []
    meta = model.get("meta", {})
    audience = audience or meta.get("audience") or "field"
    try:
        rules.audience_profile(audience)
    except ValueError as exc:
        problems.append(str(exc))

    slides = model.get("slides") or []
    if not slides:
        problems.append(f"{TAG} the model declares no slides")

    seen: set[int] = set()
    for slide in slides:
        n = slide.get("n")
        if n in seen:
            problems.append(f"{TAG} slide number {n} appears twice")
        seen.add(n)
        try:
            tier = slide_tier(slide)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if not str(slide.get("title", "")).strip() and tier != "backup":
            problems.append(f"{TAG} slide {n} has no title")
        if slide_kind(slide) == "outline" and not outline_sections(model):
            problems.append(f"{TAG} slide {n} is an outline, but no content or divider "
                            "slide declares a section for it to list")

        for block in slide.get("blocks", []):
            kind = block.get("kind")
            if kind not in BLOCK_KINDS:
                problems.append(
                    f"{TAG} slide {n} carries unknown block kind {kind!r}; "
                    f"known kinds are {', '.join(sorted(BLOCK_KINDS))}"
                )
                continue
            for field in BLOCK_KINDS[kind]:
                if not block.get(field):
                    problems.append(f"{TAG} slide {n} block {kind} is missing {field!r}")

        if tier == "content" and not exhibits(slide):
            problems.append(
                f"{TAG} slide {n} is a text-only content slide (no figure, table, chart, "
                "matrix, zone band or equation); cards, chips and bullets are prose in boxes"
            )

        notes = str(slide.get("notes", "")).lower()
        for block in exhibits(slide):
            keys = exhibit_keywords(block)
            if not keys:
                problems.append(
                    f"{TAG} slide {n} exhibit {block.get('kind')} declares no keywords, "
                    "so coverage cannot be checked"
                )
            elif not any(k in notes for k in keys):
                problems.append(
                    f"{TAG} slide {n} exhibit {block.get('kind')} is never discussed in its "
                    f"own notes (looked for {', '.join(keys)})"
                )
    return problems


def slide_text(slide: dict) -> str:
    """Every string a slide puts in front of the audience, notes excluded."""
    parts = [str(slide.get("title", ""))]
    for block in slide.get("blocks", []):
        for key in ("text", "support", "caption", "cite", "tex", "plain", "where"):
            if block.get(key):
                parts.append(str(block[key]))
        for item in block.get("items", []) or []:
            if isinstance(item, dict):
                parts += [str(v) for v in item.values()]
            else:
                parts.append(str(item))
        for row in block.get("rows", []) or []:
            parts += [str(cell) for cell in (row if isinstance(row, list) else [row])]
        for zone in block.get("zones", []) or []:
            parts += [str(v) for v in zone.values()]
        for serie in block.get("series", []) or []:
            parts.append(str(serie.get("name", "")))
            for point in serie.get("points", []) or []:
                parts += [str(v) for v in point]
    return " ".join(parts)


def check_numbers(model: dict, source_numbers) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Flag every number on a slide that the paper does not state. A number
        invented between the manuscript and the deck is the failure mode nobody
        catches by reading, and the room catches it in the worst way.

        Comparison is on normalised values (paper_extract.normalise_number), so
        "1 950", "1950" and "1.950" are one number and a French decimal comma
        does not raise a false alarm.

    Inputs:
        model (dict): a parsed talk_model.json
        source_numbers (iterable): the numbers the paper states, from
            `paper_extract.py --numbers`

    Outputs:
        problems (list): one line per slide number absent from the source
    --------------------------------------------------------------------------
    """
    import paper_extract

    known = {paper_extract.normalise_number(str(n)) for n in source_numbers}
    problems = []
    for slide in model.get("slides", []):
        reported: set[str] = set()
        for raw in paper_extract._RE_NUMBER.findall(slide_text(slide)):
            value = paper_extract.normalise_number(raw)
            # Slide numbering, list ordinals and years the paper may not repeat
            # verbatim are not claims; a bare small integer is not evidence.
            if value in known or (value.isdigit() and int(value) <= 12):
                continue
            if value in reported:      # the same number twice on one slide is one problem
                continue
            reported.add(value)
            problems.append(
                f"{TAG} slide {slide.get('n')} states {raw!r}, which is in no source "
                "sentence; build the slide on a value the results section validates"
            )
    return problems


def assert_renderable(model: dict, supported: set[str] | frozenset[str], renderer: str,
                      kinds: set[str] | frozenset[str] | None = None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse to render a model containing a block, or a slide kind, the renderer
        cannot draw. The alternative, dropping it, produces a deck that looks
        finished and is missing an argument.

    Inputs:
        model (dict): a parsed talk_model.json
        supported (set): block kinds this renderer implements
        renderer (str): renderer name, for the message
        kinds (set | None): slide kinds this renderer implements; None when the
            renderer does not declare them, which accepts every known kind

    Outputs:
        None. Raises RendererGap naming the renderer, the slide and the block or kind.
    --------------------------------------------------------------------------
    """
    for slide in model.get("slides", []):
        if kinds is not None:
            kind = str(slide.get("kind", "content")).strip().lower()
            if kind not in kinds:
                raise RendererGap(
                    f"{TAG} renderer {renderer} cannot draw slide kind {kind!r} on slide "
                    f"{slide.get('n')}; implement it or change the slide"
                )
        for block in slide.get("blocks", []):
            kind = block.get("kind")
            if kind not in supported:
                raise RendererGap(
                    f"{TAG} renderer {renderer} cannot draw block {kind!r} on slide "
                    f"{slide.get('n')}; implement it or change the block"
                )


def budget_rows(model: dict, wpm: float = rules.DEFAULT_WPM) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Aggregate the word budget straight from the model, using the same word
        counter and the same tier costs talk_notes.py applies to the built deck.
        The two must agree; when they do not, one of them is wrong.

    Inputs:
        model (dict): a parsed talk_model.json
        wpm (float): delivery rate

    Outputs:
        rows (list): per slide, its number, tier, words, target words and drift
    --------------------------------------------------------------------------
    """
    rows = []
    for slide in sorted(model.get("slides", []), key=lambda s: s.get("n", 0)):
        tier = slide_tier(slide)
        words = rules.word_count(slide.get("notes", ""))
        target = rules.tier_words(tier, wpm)
        rows.append(
            {
                "slide": slide.get("n"),
                "tier": tier,
                "words": words,
                "seconds": words / wpm * 60.0 if wpm else 0.0,
                "target_words": target,
                "drift_pct": (100.0 * (words - target) / target) if target else None,
            }
        )
    return rows


def model_totals(model: dict, wpm: float = rules.DEFAULT_WPM) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sum the model's in-slot words and report the deck shape it implies, so
        the build contract can be checked against the authored notes before the
        deck is rendered at all.

    Inputs:
        model (dict): a parsed talk_model.json
        wpm (float): delivery rate

    Outputs:
        totals (dict): total_words, total_minutes, and the tier counts
    --------------------------------------------------------------------------
    """
    rows = budget_rows(model, wpm)
    in_slot = [r for r in rows if r["tier"] != "backup"]
    total_words = sum(r["words"] for r in in_slot)
    counts = {t: sum(1 for r in rows if r["tier"] == t) for t in rules.TIERS}
    return {
        "total_words": total_words,
        "total_minutes": total_words / wpm if wpm else 0.0,
        "counts": counts,
        "n_content": counts["content"],
    }


def supported_blocks(template_path: str) -> set[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the block kinds a Jinja template implements from its comment header
        (template_requirements reads the whole header, blank lines included, up to
        the first content line), which every renderer template in assets/ declares:

            {# supported-blocks: bullets figure takeaway ... #}

        The declaration is what lets the model refuse a render that would drop a
        block, instead of discovering the hole in the room.

    Inputs:
        template_path (str): path to the .j2 template

    Outputs:
        kinds (set): the declared block kinds; all known kinds when undeclared
    --------------------------------------------------------------------------
    """
    declared = template_requirements(template_path)["supported-blocks"]
    return set(BLOCK_KINDS) if declared is None else declared


# Header keys a template may declare, one per comment line at the top of the file.
_HEADER_KEYS = ("supported-blocks", "supported-kinds", "requires")


def template_requirements(template_path: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read what a Jinja template declares about itself in its header: the block
        kinds it draws, the slide kinds it draws, and what it needs at render time.

    Details:
        The header is the run of comment lines at the top of the file, in either
        delimiter the templates use ({# ... #} for HTML, ((# ... #)) for LaTeX).
        Each line holds one "key: value value ..." declaration, Jinja's "-"
        whitespace control allowed. Blank lines are skipped; reading stops at the
        first other line that is not a comment.

    Inputs:
        template_path (str): path to the .j2 template

    Outputs:
        declared (dict): "supported-blocks" and "supported-kinds" as sets, or None
            when undeclared; "requires" as a set, empty when undeclared
    --------------------------------------------------------------------------
    """
    declared: dict = {"supported-blocks": None, "supported-kinds": None, "requires": set()}
    # utf-8-sig: a template saved with a byte-order mark keeps its header readable.
    with open(template_path, encoding="utf-8-sig") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue        # a blank line inside the header ends nothing
            if not text.startswith(("{#", "((#")):
                break
            # "{#-" / "-#}" are Jinja whitespace control, not part of the key.
            body = text.lstrip("{(#").lstrip("-").replace("#}", " ").replace("#))", " ")
            body = body.strip().rstrip("-").strip()
            key, sep, payload = body.partition(":")
            key = key.strip()
            if sep and key in _HEADER_KEYS:
                # A key repeated on another line adds to it, never replaces it.
                declared[key] = (declared[key] or set()) | {v for v in payload.split() if v}
    return declared


_LATEX_ESCAPES = (
    ("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("#", r"\#"),
    ("_", r"\_"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}"),
    ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
)


def latex_escape(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Escape the characters that make LaTeX misread authored content. The one
        that actually bit: a table cell reading "95.2 %" comments out the rest of
        the line, eats the row terminator, and the tabular collapses with a
        cascade of "Misplaced \\cr".

    Inputs:
        text (str): a value coming from talk_model.json

    Outputs:
        escaped (str): safe to drop into a .tex file
    --------------------------------------------------------------------------
    """
    for raw, safe in _LATEX_ESCAPES:
        text = text.replace(raw, safe)
    return text


def _image_mime(head: bytes) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the image type of a file from its leading bytes, never its extension.

    Details:
        SVG has no fixed signature: it is accepted when, after an optional BOM,
        whitespace, XML declaration, comments and DOCTYPE (matplotlib and draw.io
        write a DOCTYPE, Inkscape a comment), the first element is <svg. A prologue
        item that is never closed, or any other root element, is not an image.

    Inputs:
        head (bytes): the start of the file

    Outputs:
        mime (str | None): the MIME type, or None when the bytes are not an image
            type the web target accepts
    --------------------------------------------------------------------------
    """
    for signature, mime in rules.IMAGE_SIGNATURES:
        if head.startswith(signature):
            return mime
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    while True:
        if text.startswith(b"<?xml"):
            end, close = text.find(b"?>"), 2
        elif text.startswith(b"<!--"):
            end, close = text.find(b"-->"), 3
        elif text.startswith(b"<!DOCTYPE"):
            # An internal subset ([ ... ]) may itself hold a '>', so close after it.
            subset = text.find(b"[")
            gt = text.find(b">")
            close = 1
            if subset != -1 and (gt == -1 or subset < gt):
                end = text.find(b"]", subset)
                end = text.find(b">", end) if end != -1 else -1
            else:
                end = gt
        else:
            break
        if end == -1:
            return None
        text = text[end + close:].lstrip()
    if text.startswith(b"<svg"):
        return rules.SVG_MIME
    return None


def embed_asset(path: str, root: str, max_bytes: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one asset referenced by the model and return it as a data: URI, so a
        web deck carries its figures inside the file.

    Details:
        The path is resolved against root FIRST (symlinks, "..", absolute and
        drive-relative forms included) and only then compared with root, so a
        containment check never runs on the unresolved string (R24).

    Inputs:
        path (str): the asset as written in the model, relative to root
        root (str): the folder the model's asset paths are relative to
        max_bytes (int): the largest file accepted

    Outputs:
        uri (str): "data:<mime>;base64,<payload>"

    Raises:
        AssetError: the asset is not a path string, it resolves outside root, the
            file is missing, it is larger than max_bytes, or its leading bytes are not
            a recognised image.
    --------------------------------------------------------------------------
    """
    if not isinstance(path, str):
        raise AssetError(f"{TAG} asset {path!r} is not a path string; refused")
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, path))
    try:
        inside = os.path.commonpath([root_real, target]) == root_real
    except ValueError:  # different drives on Windows
        inside = False
    if not inside:
        raise AssetError(f"{TAG} asset {path!r} resolves outside {root!r}; refused")
    if not os.path.isfile(target):
        raise AssetError(f"{TAG} asset {path!r} not found under {root!r}")
    size = os.path.getsize(target)
    if size > max_bytes:
        raise AssetError(f"{TAG} asset {path!r} is {size} bytes, over the {max_bytes}-byte "
                         "cap for an embedded file; re-export it smaller")
    with open(target, "rb") as fh:
        data = fh.read()
    mime = _image_mime(data)
    if mime is None:
        raise AssetError(f"{TAG} asset {path!r} is not a recognised image (PNG, JPEG, GIF "
                         "or SVG by its content); refused")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _embed_figures(model: dict, model_dir: str | None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a copy of the model whose figure blocks carry data_uri, for the web
        target. The caller's model is left as it was.

    Inputs:
        model (dict): a parsed talk_model.json
        model_dir (str | None): the folder figure assets are relative to

    Outputs:
        model (dict): a deep copy with data_uri set on every figure block

    Raises:
        AssetError: a figure is present and model_dir is None, or embed_asset
            refuses one of the figures.
    --------------------------------------------------------------------------
    """
    embedded = copy.deepcopy(model)
    for slide in embedded.get("slides", []):
        for block in slide.get("blocks", []):
            if block.get("kind") != "figure":
                continue
            if not block.get("asset"):
                raise AssetError(f"{TAG} slide {slide.get('n')}: a figure block has no "
                                 "'asset' to embed")
            if model_dir is None:
                raise AssetError(f"{TAG} slide {slide.get('n')}: a web render needs the "
                                 "model's folder to embed figure assets")
            block["data_uri"] = embed_asset(block["asset"], model_dir,
                                            rules.WEB_ASSET_MAX_BYTES)
    return embedded


def load_lab_assets(lab_dir: str) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the lab images (banner and logo) from the gabarit folder named at
        render time, as data: URIs. The folder is the source of truth: no copy of
        either image lives in this repository.

    Inputs:
        lab_dir (str): the lab gabarit folder holding rules.LAB_ASSET_FILES

    Outputs:
        lab (dict): role ("banner", "logo") to data: URI

    Raises:
        AssetError: the folder does not exist, or embed_asset refuses one of the
            files (missing, too large, not an image).
    --------------------------------------------------------------------------
    """
    if not os.path.isdir(lab_dir):
        raise AssetError(f"{TAG} lab folder {lab_dir!r} not found; pass the gabarit "
                         "slides folder with --lab-dir")
    return {role: embed_asset(name, lab_dir, rules.WEB_ASSET_MAX_BYTES)
            for role, name in rules.LAB_ASSET_FILES.items()}


def slide_pacing(model: dict, wpm: float = rules.DEFAULT_WPM) -> list[float]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The spoken seconds of each slide, in the order a template renders them
        (the model's own order), from the same budget_rows talk_notes agrees with.
        A backup slide counts 0: it sits outside the slot.

    Inputs:
        model (dict): a parsed talk_model.json
        wpm (float): delivery rate

    Outputs:
        pacing (list): seconds per slide, aligned with model["slides"]
    --------------------------------------------------------------------------
    """
    # budget_rows sorts by slide number; a model listed out of order must still pair
    # each rendered slide with its own seconds.
    by_number = {row["slide"]: (0.0 if row["tier"] == "backup" else row["seconds"])
                 for row in budget_rows(model, wpm)}
    return [by_number[slide.get("n")] for slide in model.get("slides", [])]


def render_template(model: dict, template_path: str, out_path: str, *,
                    model_dir: str | None = None, lab_dir: str | None = None,
                    wpm: float = rules.DEFAULT_WPM) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the model through a Jinja template (the Beamer and web targets),
        after checking that the template implements every block and slide kind
        the model uses.

    Details:
        For an .html output every figure is embedded as a data: URI, so the deck
        stays one file. Any other output keeps the plain asset paths. Every
        template receives `sections` (outline_sections), what an outline lists;
        `pacing` (slide_pacing), the spoken seconds of each slide in rendering
        order; and `web` (talk_rules.WEB_INTERACTION), the interaction values. A
        template whose header declares "requires: lab-assets" also receives `lab`,
        the banner and logo read from lab_dir; one that does not declare it
        renders exactly as before.

    Inputs:
        model (dict): a parsed talk_model.json
        template_path (str): assets/beamer_skeleton.tex.j2 or web_skeleton.html.j2
        out_path (str): destination file
        model_dir (str | None): the folder figure assets are relative to; required
            for an .html output that has figures
        lab_dir (str | None): the lab gabarit folder; required when the template
            declares "requires: lab-assets"
        wpm (float): delivery rate the pacing is computed at

    Outputs:
        out_path (str): the file written

    Raises:
        AssetError: an .html render cannot embed one of its figures, or a template
            requiring lab assets gets no usable lab_dir.
        RendererGap: the template does not implement a block or a slide kind the
            model uses.
    --------------------------------------------------------------------------
    """
    try:
        from jinja2 import Environment, FileSystemLoader
        from markupsafe import Markup
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(f"{TAG} jinja2 is required to render a template: "
                           "pip install jinja2") from exc

    folder, name = os.path.split(os.path.abspath(template_path))
    declared = template_requirements(template_path)
    assert_renderable(model, supported_blocks(template_path), name,
                      declared["supported-kinds"])
    context = dict(model)
    context["sections"] = outline_sections(model)
    context["pacing"] = slide_pacing(model, wpm)
    context["web"] = dict(rules.WEB_INTERACTION)
    if "lab-assets" in declared["requires"]:
        if lab_dir is None:
            raise AssetError(f"{TAG} {name} requires the lab assets; pass the gabarit "
                             "slides folder with --lab-dir")
        context["lab"] = load_lab_assets(lab_dir)
    if out_path.lower().endswith((".html", ".htm")):
        # Only the slides change when figures are embedded. Merging the whole model
        # back would let a model key named lab, web, sections or pacing replace the
        # value computed above.
        context["slides"] = _embed_figures(model, model_dir).get("slides", [])
    # Escaping is decided by what is being written, not by the template's suffix:
    # every template here ends in .j2, so select_autoescape would never fire and a
    # title containing an ampersand would break the web deck.
    options = {
        "loader": FileSystemLoader(folder),
        "autoescape": out_path.lower().endswith((".html", ".htm")),
        "keep_trailing_newline": True,
    }
    is_tex = out_path.lower().endswith(".tex")
    if is_tex:
        # LaTeX and Jinja fight over braces: a frame option written as brace-percent
        # opens a Jinja block and the template stops compiling. The .tex templates
        # therefore use the paren delimiters above.
        options.update(LATEX_DELIMITERS)
        # Every authored value is escaped on the way out, unless the template marks
        # it as deliberate LaTeX with the raw_tex filter (an equation body, a label,
        # an asset path). Escaping by default is what keeps a "95.2 %" cell from
        # commenting out its own row terminator.
        options["finalize"] = lambda v: (
            latex_escape(v) if isinstance(v, str) and not isinstance(v, Markup) else v
        )
    env = Environment(**options)
    if is_tex:
        env.filters["raw_tex"] = lambda v: Markup("" if v is None else str(v))
    text = env.get_template(name).render(**context)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf8") as fh:
        fh.write(text)
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate and summarize a talk model.")
    ap.add_argument("model")
    ap.add_argument("--audience", help="override meta.audience for the rule check")
    ap.add_argument("--wpm", type=float, default=rules.DEFAULT_WPM)
    ap.add_argument("--render", help="a Jinja template to render the model through")
    ap.add_argument("--out", help="destination file for --render")
    ap.add_argument("--lab-dir", help="the lab gabarit slides folder holding the banner and "
                                      "logo; required by a template declaring "
                                      "'requires: lab-assets'")
    ap.add_argument("--check-numbers", metavar="SOURCE",
                    help="a paper_extract.py inventory (.json) or the paper itself: "
                         "flag any number on a slide the paper does not state")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output only")
    args = ap.parse_args(argv)

    try:
        model = load(args.model)
    except (OSError, ValueError) as exc:
        print(f"{TAG} {exc}", file=sys.stderr)
        return 2

    problems = validate_model(model, args.audience)
    totals = model_totals(model, args.wpm)

    if args.check_numbers:
        import paper_extract

        try:
            if args.check_numbers.lower().endswith(".json"):
                with open(args.check_numbers, encoding="utf8") as fh:
                    inventory = json.load(fh)
                if "numbers" not in inventory:
                    raise KeyError(
                        "no 'numbers' key: this is not a paper_extract.py inventory. "
                        "Run paper_extract.py <paper> --out inventory.json first, or pass "
                        "the paper itself"
                    )
                source_numbers = inventory["numbers"]
            else:
                source_numbers = paper_extract.extract(args.check_numbers)["numbers"]
        except (OSError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"{TAG} cannot read {args.check_numbers}: {exc}", file=sys.stderr)
            return 2
        problems += check_numbers(model, source_numbers)

    if args.render:
        if not args.out:
            print(f"{TAG} --render needs --out", file=sys.stderr)
            return 2
        try:
            written = render_template(model, args.render, args.out,
                                      model_dir=os.path.dirname(os.path.abspath(args.model)),
                                      lab_dir=args.lab_dir, wpm=args.wpm)
        except (OSError, RuntimeError, RendererGap, AssetError) as exc:
            # The module's own refusals already carry the tag; an OSError does not.
            message = str(exc)
            print(message if message.startswith(TAG) else f"{TAG} {message}", file=sys.stderr)
            return 2
        # With --json, stdout carries the JSON report alone (R17); the human line moves.
        print(f"{TAG} rendered {args.render} -> {written}",
              file=sys.stderr if args.json else sys.stdout)
        if written.lower().endswith((".html", ".htm")):
            problems += footer_problems(model)

    if args.json:
        print(json.dumps({"problems": problems, "totals": totals,
                          "rows": budget_rows(model, args.wpm)}, indent=2))
    else:
        for line in problems:
            print(line)
        print(
            f"{TAG} {totals['n_content']} content slides, {totals['total_words']} words in "
            f"the slot -> {totals['total_minutes']:.2f} min at {args.wpm:.0f} wpm"
        )
        print(f"{TAG} {'clean' if not problems else str(len(problems)) + ' problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
