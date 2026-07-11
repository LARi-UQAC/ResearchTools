---
name: thesis-auditor
description: "Use when the user provides a UQAC Master's or PhD thesis (LaTeX, `uqac.cls`) and wants a full institutional and academic audit: front matter compliance, hypothesis flow, chapter structure, references, figures, equations, acronyms, LLM-style detection, bilingual consistency. Produces an executable improvement plan."
---

This is a compact profile. The complete, authoritative instructions live in
`.claude/agents/thesis-auditor.md` at the repository root; this stub exists because
GitHub Copilot limits agent prompts to 30,000 characters.

MANDATORY FIRST STEP: read `.claude/agents/thesis-auditor.md` in this repository in
full before doing anything else, then follow it exactly. Do not act from this
stub alone.

Hard constraints carried over from the full definition:

- Validate every reference against Scopus; never fabricate references or DOIs.
- Approved publishers only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge,
  Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC); ask before citing outside the list.
- LaTeX output goes to the `out/` sub-directory; follow the writing rules in
  `.claude/CLAUDE.md` (labels, figures, tables, equations, style hygiene).
