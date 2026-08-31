"""
rt_state - assemble and print the rt-observe state snapshot.

The machine-facing half of the rt-dashboard. `--json` writes the whole snapshot
to stdout; the server and the page are added in a later phase and read the same
assembly function, so there is exactly one definition of what the state IS.

Harness-neutral by construction: standard library only, no PowerShell, no npm,
no Docker, no build step, and no file outside the clone is required. A collector
that cannot answer returns {"status": "unavailable", "reason": ...} and never
raises and never guesses (R3, R8), so an unavailable panel is stated on screen
rather than blanked.
"""
import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapters  # noqa: E402
import collect_graph  # noqa: E402
import collect_mirrors  # noqa: E402
import collect_progress  # noqa: E402
import collect_registry  # noqa: E402
import collect_repo  # noqa: E402
import collect_services  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parent.parent.parent


class ConfigError(RuntimeError):
    """A configuration key is missing. Named, never defaulted (R3)."""


def load_config(skill_root=None):
    path = Path(skill_root or SKILL_ROOT) / "observe-config.json"
    if not path.exists():
        raise ConfigError(
            "observe-config.json not found at %s. It holds every port, timeout "
            "and cap this tool uses; none of them has a default in the code." % path)
    try:
        with io.open(path, encoding="utf-8-sig") as handle:
            return json.loads(handle.read())
    except ValueError as exc:
        raise ConfigError("observe-config.json does not parse: %s" % exc)


def config_value(config, *keys):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one configured value, failing with the key path when it is absent.

    Inputs:
        config (dict): the parsed observe-config.json
        keys (str): the path to the value, e.g. ("server", "port")

    Outputs:
        value: whatever the config declares under keys + ["value"]
    --------------------------------------------------------------------------
    """
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ConfigError(
                "observe-config.json declares no %s" % ".".join(keys))
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise ConfigError(
            "observe-config.json: %s has no 'value'" % ".".join(keys))
    return node["value"]


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def build_snapshot(repo_root=None, home=None, now=None, config=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Assemble the whole snapshot. Every section is independent: one failing
        collector degrades its own panel and never the page.

    Inputs:
        repo_root (Path): repository root, injected so a test can drive a fixture
        home (Path): home directory user-scoped dialects resolve against
        now (datetime): injected rather than read from the clock (R19)
        config (dict): parsed observe-config.json, loaded when omitted

    Outputs:
        snapshot (dict): {"generated", "repo", "mirrors"}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root or REPO_ROOT)
    home = Path(home if home is not None else Path.home())
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    if config is None:
        config = load_config()

    clock = now or datetime.now(timezone.utc)

    try:
        mirrors = collect_mirrors.collect(repo_root, home, now=now)
    except collect_mirrors.PolicyError as exc:
        # The one collector whose failure is worth stating loudly: with no policy
        # there is no by-design/lost distinction, which is the product.
        mirrors = _unavailable(str(exc))
    except OSError as exc:
        mirrors = _unavailable("the mirror matrix could not read the tree: %s" % exc)

    # Each section is wrapped independently. A collector that raises costs its own
    # panel and nothing else: an unavailable panel is STATED on screen, never
    # blanked and never silently omitted (R3, R8).
    def guarded(label, call):
        try:
            return call()
        except Exception as exc:                        # noqa: BLE001
            return _unavailable("%s failed: %s: %s"
                                % (label, type(exc).__name__, exc))

    registry = guarded("the registry check",
                       lambda: collect_registry.collect(repo_root, now=clock))
    repo = guarded("the repository panel", lambda: collect_repo.collect(
        repo_root, clock, config_value(config, "staleness_seconds", "green_stamp")))
    progress = guarded("the progression panel",
                       lambda: collect_progress.collect(repo_root, now=clock))
    graph = guarded("the graph panel", lambda: collect_graph.collect(
        config_value(config, "paths", "graph_snapshot"), home, clock,
        config_value(config, "staleness_seconds", "graph_snapshot")))
    services = guarded("the services panel", lambda: collect_services.collect(
        repo_root, home,
        {
            "mcp_timeout_s": config_value(config, "timeouts_seconds", "mcp_list"),
            "subprocess_timeout_s": config_value(
                config, "timeouts_seconds", "subprocess_default"),
            "outbox_root": config_value(config, "paths", "obsidian_outbox"),
            "daemon_lock_path": config_value(
                config, "paths", "daemon_singleton_lock"),
            "lock_stale_after_s": config_value(
                config, "staleness_seconds", "daemon_lock"),
        }, now=clock))

    context = adapters.AdapterContext(repo_root, home, config, clock)
    fleet = guarded("the harness adapters",
                    lambda: adapters.collect_all(context))

    return {
        "generated": stamp,
        "repo": {"root": str(repo_root), "name": repo_root.name},
        "mirrors": mirrors,
        "registry": registry,
        "repo_state": repo,
        "progress": progress,
        "graph": graph,
        "services": services,
        "fleet": fleet,
    }


def _print_text(snapshot, stream):
    mirrors = snapshot.get("mirrors", {})
    stream.write("rt-observe  %s\n" % snapshot.get("generated", ""))
    stream.write("repository  %s\n\n" % snapshot.get("repo", {}).get("root", ""))
    if mirrors.get("status") != "ok":
        stream.write("mirror matrix UNAVAILABLE: %s\n" % mirrors.get("reason"))
        return
    totals = mirrors.get("totals", {})
    order = [collect_mirrors.LOST, collect_mirrors.STALE, collect_mirrors.ORPHAN,
             collect_mirrors.STUBBED, collect_mirrors.TRIMMED,
             collect_mirrors.BY_DESIGN, collect_mirrors.UNKNOWN, collect_mirrors.OK]
    stream.write("mirror matrix\n")
    for state in order:
        stream.write("  %-10s %d\n" % (state, totals.get(state, 0)))
    manifest = mirrors.get("manifest", {})
    if manifest.get("status") != "ok":
        stream.write("\n  manifest unavailable: %s\n" % manifest.get("reason"))
    lost = [r for r in mirrors.get("rows", [])
            if r["state"]["value"] == collect_mirrors.LOST]
    if lost:
        stream.write("\n  LOST, with no design reason:\n")
        for row in lost:
            stream.write("    %-24s %s\n" % (row["target"], row["name"]))

    _print_sections(snapshot, stream)


def _print_sections(snapshot, stream):
    """Every other panel, each stating its own unavailability rather than
    vanishing. A blank panel and an absent one look identical on a screen."""
    repo_state = snapshot.get("repo_state", {})
    if repo_state.get("status") == "ok":
        green = repo_state.get("green", {})
        branch = repo_state.get("branch", {})
        profile = repo_state.get("profile", {})
        stream.write("\nrepository\n")
        stream.write("  branch     %s\n" % (branch.get("value")
                                            or branch.get("reason")))
        stream.write("  profile    %s\n" % (profile.get("value")
                                            or profile.get("reason")))
        stream.write("  suite      %s%s\n" % (
            green.get("value"),
            "  (aged)" if green.get("aged") else ""))
        if green.get("status") != "ok":
            stream.write("             %s\n" % green.get("reason"))

    registry = snapshot.get("registry", {})
    if registry.get("status") == "ok":
        stream.write("\nregistry     %s\n" % (
            "clean" if registry.get("clean")
            else "%d definition(s) malformed" % registry.get("problem_count", 0)))
        for finding in registry.get("findings", []):
            for problem in finding.get("problems", []):
                stream.write("  %-10s %s: %s\n"
                             % (finding["kind"], finding["name"], problem))

    progress = snapshot.get("progress", {})
    stream.write("\nprogress\n")
    if progress.get("status") != "ok":
        stream.write("  unavailable: %s\n" % progress.get("reason"))
    else:
        for phase in progress.get("phases", []):
            stream.write("  [%-10s] %s\n" % (phase["state"], phase["label"]))
        if progress.get("next_action"):
            stream.write("  NEXT ACTION: %s\n" % progress["next_action"])

    graph = snapshot.get("graph", {})
    stream.write("\ngraph        ")
    if graph.get("status") != "ok":
        stream.write("unavailable: %s\n" % graph.get("reason"))
    else:
        stream.write("%s nodes, %s links%s\n" % (
            graph.get("nodes"), graph.get("links"),
            "  (stale)" if graph.get("stale") else ""))

    services = snapshot.get("services", {})
    if services.get("status") == "ok":
        mcp = services.get("mcp", {})
        stream.write("\nservices\n")
        stream.write("  mcp        tier %s, %s\n" % (
            mcp.get("tier"), mcp.get("counts") if mcp.get("status") == "ok"
            else mcp.get("reason")))
        models = services.get("local_models", {})
        stream.write("  models     %s\n" % (
            "%d resident" % models["resident_count"]
            if models.get("status") == "ok" else models.get("reason")))
        daemon = services.get("vault_daemon", {})
        stream.write("  daemon     running=%s  queue=%s\n"
                     % (daemon.get("running"), daemon.get("queue")))
        if daemon.get("alert"):
            stream.write("             %s\n" % daemon["alert"])

    fleet = snapshot.get("fleet", {})
    if fleet.get("harnesses"):
        stream.write("\nfleet\n")
        for adapter_id, state in sorted(fleet["harnesses"].items()):
            if state.get("status") != "ok":
                stream.write("  %-14s %s: %s\n" % (adapter_id,
                                                   state.get("status"),
                                                   state.get("reason")))
                continue
            stream.write("  %-14s %d session(s)\n"
                         % (adapter_id, len(state.get("sessions", []))))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Report the state of this toolkit: mirror matrix first.")
    parser.add_argument("--json", action="store_true",
                        help="write the whole snapshot to stdout as JSON")
    parser.add_argument("--repo-root", default=None,
                        help="repository root (default: this skill's own repo)")
    parser.add_argument("--home", default=None,
                        help="home directory for user-scoped dialects "
                             "(default: the real one). Point it at an empty "
                             "directory to reproduce a fresh clone.")
    args = parser.parse_args(argv)

    try:
        snapshot = build_snapshot(repo_root=args.repo_root, home=args.home)
    except ConfigError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    if args.json:
        json.dump(snapshot, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_text(snapshot, sys.stdout)

    mirrors = snapshot.get("mirrors", {})
    if mirrors.get("status") != "ok":
        return 1
    # Exit codes mean something (R12): 0 clean, 1 something is LOST or STALE,
    # 2 a refusal by design. by-design, stubbed and trimmed are intended states
    # and never fail the run.
    totals = mirrors.get("totals", {})
    bad = totals.get(collect_mirrors.LOST, 0) + totals.get(collect_mirrors.STALE, 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
