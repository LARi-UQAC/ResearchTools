# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit, design committed ac8c1aa.
- Bounds (owner 2026-11-05): max_rounds 3, max_tokens 1500000, plateau 2.
- Order (owner 2026-11-05): plan1-3, then plan13, plan14, then plan4 to plan12. Full suite once, in plan12.
- Owner 2026-11-05: outlier |z| > 2; 150 DPI; text ratio 0.7; 22nd criterion style_consistency, comment
  only; images capped at 1568 px long edge, PNG for line art, JPEG for photos.
- find-skills 2026-11-05: no figure-evaluation equivalent; how-to-review-figure and figure-results-review
  read for ideas only.
- 2026-11-05 owner: bridge reply reserve = code_file_output + fence_overhead_tokens (6, measured), was 1024; fix 8511579. Plan 3 coder role ornith:9b-gpu output unusable (truncation + self-import), wrapper rewrote; model for plans 4-6, 8 awaits owner.
- Owner 2026-11-05 (R39, plan14): no code in the cloud from plan14 on; local-coder gets aider's full budget
  (input 18548 + 16000 per file read, reply 14336, window 49152) through plan13's driver, one dispatch per
  progress.md. Plans 13-14 are the last cloud-written code. Question: owner wrote "local-writer"; read as
  local-coder (the coding agent). Say if local-writer must take the aider budget too.

## plan1.md

- [x] T1 language-review: 16 codes, checker, 11 tests OK, f6c17c4. Rulings: R3/R4 structure and IAG flags in `not_language`; composition flags scope research; colours Okabe-Ito (design 9); skill-creator eval loop needs a human, deferred to owner.

## plan2.md

- [x] T1 five agents + ch.04 point to language-review; contract 7 OK; flags before 9/9/9/9/0 = after 9/9/9/9/0. Ruling: G and S kept as reviewer-response top codes, finer codes from the table (no behaviour change).

## plan3.md

- [x] T1 config loader, rubric_check, grade_total: test_rubric_check 18 OK, test_grade_total 14 OK; local output truncated at the 1024-token reply cap, rubric_check and grade_total corrected by hand.

## plan13.md

- [ ] T1 bridge multi-file reply, exact-only budget
- [ ] T2 local_coder_driver.py, local_coder budget block
- [ ] T3 coder tag swept at 49152; owner adopts

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
