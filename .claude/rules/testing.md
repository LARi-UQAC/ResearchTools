# Testing

## Test locations
- `api/test_app.py` — Flask app init and health endpoint
- `api/test_pdf_analysis.py` — End-to-end PDF upload integration test (uses real PDFs from `cost_estimator_project/data/referenceOrders/`)
- `api/test_excel_generator.py` — Excel cost calculation validation
- `api/test_print_redirect.py` — Print capture / audit log system
- `cost_estimator_project/Test/test_scale_calibrator.py` — Stage 5 scale calibration
- `cost_estimator_project/Test/test_detection_images.py` — YOLO detection output (300 DPI, separate openings vs corners)
- `cost_estimator_project/Test/test_geometry_detector.py` — Geometric shape detection
- `cost_estimator_project/Test/test_manual_selection.py` — User-drawn region selection
- `cost_estimator_project/Test/test_composition_block_detection.py` — 16-test suite for composition block detection pipeline (Stages A–D); patches `easyocr.Reader` to avoid model loading

## How to run

```bash
# API tests (uses root .venv)
cd api
python test_app.py
python test_pdf_analysis.py      # allow 300 s — downloads ML models on first run
python test_excel_generator.py

# Analysis engine tests (uses cost_estimator_project/.venv)
cd cost_estimator_project
python -m pytest Test/test_scale_calibrator.py -v
python -m pytest Test/test_detection_images.py -v
python -m pytest Test/test_composition_block_detection.py -v   # fast — EasyOCR patched, no model load
```

## Patterns
- Integration tests hit the real Flask app — do not mock Flask or the analysis engine
- Cost formula validated: `Wall cost = (Perimeter × Height × UnitPrice) + OpeningsCost + CornersCost`
- Float comparisons use `assertAlmostEqual` with `places=2` tolerance
- Long-running tests (PDF analysis) use a 300-second timeout to account for model downloads
- Session-dependent tests create a session via `/api/analyze`, then chain subsequent calls
- Composition block detection tests patch `easyocr.Reader` via `unittest.mock.patch` before importing the module; use synthetic `TextBlock` fixtures to avoid real OCR and model I/O

## Documentation of Test Results
When adding new tests or modifying test files:
1. Update docstrings in test files to reference any related docs (e.g., formulas, validation rules)
2. If a test validates a published equation, add a comment linking to `web/CostEstimator.Web/docs/formulas/`
3. Long-running tests should document their expected timeout in a comment

Example:
```python
def test_cost_formula():
    """Validate cost calculation. See web/CostEstimator.Web/docs/formulas/canonical-equations.md#cost-calculation"""
    # Cost = (Perimeter × Height × UnitPrice) + OpeningsCost + CornersCost
    perimeter, height, unit_price = 100, 10, 50
    cost = (perimeter * height * unit_price) + 100 + 50
    self.assertAlmostEqual(cost, 50150, places=2)
```

## No CI/CD
There is no automated pipeline. Run tests manually before pushing.
