"""
wp_errors.py - exception hierarchy and exit-code mapping for wp-portfolio-sync.

Stage: imported by every other module in this skill. Holds no I/O, so it is
safe for the offline test suite.
"""

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSAL = 2


class WpSyncError(Exception):
    """A failure (network, HTTP, parse, or unverified write). Exit 1."""


class WpRefusal(WpSyncError):
    """A refusal by design (bad argument, bad config, a gate that failed). Exit 2."""


class WpWriteUnconfirmed(WpSyncError):
    """A PUT whose outcome is unknown: a timeout or lost connection after sending."""


def exit_code_for(exc):
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a caught exception to this skill's exit code (spec section 6).

    Inputs:
        exc (BaseException): the exception caught at a CLI's main() boundary.

    Outputs:
        code (int): EXIT_REFUSAL for a WpRefusal, EXIT_FAILURE for anything else.
    --------------------------------------------------------------------------
    """
    if isinstance(exc, WpRefusal):
        return EXIT_REFUSAL
    return EXIT_FAILURE
