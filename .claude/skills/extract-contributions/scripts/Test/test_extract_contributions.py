"""
test_extract_contributions.py - offline tests for the extract-contributions skill.

No PDF, no network, no model: every case feeds a synthetic text string, and the
two file-reading cases write a plain .txt that goes through the same code path
as a PDF would.

Run:
    cd .claude/skills/extract-contributions/scripts
    python Test/test_extract_contributions.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import extract_contributions as ec  # noqa: E402

MARKERS = ec.load_markers()


def _write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class SentenceSplitTest(unittest.TestCase):
    """A split that cuts inside an abbreviation loses the sentence it was after."""

    def test_abbreviations_do_not_end_a_sentence(self):
        got = ec.split_sentences("We follow Smith et al. and propose a method. Then we stop.")
        self.assertEqual(len(got), 2)
        self.assertIn("et al.", got[0])

    def test_decimals_do_not_end_a_sentence(self):
        got = ec.split_sentences("The score reached 41.7 percent overall. That is low.")
        self.assertEqual(len(got), 2)
        self.assertIn("41.7", got[0])

    def test_a_normal_boundary_still_splits(self):
        # Negative control: without this, a splitter that never splits passes.
        self.assertEqual(len(ec.split_sentences("First one here. Second one here.")), 2)

    def test_a_closing_quote_after_the_terminator_ends_the_sentence(self):
        # Measured 2026-09-13 on davis2021upzonings, where the paper's own gap
        # statement came back welded to a clause about other authors.
        got = ec.split_sentences(
            'The authors argue that \u201cstates should confer the right.\u201d '
            'Despite these valuable contributions, minimal research has examined it.')
        self.assertEqual(len(got), 2)
        self.assertTrue(got[1].startswith("Despite"))

    def test_the_closing_quote_stays_on_its_own_sentence(self):
        # re.split drops what it matches, so a pattern that CONSUMED the quote
        # would pass the count assertion above while deleting the character.
        got = ec.split_sentences(
            'He said \u201cit is done.\u201d Then the work stopped for a while.')
        self.assertTrue(got[0].endswith("\u201d"))

    def test_a_straight_quote_and_a_bracket_close_a_sentence_too(self):
        straight = ec.split_sentences('He said "it is done." Then the work stopped here.')
        bracket = ec.split_sentences("The value was corrected (see note.) Then the work stopped.")
        self.assertEqual(len(straight), 2)
        self.assertEqual(len(bracket), 2)

    def test_a_quotation_inside_a_sentence_does_not_split_it(self):
        # The load-bearing control: the new boundary must need a CAPITAL after
        # the quote, or every quoted phrase mid-sentence becomes a break.
        got = ec.split_sentences(
            'They called it \u201cupzoning.\u201d and then continued the argument here.')
        self.assertEqual(len(got), 1)


class ScanTest(unittest.TestCase):
    """What counts as a stated contribution, and what must not."""

    def test_a_contribution_sentence_is_found_and_labelled(self):
        text = ("Buildings are tall in cities of many kinds today. "
                "This paper presents an integrative approach for decision making "
                "on urban densification through roof stacking. "
                "The weather was fine that year.")
        got = ec.scan_contributions(text, MARKERS)
        self.assertEqual(len(got["sentences"]), 1)
        self.assertEqual(got["sentences"][0]["kind"], "contribution")
        self.assertIn("this paper presents", got["sentences"][0]["marker"])

    def test_a_novelty_claim_is_labelled_novelty(self):
        text = ("To the best of our knowledge this is the first framework that "
                "fuses uncertain visual detection with regulatory extraction.")
        got = ec.scan_contributions(text, MARKERS)
        self.assertEqual(got["kinds_found"], ["novelty"])

    def test_prose_with_no_claim_yields_nothing(self):
        # The load-bearing negative control: a scanner that matches anything
        # would make every paper look like it states a contribution.
        text = ("The region has grown since 1949. Rainfall was measured monthly "
                "at four stations across the plain during the whole period.")
        self.assertEqual(ec.scan_contributions(text, MARKERS)["sentences"], [])

    def test_position_separates_introduction_from_conclusion(self):
        early = "We propose a new method for this task. " + ("Filler sentence here. " * 40)
        late = ("Filler sentence here. " * 40) + "We propose a new method for this task."
        pos_early = ec.scan_contributions(early, MARKERS)["sentences"][0]["position"]
        pos_late = ec.scan_contributions(late, MARKERS)["sentences"][0]["position"]
        self.assertLess(pos_early, 0.2)
        self.assertGreater(pos_late, 0.8)

    def test_a_sentence_is_reported_once_even_on_two_markers(self):
        text = ("This paper presents a novel method that, to the best of our "
                "knowledge, has not been proposed before in this field.")
        got = ec.scan_contributions(text, MARKERS)
        self.assertEqual(len(got["sentences"]), 1)

    def test_too_short_and_too_long_sentences_are_skipped(self):
        caps = MARKERS["caps"]
        short = "We propose it."
        long = "We propose a method " + ("word " * (caps["max_sentence_words"] + 5)) + "."
        self.assertEqual(ec.scan_contributions(short, MARKERS)["sentences"], [])
        self.assertEqual(ec.scan_contributions(long, MARKERS)["sentences"], [])

    def test_the_hit_cap_is_reported_as_truncated(self):
        text = "This paper presents a method for the task at hand. " * 60
        got = ec.scan_contributions(text, MARKERS)
        self.assertLessEqual(len(got["sentences"]), MARKERS["caps"]["max_sentences"])


class FileStatusTest(unittest.TestCase):
    """Four outcomes that must never be merged into each other."""

    def test_a_paper_with_a_contribution_is_ok(self):
        body = ("Context sentence number one here. " * 30
                + "This paper proposes a calibrated non compensatory score for "
                  "screening candidate buildings across a whole borough. ")
        with tempfile.TemporaryDirectory() as tmp:
            rec = ec.analyse_file(_write(tmp, "good2020key.txt", body), MARKERS)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["citekey"], "good2020key")

    def test_a_paper_stating_nothing_is_no_contribution_not_empty(self):
        body = "Rainfall was measured at four stations every month. " * 40
        with tempfile.TemporaryDirectory() as tmp:
            rec = ec.analyse_file(_write(tmp, "silent2020key.txt", body), MARKERS)
        self.assertEqual(rec["status"], "no-contribution")
        self.assertGreater(rec["chars"], MARKERS["caps"]["min_text_chars"])

    def test_a_stub_is_empty_not_no_contribution(self):
        # This is the one-page preview case. Calling it "no-contribution" would
        # blame the paper for a retrieval failure.
        with tempfile.TemporaryDirectory() as tmp:
            rec = ec.analyse_file(_write(tmp, "stub2020key.txt", "Title. Abstract."), MARKERS)
        self.assertEqual(rec["status"], "empty")
        self.assertIn("preview", rec["reason"])

    def test_an_unreadable_file_is_reported_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = ec.analyse_file(os.path.join(tmp, "absent2020key.txt"), MARKERS)
        self.assertEqual(rec["status"], "unreadable")
        self.assertTrue(rec["reason"])


class CatalogueTest(unittest.TestCase):
    """The marker list is data, and its absence is an error, not an empty result."""

    def test_the_shipped_catalogue_declares_the_five_kinds(self):
        # "gap" joined the four on 2026-09-13. A paper in the planning and
        # social-science idiom states its contribution as an absence in the
        # prior work ("minimal empirical research to date has examined"), which
        # none of the original four kinds could hold.
        self.assertEqual(sorted(MARKERS["kinds"]),
                         ["contribution", "gap", "method", "novelty", "result"])

    def test_the_shipped_catalogue_carries_exclusions(self):
        # Without these the contribution markers fire on the CRediT block of
        # every Elsevier paper, so an empty list is not a neutral default.
        self.assertTrue(MARKERS["exclusions"]["phrases"])

    def test_a_missing_catalogue_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                ec.load_markers(os.path.join(tmp, "nope.json"))
        self.assertIn("nope.json", str(ctx.exception))

    def test_an_empty_catalogue_is_refused_rather_than_scanning_with_no_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "empty.json", json.dumps({"kinds": {}}))
            with self.assertRaises(SystemExit):
                ec.load_markers(path)


class ExpandTest(unittest.TestCase):
    """Directory expansion must skip the bookkeeping files of a refs/ folder."""

    def test_underscore_files_and_foreign_extensions_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "_manifest.json", "{}")
            _write(tmp, "_failed.md", "x")
            _write(tmp, "paper2020key.txt", "x")
            _write(tmp, "notes.docx", "x")
            got = [os.path.basename(p) for p in ec.expand([tmp], None)]
        self.assertEqual(got, ["paper2020key.txt"])

    def test_only_restricts_to_the_named_citekeys(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "a2020key.txt", "x")
            _write(tmp, "b2020key.txt", "x")
            got = [os.path.basename(p) for p in ec.expand([tmp], ["b2020key"])]
        self.assertEqual(got, ["b2020key.txt"])


class LigatureTest(unittest.TestCase):
    """A marker in correct English must still match ligature-damaged text.

    Measured 2026-09-13 on financement/refs/: pymupdf4llm drops the fi and fl
    ligatures of Elsevier PDFs, so davis2021upzonings reads "this paper fnds"
    and "fll this gap". The text is damaged and cannot be repaired by guessing
    where an "i" belongs, so the marker is damaged the same way instead.
    """

    def test_the_damaged_spelling_is_derived(self):
        self.assertEqual(ec.deligature("this paper finds"), "this paper fnds")
        self.assertEqual(ec.deligature("conflict of interest"), "confict of interest")

    def test_a_phrase_with_no_ligature_is_unchanged(self):
        self.assertEqual(ec.deligature("gap in the literature"), "gap in the literature")

    def test_a_marker_matches_the_damaged_text(self):
        self.assertTrue(ec.phrase_in("this paper finds", "using new york, this paper fnds that"))

    def test_a_marker_still_matches_undamaged_text(self):
        # Negative control for the derivation: it must not replace matching.
        self.assertTrue(ec.phrase_in("this paper finds", "this paper finds that"))

    def test_an_absent_marker_matches_neither_spelling(self):
        # Without this, a matcher that returned True always would pass above.
        self.assertFalse(ec.phrase_in("this paper finds", "rainfall was measured monthly"))


class ExclusionTest(unittest.TestCase):
    """Boilerplate carrying a marker word is not a claim.

    Both sentences below are verbatim from agbossou2026nolandtake (Land Use
    Policy 169, 2026, 108156), and both contain the word "contribution".
    """

    CREDIT = ("CRediT authorship contribution statement Edouard Patault: "
              "Writing - review & editing, Project administration, Data curation.")
    THANKS = ("We thank the reviewers for their detailed and insightful comments, "
              "which have helped us substantially improve the clarity, rigor, and "
              "scientific contribution of our work.")

    def test_a_credit_block_is_not_a_contribution(self):
        self.assertEqual(ec.scan_contributions(self.CREDIT, MARKERS)["sentences"], [])

    def test_an_acknowledgement_is_not_a_contribution(self):
        self.assertEqual(ec.scan_contributions(self.THANKS, MARKERS)["sentences"], [])

    def test_a_real_claim_using_the_same_word_is_still_found(self):
        # The load-bearing control: the exclusions must remove the boilerplate
        # and nothing else, or the fix is just the old false negative again.
        claim = ("A central methodological contribution is the systematic operational "
                 "integration of the model with the objectives of the French SCoT.")
        got = ec.scan_contributions(claim, MARKERS)
        self.assertEqual(len(got["sentences"]), 1)
        self.assertEqual(got["sentences"][0]["kind"], "contribution")


class MeasuredPapersTest(unittest.TestCase):
    """The regression this catalogue was extended for, 2026-09-13.

    Every string here is verbatim extracted text from a paper in the BuildingGIS
    corpus, ligature damage included. The 2026-09-12 catalogue matched none of
    the davis sentences and only the result and method sentences of agbossou,
    so the corpus figure of that day (72 of 92 papers stating a contribution)
    was a property of the marker list and not of the corpus.
    """

    AGBOSSOU = {
        "methodological": ("A central methodological contribution is the systematic "
                           "operational integration of the model with the objectives of "
                           "the French SCoT, a statutory strategic planning document."),
        "theoretical": ("The core theoretical contribution of this research is the "
                        "empirical validation that the effectiveness of densification as "
                        "a tool for achieving NNLT is inherently context-dependent."),
        "addresses": ("This paper addresses this gap by investigating the efficacy of "
                      "granular and spatially differentiated density thresholds as a "
                      "mechanism for achieving NNLT."),
        "three_key": ("The approach offers three key contributions: spatial explicitness "
                      "identifying precisely where densification must occur, scenario "
                      "testing evaluating policy trade-offs before implementation, and "
                      "target feasibility quantifying whether housing targets are "
                      "achievable within NNLT constraints."),
    }

    DAVIS = {
        "examines": ("To help fll this gap in the literature, this paper examines how "
                     "upzoning activity is associated with subsequent change in the "
                     "non-Hispanic white population in New York City between 2000 and 2010."),
        "minimal_empirical": ("Despite these cleavages about the effects of upzonings on "
                              "gentrifcation and displacement, minimal empirical research "
                              "to date has examined the link between upzonings and "
                              "neighborhood demographic change."),
        "finds": ("Using New York as a case study, this paper fnds that upzoning activity "
                  "is positively and signifcantly associated with the odds of a census "
                  "tract becoming whiter."),
        "minimal_research": ("Despite these valuable contributions to the literature, "
                             "minimal research has examined the link between residential "
                             "upzonings and neighborhood demographic change."),
    }

    def _kind_of(self, sentence):
        got = ec.scan_contributions(sentence, MARKERS)["sentences"]
        self.assertEqual(len(got), 1, "expected exactly one hit for: %s" % sentence[:60])
        return got[0]["kind"]

    def test_agbossou_states_its_two_contributions(self):
        self.assertEqual(self._kind_of(self.AGBOSSOU["methodological"]), "contribution")
        self.assertEqual(self._kind_of(self.AGBOSSOU["theoretical"]), "contribution")

    def test_agbossou_states_its_object_and_its_summary(self):
        self.assertEqual(self._kind_of(self.AGBOSSOU["addresses"]), "contribution")
        self.assertEqual(self._kind_of(self.AGBOSSOU["three_key"]), "contribution")

    def test_davis_is_not_a_silent_paper(self):
        self.assertEqual(self._kind_of(self.DAVIS["examines"]), "contribution")
        self.assertEqual(self._kind_of(self.DAVIS["finds"]), "result")

    def test_davis_states_its_gap_twice(self):
        self.assertEqual(self._kind_of(self.DAVIS["minimal_empirical"]), "gap")
        self.assertEqual(self._kind_of(self.DAVIS["minimal_research"]), "gap")

    def test_the_whole_davis_abstract_reports_both_kinds(self):
        body = " ".join(self.DAVIS.values())
        rec = ec.scan_contributions(body, MARKERS)
        self.assertIn("contribution", rec["kinds_found"])
        self.assertIn("gap", rec["kinds_found"])

    def test_unrelated_planning_prose_is_still_silent(self):
        # Negative control: the catalogue grew by one kind and by dozens of
        # phrases, so the risk that it now answers "contribution" to anything
        # is real, and this is what asserts against it.
        prose = ("Zoning districts in the borough were mapped at the lot level. "
                 "Rainfall was measured monthly at four stations during the period.")
        self.assertEqual(ec.scan_contributions(prose, MARKERS)["sentences"], [])

class StripTexCommentsTest(unittest.TestCase):
    """A comment must stop being text without moving any other character."""

    def test_a_comment_is_blanked_and_the_length_is_kept(self):
        src = "prose here % a note\nmore prose"
        got = ec.strip_tex_comments(src)
        self.assertEqual(len(got), len(src))
        self.assertNotIn("a note", got)
        self.assertIn("more prose", got)

    def test_an_escaped_percent_is_not_a_comment(self):
        # 100\% is a percentage; blanking from there would eat the rest of the
        # line, and with it the \cite the sentence carries.
        got = ec.strip_tex_comments("a rise of 100\\% was observed here")
        self.assertIn("was observed here", got)

    def test_the_line_number_of_later_text_is_unchanged(self):
        src = "line one % note\nline two \\cite{key2020a}\n"
        got = ec.strip_tex_comments(src)
        self.assertEqual(got.count("\n", 0, got.index("\\cite")), 1)


class CitingSentencesTest(unittest.TestCase):
    """Which sentence carries which citation, and on what line."""

    TEX = ("\\section{Intro}\n"
           "Roof stacking raises the housing supply in dense boroughs "
           "\\cite{amer2017roofstacking}. The permit record is the only "
           "ground truth available here \\cite{otto2026sanborn,lin2023goad}.\n"
           "\n"
           "A later paragraph makes no claim at all about anything.\n")

    def test_the_sentence_carrying_the_citation_is_returned(self):
        got = ec.citing_sentences(self.TEX)
        self.assertIn("amer2017roofstacking", got)
        sentence = got["amer2017roofstacking"][0]["sentence"]
        self.assertTrue(sentence.startswith("Roof stacking raises"))
        self.assertNotIn("permit record", sentence)

    def test_a_multi_key_citation_is_reported_under_every_key(self):
        # The sentence asserts something of both papers, so both must be judged
        # against it rather than only the first.
        got = ec.citing_sentences(self.TEX)
        for key in ("otto2026sanborn", "lin2023goad"):
            self.assertIn("permit record", got[key][0]["sentence"])

    def test_the_line_number_is_the_line_of_the_file(self):
        got = ec.citing_sentences(self.TEX)
        self.assertEqual(got["amer2017roofstacking"][0]["line"], 2)

    def test_a_citation_inside_a_comment_is_not_reported(self):
        # The load-bearing case for blanking: a commented-out citation is not
        # in the manuscript, and auditing it would invent work.
        got = ec.citing_sentences("Real prose \\cite{live2020key}.\n"
                                  "% dead prose \\cite{dead2020key}.\n")
        self.assertIn("live2020key", got)
        self.assertNotIn("dead2020key", got)

    def test_prose_with_no_citation_yields_nothing(self):
        # Negative control: a reader that returned every sentence would pass
        # every assertion above.
        self.assertEqual(ec.citing_sentences("Nothing is cited in this text."), {})

    def test_two_occurrences_of_one_key_are_both_kept(self):
        tex = ("First claim about the corpus is stated here \\cite{k2020a}. "
               "Second claim about the corpus is stated here \\cite{k2020a}.")
        self.assertEqual(len(ec.citing_sentences(tex)["k2020a"]), 2)


class ValidateManuscriptTest(unittest.TestCase):
    """Pairing a manuscript with its refs/, including the missing-paper case."""

    TEX = ("The method was calibrated on permits "
           "\\cite{present2020key}. A second sentence cites a paper that was "
           "never retrieved \\cite{absent2020key}.\n")

    def _fixture(self, tmp):
        refs = os.path.join(tmp, "refs")
        os.makedirs(refs)
        body = ("Context sentence number one here. " * 30
                + "This paper presents a calibrated non compensatory score for "
                  "screening candidate buildings across a whole borough. ")
        _write(refs, "present2020key.txt", body)
        tex = _write(tmp, "manuscript.tex", self.TEX)
        return tex, refs

    def test_a_cited_paper_carries_its_contribution_and_its_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tex, refs = self._fixture(tmp)
            recs = {r["citekey"]: r for r in ec.validate_manuscript(tex, refs, MARKERS)}
        rec = recs["present2020key"]
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["cite_count"], 1)
        self.assertIn("calibrated on permits", rec["citations"][0]["sentence"])

    def test_a_paper_absent_from_refs_is_no_fulltext_not_no_contribution(self):
        # Merging the two would report a retrieval gap as a silent paper, which
        # is the confusion this skill exists to prevent.
        with tempfile.TemporaryDirectory() as tmp:
            tex, refs = self._fixture(tmp)
            recs = {r["citekey"]: r for r in ec.validate_manuscript(tex, refs, MARKERS)}
        rec = recs["absent2020key"]
        self.assertEqual(rec["status"], "no-fulltext")
        self.assertIn("absent2020key", rec["reason"])
        self.assertEqual(rec["sentences"], [])


class WriteContributionFilesTest(unittest.TestCase):
    """One note per cited paper, kept where a corpus scan will not eat it."""

    def _records(self):
        return [{
            "citekey": "present2020key", "file": "present2020key.txt", "chars": 1200,
            "status": "ok", "kinds_found": ["contribution"], "cite_count": 1,
            "sentences": [{"kind": "contribution", "marker": "this paper presents",
                           "sentence": "This paper presents a calibrated score.",
                           "position": 0.9}],
            "citations": [{"line": 12, "sentence": "The method was calibrated on permits."}],
        }]

    def test_one_file_per_paper_carries_both_halves(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "_contributions")
            written = ec.write_contribution_files(self._records(), out)
            with open(written[0], encoding="utf-8") as handle:
                text = handle.read()
        self.assertEqual(len(written), 1)
        self.assertIn("This paper presents a calibrated score.", text)
        self.assertIn("The method was calibrated on permits.", text)
        self.assertIn("line 12", text)

    def test_a_silent_paper_says_so_without_claiming_the_paper_is_silent(self):
        recs = self._records()
        recs[0].update(status="no-contribution", kinds_found=[], sentences=[])
        with tempfile.TemporaryDirectory() as tmp:
            written = ec.write_contribution_files(recs, os.path.join(tmp, "_contributions"))
            with open(written[0], encoding="utf-8") as handle:
                text = handle.read()
        self.assertIn("marker catalogue", text)

    def test_the_notes_are_not_read_back_as_full_texts(self):
        # These land inside refs/. expand() skips a name starting with "_", so
        # a later corpus scan must not pick the notes up as papers.
        with tempfile.TemporaryDirectory() as tmp:
            refs = os.path.join(tmp, "refs")
            os.makedirs(refs)
            _write(refs, "paper2020key.txt", "x")
            ec.write_contribution_files(self._records(),
                                        os.path.join(refs, "_contributions"))
            got = [os.path.basename(p) for p in ec.expand([refs], None)]
        self.assertEqual(got, ["paper2020key.txt"])

class NumberCrossCheckTest(unittest.TestCase):
    """A citing sentence's figures, confronted with the paper's own text.

    The manuscript audited on 2026-09-13 is French and its corpus is English, so
    the decimal comma is the whole difficulty: without normalisation, "52,5 AP"
    and "52.5 AP" are two different claims and every figure in the manuscript
    reads as unsupported.
    """

    def test_the_decimal_comma_and_the_decimal_point_are_one_number(self):
        self.assertEqual(ec.normalise_number("52,5"), ec.normalise_number("52.5"))

    def test_a_thousands_separator_is_not_a_decimal(self):
        self.assertEqual(ec.normalise_number("1\u00a0800"), "1800")
        self.assertEqual(ec.normalise_number("1 800"), "1800")

    def test_a_trailing_zero_does_not_make_a_second_number(self):
        self.assertEqual(ec.normalise_number("0,90"), ec.normalise_number("0.9"))
        self.assertEqual(ec.normalise_number("43,0"), "43")

    def test_a_french_figure_is_found_in_an_english_paper(self):
        got = ec.check_numbers("atteint 52,5 AP en zero-tir",
                               "reaches 52.5 AP on COCO in zero-shot")
        self.assertEqual([(c["value"], c["in_paper"]) for c in got], [("52.5", True)])

    def test_a_figure_absent_from_the_paper_is_reported_absent(self):
        # The negative control that makes the check worth running: without it a
        # checker answering True always would pass the case above.
        got = ec.check_numbers("une perte de 43 %", "reaches 52.5 AP on COCO")
        self.assertEqual([(c["value"], c["in_paper"]) for c in got], [("43", False)])

    def test_a_one_digit_number_is_ignored(self):
        # "1" and "3" match almost any document, so reporting them would bury
        # the figures that carry a claim.
        self.assertEqual(ec.check_numbers("dans 3 villes", "there were 9 cities"), [])

    def test_a_repeated_figure_is_reported_once(self):
        got = ec.check_numbers("de 34 a 94 %, soit 34 au minimum", "from 34 to 94 percent")
        self.assertEqual([c["value"] for c in got], ["34", "94"])

    def test_the_sentence_keeps_its_own_spelling_in_the_report(self):
        # The reader has to find the figure in the manuscript, so the report
        # shows it as written there, not as normalised.
        got = ec.check_numbers("atteint 52,5 AP", "reaches 52.5 AP")
        self.assertEqual(got[0]["as_written"], "52,5")

class CitationYearTest(unittest.TestCase):
    r"""A citekey is a pointer, not a claim.

    Measured on the first real run over the MITACS proposal: of 32 figures
    reported absent from their paper, roughly half were the YEAR of a citekey
    standing in the same sentence. \cite{otto2026sanborn} put "2026" into a
    sentence checked against Lin 2023, and the audit called it an unsupported
    figure. Half a report's findings being an artefact of the reader is worse
    than no report.
    """

    SENTENCE = ("Lin et al.~\\cite{lin2023sanborn} puis Otto et "
                "Lin~\\cite{otto2026sanborn} atteignent un F1 de 0,9.")

    def test_the_citation_commands_are_removed_from_the_claim(self):
        got = ec.claim_text(self.SENTENCE)
        self.assertNotIn("2026", got)
        self.assertNotIn("lin2023sanborn", got)
        self.assertIn("F1 de 0,9", got)

    def test_only_the_asserted_figure_is_checked(self):
        got = ec.check_numbers(self.SENTENCE, "we reach an F1 of 0.9 on Sanborn plates")
        self.assertEqual([(c["as_written"], c["in_paper"]) for c in got], [("0,9", True)])

    def test_a_year_in_the_prose_is_still_checked(self):
        # The control that keeps the fix honest: only the CITATION is dropped.
        # A year the sentence actually asserts is a claim like any other.
        got = ec.check_numbers("Le corpus couvre la periode 1949 a 2006 \\cite{k2010a}.",
                               "the period from 1949 to 2006 was studied")
        self.assertEqual(sorted(c["value"] for c in got), ["1949", "2006"])


class AnalyseFileReuseTest(unittest.TestCase):
    """The full text is read once, not once per consumer.

    Parsing a 7 MB PDF twice per cited key doubled a corpus run of 51 papers.
    """

    def test_a_supplied_text_is_used_without_touching_the_file(self):
        body = ("Context sentence number one here. " * 30
                + "This paper presents a calibrated non compensatory score for "
                  "screening candidate buildings across a whole borough. ")
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "ghost2020key.pdf")   # never created
            rec = ec.analyse_file(absent, MARKERS, text=body)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["citekey"], "ghost2020key")

    def test_without_a_supplied_text_a_missing_file_is_still_unreadable(self):
        # Negative control: the new parameter must not turn a real failure into
        # a pass by making the read optional.
        with tempfile.TemporaryDirectory() as tmp:
            rec = ec.analyse_file(os.path.join(tmp, "ghost2020key.txt"), MARKERS)
        self.assertEqual(rec["status"], "unreadable")

class ValidateOnlyTest(unittest.TestCase):
    """`--only` has to make a targeted run cheap, or it is decoration.

    Measured 2026-09-14: validate mode parsed every cited paper and only then
    dropped the records the caller had not asked for, so asking for one key cost
    a whole corpus pass - 51 PDFs, one of them 7 MB, about eight minutes. A flag
    that changes the report and not the work is the failure class this
    repository keeps legislating against.
    """

    TEX = ("The method was calibrated on permits \\cite{wanted2020key}. "
           "A second claim rests on another paper \\cite{other2020key}.\n")

    def _fixture(self, tmp):
        refs = os.path.join(tmp, "refs")
        os.makedirs(refs)
        body = ("Context sentence number one here. " * 30
                + "This paper presents a calibrated non compensatory score for "
                  "screening candidate buildings across a whole borough. ")
        _write(refs, "wanted2020key.txt", body)
        _write(refs, "other2020key.txt", body)
        return _write(tmp, "manuscript.tex", self.TEX), refs

    def test_only_the_requested_paper_is_read_from_disk(self):
        read = []
        original = ec.read_any

        def spy(path):
            read.append(os.path.basename(path))
            return original(path)

        with tempfile.TemporaryDirectory() as tmp:
            tex, refs = self._fixture(tmp)
            ec.read_any = spy
            try:
                recs = ec.validate_manuscript(tex, refs, MARKERS, only=["wanted2020key"])
            finally:
                ec.read_any = original
        self.assertEqual([r["citekey"] for r in recs], ["wanted2020key"])
        self.assertEqual(read, ["wanted2020key.txt"])

    def test_without_only_every_cited_paper_is_read(self):
        # The positive control: without it, an implementation that read NOTHING
        # would satisfy the assertion above.
        read = []
        original = ec.read_any

        def spy(path):
            read.append(os.path.basename(path))
            return original(path)

        with tempfile.TemporaryDirectory() as tmp:
            tex, refs = self._fixture(tmp)
            ec.read_any = spy
            try:
                recs = ec.validate_manuscript(tex, refs, MARKERS)
            finally:
                ec.read_any = original
        self.assertEqual(sorted(r["citekey"] for r in recs),
                         ["other2020key", "wanted2020key"])
        self.assertEqual(sorted(read), ["other2020key.txt", "wanted2020key.txt"])

if __name__ == "__main__":
    unittest.main()
