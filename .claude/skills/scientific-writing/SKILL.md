---
name: scientific-writing
description: "Core skill for the deep research and writing tool. Write scientific manuscripts in full paragraphs (never bullet points). Use two-stage process: (1) create section outlines with key points using research-lookup, (2) convert to flowing prose. IMRAD structure, citations (IEEE/APA/AMA/Vancouver), figures/tables, reporting guidelines (CONSORT/STROBE/PRISMA), for research papers and journal submissions."
allowed-tools: [Read, Write, Edit, Bash]
---

# Scientific Writing

## Overview

**This is the core skill for the deep research and writing tool**—combining AI-driven deep research with well-formatted written outputs. Every document produced is backed by comprehensive literature search and verified citations through the research-lookup skill (in ResearchTools, use the `scopus` skill for this role).

Scientific writing is a process for communicating research with precision and clarity. Write manuscripts using IMRAD structure, citations (IEEE/APA/AMA/Vancouver), figures/tables, and reporting guidelines (CONSORT/STROBE/PRISMA). Apply this skill for research papers and journal submissions.

**Critical Principle: Always write in full paragraphs with flowing prose. Never submit bullet points in the final manuscript.** Use a two-stage process: first create section outlines with key points using research-lookup (the `scopus` skill in ResearchTools), then convert those outlines into complete paragraphs.

## Applicability of the composition rules

`references/composition_rules.md` is the canonical source for sentence composition, list policy,
section structure, abstract format, and the journal-target protocol. Its rules bind EVERY document
this skill touches: journal and conference papers, theses, thesis proposals, literature reviews,
reviewer response letters, cover letters, recommendation and support letters, and Beamer slides.
There is no exempt document type.

The five rules that most often surprise a writer:

- Passive voice is the default. Active voice is a fallback used only where the passive obscures the
  agent (R1.1, R1.2).
- `I` is absolutely forbidden everywhere, and `we` is confined to the Contributions paragraph of the
  Introduction and to the Conclusion (R1.4, R1.5).
- The semicolon is avoided in prose, and sentences stay short: 15 to 20 words, never past roughly 30,
  one idea each (R1.7, R1.8). A semicolon marks a sentence that should have been two.
- Contributions are written as a prose paragraph with inline enumeration, never as a bulleted or
  numbered list (R2.7).
- The abstract carries no labels, no citation, no acronym, and no equation (R4.1-R4.4).

Consequence to flag, not to silently work around: a letter produced by the `recommendation-letter`
skill or by `cover-paper` may not open with "I am pleased to recommend". Use the impersonal
substitutes table in `composition_rules.md`.

## When to Use This Skill

This skill should be used when:
- Writing or revising any section of a scientific manuscript (abstract, introduction, methods, results, discussion)
- Structuring a research paper using IMRAD or other standard formats
- Formatting citations and references in specific styles (APA, AMA, Vancouver, Chicago, IEEE)
- Creating, formatting, or improving figures, tables, and data visualizations
- Applying study-specific reporting guidelines (CONSORT for trials, STROBE for observational studies, PRISMA for reviews)
- Drafting abstracts that meet journal requirements (structured or unstructured)
- Preparing manuscripts for submission to specific journals
- Improving writing clarity, conciseness, and precision
- Ensuring proper use of field-specific terminology and nomenclature
- Addressing reviewer comments and revising manuscripts

## LaTeX Academic Writing (ResearchTools)

**This is the authoritative case whenever the output is LaTeX (the default in this repo).** It mirrors
the project `.claude/CLAUDE.md`. Where this section and the generic guidance below disagree, this
section wins; the generic biomedical/journal-PDF material that follows is a fallback for non-LaTeX work.

- **Language**: French by default for a UQAC thesis, English for a scientific paper. LaTeX for all
  documents; Beamer for slides. When revising or auditing an existing document, respect its original
  language (a French document stays in French, an English document stays in English); the FR/EN
  default applies only to a new document.
- **Figures**: TiKZ (`.tikz`, for TiKZiT) is the default. The float rules and the 9 TiKZ geometry
  rules are now **enumerated** in `references/float_authoring_rules.md` (mirroring `.claude/CLAUDE.md`),
  not merely linked: relative positioning, perpendicular arrows, 3-character minimum spacing, no
  overlaps, simple TiKZiT-parsable code, `fig:three-words` label, cited with >= 2 sentences. That file
  also carries the overlap-prevention procedure and the mandatory `/tikz` + TiKZiT-render gates that
  confirm no arrow, box, or label superposes, the required `\usetikzlibrary` list (`positioning`,
  `arrows.meta`, `decorations.pathreplacing`, `backgrounds`), and the **drawio2tikz exception** for
  coordinate-exact converted figures (absolute coordinates, exempt from the relative / TiKZiT-simple /
  perpendicular rules but still labelled, cited, and captioned). AI-generated schematics (the
  `scientific-schematics` skill, if available) are **optional**. When it is unclear whether a figure should be hand-authored
  in TiKZ or AI-generated, **use AskUserQuestion before generating**.
- **Tables, equations, all floats**: defer to `references/float_authoring_rules.md` (canonical). In
  short: tables have rows = parameters / columns = concepts, first row and first column bold, first
  row 10% grey, `tab:three-words`, >= 2 sentences; equations are cited BEFORE the equation via
  `\eqref`, labelled `eq:three-words`, every variable defined directly under, `\text{,}`/`\text{.}`
  punctuation. Do not restate these here — follow that file.
- **Citations**: `\cite{}` with `firstauthor-year-keyword` labels; DOI written with `http` and made
  clickable via `hyperref` `\href`; every reference validated against Scopus with the `scopus` skill;
  references limited to the approved publishers (IEEE, Springer, Elsevier, Taylor & Francis,
  Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC) — any other publisher is cleared with the
  professor first; BibTeX (separate `.bib`) or inline `\bibitem`. See the override in
  `references/citation_styles.md`.
- **Sentence composition**: defer to `references/composition_rules.md` (canonical). Passive by
  default with active as a defensible fallback (R1.1, R1.2), academic register (R1.3), `I` forbidden
  everywhere and `we` confined to the Contributions paragraph and the Conclusion (R1.4, R1.5), no
  informal language (R1.6).
- **Lists**: no bullet survives into the final manuscript; lists are confined to the Methods and to
  Supplementary Materials, and never appear in the Abstract, Introduction, Results, Discussion, or
  Conclusions (R2.1-R2.6). Contributions are prose with inline enumeration (R2.7).
- **Captions**: `\caption{}` is exactly one short meaningful sentence, for a figure, a table, and
  each subfigure alike (C1, C2). All explanation lives in the main text beside the first `\ref{}`
  (C3), and table qualifications go in a `threeparttable` `tablenotes` block with `\tnote{}` anchors
  in `\footnotesize` (C4). See `references/float_authoring_rules.md`.
- **Abstract**: carries no labeled sections (R4.1), no citation (R4.2), no acronym (R4.3), and no
  equation (R4.4). Never use `\cite{}` (or any other reference) inside the abstract; introduce every
  reference later, in the body. The structured abstract is used only when the target journal
  explicitly requires it.
- **Journal target**: read the information for authors and the editor's template before authoring or
  judging compliance; ask the user for the link when neither is supplied (R5.1-R5.4).
- **LLM usage declaration**: recommend the matching UQAC IAg pictogram for the production, per
  `references/llm_usage_declaration.md`.
- **Section flow**: no section is left without text, and every section links to its neighbours. Follow
  the "Inter-section linking" rules in `references/writing_principles.md` — open each section (except
  the Introduction) with a backward link to the previous section's conclusion and a presentation of
  its subsections via `\ref{}` (R3.1, R3.3), and close each section (except the Conclusion / Future
  Works) with EXACTLY ONE sentence of conclusion followed by EXACTLY ONE sentence presenting the next
  section (R3.2).
- **Style hygiene**: keep the AI-usage score under 10%. Avoid the banned elements from `.claude/CLAUDE.md`:
  zero-width characters (U+200B/200C/200D), Unicode tag characters, "smart" curly quotes, the ellipsis
  character (use `...`), em dash and double/triple dash and en dash (prefer a simple hyphen `-` or
  parentheses), stray `*`/`#` markup, and overly perfect hierarchical lists.
- **Tooling**: `scopus` for references, `latex-writer` (with this skill) for authoring, `deliberation`
  for cross-model debate. The generic guidance below names a `research-lookup` skill; in this repo that
  role is filled by the `scopus` skill.

## Visual Enhancement with Scientific Schematics

**Optional — and only when LaTeX/TiKZ is not the chosen medium.** Under the LaTeX Academic Writing case
above, TiKZ is the default figure medium and AI-generated schematics are not required. The guidance
below applies when AI-generated figures have been chosen for a document; when the medium is unclear,
use AskUserQuestion before generating.

For a non-LaTeX document that uses AI-generated figures:
1. Generate at least ONE schematic or diagram using scientific-schematics (if the skill is available)
2. Prefer 2-3 figures for comprehensive papers (methods flowchart, results visualization, conceptual diagram)

**How to generate figures:**
- Use the **scientific-schematics** skill to generate AI-powered publication-quality diagrams
- Simply describe your desired diagram in natural language
- Nano Banana Pro will automatically generate, review, and refine the schematic

**How to generate schematics:**
```bash
python scripts/generate_schematic.py "your diagram description" -o figures/output.png
```

The AI will automatically:
- Create publication-quality images with proper formatting
- Review and refine through multiple iterations
- Ensure accessibility (colorblind-friendly, high contrast)
- Save outputs in the figures/ directory

**When to add schematics:**
- Study design and methodology flowcharts (CONSORT, PRISMA, STROBE)
- Conceptual framework diagrams
- Experimental workflow illustrations
- Data analysis pipeline diagrams
- Biological pathway or mechanism diagrams
- System architecture visualizations
- Any complex concept that benefits from visualization

For detailed guidance on creating schematics, refer to the scientific-schematics skill documentation.

---

## Core Capabilities

### 1. Manuscript Structure and Organization

**IMRAD Format**: Guide papers through the standard Introduction, Methods, Results, And Discussion structure used across most scientific disciplines. This includes:
- **Introduction**: Establish research context, identify gaps, state objectives
- **Methods**: Detail study design, populations, procedures, and analysis approaches
- **Results**: Present findings objectively without interpretation
- **Discussion**: Interpret results, acknowledge limitations, propose future directions

For detailed guidance on IMRAD structure, refer to `references/imrad_structure.md`.

**Alternative Structures**: Support discipline-specific formats including:
- Review articles (narrative, systematic, scoping)
- Case reports and case series
- Meta-analyses and pooled analyses
- Theoretical/modeling papers
- Methods papers and protocols

### 2. Section-Specific Writing Guidance

**Abstract Composition**: Craft concise, standalone summaries (100-250 words) that capture the paper's purpose, methods, results, and conclusions. The unstructured flowing-paragraph format is the default (R4.1); the structured format with labeled sections is used only when the target journal explicitly requires it in its author guidelines. The abstract carries no citation, no acronym, and no equation (R4.2-R4.4).

**Introduction Development**: Build compelling introductions that:
- Establish the research problem's importance
- Review relevant literature systematically
- Identify knowledge gaps or controversies
- State clear research questions or hypotheses
- Explain the study's novelty and significance

**Methods Documentation**: Ensure reproducibility through:
- Detailed participant/sample descriptions
- Clear procedural documentation
- Statistical methods with justification
- Equipment and materials specifications
- Ethical approval and consent statements

**Results Presentation**: Present findings with:
- Logical flow from primary to secondary outcomes
- Integration with figures and tables
- Statistical significance with effect sizes
- Objective reporting without interpretation

**Discussion Construction**: Synthesize findings by:
- Relating results to research questions
- Comparing with existing literature
- Acknowledging limitations honestly
- Proposing mechanistic explanations
- Suggesting practical implications and future research

### 3. Citation and Reference Management

Apply citation styles correctly across disciplines. For comprehensive style guides, refer to `references/citation_styles.md`.

**Major Citation Styles:**
- **AMA (American Medical Association)**: Numbered superscript citations, common in medicine
- **Vancouver**: Numbered citations in square brackets, biomedical standard
- **APA (American Psychological Association)**: Author-date in-text citations, common in social sciences
- **Chicago**: Notes-bibliography or author-date, humanities and sciences
- **IEEE**: Numbered square brackets, engineering and computer science

**Best Practices:**
- Cite primary sources when possible
- Include recent literature (last 5-10 years for active fields)
- Balance citation distribution across introduction and discussion
- Verify all citations against original sources
- Use reference management software (Zotero, Mendeley, EndNote)

### 4. Figures and Tables

Create effective data visualizations that enhance comprehension. For detailed best practices, refer to `references/figures_tables.md`.

**When to Use Tables vs. Figures:**
- **Tables**: Precise numerical data, complex datasets, multiple variables requiring exact values
- **Figures**: Trends, patterns, relationships, comparisons best understood visually

**Design Principles:**
- In LaTeX output, keep `\caption{}` to exactly one short meaningful sentence and put the explanation in the main text beside the first `\ref{}` (C1, C3); the "self-explanatory complete caption" pattern applies only to non-LaTeX media
- Use consistent formatting and terminology across all display items
- Label all axes, columns, and rows with units
- Include sample sizes (n) and statistical annotations
- Follow the "one table/figure per 1000 words" guideline
- Avoid duplicating information between text, tables, and figures

**Common Figure Types:**
- Bar graphs: Comparing discrete categories
- Line graphs: Showing trends over time
- Scatterplots: Displaying correlations
- Box plots: Showing distributions and outliers
- Heatmaps: Visualizing matrices and patterns

### 5. Reporting Guidelines by Study Type

Ensure completeness and transparency by following established reporting standards. For comprehensive guideline details, refer to `references/reporting_guidelines.md`.

**Key Guidelines:**
- **CONSORT**: Randomized controlled trials
- **STROBE**: Observational studies (cohort, case-control, cross-sectional)
- **PRISMA**: Systematic reviews and meta-analyses
- **STARD**: Diagnostic accuracy studies
- **TRIPOD**: Prediction model studies
- **ARRIVE**: Animal research
- **CARE**: Case reports
- **SQUIRE**: Quality improvement studies
- **SPIRIT**: Study protocols for clinical trials
- **CHEERS**: Economic evaluations

Each guideline provides checklists ensuring all critical methodological elements are reported.

### 6. Writing Principles and Style

Apply fundamental scientific writing principles. For detailed guidance, refer to `references/writing_principles.md`.

**Clarity**:
- Use precise, unambiguous language
- Define technical terms and abbreviations at first use
- Maintain logical flow within and between paragraphs
- Use active voice when appropriate for clarity

**Conciseness**:
- Eliminate redundant words and phrases
- Favor shorter sentences (15-20 words average, never past roughly 30) — one idea per sentence (R1.8)
- Avoid the semicolon in prose: split the two clauses into two sentences, or use a colon when the
  second explains the first, or a comma plus a conjunction when they are short and coordinate (R1.7)
- Remove unnecessary qualifiers
- Respect word limits strictly

**Accuracy**:
- Report exact values with appropriate precision
- Use consistent terminology throughout
- Distinguish between observations and interpretations
- Acknowledge uncertainty appropriately

**Objectivity**:
- Present results without bias
- Avoid overstating findings or implications
- Acknowledge conflicting evidence
- Maintain professional, neutral tone

### 7. Writing Process: From Outline to Full Paragraphs

**CRITICAL: Always write in full paragraphs, never submit bullet points in scientific papers.**

Scientific papers must be written in complete, flowing prose. Use this two-stage approach for effective writing:

**Stage 1: Create Section Outlines with Key Points**

When starting a new section:
1. Use the research-lookup skill (the `scopus` skill in ResearchTools) to gather relevant literature and data
2. Create a structured outline with bullet points marking:
   - Main arguments or findings to present
   - Key studies to cite
   - Data points and statistics to include
   - Logical flow and organization
3. These bullet points serve as scaffolding—they are NOT the final manuscript

**Example outline (Introduction section):**
```
- Background: AI in drug discovery gaining traction
  * Cite recent reviews (Smith 2023, Jones 2024)
  * Traditional methods are slow and expensive
- Gap: Limited application to rare diseases
  * Only 2 prior studies (Lee 2022, Chen 2023)
  * Small datasets remain a challenge
- Our approach: Transfer learning from common diseases
  * Novel architecture combining X and Y
- Study objectives: Validate on 3 rare disease datasets
```

**Stage 2: Convert Key Points to Full Paragraphs**

Once the outline is complete, expand each bullet point into proper prose:

1. **Transform bullet points into complete sentences** with subjects, verbs, and objects
2. **Add transitions** between sentences and ideas (however, moreover, in contrast, subsequently)
3. **Integrate citations naturally** within sentences, not as lists
4. **Expand with context and explanation** that bullet points omit
5. **Ensure logical flow** from one sentence to the next within each paragraph
6. **Vary sentence structure** to maintain reader engagement

**Example conversion to prose:**

```
Artificial intelligence approaches have gained significant traction in drug discovery 
pipelines over the past decade (Smith, 2023; Jones, 2024). While these computational 
methods show promise for accelerating the identification of therapeutic candidates, 
traditional experimental approaches remain slow and resource-intensive, often requiring 
years of laboratory work and substantial financial investment. However, the application 
of AI to rare diseases has been limited, with only two prior studies demonstrating 
proof-of-concept results (Lee, 2022; Chen, 2023). The primary obstacle has been the 
scarcity of training data for conditions affecting small patient populations. 

To address this challenge, we developed a transfer learning approach that leverages 
knowledge from well-characterized common diseases to predict therapeutic targets for 
rare conditions. Our novel neural architecture combines convolutional layers for 
molecular feature extraction with attention mechanisms for protein-ligand interaction 
modeling. The objective of this study was to validate our approach across three 
independent rare disease datasets, assessing both predictive accuracy and biological 
interpretability of the results.
```

**Key Differences Between Outlines and Final Text:**

| Outline (Planning Stage) | Final Manuscript |
|--------------------------|------------------|
| Bullet points and fragments | Complete sentences and paragraphs |
| Telegraphic notes | Full explanations with context |
| List of citations | Citations integrated into prose |
| Abbreviated ideas | Developed arguments with transitions |
| For your eyes only | For publication and peer review |

**Common Mistakes to Avoid:**

- ❌ **Never** leave bullet points in the final manuscript
- ❌ **Never** submit lists where paragraphs should be
- ❌ **Don't** use numbered or bulleted lists in Results or Discussion sections (except for specific cases like study hypotheses or inclusion criteria)
- ❌ **Don't** write sentence fragments or incomplete thoughts
- ✅ **Do** use occasional lists only in Methods (e.g., inclusion/exclusion criteria, materials lists)
- ✅ **Do** ensure every section flows as connected prose
- ✅ **Do** read paragraphs aloud to check for natural flow
- ✅ **Do** present every subsection of a section in that section's opening paragraph, via `\ref{}` (R3.1)
- ✅ **Do** close every section, except the Conclusion and Future Works, with exactly one conclusion sentence and exactly one sentence presenting the next section (R3.2)
- ❌ **Never** write a contribution list as bullets; contributions are prose with inline enumeration (R2.7)

**When Lists ARE Acceptable (Limited Cases):**

Lists may appear in scientific papers only in specific contexts:
- **Methods**: Inclusion/exclusion criteria, materials and reagents, participant characteristics
- **Supplementary Materials**: Extended protocols, equipment lists, detailed parameters
- **Never in**: Abstract, Introduction, Results, Discussion, Conclusions

**Integration with Research Lookup:**

The research-lookup skill (the `scopus` skill in ResearchTools) is essential for Stage 1 (creating outlines):
1. Search for relevant papers using research-lookup
2. Extract key findings, methods, and data
3. Organize findings as bullet points in your outline
4. Then convert the outline to full paragraphs in Stage 2

This two-stage process ensures you:
- Gather and organize information systematically
- Create logical structure before writing
- Produce polished, publication-ready prose
- Maintain focus on the narrative flow

### 8. Journal-Specific Formatting

Adapt manuscripts to journal requirements:
- Follow author guidelines for structure, length, and format
- Apply journal-specific citation styles
- Meet figure/table specifications (resolution, file formats, dimensions)
- Include required statements (funding, conflicts of interest, data availability, ethical approval)
- Adhere to word limits for each section
- Format according to template requirements when provided

### 9. Field-Specific Language and Terminology

Adapt language, terminology, and conventions to match the specific scientific discipline. Each field has established vocabulary, preferred phrasings, and domain-specific conventions that signal expertise and ensure clarity for the target audience.

**Identify Field-Specific Linguistic Conventions:**
- Review terminology used in recent high-impact papers in the target journal
- Note field-specific abbreviations, units, and notation systems
- Identify preferred terms (e.g., "participants" vs. "subjects," "compound" vs. "drug," "specimens" vs. "samples")
- Observe how methods, organisms, or techniques are typically described

**Biomedical and Clinical Sciences:**
- Use precise anatomical and clinical terminology (e.g., "myocardial infarction" not "heart attack" in formal writing)
- Follow standardized disease nomenclature (ICD, DSM, SNOMED-CT)
- Specify drug names using generic names first, brand names in parentheses if needed
- Use "patients" for clinical studies, "participants" for community-based research
- Follow Human Genome Variation Society (HGVS) nomenclature for genetic variants
- Report lab values with standard units (SI units in most international journals)

**Molecular Biology and Genetics:**
- Use italics for gene symbols (e.g., *TP53*), regular font for proteins (e.g., p53)
- Follow species-specific gene nomenclature (uppercase for human: *BRCA1*; sentence case for mouse: *Brca1*)
- Specify organism names in full at first mention, then use accepted abbreviations (e.g., *Escherichia coli*, then *E. coli*)
- Use standard genetic notation (e.g., +/+, +/-, -/- for genotypes)
- Employ established terminology for molecular techniques (e.g., "quantitative PCR" or "qPCR," not "real-time PCR")

**Chemistry and Pharmaceutical Sciences:**
- Follow IUPAC nomenclature for chemical compounds
- Use systematic names for novel compounds, common names for well-known substances
- Specify chemical structures using standard notation (e.g., SMILES, InChI for databases)
- Report concentrations with appropriate units (mM, μM, nM, or % w/v, v/v)
- Describe synthesis routes using accepted reaction nomenclature
- Use terms like "bioavailability," "pharmacokinetics," "IC50" consistently with field definitions

**Ecology and Environmental Sciences:**
- Use binomial nomenclature for species (italicized: *Homo sapiens*)
- Specify taxonomic authorities at first species mention when relevant
- Employ standardized habitat and ecosystem classifications
- Use consistent terminology for ecological metrics (e.g., "species richness," "Shannon diversity index")
- Describe sampling methods with field-standard terms (e.g., "transect," "quadrat," "mark-recapture")

**Physics and Engineering:**
- Follow SI units consistently unless field conventions dictate otherwise
- Use standard notation for physical quantities (scalars vs. vectors, tensors)
- Employ established terminology for phenomena (e.g., "quantum entanglement," "laminar flow")
- Specify equipment with model numbers and manufacturers when relevant
- Use mathematical notation consistent with field standards (e.g., ℏ for reduced Planck constant)

**Neuroscience:**
- Use standardized brain region nomenclature (e.g., refer to atlases like Allen Brain Atlas)
- Specify coordinates for brain regions using established stereotaxic systems
- Follow conventions for neural terminology (e.g., "action potential" not "spike" in formal writing)
- Use "neural activity," "neuronal firing," "brain activation" appropriately based on measurement method
- Describe recording techniques with proper specificity (e.g., "whole-cell patch clamp," "extracellular recording")

**Social and Behavioral Sciences:**
- Use person-first language when appropriate (e.g., "people with schizophrenia" not "schizophrenics")
- Employ standardized psychological constructs and validated assessment names
- Follow APA guidelines for reducing bias in language
- Specify theoretical frameworks using established terminology
- Use "participants" rather than "subjects" for human research

**General Principles:**

**Match Audience Expertise:**
- For specialized journals: Use field-specific terminology freely, define only highly specialized or novel terms
- For broad-impact journals (e.g., *Nature*, *Science*): Define more technical terms, provide context for specialized concepts
- For interdisciplinary audiences: Balance precision with accessibility, define terms at first use

**Define Technical Terms Strategically:**
- Define abbreviations at first use: "messenger RNA (mRNA)"
- Provide brief explanations for specialized techniques when writing for broader audiences
- Avoid over-defining terms well-known to the target audience (signals unfamiliarity with field)
- Create a glossary if numerous specialized terms are unavoidable

**Maintain Consistency:**
- Use the same term for the same concept throughout (don't alternate between "medication," "drug," and "pharmaceutical")
- Follow a consistent system for abbreviations (decide on "PCR" or "polymerase chain reaction" after first definition)
- Apply the same nomenclature system throughout (especially for genes, species, chemicals)

**Avoid Field Mixing Errors:**
- Don't use clinical terminology for basic science (e.g., don't call mice "patients")
- Avoid colloquialisms or overly general terms in place of precise field terminology
- Don't import terminology from adjacent fields without ensuring proper usage

**Verify Terminology Usage:**
- Consult field-specific style guides and nomenclature resources
- Check how terms are used in recent papers from the target journal
- Use domain-specific databases and ontologies (e.g., Gene Ontology, MeSH terms)
- When uncertain, cite a key reference that establishes terminology

### 10. Common Pitfalls to Avoid

**Top Rejection Reasons:**
1. Inappropriate, incomplete, or insufficiently described statistics
2. Over-interpretation of results or unsupported conclusions
3. Poorly described methods affecting reproducibility
4. Small, biased, or inappropriate samples
5. Poor writing quality or difficult-to-follow text
6. Inadequate literature review or context
7. Figures and tables that are unclear or poorly designed
8. Failure to follow reporting guidelines

**Writing Quality Issues:**
- Long sentences carrying two or three ideas, usually spliced with a semicolon (R1.7, R1.8)
- Mixing tenses inappropriately (use past tense for methods/results, present for established facts)
- Excessive jargon or undefined acronyms
- Paragraph breaks that disrupt logical flow
- Missing transitions between sections
- Inconsistent notation or terminology

## Workflow for Manuscript Development

**Stage 1: Planning**
1. Identify target journal and review author guidelines
2. Determine applicable reporting guideline (CONSORT, STROBE, etc.)
3. Outline manuscript structure (usually IMRAD)
4. Plan figures and tables as the backbone of the paper

**Stage 2: Drafting** (Use two-stage writing process for each section)
1. Start with figures and tables (the core data story)
2. For each section below, follow the two-stage process:
   - **First**: Create outline with bullet points using research-lookup (the `scopus` skill in ResearchTools)
   - **Second**: Convert bullet points to full paragraphs with flowing prose
3. Write Methods (often easiest to draft first)
4. Draft Results (describing figures/tables objectively)
5. Compose Discussion (interpreting findings)
6. Write Introduction (setting up the research question)
7. Craft Abstract (synthesizing the complete story)
8. Create Title (concise and descriptive)

**Remember**: Bullet points are for planning only—the final manuscript must be in complete paragraphs.

**Stage 3: Revision**
1. Check logical flow and "red thread" throughout
2. Verify consistency in terminology and notation
3. Ensure figures/tables are self-explanatory
4. Confirm adherence to reporting guidelines
5. Verify all citations are accurate and properly formatted
6. Check word counts for each section
7. Proofread for grammar, spelling, and clarity

**Stage 4: Final Preparation**
1. Format according to journal requirements
2. Prepare supplementary materials
3. Write cover letter highlighting significance
4. Complete submission checklists
5. Gather all required statements and forms

## Integration with Other Scientific Skills

This skill works effectively with:
- **Data analysis skills**: For generating results to report
- **Statistical analysis**: For determining appropriate statistical presentations
- **Literature review skills**: For contextualizing research
- **Figure creation tools**: For developing publication-quality visualizations

## References

This skill includes comprehensive reference files covering specific aspects of scientific writing:

- `references/composition_rules.md`: Canonical ResearchTools rules for sentence composition (passive default, pronoun ban), lists and prose, section structure, abstract format, and the journal-target protocol. Authoritative over the generic guidance in `writing_principles.md` and `imrad_structure.md`.
- `references/llm_usage_declaration.md`: The four UQAC IAg usage levels, their pictograms, and the recommended level per ResearchTools production type.
- `references/float_authoring_rules.md`: Canonical ResearchTools rules for every figure, table, equation, and caption (label, citation, explanation, one-sentence caption, `threeparttable` notes, table orientation/bold/grey, equation citation-before/variables/punctuation). Authoritative for LaTeX floats — follow this over the generic figure/table guidance.
- `references/imrad_structure.md`: Detailed guide to IMRAD format and section-specific content
- `references/citation_styles.md`: Complete citation style guides (APA, AMA, Vancouver, Chicago, IEEE); see the ResearchTools override at the top for the LaTeX `\cite`/BibTeX policy
- `references/figures_tables.md`: Best practices for creating effective data visualizations; see the ResearchTools/LaTeX override at the top
- `references/reporting_guidelines.md`: Study-specific reporting standards and checklists
- `references/writing_principles.md`: Core principles of effective scientific communication

Load these references as needed when working on specific aspects of scientific writing.
