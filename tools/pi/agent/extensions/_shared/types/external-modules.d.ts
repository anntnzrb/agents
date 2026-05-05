declare module "@mariozechner/pi-coding-agent" {
	export type ThemeColor = string;
	export type Theme = {
		fg: (token: string, text: string) => string;
		bold: (text: string) => string;
	};

	export type ToolRenderCallContext = {
		lastComponent?: unknown;
		expanded?: boolean;
		executionStarted?: boolean;
		argsComplete?: boolean;
		cwd: string;
		state: Record<string, unknown>;
	};

	export type ToolRenderResultContext = {
		lastComponent?: unknown;
		showImages?: boolean;
		isError?: boolean;
	};

	export type ToolRenderResultOptions = {
		expanded?: boolean;
		isPartial?: boolean;
	};

	export type SessionEntry = {
		type?: string;
		customType?: string;
		data?: unknown;
		message?: {
			role?: string;
			usage?: {
				inputTokens?: number;
				outputTokens?: number;
				cacheRead?: number;
				cacheWrite?: number;
				cost?: number | { total?: number | string } | string;
			};
		};
	};

	export type SessionManagerLike = {
		getEntries: () => SessionEntry[];
		getLeafId: () => string | null;
		getSessionId: () => string | null;
	};

	export type ContextUsage = {
		tokens: number;
		contextWindow: number;
	};

	export type ExtensionContext = {
		cwd: string;
		hasUI: boolean;
		model?: unknown;
		sessionManager: SessionManagerLike;
		ui: {
			notify: (message: string, level?: string) => void;
			setFooter: (factory: (...args: any[]) => any) => void;
			custom: <T>(factory: (...args: any[]) => T | Promise<T>) => Promise<T>;
		};
		getContextUsage: () => ContextUsage | null;
		getSystemPrompt: () => string | null;
	};

	export type ToolResultEvent = {
		toolName?: string;
		isError?: boolean;
		input?: unknown;
	};

	export type ExtensionCommandContext = ExtensionContext;

	export type BashOperations = {
		exec: (
			command: string,
			cwd: string,
			input: {
				onData: (data: Uint8Array | string) => void;
				signal?: AbortSignal;
				timeout?: number;
				env?: NodeJS.ProcessEnv;
			},
		) => Promise<{ exitCode: number }>;
	};

	export type RegisteredTool = {
		name: string;
		label?: string;
		description?: string;
		promptSnippet?: string;
		promptGuidelines?: string[];
		parameters?: unknown;
		renderShell?: "default" | "self";
		renderCall?: (
			args: any,
			theme: Theme,
			context: ToolRenderCallContext,
		) => any;
		renderResult?: (
			result: any,
			options: ToolRenderResultOptions,
			theme: Theme,
			context: ToolRenderResultContext,
		) => any;
		execute?: (
			toolCallId: string,
			input: any,
			signal: AbortSignal,
			onUpdate?: (partial: AgentToolResult) => void,
			ctx: ExtensionContext,
		) => Promise<any> | any;
	};

	export type CommandSourceInfo = {
		source?: string;
		path?: string;
	};

	export type RegisteredCommand = {
		name: string;
		sourceInfo?: CommandSourceInfo;
	};

	export type ToolInfo = {
		name: string;
		description?: string;
	};

	export type ExtensionAPI = {
		on: (
			event: string,
			handler: (event: any, ctx: ExtensionContext) => any,
		) => void;
		registerTool: (tool: RegisteredTool) => void;
		registerCommand: (name: string, command: any) => void;
		getActiveTools: () => string[];
		setActiveTools: (tools: string[]) => void;
		getAllTools: () => ToolInfo[];
		getCommands: () => RegisteredCommand[];
		appendEntry: <T>(customType: string, data: T) => void;
		sendMessage: (
			message: {
				customType: string;
				content: string;
				display?: boolean;
				details?: unknown;
			},
			options?: {
				triggerTurn?: boolean;
				deliverAs?: "steer" | "followUp" | "nextTurn";
			},
		) => void;
		getThinkingLevel: () => string;
	};

	export type AgentToolContentPart = {
		type: string;
		text?: string;
	};

	export type AgentToolResult<TDetails = unknown> = {
		content: AgentToolContentPart[];
		details?: TDetails;
		isError?: boolean;
	};

	export type EditToolDetails = {
		diff: string;
		firstChangedLine?: number;
	};

	export type TruncationResult = {
		content: string;
		truncated?: boolean;
		truncatedBy?: "lines" | "bytes" | null;
		totalLines: number;
		totalBytes: number;
		outputLines?: number;
		outputBytes?: number;
		lastLinePartial?: boolean;
		firstLineExceedsLimit?: boolean;
		maxLines?: number;
		maxBytes?: number;
	};

	export const DEFAULT_MAX_BYTES: number;
	export const DEFAULT_MAX_LINES: number;
	export function formatSize(bytes: number): string;
	export function keyHint(action: string, fallbackText: string): string;
	export function truncateHead(
		content: string,
		options?: { maxLines?: number; maxBytes?: number },
	): TruncationResult;
	export function isToolCallEventType<
		TName extends string = string,
		TInput = any,
	>(
		name: TName,
		event: any,
	): event is { type: "tool_call"; toolName: TName; input: TInput };
	export function createReadToolDefinition(cwd: string): RegisteredTool;
	export function createWriteToolDefinition(cwd: string): RegisteredTool;
	export function createEditToolDefinition(cwd: string): RegisteredTool;
	export function createBashToolDefinition(
		cwd: string,
		options?: { operations?: BashOperations },
	): RegisteredTool;
	export function createFindToolDefinition(cwd: string): RegisteredTool;
	export function createGrepToolDefinition(cwd: string): RegisteredTool;
	export function withFileMutationQueue<T>(
		path: string,
		op: () => Promise<T>,
	): Promise<T>;
	export function getAgentDir(): string;
	export function getMarkdownTheme(): unknown;
	export const DynamicBorder: any;
}

declare module "@mariozechner/pi-ai" {
	export type MessageContentPart = {
		type: string;
		text?: string;
	};

	export type MessageUsage = {
		input?: number;
		output?: number;
		inputTokens?: number;
		outputTokens?: number;
		cacheRead?: number;
		cacheWrite?: number;
		totalTokens?: number;
		cost?: number | { total?: number | string } | string;
	};

	export type Message = {
		role: string;
		content: MessageContentPart[];
		usage?: MessageUsage;
		model?: string;
		stopReason?: string;
		errorMessage?: string;
	};
}

declare module "@mariozechner/pi-tui" {
	export class Text {
		constructor(text: string, width?: number, height?: number);
		setText(text: string): void;
	}

	export class Container {
		constructor(...args: any[]);
		addChild(child: any): void;
		invalidate(): void;
		render(width: number): string[];
	}

	export class Markdown {
		constructor(...args: any[]);
	}

	export class Spacer {
		constructor(...args: any[]);
	}

	export const Key: any;
	export type Component = any;
	export type TUI = any;
	export function matchesKey(...args: any[]): boolean;
	export function truncateToWidth(
		text: string,
		width: number,
		ellipsis?: any,
		pad?: boolean,
	): string;
	export function visibleWidth(text: string): number;
}

declare module "@sinclair/typebox" {
	export type Static<T> = any;
	export const Type: {
		String: (options?: unknown) => unknown;
		Number: (options?: unknown) => unknown;
		Boolean: (options?: unknown) => unknown;
		Array: (item: unknown, options?: unknown) => unknown;
		Object: (properties: Record<string, unknown>, options?: unknown) => unknown;
		Optional: (schema: unknown) => unknown;
	};
}
