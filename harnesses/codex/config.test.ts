import { test } from "bun:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

test("multi_agent_v2 stays under the features table", () => {
  const source = readFileSync(join(import.meta.dir, "config.toml"), "utf8");
  assert.doesNotMatch(source, /^\[multi_agent_v2\]$/m);
  assert.match(source, /^\[features\.multi_agent_v2\]$/m);
});

test("Codex hooks are disabled and absent", () => {
  const config = readFileSync(join(import.meta.dir, "config.toml"), "utf8");
  assert.match(config, /^hooks = false$/m);
  assert.equal(existsSync(join(import.meta.dir, "hooks.json")), false);
  assert.equal(existsSync(join(import.meta.dir, "hooks")), false);
});

test("all agents have full access except explorer", () => {
  const config = readFileSync(join(import.meta.dir, "config.toml"), "utf8");
  assert.match(config, /^approval_policy = "never"$/m);
  assert.match(config, /^default_permissions = ":danger-full-access"$/m);
  assert.match(config, /^web_search = "live"$/m);
  assert.doesNotMatch(config, /^\[permissions\.(?:agent-workspace|agent-review)\]$/m);

  for (const agent of [
    "code-reviewer.toml",
    "qa-executor.toml",
    "worker-high.toml",
    "worker-medium.toml",
  ]) {
    const source = readFileSync(join(import.meta.dir, "agents", agent), "utf8");
    assert.match(source, /^default_permissions = ":danger-full-access"$/m, agent);
  }

  const explorer = readFileSync(join(import.meta.dir, "agents", "explorer.toml"), "utf8");
  assert.match(explorer, /^default_permissions = ":read-only"$/m);
});
