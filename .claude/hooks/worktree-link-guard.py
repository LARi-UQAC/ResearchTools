"""
worktree-link-guard.py - PreToolUse gate on `git worktree remove` (Bash and PowerShell).

Enforces R37 of .claude/rules/workflows.md: a worktree holding a junction or a symbolic link
must not be removed until the link itself has been removed, because the removal follows the
link and deletes the folder it points at.

MEASURED 2026-10-16 on a throwaway copy under TEMP (git 2.53.0, Windows, fictitious folders).
With the link NOT ignored by git, `git worktree remove` refused and `--force` deleted the
target's contents. With the link IGNORED by git, which is the real case here since
.gitignore carries `.venv*/`, the plain `git worktree remove` with no `--force` deleted the
target's contents and left the target folder empty. That is how the main clone's
.venv-skills was emptied on 2026-10-06, so the gate fires with or without `--force`.

SCOPE, stated so nobody reads it as wider than it is. It judges ONE command: `git worktree
remove`, reached through the Bash or PowerShell tool. It does not judge `rm -rf`,
`Remove-Item -Recurse` or `rmdir /s`, which were left out because a refusal there would fire
on ordinary cleanups and no damage through them has been demonstrated. It cannot judge a path
it cannot resolve: a variable, a command substitution or a `%VAR%` in the path passes, and so
does a command assembled in a script file the tool call merely runs.

EXIT CODES (R12):
    0  the call is clean, OR the gate is disabled, OR the call is not ours to judge.
    2  refusal by design; stderr carries the reason and the command that removes the link.
  Every failure path returns 0 except one deliberate refusal: when the scan hits
  max_entries before it finished, the worktree could hide a link it never reached, so the
  call is refused and the message says how to check by hand. That is not a missing
  dependency (R11), it is an answer the hook cannot give. Raise max_entries to widen it.
  A missing, unreadable or unparsable worktree-link-guard.json disables the gate in silence:
  a hook whose own dependency is absent never refuses a tool (R11, the 2026-08-27 incident).
"""

import json
import os
import re
import sys

CONFIG_NAME = "worktree-link-guard.json"
TOOL_NAMES = ("Bash", "PowerShell")
# Win32 FILE_ATTRIBUTE_REPARSE_POINT: set on junctions and on every kind of symbolic link.
# It is an operating-system constant, not configuration (R0 exempts domain constants).
REPARSE_POINT = 0x400
SEPARATORS = ";|&\n\r"
# git options that take their value as the NEXT token.
VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")
UNRESOLVABLE = re.compile(r"[$%`]")
GIT_BASH_DRIVE = re.compile(r"^/([A-Za-z])/")

HEADER = (
    "[WORKTREE LINK GUARD] `git worktree remove` was refused: the worktree below holds a\n"
    "junction or symbolic link, and the removal follows it and deletes the folder it points at.\n"
    "That is how the main clone's .venv-skills was emptied on 2026-10-06 (R37).\n"
)

FOOTER = (
    "\nRemove each LINK first. These commands delete the link and never its target:\n"
    "{commands}\n"
    "Then run `git worktree remove` again. Nothing else needs to change.\n"
    "\nA worktree never needs a link to the main clone's environment: the launchers find it by\n"
    "absolute path (scripts/lib/rt-venv.ps1). Rule: .claude/rules/workflows.md, R37.\n"
    "Settings: .claude/hooks/" + CONFIG_NAME + "\n"
)

INCOMPLETE = (
    "[WORKTREE LINK GUARD] `git worktree remove` was refused: the scan of\n"
    "  {path}\n"
    "stopped after {limit} entries without finishing, so a link could be hiding in the part it\n"
    "did not reach. Check by hand with\n"
    "  Get-ChildItem -LiteralPath '{path}' -Recurse -Force -Attributes ReparsePoint\n"
    "remove any link it lists with `cmd /c rmdir`, or raise max_entries in\n"
    ".claude/hooks/" + CONFIG_NAME + ".\n"
)


def load_config(hook_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the gate's settings from the JSON beside the hook.

    Inputs:
        hook_dir (str): folder that holds the hook and its config

    Outputs:
        config (dict | None): the settings, or None when the gate is disabled,
        the file is missing or unreadable, or max_entries is not a positive
        integer (R11: a broken config disables the gate in silence)
    --------------------------------------------------------------------------
    """
    try:
        with open(os.path.join(hook_dir, CONFIG_NAME), encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return None
    limit = config.get("max_entries")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return None
    return config


def tokenize(command):
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a shell command line into segments of tokens. Quotes group a
        token, backslash is a literal character (Windows paths), and an
        unquoted ; | & or newline ends the segment.

    Inputs:
        command (str): the Bash or PowerShell command text

    Outputs:
        segments (list[list[str]]): one token list per command in the line
    --------------------------------------------------------------------------
    """
    segments, tokens, current = [], [], []
    quote = None
    has_token = False

    def end_token():
        nonlocal current, has_token
        if has_token:
            tokens.append("".join(current))
        current, has_token = [], False

    for char in command:
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
            has_token = True
        elif char in SEPARATORS:
            end_token()
            if tokens:
                segments.append(tokens)
            tokens = []
        elif char.isspace():
            end_token()
        else:
            current.append(char)
            has_token = True
    end_token()
    if tokens:
        segments.append(tokens)
    return segments


def _clean(path):
    """Normalise a Git Bash drive spelling (/c/x) to a Windows one on Windows."""
    if os.name == "nt":
        found = GIT_BASH_DRIVE.match(path)
        if found:
            return found.group(1).upper() + ":" + path[2:]
    return path


def find_removals(command, base_dir):
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every `git worktree remove <path>` in a command line and resolve
        its path.

    Details:
        Global git options before the verb are skipped, with -C accumulated as
        git does. A path holding $, % or a backtick cannot be resolved here and
        is dropped, which is the stated limit of the gate.

    Inputs:
        command (str): the command text
        base_dir (str): working directory the command runs in

    Outputs:
        paths (list[str]): absolute worktree paths named by the command
    --------------------------------------------------------------------------
    """
    found = []
    for tokens in tokenize(command):
        for index, token in enumerate(tokens):
            name = os.path.basename(_clean(token).replace("\\", "/")).lower()
            if name not in ("git", "git.exe"):
                continue
            cursor, workdir = index + 1, base_dir
            while cursor < len(tokens) and tokens[cursor].startswith("-"):
                option = tokens[cursor]
                takes_value = option in VALUE_OPTIONS
                if option == "-C" and cursor + 1 < len(tokens):
                    workdir = os.path.join(workdir, _clean(tokens[cursor + 1]))
                cursor += 2 if takes_value else 1
            if tokens[cursor:cursor + 2] != ["worktree", "remove"]:
                continue
            rest = tokens[cursor + 2:]
            positional = []
            options_over = False
            for item in rest:
                if not options_over and item == "--":
                    options_over = True
                elif options_over or not item.startswith("-"):
                    positional.append(item)
            if not positional or UNRESOLVABLE.search(positional[-1]):
                continue
            found.append(os.path.normpath(os.path.join(workdir, _clean(positional[-1]))))
    return found


def _is_link(entry):
    """True for a symbolic link or a Windows junction, without following it."""
    if entry.is_symlink():
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & REPARSE_POINT)


def scan_for_links(root, max_entries):
    """
    --------------------------------------------------------------------------
    Purpose:
        List the junctions and symbolic links under a folder, never following
        them.

    Inputs:
        root (str): the worktree folder
        max_entries (int): entries to examine before giving up (R10: bounded)

    Outputs:
        result (tuple): (links list[tuple[str, str]] of (path, target or ""),
        complete bool - False when max_entries was reached first)
    --------------------------------------------------------------------------
    """
    links, pending, seen = [], [root], 0
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    seen += 1
                    if seen > max_entries:
                        return links, False
                    if _is_link(entry):
                        try:
                            target = os.readlink(entry.path)
                        except OSError:
                            target = ""
                        links.append((entry.path, target))
                    elif entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
        except OSError:
            continue
    return links, True


def _remedy(path):
    """The command that deletes a link and never its target."""
    if os.path.isdir(path):
        return '  cmd /c rmdir "%s"' % path
    return '  cmd /c del "%s"' % path


def main():
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the PreToolUse payload from stdin and refuse `git worktree remove`
        on a worktree that holds a link.

    Inputs:
        None (stdin: the hook payload as JSON)

    Outputs:
        code (int): 0 to allow, 2 to refuse (see the module header, R12)
    --------------------------------------------------------------------------
    """
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict) or (payload.get("tool_name") or "") not in TOOL_NAMES:
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "worktree" not in command:
        return 0

    config = load_config(os.path.dirname(os.path.abspath(__file__)))
    if config is None:
        return 0

    base_dir = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    for path in find_removals(command, base_dir):
        if not os.path.isdir(path):
            continue
        links, complete = scan_for_links(path, config["max_entries"])
        if links:
            lines = ["", "worktree: " + path]
            lines += ["  link: %s -> %s" % (link, target or "(target unreadable)")
                      for link, target in links]
            sys.stderr.write(HEADER + "\n".join(lines) + "\n"
                             + FOOTER.format(commands="\n".join(_remedy(l) for l, _ in links)))
            return 2
        if not complete:
            sys.stderr.write(INCOMPLETE.format(path=path, limit=config["max_entries"]))
            return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # R11: never refuse a tool because this hook itself broke.
        sys.exit(0)
