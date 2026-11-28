"""
ugs_run.py - run the five grading steps of ONE report in one loop (Issue #104).

The steps are grade, language, figures, audit and assemble, in that order. Each is skipped when every ledger
line of it is already marked done or blocked, so a repeated run calls the model zero times and an interrupted
run continues where it stopped. The ledger receives only labels, marks and short codes, never text of the
report. A model that cannot run (NotRun) propagates and leaves the step open for a resume. An ordinary error
marks that step blocked, stops this report only and is returned as status failed.
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ugs_ledger import read, write, set_mark, parse, add_figures
from ugs_text import StepContext, read_pages, detect_language, LanguageUndecidable, PromptError
from ugs_grade import grade_report
from ugs_audit import audit_report
from ugs_language import language_report
import front_pages
from ugs_figures import figures_report
from ugs_assemble import assemble_report
from ugs_bridge import NotRun
from ugs_config import load as load_config, default_path as default_config_path
from ugs_tables import load_elements
from page_roles import LANGUAGES

STEPS = ("grade", "language", "figures", "audit", "assemble")
DEFAULT_LANGUAGE = "en"
META_NAME_KEY = "reports.meta_file_name"
ELEMENTS_NAME_KEY = "reports.elements_file_name"
META_LANGUAGE_KEY = "language"


class LanguageError(ValueError):
    """Raised when the language recorded in a report's metadata is not one the pipeline supports."""
# A "!" line whose note starts with this prefix is an ordinary exception, not a block that waits for the owner:
# a resume retries it, so an unaudited grade can never reach the annex by being skipped.
ERROR_NOTE_PREFIX = "error="
# The detail of a mark record: a ledger mark written as a word, because the allow-list of ugs_events takes no "!".
MARK_WORDS = {"x": "done", "!": "blocked", " ": "open"}
# A ledger note that comes from a model answer must look like a snake_case code, so a sentence of a report
# (letters and spaces would pass the ledger's own check) can never be written into the ledger.
CODE_RE = re.compile(r"^[a-z0-9_]{1,30}$")
UNKNOWN_CODE = "not_run"


@dataclass
class _Job:
    """Everything the five steps share for one report in one loop."""
    work_dir: Path
    report_id: str
    loop: int
    src_pdf: Path
    call: Callable
    ctx: StepContext
    services: dict
    calibration_note: str
    fetch: Optional[Callable]
    pages: List[str]
    language: str
    ledger_path: Path
    loop_dir: Path

    def call_for(self, step: str) -> Callable:
        """The model call of a step: `call` may be one callable for every step or a map from step to callable."""
        return self.call[step] if isinstance(self.call, dict) else self.call

    def mark(self, label: str, mark: str, note: Optional[str] = None) -> None:
        """Set one ledger line, reading the file again so no step works on a stale text, then record the mark."""
        write(self.ledger_path, set_mark(read(self.ledger_path), self.report_id, label, mark, note))
        self.emit("mark", label, MARK_WORDS.get(mark))

    def emit(self, action: str, target: str, detail: Optional[str] = None) -> None:
        """
        --------------------------------------------------------------------------
        Purpose:
            Record one action of this step through the emitter of the step context, when there is one.

        Inputs:
            action (str): one of the actions of ugs_events
            target (str): an item label, a page range or a bare file name
            detail (str or None): an allow-listed detail, for a mark

        Outputs:
            None. The emitter never raises (ugs_events.make_emitter), so the step result is not changed by it.

        Raises:
            None.
        --------------------------------------------------------------------------
        """
        if self.ctx.emit is not None:
            self.ctx.emit(action, target, report_id=self.report_id, detail=detail)

    def save(self, path: Path, data: Any) -> None:
        """
        --------------------------------------------------------------------------
        Purpose:
            Write one JSON output file of a step and record its base name as a write action.

        Inputs:
            path (Path): the output file, inside the loop folder
            data (Any): the JSON document

        Outputs:
            None. The file is written before its record, so a record never names a file that does not exist.

        Raises:
            OSError: the output file cannot be written, as before plan 10.
        --------------------------------------------------------------------------
        """
        _write_json(path, data)
        self.emit("write", path.name)

    def ensure_figure_lines(self, figure_ids: List[str]) -> None:
        """Add the figure lines that are not yet in the ledger (add_figures skips the present ones)."""
        write(self.ledger_path, add_figures(read(self.ledger_path), self.report_id, figure_ids))


def _short_code(text: Any) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a model-provided comment into a ledger note that can only be a code.

    Inputs:
        text (Any): the comment of a record

    Outputs:
        code (str): the text when it is a snake_case code of at most 30 characters, else `not_run`.
    --------------------------------------------------------------------------
    """
    return text if isinstance(text, str) and CODE_RE.match(text) else UNKNOWN_CODE


def _belongs(label: str, step: str) -> bool:
    """True when a ledger label is a line of the given step."""
    if step == "grade":
        return label.startswith("grade ")
    if step == "figures":
        return label == "figures" or label.startswith("figure ")
    return label == step


def _step_lines(ledger_text: str, report_id: str, step: str) -> List[dict]:
    return [s for s in parse(ledger_text) if s["report_id"] == report_id and _belongs(s["label"], step)]


def _is_settled(line: dict) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say whether one ledger line needs no further run: done, or blocked for a reason that waits for the owner.

    Details:
        A "!" line whose note is an error code (ERROR_NOTE_PREFIX) records an ordinary exception and is not
        settled, so a resume runs its step again. Every other "!" line is an explicit block (a model that
        answered not_run, a flagged audit, a missing vision validation) and stays settled.

    Inputs:
        line (dict): one step of ugs_ledger.parse, with keys `mark` and `note`

    Outputs:
        settled (bool): True for "x" and for a "!" line that is not an error.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    if line["mark"] == "x":
        return True
    if line["mark"] == "!":
        return not (line.get("note") or "").startswith(ERROR_NOTE_PREFIX)
    return False


def _settled(ledger_text: str, report_id: str, step: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say whether a step has nothing left to do: it has ledger lines and every one is settled.

    Inputs:
        ledger_text (str): the ledger
        report_id (str): the report
        step (str): one of STEPS

    Outputs:
        settled (bool): False when the step has no line at all, or when one line is open or an exception.
    --------------------------------------------------------------------------
    """
    lines = _step_lines(ledger_text, report_id, step)
    return bool(lines) and all(_is_settled(line) for line in lines)


def _load_json(path: Path) -> Optional[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_json(path: Path, data: Any) -> None:
    """
    Purpose: Write one JSON step file atomically (plan 30, Task 1): the text goes to a temporary file beside it, which
        replaces the file only when complete, so a crash never leaves a half-written file that blocks --continue.
    Inputs:
        path (Path): the file to write.
        data (Any): the JSON document.
    Outputs:
        None.
    Raises:
        OSError: when the write or the replace fails; the temporary file is removed and the old file is kept.
    """
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def report_language(work_dir: Path, report_id: str, pages: List[str], hints: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give the language of one report: the one recorded at preparation when its metadata file exists,
        otherwise the detector's answer from the page text and the language hints.

    Details:
        The metadata file is `<work_dir>/<report_id>/<reports.meta_file_name>` (ugs_config.json). Without it
        the detector runs exactly as before the metadata existed: with hints, detect_language; with none,
        DEFAULT_LANGUAGE.

    Inputs:
        work_dir (Path): the work folder
        report_id (str): the report id, for example R01
        pages (List[str]): the page texts of the report, used only by the detector
        hints (dict): the language hints, a map from 'fr' and 'en' to lists of words; empty when absent

    Outputs:
        language (str): 'fr' or 'en'.

    Raises:
        LanguageError: the metadata file is unreadable, holds no `language` key, or holds a value other
            than one of LANGUAGES. The message names the value or key and the file, never report text.
    --------------------------------------------------------------------------
    """
    meta_path = work_dir / report_id / load_config(default_config_path())[META_NAME_KEY]
    if not meta_path.exists():
        return detect_language(pages, hints) if hints else DEFAULT_LANGUAGE
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageError(f"report metadata is unreadable: {meta_path} ({type(exc).__name__})") from exc
    if not isinstance(meta, dict) or META_LANGUAGE_KEY not in meta:
        raise LanguageError(f"key '{META_LANGUAGE_KEY}' missing in report metadata: {meta_path}")
    language = meta[META_LANGUAGE_KEY]
    if language not in LANGUAGES:
        raise LanguageError(f"language '{language}' is not one of {list(LANGUAGES)} in: {meta_path}")
    return language


def _upsert(records: List[dict], key: str, value: str, record: dict) -> None:
    """Replace the record whose `key` equals `value`, else append it."""
    for index, existing in enumerate(records):
        if existing.get(key) == value:
            records[index] = record
            return
    records.append(record)


def _grade_mark(record: dict) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give the ledger mark and note of a grade line. The note is the validation code only, never a quote.

    Details:
        A record not run is blocked with its validation code (a record written before plan 12 has no
        validation field, so its comment is read as before). A rated record whose proof was refused is done
        with its code, because its score is usable; a rated record with code ok is done with no note.

    Inputs:
        record (dict): one grade record of ugs_grade.grade_item

    Outputs:
        mark_and_note (tuple): (mark, note), the mark being "x" or "!" and the note a code or None.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    if record["status"] == "not_run":
        return "!", _short_code(record.get("validation", record.get("comment")))
    code = record.get("validation")
    if code in (None, "ok"):
        return "x", None
    return "x", _short_code(code)


def _figure_mark(record: dict) -> tuple:
    """The mark and note of a figure line: blocked when any criterion of it was not run."""
    for result in record.get("criteria", {}).values():
        if result.get("verdict") == "not_run":
            return "!", "not_run"
    return "x", None


def _step_grade(job: _Job) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Grade every rubric item, saving the partial grade file and marking the item's line after each one.

    Inputs:
        job (_Job): the shared state

    Outputs:
        status (str): `blocked` when any item was not run, else `done`.
    --------------------------------------------------------------------------
    """
    grade_path = job.loop_dir / "grade.json"
    existing = _load_json(grade_path)
    items = list(existing["items"]) if existing and "items" in existing else []

    announced = set()

    def on_item(item_id: str, record: dict) -> None:
        _upsert(items, "item_id", item_id, record)
        job.save(grade_path, {"report_id": job.report_id, "loop": job.loop, "items": items})
        job.mark("grade " + item_id, *_grade_mark(record))
        announced.add(item_id)

    result = grade_report(job.services["rubric"], job.pages, job.report_id, job.loop, job.call_for("grade"), job.ctx,
                          job.language, job.calibration_note, existing, on_item)
    job.save(grade_path, result)
    for record in result["items"]:  # an item saved before an interruption still gets its mark, once
        if record["item_id"] not in announced:
            job.mark("grade " + record["item_id"], *_grade_mark(record))
    return "blocked" if any(r["status"] == "not_run" for r in result["items"]) else "done"


def _page_modes(work_dir: Path, report_id: str) -> Dict[int, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give the correction mode of each front page of a report, from the front roles recorded in its
        report_meta.json (plan 16, N3).

    Inputs:
        work_dir (Path): the work folder of the run.
        report_id (str): the report id, its folder is work_dir / report_id.

    Outputs:
        Dict[int, str]: 1-based page to mode; empty when the report has no recorded front roles.

    Raises:
        FrontMatterConfigError: when the front-matter data file is incomplete (named in the message).
    --------------------------------------------------------------------------
    """
    meta = _load_json(work_dir / report_id / "report_meta.json") or {}
    roles = meta.get("front_roles")
    if not roles:
        return {}
    return front_pages.page_modes(roles, front_pages.load_front_matter())


def _step_language(job: _Job) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Language findings of every page, saved page by page so a stop keeps the pages already answered.

    Details:
        The partial file `language.json` of the loop folder holds the pages answered so far under `pages`; a
        resume passes them to language_report, which sends only the other pages to the model. The step is
        blocked, with the count of pages that did not run, when some failed.

    Inputs:
        job (_Job): the shared state

    Outputs:
        status (str): `blocked` when a page did not run, else `done`.

    Raises:
        NotRun: propagates from the model call; the pages answered before it are already saved.
    --------------------------------------------------------------------------
    """
    path = job.loop_dir / "language.json"
    saved = _load_json(path) or {}
    existing = {int(number): record for number, record in saved.get("pages", {}).items()}
    result = language_report(job.pages, job.call_for("language"), job.ctx, job.services["entries"], job.language,
                             existing=existing, on_page=lambda _number, partial: job.save(path, partial),
                             page_modes=_page_modes(job.work_dir, job.report_id))
    job.save(path, result)
    if result["not_run"]:
        job.mark("language", "!", "pages=%d" % len(result["not_run"]))
        return "blocked"
    job.mark("language", "x")
    return "done"


def _figure_inputs(job: _Job) -> Tuple[Optional[List[Dict[str, Any]]], Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the element records and the folder that holds the figure files of one report.

    Details:
        The prepared folder is `<work_dir>/<report_id>`, where report_prepare wrote `elements.json` and the
        figure files under `figures`. When `elements.json` exists its records are given to the figure step and
        the prepared folder is the report folder of the step. Without it the figures are extracted from the PDF
        into the loop folder, as before the element records existed.

    Inputs:
        job (_Job): the shared state of the report

    Outputs:
        inputs (tuple): (elements, report_dir), where elements is the list of records or None and report_dir
        the folder given to figures_report.

    Raises:
        ugs_tables.TablesError: the elements file is not valid JSON or not a list of records.
    --------------------------------------------------------------------------
    """
    prepared = job.work_dir / job.report_id
    elements_path = prepared / load_config(default_config_path())[ELEMENTS_NAME_KEY]
    if not elements_path.exists():
        return None, job.loop_dir
    return load_elements(elements_path), prepared


def _step_figures(job: _Job) -> str:
    """Figures: partial file saved and each figure line marked after each figure, then the `figures` line."""
    figures_path = job.loop_dir / "figures.json"
    saved = _load_json(figures_path) or {}
    doc = {"report_id": job.report_id, "figures": list(saved.get("figures", [])),
           "report_criteria": saved.get("report_criteria", {})}
    existing = {f["figure_id"]: f for f in doc["figures"]}

    announced = set()

    def on_figure(figure_id: str, record: dict) -> None:
        _upsert(doc["figures"], "figure_id", figure_id, record)
        job.save(figures_path, doc)
        job.ensure_figure_lines([figure_id])
        job.mark("figure " + figure_id, *_figure_mark(record))
        announced.add(figure_id)

    elements, report_dir = _figure_inputs(job)
    result = figures_report(job.src_pdf, report_dir, job.report_id, job.pages, job.call_for("figures"), job.ctx,
                            job.services["criteria_doc"], job.language, job.services["vision_ok"],
                            existing, on_figure, elements=elements)
    job.save(figures_path, result)
    job.ensure_figure_lines([f["figure_id"] for f in result["figures"]])
    for record in result["figures"]:
        if record["figure_id"] not in announced:
            job.mark("figure " + record["figure_id"], *_figure_mark(record))
    if not job.services["vision_ok"]:
        job.mark("figures", "!", "vision_not_ok")
        return "blocked"
    job.mark("figures", "x")
    return "done"


def _step_audit(job: _Job) -> str:
    """Audit the saved grade with the second model; the grade file is rewritten, flagged items block the line."""
    grade_path = job.loop_dir / "grade.json"
    grade = json.loads(grade_path.read_text(encoding="utf-8"))

    def on_item(item_id: str, record: dict) -> None:
        _upsert(grade["items"], "item_id", item_id, record)
        job.save(grade_path, grade)

    result = audit_report(job.services["rubric"], job.pages, grade, job.call_for("audit"), job.ctx, job.language,
                          job.calibration_note, on_item)
    job.save(grade_path, result)
    flags = sum(1 for item in result["items"] if item.get("flag"))
    if flags:
        job.mark("audit", "!", "flags=%d" % flags)
        return "blocked"
    job.mark("audit", "x")
    return "done"


def _step_assemble(job: _Job) -> str:
    """Totals, annotations, the annotated copy and the annex; the line carries the annex page count."""
    result = assemble_report(job.src_pdf, job.loop_dir, job.report_id, job.loop, job.services["rubric"],
                             job.pages, job.language, job.services["settings"], job.fetch)
    job.mark("assemble", "x", "pages=%d" % result["annex_pages"])
    return "done"


RUNNERS = (("grade", _step_grade), ("language", _step_language), ("figures", _step_figures),
           ("audit", _step_audit), ("assemble", _step_assemble))


def _failure_label(job: _Job, step: str) -> str:
    """The ledger line that carries a step's failure: the first unsettled grade line for the grade step."""
    if step != "grade":
        return step
    lines = _step_lines(read(job.ledger_path), job.report_id, "grade")
    open_lines = [s for s in lines if not _is_settled(s)]
    return (open_lines or lines)[0]["label"]


def run_report(
    work_dir: Path,
    report_id: str,
    loop: int,
    src_pdf: Path,
    call: Callable,
    ctx: StepContext,
    services: dict,
    calibration_note: str,
    fetch: Optional[Callable],
    on_step: Optional[Callable[[str], None]] = None,
    only_steps: Optional[List[str]] = None
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the grading steps of one report in one loop folder, resuming and skipping what is settled.

    Details:
        The ledger is `work_dir/ledger.md` and the loop folder is `work_dir/loop-N/R01`. A step is skipped
        when every ledger line of it is already marked done or blocked. An ordinary exception in a step
        marks that line blocked with the note `error=<ExceptionName>`, stops the report and returns
        status `failed`.

    Inputs:
        work_dir (Path): the work folder
        report_id (str): the report id, for example R01
        loop (int): the loop number
        src_pdf (Path): the source PDF
        call (Callable | dict): the model call, injected: one callable for every step, or a map from step
            (`grade`, `language`, `figures`, `audit`) to the callable of its model role
        ctx (StepContext): the step context
        services (dict): `rubric`, `entries` (language table), `criteria_doc`, `hints`, `vision_ok` and
            `settings` (for assemble_report)
        calibration_note (str): the note of the loop, empty on loop 1
        fetch (Callable | None): the URL fetcher of the reference check, injected
        on_step (Callable[[str], None] | None): called with the name of each step before it runs, so the caller
            can name the role of the actions the step records; None changes nothing

    Outputs:
        summary (dict): `report_id`, `status` (`done` or `failed`) and `steps`, a map of each step to
        `done`, `blocked` or `skipped`. It holds no text of the report. A report whose metadata is refused
        is `failed` with a `reason` naming the key or the file (never report text) and no step run. A report
        whose language cannot be decided is `failed` with the reason `<report id>: language undecidable`. A report
        with no pages folder, or an empty one, is `failed` with the reason `<report id>: pages missing`.

    Raises:
        NotRun: the model could not run; the step stays open so a resume continues there.
    --------------------------------------------------------------------------
    """
    loop_dir = work_dir / f"loop-{loop}" / report_id
    loop_dir.mkdir(parents=True, exist_ok=True)
    hints = services.get("hints") or {}
    steps: Dict[str, str] = {name: "skipped" for name in STEPS}
    try:  # a report with no pages folder stops only itself, as a refused language does (Issue 122, defect 1)
        pages = read_pages(work_dir, report_id)
    except PromptError:
        return {"report_id": report_id, "status": "failed", "steps": steps,
                "reason": f"{report_id}: pages missing"}
    try:
        language = report_language(work_dir, report_id, pages, hints)
    except LanguageError as exc:  # a bad report stops only itself: the batch goes on with the next one
        return {"report_id": report_id, "status": "failed", "steps": steps, "reason": str(exc)}
    except LanguageUndecidable:  # the reason names the report only, never its text (R8, Issue 122, defect 2)
        return {"report_id": report_id, "status": "failed", "steps": steps,
                "reason": f"{report_id}: language undecidable"}
    job = _Job(work_dir, report_id, loop, src_pdf, call, ctx, services, calibration_note, fetch, pages,
               language, work_dir / "ledger.md", loop_dir)
    for name, runner in RUNNERS:
        if only_steps is not None and name not in only_steps:
            continue  # N1: `run --steps` restricts the run; the other steps stay skipped and open
        if _settled(read(job.ledger_path), report_id, name):
            continue
        if on_step is not None:
            on_step(name)
        try:
            steps[name] = runner(job)
        except NotRun:
            raise
        except Exception as exc:  # noqa: BLE001 - an ordinary failure blocks this report only
            # Plan 29: an exception that names a code (ScoreNotReproduced) blocks the line with that code.
            # Review round 2, finding 9: GradeError, RubricError and AnnexError name their code; a ledger_note wins.
            note = getattr(exc, "ledger_note", None) or "error=" + getattr(exc, "code", type(exc).__name__)
            job.mark(_failure_label(job, name), "!", note)
            steps[name] = "blocked"
            return {"report_id": report_id, "status": "failed", "steps": steps}
    return {"report_id": report_id, "status": "done", "steps": steps}
