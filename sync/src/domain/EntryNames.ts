import { Record, String as Str } from "effect"

export const IGNORED_SYNC_NAMES: Readonly<Record<string, true>> = {
  ".venv": true,
  node_modules: true,
  __pycache__: true,
  ".pytest_cache": true,
  ".ruff_cache": true,
  ".hypothesis": true,
  ".DS_Store": true,
  ".git": true,
}

export const isSafeManagedEntryName = (name: string): boolean =>
  name.length > 0 && name !== "." && name !== ".." && !Str.includes("/")(name) && !Str.includes("\\")(name)

export const isIgnoredSyncEntry = (name: string): boolean =>
  Record.has(IGNORED_SYNC_NAMES, name) || Str.endsWith(".pyc")(name) || Str.endsWith(".pyo")(name)
