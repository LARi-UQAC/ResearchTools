# Language categories - one rule per code

The codes, labels, severity, scope and actions live in `../assets/language_categories.json`; this page
gives each code its meaning and one French and one English example. The full composition rules are not
copied here: read `../../scientific-writing/references/composition_rules.md` for R1.x and R2.x.

Every example below is fictitious.

## Codes split from reviewer-response G (grammar, spelling)

**SP - Spelling / Orthographe.** A word misspelled or with a wrong accent.
- FR: "Le régulateur est intégré au procédé" (not "intégrer au procédé").
- EN: "The receiver was calibrated" (not "reciever").

**AG - Agreement / Accord.** Gender, number or tense agreement broken.
- FR: "Les valeurs mesurées sont stables" (not "Les valeurs mesuré est stable").
- EN: "The data were filtered" in a lab using the plural convention; "the results show" (not "shows").

**PN - Punctuation / Ponctuation.** A comma splice, a missing comma, or the French spacing before `:`,
`;`, `?`, `!` broken. The semicolon in prose has its own code, SEMI.
- FR: "Le gain est fixé à 2 : la réponse reste stable."
- EN: "After tuning, the response settled within 2 s."

**TYPO - Typography / Typographie.** Units, symbols, quotation marks, number formatting.
- FR: "12,5 °C" with a decimal comma and a space before the unit.
- EN: "12.5 °C", "5 ms" (not "5ms").

## Codes split from reviewer-response S (style)

**SST - Sentence structure / Structure de la phrase.** Word order or syntax that blurs the meaning.
- FR: "Le capteur, placé en amont, mesure le débit."
- EN: "The sensor placed upstream measures the flow."

**REG - Academic register / Registre scientifique (R1.3).** Wording below an academic level.
- FR: "L'écart est attribué au frottement" (not "ça vient sûrement du frottement").
- EN: "The deviation is attributed to friction."

**TERM - Terminology / Terminologie.** A technical term misused or inconsistent across the text.
- FR: "fonction de transfert" used throughout (not alternated with "fonction de transmission").
- EN: "transfer function" used throughout.

## Composition flags of the research auditors

Each keeps the exact bracket text the auditors print, so a plan reads the same before and after the
migration.

**AV - `[ACTIVE VOICE UNJUSTIFIED]` (R1.1, R1.2).** An active sentence where the passive would hide
nothing.
- FR: "Le modèle a été validé sur trois jeux de données."
- EN: "The model was validated on three datasets."

**PI - `[PRONOUN I FORBIDDEN]` (R1.4).**
- FR: "La méthode a été appliquée" (not "J'ai appliqué la méthode").
- EN: "The method was applied" (not "I applied the method").

**PW - `[PRONOUN WE OUT OF SCOPE]` (R1.5).** `we` outside the Contributions paragraph and the Conclusion.
- FR: "Les résultats montrent" (not "Nous montrons" in the Results).
- EN: "The results show" (not "We show" in the Results).

**INF - `[INFORMAL LANGUAGE]` (R1.6).** A contraction, a colloquialism or a vague quantifier.
- FR: "Douze participants sur quarante" (not "pas mal de participants").
- EN: "Twelve of forty participants" (not "a lot of participants").

**SEMI - `[SEMICOLON IN PROSE]` (R1.7).**
- FR: "Le gain a été augmenté. Le dépassement a diminué."
- EN: "The gain was raised. The overshoot fell."

**LONG - `[SENTENCE TOO LONG]` (R1.8).** Past roughly 30 words: split into two or three sentences.
- FR: a 38-word sentence split into two of 17 and 21 words.
- EN: a 35-word sentence split into two of 16 and 19 words.

**FRAG - `[SENTENCE FRAGMENT]` (R2.4).** A prose line with no finite verb.
- FR: "Le système a été stabilisé" (not "Système stabilisé.").
- EN: "The system was stabilized" (not "System stabilized.").

**LIST - `[LIST IN PROSE SECTION]` (R2.6).** A list in the Abstract, Introduction, Results, Discussion
or Conclusions: rewrite as a paragraph.

**CLIST - `[CONTRIBUTIONS AS LIST]` (R2.7).** "Trois contributions sont proposées. Premièrement, ..."
/ "Three contributions are made. First, ..."

## Not language

Flags such as `[ABSTRACT LABELED SECTIONS]`, `[SUBSECTIONS NOT PRESENTED]`, `[IAG DECLARATION MISSING]`
or `[JOURNAL GUIDELINES NOT CONSULTED]` appear in the auditors' composition sections but concern
structure or process. They are listed under `not_language` in the table and stay in the agents.
