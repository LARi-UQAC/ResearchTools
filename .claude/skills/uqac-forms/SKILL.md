---
name: uqac-forms
description: >
  Stateless mechanics for the official UQAC PDF forms (Decanat des etudes thesis
  forms, Service des ressources financieres travel and expense forms): retrieve a
  form over https with the validated ingest contract, and later fill and
  cryptographically sign one. Holds no catalogue and no personal data: the form
  catalogue, field maps and profile live in ThesisTracker. Trigger on: /uqacform,
  fetch a UQAC form PDF, formulaire UQAC, inscription du sujet, plan de travail,
  autorisation de depot, rapport de depenses, demande d'avance de voyage, fill a
  UQAC form, sign a UQAC form.
allowed-tools: [Read, Write, Edit, Bash, AskUserQuestion, Glob]
---

# uqac-forms - official UQAC form mechanics

Hand this skill a PDF and a set of values and it hands back a PDF. It is a
function, not a system, and it stores nothing.

## What lives here, and what does not

The repository boundary matters more than usual here. ResearchTools cannot track
a form and cannot know the information that fills one, so:

| Concern | Where it lives |
|---|---|
| Retrieving a PDF over https, validated | here (RT-1) |
| Reading a form's widgets, and diffing two reads | here (RT-2) |
| Writing values into a form | here (RT-3) |
| Signing a form | here (RT-4) |
| The catalogue of registered forms, and their fingerprints | ThesisTracker (TT-8) |
| Field maps, workflow rules, the drift check | ThesisTracker (TT-8) |
| The profile that supplies values | ThesisTracker (TT-9) |

If you are looking for the list of registered UQAC forms, or for what changed
when UQAC replaced one, it is in ThesisTracker and edited there in the UI by an
`owner` or the `direction`. This skill will not tell you, because it does not
know.

## Scope in this unit (RT-1, RT-2, RT-3)

Retrieval, inspection and filling: fetch a form, read its widgets, diff two
reads, and write values into one. Signing (RT-4) and the HTTP service (RT-5)
land in the following units.

## The ingest contract

`scripts/pdf_ingest.py` implements six rules. They are written down rather than
left to the code because **TT-8 implements the same contract in Node**
(`api/_lib/drift.js`), and two implementations of an unstated contract drift
apart silently.

| Rule | Value |
|---|---|
| Scheme | `https` only, re-checked on every redirect hop |
| Redirects | at most 5, followed manually, never delegated to `requests` |
| Size | 25 MiB, enforced during the stream |
| Magic bytes | the first four bytes are `%PDF` |
| Timeout | 30 s on every request |
| Write | atomic, via a `*.part` file renamed only once the body is accepted |

Three of those exist because of a specific failure:

1. **The scheme is re-checked per hop.** Checking only the URL the caller typed
   is not a scheme check: a source answering 302 to `http://` defeats it, and
   the form is then fetched in the clear.
2. **The size cap is enforced mid-stream.** A cap applied once the body is in
   memory cannot prevent the allocation it exists to prevent.
3. **The magic bytes are checked.** UQAC answers HTTP 200 with an HTML access
   page when a form moves, so a status code never proves a PDF.

## Reading a form's fields

`scripts/field_map.py` reports what a form contains, and what changed between
two reads of it. It assigns no meaning: which profile key fills which field is a
TT-8 row edited in the ThesisTracker UI.

```python
from field_map import dump_widgets, diff_widgets

widgets = dump_widgets('form.pdf')      # a path, or the PDF bytes
report  = diff_widgets(before, after)   # added, removed, relocated, retyped
```

Each widget is `{name, name_hex, type, page, rect, on_states, readonly}`, where
`type` is one of `text`, `checkbox`, `radio`, `choice`, `signature`, `unknown`.

Two things it will not do, both because an official document is at stake:

1. **It never tidies a name.** The name is the PDF's own bytes, trailing spaces
   and all. TT-8 stores it and RT-3 fills by exactly that key, so a normalized
   name is a field nobody can fill again. `name_hex` is there because `Nom` and
   `Nom ` are indistinguishable in a printed report.
2. **It never guesses an on-state.** A checkbox is checked by writing its own
   on-state, read from `/AP /N`. Real UQAC forms use `Oui`; others use `Yes`,
   `1`, `On`, and a jury form uses `Choix1` and `Choix2`. Writing the wrong one
   leaves the box unchecked on a document that then looks complete.

`diff_widgets` mirrors TT-8's `diffWidgets`: same five keys, same meanings. A
field that moved page is `relocated`, never an add plus a remove, because its
stored row is still correct. A checkbox whose on-state was renamed from `/Oui`
to `/Yes` is `restated`: nothing else about it changed, so without that key the
drift check would pass it and every later fill would leave the box unchecked on
a form that looks complete.

## Filling a form

`scripts/fill_form.py` writes values into a form and hands back the bytes. It
is stateless: the caller supplies the PDF, the values, and which fields to
lock.

```python
from fill_form import fill

filled = fill(pdf_bytes, {'Nom': 'Umuhoza', 'plan_travail': 'Oui'},
              flatten_fields=['Nom'])
```

Keys are the byte-exact field names `dump_widgets` reports. Values are strings
ThesisTracker already resolved: this function looks nothing up.

### The order, which is not negotiable

1. Write the values.
2. Set `NeedAppearances`, or the values are in the file and invisible on screen.
3. Lock the fields of the step that just completed.
4. Sign last, in RT-4, as an incremental update.

Signing last is what makes a signature verifiable. An incremental update
appends, so earlier signatures survive; a rewrite after signing does not.

### flatten_fields is a list, not a flag

A UQAC form is filled by several people in turn. Locking every field after the
first step would leave the professor and the Direction with nothing they can
write, so `flatten_fields` names the fields of the step that completed. `None`
locks nothing. **A signature widget is never locked, even when named**, because
locking one destroys the field a later signer needs.

### Three refusals, each replacing a silent failure

1. **A value for a field the PDF does not have.** The caller believes it filled
   something. Every offending name is reported, not just the first.
2. **A checkbox value that is not one of that widget's on-states.** Writing
   `Yes` to a box whose on-state is `Oui` leaves it unchecked on a document
   that looks complete.
3. **Filling a document that is already signed.** `pypdf` writes a full rewrite,
   not an incremental update, so this would invalidate the signature without
   saying so.

### What flatten does not mean

`pypdf` has no appearance-burning flatten. Locking read-only is what flattening
means here: the values are fixed and a viewer will not edit them, but they
remain form fields rather than page content. If you need a true burn-in, this
skill is not the tool, and it says so rather than letting you find out from a
PDF someone was able to edit.

## Prerequisites

- `pip install -r .claude/skills/uqac-forms/scripts/requirements.txt`
- Network access to `www.uqac.ca` for a fetch. Everything else is offline.

## Workflow

Fetch one form and report its digest:

```
python .claude/skills/uqac-forms/scripts/pdf_ingest.py <https-url> <dest.pdf>
```

On success it prints `{"ok": true, "path": ..., "sha256": ...}` and exits 0. On
any refusal it prints `{"ok": false, "url": ...}`, exits 1, and writes no file.
The reason is logged with the `[UQAC-FORMS]` prefix.

Compare the reported `sha256` against whatever your caller stored. This skill
does not keep that record, so it cannot tell you whether a form changed; it can
only tell you what the form hashes to right now.

## Outputs

Exactly the destination path you name. No cache, no index, no side files. A
refused download leaves nothing behind, including no `*.part`.

## Tests

```
python .claude/skills/uqac-forms/scripts/Test/test_pdf_ingest.py
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
```

Offline: `requests.get` is patched, so no test reaches the network. Every rule of
the contract has a test, because a rule with no test is a rule the second
implementation is free to drop.

## Unverified

Whether the Decanat des etudes and the Service des ressources financieres accept
a PAdES cryptographic signature is **not confirmed**. The signer (RT-4) is
pluggable with a self-signed development default so implementation can proceed;
the production certificate decision (UQAC PKI, or Notarius / ConsignO) is open
and someone must ask both offices.
