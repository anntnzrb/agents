/**
 * Git-aware path display utilities
 */

import { homedir } from "os";
import { basename } from "path";
import type { WorkspaceInfo } from "../types.ts";

/**
 * Get git-aware display path for current directory
 *
 * Attempts to show path relative to git repository root, falling back to
 * home-relative path or truncated path for non-git directories.
 *
 * @param workspace - Workspace info with current_dir
 * @param cwd - Current working directory fallback
 * @returns Formatted display path (e.g., "repo/subdir", "~/path", or "parent/dir")
 */
export const getDisplayPath = async (
  workspace?: WorkspaceInfo,
  cwd?: string,
): Promise<string> => {
  const path = workspace?.current_dir || cwd || process.cwd();
  if (!path) return "";

  // Try git-relative path first
  const gitPath =
    await Bun.$`cd ${path} && git rev-parse --show-toplevel 2>/dev/null`
      .quiet()
      .then(({ stdout }) => {
        const repoRoot = stdout.trim();
        if (repoRoot) {
          const relPath = path.startsWith(repoRoot)
            ? path.slice(repoRoot.length).replace(/^\//, "") || "."
            : ".";
          return relPath === "."
            ? basename(repoRoot)
            : `${basename(repoRoot)}/${relPath}`;
        }
        return null;
      })
      .catch(() => null);

  return (
    gitPath ||
    (path.startsWith(homedir())
      ? path.replace(homedir(), "") || "~"
      : path.split("/").slice(-2).join("/"))
  );
};
