# Purpose & Overview

Chapter 00 of the ResearchTools manual. Root entry point: [../../README.md](../../README.md).

## Purpose

Ask for my book (French version): Vibe Design. 30$ contribution via:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/s/89b1e1cc6c)

[![PayPal](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.me/MartinJDOtis)

ResearchTools is an AI-assisted toolbox for researcher-professors and graduate students
who want to design, find and fix the issues hiding in their academic design, writing before a reviewer,
a thesis committee, or a grant panel does. It offers a Dashboard to follow the work-in-progress and has self-learning functions. 

**Never let an LLM do your work for you. Use it to improve your work, find your weaknesses, and help you improve yourself.**
**Never use these tools to conduct a formal or professional assessment, and do not let the tool make decisions for you. Use at your own risk.**

**Always uses a logo when using these tools, such as:**
https://www.uqac.ca/ressourcespedago/iag/


ResearchTools contains two loop for authoring and coding. It covers the whole process: starting
a literature review, auditing an existing review, a complete paper, a UQAC
thesis or thesis proposal, cleaning/improving a BibTeX file, helping to respond to peer reviewers, checking submission readiness against a target journal, building the submission package, and converting Word to LaTeX with high accuracy. Moreover, it offers the process to design the code, PCB and 3D CAD with a full Dashboard to see the agents working in background including some controls.

Every check is grounded in the same working norms: no reference enters a document
without being validated against Scopus (no fabricated citations, no invented DOIs),
weaknesses are reported as actionable findings with an executable improvement plan
rather than vague encouragement, and drafts pass a multi-model deliberation (Gemini +
GitHub Copilot debate, arbitrated with Claude) before a plan or review is finalized. Each improvment is evaluated with a score and then you can see the quantitative improvments.

An agent, `\local-writer`, manage the memories with a Daemon: Obsidian Vault and Graphify. The Harness cannot access to the memories directly. A control is applied on the Harness for the code generation: when the harness needs to generate a code to overcome a weakness in ResearchTools, it is integrated in the ResearchTools clone with an auto-update in your system. Then, ResearchTools will change over time and with your specific usage.

The toolbox is built as software, agents, skills, and commands for [Claude Code](https://docs.anthropic.com/claude-code),
with generated mirrors for GitHub Copilot, OpenCode, Continue, Aider, Codex, and other
`AGENTS.md` readers (see [Installation](01-installation.md)). Typical entry points: `/litreview` for a new topic (review update using `\litreview-updater`),
`/auditpaper` before submitting, `/auditthesis` before a defense, `/bibclean` on any
`.bib` file, `/replyreviewer` when the reviews come back.

## TODO in 2026

1- ~~Agent paper2talk (latex paper to a talk for a conference using some parameters such as time 10 to 12 minutes) for conference (september 2026).~~ **Done 2026-08-12**: the `paper2talk` skill, the `talk-builder` agent, and `/talk`.

2- Agent thesis2defence (latex thesis to defence talk in Beamer, 30 to 45 minutes), october 2026.

3- Thesis-Tracker: full UI/UX with user login, database, to fill paperworks, forms, track paper submission process, manage mindmap to create new paper ideas, end of 2026. We need to investigate if we use n8n/OpenClaw/Hermes/OpenHands/?, or other agents over a cloud or local on a server.

4- plugin in marketplace with automatic update.

## About this manual

Reference for the skills, agents and commands shipped in this repository. Everything
documented here lives under `.claude/` in **this** repo (academic research tooling for
LaTeX writing, Scopus reference validation, paper/thesis auditing, and grant-template
conversion). For a map of how the pieces relate, see [Architecture.md](../../Architecture.md).

The repo ships **18 skills**, **19 agents**, and **27 commands**.

This manual is split into chapters under `docs/manual/`, the same way
[Architecture.md](../../Architecture.md) is already split into layers rather than kept as one
flat file — the root `README.md` is now a table of contents, not the full text. Two files
share a similar name and a different job: `Architecture.md` maps this repository's own
agents/skills/commands (7 layers); `NEW_ARCHITECTURE.md`, at the repo root, is the architecture
shared with the sibling repository ThesisTracker (committed identically to `main` in both).
Chapter [09](09-thesistracker-integration.md) covers that boundary.

---
[Table of contents](../../README.md) | [01 Installation →](01-installation.md)
