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
| `POST /cv/build` | JSON body `model`, `hqp`, `reference_year`, `target` (optional) | `{"latex", "text", "hqp"}` |

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

## CV build

`POST /cv/build` renders a researcher's narrative CV (CV-FRQ / tri-agency) plus
the consenting students' rows, copying the `/pdf/fill` pattern: ThesisTracker
calls, the service renders and returns, and keeps nothing (spec section 1).

- **Nothing is compiled here.** The route returns the `.tex` source and the
  plain text, never a PDF. Compiling LaTeX received over the network would let
  it read server files, and TeX Live would add several hundred MB to this
  `python:3.13-slim` image (C2). The PDF and the page-budget check stay local,
  through `cv_build.py compile_latex` / `check-pages`.
- **Nothing is stored.** No disk write, no body logged, no student name in any
  error or log line - errors name a row by its index only (C3).
- **Consent is mandatory for every row, whatever its date** (C6 revised,
  operator 2026-10-08). A row with no `consent_cv` is refused with `422`
  naming the row index; so are a future-dated `consent_cv`, an impossible
  calendar date, `start` after `end`, or `end` after `reference_year`. The
  window (`end` null, or `end` year inside it) only decides whether a row
  prints under the recent or the archive heading - it was never a consent
  exemption. The window itself is per-funder: 6 years for NSERC/tri-agency,
  5 for FRQ (`portal_variants.*.cv_window_years`), distinct from UQAC's
  unrelated 7-year data-retention period. `reference_year` is sane-ranged
  per `contribution_types.json`'s `reference_year_bounds` key (owner,
  2026-10-08: a sanity bound, not a measurement, moved into configuration
  per R0 - not a value to copy here, since a second copy would drift).
- **`consent_cv` is checked by full date, not by year alone** (owner
  decision Q1, 2026-10-08). A consent dated after December 31 of
  `reference_year`, or dated before the row's own `start`, is refused.
- **Section 2 is capped at 10 items** (owner decision Q2, 2026-10-08),
  read from `contribution_types.json`'s `sections.2.max_items` rather than
  a literal; the 11th item is refused with `422` before anything renders.
- **The row schema is closed.** `name`, `cycle`, `start`, `end`, `consent_cv`,
  and the optional `current_position` / `current_employer`; an unknown key is
  refused (C5). The model itself is closed the same way (owner decision Q3,
  2026-10-08): an unknown top-level key, an unknown item key, or a
  digit-shaped stray section key (such as `"4"` instead of `"1"`/`"2"`/`"3"`)
  is refused with the key named in the response - a key is the model's own
  fixed vocabulary, not student data. The one exception: a *non-digit*
  section key is refused without being named, since it can itself be
  caller-controlled free text.
- **`prose_file` is refused.** A request whose model carries a `prose_file` key
  is refused with `422` before any disk access, since a request body must
  never pick a file on the server (C4, R24). Run
  `cv_build.py inline --model <cv_model.json> --out <file.json>` locally first
  to turn a model that uses `prose_file` into one with inline `prose`.
- **Section prose is raw LaTeX, trusted by design - an accepted risk, not a
  gap.** Student rows are escaped; a model's own section 1/3 prose is not,
  so a `\input`/`\write18`-style command in it reaches the returned `.tex`
  verbatim. Accepted because until TT-13 only the researcher can write that
  prose. Never compile a model whose source is not trusted, and revisit a
  control (strip or allowlist) once TT-13 widens who can supply the model.

## Personal information

The service never persists a request body and never logs a field value. Nothing
is stored between requests, aside from the signing certificate.

## Signing

The default provider is `self-signed`, which is a development credential.
Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES signature is unverified. Switch providers with
`FORM_SERVICE_SIGNING_PROVIDER` once that is answered.
