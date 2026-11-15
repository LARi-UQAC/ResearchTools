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

## plan4c.md

- [x] T1 SSRF guard in ref_check: kit run u4cc, 18 tests ok, the nine plan tests present, guard refuses loopback, private, link-local, reserved, multicast and unspecified hosts at every hop; residuals after 3 audit rounds: reasoning comments left in is_public_host (rule R103), a catch-all in default_fetch (R8), reviewer wrote no report in round 3

## plan4d.md

- [x] T1 complete the address guard: night n3 wrote it (26 tests, one failing because `HTTPSConnection` has no `server_hostname`), the cloud then rewrote the module cleanly on 2026-11-12 with the owner's order: pinned connection classes, the requested path, redirects validated at every hop, `ugs_config.load` called with its path, key `references.max_redirects` added to the configuration; 33 tests ok

## plan5a.md

- [x] T1 _pdf_fixtures and its test: kit run u5a, 10 tests ok, signatures and plan tests match; stopped at the audit round limit (reviewer asked for the numeric literals of a fixture helper to become constants, which rule R0 allows inside a fixture)

## plan5b.md

- [x] T1 report_prepare and its test: kit run u5b (4th attempt), 8 tests ok, signatures and plan tests match; stopped at the audit round limit. Residuals: docstrings and comments in French (the first attempts ran before the English language settings), one comment records reasoning (R103), module constants for id and page padding, --dry-run skips the containment check; the id map file is named `ids` as plans 5b and 8k say, while plan 11 says ids.json (to align when plan 11 is run) ; 2026-11-12: residuals cleared by the owner-ordered rewrite (English, constants moved to the configuration, ids.json, containment checked in a dry run, 15 tests ok)

## plan5e.md

- [x] T1 fixed failure message of report_prepare: done with the 2026-11-12 rewrite of plan 5b (no exception text is printed, only its type; test_an_unexpected_failure_prints_the_type_and_no_path)

## plan5c.md

- [x] T1 figure_extract and its test: second night un5b 88 %, tests 8/12 red; corrected in the session (owner order, deviation from R39): vector line clusters (PyMuPDF treats a zero-height rectangle as empty), label zone, path confinement, Raises headers; tests 14/14 green

## plan5d.md

- [x] T1 figure_image and its test: second night un5b 100 %, tests 8/8 green (the reworded plan with exact PyMuPDF calls worked; was not scored the first night)

## plan6a.md

- [x] T1 pdf_annotate and its test: second night un5b 98 %, tests 12/13; one test read only the first print of a mocked stdout, fixed with StringIO; tests 13/13 green

## plan6b.md

- [x] T1 pdf_annex and its test: second night un5b 89 %, tests 4/7; corrected in the session: annex built in memory (Windows kept the temp file locked), test compares text with whitespace folded, main refuses missing inputs and non-PDF with exit 2, default template read from assets; tests 10/10 green

## plan6c.md

- [x] T1 figure_checks and its test: night n2 plan 7, 13 tests ok in the repository, the 13 named tests and the signatures match the plan; residuals: two reasoning-style comments in the module and three in the test (R103), module constants for thresholds to check against the criteria file

## plan7.md

- [x] T1 framework, prompts, schemas, templates written; ugs roles not adopted (step 3 skipped)

## plan8a.md

- [x] T1 bridge_images and its test: night n2 plan 8, 8 tests ok in the repository, the 7 named tests and the signatures match the plan, no comment at all

## plan8b.md

- [x] T1 ugs_bridge and its test: second night un5b 98 %, tests 21/24; corrected in the session: tests use real PNG files and a valid reasoning block, security finding fixed (validation messages no longer carry the replied value, new test); tests 25/25 green

## plan8c.md

- [x] T1 ugs_text and its test: second night un5b not scored, one failure; corrected in the session: fill refuses every value without a slot (contradicting test fixed), entry page is where the entry starts, only a heading of the same or higher level ends the references; tests 22/22 green

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

- [x] T1 figure-review SKILL.md, 16 research criteria + needs key, figure_tex (19 tests), figure_render (24 tests), all 6 suites green; manual check 2026-11-14: fictitious TikZ (paper macro kept) and draw.io rendered with --render. Rulings: fit_for_model is figure_image, not figure_extract; render() takes dpi, photo_colors, jpeg_quality, drawio_scale as keywords (R0); native png/jpg within max_long_edge returned as is; not_cited, citation_far, low_resolution_research, image_file_missing and the caption flags are judged_by model for now (scripting them is plan 10); draw.io page count reported, first-page default unverified

## plan10.md

- [ ] T1 four auditors and /tikz migrated to figure-review

## plan11.md

- [ ] T1 agent, command, SKILL.md, routing and docs

## plan12.md

- [ ] T1 mirrors and full checks
- [ ] T2 R35 review loop
- [ ] T3 changelog, improvements, PR

## plan17.md

- [x] T1 harvest night un5: files of plans 5c, 6a, 6b, 8b, 8c copied back (5d empty, dropped); quality 92 / not scored / 97 / 91 / 96 / 93 percent; all five test files still fail in the worktree (8/12, 11/13, 4/7, 21/24, 16/21); audit.md lists R0 literals and a placeholder distance_to_rect
- [x] T2 stop the watchdog and unload the models: no aider-watchdog process left, `ollama stop` unloaded the reviewer model (ollama ps empty), commit 4b55742 holds step 1
- [x] T3 second pass harvested and corrected in the session (owner order: do not relaunch the kit; deviation from R39, the kit wrote all code and the cloud fixed the six red plans). Quality before (night 1) 92 / not scored / 97 / 91 / 96 / 93 percent, after the second night 88 / 100 / 98 / 89 / 98 / not scored percent, all six suites green after the corrections (14, 8, 13, 10, 25, 22 tests)
- [x] T4 duplicates deleted 2026-11-13: aider-live kit and home, 19 old projects plus un5, their run logs, night logs and idmaps (no link inside, no process held them, scan done first); kept: un5 and un5b night logs, verify logs, model-reference.json; examples/ and EXAMPLE-PROMPT-robot.md untouched; the operator deletes ~/.config/aider himself
- [x] T5 impact checked 2026-11-13: verify-aider-plan 79/0, verify-audit-prompt ok, verify-audit-sandbox 4/0 (fixed: the privacy hook stderr line made its seed commit fail under PowerShell 5.1), verify-aider-path ok, verify-kit-install 11 checks ok (student zip installs and starts), plan_contract 25, dispatch guard 19, ollama_config 49 tests ok, plan_contract validate ok on lc-fix plan1; remaining mentions of .local/bin and .config/aider are the student kit, documented fallbacks (aider-night devConfig, SKILL.md) and the lc-fix spec, which was stale and is rewritten (kit in place under ~/.claude/skills/aider-setup); dry runs of aider-plan and aider-night happen at T8 on the mounted un6
- [x] T6 lc-fix plan 1 run with local-coder 2026-11-13: first attempts failed on the driver (a quoted test command with a space breaks aider argv under PowerShell 5.1; a backticked path in the plan counted as an editable target), third run: the writer changed the three files and the 19 guard tests pass (aider commit fb258a5, kept); quality percentage NOT produced because the final audit crashed (audit.md copied before it exists) and the driver wrote a false "no test file" block; driver defects to log in Issue 108: false success tick on unchanged code, audit.md copy, test lookup, test command with arguments and quoted paths
- [x] T7 close: evidence in this ledger, commit, tell the operator his two actions
- [x] T8 start the next night (plans 8d to 8l) and arm its waiter - started 2026-11-13 23:4x on un6 (plans 8d to 8l, all inputs present), log ~/.claude/aider-live/un6_night.log, branch martinotis/night-2026-11-13 in the project

## watchdog fix (Issue #108, 2026-11-13)

- [x] T1 watchdog no longer dies on one failed call: skip the tour, log each error and a gave_up line to watchdog.log, give up after maxConsecutiveFailures (10) in a row; driver restarts an ended watchdog at each plan; go test and verify-aider-plan.ps1 (79 ok) green; fresh watchdog started on the live run (pid 32996). Written by the cloud session on the owner's order, a deviation from R39 for this fix only
