/**
 * Type definitions for Claude Code configuration
 */

/**
 * Environment variables configuration
 */
export type EnvironmentConfig = Record<string, string | number>;

export type ProviderModes = {
  glm?: string;
  minimax?: string;
  chutes?: string;
  openrouter?: string;
};

/**
 * MCP server configuration with connection details
 */
export interface McpServer {
  name: string;
  command?: string;
  url?: string;
  env?: EnvironmentConfig;
  disabled?: boolean;
}

/**
 * Map of server names to their configurations
 */
export type McpServersMap = Record<string, Omit<McpServer, "name">>;
