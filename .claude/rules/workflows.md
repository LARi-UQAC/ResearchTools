# Workflows

## Starting the application

```bash
# Quickest — double-click or run:
.\stcost.bat          # Opens two cmd windows + Chrome

# PowerShell (supports -Clean to kill old processes):
.\START_APPLICATION.ps1        # Root wrapper
# or the canonical script path:
.\scripts\start\START_APPLICATION.ps1

# Manual (two terminals):
# Terminal 1 — Flask API (port 5000)
cd api && .\.venv\Scripts\Activate.ps1 && python run.py

# Terminal 2 — Blazor frontend (port 5246)
cd web\CostEstimator.Web && dotnet run
```

Flask must start **before** Blazor.

## Health checks

```bash
# Flask API
Invoke-WebRequest http://localhost:5000/api/health -UseBasicParsing

# Blazor
Invoke-WebRequest http://localhost:5246 -UseBasicParsing | Select StatusCode
```

## Modifying the JS interop layer
1. Edit the file in `web/CostEstimator.Web/wwwroot/js/`
2. Increment `?v=N` on the `<script>` tag in `App.razor` for that file
3. Hard-reload the browser (Ctrl+Shift+R) to bust the cache

## Adding a new API endpoint
1. Create or extend a route file in `api/routes/`
2. Register the blueprint in `api/app.py` if adding a new file
3. Add a corresponding method to `CostEstimatorApiClient.cs` in the Blazor service layer
4. Document the endpoint in `.claude/CLAUDE.md` (source of truth for cross-layer API contract)
5. Update `web/CostEstimator.Web/docs/reference/api-endpoints.md` with endpoint details (copy from CLAUDE.md if stable)
6. If the endpoint is consumer-specific (geometry, composition, etc.), update the relevant guide in `web/CostEstimator.Web/docs/api-integration/`

## Adding a localization key
1. Open `web/CostEstimator.Web/Services/LocalizationService.cs`
2. Add the key to the dictionary initializer for both `"fr"` and `"en"` entries
3. Use `@L["your.key"]` in the Razor component
4. Update the key registry in `web/CostEstimator.Web/docs/reference/localization-keys.md` for reference

## Adding a new validation step page
Follow the existing pattern in `Components/Pages/Step1Height.razor`:
1. Create `Step{N}{Name}.razor` in `Components/Pages/`
2. Document the step's purpose and validation rules in `web/CostEstimator.Web/docs/ui/step-pages.md`
3. Update `web/CostEstimator.Web/docs/diagrams/step-workflow.mmd` (Mermaid) if state flow changes
2. Use `ValidationCard` as the wrapper with appropriate `RenderFragment` slots
3. Add the route to `Routes.razor` / navigation logic in the step service
4. Add `POST /api/prepare-step` and `POST /api/validate` calls via `CostEstimatorApiClient`

## Documentation Maintenance
Always update docs after major changes:
1. **Frontend feature**: Update `web/CostEstimator.Web/docs/{category}/*.md`
2. **API change**: Update `.claude/CLAUDE.md##API-endpoints` and relevant integration guide
3. **Geometry/composition flow**: Update `web/CostEstimator.Web/docs/api-integration/` and relevant Mermaid diagram
4. **Cross-layer impact**: Update `.claude/CLAUDE.md##Critical-conventions` and both consumer docs
5. **Verify all links** in updated docs resolve correctly (use markdown link checker before committing)

## Analysis pipeline stages (Python engine)
1. Page extraction — `cost_estimator_project/pdf_processing/page_extraction.py`
2. Perimeter calculation — `cost_estimator_project/pdf_processing/perimeter_calculation.py`
3. Height detection (EasyOCR) — `cost_estimator_project/image_analysis/height_detection.py`
4. Composition matching — `cost_estimator_project/image_analysis/composition_finder.py`
5. Scale calibration (YOLO12 + SAM/OpenCV) — `cost_estimator_project/image_analysis/scale_calibrator.py`
6. Openings + corners detection (YOLO12) — `cost_estimator_project/digital_vision/openings_corners/opening_corner_numbers.py`

## Python virtual environments
- `cost_estimator_project/.venv` — analysis engine and its dependencies
- `.venv` (root) — Flask API (`api/requirements.txt`)
- Always use the correct venv for the layer you are working in

## Stopping services

```bash
Stop-Process -Name python, dotnet -Force -ErrorAction SilentlyContinue
```

## Troubleshooting ports

```bash
netstat -ano | findstr ":5000"
netstat -ano | findstr ":5246"
$p = Get-NetTCPConnection -LocalPort 5000 | Select -Expand OwningProcess; Stop-Process -Id $p -Force
```
