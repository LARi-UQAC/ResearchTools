# Writing code test first

A test written before the code shows that the code does the job. A test written after it only shows what the
code already does.

You never run anything: the harness runs the tests after your reply and shows you the failures. Your part is
the order in which you write.

## The order

1. **Write the test file first.** In your reply, the test file comes before the module. Each test names one
   behaviour and checks it with a real call to the code. Use the exact values of the plan.
2. **Write the test so that it fails now.** Before the code exists it must fail because the function is
   missing or gives the wrong result, not because of a typing mistake in the test. Read it once as if you
   were the harness: what would it print?
3. **Write the least code that makes the tests pass.** Nothing for a case no test names.
4. **Check every old test by reading.** A change must not break a test that passed.
5. **Clean up** the names and the repeated code without changing what the tests check.

Repeat for the next behaviour. When a plan gives you the module and its tests in one step, you still write
the tests first.

## Rules

- No code for a behaviour without a test that names it.
- A bug is fixed by a test that fails because of the bug, then by the fix.
- A test that could not fail proves nothing. Check that a wrong result would make it fail.
- Every function that can fail has a test of its failure: the bad input, the missing file, the refused case.
- A test never reaches outside the test: no network, no real model, no file outside a temporary folder.

When you write or change a test, read `writing-good-tests.md`.

## Signs you went wrong

- The code was written first and a test was added after.
- A test would pass whatever the code does.
- A test only checks that a function was called.
- The tests cannot say what breaks when they fail.

Start the step again from the test.
