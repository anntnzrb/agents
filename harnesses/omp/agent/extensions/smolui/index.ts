// smolui: display-only trims for built-in tool cards in the interactive TUI.
// Headless runs (print, json, rpc, ACP) render no transcript, so this entry
// stays a bare gate: the renderer code is imported only once a TUI session
// starts.
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		// Dynamic import on purpose: headless modes must never load the renderer code.
		const { install } = await import("./install.ts");
		install();
	});
}
