/**
 * Constants for the todo extension.
 */

import os from "node:os";
import path from "node:path";

export const TODO_ROOT_DIR = path.join(os.homedir(), ".pi", "todos");
export const TODO_PATH_ENV = "PI_TODO_PATH";
export const TODO_SETTINGS_NAME = "settings.json";
export const TODO_ID_PREFIX = "TODO-";
export const TODO_ID_PATTERN = /^[a-f0-9]{8}$/i;
export const DEFAULT_TODO_SETTINGS = {
  gc: true,
  gcDays: 7,
};
export const LOCK_TTL_MS = 30 * 60 * 1000;
