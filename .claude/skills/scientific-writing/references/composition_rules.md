# Manuscript composition rules

Canonical, project-wide rules for how sentences, lists, sections, and abstracts are COMPOSED. The
companion file `float_authoring_rules.md` governs the floats themselves (figures, tables, equations)
and their captions; this file governs the prose around them.

These rules bind at authoring time AND when an audit plan is executed. They apply to EVERY document
this skill touches: journal papers, conference papers, theses, thesis proposals, literature reviews,
reviewer response letters, cover letters, recommendation and support letters, and Beamer slides.
There is no document type that is exempt.

Where this file and the generic biomedical / journal-PDF guidance in `writing_principles.md`,
`imrad_structure.md`, or `figures_tables.md` disagree, THIS FILE WINS.

## 1. Sentence composition

- **R1.1 Passive by default.** Sentences are written in the passive voice or in an impersonal form.
  This is the default register for every section of every document.
- **R1.2 Active voice is a fallback, not a preference.** Active voice is used only where the passive
  genuinely obscures who acted, or produces an ambiguous, contorted, or unreadable sentence. Every
  active-voice sentence must be defensible on that ground. "It reads better" is not a ground.
- **R1.3 Academic register.** Write in an academic style with a high level of scientific literacy:
  precise terminology, full syntactic sentences, no conversational connectives.
- **R1.4 The pronoun `I` is absolutely forbidden.** In every document, in every section, without
  exception. The same ban covers `my`, `me`, and `mine`. A letter that would naturally open with
  "I am pleased to recommend" is reworded impersonally.
- **R1.5 The pronoun `we` is confined to two places.** `we`, `our`, and `us` are permitted ONLY in
  the Contributions paragraph of the Introduction, and in the Conclusion. They are forbidden in the
  Abstract, the Literature review, the Methodology, the Results, the Discussion, the Future works,
  every caption, and every letter.
- **R1.6 No informal language.** No contractions, no colloquialisms, no vague quantifiers standing
  in for a measured value ("a lot of", "got", "showed up", "pretty much").

### Impersonal substitutes

| Forbidden form | Compliant form |
|---|---|
| "I propose a variable-speed planner." | "A variable-speed planner is proposed." |
| "We measured the torque at each joint." | "The torque was measured at each joint." |
| "We can see in Figure 2 that ..." | "Figure~\ref{fig:speed-profile} shows that ..." |
| "Our method outperforms the baseline." | "The proposed method outperforms the baseline." |
| "In this paper we present ..." | "This paper presents ..." |
| "I am pleased to recommend the candidate." | "The candidate is recommended without reservation." |
| "We aimed to examine the effect." | "The study aimed to examine the effect." |

The last row supersedes the anthropomorphism fix shown in `writing_principles.md`: the cure for
"The study wanted to examine" is the impersonal "The study aimed to examine", never "We aimed to
examine".

## 2. Lists and prose

- **R2.1** No bullet points survive into the final manuscript. Bullets are a planning scaffold only.
- **R2.2** No list stands where a paragraph belongs.
- **R2.3** No numbered or bulleted list appears in the Results or the Discussion.
- **R2.4** No sentence fragments and no incomplete thoughts.
- **R2.5** A list is acceptable only in the Methods (inclusion and exclusion criteria, materials and
  reagents, participant characteristics) and in Supplementary Materials (extended protocols,
  equipment lists, detailed parameters).
- **R2.6** A list NEVER appears in the Abstract, the Introduction, the Results, the Discussion, or
  the Conclusions.
- **R2.7 Contributions are prose.** A contribution-oriented Introduction is still valid, but the
  contributions are written as a flowing paragraph with inline enumeration, never as an `itemize` or
  `enumerate` environment and never as bullets. This rule supersedes the "numbered contributions"
  style shown for ML conferences in `writing_principles.md`.

  Non-compliant:

  ```latex
  The main contributions of this paper are:
  \begin{itemize}
    \item a novel sparse attention mechanism;
    \item a theoretical analysis of the preserved expressive power;
    \item an empirical validation on ImageNet.
  \end{itemize}
  ```

  Compliant:

  ```latex
  Three contributions are made by this paper. First, a sparse attention mechanism is introduced that
  reduces the complexity from quadratic to log-linear. Second, a theoretical analysis is derived that
  shows the expressive power of the dense formulation is preserved. Third, an empirical validation on
  ImageNet is reported, in which a 15\% speedup is obtained at comparable accuracy.
  ```

- **R2.8** Every section reads as connected prose, not as a sequence of disconnected assertions.
- **R2.9** Each paragraph is read aloud, or read as if aloud, to confirm that the flow is natural.

## 3. Section structure

- **R3.1 Every section presents its own subsections.** A section never jumps from its `\section`
  title straight to a `\subsection`. It opens with an introductory paragraph, and that paragraph
  presents every subsection of the section through a `\ref{}` to that subsection's `\label`. Each
  subsection therefore carries a `\label` that the opening paragraph can reference.
- **R3.2 Every section closes with one sentence of conclusion and one sentence of announcement.**
  Each section, except the Conclusion and the Future works, ends with exactly one sentence stating
  what the section established, followed by exactly one sentence presenting the next section. Two
  sentences, no more.
- **R3.3 Every section opens with a backward link.** Each section except the Introduction opens with
  a backward link to the conclusion of the previous section, before it presents its own subsections
  under R3.1.

Compliant closing:

```latex
The proposed energy model was therefore shown to depend jointly on the robot speed and on the
displaced mass. The experimental protocol used to identify its coefficients is presented in
Section~\ref{sec:experimental-protocol}.
```

## 4. Abstract

- **R4.1 No labeled sections.** The abstract is never written with labels such as `Background:`,
  `Methods:`, `Results:`, or `Conclusions:`. It is written as flowing paragraph or paragraphs with
  natural transitions. **Exception:** the structured form is used only when the target journal
  explicitly requires it in its author guidelines, and the requirement is recorded under R5.4.
- **R4.2 No references.** The abstract carries no `\cite{}`, no `\citep`, no `\citet`, no
  `\bibitem` pointer, and no bare numeric reference marker.
- **R4.3 No acronyms.** The full name of every concept is written out. An acronym is never
  introduced, defined, or used inside the abstract, even when it is defined later in the body. This
  supersedes the "define at first use in the abstract" guidance in `writing_principles.md`.
- **R4.4 No equations.** No display equation, no `\begin{equation}`, and no inline math `$...$`
  appears in the abstract. A quantity is stated in words and digits.

## 5. When a journal is the target

Applies both when authoring for that journal and when auditing a manuscript aimed at it.

- **R5.1** The information for authors AND the journal template from the editor are read before any
  authoring or compliance judgment is made.
- **R5.2** If neither is supplied, ASK the user for the link to the journal's information-for-authors
  page with `AskUserQuestion`. Do not guess the journal's rules and do not proceed on a remembered
  version of them.
- **R5.3** Read the link with `WebFetch`. When the page is script-rendered and `WebFetch` returns an
  empty or partial body, read it with the `playwright` MCP tools instead. For the template itself,
  ask the user to download the `.docx`, `.tex`, or `.zip` package, then read it (`word2latex` handles
  a `.docx` gabarit).
- **R5.4** Record, in the document's plan or header comment, every journal requirement that overrides
  a default rule of this file. The structured-abstract exception of R4.1 is the common case.

## Self-check before finalizing

For the document being authored or the plan being written, verify and resolve every miss:

- [ ] R1.1 / R1.2: each active-voice sentence carries a defensible reason; otherwise it is passive
- [ ] R1.4: zero occurrences of `I`, `my`, `me`, `mine` as first-person pronouns
- [ ] R1.5: `we` / `our` / `us` occur only in the Contributions paragraph and in the Conclusion
- [ ] R1.6: no informal term, no contraction, no vague quantifier standing in for a value
- [ ] R2.6: no list in Abstract, Introduction, Results, Discussion, Conclusions
- [ ] R2.7: contributions are a prose paragraph, not an `itemize` / `enumerate` block
- [ ] R3.1: every section opens on a paragraph that `\ref{}`s each of its subsections
- [ ] R3.2: every section except Conclusion and Future works closes on exactly one conclusion
      sentence plus exactly one announcement sentence
- [ ] R4.1-R4.4: abstract has no labels, no citation, no acronym, no equation
- [ ] R5.1-R5.4: journal guidelines read, or requested, and every override recorded
