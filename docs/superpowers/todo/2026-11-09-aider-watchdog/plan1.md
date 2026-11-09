---
executor: local-coder
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - The watchdog script

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`.

**Goal:** stop the process in progress when the model server and the GPU have stopped working, as
measured against the reference that plan 2 wrote for this machine and this model.

**Spec:** `spec.md` decisions D1 to D6. Plan 2 writes the reference file this script reads.

## Global Constraints

Standard library only. No numeric literal in code: every threshold is read from `aider-watchdog.json`
(a missing key is an error that names the key and the file). Every subprocess and HTTP call has a
timeout from the file. Output paths are resolved inside the logs folder. No test starts a process,
sleeps or reads the real clock.

## Review Focus

- Nothing is judged before the model is loaded, and not in the `testing` state.
- A dimension whose reference is negligible (a model fully on the CPU has a GPU reference near zero) is
  ignored, so it can neither hide nor cause a stall.
- A model with no reference, or loaded with another context than the one in its reference, is never
  judged.

---

### Task 1: the script, its settings and its tests

**Files:**
- Create: `.claude/skills/aider-setup/scripts/aider_watchdog.py`
- Create: `.claude/skills/aider-setup/scripts/aider-watchdog.json`
- Test: `.claude/skills/aider-setup/scripts/Test/test_aider_watchdog.py`

**Interfaces:**
- `aider-watchdog.json`: each key is `{"value": ..., "provenance": "..."}`. Keys: `poll_seconds` 30,
  `negligible_reference_percent` 5, `low_readings` 6, `watched_states` `["writing", "auditing"]`,
  `terminal_states` `["done", "done_with_blocked", "failed"]`, `model_server_names` `["ollama",
  "llama-server"]`, `ollama_url` `"http://127.0.0.1:11434"`, `call_timeout_seconds` 30. Provenance of the
  numbers: "proposal 2026-11-09, to be tuned by the owner"; of the lists and the URL: "specified".
  The threshold of a low reading is not here: it is the minimum measured in the reference.
- `WatchdogError(ValueError)`; `load_settings(path: Path) -> dict`: key to value, refusing a missing
  file, a missing key or an entry without provenance, naming the key and the file.
- `Reading` (frozen dataclass): `model: str | None` (loaded model, `None` when none), `cpu_percent: float`
  (model-server CPU as a percent of one core, from the rise of its CPU seconds between two polls),
  `gpu_percent: float | None` (`None` when `nvidia-smi` is absent), `context_length: int | None`,
  `state: str`, `plan: str | None`.
- `load_references(path: Path) -> dict[str, dict]`: reads `models[tag].reference_decode` of
  `local-model-config.json` (`num_ctx`, `cpu_percent` and `gpu_percent` each with `median` and `min`);
  a missing file or entry gives an empty dict, an unparsable file raises `WatchdogError`.
- `Tracker(references: dict[str, dict], settings: dict)` (class), method `update(reading: Reading) ->
  str | None`. Returns `None` while nothing is to be judged: no model loaded, a state not in
  `watched_states`, a model with no reference, or a `context_length` different from the reference
  `num_ctx`. Otherwise a reading is low when every dimension whose reference median is at least
  `negligible_reference_percent` is under the reference minimum of that dimension (a `gpu_percent` of
  `None` on a judged GPU dimension means the reading is not judged). Returns `"stall"` once
  `low_readings` consecutive readings are low, then resets its count; one reading that is not low resets
  it.
- `read_reading(deps, settings, previous_cpu_seconds, previous_at) -> Reading`: the model from
  `GET <ollama_url>/api/ps` (name and context length), the server CPU from the process table
  (`Get-CimInstance Win32_Process`, kernel plus user ticks over `TICKS_PER_SECOND`, a named constant
  for 100-nanosecond ticks per second) summed over `model_server_names`, the GPU from `nvidia-smi
  --query-gpu=utilization.gpu --format=csv,noheader,nounits` (highest line, `None` when absent), and the
  state and plan from the run record JSON.
- `stop_work(deps, driver_pid, settings) -> bool`: finds the direct child of the driver that is not
  this script and has the most CPU seconds in its subtree, stops it with `taskkill /PID <pid> /T /F`,
  reads the process table again and returns whether it is gone.
- `append_log_line(logs_dir: Path, event: str, reading: Reading) -> None` and
  `write_stop_signal(logs_dir: Path, plan: str | None) -> None`: write `watchdog.log` (one JSON line:
  time, event, model, `cpu_percent`, `gpu_percent`, plan) and `watchdog-stop.json` (the plan name).
- `main(argv) -> int`: `--driver-pid N --run-record PATH --logs-dir DIR --settings FILE --reference FILE`. Polls until the
  driver is gone or the run record state is terminal (returns 0). On `"stall"`: `stop_work`, log line
  `stall`, signal file. Nothing else is ever written. A bad argument or settings file prints one
  JSON error line and returns 2.

**Tests to write first, each failing before the code exists:**
`test_settings_missing_key_is_named_with_the_file`; `test_nothing_is_judged_before_the_model_is_loaded`;
`test_nothing_is_judged_in_the_testing_state`; `test_a_model_with_no_reference_is_not_judged`;
`test_load_references_reads_the_measured_entry`; `test_unparsable_reference_file_is_refused`;
`test_healthy_readings_never_stall`; `test_low_readings_in_a_row_make_a_stall`;
`test_one_recovered_reading_resets_the_count`; `test_negligible_gpu_reference_is_ignored`;
`test_each_model_uses_its_own_reference`; `test_a_model_loaded_with_another_context_is_not_judged`;
`test_stop_work_picks_the_child_with_the_most_cpu_and_not_itself`;
`test_stop_work_reports_a_process_that_is_still_alive`;
`test_stall_writes_one_log_line_with_cpu_gpu_and_plan_and_the_signal`;
`test_main_returns_zero_on_a_terminal_state`; `test_bad_settings_return_2`.

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module and the settings file, run the file, every test passes.
