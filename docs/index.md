# Agent configuration documentation

Choose a page by the task you need to complete. Sync application documentation lives under `docs/sync/`; harness-local documentation lives beside its source under `harnesses/`.

## Set up

- [Set up agent configuration](quickstart.md) walks through a first installation and verifies the model endpoint.

## Operate

- [CLIProxyAPI](cliproxyapi.md) changes credentials, authenticates ChatGPT, runs the gateway, and lists artifacts, configuration fields, discovery rules, and routing settings.

## Develop

- [Develop the sync application](sync/development.md) runs checks and changes sync or harness integration.
- [Manage shared skills](skills.md) changes, validates, publishes, and archives skills; it is also the skill gate.

## Reference

- [Repository layout](repository-layout.md) maps committed sources, local inputs, generated targets, and runtime state.
- [Sync reference](sync/sync.md) lists commands, reconciliation stages, caches, and failure behavior.
- [Harness adapter reference](sync/harnesses.md) defines adapter metadata, generated paths, model integration, and wrappers.
