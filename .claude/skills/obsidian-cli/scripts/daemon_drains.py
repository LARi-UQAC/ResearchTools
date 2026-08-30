#!/usr/bin/env python3
"""
daemon_drains.py - the deferred half of the vault event daemon.

Filing a note is fast. Organising the vault is slow, so it is decoupled: the
event path only queues, and these drains run on a quiet interval or by hand.
At the measured 36.991 s median call time, judging fifteen candidate pairs
inline would pin the GPU for about ten minutes per drop.

Consolidation drain. vault_consolidate.py computes the candidate pairs; the
local model judges each one, and Python appends the accepted edges. The
computation is reached through the CLI rather than by importing a function,
because the scoring lives inside that script's main() and its JSON output is
already the contract; re-implementing the scoring here would create a second
truth that drifts from the one 35 tests pin.

The test given to the model is deliberately strict:

    do the two notes share a MECHANISM - the same tool, the same failure mode,
    the same root cause - such that someone who hit one would want to be told
    about the other?

Sharing a topic or a tag is a rejection, and rejections are the valuable
output. A graph optimised for edge count becomes a hairball, which is worse
than disconnection because it looks healthy.

The dead-link drain lives next door in daemon_phantoms.py: it edits
existing notes in place, which needs a different safety net.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daemon_states as ds  # noqa: E402
import outbox_io  # noqa: E402
import vault_journal  # noqa: E402
from daemon_states import ob  # noqa: E402

CONSOLIDATE = SCRIPTS / "vault_consolidate.py"

EDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "shares_mechanism": {"type": "boolean"},
        "mechanism": {"type": "string"},
        "sentence": {"type": "string"},
    },
    "required": ["shares_mechanism", "mechanism", "sentence"],
}

JUDGE_PREFIX = (
    "You decide whether two notes of a knowledge vault deserve a link.\n"
    "They deserve one only if they share a MECHANISM: the same tool, the same\n"
    "failure mode, or the same root cause, such that someone who hit one would\n"
    "want to be told about the other.\n"
    "Sharing a subject, a technology or a tag is NOT a mechanism. Reject those.\n"
    "Rejecting is the expected answer for most pairs, and costs nothing.\n"
    "When you accept, name the shared mechanism in a few words, and write one\n"
    "sentence, in French, saying what the two notes share. No wiki link in the\n"
    "sentence: the caller adds it.\n"
    "Answer with the JSON object only.\n"
)


def candidate_pairs(vault: Path, top_n: int, timeout_s: float) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the deterministic candidate computation and return its pairs.

    Inputs:
        vault (Path): the vault root
        top_n (int): how many candidates to ask for
        timeout_s (float): bounded, like every subprocess call (R10)

    Outputs:
        candidates (list): the report's candidate objects, each carrying the
        two note paths and the evidence that scored them.
    --------------------------------------------------------------------------
    """
    result = subprocess.run(
        [sys.executable, str(CONSOLIDATE), "--vault", str(vault),
         "--mode", "candidates", "--top", str(top_n)],
        capture_output=True, text=True, timeout=timeout_s)
    if result.returncode != 0:
        raise ds.EventRefused(
            f"candidate computation failed: {outbox_io.tail(result.stderr)}")
    try:
        return json.loads(result.stdout).get("candidates", [])
    except ValueError as exc:
        raise ds.EventRefused(f"candidate report is not JSON: {exc}") from exc


def note_excerpt(vault: Path, rel: str, max_chars: int) -> str:
    """One note's share of the window. The whole vault never fits, and a pair
    judged on truncated evidence is still judged on the part that states the
    problem, which is where a note's mechanism is written."""
    path = Path(vault) / rel
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except OSError:
        return ""


def judge_edge(vault: Path, pair: dict, model: str, window: int,
               timeout: float, max_chars: int) -> dict:
    """Ask the local model about ONE pair. One pair per call keeps the variable
    region small, so the fixed prefix stays cached."""
    a, b = pair.get("a"), pair.get("b")
    prompt = (JUDGE_PREFIX
              + f"\nNote A ({a}):\n{note_excerpt(vault, a, max_chars)}\n"
              + f"\nNote B ({b}):\n{note_excerpt(vault, b, max_chars)}\n")
    raw = ds.call_model(prompt, model, window, timeout, fmt=EDGE_SCHEMA)
    try:
        verdict = json.loads(raw)
    except ValueError as exc:
        raise ds.EventRefused(f"edge verdict is not JSON: {exc}") from exc
    verdict["a"], verdict["b"] = a, b
    return verdict


def append_edge(vault: Path, rel_self: str, rel_other: str, sentence: str,
                journal_path) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Add one edge to one note: the sentence saying what the pair shares,
        followed by the link. A bare link with no sentence is not an edge, it
        is clutter.

    Inputs:
        vault (Path), rel_self (str): the note being edited
        rel_other (str): the note being linked to
        sentence (str): the justification, from the model
        journal_path (Path | None): the recovery record

    Outputs:
        ok (bool): False when the note is missing or the link is already there,
        so a re-drained queue never doubles an edge.
    --------------------------------------------------------------------------
    """
    target = Path(vault) / rel_self
    if not target.exists():
        return False
    name = Path(rel_other).stem
    text = target.read_text(encoding="utf-8")
    if f"[[{name}]]" in text:
        return False
    before = target.stat().st_size
    if journal_path is not None:
        vault_journal.record(journal_path, rel_self, before, None,
                             "consolidation drain", vault_journal.STATE_PENDING)
    addition = f"\n{sentence.strip()} [[{name}]]\n"
    target.write_text(text.rstrip() + "\n" + addition, encoding="utf-8",
                      newline="")
    after = target.stat().st_size
    if journal_path is not None:
        vault_journal.record(journal_path, rel_self, before, after,
                             "consolidation drain", vault_journal.STATE_EDGE)
    return after > before


def drain_consolidation(vault: Path, model: str, window: int, config: dict,
                        journal_path=None, lock=None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Judge the queued candidates and write the accepted edges reciprocally.

    Inputs:
        vault (Path), model (str), window (int): the run
        config (dict): daemon-config.json, for the bounds
        journal_path (Path | None): the recovery record
        lock: a context manager serializing the writes, or None in a test

    Outputs:
        report (dict): accepted and rejected pairs with their reasons. A drain
        rejecting almost nothing means the mechanism test is not being applied,
        which is the hairball this design is trying to avoid.
    --------------------------------------------------------------------------
    """
    import outbox_io
    top_n = outbox_io.require(config, "daemon", "consolidate_top_n")
    max_pairs = outbox_io.require(config, "daemon", "judge_edge_max_pairs")
    timeout = outbox_io.require(config, "probe", "request_timeout_s")
    max_chars = ob.MAX_VAULT_NOTE_CHARS

    report = {"accepted": [], "rejected": [], "errors": []}
    pairs = candidate_pairs(vault, top_n, timeout)[:max_pairs]
    for pair in pairs:
        try:
            verdict = judge_edge(vault, pair, model, window, timeout, max_chars)
        except (ds.EventRefused, ob.BridgeError) as exc:
            report["errors"].append({"pair": [pair.get("a"), pair.get("b")],
                                     "why": str(exc)})
            continue
        if not verdict.get("shares_mechanism"):
            report["rejected"].append({"pair": [verdict["a"], verdict["b"]],
                                       "why": verdict.get("mechanism", "")})
            continue
        sentence = verdict.get("sentence", "").strip()
        if not sentence:
            report["rejected"].append({"pair": [verdict["a"], verdict["b"]],
                                       "why": "accepted with no sentence"})
            continue
        context = lock if lock is not None else _null_context()
        with context:
            first = append_edge(vault, verdict["a"], verdict["b"], sentence,
                                journal_path)
            second = append_edge(vault, verdict["b"], verdict["a"], sentence,
                                 journal_path)
        report["accepted"].append({"pair": [verdict["a"], verdict["b"]],
                                   "mechanism": verdict.get("mechanism", ""),
                                   "written": [first, second]})
    return report


def drain_graphify(paths: list, repo_root: Path, timeout_s: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refresh the repository's knowledge graph over the queued paths, in one
        call. Never on the event path: a Markdown note is a document, so this
        needs a semantic pass, which is a model call on a possibly different
        tag, and with one loaded model that evicts the resident writer.

    Inputs:
        paths (list): the queued paths
        repo_root (Path): the repository whose graph is refreshed
        timeout_s (float): bounded (R10)

    Outputs:
        report (dict): skipped with a reason, or the command's outcome.
    --------------------------------------------------------------------------
    """
    if not paths:
        return {"skipped": "nothing queued"}
    if not (Path(repo_root) / "graphify-out").is_dir():
        return {"skipped": "no graphify-out/ in this repository"}
    result = subprocess.run(["graphify", "update", *paths],
                            capture_output=True, text=True, timeout=timeout_s,
                            cwd=str(repo_root))
    return {"returncode": result.returncode,
            "stderr": outbox_io.tail(result.stderr)}


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
