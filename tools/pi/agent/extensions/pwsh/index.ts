import { existsSync } from "node:fs";
import { delimiter } from "node:path";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	createBashToolDefinition,
	type BashOperations,
	type ExtensionAPI,
} from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";

const LOOKUP_TIMEOUT_MS = 5000;
const EXIT_STDIO_GRACE_MS = 100;

const pwshSchema = Type.Object({
	command: Type.String({ description: "PowerShell command to execute" }),
	timeout: Type.Optional(Type.Number({ description: "Timeout in seconds (optional, no default timeout)" })),
});

const WINDOWS_PWSH_FALLBACK_PATHS = [
	"C:\\Program Files\\PowerShell\\7\\pwsh.exe",
];

const WINDOWS_POWERSHELL_FALLBACK_PATHS = [
	"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
];

const UNIX_PWSH_FALLBACK_PATHS = ["/usr/local/bin/pwsh", "/opt/homebrew/bin/pwsh", "/usr/bin/pwsh"];

type PwshShellConfig = {
	shellPath: string;
	args: string[];
	prependUtf8Prefix: boolean;
};

const firstExistingPath = (paths: readonly string[]): string | undefined =>
	paths.find((path) => existsSync(path));

const getPathKey = (): string =>
	Object.keys(process.env).find((key) => key.toLowerCase() === "path") ?? "PATH";

const withPathPrepended = (baseEnv: NodeJS.ProcessEnv): NodeJS.ProcessEnv => {
	const pathKey = getPathKey();
	const inheritedPath = baseEnv[pathKey] ?? process.env[pathKey] ?? "";
	const ownPath = process.env[pathKey] ?? "";
	const pathEntries = [...new Set([ownPath, inheritedPath].flatMap((value) => value.split(delimiter).filter(Boolean)))];
	return {
		...process.env,
		...baseEnv,
		[pathKey]: pathEntries.join(delimiter),
	};
};

const lookupExecutableOnPath = (binary: string): string | undefined => {
	if (process.platform === "win32") {
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

	const result = spawnSync("which", [binary], {
		encoding: "utf-8",
		timeout: LOOKUP_TIMEOUT_MS,
	});
	if (result.status !== 0 || !result.stdout) return undefined;
	const candidate = result.stdout.split(/\r?\n/)[0]?.trim();
	return candidate || undefined;
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

const killProcessTree = (pid: number): void => {
	if (process.platform === "win32") {
		try {
			spawn("taskkill", ["/F", "/T", "/PID", String(pid)], {
				stdio: "ignore",
				detached: true,
				windowsHide: true,
			});
		} catch {
			// Ignore taskkill failures.
		}
		return;
	}

	try {
		process.kill(-pid, "SIGKILL");
	} catch {
		try {
			process.kill(pid, "SIGKILL");
		} catch {
			// Process already gone.
		}
	}
};

const waitForChildProcess = (child: ChildProcess): Promise<number | null> =>
	new Promise((resolve, reject) => {
		let settled = false;
		let exited = false;
		let exitCode: number | null = null;
		let postExitTimer: NodeJS.Timeout | undefined;
		let stdoutEnded = child.stdout === null;
		let stderrEnded = child.stderr === null;

		const cleanup = () => {
			if (postExitTimer) {
				clearTimeout(postExitTimer);
				postExitTimer = undefined;
			}
			child.removeListener("error", onError);
			child.removeListener("exit", onExit);
			child.removeListener("close", onClose);
			child.stdout?.removeListener("end", onStdoutEnd);
			child.stderr?.removeListener("end", onStderrEnd);
		};

		const finalize = (code: number | null) => {
			if (settled) return;
			settled = true;
			cleanup();
			child.stdout?.destroy();
			child.stderr?.destroy();
			resolve(code);
		};

		const maybeFinalizeAfterExit = () => {
			if (!exited || settled) return;
			if (stdoutEnded && stderrEnded) {
				finalize(exitCode);
			}
		};

		const onStdoutEnd = () => {
			stdoutEnded = true;
			maybeFinalizeAfterExit();
		};

		const onStderrEnd = () => {
			stderrEnded = true;
			maybeFinalizeAfterExit();
		};

		const onError = (error: Error) => {
			if (settled) return;
			settled = true;
			cleanup();
			reject(error);
		};

		const onExit = (code: number | null) => {
			exited = true;
			exitCode = code;
			maybeFinalizeAfterExit();
			if (!settled) {
				postExitTimer = setTimeout(() => finalize(code), EXIT_STDIO_GRACE_MS);
			}
		};

		const onClose = (code: number | null) => {
			finalize(code);
		};

		child.stdout?.once("end", onStdoutEnd);
		child.stderr?.once("end", onStderrEnd);
		child.once("error", onError);
		child.once("exit", onExit);
		child.once("close", onClose);
	});

const createLocalPwshOperations = (): BashOperations => {
	let cachedShellConfig: PwshShellConfig | undefined;

	return {
		exec: (command, cwd, { onData, signal, timeout, env }) => {
			return new Promise((resolve, reject) => {
				if (!existsSync(cwd)) {
					reject(new Error(`Working directory does not exist: ${cwd}\nCannot execute PowerShell commands.`));
					return;
				}

				cachedShellConfig ??= resolvePwshShellConfig();
				const shellConfig = cachedShellConfig;
				const shellCommand = withUtf8Prefix(command, shellConfig.prependUtf8Prefix);

				const child = spawn(shellConfig.shellPath, [...shellConfig.args, shellCommand], {
					cwd,
					detached: true,
					env: withPathPrepended(env ?? process.env),
					stdio: ["ignore", "pipe", "pipe"],
					windowsHide: true,
				});

				let timedOut = false;
				let timeoutHandle: NodeJS.Timeout | undefined;

				if (timeout !== undefined && timeout > 0) {
					timeoutHandle = setTimeout(() => {
						timedOut = true;
						if (child.pid) killProcessTree(child.pid);
					}, timeout * 1000);
				}

				child.stdout?.on("data", onData);
				child.stderr?.on("data", onData);

				const onAbort = () => {
					if (child.pid) killProcessTree(child.pid);
				};

				if (signal) {
					if (signal.aborted) onAbort();
					else signal.addEventListener("abort", onAbort, { once: true });
				}

				waitForChildProcess(child)
					.then((code) => {
						if (timeoutHandle) clearTimeout(timeoutHandle);
						if (signal) signal.removeEventListener("abort", onAbort);

						if (signal?.aborted) {
							reject(new Error("aborted"));
							return;
						}
						if (timedOut) {
							reject(new Error(`timeout:${timeout}`));
							return;
						}
						resolve({ exitCode: code });
					})
					.catch((error) => {
						if (timeoutHandle) clearTimeout(timeoutHandle);
						if (signal) signal.removeEventListener("abort", onAbort);
						reject(error);
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
		description: `Execute a PowerShell command in the current working directory. Returns stdout and stderr. Output is truncated to last ${DEFAULT_MAX_LINES} lines or ${Math.trunc(DEFAULT_MAX_BYTES / 1024)}KB (whichever is hit first). If truncated, full output is saved to a temp file. Optionally provide a timeout in seconds.`,
		promptSnippet: "Execute PowerShell commands (Get-ChildItem, Select-String, etc.)",
		promptGuidelines: [
			"Use pwsh for Windows-native shell tasks and PowerShell-specific syntax.",
		],
		renderCall: (args, theme) => {
			const command = typeof args.command === "string" && args.command.length > 0 ? args.command : "...";
			const timeout = typeof args.timeout === "number" && Number.isFinite(args.timeout) ? args.timeout : undefined;
			const timeoutSuffix = timeout ? theme.fg("muted", ` (timeout ${timeout}s)`) : "";
			return new Text(theme.fg("toolTitle", theme.bold(`PS> ${command}`)) + timeoutSuffix, 0, 0);
		},
	});

	enforceWindowsToolPolicy(pi);

	pi.on("session_start", async () => {
		enforceWindowsToolPolicy(pi);
	});

	pi.on("before_agent_start", async () => {
		enforceWindowsToolPolicy(pi);
	});
}
