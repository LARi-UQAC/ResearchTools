---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 2 - Migrate the five research agents to `language-review`

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session, judgment work).
> `progress.md` is the ledger.

**Goal:** The five agents stop carrying their own language table or tag list and point to
`language-review`, with no behaviour change; the manual stops restating the table.

**Architecture:** Each agent keeps its pipeline step and its LaTeX markup rule, but the list of language
categories, flags and examples is replaced by a reference to `language_categories.json` and its R1.x
numbers. A documentation test (style of `test_deliberation_contract.py`) proves every flag each agent
used before is still reachable.

**Tech Stack:** Markdown agent definitions, Python `unittest`.

**Spec:** `spec.md` item 1, D9; design section 7.1.

## Global Constraints

`spec.md` "Constraints". No behaviour change on the research side: same flag text, same R1.x number,
same LaTeX action (direct fix for grammar, `\replaced` for style). Content codes stay in
`reviewer-response` (D9). Agent pipeline integrity (`.claude/CLAUDE.md`): steps are not removed.

## Review Focus

- A flag kept in the agent's report template (the `**Issue:** [...]` list of `paper-auditor`) but no
  longer defined anywhere: the agent would print a flag nobody explains.
- `reviewer-response` losing G and S while keeping SC to MAJ: its category table must still classify
  every reviewer comment.
- A relative link from an agent to the skill that does not resolve from `~/.claude/agents/` after
  `install-junctions.ps1 -Sync` (agents are copied, skills are junctions).

---

### Task 1: the five agents, chapter 04, contract test

**Files:**
- Modify: `.claude/agents/paper-auditor.md`
- Modify: `.claude/agents/thesis-auditor.md`
- Modify: `.claude/agents/thesis-proposal-auditor.md`
- Modify: `.claude/agents/scopus-auditor.md`
- Modify: `.claude/agents/reviewer-response.md`
- Modify: `docs/manual/04-commands.md`
- Test: `.claude/hooks/Test/test_language_review_contract.py`

**Interfaces:**
- Consumes: plan 1's `language_categories.json` (`code`, `flag`, `rule`, `latex_action`) and
  `lang_table_check.flags_in`, `unknown_flags`.
- Produces: in each agent, one short paragraph naming `.claude/skills/language-review/` and the table
  path in the form the other skill references in agents already use (absolute `~/.claude/skills/...` or
  repository-relative, whichever those agents use today, checked first).

- [ ] **Step 1: Snapshot.** Before editing, run `lang_table_check.py --agent` on each of the five files
  with `--json` and keep the output in the scratchpad: it is the "before" set of flags per agent.
- [ ] **Step 2: Write the failing test:** `test_each_agent_points_to_the_language_skill`;
  `test_no_agent_restates_the_language_table` (no Markdown table row starting with a language code such
  as `| G |` or `| S |` in any of the five); `test_every_flag_an_agent_prints_is_in_the_table` (each
  `**Issue:**` flag list and bracket flag in the five files resolves through `flags_in`);
  `test_reviewer_response_still_classifies_content_codes` (SC, M, R, D, FT, EQ, REF, Q, MAJ still listed
  there); `test_chapter_04_points_to_the_skill_instead_of_the_table`; a negative control
  `test_the_finder_reports_a_planted_unknown_flag` on fictitious text.
- [ ] **Step 3: Run** `.venv-skills\Scripts\python.exe .claude/hooks/Test/test_language_review_contract.py`.
  Expected: FAIL (pointer absent, table rows present).
- [ ] **Step 4: Edit the five agents and chapter 04.** Replace each language list by the pointer; keep the
  agent's own step, its LaTeX markup table rows that are not language rows, and its report template.
  In chapter 04 the "Comment categories processed" table keeps SC to MAJ and replaces G and S rows by
  one sentence pointing to the skill.
- [ ] **Step 5: Run** the test, then rerun step 1's command: the "after" set of flags per agent equals
  the "before" set. Expected: OK and identical sets. Record both counts in `progress.md`.
- [ ] **Step 6: Commit:** `refactor(agents): language categories come from language-review (#104)`.
