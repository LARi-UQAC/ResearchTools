"""
askuserquestion-clarity.py - PreToolUse gate on AskUserQuestion.

Enforces R25 of .claude/rules/preferences.md: a question put to the user states the origin of
the choice, what each option does, and what it costs, with the recommended option first. A
question that fails is refused (exit 2) and the reason is returned so it can be rewritten,
which is the point - the alternative is a vague question the user cannot answer without first
reconstructing the problem.

WHAT THIS CAN AND CANNOT PROVE. It checks structural minima only: that a description exists,
that it is longer than the label it belongs to, that the question is long enough to have named
something concrete, and that exactly one option is marked recommended and sits first. It cannot
prove that a description is true, that the stated cost is the real cost, or that the origin
named is the actual origin. R25 remains the standard; this catches the cases where the standard
was not attempted at all.

MEASURED 2026-08-30 on this machine, because the Claude Code hook documentation does not say
either way - it names only EndConversation as excluded from PreToolUse. A probe hook recorded:

    {"tool_name": "AskUserQuestion", "hook_event_name": "PreToolUse",
     "agent_type": null, "tool_input_keys": ["questions"]}

with tool_input.questions carrying the full question objects (question, header, multiSelect,
options[].label, options[].description). That payload shape is what this hook reads.

EXIT CODES (R12):
    0  the call is clean, OR the gate is disabled, OR the payload is not ours to judge.
    2  refusal by design; stderr carries the reason and reaches the model as the block reason.
  There is no other exit code. Every failure path here returns 0: this hook runs on someone
  else's behalf, and R11 binds - a hook whose own dependency is absent exits 0 and says nothing.
  A missing, unreadable or unparsable askuserquestion-clarity.json therefore disables the gate
  rather than refusing every question the session ever asks.
"""

import json
import os
import re
import sys

TOOL_NAME = "AskUserQuestion"
CONFIG_NAME = "askuserquestion-clarity.json"
NON_ALNUM = re.compile(r"[^a-z0-9]+")

HEADER = (
    "[QUESTION GATE] This AskUserQuestion call was refused: it would reach the user as a\n"
    "question they cannot answer without first reconstructing the problem.\n"
)

FOOTER = (
    "\nRewrite the question with the four parts R25 requires, then call the tool again:\n"
    "  1. ORIGIN      - the file and line, the flag, the measurement or the failing case that\n"
    "                   produced this choice. Name it concretely.\n"
    "  2. BEHAVIOUR   - what each option actually does, in its description. The label is a\n"
    "                   name, never an explanation.\n"
    "  3. CONSEQUENCE - what each option costs, forecloses or leaves unfixed. An option with\n"
    "                   only upsides has not been thought through.\n"
    "  4. RECOMMEND   - the option you recommend goes FIRST, its label ending in "
    "'{marker}'.\n"
    "\nIf no option has a real cost, the choice was not the user's to make: decide it here and\n"
    "say what you decided instead of asking.\n"
    "\nRule: .claude/rules/preferences.md, R25. Thresholds: .claude/hooks/" + CONFIG_NAME + "\n"
)


def _normalize(text):
    """
    --------------------------------------------------------------------------
    Purpose:
        Reduce a label or a description to comparable form, so that a
        description restating its label is recognised whatever the casing,
        punctuation or spacing.

    Inputs:
        text (str): raw label or description

    Outputs:
        result (str): lowercased text with every run of non-alphanumerics
                      collapsed to a single space, stripped
    --------------------------------------------------------------------------
    """
    return NON_ALNUM.sub(" ", (text or "").lower()).strip()


def load_config(directory):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the threshold file that sits beside this hook. Its absence is not
        an error: it disables the gate (R11), because a hook that cannot do its
        job must say nothing rather than refuse every call in its matcher.

    Inputs:
        directory (str): the directory holding this script

    Outputs:
        result (dict or None): the parsed configuration, or None when the gate
                               cannot or must not run
    --------------------------------------------------------------------------
    """
    path = os.path.join(directory, CONFIG_NAME)
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict):
        return None
    if not config.get("enabled", True):
        return None
    return config


def check_question(question, config):
    """
    --------------------------------------------------------------------------
    Purpose:
        Judge one question object against the structural minima of R25 and
        return every way it falls short, rather than the first, so that a
        rewrite can fix them in one pass.

    Inputs:
        question (dict): one entry of tool_input["questions"]
        config (dict): thresholds, as loaded from askuserquestion-clarity.json

    Outputs:
        result (list): human-readable failure strings, empty when the question
                       satisfies every check
    --------------------------------------------------------------------------
    """
    problems = []
    if not isinstance(question, dict):
        return problems

    header = str(question.get("header") or "(no header)")
    text = question.get("question")
    text = text if isinstance(text, str) else ""

    min_question = config.get("min_question_chars", 0)
    if len(text.strip()) < min_question:
        problems.append(
            "  [{h}] The question is {n} characters, under the {m} the gate asks for. It has\n"
            "        room for a label but not for the origin of the choice. Name the file and\n"
            "        line, the flag, the measurement or the failing case that produced it."
            .format(h=header, n=len(text.strip()), m=min_question))

    if config.get("require_question_mark", False) and text.strip() and not text.strip().endswith("?"):
        problems.append(
            "  [{h}] The question does not end in '?'. A statement handed to AskUserQuestion is\n"
            "        usually a decision that was never actually put to the user."
            .format(h=header))

    options = question.get("options")
    options = options if isinstance(options, list) else []

    marker = config.get("recommended_marker", "")
    marked = []
    min_description = config.get("min_description_chars", 0)
    min_gain = config.get("min_description_gain_chars", 0)

    for index, option in enumerate(options):
        if not isinstance(option, dict):
            continue
        label = option.get("label")
        label = label if isinstance(label, str) else ""
        description = option.get("description")
        description = description if isinstance(description, str) else ""

        if marker and marker.lower() in label.lower():
            marked.append(index)

        stripped = description.strip()
        if not stripped:
            problems.append(
                "  [{h}] Option '{l}' carries no description. The label is a name; the user\n"
                "        needs what the option DOES and what it COSTS."
                .format(h=header, l=label or "(unnamed)"))
            continue

        if len(stripped) < min_description:
            problems.append(
                "  [{h}] Option '{l}' has a {n}-character description, under the {m} the gate\n"
                "        asks for. Behaviour plus consequence does not fit in that; a restated\n"
                "        label does."
                .format(h=header, l=label or "(unnamed)", n=len(stripped), m=min_description))
            continue

        # The marker comes off the label first. Left in, it makes the label normalize to
        # "... recommended", which no description contains, so the restatement check below
        # could never fire on the one option most likely to carry a lazy description - the
        # recommended one. Caught by test_description_restating_its_label_is_refused.
        bare_label = label.replace(marker, " ") if marker else label
        normalized_label = _normalize(bare_label)
        normalized_description = _normalize(stripped)
        if normalized_label and normalized_label in normalized_description:
            # Every occurrence, not the first: a description that repeats the label three
            # times has added nothing three times.
            remainder = normalized_description.replace(normalized_label, " ").strip()
            if len(remainder) < min_gain:
                problems.append(
                    "  [{h}] Option '{l}' has a description that restates its label and adds\n"
                    "        {n} characters of substance, under the {m} the gate asks for. Say\n"
                    "        what happens if it is chosen, and what that costs."
                    .format(h=header, l=label or "(unnamed)", n=len(remainder), m=min_gain))

    if options and config.get("require_recommended_marker", False):
        if not marked:
            problems.append(
                "  [{h}] No option is marked '{m}'. Having an opinion is part of the work: a\n"
                "        flat menu pushes a judgment back onto the user that this session was\n"
                "        better placed to make."
                .format(h=header, m=marker))
        elif len(marked) > 1:
            problems.append(
                "  [{h}] {n} options are marked '{m}'. Exactly one is a recommendation; more\n"
                "        than one is none."
                .format(h=header, n=len(marked), m=marker))

    if marked and config.get("require_recommended_first", False) and marked[0] != 0:
        problems.append(
            "  [{h}] The recommended option is at position {p}, not first. The reader stops at\n"
            "        the first plausible option, so a recommendation buried below it is not one."
            .format(h=header, p=marked[0] + 1))

    return problems


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    if (payload.get("tool_name") or "") != TOOL_NAME:
        return 0

    config = load_config(os.path.dirname(os.path.abspath(__file__)))
    if config is None:
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    questions = tool_input.get("questions")
    if not isinstance(questions, list):
        return 0

    problems = []
    for question in questions:
        problems.extend(check_question(question, config))
    if not problems:
        return 0

    marker = config.get("recommended_marker", "")
    sys.stderr.write(HEADER + "\n" + "\n".join(problems) + FOOTER.format(marker=marker))
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # R11: never refuse a tool because this hook itself broke.
        sys.exit(0)
