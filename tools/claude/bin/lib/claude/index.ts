#!/usr/bin/env bun

/**
 * Claude Code execution and configuration management script
 *
 * This script performs the following:
 * 1. Merges global configurations into the final Claude configuration
 * 2. Executes Claude Code using Bun with proper environment setup
 *
 * The configuration merge allows defining Claude settings and MCP servers
 * in separate claude.json and mcp.json files, which are then merged into the
 * global ~/.claude.json configuration before Claude Code is launched.
 */

import { die } from "../shared/process.ts";
import { mergeConfigs } from "./config/merge.ts";
import { createAndSaveSymlinks, cleanupAgentsSymlinks } from "./symlinks.ts";
import { setupEnv, spawnClaude } from "./spawn.ts";
import {
  validateZaiToken as validateGlmToken,
  validateMiniMaxToken,
  validateChutesToken,
  validateOpenRouterToken,
} from "./config/providers.ts";
import type { ProviderModes } from "./types.ts";

/**
 * Cleanup all resources after Claude session ends
 * @returns Promise that resolves when cleanup is complete
 */
const cleanup = (): Promise<void> =>
  Promise.all([cleanupAgentsSymlinks()]).then(() => {});

const parseProviderFlag = (
  args: string[],
  flag: string,
  validator: () => void,
  modelFlag?: string,
): { isMode: boolean; model?: string } => {
  const index = args.indexOf(flag);
  if (index === -1) return { isMode: false };

  args.splice(index, 1);
  validator();

  if (modelFlag) {
    const modelIndex = args.indexOf(modelFlag);
    if (modelIndex !== -1) {
      const nextArg = args[modelIndex + 1];
      if (nextArg && !nextArg.startsWith("--")) {
        args.splice(modelIndex, 2);
        return { isMode: true, model: nextArg };
      }
    }
  }

  return { isMode: true };
};

/**
 * Main execution flow
 */
const main = async () => {
  const [, , ...args] = process.argv;
  const cwd = process.cwd();

  const { isMode: isGlmMode } = parseProviderFlag(args, "--glm", validateGlmToken);
  const { isMode: isMiniMaxMode } = parseProviderFlag(args, "--m2", validateMiniMaxToken);
  const { isMode: isChutesMode, model: chutesModel } = parseProviderFlag(
    args,
    "--chutes",
    validateChutesToken,
    "--chutes-model",
  );
  const { isMode: isOpenRouterMode, model: openrouterModel } = parseProviderFlag(
    args,
    "--openrouter",
    validateOpenRouterToken,
    "--openrouter-model",
  );

  await mergeConfigs();
  await createAndSaveSymlinks(cwd);
  const modes: ProviderModes = {};
  if (isGlmMode) modes.glm = "";
  if (isMiniMaxMode) modes.minimax = "";
  if (isChutesMode) modes.chutes = chutesModel ?? "";
  if (isOpenRouterMode) modes.openrouter = openrouterModel ?? "";
  const env = setupEnv(modes);
  const proc = await spawnClaude(args, env);
  await proc.exited;
  await cleanup();
  process.exit(0);
};

main().catch(async (err) => {
  try {
    await cleanup();
  } finally {
    die(err instanceof Error ? err : String(err));
  }
});
