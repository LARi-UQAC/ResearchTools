import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add loop-engineer scripts to path
_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "loop-engineer" / "scripts"
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from bridge_text import strip_reasoning, unwrap_sole_code_fence, ReasoningAnomalyError
from bridge_images import ImageError, attach_images


class NotRun(RuntimeError):
    """Raised when a model call cannot be completed."""
    def __init__(self, kind: str, reason: str):
        super().__init__(f"NotRun({kind}): {reason}")
        self.kind = kind
        self.reason = reason
        self.retryable = kind in ("unparsable", "invalid")


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
    
    def __init__(self):
        self._bridge = None

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

    def count(self, prompt: str, tag: str, window: int) -> int:
        try:
            return self._get_bridge().probe_prompt_tokens(prompt, tag, window, timeout=10)
        except Exception as e:
            raise NotRun("unreachable", f"Failed to count tokens: {e}")

    def payload(self, prompt: str, tag: str, window: int, schema: Dict[str, Any], reserve: int) -> Dict[str, Any]:
        try:
            return self._get_bridge().build_payload(prompt, tag, self._get_bridge().DEFAULT_SEED, window, fmt=schema, num_predict=reserve)
        except Exception as e:
            raise NotRun("unreachable", f"Failed to build payload: {e}")

    def post(self, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        try:
            return self._get_bridge()._post_generate(payload, timeout)
        except Exception as e:
            raise NotRun("unreachable", f"Post failed: {e}")


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
    max_image_bytes: int
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

    try:
        prompt_tokens = deps.count(prompt, tag, window)
    except Exception as e:
        if isinstance(e, NotRun):
            raise
        raise NotRun("unreachable", f"Failed to count tokens: {e}")
    
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
        raise NotRun("unreachable", f"Post failed: {e}")

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
    max_image_bytes: int
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
        image_tokens=image_tokens, max_image_bytes=max_image_bytes
    )
    return answer
