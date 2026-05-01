import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadConfig } from "./config.js";
import { agentHintForBlock, agentHintForWarning, formatToolSignature } from "./hints.js";
import { __test, actionForCommand, reasonForCommand } from "./matcher.js";
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
          caseSensitive: false,
          names: ["python", "python2", "python3", "pythonw", "pythonw2", "pythonw3", "py", "pypy", "pypy3"],
          patterns: ["^pythonw?(?:[23])?(?:\\.\\d+)*(?:\\.exe)?$", "^py(?:\\.exe)?$", "^pypy(?:3)?(?:\\.exe)?$"],
        },
        action: {
          type: "block",
          message: "use uv",
        },
      },
      {
        id: "no-python-m-pip",
        match: {
          type: "regex",
          pattern: "\\b(?:pythonw?(?:[23])?(?:\\.\\d+)*|py|pypy3?)\\b[^\\n;|&]*(?:\\s-m\\s*pip\\b|\\s-mpip\\b)",
          flags: "i",
        },
        action: {
          type: "block",
          message: "use uv",
        },
      },
      {
        id: "no-pip",
        match: {
          type: "executable",
          caseSensitive: false,
          names: ["pip", "pip2", "pip3", "pipx"],
          patterns: ["^pip(?:[23])?(?:\\.\\d+)*(?:\\.exe)?$", "^pipx(?:\\.exe)?$"],
        },
        action: {
          type: "block",
          message: "use uv",
        },
      },
      {
        id: "no-python-env-tools",
        match: {
          type: "executable",
          caseSensitive: false,
          names: ["conda", "hatch", "mamba", "pdm", "pipenv", "poetry", "rye", "virtualenv"],
          patterns: ["^(?:conda|hatch|mamba|pdm|pipenv|poetry|rye|virtualenv)(?:\\.exe)?$"],
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

const searchConfig: GuardrailsConfig = {
  version: 1,
  agentBash: {
    rules: [
      {
        id: "prefer-native-file-discovery-rg-files",
        match: {
          type: "regex",
          pattern: "\\b(?:rg|ripgrep)\\b[^\\n;|&]*\\s--files\\b",
          flags: "i",
        },
        action: {
          type: "warn",
          message: "prefer native find tool",
        },
      },
      {
        id: "prefer-native-file-discovery-git-ls-files",
        match: {
          type: "regex",
          pattern: "\\bgit\\b[^\\n;|&]*\\bls-files\\b",
          flags: "i",
        },
        action: {
          type: "warn",
          message: "prefer native find tool",
        },
      },
      {
        id: "prefer-native-content-search",
        match: {
          type: "executable",
          caseSensitive: false,
          names: [
            "rg",
            "ripgrep",
            "ag",
            "ack",
            "ack-grep",
            "pt",
            "ugrep",
            "sift",
            "grep",
            "ggrep",
            "findstr",
            "select-string",
          ],
          patterns: ["^(?:rg|ripgrep|ag|ack(?:-grep)?|pt|ugrep|sift|grep|ggrep|findstr|select-string)(?:\\.exe)?$"],
        },
        action: {
          type: "warn",
          message: "prefer native grep tool",
        },
      },
      {
        id: "prefer-native-content-search-git-grep",
        match: {
          type: "regex",
          pattern: "\\bgit\\b[^\\n;|&]*\\bgrep\\b",
          flags: "i",
        },
        action: {
          type: "warn",
          message: "prefer native grep tool",
        },
      },
      {
        id: "prefer-native-file-discovery",
        match: {
          type: "executable",
          caseSensitive: false,
          names: ["fd", "fdfind", "fd-find", "find", "gfind", "locate", "mlocate", "plocate"],
          patterns: ["^(?:fd|fdfind|fd-find|find|gfind|locate|mlocate|plocate)(?:\\.exe)?$"],
        },
        action: {
          type: "warn",
          message: "prefer native find tool",
        },
      },
    ],
  },
  protectedPaths: {
    rules: [],
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

test("loadConfig accepts warn actions for agentBash rules", () => {
  const dir = mkdtempSync(join(tmpdir(), "guardrails-"));
  const path = join(dir, "guardrails.jsonc");

  writeFileSync(
    path,
    `{
      "version": 1,
      "agentBash": {
        "rules": [
          {
            "match": { "type": "executable", "names": ["rg"] },
            "action": { "type": "warn", "message": "prefer native grep" }
          }
        ]
      },
      "protectedPaths": { "rules": [] }
    }`,
  );

  const result = loadConfig(path);
  assert.equal(result.ok, true);
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

test("blocks direct python heredoc stdin invocation", () => {
  assert.equal(reasonForCommand("python3 - <<'PY'\nprint(1)\nPY", pythonConfig), "use uv");
  assert.equal(reasonForCommand("python - <<PY\nprint(1)\nPY", pythonConfig), "use uv");
});

test("blocks versioned and alternate python executables", () => {
  assert.equal(reasonForCommand('.venv/bin/python3.12 -c "print(1)"', pythonConfig), "use uv");
  assert.equal(reasonForCommand('python3.12.exe -c "print(1)"', pythonConfig), "use uv");
  assert.equal(reasonForCommand('pythonw.exe script.py', pythonConfig), "use uv");
  assert.equal(reasonForCommand('py -3 script.py', pythonConfig), "use uv");
  assert.equal(reasonForCommand('py.exe -3.12 script.py', pythonConfig), "use uv");
  assert.equal(reasonForCommand('pypy3 -c "print(1)"', pythonConfig), "use uv");
});

 test("blocks python packaging and environment tools", () => {
  assert.equal(reasonForCommand("pip3.12 install rich", pythonConfig), "use uv");
  assert.equal(reasonForCommand("pip.exe install rich", pythonConfig), "use uv");
  assert.equal(reasonForCommand("pipx run black .", pythonConfig), "use uv");
  assert.equal(reasonForCommand("poetry install", pythonConfig), "use uv");
  assert.equal(reasonForCommand("pipenv run pytest", pythonConfig), "use uv");
  assert.equal(reasonForCommand("virtualenv .venv", pythonConfig), "use uv");
  assert.equal(reasonForCommand("conda env list", pythonConfig), "use uv");
});

test("blocks env wrapped python invocation", () => {
  assert.equal(reasonForCommand("/usr/bin/env PYTHONPATH=. python script.py", pythonConfig), "use uv");
  assert.equal(reasonForCommand("/usr/bin/env -S py -3 script.py", pythonConfig), "use uv");
});

test("blocks python module package tooling", () => {
  assert.equal(reasonForCommand("uv run python -m pip install rich", pythonConfig), "use uv");
});

test("blocks sudo wrapped python invocation", () => {
  assert.equal(reasonForCommand("sudo -u annt python script.py", pythonConfig), "use uv");
});

test("blocks shell -c nested python invocation", () => {
  assert.equal(reasonForCommand("bash -lc 'python -m pytest'", pythonConfig), "use uv");
});

test("blocks pwsh -Command nested python invocation", () => {
  assert.equal(reasonForCommand("pwsh -NoProfile -Command 'python -m pytest'", pythonConfig), "use uv");
  assert.equal(reasonForCommand("pwsh.exe -Command \"python -m pytest\"", pythonConfig), "use uv");
  assert.equal(reasonForCommand("powershell -Command \"python -m pytest\"", pythonConfig), "use uv");
  assert.equal(reasonForCommand("powershell.exe -Command \"python -m pytest\"", pythonConfig), "use uv");
});

test("does not block harmless mentions", () => {
  assert.equal(reasonForCommand("echo python", pythonConfig), null);
  assert.equal(reasonForCommand("rg python README.md", pythonConfig), null);
  assert.equal(reasonForCommand("command -v python", pythonConfig), null);
});

test("allows uv-based python workflow", () => {
  assert.equal(reasonForCommand("uv run python script.py", pythonConfig), null);
});

test("ignores commands inside heredoc bodies", () => {
  assert.equal(reasonForCommand("cat <<'EOF'\nrg TODO\nEOF", searchConfig), null);
  assert.equal(reasonForCommand("uv run python - <<'PY'\nprint('python -m pip is text')\nPY", pythonConfig), null);
});

test("allows uv-based python workflow with heredoc stdin", () => {
  assert.equal(
    reasonForCommand("uv run python - <<'PY'\nimport importlib.util\nprint('ok')\nPY", pythonConfig),
    null,
  );
  assert.equal(reasonForCommand('uv run python - <<"PY-EOF"\nprint("ok")\nPY-EOF', pythonConfig), null);
});

test("does not treat quoted heredoc markers as heredocs", () => {
  assert.equal(reasonForCommand('echo "<<PY"\npython script.py', pythonConfig), "use uv");
});

test("warns for shell content-search commands", () => {
  assert.equal(reasonForCommand("rg TODO", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("rg TODO src/main.ts", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("rg TODO src --glob '*.ts'", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("rg --hidden --no-ignore TODO src", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("git grep TODO", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("git grep TODO src/", searchConfig), "prefer native grep tool");
  assert.equal(reasonForCommand("grep -R TODO .", searchConfig), "prefer native grep tool");
  assert.equal(
    reasonForCommand("pwsh -NoProfile -Command 'Select-String -Pattern TODO -Path . -Recurse'", searchConfig),
    "prefer native grep tool",
  );
  assert.equal(
    reasonForCommand("git log --oneline -n 8 && rg -n \"foo\" tools/pi/agent/extensions/footer/index.ts && git status --short", searchConfig),
    "prefer native grep tool",
  );

  assert.equal(actionForCommand("rg TODO", searchConfig)?.type, "warn");
});

test("does not warn for informational shell content-search commands", () => {
  assert.equal(reasonForCommand("rg --help", searchConfig), null);
  assert.equal(reasonForCommand("rg --version", searchConfig), null);
  assert.equal(reasonForCommand("git grep --help", searchConfig), null);
  assert.equal(reasonForCommand("git ls-files --help", searchConfig), null);
});

test("agent warning hints name native replacements and shell executables", () => {
  const tools = [
    { name: "grep", parameters: { properties: { pattern: {}, paths: {}, outputMode: {}, ignored: {}, timeoutMs: {} } } },
    { name: "find", parameters: { properties: { pattern: {}, paths: {}, kind: {}, ignored: {} } } },
  ];

  const grepHint = agentHintForWarning("Use native `grep` tool for repo search.", tools);
  assert.match(grepHint, /don't use shell search executables/);
  assert.match(grepHint, /`rg`/);
  assert.match(grepHint, /grep\(\{ pattern, paths, outputMode, ignored, timeoutMs \}\)/);

  const findHint = agentHintForWarning("Use native `find` tool for file lookup.", tools);
  assert.match(findHint, /don't use shell discovery executables/);
  assert.match(findHint, /`fd`/);
  assert.match(findHint, /find\(\{ pattern, paths, kind, ignored \}\)/);
});

test("tool signatures fall back when live schema is unavailable", () => {
  assert.match(formatToolSignature("grep", []), /outputMode/);
  assert.match(formatToolSignature("find", []), /kind/);
});

test("python block hints point to python skill and uv", () => {
  const hint = agentHintForBlock("Python env/package tooling is disabled. Load `/skill:python`.");
  assert.match(hint, /direct Python tooling disabled/);
  assert.match(hint, /\/skill:python/);
  assert.match(hint, /uv run/);
  assert.equal(agentHintForBlock("Reading .env files is blocked by guardrails."), "Reading .env files is blocked by guardrails.");
});

test("warns for broad shell file-discovery commands", () => {
  assert.equal(reasonForCommand("rg --files", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("ripgrep --files src", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("rg --files | nl -ba", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("git ls-files", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("git ls-files '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("fd '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("fd-find '*.ts' .", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("gfind . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find src -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find src -maxdepth 2 -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find / -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find . -name '*.ts' | head", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("echo x | find . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("find . -name '*.ts' -print0 | xargs -0 grep TODO", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("env FOO=1 find . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("command find . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("sudo find . -name '*.ts'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("locate js", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("bash -lc 'find . -name \"*.ts\"'", searchConfig), "prefer native find tool");
  assert.equal(reasonForCommand("sh -c 'find src -name \"*.ts\"'", searchConfig), "prefer native find tool");

  assert.equal(actionForCommand("fd '*.ts'", searchConfig)?.type, "warn");
});

test("does not warn for informational or narrow non-find shell file-discovery commands", () => {
  assert.equal(reasonForCommand("fd '*.ts' src", searchConfig), null);
  assert.equal(reasonForCommand("find --help", searchConfig), null);
  assert.equal(reasonForCommand("find --version", searchConfig), null);
  assert.equal(reasonForCommand("locate package.json", searchConfig), null);
});

test("optionHasValue token rules remain stable", () => {
  assert.equal(__test.optionHasValue("--glob", "rg"), true);
  assert.equal(__test.optionHasValue("--threads", "ripgrep"), true);
  assert.equal(__test.optionHasValue("--glob", "fd"), true);
  assert.equal(__test.optionHasValue("-maxdepth", "find"), true);
  assert.equal(__test.optionHasValue("--version", "rg"), false);
});

test("does not warn for harmless mentions of search tool names", () => {
  assert.equal(reasonForCommand("echo rg", searchConfig), null);
  assert.equal(reasonForCommand("printf 'use find and grep tools'", searchConfig), null);
  assert.equal(reasonForCommand("command -v rg", searchConfig), null);
  assert.equal(reasonForCommand("where git", searchConfig), null);
  assert.equal(reasonForCommand("pwsh -NoProfile -Command 'gci -File'", searchConfig), null);
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
      ],
    },
  };

  assert.equal(reasonForPath("/tmp/project/.git", "read", config), "no git reads");
  assert.equal(reasonForPath("/tmp/project/.git/config", "read", config), "no git reads");
});

test("allows node_modules reads while still supporting node_modules write blocks", () => {
  const config: GuardrailsConfig = {
    version: 1,
    agentBash: { rules: [] },
    protectedPaths: {
      rules: [
        {
          id: "no-write-node-modules",
          pattern: "node_modules",
          tools: ["write", "edit"],
          action: { type: "block", message: "no node_modules writes" },
        },
      ],
    },
  };

  assert.equal(reasonForPath("/tmp/project/node_modules", "read", config), null);
  assert.equal(reasonForPath("/tmp/project/node_modules/react/index.js", "read", config), null);
  assert.equal(reasonForPath("/tmp/project/node_modules", "write", config), "no node_modules writes");
  assert.equal(reasonForPath("/tmp/project/node_modules/react/index.js", "edit", config), "no node_modules writes");
});
