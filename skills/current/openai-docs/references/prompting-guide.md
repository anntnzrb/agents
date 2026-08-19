# GPT-5.6 prompting and migration

## Canonical guidance
Use OpenAI Docs MCP to fetch https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6#prompting-best-practices. Extract only `## Prompting Best Practices`, through the next H2; the MCP may return the full page. Treat that live section as canonical model-specific guidance. Use this local guide only for skill-specific migration judgment: what to preserve, remove, rewrite, or test in an existing GPT-5.6 prompt stack.

## Core migration rule
Define outcome, important constraints, available evidence, and completion bar; let GPT-5.6 choose an efficient path. Prefer the smallest prompt and tool set that passes evals. Legacy repetition, unnecessary prescribed steps, irrelevant tools, and behavior-neutral examples can cause extra exploration, validation, and context. Add an instruction, example, or tool only for a measured failure mode.

### Simplify first
Remove:
- repeated rules;
- generic “be thorough,” “be concise,” and “think step by step” language;
- behavior-neutral examples;
- process instructions for reliable behavior;
- irrelevant tools and descriptions.

Keep:
- user-visible outcome;
- success criteria and stop conditions;
- safety, business, evidence, and permission constraints;
- non-obvious tool routing;
- required output shape and validation.

Review for contradictions: GPT-5-class models follow prompt contracts closely, and conflicts can destabilize behavior more than missing detail.

## Outcome and stopping
State the destination, not every step; GPT-5.6 generally selects an efficient search, tool, or reasoning path when success is defined.

Example:
```
Resolve the customer's issue end to end.
Success means:
- decide eligibility from available policy and account evidence;
- complete allowed actions before responding;
- return completed_actions, customer_message, and blockers;
- if required evidence is missing, ask for the smallest missing field.
```

Use ALWAYS, NEVER, must, and only for true invariants: safety rules, required fields, or forbidden actions. For judgment calls (search, ask, tool use, iteration), use decision rules. Preserve explicit user values; for implicit values, provide decision criteria and let context/schema determine them. Avoid universal defaults, keyword maps, and broad semantic shortcuts.

Stop rules:
- Resolve in the fewest useful tool loops, but do not let loop minimization outrank correctness, required evidence, calculations, or citations.
- After each result, determine whether useful evidence now answers the core request. If yes, answer; otherwise name the missing fact and use the smallest useful fallback.

## Personality and responses
Define briefly:
- Personality: tone, warmth, directness, formality, humor, empathy, polish.
- Collaboration style: when to ask, assume, take initiative, explain tradeoffs, check work, and handle uncertainty.

These shape experience and task behavior; neither replaces goals, success criteria, tool rules, or stop conditions.

Writing control: lead with the conclusion; include supporting evidence, material caveats, and next action; retain required facts, decisions, caveats, and next steps; remove introductions, repetition, generic reassurance, and optional background first. Avoid generic brevity instructions (“be brief,” “keep it short,” “use minimal text”), which can omit required evidence or artifact parts.

Customer-facing tone: be direct and tactful; acknowledge relevant friction specifically; avoid canned reassurance and unnecessary sign-offs. Specify output language and when it changes; do not impose “always use the user’s language” unless it is a product requirement.

Editing, rewriting, summaries, and customer-facing drafts: preserve requested artifact, length, structure, genre, and factual claims first; improve clarity, flow, and correctness without adding claims, sections, or promotional tone unless requested.

## Autonomy and permissions
Define authorization by request:
- Answer/explain/review/diagnose/plan: inspect relevant materials and report; do not implement unless requested.
- Change/build/fix: make requested in-scope local changes and run relevant non-destructive validation without asking first.
- External writes, destructive actions, purchases, or material scope expansion: require confirmation.

Specify safe local actions (for example, reading files, inspecting logs, searching, editing in-scope code, and non-destructive tests). Do not repeat “ask first,” since repetition can trigger unnecessary permission checks. For long-running work, identify the current layer; research, design, implementation, review, or external coordination; and prevent silent layer changes.

## Tool routing
Expose only task-relevant tools. Each description states purpose, when to use it, important return fields, and error behavior.

Before action, resolve required discovery, retrieval, and validation; do not skip prerequisites because the final state appears obvious. Parallelize independent reads; keep dependent work sequential; synthesize parallel results before acting. Empty, partial, or suspiciously narrow results require one or two meaningful fallbacks before concluding no result exists.

### Programmatic Tool Calling (PTC)
Use PTC when code can reduce large structured intermediates: filtering, joining, sorting, ranking, deduplication, aggregation, batching similar records, repeated deterministic validation, or reduction to a compact schema.

Prefer direct calls when one call suffices, intermediates are small, each result may change the next decision, approval is required, citations/native artifacts must be preserved, or semantic judgment is needed between calls.

Do not say merely “use PTC efficiently.” Specify bounded stage, eligible tools, output schema, retry limit, stop condition, and handoff to direct judgment. Example:
```
Use PTC only for the bounded record-reduction stage. Call only documented read-only tools. Filter and deduplicate intermediates; emit exactly the required compact schema with evidence fields. Retry transient failures at most twice. Use direct calls for approval, semantic judgment, citations, and final validation.
```

Judge the final user-visible answer, not just the program result. Fewer tokens, calls, turns, or lower latency count as improvements only if the final quality bar remains met.

## Grounding and retrieval
Make citation behavior explicit: define claims requiring support, sufficient evidence, and missing-evidence behavior. Absence of evidence is not automatically factual “no.”

Ordinary Q&A:
1. Start with one broad search using short, discriminative keywords; answer if top results sufficiently support the core request.
2. Retrieve again only for a missing required fact, owner, date, ID, or source; exhaustive coverage/comparison; a required artifact; or an important otherwise-unsupported claim.
3. Do not search again merely to improve phrasing, add examples, or support nonessential detail.

Research/synthesis: cite only retrieved sources; attach citations to supported claims; label inference separately; state source conflicts; narrow the answer or report missing evidence instead of guessing.

Creative drafting: distinguish source-backed facts from creative wording. Do not invent names, metrics, dates, roadmap status, customer outcomes, or product capabilities to strengthen a draft.

## Long-running workflows and state
For multi-step/tool-heavy work, require a short visible preamble before the first tool call and sparse outcome-based updates at major phase changes; do not narrate routine calls.

Before calls, send a one- or two-sentence user-visible update stating the first step. Thereafter update only at a major phase or plan-changing finding; each update states one concrete outcome and next step.

Preserve assistant phase values when replaying history so commentary remains distinct from the final answer. `previous_response_id` preserves prior assistant state automatically; manual replay preserves every original phase value unchanged. Compact after major milestones, not every turn; retain functional consistency and treat compacted items as opaque state.

Persisted reasoning suits stable objectives, assumptions, and priorities. Use current-turn behavior when earlier reasoning is irrelevant. It is not always-on: stale reasoning adds tokens/latency and anchors outdated work.

Keep reusable prompt prefixes stable; avoid unnecessary large-system-prompt churn. Use explicit cache breakpoints only when measured workload cache behavior and cost improve.

## Reasoning effort
Treat effort as last-mile tuning, not the first fix for weak results:
- preserve current GPT-5.5/GPT-5.4 effort as baseline;
- test that setting and one level lower on representative tasks;
- use low for latency-sensitive work when quality holds;
- use medium as balanced starting point;
- use high/xhigh only for a meaningful eval gain;
- reserve max for hardest quality-first workloads; do not recommend it globally.

Before increasing effort, check for missing success criteria, dependency rules, tool routing, or verification loops.

## Frontend and visual work
Provide product context, preserve the design system, and name relevant states/constraints. For incremental frontend changes, inspect/preserve existing tokens, components, and patterns; add no unrequested features or decoration; preserve responsive behavior and expected states; render and inspect before finalizing.

For vision, computer use, localization, and OCR requiring spatial precision, choose image detail intentionally; use original detail for large, dense, or coordinate-sensitive images when added cost/latency is justified.

## Validation
Give GPT-5.6 validation tools and specify material checks.

Coding after changes:
- targeted tests for changed behavior;
- applicable type/lint checks;
- build checks for affected packages;
- minimal smoke test when full validation is too expensive.

If validation cannot run, explain why and state the next-best check.

Visual artifacts: render before finalizing; inspect layout, clipping, spacing, missing content, and visual consistency; revise until the render matches requirements.

Implementation plans include requirements, named resources/files, state transitions/data flow, validation checks, failure behavior, privacy/security considerations, and materially consequential open questions.

## Complex-prompt skeleton
Keep sections short; add detail only when it changes behavior:
```
Role: [model function and context]
Personality: [tone and collaboration style]
Goal: [user-visible outcome]
Success criteria: [what must be true before final answer]
Constraints: [policy, safety, business, evidence, side-effect limits]
Tools: [which tools, when, and what not to use]
Output: [sections, length, format, tone]
Stop rules: [when to retry, fallback, abstain, ask, or stop]
```

## Migration workflow
1. Switch model; preserve current reasoning effort.
2. Run representative evals before prompt changes.
3. Remove obsolete scaffolding, repetition, and irrelevant tools.
4. Add only the smallest instruction fixing a measured regression.
5. Re-run evals after each prompt or reasoning change.

Do not rewrite a working stack all at once: otherwise model, effort, prompt, tools, and runtime effects cannot be separated. For a regression, inspect a small set of real traces; identify the failure mode and likely instruction/contradiction; make a surgical edit; rerun the same cases.
