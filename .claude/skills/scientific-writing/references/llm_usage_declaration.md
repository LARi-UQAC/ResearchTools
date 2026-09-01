# LLM usage declaration (UQAC IAg pictograms)

When a production has been authored with an AI tool, the level of generative-AI involvement is
declared with the UQAC pictogram that matches it. The system is maintained by the APTE team of the
UQAC library and is published at `https://www.uqac.ca/ressourcespedago/iag/`; the declaration
mechanism (pictogram or form) is at `https://www.uqac.ca/ressourcespedago/iag-declaration2/`.

Source read on 2026-08-12. The level definitions below are reproduced from that page and are not
paraphrased.

## The four levels

| Level | Pictogram name | Definition (source wording) | What it covers |
|---|---|---|---|
| **1. Aucune utilisation d'IAg** | Aucune utilisation | "La production n'a bénéficié d'aucune intervention de l'IAg, que ce soit pour le texte ou les images." | No AI involvement at all, text or image |
| **2. Assistance limitée de l'IAg** | Assistance limitée | "L'IA générative a été utilisée uniquement pour des suggestions ou des corrections mineures (orthographe, grammaire) ainsi que pour l'amélioration d'éléments visuels, tels que l'ajout d'un titre ou d'une légende, ou encore la traduction d'éléments présents dans une image." | Spelling, grammar, minor suggestions, caption or title touch-ups, image translation |
| **3. Production partagée avec l'IAg** | Assistance partagée | "Une contribution significative de l'IA générative est observée dans la création des contenus. Ces derniers ont été élaborés en partenariat avec l'IA générative, qui a joué un rôle important. Le contenu textuel a été en partie généré ou reformulé par celle-ci, tandis que les éléments visuels ont été majoritairement produits ou modifiés grâce à son intervention." | Text partly generated or reformulated by the model; visuals mostly produced or modified by it |
| **4. Production majoritairement assistée** | Assistance majeure | "Les contenus sont principalement le fruit d'un travail automatisé par l'IAg, avec une intervention humaine minimale (presque intégralement généré par l'IAg)." | Almost entirely model-generated, minimal human intervention |

## Pictogram files

Each level ships in a normal and a compact format, in two sizes each. Direct download links:

| Level | Normal 200x82 | Normal 500x204 | Compact 200x82 | Compact 272x152 |
|---|---|---|---|---|
| Aucune utilisation | [dl](https://drive.google.com/uc?export=download&id=1KPD8p0mmLmbwkML8VhJAz69WrvAgHoVb) | [dl](https://drive.google.com/uc?export=download&id=1KH_CSkswanb0rg48Dh9WRVXWMn7-920y) | [dl](https://drive.google.com/uc?export=download&id=1KU_JU0cSxtePwkLVyBq6BdprugyhR3Lm) | [dl](https://drive.google.com/uc?export=download&id=1JvTwTWB33_hFrE4dNsYr-ILlnEdQuAvz) |
| Assistance limitée | [dl](https://drive.google.com/uc?export=download&id=1KOpCg1hSwNzdgofM2mpKDHrLXAtABKEg) | [dl](https://drive.google.com/uc?export=download&id=1KHDP-kS8-v-rXM5CI4ocpHe5nHT0Q8l8) | [dl](https://drive.google.com/uc?export=download&id=1KQAg5MpYnCiYo2uyxHhAw5e773uPV2b5) | [dl](https://drive.google.com/uc?export=download&id=1JulKHxBXp1tkZy0D1i4caxLHFOdOsevH) |
| Assistance partagée | [dl](https://drive.google.com/uc?export=download&id=1KIzUjOF4HU0SfMDHApqpD1htnykJm2Sh) | [dl](https://drive.google.com/uc?export=download&id=1K8y04gllO70HON9wwd_BlI6QgvQOmP4N) | [dl](https://drive.google.com/uc?export=download&id=1KPUcZsG8sACU_CxL2zp-UKmE5gusr_gl) | [dl](https://drive.google.com/uc?export=download&id=1JsRwfTiDcQ-C1sX8G1H7X5iG5x76xt60) |
| Assistance majeure | [dl](https://drive.google.com/uc?export=download&id=1KLcm4w5Jr9_t9Bar7BvHSPj5Wr6UNOVL) | [dl](https://drive.google.com/uc?export=download&id=1KELNDr97K1cJk6HOFCI6jmYiS2o-GSLn) | [dl](https://drive.google.com/uc?export=download&id=1KPmptsRARk3ebrUQaTx0M6ARVD3KIjt8) | [dl](https://drive.google.com/uc?export=download&id=1JvS-k6oiv76JhRf5IKSpCc2AsPJEtLYk) |

Infographic of the whole scale:
`https://drive.google.com/file/d/1PZIdCwQbw43oQqSbpnL5HbQmpBw3j_t1/view?usp=sharing`

Licence: the pictograms may be used freely, without modification and without an obligation to cite;
point to `https://www.uqac.ca/ressourcespedago/iag/` where possible. The page text itself is
CC BY-ND 4.0. Citation of the source: Services de la bibliotheque - Accompagnement pedagogique et en
technologies educatives (APTE). (2025). Pictogrammes de declaration des niveaux d'utilisation de
l'intelligence artificielle generative (IAg). https://www.uqac.ca/ressourcespedago/iag/

## Recommended level per ResearchTools production

Rows are the productions this repo generates; columns are the declaration decision for each.

| Production | Tool that generates it | Recommended level | Pictogram | Why this level |
|---|---|---|---|---|
| **Reference search and validation only** | `scopus` skill, `bib-cleaner` | 1. Aucune utilisation | Aucune utilisation | A database is queried and metadata is normalised; no content is generated |
| **Language polish of a human-written draft** | `scientific-writing` revision pass | 2. Assistance limitée | Assistance limitée | Matches the level definition exactly: spelling, grammar, minor suggestions |
| **Caption or title touch-up, figure text translation** | `latex-writer`, `paper2talk` | 2. Assistance limitée | Assistance limitée | The level definition names caption addition and in-image translation explicitly |
| **Scientific paper drafted with the agents** | `latex-writer` + `scientific-writing` | 3. Production partagée | Assistance partagée | Text is partly generated or reformulated by the model, even when every claim is human-verified against Scopus |
| **Literature review** | `scopus-researcher` (`/litreview`) | 3. Production partagée | Assistance partagée | The synthesis prose is generated from validated sources |
| **Incremental review update** | `litreview-updater` (`/litupdate`) | 3. Production partagée | Assistance partagée | Same generation path as the review it extends |
| **Conference deck and speaker notes** | `paper2talk` / `talk-builder` | 3. Production partagée | Assistance partagée | Slide text and layout are model-produced from the paper |
| **Thesis or thesis proposal** | `latex-writer` + `thesis-auditor` | 3. Production partagée | Assistance partagée | Declare at the level actually reached; understating it is the failure mode that matters |
| **Support, recommendation, or cover letter** | `recommendation-letter`, `cover-paper` | 3. Production partagée | Assistance partagée | The letter body is model-drafted from the candidate's files |
| **Audit or improvement plan** | the four auditors | Declaration optional | - | An internal working document, not a production distributed under the author's name |
| **A section left as the model drafted it, unreviewed** | - | 4. Production majoritairement assistée | Assistance majeure | This level must be AVOIDED in an academic production: it signals that no human verification took place. If the audit measures it, the fix is to review and rewrite, not to declare it |

## How to apply the declaration

1. Choose the level from the table above, then verify it against what actually happened; the table is
   a default, not a substitute for judgment.
2. Download the normal or compact pictogram at the size that fits the production.
3. Place it where the reader will find it: the cover page, the acknowledgements, or beside the
   references. For a course production, the instructor states the required location; for a journal
   submission, the journal's AI-disclosure policy states it, and that policy overrides this file.
4. Point to `https://www.uqac.ca/ressourcespedago/iag/` where the medium allows a link.
5. An explanatory sentence under the pictogram is optional. When one is written, it follows the
   composition rules like any other sentence: impersonal, passive by default, no `I` (R1.1, R1.4).

LaTeX skeleton for a title-page declaration:

```latex
\begin{center}
  \includegraphics[width=0.28\textwidth]{figures/IAg_partagee.png}\\[2pt]
  {\footnotesize Niveau d'utilisation de l'IAg declare selon
  \href{https://www.uqac.ca/ressourcespedago/iag/}{le systeme de pictogrammes de l'UQAC}.}
\end{center}
```

## Relation to the measured AI-style risk score

The auditors compute an AI-style risk score (target below 10%). That score and this declaration
measure different things and must not be conflated:

- The **risk score** measures how much the prose LOOKS model-generated (em dashes, uniform sentence
  length, AI transition phrases). It is a style-hygiene metric.
- The **IAg level** declares how much the model actually CONTRIBUTED. It is an integrity statement.

A paper can carry a 4% risk score and still owe an "Assistance partagée" declaration, because the
prose was cleaned but was still model-drafted. The failure mode to flag is a declared level LOWER
than what the generation path implies.
