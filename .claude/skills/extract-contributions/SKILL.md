---
name: extract-contributions
description: "Extract the stated scientific contribution of a cited paper from its full text, to check that a citation says what the paper actually claims. Companion to extract-futureworks: that one mines what a corpus says remains to be done, this one mines what each paper says it did. Two modes. Mode validate: for one manuscript, pair every cited key with its paper's own contribution sentences and flag the citations whose claim the paper does not support. Mode mine: sweep a refs/ corpus and tabulate what each paper contributes, for a related-work section or a novelty probe. Trigger on: validate a citation against the article, check that a reference supports the sentence citing it, contribution of each cited paper, extract-contributions, cohérence citation article."
---

# extract-contributions

## Why this exists

Measured 2026-09-12 on the BuildingGIS MITACS proposal. Fourteen references
were retained, and their claims written into the text, on the strength of their
**abstract alone**. Worse, six of the fourteen "full texts" were one-page
publisher previews, so even that abstract-level check had run on a stub.

The professor's objection is the whole specification of this skill:

> Je dois valider l'article et le contenu du texte de la demande. Si je n'ai pas
> l'article, je ne peux pas faire de validation. Il est strictement interdit
> d'inventer quelque chose qui n'est pas écrit.

An abstract states what a paper is *about*. It does not always state what the
paper *contributes*, and the sentence a citing author needs — "to the best of
our knowledge this is the first...", "unlike previous work, we..." — often lives
only in the introduction's contributions paragraph. Citing from the abstract is
how a reference ends up supporting a sentence it never made.

## Precondition, not an option

The full text must be in `refs/` **and verified**. `download_pdf.py` now refuses
a one-page paywall preview and continues its tier chain, but check anyway: a
paper whose text could not be read and a paper that states no contribution are
different findings, and this script keeps them apart (`unreadable`, `empty`,
`no-contribution`, `ok`).

## Modes

### Mode validate — one manuscript

```bash
python "$S" refs/ --manuscript paper.tex --json
python "$S" refs/ --manuscript paper.tex --write-contributions refs/_contributions
```

The script reads every `\cite{key}` of the manuscript, finds the sentence that
carries it, pairs that sentence with the cited paper's own contribution
sentences out of `refs/<key>.*`, and cross-checks every figure the citing
sentence attributes to the paper against the paper's full text. Then YOU judge,
one by one: does the citing sentence assert something the paper's own words
support? Emit a flagged finding for every citation where it does not.

What it does mechanically, so that a thirty-figure audit does not become an
impression:

- **Comments are blanked, not removed.** A commented-out `\cite` is not in the
  manuscript and auditing it would invent work, while removing the text would
  move every line number after it.
- **A multi-key `\cite{a,b}` is reported under both keys.** The sentence
  asserts something of both papers, so both are judged against it.
- **Structure ends a sentence.** A claim in the first sentence of a section
  would otherwise be handed to the reader carrying the section title.
- **Figures survive the decimal comma.** The manuscript may be French and the
  corpus English: "52,5 AP" and "52.5 AP" are one claim. A number `in_paper:
  false` is evidence, never a verdict - it may be the manuscript's own
  arithmetic, or a figure from a table the extractor lost.
- **A cited key with no file in `refs/` is `no-fulltext`**, never
  `no-contribution`. A retrieval gap is not a silent paper.

`--write-contributions DIR` keeps one Markdown note per cited paper: what the
paper says it contributes, and every sentence of the manuscript that cites it.
Put it under `refs/_contributions`; the leading underscore is what stops a later
corpus scan from reading those notes back as though they were papers.

The judgment is the agent's. The script only supplies the evidence, and
supplies it verbatim.

### Mode mine — a corpus

Sweep `refs/` and tabulate what each paper claims to contribute, by kind. Feeds
a related-work section, and feeds a novelty probe: a claim of the form "no
published framework does X" is worth far more when it is set against what every
paper in the corpus says it does.

## Usage

```bash
S=.claude/skills/extract-contributions/scripts/extract_contributions.py

python "$S" refs/amer2017roofstacking.pdf            # one paper, plain text
python "$S" refs/ --json > contributions.json        # whole corpus
python "$S" refs/ --only munda2012noncompensatory --only otto2026sanborn
python "$S" refs/ --strict                           # exit 1 if any paper is silent
```

Output per paper: `citekey`, `file`, `chars`, `status`, `kinds_found`, and the
contribution `sentences`, each with its `kind`, the `marker` that matched, and
a `position` between 0 and 1. Position is the sentence index over the sentence
count, so a contributions paragraph in the introduction (near 0.05) is
distinguishable from a claim restated in the conclusion (near 0.9) without
needing page numbers, which the text extractors do not preserve.

## What it does not do

**It does not decide.** It surfaces candidate sentences. The marker list is a
heuristic and it has false positives: on `amer2017roofstacking`, "The first
method is densification by filling the backyards" matched the `novelty` kind,
where "first" enumerates rather than claims priority. A reader settles that in
a second; a regex cannot. Treat `kinds_found` as a sorting aid, never as a
verdict.

**It does not read what is not there.** A paper that never states a
contribution returns `no-contribution`, which is a fact about the paper. An
unreadable PDF returns `unreadable` with the reason. Neither is ever reported
as the other.

## Where the pieces live

- `scripts/extract_contributions.py` — the CLI and the scan.
- `scripts/contribution_markers.json` — the phrases, as DATA (R6). Four kinds:
  `contribution`, `novelty`, `result`, `method`. Extend this file, not the
  module. A missing or empty catalogue is an explicit error (R3), because
  scanning with no markers would return "no contribution found" for every
  paper, which reads like a measurement and is not one.
- The PDF and HTML readers are **reused** from
  `extract-statistic/scripts/extract_text.py` (R18: one owner per capability).
  This skill ships no reader of its own.
- `scripts/Test/test_extract_contributions.py` — offline, no PDF, no network.
