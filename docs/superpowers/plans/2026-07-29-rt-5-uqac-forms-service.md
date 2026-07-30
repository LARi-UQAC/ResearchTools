# RT-5: UQAC Form Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the fill and sign pipeline as a small containerized HTTP service that ThesisTracker can call server to server, authenticated by a shared secret, logging no field value, and shipped with a compose file whose Postgres carries the `pgvector` extension RT-7 needs.

> ## SCOPE CHANGE, 2026-07-29 - read before anything else
>
> Two decisions changed after this plan was written, and `NEW_ARCHITECTURE.md` on `main`
> is the authority on both. **Read its sections 1, 3, 4 and 10 before starting.**
>
> **The repository boundary moved.** ResearchTools cannot track a form and cannot know the information that fills one: it is skills, agents and commands for a thesis, a paper, a review or a report, and only ThesisTracker writes the database. The form catalogue, the workflow rules, the field maps, the profile store and the drift check therefore live in **ThesisTracker**, edited in the UI by an `owner` or the `direction`. The ResearchTools service is reduced to **stateless PDF mechanics**: hand it a PDF and a set of values, it hands back a PDF. It is a function, not a system, and holds no data.
>
> > **What this means for RT-5.** The service becomes stateless, and its endpoints change
> shape: they take a PDF in the request body rather than a form id.
>
> | Was | Becomes |
> |---|---|
> | `GET /forms` | **gone.** TT-8 owns the catalogue |
> | `GET /schema` | **gone.** TT-9 owns the vocabulary |
> | `POST /forms/{id}/fill` | `POST /pdf/fill`, multipart or JSON with the PDF and the values |
> | `POST /forms/{id}/signature-fields` | `POST /pdf/widgets`, returning every widget, not only signatures |
> | `POST /forms/{id}/sign` | `POST /pdf/sign`, query `field` and `reason` |
> | - | `POST /pdf/validate`, returning a signature report |
>
> - The `form-data` volume for the cache and the maps is **gone**. The service keeps one
>   volume, for signing material.
> - Everything else stands and matters more: the fail-fast shared secret, the constant-time
>   compare, no CORS, the `127.0.0.1` development bind, no AGPL in the image, and the
>   test asserting that no field value is logged and nothing is persisted between requests.
> - The `pgvector` Postgres in the compose file is needed by RT-7 only; it is no longer
>   part of the form path at all.
>
> **TT-3's client is written against this contract**, so the endpoint names and the
> `X-Uqac-*` headers must be agreed before either unit ships.
>
> Everything below that this block does not contradict still stands. Where the plan and
> `NEW_ARCHITECTURE.md` disagree, the architecture document wins, and your first commit
> should be the correction to this plan.


**Architecture:** `deploy/form-service/` is a FastAPI application that imports the skill scripts as a library and adds nothing but transport. Every route requires a constant-time-compared `X-Form-Service-Key` header; the service refuses to start when the secret is unset, so there is no accidental open deployment. `POST /forms/{form_id}/fill` returns `application/pdf` with the counts in response headers, and `POST /sign` takes a PDF body and returns the signed PDF. The image carries no AGPL dependency. `deploy/docker-compose.yml` runs the service plus a `pgvector/pgvector` Postgres and a Caddy front door whose hostname comes from the environment, so the final host stays undecided by choice.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, `pypdf`, `pyhanko`, `PyYAML`, Docker, Docker Compose, Caddy. `httpx` in the test extra for the Starlette test client.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature.
- Docstrings use the repo's extended `Purpose: / Inputs: / Outputs:` block format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[FORM-SERVICE]`. **Never log a field value, a profile, a secret, or a certificate.** Method, path, status, and duration only.
- **Bind `127.0.0.1` in development.** Inside the container the process binds `0.0.0.0` because it is reachable only on the compose network behind Caddy; the published port is bound to `127.0.0.1` on the host. Both facts are stated in the README so neither is a surprise.
- **Shared-secret header on every route**, compared with `hmac.compare_digest`. The service exits at startup when `FORM_SERVICE_KEY` is unset. The secret never appears in a log, an error body, or a compose file (it comes from the environment).
- **No CORS middleware at all.** This is a server-to-server API; a browser never calls it. A wildcard CORS policy on a route that accepts a body is forbidden by `.claude/rules/security.md`.
- **Law 25:** a profile carries a permanent code, an address, and a cheque payee. Request bodies are never persisted, never logged, and the filled PDF is streamed back rather than stored on the service.
- Maximum request body size enforced; a malformed or oversized body is rejected before any PDF work.
- Dependencies pinned exactly in `deploy/form-service/requirements.txt`, then `pip-audit -r deploy/form-service/requirements.txt --strict`. **No AGPL in the image.**
- Offline tests only: the FastAPI test client, with the skill functions patched, so the suite needs no network and no real form.

**Depends on:** RT-4 (`feat/uqac-forms-signer`), which depends on RT-3, RT-2, RT-1.

---

## File Structure

**New files**

- `deploy/form-service/app/__init__.py` - empty package marker.
- `deploy/form-service/app/config.py` - environment configuration and fail-fast validation.
- `deploy/form-service/app/security.py` - the shared-secret dependency.
- `deploy/form-service/app/skill_bridge.py` - the only module that imports the skill scripts.
- `deploy/form-service/app/main.py` - the FastAPI application and its routes.
- `deploy/form-service/requirements.txt` - exact pins for the image.
- `deploy/form-service/Dockerfile` - the image.
- `deploy/form-service/.dockerignore`
- `deploy/form-service/README.md` - run, configure, and the binding facts.
- `deploy/form-service/tests/test_api.py` - offline unit tests.
- `deploy/docker-compose.yml` - service, Postgres with `pgvector`, Caddy.
- `deploy/Caddyfile` - reverse proxy, hostname from the environment.
- `deploy/.env.example` - every variable, no value.

**Modified files**

- `.claude/skills/uqac-forms/SKILL.md` - a section pointing at the service.
- `.claude/rules/testing.md` - the new offline test command.
- `.gitignore` - ignore `deploy/.env`.

---

## Interfaces consumed

From RT-1 `form_registry.py`: `load_registry`, `map_status`, `require_fresh_map`, `StaleMapError`, `DEFAULT_CACHE_DIR`, `MAPS_DIR`.
From RT-2 `field_map.py`: `load_schema`, `load_map`, `validate_map`.
From RT-3 `fill_form.py`: `fill(form_id, profile, out_path, cache_dir, maps_dir, flatten, pdf_path) -> {"form_id","out","filled","skipped","flattened"}`.
From RT-4 `sign_form.py`: `build_signer`, `sign_pdf`, `signature_fields`, `preflight`, `SigningError`, `DEFAULT_REASON`.

---

## Task 1: Configuration and the shared-secret gate

**Files:**

- Create: `deploy/form-service/app/__init__.py`, `deploy/form-service/app/config.py`, `deploy/form-service/app/security.py`
- Create: `deploy/form-service/requirements.txt`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `class Settings` with `service_key: str`, `cache_dir: str`, `maps_dir: str`, `cert_dir: str`, `signing_provider: str`, `max_body_bytes: int`, `work_dir: str`.
  - `load_settings(env: Mapping[str, str] | None = None) -> Settings`, raising `RuntimeError` when `FORM_SERVICE_KEY` is unset or shorter than 32 characters.
  - `require_service_key(x_form_service_key: str = Header(...)) -> None`, a FastAPI dependency raising `HTTPException(401)` on a mismatch, compared with `hmac.compare_digest`.

- [ ] **Step 1: Write the failing test**

Create `deploy/form-service/tests/test_api.py`:

```python
"""
test_api.py - Offline unit tests for the UQAC form service.

No network, no real UQAC form, no certificate: the skill functions are patched
and the FastAPI test client drives the app in-process. Run with the project
Python from the repo root:
    python deploy/form-service/tests/test_api.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, security  # noqa: E402

VALID_KEY = "k" * 48


class TestSettings(unittest.TestCase):
    def test_a_valid_environment_loads(self) -> None:
        settings = config.load_settings({"FORM_SERVICE_KEY": VALID_KEY})
        self.assertEqual(settings.service_key, VALID_KEY)
        self.assertGreater(settings.max_body_bytes, 0)

    def test_a_missing_secret_refuses_to_start(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            config.load_settings({})
        self.assertIn("FORM_SERVICE_KEY", str(ctx.exception))

    def test_a_short_secret_refuses_to_start(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            config.load_settings({"FORM_SERVICE_KEY": "short"})
        self.assertIn("32", str(ctx.exception))

    def test_the_secret_is_never_repeated_in_the_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            config.load_settings({"FORM_SERVICE_KEY": "short"})
        self.assertNotIn("short", str(ctx.exception))

    def test_paths_come_from_the_environment_with_defaults(self) -> None:
        settings = config.load_settings({"FORM_SERVICE_KEY": VALID_KEY,
                                         "FORM_SERVICE_MAPS_DIR": "/data/maps"})
        self.assertEqual(settings.maps_dir, "/data/maps")
        self.assertTrue(settings.cache_dir)


class TestKeyComparison(unittest.TestCase):
    def test_the_right_key_passes(self) -> None:
        self.assertTrue(security.keys_match(VALID_KEY, VALID_KEY))

    def test_a_wrong_key_fails(self) -> None:
        self.assertFalse(security.keys_match(VALID_KEY, "j" * 48))

    def test_a_length_difference_fails_without_raising(self) -> None:
        self.assertFalse(security.keys_match(VALID_KEY, "k" * 10))

    def test_an_empty_candidate_fails(self) -> None:
        self.assertFalse(security.keys_match(VALID_KEY, ""))
        self.assertFalse(security.keys_match(VALID_KEY, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_api.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Write the requirements file**

Create `deploy/form-service/requirements.txt`:

```
# UQAC form service image. Pinned exactly, audited with:
#   pip-audit -r deploy/form-service/requirements.txt --strict
#
# Licence floor: the image must carry NO AGPL dependency, because it is
# deployed. pypdf is BSD-3 and pyhanko is MIT; PyMuPDF (AGPL-3.0) stays isolated
# in the extract-statistic skill and is never installed here.
fastapi==0.141.1
uvicorn==0.52.0
pypdf==6.14.2
pyhanko==0.36.2
cryptography==49.0.0
PyYAML==6.0.3
requests==2.34.2

# Test extra: the Starlette test client needs httpx. Installed in the test image
# layer only, never in the runtime image.
# httpx==0.28.1
```

- [ ] **Step 4: Write the minimal implementation**

Create `deploy/form-service/app/__init__.py` (empty file).

Create `deploy/form-service/app/config.py`:

```python
"""
config.py - Environment configuration for the UQAC form service.

Fails fast: a service with no shared secret does not start, so an accidental
open deployment is impossible rather than merely unlikely.
"""

import os
from dataclasses import dataclass
from typing import Mapping

MIN_KEY_LENGTH = 32
DEFAULT_MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB, matching the form download cap


@dataclass(frozen=True)
class Settings:
    """Everything the service reads from its environment."""

    service_key: str
    cache_dir: str
    maps_dir: str
    cert_dir: str
    signing_provider: str
    work_dir: str
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
        cache_dir=env.get("FORM_SERVICE_CACHE_DIR", "/data/cache"),
        maps_dir=env.get("FORM_SERVICE_MAPS_DIR", "/data/maps"),
        cert_dir=env.get("FORM_SERVICE_CERT_DIR", "/data/certs"),
        signing_provider=env.get("FORM_SERVICE_SIGNING_PROVIDER", "self-signed"),
        work_dir=env.get("FORM_SERVICE_WORK_DIR", "/tmp/form-service"),
        max_body_bytes=int(env.get("FORM_SERVICE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
    )
```

Create `deploy/form-service/app/security.py`:

```python
"""
security.py - The shared-secret gate.

Every route depends on this. The comparison is constant time, the failure
message says nothing about the expected value, and the secret is never logged.
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
        FastAPI dependency enforcing the shared secret on every route.

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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add deploy/form-service/app deploy/form-service/requirements.txt deploy/form-service/tests
git commit -m "feat(form-service): fail-fast configuration and constant-time shared-secret gate"
```

---

## Task 2: The skill bridge

**Files:**

- Create: `deploy/form-service/app/skill_bridge.py`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: `form_registry`, `field_map`, `fill_form`, `sign_form` from RT-1 to RT-4.
- Produces:
  - `list_forms(settings: Settings) -> list[dict[str, Any]]`, one entry per registered form: `{"form_id", "title", "office", "map_status"}`.
  - `profile_schema() -> dict[str, dict[str, str]]`.
  - `fill_to_bytes(form_id: str, profile: dict, flatten: bool, settings: Settings) -> tuple[bytes, dict[str, Any]]` returning the PDF bytes and the fill result.
  - `sign_bytes(pdf_bytes: bytes, field_name: str | None, reason: str, settings: Settings) -> tuple[bytes, dict[str, Any]]`.
  - `inspect_signature_fields(pdf_bytes: bytes, settings: Settings) -> list[dict[str, Any]]`.

This module is the only place that touches the skill scripts, so the routes stay pure transport and the tests patch one seam.

- [ ] **Step 1: Write the failing test**

Append to `deploy/form-service/tests/test_api.py`, above the `if __name__` block:

```python
import tempfile  # noqa: E402


class TestSkillBridge(unittest.TestCase):
    def setUp(self) -> None:
        from app import skill_bridge
        self.bridge = skill_bridge
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = config.load_settings({
            "FORM_SERVICE_KEY": VALID_KEY,
            "FORM_SERVICE_WORK_DIR": os.path.join(self.tmp.name, "work"),
            "FORM_SERVICE_MAPS_DIR": os.path.join(self.tmp.name, "maps"),
            "FORM_SERVICE_CACHE_DIR": os.path.join(self.tmp.name, "cache"),
            "FORM_SERVICE_CERT_DIR": os.path.join(self.tmp.name, "certs"),
        })
        self._real_fill = self.bridge.fill_form.fill

    def tearDown(self) -> None:
        self.bridge.fill_form.fill = self._real_fill
        self.tmp.cleanup()

    def test_fill_to_bytes_returns_the_written_pdf_and_the_counts(self) -> None:
        def fake_fill(form_id, profile, out_path, **kwargs):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as handle:
                handle.write(b"%PDF-1.7\nfilled\n%%EOF")
            return {"form_id": form_id, "out": out_path, "filled": 2,
                    "skipped": ["champ_interne"], "flattened": 2}

        self.bridge.fill_form.fill = fake_fill
        body, result = self.bridge.fill_to_bytes(
            "srf-rapport-depenses", {"student": {"nom": "X"}}, True, self.settings)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(result["filled"], 2)
        self.assertEqual(result["skipped"], ["champ_interne"])

    def test_fill_to_bytes_leaves_no_file_behind_on_the_service(self) -> None:
        def fake_fill(form_id, profile, out_path, **kwargs):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as handle:
                handle.write(b"%PDF-1.7\nfilled\n%%EOF")
            return {"form_id": form_id, "out": out_path, "filled": 1,
                    "skipped": [], "flattened": 1}

        self.bridge.fill_form.fill = fake_fill
        self.bridge.fill_to_bytes("srf-rapport-depenses", {}, True, self.settings)
        leftovers = []
        for root, _dirs, files in os.walk(self.settings.work_dir):
            leftovers.extend(os.path.join(root, f) for f in files)
        self.assertEqual(leftovers, [], "a profile-derived PDF must not linger on the service")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_api.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.skill_bridge'`.

- [ ] **Step 3: Write the minimal implementation**

Create `deploy/form-service/app/skill_bridge.py`:

```python
"""
skill_bridge.py - The only module that imports the uqac-forms skill scripts.

Keeping the import surface in one file means the routes are pure transport and
the tests have exactly one seam to patch. Nothing here persists a profile or a
filled document: the working file is deleted as soon as its bytes are read.
"""

import logging
import os
import sys
import tempfile
import uuid
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)

# The skill scripts are plain modules in the repo, mounted into the image at
# /opt/uqac-forms/scripts. SKILL_SCRIPTS_DIR overrides the location for a local
# run straight from a checkout.
_DEFAULT_SCRIPTS = os.environ.get(
    "SKILL_SCRIPTS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
        ".claude", "skills", "uqac-forms", "scripts"))
if _DEFAULT_SCRIPTS not in sys.path:
    sys.path.insert(0, _DEFAULT_SCRIPTS)

import field_map  # noqa: E402
import fill_form  # noqa: E402
import form_registry  # noqa: E402
import sign_form  # noqa: E402


def list_forms(settings: Settings) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the registered forms with the state of their field map, so a
        caller knows before filling whether a form is usable.

    Inputs:
        settings (Settings): service configuration

    Outputs:
        forms (list[dict]): {form_id, title, office, map_status}
    --------------------------------------------------------------------------
    """
    return [{
        "form_id": spec.form_id,
        "title": spec.title,
        "office": spec.office,
        "map_status": form_registry.map_status(spec.form_id, settings.maps_dir),
    } for spec in form_registry.load_registry().values()]


def profile_schema() -> dict[str, dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the shared profile vocabulary, so a caller can build a profile
        without reading the repository.

    Inputs:
        none

    Outputs:
        schema (dict): {namespace: {key: description}}
    --------------------------------------------------------------------------
    """
    return field_map.load_schema()


def _work_path(settings: Settings, suffix: str) -> str:
    """A unique path under the work directory; the caller deletes it."""
    os.makedirs(settings.work_dir, exist_ok=True)
    return os.path.join(settings.work_dir, f"{uuid.uuid4().hex}{suffix}")


def fill_to_bytes(form_id: str, profile: dict[str, Any], flatten: bool,
                  settings: Settings) -> tuple[bytes, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fill a form and return its bytes, leaving nothing on disk. The profile
        carries personal information, so the working file is removed in a finally
        block whatever happens.

    Inputs:
        form_id (str): registry id
        profile (dict): the profile document
        flatten (bool): lock the non-signature fields
        settings (Settings): service configuration

    Outputs:
        result (tuple): (pdf_bytes, fill_result)

    Raises:
        form_registry.StaleMapError, RuntimeError from the skill.
    --------------------------------------------------------------------------
    """
    out = _work_path(settings, ".pdf")
    try:
        result = fill_form.fill(form_id, profile, out,
                                cache_dir=settings.cache_dir,
                                maps_dir=settings.maps_dir,
                                flatten=flatten)
        with open(out, "rb") as handle:
            body = handle.read()
        result = {**result, "out": None}  # never leak a server path to a caller
        return body, result
    finally:
        if os.path.exists(out):
            os.remove(out)


def inspect_signature_fields(pdf_bytes: bytes, settings: Settings) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the signature fields of an uploaded PDF.

    Inputs:
        pdf_bytes (bytes): the uploaded document
        settings (Settings): service configuration

    Outputs:
        fields (list[dict]): {name, page, signed}
    --------------------------------------------------------------------------
    """
    path = _work_path(settings, ".pdf")
    try:
        with open(path, "wb") as handle:
            handle.write(pdf_bytes)
        return sign_form.signature_fields(path)
    finally:
        if os.path.exists(path):
            os.remove(path)


def sign_bytes(pdf_bytes: bytes, field_name: str | None, reason: str,
               settings: Settings) -> tuple[bytes, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sign an uploaded filled form and return the signed bytes, leaving
        nothing on disk.

    Inputs:
        pdf_bytes (bytes): the filled document
        field_name (str | None): signature field, auto-selected when unique
        reason (str): the reason recorded in the signature
        settings (Settings): service configuration

    Outputs:
        result (tuple): (signed_bytes, sign_result)

    Raises:
        sign_form.SigningError on any pre-flight refusal.
    --------------------------------------------------------------------------
    """
    source = _work_path(settings, ".pdf")
    signed = _work_path(settings, "_signe.pdf")
    try:
        with open(source, "wb") as handle:
            handle.write(pdf_bytes)
        signer = sign_form.build_signer(settings.signing_provider,
                                        cert_dir=settings.cert_dir)
        result = sign_form.sign_pdf(source, signed, signer,
                                    field_name=field_name, reason=reason)
        with open(signed, "rb") as handle:
            body = handle.read()
        return body, {**result, "in": None, "out": None}
    finally:
        for path in (source, signed):
            if os.path.exists(path):
                os.remove(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add deploy/form-service/app/skill_bridge.py deploy/form-service/tests/test_api.py
git commit -m "feat(form-service): skill bridge that never persists a profile or a filled PDF"
```

---

## Task 3: The API

**Files:**

- Create: `deploy/form-service/app/main.py`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: `load_settings`, `require_service_key`, and the whole skill bridge.
- Produces the HTTP contract TT-3 codes against:

| Method and path | Body | Success | Failure |
|---|---|---|---|
| `GET /health` | none | `200 {"status": "ok", "forms": int}` | - |
| `GET /forms` | none | `200 {"forms": [{form_id, title, office, map_status}]}` | - |
| `GET /schema` | none | `200 {"schema": {namespace: {key: description}}}` | - |
| `POST /forms/{form_id}/fill` | `{"profile": {...}, "flatten": true}` | `200 application/pdf`, headers `X-Uqac-Filled`, `X-Uqac-Flattened`, `X-Uqac-Skipped` (comma separated) | `404` unknown form, `409` stale map, `413` body too large, `422` malformed body |
| `POST /forms/{form_id}/signature-fields` | `application/pdf` | `200 {"fields": [{name, page, signed}]}` | `413`, `422` |
| `POST /forms/{form_id}/sign` | `application/pdf`, query `field`, `reason` | `200 application/pdf`, header `X-Uqac-Signature-Field` | `409` nothing signable or already signed, `413`, `422` |

Every route requires `X-Form-Service-Key` and answers `401` without it.

- [ ] **Step 1: Write the failing test**

Append to `deploy/form-service/tests/test_api.py`, above the `if __name__` block:

```python
class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FORM_SERVICE_KEY"] = VALID_KEY
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FORM_SERVICE_WORK_DIR"] = os.path.join(self.tmp.name, "work")
        os.environ["FORM_SERVICE_MAPS_DIR"] = os.path.join(self.tmp.name, "maps")
        os.environ["FORM_SERVICE_CACHE_DIR"] = os.path.join(self.tmp.name, "cache")
        os.environ["FORM_SERVICE_CERT_DIR"] = os.path.join(self.tmp.name, "certs")

        from fastapi.testclient import TestClient
        from app import main, skill_bridge

        self.bridge = skill_bridge
        self.client = TestClient(main.app)
        self.headers = {"X-Form-Service-Key": VALID_KEY}

        self._real = {
            "list_forms": skill_bridge.list_forms,
            "fill_to_bytes": skill_bridge.fill_to_bytes,
            "sign_bytes": skill_bridge.sign_bytes,
            "inspect": skill_bridge.inspect_signature_fields,
        }
        skill_bridge.list_forms = lambda settings: [
            {"form_id": "srf-rapport-depenses", "title": "Rapport de depenses",
             "office": "srf", "map_status": "ok"}]
        skill_bridge.fill_to_bytes = lambda form_id, profile, flatten, settings: (
            b"%PDF-1.7\nfilled\n%%EOF",
            {"form_id": form_id, "out": None, "filled": 3,
             "skipped": ["champ_interne"], "flattened": 3})
        skill_bridge.sign_bytes = lambda body, field, reason, settings: (
            b"%PDF-1.7\nfilled\n%%EOF-signed",
            {"field": field or "Signature_directeur", "reason": reason,
             "incremental": True, "in": None, "out": None})
        skill_bridge.inspect_signature_fields = lambda body, settings: [
            {"name": "Signature_directeur", "page": 1, "signed": False}]

    def tearDown(self) -> None:
        self.bridge.list_forms = self._real["list_forms"]
        self.bridge.fill_to_bytes = self._real["fill_to_bytes"]
        self.bridge.sign_bytes = self._real["sign_bytes"]
        self.bridge.inspect_signature_fields = self._real["inspect"]
        self.tmp.cleanup()

    def test_health_requires_no_secret_and_reports_readiness(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_every_data_route_rejects_a_missing_key(self) -> None:
        for method, path in (("get", "/forms"), ("get", "/schema"),
                             ("post", "/forms/srf-rapport-depenses/fill")):
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, 401, f"{method} {path}")

    def test_a_wrong_key_is_rejected(self) -> None:
        response = self.client.get("/forms", headers={"X-Form-Service-Key": "j" * 48})
        self.assertEqual(response.status_code, 401)

    def test_forms_lists_the_registry_with_map_status(self) -> None:
        response = self.client.get("/forms", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["forms"][0]["map_status"], "ok")

    def test_fill_returns_a_pdf_with_the_counts_in_headers(self) -> None:
        response = self.client.post("/forms/srf-rapport-depenses/fill",
                                    headers=self.headers,
                                    json={"profile": {"student": {"nom": "X"}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.headers["x-uqac-filled"], "3")
        self.assertEqual(response.headers["x-uqac-skipped"], "champ_interne")

    def test_fill_maps_a_stale_map_to_409(self) -> None:
        import form_registry

        def stale(*args, **kwargs):
            raise form_registry.StaleMapError("srf-rapport-depenses: field map is stale")
        self.bridge.fill_to_bytes = stale
        response = self.client.post("/forms/srf-rapport-depenses/fill",
                                    headers=self.headers, json={"profile": {}})
        self.assertEqual(response.status_code, 409)
        self.assertIn("stale", response.json()["detail"])

    def test_fill_maps_an_unknown_form_to_404(self) -> None:
        response = self.client.post("/forms/pas-un-formulaire/fill",
                                    headers=self.headers, json={"profile": {}})
        self.assertEqual(response.status_code, 404)

    def test_fill_rejects_a_body_without_a_profile(self) -> None:
        response = self.client.post("/forms/srf-rapport-depenses/fill",
                                    headers=self.headers, json={})
        self.assertEqual(response.status_code, 422)

    def test_signature_fields_lists_them(self) -> None:
        response = self.client.post(
            "/forms/srf-rapport-depenses/signature-fields",
            headers={**self.headers, "Content-Type": "application/pdf"},
            content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"][0]["name"], "Signature_directeur")

    def test_sign_returns_the_signed_pdf_and_names_the_field(self) -> None:
        response = self.client.post(
            "/forms/srf-rapport-depenses/sign",
            headers={**self.headers, "Content-Type": "application/pdf"},
            content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-uqac-signature-field"], "Signature_directeur")

    def test_sign_maps_a_signing_refusal_to_409(self) -> None:
        import sign_form

        def refuse(*args, **kwargs):
            raise sign_form.SigningError("no signature field")
        self.bridge.sign_bytes = refuse
        response = self.client.post(
            "/forms/srf-rapport-depenses/sign",
            headers={**self.headers, "Content-Type": "application/pdf"},
            content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 409)

    def test_an_oversized_body_is_rejected_before_any_pdf_work(self) -> None:
        os.environ["FORM_SERVICE_MAX_BODY_BYTES"] = "10"
        try:
            response = self.client.post(
                "/forms/srf-rapport-depenses/signature-fields",
                headers={**self.headers, "Content-Type": "application/pdf"},
                content=b"%PDF-1.7\n" + b"x" * 100)
            self.assertEqual(response.status_code, 413)
        finally:
            os.environ.pop("FORM_SERVICE_MAX_BODY_BYTES", None)

    def test_no_cors_middleware_is_installed(self) -> None:
        from app import main
        names = [m.cls.__name__ for m in main.app.user_middleware]
        self.assertNotIn("CORSMiddleware", names)

    def test_no_profile_value_reaches_the_log(self) -> None:
        from app import main
        with self.assertLogs(main.logger, level="INFO") as captured:
            self.client.post("/forms/srf-rapport-depenses/fill", headers=self.headers,
                             json={"profile": {"student": {"code_permanent": "TREM99010199"}}})
        self.assertNotIn("TREM99010199", "\n".join(captured.output))
```

Install the test extra first: `pip install httpx==0.28.1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_api.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Write the minimal implementation**

Create `deploy/form-service/app/main.py`:

```python
"""
main.py - The UQAC form service HTTP API.

Pure transport: every decision lives in the uqac-forms skill, reached through
skill_bridge. Every data route requires the shared secret. There is no CORS
middleware, because a browser never calls this API and a wildcard policy on a
route that accepts a body is forbidden by .claude/rules/security.md.

Nothing here logs a profile, a field value, or the secret: method, path, status,
and duration only.
"""

import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import skill_bridge
from .config import load_settings
from .security import require_service_key

logger = logging.getLogger(__name__)

app = FastAPI(title="UQAC form service", version="1.0.0", docs_url=None, redoc_url=None)


class FillRequest(BaseModel):
    """Body of a fill request. `profile` is required, so an empty POST is a 422."""

    profile: dict[str, Any] = Field(...)
    flatten: bool = True


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log method, path, status, and duration. Never a body, never a header value."""
    started = time.monotonic()
    response = await call_next(request)
    logger.info("[FORM-SERVICE] %s %s -> %s in %.0f ms", request.method,
                request.url.path, response.status_code,
                (time.monotonic() - started) * 1000)
    return response


async def _pdf_body(request: Request) -> bytes:
    """Read a PDF request body, enforcing the size cap before any PDF work."""
    settings = load_settings()
    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Request body exceeds the configured maximum")
    if not body.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Body is not a PDF")
    return body


def _known_form(form_id: str) -> None:
    """404 an unknown form id before anything else runs."""
    settings = load_settings()
    if form_id not in {f["form_id"] for f in skill_bridge.list_forms(settings)}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Unknown form id: {form_id}")


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness probe. The only route with no shared-secret requirement."""
    try:
        count = len(skill_bridge.list_forms(load_settings()))
    except Exception:  # a broken registry must not look healthy
        logger.exception("[FORM-SERVICE] health check failed to read the registry")
        return JSONResponse(status_code=503, content={"status": "degraded", "forms": 0})
    return JSONResponse(content={"status": "ok", "forms": count})


@app.get("/forms", dependencies=[Depends(require_service_key)])
async def forms() -> dict[str, Any]:
    """The registered forms with the state of their field map."""
    return {"forms": skill_bridge.list_forms(load_settings())}


@app.get("/schema", dependencies=[Depends(require_service_key)])
async def schema() -> dict[str, Any]:
    """The shared profile vocabulary."""
    return {"schema": skill_bridge.profile_schema()}


@app.post("/forms/{form_id}/fill", dependencies=[Depends(require_service_key)])
async def fill(form_id: str, body: FillRequest) -> Response:
    """Fill one form and stream the PDF back. Counts travel in headers."""
    _known_form(form_id)
    settings = load_settings()
    try:
        pdf, result = skill_bridge.fill_to_bytes(form_id, body.profile, body.flatten, settings)
    except skill_bridge.form_registry.StaleMapError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return Response(content=pdf, media_type="application/pdf", headers={
        "X-Uqac-Filled": str(result["filled"]),
        "X-Uqac-Flattened": str(result["flattened"]),
        "X-Uqac-Skipped": ",".join(result["skipped"]),
    })


@app.post("/forms/{form_id}/signature-fields", dependencies=[Depends(require_service_key)])
async def signature_fields(form_id: str, request: Request) -> dict[str, Any]:
    """List the signature fields of an uploaded filled form."""
    _known_form(form_id)
    body = await _pdf_body(request)
    return {"fields": skill_bridge.inspect_signature_fields(body, load_settings())}


@app.post("/forms/{form_id}/sign", dependencies=[Depends(require_service_key)])
async def sign(form_id: str, request: Request,
               field: str | None = None, reason: str | None = None) -> Response:
    """Sign an uploaded filled form and stream the signed PDF back."""
    _known_form(form_id)
    body = await _pdf_body(request)
    settings = load_settings()
    chosen_reason = reason or skill_bridge.sign_form.DEFAULT_REASON
    try:
        pdf, result = skill_bridge.sign_bytes(body, field, chosen_reason, settings)
    except skill_bridge.sign_form.SigningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return Response(content=pdf, media_type="application/pdf", headers={
        "X-Uqac-Signature-Field": str(result["field"]),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 25 tests.

- [ ] **Step 5: Commit**

```bash
git add deploy/form-service/app/main.py deploy/form-service/tests/test_api.py
git commit -m "feat(form-service): fill, signature-fields, and sign routes behind the shared secret"
```

---

## Task 4: Container and compose

**Files:**

- Create: `deploy/form-service/Dockerfile`, `deploy/form-service/.dockerignore`, `deploy/form-service/README.md`
- Create: `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/.env.example`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: the application from Tasks 1 to 3.
- Produces: a runnable stack. Service reachable at `http://127.0.0.1:8081` locally and behind Caddy at `${FORM_SERVICE_HOST}` on a real host; Postgres at `db:5432` with the `vector` extension available, which **RT-7 consumes** as its pgvector store.

- [ ] **Step 1: Write the Dockerfile**

Create `deploy/form-service/Dockerfile`:

```dockerfile
# UQAC form service. No AGPL dependency ships in this image.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SKILL_SCRIPTS_DIR=/opt/uqac-forms/scripts

WORKDIR /srv

COPY deploy/form-service/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

# The skill is the library; the service is the transport.
COPY .claude/skills/uqac-forms/scripts /opt/uqac-forms/scripts
COPY .claude/skills/uqac-forms/registry /opt/uqac-forms/registry
COPY deploy/form-service/app /srv/app

# Non-root, and a data directory the compose file mounts over.
RUN useradd --system --create-home --uid 10001 formsvc \
    && mkdir -p /data/cache /data/maps /data/certs /tmp/form-service \
    && chown -R formsvc:formsvc /data /tmp/form-service /srv
USER formsvc

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

# Inside the container the process binds 0.0.0.0 because it is reachable only on
# the compose network behind Caddy, and the published port is bound to 127.0.0.1
# on the host. A local run outside Docker binds 127.0.0.1 (see README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
```

Create `deploy/form-service/.dockerignore`:

```
**/__pycache__/
**/*.pyc
**/Test/
**/tests/
.git/
out/
```

- [ ] **Step 2: Write the compose file**

Create `deploy/docker-compose.yml`:

```yaml
# UQAC form engine stack. Host-agnostic by design: every hostname and secret
# comes from the environment, so the final Docker host is chosen before real
# data loads and not before build. Copy deploy/.env.example to deploy/.env.
services:
  form-service:
    build:
      context: ..
      dockerfile: deploy/form-service/Dockerfile
    environment:
      FORM_SERVICE_KEY: ${FORM_SERVICE_KEY:?set FORM_SERVICE_KEY in deploy/.env}
      FORM_SERVICE_CACHE_DIR: /data/cache
      FORM_SERVICE_MAPS_DIR: /data/maps
      FORM_SERVICE_CERT_DIR: /data/certs
      FORM_SERVICE_SIGNING_PROVIDER: ${FORM_SERVICE_SIGNING_PROVIDER:-self-signed}
    volumes:
      - form-data:/data
    ports:
      # Published on the loopback interface only, never on 0.0.0.0.
      - "127.0.0.1:8081:8080"
    restart: unless-stopped

  db:
    # pgvector rides the Postgres the stack already needs; RT-7 stores its
    # corpus embeddings here, so no separate vector vendor is introduced.
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-uqac}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in deploy/.env}
      POSTGRES_DB: ${POSTGRES_DB:-uqac}
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./initdb:/docker-entrypoint-initdb.d:ro
    ports:
      - "127.0.0.1:5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-uqac} -d ${POSTGRES_DB:-uqac}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    environment:
      # The host is undecided by choice: Caddy reads it from the environment.
      FORM_SERVICE_HOST: ${FORM_SERVICE_HOST:-localhost}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - form-service
    restart: unless-stopped

volumes:
  form-data:
  db-data:
  caddy-data:
  caddy-config:
```

Create `deploy/initdb/01-pgvector.sql`:

```sql
-- Enable the vector extension the RT-7 corpus index stores its embeddings in.
-- Runs once, on an empty data directory.
CREATE EXTENSION IF NOT EXISTS vector;
```

Create `deploy/Caddyfile`:

```
# Hostname comes from the environment so the stack is host-agnostic.
{$FORM_SERVICE_HOST} {
	encode zstd gzip

	# Server to server only: no CORS header is ever added here.
	reverse_proxy form-service:8080 {
		header_up X-Forwarded-Proto {scheme}
	}
}
```

Create `deploy/.env.example`:

```
# Copy to deploy/.env and fill. deploy/.env is gitignored and never committed.

# Shared secret between ThesisTracker and the form service. At least 32
# characters. Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
FORM_SERVICE_KEY=

# Signing provider. self-signed is a DEVELOPMENT default and is not accepted as
# an institutional signature. See the open item in SKILL.md.
FORM_SERVICE_SIGNING_PROVIDER=self-signed

# Postgres (pgvector). RT-7 stores corpus embeddings in this database.
POSTGRES_USER=uqac
POSTGRES_PASSWORD=
POSTGRES_DB=uqac

# Public hostname served by Caddy. localhost for a workstation run.
FORM_SERVICE_HOST=localhost
```

Append to `.gitignore`:

```
# form service: local environment, never committed
deploy/.env
```

- [ ] **Step 3: Write the service README**

Create `deploy/form-service/README.md`:

````markdown
# UQAC form service

Transport for the `uqac-forms` skill: fill and sign the official UQAC forms over
HTTP, so ThesisTracker calls one service instead of shelling out to Python.

## Run it locally, no Docker

```bash
export FORM_SERVICE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export FORM_SERVICE_CACHE_DIR=out/uqac-forms/cache
export FORM_SERVICE_MAPS_DIR=.claude/skills/uqac-forms/registry/maps
export FORM_SERVICE_CERT_DIR=.claude/skills/uqac-forms/certs
uvicorn app.main:app --host 127.0.0.1 --port 8081 --app-dir deploy/form-service
```

The development bind is `127.0.0.1`, never `0.0.0.0`.

## Run the stack

```bash
cp deploy/.env.example deploy/.env   # then fill FORM_SERVICE_KEY and POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build
```

Inside the container the process binds `0.0.0.0`, because it is reachable only on
the compose network behind Caddy, and the published port is bound to
`127.0.0.1:8081` on the host. Those are two different statements and both are
deliberate.

## Authentication

Every route except `GET /health` requires `X-Form-Service-Key`. The comparison is
constant time. The service refuses to start when `FORM_SERVICE_KEY` is unset or
shorter than 32 characters, so an unauthenticated deployment is not reachable by
mistake. The secret never appears in a log or an error body.

There is no CORS middleware: a browser never calls this API.

## Endpoints

| Method and path | Body | Returns |
|---|---|---|
| `GET /health` | none | `{"status": "ok", "forms": n}` |
| `GET /forms` | none | `{"forms": [{form_id, title, office, map_status}]}` |
| `GET /schema` | none | `{"schema": {namespace: {key: description}}}` |
| `POST /forms/{id}/fill` | `{"profile": {...}, "flatten": true}` | `application/pdf`, headers `X-Uqac-Filled`, `X-Uqac-Flattened`, `X-Uqac-Skipped` |
| `POST /forms/{id}/signature-fields` | `application/pdf` | `{"fields": [{name, page, signed}]}` |
| `POST /forms/{id}/sign` | `application/pdf`, query `field`, `reason` | `application/pdf`, header `X-Uqac-Signature-Field` |

Status codes: `401` no or wrong key, `404` unknown form, `409` stale field map or
a signing refusal, `413` body over the cap, `422` malformed body.

## Personal information

A profile carries a permanent code, a postal address, and a cheque payee. The
service never persists a request body, never logs a field value, and deletes its
working file in a `finally` block. Nothing is stored between requests.

## Signing

The default provider is `self-signed`, which is a development credential.
Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES signature is unverified. Switch providers with
`FORM_SERVICE_SIGNING_PROVIDER` once that is answered.
````

- [ ] **Step 4: Verify the container end to end**

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build -d
curl -s http://127.0.0.1:8081/health
curl -s -H "X-Form-Service-Key: $FORM_SERVICE_KEY" http://127.0.0.1:8081/forms
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/forms          # expect 401
docker compose -f deploy/docker-compose.yml exec db psql -U uqac -d uqac -c "SELECT extname FROM pg_extension WHERE extname='vector';"
docker compose -f deploy/docker-compose.yml down
```

Expected: `/health` returns `{"status":"ok","forms":5}`, `/forms` returns the registry with `map_status` per form, the unauthenticated call returns `401`, and the `psql` query returns one row named `vector`.

- [ ] **Step 5: Audit the image dependencies**

```powershell
pip-audit -r deploy/form-service/requirements.txt --strict
```

Expected: no vulnerabilities. Cite any `CVE-YYYY-NNNNN` and its fixed version in a comment above the bumped pin.

- [ ] **Step 6: Update SKILL.md and the rules**

Add to `.claude/skills/uqac-forms/SKILL.md`:

```markdown
## HTTP service

`deploy/form-service/` wraps this skill in a FastAPI application so another
application (ThesisTracker) can fill and sign without shelling out to Python.
Every route requires a shared-secret header, the service refuses to start
without one, and no field value or profile is ever logged or persisted. See
`deploy/form-service/README.md` for the endpoint table and the run commands.
```

Add to `.claude/rules/testing.md`:

```powershell
python deploy/form-service/tests/test_api.py   # configuration, secret gate, skill bridge, routes (needs httpx)
```

- [ ] **Step 7: Run the full offline suite**

```powershell
python deploy/form-service/tests/test_api.py
python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add deploy .claude/skills/uqac-forms/SKILL.md .claude/rules/testing.md .gitignore
git commit -m "feat(form-service): container, compose with pgvector Postgres, and Caddy front door"
```

---

## Interfaces published by RT-5

**HTTP contract, consumed by TT-3:** the endpoint table in Task 3. Header names, status codes, and the `X-Uqac-*` response headers are the contract; TT-3 codes against them and its injected-fetch tests assert them.

**For RT-6:** the same FastAPI application. RT-6 adds `GET /publications` to `app/main.py`, reuses `require_service_key`, and adds its own module next to `skill_bridge.py`.

**For RT-7:** the `db` service of `deploy/docker-compose.yml`, a `pgvector/pgvector:pg17` Postgres with the `vector` extension created by `deploy/initdb/01-pgvector.sql`, reachable at `db:5432` on the compose network and `127.0.0.1:5433` on the host.

**Environment variables:** `FORM_SERVICE_KEY` (required, 32 characters minimum), `FORM_SERVICE_CACHE_DIR`, `FORM_SERVICE_MAPS_DIR`, `FORM_SERVICE_CERT_DIR`, `FORM_SERVICE_SIGNING_PROVIDER`, `FORM_SERVICE_WORK_DIR`, `FORM_SERVICE_MAX_BODY_BYTES`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `FORM_SERVICE_HOST`.

---

## Acceptance

```powershell
python deploy/form-service/tests/test_api.py
pip-audit -r deploy/form-service/requirements.txt --strict
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build -d
curl -s http://127.0.0.1:8081/health
```

Plus the RT-1 through RT-4 suites and the five existing offline suites in `.claude/rules/testing.md`, which must stay green.

---

## Task 5: Documentation and the pull request

Run this after the acceptance block above passes. It is the last task of the unit,
and it is what makes the work reviewable by someone who was not here.

**Files:**

- Modify: `README.md`
- Modify: `Architecture.md`
- Modify: `NEW_ARCHITECTURE.md`

**Interfaces:**

- Consumes: the finished implementation of every task above.
- Produces: the inventories a reader needs, and one pull request per unit so nothing
  reaches `main` unreviewed.

- [ ] **Step 1: Update `README.md`**

Task 6 of this plan updates `SKILL.md` and the rules but not the README. Add here:

1. A `### Deployment` subsection, or a paragraph in the existing deployment area,
   naming `deploy/form-service/` as the containerized transport over the
   `uqac-forms` skill, and pointing at `deploy/form-service/README.md` for the
   endpoint table and the run commands.
2. In the Prerequisites table, a row for Docker and Docker Compose, needed only for
   the service, never for the skill itself.
3. In the File-Locations tree, a `deploy/` branch listing `form-service/` (app,
   Dockerfile, requirements, tests), `docker-compose.yml`, `Caddyfile`,
   `initdb/01-pgvector.sql`, and `.env.example`.
4. One sentence on the security posture, because it is the part a reader is most
   likely to get wrong: every route requires a shared-secret header, the service
   refuses to start without one, there is no CORS middleware, and no profile or
   field value is ever logged or persisted.

- [ ] **Step 2: Update `Architecture.md`**

This unit adds a deployment layer the document does not yet describe. Add a short
section after the existing layers, with its own mermaid diagram, showing the
service, the `pgvector` Postgres, and the Caddy front door, and stating the two
properties that matter: the service is reached over a private network with a shared
secret, and the image carries no AGPL dependency because PyMuPDF stays isolated in
the `extract-statistic` skill.

Add one line naming the consumer: ThesisTracker calls this service, and the
dependency runs one way only. Do not draw ThesisTracker into the Layer 1 graph; it
is a separate system, and `NEW_ARCHITECTURE.md` is where the two meet.

- [ ] **Step 3: Update `NEW_ARCHITECTURE.md`**

`NEW_ARCHITECTURE.md` is committed identically to `main` in both ResearchTools and
ThesisTracker. Edit only what this unit owns, and keep the wording identical in both
checkouts so the two copies never drift.

1. In the section 9 unit table, append ` Delivered <YYYY-MM-DD>.` to the **RT-5** row's
   deliverable cell.
2. Section 4 (the runtime topology diagram) describes what this unit builds. Verify the
   service name, the port, the volume, and the statement that the service has no published
   host port, all against the delivered compose file. Section 10's security table names
   `config.load_settings` and `security.keys_match`: confirm both exist and behave as stated.
3. The file opens with `**Status: planned, not implemented.**` That line stops being true
   the moment any unit lands. Replace it with
   `**Status: in progress. <n> of 14 units delivered.**` and keep the count correct.

The change must land in both repositories. After committing it here, copy the same file
into the other checkout and open a second, documentation-only pull request there, or fold
it into that repository's next unit pull request. Verify the two copies match:

```bash
git -C "<path to ResearchTools>" show main:NEW_ARCHITECTURE.md | sha256sum
git -C "<path to ThesisTracker>" show main:NEW_ARCHITECTURE.md | sha256sum
```

Expected: the two digests are equal.

- [ ] **Step 4: Verify every relative link resolves**

```bash
grep -ohE "\]\([^)#][^)]*\)" README.md Architecture.md NEW_ARCHITECTURE.md \
  | sed 's/.*](//; s/)$//' | grep -v "^http" | sort -u \
  | while read -r f; do [ -e "$f" ] || echo "BROKEN: $f"; done
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md Architecture.md NEW_ARCHITECTURE.md
git commit -m "docs(form-service): record RT-5 in the inventories"
```

- [ ] **Step 6: Open the pull request**

`gh` is **not installed** on this machine, and `GITHUB_TOKEN` carries `read:user` only,
so neither the CLI nor that token can open a pull request. Do not try to install `gh`.
The OAuth token in the Windows Credential Manager has `repo` scope and is sufficient.
Retrieve it per command: never write it to a file, never echo it, never commit it.

```bash
git push -u origin feat/uqac-forms-service

TOK=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')
curl -s -X POST https://api.github.com/repos/LARi-UQAC/ResearchTools/pulls \
  -H "Authorization: Bearer $TOK" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  --data-binary @pr-body.json
```

Write `pr-body.json` to the scratchpad first, never into the repository:

```json
{
  "title": "[RT-5] uqac-forms: containerized HTTP service",
  "head": "feat/uqac-forms-service",
  "base": "main",
  "body": "Closes #8\n\n<what the unit delivers, in three or four lines>\n\n**Depends on.** RT-4 (`feat/uqac-forms-signer`), and the whole RT-1 to RT-4 chain behind it.\n\n**Acceptance run.** <paste the commands from the acceptance block and their real result, not a summary>\n\n**Reviewer must check by hand.** <the manual verification steps of this plan, or 'none'>"
}
```

If a permission classifier blocks the command that reads the token, open the pull request
in the browser instead and paste the same title and body:

```
https://github.com/LARi-UQAC/ResearchTools/compare/main...feat/uqac-forms-service?expand=1
```

Then delete `pr-body.json` from the scratchpad.

**Do not merge your own pull request.** Merging to `main` is the human gate. RT-6, RT-7, TT-3 and TT-5 are all blocked behind this unit. It is the widest dependency of the project; say so in the body.

- [ ] **Step 7: Report**

State the pull request URL, the acceptance commands you ran with their real output, and
anything you could not verify. A test you did not run is not a test that passed.
