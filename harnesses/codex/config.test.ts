import { test } from "bun:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

test("multi_agent_v2 stays under the features table", () => {
  const source = readFileSync(join(import.meta.dir, "config.toml"), "utf8");
  assert.doesNotMatch(source, /^\[multi_agent_v2\]$/m);
  assert.match(source, /^\[features\.multi_agent_v2\]$/m);
});
