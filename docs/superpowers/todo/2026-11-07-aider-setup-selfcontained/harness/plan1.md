# Plan 1 - the checks

**Goal.** `scripts/live_checks.py` judges a finished kit project against an expectation and the text the kit printed.

**Contents.** Numbered steps, each naming its file. Done means the tests pass and assert a failure path.

1. **Create `scripts/live_checks.py`.** Standard library only, pure functions, no printing, no test code. Every
   function carries a header with purpose, inputs and outputs.

2. **Add `check_project(project_dir, expect, log_text, baseline, git_timeout_s) -> list`.** It returns one text per
   failed check and runs every check even after a failure. It holds no number and reads no file of configuration:
   the time limit of every git call is the parameter `git_timeout_s`. Nothing is silently skipped (R8): a file that
   cannot be read, a git call that fails or times out, and a missing baseline each become a failure text. The checks,
   in order:
   - each expected module exists;
   - each expected test file exists, and the folder that holds it is named exactly `Test` (a folder named
     `tests` or `test` is a failure that says so);
   - no expected module contains test code: the words `unittest`, `def test_` or `__main__` inside a module is a
     failure naming the file and the word;
   - in `progress.md`, no task line of any expected plan is still open (`- [ ]`) or blocked (`- [!]`);
   - each expected plan file was archived into the `todo` folder of the plans folder;
   - the kit printed an audit line (`audit by`) and ended it clean (`audit clean`);
   - the project's git history has at least one commit after the baseline commit: ask git for the count of commits
     between `baseline` and the head, and a count of zero is a failure.

3. **Add `describe(failures) -> str`** that turns the list into a short readable report, one line per failure, or
   the single line `all checks passed`.

4. **Write `scripts/Test/test_live_checks.py`**, a `unittest` file that ends with `unittest.main()` and puts the
   parent folder of its own folder at the start of `sys.path` before importing the module. Build small throwaway
   projects in a temporary folder. Cover: a good project giving an empty list; a test file inside a folder named
   `tests` failing; test code inside a module failing; an open task line failing; an unarchived plan failing; a log
   with no audit line failing; several faults at once all reported in one call; the failure path of a missing
   progress file, reported as a failure rather than raised; and the git check on a real throwaway repository: a commit
   made after the baseline passes, no commit after it fails with a message naming the baseline, and an unknown baseline
   hash fails rather than passing.

**Done when** `scripts/Test/test_live_checks.py` passes.
