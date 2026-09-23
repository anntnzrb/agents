# Work with user-plugin modes

Read this when creating, changing, or verifying an Amp user-plugin agent mode.

1. Locate the personal plugins checkout. Use an existing checkout when available; otherwise use `amp clone user-plugins <checkout-dir>`. Check its remote, branch, working tree, and local instructions before editing. Update a clean checkout from its remote before building on it.
2. Inspect the nearest mode, `modes/modes/index.ts`, `modes/index.ts`, `modes/shared/tools.ts`, and the package scripts. The current layout includes each mode in `allModes` and a matching `// @amp-agent-mode` header. The header lets clients discover the mode and required features before the plugin starts. [Amp's plugin docs](https://ampcode.com/docs/markdown/customize/plugins) say a mode without it can still load, but clients warn until matching metadata is added and reloaded.
3. Resolve each requested model through `amp plugins show-agent-options`. Inspect the current tool lists and feature policy rather than copying another model family's tools or paid feature flags. If models use a custom provider, follow [model routing](routing.md) for every main, Oracle, and subagent model that needs a mapping.
4. Add the mode definition and both registration entries. Run the checkout's typecheck script, compare header keys with registered mode keys, and inspect the requested models, efforts, tools, and features in the loaded mode definition.
5. After an authorized push, verify the remote result and run `amp plugins list` to check discovery. The CLI's mode tool listing can report zero tools for plugin modes; inspect the loaded definition or a live thread for tool behavior. If a running service must reload plugins, follow [runners](runners.md).

Keep mode source in the plugins repository. This configuration repository owns Amp's local settings and shared skills, not the personal plugin repository.
