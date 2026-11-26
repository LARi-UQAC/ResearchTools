"""
Documentation contract of plan 11 (Issue #104): the work-ugs-audit agent, its command and its skill definition
exist, the agent stays blind to the reports, both pause points are written, and every inventory names the three
new skills (language-review, figure-review, work-ugs-audit). It proves the rule is written where each reader
looks, never that a model obeyed it (R15). Each finder has a negative control on fictitious text (R20).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ("language-review", "figure-review", "work-ugs-audit")
# Files that hold student text or a grade. The agent must not name any of them as something to read.
FORBIDDEN_READ_TARGETS = ("grade.json", "annotations.json", "pages/", "annotated.pdf", "ids.json")
TRIGGER_WORDS = (("grading",), ("correction",), ("rubric", "grille"), ("undergraduate", "premier cycle"), ("PDF",))


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def frontmatter(text: str) -> dict:
    """The `key: value` lines of a leading `---` block; quotes around a value are removed."""
    match = re.match(r"---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    fields = {}
    for line in (match.group(1).splitlines() if match else []):
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields


def forbidden_targets_named(text: str) -> list:
    return [name for name in FORBIDDEN_READ_TARGETS if name in text]


def missing_names(text: str, names) -> list:
    return [name for name in names if name not in text]


def first_sentence(description: str) -> str:
    return re.split(r"(?<=[a-z)])\.\s", description, maxsplit=1)[0] + "."


class TestWorkUgsAuditContract(unittest.TestCase):

    def setUp(self):
        self.agent = read(".claude/agents/work-ugs-audit.md")

    def test_agent_tools_are_read_and_bash_only(self):
        self.assertEqual(frontmatter(self.agent)["tools"], "Read, Bash")
        self.assertEqual(frontmatter(self.agent)["name"], "work-ugs-audit")

    def test_agent_names_no_forbidden_read_target(self):
        self.assertEqual(forbidden_targets_named(self.agent), [])

    def test_agent_has_no_rubric_pause_and_keeps_the_third_loop_stop(self):
        self.assertNotIn("rubric-confirmation", self.agent)
        self.assertIn("PIPELINE-PAUSED @ third-loop", self.agent)
        self.assertRegex(self.agent, r"(?i)explicit answer")
        self.assertRegex(self.agent, r"(?i)there is no confirmation step")

    def test_a_failed_vision_probe_neither_asks_nor_stops_and_its_reason_is_relayed(self):
        self.assertRegex(self.agent, r"(?i)do not ask\s+a question and do not stop")
        self.assertIn("vision_not_validated", self.agent)
        self.assertIn("`reason`", self.agent)

    def test_the_long_run_is_started_detached(self):
        self.assertRegex(self.agent, r"(?i)detached")

    def test_the_agent_never_polls_the_run(self):
        self.assertNotIn("poll", self.agent.lower())
        self.assertNotIn("sleep", self.agent.lower())  # no sleep-loop either

    def test_the_agent_ends_its_turn_and_reads_the_marker_once(self):
        self.assertIn("run_in_background", self.agent)
        self.assertRegex(self.agent, r"(?i)end your turn")
        self.assertIn("run_done.json", self.agent)
        self.assertRegex(self.agent, r"(?i)read .*run_done\.json.* once")
        self.assertRegex(self.agent, r"(?i)do not call .status.")

    def test_the_command_reads_the_marker_once_and_never_polls(self):
        command = read(".claude/commands/work-ugs-audit.md")
        self.assertIn("run_done.json", command)
        self.assertRegex(command, r"(?i)never polls")

    def test_the_command_names_third_loop_as_its_only_pause(self):
        command = (ROOT / ".claude" / "commands" / "work-ugs-audit.md").read_text(encoding="utf-8")
        self.assertIn("only pause is `third-loop`", command)
        self.assertNotIn("rubric-confirmation", command)

    def test_agent_starts_no_third_loop_on_its_own(self):
        self.assertIn("--allow-third", self.agent)
        self.assertRegex(self.agent, r"never started on your own")

    def test_agent_ends_with_a_checklist(self):
        tail = self.agent.rstrip().split("## Exit checklist")[-1]
        self.assertGreaterEqual(len(re.findall(r"^\[ \] \d\.", tail, re.M)), 6)
        self.assertIn("PIPELINE INCOMPLETE", tail)
        self.assertTrue(self.agent.rstrip().endswith("before presenting the result."))

    def test_agent_names_roles_and_never_a_tag(self):
        for role in ("ugs-grader", "ugs-auditor", "ugs-vision"):
            self.assertIn(role, self.agent)
        self.assertNotRegex(self.agent, r"\b[a-z0-9.]+:[0-9]+(\.[0-9]+)?b\b", "a model tag is written in the agent")

    def test_command_dispatches_the_agent(self):
        command = read(".claude/commands/work-ugs-audit.md")
        self.assertIn("`work-ugs-audit` agent", command)
        self.assertIn("SendMessage", command)
        self.assertIn("PIPELINE-PAUSED", command)
        self.assertIn("$ARGUMENTS", command)

    def test_skill_description_first_sentence_has_trigger_words(self):
        description = frontmatter(read(".claude/skills/work-ugs-audit/SKILL.md"))["description"]
        sentence = first_sentence(description)
        self.assertGreaterEqual(len(sentence), 120)
        for alternatives in TRIGGER_WORDS:
            self.assertTrue(any(word in sentence for word in alternatives), alternatives)

    def test_routing_table_readme_architecture_and_manual_name_the_three_skills(self):
        for relative in (".claude/CLAUDE.md", "README.md", "Architecture.md", "docs/manual/06-skills.md"):
            self.assertEqual(missing_names(read(relative), SKILLS), [], relative)

    def test_commands_and_agents_pages_name_the_new_command_and_agent(self):
        self.assertIn("/work-ugs-audit", read("docs/manual/04-commands.md"))
        self.assertIn("work-ugs-audit", read("docs/manual/05-agents.md"))
        commands = read("docs/manual/04-commands.md")
        tikz_row = [line for line in commands.splitlines() if line.startswith("| `/tikz")]
        self.assertTrue(tikz_row, "the /tikz row exists")
        self.assertIn("figure-review", tikz_row[0])

    def test_the_agent_is_listed_in_the_routing_table_with_its_command(self):
        rows = [l for l in read(".claude/CLAUDE.md").splitlines() if l.startswith("|") and "work-ugs-audit" in l]
        self.assertTrue(any("`/work-ugs-audit`" in row for row in rows))

    # --- negative controls: the finders can fail ---

    def test_poll_finder_reports_a_planted_polling_instruction(self):
        self.assertIn("poll", "Poll status every minute until the run ends.".lower())

    def test_forbidden_target_finder_detects_a_planted_read(self):
        fictitious = "Read `R01/grade.json` and the pages/ folder to explain the grade."
        self.assertEqual(forbidden_targets_named(fictitious), ["grade.json", "pages/"])

    def test_missing_names_finder_reports_an_absent_skill(self):
        self.assertEqual(missing_names("only figure-review here", SKILLS), ["language-review", "work-ugs-audit"])

    def test_frontmatter_finder_reads_nothing_from_a_file_without_one(self):
        self.assertEqual(frontmatter("no block here"), {})

    def test_first_sentence_finder_stops_at_the_first_sentence(self):
        self.assertEqual(first_sentence("Grade the reports (PDF). Trigger on: x."), "Grade the reports (PDF).")


if __name__ == "__main__":
    unittest.main()
