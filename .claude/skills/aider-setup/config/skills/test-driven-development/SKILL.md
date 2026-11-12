# Writing code test first

A test written before the code shows that the code does the job. A test written after it only shows what the
code already does.

## The order

1. **Write the test.** It names one behaviour and checks it with a real call to the code. Use the exact
   values of the plan.
2. **Make sure it fails for the right reason.** Before the code exists, it fails because the function is
   missing or gives the wrong result, not because of a typing mistake in the test.
3. **Write the least code that makes it pass.** Nothing for a case no test names.
4. **Run the whole test file.** Every test must pass, the old ones as well.
5. **Clean up** the names and the repeated code, then run the tests again.

Repeat for the next behaviour. When a plan gives you the module and its tests in one step, you still write
the tests first in your reply: the test file comes before the module in the order of the files.

## Rules

- No code for a behaviour without a test that names it.
- A bug is fixed by a test that fails because of the bug, then by the fix.
- A test that passes at once proves nothing. Make it fail by hand, once, to be sure it can.
- Every function that can fail has a test of its failure: the bad input, the missing file, the refused case.
- A test never reaches outside the test: no network, no real model, no file outside a temporary folder.

When you write or change a test, read `writing-good-tests.md`.

## Signs you went wrong

- The code was written first and a test was added after.
- A test passes the first time it runs.
- A test only checks that a function was called.
- The tests cannot say what breaks when they fail.

Start the step again from the test.
