# WordPress portfolio migration (CIHR XML -> WordPress)

Migrate a researcher's final CIHR / Canadian Common CV XML export into their WordPress
portfolio, once, via the `wp-portfolio-agent` agent and the `wp-portfolio-sync` skill.

Procedure:

1. Resolve from `$ARGUMENTS` (or ask, grouped, if missing): the path to the researcher's CV
   XML export, and the data folder (`--data-dir`) their researcher data lives in — a path
   outside this repository (the repository is public).
2. Delegate to the `wp-portfolio-agent` agent, which runs the full contractual pipeline:
   parse the XML, discover WordPress pages on a first run, preview every planned change and
   pause for approval, dry-run the push, push for real only after explicit approval, and
   verify the public pages.
3. Report the agent's own ✓/✗ exit checklist, the per-page push results, and the public-page
   verification outcome.

The website becomes the source of truth for whatever this migration pushes. Never ask the
agent to re-run the migration over a page the researcher says they have since edited by
hand — the agent's Step 4 is built to catch exactly that and will stop on its own.

Respond in French unless the active file is in English.

$ARGUMENTS
