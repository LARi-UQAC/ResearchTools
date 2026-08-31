---
name: cover-paper
description: "Use when a paper is about to be submitted to a journal and needs its submission package: (a) a Cover Letter, standalone or hidden inside the main `.tex`, (b) for Elsevier / Springer / Wiley / MDPI only, a separate Title Page PDF carrying the ethics and integrity declarations, (c) a Corresponding Author Profile PDF listing affiliations, online identifiers, and the author's 10 most recent journal papers retrieved from Scopus by AU-ID, (d) a Graphical Abstract built with the Canva MCP plugin from the paper's own figures, and (e) for an invited extension of a conference paper, the mandatory Contributions Disclosure Letter quantifying the new material. The artifact set is publisher-aware: IEEE collects the title-page declarations in its submission portal and instead requires the disclosure letter."
---

This is a compact profile. The complete, authoritative instructions live in
`.claude/agents/cover-paper.md` at the repository root; this stub exists because
GitHub Copilot limits agent prompts to 30,000 characters.

MANDATORY FIRST STEP: read `.claude/agents/cover-paper.md` in this repository in
full before doing anything else, then follow it exactly. Do not act from this
stub alone.

Hard constraints carried over from the full definition:

- Validate every reference against Scopus; never fabricate references or DOIs.
- Approved publishers only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge,
  Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC); ask before citing outside the list.
- LaTeX output goes to the `out/` sub-directory; follow the writing rules in
  `.claude/CLAUDE.md` (labels, figures, tables, equations, style hygiene).
