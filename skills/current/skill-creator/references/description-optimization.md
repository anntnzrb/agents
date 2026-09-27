# Description Optimization

Read this file only when tuning skill triggering, rewriting `SKILL.md` descriptions, or checking whether a skill under-triggers or over-triggers.

## What the description is

The frontmatter `description` is the skill's trigger, not a summary. Harnesses list every enabled skill's `name` and `description` to the model, which decides from that text alone whether to load the skill. The body loads only after that decision.

## Writing rules

- One sentence, at most 120 characters; `quick-validate` enforces the cap.
- Start with `Use when` (or `Use for` / `Use before`), addressed to the agent. No "This skill", no first or second person, no marketing.
- Describe the user's situation in words users actually type. Front-load the most distinctive nouns: tool and product names, file types, artifacts.
- When a sibling skill could claim the same prompt, add a short `not for <capability>` clause. Name the other capability, never the other skill, so archiving a skill never breaks another trigger.
- Stay truthful to the body. Do not claim scope the skill lacks.
- Models skip skills for tasks they handle unaided; triggers matter most for multi-step or specialized work.

## Trigger eval set

Write about 20 queries as JSON, a mix of should-trigger and should-not-trigger:

```json
[
  { "query": "the user prompt", "should_trigger": true },
  { "query": "another prompt", "should_trigger": false }
]
```

Queries must be realistic: concrete, specific, with file paths, context, casual phrasing, or typos. Avoid abstract one-liners such as `"Format this data"`.

- Should-trigger (8 to 10): varied phrasings of the same intent, including cases where the user never names the skill or tool, and cases where this skill competes with a sibling and should win.
- Should-not-trigger (8 to 10): near-misses that share keywords but need a different capability. Obviously unrelated queries test nothing.

## Checking a description

Checking is harness-agnostic: present the full enabled skill listing (every `name: description` line) and one query to a model, ask which skill it would load or none, and compare against the expected label. Run each query at least 3 times and treat the majority as the result. Use any model the environment provides; prefer the model the user works with, since trigger behavior varies by model.

Tune on about 60% of the queries and score the final description on the held-out 40% to avoid overfitting. When a description loses to a sibling, fix both triggers, not only one.

## Apply the result

Update the `description` line only, run `quick-validate`, and report the before/after text with its held-out score.
