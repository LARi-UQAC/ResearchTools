"""
pdf2md_vlmcheck - Stage 7c of the pdf2md pipeline: a vision model reads a
rendered PDF page and checks that the formulas of the page are present, and
say the same thing, in the markdown pdf2md produced for that page.

Why a vision model and not a text comparison: formulas are exactly what the
text reader of pdf2md_fidelity cannot compare (it renders math as italic
fragments), and they are where a mineru conversion is most likely to be
wrong. The page IMAGE is the ground truth, and the model is asked one
narrow question about it, with the markdown beside it.

What the model is asked is a verification, not a count. An earlier version
asked it to count equations, tables and sections on a single page and
compared the answer to nothing, which could neither confirm nor refute a
chapter-level defect, and accepted an empty `{}` as a success. This version:

- selects the pages most worth checking (the richest in math symbols, among
  those whose prose can be located in the output, so there is a markdown
  excerpt to show),
- shows the model the page and that excerpt,
- forces the answer into a JSON schema and VALIDATES it: a reply that does
  not fit the schema is an error row, never a pass, and an empty formula
  list on a page chosen for its formulas is reported as its own status,
- turns reasoning off and bounds the context (see pdf2md-vlmcheck.json for
  why: the model reasons by default and carries a 262144-token context).

The model tag is named by the operator (R2): this module never names one.
Every network and render effect is injectable, so the offline suite touches
no model, no PDF and no network.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pdf2md_fidelity

_CONFIG_PATH = Path(__file__).with_name("pdf2md-vlmcheck.json")
_CONFIG_KEYS = (
    "base_url",
    "timeout_s",
    "dpi",
    "num_ctx",
    "think",
    "temperature",
    "seed",
    "pages_per_chapter",
    "excerpt_margin_lines",
    "max_markdown_chars",
    "max_formulas",
)

STATUS_OK = "ok"
STATUS_NO_FORMULA = "no_formula_reported"
STATUS_ERROR = "error"

KIND_MISSING = "formula_missing_in_markdown"
KIND_DIFFERS = "formula_differs"


class VlmAnswerError(ValueError):
    """The model's reply is not JSON, or does not fit the requested schema."""


@dataclass(frozen=True)
class PageChoice:
    """A page picked for the check: 0-based page index and the output lines that hold its prose."""

    page_index: int
    output_lines: tuple[int, int]


def load_vlmcheck_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read this module's settings from pdf2md-vlmcheck.json (R0), each key
        carrying a {"value", "provenance"} pair (R4).

    Inputs:
        path (Path): where the config lives; overridable for tests.

    Outputs:
        dict: key -> value for every key in _CONFIG_KEYS.

    Raises:
        FileNotFoundError: the config file is absent.
        KeyError: a required key is missing (R3: the key is named).
        ValueError: base_url is not an http(s) URL on a loopback host: the
            page images and the thesis text are sent to it, so it must be the
            machine's own daemon.
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise FileNotFoundError(f"pdf2md vlmcheck config not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if key not in data]
    if missing:
        raise KeyError(f"{path} is missing required config key(s): {missing}")
    config = {key: data[key]["value"] for key in _CONFIG_KEYS}
    _require_loopback(config["base_url"], path)
    return config


def _require_loopback(url: str, source: Path) -> None:
    """Refuse a base_url that is not http(s) on localhost, 127.0.0.0/8 or ::1 (L4, PR #69 review)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    try:
        is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if parsed.scheme not in ("http", "https") or not is_loopback:
        raise ValueError(
            f"base_url {url!r} in {source} is not an http(s) URL on a loopback host; "
            "page images and thesis text are sent to it, so it must be this machine's own daemon"
        )


def answer_schema() -> dict:
    """The JSON schema the model's answer is forced into (Ollama's `format`)
    and then checked against by validate_answer."""
    return {
        "type": "object",
        "properties": {
            "formulas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "in_markdown": {"type": "boolean"},
                        "same_as_page": {"type": "boolean"},
                        "problem": {"type": "string"},
                        "markdown_latex": {"type": "string"},
                        "corrected_latex": {"type": "string"},
                    },
                    "required": ["label", "in_markdown", "same_as_page", "problem", "markdown_latex", "corrected_latex"],
                },
            }
        },
        "required": ["formulas"],
    }


def validate_answer(raw: object) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check a model answer against answer_schema and return its formula list.
        A structural check only: a reply that parses as JSON but has no
        "formulas" list, or a formula missing a key or holding a value of the
        wrong type, is refused rather than read as "no problem".

    Inputs:
        raw (object): the parsed JSON of the model's reply.

    Outputs:
        list[dict]: the formulas, each with label, in_markdown, same_as_page, problem.

    Raises:
        VlmAnswerError: the answer does not fit the schema.
    --------------------------------------------------------------------------
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("formulas"), list):
        raise VlmAnswerError(f"the answer has no 'formulas' list: {str(raw)[:200]!r}")
    types = {"label": str, "in_markdown": bool, "same_as_page": bool, "problem": str, "markdown_latex": str, "corrected_latex": str}
    for number, formula in enumerate(raw["formulas"]):
        if not isinstance(formula, dict):
            raise VlmAnswerError(f"formula {number} is not an object")
        for key, expected in types.items():
            if not isinstance(formula.get(key), expected):
                raise VlmAnswerError(f"formula {number}: key '{key}' is missing or not a {expected.__name__}")
    return raw["formulas"]


def select_pages(
    page_texts: list[str],
    page_range: tuple[int, int],
    output_text: str,
    *,
    count: int,
    math_symbol_chars: str,
    fidelity_config: dict,
) -> list[PageChoice]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pick the pages of a chapter most worth showing to the model: those
        with the most math-symbol characters, skipping any page whose prose
        cannot be located in the output (no markdown excerpt to show).

    Inputs:
        page_texts (list[str]): raw text of every PDF page.
        page_range (tuple[int, int]): 0-based inclusive pages of the chapter.
        output_text (str): the chapter's markdown.
        count (int): how many pages to return at most.
        math_symbol_chars (str): the symbol set that scores a page, shared with
            pdf2md_validate's equation heuristic (R6, one list).
        fidelity_config (dict): thresholds for pdf2md_fidelity.locate_in_output.

    Outputs:
        list[PageChoice]: at most count pages, in page order.
    --------------------------------------------------------------------------
    """
    symbols = set(math_symbol_chars)
    start, end = page_range
    scored = sorted(
        range(start, end + 1),
        key=lambda index: (-sum(1 for char in page_texts[index] if char in symbols), index),
    )
    chosen: list[PageChoice] = []
    for index in scored:
        located = pdf2md_fidelity.locate_in_output(page_texts[index], output_text, fidelity_config)
        if located is not None:
            chosen.append(PageChoice(index, located))
        if len(chosen) == count:
            break
    return sorted(chosen, key=lambda choice: choice.page_index)


def build_excerpt(output_text: str, output_lines: tuple[int, int], *, margin: int, max_chars: int) -> tuple[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The markdown shown to the model with a page: the located lines plus
        margin lines on each side (an equation next to the first or last
        located paragraph belongs to the page), cut at max_chars.

    Inputs:
        output_text (str): the chapter markdown.
        output_lines (tuple[int, int]): 1-based inclusive first and last line.
        margin (int): extra lines kept before and after, from the config.
        max_chars (int): the cut length, from the config.

    Outputs:
        (str, bool): the excerpt and whether it was truncated.
    --------------------------------------------------------------------------
    """
    lines = output_text.splitlines()
    excerpt = "\n".join(lines[max(0, output_lines[0] - 1 - margin) : output_lines[1] + margin])
    return (excerpt[:max_chars], True) if len(excerpt) > max_chars else (excerpt, False)


def build_prompt(excerpt: str, *, max_formulas: int) -> str:
    """The question sent with the page image: verify the page's formulas
    against the markdown, ignoring everything else."""
    return (
        "The image is one page of a thesis. Below is the markdown that a PDF converter produced "
        "for the text of that page, with formulas written as LaTeX between dollar signs.\n\n"
        "Look ONLY at the mathematical formulas printed on the page. Ignore text, figures and tables. "
        f"List at most {max_formulas} of them. For each formula give: label (a short description or its "
        "equation number), in_markdown (true if the markdown contains that formula), same_as_page (true if "
        "the LaTeX in the markdown says exactly what the page says, false if a symbol, index, operator or "
        "term differs or is missing), problem (what differs, or an empty string when nothing does), "
        "markdown_latex (the formula copied EXACTLY as it is written in the markdown below, character for "
        "character, or an empty string when the markdown does not contain it), and corrected_latex (the "
        "formula as the page prints it, written in LaTeX in the same style as the markdown, or an empty "
        "string when the markdown already says the same thing). "
        'Answer with JSON only, in the form {"formulas": [...]}.\n\n'
        "Markdown:\n" + excerpt
    )


def build_request_body(image_path: Path, prompt: str, *, model_tag: str, config: dict, schema: dict | None = None) -> bytes:
    """The /api/generate request: one page image, the prompt, the answer
    schema (the formula schema unless another is given), reasoning off,
    bounded context, and sampling fixed (R19)."""
    payload = {
        "model": model_tag,
        "prompt": prompt,
        "images": [base64.b64encode(image_path.read_bytes()).decode("ascii")],
        "stream": False,
        "think": config["think"],
        "format": schema if schema is not None else answer_schema(),
        "options": {"num_ctx": config["num_ctx"], "temperature": config["temperature"], "seed": config["seed"]},
    }
    return json.dumps(payload).encode("utf-8")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow any redirect (see default_caller in post_to_model)."""

    def redirect_request(self, *args, **kwargs):
        return None


_NoRedirect = _NoRedirectHandler()


def post_to_model(body: bytes, config: dict, caller: Callable[[str, bytes, float], bytes] | None = None) -> object:
    """
    --------------------------------------------------------------------------
    Purpose:
        POST one request to the local Ollama /api/generate endpoint and
        return the model's answer parsed as JSON. Shared by every question
        this skill puts to the vision model.

    Inputs:
        body (bytes): from build_request_body.
        config (dict): from load_vlmcheck_config (base_url, timeout_s).
        caller (callable | None): injected for tests, (url, body, timeout_s)
            -> raw response bytes; defaults to a urllib POST with the
            configured timeout (R10).

    Outputs:
        object: the parsed JSON of the model's answer.

    Raises:
        VlmAnswerError: the reply is not the expected JSON envelope.
        OSError: the request failed or timed out.
    --------------------------------------------------------------------------
    """
    def default_caller(url: str, data: bytes, timeout: float) -> bytes:
        import urllib.request

        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        # No proxy and no redirect: the loopback check on base_url only means something if the
        # request really goes to that host. HTTP(S)_PROXY or a 30x answer would carry the page
        # images and thesis text elsewhere.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
        with opener.open(request, timeout=timeout) as response:
            return response.read()

    caller = caller or default_caller
    raw = caller(f"{config['base_url']}/api/generate", body, config["timeout_s"])
    try:
        return json.loads(json.loads(raw)["response"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise VlmAnswerError(f"the reply is not the expected JSON envelope: {raw[:300]!r}") from exc


def ask_model(
    image_path: Path, prompt: str, *, model_tag: str, config: dict, caller: Callable[[str, bytes, float], bytes] | None = None
) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send one page and its prompt to a local Ollama vision model and
        return the validated formula list.

    Inputs:
        image_path (Path): the rendered page PNG.
        prompt (str): from build_prompt.
        model_tag (str): the operator-named Ollama tag (R2: never a default).
        config (dict): from load_vlmcheck_config.
        caller (callable | None): injected for tests, see post_to_model.

    Outputs:
        list[dict]: the validated formulas.

    Raises:
        VlmAnswerError: the reply is not JSON or does not fit the schema.
        OSError: the request failed or timed out.
    --------------------------------------------------------------------------
    """
    body = build_request_body(image_path, prompt, model_tag=model_tag, config=config)
    return validate_answer(post_to_model(body, config, caller))


def render_page(pdf_path: str, page_index: int, out_dir: Path, *, dpi: int, renderer: Callable[[str, int, int, Path], Path] | None = None) -> Path:
    """Render one 0-based PDF page to a PNG with PyMuPDF (injectable for tests)."""
    def default_renderer(path: str, index: int, render_dpi: int, directory: Path) -> Path:
        import fitz

        with fitz.open(path) as document:
            pixmap = document[index].get_pixmap(dpi=render_dpi)
            target = directory / f"page_{index + 1}.png"
            pixmap.save(str(target))
        return target

    out_dir.mkdir(parents=True, exist_ok=True)
    return (renderer or default_renderer)(pdf_path, page_index, dpi, out_dir)


def check_page(
    pdf_path: str,
    choice: PageChoice,
    output_text: str,
    *,
    model_tag: str,
    config: dict,
    scratch_dir: Path,
    renderer: Callable[[str, int, int, Path], Path] | None = None,
    caller: Callable[[str, bytes, float], bytes] | None = None,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check one page. Any failure of the render, the request or the answer
        becomes an error row, so one bad page never loses the others.

    Inputs:
        pdf_path (str): the PDF.
        choice (PageChoice): the page and its output lines.
        output_text (str): the chapter's markdown.
        model_tag (str): the operator-named Ollama tag.
        config (dict): from load_vlmcheck_config.
        scratch_dir (Path): where the page PNG is written.
        renderer, caller (callables | None): injected for tests.

    Outputs:
        dict: {page, output_lines, status, excerpt_truncated, formulas, issues}
            where status is ok, no_formula_reported or error (with "error").
    --------------------------------------------------------------------------
    """
    excerpt, truncated = build_excerpt(output_text, choice.output_lines, margin=config["excerpt_margin_lines"], max_chars=config["max_markdown_chars"])
    row: dict = {"page": choice.page_index + 1, "output_lines": list(choice.output_lines), "excerpt_truncated": truncated, "formulas": 0, "issues": []}
    try:
        image = render_page(pdf_path, choice.page_index, scratch_dir, dpi=config["dpi"], renderer=renderer)
        formulas = ask_model(image, build_prompt(excerpt, max_formulas=config["max_formulas"]), model_tag=model_tag, config=config, caller=caller)
    except (VlmAnswerError, OSError, RuntimeError, http.client.HTTPException) as exc:
        row.update(status=STATUS_ERROR, error=str(exc))
        return row
    row["formulas"] = len(formulas)
    row["status"] = STATUS_OK if formulas else STATUS_NO_FORMULA
    for formula in formulas:
        proposal = {"label": formula["label"], "detail": formula["problem"], "markdown_latex": formula["markdown_latex"], "corrected_latex": formula["corrected_latex"]}
        if not formula["in_markdown"]:
            row["issues"].append({"kind": KIND_MISSING, **proposal})
        elif not formula["same_as_page"]:
            row["issues"].append({"kind": KIND_DIFFERS, **proposal})
    return row


def run_vlm_fidelity(
    pdf_path: str,
    output_chapters: dict[int, tuple[str, str]],
    chapter_ranges: dict[int, tuple[int, int]],
    page_texts: list[str],
    *,
    model_tag: str,
    config: dict,
    math_symbol_chars: str,
    fidelity_config: dict,
    scratch_dir: Path,
    renderer: Callable[[str, int, int, Path], Path] | None = None,
    caller: Callable[[str, bytes, float], bytes] | None = None,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the formula check on the selected pages of every chapter.

    Inputs:
        pdf_path (str): the PDF.
        output_chapters (dict): chapter -> (stem, markdown), pdf2md output side.
        chapter_ranges (dict): chapter -> 0-based inclusive page range.
        page_texts (list[str]): raw text of every PDF page.
        model_tag (str): the operator-named Ollama tag.
        config, fidelity_config (dict): vlmcheck and fidelity settings.
        math_symbol_chars (str): the page-scoring symbol set.
        scratch_dir (Path): where page PNGs go.
        renderer, caller (callables | None): injected for tests.

    Outputs:
        dict: {"chapters": {"N": [row, ...]}, "issue_count": int,
            "error_count": int, "unchecked_chapters": {"N": reason}} where a
            chapter with no locatable page, or no page range, is listed
            under unchecked_chapters with its reason rather than skipped.
    --------------------------------------------------------------------------
    """
    report: dict = {"chapters": {}, "issue_count": 0, "error_count": 0, "unchecked_chapters": {}}
    for chapter in sorted(output_chapters):
        text = output_chapters[chapter][1]
        if chapter not in chapter_ranges:
            report["unchecked_chapters"][str(chapter)] = "chapter heading not found on any PDF page"
            continue
        choices = select_pages(page_texts, chapter_ranges[chapter], text, count=config["pages_per_chapter"], math_symbol_chars=math_symbol_chars, fidelity_config=fidelity_config)
        if not choices:
            report["unchecked_chapters"][str(chapter)] = "no page of the chapter could be located in the output"
            continue
        rows = [
            check_page(pdf_path, choice, text, model_tag=model_tag, config=config, scratch_dir=scratch_dir / f"chapter_{chapter}", renderer=renderer, caller=caller)
            for choice in choices
        ]
        report["chapters"][str(chapter)] = rows
        report["issue_count"] += sum(len(row["issues"]) for row in rows)
        report["error_count"] += sum(1 for row in rows if row["status"] == STATUS_ERROR)
    return report


def render_vlm_md(report: dict) -> str:
    """Render a run_vlm_fidelity report as one table row per checked page."""
    lines = [f"Formula check (vision model): {report['issue_count']} formula issue(s), {report['error_count']} page(s) that could not be checked", ""]
    lines += ["| Chapter | Page | Output lines | Status | Formulas | Issue |", "|---|---|---|---|---|---|"]
    for chapter, rows in report["chapters"].items():
        for row in rows:
            issues = "; ".join(f"{i['kind']}: {i['label']} - {i['detail']}" for i in row["issues"]) or row.get("error", "")
            lines.append(f"| {chapter} | {row['page']} | {row['output_lines'][0]}-{row['output_lines'][1]} | {row['status']} | {row['formulas']} | {issues.replace('|', '/')} |")
    for chapter, reason in report["unchecked_chapters"].items():
        lines.append(f"| {chapter} | - | - | unchecked | 0 | {reason} |")
    return "\n".join(lines)
