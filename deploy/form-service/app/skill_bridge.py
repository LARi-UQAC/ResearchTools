"""
skill_bridge.py - The only module that imports the form-service skill scripts.

Keeping the import surface in one file means the routes are pure transport and
the tests have exactly one seam to patch. Every function is bytes-in,
bytes-out: nothing here persists a request body, and the only disk access at
all is sign_bytes reading or generating the long-lived signing certificate
under settings.cert_dir.
"""

import logging
import os
import sys
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

# The skill scripts are plain modules in the repo, mounted into the image at
# /opt/form-service/scripts. SKILL_SCRIPTS_DIR overrides the location for a
# local run straight from a checkout.
_DEFAULT_SCRIPTS = os.environ.get(
    "SKILL_SCRIPTS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
        ".claude", "skills", "form-service", "scripts"))
if _DEFAULT_SCRIPTS not in sys.path:
    sys.path.insert(0, _DEFAULT_SCRIPTS)

import field_map  # noqa: E402
import fill_form  # noqa: E402
import sign_form  # noqa: E402


def widgets_of(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List every AcroForm widget in an uploaded PDF.

    Inputs:
        pdf_bytes (bytes): the uploaded document

    Outputs:
        widgets (list[dict]): name, name_hex, type, page, rect, on_states,
            readonly, per field_map.dump_widgets
    --------------------------------------------------------------------------
    """
    return field_map.dump_widgets(pdf_bytes)


def fill_to_bytes(pdf_bytes: bytes, values: dict[str, str], flatten_fields: list[str],
                  settings: Settings) -> tuple[bytes, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fill a PDF and return the result bytes with a small summary. Stateless:
        the input bytes are never written to disk.

    Inputs:
        pdf_bytes (bytes): the form to fill
        values (dict[str, str]): byte-exact field name to value
        flatten_fields (list[str]): fields to lock, normally those of the step
            that just completed
        settings (Settings): service configuration, unused here today, carried
            for a future per-request limit

    Outputs:
        result (tuple): (filled_bytes, {"filled": int, "flattened": int})

    Raises:
        fill_form.FillError: an unknown field name or a checkbox value that is
            not one of the widget's own on-states.
    --------------------------------------------------------------------------
    """
    del settings  # not needed yet; kept for a future per-request policy
    body = fill_form.fill(pdf_bytes, values, flatten_fields or None)
    return body, {"filled": len(values), "flattened": len(flatten_fields or [])}


def sign_bytes(pdf_bytes: bytes, field_name: str | None, reason: str,
               settings: Settings) -> tuple[bytes, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sign an uploaded filled PDF and return the signed bytes.

    Inputs:
        pdf_bytes (bytes): the filled document
        field_name (str | None): signature field, auto-selected when unique
        reason (str): the reason recorded in the signature
        settings (Settings): service configuration; signing_provider and
            cert_dir decide which signer builds

    Outputs:
        result (tuple): (signed_bytes, {"field": str})

    Raises:
        sign_form.SigningError: any pre-flight refusal, or the underlying
            signing failure.
    --------------------------------------------------------------------------
    """
    signer = sign_form.build_signer(settings.signing_provider, cert_dir=settings.cert_dir)
    chosen = sign_form.preflight(pdf_bytes, field_name)
    signed = sign_form.sign_pdf(pdf_bytes, signer, field_name=chosen, reason=reason)
    return signed, {"field": chosen}


def validate_bytes(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the validation status of every signature in an uploaded PDF.

    Inputs:
        pdf_bytes (bytes): the document to check

    Outputs:
        report (list[dict]): field, intact, valid, trusted, per
            sign_form.validate_signatures
    --------------------------------------------------------------------------
    """
    return sign_form.validate_signatures(pdf_bytes)
