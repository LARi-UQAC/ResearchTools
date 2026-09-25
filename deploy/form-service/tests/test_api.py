"""
test_api.py - Offline unit tests for the form-service HTTP API.

No network, no real form, no certificate authority: the skill functions are
patched and the FastAPI test client drives the app in-process. Run with the
project Python from the repo root:
    python deploy/form-service/tests/test_api.py
"""

import json
import os
import sys
import tempfile
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
            config.load_settings({"FORM_SERVICE_KEY": "zz9wq"})
        self.assertIn("32", str(ctx.exception))

    def test_the_secret_is_never_repeated_in_the_error(self) -> None:
        # A literal like "short" would collide with the word "shorter" in the
        # refusal message and pass for the wrong reason: this probe value must
        # never appear as a substring of any English word the message uses.
        with self.assertRaises(RuntimeError) as ctx:
            config.load_settings({"FORM_SERVICE_KEY": "zz9wq"})
        self.assertNotIn("zz9wq", str(ctx.exception))

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


class TestSkillBridge(unittest.TestCase):
    def setUp(self) -> None:
        from app import skill_bridge
        self.bridge = skill_bridge
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = config.load_settings({
            "FORM_SERVICE_KEY": VALID_KEY,
            "FORM_SERVICE_CERT_DIR": os.path.join(self.tmp.name, "certs"),
        })
        self._real_dump = self.bridge.field_map.dump_widgets
        self._real_fill = self.bridge.fill_form.fill
        self._real_validate = self.bridge.sign_form.validate_signatures

    def tearDown(self) -> None:
        self.bridge.field_map.dump_widgets = self._real_dump
        self.bridge.fill_form.fill = self._real_fill
        self.bridge.sign_form.validate_signatures = self._real_validate
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


class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FORM_SERVICE_KEY"] = VALID_KEY
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

    def test_fill_rejects_a_non_pdf_upload(self) -> None:
        response = self.client.post(
            "/pdf/fill", headers=self.headers,
            files={"pdf": ("form.pdf", b"not a pdf", "application/pdf")},
            data={"values": json.dumps({})})
        self.assertEqual(response.status_code, 422)

    def test_fill_maps_an_unknown_field_to_422(self) -> None:
        import fill_form

        def refuse(pdf, values, flatten_fields, settings):
            raise fill_form.FillError("no such field in this PDF: 'Nope'")
        self.bridge.fill_to_bytes = refuse
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

        def refuse(pdf, field, reason, settings):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
