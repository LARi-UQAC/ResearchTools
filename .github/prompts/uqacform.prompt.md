---
description: "Fetch an official UQAC form PDF"
---

Thin wrapper over the `uqac-forms` skill. Read
`.claude/skills/uqac-forms/SKILL.md` and follow its workflow.

This skill holds no catalogue. It cannot tell you which UQAC forms exist, nor
whether one changed: that record lives in ThesisTracker (TT-8) and is edited
there. What it can do is fetch one PDF over https, prove it is a PDF, and report
its SHA-256 so the caller can compare against the record it keeps.

Procedure:

1. Resolve the intent from `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`. Expect an https URL and, optionally, a
   destination path. If no URL is given, ask for one rather than guessing: a
   wrong URL that happens to serve a PDF would produce a plausible file and a
   meaningless digest.
2. Default the destination to `out/uqac-forms/<basename>.pdf` and create the
   directory if needed. Everything this skill writes belongs under `out/`.
3. Run:
   ```
   python ".claude/skills/uqac-forms/scripts/pdf_ingest.py" "<url>" "<dest>"
   ```
4. Report the outcome from the JSON on stdout:
   - `{"ok": true, ...}` and exit 0: give the path and the `sha256`, and say
     plainly that a matching digest is the caller's comparison to make, not
     this skill's.
   - `{"ok": false, ...}` and exit 1: nothing was written. The `[UQAC-FORMS]`
     log line gives the reason, which is one of: not https (including a
     redirect that tried to downgrade), too many redirects, over the 25 MiB
     cap, not a PDF, an error status, or a network failure. Report the actual
     reason, never a generic failure.

Never report a form as retrieved without the digest, and never invent one. If
the fetch was refused, say so and stop; do not fall back to a browser download
or any other route that skips the validation this command exists to apply.

