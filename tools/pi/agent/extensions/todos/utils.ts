/**
 * Utility helpers for todos.
 */

import { fuzzyMatch } from "@mariozechner/pi-tui";
import { TODO_ID_PATTERN, TODO_ID_PREFIX } from "./constants.ts";
import type { TodoFrontMatter } from "./types.ts";

export const formatTodoId = (id: string): string => {
  return `${TODO_ID_PREFIX}${id}`;
};

export const normalizeTodoId = (id: string): string => {
  let trimmed = id.trim();
  if (trimmed.startsWith("#")) {
    trimmed = trimmed.slice(1);
  }
  if (trimmed.toUpperCase().startsWith(TODO_ID_PREFIX)) {
    trimmed = trimmed.slice(TODO_ID_PREFIX.length);
  }
  return trimmed;
};

export const validateTodoId = (id: string): { id: string } | { error: string } => {
  const normalized = normalizeTodoId(id);
  if (!normalized || !TODO_ID_PATTERN.test(normalized)) {
    return { error: "Invalid todo id. Expected TODO-<hex>." };
  }
  return { id: normalized.toLowerCase() };
};

export const displayTodoId = (id: string): string => {
  return formatTodoId(normalizeTodoId(id));
};

export const isTodoClosed = (status: string): boolean => {
  return ["closed", "done"].includes(status.toLowerCase());
};

export const clearAssignmentIfClosed = (todo: TodoFrontMatter): void => {
  if (isTodoClosed(getTodoStatus(todo))) {
    todo.assigned_to_session = undefined;
  }
};

export const sortTodos = (todos: TodoFrontMatter[]): TodoFrontMatter[] => {
  return [...todos].sort((a, b) => {
    const aClosed = isTodoClosed(a.status);
    const bClosed = isTodoClosed(b.status);
    if (aClosed !== bClosed) return aClosed ? 1 : -1;
    const aAssigned = !aClosed && Boolean(a.assigned_to_session);
    const bAssigned = !bClosed && Boolean(b.assigned_to_session);
    if (aAssigned !== bAssigned) return aAssigned ? -1 : 1;
    return (a.created_at || "").localeCompare(b.created_at || "");
  });
};

export const buildTodoSearchText = (todo: TodoFrontMatter): string => {
  const tags = todo.tags.join(" ");
  const assignment = todo.assigned_to_session ? `assigned:${todo.assigned_to_session}` : "";
  return `${formatTodoId(todo.id)} ${todo.id} ${todo.title} ${tags} ${todo.status} ${assignment}`.trim();
};

export const filterTodos = (todos: TodoFrontMatter[], query: string): TodoFrontMatter[] => {
  const trimmed = query.trim();
  if (!trimmed) return todos;

  const tokens = trimmed
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);

  if (tokens.length === 0) return todos;

  const matches: Array<{ todo: TodoFrontMatter; score: number }> = [];
  for (const todo of todos) {
    const text = buildTodoSearchText(todo);
    let totalScore = 0;
    let matched = true;
    for (const token of tokens) {
      const result = fuzzyMatch(token, text);
      if (!result.matches) {
        matched = false;
        break;
      }
      totalScore += result.score;
    }
    if (matched) {
      matches.push({ todo, score: totalScore });
    }
  }

  return matches
    .sort((a, b) => {
      const aClosed = isTodoClosed(a.todo.status);
      const bClosed = isTodoClosed(b.todo.status);
      if (aClosed !== bClosed) return aClosed ? 1 : -1;
      const aAssigned = !aClosed && Boolean(a.todo.assigned_to_session);
      const bAssigned = !bClosed && Boolean(b.todo.assigned_to_session);
      if (aAssigned !== bAssigned) return aAssigned ? -1 : 1;
      return a.score - b.score;
    })
    .map((match) => match.todo);
};

export const getTodoTitle = (todo: TodoFrontMatter): string => {
  return todo.title || "(untitled)";
};

export const getTodoStatus = (todo: TodoFrontMatter): string => {
  return todo.status || "open";
};

export const formatAssignmentSuffix = (todo: TodoFrontMatter): string => {
  return todo.assigned_to_session ? ` (assigned: ${todo.assigned_to_session})` : "";
};

export const formatTodoHeading = (todo: TodoFrontMatter): string => {
  const tagText = todo.tags.length ? ` [${todo.tags.join(", ")}]` : "";
  return `${formatTodoId(todo.id)} ${getTodoTitle(todo)}${tagText}${formatAssignmentSuffix(todo)}`;
};

export const buildRefinePrompt = (todoId: string, title: string): string => {
  return (
    `let's refine task ${formatTodoId(todoId)} "${title}": ` +
    "Ask me for the missing details needed to refine the todo together. Do not rewrite the todo yet and do not make assumptions. " +
    "Ask clear, concrete questions and wait for my answers before drafting any structured description.\n\n"
  );
};

export const splitTodosByAssignment = (
  todos: TodoFrontMatter[]
): {
  assignedTodos: TodoFrontMatter[];
  openTodos: TodoFrontMatter[];
  closedTodos: TodoFrontMatter[];
} => {
  const assignedTodos: TodoFrontMatter[] = [];
  const openTodos: TodoFrontMatter[] = [];
  const closedTodos: TodoFrontMatter[] = [];
  for (const todo of todos) {
    if (isTodoClosed(getTodoStatus(todo))) {
      closedTodos.push(todo);
      continue;
    }
    if (todo.assigned_to_session) {
      assignedTodos.push(todo);
    } else {
      openTodos.push(todo);
    }
  }
  return { assignedTodos, openTodos, closedTodos };
};
