---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4b - The undergraduate reference check

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** a script reports each reference's form, reachability and citation in the text, and never
moves a score.

**Spec:** `spec.md` D8, "Constraints".

## Global Constraints

The network is injected: the default fetch function is never called in tests (R21). Patterns come from
the data file, timeouts and retries from the configuration (R0). Outputs carry statuses and counts,
never a reference's text beyond its index. Python standard library only. Every function carries the
Purpose, Inputs and Outputs header, and Raises when it raises on purpose.

## Review Focus

- A URL that times out or answers 403: `unreachable` or `blocked`, never an exception.
- A standard written `ISO9001:2015`, `ISO 9001`, `CSA C22.1-21`, `CAN/CSA-Z462`, `IEEE Std 1584`:
  classified as standards.
- Accented body text searched correctly.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ref_check.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ref_check.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/assets/undergrad_references.json` (the key
`standard_patterns` is a list of objects with `name`, `regex` and `provenance`; the key
`accepted_kinds` lists `standard`, `url`, `other`), `.claude/skills/work-ugs-audit/scripts/ugs_config.py`
(`load(path)` returns a flat dict of dotted keys; here `references.url_timeout_s` and
`references.max_retries`; `default_path()` names the file).

**Interfaces:**
- `classify(ref: str, patterns: list[dict]) -> str`: `standard` when a pattern matches, `url` when the
  text holds an http or https address, else `other`.
- `check(ref: str, body_text: str, patterns: list[dict], fetch, timeout: float, retries: int) -> dict`:
  returns `kind`, `status` (`form-ok`, `malformed`, `reachable`, `unreachable`, `blocked`,
  `not_checked`) and `cited` (bool). A standard is `form-ok` when it matches a pattern completely,
  else `malformed`. A URL is fetched through `fetch(url, timeout) -> int`, which returns an HTTP status
  or raises `OSError`: 200 to 399 is `reachable`, 401 or 403 is `blocked`, any other status or an
  error after `retries` further tries is `unreachable`. `other` is `not_checked`. `cited` is true when
  a bracket marker with the reference's number, or the standard's identifier, appears in `body_text`.
- `check_all(refs: list[str], body_text: str, patterns, fetch, timeout, retries) -> list[dict]`: one
  result per reference with its 1-based `index`.
- `main(argv)`: `--refs FILE --body FILE [--patterns FILE] [--json]`; the references file holds one
  reference per line. It prints a JSON list of the results. Exit 0 on a completed check, 2 on a
  refusal (missing file, bad patterns file).

**Tests to write first, each failing before the code exists:**
`test_standard_forms_are_classified` (the five forms of the Review Focus);
`test_a_malformed_standard_is_reported`; `test_reachable_unreachable_blocked_from_injected_fetch`
(200, `OSError`, 403); `test_retries_follow_the_argument` (the fetch is called retries plus one
times); `test_cited_by_number_and_by_standard_id`; `test_an_uncited_reference_is_reported`;
`test_accented_body_text_is_searched_correctly`; `test_no_real_network_in_the_suite` (the default
fetch is replaced by one that fails the test if called); `test_missing_patterns_file_is_a_refusal`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ref_check.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
