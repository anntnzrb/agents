/**
 * Path helpers for todo storage.
 */

import path from "node:path";
import { TODO_PATH_ENV, TODO_ROOT_DIR } from "../constants.ts";

const safeCwdSegment = (cwd: string): string => {
  return `--${cwd.replace(/^[/\\]/, "").replace(/[/\\:]/g, "-")}--`;
};

const getTodosRootDir = (cwd: string): string => {
  const overridePath = process.env[TODO_PATH_ENV];
  if (overridePath && overridePath.trim()) {
    return path.resolve(cwd, overridePath.trim());
  }
  return TODO_ROOT_DIR;
};

const formatRootLabel = (root: string): string => {
  const home = process.env["HOME"];
  if (home && root.startsWith(home)) {
    return `~${root.slice(home.length)}`;
  }
  return root;
};

export const getTodosDir = (cwd: string): string => {
  const root = getTodosRootDir(cwd);
  const safeSegment = safeCwdSegment(path.resolve(cwd));
  return path.join(root, safeSegment);
};

export const getTodosDirLabel = (cwd: string): string => {
  const root = getTodosRootDir(cwd);
  const safeSegment = safeCwdSegment(path.resolve(cwd));
  return path.join(formatRootLabel(root), safeSegment);
};

export const getTodoPath = (todosDir: string, id: string): string => {
  return path.join(todosDir, `${id}.md`);
};
