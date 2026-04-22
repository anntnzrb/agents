/**
 * Serialization helpers for tool output.
 */

import type { TodoFrontMatter, TodoRecord } from "./types.ts";
import { formatTodoId, splitTodosByAssignment } from "./utils.ts";

export const serializeTodoForAgent = (todo: TodoRecord): string => {
  const payload = { ...todo, id: formatTodoId(todo.id) };
  return JSON.stringify(payload, null, 2);
};

export const serializeTodoListForAgent = (todos: TodoFrontMatter[]): string => {
  const { assignedTodos, openTodos, closedTodos } = splitTodosByAssignment(todos);
  const mapTodo = (todo: TodoFrontMatter) => ({ ...todo, id: formatTodoId(todo.id) });
  return JSON.stringify(
    {
      assigned: assignedTodos.map(mapTodo),
      open: openTodos.map(mapTodo),
      closed: closedTodos.map(mapTodo),
    },
    null,
    2
  );
};
