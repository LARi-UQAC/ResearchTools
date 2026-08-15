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

Prints the model's problems, the exhibit-coverage state, and the budget
aggregation. Exit 0 when the model is clean, 1 when it has problems, 2 on a file
or usage error.
"""
from __future__ import annotations

import argparse
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

# Slide tiers, mirroring talk_rules.TIER_MINUTES.
SLIDE_TIERS = frozenset(rules.TIERS)

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


def slide_tier(slide: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a slide's tier from the model. The tier is declared, never inferred
        from position: a deck reordered by hand keeps its declarations and loses
        its positions.

    Inputs:
        slide (dict): one entry of model["slides"]

    Outputs:
        tier (str): content, title, thanks, divider, or backup
    --------------------------------------------------------------------------
    """
    tier = str(slide.get("kind", "content")).strip().lower()
    if tier not in SLIDE_TIERS:
        raise ValueError(
            f"{TAG} slide {slide.get('n')} declares tier {tier!r}; "
            f"expected one of {', '.join(sorted(SLIDE_TIERS))}"
        )
    return tier


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


def assert_renderable(model: dict, supported: set[str] | frozenset[str], renderer: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse to render a model containing a block the renderer cannot draw. The
        alternative, dropping it, produces a deck that looks finished and is
        missing an argument.

    Inputs:
        model (dict): a parsed talk_model.json
        supported (set): block kinds this renderer implements
        renderer (str): renderer name, for the message

    Outputs:
        None. Raises RendererGap naming the renderer, the slide and the block.
    --------------------------------------------------------------------------
    """
    for slide in model.get("slides", []):
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
        Read the block kinds a Jinja template implements from its first line,
        which every renderer template in assets/ declares:

            {# supported-blocks: bullets figure takeaway ... #}

        The declaration is what lets the model refuse a render that would drop a
        block, instead of discovering the hole in the room.

    Inputs:
        template_path (str): path to the .j2 template

    Outputs:
        kinds (set): the declared block kinds; all known kinds when undeclared
    --------------------------------------------------------------------------
    """
    with open(template_path, encoding="utf8") as fh:
        head = fh.readline()
    marker = "supported-blocks:"
    if marker not in head:
        return set(BLOCK_KINDS)
    payload = head.split(marker, 1)[1].replace("#}", " ").replace("#))", " ").strip()
    return {k for k in payload.split() if k}


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


def render_template(model: dict, template_path: str, out_path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the model through a Jinja template (the Beamer and web targets),
        after checking that the template implements every block the model uses.

    Inputs:
        model (dict): a parsed talk_model.json
        template_path (str): assets/beamer_skeleton.tex.j2 or web_skeleton.html.j2
        out_path (str): destination file

    Outputs:
        out_path (str): the file written
    --------------------------------------------------------------------------
    """
    try:
        from jinja2 import Environment, FileSystemLoader
        from markupsafe import Markup
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(f"{TAG} jinja2 is required to render a template: "
                           "pip install jinja2") from exc

    folder, name = os.path.split(os.path.abspath(template_path))
    assert_renderable(model, supported_blocks(template_path), name)
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
    text = env.get_template(name).render(**model)
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
            written = render_template(model, args.render, args.out)
        except (OSError, RuntimeError, RendererGap) as exc:
            print(f"{TAG} {exc}", file=sys.stderr)
            return 2
        print(f"{TAG} rendered {args.render} -> {written}")

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
