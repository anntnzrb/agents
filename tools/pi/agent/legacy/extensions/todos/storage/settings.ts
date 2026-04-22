/**
 * Settings + GC helpers for todos.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { DEFAULT_TODO_SETTINGS, TODO_SETTINGS_NAME } from "../constants.ts";
import type { TodoSettings } from "../types.ts";
import { isTodoClosed } from "../utils.ts";
import { parseFrontMatter, splitFrontMatter } from "./front-matter.ts";

const getTodoSettingsPath = (todosDir: string): string => {
  return path.join(todosDir, TODO_SETTINGS_NAME);
};

const normalizeTodoSettings = (raw: Partial<TodoSettings>): TodoSettings => {
  const gc = raw.gc ?? DEFAULT_TODO_SETTINGS.gc;
  const gcDays = Number.isFinite(raw.gcDays) ? raw.gcDays : DEFAULT_TODO_SETTINGS.gcDays;
  return {
    gc: Boolean(gc),
    gcDays: Math.max(0, Math.floor(gcDays)),
  };
};

export const readTodoSettings = async (todosDir: string): Promise<TodoSettings> => {
  const settingsPath = getTodoSettingsPath(todosDir);
  let data: Partial<TodoSettings> = {};

  try {
    const raw = await fs.readFile(settingsPath, "utf8");
    data = JSON.parse(raw) as Partial<TodoSettings>;
  } catch {
    data = {};
  }

  return normalizeTodoSettings(data);
};

export const garbageCollectTodos = async (
  todosDir: string,
  settings: TodoSettings
): Promise<void> => {
  if (!settings.gc) return;

  let entries: string[] = [];
  try {
    entries = await fs.readdir(todosDir);
  } catch {
    return;
  }

  const cutoff = Date.now() - settings.gcDays * 24 * 60 * 60 * 1000;
  await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".md"))
      .map(async (entry) => {
        const id = entry.slice(0, -3);
        const filePath = path.join(todosDir, entry);
        try {
          const content = await fs.readFile(filePath, "utf8");
          const { frontMatter } = splitFrontMatter(content);
          const parsed = parseFrontMatter(frontMatter, id);
          if (!isTodoClosed(parsed.status)) return;
          const createdAt = Date.parse(parsed.created_at);
          if (!Number.isFinite(createdAt)) return;
          if (createdAt < cutoff) {
            await fs.unlink(filePath);
          }
        } catch {
          // ignore unreadable todo
        }
      })
  );
};
