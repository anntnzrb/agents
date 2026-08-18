import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type { Dirent } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { Effect } from "effect";

import { getCurrentMode, getModeBorderColor } from "./modes-core.ts";
import { setRequestEditorRender } from "./modes-state.ts";

const MAX_HISTORY_ENTRIES = 100;
const MAX_RECENT_PROMPTS = 30;

interface PromptEntry {
  text: string;
  timestamp: number;
}

class PromptEditor extends CustomEditor {
  public modeLabelProvider?: () => string;
  public modeLabelColor?: (text: string) => string;
  private lockedBorder = false;
  private borderColorOverride?: (text: string) => string;

  constructor(
    tui: ConstructorParameters<typeof CustomEditor>[0],
    theme: ConstructorParameters<typeof CustomEditor>[1],
    keybindings: ConstructorParameters<typeof CustomEditor>[2],
  ) {
    super(tui, theme, keybindings);
    delete (this as { borderColor?: (text: string) => string }).borderColor;
    Object.defineProperty(this, "borderColor", {
      get: () => this.borderColorOverride ?? ((text: string) => text),
      set: (value: (text: string) => string) => {
        if (this.lockedBorder) return;
        this.borderColorOverride = value;
      },
      configurable: true,
      enumerable: true,
    });
  }

  lockBorderColor(): void {
    this.lockedBorder = true;
  }

  override render(width: number): string[] {
    const lines = super.render(width);
    const mode = this.modeLabelProvider?.();
    if (!mode) return lines;

    const stripAnsi = (value: string) => value.replace(/\x1b\[[0-9;]*m/g, "");
    const topPlain = stripAnsi(lines[0] ?? "");
    const scrollPrefixMatch = topPlain.match(/^(─── ↑ \d+ more )/);
    const prefix = scrollPrefixMatch?.[1] ?? "──";

    let label = mode;
    const labelLeftSpace = prefix.endsWith(" ") ? "" : " ";
    const labelRightSpace = " ";
    const minRightBorder = 1;
    const maxLabelLen = Math.max(
      0,
      width -
        prefix.length -
        labelLeftSpace.length -
        labelRightSpace.length -
        minRightBorder,
    );
    if (maxLabelLen <= 0) return lines;
    if (label.length > maxLabelLen) label = label.slice(0, maxLabelLen);

    const labelChunk = `${labelLeftSpace}${label}${labelRightSpace}`;
    const remaining = width - prefix.length - labelChunk.length;
    if (remaining < 0) return lines;

    const right = "─".repeat(Math.max(0, remaining));
    const borderColor = this.borderColor as (text: string) => string;
    const labelColor =
      this.modeLabelColor ?? ((text: string) => borderColor(text));
    lines[0] =
      borderColor(prefix) + labelColor(labelChunk) + borderColor(right);
    return lines;
  }

  requestRenderNow(): void {
    this.tui.requestRender();
  }
}

function getGlobalAgentDir(): string {
  const env = process.env["PI_CODING_AGENT_DIR"];
  const home = process.env["HOME"] ?? "";
  if (env === "~") return home;
  if (env?.startsWith("~/")) return path.join(home, env.slice(2));
  if (env) return env;
  return path.join(home, ".pi", "agent");
}

function extractText(content: Array<{ type: string; text?: string }>): string {
  return content
    .filter((item) => item.type === "text" && typeof item.text === "string")
    .map((item) => item.text ?? "")
    .join("")
    .trim();
}

function collectUserPromptsFromEntries(entries: Array<unknown>): PromptEntry[] {
  const prompts: PromptEntry[] = [];

  for (const entry of entries) {
    if (!entry || typeof entry !== "object") continue;
    if (!("type" in entry) || entry.type !== "message") continue;
    if (!("message" in entry)) continue;
    const message = entry.message as {
      role?: string;
      content?: Array<{ type: string; text?: string }>;
      timestamp?: number;
    };
    if (!message || message.role !== "user" || !Array.isArray(message.content))
      continue;
    const text = extractText(message.content);
    if (!text) continue;
    const timestamp = Number(message.timestamp ?? Date.now());
    prompts.push({ text, timestamp });
  }

  return prompts;
}

const readTailEffect = Effect.fn("readTail")((
  filePath: string,
  maxBytes = 256 * 1024,
) =>
  Effect.acquireUseRelease(
    Effect.tryPromise({
      try: () => fs.open(filePath, "r"),
      catch: () => undefined,
    }).pipe(Effect.orElseSucceed(() => undefined)),
    (handle) => {
      if (!handle) return Effect.succeed("");
      return Effect.tryPromise({
        try: async () => {
          const { size } = await handle.stat();
          const start = Math.max(0, size - maxBytes);
          const length = size - start;
          if (length <= 0) return "";

          const buffer = Buffer.alloc(length);
          const { bytesRead } = await handle.read(buffer, 0, length, start);
          if (bytesRead === 0) return "";
          let chunk = buffer.subarray(0, bytesRead).toString("utf8");
          if (start > 0) {
            const firstNewline = chunk.indexOf("\n");
            if (firstNewline !== -1) chunk = chunk.slice(firstNewline + 1);
          }
          return chunk;
        },
        catch: () => "",
      }).pipe(Effect.orElseSucceed(() => ""));
    },
    (handle) =>
      handle
        ? Effect.promise(() => handle.close().catch(() => undefined))
        : Effect.void,
  ),
);

const readPreviousSessionPromptsEffect = Effect.fn("readPreviousSessionPrompts")(function*(
  sessionDir: string,
  excludeSessionFile?: string,
): Effect.fn.Return<PromptEntry[], never> {
  const prompts: PromptEntry[] = [];
  const resolvedExclude = excludeSessionFile
    ? path.resolve(excludeSessionFile)
    : undefined;

  const entries = yield* Effect.tryPromise({
    try: () => fs.readdir(sessionDir, { withFileTypes: true }),
    catch: () => [] as Dirent[],
  }).pipe(Effect.orElseSucceed(() => [] as Dirent[]));

  if (entries.length === 0) return prompts;

  const fileStats = yield* Effect.all(
    entries
      .filter((entry) => entry.isFile() && entry.name.endsWith(".jsonl"))
      .map((entry) => {
        const filePath = path.join(sessionDir, entry.name);
        return Effect.tryPromise({
          try: async () => {
            const stats = await fs.stat(filePath);
            return { filePath, mtimeMs: stats.mtimeMs };
          },
          catch: () => undefined,
        }).pipe(Effect.orElseSucceed(() => undefined));
      }),
    { concurrency: "unbounded" },
  );

  const sortedFiles = fileStats
    .filter((file): file is { filePath: string; mtimeMs: number } =>
      Boolean(file),
    )
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  for (const file of sortedFiles) {
    if (resolvedExclude && path.resolve(file.filePath) === resolvedExclude)
      continue;

    const tail = yield* readTailEffect(file.filePath);
    if (!tail) continue;
    const lines = tail.split("\n").filter(Boolean);
    for (const line of lines) {
      const entry = yield* Effect.try({
        try: () => JSON.parse(line),
        catch: () => null,
      }).pipe(Effect.orElseSucceed(() => null));

      if (!entry || typeof entry !== "object") continue;
      if (!("type" in entry) || entry.type !== "message") continue;
      if (!("message" in entry)) continue;
      const message = entry.message as {
        role?: string;
        content?: Array<{ type: string; text?: string }>;
        timestamp?: number;
      };
      if (
        !message ||
        message.role !== "user" ||
        !Array.isArray(message.content)
      )
        continue;
      const text = extractText(message.content);
      if (!text) continue;
      const timestamp = Number(message.timestamp ?? Date.now());
      prompts.push({ text, timestamp });
      if (prompts.length >= MAX_RECENT_PROMPTS) break;
    }
    if (prompts.length >= MAX_RECENT_PROMPTS) break;
  }

  return prompts;
});

async function readPreviousSessionPrompts(
  sessionDir: string,
  excludeSessionFile?: string,
): Promise<PromptEntry[]> {
  return Effect.runPromise(readPreviousSessionPromptsEffect(sessionDir, excludeSessionFile));
}

function buildHistoryList(
  currentSession: PromptEntry[],
  previousSessions: PromptEntry[],
): PromptEntry[] {
  const all = [...currentSession, ...previousSessions];
  all.sort((a, b) => a.timestamp - b.timestamp);

  const seen = new Set<string>();
  const deduped: PromptEntry[] = [];
  for (const prompt of all) {
    const key = `${prompt.timestamp}:${prompt.text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(prompt);
  }

  return deduped.slice(-MAX_HISTORY_ENTRIES);
}

function historiesMatch(a: PromptEntry[], b: PromptEntry[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i]?.text !== b[i]?.text || a[i]?.timestamp !== b[i]?.timestamp)
      return false;
  }
  return true;
}

function setEditor(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  history: PromptEntry[],
): void {
  ctx.ui.setEditorComponent((tui, theme, keybindings) => {
    const editor = new PromptEditor(tui, theme, keybindings);
    setRequestEditorRender(() => editor.requestRenderNow());
    editor.modeLabelProvider = () => getCurrentMode();
    editor.modeLabelColor = (text: string) => ctx.ui.theme.fg("dim", text);
    const borderColor = (text: string) => {
      const isBashMode = editor.getText().trimStart().startsWith("!");
      if (isBashMode) return ctx.ui.theme.getBashModeBorderColor()(text);
      return getModeBorderColor(ctx, pi, getCurrentMode())(text);
    };

    editor.borderColor = borderColor;
    editor.lockBorderColor();
    for (const prompt of history) {
      editor.addToHistory?.(prompt.text);
    }
    return editor;
  });
}

function getSessionDirForCwd(cwd: string): string {
  const safePath = `--${cwd.replace(/^[/\\]/, "").replace(/[/\\:]/g, "-")}--`;
  return path.join(getGlobalAgentDir(), "sessions", safePath);
}

let loadCounter = 0;

export function applyEditor(pi: ExtensionAPI, ctx: ExtensionContext): void {
  if (!ctx.hasUI) return;

  const sessionFile = ctx.sessionManager.getSessionFile();
  const currentEntries = ctx.sessionManager.getBranch();
  const currentPrompts = collectUserPromptsFromEntries(currentEntries);
  const immediateHistory = buildHistoryList(currentPrompts, []);

  const currentLoad = ++loadCounter;
  const initialText = ctx.ui.getEditorText();
  setEditor(pi, ctx, immediateHistory);

  void (async () => {
    const previousPrompts = await readPreviousSessionPrompts(
      getSessionDirForCwd(path.resolve(ctx.cwd)),
      sessionFile ?? undefined,
    );
    if (currentLoad !== loadCounter) return;
    if (ctx.ui.getEditorText() !== initialText) return;
    const history = buildHistoryList(currentPrompts, previousPrompts);
    if (historiesMatch(history, immediateHistory)) return;
    setEditor(pi, ctx, history);
  })();
}
