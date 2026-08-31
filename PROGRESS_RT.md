# PROGRESS_RT.md - ResearchTools execution registry

Single source of truth for **where the UQAC form engine work stands** in this repository.

- The architecture and the unit definitions live in [NEW_ARCHITECTURE.md](NEW_ARCHITECTURE.md)
  section 12. That document says WHAT each unit is; this one says WHERE it is.
- Each unit's implementation plan lives on the unit's own branch at
  `docs/superpowers/plans/2026-07-29-rt-<n>-<slug>.md`. Plans are deliberately not on `main`.
- ThesisTracker tracks its own units in `PROGRESS_TT.md` in that repository. Cross-repo dependencies
  are named in the Blocks column here.

**Snapshot date:** 2026-08-13. Recompute with the commands in section 4 before trusting it.

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
| `[ ]` | RT-1 skill scaffold and PDF ingest | [#4](../../issues/4) | `feat/uqac-forms-registry` | - | Plan only. **Actionable now.** Scope reduced on 2026-07-29: the registry and drift check moved to TT-8. |
| `[!]` | RT-2 widget dump and diff | [#5](../../issues/5) | `feat/uqac-forms-field-map` | RT-1 | Plan only. Scope reduced: the map and the vocabulary are TT-8 rows. |
| `[!]` | RT-3 fill | [#6](../../issues/6) | `feat/uqac-forms-filler` | RT-2 | Plan only. Scope reduced: no profile, no map, no stale gate. |
| `[!]` | RT-4 sign and chain | [#7](../../issues/7) | `feat/uqac-forms-signer` | RT-3 | Plan only. Must preserve every previous signature. |
| `[!]` | RT-5 stateless service | [#8](../../issues/8) | `feat/uqac-forms-service` | RT-4 | Plan only. **Blocks ThesisTracker TT-3 and TT-5.** |
| `[!]` | RT-6 publications endpoint | [#9](../../issues/9) | `feat/publications-endpoint` | RT-5 | Plan only. **Blocks ThesisTracker TT-6.** |
| `[!]` | RT-7 parse cache and corpus index | [#10](../../issues/10) | `feat/corpus-index` | RT-5 | Plan only. On no critical path, can land last. Recommended against, then approved: the four binding mitigations are in the plan and must not be dropped. |

Counts: 7 units. DONE 0, REVIEW 0, IN PROGRESS 0, BLOCKED 6, TODO 1, DEFERRED 0.

Issues in this repository that are NOT part of this programme and are tracked separately:
[#11](../../issues/11) `download_pdf.py` background download with Cloudflare, and
[#12](../../issues/12) local writer and coder day/night profile.

---

## 3. Actionable now

1. **RT-1.** No dependencies. It is the head of the chain RT-1 to RT-5 that ends in the stateless
   service, and until RT-5 merges the ThesisTracker units TT-3 and TT-5 cannot start.
2. In ThesisTracker, open and merge the pull request for TT-0 (see `PROGRESS_TT.md` there). That is
   the other half of the critical path and it is already implemented.

The two chains are independent until RT-5, so RT-1 to RT-5 and TT-0 to TT-9 can proceed in parallel.

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
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
pip-audit -r .claude/skills/uqac-forms/requirements.txt --strict
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
python .claude/skills/uqac-forms/scripts/form_registry.py check --all
pyhanko sign validate out/<signed>.pdf
```

---

## 6. Open items that block completion, not implementation

| Item | Owner | Needed by |
|---|---|---|
| Do the Décanat des études and the Service des ressources financières accept a PAdES signature? The signer is pluggable with a self-signed development default, so implementation proceeds; the production certificate decision (UQAC PKI, or Notarius / ConsignO) waits on this. | Prof. Otis to ask both offices | RT-4, TT-5 |
| `pypdf` and `pyhanko` are not installed on the workstation. RT-1 installs them pinned (`pypdf==6.14.2`, `pyhanko==0.36.2`) and runs `pip-audit`. | RT-1 | RT-1 |
