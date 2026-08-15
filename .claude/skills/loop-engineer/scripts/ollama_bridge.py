"""
ollama_bridge.py - deterministic bridge from a local Ollama model to a vetted text body.

Replaces the wrapper `rtk ollama run <model> "$(cat prompt.txt)"`, measured (P4 Task 1,
Ollama 0.32.9) to carry seven defects. This module talks to Ollama's HTTP API
(`POST /api/generate`, `"stream": false`) through `urllib.request` instead of shelling out
to `ollama run`, for three measured reasons plus one structural consequence:

  1. D6 (fixed seed) is not achievable through the CLI. Piping `/set parameter seed N`
     ahead of the prompt on the same stdin does NOT fix the seed on Ollama 0.32.9: two
     runs with the same requested seed produced different text (measured directly; see
     the P4 Task 1 report). A requirement cannot rest on a mechanism that does not exist.
  2. The API does fix it. `POST /api/generate` with `options.seed = 42` returned
     byte-identical responses across two runs (sha256 `b8ccaa5173ac8202`, length 194,
     `eval_count` 181, both times).
  3. The CLI writes 68 to 71 ANSI cursor-control sequences into stdout per run (Ollama's
     word-wrap redraw). A naive escape strip CORRUPTS the text, because the model writes,
     moves the cursor back, and rewrites, so "obsidian-cl" plus a cursor move plus
     "obsidian-cli" becomes "obsidian-clobsidian-cli". The API response carries zero
     escapes, removing that entire class of corruption.
  4. `num_ctx` is settable per request in `options`, so D2 does not depend on the
     Modelfile being right at call time.

Consequence for D1: the prompt travels only as a JSON field in the POST body. No argv, no
shell, no ~32000-character Git Bash ceiling to hit, and no argv-encoding path for accents,
apostrophes, or backticks to corrupt on. This satisfies D1 more strongly than a stdin pipe
would, since there is no shell and no argv anywhere on this path.

Defect map (each addressed below, named again at its implementation):
  D1 prompt as a CLI argument              -> the prompt is a JSON field (build_payload);
                                               no argv, no shell, no length ceiling.
  D2 num_ctx not set                        -> check_budget() refuses a prompt that will not
                                               fit num_ctx, using an EXACT per-prompt token
                                               count from probe_prompt_tokens (see I1 below),
                                               not a character heuristic. options.num_ctx and
                                               options.num_predict are always set explicitly
                                               (the latter capping the reply so the reserved
                                               budget is enforced, not just assumed - see I2).
  D3 reasoning block not stripped           -> strip_reasoning(). --hidethinking is a CLI
                                               flag with no HTTP equivalent, so this is real
                                               stripping code. Covered shapes are listed in
                                               strip_reasoning's own docstring; an anomalous
                                               shape (unterminated block, orphan closing
                                               marker, or unresolvable nesting) raises
                                               ReasoningAnomalyError so the caller fails the
                                               whole attempt and retries rather than guessing
                                               (see I3).
  D4 verification left to the wrapper       -> run_verify() runs an executable oracle in
                                               run_bridge()'s attempt loop; a failing oracle
                                               restores the target file (restore_target()).
  D5 style hygiene asked of the model       -> scan_hygiene() checks the response in code,
                                               never in the prompt, and a violation triggers
                                               a fresh generation attempt within a finite
                                               retry budget (MAX_GENERATION_RETRIES). An
                                               empty or whitespace-only body is ALSO treated
                                               as a failed attempt, never as an accepted
                                               generation (see the run_bridge docstring).
  D6 sampling and seed not fixed            -> build_payload() fixes seed, temperature,
                                               top_p, and top_k; attempt 1 of any two
                                               invocations sharing the same --seed sends an
                                               identical request (a pure function of its
                                               inputs). Later attempts within one run offset
                                               the seed by the 0-based attempt index, so a
                                               persistently bad response is not retried
                                               against an identical, deterministically
                                               repeating answer.
  D7 silent fallback to a weaker model      -> resolve_model() is the only place a model
                                               tag is chosen; it asks the Task 3 resolver
                                               and raises BridgeError on any failure. There
                                               is no default tag anywhere in this module -
                                               the retired behavior this replaces ("falls
                                               back to qwen2.5-coder:7b" once documented in
                                               workflows.md) is exactly what is removed.

Fix round 1 additions (adversarial review, same numbering as the report):
  C1 empty body accepted                    -> an empty or whitespace-only body after
                                               strip_reasoning is a FAILED attempt: the
                                               target is never written, the attempt retries
                                               within budget, and the run exits non-zero if
                                               every attempt is empty (run_bridge).
  I1 estimate_tokens under-estimated         -> check_budget's exact gate is now
                                               probe_prompt_tokens: one cheap local round
                                               trip to /api/generate with num_predict=1
                                               (R57 - see below), reading the daemon's own
                                               prompt_eval_count. estimate_tokens is kept
                                               ONLY as a cheap, deliberately OVER-estimating
                                               pre-filter for the obviously enormous (it can
                                               never be the reason a prompt is accepted, only
                                               a reason one is rejected before spending a
                                               round trip). ROOT CAUSE, now identified (fix
                                               round 2, R56): the ~4098 ceiling measured in
                                               fix round 1 is not a mysterious cap. Measured
                                               independently across four num_ctx windows with
                                               the same ~16351-token prompt: num_ctx 2048/
                                               4096/8192 each truncated the prompt and
                                               reported exactly num_ctx // 2 + 2 tokens
                                               (ratio 0.500 in all three cases); num_ctx 16384
                                               was the control where the prompt fit inside
                                               the window, and the reported count was the
                                               true one (ratio 0.998). So: whenever a prompt
                                               exceeds num_ctx, Ollama 0.32.9 truncates it to
                                               num_ctx // 2 + 2 tokens and reports success
                                               with no error - the "+2" is template/BOS
                                               overhead. probe_prompt_tokens now refuses
                                               outright when the reported count matches this
                                               exact signature (+/- a small slack for the "+2"
                                               to vary by one), replacing the 3.0 plausibility
                                               margin from fix round 1: the signature is exact
                                               rather than calibrated on one dataset, and it
                                               cannot fire on a legitimate prompt except at
                                               one improbable exact size, which sits near the
                                               budget ceiling anyway and is safe to refuse.
  I2 num_predict never sent                  -> build_payload now sends
                                               options.num_predict = RESPONSE_RESERVE_TOKENS,
                                               so the reply-length reserve is enforced by the
                                               daemon, not merely assumed by this module.
  I3 reasoning stripper data loss            -> strip_reasoning now protects fenced code
                                               blocks (``` ... ```) completely - a reasoning
                                               marker inside a fence is left untouched, never
                                               treated as reasoning - and resolves <think>
                                               nesting with a depth counter instead of a
                                               non-greedy regex, so a nested pair no longer
                                               leaks its outer closing tag. An unterminated
                                               <think>, an orphan </think>, or an unterminated
                                               Thinking... block raises ReasoningAnomalyError
                                               instead of guessing; run_bridge catches it as a
                                               failed attempt, same as an empty body or a
                                               hygiene violation. This is deliberately
                                               POSITION-UNIFORM (fix round 2): an unclosed or
                                               orphaned marker fails the attempt wherever in
                                               the text it appears, including trailing real
                                               content at the end - do not "improve" this into
                                               a positional guess.
  I4 log path inside the repository          -> the default log path is now
                                               ~/.claude/loop-bridge-log.jsonl (the same home
                                               the outbox already uses), never a path inside
                                               this repository; --log overrides it.

Fix round 2 rulings:
  R56 replaces the fix round 1 plausibility margin with the exact truncation signature
      described under I1 above (probe_prompt_tokens / check_budget).
  R57 the probe sends options.num_predict = 1, never 0. Measured directly: num_predict=0
      made the daemon generate a full response (eval_count 195, done_reason "stop"; a real
      generation cost paid on every budget check), while num_predict=1 stopped after one
      token (eval_count 1, done_reason "length") with the IDENTICAL prompt_eval_count either
      way. There is therefore no reason to pay for the extra generation; build_probe_payload
      is called with num_predict=1 only, no 0-then-1 fallback loop.

Hygiene set (scan_hygiene, enforced in code, never requested from the model): zero-width
characters (U+200B, U+200C, U+200D, U+2060), the Unicode Tags block (U+E0000-U+E007F),
curly quotes, the ellipsis character U+2026, em dash U+2014, en dash U+2013, non-breaking
space U+00A0, non-breaking hyphen U+2011, and minus sign U+2212 (fix round 1: grouped with
the set it already caught, since none of the three belongs in a plain-ASCII-punctuation
note either). Emoji are also in scope, even though the source brief's enumerated set did
not name them: a live measurement produced one unprompted, and an academic French vault
note has no legitimate use for it, so it is checked the same way as the rest of this set
(see _is_emoji). This decision is load-bearing: the code and this docstring must stay
consistent if it changes.

Standard library only: argparse, hashlib, json, logging, math, re, shlex, subprocess, sys,
time, urllib.request, urllib.error, collections.abc, pathlib, typing, __future__. No
`requests`, no `ollama` Python package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import logging
import math
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Anchored onto sys.path the same way resolve_model() anchors it for model_resolver (see
# below), so this import does not depend on the caller's own sys.path or working directory.
_SCRIPTS_DIR_FOR_IMPORT = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR_FOR_IMPORT not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR_FOR_IMPORT)
import context_budget  # noqa: E402  # P4 Task 5: shared local-model-config.json reader.

OLLAMA_HOST = "http://127.0.0.1:11434"
GENERATE_URL = f"{OLLAMA_HOST}/api/generate"

# P4 Task 5: read the measured window from local-model-config.json (written by
# optimize_ollama.py --sweep, P4 Task 4) through the SAME reader context_budget.py's own
# --task/--scan gates use, so the planning-time gate and this generation-time gate can never
# silently drift apart by reading two different numbers for the same measured fact. This
# replaces the fix round 1 hardcoded 8192 (P4 Task 1's server.log baseline), which had gone
# stale: the live 'ollama ps' CONTEXT field, local-model-config.json, the Modelfile, and
# ollama.yaml all now agree on 16384, but this constant still said 8192 - silently
# surrendering half the measured window and shifting the truncation signature this module's
# own D2/R56 guard computes (num_ctx // 2 + 2) from 8194 down to 4098. Raises
# context_budget.ConfigError, exactly as the planning-time gate does, when
# local-model-config.json is missing: a silent fallback here would be the same defect this
# whole module exists to remove (D7's own lesson - no default when the source of truth is
# absent), applied to the window instead of the model tag.
DEFAULT_NUM_CTX = context_budget.read_retained_num_ctx(context_budget.DEFAULT_CONFIG_PATH)
RESPONSE_RESERVE_TOKENS = 1024  # tokens reserved for the reply inside num_ctx

# Fix round 1 (I1): kept ONLY as a cheap, deliberately OVER-estimating character pre-filter
# for the obviously enormous, so a pathological prompt can be rejected without spending a
# probe round trip. 0.5 chars/token (2 tokens assumed per character) is well past every
# ratio measured this session (worst real case: ~1.09 chars/token on dense hex text at
# 2000 chars), so it over-estimates with margin; it must never be the reason a prompt is
# ACCEPTED, only a reason one is rejected early. The exact, authoritative count is
# probe_prompt_tokens's prompt_eval_count.
PREFILTER_CHARS_PER_TOKEN = 0.5

# Fix round 2 (R56): the exact fingerprint of Ollama 0.32.9 truncating a prompt to fit
# num_ctx. Measured independently across three windows with the same ~16351-token prompt:
# num_ctx 2048/4096/8192 each reported prompt_eval_count == num_ctx // 2 + 2 (ratio 0.500);
# num_ctx 16384 was the control where the prompt fit and the count was the true one (ratio
# 0.998). TRUNCATION_SIGNATURE_SLACK allows the "+2" template/BOS term to vary by one
# token without missing the match. Replaces fix round 1's 3.0 plausibility margin, which was
# calibrated on one dataset rather than an exact, measured fingerprint. All three measured
# windows hit the signature exactly with zero deviation, so a slack of 2 is wider than the
# evidence supports, and the cost of a false positive is not free - budget check runs once
# before the retry loop, so a false positive fails the entire run. A prompt sized near half
# the context window is plausible for a caller to send, yet safe to refuse.
TRUNCATION_SIGNATURE_SLACK = 1

# Measured (P4 Task 1): options.seed = 42 over the HTTP API returned byte-identical
# responses across two runs. D6 fixes sampling around that measured, working mechanism.
DEFAULT_SEED = 42
FIXED_TEMPERATURE = 0.2
FIXED_TOP_P = 0.9
FIXED_TOP_K = 40

MAX_GENERATION_RETRIES = 3      # finite retry budget for hygiene/verify failures (D5)
REQUEST_TIMEOUT_S = 300.0
VERIFY_TIMEOUT_S = 60.0

# Fix round 1 (I4): a machine-local artefact must default OUTSIDE the repository, so it
# never needs a .gitignore entry to stay out of a commit. Same home the outbox already
# uses. --log overrides this.
DEFAULT_LOG_PATH = Path.home() / ".claude" / "loop-bridge-log.jsonl"

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


def estimate_tokens(text: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        A cheap, deliberately OVER-estimating character-count pre-filter
        (fix round 1, I1). This is NOT the budget gate: it exists only so a
        pathologically enormous prompt can be rejected before spending a
        probe round trip, and so probe_prompt_tokens has a plausibility
        reference to detect a silently-capped probe response. It must never
        be the reason a prompt is ACCEPTED - only the exact count from
        probe_prompt_tokens decides that. PREFILTER_CHARS_PER_TOKEN=0.5
        (2 tokens assumed per character) is well past the densest ratio
        measured this session (~1.09 chars/token on hex-digest text).

    Inputs:
        text (str): the prompt text.

    Outputs:
        result (int): an over-estimated token count, at least 1 for
        non-empty text.
    --------------------------------------------------------------------------
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / PREFILTER_CHARS_PER_TOKEN))


def build_probe_payload(prompt: str, model: str, num_ctx: int, num_predict: int = 1) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the request body for a token-counting probe (I1): the same
        model, prompt, and num_ctx as the real generation, but num_predict
        forced to 1 (R57) so only a single completion token is generated -
        the daemon's own prompt_eval_count is what is wanted, and measured
        directly (fix round 2): num_predict=0 made the daemon generate a
        FULL response (eval_count 195, done_reason "stop") while
        num_predict=1 stopped after one token (eval_count 1, done_reason
        "length"), with the IDENTICAL prompt_eval_count either way - so 0
        simply pays for a generation on every budget check, for no benefit.

    Inputs:
        prompt (str): the full prompt text, unmodified.
        model (str): the resolved Ollama tag.
        num_ctx (int): the context window the real generation will request.
        num_predict (int): defaults to 1 (R57); kept as a parameter rather
            than hardcoded so a test can construct the exact wire payload
            and assert on it directly.

    Outputs:
        result (dict): the probe request body, ready for json.dumps.
    --------------------------------------------------------------------------
    """
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }


def _truncation_signature(num_ctx: int) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute Ollama 0.32.9's measured truncation fingerprint for a given
        num_ctx (R56): when a prompt exceeds num_ctx, the daemon truncates it
        to this many tokens and reports success, with no error. Measured
        independently across three windows with the same ~16351-token
        hex-dense prompt: num_ctx 2048 -> prompt_eval_count 1026 (ratio
        0.501), 4096 -> 2050 (0.500), 8192 -> 4098 (0.500); num_ctx 16384 was
        the control where the prompt fit inside the window and the count was
        the true, untruncated one (16351, ratio 0.998) - the fingerprint
        only appears when the prompt genuinely exceeds the window.

        The fingerprint num_ctx // 2 + 2 was measured on ornith:9b-gpu with
        ollama 0.32.9; the +2 is template or BOS overhead. A different model
        or template may carry a different constant. Re-measuring the constant
        belongs with the model qualification step, so that adopting a new
        model re-checks it rather than inheriting this one's number on faith.

    Inputs:
        num_ctx (int): the context window requested for this attempt.

    Outputs:
        result (int): num_ctx // 2 + 2, the exact truncated count Ollama
        reports when this num_ctx is exceeded.
    --------------------------------------------------------------------------
    """
    return num_ctx // 2 + 2


def _looks_truncated(prompt_eval_count: int, num_ctx: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Test whether a probe's reported prompt_eval_count matches Ollama's
        measured truncation signature for this num_ctx (R56), within
        TRUNCATION_SIGNATURE_SLACK tokens to allow for the "+2" template/BOS
        term varying by one or two.

    Inputs:
        prompt_eval_count (int): the count reported by the probe.
        num_ctx (int): the context window requested for this attempt.

    Outputs:
        result (bool): True when the count is within slack of the exact
        truncation signature for num_ctx.
    --------------------------------------------------------------------------
    """
    signature = _truncation_signature(num_ctx)
    return abs(prompt_eval_count - signature) <= TRUNCATION_SIGNATURE_SLACK


def probe_prompt_tokens(prompt: str, model: str, num_ctx: int, timeout: float = REQUEST_TIMEOUT_S) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Measure the prompt's exact token cost with the model's OWN tokenizer
        (I1), instead of a stdlib character heuristic that measurably
        under-estimates for some content (a character heuristic that
        under-counts defeats the very truncation guard it exists to
        implement). Sends num_predict=1, never 0 (R57 - see
        build_probe_payload); reads prompt_eval_count from the response.

        ROOT CAUSE, identified in fix round 2 (R56): the ~4098 ceiling
        measured in fix round 1 was not a mysterious cap - it is Ollama
        0.32.9's own truncation fingerprint, num_ctx // 2 + 2, reported with
        no error whenever the prompt exceeds num_ctx (see
        _truncation_signature's docstring for the four-window measurement).
        When the reported count matches that exact signature (within
        TRUNCATION_SIGNATURE_SLACK tokens), this function refuses outright:
        the count is not the prompt's true length, it is the truncation
        point, so trusting it would silently accept a prompt of unknown
        real size. This replaces fix round 1's 3.0 plausibility-margin
        cross-check against the character pre-filter: the signature is
        exact rather than calibrated on one dataset, and it cannot fire on
        a legitimate prompt except at the one improbable exact token count
        that equals num_ctx // 2 + 2 - which is itself within
        TRUNCATION_SIGNATURE_SLACK of half the window, comfortably inside
        the budget ceiling, and safe to refuse regardless of why it arose.

    Inputs:
        prompt (str): the full prompt text.
        model (str): the resolved Ollama tag.
        num_ctx (int): the context window the real generation will request.
        timeout (float): socket timeout in seconds.

    Outputs:
        result (int): the exact prompt_eval_count from the daemon.

    Raises:
        BridgeError: the probe call failed, the response carried no usable
        prompt_eval_count, or the count matches Ollama's truncation
        signature for this num_ctx. Never falls back to a heuristic.
    --------------------------------------------------------------------------
    """
    payload = build_probe_payload(prompt, model, num_ctx, num_predict=1)
    response = _post_generate(payload, timeout)

    count = response.get("prompt_eval_count")
    if not isinstance(count, int):
        raise BridgeError(
            "[BRIDGE] token probe response carried no usable prompt_eval_count; "
            "refusing rather than falling back to a character heuristic (I1)."
        )

    if _looks_truncated(count, num_ctx):
        signature = _truncation_signature(num_ctx)
        raise BridgeError(
            f"[BRIDGE] token probe reported {count} tokens, matching Ollama's own "
            f"truncation signature for num_ctx={num_ctx} (num_ctx // 2 + 2 = "
            f"{signature}, +/- {TRUNCATION_SIGNATURE_SLACK}); the prompt was silently "
            "truncated during counting and this is the truncation point, not the "
            "true length, so it cannot be trusted (I1/R56)."
        )
    return count


def check_budget(prompt: str, model: str, num_ctx: int) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse a prompt that will not fit inside num_ctx once a reply reserve
        is set aside (D2), instead of letting Ollama silently truncate the
        tail of the prompt, which is where the instruction usually lives.
        Order: a cheap character pre-filter rejects only the obviously
        enormous without a round trip; everything else is gated on the
        EXACT count from probe_prompt_tokens (I1), never on the pre-filter
        alone.

    Inputs:
        prompt (str): the full prompt text.
        model (str): the resolved Ollama tag (the probe needs one).
        num_ctx (int): the context window this attempt will request.

    Outputs:
        None.

    Raises:
        BridgeError: the pre-filter or the exact probe count exceeds the
        budget (num_ctx minus RESPONSE_RESERVE_TOKENS), the probe call
        itself failed, or the probe's count matched Ollama's own truncation
        signature for this num_ctx (R56 - see probe_prompt_tokens).
    --------------------------------------------------------------------------
    """
    budget = num_ctx - RESPONSE_RESERVE_TOKENS

    prefilter_tokens = estimate_tokens(prompt)
    if prefilter_tokens > budget:
        raise BridgeError(
            f"[BRIDGE] prompt is at least {prefilter_tokens} tokens by a deliberately "
            f"pessimistic character-count pre-filter alone, over the {budget}-token "
            f"budget (num_ctx={num_ctx} minus a {RESPONSE_RESERVE_TOKENS}-token reply "
            "reserve); refusing without spending a probe round trip on the obviously "
            "enormous (D2/I1)."
        )

    exact_tokens = probe_prompt_tokens(prompt, model, num_ctx)
    if exact_tokens > budget:
        raise BridgeError(
            f"[BRIDGE] prompt measured at exactly {exact_tokens} tokens (the model's "
            f"own tokenizer, via prompt_eval_count) exceeds the {budget}-token budget "
            f"(num_ctx={num_ctx} minus a {RESPONSE_RESERVE_TOKENS}-token reply "
            "reserve); refusing rather than letting Ollama truncate the tail (D2/I1)."
        )


def resolve_model(role: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the model resolver (Task 3 of this plan) which local Ollama tag
        this bridge must use for `role`. This is the ONLY place a model tag
        is chosen;
        the bridge never guesses or defaults one (D7). The retired wrapper's
        silent fallback to a weaker tag once the 9B models were missing is
        exactly the defect being removed - there is no equivalent fallback
        anywhere in this module. The scripts directory is anchored onto
        sys.path before the import (fix round 1, minor), so this does not
        depend on the caller's own sys.path or working directory once Task 3
        drops model_resolver.py next to this file.

        P4 (open-items pass, 2026-08-14): `role` is passed straight through
        to the resolver, which holds the per-role map. The bridge itself
        stores no roles and knows no tag - it only forwards what its caller
        declared it was doing, so local-coder stops being served the writer
        model that scores 0/3 on the coder tasks. role=None keeps the
        pre-P4 behaviour exactly.

    Inputs:
        role (str | None): task kind ("writer", "coder", ...), or None to
            ask for the overall current tag.

    Outputs:
        result (str): the resolved Ollama model tag.

    Raises:
        BridgeError: the resolver module is not importable, or it resolved to
        no tag. Both cases refuse rather than substitute a default.
    --------------------------------------------------------------------------
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import model_resolver  # type: ignore  # noqa: F401  # Task 3 of this plan; not yet built
    except ImportError as exc:
        raise BridgeError(
            "[BRIDGE] no model resolver available (Task 3 module 'model_resolver' not "
            "found); refusing to substitute a default or weaker tag (D7)."
        ) from exc
    tag = model_resolver.resolve(role)
    if not tag:
        raise BridgeError(
            "[BRIDGE] model resolver returned no tag; refusing to substitute a default "
            "or weaker tag (D7)."
        )
    return tag


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


def build_payload(prompt: str, model: str, seed: int, num_ctx: int) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the exact JSON body for /api/generate. Building it as a pure
        function of its inputs is what makes D6 checkable: the same seed,
        model, prompt, and num_ctx always produce the same request, so two
        runs are comparable and any difference is attributable to a real
        change rather than to hidden state.

    Inputs:
        prompt (str): the full prompt text, unmodified (D1: it travels only
            in this JSON field - no argv, no shell, no length ceiling).
        model (str): the resolved Ollama tag (see resolve_model).
        seed (int): the fixed sampling seed for this attempt.
        num_ctx (int): the context window to request explicitly (D2).

    Outputs:
        result (dict): the request body, ready for json.dumps. options.
        num_predict is set to RESPONSE_RESERVE_TOKENS (fix round 1, I2), so
        the reply-length reserve this module assumes is actually enforced by
        the daemon, not merely assumed by check_budget's arithmetic.
    --------------------------------------------------------------------------
    """
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # The bridge asks for an ANSWER, not a monologue. Measured 2026-08-14 on Ollama
        # 0.32.9 with qwen3.5:9b-gpu: on a coder qualification task the model spent the
        # ENTIRE num_predict reserve (1024 tokens, done_reason "length") inside its
        # "thinking" field and returned an EMPTY "response". Every attempt of every coder
        # task failed that way, so the candidate scored 0/3 for a reason that has nothing
        # to do with its coding: the run was measuring this reserve against a reasoning
        # model. With think=false the same task answered in 4.4 s and 94 tokens. Sending
        # the field is safe for a model that does no thinking either - checked on
        # ornith:9b-gpu and qwen2.5-coder:7b, both accepted it and answered normally - and
        # a daemon too old to know the field is handled explicitly in _post_generate.
        "think": False,
        "options": {
            "seed": seed,
            "num_ctx": num_ctx,
            "num_predict": RESPONSE_RESERVE_TOKENS,
            "temperature": FIXED_TEMPERATURE,
            "top_p": FIXED_TOP_P,
            "top_k": FIXED_TOP_K,
        },
    }


def _post_generate(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The sole network boundary. POSTs the JSON body to Ollama's
        /api/generate with stream=false and returns the parsed JSON response.
        Every offline test patches this function by name
        (unittest.mock.patch.object), so no test call ever opens a socket.

    Inputs:
        payload (dict): the request body from build_payload.
        timeout (float): socket timeout in seconds.

    Outputs:
        result (dict): the parsed JSON response (holds at least "response").

    Raises:
        BridgeError: connection failure, a read timeout, a non-2xx HTTP
        status (daemon error body surfaced rather than swallowed), or a
        response body that is not valid JSON (fix round 1, minor: both the
        timeout and the JSON-decode path used to be uncaught).
    --------------------------------------------------------------------------
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GENERATE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except TimeoutError as exc:
        raise BridgeError(
            f"[BRIDGE] Ollama request timed out after {timeout}s: {exc}"
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "think" in detail.lower() and "think" in payload:
            # A daemon too old to know the "think" field. Retry ONCE without it and say
            # so out loud: the reserve is then at the mercy of the model's reasoning
            # again (the empty-response failure documented in build_payload), so the
            # operator must be able to read that this is what happened.
            logger.warning(
                "[BRIDGE] this Ollama daemon rejected the 'think' field (HTTP 400); "
                "retrying without it. A reasoning model may now spend the whole reply "
                "reserve on its monologue and return an empty body. Detail: %s", detail,
            )
            reduced = {k: v for k, v in payload.items() if k != "think"}
            return _post_generate(reduced, timeout)
        raise BridgeError(f"[BRIDGE] Ollama returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(
            f"[BRIDGE] cannot reach the Ollama daemon at {GENERATE_URL}: {exc.reason}"
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgeError(f"[BRIDGE] Ollama response was not valid JSON: {exc}") from exc


def sha256_hex(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Hash text for the attempt log, so a prompt or response can be compared
        across runs without storing its full content in the log line.

    Inputs:
        text (str): the text to hash.

    Outputs:
        result (str): the sha256 hex digest of the utf-8 encoded text.
    --------------------------------------------------------------------------
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def append_log(log_path: Path, record: dict[str, Any]) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Append one JSON line to the machine-local bridge log (one line per
        attempt: prompt hash, response hash, seed, and durations).

    Inputs:
        log_path (Path): the loop-bridge-log.jsonl path.
        record (dict): the attempt record to serialize.

    Outputs:
        None. The line is appended to log_path, which is created if absent.
    --------------------------------------------------------------------------
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_verify(
    command: str | Sequence[str],
    target_path: Path | None = None,
    timeout: float = VERIFY_TIMEOUT_S,
) -> tuple[bool, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run an executable oracle (D4) instead of leaving verification to the
        cloud wrapper, so the innermost loop costs no cloud tokens and is
        reproducible. Never uses shell=True on a concatenated string.

    Inputs:
        command (str | Sequence[str]): the oracle to run. A string (the CLI
            --verify value) is split with shlex.split, which treats backslash
            as an escape character - a Windows path with backslashes in the
            command string should be quoted or wrapped in a small script.
            Programmatic callers should instead pass a pre-tokenized sequence
            (e.g. [sys.executable, "-c", "..."]), which sidesteps that
            limitation entirely because no string parsing happens at all.
            The literal placeholder '{target}' is substituted with
            target_path in either form when target_path is given.
        target_path (Path | None): substituted for '{target}' if present.
        timeout (float): seconds before the oracle is killed.

    Outputs:
        result (tuple[bool, str]): (passed, combined stdout+stderr).
    --------------------------------------------------------------------------
    """
    if isinstance(command, str):
        resolved = command.replace("{target}", str(target_path)) if target_path else command
        args = shlex.split(resolved)
    else:
        args = [
            str(part).replace("{target}", str(target_path)) if target_path else str(part)
            for part in command
        ]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"verify command failed to start: {exc}"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output


def read_existing(path: Path) -> bytes | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Snapshot a target file's current bytes before a candidate write, so a
        failed verification can be undone exactly (D4).

    Inputs:
        path (Path): the target file.

    Outputs:
        result (bytes | None): the file's current bytes, or None if it does
        not exist yet.
    --------------------------------------------------------------------------
    """
    return path.read_bytes() if path.exists() else None


def write_target(path: Path, text: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write an accepted candidate body to the target file.

    Inputs:
        path (Path): the target file (parent directories are created).
        text (str): the body to write.

    Outputs:
        None.
    --------------------------------------------------------------------------
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def restore_target(path: Path, previous: bytes | None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Undo a candidate write that failed verification (D4), returning the
        target file to exactly the state read_existing captured before the
        write, including "did not exist" for a file that did not exist.

    Inputs:
        path (Path): the target file.
        previous (bytes | None): the snapshot from read_existing.

    Outputs:
        None.
    --------------------------------------------------------------------------
    """
    if previous is None:
        if path.exists():
            path.unlink()
    else:
        path.write_bytes(previous)


def run_bridge(
    prompt_path: Path,
    verify_command: str | Sequence[str] | None,
    target_path: Path | None,
    seed: int,
    log_path: Path | None = None,
    max_retries: int = MAX_GENERATION_RETRIES,
    num_ctx: int = DEFAULT_NUM_CTX,
    role: str | None = None,
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Drive one bridge invocation end to end: model resolution (D7), exact
        budget refusal via a token probe (D2/I1), then a
        generate/strip/hygiene/verify attempt loop (D3, D4, D5, D6) with a
        finite retry budget, logging one JSON line per attempt. This is the
        single function main() calls; tests call it directly with
        _post_generate and resolve_model patched, so no test opens a socket.

        Fix round 1 (C1): an empty or whitespace-only body - whether from a
        response with no "response" key, an empty "response" string, or a
        reasoning-only reply that strips to nothing - is a FAILED attempt,
        exactly like a hygiene violation or a ReasoningAnomalyError (I3): the
        target is never written for it, the run retries within budget, and
        exits non-zero if every attempt is empty. The interface contract is
        "exit 0 only when a generation was produced AND passed every gate";
        an empty string is not a generation.

    Inputs:
        prompt_path (Path): file holding the full prompt text (utf-8).
        verify_command (str | Sequence[str] | None): optional executable
            oracle (D4); see run_verify for the two accepted forms.
        target_path (Path | None): optional file to write the accepted body
            to; when omitted, the accepted body is printed to stdout.
        seed (int): base seed for attempt 1 (D6); each retry adds its 0-based
            attempt offset, so a persistent failure is not retried against an
            identical, deterministically repeating response, while attempt 1
            of any two invocations sharing the same seed still issues an
            identical request.
        log_path (Path | None): defaults to DEFAULT_LOG_PATH
            (~/.claude/loop-bridge-log.jsonl, fix round 1 I4) - never a path
            inside this repository.
        max_retries (int): finite retry budget (D5).
        num_ctx (int): context window to request and to budget against (D2).
        role (str | None): task kind forwarded to resolve_model, so the
            coder role can be served by a different tag than the writer role
            (P4). None keeps the pre-P4 single-tag behaviour.

    Outputs:
        result (int): 0 on an accepted attempt, 1 on any refusal or on
        exhausting the retry budget.
    --------------------------------------------------------------------------
    """
    resolved_log_path = log_path or DEFAULT_LOG_PATH

    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("[BRIDGE] cannot read prompt file %s: %s", prompt_path, exc)
        return 1

    try:
        model = resolve_model(role)
    except BridgeError as exc:
        logger.error("%s", exc)
        return 1

    try:
        check_budget(prompt, model, num_ctx)
    except BridgeError as exc:
        logger.error("%s", exc)
        return 1

    prompt_hash = sha256_hex(prompt)
    previous_target = read_existing(target_path) if target_path is not None else None

    for attempt in range(1, max_retries + 1):
        attempt_seed = seed + (attempt - 1)
        payload = build_payload(prompt, model, attempt_seed, num_ctx)

        t0 = time.monotonic()
        try:
            response = _post_generate(payload, REQUEST_TIMEOUT_S)
        except BridgeError as exc:
            # A daemon/model-level refusal never gets a fallback tag (D7).
            logger.error("%s", exc)
            return 1
        generation_s = time.monotonic() - t0

        raw_text = response.get("response", "")
        reasoning_anomaly: str | None = None
        try:
            body = strip_reasoning(raw_text)
        except ReasoningAnomalyError as exc:
            body = ""
            reasoning_anomaly = str(exc)

        empty_body = not body.strip()
        violations: list[str] = [] if (empty_body or reasoning_anomaly) else scan_hygiene(body)

        verify_ok: bool | None = None
        verify_s = 0.0
        if reasoning_anomaly is None and not empty_body and not violations:
            if target_path is not None:
                write_target(target_path, body)
            if verify_command:
                t1 = time.monotonic()
                verify_ok, _output = run_verify(verify_command, target_path)
                verify_s = time.monotonic() - t1
                if not verify_ok and target_path is not None:
                    restore_target(target_path, previous_target)
            else:
                verify_ok = True

        accepted = (
            reasoning_anomaly is None
            and not empty_body
            and not violations
            and verify_ok is not False
        )

        append_log(resolved_log_path, {
            "attempt": attempt,
            "seed": attempt_seed,
            "prompt_hash": prompt_hash,
            "response_hash": sha256_hex(raw_text),
            "empty_body": empty_body,
            "reasoning_anomaly": reasoning_anomaly,
            "hygiene_violations": violations,
            "verify_ok": verify_ok,
            "accepted": accepted,
            "generation_s": round(generation_s, 3),
            "verify_s": round(verify_s, 3),
        })

        if accepted:
            if target_path is None:
                print(body)
            return 0

        # done_reason and the size of any "thinking" field are printed on an empty body
        # because "empty=True" alone hid a real cause for three attempts per task: the
        # model had spent the whole num_predict reserve reasoning (done_reason "length",
        # thinking 4259 chars, response 0). A rejection that does not name its cause
        # sends the reader looking at the model instead of at the request.
        cause = ""
        if empty_body:
            cause = (
                f" [done_reason={response.get('done_reason')!r}"
                f" thinking_chars={len(response.get('thinking') or '')}"
                f" eval_count={response.get('eval_count')}]"
            )
        logger.warning(
            "[BRIDGE] attempt %d rejected (empty=%s anomaly=%s hygiene=%s verify_ok=%s)%s; "
            "%d attempt(s) left",
            attempt, empty_body, bool(reasoning_anomaly), bool(violations), verify_ok,
            cause, max_retries - attempt,
        )

    logger.error("[BRIDGE] exhausted %d attempt(s) without an accepted response", max_retries)
    return 1


def resolve_vault() -> "Path | None":
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the vault the same way the outbox hook does: OBSIDIAN_VAULT wins,
        the documented default is the fallback, anything else is None.

    Inputs:
        none (reads OBSIDIAN_VAULT from the environment)

    Outputs:
        vault (Path | None): an existing vault directory, else None
    --------------------------------------------------------------------------
    """
    env = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env:
        candidate = Path(env)
        return candidate if candidate.is_dir() else None
    default = Path(r"C:\Martin Otis\Vault")
    return default if default.is_dir() else None


MAX_VAULT_NOTE_CHARS = 3000  # one note's share of the window; the whole vault never fits.


def collect_vault_context(terms: str, limit: int = 2) -> list[tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the vault notes that answer the question, mechanically. Selecting
        WHICH notes are relevant by keyword is retrieval, not judgment, and a
        grep does it more reliably than a procedure a caller can skip. The
        reusable layer (30_Ressources) is searched, because that is where
        knowledge meant to be reused lives; project logs are not answers.

    Inputs:
        terms (str): whitespace-separated search terms
        limit (int): maximum notes returned, best first

    Outputs:
        notes (list[tuple[str, str]]): (relative path, full text), best first
    --------------------------------------------------------------------------
    """
    vault = resolve_vault()
    if vault is None:
        return []
    wanted = [t.lower() for t in terms.split() if t.strip()]
    if not wanted:
        return []
    scored: list[tuple[int, int, int, str, str]] = []
    for path in (vault / "30_Ressources").rglob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name_hits = sum(path.name.lower().count(t) for t in wanted)
        body_hits = sum(text.lower().count(t) for t in wanted)
        # A note NAMED for the subject IS the answer; a long note merely mentioning it is
        # not. Filename match is a PRIMARY key, never a weight: measured here, a document
        # containing the term 200 times outranked the note named for it under a 10x bonus,
        # so volume beat relevance. Ranking removes that failure mode entirely.
        if name_hits or body_hits:
            scored.append(
                (1 if name_hits else 0, name_hits, body_hits,
                 str(path.relative_to(vault)).replace("\\", "/"), text)
            )
    scored.sort(key=lambda r: (-r[0], -r[1], -r[2], r[3]))
    return [(rel, text) for _, _, _, rel, text in scored[:limit]]


def write_prompt_with_vault_context(
    prompt_path: Path, notes: list[tuple[str, str]]
) -> Path:
    """
    --------------------------------------------------------------------------
    Purpose:
        Prepend the retrieved notes to the prompt, in a new file beside the
        original so the caller's prompt is never mutated. The instruction stays
        LAST, because Ollama truncates the tail of an over-long prompt and the
        tail is where the instruction lives.

    Inputs:
        prompt_path (Path): the caller's prompt file
        notes (list[tuple[str, str]]): (relative path, full text) to prepend

    Outputs:
        path (Path): the combined prompt file actually sent to the model
    --------------------------------------------------------------------------
    """
    blocks = ["Contexte tire du coffre Obsidian. Reponds a partir de ces notes, "
              "et si elles ne repondent pas, dis-le au lieu d'inventer.\n"]
    for rel, text in notes:
        body = text.strip()
        if len(body) > MAX_VAULT_NOTE_CHARS:
            body = body[:MAX_VAULT_NOTE_CHARS] + "\n[note tronquee pour tenir dans la fenetre]"
        blocks.append(f"--- {rel} ---\n{body}\n")
    blocks.append("--- fin du contexte ---\n\n")
    combined = prompt_path.with_name(prompt_path.stem + ".with-vault.txt")
    combined.write_text(
        "\n".join(blocks) + prompt_path.read_text(encoding="utf-8"),
        encoding="utf-8", newline="\n",
    )
    return combined


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point. Never accepts --model: the tag comes from
        resolve_model() (the Task 3 seam), never from a CLI flag or a default.

    Inputs:
        argv (list[str] | None): argument vector (defaults to sys.argv[1:]).

    Outputs:
        result (int): process exit code, 0 only when a generation was
        produced AND passed every gate.
    --------------------------------------------------------------------------
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Deterministic Ollama HTTP bridge (D1-D7). No --model: the tag comes "
                     "from the Task 3 resolver via resolve_model()."
    )
    parser.add_argument("--prompt-file", type=Path, required=True, dest="prompt_file")
    parser.add_argument("--verify", type=str, default=None, dest="verify_command")
    parser.add_argument("--target", type=Path, default=None, dest="target_path")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--role", type=str, default=None, dest="role",
        help="task kind this call is doing (writer, coder, ... as declared in "
             "qualification/tasks.json). The resolver returns the tag adopted for that role; "
             "without it, the single overall 'current' tag is used, which is how local-coder "
             "ended up being served a writer model scoring 0/3 on the coder tasks (P4).",
    )
    parser.add_argument(
        "--log", type=Path, default=None, dest="log_path",
        help="override the attempt log path (default: ~/.claude/loop-bridge-log.jsonl, "
             "fix round 1 I4 - never a path inside this repository)",
    )
    parser.add_argument(
        "--vault-context", type=str, default=None, dest="vault_context",
        help="search terms; the matching vault notes are prepended to the prompt. The lookup "
             "happens HERE, in code, because a caller cannot be trusted to have done it: the "
             "local model answers a documented question with a fluent invention when it is "
             "given no context (measured 2026-08-14, it produced the non-existent LaTeX "
             "command \\endminitoc while the vault held the real answer).",
    )
    parser.add_argument(
        "--no-vault-context", action="store_true", dest="no_vault_context",
        help="explicitly answer WITHOUT the vault. Required when --vault-context is absent: "
             "omitting both is an error, so the consultation can never be skipped by silence.",
    )
    args = parser.parse_args(argv)

    # Omission is an ERROR, not a default. This is the whole point: a rule that lives only in
    # an agent definition gets skipped by the first caller in a hurry, which is exactly how
    # the invented command reached a user. Saying "no vault" stays possible, but only out loud.
    if not args.vault_context and not args.no_vault_context:
        print(
            "[BRIDGE] refusing: no vault context. Pass --vault-context '<terms>' so the vault "
            "answers the question, or --no-vault-context to state deliberately that this call "
            "does not need it. Silence is not an acceptable answer here.",
            file=sys.stderr,
        )
        return 2
    if args.vault_context and args.no_vault_context:
        print("[BRIDGE] refusing: --vault-context and --no-vault-context are contradictory.",
              file=sys.stderr)
        return 2

    prompt_path = args.prompt_file
    if args.vault_context:
        notes = collect_vault_context(args.vault_context)
        if not notes:
            print(
                f"[BRIDGE] refusing: the vault has nothing on {args.vault_context!r}. Answering "
                "anyway would be answering from the model's own memory, which is what this "
                "guard exists to prevent. Refine the terms, or pass --no-vault-context.",
                file=sys.stderr,
            )
            return 2
        prompt_path = write_prompt_with_vault_context(prompt_path, notes)

    return run_bridge(
        prompt_path=prompt_path,
        verify_command=args.verify_command,
        target_path=args.target_path,
        seed=args.seed,
        log_path=args.log_path,
        role=args.role,
    )


if __name__ == "__main__":
    sys.exit(main())
