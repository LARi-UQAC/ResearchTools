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
import secrets
import sys
import webbrowser
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapters  # noqa: E402
import collect_graph  # noqa: E402
import collect_mirrors  # noqa: E402
import collect_progress  # noqa: E402
import collect_registry  # noqa: E402
import collect_repo  # noqa: E402
import collect_services
import collect_usage  # noqa: E402
import rt_actions  # noqa: E402
import rt_server  # noqa: E402

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


def _guarded(label, call):
    """A collector that raises costs its OWN panel and nothing else. An
    unavailable panel is stated on screen, never blanked and never silently
    omitted (R3, R8)."""
    try:
        return call()
    except Exception as exc:                            # noqa: BLE001
        return _unavailable("%s failed: %s: %s"
                            % (label, type(exc).__name__, exc))


def _mirror_section(repo_root, home, now):
    try:
        return collect_mirrors.collect(repo_root, home, now=now)
    except collect_mirrors.PolicyError as exc:
        # The one collector whose failure is worth stating loudly: with no policy
        # there is no by-design/lost distinction, which is the product.
        return _unavailable(str(exc))
    except OSError as exc:
        return _unavailable("the mirror matrix could not read the tree: %s" % exc)


def section_builders(repo_root=None, home=None, config=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Return one callable per snapshot section, so the one-shot CLI and the
        server's per-section TTL cache share ONE definition of what the state
        is. A section rebuilt on its own timer must be the same section the
        `--json` dump prints, or the page and the file disagree.

    Inputs:
        repo_root (Path): repository root, injected so a test drives a fixture
        home (Path): home directory user-scoped dialects resolve against
        config (dict): parsed observe-config.json, loaded when omitted

    Outputs:
        builders (OrderedDict): section name -> fn(now) -> section dict
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root or REPO_ROOT)
    home = Path(home if home is not None else Path.home())
    if config is None:
        config = load_config()

    def services(now):
        return collect_services.collect(repo_root, home, {
            "subprocess_timeout_s": config_value(
                config, "timeouts_seconds", "subprocess_default"),
            "outbox_root": config_value(config, "paths", "obsidian_outbox"),
            "outbox_listed": config_value(config, "caps", "outbox_listed"),
            "daemon_lock_path": config_value(
                config, "paths", "daemon_singleton_lock"),
            "lock_stale_after_s": config_value(
                config, "staleness_seconds", "daemon_lock"),
        }, now=now)

    return OrderedDict((
        ("mirrors", lambda now: _mirror_section(repo_root, home, now)),
        ("registry", lambda now: _guarded(
            "the registry check",
            lambda: collect_registry.collect(repo_root, now=now))),
        ("repo_state", lambda now: _guarded(
            "the repository panel",
            lambda: collect_repo.collect(
                repo_root, now,
                config_value(config, "staleness_seconds", "green_stamp")))),
        ("progress", lambda now: _guarded(
            "the progression panel",
            lambda: collect_progress.collect(repo_root, now=now))),
        ("graph", lambda now: _guarded(
            "the graph panel",
            lambda: collect_graph.collect(
                config_value(config, "paths", "graph_snapshot"), home, now,
                config_value(config, "staleness_seconds", "graph_snapshot")))),
        ("mcp", lambda now: _guarded(
            "the MCP roster",
            lambda: collect_services.collect_mcp(
                repo_root, home,
                {"mcp_timeout_s": config_value(
                    config, "timeouts_seconds", "mcp_list")},
                now=now))),
        ("services", lambda now: _guarded(
            "the services panel", lambda: services(now))),
        ("fleet", lambda now: _guarded(
            "the harness adapters",
            lambda: adapters.collect_all(
                adapters.AdapterContext(repo_root, home, config, now)))),
        ("usage", lambda now: _guarded(
            "the usage scan",
            lambda: collect_usage.collect(
                adapters.AdapterContext(repo_root, home, config, now)))),
    ))


def build_snapshot(repo_root=None, home=None, now=None, config=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Assemble the whole snapshot in one pass. Every section is independent:
        one failing collector degrades its own panel and never the page.

    Inputs:
        repo_root (Path): repository root, injected so a test can drive a fixture
        home (Path): home directory user-scoped dialects resolve against
        now (datetime): injected rather than read from the clock (R19)
        config (dict): parsed observe-config.json, loaded when omitted

    Outputs:
        snapshot (dict): {"generated", "repo", + one key per section}
    --------------------------------------------------------------------------
    """
    repo_root = Path(repo_root or REPO_ROOT)
    clock = now or datetime.now(timezone.utc)
    snapshot = {
        "generated": clock.isoformat(timespec="seconds"),
        "repo": {"root": str(repo_root), "name": repo_root.name},
    }
    for name, build in section_builders(repo_root, home, config).items():
        snapshot[name] = build(clock)
    return snapshot


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

    mcp = snapshot.get("mcp", {})
    stream.write("\nmcp          tier %s, %s\n" % (
        mcp.get("tier"), mcp.get("counts") if mcp.get("status") == "ok"
        else mcp.get("reason")))

    services = snapshot.get("services", {})
    if services.get("status") == "ok":
        stream.write("\nservices\n")
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


def page_path(skill_root=None):
    """Where the view lives. It does not exist until the design passes have
    produced it, and the server states that rather than failing."""
    return Path(skill_root or SKILL_ROOT) / "assets" / "rt_state.html"


def asset_roots(skill_root=None, repo_root=None):
    return [Path(skill_root or SKILL_ROOT) / "assets",
            Path(repo_root or REPO_ROOT) / "assets"]


def view_config(config):
    """
    --------------------------------------------------------------------------
    Purpose:
        Every number the served page would otherwise hardcode, as one JSON
        block injected into the page (R0). The markup carries no configured
        value of its own, so tuning the poll interval or the canvas physics is
        an edit to observe-config.json and never to the HTML.

    Inputs:
        config (dict): the parsed observe-config.json

    Outputs:
        view (dict): {"poll_ms", "canvas": {...}}
    --------------------------------------------------------------------------
    """
    canvas_keys = ("settle_ticks", "settle_ms", "spring", "repulsion",
                   "damping", "lane_pull", "min_alpha",
                   "vertical_below_px")
    return {
        "poll_ms": config_value(config, "view", "poll_ms"),
        "detail_rows": config_value(config, "view", "detail_rows"),
        "flow_groups": config_value(config, "caps", "flow_groups"),
        "refresh_choices_ms": config_value(config, "view",
                                           "refresh_choices_ms"),
        "refresh_bounds_ms": config_value(config, "view", "refresh_bounds_ms"),
        # May be null, and null is the shipped value: it is the DENOMINATOR of
        # the token bar, and nothing in a transcript reports it (R3 wants a
        # missing key named rather than defaulted, and this one is declared and
        # deliberately empty, which is a different thing).
        "context_window_tokens": config_value(config, "view",
                                              "context_window_tokens"),
        "canvas": {key: config_value(config, "view", "canvas", key)
                   for key in canvas_keys},
    }


def _ttl_floors(config):
    """The fastest a VIEWER may ask for each section, by the same key names the
    TTLs use. The refresh control lets a page ask for fresher data; this is what
    stops it asking for the impossible."""
    floors = config.get("ttl_floor_seconds")
    if not isinstance(floors, dict):
        raise KeyError("observe-config.json declares no ttl_floor_seconds")
    return {key: config_value(config, "ttl_floor_seconds", key)
            for key in floors}


def _ttls(config):
    return {section: config_value(config, "ttl_seconds", key)
            for section, key in rt_server.SECTION_TTL_KEY.items()}


def action_runner(args, config, cache, builders, clock):
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the whitelist runner the one write route calls, wired so that an
        action is judged by its EFFECT (R9): the section it claims to change is
        dropped from the TTL cache and collected again, through the SAME
        builders the page reads. There is no second definition of the state,
        so an action cannot be verified against a view the page never sees.

    Inputs:
        args (Namespace), config (dict), cache (SnapshotCache),
        builders (OrderedDict), clock (callable)

    Outputs:
        runner (rt_actions.Runner) or None when actions.json is missing, which
        is stated by the route rather than crashing the server
    --------------------------------------------------------------------------
    """
    def section_fn(name):
        cache.invalidate(name)
        return builders[name](clock())

    try:
        return rt_actions.Runner(
            Path(args.repo_root or REPO_ROOT),
            Path(args.home) if args.home else Path.home(),
            rt_actions.runner_values(config, config_value),
            section_fn=section_fn, clock=clock)
    except rt_actions.ActionsError:
        return None


def serve(args, config, out=None, err=None, clock=None,
          decide=None, browse=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Start the loopback server, or refuse. The three refusals are the whole
        reason this is a function rather than four lines in main(): a port held
        by something else is named and never worked around, because two
        dashboards showing two different snapshots is worse than none.

    Inputs:
        args (Namespace): the parsed CLI
        config (dict): parsed observe-config.json
        out, err (stream): stdout and stderr, injected for the suite
        clock (callable): returns the current time (R19)
        decide (callable): rt_server.start_decision replacement, for the suite
        browse (callable): webbrowser.open replacement, for the suite

    Outputs:
        code (int): 0 serving or already running, 1 refused, 2 refusal by design
    --------------------------------------------------------------------------
    """
    out = out or sys.stdout
    err = err or sys.stderr
    clock = clock or (lambda: datetime.now(timezone.utc))
    repo_root = Path(args.repo_root or REPO_ROOT)

    host = config_value(config, "server", "bind_host")
    port = int(args.port or config_value(config, "server", "port"))
    decision = (decide or rt_server.start_decision)(
        host, port,
        config_value(config, "timeouts_seconds", "ping"),
        config_value(config, "timeouts_seconds", "subprocess_default"))
    page = page_path()
    url = decision["url"]

    if args.dry_run:
        # Prints what it would do and touches nothing (R16). It returns the code
        # the real run WOULD return, so a script can use it as a preflight.
        out.write("rt-dashboard --dry-run\n")
        out.write("  interpreter   %s\n" % sys.executable)
        out.write("  bind          %s:%d  (loopback only)\n" % (host, port))
        out.write("  url           %s\n" % url)
        out.write("  page          %s%s\n"
                  % (page, "" if page.exists() else "   NOT BUILT YET"))
        out.write("  token         minted at startup, %s bytes of entropy\n"
                  % config_value(config, "server", "token_bytes"))
        for section, ttl in sorted(_ttls(config).items()):
            out.write("  ttl %-12s %ss\n" % (section, ttl))
        out.write("  would         %s\n" % decision["action"])
        if decision["action"] == "refuse":
            out.write("  refusal       %s\n" % decision["reason"])
        if args.open:
            out.write("  would open    %s in the default browser\n" % url)
        out.write("  started       nothing\n")
        return 1 if decision["action"] == "refuse" else 0

    if decision["action"] == "already-running":
        out.write("rt-dashboard is already running: %s\n" % url)
        if decision.get("pid"):
            out.write("  pid %s, started %s\n"
                      % (decision["pid"], decision.get("started")))
        out.write("  not starting a second one. Its token was printed when it "
                  "started.\n")
        if args.open:
            (browse or webbrowser.open)(url)
        return 0

    if decision["action"] == "refuse":
        err.write("rt-dashboard refuses to start: %s\n" % decision["reason"])
        if decision.get("pid"):
            err.write("  held by pid %s\n" % decision["pid"])
        else:
            err.write("  %s\n" % decision.get("pid_unavailable"))
        err.write("  free the port, or pass --port <n> for a different one. "
                  "Binding a second port would show two snapshots.\n")
        return 1

    token = secrets.token_urlsafe(
        int(config_value(config, "server", "token_bytes")))
    builders = section_builders(args.repo_root, args.home, config)
    cache = rt_server.SnapshotCache(
        builders, _ttls(config), floors=_ttl_floors(config),
        envelope=lambda: {"repo": {"root": str(repo_root),
                                   "name": repo_root.name}})
    runner = action_runner(args, config, cache, builders, clock)
    try:
        httpd = rt_server.build_server(
            host, port, cache, token, page,
            asset_roots(repo_root=repo_root), clock=clock,
            action_runner=(runner.run if runner else None),
            catalogue=(runner.catalogue if runner else None),
            # A callable, so the view block is rebuilt from disk on each
            # request: editing observe-config.json then refreshing is enough,
            # exactly as it already was for the markup itself.
            page_vars=lambda: {rt_server.VIEW_CONFIG_PLACEHOLDER:
                               json.dumps(view_config(load_config()))})
    except rt_server.ServerRefusal as exc:
        err.write("%s\n" % exc)
        return 2
    except OSError as exc:
        # The probe said free and the bind disagreed: something took the port in
        # between. Report it rather than retrying on another port.
        err.write("rt-dashboard could not bind %s:%d: %s\n" % (host, port, exc))
        return 1

    # Start every collector at once rather than making the first page load pay
    # for the slowest one. Measured 2026-08-31: the services section runs
    # tier-1 `claude mcp list`, which reaches the network for 28 servers.
    cache.warm(clock())
    out.write("rt-dashboard serving  %s\n" % url)
    out.write("  session token  %s\n" % token)
    out.write("  state          %sapi/state\n" % url)
    if not page.exists():
        out.write("  page           NOT BUILT YET (%s). /api/state answers.\n"
                  % page)
    out.write("  Ctrl+C to stop.\n")
    out.flush()
    if args.open:
        (browse or webbrowser.open)(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        out.write("\nrt-dashboard stopped.\n")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Report the state of this toolkit: mirror matrix first.")
    parser.add_argument("--json", action="store_true",
                        help="write the whole snapshot to stdout as JSON")
    parser.add_argument("--serve", action="store_true",
                        help="serve the dashboard on loopback instead of "
                             "printing once")
    parser.add_argument("--open", action="store_true",
                        help="with --serve, hand the URL to the default browser")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --serve, print what would happen and start "
                             "nothing")
    parser.add_argument("--port", type=int, default=None,
                        help="override the configured port for this run")
    parser.add_argument("--repo-root", default=None,
                        help="repository root (default: this skill's own repo)")
    parser.add_argument("--home", default=None,
                        help="home directory for user-scoped dialects "
                             "(default: the real one). Point it at an empty "
                             "directory to reproduce a fresh clone.")
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except ConfigError as exc:
        sys.stderr.write("%s\n" % exc)
        return 2

    if args.serve or args.dry_run:
        try:
            return serve(args, config)
        except ConfigError as exc:
            sys.stderr.write("%s\n" % exc)
            return 2

    try:
        snapshot = build_snapshot(repo_root=args.repo_root, home=args.home,
                                  config=config)
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
