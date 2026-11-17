import json
import logging
import socket
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add loop-engineer scripts to path
_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "loop-engineer" / "scripts"
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from bridge_text import strip_reasoning, unwrap_sole_code_fence, ReasoningAnomalyError
from bridge_images import ImageError, attach_images

logger = logging.getLogger(__name__)


class NotRun(RuntimeError):
    """Raised when a model call cannot be completed."""
    def __init__(self, kind: str, reason: str):
        super().__init__(f"NotRun({kind}): {reason}")
        self.kind = kind
        self.reason = reason
        self.retryable = kind in ("unparsable", "invalid", "timeout")


# HTTP status codes that carry a meaning of their own here (protocol constants, not configuration).
HTTP_REQUEST_TIMEOUT = 408
HTTP_CLIENT_ERROR_FIRST = 400
HTTP_CLIENT_ERROR_LAST = 499

# What a socket read or connect raises when it runs out of time. socket.timeout is an alias of TimeoutError from
# Python 3.10 on; it is listed for the interpreters before that.
_TIMEOUT_TYPES = (TimeoutError, socket.timeout)


def _cause_chain(exc: BaseException) -> List[BaseException]:
    """
    Purpose: List an exception and each exception it was raised from, in order.
    Details: The real client raises its own error `from` the transport error, so the kind sits one or two links
        down the __cause__ chain. A set of seen identities stops a cycle; a chain is otherwise finite.
    Inputs:
        exc (BaseException): the exception that reached the bridge.
    Outputs:
        List[BaseException]: exc first, then its causes, each listed once.
    """
    chain: List[BaseException] = []
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__
    return chain


def _is_timeout(link: BaseException) -> bool:
    """
    Purpose: Tell whether one link of a failure chain is a timeout.
    Details: urllib reports a connect timeout as a URLError whose reason is the timeout, so that reason counts.
        An HTTPError is a URLError too, and is judged by its status code instead, never here.
    Inputs:
        link (BaseException): one exception of the chain.
    Outputs:
        bool: True for a timeout error or a URLError whose reason is one.
    """
    if isinstance(link, _TIMEOUT_TYPES):
        return True
    if isinstance(link, urllib.error.HTTPError):
        return False
    if isinstance(link, urllib.error.URLError):
        return isinstance(link.reason, _TIMEOUT_TYPES)
    return False


def classify_transport_error(exc: BaseException) -> NotRun:
    """
    Purpose: Name the kind of a failed transport call, so the grading batch can tell a slow model from a dead daemon.
    Details: A timeout is kind "timeout" and retryable: the daemon was reached and the model is slow. An HTTP 408
        is the server's own request timeout and is the same kind. Any other 4xx answer is "bad_request": the
        request was refused, and sending it again changes nothing. Everything else (a refused connection, a name
        that does not resolve, a daemon that is down, a 5xx) stays "unreachable" and is not retryable.
        The message names the kind and the classes of the chain, never the text of an error, since that text can
        quote the request or the reply, and the log and the reasons must hold no report text.
    Inputs:
        exc (BaseException): the exception the transport raised, with its causes.
    Outputs:
        NotRun: the classified refusal, for the caller to raise.
    """
    chain = _cause_chain(exc)
    names = " <- ".join(link.__class__.__name__ for link in chain)
    if any(_is_timeout(link) for link in chain):
        return NotRun("timeout", f"the daemon did not answer in time ({names})")
    for link in chain:
        if isinstance(link, urllib.error.HTTPError):
            if link.code == HTTP_REQUEST_TIMEOUT:
                return NotRun("timeout", f"the daemon timed out the request ({names})")
            if HTTP_CLIENT_ERROR_FIRST <= link.code <= HTTP_CLIENT_ERROR_LAST:
                return NotRun("bad_request", f"the daemon refused the request with HTTP {link.code} ({names})")
    return NotRun("unreachable", f"the daemon could not be reached ({names})")


def _now_iso() -> str:
    """
    Purpose: The default clock of this module, a UTC ISO 8601 stamp to the millisecond.
    Details: Milliseconds, not seconds: a grading run makes calls back to back, and a start record
        stamped in the same second as the previous end would not read as generating.
    Inputs: None.
    Outputs: str: for example 2026-11-15T16:30:05.123+00:00. A caller may inject another clock (R19).
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write_log(deps: Any, record: Dict[str, Any]) -> None:
    """
    Purpose: Hand one bridge log record to the deps object when it can write one.
    Details: The log only feeds the dashboard, so any failure of the writer is reported on the logger and the
        call goes on.
        A deps object without a callable `log` writes nothing, which keeps every test fake working.
    Inputs:
        deps: the deps object of the call.
        record (dict): the log record.
    Outputs: None.
    """
    write = getattr(deps, "log", None)
    if not callable(write):
        return
    try:
        write(record)
    except Exception as exc:  # noqa: BLE001 - best effort by design, and reported
        logger.warning("[UGS-BRIDGE] bridge log not written: %s: %s", exc.__class__.__name__, exc)


def validate_answer(answer: Any, schema: Dict[str, Any]) -> List[str]:
    """
    Purpose: Validate an answer against a JSON schema.
    Inputs:
        answer: The answer to validate.
        schema: The JSON schema.
    Outputs:
        List of error strings. Empty if valid.
    """
    errors: List[str] = []
    
    def _validate(value: Any, sch: Dict[str, Any], path: str) -> None:
        expected_types = sch.get("type")
        if expected_types:
            if isinstance(expected_types, str):
                expected_types = [expected_types]
            
            type_ok = False
            for t in expected_types:
                if t == "object" and isinstance(value, dict):
                    type_ok = True
                    break
                elif t == "array" and isinstance(value, list):
                    type_ok = True
                    break
                elif t == "string" and isinstance(value, str):
                    type_ok = True
                    break
                elif t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                    type_ok = True
                    break
                elif t == "integer" and isinstance(value, int) and not isinstance(value, bool):
                    type_ok = True
                    break
                elif t == "boolean" and isinstance(value, bool):
                    type_ok = True
                    break
                elif t == "null" and value is None:
                    type_ok = True
                    break
            
            if not type_ok:
                errors.append(f"{path}: expected type {expected_types}, got {type(value).__name__}")
                return # No point checking further properties if type is wrong

        if "enum" in sch and value not in sch["enum"]:
            errors.append(f"{path}: value not in the allowed enum")

        if "minimum" in sch and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < sch["minimum"]:
                errors.append(f"{path}: value below the minimum {sch['minimum']}")

        if "maximum" in sch and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > sch["maximum"]:
                errors.append(f"{path}: value above the maximum {sch['maximum']}")

        if isinstance(value, dict):
            for req in sch.get("required", []):
                if req not in value:
                    errors.append(f"{path}: missing required property '{req}'")
            
            for key, sub_schema in sch.get("properties", {}).items():
                if key in value:
                    _validate(value[key], sub_schema, f"{path}.{key}" if path else key)

        if isinstance(value, list):
            if "minItems" in sch and len(value) < sch["minItems"]:
                errors.append(f"{path}: array has {len(value)} items, less than minItems {sch['minItems']}")
            
            if "items" in sch:
                for i, item in enumerate(value):
                    _validate(item, sch["items"], f"{path}[{i}]")

    _validate(answer, schema, "")
    return errors


class OllamaDeps:
    """Real dependencies for ugs_bridge, lazy-loading ollama_bridge."""
    
    def __init__(self, count_timeout_s: int):
        """
        Purpose: Initialize OllamaDeps with the count timeout.
        Inputs:
            count_timeout_s (int): Timeout in seconds for token counting.
        """
        self._bridge = None
        self.count_timeout_s = count_timeout_s

    def _get_bridge(self):
        if self._bridge is None:
            # Lazy import
            import ollama_bridge
            self._bridge = ollama_bridge
        return self._bridge

    def tag(self, role: str) -> str:
        try:
            return self._get_bridge().resolve_model(role)
        except Exception as e:
            raise NotRun("unadopted", f"Failed to resolve role {role}: {e}")

    def window(self, tag: str, role: str) -> int:
        try:
            return self._get_bridge()._resolve_num_ctx(tag, role)
        except Exception as e:
            raise NotRun("unreachable", f"Failed to resolve window for {tag}: {e}")

    def log(self, record: Dict[str, Any]) -> None:
        """
        Purpose: Append one record to the machine-local bridge log that the dashboard reads.
        Inputs:
            record (dict): the log record.
        Outputs: None. The line goes to the log path and the writer of ollama_bridge.
        Raises:
            OSError: when the log file cannot be written.
        """
        bridge = self._get_bridge()
        bridge.append_log(bridge.DEFAULT_LOG_PATH, record)

    def count(self, prompt: str, tag: str, window: int) -> int:
        """
        Purpose: Count tokens in a prompt.
        Inputs:
            prompt (str): The prompt text.
            tag (str): The model tag.
            window (int): The context window.
        Outputs:
            int: The token count.
        Raises:
            NotRun: If the count fails.
        """
        try:
            return self._get_bridge().probe_prompt_tokens(prompt, tag, window, timeout=self.count_timeout_s)
        except Exception as e:
            raise classify_transport_error(e) from e

    def payload(self, prompt: str, tag: str, window: int, schema: Dict[str, Any], reserve: int) -> Dict[str, Any]:
        try:
            return self._get_bridge().build_payload(prompt, tag, self._get_bridge().DEFAULT_SEED, window, fmt=schema, num_predict=reserve)
        except Exception as e:
            raise NotRun("unreachable", f"Failed to build payload: {e}")

    def post(self, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """
        Purpose: Send the generate request and return the daemon's reply, classifying any transport failure.
        Inputs:
            payload (dict): the request body.
            timeout (int): the socket timeout in seconds, from driver.request_timeout_s.
        Outputs:
            dict: the parsed reply.
        Raises:
            NotRun: kind "timeout" (retryable), "bad_request" or "unreachable" (not retryable). See classify_transport_error.
        """
        try:
            return self._get_bridge()._post_generate(payload, timeout)
        except Exception as e:
            raise classify_transport_error(e) from e


def call_with_usage(
    role: str,
    prompt: str,
    schema: Dict[str, Any],
    images: Optional[List[str]] = None,
    *,
    deps: Any,
    timeout: int,
    reserve: int,
    image_tokens: int,
    max_image_bytes: int,
    clock: Optional[Callable[[], str]] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Purpose: Call the model and return the answer and usage.
    Inputs:
        role: The model role.
        prompt: The prompt text.
        schema: The JSON schema for the answer.
        images: Optional list of image paths.
        deps: The dependencies object (OllamaDeps or fake).
        timeout: Timeout for the call.
        reserve: Reserve tokens for the reply.
        image_tokens: Estimated tokens per image.
        max_image_bytes: Max bytes per image.
        clock: Optional callable giving the stamp of a log record; defaults to the module clock.
    Outputs:
        Tuple of (answer, usage).
    Raises:
        NotRun: If the call fails.
    """
    try:
        tag = deps.tag(role)
    except Exception as e:
        if isinstance(e, NotRun):
            raise
        raise NotRun("unadopted", f"Failed to resolve role: {e}")

    try:
        window = deps.window(tag, role)
    except Exception as e:
        if isinstance(e, NotRun):
            raise
        raise NotRun("unreachable", f"Failed to resolve window: {e}")

    now = clock or _now_iso
    # The start record comes BEFORE the token count: the count is a full prefill of the prompt and can
    # take minutes on this machine, and the model is busy for all of it (Issue 118, review round 1).
    _write_log(deps, {"event": "start", "at": now(), "role": role, "tag": tag,
                      "num_ctx": window, "plan": None})
    try:
        try:
            prompt_tokens = deps.count(prompt, tag, window)
        except Exception as e:
            if isinstance(e, NotRun):
                raise
            raise classify_transport_error(e) from e

        total_image_tokens = 0
        if images:
            total_image_tokens = len(images) * image_tokens

        if prompt_tokens + reserve + total_image_tokens > window:
            raise NotRun("over_budget", f"Prompt ({prompt_tokens}) + reserve ({reserve}) + images ({total_image_tokens}) exceeds window ({window})")

        try:
            payload = deps.payload(prompt, tag, window, schema, reserve)
        except Exception as e:
            if isinstance(e, NotRun):
                raise
            raise NotRun("unreachable", f"Failed to build payload: {e}")

        if images:
            # bridge_images.attach_images expects List[Path]
            paths = [Path(img) for img in images]
            try:
                payload = attach_images(payload, paths, max_image_bytes)
            except ImageError as e:
                raise NotRun("image", f"Image attachment failed: {e}")

        try:
            reply = deps.post(payload, timeout)
        except Exception as e:
            if isinstance(e, NotRun):
                raise
            raise classify_transport_error(e) from e
    except BaseException as exc:
        # Close the start record, also on an interrupt (Ctrl-C, SystemExit): a start with no end reads as
        # a generation in progress for the whole generation limit.
        # Only the kind or the class name is logged: an error text can quote
        # the request or the reply, and the log is plain text that other tools read (confidential reports).
        _write_log(deps, {"event": "failed", "at": now(), "role": role, "tag": tag,
                          "error": exc.kind if isinstance(exc, NotRun) else exc.__class__.__name__})
        raise

    accepted = False
    try:
        response_text = reply.get("response", "")
        try:
            stripped_text = strip_reasoning(response_text)
        except ReasoningAnomalyError:
            # an unterminated or orphan reasoning marker: one bad reply costs a retry, never the report
            raise NotRun("unparsable", "Reasoning markers could not be resolved") from None

        # If the text is still wrapped in code fences, unwrap it
        if stripped_text.startswith("```"):
            stripped_text = unwrap_sole_code_fence(stripped_text)

        try:
            answer = json.loads(stripped_text)
        except json.JSONDecodeError as e:
            raise NotRun("unparsable", f"Failed to parse JSON: {e}")

        errors = validate_answer(answer, schema)
        if errors:
            # Reason holds first three errors, no reply text
            reason = "; ".join(errors[:3])
            raise NotRun("invalid", reason)
        accepted = True
    finally:
        # The model did answer, so the tokens are real even when the answer is refused; `accepted` says
        # whether it was used.
        _write_log(deps, {"at": now(), "role": role, "tag": tag, "num_ctx": window,
                          "prompt_tokens": reply.get("prompt_eval_count"),
                          "completion_tokens": reply.get("eval_count"),
                          "plan": None, "accepted": accepted})

    usage = {
        "prompt_tokens": reply.get("prompt_eval_count"),
        "completion_tokens": reply.get("eval_count")
    }
    
    return answer, usage


def call(
    role: str,
    prompt: str,
    schema: Dict[str, Any],
    images: Optional[List[str]] = None,
    *,
    deps: Any,
    timeout: int,
    reserve: int,
    image_tokens: int,
    max_image_bytes: int,
    clock: Optional[Callable[[], str]] = None
) -> Dict[str, Any]:
    """
    Purpose: Call the model and return the answer.
    Inputs:
        Same as call_with_usage.
    Outputs:
        The answer.
    Raises:
        NotRun: If the call fails.
    """
    answer, _ = call_with_usage(
        role, prompt, schema, images,
        deps=deps, timeout=timeout, reserve=reserve,
        image_tokens=image_tokens, max_image_bytes=max_image_bytes, clock=clock
    )
    return answer
