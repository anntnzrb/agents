# Fidelity audit: {{book_title}}, unit {{unit_id}}

Audit an adapted unit against its source. The bar is zero loss: a skilled reader of the source and a reader of the adaptation must reach the same conclusions and know the same facts, nuances, and author vocabulary. Report findings only. Do not edit files.

Book: {{book_title}} by {{authors}}. Unit: {{unit_title}}. Language: `{{language}}`.

The adaptation intentionally adds reading aids (`@idea`, `@question`, `@why`, `@recap`, `@quiz`, `@answers`), asides marked `{~ ~}`, glosses marked `word{= gloss}`, and at most one `{analogy}` paragraph. Additions are allowed only when they react to what the source says and assert nothing new.

## Method

1. Go through the source sentence by sentence. Split each sentence into atomic claims: facts, causal links, judgments, conditions, hedges and modality, intensity, evaluative tone, and notable author vocabulary.
2. Classify each claim as PRESERVED, WEAKENED, STRENGTHENED, CHANGED, or LOST in the adaptation.
3. Check every heading, `@idea`, `@question`, aside, gloss, analogy, recap point, quiz question, and answer for assertions beyond the source or meaning shifts. An aside passes when it is a reaction with no claim, or a restatement with the same scope as the source. Flag evaluations, generalizations, invented motives, and "literally" applied to a figure of speech. When you fix an aside, keep it a short, punchy reaction. Do not turn it into a neutral summary.
4. Check that every gloss is accurate for the word's sense in context and period, keeps its tense, mood, person, and number, and explains figures of speech without making them literal.
5. Ignore pure rewording that keeps meaning, modality, intensity, and tone.

## Facts the tooling already checked

{{protected}}

## Output

Return JSON only, with this shape:

```json
{"unit": "{{unit_id}}",
 "counts": {"preserved": 0, "weakened": 0, "strengthened": 0, "changed": 0, "lost": 0},
 "findings": [
   {"category": "weakened|strengthened|changed|lost|added|gloss",
    "severity": "matters|cosmetic",
    "source": "exact source phrase or null",
    "adapted": "exact adapted phrase or null",
    "why": "one line",
    "fix": "replacement text for the adapted phrase"}
 ]}
```

Mark a finding `matters` when a reader of the adaptation would know less, believe something different, or misjudge certainty or intensity. Every finding needs a concrete `fix`.

## Source

{{source}}

## Adaptation

{{adapted}}
