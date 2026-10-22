# Profiles & Environment

Chapter 02 of the <a href="https://lari-uqac.github.io/ResearchTools/">ResearchTools</a> manual. Back to [table of contents](../../README.md).

## Profiles

A domain profile centralizes everything domain-specific (Scopus subject areas and
exclusions, topical-relevance signals, off-topic flag, stats profile, author, course
context, language) in one YAML file under `profiles/`, so the agents and skills stay
shared across users and labs: one maintained core, N profiles.

| Profile | Domain | Author | Default |
|---|---|---|---|
| `engineering.yaml` | Mechanical / electrical / ML / control / systems engineering | Martin Otis (UQAC) | yes |
| `cosmetic.yaml` | Cosmetic / formulation science (SPF, microbiome, dermatology, sensory) | Lionel Ripoll (UQAC) | no |
| `_template.yaml` | Copy it to `profiles/<domain>.yaml` to add a new domain | - | - |

The active profile is recorded in `.claude/CLAUDE.md` as the machine-readable line
`active_profile: <name>`. Select it at install time (`.\install.ps1 -Profile <name>`, or
the interactive prompt) or edit that line directly. Currently wired consumer:
`scopus-researcher` (search clauses, Step 3a relevance check, synthesis framework); the
remaining fields (`author`, `stats_profile`, `course_context`, `language`) are schema-ready
and will be wired incrementally. Field-by-field spec, fallback rules, and the add-a-profile
procedure: [profiles/README.md](../../profiles/README.md).

## Environment variables / API keys

Set these at the Windows **User** scope (PowerShell), then restart Claude Code:

```powershell
[System.Environment]::SetEnvironmentVariable('SCOPUS_API_KEY', 'your-key', 'User')
```

| Variable / source | Required for | Where to get it |
|---|---|---|
| `SCOPUS_API_KEY` | **Required** — all `/scopus`, `/auditreview`, `/auditpaper`, `/auditthesis`, `/litreview`, `/litupdate`, `/bibclean`, `/replyreviewer`, and PDF retrieval | [Elsevier Developer Portal](https://dev.elsevier.com/) |
| `.scopus_key` file | Fallback for `SCOPUS_API_KEY` — place the key in `.claude/skills/scopus/.scopus_key` (gitignored) | same key as above |
| `UNPAYWALL_EMAIL` | *Optional* — enables the Unpaywall open-access tier in `download_pdf.py` (HTML/PDF fallback when no publisher PDF); a plain contact email, or pass `--email` | any institutional email |
| `GEMINI_API_KEY` | *Optional* — the Gemini leg of the deliberation panel (cross-review, table enrichment). The model is resolved at run time from Google's own catalogue (`--gemini-model auto`), so no model name is set here | [Google AI Studio](https://aistudio.google.com/apikey) |
| `COPILOT_TOKEN` or `GH_OAUTH_TOKEN` | *Optional* — the GitHub Copilot leg of the deliberation panel. `GH_OAUTH_TOKEN` is exchanged automatically for a Copilot token. Without either, the panel uses a local Ollama model declared for the `session` role as the second voice, and without that too the leg is skipped without stopping the pipeline | your GitHub account with Copilot |
| `GITHUB_TOKEN` | *Legacy* — Copilot refuses a personal access token and GitHub Models was retired on 2026-07-30, so this variable no longer gives a cross-review leg. It is still the last attempt of the provider chain | GitHub → Settings → Developer settings |
| `S2_API_KEY` *(or `SEMANTIC_SCHOLAR_API_KEY`)* | *Optional* — Semantic Scholar author/PDF backfill; without it the throttled public pool is used | [Semantic Scholar API key request](https://www.semanticscholar.org/product/api) |
| `--insttoken` *(CLI flag, not an env var)* | *Optional* — off-campus Elsevier access when not on the UQAC network/VPN | UQAC library / Elsevier institutional token |

> An on-campus network connection or active UQAC VPN is required for Scopus access
> unless an `--insttoken` is supplied. Secrets are kept out of git: `.env`, `secrets/`,
> and `credentials/` are listed in `.gitignore`.

### Other variables

| Variable | Used by | Meaning |
|---|---|---|
| `OBSIDIAN_VAULT` | the vault hooks, the vault daemon, `local-writer` | Root of your Obsidian vault. `setup.ps1` offers to set it at user scope when it is unset and never replaces an existing value |
| `PROFESSOR_EXPERTISE_DATA` | `professor-expertise-finder` | Folder holding the location tables and batch registries. Default `~/workspace/professor-expertise` |
| `AUGUREAI_API_KEY` | `claude-augure` in `scripts/local/claude-switch.ps1` | Key sent as `ANTHROPIC_API_KEY` when a session is routed through AugureAI, see [chapter 03](03-token-management.md) |
| `FORM_SERVICE_KEY`, `FORM_SERVICE_HOST` | `deploy/form-service/` | Shared secret and public host name of the PDF-form API, see [chapter 14](14-thesistracker-integration.md) |
| `WP_NONCE`, `WP_COOKIES`, `WP_BASE` | `wp-portfolio-sync` | WordPress cookie authentication, its cookie file and the site address, for the one-time portfolio migration |
| `RT_PG_PASSWORD` | `rt_store.py` of the dashboard | Password of the optional PostgreSQL identity layer, read only when `observe-config.json` declares a `postgres` block |
| `RT_OO_USER`, `RT_OO_PASSWORD` | `rt_openobserve.py` of the dashboard | Credentials of the optional OpenObserve trace stream, read only when an `openobserve` block is declared |
| `CORPUS_INDEX_DSN` | the optional corpus index of `extract-statistic` | Connection string of a PostgreSQL database with pgvector. Without it the four tests that need a live database are skipped |

The Ollama settings (`OLLAMA_KEEP_ALIVE` and others) are not API keys and belong to the user
registry, not to Claude Code's `env` block, see [chapter 01](01-installation.md).

---
[← 01 Installation](01-installation.md) | [Table of contents](../../README.md) | [03 Token management →](03-token-management.md)
