## What changed and why

<!-- One or two sentences. -->

Closes #<!-- issue number (R30 — every PR needs a linked Issue with a card on
https://github.com/users/LARi-UQAC/projects/6, except a pure doc fix with no behavioral
change) -->

## Checklist

- [ ] Linked Issue has a card on the [ResearchTools Roadmap](https://github.com/users/LARi-UQAC/projects/6) board (R30)
- [ ] Ran `.\scripts\test\run-offline-tests.ps1` — full pass (or explains a pre-existing
      unrelated failure)
- [ ] If a script's CLI surface changed (new flag, renamed subcommand, changed default):
      updated its line in `.claude/rules/testing.md` (R23)
- [ ] If an agent, skill, or command was added or edited: followed
      [docs/authoring-and-mirrors.md](../docs/authoring-and-mirrors.md) and ran
      `.\install.ps1` (commit the regenerated mirrors alongside the canonical change)
- [ ] If a new script was added: it lives beside its only caller or in the shared
      repo-wide home for its kind (R18), with an offline test under `Test/`
- [ ] Docs updated for whatever this PR touched (`README.md` / `docs/manual/*.md` /
      `Architecture.md` / the relevant `.claude/rules/*.md`) and links verified to resolve —
      this PR does not merge without it (R31)
- [ ] No hardcoded path, numeric value, or model tag introduced (R0 / R1 / R2)

## Notes for the reviewer

<!-- Anything that needs a second look, or a design tradeoff worth flagging. -->
