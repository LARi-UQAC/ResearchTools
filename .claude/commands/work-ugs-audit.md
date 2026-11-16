# Grade undergraduate reports (work-ugs-audit)

Grade a folder of undergraduate student reports (PDF) against a rubric with local models only, through the
`work-ugs-audit` agent. The agent is blind to the report content on purpose.

Procedure:

1. Resolve from `$ARGUMENTS` (or ask, grouped, if missing): the reports folder, the rubric file (JSON, Markdown,
   text or PDF) and the assessment type.
2. Dispatch the `work-ugs-audit` agent with those three values. Do not restate or reduce its pipeline.
3. When the agent ends with `PIPELINE-PAUSED @ <step>`, relay it verbatim to the user, then send the answer back
   to the same agent with SendMessage. The only pause is `third-loop`, a cost bound: there is no rubric confirmation.
4. Before presenting the result, check the agent's exit checklist. If it is missing or carries an unsanctioned
   ✗, send the agent back to finish instead of reporting.

$ARGUMENTS
