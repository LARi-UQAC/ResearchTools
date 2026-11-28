"""
test_augure_models - offline tests of scripts/local/augure/augure_models.py (Issue #112, plan 2).

Offline: a fake opener replaces the network, the key is a fictitious string (R21, R34), and every
config fixture lives in a temporary folder. The real home folder is never written: the
`~/.claude` containment tests patch Path.home.

Why it exists: the AugureAI route lists its models live from an MCP server and must refuse, never
guess, when a model has no measured window, a key is missing, or the server answers an error. Each
refusal below is proven able to fail (R20), since a check that cannot fail proves nothing.
"""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "scripts" / "local" / "augure" / "augure_models.py"
DATA_DIR = MODULE.parent

FAKE_KEY = "FAKEKEY-TEST-0123456789"
ENV = {"AUGURE_MCP_KEY": FAKE_KEY}


def load_module():
    """Load augure_models.py by path (it is not on any import path)."""
    spec = importlib.util.spec_from_file_location("augure_models", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AM = load_module()


class FakeResponse:
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, body, headers=None):
        self._body = body
        self.headers = dict(headers or {})

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Records every request and answers from a queue; an exception in the queue is raised."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, req, timeout=None):
        headers = {k.lower(): v for k, v in req.header_items()}
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        self.calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": headers,
            "body": body,
            "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError("unexpected extra request to the fake opener")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        body_bytes, hdrs = item
        return FakeResponse(body_bytes, hdrs)


def sse(obj):
    """An MCP answer as the real server sends it: an SSE event carrying the JSON-RPC object."""
    return ("event: message\ndata: " + json.dumps(obj) + "\n\n").encode("utf-8")


def list_result(ids, rpc_id=3):
    """A successful tools/call answer for list_models, shaped as measured on 2026-11-27."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [{"type": "text", "text": "\n".join(ids)}],
            "structuredContent": {
                "models": [{"id": i, "reasoning_efforts": ["low", "medium", "high"]} for i in ids],
                "default": ids[0] if ids else None,
            },
        },
    }


def list_responses(ids, session=None):
    """The three answers of one list_models run: initialize, notification, tools/call."""
    init_headers = {"Mcp-Session-Id": session} if session else {}
    return [
        (sse({"jsonrpc": "2.0", "id": 1, "result": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "augure"}}}),
         init_headers),
        (b"", {}),
        (sse(list_result(ids)), {}),
    ]


def copy_data_dir(tmp, edit_models=None, edit_settings=None):
    """Copy the three real data files into tmp, optionally editing their loaded dicts first."""
    tmp = Path(tmp)
    for name in ("augure-settings.json", "augure-models.json", "augure-profiles.json"):
        shutil.copy(DATA_DIR / name, tmp / name)
    if edit_models:
        path = tmp / "augure-models.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        edit_models(data)
        path.write_text(json.dumps(data), encoding="utf-8")
    if edit_settings:
        path = tmp / "augure-settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        edit_settings(data)
        path.write_text(json.dumps(data), encoding="utf-8")
    return tmp


def run_main(argv, environ=None, opener=None, data_dir=None):
    """Run the CLI and capture (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = AM.main(argv, environ=ENV if environ is None else environ,
                       opener=opener, data_dir=data_dir)
    return code, out.getvalue(), err.getvalue()


class TestMcpParsing(unittest.TestCase):
    """The MCP answer comes as SSE on the real server; a plain JSON body must also work."""

    def test_sse_body_parsed(self):
        text = 'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"x":1}}\n\n'
        obj = AM.parse_mcp_body(text)
        self.assertEqual(obj["result"], {"x": 1})

    def test_plain_json_body_parsed(self):
        obj = AM.parse_mcp_body('{"jsonrpc":"2.0","id":3,"result":{"x":2}}')
        self.assertEqual(obj["result"], {"x": 2})

    def test_unparsable_body_is_mcp_error(self):
        with self.assertRaises(AM.McpError):
            AM.parse_mcp_body("<html>502 Bad Gateway</html>")

    def test_empty_body_is_mcp_error(self):
        with self.assertRaises(AM.McpError):
            AM.parse_mcp_body("")

    def test_rpc_error_is_mcp_error(self):
        responses = list_responses([])[:2] + [
            (sse({"jsonrpc": "2.0", "id": 3, "error": {"code": -32602, "message": "bad args"}}), {}),
        ]
        with self.assertRaises(AM.McpError):
            AM.list_models("dev", ENV, opener=FakeOpener(responses))

    def test_is_error_result_is_mcp_error(self):
        responses = list_responses([])[:2] + [
            (sse({"jsonrpc": "2.0", "id": 3, "result": {
                "isError": True, "content": [{"type": "text", "text": "quota exhausted"}]}}), {}),
        ]
        with self.assertRaises(AM.McpError):
            AM.list_models("dev", ENV, opener=FakeOpener(responses))

    def test_rpc_error_exit_1_not_empty_list(self):
        responses = list_responses([])[:2] + [
            (sse({"jsonrpc": "2.0", "id": 3, "error": {"code": -1, "message": "down"}}), {}),
        ]
        code, out, _ = run_main(["list", "--profile", "dev", "--json"], opener=FakeOpener(responses))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")


class TestMcpHandshake(unittest.TestCase):
    """Request shape: initialize, the notification, then tools/call, with the bearer key."""

    def test_handshake_sequence_and_headers(self):
        opener = FakeOpener(list_responses(["rosedale-1"], session="sess-42"))
        AM.list_models("dev", ENV, opener=opener)
        self.assertEqual(len(opener.calls), 3)
        init, notif, call = opener.calls
        self.assertEqual(init["body"]["method"], "initialize")
        self.assertEqual(init["body"]["params"]["protocolVersion"], "2025-06-18")
        self.assertNotIn("mcp-session-id", init["headers"])
        self.assertEqual(notif["body"]["method"], "notifications/initialized")
        self.assertNotIn("id", notif["body"])
        self.assertEqual(call["body"]["method"], "tools/call")
        self.assertEqual(call["body"]["params"]["name"], "list_models")
        self.assertEqual(call["headers"]["mcp-session-id"], "sess-42")
        for c in opener.calls:
            self.assertEqual(c["headers"]["authorization"], "Bearer " + FAKE_KEY)
            self.assertIn("text/event-stream", c["headers"]["accept"])
            self.assertEqual(c["headers"]["content-type"], "application/json")
            self.assertEqual(c["url"], "https://mcp.augureai.ca/mcp")
            self.assertEqual(c["timeout"], 20)

    def test_http_error_is_mcp_error_without_body(self):
        err = urllib.error.HTTPError("https://mcp.augureai.ca/mcp", 401, "Unauthorized",
                                     {}, io.BytesIO(b"echo " + FAKE_KEY.encode()))
        with self.assertRaises(AM.McpError) as ctx:
            AM.list_models("dev", ENV, opener=FakeOpener([err]))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))


class TestSelection(unittest.TestCase):
    """Window filter against the real data files (rosedale-1 1048576, ossington-5 262144)."""

    def test_rosedale_selectable_with_1048576(self):
        result = AM.list_models("dev", ENV, opener=FakeOpener(list_responses(["rosedale-1"])))
        self.assertEqual(result["selectable"], [{"id": "rosedale-1", "context_window": 1048576}])
        self.assertEqual(result["refused"], [])
        self.assertEqual(result["profile"], "dev")

    def test_window_below_required_refused(self):
        result = AM.list_models("dev", ENV, opener=FakeOpener(list_responses(["ossington-5"])))
        self.assertEqual(result["selectable"], [])
        self.assertEqual(result["refused"][0]["id"], "ossington-5")
        reason = result["refused"][0]["reason"]
        self.assertIn("262144", reason)
        self.assertIn("1048576", reason)

    def test_model_without_window_refused(self):
        result = AM.list_models("dev", ENV, opener=FakeOpener(list_responses(["tofino-9", "rosedale-1"])))
        self.assertEqual([s["id"] for s in result["selectable"]], ["rosedale-1"])
        refused = {r["id"]: r["reason"] for r in result["refused"]}
        self.assertIn("augure-models.json", refused["tofino-9"])

    def test_empty_selectable_exit_2(self):
        code, _, err = run_main(["list", "--profile", "dev"],
                                opener=FakeOpener(list_responses(["ossington-5"])))
        self.assertEqual(code, 2)
        self.assertIn("selectable", err)

    def test_unknown_profile_exit_2(self):
        opener = FakeOpener([])
        code, _, _ = run_main(["list", "--profile", "nope"], opener=opener)
        self.assertEqual(code, 2)
        self.assertEqual(opener.calls, [])

    def test_list_cli_json_success(self):
        code, out, _ = run_main(["list", "--profile", "chat", "--json"],
                                opener=FakeOpener(list_responses(["rosedale-1", "ossington-5"])))
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["profile"], "chat")
        self.assertEqual([s["id"] for s in report["selectable"]], ["rosedale-1"])
        self.assertEqual(report["refused"][0]["id"], "ossington-5")


class TestKeyHandling(unittest.TestCase):
    """The key comes only from the environment and never reaches an output or an error text."""

    def test_missing_key_var_refused_exit_2(self):
        opener = FakeOpener([])
        code, out, err = run_main(["list", "--profile", "dev", "--json"], environ={}, opener=opener)
        self.assertEqual(code, 2)
        self.assertIn("AUGURE_MCP_KEY", err)
        self.assertEqual(opener.calls, [])

    def test_empty_key_var_refused_exit_2(self):
        opener = FakeOpener([])
        code, _, err = run_main(["list", "--profile", "dev"], environ={"AUGURE_MCP_KEY": ""},
                                opener=opener)
        self.assertEqual(code, 2)
        self.assertIn("AUGURE_MCP_KEY", err)
        self.assertEqual(opener.calls, [])

    def test_key_never_in_output_or_error(self):
        # The server reflects the key inside its own error text: the key must still not leak.
        reflected = (sse({"jsonrpc": "2.0", "id": 3,
                          "error": {"code": -32000, "message": "bad key " + FAKE_KEY}}), {})
        cases = {
            "success": list_responses(["rosedale-1"]),
            "rpc_error": list_responses([])[:2] + [reflected],
            "http_error": [urllib.error.HTTPError("https://x", 401, "no", {},
                                                  io.BytesIO(FAKE_KEY.encode()))],
        }
        for name, responses in cases.items():
            with self.subTest(case=name):
                code, out, err = run_main(["list", "--profile", "dev", "--json"],
                                          opener=FakeOpener(responses))
                self.assertNotIn(FAKE_KEY, out)
                self.assertNotIn(FAKE_KEY, err)
        with self.assertRaises(AM.McpError) as ctx:
            AM.list_models("dev", ENV, opener=FakeOpener(cases["rpc_error"]))
        self.assertNotIn(FAKE_KEY, str(ctx.exception))


class TestConfigValidation(unittest.TestCase):
    """Every number and name comes from the data files, and a bad one is a named ConfigError."""

    def test_bad_window_config_error(self):
        for bad in ("1048576", 0, -5, True, 1.5):
            with self.subTest(value=bad):
                with tempfile.TemporaryDirectory() as tmp:
                    d = copy_data_dir(tmp, edit_models=lambda m, b=bad: m["models"]["rosedale-1"]
                                      .__setitem__("context_window", {"unit": "tokens", "value": b,
                                                                      "provenance": "test"}))
                    with self.assertRaises(AM.ConfigError):
                        AM.load_models(d / "augure-models.json")

    def test_missing_settings_key_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = copy_data_dir(tmp, edit_settings=lambda s: s.pop("mcp_url"))
            with self.assertRaises(AM.ConfigError) as ctx:
                AM.load_settings(d / "augure-settings.json")
            self.assertIn("mcp_url", str(ctx.exception))
            self.assertIn("augure-settings.json", str(ctx.exception))

    def test_real_data_files_load(self):
        settings = AM.load_settings(DATA_DIR / "augure-settings.json")
        models = AM.load_models(DATA_DIR / "augure-models.json")
        profiles = AM.load_profiles(DATA_DIR / "augure-profiles.json")
        self.assertEqual(settings["mcp_url"]["value"], "https://mcp.augureai.ca/mcp")
        self.assertEqual(models["required_window"]["value"], 1048576)
        self.assertIn("dev", profiles["profiles"])

    def test_unknown_profile_in_list_models_is_config_error(self):
        with self.assertRaises(AM.ConfigError):
            AM.list_models("nope", ENV, opener=FakeOpener([]))


class TestRenderConfig(unittest.TestCase):
    """The LiteLLM config: one wildcard per profile, master key by reference only."""

    def setUp(self):
        self.settings = AM.load_settings(DATA_DIR / "augure-settings.json")
        self.profiles = AM.load_profiles(DATA_DIR / "augure-profiles.json")

    def test_render_config_one_wildcard_per_profile(self):
        cfg = AM.render_config(self.profiles, self.settings)
        names = [entry["model_name"] for entry in cfg["model_list"]]
        self.assertEqual(names, ["augure-dev/*", "augure-chat/*"])
        for entry in cfg["model_list"]:
            params = entry["litellm_params"]
            self.assertEqual(params["model"], "hosted_vllm/*")
            self.assertEqual(params["api_base"], "https://api.augureai.ca/v1")
            self.assertEqual(params["api_key"], "os.environ/AUGUREAI_API_KEY")
        self.assertEqual(cfg["general_settings"]["master_key"], "os.environ/LITELLM_MASTER_KEY")

    def test_render_config_provider_read_from_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = copy_data_dir(tmp, edit_settings=lambda s: s.__setitem__(
                "litellm_provider", {"value": "other_provider", "provenance": "test"}))
            settings = AM.load_settings(d / "augure-settings.json")
            cfg = AM.render_config(self.profiles, settings)
            for entry in cfg["model_list"]:
                self.assertEqual(entry["litellm_params"]["model"], "other_provider/*")

    def test_render_config_missing_provider_names_key(self):
        settings = dict(self.settings)
        settings.pop("litellm_provider")
        with self.assertRaises(AM.ConfigError) as ctx:
            AM.render_config(self.profiles, settings)
        self.assertIn("litellm_provider", str(ctx.exception))
        self.assertIn("augure-settings.json", str(ctx.exception))

    def test_render_config_carries_no_key_value(self):
        cfg = AM.render_config(self.profiles, self.settings)
        self.assertNotIn(FAKE_KEY, json.dumps(cfg))


class TestRenderOut(unittest.TestCase):
    """render-config --out: contained under ~/.claude, atomic, and dry run writes nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.patch = mock.patch.object(Path, "home", return_value=self.home)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def test_render_out_outside_claude_dir_refused(self):
        out = self.root / "elsewhere" / "config.yaml"
        code, _, err = run_main(["render-config", "--out", str(out)])
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())

    def test_render_out_in_home_but_not_claude_refused(self):
        out = self.home / "notclaude" / "config.yaml"
        code, _, _ = run_main(["render-config", "--out", str(out)])
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())

    def test_render_dry_run_writes_nothing(self):
        out = self.home / ".claude" / "litellm" / "config.yaml"
        code, _, _ = run_main(["render-config", "--out", str(out), "--dry-run", "--json"])
        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertFalse(out.parent.exists())

    def test_render_writes_valid_json_atomically(self):
        out = self.home / ".claude" / "litellm" / "config.yaml"
        code, _, _ = run_main(["render-config", "--out", str(out), "--json"])
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["general_settings"]["master_key"], "os.environ/LITELLM_MASTER_KEY")
        leftovers = [p for p in out.parent.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_tilde_expanded_to_home(self):
        code, _, _ = run_main(["render-config", "--out", "~/.claude/litellm/c.yaml", "--dry-run"])
        self.assertEqual(code, 0)


class TestPureHelpers(unittest.TestCase):
    """Small contracts other plans rely on."""

    def test_list_models_signature_and_return_keys(self):
        result = AM.list_models("dev", ENV, opener=FakeOpener(list_responses(["rosedale-1"])))
        self.assertEqual(set(result), {"profile", "selectable", "refused"})

    def test_profiles_docstring_states_one_line_rule(self):
        doc = AM.load_profiles.__doc__ or ""
        self.assertIn("augure-profiles.json", doc)
        self.assertIn("no code change", doc)
        self.assertIn("augure_models", AM.__doc__ or "")
        self.assertIn("one line", (AM.__doc__ or "") + doc)


if __name__ == "__main__":
    unittest.main()
