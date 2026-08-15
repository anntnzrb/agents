export type TreexMessage = {
  role?: string;
  content?: unknown;
  toolName?: string;
  toolCallId?: string;
  stopReason?: string;
  errorMessage?: string;
  command?: string;
  [key: string]: unknown;
};

export type SessionEntry = {
  id: string;
  parentId?: string | null;
  type?: string;
  message?: TreexMessage;
  customType?: string;
  content?: unknown;
  summary?: string;
  tokensBefore?: number;
  modelId?: string;
  thinkingLevel?: string;
  [key: string]: unknown;
};

export type TreexSessionManager = {
  getEntry(id: string): SessionEntry | undefined;
  getBranch(leafId: string): SessionEntry[];
};

export type TreeNode = {
  entry: SessionEntry;
  children: TreeNode[];
  label?: string;
  labelTimestamp?: string;
};

export type TreebaseAction = "pick" | "summarize" | "drop";

export type ActionItem = {
  id: string;
  entry: SessionEntry;
  action: TreebaseAction;
  groupId: string;
  depth: number;
};

export function isAncestor(
  sessionManager: TreexSessionManager,
  ancestorId: string | null,
  descendantId: string | null,
): boolean {
  if (ancestorId === null) return true;
  if (!ancestorId || !descendantId) return false;
  let current = sessionManager.getEntry(descendantId);
  while (current) {
    if (current.id === ancestorId) return true;
    current = current.parentId
      ? sessionManager.getEntry(current.parentId)
      : undefined;
  }
  return false;
}

export function entriesBetweenAncestorAndLeaf(
  sessionManager: TreexSessionManager,
  ancestorId: string,
  leafId: string,
): SessionEntry[] {
  const branch = sessionManager.getBranch(leafId);
  const start = branch.findIndex((entry) => entry.id === ancestorId);
  return start >= 0 ? branch.slice(start) : [];
}

export function parentOf(
  sessionManager: TreexSessionManager,
  entryId: string,
): string | null {
  return sessionManager.getEntry(entryId)?.parentId ?? null;
}

export function actionLetter(action: TreebaseAction): string {
  switch (action) {
    case "pick":
      return "P";
    case "summarize":
      return "S";
    case "drop":
      return "D";
  }
}

export function isTreebaseActionableEntry(entry: SessionEntry): boolean {
  switch (entry.type) {
    case "message":
    case "custom_message":
    case "branch_summary":
    case "compaction":
      return true;
    case "thinking_level_change":
    case "model_change":
    case "label":
    case "session_info":
    case "custom":
      return false;
    default:
      return false;
  }
}

export function filterActionableEntries(
  entries: SessionEntry[],
): SessionEntry[] {
  return entries.filter(isTreebaseActionableEntry);
}

export function makeActionItems(entries: SessionEntry[]): ActionItem[] {
  const actionableEntries = filterActionableEntries(entries);
  let turn = 0;
  let assistantGroupId: string | null = null;

  return actionableEntries.map((entry) => {
    const role = entry.type === "message" ? entry.message?.role : entry.type;
    let groupId: string;

    if (role === "user") {
      turn++;
      assistantGroupId = null;
      groupId = `turn-${turn}-user`;
    } else if (role === "assistant" || role === "toolResult") {
      if (!assistantGroupId) {
        if (turn === 0) turn++;
        assistantGroupId = `turn-${turn}-assistant`;
      }
      groupId = assistantGroupId;
    } else {
      if (turn === 0) turn++;
      assistantGroupId = null;
      groupId = `turn-${turn}-${entry.type ?? "entry"}-${entry.id}`;
    }

    return { id: entry.id, entry, action: "summarize", groupId, depth: 0 };
  });
}

export function setGroupAction(
  items: ActionItem[],
  groupId: string,
  action: TreebaseAction,
): ActionItem[] {
  return items.map((item) =>
    item.groupId === groupId ? { ...item, action } : item,
  );
}
