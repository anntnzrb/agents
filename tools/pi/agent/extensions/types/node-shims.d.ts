declare interface ImportMeta {
	url: string;
}

declare type AbortSignal = {
	aborted?: boolean;
	addEventListener: (event: "abort", handler: () => void, options?: { once?: boolean }) => void;
	removeEventListener: (event: "abort", handler: () => void) => void;
};

declare function setTimeout(handler: () => void, ms?: number): unknown;
declare function clearTimeout(handle: unknown): void;
declare function setInterval(handler: () => void, ms?: number): unknown;
declare function clearInterval(handle: unknown): void;

declare const process: {
	env: Record<string, string | undefined>;
	cwd: () => string;
	execPath: string;
	argv: string[];
	platform: string;
};

declare const console: {
	log: (...args: unknown[]) => void;
	error: (...args: unknown[]) => void;
	warn: (...args: unknown[]) => void;
};

declare const Buffer: {
	byteLength: (value: string, encoding?: string) => number;
	from: (value: string, encoding?: string) => Uint8Array;
};

declare namespace NodeJS {
	interface ErrnoException extends Error {
		code?: string;
	}
	interface ProcessEnv {
		[key: string]: string | undefined;
	}
}

declare module "node:child_process" {
	export function spawn(command: string, args?: string[], options?: unknown): any;
	export function spawnSync(command: string, args?: string[], options?: unknown): {
		status: number | null;
		stdout?: string;
		stderr?: string;
		error?: Error;
	};
	export function execFileSync(command: string, args?: string[], options?: unknown): any;
}

declare module "node:crypto" {
	export function createHash(algorithm: string): {
		update: (value: string) => { digest: (encoding: string) => string };
		digest: (encoding: string) => string;
	};
}

declare module "node:fs" {
	export const promises: {
		readFile: {
			(path: string): Promise<{ toString: (encoding?: string) => string; byteLength: number }>;
			(path: string, encoding: string): Promise<string>;
		};
		stat: (path: string) => Promise<{ isDirectory: () => boolean }>;
	};
	export function statSync(path: string): { mtimeMs: number; size: number };
	export function existsSync(path: string): boolean;
	export function readFileSync(path: string, encoding: string): string;
	export function writeFileSync(path: string, content: string): void;
	export function mkdtempSync(prefix: string): string;
}

declare module "node:fs/promises" {
	export function readFile(path: string): Promise<{ toString: (encoding?: string) => string; byteLength: number }>;
	export function readFile(path: string, encoding: string): Promise<string>;
	export function stat(path: string): Promise<{ isDirectory: () => boolean }>;
	export function mkdtemp(prefix: string): Promise<string>;
	export function writeFile(path: string, content: string, options?: unknown): Promise<void>;

	const fsPromises: {
		readFile: typeof readFile;
		stat: typeof stat;
		mkdtemp: typeof mkdtemp;
		writeFile: typeof writeFile;
	};
	export default fsPromises;
}

declare module "node:path" {
	const path: {
		sep: string;
		delimiter: string;
		resolve: (...parts: string[]) => string;
		relative: (from: string, to: string) => string;
		basename: (value: string) => string;
		isAbsolute: (value: string) => boolean;
		join: (...parts: string[]) => string;
		dirname: (value: string) => string;
	};
	export = path;
}

declare module "node:readline" {
	export function createInterface(options: { input: any }): {
		on: (event: string, handler: (line: string) => void) => void;
		close: () => void;
	};
}

declare module "node:url" {
	export function fileURLToPath(value: string | unknown): string;
}

declare module "node:os" {
	export function tmpdir(): string;
	export function homedir(): string;
}

declare module "node:perf_hooks" {
	export const performance: {
		now: () => number;
	};
}
