import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadConfig } from "./config.js";
import { reasonForCommand } from "./matcher.js";
import { reasonForPath } from "./paths.js";
import type { GuardrailsConfig } from "./types.js";

const pythonConfig: GuardrailsConfig = {
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
  protectedPaths: {
    rules: [
      {
        id: "no-read-env",
        pattern: ".env",
        tools: ["read"],
        action: {
          type: "block",
          message: "no env reads",
        },
      },
    ],
  },
};

test("loadConfig accepts JSONC comments and trailing commas", () => {
  const dir = mkdtempSync(join(tmpdir(), "guardrails-"));
  const path = join(dir, "guardrails.jsonc");

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
      "protectedPaths": {
        "rules": [
          {
            "id": "no-read-env",
            "pattern": ".env",
            "tools": ["read",],
            "action": {
              "type": "block",
              "message": "no env reads",
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
  assert.equal(result.config.protectedPaths.rules.length, 1);
});

test("loadConfig fails closed on invalid config", () => {
  const dir = mkdtempSync(join(tmpdir(), "guardrails-"));
  const path = join(dir, "guardrails.jsonc");

  writeFileSync(
    path,
    `{
      "version": 2,
      "agentBash": { "rules": [] },
      "protectedPaths": { "rules": [] }
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
  assert.equal(reasonForCommand('.venv/bin/python3.12 -c "print(1)"', pythonConfig), "use uv");
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
  const config: GuardrailsConfig = {
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
    protectedPaths: {
      rules: [],
    },
  };

  assert.equal(reasonForCommand("bash -lc 'python -m pip install rich'", config), "use uv add or uv run --with");
});

test("blocks protected reads", () => {
  assert.equal(reasonForPath("/tmp/project/.env", "read", pythonConfig), "no env reads");
});

test("does not block unmatched tools for protected paths", () => {
  assert.equal(reasonForPath("/tmp/project/.env", "write", pythonConfig), null);
});

test("does not overblock .env.example", () => {
  assert.equal(reasonForPath("/tmp/project/.env.example", "read", pythonConfig), null);
});

test("blocks protected directory roots and children", () => {
  const config: GuardrailsConfig = {
    version: 1,
    agentBash: { rules: [] },
    protectedPaths: {
      rules: [
        {
          id: "no-read-git",
          pattern: ".git",
          tools: ["read"],
          action: { type: "block", message: "no git reads" },
        },
        {
          id: "no-read-node-modules",
          pattern: "node_modules",
          tools: ["read"],
          action: { type: "block", message: "no node_modules reads" },
        },
      ],
    },
  };

  assert.equal(reasonForPath("/tmp/project/.git", "read", config), "no git reads");
  assert.equal(reasonForPath("/tmp/project/.git/config", "read", config), "no git reads");
  assert.equal(reasonForPath("/tmp/project/node_modules", "read", config), "no node_modules reads");
  assert.equal(reasonForPath("/tmp/project/node_modules/react/index.js", "read", config), "no node_modules reads");
});
