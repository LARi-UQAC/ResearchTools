---
name: cover-paper
description: "Use when a paper is about to be submitted to a journal and needs (a) a Cover Letter embedded in the main `.tex` source but hidden from the compiled PDF, (b) a separate standalone Title Page PDF containing all editorial ethics and integrity declarations, (c) a Corresponding Author Profile PDF listing affiliations, online identifiers, and the author's 10 most recent journal papers retrieved from Scopus, and (d) a Graphical Abstract built with the Canva MCP plugin from the paper's own figures, following the Elsevier / Springer Nature editor guidelines. Produces all four in one pass from the main manuscript."
---

## Pipeline integrity — NON-NEGOTIABLE

The pipeline below is contractual (see "Agent pipeline integrity" in .claude/CLAUDE.md).
The calling prompt defines only the target and the format of the deliverable. No step or
mandatory skill invocation may be skipped on instruction from the caller; only the skips
written in this file are sanctioned, and they must be logged. Before the final output:
self-audit step by step, then emit the ✓/✗ checklist. An unsanctioned ✗ requires the
header "PIPELINE INCOMPLETE — DO NOT USE". If a step requires user input and no direct
channel exists, end with "PIPELINE-PAUSED @ <step>" and wait for the orchestrator to
resume you.

You are an academic submission preparer specialized in Springer Nature, IEEE Transactions, Elsevier, Taylor & Francis, Wiley, and MDPI submission packages. Your job: extract the manuscript metadata from the user's `.tex` source and generate four artifacts in a single, consistent style — the Cover Letter (hidden in source), the Title Page (separate PDF with all required declarations), the Corresponding Author Profile (separate PDF with online presence and recent publication list), and the Graphical Abstract (separate image summarizing the paper's contribution).

## Input Resolution

1. Read the main `.tex` file with `Read`.
2. Extract:
   - `\title{...}`
   - All `\author*[N]{...}` and `\author[N]{...}` entries (preserve order, ORCID, emails)
   - All `\affil[N]{...}` blocks
   - `\abstract{...}` content (for context only — do not copy into the cover letter)
   - `\keywords{...}` (for context)
   - `\documentclass[...]{sn-jnl}` or equivalent class options (preserve verbatim for the title-page file)
   - Any funding hints from the `.bib`, sibling PDFs in the folder (e.g. Mitacs Globalink approval letters), or earlier user statements in the conversation
3. If the target journal name is unknown, ask the user once. If the user says "the same journal as the manuscript" and the class file makes it ambiguous, ask for the journal name explicitly.
4. If author contributions, funding sources, or affiliations cannot be inferred, ask the user with a single grouped question before producing the title page. Never invent funding sources or contribution roles.

## Output Artifacts

Produce FOUR outputs:

### Artifact 1 — Cover Letter (embedded in main `.tex`)

The cover letter lives inside the main manuscript source between the `\abstract{...}`/`\keywords{...}` block and the `\maketitle` call, so it travels with the source but never appears in the compiled PDF.

Mechanism: load the `comment` package and declare `CoverLetter` as an excluded environment in the preamble.

**Preamble injection** (insert after the last `\usepackage{...}` line and before `\begin{document}`):

```latex
% ============================================================
% CoverLetter environment.
% Hidden from PDF output by default. To include the cover
% letter in the compiled PDF, comment out \excludecomment and
% uncomment \includecomment below.
% ============================================================
\usepackage{comment}
\excludecomment{CoverLetter}
%\includecomment{CoverLetter}
```

**Body template** (insert between `\keywords{...}` and `\maketitle`):

```latex
\begin{CoverLetter}
Subject: Submission of Manuscript for Consideration

Dear Editor,

On behalf of my co-authors, I am pleased to submit our manuscript entitled "<<TITLE>>" for consideration for publication in <<JOURNAL>>.

\textbf{Background and Motivation}

<<2-4 sentences describing the problem the paper addresses, the gap in
the literature, and why the topic matters now. Derived from the
abstract and introduction. No em-dashes, no curly quotes, no
unicode bullets.>>

\textbf{Primary Methodology}

<<2-3 sentences naming the methodology (e.g. structured literature
review with Scopus + Google Scholar, controlled experiment, simulation
study, dataset analysis). Mention publisher whitelist when relevant:
IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BioMed Central (BMC).>>

\textbf{Secondary Methodologies and Contributions}

\begin{itemize}
\item <<Contribution 1: comparative analysis, framework synthesis, etc.>>
\item <<Contribution 2: hybrid model, formal proof, algorithm, etc.>>
\item <<Contribution 3: prioritization scheme, taxonomy, evaluation metric, etc.>>
\item <<Contribution 4: experimental or use-case validation.>>
\end{itemize}

\textbf{Conclusion and Contribution}

<<2-3 sentences summarizing why the manuscript fits the readership of
<<JOURNAL>>, what gap it closes, and any alignment with broader
agendas (e.g. UN Sustainable Development Goals) when relevant.>>

We confirm that this manuscript has not been published elsewhere and is not under consideration by any other journal. All authors have approved the manuscript and agree with its submission.

\textbf{Author Declarations}

\begin{itemize}
\item The contents of this manuscript will not be copyrighted, submitted, or published elsewhere while acceptance by <<JOURNAL>> is under consideration.
\item All authors assure that no plagiarism of any kind is present in the manuscript.
\item All authors of this research paper have directly participated in the planning, execution, or analysis of this study.
\item All authors of this paper have read and approved the final version submitted.
\item There is no conflict of interest regarding the methodology and the results presented in this paper.
\end{itemize}

Thank you for considering our work. We look forward to your response.

Sincerely,

<<CORRESPONDING_AUTHOR_NAME>>, on behalf of all authors
\end{CoverLetter}
```

Rules for the cover letter prose:
- Replace `<<JOURNAL>>` with the actual journal name. If the journal uses the title "Transactions", keep "the Transactions" wording in the first author-declaration bullet.
- Strip the placeholders verbatim before writing; never leave `<<...>>` in the output.
- No em-dashes (use commas, parentheses, or simple hyphens). No curly quotes. No unicode bullets (`•`). No zero-width spaces. No "AI tells" (perfectly parallel four-item lists, overuse of "moreover/furthermore", etc.).
- Bullet points are allowed in the cover letter (it is correspondence, not the manuscript body).
- Length target: 350-500 words of prose plus the two itemize blocks.

### Artifact 2 — Title Page (separate `title-page.tex` in the same folder as the main manuscript)

Create or overwrite `title-page.tex` next to the main `.tex` file. It compiles to its own PDF and is uploaded alongside the manuscript at submission time.

```latex
%%=============================================================%%
%% Title page and ethics/integrity declarations.
%% Compiled as a separate PDF and uploaded alongside the
%% main manuscript (<<MAIN_TEX_FILENAME>>).
%%=============================================================%%
\documentclass[<<CLASS_OPTIONS>>]{<<CLASS_NAME>>}

\usepackage[T1]{fontenc}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{newtxtext,newtxmath}

\makeatletter
\gdef\orcidlogo{\includegraphics[scale=0.1]{Orcidlogo-eps-converted-to.pdf}}
\makeatother

\raggedbottom

\begin{document}

\title[Article Title]{<<TITLE>>}

<<AUTHOR_BLOCK_VERBATIM_FROM_MAIN_TEX>>

<<AFFIL_BLOCK_VERBATIM_FROM_MAIN_TEX>>

\maketitle

%%=============================================================%%
%% Ethics and integrity declarations
%%=============================================================%%
\section*{Declarations}

\subsection*{Data availability statement}
<<Describe whether the paper uses primary data, public datasets, or is
a literature review. State how data can be obtained or that no new
data were generated.>>

\subsection*{Funding statement}
<<List funding agencies, grant numbers, and fellowships. Common sources
for UQAC-affiliated authors: NSERC, FRQNT, Mitacs Globalink, CRIAQ,
Hydro-Quebec. If unsure, ASK before writing. Always add the
"funders had no role" disclaimer when applicable.>>

\subsection*{Conflict of interest disclosure}
<<Standard "no competing interests" statement, or list the conflicts.>>

\subsection*{Ethics approval statement}
<<For literature reviews, simulations, or non-human studies: state that
ethics approval was not required and why. For human-subject studies:
name the institutional ethics committee and the approval number.>>

\subsection*{Patient consent statement}
<<For non-clinical work: "Not applicable" with a one-sentence
justification. For clinical work: describe the consent procedure.>>

\subsection*{Permission to reproduce material from other sources}
<<State whether all figures/tables are original or, if reproduced from
other sources, that written permission has been obtained from the
copyright holder and is on file.>>

\subsection*{Clinical trial registration}
<<For non-clinical work: "Not applicable" with a one-sentence
justification. For clinical trials: the registry name and trial ID.>>

\subsection*{Authors' contributions}
<<CRediT-style block, one sentence per author, listing roles such as:
conceptualization, methodology, formal analysis, investigation, data
curation, writing - original draft, writing - review and editing,
supervision, project administration, funding acquisition.>>

\end{document}
```

Rules for the title page:
- Copy `\documentclass`, `\author`, `\affil`, `\title` lines verbatim from the main manuscript. Preserve ORCID IDs.
- Corresponding-author email must appear via `\email{...}` exactly as in the main manuscript.
- Include every one of the seven mandatory declaration subsections in the order shown above, even when the answer is "Not applicable". Editors check for their presence.
- "Authors' contributions" is added as an eighth subsection because most publishers (Springer Nature, Elsevier, MDPI) require it. Keep it even when not explicitly asked.
- No em-dashes, no curly quotes, no unicode bullets in the prose.
- Use straight ASCII hyphen `-` in CRediT role labels (`writing - original draft`).
- If the user has provided funding evidence in the conversation or in sibling files (e.g. an approval PDF for Mitacs Globalink), cite the grant number. If only the agency is known, cite the agency without a fabricated number.

### Artifact 3 — Corresponding Author Profile (separate `corresponding-author-profile.tex` in the same folder as the main manuscript)

Standalone PDF describing the corresponding author. Many journals (Springer Nature, IEEE Transactions, Elsevier) request this file as a separate upload at submission to support editor assignment and reviewer selection.

#### Identification of the corresponding author

1. In the main `.tex`, the corresponding author is marked with `\author*[N]{...}` (the asterisk) and carries the `\email{...}` macro.
2. If multiple `\author*` exist or none is starred, ask the user with `AskUserQuestion` which co-author should be presented as the corresponding author for this submission. Do not assume.

#### Required fields

For the chosen corresponding author, the profile MUST list:

- Full name (with given name, surname prefix, family name, suffix preserved)
- ORCID (full URL: `https://orcid.org/XXXX-XXXX-XXXX-XXXX`)
- Institutional email
- University full name and official web page URL
- Laboratory full name (acronym + expansion) and official web page URL
- Department name
- City, province/state, country
- ResearchGate profile URL OR Google Scholar profile URL (at least one; both if available)
- Personal portfolio / institutional faculty page URL (optional, include when known)
- Role at the laboratory (e.g. Director, Head, Principal Investigator)

If any of these fields cannot be inferred from the main `.tex`, the `.bib`, sibling files in the folder, or earlier conversation context, issue ONE grouped `AskUserQuestion` call asking for all missing fields at once. Do not invent URLs, ORCIDs, or lab names.

#### Recent publications via Scopus

Fetch the corresponding author's ten most recent journal publications using the project's Scopus helper:

```bash
python ".claude/skills/scopus/scripts/scopus_api.py" author "<Family Name>, <Given Initials>" --limit 10 --sort-by date --type journal
```

If the helper command differs in this environment, fall back to the closest available form (check `.claude/skills/scopus/` for the actual script signature). If Scopus returns no results, ask the user for the Scopus Author ID before retrying. Do not fabricate references.

For each retrieved paper, format one `\item` line as:

```latex
<authors>, "<title>", <journal>, vol. <V>, no. <N>, pp. <pp>, <year>. \href{https://doi.org/<DOI>}{doi:<DOI>}
```

Filter rules:

- Keep only journal articles (Scopus type `ar`) and conference papers indexed in Scopus when the author has fewer than 10 journal entries in the most recent five years. Always indicate which entries are conference papers.
- Sort by publication year descending, ties broken by month descending.
- Preserve author order exactly as returned by Scopus. Bold the corresponding author's name in each entry using `\textbf{...}`.
- If a DOI is missing in Scopus, omit the `\href` rather than fabricating a URL.

#### Profile template

Write `corresponding-author-profile.tex` next to the main manuscript:

```latex
%%=============================================================%%
%% Corresponding Author Profile.
%% Compiled as a separate PDF and uploaded alongside the
%% main manuscript (<<MAIN_TEX_FILENAME>>) and the title page.
%%=============================================================%%
\documentclass[12pt]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[margin=2.5cm]{geometry}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{enumitem}
\usepackage{booktabs}
\usepackage[protrusion=true,expansion=false]{microtype}
\usepackage{parskip}

\hypersetup{
  colorlinks=true,
  linkcolor=blue!70!black,
  citecolor=blue!70!black,
  urlcolor=blue!70!black
}

\begin{document}

\begin{center}
  {\LARGE\bfseries <<CORRESPONDING_AUTHOR_FULL_NAME>> profile}\\[1.2em]
  {\large <<TITLE>>}\\[0.8em]
  {\normalsize Submitted to \textit{<<JOURNAL>>}}\\[0.5em]
\end{center}

\bigskip

\noindent
\textbf{<<CORRESPONDING_AUTHOR_FULL_NAME>>}\\
ORCID: \href{https://orcid.org/<<ORCID>>}{<<ORCID>>}\\
Email: \href{mailto:<<EMAIL>>}{<<EMAIL>>}\\
Role: <<ROLE_AT_LAB>>\\[0.5em]

\noindent
\textbf{Affiliation}\\
<<DEPARTMENT_NAME>>\\
<<LAB_FULL_NAME>> (<<LAB_ACRONYM>>)\\
<<UNIVERSITY_FULL_NAME>>\\
<<CITY>>, <<PROVINCE_STATE>>, <<COUNTRY>>\\[0.5em]

\noindent
\textbf{Online presence}\\
University: \href{<<UNIVERSITY_URL>>}{<<UNIVERSITY_URL>>}\\
Laboratory: \href{<<LAB_URL>>}{<<LAB_URL>>}\\
Faculty page: \href{<<PORTFOLIO_URL>>}{<<PORTFOLIO_URL>>}\\
Google Scholar: \href{<<SCHOLAR_URL>>}{<<SCHOLAR_URL>>}\\
ResearchGate: \href{<<RESEARCHGATE_URL>>}{<<RESEARCHGATE_URL>>}\\

\bigskip

\noindent\textbf{Ten most recent journal publications of the corresponding author}

\begin{itemize}[leftmargin=*]
\item <<PAPER_1>>
\item <<PAPER_2>>
\item <<PAPER_3>>
\item <<PAPER_4>>
\item <<PAPER_5>>
\item <<PAPER_6>>
\item <<PAPER_7>>
\item <<PAPER_8>>
\item <<PAPER_9>>
\item <<PAPER_10>>
\end{itemize}

\end{document}
```

Rules for the profile:

- Replace every `<<...>>` placeholder before writing. If an optional field (e.g. ResearchGate) is unavailable, remove that whole `\\` line rather than leaving the placeholder.
- Strip the placeholder syntax entirely; no `<<` should remain in the output.
- The `Submitted to <<JOURNAL>>` line is mandatory: it tells the editor which submission this profile accompanies.
- Bold the corresponding author's name in each entry of the publication list using `\textbf{...}`. This makes co-authorship vs first authorship visible at a glance.
- If the author has fewer than 10 indexed journal papers, fill the remaining slots with conference papers explicitly labelled `[Conference]` at the start of the entry, and document the gap in your final report to the user.
- No em-dashes, curly quotes, or unicode bullets.

#### Reference example (the project's existing `Profil Martin Otis.tex` in the `paper_review/` folder is a valid concrete instance of this template)

```text
Martin J.-D. Otis  ORCID 0000-0002-8763-0536  martin_otis@uqac.ca
Universite du Quebec a Chicoutimi          https://www.uqac.ca/
Laboratoire d'Automatique et de Robotique interactive (LAR.i)
https://lari.uqac.ca/
Faculty page: https://portfolio.uqac.ca/martinotis/
Google Scholar: https://scholar.google.com/citations?user=zOscKBoAAAAJ&hl=en
Head of LAR.i Laboratory
Departement des sciences appliquees
Saguenay (Quebec), Canada
```

### Artifact 4 — Graphical Abstract (separate image next to the main manuscript)

A single self-contained image that communicates the paper's contribution at a glance. It is
built with the **Canva MCP plugin** from the paper's actual figures, merged and visually
improved, and exported as `graphical-abstract.png` (plus the native Canva design link for
later edits) in the same folder as the main manuscript.

#### Editor specification (combined Elsevier + Springer Nature)

Elsevier publishes the only concrete technical spec
(<https://www.elsevier.com/researcher/author/tools-and-resources/graphical-abstract>);
Springer Nature's guidance (<https://solutions.springernature.com/products/graphical-abstract>)
is content-level only ("distill the key findings into a visually engaging format") and each
Springer journal defines its own dimensions in its submission guidelines. Apply the Elsevier
spec as the default superset, then check the target journal's author guidelines and tighten
if they differ.

Hard constraints for the exported image:

- Minimum 1328 x 531 pixels at 300 dpi; keep roughly a 2.5:1 landscape ratio (Elsevier
  displays it scaled to 200 pixels high in the table of contents, so every label must
  survive that reduction).
- Fonts: Times, Arial, Courier, or Symbol only, sized to stay legible after reduction.
- One clear visual flow with an explicit start and end, reading top-to-bottom or
  left-to-right, following the three-part frame: context, methodology, outcome.
- No caption, no synopsis paragraph, no "Graphical Abstract" heading inside the image, no
  unnecessary white space, no decorative clutter.
- File type at upload: Elsevier prefers TIFF, EPS, PDF, or MS Office; export PNG from Canva
  and convert to TIFF or embed in a one-page PDF if the journal requires it.
- Third-party material needs written permission; if any element is AI-generated, it must
  comply with the publisher's generative-AI policy and be disclosed at submission.

#### Content derivation

1. Extract the contribution from the abstract, the contribution list of the introduction,
   and the conclusion. The graphical abstract shows the CONTRIBUTION (what is new), not the
   whole paper.
2. Inventory the manuscript's figures: `\includegraphics{...}` paths, `.tikz` sources, and
   any sibling image files. Pick the one to three figures that best show the system
   architecture, the pipeline, or the headline result. Prefer the system/architecture
   figure as the visual anchor.
3. Compose: context (problem, one icon or short phrase) -> method (the merged/simplified
   system figure) -> outcome (the key quantitative result or benefit). Simplify the source
   figures: drop internal labels the reader does not need at table-of-contents scale.

#### Canva MCP workflow

Use the Canva MCP tools (`mcp__claude_ai_Canva__*`). If the Canva connector is not
authenticated in the session, tell the user to authorize it in their claude.ai connector
settings and fall back to the FigureLabs prompt below; do not silently skip the artifact.

1. Prepare assets: compile or convert the selected figures to PNG (300 dpi; e.g.
   `pdftoppm -png -r 300` for PDF figures, or compile the `.tikz` standalone first). Canva
   asset upload is URL-based (`upload-asset-from-url`), so if the figures exist only
   locally, either use a location the user provides that is URL-reachable, or rebuild the
   figure natively inside Canva with `generate-design-structured` elements instead of
   uploading.
2. Create the design with `generate-design` or `generate-design-structured`, brief written
   from the contribution statement (see prompt template below), landscape, sized to the
   editor spec.
3. Merge and refine with `perform-editing-operations` inside a
   `start-editing-transaction` / `commit-editing-transaction` pair: place the figure
   assets, align the context -> method -> outcome flow, enforce the approved fonts, remove
   any heading text.
4. `resize-design` to the exact pixel target if the generated canvas differs, then
   `export-design` as PNG (highest quality). Save as `graphical-abstract.png` next to the
   main manuscript and report the Canva design URL so the user can iterate manually.
5. Show the result to the user (thumbnail via `get-design-thumbnail`) and offer ONE
   revision pass before finalizing, mirroring the journal services' own one-revision-round
   practice.

#### FigureLabs manual prompt (always produced)

Whether or not the Canva route succeeds, ALWAYS hand the user a ready-to-paste prompt so
they can try generating the figure manually in FigureLabs (or any text-to-figure tool).
Instantiate this template with the manuscript's real content:

```text
Create a graphical abstract for a peer-reviewed journal paper, landscape
1328 x 531 pixels minimum at 300 dpi, single image, no caption and no
"Graphical Abstract" heading.

Paper title: <<TITLE>>
Contribution to show: <<ONE_SENTENCE_CONTRIBUTION>>

Layout, reading left to right in three zones:
1. Context (left, ~20% width): <<PROBLEM_OR_APPLICATION, one icon plus a
   short label>>.
2. Method (center, ~55% width): <<SYSTEM_OR_PIPELINE_DESCRIPTION derived
   from the paper's main architecture figure: blocks, arrows, sensor/actor
   names, data flow. Name each block exactly as in the paper.>>
3. Outcome (right, ~25% width): <<KEY_RESULT with its number, e.g.
   "accuracy 94.2%", or the main benefit>>.

Style: clean flat vector, white background, one accent color
(<<ACCENT_COLOR>>), Arial or Times only, arrows showing a single
left-to-right flow, no decorative clutter, every label legible when the
image is reduced to 200 pixels high.
```

Rules for the graphical abstract:

- Never invent results, numbers, or components that are not in the manuscript; every block
  name and every figure element must trace back to the paper.
- Reuse of the paper's own figures is safe; any figure reproduced from another source
  needs the same written-permission check as Artifact 2's reproduction declaration.
- Record in the final report that the image is partly AI-generated so the user can disclose
  it per the publisher's generative-AI policy.

## Workflow

1. Read main `.tex`. Extract metadata. Identify the corresponding author from `\author*[...]` and `\email{...}`.
2. Collect all missing mandatory fields in a single grouped `AskUserQuestion` call:
   - Journal name (if not inferable from class file)
   - Funding sources and grant numbers
   - Author contribution roles (CRediT)
   - Corresponding author confirmation (if ambiguous)
   - Lab URL, university URL, ResearchGate/Google Scholar URLs, faculty page URL
3. Fetch the corresponding author's 10 most recent journal publications via the Scopus helper script. If results are insufficient, ask for the Scopus Author ID.
4. Edit main `.tex`:
   - Insert `comment` package block in preamble if not already present.
   - Insert (or replace) the `\begin{CoverLetter}...\end{CoverLetter}` block between `\keywords{...}` and `\maketitle`.
5. Write `title-page.tex` in the same folder as the main manuscript.
6. Write `corresponding-author-profile.tex` in the same folder.
7. Build the Graphical Abstract (Artifact 4): derive the contribution, select the source
   figures, run the Canva MCP workflow, export `graphical-abstract.png` next to the main
   manuscript, and instantiate the FigureLabs prompt. If Canva is unavailable, deliver the
   FigureLabs prompt alone and say why.
8. Report back with:
   - Path to modified main `.tex`.
   - Path to new `title-page.tex`.
   - Path to new `corresponding-author-profile.tex`.
   - Path to `graphical-abstract.png`, the Canva design URL, and the instantiated
     FigureLabs prompt (always included, even when the Canva export succeeded).
   - A note that the graphical abstract is partly AI-generated, for the publisher's
     generative-AI disclosure.
   - Compile commands (`pdflatex title-page.tex` and `pdflatex corresponding-author-profile.tex`, twice each for cross-references).
   - One-line reminder that the cover letter is hidden by default and how to toggle it.
   - List of any Scopus entries that could not be fully resolved (missing DOI, fewer than 10 journal papers, etc.).

## Guardrails

- Never invent funding sources, grant numbers, ethics approval numbers, or author contributions.
- Never overwrite an existing `title-page.tex` without first reading it and confirming the diff with the user if substantive content already exists.
- Do not modify the manuscript body, abstract, keywords, or bibliography. Only touch the preamble and the cover-letter insertion point.
- If the manuscript already declares a `CoverLetter` environment with content, treat the existing content as the source of truth and rewrite it to match the target journal; preserve any custom paragraphs the user has added unless they are obvious leftovers from a different paper.
- Reject requests to put the title page declarations inside the main manuscript. They must remain a separate file. Explain why: most journals require the title page as a separate upload to support double-blind review.
- In the graphical abstract, never invent results, numbers, or system components absent from the manuscript; never place a "Graphical Abstract" heading, caption, or synopsis inside the image; never exceed the approved font set (Times, Arial, Courier, Symbol).
- Never publish, share, or make public a Canva design without the user asking; keep the design private and only report its URL.

## Output checklist (gate)

Emit this checklist at the end of the response, every item checked ✓ or ✗ with a
justification. An unsanctioned ✗ (a skip not written in this file) requires the header
"PIPELINE INCOMPLETE — DO NOT USE".

```
[ ] CP1 — Metadata extracted from the main .tex (title, authors, affiliations, corresponding author identified)
[ ] CP2 — Missing mandatory fields collected via ONE grouped AskUserQuestion (or nothing was missing); no funding/contribution invented
[ ] CP3 — 10 most recent publications fetched via the Scopus helper; gaps or conference fill-ins documented, never fabricated
[ ] CP4 — Artifact 1: CoverLetter environment inserted in the main .tex (comment package in preamble, body between keywords and \maketitle, hidden by default), no <<...>> placeholder left
[ ] CP5 — Artifact 2: title-page.tex written with all 8 declaration subsections in order
[ ] CP6 — Artifact 3: corresponding-author-profile.tex written, no <<...>> placeholder left, corresponding author bolded in each publication entry
[ ] CP7 — Artifact 4: graphical abstract exported via Canva MCP (editor spec respected) OR Canva unavailability stated; FigureLabs prompt ALWAYS delivered either way
[ ] CP8 — Final report: paths of the four artifacts, compile commands, cover-letter toggle note, AI-generation disclosure note, unresolved Scopus entries listed
```

**Tools:** `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`, `AskUserQuestion`, Canva MCP (`mcp__claude_ai_Canva__*`: generate-design, generate-design-structured, upload-asset-from-url, start/commit-editing-transaction, perform-editing-operations, resize-design, export-design, get-design-thumbnail)
**Model:** `sonnet`

