declare module "@earendil-works/pi-coding-agent" {
  export type ThemeColor = string;
  export type Theme = {
    fg: (token: string, text: string) => string;
    bold: (text: string) => string;
    italic?: (text: string) => string;
    getBashModeBorderColor?: () => (text: string) => string;
    getThinkingBorderColor?: (level: unknown) => (text: string) => string;
    getFgAnsi?: (color: string) => string;
    [key: string]: unknown;
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

  export type SessionMessage = {
    role?: string;
    stopReason?: string;
    content?: readonly { type: string; text?: string }[] | { type: string; text?: string }[];
    usage?: {
      inputTokens?: number;
      outputTokens?: number;
      cacheRead?: number;
      cacheWrite?: number;
      cost?: number | { total?: number | string } | string;
    };
    [key: string]: unknown;
  };

  export type SessionEntry = {
    type?: string;
    customType?: string;
    data?: unknown;
    message?: SessionMessage;
    [key: string]: unknown;
  };

  export type SessionManagerLike = {
    getEntries: () => SessionEntry[];
    getBranch: () => SessionEntry[];
    getLeafId: () => string | null;
    getSessionId: () => string | null;
    getSessionFile?: () => string | undefined;
    [key: string]: unknown;
  };

  export type Model = {
    id: string;
    provider: string;
    reasoning?: boolean | undefined;
    [key: string]: unknown;
  };
  export type ModelAuth = {
    ok: boolean;
    apiKey?: string;
    headers?: Record<string, string>;
    error?: string;
    [key: string]: unknown;
  };

  export type ModelRegistry = {
    find: (provider: string, modelId: string) => Model | undefined;
    getApiKeyAndHeaders: (model: Model | unknown) => Promise<ModelAuth>;
    [key: string]: unknown;
  };

  export type ExtensionContext = {
    cwd: string;
    hasUI: boolean;
    model?: Model;
    modelRegistry: ModelRegistry;
    sessionManager: SessionManagerLike;
    ui: {
      theme: Theme;
      notify: (message: string, level?: string) => void;
      setFooter: (factory: (...args: unknown[]) => unknown) => void;
      setWidget: (key: string, widget: unknown) => void;
      setEditorComponent?: (factory: (tui: unknown, theme: Theme, keybindings: unknown) => unknown) => void;
      setEditorText: (text: string) => void;
      getEditorText?: () => string;
      custom: <T>(
        factory: (
          tui: { requestRender: () => void; [key: string]: unknown },
          theme: Theme,
          kb: unknown,
          done: (result: T) => void,
        ) => unknown,
      ) => Promise<T>;
      select: (
        title: string,
        options: string[],
      ) => Promise<string | undefined>;
      confirm: (title: string, message: string) => Promise<boolean>;
      input: (title: string, placeholder?: string) => Promise<string | undefined>;
      editor: (title: string, content: string) => Promise<string | undefined>;
      [key: string]: unknown;
    };
    hasPendingMessages: () => boolean;
    navigateTree?: (targetId: string, options?: { summarize?: boolean }) => Promise<{ cancelled?: boolean; [key: string]: unknown }>;
    waitForIdle?: () => Promise<void>;
    newSession: (options?: { parentSession?: string }) => Promise<{ cancelled?: boolean; [key: string]: unknown }>;
    getContextUsage: () => ContextUsage | null;
    getSystemPrompt: () => string | null;
    [key: string]: unknown;
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
    label?: string | undefined;
    description?: string | undefined;
    promptSnippet?: string | undefined;
    promptGuidelines?: string[] | undefined;
    parameters?: unknown;
    renderShell?: "default" | "self" | undefined;
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
      ctx?: ExtensionContext,
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

  export type Skill = {
    name: string;
    description: string;
    filePath: string;
    baseDir: string;
    sourceInfo: unknown;
    disableModelInvocation: boolean;
  };

  export type ExtensionAPI = {
    on: (
      event: string,
      handler: (event: any, ctx: ExtensionContext) => any,
    ) => void;
    registerTool: (tool: RegisteredTool) => void;
    registerCommand: (
      name: string,
      command:
        | {
            description?: string;
            handler: (args: string, ctx: ExtensionContext) => unknown;
            [key: string]: unknown;
          }
        | ((args: string, ctx: ExtensionContext) => unknown),
    ) => void;
    registerShortcut?: (
      shortcut: string,
      options:
        | {
            description?: string;
            handler: (ctx: ExtensionContext) => unknown;
            [key: string]: unknown;
          }
        | ((ctx: ExtensionContext) => unknown),
    ) => void;
    getThinkingLevel: () => string | undefined;
    setThinkingLevel: (level: string) => void;
    setModel: (model: Model) => Promise<boolean>;
    getActiveTools: () => string[];
    setActiveTools: (tools: string[]) => void;
    getAllTools: () => ToolInfo[];
    getCommands: () => RegisteredCommand[];
    setLabel?: (entryId: string, label?: string) => void;
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

  export const VERSION: string;
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
  export function loadSkills(options: {
    cwd: string;
    agentDir: string;
    skillPaths: string[];
    includeDefaults: boolean;
  }): { skills: Skill[]; diagnostics: unknown[] };
  export function getMarkdownTheme(): unknown;
  export function convertToLlm(...args: unknown[]): unknown;
  export function serializeConversation(...args: unknown[]): string;
  export function compact(...args: unknown[]): Promise<{
    summary?: string;
    firstKeptEntryIndex?: number;
    tokensBefore?: number;
    [key: string]: unknown;
  }>;
  export type ToolDefinition = {
    name: string;
    description: string;
    parameters: unknown;
    execute: (...args: unknown[]) => unknown;
    [key: string]: unknown;
  };
  export function createCodingTools(cwd: string): RegisteredTool[];
  export function createReadOnlyTools(cwd: string): RegisteredTool[];
  export function copyToClipboard(...args: unknown[]): Promise<boolean> | boolean | void;
  export class CustomEditor {
    constructor(tui: unknown, theme: Theme, keybindings: unknown);
    tui: { requestRender: () => void; [key: string]: unknown };
    theme: Theme;
    borderColor?: ((text: string) => string) | undefined;
    getText: () => string;
    setText: (text: string) => void;
    addToHistory?: ((text: string) => void) | undefined;
    render(width: number): string[];
    [key: string]: unknown;
  }
  export class DynamicBorder {
    constructor(render?: (str: string) => string);
    [key: string]: unknown;
  }
  export const BorderedLoader: any;
  export const TreeSelectorComponent: any;
  export class ModelSelectorComponent {
    constructor(...args: unknown[]);
    [key: string]: unknown;
  }
  export const SettingsManager: {
    inMemory: () => unknown;
    [key: string]: unknown;
  };
}

declare module "@earendil-works/pi-ai" {
  export function complete(
    ...args: unknown[]
  ): Promise<{
    content: Array<{ type: string; text?: string; [key: string]: unknown }>;
    stopReason?: string;
    [key: string]: unknown;
  }>;
  export type Api = unknown;
  export type Model<TApi = unknown> = {
    id: string;
    provider: string;
    api?: TApi;
    [key: string]: unknown;
  };
  export function StringEnum<T extends readonly string[]>(values: T): unknown;
  export type UserMessage = any;
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
    timestamp?: number;
    [key: string]: unknown;
  };
}

declare module "@earendil-works/pi-tui" {
  export class Text {
    constructor(text: string, width?: number, height?: number);
    setText(text: string): void;
  }

  export class Container {
    constructor(...args: any[]);
    addChild(child: any): void;
    clear(): void;
    invalidate(): void;
    render(width: number): string[];
  }

  export type SelectItem = {
    value: string;
    label: string;
    description?: string;
    [key: string]: unknown;
  };

  export class SelectList {
    constructor(
      items: SelectItem[] | unknown[],
      maxVisible?: number,
      options?: {
        selectedPrefix?: (text: string) => string;
        selectedText?: (text: string) => string;
        description?: (text: string) => string;
        scrollInfo?: (text: string) => string;
        noMatch?: (text: string) => string;
        [key: string]: unknown;
      },
    );
    onSelect?: (item: SelectItem | any) => void;
    onCancel?: () => void;
    handleInput(data: string): void;
    [key: string]: unknown;
  }

  export function getEditorKeybindings(...args: unknown[]): unknown;
  export function fuzzyMatch(pattern: string, text: string): unknown;

  export class Markdown {
    constructor(...args: any[]);
  }

  export class Spacer {
    constructor(...args: any[]);
  }

  export interface Focusable {
    focused: boolean;
  }

  export interface EditorTheme {
    borderColor?: (text: string) => string;
    selectList?: {
      selectedBg?: (text: string) => string;
      selectedFg?: (text: string) => string;
      matchHighlight?: (text: string) => string;
      itemSecondary?: (text: string) => string;
      selectedPrefix?: (text: string) => string;
      selectedText?: (text: string) => string;
      description?: (text: string) => string;
      scrollInfo?: (text: string) => string;
      noMatch?: (text: string) => string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  }

  export class Editor {
    constructor(tui: unknown, theme?: unknown);
    focused: boolean;
    disableSubmit: boolean;
    onChange?: () => void;
    getText(): string;
    setText(text: string): void;
    handleInput(data: string): void;
    render(width: number): string[];
  }

  export const Key: any;
  export function getKeybindings(): any;
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
  export function wrapTextWithAnsi(text: string, width: number): string[];
}

declare module "@sinclair/typebox" {
  export type Static<T> = any;
  export const Type: {
    String: (options?: unknown) => unknown;
    Number: (options?: unknown) => unknown;
    Integer: (options?: unknown) => unknown;
    Boolean: (options?: unknown) => unknown;
    Array: (item: unknown, options?: unknown) => unknown;
    Object: (properties: Record<string, unknown>, options?: unknown) => unknown;
    Optional: (schema: unknown) => unknown;
  };
}
