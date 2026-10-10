# Rewrite brief: {{book_title}}, unit {{unit_id}}

Adapt the source unit below into an elaborated edition for a reader who struggles to sustain attention on dense prose. Write the result in the adapted format and save it as `adapted/{{unit_id}}.md` in the work directory.

Book: {{book_title}} by {{authors}}. Unit: {{unit_title}}. Language: `{{language}}`. Write in this language. Do not translate.

## The invariant

Elaborate, never simplify. A skilled reader of the source and a reader of your text must reach the same conclusions and know the same facts, nuances, and vocabulary. Make it easier by splitting sentences, adding structure, glossing rare words, and adding short reactions. Never cut content to make it easier.

- Keep every fact, causal link, judgment, condition, and example, in the source order.
- Keep hedges and modality exactly: "might" stays "might", "perhaps" stays "perhaps", "it seems" stays. Never raise or lower certainty.
- Keep intensity words and the author's tone.
- Copy quotations verbatim with their attribution. Do not put asides inside quotations.
- Keep the author's rare words and gloss each one at its first occurrence.
- Add no facts, names, numbers, or judgments the source does not contain, including in asides and the analogy.

## Must survive

{{protected}}

## Reader profile

{{voice}}

Use the profile for asides, slang, and the analogy only. Facts and quotations never change for the voice.

## Measured gates

`check` rejects the unit unless these pass:

{{thresholds}}

## Format

Follow `references/adapted-format.md`: `@idea`, `@question`, body with `##` headings, asides as `{~ ~}`, glosses as `word{= gloss}`, at most one `{analogy}` paragraph, then `@why`, `@recap`, `@quiz`, `@answers`. The build renders these labels: {{labels}}. Do not write the labels or a `#` title.

- Asides react to the sentence before them. Two kinds are allowed:
  - A reaction with no claim: "No pressure, then." "Brutal."
  - A punchier restatement of what the source just said, with the same scope: "Four cases, one pattern: show the opposite."
- Asides never evaluate, generalize, or characterize beyond the source. Rejected in audits: "That is the whole game." (evaluation), "Whatever is true, show the opposite." (wider than the four cases given), "Cat and mouse, literally." (the source compares), "A job application. To a king." (invented motive).
- Asides never carry information the reader needs. The body already holds it.
- Put a heading wherever the topic shifts, and name what the section is about. A heading is a claim: it must not generalize, drop a condition, or narrow what the section says. "What Pliny says about books" is safe. "No book is entirely bad" drops the author's exception.
- Glosses keep the word's grammar and period sense: tense, mood, person, number. Gloss a figure of speech by explaining it, not by making it literal.
- `@idea` and `@question` keep the source's modality and exceptions.
- Turn parallel enumerations into lists. Turn source contrasts into two labeled paragraphs.
- Recap points and quiz answers must be traceable to the source.

## Source

{{source}}

## After writing

Run `check` on unit `{{unit_id}}` and fix every failing gate. Report the gate result. Do not report the unit as done while a gate fails.
