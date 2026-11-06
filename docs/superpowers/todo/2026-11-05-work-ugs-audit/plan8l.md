---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8l - The vision capability probe

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder, and the folder holding the fixture helper, at the start of
> `sys.path`.

**Goal:** a script decides whether the vision role can read a chart (axis titles, unit, curve count) and
measures what one image costs that model, and writes the verdict that the figure step reads.

**Spec:** `spec.md` D14, "Model roles", "Driver contracts" (the probe answer, the work folder).

## Global Constraints

Local models only. The model call is injected (R21). The fixture image is invented; no report is used
(R34). No model tag in code (R2). Every function carries the Purpose, Inputs and Outputs header, and
Raises when it raises on purpose.

## Review Focus

- A wrong axis title, unit or curve count makes the probe not ok.
- A model that cannot run makes the probe not ok with its kind, and nothing else is claimed.
- The image cost is the difference between the prompt counts with and without the image.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/vision_probe.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_vision_probe.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/scripts/ugs_bridge.py` (`call_with_usage(role,
prompt, schema, images=None, *, deps, timeout, reserve, image_tokens, max_image_bytes)` returns the
answer and a usage dict with `prompt_tokens`; `OllamaDeps`; `NotRun` with `kind`),
`.claude/skills/work-ugs-audit/scripts/ugs_text.py` (`load_schemas`, `load_prompts`),
`.claude/skills/work-ugs-audit/scripts/ugs_config.py` (`load`, `default_path`),
`.claude/skills/figure-review/scripts/Test/_pdf_fixtures.py`. The probe prompt is the prompt file named
`vision_probe`, with no slot; its schema is the `vision_probe` key of the schemas file.

**Interfaces:**
- `probe(call_usage, image: Path, expected: dict, prompt: str, schema: dict) -> dict`: `call_usage(prompt,
  schema, images)` returns `(answer, usage)`. Calls it twice, with the image and without. Returns
  `{ok, answers, image_tokens}`: `ok` is true only when the answered `x_title`, `y_title` and `unit` each
  equal the expected text after folding case, accents and spaces, and `curve_count` equals the expected
  integer. `image_tokens` is the prompt token count with the image minus the count without it, None when
  either count is missing. A `NotRun` from the first call gives `{ok: false, kind, answers: None,
  image_tokens: None}`; one from the second call keeps `ok` and gives `image_tokens` None.
- `main(argv=None, *, call_usage=None) -> int`: `--work DIR --image FILE --expected FILE [--dry-run]
  [--json]`. Builds the real `call_usage` from the configuration (role `roles.vision`, reserve, timeout)
  when none is injected. Writes `vision_probe`.json (keys `ok`, `image_tokens`, `kind`) in the work
  folder, resolved inside it (R24), and prints the same object. Exit 0 when the file is written, whatever
  `ok` says, 2 on a refusal (missing file, bad expected file, path outside the work folder), 1 on a
  failure.

**Tests to write first, each failing before the code exists:**
`test_probe_passes_when_the_four_facts_come_back`; `test_probe_fails_on_a_wrong_axis_title`;
`test_probe_fails_on_a_wrong_curve_count`; `test_comparison_ignores_case_accents_and_spaces`;
`test_not_run_on_the_first_call_is_not_ok_with_its_kind`;
`test_image_tokens_is_the_difference_of_the_two_prompt_counts`; `test_missing_count_gives_none`;
`test_main_writes_the_verdict_file_inside_the_work_folder`; `test_main_refuses_a_path_outside_the_work_folder`;
`test_dry_run_writes_nothing`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_vision_probe.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
