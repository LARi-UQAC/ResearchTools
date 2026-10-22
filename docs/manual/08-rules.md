# Rules and conventions

Chapter 08 of the ResearchTools manual. Back to [table of contents](../../README.md).

The working rules of this repository are numbered `R0` to `R38`. A number is stable: a review, a
commit message or an audit plan cites it, and a rule never changes number. They are unrelated to the
`R1.x` sentence rules of the `scientific-writing` skill, which govern prose and not code.

The rules live in five files under `.claude/rules/`. That folder is linked whole into
`~/.claude/rules/`, so a saved edit is active in every project on the machine at once. Be careful
with it.

| File | Holds | Rules |
|---|---|---|
| `code-style.md` | Naming, constants and configuration, data versus code, docstrings, error handling, script interface, determinism, logging | R0 to R13, R16, R17, R19, R27 |
| `preferences.md` | Documentation structure, language, verified claims, how to ask and answer the user | R14, R15, R22, R23, R25, R28 |
| `security.md` | Secrets, dependency audits, the personal-data guard, vault and graph access, skill provenance, path containment | R24 |
| `testing.md` | Test principles, the inventory of every script and its offline test, CI | R20, R21, R34 |
| `workflows.md` | Research and writing flows, local delegation, plan shape, tracking, code placement, skill-first, review and branch rules | R18, R26, R29 to R33, R35 to R38 |

`testing.md` is also the discovery path for scripts: search its inventory before writing a new
script, and extend an existing one with a flag instead of forking it.

## Rule index

| Rule | In one line |
|---|---|
| R0 | No hardcoded number: thresholds, limits, timeouts and ports come from a configuration file |
| R1 | No hardcoded path: it resolves from an environment variable or a configuration file |
| R2 | One module owns each external identifier (a model tag, an API host, a DOI prefix) |
| R3 | A missing configuration value is an explicit error naming the key and the file |
| R4 | A numeric key carries its unit and its provenance (measured, specified or chosen) |
| R5 | An enum-like literal comes from one table |
| R6 | A list of literals is data in a JSON, CSV or YAML file, not code |
| R7 | No per-manuscript, per-student or per-course specific inside repository code |
| R8 | No silent fallback: a missing dependency stops the run and names itself |
| R9 | Verify the effect, not the return code, whenever the tool is known to lie |
| R10 | Every network and subprocess call has an explicit timeout and a bounded retry count |
| R11 | A hook exits 0 and says nothing when its own dependency is absent |
| R12 | Exit codes mean something: 0 success, 2 refusal by design, other non-zero failure |
| R13 | A measured number in prose carries its date and what measured it |
| R14 | No invented API, flag, path or file name: check it exists first |
| R15 | A documented claim about behaviour names the test that proves it, or is marked unverified |
| R16 | A state-changing script offers `--dry-run`, and a destructive path also needs `--yes` |
| R17 | A state-changing script emits a machine-readable report beside its text |
| R18 | A script lives beside its only caller; several callers mean a repository-wide home |
| R19 | No wall clock and no unseeded randomness in logic that must be reproducible |
| R20 | Every test suite asserts at least one failure path |
| R21 | No test reads machine-local measured configuration |
| R22 | Agent, skill, command and `CLAUDE*.md` definition files are English only |
| R23 | A change to a script's command-line surface updates its line in the `testing.md` inventory |
| R24 | A path derived from input is resolved, then checked to sit inside an allowed root |
| R25 | A question to the user states the origin, what each option does and what it costs, with the recommended option first |
| R26 | A multi-step task is planned in files (`spec.md`, `plan<N>.md`, `progress.md`) with a fixed shape and size ceilings |
| R27 | Every function carries a header a caller can act on: purpose, inputs, outputs, raises |
| R28 | A direct question gets a short plain answer before any action, and work waits for confirmation |
| R29 | A plan states what to build, never a literal code block to transcribe |
| R30 | A pull request carries a linked Issue, and the Issue has a card on the project board |
| R31 | A pull request does not merge until the documentation it touched is updated in the same PR |
| R32 | On the shared working tree, never assume you are alone and never switch branch without checking |
| R33 | A plan's doc task updates the public docs too, the README and the MkDocs pages |
| R34 | A fixture never carries a real identity |
| R35 | No pull request opens until a bounded local security and code review comes back clean |
| R36 | No task runs without a skill, or an agent that uses one; a missing skill is authored here, never installed from the internet |
| R37 | Never link a dependency folder into a worktree; call the main clone's interpreter by absolute path |
| R38 | Any coding request beyond a single step gets plan files with a header before any code |

## Written rule or enforced rule

Some rules are checked by a hook at the tool boundary, and some are only written and proven present
by a documentation test. The test proves the rule is written where the harness reads it, never that
a model obeyed it.

| Rule | Mechanical check |
|---|---|
| R25 | `askuserquestion-clarity.py` |
| R35 | `review-loop-guard.py` |
| R37 | `worktree-link-guard.py` |
| R38 | `local-coder-dispatch-guard.py` and `review-loop-guard.py` |
| Vault and graph access | `vault-access-guard.py` |
| R36 and the others | Documentation tests only, for example `test_skill_first_rule.py` |

The hooks are in [chapter 07](07-hooks.md).

## How the rules reach other harnesses

`install.ps1` regenerates the rules for each harness from `.claude/rules/*.md`: one
`.github/instructions/<name>.instructions.md` per file for GitHub Copilot, and the cross-cutting
rules inside `AGENTS.md`. Rerun it after editing a rule and commit the output with the change. See
[chapter 09](09-harnesses.md).

## Adding or changing a rule

Add the rule to the file that enforces it, and update the "Rule identifiers" index in `code-style.md`
in the same edit. An index that lags is a map that is confidently wrong. Where the rule is
mechanical, write the hook and its test in the same change.

---
[← 07 Hooks and guards](07-hooks.md) | [Table of contents](../../README.md) | [09 Harnesses and mirrors →](09-harnesses.md)
