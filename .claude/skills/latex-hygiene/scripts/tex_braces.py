"""
tex_braces - subcommand `braces`: brace-balance and environment-balance check.

Stage: latex-hygiene pipeline, structural sanity check. Curly-brace depth is a
verbatim port of brace_check.py, paths as arguments instead of a chdir.
Environment balance (\\begin{env}/\\end{env}) is a distinct defect class
added alongside it: both answer "is this file balanced", one at the character
level, one at the environment level.
"""

import logging
import re
from typing import Dict, List, Optional

from tex_common import read_text

logger = logging.getLogger(__name__)

_COMMENT = re.compile(r"(?<!\\)%.*$")
_ENV_TOKEN = re.compile(r"\\(begin|end)\{([^}]*)\}")


def _scan_env_balance(text: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Walk \\begin{env}/\\end{env} tokens on a stack and report the first
        mismatch encountered (an \\end with no open \\begin, or an \\end{a}
        closing a \\begin{b}), plus any environment still open at EOF. On a
        name mismatch the stack top is popped anyway so tracking can keep
        going for the rest of the file instead of cascading false positives.

    Inputs:
        text (str): .tex source (one file).

    Outputs:
        result (Dict): {"first_mismatch": Optional[Dict],
            "unclosed_at_eof": List[Dict]}. first_mismatch is one of
            {"type": "unmatched_end", "env": str, "line": int} or
            {"type": "mismatched_end", "expected_env": str,
            "expected_line": int, "found_env": str, "line": int}.
    --------------------------------------------------------------------------
    """
    stack: List[Dict] = []
    first_mismatch: Optional[Dict] = None
    for ln, line in enumerate(text.split("\n"), 1):
        code = _COMMENT.sub("", line)
        for m in _ENV_TOKEN.finditer(code):
            kind, env = m.group(1), m.group(2)
            if kind == "begin":
                stack.append({"env": env, "line": ln})
                continue
            if not stack:
                if first_mismatch is None:
                    first_mismatch = {"type": "unmatched_end", "env": env, "line": ln}
                continue
            top = stack[-1]
            if top["env"] == env:
                stack.pop()
            else:
                if first_mismatch is None:
                    first_mismatch = {
                        "type": "mismatched_end",
                        "expected_env": top["env"], "expected_line": top["line"],
                        "found_env": env, "line": ln,
                    }
                stack.pop()
    unclosed = [{"env": entry["env"], "line": entry["line"]} for entry in stack]
    return {"first_mismatch": first_mismatch, "unclosed_at_eof": unclosed}


def scan_braces(files: List[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Track brace depth line by line (escaped `\\{` `\\}` do not count) and
        report the final depth per file plus the first line where depth goes
        negative, alongside the environment-balance result from
        _scan_env_balance for the same file.

    Inputs:
        files (List[str]): .tex files to scan.

    Outputs:
        result (Dict): {"files": {path: {"final_depth": int,
            "first_negative_line": Optional[int], "environments": Dict}},
            "balanced": bool, "env_balanced": bool}. "balanced" covers curly
            braces only (unchanged meaning); "env_balanced" is True only if
            every file has no environment mismatch and nothing left open at
            EOF.
    --------------------------------------------------------------------------
    """
    per_file = {}
    balanced = True
    env_balanced = True
    for path in files:
        depth = 0
        minline: Optional[int] = None
        text = read_text(path)
        for ln, line in enumerate(text.split("\n"), 1):
            code = _COMMENT.sub("", line)
            code = code.replace(r"\{", "").replace(r"\}", "")
            for ch in code:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0 and minline is None:
                        minline = ln
        env_result = _scan_env_balance(text)
        per_file[path] = {
            "final_depth": depth,
            "first_negative_line": minline,
            "environments": env_result,
        }
        if depth != 0 or minline is not None:
            balanced = False
        if env_result["first_mismatch"] is not None or env_result["unclosed_at_eof"]:
            env_balanced = False
        logger.info(
            "[HYGIENE] braces: %s -> final_depth=%d env_mismatch=%s env_unclosed=%d",
            path, depth, env_result["first_mismatch"] is not None, len(env_result["unclosed_at_eof"]),
        )
    return {"files": per_file, "balanced": balanced, "env_balanced": env_balanced}
