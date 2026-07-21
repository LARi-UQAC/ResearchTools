"""
litreview_update.py - Deterministic delta and merge bookkeeping for the
incremental literature-review update (the litreview-updater agent, /litupdate).

A prior /litreview run (scopus-researcher) leaves the persisted corpus state a
refresh can diff against: corpus.json (citekey -> {doi, title, ...}), review.bib,
and the review .tex (which carries the "Prochaine mise a jour" date). This script
owns only the mechanical parts of an update so the agent keeps the judgment:

  baseline   parse the existing review into {dois, citekeys, titles, next_update}
  delta      drop the fresh Scopus/Consensus candidates already in the baseline
             (DOI exact, else title Jaccard via bib_batch.title_match), keeping
             only the genuinely new papers as a candidates.json for bib_batch
  changelog  compute the dated, track-changed output paths and scaffold the
             CHANGELOG (with a REVIEW REQUIRED section for the human gates)

It never calls the network; enrichment, grading, PDF retrieval, mining, and the
LaTeX merge are done by the reused scripts/skills and the agent. The title match
and the 0.6 Jaccard threshold are reused from bib_batch so the update dedups
exactly the way the original run resolved titles.

Usage:
  python litreview_update.py baseline  <review.tex> [--corpus corpus.json] [--bib review.bib] [--out baseline.json]
  python litreview_update.py delta     <candidates.json> --baseline baseline.json [--out delta_candidates.json]
  python litreview_update.py changelog <delta_corpus.json> --review <review.tex> [--date YYYYMMDD] [--out <auto>]
"""

import argparse
import datetime
import json
import logging
import os
import re
from typing import Any

# Reuse the exact title matcher and Jaccard threshold the original run used to
# resolve titles, so an update dedups new hits the same way (same file dir).
import bib_batch  # noqa: E402  (sibling script; no network at import)

logger = logging.getLogger(__name__)

# Reproducibility-metadata line written by scopus-researcher Step 15, e.g.
# "Prochaine mise a jour recommandee : 2027-01-15". Accent-insensitive, tolerant
# of an optional colon and surrounding LaTeX; captures an ISO date anywhere after.
_NEXT_UPDATE_RE = re.compile(
    r"[Pp]rochaine\s+mise\s+[aà]\s+jour[^0-9]{0,40}(\d{4}-\d{2}-\d{2})")
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
_BIB_DOI_RE = re.compile(r"\bdoi\s*=\s*[{\"]([^}\"]+)[}\"]", re.IGNORECASE)
_BIB_TITLE_RE = re.compile(r"\btitle\s*=\s*\{([^}]*)\}", re.IGNORECASE)


def _norm_doi(doi: Any) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Canonicalize a DOI for set comparison: strip any resolver prefix, lower
        case, and trim, so "https://doi.org/10.1/X" and "10.1/x" compare equal.

    Inputs:
        doi (Any): a raw DOI string (or anything; non-strings become "").

    Outputs:
        doi (str): the bare lowercased DOI, or "" when absent.
    --------------------------------------------------------------------------
    """
    text = str(doi or "").strip().lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    return text.strip()


def parse_bib(path: str) -> dict[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the citekeys, DOIs, and titles from a .bib file with a light
        regex pass (no BibTeX parser dependency), for baseline dedup.

    Inputs:
        path (str): path to a .bib file; a missing file yields empty lists.

    Outputs:
        parsed (dict): {"citekeys": [...], "dois": [...], "titles": [...]}.
    --------------------------------------------------------------------------
    """
    if not path or not os.path.isfile(path):
        return {"citekeys": [], "dois": [], "titles": []}
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return {
        "citekeys": _BIB_KEY_RE.findall(text),
        "dois": [_norm_doi(d) for d in _BIB_DOI_RE.findall(text)],
        "titles": [t.strip() for t in _BIB_TITLE_RE.findall(text) if t.strip()],
    }


def extract_next_update_date(tex_text: str) -> str | None:
    """Return the ISO 'Prochaine mise a jour' date from a review .tex, or None."""
    match = _NEXT_UPDATE_RE.search(tex_text or "")
    return match.group(1) if match else None


def build_baseline(review_tex: str, corpus_path: str | None,
                   bib_path: str | None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Assemble the baseline corpus fingerprint an update diffs against: every
        DOI, citekey, and title already covered by the review, plus the last
        recommended-update date. corpus.json (when present) is authoritative for
        DOIs; the .bib is merged in as a fallback / cross-check.

    Inputs:
        review_tex (str): path to the existing review .tex.
        corpus_path (str | None): the run's corpus.json, if it exists.
        bib_path (str | None): the run's review.bib, if it exists.

    Outputs:
        baseline (dict): {review_tex, dois, citekeys, titles, next_update_date,
                          run_date}. Lists are deduplicated and sorted.
    --------------------------------------------------------------------------
    """
    dois: set[str] = set()
    citekeys: set[str] = set()
    titles: set[str] = set()

    if corpus_path and os.path.isfile(corpus_path):
        with open(corpus_path, encoding="utf-8") as handle:
            corpus = json.load(handle)
        for key, record in (corpus or {}).items():
            citekeys.add(key)
            if isinstance(record, dict):
                if record.get("doi"):
                    dois.add(_norm_doi(record["doi"]))
                for field in ("title", "query_title"):
                    if record.get(field):
                        titles.add(str(record[field]).strip())

    parsed_bib = parse_bib(bib_path) if bib_path else {"citekeys": [], "dois": [], "titles": []}
    dois.update(d for d in parsed_bib["dois"] if d)
    citekeys.update(parsed_bib["citekeys"])
    titles.update(parsed_bib["titles"])

    next_update = None
    if review_tex and os.path.isfile(review_tex):
        with open(review_tex, encoding="utf-8") as handle:
            next_update = extract_next_update_date(handle.read())

    return {
        "review_tex": review_tex,
        "dois": sorted(dois),
        "citekeys": sorted(citekeys),
        "titles": sorted(titles),
        "next_update_date": next_update,
        "run_date": datetime.date.today().isoformat(),
    }


def is_duplicate(candidate: dict[str, Any], baseline_dois: set[str],
                 baseline_titles: list[str]) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a fresh candidate is already in the review: DOI exact
        match first (cheap, authoritative), then a title match against every
        baseline title via bib_batch.title_match (the same 0.6 Jaccard the
        original run used), which catches DOI-less hits and preprint/version
        duplicates.

    Inputs:
        candidate (dict): a fresh hit ({key, source, title, doi?}).
        baseline_dois (set[str]): normalized baseline DOIs.
        baseline_titles (list[str]): baseline titles.

    Outputs:
        duplicate (bool): True when the candidate is already covered.
    --------------------------------------------------------------------------
    """
    doi = _norm_doi(candidate.get("doi"))
    if doi and doi in baseline_dois:
        return True
    title = candidate.get("title") or ""
    if not title:
        return False
    return any(bib_batch.title_match(title, known) for known in baseline_titles)


def compute_delta(candidates: list[dict[str, Any]],
                  baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return only the candidates not already in the baseline, also
        deduplicating within the fresh list itself (two hits on the same DOI or
        title collapse to the first), preserving input order.

    Inputs:
        candidates (list[dict]): fresh {key, source, title, doi?} hits.
        baseline (dict): output of build_baseline.

    Outputs:
        delta (list[dict]): the genuinely new candidates, in candidates.json form.
    --------------------------------------------------------------------------
    """
    baseline_dois = set(baseline.get("dois", []))
    seen_titles: list[str] = list(baseline.get("titles", []))
    delta: list[dict[str, Any]] = []
    for cand in candidates:
        if is_duplicate(cand, baseline_dois, seen_titles):
            continue
        delta.append(cand)
        # Fold the accepted candidate into the running seen-set so a second copy
        # later in the same batch is dropped as a within-list duplicate.
        doi = _norm_doi(cand.get("doi"))
        if doi:
            baseline_dois.add(doi)
        if cand.get("title"):
            seen_titles.append(cand["title"])
    return delta


def dated_paths(review_tex: str, date: str | None = None) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Derive the dated, track-changed output paths for an update run:
        <basename>_up_YYYYMMDD.tex, its CHANGELOG, and the best-guess .bib to
        append to (review.bib next to the .tex, else <basename>.bib).

    Inputs:
        review_tex (str): path to the existing review .tex.
        date (str | None): YYYYMMDD stamp; defaults to today.

    Outputs:
        paths (dict): {date, updated_tex, changelog, bib}.
    --------------------------------------------------------------------------
    """
    stamp = date or datetime.date.today().strftime("%Y%m%d")
    directory = os.path.dirname(review_tex)
    base = os.path.splitext(os.path.basename(review_tex))[0]
    prefix = os.path.join(directory, f"{base}_up_{stamp}")
    review_bib = os.path.join(directory, "review.bib")
    same_base_bib = os.path.join(directory, f"{base}.bib")
    bib = review_bib if os.path.isfile(review_bib) else (
        same_base_bib if os.path.isfile(same_base_bib) else review_bib)
    return {
        "date": stamp,
        "updated_tex": f"{prefix}.tex",
        "changelog": f"{prefix}_CHANGELOG.md",
        "bib": bib,
    }


def build_changelog(delta_corpus: dict[str, dict[str, Any]], review_tex: str,
                    date: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Scaffold the CHANGELOG markdown for an update run: a table of the new
        papers (grade, publisher, DOI) and a REVIEW REQUIRED section listing the
        human-gate items (non-approved publisher, unresolved venue, no DOI).
        An empty delta yields an explicit "no update needed" note instead.

    Inputs:
        delta_corpus (dict): enriched delta corpus keyed by citekey.
        review_tex (str): the existing review .tex (for the header path).
        date (str | None): YYYYMMDD stamp; defaults to today.

    Outputs:
        changelog (str): the CHANGELOG markdown body.
    --------------------------------------------------------------------------
    """
    paths = dated_paths(review_tex, date)
    header = (f"# Literature-review update - {paths['date']}\n\n"
              f"- Source review: `{review_tex}`\n"
              f"- Updated copy: `{paths['updated_tex']}`\n"
              f"- BibTeX appended: `{paths['bib']}`\n\n")

    if not delta_corpus:
        return header + ("## Result\n\nNo new papers found in the search window. "
                         "The review is up to date; bump the next-update date and "
                         "leave the source .tex unchanged.\n")

    rows = ["| Citekey | Year | Grade | Publisher | Approved | DOI |",
            "|---|---|---|---|---|---|"]
    review_required: list[str] = []
    for key, record in sorted(delta_corpus.items()):
        grade = record.get("grade", "?")
        publisher = record.get("publisher_guess") or record.get("publisher") or "?"
        approved = record.get("publisher_approved", False)
        doi = record.get("doi", "")
        rows.append(f"| {key} | {str(record.get('year', ''))[:4]} | {grade} | "
                    f"{publisher} | {'yes' if approved else 'NO'} | {doi} |")
        if not record.get("found") or not doi:
            review_required.append(f"- `{key}`: unresolved (no Scopus DOI match) - verify before inclusion")
        elif not approved or grade == "?":
            review_required.append(f"- `{key}`: publisher `{publisher}` not on the approved list "
                                   f"(grade {grade}) - professor approval required")

    body = header + "## New papers\n\n" + "\n".join(rows) + "\n\n"
    body += "## REVIEW REQUIRED\n\n"
    body += ("\n".join(review_required) if review_required
             else "- None from the automated gates; the professor still confirms the "
                  "preemption verdict (gaps/hypotheses possibly closed by the new papers).")
    body += ("\n\n## Preemption verdict (fill from the deliberation + scholar-evaluation steps)\n\n"
             "- Gaps possibly closed by the new papers: _..._\n"
             "- Hypotheses possibly preempted / to revise: _..._\n"
             "- Contribution-still-novel score: _.../5_\n")
    return body


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Delta and merge bookkeeping for the incremental litreview update")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_base = sub.add_parser("baseline", help="fingerprint an existing review")
    p_base.add_argument("review_tex")
    p_base.add_argument("--corpus", default=None, help="corpus.json from the original run")
    p_base.add_argument("--bib", default=None, help="review.bib from the original run")
    p_base.add_argument("--out", default="baseline.json")

    p_delta = sub.add_parser("delta", help="keep only candidates new vs the baseline")
    p_delta.add_argument("candidates", help="fresh candidates.json")
    p_delta.add_argument("--baseline", required=True, help="baseline.json from the baseline mode")
    p_delta.add_argument("--out", default="delta_candidates.json")

    p_log = sub.add_parser("changelog", help="dated output paths + CHANGELOG scaffold")
    p_log.add_argument("delta_corpus", help="enriched delta corpus.json ({} for an empty delta)")
    p_log.add_argument("--review", required=True, help="the existing review .tex")
    p_log.add_argument("--date", default=None, help="YYYYMMDD stamp (default: today)")
    p_log.add_argument("--out", default=None, help="CHANGELOG path (default: alongside the review)")

    args = parser.parse_args()

    if args.mode == "baseline":
        baseline = build_baseline(args.review_tex, args.corpus, args.bib)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(baseline, handle, ensure_ascii=False, indent=1)
        logger.info("[LIT-UPDATE] baseline: %d dois, %d citekeys, %d titles, next=%s -> %s",
                    len(baseline["dois"]), len(baseline["citekeys"]),
                    len(baseline["titles"]), baseline["next_update_date"], args.out)

    elif args.mode == "delta":
        candidates = _load_json(args.candidates)
        baseline = _load_json(args.baseline)
        delta = compute_delta(candidates, baseline)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(delta, handle, ensure_ascii=False, indent=1)
        logger.info("[LIT-UPDATE] delta: %d candidates, %d new -> %s",
                    len(candidates), len(delta), args.out)
        print(json.dumps({"total": len(candidates), "new": len(delta),
                          "duplicates": len(candidates) - len(delta),
                          "delta_out": args.out}))

    elif args.mode == "changelog":
        delta_corpus = _load_json(args.delta_corpus)
        paths = dated_paths(args.review, args.date)
        out = args.out or paths["changelog"]
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(build_changelog(delta_corpus, args.review, args.date))
        logger.info("[LIT-UPDATE] changelog -> %s (updated tex: %s)", out, paths["updated_tex"])
        print(json.dumps(dict(paths, changelog=out, new=len(delta_corpus or {}))))


if __name__ == "__main__":
    main()