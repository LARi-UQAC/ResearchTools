"""
cv_select.py - deterministic relevance shortlist over the CV inventory.

Stage: sits between cv_inventory.py (the data) and the drafting agent's own
judgment (the prose). This module computes ONE mechanical signal - keyword
overlap between a competition's stated objectives/evaluation criteria and
each inventory item's own keywords/title/contribution_summary - and ranks on
it. It never decides what goes in the final CV: FRQ's own instruction is
that content must be "interprété à la lumière des objectifs et des critères
d'évaluation du programme," a judgment call the agent makes after seeing
this ranking, not before. The up-to-10 cap on section 2 belongs to the
caller (contribution_types.json's sections."2".max_items), not to this
script, since sections 1 and 3 may still draw on lower-ranked items.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cv_inventory import list_items  # noqa: E402

# Small bilingual stopword list. Not exhaustive by design: this is a ranking
# SIGNAL for the agent to weigh, not a search index that must be complete.
_STOPWORDS = frozenset("""
the a an of to for and or in on with by from as is are be this that these
those it its at into which who whom
le la les un une des de du et ou pour dans sur avec par comme est sont
ce cette ces qui que quoi dont au aux en son sa ses leur leurs
""".split())

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-]{2,}")


def extract_keywords(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn free-text objectives/evaluation-criteria prose into a lowercase
        keyword set, for a mechanical overlap score.

    Inputs:
        text (str): the competition's objectives / evaluation criteria text

    Outputs:
        keywords (set of str): lowercase tokens, length >= 3, stopwords removed
    --------------------------------------------------------------------------
    """
    tokens = (m.group(0).lower() for m in _WORD_RE.finditer(text or ""))
    return {t for t in tokens if t not in _STOPWORDS}


def _item_keyword_pool(item):
    pool = set(k.lower() for k in item.get("keywords", []))
    pool |= extract_keywords(item.get("title", ""))
    pool |= extract_keywords(item.get("contribution_summary", ""))
    return pool


def score_item(item, criteria_keywords):
    """Return (score, matched_keywords) for one inventory item."""
    pool = _item_keyword_pool(item)
    matched = sorted(pool & criteria_keywords)
    return len(matched), matched


def rank_items(items, criteria_keywords):
    """
    --------------------------------------------------------------------------
    Purpose:
        Rank `items` by keyword-overlap score against `criteria_keywords`,
        descending; ties broken by date descending (most recent first), then
        by id for a fully deterministic order (R19).

    Inputs:
        items (list of dict): candidate inventory items
        criteria_keywords (set of str): from extract_keywords()

    Outputs:
        ranked (list of dict): each item plus "score" and "matched_keywords",
            sorted best-first
    --------------------------------------------------------------------------
    """
    scored = []
    for item in items:
        score, matched = score_item(item, criteria_keywords)
        entry = dict(item)
        entry["score"] = score
        entry["matched_keywords"] = matched
        scored.append(entry)
    # Descending on score and date together; id ascending only breaks a true
    # tie, so it must sort separately (a single reversed tuple would also
    # reverse id order, which is not the intent).
    scored.sort(key=lambda e: e.get("id", ""))
    scored.sort(key=lambda e: (e["score"], str(e.get("date", ""))), reverse=True)
    return scored


def select(inventory_path, criteria_text=None, keywords_csv=None, kind=None, top=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the inventory, rank it against the given criteria, and return
        the top `top` items (or all, ranked, when `top` is None).

    Inputs:
        inventory_path (str or Path): the inventory YAML
        criteria_text (str or None): objectives/evaluation-criteria prose
        keywords_csv (str or None): comma-separated explicit keywords, used
            instead of or in addition to criteria_text
        kind (str or None): "publication" or "non_publication" filter
        top (int or None): cap on the number of results

    Outputs:
        ranked (list of dict): see rank_items()
    --------------------------------------------------------------------------
    """
    criteria_keywords = set()
    if criteria_text:
        criteria_keywords |= extract_keywords(criteria_text)
    if keywords_csv:
        criteria_keywords |= {k.strip().lower() for k in keywords_csv.split(",") if k.strip()}

    items = list_items(inventory_path, kind=kind)
    ranked = rank_items(items, criteria_keywords)
    if top is not None:
        ranked = ranked[:top]
    return ranked


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--criteria-file")
    parser.add_argument("--criteria-text")
    parser.add_argument("--keywords", help="comma-separated explicit keywords")
    parser.add_argument("--kind", choices=["publication", "non_publication"])
    parser.add_argument("--top", type=int)
    args = parser.parse_args()

    criteria_text = args.criteria_text
    if args.criteria_file:
        criteria_text = (criteria_text or "") + "\n" + Path(args.criteria_file).read_text(encoding="utf-8")

    ranked = select(args.inventory, criteria_text=criteria_text, keywords_csv=args.keywords,
                     kind=args.kind, top=args.top)
    print(json.dumps(ranked, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
