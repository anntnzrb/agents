import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@mariozechner/pi-coding-agent";
import os from "node:os";
import path from "node:path";
import fs from "node:fs/promises";

export function formatUsd(cost: number): string {
	if (!Number.isFinite(cost) || cost <= 0) return "$0.00";
	if (cost >= 1) return `$${cost.toFixed(2)}`;
	if (cost >= 0.1) return `$${cost.toFixed(3)}`;
	return `$${cost.toFixed(4)}`;
}

export function estimateTokens(text: string): number {
	return Math.max(0, Math.ceil(text.length / 4));
}

export function normalizeReadPath(inputPath: string, cwd: string): string {
	let p = inputPath;
	if (p.startsWith("@")) p = p.slice(1);
	if (p === "~") p = os.homedir();
	else if (p.startsWith("~/")) p = path.join(os.homedir(), p.slice(2));
	if (!path.isAbsolute(p)) p = path.resolve(cwd, p);
	return path.resolve(p);
}

function getAgentDir(): string {
	const envCandidates = ["PI_CODING_AGENT_DIR", "TAU_CODING_AGENT_DIR"];
	let envDir: string | undefined;
	for (const k of envCandidates) {
		if (process.env[k]) {
			envDir = process.env[k];
			break;
		}
	}
	if (!envDir) {
		for (const [k, v] of Object.entries(process.env)) {
			if (k.endsWith("_CODING_AGENT_DIR") && v) {
				envDir = v;
				break;
			}
		}
	}

	if (envDir) {
		if (envDir === "~") return os.homedir();
		if (envDir.startsWith("~/")) return path.join(os.homedir(), envDir.slice(2));
		return envDir;
	}
	return path.join(os.homedir(), ".pi", "agent");
}

async function readFileIfExists(filePath: string): Promise<{ path: string; content: string; bytes: number } | null> {
	try {
		const buf = await fs.readFile(filePath);
		return { path: filePath, content: buf.toString("utf8"), bytes: buf.byteLength };
	} catch {
		return null;
	}
}

export async function loadProjectContextFiles(cwd: string): Promise<Array<{ path: string; tokens: number; bytes: number }>> {
	const out: Array<{ path: string; tokens: number; bytes: number }> = [];
	const seen = new Set<string>();

	const loadFromDir = async (dir: string) => {
		for (const name of ["AGENTS.md", "CLAUDE.md"]) {
			const p = path.join(dir, name);
			const f = await readFileIfExists(p);
			if (f && !seen.has(f.path)) {
				seen.add(f.path);
				out.push({ path: f.path, tokens: estimateTokens(f.content), bytes: f.bytes });
				return;
			}
		}
	};

	await loadFromDir(getAgentDir());

	const stack: string[] = [];
	let current = path.resolve(cwd);
	while (true) {
		stack.push(current);
		const parent = path.resolve(current, "..");
		if (parent === current) break;
		current = parent;
	}
	stack.reverse();
	for (const dir of stack) await loadFromDir(dir);

	return out;
}

export function normalizeSkillName(name: string): string {
	return name.startsWith("skill:") ? name.slice("skill:".length) : name;
}

export type SkillIndexEntry = {
	name: string;
	skillFilePath: string;
	skillDir: string;
};

export function buildSkillIndex(pi: ExtensionAPI, cwd: string): SkillIndexEntry[] {
	return pi
		.getCommands()
		.filter((c) => c.sourceInfo?.source === "skill")
		.map((c) => {
			const p = c.sourceInfo?.path ? normalizeReadPath(c.sourceInfo.path, cwd) : "";
			return {
				name: normalizeSkillName(c.name),
				skillFilePath: p,
				skillDir: p ? path.dirname(p) : "",
			};
		})
		.filter((x) => x.name && x.skillDir);
}

export const SKILL_LOADED_ENTRY = "context:skill_loaded";

export type SkillLoadedEntryData = {
	name: string;
	path: string;
};

export function getLoadedSkillsFromSession(ctx: ExtensionContext): Set<string> {
	const out = new Set<string>();
	for (const e of ctx.sessionManager.getEntries()) {
		if (e?.type !== "custom") continue;
		if (e?.customType !== SKILL_LOADED_ENTRY) continue;
		const data = e?.data as SkillLoadedEntryData | undefined;
		if (data?.name) out.add(data.name);
	}
	return out;
}

function extractCostTotal(usage: unknown): number {
	if (!usage || typeof usage !== "object") return 0;
	const value = usage as { cost?: unknown };
	const c = value.cost;
	if (typeof c === "number") return Number.isFinite(c) ? c : 0;
	if (typeof c === "string") {
		const n = Number(c);
		return Number.isFinite(n) ? n : 0;
	}
	if (c && typeof c === "object") {
		const nested = c as { total?: unknown };
		const t = nested.total;
		if (typeof t === "number") return Number.isFinite(t) ? t : 0;
		if (typeof t === "string") {
			const n = Number(t);
			return Number.isFinite(n) ? n : 0;
		}
	}
	return 0;
}

export function sumSessionUsage(ctx: ExtensionCommandContext): {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	totalTokens: number;
	totalCost: number;
} {
	let input = 0;
	let output = 0;
	let cacheRead = 0;
	let cacheWrite = 0;
	let totalCost = 0;

	for (const entry of ctx.sessionManager.getEntries()) {
		if (entry?.type !== "message") continue;
		const msg = entry.message;
		if (!msg || msg.role !== "assistant") continue;
		const usage = msg.usage;
		if (!usage) continue;
		input += Number(usage.inputTokens ?? 0) || 0;
		output += Number(usage.outputTokens ?? 0) || 0;
		cacheRead += Number(usage.cacheRead ?? 0) || 0;
		cacheWrite += Number(usage.cacheWrite ?? 0) || 0;
		totalCost += extractCostTotal(usage);
	}

	return {
		input,
		output,
		cacheRead,
		cacheWrite,
		totalTokens: input + output + cacheRead + cacheWrite,
		totalCost,
	};
}

export function shortenPath(p: string, cwd: string): string {
	const rp = path.resolve(p);
	const rc = path.resolve(cwd);
	if (rp === rc) return ".";
	if (rp.startsWith(rc + path.sep)) return "./" + rp.slice(rc.length + 1);
	return rp;
}

export function renderUsageBar(
	theme: { fg: (token: string, text: string) => string },
	parts: { system: number; tools: number; convo: number; remaining: number },
	total: number,
	width: number,
): string {
	const w = Math.max(10, width);
	if (total <= 0) return "";

	const toCols = (n: number) => Math.round((n / total) * w);
	let sys = toCols(parts.system);
	let tools = toCols(parts.tools);
	let con = toCols(parts.convo);
	let rem = w - sys - tools - con;
	if (rem < 0) rem = 0;
	while (sys + tools + con + rem < w) rem++;
	while (sys + tools + con + rem > w && rem > 0) rem--;

	const block = "█";
	const sysStr = theme.fg("accent", block.repeat(sys));
	const toolsStr = theme.fg("warning", block.repeat(tools));
	const conStr = theme.fg("success", block.repeat(con));
	const remStr = theme.fg("dim", block.repeat(rem));
	return `${sysStr}${toolsStr}${conStr}${remStr}`;
}

export function joinComma(items: string[]): string {
	return items.join(", ");
}

export function joinCommaStyled(items: string[], renderItem: (item: string) => string, sep: string): string {
	return items.map(renderItem).join(sep);
}

export type ContextViewData = {
	usage:
		| {
			messageTokens: number;
			contextWindow: number;
			effectiveTokens: number;
			percent: number;
			remainingTokens: number;
			systemPromptTokens: number;
			agentTokens: number;
			toolsTokens: number;
			activeTools: number;
		}
		| null;
	agentFiles: string[];
	extensions: string[];
	skills: string[];
	loadedSkills: string[];
	session: { totalTokens: number; totalCost: number };
};
