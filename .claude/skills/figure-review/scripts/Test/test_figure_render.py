"""
Offline tests of figure_render.py: which figures a model can see as they are, how the others are turned
into a PNG or JPEG, and what is reported when a tool is missing. Every subprocess and every `which` is
patched, so no TeX or draw.io is needed; bitmaps and PDFs are built with PyMuPDF (fictitious data, R34).
"""
import contextlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz

import figure_checks
import figure_render

CRITERIA = Path(__file__).parent.parent.parent / "assets" / "figure_criteria.json"
SETTINGS = dict(timeout=5.0, max_long_edge=1568, dpi=72, photo_colors=10, jpeg_quality=80, drawio_scale=2)


def make_png(path: Path, width: int, height: int, colors: int = 1) -> Path:
    """Write a PNG of the given size holding about `colors` distinct colours."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(255)
    for i in range(colors - 1):
        pix.set_pixel(i % width, (i // width) % height, (i * 5 % 256, i * 11 % 256, i * 17 % 256))
    pix.save(str(path))
    return path


def make_bmp(path: Path, side: int = 8) -> Path:
    """Write a 24-bit BMP of side x side pixels, every pixel a different colour."""
    row = b"".join(bytes((x * 30 % 256, y * 30 % 256, (x + y) * 15 % 256)) for y in range(side) for x in range(side))
    rows = [row[i * side * 3:(i + 1) * side * 3] for i in range(side)][::-1]
    pad = (4 - (side * 3) % 4) % 4
    data = b"".join(r + b"\0" * pad for r in rows)
    header = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
    header += struct.pack("<IiiHHIIiiII", 40, side, side, 1, 24, 0, len(data), 2835, 2835, 0, 0)
    path.write_bytes(header + data)
    return path


def make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=100, height=60)
    page.draw_rect(fitz.Rect(10, 10, 90, 50), fill=(0, 0, 1))
    doc.save(str(path))
    doc.close()
    return path


class FakeLatex:
    """A `run` that behaves like pdflatex: reads the .tex, writes the PDF into -output-directory."""

    def __init__(self, fail_text=None):
        self.calls = []
        self.fail_text = fail_text

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.fail_text is not None:
            return subprocess.CompletedProcess(argv, 1, stdout=self.fail_text, stderr="")
        out_dir = Path(argv[argv.index("-output-directory") + 1])
        stem = Path(argv[-1]).stem
        make_pdf(out_dir / (stem + ".pdf"))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def which_all(name):
    return "/fake/" + name


def which_none(name):
    return None


class TestFigureRender(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, source, preamble=None, which=which_all, run=None, export=None, **settings):
        merged = dict(SETTINGS, **settings)
        return figure_render.render(source, self.out, preamble, which=which,
                                    run=run or mock.Mock(side_effect=AssertionError("no tool expected")),
                                    export=export, **merged)

    def test_png_and_jpg_are_native_and_not_rendered(self):
        self.assertTrue(figure_render.native("png"))
        self.assertTrue(figure_render.native("jpg"))
        for kind in ("svg", "pdf", "tikz", "drawio", "eps", "bmp", "gif", "tiff", "webp"):
            self.assertFalse(figure_render.native(kind), kind)
        src = make_png(self.dir / "a.png", 100, 50)
        res = self.render({"kind": "png", "path_or_code": str(src)})
        self.assertEqual(res["status"], "native")
        self.assertEqual(res["file"], str(src))
        self.assertIsNone(res["tool"])

    def test_a_large_native_png_is_downscaled_to_max_long_edge(self):
        src = make_png(self.dir / "big.png", 3000, 1000)
        res = self.render({"kind": "png", "path_or_code": str(src)})
        self.assertEqual(res["status"], "native")
        self.assertNotEqual(res["file"], str(src))
        self.assertTrue(Path(res["file"]).is_relative_to(self.out.resolve()))
        pix = fitz.Pixmap(res["file"])
        self.assertEqual(max(pix.width, pix.height), 1568)
        self.assertEqual(fitz.Pixmap(str(src)).width, 3000, "the source figure is never modified")

    def test_tikz_is_compiled_with_the_document_preamble(self):
        run = FakeLatex()
        code = r"\begin{tikzpicture}\node {\mymacro};\end{tikzpicture}"
        res = self.render({"kind": "tikz", "path_or_code": code, "name": "fig1"},
                          preamble=r"\newcommand{\mymacro}{M}", run=run, photo_colors=2000)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv[0], "/fake/pdflatex")
        self.assertIn("-interaction=nonstopmode", argv)
        self.assertIn("-halt-on-error", argv)
        self.assertEqual(kwargs["timeout"], SETTINGS["timeout"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(res["status"], "rendered")
        self.assertEqual(res["format"], "png")
        self.assertEqual(res["tool"], "pdflatex")
        self.assertTrue(Path(res["file"]).is_file())

    def test_the_standalone_text_holds_the_preamble_then_the_picture(self):
        text = figure_render.standalone_text(r"\begin{tikzpicture}\end{tikzpicture}", r"\newcommand{\mymacro}{M}")
        self.assertIn(r"\documentclass", text)
        self.assertIn("standalone", text)
        self.assertLess(text.index(r"\newcommand{\mymacro}"), text.index(r"\begin{document}"))
        self.assertLess(text.index(r"\begin{document}"), text.index(r"\begin{tikzpicture}"))
        self.assertIn("tikz", figure_render.standalone_text("X", None))

    def test_a_missing_macro_is_not_run_with_the_latex_message(self):
        run = FakeLatex(fail_text="! Undefined control sequence.\nl.7 \\mymacro\n")
        res = self.render({"kind": "tikz", "path_or_code": r"\begin{tikzpicture}\mymacro\end{tikzpicture}"}, run=run)
        self.assertEqual(res["status"], "not_run")
        self.assertIn("Undefined control sequence", res["reason"])
        self.assertIsNone(res["file"])

    def test_drawio_goes_through_fig_export(self):
        src = self.dir / "s.drawio"
        src.write_text("<mxfile><diagram/><diagram/><diagram/></mxfile>", encoding="utf-8")
        calls = []

        def export(source, out, scale, timeout):
            calls.append((source, out, scale, timeout))
            make_png(Path(out), 40, 30)
            return True

        res = self.render({"kind": "drawio", "path_or_code": str(src)}, export=export)
        self.assertEqual(calls[0][0], str(src))
        self.assertEqual(calls[0][2], SETTINGS["drawio_scale"])
        self.assertEqual(res["status"], "rendered")
        self.assertEqual(res["tool"], "draw.io")
        self.assertEqual(res["pages"], 3)
        self.assertIn("3", res["reason"])

    def test_drawio_missing_is_not_run_naming_it(self):
        src = self.dir / "s.drawio"
        src.write_text("<mxfile/>", encoding="utf-8")

        def export(*args, **kwargs):
            raise RuntimeError("draw.io CLI not found")

        res = self.render({"kind": "drawio", "path_or_code": str(src)}, export=export)
        self.assertEqual(res["status"], "not_run")
        self.assertEqual(res["tool"], "draw.io")

    def test_drawio_that_writes_nothing_is_not_run(self):
        src = self.dir / "s.drawio"
        src.write_text("<mxfile/>", encoding="utf-8")
        res = self.render({"kind": "drawio", "path_or_code": str(src)}, export=lambda *a, **k: False)
        self.assertEqual(res["status"], "not_run")

    def test_missing_tool_is_not_run_naming_it(self):
        res = self.render({"kind": "tikz", "path_or_code": "X"}, which=which_none)
        self.assertEqual((res["status"], res["tool"]), ("not_run", "pdflatex"))
        self.assertIn("pdflatex", res["reason"])
        eps = self.dir / "a.eps"
        eps.write_bytes(b"%!PS")
        res = self.render({"kind": "eps", "path_or_code": str(eps)}, which=which_none)
        self.assertEqual((res["status"], res["tool"]), ("not_run", "epstopdf"))

    def test_eps_goes_through_epstopdf_then_pymupdf(self):
        eps = self.dir / "a.eps"
        eps.write_bytes(b"%!PS")
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            out = [a for a in argv if a.startswith("--outfile=")][0].split("=", 1)[1]
            make_pdf(Path(out))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        res = self.render({"kind": "eps", "path_or_code": str(eps)}, run=run)
        self.assertEqual(calls[0][0], "/fake/epstopdf")
        self.assertEqual(res["status"], "rendered")
        self.assertEqual(res["tool"], "epstopdf")

    def test_timeout_is_not_run_with_reason(self):
        def run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        res = self.render({"kind": "tikz", "path_or_code": "X"}, run=run)
        self.assertEqual(res["status"], "not_run")
        self.assertIn("timeout", res["reason"].lower())

    def test_pdf_and_svg_are_rasterised_with_pymupdf(self):
        pdf = make_pdf(self.dir / "p.pdf")
        res = self.render({"kind": "pdf", "path_or_code": str(pdf)}, photo_colors=2000)
        self.assertEqual((res["status"], res["format"], res["tool"]), ("rendered", "png", "pymupdf"))
        svg = self.dir / "s.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40">'
                       '<rect width="60" height="40" fill="blue"/></svg>', encoding="utf-8")
        res = self.render({"kind": "svg", "path_or_code": str(svg)})
        self.assertEqual(res["status"], "rendered", res)

    def test_an_unreadable_file_is_not_run_with_the_reason(self):
        bad = self.dir / "bad.svg"
        bad.write_text("not an svg at all", encoding="utf-8")
        res = self.render({"kind": "svg", "path_or_code": str(bad)})
        self.assertEqual(res["status"], "not_run")
        self.assertTrue(res["reason"])

    def test_bmp_is_converted_to_png(self):
        bmp = make_bmp(self.dir / "a.bmp", side=2)
        res = self.render({"kind": "bmp", "path_or_code": str(bmp)})
        self.assertEqual(res["status"], "rendered", res)
        self.assertEqual(res["format"], "png")
        self.assertTrue(res["file"].endswith(".png"))
        self.assertEqual(fitz.Pixmap(res["file"]).width, 2)

    def test_a_photo_is_jpeg_and_line_art_is_png(self):
        photo = make_bmp(self.dir / "photo.bmp", side=8)
        res = self.render({"kind": "bmp", "path_or_code": str(photo)})
        self.assertEqual(res["format"], "jpeg")
        self.assertTrue(res["estimated_tokens"] > 0)
        line = make_pdf(self.dir / "line.pdf")
        self.assertEqual(self.render({"kind": "pdf", "path_or_code": str(line)}, photo_colors=2000)["format"], "png")

    def test_output_outside_out_dir_is_refused(self):
        bmp = make_bmp(self.dir / "a.bmp", side=2)
        with self.assertRaises(figure_render.RenderError):
            self.render({"kind": "bmp", "path_or_code": str(bmp), "name": "../escape"})
        self.assertFalse((self.dir / "escape.png").exists())

    def test_unknown_kind_and_missing_source_are_not_run(self):
        self.assertEqual(self.render({"kind": "unknown", "path_or_code": "x.xyz"})["status"], "not_run")
        self.assertEqual(self.render({"kind": "bmp", "path_or_code": str(self.dir / "gone.bmp")})["status"], "not_run")

    # --- command line ---

    def doc(self, body):
        tex = self.dir / "main.tex"
        tex.write_text("\\documentclass{article}\n\\usepackage{tikz}\n\\newcommand{\\mymacro}{M}\n"
                       "\\begin{document}\n" + body + "\n\\end{document}\n", encoding="utf-8")
        return tex

    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = figure_render.main(argv)
        return code, buf.getvalue()

    def test_without_render_flag_no_subprocess_is_called(self):
        make_png(self.dir / "a.png", 10, 10)
        tex = self.doc(r"\begin{figure}\includegraphics{a.png}\begin{tikzpicture}\end{tikzpicture}"
                       r"\caption{X.}\label{fig:aaa-bbb-ccc}\end{figure}")
        boom = mock.Mock(side_effect=AssertionError("no subprocess"))
        with mock.patch.object(figure_render.subprocess, "run", boom):
            code, text = self.run_main(["--tex", str(tex), "--out", str(self.out), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual([s["kind"] for s in data["figures"][0]["sources"]], ["png", "tikz"])
        self.assertNotIn("render", data["figures"][0]["sources"][0])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_render_on_a_bitmap_only_document_costs_no_tool_call(self):
        make_png(self.dir / "a.png", 10, 10)
        tex = self.doc(r"\begin{figure}\includegraphics{a.png}\caption{X.}\label{fig:aaa-bbb-ccc}\end{figure}")
        boom = mock.Mock(side_effect=AssertionError("no subprocess"))
        with mock.patch.object(figure_render.subprocess, "run", boom):
            code, text = self.run_main(["--tex", str(tex), "--out", str(self.out), "--render", "--json"])
        self.assertEqual(code, 0)
        render = json.loads(text)["figures"][0]["sources"][0]["render"]
        self.assertEqual(render["status"], "native")

    def test_render_uses_the_preamble_of_the_document(self):
        tex = self.doc(r"\begin{figure}\begin{tikzpicture}\node {\mymacro};\end{tikzpicture}"
                       r"\caption{X.}\label{fig:aaa-bbb-ccc}\end{figure}")
        run = FakeLatex()
        with mock.patch.object(figure_render.subprocess, "run", run), \
                mock.patch.object(figure_render.shutil, "which", which_all):
            code, text = self.run_main(["--tex", str(tex), "--out", str(self.out), "--render", "--json"])
        self.assertEqual(code, 0)
        written = [a for a in run.calls[0][0] if a.endswith(".tex")]
        self.assertTrue(written)
        self.assertEqual(json.loads(text)["figures"][0]["sources"][0]["render"]["status"], "rendered")

    def test_a_source_outside_the_document_folder_is_not_run(self):
        outside = make_png(self.dir.parent / "outside_figure.png", 10, 10)
        try:
            tex = self.doc(r"\begin{figure}\includegraphics{../outside_figure.png}\caption{X.}\end{figure}")
            code, text = self.run_main(["--tex", str(tex), "--out", str(self.out), "--render", "--json"])
            render = json.loads(text)["figures"][0]["sources"][0]["render"]
            self.assertEqual(render["status"], "not_run")
            self.assertIn("outside", render["reason"])
        finally:
            outside.unlink()

    def test_missing_tex_file_is_a_refusal(self):
        code, _ = self.run_main(["--tex", str(self.dir / "none.tex"), "--out", str(self.out)])
        self.assertEqual(code, 2)

    def test_criteria_file_has_research_entries_and_needs_key(self):
        doc = figure_checks.load_criteria(CRITERIA)
        crits = doc["criteria"]
        self.assertTrue(any(c["scope"] == "research" for c in crits))
        for c in crits:
            self.assertIn(c.get("needs"), ("source", "image", "either"), c["id"])
        ids = [c["id"] for c in crits]
        self.assertEqual(len(ids), len(set(ids)), "criterion ids are unique")
        for needed in ("figure_label_form", "tikz_anchored_positioning", "not_cited", "caption_multi_sentence"):
            self.assertIn(needed, ids)
        for key in ("render_dpi", "render_timeout_s", "drawio_scale"):
            self.assertIn("value", doc["extraction"][key])
            self.assertTrue(doc["extraction"][key]["provenance"])

    def test_every_auditor_figure_flag_is_a_criterion(self):
        doc = figure_checks.load_criteria(CRITERIA)
        flags = {c["flag"] for c in doc["criteria"] if c.get("flag")}
        for flag in ("[NOT CITED]", "[CITATION FAR]", "[INSUFFICIENT DESCRIPTION]", "[LOW RESOLUTION]",
                     "[IMAGE FILE MISSING]", "[CAPTION MULTI-SENTENCE]", "[CAPTION NOT A SENTENCE]",
                     "[CAPTION CARRIES EXPLANATION]"):
            self.assertIn(flag, flags)


if __name__ == "__main__":
    unittest.main()
