import { performance } from "node:perf_hooks";

import { actionForCommand } from "./matcher.js";
import type { GuardrailsConfig } from "./types.js";

const ITERATIONS = Number.parseInt(
  process.env["GUARDRAILS_BENCH_ITERS"] ?? "100000",
  10,
);

const config: GuardrailsConfig = {
  version: 1,
  skillBindings: {},
  agentBash: {
    rules: [
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
          patterns: [
            "^(?:rg|ripgrep|ag|ack(?:-grep)?|pt|ugrep|sift|grep|ggrep|findstr|select-string)(?:\\.exe)?$",
          ],
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
          names: [
            "fd",
            "fdfind",
            "fd-find",
            "find",
            "gfind",
            "locate",
            "mlocate",
            "plocate",
          ],
          patterns: [
            "^(?:fd|fdfind|fd-find|find|gfind|locate|mlocate|plocate)(?:\\.exe)?$",
          ],
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

const corpus = [
  "rg -n TODO src",
  "git grep TODO",
  "find . -name '*.ts'",
  "fd '*.ts' src",
  "echo hello",
  "uv run python script.py",
  "bash -lc 'rg TODO src'",
  "pwsh -NoProfile -Command 'Select-String -Pattern TODO -Path . -Recurse'",
  'git log --oneline -n 8 && rg -n "foo" src/index.ts && git status --short',
];

const start = performance.now();
let warned = 0;
for (let i = 0; i < ITERATIONS; i += 1) {
  const command = corpus[i % corpus.length] ?? corpus[0] ?? "";
  const action = actionForCommand(command, config);
  if (action?.type === "warn") warned += 1;
}
const elapsedMs = performance.now() - start;
const opsPerSec = Math.round((ITERATIONS / elapsedMs) * 1000);

console.log(
  JSON.stringify(
    {
      iterations: ITERATIONS,
      elapsedMs: Math.round(elapsedMs * 100) / 100,
      opsPerSec,
      warned,
    },
    null,
    2,
  ),
);
