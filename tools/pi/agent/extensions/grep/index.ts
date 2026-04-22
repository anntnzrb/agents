import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const ensureToolActive = (pi: ExtensionAPI, toolName: string): void => {
	const nextTools = new Set(pi.getActiveTools());
	if (nextTools.has(toolName)) return;
	nextTools.add(toolName);
	pi.setActiveTools(Array.from(nextTools));
};

export default function grepExtension(pi: ExtensionAPI) {
	const activate = () => ensureToolActive(pi, "grep");
	pi.on("session_start", activate);
	pi.on("session_tree", activate);
}
