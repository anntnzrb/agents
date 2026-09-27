# Change model routing

Read this when an Amp mode or agent must use a custom model provider.

1. Check Amp's model ID with `amp plugins show-agent-options`. Check the backend's current model inventory through its configured endpoint. Keep the Amp ID and backend ID distinct; do not infer either from display names.
2. Identify the intended router with `amp config model-providers` and read its current configuration with `amp config model-providers show <router-id>`. To register a new endpoint, use `amp config model-providers add-router custom-url`. Pass credentials via `--api-key-file -` to avoid exposing secrets in command arguments or shell history.
3. For an authorized change, pass the complete existing mapping plus the intended edit to `amp config model-providers edit-router <router-id> --model-mapping <mapping>`. That option replaces the whole mapping. Preserve unrelated entries and their ordering; the last matching line wins within one mapping. Check for another writer before submitting a stale snapshot.
4. Read the router again and verify the exact mapping. Confirm that every routed model in the mode, including Oracle and subagents, has a valid route. Check active connection priority: Amp uses the first matching personal connection, then workspace connections, then Amp. If another connection wins, adjust priority with `amp config model-providers set-priority <connection-id> <priority>` (such as `0` to evaluate before cloud credits) or exclude the model from that connection. With authorization for a short inference, `amp config model-providers check-access --provider-model <provider/model>` reports which connection served it.

Use [Amp's model-routing docs](https://ampcode.com/docs/markdown/customize/model-routing) and `amp config model-providers edit-router --help` for current behavior and syntax. Do not bake router IDs, hostnames, gateway secrets, or current model inventories into the skill.

## Formats, verification, and leaks

- A connection has one API format. To serve model families in different formats from one backend, create one connection per format against the same base URL and split the mapping by provider prefix. Verify the new connection with `amp config model-providers test <id>` and every moved model with `check-access` before removing lines from the old connection; keep the old mapping to restore.
- `check-access` needs an unarchived thread you own: create one with `amp threads new --visibility private` and archive it afterwards. An archived thread, or calls closer than about 5 seconds apart, return a bare `Internal error`. Pass the mode's `--reasoning-effort`: the default can disable thinking, which thinking-only upstreams reject, so a failure at the default effort does not prove the route broken.
- `-> <backend-id>` maps an Amp model to the backend ID. Amp's plugin validator rejects model IDs not listed in `amp plugins show-agent-options`; to route an unlisted backend model, use an allowed placeholder ID in the plugin mode and remap it here. Remap within the same model family, because Amp still builds that slot's prompt and tools for the requested model.
- Find what still bills Amp with `amp usage --details` (per-model cost) and `amp threads usage <thread> --details`, whose model-routing table shows the connection that served each purpose and whose input line reports cache reads.
