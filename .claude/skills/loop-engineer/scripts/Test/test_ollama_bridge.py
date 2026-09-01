"""
test_ollama_bridge.py - offline unit tests for the deterministic Ollama HTTP bridge.

Every test patches ollama_bridge._post_generate (the sole network boundary) and, where a
model tag is needed, ollama_bridge.resolve_model (D7's own test deliberately does NOT patch
resolve_model - see its docstring). No test calls urllib.request.urlopen and no test opens
a socket: the patched callables are plain Python functions substituted in place of the
module's own names via unittest.mock.patch.object / unittest.mock.patch.dict, so
pytest/unittest never constructs a real urllib.request.Request or reaches 127.0.0.1. That
substitution is the mechanism that guarantees these tests are offline.

Since fix round 1 (I1), check_budget's exact gate is a token PROBE - a call to
_post_generate - that happens once per run_bridge invocation, before the real generation
attempts. Since fix round 2 (R57), the probe ALWAYS sends options.num_predict = 1 (never 0 -
measured to pay for a full generation for no benefit). Every fake transport below must
therefore distinguish a probe call (num_predict == 1: must return a dict with an int
"prompt_eval_count") from a real generation call (num_predict == RESPONSE_RESERVE_TOKENS:
must return a dict with a "response" string). _is_probe() is the shared discriminator.

Since fix round 2 (R56), a probe count that matches Ollama's measured truncation signature
(num_ctx // 2 + 2, within TRUNCATION_SIGNATURE_SLACK) is refused outright, replacing fix
round 1's 3.0 plausibility margin against the character pre-filter. _plausible_probe_count()
picks a count derived from the prompt's own length, which stays far from that signature for
every prompt used in this file.

Twelve cases:

  1. test_full_prompt_reaches_transport_unmodified              -> D1
  2. test_over_budget_prompt_refused_without_partial_answer     -> D2 (fix round 1: C2)
  3. test_reasoning_block_stripped_over_twenty_responses        -> D3 (fix round 1: I3)
  4. test_failed_verify_restores_previous_target_content        -> D4
  5. test_dirty_response_triggers_finite_retry_budget           -> D5
  6. test_same_seed_produces_identical_recorded_request         -> D6
  7. test_unavailable_model_refuses_without_fallback_tag        -> D7 (fix round 1: C3)
  8. test_log_file_has_one_json_line_per_attempt_with_hashes_seed_durations
  9. test_empty_body_never_overwrites_target_and_retries        -> fix round 1: C1
  10. test_default_log_path_is_outside_repository               -> fix round 1: I4
  11. test_truncation_signature_refuses_exact_match              -> fix round 2: R56
  12. test_near_signature_count_is_accepted_not_a_false_positive -> fix round 2: R56

Run:
    python .claude/skills/loop-engineer/scripts/Test/test_ollama_bridge.py
"""

import io
import logging
import json
import sys
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
sys.path.insert(0, str(_SCRIPTS))

import ollama_bridge as ob  # noqa: E402


# The context window is a property of the MODEL, so run_bridge reads it for whichever tag
# resolve_model returns (ollama_bridge._resolve_num_ctx). Every test below patches
# resolve_model to a fixed tag, which is deliberately NOT one this machine has necessarily
# swept, so the lookup is patched here once for the whole module rather than in each test.
# This also removes a latent machine dependency: before 2026-08-27 the window came from a
# module-level constant that read this machine's own local-model-config.json at import
# time, so the suite quietly passed or failed according to what happened to be measured
# locally. Tests that care about a specific window still pass num_ctx explicitly, and that
# explicit value always wins over this patch.
_TEST_NUM_CTX = 16384


def setUpModule():
    patcher = mock.patch.object(ob, "_resolve_num_ctx", return_value=_TEST_NUM_CTX)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def _is_probe(payload):
    """True when payload is a token-probe request (options.num_predict == 1, R57 - the
    probe never sends 0)."""
    return payload.get("options", {}).get("num_predict") == 1


def _plausible_probe_count(prompt_text):
    """
    A fake probe response's prompt_eval_count must NOT match Ollama's measured
    truncation signature (num_ctx // 2 + 2, within ollama_bridge.
    TRUNCATION_SIGNATURE_SLACK - fix round 2, R56), or probe_prompt_tokens
    legitimately refuses it as truncated. Using the prompt's own length keeps
    every fake transport's count far from that signature for every num_ctx used
    in this file (default 8192 -> signature 4098; none of this file's prompts
    are anywhere near that many characters long except the D1 test, which
    overrides num_ctx to 300000, moving the signature to 150002).
    """
    return max(1, len(prompt_text))


class TestFullPromptReachesTransport(unittest.TestCase):
    def test_full_prompt_reaches_transport_unmodified(self):
        # D1: the prompt travels only inside the JSON body sent to _post_generate;
        # there is no argv and no shell on this path, so there is no ~32000-character
        # Git Bash ceiling and no accent/quote/backtick corruption to worry about.
        # num_ctx is generously overridden here ONLY to keep the budget gate (D2,
        # tested on its own below with the real 8192 default) out of this case. Every
        # call (the probe AND the real generation) must carry the identical prompt.
        unit = (
            "Contexte francais avec accents : éàçîôùïüñ, "
"guillemets droits \" et ' , un backtick ` et un bloc ```python\nprint('bonjour')\n``` "
        )
        big_prompt = (unit * (100000 // len(unit) + 1))[:100000]
        self.assertEqual(len(big_prompt), 100000)

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text(big_prompt, encoding="utf-8")

            captured = []

            def capture_transport(payload, timeout):
                captured.append(payload)
                if _is_probe(payload):
                    return {"prompt_eval_count": _plausible_probe_count(big_prompt)}
                return {"response": "Reponse breve et propre."}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=capture_transport):
                rc = ob.run_bridge(
                    prompt_path=prompt_path,
                    verify_command=None,
                    target_path=None,
                    seed=ob.DEFAULT_SEED,
                    log_path=d / "log.jsonl",
                    num_ctx=300000,  # generous override so the pre-filter itself does not refuse
                )

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 2)  # 1 probe + 1 generation
        for payload in captured:
            self.assertEqual(payload["prompt"], big_prompt)


class TestOverBudgetPromptRefused(unittest.TestCase):
    def test_over_budget_prompt_refused_without_partial_answer(self):
        # D2, fixed for fix round 1's C2: the original version of this test did not
        # patch resolve_model, so its asserted BridgeError came from the ABSENT
        # resolver, not from the budget guard - removing the guard entirely still
        # passed. resolve_model is now patched to SUCCEED, so the only way run_bridge
        # can still return 1 is the budget guard itself.
        #
        # The prompt is short enough to pass the pessimistic character pre-filter (so
        # it actually reaches the probe), and the probe reports an over-budget
        # prompt_eval_count on its ONE call. A correctly-guarded bridge must stop
        # there and never call the transport again. If the guard is removed (verified
        # by mutation in a scratch copy - see the report), execution falls through to
        # a real generation attempt; the second call below deliberately returns a
        # clean, acceptable response so that mutation is unmistakable (rc flips to 0).
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("mot " * 500, encoding="utf-8")  # 2000 chars

            call_count = {"n": 0}

            def transport(payload, timeout):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    self.assertTrue(_is_probe(payload))
                    return {"prompt_eval_count": 999999}  # far over budget
                # Only reached if the budget guard was removed/broken.
                return {"response": "Ne devrait jamais etre accepte."}

            buf = io.StringIO()
            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport), \
                 redirect_stdout(buf):
                rc = ob.run_bridge(
                    prompt_path=prompt_path,
                    verify_command=None,
                    target_path=None,
                    seed=ob.DEFAULT_SEED,
                    log_path=d / "log.jsonl",
                )  # default num_ctx=8192

        self.assertEqual(rc, 1)
        self.assertEqual(call_count["n"], 1)  # only the probe; the guard stopped it there
        self.assertEqual(buf.getvalue(), "")  # no partial answer printed
        self.assertFalse((d / "log.jsonl").exists())  # never attempted, nothing to log


class TestReasoningStripped(unittest.TestCase):
    def test_reasoning_block_stripped_over_twenty_responses(self):
        # D3, rewritten for fix round 1's I3. Two groups:
        #   - well-formed shapes: strip_reasoning must return cleanly (no raise), with
        #     every "keep" fragment present and every "drop" fragment absent.
        #   - anomalous shapes: strip_reasoning must raise ReasoningAnomalyError,
        #     never guess how much to drop or keep.
        well_formed = [
            ("<think>raisonnement un</think>Reponse un.",
             ["Reponse un."], ["raisonnement un"]),
            ("Reponse deux.<think>raisonnement deux</think>",
             ["Reponse deux."], ["raisonnement deux"]),
            ("Debut trois.<think>raisonnement trois</think>Fin trois.",
             ["Debut trois.", "Fin trois."], ["raisonnement trois"]),
            ("<THINK>raisonnement quatre majuscule</THINK>Reponse quatre.",
             ["Reponse quatre."], ["raisonnement quatre majuscule"]),
            ("<Think>raisonnement cinq mixte</Think>Reponse cinq.",
             ["Reponse cinq."], ["raisonnement cinq mixte"]),
            ("<think>ligne un\nligne deux\nligne trois</think>Reponse six.",
             ["Reponse six."], ["ligne un", "ligne deux", "ligne trois"]),
            ("<think>premier bloc</think>Milieu sept.<think>second bloc</think>Fin sept.",
             ["Milieu sept.", "Fin sept."], ["premier bloc", "second bloc"]),
            ("<think>raisonnement dix avec accents éàçîôù</think>"
"Reponse dix accents éàçîôù.",
             ["Reponse dix accents éàçîôù."],
             ["raisonnement dix avec accents"]),
            ("Thinking...\nreflexion onze etape un\nreflexion onze etape deux\n"
"...done thinking.\nReponse onze.",
             ["Reponse onze."], ["reflexion onze etape un", "reflexion onze etape deux"]),
            ("Reponse douze avant.\nThinking...\nreflexion douze\n...done thinking.",
             ["Reponse douze avant."], ["reflexion douze"]),
            ("THINKING...\nreflexion treize majuscule\n...DONE THINKING.\nReponse treize.",
             ["Reponse treize."], ["reflexion treize majuscule"]),
            ("Thinking...\nreflexion quatorze\n...done thinking.Reponse quatorze colle.",
             ["Reponse quatorze colle."], ["reflexion quatorze"]),
            ("Debut quinze.\nThinking...\nreflexion quinze\n...done thinking.\nFin quinze.",
             ["Debut quinze.", "Fin quinze."], ["reflexion quinze"]),
            ("<think>bloc seize</think>Thinking...\nreflexion seize deux\n...done thinking.\n"
"Reponse seize finale.",
             ["Reponse seize finale."], ["bloc seize", "reflexion seize deux"]),
            ("Reponse dix-sept sans aucun raisonnement.",
             ["Reponse dix-sept sans aucun raisonnement."], []),
            ("<think>   \n  \n</think>Reponse dix-huit.",
             ["Reponse dix-huit."], []),
            # A fence used AS FORMATTING INSIDE an active think span: the whole span,
            # fence included, is dropped as one unit (I3 - fence markers seen while
            # think_depth > 0 are just more dropped text).
            ("<think>raisonnement dix-neuf avec ```code``` et backticks</think>"
"Reponse dix-neuf avec du texte normal.",
             ["Reponse dix-neuf avec du texte normal."], ["raisonnement dix-neuf avec"]),
            ("Thinking...\n...done thinking.\nReponse vingt.",
             ["Reponse vingt."], []),
            # Nested <think> tags (I3, was the "leak" defect): the outer close must be
            # the one that ends the drop, not the first (inner) closing tag found.
            ("<think>outer <think>inner</think> still reasoning</think>Reponse vingt-un.",
             ["Reponse vingt-un."], ["outer", "inner", "still reasoning"]),
            # An unclosed <think> used as a LITERAL example INSIDE a real fence: the
            # fence protects it completely, so the ENTIRE text survives unchanged
            # (I3 - this is the "deletes the rest of the note" defect).
            ("Avant.\n```html\n<think>exemple non ferme dans le HTML\n```\nApres vingt-deux.",
             ["Avant.", "```html", "<think>exemple non ferme dans le HTML", "```",
"Apres vingt-deux."], []),
        ]
        self.assertEqual(len(well_formed), 20)

        for i, (raw, keep, drop) in enumerate(well_formed, start=1):
            with self.subTest(well_formed=i):
                cleaned = ob.strip_reasoning(raw)
                low = cleaned.lower()
                if "```" not in raw:  # the fence-protection case legitimately keeps <think
                    self.assertNotIn("<think", low)
                    self.assertNotIn("</think>", low)
                self.assertNotIn("thinking...", low.replace("```html", ""))
                self.assertNotIn("done thinking", low)
                for frag in keep:
                    self.assertIn(frag, cleaned)
                for frag in drop:
                    self.assertNotIn(frag, cleaned)

        anomalous = [
            "<think>raisonnement non ferme jusqu'a la fin sans balise fermante",
"Avant vingt-trois conserve.<think>raisonnement non ferme apres",
"Corps avant.</think>Corps apres orphelin.",
"Corps.\nThinking...\nreflexion qui ne se termine jamais",
"Corps avant.\n...done thinking.\nOrphelin de fermeture.",
        ]
        for i, raw in enumerate(anomalous, start=1):
            with self.subTest(anomalous=i):
                with self.assertRaises(ob.ReasoningAnomalyError):
                    ob.strip_reasoning(raw)


class TestVerifyRestoresTarget(unittest.TestCase):
    def test_failed_verify_restores_previous_target_content(self):
        # D4: run an executable oracle; on failure, restore the target to exactly
        # what it held before this attempt rather than leaving a rejected candidate.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            target = d / "note.md"
            target.write_text("CONTENU ORIGINAL", encoding="utf-8")
            prompt_path = d / "prompt.txt"
            prompt_text = "Ecris une note courte."
            prompt_path.write_text(prompt_text, encoding="utf-8")

            def transport(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": _plausible_probe_count(prompt_text)}
                return {"response": "Note propre generee."}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                rc = ob.run_bridge(
                    prompt_path=prompt_path,
                    verify_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
                    target_path=target,
                    seed=ob.DEFAULT_SEED,
                    log_path=d / "log.jsonl",
                    max_retries=1,
                )

            self.assertEqual(rc, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "CONTENU ORIGINAL")


class TestDirtyResponseRetriesFinitely(unittest.TestCase):
    def test_dirty_response_triggers_finite_retry_budget(self):
        # D5: the hygiene check runs in code (never as a paragraph asked of the
        # model) and a violation triggers a retry, but the retry budget is finite.
        # Includes the three characters added in fix round 1 (minor): non-breaking
        # space, non-breaking hyphen, minus sign.
        banned_samples = {
            "curly quote": "Texte avec une citation \u2019bizarre\u2019 ici.",
"em dash": "Texte avec un tiret \u2014 long ici.",
"en dash": "Texte avec un tiret \u2013 moyen ici.",
"word joiner": "Texte avec un\u2060espace cache ici.",
"ellipsis": "Texte qui continue\u2026 sans fin.",
"non-breaking space": "Texte avec un\u00a0espace insecable ici.",
"non-breaking hyphen": "Texte avec un tiret\u2011insecable ici.",
"minus sign": "Texte avec un signe \u2212 moins ici.",
        }
        for label, text in banned_samples.items():
            with self.subTest(label=label):
                self.assertTrue(ob.scan_hygiene(text), f"{label} should be flagged")

        call_count = {"n": 0}
        dirty_prompt_text = "Ecris une note."

        def always_dirty(payload, timeout):
            if _is_probe(payload):
                return {"prompt_eval_count": _plausible_probe_count(dirty_prompt_text)}
            call_count["n"] += 1
            return {"response": "Toujours sale \u2014 jamais propre."}

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text(dirty_prompt_text, encoding="utf-8")

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=always_dirty):
                rc = ob.run_bridge(
                    prompt_path=prompt_path,
                    verify_command=None,
                    target_path=None,
                    seed=ob.DEFAULT_SEED,
                    log_path=d / "log.jsonl",
                    max_retries=3,
                )

        self.assertEqual(rc, 1)
        self.assertEqual(call_count["n"], 3)  # finite budget, not an infinite loop


class TestSeedDeterminesRequest(unittest.TestCase):
    def test_same_seed_produces_identical_recorded_request(self):
        # D6: fix sampling and seed so two runs are comparable and a regression is
        # attributable. Two full bridge invocations with the same seed must send
        # the same attempt-1 GENERATION request (the probe carries no seed at all,
        # so only the generation payloads are compared here).
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_text = "Note deterministe."
            prompt_path.write_text(prompt_text, encoding="utf-8")

            generation_payloads = []

            def capture(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": _plausible_probe_count(prompt_text)}
                generation_payloads.append(payload)
                return {"response": "Reponse propre."}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=capture):
                rc1 = ob.run_bridge(prompt_path, None, None, seed=7, log_path=d / "log1.jsonl")
                rc2 = ob.run_bridge(prompt_path, None, None, seed=7, log_path=d / "log2.jsonl")

        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(len(generation_payloads), 2)
        self.assertEqual(generation_payloads[0], generation_payloads[1])
        self.assertEqual(generation_payloads[0]["options"]["seed"], 7)


class TestUnavailableModelRefuses(unittest.TestCase):
    def test_unavailable_model_refuses_without_fallback_tag(self):
        # D7, fixed for fix round 1's C3: the original version of this test patched
        # resolve_model itself, which bypassed the very function that holds the
        # anti-fallback logic - removing that logic entirely still passed. This
        # version exercises the REAL resolve_model(): sys.modules["model_resolver"]
        # is set to None, which is the standard way to force "import model_resolver"
        # to raise ImportError regardless of whether such a module exists anywhere
        # else on sys.path (robust even after Task 3 eventually ships it for real).
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Note.", encoding="utf-8")

            transport_calls = []

            def transport(payload, timeout):
                transport_calls.append(payload)
                return {"response": "ne doit jamais etre appele"}

            with mock.patch.dict(sys.modules, {"model_resolver": None}), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                # --no-vault-context is REQUIRED since the mandatory-consultation guard landed: this
                # case exercises the log path, not the vault, so it says so out loud.
                rc = ob.main(["--prompt-file", str(prompt_path), "--no-vault-context"])

        self.assertEqual(rc, 1)
        self.assertEqual(transport_calls, [])  # never substituted a tag and called the API


class TestLogFileFormat(unittest.TestCase):
    def test_log_file_has_one_json_line_per_attempt_with_hashes_seed_durations(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_text = "Contenu de la note a journaliser."
            prompt_path.write_text(prompt_text, encoding="utf-8")
            log_path = d / "loop-bridge-log.jsonl"

            attempts = {"n": 0}

            def flaky(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": _plausible_probe_count(prompt_text)}
                attempts["n"] += 1
                if attempts["n"] == 1:
                    return {"response": "Sale \u2014 ici."}
                return {"response": "Propre maintenant."}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=flaky):
                rc = ob.run_bridge(prompt_path, None, None, seed=11, log_path=log_path, max_retries=3)

            self.assertEqual(rc, 0)
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)  # one line per GENERATION attempt (probe not logged)
            for i, line in enumerate(lines, start=1):
                record = json.loads(line)
                for key in ("attempt", "seed", "prompt_hash", "response_hash", "generation_s"):
                    self.assertIn(key, record)
                self.assertEqual(record["attempt"], i)
                self.assertEqual(record["prompt_hash"], ob.sha256_hex(prompt_text))
            self.assertEqual(json.loads(lines[0])["seed"], 11)
            self.assertEqual(json.loads(lines[1])["seed"], 12)  # attempt offset (D6 retry policy)


class TestEmptyBodyNeverOverwritesTarget(unittest.TestCase):
    def test_empty_body_never_overwrites_target_and_retries(self):
        # Fix round 1, C1 (CRITICAL, data loss): a response with no "response" key,
        # an empty "response" string, and a reasoning-only reply that strips to
        # nothing must ALL be treated as a failed attempt - never written to
        # --target, never accepted. The interface contract is "exit 0 only when a
        # generation was produced AND passed every gate"; an empty string is not a
        # generation.
        precious = "CONTENU PRECIEUX EXISTANT"
        shapes = {
            "missing response key": lambda: {},
"empty response string": lambda: {"response": ""},
"whitespace-only response": lambda: {"response": "   \n  "},
"reasoning-only response strips to empty": lambda: {"response": "<think>rien que du raisonnement</think>"},
        }
        for label, make_response in shapes.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as d:
                    d = Path(d)
                    target = d / "note.md"
                    target.write_text(precious, encoding="utf-8")
                    prompt_path = d / "prompt.txt"
                    empty_case_prompt_text = "Ecris une note."
                    prompt_path.write_text(empty_case_prompt_text, encoding="utf-8")

                    call_count = {"n": 0}

                    def transport(payload, timeout, _mk=make_response):
                        if _is_probe(payload):
                            return {"prompt_eval_count": _plausible_probe_count(empty_case_prompt_text)}
                        call_count["n"] += 1
                        return _mk()

                    with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                         mock.patch.object(ob, "_post_generate", side_effect=transport):
                        rc = ob.run_bridge(
                            prompt_path=prompt_path,
                            verify_command=None,
                            target_path=target,
                            seed=ob.DEFAULT_SEED,
                            log_path=d / "log.jsonl",
                            max_retries=2,
                        )

                    self.assertEqual(rc, 1)
                    self.assertEqual(call_count["n"], 2)  # retried within budget, then gave up
                    self.assertEqual(target.read_bytes(), precious.encode("utf-8"))


class TestDefaultLogPathOutsideRepository(unittest.TestCase):
    def test_default_log_path_is_outside_repository(self):
        # Fix round 1, I4: the log defaulted INSIDE the repository tree with no
        # override flag. DEFAULT_LOG_PATH must now live under the user's home
        # (~/.claude/loop-bridge-log.jsonl, the same home the outbox already uses),
        # never under this script's own directory, and --log must be able to
        # override it.
        scripts_dir = Path(__file__).resolve().parent.parent
        self.assertEqual(ob.DEFAULT_LOG_PATH, Path.home() / ".claude" / "loop-bridge-log.jsonl")
        self.assertNotIn(scripts_dir, ob.DEFAULT_LOG_PATH.parents)

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_text = "Note."
            prompt_path.write_text(prompt_text, encoding="utf-8")
            override_log = d / "custom-log.jsonl"

            def transport(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": _plausible_probe_count(prompt_text)}
                return {"response": "Reponse propre."}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                rc = ob.main([
                    "--prompt-file", str(prompt_path), "--no-vault-context",
"--log", str(override_log),
                ])

            self.assertEqual(rc, 0)
            self.assertTrue(override_log.exists())


class TestTruncationSignatureRefusesExactMatch(unittest.TestCase):
    def test_truncation_signature_refuses_exact_match(self):
        # Fix round 2, R56: Ollama 0.32.9 truncates a prompt that exceeds num_ctx to
        # exactly num_ctx // 2 + 2 tokens and reports success, with no error. Measured
        # independently across three windows with the same ~16351-token prompt:
        #   num_ctx  2048 -> prompt_eval_count  1026 (signature 2048 // 2 + 2 = 1026, ratio 0.501)
        #   num_ctx  4096 -> prompt_eval_count  2050 (signature 4096 // 2 + 2 = 2050, ratio 0.500)
        #   num_ctx  8192 -> prompt_eval_count  4098 (signature 8192 // 2 + 2 = 4098, ratio 0.500)
        # (num_ctx 16384 was the control where the prompt fit and the true count, 16351,
        # came back - ratio 0.998 - proving the signature only appears under truncation.)
        # For every window: a probe reporting exactly the signature is refused; a probe
        # reporting any other value is accepted normally.
        windows = [
            (2048, 1026),
            (4096, 2050),
            (8192, 4098),
        ]
        for num_ctx, signature in windows:
            with self.subTest(num_ctx=num_ctx, expect="refused_exact_signature"):
                self.assertEqual(ob._truncation_signature(num_ctx), signature)
                with mock.patch.object(
                        ob, "_post_generate",
                        return_value={"prompt_eval_count": signature}):
                    with self.assertRaises(ob.BridgeError) as ctx:
                        ob.probe_prompt_tokens(
                            "un prompt hex-dense quelconque", "vendor-a:9b", num_ctx,
                        )
                self.assertIn("truncation signature", str(ctx.exception))

        for num_ctx, signature in windows:
            with self.subTest(num_ctx=num_ctx, expect="accepted_other_value"):
                legitimate_count = 50  # far from every signature measured above
                with mock.patch.object(
                        ob, "_post_generate",
                        return_value={"prompt_eval_count": legitimate_count}):
                    result = ob.probe_prompt_tokens(
                        "un prompt legitime et court", "vendor-a:9b", num_ctx,
                    )
                self.assertEqual(result, legitimate_count)


class TestProbeSendsNumPredictOne(unittest.TestCase):
    def test_probe_sends_num_predict_one_on_the_wire(self):
        # Fix round 2, R57: measured directly that num_predict=0 made the daemon
        # generate a FULL response (eval_count 195, done_reason "stop") while
        # num_predict=1 stopped after one token (eval_count 1, done_reason "length"),
        # with an IDENTICAL prompt_eval_count either way - so the probe must always
        # send 1, never 0. Inspects the actual recorded request, not a proxy.
        captured = []

        def transport(payload, timeout):
            captured.append(payload)
            return {"prompt_eval_count": 50}

        with mock.patch.object(ob, "_post_generate", side_effect=transport):
            count = ob.probe_prompt_tokens(
                "Un prompt de test pour verifier num_predict.",
                # A literal, not the former module constant ob.DEFAULT_NUM_CTX: that
                # constant was an eager import-time read of local-model-config.json and
                # was removed on 2026-08-27, when a second measured model made it raise.
                # This test only needs SOME window; 16384 is the writer tag's measured one.
                "vendor-a:9b", 16384,
            )

        self.assertEqual(count, 50)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["options"]["num_predict"], 1)


class TestNearSignatureCountIsAcceptedNotAFalsePositive(unittest.TestCase):
    def test_near_signature_count_is_accepted_not_a_false_positive(self):
        # Fix round 3: verify that the tightened TRUNCATION_SIGNATURE_SLACK=1 boundary
        # is correctly implemented. For num_ctx 8192, the signature is 4098. With slack=1:
        # - 4098 (exact signature) must be REFUSED
        # - 4097, 4099 (within slack of 1) must be REFUSED
        # - 4096, 4100 (outside slack of 1) must be ACCEPTED
        # - far values like 500 must be ACCEPTED
        #
        # This test validates the boundary behavior after tightening the slack from 2 to 1.
        num_ctx = 8192
        signature = ob._truncation_signature(num_ctx)
        self.assertEqual(signature, 4098)

        test_cases = {
            "exact_signature_refused": (4098, False),
"within_slack_low_refused": (4097, False),
"within_slack_high_refused": (4099, False),
"outside_slack_low_accepted": (4096, True),
"outside_slack_high_accepted": (4100, True),
"far_from_signature_accepted": (500, True),
        }

        for label, (count, should_accept) in test_cases.items():
            with self.subTest(count=count, label=label):
                with mock.patch.object(
                        ob, "_post_generate",
                        return_value={"prompt_eval_count": count}):
                    if should_accept:
                        result = ob.probe_prompt_tokens(
                            "un prompt legitime de test", "vendor-a:9b", num_ctx,
                        )
                        self.assertEqual(result, count)
                    else:
                        with self.assertRaises(ob.BridgeError) as ctx:
                            ob.probe_prompt_tokens(
                                "un prompt legitime de test", "vendor-a:9b", num_ctx,
                            )
                        self.assertIn("truncation signature", str(ctx.exception))


class TestVaultConsultationIsMandatory(unittest.TestCase):
    """
    The vault lookup lives in the bridge, not in a procedure, because a procedure written in
    an agent definition was skipped by the first caller in a hurry. Measured 2026-08-14: with
    no context injected the local model answered a documented LaTeX question with the
    non-existent command \\endminitoc, and it passed every other gate, because the other
    gates are structural and none of them looks at truth.
    """

    def test_omitting_both_flags_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "q.txt"
            prompt.write_text("une question\n", encoding="utf-8")
            rc = ob.main(["--prompt-file", str(prompt)])
        self.assertEqual(rc, 2, "silence must not be an acceptable answer")

    def test_both_flags_together_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "q.txt"
            prompt.write_text("une question\n", encoding="utf-8")
            rc = ob.main(["--prompt-file", str(prompt),
                          "--vault-context", "minitoc", "--no-vault-context"])
        self.assertEqual(rc, 2, "contradictory intent must be refused, not silently ranked")

    def test_a_vault_with_no_match_is_refused_not_answered_from_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            (vault / "30_Ressources" / "LaTEX").mkdir(parents=True)
            (vault / "30_Ressources" / "LaTEX" / "a.md").write_text(
                "rien sur ce sujet\n", encoding="utf-8")
            prompt = Path(tmp) / "q.txt"
            prompt.write_text("une question\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"OBSIDIAN_VAULT": str(vault)}):
                rc = ob.main(["--prompt-file", str(prompt),
                              "--vault-context", "sujetabsentducoffre"])
        self.assertEqual(rc, 2, "no match must refuse, never fall through to the model")

    def test_filename_match_outranks_a_longer_note_that_merely_mentions_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            res = vault / "30_Ressources" / "LaTEX"
            res.mkdir(parents=True)
            (res / "minitoc-le-vrai-sujet.md").write_text("court\n", encoding="utf-8")
            (res / "un-long-document.md").write_text("minitoc " * 200, encoding="utf-8")
            with mock.patch.dict(os.environ, {"OBSIDIAN_VAULT": str(vault)}):
                notes = ob.collect_vault_context("minitoc", limit=1)
        self.assertEqual(len(notes), 1)
        self.assertIn("minitoc-le-vrai-sujet", notes[0][0],
                      "a note NAMED for the subject must beat one that wins on volume")


class TestStructuredOutputConstraint(unittest.TestCase):
    """The vault event daemon asks the model for a JSON object whose shape is
    constrained at the sampler, not merely validated afterwards. The constraint
    travels in the top-level "format" field of the same request body, so the
    daemon keeps every decision this builder carries instead of assembling a
    second one of its own."""

    SCHEMA = {
        "type": "object",
        "properties": {"scope": {"type": "string", "enum": ["reusable", "project"]}},
        "required": ["scope"],
    }

    def test_a_schema_is_passed_through_untouched(self):
        payload = ob.build_payload("prompt", "some:tag", 7, 8192, fmt=self.SCHEMA)
        self.assertEqual(payload["format"], self.SCHEMA)
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"]["num_ctx"], 8192)

    def test_omitting_the_schema_leaves_the_body_byte_identical(self):
        """The failure this guards: a new optional parameter that silently
        changes what every existing caller sends would invalidate every
        measurement taken with this builder."""
        before = ob.build_payload("prompt", "some:tag", 7, 8192)
        after = ob.build_payload("prompt", "some:tag", 7, 8192, fmt=None)
        self.assertEqual(before, after)
        self.assertNotIn("format", before)


class TestThinkingDoesNotEatTheReplyReserve(unittest.TestCase):
    """Measured 2026-08-14 on Ollama 0.32.9: a reasoning model spent the whole 1024-token
    num_predict reserve inside its "thinking" field (done_reason "length") and returned an
    EMPTY "response". Three attempts per task failed that way, so the coder candidate
    scored 0/3 for a reason that had nothing to do with its coding. The bridge asks for an
    answer, not a monologue."""

    def test_payload_asks_the_daemon_not_to_think(self):
        payload = ob.build_payload("prompt", "some:tag", 7, 8192)
        self.assertIs(payload["think"], False)

    def test_a_daemon_that_rejects_the_field_is_retried_without_it_and_says_so(self):
        seen = []

        class FakeResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            body = json.loads(request.data.decode("utf-8"))
            seen.append("think" in body)
            if "think" in body:
                raise urllib.error.HTTPError(
                    ob.GENERATE_URL, 400, "Bad Request", {},
                    io.BytesIO(b'{"error":"registry does not support think"}'),
                )
            return FakeResponse(json.dumps({"response": "Reponse propre."}).encode("utf-8"))

        with mock.patch.object(ob.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = ob._post_generate(ob.build_payload("p", "t", 7, 8192), 5.0)

        self.assertEqual(result["response"], "Reponse propre.")
        self.assertEqual(seen, [True, False])  # tried with the field, then without

    def test_an_empty_body_names_its_cause(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Ecris une note.", encoding="utf-8")

            def transport(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": 12}
                return {"response": "", "done_reason": "length",
                         "thinking": "x" * 4259, "eval_count": 1024}

            with mock.patch.object(ob, "resolve_model", return_value="vendor-a:9b"), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport), \
                 self.assertLogs(ob.logger, level="WARNING") as logged:
                rc = ob.run_bridge(
                    prompt_path=prompt_path, verify_command=None, target_path=None,
                    seed=ob.DEFAULT_SEED, log_path=d / "log.jsonl", max_retries=1,
                )

        self.assertEqual(rc, 1)
        joined = "\n".join(logged.output)
        self.assertIn("done_reason='length'", joined)
        self.assertIn("thinking_chars=4259", joined)


class TestRoleReachesTheResolver(unittest.TestCase):
    """P4 (open-items pass): the bridge holds no role and no tag - it forwards what its
    caller declared it was doing to model_resolver.resolve(), which owns the per-role map.
    Without this, local-coder was served the writer model that scores 0/3 on coder tasks.
    """

    def test_role_flag_is_forwarded_to_resolve(self):
        seen = []

        class FakeResolver:
            @staticmethod
            def resolve(role=None):
                seen.append(role)
                return "vendor:7b"

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Ecris une note.", encoding="utf-8")

            def transport(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": 12}
                return {"response": "Reponse propre."}

            with mock.patch.dict(sys.modules, {"model_resolver": FakeResolver}), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                rc = ob.main([
                    "--prompt-file", str(prompt_path),
                    "--no-vault-context",
                    "--role", "coder",
                    "--log", str(d / "log.jsonl"),
                ])

        self.assertEqual(rc, 0)
        self.assertEqual(seen, ["coder"])

    def test_absent_role_resolves_exactly_as_before(self):
        seen = []

        class FakeResolver:
            @staticmethod
            def resolve(role=None):
                seen.append(role)
                return "vendor-a:9b"

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Ecris une note.", encoding="utf-8")

            def transport(payload, timeout):
                if _is_probe(payload):
                    return {"prompt_eval_count": 12}
                return {"response": "Reponse propre."}

            with mock.patch.dict(sys.modules, {"model_resolver": FakeResolver}), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                rc = ob.main([
                    "--prompt-file", str(prompt_path),
                    "--no-vault-context",
                    "--log", str(d / "log.jsonl"),
                ])

        self.assertEqual(rc, 0)
        self.assertEqual(seen, [None])


class TestNumCtxIsResolvedPerResolvedTag(unittest.TestCase):
    def test_window_is_read_for_the_tag_the_role_resolved_to(self):
        # 2026-08-27: the window used to come from a module-level constant read at
        # import time with NO tag, so every role shared one number and a config
        # describing two measured models made the import itself raise. run_bridge now
        # resolves the tag first (D7) and reads THAT tag's measured window, which is
        # what makes a writer at 16384 and a coder at 32768 coexist in one config.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Petit prompt.", encoding="utf-8")

            captured = []

            def transport(payload, timeout):
                captured.append(payload)
                if _is_probe(payload):
                    return {"prompt_eval_count": 12}
                return {"response": "Reponse propre."}

            lookup = mock.Mock(return_value=32768)
            with mock.patch.object(ob, "resolve_model", return_value="qwen2.5-coder:7b-gpu"), \
                 mock.patch.object(ob, "_resolve_num_ctx", lookup), \
                 mock.patch.object(ob, "_post_generate", side_effect=transport):
                rc = ob.run_bridge(
                    prompt_path=prompt_path,
                    verify_command=None,
                    target_path=None,
                    seed=ob.DEFAULT_SEED,
                    log_path=d / "log.jsonl",
                )

        self.assertEqual(rc, 0)
        lookup.assert_called_once_with("qwen2.5-coder:7b-gpu")
        self.assertTrue(captured)
        for payload in captured:
            self.assertEqual(payload["options"]["num_ctx"], 32768)


class TestMissingMeasuredWindowIsRefusedNotDefaulted(unittest.TestCase):
    def test_no_config_entry_for_the_resolved_tag_fails_the_run(self):
        # The no-silent-fallback rule (D7's lesson applied to the window): a tag with
        # no swept measurement must stop the run and name itself, never borrow another
        # model's number.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prompt_path = d / "prompt.txt"
            prompt_path.write_text("Petit prompt.", encoding="utf-8")

            stderr = io.StringIO()
            error = ob.context_budget.ConfigError(
                "[CONTEXT-BUDGET] config has no entry for model 'never-swept:9b'."
            )
            handler = logging.StreamHandler(stderr)
            ob.logger.addHandler(handler)
            try:
                with mock.patch.object(ob, "resolve_model", return_value="never-swept:9b"), \
                     mock.patch.object(ob, "_resolve_num_ctx", side_effect=error), \
                     mock.patch.object(ob, "_post_generate") as transport:
                    rc = ob.run_bridge(
                        prompt_path=prompt_path,
                        verify_command=None,
                        target_path=None,
                        seed=ob.DEFAULT_SEED,
                        log_path=d / "log.jsonl",
                    )
            finally:
                ob.logger.removeHandler(handler)

        self.assertEqual(rc, 1)
        self.assertIn("never-swept:9b", stderr.getvalue())
        transport.assert_not_called()



class TestSoleCodeFenceIsUnwrapped(unittest.TestCase):
    """
    Measured 2026-08-28 while investigating a coder candidate that scored 0/3. The model
    wrapped its module in a ```python fence despite the prompt forbidding one, the bridge
    wrote that text verbatim to a .py file, and every attempt died with "SyntaxError:
    invalid syntax" on line 1 - before a single test case ran. The oracle was grading
    punctuation, not code. strip_reasoning deliberately PROTECTS fences, so nothing in the
    pipeline ever removed an outer one.
    """

    def test_a_body_that_is_one_fenced_block_is_unwrapped(self):
        body = "```python\ndef f():\n    return 1\n```"

        self.assertEqual(ob.unwrap_sole_code_fence(body), "def f():\n    return 1")

    def test_the_language_tag_is_optional(self):
        self.assertEqual(ob.unwrap_sole_code_fence("```\nx = 1\n```"), "x = 1")

    def test_surrounding_whitespace_does_not_hide_the_fence(self):
        self.assertEqual(ob.unwrap_sole_code_fence("\n\n```py\nx = 1\n```\n\n"), "x = 1")

    def test_an_unfenced_body_is_returned_unchanged(self):
        body = "def f():\n    return 1\n"

        self.assertEqual(ob.unwrap_sole_code_fence(body), body)

    def test_prose_around_a_fence_is_left_alone(self):
        # A writer deliverable legitimately carries fenced code inside Markdown. Unwrapping
        # there would delete the prose, which is the whole document.
        body = "Here is the helper:\n\n```python\nx = 1\n```\n\nCall it once."

        self.assertEqual(ob.unwrap_sole_code_fence(body), body)

    def test_two_fenced_blocks_are_left_alone(self):
        # Two blocks are a document, not a module wrapped for display.
        body = "```python\nx = 1\n```\n\n```python\ny = 2\n```"

        self.assertEqual(ob.unwrap_sole_code_fence(body), body)

    def test_an_unterminated_fence_is_left_alone(self):
        # Truncated output. Silently dropping the opening marker would turn a broken
        # response into one that merely looks syntactically plausible.
        body = "```python\ndef f():\n    return 1"

        self.assertEqual(ob.unwrap_sole_code_fence(body), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
