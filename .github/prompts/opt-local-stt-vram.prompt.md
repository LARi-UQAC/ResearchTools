---
description: "Choose a speech-to-text model for this GPU"
---

Thin wrapper over the `opt-local-stt-vram` skill. Read
`.claude/skills/opt-local-stt-vram/SKILL.md` first, then follow it exactly.

Option contract:

```
/opt-local-stt-vram --reference <folder>/reference.txt --out <dir>
                    [--model NAME:COMPUTE ...] [--language auto|en|fr]
                    [--engine faster-whisper] [--dry-run] [--rescore RAW_JSON] [--json]
```

Procedure:

1. Parse `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`. `--reference` is required; refuse to start without it, and say that it
   must hold the operator's OWN words for each recording, never a model's transcript.
2. Ask the operator to close the voice dashboard before a real run: it keeps its own Whisper in
   VRAM and every candidate would be measured beside it. Suggest `--dry-run` first.
3. Run the driver with the `.venv-skills` interpreter:

   ```bash
   .venv-skills/Scripts/python.exe .claude/skills/opt-local-stt-vram/scripts/stt_bench.py <args>
   ```

4. Report the table as printed, the winner, and every `gated` or `not runnable` row with its
   reason. If a WARNING named another GPU process, say that the figures include it.
5. Print the two `observe-config.json` keys to edit for the winner and stop. Never edit them:
   adopting a model changes what the voice panel runs, and that is the operator's call.

