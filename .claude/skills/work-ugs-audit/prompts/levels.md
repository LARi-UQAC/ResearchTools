List every distinct thing the rubric section asks for, one entry per element, in the order of the section. Give each
element one name and never list it twice. Then judge each element against the report pages, with one verdict:

- present: the element is in the report and correct.
- partial: the element is in the report, but incomplete, or with one technical error.
- absent: the element is not in the report.

For a present or partial element, give its page number and a quote copied word for word from that page. The quote
is plain text, twelve words at most, with no table bars and no Markdown marks. An absent element has no page and no
quote.

The code computes the level from your verdicts, and the points from the level. An element whose quote the code
cannot find on the page counts as partial. A single partial element and nothing else gives the level attempted; a
present element is needed for the level partial or better. Never write a level, a score or a number for the level.

Set exceptional to true only when every element is present and the report shows clearly more than was asked, with a
quote for each. Otherwise set it to false.

The levels the code can give are: absent, attempted, partial, complete_correct and exemplary.
