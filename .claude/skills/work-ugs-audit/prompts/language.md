You list the language errors of one page of an undergraduate report. The language of the report is
{{LANGUAGE_OF_REPORT}}. Use only the categories of this table, by their code.

## Categories

{{LANGUAGE_TABLE}}

## Rules

- Report real errors only. Do not report a style choice or a technical term.
- Quote the faulty passage word for word from the page, as short as possible (a few words).
- Propose the corrected wording in the same language.
- Give a short reason, one sentence.
- Report at most the clearest errors of the page. If there is none, return an empty list.

## Page

{{SECTION}}

## Answer

Return one JSON object with the key findings, a list of objects with the keys page, code, quote, proposed
and reason. The page is the number given in the page heading. Nothing else.
