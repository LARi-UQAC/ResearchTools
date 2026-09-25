# form-service

Transport for the `form-service` skill: fill, sign, and validate PDF forms over
HTTP, so ThesisTracker calls one service instead of shelling out to Python. The
service holds no catalogue: which forms exist and what their fields mean is
ThesisTracker's own record (TT-8/TT-9).

## Run it locally, no Docker

```bash
export FORM_SERVICE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export FORM_SERVICE_CERT_DIR=out/form-service/certs
uvicorn app.main:app --host 127.0.0.1 --port 8081 --app-dir deploy/form-service
```

The development bind is `127.0.0.1`, never `0.0.0.0`.

## Run the stack

```bash
cp deploy/.env.example deploy/.env   # then fill FORM_SERVICE_KEY and POSTGRES_PASSWORD
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build
```

Inside the container the process binds `0.0.0.0`, because it is reachable only on
the compose network behind Caddy, and the published port is bound to
`127.0.0.1:8081` on the host. Those are two different statements and both are
deliberate.

## Authentication

Every route except `GET /health` requires `X-Form-Service-Key`. The comparison is
constant time. The service refuses to start when `FORM_SERVICE_KEY` is unset or
shorter than 32 characters, so an unauthenticated deployment is not reachable by
mistake. The secret never appears in a log or an error body.

There is no CORS middleware: a browser never calls this API.

## Endpoints

| Method and path | Request | Returns |
|---|---|---|
| `GET /health` | none | `{"status": "ok"}` |
| `POST /pdf/widgets` | raw PDF body | `{"widgets": [{name, name_hex, type, page, rect, on_states, readonly}]}` |
| `POST /pdf/fill` | `multipart/form-data`: `pdf` file, `values` JSON object, `flatten_fields` JSON array (optional) | `application/pdf`, headers `X-Form-Filled`, `X-Form-Flattened` |
| `POST /pdf/sign` | raw PDF body; query `field`, `reason` (both optional) | `application/pdf`, header `X-Form-Signature-Field` |
| `POST /pdf/validate` | raw PDF body | `{"signatures": [{field, intact, valid, trusted}]}` |
| `GET /publications` | query `author`, `count` (max 25), `refresh` | `{"query", "author", "publications", "fetched_at", "cached"}` |

Status codes: `401` no or wrong key, `409` a signing refusal (nothing signable,
already signed, or ambiguous which field), `413` body over the cap, `422` not a
PDF or a fill refusal (unknown field, bad checkbox value, malformed JSON), `429`
the publications rate limit is exhausted, `503` Scopus unreachable or
unconfigured, `404` the author was not found in Scopus.

## Publications

`GET /publications` is the one route with a policy of its own. The Scopus key,
the request throttling, and the approved-publisher list all stay in this
service; ThesisTracker receives plain JSON with a per-entry
`approved_publisher` flag and never reaches Elsevier. A venue outside the
approved list is **flagged, never dropped**, since a silent drop would hide a
real publication from a cohort report. An unreachable or unconfigured Scopus
answers `503`, never an empty list, because an empty list reads as "this
person has never published". `count` is capped at 25, not a round 50: Scopus's
STANDARD view refuses a page above 25 with HTTP 400. A cache hit costs no
Scopus quota, so a cohort report over an already-seen roster makes no network
call at all.

## Personal information

The service never persists a request body and never logs a field value. Nothing
is stored between requests, aside from the signing certificate.

## Signing

The default provider is `self-signed`, which is a development credential.
Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES signature is unverified. Switch providers with
`FORM_SERVICE_SIGNING_PROVIDER` once that is answered.
