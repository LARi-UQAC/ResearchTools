"""
test_sign_form.py - Offline unit tests for sign_form.py.

No network, no timestamp authority and no committed certificate: the development
certificate is generated into a temporary directory inside the test.

The chain test is the point of this file. One UQAC form collects three
signatures, from the student, the professor and the Direction, in separate
requests hours or days apart. Asserting that the output starts with the input
bytes is necessary and not sufficient, because a file can carry the earlier bytes
and still have a broken earlier signature. So the test signs one document three
times and asks pyHanko to validate all three afterwards.

Run with the project Python:
    python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
"""

import io
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The self-signed certificate cannot chain to a trust anchor, which pyhanko
# reports at ERROR with a full traceback. That is the expected result here and
# it is asserted below, so the log noise is silenced rather than read.
logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko").setLevel(logging.CRITICAL)

import sign_form  # noqa: E402

from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject,
)


def _sig_widget(name: str, rect: tuple) -> DictionaryObject:
    annot = DictionaryObject()
    annot.update({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Sig"),
        NameObject("/T"): TextStringObject(name),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
        NameObject("/F"): FloatObject(4),
    })
    return annot


def form_with_signature_fields(names: list) -> bytes:
    """A PDF carrying one empty signature field per name."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    annots = ArrayObject()
    refs = []
    y = 700
    for name in names:
        ref = writer._add_object(_sig_widget(name, (50, y, 250, y + 40)))
        refs.append(ref)
        annots.append(ref)
        y -= 80
    page[NameObject("/Annots")] = annots
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject(refs),
        NameObject("/SigFlags"): FloatObject(3),
    })
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


THREE = ["signature_etudiant", "signature_direction_recherche", "signature_decanat"]


class _SignerTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        # Generating a key pair is slow, so the development signer is built once
        # for the whole file rather than per test.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.signer = sign_form.SelfSignedSigner(cls.tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()


class TestSignatureFields(_SignerTestCase):

    def test_every_signature_field_is_listed(self) -> None:
        found = sign_form.signature_fields(form_with_signature_fields(THREE))
        self.assertEqual([f["name"] for f in found], THREE)

    def test_an_unsigned_field_is_reported_unsigned(self) -> None:
        found = sign_form.signature_fields(form_with_signature_fields(THREE))
        self.assertTrue(all(f["signed"] is False for f in found))

    def test_a_signed_field_is_reported_signed(self) -> None:
        pdf = form_with_signature_fields(THREE)
        signed = sign_form.sign_pdf(pdf, self.signer, field_name=THREE[0])
        by_name = {f["name"]: f for f in sign_form.signature_fields(signed)}
        self.assertTrue(by_name[THREE[0]]["signed"])
        self.assertFalse(by_name[THREE[1]]["signed"])

    def test_a_pdf_with_no_signature_field_returns_an_empty_list(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)
        self.assertEqual(sign_form.signature_fields(buffer.getvalue()), [])

    def test_bytes_and_a_path_agree(self) -> None:
        pdf = form_with_signature_fields(THREE)
        path = os.path.join(self.tmp.name, "form.pdf")
        with open(path, "wb") as handle:
            handle.write(pdf)
        self.assertEqual(sign_form.signature_fields(path),
                         sign_form.signature_fields(pdf))


class TestPreflight(_SignerTestCase):

    def test_a_single_empty_field_is_chosen_without_being_named(self) -> None:
        pdf = form_with_signature_fields(["signature_etudiant"])
        self.assertEqual(sign_form.preflight(pdf), "signature_etudiant")

    def test_a_named_field_is_returned(self) -> None:
        pdf = form_with_signature_fields(THREE)
        self.assertEqual(sign_form.preflight(pdf, THREE[1]), THREE[1])

    def test_several_empty_fields_and_no_choice_is_refused(self) -> None:
        # Signing the wrong one attributes a signature to the wrong actor, so
        # guessing is worse than refusing.
        with self.assertRaises(sign_form.SigningError):
            sign_form.preflight(form_with_signature_fields(THREE))

    def test_a_document_with_no_signature_field_is_refused(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaises(sign_form.SigningError):
            sign_form.preflight(buffer.getvalue())

    def test_a_name_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(sign_form.SigningError) as caught:
            sign_form.preflight(form_with_signature_fields(THREE), "signature_absente")
        self.assertIn("signature_absente", str(caught.exception))

    def test_an_already_signed_field_is_refused(self) -> None:
        pdf = form_with_signature_fields(THREE)
        signed = sign_form.sign_pdf(pdf, self.signer, field_name=THREE[0])
        with self.assertRaises(sign_form.SigningError):
            sign_form.preflight(signed, THREE[0])

    def test_the_remaining_empty_field_is_chosen_after_two_are_signed(self) -> None:
        pdf = form_with_signature_fields(THREE)
        pdf = sign_form.sign_pdf(pdf, self.signer, field_name=THREE[0])
        pdf = sign_form.sign_pdf(pdf, self.signer, field_name=THREE[1])
        self.assertEqual(sign_form.preflight(pdf), THREE[2])


class TestSigning(_SignerTestCase):

    def test_the_result_is_a_pdf(self) -> None:
        out = sign_form.sign_pdf(form_with_signature_fields(THREE), self.signer,
                                 field_name=THREE[0])
        self.assertTrue(out.startswith(b"%PDF"))

    def test_signing_is_an_incremental_update(self) -> None:
        # Necessary but not sufficient. The chain test below is what proves the
        # earlier signatures still verify.
        original = form_with_signature_fields(THREE)
        out = sign_form.sign_pdf(original, self.signer, field_name=THREE[0])
        self.assertEqual(out[:len(original)], original)

    def test_the_named_field_is_the_one_signed(self) -> None:
        out = sign_form.sign_pdf(form_with_signature_fields(THREE), self.signer,
                                 field_name=THREE[1])
        by_name = {f["name"]: f for f in sign_form.signature_fields(out)}
        self.assertTrue(by_name[THREE[1]]["signed"])
        self.assertFalse(by_name[THREE[0]]["signed"])

    def test_the_reason_is_recorded(self) -> None:
        out = sign_form.sign_pdf(form_with_signature_fields(THREE), self.signer,
                                 field_name=THREE[0], reason="Approbation du plan")
        self.assertIn(b"Approbation du plan", out)

    def test_signing_a_field_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(sign_form.SigningError):
            sign_form.sign_pdf(form_with_signature_fields(THREE), self.signer,
                               field_name="signature_absente")


class TestThreeSignatureChain(_SignerTestCase):
    """The requirement that carries this unit."""

    def signed_three_times(self) -> bytes:
        pdf = form_with_signature_fields(THREE)
        for name in THREE:
            pdf = sign_form.sign_pdf(pdf, self.signer, field_name=name,
                                     reason=f"signed as {name}")
        return pdf

    def test_all_three_fields_report_signed(self) -> None:
        out = self.signed_three_times()
        self.assertTrue(all(f["signed"] for f in sign_form.signature_fields(out)))

    def test_pyhanko_validates_every_signature_not_only_the_last(self) -> None:
        # A file can carry the earlier bytes and still have a broken earlier
        # signature, which is exactly what a rewrite produces. This is the
        # assertion that distinguishes the two.
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature

        reader = PdfFileReader(io.BytesIO(self.signed_three_times()))
        self.assertEqual(len(reader.embedded_signatures), 3,
                         "three signatures must be present")
        for embedded in reader.embedded_signatures:
            status = validate_pdf_signature(embedded)
            self.assertTrue(status.intact,
                            f"{embedded.field_name}: the signed bytes were altered")
            self.assertTrue(status.valid,
                            f"{embedded.field_name}: the signature does not verify")

    def test_the_development_signatures_are_valid_but_not_trusted(self) -> None:
        # The distinction the open item turns on. Each signature is
        # cryptographically sound and covers what it claims to cover, and none
        # of them chains to an authority anyone recognizes, because the
        # certificate is self-signed.
        #
        # This asserts the gap rather than hiding it. Nothing may present a
        # document signed this way as one the Decanat has accepted, and the
        # answer arrives as a build_signer provider, not as a code change here.
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature

        reader = PdfFileReader(io.BytesIO(self.signed_three_times()))
        for embedded in reader.embedded_signatures:
            status = validate_pdf_signature(embedded)
            self.assertTrue(status.valid, embedded.field_name)
            self.assertFalse(status.trusted,
                             f"{embedded.field_name}: a development signature must "
                             "never report as trusted")

    def test_each_signature_covers_the_document_as_it_stood(self) -> None:
        from pyhanko.pdf_utils.reader import PdfFileReader
        reader = PdfFileReader(io.BytesIO(self.signed_three_times()))
        covered = [e.signed_data is not None for e in reader.embedded_signatures]
        self.assertEqual(covered, [True, True, True])

    def test_the_signatures_appear_in_the_order_they_were_applied(self) -> None:
        from pyhanko.pdf_utils.reader import PdfFileReader
        reader = PdfFileReader(io.BytesIO(self.signed_three_times()))
        self.assertEqual([e.field_name for e in reader.embedded_signatures], THREE)

    def test_each_signing_appends_rather_than_rewrites(self) -> None:
        pdf = form_with_signature_fields(THREE)
        sizes = [len(pdf)]
        for name in THREE:
            previous = pdf
            pdf = sign_form.sign_pdf(pdf, self.signer, field_name=name)
            self.assertEqual(pdf[:len(previous)], previous,
                             f"signing {name} rewrote the document")
            sizes.append(len(pdf))
        self.assertEqual(sizes, sorted(sizes), "the file must only grow")


class TestSelfSignedSigner(_SignerTestCase):

    def test_the_certificate_is_generated_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            self.assertEqual(os.listdir(fresh), [])
            sign_form.SelfSignedSigner(fresh)
            self.assertTrue(os.listdir(fresh), "no material was written")

    def test_material_is_reused_rather_than_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            first = sign_form.SelfSignedSigner(fresh).certificate_pem()
            second = sign_form.SelfSignedSigner(fresh).certificate_pem()
            self.assertEqual(first, second)

    def test_it_declares_itself_a_development_signer(self) -> None:
        # A self-signed certificate is what an institutional office is most
        # likely to reject. Nothing may present it as accepted.
        self.assertTrue(sign_form.SelfSignedSigner.is_development)


class TestBuildSigner(_SignerTestCase):

    def test_the_development_provider_is_built(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            signer = sign_form.build_signer("self-signed", cert_dir=fresh)
            self.assertIsInstance(signer, sign_form.SelfSignedSigner)

    def test_an_unknown_provider_is_refused_by_name(self) -> None:
        with self.assertRaises(sign_form.SigningError) as caught:
            sign_form.build_signer("uqac-pki")
        self.assertIn("uqac-pki", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
