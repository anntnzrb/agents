import {
  mkdir,
  readFile,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { withFileMutationQueue } from "@earendil-works/pi-coding-agent";

const BEGIN_PATCH = "*** Begin Patch";
const END_PATCH = "*** End Patch";
const ADD_FILE = "*** Add File: ";
const DELETE_FILE = "*** Delete File: ";
const UPDATE_FILE = "*** Update File: ";
const MOVE_TO = "*** Move to: ";
const END_OF_FILE = "*** End of File";

type PatchOperation =
  | { readonly type: "add"; readonly path: string; readonly content: string }
  | { readonly type: "delete"; readonly path: string }
  | {
      readonly type: "update";
      readonly path: string;
      readonly movePath?: string;
      readonly chunks: readonly UpdateChunk[];
    };

interface UpdateChunk {
  readonly context?: string;
  readonly oldLines: string[];
  readonly newLines: string[];
  readonly contextLineIndices: Array<readonly [number, number]>;
  endOfFile: boolean;
}

interface Replacement {
  readonly index: number;
  readonly oldLength: number;
  readonly newLines: readonly string[];
}

interface AffectedPaths {
  readonly added: string[];
  readonly modified: string[];
  readonly deleted: string[];
}

const patchError = (message: string, line?: number): Error =>
  new Error(line === undefined ? `Invalid patch: ${message}` : `Invalid patch at line ${line}: ${message}`);

const isFileHeader = (line: string): boolean =>
  line.startsWith(ADD_FILE) ||
  line.startsWith(DELETE_FILE) ||
  line.startsWith(UPDATE_FILE);

const parsePath = (line: string, marker: string, lineNumber: number): string => {
  const path = line.slice(marker.length).trim();
  if (!path) throw patchError("file path cannot be empty", lineNumber);
  return path;
};

const stripHeredoc = (text: string): string => {
  const lines = text.trim().replaceAll("\r\n", "\n").split("\n");
  if (
    lines.length >= 4 &&
    ["<<EOF", "<<'EOF'", '<<"EOF"'].includes(lines[0] ?? "") &&
    lines.at(-1)?.trim() === "EOF"
  ) {
    return lines.slice(1, -1).join("\n");
  }
  return lines.join("\n");
};

const newChunk = (context?: string): UpdateChunk => ({
  ...(context === undefined ? {} : { context }),
  oldLines: [],
  newLines: [],
  contextLineIndices: [],
  endOfFile: false,
});

const chunkIsEmpty = (chunk: UpdateChunk): boolean =>
  chunk.oldLines.length === 0 && chunk.newLines.length === 0;

const parseUpdate = (
  lines: readonly string[],
  start: number,
  path: string,
): { readonly operation: PatchOperation; readonly next: number } => {
  let index = start;
  let movePath: string | undefined;
  if (lines[index]?.startsWith(MOVE_TO)) {
    movePath = parsePath(lines[index] ?? "", MOVE_TO, index + 1);
    index += 1;
  }

  const chunks: UpdateChunk[] = [];
  let current: UpdateChunk | undefined;
  while (index < lines.length && !isFileHeader(lines[index] ?? "")) {
    const line = lines[index] ?? "";
    const lineNumber = index + 1;

    if (line === END_OF_FILE) {
      if (!current || chunkIsEmpty(current)) {
        throw patchError("update hunk does not contain any lines", lineNumber);
      }
      current.endOfFile = true;
      index += 1;
      while (lines[index] === "") index += 1;
      continue;
    }

    if (line === "@@" || line.startsWith("@@ ")) {
      if (current && chunkIsEmpty(current)) {
        throw patchError("update hunk does not contain any lines", lineNumber);
      }
      current = newChunk(line === "@@" ? undefined : line.slice(3));
      chunks.push(current);
      index += 1;
      continue;
    }

    if (!current) {
      current = newChunk();
      chunks.push(current);
    }

    if (line === "") {
      current.contextLineIndices.push([
        current.oldLines.length,
        current.newLines.length,
      ]);
      current.oldLines.push("");
      current.newLines.push("");
    } else if (line.startsWith(" ")) {
      current.contextLineIndices.push([
        current.oldLines.length,
        current.newLines.length,
      ]);
      current.oldLines.push(line.slice(1));
      current.newLines.push(line.slice(1));
    } else if (line.startsWith("+")) {
      current.newLines.push(line.slice(1));
    } else if (line.startsWith("-")) {
      current.oldLines.push(line.slice(1));
    } else {
      throw patchError(
        `unexpected update line '${line}'; expected '@@', ' ', '+', or '-'`,
        lineNumber,
      );
    }
    index += 1;
  }

  if (chunks.length === 0 || chunks.some(chunkIsEmpty)) {
    throw patchError(`update hunk for '${path}' is empty`, start);
  }

  return {
    operation: {
      type: "update",
      path,
      ...(movePath === undefined ? {} : { movePath }),
      chunks,
    },
    next: index,
  };
};

export const parsePatch = (patchText: string): readonly PatchOperation[] => {
  const lines = stripHeredoc(patchText).trim().split("\n");
  if (lines[0]?.trim() !== BEGIN_PATCH) {
    throw patchError(`the first line must be '${BEGIN_PATCH}'`);
  }
  if (lines.at(-1)?.trim() !== END_PATCH) {
    throw patchError(`the last line must be '${END_PATCH}'`);
  }

  const operations: PatchOperation[] = [];
  let index = 1;
  const end = lines.length - 1;
  while (index < end) {
    const line = lines[index]?.trim() ?? "";
    if (!line) {
      index += 1;
      continue;
    }

    if (line.startsWith(ADD_FILE)) {
      const path = parsePath(line, ADD_FILE, index + 1);
      const content: string[] = [];
      index += 1;
      while (index < end && lines[index]?.startsWith("+")) {
        content.push((lines[index] ?? "").slice(1));
        index += 1;
      }
      if (content.length === 0) {
        throw patchError(`add hunk for '${path}' has no content`, index + 1);
      }
      operations.push({ type: "add", path, content: `${content.join("\n")}\n` });
      continue;
    }

    if (line.startsWith(DELETE_FILE)) {
      operations.push({
        type: "delete",
        path: parsePath(line, DELETE_FILE, index + 1),
      });
      index += 1;
      continue;
    }

    if (line.startsWith(UPDATE_FILE)) {
      const path = parsePath(line, UPDATE_FILE, index + 1);
      const parsed = parseUpdate(lines.slice(0, end), index + 1, path);
      operations.push(parsed.operation);
      index = parsed.next;
      continue;
    }

    throw patchError(`'${line.trim()}' is not a valid file operation`, index + 1);
  }

  return operations;
};

const normalizeUnicode = (line: string): string =>
  line
    .trim()
    .replace(/[‐‑‒–—―−]/gu, "-")
    .replace(/[‘’‚‛]/gu, "'")
    .replace(/[“”„‟]/gu, '"')
    .replace(/[  -   　]/gu, " ");

const findSequence = (
  lines: readonly string[],
  pattern: readonly string[],
  start: number,
  endOfFile: boolean,
): number | undefined => {
  if (pattern.length === 0) return start;
  if (pattern.length > lines.length) return undefined;
  const last = lines.length - pattern.length;
  const searchStart = endOfFile ? last : start;
  if (searchStart > last) return undefined;

  const comparisons = [
    (left: string, right: string) => left === right,
    (left: string, right: string) => left.trimEnd() === right.trimEnd(),
    (left: string, right: string) => left.trim() === right.trim(),
    (left: string, right: string) => normalizeUnicode(left) === normalizeUnicode(right),
  ];
  for (const equal of comparisons) {
    for (let index = searchStart; index <= last; index += 1) {
      if (pattern.every((line, offset) => equal(lines[index + offset] ?? "", line))) {
        return index;
      }
    }
  }
  return undefined;
};

const splitFile = (contents: string): {
  readonly bom: string;
  readonly lineEnding: string;
  readonly lines: string[];
} => {
  const bom = contents.startsWith("\uFEFF") ? "\uFEFF" : "";
  const body = bom ? contents.slice(1) : contents;
  const lineEnding = body.includes("\r\n") ? "\r\n" : body.includes("\r") ? "\r" : "\n";
  const lines = body.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  return { bom, lineEnding, lines };
};

const deriveUpdatedContents = (
  contents: string,
  path: string,
  chunks: readonly UpdateChunk[],
): string => {
  const source = splitFile(contents);
  const replacements: Replacement[] = [];
  let lineIndex = 0;

  for (const chunk of chunks) {
    if (chunk.context !== undefined) {
      const contextIndex = findSequence(source.lines, [chunk.context], lineIndex, false);
      if (contextIndex === undefined) {
        throw new Error(`Failed to find context '${chunk.context}' in ${path}`);
      }
      lineIndex = contextIndex + 1;
    }

    if (chunk.oldLines.length === 0) {
      replacements.push({
        index: source.lines.length,
        oldLength: 0,
        newLines: chunk.newLines,
      });
      continue;
    }

    let oldLines: readonly string[] = chunk.oldLines;
    let newLines: readonly string[] = chunk.newLines;
    let match = findSequence(source.lines, oldLines, lineIndex, chunk.endOfFile);
    if (match === undefined && oldLines.at(-1) === "") {
      oldLines = oldLines.slice(0, -1);
      if (newLines.at(-1) === "") newLines = newLines.slice(0, -1);
      match = findSequence(source.lines, oldLines, lineIndex, chunk.endOfFile);
    }
    if (match === undefined) {
      throw new Error(
        `Failed to find expected lines in ${path}:\n${chunk.oldLines.join("\n")}`,
      );
    }

    const replacementLines = [...newLines];
    for (const [oldIndex, newIndex] of chunk.contextLineIndices) {
      if (oldIndex < oldLines.length && newIndex < replacementLines.length) {
        replacementLines[newIndex] = source.lines[match + oldIndex] ?? "";
      }
    }
    replacements.push({
      index: match,
      oldLength: oldLines.length,
      newLines: replacementLines,
    });
    lineIndex = match + oldLines.length;
  }

  const output = [...source.lines];
  for (const replacement of [...replacements].reverse()) {
    output.splice(
      replacement.index,
      replacement.oldLength,
      ...replacement.newLines,
    );
  }
  return `${source.bom}${output.join(source.lineEnding)}${source.lineEnding}`;
};

const exists = async (path: string): Promise<boolean> => {
  try {
    await stat(path);
    return true;
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      (error as { code?: unknown }).code === "ENOENT"
    ) {
      return false;
    }
    throw error;
  }
};

const formatSummary = (affected: AffectedPaths): string => [
  "Success. Updated the following files:",
  ...affected.added.map(path => `A ${path}`),
  ...affected.modified.map(path => `M ${path}`),
  ...affected.deleted.map(path => `D ${path}`),
].join("\n");

const lockPaths = async <T>(
  paths: readonly string[],
  operation: () => Promise<T>,
): Promise<T> => {
  const unique = [...new Set(paths)].sort();
  const acquire = (index: number): Promise<T> => {
    const path = unique[index];
    return path === undefined
      ? operation()
      : withFileMutationQueue(path, () => acquire(index + 1));
  };
  return acquire(0);
};

export const applyPatch = async (
  patchText: string,
  cwd: string,
  signal?: AbortSignal,
): Promise<string> => {
  const operations = parsePatch(patchText);
  if (operations.length === 0) throw new Error("No files were modified.");

  const absolutePaths = operations.flatMap(operation => [
    resolve(cwd, operation.path),
    ...(operation.type === "update" && operation.movePath
      ? [resolve(cwd, operation.movePath)]
      : []),
  ]);

  return lockPaths(absolutePaths, async () => {
    const affected: AffectedPaths = { added: [], modified: [], deleted: [] };
    try {
      for (const operation of operations) {
        if (signal?.aborted) throw new Error("Operation aborted");
        const path = resolve(cwd, operation.path);

        if (operation.type === "add") {
          if (await exists(path)) throw new Error(`File already exists: ${operation.path}`);
          await mkdir(dirname(path), { recursive: true });
          await writeFile(path, operation.content, "utf8");
          affected.added.push(operation.path);
          continue;
        }

        if (operation.type === "delete") {
          await unlink(path).catch(error => {
            throw new Error(`Failed to delete file ${operation.path}`, { cause: error });
          });
          affected.deleted.push(operation.path);
          continue;
        }

        const contents = await readFile(path, "utf8").catch(error => {
          throw new Error(`Failed to read file to update ${operation.path}`, {
            cause: error,
          });
        });
        const updated = deriveUpdatedContents(
          contents,
          operation.path,
          operation.chunks,
        );
        if (operation.movePath) {
          const destination = resolve(cwd, operation.movePath);
          if (destination !== path && (await exists(destination))) {
            throw new Error(`File already exists: ${operation.movePath}`);
          }
          await mkdir(dirname(destination), { recursive: true });
          if (destination === path) {
            await writeFile(path, updated, "utf8");
          } else {
            await writeFile(destination, updated, "utf8");
            affected.modified.push(operation.path);
            await unlink(path);
            continue;
          }
        } else {
          await writeFile(path, updated, "utf8");
        }
        affected.modified.push(operation.path);
      }
    } catch (error) {
      const applied = [
        ...affected.added.map(path => `A ${path}`),
        ...affected.modified.map(path => `M ${path}`),
        ...affected.deleted.map(path => `D ${path}`),
      ];
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(
        applied.length === 0
          ? message
          : `${message}\nApplied before failure:\n${applied.join("\n")}`,
        { cause: error },
      );
    }
    return formatSummary(affected);
  });
};
