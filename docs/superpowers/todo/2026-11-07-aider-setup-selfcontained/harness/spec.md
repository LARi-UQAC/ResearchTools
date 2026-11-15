# Spec - live test runner for the aider kit

**Goal.** Two standard-library Python modules that replay the kit's live tests on demand: one plan, then two
plans. They mount a throwaway kit project from a fixture, run the repository's own `aider-plan.ps1` on it with
a configuration rendered from the repository, and check the result. They are the tools the owner re-runs after
every change to the kit.

**Contents.** The decisions both plans rely on. Nothing else.

## Decisions

- Everything lives in the aider-setup skill folder, called `SKILL` below. Modules in `SKILL/scripts/`, tests in
  `SKILL/scripts/Test/`, fixtures in `SKILL/scripts/Test/live/<case>/` where `<case>` is `single` or `multi`.
- Each fixture folder holds `spec.md`, one `plan<N>.md` per plan, `progress.md` and an expectation file
  `expect.json`. The expectation file has the keys `test_command` (text), `modules` (relative paths), `tests`
  (relative paths) and `plans` (plan file names).
- The live run needs the local models and takes a long time. It is never part of the offline suite: no module or
  test of this effort is named so that `run-offline-tests.ps1` runs it. Only the pure checks and the pure helpers
  have offline tests.
- The tests of the project under test live in a folder named exactly `Test`, as in ResearchTools.
- Every number and path comes from a configuration file `SKILL/scripts/live_config.json`, each value with its
  provenance (R0, R4): the work folder, the run timeout in seconds, the time limit of one git call in seconds, the interpreter for the project environment.
  A missing key is an error that names the key and the file (R3).
- Failure is reported, never hidden: the report lists every failed check, the exit code is 0 when all checks
  pass, 1 when a check fails, 2 when the run could not start (R12).

## Interfaces shared by both plans

- `check_project(project_dir, expect, log_text, baseline, git_timeout_s) -> list of str`, in
  `SKILL/scripts/live_checks.py`: one text per failed check, an empty list when the run is good. `baseline` is the
  hash of the commit made when the project was mounted, supplied by the runner. `git_timeout_s` is the time limit of
  every git call, read by the runner from `live_config.json` and passed in, so the checker holds no number (R0).
- `main(argv) -> int`, in `SKILL/scripts/live_runner.py`: command line `single`, `multi`, with `--dry-run` that runs
  the kit's own dry run and loads no model, and `--keep` that keeps the throwaway project.

## Language and conventions

- **Language and version:** Python 3.11 or later, standard library only.
- **Case of names:** functions are `verb_complement` in lower snake case (`parse_moves`), private helpers
  start with an underscore, classes are `PascalCase`, constants are `UPPER_SNAKE_CASE`, variables are
  lower snake case.
- **Documentation comment:** a docstring with the parts Purpose, Inputs, Outputs and, when the function
  raises on purpose, Raises.
- **Types:** a type annotation on every parameter and every return value.
- **Tests:** `unittest`, in the folder `Test` beside the source, one file `test_<module>.py` per module.
  Each test file ends with `unittest.main()` and puts the parent folder of its own folder at the start of
  `sys.path` before it imports the module.
- **Format and lint:** none required here.

