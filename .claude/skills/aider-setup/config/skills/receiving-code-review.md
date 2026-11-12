# How to act on a review report

A reviewer read your code and listed problems. You fix what is wrong. Nobody answers questions during a run,
so you never stop to ask: you decide, you act, and you say what you decided.

## For each entry of the report

1. **Read it whole** before touching a file. Entries can be related, and a fix for one may remove another.
2. **Check it against the code.** Open the line the entry names. Is the problem real, or did the reviewer
   misread the code?
3. **If it is real**, fix it with the smallest change that removes the cause, and add or adjust a test that
   fails before the fix and passes after it.
4. **If it is not real**, change nothing and write one line in the progress file saying why the entry does
   not apply, with the line of the code that shows it.
5. **If it is unclear**, do the most reasonable reading, and say in the progress file which reading you took.

## Rules

- One entry at a time. After each fix, read the tests that touch the changed code. A fix that would break a
  test that passed is not made that way: find another way. The harness runs the tests after your reply.
- Fix the most serious entries first. Do not stop at the first one.
- Do not add anything the report did not ask for: no new feature, no clean-up of code the report did not
  mention, no rewrite "while you are there".
- Do not praise the report or agree out loud. State what you changed, in the progress file, in one line per
  entry.
- A suggestion that would break the plan the code follows is not applied. The plan wins, and you say so in
  one line.
- Never end your turn with a question, a request for permission or an offer to do more.
