#!/usr/bin/env python3
"""
vault_corpus - read the vault and measure it. No writes, no model, no judgment.

Split out of vault_consolidate.py on 2026-08-28, which had reached 8768 tokens,
more than twice the 4096-token source ceiling, and along the seam the module
already had rather than an arbitrary one. What lives here answers "what is in
the vault and what is connected to what": the corpus loader, the name and alias
index, the edge graph, the term extraction, the scored suggestions, and the
phantom (dead link) report.

Everything here is READ-ONLY. The two modules that change a note are
vault_links (the string surgery on one note) and vault_apply (the guarded
rewrite across the vault), and both import from here rather than the reverse.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import collections
import difflib
import glob
import io
import os
import re

FENCE = re.compile(r"(?ms)^```.*?^```")
CODE_SPAN = re.compile(r"`[^`\n]*`")
# Same two shapes as FENCE and CODE_SPAN, combined so apply_map can carve
# both kinds of code region out of a note in one left-to-right pass and
# leave them byte-identical, instead of rewriting through them.
CODE_REGION = re.compile(r"(?ms)(?:^```.*?^```)|(?:`[^`\n]*`)")
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
ALIASES = re.compile(r"(?m)^aliases:\s*\[(.*?)\]")
TAGS = re.compile(r"(?m)^tags:\s*\[(.*?)\]")
DOMAINE = re.compile(r"(?m)^domaine:\s*(.+)$")
FRONT = re.compile(r"(?s)\A---\n.*?\n---\n")
WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_\-]{3,}")

# Terms too common to carry a signal, in French technical vocabulary. This list is DATA, not
# prose: it is matched against note bodies that are themselves in French, so it MUST STAY
# FRENCH. Do not translate it to English later; doing so would silently break the scoring
# by letting every common French word through as a rare, supposedly meaningful term.
STOP = set("""
dans pour avec sans donc mais elle il ils elles cette cet ces leur leurs plus moins tout tous
toute toutes meme meme etre avoir fait faire fais deja alors ainsi comme quand parce que qui
quoi dont lequel laquelle celui celle ceux celles note notes coffre projet projets voir aussi
contexte probleme cause racine correctif reutilisation exemple exemples cas type date tags
domaine ligne lignes fichier fichiers valeur valeurs resultat resultats regle regles
""".split())



def strip_code(text: str) -> str:
    return CODE_SPAN.sub(" ", FENCE.sub(" ", text))


def load(vault: str) -> dict[str, str]:
    notes = {}
    for p in glob.glob(os.path.join(vault, "**", "*.md"), recursive=True):
        rel = os.path.relpath(p, vault).replace(os.sep, "/")
        notes[rel] = io.open(p, encoding="utf8", errors="replace").read()
    return notes


def build_names(notes: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for rel, text in notes.items():
        names[os.path.basename(rel)[:-3]] = rel
        names[rel[:-3]] = rel
        m = ALIASES.search(text[:1500])
        if m:
            for a in re.findall(r'"([^"]+)"', m.group(1)):
                names[a.strip()] = rel
    return names


def build_path_suffixes(notes: dict[str, str]) -> dict[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Index every PATH SUFFIX of every note, at folder boundaries. Obsidian
        resolves a link written as an intermediate suffix - `[[Project/Notes]]`
        for `10_Projets/Logiciels/Project/Notes.md` - but build_names indexes
        only the bare basename and the full relative path, so such a link was
        reported as a phantom although the vault resolves it.

        Deliberately NOT folded into build_names: that function also feeds
        the candidates mode, whose JSON output is contractually byte-identical
        for local-writer, and widening its namespace would change which pairs
        count as already linked. This index is consulted by the links report
        alone.

    Inputs:
        notes (dict[str, str]): relative path -> full text, from load()

    Outputs:
        index (dict[str, list[str]]): suffix -> the notes it can designate,
        sorted. More than one note per suffix is normal and is not an error
        here: for phantom detection, being designatable by at least one note
        is the whole question.
    --------------------------------------------------------------------------
    """
    index: dict[str, list[str]] = {}
    for rel in notes:
        parts = rel[:-3].split("/")
        for i in range(len(parts)):
            index.setdefault("/".join(parts[i:]), []).append(rel)
    for targets in index.values():
        targets.sort()
    return index


def build_graph(notes, names):
    out = {r: set() for r in notes}
    inc = {r: set() for r in notes}
    for rel, text in notes.items():
        for target in LINK.findall(strip_code(text)):
            dest = names.get(target.strip())
            if dest and dest != rel:
                out[rel].add(dest)
                inc[dest].add(rel)
    return out, inc


def meta(text: str):
    head = text[:1500]
    tags = set()
    m = TAGS.search(head)
    if m:
        tags = {t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()}
    d = DOMAINE.search(head)
    return tags, (d.group(1).strip().strip('"\'') if d else "")


def terms(text: str) -> set[str]:
    body = strip_code(FRONT.sub("", text)).lower()
    return {w for w in WORD.findall(body) if w not in STOP}


def suggest(target: str, names: dict[str, str], limit: int = 3) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Propose existing notes an unresolved link may have meant. The script
        proposes; it never chooses. Choosing is judgment and belongs to
        local-writer.

    Inputs:
        target (str): the unresolved link text, without the brackets
        names (dict[str, str]): resolution namespace from build_names
        limit (int): maximum suggestions returned

    Outputs:
        suggestions (list[dict]): {"target", "score", "why"}, best first
    --------------------------------------------------------------------------
    """
    out = []
    for candidate in difflib.get_close_matches(target, list(names), n=limit, cutoff=0.6):
        score = difflib.SequenceMatcher(None, target.lower(), candidate.lower()).ratio()
        # The three whys are not decoration: an exact basename or alias match that
        # only failed on case or on a stray space is a near-certain repoint, while
        # a fuzzy one always needs the agent's judgment.
        if score == 1.0:
            rel = names[candidate]
            stem = os.path.basename(rel)[:-3]
            # A match on the note's own name, whether the bare basename or the
            # full relative path, is a name match; only a frontmatter alias is
            # an alias. The earlier endswith test mislabelled a root-level note
            # and a full-path match as aliases.
            why = "basename" if candidate in (stem, rel[:-3]) else "alias"
        else:
            why = "fuzzy"
        out.append({"target": candidate, "score": round(score, 3), "why": why})
    return out


def find_phantoms(notes: dict[str, str], names: dict[str, str]) -> dict[str, dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every wiki-link that resolves to no note. Such a link creates a
        phantom node in Obsidian's graph, which degrades it as much as an
        isolated note does.

        A target counts as resolved when build_names knows it (basename, full
        path, frontmatter alias) OR when it is a path suffix of a real note
        (build_path_suffixes). Without the second test the report flagged
        links Obsidian resolves perfectly well, and an operator who "repaired"
        one would have rewritten a working link.

    Inputs:
        notes (dict[str, str]): relative path -> full text, from load()
        names (dict[str, str]): resolution namespace, from build_names()

    Outputs:
        phantoms (dict[str, dict]): unresolved target -> {"sources", "suggestions"}
    --------------------------------------------------------------------------
    """
    suffixes = build_path_suffixes(notes)
    found: dict[str, dict] = {}
    for rel, text in notes.items():
        # An archive pointing at a deleted note is not a defect to fix, so
        # 90_Archives is excluded as a link SOURCE (never as a target).
        if rel.startswith("90_Archives/"):
            continue
        for raw in LINK.findall(strip_code(text)):
            target = raw.strip()
            if target in names or target in suffixes:
                continue
            entry = found.setdefault(target, {"sources": [], "suggestions": []})
            if rel not in entry["sources"]:
                entry["sources"].append(rel)
    for target, entry in found.items():
        entry["sources"].sort()
        entry["suggestions"] = suggest(target, names)
    return found


def split_inherited(phantoms: dict[str, dict], baseline: dict[str, dict] | None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Separate the phantoms this vault already carried from the ones the
        current work introduced. A raw count is not a quality signal on its
        own: it went 7 -> 8 -> 7 across one evening purely because of notes
        that same work wrote, which reads as progress and is not.

    Inputs:
        phantoms (dict): the current report's phantoms.
        baseline (dict | None): the "phantoms" object of an earlier links
            report, or None when no baseline was supplied.

    Outputs:
        split (dict): {"baseline_supplied": bool, "inherited": [...],
        "introduced": [...], "resolved_since_baseline": [...]}, each a sorted
        list of targets. With no baseline every target is reported as
        inherited and "baseline_supplied" is false, so a reader is never
        shown a zero that only means "nothing was compared".
    --------------------------------------------------------------------------
    """
    if baseline is None:
        return {
            "baseline_supplied": False,
            "inherited": sorted(phantoms),
            "introduced": [],
            "resolved_since_baseline": [],
        }
    known = set(baseline)
    current = set(phantoms)
    return {
        "baseline_supplied": True,
        "inherited": sorted(current & known),
        "introduced": sorted(current - known),
        "resolved_since_baseline": sorted(known - current),
    }


# Exactly one bracketed target and nothing else: the character class
# excludes "[" and "]" so a second bracket pair anywhere in the string
# (leading, trailing, or embedded prose) leaves a residue that fullmatch
# refuses, rather than being accepted as an unbracketed suffix.
