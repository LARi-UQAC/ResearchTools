"""
vault-access-guard.py - PreToolUse guard keeping BOTH memories behind local-writer.

Two memories, one guard, one exempt agent. The Obsidian vault holds what was LEARNED; the
graphify graph under graphify-out/ holds what this repository's code IS. `.claude/CLAUDE.md`
routes both through local-writer and says outright that consulting or refreshing the graph by
hand is the same breach as reading the vault by hand. Until 2026-08-30 only the vault half was
enforced, and the graph half was prose: it was bypassed in three separate sessions, the last of
which ran a read-only audit script twice to learn the graph's state and only noticed afterwards.

The graph arm therefore guards three things, not one. The graphify-out/ path, like the vault.
The graphify CLI itself, matched at COMMAND POSITION so that grepping for the word, or reading
the vendored .claude/skills/graphify/SKILL.md, stays possible. And the two read-only audit
scripts BY NAME - check-graph-health.ps1 and verify-graph-health.ps1 - because they read
graph.json on the caller's behalf and their command line never contains the graph's path at
all. A guard matching only the path would have caught none of the three bypasses; that is the
2026-08-27 vault lesson repeating one level up, where the wrapper rather than the command hides
the access.

The script names are matched ONLY inside an executed command, never against a path argument, so
editing or reading the audit scripts themselves is untouched. Only RUNNING them is a graph
consultation.

Fires before Bash, Read, Grep, Glob, Edit, Write, and NotebookEdit. Blocks (exit 2) any tool
call whose target path lies inside the vault, unless the call comes from the one agent allowed
to touch it. The rule it enforces is stated in the global CLAUDE.md: vault access, read as well
as write, goes through local-writer, and the prohibition attaches to the PATH TOUCHED rather
than to the command used. An earlier wording banned a list of obsidian CLI commands, which left
cat, ls, grep and a Python script pointed at the vault outside its scope. That gap was walked
through on 2026-08-27, which is why this guard exists.

The subagent is identified by the `agent_type` field, present in the hook payload only when the
call fires inside a subagent. Absent field means the main session, which is never exempt.

Known and accepted false positive: a Bash command that merely CONTAINS a vault path, such as a
heredoc writing documentation about the vault, is refused, because a shell command carries its
content inside the command string and the two cannot be told apart. File content handed to Write,
Edit or NotebookEdit is not scanned at all, so the workaround is to use those tools rather than a
shell heredoc when writing about the vault. That asymmetry is deliberate: documenting the vault
path must stay possible, and shelling out is the case where the guard cannot afford to guess.
"""

import json
import os
import re
import sys

DEFAULT_VAULT = "C:/Martin Otis/Vault"
SOLE_VAULT_AGENT = "local-writer"
SOLE_MEMORY_AGENT = SOLE_VAULT_AGENT  # the same agent keeps both memories

# The graph's own storage. Deliberately NOT the bare word "graphify": the skill is vendored at
# .claude/skills/graphify/, and reading its SKILL.md is not consulting the graph.
GRAPH_PATH_NEEDLES = ("graphify-out",)

# Read graph.json on the caller's behalf, and their command line never names the graph's path.
# Matched in a COMMAND ONLY - see the module docstring.
GRAPH_SCRIPT_NEEDLES = ("check-graph-health.ps1", "verify-graph-health.ps1")

# The CLI at command position: start of line, or after a pipe, semicolon, &&, backtick or $(.
# `grep graphify ...` and `rtk grep graphify` are therefore NOT matched, which is the point.
GRAPH_CLI_PATTERN = re.compile(r"(?:^|[|;&`]|\$\()\s*(?:[\w./\\-]*[/\\])?graphify(?:\.exe|\.cmd|\.bat)?\b")
GUARDED_TOOLS = ("Bash", "PowerShell", "Read", "Grep", "Glob", "Edit", "Write",
                 "NotebookEdit", "MultiEdit")
PATH_KEYS = ("file_path", "path", "notebook_path")
BACKSLASH = chr(92)

MESSAGE = (
    "[VAULT GUARD] Direct access to the Obsidian vault is refused.\n"
    "Matched vault path: {hit}\n"
    "Tool: {tool}\n\n"
    "All vault access, reading included, goes through the local-writer agent:\n"
    "  Agent tool, subagent_type: local-writer, with the search terms and the question.\n\n"
    "This applies to the filesystem too. A cat, ls, grep, Read or Python script pointed at the\n"
    "vault is a direct access, exactly like an obsidian read. See the global CLAUDE.md, section\n"
    '"Lecture du coffre".'
)


GRAPH_MESSAGE = (
    "[GRAPH GUARD] Direct access to the graphify knowledge graph is refused.\n"
    "Matched: {hit}\n"
    "Tool: {tool}\n\n"
    "The graph is the second memory, and it is reached the same way as the vault:\n"
    "  Agent tool, subagent_type: local-writer, with the question you want answered.\n\n"
    "This covers running scripts/audit/check-graph-health.ps1 and\n"
    "scripts/test/verify-graph-health.ps1 as well: they read graph.json on your behalf, so\n"
    "running one to learn the graph's state is a consultation, not an audit of your own work.\n"
    "Editing or reading those scripts is untouched - only running them is guarded.\n"
    'See .claude/CLAUDE.md, the graphify row of the routing table.'
)


def _norm(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Normalize a path or a shell command for case- and separator-insensitive
        comparison against the vault root.

    Inputs:
        text (str): raw path or command line

    Outputs:
        result (str): lowercased text with every backslash turned into a slash
    --------------------------------------------------------------------------
    """
    return text.replace(BACKSLASH, "/").lower()


def vault_needles() -> set:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build every textual form the vault root can take in a tool argument:
        the Windows form, the drive-relative form, the Git Bash form, and the
        environment variable standing in for it.

    Inputs:
        none (reads OBSIDIAN_VAULT from the environment)

    Outputs:
        result (set): normalized substrings, any of which marks a vault touch
    --------------------------------------------------------------------------
    """
    root = os.environ.get("OBSIDIAN_VAULT") or DEFAULT_VAULT
    normalized = _norm(root).rstrip("/")
    needles = set()
    if normalized:
        needles.add(normalized)
        if len(normalized) > 2 and normalized[1] == ":":
            tail = normalized[2:]
            needles.add(tail)
            needles.add("/" + normalized[0] + tail)
    needles.add("$obsidian_vault")
    needles.add("${obsidian_vault}")
    needles.add("%obsidian_vault%")
    return {n for n in needles if n}


def candidate_targets(tool_name: str, tool_input: dict) -> list:
    """
    --------------------------------------------------------------------------
    Purpose:
        Collect the strings of a tool call that can designate a location. File
        CONTENT is deliberately excluded, so that writing the vault path into a
        documentation file is not mistaken for touching the vault.

    Inputs:
        tool_name (str): the tool about to run
        tool_input (dict): its arguments

    Outputs:
        result (list): strings to test against the vault needles
    --------------------------------------------------------------------------
    """
    targets = []
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str):
            targets.append(value)
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command")
        if isinstance(command, str):
            targets.append(command)
    return targets


def find_violation(tool_name: str, tool_input: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a tool call reaches into the vault.

    Inputs:
        tool_name (str): the tool about to run
        tool_input (dict): its arguments

    Outputs:
        result (str): the matched needle, or an empty string when the call is clean
    --------------------------------------------------------------------------
    """
    needles = vault_needles()
    for target in candidate_targets(tool_name, tool_input):
        normalized = _norm(target)
        for needle in needles:
            if needle in normalized:
                return needle
    return ""


def find_graph_violation(tool_name: str, tool_input: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a tool call reaches into the graphify knowledge graph,
        by its storage path, by the CLI, or through one of the two audit
        scripts that read it on the caller's behalf.

    Inputs:
        tool_name (str): the tool about to run
        tool_input (dict): its arguments

    Outputs:
        result (str): what matched, or an empty string when the call is clean
    --------------------------------------------------------------------------
    """
    targets = candidate_targets(tool_name, tool_input)

    # The storage path counts wherever it appears, exactly like the vault root.
    for target in targets:
        normalized = _norm(target)
        for needle in GRAPH_PATH_NEEDLES:
            if needle in normalized:
                return needle

    # The CLI and the audit scripts count only in something being EXECUTED. A path argument
    # naming one of those scripts is an edit or a read of the script, not a graph consultation.
    if tool_name not in ("Bash", "PowerShell"):
        return ""

    command = tool_input.get("command")
    if not isinstance(command, str):
        return ""
    normalized = _norm(command)

    for needle in GRAPH_SCRIPT_NEEDLES:
        if needle in normalized:
            return needle

    if GRAPH_CLI_PATTERN.search(normalized):
        return "graphify (CLI)"

    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    tool_name = payload.get("tool_name") or ""
    if tool_name not in GUARDED_TOOLS:
        return 0

    if (payload.get("agent_type") or "") == SOLE_MEMORY_AGENT:
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    hit = find_violation(tool_name, tool_input)
    if hit:
        sys.stderr.write(MESSAGE.format(hit=hit, tool=tool_name) + "\n")
        return 2

    graph_hit = find_graph_violation(tool_name, tool_input)
    if graph_hit:
        sys.stderr.write(GRAPH_MESSAGE.format(hit=graph_hit, tool=tool_name) + "\n")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
