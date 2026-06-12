# Architecture — Academic Agents, Commands, and Skills

This document maps the academic tooling layer under [.claude/](.). Three layers cooperate: user-facing **slash commands** ([commands/](commands)) launch **agents** ([agents/](agents)), and each agent draws on shared **skills** ([skills/](skills)) and the external Scopus / multi-model APIs. All paths below are relative to the [.claude/](.) directory.

## Layer 1 — Component architecture

The diagram shows which command launches which agent, and which skills each agent consumes. Two agents — [cover-paper](agents/cover-paper/AGENT.md) and [thesis-proposal-auditor](agents/thesis-proposal-auditor/AGENT.md) — have no dedicated slash command; they are invoked by name. Every agent depends on the [scopus](skills/scopus) skill for reference validation; the auditors and the researcher additionally route through [deliberation](skills/deliberation), [scholar-evaluation](skills/scholar-evaluation), and [scientific-writing](skills/scientific-writing).

```mermaid
graph TD
  subgraph CMD["Commands — commands/"]
    c1["/auditpaper"]
    c2["/auditreview"]
    c3["/auditthesis"]
    c4["/bibclean"]
    c5["/litreview"]
    c6["/replyreviewer"]
    c7["/submitcheck"]
  end

  subgraph AG["Agents — agents/"]
    a1["paper-auditor"]
    a2["scopus-auditor"]
    a3["thesis-auditor"]
    a4["thesis-proposal-auditor"]
    a5["bib-cleaner"]
    a6["scopus-researcher"]
    a7["reviewer-response"]
    a8["submit-checker"]
    a9["cover-paper"]
  end

  subgraph SK["Skills — skills/"]
    s1["scopus<br/>scopus_api.py · download_pdf.py"]
    s2["deliberation<br/>deliberate.py"]
    s3["scholar-evaluation<br/>calculate_scores.py"]
    s4["scientific-writing<br/>float / writing rules"]
  end

  subgraph EXT["External APIs / models"]
    e1[("Scopus API")]
    e2["Gemini"]
    e3["GitHub Copilot"]
    e4["Consensus / Scopus.AI"]
  end

  c1 --> a1
  c2 --> a2
  c3 --> a3
  c4 --> a5
  c5 --> a6
  c6 --> a7
  c7 --> a8
  a4 -.->|"invoked by name<br/>(no command)"| a4
  a9 -.->|"invoked by name<br/>(no command)"| a9

  a1 --> s1 & s2 & s3 & s4
  a2 --> s1 & s2 & s3 & s4
  a3 --> s1 & s2 & s3 & s4
  a4 --> s1 & s2 & s3 & s4
  a6 --> s1 & s2 & s4
  a7 --> s1 & s2 & s4
  a8 --> s1 & s3
  a5 --> s1
  a9 --> s1

  s1 --> e1
  s2 --> e2 & e3 & e4 & e1
```

### Command → agent → skill matrix

| Command | Agent | scopus | deliberation | scholar-evaluation | scientific-writing |
| --- | --- | --- | --- | --- | --- |
| `/auditpaper` | [paper-auditor](agents/paper-auditor/AGENT.md) | yes | yes | yes | yes |
| `/auditreview` | [scopus-auditor](agents/scopus-auditor/AGENT.md) | yes | yes | yes | yes |
| `/auditthesis` | [thesis-auditor](agents/thesis-auditor/AGENT.md) | yes | yes | yes | yes |
| *(by name)* | [thesis-proposal-auditor](agents/thesis-proposal-auditor/AGENT.md) | yes | yes | yes | yes |
| `/bibclean` | [bib-cleaner](agents/bib-cleaner/AGENT.md) | yes | no | no | no |
| `/litreview` | [scopus-researcher](agents/scopus-researcher/AGENT.md) | yes | yes | no | yes |
| `/replyreviewer` | [reviewer-response](agents/reviewer-response/AGENT.md) | yes | yes | no | yes |
| `/submitcheck` | [submit-checker](agents/submit-checker/AGENT.md) | yes | no | yes | no |
| *(by name)* | [cover-paper](agents/cover-paper/AGENT.md) | yes | no | no | no |

## Layer 2 — Execution flowchart

The auditors ([paper-auditor](agents/paper-auditor/AGENT.md), [scopus-auditor](agents/scopus-auditor/AGENT.md), [thesis-auditor](agents/thesis-auditor/AGENT.md), [thesis-proposal-auditor](agents/thesis-proposal-auditor/AGENT.md)) share one canonical pipeline. This flowchart traces a request from the slash command through input resolution, Scopus validation, the multi-model deliberation panel, ScholarEval scoring, and the executable improvement plan, then to optional execution with `changes`-package markup. The skill script invoked at each stage is labelled on the node. Agents with a narrower scope ([bib-cleaner](agents/bib-cleaner/AGENT.md), [submit-checker](agents/submit-checker/AGENT.md), [cover-paper](agents/cover-paper/AGENT.md), [reviewer-response](agents/reviewer-response/AGENT.md), [scopus-researcher](agents/scopus-researcher/AGENT.md)) enter the same path but skip the stages their matrix row marks "no".

```mermaid
flowchart TD
  U([User request]) --> CMD{"Slash command<br/>or agent name?"}
  CMD -->|"command"| MAP["commands/*.md<br/>launches mapped agent"]
  CMD -->|"by name"| MAP2["cover-paper /<br/>thesis-proposal-auditor"]
  MAP --> IN
  MAP2 --> IN

  IN["Input resolution<br/>$ARGUMENTS · IDE file · pasted text"]
  IN --> MERGE["Merge input/include<br/>recursively (3–4 levels)"]
  MERGE --> PARSE["Parse structure +<br/>extract all references"]

  PARSE --> VAL["Reference validation loop<br/>skills/scopus/scripts/scopus_api.py<br/>cite · validate · verify"]
  VAL --> SOTA["State-of-art search<br/>scopus_api.py search"]
  SOTA --> AUDIT["Section / content audits<br/>emit [FLAG] markers"]
  AUDIT --> FLOAT["Float compliance check<br/>skills/scientific-writing/references/<br/>float_authoring_rules.md"]

  FLOAT --> DELIB["Deliberation panel<br/>skills/deliberation/scripts/deliberate.py<br/>Gemini + Copilot + Consensus, 2 rounds"]
  DELIB --> GATE{"New references<br/>proposed?"}
  GATE -->|"yes"| REVAL["Re-validate<br/>scopus_api.py verify<br/>(accept only valid:true)"]
  GATE -->|"no"| SCORE
  REVAL --> SCORE

  SCORE["ScholarEval scoring<br/>skills/scholar-evaluation/scripts/<br/>calculate_scores.py"]
  SCORE --> PLAN[("Executable plan .md<br/>+ Deliberation Log")]

  PLAN --> EXEC{"User edits,<br/>then executes?"}
  EXEC -->|"yes"| APPLY["Apply changes-package markup<br/>added · replaced · deleted<br/>(id = author / reviewer)"]
  EXEC -->|"no — review only"| END([End])
  APPLY --> END
```

## Layer 3 — Scopus skill internals

The [scopus](skills/scopus) skill is the busiest dependency: six scripts under [skills/scopus/scripts/](skills/scopus/scripts) split metadata, full-text retrieval, author backfill, and the multi-model reviewers. [SKILL.md](skills/scopus/SKILL.md) dispatches `$ARGUMENTS` to one of six metadata modes on `scopus_api.py` (a pure JSON client that never writes files), to `download_pdf.py` for PDFs, or to `gemini_table.py` for comparison-table cell enrichment. `semantic_scholar_api.py` is a throttled fallback that backfills the full ordered author list when Scopus returns none. `gemini_reviewer.py` and `github_reviewer.py` live here too but are consumed by the [deliberation](skills/deliberation) panel, not by `scopus_api.py`.

**Consensus is not a scopus script.** No file under [skills/scopus](skills/scopus) references it. Consensus is the MCP tool `mcp__claude_ai_Consensus__search`, called by the agent (Claude) itself during the [deliberation](skills/deliberation) step; the agent runs up to four searches, writes them to `evidence.txt`, and hands that file to `deliberate.py` via `--evidence-file`. `deliberate.py` performs only the Gemini and Copilot API calls. The dashed evidence path is shown in the cluster below to make this boundary explicit. (Scopus.AI — Elsevier's manual generative tool — and the `scopus` skill scripts are three distinct things.)

```mermaid
flowchart TD
  AG["Agent / command<br/>$ARGUMENTS"] --> DISP{"Mode dispatch<br/>SKILL.md"}

  DISP -->|"search · cite · validate<br/>verify · author · journal"| API
  DISP -->|"download"| DL
  DISP -->|"table enrich"| GT

  subgraph S["scopus_api.py — pure JSON metadata client"]
    API["scopus_api.py"]
    API --> EP1["Search API"]
    API --> EP2["Abstract Retrieval<br/>(cite / verify)"]
    API --> EP3["Author Search<br/>(author)"]
    API --> EP4["Serial Title<br/>(journal)"]
  end

  EP1 --> ELS[("Elsevier Scopus API<br/>SCOPUS_API_KEY")]
  EP2 --> ELS
  EP3 --> ELS
  EP4 --> ELS

  API -.->|"0 authors on cite/verify<br/>or --enrich-authors"| S2
  S2["semantic_scholar_api.py<br/>authors · paper<br/>1 req/s throttle"] --> S2EP[("Semantic Scholar<br/>Academic Graph")]
  S2 -.->|"ordered authors backfill"| API

  subgraph D["download_pdf.py — full-text PDF"]
    DL["download_pdf.py<br/>doi · bib"]
    DL --> DLE["Elsevier Full-Text API"]
    DL -.->|"OA fallback"| DLS["S2 openAccessPdf"]
    DLE --> CHK{"%PDF magic-byte<br/>+ HTTPS + size cap"}
    DLS --> CHK
    CHK -->|"ok"| REFS[("refs/*.pdf<br/>_manifest.json")]
    CHK -->|"reject"| FAIL[("refs/_failed.md")]
  end
  DLE --> ELS
  DLS --> S2EP

  GT["gemini_table.py<br/>GEMINI_API_KEY (optional)"] --> GEM[("Google Gemini<br/>2.0 Flash")]

  subgraph R["Reviewer scripts — used by deliberation skill"]
    GR["gemini_reviewer.py"] --> GEM
    HR["github_reviewer.py"] --> GH[("GitHub Models<br/>models.inference.ai.azure.com")]
  end
  DELIB["deliberation/deliberate.py<br/>(Gemini + Copilot only)"] -.-> GR
  DELIB -.-> HR
  AGT["agent (Claude)"] -.->|"mcp Consensus__search ≤4<br/>+ Scopus.AI (manual)"| EV["evidence.txt"]
  EV -.->|"--evidence-file"| DELIB
  CONS[("Consensus MCP")] -.-> AGT
```

### Scopus script reference

| Script | Modes / subcommands | External endpoint | Env var |
| --- | --- | --- | --- |
| [scopus_api.py](skills/scopus/scripts/scopus_api.py) | search · cite · validate · verify · author · journal | Elsevier Search / Abstract Retrieval / Author Search / Serial Title | `SCOPUS_API_KEY` |
| [semantic_scholar_api.py](skills/scopus/scripts/semantic_scholar_api.py) | authors · paper | Semantic Scholar Academic Graph | `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` (optional) |
| [download_pdf.py](skills/scopus/scripts/download_pdf.py) | doi · bib | Elsevier Full-Text → S2 openAccessPdf | `SCOPUS_API_KEY` |
| [gemini_table.py](skills/scopus/scripts/gemini_table.py) | table-cell enrichment | Google Gemini 2.0 Flash | `GEMINI_API_KEY` |
| [gemini_reviewer.py](skills/scopus/scripts/gemini_reviewer.py) | peer-review (deliberation) | Google Gemini 2.0 Flash | `GEMINI_API_KEY` |
| [github_reviewer.py](skills/scopus/scripts/github_reviewer.py) | peer-review (deliberation) | GitHub Models (Azure inference) | GitHub token |

## Layer 4 — Deliberation process

The [deliberation](skills/deliberation) skill runs a two-round Gemini + Copilot debate, then hands the merged suggestions to Claude for arbitration. Two hard boundaries shape it ([deliberation-protocol.md](skills/deliberation/references/deliberation-protocol.md)): there is no nested-agent dispatch (it is a skill module, not an agent), and a subprocess cannot reach MCP, so `deliberate.py` runs only the two model APIs while the agent gathers Consensus (and, for [scopus-researcher](agents/scopus-researcher/AGENT.md) only, Scopus.AI) evidence itself and passes it in as a file. The script never accepts, validates, or scores anything — it emits evidence; Claude judges. The deliberation step itself is fully autonomous (no user pause); the one manual checkpoint is the Scopus.AI loop, which belongs to [scopus-researcher](agents/scopus-researcher/AGENT.md) Step 1a upstream — the agent generates a copy-paste prompt menu, HALTs for the user to run it in the Scopus.AI web UI and paste the result back, then folds that output into the same evidence file. The other five agents have no Scopus.AI branch.

```mermaid
flowchart TD
  START["Agent reaches Deliberation step"] --> EVG

  subgraph EVG["Evidence gathering — agent side"]
    direction TB
    CONS["Consensus search ≤4 · 1/s<br/>(MCP, all agents)"]
    subgraph SAI["Scopus.AI MANUAL loop — scopus-researcher Step 1a ONLY"]
      direction TB
      SAGEN["Generate prompt menu P1–P5<br/>natural language, one question each"] --> SAPRES["Present prompts to user<br/>for copy-paste"]
      SAPRES --> SAHALT{{"HALT — manual step, no automation<br/>wait for user"}}
      SAHALT --> USER[/"USER runs prompts in Scopus.AI web UI,<br/>pastes back: Summary · refs+DOIs ·<br/>Concept map · Foundational papers"/]
      USER -.->|"refine / iterate"| SAGEN
      USER --> SAING["Ingest: flag every ref [SCOPUS.AI],<br/>validate via Step 2/3 gate"]
    end
  end

  CONS --> EVF
  SAING --> EVF
  SAHALT -.->|"user skips → omit section"| EVF
  EVF[("evidence.txt")] --> RUN["deliberate.py --stdin<br/>--rounds 2 --evidence-file"]

  subgraph SCRIPT["deliberate.py — Gemini + Copilot only · never accepts/scores"]
    RUN --> AVAIL{"Models<br/>available?"}
    AVAIL -->|"both unavailable"| EMPTY["empty merged[] + skip note<br/>exit 0"]
    AVAIL -->|"≥1 available"| R1["Round 1 — independent critique<br/>each model returns<br/>{overall_assessment, suggestions[]}<br/>type · confidence · requires_scopus_validation"]
    R1 --> R2Q{"--rounds 2?"}
    R2Q -->|"yes"| R2["Round 2 — rebuttal<br/>each sees other's R1 JSON<br/>keep / withdraw / strengthen<br/>+ responses_to_other"]
    R2Q -->|"no (rounds 1)"| MERGE
    R2 --> MERGE["Merge: pair by (section, type)<br/>tag agreement, rank<br/>consensus &gt; high &gt; conflict &gt; medium &gt; low"]
  end

  EMPTY --> SKIP["No-op: record<br/>[REVIEWER UNAVAILABLE] ×2"]
  MERGE --> ARB["Claude arbitrates each merged item<br/>arbitration table → 8 provenance markers"]

  ARB --> GATE{"reference_issue / coverage_gap /<br/>requires_scopus_validation?"}
  GATE -->|"full bib fields"| VER["scopus_api.py verify<br/>accept iff valid:true"]
  GATE -->|"existence only"| SR["scopus_api.py search / validate<br/>accept iff ≥1 result"]
  GATE -->|"no"| DEC{"Claude decision"}
  VER --> DEC
  SR --> DEC

  DEC -->|"accept"| APPLY["Apply change<br/>[✓ GEMINI] / [✓ GEMINI + COPILOT]"]
  DEC -->|"low confidence"| FLAG["Flag only<br/>[? GEMINI — LOW]"]
  DEC -->|"conflict"| CONF["Claude resolves<br/>[✓ GEMINI — COPILOT DISAGREED]"]
  DEC -->|"reject"| REJ["[✗ — reason]"]

  APPLY --> LOG
  FLAG --> LOG
  CONF --> LOG
  REJ --> LOG
  SKIP --> LOG
  LOG["Append ## Deliberation Log<br/>(Accepted / Flagged / Conflicts / Rejected)"] --> SCORE["scholar-evaluation scoring next<br/>(auditors + researcher;<br/>reviewer-response skips)"]
```

The arbitration table maps each merged item's `agreement` (`consensus`, `gemini_only`, `copilot_only`, `conflict`) to one of eight provenance markers. Any item proposing a specific paper passes the Scopus gate first — `verify` (accept on `valid: true`) when full fields exist, else `search`/`validate` (accept on ≥1 result). [reviewer-response](agents/reviewer-response/AGENT.md) is host-stricter: a panel-proposed reference there runs its own decision tree instead of this generic gate. Graceful skips never abort the host pipeline: one model down → debate with the survivor; both down → empty `merged[]`, step is a no-op; Consensus unreachable → empty evidence file, debate runs on the draft alone.

## Notes

- The [deliberation](skills/deliberation) skill is itself a composite step: it runs a two-round Gemini + GitHub Copilot debate, enriches with Consensus and optional Scopus.AI evidence, then re-validates every newly proposed reference through the [scopus](skills/scopus) gate before any suggestion is merged into the plan.
- Reference enrichment and PDF retrieval share one script set under [skills/scopus/scripts/](skills/scopus/scripts): `scopus_api.py` (Elsevier API first) and `download_pdf.py` (Elsevier, then Semantic Scholar open-access fallback).
- The non-academic agents in [agents/](agents) (analysis-engine, blazor-dev, cost-tester, flask-api, react-dev, latex-writer, security-auditor, word-to-latex) serve the CostEstimator software project and are out of scope for this diagram.
