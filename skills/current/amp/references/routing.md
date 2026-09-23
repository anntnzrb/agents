# Change model routing

Read this when an Amp mode or agent must use a custom model provider.

1. Check Amp's model ID with `amp plugins show-agent-options`. Check the backend's current model inventory through its configured endpoint. Keep the Amp ID and backend ID distinct; do not infer either from display names.
2. Identify the intended router with `amp config model-providers` and read its current configuration with `amp config model-providers show <router-id>`. Do not print credentials or copy them into command arguments, logs, or skill files.
3. For an authorized change, pass the complete existing mapping plus the intended edit to `amp config model-providers edit-router <router-id> --model-mapping <mapping>`. That option replaces the whole mapping. Preserve unrelated entries and their ordering; the last matching line wins within one mapping. Check for another writer before submitting a stale snapshot.
4. Read the router again and verify the exact mapping. Confirm that every routed model in the mode, including Oracle and subagents, has a valid route. Check active connection priority: Amp uses the first matching personal connection, then workspace connections, then Amp. If another connection wins, change priority or exclude the model from that connection. With authorization for a short inference, `amp config model-providers check-access --provider-model <provider/model>` reports which connection served it.

Use [Amp's model-routing docs](https://ampcode.com/docs/markdown/customize/model-routing) and `amp config model-providers edit-router --help` for current behavior and syntax. Do not bake router IDs, hostnames, gateway secrets, or current model inventories into the skill.
