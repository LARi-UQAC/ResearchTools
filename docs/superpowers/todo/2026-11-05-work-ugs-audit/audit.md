# Review rounds of Issue #104 (R35)

Bounds: 3 rounds, 1500000 tokens, plateau 2 (owner, 2026-11-05). Round 1 ran on 2026-11-15 against main: `code-review` at high effort (10 findings) and `security-review` (1 finding).

## Fixed, each with a test that failed first (R20)

| Finding | File | Test |
|---|---|---|
| numbered references (`1. Smith, J. 2020.`) read as a section heading, every reference lost | `ugs_text.py` | `test_numbered_dot_references_are_entries_and_not_headings`, `test_a_numbered_section_heading_after_the_list_still_ends_it` |
| a reasoning-marker anomaly escaped the retry as a `RuntimeError` and failed the report | `ugs_bridge.py` | `test_a_reasoning_anomaly_is_a_retryable_unparsable_not_an_escape` |
| `add_report` used a substring test, so `## R1` matched inside `## R10` | `ugs_ledger.py` | `test_a_report_id_that_begins_another_id_is_still_added` |
| a URL followed by punctuation was checked with it, and servers refusing HEAD were reported unreachable | `ref_check.py` | `test_punctuation_after_a_url_is_not_part_of_it`, `test_a_server_that_refuses_head_is_asked_with_get` |

## Declined, by the owner

- `figure_render.py`, TikZ compile, untrusted LaTeX (security review, Medium): a file-reading package such as `pgfplotstable` is not on the refusal list. Declined on 2026-11-15, owner decision: the real boundary is the final system of Issue 107, not a devcontainer (a devcontainer is one deployment of it). The case is written into Issue 107 as a comment (scanner for executable document formats, allowlist, confined execution, acceptance tests with planted files). Until then `--render` is off by default and `SKILL.md` says not to use it on an untrusted document.

## Deferred, outside Issue #104 (the aider kit, its watchdog and the dashboard)

Owner instruction: do not touch other Issues. Listed in the pull request body.

- `watchdog/main.go`: the stop signal is written after the kill, so the driver may read it too late.
- `watchdog/tracker.go`: a reference negligible on both CPU and GPU leaves `isLow` true; unjudged readings do not reset the streak; zero settings accepted.
- `aider-plan-core.ps1`: `Measure-PlanTests` runs each test file as a script, not through the configured test command.
- `scripts/lib/rt-aider-path.ps1`: the user Path is rewritten as an expanded REG_SZ.
- `rt-observe/scripts/collect_rex.py`: two PowerShell processes on a 3 second TTL.
- `aider-plan.ps1`: the cycle-archive check counts `[~]` steps as open.
