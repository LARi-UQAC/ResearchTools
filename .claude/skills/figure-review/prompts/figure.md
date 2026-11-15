## single

You judge ONE figure of a technical report. The image is attached. Judge only what you can see in it.

First name the kind of figure: chart (curves, bars or points on axes), diagram (blocks and arrows),
flowchart (decision boxes), photo, or other. Then judge each criterion listed below, using the
criterion id exactly as written. Judge only the criteria that fit the kind you named. For a criterion
that does not fit, answer not_applicable.

The program already measured some points. Do not overturn them: use them only to explain.

Measured by the program:

{{SCRIPT_VERDICTS}}

Caption of the figure: {{CAPTION}}

Text of the report that cites the figure:

{{CITING_TEXT}}

Criteria to judge (id | label | kinds it applies to):

{{CRITERIA}}

Answer with one JSON object with the keys kind and criteria. Criteria is a list of objects with the keys
id, verdict (pass, fail or not_applicable) and reason (one short sentence). Give one object for every
criterion listed, and no other id. Nothing else.

## set

You judge a set of {{FIGURE_COUNT}} figures of one report, shown together in one image, one figure per
tile. Judge only this criterion: {{CRITERION}}

Answer with one JSON object with the keys verdict (pass, fail or not_applicable), reason (one short
sentence) and figures_involved (the tile numbers, starting at 1, that break the criterion; an empty list
when it holds). Nothing else.
