"""
collect_services - the shared infrastructure every harness leans on.

Three services, deliberately in the CORE rather than in an adapter, because none
of them belongs to one harness: the MCP roster, the local model daemon, and the
Obsidian vault daemon.

MCP is reported in two tiers, because the live half is Claude-specific and this
tool may not have Claude at all.

  Tier 1, only when the `claude` binary is on PATH: `claude mcp list` reports
  three states - connected, needs authentication, failed to connect. Behind its
  own long TTL because it reaches the network for every server.

  Tier 2, always: the DECLARED roster read straight from configuration files,
  reported as "configured, liveness unavailable" with the reason. Measured
  2026-08-30, grepping a full session transcript for connection state returned
  zero hits: live MCP state exists on no file on disk, so tier 2 is honest about
  being a roster and not a status.

A Codex user on Linux therefore gets tier 2 and a panel that says so, never a
blank one. Every subprocess call carries an explicit timeout from configuration
(R10), and a timeout is reported as unavailable with its reason - never as an
empty roster, which would read as "no servers configured" (R8).

This module never reads the Obsidian vault. The daemon's lock and its outbox live
under the Claude home, outside the vault, so the access guard is not involved and
the single-writer rule is untouched. Liveness and queue depth only, never note
content.
"""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MCP_STATE_MARKERS = (
    ("connected", ("✔", "connected")),
    ("needs-auth", ("needs authentication", "needs auth")),
    ("failed", ("✘", "failed to connect")),
)


def _run(argv, timeout_s):
    """A bounded subprocess. Returns (ok, stdout, reason)."""
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s,
            check=False)
    except subprocess.TimeoutExpired:
        return False, "", ("%s did not answer within %ss; reporting unavailable "
                           "rather than an empty result, which would read as "
                           "'nothing configured'" % (argv[0], timeout_s))
    except OSError as exc:
        return False, "", "%s could not be run: %s" % (argv[0], exc)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip()
        # Keep the END of the output: a traceback names its exception last.
        return False, "", "%s exited %d: %s" % (
            argv[0], completed.returncode, tail[-300:])
    return True, completed.stdout, None


def _classify_mcp_line(line):
    lowered = line.lower()
    for state, markers in MCP_STATE_MARKERS:
        for marker in markers:
            if marker in lowered or marker in line:
                return state
    return None


def _mcp_tier1(timeout_s):
    # shutil.which is used for the RESOLVED PATH, not merely as a presence test.
    # On Windows the launcher is claude.CMD, and passing the bare name to
    # subprocess without a shell fails with [WinError 2] - measured 2026-08-30,
    # which silently demoted a machine that HAS the binary to the tier-2 roster.
    binary = shutil.which("claude")
    if not binary:
        return None
    ok, out, reason = _run([binary, "mcp", "list"], timeout_s)
    if not ok:
        return {"status": "unavailable", "tier": 1, "reason": reason}
    servers = []
    counts = {"connected": 0, "needs-auth": 0, "failed": 0}
    for line in out.splitlines():
        text = line.strip()
        if not text or ":" not in text:
            continue
        state = _classify_mcp_line(text)
        if state is None:
            continue
        name = text.split(":", 1)[0].strip()
        if not name:
            continue
        servers.append({"name": name, "state": state})
        counts[state] += 1
    if not servers:
        return {"status": "unavailable", "tier": 1,
                "reason": "`claude mcp list` answered but no server line could be "
                          "parsed; the output format may have changed"}
    return {"status": "ok", "tier": 1, "liveness": "live",
            "proven_by": "claude mcp list",
            "servers": sorted(servers, key=lambda s: s["name"]),
            "counts": counts}


def _mcp_tier2(repo_root, home):
    """The declared roster, from configuration. Always available."""
    sources = [
        ("repo .mcp.json", Path(repo_root) / ".mcp.json"),
        ("repo .vscode/mcp.json", Path(repo_root) / ".vscode" / "mcp.json"),
        ("~/.claude.json", Path(home) / ".claude.json"),
    ]
    names = set()
    read = []
    for label, path in sources:
        if not path.exists():
            continue
        try:
            with io.open(path, encoding="utf-8-sig") as handle:
                data = json.loads(handle.read())
        except (ValueError, OSError):
            continue
        read.append(label)
        for key in ("mcpServers", "servers"):
            block = data.get(key)
            if isinstance(block, dict):
                names.update(block.keys())
    codex_toml = Path(home) / ".codex" / "config.toml"
    if codex_toml.exists():
        try:
            with io.open(codex_toml, encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if (stripped.startswith("[mcp_servers.")
                            and stripped.endswith("]")):
                        names.add(stripped[len("[mcp_servers."):-1])
            read.append("~/.codex/config.toml")
        except OSError:
            pass

    if not read:
        return {"status": "unavailable", "tier": 2,
                "reason": "no MCP configuration found in the repository or the "
                          "home directory, so nothing declares a server here"}
    return {
        "status": "ok", "tier": 2, "liveness": "unavailable",
        "proven_by": ", ".join(read),
        "reason": "configured roster only. Live connection state exists on no "
                  "file on disk; only `claude mcp list` reports it, and that "
                  "command is unavailable here - see tier1_reason when present, "
                  "otherwise the claude binary is not on PATH.",
        "servers": [{"name": n, "state": "configured"} for n in sorted(names)],
        "counts": {"configured": len(names)},
    }


def _ollama(timeout_s):
    binary = shutil.which("ollama")
    if not binary:
        return {"status": "unavailable",
                "reason": "ollama is not on PATH, so no local model can be "
                          "resident and none is reported"}
    ok, out, reason = _run([binary, "ps"], timeout_s)
    if not ok:
        return {"status": "unavailable", "reason": reason}
    lines = [line for line in out.splitlines() if line.strip()]
    rows = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append({"tag": parts[0], "detail": " ".join(parts[1:])})
    return {
        "status": "ok",
        "proven_by": "ollama ps",
        "resident_count": len(rows),
        "resident": rows,
        "reason": (None if rows else
                   "the daemon is up and holds no model resident; the first "
                   "request will pay a load"),
    }


def _load_module(path, name):
    """Import a module by PATH.

    Needed because the modules reused here live in another skill and, in the
    hooks case, carry hyphens in the filename, which cannot be imported by name
    at all.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:                                  # noqa: BLE001
        return None
    return module


def _vault_daemon(repo_root, home, outbox_root, lock_path_value, stale_after_s):
    """Liveness and queue depth. Never note content, never the vault.

    The lock asked here is the SINGLETON lock, and getting that wrong reports
    exactly backwards. Two locks live side by side: obsidian-outbox.lock
    serializes writers and is held only for the instant of a write, so a healthy
    idle daemon does not hold it; vault-daemon.lock is the one that says a daemon
    owns this machine. Measured 2026-08-30, this collector asked the write lock
    and called a running daemon dead.
    """
    lock_path = _expand(lock_path_value, home)
    vault_lock_py = (Path(repo_root) / ".claude" / "skills" / "obsidian-cli"
                     / "scripts" / "vault_lock.py")
    running = None
    reason = None
    if not vault_lock_py.exists():
        reason = ("vault_lock.py is not in this clone, so daemon liveness cannot "
                  "be judged; the lock file existing does NOT mean a daemon is "
                  "running, since a killed daemon leaves its lock behind")
    else:
        module = _load_module(vault_lock_py, "rt_observe_vault_lock")
        if module is None or not hasattr(module, "held_by_live_holder"):
            reason = ("vault_lock.py could not be loaded or no longer exposes "
                      "held_by_live_holder, the read-only liveness check")
        else:
            try:
                running = bool(module.held_by_live_holder(lock_path, stale_after_s))
            except Exception as exc:                   # noqa: BLE001
                reason = "the liveness check failed: %s" % exc

    queue = {}
    root = Path(_expand(outbox_root, home))
    if root.is_dir():
        for folder in ("raw", "working", "sent", "needs-review", "queue"):
            directory = root / folder
            queue[folder] = (len([p for p in directory.iterdir() if p.is_file()])
                             if directory.is_dir() else None)

    waiting = queue.get("raw") or 0
    return {
        "status": "ok" if reason is None else "degraded",
        "proven_by": "vault_lock.held_by_live_holder",
        "running": running,
        "reason": reason,
        "lock": str(lock_path.name),
        "outbox": str(root),
        "queue": queue,
        "alert": ("%d raw drop(s) are waiting and no daemon holds the lock, so "
                  "nothing will consume them" % waiting
                  if waiting and running is False else None),
    }


def _expand(value, home):
    text = str(value)
    if text.startswith("~/"):
        return Path(home) / text[2:]
    return Path(text)


def collect(repo_root, home, config_values, now=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the shared services: MCP, local models, the vault daemon.

    Inputs:
        repo_root (Path): repository root
        home (Path): home directory, injected (R21)
        config_values (dict): {"mcp_timeout_s", "subprocess_timeout_s",
                               "outbox_root", "daemon_lock_path",
                               "lock_stale_after_s"}
        now (datetime): injected clock (R19)

    Outputs:
        state (dict): {"mcp", "local_models", "vault_daemon"}
    --------------------------------------------------------------------------
    """
    stamp = now.isoformat(timespec="seconds") if now else None
    mcp = _mcp_tier1(config_values["mcp_timeout_s"])
    if mcp is None or mcp.get("status") != "ok":
        fallback = _mcp_tier2(repo_root, home)
        if mcp is not None and mcp.get("status") != "ok":
            fallback["tier1_reason"] = mcp.get("reason")
        mcp = fallback

    return {
        "status": "ok",
        "collected_at": stamp,
        "mcp": mcp,
        "local_models": _ollama(config_values["subprocess_timeout_s"]),
        "vault_daemon": _vault_daemon(repo_root, home,
                                      config_values["outbox_root"],
                                      config_values["daemon_lock_path"],
                                      config_values["lock_stale_after_s"]),
    }
