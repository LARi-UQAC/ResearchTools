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

# The venv paths are resolved from this script's own location, so they are not
# configuration (R1). The Scripts/ spelling is the Windows venv layout, reached
# from Git Bash.
CANDIDATES="$REPO_ROOT/.venv-skills/bin/python
$REPO_ROOT/.venv-skills/Scripts/python.exe
python3
python"

PYTHON=""
for candidate in $CANDIDATES; do
    case "$candidate" in
        */*)
            if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
            ;;
        *)
            if command -v "$candidate" >/dev/null 2>&1; then
                PYTHON="$candidate"
                break
            fi
            ;;
    esac
done

if [ -z "$PYTHON" ]; then
    printf 'rt-dashboard: no Python interpreter found. Tried, in order:\n' >&2
    for candidate in $CANDIDATES; do
        printf '  %s\n' "$candidate" >&2
    done
    printf 'Install Python 3, or create the suite environment with setup.ps1 -InstallPython.\n' >&2
    exit 2
fi

exec "$PYTHON" "$MODULE" --serve "$@"
