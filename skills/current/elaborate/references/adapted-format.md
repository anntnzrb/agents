# Adapted unit format

Write each adapted unit to `<work>/adapted/<id>.md`. `check` parses this format. A parse error fails gate `K-format` with a line number.

## Skeleton

```markdown
@idea: One sentence with the unit's central claim.
@question: One question the unit answers.

## A heading that names what comes
Body paragraph with an aside {~ short reaction ~} and a glossed word parsimony{= extreme stinginess}.

{analogy} The modern version: one labeled analogy paragraph.

> Verbatim quotation from the source.
>
> Attribution as in the source.

- A list item for a parallel enumeration

@why: One prompt that connects the idea to the reader's life.
@recap:
- First point
- Second point
- Third point
@quiz:
1. First question?
2. Second question?
@answers:
1. First answer.
2. Second answer.
```

## Directives

- A directive starts at column 0 with `@name:`.
- Inline directives: `@idea`, `@question`, `@why`. The text continues on following lines until a blank line.
- List directives: `@recap`, `@quiz`, `@answers`. Items use `- ` or `1. ` and end at a blank line or the next directive.
- Put `@idea` and `@question` first and the other directives last. The build renders them in fixed positions with the language's labels, so never write the labels yourself.

## Body

- Headings: `##` to `####`. Never `#`. The build writes the unit title.
- Paragraphs, `> ` quotations, `- ` and `1. ` lists, `*emphasis*`, `**strong**`.
- Images: copy each source image marker `{image images/<file> | <alt text>}` as its own paragraph, in the same order. Never add, drop, or reorder images.
- No tables, no emoji, no HTML.

## Markers

| Marker | Syntax | Rendered as |
|---|---|---|
| Aside | `{~ text ~}` | the text, inline |
| Gloss | `word{= gloss}` | `word (gloss)` |
| Multiword gloss | `{term words}{= gloss}` | `term words (gloss)` |
| Analogy | paragraph starting with `{analogy} ` | the paragraph, marker removed |

- Write a literal asterisk as `\*`, a period after a number that starts a paragraph as `\.`, and a literal brace as `\{` or `\}`. Sources keep editorial braces escaped the same way. Copy them as they appear.
- Mark every aside. Unmarked jokes cannot be checked for cadence, length, or invented facts.
- Glosses attach to the word immediately before `{=`. Gloss the first occurrence of each rare word only.
