# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit, design committed ac8c1aa.
- Bounds (owner 2026-11-05): max_rounds 3, max_tokens 1500000, plateau 2.
- Order (owner 2026-11-05): plan1-3, then plan13, plan15, plan14, then plan4 to plan12. Full suite once, in plan12.
- Owner 2026-11-05: outlier |z| > 2; 150 DPI; text ratio 0.7; 22nd criterion style_consistency, comment
  only; images capped at 1568 px long edge, PNG for line art, JPEG for photos.
- find-skills 2026-11-05: no figure-evaluation equivalent; how-to-review-figure and figure-results-review
  read for ideas only.
- 2026-11-05 owner: bridge reply reserve = code_file_output + fence_overhead_tokens (6, measured), was 1024; fix 8511579. Plan 3 coder role ornith:9b-gpu output unusable (truncation + self-import), wrapper rewrote; model for plans 4-6, 8 awaits owner.
- Owner 2026-11-05 (R39, plans 13-14, last cloud-written code): local-coder submits to the coder model the
  exact file set of aider-setup (conventions, rules, spec, plan, skill stage, progress, plan targets,
  plan message; same context-budget.json), one LLM call per plan; ONE dispatch runs the whole ledger;
  the wrapper is the auditor: code-review + security-review on the written files, bounded by the plan
  header via loop_bounds.py (R35); findings = `- [ ] audit:` lines, the driver reruns; the wrapper never codes.

## plan1.md

- [x] T1 language-review: 16 codes, checker, 11 tests OK, f6c17c4. Rulings: R3/R4 structure and IAG flags in `not_language`; composition flags scope research; colours Okabe-Ito (design 9); skill-creator eval loop needs a human, deferred to owner.

## plan2.md

- [x] T1 five agents + ch.04 point to language-review; contract 7 OK; flags before 9/9/9/9/0 = after 9/9/9/9/0. Ruling: G and S kept as reviewer-response top codes, finer codes from the table (no behaviour change).

## plan3.md

- [x] T1 config loader, rubric_check, grade_total: test_rubric_check 18 OK, test_grade_total 14 OK; local output truncated at the 1024-token reply cap, rubric_check and grade_total corrected by hand.

## plan13.md

- [x] T1 bridge split_files + exact_only: 62 OK, 596e23c
- [x] T2 driver: 15 OK, 2c3d6d9; dry run on this ledger: plan4 prompt 12919 + reply 14336. Ruling withdrawn: ~/.config/aider holds every aider file (my listing was cut by head); the driver reads them there, like aider. Driver settings in local-coder-driver.json; RED was the import failure, not run separately. Fix: `.claude/...` targets lost their leading dot (Get-PlanTargets trims both sides, aider has the same defect, to log in IMPROVEMENTS at plan 12); 16 OK.
- [x] T4 driver reruns a plan reopened by the audit (reopen stage + aider reopen message): 19 OK
- [x] T3 coder role = ornith:9b-gpu, window 49152, adopted by the owner 2026-11-05 (measured: 33/33 layers on GPU, 5921 MiB, 28 tok/s).

## plan15.md

- [x] T1 audit sandbox --audit-begin/--audit-end like aider's reviewer: 28 OK. One difference: a moved HEAD is reported, never reset.

## plan14.md

- [ ] T1 R39 local-only coding, local-coder launcher, docs and tests

## plan4.md

- [ ] T0 revise plan4 for the driver (files, test command, fixture layout per spec)
- [ ] T1 batch_stats with loop counter (test file, calibration_targets.json and two templates on disk, uncommitted; batch_stats.py absent)
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

- [ ] T1 figure-review SKILL.md, research criteria, figure_tex, figure_render (option)

## plan10.md

- [ ] T1 four auditors and /tikz migrated to figure-review

## plan11.md

- [ ] T1 agent, command, SKILL.md, routing and docs

## plan12.md

- [ ] T1 mirrors and full checks
- [ ] T2 R35 review loop
- [ ] T3 changelog, improvements, PR
