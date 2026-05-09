import { existsSync } from "node:fs";
import { delimiter } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	createBashToolDefinition,
	type BashOperations,
	type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "@sinclair/typebox";

const LOOKUP_TIMEOUT_MS = 5000;

const pwshSchema = Type.Object({
	command: Type.String({ description: "PowerShell command" }),
	timeout: Type.Optional(Type.Number({ description: "Timeout seconds (optional; no default)" })),
});

const WINDOWS_PWSH_FALLBACK_PATHS = ["C:\\Program Files\\PowerShell\\7\\pwsh.exe"];
const WINDOWS_POWERSHELL_FALLBACK_PATHS = ["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"];

const UNIX_PWSH_FALLBACK_PATHS = ["/usr/local/bin/pwsh", "/opt/homebrew/bin/pwsh", "/usr/bin/pwsh"];

type PwshShellConfig = {
	shellPath: string;
	args: string[];
	prependUtf8Prefix: boolean;
};

const firstExistingPath = (paths: readonly string[]): string | undefined =>
	paths.find((path) => existsSync(path));

const withPathPrepended = (baseEnv: NodeJS.ProcessEnv): NodeJS.ProcessEnv => {
	const pathKey = Object.keys(process.env).find((key) => key.toLowerCase() === "path") ?? "PATH";
	const inheritedPath = baseEnv[pathKey] ?? process.env[pathKey] ?? "";
	const ownPath = process.env[pathKey] ?? "";
	const pathEntries = [...new Set([ownPath, inheritedPath].flatMap((value) => value.split(delimiter).filter(Boolean)))];
	return {
		...process.env,
		...baseEnv,
		[pathKey]: pathEntries.join(delimiter),
	};
};

// Cold-path: spawnSync for binary lookup is cached after first call.
// Per AGENTS.md event-loop hygiene: acceptable because it runs once and is memoized.
const lookupExecutableOnPath = (binary: string): string | undefined => {
	if (process.platform === "win32") {
		// Cold-path: see above.
		const result = spawnSync("where", [binary], {
			encoding: "utf-8",
			timeout: LOOKUP_TIMEOUT_MS,
		});
		if (result.status !== 0 || !result.stdout) return undefined;
		const candidates = result.stdout
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean);
		return candidates.find((candidate) => existsSync(candidate));
	}

	// Cold-path: see above.
	const result = spawnSync("which", [binary], {
		encoding: "utf-8",
		timeout: LOOKUP_TIMEOUT_MS,
	});
	if (result.status !== 0 || !result.stdout) return undefined;
	return result.stdout.split(/\r?\n/)[0]?.trim() || undefined;
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

	const pwshPath =
		firstExistingPath(UNIX_PWSH_FALLBACK_PATHS) ??
		lookupExecutableOnPath("pwsh");
	if (pwshPath) {
		return {
			shellPath: pwshPath,
			args: ["-NoProfile", "-NoLogo", "-NonInteractive", "-Command"],
			prependUtf8Prefix: false,
		};
	}

	throw new Error("pwsh not found on PATH. Install PowerShell from https://github.com/PowerShell/PowerShell");
};

const withUtf8Prefix = (command: string, shouldPrefix: boolean): string => {
	if (!shouldPrefix) return command;
	const prefix = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;";
	return `${prefix}\n${command}`;
};

const createLocalPwshOperations = (): BashOperations => {
	let cachedShellConfig: PwshShellConfig | undefined;

	return {
		exec: (command, cwd, { onData, signal, timeout, env }) => {
			return new Promise((resolve, reject) => {
				if (!existsSync(cwd)) {
					reject(new Error(`Working directory does not exist: ${cwd}\nCannot execute PowerShell commands.`));
					return;
				}
				if (signal?.aborted) {
					reject(new Error("aborted"));
					return;
				}

				const shellConfig = cachedShellConfig ?? (cachedShellConfig = resolvePwshShellConfig());
				const shellCommand = withUtf8Prefix(command, shellConfig.prependUtf8Prefix);

				const child = spawn(shellConfig.shellPath, [...shellConfig.args, shellCommand], {
					cwd,
					env: withPathPrepended(env ?? process.env),
					windowsHide: true,
				});

				let settled = false;
				let timedOut = false;
				let timeoutTimer: ReturnType<typeof setTimeout> | undefined;

				if (timeout && timeout > 0) {
					timeoutTimer = setTimeout(() => {
						timedOut = true;
						child.kill("SIGTERM");
					}, timeout * 1000);
				}

				const onAbort = () => {
					child.kill("SIGTERM");
				};
				signal?.addEventListener("abort", onAbort, { once: true });

				child.stdout?.on("data", (chunk: Buffer) => {
					onData(chunk);
				});
				child.stderr?.on("data", (chunk: Buffer) => {
					onData(chunk);
				});

				child.on("error", (error: Error) => {
					settled = true;
					signal?.removeEventListener("abort", onAbort);
					if (timeoutTimer) clearTimeout(timeoutTimer);
					reject(error);
				});

				child.on("close", (code: number | null) => {
					signal?.removeEventListener("abort", onAbort);
					if (timeoutTimer) clearTimeout(timeoutTimer);
					if (settled) return;
					if (timedOut) {
						reject(new Error(`timeout:${timeout}`));
						return;
					}
					if (signal?.aborted) {
						reject(new Error("aborted"));
						return;
					}
					resolve({ exitCode: code ?? 1 });
				});
			});
		},
	};
};

const enforceWindowsToolPolicy = (pi: ExtensionAPI): void => {
	if (process.platform !== "win32") return;

	const activeTools = pi.getActiveTools();
	const withoutBash = activeTools.filter((name) => name !== "bash");
	const nextTools = withoutBash.includes("pwsh") ? withoutBash : [...withoutBash, "pwsh"];
	const unchanged = nextTools.length === activeTools.length && nextTools.every((name, index) => name === activeTools[index]);
	if (!unchanged) {
		pi.setActiveTools(nextTools);
	}
};

export default function pwshExtension(pi: ExtensionAPI): void {
	const cwd = process.cwd();
	const baseTool = createBashToolDefinition(cwd, {
		operations: createLocalPwshOperations(),
	});

	pi.registerTool({
		...baseTool,
		name: "pwsh",
		label: "pwsh",
		parameters: pwshSchema,
		description: `Execute PowerShell in current working directory. Returns stdout/stderr. Output truncated to last ${DEFAULT_MAX_LINES} lines or ${Math.trunc(DEFAULT_MAX_BYTES / 1024)}KB, whichever hits first; full truncated output saved to temp file. Optional timeout seconds.`,
		promptSnippet: "Execute PowerShell commands (Get-ChildItem, Select-String, etc.)",
		promptGuidelines: [
			"Use pwsh for Windows-native shell tasks and PowerShell syntax; not bash syntax.",
			"Quote-heavy commands: prefer here-strings or temp .ps1 scripts; use ${var} near punctuation; regex backslashes as '\\\\'.",
		],
		renderCall: (args, theme) => {
			const command = typeof args.command === "string" && args.command.length > 0 ? args.command : "...";
			const timeout = typeof args.timeout === "number" && Number.isFinite(args.timeout) ? args.timeout : undefined;
			const timeoutSuffix = timeout ? theme.fg("muted", ` (timeout ${timeout}s)`) : "";
			return new Text(theme.fg("toolTitle", theme.bold(`PS> ${command}`)) + timeoutSuffix, 0, 0);
		},
	});

	pi.on("session_start", async () => {
		enforceWindowsToolPolicy(pi);
	});

	pi.on("before_agent_start", async () => {
		enforceWindowsToolPolicy(pi);
	});
}
