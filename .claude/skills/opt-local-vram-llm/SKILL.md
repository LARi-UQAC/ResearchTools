---
name: opt-local-vram-llm
description: "Tune a local Ollama model for this machine's GPU: retain the largest context window that keeps the model 100 percent resident in VRAM, among configurations whose decode throughput clears a floor. Builds the tuned -gpu tag from a base tag, sweeps num_ctx against OLLAMA_KV_CACHE_TYPE (restarting the daemon between axis values and proving it took them), writes the measurement, and declares the tag as a candidate for its role. Trigger on: /opt-local-vram-llm, 'optimize the local model for my VRAM', 'tune the context window', 'a new model shipped, re-tune local-writer or local-coder', 'how much context fits on my GPU', 'combien de contexte tient dans ma VRAM'."
allowed-tools: [Read, Write, Edit, Bash]
permissions: [read]
---

# opt-local-vram-llm - measured VRAM tuning for the local agents

Replaces six manual steps with one command when a newer model arrives for `local-writer` or
`local-coder`: read the manifest, write a Modelfile, create the tag, sweep, declare the
candidate, qualify. Every number it writes is measured on this card; none is copied from a
model card or inferred from a parameter count.

## What it optimizes

**The largest context window that keeps the model fully resident in VRAM, among the
configurations whose decode throughput clears a floor.** Three rules, in order:

1. **Admissible.** `size_vram / size >= 0.999` from `/api/ps` on every run, at least 300 MiB
   still free on the card, and the rung not clamped by the model's own context maximum. A
   spill is refused however fast it measured, because that speed stops being reproducible the
   moment anything else touches the card.
2. **Fast enough.** Decode throughput at least `--throughput-floor` (default 0.90) of the best
   throughput observed among the ADMISSIBLE configurations. An inadmissible configuration
   never gets a vote on what counts as fast.
3. **Largest window wins.** Ties break on throughput.

The report names every dropped configuration and which rule dropped it, so a surprising
result is auditable rather than merely announced.

Throughput here means `eval_count / eval_duration` from the daemon's own response, not
elapsed wall-clock time. The two are not interchangeable: measured on this machine on
2026-08-27, a writer model took 36.991 s and a coder model 4.918 s on the same prompt for
decode rates of 27.3 and 30.1 tokens per second. The gap was output length, not speed.
Ranking on elapsed time compares verbosity.

## The two axes

`num_ctx` climbs the existing ladder, stopping at the model's native maximum. Ollama does not
error above that maximum, it clamps silently, so the clamped rung would otherwise measure
identically to the honest one and be retained as a window the daemon never grants.

`kv_cache_type` tries `f16`, `q8_0`, `q4_0`. This one is a daemon-wide environment variable
read only at daemon start, so **each value costs a restart of Ollama**, which evicts the
resident model. The tool writes the variable, restarts through `scripts/dev/restart-ollama.ps1`
(which kills the `llama-server.exe` child a naive pattern misses), then reads `server.log` to
prove the daemon actually took the value before measuring anything.

On success the daemon is left on the retained value. On failure or interruption it is put back
on the value found at startup: the machine is never left on an axis value chosen by a search
that failed.

`num_gpu` is not an axis. It is pinned at 99, since anything less breaks rule 1 by
construction. An untuned base measured 79 percent GPU at 16384 despite its weights fitting the
card, because what Ollama held back was layer offload rather than KV cache.

## Contract

```
/opt-local-vram-llm <base-tag> --role <writer|coder>
                    [--throughput-floor 0.90] [--kv f16,q8_0,q4_0]
                    [--keep-vision] [--dry-run]
```

`--dry-run` probes and prints the Modelfile it would write, touching neither Ollama nor the
daemon. `--keep-vision` keeps a separate projector layer that would otherwise be dropped: the
bridge is text-only, so a projector buys nothing and costs its size in VRAM. Whether a model
even has a separate projector is read from its manifest, not assumed.

## Modules

| Script | Responsibility |
|---|---|
| `scripts/vram_probe.py` | Read-only facts: manifest layers, native context maximum, daemon settings from `server.log`. Changes nothing. |
| `scripts/vram_modelfile.py` | Render the tuned Modelfile. Pure function; opens no file. |
| `scripts/vram_daemon.py` | The KV cache axis: write, restart, verify, restore. |
| `scripts/vram_optimizer.py` | The driver: search, objective function, report, declaration. |

The rung measurement itself is `optimize_ollama.evaluate_rung`, imported from the
`loop-engineer` skill rather than copied. Two implementations of "measure a rung" would drift,
and the drift would stay invisible until they disagreed about a model.

## Where it stops

At declaration. It writes `local-model-config.json`, declares the tag in `local-models.json`
as a candidate for the role, prints the `model_resolver.py --qualify` command, and stops.

**It never adopts a model.** Qualification grades code quality against a frozen task set; this
tool measures memory and speed. Different criterion, different oracle, and adopting a tag
changes what the local agents execute.

## Expected failure

A model whose weights nearly fill the card retains nothing, at any rung of any axis value.
That is a correct answer about this card, reported with the numbers behind it, not an error to
work around. A model whose weights alone exceed the card is refused before anything is built.

## Tests

Four offline suites under `scripts/Test/`, no network, no GPU, no Ollama daemon:
`test_vram_probe.py` (11), `test_vram_modelfile.py` (11), `test_vram_daemon.py` (5),
`test_vram_optimizer.py` (13). Forty in total.
