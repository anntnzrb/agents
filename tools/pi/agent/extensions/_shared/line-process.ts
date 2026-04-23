import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

type ExitCode = number | null;

export type RunLineStreamingProcessOptions<T> = {
	command: string;
	args: string[];
	maxResults: number;
	signal?: AbortSignal;
	timeoutMs?: number;
	normalizeLine?: (line: string) => string;
	skipEmptyLines?: boolean;
	parseLine: (line: string) => T | undefined;
	missingBinaryMessage: string;
	runErrorLabel?: string;
	exitErrorLabel?: string;
	allowedExitCodes?: readonly number[];
	abortErrorMessage?: string;
	timeoutErrorMessage?: (timeoutMs: number) => string;
};

export async function runLineStreamingProcess<T>(options: RunLineStreamingProcessOptions<T>): Promise<T[]> {
	const {
		command,
		args,
		maxResults,
		signal,
		timeoutMs,
		normalizeLine,
		skipEmptyLines = false,
		parseLine,
		missingBinaryMessage,
		runErrorLabel = command,
		exitErrorLabel = command,
		allowedExitCodes = [0, 1],
		abortErrorMessage = "Operation aborted",
		timeoutErrorMessage = (ms) => `${command} timed out after ${Math.max(1, Math.round(ms / 1000))}s`,
	} = options;

	return await new Promise<T[]>((resolve, reject) => {
		const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
		const lines = createInterface({ input: child.stdout });
		const results: T[] = [];
		let stderr = "";
		let killedForLimit = false;
		let aborted = false;
		let timedOut = false;

		const timer =
			timeoutMs === undefined
				? undefined
				: setTimeout(() => {
					timedOut = true;
					child.kill();
				}, timeoutMs);

		const stopChild = () => {
			if (!child.killed) {
				killedForLimit = true;
				child.kill();
			}
		};

		const cleanup = () => {
			if (timer) clearTimeout(timer);
			lines.close();
			signal?.removeEventListener("abort", onAbort);
		};

		const onAbort = () => {
			aborted = true;
			child.kill();
		};
		signal?.addEventListener("abort", onAbort, { once: true });

		child.stderr.on("data", (chunk: { toString: () => string }) => {
			stderr += chunk.toString();
		});

		lines.on("line", (rawLine) => {
			if (results.length >= maxResults) {
				stopChild();
				return;
			}

			const line = normalizeLine ? normalizeLine(rawLine) : rawLine;
			if (skipEmptyLines && line.length === 0) return;
			const parsed = parseLine(line);
			if (parsed === undefined) return;

			results.push(parsed);
			if (results.length >= maxResults) {
				stopChild();
			}
		});

		child.on("error", (error: Error) => {
			cleanup();
			if ((error as NodeJS.ErrnoException).code === "ENOENT") {
				reject(new Error(missingBinaryMessage));
				return;
			}
			reject(new Error(`Failed to run ${runErrorLabel}: ${error.message}`));
		});

		child.on("close", (code: ExitCode) => {
			cleanup();
			if (aborted) {
				reject(new Error(abortErrorMessage));
				return;
			}
			if (timedOut && timeoutMs !== undefined) {
				reject(new Error(timeoutErrorMessage(timeoutMs)));
				return;
			}
			if (!killedForLimit && !allowedExitCodes.includes(code ?? -1)) {
				const detail = stderr.trim() || `${exitErrorLabel} exited with code ${code}`;
				reject(new Error(detail));
				return;
			}
			resolve(results);
		});
	});
}
