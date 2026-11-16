"""
vision_probe - check that the vision role reads an image, and measure what an image costs in tokens.

The probe is kind-neutral (Issue 120): a figure of a report can be a chart, a Gantt chart, a diagram, a technical
drawing (a CAD view, a PCB layout) or a photo, and only a chart has axes and a legend. The model names the kind of
the figure and lists the text printed on it. The probe passes when the kind is the expected one (when one is
expected) and enough of the expected words are among the text the model read. The verdict always says why.
"""
import argparse
import json
import re
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
    Purpose: Normalize text for comparison by lowercasing, removing accents, and removing all whitespace.
    Inputs:
        text: str - The text to normalize.
    Outputs:
        str - The normalized text.
    """
    text = text.lower()
    nfkd_form = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in nfkd_form if not unicodedata.combining(c)])
    return ''.join(text.split())


def _spaced(text: str) -> str:
    """
    Purpose: Lowercase a text, remove its accents and collapse its spacing to single spaces, to match whole words.
    Inputs:
        text: str - The text.
    Outputs:
        str - The comparable form.
    """
    nfkd_form = unicodedata.normalize('NFKD', text.lower())
    return ' '.join(''.join(c for c in nfkd_form if not unicodedata.combining(c)).split())


def _contains_word(entry: str, word: str) -> bool:
    """
    Purpose: Tell whether a normalized entry holds a normalized word or phrase as whole words, so a short word such
        as x or mm is not found inside an unrelated word.
    Inputs:
        entry: str - the normalized text the model read.
        word: str - the normalized expected word or phrase.
    Outputs:
        bool - True when the word stands in the entry between non-word characters.
    """
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", entry) is not None


def _verdict(ok: bool, reason: str, kind: Optional[str], image_tokens: Optional[int], answer: Any,
             expected: dict, found: List[str], missing: List[str]) -> dict:
    """
    Purpose: Build the verdict record with every field the file and the printed line carry.
    Inputs:
        ok: bool - the verdict.
        reason: str - one sentence saying why.
        kind: str | None - the error kind of a failed model call, else None.
        image_tokens: int | None - the measured cost of the image.
        answer: Any - the model answer, kept in the record for the caller only.
        expected: dict - the expected values.
        found: list[str] - expected words found in the text the model read.
        missing: list[str] - expected words not found.
    Outputs:
        dict - ok, reason, kind, image_tokens, figure_kind, expected_words, found_words, missing_words, answers.
    """
    figure_kind = answer.get("figure_kind") if isinstance(answer, dict) else None
    return {"ok": ok, "reason": reason, "kind": kind, "image_tokens": image_tokens,
            "figure_kind": figure_kind if isinstance(figure_kind, str) else None,
            "expected_words": list(expected.get("words", [])), "found_words": found, "missing_words": missing,
            "answers": answer}


def _judge(answer: Any, expected: dict, min_share: float) -> Tuple[bool, str, List[str], List[str]]:
    """
    Purpose: Compare the model answer with what the figure is known to show.
    Inputs:
        answer: Any - the model answer: figure_kind and visible_text.
        expected: dict - `words` (list of text printed on the figure) and an optional `kind`.
        min_share: float - the share of expected words that must be found (config key vision.min_word_share).
    Outputs:
        tuple - (ok, reason, found words, missing words).
    """
    words = [str(word) for word in expected.get("words", [])]
    if not isinstance(answer, dict) or not isinstance(answer.get("figure_kind"), str) \
            or not isinstance(answer.get("visible_text"), list):
        return False, "the answer has no figure_kind or no visible_text list", [], words
    seen = [_spaced(str(entry)) for entry in answer["visible_text"]]
    found = [word for word in words if any(_contains_word(entry, _spaced(word)) for entry in seen)]
    missing = [word for word in words if word not in found]
    wanted = expected.get("kind")
    if wanted and _normalize_text(str(wanted)) != _normalize_text(answer["figure_kind"]):
        return False, "expected the kind %s, the model said %s" % (wanted, answer["figure_kind"]), found, missing
    share = len(found) / len(words) if words else 0.0
    if share < min_share:
        return (False, "found %d of %d expected words, %.2f of them is needed; missing: %s"
                % (len(found), len(words), min_share, ", ".join(missing)), found, missing)
    return True, "the model read %d of %d expected words and named the kind %s" % (
        len(found), len(words), answer["figure_kind"]), found, missing


def probe(
    call_usage: Callable[..., Tuple[Dict, Dict]],
    image: Path,
    expected: dict,
    prompt: str,
    schema: dict,
    min_share: float = 1.0
) -> dict:
    """
    Purpose: Probe the vision model: does it read the figure, and what does the image cost in tokens.
    Inputs:
        call_usage: Callable - Function to call the model and return (answer, usage).
        image: Path - Path to the image file.
        expected: dict - `words` and an optional `kind`.
        prompt: str - The prompt text.
        schema: dict - The JSON schema for the answer.
        min_share: float - the share of expected words that must be found.
    Outputs:
        dict - the verdict record of `_verdict`. A failed model call gives ok false with its kind and a reason.
    """
    try:
        answer, usage_with = call_usage(prompt, schema, [str(image)])
    except NotRun as error:
        return _verdict(False, "the model call did not run: %s (%s)" % (error.kind, error.reason), error.kind,
                        None, None, expected, [], [str(w) for w in expected.get("words", [])])
    except Exception as error:
        return _verdict(False, "the model call failed: %s" % error.__class__.__name__, "unreachable", None, None,
                        expected, [], [str(w) for w in expected.get("words", [])])
    ok, reason, found, missing = _judge(answer, expected, min_share)
    image_tokens = None
    try:
        _, usage_without = call_usage(prompt, schema, None)
        if usage_with.get("prompt_tokens") is not None and usage_without.get("prompt_tokens") is not None:
            image_tokens = usage_with["prompt_tokens"] - usage_without["prompt_tokens"]
        else:
            reason += "; the daemon did not report the prompt token count, so the image cost is unknown"
    except Exception:
        reason += "; the image cost could not be measured"
    return _verdict(ok, reason, None, image_tokens, answer, expected, found, missing)


def main(argv: Optional[List[str]] = None, *, call_usage: Optional[Callable] = None) -> int:
    """
    Purpose: Run the vision probe, write the verdict file and print the verdict as one JSON line.
    Inputs:
        argv: Optional[List[str]] - Command line arguments.
        call_usage: Optional[Callable] - Injected call function.
    Outputs:
        int - Exit code: 0 a verdict was written (ok or not), 2 a refusal, 1 the file could not be written.
    """
    parser = argparse.ArgumentParser(description="Vision probe")
    parser.add_argument("--work", required=True, help="Work directory")
    parser.add_argument("--image", required=True, help="Image file path")
    parser.add_argument("--expected", required=True, help="Expected values JSON file: words and an optional kind")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output")
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility: the line is always printed")

    args = parser.parse_args(argv)

    work_dir = Path(args.work).resolve()
    image_path = Path(args.image).resolve()
    expected_path = Path(args.expected).resolve()

    # R24: confine every path derived from input
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
    words = expected.get("words") if isinstance(expected, dict) else None
    if not isinstance(words, list) or not words or not all(isinstance(word, str) and word.strip() for word in words):
        print("Error: the expected file needs a non-empty list of strings under the key words", file=sys.stderr)
        return 2

    # Flat dotted keys, every value read from the file (R0), a missing key refused by name (R3)
    try:
        config = load_config(default_path())
        min_share = config["vision.min_word_share"]
    except Exception as e:
        print(f"Error: failed to load config: {e}", file=sys.stderr)
        return 2
    if isinstance(min_share, bool) or not isinstance(min_share, (int, float)) or not 0 < min_share <= 1:
        print("Error: vision.min_word_share must be a number above 0 and at most 1", file=sys.stderr)
        return 2

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

    result = probe(call_usage, image_path, expected, prompt_text, schema, min_share)
    output = {key: result[key] for key in ("ok", "reason", "image_tokens", "kind", "figure_kind",
                                           "expected_words", "found_words", "missing_words")}

    out_path = work_dir / "vision_probe.json"
    try:
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"Error: failed to write output: {e}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
