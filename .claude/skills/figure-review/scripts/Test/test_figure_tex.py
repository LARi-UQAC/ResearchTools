"""
Offline tests of figure_tex.py: the figures of a LaTeX document, their source kinds, the citations
and the three script checks that need only the text. Documents are fictitious and built in a temporary
folder (R34).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import figure_checks
import figure_tex

CRITERIA = Path(__file__).parent.parent.parent / "assets" / "figure_criteria.json"

MIXED = r"""
\section{Results}
Figure~\ref{fig:inline-tikz-plan} shows the plan, \autoref{fig:from-input-file} the layout.
\begin{figure}[htbp]
  \centering
  \begin{tikzpicture}\node (a) {A};\end{tikzpicture}
  \caption{The plan of the cell.}\label{fig:inline-tikz-plan}
\end{figure}
\begin{figure}
  \input{fig.tikz}
  \caption{The layout.}\label{fig:from-input-file}
\end{figure}
\begin{figure}
  \includegraphics[width=5cm]{schema}
  \caption{A schema exported from draw.io.}\label{fig:schema-from-drawio}
\end{figure}
\begin{figure}
  \includesvg{curve}
  \caption{A curve.}\label{fig:curve-as-svg}
\end{figure}
\begin{figure}
  \includegraphics{scan.pdf}\includegraphics{photo.png}\includegraphics{photo2.jpg}
  \caption{Three files.}\label{fig:three-plain-files}
\end{figure}
"""


def make_files(folder: Path) -> None:
    (folder / "fig.tikz").write_text(r"\begin{tikzpicture}\node {B};\end{tikzpicture}", encoding="utf-8")
    (folder / "schema.drawio").write_text("<mxfile><diagram/></mxfile>", encoding="utf-8")
    (folder / "schema.pdf").write_bytes(b"%PDF-1.4")


class TestFigureTex(unittest.TestCase):

    def setUp(self):
        self.criteria = figure_checks.load_criteria(CRITERIA)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        make_files(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, figure):
        return [s["kind"] for s in figure["sources"]]

    def test_mixed_document_lists_each_source_kind(self):
        figs = figure_tex.figures(MIXED, self.base)
        self.assertEqual([f["label"] for f in figs], [
            "fig:inline-tikz-plan", "fig:from-input-file", "fig:schema-from-drawio",
            "fig:curve-as-svg", "fig:three-plain-files"])
        self.assertEqual(self.kinds(figs[0]), ["tikz"])
        self.assertEqual(self.kinds(figs[1]), ["tikz"])
        self.assertEqual(self.kinds(figs[2]), ["drawio"])
        self.assertEqual(self.kinds(figs[3]), ["svg"])
        self.assertEqual(self.kinds(figs[4]), ["pdf", "png", "jpg"])
        self.assertEqual(figs[0]["caption"], "The plan of the cell.")
        self.assertEqual(figs[0]["position"], "htbp")
        self.assertIsNone(figs[1]["position"])

    def test_unknown_extension_is_kept_as_unknown(self):
        figs = figure_tex.figures(r"\begin{figure}\includegraphics{a.xyz}\caption{X.}\label{fig:a-b-c}\end{figure}", self.base)
        self.assertEqual(self.kinds(figs[0]), ["unknown"])

    def test_every_listed_extension_has_its_kind(self):
        for ext, kind in [("eps", "eps"), ("gif", "gif"), ("bmp", "bmp"), ("tiff", "tiff"), ("tif", "tiff"),
                          ("webp", "webp"), ("jpeg", "jpg"), ("drawio", "drawio")]:
            tex = r"\begin{figure}\includegraphics{x.%s}\caption{X.}\end{figure}" % ext
            self.assertEqual(self.kinds(figure_tex.figures(tex, None)[0]), [kind], ext)

    def test_subfigures_give_several_sources(self):
        tex = (r"\begin{figure}\begin{subfigure}{.5\textwidth}\includegraphics{a.png}\caption{A.}\end{subfigure}"
               r"\begin{subfigure}{.5\textwidth}\begin{tikzpicture}\end{tikzpicture}\caption{B.}\end{subfigure}"
               r"\caption{Both.}\label{fig:two-sub-parts}\end{figure}")
        fig = figure_tex.figures(tex, None)[0]
        self.assertEqual(self.kinds(fig), ["png", "tikz"])
        self.assertEqual(fig["caption"], "Both.")
        self.assertEqual(fig["label"], "fig:two-sub-parts")

    def test_input_files_are_followed(self):
        fig = figure_tex.figures(r"\begin{figure}\input{fig.tikz}\caption{L.}\end{figure}", self.base)[0]
        src = fig["sources"][0]
        self.assertEqual(src["kind"], "tikz")
        self.assertIn("node {B}", src["path_or_code"])

    def test_input_outside_the_folder_is_not_followed(self):
        fig = figure_tex.figures(r"\begin{figure}\input{../../secret.tikz}\caption{L.}\end{figure}", self.base)[0]
        self.assertEqual(fig["sources"][0]["kind"], "unknown")

    def test_a_commented_figure_is_ignored(self):
        tex = "% \\begin{figure}\\includegraphics{a.png}\\caption{X.}\\end{figure}\n"
        self.assertEqual(figure_tex.figures(tex, None), [])

    def test_ref_autoref_cref_all_count(self):
        tex = r"A~\ref{fig:a-b-c}, \autoref{fig:a-b-c}, \cref{fig:a-b-c,fig:d-e-f} and \Cref{fig:d-e-f}."
        refs = figure_tex.references(tex)
        self.assertEqual(len(refs["fig:a-b-c"]), 3)
        self.assertEqual(len(refs["fig:d-e-f"]), 2)

    def test_a_reference_in_a_comment_does_not_count(self):
        self.assertEqual(figure_tex.references("% see \\ref{fig:a-b-c}\n"), {})

    def check(self, tex):
        records = figure_tex.text_checks(tex, self.criteria)
        return [r["criteria"] for r in records]

    def test_figure_cited_after_it_appears_fails(self):
        tex = (r"\begin{figure}\caption{X.}\label{fig:one-two-three}\end{figure}"
               r" Text with \ref{fig:one-two-three}.")
        self.assertEqual(self.check(tex)[0]["called_before_appearing"]["verdict"], "fail")

    def test_figure_cited_before_it_appears_passes(self):
        tex = (r"Text with \ref{fig:one-two-three}. \begin{figure}\caption{X.}\label{fig:one-two-three}\end{figure}")
        self.assertEqual(self.check(tex)[0]["called_before_appearing"]["verdict"], "pass")

    def test_figure_never_cited_fails_and_says_so(self):
        tex = r"\begin{figure}\caption{X.}\label{fig:one-two-three}\end{figure}"
        res = self.check(tex)[0]["called_before_appearing"]
        self.assertEqual(res["verdict"], "fail")
        self.assertIn("never", res["reason"])

    def test_figure_without_label_cannot_be_judged_for_citation(self):
        res = self.check(r"\begin{figure}\caption{X.}\end{figure}")[0]
        self.assertEqual(res["called_before_appearing"]["verdict"], "not_run")
        self.assertEqual(res["figure_label_form"]["verdict"], "fail")

    def test_label_not_three_words_fails(self):
        for label in ("fig:schema", "fig:two-words", "fig:four-words-in-all", "plan-of-cell", "fig:Upper-Case-Words"):
            tex = r"\begin{figure}\caption{X.}\label{%s}\end{figure}" % label
            self.assertEqual(self.check(tex)[0]["figure_label_form"]["verdict"], "fail", label)

    def test_label_with_three_words_passes(self):
        tex = r"\begin{figure}\caption{X.}\label{fig:plan-of-cell}\end{figure}"
        self.assertEqual(self.check(tex)[0]["figure_label_form"]["verdict"], "pass")

    def test_hardcoded_number_out_of_order_fails_and_automatic_numbering_is_not_applicable(self):
        tex = (r"\begin{figure}\caption{Figure 2: X.}\label{fig:aaa-bbb-ccc}\end{figure}"
               r"\begin{figure}\caption{Plain.}\label{fig:ddd-eee-fff}\end{figure}")
        recs = self.check(tex)
        self.assertEqual(recs[0]["numbered_in_sequence"]["verdict"], "fail")
        self.assertEqual(recs[1]["numbered_in_sequence"]["verdict"], "not_applicable")

    def test_hardcoded_number_in_order_passes(self):
        tex = r"\begin{figure}\caption{Figure 1: X.}\label{fig:aaa-bbb-ccc}\end{figure}"
        self.assertEqual(self.check(tex)[0]["numbered_in_sequence"]["verdict"], "pass")

    def test_a_criteria_document_without_the_ids_is_refused_naming_them(self):
        with self.assertRaises(figure_checks.CriteriaError) as ctx:
            figure_tex.text_checks(MIXED, {"criteria": []})
        self.assertIn("figure_label_form", str(ctx.exception))

    def test_document_without_figures_gives_nothing(self):
        self.assertEqual(figure_tex.figures("Just text.", self.base), [])
        self.assertEqual(figure_tex.text_checks("Just text.", self.criteria), [])


if __name__ == "__main__":
    unittest.main()
