/**
 * Todo extension - file-backed todo manager with tool + TUI.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { createTodoTool } from "./tool.ts";
import {
  ensureTodosDir,
  garbageCollectTodos,
  getTodosDir,
  getTodosDirLabel,
  readTodoSettings,
} from "./storage/index.ts";
import { getTodoArgumentCompletions, runTodosCommand } from "./command.ts";

/**
 * Register the todo extension.
 */
const todosExtension = (pi: ExtensionAPI): void => {
  pi.on("session_start", async (_event, ctx) => {
    const todosDir = getTodosDir(ctx.cwd);
    await ensureTodosDir(todosDir);
    const settings = await readTodoSettings(todosDir);
    await garbageCollectTodos(todosDir, settings);
  });

  const todosDirLabel = getTodosDirLabel(process.cwd());
  pi.registerTool(createTodoTool(todosDirLabel));

  pi.registerCommand("todos", {
    description: "List todos from ~/.pi/todos",
    getArgumentCompletions: (argumentPrefix: string) =>
      getTodoArgumentCompletions(argumentPrefix, process.cwd()),
    handler: async (args, ctx) => {
      await runTodosCommand(ctx, args);
    },
  });
};

export default todosExtension;
