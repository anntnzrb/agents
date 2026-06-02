import { complete, type UserMessage } from "@earendil-works/pi-ai";
import {
  BorderedLoader,
  type ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import { type ActionItem, type SessionEntry } from "./tree-utils.js";

export type RewritePart =
  | { kind: "pick"; item: ActionItem }
  | {
      kind: "summary";
      priority: "combined";
      text: string;
      sourceIds: string[];
      readFiles: string[];
      modifiedFiles: string[];
    };

const SYSTEM_PROMPT = `You summarize conversation history segments between a user and an expert coding agent inside the pi coding agent harness.

Input contains <summary-group> elements. Each <summary-group> must become exactly one summary.
Input may also contain <picked-verbatim-group> blocks between summary groups. Use that nearby picked context for coherence, but do not repeat it unless necessary.

Return ONLY JSON in this exact shape:
{"summary_groups":[{"id":"g1","summary":"..."}]}

Keep group order and ids exactly as provided. Do not invent facts.

Each summary should preserve useful technical detail: goals, constraints, decisions, exact file paths, function names, commands, errors, implementation status, and unresolved issues.
Compress repetitive tool chatter aggressively.

Use this structure:
## Goal
## Constraints & Preferences
## Progress
### Done
### In Progress
### Blocked
## Key Decisions`;

type TreexModel = { id?: string; provider?: string };
type TreexRewriteContext = ExtensionCommandContext & {
  model?: TreexModel;
  modelRegistry: {
    getApiKeyAndHeaders(
      model: TreexModel,
    ): Promise<
      | { ok: true; apiKey?: string; headers?: Record<string, string> }
      | { ok: false; error?: unknown }
    >;
  };
};

type FileOps = { read: Set<string>; modified: Set<string> };
type SummaryGroup = { id: string; items: ActionItem[] };

function createFileOps(): FileOps {
  return { read: new Set(), modified: new Set() };
}

function mergeFileOps(into: FileOps, from: FileOps): void {
  for (const path of from.read) into.read.add(path);
  for (const path of from.modified) into.modified.add(path);
}

function entryFileOps(entry: SessionEntry): FileOps {
  const fileOps = createFileOps();

  if (
    entry.type === "branch_summary" &&
    !entry["fromHook"] &&
    entry["details"] &&
    typeof entry["details"] === "object"
  ) {
    const details = entry["details"] as {
      readFiles?: unknown;
      modifiedFiles?: unknown;
    };
    if (Array.isArray(details.readFiles)) {
      for (const file of details.readFiles) {
        if (typeof file === "string") fileOps.read.add(file);
      }
    }
    if (Array.isArray(details.modifiedFiles)) {
      for (const file of details.modifiedFiles) {
        if (typeof file === "string") fileOps.modified.add(file);
      }
    }
  }

  if (
    entry.type !== "message" ||
    entry.message?.role !== "assistant" ||
    !Array.isArray(entry.message.content)
  ) {
    return fileOps;
  }

  for (const block of entry.message.content) {
    if (!block || typeof block !== "object" || block.type !== "toolCall")
      continue;
    const toolName = typeof block.name === "string" ? block.name : "";
    const path =
      typeof block.arguments?.path === "string"
        ? block.arguments.path
        : undefined;
    if (!path) continue;

    if (toolName === "read") fileOps.read.add(path);
    if (toolName === "write" || toolName === "edit") fileOps.modified.add(path);
  }

  return fileOps;
}

function computeFileLists(entries: SessionEntry[]): {
  readFiles: string[];
  modifiedFiles: string[];
} {
  const combined = createFileOps();
  for (const entry of entries) mergeFileOps(combined, entryFileOps(entry));

  for (const path of combined.modified) combined.read.delete(path);

  return {
    readFiles: [...combined.read].sort(),
    modifiedFiles: [...combined.modified].sort(),
  };
}

function entryTextContent(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";

  const text = content
    .filter(
      (block) =>
        block &&
        typeof block === "object" &&
        "type" in block &&
        block.type === "text",
    )
    .map((block: any) => String(block.text ?? ""))
    .join("\n")
    .trim();

  return text;
}

function summarizeToolCalls(content: unknown): string[] {
  if (!Array.isArray(content)) return [];
  return content
    .filter(
      (block) =>
        block &&
        typeof block === "object" &&
        "type" in block &&
        block.type === "toolCall",
    )
    .map((block: any) => {
      const name = typeof block.name === "string" ? block.name : "tool";
      const args =
        block.arguments && typeof block.arguments === "object"
          ? block.arguments
          : {};
      const preview = JSON.stringify(args);
      return `${name}(${preview.slice(0, 120)}${preview.length > 120 ? "..." : ""})`;
    });
}

function serializeEntry(entry: SessionEntry): string {
  if (entry.type === "message") {
    const role = entry.message?.role ?? "message";
    if (role === "toolResult") {
      const tool =
        entry.message?.toolName ?? entry.message?.toolCallId ?? "tool";
      return `[ToolResult:${tool}]`;
    }
    const text = entryTextContent(entry.message?.content);
    const toolCalls = summarizeToolCalls(entry.message?.content);
    const parts = [`[${role}]`, text || "(no text)"];
    if (toolCalls.length > 0) parts.push(`[ToolCalls] ${toolCalls.join("; ")}`);
    return parts.join(" ");
  }

  if (entry.type === "custom_message") {
    const text = entryTextContent(entry.content);
    return `[custom:${entry.customType ?? "custom"}] ${text || "(no text)"}`;
  }

  if (entry.type === "branch_summary") {
    return `[branch_summary] ${String(entry.summary ?? "")}`;
  }

  if (entry.type === "compaction") {
    return `[compaction] ${String(entry.summary ?? "")}`;
  }

  return `[${entry.type ?? "entry"}]`;
}

function formatFileOperations(entries: SessionEntry[]): string {
  const { readFiles, modifiedFiles } = computeFileLists(entries);
  const sections: string[] = [];

  if (readFiles.length > 0) {
    sections.push(`<read-files>\n${readFiles.join("\n")}\n</read-files>`);
  }
  if (modifiedFiles.length > 0) {
    sections.push(
      `<modified-files>\n${modifiedFiles.join("\n")}\n</modified-files>`,
    );
  }

  return sections.length > 0 ? `\n${sections.join("\n\n")}` : "";
}

function groupSummaryItems(items: ActionItem[]): SummaryGroup[] {
  const groups: SummaryGroup[] = [];
  let current: SummaryGroup | null = null;

  for (const item of items) {
    if (item.action === "pick") {
      current = null;
      continue;
    }
    if (item.action === "drop") continue;

    if (!current) {
      current = { id: `g${groups.length + 1}`, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }

  return groups;
}

function conversationBlock(entries: SessionEntry[]): string {
  const conversation = entries.map(serializeEntry).join("\n");
  return `<conversation>\n${conversation}\n</conversation>${formatFileOperations(entries)}`;
}

export function buildSummarizerUserMessage(items: ActionItem[]): string {
  const groups = groupSummaryItems(items);
  const groupByItemId = new Map<string, SummaryGroup>();
  for (const group of groups) {
    for (const item of group.items) groupByItemId.set(item.id, group);
  }

  const parts: string[] = [];
  const emitted = new Set<string>();
  let picked: ActionItem[] = [];

  const flushPicked = () => {
    if (picked.length === 0) return;
    parts.push(
      `<picked-verbatim-group>\n${conversationBlock(picked.map((item) => item.entry))}\n</picked-verbatim-group>`,
    );
    picked = [];
  };

  for (const item of items) {
    if (item.action === "drop") continue;
    if (item.action === "pick") {
      picked.push(item);
      continue;
    }

    flushPicked();
    const group = groupByItemId.get(item.id);
    if (!group || emitted.has(group.id)) continue;
    emitted.add(group.id);

    parts.push(
      `<summary-group id="${group.id}">\n<summarize entryIds="${group.items.map((entryItem) => entryItem.id).join(",")}">\n${conversationBlock(group.items.map((entryItem) => entryItem.entry))}\n</summarize>\n</summary-group>`,
    );
  }

  flushPicked();
  return parts.join("\n\n");
}

function parseSummaryJson(responseText: string): Map<string, string> {
  let parsed: any;
  try {
    parsed = JSON.parse(
      responseText
        .replace(/^```json\s*/i, "")
        .replace(/```$/g, "")
        .trim(),
    );
  } catch {
    throw new Error(
      `Could not parse summarizer JSON: ${responseText.slice(0, 500)}`,
    );
  }

  if (parsed.error) throw new Error(String(parsed.error));

  const summaries = new Map<string, string>();
  for (const group of parsed.summary_groups ?? []) {
    const id = typeof group?.id === "string" ? group.id : "";
    const summary = typeof group?.summary === "string" ? group.summary : "";
    if (id) summaries.set(id, summary);
  }
  return summaries;
}

async function summarizeGroups(
  ctx: TreexRewriteContext,
  items: ActionItem[],
): Promise<Map<string, string> | null> {
  const model = ctx.model;
  if (!model) throw new Error("No model selected for summarization");

  const result = await ctx.ui.custom<string | null>(
    (tui: any, theme: any, _kb: any, done: any) => {
      const loader = new BorderedLoader(
        tui,
        theme,
        `Treex summarizing with ${model.id ?? "selected model"}...`,
      );
      loader.onAbort = () => done(null);

      const run = async () => {
        const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
        if (!auth.ok || !auth.apiKey) {
          throw new Error(
            auth.ok
              ? `No API key for ${model.provider ?? "provider"}`
              : String((auth as { error?: unknown }).error ?? "auth failed"),
          );
        }

        const message: UserMessage = {
          role: "user",
          content: [{ type: "text", text: buildSummarizerUserMessage(items) }],
          timestamp: Date.now(),
        };

        const response = await complete(
          model,
          { systemPrompt: SYSTEM_PROMPT, messages: [message] },
          {
            apiKey: auth.apiKey,
            headers: auth.headers,
            signal: loader.signal,
          },
        );

        if (response.stopReason === "aborted") return null;
        return response.content
          .filter((contentBlock: any) => contentBlock.type === "text")
          .map((contentBlock: any) => contentBlock.text)
          .join("\n");
      };

      run()
        .then(done)
        .catch((error) =>
          done(JSON.stringify({ error: String(error?.message ?? error) })),
        );
      return loader;
    },
  );

  if (result === null) return null;
  return parseSummaryJson(result);
}

export async function buildRewrite(
  ctx: TreexRewriteContext,
  items: ActionItem[],
): Promise<RewritePart[] | null> {
  const groups = groupSummaryItems(items);
  const summaries =
    groups.length > 0
      ? await summarizeGroups(ctx, items)
      : new Map<string, string>();
  if (summaries === null) return null;

  const groupByItemId = new Map<string, SummaryGroup>();
  for (const group of groups) {
    for (const item of group.items) groupByItemId.set(item.id, group);
  }

  const emitted = new Set<string>();
  const parts: RewritePart[] = [];

  for (const item of items) {
    if (item.action === "drop") continue;
    if (item.action === "pick") {
      parts.push({ kind: "pick", item });
      continue;
    }

    const group = groupByItemId.get(item.id);
    if (!group || emitted.has(group.id)) continue;
    emitted.add(group.id);

    const { readFiles, modifiedFiles } = computeFileLists(
      group.items.map((entryItem) => entryItem.entry),
    );
    parts.push({
      kind: "summary",
      priority: "combined",
      text: summaries.get(group.id) ?? "",
      sourceIds: group.items.map((entryItem) => entryItem.id),
      readFiles,
      modifiedFiles,
    });
  }

  return parts;
}
