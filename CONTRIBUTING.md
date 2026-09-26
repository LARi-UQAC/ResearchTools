# Contributing to ResearchTools

Thanks for looking at this before opening a pull request — it saves a review round-trip.

## Quick version

1. Fork the repository, work on a feature branch.
2. Follow the conventions in [docs/authoring-and-mirrors.md](docs/authoring-and-mirrors.md)
   when adding or editing an agent, skill, or command — it names the canonical source for
   each kind, the per-type doc-update checklist, and the mirror regeneration step.
3. Run `.\scripts\test\run-offline-tests.ps1` before opening the PR. It discovers every
   offline suite; a single failure, even in a skill you did not touch, means not finished.
4. Open a pull request against `main`. See [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)
   for the checklist the review expects.

Full detail (install scripts, junctions, mirror generation): [docs/manual/01-installation.md](docs/manual/01-installation.md#contributing-improvements).
Shared conventions (English-only definition files, agent/skill layout, local-model routing,
git/GitHub workflow): [docs/contributor-notes.md](docs/contributor-notes.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Where code belongs

Code written to fix or extend something in this toolkit lives inside the repository, at the
level of the skill, agent, or command that owns it — never as a one-off script in an unrelated
project directory. See `.claude/rules/workflows.md`, "Where code belongs", for the full rule
and its exemption test.

## No CI/CD

There is no automated pipeline. Run the relevant tests manually before pushing — see
[.claude/rules/testing.md](.claude/rules/testing.md) for the full offline-test inventory.
