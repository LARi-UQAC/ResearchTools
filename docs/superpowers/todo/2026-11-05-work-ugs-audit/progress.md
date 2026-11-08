# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit. Bounds (owner): 3 rounds, 1500000 tokens, plateau 2.
- Done and pushed: plans 1, 2, 3, 13, 14 (R39), 15, bridge reply reserve fix, mirrors regenerated.
- Owner 2026-11-05: cloud splits files (moves only, byte for byte): bridge_text.py (c7f8866), driver_deps.py (a1f1a5f). Plans were re-cut so one driver reply (reserve 14336 tokens, whole files returned) holds one module and its test.
- Authoring rule for plans: a name with a code or data extension in plan prose becomes a file to create. Write full paths only in Files/Reads lines; elsewhere write `grade`.json (split by the backtick). Check with the targets probe or a driver dry run.
- Old plan4, plan5, plan6, plan8 deleted (replaced by 4a to 6c and 8a to 8l; shared contracts in spec.md "Driver contracts"). Cloud DATA and plan 7 are written before the lot (exempt from R39). The old test_batch_stats.py of the cloud is set aside; the local model writes it.
- Plan 8 order is by dependency: 8a bridge_images, 8b ugs_bridge, 8c ugs_text, 8d ugs_ledger, 8e ugs_grade, 8f ugs_audit, 8g ugs_language, 8h ugs_figures, 8i ugs_assemble, 8j ugs_run, 8k ugs_driver, 8l vision_probe. The driver was cut in two (8j, 8k): one reply holds one module and its test.
- Open: test_settings_template_distribution fails until plans 9 and 11 add SKILL.md to figure-review and work-ugs-audit. Inventory lines in testing.md for all new test files are the cloud's job in plan 11 (the file is over the read ceiling).

## plan1.md

- [x] T1 language-review skill, f6c17c4

## plan2.md

- [x] T1 five agents migrated to language-review

## plan3.md

- [x] T1 config loader, rubric_check, grade_total (cloud-written, before R39)

## plan13.md

- [x] T1 to T4 bridge split_files, driver, reopen rerun, coder role ornith window 49152

## plan14.md

- [x] T1 R39 and the launcher, 93ce66f

## plan15.md

- [x] T1 audit sandbox


## plan4a.md

- [x] T1 batch_stats and its test: 15 tests ok, signatures and test names match the plan (aider commits 9115747 to 2d7eb2c)

## plan4b.md

- [x] T1 ref_check and its test: kit run u4b, 9 tests ok, signatures and test names match; residuals after 3 audit rounds: HTTP status literals (domain constants), no full header on default_fetch, reviewer remark on citation matching

## plan5a.md

- [ ] T1 _pdf_fixtures and its test

## plan5b.md

- [ ] T1 report_prepare and its test

## plan5c.md

- [ ] T1 figure_extract and its test

## plan5d.md

- [ ] T1 figure_image and its test

## plan6a.md

- [ ] T1 pdf_annotate and its test

## plan6b.md

- [ ] T1 pdf_annex and its test

## plan6c.md

- [ ] T1 figure_checks and its test

## plan7.md

- [x] T1 framework, prompts, schemas, templates written; ugs roles not adopted (step 3 skipped)

## plan8a.md

- [ ] T1 bridge_images and its test

## plan8b.md

- [ ] T1 ugs_bridge and its test

## plan8c.md

- [ ] T1 ugs_text and its test

## plan8d.md

- [ ] T1 ugs_ledger and its test

## plan8e.md

- [ ] T1 ugs_grade and its test

## plan8f.md

- [ ] T1 ugs_audit and its test

## plan8g.md

- [ ] T1 ugs_language and its test

## plan8h.md

- [ ] T1 ugs_figures and its test

## plan8i.md

- [ ] T1 ugs_assemble and its test

## plan8j.md

- [ ] T1 ugs_run and its test

## plan8k.md

- [ ] T1 ugs_driver and its test

## plan8l.md

- [ ] T1 vision_probe and its test

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
