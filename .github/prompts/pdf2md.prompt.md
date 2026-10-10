---
description: "Convert a PDF to UQAC-shaped markdown, maximum accuracy"
---

Thin wrapper over the `pdf2md` skill. Read `.claude/skills/pdf2md/SKILL.md`
first, then follow it exactly.

Option contract:

```
/pdf2md <pdf-path> -o <output-dir> [--tier flash|basic|standard|advanced]
                   [--port 30000] [--yes]
```

Procedure:

1. Parse `the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)`. The PDF path and `-o/--output-dir` are both required;
   refuse to start without either, naming which one is missing.
2. Run bootstrap first, report-only, so the user sees what is missing
   before anything is installed or downloaded:
   ```bash
   python .claude/skills/pdf2md/scripts/pdf2md.py bootstrap --server-url http://127.0.0.1:<port>/v1
   ```
   If it reports missing packages, a missing model, or config issues, ask
   the user before passing `--yes` to apply them -- a model download can
   be several GB and the config rewrite discards any hand-written comments
   in `~/.mineru/config.yaml` (it regenerates the file; see
   `pdf2md_config.py`'s own docstring for why).
3. Run the full pipeline:
   ```bash
   python .claude/skills/pdf2md/scripts/pdf2md.py run <pdf-path> -o <output-dir> --tier advanced --yes --json
   ```
   This starts the VLM server and the conversion, both detached, and
   returns immediately with a PID and a log path -- it does NOT wait for
   the conversion to finish, which can take a long time at `--tier
   advanced` on a long document. Tell the user this up front.
4. Poll progress on request with:
   ```bash
   python .claude/skills/pdf2md/scripts/pdf2md.py convert status --log <convert_log> --json
   ```
   Report `routed_via_vlm_server` explicitly if it is `false` -- that
   means the config/server wiring regressed and the run is using the
   slow, warning-prone in-process engine instead of the fixed server.
5. Once `finished` is true, run the two remaining stages. `postprocess` writes
   everything under `<output-dir>/src/` (mirroring thesis-auditor's own
   `<project-dir>/src/main.tex` convention): `frontmatter.md`, one file per
   chapter (first chapter -> `Introduction.md`, last -> `Conclusion.md`,
   middle ones -> `chapitreN.md`), `bibliography.md` when a bibliography is
   found, and `main.md` linking all of them. Feed `bibliography.md` to
   `refs` (its own report says `bibliography_path`):
   ```bash
   python .claude/skills/pdf2md/scripts/pdf2md.py postprocess <mineru's markdown output> -o <output-dir> --json
   python .claude/skills/pdf2md/scripts/pdf2md.py refs <output-dir>/src/bibliography.md -o <output-dir>/src/ref.md --json
   ```
6. Report: splice headings removed, chapter files written (and their
   Introduction/Conclusion/chapitreN names), reference count, and the known
   limits from SKILL.md (no real `.tex`, mixed French/English inside a
   chapter is normal for a thèse-par-articles).

the file(s) or topic given after the command in the chat message (if none was given, use the file currently open in the editor)

