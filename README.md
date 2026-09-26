# ResearchTools — Manual

[![License: MIT](https://img.shields.io/badge/License-MIT-10243E.svg)](LICENSE)
[![Python 3.x](https://img.shields.io/badge/python-3.x-1F9E8F.svg)](docs/manual/01-installation.md)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-1F9E8F.svg)](docs/manual/01-installation.md)
[![Docs](https://img.shields.io/badge/docs-12%20chapters-10243E.svg)](docs/manual/00-purpose.md)
[![GitHub Repo stars](https://img.shields.io/github/stars/LARi-UQAC/ResearchTools?style=flat&color=C9762F)](https://github.com/LARi-UQAC/ResearchTools/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/LARi-UQAC/ResearchTools?color=1F9E8F)](https://github.com/LARi-UQAC/ResearchTools/commits/main)
[![Contributors](https://img.shields.io/github/contributors/LARi-UQAC/ResearchTools?color=1F9E8F)](https://github.com/LARi-UQAC/ResearchTools/graphs/contributors)
[![Open issues](https://img.shields.io/github/issues/LARi-UQAC/ResearchTools?color=10243E)](https://github.com/LARi-UQAC/ResearchTools/issues)

<p align="center">
  <img src="ResearchToolsLogo.png" alt="ResearchTools logo" width="200">
</p>

<p align="center"><b>Find what's wrong in your academic writing or software design: before a reviewer, a thesis committee, or a grant panel does.</b></p>

![ResearchTools promo](docs/manual/researchtools-hero.gif)

<details>
<summary><b>Table of contents</b></summary>

- [ResearchTools — Manual](#researchtools--manual)
  - [Why ResearchTools](#why-researchtools)
  - [See it in action](#see-it-in-action)
  - [Quickstart](#quickstart)
  - [The two memories](#the-two-memories)
  - [Manual chapters](#manual-chapters)
  - [Supported harnesses](#supported-harnesses)
  - [Support this project](#support-this-project)

</details>

ResearchTools is an AI-assisted toolbox for researcher-professors and graduate students. It
finds and fixes what's wrong before a reviewer, a thesis committee, or a grant panel does:

- Literature reviews, paper and thesis audits, BibTeX cleanup, reviewer responses, submission
  packages: the academic writing side.
- Code, PCB, and 3D CAD design review, with a dashboard to watch the agents work, and log them.
- A local-model-backed dev loop that keeps the heavy generation off your cloud bill.

Full pitch, the 2026 roadmap, and this manual's own conventions:
[docs/manual/00-purpose.md](docs/manual/00-purpose.md).

**Never let an LLM do your work for you. Use it to improve your work, find your weaknesses,
and help you improve yourself. Never use these tools to conduct a formal or professional
assessment, and do not let the tool make decisions for you. Use at your own risk.**

This file is the entry point only. The manual is split into chapters under `docs/manual/`,
the same way [Architecture.md](Architecture.md) is already split into layers instead of kept
as one flat file — this keeps each topic at a readable size instead of one 1300-line page.

## Why ResearchTools

| Without | With ResearchTools |
|---|---|
| Catch a missing reference or a broken hypothesis flow after the reviewer does | An auditor scores the manuscript first, against the same ScholarEval rubric a committee uses |
| Re-read a cited paper's abstract/contribution/futureworks/statistics and hope the citation says what you think it says | `extract-contributions` checks the citing sentence against the paper's own stated contribution |
| Burn cloud tokens on routine docstrings and refactors | `local-writer` / `local-coder` push that generation to a local model, for free |

Not a replacement for judgment — a second pair of eyes that never gets tired of checking.

## See it in action

![rt-observe dashboard, Real-Time Process tab](docs/manual/rtobserve.png)

The `rt-observe` dashboard watching a live session: hook flow, fan-out to the two memories
(Obsidian vault, `graphify` graph), and a spawned subagent, all on loopback with no external
service. Full walkthrough: [docs/manual/07-rt-observe-dashboard.md](docs/manual/07-rt-observe-dashboard.md).

## Quickstart

```powershell
git clone https://github.com/LARi-UQAC/ResearchTools.git
cd ResearchTools
.\setup.ps1 -All -Personal   # config + Claude links + all tool mirrors
.\setup.ps1 -InstallPython   # optional: creates .venv-skills for the offline test suite
```

Full install steps (junctions, other-tool mirrors, prerequisites table):
[docs/manual/01-installation.md](docs/manual/01-installation.md).

## The two memories

Two memories back this toolkit, and neither is read or written directly: the Obsidian vault
(what was learned, across every project) and the `graphify` code graph in `graphify-out/`
(what this repository's code IS right now). Both are reached only by dispatching the
`local-writer` agent. The graph's own state is read-only via
`scripts/audit/check-graph-health.ps1`. Full design:
[docs/manual/04-skills.md](docs/manual/04-skills.md#the-two-memories---the-vault-and-the-code-graph).

## Manual chapters

At a glance — commands drive agents, agents draw on skills, and both memories are reached
only through `local-writer` (detail: [04-skills.md](docs/manual/04-skills.md)):

```mermaid
graph LR
  U["You"] -->|"/command"| CC["Your Harness"]
  CC --> AG["Agents"]
  AG --> SK["Skills"]
  SK --> EXT[("Scopus / Gemini /<br/>Copilot APIs, etc.")]
  AG -->|"dispatch local-writer"| VAULT[("Obsidian vault<br/>what was learned")]
  AG -->|"dispatch local-writer"| GRAPH[("graphify graph<br/>what the code is")]
```

| # | Chapter | Covers |
|---|---|---|
| 00 | [Purpose & overview](docs/manual/00-purpose.md) | Mission, 2026 roadmap, manual conventions |
| 01 | [Installation](docs/manual/01-installation.md) | `setup.ps1` / `install.ps1` / `install-junctions.ps1`, prerequisites, the 5 install steps |
| 02 | [Profiles & environment](docs/manual/02-profiles.md) | Domain profiles, API keys |
| 03 | [Token management](docs/manual/03-token-management.md) | Output modes, `/slim` `/concis` `/focus` `/ctx` |
| 04 | [Skills](docs/manual/04-skills.md) | All 15 skills, the two memories |
| 05 | [Security audit](docs/manual/05-security-audit.md) | SkillSpector findings |
| 06 | [Aider nightly pipeline](docs/manual/06-aider-pipeline.md) | `aider-setup`, the student `aider-kit.zip`, vs. `local-coder` |
| 07 | [rt-observe & dashboard](docs/manual/07-rt-observe-dashboard.md) | Mirror matrix, `/rt-dashboard` |
| 08 | [Commands](docs/manual/08-commands.md) | All slash commands |
| 09 | [ThesisTracker integration](docs/manual/09-thesistracker-integration.md) | The sibling repository, `NEW_ARCHITECTURE.md`, the `form-service` boundary |
| 10 | [Agents](docs/manual/10-agents.md) | All agents, local delegation, loop engineering |
| 11 | [File locations](docs/manual/11-file-locations.md) | Directory tree summary |

Relationship diagrams and the 7-layer execution architecture for **this** repository:
[Architecture.md](Architecture.md). The architecture **shared with the sibling repository
ThesisTracker** (form catalogue, twenty-unit delivery plan) is a separate file,
[NEW_ARCHITECTURE.md](NEW_ARCHITECTURE.md) — see chapter 09 above; do not confuse the two.

## Supported harnesses

One canonical `.claude/` source, mirrored everywhere below (detail:
[10-agents.md](docs/manual/10-agents.md#using-the-agents-outside-claude-code)):

[![Claude Code](https://img.shields.io/badge/Claude%20Code-native-1F9E8F.svg)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![GitHub Copilot](https://img.shields.io/badge/GitHub%20Copilot-mirrored-1F9E8F.svg?logo=githubcopilot&logoColor=white)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![OpenCode](https://img.shields.io/badge/OpenCode-mirrored-1F9E8F.svg)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![Continue](https://img.shields.io/badge/Continue-mirrored-1F9E8F.svg)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![Aider](https://img.shields.io/badge/Aider-mirrored-1F9E8F.svg)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![Codex](https://img.shields.io/badge/Codex-mirrored-1F9E8F.svg?logo=openai&logoColor=white)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)
[![AGENTS.md readers](https://img.shields.io/badge/AGENTS.md-generic%20readers-1F9E8F.svg)](docs/manual/10-agents.md#using-the-agents-outside-claude-code)

## Support this project

If this toolkit is useful to you, a star helps others find it. Ask for my book (French
version): Vibe Design. 30$ contribution via:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/s/89b1e1cc6c)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-C9762F.svg)](https://www.paypal.me/MartinJDOtis)
