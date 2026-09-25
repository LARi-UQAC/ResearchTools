# RT-5: form-service HTTP API implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the `form-service` skill's stateless PDF mechanics (RT-1 through RT-4) as a small containerized HTTP service that ThesisTracker calls server to server, authenticated by a shared secret, logging no field value, and shipped with a compose file whose Postgres carries the `pgvector` extension RT-7 needs.

> ## CORRECTION, 2026-09-25 - this plan was rewritten before implementation started
>
> The version of this plan written 2026-07-29 targeted a form-catalogue-aware service
> (`GET /forms`, `GET /schema`, `POST /forms/{id}/fill`) built on top of a `form_registry`
> module. Two things changed since, both already recorded in `NEW_ARCHITECTURE.md`:
>
> 1. **The repository boundary moved (2026-07-29 SCOPE CHANGE).** ResearchTools cannot track
>    a form and cannot know the information that fills one. The catalogue, the field maps, the
>    profile store and the drift check live in **ThesisTracker** (TT-8/TT-9). This service is
>    reduced to stateless PDF mechanics: hand it a PDF and it hands back a PDF, or a report
>    about one. There never was a `form_registry.py` module in this skill; RT-1 through RT-4
>    shipped `pdf_ingest.py`, `field_map.py`, `fill_form.py`, `sign_form.py`, all bytes-in,
>    bytes-out, none of them touching a catalogue.
> 2. **The skill renamed `uqac-forms` -> `form-service` (2026-09-25).** The form-filling
>    mechanics were already institution-agnostic; only the name overclaimed UQAC-specificity.
>    This plan's own branch is `feat/uqac-forms-service` on disk still; it renames to
>    `feat/form-service` as this plan's first commit, matching the row `NEW_ARCHITECTURE.md`
>    section 9 already carries for RT-5.
>
> **The endpoint contract is `/pdf/widgets`, `/pdf/fill`, `/pdf/sign`, `/pdf/validate`** (the
> `NEW_ARCHITECTURE.md` section 9 RT-5 row, and its section 4 sequence diagram: `POST
> /pdf/widgets (the bytes)` in, `every widget: name, type, page, rect, on-states` out). Every
> route takes the PDF itself, never a form id, because the service holds no catalogue to look
> one up in.
>
> **A second simplification, discovered only once the RT-1 to RT-4 code existed to read.**
> `field_map.dump_widgets`, `fill_form.fill`, and `sign_form.sign_pdf`/`signature_fields` are
> already bytes-in, bytes-out; none of them writes to or reads from disk except
> `sign_form.build_signer`, which persists the signing certificate under `cert_dir` (a
> long-lived credential, not per-request data). The service therefore needs **no work
> directory and no per-request temporary file**, which the 2026-07-29 plan assumed it would
> (its `Settings.work_dir` and its file-cleanup tests). Removed below.
>
> Everything else in the 2026-07-29 draft that this block does not contradict still stands:
> the fail-fast shared secret, the constant-time compare, no CORS, the `127.0.0.1`
> development bind, no AGPL in the image, and the test asserting that no field value is ever
> logged. Where this correction and an older paragraph below disagree, this correction wins.

**Architecture:** `deploy/form-service/` is a FastAPI application that imports the
`form-service` skill scripts as a library and adds nothing but transport. Every route except
`GET /health` requires a constant-time-compared `X-Form-Service-Key` header; the service
refuses to start when the secret is unset or under 32 characters, so there is no accidental
open deployment. Every route accepts and returns bytes or a small JSON report; nothing is
persisted between requests except the signing certificate. The image carries no AGPL
dependency. `deploy/docker-compose.yml` runs the service plus a `pgvector/pgvector` Postgres
(needed by RT-7, unrelated to the form path) and a Caddy front door whose hostname comes from
the environment, so the final host stays undecided by choice.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, `pypdf`, `pyHanko`, `cryptography`, `requests`,
Docker, Docker Compose, Caddy. `httpx` in the test extra for the Starlette test client.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature.
- Docstrings use the repo's extended `Purpose: / Inputs: / Outputs:` block format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[FORM-SERVICE]`. **Never log a field value, a profile, a secret, or a certificate.** Method, path, status, and duration only.
- **Bind `127.0.0.1` in development.** Inside the container the process binds `0.0.0.0` because it is reachable only on the compose network behind Caddy; the published port is bound to `127.0.0.1` on the host. Both facts are stated in the README so neither is a surprise.
- **Shared-secret header on every route except `/health`**, compared with `hmac.compare_digest`. The service exits at startup when `FORM_SERVICE_KEY` is unset or shorter than 32 characters. The secret never appears in a log, an error body, or a compose file (it comes from the environment).
- **No CORS middleware at all.** This is a server-to-server API; a browser never calls it. A wildcard CORS policy on a route that accepts a body is forbidden by `.claude/rules/security.md`.
- **Nothing persisted, nothing logged.** A request body (a PDF, its values) is never written to disk and never appears in a log line, aside from the one-time signing certificate under `cert_dir`.
- Maximum request body size enforced; a malformed or oversized body is rejected before any PDF work.
- Dependencies pinned exactly in `deploy/form-service/requirements.txt`, matching the versions already pinned and audited in `.claude/skills/form-service/scripts/requirements.txt`, then `pip-audit -r deploy/form-service/requirements.txt --strict`. **No AGPL in the image.**
- Offline tests only: the FastAPI test client, with the skill functions patched, so the suite needs no network and no real form.

**Depends on:** RT-4 (`feat/form-service-signer`), which depends on RT-3, RT-2, RT-1. All four delivered 2026-08-31.

---

## Task 0: Rename the branch to match `NEW_ARCHITECTURE.md`

**Files:** none; this is a git operation.

- [ ] **Step 1: Rename the local and remote branch**

```bash
git branch -m feat/uqac-forms-service feat/form-service
```

The remote still carries the old name from before the branch was rebased; the corrected
history is pushed under the new name in Task 5, with `git push origin :feat/uqac-forms-service`
deleting the stale remote branch once the new one is up.

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

- `.claude/skills/form-service/scripts/sign_form.py` - add `validate_signatures`.
- `.claude/skills/form-service/scripts/Test/test_sign_form.py` - test it.
- `.claude/skills/form-service/SKILL.md` - a section pointing at the service.
- `.claude/rules/testing.md` - the new offline test command.
- `.gitignore` - ignore `deploy/.env`.
- `README.md`, `Architecture.md`, `NEW_ARCHITECTURE.md` - record delivery (Task 5).

---

## Interfaces consumed

From RT-2 `field_map.py`: `dump_widgets(pdf: str | bytes) -> list[dict]`.
From RT-3 `fill_form.py`: `fill(pdf_bytes: bytes, values: dict[str, str], flatten_fields: list[str] | None = None) -> bytes`, raising `FillError`.
From RT-4 `sign_form.py`: `signature_fields(pdf) -> list[dict]`, `build_signer(provider, **options) -> Signer`, `sign_pdf(pdf_bytes, signer, field_name=None, reason=...) -> bytes`, `DEFAULT_REASON`, raising `SigningError`. This plan adds `validate_signatures(pdf) -> list[dict]` to the same module (Task 1a), since it needs the same pyHanko import surface `signature_fields` already has.

---

## Task 1: Configuration and the shared-secret gate

**Files:**

- Create: `deploy/form-service/app/__init__.py`, `deploy/form-service/app/config.py`, `deploy/form-service/app/security.py`
- Create: `deploy/form-service/requirements.txt`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `class Settings` with `service_key: str`, `cert_dir: str`, `signing_provider: str`, `max_body_bytes: int`. No `cache_dir`, `maps_dir`, or `work_dir`: nothing in this service reads a map or writes a scratch file (see the 2026-09-25 correction above).
  - `load_settings(env: Mapping[str, str] | None = None) -> Settings`, raising `RuntimeError` when `FORM_SERVICE_KEY` is unset or shorter than 32 characters.
  - `require_service_key(x_form_service_key: str = Header(...)) -> None`, a FastAPI dependency raising `HTTPException(401)` on a mismatch, compared with `hmac.compare_digest`.

- [ ] **Step 1: Write the failing test**

Create `deploy/form-service/tests/test_api.py`:

```python
"""
test_api.py - Offline unit tests for the form-service HTTP API.

No network, no real form, no certificate authority: the skill functions are
patched and the FastAPI test client drives the app in-process. Run with the
project Python from the repo root:
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

    def test_cert_dir_comes_from_the_environment_with_a_default(self) -> None:
        settings = config.load_settings({"FORM_SERVICE_KEY": VALID_KEY,
                                         "FORM_SERVICE_CERT_DIR": "/data/certs"})
        self.assertEqual(settings.cert_dir, "/data/certs")

    def test_a_default_environment_still_has_a_cert_dir(self) -> None:
        settings = config.load_settings({"FORM_SERVICE_KEY": VALID_KEY})
        self.assertTrue(settings.cert_dir)


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

Create `deploy/form-service/requirements.txt`, matching the versions already pinned and
audited in `.claude/skills/form-service/scripts/requirements.txt`:

```
# form-service image. Pinned exactly, audited with:
#   pip-audit -r deploy/form-service/requirements.txt --strict
#
# Licence floor: the image must carry NO AGPL dependency, because it is
# deployed. pypdf is BSD-3 and pyHanko is MIT; PyMuPDF (AGPL-3.0) stays isolated
# in the extract-statistic skill and is never installed here.
fastapi==0.141.1
uvicorn==0.54.0
pypdf==6.16.1
pyHanko==0.37.0
cryptography==46.0.7
requests==2.34.2

# Test extra: the Starlette test client needs httpx. Installed in the test
# environment only, never in the runtime image.
# httpx==0.28.1
```

- [ ] **Step 4: Write the minimal implementation**

Create `deploy/form-service/app/__init__.py` (empty file).

Create `deploy/form-service/app/config.py`:

```python
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
```

Create `deploy/form-service/app/security.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 10 tests.

- [ ] **Step 6: Commit**

```bash
git add deploy/form-service/app deploy/form-service/requirements.txt deploy/form-service/tests
git commit -m "feat(form-service): fail-fast configuration and constant-time shared-secret gate"
```

---

## Task 1a: `validate_signatures` in the signing module

RT-4 shipped `signature_fields` (who is signed) but nothing that reports whether a signature
verifies. `POST /pdf/validate` needs that, and the pyHanko import surface belongs with the
rest of the signing module rather than duplicated in the HTTP layer.

**Files:**

- Modify: `.claude/skills/form-service/scripts/sign_form.py`
- Modify: `.claude/skills/form-service/scripts/Test/test_sign_form.py`

**Interfaces:**

- Produces: `validate_signatures(pdf: str | bytes) -> list[dict[str, Any]]`, one entry per
  embedded signature: `{"field", "intact", "valid", "trusted"}`.

- [ ] **Step 1: Write the failing test**

Append to `TestThreeSignatureChain` in `test_sign_form.py`:

```python
    def test_validate_signatures_reports_intact_valid_and_untrusted(self) -> None:
        report = sign_form.validate_signatures(self.signed_three_times())
        self.assertEqual(len(report), 3)
        for entry in report:
            self.assertTrue(entry["intact"], entry["field"])
            self.assertTrue(entry["valid"], entry["field"])
            self.assertFalse(entry["trusted"],
                             f"{entry['field']}: a development signature must never "
                             "report as trusted")

    def test_validate_signatures_on_an_unsigned_document_is_empty(self) -> None:
        pdf = form_with_signature_fields(THREE)
        self.assertEqual(sign_form.validate_signatures(pdf), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/form-service/scripts/Test/test_sign_form.py`
Expected: FAIL with `AttributeError: module 'sign_form' has no attribute 'validate_signatures'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `sign_form.py`, after `signature_fields`:

```python
def validate_signatures(pdf: str | bytes) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the validation status of every embedded signature: whether the
        signed bytes are intact, whether the signature verifies, and whether it
        chains to a trusted authority. The three are kept apart rather than
        collapsed into one pass/fail, because a self-signed development
        signature is intact and valid and must still never be presented as one
        an institutional office has accepted.

    Inputs:
        pdf (str | bytes): a path, or the PDF body

    Outputs:
        report (list[dict]): one entry per embedded signature, each with
            field, intact, valid and trusted. Empty when the document carries
            no signature at all.
    --------------------------------------------------------------------------
    """
    from pyhanko.sign.validation import validate_pdf_signature

    body = pdf if isinstance(pdf, (bytes, bytearray)) else open(pdf, "rb").read()
    reader = PdfFileReader(io.BytesIO(body), strict=False)
    report: list[dict[str, Any]] = []
    for embedded in reader.embedded_signatures:
        status_ = validate_pdf_signature(embedded)
        report.append({
            "field": embedded.field_name,
            "intact": bool(status_.intact),
            "valid": bool(status_.valid),
            "trusted": bool(status_.trusted),
        })
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/form-service/scripts/Test/test_sign_form.py`
Expected: PASS, every prior test plus the 2 new ones.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/form-service/scripts/sign_form.py .claude/skills/form-service/scripts/Test/test_sign_form.py
git commit -m "feat(form-service): validate_signatures reports intact, valid and trusted separately"
```

---

## Task 2: The skill bridge

**Files:**

- Create: `deploy/form-service/app/skill_bridge.py`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: `field_map`, `fill_form`, `sign_form` from RT-2 to RT-4 plus Task 1a.
- Produces:
  - `widgets_of(pdf_bytes: bytes) -> list[dict[str, Any]]`.
  - `fill_to_bytes(pdf_bytes: bytes, values: dict[str, str], flatten_fields: list[str], settings: Settings) -> tuple[bytes, dict[str, Any]]` returning the filled PDF and a small result summary.
  - `sign_bytes(pdf_bytes: bytes, field_name: str | None, reason: str, settings: Settings) -> tuple[bytes, dict[str, Any]]`.
  - `validate_bytes(pdf_bytes: bytes) -> list[dict[str, Any]]`.

Every function is bytes-in, bytes-out, and none of them touches disk except `sign_bytes`
building the signer from `settings.cert_dir`. This module is the only place that imports the
skill scripts, so the routes stay pure transport and the tests patch one seam.

- [ ] **Step 1: Write the failing test**

Append to `deploy/form-service/tests/test_api.py`, above the `if __name__` block:

```python
class TestSkillBridge(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from app import skill_bridge
        self.bridge = skill_bridge
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = config.load_settings({
            "FORM_SERVICE_KEY": VALID_KEY,
            "FORM_SERVICE_CERT_DIR": os.path.join(self.tmp.name, "certs"),
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_widgets_of_delegates_to_field_map(self) -> None:
        self.bridge.field_map.dump_widgets = lambda pdf: [{"name": "Champ1"}]
        self.assertEqual(self.bridge.widgets_of(b"%PDF-1.7\n"), [{"name": "Champ1"}])

    def test_fill_to_bytes_returns_the_pdf_and_the_counts(self) -> None:
        self.bridge.fill_form.fill = lambda pdf_bytes, values, flatten_fields=None: (
            b"%PDF-1.7\nfilled\n%%EOF")
        body, result = self.bridge.fill_to_bytes(
            b"%PDF-1.7\n", {"student.nom": "X"}, [], self.settings)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(result["filled"], 1)
        self.assertEqual(result["flattened"], 0)

    def test_validate_bytes_delegates_to_sign_form(self) -> None:
        self.bridge.sign_form.validate_signatures = lambda pdf: [
            {"field": "Signature_directeur", "intact": True, "valid": True, "trusted": False}]
        report = self.bridge.validate_bytes(b"%PDF-1.7\n")
        self.assertEqual(report[0]["field"], "Signature_directeur")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_api.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.skill_bridge'`.

- [ ] **Step 3: Write the minimal implementation**

Create `deploy/form-service/app/skill_bridge.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add deploy/form-service/app/skill_bridge.py deploy/form-service/tests/test_api.py
git commit -m "feat(form-service): bytes-in bytes-out skill bridge, no work directory needed"
```

---

## Task 3: The API

**Files:**

- Create: `deploy/form-service/app/main.py`
- Test: `deploy/form-service/tests/test_api.py`

**Interfaces:**

- Consumes: `load_settings`, `require_service_key`, and the whole skill bridge.
- Produces the HTTP contract TT-3 codes against:

| Method and path | Request | Success | Failure |
|---|---|---|---|
| `GET /health` | none | `200 {"status": "ok"}` | - |
| `POST /pdf/widgets` | body: raw PDF, `Content-Type: application/pdf` | `200 {"widgets": [...]}` | `401`, `413`, `422` |
| `POST /pdf/fill` | `multipart/form-data`: `pdf` (file), `values` (JSON object string), `flatten_fields` (JSON array string, optional) | `200 application/pdf`, headers `X-Form-Filled`, `X-Form-Flattened` | `401`, `409` already signed, `413`, `422` unknown field or bad checkbox value or malformed JSON |
| `POST /pdf/sign` | body: raw PDF, `Content-Type: application/pdf`; query `field` (optional), `reason` (optional) | `200 application/pdf`, header `X-Form-Signature-Field` | `401`, `409` nothing signable, already signed, or ambiguous; `413`, `422` |
| `POST /pdf/validate` | body: raw PDF, `Content-Type: application/pdf` | `200 {"signatures": [{field, intact, valid, trusted}]}` | `401`, `413`, `422` |

`multipart/form-data` is used only for `/pdf/fill`, the one route that needs both a PDF and
structured data in the same request; the other three routes take the PDF as the whole body,
matching `NEW_ARCHITECTURE.md` section 4's own phrasing ("`POST /pdf/widgets` (the bytes)").
This choice has not been confirmed with the ThesisTracker side; say so in the pull request
body per this plan's own Task 5.

- [ ] **Step 1: Write the failing test**

Append to `deploy/form-service/tests/test_api.py`, above the `if __name__` block:

```python
import json  # noqa: E402


class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FORM_SERVICE_KEY"] = VALID_KEY
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FORM_SERVICE_CERT_DIR"] = os.path.join(self.tmp.name, "certs")

        from fastapi.testclient import TestClient
        from app import main, skill_bridge

        self.bridge = skill_bridge
        self.client = TestClient(main.app)
        self.headers = {"X-Form-Service-Key": VALID_KEY}

        self._real = {
            "widgets_of": skill_bridge.widgets_of,
            "fill_to_bytes": skill_bridge.fill_to_bytes,
            "sign_bytes": skill_bridge.sign_bytes,
            "validate_bytes": skill_bridge.validate_bytes,
        }
        skill_bridge.widgets_of = lambda pdf: [
            {"name": "Champ1", "type": "text", "page": 1}]
        skill_bridge.fill_to_bytes = lambda pdf, values, flatten_fields, settings: (
            b"%PDF-1.7\nfilled\n%%EOF", {"filled": len(values), "flattened": len(flatten_fields)})
        skill_bridge.sign_bytes = lambda pdf, field, reason, settings: (
            b"%PDF-1.7\nfilled\n%%EOF-signed", {"field": field or "Signature_directeur"})
        skill_bridge.validate_bytes = lambda pdf: [
            {"field": "Signature_directeur", "intact": True, "valid": True, "trusted": False}]

    def tearDown(self) -> None:
        self.bridge.widgets_of = self._real["widgets_of"]
        self.bridge.fill_to_bytes = self._real["fill_to_bytes"]
        self.bridge.sign_bytes = self._real["sign_bytes"]
        self.bridge.validate_bytes = self._real["validate_bytes"]
        os.environ.pop("FORM_SERVICE_CERT_DIR", None)
        self.tmp.cleanup()

    def test_health_requires_no_secret(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_every_data_route_rejects_a_missing_key(self) -> None:
        for method, path, kwargs in (
            ("post", "/pdf/widgets", {"content": b"%PDF-1.7\n"}),
            ("post", "/pdf/validate", {"content": b"%PDF-1.7\n"}),
        ):
            response = getattr(self.client, method)(path, **kwargs)
            self.assertEqual(response.status_code, 401, f"{method} {path}")

    def test_a_wrong_key_is_rejected(self) -> None:
        response = self.client.post("/pdf/widgets",
                                    headers={"X-Form-Service-Key": "j" * 48},
                                    content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 401)

    def test_widgets_returns_the_dump(self) -> None:
        response = self.client.post("/pdf/widgets", headers=self.headers,
                                    content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["widgets"][0]["name"], "Champ1")

    def test_widgets_rejects_a_non_pdf_body(self) -> None:
        response = self.client.post("/pdf/widgets", headers=self.headers,
                                    content=b"not a pdf")
        self.assertEqual(response.status_code, 422)

    def test_widgets_rejects_an_oversized_body(self) -> None:
        os.environ["FORM_SERVICE_MAX_BODY_BYTES"] = "10"
        try:
            response = self.client.post("/pdf/widgets", headers=self.headers,
                                        content=b"%PDF-1.7\n" + b"x" * 100)
            self.assertEqual(response.status_code, 413)
        finally:
            os.environ.pop("FORM_SERVICE_MAX_BODY_BYTES", None)

    def test_fill_returns_a_pdf_with_the_counts_in_headers(self) -> None:
        response = self.client.post(
            "/pdf/fill", headers=self.headers,
            files={"pdf": ("form.pdf", b"%PDF-1.7\n", "application/pdf")},
            data={"values": json.dumps({"student.nom": "X"}),
                 "flatten_fields": json.dumps(["student.nom"])})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.headers["x-form-filled"], "1")
        self.assertEqual(response.headers["x-form-flattened"], "1")

    def test_fill_rejects_malformed_values_json(self) -> None:
        response = self.client.post(
            "/pdf/fill", headers=self.headers,
            files={"pdf": ("form.pdf", b"%PDF-1.7\n", "application/pdf")},
            data={"values": "not json"})
        self.assertEqual(response.status_code, 422)

    def test_fill_maps_an_unknown_field_to_422(self) -> None:
        import fill_form

        def refuse(*args, **kwargs):
            raise fill_form.FillError("no such field in this PDF: 'Nope'")
        self.bridge.fill_to_bytes = lambda pdf, values, flatten_fields, settings: refuse()
        response = self.client.post(
            "/pdf/fill", headers=self.headers,
            files={"pdf": ("form.pdf", b"%PDF-1.7\n", "application/pdf")},
            data={"values": json.dumps({"Nope": "X"})})
        self.assertEqual(response.status_code, 422)

    def test_sign_returns_the_signed_pdf_and_names_the_field(self) -> None:
        response = self.client.post("/pdf/sign", headers=self.headers,
                                    content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-form-signature-field"], "Signature_directeur")

    def test_sign_maps_a_signing_refusal_to_409(self) -> None:
        import sign_form

        def refuse(*args, **kwargs):
            raise sign_form.SigningError("no signature field")
        self.bridge.sign_bytes = refuse
        response = self.client.post("/pdf/sign", headers=self.headers,
                                    content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 409)

    def test_validate_returns_the_report(self) -> None:
        response = self.client.post("/pdf/validate", headers=self.headers,
                                    content=b"%PDF-1.7\n")
        self.assertEqual(response.status_code, 200)
        entry = response.json()["signatures"][0]
        self.assertTrue(entry["valid"])
        self.assertFalse(entry["trusted"])

    def test_no_cors_middleware_is_installed(self) -> None:
        from app import main
        names = [m.cls.__name__ for m in main.app.user_middleware]
        self.assertNotIn("CORSMiddleware", names)

    def test_no_field_value_reaches_the_log(self) -> None:
        from app import main
        with self.assertLogs(main.logger, level="INFO") as captured:
            self.client.post(
                "/pdf/fill", headers=self.headers,
                files={"pdf": ("form.pdf", b"%PDF-1.7\n", "application/pdf")},
                data={"values": json.dumps({"student.code_permanent": "TREM99010199"})})
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
main.py - The form-service HTTP API.

Pure transport: every decision lives in the form-service skill, reached
through skill_bridge. Every route except /health requires the shared secret.
There is no CORS middleware, because a browser never calls this API and a
wildcard policy on a route that accepts a body is forbidden by
.claude/rules/security.md.

Nothing here logs a field value, a profile, or the secret: method, path,
status, and duration only.
"""

import json
import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from . import skill_bridge
from .config import load_settings
from .security import require_service_key

logger = logging.getLogger(__name__)

app = FastAPI(title="form-service", version="1.0.0", docs_url=None, redoc_url=None)


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
    """Read a raw PDF request body, enforcing the size cap before any PDF work."""
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


def _parse_json_field(raw: str, name: str) -> Any:
    """Parse a form field that carries JSON, mapping a bad payload to 422."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{name} is not valid JSON: {exc}") from exc


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness probe. The only route with no shared-secret requirement."""
    return JSONResponse(content={"status": "ok"})


@app.post("/pdf/widgets", dependencies=[Depends(require_service_key)])
async def widgets(request: Request) -> dict[str, Any]:
    """List every AcroForm widget in the uploaded PDF."""
    body = await _pdf_body(request)
    return {"widgets": skill_bridge.widgets_of(body)}


@app.post("/pdf/fill", dependencies=[Depends(require_service_key)])
async def fill(pdf: UploadFile = File(...), values: str = Form(...),
              flatten_fields: str = Form(default="[]")) -> Response:
    """Fill an uploaded form and stream the PDF back. Counts travel in headers."""
    settings = load_settings()
    body = await pdf.read()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Request body exceeds the configured maximum")
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Body is not a PDF")

    parsed_values = _parse_json_field(values, "values")
    parsed_flatten = _parse_json_field(flatten_fields, "flatten_fields")

    try:
        filled, result = skill_bridge.fill_to_bytes(body, parsed_values, parsed_flatten, settings)
    except skill_bridge.fill_form.FillError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return Response(content=filled, media_type="application/pdf", headers={
        "X-Form-Filled": str(result["filled"]),
        "X-Form-Flattened": str(result["flattened"]),
    })


@app.post("/pdf/sign", dependencies=[Depends(require_service_key)])
async def sign(request: Request, field: str | None = None,
              reason: str | None = None) -> Response:
    """Sign an uploaded filled form and stream the signed PDF back."""
    body = await _pdf_body(request)
    settings = load_settings()
    chosen_reason = reason or skill_bridge.sign_form.DEFAULT_REASON
    try:
        signed, result = skill_bridge.sign_bytes(body, field, chosen_reason, settings)
    except skill_bridge.sign_form.SigningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return Response(content=signed, media_type="application/pdf", headers={
        "X-Form-Signature-Field": str(result["field"]),
    })


@app.post("/pdf/validate", dependencies=[Depends(require_service_key)])
async def validate(request: Request) -> dict[str, Any]:
    """Report the validation status of every signature in the uploaded PDF."""
    body = await _pdf_body(request)
    return {"signatures": skill_bridge.validate_bytes(body)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_api.py`
Expected: PASS, 26 tests.

- [ ] **Step 5: Commit**

```bash
git add deploy/form-service/app/main.py deploy/form-service/tests/test_api.py
git commit -m "feat(form-service): widgets, fill, sign and validate routes behind the shared secret"
```

---

## Task 4: Container and compose

**Files:**

- Create: `deploy/form-service/Dockerfile`, `deploy/form-service/.dockerignore`, `deploy/form-service/README.md`
- Create: `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/initdb/01-pgvector.sql`, `deploy/.env.example`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: the application from Tasks 1 to 3.
- Produces: a runnable stack. Service reachable at `http://127.0.0.1:8081` locally and behind Caddy at `${FORM_SERVICE_HOST}` on a real host; Postgres at `db:5432` with the `vector` extension available, which **RT-7 consumes** as its pgvector store. The form service has no data volume of its own beyond the signing certificate.

- [ ] **Step 1: Write the Dockerfile**

Create `deploy/form-service/Dockerfile`:

```dockerfile
# form-service. No AGPL dependency ships in this image.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SKILL_SCRIPTS_DIR=/opt/form-service/scripts

WORKDIR /srv

COPY deploy/form-service/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

# The skill is the library; the service is the transport.
COPY .claude/skills/form-service/scripts /opt/form-service/scripts
COPY deploy/form-service/app /srv/app

# Non-root, and one data directory: the signing certificate only.
RUN useradd --system --create-home --uid 10001 formsvc \
    && mkdir -p /data/certs \
    && chown -R formsvc:formsvc /data /srv
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
# form engine stack. Host-agnostic by design: every hostname and secret comes
# from the environment, so the final Docker host is chosen before real data
# loads and not before build. Copy deploy/.env.example to deploy/.env.
services:
  form-service:
    build:
      context: ..
      dockerfile: deploy/form-service/Dockerfile
    environment:
      FORM_SERVICE_KEY: ${FORM_SERVICE_KEY:?set FORM_SERVICE_KEY in deploy/.env}
      FORM_SERVICE_CERT_DIR: /data/certs
      FORM_SERVICE_SIGNING_PROVIDER: ${FORM_SERVICE_SIGNING_PROVIDER:-self-signed}
    volumes:
      - form-certs:/data/certs
    ports:
      # Published on the loopback interface only, never on 0.0.0.0.
      - "127.0.0.1:8081:8080"
    restart: unless-stopped

  db:
    # pgvector rides the Postgres the stack already needs; RT-7 stores its
    # corpus embeddings here, so no separate vector vendor is introduced. It
    # is unrelated to the form path.
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
  form-certs:
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

# Postgres (pgvector). RT-7 stores corpus embeddings in this database, unrelated
# to the form path.
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
# form-service

Transport for the `form-service` skill: fill, sign, and validate PDF forms over
HTTP, so ThesisTracker calls one service instead of shelling out to Python. The
service holds no catalogue: which forms exist and what their fields mean is
ThesisTracker's own record (TT-8/TT-9).

## Run it locally, no Docker

```bash
export FORM_SERVICE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export FORM_SERVICE_CERT_DIR=out/form-service/certs
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

| Method and path | Request | Returns |
|---|---|---|
| `GET /health` | none | `{"status": "ok"}` |
| `POST /pdf/widgets` | raw PDF body | `{"widgets": [{name, name_hex, type, page, rect, on_states, readonly}]}` |
| `POST /pdf/fill` | `multipart/form-data`: `pdf` file, `values` JSON object, `flatten_fields` JSON array (optional) | `application/pdf`, headers `X-Form-Filled`, `X-Form-Flattened` |
| `POST /pdf/sign` | raw PDF body; query `field`, `reason` (both optional) | `application/pdf`, header `X-Form-Signature-Field` |
| `POST /pdf/validate` | raw PDF body | `{"signatures": [{field, intact, valid, trusted}]}` |

Status codes: `401` no or wrong key, `409` a signing refusal (nothing signable,
already signed, or ambiguous which field), `413` body over the cap, `422` not a
PDF or a fill refusal (unknown field, bad checkbox value, malformed JSON).

## Personal information

The service never persists a request body and never logs a field value. Nothing
is stored between requests, aside from the signing certificate.

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
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/pdf/widgets   # expect 401
docker compose -f deploy/docker-compose.yml exec db psql -U uqac -d uqac -c "SELECT extname FROM pg_extension WHERE extname='vector';"
docker compose -f deploy/docker-compose.yml down
```

Expected: `/health` returns `{"status":"ok"}`, the unauthenticated call returns `401`, and the
`psql` query returns one row named `vector`. **Not run in this environment**: no Docker
daemon is available in the sandbox this plan was executed in; state this explicitly rather
than claiming it passed.

- [ ] **Step 5: Audit the image dependencies**

```powershell
pip-audit -r deploy/form-service/requirements.txt --strict
```

Expected: no vulnerabilities. Cite any `CVE-YYYY-NNNNN` and its fixed version in a comment
above the bumped pin.

- [ ] **Step 6: Update SKILL.md and the rules**

Add to `.claude/skills/form-service/SKILL.md`:

```markdown
## HTTP service

`deploy/form-service/` wraps this skill in a FastAPI application so another
application (ThesisTracker) can fill, sign, and validate PDFs without shelling
out to Python. Every route except `/health` requires a shared-secret header,
the service refuses to start without one, and no field value is ever logged or
persisted. See `deploy/form-service/README.md` for the endpoint table and the
run commands.
```

Add to `.claude/rules/testing.md`:

```powershell
python deploy/form-service/tests/test_api.py   # configuration, secret gate, skill bridge, routes (needs httpx)
```

- [ ] **Step 7: Run the full offline suite**

```powershell
python deploy/form-service/tests/test_api.py
python .claude/skills/form-service/scripts/Test/test_sign_form.py
python .claude/skills/form-service/scripts/Test/test_fill_form.py
python .claude/skills/form-service/scripts/Test/test_field_map.py
python .claude/skills/form-service/scripts/Test/test_pdf_ingest.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add deploy .claude/skills/form-service/SKILL.md .claude/rules/testing.md .gitignore
git commit -m "feat(form-service): container, compose with pgvector Postgres, and Caddy front door"
```

---

## Interfaces published by RT-5

**HTTP contract, consumed by TT-3:** the endpoint table in Task 3. Header names, status
codes, and the `X-Form-*` response headers are the contract; TT-3 codes against them and its
injected-fetch tests assert them. **The multipart-vs-raw-body split has not been confirmed
with TT-3 and must be before either unit ships**, per this plan's own Task 3 note.

**For RT-6:** the same FastAPI application. RT-6 adds `GET /publications` to `app/main.py`,
reuses `require_service_key`, and adds its own module next to `skill_bridge.py`.

**For RT-7:** the `db` service of `deploy/docker-compose.yml`, a `pgvector/pgvector:pg17`
Postgres with the `vector` extension created by `deploy/initdb/01-pgvector.sql`, reachable at
`db:5432` on the compose network and `127.0.0.1:5433` on the host.

**Environment variables:** `FORM_SERVICE_KEY` (required, 32 characters minimum),
`FORM_SERVICE_CERT_DIR`, `FORM_SERVICE_SIGNING_PROVIDER`, `FORM_SERVICE_MAX_BODY_BYTES`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `FORM_SERVICE_HOST`.

---

## Acceptance

```powershell
python deploy/form-service/tests/test_api.py
python .claude/skills/form-service/scripts/Test/test_sign_form.py
pip-audit -r deploy/form-service/requirements.txt --strict
```

Plus the RT-1 through RT-4 suites, which must stay green. The Docker/compose acceptance
commands in Task 4 Step 4 need a Docker daemon this plan's execution environment did not
have; report that gap rather than claiming it passed.

---

## Task 5: Documentation and the pull request

Run this after the acceptance block above passes. It is the last task of the unit, and it is
what makes the work reviewable by someone who was not here.

**Files:**

- Modify: `README.md`
- Modify: `Architecture.md`
- Modify: `NEW_ARCHITECTURE.md`

**Interfaces:**

- Consumes: the finished implementation of every task above.
- Produces: the inventories a reader needs, and one pull request per unit so nothing reaches
  `main` unreviewed.

- [ ] **Step 1: Update `README.md`**

1. A `### Deployment` subsection, or a paragraph in the existing deployment area, naming
   `deploy/form-service/` as the containerized transport over the `form-service` skill, and
   pointing at `deploy/form-service/README.md` for the endpoint table and the run commands.
2. In the Prerequisites table, a row for Docker and Docker Compose, needed only for the
   service, never for the skill itself.
3. In the File-Locations tree, a `deploy/` branch listing `form-service/` (app, Dockerfile,
   requirements, tests), `docker-compose.yml`, `Caddyfile`, `initdb/01-pgvector.sql`, and
   `.env.example`.
4. One sentence on the security posture: every route except `/health` requires a
   shared-secret header, the service refuses to start without one, there is no CORS
   middleware, and no field value is ever logged or persisted.

- [ ] **Step 2: Update `Architecture.md`**

Add a short section after the existing layers, with its own mermaid diagram, showing the
service, the `pgvector` Postgres, and the Caddy front door, and stating the two properties
that matter: the service is reached over a private network with a shared secret, and the
image carries no AGPL dependency because PyMuPDF stays isolated in the `extract-statistic`
skill.

Add one line naming the consumer: ThesisTracker calls this service, and the dependency runs
one way only. Do not draw ThesisTracker into the Layer 1 graph; it is a separate system, and
`NEW_ARCHITECTURE.md` is where the two meet.

- [ ] **Step 3: Update `NEW_ARCHITECTURE.md`**

`NEW_ARCHITECTURE.md` is committed identically to `main` in both ResearchTools and
ThesisTracker. Edit only what this unit owns, and keep the wording identical in both
checkouts so the two copies never drift.

1. In the section 9 unit table, append ` Delivered <YYYY-MM-DD>.` to the **RT-5** row's
   deliverable cell.
2. Verify section 4's runtime topology diagram (the `form-service` node, its `:8080` port,
   its `certs` volume) against the delivered compose file.
3. Section 10's security table names `config.load_settings` and `security.keys_match`:
   confirm both exist and behave as stated, and add the new `RT-5, asserted by test` row for
   `validate_signatures` reporting intact, valid and trusted separately.

The change must land in both repositories. After committing it here, copy the same file into
the other checkout and open a second, documentation-only pull request there, or fold it into
that repository's next unit pull request. Verify the two copies match:

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

`gh` is **not installed** on this machine, and `GITHUB_TOKEN` carries `read:user` only, so
neither the CLI nor that token can open a pull request. Do not try to install `gh`. The OAuth
token in the Windows Credential Manager has `repo` scope and is sufficient. Retrieve it per
command: never write it to a file, never echo it, never commit it.

```bash
git push -u origin feat/form-service

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
  "title": "[RT-5] form-service: stateless HTTP API for widgets, fill, sign, validate",
  "head": "feat/form-service",
  "base": "main",
  "body": "Closes #8\n\n<what the unit delivers, in three or four lines>\n\n**Depends on.** RT-4 (`feat/form-service-signer`), and the whole RT-1 to RT-4 chain behind it.\n\n**Needs confirmation with ThesisTracker (TT-3).** /pdf/fill uses multipart/form-data (a pdf file plus values and flatten_fields as JSON form fields); the other three routes take the raw PDF as the whole body. This has not been agreed with the TT-3 side.\n\n**Acceptance run.** <paste the commands from the acceptance block and their real result, not a summary; the Docker/compose commands were not run, no Docker daemon in this environment>\n\n**Reviewer must check by hand.** The Docker/compose stack end to end, since it was not run here."
}
```

If a permission classifier blocks the command that reads the token, open the pull request in
the browser instead and paste the same title and body:

```
https://github.com/LARi-UQAC/ResearchTools/compare/main...feat/form-service?expand=1
```

Then delete `pr-body.json` from the scratchpad.

**Do not merge your own pull request.** Merging to `main` is the human gate. RT-6, RT-7, TT-3
and TT-5 are all blocked behind this unit. It is the widest dependency of the project; say so
in the body.

- [ ] **Step 7: Report**

State the pull request URL, the acceptance commands you ran with their real output, and
anything you could not verify. A test you did not run is not a test that passed.
