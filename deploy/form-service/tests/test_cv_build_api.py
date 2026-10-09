"""
test_cv_build_api.py - Offline unit tests for POST /cv/build.

No network, no LaTeX compilation, no disk write: the narrative-cv skill
functions run for real (they are pure), and the FastAPI test client drives
the app in-process. Fictitious data only (CLAUDE.md global constraint).
Run with the service venv from the repo root:
    & $svc deploy/form-service/tests/test_cv_build_api.py
"""

import builtins
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VALID_KEY = "k" * 48

MODEL = {
    "language": "fr",
    "portal_variant": "frq_old_portal",
    "candidate_name": "Camille Exemple",
    "document_title": "CV descriptif",
    "sections": {
        "1": {"title": "Parcours et compétences", "prose": "Texte de parcours."},
        "2": {"title": "Contributions et expériences les plus importantes", "items": []},
        "3": {"title": "Activités de supervision et de mentorat", "prose": "s.o.", "hqp_list": True},
    },
}

RECENT_ROW = {
    "name": "Étudiante Alpha", "cycle": "Maîtrise", "start": "2022-09", "end": "2024-08",
    "consent_cv": "2026-09-01",
}
ARCHIVE_ROW = {
    # C6 revised 2026-10-08: consent is mandatory for every row, archive
    # included - the window only decides the recent/archive LISTING.
    "name": "Étudiant Gamma", "cycle": "Doctorat", "start": "2015-09", "end": "2016-08",
    "consent_cv": "2016-09-01",
}


def _model_without_hqp_list():
    model = json.loads(json.dumps(MODEL))
    del model["sections"]["3"]["hqp_list"]
    return model


class TestCvBuildApi(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FORM_SERVICE_KEY"] = VALID_KEY

        from fastapi.testclient import TestClient
        from app import main

        self.client = TestClient(main.app)
        self.headers = {"X-Form-Service-Key": VALID_KEY}

    def tearDown(self) -> None:
        os.environ.pop("FORM_SERVICE_MAX_BODY_BYTES", None)

    def _post(self, body, headers=None):
        return self.client.post(
            "/cv/build", headers=self.headers if headers is None else headers,
            content=json.dumps(body))

    def test_missing_key_401(self) -> None:
        response = self.client.post("/cv/build", content=json.dumps(
            {"model": MODEL, "hqp": [], "reference_year": 2026}))
        self.assertEqual(response.status_code, 401)

    def test_wrong_key_401(self) -> None:
        response = self._post({"model": MODEL, "hqp": [], "reference_year": 2026},
                              headers={"X-Form-Service-Key": "j" * 48})
        self.assertEqual(response.status_code, 401)

    def test_oversized_body_413(self) -> None:
        os.environ["FORM_SERVICE_MAX_BODY_BYTES"] = "10"
        response = self._post({"model": MODEL, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 413)

    def test_not_json_422(self) -> None:
        response = self.client.post("/cv/build", headers=self.headers, content=b"not json")
        self.assertEqual(response.status_code, 422)

    def test_missing_model_422(self) -> None:
        response = self._post({"hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_hqp_not_list_422(self) -> None:
        response = self._post({"model": MODEL, "hqp": "not-a-list", "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_reference_year_bool_422(self) -> None:
        response = self._post({"model": MODEL, "hqp": [], "reference_year": True})
        self.assertEqual(response.status_code, 422)

    def test_prose_file_422(self) -> None:
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = {"title": "X", "prose_file": "../../etc/passwd"}
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("passwd", response.text)

    def test_missing_consent_422_names_no_person(self) -> None:
        bad_row = dict(RECENT_ROW, consent_cv=None)
        with self.assertLogs(level="INFO") as captured:
            response = self._post({"model": MODEL, "hqp": [bad_row], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)
        self.assertIn("row 0", response.text)
        self.assertNotIn("Étudiante Alpha", response.text)
        self.assertNotIn("Étudiante Alpha", "\n".join(captured.output))

    def test_rows_without_hqp_list_422(self) -> None:
        response = self._post(
            {"model": _model_without_hqp_list(), "hqp": [RECENT_ROW], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_build_both_200(self) -> None:
        response = self._post(
            {"model": MODEL, "hqp": [RECENT_ROW, ARCHIVE_ROW], "reference_year": 2026})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(r"\textbf{Étudiante Alpha}", payload["latex"])
        self.assertIn("- Étudiante Alpha", payload["text"])
        self.assertEqual(payload["hqp"], {"recent": 1, "archive": 1})

    def test_target_text_only(self) -> None:
        response = self._post(
            {"model": MODEL, "hqp": [RECENT_ROW], "reference_year": 2026, "target": "text"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["latex"])

    def test_empty_hqp_200(self) -> None:
        import cv_build

        response = self._post({"model": MODEL, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["latex"], cv_build.render_latex(MODEL))
        self.assertEqual(payload["hqp"], {"recent": 0, "archive": 0})

    def test_nothing_written_to_disk(self) -> None:
        real_open = builtins.open

        def guarded_open(path, mode="r", *args, **kwargs):
            if any(flag in mode for flag in ("w", "a", "x")):
                raise AssertionError("disk write attempted: open(%r, %r)" % (path, mode))
            return real_open(path, mode, *args, **kwargs)

        def guarded_write_text(self_path, *args, **kwargs):
            # builtins.open alone does not intercept pathlib.Path.write_text,
            # which calls the C-level io machinery directly: patch it too, or
            # a route that switched to Path.write_text would pass this test
            # while still writing to disk.
            raise AssertionError("disk write attempted: Path.write_text(%r)" % (self_path,))

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with patch("builtins.open", guarded_open), \
                        patch("pathlib.Path.write_text", guarded_write_text):
                    response = self._post(
                        {"model": MODEL, "hqp": [RECENT_ROW], "reference_year": 2026})
                self.assertEqual(response.status_code, 200)
                # The cwd check alone misses a write to an absolute path
                # elsewhere on disk; the two patches above are what actually
                # enforce the no-write invariant everywhere, not this listing.
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(cwd)

    def test_malformed_model_422_not_500(self) -> None:
        # {"sections": {}} passes a prose_file-only check, then crashes
        # render_latex on model["portal_variant"] with a bare KeyError the
        # route's `except CvDataError` does not catch.
        response = self._post({"model": {"sections": {}}, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_existing_routes_unaffected(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_section_items_not_a_list_422_not_500(self) -> None:
        model = json.loads(json.dumps(MODEL))
        model["sections"]["2"]["items"] = "not-a-list"
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_section_prose_not_a_string_422_not_500(self) -> None:
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = {"title": "X", "prose": ["not", "a", "string"]}
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_deeply_nested_json_422_not_500(self) -> None:
        # json.loads raises RecursionError (a RuntimeError, not a ValueError)
        # on pathologically deep nesting; the route must catch it too.
        deep = b"[" * 100000 + b"]" * 100000
        response = self.client.post("/cv/build", headers=self.headers, content=deep)
        self.assertEqual(response.status_code, 422)

    def test_unknown_top_level_key_422(self) -> None:
        # N-B (reviewer, 2026-10-08): a stray "funder" key must not be
        # silently ignored - the window always comes from portal_variant.
        response = self._post(
            {"model": MODEL, "hqp": [], "reference_year": 2026, "funder": "nserc"})
        self.assertEqual(response.status_code, 422)

    def test_language_de_with_rows_422_not_500(self) -> None:
        # F1 (reviewer, 2026-10-08): render_hqp's bare labels[language]
        # lookup raised a bare KeyError, not CvDataError, for an unsupported
        # language once rows made the HQP block render at all.
        model = json.loads(json.dumps(MODEL))
        model["language"] = "de"
        response = self._post(
            {"model": model, "hqp": [RECENT_ROW], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_language_explicit_null_422(self) -> None:
        # M1: an explicit null (not merely absent) must stop at
        # assert_inline_model with 422, not crash deeper with 500.
        model = json.loads(json.dumps(MODEL))
        model["language"] = None
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_item_clienteles_element_type_422(self) -> None:
        # M2: a non-string element inside an otherwise-list clienteles field.
        model = json.loads(json.dumps(MODEL))
        model["sections"]["2"]["items"] = [{
            "description": "X", "clienteles": ["milieu_academique", 123]}]
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_section2_item_cap_exceeded_422(self) -> None:
        # Q2: section 2 is capped at 10 items.
        model = json.loads(json.dumps(MODEL))
        model["sections"]["2"]["items"] = [
            {"description": "Item %d" % i} for i in range(11)]
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_unknown_top_level_model_key_422_names_it(self) -> None:
        # Q3a: a stray model-level key is named rather than silently ignored.
        model = json.loads(json.dumps(MODEL))
        model["funder"] = "nserc"
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)
        self.assertIn("funder", response.text)

    def test_unknown_item_key_422_names_it(self) -> None:
        # Q3d: an item field name is caller-fixed vocabulary, safe to name.
        model = json.loads(json.dumps(MODEL))
        model["sections"]["2"]["items"] = [
            {"description": "X", "funding_source": "CRSNG"}]
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)
        self.assertIn("funding_source", response.text)

    def test_section_as_int_422_not_500(self) -> None:
        # R1: regression from the Q3 unknown-section-key fix - the
        # isinstance(dict) check ran AFTER set(section), so a truthy
        # non-dict section crashed with a bare 500 instead of a 422.
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = 1
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_section_as_list_422_not_500(self) -> None:
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = [1]
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_section_as_list_with_null_422_not_500(self) -> None:
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = [None]
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)

    def test_section_as_string_422_does_not_echo_its_characters(self) -> None:
        # The measured defect: set("Jean Tremblay") iterates the string's
        # CHARACTERS, and the old check order let that reach the response
        # body through the "unknown key(s): ..." message.
        model = json.loads(json.dumps(MODEL))
        model["sections"]["1"] = "Jean Tremblay"
        response = self._post({"model": model, "hqp": [], "reference_year": 2026})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("Jean", response.text)
        self.assertNotIn("Tremblay", response.text)

    def test_falsy_section_422_not_silently_dropped(self) -> None:
        # Low-3: 0/false/""/[]/{} used to be read as "no section" and
        # silently dropped the section from the rendered CV with no error.
        for falsy in (0, False, "", [], {}):
            model = json.loads(json.dumps(MODEL))
            model["sections"]["1"] = falsy
            response = self._post({"model": model, "hqp": [], "reference_year": 2026})
            self.assertEqual(response.status_code, 422, falsy)

    def test_invalid_target_422(self) -> None:
        # M-E: cv_bridge.build_cv's own _TARGETS whitelist, reached through
        # the route, not only as unit-tested code with no caller.
        response = self._post(
            {"model": MODEL, "hqp": [], "reference_year": 2026, "target": "pdf"})
        self.assertEqual(response.status_code, 422)

    def test_cv_build_unavailable_when_narrative_cv_missing_503(self) -> None:
        # M3: cv_bridge is imported lazily inside the route so a missing
        # narrative-cv checkout stops only /cv/build, never /pdf/fill or
        # /pdf/sign. Setting the module to None in sys.modules forces the
        # next "from . import cv_bridge" to raise ImportError - but only if
        # the `app` package object does not ALSO carry `cv_bridge` as an
        # already-bound attribute from an earlier successful import in this
        # process, which "from X import Y" falls back to even when
        # sys.modules["X.Y"] is None. Both have to be cleared.
        import app as app_pkg

        had_attr = hasattr(app_pkg, "cv_bridge")
        saved = getattr(app_pkg, "cv_bridge", None)
        if had_attr:
            delattr(app_pkg, "cv_bridge")
        try:
            with patch.dict(sys.modules, {"app.cv_bridge": None}):
                response = self._post({"model": MODEL, "hqp": [], "reference_year": 2026})
        finally:
            if had_attr:
                app_pkg.cv_bridge = saved
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
