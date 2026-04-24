import path from "node:path";
import { runLineStreamingProcess } from "../_shared/line-process.js";
import { toPosixRelative, type RawMatch, type TypeFilter } from "./logic.js";

type MatchEvent = {
	type?: string;
	data?: {
		path?: { text?: string };
		line_number?: number;
		lines?: { text?: string };
	};
};

export type FileHit = {
	absolutePath: string;
	displayPath: string;
};

export type CountHit = FileHit & {
	count: number;
};

type RipgrepBaseParams = {
	command: string;
	rootAbsolute: string;
	cwd: string;
	pattern: string;
	glob: string | undefined;
	typeFilter: TypeFilter | null;
	ignoreCase: boolean;
	literal: boolean;
	useGitignore: boolean;
	timeoutMs: number;
	signal?: AbortSignal;
};

type RipgrepLineParams<T> = RipgrepBaseParams & {
	maxResults: number;
	modeArgs: string[];
	parseLine: (line: string, cwd: string, rootAbsolute: string) => T | undefined;
};

export type RipgrepMatchParams = RipgrepBaseParams & {
	maxMatches: number;
};

export type RipgrepResultParams = RipgrepBaseParams & {
	maxResults: number;
};

const parseMatchEvent = (line: string): MatchEvent | null => {
	if (line.trim().length === 0) return null;
	try {
		return JSON.parse(line) as MatchEvent;
	} catch {
		return null;
	}
};

const toolMissingMessage = (binary: string, installHint: string): string =>
	`'${binary}' is not available in PATH. Install ${installHint} and retry.`;

const DEFAULT_EXCLUDE_GLOBS = ["!**/.git/**"] as const;

const normalizeRipgrepGlob = (glob: string): string => {
	if (!glob.includes("/") || glob.startsWith("/") || glob.startsWith("**/")) return glob;
	return `**/${glob}`;
};

const buildRipgrepCommonArgs = (params: {
	glob: string | undefined;
	typeFilter: TypeFilter | null;
	ignoreCase: boolean;
	literal: boolean;
	useGitignore: boolean;
}): string[] => {
	const { glob, typeFilter, ignoreCase, literal, useGitignore } = params;
	const args: string[] = [];
	if (ignoreCase) args.push("--ignore-case");
	if (literal) args.push("--fixed-strings");
	if (!useGitignore) args.push("--no-ignore");
	if (glob) {
		args.push("--glob", normalizeRipgrepGlob(glob));
	} else {
		for (const excludeGlob of DEFAULT_EXCLUDE_GLOBS) args.push("--glob", excludeGlob);
	}
	if (typeFilter) {
		for (const typeGlob of typeFilter.rgGlobs) {
			args.push("--glob", typeGlob);
		}
	}
	return args;
};

const appendCommonRipgrepArgs = (params: Parameters<typeof buildRipgrepCommonArgs>[0] & { args: string[] }): void => {
	params.args.push(...buildRipgrepCommonArgs(params));
};

export const __test = {
	buildRipgrepCommonArgs,
	normalizeRipgrepGlob,
};

const resolveRipgrepPath = (cwd: string, rootAbsolute: string, filePath: string): FileHit => {
	const absolutePath = path.isAbsolute(filePath) ? filePath : path.resolve(rootAbsolute, filePath);
	return {
		absolutePath,
		displayPath: toPosixRelative(cwd, absolutePath),
	};
};

const runRipgrepLineMode = async <T>(params: RipgrepLineParams<T>): Promise<T[]> => {
	const { command, rootAbsolute, cwd, pattern, glob, typeFilter, ignoreCase, literal, useGitignore, maxResults, timeoutMs, signal, modeArgs, parseLine } = params;
	const args = [...modeArgs, "--color=never", "--hidden", "--no-require-git"];
	appendCommonRipgrepArgs({ args, glob, typeFilter, ignoreCase, literal, useGitignore });
	args.push(pattern, rootAbsolute);

	return await runLineStreamingProcess<T>({
		command,
		args,
		maxResults,
		timeoutMs,
		...(signal ? { signal } : {}),
		normalizeLine: (line) => line.replace(/\r$/, ""),
		skipEmptyLines: true,
		missingBinaryMessage: toolMissingMessage("rg", "ripgrep (e.g. `brew install ripgrep`)"),
		runErrorLabel: "ripgrep",
		exitErrorLabel: "ripgrep",
		timeoutErrorMessage: (ms) => `grep timed out after ${Math.max(1, Math.round(ms / 1000))}s`,
		parseLine: (line) => parseLine(line, cwd, rootAbsolute),
	});
};

export const runRipgrepFiles = async (params: RipgrepResultParams): Promise<FileHit[]> =>
	await runRipgrepLineMode<FileHit>({
		...params,
		modeArgs: ["--files-with-matches"],
		parseLine: (line, cwd, rootAbsolute) => resolveRipgrepPath(cwd, rootAbsolute, line),
	});

export const runRipgrepCounts = async (params: RipgrepResultParams): Promise<CountHit[]> =>
	await runRipgrepLineMode<CountHit>({
		...params,
		modeArgs: ["--count-matches", "--with-filename"],
		parseLine: (line, cwd, rootAbsolute) => {
			const separator = line.lastIndexOf(":");
			if (separator <= 0) return undefined;
			const count = Number.parseInt(line.slice(separator + 1), 10);
			if (!Number.isFinite(count)) return undefined;
			return { ...resolveRipgrepPath(cwd, rootAbsolute, line.slice(0, separator)), count };
		},
	});

export const runRipgrep = async (params: RipgrepMatchParams): Promise<RawMatch[]> => {
	const { command, rootAbsolute, cwd, pattern, glob, typeFilter, ignoreCase, literal, useGitignore, maxMatches, timeoutMs, signal } = params;
	const args = ["--json", "--line-number", "--color=never", "--hidden", "--no-require-git"];
	appendCommonRipgrepArgs({ args, glob, typeFilter, ignoreCase, literal, useGitignore });
	args.push(pattern, rootAbsolute);

	return await runLineStreamingProcess<RawMatch>({
		command,
		args,
		maxResults: maxMatches,
		timeoutMs,
		...(signal ? { signal } : {}),
		missingBinaryMessage: toolMissingMessage("rg", "ripgrep (e.g. `brew install ripgrep`)"),
		runErrorLabel: "ripgrep",
		exitErrorLabel: "ripgrep",
		timeoutErrorMessage: (ms) => `grep timed out after ${Math.max(1, Math.round(ms / 1000))}s`,
		parseLine: (line) => {
			const event = parseMatchEvent(line);
			if (!event || event.type !== "match") return undefined;
			const filePath = event.data?.path?.text;
			const lineNumber = event.data?.line_number;
			const lineText = event.data?.lines?.text;
			if (!filePath || typeof lineNumber !== "number") return undefined;
			const { absolutePath, displayPath } = resolveRipgrepPath(cwd, rootAbsolute, filePath);
			const cleanedLine = (lineText ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "").replace(/\n$/, "");
			return {
				absolutePath,
				displayPath,
				lineNumber,
				lineText: cleanedLine,
			};
		},
	});
};
