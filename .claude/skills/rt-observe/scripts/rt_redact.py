"""
rt_redact - rewrite any path under the home directory to `~`.

One implementation, four callers. It existed as a private copy in each of the
two adapters, and the two collectors that report a path had no copy at all -
which is exactly the defect it exists to prevent. Measured 2026-08-31 on the
live `/api/state`: two fields carried the operator's account name in full, the
graph panel's own reason string and the vault daemon's outbox path, because both
expand `~` before reporting it and nothing put it back.

The snapshot is rendered in a browser, screenshotted, and pasted into reports, so
an account name in it travels further than the machine it came from. That is why
this is a shared module rather than a habit.
"""
from pathlib import Path


def home_tilde(text, home):
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace the home directory prefix with `~` in any string, in both the
        native and the forward-slash spelling, so a Windows path and its Git
        Bash form are both covered.

    Inputs:
        text (str): any string that may carry a path
        home (Path or str): the home directory to hide

    Outputs:
        text (str): the same string with the home prefix rewritten
    --------------------------------------------------------------------------
    """
    if not text:
        return text
    home_text = str(Path(home))
    out = str(text).replace(home_text, "~")
    return out.replace(home_text.replace("\\", "/"), "~")


def redact_json(value, home):
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply `home_tilde` to every string inside a JSON-shaped value (a
        dict/list/str/other mix), recursively, so a whole response body can be
        redacted in one call rather than per field. Promoted here from
        `rt_openobserve.py`'s own private copy once a second caller
        (`rt_state.py`'s voice-answer route) needed the same walk (R18).

    Inputs:
        value: any JSON-decodable value - dict, list, str, or a JSON scalar
        home (Path or str): the home directory to hide

    Outputs:
        value: the same shape, with every string passed through `home_tilde`
    --------------------------------------------------------------------------
    """
    if isinstance(value, str):
        return home_tilde(value, home)
    if isinstance(value, dict):
        return {k: redact_json(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_json(v, home) for v in value]
    return value
