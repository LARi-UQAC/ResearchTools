# Progress

**Ceiling {{CEILING_PROGRESS}} tokens.** It is a ledger, not a report: one
`## <filename>` section per plan and one line per step. The harness re-reads
it on every call, so prose here is paid for on every call of every plan.

One `## <filename>` section per plan. The heading must match the plan's
filename exactly: the harness reads that section to decide whether the plan is
finished.

Three marks, and only three:

- `- [ ]` not done
- `- [x]` done, with a short result after the text
- `- [!]` blocked, with one line saying what blocked it

The harness adds its own lines here: `- [x] tests pass` after the suite runs,
and `- [ ] audit: ...` for anything the audit says must be fixed before the
next plan starts.

## plan1.md
- [ ] add subtract to calc.py, with its test
