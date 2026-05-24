import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process";
import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as path from "node:path";
import type {
	AgentToolResult,
	AgentToolUpdateCallback,
	ExtensionAPI,
	ExtensionContext,
	OutputMeta,
} from "@oh-my-pi/pi-coding-agent";
import promptText from "./prompt.md" with { type: "text" };

const DEFAULT_TIMEOUT_SECONDS = 300;
const LOOKUP_TIMEOUT_MS = 5000;
const MAX_TIMEOUT_MS = 2_147_483_647;
const UTF8_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;";

const WINDOWS_PWSH_FALLBACK_PATHS = ["C:\\Program Files\\PowerShell\\7\\pwsh.exe"];
const WINDOWS_POWERSHELL_FALLBACK_PATHS = ["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"];
const UNIX_PWSH_FALLBACK_PATHS = ["/opt/homebrew/bin/pwsh", "/usr/local/bin/pwsh", "/usr/bin/pwsh"];

type PwshParams = {
	command: string;
	timeout?: number;
	cwd?: string;
	env?: Record<string, string>;
};

type PwshShellConfig = {
	shellPath: string;
	args: string[];
	prependUtf8Prefix: boolean;
};

type PwshDetails = {
	meta?: OutputMeta;
	exitCode: number | null;
	timedOut: boolean;
	aborted: boolean;
	shellPath?: string;
	cwd: string;
	truncated?: boolean;
	timeoutSeconds?: number;
	requestedTimeoutSeconds?: number;
};

type PiExports = ExtensionAPI["pi"];

const firstExistingPath = (paths: readonly string[]): string | undefined =>
	paths.find(candidate => fs.existsSync(candidate));

const lookupExecutableOnPath = (binary: string): string | undefined => {
	const lookupBinary = process.platform === "win32" ? "where" : "which";
	const result = spawnSync(lookupBinary, [binary], {
		encoding: "utf-8",
		timeout: LOOKUP_TIMEOUT_MS,
	});
	if (result.status !== 0 || !result.stdout) return undefined;
	return result.stdout
		.split(/\r?\n/)
		.map(line => line.trim())
		.find(candidate => candidate.length > 0 && fs.existsSync(candidate));
};

const resolvePwshShellConfig = (): PwshShellConfig => {
	if (process.platform === "win32") {
		const pwshPath =
			firstExistingPath(WINDOWS_PWSH_FALLBACK_PATHS) ??
			lookupExecutableOnPath("pwsh.exe") ??
			lookupExecutableOnPath("pwsh");
		if (pwshPath) {
			return {
				shellPath: pwshPath,
				args: ["-NoProfile", "-NoLogo", "-NonInteractive", "-Command"],
				prependUtf8Prefix: true,
			};
		}

		const powershellPath =
			firstExistingPath(WINDOWS_POWERSHELL_FALLBACK_PATHS) ??
			lookupExecutableOnPath("powershell.exe") ??
			lookupExecutableOnPath("powershell");
		if (powershellPath) {
			return {
				shellPath: powershellPath,
				args: ["-NoProfile", "-NoLogo", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"],
				prependUtf8Prefix: true,
			};
		}

		throw new Error("PowerShell not found. Install pwsh or ensure powershell.exe is available on PATH.");
	}

	const pwshPath = firstExistingPath(UNIX_PWSH_FALLBACK_PATHS) ?? lookupExecutableOnPath("pwsh");
	if (pwshPath) {
		return {
			shellPath: pwshPath,
			args: ["-NoProfile", "-NoLogo", "-NonInteractive", "-Command"],
			prependUtf8Prefix: false,
		};
	}

	throw new Error("pwsh not found on PATH. Install PowerShell from https://github.com/PowerShell/PowerShell");
};

const resolveCwd = async (baseCwd: string, cwd: string | undefined): Promise<string> => {
	const resolved = cwd ? path.resolve(baseCwd, cwd) : baseCwd;
	let stat: fs.Stats;
	try {
		stat = await fsp.stat(resolved);
	} catch {
		throw new Error(`Working directory does not exist: ${resolved}`);
	}
	if (!stat.isDirectory()) throw new Error(`Working directory is not a directory: ${resolved}`);
	return resolved;
};

const buildEnv = (env: Record<string, string> | undefined): NodeJS.ProcessEnv => {
	const pathKey = Object.keys(process.env).find(key => key.toLowerCase() === "path") ?? "PATH";
	const envPathKey = env ? Object.keys(env).find(key => key.toLowerCase() === "path") : undefined;
	const inheritedPath = (envPathKey ? env?.[envPathKey] : undefined) ?? process.env[pathKey] ?? "";
	const ownPath = process.env[pathKey] ?? "";
	const pathEntries = [...new Set([ownPath, inheritedPath].flatMap(value => value.split(path.delimiter).filter(Boolean)))];
	const mergedEnvEntries = Object.entries({ ...process.env, ...env }).filter(([key]) => key.toLowerCase() !== "path");
	return {
		...Object.fromEntries(mergedEnvEntries),
		[pathKey]: pathEntries.join(path.delimiter),
	};
};

const withUtf8Prefix = (command: string, shouldPrefix: boolean): string =>
	shouldPrefix ? `${UTF8_PREFIX}\n${command}` : command;

const enforceWindowsToolPolicy = async (pi: ExtensionAPI): Promise<void> => {
	if (process.platform !== "win32") return;

	const activeTools = pi.getActiveTools();
	const withoutBash = activeTools.filter(name => name !== "bash");
	const nextTools = withoutBash.includes("pwsh") ? withoutBash : [...withoutBash, "pwsh"];
	const unchanged = nextTools.length === activeTools.length && nextTools.every((name, index) => name === activeTools[index]);
	if (!unchanged) await pi.setActiveTools(nextTools);
};

let cachedShellConfig: PwshShellConfig | undefined;

const escapePwshSingleQuotedForDisplay = (value: string): string => value.replaceAll("'", "''");

const formatPwshEnvAssignments = (env: Record<string, string> | undefined): string => {
	if (!env || Object.keys(env).length === 0) return "";
	return Object.entries(env)
		.sort(([a], [b]) => a.localeCompare(b))
		.map(([key, value]) => `$env:${key}='${escapePwshSingleQuotedForDisplay(value)}';`)
		.join(" ");
};

const formatFailureMessage = (
	output: string,
	exitCode: number | null,
	timedOut: boolean,
	aborted: boolean,
	error: Error | undefined,
	timeoutSeconds: number,
): string => {
	if (error) return [output, error.message].filter(Boolean).join("\n\n");
	if (timedOut) return [output, `Command timed out after ${timeoutSeconds} seconds`].filter(Boolean).join("\n\n");
	if (aborted) return [output, "Command aborted"].filter(Boolean).join("\n\n");
	if (exitCode !== 0) return [output, `Command exited with code ${exitCode ?? 1}`].filter(Boolean).join("\n\n");
	return output;
};

const abortResult = (cwd: string): AgentToolResult<PwshDetails> => ({
	content: [{ type: "text", text: "Command aborted" }],
	isError: true,
	details: { exitCode: null, timedOut: false, aborted: true, cwd },
});

const resolveTimeoutMs = (timeoutSeconds: number): number => {
	const timeoutMs = timeoutSeconds * 1000;
	return Math.min(timeoutMs, MAX_TIMEOUT_MS);
};

const terminateProcessTree = (child: ChildProcessWithoutNullStreams): void => {
	if (child.pid === undefined) return;
	if (process.platform === "win32") {
		spawn("taskkill.exe", ["/pid", String(child.pid), "/t", "/f"], {
			stdio: "ignore",
			windowsHide: true,
		}).unref();
		return;
	}
	try {
		process.kill(-child.pid, "SIGTERM");
	} catch {
		child.kill("SIGTERM");
	}
	const killer = setTimeout(() => {
		try {
			process.kill(-child.pid!, "SIGKILL");
		} catch {
			try {
				child.kill("SIGKILL");
			} catch {
				// ignore cleanup races
			}
		}
	}, 1000);
	killer.unref();
};

const executePwsh = async (
	params: PwshParams,
	signal: AbortSignal | undefined,
	onUpdate: AgentToolUpdateCallback<PwshDetails> | undefined,
	ctx: ExtensionContext,
	piExports: PiExports,
): Promise<AgentToolResult<PwshDetails>> => {
	if (signal?.aborted) {
		return abortResult(ctx.cwd);
	}

	const timeoutSeconds =
		params.timeout && Number.isFinite(params.timeout) && params.timeout > 0 ? params.timeout : DEFAULT_TIMEOUT_SECONDS;
	const timeoutMs = resolveTimeoutMs(timeoutSeconds);
	const cwd = await resolveCwd(ctx.cwd, params.cwd);
	const shellConfig = cachedShellConfig ?? (cachedShellConfig = resolvePwshShellConfig());
	const shellCommand = withUtf8Prefix(params.command, shellConfig.prependUtf8Prefix);
	const { id: artifactId, path: artifactPath } = await ctx.sessionManager.allocateArtifactPath("pwsh");
	if (signal?.aborted) return abortResult(cwd);
	const tailBuffer = new piExports.TailBuffer(piExports.DEFAULT_MAX_BYTES);
	const streamUpdate = piExports.streamTailUpdates<PwshDetails>(tailBuffer, onUpdate);
	const sink = new piExports.OutputSink({
		artifactId,
		artifactPath,
		spillThreshold: piExports.DEFAULT_MAX_BYTES,
		onChunk: streamUpdate,
	});

	const { promise, resolve } = Promise.withResolvers<AgentToolResult<PwshDetails>>();
	const child = spawn(shellConfig.shellPath, [...shellConfig.args, shellCommand], {
		cwd,
		env: buildEnv(params.env),
		detached: process.platform !== "win32",
		windowsHide: true,
	});

	let settled = false;
	let timedOut = false;
	let aborted = false;
	const stdoutDecoder = new TextDecoder("utf-8", { ignoreBOM: true });
	const stderrDecoder = new TextDecoder("utf-8", { ignoreBOM: true });

	const onAbort = (): void => {
		aborted = true;
		terminateProcessTree(child);
	};

	const timer = setTimeout(() => {
		timedOut = true;
		terminateProcessTree(child);
	}, timeoutMs);

	const finish = async (exitCode: number | null, error?: Error): Promise<void> => {
		if (settled) return;
		settled = true;
		clearTimeout(timer);
		signal?.removeEventListener("abort", onAbort);
		sink.push(stdoutDecoder.decode());
		sink.push(stderrDecoder.decode());

		const summary = await sink.dump();
		const outputText = formatFailureMessage(summary.output, exitCode, timedOut, aborted, error, timeoutSeconds);
		const isError = Boolean(error || timedOut || aborted || exitCode !== 0);
		const result = piExports.toolResult<PwshDetails>({
			exitCode,
			timedOut,
			aborted,
			shellPath: shellConfig.shellPath,
			cwd,
			truncated: summary.truncated,
			timeoutSeconds,
		})
			.text(outputText)
			.truncationFromSummary(summary, { direction: "tail" })
			.done();
		resolve(isError ? { ...result, isError: true } : result);
	};

	const onChunk = (decoder: TextDecoder, chunk: Buffer): void => {
		const text = decoder.decode(chunk, { stream: true });
		sink.push(text);
	};

	signal?.addEventListener("abort", onAbort, { once: true });
	if (signal?.aborted) onAbort();
	child.stdout?.on("data", chunk => onChunk(stdoutDecoder, chunk));
	child.stderr?.on("data", chunk => onChunk(stderrDecoder, chunk));
	child.on("error", error => {
		void finish(null, error);
	});
	child.on("close", code => {
		void finish(code);
	});

	return await promise;
};

export default function pwshExtension(pi: ExtensionAPI): void {
	const { z } = pi.zod;
	const pwshSchema = z.object({
		command: z.string().describe("PowerShell command to execute"),
		timeout: z.number().optional().describe("Timeout in seconds; defaults to 300"),
		cwd: z.string().optional().describe("Working directory, resolved relative to the session cwd"),
		env: z.record(z.string(), z.string()).optional().describe("Extra environment variables"),
	});

	pi.registerTool({
		name: "pwsh",
		label: "pwsh",
		description: promptText,
		parameters: pwshSchema,
		defaultInactive: process.platform !== "win32",
		async execute(_toolCallId, params, signal, onUpdate, ctx) {
			return await executePwsh(params, signal, onUpdate, ctx, pi.pi);
		},
		renderCall(args, _options, theme) {
			const command = args.command.length > 0 ? args.command : "...";
			const envPrefix = formatPwshEnvAssignments(args.env);
			const displayCommand = [envPrefix, command].filter(Boolean).join(" ");
			const timeout =
				typeof args.timeout === "number" && Number.isFinite(args.timeout) ? theme.fg("muted", ` (${args.timeout}s)`) : "";
			return new pi.pi.Text(theme.fg("toolTitle", theme.bold(`PS> ${displayCommand}`)) + timeout, 0, 0);
		},
	});

	pi.on("session_start", async () => {
		await enforceWindowsToolPolicy(pi);
	});

	pi.on("before_agent_start", async () => {
		await enforceWindowsToolPolicy(pi);
	});
}
