import tempfile
import shutil
import os
import base64
import atexit
import sys
import json
import io
import unittest
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

# Put the parent folder of the test folder on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ugs_bridge

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PNG_DIR = tempfile.mkdtemp()
atexit.register(shutil.rmtree, _PNG_DIR, True)


def _png_files(count):
    """
    Purpose: Write count tiny real PNG files and return their paths as strings.
    Inputs:
        count (int): Number of files to write.
    Outputs:
        list of str: The paths, inside a folder removed at exit.
    """
    paths = []
    for i in range(count):
        path = os.path.join(_PNG_DIR, f"img{i + 1}.png")
        with open(path, "wb") as handle:
            handle.write(_PNG_1X1)
        paths.append(path)
    return paths



class FakeDeps:
    def __init__(self, tag: str = "fake-tag", window: int = 1000, count: int = 100,
                 payload: Optional[Dict[str, Any]] = None, post_result: Optional[Dict[str, Any]] = None,
                 post_error: Optional[Exception] = None, tag_error: Optional[Exception] = None,
                 count_error: Optional[Exception] = None, count_timeout_s: int = 10):
        self._default_tag = tag
        self._default_window = window
        self._default_count = count
        self._default_payload = payload or {"prompt": "fake"}
        self.post_result = post_result or {"response": "{}", "prompt_eval_count": 10, "eval_count": 5}
        self.post_error = post_error
        self.tag_error = tag_error
        self.count_error = count_error
        self.count_timeout_s = count_timeout_s
        self.calls = []

    def tag(self, role: str) -> str:
        self.calls.append(("tag", role))
        if self.tag_error:
            raise self.tag_error
        return self._default_tag

    def window(self, tag: str, role: str) -> int:
        self.calls.append(("window", tag, role))
        return self._default_window

    def count(self, prompt: str, tag: str, window: int) -> int:
        self.calls.append(("count", prompt, tag, window))
        if self.count_error:
            raise self.count_error
        return self._default_count

    def payload(self, prompt: str, tag: str, window: int, schema: Dict[str, Any], reserve: int) -> Dict[str, Any]:
        self.calls.append(("payload", prompt, tag, window, schema, reserve))
        return self._default_payload

    def post(self, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        self.calls.append(("post", payload, timeout))
        if self.post_error:
            raise self.post_error
        return self.post_result


class TestNotRun(unittest.TestCase):
    def test_retryable_kinds(self):
        self.assertTrue(ugs_bridge.NotRun("unparsable", "reason").retryable)
        self.assertTrue(ugs_bridge.NotRun("invalid", "reason").retryable)
        self.assertFalse(ugs_bridge.NotRun("unreachable", "reason").retryable)
        self.assertFalse(ugs_bridge.NotRun("unadopted", "reason").retryable)
        self.assertFalse(ugs_bridge.NotRun("over_budget", "reason").retryable)
        self.assertFalse(ugs_bridge.NotRun("image", "reason").retryable)

    def test_attributes(self):
        err = ugs_bridge.NotRun("invalid", "some reason")
        self.assertEqual(err.kind, "invalid")
        self.assertEqual(err.reason, "some reason")
        self.assertIsInstance(err, RuntimeError)


class TestValidateAnswer(unittest.TestCase):
    def test_valid_object(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer = {"a": "hello"}
        self.assertEqual(ugs_bridge.validate_answer(answer, schema), [])

    def test_missing_required(self):
        schema = {"type": "object", "required": ["a"]}
        answer = {}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("a" in e for e in errors))

    def test_wrong_type(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer = {"a": 123}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("a" in e and "string" in e for e in errors))

    def test_enum_violation(self):
        schema = {"type": "object", "properties": {"a": {"enum": ["x", "y"]}}, "required": ["a"]}
        answer = {"a": "z"}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("a" in e and "enum" in e for e in errors))

    def test_array_items_and_minItems(self):
        schema = {
            "type": "object",
            "properties": {"arr": {"type": "array", "items": {"type": "integer"}, "minItems": 2}},
            "required": ["arr"]
        }
        answer = {"arr": [1]}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("arr" in e and "minItems" in e for e in errors))

        answer = {"arr": [1, "two"]}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("arr[1]" in e and "integer" in e for e in errors))

    def test_bounds(self):
        schema = {"type": "object", "properties": {"n": {"type": "number", "minimum": 1, "maximum": 10}}, "required": ["n"]}
        answer = {"n": 0}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("n" in e and "minimum" in e for e in errors))

        answer = {"n": 11}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("n" in e and "maximum" in e for e in errors))

    def test_boolean_is_not_integer(self):
        schema = {"type": "object", "properties": {"b": {"type": "integer"}}, "required": ["b"]}
        answer = {"b": True}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("b" in e and "integer" in e for e in errors))

    def test_boolean_is_not_number(self):
        schema = {"type": "object", "properties": {"b": {"type": "number"}}, "required": ["b"]}
        answer = {"b": False}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("b" in e and "number" in e for e in errors))

    def test_array_index_in_error(self):
        schema = {"type": "object", "properties": {"arr": {"type": "array", "items": {"type": "string"}}}, "required": ["arr"]}
        answer = {"arr": ["ok", 123]}
        errors = ugs_bridge.validate_answer(answer, schema)
        self.assertTrue(any("arr[1]" in e for e in errors))


class TestCallWithUsage(unittest.TestCase):
    def test_call_returns_parsed_answer(self):
        deps = FakeDeps(post_result={"response": '{"a": "hello"}', "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer, usage = ugs_bridge.call_with_usage(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100
        )
        self.assertEqual(answer, {"a": "hello"})
        self.assertEqual(usage, {"prompt_tokens": 10, "completion_tokens": 5})

    def test_reasoning_block_is_removed_before_parsing(self):
        # Simulate a response with reasoning that strip_reasoning would remove
        # strip_reasoning removes think... blocks or Thinking... blocks
        # We use a format that strip_reasoning handles: think... ...done thinking.
        reply = 'Thinking...\nsome thoughts\n...done thinking.\n{"a": "hello"}'
        deps = FakeDeps(post_result={"response": reply, "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer, _ = ugs_bridge.call_with_usage(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100
        )
        self.assertEqual(answer, {"a": "hello"})

    def test_a_reasoning_anomaly_is_a_retryable_unparsable_not_an_escape(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        for reply in ("<think>never closed {\"a\": \"x\"}", "</think>{\"a\": \"x\"}"):
            deps = FakeDeps(post_result={"response": reply, "prompt_eval_count": 1, "eval_count": 1})
            with self.assertRaises(ugs_bridge.NotRun) as ctx:
                ugs_bridge.call_with_usage(role="grader", prompt="test", schema=schema, deps=deps, timeout=1,
                                           reserve=0, image_tokens=0, max_image_bytes=100)
            self.assertEqual(ctx.exception.kind, "unparsable")
            self.assertTrue(ctx.exception.retryable)

    def test_invalid_reason_never_carries_the_replied_value(self):
        # A reply value can echo student text: only the path and the constraint may be reported.
        sentinel = "SENTINEL-STUDENT-TEXT"
        schema = {
            "type": "object",
            "properties": {"a": {"enum": ["x", "y"]}, "n": {"type": "number", "minimum": 0, "maximum": 5}},
        }
        for reply in (
            '{"a": "%s"}' % sentinel,
            '{"n": -987654}',
            '{"n": 987654}',
        ):
            deps = FakeDeps(post_result={"response": reply, "prompt_eval_count": 1, "eval_count": 1})
            with self.assertRaises(ugs_bridge.NotRun) as ctx:
                ugs_bridge.call_with_usage(
                    role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                    image_tokens=0, max_image_bytes=100
                )
            self.assertEqual(ctx.exception.kind, "invalid")
            for leaked in (sentinel, "987654"):
                self.assertNotIn(leaked, str(ctx.exception))
                self.assertNotIn(leaked, ctx.exception.reason)

    def test_over_budget_prompt_is_not_run_and_never_posted(self):
        deps = FakeDeps(count=900, window=1000)
        schema = {"type": "object"}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=200,
                image_tokens=0, max_image_bytes=100
            )
        self.assertEqual(ctx.exception.kind, "over_budget")
        # Check that post was NOT called
        self.assertFalse(any(call[0] == "post" for call in deps.calls))

    def test_image_cost_counts_against_the_window(self):
        deps = FakeDeps(count=900, window=1000)
        schema = {"type": "object"}
        # image_tokens=50, 2 images -> 100 total image cost
        # 900 + 0 + 100 = 1000 <= 1000 (OK)
        answer, _ = ugs_bridge.call_with_usage(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=50, max_image_bytes=100, images=_png_files(2)
        )
        
        # Now make it exceed
        deps2 = FakeDeps(count=900, window=1000)
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps2, timeout=1, reserve=0,
                image_tokens=51, max_image_bytes=100, images=_png_files(2)
            )
        self.assertEqual(ctx.exception.kind, "over_budget")

    def test_unparsable_reply_is_retryable(self):
        deps = FakeDeps(post_result={"response": "not json", "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object"}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                image_tokens=0, max_image_bytes=100
            )
        self.assertEqual(ctx.exception.kind, "unparsable")
        self.assertTrue(ctx.exception.retryable)

    def test_schema_violation_is_invalid_and_retryable(self):
        deps = FakeDeps(post_result={"response": '{"a": 123}', "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                image_tokens=0, max_image_bytes=100
            )
        self.assertEqual(ctx.exception.kind, "invalid")
        self.assertTrue(ctx.exception.retryable)

    def test_unreachable_post_is_not_retryable(self):
        deps = FakeDeps(post_error=Exception("connection refused"))
        schema = {"type": "object"}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                image_tokens=0, max_image_bytes=100
            )
        self.assertEqual(ctx.exception.kind, "unreachable")
        self.assertFalse(ctx.exception.retryable)

    def test_unadopted_role_is_not_run(self):
        deps = FakeDeps(tag_error=Exception("role not found"))
        schema = {"type": "object"}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                image_tokens=0, max_image_bytes=100
            )
        self.assertEqual(ctx.exception.kind, "unadopted")
        self.assertFalse(ctx.exception.retryable)

    def test_count_uses_configured_timeout(self):
        class SpyBridge:
            def probe_prompt_tokens(self, prompt, tag, window, timeout):
                self.timeout = timeout
                return 100
            def resolve_model(self, role):
                return "tag"
            def _resolve_num_ctx(self, tag, role):
                return 1000
            def build_payload(self, *args, **kwargs):
                return {}
            def _post_generate(self, payload, timeout):
                return {"response": "{}", "prompt_eval_count": 10, "eval_count": 5}
            DEFAULT_SEED = 42
        
        bridge = SpyBridge()
        deps = ugs_bridge.OllamaDeps(count_timeout_s=123)
        deps._bridge = bridge
        deps.count("prompt", "tag", 1000)
        self.assertEqual(bridge.timeout, 123)

    def test_count_timeout_missing_in_config_raises(self):
        config = {"driver.request_timeout_s": 600}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            # This test is conceptual: the actual check happens in driver/vision_probe
            # We verify OllamaDeps requires count_timeout_s
            try:
                ugs_bridge.OllamaDeps()
            except TypeError as e:
                raise ugs_bridge.NotRun("config", str(e))
        self.assertIn("count_timeout_s", str(ctx.exception))

    def test_shipped_config_has_count_timeout(self):
        config_path = Path(__file__).resolve().parent.parent.parent / "assets" / "ugs_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.assertIn("driver.count_timeout_s", config)
        entry = config["driver.count_timeout_s"]
        self.assertEqual(entry["value"], 1200)
        self.assertTrue(entry["provenance"])

    def test_images_reach_the_posted_body(self):
        deps = FakeDeps(post_result={"response": "{}", "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object"}
        ugs_bridge.call_with_usage(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100, images=_png_files(2)
        )
        # Check that post was called with a payload containing images
        post_call = [c for c in deps.calls if c[0] == "post"][0]
        payload = post_call[1]
        self.assertIn("images", payload)
        self.assertEqual(len(payload["images"]), 2)

    def test_bad_image_is_kind_image(self):
        import unittest.mock as mock
        from bridge_images import ImageError
        
        # Patch attach_images in ugs_bridge to raise ImageError
        with mock.patch('ugs_bridge.attach_images', side_effect=ImageError("Bad image")):
            deps = FakeDeps(post_result={"response": "{}", "prompt_eval_count": 10, "eval_count": 5})
            schema = {"type": "object"}
            with self.assertRaises(ugs_bridge.NotRun) as ctx:
                ugs_bridge.call_with_usage(
                    role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                    images=["img1"], image_tokens=0, max_image_bytes=100
                )
            self.assertEqual(ctx.exception.kind, "image")

    def test_usage_counts_come_from_the_reply_and_none_when_absent(self):
        deps = FakeDeps(post_result={"response": "{}"}) # No prompt_eval_count or eval_count
        schema = {"type": "object"}
        _, usage = ugs_bridge.call_with_usage(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100
        )
        self.assertIsNone(usage["prompt_tokens"])
        self.assertIsNone(usage["completion_tokens"])

    def test_invalid_reason_holds_no_reply_text(self):
        deps = FakeDeps(post_result={"response": '{"a": 123}', "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call_with_usage(
                role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
                image_tokens=0, max_image_bytes=100
            )
        self.assertIn("a", ctx.exception.reason)
        self.assertNotIn("123", ctx.exception.reason) # Reply text should not be in reason


class FakeTransportBridge:
    """
    Purpose: Stand in for the ollama_bridge module behind OllamaDeps, with its transport raising what the test sets.
    Details: The real _post_generate wraps a timeout or a refused connection in BridgeError with the original as its
        __cause__; FakeBridgeError below plays BridgeError, so the test reads the same chain the real client makes.
    """

    DEFAULT_SEED = 1
    DEFAULT_LOG_PATH = None

    def __init__(self, post_exc: Optional[BaseException] = None, count_exc: Optional[BaseException] = None):
        self.post_exc = post_exc
        self.count_exc = count_exc

    def append_log(self, path, record) -> None:
        return None

    def resolve_model(self, role: str) -> str:
        return "fake-tag"

    def _resolve_num_ctx(self, tag: str, role: str) -> int:
        return 1000

    def build_payload(self, prompt, tag, seed, window, fmt=None, num_predict=None) -> Dict[str, Any]:
        return {"prompt": prompt}

    def probe_prompt_tokens(self, prompt, tag, window, timeout) -> int:
        if self.count_exc is not None:
            raise self.count_exc
        return 5

    def _post_generate(self, payload, timeout) -> Dict[str, Any]:
        if self.post_exc is not None:
            raise self.post_exc
        return {"response": "{}"}


class FakeBridgeError(Exception):
    """Plays ollama_bridge.BridgeError, the wrapper the real client raises around the transport error."""


def _chained(outer: BaseException, inner: BaseException) -> BaseException:
    """
    Purpose: Attach inner as the cause of outer, the way `raise outer from inner` does in the real client.
    Inputs:
        outer (BaseException): the wrapper, a BridgeError in the tests.
        inner (BaseException): the transport error underneath.
    Outputs:
        BaseException: outer, with __cause__ set to inner.
    """
    outer.__cause__ = inner
    return outer


def _ollama_deps_with(post_exc: Optional[BaseException] = None, count_exc: Optional[BaseException] = None):
    """
    Purpose: Build the real OllamaDeps over a fake bridge module, so its own error classification runs.
    Inputs:
        post_exc (BaseException or None): what the transport raises on the generate call.
        count_exc (BaseException or None): what the transport raises on the token count.
    Outputs:
        OllamaDeps: the dependencies object with the fake bridge in place.
    """
    deps = ugs_bridge.OllamaDeps(count_timeout_s=10)
    deps._bridge = FakeTransportBridge(post_exc=post_exc, count_exc=count_exc)
    return deps


def _call_over(deps) -> None:
    """
    Purpose: Make one bridge call over the given dependencies, with no reserve and no images.
    Inputs:
        deps: the dependencies object.
    Outputs:
        None. Any NotRun raised by the call propagates to the caller.
    """
    ugs_bridge.call_with_usage(
        role="grader", prompt="test", schema={"type": "object"}, deps=deps, timeout=1, reserve=0,
        image_tokens=0, max_image_bytes=100
    )


class TestTransportKinds(unittest.TestCase):
    def test_timeout_is_a_retryable_timeout_kind(self):
        timed_out = _chained(FakeBridgeError("request timed out"), TimeoutError("read timed out"))
        for post_exc in (timed_out, TimeoutError("read timed out")):
            with self.subTest(post_exc=type(post_exc).__name__):
                deps = _ollama_deps_with(post_exc=post_exc)
                with self.assertRaises(ugs_bridge.NotRun) as ctx:
                    _call_over(deps)
                self.assertEqual(ctx.exception.kind, "timeout")
                self.assertTrue(ctx.exception.retryable)

    def test_a_timeout_on_the_token_count_is_a_retryable_timeout_kind(self):
        deps = _ollama_deps_with(count_exc=_chained(FakeBridgeError("count timed out"), TimeoutError("slow")))
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            _call_over(deps)
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertTrue(ctx.exception.retryable)

    def test_connection_refused_stays_unreachable_and_not_retryable(self):
        refused = _chained(FakeBridgeError("cannot reach the daemon"), urllib.error.URLError(ConnectionRefusedError("refused")))
        deps = _ollama_deps_with(post_exc=refused)
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            _call_over(deps)
        self.assertEqual(ctx.exception.kind, "unreachable")
        self.assertFalse(ctx.exception.retryable)

    def test_bad_request_is_its_own_kind_not_retryable(self):
        http_400 = urllib.error.HTTPError("http://127.0.0.1/api/generate", 400, "Bad Request", None, io.BytesIO(b""))
        deps = _ollama_deps_with(post_exc=_chained(FakeBridgeError("HTTP 400"), http_400))
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            _call_over(deps)
        self.assertEqual(ctx.exception.kind, "bad_request")
        self.assertFalse(ctx.exception.retryable)

    def test_the_reason_holds_no_report_text(self):
        deps = _ollama_deps_with(post_exc=_chained(FakeBridgeError("SECRET-REPORT-TEXT"), TimeoutError("read timed out")))
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            _call_over(deps)
        self.assertNotIn("SECRET-REPORT-TEXT", ctx.exception.reason)


class TestCall(unittest.TestCase):
    def test_call_returns_only_answer(self):
        deps = FakeDeps(post_result={"response": '{"a": "hello"}', "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer = ugs_bridge.call(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100
        )
        self.assertEqual(answer, {"a": "hello"})


class LoggingDeps(FakeDeps):
    """FakeDeps that also records the bridge log records it is asked to write."""

    def __init__(self, *args, log_error: Optional[Exception] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.records: List[Dict[str, Any]] = []
        self.log_error = log_error

    def log(self, record: Dict[str, Any]) -> None:
        if self.log_error:
            raise self.log_error
        self.records.append(record)


_SCHEMA_A = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def _call(deps, role="ugs-grader"):
    """
    Purpose: Run one call of ugs_bridge with fixed small settings.
    Inputs:
        deps: the deps object under test.
        role (str): the role name.
    Outputs:
        The parsed answer.
    """
    return ugs_bridge.call(role=role, prompt="test", schema=_SCHEMA_A, deps=deps, timeout=1,
                           reserve=0, image_tokens=0, max_image_bytes=100)


class TestBridgeLog(unittest.TestCase):
    """The records that let the dashboard see a work-ugs-audit call (Issue 118)."""

    def test_a_good_call_writes_start_then_the_attempt_with_tokens(self):
        deps = LoggingDeps(tag="tag-x", window=500,
                           post_result={"response": '{"a": "x"}', "prompt_eval_count": 12, "eval_count": 7})
        _call(deps)
        self.assertEqual([r.get("event") for r in deps.records], ["start", None])
        start, attempt = deps.records
        self.assertEqual((start["role"], start["tag"], start["num_ctx"]), ("ugs-grader", "tag-x", 500))
        self.assertEqual((attempt["prompt_tokens"], attempt["completion_tokens"]), (12, 7))
        self.assertEqual((attempt["role"], attempt["tag"], attempt["num_ctx"]), ("ugs-grader", "tag-x", 500))
        self.assertTrue(attempt["accepted"])
        self.assertTrue(start["at"] and attempt["at"])

    def test_absent_token_counts_are_none_not_zero(self):
        deps = LoggingDeps(post_result={"response": '{"a": "x"}'})
        _call(deps)
        attempt = deps.records[1]
        self.assertIsNone(attempt["prompt_tokens"])
        self.assertIsNone(attempt["completion_tokens"])

    def test_a_failing_post_writes_start_then_failed_and_still_raises(self):
        deps = LoggingDeps(post_error=Exception("connection refused SECRET-REPORT-TEXT"))
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            _call(deps)
        self.assertEqual(ctx.exception.kind, "unreachable")
        self.assertEqual([r.get("event") for r in deps.records], ["start", "failed"])
        self.assertEqual(deps.records[1]["error"], "unreachable")

    def test_the_log_never_carries_an_error_text(self):
        deps = LoggingDeps(post_error=Exception("SECRET-REPORT-TEXT"))
        with self.assertRaises(ugs_bridge.NotRun):
            _call(deps)
        self.assertNotIn("SECRET-REPORT-TEXT", json.dumps(deps.records))

    def test_the_start_record_comes_before_the_token_count(self):
        order = []

        class Ordered(LoggingDeps):
            def count(self, prompt, tag, window):
                order.append(("count", [r.get("event") for r in self.records]))
                return super().count(prompt, tag, window)

        deps = Ordered(post_result={"response": '{"a": "x"}', "prompt_eval_count": 1, "eval_count": 1})
        _call(deps)
        self.assertEqual(order, [("count", ["start"])])

    def test_a_count_that_fails_closes_the_start_record(self):
        deps = LoggingDeps(count_error=Exception("timed out"))
        with self.assertRaises(ugs_bridge.NotRun):
            _call(deps)
        self.assertEqual([r.get("event") for r in deps.records], ["start", "failed"])

    def test_an_over_budget_prompt_closes_the_start_record_and_is_never_posted(self):
        deps = LoggingDeps(count=900, window=1000)
        with self.assertRaises(ugs_bridge.NotRun) as ctx:
            ugs_bridge.call(role="ugs-grader", prompt="test", schema=_SCHEMA_A, deps=deps, timeout=1,
                            reserve=500, image_tokens=0, max_image_bytes=100)
        self.assertEqual(ctx.exception.kind, "over_budget")
        self.assertEqual([r.get("event") for r in deps.records], ["start", "failed"])
        self.assertEqual(deps.records[1]["error"], "over_budget")
        self.assertNotIn("post", [c[0] for c in deps.calls])

    def test_a_refused_reply_is_logged_with_its_tokens_and_not_accepted(self):
        for reply in ("not json", '{"a": 123}'):
            deps = LoggingDeps(post_result={"response": reply, "prompt_eval_count": 30, "eval_count": 4})
            with self.assertRaises(ugs_bridge.NotRun):
                _call(deps)
            attempt = deps.records[-1]
            self.assertEqual((attempt["prompt_tokens"], attempt["completion_tokens"]), (30, 4))
            self.assertIs(attempt["accepted"], False)

    def test_stamps_carry_milliseconds_so_back_to_back_calls_keep_their_order(self):
        import re
        self.assertRegex(ugs_bridge._now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$")

    def test_the_clock_is_injected_by_the_caller(self):
        stamps = iter(["2026-11-15T12:00:00.001+00:00", "2026-11-15T12:00:00.002+00:00"])
        deps = LoggingDeps(post_result={"response": '{"a": "x"}', "prompt_eval_count": 1, "eval_count": 1})
        ugs_bridge.call(role="ugs-grader", prompt="test", schema=_SCHEMA_A, deps=deps, timeout=1,
                        reserve=0, image_tokens=0, max_image_bytes=100, clock=lambda: next(stamps))
        self.assertEqual([r["at"] for r in deps.records],
                         ["2026-11-15T12:00:00.001+00:00", "2026-11-15T12:00:00.002+00:00"])

    def test_an_interrupt_during_the_post_still_closes_the_start_record(self):
        deps = LoggingDeps(post_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            _call(deps)
        self.assertEqual([r.get("event") for r in deps.records], ["start", "failed"])
        self.assertEqual(deps.records[1]["error"], "KeyboardInterrupt")

    def test_deps_without_log_make_the_same_call(self):
        deps = FakeDeps(post_result={"response": '{"a": "x"}', "prompt_eval_count": 1, "eval_count": 1})
        self.assertEqual(_call(deps), {"a": "x"})

    def test_a_log_that_cannot_write_does_not_change_the_answer(self):
        deps = LoggingDeps(log_error=OSError("disk full"),
                           post_result={"response": '{"a": "x"}', "prompt_eval_count": 1, "eval_count": 1})
        self.assertEqual(_call(deps), {"a": "x"})

    def test_any_failure_of_the_log_writer_is_reported_and_never_fatal(self):
        for error in (ValueError("bug"), AttributeError("older bridge")):
            deps = LoggingDeps(log_error=error,
                               post_result={"response": '{"a": "x"}', "prompt_eval_count": 1, "eval_count": 1})
            with self.assertLogs("ugs_bridge", level="WARNING"):
                self.assertEqual(_call(deps), {"a": "x"})

    def test_the_records_read_back_as_a_generating_then_idle_role(self):
        scripts = Path(__file__).resolve().parents[3] / "rt-observe" / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            import collect_local
        finally:
            sys.path.remove(str(scripts))
        deps = LoggingDeps(tag="tag-y", window=777,
                           post_result={"response": '{"a": "x"}', "prompt_eval_count": 20, "eval_count": 9})
        _call(deps)
        start, attempt = deps.records
        now = collect_local._stamp(attempt["at"])
        roles, kept, skipped, _actions = collect_local._group([start], now, 60, 3600)
        self.assertTrue(roles["ugs-grader"]["generating"])
        roles, kept, skipped, _actions = collect_local._group([start, attempt], now, 60, 3600)
        row = roles["ugs-grader"]
        self.assertFalse(row["generating"])
        self.assertEqual((row["tag"], row["num_ctx"], row["prompt_tokens"], row["completion_tokens"]),
                         ("tag-y", 777, 20, 9))

    def test_ollama_deps_log_appends_to_the_bridge_log_path(self):
        class SpyBridge:
            DEFAULT_LOG_PATH = Path("log-path-for-the-test")
            written = []

            @staticmethod
            def append_log(path, record):
                SpyBridge.written.append((path, record))

        deps = ugs_bridge.OllamaDeps(1200)
        deps._bridge = SpyBridge
        deps.log({"event": "start"})
        self.assertEqual(SpyBridge.written, [(Path("log-path-for-the-test"), {"event": "start"})])


class RecordingDeps:
    """Fake deps that record the schema sent to the payload and then refuse the call (fictitious, R21)."""

    def __init__(self):
        self.sent_schemas = []

    def tag(self, role):
        return "fictitious-tag"

    def window(self, tag, role):
        return 100000

    def count(self, prompt, tag, window):
        return 10

    def payload(self, prompt, tag, window, schema, reserve):
        self.sent_schemas.append(schema)
        raise ugs_bridge.NotRun("unreachable", "recorded, not sent")


class SchemaThroughTheBridgeTest(unittest.TestCase):
    """Review round 3: the schema the grader passes is the one the bridge puts in the payload's format field."""

    def test_the_per_item_schema_reaches_the_payload_format_field(self):
        import ugs_grade
        from ugs_text import StepContext
        schema_file = Path(__file__).resolve().parent.parent.parent / "prompts" / "schemas.json"
        base = json.loads(schema_file.read_text(encoding="utf-8"))["grade_item"]
        deps = RecordingDeps()
        call = lambda prompt, schema, images=None: ugs_bridge.call(
            "writer", prompt, schema, images, deps=deps, timeout=1, reserve=10, image_tokens=0,
            max_image_bytes=10 ** 6)
        ctx = StepContext(prompts={"grade_item": "G {{ITEM}} {{SECTIONS}} {{LEVELS}} {{LANGUAGE_OF_REPORT}} "
                                                 "{{CALIBRATION_NOTE}}"},
                          schemas={"grade_item": base}, levels={"absent": 0}, window_tokens=100000,
                          reserve_tokens=10, count=lambda text: len(text.split()), grade_retries=0,
                          audit_retries=0, min_word_len=3)
        item = {"id": "I01", "title": "T", "max_points": 2,
                "elements": [{"id": "E1", "text": "Alpha"}, {"id": "E2", "text": "Beta"}]}
        settings = {"quote": {"min_chars": 12, "min_words": 3, "min_word_share": 0.9, "window_factor": 1.3,
                              "page_window": 1, "max_words": 24},
                    "unverified_as": "partial", "step": ugs_grade.Decimal("0.001"), "max_elements": 12,
                    "comment_openings": ["le rapport"], "min_model_elements": 1}
        with self.assertRaises(ugs_bridge.NotRun):
            ugs_grade.grade_item(item, ["Fictive page text here."], call, ctx, "en", "", settings=settings)
        sent = deps.sent_schemas[0]
        self.assertEqual(sent["properties"]["elements"]["minItems"], 2)
        self.assertEqual(sent["properties"]["elements"]["items"]["properties"]["id"]["enum"], ["E1", "E2"])
        self.assertNotIn("minItems", base["properties"]["elements"])


if __name__ == "__main__":
    unittest.main()
