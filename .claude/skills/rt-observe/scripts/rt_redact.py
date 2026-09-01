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
