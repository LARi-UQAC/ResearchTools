List every distinct thing the rubric section asks for, one entry per element, in the order of the section. Then judge
each element against the report pages, one verdict per element:

- present: the element is in the report and correct.
- partial: the element is in the report, but incomplete, or with one technical error.
- absent: the element is not in the report.

For a present or partial element, give its page number and a quote copied word for word from that page, one sentence at
most. An absent element has no page and no quote.

Set exceptional to true only when every element is present and the report shows clearly more than was asked, with a
quote for it. Otherwise set it to false.

The code computes the level from your verdicts, and the points from the level. Never write a level, a score or a number
for the level. The levels the code can give are: absent, attempted, partial, complete_correct and exemplary.
