# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit, design committed ac8c1aa.
- Bounds (owner 2026-11-05): max_rounds 3, max_tokens 1500000, plateau 2.
- Order: plan1 to plan12 in number order. Full suite once, in plan12.
- Owner 2026-11-05: outlier |z| > 2; 150 DPI; text ratio 0.7; 22nd criterion style_consistency, comment
  only; images capped at 1568 px long edge, PNG for line art, JPEG for photos.
- find-skills 2026-11-05: no figure-evaluation equivalent; how-to-review-figure and figure-results-review
  read for ideas only.

## plan1.md

- [x] T1 language-review: 16 codes, checker, 11 tests OK, f6c17c4. Rulings: R3/R4 structure and IAG flags in `not_language`; composition flags scope research; colours Okabe-Ito (design 9); skill-creator eval loop needs a human, deferred to owner.

## plan2.md

- [x] T1 five agents + ch.04 point to language-review; contract 7 OK; flags before 9/9/9/9/0 = after 9/9/9/9/0. Ruling: G and S kept as reviewer-response top codes, finer codes from the table (no behaviour change).

## plan3.md

- [x] T1 config loader, rubric_check, grade_total: test_rubric_check 18 OK, test_grade_total 14 OK; local output truncated at the 1024-token reply cap, rubric_check and grade_total corrected by hand.

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

- [ ] T1 figure-review SKILL.md, research criteria, figure_tex, figure_render (option)

## plan10.md

- [ ] T1 four auditors and /tikz migrated to figure-review

## plan11.md

- [ ] T1 agent, command, SKILL.md, routing and docs

## plan12.md

- [ ] T1 mirrors and full checks
- [ ] T2 R35 review loop
- [ ] T3 changelog, improvements, PR
