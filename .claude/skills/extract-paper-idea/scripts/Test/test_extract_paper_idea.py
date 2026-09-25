import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import extract_paper_idea  # noqa: E402


FIXTURE_PAPER = r"""
\documentclass{article}
\usepackage[english]{babel}
\begin{document}
\title{A Sparse Attention Mechanism for Real-Time Control}
\begin{abstract}
This paper introduces an entirely unrelated gating trick for legacy conveyor belts,
unlike previous work in that separate domain.
\end{abstract}

\section{Introduction}
Real-time robotic control remains constrained by the cost of dense attention.
This paper proposes a sparse attention mechanism that reduces inference cost.
To the best of our knowledge, this is the first method that adapts sparsity
per joint at run time.

\section{Methodology}
The method partitions the attention matrix into joint-local blocks and prunes
blocks below a learned threshold.

\section{Results}
The proposed method achieves a 42\% reduction in inference latency on the
benchmark arm, with no measurable accuracy loss (p<0.01).

\section{Limitations and Future Work}
The approach has only been validated on a single robotic arm. Future work
will extend the method to multi-arm coordination.

\section{Conclusion}
This work showed that per-joint sparsity is a practical way to meet real-time
budgets.
\end{document}
"""

# Reproduces the reviewer's finding: a heading with no preceding terminal
# punctuation, immediately followed by a claim sentence. Without stripping the
# \section macro first, the backslash blocks the sentence-boundary lookahead
# in extract_contributions' splitter, gluing the heading and the claim
# together with whatever came before it.
GLUED_HEADING_PAPER = r"""
\documentclass{article}
\usepackage[english]{babel}
\begin{document}
\title{Self-Tuning Gain Scheduler}
\section{Introduction}
Prior industrial practice still relies extensively on manual gain tuning performed by a skilled
expert engineer over several days of on-site work, a process that does not scale well to large
fleets of heterogeneous robotic arms deployed across many separate factories and production lines
\section{Contributions}
This paper proposes a self-tuning gain scheduler that outperforms existing manual baselines on
every tested rig, adapting its parameters online without requiring any operator intervention
whatsoever, even under substantial payload variation across an entire operating shift.
\end{document}
"""


class ExtractPaperIdeaTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.paper_path = os.path.join(self.tmpdir.name, "paper.tex")
        with open(self.paper_path, "w", encoding="utf-8") as f:
            f.write(FIXTURE_PAPER)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_merge_schema_has_every_required_key(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        required = {
            "source", "title", "section_map", "background_context",
            "objective_purpose", "methodology_summary", "key_findings",
            "contribution_novelty", "limitations", "future_work",
            "implications", "hypotheses", "keyword_candidates", "existing_abstract",
            "existing_resume", "existing_abstract_present",
            "existing_resume_present", "contribution_status", "warnings",
        }
        self.assertEqual(required, set(result.keys()))

    def test_existing_abstract_is_captured_verbatim(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        self.assertIn("entirely unrelated gating trick", result["existing_abstract"])
        self.assertTrue(result["existing_abstract_present"])

    def test_absent_abstract_is_distinct_from_present_but_empty(self):
        bare_path = os.path.join(self.tmpdir.name, "bare2.tex")
        with open(bare_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{article}\begin{document}"
                     r"\section{Introduction}No abstract here at all, just prose that runs on for "
                     r"a while so the paper clears the minimum text length the scanner requires."
                     r"\end{document}")
        result = extract_paper_idea.build_extraction(bare_path)
        self.assertIsNone(result["existing_abstract"])
        self.assertFalse(result["existing_abstract_present"])

    def test_existing_abstract_and_bibliography_do_not_contaminate_the_marker_scan(self):
        # The fixture's OWN abstract states a DIFFERENT contribution ("gating trick for legacy
        # conveyor belts") than the paper's real one (sparse attention). If the scan is not
        # scoped away from the abstract, this wrong claim leaks into contribution_novelty.
        result = extract_paper_idea.build_extraction(self.paper_path)
        joined = " ".join(result["contribution_novelty"]).lower()
        self.assertNotIn("conveyor belt", joined)
        self.assertNotIn("gating trick", joined)

    def test_a_heading_with_no_preceding_period_does_not_glue_sentences_together(self):
        glued_path = os.path.join(self.tmpdir.name, "glued.tex")
        with open(glued_path, "w", encoding="utf-8") as f:
            f.write(GLUED_HEADING_PAPER)
        result = extract_paper_idea.build_extraction(glued_path)
        joined = " ".join(result["contribution_novelty"]).lower()
        self.assertIn("this paper proposes a self-tuning gain scheduler", joined)
        # The claim sentence must NOT carry the unrelated Introduction prose or the literal
        # macro text glued onto its front - both are symptoms of the same splitter defect.
        self.assertNotIn("\\section", joined)
        self.assertNotIn("prior industrial practice", joined)

    def test_contribution_status_is_reported(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        self.assertEqual(result["contribution_status"], "ok")

    def test_contribution_status_empty_is_flagged_in_warnings(self):
        tiny_path = os.path.join(self.tmpdir.name, "tiny.tex")
        with open(tiny_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{article}\begin{document}\section{Intro}Too short."
                     r"\end{document}")
        result = extract_paper_idea.build_extraction(tiny_path)
        self.assertEqual(result["contribution_status"], "empty")
        self.assertTrue(any("contribution scan status" in w for w in result["warnings"]))

    def test_section_map_carries_a_text_excerpt(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        intro = next(s for s in result["section_map"] if s["title"] == "Introduction")
        self.assertIn("real-time robotic control", intro["text"].lower())

    def test_document_type_defaults_to_paper_without_uqac_cls(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        self.assertEqual(result["source"]["document_type"], "paper")

    def test_contribution_sentence_is_found_from_the_papers_own_text(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        joined = " ".join(result["contribution_novelty"])
        self.assertIn("first method", joined.lower())

    def test_future_work_section_is_surfaced(self):
        result = extract_paper_idea.build_extraction(self.paper_path)
        joined = " ".join(result["future_work"])
        self.assertIn("multi-arm", joined.lower())

    def test_a_paper_with_no_sections_at_all_warns_instead_of_crashing(self):
        bare_path = os.path.join(self.tmpdir.name, "bare.tex")
        with open(bare_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{article}\begin{document}Just one line.\end{document}")
        result = extract_paper_idea.build_extraction(bare_path)
        self.assertTrue(any("section" in w.lower() for w in result["warnings"]))
        self.assertEqual(result["section_map"], [])

    def test_uqac_cls_in_an_included_file_is_still_detected(self):
        main_path = os.path.join(self.tmpdir.name, "main.tex")
        setup_path = os.path.join(self.tmpdir.name, "setup.tex")
        with open(setup_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{uqac}")
        with open(main_path, "w", encoding="utf-8") as f:
            f.write("\\input{setup}\n\\begin{document}\n\\section{Introduction}\nText.\n"
                     "\\end{document}")
        result = extract_paper_idea.build_extraction(main_path)
        self.assertEqual(result["source"]["document_type"], "thesis")

    def test_cli_json_output_is_valid_json(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = extract_paper_idea.main([self.paper_path, "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIn("section_map", parsed)

    def test_babel_multi_option_uses_the_last_language(self):
        # Babel's own convention: the LAST language option in the list is the main document
        # language. [french,english] means English, not French.
        multi_path = os.path.join(self.tmpdir.name, "multi.tex")
        with open(multi_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{article}\usepackage[french,english]{babel}"
                     r"\begin{document}\section{Intro}Some prose that is long enough to clear "
                     r"the minimum text length the scanner requires before judging anything."
                     r"\end{document}")
        result = extract_paper_idea.build_extraction(multi_path)
        self.assertEqual(result["source"]["language"], "en")

    def test_babel_french_alias_frenchb_is_recognised(self):
        fr_path = os.path.join(self.tmpdir.name, "fr.tex")
        with open(fr_path, "w", encoding="utf-8") as f:
            f.write(r"\documentclass{article}\usepackage[frenchb]{babel}"
                     r"\begin{document}\section{Intro}Du texte suffisamment long pour depasser "
                     r"le seuil minimal de longueur exige par l'analyseur avant tout jugement."
                     r"\end{document}")
        result = extract_paper_idea.build_extraction(fr_path)
        self.assertEqual(result["source"]["language"], "fr")

    def test_cli_json_survives_a_non_cp1252_character_on_a_cp1252_stream(self):
        # Reproduces the reviewer's finding: a title containing a character outside cp1252
        # (e.g. U+2264 <=) crashed main()'s --json print with UnicodeEncodeError on a Windows
        # console stream, after the JSON file had already been written.
        import io
        title_path = os.path.join(self.tmpdir.name, "unicode_title.tex")
        with open(title_path, "w", encoding="utf-8") as f:
            f.write("\\documentclass{article}\\begin{document}"
                     "\\title{A bound of ≤ 1 on the error}"
                     "\\section{Intro}Prose long enough to clear the minimum text length the "
                     "scanner requires before judging anything at all in this fixture."
                     "\\end{document}")
        raw = io.BytesIO()
        # A real Windows console stream is a reconfigurable TextIOWrapper starting on cp1252 -
        # configure_streams() checks hasattr(stream, "reconfigure") and only such a stream lets
        # it upgrade to utf-8 before the crashing character is ever written.
        cp1252_stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
        old_stdout = sys.stdout
        sys.stdout = cp1252_stream
        try:
            rc = extract_paper_idea.main([title_path, "--json"])
            sys.stdout.flush()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(rc, 0)
        parsed = json.loads(raw.getvalue().decode("utf-8", errors="replace"))
        self.assertIn("bound of", parsed["title"])


if __name__ == "__main__":
    unittest.main()
