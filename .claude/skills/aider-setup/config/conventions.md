# Working protocol

**Goal.** The working protocol handed to the model on every single call: how the ledger works, how one plan at a time is executed, what size each file may reach, and what a function's header must contain.

**Contents.** Only instructions the model must follow while writing code, kept short because every token here is spent on every call - coding rules go in `rules.md`, and anything a human needs but the model does not goes in `MANUAL.md`.

Read into context on every run, in every project. English, because these are
instructions to the model. Written 2026-09-02.

## Where the files live

Everything below sits in `docs/superpowers/plans/` of the project:

| File | Role | Who writes it |
|---|---|---|
| `spec.md` | What is being built and why. The stable reference. | The human. Read-only for you. |
| `plan1.md`, `plan2.md`, ... | One numbered plan per stage, an ordered list of steps. | The human. Read-only for you. |
| `progress.md` | The ledger. One `## <filename>` section per file above, each holding that file's checkboxes. | You. |
| `audit.md` | Problems found in the finished code. Written in the audit pass, never before. | You, in the audit pass only. |

A completed file moves to `docs/superpowers/plans/todo/`. The harness moves it,
not you: never move, rename or delete any of these files yourself.

## The ledger

`progress.md` carries one section per plan, named exactly after the file:

```markdown
## plan1.md
- [x] Add the subtract function in calc.py - returns a - b, tested
- [ ] Wire it into the CLI
```

Three marks, and only three:

- `- [ ]` not done.
- `- [x]` done. The code is written and, where the plan asked for a test, the
  test passes. Add a short result after the text.
- `- [!]` blocked. Add one line saying what blocked it. A blocked step stops the
  plan; do not carry on past it.

Tick nothing you did not do. A false tick is worse than an unticked box, because
the next run starts from it and never revisits it.

## One plan at a time

Work only on the plan file present in your context. Never read ahead to the next
plan, never act on a step belonging to another one.

The context window is dropped between plans, because each plan runs in a new
process. Nothing you hold now survives into the next plan. Whatever the next plan
needs to know must be written into `progress.md` before you finish.

When every step of the current plan is ticked or blocked, say so and stop.

## Size ceilings

Every one of these is a token count, not a line count. The harness measures each
file before every run and reports the ones over budget.

| File | Max tokens | Why that figure |
|---|---:|---|
| a NEW file you create | **4000** | you write it whole in one reply, so it has to fit in one reply |
| a NEW test file you create | **4000** | same reason: it is new text, not a diff |
| an existing file you edit | **16000** | you send a diff, not the file, so reading a large file is cheap |
| `progress.md` | **2048** | a list of tasks pointing at the plans, nothing more |
| `audit.md` | **4096** | you append to it per batch, so this bounds one batch of findings |
| `spec.md` | **4000** | written once, re-read on every call |
| each `plan<N>.md` | **4000** | only one is ever loaded at a time |
| `rules.md` | **3500** | generated, not written by hand |
| `conventions.md` | **2500** | this file |

Three rules follow from those numbers.

- **A new file you create stays under 4000 tokens**, roughly 300 to 400 lines,
  and so does its test. You write new text whole, so it has to fit in one reply,
  and a reply that size already takes about a quarter of an hour here. If the
  step needs more, write the first module, say so in `progress.md`, and leave
  the rest to the next plan.
- **An existing file over 16000 tokens is split** along a seam that already
  exists in the code, one module per responsibility, never at an arbitrary line
  count. Say in `progress.md` which file you split and where the seam was.
- **A plan touches at most ten files.** Not because any single ceiling forbids
  more, but because ten files at 16000 tokens is already everything the window
  has left once the fixed cost and the protocol files are paid for. A plan that
  needs more than ten files is two plans, and saying so in `progress.md` is the
  right answer rather than pressing on.

When `progress.md` approaches its ceiling, compress the sections of finished
plans to one summary line each and leave the current plan's detail intact.

## The audit pass

When the last plan is done, one more pass runs, and it is not a coding pass.

- Every source file is handed to you **read-only**. You cannot edit them, and
  that is deliberate.
- You write `audit.md`: a numbered list of problems found, each with the file
  and line, what is wrong, and why it matters. Order them worst first.
- Check at least: values hard-coded where configuration belongs, silent
  fallbacks, missing error paths, a return code trusted where the effect should
  have been verified, a file over the 16000-token ceiling, and anything the
  `spec.md` asked for that no plan delivered.
- Propose no rewrite and apply no fix. The list is for a person to act on.
- If you find nothing, say so in one line rather than padding the list.

## Tests

**Every source file you create or change has a matching test file, written in
the same step as the code.** A step is not done until its test exists and
passes, so a step whose code is written and whose test is not is `- [ ]`, never
`- [x]`.

Where the test goes, first form that fits the project:

| Source file | Test file |
|---|---|
| `calc.py` | `tests/test_calc.py` |
| `src/parser.py` | `src/tests/test_parser.py`, else `tests/test_parser.py` |

The harness runs the suite itself after each plan, with a fixed command the
operator chose. You never run it and never propose a shell command: if a test
fails, you are given its output and you fix the code. After three attempts the
harness stops and records the failure, so use them on the actual cause rather
than on guesses.

A test that asserts only the happy path is half a test. Assert at least one
failure path as well - the wrong input, the missing file, the empty case.

## Dependencies

A step that introduces a third-party import adds that package to
`requirements.txt` at the project root, in the same step, one package per
line. Create the file if it is absent.

**Never install anything.** You cannot run commands, and the run does not
install what you declare: a person reads `requirements.txt` in the morning and
installs it themselves. So a plan whose tests need a package still fails
tonight, and that is correct - the declaration is what makes it fixable in one
command rather than a hunt through seven plans for what was imported.

## Code

Match the surrounding code: its naming, its comment density, its idiom. Change
nothing the current step did not ask for. The coding rules in `rules.md` bind
every file you write.

### Every function you write or change carries a header

The full rule, with its five parts and an example, is **R27** in `rules.md`,
which you are given on every call. It is stated once, there, so that this file
and that rule cannot come to say different things.

