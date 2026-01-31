/**
 * /todos command UI.
 */

import { copyToClipboard, type ExtensionContext } from "@mariozechner/pi-coding-agent";
import type { TUI } from "@mariozechner/pi-tui";
import path from "node:path";
import {
  TodoActionMenuComponent,
  TodoDeleteConfirmComponent,
  TodoDetailOverlayComponent,
  TodoSelectorComponent,
} from "./components.ts";
import {
  deleteTodo,
  ensureTodoExists,
  getTodoPath,
  getTodosDir,
  listTodos,
  listTodosSync,
  releaseTodoAssignment,
  updateTodoStatus,
} from "./storage/index.ts";
import type { TodoFrontMatter, TodoMenuAction, TodoRecord } from "./types.ts";
import { buildRefinePrompt, filterTodos, formatTodoId } from "./utils.ts";
import { formatTodoList } from "./render.ts";

/**
 * Build command argument completions.
 */
export function getTodoArgumentCompletions(
  argumentPrefix: string,
  cwd: string
): Array<{ value: string; label: string; description?: string }> | null {
  const todos = listTodosSync(getTodosDir(cwd));
  if (!todos.length) return null;
  const matches = filterTodos(todos, argumentPrefix);
  if (!matches.length) return null;
  return matches.map((todo) => {
    const title = todo.title || "(untitled)";
    const tags = todo.tags.length ? ` • ${todo.tags.join(", ")}` : "";
    return {
      value: title,
      label: `${formatTodoId(todo.id)} ${title}`,
      description: `${todo.status || "open"}${tags}`,
    };
  });
}

/**
 * Handle the /todos command.
 */
export async function runTodosCommand(
  ctx: ExtensionContext,
  args?: string | null
): Promise<void> {
  const todosDir = getTodosDir(ctx.cwd);
  const todos = await listTodos(todosDir);
  const currentSessionId = ctx.sessionManager.getSessionId();
  const searchTerm = (args ?? "").trim();

  if (!ctx.hasUI) {
    const text = formatTodoList(todos);
    console.log(text);
    return;
  }

  let nextPrompt: string | null = null;
  let rootTui: TUI | null = null;
  await ctx.ui.custom<void>((tui, theme, _kb, done) => {
    rootTui = tui;
    let selector: TodoSelectorComponent | null = null;
    let actionMenu: TodoActionMenuComponent | null = null;
    let deleteConfirm: TodoDeleteConfirmComponent | null = null;
    let activeComponent:
      | {
          render: (width: number) => string[];
          invalidate: () => void;
          handleInput?: (data: string) => void;
          focused?: boolean;
        }
      | null = null;
    let wrapperFocused = false;

    const setActiveComponent = (
      component:
        | {
            render: (width: number) => string[];
            invalidate: () => void;
            handleInput?: (data: string) => void;
            focused?: boolean;
          }
        | null
    ) => {
      if (activeComponent && "focused" in activeComponent) {
        activeComponent.focused = false;
      }
      activeComponent = component;
      if (activeComponent && "focused" in activeComponent) {
        activeComponent.focused = wrapperFocused;
      }
      tui.requestRender();
    };

    const copyTodoPathToClipboard = (todoId: string) => {
      const filePath = getTodoPath(todosDir, todoId);
      const absolutePath = path.resolve(filePath);
      try {
        copyToClipboard(absolutePath);
        ctx.ui.notify(`Copied ${absolutePath} to clipboard`, "info");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ctx.ui.notify(message, "error");
      }
    };

    const copyTodoTextToClipboard = (record: TodoRecord) => {
      const title = record.title || "(untitled)";
      const body = record.body?.trim() || "";
      const text = body ? `# ${title}\n\n${body}` : `# ${title}`;
      try {
        copyToClipboard(text);
        ctx.ui.notify("Copied todo text to clipboard", "info");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ctx.ui.notify(message, "error");
      }
    };

    const resolveTodoRecord = async (todo: TodoFrontMatter): Promise<TodoRecord | null> => {
      const filePath = getTodoPath(todosDir, todo.id);
      const record = await ensureTodoExists(filePath, todo.id);
      if (!record) {
        ctx.ui.notify(`Todo ${formatTodoId(todo.id)} not found`, "error");
        return null;
      }
      return record;
    };

    const openTodoOverlay = async (record: TodoRecord): Promise<"back" | "work"> => {
      const action = await ctx.ui.custom<"back" | "work">(
        (overlayTui, overlayTheme, _overlayKb, overlayDone) =>
          new TodoDetailOverlayComponent(overlayTui, overlayTheme, record, overlayDone),
        {
          overlay: true,
          overlayOptions: { width: "80%", maxHeight: "80%", anchor: "center" },
        }
      );

      return action ?? "back";
    };

    const applyTodoAction = async (
      record: TodoRecord,
      action: TodoMenuAction
    ): Promise<"stay" | "exit"> => {
      if (action === "refine") {
        const title = record.title || "(untitled)";
        nextPrompt = buildRefinePrompt(record.id, title);
        done();
        return "exit";
      }
      if (action === "work") {
        const title = record.title || "(untitled)";
        nextPrompt = `work on todo ${formatTodoId(record.id)} "${title}"`;
        done();
        return "exit";
      }
      if (action === "view") {
        return "stay";
      }
      if (action === "copyPath") {
        copyTodoPathToClipboard(record.id);
        return "stay";
      }
      if (action === "copyText") {
        copyTodoTextToClipboard(record);
        return "stay";
      }

      if (action === "release") {
        const result = await releaseTodoAssignment(todosDir, record.id, ctx, true);
        if ("error" in result) {
          ctx.ui.notify(result.error, "error");
          return "stay";
        }
        const updatedTodos = await listTodos(todosDir);
        selector?.setTodos(updatedTodos);
        ctx.ui.notify(`Released todo ${formatTodoId(record.id)}`, "info");
        return "stay";
      }

      if (action === "delete") {
        const result = await deleteTodo(todosDir, record.id, ctx);
        if ("error" in result) {
          ctx.ui.notify(result.error, "error");
          return "stay";
        }
        const updatedTodos = await listTodos(todosDir);
        selector?.setTodos(updatedTodos);
        ctx.ui.notify(`Deleted todo ${formatTodoId(record.id)}`, "info");
        return "stay";
      }

      const nextStatus = action === "close" ? "closed" : "open";
      const result = await updateTodoStatus(todosDir, record.id, nextStatus, ctx);
      if ("error" in result) {
        ctx.ui.notify(result.error, "error");
        return "stay";
      }

      const updatedTodos = await listTodos(todosDir);
      selector?.setTodos(updatedTodos);
      ctx.ui.notify(`${action === "close" ? "Closed" : "Reopened"} todo ${formatTodoId(record.id)}`, "info");
      return "stay";
    };

    const handleActionSelection = async (record: TodoRecord, action: TodoMenuAction) => {
      if (action === "view") {
        const overlayAction = await openTodoOverlay(record);
        if (overlayAction === "work") {
          await applyTodoAction(record, "work");
          return;
        }
        if (actionMenu) {
          setActiveComponent(actionMenu);
        }
        return;
      }

      if (action === "delete") {
        const message = `Delete todo ${formatTodoId(record.id)}? This cannot be undone.`;
        deleteConfirm = new TodoDeleteConfirmComponent(theme, message, (confirmed) => {
          if (!confirmed) {
            setActiveComponent(actionMenu);
            return;
          }
          void (async () => {
            await applyTodoAction(record, "delete");
            setActiveComponent(selector);
          })();
        });
        setActiveComponent(deleteConfirm);
        return;
      }

      const result = await applyTodoAction(record, action);
      if (result === "stay") {
        setActiveComponent(selector);
      }
    };

    const showActionMenu = async (todo: TodoFrontMatter | TodoRecord) => {
      const record = "body" in todo ? todo : await resolveTodoRecord(todo);
      if (!record) return;
      actionMenu = new TodoActionMenuComponent(
        theme,
        record,
        (action) => {
          void handleActionSelection(record, action);
        },
        () => {
          setActiveComponent(selector);
        }
      );
      setActiveComponent(actionMenu);
    };

    const handleSelect = async (todo: TodoFrontMatter) => {
      await showActionMenu(todo);
    };

    selector = new TodoSelectorComponent(
      tui,
      theme,
      todos,
      (todo) => {
        void handleSelect(todo);
      },
      () => done(),
      searchTerm || undefined,
      currentSessionId,
      (todo, action) => {
        const title = todo.title || "(untitled)";
        nextPrompt =
          action === "refine"
            ? buildRefinePrompt(todo.id, title)
            : `work on todo ${formatTodoId(todo.id)} "${title}"`;
        done();
      }
    );

    setActiveComponent(selector);

    const rootComponent = {
      get focused() {
        return wrapperFocused;
      },
      set focused(value: boolean) {
        wrapperFocused = value;
        if (activeComponent && "focused" in activeComponent) {
          activeComponent.focused = value;
        }
      },
      render(width: number) {
        return activeComponent ? activeComponent.render(width) : [];
      },
      invalidate() {
        activeComponent?.invalidate();
      },
      handleInput(data: string) {
        activeComponent?.handleInput?.(data);
      },
    };

    return rootComponent;
  });

  if (nextPrompt) {
    ctx.ui.setEditorText(nextPrompt);
    rootTui?.requestRender();
  }
}
