"""
test_rt_state - the loopback server, its routes, its TTL cache and its refusals.

Offline, and offline in the strong sense: NO port is bound and NO process is
spawned. The request handler is driven in memory over a fake socket, `socket`
and `subprocess` are patched wherever the code would reach for them, and the
one test that touches the shipped `observe-config.json` reads it rather than
writing it.

The assertions that carry weight are the refusals, because each of them is a
wrong answer that would look like a right one:

- a port held by SOMETHING ELSE must be named and refused, never worked around
  by binding a second port, since two dashboards showing two different
  snapshots is worse than none;
- our own server already running is reported with its URL, not started twice;
- a bind host that is not loopback is refused BEFORE a socket exists;
- `POST /api/action` without the session token is refused, and the token is
  what stops a page on another website from POSTing into this server;
- a section within its TTL is served from the cache, so a two-second page poll
  can never re-run `claude mcp list`;
- the view not being built yet is STATED with the path it looked for, which is
  a different thing from a broken server.
"""
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rt_server  # noqa: E402
import rt_state  # noqa: E402

NOW = datetime(2026, 8, 31, 9, 0, 0, tzinfo=timezone.utc)
TOKEN = "test-token-not-a-secret"


def fixture_config(bind_host="127.0.0.1", port=8787):
    """A config built here rather than read from disk, so tuning a shipped TTL
    cannot fail this suite (R21 in spirit: no measured value in a test)."""
    def value(v, **extra):
        item = {"value": v}
        item.update(extra)
        return item

    return {
        "server": {"bind_host": value(bind_host), "port": value(port),
                   "token_bytes": value(8)},
        "ttl_seconds": {"mirrors": value(15), "repo": value(30),
                        "registry": value(60), "progress": value(15),
                        "services": value(60), "sessions": value(10),
                        "graph": value(60), "mcp_live": value(300)},
        "timeouts_seconds": {"subprocess_default": value(20),
                             "mcp_list": value(45), "action_default": value(600),
                             "ping": value(2)},
        # Everything the served page reads, injected as one block so the markup
        # carries no configured number (R0). The shipped file's own keys are
        # asserted separately, against the real config rather than this one.
        "view": {"poll_ms": value(2000),
                 "canvas": {"settle_ticks": value(320), "settle_ms": value(420),
                            "spring": value(0.045), "repulsion": value(2600),
                            "damping": value(0.86), "lane_pull": value(0.09),
                            "min_alpha": value(0.004),
                            "vertical_below_px": value(640)}},
        # What the action runner reads. serve() builds the runner before it
        # binds, so a config missing these fails the REFUSAL cases too - which
        # is how this block came to be added.
        "paths": {"action_log": value("~/.claude/rt-actions.jsonl"),
                  "inbox_root": value("~/.claude/rt-inbox")},
        "caps": {"inbox_message_chars": value(4000),
                 "output_tail_chars": value(2000)},
    }


def ttls_from(config):
    return {section: config["ttl_seconds"][key]["value"]
            for section, key in rt_server.SECTION_TTL_KEY.items()}


# --------------------------------------------------------------------------
# In-memory HTTP, so the suite binds nothing
# --------------------------------------------------------------------------
class _Keep(io.BytesIO):
    """A response buffer that survives the handler's finish(), which closes
    wfile before the test can read it."""

    def close(self):
        pass


class _FakeSocket:
    """Enough socket for BaseHTTPRequestHandler and no more.

    `sendall` is the one that matters: since Python 3.6 an unbuffered wfile is a
    `socketserver._SocketWriter`, which writes THROUGH the socket rather than to
    the file object, so a fake that only implements makefile records nothing.
    """

    def __init__(self, rfile, wfile):
        self._rfile = rfile
        self._wfile = wfile

    def makefile(self, mode="rb", *_args, **_kwargs):
        return self._wfile if "w" in mode else self._rfile

    def sendall(self, data):
        self._wfile.write(data)

    def close(self):
        pass


class _FakeServer:
    server_address = ("127.0.0.1", 8787)


class Response:
    def __init__(self, raw):
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").splitlines()
        self.status = int(lines[0].split()[1])
        self.headers = {}
        for line in lines[1:]:
            key, _, val = line.partition(":")
            self.headers[key.strip().lower()] = val.strip()
        self.body = body

    @property
    def text(self):
        return self.body.decode("utf-8")

    def json(self):
        return json.loads(self.text)


def call(handler_cls, method, path, body=None, headers=None):
    """Drive one request through the handler with no socket and no port."""
    raw = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\n" % (method, path)
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    for key, val in (headers or {}).items():
        raw += "%s: %s\r\n" % (key, val)
    if body is not None:
        raw += "Content-Type: application/json\r\n"
        raw += "Content-Length: %d\r\n" % len(payload)
    raw += "\r\n"
    rfile = io.BytesIO(raw.encode("latin-1") + payload)
    wfile = _Keep()
    handler_cls(_FakeSocket(rfile, wfile), ("127.0.0.1", 51234), _FakeServer())
    return Response(wfile.getvalue())


def handler_for(snapshot=None, token=TOKEN, page=None, asset_roots=(),
                action_runner=None, catalogue=None, port=8787):
    return rt_server.make_handler(
        snapshot or (lambda: {"generated": NOW.isoformat()}),
        token, page, list(asset_roots), action_runner=action_runner,
        catalogue=catalogue, log=None,
        started=NOW.isoformat(timespec="seconds"), port=port)


# --------------------------------------------------------------------------
class LoopbackBind(unittest.TestCase):
    def test_loopback_is_accepted(self):
        self.assertEqual("127.0.0.1", rt_server.assert_loopback("127.0.0.1"))

    def test_all_interfaces_is_refused_before_a_socket_exists(self):
        with self.assertRaises(rt_server.ServerRefusal) as caught:
            rt_server.assert_loopback("0.0.0.0")
        self.assertIn("loopback", str(caught.exception))

    def test_a_routable_address_is_refused(self):
        with self.assertRaises(rt_server.ServerRefusal):
            rt_server.assert_loopback("10.0.0.7")

    def test_a_host_that_does_not_resolve_is_named(self):
        with self.assertRaises(rt_server.ServerRefusal) as caught:
            rt_server.assert_loopback("no-such-host.invalid")
        self.assertIn("no-such-host.invalid", str(caught.exception))


class Cache(unittest.TestCase):
    def setUp(self):
        self.calls = {"mirrors": 0, "services": 0}

        def mirrors(now):
            self.calls["mirrors"] += 1
            return {"status": "ok", "n": self.calls["mirrors"]}

        def services(now):
            self.calls["services"] += 1
            return {"status": "ok", "n": self.calls["services"]}

        self.builders = {"mirrors": mirrors, "services": services}
        self.ttls = {"mirrors": 15, "services": 60}
        self.cache = rt_server.SnapshotCache(self.builders, self.ttls)

    def test_a_section_inside_its_ttl_is_not_rebuilt(self):
        self.cache.snapshot(NOW)
        self.cache.snapshot(NOW + timedelta(seconds=5))
        self.assertEqual(1, self.calls["mirrors"])

    def test_a_section_past_its_ttl_is_rebuilt(self):
        self.cache.snapshot(NOW)
        self.cache.snapshot(NOW + timedelta(seconds=16))
        self.assertEqual(2, self.calls["mirrors"])

    def test_each_section_expires_on_its_own_timer(self):
        # The point of a per-section TTL: the cheap filesystem walk refreshes
        # while the expensive service probe does not.
        self.cache.snapshot(NOW)
        self.cache.snapshot(NOW + timedelta(seconds=20))
        self.assertEqual(2, self.calls["mirrors"])
        self.assertEqual(1, self.calls["services"])

    def test_every_section_carries_a_receipt_with_its_age(self):
        self.cache.snapshot(NOW)
        payload = self.cache.snapshot(NOW + timedelta(seconds=5))
        receipt = payload["receipts"]["mirrors"]
        self.assertEqual(5.0, receipt["age_seconds"])
        self.assertEqual(15, receipt["ttl_seconds"])
        self.assertIn("2026-08-31T09:00:00", receipt["collected_at"])

    def test_invalidate_forces_a_rebuild_so_an_action_is_judged_by_effect(self):
        self.cache.snapshot(NOW)
        self.cache.invalidate("mirrors")
        self.cache.snapshot(NOW + timedelta(seconds=1))
        self.assertEqual(2, self.calls["mirrors"])
        self.assertEqual(1, self.calls["services"])

    def test_a_missing_ttl_key_is_named_and_never_invented(self):
        cache = rt_server.SnapshotCache(self.builders, {"mirrors": 15})
        with self.assertRaises(KeyError) as caught:
            cache.snapshot(NOW)
        self.assertIn("ttl_seconds", str(caught.exception))

    def test_serving_never_blocks_on_a_section_never_collected(self):
        """Measured 2026-08-31 against the live server: the first
        `GET /api/state` did not return within 10 seconds, because the services
        section runs tier-1 `claude mcp list` against 28 servers under a
        45-second budget. A TTL cannot help the FIRST call, so the serving mode
        reports `collecting` and lets the next poll carry the answer."""
        spawned = []
        cache = rt_server.SnapshotCache(self.builders, self.ttls,
                                        spawn=spawned.append)
        payload = cache.snapshot(NOW, block=False)
        self.assertEqual("collecting", payload["mirrors"]["status"])
        self.assertIsNone(payload["receipts"]["mirrors"]["collected_at"])
        self.assertEqual(0, self.calls["mirrors"])
        self.assertEqual(2, len(spawned))

    def test_a_stale_section_is_served_with_its_real_age_not_withheld(self):
        spawned = []
        cache = rt_server.SnapshotCache(self.builders, self.ttls,
                                        spawn=spawned.append)
        cache.snapshot(NOW)                       # blocking: fills the cache
        payload = cache.snapshot(NOW + timedelta(seconds=99), block=False)
        self.assertEqual("ok", payload["mirrors"]["status"])
        self.assertEqual(99.0, payload["receipts"]["mirrors"]["age_seconds"])
        self.assertEqual("refreshing", payload["receipts"]["mirrors"]["state"])

    def test_a_refresh_already_running_is_not_spawned_twice(self):
        spawned = []
        cache = rt_server.SnapshotCache(self.builders, self.ttls,
                                        spawn=spawned.append)
        cache.snapshot(NOW, block=False)
        cache.snapshot(NOW + timedelta(seconds=1), block=False)
        self.assertEqual(2, len(spawned))         # one per section, not four

    def test_a_background_refresh_that_raises_lands_as_unavailable(self):
        def boom(_now):
            raise RuntimeError("mcp list exploded")
        spawned = []
        cache = rt_server.SnapshotCache({"mirrors": boom}, {"mirrors": 15},
                                        spawn=spawned.append)
        cache.snapshot(NOW, block=False)
        spawned[0]()                              # run the background work here
        payload = cache.snapshot(NOW + timedelta(seconds=1), block=False)
        self.assertEqual("unavailable", payload["mirrors"]["status"])
        self.assertIn("mcp list exploded", payload["mirrors"]["reason"])

    def test_warm_starts_every_section_at_once(self):
        spawned = []
        cache = rt_server.SnapshotCache(self.builders, self.ttls,
                                        spawn=spawned.append)
        cache.warm(NOW)
        self.assertEqual(2, len(spawned))
        for work in spawned:
            work()
        payload = cache.snapshot(NOW, block=False)
        self.assertEqual("ok", payload["services"]["status"])

    def test_the_envelope_is_carried_through(self):
        cache = rt_server.SnapshotCache(
            self.builders, self.ttls, envelope=lambda: {"repo": {"name": "rt"}})
        payload = cache.snapshot(NOW)
        self.assertEqual("rt", payload["repo"]["name"])
        self.assertEqual(NOW.isoformat(timespec="seconds"), payload["generated"])


class PortProbe(unittest.TestCase):
    def test_nothing_listening_is_free(self):
        def opener(*_a, **_k):
            raise OSError("refused")
        verdict, _ = rt_server.probe_port("127.0.0.1", 8787, 2, opener=opener,
                                          free_check=lambda h, p: True)
        self.assertEqual("free", verdict)

    def test_our_own_server_answering_ping_is_ours(self):
        verdict, detail = rt_server.probe_port(
            "127.0.0.1", 8787, 2,
            opener=_pinger({"app": rt_server.APP_ID, "pid": 4242}))
        self.assertEqual("ours", verdict)
        self.assertEqual(4242, detail["pid"])

    def test_another_http_server_answering_is_foreign_not_ours(self):
        verdict, detail = rt_server.probe_port(
            "127.0.0.1", 8787, 2, opener=_pinger({"app": "something-else"}))
        self.assertEqual("foreign", verdict)
        self.assertIn("not rt-observe", detail["reason"])

    def test_a_bound_port_that_does_not_answer_is_foreign_with_the_reason(self):
        def opener(*_a, **_k):
            raise OSError("connection reset")
        verdict, detail = rt_server.probe_port("127.0.0.1", 8787, 2,
                                               opener=opener,
                                               free_check=lambda h, p: False)
        self.assertEqual("foreign", verdict)
        self.assertIn("in use", detail["reason"])


def _pinger(payload):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    return lambda *_a, **_k: _Resp()


class Decision(unittest.TestCase):
    def _decide(self, verdict, detail=None, pid=("4242", None)):
        return rt_server.start_decision(
            "127.0.0.1", 8787, 2, 20,
            opener=(_pinger(detail) if verdict == "ours" or detail
                    else _raiser()),
            free_check=lambda h, p: verdict == "free",
            pid_lookup=lambda port, timeout: pid)

    def test_a_free_port_means_serve(self):
        decision = self._decide("free")
        self.assertEqual("serve", decision["action"])
        self.assertEqual("http://127.0.0.1:8787/", decision["url"])

    def test_our_own_server_is_reported_running_never_started_twice(self):
        decision = self._decide("ours", {"app": rt_server.APP_ID, "pid": 99})
        self.assertEqual("already-running", decision["action"])
        self.assertEqual(99, decision["pid"])
        self.assertEqual("http://127.0.0.1:8787/", decision["url"])

    def test_a_foreign_holder_is_refused_and_its_pid_named(self):
        decision = self._decide("held")
        self.assertEqual("refuse", decision["action"])
        self.assertEqual("4242", decision["pid"])
        self.assertIn("in use", decision["reason"])

    def test_a_foreign_holder_whose_pid_is_unknown_says_why(self):
        decision = self._decide("held", pid=(None, "no netstat on PATH"))
        self.assertEqual("refuse", decision["action"])
        self.assertIsNone(decision["pid"])
        self.assertIn("netstat", decision["pid_unavailable"])


def _raiser():
    def opener(*_a, **_k):
        raise OSError("refused")
    return opener


class HoldingPid(unittest.TestCase):
    def test_with_no_tool_on_path_the_reason_names_all_three(self):
        with mock.patch.object(rt_server.shutil, "which", return_value=None):
            pid, why = rt_server.holding_pid(8787, 5)
        self.assertIsNone(pid)
        for tool in ("netstat", "ss", "lsof"):
            self.assertIn(tool, why)

    def test_a_netstat_listener_line_yields_the_pid(self):
        out = ("  Proto  Local Address    Foreign Address    State\n"
               "  TCP    127.0.0.1:8787   0.0.0.0:0          LISTENING  13337\n")
        with mock.patch.object(rt_server.shutil, "which",
                              side_effect=lambda n: "netstat" if n == "netstat"
                              else None), \
             mock.patch.object(rt_server.subprocess, "run",
                               return_value=mock.Mock(stdout=out)):
            pid, why = rt_server.holding_pid(8787, 5)
        self.assertEqual("13337", pid)
        self.assertIsNone(why)

    def test_a_tool_that_reports_no_listener_says_so_rather_than_guessing(self):
        with mock.patch.object(rt_server.shutil, "which",
                              side_effect=lambda n: "netstat" if n == "netstat"
                              else None), \
             mock.patch.object(rt_server.subprocess, "run",
                               return_value=mock.Mock(stdout="")):
            pid, why = rt_server.holding_pid(8787, 5)
        self.assertIsNone(pid)
        self.assertIn("no listener", why)

    def test_the_output_is_decoded_with_replacement_not_strictly(self):
        """Measured 2026-08-31 on this machine: French Windows netstat emits
        byte 0x90 in its header, the default cp1252 decode raised
        UnicodeDecodeError inside subprocess's reader THREAD, and stdout came
        back empty. holding_pid then answered "netstat ran but reported no
        listener" while the port was held and the pid was in that output - a
        wrong answer that reads exactly like a right one."""
        with mock.patch.object(rt_server.shutil, "which",
                              side_effect=lambda n: "netstat" if n == "netstat"
                              else None), \
             mock.patch.object(rt_server.subprocess, "run",
                               return_value=mock.Mock(stdout="")) as run:
            rt_server.holding_pid(8787, 5)
        self.assertEqual("replace", run.call_args.kwargs["errors"])

    def test_the_subprocess_call_carries_an_explicit_timeout(self):
        with mock.patch.object(rt_server.shutil, "which",
                              side_effect=lambda n: "netstat" if n == "netstat"
                              else None), \
             mock.patch.object(rt_server.subprocess, "run",
                               return_value=mock.Mock(stdout="")) as run:
            rt_server.holding_pid(8787, 7)
        self.assertEqual(7, run.call_args.kwargs["timeout"])


class GetRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_the_page_absent_is_stated_with_the_path_it_looked_for(self):
        missing = self.root / "assets" / "rt_state.html"
        response = call(handler_for(page=missing), "GET", "/")
        self.assertEqual(503, response.status)
        self.assertIn("not been built yet", response.text)
        self.assertIn("rt_state.html", response.text)
        self.assertIn("/api/state", response.text)

    def test_the_page_is_served_with_the_token_substituted(self):
        page = self.root / "rt_state.html"
        page.write_text("<p>%s</p>" % rt_server.TOKEN_PLACEHOLDER,
                        encoding="utf-8")
        response = call(handler_for(page=page), "GET", "/")
        self.assertEqual(200, response.status)
        self.assertIn(TOKEN, response.text)
        self.assertNotIn(rt_server.TOKEN_PLACEHOLDER, response.text)

    def test_ping_identifies_this_app_so_the_launcher_can_recognise_it(self):
        response = call(handler_for(), "GET", "/api/ping")
        self.assertEqual(200, response.status)
        self.assertEqual(rt_server.APP_ID, response.json()["app"])

    def test_state_returns_the_snapshot(self):
        payload = {"generated": "x", "mirrors": {"status": "ok"}}
        response = call(handler_for(snapshot=lambda: payload),
                        "GET", "/api/state")
        self.assertEqual(200, response.status)
        self.assertEqual("ok", response.json()["mirrors"]["status"])

    def test_a_snapshot_that_raises_is_stated_never_blanked(self):
        def boom():
            raise RuntimeError("collector exploded")
        response = call(handler_for(snapshot=boom), "GET", "/api/state")
        self.assertEqual(500, response.status)
        self.assertEqual("unavailable", response.json()["status"])
        self.assertIn("collector exploded", response.json()["reason"])

    def test_an_unknown_route_is_a_json_404_naming_the_path(self):
        response = call(handler_for(), "GET", "/nope")
        self.assertEqual(404, response.status)
        self.assertIn("/nope", response.json()["reason"])

    def test_no_cors_header_is_ever_emitted(self):
        # Another origin may SEND a request; it must never be able to read the
        # answer, which is what keeps the token unknown to it.
        response = call(handler_for(), "GET", "/api/ping")
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_an_asset_is_served_from_an_asset_root(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "rt-tokens.css").write_text(":root{--a:1}", encoding="utf-8")
        response = call(handler_for(asset_roots=[assets]),
                        "GET", "/assets/rt-tokens.css")
        self.assertEqual(200, response.status)
        self.assertIn("--a:1", response.text)
        self.assertIn("text/css", response.headers["content-type"])

    def test_an_asset_name_that_walks_out_of_the_root_is_refused(self):
        assets = self.root / "assets"
        assets.mkdir()
        (self.root / "secret.css").write_text("x", encoding="utf-8")
        response = call(handler_for(asset_roots=[assets]),
                        "GET", "/assets/..%2Fsecret.css")
        self.assertEqual(404, response.status)

    def test_an_unserved_asset_type_is_refused_with_the_reason(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "notes.txt").write_text("x", encoding="utf-8")
        response = call(handler_for(asset_roots=[assets]),
                        "GET", "/assets/notes.txt")
        self.assertEqual(404, response.status)
        self.assertIn(".txt", response.json()["reason"])


class ActionRoute(unittest.TestCase):
    def test_no_token_is_refused_and_says_where_the_token_comes_from(self):
        response = call(handler_for(), "POST", "/api/action", body={"id": "x"})
        self.assertEqual(403, response.status)
        self.assertIn("session token", response.json()["reason"])

    def test_a_wrong_token_is_refused(self):
        response = call(handler_for(), "POST", "/api/action",
                        body={"id": "x", "token": "guess"})
        self.assertEqual(403, response.status)
        self.assertIn("invalid", response.json()["reason"])

    def test_with_no_runner_installed_the_route_says_so_rather_than_500(self):
        response = call(handler_for(), "POST", "/api/action",
                        body={"id": "x", "token": TOKEN})
        self.assertEqual(501, response.status)
        self.assertEqual("unavailable", response.json()["status"])

    def test_a_valid_call_reaches_the_runner(self):
        # The negative control for every refusal above: with the right token and
        # a runner installed the call must actually go through, or the gate is
        # refusing everything and proving nothing.
        seen = {}

        def runner(body):
            seen.update(body)
            return {"status": "ok", "id": body["id"]}

        response = call(handler_for(action_runner=runner), "POST",
                        "/api/action", body={"id": "check", "token": TOKEN})
        self.assertEqual(200, response.status)
        self.assertEqual("check", response.json()["id"])
        self.assertEqual("check", seen["id"])

    def test_a_refused_call_never_reaches_the_runner(self):
        """The gate is only a gate if the thing behind it is not touched. A
        runner that ran and was then refused would have already done the work."""
        calls = []
        runner = handler_for(action_runner=lambda body: calls.append(body))
        for body, headers in (({"id": "x"}, None),
                              ({"id": "x", "token": "guess"}, None),
                              ({"id": "x", "token": TOKEN},
                               {"Origin": "https://evil.example"})):
            with self.subTest(body=body, headers=headers):
                response = call(runner, "POST", "/api/action", body=body,
                                headers=headers)
                self.assertEqual(403, response.status)
        self.assertEqual([], calls)

    def test_a_runner_that_raises_is_stated_not_swallowed(self):
        def runner(_body):
            raise RuntimeError("install.ps1 vanished")
        response = call(handler_for(action_runner=runner), "POST",
                        "/api/action", body={"id": "x", "token": TOKEN})
        self.assertEqual(500, response.status)
        self.assertIn("install.ps1 vanished", response.json()["reason"])

    def test_a_body_that_is_not_a_json_object_is_refused(self):
        response = call(handler_for(), "POST", "/api/action", body=["not", "a"])
        self.assertEqual(400, response.status)

    def test_a_cross_origin_post_is_refused_before_the_token_is_read(self):
        response = call(handler_for(), "POST", "/api/action",
                        body={"id": "x", "token": TOKEN},
                        headers={"Origin": "https://evil.example"})
        self.assertEqual(403, response.status)
        self.assertIn("cross-origin", response.json()["reason"])

    def test_our_own_origin_is_accepted(self):
        response = call(handler_for(action_runner=lambda b: {"status": "ok"}),
                        "POST", "/api/action",
                        body={"id": "x", "token": TOKEN},
                        headers={"Origin": "http://127.0.0.1:8787"})
        self.assertEqual(200, response.status)

    def test_posting_to_another_path_is_a_404(self):
        response = call(handler_for(), "POST", "/api/state",
                        body={"token": TOKEN})
        self.assertEqual(404, response.status)

    def test_a_refused_post_leaves_the_connection_aligned(self):
        """The negative control for a defect this suite found on 2026-08-31.

        The connection is keep-alive. Refusing a POST without consuming its body
        left those bytes to be read as the NEXT request line, so every later
        answer on the connection was misaligned - the refusal itself looked
        correct and the request after it did not. Two requests on one connection
        is the only shape that shows it.
        """
        first = ("POST /api/action HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                 "Origin: https://evil.example\r\n"
                 "Content-Type: application/json\r\n")
        payload = json.dumps({"id": "x", "token": TOKEN}).encode("utf-8")
        first += "Content-Length: %d\r\n\r\n" % len(payload)
        second = "GET /api/ping HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        rfile = io.BytesIO(first.encode("latin-1") + payload
                           + second.encode("latin-1"))
        wfile = _Keep()
        handler_for()(_FakeSocket(rfile, wfile), ("127.0.0.1", 51234),
                      _FakeServer())
        raw = wfile.getvalue()
        statuses = [int(part.split(b"\r\n", 1)[0].split()[0])
                    for part in raw.split(b"HTTP/1.1 ")[1:]]
        self.assertEqual([403, 200], statuses)
        self.assertIn(b'"app": "rt-observe"', raw)


class ActionCatalogue(unittest.TestCase):
    """GET /api/actions: what the page may offer as a button. It carries no
    secret - it names scripts, never the token - which is why it is a GET."""

    def test_the_catalogue_is_served(self):
        entries = [{"id": "tests.offline", "label": "Run the offline suite",
                    "available": True}]
        response = call(handler_for(catalogue=lambda: entries),
                        "GET", "/api/actions")
        self.assertEqual(200, response.status)
        self.assertEqual(entries, response.json()["actions"])

    def test_with_no_whitelist_the_page_is_told_so_rather_than_shown_nothing(self):
        """An empty list would render as 'no actions exist'. 501 with a reason
        renders as 'this server offers none, and here is why' (R8)."""
        response = call(handler_for(), "GET", "/api/actions")
        self.assertEqual(501, response.status)
        self.assertIn("no action whitelist", response.json()["reason"])

    def test_a_catalogue_that_raises_costs_its_own_route_only(self):
        def boom():
            raise RuntimeError("actions.json vanished")
        response = call(handler_for(catalogue=boom), "GET", "/api/actions")
        self.assertEqual(500, response.status)
        self.assertIn("actions.json vanished", response.json()["reason"])

    def test_the_catalogue_route_never_carries_the_session_token(self):
        entries = [{"id": "x", "label": "x", "available": True}]
        response = call(handler_for(catalogue=lambda: entries),
                        "GET", "/api/actions")
        self.assertNotIn(TOKEN, response.text)


class ServeCommand(unittest.TestCase):
    def _args(self, **over):
        base = dict(serve=True, dry_run=False, open=False, port=None,
                    repo_root=None, home=None, json=False)
        base.update(over)
        return type("Args", (), base)()

    def test_dry_run_starts_nothing_and_names_what_it_would_do(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rt_server, "build_server") as build:
            code = rt_state.serve(
                self._args(dry_run=True), fixture_config(), out=out, err=err,
                clock=lambda: NOW,
                decide=lambda *a: {"action": "serve", "port": 8787,
                                   "host": "127.0.0.1",
                                   "url": "http://127.0.0.1:8787/"})
        self.assertEqual(0, code)
        build.assert_not_called()
        self.assertIn("started       nothing", out.getvalue())
        self.assertIn("127.0.0.1:8787", out.getvalue())

    def test_dry_run_returns_the_code_the_real_run_would(self):
        out, err = io.StringIO(), io.StringIO()
        code = rt_state.serve(
            self._args(dry_run=True), fixture_config(), out=out, err=err,
            clock=lambda: NOW,
            decide=lambda *a: {"action": "refuse", "port": 8787,
                               "host": "127.0.0.1", "pid": "4242",
                               "url": "http://127.0.0.1:8787/",
                               "reason": "port 8787 is in use"})
        self.assertEqual(1, code)
        self.assertIn("refusal", out.getvalue())

    def test_an_already_running_server_is_reported_with_its_url(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rt_server, "build_server") as build:
            code = rt_state.serve(
                self._args(), fixture_config(), out=out, err=err,
                clock=lambda: NOW,
                decide=lambda *a: {"action": "already-running", "pid": 99,
                                   "started": "2026-08-31T08:00:00",
                                   "port": 8787, "host": "127.0.0.1",
                                   "url": "http://127.0.0.1:8787/"})
        self.assertEqual(0, code)
        build.assert_not_called()
        self.assertIn("already running", out.getvalue())
        self.assertIn("http://127.0.0.1:8787/", out.getvalue())

    def test_a_held_port_is_refused_with_its_pid_and_never_rebound(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rt_server, "build_server") as build:
            code = rt_state.serve(
                self._args(), fixture_config(), out=out, err=err,
                clock=lambda: NOW,
                decide=lambda *a: {"action": "refuse", "pid": "4242",
                                   "port": 8787, "host": "127.0.0.1",
                                   "url": "http://127.0.0.1:8787/",
                                   "reason": "port 8787 is in use"})
        self.assertEqual(1, code)
        build.assert_not_called()
        self.assertIn("4242", err.getvalue())
        self.assertIn("two snapshots", err.getvalue())

    def test_a_non_loopback_bind_host_is_a_refusal_by_design(self):
        out, err = io.StringIO(), io.StringIO()
        code = rt_state.serve(
            self._args(), fixture_config(bind_host="0.0.0.0"), out=out, err=err,
            clock=lambda: NOW,
            decide=lambda *a: {"action": "serve", "port": 8787,
                               "host": "0.0.0.0",
                               "url": "http://0.0.0.0:8787/"})
        self.assertEqual(2, code)
        self.assertIn("loopback", err.getvalue())

    def test_the_serving_path_prints_the_token_and_the_state_url(self):
        out, err = io.StringIO(), io.StringIO()
        httpd = mock.Mock()
        httpd.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(rt_server, "build_server", return_value=httpd), \
             mock.patch.object(rt_state, "section_builders", return_value={}):
            code = rt_state.serve(
                self._args(), fixture_config(), out=out, err=err,
                clock=lambda: NOW,
                decide=lambda *a: {"action": "serve", "port": 8787,
                                   "host": "127.0.0.1",
                                   "url": "http://127.0.0.1:8787/"})
        self.assertEqual(0, code)
        self.assertIn("session token", out.getvalue())
        self.assertIn("api/state", out.getvalue())
        httpd.server_close.assert_called_once()

    def test_open_is_not_honoured_by_a_dry_run(self):
        out, err = io.StringIO(), io.StringIO()
        browse = mock.Mock()
        rt_state.serve(self._args(dry_run=True, open=True), fixture_config(),
                       out=out, err=err, clock=lambda: NOW, browse=browse,
                       decide=lambda *a: {"action": "serve", "port": 8787,
                                          "host": "127.0.0.1",
                                          "url": "http://127.0.0.1:8787/"})
        browse.assert_not_called()
        self.assertIn("would open", out.getvalue())

    def test_a_port_taken_between_the_probe_and_the_bind_is_reported(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rt_server, "build_server",
                               side_effect=OSError("address in use")), \
             mock.patch.object(rt_state, "section_builders", return_value={}):
            code = rt_state.serve(
                self._args(), fixture_config(), out=out, err=err,
                clock=lambda: NOW,
                decide=lambda *a: {"action": "serve", "port": 8787,
                                   "host": "127.0.0.1",
                                   "url": "http://127.0.0.1:8787/"})
        self.assertEqual(1, code)
        self.assertIn("could not bind", err.getvalue())


class SectionBuilders(unittest.TestCase):
    """The server's cache calls these one at a time on their own timers, so each
    must degrade on its own exactly as the one-shot dump does."""

    def test_every_ttl_the_cache_needs_is_declared_by_the_shipped_config(self):
        config = rt_state.load_config()
        for section, key in rt_server.SECTION_TTL_KEY.items():
            with self.subTest(section=section):
                self.assertIsInstance(
                    rt_state.config_value(config, "ttl_seconds", key),
                    int, "ttl_seconds.%s missing for section %s" % (key, section))
        self.assertIsInstance(
            rt_state.config_value(config, "timeouts_seconds", "ping"), int)

    def test_the_fixture_config_declares_everything_serve_reads(self):
        """The fixture is a stand-in for the shipped config, and a stand-in that
        drifts is worse than none. Measured 2026-08-31: a `view` block was added
        to observe-config.json, the fixture did not learn it, and the one serve
        case that does NOT patch build_server died on a ConfigError instead of
        testing its refusal. Every path serve() reads is checked against both
        files here, so the next added key fails on this line rather than on a
        case that looks unrelated."""
        shipped = rt_state.load_config()
        fixture = fixture_config()
        paths = [("server", "bind_host"), ("server", "port"),
                 ("server", "token_bytes"), ("timeouts_seconds", "ping"),
                 ("timeouts_seconds", "subprocess_default"),
                 ("timeouts_seconds", "action_default"),
                 ("paths", "action_log"), ("paths", "inbox_root"),
                 ("caps", "inbox_message_chars"),
                 ("caps", "output_tail_chars"),
                 ("view", "poll_ms")]
        paths += [("ttl_seconds", key)
                  for key in rt_server.SECTION_TTL_KEY.values()]
        for path in paths:
            with self.subTest(path=".".join(path)):
                rt_state.config_value(shipped, *path)
                rt_state.config_value(fixture, *path)
        for key in rt_state.view_config(shipped)["canvas"]:
            with self.subTest(canvas=key):
                rt_state.config_value(fixture, "view", "canvas", key)

    def test_every_declared_ttl_is_consumed_by_a_section(self):
        """The direction the other TTL test cannot see. Measured 2026-08-31:
        ttl_seconds.mcp_live was declared at 300s with its own provenance and
        consumed by NOTHING - MCP rode the services section's 60s timer, so
        `claude mcp list` reached 28 servers over the network five times more
        often than the configuration said it would. A key that looks configured
        and does nothing is exactly the failure class this repository keeps
        legislating against, and only a check in this direction catches it."""
        config = rt_state.load_config()
        declared = set(config["ttl_seconds"])
        consumed = set(rt_server.SECTION_TTL_KEY.values())
        self.assertEqual(
            set(), declared - consumed,
            "observe-config.json declares ttl_seconds no section reads: %s"
            % sorted(declared - consumed))

    def test_mcp_is_its_own_section_on_its_own_long_timer(self):
        """The split itself: the one collector that leaves the machine must not
        share a timer with the two local daemon probes."""
        config = rt_state.load_config()
        self.assertEqual("mcp_live", rt_server.SECTION_TTL_KEY["mcp"])
        mcp_ttl = rt_state.config_value(config, "ttl_seconds", "mcp_live")
        services_ttl = rt_state.config_value(config, "ttl_seconds", "services")
        self.assertGreater(mcp_ttl, services_ttl)

    def test_the_section_set_matches_the_ttl_table(self):
        # A section with no TTL entry would raise on the first page poll, which
        # is a failure the one-shot dump would never show.
        builders = rt_state.section_builders(config=fixture_config())
        self.assertEqual(set(rt_server.SECTION_TTL_KEY), set(builders))

    def test_one_failing_collector_costs_only_its_own_section(self):
        builders = rt_state.section_builders(config=fixture_config())
        with mock.patch.object(rt_state.collect_registry, "collect",
                               side_effect=RuntimeError("frontmatter exploded")):
            registry = builders["registry"](NOW)
        self.assertEqual("unavailable", registry["status"])
        self.assertIn("frontmatter exploded", registry["reason"])

    def test_a_missing_policy_is_stated_by_the_mirror_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            builders = rt_state.section_builders(
                repo_root=tmp, home=tmp, config=fixture_config())
            mirrors = builders["mirrors"](NOW)
        self.assertEqual("unavailable", mirrors["status"])
        self.assertIn("mirror-policy.json", mirrors["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
