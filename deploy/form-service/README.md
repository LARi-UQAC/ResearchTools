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

Status codes: `401` no or wrong key, `409` a signing refusal (nothing signable,
already signed, or ambiguous which field), `413` body over the cap, `422` not a
PDF or a fill refusal (unknown field, bad checkbox value, malformed JSON).

## Personal information

The service never persists a request body and never logs a field value. Nothing
is stored between requests, aside from the signing certificate.

## Signing

The default provider is `self-signed`, which is a development credential.
Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES signature is unverified. Switch providers with
`FORM_SERVICE_SIGNING_PROVIDER` once that is answered.
