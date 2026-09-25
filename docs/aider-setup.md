# aider-setup — the aider nightly local-coding pipeline

Index page. The `aider-setup` skill is a second, independent local-coding harness that needs
no Claude Code: two local Ollama models (a writer that codes and tests, a reviewer that never
edits, gated by measured token budgets) run one aider process per plan overnight, driven by
`aider-plan.ps1` / `aider-night.ps1`. See the root [README.md](../README.md) Skills table for
the one-line summary and [Architecture.md](../Architecture.md) for how it fits the rest of the
toolkit.

Its own docs live beside the skill, not here, so the code and its documentation stay one
commit apart (R18):

| Doc | Covers |
|---|---|
| [`.claude/skills/aider-setup/SKILL.md`](../.claude/skills/aider-setup/SKILL.md) | What the skill does, the three pieces and their lifetimes, the `scripts/build/` packaging pipeline for the student-facing `aider-kit.zip` |
| [`.claude/skills/aider-setup/MANUAL.md`](../.claude/skills/aider-setup/MANUAL.md) | The full runbook: install, build the kit, test the computer, tune Ollama and build the tag, create a project, write the three inputs, run a night, read the result, budgets, git during a run |
| [`.claude/skills/aider-setup/CONFIG_OLLAMA.md`](../.claude/skills/aider-setup/CONFIG_OLLAMA.md) | Measured Ollama tuning for THIS harness: the input-token floor, the GPU/context/thread test, `num_ctx`/`num_gpu`/`num_thread`, tuning the reviewer too |
| [`.claude/skills/aider-setup/EXAMPLE-PROMPT-robot.md`](../.claude/skills/aider-setup/EXAMPLE-PROMPT-robot.md) | A worked planning-prompt example (mobile robot path planner) for a first run |
| [`.claude/skills/aider-setup/MEMORY.md`](../.claude/skills/aider-setup/MEMORY.md) | Continuity notes for the next session working on this skill: where things live, traps, what is left undone |

Nightly entry point, once the machine is set up (no Claude Code involved):

```powershell
.claude\skills\aider-setup\scripts\aider-night.ps1
```
