/**
 * AGENTS.md symlink management
 */

import { existsSync } from "fs";
import { dirname, join } from "path";
import { safeDelete } from "../shared/fs.ts";
import { safeJsonRead, safeJsonWrite } from "../shared/json.ts";

const MANIFEST_PATH = `/tmp/claude-symlinks-${process.pid}-${Date.now()}.json`;

/**
 * Create CLAUDE.md symlinks next to AGENTS.md files and save manifest
 * @param cwd - Current working directory to search from
 * @returns Promise that resolves when symlinks are created and saved
 */
export const createAndSaveSymlinks = async (cwd: string): Promise<void> => {
  const stdout = await Bun.$`find ${cwd} -type f -name "AGENTS.md" 2>/dev/null`
    .quiet()
    .then(({ stdout }) => stdout.toString())
    .catch(() => "");

  const agentsFiles = stdout.trim().split("\n").filter(Boolean);
  const created: string[] = [];

  for (const agentsMdPath of agentsFiles) {
    const claudeMdPath = join(dirname(agentsMdPath), "CLAUDE.md");
    if (existsSync(claudeMdPath)) continue;

    await Bun.$`ln -s AGENTS.md ${claudeMdPath}`
      .quiet()
      .then(() => created.push(claudeMdPath))
      .catch(() => console.warn(`Failed to symlink: ${claudeMdPath}`));
  }

  await safeJsonWrite(MANIFEST_PATH, created);
};

/**
 * Cleanup symlinks created from AGENTS.md files
 * @returns Promise that resolves when all symlinks are removed
 */
export const cleanupAgentsSymlinks = async (): Promise<void> => {
  if (!existsSync(MANIFEST_PATH)) return;

  const result = await safeJsonRead<string[]>(MANIFEST_PATH);
  const symlinks = Array.isArray(result) ? result : [];
  await Promise.all(symlinks.map(safeDelete));
  await safeDelete(MANIFEST_PATH);
};
