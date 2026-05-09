/**
 * /context
 *
 * Small TUI view showing what's loaded/available:
 * - extensions (best-effort from registered extension slash commands)
 * - skills
 * - project context files (AGENTS.md / CLAUDE.md)
 * - current context window usage + session totals (tokens/cost)
 */

import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext, ToolResultEvent } from "@earendil-works/pi-coding-agent";
import { DynamicBorder } from "@earendil-works/pi-coding-agent";
import { Container, Key, Text, matchesKey, type Component, type TUI } from "@earendil-works/pi-tui";
import path from "node:path";
import {
	buildSkillIndex,
	formatUsd,
	getLoadedSkillsFromSession,
	joinComma,
	joinCommaStyled,
	loadProjectContextFiles,
	normalizeReadPath,
	normalizeSkillName,
	renderUsageBar,
	shortenPath,
	SKILL_LOADED_ENTRY,
	sumSessionUsage,
	type ContextViewData,
	type SkillIndexEntry,
	type SkillLoadedEntryData,
	estimateTokens,
} from "./utils.js";

class ContextView implements Component {
	private theme: any;
	private onDone: () => void;
	private data: ContextViewData;
	private container: Container;
	private body: Text;
	private cachedWidth: number | undefined;

	constructor(_tui: TUI, theme: any, data: ContextViewData, onDone: () => void) {
		this.theme = theme;
		this.data = data;
		this.onDone = onDone;

		this.container = new Container();
		this.container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));
		this.container.addChild(
			new Text(
				theme.fg("accent", theme.bold("Context")) + theme.fg("dim", "  (Esc/q/Enter to close)"),
				1,
				0,
			),
		);
		this.container.addChild(new Text("", 1, 0));

		this.body = new Text("", 1, 0);
		this.container.addChild(this.body);

		this.container.addChild(new Text("", 1, 0));
		this.container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));
	}

	private rebuild(width: number): void {
		const muted = (s: string) => this.theme.fg("muted", s);
		const dim = (s: string) => this.theme.fg("dim", s);
		const text = (s: string) => this.theme.fg("text", s);

		const lines: string[] = [];

		// Window + bar
		if (!this.data.usage) {
			lines.push(muted("Window: ") + dim("(unknown)"));
		} else {
			const u = this.data.usage;
			lines.push(
				muted("Window: ") +
					text(`~${u.effectiveTokens.toLocaleString()} / ${u.contextWindow.toLocaleString()}`) +
					muted(`  (${u.percent.toFixed(1)}% used, ~${u.remainingTokens.toLocaleString()} left)`),
			);

			// bar width tries to fit within the viewport
			const barWidth = Math.max(10, Math.min(36, width - 10));

			// Prorate system prompt into current message context estimate, then add tools estimate.
			const sysInMessages = Math.min(u.systemPromptTokens, u.messageTokens);
			const convoInMessages = Math.max(0, u.messageTokens - sysInMessages);
			const bar =
				renderUsageBar(
					this.theme,
					{
						system: sysInMessages,
						tools: u.toolsTokens,
						convo: convoInMessages,
						remaining: u.remainingTokens,
					},
					u.contextWindow,
					barWidth,
				) +
				" " +
				dim("sys") +
				this.theme.fg("accent", "█") +
				" " +
				dim("tools") +
				this.theme.fg("warning", "█") +
				" " +
				dim("convo") +
				this.theme.fg("success", "█") +
				" " +
				dim("free") +
				this.theme.fg("dim", "█");
			lines.push(bar);
		}

		lines.push("");

		// System prompt + tools totals (approx)
		if (this.data.usage) {
			const u = this.data.usage;
			lines.push(
				muted("System: ") +
					text(`~${u.systemPromptTokens.toLocaleString()} tok`) +
					muted(` (AGENTS ~${u.agentTokens.toLocaleString()})`),
			);
			lines.push(
				muted("Tools: ") +
					text(`~${u.toolsTokens.toLocaleString()} tok`) +
					muted(` (${u.activeTools} active)`),
			);
		}

		lines.push(muted(`AGENTS (${this.data.agentFiles.length}): `) + text(this.data.agentFiles.length ? joinComma(this.data.agentFiles) : "(none)"));
		lines.push("");
		lines.push(muted(`Extensions (${this.data.extensions.length}): `) + text(this.data.extensions.length ? joinComma(this.data.extensions) : "(none)"));

		const loaded = new Set(this.data.loadedSkills);
		const skillsRendered = this.data.skills.length
			? joinCommaStyled(
					this.data.skills,
					(name) => (loaded.has(name) ? this.theme.fg("success", name) : this.theme.fg("muted", name)),
					this.theme.fg("muted", ", "),
				)
			: "(none)";
		lines.push(muted(`Skills (${this.data.skills.length}): `) + skillsRendered);
		lines.push("");
		lines.push(
			muted("Session: ") +
				text(`${this.data.session.totalTokens.toLocaleString()} tokens`) +
				muted(" · ") +
				text(formatUsd(this.data.session.totalCost)),
		);

		this.body.setText(lines.join("\n"));
		this.cachedWidth = width;
	}

	handleInput(data: string): void {
		if (
			matchesKey(data, Key.escape) ||
			matchesKey(data, Key.ctrl("c")) ||
			data.toLowerCase() === "q" ||
			data === "\r"
		) {
			this.onDone();
			return;
		}
	}

	invalidate(): void {
		this.container.invalidate();
		this.cachedWidth = undefined;
	}

	render(width: number): string[] {
		if (this.cachedWidth !== width) this.rebuild(width);
		return this.container.render(width);
	}
}

export default function contextExtension(pi: ExtensionAPI) {
	// Track which skills were actually pulled in via read tool calls.
	let lastSessionId: string | null = null;
	let cachedLoadedSkills = new Set<string>();
	let cachedSkillIndex: SkillIndexEntry[] = [];

	const ensureCaches = (ctx: ExtensionContext) => {
		const sid = ctx.sessionManager.getSessionId();
		if (sid !== lastSessionId) {
			lastSessionId = sid;
			cachedLoadedSkills = getLoadedSkillsFromSession(ctx);
			cachedSkillIndex = buildSkillIndex(pi, ctx.cwd);
		}
		if (cachedSkillIndex.length === 0) {
			cachedSkillIndex = buildSkillIndex(pi, ctx.cwd);
		}
	};

	const matchSkillForPath = (absPath: string): string | null => {
		let best: SkillIndexEntry | null = null;
		for (const s of cachedSkillIndex) {
			if (!s.skillDir) continue;
			if (absPath === s.skillFilePath || absPath.startsWith(s.skillDir + path.sep)) {
				if (!best || s.skillDir.length > best.skillDir.length) best = s;
			}
		}
		return best?.name ?? null;
	};

	pi.on("tool_result", (event: ToolResultEvent, ctx: ExtensionContext) => {
		// Only count successful reads.
		if ((event as any).toolName !== "read") return;
		if ((event as any).isError) return;

		const input = (event as any).input as { path?: unknown } | undefined;
		const p = typeof input?.path === "string" ? input.path : "";
		if (!p) return;

		ensureCaches(ctx);
		const abs = normalizeReadPath(p, ctx.cwd);
		const skillName = matchSkillForPath(abs);
		if (!skillName) return;

		if (!cachedLoadedSkills.has(skillName)) {
			cachedLoadedSkills.add(skillName);
			pi.appendEntry<SkillLoadedEntryData>(SKILL_LOADED_ENTRY, { name: skillName, path: abs });
		}
	});

	pi.registerCommand("context", {
		description: "Show loaded context overview",
		handler: async (_args: string[], ctx: ExtensionCommandContext) => {
			const commands = pi.getCommands();
			const extensionCmds = commands.filter((c) => c.sourceInfo?.source === "extension");
			const skillCmds = commands.filter((c) => c.sourceInfo?.source === "skill");

			const extensionsByPath = new Map<string, string[]>();
			for (const c of extensionCmds) {
				const p = c.sourceInfo?.path ?? "<unknown>";
				const arr = extensionsByPath.get(p) ?? [];
				arr.push(c.name);
				extensionsByPath.set(p, arr);
			}
			const extensionFiles = [...extensionsByPath.keys()]
				.map((p) => (p === "<unknown>" ? p : path.basename(p)))
				.sort((a, b) => a.localeCompare(b));

			const skills = skillCmds
				.map((c) => normalizeSkillName(c.name))
				.sort((a, b) => a.localeCompare(b));

			const agentFiles = await loadProjectContextFiles(ctx.cwd);
			const agentFilePaths = agentFiles.map((f) => shortenPath(f.path, ctx.cwd));
			const agentTokens = agentFiles.reduce((a, f) => a + f.tokens, 0);

			const systemPrompt = ctx.getSystemPrompt();
			const systemPromptTokens = systemPrompt ? estimateTokens(systemPrompt) : 0;

			const usage = ctx.getContextUsage();
			const messageTokens = usage?.tokens ?? 0;
			const ctxWindow = usage?.contextWindow ?? 0;

			// Tool definitions are not part of ctx.getContextUsage() (it estimates message tokens).
			// We approximate their token impact from tool name + description, and apply a fudge
			// factor to account for parameters/schema/formatting.
			const TOOL_FUDGE = 1.5;
			const activeToolNames = pi.getActiveTools();
			const toolInfoByName = new Map(pi.getAllTools().map((t) => [t.name, t] as const));
			let toolsTokens = 0;
			for (const name of activeToolNames) {
				const info = toolInfoByName.get(name);
				const blob = `${name}\n${info?.description ?? ""}`;
				toolsTokens += estimateTokens(blob);
			}
			toolsTokens = Math.round(toolsTokens * TOOL_FUDGE);

			const effectiveTokens = messageTokens + toolsTokens;
			const percent = ctxWindow > 0 ? (effectiveTokens / ctxWindow) * 100 : 0;
			const remainingTokens = ctxWindow > 0 ? Math.max(0, ctxWindow - effectiveTokens) : 0;

			const sessionUsage = sumSessionUsage(ctx);

			const makePlainText = () => {
				const lines: string[] = [];
				lines.push("Context");
				if (usage) {
					lines.push(
						`Window: ~${effectiveTokens.toLocaleString()} / ${ctxWindow.toLocaleString()} (${percent.toFixed(1)}% used, ~${remainingTokens.toLocaleString()} left)`,
					);
				} else {
					lines.push("Window: (unknown)");
				}
				lines.push(`System: ~${systemPromptTokens.toLocaleString()} tok (AGENTS ~${agentTokens.toLocaleString()})`);
				lines.push(`Tools: ~${toolsTokens.toLocaleString()} tok (${activeToolNames.length} active)`);
				lines.push(`AGENTS: ${agentFilePaths.length ? joinComma(agentFilePaths) : "(none)"}`);
				lines.push(`Extensions (${extensionFiles.length}): ${extensionFiles.length ? joinComma(extensionFiles) : "(none)"}`);
				lines.push(`Skills (${skills.length}): ${skills.length ? joinComma(skills) : "(none)"}`);
				lines.push(`Session: ${sessionUsage.totalTokens.toLocaleString()} tokens · ${formatUsd(sessionUsage.totalCost)}`);
				return lines.join("\n");
			};

			if (!ctx.hasUI) {
				pi.sendMessage({ customType: "context", content: makePlainText(), display: true }, { triggerTurn: false });
				return;
			}

			const loadedSkills = Array.from(getLoadedSkillsFromSession(ctx)).sort((a, b) => a.localeCompare(b));

			const viewData: ContextViewData = {
				usage: usage
					? {
						messageTokens,
						contextWindow: ctxWindow,
						effectiveTokens,
						percent,
						remainingTokens,
						systemPromptTokens,
						agentTokens,
						toolsTokens,
						activeTools: activeToolNames.length,
					}
					: null,
				agentFiles: agentFilePaths,
				extensions: extensionFiles,
				skills,
				loadedSkills,
				session: { totalTokens: sessionUsage.totalTokens, totalCost: sessionUsage.totalCost },
			};

			await ctx.ui.custom<ContextView>((tui: TUI, theme: any, _kb: unknown, done: () => void) => {
				return new ContextView(tui, theme, viewData, done);
			});
		},
	});
}
