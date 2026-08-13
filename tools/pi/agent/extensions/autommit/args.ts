export interface CommitOptions {
    readonly context: readonly string[];
}

interface ParseState {
    readonly options: CommitOptions;
    readonly awaitingContext: boolean;
    readonly passthrough: boolean;
    readonly error?: string;
}

export type ParseResult = CommitOptions | { readonly error: string };

const initialParseState: ParseState = {
    options: { context: [] },
    awaitingContext: false,
    passthrough: false,
};

const appendContext = (state: ParseState, value: string): ParseState => ({
    ...state,
    options: {
        ...state.options,
        context: [...state.options.context, value],
    },
    awaitingContext: false,
});

const reduceArgument = (state: ParseState, argument: string): ParseState => {
    if (state.error) return state;
    if (state.awaitingContext) {
        return argument
            ? appendContext(state, argument)
            : { ...state, error: "--context requires a value" };
    }
    if (state.passthrough) return appendContext(state, argument);
    if (argument === "--") {
        return { ...state, passthrough: true };
    }
    if (argument === "--context") return { ...state, awaitingContext: true };
    if (argument.startsWith("--context=")) {
        const value = argument.slice("--context=".length);
        return value
            ? appendContext(state, value)
            : { ...state, error: "--context requires a value" };
    }
    if (argument.startsWith("-")) return { ...state, error: `Unsupported option: ${argument}` };
    return appendContext(state, argument);
};

export const parseArgs = (args: readonly string[]): ParseResult => {
    const state = args.reduce<ParseState>(reduceArgument, initialParseState);
    if (state.error) return { error: state.error };
    if (state.awaitingContext) return { error: "--context requires a value" };
    return state.options;
};

/** Splits the raw command argument string into tokens, honoring simple quotes. */
export const splitArgs = (raw: string): string[] => {
    const tokens: string[] = [];
    const pattern = /"([^"]*)"|'([^']*)'|(\S+)/gu;
    for (const match of raw.matchAll(pattern)) {
        tokens.push(match[1] ?? match[2] ?? match[3] ?? "");
    }
    return tokens;
};

export const composeContext = (options: CommitOptions): string =>
    [...options.context].filter(Boolean).join("\n\n");
