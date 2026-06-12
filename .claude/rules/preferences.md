# Preferences

## Documentation Structure
- **Frontend documentation home**: `web/CostEstimator.Web/docs/` (all UI, component, interop, and integration docs)
- **Cross-layer context**: `.claude/CLAUDE.md` (3-layer architecture, no duplication)
- **Backend docs**: `api/README.md` (Flask-specific)
- **Engine docs**: `cost_estimator_project/README.md`, `project_structure.md` (Python analysis engine)
- **Operational scripts**: `scripts/` (`start/`, `audit/`, `test/`, `scaffold/`, `dev/`)
- **Code rules/style**: This folder `.claude/rules/` (not for end-user docs)

When documenting a new frontend feature:
- Update the relevant subfolder under `web/CostEstimator.Web/docs/` (architecture/ui/interop/api-integration/reference)
- Link from that index in `DOCUMENTATION_INDEX.md` if it's a major feature
- In code docstrings, reference the relevant doc with relative path: `/// See docs/ui/component-patterns.md for ValidationCard contract`

## Localization
- Two languages: French (default) and English
- All UI strings live in `LocalizationService.cs` — add new keys there, not inline in Razor files
- Inject with `@inject LocalizationService L` and use `@L["key"]`
- Key format: `section.key` (e.g. `step1.title`, `home.paramHeight`, `nav.next`)
- Export language (`ExportLanguage`) may differ from UI language (`CurrentLanguage`)

## Blazor render mode
- Always `@rendermode="InteractiveServer"` (SignalR). Never assume WASM behavior.

## JS interop (geometry-interop.js)
- Element identity across interop calls: use `el.getAttribute('data-ce-vid')` (DOM attribute, survives Blazor proxy re-creation)
- Never key module-level Maps by the ElementReference object itself
- After every change to any file in `wwwroot/js/`, increment the `?v=N` query string in `App.razor`:
  - `geometry-interop.js?v=11` — this is the file that requires versioning
  - `zoom-interop.js` — no versioning (static)

## ValidationCard component
- Shared across all 5 steps (`web/CostEstimator.Web/Components/Shared/ValidationCard.razor`)
- Do not duplicate zoom/pan/rubber-band logic — it belongs here
- Add step-specific UI via the `RenderFragment` slots: `ImageOverlayContent`, `AfterUserValueContent`, `NavigationButtons`, `ExtraDebugContent`
- Scale/geometry parameters (Steps 1 & 2 only): `ScaleX`, `ScaleY`, `ScaleUnit`, `GeometryShapesJson`, `OnGetScaleClick`, `OnShapesEdited`

## Geometry annotations
- Supported shape primitives: `rect`, `triangle`, `trapezoid`, `parallelogram`
- Store `form` (geometric primitive) and `classification` (architectural element) as separate fields — they must never overwrite each other
- Dimension enrichment (`_geoEnrichShapeDimensions`) runs at draw completion and after every vertex drag

## API communication
- Use `CostEstimatorApiClient` for all HTTP calls from Blazor — never call `HttpClient` directly from pages
- Session ID flows: PDF upload → `SessionStateService.SessionId` → all subsequent API calls
- Async methods return tuples on failure: `(string.Empty, "error message")`

## Excel export
- Export language is set independently of UI language via `LocalizationService.ExportLanguage`
- Cost formula: `(Perimeter × Height × UnitPrice) + OpeningsCost + CornersCost`
