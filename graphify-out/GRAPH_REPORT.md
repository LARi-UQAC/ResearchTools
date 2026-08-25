# Graph Report - .  (2026-06-15)

## Corpus Check
- 72 files · ~110,951 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 419 nodes · 662 edges · 32 communities (21 shown, 11 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 22 edges (avg confidence: 0.8)
- Token cost: 283,531 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_ScholarEval Scoring Script|ScholarEval Scoring Script]]
- [[_COMMUNITY_Scopus & Reference Tooling|Scopus & Reference Tooling]]
- [[_COMMUNITY_Deliberation Protocol|Deliberation Protocol]]
- [[_COMMUNITY_Deliberation Engine|Deliberation Engine]]
- [[_COMMUNITY_Scopus Validation Core|Scopus Validation Core]]
- [[_COMMUNITY_Deliberation Tests|Deliberation Tests]]
- [[_COMMUNITY_Manuscript Bibliography Conversion|Manuscript Bibliography Conversion]]
- [[_COMMUNITY_PDF & BibTeX Retrieval|PDF & BibTeX Retrieval]]
- [[_COMMUNITY_DOCX Inspection|DOCX Inspection]]
- [[_COMMUNITY_Gemini Cross-Reviewer|Gemini Cross-Reviewer]]
- [[_COMMUNITY_Audit Agents & Commands|Audit Agents & Commands]]
- [[_COMMUNITY_Copilot Cross-Reviewer|Copilot Cross-Reviewer]]
- [[_COMMUNITY_Project Instructions & Policy|Project Instructions & Policy]]
- [[_COMMUNITY_PDF Download Internals|PDF Download Internals]]
- [[_COMMUNITY_Literature Review Pipeline|Literature Review Pipeline]]
- [[_COMMUNITY_Scientific Writing Standards|Scientific Writing Standards]]
- [[_COMMUNITY_Junction Install Script|Junction Install Script]]
- [[_COMMUNITY_Setup Script|Setup Script]]
- [[_COMMUNITY_Table Enrichment Tests|Table Enrichment Tests]]
- [[_COMMUNITY_Reference & Markup Commands|Reference & Markup Commands]]
- [[_COMMUNITY_Filename Helpers|Filename Helpers]]
- [[_COMMUNITY_LaTeX & TikZ Commands|LaTeX & TikZ Commands]]
- [[_COMMUNITY_Testing Rules|Testing Rules]]
- [[_COMMUNITY_Concis Command|Concis Command]]
- [[_COMMUNITY_Context Command|Context Command]]
- [[_COMMUNITY_Focus Command|Focus Command]]
- [[_COMMUNITY_Slim Command|Slim Command]]
- [[_COMMUNITY_Code Style Rules|Code Style Rules]]
- [[_COMMUNITY_Preferences Rules|Preferences Rules]]
- [[_COMMUNITY_Security Rules|Security Rules]]
- [[_COMMUNITY_Workflows Rules|Workflows Rules]]

## God Nodes (most connected - your core abstractions)
1. `deliberate()` - 13 edges
2. `paper-auditor agent` - 13 edges
3. `scopus-researcher agent` - 12 edges
4. `scopus skill` - 12 edges
5. `scopus-auditor agent` - 11 edges
6. `_run_bib()` - 10 edges
7. `_verify()` - 10 edges
8. `main()` - 10 edges
9. `thesis-auditor agent` - 10 edges
10. `generate_report()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `ResearchTools Project Instructions (.claude/CLAUDE.md)` --references--> `ResearchTools Architecture Map`  [EXTRACTED]
  .claude/CLAUDE.md → Architecture.md
- `Canonical Auditor Pipeline` --rationale_for--> `LaTeX changes package track-change markup`  [EXTRACTED]
  Architecture.md → .claude/agents/reviewer-response/AGENT.md
- `Plan-Mode Vault Workflow (six cases)` --references--> `reviewer-response agent`  [EXTRACTED]
  CLAUDE.template.md → .claude/agents/reviewer-response/AGENT.md
- `ResearchTools Project Instructions (.claude/CLAUDE.md)` --references--> `ResearchTools Manual (README)`  [EXTRACTED]
  .claude/CLAUDE.md → README.md
- `bib-cleaner agent` --references--> `scopus skill`  [EXTRACTED]
  .claude/agents/bib-cleaner/AGENT.md → Architecture.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Auditors share scopus + deliberation + scholar-evaluation + scientific-writing** — agents_paper_auditor, agents_scopus_auditor, agents_thesis_auditor, skill_scopus, skill_deliberation, skill_scholar_evaluation [EXTRACTED 0.95]
- **Two-round Gemini + Copilot debate via deliberate.py** — script_deliberate, script_gemini_reviewer, script_github_reviewer, ext_consensus_mcp [EXTRACTED 0.95]
- **Command launches agent which consumes scopus skill** — commands_auditpaper, agents_paper_auditor, skill_scopus, script_scopus_api [EXTRACTED 0.95]
- **Two-round deliberation panel** — deliberation_deliberate_py, deliberation_gemini, deliberation_copilot, deliberation_consensus [EXTRACTED 0.85]
- **Claude arbitration and validation flow** — deliberation_arbitration_table, deliberation_scopus_gate, deliberation_log [EXTRACTED 0.85]
- **Word to LaTeX conversion pipeline** — commands_word2latex, agents_word_to_latex, word2latex_docx_inspect, word2latex_manuscript_bib [EXTRACTED 0.85]
- **EQUATOR Reporting Guideline Family** — references_reporting_guidelines_consort, references_reporting_guidelines_strobe, references_reporting_guidelines_prisma, references_reporting_guidelines_equator [EXTRACTED 0.85]
- **Scopus Skill Script Family** — scopus_scopus_api, scopus_semantic_scholar_api, scopus_download_pdf, scopus_gemini_table [INFERRED 0.75]
- **word2latex Conversion Pipeline** — word2latex_docx_inspect, pandoc_tool, word2latex_manuscript_bib, word2latex_word_to_latex_agent [EXTRACTED 0.85]

## Communities (32 total, 11 thin omitted)

### Community 0 - "ScholarEval Scoring Script"
Cohesion: 0.05
Nodes (27): Path, calculate_weighted_average(), generate_bar_chart(), generate_report(), get_quality_level(), identify_strengths_weaknesses(), interactive_mode(), load_scores() (+19 more)

### Community 1 - "Scopus & Reference Tooling"
Cohesion: 0.10
Nodes (33): /bibclean Command, Any, /word2latex command, pandoc, Manuscript Bibliography & Citations Reference, Word to LaTeX Preamble Patches, Scopus Scripts requirements.txt, Scopus Skill (+25 more)

### Community 2 - "Deliberation Protocol"
Cohesion: 0.06
Nodes (33): Canonical arbitration table and provenance markers, Consensus evidence source, GitHub Copilot (GPT-4o) reviewer, deliberate.py debate engine, Gemini 2.0 Flash reviewer, Deliberation Log format, Deliberation Protocol (canonical), Scopus.AI evidence source (+25 more)

### Community 3 - "Deliberation Engine"
Cohesion: 0.10
Nodes (33): _best_conf(), _collect(), copilot_available(), count_gemini_tokens(), deliberate(), _digest_draft(), _disagreed_sections(), _expand_schema() (+25 more)

### Community 4 - "Scopus Validation Core"
Cohesion: 0.14
Nodes (26): Any, Semantic Scholar Academic Graph, Response, _author(), _author_match(), _check_field(), _check_response(), _cite() (+18 more)

### Community 5 - "Deliberation Tests"
Cohesion: 0.09
Nodes (6): test_deliberate.py — offline unit tests for the deliberation panel.  The Gemini, TestBudgetFit, TestCompressionHelpers, TestDeliberateCLI, TestDeliberateMerge, TestSlimRound2

### Community 6 - "Manuscript Bibliography Conversion"
Cohesion: 0.14
Nodes (22): word-to-latex agent, Namespace, bracket_to_cite(), convert_citations(), _expand_nums(), find_bib_start(), main(), _nums_to_cite() (+14 more)

### Community 7 - "PDF & BibTeX Retrieval"
Cohesion: 0.16
Nodes (19): Any, Namespace, Elsevier Scopus API, extract_bib_entries(), find_bib_from_latex(), download_pdf.py — Full-text PDF retrieval for the Claude Code /scopus skill.  St, --------------------------------------------------------------------------     P, --------------------------------------------------------------------------     P (+11 more)

### Community 8 - "DOCX Inspection"
Cohesion: 0.28
Nodes (16): extract_attr(), find_style_block(), hp_to_pt(), inspect_defaults(), inspect_headers_footers(), inspect_headings(), inspect_images(), inspect_sections() (+8 more)

### Community 9 - "Gemini Cross-Reviewer"
Cohesion: 0.18
Nodes (16): Google Gemini 2.0 Flash, count_gemini_tokens(), gemini_available(), main(), gemini_reviewer.py — Gemini AI cross-reviewer for the scopus-auditor pipeline., Parse possibly-truncated JSON. A free-tier max_output_tokens cap can cut the, --------------------------------------------------------------------------     P, Standalone CLI behavior: format the default review prompt, call Gemini, print JS (+8 more)

### Community 10 - "Audit Agents & Commands"
Cohesion: 0.25
Nodes (15): cover-paper agent, paper-auditor agent, reviewer-response agent, scopus-auditor agent, submit-checker agent, thesis-auditor agent, thesis-proposal-auditor agent, Figure/Table/Equation Authoring Rules (+7 more)

### Community 11 - "Copilot Cross-Reviewer"
Cohesion: 0.20
Nodes (13): Exception, GitHub Models (GPT-4o / Copilot), copilot_available(), main(), github_reviewer.py — GitHub Copilot (GPT-4o via GitHub Models) cross-reviewer fo, Standalone CLI behavior: format the default review prompt, call GPT-4o, print JS, Raised when the Copilot reviewer cannot return a result (missing dependency, mis, True when openai is importable and GITHUB_TOKEN is set. Never raises or exits. (+5 more)

### Community 12 - "Project Instructions & Policy"
Cohesion: 0.20
Nodes (12): bib-cleaner agent, latex-writer agent, ResearchTools Project Instructions (.claude/CLAUDE.md), AI-Style Hygiene Constraints, Approved Publisher List, Global Obsidian Integration Instructions, Forbidden Obsidian Commands, Plan-Mode Vault Workflow (six cases) (+4 more)

### Community 13 - "PDF Download Internals"
Cohesion: 0.20
Nodes (12): _clean_doi(), download_one(), _fetch_pdf(), --------------------------------------------------------------------------     P, --------------------------------------------------------------------------     P, Primary source: Elsevier Full-Text API. No-op when no Scopus key is set., Fallback source: the Semantic Scholar open-access PDF URL, if S2 has one., --------------------------------------------------------------------------     P (+4 more)

### Community 14 - "Literature Review Pipeline"
Cohesion: 0.18
Nodes (11): scopus-researcher agent, ResearchTools Architecture Map, Canonical Auditor Pipeline, Consensus is not a Scopus script (MCP boundary), Deliberation Process (two-round panel), /litreview command, Pareto 80-20 contribution matrix, PRISMA-style screening flow (+3 more)

### Community 16 - "Scientific Writing Standards"
Cohesion: 0.29
Nodes (10): IMRAD Structure Guide, IMRAD Format, ML Conference Structure (NeurIPS/ICML/ICLR), Reporting Guidelines for Scientific Studies, CONSORT Guideline, EQUATOR Network, PRISMA Guideline, STROBE Guideline (+2 more)

### Community 17 - "Junction Install Script"
Cohesion: 0.44
Nodes (6): New-JunctionSafe(), New-SymlinkSafe(), Write-Conflict(), Write-Created(), Write-Exists(), Write-WhatIf()

### Community 19 - "Table Enrichment Tests"
Cohesion: 0.29
Nodes (3): test_gemini_table.py — offline unit tests for the comparison-table enrichment he, TestEnrich, TestMainSkip

### Community 20 - "Reference & Markup Commands"
Cohesion: 0.40
Nodes (5): LaTeX changes package, /ref command, /replyreviewer command, /submitcheck command, scopus skill

### Community 21 - "Filename Helpers"
Cohesion: 0.50
Nodes (4): --------------------------------------------------------------------------     P, --------------------------------------------------------------------------     P, _slugify(), target_filename()

## Knowledge Gaps
- **43 isolated node(s):** `Response`, `Namespace`, `ResearchTools Manual (README)`, `/auditpaper command`, `/auditreview command` (+38 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Deliberation Protocol (canonical)` connect `Deliberation Protocol` to `Audit Agents & Commands`, `Literature Review Pipeline`?**
  _High betweenness centrality (0.189) - this node is a cross-community bridge._
- **Why does `Path` connect `ScholarEval Scoring Script` to `DOCX Inspection`, `Deliberation Engine`, `Manuscript Bibliography Conversion`?**
  _High betweenness centrality (0.166) - this node is a cross-community bridge._
- **Why does `reviewer-response agent` connect `Audit Agents & Commands` to `Community None`, `Deliberation Protocol`, `Deliberation Engine`, `Scopus Validation Core`, `Project Instructions & Policy`, `Reference & Markup Commands`?**
  _High betweenness centrality (0.155) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Path` (e.g. with `main()` and `_read_evidence()`) actually correct?**
  _`Path` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `test_deliberate.py — offline unit tests for the deliberation panel.  The Gemini`, `deliberate.py — Deliberation panel (debate stage of the audit / research pipelin`, `--------------------------------------------------------------------------     P` to the rest of the system?**
  _129 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `ScholarEval Scoring Script` be split into smaller, more focused modules?**
  _Cohesion score 0.054901960784313725 - nodes in this community are weakly interconnected._
- **Should `Scopus & Reference Tooling` be split into smaller, more focused modules?**
  _Cohesion score 0.0957983193277311 - nodes in this community are weakly interconnected._