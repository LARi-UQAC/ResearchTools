# Code Style

General code and document conventions for any project in this workspace. Where a project
ships its own stack, follow the matching language section; the LaTeX and documentation
sections apply to all academic work.

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

### File size ceiling

No source file exceeds 4096 tokens, a quarter of the local model's measured 16384-token
context window. The constraint comes from the local model, not the cloud one: the local
bridge (`.claude/skills/loop-engineer/scripts/ollama_bridge.py`) works inside a window an
order of magnitude smaller than a cloud model's, and Ollama does not raise an error when a
prompt exceeds it - it silently truncates to `num_ctx // 2 + 2` tokens and reports success,
so an oversized file handed whole to a local task loses exactly the instruction most likely
to sit at the end. It is good practice independent of that origin: a file a quarter of a
16384-token window still holds is a file a reviewer, human or model, can hold in mind
without paging. This number is derived from a measurement that can change - the retained
window lives in `.claude/local-model-config.json` (`models["<the tag the resolver returns>"].retained_num_ctx`,
written by `optimize_ollama.py --sweep`), machine-local and gitignored - so treat 4096 as
that measurement's current quarter, not a fixed constant. `context_budget.py --scan <path>`
reads the live window and names every file above the threshold; it does not split them.

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

### Python
- Validate required inputs at entry; fail fast with a clear message.
- For HTTP/API clients (e.g. the `scopus` scripts), catch network and timeout errors
  explicitly and surface an actionable message rather than a bare traceback.
- Do not silently swallow exceptions; log the cause.

### Web back ends (when present)
- Wrap external calls in try/catch, handle cancellation and timeout separately, return safe
  fallbacks, and log with structured parameters.

## Logging

### Python
Use `logging.getLogger(__name__)` per module. Prefix messages with a context tag:

```python
logger.info("[SCOPUS] query sent")
logger.error("[VALIDATION] DOI not found")
```

### Other languages
Inject the framework logger and use structured parameters rather than string concatenation.
