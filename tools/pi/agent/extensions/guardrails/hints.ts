type GuardedNativeTool = "grep" | "find";

type ToolLike = {
	name?: string;
	parameters?: unknown;
};

type HintDefinition = {
	nativeTool: GuardedNativeTool;
	messagePattern: RegExp;
	shellExecutableLabel: string;
	shellToolKind: string;
	taskLabel: string;
	fallbackSignature: string;
};

type BlockHintDefinition = {
	messagePattern: RegExp;
	hint: string;
};

const HINT_DEFINITIONS = {
	grep: {
		nativeTool: "grep",
		messagePattern: /native [`']?grep[`']? tool|`grep`/i,
		shellExecutableLabel: "`rg`, `grep`, `git grep`, `Select-String`",
		shellToolKind: "search executables",
		taskLabel: "repository search",
		fallbackSignature:
			"grep({ pattern, path, paths, glob, type, ignoreCase, literal, context, outputMode, gitignore, noIgnore, offset, limit, timeoutMs })",
	},
	find: {
		nativeTool: "find",
		messagePattern: /native [`']?find[`']? tool|`find`/i,
		shellExecutableLabel: "`fd`, `find`, `locate`",
		shellToolKind: "discovery executables",
		taskLabel: "repository file lookup",
		fallbackSignature: "find({ pattern, path, paths, hidden, kind, gitignore, noIgnore, limit, timeoutMs })",
	},
} as const satisfies Record<GuardedNativeTool, HintDefinition>;

const HINT_DEFINITION_LIST = Object.values(HINT_DEFINITIONS);

const BLOCK_HINT_DEFINITIONS: readonly BlockHintDefinition[] = [
	{
		messagePattern: /python|pip|poetry|package tooling|py_compile|venv/i,
		hint:
			"Guardrail: direct Python tooling disabled. Load `/skill:python`; use repo Python workflow/uv (`uv run`, `uv add`, `uv run --with`) instead of raw python/pip/env commands.",
	},
];

const extractObjectPropertyNames = (schema: unknown): string[] => {
	if (!schema || typeof schema !== "object") return [];
	const properties = (schema as { properties?: unknown }).properties;
	if (!properties || typeof properties !== "object") return [];
	return Object.keys(properties);
};

const definitionForMessage = (message: string): HintDefinition | undefined => HINT_DEFINITION_LIST.find((definition) => definition.messagePattern.test(message));

const blockDefinitionForMessage = (message: string): BlockHintDefinition | undefined =>
	BLOCK_HINT_DEFINITIONS.find((definition) => definition.messagePattern.test(message));

export const formatToolSignature = (toolName: GuardedNativeTool, tools: readonly ToolLike[] = []): string => {
	const definition = HINT_DEFINITIONS[toolName];
	const tool = tools.find((candidate) => candidate.name === toolName);
	const propertyNames = extractObjectPropertyNames(tool?.parameters);
	if (propertyNames.length === 0) return definition.fallbackSignature;
	return `${toolName}({ ${propertyNames.join(", ")} })`;
};

const formatWarningHint = (definition: HintDefinition, tools: readonly ToolLike[]): string => {
	const signature = formatToolSignature(definition.nativeTool, tools);
	return `Guardrail: don't use shell ${definition.shellToolKind} (${definition.shellExecutableLabel}) for ${definition.taskLabel}. Use native \`${definition.nativeTool}\` tool instead: ${signature}.`;
};

export const agentHintForWarning = (message: string, tools: readonly ToolLike[] = []): string => {
	const definition = definitionForMessage(message);
	return definition ? formatWarningHint(definition, tools) : message;
};

export const agentHintForBlock = (message: string): string => blockDefinitionForMessage(message)?.hint ?? message;
