import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type TextPart = {
  type: string;
  text?: string;
};

export const ensureToolActive = (pi: ExtensionAPI, toolName: string): void => {
  const nextTools = new Set(pi.getActiveTools());
  if (nextTools.has(toolName)) return;
  nextTools.add(toolName);
  pi.setActiveTools(Array.from(nextTools));
};

export const summarizeList = (items: string[], max = 2): string => {
  if (items.length <= max) return items.join(", ");
  return `${items.slice(0, max).join(", ")} +${items.length - max} more`;
};

export const getFirstTextContent = (content: readonly TextPart[]): string => {
  for (const part of content) {
    if (part.type === "text") return part.text ?? "";
  }
  return "";
};
