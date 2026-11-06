"""
bridge_text.py - the pure text helpers of ollama_bridge, moved out so that no module of the
bridge family goes over the 16000-token reading ceiling of context-budget.json.

Holds what has no network, no filesystem and no model in it: BridgeError, the reasoning stripper
(`strip_reasoning`, `ReasoningAnomalyError`), the reply splitter (`split_files`), the sole-fence
unwrapper (`unwrap_sole_code_fence`) and the hygiene scan (`scan_hygiene`). Every name is
re-exported by `ollama_bridge`, so `ollama_bridge.split_files` and `except ollama_bridge.BridgeError`
keep working and are the very same objects. The code was moved byte for byte (Issue #104, owner
decision 2026-11-05, cloud split because the cut is delicate); nothing was rewritten.
"""
from __future__ import annotations

import re


# D3 / I3: every marker strip_reasoning's single-pass state machine reacts to, matched in
# one pass so fence and think/thinking state never break across an artificial segment
# boundary. Order in the alternation does not matter; the state machine's own precedence
# (in_fence, then think_depth, then in_thinking, then normal) decides what each match means.
_REASONING_MARKER_RE = re.compile(
    r"```|<think>|</think>|Thinking\.\.\.|\.\.\.done thinking\.",
    re.IGNORECASE,
)

_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\u2060"
_CURLY_QUOTES = "\u2018\u2019\u201c\u201d"
# Fix round 1 (minor): non-breaking space, non-breaking hyphen, minus sign - grouped with
# the typographic set scan_hygiene already checks.
_OTHER_TYPOGRAPHIC_CHARS = "\u00a0\u2011\u2212"

# Emoji blocks checked by _is_emoji (decision recorded in the module docstring).
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F300, 0x1F5FF),
    (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
    (0xFE0F, 0xFE0F),
)


class BridgeError(RuntimeError):
    """Raised on any refusal path: over-budget prompt, resolver failure, or daemon error."""


def _is_unicode_tag(codepoint: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Test whether a codepoint falls in the deprecated Unicode Tags block,
        which can encode invisible machine-only instructions.

    Inputs:
        codepoint (int): a single character's ordinal value.

    Outputs:
        result (bool): True when the codepoint is in U+E0000..U+E007F.
    --------------------------------------------------------------------------
    """
    return 0xE0000 <= codepoint <= 0xE007F


def _is_emoji(codepoint: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Test whether a codepoint falls in a common emoji block. See the module
        docstring for why emoji are in scope for this bridge's hygiene gate.

    Inputs:
        codepoint (int): a single character's ordinal value.

    Outputs:
        result (bool): True when the codepoint falls in one of _EMOJI_RANGES.
    --------------------------------------------------------------------------
    """
    return any(low <= codepoint <= high for low, high in _EMOJI_RANGES)



class ReasoningAnomalyError(RuntimeError):
    """
    Raised by strip_reasoning (I3) when the reasoning markers cannot be resolved safely:
    an unterminated <think> block, an orphan </think> with no opener, or an unterminated
    Thinking... block. The caller (run_bridge) must treat the whole attempt as failed and
    retry, never guess how to clean an anomalous shape - a stripper that eats legitimate
    content is worse than one that leaks, and both are unacceptable in a note.
    """


def strip_reasoning(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove a model's reasoning trace before it can reach a note (D3): a
        plausible-looking reasoning block that survives into a file is worse
        than a syntax error, because it reads as content and passes casual
        review. Ollama's CLI '--hidethinking' flag has no HTTP equivalent, so
        this is real stripping code, not a request flag.

        A single left-to-right scan tracks three pieces of state at once -
        in_fence, think_depth, in_thinking - because an earlier two-pass
        design (split all fences out FIRST, then strip each fence-free
        segment independently) broke exactly the case where a fence sits
        INSIDE an active <think> span: splitting resets the depth counter
        per segment, so the outer <think> looked unterminated in one
        segment and its </think> looked orphaned in the next. A single
        pass with one set of counters has no segment boundary to break
        across (I3).

        Precedence, checked in this order for every marker encountered:
          1. Already inside a fence (in_fence) - only a closing ``` is
             recognized; every other marker (including <think>, </think>,
             Thinking..., ...done thinking.) is inert, just more protected
             text. This is what stops an unclosed <think> used as a
             literal HTML example inside a real ```html fence from
             deleting the rest of the note.
          2. Already dropping a <think> span (think_depth > 0) - only
             <think> (nests deeper) and </think> (unnests) are recognized;
             a fence marker seen here is simply more text being dropped
             along with the rest of the reasoning (this is also what lets
             a fence-looking backtick pair used INSIDE a think span, as
             formatting inside the model's own reasoning, disappear
             cleanly with it).
          3. Already dropping a Thinking... block (in_thinking) - only the
             closing '...done thinking.' marker is recognized; other
             markers seen here are likewise just dropped text.
          4. Otherwise (fully normal) - a marker starts a new state: ```
             opens a fence, <think> starts dropping (depth 1), Thinking...
             starts dropping. A </think> or an orphan '...done thinking.'
             seen here has no opener to match, which is anomalous.
        No other reasoning convention is recognized.

        An ANOMALOUS shape - an orphan </think>, an orphan
        '...done thinking.', an unterminated <think> (depth > 0 at the end
        of the text), or an unterminated Thinking... block - raises
        ReasoningAnomalyError instead of guessing how much to drop or keep
        (I3). The caller must treat that as a failed attempt and retry,
        the same as an empty body or a hygiene violation. An unterminated
        FENCE is not treated as a reasoning anomaly (fences are not this
        function's concern beyond protecting their contents); whatever
        text remains open in that state is kept as-is.

    Inputs:
        text (str): the raw model response.

    Outputs:
        result (str): text with every recognized reasoning span removed
        (fenced code preserved verbatim), then stripped of leading/trailing
        whitespace.

    Raises:
        ReasoningAnomalyError: see above.
    --------------------------------------------------------------------------
    """
    kept: list[str] = []
    keep_from = 0
    in_fence = False
    think_depth = 0
    in_thinking = False

    for m in _REASONING_MARKER_RE.finditer(text):
        token = m.group(0)
        low = token.lower()

        if in_fence:
            if token == "```":
                in_fence = False
            continue  # every marker is inert while inside a protected fence

        if think_depth > 0:
            if low == "<think>":
                think_depth += 1
            elif low == "</think>":
                think_depth -= 1
                if think_depth == 0:
                    keep_from = m.end()
            continue  # a fence or Thinking marker here is just dropped text

        if in_thinking:
            if low == "...done thinking.":
                in_thinking = False
                keep_from = m.end()
            continue  # a fence or <think> marker here is just dropped text

        # Fully normal state: this marker starts something new.
        if token == "```":
            in_fence = True
        elif low == "<think>":
            kept.append(text[keep_from:m.start()])
            think_depth = 1
        elif low == "</think>":
            raise ReasoningAnomalyError(
                "[BRIDGE] orphan </think> with no matching opening tag (I3)."
            )
        elif low == "thinking...":
            kept.append(text[keep_from:m.start()])
            in_thinking = True
        elif low == "...done thinking.":
            raise ReasoningAnomalyError(
                "[BRIDGE] orphan ...done thinking. with no matching Thinking... (I3)."
            )

    if think_depth > 0:
        raise ReasoningAnomalyError(
            "[BRIDGE] unterminated <think> block (no matching closing tag) (I3)."
        )
    if in_thinking:
        raise ReasoningAnomalyError(
            "[BRIDGE] unterminated Thinking... block (no matching "
            "...done thinking.) (I3)."
        )

    kept.append(text[keep_from:])
    return "".join(kept).strip()


_FENCE_LINE_RE = re.compile(r"^\s*```[A-Za-z0-9_+.-]*\s*$")


_FILE_FENCE_OPEN_RE = re.compile(r"^(`{3,})[A-Za-z0-9_+.-]*\s*$")
_FILE_PATH_RE = re.compile(r"^#\s*file:\s*(\S.*?)\s*$")


def split_files(text: str) -> list[tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a local-coder reply into the files it carries. The driver asks
        the model for a whole plan in one answer, as aider-setup does, so one
        reply holds several files (Issue #104, plan 13).

    Details:
        A file is a fenced block whose first inner line is
        `# file: <relative path>`. The closing fence is a line of backticks
        at least as long as the opening one (CommonMark), so a Markdown file
        that holds its own three-backtick fences is wrapped in four. Text
        outside the blocks is ignored: it is the model's commentary, never a
        file. The path is returned as written; the caller resolves it and
        checks it against the plan (R24).

    Inputs:
        text (str): the reply, after reasoning has been stripped.

    Outputs:
        files (list[tuple[str, str]]): (path, body) in reply order; each body
            ends with one newline.

    Raises:
        BridgeError: no file at all, a block with no `# file:` line, the same
            path twice, or a fence left open (a truncated reply).
    --------------------------------------------------------------------------
    """
    lines = text.splitlines()
    files: list[tuple[str, str]] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        opening = _FILE_FENCE_OPEN_RE.match(lines[index])
        if not opening:
            index += 1
            continue
        fence = opening.group(1)
        first = lines[index + 1] if index + 1 < len(lines) else ""
        path_match = _FILE_PATH_RE.match(first)
        if not path_match:
            raise BridgeError(f"[BRIDGE] reply block at line {index + 1} has no '# file: <path>' line")
        path = path_match.group(1)
        if path in seen:
            raise BridgeError(f"[BRIDGE] reply carries {path} twice")
        body: list[str] = []
        cursor = index + 2
        while cursor < len(lines):
            stripped = lines[cursor].strip()
            if stripped and set(stripped) == {"`"} and len(stripped) >= len(fence):
                break
            body.append(lines[cursor])
            cursor += 1
        else:
            raise BridgeError(f"[BRIDGE] reply block for {path} is never closed (truncated reply?)")
        seen.add(path)
        files.append((path, "\n".join(body).rstrip("\n") + "\n"))
        index = cursor + 1
    if not files:
        raise BridgeError("[BRIDGE] reply carries no '# file:' block")
    return files


def unwrap_sole_code_fence(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove the fence when a response IS one fenced block and nothing else,
        so a model that presents its module for display does not fail on
        punctuation.

        Measured 2026-08-28 on a coder candidate that scored 0 of 3. It wrapped
        its module in a fence despite a prompt forbidding one, the bridge wrote
        that text verbatim to a .py file, and every attempt died with
        "SyntaxError: invalid syntax" on line 1, before a single case ran. The
        oracle was grading punctuation rather than code, and it did so for any
        model with that habit, which is most instruction-tuned ones.
        strip_reasoning deliberately PROTECTS fences (defect I3), so nothing
        else in the pipeline could ever remove an outer one.

        Deliberately narrow. Only a body whose first and last lines are the
        ONLY two fence lines in it is unwrapped. Prose around a fence is a
        Markdown deliverable and unwrapping it would delete the document; two
        blocks are a document as well; an unterminated fence is truncated
        output, and dropping its opening marker would turn a broken response
        into one that merely looks plausible.

    Inputs:
        text (str): the response body, after reasoning has been stripped.

    Outputs:
        result (str): the fenced block's contents when the body is exactly one
        fenced block, otherwise `text` unchanged.
    --------------------------------------------------------------------------
    """
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return text
    fence_lines = [i for i, line in enumerate(lines) if _FENCE_LINE_RE.match(line)]
    if fence_lines != [0, len(lines) - 1]:
        return text
    return "\n".join(lines[1:-1]).strip()


def scan_hygiene(text: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Detect banned characters in code, never by asking the model to avoid
        them (D5): a 9B model follows a style paragraph inconsistently, and
        the paragraph itself spends the scarce num_ctx window. See the module
        docstring for the exact banned set and the emoji decision.

    Inputs:
        text (str): the reasoning-stripped candidate body.

    Outputs:
        result (list[str]): one description per distinct violation found,
        sorted for a deterministic log line; empty when the text is clean.
        Non-empty means the caller must retry, not patch the text in place.
    --------------------------------------------------------------------------
    """
    found: set[str] = set()
    for ch in text:
        cp = ord(ch)
        if ch in _ZERO_WIDTH_CHARS:
            found.add(f"zero-width character U+{cp:04X}")
        elif ch in _CURLY_QUOTES:
            found.add(f"curly quote U+{cp:04X}")
        elif ch in _OTHER_TYPOGRAPHIC_CHARS:
            found.add(f"typographic character U+{cp:04X}")
        elif cp == 0x2026:
            found.add("ellipsis character U+2026")
        elif cp == 0x2014:
            found.add("em dash U+2014")
        elif cp == 0x2013:
            found.add("en dash U+2013")
        elif _is_unicode_tag(cp):
            found.add(f"unicode tag character U+{cp:05X}")
        elif _is_emoji(cp):
            found.add(f"emoji character U+{cp:04X}")
    return sorted(found)

