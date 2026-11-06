# Progress - work-ugs-audit (Issue #104)

Marks: `- [ ]` open, `- [x]` done with a short result, `- [!]` blocked with one line of reason. Nothing
else. Finished sections are compressed to one line each (ceiling 2048 tokens).

## notes

- Branch feat/work-ugs-audit, worktree .worktrees/work-ugs-audit. Bounds (owner): 3 rounds, 1500000 tokens, plateau 2.
- Done and pushed: plans 1, 2, 3, 13, 14 (R39), 15, bridge reply reserve fix, mirrors regenerated.
- Owner 2026-11-05: cloud splits files (moves only, byte for byte): bridge_text.py (c7f8866), driver_deps.py (a1f1a5f). Plans were re-cut so one driver reply (reserve 14336 tokens, whole files returned) holds one module and its test.
- Authoring rule for plans: a name with a code or data extension in plan prose becomes a file to create. Write full paths only in Files/Reads lines; elsewhere write `grade`.json (split by the backtick). Check with the targets probe or a driver dry run.
- Old plan4, plan5, plan6 deleted (replaced by 4a to 6c). plan8 not yet split: see the next-session list below.
- Cloud DATA to write before the lot (exempt from R39): undergrad_references.json (4b), annex.template.html (6b), figure_criteria.json and figure_analysis.template.json (6c), the two requirements files and rt-python-requirements.json (5), new ugs_config.json keys (roles.grader/auditor/vision, driver.reply_reserve_tokens, grade.invalid_answer_retries, select.min_word_len), then plan 7 (prompts, schemas, templates; progress template lines: `grade I01`, `language`, `figures`, `figure F01`, `audit`, `assemble`).
- Next session: split plan 8 into 8a bridge_images (loop-engineer), 8b ugs_bridge, 8c ugs_text, 8d ugs_grade, 8e ugs_audit, 8f ugs_language, 8g ugs_figures, 8h ugs_assemble, 8i ugs_ledger, 8j ugs_driver, 8k vision_probe, each one module plus one test; do NOT edit ollama_bridge.py (images are added by a new module that attaches them to the payload). Then dry run the whole ledger, then the owner's real lot.
- Open points: the old test_batch_stats.py written by the cloud is set aside (scratchpad), the local model writes it. test_settings_template_distribution fails until plan 11 adds SKILL.md to work-ugs-audit.

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

## plan16.md

- [ ] T1 BridgeDeps writes start, attempt and failed records to the bridge log

## plan4a.md

- [ ] T1 batch_stats and its test

## plan4b.md

- [ ] T1 ref_check and its test

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

- [ ] T1 undergraduate framework, prompts, spec and progress templates (cloud, before plan 8)

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
