import {
    DynamicBorder,
    type ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import {
    Container,
    getKeybindings,
    Key,
    matchesKey,
    Text,
    truncateToWidth,
} from "@earendil-works/pi-tui";
import { actionLetter, type ActionItem, type SessionEntry, type TreebaseAction } from "./tree-utils.js";

type Theme = any;
type ToolCallInfo = { name: string; arguments: Record<string, unknown> };

type ActionRow = {
    itemIndex: number;
    groupId: string;
    entry: SessionEntry;
    action: TreebaseAction;
};

type VisibleActionRow = ActionRow & {
    groupPosition: "only" | "first" | "middle" | "last";
};

function extractTextContent(content: unknown, maxLen = 220): string {
    if (typeof content === "string") return content.slice(0, maxLen);
    if (!Array.isArray(content)) return "";
    let result = "";
    for (const part of content) {
        if (
            part &&
            typeof part === "object" &&
            "type" in part &&
            part.type === "text" &&
            "text" in part &&
            typeof part.text === "string"
        ) {
            result += part.text;
            if (result.length >= maxLen) return result.slice(0, maxLen);
        }
    }
    return result;
}

function isHiddenToolCallEnvelope(entry: SessionEntry): boolean {
    if (entry.type !== "message" || entry.message?.role !== "assistant") return false;
    const message = entry.message;
    const hasText = extractTextContent(message.content).trim().length > 0;
    const isErrorOrAborted =
        Boolean(message.errorMessage) ||
        (Boolean(message.stopReason) && message.stopReason !== "stop" && message.stopReason !== "toolUse");
    return !hasText && !isErrorOrAborted;
}

class ActionList {
    private selectedVisibleIndex = 0;
    private maxVisibleLines: number;
    private groupAction = new Map<string, TreebaseAction>();
    private rows: ActionRow[];
    private toolCallMap = new Map<string, ToolCallInfo>();

    constructor(
        private items: ActionItem[],
        private done: (items: ActionItem[] | null) => void,
        private theme: Theme,
        terminalHeight: number,
    ) {
        this.maxVisibleLines = Math.max(8, Math.floor(terminalHeight / 2));
        this.rows = items.map((item, itemIndex) => {
            const groupId = item.groupId || `row:${itemIndex}`;
            this.groupAction.set(groupId, item.action);
            return {
                itemIndex,
                groupId,
                entry: item.entry,
                action: item.action,
            };
        });
        this.selectedVisibleIndex = Math.max(0, this.getVisibleRows().length - 1);
        this.buildToolCallMap();
    }

    invalidate() {}

    private buildToolCallMap() {
        this.toolCallMap.clear();
        for (const row of this.rows) {
            if (row.entry.type !== "message" || row.entry.message?.role !== "assistant") continue;
            const content = row.entry.message.content;
            if (!Array.isArray(content)) continue;
            for (const block of content) {
                if (
                    block &&
                    typeof block === "object" &&
                    "type" in block &&
                    block.type === "toolCall" &&
                    "id" in block &&
                    "name" in block
                ) {
                    this.toolCallMap.set(String(block.id), {
                        name: String(block.name),
                        arguments:
                            "arguments" in block && block.arguments && typeof block.arguments === "object"
                                ? (block.arguments as Record<string, unknown>)
                                : {},
                    });
                }
            }
        }
    }

    private getVisibleRows(): VisibleActionRow[] {
        const visible = this.rows
            .filter((row) => !isHiddenToolCallEnvelope(row.entry))
            .map((row) => ({
                ...row,
                action: this.groupAction.get(row.groupId) ?? "summarize",
                groupPosition: "only" as const,
            }));

        return visible.map((row, index) => {
            const samePrev = visible[index - 1]?.groupId === row.groupId;
            const sameNext = visible[index + 1]?.groupId === row.groupId;
            return {
                ...row,
                groupPosition: !samePrev && !sameNext
                    ? "only"
                    : !samePrev
                      ? "first"
                      : !sameNext
                        ? "last"
                        : "middle",
            };
        });
    }

    render(width: number): string[] {
        const visible = this.getVisibleRows();
        if (visible.length === 0) return [truncateToWidth(this.theme.fg("muted", "  No entries on path"), width)];

        this.selectedVisibleIndex = Math.max(0, Math.min(this.selectedVisibleIndex, visible.length - 1));

        const start = Math.max(
            0,
            Math.min(this.selectedVisibleIndex - Math.floor(this.maxVisibleLines / 2), visible.length - this.maxVisibleLines),
        );
        const end = Math.min(visible.length, start + this.maxVisibleLines);

        const lines: string[] = [];
        for (let i = start; i < end; i++) {
            const row = visible[i];
            if (!row) continue;
            const selected = i === this.selectedVisibleIndex;
            const cursor = selected ? this.theme.fg("accent", "› ") : "  ";
            const action = this.formatAction(row.action);
            const prefix = this.formatGroupPrefix(row.groupPosition);
            const content = this.getEntryDisplayText(row.entry, selected);
            let line = `${cursor}${action} ${this.theme.fg("dim", prefix)}${content}`;
            if (selected) line = this.theme.bg("selectedBg", line);
            lines.push(truncateToWidth(line, width));
        }

        lines.push(truncateToWidth(this.theme.fg("muted", `  (${this.selectedVisibleIndex + 1}/${visible.length})`), width));
        lines.push(
            truncateToWidth(
                this.theme.fg(
                    "muted",
                    "  ↑/↓ move  ←/→ jump groups  P/S/D set action  Enter confirm  Esc cancel",
                ),
                width,
            ),
        );
        return lines;
    }

    handleInput(data: string) {
        const kb = getKeybindings();
        const visible = this.getVisibleRows();
        if (visible.length === 0) return;

        if (kb.matches(data, "tui.select.up") || matchesKey(data, Key.up)) {
            this.selectedVisibleIndex = this.selectedVisibleIndex === 0 ? visible.length - 1 : this.selectedVisibleIndex - 1;
            return;
        }
        if (kb.matches(data, "tui.select.down") || matchesKey(data, Key.down)) {
            this.selectedVisibleIndex = this.selectedVisibleIndex === visible.length - 1 ? 0 : this.selectedVisibleIndex + 1;
            return;
        }
        if (kb.matches(data, "app.tree.foldOrUp") || kb.matches(data, "tui.editor.cursorLeft") || matchesKey(data, Key.left)) {
            this.jumpGroup(visible, "up");
            return;
        }
        if (kb.matches(data, "app.tree.unfoldOrDown") || kb.matches(data, "tui.editor.cursorRight") || matchesKey(data, Key.right)) {
            this.jumpGroup(visible, "down");
            return;
        }
        if (kb.matches(data, "tui.select.confirm") || matchesKey(data, Key.enter)) {
            this.done(this.toActionItems());
            return;
        }
        if (kb.matches(data, "tui.select.cancel") || matchesKey(data, Key.escape)) {
            this.done(null);
            return;
        }

        const lower = data.toLowerCase();
        if (lower === "p") this.setCurrentAction(visible, "pick");
        else if (lower === "s") this.setCurrentAction(visible, "summarize");
        else if (lower === "d") this.setCurrentAction(visible, "drop");
    }

    private setCurrentAction(visible: VisibleActionRow[], action: TreebaseAction) {
        const row = visible[this.selectedVisibleIndex];
        if (!row) return;
        this.groupAction.set(row.groupId, action);
    }

    private jumpGroup(visible: VisibleActionRow[], direction: "up" | "down") {
        const currentGroup = visible[this.selectedVisibleIndex]?.groupId;
        if (!currentGroup) return;

        if (direction === "up") {
            let first = this.selectedVisibleIndex;
            while (first > 0 && visible[first - 1]?.groupId === currentGroup) first--;
            this.selectedVisibleIndex = Math.max(0, first - 1);
            return;
        }

        let last = this.selectedVisibleIndex;
        while (last < visible.length - 1 && visible[last + 1]?.groupId === currentGroup) last++;
        if (last >= visible.length - 1) {
            this.selectedVisibleIndex = visible.length - 1;
            return;
        }

        const nextGroupId = visible[last + 1]?.groupId;
        if (!nextGroupId) return;
        let lastOfNext = last + 1;
        while (lastOfNext < visible.length - 1 && visible[lastOfNext + 1]?.groupId === nextGroupId) lastOfNext++;
        this.selectedVisibleIndex = lastOfNext;
    }

    private toActionItems(): ActionItem[] {
        return this.items.map((item, index) => {
            const groupId = item.groupId || `row:${index}`;
            return {
                ...item,
                groupId,
                action: this.groupAction.get(groupId) ?? item.action,
            };
        });
    }

    private formatAction(action: TreebaseAction): string {
        const label = `[${actionLetter(action)}]`;
        const themed = action === "pick"
            ? this.theme.fg("warning", label)
            : action === "summarize"
              ? this.theme.fg("success", label)
              : this.theme.fg("error", label);
        return this.theme.bold(themed);
    }

    private formatGroupPrefix(position: VisibleActionRow["groupPosition"]): string {
        if (position === "only") return "── ";
        if (position === "first") return "┌─ ";
        if (position === "last") return "└─ ";
        return "│  ";
    }

    private getEntryDisplayText(entry: SessionEntry, isSelected: boolean): string {
        const normalize = (s: string) => s.replace(/[\n\t]/g, " ").trim();
        let result = "";
        switch (entry.type) {
            case "message": {
                const msg = entry.message;
                const role = msg?.role;
                if (role === "user") {
                    result = this.theme.fg("accent", "user: ") + normalize(extractTextContent(msg?.content));
                } else if (role === "assistant") {
                    const content = normalize(extractTextContent(msg?.content));
                    if (content) result = this.theme.fg("success", "assistant: ") + content;
                    else if (msg?.errorMessage) result = this.theme.fg("success", "assistant: ") + this.theme.fg("error", normalize(msg.errorMessage).slice(0, 120));
                    else if (msg?.stopReason === "aborted") result = this.theme.fg("success", "assistant: ") + this.theme.fg("muted", "(aborted)");
                    else result = this.theme.fg("success", "assistant: ") + this.theme.fg("muted", "(no content)");
                } else if (role === "toolResult") {
                    const toolCall = msg?.toolCallId ? this.toolCallMap.get(msg.toolCallId) : undefined;
                    result = this.theme.fg("muted", toolCall ? this.formatToolCall(toolCall.name, toolCall.arguments) : `[${msg?.toolName ?? "tool"}]`);
                } else if (role === "bashExecution") {
                    result = this.theme.fg("dim", `[bash]: ${normalize(String(msg?.command ?? ""))}`);
                } else {
                    result = this.theme.fg("dim", `[${role ?? "message"}]`);
                }
                break;
            }
            case "custom_message": {
                const content = typeof entry.content === "string"
                    ? entry.content
                    : Array.isArray(entry.content)
                      ? entry.content
                          .filter((part: any) => part?.type === "text")
                          .map((part: any) => String(part.text ?? ""))
                          .join("")
                      : "";
                result = `${this.theme.fg("customMessageLabel", `[${entry.customType ?? "custom"}]: `)}${normalize(content)}`;
                break;
            }
            case "branch_summary":
                result = this.theme.fg("warning", "[branch summary]: ") + normalize(String(entry.summary ?? ""));
                break;
            case "compaction":
                result = this.theme.fg("borderAccent", `[compaction: ${Math.round(Number(entry.tokensBefore ?? 0) / 1000)}k tokens]`);
                break;
            default:
                result = this.theme.fg("dim", `[${entry.type ?? "entry"}]`);
        }
        return isSelected ? this.theme.bold(result) : result;
    }

    private formatToolCall(name: string, args: Record<string, unknown>): string {
        const shortenPath = (path: string) => {
            const home = process.env["HOME"] || process.env["USERPROFILE"] || "";
            return home && path.startsWith(home) ? `~${path.slice(home.length)}` : path;
        };
        if (name === "read" || name === "write" || name === "edit") {
            const path = shortenPath(String(args["path"] ?? args["file_path"] ?? ""));
            return `[${name}: ${path}]`;
        }
        if (name === "bash") {
            const command = String(args["command"] ?? "").replace(/[\n\t]/g, " ").trim();
            return `[bash: ${command.slice(0, 50)}${command.length > 50 ? "..." : ""}]`;
        }
        return `[${name}]`;
    }
}

export async function showActionList(
    ctx: ExtensionCommandContext,
    initialItems: ActionItem[],
): Promise<ActionItem[] | null> {
    return (ctx.ui as any).custom((tui: any, theme: any, _kb: any, done: any) => {
        const terminalHeight = tui?.terminal?.rows ?? 40;
        const container = new Container();
        const list = new ActionList(initialItems, done, theme, terminalHeight);

        container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));
        container.addChild(new Text(theme.fg("accent", theme.bold("Treex Actions")), 1, 0));
        container.addChild(
            new Text(
                theme.fg("muted", "Choose what should happen to each group. P = pick, S = summarize, D = drop"),
                1,
                0,
            ),
        );
        container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));
        container.addChild(list);
        container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));

        return {
            render: (width: number) => container.render(width),
            invalidate: () => container.invalidate(),
            handleInput: (data: string) => {
                list.handleInput(data);
                tui.requestRender();
            },
        };
    });
}
