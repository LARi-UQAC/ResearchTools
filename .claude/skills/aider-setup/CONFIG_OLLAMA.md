# Configuring Ollama for this harness

**Goal.** Work out the Ollama settings for YOUR computer: the smallest context window that can hold this harness's prompt, and how many CPU threads and GPU layers your hardware actually wants.

**Contents.** The arithmetic, which is the same everywhere because it comes from `config/context-budget.json`; the test that measures the rest; and empty tables for your own numbers - every measurement here is yours to fill in by running `ollama-tune.bat`, because no two machines answer alike.

This harness assembles a prompt of a known minimum size, and a local model on a
small card is bounded by things that are measurable rather than guessable. This
file holds the arithmetic, the test that measures the rest, and what to do with
the answer.

Run the test with:

```
ollama-tune.bat
```

---

## 1. The minimum number of input tokens

Every number below comes from `config/context-budget.json`. Nothing here is a
preference: below this floor a plan does not run at all, and above it every
extra token of window is paid for in model weights pushed off the GPU.

### What is present on every single call

| Item | Tokens | Why it is always there |
|---|---:|---|
| reply reserve | 8 192 | room for the model's own answer. Twice the largest reply the ceilings permit, `audit.md` at 4 096 or a new code file at 4 000 |
| harness overhead | 3 072 | aider's system prompt, its edit-format examples, the file listing, the chat scaffolding — count it for your own aider version below |
| repo map | 4 096 | `--map-tokens`. Half of aider's own ceiling for this model class, which is a cap and not a target |
| **reserves subtotal** | **15 360** | **holds no file at all** |

That subtotal is the single most important number here: **15 360 tokens of any
window are gone before one line of a rule, a plan or a source file is loaded.**

The harness figure is the one worth understanding, because it is the only
reserve you can verify without loading a model. aider's system prompt, its
edit-format examples and its file scaffolding are **static text inside the
installed package**, so they can be counted exactly:

<!-- MEASURED:BEGIN aider harness components -->

| Component of aider 0.86.2, diff edit format | Tokens |
|---|---:|
| `system_reminder` | 530 |
| `example_messages` (4, fixed) | 369 |
| shell-command clause | 351 |
| file and repo-map scaffolding | 312 |
| `main_system` | 236 |
| **static total** | **1 798** |

The remainder of the 3 072 covers the per-file framing, which does grow with the
number of files in the chat. The `example_messages` do **not** — they are a
fixed four-message exchange, which is worth knowing because it is the usual
reason this reserve gets over-provisioned.

<!-- MEASURED:TEMPLATE -->

| Component of aider's diff edit format | Tokens |
|---|---:|
| `system_reminder` | |
| `example_messages` | |
| shell-command clause | |
| file and repo-map scaffolding | |
| `main_system` | |
| **static total** | |

Count them for your own aider version:

```
python -c "import tiktoken;from aider.coders.editblock_prompts import EditBlockPrompts as P;e=tiktoken.get_encoding('cl100k_base');p=P();print(sum(len(e.encode(getattr(p,n) or '')) for n in ('main_system','system_reminder','files_content_prefix','read_only_files_prefix','repo_content_prefix','shell_cmd_prompt','shell_cmd_reminder','go_ahead_tip')) + sum(len(e.encode(m['content'])) for m in (p.example_messages or [])))"
```

The remainder of the 3 072 covers the per-file framing, which grows with the
number of files in the chat. The `example_messages` do **not** — they are a
fixed exchange, which is the usual reason this reserve gets over-provisioned.

<!-- MEASURED:END -->

### What the protocol adds

`progress.md` points at the current `plan<N>.md`, and the harness **drops the
context between plans**, so exactly one plan is loaded at a time and the plans
are not summed.

| File | Ceiling | As shipped | Loaded |
|---|---:|---:|---|
| `conventions.md` | 2 500 | 1 889 | every call, as `--read` |
| `rules.md` | 3 500 | 2 729 | every call, as `--read` |
| `spec.md` | 4 000 | 65 | every call |
| `progress.md` | 2 048 | 145 | every call, and it GROWS with every plan |
| `plan<N>.md` | 4 000 | 92 | one at a time |
| **subtotal** | **16 048** | **4 920** | |

`audit.md` is not in that list because it is *written*, not read in. Its
ceiling is 4 096.

### What the skills add

The skill files have ceilings too, and they live in `skills.json` rather than in
`context-budget.json`. Exactly **one stage is active per call**, so the floor
takes the largest stage rather than the sum.

| Stage | File(s) | Ceiling | As shipped |
|---|---|---:|---:|
| write | `test-driven-development/` bundle | 2 500 | 2 427 |
| audit | `code-reviewer.md` | 2 000 | 1 283 |
| reopen | `receiving-code-review.md` | 2 000 | 1 487 |
| **largest stage, which is what the floor pays** | | **2 500** | |

The write bundle sits at **97 percent** of its ceiling, and that carries a trap:
§8.5 of `MANUAL.md` says you may refresh those files from an installed
superpowers. **A refresh restores the full upstream originals and overflows this
ceiling** — the shipped copies had their teaching prose removed to fit.

### The floor

| | Tokens |
|---|---:|
| reserves | 15 360 |
| always-on and protocol, at their ceilings | 16 048 |
| skills, largest stage | 2 500 |
| **minimum window, zero source code** | **33 908** |
| plus one new file and its test, at the 4 000 output ceiling | **41 908** |
| worst case, two *existing* files at the 16 000 read ceiling | 65 908 |

**Size the window for 41 908.** The 65 908 line is the case where a plan opens
two files each near the 16 000 read ceiling; the harness does not generate it on
its own, and a project whose files are that large should split them rather than
buy a larger window for all of them.

| Window | Left for source after the 33 908 floor | Verdict |
|---|---:|---|
| 32 768 | −1 140 | does not hold the floor at all |
| 49 152 | 15 244 | holds it, but not a 16 000 file plus a new one |
| **65 536** | **31 628** | **the recommendation** |
| 131 072 | 97 164 | wasteful: about 2.2 GB more VRAM on KV cache than 65 536 |

The arithmetic above is the same on every machine, because it comes from the
ceilings this kit ships. **Which of the qualifying rungs is right for YOUR card
is not**, and the only way to know is to load both and time them.

<!-- MEASURED:BEGIN candidate windows -->

| `num_ctx` granted | decode | layers on GPU | KV cache | device compute buffer |
|---:|---:|---:|---:|---:|
| 49 152 | 3.41 tok/s | 3 of 66 | 1 824 MiB | 770 MiB |
| 65 536 | 3.48 tok/s | 2 of 66 | 2 432 MiB | 856 MiB |

On the reference machine these are **throughput-equivalent** — 2 percent apart
against a run-to-run noise of about 12 percent — so the wider window costs
nothing measurable and doubles the working set, and it wins for that reason. Had
it been slower, the narrower one would have been the answer.

<!-- MEASURED:END -->

Read your own table the same way: if two qualifying rungs are within your
measured noise, take the **wider** one, because the working set is free at that
point. If the wider one is genuinely slower, take the narrower and accept that
plans must touch fewer or smaller files.

### 1.1 Measuring your own floor

The numbers above come from the ceilings this kit ships, so the floor is the
same arithmetic on every machine. What differs is how much of each allowance
your project actually uses, and that decides whether you can lower a ceiling and
buy back VRAM.

Two commands, neither of which loads a model:

```
ollama-tune.bat floor          the arithmetic: what your ceilings imply
ollama-tune.bat promptfloor    what your runs ACTUALLY sent, from the run logs
```

`promptfloor` is the one that matters. The driver writes every message it sends
to `docs/superpowers/plans/.logs`, so after a night you can measure the largest
prompt your own project produced. It reports plan and audit messages separately,
because an audit embeds source and a plan step does not.

<!-- MEASURED:BEGIN empirical floor -->

On the reference fixture the largest plan message was **119** tokens and the
largest audit message **819**, implying a window near **35 000** against a
ceiling-derived 41 908 — so the ceilings there carried about a factor of two in
hand.

<!-- MEASURED:TEMPLATE -->

| | Tokens |
|---|---:|
| largest plan message | |
| largest audit message | |
| window this implies | |
| against the ceiling-derived minimum | 41 908 |

<!-- MEASURED:END -->

The audit message is the one that grows with your code base — but it is
**batched**, bounded by `audit.max_files_per_batch` and
`audit.batch_safety_margin_tokens`, so it is bounded by design rather than by
the window.

### If the floor is larger than your card can hold

The floor is a consequence of `context-budget.json`, so it can be lowered
deliberately. In descending order of what they cost, and of what they risk:

| Lower this | Buys | Costs |
|---|---:|---|
| `ceilings.progress.md` | up to ~2 000 | nothing, if the ledger stays a list of tasks pointing at the plans rather than restating them |
| `repo_map_tokens` | up to ~2 000 | a smaller repo map. Safe for a project of a few dozen files; below aider's 1 024 default the model starts editing files it never saw |
| `ceilings.spec.md`, `ceilings.plan.md` | ~2 000 each | little, if specs and plans stay short. Measure with `promptfloor` first |
| `ceilings.rules.md` | ~1 000 | fewer or shorter rules reaching the model |
| `reserve.reply_tokens` | ~2 000 | **a truncated audit**, which loses findings silently. Only after measuring an `audit.md` near its ceiling |

Do not set a ceiling equal to a measurement. `progress.md` is the one file that
genuinely grows, and compressing the sections of finished plans to one line each
is part of the design rather than a remedy for an overflow.

### How big a file the coder should write

The `ceilings.code_file` figure of 16 000 tokens is a **reading** ceiling: how
large a source file may be when it is loaded into the prompt. It is a reasonable
number and worth keeping. It is **not** the right target for what the coder
should *produce*, and the two get confused because they are measured in the same
unit.

Three separate limits apply to output, and the smallest one wins.

| Limit | Value | Where it comes from |
|---|---|---|
| hard cap on one reply | 8 192 tokens | `reserve.reply_tokens`. Past it the reply is cut off |
| wall clock | **your decode rate x 60** | output tokens *are* minutes. At 4 tok/s that is 240 a minute |
| what the model does well | a few thousand tokens | a local model's single-shot generation degrades with length |

The wall clock is the one that actually binds, and it is easy to underestimate.
At the measured rate:

| Output in one reply | Time |
|---|---|
| 750 tokens | ~3 minutes |
| 4 000 tokens | ~17 minutes |
| 8 192 tokens | **~34 minutes** |

An eight-hour night is therefore about **115 000 output tokens in total**, across
every plan step, every test, and every audit. A single 16 000-token file spends
almost an hour of that on one reply — and aider's own fix loop retries up to
three times, so a step that fails at that size can cost three hours and produce
nothing.

Two facts make the practical answer much smaller than 16 000.

**Editing is cheap; creating is not.** aider uses SEARCH/REPLACE blocks, so
changing an existing file costs roughly twice the changed region, not the file's
size. Measured 2026-09-02 and recorded in `context-budget.json`, a plan step's
reply was **164 to 759 tokens**. The 8 192 reserve is not sized for code at all
— it is sized for `audit.md`, which is a whole document written in one reply.

**A file you cannot rewrite whole is a file you cannot recover.** If a file fits
in one reply, a step that goes wrong can be regenerated. Past that, the only
route is a diff onto something already broken.

Suggested targets:

| What | Target | Reason |
|---|---|---|
| a NEW source file | **≤ 4 000 tokens**, about 300–400 lines | rewritable whole inside the reply reserve, ~17 minutes, cheap to retry |
| one plan step's total output | **2 000–4 000 tokens** | one module plus its test |
| an existing file being edited | up to the 16 000 read ceiling | the diff is small even when the file is not |
| absolute ceiling | 8 192 | `reserve.reply_tokens`. Never *plan* to approach it |

So: **write plan steps that produce one module of roughly 300 lines and its
test.** A step that would produce more than that is two steps, and splitting it
costs nothing because the context is dropped between plans anyway.

One setting to check while you are here, and it takes TWO places rather than
one. Ollama's `num_predict` bounds a single reply. Left unbounded, a model that
starts repeating itself consumes hours of a night at 240 tokens per minute with
nothing to show; bounded too low, it truncates a reply mid-edit and aider writes
nothing at all, which is the more expensive failure because it looks like the
model produced code. Set it to the reply reserve in both places:

```
PARAMETER num_predict 8192          # the tuned tag's Modelfile
```

```yaml
  extra_params:                     # model-settings.yml, the SAME value
    num_ctx: 65536
    num_predict: 8192
```

**Why both places.** A request-level `num_predict` is honoured exactly -
measured 2026-09-05, 30 asked and 30 generated with `done_reason=length` - and
aider sends `extra_params` on every request, so the value in `model-settings.yml`
is the one that binds. The Modelfile line is the floor under any caller that
sends no options at all. Stating it twice costs nothing and removes a question.

### `think` — check this before you trust any budget above

Applies to the coder AND the reviewer.

**1. Ask whether your model is a thinking model.**

```powershell
ollama show <your-tag> | findstr /I "think"
```

**2. If it is, add one line to BOTH entries in `model-settings.yml`:**

```yaml
  extra_params:
    think: false
```

It cannot go in the Modelfile. Ollama reads `think` as a top-level field of the
request, never as a `PARAMETER`.

**3. Check that it took**, with two calls to `/api/chat` at a small
`num_predict`, one with the field and one without. Compare `eval_count` and
`done_reason`.

**Why it matters:** a thinking model emits its reasoning AS TOKENS, and those
are billed against `num_predict` like any others. Your editor may hide them -
aider's `reasoning_tag` does exactly that - and hiding is not the same as not
generating. Every budget above is then spent on text you never see.

<!-- MEASURED:BEGIN what reasoning costs the reply budget -->
Measured 2026-09-06 on the reference machine, two calls with one variable
changed, `num_predict` 250:

| | tokens generated | stop reason | content | reasoning |
|---|---|---|---|---|
| as sent before | 250 | `length` | **0 characters** | 724 characters |
| `think: false` | 51 | `stop` | 172 characters | 0 |

The first answer spent its entire budget deliberating and returned nothing. At
full scale the same thing had emptied two source files: 14336 tokens generated,
exactly `num_predict`, of which the editor counted 2803 as content.

<!-- MEASURED:TEMPLATE -->
Your own two calls, one variable changed:

| | tokens generated | stop reason | content | reasoning |
|---|---|---|---|---|
| as sent before | | | | |
| `think: false` | | | | |
<!-- MEASURED:END -->

**Know what this costs before you take it.** The forward pass is unchanged, so
the model still reasons; what it loses is the ability to write intermediate
steps and build on them. That costs little when transcribing an
already-decomposed plan and costs real depth on deduction - geometry,
invariants, error paths. Measured 2026-09-07 on this harness: the first module
written this way carried **zero** `raise` statements where three comparable
modules written with reasoning carried one to three each.

**The alternative, if that trade is not acceptable to you:** make each plan
small enough that a reply WITH reasoning fits the reserve. One module or its
test suite, not both. That is a change to your plans, not to your daemon.

**Set it to cover a whole PLAN, not one file.** This is where a night is lost.
Measured 2026-09-05: two plans in a row were cut off mid-word, and the server log
gives the arithmetic exactly - 20410 total tokens minus 8192 generated for a
12218-token prompt, and 17493 minus 8192 for a 9301-token one. Both replies ended
at precisely the reserve.

The budget had permitted it. A plan may name several files, each new one may
reach `ceilings.code_file_output`, and the WHOLE plan is answered in ONE reply
bounded by `reserve.reply_tokens`. Nothing compared those numbers. A plan creating
three files at a 4000-token ceiling asks for 12000 tokens of output into an
8192-token reply, so the reserve was raised to 14336 - the largest value that
still lets the computed window land on the 65536 rung rather than 131072, which
is the configuration measured to put ZERO layers of a 27B model on a 6 GB card.

**The driver now refuses the state that hides it.** Before running anything it
compares the `max_input_tokens` aider reports against the `num_ctx`
`model-settings.yml` sends. Those come from different places - litellm
metadata versus `extra_params` - and when they disagree the second is what
Ollama allocates while the first is what every budget is computed from. The
usual cause is a missing metadata entry for the tuned tag, which is written
by `aider-ollama-config.py`; the refusal names both numbers and points at it.

**Why this is hard to diagnose, and what to look for instead.** Every visible
signal pointed elsewhere. aider printed `Output tokens: ~2,104 of 8,192` - its own
counts are approximate and that one was wrong by a factor of four, which is why
the reserve looked untouched. The file aider had created was left EMPTY, because
it writes a file only once it has parsed a COMPLETE edit block. The suite then
reported `Ran 0 tests ... OK`, which the driver read as a pass. Three signals, all
misleading. The one that is not: the Ollama server log's `stop processing:
n_tokens = N` minus your reserve gives the prompt size, and if that subtraction
comes out to a round number you have found the cap.

What the failure looks like, so it is recognisable rather than mysterious: the
code appears in the chat, the file on disk stays **empty**, and the suite then
reports `Ran 0 tests ... OK`. Aider writes a file only once it has parsed a
COMPLETE edit block, so a truncated reply produces a created, empty file and no
error anywhere.

---

## 2. How the test works

`ollama-tune.bat` runs `ollama-tune.ps1`, which does the arithmetic above and
then drives `bin/aider-thread-probe.py` over four axes. The probe reloads the
model for each rung, evicting whatever was resident first, and **reads back from
the Ollama server log what the daemon actually did** rather than trusting what
it was asked for. That last point is the whole design: Ollama accepts a setting
and then silently places what it can.

| Phase | What it varies | What it answers | Needs the daemon |
|---|---|---|---|
| `floor` | nothing | the arithmetic of section 1 | no |
| `bandwidth` | concurrent DRAM readers | how fast this machine can read system RAM, and where more readers stop helping | no |
| `threads` | `num_thread` | decode and prefill throughput against CPU threads | yes |
| `layers` | `num_gpu` | whether forcing more layers onto the card beats the allocator's own choice | yes |
| `context` | `num_ctx` | what each window costs in KV cache, in compute buffer, and in layers it displaces | yes |

Each measured rung reports:

| Column | Source | Note |
|---|---|---|
| `thr_ask` / `thr_got` | request / server log | **different numbers mean the request was ignored**, and that rung measures nothing |
| `gpu_ask` / `gpu_lyr` | request / server log | likewise: `DECLINED` means the allocator placed fewer layers than asked |
| `dec_tps` | `/api/generate` | `eval_count / eval_duration`. Decode only |
| `pre_tps` | `/api/generate` | `prompt_eval_*`. Prefill, which is a separate and much less noisy signal |
| `cpu%`, `pk%` | kernel32 `GetSystemTimes` | mean and peak over the timed decode |
| `sm%` | `nvidia-smi dmon -s ut` | GPU SM utilization. See the note below |
| `freeRAM` | `GlobalMemoryStatusEx` | lowest reading during the decode |
| `pgin/s` | `Win32_PerfFormattedData_PerfOS_Memory` | **hard page-ins. Non-zero means the figures measure the disk as much as the CPU** |
| `rx_MB/s`, `tx_MB/s` | `nvidia-smi dmon -s ut` | real PCIe traffic during the decode |
| `load_s` | wall clock | how long the model took to load |

Three things the test is deliberately careful about, each because it was
measured going wrong:

- **A clamped window is not a measurement.** A `num_ctx` the daemon cannot place
  is reduced and reported as success. In the thread and layer phases such a rung
  is *rejected*, because two rungs on different windows are not comparable. In
  the `context` phase it is *recorded* with what was granted, because there the
  clamp is the answer.
- **An ignored setting is not a measurement.** `num_thread` and `num_gpu` are
  both read back from the log. A table of identical throughputs from ignored
  requests reads exactly like "this setting does not matter".
- **A counter that is unavailable says so.** A missing `nvidia-smi` or a
  non-Windows host reports the reason, never a zero. Zero page-ins and unmeasured
  page-ins lead to opposite conclusions.

### Why the GPU shows 0 percent in Task Manager

It is not broken and it is not the test. Task Manager's GPU graphs default to
the **3D** engine, while CUDA work appears under a separate **`Cuda`** or
**`Compute_0`** engine that is not displayed until a graph's dropdown is
changed. Read the real counter instead:

```
nvidia-smi --query-gpu=utilization.gpu --format=csv
```

Expect a low number anyway, and expect it to be correct. With a handful of a
model's layers on the card, the GPU finishes its share and then waits for the
CPU to grind through the rest of the token.

---

## 3. Configuring Ollama from the results

The test prints a recommendation block and, with `ollama-tune.bat quick apply`,
writes it into section 6 of this file. Three settings come out of it.

### Where to put them

Either as options on the request, or baked into a tuned tag, which is what a
harness should use because it cannot be forgotten:

```
# Modelfile
FROM <your-base-tag>
PARAMETER num_ctx    <from the test>
PARAMETER num_gpu    <from the test>
PARAMETER num_thread <from the test>
```

```
ollama create <your-tag>-tuned -f Modelfile
```

### `num_ctx` — set it from section 1, not from the model's maximum

Take the **smallest** window that clears the floor of section 1. This is the
setting that decides all the others, because a context window is not free: it
buys a **compute buffer that is charged to VRAM and displaces model weights**.

<!-- MEASURED:BEGIN window cost, same card two windows -->

Measured on a 6 GB laptop-class card, one large model at two windows:

| | at `num_ctx` 262144 | at `num_ctx` 8192 |
|---|---|---|
| VRAM in use | 4911 MiB | 4189 MiB |
| of which **weights** | **0 MiB** | **3564 MiB** |
| of which **compute buffer** | **3525 MiB** | **192 MiB** |
| layers placed on GPU | **0 of 61** | **12 of 66** |

The same VRAM total, spent on opposite things. At the huge window the buffer
alone took 3.5 GB of the card and there was no room left for a single layer,
which is why the model ran entirely on the CPU while the card *looked* busy.

<!-- MEASURED:TEMPLATE -->

Fill this in with `ollama-tune.bat context`, which reports the KV cache and the
device compute buffer per window, alongside how many layers were placed:

| | at your largest window | at your smallest |
|---|---|---|
| VRAM in use | | |
| of which **weights** | | |
| of which **compute buffer** | | |
| layers placed on GPU | | |

What you are looking for is whether the compute buffer alone crowds the weights
off the card. On a small card at a very large window it can: the total VRAM in
use looks the same, but none of it is model.

<!-- MEASURED:END -->

The KV cache is the **second** cost, not the first: about **34 KiB per token**
measured with `OLLAMA_KV_CACHE_TYPE=q8_0`.

### `num_gpu` — measure it, and accept that the answer may be "leave it alone"

Two measurements on this same card, on two different models, gave **opposite**
answers. That is the finding, and it is why this section tells you to read your
own table rather than to apply a verdict.

On the coder the allocator was measurably too conservative: it placed 5 layers
of 66 and refused a sixth while its own log reported 2 057 MiB still free and
`nvidia-smi` showed about 2.5 GB of the card idle. Forced to 12 layers it worked
and decode rose by over a quarter, and page-ins fell from 4 655/s at 5 layers to
under 1 100/s at 10 to 12 — every layer moved onto the card is a layer no longer
occupying system RAM, which is what stops the operating system paging your
editor out.

On the reviewer, a larger model on the same card, forcing layers bought
**nothing and cost the disk**: 2.83 tok/s at the allocator's own 2 layers
against 2.87 at 6, a 1.4 percent gap on a single run per rung, while page-ins
rose from 671/s to 3 604/s. There `num_gpu` was left unset, deliberately.

So run `ollama-tune.bat layers` on **each model you will actually use**, and
decide from three columns together:

- `gpu_lyr`, never the request. `DECLINED` means the card genuinely refused.
- `dec_tps`. A gap of a few percent from a single run is not a result — the
  probe says so itself. Raise `sweep.repeats` before acting on one.
- `pgin/s`. This is the tiebreaker. If forcing layers makes page-ins **fall**,
  take it even at equal throughput. If it makes them **rise**, the throughput
  gain is being paid for on your disk and it is not a gain.

<!-- MEASURED:BEGIN layer placement per model -->
Measured 2026-09-06 by `aider-thread-probe.py --mode gpulayers` on the
reference card, reviewer model at `num_ctx` 49152:

| forced `num_gpu` | placed | `dec_tps` | `pgin/s` | verdict |
|---|---|---|---|---|
| none | 0/61 | 3.01 | 1 150 | |
| 2 | 2/61 | 2.83 | 671 | the allocator's own choice |
| 4 | 4/61 | 2.85 | 863 | |
| 6 | 6/61 | 2.87 | **3 604** | gain inside the noise, paid on disk |

Conclusion for that model: set no `num_gpu` at all.

<!-- MEASURED:TEMPLATE -->
| forced `num_gpu` | placed | `dec_tps` | `pgin/s` | verdict |
|---|---|---|---|---|
| none | | | | |
| | | | | |
| | | | | |

Fill one table per model you run. The two on this machine disagreed, so one
table does not answer for the other.
<!-- MEASURED:END -->

### `num_thread` — set it, but do not over-read the precision

Threads help, and by less than the CPU count suggests. On the reference machine
the whole 4-to-20-thread range moved decode by about half, while a **repeated**
rung moved 12 percent on its own — wider than the gap between the top four
rungs. So pick a rung near the top of your measured range and prefer the lower
one when two are within your noise: the CPU left over is what keeps the machine
usable while a night runs.

`ollama-tune.bat threads` measures it, and raise `sweep.repeats` before trying
to separate two rungs that look close.

`prefill` is the cleaner signal. It rose monotonically where decode was noisy,
so when two thread rungs look equal, compare their `pre_tps`.

### Tune the REVIEWER too, not only the coder

Everything above is usually done for the model that writes code, and then the
reviewer is left as it was pulled. Do not do that. Two models run every night
here, they take turns on one card, and the reviewer is half the wall-clock time.

Left untuned it carries whatever its Modelfile happened to bake and nothing
else — no `num_thread`, no `num_gpu`, and crucially **no `num_predict`**, so
nothing bounds its reply. Measured on the reference machine 2026-09-06: the
untuned reviewer decoded at 1.6 tok/s against the coder's 2.8, and one review
ran for two hours and wrote no report at all.

Two traps are specific to the reviewer, and both cost a whole night here.

**A baked window is not the window you get.** The reviewer tag declared
`num_ctx 262144`. aider believed it and reported `~35,390 of 262,144` as its
reply was cut, while the daemon had opened the slot at 28 928 and the reply had
overrun it. Ask `ollama ps` what the CONTEXT column says. Ollama clamps a
window it cannot satisfy rather than refusing it, so the declared number tells
you nothing.

**A reasoning model spends the reply budget thinking.** If your reviewer is a
thinking model, its reasoning tokens are billed against `num_predict` even when
your editor hides them, and a review can burn its whole budget deliberating and
return an empty report. Send `think: false`. Measured here at `num_predict` 250,
one variable changed: with reasoning on, 250 tokens generated, stop reason
`length`, **zero characters of content**; with `think: false`, 51 tokens, stop
reason `stop`, a complete answer.

Do the same three steps you did for the coder, on the reviewer tag:

```
ollama-tune.bat layers      # its num_gpu answer may differ from the coder's
ollama-tune.bat threads     # confirm the thread rung transfers
```

then build its tuned tag, give it a `num_predict` about twice your `audit.md`
ceiling, and read the result back with `ollama ps`.

<!-- MEASURED:BEGIN reviewer tag, this machine -->
Reference machine, 2026-09-06, after tuning: `num_ctx` 49152, `num_thread` 14,
no `num_gpu`, `num_predict` 8192, `think: false`. Decode 2.86 tok/s against
1.6 untuned.

Caveat recorded rather than buried: every thread rung logged hard page-ins
during the timed decode, so those figures measure the disk as much as the CPU.

<!-- MEASURED:TEMPLATE -->
Your reviewer tag, after tuning:

| setting | your value | how you chose it |
|---|---|---|
| `num_ctx` | | |
| `num_thread` | | |
| `num_gpu` | | |
| `num_predict` | | |
| `think` | | |

Decode before tuning: ______ tok/s. After: ______ tok/s.
<!-- MEASURED:END -->

### `OLLAMA_*` environment variables, which are a separate matter

These are read by the **daemon at start**, not per request, so a change needs a
daemon restart to take effect and the effect must be verified rather than
assumed.

| Variable | Why |
|---|---|
| `OLLAMA_KV_CACHE_TYPE=q8_0` | halves the KV cache against the default, which is the second-largest VRAM cost |
| `OLLAMA_MAX_LOADED_MODELS=1` | this harness uses two models and swaps between them; two large models briefly resident together is how a laptop stops |
| `OLLAMA_FLASH_ATTENTION=1` | reduces the attention working set |
| `OLLAMA_KEEP_ALIVE` | the harness sends its own `keep_alive` per request, which overrides this |

---

## 4. What size of model this computer should run

The card is the binding constraint, and the arithmetic is short. For a model to
run **entirely** on the GPU:

```
weights + KV cache + compute buffer + CUDA context  <=  VRAM available
```

Two of the four terms you can get without loading anything. The KV cache is
about **34 KiB per token** for a 4-bit model with `OLLAMA_KV_CACHE_TYPE=q8_0`,
and the CUDA context is roughly **300 MiB**. The other two have to be measured,
and one of them is the trap.

**The available VRAM is not your card's size.** The desktop compositor and every
GPU-accelerated application — your editor and your browser both count — hold
VRAM before Ollama is consulted, and the allocator budgets against what is left.
`ollama-tune.bat context` reports what the allocator actually granted, which is
the only figure worth acting on.

Fill this in from your own run. `ollama-tune.bat context` gives you the KV cache
and compute buffer per window; `nvidia-smi --query-gpu=memory.total,memory.used`
with nothing loaded gives you what the desktop is already holding.

<!-- MEASURED:BEGIN weights budget by window -->

| `num_ctx` | KV cache | compute buffer | overhead total | weights budget | largest model fully resident |
|---:|---:|---:|---:|---:|---|
| 8 192 | 272 MiB | 192 MiB | ~0.8 GB | | |
| 16 384 | 544 MiB | | | | |
| 32 768 | 1.1 GB | | | | |
| 49 152 | 1 824 MiB | 770 MiB | ~2.9 GB | | |
| 65 536 | 2 432 MiB | 856 MiB | ~3.6 GB | | |
| 131 072 | 4.4 GB | | | | |
| 262 144 | 8.7 GB | 3 525 MiB | over a 6 GB card | none | none — 0 layers placed |

<!-- MEASURED:END -->

### How to read your own table

1. **Start from the floor.** Section 1 gives the smallest window this harness can
   run in. Rows below it are unusable however fast they look.
2. **Subtract the overhead at that window** from your available VRAM. What is
   left is the weights budget.
3. **Compare it against the model file's size on disk.** A 4-bit model's weights
   are roughly its download size. If the weights fit inside the budget, the model
   runs entirely on the GPU and is not bounded by system memory bandwidth at all
   — usually several times faster than any partial offload.
4. **If nothing fits, that is an answer too.** A model larger than the budget
   runs partly on the CPU, and its speed is then set by your memory bandwidth
   rather than your card. `ollama-tune.bat quick` measures both.

The general shape, which holds on any small card: **a large window and a large
model are alternatives, not a pair.** Every token of window is KV cache and
compute buffer, and both are charged to the same VRAM the weights need. The
worst configuration is a large model at a large window, which puts no layers on
the card, all weights in system RAM, and the operating system into paging.

### Before choosing, close things

Two resources are freed, not one, and the second is the one people miss:

| Freed by closing applications | Effect |
|---|---|
| system RAM | fewer hard page-ins, so fewer weight faults per token |
| **VRAM** | the allocator's budget rises, so **more layers become placeable** |

Measure with the desktop as it will be during a run. An unattended night has the
whole machine; an afternoon with an editor and a browser open does not, and the
two give different answers.

Every measurement in this file was taken with a desktop running, so the layer
counts here are a **floor and not a ceiling**. For an unattended overnight run,
where nothing else needs the machine, re-run the test with the desktop closed
and expect better numbers than these.

---

## 5. Running the test

```
ollama-tune.bat                 the quick run: floor, bandwidth, 3 thread rungs, 2 layer rungs
ollama-tune.bat floor           the arithmetic only. Seconds, no model loaded
ollama-tune.bat promptfloor     what your runs ACTUALLY sent, from the run logs
ollama-tune.bat context         what each context window costs
ollama-tune.bat layers          decode against forced num_gpu, once per rung
ollama-tune.bat repeat          the same, every rung THREE times, interleaved
ollama-tune.bat full            every axis at every rung. Budget an hour
ollama-tune.bat quick apply     the quick run, and write section 6 of this file
```

### Why `repeat` exists, and when you need it

One run of a setting does not separate it from its neighbour. On the reference
machine a single offload setting measured three times gave **3.48, 3.00 and
3.02 tok/s** — a 16 percent spread, wider than the gap between the settings
being compared. A single sweep would therefore have named a winner on noise.

`repeat` runs every rung three times and **interleaves** them (2, 3, 4, 2, 3, 4,
…) rather than blocking them (2, 2, 2, 3, 3, 3). That matters: in the same run
every setting declined steadily as the machine warmed, and blocked repeats would
have charged that whole drift to whichever setting happened to go last.
Interleaved, the drift falls on all of them equally and the ranking survives even
though the absolute numbers do not.

**Use `repeat` whenever two settings look close** — which, on a small card, is
most of the time. `layers` is enough only to find a difference so large that
noise cannot explain it.

The verdict tells you which case you are in: it reports the mean of each setting
with how many runs it averages, states the run-to-run spread, and says outright
when every setting was run **once**, so a ranking is never presented as settled
when it is not.

### Applying the result

```
python bin\aider-ollama-config.py --report <the report the run printed> --yes
```

That computes `num_ctx` from the budget, takes `num_gpu` and `num_thread` from
the report, writes the Modelfile, creates the tuned tag and **reads it back** to
prove the parameters took. Add `--tag <name>` to choose the name.

Only after that read-back succeeds does it wire the tag into aider, because
wiring the harness to a tag whose parameters did not take would point it at the
failure rather than away from it. Two files, both of which fail silently when
they disagree with the tag:

- `model-settings.yml` gets the tuned entry's `extra_params: num_ctx:` **and**
  `num_predict:`, both for the same reason and both measured to be needed. aider
  sends `extra_params` on every request and a request-level `num_ctx`
  **overrides the Modelfile**, so without this the tag runs at the base entry's
  window and the tuning is invisible rather than absent.
- `~\.aider.model.metadata.json` gets `max_input_tokens`. aider otherwise
  asks Ollama, which answers with the architecture's native maximum whatever
  the Modelfile bakes in.

Each is add-only: the tuned entry's number is corrected and every other entry,
and every comment, is left byte-identical. `--no-wire` skips both, `--settings`
and `--metadata` point them elsewhere.

While a sweep runs the machine is loaded and any resident model is evicted
between rungs, so do not run it during work you care about. The sweeps change no
Ollama setting; only the command above does, and only with `--yes`.

To check the tools before trusting them:

```
python bin\Test\test_aider_thread_probe.py
python bin\Test\test_aider_ollama_config.py
```

---

## 6. Results measured on this machine

<!-- RESULTS:BEGIN -->

The previous contents were discarded on 2026-09-05. The measurements in them
were sound - they came from the daemon's own log - but the recommendation
computed on top of them was not: it sized `num_ctx` from the 16 000-token READ
ceiling and so said 131 072, it picked the fastest thread rung rather than the
lowest one within tolerance and so said 20 threads at 99 percent CPU, and it
wrote decimal separators in two different conventions. All three are fixed.

**Run the test: `ollama-tune.bat quick apply`**

<!-- RESULTS:END -->
