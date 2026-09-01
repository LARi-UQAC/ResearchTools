# Accepted paper → conference talk

Build the presentation for an accepted paper: a deck on the lab gabarit with timed speaker notes, in PowerPoint, LaTeX Beamer, or a self-contained web page, plus the projector-grade figures and the printable PDF.

```
/talk <paper> [--audience field|academic|public] [--target pptx|beamer|web]
      [--aspect 4:3|16:9|9:16] [--paper slide|a4|letter] [--minutes 13]
      [--venue "IEEE CASE 2026"] [--template <pptx|tex>] [--lang en|fr]
      [--ending conclusions|thanks]
```

Procedure:

1. Resolve the paper path from `$ARGUMENTS` (a `.tex`, `.docx`, or `.pdf`, or the file open in the IDE).
2. Delegate to the `talk-builder` agent, which runs the pipeline in `.claude/skills/paper2talk/SKILL.md`.
3. Any flag supplied above **pre-answers** its opening question, and that question is dropped. Whatever is left is still asked first, as two consecutive `AskUserQuestion` calls, before the paper is read: audience, duration and conference, output target, aspect ratio, then PDF format and how the deck ends. A bare `/talk <paper>` asks all six.
4. The agent echoes the build contract (`n_content`, word budget, font floor, preferred form, deliverables) before authoring a single slide, then builds `talk_model.json` and renders it.
5. Gates before anything is shown: `talk_model.py` clean, `talk_validate.py` clean, `talk_notes.py` within 5 % per section and under the slot, `talk_render.py` page count equal to slide count. Then every rendered page is inspected.

Report at the end:

- The deck path and the PDF path (plus the paper-size PDF when one was asked for)
- Content slides against the budget, and the measured spoken length at 130 wpm
- Any section outside the 5 % tolerance
- Figures below 150 DPI, contradictions found in the paper, and exhibits no note discusses
- The QA folder holding the page images

Read only the files needed. Apply fixes directly - do not ask "would you like me to...". Respond in French unless the active file is in English.

$ARGUMENTS
