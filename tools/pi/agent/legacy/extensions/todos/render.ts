/**
 * Rendering helpers for todos.
 */

import type { Theme } from "@mariozechner/pi-coding-agent";
import { keyHint } from "@mariozechner/pi-coding-agent";
import type { TodoFrontMatter, TodoRecord } from "./types.ts";
import {
  formatTodoHeading,
  getTodoStatus,
  isTodoClosed,
  splitTodosByAssignment,
} from "./utils.ts";

export const renderAssignmentSuffix = (
  theme: Theme,
  todo: TodoFrontMatter,
  currentSessionId?: string
): string => {
  if (!todo.assigned_to_session) return "";
  const isCurrent = todo.assigned_to_session === currentSessionId;
  const color = isCurrent ? "success" : "dim";
  const suffix = isCurrent ? ", current" : "";
  return theme.fg(color, ` (assigned: ${todo.assigned_to_session}${suffix})`);
};

export const renderTodoHeading = (
  theme: Theme,
  todo: TodoFrontMatter,
  currentSessionId?: string
): string => {
  const closed = isTodoClosed(getTodoStatus(todo));
  const titleColor = closed ? "dim" : "text";
  const tagText = todo.tags.length ? theme.fg("dim", ` [${todo.tags.join(", ")}]`) : "";
  const assignmentText = renderAssignmentSuffix(theme, todo, currentSessionId);
  return (
    theme.fg("accent", formatTodoId(todo.id)) +
    " " +
    theme.fg(titleColor, getTodoTitle(todo)) +
    tagText +
    assignmentText
  );
};

export const renderTodoList = (
  theme: Theme,
  todos: TodoFrontMatter[],
  expanded: boolean,
  currentSessionId?: string
): string => {
  if (!todos.length) return theme.fg("dim", "No todos");

  const { assignedTodos, openTodos, closedTodos } = splitTodosByAssignment(todos);
  const lines: string[] = [];
  const pushSection = (label: string, sectionTodos: TodoFrontMatter[]) => {
    lines.push(theme.fg("muted", `${label} (${sectionTodos.length})`));
    if (!sectionTodos.length) {
      lines.push(theme.fg("dim", "  none"));
      return;
    }
    const maxItems = expanded ? sectionTodos.length : Math.min(sectionTodos.length, 3);
    for (let i = 0; i < maxItems; i++) {
      lines.push(`  ${renderTodoHeading(theme, sectionTodos[i], currentSessionId)}`);
    }
    if (!expanded && sectionTodos.length > maxItems) {
      lines.push(theme.fg("dim", `  ... ${sectionTodos.length - maxItems} more`));
    }
  };

  const sections: Array<{ label: string; todos: TodoFrontMatter[] }> = [
    { label: "Assigned todos", todos: assignedTodos },
    { label: "Open todos", todos: openTodos },
    { label: "Closed todos", todos: closedTodos },
  ];

  sections.forEach((section, index) => {
    if (index > 0) lines.push("");
    pushSection(section.label, section.todos);
  });

  return lines.join("\n");
};

export const renderTodoDetail = (theme: Theme, todo: TodoRecord, expanded: boolean): string => {
  const summary = renderTodoHeading(theme, todo);
  if (!expanded) return summary;

  const tags = todo.tags.length ? todo.tags.join(", ") : "none";
  const createdAt = todo.created_at || "unknown";
  const bodyText = todo.body?.trim() ? todo.body.trim() : "No details yet.";
  const bodyLines = bodyText.split("\n");

  const lines = [
    summary,
    theme.fg("muted", `Status: ${getTodoStatus(todo)}`),
    theme.fg("muted", `Tags: ${tags}`),
    theme.fg("muted", `Created: ${createdAt}`),
    "",
    theme.fg("muted", "Body:"),
    ...bodyLines.map((line) => theme.fg("text", `  ${line}`)),
  ];

  return lines.join("\n");
};

export const appendExpandHint = (theme: Theme, text: string): string => {
  return `${text}\n${theme.fg("dim", `(${keyHint("app.tools.expand", "to expand")})`)}`;
};

export const formatTodoList = (todos: TodoFrontMatter[]): string => {
  if (!todos.length) return "No todos.";

  const { assignedTodos, openTodos, closedTodos } = splitTodosByAssignment(todos);
  const lines: string[] = [];
  const pushSection = (label: string, sectionTodos: TodoFrontMatter[]) => {
    lines.push(`${label} (${sectionTodos.length}):`);
    if (!sectionTodos.length) {
      lines.push("  none");
      return;
    }
    for (const todo of sectionTodos) {
      lines.push(`  ${formatTodoHeading(todo)}`);
    }
  };

  pushSection("Assigned todos", assignedTodos);
  pushSection("Open todos", openTodos);
  pushSection("Closed todos", closedTodos);
  return lines.join("\n");
};
