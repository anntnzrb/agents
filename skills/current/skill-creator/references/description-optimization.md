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
- When porting a skill, write a new trigger. Upstream descriptions usually summarize the skill or name a slash command, and neither tells the model when to load it.
- When a skill gains a capability, add its trigger noun. A capability missing from the trigger loses to a sibling whose trigger names the artifact: a perf-claim request routes to a writing skill when the principles trigger never mentions measured numbers.

## Trigger eval set

Write about 20 queries as JSON, a mix of should-trigger and should-not-trigger:

```json
[
  { "query": "the user prompt", "expect": "skill-name" },
  { "query": "a near-miss prompt", "expect": "sibling-skill" },
  { "query": "a prompt needing no skill", "expect": "none" }
]
```

Include requests at each boundary the change moves: an added capability, a dropped `not for` clause, and a new sibling. Queries must be realistic: concrete, specific, with file paths, context, casual phrasing, or typos. Avoid abstract one-liners such as `"Format this data"`.

- Should-trigger (8 to 10): varied phrasings of the same intent, including cases where the user never names the skill or tool, and cases where this skill competes with a sibling and should win.
- Should-not-trigger (8 to 10): near-misses that share keywords but need a different capability. Obviously unrelated queries test nothing.

## Checking a description

Run `quick-validate` for the deterministic gate: nonempty trigger wording, an approved opener, the length cap, and allowed characters. Passing this gate does not prove semantic quality. `Use when you need a comprehensive toolkit.` passes the grammar but gives no useful trigger.

During authoring review, require a concrete user situation, scope consistent with the body, and a boundary from neighboring capabilities where needed. Reject synopsis wording even when an approved opener precedes it. Compare a positive request with a plausible near-miss. Record why each should or should not load the skill. Keep this review separate from the deterministic validator.

Checking is harness-agnostic: present the full enabled skill listing (every `name: description` line) and one query to a model, ask which skill it would load or none, and compare against the expected label. Run each query at least 3 times and treat the majority as the result. Use any model the environment provides; prefer the model the user works with, since trigger behavior varies by model.

Run the bundled `trigger-eval` command manually. It costs inference and is OPTIONAL. CI MUST NOT run it. Save the JSON array above as a cases file, replacing the placeholder queries and labels:

```text
uv run --script <skill-dir>/scripts/cli.py trigger-eval --cases <cases.json> --base-url <api-base-url> --model <model-id> --api-key <api-key> --runs 3 --jobs 2 --json
```

The command defaults to the repository's `skills/current` listing. Use `--skills-dir <skills-dir>` for another inventory. It excludes `disable-model-invocation: true` skills. Repeat `--override 'name=description'` to test candidate wording without editing files. `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` supply settings when flags are absent. No endpoint or credential is built in.

Each call contains the full enabled listing and one query. Replies are normalized for case, whitespace, and surrounding quotes or backticks. A strict majority wins; no majority is a miss. The report includes each expected label, majority answer, vote counts, and total score. Exit codes are `0` for all passing cases, `1` for a miss or provider failure, and `2` for invalid input or missing configuration. Transient failures receive at most two retries per call.

Tune on about 60% of the queries and score the final description on the held-out 40% to avoid overfitting. When a description loses to a sibling, fix both triggers, not only one.

Keep tuning and held-out cases in separate files. Run `trigger-eval` against the tuning file while comparing overrides, then against the held-out file once the wording is fixed.

A passing score shows the description picks the right skill when the model is asked to choose. To check what the agent does during real work, run real tasks and count reads of the skill's `SKILL.md`; some harnesses read skills through a URL scheme such as `skill://<name>` instead of a file path, so count both. Add a routing line to global instructions only when that count shows a miss: a routing line can also make the skill load where it does not apply.

Use repeated model evaluation when investigating trigger failures or comparing candidate wording. Do not require network access or a model judge for ordinary metadata validation. Report model routing scores separately from structural validation results.

## Apply the result

Update the `description` line only, run `quick-validate`, and report the before/after text with its held-out score.
