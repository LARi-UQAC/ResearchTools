#!/usr/bin/env python3
"""
vault_apply - apply a link map across the vault, with the refusals that make it safe.

Split out of vault_consolidate.py with vault_corpus and vault_links. This module
owns apply_map: the one sanctioned in-place edit of notes that already exist. Its
value is in what it REFUSES - a replacement that is not itself a bracketed
wiki-link, a path resolving outside the vault, a junction escape, a target on
another drive - and in being dry-run until the caller says --yes.

It is the only module here that writes to a note, so a reviewer looking for the
blast radius of this skill reads this file and no other.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import glob
import io
import os

from vault_corpus import find_phantoms, load  # noqa: E402,F401
from vault_links import (  # noqa: E402,F401
    _is_bracketed_link, _link_target, _rewrite_prose_preserving_code)

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


