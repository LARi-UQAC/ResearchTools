# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit, design committed ac8c1aa.
- Bounds (owner 2026-11-05): max_rounds 3, max_tokens 1500000, plateau 2.
- Order: plan1, plan2, plan3, plan4, plan5, plan6, plan7, plan8, plan9, plan10. Full suite once, in plan10.
- To confirm with the owner before plan4 runs: outlier threshold (proposal |z| > 2).

## plan1.md

- [ ] T1 language-review skill, table, correction template, checker

## plan2.md

- [ ] T1 five agents and chapter 04 point to language-review, contract test

## plan3.md

- [ ] T1 config loader, rubric_check, grade_total

## plan4.md

- [ ] T1 batch_stats with loop counter
- [ ] T2 ref_check

## plan5.md

- [ ] T1 fixtures and report_prepare
- [ ] T2 figure_extract

## plan6.md

- [ ] T1 pdf_annotate
- [ ] T2 pdf_annex
- [ ] T3 figure_criteria.json (21 criteria), figure_checks

## plan7.md

- [ ] T1 undergraduate framework, prompts, spec and progress templates

## plan8.md

- [ ] T1 bridge images parameter and ugs_bridge
- [ ] T2 ugs_steps and ugs_driver
- [ ] T3 vision_probe

## plan9.md

- [ ] T1 agent, command, SKILL.md, routing and docs

## plan10.md

- [ ] T1 mirrors and full checks
- [ ] T2 R35 review loop
- [ ] T3 changelog, improvements, PR
