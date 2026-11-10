// smolui: display-only trims for built-in tool cards in the interactive TUI.
// Headless runs (print, json, rpc, ACP) render no transcript, so this entry
// stays a bare gate: the renderer code is imported only once a TUI session
// starts.
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		// Dynamic import on purpose: headless modes must never load the renderer code.
		const { install, missing } = await import("./install.ts");
		install();
		// A renamed or removed built-in leaves its card stock; say so instead of drifting silently.
		const gone = missing();
		if (gone.length > 0) ctx.ui.notify(`smolui: no omp renderer for ${gone.join(", ")}; those cards stay stock`, "warning");
	});
}
