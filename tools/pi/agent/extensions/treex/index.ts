import type {
    ExtensionAPI,
    ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import { showActionList } from "./action-list.js";
import { buildRewrite, type RewritePart } from "./summarize.js";
import { showTreeSelector } from "./tree-selector.js";
import {
    entriesBetweenAncestorAndLeaf,
    isAncestor,
    makeActionItems,
    parentOf,
    type SessionEntry,
    type TreexSessionManager,
} from "./tree-utils.js";

type NotificationLevel = "info" | "warning" | "error";
type NavigateTreeResult = {
    aborted?: boolean;
    cancelled?: boolean;
    editorText?: string;
};

type MutableSessionManager = TreexSessionManager & {
    getLeafId(): string | null;
    getTree(): unknown[];
    resetLeaf(): void;
    branch(entryId: string): void;
    appendMessage(message: unknown): string;
    appendCustomMessageEntry(
        customType: string | undefined,
        content: unknown,
        display: unknown,
        details: unknown,
    ): string;
    appendModelChange(provider: unknown, modelId: unknown): string;
    appendThinkingLevelChange(thinkingLevel: unknown): string;
    appendCompaction(
        summary: string,
        firstKeptEntryId: string,
        tokensBefore: number,
        details?: unknown,
        fromHook?: boolean,
    ): string;
};

type TreexContext = ExtensionCommandContext & {
    waitForIdle?: () => Promise<void>;
    sessionManager: MutableSessionManager;
    navigateTree: (
        targetId: string,
        options: { summarize: boolean; customInstructions?: string },
    ) => Promise<NavigateTreeResult>;
    modelRegistry: {
        getApiKeyAndHeaders(model: unknown): Promise<unknown>;
    };
    ui: ExtensionCommandContext["ui"] & {
        select: (title: string, options: string[]) => Promise<string | undefined>;
        input: (title: string, placeholder?: string) => Promise<string | undefined>;
        notify: (message: string, level?: NotificationLevel) => void;
    };
};

function cloneValue<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
}

function freshId(sm: MutableSessionManager): string {
    for (let i = 0; i < 100; i++) {
        const id = Math.random().toString(36).slice(2, 10);
        if (!sm.getEntry(id)) return id;
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function appendRawEntry(sm: MutableSessionManager, entry: unknown): void {
    // Pi does not currently expose public append APIs for branch summaries.
    // Keep the cursed private call quarantined here so future native APIs only
    // require changing one adapter instead of spelunking the whole extension.
    (sm as unknown as { _appendEntry(entry: unknown): void })._appendEntry(entry);
}

function appendClonedEntry(
    sm: MutableSessionManager,
    original: SessionEntry,
): string | null {
    switch (original.type) {
        case "message":
            return sm.appendMessage(cloneValue(original.message));
        case "custom_message":
            return sm.appendCustomMessageEntry(
                original.customType,
                cloneValue(original.content),
                original["display"],
                cloneValue(original["details"]),
            );
        case "model_change":
            return sm.appendModelChange(original["provider"], original.modelId);
        case "thinking_level_change":
            return sm.appendThinkingLevelChange(original.thinkingLevel);
        case "compaction":
            return sm.appendCompaction(
                original.summary ?? "",
                String(original["firstKeptEntryId"] ?? original.id),
                Number(original.tokensBefore ?? 0),
                cloneValue(original["details"]),
                Boolean(original["fromHook"]),
            );
        case "branch_summary": {
            const entry = {
                type: "branch_summary",
                id: freshId(sm),
                parentId: sm.getLeafId(),
                timestamp: new Date().toISOString(),
                fromId: original["fromId"],
                summary: original.summary,
                details: cloneValue(original["details"]),
                fromHook: original["fromHook"],
            };
            appendRawEntry(sm, entry);
            return entry.id;
        }
        default:
            return null;
    }
}

function formatFileOperations(readFiles: string[], modifiedFiles: string[]): string {
    const sections: string[] = [];
    if (readFiles.length > 0) {
        sections.push(`<read-files>\n${readFiles.join("\n")}\n</read-files>`);
    }
    if (modifiedFiles.length > 0) {
        sections.push(`<modified-files>\n${modifiedFiles.join("\n")}\n</modified-files>`);
    }
    return sections.length > 0 ? `\n\n${sections.join("\n\n")}` : "";
}

function appendSummary(
    sm: MutableSessionManager,
    summary: string,
    sourceIds: string[],
    readFiles: string[],
    modifiedFiles: string[],
): string {
    const summaryWithFileOps = summary + formatFileOperations(readFiles, modifiedFiles);
    const entry = {
        type: "branch_summary",
        id: freshId(sm),
        parentId: sm.getLeafId(),
        timestamp: new Date().toISOString(),
        fromId: sourceIds.at(-1) ?? sm.getLeafId() ?? "treex",
        summary: summaryWithFileOps,
        details: { sourceIds, readFiles, modifiedFiles, generatedBy: "treex" },
        fromHook: false,
    };
    appendRawEntry(sm, entry);
    return entry.id;
}

async function applyRewrite(
    ctx: TreexContext,
    targetId: string,
    parts: RewritePart[] | null,
): Promise<string | null> {
    if (!parts) return null;
    const sm = ctx.sessionManager;

    const parentId = parentOf(sm, targetId);
    if (parentId) sm.branch(parentId);
    else sm.resetLeaf();

    let appended = 0;
    for (const part of parts) {
        if (part.kind === "pick") {
            if (appendClonedEntry(sm, part.item.entry)) appended++;
        } else if (part.text.trim()) {
            appendSummary(
                sm,
                part.text.trim(),
                part.sourceIds,
                part.readFiles,
                part.modifiedFiles,
            );
            appended++;
        }
    }
    if (appended === 0) {
        ctx.ui.notify(
            "Treex produced no entries; moved to target parent.",
            "warning",
        );
    }

    return sm.getLeafId();
}

function isEditableNavigationTarget(entry: SessionEntry | undefined): boolean {
    if (!entry) return false;
    if (entry.type === "custom_message") return true;
    return entry.type === "message" && entry.message?.role === "user";
}

async function navigateToRewrittenLeaf(
    sm: MutableSessionManager,
    ctx: TreexContext,
    rewrittenLeafId: string,
): Promise<void> {
    const rewrittenLeaf = sm.getEntry(rewrittenLeafId);

    if (isEditableNavigationTarget(rewrittenLeaf)) {
        const draftParentId = sm.getLeafId();
        if (!draftParentId) throw new Error("failed to get leaf id");
        const draftId = sm.appendMessage({
            role: "user",
            content: "",
            timestamp: Date.now(),
        });
        sm.branch(draftParentId);
        const result = await ctx.navigateTree(draftId, { summarize: false });
        if (result.cancelled) throw new Error("navigateTree cancelled unexpectedly");
        return;
    }

    const parentId = rewrittenLeaf?.parentId ?? null;
    if (parentId) sm.branch(parentId);
    else sm.resetLeaf();

    const result = await ctx.navigateTree(rewrittenLeafId, { summarize: false });
    if (result.cancelled) throw new Error("navigateTree cancelled unexpectedly");
}

async function chooseAncestorMode(ctx: TreexContext): Promise<"navigate" | "rewrite" | null> {
    const choice = await ctx.ui.select("Treex ancestor target", [
        "Rewrite path (pick/summarize/drop)",
        "Navigate only",
        "Cancel",
    ]);
    if (choice === "Rewrite path (pick/summarize/drop)") return "rewrite";
    if (choice === "Navigate only") return "navigate";
    return null;
}

async function navigateNative(ctx: TreexContext, targetId: string): Promise<void> {
    const result = await ctx.navigateTree(targetId, { summarize: false });
    if (result.cancelled) ctx.ui.notify("Navigation cancelled", "warning");
    else ctx.ui.notify("Navigated to selected point", "info");
}

async function runTreexCommand(pi: ExtensionAPI, rawCtx: ExtensionCommandContext): Promise<void> {
    const ctx = rawCtx as TreexContext;
    if (!ctx.hasUI) {
        ctx.ui.notify("/treex requires interactive mode", "error");
        return;
    }
    await ctx.waitForIdle?.();

    const sm = ctx.sessionManager;
    const currentLeafId = sm.getLeafId();
    if (!currentLeafId) {
        ctx.ui.notify("No current session leaf", "error");
        return;
    }

    const targetId = await showTreeSelector(ctx as never, pi);
    if (!targetId || targetId === currentLeafId) return;

    if (!isAncestor(sm, targetId, currentLeafId)) {
        await navigateNative(ctx, targetId);
        return;
    }

    const mode = await chooseAncestorMode(ctx);
    if (!mode) return;
    if (mode === "navigate") {
        await navigateNative(ctx, targetId);
        return;
    }

    const segment = entriesBetweenAncestorAndLeaf(
        sm,
        targetId,
        currentLeafId,
    );
    const actionItems = makeActionItems(segment);
    if (segment.length === 0 || actionItems.length === 0) {
        ctx.ui.notify("Could not compute treex path with any context-bearing entries", "error");
        return;
    }

    const edited = await showActionList(ctx, actionItems);
    if (!edited) return;

    try {
        const rewrite = await buildRewrite(ctx as never, edited);
        if (!rewrite) {
            ctx.ui.notify("Treex rewrite cancelled", "info");
            return;
        }
        const rewrittenLeafId = await applyRewrite(ctx, targetId, rewrite);
        if (!rewrittenLeafId) return;

        await navigateToRewrittenLeaf(sm, ctx, rewrittenLeafId);
        ctx.ui.notify("Treex branch created", "info");
    } catch (err: unknown) {
        ctx.ui.notify(
            `Treex failed: ${err instanceof Error ? err.message : String(err)}`,
            "error",
        );
    }
}

export default function (pi: ExtensionAPI): void {
    pi.registerCommand("treex", {
        description: "Extended tree navigation with optional interactive history rewrite",
        handler: async (_args: unknown, rawCtx: ExtensionCommandContext) => {
            await runTreexCommand(pi, rawCtx);
        },
    });
}
