#!/usr/bin/env python3
"""
stt_score.py - score speech-to-text candidates measured beside the resident LLM.

Pure: no model, no GPU, no file I/O. Takes the raw measurement report stt_bench.py writes
and the operator's reference text, and returns one row per candidate with a status:

  ranked        passed the VRAM gate, carries a score
  gated         measured, but it pushes too much of the LLM out of VRAM (or that share
                could not be measured) - informational figures, no score
  not runnable  the candidate never produced a measurement - its reason, no figures

The score is the weighted mean of accuracy (100 minus word error) and live-caption speed
(100 when the longest recording transcribes within the live budget, else proportional).
Speed is judged against the budget rather than against the fastest candidate because the
voice panel re-transcribes the growing buffer once per refresh: a model under the budget
keeps the caption live, and being faster than that is invisible to the speaker (measured
2026-09-26, see Test/fixtures/session_2026_09_26.json).
"""
import re
import unicodedata

from bench_config import value

_KEEP_DECIMAL = re.compile(r"(\d),(\d)")
_DROP = re.compile(r"[^\w'.\s]|(?<!\d)\.|\.(?!\d)")


def normalize(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce a transcript to the words a scorer should compare.

    Details:
        NFC, lower case, typographic apostrophe folded to "'", a decimal comma
        read as a point ("0,5" == "0.5"), punctuation dropped except a point
        between digits. Accents are kept: they change a French word.

    Inputs:
        text (str): a reference or a hypothesis

    Outputs:
        normalized (str): space-separated words
    --------------------------------------------------------------------------
    """
    t = unicodedata.normalize("NFC", text).lower().replace("’", "'")
    t = _KEEP_DECIMAL.sub(r"\1.\2", t)
    return " ".join(_DROP.sub(" ", t).split())


def edits(ref: list, hyp: list) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Levenshtein distance between two token sequences, with the edits named.

    Inputs:
        ref (list): reference tokens
        hyp (list): hypothesis tokens

    Outputs:
        (distance, named) (tuple[int, list[str]]): named edits in reading order,
        "ref->hyp" for a substitution, "ref->(missing)" for a deletion,
        "(extra)->hyp" for an insertion
    --------------------------------------------------------------------------
    """
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    named, i, j = [], n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                named.append(f"{ref[i - 1]}->{hyp[j - 1]}")
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            named.append(f"{ref[i - 1]}->(missing)")
            i -= 1
        else:
            named.append(f"(extra)->{hyp[j - 1]}")
            j -= 1
    return d[n][m], named[::-1]


def transcript_error(reference: dict, texts: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Word and character error rates of one candidate over every recording.

    Details:
        Micro-averaged: total edits over total reference length, so a long
        recording weighs more than a one-word confirmation. A recording with
        no transcript counts every reference word as an error.

    Inputs:
        reference (dict): recording name -> the operator's exact words
        texts (dict): recording name -> the candidate's transcript

    Outputs:
        error (dict): wer_pct, cer_pct, word_errors (list of named edits),
        ref_words (int)

    Raises:
        ValueError: the reference holds no word at all.
    --------------------------------------------------------------------------
    """
    word_edits = word_total = char_edits = char_total = 0
    named = []
    for name, ref_text in reference.items():
        ref, hyp = normalize(ref_text), normalize(texts.get(name, ""))
        dw, nw = edits(ref.split(), hyp.split())
        dc, _ = edits(list(ref), list(hyp))
        word_edits, word_total = word_edits + dw, word_total + len(ref.split())
        char_edits, char_total = char_edits + dc, char_total + len(ref)
        named += nw
    if not word_total:
        raise ValueError("the reference holds no word to score against")
    return {"wer_pct": 100 * word_edits / word_total, "cer_pct": 100 * char_edits / char_total,
            "word_errors": named, "ref_words": word_total}


def _weights(config: dict) -> tuple:
    w_acc, w_speed = value(config, "weights", "accuracy"), value(config, "weights", "speed")
    if abs(w_acc + w_speed - 1.0) > 1e-9:
        raise ValueError(f"weights.accuracy + weights.speed must sum to 1, got {w_acc + w_speed}")
    return w_acc, w_speed


def _measured(row: dict, raw: dict, reference: dict, budget_s: float) -> dict:
    files = row["files"]
    longest = max(raw["audio_s"], key=raw["audio_s"].get)
    others = [files[f]["median_s"] for f in files if f != longest]
    err = transcript_error(reference, {f: v["text"] for f, v in files.items()})
    long_s = files[longest]["median_s"]
    out = {"wer_pct": err["wer_pct"], "cer_pct": err["cer_pct"], "word_errors": err["word_errors"],
           "longest_recording": longest, "long_s": long_s,
           "short_s": max(others) if others else None,
           "load_s": row.get("load_s"), "first_call_s": row.get("first_call_s"),
           "accuracy": max(0.0, 100 - err["wer_pct"]),
           "speed": 100.0 if long_s <= budget_s else 100 * budget_s / long_s}
    mem = row.get("memory") or {}
    before, after = mem.get("llm_dedicated_before_mib"), mem.get("llm_dedicated_after_mib")
    out["vram_mib"] = mem.get("dedicated_mib")
    out["llm_answer_s"] = (row.get("llm_answer_after") or {}).get("total_s")
    if before and after is not None:
        out["llm_demoted_mib"] = max(0, before - after)
        out["llm_demoted_pct"] = 100 * out["llm_demoted_mib"] / before
    return out


def score_report(raw: dict, reference: dict, config: dict) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Score every candidate of one raw measurement report and rank them.

    Inputs:
        raw (dict): stt_bench.py's raw report (audio_s, candidates)
        reference (dict): recording name -> the operator's exact words
        config (dict): parsed stt-bench-config.json (live_budget_ms, gate,
            weights)

    Outputs:
        rows (list[dict]): ranked rows by descending score, then gated rows,
        then not-runnable rows. Every row has model, compute_type, engine and
        status; ranked rows carry score; the others carry reason and no score.

    Raises:
        KeyError: a configuration key is absent (R3).
        ValueError: the weights do not sum to 1, or the reference is empty.
    --------------------------------------------------------------------------
    """
    budget_s = value(config, "live_budget_ms") / 1000
    max_demoted = value(config, "gate", "max_llm_demoted_pct")
    w_acc, w_speed = _weights(config)
    ranked, gated, broken = [], [], []
    for row in raw["candidates"]:
        head = {k: row.get(k) for k in ("model", "compute_type", "engine")}
        if "error" in row or "files" not in row:
            broken.append(head | {"status": "not runnable",
                                  "reason": row.get("error", "no measurement recorded")})
            continue
        out = head | _measured(row, raw, reference, budget_s)
        if "llm_demoted_pct" not in out:
            gated.append(out | {"status": "gated",
                                "reason": "the LLM's VRAM residency could not be measured"})
        elif out["llm_demoted_pct"] > max_demoted:
            gated.append(out | {"status": "gated",
                                "reason": f"pushes {out['llm_demoted_pct']:.1f}% of the LLM out "
                                          f"of VRAM (gate {max_demoted}%)"})
        else:
            ranked.append(out | {"status": "ranked",
                                 "score": w_acc * out["accuracy"] + w_speed * out["speed"]})
    ranked.sort(key=lambda r: (-r["score"], r["long_s"]))
    return ranked + gated + broken


def _fmt(v, spec: str, unit: str = "") -> str:
    return "-" if v is None else format(v, spec) + unit


def render_table(rows: list) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render scored rows as the markdown selection table.

    Inputs:
        rows (list[dict]): the output of score_report

    Outputs:
        table (str): a markdown table, winner first, every unranked row with
        its reason in the Score column
    --------------------------------------------------------------------------
    """
    head = ("| # | Model | Word error | Wrong words | Longest rec. | Short rec. | Load | "
            "VRAM | LLM pushed out | Accuracy | Speed | Score |")
    lines = [head, "|" + "---|" * 12]
    rank = 0
    for r in rows:
        name = f"{r['model']} {r.get('compute_type') or ''}".strip()
        if r["status"] == "not runnable":
            lines.append(f"| - | {name} | - | - | - | - | - | - | - | - | - | "
                         f"not runnable: {r['reason']} |")
            continue
        rank += r["status"] == "ranked"
        score = f"**{r['score']:.1f}**" if r["status"] == "ranked" else f"gated: {r['reason']}"
        pushed = ("-" if r.get("llm_demoted_mib") is None
                  else f"{r['llm_demoted_mib']} MiB ({r['llm_demoted_pct']:.1f}%)")
        lines.append(
            f"| {rank if r['status'] == 'ranked' else '-'} | {name} | {r['wer_pct']:.1f}% | "
            f"{', '.join(r['word_errors']) or 'none'} | {_fmt(r['long_s'], '.2f', ' s')} | "
            f"{_fmt(r['short_s'], '.2f', ' s')} | {_fmt(r['load_s'], '.1f', ' s')} | "
            f"{_fmt(r['vram_mib'], 'd', ' MiB')} | {pushed} | {r['accuracy']:.1f} | "
            f"{r['speed']:.1f} | {score} |")
    return "\n".join(lines)
