---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 1 - Skill `language-review`: the single language table

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (run in the session, judgment
> work). The SKILL.md is authored with superpowers:writing-skills and skill-creator:skill-creator.
> `progress.md` is the ledger.

**Goal:** One language-only category table that the research auditors and the undergraduate grader both
read, with a ready-to-fill correction table and a checker script.

**Architecture:** The table is data (`language_categories.json`, R6). A small stdlib checker validates it
and lists, for a given agent file, the language flags that agent uses, so plan 2 can prove nothing was
lost. No grading logic lives here.

**Tech Stack:** Python standard library, `unittest`.

**Spec:** `spec.md` items 1, D9, D10; design section 7.1.

## Global Constraints

`spec.md` "Constraints". Language only (D9): SC, M, R, D, FT, EQ, REF, Q, MAJ are NOT entries. R22: the
skill files are English; FR labels are data values. R1.x numbers come from
`.claude/skills/scientific-writing/references/composition_rules.md` and are copied, never invented.

## Review Focus

- A flag one of the five agents prints today (for example `SEMICOLON IN PROSE`, `SENTENCE TOO LONG`,
  `INFORMAL LANGUAGE`, `ACTIVE VOICE UNJUSTIFIED`) missing from the table: plan 2 would silently drop it.
- An accented French label or example mangled on load (cp1252 console).
- Two entries sharing a code, or an entry with no PDF action, accepted by the checker.

---

### Task 1: table, templates, checker, SKILL.md

**Files:**
- Create: `.claude/skills/language-review/SKILL.md`
- Create: `.claude/skills/language-review/assets/language_categories.json`
- Create: `.claude/skills/language-review/assets/correction_table.csv`
- Create: `.claude/skills/language-review/assets/correction_table.md`
- Create: `.claude/skills/language-review/references/categories.md`
- Create: `.claude/skills/language-review/scripts/lang_table_check.py`
- Test: `.claude/skills/language-review/scripts/Test/test_lang_table_check.py`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- Produces:
  - `language_categories.json`: `{"_provenance": str, "entries": [ ... ]}`. Each entry: `code` (short
    uppercase, unique), `flag` (the exact bracket text an auditor prints, or null for a new code),
    `label_fr`, `label_en`, `severity` (`minor`, `major`), `scope` (`research`, `undergraduate`,
    `both`), `rule` (R1.x string or null), `latex_action` (`direct_fix` or `replaced`), `pdf_action`
    (`{"color": str, "prefix": str}`).
  - Required coverage: G and S of `reviewer-response` split into spelling, agreement, punctuation,
    sentence structure, register, terminology, typography; plus every language flag printed by the five
    agents, found by reading them in step 1.
  - `correction_table.csv` header: `location,code,original,proposed,reason`; the `.md` is the same table
    with one filled fictitious example row per scope.
  - `lang_table_check.py`: `load_table(path: Path) -> list[dict]` raising `TableError` (a `ValueError`)
    naming the entry and key; `flags_in(agent_text: str, table: list[dict]) -> set[str]` returning the
    table flags present in an agent file; `unknown_flags(agent_text: str, table: list[dict]) -> set[str]`
    returning bracketed upper-case language flags in the agent file that the table lacks; `main(argv)`
    with `--table`, `--agent PATH` (repeatable), `--json`; exit 0 clean, 1 unknown flags found, 2 refusal.
  - `language_categories.json` is read with `encoding="utf-8"`; the script calls the stream utf-8 setup
    pattern of `extract_text.configure_streams` (own copy, R18) before printing.

- [ ] **Step 1: Inventory.** Read the language and composition sections of the five agents and
  `composition_rules.md`; list every language flag and its R1.x number in the plan's own scratch notes
  (scratchpad, not the repository).
- [ ] **Step 2: Write the failing tests:** `test_shipped_table_loads_and_codes_are_unique`;
  `test_every_entry_has_both_actions_and_both_labels`; `test_a_duplicate_code_is_refused_naming_it`;
  `test_a_missing_key_is_refused_naming_entry_and_key`; `test_content_codes_are_not_language_entries`
  (SC, M, R, D, FT, EQ, REF, Q, MAJ absent); `test_accented_labels_round_trip` (a label with `é`, `à`,
  `ç` read back identical); `test_flags_in_finds_a_planted_flag_and_unknown_flags_finds_a_new_one`
  (fixture agent text, fictitious); `test_each_of_the_five_agents_has_no_unknown_language_flag` (reads
  the real agent files); `test_cli_exit_codes` (0, 1, 2).
- [ ] **Step 3: Run** `.venv-skills\Scripts\python.exe .claude/skills/language-review/scripts/Test/test_lang_table_check.py`.
  Expected: FAIL (module absent).
- [ ] **Step 4: Write** the JSON table, the two correction templates, `references/categories.md` (one FR
  and one EN example per code, composition rules pointed to, not copied) and the checker.
- [ ] **Step 5: Run** the suite. Expected: all OK.
- [ ] **Step 6: Write `SKILL.md`** with writing-skills and skill-creator: trigger words in the first
  sentence (language correction, orthographe, grammaire, style, correction table, R1.x), the two targets
  (LaTeX for research agents, PDF annotation for undergraduate grading), where the table lives, how a
  caller cites a code. Add the script line to `.claude/rules/testing.md` (R23).
- [ ] **Step 7: Commit:** `feat(language-review): one language table with LaTeX and PDF targets (#104)`.
