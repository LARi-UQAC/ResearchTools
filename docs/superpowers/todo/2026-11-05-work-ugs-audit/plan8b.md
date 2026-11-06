---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8b - The local model adapter

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** one function sends a prompt, a JSON schema and optional images to a resolver role and returns a
validated JSON answer, or raises a typed refusal. It is the only module that talks to the daemon.

**Spec:** `spec.md` D2, D14, "Driver contracts" (the `NotRun` kinds).

## Global Constraints

No model tag in code (R2): the role name is an argument and the resolver names the tag. No fallback
(R8). A prompt that does not fit the window is never sent and never truncated. The daemon is reached only
through the deps object, so tests never open a socket (R21). Every function carries the Purpose, Inputs
and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A reply wrapped in a reasoning block is parsed after the block is removed.
- A reply that parses but breaks the schema is `invalid` and retryable; an unreachable daemon is not.
- A boolean is not an integer for the validator.
- The image cost is counted against the window before anything is sent.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_bridge.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_bridge.py`

**Reads, do not modify:** `.claude/skills/loop-engineer/scripts/bridge_images.py` (`attach_images(payload,
files, max_bytes)` returns a copy of the body with an `images` list, `ImageError` is a `ValueError`) and
`.claude/skills/loop-engineer/scripts/bridge_text.py` (`strip_reasoning(text)`).

**The bridge module, described here and not shown** (it is too large to read; the real deps import it
lazily by adding the loop-engineer scripts folder to `sys.path`): `resolve_model(role) -> str`,
`_resolve_num_ctx(model, role=None) -> int`, `probe_prompt_tokens(prompt, model, num_ctx, timeout) -> int`,
`build_payload(prompt, model, seed, num_ctx, fmt=None, *, num_predict=None) -> dict`,
`_post_generate(payload, timeout) -> dict` (the reply holds `response`, `prompt_eval_count`, `eval_count`),
the constant `DEFAULT_SEED`, and the error class `BridgeError` (a `RuntimeError`).

**Interfaces:**
- `NotRun(RuntimeError)`: built with `(kind, reason)`; attributes `kind`, `reason`, and `retryable`
  (true only for kinds `unparsable` and `invalid`). Kinds: `unadopted`, `over_budget`, `unreachable`,
  `unparsable`, `invalid`, `image`.
- `validate_answer(answer, schema: dict) -> list[str]`: a list of error strings, empty when valid.
  Keywords supported: `type` (a name or a list of names among object, array, string, number, integer,
  boolean, null), `required`, `properties`, `items`, `enum`, `minItems`, `minimum`, `maximum`. A boolean
  is neither a number nor an integer. Each error starts with a path such as `criteria[2].verdict`.
- `OllamaDeps`: the real deps, with `tag(role) -> str`, `window(tag, role) -> int`,
  `count(prompt, tag, window) -> int` (the exact count of the daemon), `payload(prompt, tag, window,
  schema, reserve) -> dict` (the bridge body with the schema as its format and `reserve` as its reply cap)
  and `post(payload, timeout) -> dict`. It imports the bridge lazily, inside its methods. A resolver
  failure becomes `NotRun("unadopted", ...)`; a count or post failure becomes `NotRun("unreachable", ...)`.
- `call_with_usage(role, prompt, schema, images=None, *, deps, timeout, reserve, image_tokens=0,
  max_image_bytes) -> tuple[dict, dict]`: resolves the tag and the window; refuses with `over_budget`
  when `deps.count(...)` plus `reserve` plus `image_tokens` per image exceeds the window, before any
  post; builds the body, attaches the images (an `ImageError` becomes kind `image`), posts, strips
  reasoning from the reply text, parses JSON (failure: `unparsable`), validates against `schema` (failure:
  `invalid`, the reason holds the first three errors and no reply text). Returns the answer and
  `{"prompt_tokens", "completion_tokens"}` taken from the reply's `prompt_eval_count` and `eval_count`
  (None when absent).
- `call(...)`: the same arguments, returns only the answer.

**Tests to write first, each failing before the code exists** (a fake deps class records what it
receives and returns canned replies):
`test_call_returns_the_parsed_answer`; `test_reasoning_block_is_removed_before_parsing`;
`test_over_budget_prompt_is_not_run_and_never_posted`; `test_image_cost_counts_against_the_window`;
`test_unparsable_reply_is_retryable`; `test_schema_violation_is_invalid_and_retryable`;
`test_unreachable_post_is_not_retryable`; `test_unadopted_role_is_not_run`;
`test_images_reach_the_posted_body`; `test_bad_image_is_kind_image`;
`test_usage_counts_come_from_the_reply_and_none_when_absent`; `test_invalid_reason_holds_no_reply_text`;
`test_validate_answer_checks_type_required_enum_and_bounds`; `test_boolean_is_not_an_integer`;
`test_validate_answer_error_path_names_the_array_index`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_bridge.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
