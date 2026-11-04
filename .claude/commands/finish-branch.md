# Finish a branch

Use the `finish-branch` skill with `$ARGUMENTS` as the branch name (for example
`feat/my-change`). With no argument, ask which branch.

- If the branch's pull request is not merged yet, run Part 1 of the skill: regenerate the mirrors,
  then `scripts/test/run-all-checks.ps1`.
- If it is merged, run Part 2 of the skill: confirm the merge, check the main checkout, show the
  `finish-branch.ps1 -Branch <b> -Refresh` dry run, and add `-Yes` only when the owner asks.

The skill holds the procedure and the scripts hold the logic. This command adds none of its own.
