# Work with user-plugin modes

Read this when creating, changing, or verifying an Amp user-plugin agent mode.

1. Locate the personal plugins checkout. Use an existing checkout when available; otherwise use `amp clone user-plugins <checkout-dir>`. Check its remote, branch, working tree, and local instructions before editing. Update a clean checkout from its remote before building on it.
2. Inspect the nearest mode, `modes/modes/index.ts`, `modes/index.ts`, `modes/shared/tools.ts`, and the package scripts. The current layout includes each mode in `allModes` and a matching `// @amp-agent-mode` header. The header lets clients discover the mode and required features before the plugin starts. [Amp's plugin docs](https://ampcode.com/docs/markdown/customize/plugins) say a mode without it can still load, but clients warn until matching metadata is added and reloaded.
3. Resolve each requested model through `amp plugins show-agent-options`. Inspect the current tool lists and feature policy rather than copying another model family's tools or paid feature flags. If models use a custom provider, follow [model routing](routing.md) for every main, Oracle, and subagent model that needs a mapping.
4. Add the mode definition and both registration entries. Run the checkout's typecheck script, compare header keys with registered mode keys, and inspect the requested models, efforts, tools, and features in the loaded mode definition.
5. After an authorized push, verify the remote result and run `amp plugins list` to check discovery. The CLI's mode tool listing can report zero tools for plugin modes; inspect the loaded definition or a live thread for tool behavior. If a running service must reload plugins, follow [runners](runners.md).

Keep mode source in the plugins repository. This configuration repository owns Amp's local settings and shared skills, not the personal plugin repository.

## Tools and subagent models

- An explicit `tools` array, or `include` list, replaces the extended mode's defaults, including delegation tools; `add` extends them and `exclude` always wins. Keep `mcp__*` and `plugin__*` in explicit lists so MCP and plugin tools stay available. `amp plugins show-docs` prints the current plugin API types.
- Give each model family the tools it was trained on. [Amp's official modes](https://github.com/ampcode/official-plugins/tree/main/official-modes/modes) are the reference: GPT gets `apply_patch` and no `Read`, frontier Claude gets `edit_file` and `create_file` without `Read`, and other families also get `Read`.
- `amp tools show <tool> --mode <built-in mode> --json` describes a tool; `tools list` and `tools show` resolve built-in modes only.
- A mode's `oracle` and `subagents` pins cover the Oracle, Task workers, finder, thread reader, and librarian, so routing must cover exactly those models plus the main model.
