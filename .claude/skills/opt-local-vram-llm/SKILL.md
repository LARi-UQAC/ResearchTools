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
3. **Largest EFFECTIVE window wins.** Ties break on cache fidelity first, throughput
   second.

Effective, not raw, and this is the rule that changed on 2026-08-28. A quantised KV cache
makes the cache smaller, so it buys context for nothing in VRAM terms while degrading what
the model recalls from that context. Ranking on the raw token count therefore handed the win
to the cheapest cache on every model with room to grow, and reported the outcome as a bigger
window rather than as the trade it was. The window is now divided by
`--fidelity-exchange-rate` (default 2.0) for each step below `f16` on the declared ladder
`f16 > q8_0 > q4_0`, so `q8_0` must double the window to be preferred and `q4_0` must
quadruple it. `--fidelity-exchange-rate 1.0` restores the raw ranking and treats a quantised
cache as free, which is the honest way to ask for that behaviour rather than getting it by
default. The ordering itself is declared, not measured: throughput and VRAM say nothing
about recall quality, and the frozen task set is the resolver's oracle, not this tool's.

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
resident model. The tool writes the variable, restarts through `scripts/restart-ollama.ps1`
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
                    [--throughput-floor 0.90] [--fidelity-exchange-rate 2.0]
                    [--kv f16,q8_0,q4_0] [--keep-vision] [--dry-run]
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
| `scripts/restart-ollama.ps1` | The restart itself: kills the daemon AND its `llama-server.exe` child, re-reads the user environment so the relaunched daemon sees the value just written, verifies the card released its memory. |
| `scripts/vram_optimizer.py` | The driver: search, objective function, report, declaration. Owns the tuned tag's NAME (`tuned_tag_for`), so nothing else spells the suffix. |
| `scripts/tune_preflight.py` | The refusals and the comparison behind the runbook below: what stops a run before it starts, and how the measured field is put to the person who has to choose. Adopts nothing. |
| `scripts/tune-new-model.ps1` | The runbook itself, steps 1 to 3 plus the comparison. Sequencing only; everything that decides lives in `tune_preflight.py`, where the offline suite reaches it. |

The rung measurement itself is `optimize_ollama.evaluate_rung`, imported from the
`loop-engineer` skill rather than copied. Two implementations of "measure a rung" would drift,
and the drift would stay invisible until they disagreed about a model.

## From "it is on disk" to "the resolver serves it"

Five steps, and only the first is this skill's own. They were written down because the pieces
all existed and were tested while the SEQUENCE lived nowhere, so a new model got tuned and
then either adopted without being compared or left declared and forgotten.

1. **Tune it for this card.**
   `python .claude\skills\opt-local-vram-llm\scripts\vram_optimizer.py <base-tag> --role <writer|coder>`
   (`--dry-run` first). Sweeps the two axes, writes the measurement, declares the tuned tag as
   a candidate. Stops before qualification on purpose.
2. **Measure it against the frozen task set, writing nothing.**
   `python .claude\skills\loop-engineer\scripts\model_resolver.py --score <TUNED-TAG> --role <role> --json`
3. **Compare it against every other candidate.**
   `model_resolver.py --matrix` scores every declared and installed candidate on every task,
   including roles a candidate is not declared for. That exists because a candidate scored
   only on its own role is not comparable: an 18/20 tag once held the coder role while a 20/20
   tag sat unscored on coder tasks.
4. **Adopt it, or do not.** `model_resolver.py --qualify <TUNED-TAG> --role <role>` is the only
   step that changes which tag is current. It is a decision, so it stays a command a human
   runs.
5. **Confirm what is now served.** `model_resolver.py --resolve --role <role>`.

`scripts/tune-new-model.ps1 <base-tag> -Role <writer|coder>` is the harness for steps 1 to 3
plus the comparison, and it **stops before step 4**. It refuses up front rather than half way
(no such tag installed, a tag that is already tuned, Ollama unreachable, and after the sweep,
a tuned tag with no measured window), dry-runs before it acts, confirms before a sweep that
will restart the daemon, writes `score.json` and `matrix.json` for the record (R17), and ends
by printing the two commands the operator has to run. It names no model tag: the tag is an
argument, and a resolver naming no qualified model is an explicit stop, never a fallback.

## Where it stops

At declaration. It writes `local-model-config.json`, declares the tag in `local-models.json`
as a candidate for the role, prints the `model_resolver.py --qualify` command, and stops.

**It never adopts a model.** Qualification grades code quality against a frozen task set; this
tool measures memory and speed. Different criterion, different oracle, and adopting a tag
changes what the local agents execute.

## Expected failure

A model whose weights nearly fill the card retains nothing, at any rung of any axis value.
That is a correct answer about this card, reported with the numbers behind it, not an error to
work around. A model whose weights alone exceed the card is refused before anything is built, but that
refusal rests on a measurement, not on the size of the file on disk. The manifest layer size
is the cheap first filter; when it trips, the model is loaded once at a 512-token window and
the decision is made on what the daemon reports pinning. The two disagree by a lot: measured
2026-08-28 on a 6144 MiB card, one tag weighing 9163 MiB on disk is fully resident at 3057
MiB, and another weighing 6289 MiB is fully resident at 5248 MiB. Refusing on the file size
alone turned both away.

## Tests

Five offline suites under `scripts/Test/`, no network, no GPU, no Ollama daemon:
`test_vram_probe.py` (11), `test_vram_modelfile.py` (11), `test_vram_daemon.py` (5),
`test_vram_optimizer.py` (24), `test_tune_preflight.py` (30). Eighty-one in total.

The last one covers the runbook, since the PowerShell cannot be run offline: every refusal,
the ranking, the summary, and three guards read off the `.ps1` as text - it must never hand
`--qualify` to the resolver, never shell out to `ollama run`, and never name a model tag, that
last check carrying a negative control so a broken pattern cannot pass silently.
