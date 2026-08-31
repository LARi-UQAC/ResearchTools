"""
tex_report - presentation and gating helpers for tex_check.py.

Stage: latex-hygiene pipeline, dispatch and output. Split out of
tex_check.py on 2026-08-27 to keep the CLI entry point under the repo's
per-file token ceiling (.claude/rules/code-style.md): plain-text rendering
and the --strict defect predicate are pure formatting and pure predicate
logic, carrying no argparse state, so they move here cleanly while
tex_check.py keeps the argument parser and the subcommand dispatch.
"""

import json
import logging
from typing import Dict

from tex_scan import has_scan_defect

logger = logging.getLogger(__name__)


def has_defect(command: str, result: Dict) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a result represents a hygiene defect, for the
        --strict exit code. wc is purely informational (word counts and page
        estimates are not pass/fail) and never trips --strict.

    Inputs:
        command (str): the subcommand name.
        result (Dict): that subcommand's result dict.

    Outputs:
        defect (bool): True if --strict should cause a non-zero exit.
    --------------------------------------------------------------------------
    """
    if command == "chars":
        return result.get("total", 0) > 0
    if command == "aiscan":
        return result.get("risk_score", 0) >= 10
    if command == "wc":
        return False
    if command == "abstract":
        return not result.get("abstract_found", True)
    if command == "braces":
        return (not result.get("balanced", True)) or (not result.get("env_balanced", True))
    if command == "par":
        return result.get("total", 0) > 0
    if command == "citecov":
        return bool(result.get("dangling"))
    if command == "refcov":
        return bool(result.get("uncited_labels") or result.get("dangling_references")
                     or result.get("duplicate_labels"))
    if command == "build":
        return bool(result.get("errors")) or bool(result.get("undefined"))
    if command == "patch":
        return bool(result.get("fails"))
    if command == "scan":
        return has_scan_defect(result, result.get("fail_on_markers", False))
    if command == "all":
        return any(
            has_defect(name, sub)
            for name, sub in result.items()
            if isinstance(sub, dict) and "skipped" not in sub
        )
    return False


def print_text(command: str, result: Dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Plain-text rendering for interactive use. --json is the contract
        agents rely on; this path exists for a human running the script by
        hand and stays intentionally terse.

    Inputs:
        command (str): the subcommand name.
        result (Dict): that subcommand's result dict.

    Outputs:
        None. Writes to stdout.
    --------------------------------------------------------------------------
    """
    if command == "chars":
        for path, hits in result["files"].items():
            print("%-40s %s" % (path, "clean" if not hits else hits))
        print("TOTAL forbidden-char hits:", result["total"])
    elif command == "aiscan":
        print("risk_score: %d%% %s" % (result["risk_score"], result["flag"]))
        print("raw_count: %s over %d prose sentences" % (result["raw_count"], result["sentence_stats"]["count"]))
        for name, sig in result["signals"].items():
            print("  %-26s weight=%-6s count=%d" % (name, sig["weight"], sig["count"]))
        print("pronoun hits: %d | list environments: %d" % (len(result["pronouns"]), len(result["lists"])))
    elif command == "wc":
        if "rows" in result:
            print("%-26s %7s %7s %7s %7s" % ("section", "before", "after", "delta", "pct"))
            for row in result["rows"]:
                pct = "n/a" if row["pct"] is None else "%.1f%%" % row["pct"]
                print("%-26s %7d %7d %+7d %7s" % (row["file"], row["before"], row["after"], row["delta"], pct))
            print("TOTAL delta:", result["total_delta"])
        elif "total" in result and "files" in result and isinstance(next(iter(result["files"].values()), 0), int):
            for path, n in result["files"].items():
                print("%-40s %d" % (path, n))
            print("TOTAL accepted words:", result["total"])
        else:
            for path, info in result["files"].items():
                print("%-40s prose_words=%5d floats=%d" % (path, info["prose_words"], info["floats"]))
            print("TOTAL prose words (floats excluded):", result["total_prose_words"])
            print("estimated pages: %s (%d words/page)" % (result["estimated_pages"], result["words_per_page"]))
    elif command == "abstract":
        print("abstract words:", result["abstract_words"], "| keywords:", result["keyword_count"])
    elif command == "braces":
        for path, info in result["files"].items():
            print("%-40s final_depth=%3d first_negative_line=%s" % (
                path, info["final_depth"], info["first_negative_line"]))
            env = info["environments"]
            if env["first_mismatch"] or env["unclosed_at_eof"]:
                print("  environments: first_mismatch=%s unclosed_at_eof=%s" % (
                    env["first_mismatch"], env["unclosed_at_eof"]))
            else:
                print("  environments: OK")
    elif command == "par":
        for path, hits in result["files"].items():
            print("%-40s %s" % (path, "OK" if not hits else "PAR INSIDE MACRO -> " + str(hits)))
    elif command == "citecov":
        print("distinct cited:", result["cited_count"], "| bib entries:", result["bib_entry_count"])
        print("DANGLING (cited, no bib entry):", result["dangling"])
        print("UNCITED (in bib, never cited):", len(result["uncited"]))
    elif command == "refcov":
        print("labels:", result["label_count"], "| references:", result["reference_count"])
        print("UNCITED LABELS (defined, never referenced):", result["uncited_labels"])
        print("DANGLING REFERENCES (referenced, no label):", result["dangling_references"])
        print("DUPLICATE LABELS:", result["duplicate_labels"])
    elif command == "all":
        for name, sub in result.items():
            print("=== %s ===" % name)
            if "skipped" in sub:
                print("  skipped:", sub["skipped"])
            else:
                print_text(name, sub)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))  # accept / build / patch / scan
