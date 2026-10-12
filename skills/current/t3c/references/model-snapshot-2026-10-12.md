# Model selection snapshot

Read this file when reconsidering a `roles.toml` target. It records the evidence behind the current targets, as of the date below. Models, harnesses, and effort levels change often, so treat every number here as dated.

## Snapshot

- Date: 2026-10-12.
- Benchmarks: Artificial Analysis, fetched 2026-10-11 23:05 local time through the `artificial-analysis-live` skill (`/api/v2/data/llms/models` and `/leaderboards/providers`).
- Cost per task: `costPerTask` on the first-party host (Anthropic, OpenAI, or Google). It is a benchmark cost, not the user's bill.
- Terminal-Bench v4: agentic terminal work, about 198 tasks, so one task is about 0.5 percentage points.
- Session timings: median Codex session time on the user's machines, from saved session logs.

| Variant | Intelligence Index | Terminal-Bench v4 | Cost per task (USD) | Time to first answer token (s) |
| --- | --- | --- | --- | --- |
| `claude-opus-5-5-medium` (medium) | 51.2 | 52.5% | 1.336 | 7.934 |
| `gpt-6-1-sol-low` (low) | 42.1 | 30.8% | 0.131 | 1.225 |
| `gpt-6-1-sol-medium` (medium) | 47.8 | 48.0% | 0.214 | 5.417 |
| `gpt-6-1-sol-high` (high) | 50.2 | 51.5% | 0.319 | 22.856 |
| `gpt-6-1-sol-xhigh` (xhigh) | 51 | 54.0% | 0.393 | 63.338 |
| `gpt-6-1-sol` (max) | 51.8 | 56.1% | 0.724 | 173.686 |
| `claude-sonnet-5-5-low` (low) | 35.9 | 20.7% | 0.345 | 0.61 |
| `claude-sonnet-5-5-medium` (medium) | 40.8 | 29.8% | 0.483 | 0.632 |
| `claude-sonnet-5-5-high` (high) | 46.8 | 43.9% | 0.884 | 6.491 |
| `claude-sonnet-5-5-xhigh` (xhigh) | 51.9 | 57.1% | 2.012 | 13.454 |
| `claude-sonnet-5-5` (max) | 56 | 63.6% | 5.461 | 310 |
| `gemini-3-8-flash-low` (low) | 33.5 | 10.1% | n/a | n/a |
| `gemini-3-8-flash-medium` (medium) | 39.8 | 19.7% | 0.931 | n/a |
| `gemini-3-8-flash` (high) | 40.9 | 19.7% | 1.243 | 14.159 |
| `claude-haiku-5-5-low` (low) | 29.5 | 12.6% | 0.024 | 3.998 |
| `claude-haiku-5-5-medium` (medium) | 34.5 | 15.2% | 0.047 | 7.633 |
| `claude-haiku-5-5-high` (high) | 37.8 | 21.7% | 0.079 | 18.167 |
| `claude-haiku-5-5-xhigh` (xhigh) | 41.2 | 29.3% | 0.124 | 42.121 |
| `claude-haiku-5-5` (max) | 43.4 | 32.8% | 0.213 | 260.431 |
| `gpt-6-luna-low` (low) | 21.5 | 0.0% | 0.005 | 3.046 |
| `gpt-6-luna-medium` (medium) | 29.9 | 2.5% | 0.017 | n/a |
| `gpt-6-luna-high` (high) | 32.9 | 4.5% | 0.029 | 11.407 |
| `gpt-6-luna-xhigh` (xhigh) | 34.6 | 8.1% | 0.042 | 27.422 |
| `gpt-6-luna` (max) | 38.1 | 12.6% | 0.068 | 86.841 |

`n/a`: Artificial Analysis published no value for that row.

## Access constraints

- Claude Opus 5.5 is available only at `medium` effort.
- Every other model is available at every effort level.
- Gemini 3.8 Flash is on an unlimited plan, so its effective cost is zero.
- `max` effort is never used. The user's guidance for Codex and Anthropic models is to avoid it, and the data agrees: time to first answer token reaches 174 s on Sol and 260 to 310 s on Haiku and Sonnet.

## Why each target

| Role | Target | Evidence |
| --- | --- | --- |
| orchestrator | Claude Opus 5.5, `medium` | Fixed by access. Not in `roles.toml`. |
| scout | Gemini 3.8 Flash, `high` | Zero effective cost. Its Intelligence Index of 40.9 beats every Luna effort and Haiku through `high`. |
| runner | Gemini 3.8 Flash, `high` | Running named commands needs no stronger model. Haiku beats Gemini on Terminal-Bench only at `xhigh`, 29.3% against 19.7%. |
| implementer | GPT-6.1 Sol, `medium` | The best ratio on the frontier: 48.0% Terminal-Bench at a time to first answer token of 5.4 s. Low effort drops 17 points. |
| implementer retry | GPT-6.1 Sol, `xhigh` | A retry runs once, after a failure. Medium to `xhigh` adds 6.0 points on Terminal-Bench, about 12 tasks. Medium to `high` adds 3.5 points, which is close to noise. |
| reviewer | GPT-6.1 Sol, `high` | 50.2 Intelligence Index, 1.0 below Opus `medium`. `xhigh` would add 0.8 for nearly triple the time to first answer token. |

## Excluded models

- Luna, every effort: Gemini, at zero effective cost, scores higher on both indexes than Luna `max`.
- Haiku: below `xhigh` it scores below Gemini on the Intelligence Index and at most 2 points above it on Terminal-Bench. At `xhigh` it leads Gemini by 9.6 points on Terminal-Bench, which the runner does not need.
- Sonnet: `high` scores below Sol `medium` on both indexes and costs about four times more per task. `xhigh` scores 0.7 above Opus `medium`, which the orchestrator already provides.
- Sol `low`: 17 points below `medium` on Terminal-Bench.

## Harness for Gemini

Gemini 3.8 Flash runs on the `opencode` driver, through the `cliproxy` OpenCode plugin. On that driver the effort option is `variant`, not `reasoningEffort`.

Evidence from 2026-10-12:

- Two T3 `delegate_task` smoke runs passed: a read-only lookup in 23 s, and a `shell` call with `background: true` whose file appeared after the child kept working.
- Headless `opencode run` with OpenCode 2.0.27 hung at startup in 6 of 17 runs: no session, no request, and no error logged, while the gateway answered the same prompt in under 2 s. The T3 runs did not hang.

Alternatives evaluated on 2026-10-11:

- `codex`: works, but its tools and prompts target GPT models.

- `pi`: four default tools and a `bash` tool that blocks until the command exits.
- `antigravity`: Google's native driver. Its own subagents cannot be disabled.
- `claudeAgent`: exposes Gemini only under a renamed model ID, with no effort option.
- Oh-my-pi through the `acpRegistry` driver: async `bash`, a Gemini stall guard, and no T3 MCP injection. Parked because it needs a new T3 provider instance.

## Session timings

From GPT-6.1 Sol sessions on the user's machines: median 8.5 minutes at `medium` and 20 minutes at `high`. Too few `xhigh` sessions exist for a median.
