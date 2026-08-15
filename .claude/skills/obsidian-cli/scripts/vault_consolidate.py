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
"""
from __future__ import annotations

# check_isolated.py is deliberately not ported here: this script already computes "isolated"
# and "lonely" below, with the same edge definition and the same alias resolution, so a
# separate script would only duplicate that work. This comment exists so nobody ports it
# later out of unfamiliarity with what is already covered.

import argparse
import collections
import difflib
import glob
import io
import json
import os
import re
import sys

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
_BRACKETED_LINK = re.compile(r"\[\[([^\[\]]+)\]\]")


def _link_target(value: object) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the TARGET of a map key or value: "[[A/B]]" -> "A/B". Returns
        None for anything that is not exactly one bracketed target, which is
        what makes _is_bracketed_link a thin wrapper over this function.

        An alias or a heading inside the key is refused (None), because the
        key names WHAT a link points at, and the repair preserves whatever
        alias or heading the note itself carries. Accepting "[[A|B]]" as a key
        would silently mean "only repair the occurrences whose alias happens
        to be B", which nobody authoring a repair map intends.

    Inputs:
        value (object): candidate key or value; typed as object because the
            map is untrusted JSON with no schema.

    Outputs:
        target (str | None): the inner target, stripped of nothing else, or
        None when the value is not a single plain bracketed target.
    --------------------------------------------------------------------------
    """
    if not isinstance(value, str):
        return None
    m = _BRACKETED_LINK.fullmatch(value)
    if not m:
        return None
    inner = m.group(1)
    if not inner.strip():
        return None
    if "|" in inner or "#" in inner:
        return None
    return inner


def _is_bracketed_link(value: object) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enforce the map's contract on a single key or value: a bracketed
        wiki-link target and nothing else. This is the same scrutiny the
        escape guard already gives the PATH a rewrite writes to, applied to
        the TEXT a rewrite searches for and writes, because an empty,
        whitespace-only, unbracketed, or multi-link entry is not a single
        link at all: an empty key rewrites every note character by
        character, an unbracketed key rewrites word interiors ("Old"
        turning "Oldenburg" into "Newenburg"), "[[ ]]" carries no real
        target, and "[[A]] prose [[B]]" is two links and free text rather
        than one target.

    Inputs:
        value (object): a candidate map key or value; typed as object because
            the map is untrusted input read back from JSON with no schema

    Outputs:
        valid (bool): True only for a string that is EXACTLY one bracketed
            target, "[[...]]" with no other "[[" or "]]" anywhere in it,
            whose inner text is not empty, not only whitespace, and carries
            neither an alias ("|") nor a heading ("#") - see _link_target,
            which this function now wraps
    --------------------------------------------------------------------------
    """
    return _link_target(value) is not None


def _find_link_occurrence(text: str, target: str, start: int) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the next occurrence of a wiki-link POINTING AT `target`, in any
        of the four forms Obsidian accepts: [[target]], [[target|alias]],
        [[target#heading]], [[target#heading|alias]].

        This is the whole of defect P13. The repair used to be a literal
        replacement of "[[target]]", so an aliased link - the common form in
        this vault - never matched, and the dry run reported "modified: []"
        with nothing refused: it looked like a clean no-op rather than an
        inability, which is the worst way for a tool to fail.

        Plain substring search still, never a regex over note content (which
        is full of regex metacharacters); the shape is confirmed by looking
        at the ONE character that follows the target.

    Inputs:
        text (str): the prose being scanned.
        target (str): the link target, without brackets.
        start (int): index to search from.

    Outputs:
        pos (int): index of the opening "[[", or -1. A prefix hit such as
        "[[Older" while looking for "Old" is skipped, not returned: the
        character after the target must close the link (]]), open an alias
        (|), or open a heading (#).
    --------------------------------------------------------------------------
    """
    needle = "[[" + target
    i = start
    while True:
        pos = text.find(needle, i)
        if pos == -1:
            return -1
        after = text[pos + len(needle):]
        if after.startswith("]]") or after[:1] in ("|", "#"):
            return pos
        i = pos + 1


def _replace_single_pass(text: str, pairs: list[tuple[str, str]]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite every link pointing at a mapped target in ONE left-to-right
        pass over the original text, so chained keys never cascade: with
        {"[[A]]": "[[B]]", "[[B]]": "[[C]]"}, a note containing "[[A]]" must
        end as "[[B]]", never "[[C]]". Because the scan reads only the
        original text and never re-reads what it has already emitted, a
        replacement's own text is never a candidate for a further match.

        Only the "[[target" head is consumed and rewritten; whatever follows
        it - an alias, a heading, the closing brackets - is copied through
        from the original text, so [[A/B|Short label]] becomes
        [[C/D|Short label]] and the display text a human chose is preserved.

    Inputs:
        text (str): the prose to search (a whole note, or one prose segment
            with code fences and inline code already carved out by the
            caller)
        pairs (list[tuple[str, str]]): validated (target, replacement target)
            pairs WITHOUT brackets, in map order; ties on start position
            favour the earlier pair

    Outputs:
        result (str): text with every matched link retargeted, scanning
            resumed strictly after each matched target in the ORIGINAL text
    --------------------------------------------------------------------------
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        best_pos = -1
        best_target = ""
        best_replacement = ""
        for target, replacement in pairs:
            if not target:
                # Defense in depth, unreachable through apply_map's own
                # validated pairs: a zero-length target would match at
                # position i without consuming anything, stalling the scan
                # forever instead of failing loudly.
                continue
            pos = _find_link_occurrence(text, target, i)
            if pos != -1 and (best_pos == -1 or pos < best_pos):
                best_pos = pos
                best_target = target
                best_replacement = replacement
        if best_pos == -1:
            out.append(text[i:])
            break
        out.append(text[i:best_pos])
        out.append("[[" + best_replacement)
        i = best_pos + 2 + len(best_target)
    return "".join(out)


def _rewrite_prose_preserving_code(text: str, pairs: list[tuple[str, str]]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply the single-pass literal map to a note's PROSE only, leaving
        every code fence and inline code span byte-identical. This is the
        same exclusion find_phantoms already applies for DETECTION
        (strip_code), now honoured by the rewrite too, so apply never
        touches text the links report never flagged as a phantom.

    Inputs:
        text (str): the full note text
        pairs (list[tuple[str, str]]): validated (key, replacement) pairs

    Outputs:
        result (str): text with prose segments passed through
            _replace_single_pass and every code region copied through
            unchanged
    --------------------------------------------------------------------------
    """
    out: list[str] = []
    pos = 0
    for m in CODE_REGION.finditer(text):
        out.append(_replace_single_pass(text[pos:m.start()], pairs))
        out.append(m.group())  # code fence or inline code span, untouched
        pos = m.end()
    out.append(_replace_single_pass(text[pos:], pairs))
    return "".join(out)


def apply_map(vault: str, mapping: dict[str, str], write: bool) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite dead wiki-links across the vault from a human-curated map,
        under the same write discipline as the Obsidian outbox hook: dry-run
        unless explicitly authorised, a path that resolves outside the vault
        is refused rather than written, only a literal substring is ever
        replaced in one single pass (never a regex over note content, which
        contains regex metacharacters, and never a cascade across chained
        keys), code fences and inline code are left untouched, and every
        write is verified by its effect on disk rather than trusted on the
        strength of the write call alone. The map itself is untrusted input
        (it is JSON authored by human judgment, but read back with no schema
        enforcement, so it may not even be a JSON object): every key and
        every value must be a bracketed wiki-link target, and the check
        covers the WHOLE map before any file is opened. One malformed entry
        refuses the ENTIRE run and writes nothing anywhere, the same
        all-or-nothing discipline the path guard already applies to WHERE a
        rewrite lands. A partially applied map would be the half-rewritten
        vault that discipline exists to prevent, and it is worse than a
        clean refusal because the operator cannot tell which half landed.

    Inputs:
        vault (str): vault root path
        mapping (dict[str, str]): bracketed wiki-link target (such as
            "[[Old]]") to bracketed wiki-link replacement, authored by human
            judgment from a --mode links report; typed as the intended
            shape, but read back from JSON with no schema, so it is
            validated at runtime rather than trusted to match the hint
        write (bool): perform the write when True; compute the report with
            no filesystem write when False (dry run)

    Outputs:
        report (dict): {"modified": [rel...], "skipped": [rel...],
            "refused_map_entries": [entry...], "refused_paths": [rel...]}.
            "refused_map_entries" names a malformed key or value (the
            operator's remedy is to edit the map) and is never empty
            together with a non-empty "modified": either the whole map is
            clean and the run proceeds, or it is not and nothing is
            written. "refused_paths" lists relative paths (forward slashes)
            that resolve outside the vault (the operator's remedy is to
            look at the vault for a link or a junction); a path refusal is
            per-file and does not block other valid files from being
            written.
    --------------------------------------------------------------------------
    """
    vault_root = os.path.realpath(vault)
    modified: list[str] = []
    skipped: list[str] = []
    refused_map_entries: list[str] = []
    refused_paths: list[str] = []

    def _refused_report() -> dict:
        return {
            "modified": modified,
            "skipped": skipped,
            "refused_map_entries": refused_map_entries,
            "refused_paths": refused_paths,
        }

    # Phase 0a: the map must be a JSON object at all. Untrusted JSON with no
    # schema can hand back a list or a scalar; failing closed here avoids an
    # AttributeError on mapping.items() below and reports the same way any
    # other malformed map does.
    if not isinstance(mapping, dict):
        refused_map_entries.append(
            f"map is not an object: {type(mapping).__name__}"
        )
        return _refused_report()

    # Phase 0b: validate the WHOLE MAP before any path is even resolved. The
    # path guard below protects WHERE a rewrite lands; this protects WHAT it
    # searches for and writes, which the map's own untrusted-input status
    # demands just as much.
    pairs: list[tuple[str, str]] = []
    for key, value in mapping.items():
        key_target = _link_target(key)
        value_target = _link_target(value)
        if key_target is not None and value_target is not None:
            # Stored WITHOUT brackets: the rewrite consumes only the "[[target"
            # head so the alias or heading that follows survives (P13).
            pairs.append((key_target, value_target))
        else:
            refused_map_entries.append(f"map entry {key!r} -> {value!r}")

    if refused_map_entries:
        # WHOLE-MAP GATE: any malformed entry refuses the entire run, before
        # Phase 1 resolves a single path or a single file is opened. Without
        # this early return, the valid pairs collected above would still be
        # applied to the valid paths below, writing the "good half" of a
        # mixed map while reporting a refusal - exactly the half-rewritten
        # vault this gate exists to rule out.
        return _refused_report()

    # Phase 1: resolve and classify every candidate PATH before any file is
    # opened for writing, so a run never leaves the vault half-rewritten
    # because a later path's validation happened lazily mid-loop.
    targets: list[tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(vault, "**", "*.md"), recursive=True)):
        rel = os.path.relpath(path, vault).replace(os.sep, "/")
        if rel.startswith("90_Archives/"):
            # Same exclusion find_phantoms applies as a link SOURCE: an
            # archived note referencing a retired link was never flagged by
            # the links report, so apply must not silently rewrite it.
            skipped.append(rel)
            continue
        real = os.path.realpath(path)
        try:
            # Defense in depth: a note reached through a symlink or junction
            # could resolve outside the vault root even though the glob
            # discovered it inside the vault tree. Refuse it rather than
            # write through it, the same guard the outbox hook applies to a
            # path built from an untrusted directive.
            escapes = os.path.commonpath([vault_root, real]) != vault_root
        except ValueError:
            # commonpath raises when the two paths sit on different drives
            # or UNC roots. That failure IS proof the path is not under the
            # vault root, so it becomes a refusal, not a crash that would
            # otherwise abort the loop after earlier files were rewritten.
            escapes = True
        if escapes:
            refused_paths.append(rel)
            continue
        targets.append((path, rel))

    if not pairs:
        # Only reachable with an empty mapping ({}): every malformed-entry
        # case already returned above. An empty map has nothing to search
        # for, which is a no-op, not a refusal; every path was already
        # classified above, so report cleanly rather than opening files.
        skipped.extend(rel for _, rel in targets)
        return _refused_report()

    for path, rel in targets:
        before_text = io.open(path, encoding="utf-8", errors="replace").read()
        after_text = _rewrite_prose_preserving_code(before_text, pairs)

        if after_text == before_text:
            skipped.append(rel)
            continue

        if not write:
            # Dry run: report the intended change, write nothing.
            modified.append(rel)
            continue

        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(after_text)
        verify_text = io.open(path, encoding="utf-8", errors="replace").read()
        # Verify by effect rather than by trusting the write call: re-read
        # the file from disk and compare it to what stood there before the
        # write. A byte-size comparison cannot serve as that check, because
        # a same-length replacement leaves the size unchanged.
        if verify_text != before_text:
            modified.append(rel)
        else:
            skipped.append(rel)

    return _refused_report()


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
