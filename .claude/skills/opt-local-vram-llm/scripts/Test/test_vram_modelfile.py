"""
Offline tests for vram_modelfile.py.

Each assertion below encodes a case measured on 2026-08-27 while tuning two models by hand.
Rendering is a pure function of a base configuration and a retained window, so no Ollama and
no GPU are involved.
"""

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import vram_modelfile as vm  # noqa: E402

_PROVENANCE = {
    "card": "NVIDIA RTX A1000 6GB Laptop GPU", "vram_mib": 6144,
    "kv_cache_type": "q8_0", "free_mib": 617, "decode_tps": 30.1, "date": "2026-08-27",
}
_RENDERER_BASE = {
    "template": "{{ .Prompt }}", "system": "You are an assistant.",
    "renderer": "somerenderer", "parser": "someparser", "stop": ["<|im_end|>"],
}
_TEMPLATE_BASE = {
    "template": "{{- if .Suffix }}<|fim_prefix|>{{ .Prompt }}{{- else }}<|im_start|>user\n"
                "{{ .Prompt }}<|im_end|>\n{{ end }}",
    "system": "You are a helpful assistant.",
    "renderer": None, "parser": None, "stop": [],
}


class TestAlwaysPresentParameters(unittest.TestCase):
    def test_num_gpu_and_num_ctx_are_always_emitted(self):
        # num_gpu 99 is not optional: an untuned base measured 79 percent GPU at 16384
        # despite its weights fitting the card, because what Ollama held back was layer
        # offload rather than KV cache.
        out = vm.render(base_tag="vendor:7b", from_reference="vendor:7b", from_is_blob=False,
                        num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                        provenance=_PROVENANCE)

        self.assertIn("PARAMETER num_gpu 99", out)
        self.assertIn("PARAMETER num_ctx 32768", out)


class TestNoRepetitionPenalty(unittest.TestCase):
    def test_no_forbidden_penalty_parameter_is_ever_emitted(self):
        # The bridge overrides temperature, top_p and top_k per request but NOT the
        # penalties, so a penalty left in a Modelfile does reach generation. One incumbent
        # tag carried presence_penalty 1.5, a repetition penalty applied to code.
        poisoned = dict(_TEMPLATE_BASE, presence_penalty="1.5", repeat_penalty="1.2")
        out = vm.render(base_tag="vendor:9b", from_reference="vendor:9b", from_is_blob=False,
                        num_ctx=16384, role="coder", base_config=poisoned,
                        provenance=_PROVENANCE)

        for forbidden in vm.FORBIDDEN_PARAMETERS:
            self.assertNotIn(f"PARAMETER {forbidden}", out)


class TestTemplateHandling(unittest.TestCase):
    def test_a_tag_from_reference_does_not_restate_the_inherited_template(self):
        # FROM a tag inherits TEMPLATE/SYSTEM/RENDERER/PARSER. Restating a passthrough
        # template over a model that formats solely through its own TEMPLATE would feed it
        # an unframed prompt and discard the fill-in-the-middle branch.
        out = vm.render(base_tag="vendor:7b", from_reference="vendor:7b", from_is_blob=False,
                        num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                        provenance=_PROVENANCE)

        self.assertNotIn("TEMPLATE", out)
        self.assertNotIn("<|fim_prefix|>", out)

    def test_a_blob_from_reference_restates_every_inherited_directive(self):
        # A blob carries no TEMPLATE, SYSTEM, RENDERER, PARSER or stop token, so dropping a
        # projector means restating all of them explicitly.
        out = vm.render(base_tag="vendor:9b", from_reference="sha256-abc", from_is_blob=True,
                        num_ctx=16384, role="writer", base_config=_RENDERER_BASE,
                        provenance=_PROVENANCE)

        self.assertIn("TEMPLATE {{ .Prompt }}", out)
        self.assertIn("RENDERER somerenderer", out)
        self.assertIn("PARSER someparser", out)
        self.assertIn("PARAMETER stop <|im_end|>", out)

    def test_a_multi_line_template_is_triple_quoted_not_flattened(self):
        # A real chat template spans lines. Emitting it bare would end the directive at the
        # first newline and leave the rest as garbage directives.
        base = dict(_RENDERER_BASE, template="line one\nline two\nline three")
        out = vm.render(base_tag="vendor:9b", from_reference="sha256-abc", from_is_blob=True,
                        num_ctx=16384, role="writer", base_config=base,
                        provenance=_PROVENANCE)

        self.assertIn('TEMPLATE """line one\nline two\nline three"""', out)


class TestParseModelfile(unittest.TestCase):
    def test_a_triple_quoted_template_is_captured_whole(self):
        # The parser's reason for existing: `ollama show --modelfile` wraps a real template
        # in triple quotes across many lines, and a single-line parser truncates it.
        text = (
            'FROM somewhere\n'
            'TEMPLATE """{{- if .Messages }}\n<|im_start|>user\n{{ .Prompt }}\n{{ end }}"""\n'
            'SYSTEM You are Qwen.\n'
            'PARAMETER stop <|im_end|>\n'
            'PARAMETER temperature 1\n'
        )
        config = vm.parse_modelfile(text)

        self.assertIn("<|im_start|>user", config["template"])
        self.assertIn("{{ end }}", config["template"])
        self.assertEqual(config["system"], "You are Qwen.")
        self.assertEqual(config["stop"], ["<|im_end|>"])

    def test_renderer_and_parser_are_captured_and_absent_ones_are_none(self):
        config = vm.parse_modelfile("FROM x\nRENDERER r1\nPARSER p1\n")

        self.assertEqual(config["renderer"], "r1")
        self.assertEqual(config["parser"], "p1")
        self.assertIsNone(config["template"])
        self.assertEqual(config["stop"], [])


class TestPreviewDoesNotClaimAMeasurement(unittest.TestCase):
    def test_an_unmeasured_render_says_so_instead_of_printing_zeros(self):
        # Caught by a smoke test on 2026-08-27: --dry-run emitted "0 MiB free, 0.0 tok/s
        # decode, 100 percent GPU residency", asserting full residency before a single rung
        # had been measured. A preview must never wear a measurement's provenance.
        preview = dict(_PROVENANCE, free_mib=0, decode_tps=0.0, measured=False)
        out = vm.render(base_tag="v:7b", from_reference="v:7b", from_is_blob=False,
                        num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                        provenance=preview)

        self.assertIn("PREVIEW ONLY, NOTHING MEASURED YET", out)
        self.assertNotIn("100 percent GPU residency", out)
        self.assertNotIn("0.0 tok/s", out)

    def test_a_measured_render_keeps_the_retained_line(self):
        out = vm.render(base_tag="v:7b", from_reference="v:7b", from_is_blob=False,
                        num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                        provenance=dict(_PROVENANCE, measured=True))

        self.assertIn("100 percent GPU residency", out)
        self.assertNotIn("PREVIEW ONLY", out)


class TestRoleSystemPrompt(unittest.TestCase):
    def test_each_role_gets_its_own_system_line(self):
        coder = vm.render(base_tag="v:7b", from_reference="v:7b", from_is_blob=False,
                          num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                          provenance=_PROVENANCE)
        writer = vm.render(base_tag="v:9b", from_reference="v:9b", from_is_blob=False,
                           num_ctx=16384, role="writer", base_config=_TEMPLATE_BASE,
                           provenance=_PROVENANCE)

        self.assertIn(vm.ROLE_SYSTEM["coder"], coder)
        self.assertIn(vm.ROLE_SYSTEM["writer"], writer)
        self.assertNotEqual(vm.ROLE_SYSTEM["coder"], vm.ROLE_SYSTEM["writer"])


class TestProvenanceIsRecorded(unittest.TestCase):
    def test_the_measurement_that_justifies_the_window_is_in_the_comments(self):
        # A Modelfile whose num_ctx carries no provenance is indistinguishable from a
        # guessed one six months later.
        out = vm.render(base_tag="v:7b", from_reference="v:7b", from_is_blob=False,
                        num_ctx=32768, role="coder", base_config=_TEMPLATE_BASE,
                        provenance=_PROVENANCE)

        self.assertIn("NVIDIA RTX A1000 6GB Laptop GPU", out)
        self.assertIn("q8_0", out)
        self.assertIn("617", out)
        self.assertIn("2026-08-27", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
