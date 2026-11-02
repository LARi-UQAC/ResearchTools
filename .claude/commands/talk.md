# Accepted paper → conference talk

Build the presentation for an accepted paper: a deck on the lab gabarit with timed speaker notes, in PowerPoint, LaTeX Beamer, or a self-contained web page, plus the projector-grade figures and the printable PDF.

```
/talk <paper> [--audience field|academic|public] [--target pptx|beamer|web]
      [--aspect 4:3|16:9|9:16] [--paper slide|a4|letter] [--minutes 13]
      [--venue "IEEE CASE 2026"] [--template <pptx|tex>] [--lang en|fr]
      [--ending conclusions|thanks] [--no-open]
```

`--no-open` only matters for `--target web`: the deck is still rendered and validated, but it is
not opened in the browser. It answers none of the opening questions.

Procedure:

1. Resolve the paper path from `$ARGUMENTS` (a `.tex`, `.docx`, or `.pdf`, or the file open in the IDE).
2. Delegate to the `talk-builder` agent, which runs the pipeline in `.claude/skills/paper2talk/SKILL.md`.
3. Any flag supplied above **pre-answers** its opening question, and that question is dropped. Whatever is left is still asked first, as two consecutive `AskUserQuestion` calls, before the paper is read: audience, duration and conference, output target, aspect ratio, then PDF format and how the deck ends. A bare `/talk <paper>` asks all six. `--no-open` is not one of them and adds no question.
4. The agent echoes the build contract (`n_content`, word budget, font floor, preferred form, deliverables) before authoring a single slide, then builds `talk_model.json` and renders it.
5. Gates before anything is shown: `talk_model.py` clean (for a web deck, its render too, which alone reports a footer field too long for its box), `talk_validate.py` clean, `talk_notes.py` within 5 % per section and under the slot, and for a PowerPoint deck `talk_render.py` page count equal to slide count. Then every rendered page is inspected.

For `--target web`, the lab gabarit slides folder (`../gabarit_these_maitrise_DSA_UQAC/src/slides/`, holding the banner `en-tete1260.jpg` and the logo `LogoLARI_FINAL.png`) is required: the agent passes it to the render as `--lab-dir`, and if it cannot be resolved it asks for the path instead of substituting another template. Every gate pass validates with `talk_validate.py --web <deck>`; once the last pass is clean, the default is `talk_validate.py --web <deck> --open`, which opens the deck in the default browser only if the validation is clean, once; with `--no-open` that final open is skipped. A deck with findings, or one that cannot be read, is never opened. Opening applies to the web target only; `pptx` and `beamer` are never opened in a browser.

Report at the end:

- The deck path and the PDF path (plus the paper-size PDF when one was asked for)
- Content slides against the budget, and the measured spoken length at 130 wpm
- Any section outside the 5 % tolerance
- Figures below 150 DPI, contradictions found in the paper, and exhibits no note discusses
- The QA folder holding the page images

Read only the files needed. Apply fixes directly - do not ask "would you like me to...". Respond in French unless the active file is in English.

$ARGUMENTS
