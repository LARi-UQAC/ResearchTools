import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add loop-engineer scripts to path
_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "loop-engineer" / "scripts"
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from ugs_bridge import NotRun, OllamaDeps
from ugs_text import load_schemas, load_prompts
from ugs_config import load as load_config, default_path, ConfigError

def _normalize_text(text: str) -> str:
    """
    Purpose: Normalize text for comparison by lowercasing, removing accents, and collapsing whitespace.
    Inputs:
        text: str - The text to normalize.
    Outputs:
        str - The normalized text.
    """
    text = text.lower()
    nfkd_form = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in nfkd_form if not unicodedata.combining(c)])
    # Remove all whitespace
    text = ''.join(text.split())
    return text

def probe(
    call_usage: Callable[..., Tuple[Dict, Dict]],
    image: Path,
    expected: dict,
    prompt: str,
    schema: dict
) -> dict:
    """
    Purpose: Probe the vision model to verify it can read the chart and measure image cost.
    Inputs:
        call_usage: Callable - Function to call the model and return (answer, usage).
        image: Path - Path to the image file.
        expected: dict - Expected values for x_title, y_title, unit, curve_count.
        prompt: str - The prompt text.
        schema: dict - The JSON schema for the answer.
    Outputs:
        dict - {ok: bool, answers: dict|None, image_tokens: int|None, kind: str|None}
    """
    # Call with image
    try:
        answer_with, usage_with = call_usage(prompt, schema, [str(image)])
    except NotRun as e:
        return {
            "ok": False,
            "kind": e.kind,
            "answers": None,
            "image_tokens": None
        }
    except Exception as e:
        return {
            "ok": False,
            "kind": "unreachable",
            "answers": None,
            "image_tokens": None
        }

    # Call without image
    try:
        answer_without, usage_without = call_usage(prompt, schema, None)
    except NotRun as e:
        # If the second call fails, we keep the result of the first but image_tokens is None
        # The spec says: "one from the second call keeps ok and gives image_tokens None"
        # But wait, if the first call succeeded, ok is determined by the first call's answer.
        # "A NotRun from the first call gives {ok: false...}; one from the second call keeps ok and gives image_tokens None."
        # So we need to evaluate ok based on answer_with.
        
        # Evaluate ok
        ok = _check_answer(answer_with, expected)
        
        return {
            "ok": ok,
            "kind": None,
            "answers": answer_with,
            "image_tokens": None
        }
    except Exception as e:
        ok = _check_answer(answer_with, expected)
        return {
            "ok": ok,
            "kind": None,
            "answers": answer_with,
            "image_tokens": None
        }

    # Evaluate ok
    ok = _check_answer(answer_with, expected)
    
    # Calculate image tokens
    image_tokens = None
    if "prompt_tokens" in usage_with and "prompt_tokens" in usage_without:
        image_tokens = usage_with["prompt_tokens"] - usage_without["prompt_tokens"]

    return {
        "ok": ok,
        "kind": None,
        "answers": answer_with,
        "image_tokens": image_tokens
    }

def _check_answer(answer: dict, expected: dict) -> bool:
    """
    Purpose: Check if the model answer matches the expected values.
    Inputs:
        answer: dict - The model answer.
        expected: dict - The expected values.
    Outputs:
        bool - True if all fields match.
    """
    if not isinstance(answer, dict):
        return False
        
    # Check text fields
    for key in ["x_title", "y_title", "unit"]:
        if key not in answer or key not in expected:
            return False
        if _normalize_text(str(answer[key])) != _normalize_text(str(expected[key])):
            return False
            
    # Check curve count
    if "curve_count" not in answer or "curve_count" not in expected:
        return False
    if answer["curve_count"] != expected["curve_count"]:
        return False
        
    return True

def main(argv: Optional[List[str]] = None, *, call_usage: Optional[Callable] = None) -> int:
    """
    Purpose: Run the vision probe and write the verdict.
    Inputs:
        argv: Optional[List[str]] - Command line arguments.
        call_usage: Optional[Callable] - Injected call function.
    Outputs:
        int - Exit code.
    """
    parser = argparse.ArgumentParser(description="Vision probe")
    parser.add_argument("--work", required=True, help="Work directory")
    parser.add_argument("--image", required=True, help="Image file path")
    parser.add_argument("--expected", required=True, help="Expected values JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    
    args = parser.parse_args(argv)
    
    work_dir = Path(args.work).resolve()
    image_path = Path(args.image).resolve()
    expected_path = Path(args.expected).resolve()
    
    # R17: confine every path derived from input
    try:
        image_path.relative_to(work_dir)
    except ValueError:
        print(f"Error: image path {image_path} is outside work folder {work_dir}", file=sys.stderr)
        return 2
        
    try:
        expected_path.relative_to(work_dir)
    except ValueError:
        print(f"Error: expected path {expected_path} is outside work folder {work_dir}", file=sys.stderr)
        return 2

    if not image_path.is_file():
        print(f"Error: image file not found: {image_path}", file=sys.stderr)
        return 2
        
    if not expected_path.is_file():
        print(f"Error: expected file not found: {expected_path}", file=sys.stderr)
        return 2

    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Error: invalid JSON in expected file: {expected_path}", file=sys.stderr)
        return 2

    # Load the configuration: flat dotted keys, every value read from the file (R0), a missing key refused by name (R3)
    try:
        config = load_config(default_path())
    except Exception as e:
        print(f"Error: failed to load config: {e}", file=sys.stderr)
        return 2

    # Prompts and schemas live in the prompts folder of the skill
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    try:
        prompts = load_prompts(prompts_dir)
        prompt_text = prompts.get("vision_probe", "")
        if not prompt_text:
            print("Error: vision_probe prompt not found", file=sys.stderr)
            return 2
        schemas = load_schemas(prompts_dir / "schemas.json", ["vision_probe"])
        schema = schemas["vision_probe"]
    except Exception as e:
        print(f"Error: failed to load prompts/schemas: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        # R16: say what would be done and touch nothing, no model is called
        print(json.dumps({"dry_run": True, "role": config["roles.vision"], "image": image_path.name,
                          "would_write": "vision_probe.json"}))
        return 0

    # Build call_usage if not injected
    if call_usage is None:
        deps = OllamaDeps(config["driver.count_timeout_s"])
        role = config["roles.vision"]
        timeout = config["driver.request_timeout_s"]
        reserve = config["driver.reply_reserve_tokens"]
        image_tokens_est = config["driver.image_tokens_fallback"]
        max_image_bytes = config["driver.max_image_bytes"]

        def real_call_usage(prompt: str, schema: dict, images: Optional[List[str]] = None) -> Tuple[dict, dict]:
            from ugs_bridge import call_with_usage
            return call_with_usage(
                role, prompt, schema, images,
                deps=deps,
                timeout=timeout,
                reserve=reserve,
                image_tokens=image_tokens_est,
                max_image_bytes=max_image_bytes
            )
        call_usage = real_call_usage

    result = probe(call_usage, image_path, expected, prompt_text, schema)
    
    output = {
        "ok": result["ok"],
        "image_tokens": result["image_tokens"],
        "kind": result.get("kind")
    }
    
    # Write output
    out_path = work_dir / "vision_probe.json"
    try:
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Error: failed to write output: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(output))
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
