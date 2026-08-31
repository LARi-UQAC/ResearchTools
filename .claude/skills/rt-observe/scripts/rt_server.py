"""
rt_server - the loopback HTTP server behind rt-dashboard.

It knows nothing about what the state IS. `rt_state.section_builders()` hands it
a mapping of section name to a callable, and this module's only additions are a
per-section TTL cache, four routes and the refusals that keep two dashboards from
showing two different snapshots. That split is deliberate: there is exactly one
definition of the snapshot, and the server cannot drift from it.

Binding. `127.0.0.1` only, never `0.0.0.0` (`.claude/rules/security.md`), and a
configured host that is not a loopback address is a refusal by design rather than
a warning - see `assert_loopback`.

The session token, and what it actually defends against. Loopback is shared by
every process on this machine, so the port is not an authorization boundary and
the token cannot make it one: `GET /` hands the token to whoever asks, because
that is how the page receives it. What the token DOES defend against is a page
on some other website POSTing to `127.0.0.1` in the operator's browser. Such a
request can be sent but its response cannot be read cross-origin, so the token
stays unknown to it and `POST /api/action` refuses. That is why the token gates
the action route and not `/api/state`: gating a GET whose token is readable from
`/` would be theatre. `Origin` is checked as well, and no CORS header is ever
emitted.

Every timeout, port and TTL comes from `observe-config.json` (R0). No numeric
literal of any of them appears here.
"""
import io
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_ID = "rt-observe"

# Which configured TTL governs which section. An enum-like table defined once
# rather than a string repeated at seven call sites (R5).
SECTION_TTL_KEY = {
    "mirrors": "mirrors",
    "registry": "registry",
    "repo_state": "repo",
    "progress": "progress",
    "graph": "graph",
    # MCP is its own section for one reason: it is the only collector that
    # reaches the network, so it needs its own, much longer timer. Sharing the
    # services timer is what made ttl_seconds.mcp_live dead config until
    # 2026-08-31.
    "mcp": "mcp_live",
    "services": "services",
    "fleet": "sessions",
}

_ASSET_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".js": "text/javascript; charset=utf-8",
}
TOKEN_PLACEHOLDER = "__RT_SESSION_TOKEN__"
VIEW_CONFIG_PLACEHOLDER = "__RT_VIEW_CONFIG__"


def _spawn_thread(work):
    """Run one background refresh. Daemon, so a slow collector never keeps the
    process alive after Ctrl+C."""
    threading.Thread(target=work, daemon=True).start()


class ServerRefusal(RuntimeError):
    """A refusal by design: the caller asked for something we will not do."""


def assert_loopback(host):
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse any bind address that is not loopback, before a socket exists.

    Inputs:
        host (str): the configured bind address

    Outputs:
        host (str): the same value, when it is a loopback address
    --------------------------------------------------------------------------
    """
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ServerRefusal("bind host %r does not resolve: %s" % (host, exc))
    for family, _, _, _, sockaddr in info:
        address = sockaddr[0]
        if family == socket.AF_INET and not address.startswith("127."):
            raise ServerRefusal(
                "refusing to bind %s: this server serves the fleet of every "
                "project on the machine and binds loopback only" % host)
        if family == socket.AF_INET6 and address not in ("::1",):
            raise ServerRefusal(
                "refusing to bind %s: loopback only" % host)
    return host


# --------------------------------------------------------------------------
# TTL cache
# --------------------------------------------------------------------------
class SnapshotCache:
    """Per-section TTL, so a two-second page poll never re-runs `claude mcp
    list`. Each section carries a receipt saying when it was collected and how
    old that makes it, because "green" with no timestamp is the failure this
    whole panel is built against.

    Two modes, and the second one exists because of a measurement. Blocking is
    what the one-shot `--json` dump wants: collect everything, print it, exit.
    Serving wants the opposite. Measured 2026-08-31 against the live server: the
    first `GET /api/state` did not return within 10 seconds, because the services
    section runs tier-1 `claude mcp list`, which reaches the network for 28
    servers under a 45-second budget. A TTL cannot help the FIRST call. So
    `snapshot(now, block=False)` never waits: a section already collected is
    served with its true age even when stale, a section never collected is
    reported `collecting` rather than blanked or faked, and the refresh happens
    on a background thread whose result the next poll picks up.
    """

    def __init__(self, builders, ttls, envelope=None, spawn=None):
        self._builders = builders
        self._ttls = dict(ttls)
        self._envelope = envelope or (lambda: {})
        self._cache = {}
        self._inflight = set()
        self._spawn = spawn or _spawn_thread
        self._lock = threading.Lock()

    def ttl_for(self, section):
        if section not in self._ttls:
            raise KeyError(
                "observe-config.json declares no ttl_seconds.%s, and this "
                "server never invents one" % SECTION_TTL_KEY.get(section, section))
        return self._ttls[section]

    def invalidate(self, section=None):
        """Drop a cached section so the next read re-collects it. This is what
        makes an action judged by EFFECT rather than by exit code (R9)."""
        with self._lock:
            if section is None:
                self._cache.clear()
            else:
                self._cache.pop(section, None)

    def warm(self, now):
        """Start every section collecting, in parallel, without waiting. Called
        once at startup so the first page load finds most panels already there
        instead of paying for the slowest collector."""
        for name, build in self._builders.items():
            self._refresh_later(name, build, now)

    def snapshot(self, now, block=True):
        sections = {}
        receipts = {}
        for name, build in self._builders.items():
            value, collected_at = self._section(name, build, now, block)
            ttl = self.ttl_for(name)
            if collected_at is None:
                # Never collected, and we are not waiting for it. Stated, not
                # blanked and not invented (R3, R8).
                sections[name] = {
                    "status": "collecting",
                    "reason": "first collection of %s is running; the next "
                              "poll carries it" % name}
                receipts[name] = {"collected_at": None, "ttl_seconds": ttl,
                                  "age_seconds": None, "state": "collecting"}
                continue
            age = max(0.0, (now - collected_at).total_seconds())
            sections[name] = value
            receipts[name] = {
                "collected_at": collected_at.isoformat(timespec="seconds"),
                "ttl_seconds": ttl,
                "age_seconds": round(age, 1),
                "state": "fresh" if age < ttl else "refreshing",
            }
        payload = dict(self._envelope())
        payload["generated"] = now.isoformat(timespec="seconds")
        payload.update(sections)
        payload["receipts"] = receipts
        return payload

    def _section(self, name, build, now, block=True):
        ttl = self.ttl_for(name)
        with self._lock:
            hit = self._cache.get(name)
        if hit is not None and now - hit[1] < timedelta(seconds=ttl):
            return hit
        if block:
            value = build(now)
            with self._lock:
                self._cache[name] = (value, now)
            return value, now
        self._refresh_later(name, build, now)
        if hit is not None:
            # Stale, and served WITH its real age rather than withheld. An old
            # answer labelled old beats a blank panel.
            return hit
        return None, None

    def _refresh_later(self, name, build, now):
        with self._lock:
            if name in self._inflight:
                return
            self._inflight.add(name)

        def work():
            try:
                value = build(now)
            except Exception as exc:                    # noqa: BLE001
                # A collector that dies on a background thread must land in the
                # panel as unavailable with its reason, never as a section that
                # silently never arrives.
                value = {"status": "unavailable",
                         "reason": "%s failed on refresh: %s: %s"
                                   % (name, type(exc).__name__, exc)}
            with self._lock:
                self._cache[name] = (value, now)
                self._inflight.discard(name)

        self._spawn(work)


# --------------------------------------------------------------------------
# Port probing - the launcher's two refusals
# --------------------------------------------------------------------------
def port_is_free(host, port):
    """Bind-test the port. No SO_REUSEADDR: an in-use port must fail."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def holding_pid(port, timeout_s):
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the process holding a port, so a refusal is actionable.

    Inputs:
        port (int): the TCP port
        timeout_s (float): explicit subprocess timeout (R10)

    Outputs:
        (pid, reason) (tuple): pid as str when found, else None with the reason
                               naming what was missing (R3, R8)
    --------------------------------------------------------------------------
    """
    plans = [
        ("netstat", ["netstat", "-ano"], r"[:.]%d\s+\S+\s+LISTEN\S*\s+(\d+)"),
        ("ss", ["ss", "-ltnp"], r"[:.]%d\s.*pid=(\d+)"),
        ("lsof", ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"],
         r"^\S+\s+(\d+)"),
    ]
    tried = []
    for name, argv, pattern in plans:
        binary = shutil.which(name)
        if not binary:
            tried.append(name)
            continue
        argv = [binary] + argv[1:]
        try:
            # errors="replace" is load-bearing, not defensive. Measured
            # 2026-08-31 on this machine: French Windows netstat emits byte 0x90
            # in its header, the default cp1252 decode raised UnicodeDecodeError
            # inside subprocess's reader THREAD, and stdout came back empty. The
            # caller then reported "netstat ran but reported no listener", which
            # is a wrong answer that reads like a right one - the port WAS held
            # and the pid was in the output.
            done = subprocess.run(argv, capture_output=True, text=True,
                                  errors="replace", timeout=timeout_s)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, "%s failed: %s" % (name, exc)
        for line in (done.stdout or "").splitlines():
            match = re.search(pattern % port if "%d" in pattern else pattern,
                              line, re.IGNORECASE)
            if match:
                return match.group(1), None
        return None, ("%s ran but reported no listener on port %d"
                      % (name, port))
    return None, ("the holding process cannot be named: none of %s is on PATH"
                  % ", ".join(tried))


def _ping(host, port, timeout_s, opener=None):
    url = "http://%s:%d/api/ping" % (host, port)
    open_url = opener or urllib.request.urlopen
    with open_url(url, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def probe_port(host, port, timeout_s, opener=None, free_check=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether the port is free, held by our own server, or held by
        something else. Two dashboards showing different snapshots is worse
        than none, so a foreign holder is never worked around.

    Inputs:
        host (str), port (int): the loopback endpoint
        timeout_s (float): explicit HTTP timeout (R10)
        opener (callable): urlopen replacement, for the suite
        free_check (callable): port_is_free replacement, for the suite

    Outputs:
        (verdict, detail) (tuple): verdict is "free", "ours" or "foreign"
    --------------------------------------------------------------------------
    """
    try:
        body = _ping(host, port, timeout_s, opener)
    except Exception as exc:                            # noqa: BLE001
        # Nothing answered our probe, or answered something unparsable. That is
        # not yet an answer: an unrelated server would also land here.
        free = (free_check or port_is_free)(host, port)
        if free:
            return "free", {}
        return "foreign", {
            "reason": "port %d is in use and did not answer %s's ping (%s: %s)"
                      % (port, APP_ID, type(exc).__name__, exc)}
    if isinstance(body, dict) and body.get("app") == APP_ID:
        return "ours", body
    return "foreign", {
        "reason": "an HTTP server answered on port %d but it is not %s"
                  % (port, APP_ID)}


def start_decision(host, port, timeout_s, subprocess_timeout_s,
                   opener=None, free_check=None, pid_lookup=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        The launcher's whole decision, with no side effect, so the suite can
        assert all three outcomes without binding a port or spawning anything.

    Inputs:
        host (str), port (int): the loopback endpoint
        timeout_s (float): ping timeout
        subprocess_timeout_s (float): timeout for the PID lookup
        opener, free_check, pid_lookup (callable): injected for the suite

    Outputs:
        decision (dict): {"action": "serve"|"already-running"|"refuse", ...}
    --------------------------------------------------------------------------
    """
    url = "http://%s:%d/" % (host, port)
    verdict, detail = probe_port(host, port, timeout_s, opener, free_check)
    if verdict == "free":
        return {"action": "serve", "url": url, "port": port, "host": host}
    if verdict == "ours":
        return {"action": "already-running", "url": url, "port": port,
                "host": host, "pid": detail.get("pid"),
                "started": detail.get("started")}
    pid, why = (pid_lookup or holding_pid)(port, subprocess_timeout_s)
    return {"action": "refuse", "url": url, "port": port, "host": host,
            "pid": pid, "pid_unavailable": why,
            "reason": detail.get("reason", "port %d is in use" % port)}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def make_handler(snapshot_fn, token, page_path, asset_roots,
                 action_runner=None, catalogue=None, log=None, started=None,
                 port=None, page_vars=None):
    """Build the request handler. Everything it needs is closed over, so the
    handler class holds no module-level state and two servers in one process
    could not share a token by accident."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "rt-observe"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):              # noqa: A003
            if log is not None:
                log("%s %s\n" % (self.address_string(), fmt % args))

        # -- helpers ----------------------------------------------------
        def _send(self, code, body, content_type):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # No CORS header, ever: another origin may send a request but must
            # never be able to read the answer.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, payload):
            self._send(code, json.dumps(payload, indent=2, default=str),
                       "application/json; charset=utf-8")

        def _origin_ok(self):
            origin = self.headers.get("Origin")
            if not origin:
                return True
            allowed = {"http://127.0.0.1:%s" % port,
                       "http://localhost:%s" % port}
            return origin in allowed

        # -- GET --------------------------------------------------------
        def do_GET(self):                               # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/":
                return self._page()
            if path == "/api/ping":
                return self._json(200, {
                    "app": APP_ID,
                    "pid": os.getpid(),
                    "started": started,
                    "url": "http://%s:%s/" % (self.server.server_address[0], port),
                })
            if path == "/api/state":
                return self._state()
            if path == "/api/actions":
                return self._catalogue()
            if path.startswith("/assets/"):
                return self._asset(path[len("/assets/"):])
            return self._json(404, {"status": "unavailable",
                                    "reason": "no route %s" % path})

        def do_HEAD(self):                              # noqa: N802
            self.do_GET()

        def _page(self):
            if page_path is None or not Path(page_path).exists():
                # Stated, never blanked: the server is up and the view is not
                # built yet, which is a different thing from a broken server.
                return self._send(503, (
                    "rt-observe is serving, and its page has not been built "
                    "yet.\n\nExpected: %s\n\nThe state itself is available at "
                    "/api/state.\n" % page_path),
                    "text/plain; charset=utf-8")
            with io.open(page_path, encoding="utf-8") as handle:
                markup = handle.read()
            # The page is served with its placeholders filled in, so no value
            # the server owns - the token, and the view block from
            # observe-config.json (R0) - is ever a literal in the markup.
            #
            # Resolved PER REQUEST, not once at startup. Measured 2026-08-31:
            # the markup was re-read from disk on every request while the
            # config was serialised once, so editing observe-config.json and
            # refreshing gave a page whose script read `undefined` for the new
            # key - which then produced NaN arithmetic and a silently broken
            # animation rather than any error. Two files that are read at
            # different times are two truths.
            variables = page_vars() if callable(page_vars) else (page_vars or {})
            for placeholder, value in variables.items():
                markup = markup.replace(placeholder, str(value))
            markup = markup.replace(TOKEN_PLACEHOLDER, token)
            self._send(200, markup, "text/html; charset=utf-8")

        def _state(self):
            try:
                payload = snapshot_fn()
            except Exception as exc:                    # noqa: BLE001
                return self._json(500, {
                    "status": "unavailable",
                    "reason": "the snapshot could not be assembled: %s: %s"
                              % (type(exc).__name__, exc)})
            return self._json(200, payload)

        def _catalogue(self):
            """What the page may offer as a button. An action that cannot run
            HERE arrives with available=false and its reason, because a dead
            button is worse than an absent one. This is a GET and carries no
            secret: it names scripts, never the token."""
            if catalogue is None:
                return self._json(501, {
                    "status": "unavailable",
                    "reason": "no action whitelist is installed on this "
                              "server, so the page offers no action at all"})
            try:
                entries = catalogue()
            except Exception as exc:                    # noqa: BLE001
                return self._json(500, {
                    "status": "unavailable",
                    "reason": "the action whitelist could not be read: %s: %s"
                              % (type(exc).__name__, exc)})
            return self._json(200, {"status": "ok", "actions": entries})

        def _asset(self, name):
            if not _ASSET_NAME.match(name):
                return self._json(404, {"status": "unavailable",
                                        "reason": "not an asset name"})
            suffix = Path(name).suffix.lower()
            if suffix not in _ASSET_TYPES:
                return self._json(404, {
                    "status": "unavailable",
                    "reason": "%s is not a served asset type" % suffix})
            for root in asset_roots:
                root = Path(root).resolve()
                candidate = (root / name).resolve()
                # Resolve first, then contain (R24). A name that walks out of
                # the root is refused rather than clamped.
                if root not in candidate.parents:
                    continue
                if candidate.is_file():
                    return self._send(200, candidate.read_bytes(),
                                      _ASSET_TYPES[suffix])
            return self._json(404, {"status": "unavailable",
                                    "reason": "%s is in no asset root" % name})

        # -- POST -------------------------------------------------------
        def do_POST(self):                              # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path != "/api/action":
                return self._json(404, {"status": "unavailable",
                                        "reason": "no route %s" % path})
            # The body is DRAINED first, whatever the verdict. This connection
            # is keep-alive, so refusing without consuming the body leaves those
            # bytes to be read as the next request line and every later answer on
            # the connection is misaligned.
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            if not self._origin_ok():
                return self._json(403, {
                    "status": "refused",
                    "reason": "cross-origin request refused"})
            try:
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("body is not an object")
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                return self._json(400, {
                    "status": "refused",
                    "reason": "the request body is not a JSON object: %s" % exc})
            supplied = body.get("token")
            if not supplied:
                return self._json(403, {
                    "status": "refused",
                    "reason": "no session token: it is printed when the server "
                              "starts and embedded in the served page"})
            if supplied != token:
                return self._json(403, {"status": "refused",
                                        "reason": "invalid session token"})
            if action_runner is None:
                return self._json(501, {
                    "status": "unavailable",
                    "reason": "the action runner is not installed on this "
                              "server, so no action can be run from the page"})
            try:
                result = action_runner(body)
            except Exception as exc:                    # noqa: BLE001
                return self._json(500, {
                    "status": "unavailable",
                    "reason": "the action runner raised: %s: %s"
                              % (type(exc).__name__, exc)})
            return self._json(int(result.get("http_status", 200)), result)

    return Handler


def build_server(host, port, cache, token, page_path, asset_roots,
                 action_runner=None, catalogue=None, log=None, clock=None,
                 page_vars=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Bind the server. `assert_loopback` runs FIRST, so a non-loopback host
        is refused before a socket exists rather than after.

    Inputs:
        host (str), port (int): the loopback endpoint
        cache (SnapshotCache): the per-section TTL cache
        token (str): the session token minted at startup
        page_path (Path): assets/rt_state.html, absent until the view is built
        asset_roots (list): directories `/assets/<name>` may be served from
        action_runner (callable): the whitelist runner behind POST
                                  /api/action; None means the route answers 501
        catalogue (callable): what GET /api/actions lists; None means the page
                              is told no whitelist is installed
        log (callable): where request lines go; None silences them
        clock (callable): returns the current time (R19, injected)

    Outputs:
        httpd (ThreadingHTTPServer): bound, not yet serving
    --------------------------------------------------------------------------
    """
    assert_loopback(host)
    started = clock().isoformat(timespec="seconds") if clock else None
    handler = make_handler(
        lambda: cache.snapshot(clock(), block=False),
        token, page_path, asset_roots,
        action_runner=action_runner, catalogue=catalogue, log=log,
        started=started, port=port, page_vars=page_vars)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    httpd.rt_cache = cache
    httpd.rt_token = token
    return httpd
