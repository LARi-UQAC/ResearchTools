---
description: "Tune a local Ollama model for this GPU"
---

Thin wrapper over the `opt-local-vram-llm` skill. Read
`.claude/skills/opt-local-vram-llm/SKILL.md` first, then follow it exactly.

Option contract:

```
/opt-local-vram-llm <base-tag> --role <writer|coder>
                    [--throughput-floor 0.90] [--kv f16,q8_0,q4_0]
                    [--keep-vision] [--dry-run]
```

Procedure:

1. Parse `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`. The base tag and `--role` are both required; refuse to start without
   either, naming which one is missing. Do not infer a role from the tag's name.
2. Warn the user, before running anything, that the sweep restarts the Ollama daemon once per
   KV cache type and evicts the resident model for the duration. Suggest `--dry-run` first if
   a local agent is running.
3. Run the driver:

   ```bash
   python .claude/skills/opt-local-vram-llm/scripts/vram_optimizer.py <base-tag> --role <role>
   ```

4. Report the retained `num_ctx`, `kv_cache_type`, `decode_tps` and free VRAM, plus the
   configurations that were dropped and the rule that dropped each. If nothing was admissible,
   say so plainly with the numbers: that is a real answer about this card, not a tool failure.
5. Print the `model_resolver.py --qualify` command and stop. Never run it. Adopting a model
   changes what the local agents execute, and that is the user's call.

