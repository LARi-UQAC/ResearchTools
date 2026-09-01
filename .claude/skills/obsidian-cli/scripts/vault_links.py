#!/usr/bin/env python3
"""
vault_links - the string surgery that rewrites one wiki-link inside one note.

Split out of vault_consolidate.py with vault_corpus and vault_apply. This is the
half that is easy to get subtly wrong: a link may be written bare, aliased with
a pipe, or carrying a heading anchor, and a naive replace corrupts the alias or
silently misses the link entirely. It also must never touch a link shown as an
example inside backticks or a fenced block, which is what CODE_REGION is for.

Nothing here reads the vault or decides anything. It is given text and pairs,
and returns text. vault_apply owns the guardrails and the file writing.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import re

from vault_corpus import CODE_REGION  # noqa: E402,F401

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


