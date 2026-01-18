/**
 * File system paths for Claude configuration files
 */

import { homedir } from "os";
import { join } from "path";

/**
 * Claude home directory path
 * @readonly
 */
export const CLAUDE_HOME = join(homedir(), ".claude");

/**
 * File system paths for Claude configuration files
 * @readonly
 */
export const paths = {
  /** Global Claude configuration file path */
  claude: join(CLAUDE_HOME, "claude.json"),
  /** Global MCP servers configuration file path */
  mcp: join(CLAUDE_HOME, "mcp.json"),
  /** Final merged global configuration file path */
  global: join(homedir(), ".claude.json"),
} as const;
