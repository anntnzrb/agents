/**
 * Path helpers for todo storage.
 */

import path from "node:path";
import { TODO_PATH_ENV, TODO_ROOT_DIR } from "../constants.ts";

function safeCwdSegment(cwd: string): string {
  return `--${cwd.replace(/^[/\\]/, "").replace(/[/\\:]/g, "-")}--`;
}

function getTodosRootDir(cwd: string): string {
  const overridePath = process.env[TODO_PATH_ENV];
  if (overridePath && overridePath.trim()) {
    return path.resolve(cwd, overridePath.trim());
  }
  return TODO_ROOT_DIR;
}

function formatRootLabel(root: string): string {
  const home = process.env["HOME"];
  if (home && root.startsWith(home)) {
    return `~${root.slice(home.length)}`;
  }
  return root;
}

export function getTodosDir(cwd: string): string {
  const root = getTodosRootDir(cwd);
  const safeSegment = safeCwdSegment(path.resolve(cwd));
  return path.join(root, safeSegment);
}

export function getTodosDirLabel(cwd: string): string {
  const root = getTodosRootDir(cwd);
  const safeSegment = safeCwdSegment(path.resolve(cwd));
  return path.join(formatRootLabel(root), safeSegment);
}

export function getTodoPath(todosDir: string, id: string): string {
  return path.join(todosDir, `${id}.md`);
}
