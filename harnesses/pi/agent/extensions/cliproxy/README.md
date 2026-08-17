# Pi CLIProxyAPI extension

The extension reads ordered reasoning efforts from the shared model catalog. `piThinkingLevelMap()` projects those strings onto Pi's closed thinking-level set. Unsupported Pi levels map to `null`, and `max` maps to the last advertised effort. This keeps an unknown future effort reachable through `max`.
