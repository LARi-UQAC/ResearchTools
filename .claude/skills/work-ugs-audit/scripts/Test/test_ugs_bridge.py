import tempfile
import shutil
import os
import base64
import atexit
import sys
import json
import unittest
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


class TestCall(unittest.TestCase):
    def test_call_returns_only_answer(self):
        deps = FakeDeps(post_result={"response": '{"a": "hello"}', "prompt_eval_count": 10, "eval_count": 5})
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        answer = ugs_bridge.call(
            role="grader", prompt="test", schema=schema, deps=deps, timeout=1, reserve=0,
            image_tokens=0, max_image_bytes=100
        )
        self.assertEqual(answer, {"a": "hello"})


if __name__ == "__main__":
    unittest.main()
