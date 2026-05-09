/**
 * CRUD operations for todos.
 */

import crypto from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import fs from "node:fs/promises";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { TodoFrontMatter, TodoRecord } from "../types.ts";
import {
  clearAssignmentIfClosed,
  displayTodoId,
  isTodoClosed,
  sortTodos,
  validateTodoId,
} from "../utils.ts";
import { parseFrontMatter, parseTodoContent, serializeTodo, splitFrontMatter } from "./front-matter.ts";
import { withTodoLock } from "./locks.ts";
import { getTodoPath } from "./paths.ts";

export const ensureTodosDir = async (todosDir: string): Promise<void> => {
  await fs.mkdir(todosDir, { recursive: true });
};

const readTodoFile = async (filePath: string, idFallback: string): Promise<TodoRecord> => {
  const content = await fs.readFile(filePath, "utf8");
  return parseTodoContent(content, idFallback);
};

const writeTodoFile = async (filePath: string, todo: TodoRecord): Promise<void> => {
  await fs.writeFile(filePath, serializeTodo(todo), "utf8");
};

export const generateTodoId = async (todosDir: string): Promise<string> => {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const id = crypto.randomBytes(4).toString("hex");
    const todoPath = getTodoPath(todosDir, id);
    if (!existsSync(todoPath)) return id;
  }
  throw new Error("Failed to generate unique todo id");
};

export const listTodos = async (todosDir: string): Promise<TodoFrontMatter[]> => {
  let entries: string[] = [];
  try {
    entries = await fs.readdir(todosDir);
  } catch {
    return [];
  }

  const todos: TodoFrontMatter[] = [];
  for (const entry of entries) {
    if (!entry.endsWith(".md")) continue;
    const id = entry.slice(0, -3);
    const filePath = getTodoPath(todosDir, id);
    try {
      const content = await fs.readFile(filePath, "utf8");
      const { frontMatter } = splitFrontMatter(content);
      const parsed = parseFrontMatter(frontMatter, id);
      todos.push({
        id,
        title: parsed.title,
        tags: parsed.tags ?? [],
        status: parsed.status,
        created_at: parsed.created_at,
        assigned_to_session: parsed.assigned_to_session,
      });
    } catch {
      // ignore unreadable todo
    }
  }

  return sortTodos(todos);
};

export const listTodosSync = (todosDir: string): TodoFrontMatter[] => {
  let entries: string[] = [];
  try {
    entries = readdirSync(todosDir);
  } catch {
    return [];
  }

  const todos: TodoFrontMatter[] = [];
  for (const entry of entries) {
    if (!entry.endsWith(".md")) continue;
    const id = entry.slice(0, -3);
    const filePath = getTodoPath(todosDir, id);
    try {
      const content = readFileSync(filePath, "utf8");
      const { frontMatter } = splitFrontMatter(content);
      const parsed = parseFrontMatter(frontMatter, id);
      todos.push({
        id,
        title: parsed.title,
        tags: parsed.tags ?? [],
        status: parsed.status,
        created_at: parsed.created_at,
        assigned_to_session: parsed.assigned_to_session,
      });
    } catch {
      // ignore
    }
  }

  return sortTodos(todos);
};

export const ensureTodoExists = async (
  filePath: string,
  id: string
): Promise<TodoRecord | null> => {
  if (!existsSync(filePath)) return null;
  return readTodoFile(filePath, id);
};

export const appendTodoBody = async (
  filePath: string,
  todo: TodoRecord,
  text: string
): Promise<TodoRecord> => {
  const spacer = todo.body.trim().length ? "\n\n" : "";
  todo.body = `${todo.body.replace(/\s+$/, "")}${spacer}${text.trim()}\n`;
  await writeTodoFile(filePath, todo);
  return todo;
};

export const createTodo = async (
  todosDir: string,
  todo: TodoRecord,
  ctx: ExtensionContext
): Promise<TodoRecord | { error: string }> => {
  await ensureTodosDir(todosDir);
  if (!todo.created_at) {
    todo.created_at = new Date().toISOString();
  }
  const filePath = getTodoPath(todosDir, todo.id);
  const result = await withTodoLock(todosDir, todo.id, ctx, async () => {
    await writeTodoFile(filePath, todo);
    return todo;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const updateTodo = async (
  todosDir: string,
  id: string,
  updates: Partial<Pick<TodoRecord, "title" | "status" | "tags" | "body">>,
  ctx: ExtensionContext
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }

  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;

    existing.id = normalizedId;
    if (updates.title !== undefined) existing.title = updates.title;
    if (updates.status !== undefined) existing.status = updates.status;
    if (updates.tags !== undefined) existing.tags = updates.tags;
    if (updates.body !== undefined) existing.body = updates.body;
    if (!existing.created_at) existing.created_at = new Date().toISOString();
    clearAssignmentIfClosed(existing);

    await writeTodoFile(filePath, existing);
    return existing;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const appendTodo = async (
  todosDir: string,
  id: string,
  text: string,
  ctx: ExtensionContext
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }

  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;
    if (!text.trim()) return existing;
    return appendTodoBody(filePath, existing, text);
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const updateTodoStatus = async (
  todosDir: string,
  id: string,
  status: string,
  ctx: ExtensionContext
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }

  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;
    existing.status = status;
    clearAssignmentIfClosed(existing);
    await writeTodoFile(filePath, existing);
    return existing;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const claimTodoAssignment = async (
  todosDir: string,
  id: string,
  ctx: ExtensionContext,
  force = false
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }
  const sessionId = ctx.sessionManager.getSessionId();
  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;
    if (isTodoClosed(existing.status)) {
      return { error: `Todo ${displayTodoId(id)} is closed` } as const;
    }
    const assigned = existing.assigned_to_session;
    if (assigned && assigned !== sessionId && !force) {
      return {
        error: `Todo ${displayTodoId(id)} is already assigned to session ${assigned}. Use force to override.`,
      } as const;
    }
    if (assigned !== sessionId) {
      existing.assigned_to_session = sessionId;
      await writeTodoFile(filePath, existing);
    }
    return existing;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const releaseTodoAssignment = async (
  todosDir: string,
  id: string,
  ctx: ExtensionContext,
  force = false
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }
  const sessionId = ctx.sessionManager.getSessionId();
  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;
    const assigned = existing.assigned_to_session;
    if (!assigned) {
      return existing;
    }
    if (assigned !== sessionId && !force) {
      return {
        error: `Todo ${displayTodoId(id)} is assigned to session ${assigned}. Use force to release.`,
      } as const;
    }
    existing.assigned_to_session = undefined;
    await writeTodoFile(filePath, existing);
    return existing;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};

export const deleteTodo = async (
  todosDir: string,
  id: string,
  ctx: ExtensionContext
): Promise<TodoRecord | { error: string }> => {
  const validated = validateTodoId(id);
  if ("error" in validated) {
    return { error: validated.error };
  }
  const normalizedId = validated.id;
  const filePath = getTodoPath(todosDir, normalizedId);
  if (!existsSync(filePath)) {
    return { error: `Todo ${displayTodoId(id)} not found` };
  }

  const result = await withTodoLock(todosDir, normalizedId, ctx, async () => {
    const existing = await ensureTodoExists(filePath, normalizedId);
    if (!existing) return { error: `Todo ${displayTodoId(id)} not found` } as const;
    await fs.unlink(filePath);
    return existing;
  });

  if (typeof result === "object" && "error" in result) {
    return { error: result.error };
  }

  return result;
};
