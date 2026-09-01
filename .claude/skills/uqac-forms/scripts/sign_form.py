"""
sign_form.py - apply a PAdES signature to one named field of a UQAC form.

Stage: signing, and always last. It takes a PDF and returns a PDF, holds no
document and no record of who signed what: TT-8's step definition names the
signature field and TT-10 decides whose turn it is.

The requirement that shapes everything here: **a new signature must preserve
every previous one.** One form collects three signatures, from the student, the
direction de recherche and the Decanat, in separate requests hours or days
apart. Each is written as an incremental update, appended to the document as it
stood, so the earlier signatures still cover the bytes they signed.

That is also why fill_form refuses to fill a document that is already signed:
pypdf rewrites the file, and a rewrite destroys exactly what an incremental
update protects.

Asserting that the output starts with the input bytes is necessary and not
sufficient. A file can carry the earlier bytes and still hold a broken earlier
signature, so the test suite asks pyHanko to validate all three.

The certificate is the only state this module has. SelfSignedSigner generates
development material on demand into a directory that is never committed. It
exists so implementation proceeds while the production credential is undecided,
and build_signer is the seam where that decision arrives as configuration rather
than as a code change.

**Self-signed material is for development.** An institutional office is more
likely to reject a self-signed certificate than any other kind, so nothing here
may present a document signed with it as one an office would accept. See the
Open items table in NEW_ARCHITECTURE.md: whether the Decanat and the Service des
ressources financieres accept a PAdES signature at all is still unanswered.
"""

import datetime
import io
import logging
import os
from typing import Any, Protocol, runtime_checkable

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers

import field_map

logger = logging.getLogger(__name__)

DEFAULT_REASON: str = "Signature apposee via ThesisTracker"

_DEV_KEY_NAME: str = "dev-signing-key.pem"
_DEV_CERT_NAME: str = "dev-signing-cert.pem"


class SigningError(RuntimeError):
    """Signing cannot proceed, and no document is produced."""


@runtime_checkable
class Signer(Protocol):
    """What RT-5 needs from any signer, development or institutional."""

    def sign(self, pdf_bytes: bytes, field_name: str, reason: str) -> bytes:
        ...


def _as_stream(pdf: str | bytes) -> io.BytesIO:
    """Accept a path or a body, because TT-8 stores bytes and RT-5 receives them."""
    if isinstance(pdf, (bytes, bytearray)):
        return io.BytesIO(pdf)
    with open(pdf, "rb") as handle:
        return io.BytesIO(handle.read())


def signature_fields(pdf: str | bytes) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every signature field in a document and whether it is already
        signed, so a caller can decide whose turn it is without opening the
        file itself.

    Inputs:
        pdf (str | bytes): a path, or the PDF body

    Outputs:
        fields (list[dict]): one entry per signature field, each with name,
            page (1-based) and signed. Empty when the form has none.
    --------------------------------------------------------------------------
    """
    # Which fields carry a real signature comes from pyHanko, which understands
    # signatures. Which widgets exist comes from field_map, whose traversal is
    # already exercised against real UQAC forms: walking pyHanko's page tree by
    # hand broke on the first real one, because /Kids is an indirect object
    # there and was a direct array in every synthetic fixture.
    body = pdf if isinstance(pdf, (bytes, bytearray)) else open(pdf, "rb").read()

    try:
        signed_names = {
            e.field_name for e in PdfFileReader(io.BytesIO(body),
                                                strict=False).embedded_signatures}
    except Exception as err:
        # A document pyHanko cannot parse for signatures may still be a form we
        # can list, so this is not fatal on its own.
        logger.warning("[UQAC-FORMS] could not read embedded signatures: %s", err)
        signed_names = set()

    out: list[dict[str, Any]] = []
    for widget in field_map.dump_widgets(body):
        if widget["type"] != "signature":
            continue
        out.append({
            "name": widget["name"],
            "page": widget["page"],
            # A field counts as signed when it carries a signature or a value.
            # Whether that signature validates is a separate question, and not
            # one this listing should silently answer.
            "signed": widget["name"] in signed_names,
        })
    return out


def preflight(pdf: str | bytes, field_name: str | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide which signature field will be signed, and refuse rather than
        guess when the answer is not obvious.

    Inputs:
        pdf (str | bytes): a path, or the PDF body
        field_name (str | None): the field the caller wants, or None to let a
            single empty field be chosen

    Outputs:
        name (str): the field that will be signed

    Raises:
        SigningError: the document has no signature field, the named field does
            not exist, the named field is already signed, or several are empty
            and the caller named none. Guessing in that last case would
            attribute a signature to the wrong actor, which is worse on an
            official document than refusing to sign at all.
    --------------------------------------------------------------------------
    """
    fields = signature_fields(pdf)
    if not fields:
        raise SigningError("this document has no signature field")

    by_name = {f["name"]: f for f in fields}
    if field_name is not None:
        if field_name not in by_name:
            raise SigningError(
                f"no signature field named {field_name!r}. This document has: "
                + ", ".join(repr(f["name"]) for f in fields))
        if by_name[field_name]["signed"]:
            raise SigningError(f"{field_name!r} is already signed")
        return field_name

    empty = [f["name"] for f in fields if not f["signed"]]
    if not empty:
        raise SigningError("every signature field in this document is already signed")
    if len(empty) > 1:
        raise SigningError(
            "this document has more than one empty signature field, so the "
            "caller must say which to sign: " + ", ".join(repr(n) for n in empty))
    return empty[0]


class SelfSignedSigner:
    """
    A development signer. It generates its own key and certificate on first use
    and reuses them afterwards.

    Present so RT-4 can be built and tested while the production credential is
    undecided. `is_development` is True and is meant to be read: a document
    signed with this must never be presented as one an institutional office has
    accepted.
    """

    is_development: bool = True

    def __init__(self, cert_dir: str,
                 common_name: str = "ThesisTracker development signer",
                 validity_days: int = 365) -> None:
        self._dir = cert_dir
        self._key_path = os.path.join(cert_dir, _DEV_KEY_NAME)
        self._cert_path = os.path.join(cert_dir, _DEV_CERT_NAME)
        os.makedirs(cert_dir, exist_ok=True)
        if not (os.path.exists(self._key_path) and os.path.exists(self._cert_path)):
            self._generate(common_name, validity_days)
        self._signer = signers.SimpleSigner.load(
            self._key_path, self._cert_path, key_passphrase=None)

    def _generate(self, common_name: str, validity_days: int) -> None:
        """Write a fresh key pair and self-signed certificate."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "UQAC (development)"),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=validity_days))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                               critical=True)
                .add_extension(x509.KeyUsage(
                    digital_signature=True, content_commitment=True,
                    key_encipherment=False, data_encipherment=False,
                    key_agreement=False, key_cert_sign=False, crl_sign=False,
                    encipher_only=False, decipher_only=False), critical=True)
                .sign(key, hashes.SHA256()))

        with open(self._key_path, "wb") as handle:
            handle.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()))
        with open(self._cert_path, "wb") as handle:
            handle.write(cert.public_bytes(serialization.Encoding.PEM))
        logger.info("[UQAC-FORMS] generated development signing material in %s",
                    self._dir)

    def certificate_pem(self) -> bytes:
        """The certificate, for a caller that wants to show what signed."""
        with open(self._cert_path, "rb") as handle:
            return handle.read()

    def sign(self, pdf_bytes: bytes, field_name: str,
             reason: str = DEFAULT_REASON) -> bytes:
        """Sign one field as an incremental update. See sign_pdf."""
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes), strict=False)
        out = io.BytesIO()
        signers.sign_pdf(
            writer,
            signers.PdfSignatureMetadata(field_name=field_name, reason=reason),
            signer=self._signer,
            output=out,
            in_place=False,
        )
        return out.getvalue()


def build_signer(provider: str, **options: Any) -> Signer:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a signer by name. This is the seam where the production
        certificate decision lands as configuration instead of as a code
        change, once the Decanat and the Service des ressources financieres say
        what they accept.

    Inputs:
        provider (str): currently only "self-signed"
        options (Any): passed to the signer, for example cert_dir

    Outputs:
        signer (Signer): something with a sign method

    Raises:
        SigningError: the provider is unknown. It names the provider asked for,
            because a silent fallback to the development signer would be the
            worst possible default.
    --------------------------------------------------------------------------
    """
    if provider == "self-signed":
        return SelfSignedSigner(**options)
    raise SigningError(
        f"unknown signer provider {provider!r}. Only 'self-signed' exists so "
        "far, and it is for development: the institutional credential is an "
        "open item in NEW_ARCHITECTURE.md.")


def sign_pdf(pdf_bytes: bytes, signer: Signer, field_name: str | None = None,
             reason: str = DEFAULT_REASON) -> bytes:
    """
    --------------------------------------------------------------------------
    Purpose:
        Sign one field and return the signed PDF. The write is an incremental
        update: the original bytes are left untouched and the signature is
        appended, so every signature already in the document still covers the
        bytes it signed.

    Inputs:
        pdf_bytes (bytes): the document to sign
        signer (Signer): what to sign with
        field_name (str | None): the field to sign, or None when the document
            has exactly one empty signature field
        reason (str): recorded in the signature

    Outputs:
        signed (bytes): the document with one more signature

    Raises:
        SigningError: preflight refused, or the signing itself failed. Nothing
            is returned in that case.
    --------------------------------------------------------------------------
    """
    chosen = preflight(pdf_bytes, field_name)
    try:
        return signer.sign(pdf_bytes, chosen, reason)
    except SigningError:
        raise
    except Exception as err:
        raise SigningError(f"signing {chosen!r} failed: {err}") from err
