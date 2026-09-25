"""
security.py - The shared-secret gate.

Every route except /health depends on this. The comparison is constant time,
the failure message says nothing about the expected value, and the secret is
never logged.
"""

import hmac
import logging

from fastapi import Header, HTTPException, status

from .config import load_settings

logger = logging.getLogger(__name__)


def keys_match(expected: str, candidate: str | None) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compare a presented key with the configured one in constant time, with
        a length mismatch handled rather than raised.

    Inputs:
        expected (str): the configured secret
        candidate (str | None): the value presented by the caller

    Outputs:
        ok (bool): True only on an exact match
    --------------------------------------------------------------------------
    """
    if not candidate:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), candidate.encode("utf-8"))


async def require_service_key(x_form_service_key: str | None = Header(default=None)) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        FastAPI dependency enforcing the shared secret on every route it guards.

    Inputs:
        x_form_service_key (str | None): the X-Form-Service-Key request header

    Outputs:
        none

    Raises:
        HTTPException 401 with a generic body; the detail never distinguishes a
        missing header from a wrong one.
    --------------------------------------------------------------------------
    """
    if not keys_match(load_settings().service_key, x_form_service_key):
        logger.warning("[FORM-SERVICE] rejected a request with an invalid service key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
