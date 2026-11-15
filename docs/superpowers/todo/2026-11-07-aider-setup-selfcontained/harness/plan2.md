# Plan 2 - the runner

**Goal.** `scripts/live_runner.py` renders a configuration, mounts a throwaway kit project from a fixture, runs the
kit and reports.

**Contents.** Numbered steps, each naming its file. Done means the tests pass and assert a failure path.

1. **Create `scripts/live_runner.py`.** Standard library only. It imports `check_project` and `describe` from
   `live_checks`. Every function carries a header with purpose, inputs, outputs and, when it raises, what.

2. **Add `load_config(path) -> dict`** reading `live_config.json` beside the module. Every value is an object with
   `value` and `provenance`. A missing file or key raises `ConfigError` naming the key and the file.

3. **Add `render_config(skill_dir, home_dir) -> dict`.** Copy the skill's `config` folder to the `.config/aider`
   folder of `home_dir`, replace the text `{{HOME}}` by `home_dir` (forward slashes) in every Markdown, JSON and YAML
   file, write the rendered `aider.conf.yml` as `.aider.conf.yml` of `home_dir`, and return the paths of the
   configuration file and the budget file. No `{{HOME}}` may remain: if one does, raise `ConfigError`.

4. **Add `build_commands(skill_dir, project, home_paths, expect, dry_run) -> list`** returning the argument lists the
   runner executes: PowerShell on the skill's `new-project.ps1` is a separate step, this one builds the kit command, the
   skill's own `scripts/aider-plan.ps1` with `-Path`, `-Config`, `-BudgetFile`, `-TestCommand` taken from the
   expectation, and `-DryRun` only when asked. It never passes `-NoAudit`, `-AllowCloud` or `-Model`.

5. **Add `mount(skill_dir, case, work_root, python) -> Path`**: run `new-project.ps1` for a fresh project folder, copy
   the fixture's `spec.md`, `plan<N>.md` and `progress.md` over the templates, create an empty `audit.md`, and commit
   that baseline on the branch `work`. An existing project folder is refused with a message naming it.

6. **Add `unload_models(runner)`** that asks `ollama ps` for the loaded models and stops each one, so the kit starts
   from an empty memory. The command runner is a parameter, so the tests need no daemon.

7. **Add `run_case(case, options, runner) -> dict` and `main(argv) -> int`.** `run_case` renders, mounts, unloads,
   runs the kit with the configured timeout, runs the project's own test command, calls `check_project` with the
   captured kit text, the baseline commit hash read at mount time and the configured git time limit, and returns a report with `case`, `ok`, `failures` and `log_path`. `main` prints `describe`
   and a JSON report, returns the exit codes of the spec, and removes the throwaway project unless `--keep`.

8. **Write `scripts/Test/test_live_runner.py`**, a `unittest` file that ends with `unittest.main()` and puts the parent
   folder of its own folder at the start of `sys.path` before importing the module. No model, no network, a fake
   command runner. Cover: `load_config` on a good file; a missing key naming the key and the file; `render_config`
   leaving no `{{HOME}}` and writing the rendered configuration; a leftover placeholder raising; `build_commands` never
   containing the three forbidden flags and adding `-DryRun` only when asked; a mount into an existing folder refused;
   `main` returning 2 for an unknown case.

9. **Create `scripts/live_config.json`** with the keys `work_root`, `run_timeout_s`, `git_timeout_s` and `python`, each as an object
   with `value` and `provenance`. Use the value 10800 for the timeout with the provenance "chosen by the owner,
   2026-11-07, three hours covers two audited plans on this machine".

**Done when** `scripts/Test/test_live_runner.py` passes.
