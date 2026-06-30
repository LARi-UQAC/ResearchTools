# Domain profiles

A **profile** centralizes everything domain-specific so the rest of the repo (agents,
skills, auditors) stays **shared across users and labs**. One maintained core, N profiles —
only the profile changes between an engineering user and a cosmetic-science user.

This generalizes the pattern already shipped in `extract-statistic`
(`references/domain-profiles.md`, engineering + cosmetic) to the whole repo.

## Active profile

Declared in the repo `CLAUDE.md` (`Profil actif : <name>`), or overridden per-session with
the `ACTIVE_PROFILE` environment variable. **Default: `engineering`.**

## Files

| File | Domain |
|---|---|
| `engineering.yaml` | Mechanical / electrical / ML / control (default) |
| `cosmetic.yaml` | Formulation, SPF, microbiome, dermatology |
| `_template.yaml` | Copy this to add a new domain |

## What a profile controls

| Field | Consumed by |
|---|---|
| `author.*` | cover-paper, submit-checker |
| `scopus.subject_areas` | scopus-researcher, scopus-auditor (search anchor) |
| `scopus.relevance_signals` + `off_topic_flag` | scopus-researcher Step 3a content/relevance check |
| `stats_profile` | extract-statistic (audit + mine) |
| `framework_default` | scopus-researcher synthesis framework |
| `course_context` | course authoring (null = none) |
| `language` | manuscript + response language defaults |

## What stays shared / domain-neutral

Auditor structure (paper/thesis/proposal), `deliberation`, `scholar-evaluation`,
`scientific-writing` (IMRAD, citation styles, reporting guidelines), conversions
(`word2latex`), `extract-futureworks`, `drawio2tikz`, anti-AI-style rules. None read the profile.

## How agents read a profile

Profile-aware agents **read the YAML directly** (no script, no interpreter): they read
`Profil actif : <name>` from `CLAUDE.md`, then `profiles/<name>.yaml`, and use its values
(building the Scopus `SUBJAREA(...)` clause by joining `scopus.subject_areas`, etc.). The
inline domain values in those agents are the engineering defaults shown for reference.

## Status

- `scopus-researcher` reads the active profile (subject areas, relevance signals, off-topic
  flag, framework). Switching `Profil actif :` switches its domain.
- Other domain-specific agents (course/journal selection, cover-paper author) can be wired the
  same way incrementally.

## Adding a profile

1. `cp profiles/_template.yaml profiles/<domain>.yaml`, fill it in.
2. Add a matching `<domain>` block to `.claude/skills/extract-statistic/references/domain-profiles.md`.
3. Set `Profil actif : <domain>` in `CLAUDE.md` (or `export ACTIVE_PROFILE=<domain>`).

> Target-journal requirements are resolved per submission by submit-checker (via Scopus / web),
> independently of the profile.
