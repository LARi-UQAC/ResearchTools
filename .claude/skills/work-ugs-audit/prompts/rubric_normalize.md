You turn the text of a grading rubric into a structured list of items. The assessment is a
{{ASSESSMENT_TYPE}}.

## Rules

- One rubric section is one item. Keep the sections in their order.
- id: I01, I02, and so on, in order.
- title: the section title.
- max_points: the points of the section as a number. Decimals are allowed (0.5, 2.5). Use the number
  written after a slash or in parentheses next to the section.
- text: the text of the section, copied WHOLE and word for word from the rubric, with its tables, quotations,
  lists and checkboxes. Never remove, shorten or reword a sentence. You may only restructure.
- criteria and checklist are optional: leave them out unless the rubric has them.
- preamble: the text before the first section (title, points table, acronyms), copied whole. Leave it
  out when there is none.
- total_points: the sum of the max_points of all items. If the text states a total, it must equal the sum.
- Do not invent an item, a criterion or a point value that the text does not give.
- Keep the language of the rubric.

## Rubric text

{{RUBRIC_TEXT}}

## Answer

Return one JSON object with the keys assessment_type, total_points and items. Nothing else.
