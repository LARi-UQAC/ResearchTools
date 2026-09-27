---
name: opt-local-stt-vram
description: "Benchmark speech-to-text models (Whisper, faster-whisper) for this GPU beside the resident local LLM, all on VRAM, and print a scored table to pick the best one: transcript error against your own reference words, live-caption speed, and how much VRAM each takes and pushes the LLM out of. Downloads the named models, measures each in a fresh process, gates out any model that demotes too much of the LLM, and stops before adoption. Trigger on: /opt-local-stt-vram, 'which speech-to-text model fits my GPU', 'compare whisper models', 'benchmark STT beside the LLM', 'test a new voice-to-text model for the voice panel', 'quel modele de reconnaissance vocale'."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [read]
---

# opt-local-stt-vram - measured speech-to-text selection for this GPU

The sibling of `opt-local-vram-llm`, for the voice panel's speech-to-text engine. You name the
models; it downloads them, measures each one BESIDE the resident local LLM (the way the voice
panel actually runs: everything on VRAM), scores them, and prints one table to choose from.
Every figure is measured on this card. It never adopts: switching the panel's model stays a
human edit, printed at the end, the same stop `tune-new-model.ps1` makes before `--qualify`.

## What it measures, and why each measure is the one it is

Built from the comparison of 2026-09-26, whose traps are now the design:

| Measure | How | Why this way |
|---|---|---|
| Transcript error | word error rate (and character error rate) against YOUR reference words, with each wrong word named | Devoir2's constants were Whisper small's own output; scoring against a model's output rigs the result for that model |
| Speed | median of `runs_per_file` transcriptions per recording, the longest recording judged against `live_budget_ms` | the panel re-transcribes the growing buffer once per live refresh; under the budget the caption keeps up, and faster than that is invisible to the speaker |
| VRAM | per-process `GPU Process Memory` counters, dedicated and shared | under WDDM `nvidia-smi` gives a card total that cannot say whose memory it is |
| LLM pushed out | the LLM's own dedicated VRAM before and after the candidate transcribes | a bigger model does not spill itself; Windows demotes part of the LLM instead (large-v3 pushed 1.3 GB of it out) |
| LLM answer after | one timed LLM answer after the transcriptions | what paging the LLM back in costs the "thinking" stage |

Each candidate runs in its OWN child process: measured in one process, a candidate inherits
the previous model's reserved CUDA memory and reads too low. Download time and the first call
(which pays CUDA initialisation) are recorded apart and never mixed into the latency.

## The score

1. **Gate.** A candidate that pushes more than `gate.max_llm_demoted_pct` of the LLM out of
   VRAM is listed as `gated`, with its figures, and gets no score.
2. **Accuracy** = 100 - word error %.
3. **Speed** = 100 when the longest recording transcribes within `live_budget_ms`, otherwise
   100 x budget / time.
4. **Score** = `weights.accuracy` x Accuracy + `weights.speed` x Speed (the weights sum to 1).

A candidate that fails to download, load or run is `not runnable` with its reason, never a
score. Another process holding more than `other_process_warn_mib` of VRAM (a dashboard left
open with its own Whisper, for instance) is named on screen and in the report, since every
candidate would be measured beside it.

## Running it

```bash
.venv-skills/Scripts/python.exe .claude/skills/opt-local-stt-vram/scripts/stt_bench.py \
    --reference <folder>/reference.txt --language fr --out <report-dir> [--dry-run]
```

- `--reference`: one `audio-file | exact words` line per recording, `#` for comments. The audio
  files sit in the same folder as the reference file; a path leaving that folder is refused.
- `--model NAME:COMPUTE`, repeatable: any faster-whisper size or Hugging Face CTranslate2 repo
  id with its compute type (`large-v3-turbo:int8_float16`). None given means the four defaults
  in `stt-bench-config.json`, the models measured on 2026-09-26.
- `--engine`: `faster-whisper` (default). `nemo` is declared and refuses, see below.
- `--dry-run`: names the engine, the LLM and its process, every candidate and recording, and
  the files it would write; downloads, measures and writes nothing.
- `--rescore <out>/stt_bench_raw.json`: recompute the score and table from a saved run, for
  instance after correcting a word in the reference, without running any model.
- `--json`: print the report instead of the table.

Close the voice dashboard first: it holds its own Whisper in VRAM. Run it with the
`.venv-skills` interpreter, which carries faster-whisper and its CUDA runtime
(`rt-observe/scripts/requirements-voice*.txt`). Exit codes: 0 report written, 2 refusal
(no reference, missing audio, engine not installed, no qualified writer-role model, Ollama
down), 1 failure.

Outputs in `--out`: `stt_bench_raw.json` (measurements), `stt_bench_report.json` (scores,
winner, the rule used), `stt_bench_table.md` (the selection table).

## Adopting the winner

A human edit, never done by this skill: in `.claude/skills/rt-observe/observe-config.json` set
`voice.stt.model_size` and `voice.stt.compute_type` to the winner, update their provenance with
the run's figures, then restart the dashboard. `test_voice_config.py` pins the adopted model, so
the same commit updates its expected value.

## Files

- `stt-bench-config.json` - defaults, gate, weights, budget, timeouts, engine registry; every
  number with provenance (R4). `live_budget_ms` and the `transcribe` options must equal
  rt-observe's `voice.partial_refresh_ms` and `voice.stt.*`, asserted by test.
- `scripts/stt_bench.py` - the CLI and orchestration (one child per candidate)
- `scripts/stt_score.py` - pure scoring and the table
- `scripts/gpu_memory.py` - per-process GPU memory, the LLM's process, other GPU processes
- `scripts/bench_config.py` - config reader, a missing key named (R3)
- `scripts/engines/` - one adapter per engine: `faster_whisper_engine.py`, `nemo_engine.py`
- `scripts/Test/` - four offline suites, no model, no GPU, no Ollama; the scorer's regression
  fixture replays the real measurements of 2026-09-26

## Known limitations

- **NeMo is a seam, not an engine.** `nemo_engine.py` is declared so NVIDIA models
  (Canary-Qwen 2.5B, parakeet) can be added on a machine whose GPU can hold them beside the
  LLM; today it refuses with that reason. Implementing it means adding `nemo_toolkit` and
  PyTorch to a pinned, pip-audited requirement file and filling in its three functions.
- **Small reference sample.** Three recordings and 40 reference words made one word worth
  2.5% of word error on 2026-09-26. Add recordings to the reference for a finer ranking.
- **The gate sits close to one candidate.** large-v3-turbo measured 7.2% and then 9.6% of the
  LLM pushed out in two runs the same day, against a 10% gate: that share depends on how much
  of the LLM was resident when the candidate loaded.
- **Windows-measured.** The per-process counters are Windows (WDDM) counters. The
  `nvidia-smi --query-compute-apps` path used elsewhere is proven by the offline suite only.
- **Speech-to-text only.** TTS candidates (F5-TTS, chatterbox) from plan3 are not covered.
