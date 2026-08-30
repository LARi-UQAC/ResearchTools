# Domain profiles

A **profile** centralizes everything domain-specific so the rest of the repo (agents,
skills, auditors) stays **shared across users and labs**. One maintained core, N profiles:
only the profile changes between an engineering user and a cosmetic-science user.

This generalizes the pattern already shipped in `extract-statistic`
(`references/domain-profiles.md`, engineering + cosmetic) to the whole repo.

## Active profile

Declared in [.claude/CLAUDE.md](../.claude/CLAUDE.md), section "Domain profile", as a
machine-readable line:

```yaml
active_profile: engineering
```

plus a human-readable French line (`Profil actif : engineering`). That file is the single
authoritative location. `install.ps1` sets both lines: pass `-Profile <name>` or answer its
interactive prompt (non-interactive runs default to `engineering`). There is no
environment-variable override.

**Default: `engineering`.** If the selected profile's YAML is missing or malformed, agents
fall back to `profiles/engineering.yaml`; if that also fails, they stop with an error
instead of guessing values.

## Files

| File | Domain |
|---|---|
| `engineering.yaml` | Mechanical / electrical / ML / control (default) |
| `cosmetic.yaml` | Formulation, SPF, microbiome, dermatology |
| `_template.yaml` | Copy this to add a new domain |

## What a profile controls

The YAML is the **single source of truth**: profile-aware agents read it directly (no
script, no interpreter) and carry no inline copy of its values.

Wired now:

| Field | Consumed by |
|---|---|
| `scopus.subject_areas` | scopus-researcher: `AND ( SUBJAREA(...) )` inclusion clause of every query |
| `scopus.exclude_areas` | scopus-researcher: `AND NOT ( SUBJAREA(...) )` exclusion clause |
| `scopus.relevance_signals` + `off_topic_flag` | scopus-researcher Step 3a topical-relevance check |
| `framework_default` | scopus-researcher Step 1d.2 synthesis framework |
| `author.letter` | recommendation-letter: WHO signs the letter. Read by `letter_identity.py`, which refuses by name when the block or one of its keys is absent rather than borrowing another profile's identity - signing a letter with someone else's name, laboratory and telephone number is a wrong answer that reads exactly like a right one. `profiles/_template.yaml` carries the full key list; a profile that never generates letters simply omits the block |

Planned (fields exist in the schema, consumers not wired yet):

| Field | Planned consumer |
|---|---|
| `author.name` / `email` / `institution` / `department` | cover-paper, submit-checker (`author.letter` is wired, see above) |
| `stats_profile` | extract-statistic (audit + mine) |
| `course_context` | course authoring (null = none) |
| `language` | manuscript + response language defaults |

Switching to a profile only switches the behavior of the wired consumers; the planned ones
still use their built-in engineering values until wired.

## What stays shared / domain-neutral

Auditor structure (paper/thesis/proposal), `deliberation`, `scholar-evaluation`,
`scientific-writing` (IMRAD, citation styles, reporting guidelines), conversions
(`word2latex`), `extract-futureworks`, `drawio2tikz`, anti-AI-style rules. None read the
profile.

## How agents read a profile

1. Read `.claude/CLAUDE.md`, find `active_profile: <name>` (fallback: the prose line
   `Profil actif : <name>`).
2. Read `profiles/<name>.yaml`. Both paths are relative to the repo root.
3. Build the Scopus clauses by joining `scopus.subject_areas` (primary then secondary) and
   `scopus.exclude_areas` as `SUBJAREA(<code>) OR ...`.
4. On a missing or malformed file, fall back to `profiles/engineering.yaml`, then hard
   stop with an error.

## Adding a profile

1. `cp profiles/_template.yaml profiles/<domain>.yaml`, fill it in.
2. Pre-flight check (nothing validates the YAML automatically):

   ```bash
   python -c "import yaml,glob; [yaml.safe_load(open(f,encoding='utf-8')) for f in glob.glob('profiles/*.yaml')]"
   ```

   and verify by hand that `subject_areas.primary` is non-empty, every code is a valid
   Scopus SUBJAREA code, `relevance_signals` is non-empty, and `off_topic_flag` is set.
3. Add a matching `<domain>` block to
   `.claude/skills/extract-statistic/references/domain-profiles.md` (used once
   `stats_profile` is wired).
4. Activate it: `.\install.ps1 -Profile <domain>`, or edit the `active_profile:` line in
   `.claude/CLAUDE.md`.

> Target-journal requirements are resolved per submission by submit-checker (via Scopus /
> web), independently of the profile.
