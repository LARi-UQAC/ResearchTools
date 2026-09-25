"""
aider-ollama-config - decide this machine's Ollama settings, then apply them.

Stage: machine setup, after measurement. It turns two things into one tuned
Ollama tag:

  the ARITHMETIC   the smallest context window that holds the prompt this
                   harness assembles, computed from context-budget.json and
                   skills.json rather than chosen.
  the MEASUREMENT  num_gpu and num_thread, read from a report written by
                   aider-thread-probe.py.

Why this exists as its own file, rather than more PowerShell inside
ollama-tune.ps1: a student should get a configured machine from one command on
any operating system, and the decision it makes is worth testing offline. The
PowerShell script measures and reports; this one decides and applies.

Three refusals rather than guesses (R3, R8):
  a budget key that is absent is named, never defaulted;
  a report that measured nothing yields no num_gpu, and the tag is not written;
  a window no configured rung can hold is reported with the arithmetic.

It verifies the effect rather than the exit code (R9): after `ollama create` it
reads the new tag back and confirms the parameters are the ones asked for.

Exit codes: 0 success, 2 a refusal by design, 1 a failure.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2

# The suffix a tuned tag carries. One place names it, so the script that writes
# the tag and any script that looks for it cannot disagree (R2).
TUNED_SUFFIX = "-aider"


class Refusal(Exception):
    """Raised when this script must stop rather than guess. Names what is missing."""


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def require(data: dict, dotted: str, origin: str):
    """Read one configuration value, naming both key and file when absent."""
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise Refusal(f"'{dotted}' is absent from {origin}")
        node = node[part]
    return node


def largest_skill_stage(skills: dict, origin: str) -> int:
    """
    The skill cost the floor pays. Exactly one stage is active per call, so this
    is the largest stage ceiling and never their sum - adding them would reserve
    window for skills that are never loaded together.
    """
    stages = require(skills, "stages", origin)
    ceilings = [int(v["ceiling"]) for k, v in stages.items()
                if not k.startswith("_") and isinstance(v, dict) and "ceiling" in v]
    if not ceilings:
        raise Refusal(f"no stage in {origin} declares a 'ceiling'")
    return max(ceilings)


def compute_floor(budget: dict, budget_origin: str,
                  skills: dict, skills_origin: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        The window this harness needs before any source code, and the working
        minimum that a plan step actually puts in front of the model.

    Outputs:
        terms (dict): every component plus 'floor' and 'working_minimum', so a
        caller can print the arithmetic rather than only its result. A number
        with no visible derivation cannot be argued with.
    --------------------------------------------------------------------------
    """
    reply = int(require(budget, "reserve.reply_tokens", budget_origin))
    harness = int(require(budget, "reserve.harness_overhead_tokens", budget_origin))
    repo_map = int(require(budget, "repo_map_tokens", budget_origin))
    ceilings = require(budget, "ceilings", budget_origin)
    for key in ("conventions.md", "rules.md", "spec.md", "progress.md",
                "plan.md", "code_file_output", "test_file_output"):
        if key not in ceilings:
            raise Refusal(f"'ceilings.{key}' is absent from {budget_origin}")

    reserves = reply + harness + repo_map
    always_on = int(ceilings["conventions.md"]) + int(ceilings["rules.md"])
    protocol = (int(ceilings["spec.md"]) + int(ceilings["progress.md"])
                + int(ceilings["plan.md"]))
    skill_cost = largest_skill_stage(skills, skills_origin)
    floor = reserves + always_on + protocol + skill_cost
    working = floor + int(ceilings["code_file_output"]) + int(ceilings["test_file_output"])
    return {
        "reply": reply, "harness": harness, "repo_map": repo_map,
        "reserves": reserves, "always_on": always_on, "protocol": protocol,
        "skills": skill_cost, "floor": floor, "working_minimum": working,
        # Reported, never used to size the window: a plan that opens two files
        # at the read ceiling really does need it, but the harness sends a diff
        # rather than a whole file, so sizing for it spends VRAM on a case it
        # does not generate.
        "read_worst_case": floor + 2 * int(ceilings["code_file"]),
    }


def choose_window(working_minimum: int, rungs, headroom_tokens: int) -> int:
    """
    The smallest configured rung that holds the working minimum plus headroom.

    Headroom is not padding: a rung that clears the minimum by a few hundred
    tokens cannot also hold one existing file read in, and a window chosen that
    tightly fails on the first plan that touches real code.
    """
    for rung in sorted(int(r) for r in rungs):
        if rung >= working_minimum + headroom_tokens:
            return rung
    raise Refusal(
        f"no configured window holds the working minimum of {working_minimum} "
        f"tokens plus {headroom_tokens} of headroom. Rungs offered: "
        f"{', '.join(str(int(r)) for r in sorted(rungs))}.\n"
        f"  Either add a larger rung, or lower the ceilings in the budget: the "
        f"floor is the sum of what those ceilings permit, not of what the files "
        f"currently hold.")


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def group_means(rows, key_field: str, value_field: str = "decode_tps") -> list:
    """
    Group measurements by the setting they measured and average each group.

    A report may contain the same setting several times, because one run of a
    rung does not separate it from its neighbour: measured 2026-09-05, one
    offload setting produced 3.48, 3.00 and 3.02 tok/s across three runs, a
    16 percent spread wider than the gap between settings. Taking the best
    single run of each setting therefore selects the luckiest measurement
    rather than the fastest setting, which is the opposite of what repeating
    the rungs was for.
    """
    groups = {}
    for row in rows:
        key, value = row.get(key_field), row.get(value_field)
        if key is None or value is None:
            continue
        groups.setdefault(int(key), []).append(float(value))
    return [{"key": key, "mean": sum(v) / len(v), "n": len(v), "values": v}
            for key, v in sorted(groups.items())]


def pick_from_report(report: dict, tolerance_pct: float) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read num_gpu and num_thread out of a probe report.

    Details:
        The fastest rung is not automatically the right one. Measured
        2026-09-05: 20 threads returned 3.41 tok/s at 99.4 percent CPU where 14
        returned 3.39 at 81.3, so taking the maximum bought 0.6 percent and cost
        every remaining core. So within `tolerance_pct` of the best, the LOWEST
        rung wins.

        A rung whose request the daemon ignored is discarded rather than read:
        its throughput describes whatever the daemon actually ran.

    Outputs:
        picks (dict): 'num_thread' and 'num_gpu', each with the rung chosen, the
        best seen, and a reason. A value that could not be measured is None with
        its reason stated, never a plausible default.
    --------------------------------------------------------------------------
    """
    out = {"num_thread": None, "num_gpu": None, "notes": {}}

    threads = [r for r in (report.get("sweep") or [])
               if r.get("decode_tps") is not None
               and r.get("thread_effect") == "honoured"
               and r.get("num_thread_granted") is not None]
    if threads:
        groups = group_means(threads, "num_thread_granted")
        best = max(groups, key=lambda g: g["mean"])
        floor_tps = best["mean"] * (1.0 - tolerance_pct / 100.0)
        pick = min((g for g in groups if g["mean"] >= floor_tps),
                   key=lambda g: g["key"])
        out["num_thread"] = pick["key"]
        runs = "" if pick["n"] == 1 else f" (mean of {pick['n']} runs)"
        out["notes"]["num_thread"] = (
            f"{pick['mean']:.2f} tok/s{runs}; fastest was {best['key']} threads "
            f"at {best['mean']:.2f} tok/s")
    else:
        out["notes"]["num_thread"] = ("no thread rung was both measured and "
                                      "honoured by the daemon")

    layers = [r for r in (report.get("gpu_layers") or [])
              if r.get("decode_tps") is not None
              and r.get("layers_offloaded") is not None]
    if layers:
        groups = group_means(layers, "layers_offloaded")
        best = max(groups, key=lambda g: g["mean"])
        out["num_gpu"] = best["key"]
        runs = "" if best["n"] == 1 else f", mean of {best['n']} runs"
        out["notes"]["num_gpu"] = (
            f"{best['mean']:.2f} tok/s with {best['key']} layers placed{runs}, "
            f"best of {len(groups)} setting(s)")
        windows = {r.get("n_ctx_granted") or r.get("num_ctx") for r in layers}
        out["notes"]["num_gpu_window"] = sorted(w for w in windows if w)
    else:
        out["notes"]["num_gpu"] = "no offload rung produced a decode figure"
    return out


def warn_window_mismatch(picks: dict, window: int) -> str | None:
    """
    A num_gpu measured at one context window does not transfer to another. The
    KV cache is the second-largest VRAM consumer, so a wider window leaves less
    room for layers and the measured best becomes unreachable. Measured
    2026-09-05: the cache was 272 MiB at 8192 and about 2.1 GB at 65536.
    """
    measured = picks.get("notes", {}).get("num_gpu_window") or []
    if picks.get("num_gpu") is None or not measured:
        return None
    if all(int(w) == int(window) for w in measured):
        return None
    return (f"num_gpu was measured at num_ctx {', '.join(str(w) for w in measured)} "
            f"but is being applied at {window}. The KV cache grows with the "
            f"window and takes the VRAM those layers need, so re-measure with "
            f"--mode gpulayers --num-ctx {window} before trusting it.")


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def render_modelfile(base_tag: str, window: int, picks: dict,
                     reply_tokens: int, terms: dict) -> str:
    """The Modelfile, with every number's derivation in a comment beside it."""
    lines = [
        f"# Generated by aider-ollama-config for this machine.",
        f"# Do not hand-edit: re-run the tool, or the settings and the reasons",
        f"# for them drift apart.",
        f"#",
        f"# num_ctx {window} is the smallest configured rung holding this",
        f"#   harness's working minimum of {terms['working_minimum']} tokens:",
        f"#   reserves {terms['reserves']} + always-on {terms['always_on']}",
        f"#   + protocol {terms['protocol']} + skills {terms['skills']}",
        f"#   = floor {terms['floor']}, plus one new file and its test.",
        f"# Every token above that is KV cache, and KV cache displaces weights.",
        f"FROM {base_tag}",
        f"PARAMETER num_ctx {window}",
        f"PARAMETER num_predict {reply_tokens}",
    ]
    if picks.get("num_gpu") is not None:
        lines += [f"# measured: {picks['notes']['num_gpu']}",
                  f"PARAMETER num_gpu {picks['num_gpu']}"]
    else:
        lines += [f"# num_gpu NOT set: {picks['notes']['num_gpu']}.",
                  f"#   The allocator decides, and it places conservatively."]
    if picks.get("num_thread") is not None:
        lines += [f"# measured: {picks['notes']['num_thread']}",
                  f"PARAMETER num_thread {picks['num_thread']}"]
    else:
        lines += [f"# num_thread NOT set: {picks['notes']['num_thread']}."]
    return "\n".join(lines) + "\n"


def run(argv, runner, timeout: float):
    return runner(argv, capture_output=True, text=True, timeout=timeout)


def tuned_name(base_tag: str) -> str:
    """
    `name:tag` becomes `name:tag-aider`, preserving the tag portion.

    An earlier version returned `name-aider`, dropping everything after the
    colon. That collides: two variants of one family, say `<name>:9b` and
    `<name>:9b-gpu`, both became `<name>-aider`, so tuning the second would
    silently overwrite the first and the operator would be running a model they
    did not think they were.
    """
    if ":" in base_tag:
        name, tag = base_tag.split(":", 1)
        return f"{name}:{tag}{TUNED_SUFFIX}"
    return base_tag + TUNED_SUFFIX


def apply_tag(base_tag: str, modelfile: str, work_dir: pathlib.Path,
              runner=subprocess.run, which=shutil.which,
              timeout: float = 600.0, tag: str = None) -> dict:
    """
    Create the tuned tag, then READ IT BACK. `ollama create` exiting 0 is not
    evidence the parameters took: the effect is checked against `ollama show`.
    """
    binary = which("ollama")
    if not binary:
        raise Refusal("'ollama' was not found on PATH, so no tag can be created")
    tag = tag or tuned_name(base_tag)
    path = work_dir / "Modelfile"
    path.write_text(modelfile, encoding="utf-8")

    created = run([binary, "create", tag, "-f", str(path)], runner, timeout)
    if created.returncode != 0:
        raise Refusal(f"'ollama create {tag}' failed: "
                      f"{(created.stderr or created.stdout or '').strip()[-400:]}")

    shown = run([binary, "show", "--modelfile", tag], runner, timeout)
    if shown.returncode != 0:
        raise Refusal(f"the tag '{tag}' was created but cannot be read back: "
                      f"{(shown.stderr or '').strip()[-200:]}")
    return {"tag": tag, "modelfile_path": str(path), "readback": shown.stdout or ""}


def verify_readback(readback: str, expected: dict) -> list:
    """Which expected PARAMETERs are missing from the created tag (R9)."""
    missing = []
    for name, value in expected.items():
        if value is None:
            continue
        if f"{name} {value}" not in readback.replace("PARAMETER ", ""):
            missing.append(f"{name} {value}")
    return missing


# ---------------------------------------------------------------------------
# Wiring the tuned tag into aider (G5)
#
# Creating the tag is not enough, and this is the fault chain that made the
# tuning silently ineffective on 2026-09-05. Three faults, each of which alone
# reproduces the failure:
#
#   1. aider is pointed at the base tag, so the tuned Modelfile is never used;
#   2. aider is pointed at the tuned tag, but model-settings.yml sends
#      extra_params.num_ctx on every request, and a num_ctx in the REQUEST
#      overrides the one baked into the Modelfile - so the tag runs at whatever
#      the base entry says, which was the configuration measured to put ZERO
#      layers of a 27B model on a 6 GB card;
#   3. both are right, but aider takes max_input_tokens from litellm metadata
#      and, finding none, asks Ollama - which answers with the ARCHITECTURE's
#      native maximum whatever the Modelfile bakes in. The driver then sizes
#      batches against a window that is not in force, and Ollama truncates the
#      over-long prompt to num_ctx // 2 + 2 while reporting success.
#
# All three were fixed by hand. Doing it by hand is the defect: a student who
# runs the tuner gets a tag and none of the wiring, so they reproduce the
# original failure by construction. These two writers make the wiring part of
# tuning.
#
# Both are ADD-ONLY with respect to anything they did not write. The YAML is
# edited textually rather than parsed and re-dumped, because the file is
# hand-commented and a round trip through a YAML library would discard every
# comment in it - and those comments carry the measurements.


def settings_block(tag: str, window: int, reply: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The model-settings.yml entry for a freshly tuned tag, used only when no
        entry for that tag exists yet.

    Inputs:
        tag (str): the tuned Ollama tag, without the ollama_chat/ prefix
        window (int): the computed num_ctx
        reply (int): the reply reserve, named in the comment

    Outputs:
        block (str): a YAML list entry, newline-terminated
    --------------------------------------------------------------------------
    """
    nl = chr(10)
    return (
        "# Written by aider-ollama-config.py. num_ctx here is not decoration:" + nl +
        "# aider sends extra_params on every request, and a num_ctx in the request" + nl +
        "# OVERRIDES the one baked into the tag's Modelfile. Without this entry," + nl +
        "# pointing aider at a tuned tag changes the name and nothing else." + nl +
        "#" + nl +
        "# The value is the smallest window that holds this harness's assembled" + nl +
        "# prompt, computed from context-budget.json rather than chosen, against a" + nl +
        "# reply reserve of " + str(reply) + " tokens. Re-run the script after changing" + nl +
        "# any ceiling in that file, or the two disagree and the budget the driver" + nl +
        "# prints describes a window that is not in force." + nl +
        "- name: ollama_chat/" + tag + nl +
        "  edit_format: diff" + nl +
        "  use_repo_map: true" + nl +
        "  reasoning_tag: think" + nl +
        "  use_temperature: 0.6" + nl +
        "  editor_edit_format: editor-diff" + nl +
        "  extra_params:" + nl +
        "    num_ctx: " + str(window) + nl +
        # Sent per request for the same reason num_ctx is. Measured 2026-09-05:
        # a reply stopped at about 2104 tokens with finish_reason=length while
        # the tag's Modelfile declared num_predict 8192, so the tag's value was
        # not what governed the call. A truncated reply is invisible - aider
        # writes a file only once it has parsed a COMPLETE edit block, so the
        # code appears in the chat and the file stays empty.
        "    num_predict: " + str(reply) + nl +
        "    top_p: 0.95" + nl +
        "    keep_alive: -1" + nl
    )


def upsert_settings(text: str, tag: str, window: int, reply: int):
    """
    --------------------------------------------------------------------------
    Purpose:
        Put the tuned tag's num_ctx into model-settings.yml, creating the entry
        when it is absent and correcting only that one number when it is not.
        Every other entry, and every comment, is left byte-identical.

    Inputs:
        text (str): the current file
        tag (str): the tuned tag, without the ollama_chat/ prefix
        window (int): the computed num_ctx
        reply (int): the reply reserve, for a new entry's comment

    Outputs:
        (text, what) (tuple of str): the new content, and one line saying what
            happened - added, corrected, inserted, or already correct
    --------------------------------------------------------------------------
    """
    nl = chr(10)
    name_line = "- name: ollama_chat/" + tag
    lines = text.split(nl)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == name_line:
            start = i
            break
    if start is None:
        sep = "" if text.endswith(nl + nl) else (nl if text.endswith(nl) else nl + nl)
        return text + sep + settings_block(tag, window, reply), "added"

    # The entry ends where the next one begins. Anything after that - the next
    # entry's own comment block included - is not ours to touch.
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("- name:"):
            end = i
            break

    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("num_ctx:"):
            was = stripped.split(":", 1)[1].strip()
            if was == str(window):
                return text, "already correct"
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = indent + "num_ctx: " + str(window)
            return nl.join(lines), "corrected " + was + " -> " + str(window)

    # An entry carrying no num_ctx at all is fault 2 of the chain waiting to
    # happen, so it is filled rather than reported and left.
    for i in range(start, end):
        if lines[i].strip() == "extra_params:":
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines.insert(i + 1, indent + "  num_ctx: " + str(window))
            return nl.join(lines), "inserted num_ctx " + str(window)
    lines.insert(end, "  extra_params:")
    lines.insert(end + 1, "    num_ctx: " + str(window))
    return nl.join(lines), "added extra_params with num_ctx " + str(window)


def upsert_metadata(data: dict, tag: str, window: int, reply: int):
    """
    --------------------------------------------------------------------------
    Purpose:
        State the tuned tag's true window in the litellm metadata aider reads,
        so aider stops asking Ollama a question Ollama answers wrongly.

    Inputs:
        data (dict): the current ~/.aider.model.metadata.json content
        tag (str): the tuned tag, without the ollama_chat/ prefix
        window (int): max_input_tokens
        reply (int): max_output_tokens

    Outputs:
        (data, what) (tuple): the new mapping, and one line saying what happened
    --------------------------------------------------------------------------
    """
    key = "ollama_chat/" + tag
    entry = {
        "max_input_tokens": window,
        "max_output_tokens": reply,
        "input_cost_per_token": 0.0,
        "output_cost_per_token": 0.0,
        "litellm_provider": "ollama_chat",
        "mode": "chat",
    }
    out = dict(data)
    if "_comment" not in out:
        out["_comment"] = (
            "Written by aider-ollama-config.py. aider asks Ollama for a model's"
            " context length, and Ollama answers with the ARCHITECTURE's native"
            " maximum whatever num_ctx the tag's Modelfile bakes in, so a tuned"
            " tag reports a window several times larger than the one it will run"
            " at. Ollama then truncates an over-long prompt to num_ctx // 2 + 2"
            " and reports success, so the failure is silent. This file states the"
            " true window per tag."
        )
    before = out.get(key)
    if before == entry:
        return out, "already correct"
    out[key] = entry
    if before is None:
        return out, "added"
    was = before.get("max_input_tokens") if isinstance(before, dict) else before
    return out, "corrected max_input_tokens " + str(was) + " -> " + str(window)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--budget", default=None, help="context-budget.json")
    p.add_argument("--skills", default=None, help="skills.json")
    p.add_argument("--report", default=None,
                   help="a report written by aider-thread-probe.py --json")
    p.add_argument("--model", default=None, help="the base tag to tune")
    p.add_argument("--tag", default=None,
                   help="name for the tuned tag (default: the base tag with "
                        "'-aider' appended to its tag portion)")
    p.add_argument("--windows", nargs="+", type=int, default=None,
                   help="candidate context windows, smallest first")
    p.add_argument("--headroom", type=int, default=None,
                   help="tokens a window must clear the minimum by")
    p.add_argument("--dry-run", action="store_true",
                   help="print the decision and the Modelfile, create nothing")
    p.add_argument("--yes", action="store_true",
                   help="required to create the tag; without it this is a dry run")
    p.add_argument("--settings", default=None,
                   help="model-settings.yml to wire the tuned tag into "
                        "(default ~/.config/aider/model-settings.yml)")
    p.add_argument("--metadata", default=None,
                   help="litellm metadata aider reads for max_input_tokens "
                        "(default ~/.aider.model.metadata.json)")
    p.add_argument("--no-wire", action="store_true",
                   help="create the tag and write neither file. The tag alone "
                        "changes nothing aider does, so this is for inspecting "
                        "a tag before adopting it, not a normal run")
    p.add_argument("--json", dest="json_out", default=None,
                   help="write the decision as JSON here (R17)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    here = pathlib.Path(__file__).resolve().parent
    config_dir = pathlib.Path.home() / ".config" / "aider"

    try:
        budget_path = pathlib.Path(args.budget) if args.budget else config_dir / "context-budget.json"
        skills_path = pathlib.Path(args.skills) if args.skills else config_dir / "skills.json"
        for path, what in ((budget_path, "context budget"), (skills_path, "skills map")):
            if not path.is_file():
                raise Refusal(f"the {what} was not found at {path}")
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        skills = json.loads(skills_path.read_text(encoding="utf-8"))

        terms = compute_floor(budget, str(budget_path), skills, str(skills_path))
        windows = args.windows or (budget.get("ollama") or {}).get("window_rungs") \
            or [32768, 49152, 65536, 131072]
        headroom = args.headroom
        if headroom is None:
            headroom = int((budget.get("ollama") or {}).get("window_headroom_tokens", 16000))
        window = choose_window(terms["working_minimum"], windows, headroom)

        tolerance = float((budget.get("report") or {}).get("tie_tolerance_pct", 3.0))
        picks = {"num_thread": None, "num_gpu": None, "notes": {}}
        if args.report:
            report_path = pathlib.Path(args.report)
            if not report_path.is_file():
                raise Refusal(f"the probe report was not found at {report_path}")
            picks = pick_from_report(json.loads(report_path.read_text(encoding="utf-8")),
                                     tolerance)
        else:
            picks["notes"]["num_thread"] = "no --report given, so nothing was measured"
            picks["notes"]["num_gpu"] = "no --report given, so nothing was measured"

        model = args.model or (budget.get("audit") or {}).get("model") or ""
        model = model.split("/")[-1]
        if not model:
            raise Refusal("no base tag: pass --model <tag>")

        modelfile = render_modelfile(model, window, picks,
                                     terms["reply"], terms)
        mismatch = warn_window_mismatch(picks, window)

        print("Decision")
        print(f"  floor            {terms['floor']:>8}")
        print(f"  working minimum  {terms['working_minimum']:>8}")
        print(f"  num_ctx          {window:>8}   smallest rung clearing it by {headroom}")
        print(f"  num_predict      {terms['reply']:>8}   the reply reserve")
        print(f"  num_gpu          {str(picks['num_gpu']):>8}   {picks['notes']['num_gpu']}")
        print(f"  num_thread       {str(picks['num_thread']):>8}   {picks['notes']['num_thread']}")
        if mismatch:
            print()
            print("  WARNING: " + mismatch)
        print()
        print(modelfile)

        decision = {"terms": terms, "num_ctx": window, "picks": picks,
                    "base_model": model, "warning": mismatch,
                    "modelfile": modelfile, "applied": False}

        if not args.yes or args.dry_run:
            print("Nothing created. Pass --yes to build the tuned tag.")
        else:
            result = apply_tag(model, modelfile,
                               pathlib.Path(args.json_out).parent
                               if args.json_out else pathlib.Path.cwd(),
                               tag=args.tag)
            missing = verify_readback(result["readback"], {
                "num_ctx": window, "num_predict": terms["reply"],
                "num_gpu": picks["num_gpu"], "num_thread": picks["num_thread"]})
            decision["applied"] = not missing
            decision["tag"] = result["tag"]
            decision["missing_after_readback"] = missing
            if missing:
                print(f"FAILED: '{result['tag']}' was created but does not carry: "
                      + ", ".join(missing))
                print("  The create call succeeded and the effect did not, which is "
                      "why this is checked rather than assumed.")
                return EXIT_FAIL
            print(f"created and verified: {result['tag']}")

            # Only after the read-back. Wiring aider to a tag whose parameters
            # did not take would point the harness at the failure rather than
            # away from it, which is why this sits below the return above.
            if args.no_wire:
                print("  --no-wire: model-settings.yml and the litellm metadata "
                      "were not written, so aider still runs this tag at "
                      "whatever the base entry says")
            else:
                settings_path = (pathlib.Path(args.settings) if args.settings
                                 else config_dir / "model-settings.yml")
                metadata_path = (pathlib.Path(args.metadata) if args.metadata
                                 else pathlib.Path.home() / ".aider.model.metadata.json")
                if not settings_path.is_file():
                    raise Refusal(f"no model-settings.yml at {settings_path}. "
                                  "The tag exists; nothing was wired. Pass "
                                  "--settings, or --no-wire to skip.")
                text = settings_path.read_text(encoding="utf-8", newline="")
                text, did = upsert_settings(text, result["tag"], window, terms["reply"])
                if did != "already correct":
                    settings_path.write_text(text, encoding="utf-8", newline="")
                print(f"  model-settings.yml   {did}")

                # An absent metadata file is created rather than refused: unlike
                # model-settings.yml it has no other content to be careful of,
                # and aider works without it by asking Ollama the question
                # Ollama answers wrongly - which is fault 3 (R8: the fallback is
                # what makes it silent, so there is no fallback here).
                existing = {}
                if metadata_path.is_file():
                    existing = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                data, did = upsert_metadata(existing, result["tag"], window,
                                            terms["reply"])
                if did != "already correct":
                    metadata_path.write_text(json.dumps(data, indent=2) + chr(10),
                                             encoding="utf-8", newline="")
                print(f"  litellm metadata     {did}")
                decision["wired"] = {"settings": str(settings_path),
                                     "metadata": str(metadata_path)}

            print(f"  point aider at it with  --model ollama_chat/{result['tag']}")

        if args.json_out:
            pathlib.Path(args.json_out).write_text(json.dumps(decision, indent=2),
                                                   encoding="utf-8")
            print(f"report -> {args.json_out}")
        return EXIT_OK

    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except json.JSONDecodeError as exc:
        print(f"REFUSED: a configuration file does not parse: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
