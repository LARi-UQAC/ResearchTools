#!/usr/bin/env sh
# Start the rt-observe dashboard. Thin wrapper, no logic.
#
# The canonical launcher lives beside its module, in
# .claude/skills/rt-observe/scripts/rt-dashboard.sh (R18). This file exists only
# so the command is reachable from the repository root on macOS and Linux.
#
# Flags are forwarded unchanged: --dry-run, --open, --port N.
set -eu

DIR=$(cd "$(dirname "$0")" && pwd)
CANONICAL="$DIR/.claude/skills/rt-observe/scripts/rt-dashboard.sh"

if [ ! -f "$CANONICAL" ]; then
    printf 'rt-dashboard: the canonical launcher is missing (%s).\n' \
        "$CANONICAL" >&2
    exit 2
fi

exec sh "$CANONICAL" "$@"
