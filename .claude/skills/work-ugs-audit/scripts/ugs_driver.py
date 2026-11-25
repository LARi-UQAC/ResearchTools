"""
ugs_driver.py - the command line of the grading driver of work-ugs-audit (Issue #104).

Subcommands: prepare (ids, pages, rubric, ledger), run (the five steps of every report), batch (the spread of the
totals and the next loop) and status (the ledger counts). The program that runs it reads only what it prints:
every printed line is a JSON object whose values are ids, step labels, statuses, kinds and numbers, never text of a
report. The work folder `_correction` lies inside the reports folder (owner decision 2026-11-15).

EXIT CODES (R12): 0 done, 1 a model step could not run (stop, resume later), 2 refusal, 3 batch out of band.
"""
import argparse
import contextlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_SKILLS = Path(__file__).resolve().parent.parent.parent
for _folder in (_SKILLS / "figure-review" / "scripts",):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import ugs_config
import report_prepare
from rubric_check import validate as validate_rubric, RubricError
from ugs_grade import normalize_rubric
import rubric_split
from ugs_run import STEPS, run_report
from ugs_ledger import (new_ledger, add_report, set_mark, reopen_all, add_note, read as read_ledger,
                        write as write_ledger, counts as ledger_counts, first_open, parse as parse_ledger)
from batch_stats import main as batch_stats_main
from ugs_text import StepContext, load_prompts, load_schemas, load_hints, fill
from ugs_language import load_table
from ugs_tables import TablesError
from ugs_bridge import OllamaDeps, NotRun, call as bridge_call
from ugs_events import make_emitter
from figure_checks import load_criteria

EXIT_OK, EXIT_NOT_RUN, EXIT_REFUSAL, EXIT_OUT_OF_BAND = 0, 1, 2, 3
SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[4]
PROMPTS_DIRS = (SKILL_DIR / "prompts", _SKILLS / "figure-review" / "prompts")
SCHEMAS_FILE = SKILL_DIR / "prompts" / "schemas.json"
ASSETS = SKILL_DIR / "assets"
CRITERIA_FILE = _SKILLS / "figure-review" / "assets" / "figure_criteria.json"
LANGUAGE_TABLE = _SKILLS / "language-review" / "assets" / "language_categories.json"
WORK_FOLDER_NAME = "_correction"
SCHEMA_NAMES = ["rubric", "grade_item", "audit_item", "language", "figure", "figure_set", "vision_probe"]
STEP_KIND = {"grade": "grader", "language": "grader", "figures": "vision", "audit": "auditor"}
TEXT_RUBRIC_SUFFIXES = (".md", ".txt", ".pdf")
REQUIRED_CONFIG_KEYS = [
    "roles.grader", "roles.auditor", "roles.vision", "driver.reply_reserve_tokens", "driver.request_timeout_s",
    "driver.audit_retries", "driver.max_image_bytes", "driver.image_tokens_fallback",
    "grade.invalid_answer_retries", "select.min_word_len", "references.quote_chars", "references.url_timeout_s",
    "references.max_retries", "batch.outlier_z", "annotation.colors",
]


class DriverError(Exception):
    """A refusal: the message names a key or a rule, never a file name or text of a report."""


def _emit(record: Dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=False))


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DriverError(f"{what} is missing or unreadable") from None


def _load_config() -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Load the configuration and check every key the driver reads.

    Inputs:
        None

    Outputs:
        config (dict): dotted key to value.

    Raises:
        DriverError: the file cannot be read or a required key is missing; the message names the key (R3).
    --------------------------------------------------------------------------
    """
    try:
        config = ugs_config.load(ugs_config.default_path())
    except ugs_config.ConfigError as error:
        raise DriverError(str(error)) from None
    for key in REQUIRED_CONFIG_KEYS:
        if key not in config:
            raise DriverError(f"missing configuration key: {key}")
    return config


def _assessment_types() -> List[str]:
    return list(_read_json(ASSETS / "calibration_targets.json", "calibration targets"))


def _work_dir(work: Path) -> Path:
    """The work folder of run, batch and status: it must hold a rubric and a ledger."""
    work = work.resolve()
    if not (work / "rubric.json").is_file() or not (work / "ledger.md").is_file():
        raise DriverError("not a prepared work folder (run prepare first)")
    return work


def _current_loop(work: Path) -> int:
    state = work / "loop_state.json"
    return int(_read_json(state, "loop state").get("loop", 1)) if state.is_file() else 1


def _real_deps(config: Dict[str, Any]) -> Dict[str, Any]:
    """The real window and token counter, from the resolver and the daemon; NotRun when a role is unadopted."""
    deps = OllamaDeps(config["driver.count_timeout_s"])
    windows, tags = {}, {}
    for kind in ("grader", "auditor"):
        role = config[f"roles.{kind}"]
        tags[kind] = deps.tag(role)
        windows[kind] = deps.window(tags[kind], role)
    window = min(windows.values())
    return {"deps": deps, "window": window, "count": lambda text: deps.count(text, tags["grader"], window)}


def _real_call(config: Dict[str, Any], work: Path, deps: OllamaDeps) -> Callable:
    """The model call `call(kind, prompt, schema, images)`, one role per kind, the limits from the configuration."""
    def call(kind: str, prompt: str, schema: dict, images: Optional[List[str]] = None) -> dict:
        probe = work / "vision_probe.json"
        image_tokens = config["driver.image_tokens_fallback"]
        if probe.is_file():
            measured = _read_json(probe, "vision probe").get("image_tokens")
            image_tokens = measured if isinstance(measured, int) and measured > 0 else image_tokens
        return bridge_call(config[f"roles.{kind}"], prompt, schema, images, deps=deps,
                           timeout=config["driver.request_timeout_s"], reserve=config["driver.reply_reserve_tokens"],
                           image_tokens=image_tokens, max_image_bytes=config["driver.max_image_bytes"])
    return call


def _stamp() -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The clock of the action records: a UTC ISO 8601 stamp to the millisecond, the format of the bridge log.

    Inputs:
        None

    Outputs:
        stamp (str): for example 2026-11-16T10:00:00.000+00:00

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _step_role(config: Dict[str, Any], step: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the local role that acts in a grading step, for the action records of the dashboard.

    Inputs:
        config (dict): the configuration, with the roles.* keys
        step (str): one of the steps of ugs_run; a step with no model call acts as the grader

    Outputs:
        role (str): the configured role name, for example the grader role.

    Raises:
        KeyError: the configuration lacks the roles.* key; cmd_run checks the keys before it calls this.
    --------------------------------------------------------------------------
    """
    return config[f"roles.{STEP_KIND.get(step, 'grader')}"]


def _action_emitter(deps: Any, role_for: Callable[[], str], clock: Callable[[], str]) -> Optional[Callable[..., None]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the emitter of the grading steps on the bridge log writer, or None when there is no real log.

    Details:
        The records go through deps.log, the writer the bridge uses, so no second log file is opened. A test that
        injects its own model call passes no deps, which gives None and keeps the machine's log untouched.

    Inputs:
        deps (object or None): an object with a log(record) method, None when there is no real log
        role_for (callable): returns the role of the acting step at the time of the call
        clock (callable): returns the stamp of a record

    Outputs:
        emit (callable or None): the make_emitter function, which never raises, or None.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    if deps is None:
        return None
    return make_emitter(deps.log, role_for, clock)


def _context(config: Dict[str, Any], window: int, count: Callable,
             emit: Optional[Callable[..., None]] = None) -> StepContext:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the step context of the grading steps from the prompts, the schemas and the configuration.

    Inputs:
        config (dict): the configuration
        window (int): the context window in tokens
        count (callable): the token counter
        emit (callable or None): the action emitter, None for a silent run

    Outputs:
        ctx (StepContext): the context shared by the steps of one run.

    Raises:
        PromptError: a missing prompt or schema, raised by ugs_text as before.
    --------------------------------------------------------------------------
    """
    prompts: Dict[str, str] = {}
    for folder in PROMPTS_DIRS:
        prompts.update(load_prompts(folder))
    return StepContext(prompts=prompts, schemas=load_schemas(SCHEMAS_FILE, SCHEMA_NAMES), levels=prompts["levels"],
                       window_tokens=window, reserve_tokens=config["driver.reply_reserve_tokens"], count=count,
                       grade_retries=config["grade.invalid_answer_retries"],
                       audit_retries=config["driver.audit_retries"], min_word_len=config["select.min_word_len"],
                       emit=emit)


def _inputs(call: Optional[Callable], window: Optional[int], count: Optional[Callable], config: dict, work: Path):
    """The model call, the window and the counter: injected together (tests) or built from the real ones."""
    if call is not None:
        if window is None or count is None:
            raise DriverError("an injected call needs an injected window and counter")
        return call, window, count
    real = _real_deps(config)
    return _real_call(config, work, real["deps"]), real["window"], real["count"]


def _rubric_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(str(path)) as doc:
            return "\n\n".join(page.get_text() for page in doc)
    return path.read_text(encoding="utf-8")


def _items_markdown(rubric: dict) -> str:
    """The sections of the rubric as the professor wrote them: each item's exact text, else its title and criteria."""
    # The exact text starts with the professor's own heading, so the id the ledger and the grades use is added
    # above it: the orchestrating agent reads only this file and must map a ledger line `I07` to its section.
    return "\n\n".join(("[%s]\n%s" % (item["id"], rubric_split.item_markdown(item))) if item.get("text")
                       else rubric_split.item_markdown(item) for item in rubric["items"])


def _rubric_for(args: argparse.Namespace, config: dict, work: Path, call, window, count, dry: bool) -> Optional[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the professor's rubric file: JSON is validated and used as it is. A Markdown or text file with
        numbered sections is split by the code (every section keeps its exact text, no model call). Any other text,
        Markdown or PDF text goes through the grader model, which may restructure it but not remove a line (checked
        for Markdown and text, reported as unverified for PDF). Any other extension is refused.

    Inputs:
        args (Namespace): `rubric` and `type`
        config, work, call, window, count: the context for a model call
        dry (bool): True for a dry run, which never calls a model

    Outputs:
        rubric (dict | None): the validated rubric, None in a dry run of a rubric that needs the model.

    Raises:
        DriverError: unsupported extension, missing file, invalid rubric, a type that differs from the rubric's.
        NotRun: the grader model could not run.
    --------------------------------------------------------------------------
    """
    path = Path(args.rubric)
    suffix = path.suffix.lower()
    if suffix != ".json" and suffix not in TEXT_RUBRIC_SUFFIXES:
        raise DriverError("unsupported rubric file type: convert it to JSON, Markdown, text or PDF text")
    if not path.is_file():
        raise DriverError("rubric file not found")
    if suffix == ".json":
        rubric = _read_json(path, "rubric file")
    else:
        source = _rubric_text(path)
        rubric = None
        if suffix != ".pdf":
            # A rubric with numbered sections is split by the code: no sentence is removed or shortened.
            try:
                rubric = rubric_split.split_rubric(source, args.type, config["rubric.section_heading_regex"],
                                                   config["rubric.total_regex"],
                                                   config["rubric.loose_heading_regex"])
            except rubric_split.RubricSplitError as error:
                raise DriverError(f"invalid rubric: {error}") from None
        if rubric is None:
            if dry:
                return None
            model_call, model_window, model_count = _inputs(call, window, count, config, work)
            ctx = _context(config, model_window, model_count)
            rubric = normalize_rubric(source, args.type,
                                      lambda prompt, schema, images=None: model_call("grader", prompt, schema, images), ctx)
            _emit({"warning": "rubric_model_split"})
            if rubric.get("preamble"):
                for item in rubric.get("items", []):
                    item.setdefault("preamble", rubric["preamble"])
            if suffix == ".pdf":
                # PDF text carries running headers, page numbers and hyphenation that no model copies, so a line
                # check would refuse a faithful split: say it was not verified instead.
                _emit({"warning": "rubric_pdf_text_unverified"})
            else:
                missing = rubric_split.check_text_kept(source, rubric, config["rubric.min_check_words"])
                if missing is not None:
                    raise DriverError(f"the model removed a line of the rubric: {missing}")
    try:
        validate_rubric(rubric)
    except RubricError as error:
        raise DriverError(f"invalid rubric: {error}") from None
    if rubric["assessment_type"] != args.type:
        raise DriverError("the rubric assessment type differs from --type")
    return rubric


def cmd_prepare(args, call, window, count) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Give every report an id and its pages, write the rubric (JSON and Markdown) and the ledger.

    Details:
        Idempotent: a second run adds no ledger section. The rubric is validated (split by the code when it has
        numbered sections, restructured by the model otherwise) before any page is extracted, so a refusal leaves
        nothing behind. The loop state
        is not touched.

    Inputs:
        args (Namespace): `reports`, `rubric`, `type`, `work`, `dry_run`
        call, window, count: injected model call, window and counter (tests), or None

    Outputs:
        code (int): 0, after one JSON line per report.

    Raises:
        DriverError: a refusal. NotRun: the grader could not run (a text rubric).
    --------------------------------------------------------------------------
    """
    config = _load_config()
    reports = Path(args.reports).resolve()
    if not reports.is_dir():
        raise DriverError("reports folder not found")
    work = Path(args.work).resolve() if args.work else reports / WORK_FOLDER_NAME
    try:
        report_prepare._check_work_dir(reports, work)
    except report_prepare.PrepareError as error:
        raise DriverError(str(error)) from None
    if args.type not in _assessment_types():
        raise DriverError("unknown assessment type")
    rubric = _rubric_for(args, config, work, call, window, count, args.dry_run)
    if args.dry_run:
        _emit({"dry_run": True, "step": "prepare", "reports": len([p for p in reports.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])})
        return EXIT_OK
    try:
        results = report_prepare.prepare(reports, work)
    except (report_prepare.PrepareError, TablesError) as error:  # TablesError names the missing key (R3)
        raise DriverError(str(error)) from None
    work.mkdir(parents=True, exist_ok=True)
    (work / "rubric.json").write_text(json.dumps(rubric, indent=2, ensure_ascii=False), encoding="utf-8")
    template = (ASSETS / "rubric.template.md").read_text(encoding="utf-8")
    (work / "rubric.md").write_text(fill(template, {
        "ASSESSMENT_TYPE": rubric["assessment_type"], "TOTAL_POINTS": str(rubric["total_points"]),
        "PREAMBLE": rubric.get("preamble", ""), "ITEMS": _items_markdown(rubric)}), encoding="utf-8")
    ledger_path = work / "ledger.md"
    ledger = read_ledger(ledger_path) if ledger_path.is_file() else new_ledger("Ledger - grading steps")
    item_ids = [item["id"] for item in rubric["items"]]
    for result in results:
        ledger = add_report(ledger, result["report_id"], item_ids)
        if "refused" not in result:  # a refused report stays open: its prepare line is not done (Issue 122, defect 1)
            ledger = set_mark(ledger, result["report_id"], "prepare", "x")
    write_ledger(ledger_path, ledger)
    for result in results:
        if "refused" in result:
            _emit({"report_id": result["report_id"], "step": "prepare", "status": "refused",
                   "reason": result["refused"]})
        else:
            _emit({"report_id": result["report_id"], "pages": result["pages"], "step": "prepare", "status": "done"})
    return EXIT_OK


def _services(config: dict, work: Path, rubric: dict) -> Dict[str, Any]:
    patterns = _read_json(ASSETS / "undergrad_references.json", "reference patterns")
    try:
        author = ugs_config.annotation_author(REPO_ROOT)
    except ugs_config.ConfigError as error:
        raise DriverError(str(error)) from None
    probe = work / "vision_probe.json"
    return {
        "rubric": rubric,
        "entries": load_table(LANGUAGE_TABLE),
        "criteria_doc": load_criteria(CRITERIA_FILE),
        "hints": load_hints(ASSETS / "language_hints.json"),
        "vision_ok": probe.is_file() and _read_json(probe, "vision probe").get("ok") is True,
        "settings": {
            "colors": config["annotation.colors"], "author": author, "quote_chars": config["references.quote_chars"],
            "url_timeout_s": config["references.url_timeout_s"], "max_retries": config["references.max_retries"],
            "patterns": patterns["standard_patterns"], "ref_comments": patterns["comments"],
            "annex_template": (ASSETS / "annex.template.html").read_text(encoding="utf-8"),
        },
    }


def _calibration_note(work: Path, loop: int, prompts: Dict[str, str]) -> str:
    """The note of the previous loop's batch, empty on loop 1 (band written `83 to 93`, reasons joined by `; `)."""
    if loop <= 1:
        return ""
    batch = _read_json(work / f"loop-{loop - 1}" / "batch.json", "previous batch")
    band = lambda b: f"{b[0]} to {b[1]}"
    return fill(prompts["calibration_note"], {
        "LOOP": str(loop), "MEAN": str(batch["mean"]), "MEAN_BAND": band(batch["mean_band"]),
        "SD": str(batch["sd"]), "SD_BAND": band(batch["sd_band"]), "VERDICT": str(batch["verdict"]),
        "REASONS": "; ".join(batch.get("reasons", []))})


def _stopped_step(ledger_path: Path, report_id: str, step: Optional[str]) -> Optional[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Name the step that raised a NotRun: the step on_step announced last, a grade step narrowed to its open item.

    Details:
        The first open line of the whole ledger is not the answer: a figure line can be open before the language
        step that failed. A grade stop keeps the label of the grade item still open, as the run has always named it.

    Inputs:
        ledger_path (Path): the work ledger
        report_id (str): the report whose step raised
        step (str | None): the step announced by on_step, None when no step was active

    Outputs:
        label (str | None): None when no step was active; the open grade line when a grade step stopped on one;
        otherwise the step name.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    if step != "grade":
        return step
    open_items = [s["label"] for s in parse_ledger(read_ledger(ledger_path))
                  if s["report_id"] == report_id and s["label"].startswith("grade ") and s["mark"] == " "]
    return open_items[0] if open_items else step


def parse_steps(value: Optional[str]) -> Optional[List[str]]:
    """
    Purpose: Read the comma list of `run --steps` and refuse a step name the grading run does not have (N1).
    Inputs:
        value (str or None): the comma-separated step names, None for every step.
    Outputs:
        Optional[List[str]]: the names in the order given, or None when no list was given.
    Raises:
        DriverError: a name is not one of ugs_run.STEPS; the message names it.
    """
    if value is None:
        return None
    names = [part.strip() for part in value.split(",") if part.strip()]
    for name in names:
        if name not in STEPS:
            raise DriverError(f"unknown step '{name}', expected one of {', '.join(STEPS)}")
    return names


def cmd_run(args, call, fetch, window, count) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the five steps of every report in id order, resuming from the ledger.

    Details:
        The loop must be the current one (a first run opens loop 1). The role of each step is chosen here
        (grade and language the grader, figures the vision model, audit the auditor). An unretryable NotRun
        stops the run with one line naming the report, the step and the kind, exit 1; a resume continues
        there because the ledger keeps the step open.

    Inputs:
        args (Namespace): `work`, `reports`, `loop`, `only`, `dry_run`
        call, fetch, window, count: injected (tests), or None

    Outputs:
        code (int): 0, or 1 when a model step could not run.

    Raises:
        DriverError: a refusal.
    --------------------------------------------------------------------------
    """
    config = _load_config()
    work = _work_dir(Path(args.work))
    reports = Path(args.reports).resolve()
    try:
        report_prepare._check_work_dir(reports, work)
    except report_prepare.PrepareError as error:
        raise DriverError(str(error)) from None
    current = _current_loop(work)
    if args.loop != current:
        raise DriverError(f"loop {args.loop} is not the current loop")
    ids = _read_json(work / report_prepare.IDS_FILE_NAME, "id map")
    wanted = sorted(ids) if not args.only else [args.only]
    if any(report_id not in ids for report_id in wanted):
        raise DriverError("unknown report id")
    if args.dry_run:
        _emit({"dry_run": True, "step": "run", "loop": current, "reports": len(wanted)})
        return EXIT_OK
    rubric = _read_json(work / "rubric.json", "rubric")
    model_call, model_window, model_count = _inputs(call, window, count, config, work)
    # The actions are recorded only on the real run: an injected call (tests) writes nothing to the machine's log.
    active: Dict[str, Optional[str]] = {"step": None}  # the step running now, set by on_step; None before any
    emitter = _action_emitter(OllamaDeps(config["driver.count_timeout_s"]) if call is None else None,
                              lambda: _step_role(config, active["step"]), _stamp)
    ctx = _context(config, model_window, model_count, emitter)
    services = _services(config, work, rubric)
    note = _calibration_note(work, current, ctx.prompts)
    state = work / "loop_state.json"
    if not state.is_file():
        state.write_text(json.dumps({"loop": current}), encoding="utf-8")
    calls = {step: (lambda prompt, schema, images=None, kind=kind: model_call(kind, prompt, schema, images))
             for step, kind in STEP_KIND.items()}
    only_steps = parse_steps(getattr(args, "steps", None))
    for report_id in wanted:
        try:
            result = run_report(work, report_id, current, reports / ids[report_id], calls, ctx, services, note, fetch,
                                on_step=lambda name: active.update(step=name), only_steps=only_steps)
        except NotRun as error:
            _emit({"report_id": report_id, "step": _stopped_step(work / "ledger.md", report_id, active["step"]),
                   "status": "not_run", "kind": error.kind})
            return EXIT_NOT_RUN
        states = list(result["steps"].values())
        line = {"report_id": report_id, "status": result["status"], "done": states.count("done"),
                "blocked": states.count("blocked")}
        if "reason" in result:  # a report refused by its own pages or language: named, the batch goes on
            line["reason"] = result["reason"]
        _emit(line)
    return EXIT_OK


def _batch_stats(argv: List[str]) -> tuple:
    """Run batch_stats and return its exit code and what it printed on stdout."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = batch_stats_main(argv)
    return code, buffer.getvalue().strip()


def cmd_batch(args) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Analyse the totals of a loop, store the verdict, and open the next loop when the batch is out of band.

    Details:
        The verdict line of batch_stats is stored as `loop-N/batch.json` and printed. Out of band with a further
        loop allowed: the loop state advances, every ledger line except `prepare` is reopened, a note
        `loop <n> opened` is added, exit 3. A refused third loop (no `--allow-third`) is exit 2.

    Inputs:
        args (Namespace): `work`, `loop`, `allow_third`, `dry_run`

    Outputs:
        code (int): 0 in band, 3 out of band with a new loop open, 2 refused.

    Raises:
        DriverError: a refusal.
    --------------------------------------------------------------------------
    """
    work = _work_dir(Path(args.work))
    if args.loop != _current_loop(work):
        raise DriverError(f"loop {args.loop} is not the current loop")
    assessment_type = _read_json(work / "rubric.json", "rubric")["assessment_type"]
    if args.dry_run:
        _emit({"dry_run": True, "step": "batch", "loop": args.loop})
        return EXIT_OK
    code, line = _batch_stats(["--work", str(work), "--loop", str(args.loop), "--type", assessment_type, "--json"])
    if code == EXIT_REFUSAL or not line:
        raise DriverError("the batch could not be analysed")
    verdict = json.loads(line)
    (work / f"loop-{args.loop}" / "batch.json").write_text(line, encoding="utf-8")
    _emit(verdict)
    if code != EXIT_OUT_OF_BAND:
        return EXIT_OK
    nxt = ["--work", str(work), "--loop", str(args.loop), "--type", assessment_type, "--next-loop"]
    code_next, printed = _batch_stats(nxt + (["--allow-third"] if args.allow_third else []))
    if code_next != EXIT_OK:
        _emit({"status": "refused", "reason": "loop_limit"})
        return EXIT_REFUSAL
    ledger_path = work / "ledger.md"
    ledger = reopen_all(read_ledger(ledger_path), ["prepare"])
    write_ledger(ledger_path, add_note(ledger, f"loop {printed} opened"))
    return EXIT_OUT_OF_BAND


def cmd_status(args) -> int:
    """One line: the ledger counts and the first open step, as labels and numbers."""
    work = _work_dir(Path(args.work))
    text = read_ledger(work / "ledger.md")
    counts = ledger_counts(text)
    opened = first_open(text)
    _emit({"done": counts["done"], "open": counts["open"], "blocked": counts["blocked"],
           "first_open_report": opened[0] if opened else None, "first_open_step": opened[1] if opened else None})
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugs_driver")
    sub = parser.add_subparsers(dest="command")
    prep = sub.add_parser("prepare")
    prep.add_argument("--reports", required=True)
    prep.add_argument("--rubric", required=True)
    prep.add_argument("--type", required=True)
    prep.add_argument("--work", default=None)
    run = sub.add_parser("run")
    run.add_argument("--work", required=True)
    run.add_argument("--reports", required=True)
    run.add_argument("--loop", type=int, default=1)
    run.add_argument("--resume", action="store_true", help="accepted for clarity: a run always resumes from the ledger")
    run.add_argument("--only", default=None)
    run.add_argument("--steps", default=None, help="comma list of steps to run, for example language,figures")
    batch = sub.add_parser("batch")
    batch.add_argument("--work", required=True)
    batch.add_argument("--loop", type=int, required=True)
    batch.add_argument("--allow-third", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--work", required=True)
    for command in (prep, run, batch, status):
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true", help="the output is always JSON lines")
    return parser


def main(argv: Optional[List[str]] = None, *, call: Optional[Callable] = None, fetch: Optional[Callable] = None,
         window: Optional[int] = None, count: Optional[Callable] = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Entry point: dispatch a subcommand and turn every failure into an exit code and one JSON line.

    Inputs:
        argv (list[str] | None): the command line
        call, fetch, window, count: injected model call, URL fetcher, window and token counter (tests); with
            `call` given, `window` and `count` must be given too, otherwise the real ones are built

    Outputs:
        code (int): 0 done, 1 a model step could not run, 2 refusal, 3 batch out of band.
    --------------------------------------------------------------------------
    """
    args = _parser().parse_args(argv)
    if not args.command:
        _parser().print_help()
        return EXIT_REFUSAL
    try:
        if args.command == "prepare":
            return cmd_prepare(args, call, window, count)
        if args.command == "run":
            return cmd_run(args, call, fetch, window, count)
        return cmd_batch(args) if args.command == "batch" else cmd_status(args)
    except DriverError as error:
        _emit({"status": "refused", "error": str(error)})
        return EXIT_REFUSAL
    except NotRun as error:
        _emit({"status": "not_run", "kind": error.kind})
        return EXIT_NOT_RUN
    except Exception as error:  # noqa: BLE001 - only the type is printed, never a message that could hold a path
        _emit({"status": "failed", "error": type(error).__name__})
        return EXIT_NOT_RUN


if __name__ == "__main__":
    sys.exit(main())
