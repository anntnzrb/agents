/**
 * MCP server configuration builder
 */

import type { McpServer, McpServersMap } from "../types.ts";

/**
 * Build mcpServers object from array of server configurations
 *
 * Transforms user-friendly config format to Claude's expected format:
 * - If has `command`: splits "docker mcp run" → command: "docker", args: ["mcp", "run"], type: "stdio"
 * - If has `url`: passes through as type: "http" server
 *
 * @param mcpArray - Array of MCP server configurations
 * @returns Object with server names as keys and configs as values
 */
export const buildMcpServers = (mcpArray: McpServer[]): McpServersMap =>
  mcpArray
    .filter((server) => !server.disabled)
    .reduce((acc, { name, command, url, env, disabled, ...rest }) => {
      const parts = command?.trim().split(/\s+/).filter(Boolean) || [];
      return {
        ...acc,
        [name]: {
          ...rest,
          ...(parts[0] && {
            type: "stdio",
            command: parts[0],
            args: parts.slice(1),
          }),
          ...(url && { type: "http", url }),
          ...(env && { env }),
        },
      };
    }, {});
