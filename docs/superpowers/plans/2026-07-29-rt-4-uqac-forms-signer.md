# RT-4: UQAC Form Signer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sign a filled UQAC form cryptographically as a PAdES incremental update, behind a pluggable `Signer` protocol whose shipped implementation is a self-signed development signer, so the whole pipeline is usable while the question of what UQAC actually accepts stays open.

**Architecture:** `sign_form.py` defines a one-method `Signer` protocol, `sign(pdf_bytes, field_name, reason) -> bytes`. The shipped `SelfSignedSigner` builds a throwaway certificate with `pyhanko` plus `cryptography` at test time, into the scratchpad, and signs with PAdES. Configuration selects the provider, so a UQAC PKI or a Notarius provider drops in later without touching any caller. The ordering rule of the whole engine is enforced here rather than documented: signing refuses a document with no signature field, and refuses a document already carrying a signature it would invalidate. The certificate is never committed, and no key material ever reaches a log.

**Tech Stack:** Python 3.13, `pyhanko` (MIT), `cryptography`, `pypdf` (BSD-3, for the pre-flight inspection), standard library.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming: classes `PascalCase`, functions and module variables `snake_case`, private `_snake_case`, constants `UPPER_SNAKE_CASE`. Type hints in every signature.
- Docstrings use the repo's extended `Purpose: / Inputs: / Outputs:` block format.
- Logging: `logging.getLogger(__name__)`, messages prefixed `[UQAC-FORMS]`. **Never log key material, a passphrase, a certificate body, or a field value.**
- **Order is fill, appearances, flatten non-signature fields, sign LAST as an incremental update.** Flattening destroys signature fields, so this module never re-writes the whole document; it appends.
- **No AGPL in this skill**: `pyhanko` is MIT and `pypdf` is BSD-3. PyMuPDF stays isolated in `extract-statistic`.
- **All fixtures synthetic.** The development certificate is generated into the scratchpad at test time and is never committed. `.gitignore` must cover it.
- Dependencies pinned exactly, then `pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict`.
- Offline tests only: certificate generation is local, and no timestamp authority is contacted by default.
- **Unverified, and stated as such in `SKILL.md`:** whether the Decanat des etudes and the Service des ressources financieres accept a PAdES signature is not confirmed. The self-signed default is a development default, not a submission-ready credential.

**Depends on:** RT-3 (`feat/uqac-forms-filler`), which depends on RT-2 and RT-1.

---

## File Structure

**New files**

- `.claude/skills/uqac-forms/scripts/sign_form.py` - `Signer` protocol, `SelfSignedSigner`, the signing entry point and its pre-flight checks.
- `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py` - offline unit tests.

**Modified files**

- `.claude/skills/uqac-forms/scripts/requirements.txt` - add the `pyhanko` and `cryptography` pins.
- `.claude/skills/uqac-forms/SKILL.md` - the signing workflow, the ordering rule, the unverified-acceptance disclosure.
- `.claude/rules/testing.md` - the new offline test command.
- `.gitignore` - ignore any generated certificate or key.

---

## Interfaces consumed

From RT-1 `form_registry.py`: `require_fresh_map(form_id, maps_dir)`, `StaleMapError`, `MAPS_DIR`.

From RT-3 `fill_form.py`: `fill(form_id, profile, out_path, cache_dir, maps_dir, flatten, pdf_path) -> dict` with result shape `{"form_id", "out", "filled", "skipped", "flattened"}`, and `READONLY_FLAG`.

---

## Task 1: Pre-flight inspection

**Files:**

- Create: `.claude/skills/uqac-forms/scripts/sign_form.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`

**Interfaces:**

- Consumes: nothing (pure PDF inspection with `pypdf`).
- Produces:
  - `signature_fields(pdf_path: str) -> list[dict[str, Any]]`, one entry per `/Sig` widget: `{"name": str, "page": int, "signed": bool}`. `signed` is True when the widget already carries a `/V`.
  - `class SigningError(RuntimeError)`.
  - `preflight(pdf_path: str, field_name: str | None = None) -> str` returning the name of the signature field that will be used, raising `SigningError` when there is none, when the requested name does not exist, when it is already signed, or when the document offers more than one empty signature field and the caller did not choose.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`:

```python
"""
test_sign_form.py - Offline unit tests for sign_form.py.

No network, no timestamp authority, and no committed certificate: the
development certificate is generated in a temporary directory inside the test.
Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sign_form  # noqa: E402

from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject,
)


def _widget(name: str, field_type: str, rect: tuple[float, float, float, float],
            signed: bool = False) -> DictionaryObject:
    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject(field_type),
        NameObject("/T"): TextStringObject(name),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
    })
    if signed:
        annot[NameObject("/V")] = DictionaryObject()
    return annot


def make_pdf(path: str, widgets: list[DictionaryObject]) -> str:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    annots = ArrayObject()
    for widget in widgets:
        annots.append(writer._add_object(widget))
    page[NameObject("/Annots")] = annots
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


class TestPreflight(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _pdf(self, widgets: list[DictionaryObject]) -> str:
        return make_pdf(os.path.join(self.tmp.name, "doc.pdf"), widgets)

    def test_one_empty_signature_field_is_chosen_automatically(self) -> None:
        pdf = self._pdf([_widget("Nom", "/Tx", (10, 700, 200, 720)),
                         _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))])
        self.assertEqual(sign_form.preflight(pdf), "Signature_directeur")

    def test_a_document_with_no_signature_field_is_refused(self) -> None:
        pdf = self._pdf([_widget("Nom", "/Tx", (10, 700, 200, 720))])
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.preflight(pdf)
        self.assertIn("no signature field", str(ctx.exception))

    def test_an_already_signed_field_is_refused(self) -> None:
        pdf = self._pdf([_widget("Signature_directeur", "/Sig", (300, 100, 500, 160), signed=True)])
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.preflight(pdf, "Signature_directeur")
        self.assertIn("already signed", str(ctx.exception))

    def test_two_empty_fields_require_an_explicit_choice(self) -> None:
        pdf = self._pdf([_widget("Signature_etudiant", "/Sig", (10, 100, 200, 160)),
                         _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))])
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.preflight(pdf)
        self.assertIn("Signature_etudiant", str(ctx.exception))
        self.assertIn("Signature_directeur", str(ctx.exception))

    def test_an_explicit_choice_resolves_the_ambiguity(self) -> None:
        pdf = self._pdf([_widget("Signature_etudiant", "/Sig", (10, 100, 200, 160)),
                         _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))])
        self.assertEqual(sign_form.preflight(pdf, "Signature_directeur"), "Signature_directeur")

    def test_an_unknown_field_name_is_refused_and_lists_the_real_ones(self) -> None:
        pdf = self._pdf([_widget("Signature_directeur", "/Sig", (300, 100, 500, 160))])
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.preflight(pdf, "Signature_doyen")
        self.assertIn("Signature_directeur", str(ctx.exception))

    def test_signature_fields_reports_page_and_signed_state(self) -> None:
        pdf = self._pdf([_widget("Signature_directeur", "/Sig", (300, 100, 500, 160), signed=True)])
        fields = sign_form.signature_fields(pdf)
        self.assertEqual(fields, [{"name": "Signature_directeur", "page": 1, "signed": True}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'sign_form'`.

- [ ] **Step 3: Write the minimal implementation**

Create `.claude/skills/uqac-forms/scripts/sign_form.py`:

```python
"""
sign_form.py - Cryptographic signing of a filled UQAC form, as a PAdES
incremental update.

Signing is the LAST step of the pipeline: fill, appearances, flatten the
non-signature fields, then sign. An incremental update appends to the file
rather than rewriting it, which is what keeps the signature verifiable.

The signer is pluggable behind a one-method protocol. The shipped implementation
is a self-signed development signer whose certificate is generated on demand into
a scratchpad and never committed. Whether the Decanat des etudes and the Service
des ressources financieres accept a PAdES signature is UNVERIFIED, so a
production provider (UQAC PKI, or Notarius / ConsignO) is selected by
configuration when that answer arrives.

Nothing here logs key material, a passphrase, a certificate body, or a field
value.

Usage:
  python sign_form.py <filled.pdf> [--field NAME] [--reason TEXT]
                      [--out out/<name>_signe.pdf] [--provider self-signed]
                      [--cert PATH --key PATH [--passphrase-env VAR]]
"""

import argparse
import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

from pypdf import PdfReader

logger = logging.getLogger(__name__)

DEFAULT_REASON = "Approbation du directeur de recherche"


class SigningError(RuntimeError):
    """Raised when a document cannot be signed as requested."""


def signature_fields(pdf_path: str) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the signature widgets of a PDF with their page and whether they
        already carry a signature.

    Inputs:
        pdf_path (str): path to the filled PDF

    Outputs:
        fields (list[dict]): {name, page, signed}, in page then annotation order
    --------------------------------------------------------------------------
    """
    reader = PdfReader(pdf_path)
    found: list[dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        annots = page.get("/Annots") or []
        for ref in annots:
            annot = ref.get_object()
            if str(annot.get("/Subtype") or "") != "/Widget":
                continue
            if str(annot.get("/FT") or "") != "/Sig":
                continue
            title = annot.get("/T")
            if title is None:
                continue
            found.append({
                "name": str(title),
                "page": page_index,
                "signed": annot.get("/V") is not None,
            })
    return found


def preflight(pdf_path: str, field_name: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide which signature field to use, and refuse anything that would
        produce a document nobody can verify: no signature field at all (the
        filler flattened it away, or the form has none), a name that does not
        exist, a field already signed, or an ambiguous choice between several
        empty fields.

    Inputs:
        pdf_path (str): path to the filled PDF
        field_name (str | None): the field to sign, or None to auto-select when
            exactly one empty signature field exists

    Outputs:
        name (str): the signature field name that will be used

    Raises:
        SigningError with an actionable message in every refusal case.
    --------------------------------------------------------------------------
    """
    fields = signature_fields(pdf_path)
    if not fields:
        raise SigningError(
            f"{os.path.basename(pdf_path)}: no signature field. Either the form has "
            f"none, or a flatten step destroyed it. Sign LAST, never after a burn-in "
            f"flatten.")

    by_name = {f["name"]: f for f in fields}
    if field_name is not None:
        if field_name not in by_name:
            raise SigningError(
                f"no signature field named {field_name!r}. Available: "
                f"{sorted(by_name)}")
        if by_name[field_name]["signed"]:
            raise SigningError(
                f"signature field {field_name!r} is already signed. Signing it again "
                f"would invalidate the existing signature.")
        return field_name

    empty = [f["name"] for f in fields if not f["signed"]]
    if not empty:
        raise SigningError(
            f"every signature field of {os.path.basename(pdf_path)} is already signed")
    if len(empty) > 1:
        raise SigningError(
            f"several empty signature fields, choose one with --field: {sorted(empty)}")
    return empty[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/sign_form.py \
        .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
git commit -m "feat(uqac-forms): signing pre-flight refusing a document that cannot be signed"
```

---

## Task 2: The Signer protocol and the self-signed development signer

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/sign_form.py`
- Modify: `.claude/skills/uqac-forms/scripts/requirements.txt`
- Modify: `.gitignore`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`

**Interfaces:**

- Consumes: `SigningError` from Task 1.
- Produces:
  - `class Signer(Protocol)` with `sign(self, pdf_bytes: bytes, field_name: str, reason: str) -> bytes`.
  - `class SelfSignedSigner` implementing it, constructed as `SelfSignedSigner(cert_dir: str, common_name: str = "UQAC forms development signer", validity_days: int = 365)`.
  - `SelfSignedSigner.ensure_material() -> tuple[str, str]` returning `(cert_path, key_path)`, generating them on first use.
  - `build_signer(provider: str, **options: Any) -> Signer`, the configuration seam. `provider="self-signed"` ships; any other name raises `SigningError` naming the providers that exist, so a production credential is a configuration change and not a code change.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`, above the `if __name__` block:

```python
class TestSelfSignedSigner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.certs = os.path.join(self.tmp.name, "certs")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_material_is_generated_on_first_use(self) -> None:
        signer = sign_form.SelfSignedSigner(self.certs)
        cert, key = signer.ensure_material()
        self.assertTrue(os.path.isfile(cert))
        self.assertTrue(os.path.isfile(key))

    def test_material_is_reused_on_a_second_call(self) -> None:
        signer = sign_form.SelfSignedSigner(self.certs)
        first = signer.ensure_material()
        with open(first[0], "rb") as handle:
            body = handle.read()
        second = signer.ensure_material()
        self.assertEqual(first, second)
        with open(second[0], "rb") as handle:
            self.assertEqual(handle.read(), body)

    def test_material_lands_only_under_the_given_directory(self) -> None:
        signer = sign_form.SelfSignedSigner(self.certs)
        cert, key = signer.ensure_material()
        self.assertTrue(os.path.abspath(cert).startswith(os.path.abspath(self.certs)))
        self.assertTrue(os.path.abspath(key).startswith(os.path.abspath(self.certs)))

    def test_the_self_signed_provider_is_buildable(self) -> None:
        signer = sign_form.build_signer("self-signed", cert_dir=self.certs)
        self.assertIsInstance(signer, sign_form.SelfSignedSigner)

    def test_an_unknown_provider_names_the_ones_that_exist(self) -> None:
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.build_signer("notarius")
        self.assertIn("self-signed", str(ctx.exception))

    def test_no_key_material_reaches_the_log(self) -> None:
        with self.assertLogs(sign_form.logger, level="INFO") as captured:
            sign_form.SelfSignedSigner(self.certs).ensure_material()
        joined = "\n".join(captured.output)
        self.assertNotIn("BEGIN", joined)
        self.assertNotIn("PRIVATE KEY", joined)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: FAIL with `AttributeError: module 'sign_form' has no attribute 'SelfSignedSigner'`.

- [ ] **Step 3: Add the pins**

In `.claude/skills/uqac-forms/scripts/requirements.txt`, add:

```
pyhanko==0.36.2
cryptography==49.0.0
```

Then:

```powershell
pip install -r .claude/skills/uqac-forms/scripts/requirements.txt
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

- [ ] **Step 4: Ignore the generated material**

Append to `.gitignore`:

```
# uqac-forms: development signing material, generated on demand, never committed
.claude/skills/uqac-forms/certs/
*.p12
*.pfx
```

- [ ] **Step 5: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/sign_form.py`:

```python
@runtime_checkable
class Signer(Protocol):
    """
    The whole signing seam. A production provider (UQAC PKI, Notarius, ConsignO)
    implements this one method and is selected by configuration; no caller
    changes.
    """

    def sign(self, pdf_bytes: bytes, field_name: str, reason: str) -> bytes:
        """Return the signed PDF bytes, appended as an incremental update."""


class SelfSignedSigner:
    """
    Development signer. Generates a throwaway self-signed certificate on first
    use and signs with it. The material lives wherever the caller says, is
    gitignored, and is not a submission-ready credential.
    """

    def __init__(self, cert_dir: str,
                 common_name: str = "UQAC forms development signer",
                 validity_days: int = 365) -> None:
        self.cert_dir = cert_dir
        self.common_name = common_name
        self.validity_days = validity_days

    def ensure_material(self) -> tuple[str, str]:
        """
        ----------------------------------------------------------------------
        Purpose:
            Generate the development certificate and private key on first use,
            then reuse them. Both are written under cert_dir and nowhere else.

        Inputs:
            none (uses the instance configuration)

        Outputs:
            paths (tuple[str, str]): (certificate PEM path, private key PEM path)
        ----------------------------------------------------------------------
        """
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        os.makedirs(self.cert_dir, exist_ok=True)
        cert_path = os.path.join(self.cert_dir, "dev-signer.cert.pem")
        key_path = os.path.join(self.cert_dir, "dev-signer.key.pem")
        if os.path.isfile(cert_path) and os.path.isfile(key_path):
            logger.info("[UQAC-FORMS] reusing the development signing material")
            return cert_path, key_path

        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CA"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Quebec"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "UQAC (development only)"),
            x509.NameAttribute(NameOID.COMMON_NAME, self.common_name),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=self.validity_days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=True,
                    key_encipherment=False, data_encipherment=False,
                    key_agreement=False, key_cert_sign=False, crl_sign=False,
                    encipher_only=False, decipher_only=False),
                critical=True)
            .sign(key, hashes.SHA256())
        )

        with open(key_path, "wb") as handle:
            handle.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()))
        with open(cert_path, "wb") as handle:
            handle.write(certificate.public_bytes(serialization.Encoding.PEM))

        # Paths only: never the key body, never the passphrase.
        logger.info("[UQAC-FORMS] generated development signing material in %s", self.cert_dir)
        return cert_path, key_path

    def sign(self, pdf_bytes: bytes, field_name: str, reason: str) -> bytes:
        """
        ----------------------------------------------------------------------
        Purpose:
            Sign the given PDF bytes on the named signature field with PAdES,
            as an incremental update.

        Inputs:
            pdf_bytes (bytes): the filled PDF
            field_name (str): the empty signature field to use
            reason (str): the human-readable reason recorded in the signature

        Outputs:
            signed (bytes): the signed PDF
        ----------------------------------------------------------------------
        """
        import io

        from pyhanko.sign import signers
        from pyhanko.sign.fields import SigFieldSpec, append_signature_field
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

        cert_path, key_path = self.ensure_material()
        simple = signers.SimpleSigner.load(
            key_file=key_path, cert_file=cert_path, key_passphrase=None)

        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
        existing = {f[0] for f in signers.fields.enumerate_sig_fields(writer)}
        if field_name not in existing:
            append_signature_field(writer, SigFieldSpec(sig_field_name=field_name))

        meta = signers.PdfSignatureMetadata(
            field_name=field_name, reason=reason,
            subfilter=signers.fields.SigSeedSubFilter.PADES)
        out = signers.sign_pdf(writer, meta, signer=simple)
        return out.getvalue()


_PROVIDERS = {"self-signed": SelfSignedSigner}


def build_signer(provider: str, **options: Any) -> Signer:
    """
    --------------------------------------------------------------------------
    Purpose:
        Construct the configured signer. This is the seam a production
        credential arrives through: register the provider here, select it by
        name, and no caller changes.

    Inputs:
        provider (str): provider name, "self-signed" today
        options (Any): constructor options, for example cert_dir

    Outputs:
        signer (Signer): the constructed signer

    Raises:
        SigningError naming the providers that exist.
    --------------------------------------------------------------------------
    """
    factory = _PROVIDERS.get(provider)
    if factory is None:
        raise SigningError(
            f"unknown signing provider {provider!r}. Available: {sorted(_PROVIDERS)}. "
            f"A UQAC PKI or Notarius provider is registered here when the "
            f"acceptance question is answered.")
    if provider == "self-signed":
        options.setdefault("cert_dir", os.path.join(".claude", "skills", "uqac-forms", "certs"))
    return factory(**options)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: PASS, 13 tests.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/uqac-forms/scripts/sign_form.py \
        .claude/skills/uqac-forms/scripts/requirements.txt \
        .claude/skills/uqac-forms/scripts/Test/test_sign_form.py .gitignore
git commit -m "feat(uqac-forms): pluggable Signer protocol with a self-signed development signer"
```

---

## Task 3: The signing entry point, with signature validation in tests

**Files:**

- Modify: `.claude/skills/uqac-forms/scripts/sign_form.py`
- Test: `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`

**Interfaces:**

- Consumes: `preflight`, `Signer`, `build_signer`, `SigningError` from Tasks 1 and 2.
- Produces:
  - `sign_pdf(in_path: str, out_path: str, signer: Signer, field_name: str | None = None, reason: str = DEFAULT_REASON) -> dict[str, Any]` returning `{"in": str, "out": str, "field": str, "reason": str, "incremental": True}`.
  - Guarantee asserted by test: the output file starts with the input bytes, because a PAdES signature is an incremental update and never a rewrite.

- [ ] **Step 1: Write the failing test**

Append to `.claude/skills/uqac-forms/scripts/Test/test_sign_form.py`, above the `if __name__` block:

```python
class TestSignPdf(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.certs = os.path.join(self.tmp.name, "certs")
        self.pdf = make_pdf(
            os.path.join(self.tmp.name, "filled.pdf"),
            [_widget("Nom", "/Tx", (10, 700, 200, 720)),
             _widget("Signature_directeur", "/Sig", (300, 100, 500, 160))])
        self.out = os.path.join(self.tmp.name, "out", "signed.pdf")
        self.signer = sign_form.SelfSignedSigner(self.certs)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_signing_writes_the_output_and_reports_the_field(self) -> None:
        result = sign_form.sign_pdf(self.pdf, self.out, self.signer)
        self.assertTrue(os.path.isfile(self.out))
        self.assertEqual(result["field"], "Signature_directeur")
        self.assertTrue(result["incremental"])

    def test_the_signature_is_an_incremental_update_not_a_rewrite(self) -> None:
        sign_form.sign_pdf(self.pdf, self.out, self.signer)
        with open(self.pdf, "rb") as handle:
            original = handle.read()
        with open(self.out, "rb") as handle:
            signed = handle.read()
        self.assertTrue(signed.startswith(original),
                        "a PAdES signature appends; it must not rewrite the file")
        self.assertGreater(len(signed), len(original))

    def test_the_field_is_signed_afterwards(self) -> None:
        sign_form.sign_pdf(self.pdf, self.out, self.signer)
        fields = {f["name"]: f for f in sign_form.signature_fields(self.out)}
        self.assertTrue(fields["Signature_directeur"]["signed"])

    def test_pyhanko_validates_the_signature_it_produced(self) -> None:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext

        sign_form.sign_pdf(self.pdf, self.out, self.signer)
        cert_path, _ = self.signer.ensure_material()
        with open(cert_path, "rb") as handle:
            from asn1crypto import pem, x509 as asn1_x509
            _, _, der = pem.unarmor(handle.read())
            root = asn1_x509.Certificate.load(der)

        with open(self.out, "rb") as handle:
            reader = PdfFileReader(handle)
            embedded = reader.embedded_signatures[0]
            status = validate_pdf_signature(
                embedded, signer_validation_context=ValidationContext(trust_roots=[root]))
            # Integrity is what this asserts: the bytes covered by the signature
            # were not modified. Trust of a self-signed root is not the claim.
            self.assertTrue(status.intact)
            self.assertTrue(status.valid)

    def test_signing_a_document_with_no_signature_field_is_refused(self) -> None:
        plain = make_pdf(os.path.join(self.tmp.name, "plain.pdf"),
                         [_widget("Nom", "/Tx", (10, 700, 200, 720))])
        with self.assertRaises(sign_form.SigningError):
            sign_form.sign_pdf(plain, self.out, self.signer)
        self.assertFalse(os.path.exists(self.out))

    def test_signing_twice_on_the_same_field_is_refused(self) -> None:
        sign_form.sign_pdf(self.pdf, self.out, self.signer)
        again = os.path.join(self.tmp.name, "out", "again.pdf")
        with self.assertRaises(sign_form.SigningError) as ctx:
            sign_form.sign_pdf(self.out, again, self.signer, field_name="Signature_directeur")
        self.assertIn("already signed", str(ctx.exception))

    def test_the_reason_is_recorded(self) -> None:
        result = sign_form.sign_pdf(self.pdf, self.out, self.signer,
                                    reason="Approbation du directeur de recherche")
        self.assertEqual(result["reason"], "Approbation du directeur de recherche")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: FAIL with `AttributeError: module 'sign_form' has no attribute 'sign_pdf'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `.claude/skills/uqac-forms/scripts/sign_form.py`:

```python
def sign_pdf(in_path: str, out_path: str, signer: Signer,
             field_name: str | None = None,
             reason: str = DEFAULT_REASON) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sign a filled form and write the result. The pre-flight refuses anything
        that would produce an unverifiable document, and the signature is an
        incremental update: the output starts with the input bytes.

    Inputs:
        in_path (str): the filled PDF
        out_path (str): destination (its directory is created)
        signer (Signer): the configured signer
        field_name (str | None): signature field, auto-selected when there is
            exactly one empty field
        reason (str): human-readable reason recorded in the signature

    Outputs:
        result (dict): {in, out, field, reason, incremental}

    Raises:
        SigningError from the pre-flight, before anything is written.
    --------------------------------------------------------------------------
    """
    field = preflight(in_path, field_name)
    with open(in_path, "rb") as handle:
        original = handle.read()

    signed = signer.sign(original, field, reason)
    if not signed.startswith(original):
        raise SigningError(
            "the signer rewrote the document instead of appending an incremental "
            "update; the signature would not be verifiable")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as handle:
        handle.write(signed)

    logger.info("[UQAC-FORMS] signed %s on field %s -> %s",
                os.path.basename(in_path), field, out_path)
    return {"in": in_path, "out": out_path, "field": field,
            "reason": reason, "incremental": True}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Sign a filled UQAC form (PAdES)")
    parser.add_argument("pdf", help="the filled PDF")
    parser.add_argument("--field", default=None, help="signature field name")
    parser.add_argument("--reason", default=DEFAULT_REASON)
    parser.add_argument("--out", default=None, help="output PDF (default <name>_signe.pdf)")
    parser.add_argument("--provider", default="self-signed",
                        help="signing provider (self-signed ships today)")
    parser.add_argument("--cert-dir", default=None,
                        help="directory for the development signing material")
    parser.add_argument("--list-fields", action="store_true",
                        help="print the signature fields and exit")
    args = parser.parse_args()

    if args.list_fields:
        print(json.dumps(signature_fields(args.pdf), indent=2, ensure_ascii=False))
        return

    stem, ext = os.path.splitext(args.pdf)
    out = args.out or f"{stem}_signe{ext}"
    options: dict[str, Any] = {}
    if args.cert_dir:
        options["cert_dir"] = args.cert_dir
    try:
        result = sign_pdf(args.pdf, out, build_signer(args.provider, **options),
                          field_name=args.field, reason=args.reason)
    except SigningError as exc:
        raise SystemExit(f"refusing to sign: {exc}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py`
Expected: PASS, 20 tests.

- [ ] **Step 5: Verify the full fill-then-sign chain against a real form**

```powershell
python .claude/skills/uqac-forms/scripts/fill_form.py mth-autorisation-depot `
  --profile .claude/skills/uqac-forms/samples/profile.sample.json `
  --out out/mth-autorisation-depot_rempli.pdf
python .claude/skills/uqac-forms/scripts/sign_form.py out/mth-autorisation-depot_rempli.pdf `
  --list-fields
python .claude/skills/uqac-forms/scripts/sign_form.py out/mth-autorisation-depot_rempli.pdf `
  --out out/mth-autorisation-depot_signe.pdf
pyhanko sign validate out/mth-autorisation-depot_signe.pdf
```

Expected: the fill reports its counts, `--list-fields` names at least one empty signature field, signing writes the output, and `pyhanko sign validate` reports the signature as intact. It also reports the certificate as untrusted, which is correct and expected for a self-signed development credential.

If the form carries no signature field at all, `--list-fields` prints an empty list and signing is refused by name. That is a property of the form, not a defect: record it in `SKILL.md` next to the form id.

- [ ] **Step 6: Update SKILL.md**

Add to `.claude/skills/uqac-forms/SKILL.md`:

````markdown
## Signing

```
python .claude/skills/uqac-forms/scripts/sign_form.py <filled.pdf> [--field NAME] [--reason TEXT] [--out out/<name>_signe.pdf]
```

Signing is the LAST step and is a PAdES incremental update: the signed file
starts with the exact bytes of the filled file. The pre-flight refuses a document
with no signature field, an unknown field name, an already signed field, and an
ambiguous choice between several empty fields.

The signer is pluggable: `build_signer(provider, **options)` is the only place a
credential is chosen. `self-signed` ships and generates a throwaway certificate
into `.claude/skills/uqac-forms/certs/` (gitignored) on first use.

**Unverified.** Whether the Decanat des etudes and the Service des ressources
financieres accept a PAdES cryptographic signature is not confirmed. The
self-signed default is a development default, not a submission-ready credential;
`pyhanko sign validate` will correctly report it as untrusted. The production
certificate decision (UQAC PKI, or Notarius / ConsignO) is open and someone must
ask both offices.

Independent verification of any signed output:

```
pyhanko sign validate out/<name>_signe.pdf
```
````

- [ ] **Step 7: Update `.claude/rules/testing.md`**

Add to the offline test list:

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py   # pre-flight refusals, self-signed material, incremental-update signature, pyhanko validation
```

- [ ] **Step 8: Run the full offline suite**

```powershell
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

- [ ] **Step 9: Commit**

```bash
git add .claude/skills/uqac-forms .claude/rules/testing.md
git commit -m "feat(uqac-forms): PAdES incremental-update signing with validation tests"
```

---

## Interfaces published by RT-4

| Name | Signature | Consumed by |
|---|---|---|
| `Signer` | protocol, `sign(pdf_bytes: bytes, field_name: str, reason: str) -> bytes` | RT-5 |
| `SelfSignedSigner` | `SelfSignedSigner(cert_dir: str, common_name: str = ..., validity_days: int = 365)` | RT-5 |
| `build_signer` | `build_signer(provider: str, **options: Any) -> Signer` | RT-5 (configuration seam) |
| `signature_fields` | `signature_fields(pdf_path: str) -> list[dict]` | RT-5 `GET /forms/{form_id}/signature-fields` |
| `preflight` | `preflight(pdf_path: str, field_name: str \| None = None) -> str` | RT-5 |
| `sign_pdf` | `sign_pdf(in_path, out_path, signer, field_name=None, reason=DEFAULT_REASON) -> dict` | RT-5 `POST /forms/{form_id}/sign` |
| `SigningError` | `class SigningError(RuntimeError)` | RT-5 (maps to HTTP 409) |
| `DEFAULT_REASON` | `str` | RT-5 |

`sign_pdf` result shape: `{"in": str, "out": str, "field": str, "reason": str, "incremental": True}`.
`signature_fields` entry shape: `{"name": str, "page": int, "signed": bool}`.

---

## Acceptance

```powershell
python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
pyhanko sign validate out/<signed>.pdf          # intact, untrusted root is expected
pip-audit -r .claude/skills/uqac-forms/scripts/requirements.txt --strict
```

Plus the RT-1, RT-2, and RT-3 suites and the five existing offline suites in `.claude/rules/testing.md`, which must stay green.

---

## Open item carried forward

The PAdES acceptance question is recorded here and again in TT-5. It blocks nothing in this unit: the pipeline is complete and testable with the development signer. Someone must ask the Decanat des etudes and the Service des ressources financieres whether a cryptographic signature is accepted and, if so, which certificate authority they recognize.

---

## Task 4: Documentation and the pull request

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

In the `### uqac-forms` subsection, add:

```markdown
- `.claude/skills/uqac-forms/scripts/sign_form.py` - `Signer` protocol, self-signed development signer, PAdES incremental update
```

Add the disclosure in the README itself, not only in `SKILL.md`, because the README
is what a reader opens first: whether the Decanat des etudes and the Service des
ressources financieres accept a PAdES cryptographic signature is **unverified**. The
shipped signer is a self-signed development default, `pyhanko sign validate` will
correctly report its root as untrusted, and the production certificate decision
(UQAC PKI, or Notarius / ConsignO) is open.

In the Prerequisites table, extend the `uqac-forms` row with `pyhanko` (MIT) and
`cryptography`, and state that the development certificate is generated on demand
and gitignored, never committed.

In the File-Locations tree, add `sign_form.py` and `Test\test_sign_form.py`.

- [ ] **Step 2: Update `Architecture.md`**

Extend the `s10` node label:

```
    s10["uqac-forms<br/>registry . map . fill . sign"]
```

In the Notes, add one bullet: the signer is pluggable behind a one-method protocol,
`build_signer(provider, **options)` is the only place a credential is chosen, and a
production authority drops in as a configuration change rather than a code change.
State in the same bullet that institutional acceptance of a PAdES signature is
unverified, so a reader of the architecture is not misled into thinking it is settled.

- [ ] **Step 3: Update `NEW_ARCHITECTURE.md`**

`NEW_ARCHITECTURE.md` is committed identically to `main` in both ResearchTools and
ThesisTracker. Edit only what this unit owns, and keep the wording identical in both
checkouts so the two copies never drift.

1. In the section 9 unit table, append ` Delivered <YYYY-MM-DD>.` to the **RT-4** row's
   deliverable cell.
2. Section 5.2 (the sign sequence diagram) and the PAdES rows of the section 11 open-items
   table both describe this unit. Verify the diagram against the delivered `sign_form.py`,
   and leave the open items open unless an office has actually answered.
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
git commit -m "docs(uqac-forms): record RT-4 in the inventories"
```

- [ ] **Step 6: Open the pull request**

`gh` is **not installed** on this machine, and `GITHUB_TOKEN` carries `read:user` only,
so neither the CLI nor that token can open a pull request. Do not try to install `gh`.
The OAuth token in the Windows Credential Manager has `repo` scope and is sufficient.
Retrieve it per command: never write it to a file, never echo it, never commit it.

```bash
git push -u origin feat/uqac-forms-signer

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
  "title": "[RT-4] uqac-forms: PAdES signer",
  "head": "feat/uqac-forms-signer",
  "base": "main",
  "body": "Closes #7\n\n<what the unit delivers, in three or four lines>\n\n**Depends on.** RT-3 (`feat/uqac-forms-filler`), which depends on RT-2 and RT-1.\n\n**Acceptance run.** <paste the commands from the acceptance block and their real result, not a summary>\n\n**Reviewer must check by hand.** <the manual verification steps of this plan, or 'none'>"
}
```

If a permission classifier blocks the command that reads the token, open the pull request
in the browser instead and paste the same title and body:

```
https://github.com/LARi-UQAC/ResearchTools/compare/main...feat/uqac-forms-signer?expand=1
```

Then delete `pr-body.json` from the scratchpad.

**Do not merge your own pull request.** Merging to `main` is the human gate. RT-5 is blocked behind this unit, and TT-3 and TT-5 behind that; say so in the body.

- [ ] **Step 7: Report**

State the pull request URL, the acceptance commands you ran with their real output, and
anything you could not verify. A test you did not run is not a test that passed.
