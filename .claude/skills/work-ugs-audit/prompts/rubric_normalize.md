You turn the text of a grading rubric into a structured list of items. The assessment is a
{{ASSESSMENT_TYPE}}.

## Rules

- One rubric section is one item. Keep the sections in their order.
- id: I01, I02, and so on, in order.
- title: the section title, short.
- max_points: the points of the section as a number. Decimals are allowed (0.5, 2.5). Use the number
  written after a slash or in parentheses next to the section.
- criteria: what the section asks for, one short sentence each.
- checklist: each checkbox or tick line of the section, copied as one string without the box mark.
- total_points: the sum of the max_points of all items. If the text states a total, it must equal the sum.
- Do not invent an item, a criterion or a point value that the text does not give.
- Keep the language of the rubric.

## Rubric text

{{RUBRIC_TEXT}}

## Answer

Return one JSON object with the keys assessment_type, total_points and items. Nothing else.
