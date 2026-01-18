/**
 * Claude Code process spawning
 */

import { safeJsonRead } from "../shared/json.ts";
import type { EnvironmentConfig, McpServer, ProviderModes } from "./types.ts";
import { claudeCmd } from "./config/env.ts";
import { providers, createProviderEnvWithModel } from "./config/providers.ts";
import { paths } from "./config/paths.ts";
import { buildMcpServers } from "./config/mcp.ts";

type ProviderKey = keyof typeof providers;

/**
 * Create environment object with Claude variables and development flags
 * @param modes - Object mapping provider keys to their custom models (if any)
 * @returns Environment object for Claude Code execution
 */
export const setupEnv = (modes: ProviderModes = {}): EnvironmentConfig => {
  const env: EnvironmentConfig = { ...process.env };

  for (const [key, model] of Object.entries(modes)) {
    const provider = key as ProviderKey;
    if (model) {
      const extraConfig: EnvironmentConfig =
        provider === "chutes"
          ? { API_TIMEOUT_MS: "6000000" }
          : provider === "openrouter"
            ? { ANTHROPIC_API_KEY: "" }
            : {};
      Object.assign(env, createProviderEnvWithModel(provider, model, extraConfig));
    } else {
      Object.assign(env, providers[provider].env);
    }
  }

  // Map provider-specific API keys to ANTHROPIC_AUTH_TOKEN
  for (const [key, provider] of Object.entries(providers)) {
    if (modes[key as ProviderKey] !== undefined && process.env[provider.apiKeyEnvVar]) {
      env.ANTHROPIC_AUTH_TOKEN = process.env[provider.apiKeyEnvVar]!;
      break;
    }
  }

  return env;
};

/**
 * Spawn Claude with provided arguments
 * @param args - Command line arguments to pass to Claude Code
 * @param env - Environment configuration
 * @returns Spawned Claude process
 */
export const spawnClaude = async (
  args: string[],
  env: EnvironmentConfig,
): Promise<Subprocess> => {
  const mcpResult = await safeJsonRead<McpServer[]>(paths.mcp);
  const mcpArray = Array.isArray(mcpResult) ? mcpResult : [];
  const mcpServers = buildMcpServers(mcpArray);

  const claudeArgs = [
    ...args,
    ...(Object.keys(mcpServers).length > 0
      ? ["--mcp-config", JSON.stringify({ mcpServers }), "--strict-mcp-config"]
      : []),
  ];

  return Bun.spawn([...claudeCmd, ...claudeArgs], {
    env,
    stdio: ["inherit", "inherit", "inherit"],
  });
};
