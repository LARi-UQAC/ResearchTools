---
executor: local-coder
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - Reference measurement of a tuned model (skill opt-local-vram-llm)

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`.

**Goal:** measure, for one installed model as the machine runs it, the CPU of the model server and the
GPU load during a healthy generation, and keep that reference in `local-model-config.json` for the
watchdog to read.

**Spec:** `spec.md` decisions D1, D2.

## Global Constraints

Standard library only. No numeric literal in code: sampling interval, prompt, token count and timeouts are
read from `vram-reference.json` beside the script (each `{value, provenance}`, a missing key is an error
naming the key and the file). The tag is an argument, never written in the code (R2). Every HTTP and
subprocess call has a timeout. The write into `local-model-config.json` keeps every other key and every
other model byte for byte, goes through a temporary file and a rename, and refuses an existing file it
cannot parse. No test starts a process, calls the daemon or sleeps.

## Review Focus

- The measurement is of the model server process (names from the settings), not of the whole machine.
- A model fully on the CPU has a GPU reference near zero: it is recorded as measured, not as an error.
- The record stores the context length the server reported, because the watchdog compares it with the
  tuned `num_ctx`.

---

### Task 1: the measurement script, its settings and its tests

**Files:**
- Create: `.claude/skills/opt-local-vram-llm/scripts/vram_reference.py`
- Create: `.claude/skills/opt-local-vram-llm/scripts/vram-reference.json`
- Test: `.claude/skills/opt-local-vram-llm/scripts/Test/test_vram_reference.py`

**Interfaces:**
- `vram-reference.json` keys: `ollama_url`, `model_server_names`, `sample_seconds`, `prompt`, `num_predict`,
  `warmup_num_predict`, `call_timeout_seconds`, `generation_timeout_seconds`. Provenance: "specified" for
  the address and the names, "proposal 2026-11-09" for the rest. The prompt is a short fixed paragraph
  request.
- `ReferenceError(ValueError)`; `load_settings(path: Path) -> dict`.
- `summarize_samples(cpu_percents: list[float], gpu_percents: list[float | None]) -> dict`: `cpu_percent`
  and `gpu_percent` each `{"median": float, "min": float}`, and `samples`; `gpu_percent` is `None` when no
  GPU reading exists. Raises `ReferenceError` on an empty CPU list.
- `measure_reference(deps, tag: str, settings: dict) -> dict`: loads the tag with a warm-up request,
  reads the context length from `GET <ollama_url>/api/ps`, starts one generation of `num_predict` tokens in
  a background thread and, every `sample_seconds` until it ends, reads the model-server CPU percent of one
  core (rise of kernel plus user CPU seconds over elapsed seconds, from the process table) and the GPU
  load (`nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits`, `None` when absent). Returns
  `{"measured_at", "num_ctx", "decode_tps", "cpu_percent", "gpu_percent", "samples", "source"}`, with the
  decode speed from the response's `eval_count` and `eval_duration`. The injected `deps` hold the HTTP
  call, the process-table reader, the GPU reader, the clock and the sleep.
- `write_reference(path: Path, tag: str, record: dict) -> None`: sets `models[tag].reference_decode`.
- `main(argv) -> int`: `--tag T [--config FILE] [--dry-run]`. Default config file: the repository's
  `.claude/local-model-config.json`, resolved from the script location. `--dry-run` measures nothing and
  prints what it would do. Prints one JSON line with the record; 0 done, 2 refusal, 1 failure.

**Tests to write first, each failing before the code exists:**
`test_settings_missing_key_is_named_with_the_file`; `test_summarize_gives_median_and_min`;
`test_summarize_without_gpu_readings_gives_none`; `test_empty_cpu_samples_are_refused`;
`test_measure_reads_the_model_server_not_the_machine`; `test_decode_speed_comes_from_the_response`;
`test_record_carries_the_context_length_the_server_reported`;
`test_write_keeps_every_other_model_and_key`; `test_write_refuses_an_unreadable_file`;
`test_write_goes_through_a_temporary_file`; `test_dry_run_writes_nothing`.

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module and the settings file, run the file, every test passes.
