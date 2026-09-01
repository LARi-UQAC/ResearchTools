"""
talk_notes - measure the spoken length of a deck's speaker notes.

A conference talk is a time budget, not a slide count. This script turns the notes
already inside a .pptx into numbers: words per slide, seconds per slide, drift
against the per-slide and per-section targets, the slide cadence, and whether every
exhibit on a slide is actually discussed in that slide's notes. It never edits the
deck.

Rate: 130 words per minute (professor's calibration, 2026-08-11). That is a measured
delivery rate for a technical talk, not the 150 wpm quoted for conversational
speech; the same notes read as 13.0 min at 150 and 15.0 min at 130.

Budget model, three chrome tiers (see talk_rules.py):

    content slide            1.00 min  ->  130 words
    title, thank-you         0.50 min  ->   65 words   (20-30 s)
    section transition       0.33 min  ->   43 words   (10-20 s)
    references, appendix     0.00 min  ->    0 words   (never traversed in the slot)

    n_content = floor(minutes - 0.5*(title+thanks) - 0.33*n_transitions)

The word budget aims at (minutes - 1.5) x wpm by default, so the talk lands one to
two minutes under the slot; the raw slot is reported next to it. `--safety-margin 0`
targets the full slot.

Notes are mapped to slides through ppt/slides/_rels/*.rels, never by matching
notesSlideN to slideN: PowerPoint does not guarantee the two numberings agree, and a
deck edited by hand routinely has them shuffled.

Usage
-----
    python talk_notes.py deck.pptx --minutes 13
    python talk_notes.py deck.pptx --minutes 13 --title 1 --divider 2 --thanks 15 --backup 16
    python talk_notes.py deck.pptx --minutes 13 --model talk_model.json --tolerance 5

budget.json (optional), section name -> slides, target in minutes or words:

    {
      "Introduction": {"slides": [1, 2, 3, 4], "target_minutes": 2.5},
      "Objective":    {"slides": [5],          "target_minutes": 1.0}
    }

Exit codes: 0 all within tolerance, 1 a section or the total drifts beyond it,
2 a usage or file error. Uncovered exhibits and an over-budget slide count are
warnings, not failures: an equation-dense in-field deck may legitimately run faster
than a minute a slide, and that is the professor's call to make with the number in
front of him.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile

import talk_rules as rules
from talk_rules import word_count as _raw_word_count

TAG = "[NOTES]"

# Structured speaker notes carry section labels. They are scaffolding for the
# speaker, not words anybody says, so they are stripped before the count - the
# alternative is a deck that reads two minutes long because of its own headings.
NOTE_LABELS = (
    "WHAT TO SAY", "KEY POINT", "TIMING", "TRANSITION", "ANTICIPATED QUESTIONS",
    "CE QUE JE DIS", "POINT CLE", "MINUTAGE", "TRANSITION", "QUESTIONS ATTENDUES",
)
_RE_NOTE_LABEL = re.compile(
    r"^\s*(?:" + "|".join(re.escape(lbl) for lbl in NOTE_LABELS) + r")\s*:",
    re.I | re.M,
)


def word_count(text: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the words the speaker actually says, ignoring the labels of the
        structured notes template.

    Inputs:
        text (str): the notes of one slide

    Outputs:
        n (int): spoken word count
    --------------------------------------------------------------------------
    """
    return _raw_word_count(_RE_NOTE_LABEL.sub(" ", text or ""))

TIER_MINUTES = rules.TIER_MINUTES

_RE_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_RE_NOTES_TARGET = re.compile(r'Target="\.\./(notesSlides/notesSlide\d+\.xml)"')
_RE_FLD = re.compile(r"<a:fld\b.*?</a:fld>", re.S)
_RE_TEXT = re.compile(r"<a:t>(.*?)</a:t>", re.S)
_RE_PARA = re.compile(r"</a:p>")
_RE_PIC = re.compile(r"<p:pic\b")
_RE_FRAME = re.compile(r"<p:graphicFrame\b")
_RE_SUBSUP = re.compile(r'<a:rPr\b[^>]*\b(?:baseline="-?\d+"|sub|sup)\b')

_ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"))


def _unescape(s: str) -> str:
    for a, b in _ENTITIES:
        s = s.replace(a, b)
    return s


def notes_by_slide(path: str) -> dict[int, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map slide number to notes text, resolved through the relationship parts.
        The slide-number placeholder lives in an <a:fld> and is dropped, or every
        slide reads one word long.

    Inputs:
        path (str): path to the .pptx

    Outputs:
        notes (dict): slide number -> notes text, "" when a slide has none
    --------------------------------------------------------------------------
    """
    out: dict[int, str] = {}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        slides = sorted(
            (int(m.group(1)) for m in (_RE_SLIDE.match(n) for n in names) if m)
        )
        for n in slides:
            rels = f"ppt/slides/_rels/slide{n}.xml.rels"
            if rels not in names:
                out[n] = ""
                continue
            m = _RE_NOTES_TARGET.search(z.read(rels).decode("utf8"))
            if not m:
                out[n] = ""
                continue
            part = "ppt/" + m.group(1)
            if part not in names:
                out[n] = ""
                continue
            xml = z.read(part).decode("utf8")
            # Drop <a:fld> entirely: it carries the slide-number placeholder, whose
            # digits would otherwise be counted as a spoken word.
            xml = _RE_FLD.sub("", xml)
            # Paragraph breaks become spaces so two paragraphs do not fuse into one word.
            xml = _RE_PARA.sub(" </a:p>", xml)
            out[n] = _unescape(" ".join(_RE_TEXT.findall(xml))).strip()
    return out


def exhibits_by_slide(path: str) -> dict[int, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List what each slide shows: a picture, a chart or table frame, or a run
        formatted as a sub/superscript, which is how an equation is faked when the
        renderer has no LaTeX. This feeds the say-what-you-show check.

    Inputs:
        path (str): path to the .pptx

    Outputs:
        exhibits (dict): slide number -> list of kinds ("picture", "frame", "equation")
    --------------------------------------------------------------------------
    """
    out: dict[int, list[str]] = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            m = _RE_SLIDE.match(name)
            if not m:
                continue
            xml = z.read(name).decode("utf8")
            found = []
            found += ["picture"] * len(_RE_PIC.findall(xml))
            found += ["frame"] * len(_RE_FRAME.findall(xml))
            if _RE_SUBSUP.search(xml):
                found.append("equation")
            out[int(m.group(1))] = found
    return out


def coverage_warnings(
    notes: dict[int, str], exhibits: dict[int, list[str]], model: dict | None
) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enforce "say what you show": everything presented visually must be
        discussed orally. Matching is on subject keywords declared in the model,
        never on a filename, because no speaker reads a filename out loud.

    Inputs:
        notes (dict): slide number -> notes text
        exhibits (dict): slide number -> exhibit kinds present in the slide XML
        model (dict): a parsed talk_model.json, or None when there is no model

    Outputs:
        warnings (list): one line per exhibit that no notes text addresses
    --------------------------------------------------------------------------
    """
    warnings: list[str] = []
    keywords: dict[int, list[tuple[str, list[str]]]] = {}
    if model:
        for slide in model.get("slides", []):
            n = slide.get("n")
            entries = []
            for block in slide.get("blocks", []):
                if block.get("kind") in {"figure", "table", "chart", "matrix",
                                         "zoneband", "equation"}:
                    keys = [str(k).strip().lower() for k in (block.get("keywords") or [])]
                    entries.append((block.get("kind"), keys))
            if entries:
                keywords[n] = entries

    for n, kinds in sorted(exhibits.items()):
        if not kinds:
            continue
        text = (notes.get(n) or "").lower()
        if not text:
            warnings.append(f"{TAG} slide {n} shows {len(kinds)} exhibit(s) and has no notes")
            continue
        for kind, keys in keywords.get(n, []):
            if not keys:
                warnings.append(
                    f"{TAG} slide {n} exhibit {kind} declares no keywords in the model, "
                    "so coverage cannot be checked"
                )
            elif not any(k in text for k in keys):
                warnings.append(
                    f"{TAG} slide {n} exhibit {kind} is never discussed in its own notes "
                    f"(looked for {', '.join(keys)})"
                )
    return warnings


def parse_slide_list(spec: str | None) -> set[int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a tier declaration such as "3,7,12" or "14-16" into slide numbers.

    Inputs:
        spec (str): comma-separated numbers and ranges, or None

    Outputs:
        slides (set): the slide numbers named
    --------------------------------------------------------------------------
    """
    if not spec:
        return set()
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def tiers_from_model(model: dict) -> dict[str, set[int]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read each slide's declared tier out of talk_model.json, so the tiers never
        have to be typed twice or inferred from a slide's position.

    Inputs:
        model (dict): a parsed talk_model.json

    Outputs:
        tiers (dict): tier name -> set of slide numbers (content is left implicit)
    --------------------------------------------------------------------------
    """
    tiers: dict[str, set[int]] = {"title": set(), "thanks": set(),
                                  "divider": set(), "backup": set()}
    for slide in model.get("slides", []):
        kind = str(slide.get("kind", "content")).strip().lower()
        if kind in tiers:
            tiers[kind].add(slide.get("n"))
    return tiers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure the spoken length of a deck's notes.")
    ap.add_argument("deck")
    ap.add_argument("--minutes", type=float, required=True, help="conference slot, in minutes")
    ap.add_argument("--wpm", type=float, default=rules.DEFAULT_WPM,
                    help="delivery rate (default 130, the technical-talk rate)")
    ap.add_argument("--safety-margin", type=float, default=rules.DEFAULT_SAFETY_MARGIN_MIN,
                    help="minutes to land under the slot (default 1.5; 0 targets the slot)")
    ap.add_argument("--title", default="", help="slide numbers of title slides, e.g. 1")
    ap.add_argument("--thanks", default="", help="slide numbers of thank-you slides")
    ap.add_argument("--divider", default="", help="section transition slides, e.g. 2,7,12")
    ap.add_argument("--backup", default="", help="references/appendix slides, outside the slot")
    ap.add_argument("--model", help="talk_model.json: read the tiers and exhibit keywords")
    ap.add_argument("--budget", help="JSON file mapping sections to slides and targets")
    ap.add_argument("--tolerance", type=float, default=5.0, help="allowed drift in percent")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output only")
    args = ap.parse_args(argv)

    try:
        notes = notes_by_slide(args.deck)
        shown = exhibits_by_slide(args.deck)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"{TAG} cannot read {args.deck}: {exc}", file=sys.stderr)
        return 2
    if not notes:
        print(f"{TAG} no slides found in {args.deck}", file=sys.stderr)
        return 2

    model = None
    if args.model:
        try:
            with open(args.model, encoding="utf8") as fh:
                model = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{TAG} cannot read {args.model}: {exc}", file=sys.stderr)
            return 2

    tiers = {
        "title": parse_slide_list(args.title),
        "thanks": parse_slide_list(args.thanks),
        "divider": parse_slide_list(args.divider),
        "backup": parse_slide_list(args.backup),
    }
    if model and not any(tiers.values()):
        tiers = tiers_from_model(model)

    overlap = [n for n in notes for a in tiers for b in tiers
               if a < b and n in tiers[a] and n in tiers[b]]
    if overlap:
        print(f"{TAG} slide(s) {sorted(set(overlap))} declared in two tiers", file=sys.stderr)
        return 2

    def tier_of(n: int) -> str:
        for name, members in tiers.items():
            if n in members:
                return name
        return "content"

    rows = []
    for n in sorted(notes):
        t = tier_of(n)
        w = word_count(notes[n])
        target = rules.tier_words(t, args.wpm)
        rows.append(
            {
                "slide": n,
                "tier": t,
                "words": w,
                "seconds": w / args.wpm * 60.0,
                "target_words": target,
                "drift_pct": (100.0 * (w - target) / target) if target else None,
            }
        )

    n_content = sum(1 for r in rows if r["tier"] == "content")
    n_div = len(tiers["divider"])
    n_cap = len(tiers["title"]) + len(tiers["thanks"])
    allowed = rules.content_slide_allowance(
        args.minutes, len(tiers["title"]), len(tiers["thanks"]), n_div
    )
    budget = rules.word_budget(args.minutes, args.wpm, args.safety_margin)
    in_slot = [r for r in rows if r["tier"] != "backup"]
    total_words = sum(r["words"] for r in in_slot)
    total_min = total_words / args.wpm
    content_words = sum(r["words"] for r in rows if r["tier"] == "content")

    sections = []
    if args.budget:
        with open(args.budget, encoding="utf8") as fh:
            spec = json.load(fh)
        for name, cfg in spec.items():
            ids = cfg.get("slides", [])
            tw = cfg.get("target_words")
            if tw is None and cfg.get("target_minutes") is not None:
                tw = cfg["target_minutes"] * args.wpm
            got = sum(word_count(notes.get(i, "")) for i in ids)
            sections.append(
                {
                    "section": name,
                    "slides": ids,
                    "words": got,
                    "target_words": tw,
                    "drift_pct": (100.0 * (got - tw) / tw) if tw else None,
                }
            )

    warnings = coverage_warnings(notes, shown, model)

    result = {
        "deck": args.deck,
        "wpm": args.wpm,
        "slot_minutes": args.minutes,
        "target_minutes": budget["target_minutes"],
        "target_words": budget["target_words"],
        "slides": rows,
        "sections": sections,
        "cadence": {
            "n_content": n_content,
            "n_title_thanks": n_cap,
            "n_divider": n_div,
            "n_backup": len(tiers["backup"]),
            "content_allowed": allowed,
            "content_words": content_words,
            "seconds_per_content_slide": (content_words / n_content / args.wpm * 60.0)
            if n_content
            else 0.0,
        },
        "exhibit_warnings": warnings,
        "total_words": total_words,
        "total_minutes": total_min,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{TAG} {args.deck}  rate {args.wpm:.0f} wpm  slot {args.minutes:g} min  "
              f"aim {budget['target_minutes']:g} min ({budget['target_words']:.0f} words)")
        print(f"{TAG} {'slide':>5} {'tier':<8} {'words':>6} {'sec':>6} {'target':>7} {'drift':>8}")
        for r in rows:
            d = "-" if r["drift_pct"] is None else f"{r['drift_pct']:+.0f}%"
            print(
                f"{TAG} {r['slide']:>5} {r['tier']:<8} {r['words']:>6} "
                f"{r['seconds']:>6.0f} {r['target_words']:>7.0f} {d:>8}"
            )
        if sections:
            print(f"{TAG}")
            for s in sections:
                d = "-" if s["drift_pct"] is None else f"{s['drift_pct']:+.1f}%"
                print(
                    f"{TAG} {s['section']:<28} {s['words']:>5} / "
                    f"{(s['target_words'] or 0):>5.0f}  drift {d:>8}"
                )
        c = result["cadence"]
        print(f"{TAG}")
        print(
            f"{TAG} cadence: {c['n_content']} content, {c['n_title_thanks']} title/thanks, "
            f"{c['n_divider']} divider, {c['n_backup']} backup"
        )
        print(
            f"{TAG}   allowed content slides = floor({args.minutes:g} - "
            f"0.5*{c['n_title_thanks']} - 0.33*{c['n_divider']}) = {c['content_allowed']}"
            f"  -> {'OK' if c['n_content'] <= c['content_allowed'] else 'OVER (warning)'}"
        )
        print(
            f"{TAG}   {c['content_words']} words over {c['n_content']} content slides = "
            f"{c['seconds_per_content_slide']:.0f} s each"
        )
        if warnings:
            print(f"{TAG}")
            for line in warnings:
                print(line)
        print(f"{TAG}")
        print(
            f"{TAG} TOTAL {total_words} words in the slot -> {total_min:.2f} min "
            f"(aim {budget['target_minutes']:g}, slot {args.minutes:g}, drift vs slot "
            f"{100.0 * (total_min - args.minutes) / args.minutes:+.1f}%)"
        )

    bad = [s["section"] for s in sections
           if s["drift_pct"] is not None and abs(s["drift_pct"]) > args.tolerance]
    aim = budget["target_minutes"] or args.minutes
    over_total = abs(100.0 * (total_min - aim) / aim) > args.tolerance
    if bad or over_total:
        if not args.json:
            if bad:
                print(f"{TAG} FAIL sections beyond {args.tolerance:g}%: {', '.join(bad)}",
                      file=sys.stderr)
            if over_total:
                print(f"{TAG} FAIL total beyond {args.tolerance:g}% of the {aim:g} min aim",
                      file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
