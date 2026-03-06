import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadConfig } from "./config";
import { reasonForCommand } from "./matcher";
import type { CommandGuardConfig } from "./types";

const pythonConfig: CommandGuardConfig = {
  version: 1,
  agentBash: {
    rules: [
      {
        id: "no-python",
        match: {
          type: "executable",
          names: ["python", "python3"],
          patterns: ["^python3(?:\\.\\d+)+$"],
        },
        action: {
          type: "block",
          message: "use uv",
        },
      },
    ],
  },
};

test("loadConfig accepts JSONC comments and trailing commas", () => {
  const dir = mkdtempSync(join(tmpdir(), "command-guard-"));
  const path = join(dir, "command-guard.jsonc");

  writeFileSync(
    path,
    `{
      // comment
      "version": 1,
      "agentBash": {
        "rules": [
          {
            "id": "no-python",
            "match": {
              "type": "executable",
              "names": ["python",],
            },
            "action": {
              "type": "block",
              "message": "use uv",
            },
          },
        ],
      },
    }`,
  );

  const result = loadConfig(path);
  assert.equal(result.ok, true);
  if (!result.ok) {
    return;
  }
  assert.equal(result.config.agentBash.rules.length, 1);
});

test("loadConfig fails closed on invalid config", () => {
  const dir = mkdtempSync(join(tmpdir(), "command-guard-"));
  const path = join(dir, "command-guard.jsonc");

  writeFileSync(
    path,
    `{
      "version": 2,
      "agentBash": { "rules": [] }
    }`,
  );

  const result = loadConfig(path);
  assert.equal(result.ok, false);
  if (result.ok) {
    return;
  }
  assert.match(result.reason, /version must be 1/);
});

test("blocks direct python invocation", () => {
  assert.equal(reasonForCommand("python script.py", pythonConfig), "use uv");
});

test("blocks versioned python executable", () => {
  assert.equal(reasonForCommand(".venv/bin/python3.12 -c \"print(1)\"", pythonConfig), "use uv");
});

test("blocks env wrapped python invocation", () => {
  assert.equal(reasonForCommand("/usr/bin/env PYTHONPATH=. python script.py", pythonConfig), "use uv");
});

test("blocks sudo wrapped python invocation", () => {
  assert.equal(reasonForCommand("sudo -u annt python script.py", pythonConfig), "use uv");
});

test("blocks shell -c nested python invocation", () => {
  assert.equal(reasonForCommand("bash -lc 'python -m pytest'", pythonConfig), "use uv");
});

test("does not block harmless mentions", () => {
  assert.equal(reasonForCommand("echo python", pythonConfig), null);
  assert.equal(reasonForCommand("rg python README.md", pythonConfig), null);
  assert.equal(reasonForCommand("command -v python", pythonConfig), null);
});

test("allows uv-based python workflow", () => {
  assert.equal(reasonForCommand("uv run python script.py", pythonConfig), null);
});

test("regex rules apply inside nested shell wrappers", () => {
  const config: CommandGuardConfig = {
    version: 1,
    agentBash: {
      rules: [
        {
          id: "no-python-pip",
          match: {
            type: "regex",
            pattern: "\\bpython(?:3(?:\\.\\d+)*)?\\s+-m\\s+pip\\b",
          },
          action: {
            type: "block",
            message: "use uv add or uv run --with",
          },
        },
      ],
    },
  };

  assert.equal(reasonForCommand("bash -lc 'python -m pip install rich'", config), "use uv add or uv run --with");
});
