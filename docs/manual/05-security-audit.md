# Security Audit (SkillSpector)

Chapter 05 of the ResearchTools manual. Back to [table of contents](../../README.md).

All eight skills under `.claude/skills/` were scanned with **SkillSpector v2.2.3** in
static-only mode (`skillspector scan <skill> --no-llm`) on **2026-06-18**, every dependency
finding cross-checked against `pip-audit`.

**True positives — corrected**

- **LP3 (missing permission declaration):** added to the frontmatter of `scopus`, `deliberation`,
  `extract-statistic`, `scholar-evaluation`, `word2latex`, and `drawio2tikz` a per-skill
  `permissions:` list declaring exactly the capabilities each skill's scripts use (e.g. `scopus`
  → `[env, read, write, network]`), plus an `allowed-tools: [Read, Write, Edit, Bash]` runtime
  restriction. Re-scan confirms LP3 cleared with no LP1/LP4 regression.
- **SC1 (unpinned dependencies):** pinned `>=` to exact `==` versions in
  `scopus/scripts/requirements.txt` (requests, google-genai, openai) and
  `extract-statistic/scripts/requirements.txt` (pymupdf4llm, pymupdf, docling, markitdown),
  using versions confirmed clean by `pip-audit`.

**False positives — reviewed and ignored**

- **SC4 (vulnerable dependency):** flagged by package name only; `pip-audit` resolves every
  declared `>=` floor to a patched release (`No known vulnerabilities found`).
- **E1 / E2 (external transmission / env harvesting):** skills reading their own configured API
  keys and querying their own research APIs (Elsevier, Unpaywall, Semantic Scholar).
- **TT2 (taint flow):** the https-only, redirect-disabled PDF download in `download_pdf.py`.
- **PE3 / RA2 / EA1 / EA2 / P6:** keyword matches inside docstrings/markdown (e.g. `SNIPList`,
  the `GITHUB_TOKEN` doc line, a `**…tool:**` bullet, a DOI-workflow description, a returned
  local prompt string).
- **AST4 (subprocess):** the test harness invoking the skill script with a fixed argument list.

`scientific-writing` and `extract-futureworks` required no changes.

The `geolocalisation` skill was added after this scan (2026-07) and should be scanned on the
next pass. Its declared dependencies pin exact/floor versions verified with `pip-audit`:
`matplotlib==3.9.2`, `pillow>=12.3.0` (fixes PYSEC-2026-2253..2257), and the optional
`folium==0.17.0` / `PyMuPDF==1.27.2`. It declares `permissions: [read]` and
`allowed-tools: [Read, Write, Edit, Bash]`, reuses the scopus skill's network I/O through
`download_pdf.py` rather than opening its own, and fetches only public-domain Natural Earth
basemaps (TLS-verified, cached).

---
[← 04 Skills](04-skills.md) | [Table of contents](../../README.md) | [06 Aider nightly pipeline →](06-aider-pipeline.md)
