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
| `S2_API_KEY` *(or `SEMANTIC_SCHOLAR_API_KEY`)* | *Optional* — Semantic Scholar author/PDF backfill and keyword search; without it the throttled public pool is used, where a search can be refused (429) and exits 1 | [Semantic Scholar API key request](https://www.semanticscholar.org/product/api) |
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
| `FORM_SERVICE_KEY`, `FORM_SERVICE_HOST` | `deploy/form-service/` | Shared secret and public host name of the PDF-form API, see [chapter 17](17-thesistracker-integration.md) |
| `WP_NONCE`, `WP_COOKIES`, `WP_BASE` | `wp-portfolio-sync` | WordPress cookie authentication, its cookie file and the site address, for the one-time portfolio migration |
| `RT_PG_PASSWORD` | `rt_store.py` of the dashboard | Password of the optional PostgreSQL identity layer, read only when `observe-config.json` declares a `postgres` block |
| `RT_OO_USER`, `RT_OO_PASSWORD` | `rt_openobserve.py` of the dashboard | Credentials of the optional OpenObserve trace stream, read only when an `openobserve` block is declared |
| `CORPUS_INDEX_DSN` | the optional corpus index of `extract-statistic` | Connection string of a PostgreSQL database with pgvector. Without it the four tests that need a live database are skipped |

The Ollama settings (`OLLAMA_KEEP_ALIVE` and others) are not API keys and belong to the user
registry, not to Claude Code's `env` block, see [chapter 01](01-installation.md).


## Python environments: every library

A skill that imports a library nobody declared works on the machine that happens to have it and
fails on every other one, so this section lists every third-party library the repository's Python
code needs, one row per library. It was built on 2026-10-22 by reading the `import` statements of
all 404 `.py` files (skills, hooks, scripts and tests, but not `docs/superpowers/`), then comparing
them with every requirements file and with what each environment really holds. The environments are
two: `.venv-skills`, for the skills, the hooks' tests and the offline suite, and `.venv-docs`, for
this site. A library used in both has a row in each table with its own version, since the two
environments are independent and do not always agree.

How to read the tables:

- ☑ in the first column means the library is declared in a requirements file. ☐ means the code
  uses it and no file declares it, and the note says why.
- "Version" is what the environment holds on this machine on 2026-10-22, measured with
  `pip list`, and not the version a fresh install would resolve.
- `(added)` marks a line added to a requirements file on 2026-10-22 because the code imported the
  library and no file declared it.
- A library that is optional in code (a guarded or lazy `import`) is marked `optional`.
- Programs that are not pip packages (pandoc, Poppler, MiKTeX, Ollama, Node.js) are in the
  Prerequisites table of [chapter 01](01-installation.md).

### `.venv-skills`

Python 3.11.0 on this machine. Created by `.\setup.ps1 -InstallPython`, which installs only the
requirements files named in `scripts/lib/rt-python-requirements.json`: `paper2talk`,
`recommendation-letter`, `scopus` and `extract-statistic` (without `docling`), plus `pip-audit`.
The last column says whether that command installs the library. Everything else was installed by
hand. The environment holds 180 packages, and most of the ones not listed here are dependencies of
the listed ones (`mineru` pulls a very large tree).

<!-- python-libs:begin .venv-skills -->
| Declared | Library | Import | Pin | Declared in | Used by | Optional | Note |
|---|---|---|---|---|---|---|---|
| ☑ | `claude-agent-sdk` | claude_agent_sdk | 0.2.172 | loop-engineer `==0.2.172` | loop-engineer | yes | only the live loop path of loop_engineer.py |
| ☑ | `cryptography` | cryptography | 50.0.2 | form-service `==50.0.2` | form-service | yes |  |
| ☑ | `curl_cffi` | curl_cffi | 0.15.0 | scopus `==0.15.0` | scopus | yes |  |
| ☑ | `defusedxml` | defusedxml | 0.7.1 | paper2talk `==0.7.1`; drawio2tikz `==0.7.1`; wp-portfolio-sync `==0.7.1` | drawio2tikz, paper2talk, wp-portfolio-sync | yes |  |
| ☑ | `docling` | docling | 2.142.0 | extract-statistic `==2.142.0` | extract-statistic | yes | MIT licence; pulls torch and downloads layout models on first run |
| ☑ | `faster-whisper` | faster_whisper | 1.2.1 | opt-local-stt-vram `==1.2.1`; rt-observe `==1.2.1` | opt-local-stt-vram, rt-observe | yes | pulls ctranslate2 |
| ☑ | `folium` | folium | 0.20.0 | geolocalisation `==0.20.0` | geolocalisation | yes |  |
| ☑ | `google-genai` | google | 2.8.0 | scopus `==2.8.0` | scopus | yes | imported as google.genai |
| ☑ | `Jinja2` | jinja2 | 3.1.6 | paper2talk `==3.1.6` | paper2talk | yes |  |
| ☑ | `markitdown` | markitdown | 0.1.6 | extract-statistic `[pdf]==0.1.6` | extract-statistic | yes | MIT licence |
| ☑ | `matplotlib` | matplotlib | 3.9.2 | geolocalisation `==3.9.2` | geolocalisation | yes |  |
| ☑ | `numpy` | numpy | 2.4.6 | word2latex `==2.4.6` | aider-setup, word2latex | yes | aider-setup also imports it, in aider's own interpreter |
| ☑ | `nvidia-cublas-cu12` | (none) | 12.9.2.10 | rt-observe `==12.9.2.10` | - | yes | never imported: stt_engine.py puts its DLL folder on PATH for GPU speech-to-text; Windows and Linux only |
| ☑ | `nvidia-cuda-nvrtc-cu12` | (none) | 12.9.86 | rt-observe `==12.9.86` | - | yes | same, Windows and Linux only |
| ☑ | `nvidia-cudnn-cu12` | (none) | 9.26.0.51 | rt-observe `==9.26.0.51` | - | yes | same, Windows and Linux only |
| ☑ | `openai` | openai | 2.43.0 | scopus `==2.43.0` | scopus | yes |  |
| ☑ | `openpyxl` | openpyxl | 3.1.5 | professor-expertise-finder `==3.1.5` | professor-expertise-finder | yes | only for .xlsx and .xlsm input |
| ☑ | `pgvector` | (none) | 0.5.0 | extract-statistic `==0.5.0` | - | yes | no .py file imports it: the vector store is SQL |
| ☑ | `pillow` | PIL | 13.0.0 | extract-statistic `==13.0.0`; geolocalisation `==13.0.0`; word2latex `==13.0.0` | word2latex | yes | also pinned where it is only transitive, to keep the fixed version |
| ☑ | `pip-audit` | (none) | 2.10.1 | data file tools `==2.10.1` | - |  | run as a module (python -m pip_audit), never imported |
| ☑ | `playwright` | playwright | 1.61.0 | scopus `==1.61.0` | scopus | yes | the Chromium binary is a separate playwright install chromium |
| ☑ | `playwright-stealth` | playwright_stealth | 2.0.3 | scopus `==2.0.3` | scopus | yes |  |
| ☑ | `psycopg` | psycopg | 3.3.6 | extract-statistic `[binary]==3.3.6`; rt-observe `[binary]==3.3.6` | extract-statistic, rt-observe | yes |  |
| ☑ | `pyHanko` | pyhanko | 0.37.0 | form-service `==0.37.0` | form-service |  | MIT licence |
| ☑ | `PyMuPDF` | fitz, pymupdf | 1.27.2.3 | paper2talk `==1.27.2.3`; extract-statistic `==1.27.2.3` | extract-statistic, geolocalisation, paper2talk, pdf2md, scopus | yes | AGPL-3.0 licence; scopus uses it when present without declaring it |
| ☑ | `pymupdf4llm` | pymupdf4llm | 1.27.2.3 | extract-statistic `==1.27.2.3` | extract-statistic | yes | AGPL-3.0 licence |
| ☑ | `pypdf` | pypdf | 6.21.1 | paper2talk `==6.21.1`; form-service `==6.21.1`; narrative-cv `==6.21.1` | form-service, narrative-cv, paper2talk |  |  |
| ☑ | `python-pptx` | pptx | 1.0.2 | paper2talk `==1.0.2` | paper2talk | yes |  |
| ☑ | `PyYAML` | yaml | 6.0.3 | recommendation-letter `==6.0.3`; narrative-cv `==6.0.3`; wp-portfolio-sync `==6.0.3` | narrative-cv, pdf2md, recommendation-letter, wp-portfolio-sync |  | read with yaml.safe_load only |
| ☑ | `requests` | requests | 2.34.2 | scopus `==2.34.2`; extract-statistic `==2.34.2`; form-service `==2.34.2`; wp-portfolio-sync `==2.34.2` | extract-statistic, form-service, scopus, wp-portfolio-sync |  |  |
| ☑ | `tiktoken` | tiktoken | 0.14.0 | loop-engineer `==0.14.0` | aider-setup, loop-engineer | yes | aider-setup also uses the copy in aider's own interpreter |
<!-- python-libs:end .venv-skills -->

Eleven skills declare their libraries in a file that `-InstallPython` does not read:
`rt-observe`, `opt-local-stt-vram`, `word2latex` and `drawio2tikz` (all four with a requirements
file created on 2026-10-22), `form-service`, `pdf2md`, `geolocalisation`, `narrative-cv`,
`wp-portfolio-sync`, `professor-expertise-finder` and `loop-engineer`. Adding them
to the data file is a one-line change per file and is left for a separate change, because it
changes what the installer installs.

### `.venv-docs`

Python 3.13.3 on this machine. It is created by hand, `setup.ps1` does not create it: see
[chapter 16](16-maintenance.md). It holds the 40 pinned lines of `requirements-docs.txt` plus pip, and the
installed versions match the pins exactly. The site needs `mkdocs` and `mkdocs-material` (the
theme), `pymdown-extensions` and `Markdown` (the extensions listed in `mkdocs.yml`: `attr_list`,
`md_in_html`, `tables`, `toc`, `pymdownx.superfences`, `pymdownx.highlight` and
`pymdownx.slugs`), `ghp-import` (the `gh-deploy` command) and `PyYAML`. The build hook
`scripts/docs/mkdocs_hooks.py` uses the standard library only.

Eleven lines are marked orphan: nothing installed in this environment requires them, or they are
required only by another orphan. They are not needed to build the site. Their set matches the
dependencies of `pip-audit`, which suggests a past install of it, but that is an inference and not
checked. They are left in `requirements-docs.txt` for now.

<!-- python-libs:begin .venv-docs -->
| Declared | Library | Pin | Role | Note |
|---|---|---|---|---|
| ☑ | `babel` | 2.18.0 | transitive |  |
| ☑ | `backrefs` | 8.0 | transitive |  |
| ☑ | `certifi` | 2026.10.19 | transitive |  |
| ☑ | `charset-normalizer` | 3.5.1 | transitive |  |
| ☑ | `click` | 8.5.0 | transitive |  |
| ☑ | `colorama` | 0.4.6 | transitive |  |
| ☑ | `ghp-import` | 2.1.0 | direct |  |
| ☑ | `idna` | 3.20 | transitive |  |
| ☑ | `Jinja2` | 3.1.6 | transitive |  |
| ☑ | `Markdown` | 3.11 | direct |  |
| ☑ | `MarkupSafe` | 3.0.3 | transitive | a dependency of Jinja2, imported directly by talk_model.py |
| ☑ | `mergedeep` | 1.3.4 | transitive |  |
| ☑ | `mkdocs` | 1.6.1 | direct |  |
| ☑ | `mkdocs-get-deps` | 0.2.2 | transitive |  |
| ☑ | `mkdocs-material` | 9.7.7 | direct |  |
| ☑ | `mkdocs-material-extensions` | 1.3.1 | transitive |  |
| ☑ | `packaging` | 26.3 | transitive |  |
| ☑ | `paginate` | 0.5.7 | transitive |  |
| ☑ | `pathspec` | 1.1.1 | transitive |  |
| ☑ | `platformdirs` | 4.12.0 | transitive |  |
| ☑ | `Pygments` | 2.21.0 | direct |  |
| ☑ | `pymdown-extensions` | 12.1 | direct |  |
| ☑ | `python-dateutil` | 2.9.0.post0 | transitive |  |
| ☑ | `PyYAML` | 6.0.3 | direct | read with yaml.safe_load only |
| ☑ | `pyyaml_env_tag` | 1.1 | transitive |  |
| ☑ | `requests` | 2.34.2 | transitive |  |
| ☑ | `six` | 1.17.0 | transitive |  |
| ☑ | `urllib3` | 2.8.0 | transitive |  |
| ☑ | `watchdog` | 6.0.0 | transitive |  |
<!-- python-libs:end .venv-docs -->

### `.venv-pdf2md`

The environment of the `pdf2md` conversion (mineru), kept apart from `.venv-skills` because mineru needs gradio and every gradio caps pillow below 13.0.0.

<!-- python-libs:begin .venv-pdf2md -->
| Declared | Library | Import | Pin | Declared in | Used by | Optional | Note |
|---|---|---|---|---|---|---|---|
| ☑ | `mineru` | (none) | 4.0.11 | pdf2md `==4.0.11` | - |  | used through the mineru-kit command |
| ☑ | `mineru-llama-cpp` | mineru_llama_cpp | 0.1.2 | pdf2md `==0.1.2` | pdf2md | yes | the VLM server binary mineru starts |
| ☑ | `PyMuPDF` | fitz, pymupdf | 1.27.2.3 | pdf2md `==1.27.2.3` | extract-statistic, geolocalisation, paper2talk, pdf2md, scopus | yes | AGPL-3.0 licence; scopus uses it when present without declaring it |
| ☑ | `PyYAML` | yaml | 6.0.3 | pdf2md `==6.0.3` | narrative-cv, pdf2md, recommendation-letter, wp-portfolio-sync |  | read with yaml.safe_load only |
<!-- python-libs:end .venv-pdf2md -->

### A third environment

`deploy/form-service/` has its own environment, `%LOCALAPPDATA%\ResearchTools\venv-form-service`,
described by `deploy/form-service/requirements.txt`: `fastapi==0.141.1`, `uvicorn==0.54.0`,
`pypdf==6.19.0`, `pyHanko==0.37.0`, `cryptography==50.0.1` and `requests==2.34.2`. Two of them
differ from `.venv-skills`, which holds `fastapi` 0.159.1 and `cryptography` 50.0.2. The service
tests run in that environment, not in `.venv-skills`.

### Keeping these tables true

No script regenerates them. A library added to a skill without a line in its requirements file is
exactly the gap this section was written to close, so a change that adds an `import` of a new
third-party library also adds the line, with an exact version checked by `pip-audit`
([chapter 16](16-maintenance.md)), and one row here.

---
[← 01 Installation](01-installation.md) | [Table of contents](../../README.md) | [03 Token management →](03-token-management.md)
