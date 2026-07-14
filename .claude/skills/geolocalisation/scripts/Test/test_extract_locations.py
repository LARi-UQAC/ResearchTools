"""
Offline unit tests for the geolocalisation skill (no network, no API key, no
matplotlib). Exercises the deterministic core: bib parsing, author labelling,
place-name matching + confidence scoring on a synthetic gazetteer, override
merge, and the KML/GeoJSON/country-count writers.

Run: python .claude/skills/geolocalisation/scripts/Test/test_extract_locations.py
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract_locations as ex
import generate_geomap as gm


# A tiny hand-built gazetteer so the tests never touch the Natural Earth files.
FAKE_GAZ = (
    {"canada": "Canada", "iran": "Iran", "switzerland": "Switzerland",
     "afghanistan": "Afghanistan"},
    {"Canada": (56.0, -106.0), "Iran": (32.0, 53.0),
     "Switzerland": (46.8, 8.2), "Afghanistan": (33.9, 67.7)},
    {"montreal": ("Montreal", 45.5, -73.5, "Canada", 1700000),
     "kabul": ("Kabul", 34.5, 69.1, "Afghanistan", 3500000),
     "shiraz": ("Shiraz", 29.6, 52.5, "Iran", 1500000)},
)


class TestAuthorLabel(unittest.TestCase):
    def test_single(self):
        self.assertEqual(ex._first_author_label("Cai, Xin"), "Cai")

    def test_two_authors_ampersand(self):
        self.assertEqual(ex._first_author_label("Choi, J. and Kim, J."), "Choi & Kim")

    def test_three_plus_et_al(self):
        self.assertEqual(
            ex._first_author_label("Li, A. and Wang, B. and Sun, C."), "Li et al.")

    def test_no_comma(self):
        self.assertEqual(ex._first_author_label("Xin Cai and Yu Li"), "Cai & Li")


class TestParseBib(unittest.TestCase):
    BIB = """@article{choi2023renovation,
  author  = {Choi, Junho and Kim, Jun},
  title   = {Deep renovation of old apartment},
  journal = {Journal of Cleaner Production},
  year    = {2023},
  doi     = {10.1016/j.jclepro.2022.135396}
}
% [GRADE: A] --- Journal of Cleaner Production (Elsevier)
% [SOURCE: SCOPUS.AI] [THEME: T1] Scopus citations: 14

@inproceedings{redmon2016yolo,
  author  = {Redmon, J. and Divvala, S. and Girshick, R.},
  title   = {You only look once},
  year    = {2016},
  doi     = {10.1109/CVPR.2016.91}
}
% [THEME: T2] Scopus citations: 51229
"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False,
                                               encoding="utf-8")
        self.tmp.write(self.BIB)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_records(self):
        recs = ex.parse_bib(self.tmp.name)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["citekey"], "choi2023renovation")
        self.assertEqual(recs[0]["etude"], "Choi & Kim")
        self.assertEqual(recs[0]["doi"], "10.1016/j.jclepro.2022.135396")
        self.assertEqual(recs[0]["theme"], "T1")
        self.assertEqual(recs[1]["etude"], "Redmon et al.")
        self.assertEqual(recs[1]["theme"], "T2")


class TestMatchLocation(unittest.TestCase):
    def test_high_city_and_country(self):
        r = ex.match_location("A case study of buildings in Montreal, Canada.", FAKE_GAZ)
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["ville"], "Montreal")
        self.assertEqual(r["pays"], "Canada")

    def test_medium_single_city(self):
        r = ex.match_location("Rooftop survey conducted in Montreal only.", FAKE_GAZ)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["ville"], "Montreal")

    def test_medium_single_country(self):
        r = ex.match_location("A nationwide compliance study across Iran.", FAKE_GAZ)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["pays"], "Iran")
        self.assertEqual(r["ville"], "")

    def test_low_author_country_conflict(self):
        # City site (Kabul/Afghanistan) but only the authors' country (Switzerland)
        # is named as a country - the classic author-country false positive.
        r = ex.match_location(
            "Seismic risk in Kabul, by a team based in Switzerland.", FAKE_GAZ)
        self.assertEqual(r["confidence"], "low")

    def test_none_global(self):
        r = ex.match_location("A global systematic review of methods.", FAKE_GAZ)
        self.assertEqual(r["confidence"], "none")
        self.assertEqual(r["lat"], "")

    def test_city_alias_french(self):
        # "Chiraz" (French) should fold onto the gazetteer "Shiraz".
        r = ex.match_location("Etude de cas a Chiraz, Iran.", FAKE_GAZ)
        self.assertEqual(r["ville"], "Shiraz")
        self.assertEqual(r["confidence"], "high")


class TestOverrideMerge(unittest.TestCase):
    def test_override_wins(self):
        base = {"citekey": "k", "etude": "", "theme": "", "ville": "", "pays": "",
                "lat": "", "lon": "", "confidence": "none", "source": "", "matched": ""}
        ov = {"citekey": "k", "ville": "Kabul", "pays": "Afghanistan",
              "lat": "34.53", "lon": "69.17"}
        bib = {"etude": "Rahman et al.", "theme": "T5"}
        merged = ex.apply_override(base, ov, bib)
        self.assertEqual(merged["ville"], "Kabul")
        self.assertEqual(merged["etude"], "Rahman et al.")
        self.assertEqual(merged["theme"], "T5")
        self.assertEqual(merged["confidence"], "manual")
        self.assertEqual(merged["source"], "override")


class TestRenderWriters(unittest.TestCase):
    ROWS = [
        {"citekey": "a1", "etude": "Cai et al.", "ville": "Montreal", "pays": "Canada",
         "lat": "45.5", "lon": "-73.5", "theme": "T2", "confidence": "high",
         "source": "scopus-abstract", "matched": "Montreal+Canada"},
        {"citekey": "a2", "etude": "Li et al.", "ville": "", "pays": "Iran",
         "lat": "32.0", "lon": "53.0", "theme": "T5", "confidence": "medium",
         "source": "scopus-abstract", "matched": "Iran"},
        {"citekey": "a3", "etude": "Global rev.", "ville": "", "pays": "",
         "lat": "", "lon": "", "theme": "T4", "confidence": "none",
         "source": "scopus-abstract", "matched": ""},
    ]

    def test_mappable_filter(self):
        keep_all = gm.mappable([dict(r) for r in self.ROWS], "none")
        self.assertEqual(len(keep_all), 2)  # a3 has no coords
        keep_high = gm.mappable([dict(r) for r in self.ROWS], "high")
        self.assertEqual(len(keep_high), 1)  # only a1 is high

    def test_kml_geojson_counts(self):
        rows = gm.mappable([dict(r) for r in self.ROWS], "none")
        with tempfile.TemporaryDirectory() as d:
            gm.write_kml(rows, d)
            gm.write_geojson(rows, d)
            counts = gm.write_country_counts(rows, d)
            with open(os.path.join(d, "study_locations.kml"), encoding="utf-8") as fh:
                kml = fh.read()
            self.assertIn("Montreal", kml)
            self.assertIn("<Placemark>", kml)
            with open(os.path.join(d, "study_locations.geojson"), encoding="utf-8") as fh:
                gj = json.load(fh)
            self.assertEqual(gj["type"], "FeatureCollection")
            self.assertEqual(len(gj["features"]), 2)
            self.assertEqual(gj["features"][0]["geometry"]["coordinates"], [-73.5, 45.5])
            self.assertEqual(counts["Canada"], 1)
            self.assertEqual(counts["Iran"], 1)


class TestEvidence(unittest.TestCase):
    def test_terms_include_reverse_aliases(self):
        terms = [t.lower() for t in
                 ex._evidence_terms("Shiraz", "United States of America", "Shiraz+USA")]
        self.assertIn("shiraz", terms)
        self.assertIn("chiraz", terms)   # reverse city alias
        self.assertIn("usa", terms)      # reverse country alias

    def test_find_evidence_prefers_title(self):
        fields = [("title", "A rooftop study in Montreal"),
                  ("abstract", "We surveyed Montreal, Canada."),
                  ("keywords", "solar; rooftop")]
        field, snippet = ex.find_evidence(["Montreal", "Canada"], fields)
        self.assertEqual(field, "title")
        self.assertIn("Montreal", snippet)

    def test_find_evidence_falls_to_abstract(self):
        fields = [("title", "A study of rooftops"),
                  ("abstract", "Intro sentence here. The case study is in Kabul, Afghanistan."),
                  ("keywords", "")]
        field, snippet = ex.find_evidence(["Kabul"], fields)
        self.assertEqual(field, "abstract")
        self.assertIn("Kabul", snippet)

    def test_write_provenance(self):
        row = {"citekey": "k1", "etude": "Cai et al.", "ville": "Montreal",
               "pays": "Canada", "lat": "45.5", "lon": "-73.5", "theme": "T2",
               "confidence": "high", "source": "scopus-abstract",
               "matched": "Montreal+Canada", "evidence_field": "abstract",
               "evidence": "The case study is in Montreal, Canada."}
        with tempfile.TemporaryDirectory() as d:
            rel = ex.write_provenance(d, row, "10.0/x")
            self.assertEqual(rel, "provenance/k1.md")
            with open(os.path.join(d, rel), encoding="utf-8") as fh:
                md = fh.read()
            self.assertIn("Montreal, Canada", md)
            self.assertIn("The case study is in Montreal, Canada.", md)


class TestFullText(unittest.TestCase):
    def test_focus_body_drops_references(self):
        body = "Study text about Montreal.\nReferences\nSmith studied Shiraz."
        focused = ex._focus_body(body)
        self.assertIn("Montreal", focused)
        self.assertNotIn("Shiraz", focused)   # reference list removed

    def test_match_fulltext_prefers_cue_sentence(self):
        # A cue sentence names the true site; a decoy sits in the (removed) refs.
        body = ("Background paragraph. Our case study is conducted in Montreal, "
                "Canada, over one year.\nReferences\nJones studied Shiraz, Iran.")
        loc, evidence = ex.match_fulltext(body, FAKE_GAZ)
        self.assertEqual(loc["ville"], "Montreal")
        self.assertEqual(loc["confidence"], "high")
        self.assertIn("case study", evidence.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
