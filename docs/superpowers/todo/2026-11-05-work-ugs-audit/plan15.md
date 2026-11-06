---
executor: cloud
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 15 - The audit sandbox: the wrapper audits like aider-setup's reviewer

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, in the session. Runs after
> plan 13 and before plan 14 (plan 14's agent text names these subcommands). Last cloud-written code.

**Goal:** the local-coder wrapper, as auditor, can write only `audit.md` and the `audit:` lines of
`progress.md`, exactly as aider-setup's reviewer can: it works on copies in a sandbox, and the driver
restores any project file touched during the audit, judged by effect (R9).

**Source (owner 2026-11-05: "work like aider-setup"):** `aider-plan.ps1` lines 776-812 (sandbox holding
copies of `audit.md` and `progress.md`, copied back after the guard) and 815-900
(`Get-ProjectFingerprint`, `Restore-ProjectIfTouched`).

**One deliberate difference:** aider runs `git reset --hard` when the reviewer moved HEAD. The driver
reports it and stops; a destructive git command is the owner's.

## Global Constraints

Tests first, failure paths (R20), fictitious git repository in TEMP (R21, R34). R27 headers. R24 every
restored or deleted path resolved inside the root. Exclusions are data in `local-coder-driver.json`
(R6). Git is used to read status and restore a committed file, never to commit, reset or push.

## Review Focus

- A source file the auditor changed and not restored, or a file outside the root deleted.
- An uncommitted file restored from git instead of its backup (the owner's work lost).
- The audit report copied back before the restore ran.

---

### Task 1: `--audit-begin` and `--audit-end`

**Files:**
- Modify: `.claude/skills/loop-engineer/scripts/local_coder_driver.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_local_coder_driver.py`
- Modify: `.claude/skills/loop-engineer/local-coder-driver.json`
- Modify: `.claude/rules/testing.md`

**Interfaces:**
- `local-coder-driver.json` gains `audit_exclude` (`.git/`, `__pycache__/`, `.venv*/`, `.aider.*`), with
  provenance `aider-plan.ps1` lines 837-840.
- `audit_begin(progress: Path, root: Path, sandbox: Path, config: dict) -> dict`: copy `progress.md` and
  `audit.md` (created empty when absent) of the effort into `sandbox`; hash every file under root not
  excluded (the effort's `progress.md` and `audit.md` excluded too); back up into `sandbox/backup/` every
  file `git status --porcelain` lists; write `sandbox/state.json` (HEAD, hashes, backups).
- `audit_end(progress: Path, root: Path, sandbox: Path, config: dict) -> dict`: rehash; a file new since
  begin is deleted; a changed file is restored from its backup when it had one, else with
  `git checkout -- <file>`; a moved HEAD is reported (`head_moved`) and nothing is reset; only then
  are the sandbox `audit.md` and `progress.md` copied back. Returns `touched` (paths) and `head_moved`.
- CLI: `--audit-begin --sandbox DIR` and `--audit-end --sandbox DIR`, with `--progress` and `--root`;
  `--json`. Exit 0 nothing touched, 1 something touched and restored or HEAD moved, 2 refusal (no
  `state.json`, sandbox inside the root).

- [ ] Step 1: failing tests: an untouched audit copies `audit.md` and the `audit:` line back (exit 0);
  a committed file changed during the audit is restored from git; an uncommitted file changed is
  restored from its backup with the owner's edit intact; a new file is deleted; a moved HEAD is reported
  and not reset; an excluded folder is ignored; the report is copied back after the restore; `--audit-end`
  with no `state.json` is a refusal. Step 2: FAIL. Step 3: implement. Step 4: OK, with the rest of the
  driver suite.
- [ ] Step 5: testing.md line (R23); commit `feat(loop-engineer): audit sandbox like aider-setup (#104)`.
