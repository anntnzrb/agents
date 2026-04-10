import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const REQUIRED_TOOLS = ["grep", "find"] as const;

const unique = (names: readonly string[]): string[] => Array.from(new Set(names));

const withRequiredTools = (names: readonly string[]): string[] =>
	unique([...names, ...REQUIRED_TOOLS]);

export default function builtInsExtension(pi: ExtensionAPI) {
	const ensureSearchTools = () => {
		const activeNames = pi.getActiveTools().map((tool) => tool.name);
		const nextNames = withRequiredTools(activeNames);
		if (nextNames.length !== activeNames.length) {
			pi.setActiveTools(nextNames);
		}
	};

	pi.on("session_start", () => {
		ensureSearchTools();
	});
}
