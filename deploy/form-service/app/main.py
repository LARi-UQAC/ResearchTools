"""
main.py - The form-service HTTP API.

Pure transport: every decision lives in the form-service skill, reached
through skill_bridge. Every route except /health requires the shared secret.
There is no CORS middleware, because a browser never calls this API and a
wildcard policy on a route that accepts a body is forbidden by
.claude/rules/security.md.

Nothing here logs a field value, a profile, or the secret: method, path,
status, and duration only.
"""

import json
import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from . import skill_bridge
from .config import load_settings
from .security import require_service_key

logger = logging.getLogger(__name__)

app = FastAPI(title="form-service", version="1.0.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log method, path, status, and duration. Never a body, never a header value."""
    started = time.monotonic()
    response = await call_next(request)
    logger.info("[FORM-SERVICE] %s %s -> %s in %.0f ms", request.method,
                request.url.path, response.status_code,
                (time.monotonic() - started) * 1000)
    return response


async def _pdf_body(request: Request) -> bytes:
    """Read a raw PDF request body, enforcing the size cap before any PDF work."""
    settings = load_settings()
    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Request body exceeds the configured maximum")
    if not body.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Body is not a PDF")
    return body


def _parse_json_field(raw: str, name: str) -> Any:
    """Parse a form field that carries JSON, mapping a bad payload to 422."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{name} is not valid JSON: {exc}") from exc


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness probe. The only route with no shared-secret requirement."""
    return JSONResponse(content={"status": "ok"})


@app.post("/pdf/widgets", dependencies=[Depends(require_service_key)])
async def widgets(request: Request) -> dict[str, Any]:
    """List every AcroForm widget in the uploaded PDF."""
    body = await _pdf_body(request)
    return {"widgets": skill_bridge.widgets_of(body)}


@app.post("/pdf/fill", dependencies=[Depends(require_service_key)])
async def fill(pdf: UploadFile = File(...), values: str = Form(...),
              flatten_fields: str = Form(default="[]")) -> Response:
    """Fill an uploaded form and stream the PDF back. Counts travel in headers."""
    settings = load_settings()
    body = await pdf.read()
    if len(body) > settings.max_body_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Request body exceeds the configured maximum")
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Body is not a PDF")

    parsed_values = _parse_json_field(values, "values")
    parsed_flatten = _parse_json_field(flatten_fields, "flatten_fields")

    try:
        filled, result = skill_bridge.fill_to_bytes(body, parsed_values, parsed_flatten, settings)
    except skill_bridge.fill_form.FillError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return Response(content=filled, media_type="application/pdf", headers={
        "X-Form-Filled": str(result["filled"]),
        "X-Form-Flattened": str(result["flattened"]),
    })


@app.post("/pdf/sign", dependencies=[Depends(require_service_key)])
async def sign(request: Request, field: str | None = None,
              reason: str | None = None) -> Response:
    """Sign an uploaded filled form and stream the signed PDF back."""
    body = await _pdf_body(request)
    settings = load_settings()
    chosen_reason = reason or skill_bridge.sign_form.DEFAULT_REASON
    try:
        signed, result = skill_bridge.sign_bytes(body, field, chosen_reason, settings)
    except skill_bridge.sign_form.SigningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return Response(content=signed, media_type="application/pdf", headers={
        "X-Form-Signature-Field": str(result["field"]),
    })


@app.post("/pdf/validate", dependencies=[Depends(require_service_key)])
async def validate(request: Request) -> dict[str, Any]:
    """Report the validation status of every signature in the uploaded PDF."""
    body = await _pdf_body(request)
    return {"signatures": skill_bridge.validate_bytes(body)}
