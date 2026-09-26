# ThesisTracker Integration

Chapter 09 of the ResearchTools manual. Back to [table of contents](../../README.md).

This repository is one half of a two-repository system. The other half,
`JdUmuhoza/ThesisTracker`, is where the form catalogue, field maps, and the student-facing
UI/UX live (see the 2026 roadmap item in [00-purpose.md](00-purpose.md)). Neither repository's
`.claude/CLAUDE.md` or this manual duplicates that project's own documentation; this chapter
is only the map of where the two meet, so the relationship stays discoverable instead of
being findable only by reading `Architecture.md` prose.

## Two files named alike, two different scopes

- **[Architecture.md](../../Architecture.md)** — this repository's own agent/skill/command
  architecture, seven layers, entirely internal to ResearchTools.
- **[NEW_ARCHITECTURE.md](../../NEW_ARCHITECTURE.md)** — the shared architecture document for
  the UQAC form engine, the system the two repositories make up together. It is committed
  identically to `main` in both repositories (byte-for-byte, checked by `sha256sum`), so either
  checkout tells the whole story. It carries the twenty planned units (`RT-*` on this side,
  `TT-*` on ThesisTracker's), their delivery status, and the data model and lifecycle both
  sides agree on. That content is deliberately not repeated here: a second copy is exactly the
  kind of drift this manual split exists to avoid (see [00-purpose.md](00-purpose.md)).

## The boundary: `form-service`

The dependency between the two systems runs one way only: **ThesisTracker calls the form
service, never the reverse.** ThesisTracker itself does not belong to this repository's own
component graph and is a separate system.

`deploy/form-service/` (the `form-service` skill, chapter [04](04-skills.md)) wraps the PDF
ingest, widget-dump, filling, and PAdES-signing scripts in a stateless FastAPI application, so
ThesisTracker calls one HTTP service (`/pdf/widgets`, `/pdf/fill`, `/pdf/sign`, `/pdf/validate`,
plus `GET /publications`) instead of shelling out to Python itself. The service is reached only
over a private network behind a shared secret compared in constant time, and refuses to start
when that secret is unset or too short; nothing is persisted beyond a certificates volume and a
disk-cached, rate-limited publications cache. Full diagram and detail: `Architecture.md`,
"Layer 7 - Deployment (form-service HTTP API)".

## What lives where

| Concern | Owner |
|---|---|
| PDF ingest contract, widget dump, filling, PAdES signing, HTTP transport | ResearchTools (`form-service` skill + `deploy/form-service/`) |
| Form catalogue, field maps, student profile | ThesisTracker |
| Twenty-unit delivery plan, shared data model, cross-repo decisions | `NEW_ARCHITECTURE.md` (both repos) |

When a plan changes something both sides depend on, `NEW_ARCHITECTURE.md` is the file that
records it — update it there, in both checkouts, rather than in this manual.
