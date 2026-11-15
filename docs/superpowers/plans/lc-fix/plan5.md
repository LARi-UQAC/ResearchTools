---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 5 - The repository sync also keeps the installed aider kit scripts current

> **For agentic workers:** run by the local coder model through the aider kit (rule R39). Return every
> file you change in full. The check script is a PowerShell script that exits non-zero on a failure.

**Goal:** the existing sync of the repository (run at every session start) copies the aider-setup scripts
into the installed kit folder, following the section "Sync of the kit scripts" of the spec.

**Spec:** the section "Sync of the kit scripts" of the spec.

## Global Constraints

Reuse what the sync engine already has (its copy-with-undo function, its proof test and its dry-run flag)
and write no second copy of that logic. No path is written in the code: the destination is derived from the
home that owns the `.claude` folder being synced, so a test can use a temporary home. A step that cannot do
its job stays silent and exits 0 (R11). Every function carries the Purpose, Inputs and Outputs header.

## Review Focus

- A repository file holding the home placeholder is installed with the placeholder replaced, and a second
  run changes nothing.
- A script with a syntax error is held, not written.
- The folder of the owner's configuration is untouched, byte for byte.
- With the dry-run flag nothing is written and no undo copy is made.

---

### Task 1: the sync step and its checks

**Files:**
- Modify: `scripts/lib/rt-sync.ps1`
- Modify: `scripts/test/verify-sync-writes.ps1`

**Interfaces:**
- `Sync-RtKitScripts([string]$repoRoot, [string]$homeBin)` returns nothing; it writes through the existing
  report function and is called by `Invoke-RtSync` after the skills step, with the install folder derived
  from the parent of the synced `.claude` folder.
- A small helper that decides whether one file is proven for installation, by extension, as the spec says.

**Checks to write first, each failing before the code exists** (a throwaway home and repository built in a
temporary folder, fictitious content): a file with the home placeholder is installed substituted and
without a byte order mark; a second run writes nothing; a changed file is replaced and its previous version
is copied to the undo folder; a Python file absent from the green stamp is held; a script with a syntax
error is held; a missing install folder is skipped silently; the dry-run flag writes nothing; the
configuration folder is hashed before and after and is unchanged.

- Test: `scripts/test/verify-sync-writes.ps1`

- [ ] Step 1: add the checks, run the script, the new ones fail.
- [ ] Step 2: add the sync step, run the script, every check passes.
