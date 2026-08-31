# NEW_ARCHITECTURE.md - the UQAC form engine

Shared architecture document for the two repositories that make up the UQAC form engine:
**ResearchTools** (`LARi-UQAC/ResearchTools`) and **ThesisTracker** (`JdUmuhoza/ThesisTracker`).
The same file is committed to `main` in both, so either checkout tells the whole story.

**Status: in progress. 7 of 20 units delivered.** Twenty branches carry one plan document each,
and twenty-one issues track them. Written 2026-07-29.

Delivered: TT-0, TT-1, TT-2, TT-8, TT-9 and TT-12 are merged to `main` in ThesisTracker; RT-1 is
on `feat/uqac-forms-registry` here. TT-7 (email one-time codes) is built but **excluded by
design** until UQAC provides a mail relay: merging it would replace the only working sign-in with
a code nothing can deliver. It also carries the `direction` role, so it gates TT-10.

This file is meant to be identical on `main` in both repositories. It had drifted: this copy still
read "planned, not implemented" while six units were live in production.

Outcome when all twenty units land: a professor admits a student and their whole timeline appears,
from the first administrative form to the final thesis deposit; a superuser registers an official
UQAC PDF and defines its rules; the student signs in with a one-time code sent to their
institutional address and fills the form, pre-filled from what they entered last time; they sign it,
the professor corrects it and sends it back for the student's approval, the Direction countersigns
or returns it, and the completed form is emailed to the office that owns it. ResearchTools audits
the student's papers, reports and thesis and returns a correction plan the student works through
inside ThesisTracker. All of it on institutional Docker infrastructure, with automatic detection
when UQAC silently replaces a form at the same URL.

**Revision note, 2026-07-29.** Four decisions changed after the first fourteen plans were written,
and this document is the authority on all four. Every affected plan carries a scope-change block.

1. **Sign-in is an email one-time code**, not GitHub OAuth (unit TT-7).
2. **The form catalogue, the workflow rules, the field maps and the student data live in the
   ThesisTracker database**, not in a ResearchTools registry: ResearchTools is skills, agents and
   commands for a thesis, a paper, a review or a report, it cannot track a form and it cannot know
   what fills one. Its service is reduced to stateless PDF mechanics (sections 3 and 4, units TT-8
   and TT-9).
3. **A form can go backwards.** The professor sends it back to the student for a final approval, and
   the Direction sends it back to the professor when something is wrong. This is not a convenience:
   a `modify` after a `sign` means the earlier signature no longer covers the final content, so the
   engine **forces** a return rather than offering it (section 5.1, unit TT-10).
4. **A completed form is submitted by email to the office that owns it**, and each form definition
   carries its own destination address (sections 5.2 and 11, units TT-8 and TT-10).

Two units are new with this revision: **TT-11**, the student timeline created on admission
(section 7), and **TT-12**, the intake of ResearchTools correction plans (section 8).

---

## 1. Why this shape

`README.md` TODO item 3 in ResearchTools targeted, for end of 2026, a Thesis-Tracker with user
login, a database, paperwork and forms, submission tracking, and mindmaps, with an open question
about n8n. The original proposal was Plane plus n8n plus Graphify plus a local LLM, replacing
ThesisTracker. Investigation rejected that shape.

| Question | Decision | Why |
|---|---|---|
| Plane as system of record | **Rejected** | ThesisTracker already has tested per-row RBAC that Plane Community cannot express. Migrating would trade it for one project per student and discard the nine-status domain semantics. Plane granular access control is Enterprise-only, and Plane webhooks do not cover Pages, which kills the "Pages edit triggers the mindmap" design. |
| Graphify for mindmaps | **Rejected** | Code-first knowledge-graph tool, not a research-notes concept extractor. The need is already served by the markmap view, the Obsidian vault, and `extract-futureworks` mine mode. |
| n8n now | **Deferred to Phase 3** | Every automation currently wanted is one cron and one script. Entry criteria in section 14. |
| Where the form catalogue, the rules, the field maps and the student data live | **The ThesisTracker database, edited in the UI** | Only ThesisTracker writes that database. ResearchTools is skills, agents and commands operating on a thesis, a paper, a review or a report: it cannot track a form and cannot know the information that fills one. |
| What the ResearchTools form service does | **Stateless PDF mechanics only** | Enumerate the widgets of a PDF it is handed, write given values into given fields, sign a named signature field, validate a signature. No registry, no map, no profile, no state between requests. Python holds this because `pypdf` and `pyhanko` have no Node equivalent. |
| Who may add a form or change its rules | **`owner` (superuser) or `direction`** | Every PDF comes from the University administration, so a professor neither adds forms nor rewrites the rules of an official document. A professor uses them. |
| The Direction de programme | **A fourth role that signs in the app** | Signature only: the Direction never writes a field. They see a signing queue and the rules editor, never a student's tracker. |
| Fields repeated on every form (name, address, program) | **Filled automatically from a profile store, written back on every edit** | A student types their address once. When a student or a professor corrects a value while filling, the correction is saved and becomes the default for the next form. |
| A form that needs correcting after it was signed | **Sent back, and the engine forces it** | A `modify` after a `sign` leaves the earlier signature valid over its own revision but no longer covering the final content. So the professor's correction routes the form back to the student for approval automatically, and the Direction can return it to the professor. Forward-only would produce documents whose signatures no longer mean what they appear to mean. |
| Getting the finished form to the office | **Emailed to a destination stored on the form definition** | Each official form belongs to a different office. The address is part of the definition, editable by an `owner` or the `direction`, and never supplied by the client at submission time. |
| What happens when a student is admitted | **The whole timeline is created from a template** | Forms, reports, seminar, papers per contribution, and the thesis milestones from initial to final deposit. The subject-calendar form then shifts the dates, because its values are already in the database. A student should not have to discover what is expected of them one deadline at a time. |
| Who validates a paper, a report or a thesis | **ResearchTools, which returns a correction plan** | Its auditors already produce exactly that: `paper-auditor`, `thesis-auditor`, `scopus-auditor`, `submit-checker`, `scholar-evaluation`. ThesisTracker ingests the plan and tracks the findings as a worklist; it does not re-implement the audit. |
| GitHub OAuth for sign-in | **Replaced by an email one-time code (TT-7)** | It required every user to hold a GitHub account, a handle is not an identity a supervisor recognizes, and the OAuth callback was the one step of the Vercel retirement that could not be rolled back instantly. The institutional email address becomes the username; `users.login` stays the primary key, so no data row moves. |
| Personal email (gmail, hotmail) | **Recovery and security notices only, never a login** | Rebinding an institutional address is an `owner` action, so a compromised personal mailbox alone cannot take over an account. |
| Which domains may sign in | **A configurable allowlist with no default** | `ALLOWED_EMAIL_DOMAINS`, and the application refuses to start when it is empty. A wrong default would silently admit a domain nobody vetted. |
| Runtime | **Dual-target, converging to Docker** | Vercel sat at 12 of 12 Hobby functions, is licensed for personal non-commercial use, and would place matricules and signed expense claims on United States infrastructure under Quebec Law 25. |
| PDF library | **`pypdf`, BSD-3** | PyMuPDF is AGPL-3.0 and stays isolated in the `extract-statistic` skill. The deployable container carries no AGPL. |
| Signature | **PAdES, pluggable signer, self-signed development default** | Unblocks implementation while the Décanat and SRF acceptance question stays open. |
| Docker host | **Undecided by choice** | Compose and Caddy read the hostname from the environment. Chosen before real data loads, not before build. |

---

## 2. System context

```mermaid
flowchart TB
  subgraph People["People"]
    STU["Student<br/>fills, signs"]
    PROF["Professor<br/>corrects, signs"]
    DIRE["Direction<br/>countersigns, owns the rules"]
    SUPER["Superuser<br/>registers forms, owns the rules"]
  end

  subgraph TT["ThesisTracker - system of record"]
    APP["React SPA + API<br/>papers, journal, ideas, meetings,<br/>mindmap, forms"]
    CAT["Form catalogue<br/>definitions, rules, field maps,<br/>submission address"]
    PROF_STORE["Profile store<br/>shared field values, write-back"]
    TIME["Student timeline<br/>forms, reports, seminar,<br/>papers, thesis"]
    PLANS["Correction plans<br/>findings as a worklist"]
    DB[("Postgres<br/>row-level ownership")]
  end

  subgraph RT["ResearchTools"]
    SVC["PDF service<br/>widgets, fill, sign, validate<br/>stateless"]
    AUD["Auditors in Claude Code<br/>paper, thesis, review,<br/>submitcheck, ScholarEval"]
    SCOPUS["scopus skill<br/>metadata and validation"]
  end

  subgraph Outside["Outside"]
    UQAC[("www.uqac.ca<br/>official PDF forms")]
    ELS[("Elsevier Scopus API")]
    MAIL[("Institutional SMTP relay")]
    OFFICE[("Decanat and SRF<br/>submission mailboxes")]
  end

  STU --> APP
  PROF --> APP
  DIRE --> APP
  SUPER --> APP
  APP <--> DB
  CAT --- DB
  PROF_STORE --- DB
  TIME --- DB
  PLANS --- DB
  APP -->|"download, fingerprint,<br/>drift check"| UQAC
  APP -->|"shared secret, private network<br/>PDF bytes plus values"| SVC
  APP -->|"one-time sign-in code"| MAIL
  APP -->|"the completed signed form"| MAIL
  MAIL --> OFFICE
  APP -->|"publications, via the service"| SVC
  SVC --> SCOPUS
  SCOPUS -->|"validated metadata, DOI"| ELS
  PROF -->|"runs an audit"| AUD
  AUD --> SCOPUS
  AUD -.->|"the correction plan,<br/>uploaded as an artifact"| PLANS
  PLANS -.->|"findings to work through"| STU

  classDef tt fill:#DBEAFE,stroke:#1E40AF,color:#14181F
  classDef rt fill:#D1FAE5,stroke:#065F46,color:#14181F
  classDef out fill:#F3F4F6,stroke:#6B7280,color:#14181F
  class APP,DB,CAT,PROF_STORE,TIME,PLANS tt
  class SVC,AUD,SCOPUS rt
  class UQAC,ELS,MAIL,OFFICE out
```

**Dependency direction is one way: ThesisTracker depends on ResearchTools, never the reverse.**
ThesisTracker never calls Elsevier and never holds the Scopus key. The key, the throttling, and the
approved-publisher policy stay in ResearchTools. Note what moved with the revision: ThesisTracker
now downloads and fingerprints the UQAC PDFs itself, because it owns the catalogue, and a download
plus a SHA-256 is a `fetch` in Node.

---

## 3. The two repositories

| | ResearchTools | ThesisTracker |
|---|---|---|
| Role | Stateless PDF mechanics, plus the academic toolbox that audits the work | System of record: catalogue, rules, data, timeline, interface |
| Stack | Python 3.13, FastAPI, `pypdf`, `pyhanko`, plus the Claude Code agents | Node 20 ESM, React 19, Vite 8, Postgres |
| Visibility | Public | Private |
| Knows about | What a PDF widget is, how to write a value into one, how to sign, and how to judge a paper or a thesis against the literature | Which forms exist, who fills what, in what order, with which data, and what is expected of each student by when |
| Does **not** know | Which forms exist, who a student is, what any field means, how anyone signs in, what a deadline is | How to parse a PDF, how to validate a reference |
| State it keeps | None per request. A signing certificate, nothing else | Everything: catalogue, rules, maps, profiles, documents, workflow position, timeline, findings |
| New surface | `.claude/skills/uqac-forms/` (PDF mechanics), `deploy/form-service/` | `api/_lib/routes/`, `server/`, the catalogue, the profile store, the workflow engine, the timeline, correction-plan intake, email-code sign-in |
| Direction of travel | Produces artifacts: filled bytes, signed bytes, an improvement plan | Consumes them, tracks them, and shows them to a person |

The boundary rule, corrected: **ResearchTools manipulates PDF bytes, ThesisTracker knows what they
mean.** A form code, a profile key, a role, an email address, and an ownership guard never appear in
ResearchTools code. A `pypdf` call never appears in ThesisTracker code.

The consequence worth stating plainly: **the ResearchTools service is a function, not a system.**
Hand it a PDF and a set of field values and it hands back a PDF. It cannot answer "which forms
exist", "who signs this next", or "what is this student's address", because it holds nothing. That
is what makes it safe to deploy publicly-sourced code beside private student data: it has no data.

Identity is entirely ThesisTracker's. The service authenticates a **machine** with a shared secret
and never sees a user, a session, or an email address.

---

## 4. Runtime topology

One compose file, one network, one public door.

```mermaid
flowchart TB
  NET["Internet"] -->|":80, :443"| CADDY["caddy<br/>hostname from APP_HOST"]

  subgraph COMPOSE["Docker Compose network"]
    CADDY --> APP["app<br/>ThesisTracker<br/>Express + built SPA<br/>:3000"]
    APP --> DB[("db<br/>Postgres 17<br/>catalogue, rules, maps,<br/>profiles, documents")]
    APP -->|"X-Form-Service-Key<br/>PDF bytes plus values"| FS["form-service<br/>ResearchTools FastAPI<br/>:8080 - stateless"]
    FS --> CERT[("certs volume<br/>signing material only")]
  end

  APP -.->|"form download<br/>and drift check"| UQAC[("www.uqac.ca")]
  APP -.->|"one-time sign-in code"| MAIL[("SMTP relay")]
  FS -.->|"publications, cached<br/>and rate limited"| ELS[("Scopus API")]

  HOST["Host loopback<br/>127.0.0.1:3001"] -.-> APP

  classDef private fill:#FEF3C7,stroke:#B45309,color:#14181F
  classDef public fill:#DBEAFE,stroke:#1E40AF,color:#14181F
  class FS,DB,CERT private
  class CADDY public
```

Deliberate properties:

- **The form service has no published host port.** It is reachable only on the compose network, so
  the shared secret never crosses a public interface.
- **The form service keeps one volume, for signing material.** It no longer caches PDFs or stores
  field maps: those are rows in the ThesisTracker database.
- The app is published on `127.0.0.1` only; everything public goes through Caddy.
- Every hostname comes from the environment. No domain is hardcoded anywhere.
- The `pgvector` extension is needed by RT-7 only. It rides whichever Postgres the deployment
  gives it; the compose files are written so a merged or a separate instance both work.

Vercel remains the second front door until retirement (section 14). One implementation, two doors:
`api/_lib/routes/*.js` holds every handler, a thin Vercel entry dispatches on method plus query
parameter, and the Express app mounts the same handlers on REST paths.

```mermaid
flowchart LR
  subgraph ONE["One implementation"]
    R["api/_lib/routes/&lt;resource&gt;.js<br/>named handlers<br/>list, get, create, update,<br/>remove, fill, sign, advance"]
  end
  V["api/&lt;resource&gt;.js<br/>Vercel dispatcher<br/>method + query param"] --> R
  E["server/index.js<br/>Express adapter<br/>REST paths"] --> R
  R --> L["_lib: auth, scope, crud, entities, db,<br/>form-rules, profile-store, form-service client"]
```

---

## 5. Per-form workflow rules

**Every registered PDF carries its own rules.** They are defined once, when the PDF is added to the
catalogue, and they say who touches the form, in what order, and what each of them may do.

### 5.1 The capability model

A form definition owns an ordered list of steps. Each step names one **actor role** and grants a
subset of five capabilities:

| Capability | Meaning | Enforced by |
|---|---|---|
| `fill` | may write a field that is currently **empty** | the route rejects a write to a non-empty field |
| `modify` | may **overwrite** a field that already has a value, to correct an error | the route rejects any write when absent |
| `sign` | must sign the signature field named by the step | the step cannot complete without it |
| `return` | may send the form back to an earlier step, with a reason that is recorded | the route rejects a return by a step that lacks it, and a return with no reason |
| `submit` | performs the final submission by email to the destination on the definition | only a step with this capability may submit, and only when every earlier step is complete |

What each actor does, in the University's own terms:

| Step | Actor | `fill` | `modify` | `sign` | `return` | What they actually do |
|---|---|---|---|---|---|---|
| 1 | `student` | yes | **yes, own situation only** | yes | no | Sees the form already filled in. Adds or corrects anything about their own situation, then signs. |
| 2 | `professor` | yes | yes | yes | **yes, to the student** | Corrects an error, sends it back for the student's approval, then flags it forward. |
| 3 | `direction` | no | no | yes | **yes, to the professor** | Countersigns, or returns it to the professor when something is wrong. |

Two things in that table are new and both matter.

**The student may modify, not only fill.** The form arrives pre-filled from the profile store, and a
pre-filled value is not necessarily right: an address changes, a program code was entered wrongly
last year. The student corrects anything about their **own situation**, which in practice means every
field their step owns. What they cannot touch is a field belonging to the professor's step or the
Direction's.

**A form can go backwards, and sometimes it must.** This is the part that is not a preference:

> A PAdES signature covers the revision of the document that existed when it was applied. When the
> professor modifies a field at step 2 that the student signed at step 1, the student's signature
> stays cryptographically **valid over its own revision** but no longer **covers the final content**.
> A viewer reports exactly that: signed, and altered since signing.

So the engine does not leave the return to the professor's judgement. **When a step modifies a field
that an earlier step signed, the instance is routed back to that signer automatically**, and cannot
advance until they approve and re-sign. The professor's "send back to the student" is therefore the
normal path after any correction, not an exception, and the professor's own step is not complete
until the student has approved.

A `return` that follows no modification is still available and still useful: the Direction returning
a form to the professor because a date is wrong, or the professor returning it to the student because
a required attachment is missing. Every return carries a reason, and the reason is shown to the person
it lands on. A return with no reason is refused, because "sent back" with no explanation is a message
nobody can act on.

Two guards keep the loop from being abused:

- A step may only return to an **earlier** step, never forward. Forward movement is signing.
- A return is recorded in the audit trail with its reason, so a form that has bounced three times
  shows why each time.

### 5.2 Three worked examples, each ending in a submission

Every form ends the same way: **submitted by email to the office that owns it.** The destination is
`form_definitions.submission_email`, set when the form is registered.

```mermaid
flowchart LR
  subgraph A["Thesis subject registration - three signatures"]
    A1["1. student<br/>fill + modify + sign"] --> A2["2. professor<br/>fill + modify + sign<br/>return to student"]
    A2 -.->|"returned for approval"| A1
    A2 --> A3["3. direction<br/>sign, return to professor"]
    A3 -.->|"issue found"| A2
    A3 --> A4["4. professor<br/>submit by email<br/>decanat-mth@uqac.ca"]
  end
  subgraph B["Deposit authorization - professor only"]
    B1["1. professor<br/>fill + modify + sign"] --> B2["2. professor<br/>submit by email"]
  end
  subgraph C["Expense claim - two signatures"]
    C1["1. student<br/>fill + modify + sign"] --> C2["2. professor<br/>modify + sign<br/>return to student"]
    C2 -.->|"returned"| C1
    C2 --> C3["3. professor<br/>submit by email<br/>srf-depenses@uqac.ca"]
  end
```

The dotted edges are returns. In example A the professor correcting a student field sends the form
back automatically, because the student's signature no longer covers the corrected content.

A form with a single professor step never appears in a student's list at all. A form whose first step
is the student's appears for the student and only reaches the professor when the student completes
their step.

### 5.3 The submission step

The last step of every definition carries `submit`. It is deliberately **a step with an actor, not an
automatic side effect of the last signature**, for one reason: emailing a signed official document to
an administrative office is outward-facing and cannot be undone. A person presses it.

| Property | Decision |
|---|---|
| Where the address lives | `form_definitions.submission_email`, plus optional `submission_cc`. Set at registration, editable by `owner` or `direction` only. |
| Who may change it | Nobody else. **The client never supplies a destination at submission time**, so no caller can email an official signed form to an address of their choosing. |
| What is sent | The final signed PDF, and nothing else. No profile data in the body. |
| What is recorded | A `form_step_events` row with `action = 'submit'`, the destination, the message id from the relay, and the document SHA-256. |
| On failure | The instance stays `AwaitingSubmission` and the failure is shown with the relay's message. A retry is the same button. Nothing is silently marked submitted. |
| Can it be sent twice | No. Once a submission is recorded, the step is complete and the button is gone. A resend is an `owner` action that records why. |

The relay is the same institutional SMTP relay that carries the sign-in codes (section 13), so a
signed official form never transits a third-party mail vendor.

### 5.4 Who defines the rules

**`owner` (superuser) or `direction`. Never a professor, never a student.** Every PDF comes from the
University administration, so a professor neither adds a form nor rewrites the rules of an official
document; they use them.

Registration is a guided flow, because the rules cannot be guessed from the file:

```mermaid
sequenceDiagram
  autonumber
  participant U as Superuser or Direction
  participant A as ThesisTracker API
  participant F as PDF service
  participant D as Postgres

  U->>A: upload the official PDF, its source URL,<br/>and the office address it is submitted to
  A->>A: validate: %PDF magic, size cap, https source,<br/>a deliverable submission address
  A->>F: POST /pdf/widgets (the bytes)
  F-->>A: every widget: name, type, page, rect, on-states
  A->>D: store the definition, its SHA-256, the submission address,<br/>and the raw widget list
  A-->>U: "56 fields found. Map them, then define the steps."
  U->>A: bind each field to a profile key, a literal, or "not filled"
  U->>A: define the ordered steps: actor, fill, modify, sign,<br/>return target, signature field, and which step submits
  A->>A: validate: signature fields exist, actor roles exist, return target is earlier,<br/>exactly one step submits, last step submits, and each step has capability
  A->>D: store the field map and the step definitions, status active
  A-->>U: the form is available to the roles its first step names
```

Nothing is inferred. A field nobody fills is marked as such explicitly, so a blank on an official
form is a decision on the record rather than an oversight. The submission address is asked for at
registration rather than at submission time, so nobody has to know it under pressure and no caller
can choose it.

---

## 6. Shared fields and the profile store

Many forms ask for the same things: name, permanent code, address, program, supervisor. A student
types them once.

```mermaid
flowchart LR
  P[("profile_values<br/>owner_login, key, value")] -->|"pre-fill"| F["Fill a form<br/>step 1"]
  F -->|"student corrects the address"| W["write-back"]
  W --> P
  P -->|"pre-fill, now corrected"| F2["Fill the next form"]
  F3["Professor corrects the program<br/>at step 2"] -->|"write-back"| P

  classDef store fill:#D1FAE5,stroke:#065F46,color:#14181F
  class P store
```

Rules, each enforced server-side:

- A field bound to a profile key is **pre-filled** from the store, so the student sees it already
  entered and only corrects it if it is wrong.
- **Any `fill` or `modify` writes back.** A student correcting their address, or a professor
  correcting a program code, updates the store and therefore every later form.
- The write-back is **owner-scoped**: it updates the profile of the student the form belongs to,
  never the profile of the person doing the editing. A professor correcting a student's address
  writes the student's profile, and the audit trail records who did it.
- Every change is versioned, so "the address was wrong on the form I submitted in March" is an
  answerable question.
- A field bound to a literal or marked as not filled is never written back.

---

## 7. The student timeline

**When a professor admits a student, the whole timeline appears.** Not a blank tracker: the forms, the
reports, the seminar, one entry per planned paper, and the thesis milestones from initial to final
deposit. A doctoral candidate should not have to discover what is expected of them one deadline at a
time.

```mermaid
flowchart TB
  ADMIT["Professor approves a pending user<br/>role becomes student"] --> INST["Instantiate the timeline<br/>from the template for their cycle"]
  INST --> ITEMS

  subgraph ITEMS["timeline_items, one row each"]
    F["Administrative forms<br/>subject registration, work plan,<br/>deposit authorization"]
    R["Reports<br/>annual progress"]
    S["Seminar"]
    P["Papers, one per contribution<br/>C1..C5 from the mindmap<br/>first submission to final"]
    T["Thesis<br/>initial deposit to final deposit"]
  end

  CAL["The subject-calendar form<br/>is completed and signed"] -->|"its dates are already<br/>in the database"| SHIFT["Shift the timeline<br/>to the real dates"]
  SHIFT --> ITEMS
  PROJ["The thesis project definition<br/>on the same form"] --> SHIFT

  classDef gen fill:#DBEAFE,stroke:#1E40AF,color:#14181F
  class INST,SHIFT gen
```

### 7.1 Where the dates come from

Three sources, in increasing authority:

| Source | Gives | Authority |
|---|---|---|
| The template for the student's cycle | the shape: which items exist and their offsets from admission | lowest, a starting point |
| The **subject-calendar form**, once completed | the real dates, and the thesis project definition | **overrides the template** |
| A professor or the student editing an item | one date at a time, with a reason | highest, and recorded |

The calendar form needs no parser and no upload: **its values are already rows.** A form's field map
binds each widget to a profile key, so once the calendar form is filled, the dates are in the
database and the timeline reads them directly. That is a direct benefit of having put the form data
in ThesisTracker rather than in a ResearchTools registry.

### 7.2 What a timeline item is

One row per expected thing, whatever kind it is, so one view shows the whole degree:

| Kind | Links to | Completed when |
|---|---|---|
| `form` | a `form_definitions.code`, and its instance once created | the instance is `Submitted` |
| `report` | a document | the document is accepted |
| `seminar` | a date and a title | marked done by the professor |
| `paper` | a `papers` row, and therefore a contribution `C1` to `C5` | the paper reaches `Published` |
| `thesis` | a milestone, `initial_deposit` or `final_deposit` | the deposit is recorded |

The paper items come from the contributions the mindmap already draws, so the timeline and the
mindmap are two views of one plan rather than two plans that drift apart. A paper item tracks the
whole arc the `papers` entity already models, from first submission to final acceptance, through the
nine statuses that exist today.

### 7.3 What the timeline is not

- **It is not a scheduler.** Nothing runs because a date arrives. Deadline reminders are Phase 3
  (section 14) and need one cron, not a workflow engine.
- **It is not a gate.** A late item is late and visible; it does not block a form or a signature. The
  administration's rules gate those, not this timeline.
- **It is not fixed.** A thesis changes shape. Every item is editable by the professor, with the
  change recorded, and the template only ever seeds.

---

## 8. Validation and correction plans

**ResearchTools validates, ThesisTracker tracks.** This is the same boundary as everywhere else, applied
to academic content instead of forms.

```mermaid
sequenceDiagram
  autonumber
  participant P as Professor in Harness
  participant RT as ResearchTools auditors
  participant A as ThesisTracker API
  participant S as Student

  P->>RT: /auditpaper, /auditthesis, /auditreview,<br/>/submitcheck, scholar-evaluation
  RT->>RT: validate every reference against Scopus,<br/>audit method, results, statistics, future works,<br/>run the deliberation panel, score with ScholarEval
  RT-->>P: an improvement plan with track-change markup,<br/>plus a ScholarEval score report
  P->>A: upload the plan against the paper, report or thesis
  A->>A: split it into findings: severity, section,<br/>the quoted passage, the recommendation
  A-->>S: a worklist, one item per finding
  S->>A: mark a finding addressed, with what changed
  A-->>P: progress per finding, and what is still open
```

### 8.1 Why the audit is not a service endpoint

The auditors are not functions. `paper-auditor` reads a whole manuscript, validates every reference
against Scopus, runs a two-round cross-model deliberation panel, scores with `scholar-evaluation`, and
pauses for a human at defined checkpoints. Running that behind an HTTP request would mean
reimplementing it as something it is not.

So the artifact crosses the boundary, not the computation: **the plan is produced in Claude Code, as
today, and ingested by ThesisTracker.** ThesisTracker turns it into findings and tracks them. It never
re-implements the audit, and it never claims a score it did not receive.

> If the intent was a live endpoint that audits on demand, say so and this section changes. The
> artifact route is what the existing agents actually support, and it is why this unit is small.

### 8.2 What a finding is

| Field | Meaning |
|---|---|
| `severity` | `critical`, `major`, `minor`, from the auditor's own classification |
| `section` | where in the work, so the student can find it |
| `quote` | the passage the auditor flagged, verbatim |
| `recommendation` | what to do about it |
| `status` | `open`, `addressed`, or `rejected` with a reason |

**A finding is never silently closed.** `rejected` needs a reason, because a student disagreeing with
an auditor is a legitimate outcome that the professor should see rather than a state to hide. And a
score is stored as received: ThesisTracker displays what ResearchTools reported and does not compute
its own.

---

## 9. The drift guard

The piece that makes the engine survive contact with UQAC. Forms can be added, modified, or
withdrawn by the administration at any time, always at the same URL. **This now lives in
ThesisTracker**, which owns the catalogue: a download and a SHA-256 comparison is a `fetch` in Node.

```mermaid
stateDiagram-v2
  [*] --> Draft: superuser uploads the PDF
  Draft --> Active: field map complete and steps defined
  Active --> Stale: scheduled check finds a SHA-256 mismatch
  Stale --> Draft: superuser re-maps the changed fields
  Active --> Retired: the administration withdraws the form
  Active --> Active: check passes

  note right of Stale
    No new form instance can be created, and no
    in-flight instance can advance. The UI greys the
    entry out and names the fields that changed.
    Silent drift producing a wrong-looking official
    form is the failure mode this must not have.
  end note
```

The check re-downloads each active definition, compares the SHA-256, and on a mismatch asks the PDF
service for the new widget list, diffs it against the stored map (added, removed, relocated fields),
marks the definition `stale`, and notifies the superuser and the Direction. An in-flight instance is
frozen rather than silently continued on a form that no longer matches its map.

---

## 10. Form instance lifecycle

A form instance walks its definition's steps, forwards by signing and backwards by returning. Status
is derived from the position, not typed in by hand, which is why the previous fixed six-status flow is
gone.

```mermaid
stateDiagram-v2
  [*] --> Draft: instance created from an active definition
  Draft --> AwaitingStep: pre-filled from the profile store
  AwaitingStep --> AwaitingStep: the current actor fills or modifies
  AwaitingStep --> StepSigned: the current actor signs
  StepSigned --> AwaitingStep: a later step exists, flagged to its actor
  StepSigned --> AwaitingSubmission: every signing step is done
  AwaitingStep --> AwaitingApproval: a modification broke an earlier signature
  AwaitingApproval --> AwaitingStep: the earlier signer approved and re-signed
  AwaitingStep --> Returned: the actor returns it, with a reason
  Returned --> AwaitingStep: it lands on the earlier step's actor
  AwaitingSubmission --> Submitted: emailed to the office on the definition
  AwaitingSubmission --> AwaitingSubmission: the send failed, retry
  Submitted --> Accepted
  Submitted --> Rejected
  Rejected --> AwaitingStep: reopened at a named step by a superuser
  AwaitingStep --> Frozen: its definition went stale
  Frozen --> AwaitingStep: the definition is active again

  note right of AwaitingApproval
    NOT a choice. A modify at step 2 of a field
    signed at step 1 leaves that signature no
    longer covering the final content, so the
    engine routes it back automatically.
  end note

  note right of Returned
    A return carries a mandatory reason and may
    only go to an EARLIER step. Forward movement
    is signing.
  end note
```

Signatures accumulate: each step's signature is a PAdES incremental update appended to the previous
one, so signature 2 does not invalidate signature 1 and the final PDF carries a verifiable chain in
step order. What a later **modification** does break is the *coverage* of an earlier signature, which
is what `AwaitingApproval` exists to repair.

`AwaitingSubmission` is a real resting state, not a formality: a form can sit there because the relay
was down. It is never marked `Submitted` until a message id comes back.

---

## 11. Data model

New tables in bold. The four original entities are unchanged, and they and the form tables share one
ownership and audit layer, which is why `crud.js`, `scope.js` and `auth.js` are not modified.

```mermaid
erDiagram
  users ||--o{ papers : owns
  users ||--o{ journal_entries : owns
  users ||--o{ ideas : owns
  users ||--o{ meetings : owns
  users ||--o{ form_instances : owns
  users ||--o{ profile_values : owns
  users ||--o{ timeline_items : owns
  users ||--o{ review_artifacts : owns
  form_definitions ||--o{ form_step_defs : "ordered steps"
  form_definitions ||--o{ form_field_map : "one row per widget"
  form_definitions ||--o{ form_instances : "instantiated as"
  form_instances ||--o{ form_step_events : "audit per step"
  form_instances ||--o{ form_documents : "filled and signed"
  timeline_templates ||--o{ timeline_template_items : "seeds"
  timeline_items ||--o| form_instances : "may track"
  timeline_items ||--o| papers : "may track"
  review_artifacts ||--o{ review_findings : "split into"

  users {
    text login PK
    text email UK "the username"
    text recovery_email
    text role "pending|student|professor|direction|owner"
    text name
  }
  form_definitions {
    text id PK
    text code UK "for example mth-inscription-sujet"
    text title
    text office "decanat|srf|dsa"
    text source_url
    text submission_email "where the finished form is sent"
    text submission_cc
    text pdf_sha256
    bytea pdf_bytes
    int widget_count
    text status "draft|active|stale|retired"
    text created_by
  }
  form_step_defs {
    text id PK
    text form_def_id FK
    int seq "1, 2, 3"
    text actor_role "student|professor|direction"
    bool can_fill
    bool can_modify
    bool must_sign
    bool can_return
    int return_to_seq "must be earlier"
    bool must_submit "exactly one step, the last"
    text signature_field
    text label
  }
  timeline_templates {
    text id PK
    text cycle "2 master, 3 doctorate"
    text program
    text label
  }
  timeline_template_items {
    text id PK
    text template_id FK
    int seq
    text kind "form|report|seminar|paper|thesis"
    text ref "a form code, a milestone, a contribution"
    int offset_days "from admission"
    text title
  }
  timeline_items {
    text id PK
    text owner_login FK
    text kind "form|report|seminar|paper|thesis"
    text ref
    text title
    date due_date
    text date_source "template|calendar|manual"
    text status "pending|in_progress|done|late|waived"
    text form_instance_id FK
    text paper_id FK
    text updated_by
  }
  review_artifacts {
    text id PK
    text owner_login FK
    text kind "paper-audit|thesis-audit|review-audit|submitcheck|scholareval"
    text target "a paper id, thesis, or a report"
    text produced_by "which ResearchTools agent"
    text score "as reported, never computed here"
    bytea document
    text uploaded_by
  }
  review_findings {
    text id PK
    text artifact_id FK
    text severity "critical|major|minor"
    text section
    text quote
    text recommendation
    text status "open|addressed|rejected"
    text resolution_note "required to reject"
  }
  form_field_map {
    text id PK
    text form_def_id FK
    text field_name "byte exact, never normalized"
    text field_type "text|checkbox|radio|choice|signature"
    int page
    text on_states
    text profile_key "or null"
    text literal_value "or null"
    int owner_step_seq
    bool required
  }
  form_instances {
    text id PK
    text form_def_id FK
    int current_step_seq
    text status "Draft..Rejected|Frozen"
    text owner_login FK
    date due_date
    text updated_by
  }
  form_step_events {
    text id PK
    text form_instance_id FK
    int step_seq
    text actor_login
    text action "fill|modify|sign|return|approve|submit|reopen|freeze"
    int returned_to_seq
    text reason "required for return and reject"
    text submitted_to "the destination, recorded as sent"
    text message_id "from the relay, proof of sending"
    text document_sha256
    timestamptz at
  }
  form_documents {
    text id PK
    text form_instance_id FK
    text kind "filled|signed"
    int after_step_seq
    bytea bytes
    text sha256
  }
  profile_values {
    text id PK
    text owner_login FK
    text key "student.adresse"
    text value
    text updated_by
    timestamptz updated_at
  }
```

`form_field_map.field_name` holds the PDF's own byte-exact widget name and is never normalized: the
probed forms carry accented, space-bearing and generic names such as `code permanent`,
`no_matricule` and `TachesAEffectuerRow1`, and two forms name the same thing differently. That is
precisely why one profile key maps to many field names.

On the ResearchTools side there is no state to model. The service holds a signing certificate and
nothing else.

---

## 12. The twenty units

One plan document, one branch, one issue each. Every branch is cut from its repository's `main` and
its only commit is its own plan file.

```mermaid
flowchart LR
  subgraph RTU["ResearchTools - stateless PDF mechanics"]
    RT1["RT-1 skill scaffold<br/>+ PDF ingest"]
    RT2["RT-2 widget dump<br/>+ diff"]
    RT3["RT-3 fill"]
    RT4["RT-4 sign + chain"]
    RT5["RT-5 stateless service"]
    RT6["RT-6 publications<br/>endpoint"]
    RT7["RT-7 parse cache<br/>+ corpus index"]
  end

  subgraph TTU["ThesisTracker - catalogue, rules, data, UI"]
    TT0["TT-0 routes<br/>portability"]
    TT7["TT-7 email-code<br/>authentication"]
    TT8["TT-8 catalogue<br/>+ workflow rules"]
    TT9["TT-9 profile store<br/>+ write-back"]
    TT1["TT-1 form instance<br/>entity"]
    TT2["TT-2 instance routes"]
    TT3["TT-3 service client"]
    TT10["TT-10 multi-step<br/>workflow engine"]
    TT11["TT-11 student<br/>timeline"]
    TT12["TT-12 correction<br/>plan intake"]
    TT4["TT-4 forms UI"]
    TT5["TT-5 integration"]
    TT6["TT-6 cohort report"]
  end

  RT1 --> RT2 --> RT3 --> RT4 --> RT5
  RT5 --> RT6
  RT5 --> RT7
  TT0 --> TT7
  TT0 --> TT8 --> TT9
  TT0 --> TT1 --> TT2 --> TT3 --> TT10 --> TT4 --> TT5
  TT8 --> TT2
  TT9 --> TT10
  TT7 --> TT10
  TT10 --> TT11
  TT8 --> TT11
  TT0 --> TT12
  TT11 --> TT4
  TT12 --> TT4
  TT0 --> TT6
  RT5 --> TT3
  RT5 --> TT5
  RT6 --> TT6

  classDef first fill:#FEF3C7,stroke:#B45309,color:#14181F
  classDef last fill:#F3F4F6,stroke:#9CA3AF,color:#14181F
  class TT0 first
  class RT7 last
```

**Execution order:** TT-0 first, it unblocks every ThesisTracker unit and frees the function budget.
Then TT-7, because until it lands every new user needs a GitHub account. RT-1 through RT-5 run in
parallel with TT-8 and TT-9. TT-3 needs RT-5. TT-10 needs TT-9 for the profile store and TT-7 for
the `direction` role. TT-11 needs TT-10 and TT-8, because a timeline item tracks a form instance and
reads the calendar form's values. TT-12 needs only TT-0 and can run early: it touches no form.
RT-6 and RT-7 branch off RT-5 and are independent of each other. TT-6 needs RT-6. RT-7 is on no
critical path and can land last.

| Unit | Branch | Issue | Deliverable |
|---|---|---|---|
| RT-1 | `feat/uqac-forms-registry` | ResearchTools #4 | `uqac-forms` skill scaffold and the validated PDF-ingest contract (`%PDF` magic, size cap, https only, capped redirects). **Scope reduced:** the registry and the drift check moved to TT-8. **Delivered 2026-08-31.** |
| RT-2 | `feat/uqac-forms-field-map` | ResearchTools #5 | `dump_widgets` with byte-exact names and `/AP /N` on-states, and `diff_widgets(a, b)` for drift reporting. **Scope reduced:** the map and the vocabulary are TT-8's rows. |
| RT-3 | `feat/uqac-forms-filler` | ResearchTools #6 | Stateless `fill(pdf_bytes, values, flatten_fields) -> bytes`, `NeedAppearances`, selective field locking. **Scope reduced:** no profile, no map, no stale gate. |
| RT-4 | `feat/uqac-forms-signer` | ResearchTools #7 | Stateless PAdES sign of a named field, pluggable signer, and the guarantee that a new signature preserves every previous one. |
| RT-5 | `feat/uqac-forms-service` | ResearchTools #8 | Stateless service: `/pdf/widgets`, `/pdf/fill`, `/pdf/sign`, `/pdf/validate`. Shared-secret gate, no CORS, nothing persisted, no map volume. |
| RT-6 | `feat/publications-endpoint` | ResearchTools #9 | `scopus_api.author_documents`, cached and rate-limited `GET /publications`, approved-publisher flag |
| RT-7 | `feat/corpus-index` | ResearchTools #10 | Content-addressed parse cache, deterministic chunker, injected embedder, pgvector store, opt-in build |
| TT-0 | `feat/routes-portability` | ThesisTracker #1 | Named handlers, thin Vercel dispatchers, `pg` swap, Express front door, container |
| TT-1 | `feat/forms-entity` | ThesisTracker #2 | `form_instances` entity and its additive migration; `crud.js`, `scope.js`, `auth.js` untouched |
| TT-2 | `feat/forms-routes` | ThesisTracker #3 | Owner-scoped instance routes, signing queues, binary document routes |
| TT-3 | `feat/forms-service-client` | ThesisTracker #4 | Injected-fetch client for the stateless PDF service, with a complete failure-to-status mapping |
| TT-4 | `feat/forms-ui` | ThesisTracker #5 | Step-aware Forms view, per-role queues, pre-filled fields, the rules editor for a superuser |
| TT-5 | `feat/forms-integration` | ThesisTracker #6 | Combined compose, executable acceptance checklist, Vercel retirement checklist |
| TT-6 | `feat/cohort-report` | ThesisTracker #7 | Publications client method, staff-only roster walk, printable cohort report |
| TT-7 | `feat/email-code-auth` | ThesisTracker #9 | Email one-time code replaces GitHub OAuth; domain allowlist with no default; the `direction` role |
| TT-8 | `feat/form-catalogue` | ThesisTracker #10 | `form_definitions` (with `submission_email`), `form_step_defs` (with `can_return`, `return_to_seq`, `must_submit`), `form_field_map`; superuser-only registration and rules editing; the drift check in Node |
| TT-9 | `feat/profile-store` | ThesisTracker #11 | `profile_values` with history, pre-fill resolution, owner-scoped write-back on every fill and modify |
| TT-10 | `feat/workflow-engine` | ThesisTracker #12 | Step instances; actor and capability enforcement; **returns with a mandatory reason**; **forced re-approval when a modification breaks an earlier signature**; signature stacking; **submission by email to the definition's address**; reopen at a named step |
| TT-11 | `feat/student-timeline` | ThesisTracker #13 | Timeline template and instantiation on admission; forms, reports, seminar, papers per contribution, thesis milestones; dates shifted from the subject-calendar form's stored values |
| TT-12 | `feat/correction-plans` | ThesisTracker #14 | Intake of ResearchTools audit artifacts; `review_findings` as a student worklist; a rejected finding needs a reason; the score is stored as reported, never recomputed |

Plans live at `docs/superpowers/plans/2026-07-29-<unit>.md` on each unit's own branch. Every plan
whose scope the 2026-07-29 revision changed carries a scope-change block at the top pointing here.

---

## 13. Security and Law 25

```mermaid
flowchart TB
  subgraph PUB["Public"]
    B["Browser"]
  end
  subgraph INST["Institutional host"]
    A["ThesisTracker<br/>session token carries login only,<br/>role read from the DB per request"]
    D[("Postgres<br/>row-level ownership,<br/>student locked to own login")]
    F["PDF service<br/>no host port, stateless,<br/>constant-time secret compare"]
  end
  subgraph SEC["Secrets, environment only"]
    K1["SESSION_SECRET<br/>also keys the sign-in code HMAC"]
    K2["FORM_SERVICE_KEY"]
    K3["SCOPUS_API_KEY"]
    K4["SMTP_PASSWORD"]
  end
  MAIL[("Institutional SMTP relay")]

  B -->|"HTTPS, bearer token"| A
  B -->|"email address only,<br/>no credential"| A
  A --> D
  A -->|"private network"| F
  A -->|"one-time code"| MAIL
  K1 -.-> A
  K2 -.-> A
  K2 -.-> F
  K3 -.-> F
  K4 -.-> A

  classDef never fill:#FEE2D0,stroke:#993C1D,color:#14181F
  class SEC never
```

Binding rules, each enforced by a test or a startup check:

| Rule | Where |
|---|---|
| A student reads and writes only rows where `owner_login` equals their login; a cross-tenant id returns 404 | `scope.js`, `crud.js`, unchanged by every unit |
| Only the actor of the **current** step may act on an instance, and only within that step's capabilities | TT-10 workflow engine |
| A step without `modify` cannot overwrite a non-empty field; a step without `fill` cannot write at all | TT-10, asserted per capability |
| A modification that breaks an earlier signature's coverage **forces** a return to that signer; the instance cannot advance until they approve and re-sign | TT-10, asserted by test |
| A return may only target an **earlier** step, and needs a reason; a return with no reason is refused | TT-10 |
| The submission destination comes from `form_definitions.submission_email` and is **never accepted from the client**; only `owner` or `direction` may change it | TT-8, TT-10 |
| A submission is recorded with the destination and the relay's message id, and an instance is never marked `Submitted` without one. A second send needs an `owner` action with a reason | TT-10 |
| A rejected review finding requires a resolution note; nothing is silently closed. A ScholarEval score is stored as reported and never recomputed | TT-12 |
| The `direction` role can sign and edit rules, and can never write a form field or browse a tracker | TT-7 role, TT-8 rules routes, TT-10 capabilities |
| Only `owner` or `direction` may add a form definition or change its rules; a professor gets 403 | TT-8 |
| A profile write-back updates the **form owner's** profile, never the editor's, and records who did it | TT-9 |
| A new signature preserves every previous one; the chain is verifiable in step order | RT-4, asserted by test |
| An instance whose definition went stale is frozen, not silently advanced | TT-8 drift check, TT-10 gate |
| The PDF service persists nothing from a request and logs no field value | RT-5, asserted by test |
| The form service refuses to start without a shared secret of at least 32 characters, compared in constant time | RT-5 `config.load_settings`, `security.keys_match` |
| No CORS middleware anywhere on the service | server to server only |
| Only an address on an approved institutional domain may sign in; the allowlist has **no default** and the app refuses to start when empty | TT-7 `email-policy.allowedDomains`, called in `createApp()` |
| A sign-in code is stored only as `HMAC-SHA256(code, SESSION_SECRET)`, single use, 10 minutes, 5 attempts, rate limited | TT-7 `login-codes.js` |
| The code request answers identically whether or not the account exists, and all invalid-code reasons return one body | TT-7, asserted by test |
| A personal address can never sign in; rebinding an institutional address is an `owner` action | TT-7 |
| Downloads are HTTPS only, magic-byte validated, size capped, redirect capped | TT-8 ingest, RT-1 contract |
| Stored documents must start with `%PDF` and stay under the cap | TT-2 |
| No AGPL dependency in the deployable image | `deploy/form-service/requirements.txt` |
| Dependencies pinned exactly, `pip-audit --strict` before use | both requirements files |
| TLS verified against the system trust store for any remote database host | `api/_lib/db.js` |
| No email address, code, session token, profile value, or PDF byte is ever logged | asserted by tests across RT-3, RT-5, TT-2, TT-3, TT-7, TT-9 |

Law 25 drives the runtime decision: matricules, addresses, and signed expense claims stay on the
institutional host. Retiring Vercel removes the last location of student personal information
outside the institution. The same reasoning chooses the mail relay, and it is also why the PDF
service is stateless: publicly-sourced code runs beside private student data while holding none of
it.

---

## 14. Deferred and open

### Phase 3, n8n

Not dropped, deferred with explicit entry criteria. Reintroduce when any **two** hold:

1. Three or more scheduled automations exist that share credentials and need retry.
2. A non-developer must change rules without a deploy.
3. Two or more OAuth-bound external systems are in play.
4. Failed automations have become a support burden needing run history and a retry UI.

Note that criterion 2 is now **partly satisfied by design rather than by n8n**: the form rules are
editable in the UI by a superuser or the Direction, with no deploy. That was the requirement the
original specification implied, and TT-8 answers it directly. Constraints for that phase if it
arrives: self-hosted on the same UQAC host, never n8n Cloud; workflows authored from scratch and
reviewed as source, never imported; paper metadata from the `scopus` skill, never a scraper or
Google Scholar; no LLM node drafts scientific prose. Full rationale in ThesisTracker issue #8.

### Vercel retirement

Planned, not urgent, checklist written in TT-5. Order: choose the host, provision Postgres, migrate
with row-count verification, confirm the new host can send mail, set DNS, run the acceptance
checklist, keep Vercel read-only for two weeks, delete.

**The rollback is free at every step: stop the new stack.** That was not true when this project
started. The original step 4 was repointing the GitHub OAuth callback, and it was the pivot:
everything before it could be undone by stopping a container, everything after it needed a second
change in a third-party account. TT-7 removed it, so nothing outside the two hosts has to change.

### Open items

| Item | Status | Who answers |
|---|---|---|
| Does the Décanat des études accept a PAdES cryptographic signature on a thesis form, and which certificate authority does it recognize? | **Unverified.** The signer is pluggable with a self-signed development default, so implementation proceeds. A production credential is a configuration change, not a code change. | Someone must ask the Décanat |
| Does the Service des ressources financières accept a PAdES signature on an expense claim? | **Unverified**, same shape | Someone must ask the SRF |
| Does either office accept a **three-signature chain** in one PDF, or do they expect a separate signature page? | **Unverified.** The engine produces a stacked PAdES chain in step order, which is the technically correct form; whether the office reads it that way is not confirmed. | Same two offices, same conversation |
| Which institutional Docker host, and who administers it? | **Undecided by choice.** The stack is host-agnostic | The professor, with UQAC IT |
| Backup policy for the institutional Postgres | Open. A `pg_dump` cron container is the intended answer and needs no n8n | Whoever administers the host |
| Who holds the `direction` account, and does one account serve the whole Direction de programme or one per person? | Open. One per person gives a real audit trail; a shared account does not | The professor, with the Direction |

---

## 15. Where to look next

| You want | Read |
|---|---|
| The academic tooling inventory | `ResearchTools/README.md`, `ResearchTools/Architecture.md` |
| The routing table for agents, skills, commands | `ResearchTools/.claude/CLAUDE.md` |
| How to add a skill, agent, or command | `ResearchTools/docs/authoring-and-mirrors.md` |
| One unit's implementation steps | `docs/superpowers/plans/2026-07-29-<unit>.md` on that unit's branch |
| The app's own roadmap | `ThesisTracker/ROADMAP.md` |
| The acceptance checklist, once TT-5 lands | `ThesisTracker/docs/acceptance-forms.md` |
| The retirement procedure, once TT-5 lands | `ThesisTracker/docs/vercel-retirement.md` |
