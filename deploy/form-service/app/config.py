"""
config.py - Environment configuration for the form-service HTTP API.

Fails fast: a service with no shared secret does not start, so an accidental
open deployment is impossible rather than merely unlikely.
"""

import os
from dataclasses import dataclass
from typing import Mapping

MIN_KEY_LENGTH = 32
DEFAULT_MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB, matching the form-service ingest cap


@dataclass(frozen=True)
class Settings:
    """Everything the service reads from its environment."""

    service_key: str
    cert_dir: str
    signing_provider: str
    max_body_bytes: int


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the service configuration from the environment, refusing to
        return one that would leave the API unauthenticated.

    Inputs:
        env (Mapping[str, str] | None): environment mapping, os.environ by default

    Outputs:
        settings (Settings): the validated configuration

    Raises:
        RuntimeError when FORM_SERVICE_KEY is unset or too short. The message
        never repeats the value.
    --------------------------------------------------------------------------
    """
    env = os.environ if env is None else env
    key = env.get("FORM_SERVICE_KEY", "")
    if not key:
        raise RuntimeError(
            "FORM_SERVICE_KEY is not set: refusing to start an unauthenticated "
            "form service")
    if len(key) < MIN_KEY_LENGTH:
        raise RuntimeError(
            f"FORM_SERVICE_KEY is shorter than {MIN_KEY_LENGTH} characters: "
            f"refusing to start")

    return Settings(
        service_key=key,
        cert_dir=env.get("FORM_SERVICE_CERT_DIR", "/data/certs"),
        signing_provider=env.get("FORM_SERVICE_SIGNING_PROVIDER", "self-signed"),
        max_body_bytes=int(env.get("FORM_SERVICE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
    )
