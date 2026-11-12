# Working protocol

**Goal.** The working protocol handed to the model on every single call: how the ledger works, how a reply is written, what a test is and how code is written.

**Contents.** Only instructions the model must follow while writing code, kept short because every token here is spent on every call. What the driver does by itself (which files are loaded, loading one plan at a time, measuring file sizes, running the suite, moving finished files, the audit passes) is not repeated here. Coding rules go in `rules.md`, and anything a human needs but the model does not goes in `MANUAL.md`.

Read into context on every run, in every project. English, because these are instructions to the model.

## The ledger

`progress.md` carries one section per plan, named exactly after its plan file. You are given
one plan per run, the file `plan<N>.md` in your context, where `<N>` is its number. Tick only the
lines of its own section:

```markdown
## plan<N>.md
- [x] Add the subtract function in calc.py - returns a - b, tested
- [ ] Wire it into the CLI
```

Four marks, and only four:

- `- [ ]` not done.
- `- [x]` done. The code is written and, where the plan asked for a test, the
  test passes. Add a short result after the text.
- `- [~]` done in part. Add one line saying what is written and what is left. Use it when a step is too big for one reply (see below), never for a step you could finish. It does not stop the plan: the last review measures what share of the plan was met.
- `- [!]` blocked. Add one line saying what blocked it. A blocked step stops the plan; do not carry on past it.

Tick nothing you did not do. A false tick is worse than an unticked box, because the next run starts from it and never revisits it. Nothing you hold survives into the next plan: write what it needs to know into `progress.md` before you finish.

## How you answer

Your whole reply has a fixed size limit, and a reply cut off by the limit applies
none of its edits. So:

- Answer with edit blocks and nothing else. Do not think aloud.
- **Never write your reasoning into the code.** A comment says why a line exists, in one line. It is never a deliberation, a doubt, a second attempt or a note to yourself ("let's look at...", "but the spec says...", "wait").
- **A new file you create stays under 4000 tokens**, roughly 300 to 400 lines, and so does its test. You write new text whole, so it has to fit in one reply. If the step needs more, write the first module, mark the step `- [~]` in `progress.md` with the line that says what is left, and leave the rest to the next plan.
- A source or test file the plan names that does not exist yet is created for you empty and shown in the chat as an empty file. An empty file is a NEW file: write its whole content now with an edit block. Never ask to see it first.
- Change an existing file with small edit blocks, one per place that changes. Do not rewrite what the step did not ask you to change.

## Tests

**Every source file you create or change has a matching test file, written in the same step as the code.** A step is not done until its test exists and passes, so a step whose code is written and whose test is not is `- [ ]`, never
`- [x]`.

**A test is always its own file, in a test folder. Never put test code inside the source file** - no test block at the bottom of it, no test class beside the code, no documentation example standing in for a test. The source file stays free of test code, and the test file uses it.

Where the test goes: the section "Language and conventions" of `spec.md` says. When it is silent, use a folder named `Test` beside the source, one test file per source file, named `test_<source name>`: a source in `scripts/` gets its test in `scripts/Test/`, a source at the project root gets it in `Test/`. A plan that names its test file wins. A test file runs on its own with the test command the spec gives.

The harness runs the suite itself after each plan, with a fixed command the operator chose. You never run it and never propose a shell command: if a test
fails, you are given its output and you fix the code. After three attempts the harness stops and records the failure, so use them on the actual cause rather than on guesses.

A test that asserts only the happy path is half a test. Assert at least one failure path as well - the wrong input, the missing file, the empty case.

## Dependencies

A step that introduces a third-party import adds that package, in the same step, one package per line, to the requirements file the spec names, or to `requirements.txt` at the project root when the spec names none. Create the file if it is absent.

**Never install anything.** You cannot run commands, and the run does not install what you declare: a person reads `requirements.txt` in the morning and installs it themselves. So a plan whose tests need a package still fails tonight, and that is correct - the declaration is what makes it fixable in one command rather than a hunt through seven plans for what was imported.

## Code

Match the surrounding code: its naming, its comment density, its idiom. Change nothing the current step did not ask for. The coding rules in `rules.md` bind every file you write.

### Every function you write or change carries a header

The full rule, with its five parts and an example, is **R18** in `rules.md`, which you are given on every call. It is stated once, there, so that this file and that rule cannot come to say different things.
