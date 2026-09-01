"""
claude_code - the Claude Code adapter: sessions, hooks, and inbox reachability.

Sessions are tail-read from the JSONL transcripts. A transcript grows without
bound and only its tail carries current state, so a configured number of bytes is
read from the end rather than the whole file.

The hooks inventory is carried here rather than in the core because it is
harness-specific. It reuses `build_inventory` out of
`.claude/hooks/session-hooks-inventory.py`, loaded BY PATH: that filename carries
hyphens and cannot be imported by name, and the function has exactly one caller
of its own, so it was never an API. It is covered by a 26-test suite, which is
what makes the reuse defensible - not its visibility.

Privacy is applied before anything leaves this module. A project named in the
configured exclusion list contributes nothing at all rather than something
shortened, prompts and summaries are truncated to their configured caps, and
every path under the home directory is rewritten to `~/...` so no account name
reaches the snapshot or the page.
"""
import importlib.util
import io
import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rt_redact import home_tilde  # noqa: E402


def _projects_dir(context):
    return context.home / ".claude" / "projects"


def probe(context):
    """Is Claude Code present on this machine at all."""
    return _projects_dir(context).is_dir()


def _cap(context, *keys):
    node = context.config
    for key in keys:
        node = node[key]
    return node["value"]


def _redact(text, home):
    """Delegates to rt_redact.home_tilde, which is the single implementation.

    It lived here as one of four near-copies until 2026-08-31, and the two
    collectors that had no copy were the ones leaking the account name.
    """
    return home_tilde(text, home)


def _truncate(text, limit):
    if text is None:
        return None
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _tail_records(path, tail_bytes):
    """The last decodable JSON records of a transcript, newest last.

    A truncated first line is expected when reading from an offset and must not
    abort the fleet, so undecodable lines are skipped rather than raised on.
    """
    try:
        size = path.stat().st_size
        with io.open(path, "rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
            blob = handle.read()
    except OSError:
        return []
    text = blob.decode("utf-8", errors="replace")
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


# The harness state machine of `c2:fig:hooks_states`, in the book's own order
# and with the book's own reading of who executes each state: a deterministic
# hook, the token-costing core, the deterministic security audit, or waiting.
# One table, because the page colours by role and the adapter names the role
# (R5) - a second list in the markup would be a second truth.
FLOW_STATES = [
    ("session_start", "SessionStart", "hook"),
    ("idle", "waiting", "idle"),
    ("prompt", "UserPromptSubmit", "hook"),
    ("reasoning", "reasoning + tool calling", "core"),
    ("tool", "tool call", "core"),
    ("post_tool", "PostToolUse", "hook"),
    ("audit", "security audit", "security"),
]

# Tools whose whole purpose is to leave this machine. Anything reached through
# an MCP server is reported as MAY leave it rather than as network: a server can
# be a local process, and asserting more than is known is the failure this
# repository legislates against.
NETWORK_TOOLS = ("WebFetch", "WebSearch")


def _blocks(record):
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] \
        if isinstance(content, list) else []


_RUNNERS = ("python", "python3", "node", "pwsh", "powershell", "sh", "bash")


def _printed_name(stdout):
    """A name taken from what the hook PRINTED, when it named itself nowhere
    else.

    Measured 2026-09-01: the caveman tracker and the RTK notice identify
    themselves only in their output - `[RTK ACTIVE] ...`, `CAVEMAN MODE ACTIVE
    - level: full` - so a bracketed tag is the name, and failing that the first
    few words are. Without this the operator saw the bare event name for two of
    the hooks they most wanted to see."""
    text = (stdout or "").strip()
    if not text or text[0] in "{[" and text[:2] != "[R" and "]" not in text[:24]:
        # A JSON envelope is not a name. Measured: plugin hooks print `{}` and
        # were being called that on the diagram.
        return ""
    if text in ("{}", "[]"):
        return ""
    if text.startswith("["):
        tag = text[1:].split("]", 1)[0].strip()
        # `[RTK ACTIVE]` is the RTK hook; the state word adds nothing.
        head = tag.split(" ")[0]
        return head if len(head) > 2 else tag
    words = text.replace("\r", " ").replace("\n", " ").split()
    return " ".join(words[:3])[:28]


def _hook_label(printed, hook_name="", stdout=""):
    """What to CALL a hook on the diagram.

    The operator asked for the hook's NAME, never the file that implements it,
    and there are three sources in descending order of how much they were meant
    to be read:

    1. the sentence the hook prints for itself - "Scanning for secrets
       (betterleaks)", "Checking RTK" - which is the author naming their own
       guard, so it wins outright;
    2. the script it runs, reduced to a name: no directory, no extension, and no
       `-hook` suffix, so `betterleaks-hook.py` reads `betterleaks`;
    3. the matcher out of `Event:Matcher`, when step 2 only produces the event
       again - a plugin whose file is called `pretooluse.py` has told us nothing
       the arrow does not already say."""
    printed = (printed or "").strip().strip(".")
    hook_name = (hook_name or "").strip()
    matcher = hook_name.split(":", 1)[1] if ":" in hook_name else ""
    event = hook_name.split(":", 1)[0] if hook_name else ""

    looks_like_a_command = bool(printed) and (
        "/" in printed or "\\" in printed
        or printed.split(" ")[0] in _RUNNERS)
    if printed and not looks_like_a_command:
        return printed

    base = ""
    for token in reversed(printed.replace('"', " ").replace("'", " ").split()):
        candidate = token.replace("\\", "/").rstrip("/").split("/")[-1]
        if "." in candidate and not candidate.startswith("-"):
            base = candidate
            break
    if base:
        name = base.rsplit(".", 1)[0]
        for suffix in ("-hook", "_hook", "-hooks"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        flat = name.replace("-", "").replace("_", "").lower()
        if flat and flat != event.lower():
            return name
    # Only now: what the hook PRINTED. It is the last identifying thing there
    # is, and it is tried after the script name because a plugin hook whose
    # stdout is a JSON envelope would otherwise be called `{}`.
    from_output = _printed_name(stdout)
    if from_output:
        return from_output

    if matcher:
        # Read as "a hook on Write" rather than as a tool called Write: it is
        # the only honest thing left to say when the hook named itself nowhere.
        return "on " + matcher
    return event or (printed.split(" ")[0] if printed else "")


def _hook_for(record):
    """A hook firing, or None.

    Hook firings arrive as ATTACHMENT records carrying `hook_success` or
    `hook_error`, and reading every attachment as noise is why the whole
    deterministic half of the harness was invisible: measured 2026-09-01, the
    outbox flush that writes the vault, the secret scan on every write and the
    injection scan on every read left NO trace on a tab whose entire subject is
    what the harness is doing. The figure this tab is drawn from colours four of
    its seven states for hooks."""
    attachment = record.get("attachment")
    if not isinstance(attachment, dict):
        return None
    if not str(attachment.get("type") or "").startswith("hook"):
        return None
    code = str(attachment.get("exitCode"))
    return {
        "event": str(attachment.get("hookEvent") or "hook"),
        "name": str(attachment.get("hookName") or "hook"),
        # The label the hook prints for ITSELF, which is what names the outbox
        # flush or the secret scan rather than the event that ran it.
        "label": _hook_label(attachment.get("command"),
                             attachment.get("hookName"),
                             attachment.get("stdout")),
        # Kept whole for the hover panel: the NAME is what the diagram shows,
        # and the command is what an operator needs when the name is not enough.
        "command": str(attachment.get("command") or "").strip(),
        "exit": int(code) if code.lstrip("-").isdigit() else None,
        "ms": attachment.get("durationMs"),
        "at": record.get("timestamp") or "",
    }


def _step_for(record, blocks):
    """One transcript record folded into at most one flow step, or None.

    Deliberately lossy: the tab is read while something is happening, so a
    record that says nothing about WHAT the harness is doing contributes
    nothing. An attachment that is NOT a hook firing is the clearest case - the
    tail is full of them and not one is a step."""
    kind = record.get("type")
    if kind == "last-prompt":
        return {"kind": "prompt", "name": "prompt"}
    if kind == "assistant":
        for block in blocks:
            if block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "tool")
            payload = block.get("input") if isinstance(block.get("input"), dict) else {}
            if name in ("Agent", "Task"):
                return {"kind": "subagent",
                        "name": str(payload.get("subagent_type") or "subagent")}
            if name == "Skill":
                # A skill is not a tool call like any other: it changes what the
                # session is FOLLOWING for the rest of the turn, so the tab
                # draws it as its own box rather than as one more step.
                return {"kind": "skill",
                        "name": str(payload.get("skill") or "skill")}
            server = record.get("attributionMcpServer")
            shown = name
            if not server and name.startswith("mcp__"):
                # The attribution field is not always present, and the tool id
                # carries the same two names: mcp__<server>__<tool>.
                parts = name.split("__")
                if len(parts) >= 3:
                    server = parts[1]
            if server and name.startswith("mcp__"):
                # The operator asked to see the MCP SERVER rather than the tool
                # id: `playwright . browser_evaluate` says who was called and
                # what for, where `mcp__playwright__browser_evaluate` says the
                # protocol twice and the server once.
                shown = str(server) + " . " + name.split("__")[-1]
            return {"kind": "tool", "name": shown, "tool": name,
                    "network": "yes" if name in NETWORK_TOOLS
                               else ("mcp" if server else "no"),
                    "server": str(server) if server else ""}
        for block in blocks:
            if block.get("type") in ("thinking", "text"):
                return {"kind": "reasoning", "name": "reasoning"}
        return None
    if kind == "user":
        for block in blocks:
            if block.get("type") != "tool_result":
                continue
            # A FAILURE is a result, and it was the one result nobody could
            # see: the transcript marks it on the result block itself, so the
            # call it answers can be drawn as failed rather than as returned.
            return {"kind": "result", "name": "tool result",
                    "error": bool(block.get("is_error"))}
    return None


def _usage_from(record, blocks):
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    return usage if isinstance(usage, dict) else None


def _only_declared(hooks, declared, table):
    """Keep the firings of hooks this machine declares, and name them.

    A firing carries the script that ran, or the sentence the hook printed. Both
    are matched against the declared roster, and anything that matches nothing -
    the harness's own plugin hooks, which no `settings.json` here asked for - is
    dropped rather than drawn beside the operator's own guards."""
    if not declared:
        return hooks
    wanted = {}
    for row in declared:
        for index, script in enumerate(row.get("scripts") or []):
            wanted[script] = row["names"][index]
    kept = []
    for hook in hooks:
        command = (hook.get("command") or "")
        spoken = (hook.get("label") or "").lower()
        name = ""
        for script, display in wanted.items():
            stem = script.rsplit(".", 1)[0]
            # The WHOLE basename in the command, never a loose stem: `hook` is
            # inside every path that contains `hooks/`, which is how one plugin
            # entry came to relabel every firing on the diagram.
            if script and script in command:
                name = display
                break
            # Or the hook naming itself in its own printed sentence. Compared by
            # WORDS, because `vault-access-guard.py` prints "Checking vault
            # access (local-writer only)" and shares no substring with the name
            # it is displayed under.
            words = set(w for w in stem.replace("-", " ").replace("_", " ")
                        .split() if len(w) > 3)
            if words and len(words & set(spoken.replace("(", " ")
                                         .replace(")", " ").split())) >= 1:
                name = display
                break
            if display.lower() in spoken:
                name = display
                break
        if not name:
            continue
        hook = dict(hook)
        hook["label"] = name
        kept.append(hook)
    return kept


def _keep_per_event(hooks, per_event, total):
    """Keep the last few firings of EACH event, then the last `total` overall.

    A flat window is what hid RTK and caveman: PreToolUse and PostToolUse fire
    on every tool call, so within a dozen firings they are all that is left, and
    the hooks that run once at the start of a session - the ones an operator
    most wants to see - are always the ones evicted."""
    if not per_event:
        return hooks[-total:] if total else []
    by_event = {}
    for hook in hooks:
        by_event.setdefault(hook["event"], []).append(hook)
    kept = []
    for event, fired in by_event.items():
        kept.extend(fired[-per_event:])
    kept.sort(key=lambda hook: hook.get("at") or "")
    return kept[-total:] if total else kept


def _flow_from(records, cap, age, idle_after, subagent_cap=6, hook_cap=8,
               hook_per_event=2, declared=None, table=None):
    """The session's recent flow, its current state, and what it has spent.

    The percentage Part F asks for is NOT invented here. A transcript records
    tokens per message and never the size of the window they sit in, so the
    total is reported and the percentage is reported as unavailable with that
    reason (R8): a bar drawn from a guessed denominator reads exactly like a
    measured one."""
    steps = []
    subagents = []
    hooks = []
    usage = None
    for record in records:
        blocks = _blocks(record)
        fired = _hook_for(record)
        if fired:
            hooks.append(fired)
        found = _step_for(record, blocks)
        if found:
            found["at"] = record.get("timestamp") or ""
            found["sidechain"] = bool(record.get("isSidechain"))
            steps.append(found)
            if found["kind"] == "subagent":
                subagents.append({"name": found["name"], "at": found["at"]})
        seen = _usage_from(record, blocks)
        if seen:
            usage = seen
    dropped = max(0, len(steps) - cap)
    steps = steps[-cap:] if cap else []
    # Counted SEPARATELY on purpose. Measured 2026-09-01: a dispatch sharing the
    # step list with tool calls disappeared behind 120 later Bash calls, so the
    # one thing the operator was looking for was the one thing the cap dropped.
    # Hooks are separate for the opposite reason - PreToolUse and PostToolUse
    # fire on EVERY tool call, so sharing the list they would drown it.
    subagents = subagents[-subagent_cap:] if subagent_cap else []
    # Only the hooks THIS MACHINE declares. The transcript also records the
    # harness's own plugin hooks, which run inside a plugin nobody here
    # configured: showing them as `on Write` alongside BetterLeaks and Caveman
    # is noise wearing the same shape as the operator's own guards.
    hooks = _only_declared(hooks, declared, table or {})
    hooks = _keep_per_event(hooks, hook_per_event, hook_cap)

    last = steps[-1]["kind"] if steps else ""
    # A call with no result after it is still OUT, and a session waiting on one
    # is working however long it has been quiet: a build or a test run writes
    # nothing to the transcript for minutes. Silence alone therefore cannot mean
    # idle, which is what made an actively working session read as asleep.
    outstanding = last in ("tool", "subagent")
    if not steps or (age >= idle_after and not outstanding):
        state = "idle"
    else:
        state = {"prompt": "prompt", "reasoning": "reasoning", "tool": "tool",
                 "subagent": "tool", "result": "post_tool"}.get(last, "idle")

    tokens = {"status": "unavailable",
              "reason": "no usage recorded in this transcript's tail"}
    if usage:
        held = (int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0))
        tokens = {"status": "ok",
                  "held": held,
                  "output": int(usage.get("output_tokens") or 0),
                  "percent": None,
                  "percent_reason": "the transcript records tokens per message "
                                    "and never the window they sit in"}
    return {"status": "ok", "state": state, "steps": steps,
            "subagents": subagents, "hooks": hooks,
            "dropped": dropped, "tokens": tokens}


def _session_from(records):
    """Fold a transcript's tail into one session card."""
    card = {}
    hook_errors = []
    sidechains = 0
    for record in records:
        for key in ("sessionId", "cwd", "gitBranch", "mode", "lastPrompt",
                    "entrypoint", "effort", "version"):
            if record.get(key) not in (None, ""):
                card[key] = record[key]
        if record.get("isSidechain"):
            sidechains += 1
        system = record.get("system")
        if isinstance(system, dict):
            summary = system.get("stop_hook_summary")
            if isinstance(summary, dict):
                for err in summary.get("hookErrors", []) or []:
                    hook_errors.append(str(err))
    card["sidechain_records"] = sidechains
    card["hook_errors"] = hook_errors[-3:]
    return card


# A script whose name says nothing. Measured 2026-09-01: a plugin registers
# `hook.js` on EVERY event, so the roster carried an entry called `Hook` on all
# ten of them - and because its stem is a substring of every path containing
# `hooks/`, it then matched every plugin firing and relabelled the lot `Hook`.
# A hook with no name of its own is the harness's, not the operator's, and this
# panel is about the operator's.
GENERIC_HOOK_STEMS = ("hook", "hooks", "index", "main", "run")


def _hook_names(context):
    """The display-name table, or an empty one.

    Data, not code (R6): a hook added to settings.json is named in
    `hook-names.json` without touching this module. A missing or unparsable
    table degrades to the generic reading of a file name (R11) - it must never
    be the reason a panel is empty."""
    path = Path(__file__).resolve().parent.parent.parent / "hook-names.json"
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle).get("names", {})
    except (OSError, ValueError):
        return {}


def _hook_display(script, table):
    """What to CALL a hook. `betterleaks-hook.py` reads `BetterLeaks`.

    The operator asked for the NAME and not the file, and the inventory only
    knows the file. The table answers the ones this machine declares; anything
    else gets the readable form of its own stem, which is still a name rather
    than a path with an extension on it."""
    script = (script or "").strip()
    if not script:
        return ""
    if script in table:
        return table[script]
    stem = script.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    for suffix in ("-hook", "_hook", "-hooks"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    words = stem.replace("_", " ").replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else script


def _declared_hooks(inventory, table=None):
    """The hooks this machine DECLARES, per event, from the SessionStart
    inventory the session already prints.

    Firings are read from the transcript tail, and that is not enough on its
    own: a hook that runs once at SessionStart scrolls out of the tail within
    minutes of work, so on any session older than an hour the diagram showed
    PreToolUse and PostToolUse and nothing else. Measured 2026-09-01, and it is
    why the operator could not find RTK or caveman - the two hooks the figure
    draws as BACKGROUND LOOPS, which is exactly what a declared-but-not-recently
    -fired hook is.

    The inventory lines look like:
        SessionStart(7): install-junctions.ps1 [ok] | caveman-activate.js [ok]
    so the event is what precedes the colon and the names are what follow it.
    """
    declared = []
    for line in inventory or []:
        text = str(line)
        if ":" not in text or text.startswith("["):
            continue
        head, tail = text.split(":", 1)
        event = head.split("(")[0].strip()
        if not event or not event[0].isupper():
            continue
        # The bracketed status carries its own pipes - `[ok, Write|Edit]` - so
        # it is removed BEFORE the separator is split on, or every matcher in it
        # is read as another hook.
        names = []
        for chunk in re.sub(r"\[[^\]]*\]", "", tail).split("|"):
            script = chunk.strip().strip(",").strip()
            if not script:
                continue
            stem = script.rsplit(".", 1)[0].lower().replace("-", "")
            if script not in (table or {}) and stem in GENERIC_HOOK_STEMS:
                continue
            names.append({"name": _hook_display(script, table or {}),
                          "script": script})
        if names:
            declared.append({"event": event,
                             "names": [row["name"] for row in names],
                             "scripts": [row["script"] for row in names]})
    return declared


def _hooks_inventory(context):
    """The hooks inventory, reusing the SessionStart hook's own builder."""
    script = (context.repo_root / ".claude" / "hooks"
              / "session-hooks-inventory.py")
    settings = context.home / ".claude" / "settings.json"
    if not script.exists():
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py is not in this clone, so "
                          "the hook inventory cannot be built"}
    if not settings.exists():
        return {"status": "unavailable",
                "reason": "no ~/.claude/settings.json, so no hook is declared "
                          "on this machine"}
    spec = importlib.util.spec_from_file_location(
        "rt_observe_hooks_inventory", str(script))
    if spec is None or spec.loader is None:
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py could not be loaded"}
    module = importlib.util.module_from_spec(spec)
    sys.modules["rt_observe_hooks_inventory"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                            # noqa: BLE001
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py failed to import: %s" % exc}
    if not hasattr(module, "build_inventory"):
        return {"status": "unavailable",
                "reason": "session-hooks-inventory.py no longer exposes "
                          "build_inventory, the function this panel reuses"}
    try:
        parsed = json.loads(io.open(settings, encoding="utf-8-sig").read())
    except (ValueError, OSError) as exc:
        return {"status": "unavailable",
                "reason": "~/.claude/settings.json does not parse: %s" % exc}
    try:
        inventory = module.build_inventory(parsed)
    except Exception as exc:                            # noqa: BLE001
        return {"status": "unavailable",
                "reason": "build_inventory failed: %s" % exc}
    return {"status": "ok", "proven_by": "session-hooks-inventory.build_inventory",
            "inventory": inventory}


def _inbox(context, session_id):
    """Is this session reachable by the dashboard's inbox, and what is pending.

    A message written into a directory nobody drains is the vault drop that sat
    in working/ for an hour. So an unreachable target is SAID to be unreachable
    rather than reported as delivered.
    """
    root = context.home / ".claude" / "rt-inbox"
    hook_installed = False
    settings = context.home / ".claude" / "settings.json"
    if settings.exists():
        try:
            hook_installed = "rt-inbox" in io.open(
                settings, encoding="utf-8-sig").read()
        except OSError:
            hook_installed = False
    folder = root / session_id if session_id else None
    pending = 0
    if folder is not None and folder.is_dir():
        pending = len([p for p in folder.glob("*.json") if p.is_file()])
    return {
        "reachable": hook_installed,
        "pending": pending,
        "reason": (None if hook_installed else
                   "no inbox delivery hook is declared in ~/.claude/settings.json, "
                   "so a message written for this session would never be read"),
    }


def collect(context):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report Claude Code's live state: recent sessions, the hook inventory,
        and whether each session can be reached by the inbox.

    Inputs:
        context (AdapterContext): injected home, repo root, config and clock

    Outputs:
        state (dict): {"status", "sessions", "hooks", "counts"}
    --------------------------------------------------------------------------
    """
    projects = _projects_dir(context)
    excluded = set(_cap(context, "privacy", "excluded_projects"))
    prompt_cap = _cap(context, "caps", "prompt_chars")
    shown = _cap(context, "caps", "sessions_shown")
    tail_bytes = _cap(context, "caps", "transcript_tail_bytes")
    flow_cap = _cap(context, "caps", "flow_steps")
    subagent_cap = _cap(context, "caps", "flow_subagents")
    hook_cap = _cap(context, "caps", "flow_hooks")
    hook_per_event = _cap(context, "caps", "flow_hooks_per_event")
    name_table = _hook_names(context)
    declared = _declared_hooks(
        (_hooks_inventory(context) or {}).get("inventory"), name_table)
    idle_after = _cap(context, "staleness_seconds", "session_idle")

    transcripts = []
    for project_dir in sorted(projects.iterdir()) if projects.is_dir() else []:
        if not project_dir.is_dir() or project_dir.name in excluded:
            continue
        for path in project_dir.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            transcripts.append((mtime, project_dir.name, path))

    transcripts.sort(reverse=True)
    plans = {p.stem: p.name for p in (context.home / ".claude" / "plans").glob("*.md")} \
        if (context.home / ".claude" / "plans").is_dir() else {}

    sessions = []
    for mtime, project, path in transcripts[:shown]:
        records = _tail_records(path, tail_bytes)
        card = _session_from(records)
        session_id = card.get("sessionId") or path.stem
        age = int(max(0.0, context.now.timestamp() - mtime))
        flow = _flow_from(records, flow_cap, age, idle_after,
                          subagent_cap, hook_cap, hook_per_event,
                          declared, name_table)
        sessions.append({
            "session_id": session_id,
            "project": project,
            "cwd": _redact(card.get("cwd"), context.home),
            "branch": card.get("gitBranch"),
            "mode": card.get("mode"),
            "effort": card.get("effort"),
            "entrypoint": card.get("entrypoint"),
            # Redacted BEFORE truncation: a prompt is free text and routinely
            # quotes a path under the home directory, which is where the account
            # name lives. Measured 2026-08-31 on the rendered page: a session
            # card carried ~/.claude/plans/... spelled out in full, because only
            # the cwd was being redacted and the prompt was not.
            "prompt": _truncate(_redact(card.get("lastPrompt"), context.home),
                                prompt_cap),
            "subagents": card.get("sidechain_records", 0),
            "hook_errors": [_truncate(_redact(e, context.home), prompt_cap)
                            for e in card.get("hook_errors", [])],
            "age_seconds": age,
            "plan": plans.get(session_id),
            "flow": flow,
            "inbox": _inbox(context, session_id),
        })

    return {
        "status": "ok",
        "proven_by": "~/.claude/projects/*/*.jsonl",
        "proven_at": context.stamp,
        "counts": {"transcripts": len(transcripts), "shown": len(sessions),
                   "excluded_projects": len(excluded)},
        "sessions": sessions,
        "flow_states": [{"id": s[0], "label": s[1], "role": s[2]}
                        for s in FLOW_STATES],
        "hook_loops": declared,
        "hooks": _hooks_inventory(context),
    }
