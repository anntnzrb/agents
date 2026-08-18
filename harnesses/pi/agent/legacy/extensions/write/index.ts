import { Effect, Schema } from "effect";
import { createHash, randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import {
  chmod,
  lstat,
  mkdir,
  open,
  readFile,
  readlink,
  realpath,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import {
  createWriteToolDefinition,
  formatSize,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import {
  getReusableText,
  joinRenderSegments,
  pluralize,
  type ColorTheme,
  type RenderTheme,
} from "../_shared/render-utils.js";
import { getUtf8ContentStats } from "../_shared/text-stats.js";
import { asString } from "../_shared/value-utils.js";

type WriteArgs = {
  path?: unknown;
  content?: unknown;
  expectedHash?: unknown;
};

type WriteRenderState = {
  marker?: "+" | "~" | "?";
};

const getWriteMarker = (rawPath: string, cwd: string): "+" | "~" | "?" => {
  if (rawPath.length === 0 || rawPath === "...") return "?";
  try {
    const absolutePath = path.isAbsolute(rawPath)
      ? rawPath
      : path.resolve(cwd, rawPath);
    return existsSync(absolutePath) ? "~" : "+";
  } catch {
    return "?";
  }
};

const formatWriteMarker = (
  marker: "+" | "~" | "?",
  theme: ColorTheme,
): string => {
  if (marker === "+") return theme.fg("toolDiffAdded", marker);
  if (marker === "~") return theme.fg("warning", marker);
  return theme.fg("muted", marker);
};

const writeSchema = {
  type: "object",
  properties: {
    path: {
      type: "string",
      description: "Path to the file to write (relative or absolute)",
    },
    content: { type: "string", description: "Content to write to the file" },
    expectedHash: {
      type: "string",
      description:
        "Optional SHA-256 hex hash of the current file contents. If provided, write fails when the existing file does not match.",
    },
  },
  required: ["path", "content"],
};

const sha256 = (content: Uint8Array): string =>
  createHash("sha256").update(content).digest("hex");

export class WriteFileError extends Schema.TaggedError<WriteFileError>()(
  "WriteFileError",
  {
    path: Schema.String,
    message: Schema.String,
    cause: Schema.optional(Schema.Unknown),
  },
) {}

const bestEffort = <A>(operation: () => Promise<A>): Effect.Effect<A | undefined> =>
  Effect.promise(async () => {
    try {
      return await operation();
    } catch {
      return undefined;
    }
  });

const writeError = (
  filePath: string,
  operation: string,
  cause: unknown,
): WriteFileError =>
  new WriteFileError({
    path: filePath,
    message: `${operation} ${filePath}: ${cause instanceof Error ? cause.message : String(cause)}`,
    cause,
  });

export const resolveWriteTargetEffect = Effect.fn("resolveWriteTarget")(function*(
  filePath: string,
): Effect.fn.Return<string, never> {
  const info = yield* bestEffort(() => lstat(filePath));
  if (!info?.isSymbolicLink()) return filePath;

  const resolved = yield* bestEffort(() => realpath(filePath));
  if (resolved) return resolved;

  const linkTarget = yield* bestEffort(() => readlink(filePath));
  return linkTarget
    ? path.isAbsolute(linkTarget)
      ? linkTarget
      : path.resolve(path.dirname(filePath), linkTarget)
    : filePath;
});

export const syncDirectoryEffect = Effect.fn("syncDirectory")(function*(
  dir: string,
): Effect.fn.Return<void, never> {
  yield* Effect.acquireUseRelease(
    Effect.tryPromise({
      try: () => open(dir, "r"),
      catch: () => undefined,
    }),
    (handle) =>
      Effect.tryPromise({
        try: () => handle.sync(),
        catch: () => undefined,
      }),
    (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
  ).pipe(Effect.ignore);
});

const writeTemporaryFile = (
  tmpPath: string,
  content: string,
  mode: number | undefined,
): Effect.Effect<void, WriteFileError> =>
  Effect.acquireUseRelease(
    Effect.tryPromise({
      try: () => open(tmpPath, "wx", mode),
      catch: (cause) => writeError(tmpPath, "Unable to open temporary file", cause),
    }),
    (handle) =>
      Effect.tryPromise({
        try: async () => {
          await handle.writeFile(content, "utf8");
          await handle.sync();
        },
        catch: (cause) => writeError(tmpPath, "Unable to write temporary file", cause),
      }),
    (handle) => Effect.promise(() => handle.close().catch(() => undefined)),
  );

export const atomicWriteFileEffect = Effect.fn("atomicWriteFile")(function*(
  filePath: string,
  content: string,
): Effect.fn.Return<void, WriteFileError> {
  const targetPath = yield* resolveWriteTargetEffect(filePath);
  const dir = path.dirname(targetPath);
  const tmpPath = path.join(
    dir,
    `.pi-write-${Date.now()}-${randomBytes(6).toString("hex")}.tmp`,
  );
  const info = yield* bestEffort(() => stat(targetPath));
  const existing = info
    ? { mode: info.mode & 0o777, nlink: info.nlink }
    : undefined;

  if (existing && existing.nlink > 1) {
    return yield* Effect.tryPromise({
      try: () => writeFile(targetPath, content, "utf8"),
      catch: (cause) => writeError(targetPath, "Unable to write hardlinked file", cause),
    });
  }

  yield* Effect.acquireUseRelease(
    Effect.succeed(tmpPath),
    () =>
      Effect.gen(function*() {
        yield* writeTemporaryFile(tmpPath, content, existing?.mode);
        if (existing) yield* bestEffort(() => chmod(tmpPath, existing.mode));
        yield* Effect.tryPromise({
          try: () => rename(tmpPath, targetPath),
          catch: (cause) => writeError(targetPath, "Unable to replace file", cause),
        });
        yield* syncDirectoryEffect(dir);
      }),
    (temporaryPath) =>
      Effect.promise(() => unlink(temporaryPath).catch(() => undefined)),
  );
});

const atomicWriteFile = (filePath: string, content: string): Promise<void> =>
  Effect.runPromise(atomicWriteFileEffect(filePath, content));

type HardenedWriteOperations = {
  mkdir: (dir: string) => Promise<void>;
  writeFile: (filePath: string, content: string) => Promise<void>;
};

type CreateWriteToolDefinition = (
  cwd: string,
  options?: { operations?: HardenedWriteOperations },
) => ReturnType<typeof createWriteToolDefinition>;

const createNativeWriteToolDefinition =
  createWriteToolDefinition as CreateWriteToolDefinition;

const createHardenedWriteToolDefinition = (
  cwd: string,
  expectedHash?: string,
) =>
  createNativeWriteToolDefinition(cwd, {
    operations: {
      mkdir: (dir) => mkdir(dir, { recursive: true }).then(() => undefined),
      writeFile: async (filePath, content) => {
        if (expectedHash !== undefined) {
          let current: Uint8Array;
          try {
            current = (await readFile(filePath)) as Uint8Array;
          } catch {
            throw new Error(
              `Hash mismatch for ${filePath}: expected ${expectedHash}, got <missing file>`,
            );
          }
          const actualHash = sha256(current);
          if (actualHash !== expectedHash)
            throw new Error(
              `Hash mismatch for ${filePath}: expected ${expectedHash}, got ${actualHash}`,
            );
        }
        await atomicWriteFile(filePath, content);
      },
    },
  });

const executeWrite = (
  toolCallId: string,
  cwd: string,
  input: WriteArgs,
  signal: AbortSignal,
  onUpdate?: unknown,
  ctx?: unknown,
) => {
  const expectedHash = asString(input.expectedHash);
  const tool = createHardenedWriteToolDefinition(cwd, expectedHash);
  if (!tool.execute) throw new Error("native write tool is unavailable");
  return tool.execute(
    toolCallId,
    input,
    signal,
    onUpdate as never,
    ctx as never,
  );
};

const buildCollapsedWriteCallText = (
  args: WriteArgs,
  marker: "+" | "~" | "?",
  theme: RenderTheme,
): string => {
  const rawPath = asString(args.path) ?? "...";
  const content = asString(args.content) ?? "";
  const stats = getUtf8ContentStats(content);
  const lines = `${stats.lines} ${pluralize(stats.lines, "line")}`;

  return joinRenderSegments(
    [
      `${theme.fg("muted", "▣")} ${theme.fg("toolTitle", theme.bold("write"))} ${formatWriteMarker(marker, theme)} ${theme.fg("muted", rawPath)}`,
      formatSize(stats.bytes),
      lines,
    ],
    theme,
  );
};

export const __test = {
  atomicWriteFile,
  buildCollapsedWriteCallText,
  executeWrite: (cwd: string, input: WriteArgs) =>
    executeWrite("test", cwd, input, undefined as never),
  formatWriteMarker,
  getContentStats: getUtf8ContentStats,
  sha256,
};

export default function writeExtension(pi: ExtensionAPI): void {
  const cwd = process.cwd();
  const baseWrite = createWriteToolDefinition(cwd);

  pi.registerTool({
    ...baseWrite,
    parameters: writeSchema,
    renderShell: "self",
    async execute(toolCallId, input, signal, onUpdate, ctx) {
      return executeWrite(
        toolCallId,
        cwd,
        input as WriteArgs,
        signal,
        onUpdate,
        ctx,
      );
    },
    renderCall(args, theme, context) {
      const state = context.state as WriteRenderState;
      const typedArgs = (args ?? {}) as WriteArgs;
      const rawPath = asString(typedArgs.path) ?? "...";
      const canClassifyMarker =
        rawPath.length > 0 &&
        rawPath !== "..." &&
        (!context.executionStarted || !context.argsComplete);
      if (
        (state.marker === undefined || state.marker === "?") &&
        canClassifyMarker
      ) {
        state.marker = getWriteMarker(rawPath, context.cwd);
      } else if (state.marker === undefined) {
        state.marker = "?";
      }

      const text = getReusableText(context.lastComponent);
      text.setText(
        buildCollapsedWriteCallText(typedArgs, state.marker ?? "?", theme),
      );
      return text;
    },
  });
}
