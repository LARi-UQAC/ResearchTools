# Code Style

General code and document conventions for any project in this workspace. Where a project
ships its own stack, follow the matching language section; the LaTeX and documentation
sections apply to all academic work.

## Rule identifiers

The numbered rules `R0` to `R24` are workspace-wide and stable; cite them by number in a
review, a commit message, or an audit plan. Each lives in the file that enforces it: `R0`
to `R13`, `R16`, `R17` and `R19` in this file, `R14`, `R15`, `R22` and `R23` in
`preferences.md`, `R18` in `workflows.md`, `R20` and `R21` in `testing.md`, `R24` in
`security.md`. They are unrelated to the `R1.x` sentence rules of the `scientific-writing`
skill's `composition_rules.md`, which govern prose rather than code.

## Naming conventions

### Python
- Classes: `PascalCase`
- Functions and module variables: `snake_case`
- Private functions and module-level internals: `_snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Type hints always present in function signatures (PEP 8 / PEP 484)

### JavaScript / TypeScript
- Classes and components: `PascalCase`
- Functions, variables: `camelCase`
- Constants: `UPPER_SNAKE_CASE`
- Files: `kebab-case`, or the framework convention (e.g. `PascalCase` component files)

### C# (when present)
- Classes, methods, properties: `PascalCase`
- Private fields: `_camelCase`
- Parameters and locals: `camelCase`

### LaTeX labels
- Figures: `fig:three-words`, cited with `\ref{}`
- Tables: `tab:three-words`, cited with `\ref{}`
- Equations: `eq:three-words`, cited with `\eqref{}` (or `\ref{}`) before the equation
- References (`\cite{}`): first author, year, one keyword (e.g. `otis2024diagnosis`)
- TikZ figures: simple code for the TiKZiT parser, named styles in `.tikzstyles`,
  `positioning` and node distance only (no absolute coordinates)

### Size limits, and what they actually bind

The limit is on what a local model is GIVEN, never on how large a source file may be. A
script invoked as a tool is executed, not read into a prompt, so its size costs a local
model nothing. Two things are given to a local model, and each is bounded for its own
reason.

**The plan handed to `local-coder`.** The plan and the code it dictates share one window, so
the plan has to leave room for the answer. That budget is not a property of the repository,
it is part of the plan's design: it is specified by the user when `superpowers:writing-plans`
is invoked, alongside the rest of the specification. **Without that specification, do not use
`local-coder` at all.** There is no default to fall back on, because the right split between
instruction and output depends on what is being built, and guessing it is how a task silently
loses its ending: Ollama does not error when a prompt exceeds the window, it truncates to
`num_ctx // 2 + 2` tokens and reports success, so the instruction most likely to be lost is
the last one.

**The note `local-writer` stages for the vault.** A formal limit, because every write it
makes passes through the same window, and a truncated note is written to the vault as though
it were whole. This is separate from, and stricter than, the Obsidian CLI's own ~4096-byte
header threshold, which is why the outbox exists at all (see `security.md`).

Both numbers are quarters of a measured window, not constants. The retained window lives in
`.claude/local-model-config.json` (`models["<the tag the resolver returns>"].retained_num_ctx`,
written by `optimize_ollama.py --sweep`), machine-local and gitignored. Measured 2026-08-29:
the tags currently adopted for both roles retain 16384, so the working quarter is 4096, while
the same file holds a 65536 measurement on a tag that is not adopted - the number therefore
moves with adoption, and reading it from the file is the only correct way to know it.

`context_budget.py --task <prompt file>` is the check that matters: it measures the ASSEMBLED
prompt against the live window and exits non-zero, at the moment the prompt is built.
`context_budget.py --scan <path>` reports files larger than that quarter; it is a review aid
for deciding what could be handed to a local model, not a gate on the repository, and it
splits nothing.

## Constants and configuration

A literal value inside code is a value nobody can change without editing code and nobody
can trace back to a decision. These rules move every such value out to a place that is read
at run time and that states where the value came from.

**R0 - no hardcoded numerical value.** Thresholds, limits, timeouts, ports, window sizes,
tolerances, target scores, retry counts, sample counts and keys are read from a
configuration file, or from a database where the project has one, never written as a literal
in the code that uses them. A pure mathematical constant of the domain (the 2 of a mean, a
unit conversion factor) and a value fixed inside a test fixture are not configuration and
stay in place. When the value is specified nowhere, ask with AskUserQuestion rather than
inventing a plausible default: once committed, an invented default is indistinguishable
from a measured one.

**R1 - no hardcoded path.** An absolute path, a vault root, an output directory, a binary
location and any machine-specific home resolve from an environment variable or a
configuration file. `OBSIDIAN_VAULT` is the model: a documented default, substituted at
install time, never a literal inside a script. A path with no configured source is an
AskUserQuestion, not a guess. A relative path resolved from the module's own location is
not configuration.

**R2 - no hardcoded external identifier.** A model tag, an API host, a DOI prefix, an ISSN,
a publisher name: exactly one module owns each identifier class and every other caller asks
it. `model_resolver.py` is the only thing in this repo that names a model tag, and
`doi_publisher.py` the only thing that maps a DOI prefix to a publisher. A duplicated
identifier creates two truths that drift apart silently.

**R3 - a missing configuration value is an explicit error.** The message names the key and
the file it was expected in. Never a silent default and never a substitution with a weaker
resource: `context_budget.py` fails rather than borrowing another model's window, and the
resolver refuses rather than returning a lesser tag. See also R8.

**R4 - a numeric key carries its unit and its provenance.** `retained_num_ctx` says what it
counts and, through its writer (`optimize_ollama.py --sweep`), that it was measured on this
machine. Provenance is one of three: measured (name the script and the date), specified
(name the standard, journal or publisher rule), or chosen by the user (name them). A number
with no provenance cannot be revised by anyone later.

**R5 - an enum-like literal comes from one table.** Roles (`writer`, `coder`), modes
(`audit`, `mine`), statuses (`submitted`, `deposed`), KV cache types, note types: define
them once as a constant or a small module and import them. A repeated string literal is a
typo waiting to become a silent no-op.

**R13 - a measured number written into a rule, a document or a comment carries its date and
what measured it.** This is the counterpart of R0 and resolves its apparent tension: a
number in code comes from configuration, a number in prose comes with provenance. The
4096-token quarter above is the model, since it states the window it is a quarter of, the
file that holds that window, the script that wrote it, and the date it was read; the dated
measurement notes in
the repo-root `CLAUDE.md` are the same discipline. A bare number in prose is unrevisable,
because nobody can tell whether it was measured, specified or invented.

## Data is not code

**R6 - a list of literals is data.** Find-and-replace pairs, a keyword map, a per-venue
table, a gazetteer, a prompt catalogue: they live in a JSON, CSV or YAML file that the
script reads, and the script holds the harness only. The anti-pattern named in
`workflows.md` (a patch script whose body is one long list of literal pairs for a single
manuscript) is the general case, data wearing a script's clothes.

**R7 - no per-manuscript, per-student or per-course specific inside repo code.** Anything
true of exactly one document, one candidate or one term is a parameter, a profile entry in
`profiles/<name>.yaml`, or a CLI argument. Repo code stays reusable for the next paper, and
the project directory holds only a thin wrapper with no logic (see `workflows.md`, "Where
code belongs", step 5).

## Docstrings

### Python
Module-level docstring states purpose and, where the module is part of a pipeline, its
stage:

```
"""
Module name - purpose in one or two sentences.
"""
```

Function docstrings use the project's extended format:

```
"""
--------------------------------------------------------------------------
Purpose:
    One or two sentences.

Inputs:
    param (type): description

Outputs:
    result (type): description
--------------------------------------------------------------------------
"""
```

### Other languages
Use the idiomatic doc form (`/// <summary>` for C#, JSDoc for JS/TS) on public types and
non-obvious members only. Document WHY, not WHAT.

### References in code
When a docstring describes complex behavior or a data structure documented elsewhere, link
to the relevant doc with a relative path.

## Documentation standards

### Diagrams
- Mermaid preferred for version control: store `.mmd` sources and inline with fenced
  ` ```mermaid ``` ` blocks. Use for data flows, state machines, component trees, workflows.
- SVG for complex visual layouts; keep the editable source (`.drawio`) alongside the export.
- TikZ for academic figures (see the LaTeX label rules above and `.claude/CLAUDE.md`).

### Mathematical equations
- Markdown / KaTeX: inline `$...$`, display `$$...$$`.
- LaTeX documents: every equation labeled and cited before it appears; variables defined
  directly under the equation if not already introduced.

### Documentation file naming
- `{category}-{topic}.md` (e.g. `component-validation.md`, `integration-geometry.md`)
- Category folders such as `architecture/`, `reference/`, `diagrams/`, `formulas/`.

## Error handling

### Failure semantics (any language)

**R8 - no silent fallback.** A missing dependency, key, measurement or model stops the run
and names what is missing. Never substitute something weaker and continue: the local bridge
has no fallback tag, and a resolver naming no qualified model is an explicit stop. An
unannounced fallback turns a hard failure into a wrong answer, which costs more.

**R9 - verify the effect, not the return code, whenever the tool is known to lie.** Read
back the state that was supposed to change. Measured cases: the Obsidian CLI exits 0 on a
write that never happened, so the outbox hook compares `st_size` before and after; Ollama
silently clamps `options.num_ctx` instead of erroring, so a swept rung is checked against
the model's native maximum; the daemon restart script exits 0 while an orphaned child keeps
its VRAM, so `ollama ps` and `nvidia-smi` are read afterwards.

**R10 - every network and subprocess call has an explicit timeout and a bounded retry
count.** The timeout value itself follows R0. No unbounded wait and no unbounded retry loop.
State the timeout at the call site or in the header so a reader does not have to infer it.

**R11 - a hook, or any process running on someone else's behalf, exits 0 when its own
dependency is absent, and says nothing.** Only a real violation of what it guards exits
non-zero. Measured 2026-08-27: `vault-access-guard.py` had been removed from
`~/.claude/hooks/` while `settings.json` still declared it, the interpreter returned a
non-zero code, and Read, Grep and Bash were refused for four turns. The wider the matcher,
the more critical the rule.

**R12 - exit codes mean something, and the header says what.** 0 is success, 2 is refusal by
design (the bridge uses it for a caller that omitted both `--vault-context` and
`--no-vault-context`), any other non-zero is failure. A caller can then branch on a refusal
without parsing prose.

### Python
- Validate required inputs at entry; fail fast with a clear message.
- For HTTP/API clients (e.g. the `scopus` scripts), catch network and timeout errors
  explicitly and surface an actionable message rather than a bare traceback.
- Do not silently swallow exceptions; log the cause.

### Web back ends (when present)
- Wrap external calls in try/catch, handle cancellation and timeout separately, return safe
  fallbacks, and log with structured parameters.

## Script interface

**R16 - a state-changing script offers `--dry-run`, and a destructive path also requires
`--yes`.** The dry run prints exactly what would be done and touches nothing;
`vault_consolidate.py --apply --yes` is the model, and its CLI dry-run gate is covered by a
test. A dry run is the only cheap way to review an action whose effect is spread across many
files.

**R17 - a state-changing script emits a machine-readable report beside its human text.**
Normally JSON, as `bib_audit.py` and `deliberate.py` already do: a caller reads a field
instead of matching prose, and two runs can be diffed. Keep the human text as well, since
the report is for the caller and the text is for the person.

## Determinism

**R19 - no wall clock and no unseeded randomness in logic that must be reproducible.** A
timestamp and a seed are injected by the caller, from configuration or from an argument
(`ollama_bridge.py` passes a seed, and the Workflow runtime makes `Date.now()` and
`Math.random()` throw for exactly this reason). Stamp the result after the work rather than
inside it, so the same input gives the same output on a re-run.

## Logging

### Python
Use `logging.getLogger(__name__)` per module. Prefix messages with a context tag:

```python
logger.info("[SCOPUS] query sent")
logger.error("[VALIDATION] DOI not found")
```

### Other languages
Inject the framework logger and use structured parameters rather than string concatenation.
