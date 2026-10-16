#!/usr/bin/env sh
# rt-dashboard - start the rt-observe loopback dashboard (canonical launcher,
# POSIX). The twin of rt-dashboard.ps1 beside it, and the reason a lab member on
# macOS or Linux needs no PowerShell: zero PowerShell is a supported
# configuration, not a degraded one.
#
# It does ONE thing Python cannot do for itself: find an interpreter. The port
# probe, the refusals and the bind all live in rt_state.py, where the offline
# suite can reach them.
#
# Its own refusal: with no interpreter found, every candidate tried is NAMED and
# the exit code is 2, a refusal by design (R12). It never guesses a path.
#
# Flags are rt_state.py's own: --dry-run, --open, --port N. The PowerShell
# spellings (-DryRun, -Open) belong to rt-dashboard.ps1 and are not translated
# here, because translating them would be logic and this file has none.
set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
MODULE="$SCRIPT_DIR/rt_state.py"

if [ ! -f "$MODULE" ]; then
    printf 'rt-dashboard: rt_state.py is not beside this launcher (%s).\n' \
        "$MODULE" >&2
    exit 2
fi

# The environment is looked for in THIS clone first and then in the MAIN clone
# (git's common directory), so a linked worktree reaches the main environment by
# its absolute path and needs no link. That is the point: a junction into the main
# environment is what let `git worktree remove` delete the real one (2026-10-06).
# The paths come from this script's own location, so they are not configuration
# (R1). The Scripts/ spelling is the Windows venv layout, reached from Git Bash.
#
# PATH is NOT searched unless the FIRST argument is --allow-path-fallback (R8): an
# emptied environment must be a stated refusal and not a quiet move to some other
# python. The flag is consumed here and never reaches rt_state.py.
ALLOW_PATH_FALLBACK=0
if [ "${1:-}" = "--allow-path-fallback" ]; then
    ALLOW_PATH_FALLBACK=1
    shift
fi

MAIN_ROOT="$REPO_ROOT"
if command -v git >/dev/null 2>&1; then
    COMMON=$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || true)
    if [ -n "$COMMON" ]; then
        case "$COMMON" in
            /*|[A-Za-z]:*) ;;
            *) COMMON="$REPO_ROOT/$COMMON" ;;
        esac
        if [ -d "$COMMON" ] && [ "$(basename "$COMMON")" = ".git" ]; then
            MAIN_ROOT=$(cd "$COMMON/.." && pwd)
        fi
    fi
fi

CANDIDATES="$REPO_ROOT/.venv-skills/bin/python
$REPO_ROOT/.venv-skills/Scripts/python.exe"
if [ "$MAIN_ROOT" != "$REPO_ROOT" ]; then
    CANDIDATES="$CANDIDATES
$MAIN_ROOT/.venv-skills/bin/python
$MAIN_ROOT/.venv-skills/Scripts/python.exe"
fi

# Split on newlines only: a clone path such as "My Tools/clone" holds a space.
NL='
'
IFS="$NL"

PYTHON=""
for candidate in $CANDIDATES; do
    if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done

if [ -z "$PYTHON" ] && [ "$ALLOW_PATH_FALLBACK" = "1" ]; then
    IFS=" "
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON="$candidate"
            printf 'rt-dashboard: --allow-path-fallback given, using %s from PATH.\n' \
                "$candidate" >&2
            break
        fi
    done
    IFS="$NL"
fi

if [ -z "$PYTHON" ]; then
    printf 'rt-dashboard: no Python interpreter found. Tried, in order:\n' >&2
    for candidate in $CANDIDATES; do
        printf '  %s\n' "$candidate" >&2
    done
    if [ "$ALLOW_PATH_FALLBACK" = "1" ]; then
        printf '  python3 and python on PATH (none found)\n' >&2
    fi
    printf 'Rebuild the environment with: setup.ps1 -InstallPython (run from %s)\n' \
        "$MAIN_ROOT" >&2
    printf 'Or pass --allow-path-fallback as the FIRST argument to accept PATH knowingly.\n' >&2
    exit 2
fi

unset IFS
exec "$PYTHON" "$MODULE" --serve "$@"
