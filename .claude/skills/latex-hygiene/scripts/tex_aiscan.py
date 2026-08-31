"""
tex_aiscan - subcommand `aiscan`: AI-usage style risk score.

Stage: latex-hygiene pipeline, register/AI-style measurement. Reproduces
paper-auditor.md Step 7.5 signal by signal (weights, phrase list, sliding-
window sentence-uniformity check, and the risk_score formula), merges in the
four compose_audit.py behaviours (section attribution, pronoun scan, list
detection, three extra forbidden characters routed to the `chars` subcommand
instead) via tex_aiscan_text, and reuses aiscan.py's `(?<!-)--(?!-)` double-
dash isolation verbatim.

Weight numbers: WEIGHT_NUMERIC fixes High=2, Medium=1. These two numbers are
now stated explicitly in .claude/agents/paper-auditor.md Step 7.5, alongside
the qualitative High/Medium labels; the two must always change together.
"""

import logging
import re
import statistics
from typing import Dict, List, Optional

from tex_aiscan_text import (
    build_sections,
    extract_prose,
    scan_lists,
    scan_pronouns,
    sentence_lengths,
    sentence_uniformity,
)
from tex_common import build_line_starts, excerpt_words, line_at, read_text

logger = logging.getLogger(__name__)

AI_PHRASES = [
    "Furthermore,", "Moreover,", "Additionally,", "It is worth noting",
    "It is important to note", "In conclusion,", "Notably,",
]
_PHRASE_PATTERNS = {p: re.compile(r"(?m)(^|\.\s+|\}\s+)" + re.escape(p)) for p in AI_PHRASES}
_DOUBLE_DASH = re.compile(r"(?<!-)--(?!-)")

_EM_DASH_CHARS = "—"
_SMART_QUOTE_CHARS = "‘’“”"
_ZWSP_CHARS = "​"
_ZWJ_ZWNJ_CHARS = "‌‍"
_ELLIPSIS_CHARS = "…"

# Numeric weight mapping (see module docstring): kept alongside the signal
# table so the two never drift silently out of sync.
WEIGHT_NUMERIC = {"High": 2, "Medium": 1}

_SIGNAL_TABLE = {
    "em_dash": "High",
    "smart_quotes": "Medium",
    "zero_width_space": "High",
    "zwj_zwnj": "High",
    "ellipsis": "Medium",
    "ai_transition_phrase": "Medium",
    "sentence_length_uniformity": "High",
    "perfect_parallel_list": "Medium",
}


def _empty_signals() -> Dict[str, Dict]:
    return {name: {"weight": weight, "count": 0, "hits": []} for name, weight in _SIGNAL_TABLE.items()}


def _hit(path: str, line: int, text: str, pos: int, section_map: Optional[Dict]) -> Dict:
    from tex_aiscan_text import section_of
    return {
        "file": path,
        "line": line,
        "section": section_of(line, section_map),
        "excerpt": excerpt_words(text, pos),
    }


def _char_hits(text: str, starts: List[int], chars: str, path: str, section_map: Optional[Dict]) -> List[Dict]:
    return [_hit(path, line_at(i, starts), text, i, section_map)
            for i, ch in enumerate(text) if ch in chars]


def scan_aiscan(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute the AI-usage style risk score for one or more .tex files,
        with the same signals, weights, and formula as paper-auditor.md
        Step 7.5, plus section attribution, pronoun hits, and list hits.

    Inputs:
        files (List[str]): .tex files to scan. Section attribution runs only
            when exactly one file is given; with more than one, hits fall
            back to per-file reporting (each hit still carries "file").

    Outputs:
        result (Dict): {"files": List[str], "single_file_mode": bool,
            "risk_score": int, "flag": str, "raw_count": float,
            "weight_map": Dict, "signals": Dict, "sentence_stats": Dict,
            "pronouns": List[Dict], "lists": List[Dict], "sections": List[Dict]}.
    --------------------------------------------------------------------------
    """
    single_file_mode = len(files) == 1
    signals = _empty_signals()
    all_pronouns: List[Dict] = []
    all_lists: List[Dict] = []
    prose_parts: List[str] = []
    last_section_map: Optional[Dict] = None

    for path in files:
        text = read_text(path)
        starts = build_line_starts(text)
        section_map = build_sections(text) if single_file_mode else None
        last_section_map = section_map

        signals["em_dash"]["hits"].extend(_char_hits(text, starts, _EM_DASH_CHARS, path, section_map))
        for m in _DOUBLE_DASH.finditer(text):
            signals["em_dash"]["hits"].append(_hit(path, line_at(m.start(), starts), text, m.start(), section_map))
        signals["smart_quotes"]["hits"].extend(_char_hits(text, starts, _SMART_QUOTE_CHARS, path, section_map))
        signals["zero_width_space"]["hits"].extend(_char_hits(text, starts, _ZWSP_CHARS, path, section_map))
        signals["zwj_zwnj"]["hits"].extend(_char_hits(text, starts, _ZWJ_ZWNJ_CHARS, path, section_map))
        signals["ellipsis"]["hits"].extend(_char_hits(text, starts, _ELLIPSIS_CHARS, path, section_map))

        for phrase, pattern in _PHRASE_PATTERNS.items():
            for m in pattern.finditer(text):
                pos = m.start() + len(m.group(1))
                hit = _hit(path, line_at(pos, starts), text, pos, section_map)
                hit["phrase"] = phrase
                signals["ai_transition_phrase"]["hits"].append(hit)

        all_pronouns.extend(scan_pronouns(text, section_map, path))
        for entry in scan_lists(text, section_map):
            entry["file"] = path
            all_lists.append(entry)
            if entry["parallel"]:
                signals["perfect_parallel_list"]["hits"].append({
                    "file": path, "line": entry["line"], "section": entry["section"],
                    "env": entry["env"], "item_count": entry["item_count"],
                })

        prose_parts.append(extract_prose(text))

    full_prose = " ".join(prose_parts)
    sentences, lengths = sentence_lengths(full_prose)
    uniformity = sentence_uniformity(lengths)
    if uniformity and uniformity["flagged"]:
        signals["sentence_length_uniformity"]["hits"] = [{
            "min_window_stdev": uniformity["min_window_stdev"],
            "min_window_start_sentence": uniformity["min_window_start_sentence"],
        }]

    for sig in signals.values():
        sig["count"] = len(sig["hits"])

    raw_count = sum(WEIGHT_NUMERIC[sig["weight"]] * sig["count"] for sig in signals.values())
    total_prose_sentences = len(sentences)
    risk_score = min(100, round(raw_count / total_prose_sentences * 100)) if total_prose_sentences else 0
    flag = "[AI RISK HIGH]" if risk_score >= 10 else "[AI RISK LOW]"

    logger.info(
        "[HYGIENE] aiscan: risk_score=%d raw_count=%s sentences=%d",
        risk_score, raw_count, total_prose_sentences,
    )

    return {
        "files": files,
        "single_file_mode": single_file_mode,
        "risk_score": risk_score,
        "flag": flag,
        "raw_count": raw_count,
        "weight_map": WEIGHT_NUMERIC,
        "signals": signals,
        "sentence_stats": {
            "count": total_prose_sentences,
            "mean_length": statistics.mean(lengths) if lengths else 0,
            "pstdev": statistics.pstdev(lengths) if len(lengths) > 1 else 0,
            "min_window_stdev": uniformity["min_window_stdev"] if uniformity else None,
            "min_window_start_sentence": uniformity["min_window_start_sentence"] if uniformity else None,
        },
        "pronouns": all_pronouns,
        "lists": all_lists,
        "sections": (last_section_map["sections"] if (single_file_mode and last_section_map) else []),
    }
