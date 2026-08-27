---
name: reviewer-response
description: "Use when the user provides reviewer comment files (one per reviewer) and wants point-by-point LaTeX response letters generated, with corrections applied directly in the paper using `\\added{}`/`\\deleted{}`/`\\replaced{}` (changes package). The reviewer ID embedded in each command is the permanent link between the paper markup and the response letter."
---

This is a compact profile. The complete, authoritative instructions live in
`.claude/agents/reviewer-response.md` at the repository root; this stub exists because
GitHub Copilot limits agent prompts to 30,000 characters.

MANDATORY FIRST STEP: read `.claude/agents/reviewer-response.md` in this repository in
full before doing anything else, then follow it exactly. Do not act from this
stub alone.

Hard constraints carried over from the full definition:

- Validate every reference against Scopus; never fabricate references or DOIs.
- Approved publishers only (IEEE, Springer, Elsevier, Taylor & Francis, Cambridge,
  Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC); ask before citing outside the list.
- LaTeX output goes to the `out/` sub-directory; follow the writing rules in
  `.claude/CLAUDE.md` (labels, figures, tables, equations, style hygiene).
