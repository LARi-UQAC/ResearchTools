# Undergraduate technical report framework

For lab reports and project reports of undergraduate students. The research framework
(`evaluation_framework.md`) is unchanged and is not used here. This framework is written so that a
mid-size local model can apply it from the prompt alone.

## What is judged

One rubric item at a time, on its own evidence. A report is judged on what a competent undergraduate
can do: describe a method, apply a formula correctly, present results with units, draw a sound
conclusion. Research-level depth (a literature review, a novelty claim) is not expected and never
costs points.

## Anchored levels

The score of an item is a share of its maximum points. Use only these five anchors.

| Level | Share | When it applies |
|---|---|---|
| absent | 0 | The element the item asks for is not in the report. |
| attempted | 0.5 | The element is present but largely wrong, or most of its parts are missing. |
| partial | 0.75 | The element is present and mostly right, but a part is missing or a technical error remains. |
| complete and correct | 0.88 | Every part asked for is present and correct. This is the normal good report. |
| exemplary | 1.0 | Complete, correct and clearly better than expected: rare, and only with strong evidence. |

"Complete and correct" is 88 percent of the item and not 100 percent. A full mark is exceptional.

## What costs points

- A missing element asked for by the item or its checklist.
- A technical error: a wrong formula, a wrong unit, a result that contradicts the data, a conclusion the
  results do not support.

## What never costs points in an item

- Spelling, grammar and style: a separate step lists them and they do not move the score.
- References, unless the item is about references.
- Figures, unless the item covers figures.
- Research-level depth.

## Statuses

- `rated`: the item applies and a score between 0 and the maximum is given. A score of 0 is allowed for
  an absent element.
- `not_applicable`: the item cannot apply to this report. No score. It is left out of the maximum.
- `not_run`: set by the program when a model could not run. A model never answers it, and it is never a
  zero: the total of the report is withheld until it is graded.

## Evidence

Every score under the maximum quotes the report word for word, with the page number. A quote is one
sentence or less. A comment says what is missing or wrong in at most two sentences, in the language of
the report, in a respectful tone.

## Calibration

The professor expects a batch around 88 percent with a standard deviation of about 4 points. A batch
far above or below is graded again with the batch figures given to the grader. The framework itself does
not change between loops: the anchors stay the same and the grader is asked to apply them more carefully.
