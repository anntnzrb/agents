# Agent configuration documentation

Choose a page by the task you need to complete. Sync application documentation lives under `docs/sync/`; harness-local documentation lives beside its source under `harnesses/`.

## Set up

- [Set up agent configuration](quickstart.md) walks through a first installation and verifies the model endpoint.

## Operate

- [CLIProxyAPI](cliproxyapi.md) changes credentials, authenticates OAuth accounts, runs the gateway, and lists artifacts, configuration fields, discovery rules, and routing settings.
- [Cache sweeper](cache-gc.md) reclaims npm, uv, and bun caches and stale `/tmp` scratch nightly on the hosts declared by `tools/cache-gc/`.
- [Paseo daemon](paseo.md) runs the Paseo agent daemon on the hosts declared by `tools/paseo/` and publishes it to the tailnet.
- [T3 Code server](t3.md) (legacy, no hosts) installs, repairs, exposes, and moves the T3 background service declared by `tools/t3/`.

## Develop

- [Verify a change in CI](ci.md) runs repository checks, diagnoses failures, explains the required merge check, and merges a pull request.
- [Develop the sync application](sync/development.md) runs checks and changes sync, harness integration, or managed tools.
- [Manage shared skills](skills.md) creates, changes, validates, publishes, and archives skills; it is also the skill gate.

## Reference

- [Repository layout](repository-layout.md) maps committed sources, local inputs, generated targets, and runtime state.
- [Sync reference](sync/sync.md) lists commands, reconciliation stages, background updates, caches, and failure behavior.
- [Harness adapter reference](sync/harnesses.md) defines adapter metadata, generated paths, model integration, and wrappers.
