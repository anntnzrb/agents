/**
 * Tool registration for todo operations.
 */

import type {
  ExtensionContext,
  ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  TodoParams,
  type TodoAction,
  type TodoRecord,
  type TodoToolDetails,
} from "./types.js";
import {
  appendTodo,
  claimTodoAssignment,
  createTodo,
  deleteTodo,
  ensureTodoExists,
  generateTodoId,
  getTodoPath,
  getTodosDir,
  listTodos,
  releaseTodoAssignment,
  updateTodo,
} from "./storage/index.js";
import {
  formatTodoId,
  normalizeTodoId,
  splitTodosByAssignment,
  validateTodoId,
} from "./utils.js";
import {
  appendExpandHint,
  renderTodoDetail,
  renderTodoList,
} from "./render.js";
import {
  serializeTodoForAgent,
  serializeTodoListForAgent,
} from "./serialize.js";

/**
 * Create the todo tool definition.
 */
export const createTodoTool = (todosDirLabel: string): ToolDefinition => {
  return {
    name: "todo",
    label: "Todo",
    description:
      `Manage file-based todos in ${todosDirLabel} (list, list-all, get, create, update, append, delete, claim, release). ` +
      "Title is the short summary; body is long-form markdown notes (update replaces, append adds). " +
      "Todo ids are shown as TODO-<hex>; id parameters accept TODO-<hex> or the raw hex filename. " +
      "Claim tasks before working on them to avoid conflicts, and close them when complete.",
    promptSnippet:
      "Manage persisted todos (list/get/create/update/claim/release/delete).",
    promptGuidelines: [
      "Use todo when work needs persisted task tracking across turns or sessions.",
      "Claim todo items before executing work and release or close them when done.",
    ],
    parameters: TodoParams,

    async execute(_toolCallId, params, _onUpdate, ctx: ExtensionContext) {
      const todosDir = getTodosDir(ctx.cwd);
      const action: TodoAction = params.action;

      switch (action) {
        case "list": {
          const todos = await listTodos(todosDir);
          const { assignedTodos, openTodos } = splitTodosByAssignment(todos);
          const listedTodos = [...assignedTodos, ...openTodos];
          const currentSessionId = ctx.sessionManager.getSessionId();
          return {
            content: [
              { type: "text", text: serializeTodoListForAgent(listedTodos) },
            ],
            details: { action: "list", todos: listedTodos, currentSessionId },
          };
        }

        case "list-all": {
          const todos = await listTodos(todosDir);
          const currentSessionId = ctx.sessionManager.getSessionId();
          return {
            content: [{ type: "text", text: serializeTodoListForAgent(todos) }],
            details: { action: "list-all", todos, currentSessionId },
          };
        }

        case "get": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "get", error: "id required" },
            };
          }
          const validated = validateTodoId(params.id);
          if ("error" in validated) {
            return {
              content: [{ type: "text", text: validated.error }],
              details: { action: "get", error: validated.error },
            };
          }
          const normalizedId = validated.id;
          const displayId = formatTodoId(normalizedId);
          const filePath = getTodoPath(todosDir, normalizedId);
          const todo = await ensureTodoExists(filePath, normalizedId);
          if (!todo) {
            return {
              content: [{ type: "text", text: `Todo ${displayId} not found` }],
              details: { action: "get", error: "not found" },
            };
          }
          return {
            content: [{ type: "text", text: serializeTodoForAgent(todo) }],
            details: { action: "get", todo },
          };
        }

        case "create": {
          if (!params.title) {
            return {
              content: [{ type: "text", text: "Error: title required" }],
              details: { action: "create", error: "title required" },
            };
          }
          const id = await generateTodoId(todosDir);
          const todo: TodoRecord = {
            id,
            title: params.title,
            tags: params.tags ?? [],
            status: params.status ?? "open",
            created_at: new Date().toISOString(),
            body: params.body ?? "",
          };

          const result = await createTodo(todosDir, todo, ctx);
          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "create", error: result.error },
            };
          }

          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "create", todo: result as TodoRecord },
          };
        }

        case "update": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "update", error: "id required" },
            };
          }
          const result = await updateTodo(
            todosDir,
            params.id,
            {
              title: params.title,
              status: params.status,
              tags: params.tags,
              body: params.body,
            },
            ctx,
          );

          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "update", error: result.error },
            };
          }

          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "update", todo: result as TodoRecord },
          };
        }

        case "append": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "append", error: "id required" },
            };
          }
          const result = await appendTodo(
            todosDir,
            params.id,
            params.body ?? "",
            ctx,
          );
          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "append", error: result.error },
            };
          }
          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "append", todo: result as TodoRecord },
          };
        }

        case "claim": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "claim", error: "id required" },
            };
          }
          const result = await claimTodoAssignment(
            todosDir,
            params.id,
            ctx,
            Boolean(params.force),
          );
          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "claim", error: result.error },
            };
          }
          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "claim", todo: result as TodoRecord },
          };
        }

        case "release": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "release", error: "id required" },
            };
          }
          const result = await releaseTodoAssignment(
            todosDir,
            params.id,
            ctx,
            Boolean(params.force),
          );
          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "release", error: result.error },
            };
          }
          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "release", todo: result as TodoRecord },
          };
        }

        case "delete": {
          if (!params.id) {
            return {
              content: [{ type: "text", text: "Error: id required" }],
              details: { action: "delete", error: "id required" },
            };
          }

          const validated = validateTodoId(params.id);
          if ("error" in validated) {
            return {
              content: [{ type: "text", text: validated.error }],
              details: { action: "delete", error: validated.error },
            };
          }
          const result = await deleteTodo(todosDir, validated.id, ctx);
          if (typeof result === "object" && "error" in result) {
            return {
              content: [{ type: "text", text: result.error }],
              details: { action: "delete", error: result.error },
            };
          }

          return {
            content: [
              {
                type: "text",
                text: serializeTodoForAgent(result as TodoRecord),
              },
            ],
            details: { action: "delete", todo: result as TodoRecord },
          };
        }
      }
    },

    renderCall(args, theme) {
      const action = typeof args.action === "string" ? args.action : "";
      const id = typeof args.id === "string" ? args.id : "";
      const normalizedId = id ? normalizeTodoId(id) : "";
      const title = typeof args.title === "string" ? args.title : "";
      let text =
        theme.fg("toolTitle", theme.bold("todo ")) + theme.fg("muted", action);
      if (normalizedId) {
        text += " " + theme.fg("accent", formatTodoId(normalizedId));
      }
      if (title) {
        text += " " + theme.fg("dim", `\"${title}\"`);
      }
      return new Text(text, 0, 0);
    },

    renderResult(result, { expanded, isPartial }, theme) {
      const details = result.details as TodoToolDetails | undefined;
      if (isPartial) {
        return new Text(theme.fg("warning", "Processing..."), 0, 0);
      }
      if (!details) {
        const text = result.content[0];
        return new Text(text?.type === "text" ? text.text : "", 0, 0);
      }

      if (details.error) {
        return new Text(theme.fg("error", `Error: ${details.error}`), 0, 0);
      }

      if (details.action === "list" || details.action === "list-all") {
        let text = renderTodoList(
          theme,
          details.todos,
          expanded,
          details.currentSessionId,
        );
        if (!expanded) {
          const { closedTodos } = splitTodosByAssignment(details.todos);
          if (closedTodos.length) {
            text = appendExpandHint(theme, text);
          }
        }
        return new Text(text, 0, 0);
      }

      if (!details.todo) {
        const text = result.content[0];
        return new Text(text?.type === "text" ? text.text : "", 0, 0);
      }

      let text = renderTodoDetail(theme, details.todo, expanded);
      const actionLabel =
        details.action === "create"
          ? "Created"
          : details.action === "update"
            ? "Updated"
            : details.action === "append"
              ? "Appended to"
              : details.action === "delete"
                ? "Deleted"
                : details.action === "claim"
                  ? "Claimed"
                  : details.action === "release"
                    ? "Released"
                    : null;
      if (actionLabel) {
        const lines = text.split("\n");
        lines[0] =
          theme.fg("success", "✓ ") +
          theme.fg("muted", `${actionLabel} `) +
          lines[0];
        text = lines.join("\n");
      }
      if (!expanded) {
        text = appendExpandHint(theme, text);
      }
      return new Text(text, 0, 0);
    },
  };
};
