#!/usr/bin/env python3
"""
tune_preflight.py - the refusals and the comparison behind tune-new-model.ps1.

The runbook from "a model is on disk" to "the resolver serves it" is five steps: tune it for
this card, score it against the frozen task set, compare it with every other candidate,
adopt it or not, then confirm what is served. Steps 1 to 3 are mechanical and belong in a
harness; step 4 changes what every local agent executes, so it stays a command a human types.

This module is the part of that harness a test can reach. tune-new-model.ps1 spawns
processes and cannot be exercised offline, so everything that DECIDES lives here: which
preconditions refuse the run, and how the measured field is presented to the person who has
to choose. The PowerShell keeps only sequencing.

Names no model tag (R2). The tuned variant's name comes from vram_optimizer, the installed
list from model_resolver, and the measured window from context_budget, so this module adds
no fourth truth about any of them.

Exit codes (R12): 0 proceed, 2 refusal by design, 1 failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import vram_optimizer

_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parents[2] / "loop-engineer" / "scripts"
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

import context_budget  # noqa: E402
import model_resolver  # noqa: E402

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSED = 2


def installed_tags() -> tuple[list[str], str | None]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask the resolver what Ollama has installed. Reachability is answered by
        the same call, since an unreachable daemon cannot list anything: two
        separate probes would be two chances to disagree.

    Inputs:
        none.

    Outputs:
        result (tuple): (tags, error). On failure tags is empty and error is
            the resolver's own message, which already names the cause.
    --------------------------------------------------------------------------
    """
    try:
        return list(model_resolver.list_installed_models()), None
    except model_resolver.ResolverError as exc:
        return [], str(exc)
    except OSError as exc:
        return [], f"[TUNE] cannot reach Ollama: {exc}"


def check_tune(base_tag: str, tags: list[str], list_error: str | None) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refusals that apply BEFORE the sweep: is there a daemon, is the tag on
        this machine, and is it a base tag rather than something already tuned.

    Inputs:
        base_tag (str): the tag the operator named.
        tags (list[str]): installed tags.
        list_error (str | None): why the listing failed, if it did.

    Outputs:
        result (list[str]): refusal messages, empty when the run may proceed.
    --------------------------------------------------------------------------
    """
    refusals: list[str] = []
    if not base_tag or not base_tag.strip():
        refusals.append("[TUNE] no tag given. The tag is an argument, never a default: "
                        "this harness names no model.")
        return refusals
    if list_error:
        refusals.append(list_error)
        return refusals
    if not tags:
        refusals.append("[TUNE] Ollama reports no installed model, so there is nothing to "
                        "tune. Pull the model first.")
        return refusals
    if base_tag.endswith(vram_optimizer.TUNED_TAG_SUFFIX):
        refusals.append(
            f"[TUNE] '{base_tag}' is already a tuned tag (it ends in "
            f"'{vram_optimizer.TUNED_TAG_SUFFIX}'). Pass the BASE tag; the sweep builds the "
            "tuned variant itself, and tuning a tuned tag measures a model twice removed "
            "from what you downloaded.")
    if base_tag not in tags:
        refusals.append(
            f"[TUNE] '{base_tag}' is not installed. Ollama reports {len(tags)} tag(s); the "
            "name must match one of them exactly, including its ':' suffix.")
    return refusals


def check_score(tuned_tag: str, tags: list[str], list_error: str | None,
                config_path: Path) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refusals that apply between the sweep and the scoring: the sweep must
        have produced the tuned tag AND a measured window for it. Scoring a tag
        with no measured window is exactly the case model_resolver reports as
        NOT RUNNABLE, and reaching that state through this harness means the
        sweep failed quietly a step earlier.

    Inputs:
        tuned_tag (str): the tag the sweep was to build.
        tags (list[str]): installed tags, re-read after the sweep.
        list_error (str | None): why the listing failed, if it did.
        config_path (Path): local-model-config.json.

    Outputs:
        result (list[str]): refusal messages, empty when scoring may proceed.
    --------------------------------------------------------------------------
    """
    refusals: list[str] = []
    if list_error:
        return [list_error]
    if tuned_tag not in tags:
        refusals.append(
            f"[TUNE] the sweep did not leave '{tuned_tag}' installed, so there is nothing to "
            "score. Read the sweep's own refusal above rather than re-running this step.")
    try:
        window = context_budget.read_retained_num_ctx(config_path, tuned_tag)
    except context_budget.ConfigError as exc:
        refusals.append(
            f"[TUNE] no measured context window for '{tuned_tag}': {exc} A tag with no "
            "measurement is reported NOT RUNNABLE and never asked to run a task, so scoring "
            "it would print zeros that look like failures.")
    else:
        if window <= 0:
            refusals.append(f"[TUNE] '{tuned_tag}' measures a non-positive window ({window}).")
    return refusals


def rank_rows(matrix: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Order the --matrix rows the way the decision is actually made: by the
        role's own score first, then by the total across every role, then by
        name so two equal candidates always print in the same order.

    Inputs:
        matrix (dict): the structure model_resolver --matrix --json emits.
        role (str): the role being filled.

    Outputs:
        result (list[dict]): one record per tag, runnable rows first.
    --------------------------------------------------------------------------
    """
    out: list[dict[str, Any]] = []
    for tag, row in matrix.get("rows", {}).items():
        runnable = bool(row.get("runnable"))
        by_kind = row.get("by_kind", {}) if runnable else {}
        kind = by_kind.get(role, {}) if isinstance(by_kind, dict) else {}
        budget = row.get("budget", {}) if runnable else {}
        out.append({
            "tag": tag,
            "runnable": runnable,
            "why": row.get("why", ""),
            "role_passed": kind.get("passed", 0),
            "role_total": kind.get("total", 0),
            "passed": row.get("passed", 0) if runnable else 0,
            "total": row.get("total", 0) if runnable else 0,
            "num_ctx": budget.get("num_ctx"),
            "decode_tps": budget.get("decode_tps"),
        })
    out.sort(key=lambda r: (not r["runnable"], -r["role_passed"], -r["passed"], r["tag"]))
    return out


def summarize(matrix: dict[str, Any], candidate: str, role: str,
              incumbent: str | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say where the new tag landed and what the operator has to decide. It
        states the comparison and stops: adoption is a separate command, run by
        a person, because it changes which model every local agent executes.

    Inputs:
        matrix (dict): model_resolver --matrix --json output.
        candidate (str): the tuned tag just measured.
        role (str): the role being filled.
        incumbent (str | None): the tag currently serving that role, if any.

    Outputs:
        result (str): the report, ready to print.
    --------------------------------------------------------------------------
    """
    rows = rank_rows(matrix, role)
    width = max([len(r["tag"]) for r in rows] + [len("model")]) + 2
    lines = ["", f"Candidates for the {role} role, best first", "",
             "model".ljust(width) + role.ljust(10) + "all".ljust(10)
             + "num_ctx".ljust(10) + "tok/s"]
    for r in rows:
        if not r["runnable"]:
            lines.append(r["tag"].ljust(width) + "NOT RUNNABLE: " + r["why"])
            continue
        tps = "-" if r["decode_tps"] is None else f"{r['decode_tps']:.2f}"
        lines.append(
            r["tag"].ljust(width)
            + f"{r['role_passed']}/{r['role_total']}".ljust(10)
            + f"{r['passed']}/{r['total']}".ljust(10)
            + str(r["num_ctx"] if r["num_ctx"] is not None else "-").ljust(10)
            + tps)

    by_tag = {r["tag"]: r for r in rows}
    cand = by_tag.get(candidate)
    inc = by_tag.get(incumbent) if incumbent else None
    lines += ["", "What this measured"]
    if cand is None:
        lines.append(f"  '{candidate}' is not in the matrix. --matrix scores tags that are "
                     "BOTH declared and installed, so the sweep's declaration did not land.")
    elif not cand["runnable"]:
        lines.append(f"  '{candidate}' is NOT RUNNABLE: {cand['why']}")
    else:
        lines.append(f"  {candidate}: {cand['role_passed']}/{cand['role_total']} on {role} "
                     f"tasks, {cand['passed']}/{cand['total']} overall.")
        if inc is None:
            lines.append(f"  No tag is currently adopted for {role}, so there is no "
                         "incumbent to beat, only the field above.")
        elif inc["tag"] == candidate:
            lines.append(f"  It is already the adopted {role} tag.")
        else:
            delta = cand["role_passed"] - inc["role_passed"]
            verdict = ("ahead of" if delta > 0 else "behind" if delta < 0 else "level with")
            lines.append(f"  Incumbent {inc['tag']}: {inc['role_passed']}/{inc['role_total']} "
                         f"on {role}. The candidate is {verdict} it.")

    lines += ["", "The decision is yours - nothing above changed what is served.",
              "  Adopt:   model_resolver.py --qualify <TAG> --role " + role,
              "  Confirm: model_resolver.py --resolve --role " + role,
              "This harness stops here on purpose: --qualify is the only step that changes "
              "which tag the local agents execute."]
    return "\n".join(lines)


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    """Print refusals as JSON or as text, and return the matching exit code."""
    refusals = payload["refusals"]
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in refusals:
            print(line, file=sys.stderr)
    return EXIT_REFUSED if refusals else EXIT_OK


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI: one phase check, or the post-matrix summary."""
    parser = argparse.ArgumentParser(
        prog="tune_preflight",
        description="Preconditions and comparison for the tune-new-model runbook. Measures "
                    "nothing itself and adopts nothing.")
    parser.add_argument("--phase", choices=("tune", "score"),
                        help="which set of refusals to apply")
    parser.add_argument("--tag", help="the tag being tuned (phase tune) or scored (phase "
                                      "score, and the candidate for --summarize)")
    parser.add_argument("--role", help="the role being filled, for --summarize")
    parser.add_argument("--incumbent", default=None,
                        help="the tag currently adopted for that role, if any")
    parser.add_argument("--config", default=str(context_budget.DEFAULT_CONFIG_PATH),
                        help="local-model-config.json")
    parser.add_argument("--summarize", metavar="MATRIX_JSON",
                        help="render the decision from a saved --matrix --json file")
    parser.add_argument("--tuned-tag", action="store_true",
                        help="print the tuned variant's name for a base tag and exit")
    parser.add_argument("--json", action="store_true", help="machine-readable output (R17)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. 0 proceed, 2 refusal by design, 1 failure."""
    args = build_arg_parser().parse_args(argv)

    if args.tuned_tag:
        if not args.tag:
            print("[TUNE] --tuned-tag needs --tag", file=sys.stderr)
            return EXIT_FAILURE
        print(vram_optimizer.tuned_tag_for(args.tag))
        return EXIT_OK

    if args.summarize:
        if not args.tag or not args.role:
            print("[TUNE] --summarize needs --tag and --role", file=sys.stderr)
            return EXIT_FAILURE
        path = Path(args.summarize)
        try:
            matrix = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[TUNE] cannot read the matrix at {path}: {exc}", file=sys.stderr)
            return EXIT_FAILURE
        print(summarize(matrix, args.tag, args.role, args.incumbent))
        return EXIT_OK

    if not args.phase:
        print("[TUNE] one of --phase, --summarize or --tuned-tag is required",
              file=sys.stderr)
        return EXIT_FAILURE

    tags, error = installed_tags()
    if args.phase == "tune":
        refusals = check_tune(args.tag or "", tags, error)
    else:
        refusals = check_score(args.tag or "", tags, error, Path(args.config))
    return _emit({"phase": args.phase, "tag": args.tag, "refusals": refusals}, args.json)


if __name__ == "__main__":
    sys.exit(main())
