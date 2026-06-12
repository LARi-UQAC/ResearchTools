# Code Style

## Naming conventions

### C# (Blazor)
- Classes, methods, properties, EventCallbacks: `PascalCase`
- Private fields: `_camelCase` (leading underscore)
- Parameters/locals: `camelCase`
- Event callback parameters prefixed with `On`: `OnValidateClick`, `OnShapesEdited`

### Python (Flask API + analysis engine)
- Classes: `PascalCase`
- Functions and module variables: `snake_case`
- Private functions and module-level internals: `_snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Type hints always present in function signatures

### JavaScript / Razor
- Component files: `PascalCase.razor`
- Page files: `Step{N}{Name}.razor` for step workflow pages
- CSS classes: `kebab-case` with `ce-` prefix (never raw Bootstrap overrides)

## Docstrings

### Python
Module-level docstring explains purpose and pipeline stage:
```
"""
Module name — Stage N of the analysis pipeline.
Brief description.
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

### C#
Use `/// <summary>` XML doc for public types and non-obvious members only.

### Documentation References in Code
When a docstring mentions a complex behavior or data structure, reference the relevant frontend doc:
```csharp
/// <summary>
/// Handles geometry shape validation. See ../../docs/ui/component-patterns.md for ValidationCard RenderFragment contract.
/// </summary>
```

Python and JavaScript modules should similarly link to their relevant docs sections.

## Documentation Standards

### Diagrams
- **Mermaid** (preferred for version control and editability):
  - Store `.mmd` sources in `web/CostEstimator.Web/docs/diagrams/`
  - Inline in markdown using ` ```mermaid ... ``` ` fenced blocks
  - Use for: data flows, state machines, component trees, step workflows
  
- **SVG** (for complex visual layouts):
  - Export from draw.io with layers enabled
  - Store in `web/CostEstimator.Web/docs/diagrams/` with descriptive names
  - Reference in markdown: `![Description](diagrams/filename.svg)`
  - Always maintain the `.drawio` editable source alongside the SVG export

### Mathematical Equations (KaTeX/LaTeX)
- **Inline**: Wrap in `$...$` delimiters
  ```markdown
  The formula is $\text{Cost} = (\text{Perimeter} \times \text{Height} \times \text{UnitPrice}) + \text{OpeningsCost}$.
  ```
- **Display blocks**: Wrap in `$$...$$` delimiters
  ```markdown
  $$\text{Wall Cost} = (\text{Perimeter} \times \text{Height} \times \text{UnitPrice}) + \text{OpeningsCost} + \text{CornersCost}$$
  ```
- **Canonical reference**: `web/CostEstimator.Web/docs/formulas/canonical-equations.md`
- **Validation**: Equations referenced in docs must have corresponding unit tests in `api/test_excel_generator.py` or `cost_estimator_project/Test/`

### Naming Conventions for Documentation Files
- **Frontend docs**: `{category}-{topic}.md` (e.g., `component-validation-card.md`, `integration-geometry-interop.md`)
- **Category folders**: `architecture/`, `ui/`, `interop/`, `api-integration/`, `reference/`, `diagrams/`, `formulas/`, `archive/`

## Error handling

### C# (Blazor services)
- Wrap every HTTP call in try/catch
- Catch `OperationCanceledException` separately for timeout handling
- Return safe fallbacks: `(string.Empty, "error message")` or `null`
- Log errors with structured parameters via `ILogger<T>`

### Python (Flask routes)
- Return `jsonify({"status": "error", "message": "..."})` with explicit HTTP status codes
- 400 for validation failures, 404 for missing sessions, 500 for unexpected errors
- Validate all required JSON fields before processing; return 400 immediately if missing

## CSS design system
- Use `ce-*` classes and CSS variables from `web/CostEstimator.Web/wwwroot/app.css`
- Do not override Bootstrap directly; use `ce-btn`, `ce-text-*`, `ce-bg-*`, etc.
- Theme tokens live in `:root` as `--ce-*` variables (e.g. `--ce-primary`, `--ce-danger`)
- Component-specific classes: `ce-card-header`, `ce-alert-error`, `ce-badge-step`, etc.

## Logging

### C#
Inject `ILogger<T>` via constructor. Use structured parameters:
```csharp
_logger.LogError("Prepare step failed for step {Step}: {Status}", step, response.StatusCode);
```

### Python
Use `logging.getLogger(__name__)` per module. Prefix messages with context tags:
```python
logger.info("[UPLOAD] Request received")
logger.error("[VALIDATION] Session not found")
```
