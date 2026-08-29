#!/usr/bin/env python3
"""
local_capability_probe.py - Stage 1 gate of the vault event daemon.

Measures two premises of the daemon's design on the installed Ollama daemon,
because both change what Stage 2 must be written to do, and neither can be
answered from documentation:

1. Structured output. Ollama constrains generation to a JSON schema at the
   sampler, which makes an invalid answer impossible rather than merely
   unlikely. A tag advertising the `tools` capability only means supported, not
   reliable. If the constraint does not hold here, the daemon's CLASSIFY and
   JUDGE_EDGE states must fall back to asking for JSON and validating it in
   Python with a retry budget, which is weaker and must be known before the
   states are written, not discovered mid-build.

2. Prefix cache. The design fires every event against one fixed instruction
   prefix, on the premise that the daemon re-uses the cached prefix and only
   evaluates the short variable tail. Three calls decide it: the same prefix
   twice, then a control call on a prefix the daemon has never seen. The
   comparison is on prefill DURATION, not on token count, because Ollama 0.33.0
   reports the full `prompt_eval_count` even when it skipped the work (measured
   2026-08-28: 2186 tokens billed on both calls, 2612 ms then 634 ms). Duration
   alone would track machine load, which is what the control call removes.

Neither outcome is fatal. The point is to record which world Stage 2 is written
for. The report goes to .claude/local-capability-probe.json, deliberately NOT
into local-model-config.json, which optimize_ollama.py --sweep rewrites whole
and would drop a second writer's records at the next sweep.

The model tag is never named here. model_resolver.py names it, through
ollama_bridge.resolve_model, and a resolver naming no qualified model is a stop:
a weaker model's answer to a capability question is indistinguishable from a
correct one.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
BRIDGE_DIR = SKILLS_DIR / "loop-engineer" / "scripts"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import context_budget  # noqa: E402
import ollama_bridge as ob  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outbox_io  # noqa: E402

REPORT_PATH = SKILLS_DIR.parent / "local-capability-probe.json"

# The schema the CLASSIFY state will use, reduced to its constrained field. An
# enum is the whole point: it is what Python would otherwise have to re-check.
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["reusable", "project"]},
        "confidence": {"type": "number"},
    },
    "required": ["scope", "confidence"],
}

SCHEMA_PROMPT = (
    "A note records that a command line tool exited 0 while its write never "
    "reached disk. Decide whether this learning is reusable across projects or "
    "bound to one project. Answer with the JSON object only."
)

# One paragraph repeated to build a prefix long enough for a cache effect to be
# visible above measurement noise. Content is irrelevant; length is not.
PREFIX_PARAGRAPH = (
    "You are filing a knowledge drop into a personal note vault. A reusable "
    "learning is filed under the technology where the defect lives. A project "
    "bound state is appended to that project's decision log. Never invent a "
    "destination, and never answer with prose outside the requested object. "
)

# The control prefix. Same length and register, different tokens from the first
# one, so a daemon that has never seen it must pay a full prefill.
CONTROL_PARAGRAPH = (
    "Consider a build log emitted by a compiler running under a continuous "
    "integration runner. Each warning names a source file, a line, and a rule "
    "identifier. Summaries group warnings by rule before ranking them by how "
    "many distinct files each rule touches across the whole build. "
)


def utc_now_iso() -> str:
    """Wall clock read in one place, after the work, never inside it (R19)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def probe_structured_output(model: str, num_ctx: int, timeout: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Ask for one schema-constrained object and check that the answer parses
        and that the enum was honoured.

    Inputs:
        model (str): the resolved tag, from the resolver
        num_ctx (int): the measured window
        timeout (float): socket timeout in seconds

    Outputs:
        result (dict): honoured (bool), the raw reply, and why it failed when
        it did. Never raises on a bad answer: a refusal to constrain IS the
        measurement.
    --------------------------------------------------------------------------
    """
    payload = ob.build_payload(SCHEMA_PROMPT, model, ob.DEFAULT_SEED, num_ctx,
                               fmt=CLASSIFY_SCHEMA)
    response = ob._post_generate(payload, timeout)
    raw = (response.get("response") or "").strip()
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        return {"honoured": False, "raw": raw[:400],
                "why": f"reply is not JSON: {exc}"}
    if not isinstance(parsed, dict) or "scope" not in parsed:
        return {"honoured": False, "raw": raw[:400],
                "why": "reply is JSON but not the requested object"}
    if parsed["scope"] not in ("reusable", "project"):
        return {"honoured": False, "raw": raw[:400],
                "why": f"enum violated: scope={parsed['scope']!r}"}
    return {"honoured": True, "parsed": parsed}


def probe_prefix_cache(model: str, num_ctx: int, timeout: float, repeat: int,
                       ratio_max: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether the daemon re-uses a cached prompt prefix, using three
        calls: the same prefix twice with different tails, then a CONTROL call
        on a different prefix of the same length.

        The count rule this probe first used cannot work here. Measured
        2026-08-28 on Ollama 0.33.0: the second call reported the identical
        prompt_eval_count (2186) while its prefill took 634 ms against 2612 ms,
        so the daemon bills the whole prompt whether or not it evaluated it.
        Duration is therefore the only exposed signal, and duration alone
        tracks machine load, which is exactly what the control call removes: a
        prefix the daemon has never seen must pay full prefill in the same
        conditions, moments apart.

    Inputs:
        model (str): the resolved tag
        num_ctx (int): the measured window
        timeout (float): socket timeout in seconds
        repeat (int): how many times the fixed paragraph is repeated
        ratio_max (float): the shared-prefix prefill must fall to at most this
            fraction of the control prefill to count as reuse

    Outputs:
        result (dict): the three calls, the measured ratio, and `reused`.
    --------------------------------------------------------------------------
    """
    prefix = PREFIX_PARAGRAPH * repeat
    control_prefix = CONTROL_PARAGRAPH * repeat
    plan = [
        ("warm", prefix + "Drop one: a lock file was left by a killed process."),
        ("shared_prefix", prefix + "Drop two: a note was filed under a project name."),
        ("control", control_prefix + "Drop three: a link pointed at a folder."),
    ]
    calls = {}
    for label, prompt in plan:
        response = ob._post_generate(
            ob.build_payload(prompt, model, ob.DEFAULT_SEED, num_ctx), timeout)
        calls[label] = {
            "prompt_eval_count": response.get("prompt_eval_count"),
            "prompt_eval_duration_ns": response.get("prompt_eval_duration"),
            "total_duration_ns": response.get("total_duration"),
        }
    shared = calls["shared_prefix"]["prompt_eval_duration_ns"]
    control = calls["control"]["prompt_eval_duration_ns"]
    if not (isinstance(shared, int) and isinstance(control, int) and control > 0):
        return {"reused": False, "ratio": None, "calls": calls,
                "why": "the daemon reported no usable prefill duration"}
    ratio = shared / control
    return {
        "reused": ratio <= ratio_max, "ratio": round(ratio, 4), "calls": calls,
        "rule": f"reused is True when the shared-prefix prefill is at most "
                f"{ratio_max} of the control prefill, measured moments apart",
    }


def run_probes(repeat: int, timeout: float, ratio_max: float) -> dict:
    """Resolve the tag, read the measured window for THAT tag, run both probes."""
    model = ob.resolve_model("writer")
    window = context_budget.read_retained_num_ctx(
        context_budget.DEFAULT_CONFIG_PATH, model)
    report = {
        "measured_at": None,
        "role": "writer",
        "num_ctx": window,
        "structured_output": probe_structured_output(model, window, timeout),
        "prefix_cache": probe_prefix_cache(model, window, timeout, repeat,
                                           ratio_max),
    }
    report["measured_at"] = utc_now_iso()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stage 1 capability probe.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the report, write nothing")
    parser.add_argument("--report", default=str(REPORT_PATH))
    args = parser.parse_args(argv)

    config = outbox_io.load_config()
    repeat = outbox_io.require(config, "probe", "prefix_paragraph_repeat")
    timeout = outbox_io.require(config, "probe", "request_timeout_s")
    ratio_max = outbox_io.require(config, "probe", "prefix_cache_duration_ratio_max")

    try:
        report = run_probes(repeat, timeout, ratio_max)
    except (ob.BridgeError, context_budget.ContextBudgetError) as exc:
        # No fallback tag and no assumed window (R8): the run stops and names
        # what is missing rather than measuring something else.
        print(str(exc), file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.dry_run:
        print("[PROBE] dry run, nothing written", file=sys.stderr)
        return 0
    Path(args.report).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"[PROBE] verdicts written to {args.report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
