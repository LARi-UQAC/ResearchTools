# Writing good tests

## One behaviour, one test

A test checks one thing and says it in its name: `test_total_is_refused_when_a_score_is_missing`, not
`test_total`. If the name needs the word "and", split the test.

## Check the result, not the machinery

- Assert on what the code returns or writes, with exact values.
- Do not assert that an inner function was called, unless the call is the behaviour.
- A fake stands in for something outside the code (a model, a network, the clock). It is never what the test
  checks.

## Cover the failure

For every function that can refuse or fail, write the test that makes it do so and check the error: its type
and the fact that its message names the cause.

## Real inputs

- Build inputs by hand in a temporary folder, with invented names and invented text.
- Include the awkward case the plan lists: the empty list, the accented text, the value at the limit, the
  value one past it.
- A boundary is tested on both sides.

## Stable and fast

- No test depends on the order of the other tests, on the date, on a random number or on a file that
  another test left behind.
- A test cleans up the folder it created.

## Test file layout

The test file is a program: it ends with `unittest.main()`, and it puts the parent folder of its own folder
at the start of `sys.path` before it imports the module it tests.
