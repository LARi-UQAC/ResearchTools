"""
talk_rules - the numbers a conference deck is built from.

One module holds every rule the rest of the skill computes against: the three
audience profiles, the three chrome tiers and their cost in minutes, the
content-slide formula, and the word budget. The generator, the notes measurer and
the validator all import from here, so a rule can never drift between the contract
echoed to the professor and the measurement taken on the finished deck.

Two calibrations are the professor's, 2026-08-11, and neither is negotiable inside
the skill:

    delivery rate      130 words per minute for a technical talk, not the 150 wpm
                       quoted for conversational speech. The same notes read as
                       13.0 min at 150 and 15.0 min at 130, which is a talk cut off
                       by the session chair.
    slide cadence      one slide per minute counts CONTENT slides only. Title and
                       thank-you are chrome at 20-30 s, a section divider is under
                       20 s, and references and appendix sit outside the slot.

Adopted 2026-08-12: the word budget aims at (minutes - 1.5) x wpm so the talk lands
one to two minutes under the slot, which is what conference practice advises. The
raw slot is still reported next to it.

No I/O, no dependencies. Import it, do not run it.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

TAG = "[RULES]"

# Delivery rate for a technical talk, words per minute.
DEFAULT_WPM = 130.0

# How far under the slot the word budget aims, in minutes.
DEFAULT_SAFETY_MARGIN_MIN = 1.5

# Cost of one slide of each tier, in minutes of the conference slot.
TIER_MINUTES: dict[str, float] = {
    "content": 1.0,
    "title": 0.5,
    "thanks": 0.5,
    "divider": 1.0 / 3.0,
    "backup": 0.0,
}

TIERS = tuple(TIER_MINUTES)

# Audience profiles. Question 1 of the opening round selects one, and it
# parameterises typography, density, equation policy and cadence. The 20 pt floor
# and the bullet cap are executive and marketing conventions; they hold only for
# the general-public column, because in an in-field talk they force out exactly the
# detail the audience came for.
AUDIENCES: dict[str, dict] = {
    "field": {
        "label": "scientists in the field",
        "font_floor_pt": 16.0,
        "caption_floor_pt": 14.0,
        "words_per_content_slide": 130.0,
        "bullet_cap": None,           # the gate is legibility and overflow, not a count
        "equations": "allowed in quantity; 7 to 8 on one slide is legitimate when each "
                     "is labelled and cited",
        "jargon": "field terms used directly",
        "method_detail": "full, including parameter values",
        "citation_density": "on every borrowed figure and every borrowed claim",
        "cadence": "may exceed one slide per minute when the deck is equation-dense",
        "preferred_form": ("figure", "table", "equation", "prose"),
    },
    "academic": {
        "label": "academics outside the field",
        "font_floor_pt": 16.0,
        "caption_floor_pt": 14.0,
        "words_per_content_slide": 130.0,
        "bullet_cap": 5,
        "equations": "one or two, each also stated in words",
        "jargon": "expanded on first use",
        "method_detail": "the shape of the method",
        "citation_density": "on figures",
        "cadence": "one slide per minute",
        "preferred_form": ("figure", "table", "equation", "prose"),
    },
    "public": {
        "label": "general public and media",
        "font_floor_pt": 20.0,
        "caption_floor_pt": 18.0,
        "words_per_content_slide": 115.0,
        "bullet_cap": 5,
        "equations": "none; state the mechanism in words",
        "jargon": "avoided or replaced",
        "method_detail": "the intuition only",
        "citation_density": "a source line only",
        "cadence": "slower than one slide per minute",
        "preferred_form": ("figure", "table", "prose"),
    },
}

# The content hierarchy, highest first. A picture is worth a thousand words
# (professor's rule, 2026-08-11): prose, and that includes bullets, is the last
# resort rather than the default.
CONTENT_HIERARCHY = ("figure", "table", "equation", "prose")

# Slide sizes in inches, keyed by the aspect answer. 9:16 is portrait, not a typo
# for 16:9, and no lab gabarit ships a background for it.
ASPECTS: dict[str, tuple[float, float]] = {
    "4:3": (10.0, 7.5),
    "16:9": (13.333, 7.5),
    "9:16": (7.5, 13.333),
}


def word_count(text: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the words a presenter actually says. Shared by the model and by the
        measurement taken on the built deck, so a budget computed at authoring
        time and the one measured afterwards cannot disagree over what a word is.

    Inputs:
        text (str): speaker notes, already stripped of placeholders

    Outputs:
        n (int): whitespace-separated tokens; a bare number counts as one word
    --------------------------------------------------------------------------
    """
    return len([w for w in re.split(r"\s+", text or "") if w.strip()])


def audience_profile(name: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve an audience answer to its rule set, failing loudly on a name the
        skill does not define rather than silently applying the in-field rules.

    Inputs:
        name (str): field, academic, or public

    Outputs:
        profile (dict): the entry of AUDIENCES, including font_floor_pt
    --------------------------------------------------------------------------
    """
    key = (name or "").strip().lower()
    if key not in AUDIENCES:
        raise ValueError(
            f"{TAG} unknown audience {name!r}; expected one of {', '.join(AUDIENCES)}"
        )
    return AUDIENCES[key]


def content_slide_allowance(
    minutes: float, n_title: int = 1, n_thanks: int = 1, n_dividers: int = 0
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply the three-tier cadence formula: how many content slides fit a slot
        once the chrome has been paid for.

            n_content = floor(minutes - 0.5*(title + thanks) - 0.33*n_dividers)

    Inputs:
        minutes (float): the conference slot
        n_title (int): number of title slides, normally 1
        n_thanks (int): number of thank-you slides, 0 when the deck ends on
            the conclusions slide
        n_dividers (int): number of section-transition slides

    Outputs:
        n_content (int): content slides the slot affords, never below zero
    --------------------------------------------------------------------------
    """
    spent = (
        TIER_MINUTES["title"] * n_title
        + TIER_MINUTES["thanks"] * n_thanks
        + TIER_MINUTES["divider"] * n_dividers
    )
    return max(0, math.floor(minutes - spent))


def deck_shape(
    minutes: float, n_title: int = 1, n_thanks: int = 1, n_dividers: int = 0,
    n_backup: int = 0,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the whole shape of a deck for a slot, so the professor sees that a
        divider-bearing deck runs fewer content slides and more slides overall.

    Inputs:
        minutes (float): the conference slot
        n_title, n_thanks, n_dividers, n_backup (int): chrome counts

    Outputs:
        shape (dict): n_content, n_total, chrome_minutes, and the counts given
    --------------------------------------------------------------------------
    """
    n_content = content_slide_allowance(minutes, n_title, n_thanks, n_dividers)
    chrome = (
        TIER_MINUTES["title"] * n_title
        + TIER_MINUTES["thanks"] * n_thanks
        + TIER_MINUTES["divider"] * n_dividers
    )
    return {
        "minutes": minutes,
        "n_title": n_title,
        "n_thanks": n_thanks,
        "n_dividers": n_dividers,
        "n_backup": n_backup,
        "n_content": n_content,
        "chrome_minutes": chrome,
        "n_total": n_content + n_title + n_thanks + n_dividers + n_backup,
    }


def word_budget(
    minutes: float,
    wpm: float = DEFAULT_WPM,
    safety_margin_min: float = DEFAULT_SAFETY_MARGIN_MIN,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a slot into the two word totals the deck is measured against: the
        safe target the notes should hit, and the raw slot they must not exceed.

    Inputs:
        minutes (float): the conference slot
        wpm (float): delivery rate, 130 for a technical talk
        safety_margin_min (float): how far under the slot to aim; 0 targets the
            full slot, which is the CASE 2026 behaviour

    Outputs:
        budget (dict): target_words, slot_words, target_minutes, wpm, margin
    --------------------------------------------------------------------------
    """
    target_minutes = max(0.0, minutes - max(0.0, safety_margin_min))
    return {
        "wpm": wpm,
        "slot_minutes": minutes,
        "target_minutes": target_minutes,
        "safety_margin_min": safety_margin_min,
        "slot_words": minutes * wpm,
        "target_words": target_minutes * wpm,
    }


def tier_words(tier: str, wpm: float = DEFAULT_WPM) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        The per-slide word target of one tier, which is its minute cost times the
        delivery rate: 130 for content, 65 for title or thank-you, 43 for a
        divider, 0 for anything outside the slot.

    Inputs:
        tier (str): content, title, thanks, divider, or backup
        wpm (float): delivery rate

    Outputs:
        words (float): the target word count for one slide of that tier
    --------------------------------------------------------------------------
    """
    if tier not in TIER_MINUTES:
        raise ValueError(f"{TAG} unknown tier {tier!r}; expected one of {', '.join(TIERS)}")
    return TIER_MINUTES[tier] * wpm


def aspect_size_in(aspect: str) -> tuple[float, float]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve an aspect answer to a canvas in inches. The PDF paper format is a
        separate question and never changes this number: reflow happens after
        rendering, because resizing the slide stretches a branded background.

    Inputs:
        aspect (str): 4:3, 16:9, or 9:16

    Outputs:
        size (tuple): width and height in inches
    --------------------------------------------------------------------------
    """
    key = (aspect or "").strip()
    if key not in ASPECTS:
        raise ValueError(f"{TAG} unknown aspect {aspect!r}; expected one of {', '.join(ASPECTS)}")
    return ASPECTS[key]


def preferred_form(audience: str, available: Iterable[str]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pick the strongest form available for a point, following the content
        hierarchy of the audience profile. Used when the same statement could be
        a figure, a table, an equation or a sentence.

    Inputs:
        audience (str): field, academic, or public
        available (iterable): candidate forms for this point

    Outputs:
        form (str): the highest-ranked available form, "prose" as the last resort
    --------------------------------------------------------------------------
    """
    ranking = audience_profile(audience)["preferred_form"]
    have = {str(f).lower() for f in available}
    for form in ranking:
        if form in have:
            return form
    return "prose"


def build_contract(
    audience: str,
    minutes: float,
    target: str,
    aspect: str,
    paper: str,
    n_title: int = 1,
    n_thanks: int = 1,
    n_dividers: int = 0,
    n_backup: int = 0,
    wpm: float = DEFAULT_WPM,
    safety_margin_min: float = DEFAULT_SAFETY_MARGIN_MIN,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute the build contract echoed to the professor before a single slide
        is authored. A contract that later disagrees with what talk_notes.py and
        talk_validate.py measure is a bug in one of the two, not a rounding
        difference to wave through.

    Inputs:
        audience (str): field, academic, or public
        minutes (float): the conference slot
        target (str): pptx, beamer, or web
        aspect (str): 4:3, 16:9, or 9:16
        paper (str): slide, a4, or letter
        n_title, n_thanks, n_dividers, n_backup (int): chrome counts
        wpm (float), safety_margin_min (float): delivery calibration

    Outputs:
        contract (dict): shape, budget, font floors, form ranking, equation policy
    --------------------------------------------------------------------------
    """
    profile = audience_profile(audience)
    shape = deck_shape(minutes, n_title, n_thanks, n_dividers, n_backup)
    budget = word_budget(minutes, wpm, safety_margin_min)
    w, h = aspect_size_in(aspect)
    return {
        "audience": audience,
        "audience_label": profile["label"],
        "target": target,
        "aspect": aspect,
        "canvas_in": {"w": w, "h": h},
        "paper": paper,
        "shape": shape,
        "budget": budget,
        "font_floor_pt": profile["font_floor_pt"],
        "caption_floor_pt": profile["caption_floor_pt"],
        "words_per_content_slide": profile["words_per_content_slide"],
        "equations": profile["equations"],
        "preferred_form": list(profile["preferred_form"]),
    }


def format_contract(contract: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render a build contract as the short block the agent shows the professor.
        Five lines, because a misunderstanding caught here costs a message and
        caught after twelve slides exist costs the whole build.

    Inputs:
        contract (dict): the output of build_contract

    Outputs:
        text (str): the block, without a trailing newline
    --------------------------------------------------------------------------
    """
    s, b = contract["shape"], contract["budget"]
    head = (
        f"audience {contract['audience']} | {s['minutes']:g} min | "
        f"{contract['target']} | {contract['aspect']} | {contract['paper']}"
    )
    lines = [
        head,
        f"  -> n_content   = {s['n_content']}  "
        f"(title {s['n_title']}, thanks {s['n_thanks']}, dividers {s['n_dividers']}, "
        f"backup {s['n_backup']}; total {s['n_total']})",
        f"  -> words       = {b['target_words']:.0f} aimed "
        f"({b['target_minutes']:g} min at {b['wpm']:.0f} wpm), "
        f"{b['slot_words']:.0f} is the raw slot",
        f"  -> font floor  = {contract['font_floor_pt']:g} pt body, "
        f"{contract['caption_floor_pt']:g} pt captions and references",
        f"  -> form        = {' > '.join(contract['preferred_form'])}; "
        f"equations: {contract['equations']}",
    ]
    return "\n".join(lines)
