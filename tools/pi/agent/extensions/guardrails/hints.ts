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

type BlockHintInput = {
	message: string;
	requiresSkill?: string;
	requiredWorkflow?: string;
};

const HINT_DEFINITIONS = {
	grep: {
		nativeTool: "grep",
		messagePattern: /native [`']?grep[`']? tool|`grep`/i,
		shellExecutableLabel: "`rg`, `grep`, `git grep`, `Select-String`",
		shellToolKind: "search executables",
		taskLabel: "repository search",
		fallbackSignature:
			"grep({ pattern, paths, glob, type, ignoreCase, literal, context, outputMode, ignored, offset, limit, timeoutMs })",
	},
	find: {
		nativeTool: "find",
		messagePattern: /native [`']?find[`']? tool|`find`/i,
		shellExecutableLabel: "`fd`, `find`, `locate`",
		shellToolKind: "discovery executables",
		taskLabel: "repository file lookup",
		fallbackSignature: "find({ pattern, paths, hidden, kind, ignored, limit, timeoutMs })",
	},
} as const satisfies Record<GuardedNativeTool, HintDefinition>;

const HINT_DEFINITION_LIST = Object.values(HINT_DEFINITIONS);

const formatBlockHint = ({ message, requiresSkill, requiredWorkflow }: BlockHintInput): string => {
	if (!requiresSkill) return message;
	const workflowLine = requiredWorkflow ? ` ${requiredWorkflow}` : "";
	return `Guardrail blocked this command. Required skill \`${requiresSkill}\` has been loaded into context when configured.${workflowLine}`;
};

const extractObjectPropertyNames = (schema: unknown): string[] => {
	if (!schema || typeof schema !== "object") return [];
	const properties = (schema as { properties?: unknown }).properties;
	if (!properties || typeof properties !== "object") return [];
	return Object.keys(properties);
};

const definitionForMessage = (message: string): HintDefinition | undefined => HINT_DEFINITION_LIST.find((definition) => definition.messagePattern.test(message));


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

export const agentHintForBlock = (input: string | BlockHintInput): string => {
	if (typeof input === "string") return input;
	return formatBlockHint(input);
};
