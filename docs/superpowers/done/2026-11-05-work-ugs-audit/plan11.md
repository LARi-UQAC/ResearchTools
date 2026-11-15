---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 11 - Agent, command, skill definition, routing and documentation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (session, judgment work). The
> SKILL.md is authored with superpowers:writing-skills and skill-creator:skill-creator. `progress.md` is
> the ledger.

**Goal:** The professor can type `/work-ugs-audit`, the `work-ugs-audit` agent drives the plan 8 driver while
staying blind to report content, and every inventory names the three new skills (`language-review`, `figure-review`, `work-ugs-audit`).

**Architecture:** The agent is a cheap cloud wrapper in the `local-coder` shape: tools `Read, Bash`,
reads only `progress.md` and the driver's JSON lines, pauses for the rubric confirmation and at the end of
each batch, and ends with the pipeline checklist. The command is a thin wrapper over the agent.

**Tech Stack:** Markdown definitions, existing documentation pages.

**Spec:** `spec.md` items 1 to 3, D1 to D11; design section 7.2 "Agent pipeline".

## Global Constraints

`spec.md` "Constraints". R22 (definition files English; the agent speaks to the professor in his
language). R31 and R33: README, Architecture, the routing table and the manual pages change in this same
PR. The agent never runs `Read` on a path under the reports folder except `_correction/progress.md` and
`_correction/spec.md` (the rubric, written by the professor, carries no student text).

## Review Focus

- The agent reading `grade.json`, `annotations.json`, a page Markdown file or an annotated PDF: forbidden;
  the definition states it, and a documentation test fails if the definition names any of those files
  as something to read.
- The rubric confirmation pause skipped by a caller in a hurry: `PIPELINE-PAUSED @ rubric-confirmation`
  is mandatory (agent pipeline integrity).
- A third loop started without the professor's answer.
- The description's first sentence lacking trigger words (Codex trims to whole sentences).

---

### Task 1: definitions, routing, documentation

**Files:**
- Create: `.claude/agents/work-ugs-audit.md`
- Create: `.claude/commands/work-ugs-audit.md`
- Create: `.claude/skills/work-ugs-audit/SKILL.md`
- Modify: `.claude/CLAUDE.md`
- Modify: `README.md`
- Modify: `Architecture.md`
- Modify: `docs/manual/04-commands.md`
- Modify: `docs/manual/05-agents.md`
- Modify: `docs/manual/06-skills.md`
- Test: `.claude/hooks/Test/test_work_ugs_audit_contract.py`

**Interfaces:**
- Consumes: `ugs_driver.py` subcommands and exit codes (plan 8), `batch_stats` verdicts (plan 4),
  `vision_probe.py` (plan 8).
- Produces: agent steps, in order: 1 `ugs_driver.py prepare`, show `spec.md` and figure counts,
  `PIPELINE-PAUSED @ rubric-confirmation`; 2 `vision_probe.py` for the vision role; 3 `ugs_driver.py run`,
  polling `status`; 4 `ugs_driver.py batch`, present the verdict and options from numbers only (accept,
  re-grade, adjust one item's anchors); 5 out of band: next loop with the calibration note, after loop 2
  `PIPELINE-PAUSED @ third-loop`; 6 final checklist, outputs listed by relative path inside `_correction/`.
  Model roles named, never tags; the owner action `model_resolver.py --adopt-role ugs-grader|ugs-auditor|ugs-vision`
  documented.

- [ ] **Step 1: Write the failing test:** `test_agent_tools_are_read_and_bash_only`;
  `test_agent_names_no_forbidden_read_target` (`grade.json`, `annotations.json`, `pages/`,
  `annotated.pdf`, `ids.json`); `test_agent_has_both_pause_points`; `test_agent_ends_with_a_checklist`;
  `test_command_dispatches_the_agent`; `test_skill_description_first_sentence_has_trigger_words` (grading,
  correction, rubric or grille, undergraduate or premier cycle, PDF) and is at least 120 characters;
  `test_routing_table_readme_architecture_and_manual_name_the_three_skills`; a negative control on a
  fictitious definition naming `grade.json`.
- [ ] **Step 2: Run** `.venv-skills\Scripts\python.exe .claude/hooks/Test/test_work_ugs_audit_contract.py`.
  Expected: FAIL.
- [ ] **Step 3: Write** the agent, the command, the SKILL.md (writing-skills, skill-creator), the routing
  row in `.claude/CLAUDE.md`, the README row and counts, the Architecture relation, and the three manual
  pages (chapter 06 also gets `language-review` and `figure-review`; chapter 04 names `/tikz` pointing to `figure-review`).
- [ ] **Step 4: Run** the test. Expected: OK.
- [ ] **Step 5: Commit:** `feat(work-ugs-audit): agent, /work-ugs-audit command, routing and docs (#104)`.
