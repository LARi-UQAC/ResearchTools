---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8c - Prompt filling, page selection and reference sections

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** the pure text helpers every grading step needs: fill a prompt, pick the pages that fit a
window, find the reference list, guess the report language, and load the prompt and schema files.

**Spec:** `spec.md` D7, D8, "Driver contracts" (`StepContext`).

## Global Constraints

Python standard library only. Pure functions: the token counter is passed in (R21). Text is compared
after folding case and accents, so accented French works. Word lists live in a data file, not in code
(R6). Every function carries the Purpose, Inputs and Outputs header, and Raises when it raises on
purpose.

## Review Focus

- A filled value that itself holds `{{NAME}}` is not expanded a second time.
- A page that does not fit is never cut: it is taken whole or left out.
- A heading such as `7. Références` or `## Bibliographie` opens the reference list; the same word inside
  a sentence does not.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/work-ugs-audit/scripts/ugs_text.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_text.py`

**Reads, do not modify:** `.claude/skills/work-ugs-audit/assets/language_hints.json` (keys `fr` and `en`,
each an object whose `value` is a list of common words).

**Interfaces:**
- `PromptError` (a `ValueError`).
- `StepContext`: a dataclass with the fields named in "Driver contracts": `prompts`, `schemas`, `levels`,
  `window_tokens`, `reserve_tokens`, `count`, `grade_retries`, `audit_retries`, `min_word_len`.
- `fill(template: str, values: dict) -> str`: replaces every `{{NAME}}` (capitals and underscore) in one
  pass. A slot with no value, or a value whose name is not a slot of the template, raises `PromptError`
  naming it.
- `prompt_section(text: str, name: str) -> str`: the body under the heading `## name` up to the next
  `## ` heading; a missing section raises `PromptError`.
- `page_blocks(pages: list[str], numbers: list[int]) -> str`: for each 1-based number, a block that
  starts with the line `### Page N` followed by that page's text.
- `select_pages(item: dict, pages: list[str], budget_tokens: int, count, min_word_len: int) ->
  list[int]`: all page numbers when `count(page_blocks(all pages))` fits `budget_tokens`. Otherwise the
  pages having a Markdown heading line (starting with `#`) that shares a word of at least `min_word_len`
  letters with the item's title, criteria and checklist, kept in order while the blocks still fit; a
  page that would not fit is skipped, never cut. An empty list means nothing fits.
- `split_body_and_references(pages: list[str]) -> tuple[str, list[dict]]`: the text before the first
  heading named References, Références or Bibliographie (optionally numbered), and the entries after
  it up to the next heading of the same or a higher level. An entry is a dict with `page` (1-based) and
  `text`. An entry starts at a line beginning `[n]`, `n.`, `n)` or a bullet; continuation lines join it;
  with no such marker, blank lines separate entries. No such heading: the whole text and an empty list.
- `detect_language(pages: list[str], hints: dict) -> str`: `fr` or `en`, by which list of common words
  occurs more often; a tie gives `en`.
- `load_hints(path: Path) -> dict`: the two word lists as plain lists; a missing key raises `PromptError`
  naming it.
- `read_pages(work_dir: Path, report_id: str) -> list[str]`: the text of `R01/pages/p001.md`, `p002.md`
  and so on, in numeric order; no page raises `PromptError`.
- `load_prompts(prompts_dir: Path) -> dict`: file stem to text for every Markdown file of the folder.
- `load_schemas(path: Path, required: list[str]) -> dict`: the JSON object; a missing key of `required`
  raises `PromptError` naming it.

**Tests to write first, each failing before the code exists:**
`test_fill_replaces_every_slot`; `test_fill_does_not_expand_a_value_twice`;
`test_fill_raises_on_an_unfilled_slot_and_on_an_unknown_value`; `test_prompt_section_returns_one_body`;
`test_prompt_section_missing_raises`; `test_page_blocks_tag_each_page`;
`test_all_pages_when_they_fit`; `test_matching_headings_select_pages_when_they_do_not_fit`;
`test_accented_heading_matches_an_unaccented_word`; `test_a_page_over_budget_is_skipped_not_cut`;
`test_nothing_fits_gives_an_empty_list`; `test_references_after_a_numbered_heading`;
`test_reference_word_in_a_sentence_is_not_a_heading`; `test_entries_with_continuation_lines`;
`test_entries_split_on_blank_lines_without_markers`; `test_no_reference_heading_gives_empty_list`;
`test_entry_page_is_where_it_starts`; `test_detect_language_french_and_english_and_tie`;
`test_load_hints_names_a_missing_key`; `test_read_pages_in_numeric_order`;
`test_load_schemas_names_a_missing_key`.

- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ugs_text.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
