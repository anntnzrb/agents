# Upgrading to GPT-5.6 Sol

Use this guide for migrations of an OpenAI API integration, repository, prompt stack, agent, model router, or model picker to GPT-5.6 Sol/family.

## Canonical docs

Before code changes, use OpenAI Docs MCP to fetch current guidance:
https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6

For prompt edits, read only `## Prompting Best Practices`:
https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6#prompting-best-practices

Live docs are canonical for model IDs, parameters, limits, pricing, and feature availability. This guide supplies migration judgment: search surfaces, breakage risks, preservation rules, adoption boundaries, and validation.

## Core rule

NEVER blindly replace model strings. For each usage site, first preserve behavior, latency/cost class, reasoning level, endpoint contract, tool semantics, cache behavior, and output contract; then make the smallest safe change. New GPT-5.6 capabilities require a measured problem or explicit user request. A model upgrade alone does not authorize reasoning fields, request-schema changes, or test rewrites. Add explicit reasoning only when old effective behavior is known and omission would change GPT-5.6 behavior.

Main hazards:
- Sol replacing intentional mini/nano, low-cost, or latency-sensitive roles.
- GPT-5.6 omitted reasoning becoming `medium` where old effective effort was `none`.
- Chat Completions function tools without effective `none`.
- Cache misses from a stable prefix plus changing suffix.
- More image/PDF tokens from omitted/`auto` detail.
- Unsupported new cache, persisted-reasoning, Pro, Programmatic Tool Calling, or multi-agent fields.
- Model strings changed while registries, allowlists, pricing/capability metadata, tests, or UI pickers remain stale.

## Classify every usage before editing

- `simple Sol migration`: one flagship usage; endpoint/request shape unchanged; effort explicit or old effective value known; no cache, vision, file, tool, or parser implementation change.
- `tier-aware family migration`: multiple roles, choices, fallbacks, routers, pricing, or capability metadata; map roles to Sol/Terra/Luna, not all to Sol.
- `compatibility migration`: safe change requires parameter, endpoint, cache, state, tool-loop, or multimodal-detail work. Make it only if in scope; otherwise report exact blocker and smallest follow-up.
- `prompt migration`: API shape remains, but representative traces show a prompt regression; make a surgical failure-linked edit, never a wholesale rewrite. Prompt-guidance tasks change only the directly tied prompt surface unless runtime/schema/tests require change.
- `optional feature adoption`: deliberate Pro, persisted reasoning, explicit caching, Programmatic Tool Calling, or multi-agent addition; isolate from baseline for measurement.
- `leave unchanged`: historical examples/docs, snapshots, fixtures, eval baselines, comparison code, pinned fallbacks, unsupported providers, or ambiguous usages.

If intent is unclear, leave the usage unchanged and request confirmation rather than silently changing its role.

## Inventory

Search beyond literal model IDs:
- model strings/aliases, environment variables, CLI flags, config defaults, deployment settings;
- Responses, Chat Completions, Batch, and provider adapters;
- reasoning, token budgets, sampling, and latency timeouts;
- function/hosted tools, structured outputs, parsers, and replay;
- system/developer/user/tool-description prompts;
- routers, fallbacks, allowlists, enums, regexes, validation schemas, capability maps;
- picker labels/descriptions, context limits, pricing, provider catalogs;
- cache keys/retention, stable-prefix construction, metrics;
- image/PDF/file/OCR/computer-use inputs;
- tests, fixtures, snapshots, evals, analytics, billing tables, and docs.

For changed defaults, update all active default surfaces together: runtime/config files, environment, setup docs, tests, CLI defaults, and deployment examples.

Record per site: source model and apparent purpose; endpoint/client; prompt; effective reasoning including defaults; latency/cost/context/quality role; tools, schemas, cache, replay, multimodal inputs; downstream parser/user contract; migration class; validation plan.

## Target by workload role

| Existing role | Starting target | Rule |
|---|---|---|
| Unsuffixed GPT-5 flagship, GPT-5.5, GPT-5.4 flagship | `gpt-5.6-sol` | flagship-equivalent |
| Mini, balanced lower-cost, medium-throughput worker | `gpt-5.6-terra` | mini-like tier |
| Nano, classification, extraction, routing, high-volume, strict-latency | `gpt-5.6-luna` | nano-like tier |
| GPT-4.1/GPT-4o latency-sensitive | Evaluate Luna/Terra first; Sol only if quality requires | flagship can materially change latency/cost |
| Reasoning-heavy/quality-first | Sol at old effective effort | preserve contract before tuning |
| Old Pro | Sol plus `reasoning.mode: "pro"`, only if Pro behavior wanted | Pro is a mode, not a separate slug |
| Router/fallback/picker | Add family by role | do not collapse design |
| Third-party/provider-specific | Unchanged unless provider migration explicitly requested | name similarity is unsafe |

Default explicit target: `gpt-5.6-sol`. Alias `gpt-5.6` routes to Sol; use it only when the repository intentionally prefers family aliases. If used, record returned `response.model`; do not assume alias and explicit slug match in dashboards, rate limits, analytics, or billing.

Check live docs for limits; do not invent prices, limits, capabilities, or registry metadata. Starting limits: Sol/Terra roughly 1.05M context and 128K max output; Luna 400K context and 128K max output; Sol/Terra requests above 272K input tokens can change pricing for the full request. Preserve existing picker/registry entries by default; add Sol/Terra/Luna options unless replacement/removal is requested.

## Preserve effective reasoning

GPT-5.6 supports `none`, `low`, `medium`, `high`, `xhigh`, `max`; omitted defaults to `medium`. GPT-5.5 commonly defaulted to `medium`; GPT-5.4/mini/nano commonly to `none`. An omitted old setting can therefore become slower, costlier, and incompatible with Chat Completions function tools.

1. Preserve explicit effort on the first 5.6 run when supported.
2. If omitted and old effective default is known, add it only when GPT-5.6 omission changes behavior; if defaults match, keep omission.
3. If unknown, do not guess: flag and compare old behavior with 5.6 at likely baseline.
4. After baseline, test same effort and one lower on representative tasks.
5. Use `xhigh`/`max` only for hard quality-first workloads with measured gain.

NEVER globally recommend `max`; first check success criteria, dependency/tool-routing rules, replay bugs, and validation loops. Use endpoint-specific field shape.

Responses:
```json
{
  "model": "gpt-5.6-sol",
  "reasoning": { "effort": "none" }
}
```

Chat Completions:
```json
{
  "model": "gpt-5.6-sol",
  "reasoning_effort": "none"
}
```

## Chat Completions + function tools

GPT-5.6 Chat Completions function tools are compatible only with effective reasoning `none`; reasoning plus tools belongs on Responses. Since GPT-5.6 defaults to `medium`, this is unsafe:

```json
{
  "model": "gpt-5.6-luna",
  "tools": [{ "type": "function", "function": { "...": "..." } }]
}
```

For a latency-sensitive flow retaining tools, explicitly set `none`:
```json
{
  "model": "gpt-5.6-luna",
  "reasoning_effort": "none",
  "tools": [{ "type": "function", "function": { "...": "..." } }]
}
```

If reasoning and tools are both required, migrate to Responses only when in scope; otherwise report a compatibility blocker. NEVER conceal it by removing tools, dropping reasoning, or changing workload behavior without approval. If live API rejects the intended `none` path, report exact request and error; do not invent a workaround.

## Responses and state

Prefer Responses for reasoning, tools, multi-turn agents, and new 5.6 capabilities. Preserve existing ordinary multi-turn state strategy; do not add persisted reasoning merely because available.

When deliberately enabling persisted reasoning:
- use `reasoning.context: "all_turns"` only when objective/assumptions remain stable;
- prefer `previous_response_id` when server state is available;
- manual replay preserves every prior user input and relevant output item, not only assistant text;
- with `store: false` or ZDR, request/replay `reasoning.encrypted_content`;
- use current-turn behavior when old reasoning may be stale/misleading.

Manual replay preserves item types, IDs, call IDs, caller metadata, and assistant phase values exactly. Incomplete replay can silently reduce quality or break tool continuation.

## Prompt caching

Do not assume cache behavior survives the model swap. GPT-5.6 implicit caching uses a managed breakpoint near the latest user/tool message and no longer relies on 128-token rounding; a large stable prefix followed by changing suffix can lose hits.

Audit reusable system/developer prompts, dynamic suffixes, changing timestamps/request IDs/user values/tool lists in prefixes, cache keys/retention/dashboards, and accounting for writes as well as reads. Keep reusable prefixes stable; avoid needless churn; compare `cached_tokens`, `cache_write_tokens`, latency, and cost. Use explicit breakpoints only for a measured stable boundary missed by implicit caching. Do not globally convert prompts or send 5.6-only cache fields to older routes. Shared builders must isolate 5.6-only fields.

New top-level shape:
```json
{
  "prompt_cache_options": {
    "mode": "explicit",
    "ttl": "30m"
  }
}
```

Put `prompt_cache_breakpoint` at the actual stable rendered boundary. Preserve existing `prompt_cache_key`. Treat `prompt_cache_retention` as deprecated and verify live docs before rewriting. Cache writes cost more than ordinary uncached input; lower hit rate can be slower and more expensive.

## Images, PDFs, files, long context

GPT-5.6 may change tokens/latency without prompt changes: omitted/`auto` image detail can preserve original dimensions; Responses PDF/file omitted or `input_file.detail: "auto"` can use high page-image detail; Chat Completions file inputs lack the same detail control; Sol/Terra long context can cross pricing thresholds; Luna's smaller context can break workloads fitting Sol/Terra.

For multimodal/long-context sites: measure before/after input tokens and latency; make detail explicit when cost/latency matters; resize/lower detail when spatial precision is unnecessary; retain original/high detail for dense, coordinate-sensitive, OCR, localization, or visual-inspection work; test worst-case lengths. A missing metadata flag does not prove capability removal; verify docs and a representative request.

## Contracts

Preserve explicit JSON schemas, required fields, enums, refusal handling, parser expectations, tool names/parameter schemas/call IDs/retries, and required citations/evidence/native artifacts. Validate the final answer, not merely tool success. NEVER fix migration failures by weakening schemas, deleting behavior/routes, dropping tools, or changing business logic unless explicitly requested.

## Optional features

### Pro
Do not enable in baseline unless old usage was Pro-like or requested. GPT-5.6 Pro uses base model plus mode:
```json
{
  "model": "gpt-5.6-sol",
  "reasoning": {
    "mode": "pro",
    "effort": "medium"
  }
}
```
Use Responses, not Chat Completions; never invent/search for `gpt-5.6-pro`; supported Pro efforts start at `medium`; mode and effort are separate. Compare quality, total latency, and billed tokens with standard mode. Legacy Pro migration must explicitly change mode and be evaluated separately.

### Programmatic Tool Calling (PTC)
Optional; add only when code can reduce large structured intermediates before model context. Good: bounded read-only filtering/joining/sorting/ranking/deduplication/aggregation, batching, deterministic validation, compact-schema map-reduce. Poor: one direct call, adaptive next-decision workflows, writes/approvals/side effects, citation-heavy/native-artifact flows, or semantic judgment that should remain model-visible.

Required shape:
```json
{
  "tools": [
    { "type": "programmatic_tool_calling" },
    {
      "type": "function",
      "name": "lookup_records",
      "allowed_callers": ["programmatic"]
    }
  ]
}
```

Do not nest `programmatic_tool_calling` under another `tools`. Host handles `program`, program-issued `function_call`, `function_call_output`, and `program_output`; preserve original `call_id` and `caller` in function results. Constrain stage, eligible read-only tools, output schema, retries, and handoff to direct judgment. Validate final user-visible answer.

### Multi-agent beta
Do not enable in baseline unless a clear parallelizable workflow exists and requested. Requirements: header `OpenAI-Beta: responses_multi_agent=v1`; `multi_agent: { "enabled": true, "max_concurrent_subagents": 3 }`; handle `multi_agent_call`, `multi_agent_call_output`, and `agent_message`; execute ordinary developer-defined function calls from any agent and return all required outputs; preserve new replay/tracing items; check current-doc incompatibilities with compaction, reasoning summaries, and tool-call limits. Cap concurrency; prevent unbounded/duplicate work and require final synthesis.

## Prompt migration judgment

After API/model baseline works, run representative traces and edit prompts only for measured failures. Prefer shorter outcome-oriented prompts; explicit success criteria, dependencies, stopping/completion boundaries; preserved user values; decision criteria instead of universal defaults/keyword maps; explicit autonomy/permission; tool routing, resource links, breadcrumbs, expected tool choice; staged plans, current-layer awareness, concise long-work handoffs; real validation before completion.

Avoid generic `be brief`, `be thorough`, or `think step by step`; blanket language instructions causing unwanted switching; repeated `ask first` that blocks safe local work; giant rewrites obscuring regressions; and minimizing tool loops when correctness/evidence/validation requires them.

For coding/agentic migrations, add:
```
Preserve existing functionality, routes, outputs, and user-visible behavior.
Do not delete or disable required behavior merely to make the build pass.
Before finishing, run the relevant build, tests, type checks, render or smoke
checks, and report the evidence.
```

For long-running work, define current layer: research, design, implementation, review, or external coordination; do not silently switch layers.

## Workflow

1. Fetch live 5.6 docs and Prompting Best Practices.
2. Inventory every usage and adjacent prompt/config/registry/parser/test surface.
3. Classify role and migration class.
4. Select Sol/Terra/Luna by workload role.
5. Preserve old effective effort explicitly.
6. Gate endpoint/SDK support; Chat Completions/tools; cache topology/fields; context and long-context cost; image/PDF/file detail; schemas/parsers; Responses replay/tool continuation; mixed-model routing and unsupported fields.
7. Apply smallest safe model/config/registry/prompt changes.
8. Add Pro, persisted reasoning, PTC, explicit caching, or multi-agent only when needed and measurable.
9. Run existing tests and representative evals.
10. Report changed, unchanged, blocked, and confirmation-needed sites separately.

## Validation

Controlled comparison:
1. old model + old prompt + old settings;
2. target + same prompt + preserved effort;
3. target + same prompt + one lower effort;
4. target + smallest prompt/API fix for measured failure;
5. optional feature treatment isolated from baseline.

Measure task success/user quality; schema/parser validity; tool choice/arguments/retries/loops/completion; TTFT, end-to-end latency, timeouts, concurrency; input/output/reasoning/cached/cache-write tokens; cost per successful task; long-context/compaction/replay; image/PDF tokens and visual/OCR accuracy; completeness, preserved behavior, citations, and validation evidence. For routers/pickers, test one representative workload per role; ensure cheapest/fastest tier is not used for quality-critical work and Sol is not used for everything.

## Required final report

Return:
- `Current usage inventory`: model site, endpoint, role, prompt surface, old effective reasoning;
- `Target mapping`: Sol, Terra, Luna, unchanged, or confirmation-needed, with reason;
- `Changes made`: model strings, reasoning, prompts, registries, metadata, tests, API shape;
- `Compatibility checks`: Chat Completions/tools, caching, replay, multimodal detail, context/cost, schemas, mixed routing;
- `Prompt changes`: each surgical edit and addressed failure;
- `Validation`: commands, evals, traces, before/after measurements, remaining gaps;
- `Unchanged sites`: historical, pinned, ambiguous, or intentionally role-specific;
- `Blockers and open questions`: exact issue, why guessing is unsafe, smallest next step.

NEVER call migration complete merely because model strings changed. Completion requires validated affected behavior/contracts or explicit remaining gaps.
