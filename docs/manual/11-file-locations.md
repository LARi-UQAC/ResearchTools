# File Locations Summary

Chapter 11 of the ResearchTools manual. Back to [table of contents](../../README.md).

All agents, commands, and skills live under this repository's `.claude/` directory.

```
ResearchTools\
└── .claude\
    ├── agents\                              (18 agents; not all listed below -- see the
    │                                          Agents chapter for the current, complete list)
    │   ├── scopus-researcher.md       ← /litreview
    │   ├── litreview-updater.md       ← /litupdate
    │   ├── scopus-auditor.md          ← /auditreview
    │   ├── paper-auditor.md           ← /auditpaper
    │   ├── thesis-auditor.md          ← /auditthesis
    │   ├── thesis-proposal-auditor.md ← thesis-proposal audit
    │   ├── reviewer-response.md       ← /replyreviewer
    │   ├── bib-cleaner.md             ← /bibclean
    │   ├── submit-checker.md          ← /submitcheck
    │   ├── word-to-latex.md           ← /word2latex
    │   ├── talk-builder.md           ← /talk
    │   ├── cover-paper.md             ← submission package
    │   ├── thesis-to-paper.md         ← thesis + conf papers -> journal manuscript
    │   ├── authoring-loop.md          ← ScholarEval-gated authoring loop
    │   ├── latex-writer.md            ← LaTeX authoring
    │   ├── local-writer.md            ← local docs/comments (bridge)
    │   ├── local-coder.md             ← local code gen (bridge)
    │   └── narrative-cv-writer.md     ← /cv
    ├── commands\                            (25 commands; not all listed below -- see the
    │                                          Commands chapter for the current, complete list)
    │   ├── concis.md   ├── slim.md    ├── focus.md   ├── ctx.md
    │   ├── tikz.md     ├── test.md    ├── doc.md     ├── latex.md
    │   ├── ref.md      ├── litreview.md             ├── litupdate.md
    │   ├── auditreview.md              ├── auditpaper.md
    │   ├── auditthesis.md              ├── bibclean.md
    │   ├── submitcheck.md              ├── replyreviewer.md
    │   ├── word2latex.md               ├── geolocalisation.md
    │   ├── loopdev.md                  ├── talk.md
    │   ├── recommendation-letter.md
    │   └── cv.md
    ├── rules\                               (code-style, preferences, security, testing, workflows)
    └── skills\                              (18 skills; not all listed below -- see the
                                               Skills chapter for the current, complete list)
        ├── scopus\
        │   ├── SKILL.md
        │   └── scripts\  (scopus_api.py, semantic_scholar_api.py, download_pdf.py,
        │                  bib_batch.py, litreview_update.py,
        │                  gemini_reviewer.py, github_reviewer.py, gemini_table.py)
        ├── scientific-writing\SKILL.md
        ├── scholar-evaluation\SKILL.md      (+ scripts\calculate_scores.py)
        ├── deliberation\SKILL.md            (+ scripts\deliberate.py)
        ├── extract-statistic\SKILL.md       (+ scripts\extract_text.py [--stats-scan / --section-scan];
        │                  references\statistical-audit-protocol.md, domain-profiles.md)
        ├── extract-futureworks\SKILL.md     (no script; reuses extract_text.py --section-scan;
        │                  references\futureworks-protocol.md, section-cues.md)
        ├── word2latex\SKILL.md              (+ scripts\docx_inspect.py, manuscript_bib.py)
        ├── drawio2tikz\SKILL.md             (+ scripts\drawio2tikz.py;
        │                  references\conversion-rules.md)
        ├── geolocalisation\SKILL.md         (+ scripts\extract_locations.py, generate_geomap.py,
        │                  Test\test_extract_locations.py; references\geocoding-protocol.md;
        │                  data\ Natural Earth gazetteer cache)
        ├── loop-engineer\SKILL.md           (+ scripts\loop_engineer.py [Agent SDK driver],
                           loop_audit.py [code-quality scorer], Test\test_loop_audit.py;
                           references\ LOOP/STATE/PROCESS/ledger templates; requirements.txt)
        ├── recommendation-letter\SKILL.md   (+ scripts\generate_letter.py, letter_templates.py,
        │                  Test\test_generate_letter.py; references\quality-patterns.md; evals\)
        ├── narrative-cv\SKILL.md            (+ scripts\cv_common.py, cv_inventory.py, cv_select.py,
        │                  cv_build.py, contribution_types.json,
        │                  Test\test_cv_common.py, test_cv_inventory.py, test_cv_select.py, test_cv_build.py)
        ├── paper2talk\SKILL.md              (+ scripts\talk_rules.py, talk_model.py, talk_template.py,
                           fig_export.py, talk_render.py, talk_notes.py, to_a4.py, talk_validate.py,
                           talk_pptx.py, paper_extract.py, talk_doctor.py,
                           requirements.txt, Test\ [13 offline suites];
                           assets\deck_skeleton.js, beamer_skeleton.tex.j2, web_skeleton.html.j2;
                           references\renderer-contracts.md, qa-loop.md)
        ├── latex-hygiene\SKILL.md           (+ scripts\tex_check.py, tex_common.py, tex_chars.py,
                           tex_braces.py, tex_par.py, tex_citecov.py, tex_abstract.py, tex_wc.py,
                           tex_aiscan.py, tex_aiscan_text.py, tex_patch.py, tex_scan.py, tex_build.py,
                           Test\test_tex_check.py, Test\test_tex_patch.py, Test\test_tex_build.py)
        └── opt-local-vram-llm\SKILL.md      (+ scripts\vram_probe.py, vram_modelfile.py,
                           vram_daemon.py, vram_optimizer.py, Test\test_vram_probe.py,
                           Test\test_vram_modelfile.py, Test\test_vram_daemon.py,
                           Test\test_vram_optimizer.py)
```
