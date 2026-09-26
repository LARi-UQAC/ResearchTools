# PROGRESS_RT.md - ResearchTools execution registry

Single source of truth for **where the UQAC form engine work stands** in this repository.

- The architecture and the unit definitions live in [NEW_ARCHITECTURE.md](NEW_ARCHITECTURE.md)
  section 12. That document says WHAT each unit is; this one says WHERE it is.
- Each unit's implementation plan lives on the unit's own branch at
  `docs/superpowers/plans/2026-07-29-rt-<n>-<slug>.md`. Plans are deliberately not on `main`.
- ThesisTracker tracks its own units in `PROGRESS_TT.md` in that repository. Cross-repo dependencies
  are named in the Blocks column here.

**Snapshot date:** 2026-09-25 (RT-7). Recomputed via git ancestry (RT-1..4 confirmed merged to
`main` by `ls-tree`/branch inspection, cross-checked with the ThesisTracker session's own audit of
this repo) after the 2026-08-13 snapshot below was found stale — it still marked RT-1 as TODO and
RT-2..4 as BLOCKED with zero code, while `NEW_ARCHITECTURE.md`'s own header already said
"Delivered 2026-08-31" for RT-1..3. RT-6's row here was itself found stale within this same RT-7
pass (still read PR open after PR #24 actually merged) - a reminder that this registry drifts even
between adjacent units, not just across large gaps. Recompute again with the commands in section 4
before trusting this one too.

---

## 1. Status vocabulary (strict)

A status is never a judgement call. Each one is derivable from git and the GitHub API, so the
registry can be audited and cannot drift.

| Marker | Status | Machine rule that defines it |
|---|---|---|
| `[ ]` | TODO | Branch exists and `git diff --name-only main..<branch>` contains ONLY the plan file. All dependencies are DONE. |
| `[!]` | BLOCKED | Same as TODO, except at least one dependency is not DONE, or an external answer is pending. |
| `[~]` | IN PROGRESS | The diff against `main` contains code files, and no pull request is open. |
| `[R]` | REVIEW | A pull request is open for the branch. |
| `[x]` | DONE | The branch is merged into `main` (`git merge-base --is-ancestor`) AND the issue is closed. |
| `[-]` | DEFERRED | Intentionally not scheduled. Entry criteria recorded on the issue. |

Precedence: BLOCKED outranks TODO. A unit whose dependencies are unmet is never TODO, so the
"actionable now" list in section 3 is unambiguous.

Rules for updating this file:

1. Never hand-set a status the commands in section 4 contradict.
2. A unit moves to DONE only after the merge, never at "code complete".
3. When a unit's scope changes, edit [NEW_ARCHITECTURE.md](NEW_ARCHITECTURE.md) section 12 first,
   then the Notes column here.
4. Update this file in the same commit that changes a unit's state, so history shows the transition.
5. A unit that adds a skill is not DONE until the wiring checklist in
   [docs/authoring-and-mirrors.md](docs/authoring-and-mirrors.md) section 7 is complete and
   `install.ps1` has regenerated the mirrors. A skill has no per-tool mirror, so the routing row in
   `.claude/CLAUDE.md` is the only thing that makes it discoverable.

---

## 2. Units

All seven ResearchTools units are stateless PDF mechanics. They hold no student data and no form
catalogue: the catalogue, the field maps and the drift check live in ThesisTracker TT-8.

| St | Unit | Issue | Branch | Depends on | Notes |
|---|---|---|---|---|---|
| `[x]` | RT-1 skill scaffold and PDF ingest | [#4](../../issues/4) | `feat/form-service-registry` (was `feat/uqac-forms-registry`) | - | Merged to `main`. Scope reduced on 2026-07-29: the registry and drift check moved to TT-8. |
| `[x]` | RT-2 widget dump and diff | [#5](../../issues/5) | `feat/form-service-field-map` (was `feat/uqac-forms-field-map`) | RT-1 | Merged to `main`. Scope reduced: the map and the vocabulary are TT-8 rows. |
| `[x]` | RT-3 fill | [#6](../../issues/6) | `feat/form-service-filler` (was `feat/uqac-forms-filler`) | RT-2 | Merged to `main`. Scope reduced: no profile, no map, no stale gate. |
| `[x]` | RT-4 sign and chain | [#7](../../issues/7) | `feat/form-service-signer` (was `feat/uqac-forms-signer`) | RT-3 | Merged to `main`, confirmed 2026-09-25 (NEW_ARCHITECTURE.md's header still read it as pending — that line is stale, not this one). Preserves every previous signature. |
| `[x]` | RT-5 stateless service | [#8](../../issues/8) | `feat/form-service` (was `feat/uqac-forms-service`) | RT-4 | Merged to `main` 2026-09-25 (PR #22). `/pdf/widgets`, `/pdf/fill`, `/pdf/sign`, `/pdf/validate`; fail-fast shared-secret gate, no CORS, no work directory. `sign_form.validate_signatures` added (intact/valid/trusted reported separately). `/pdf/fill`'s multipart-vs-raw-body shape checked against ThesisTracker 2026-09-25: TT-3 not built yet, no conflict, no objection raised; reconfirm once TT-3 lands. Docker/Compose stack written but not run end to end (no Docker daemon in the build environment). |
| `[x]` | RT-6 publications endpoint | [#9](../../issues/9) | `feat/publications-endpoint` | RT-5 | Merged to `main` 2026-09-25 (PR #24). `GET /publications`: disk cache, token-bucket rate limiter, `count` capped at 25 (Scopus's own STANDARD-view ceiling, not the plan's original 50). Three plan defects fixed before shipping: `_check_response`'s `sys.exit(1)` would have killed the service worker on a Scopus outage; the naive name-split reintroduced the "Otis, Martin" bug `_split_author_name` was written to fix; the Dockerfile never copied `scopus_api.py`'s skill into the image. Live-Scopus verification and the Docker/Compose build not run (no network/daemon in the build environment). Unblocks ThesisTracker TT-6. |
| `[x]` | RT-7 parse cache and corpus index | [#10](../../issues/10) | `feat/corpus-index` | RT-5 | Merged to `main` 2026-09-25 (PR #26). Content-addressed parse cache (additive to every `extract_text.py` consumer) + opt-in chunker/embedder/pgvector index over a corpus, provenance-only retrieval. Its remote branch was 100+ commits stale with only its 2 plan-writing commits still real (same pattern as RT-6) - reset onto `main` + cherry-picked rather than rebased. Three plan defects fixed before shipping: a bare `import pymupdf` that would silently drop page offsets on a machine only exposing the legacy `fitz` alias; a naive whole-file `.bib` regex reused instead as `bib_audit.parse_bib`'s line-anchored parser (the naive form also matches an `@` inside a field value); a missing `psycopg` surfacing a bare `ModuleNotFoundError` instead of the actionable message the requirements.txt comment promises. Live pgvector-store tests (4) not run against a real database (Docker Desktop not running in the build environment); they skip cleanly by design. |

Counts: 7 units. DONE 7, REVIEW 0, IN PROGRESS 0, BLOCKED 0, TODO 0, DEFERRED 0.

**All seven ResearchTools units are now merged to `main`. This side of the 20-unit programme is
complete; the thirteen remaining units (TT-0 through TT-12) are entirely ThesisTracker's.**

Issues in this repository that are NOT part of this programme and are tracked separately:
[#11](../../issues/11) `download_pdf.py` background download with Cloudflare, and
[#12](../../issues/12) local writer and coder day/night profile.

---

## 3. Actionable now

Nothing. All seven ResearchTools units (RT-1 through RT-7) are merged to `main`; there is no more
RT-side code to write in this programme. What remains, entirely on ThesisTracker: TT-3
(forms-service-client, PR #16) and TT-7 (email-code-auth, PR #15) open awaiting review; TT-4
(forms-ui) in progress; TT-5 and TT-6 unblocked (RT-5 and RT-6 both merged) but not yet started;
TT-0, TT-1, TT-2, TT-8, TT-9, TT-12 merged.

No remaining blocker on the ResearchTools side. A future session touching this repo again is
maintenance or a scope change, not a new numbered unit.

---

## 4. How to recompute this file

Run from the repository root. The output maps directly onto the markers in section 1.

```bash
git fetch origin --quiet
for b in $(git ls-remote --heads origin | sed 's#.*refs/heads/##' | grep '^feat/'); do
  files=$(git diff --name-only origin/main..origin/$b | wc -l)
  code=$(git diff --name-only origin/main..origin/$b | grep -vc 'superpowers/plans')
  merged=$(git merge-base --is-ancestor origin/$b origin/main && echo DONE || echo open)
  printf "%-32s files=%-3s code=%-3s %s\n" "$b" "$files" "$code" "$merged"
done
```

Read it as: `code=0` means plan-only (TODO or BLOCKED), `code>0` means IN PROGRESS or REVIEW,
`DONE` means merged.

Issue state, using the git credential. Do NOT use `GITHUB_TOKEN`: it carries only `read:user` and
cannot see or create issues. The Windows Credential Manager holds an OAuth token with `repo` scope.

```bash
TOK=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')
curl -s -H "Authorization: Bearer $TOK" \
  "https://api.github.com/repos/LARi-UQAC/ResearchTools/issues?state=all&per_page=100"
```

Never write that token to a file and never commit it.

---

## 5. Acceptance gates once a unit is implemented

A ResearchTools unit is not DONE until these pass. They are offline: no network, no API key, no
model load, per [.claude/rules/testing.md](.claude/rules/testing.md).

```powershell
python .claude/skills/form-service/scripts/Test/test_form_registry.py
python .claude/skills/form-service/scripts/Test/test_field_map.py
python .claude/skills/form-service/scripts/Test/test_fill_form.py
python .claude/skills/form-service/scripts/Test/test_sign_form.py
pip-audit -r .claude/skills/form-service/requirements.txt --strict
.\install.ps1 -Profile engineering
```

These existing suites must not regress:

```powershell
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Manual, network-bound, not part of the offline gate:

```powershell
python .claude/skills/form-service/scripts/form_registry.py check --all
pyhanko sign validate out/<signed>.pdf
```

---

## 6. Open items that block completion, not implementation

| Item | Owner | Needed by |
|---|---|---|
| Do the Décanat des études and the Service des ressources financières accept a PAdES signature? The signer is pluggable with a self-signed development default, so implementation proceeds; the production certificate decision (UQAC PKI, or Notarius / ConsignO) waits on this. | Prof. Otis to ask both offices | RT-4, TT-5 |
| `pypdf` and `pyhanko` are not installed on the workstation. RT-1 installs them pinned (`pypdf==6.14.2`, `pyhanko==0.36.2`) and runs `pip-audit`. | RT-1 | RT-1 |
