import { afterEach, beforeEach, type Mock, spyOn, test } from "bun:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { loadRootEnv, RootEnvReadError, SyncEnv } from "@core/harness.ts";
import { Effect, Result } from "effect";

async function withTempHome<T>(fn: (home: string) => T | Promise<T>): Promise<T> {
  const home = mkdtempSync(join(tmpdir(), "agents-sync-harness-test-"));
  try {
    return await fn(home);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}

let errorSpy: Mock<(...args: unknown[]) => void>;
beforeEach(() => {
  errorSpy = spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => errorSpy.mockRestore());

test("root_env_returns_empty_when_env_file_is_missing", async () => {
  await withTempHome((home) => {
    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    assert.deepEqual(syncEnv.rootEnv, {});
  });
});

test("root_env_parses_dotenv_contents_with_expected_precedence_and_literals", async () => {
  await withTempHome((home) => {
    const agentsHome = join(home, ".config", "agents");
    mkdirSync(agentsHome, { recursive: true });
    writeFileSync(
      join(agentsHome, ".env"),
      [
        "# Shared test env",
        'QUOTED_VAL="secret_value # not a comment"',
        "SINGLE_QUOTED='single'",
        "EMPTY_KEY=",
        'EMPTY_QUOTED=""',
        `VARIABLE_REF=\${UNEXPANDED_VAR}`,
        "DOLLAR_PREFIX=$LITERAL_VAR",
        "NESTED_PREFIX_A=foo",
        "NESTED_PREFIX_B=bar",
        "COMMAND_CODE_API_KEY=",
        "API_KEY=12345",
      ].join("\n"),
      "utf8",
    );

    const syncEnv = SyncEnv.fromHome(home, 1000, { platform: "linux" });
    assert.deepEqual(syncEnv.rootEnv, {
      QUOTED_VAL: "secret_value # not a comment",
      SINGLE_QUOTED: "single",
      VARIABLE_REF: `\${UNEXPANDED_VAR}`,
      DOLLAR_PREFIX: "$LITERAL_VAR",
      NESTED_PREFIX_A: "foo",
      NESTED_PREFIX_B: "bar",
      API_KEY: "12345",
    });
  });
});

test("root_env_throws_when_reading_env_fails_with_non_enoent_error", async () => {
  await withTempHome((home) => {
    const agentsHome = join(home, ".config", "agents");
    mkdirSync(join(agentsHome, ".env"), { recursive: true }); // .env is a directory -> EISDIR on read

    assert.throws(
      () => SyncEnv.fromHome(home, 1000, { platform: "linux" }),
      (error: unknown) => {
        assert(error instanceof Error);
        assert(error.message.includes("failed to read root environment file"));
        assert(error.message.includes(join(agentsHome, ".env")));
        return true;
      },
    );
  });
});

test("load_root_env_effect_returns_tagged_error_when_reading_fails", async () => {
  await withTempHome((home) => {
    const agentsHome = join(home, ".config", "agents");
    const badEnvPath = join(agentsHome, ".env");
    mkdirSync(badEnvPath, { recursive: true });

    const result = Effect.runSync(Effect.result(loadRootEnv(badEnvPath)));
    assert.equal(Result.isFailure(result), true);
    if (Result.isFailure(result)) {
      assert.equal(result.failure instanceof RootEnvReadError, true);
      assert.equal(result.failure._tag, "RootEnvReadError");
      assert.equal(result.failure.path, badEnvPath);
      assert.equal(result.failure.message.includes("failed to read root environment file"), true);
    }
  });
});
