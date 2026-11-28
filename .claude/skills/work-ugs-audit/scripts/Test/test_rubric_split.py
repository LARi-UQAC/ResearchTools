"""
Offline tests for rubric_split (Issue 120, plan 1): a Markdown rubric is split by the code on its numbered
sections and every section keeps its exact text. Fictitious rubric text only (R34), no model, no network (R21).
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rubric_split  # noqa: E402
import ugs_config  # noqa: E402

CONFIG = ugs_config.load(ugs_config.default_path())
HEADING = CONFIG["rubric.section_heading_regex"]
TOTAL = CONFIG["rubric.total_regex"]
LOOSE = CONFIG["rubric.loose_heading_regex"]

SAMPLE = """# Grille d'exemple

**Total : 3.5 points**, repartis comme suit.

| # | Section | Points |
|---|---------|-------:|
| 1 | Resume | 1 |
| 2 | Methode | 2 |
| 3 | Conclusion | 0.5 |

## Acronymes

| Acronyme | Signification |
|----------|---------------|
| ABC | Guide fictif de la pratique |

---

## 1. Resume (/1)

Le resume fait environ **250 mots** et comprend :

- [ ] Contexte
- [ ] Objectif

---

## 2. Methode (/2)

Selon l'ABC :

> Une citation fictive qui doit rester intacte.

| Type | Information |
|------|-------------|
| Essais | nom de l'appareil |

> **Exigence.** Un texte coherent et precis.

---

## 3. Conclusion (/0.5)

Rappel des objectifs et des contraintes du client.
"""


def split(text=SAMPLE):
    return rubric_split.split_rubric(text, "project_report", HEADING, TOTAL, LOOSE)


class SplitTests(unittest.TestCase):

    def test_items_carry_id_title_points_in_order(self):
        rubric = split()
        self.assertEqual(rubric["assessment_type"], "project_report")
        self.assertEqual([i["id"] for i in rubric["items"]], ["I01", "I02", "I03"])
        self.assertEqual([i["title"] for i in rubric["items"]], ["Resume", "Methode", "Conclusion"])
        self.assertEqual([i["max_points"] for i in rubric["items"]], [1, 2, 0.5])
        self.assertEqual(rubric["total_points"], 3.5)

    def test_each_section_keeps_its_exact_text_without_the_closing_rule(self):
        rubric = split()
        second = rubric["items"][1]["text"]
        self.assertTrue(second.startswith("## 2. Methode (/2)\n"))
        for kept in ("> Une citation fictive qui doit rester intacte.", "| Essais | nom de l'appareil |",
                     "> **Exigence.** Un texte coherent et precis."):
            self.assertIn(kept, second)
        self.assertFalse(second.rstrip().endswith("---"))
        self.assertTrue(rubric["items"][0]["text"].rstrip().endswith("- [ ] Objectif"))

    def test_the_last_section_runs_to_the_end_of_the_text(self):
        self.assertTrue(split()["items"][2]["text"].rstrip().endswith("contraintes du client."))

    def test_preamble_is_kept_whole_and_copied_into_each_item(self):
        rubric = split()
        self.assertIn("| ABC | Guide fictif de la pratique |", rubric["preamble"])
        self.assertIn("**Total : 3.5 points**", rubric["preamble"])
        for item in rubric["items"]:
            self.assertEqual(item["preamble"], rubric["preamble"])

    def test_a_wrong_stated_total_is_refused_naming_both_numbers(self):
        with self.assertRaises(rubric_split.RubricSplitError) as ctx:
            split(SAMPLE.replace("**Total : 3.5 points**", "**Total : 9 points**"))
        self.assertIn("9", str(ctx.exception))
        self.assertIn("3.5", str(ctx.exception))

    def test_no_stated_total_is_accepted(self):
        rubric = split(SAMPLE.replace("**Total : 3.5 points**, repartis comme suit.", ""))
        self.assertEqual(rubric["total_points"], 3.5)

    def test_fewer_than_two_numbered_sections_returns_none(self):
        self.assertIsNone(split("# Titre\n\n## 1. Seule section (/2)\n\ntexte\n"))
        self.assertIsNone(split("Du texte libre sans section numerotee.\n"))

    def test_comma_points_are_read(self):
        rubric = split(SAMPLE.replace("(/0.5)", "(/0,5)"))
        self.assertEqual(rubric["items"][2]["max_points"], 0.5)

    def test_a_numbered_heading_without_points_is_refused_naming_it(self):
        for bad in ("## 4. Annexes\n\ntexte\n", "## 4. Annexes (10 points)\n\ntexte\n"):
            with self.assertRaises(rubric_split.RubricSplitError) as ctx:
                split(SAMPLE + "\n---\n\n" + bad)
            self.assertIn("## 4. Annexes", str(ctx.exception))

    def test_a_sub_heading_and_the_acronym_heading_are_not_refused(self):
        rubric = split(SAMPLE.replace("Selon l'ABC :", "### 2.1 Description\n\nSelon l'ABC :"))
        self.assertIn("### 2.1 Description", rubric["items"][1]["text"])

    def test_a_numbered_level_three_sub_heading_stays_inside_its_section(self):
        rubric = split(SAMPLE.replace("Selon l'ABC :", "### 2. Verifier le circuit\n\nSelon l'ABC :"))
        self.assertEqual(len(rubric["items"]), 3)
        self.assertIn("### 2. Verifier le circuit", rubric["items"][1]["text"])

    def test_a_total_stated_at_the_end_of_the_text_is_checked(self):
        with self.assertRaises(rubric_split.RubricSplitError):
            split(SAMPLE.replace("**Total : 3.5 points**, repartis comme suit.", "") + "\n**Total : 8 points**\n")

    def test_more_than_ninety_nine_sections_are_refused(self):
        text = "".join("## %d. S%d (/1)\n\ntexte\n\n" % (n, n) for n in range(1, 101))
        with self.assertRaises(rubric_split.RubricSplitError):
            split(text)


class PromptTextTests(unittest.TestCase):

    def test_a_split_item_gives_its_text_and_the_acronym_block(self):
        rubric = split()
        text = rubric_split.item_prompt_text(rubric["items"][1])
        self.assertIn("> Une citation fictive qui doit rester intacte.", text)
        self.assertIn("| ABC | Guide fictif de la pratique |", text)
        self.assertNotIn("{'id'", text)

    def test_an_item_without_text_keeps_the_old_rendering(self):
        item = {"id": "I01", "title": "Resume", "max_points": 1, "criteria": ["Un critere."],
                "checklist": ["Une case"]}
        text = rubric_split.item_prompt_text(item)
        self.assertIn("I01 - Resume (1)", text)
        self.assertIn("- Un critere.", text)
        self.assertIn("- Une case", text)

    def test_markdown_of_a_split_item_is_its_exact_text(self):
        item = split()["items"][1]
        self.assertEqual(rubric_split.item_markdown(item), item["text"])


class KeptTextTests(unittest.TestCase):

    def test_a_faithful_rubric_keeps_every_long_line(self):
        self.assertIsNone(rubric_split.check_text_kept(SAMPLE, split(), 4))

    def test_a_removed_line_is_named(self):
        rubric = copy.deepcopy(split())
        rubric["items"][1]["text"] = rubric["items"][1]["text"].replace(
            "> Une citation fictive qui doit rester intacte.", "")
        missing = rubric_split.check_text_kept(SAMPLE, rubric, 4)
        self.assertIn("Une citation fictive", missing)

    def test_a_line_repeated_in_two_sections_must_be_kept_in_both(self):
        repeated = "- [ ] Les unites sont indiquees partout dans le texte"
        source = SAMPLE.replace("- [ ] Contexte", repeated).replace(
            "Rappel des objectifs et des contraintes du client.", repeated)
        rubric = copy.deepcopy(split(source))
        self.assertIsNone(rubric_split.check_text_kept(source, rubric, 4))
        rubric["items"][2]["text"] = rubric["items"][2]["text"].replace(repeated, "")
        missing = rubric_split.check_text_kept(source, rubric, 4)
        self.assertIn("Les unites sont indiquees", missing)

    def test_case_and_spacing_are_ignored_and_short_lines_are_not_checked(self):
        rubric = copy.deepcopy(split())
        rubric["items"][0]["text"] = rubric["items"][0]["text"].replace(
            "Le resume fait environ", "LE  RESUME   fait environ")
        self.assertIsNone(rubric_split.check_text_kept(SAMPLE, rubric, 4))
        self.assertIsNone(rubric_split.check_text_kept("Mot seul\n", rubric, 4))


class ConfigTests(unittest.TestCase):

    def test_shipped_keys_load_and_the_regex_reads_a_heading(self):
        import re
        match = re.match(HEADING, "## 3. Titre long avec (parentheses) (/10)")
        self.assertEqual((match.group("n"), match.group("title"), match.group("points")),
                         ("3", "Titre long avec (parentheses)", "10"))
        self.assertGreaterEqual(CONFIG["rubric.min_check_words"], 1)
        self.assertTrue(re.match(LOOSE, "## 4. Annexes"))
        self.assertFalse(re.match(LOOSE, "### 3.1 Description"))
        self.assertTrue(re.search(TOTAL, "**Total : 28.5 points**").group("total"))

    def test_a_missing_key_is_refused_by_the_loader_naming_it(self):
        for key in ("rubric.section_heading_regex", "rubric.total_regex", "rubric.min_check_words",
                    "rubric.loose_heading_regex"):
            self.assertIn(key, ugs_config.REQUIRED_KEYS)


ELEMENT_RULES = CONFIG["rubric.element_regexes"]

CHECKLIST_SECTION = """## 1. Resume (/1)

Le resume contient :

- [ ] Contexte
- [ ] Objectif
- [ ] Methode
- [ ] Resultat
- [ ] Conclusion
- [ ] Mots cles
"""

NUMBERED_SECTION = """## 2. Methode (/2)

1. **Essais** : nom de l'appareil
2. **Mesures** : unites
3. **Calcul** : formule
"""

BULLETS_ONLY_SECTION = """## 3. Conclusion (/0.5)

- Rappel des objectifs
- Limites
"""

MIXED_SECTION = """## 4. Mixte (/1)

1. **Ancien** : numerote
- [ ] Coche un
- [ ] Coche deux
"""


class ElementTests(unittest.TestCase):

    def test_six_checklist_lines_give_six_elements_in_order(self):
        elements = rubric_split.section_elements(CHECKLIST_SECTION, ELEMENT_RULES)
        self.assertEqual([e["id"] for e in elements], ["E1", "E2", "E3", "E4", "E5", "E6"])
        self.assertEqual([e["text"] for e in elements],
                         ["Contexte", "Objectif", "Methode", "Resultat", "Conclusion", "Mots cles"])

    def test_numbered_points_give_elements_with_the_bold_label_kept(self):
        elements = rubric_split.section_elements(NUMBERED_SECTION, ELEMENT_RULES)
        self.assertEqual([e["text"] for e in elements],
                         ["**Essais** : nom de l'appareil", "**Mesures** : unites", "**Calcul** : formule"])

    def test_bullets_without_a_checkbox_give_no_element(self):
        self.assertEqual(rubric_split.section_elements(BULLETS_ONLY_SECTION, ELEMENT_RULES), [])

    def test_checkbox_lines_win_over_numbered_points_in_the_same_section(self):
        elements = rubric_split.section_elements(MIXED_SECTION, ELEMENT_RULES)
        self.assertEqual([e["text"] for e in elements], ["Coche un", "Coche deux"])

    def test_split_items_carry_their_elements(self):
        rubric = rubric_split.split_rubric(CHECKLIST_SECTION + "\n---\n\n" + NUMBERED_SECTION, "report",
                                           HEADING, TOTAL, LOOSE, ELEMENT_RULES)
        self.assertEqual(len(rubric["items"][0]["elements"]), 6)
        self.assertEqual(len(rubric["items"][1]["elements"]), 3)

    def test_without_element_rules_items_have_no_elements_key(self):
        rubric = rubric_split.split_rubric(CHECKLIST_SECTION + "\n---\n\n" + NUMBERED_SECTION, "report",
                                           HEADING, TOTAL, LOOSE)
        self.assertNotIn("elements", rubric["items"][0])

    def test_the_element_rules_key_is_required_and_named_when_missing(self):
        self.assertIn("rubric.element_regexes", ugs_config.REQUIRED_KEYS)


class ElementRuleValidationTest(unittest.TestCase):
    """Review round 1, group B, finding 13: the element rules are checked at load, and a number is an element at column 0."""

    @staticmethod
    def load_with(rules):
        """Load the shipped configuration with another element rule list, from a temporary file (fictitious)."""
        import tempfile
        raw = json.loads(ugs_config.default_path().read_text(encoding="utf-8"))
        raw["rubric.element_regexes"]["value"] = rules
        path = Path(tempfile.mkdtemp()) / "ugs_config.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return ugs_config.load(path)

    def test_a_rule_that_does_not_compile_is_a_named_error(self):
        with self.assertRaises(ugs_config.ConfigError) as ctx:
            self.load_with(["(unclosed"])
        self.assertIn("rubric.element_regexes", str(ctx.exception))

    def test_a_rule_without_a_capture_group_is_a_named_error(self):
        with self.assertRaises(ugs_config.ConfigError) as ctx:
            self.load_with(["^\\s*- \\[ \\]\\s+.+$"])
        self.assertIn("rubric.element_regexes", str(ctx.exception))

    def test_an_indented_nested_number_is_not_an_element(self):
        text = "## 1. Resume (/1)\n\n1. **Un** : a\n   2. nested point\n3. **Trois** : c\n"
        elements = rubric_split.section_elements(text, ELEMENT_RULES)
        self.assertEqual([e["text"] for e in elements], ["**Un** : a", "**Trois** : c"])


REAL_RUBRIC = os.environ.get("UGS_REAL_RUBRIC")


@unittest.skipUnless(REAL_RUBRIC, "UGS_REAL_RUBRIC not set: real rubric not read")
class RealRubricElementsTest(unittest.TestCase):

    def test_section_one_has_six_elements_and_counts_are_recorded(self):
        text = Path(REAL_RUBRIC).read_text(encoding="utf-8")
        rubric = rubric_split.split_rubric(text, "report", HEADING, TOTAL, LOOSE, ELEMENT_RULES)
        counts = {item["id"]: len(item["elements"]) for item in rubric["items"]}
        # Numbers only: the section id and its element count, never the rubric text.
        print("element counts per section: %s" % counts, file=sys.stderr)
        self.assertEqual(counts["I01"], 6)


if __name__ == "__main__":
    unittest.main()
