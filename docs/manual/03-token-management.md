# Token Management

Chapter 03 of the ResearchTools manual. Back to [table of contents](../../README.md).

Use these tools together to keep sessions fast and cheap.

## Output modes

| Mode | Command | Max length | Formatting |
| --- | --- | --- | --- |
| Normal | *(none)* | Unlimited | Full — headers, tables, bullets |
| Concise | `/concis` | 5 sentences | Structured bullets allowed |
| Slim | `/slim` | 2 sentences | Code blocks only, no prose |

## Recommended workflow

1. **Start** every session with `/slim` (quick tasks) or `/concis` (exploratory work)
2. **Scope** context with `/focus <topic>` to avoid loading irrelevant files
3. **Monitor** with `/ctx` when responses feel slow — it reports context pressure in under 10 lines
4. **Compress** with `/compact` when `/ctx` reports moderate or high pressure

> `/compact` is destructive — conversation history is summarized and cannot be restored. Always run `/ctx` first to confirm it is needed.

## Running the whole session on a local model (optional)

The output modes above shrink what the cloud model reads and writes. Switching the session
itself to a local model goes further — no cloud generation tokens at all for that session — at
a real speed tradeoff (a CPU/RAM-bound model can run at a few tokens per second).

`scripts/local/claude-switch.ps1` dot-sources two functions. Load it once per shell:

```powershell
. .\scripts\local\claude-switch.ps1
```

| Command | Effect |
| --- | --- |
| `claude-local` (alias of `claude-ollama`, optional `-Model <tag>` and `-SessionName <name>`) | Points Claude Code straight at a local Ollama model — Ollama's own Anthropic-API compatibility since 2026-01-16, no proxy needed. With no `-Model`, resolves the default through `model_resolver.py` (the same resolver local-writer/local-coder use), never a hardcoded tag. Refuses to switch, and never launches Claude Code, if Ollama isn't reachable or the requested model isn't actually installed |
| `claude-cloud` (optional `-SessionName <name>`) | Clears the local redirection, restores whatever `ANTHROPIC_API_KEY` was set before switching local, and returns to Anthropic |

`-SessionName` just labels the terminal window title (`[LOCAL]`/`[CLOUD] <name>`) so several
parallel Claude Code sessions in different windows stay distinguishable — it has no effect on
routing.

Measure before switching — a local model is not plug-and-play. A tag that fits in VRAM is tuned
by the `opt-local-vram-llm` skill (`/opt-local-vram-llm`); one too large for the GPU and running
on CPU/RAM is measured instead with `aider-thread-probe.py --mode sweep`, which reads real decode
speed, CPU load, and page-in rate off the machine rather than guessing. The measured tag is then
registered as the script's default with `model_resolver.py --adopt-role session <tag> --reason
"..."`. Full three-step process and a worked example in `.claude/rules/workflows.md`, "Switching
the Claude Code session itself to a local model".

## Quick reference

| Command | When to use |
| --- | --- |
| `/slim` | Fast edits, one-liners, quick questions |
| `/concis` | Code reviews, multi-step explanations |
| `/focus <topic>` | Long sessions touching many files |
| `/ctx` | When the session feels sluggish or heavy |
| `/compact` | After `/ctx` reports moderate/high pressure |

---
[← 02 Profiles & environment](02-profiles.md) | [Table of contents](../../README.md) | [04 Skills →](04-skills.md)
