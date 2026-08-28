#!/usr/bin/env python3
"""
vram_optimizer.py - the opt-local-vram-llm driver: search, decide, report.

Drives a two-axis search (num_ctx by OLLAMA_KV_CACHE_TYPE) over a tuned model variant,
retains the largest window that keeps the model fully resident in VRAM among the
configurations whose decode throughput clears a floor, then writes the measurement, rewrites
the Modelfile and declares the tag as a candidate for its role.

Reuses optimize_ollama.evaluate_rung by import so the repository keeps ONE implementation of
"measure a rung". Qualification against the frozen task set stays with model_resolver.py:
this module measures memory and speed, not code quality, and adopting a tag changes what the
local agents execute.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import vram_daemon
import vram_modelfile
import vram_probe

# optimize_ollama lives with the loop-engineer skill, which owns the bridge and the resolver
# that consume its measurements. Importing it here rather than copying the rung measurement
# is deliberate: two implementations of "measure a rung" would drift, and the drift would be
# invisible until the two disagreed about a model.
_LOOP_ENGINEER_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "loop-engineer" / "scripts"
)
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

import optimize_ollama  # noqa: E402

logger = logging.getLogger(__name__)

_MIB = 1024 * 1024
_CLAUDE_DIR = Path(__file__).resolve().parents[3]
_CANDIDATES_PATH = _CLAUDE_DIR / "local-models.json"

# Fraction of the best decode throughput observed ANYWHERE in the sweep that a configuration
# must still reach to stay eligible. At 0.90 a configuration that doubles the window while
# losing a tenth of the speed is kept; one that halves the speed is not.
DEFAULT_THROUGHPUT_FLOOR = 0.90

KV_CACHE_TYPES = vram_daemon.KV_CACHE_TYPES


class OptimizerError(Exception):
    """Raised when the search cannot proceed. Never degrades quietly."""


def select_configuration(
    records: list[dict[str, Any]],
    throughput_floor: float = DEFAULT_THROUGHPUT_FLOOR,
) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply the objective function to every measured configuration and return
        the retained one plus the reason each other was dropped.

        Three rules, in order. A configuration must be ADMISSIBLE: fully
        resident in VRAM, above the free-VRAM floor, and not clamped by the
        model's own maximum. Rule 1 outranks speed absolutely - a spilled
        configuration is refused however fast it measured, because that speed
        stops being reproducible the moment anything else touches the card.
        Among the admissible, throughput must reach a fraction of the best
        observed. Among those, the largest window wins, ties breaking on
        throughput.

    Inputs:
        records (list[dict]): one per measured (num_ctx, kv_cache_type) pair,
            carrying residency_ratio, min_free_mib, clamped_by_model_maximum
            and decode_tps.
        throughput_floor (float): fraction of the best observed decode
            throughput a configuration must still reach.

    Outputs:
        result (dict): {"retained": dict | None, "dropped": list of
        (record, reason), "best_decode_tps": float}. retained is None when
        nothing is admissible, which is a legitimate answer for a model whose
        weights nearly fill the card, not an error.

    Raises:
        OptimizerError: no configuration was measured at all.
    --------------------------------------------------------------------------
    """
    if not records:
        raise OptimizerError("[VRAM-OPT] no configuration was measured; nothing to select.")

    dropped: list[tuple[dict[str, Any], str]] = []
    admissible: list[dict[str, Any]] = []

    # Pass 1: admissibility. Rule 1 outranks speed absolutely, so it is settled before any
    # throughput number is even compared.
    for record in records:
        if record["residency_ratio"] < optimize_ollama.GPU_RESIDENCY_MIN_RATIO:
            dropped.append((record, (
                f"residency {record['residency_ratio']:.3f} below "
                f"{optimize_ollama.GPU_RESIDENCY_MIN_RATIO}: part of the model spilled to "
                "host memory"
            )))
        elif record["min_free_mib"] < optimize_ollama.MIN_FREE_MIB:
            dropped.append((record, (
                f"free VRAM {record['min_free_mib']} MiB below the "
                f"{optimize_ollama.MIN_FREE_MIB} MiB floor"
            )))
        elif record["clamped_by_model_maximum"]:
            dropped.append((record, "clamped by the model's own context maximum"))
        else:
            admissible.append(record)

    if not admissible:
        return {"retained": None, "dropped": dropped, "best_decode_tps": 0.0}

    # The reference is the best throughput among ADMISSIBLE configurations, not among all of
    # them. Measured while testing on 2026-08-27: a spilled rung that reported a high decode
    # rate would otherwise set a reference no usable configuration could reach, and the tool
    # would retain nothing while a perfectly good window sat in the list. An inadmissible
    # configuration must never get a vote on what counts as fast.
    best_decode_tps = max(r["decode_tps"] for r in admissible)

    eligible: list[dict[str, Any]] = []
    for record in admissible:
        if record["decode_tps"] < throughput_floor * best_decode_tps:
            dropped.append((record, (
                f"decode {record['decode_tps']:.1f} tok/s below {throughput_floor:.0%} of "
                f"the best admissible {best_decode_tps:.1f} tok/s"
            )))
        else:
            eligible.append(record)

    retained = max(eligible, key=lambda r: (r["num_ctx"], r["decode_tps"])) if eligible else None
    return {"retained": retained, "dropped": dropped, "best_decode_tps": best_decode_tps}


def probe_base(base_tag: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Gather every read-only fact the search needs, in one place, so run() can
        refuse early without having touched anything.

    Inputs:
        base_tag (str): the tag to tune.

    Outputs:
        result (dict): layers, native_max_context, card, daemon_kv_cache_type,
        base_config.
    --------------------------------------------------------------------------
    """
    return {
        "layers": vram_probe.manifest_layers(base_tag),
        "native_max_context": vram_probe.native_max_context(base_tag),
        "card": optimize_ollama.detect_card(),
        "daemon_kv_cache_type": vram_daemon.active_kv_cache_type(),
        "base_config": vram_modelfile.base_configuration(base_tag),
    }


def ollama_create(tag: str, modelfile_path: Path) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the tuned tag from a rendered Modelfile.

    Inputs:
        tag (str): the tag to create.
        modelfile_path (Path): the rendered Modelfile.

    Outputs:
        None.

    Raises:
        OptimizerError: `ollama create` could not run or exited non-zero.
    --------------------------------------------------------------------------
    """
    import subprocess

    try:
        done = subprocess.run(["ollama", "create", tag, "-f", str(modelfile_path)],
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OptimizerError(f"[VRAM-OPT] `ollama create {tag}` could not run: {exc}") from exc
    if done.returncode != 0:
        raise OptimizerError(f"[VRAM-OPT] `ollama create {tag}` failed: {done.stderr.strip()}")


def sweep_axis_value(tag: str, kv_value: str, native_max: int, num_predict: int) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Climb the num_ctx ladder at ONE axis value, stopping at the model's
        native maximum, and return one record per rung tagged with the axis
        value. Delegates the measurement to optimize_ollama.evaluate_rung.

    Inputs:
        tag (str): the tuned tag to measure.
        kv_value (str): the axis value currently active on the daemon.
        native_max (int): the model's own context maximum.
        num_predict (int): fixed reply length, for comparable decode rates.

    Outputs:
        result (list[dict]): rung records, each with kv_cache_type added.
    --------------------------------------------------------------------------
    """
    records: list[dict[str, Any]] = []
    for num_ctx in optimize_ollama.CONTEXT_LADDER:
        if num_ctx > native_max:
            break
        # baseline_median_s stays None on every rung: the wall-clock regression check it
        # drives is the metric this tool exists to replace, since elapsed time measures a
        # model's verbosity rather than its speed. Ranking happens on decode_tps instead.
        record = optimize_ollama.evaluate_rung(
            tag, num_ctx, optimize_ollama._PROBE_PROMPT, num_predict, None)
        record["kv_cache_type"] = kv_value
        records.append(record)
        if not record["accepted"]:
            break
    return records


def declare_candidate(tag: str, role: str, retained: dict[str, Any], card: dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Declare the tuned tag as a candidate for its role in local-models.json,
        so the resolver may later qualify it. Idempotent: re-running the tool on
        the same tag updates that entry instead of appending a second one.

        Declaration is NOT adoption. The resolver decides that, against a frozen
        task set, on a criterion this tool does not measure.

    Inputs:
        tag (str): the tuned tag.
        role (str): "writer" or "coder".
        retained (dict): the retained configuration record.
        card (dict): detect_card's output, recorded in the note.

    Outputs:
        None.
    --------------------------------------------------------------------------
    """
    document = json.loads(_CANDIDATES_PATH.read_text(encoding="utf-8"))
    note = (
        f"Built and measured by opt-local-vram-llm on {_today()}. "
        f"{card['name']}, {card['memory_total_mib']} MiB: num_ctx {retained['num_ctx']} at "
        f"OLLAMA_KV_CACHE_TYPE={retained['kv_cache_type']}, {retained['min_free_mib']} MiB "
        f"free, {retained['decode_tps']} tok/s decode, 100 percent GPU residency."
    )
    for entry in document.setdefault("candidates", []):
        if entry.get("tag") == tag:
            entry.update({"role": role, "declared": _today(), "notes": note})
            break
    else:
        document["candidates"].append(
            {"tag": tag, "role": role, "declared": _today(), "notes": note})
    _CANDIDATES_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _today() -> str:
    """Return today's date as YYYY-MM-DD."""
    return _datetime.date.today().isoformat()


def modelfile_dir() -> Path:
    """Return the directory tuned Modelfiles are written to."""
    return Path(os.environ.get("LARI_MODELFILE_DIR", str(Path.home() / ".litellm")))


def run(
    *,
    base_tag: str,
    role: str,
    throughput_floor: float,
    kv_types: tuple[str, ...],
    keep_vision: bool,
    dry_run: bool,
) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tune base_tag for this card and this role, end to end. Refuses early
        rather than half-building, restores the daemon axis on any exit, and
        stops short of qualification.

    Inputs:
        base_tag (str): the model tag to tune.
        role (str): "writer" or "coder".
        throughput_floor (float): fraction of the best observed decode rate.
        kv_types (tuple[str, ...]): axis values to try, in order.
        keep_vision (bool): keep a separate projector layer instead of dropping.
        dry_run (bool): probe and print the Modelfile, touch nothing else.

    Outputs:
        result (int): 0 on success, 1 on any explicit refusal.
    --------------------------------------------------------------------------
    """
    try:
        facts = probe_base(base_tag)
    except (vram_probe.ProbeError, optimize_ollama.OptimizeError) as exc:
        logger.error("%s", exc)
        return 1

    model = vram_probe.model_layer(facts["layers"])
    weights_mib = model["size"] / _MIB
    card_mib = facts["card"]["memory_total_mib"]
    if weights_mib >= card_mib:
        logger.error(
            "[VRAM-OPT] %s weighs %.0f MiB, at or above the card's %d MiB; no context window "
            "can make it fit. Refusing before building anything.",
            base_tag, weights_mib, card_mib)
        return 1

    projector = vram_probe.projector_layer(facts["layers"])
    strip = projector is not None and not keep_vision
    if strip:
        blob = model["digest"].replace("sha256:", "sha256-")
        from_reference = str(Path.home() / ".ollama" / "models" / "blobs" / blob)
        logger.info("[VRAM-OPT] dropping a %.0f MiB projector: the bridge is text-only.",
                    projector["size"] / _MIB)
    else:
        from_reference = base_tag

    tuned_tag = f"{base_tag}-gpu"
    provenance = {
        "card": facts["card"]["name"], "vram_mib": card_mib,
        "kv_cache_type": facts["daemon_kv_cache_type"], "free_mib": 0,
        "decode_tps": 0.0, "date": _today(), "measured": False,
    }

    def modelfile_text(num_ctx: int, prov: dict[str, Any]) -> str:
        return vram_modelfile.render(
            base_tag=base_tag, from_reference=from_reference, from_is_blob=strip,
            num_ctx=num_ctx, role=role, base_config=facts["base_config"], provenance=prov)

    if dry_run:
        print(modelfile_text(facts["native_max_context"], provenance))
        return 0

    path = modelfile_dir() / f"Modelfile.{tuned_tag.replace(':', '-')}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(modelfile_text(facts["native_max_context"], provenance), encoding="utf-8")

    records: list[dict[str, Any]] = []
    try:
        ollama_create(tuned_tag, path)
        with vram_daemon.axis_restored(facts["daemon_kv_cache_type"]) as apply_axis:
            for kv_value in kv_types:
                apply_axis(kv_value)
                records.extend(sweep_axis_value(
                    tuned_tag, kv_value, facts["native_max_context"],
                    optimize_ollama.DEFAULT_NUM_PREDICT))
    except (OptimizerError, vram_daemon.DaemonError, optimize_ollama.OptimizeError) as exc:
        logger.error("%s", exc)
        return 1

    selection = select_configuration(records, throughput_floor)
    for record, reason in selection["dropped"]:
        logger.info("[VRAM-OPT] dropped num_ctx=%d kv=%s: %s",
                    record["num_ctx"], record["kv_cache_type"], reason)

    retained = selection["retained"]
    if retained is None:
        logger.error(
            "[VRAM-OPT] no configuration of %s is admissible on this card. Nothing written. "
            "The reasons above are the measurement, not a guess.", base_tag)
        return 1

    provenance.update({
        "kv_cache_type": retained["kv_cache_type"],
        "free_mib": retained["min_free_mib"],
        "decode_tps": retained["decode_tps"],
        "measured": True,
    })
    path.write_text(modelfile_text(retained["num_ctx"], provenance), encoding="utf-8")
    try:
        vram_daemon.set_kv_cache_type(retained["kv_cache_type"])
        ollama_create(tuned_tag, path)
    except (OptimizerError, vram_daemon.DaemonError) as exc:
        logger.error("%s", exc)
        return 1

    optimize_ollama.write_config(
        tuned_tag, retained, records,
        optimize_ollama.isolate_weight_and_kv_cost(tuned_tag, retained["num_ctx"]),
        facts["card"], retained["kv_cache_type"])
    declare_candidate(tuned_tag, role, retained, facts["card"])

    print(f"tag: {tuned_tag}")
    print(f"retained_num_ctx: {retained['num_ctx']}")
    print(f"kv_cache_type: {retained['kv_cache_type']}")
    print(f"decode_tps: {retained['decode_tps']}")
    print(f"free_mib: {retained['min_free_mib']}")
    print("\nDeclared as a candidate, NOT adopted. Qualify it against the incumbent:")
    print(f"  python .claude/skills/loop-engineer/scripts/model_resolver.py "
          f"--qualify {tuned_tag} --role {role}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI. The base tag is positional; --role is required."""
    parser = argparse.ArgumentParser(
        prog="opt-local-vram-llm",
        description="Tune a local Ollama model for this GPU: the largest context window that "
                    "stays fully resident in VRAM, among configurations clearing a decode "
                    "throughput floor. Measures; never assumes.")
    parser.add_argument("base_tag", help="the model tag to tune")
    parser.add_argument("--role", required=True, choices=("writer", "coder"))
    parser.add_argument("--throughput-floor", type=float, default=DEFAULT_THROUGHPUT_FLOOR)
    parser.add_argument("--kv", default=",".join(KV_CACHE_TYPES),
                        help="comma-separated KV cache types to try, in order")
    parser.add_argument("--keep-vision", action="store_true",
                        help="keep a separate projector layer instead of dropping it")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe and print the Modelfile; touch neither Ollama nor daemon")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 on any explicit refusal."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_arg_parser().parse_args(argv)
    kv_types = tuple(v.strip() for v in args.kv.split(",") if v.strip())
    unknown = [v for v in kv_types if v not in KV_CACHE_TYPES]
    if unknown:
        logger.error("[VRAM-OPT] unknown KV cache type(s) %s; known: %s",
                     unknown, ", ".join(KV_CACHE_TYPES))
        return 1
    return run(base_tag=args.base_tag, role=args.role,
               throughput_floor=args.throughput_floor, kv_types=kv_types,
               keep_vision=args.keep_vision, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
