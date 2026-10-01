# GPT apply_patch

This Pi extension replaces active `edit` and `write` tools with `apply_patch` for GPT models whose Codex metadata declares patch support. OpenAI-compatible transport alone does not activate it.

## Model selection

Codex enables the tool when `model_info.apply_patch_tool_type` is present. Its model lookup uses the longest matching catalog slug prefix, then retries after one simple provider namespace, such as `command-code/gpt-6.1-sol`. Matching is case-sensitive. Unknown models receive fallback metadata with no patch capability.

Pi does not expose that Codex metadata. The extension uses the GPT entries from Codex 0.159.2's shipped catalog, projected into [model-catalog.ts](model-catalog.ts). Internal non-GPT entries are excluded to keep this extension GPT-only. It uses the same lookup and capability condition; it does not read Codex's machine-local cache or assume that future GPT versions support patching.

Sources: [tool selection](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/core/src/tools/spec_plan.rs), [model lookup](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/models-manager/src/manager.rs), [fallback metadata](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/models-manager/src/model_info.rs), and [shipped catalog](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/models-manager/models.json). When updating the snapshot, preserve each GPT entry's `slug` and `apply_patch_tool_type`, then run the model-selection tests.

Switching to another model hides `apply_patch` from both model declarations and nested tool calls, then restores the tools the extension replaced. Unrelated active tools stay active. The executor also rejects calls from non-GPT models.

Read-only tool selections stay read-only. With `--tools`, include `apply_patch` in the allowlist as well as `edit` or `write` for model switching. If the allowlist or `--exclude-tools` excludes `apply_patch`, the extension leaves the original tools active.

## Patch execution

The extension invokes the installed `codex` CLI on `PATH` with `--codex-run-as-apply-patch`. This runs Codex's native patch engine locally without authentication or a model request. The hidden CLI flag was verified with Codex 0.159.2; keep the native execution tests passing when updating Codex.

The tool accepts an `input` string containing Codex's `*** Begin Patch` syntax. Add, update, delete, move, context anchors, and end-of-file matching use the native engine. Paths resolve from Pi's working directory. Source and destination paths share Pi's file mutation queues, including symlink aliases and new files under symlinked directories.

The [grammar](grammar.ts) comes from [OpenAI Codex](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/core/assets/tools/apply_patch.lark), under [Apache-2.0](LICENSE). Pi sends it as a Lark custom tool when the model's Responses transport advertises `supportsOpenAIGrammarTools`. Other transports receive a JSON function tool with the same `input` string. In particular, the current `cliproxy` extension uses Chat Completions, so it gets the JSON form.

Multi-file execution is not transactional. On failure or cancellation, earlier changes may remain applied. Error output includes the native engine's report. Results over Pi's output limits are truncated, with the complete output saved to a temporary file whose path appears in the result.

The [pi-codex-conversion reference](https://github.com/IgorWarzocha/howaboua-pi-stuff/tree/main/packages/pi-codex-conversion) informed the tool shape and mutation queue integration. This extension uses the existing Codex installation rather than vendoring its Rust engine or replacing Pi's providers.

## Load and validate

After sync publishes the extension, run `/reload` in Pi or restart it. To load this checkout directly from the repository root:

```sh
pi --no-extensions -e ./harnesses/pi/agent/extensions/apply-patch/index.ts
```

With Pi's host packages available to Bun, run:

```sh
bun test harnesses/pi/agent/extensions/apply-patch/
git diff --check
```

The native engine tests require `codex` on `PATH`. For a fresh runtime check, use an authenticated GPT provider in a temporary working directory:

```sh
pi --no-extensions -e /absolute/path/to/apply-patch/index.ts \
	--provider openai --model gpt-6.1-sol --no-session --mode json -p \
	--tools read,bash,edit,write,apply_patch \
	'Use apply_patch to create proof.txt containing hello, then change it to goodbye. Read it to verify the result.'
```

Inspect the JSONL tool execution events and `proof.txt`. A custom gateway provider also needs its provider extension loaded with `-e`.
