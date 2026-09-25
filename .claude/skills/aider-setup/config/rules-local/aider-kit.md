# Rules this kit adds

A local rules directory, read by `aider-rules-sync.py` alongside the canonical
one and merged into `rules.md`. A rule number defined in both places is a
refusal, not a merge, so nothing here can quietly override a rule from upstream.

This is also where a rule of your own goes. Write it as a bolded statement in the
same form, give it a number nobody else uses, and re-run the sync.

---

R27 used to be defined here (the function-header rule, "every function carries a
header a caller can act on"). It is empty on purpose since 2026-09-24: R27 landed
as a bolded statement in the canonical `.claude/rules/code-style.md` of the
repository this kit now ships from, and a rule number defined in both places is a
refusal, not a merge - see this file's own opening paragraph. Keeping a second
copy here would be exactly the drift a generated `rules.md` exists to prevent.
This file stays as the place a genuinely new, kit-only rule goes.
