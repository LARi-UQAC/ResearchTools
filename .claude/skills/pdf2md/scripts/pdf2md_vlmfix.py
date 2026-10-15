"""
pdf2md_vlmfix - Stage 7e of the pdf2md pipeline: let the local vision model
CORRECT what it finds, inside a loop that is bounded and that stops when the
error is low enough.

Stage 7c (pdf2md_vlmcheck) only reports. This stage acts on two things a
vision model can do and Python cannot, and refuses everything else:

1. A numbered equation the conversion lost (the numbering has a gap, for
   example (4.5) between (4.4) and (4.6)). The model reads the page image,
   transcribes the equation and names the paragraph it follows. The result is
   inserted with an HTML comment saying it was transcribed by a model.
2. A formula the markdown writes differently from the page (a lost index, a
   wrong symbol). The model returns the markdown formula verbatim and its
   corrected form; the replacement is applied only when the verbatim formula
   occurs exactly once, the correction passes a syntax and length check, and a
   second look at the page by the model does not still report it wrong.

What it does NOT do: insert a formula the model reports missing without a
numbering gap to anchor it (the position is unknown), or touch prose. Those
are listed for a person.

The loop (run_correction_loop): equation gaps, then the formula check, then
the fidelity errors of the deterministic checks are added to the formulas the
model still reports; the loop stops when that remainder is at most
target_remaining_issues, when a round did not lower it, or after max_rounds.

Everything the model changed is written to assets/vlm_changes.json with its
page and its before and after, so a person can check each against the PDF.
A dry run by default (R16); --yes writes, after copying each original once.
The model tag is the operator's (R2). Every network and render effect is
injectable, so the offline suite touches no model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import pdf2md_fidelity as fidelity
import pdf2md_vlmcheck as vlmcheck

_CONFIG_PATH = Path(__file__).with_name("pdf2md-vlmfix.json")
_CONFIG_KEYS = (
    "max_rounds",
    "target_remaining_issues",
    "gap_pages_tried",
    "gap_margin_lines",
    "candidate_paragraph_chars",
    "max_candidates",
    "max_length_ratio",
    "max_latex_chars",
    "verify_corrections",
    "changes_file",
)

KIND_EQUATION_INSERTED = "equation_inserted"
KIND_FORMULA_CORRECTED = "formula_corrected"


def load_vlmfix_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read this module's settings from pdf2md-vlmfix.json (R0), each key
        carrying a {"value", "provenance"} pair (R4).

    Inputs:
        path (Path): where the config lives; overridable for tests.

    Outputs:
        dict: key -> value for every key in _CONFIG_KEYS.

    Raises:
        FileNotFoundError: the config file is absent.
        KeyError: a required key is missing (R3: the key is named).
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise FileNotFoundError(f"pdf2md vlmfix config not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if key not in data]
    if missing:
        raise KeyError(f"{path} is missing required config key(s): {missing}")
    return {key: data[key]["value"] for key in _CONFIG_KEYS}


# --------------------------------------------------------------------------- #
# What a proposed formula must satisfy before it is allowed into the text.
# --------------------------------------------------------------------------- #


def latex_is_sane(latex: str, config: dict) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        A syntax gate for a formula the model wrote: non-empty, not a runaway
        generation, no stray dollar sign, braces balanced, and as many
        \\right as \\left and \\end as \\begin. It cannot tell a right formula
        from a wrong one, only an obviously broken one from a plausible one.

    Inputs:
        latex (str): the proposed formula, without dollar signs.
        config (dict): from load_vlmfix_config (max_latex_chars).

    Outputs:
        bool: True when the formula passes.
    --------------------------------------------------------------------------
    """
    if not latex.strip() or len(latex) > config["max_latex_chars"] or "$" in latex:
        return False
    depth = 0
    for match in re.finditer(r"(?<!\\)[{}]", latex):
        depth += 1 if match.group(0) == "{" else -1
        if depth < 0:
            return False
    return depth == 0 and latex.count("\\left") == latex.count("\\right") and latex.count("\\begin") == latex.count("\\end")


def apply_formula_corrections(text: str, issues: list[dict], config: dict) -> tuple[str, list[dict], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace, in a chapter, each formula the model reports as differing
        from the page by the correction it proposed, when it is safe to.

    Details:
        A correction is applied only when the formula the model quoted occurs
        EXACTLY once in the text (a quote that is not verbatim, or that is
        ambiguous, is skipped), the correction differs from it, passes
        latex_is_sane, and is between 1/max_length_ratio and max_length_ratio
        times as long. Otherwise the issue is returned as skipped, with the
        reason, for a person.

    Inputs:
        text (str): the chapter markdown.
        issues (list[dict]): the formula_differs issues of one or more pages
            (kind, label, detail, markdown_latex, corrected_latex).
        config (dict): from load_vlmfix_config.

    Outputs:
        (str, list[dict], list[dict]): the new text, the corrections applied
            ({label, before, after}) and the issues skipped ({label, reason}).
    --------------------------------------------------------------------------
    """
    applied: list[dict] = []
    skipped: list[dict] = []
    for issue in issues:
        before, after = issue["markdown_latex"].strip(), issue["corrected_latex"].strip()
        reason = None
        if not before or not after:
            reason = "the model gave no formula or no correction"
        elif before == after:
            reason = "the correction equals the formula"
        elif text.count(before) == 0:
            reason = "the quoted formula is not in the text verbatim"
        elif text.count(before) > 1:
            reason = "the quoted formula occurs more than once"
        elif not latex_is_sane(after, config):
            reason = "the correction fails the syntax check"
        elif not (1 / config["max_length_ratio"] <= len(after) / len(before) <= config["max_length_ratio"]):
            reason = "the correction is much longer or shorter than the formula"
        if reason:
            skipped.append({"label": issue["label"], "reason": reason})
            continue
        text = text.replace(before, after, 1)
        applied.append({"label": issue["label"], "before": before, "after": after})
    return text, applied, skipped


# --------------------------------------------------------------------------- #
# A numbered equation the conversion lost.
# --------------------------------------------------------------------------- #


def equation_schema() -> dict:
    """The JSON schema of the answer to 'transcribe equation (N.M)'."""
    return {
        "type": "object",
        "properties": {
            "found": {"type": "boolean"},
            "latex": {"type": "string"},
            "after_paragraph": {"type": "integer"},
        },
        "required": ["found", "latex", "after_paragraph"],
    }


def build_equation_prompt(label: str, candidates: list[str]) -> str:
    """The question sent with the page image: transcribe the equation printed
    with this number and say which listed paragraph it follows."""
    listing = "\n".join(f"{index}: {text}" for index, text in enumerate(candidates))
    return (
        f"The image is one page of a thesis. Find the display equation printed with the number ({label}) on this page, "
        "possibly inside a footnote. Transcribe the COMPLETE display from its first symbol to its last, including every "
        "equality sign of a chain (a = b = c), not only its last part. Answer with JSON only: found (true if the page prints it), latex (the equation "
        "written in LaTeX WITHOUT its number and without dollar signs, empty if not found), and after_paragraph "
        "(the number of the paragraph in the list below that comes IMMEDIATELY BEFORE the equation in reading order, "
        "or -1 if you cannot tell).\n\nParagraphs of the converted text:\n" + listing
    )


def validate_equation_answer(raw: object, candidate_count: int) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check the model's answer to the equation question against its schema
        and against the list it was given.

    Inputs:
        raw (object): the parsed JSON of the answer.
        candidate_count (int): how many paragraphs were listed.

    Outputs:
        dict: {"found": bool, "latex": str, "after_paragraph": int}.

    Raises:
        vlmcheck.VlmAnswerError: a key is missing or mistyped, or
            after_paragraph is outside the list (and not -1).
    --------------------------------------------------------------------------
    """
    if not isinstance(raw, dict):
        raise vlmcheck.VlmAnswerError(f"the answer is not an object: {str(raw)[:200]!r}")
    for key, expected in (("found", bool), ("latex", str), ("after_paragraph", int)):
        value = raw.get(key)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise vlmcheck.VlmAnswerError(f"key '{key}' is missing or not a {expected.__name__}")
    if not -1 <= raw["after_paragraph"] < candidate_count:
        raise vlmcheck.VlmAnswerError(f"after_paragraph {raw['after_paragraph']} is outside the {candidate_count} listed paragraphs")
    return raw


def ask_equation(
    image_path: Path, label: str, candidates: list[str], *, model_tag: str, vlm_config: dict, caller: Callable[[str, bytes, float], bytes] | None = None
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put the equation question to the local vision model and return its
        validated answer.

    Inputs:
        image_path (Path): the rendered page.
        label (str): the equation number, for example "4.5".
        candidates (list[str]): the paragraphs offered as the place to insert.
        model_tag (str): the operator-named Ollama tag (R2).
        vlm_config (dict): from vlmcheck.load_vlmcheck_config.
        caller (callable | None): injected for tests.

    Outputs:
        dict: see validate_equation_answer.

    Raises:
        vlmcheck.VlmAnswerError: the reply does not fit the schema.
        OSError: the request failed or timed out.
    --------------------------------------------------------------------------
    """
    body = vlmcheck.build_request_body(image_path, build_equation_prompt(label, candidates), model_tag=model_tag, config=vlm_config, schema=equation_schema())
    return validate_equation_answer(vlmcheck.post_to_model(body, vlm_config, caller), len(candidates))


def locate_pages(page_texts: list[str], page_range: tuple[int, int], text: str, fidelity_config: dict) -> dict[int, tuple[int, int]]:
    """For each PDF page of a chapter, the output lines that hold its prose
    (pdf2md_fidelity.locate_in_output); a page that cannot be located is absent."""
    located = {}
    for index in range(page_range[0], page_range[1] + 1):
        lines = fidelity.locate_in_output(page_texts[index], text, fidelity_config)
        if lines is not None:
            located[index] = lines
    return located


def gap_candidates(text: str, gap_lines: tuple[int, int], page_lines: list[tuple[int, int]], config: dict) -> list[fidelity.Paragraph]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The paragraphs offered to the model as the place a lost equation
        follows: those within gap_margin_lines of the gap and those the located
        pages hold, nearest to the gap first, at most max_candidates, returned
        in document order.

    Details:
        Measured on the real thesis: equation (4.5) sits in a footnote that
        mineru wrote 30 lines from equations (4.4) and (4.6), so the gap alone
        is not enough and the located pages are added.

    Inputs:
        text (str): the chapter markdown.
        gap_lines (tuple[int, int]): lines of the equations either side of the gap.
        page_lines (list[tuple[int, int]]): output line ranges of the candidate pages.
        config (dict): from load_vlmfix_config.

    Outputs:
        list[Paragraph]: the candidates, in document order.
    --------------------------------------------------------------------------
    """
    margin = config["gap_margin_lines"]
    low, high = gap_lines[0] - margin, gap_lines[1] + margin
    centre = (gap_lines[0] + gap_lines[1]) / 2
    chosen = [
        paragraph
        for paragraph in fidelity.split_paragraphs(text)
        if low <= paragraph.line <= high or any(start <= paragraph.line <= end for start, end in page_lines)
    ]
    chosen.sort(key=lambda paragraph: abs(paragraph.line - centre))
    return sorted(chosen[: config["max_candidates"]], key=lambda paragraph: paragraph.line)


def insert_equation(text: str, after_line: int, latex: str, label: str, *, page: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Insert a transcribed equation after a given line, written like the
        other numbered equations of the chapter and preceded by an HTML
        comment that says a model transcribed it from this page, so a reader
        of the markdown knows to check it.

    Inputs:
        text (str): the chapter markdown.
        after_line (int): 1-based line after which the equation goes.
        latex (str): the equation without its number.
        label (str): the equation number, for example "4.5".
        page (int): the 1-based PDF page it was read from.

    Outputs:
        str: the new text.
    --------------------------------------------------------------------------
    """
    lines = text.split("\n")
    block = ["", f"<!-- pdf2md: equation ({label}) transcribed by a vision model from PDF page {page}; check it against the PDF -->", "$$", f"{latex.strip()} \\tag {{{label}}}", "$$"]
    if after_line < len(lines) and lines[after_line].strip():
        block.append("")
    lines[after_line:after_line] = block
    return "\n".join(lines)


def replace_orphan_number(text: str, label: str, latex: str, *, page: int) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        When mineru kept an equation's number as a lone text line "(4.5)" but
        lost the equation itself, put the transcription exactly where that
        number stands, so no placement has to be guessed.

    Details:
        Measured on the real thesis: equation (4.5) sat inside a page footnote,
        and the converted text kept only the line "(4.5)" after the sentence
        "The i-th row of ... is".

    Inputs:
        text (str): the chapter markdown.
        label (str): the equation number, for example "4.5".
        latex (str): the transcribed equation without its number.
        page (int): the 1-based PDF page it was read from.

    Outputs:
        str | None: the new text, or None when the chapter holds no line that
            is exactly the number, or holds it more than once (ambiguous).
    --------------------------------------------------------------------------
    """
    lines = text.split("\n")
    matches = [i for i, line in enumerate(lines) if line.strip() == f"({label})"]
    if len(matches) != 1:
        return None
    block = [f"<!-- pdf2md: equation ({label}) transcribed by a vision model from PDF page {page}; check it against the PDF -->", "$$", f"{latex.strip()} \\tag {{{label}}}", "$$"]
    lines[matches[0] : matches[0] + 1] = block
    return "\n".join(lines)


def _short(paragraph: fidelity.Paragraph, chars: int) -> str:
    text = " ".join(paragraph.text.split())
    return text if len(text) <= 2 * chars else f"{text[:chars]} ... {text[-chars:]}"


def fix_equation_gaps(
    chapter: int,
    text: str,
    *,
    pdf_path: str,
    page_texts: list[str],
    page_range: tuple[int, int],
    model_tag: str,
    vlm_config: dict,
    fidelity_config: dict,
    config: dict,
    scratch_dir: Path,
    renderer: Callable[[str, int, int, Path], Path] | None = None,
    caller: Callable[[str, bytes, float], bytes] | None = None,
) -> tuple[str, list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Recover the numbered equations the conversion lost, one gap at a time,
        lowest number first (an insertion moves the lines of the next gap, so
        positions are recomputed after each).

    Details:
        For a gap (p, n): the candidate pages are those whose prose lies
        nearest equations (p, n-1) and (p, n+1); the model reads each in turn
        (at most gap_pages_tried) and the first page that prints the equation
        wins. A transcription that fails latex_is_sane, a page that does not
        print it, or an anchor the model could not name leaves the gap in the
        report as needs_review with the reason, and the text untouched.

    Inputs:
        chapter (int): chapter number, for the records.
        text (str): the chapter markdown.
        pdf_path (str): the PDF.
        page_texts (list[str]): raw text of every PDF page.
        page_range (tuple[int, int]): the chapter's 0-based inclusive pages.
        model_tag (str): the operator-named Ollama tag.
        vlm_config, fidelity_config, config (dict): the three configurations.
        scratch_dir (Path): where page images are written.
        renderer, caller (callables | None): injected for tests.

    Outputs:
        (str, list[dict]): the new text, and one record per gap with kind
            "equation_inserted" or "needs_review" (chapter, label, page,
            after, reason).
    --------------------------------------------------------------------------
    """
    records: list[dict] = []
    for prefix, index in fidelity.equation_gaps(text):
        label = f"{prefix}.{index}"
        numbered = {number: line for number, line, _form in fidelity.equation_numbers(text)}
        below, above = numbered.get((prefix, index - 1)), numbered.get((prefix, index + 1))
        gap_lines = (below if below is not None else 1, above if above is not None else len(text.splitlines()))
        located = locate_pages(page_texts, page_range, text, fidelity_config)
        centre = (gap_lines[0] + gap_lines[1]) / 2
        pages = sorted(located, key=lambda page: abs((located[page][0] + located[page][1]) / 2 - centre))[: config["gap_pages_tried"]]
        record = {"chapter": chapter, "label": label, "kind": "needs_review", "page": None, "reason": "no page of the chapter could be located near the gap"}
        for page in pages:
            candidates = gap_candidates(text, gap_lines, [located[page]], config)
            if not candidates:
                continue
            try:
                image = vlmcheck.render_page(pdf_path, page, scratch_dir, dpi=vlm_config["dpi"], renderer=renderer)
                answer = ask_equation(image, label, [_short(p, config["candidate_paragraph_chars"]) for p in candidates], model_tag=model_tag, vlm_config=vlm_config, caller=caller)
            except (vlmcheck.VlmAnswerError, OSError, RuntimeError) as exc:
                record.update(page=page + 1, reason=f"the model call failed: {exc}")
                continue
            if not answer["found"]:
                record.update(page=page + 1, reason="the model does not see the equation on this page")
                continue
            if not latex_is_sane(answer["latex"], config):
                record.update(page=page + 1, reason="the transcription fails the syntax check", proposed=answer["latex"][: config["max_latex_chars"]])
                continue
            replaced = replace_orphan_number(text, label, answer["latex"], page=page + 1)
            if replaced is not None:
                text = replaced
                record = {"chapter": chapter, "label": label, "kind": KIND_EQUATION_INSERTED, "page": page + 1, "after": f"(orphan number line ({label}))", "latex": answer["latex"].strip()}
                break
            if answer["after_paragraph"] < 0:
                record.update(page=page + 1, reason="the model could not say which paragraph the equation follows", proposed=answer["latex"])
                continue
            anchor = candidates[answer["after_paragraph"]]
            text = insert_equation(text, anchor.end, answer["latex"], label, page=page + 1)
            record = {"chapter": chapter, "label": label, "kind": KIND_EQUATION_INSERTED, "page": page + 1, "after": anchor.text[:80], "latex": answer["latex"].strip()}
            break
        records.append(record)
    return text, records


# --------------------------------------------------------------------------- #
# The loop.
# --------------------------------------------------------------------------- #


def _count_unresolved(report: dict, resolved_labels: set[tuple[int, str]]) -> int:
    """Formula issues the model still reports and that no correction resolved."""
    total = 0
    for chapter, rows in report["chapters"].items():
        for row in rows:
            total += sum(1 for issue in row["issues"] if (int(chapter), issue["label"]) not in resolved_labels)
            total += 1 if row["status"] == vlmcheck.STATUS_ERROR else 0
    return total


def run_correction_loop(
    *,
    pdf_path: str,
    chapters: dict[int, tuple[str, str]],
    pdf_chapters: dict[int, tuple[str, str]],
    chapter_ranges: dict[int, tuple[int, int]],
    page_texts: list[str],
    model_tag: str,
    vlm_config: dict,
    fidelity_config: dict,
    config: dict,
    math_symbol_chars: str,
    scratch_dir: Path,
    all_pages: bool = False,
    equations_only: bool = False,
    renderer: Callable[[str, int, int, Path], Path] | None = None,
    caller: Callable[[str, bytes, float], bytes] | None = None,
    on_round: Callable[[int, dict[int, str], list[dict]], None] | None = None,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the bounded correction loop: each round recovers lost numbered
        equations, checks formulas on the pages, corrects the ones the model
        reports as wrong and verifies each correction by showing the page
        again, then counts what remains.

    Details:
        remaining = the deterministic fidelity errors + the formula issues the
        model still reports that no correction resolved + the pages it could
        not check. The loop stops when remaining <= target_remaining_issues
        ("target reached"), when a round did not lower it ("no progress"), or
        after max_rounds ("round limit"). A round with no model change also
        stops it, since the next round would be identical (R19).

    Inputs:
        pdf_path (str): the PDF.
        chapters (dict): chapter -> (stem, markdown), the output side.
        pdf_chapters (dict): chapter -> (title, text), the PDF reader's side.
        chapter_ranges (dict): chapter -> 0-based inclusive PDF page range.
        page_texts (list[str]): raw text of every PDF page.
        model_tag (str): the operator-named Ollama tag (R2).
        vlm_config, fidelity_config, config (dict): the three configurations.
        math_symbol_chars (str): the page-scoring symbol set.
        scratch_dir (Path): where page images are written.
        all_pages (bool): check every page that can be located, not only the
            pages_per_chapter richest in math (the overnight setting).
        equations_only (bool): recover lost numbered equations and stop after
            one round; no formula is checked or rewritten.
        renderer, caller (callables | None): injected for tests.
        on_round (callable | None): called after each round with (round,
            texts, changes), to persist progress.

    Outputs:
        dict: {"texts": chapter -> markdown, "changes": [...], "needs_review":
            [...], "history": [{round, remaining, fidelity_errors,
            formula_issues}], "stopped": reason, "remaining": int}.
    --------------------------------------------------------------------------
    """
    texts = {number: text for number, (_stem, text) in chapters.items()}
    stems = {number: stem for number, (stem, _text) in chapters.items()}
    changes: list[dict] = []
    needs_review: list[dict] = []
    history: list[dict] = []
    previous: int | None = None
    stopped = "round limit"
    check_config = {**vlm_config, "pages_per_chapter": len(page_texts)} if all_pages else vlm_config

    for round_number in range(1, config["max_rounds"] + 1):
        round_changes = 0
        for number in sorted(texts):
            if number not in chapter_ranges:
                continue
            texts[number], records = fix_equation_gaps(
                number, texts[number], pdf_path=pdf_path, page_texts=page_texts, page_range=chapter_ranges[number], model_tag=model_tag,
                vlm_config=vlm_config, fidelity_config=fidelity_config, config=config, scratch_dir=scratch_dir / "gaps", renderer=renderer, caller=caller,
            )
            for record in records:
                (changes if record["kind"] == KIND_EQUATION_INSERTED else needs_review).append(record)
                round_changes += record["kind"] == KIND_EQUATION_INSERTED

        if equations_only:
            # Lost equations only: no formula is checked or rewritten, so the model
            # can never change the meaning of a formula the conversion got right.
            fidelity_errors = fidelity.check_chapters(pdf_chapters, {number: (stems[number], texts[number]) for number in texts}, fidelity_config)["error_count"]
            history.append({"round": round_number, "remaining": fidelity_errors, "fidelity_errors": fidelity_errors, "formula_issues": 0, "changes": round_changes})
            if on_round is not None:
                on_round(round_number, dict(texts), list(changes))
            stopped = "target reached" if fidelity_errors <= config["target_remaining_issues"] else "no change"
            break
        report = vlmcheck.run_vlm_fidelity(
            pdf_path, {number: (stems[number], texts[number]) for number in texts}, chapter_ranges, page_texts, model_tag=model_tag, config=check_config,
            math_symbol_chars=math_symbol_chars, fidelity_config=fidelity_config, scratch_dir=scratch_dir / "check", renderer=renderer, caller=caller,
        )
        resolved: set[tuple[int, str]] = set()
        for chapter_key, rows in report["chapters"].items():
            number = int(chapter_key)
            for row in rows:
                differing = [issue for issue in row["issues"] if issue["kind"] == vlmcheck.KIND_DIFFERS]
                new_text, applied, skipped = apply_formula_corrections(texts[number], differing, config)
                needs_review += [{"chapter": number, "page": row["page"], "kind": "needs_review", **item} for item in skipped]
                if not applied:
                    continue
                if config["verify_corrections"]:
                    again = vlmcheck.check_page(
                        pdf_path, vlmcheck.PageChoice(row["page"] - 1, tuple(row["output_lines"])), new_text, model_tag=model_tag, config=vlm_config,
                        scratch_dir=scratch_dir / "verify", renderer=renderer, caller=caller,
                    )
                    still_wrong = {issue["markdown_latex"].strip() for issue in again["issues"] if issue["kind"] == vlmcheck.KIND_DIFFERS}
                    failed_check = again["status"] == vlmcheck.STATUS_ERROR
                    for item in list(applied):
                        if failed_check or item["after"] in still_wrong:
                            new_text = new_text.replace(item["after"], item["before"], 1)
                            applied.remove(item)
                            needs_review.append({"chapter": number, "page": row["page"], "kind": "needs_review", "label": item["label"], "reason": "the model still reports the corrected formula as wrong" if not failed_check else "the verification could not be done"})
                texts[number] = new_text
                for item in applied:
                    resolved.add((number, item["label"]))
                    changes.append({"chapter": number, "page": row["page"], "kind": KIND_FORMULA_CORRECTED, **item})
                    round_changes += 1

        fidelity_errors = fidelity.check_chapters(pdf_chapters, {number: (stems[number], texts[number]) for number in texts}, fidelity_config)["error_count"]
        formula_issues = _count_unresolved(report, resolved)
        remaining = fidelity_errors + formula_issues
        history.append({"round": round_number, "remaining": remaining, "fidelity_errors": fidelity_errors, "formula_issues": formula_issues, "changes": round_changes})
        if on_round is not None:
            on_round(round_number, dict(texts), list(changes))
        if remaining <= config["target_remaining_issues"]:
            stopped = "target reached"
            break
        if round_changes == 0:
            stopped = "no change"
            break
        if previous is not None and remaining >= previous:
            stopped = "no progress"
            break
        previous = remaining

    return {"texts": texts, "changes": changes, "needs_review": needs_review, "history": history, "stopped": stopped, "remaining": history[-1]["remaining"] if history else 0}


# --------------------------------------------------------------------------- #
# Command line.
# --------------------------------------------------------------------------- #


def _write_changes_file(path: Path, changes: list[dict], needs_review: list[dict]) -> None:
    """Merge this run's changes into assets/vlm_changes.json (written atomically)."""
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"changes": [], "needs_review": []}
    known = {(c["chapter"], c["kind"], c.get("label")) for c in previous["changes"]}
    previous["changes"] += [c for c in changes if (c["chapter"], c["kind"], c.get("label")) not in known]
    previous["needs_review"] = needs_review
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(previous, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _render(summary: dict) -> str:
    """Human text for a loop result: the rounds, what changed, what needs a person."""
    state = "(applied)" if summary["applied"] else "(dry run, nothing written)"
    lines = [f"Correction loop {state}: stopped on '{summary['stopped']}', {summary['remaining']} issue(s) remaining", ""]
    lines += ["| Round | Remaining | Fidelity errors | Formula issues | Model changes |", "|---|---|---|---|---|"]
    lines += [f"| {h['round']} | {h['remaining']} | {h['fidelity_errors']} | {h['formula_issues']} | {h['changes']} |" for h in summary["history"]]
    lines += ["", f"Changes made by the model: {len(summary['changes'])}"]
    lines += [f"- chapter {c['chapter']}, page {c['page']}: {c['kind']} {c.get('label', '')}" for c in summary["changes"]]
    lines += ["", f"Left for a person: {len(summary['needs_review'])}"]
    lines += [f"- chapter {r['chapter']}, {r.get('label', '')}: {r.get('reason', '')}" for r in summary["needs_review"]]
    return "\n".join(lines)


def _build_parser():
    """The `pdf2md.py fix` command line. Rewriting formulas is opt-in (--rewrite-formulas), never the default."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--model", default=None, help="REQUIRED: the operator's own Ollama vision tag (R2 -- never a default)")
    parser.add_argument("--pages", choices=("config", "all"), default="config", help="'all' checks every page that can be located (the overnight setting)")
    parser.add_argument("--equations-only", action="store_true", help="the DEFAULT, kept so older command lines still run: recover lost numbered equations only, never check or rewrite a formula")
    parser.add_argument("--rewrite-formulas", action="store_true", help="also check every formula against the page and rewrite the ones the model disputes (measured 2026-10-11: a model changed the meaning of a correct formula, so every rewrite needs a human read)")
    parser.add_argument("--yes", action="store_true", help="write the corrections (default: a dry run that writes nothing)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when the loop stops with more than target_remaining_issues left")
    parser.add_argument("--json", action="store_true")
    return parser


def resolve_equations_only(args) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether the loop may rewrite formulas. The safe setting is the
        default: only --rewrite-formulas turns the rewrite on.

    Inputs:
        args (argparse.Namespace): the parsed `fix` command line.

    Outputs:
        bool: True when only lost equations are recovered.

    Raises:
        ValueError: both --equations-only and --rewrite-formulas were given.
    --------------------------------------------------------------------------
    """
    if args.equations_only and args.rewrite_formulas:
        raise ValueError("--equations-only and --rewrite-formulas contradict each other; pass at most one")
    return not args.rewrite_formulas


def _main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        The `pdf2md.py fix` command: run the correction loop on an output
        directory, as a dry run unless --yes.

    Details:
        Exit codes (R12): 0 done, 2 refused by design (no --model, or a backup
        of an earlier run is in the way), 1 the loop stopped with more than
        target_remaining_issues left and --strict was given.

    Inputs:
        argv (list[str] | None): the command line.

    Outputs:
        int: the exit code.
    --------------------------------------------------------------------------
    """
    import shutil
    import sys

    import pdf2md_postprocess
    import pdf2md_repair as repair
    import pdf2md_validate as validate

    validate.extract_text.configure_streams()
    args = _build_parser().parse_args(argv)
    if not args.model:
        print("[VLMFIX] refusing: --model TAG is required (never a default, R2).", file=sys.stderr)
        return 2
    try:
        equations_only = resolve_equations_only(args)
    except ValueError as exc:
        print(f"[VLMFIX] refusing: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    try:
        layout = pdf2md_postprocess.read_layout(output_dir)
    except ValueError as exc:
        print(f"[VLMFIX] refusing: {exc}", file=sys.stderr)
        return 2
    if layout == "single":
        print("[VLMFIX] refusing: this output uses the single-document layout; the correction loop works chapter by chapter.", file=sys.stderr)
        return 2
    config, vlm_config, fidelity_config = load_vlmfix_config(), vlmcheck.load_vlmcheck_config(), fidelity.load_fidelity_config()
    backup_dir = output_dir / "pdf2md-backup-vlm"
    if args.yes and backup_dir.exists() and any(backup_dir.iterdir()):
        print(f"[VLMFIX] refused: {backup_dir} already holds the originals of an earlier run; move it aside first.", file=sys.stderr)
        return 2

    chapters = validate.load_output_chapters(output_dir)
    page_texts = validate._read_page_texts(args.pdf_path)
    ranges = {}
    for number in chapters:
        found = validate.find_chapter_page_range(args.pdf_path, number, page_texts=page_texts)
        if found is not None:
            ranges[number] = found
    changes_path = output_dir / repair.load_repair_config()["assets_dir_name"] / config["changes_file"]

    def persist(_round: int, texts: dict[int, str], changes: list[dict]) -> None:
        if not args.yes:
            return
        for number, text in texts.items():
            stem, original = chapters[number]
            if text != original:
                path = output_dir / "content" / f"{stem}.md"
                backup_dir.mkdir(parents=True, exist_ok=True)
                if not (backup_dir / path.name).exists():
                    shutil.copy2(path, backup_dir / path.name)
                path.write_text(text, encoding="utf-8")
        _write_changes_file(changes_path, changes, [])

    result = run_correction_loop(
        pdf_path=args.pdf_path, chapters=chapters, pdf_chapters=validate.extract_pdf_chapters(args.pdf_path), chapter_ranges=ranges, page_texts=page_texts,
        model_tag=args.model, vlm_config=vlm_config, fidelity_config=fidelity_config, config=config,
        math_symbol_chars=validate.load_config()["math_symbol_chars"], scratch_dir=output_dir / "validate-scratch", all_pages=args.pages == "all", equations_only=equations_only, on_round=persist,
    )
    if args.yes:
        _write_changes_file(changes_path, result["changes"], result["needs_review"])
    summary = {key: result[key] for key in ("stopped", "remaining", "history", "changes", "needs_review")}
    summary["applied"] = args.yes
    print(json.dumps(summary, ensure_ascii=False) if args.json else _render(summary))
    return 1 if args.strict and result["remaining"] > config["target_remaining_issues"] else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
