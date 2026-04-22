export type ProviderVerbosity = "low" | "medium" | "high";

export type PlainObject = Record<string, unknown>;

export type PatchFieldChange = {
	path: string;
	before: unknown;
	after: unknown;
};

export type PatchTrace = {
	provider: string;
	rule: string;
	model?: string;
	changed: boolean;
	reason: string;
	changes: readonly PatchFieldChange[];
};

export type PatchResult =
	| { changed: false; trace: PatchTrace }
	| { changed: true; payload: unknown; trace: PatchTrace };

export type ProviderPayloadPatcher = (payload: unknown) => PatchResult;

export const unchanged = (trace: PatchTrace): PatchResult => ({
	changed: false,
	trace,
});

export const changed = (payload: unknown, trace: PatchTrace): PatchResult => ({
	changed: true,
	payload,
	trace,
});

export const isPlainObject = (value: unknown): value is PlainObject =>
	typeof value === "object" && value !== null && !Array.isArray(value);

export const getString = (value: unknown): string | undefined =>
	typeof value === "string" ? value : undefined;
