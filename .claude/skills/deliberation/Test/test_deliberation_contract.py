"""Offline documentation contract for the deliberation panel and its host agents (R15).

Documentation only: it proves the rules are WRITTEN where every host agent reads them, never that a
model obeyed them. It exists because the panel is shared by seven agents and three of its failure
modes were invisible until measured: a Log that could drop a reviewer item in silence, a rebuttal
round that never saw the context, and stale statements (a fixed model name, a fixed token cap)
that no longer matched the code. Every check carries its negative control so it can fail."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PROTOCOL = ROOT / ".claude" / "skills" / "deliberation" / "references" / "deliberation-protocol.md"
SKILL = ROOT / ".claude" / "skills" / "deliberation" / "SKILL.md"
AGENTS = ROOT / ".claude" / "agents"
COMMANDS = ROOT / ".claude" / "commands"

# The agents that RUN the panel through deliberate.py; litreview-updater runs it too, with the
# command in its own Step 6.
HOSTS = ("paper-auditor", "thesis-auditor", "thesis-proposal-auditor", "scopus-auditor",
         "scopus-researcher", "reviewer-response", "litreview-updater")
# Agents that explicitly do NOT run it.
NON_HOSTS = ("bib-cleaner", "submit-checker", "abstract-writer")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def missing(body: str, needles) -> list:
    """The needles absent from body (the finder every check below uses, so one negative control
    covers them all)."""
    return [needle for needle in needles if needle not in body]


def deliberate_commands(body: str) -> list:
    """Every line of body that invokes deliberate.py."""
    return [line for line in body.splitlines() if "deliberate.py" in line and "--stdin" in line]


class TestFinder(unittest.TestCase):
    def test_the_finder_reports_what_is_absent_and_only_that(self):
        self.assertEqual(missing("alpha beta", ["alpha", "gamma"]), ["gamma"])
        self.assertEqual(missing("alpha beta", ["alpha"]), [])

    def test_the_command_finder_ignores_prose_that_merely_names_the_script(self):
        body = "the script deliberate.py resolves a model\necho x | python deliberate.py --stdin --rounds 2"
        self.assertEqual(len(deliberate_commands(body)), 1)


class TestProtocol(unittest.TestCase):
    def test_the_protocol_states_that_any_object_may_be_deliberated_with_its_full_context(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, [
            "not limited to a kind of object", "research question", "methodological choice", "a table", "a result",
            "## 10. The context every submission must carry", "self-sufficient", "round2-include-draft"]), [])

    def test_the_arbitration_table_covers_every_suggestion_type_the_reviewers_may_return(self):
        body = text(PROTOCOL)
        for kind in ("text_improvement", "reference_issue", "coverage_gap", "style", "structure"):
            self.assertIn(f"`{kind}`", body, kind)

    def test_the_arbitration_table_has_a_row_for_an_off_topic_suggestion_and_a_relevance_step(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, ["Off topic", "judges RELEVANCE", "A confident tone is not evidence"]), [])

    def test_the_log_must_account_for_every_merged_item(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, ["Accounting:", "every id M1..MN appears", "exactly once in the four lists"]), [])

    def test_the_pairing_by_meaning_is_required_because_the_script_pairs_literally(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, ["pairs such\n  items by MEANING", "`id`"]), [])

    def test_the_local_fallback_is_documented_with_its_marker_and_agreement_value(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, ["`ollama_only`", "[✓ OLLAMA]", "`session`", "`fallback`"]), [])

    def test_the_protocol_names_no_fixed_model_and_no_stale_cap(self):
        body = text(PROTOCOL)
        for stale in ("Gemini 2.0 Flash", "GPT-4o", "--max-output-tokens 2048"):
            self.assertNotIn(stale, body, stale)

    def test_a_digest_is_declared_a_loss_of_context_never_silent(self):
        body = text(PROTOCOL)
        self.assertEqual(missing(body, ["LOSS of context", "never silently", "never given a digest"]), [])


class TestHostAgents(unittest.TestCase):
    def test_every_host_agent_exists_and_runs_the_panel_with_the_round_two_context(self):
        for name in HOSTS:
            body = text(AGENTS / f"{name}.md")
            commands = deliberate_commands(body)
            self.assertTrue(commands, f"{name} carries no deliberate.py command")
            for command in commands:
                self.assertIn("--round2-include-draft", command, name)

    def test_every_host_agent_makes_the_arbitrator_account_for_every_item(self):
        for name in HOSTS:
            body = text(AGENTS / f"{name}.md")
            self.assertIn("EVERY", body, name)
            self.assertIn("Accounting", body, name)

    def test_every_host_agent_reads_the_context_record_before_arbitrating(self):
        for name in HOSTS:
            self.assertIn("`context` record", text(AGENTS / f"{name}.md"), name)

    def test_every_host_agent_judges_relevance_and_pairs_by_meaning(self):
        for name in HOSTS:
            body = text(AGENTS / f"{name}.md")
            self.assertIn("relevance", body, name)
            self.assertIn("pair by meaning", body, name)

    def test_no_host_agent_still_claims_a_fixed_model_cap_or_a_token_only_skip_rule(self):
        for name in HOSTS + ("thesis-to-paper",):
            body = text(AGENTS / f"{name}.md")
            self.assertNotIn("gpt-4o", body.lower(), name)
            self.assertNotIn("~8k", body, name)
            self.assertNotRegex(body, r"AND\s+`GITHUB_TOKEN`", name)

    def test_the_agents_that_pipe_an_audit_summary_also_pipe_the_passages_it_is_about(self):
        for name in ("paper-auditor", "thesis-auditor", "thesis-proposal-auditor", "scopus-auditor", "reviewer-response"):
            body = text(AGENTS / f"{name}.md")
            self.assertRegex(body, r"verbatim passage", name)
            self.assertIn("last resort", body, name)

    def test_litreview_updater_states_its_question_its_context_and_its_command(self):
        body = text(AGENTS / "litreview-updater.md")
        self.assertIn("The question travels WITH its context", body)
        self.assertIn("--plan-schema researcher", body)

    def test_the_agents_that_do_not_run_the_panel_never_claim_to(self):
        for name in NON_HOSTS:
            body = text(AGENTS / f"{name}.md")
            self.assertEqual(deliberate_commands(body), [], name)


class TestCommands(unittest.TestCase):
    def test_commands_of_agents_that_do_not_run_the_panel_do_not_list_it_as_mandatory(self):
        for name in ("bibclean", "submitcheck"):
            body = text(COMMANDS / f"{name}.md")
            self.assertNotRegex(body, r"\(deliberation, scholar-evaluation", name)
            self.assertIn("does not run the", body.replace("\n", " "), name)

    def test_the_commands_of_the_host_agents_still_name_the_panel(self):
        for name in ("auditpaper", "auditthesis", "auditreview", "replyreviewer", "litreview", "litupdate"):
            self.assertIn("deliberation", text(COMMANDS / f"{name}.md"), name)


class TestSkill(unittest.TestCase):
    def test_the_skill_is_not_narrowed_to_one_kind_of_object(self):
        body = text(SKILL)
        self.assertEqual(missing(body, ["any object of the work", "a methodological\nchoice, a table, a result"]), [])
        self.assertIsNone(re.search(r"Never send a whole chapter", body), "the skill must not forbid a whole chapter")
        self.assertIsNone(re.search(r"one question per type of hypothesis", body), "the skill must not limit questions to hypotheses")

    def test_the_skill_still_describes_the_original_near_final_draft_use(self):
        self.assertIn("near-final", text(SKILL))


if __name__ == "__main__":
    unittest.main()
