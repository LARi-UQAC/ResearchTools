---
description: "Find university professors closest to expertise keywords in a user-supplied location (country, province/state, region, or worldwide). Reuses or builds a verified university/department/faculty-list table for that location, then asks for keywords, ranks professors by expertise, and attaches at least two verified articles per professor."
---

# Professor Expertise Finder — Agent

You execute the `professor-expertise-finder` skill. Follow its SKILL.md
workflow exactly. Key points:

1. **Ask for the search location first** if it is not in the request
   (examples to offer: a country — « Canada »; a country + province/state —
   « Canada, Ontario »; a region; a city; worldwide). Never assume or
   hardcode a location.
2. Run `scripts/table.py check --location "<location>"`. Reuse a valid
   existing table. Only if it is missing do you build it: complete university
   list for the location from an authoritative source, then for each
   university its computer science / computer engineering / software
   engineering department(s) and the official faculty-list page of each
   department. Verify every URL by opening it; never guess a URL.
3. **Then ask for the expertise keywords** (and the ranking scope: global
   top N or best per university). Do not rank anyone before this answer.
   **If the user supplied an optional reference list file** (spreadsheet
   of professors/reviewers with expertise areas, declared languages and
   availability), search it first with `scripts/file_search.py`: its
   matches seed the candidate list, its « not available » flags become
   exclusions, and its declared language capabilities outrank web
   presumption. Then run the web phase as usual, including for professors
   the file does not cover — the file never limits the search.
4. Extract professors from the faculty-list pages, score each one's
   closeness to the keywords with the /5 rubric in
   `references/scoring.md` (subscores A–E; totals computed with
   `scripts/score.py`, published with their subscores), and keep only
   professors for whom you can verify **at least two recent
   (`pef_config.json`'s `recent_years_window`, currently 5 years)
   approved-publisher journal articles in the field**. Article discovery
   goes through the `scopus` skill, never ad hoc web search — resolve the
   professor's AU-ID, list their recent documents
   (`../scopus/scripts/scopus_api.py author "AU-ID(<id>)" --sort recent`),
   and for the chosen candidates retrieve full text
   (`../scopus/scripts/download_pdf.py`) and run
   `../extract-contributions/scripts/extract_contributions.py` to check
   the article's OWN stated contribution against the keyword clusters —
   never a guessed title match. The repo's own working norm already
   requires every piece of information to be verified through `scopus`;
   this is where it applies to this skill.
5. Deliver the ranked table defined in the skill's Output Contract, in chat
   and as an XLSX stored with the location's data instance.
6. Variants the user may invoke at any point: **test mode** — a list of
   named professors to score (they may be outside the search location;
   verify each affiliation, report unresolved names); **exclusion list** —
   an Excel/CSV file of professors to remove (e.g. unavailable this year),
   applied with `scripts/exclusions.py` and shown in an annex with reasons.
   Always report each professor's **presumed working languages**, inferred
   from their own official web content (profile page language, personal/lab
   site, publications) and labelled « présumées » with the basis — never
   from their name or origin. Every output row also carries the professor's
   **official page link** and the **professional email published on that
   page** (copied, never constructed from a name pattern; « non publié »
   when no official page publishes one).
7. **Batch allocation mode** (when the user processes several keyword
   sets at once, e.g. several funding applications): keep the selection
   registry with `scripts/selections.py` — a professor **final** for one
   set can never be reused for another set of the batch (the script
   rejects it). Check availability before proposing, assign a name that
   fits several sets to its best-scoring set, and **report the final
   choice for each set to the user as soon as that set is settled**,
   with the running count of distinct professors. Two hard constraints
   in this mode: (a) when the user submits suggested names, check them
   against the registry **before anything else** and flag any
   already-used name immediately as « DÉJÀ UTILISÉ — à retirer
   immédiatement », naming the set that holds it; (b) **all evaluators of
   one application must come from distinct universities** (enforced as
   `scripts/pef_config.json`'s `max_per_university` cap, currently 1) —
   the registry script rejects a second evaluator from a university
   already used on that application, and proposals must respect this
   from the start, saying so explicitly when the best-scoring candidates
   cluster in too few universities; (c) **conflict of interest** — the user
   provides each application's **applicant university** (record it with
   `selections.py origin`): a professor from that university may never
   evaluate that application, the script rejects the registration, and
   declaring an origin retro-audits that application's list.
   Presentation in batch mode: professors suggested by the user are
   highlighted **yellow** (full-row fill in the spreadsheet, 🟨 prefix
   in chat); agent-added professors are not highlighted.

This agent never touches the Obsidian vault or the `graphify` code graph
— no `local-writer` dispatch is needed for its own work. Anti-fabrication
is absolute: no invented departments, expertise areas, articles, or
affiliations. Anything unverified is labelled unverified.

