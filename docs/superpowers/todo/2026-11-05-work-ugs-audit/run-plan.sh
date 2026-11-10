#!/usr/bin/env bash
# Operational helper of the work-ugs-audit effort (Issue #104). It carries out the mechanical steps of the
# local-coder procedure for ONE plan, so each step is the same command every time:
#   run-plan.sh mount   <id>   mount a kit project for plan <id> (spec, plan as plan1, ledger, inputs, venv)
#   run-plan.sh start   <id>   launch the repository copy of aider-plan.ps1 on it, detached, log with a marker
#   run-plan.sh harvest <id>   bring back the files the plan names, run their test in the repository, tick, commit
# It writes no source file and calls no model itself: the kit's writer and reviewer models do.
set -euo pipefail

MODE="$1"; ID="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
W="$(cd "$HERE/../../../.." && pwd)"                    # this worktree
MAIN="$(cd "$W/../.." && pwd)"                          # main clone: holds the shared interpreter
S="$W/.claude/skills/aider-setup"
PYI="$MAIN/.venv-skills/Scripts/python.exe"
LIVE="$HOME/.claude/aider-live"
HOME_CFG="$LIVE/home"                                   # configuration rendered from the repository
P="$LIVE/work/u$ID${SUFFIX:-}"
PL="$P/docs/superpowers/plans"
PLANS_HOME="${PLANS_HOME:-$HERE}"                      # folder holding spec.md and plan<ID>.md (default: this folder)
PLAN="$PLANS_HOME/plan$ID.md"
LOG="$LIVE/u${ID}${SUFFIX:-}_run.log"

# Paths named by the plan: Files block (create or modify) and Reads block (inputs).
plan_paths_raw() {  # $1 = files | reads | test
  "$PYI" - "$PLAN" "$1" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
kind = sys.argv[2]
m = re.search(r"\*\*Files:\*\*\n((?:- .*\n?)+)", text)
files = re.findall(r"`([^`]+\.\w+)`", m.group(1)) if m else []
r = re.search(r"\*\*Reads, do not modify:\*\*(.*?)\n\n", text, re.S)
reads = re.findall(r"`([\w./-]+/[\w./-]+\.\w+)`", r.group(1)) if r else []
if kind == "files":
    print("\n".join(files))
elif kind == "reads":
    print("\n".join(reads))
else:
    print("\n".join(f for f in files if "/Test/test_" in f or f.endswith("_test.go")))
EOF
}

plan_paths() { plan_paths_raw "$1" | tr -d '\015'; }

# A plan whose files are Go files is tested with `go test` in its module folder; any other plan runs its
# Python test file. The Go toolchain is called by full path because it is not on PATH.
GO_EXE="$HOME/.local/go-sdk/go/bin/go.exe"
is_go() { plan_paths files | grep -q '\.go$'; }
go_dir() { plan_paths files | grep -E '(go\.mod|\.go)$' | head -1 | xargs dirname; }
test_command() {
  if is_go; then printf '%s' "$(cygpath -w "$GO_EXE") test -C $(go_dir) ./..."
  else printf '%s' ".\\.venv\\Scripts\\python.exe $(plan_paths test | head -1)"; fi
}

# The front matter of a plan (executor, tier, bounds) serves the plan contract of this repository. The writer
# model must not read it, so the copy mounted for the kit has none.
strip_header() { "$PYI" -c 'import sys; t=sys.stdin.read().replace("\r\n","\n"); print(t.split("\n---\n",1)[1].lstrip("\n") if t.startswith("---\n") else t, end="")'; }

case "$MODE" in
mount-all)
  # One kit project holding every plan<N>.md of PLANS_HOME, for aider-night.ps1. ID is the project name.
  [ -e "$P" ] && { echo "REFUSED: $P exists"; exit 1; }
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$S/new-project.ps1")" \
    -Name "u$ID${SUFFIX:-}" -Root "$(cygpath -w "$LIVE/work")" -Python "$(cygpath -w "$PYI")" >/dev/null 2>&1
  cp "$PLANS_HOME/spec.md" "$PL/spec.md"; cp "$PLANS_HOME/progress.md" "$PL/progress.md"; : > "$PL/audit.md"
  for pf in "$PLANS_HOME"/plan*.md; do
    strip_header < "$pf" > "$PL/$(basename "$pf")"
    PLAN="$pf"
    plan_paths reads | while read -r f; do
      if [ -n "$f" ] && [ -f "$W/$f" ]; then mkdir -p "$P/$(dirname "$f")"; cp "$W/$f" "$P/$f"; fi
    done
  done
  rmdir "$P/Test" 2>/dev/null || true
  ( cd "$P" && git add -A >/dev/null 2>&1 && git -c core.safecrlf=false commit -q -m "mount: $ID" >/dev/null 2>&1 )
  echo "mounted $P ($(ls "$PL"/plan*.md | wc -l) plans)"
  ;;
mount)
  [ -e "$P" ] && { echo "REFUSED: $P exists"; exit 1; }
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$S/new-project.ps1")" \
    -Name "u$ID${SUFFIX:-}" -Root "$(cygpath -w "$LIVE/work")" -Python "$(cygpath -w "$PYI")" >/dev/null 2>&1
  cp "$PLANS_HOME/spec.md" "$PL/spec.md"
  strip_header < "$PLAN" > "$PL/plan1.md"
  { printf '# Progress\n\n**Goal.** The ledger of plan %s.\n\n**Contents.** Task lines only.\n\n## plan1.md\n' "$ID"
    plan_paths files | while read -r f; do [ -n "$f" ] && printf -- '- [ ] create %s as plan1.md describes\n' "$f"; done
  } > "$PL/progress.md"
  : > "$PL/audit.md"
  # Inputs that already exist, with their repository-relative paths.
  { plan_paths reads; plan_paths files; } | while read -r f; do
    if [ -n "$f" ] && [ -f "$W/$f" ]; then mkdir -p "$P/$(dirname "$f")"; cp "$W/$f" "$P/$f"; fi
  done
  # Sibling modules imported by the copied files, with their tests: without them the writer invents its own.
  for _pass in 1 2; do
    find "$P" -name '*.py' -not -path '*/.venv/*' | while read -r src; do
      dir="$(dirname "$src")"; rel="${dir#$P/}"
      grep -h -E '^(from|import) [a-z_][a-z0-9_]*' "$src" | sed -E 's/^(from|import) ([a-z_][a-z0-9_]*).*/\2/' | sort -u | while read -r mod; do
        for cand in "$rel/$mod.py" "$rel/Test/test_$mod.py"; do
          if [ -f "$W/$cand" ] && [ ! -f "$P/$cand" ]; then mkdir -p "$P/$(dirname "$cand")"; cp "$W/$cand" "$P/$cand"; echo "copied imported sibling $cand"; fi
        done
      done
    done
  done
  # PyMuPDF for the plans that use it, from the pinned and audited file of the repository.
  if grep -q -i -E "fitz|PyMuPDF" "$PLAN"; then
    "$P/.venv/Scripts/python.exe" -m ensurepip >/dev/null 2>&1 || true   # the kit's venv has no pip
    "$P/.venv/Scripts/python.exe" -m pip install -q -r "$W/.claude/skills/figure-review/scripts/requirements.txt" >/dev/null 2>&1 \
      && echo "PyMuPDF installed in the project environment" || echo "WARNING: PyMuPDF install failed"
  fi
  # pymupdf4llm for the plans that read PDF text: the pinned, audited version of extract-statistic.
  if grep -q -i "pymupdf4llm" "$PLAN"; then
    pin="$(grep -E '^pymupdf4llm==' "$W/.claude/skills/extract-statistic/scripts/requirements.txt" | head -1)"
    "$P/.venv/Scripts/python.exe" -m pip install -q "$pin" >/dev/null 2>&1       && echo "$pin installed in the project environment" || echo "WARNING: $pin install failed"
  fi
  rmdir "$P/Test" 2>/dev/null || true
  ( cd "$P" && git add -A >/dev/null 2>&1 && git -c core.safecrlf=false commit -q -m "mount: plan $ID" >/dev/null 2>&1 )
  echo "mounted $P"; echo "test: $(plan_paths test | head -1)"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$S/scripts/aider-plan.ps1")" \
    -Path "$(cygpath -w "$P")" -Config "$(cygpath -w "$HOME_CFG/.aider.conf.yml")" \
    -BudgetFile "$(cygpath -w "$HOME_CFG/.config/aider/context-budget.json")" \
    -TestCommand "$(test_command)" -DryRun 2>&1 \
    | grep -a -E "editable|REFUSED|OVER|audit with" | cut -c1-170
  ;;
start)
  for m in $(powershell.exe -NoProfile -Command "ollama ps" | tail -n +2 | awk '{print $1}'); do
    powershell.exe -NoProfile -Command "ollama stop $m" >/dev/null 2>&1 || true
  done
  : > "$LOG"
  TC="$(test_command)"
  nohup bash -c "powershell.exe -NoProfile -ExecutionPolicy Bypass -File '$(cygpath -w "$S/scripts/aider-plan.ps1")' \
    -Path '$(cygpath -w "$P")' -Config '$(cygpath -w "$HOME_CFG/.aider.conf.yml")' \
    -BudgetFile '$(cygpath -w "$HOME_CFG/.config/aider/context-budget.json")' -TestCommand '$TC' >> '$LOG' 2>&1; \
    echo KIT-FINISHED rc=\$? >> '$LOG'" >/dev/null 2>&1 &
  sleep 1; echo "started plan $ID at $(date +%H:%M), log $LOG"
  ;;
harvest)
  # The plan must be archived and carry no blocked mark; otherwise nothing comes back.
  # ACCEPT=1 brings the files back although the kit stopped the plan at its audit round limit; the cloud has
  # then checked them against the plan (signatures, named tests, rules) and records the residuals in the ledger.
  if [ "${ACCEPT:-0}" != "1" ]; then
    [ -f "$PL/todo/plan1.md" ] || { echo "NOT DONE: plan1.md is not archived in the project"; exit 2; }
    if grep -q -E '^\s*-\s*\[!\]' "$PL/progress.md" "$PL/todo/progress.md" 2>/dev/null; then echo "BLOCKED mark in the ledger"; exit 2; fi
  fi
  # Only the paths the plan names come back.
  plan_paths files | while read -r f; do
    [ -z "$f" ] && continue
    [ -f "$P/$f" ] || { echo "MISSING in the project: $f"; exit 2; }
    mkdir -p "$W/$(dirname "$f")"; cp "$P/$f" "$W/$f"; echo "harvested $f"
  done
  T="$(plan_paths test | head -1)"
  echo "--- repository test: $T"
  if is_go; then ( cd "$W" && "$GO_EXE" test -C "$(go_dir)" ./... 2>&1 | tail -6 )
  else ( cd "$W" && "$PYI" "$T" 2>&1 | tail -4 ); fi
  ;;
*) echo "usage: run-plan.sh mount|start|harvest <id>"; exit 64 ;;
esac
