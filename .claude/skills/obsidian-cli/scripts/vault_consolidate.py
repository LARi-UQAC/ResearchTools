#!/usr/bin/env python3
"""
vault_consolidate - propose missing edges between notes in the Obsidian vault.

Role: the DETERMINISTIC half of memory consolidation. The script decides nothing; it measures
verifiable signals and returns a list of candidate pairs not yet linked, with the evidence for
each candidacy. It is the agent (local-writer) that judges and writes.

Why this separation: finding candidates is a computation, deciding whether an edge is real is a
judgment. An agent that did both would invent subject links; a script that did both would
saturate the graph. The graph degrades as much from an excess of links as from a lack of them.

JSON output on stdout:
    {
      "notes": <int>,
      "isolated": [paths with no edge at all],
      "lonely":   [paths with exactly one edge],
      "candidates": [ {a, b, score, shared_tags, same_domaine, shared_terms, why} ... ]
    }

Usage:
    python vault_consolidate.py [--vault <path>] [--top 25] [--min-score 2]

Since 2026-08-28 this file is the CLI and nothing else. The module passed 8768
tokens, more than twice the 4096-token source ceiling, so it was split along the
seam it already had:

    vault_corpus  read the vault and measure it, read-only
    vault_links   rewrite one wiki-link inside one note, text in and text out
    vault_apply   apply a link map across the vault, with the refusals

Every name those modules export is re-exported here, so `vault_consolidate.X`
keeps working for the offline suite and for daemon_phantoms. The split is a size
boundary, not a change of interface.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import argparse
import io
import json
import os  # noqa: F401  re-exported: the suite reads os through this module

# Re-exported public surface. Explicit, not a star import, so a reader can
# see what this entry point promises and a removal shows up as an error here
# rather than as a mystery at a call site.
from vault_corpus import (  # noqa: E402,F401
    ALIASES, CODE_REGION, CODE_SPAN, DOMAINE, FENCE, FRONT, LINK, STOP, TAGS, WORD,
    build_graph, build_names, build_path_suffixes, find_phantoms, load, meta,
    split_inherited, strip_code, suggest, terms)
from vault_links import (  # noqa: E402,F401
    _BRACKETED_LINK, _find_link_occurrence, _is_bracketed_link, _link_target,
    _replace_single_pass, _rewrite_prose_preserving_code)
from vault_apply import apply_map  # noqa: E402,F401


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: the read-only candidate and links reports, plus the
        guarded --apply rewrite. Returns an int so the exit code is testable
        without spawning a process.

    Inputs:
        argv (list[str] | None): argument vector; None reads sys.argv, as
            argparse does by default

    Outputs:
        code (int): 0 on a normal report or a completed apply, non-zero when
            a refusal happened, so a caller cannot mistake a refusal for a
            no-op
    --------------------------------------------------------------------------
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:/Martin Otis/Vault")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min-score", type=float, default=2.0)
    ap.add_argument("--mode", choices=["candidates", "links"], default="candidates")
    ap.add_argument("--apply", metavar="MAP_JSON", default=None,
                     help='path to a JSON map of literal link text to rewrite, '
                          'e.g. {"[[Old]]": "[[New]]"}, authored by judgment '
                          'from a --mode links report')
    ap.add_argument("--yes", action="store_true",
                     help="authorise the write; without it --apply only "
                          "prints the intended change")
    ap.add_argument("--baseline", metavar="LINKS_JSON", default=None,
                     help="an earlier --mode links report; the new report then "
                          "separates phantoms INHERITED from the vault from those "
                          "INTRODUCED since. A bare count is not a quality signal: "
                          "it moved 7 -> 8 -> 7 in one evening purely because of "
                          "notes that same work wrote")
    args = ap.parse_args(argv)

    if args.apply:
        # No emptiness pre-check here: an empty vault (or a --vault typo
        # that finds no note) has nothing to change, and finding nothing to
        # change is a no-op, not a refusal. A non-zero exit below must come
        # only from a genuine refused write, never from an absence of work.
        with io.open(args.apply, encoding="utf-8") as fh:
            mapping = json.load(fh)
        report = apply_map(args.vault, mapping, write=args.yes)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        # The two refusal kinds have different causes and different
        # remedies, so they are counted and reported separately, and only
        # when they actually occurred: a malformed map entry is fixed by
        # editing the map, a path outside the vault is fixed by looking at
        # the vault for a link or a junction. len() is now taken on each
        # kind's own list, never on a mixed list of paths and entry strings.
        n_map = len(report["refused_map_entries"])
        n_path = len(report["refused_paths"])
        if n_map:
            entries = "entry is" if n_map == 1 else "entries are"
            print(f"[REFUSED] {n_map} map {entries} malformed; the run is "
                  "refused and nothing was written", file=sys.stderr)
        if n_path:
            paths = "path" if n_path == 1 else "paths"
            print(f"[REFUSED] {n_path} {paths} resolved outside the vault; "
                  "nothing written there", file=sys.stderr)
        if n_map or n_path:
            return 1
        verb = "modified" if args.yes else "would modify"
        print(f"[APPLY] {verb} {len(report['modified'])} file(s)", file=sys.stderr)
        return 0

    notes = load(args.vault)
    names = build_names(notes)

    if args.mode == "links":
        checked = sum(len(LINK.findall(strip_code(text))) for text in notes.values())
        phantoms = find_phantoms(notes, names)
        baseline = None
        if args.baseline:
            with io.open(args.baseline, encoding="utf-8") as fh:
                baseline = json.load(fh).get("phantoms", {})
        print(json.dumps({
            "notes": len(notes),
            "checked": checked,
            "provenance": split_inherited(phantoms, baseline),
            "phantoms": phantoms,
        }, ensure_ascii=False, indent=2))
        return 0

    out, inc = build_graph(notes, names)

    tags_of, dom_of, terms_of = {}, {}, {}
    for rel, text in notes.items():
        tags_of[rel], dom_of[rel] = meta(text)
        terms_of[rel] = terms(text)

    # Term rarity: a term present everywhere links nothing.
    df = collections.Counter()
    for ts in terms_of.values():
        df.update(ts)
    n = max(1, len(notes))
    rare = {t for t, c in df.items() if 2 <= c <= max(2, n // 4)}

    linked = {(a, b) for a in out for b in out[a]}

    # Scope: only notes under 30_Ressources are candidates. That is where reusable knowledge
    # lives; a project log carries only pointers, and linking it to another log teaches
    # nothing. Without this filter, the (very long) logs dominate the ranking.
    keys = sorted(r for r in notes
                  if r.startswith("30_Ressources/") and not r.endswith("_Convention_Capture.md"))
    cands = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if (a, b) in linked or (b, a) in linked:
                continue
            st = tags_of[a] & tags_of[b]
            sd = dom_of[a] and dom_of[a] == dom_of[b]
            sr = (terms_of[a] & terms_of[b]) & rare
            # Jaccard over the rare terms, not a raw count: without normalisation a long note
            # shares terms with everything and saturates the ranking (length bias measured on
            # the first attempt, a 20 kB log ranked first against everyone).
            union = (terms_of[a] | terms_of[b]) & rare
            jac = len(sr) / len(union) if union else 0.0
            score = 1.5 * len(st) + (1.0 if sd else 0.0) + 6.0 * jac
            if score < args.min_score:
                continue
            why = []
            if st:
                why.append("tags communs: " + ", ".join(sorted(st)))
            if sd:
                why.append("meme domaine: " + dom_of[a])
            if sr:
                why.append("termes rares partages: " + ", ".join(sorted(sr)[:8]))
            cands.append({
                "a": a, "b": b, "score": round(score, 2), "jaccard": round(jac, 3),
                "shared_tags": sorted(st), "same_domaine": bool(sd),
                "shared_terms": sorted(sr)[:12], "why": " | ".join(why),
            })

    cands.sort(key=lambda c: -c["score"])
    print(json.dumps({
        "notes": len(notes),
        "isolated": sorted(r for r in notes if not out[r] and not inc[r]),
        "lonely": sorted(r for r in notes if len(out[r]) + len(inc[r]) == 1),
        "candidates": cands[:args.top],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
