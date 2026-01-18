import type {
  AnswerOptions,
  ResearchCreateRequest,
  TextContentsOptions,
} from "exa-js";
import type {
  Command,
  ContentsOptionsInput,
  LinkedInSearchType,
  ParseResult,
  SearchOptionsInput,
  SearchType,
} from "@/types";

const SEARCH_TYPES: Set<SearchType> = new Set(["auto", "fast", "deep"]);
const CODE_CONTEXT_TOKENS_MIN = 1000;
const CODE_CONTEXT_TOKENS_MAX = 50000;

export function parseCommand(argv: string[]): ParseResult<Command> {
  if (argv.includes("-h") || argv.includes("--help")) {
    return { ok: false, error: "Help requested." };
  }

  const [command, ...rest] = argv;
  if (!command) {
    return { ok: false, error: "Missing command." };
  }

  switch (command) {
    case "search":
      return parseSearch(rest);
    case "contents":
      return parseContents(rest);
    case "answer":
      return parseAnswer(rest);
    case "research-start":
      return parseResearchStart(rest);
    case "research-check":
      return parseResearchCheck(rest);
    case "deep-search":
      return parseDeepSearch(rest);
    case "code-context":
      return parseCodeContext(rest);
    case "company-research":
      return parseCompanyResearch(rest);
    case "linkedin-search":
      return parseLinkedInSearch(rest);
    default:
      return { ok: false, error: `Unknown command: ${command}` };
  }
}

export function usage(): string {
  return [
    "Usage:",
    "  exa.ts search <query> [options]",
    "  exa.ts contents <url...> [options]",
    "  exa.ts answer <question> [options]",
    "  exa.ts research-start <instructions> [options]",
    "  exa.ts research-check <task-id>",
    "  exa.ts deep-search <objective> [options]",
    "  exa.ts code-context <query> [options]",
    "  exa.ts company-research <name> [options]",
    "  exa.ts linkedin-search <query> [options]",
    "",
    "Common options:",
    "  -n <num>                      Number of results",
    "  --type <auto|fast|deep>",
    "  --text-max <num>",
    "",
    "Answer options:",
    "  --text",
    "  --system <prompt>",
    "  --schema <json>",
    "",
    "Deep search options:",
    "  --queries a,b,c",
    "",
    "Code context options:",
    "  --tokens <num>",
    "",
    "LinkedIn options:",
    "  --type <profiles|companies|all>",
  ].join("\n");
}

function parseSearch(args: string[]): ParseResult<Command> {
  const options: SearchOptionsInput = {};
  const queryParts: string[] = [];

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "-n":
      case "--num": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        options.numResults = parsed.value;
        i += 2;
        break;
      }
      case "--text-max": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        const contents = ensureContents(options);
        contents.text = mergeTextOptions(contents.text, {
          maxCharacters: parsed.value,
        });
        i += 2;
        break;
      }
      case "--type": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        if (!isSearchType(value)) {
          return { ok: false, error: `Invalid search type: ${value}` };
        }
        options.type = value;
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        queryParts.push(arg);
        i += 1;
      }
    }
  }

  const query = queryParts.join(" ").trim();
  if (!query) {
    return { ok: false, error: "Missing query." };
  }

  return { ok: true, value: { kind: "search", query, options } };
}

function parseContents(args: string[]): ParseResult<Command> {
  const options: ContentsOptionsInput = {};
  const urls: string[] = [];

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--text-max": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        options.text = mergeTextOptions(options.text, {
          maxCharacters: parsed.value,
        });
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        urls.push(arg);
        i += 1;
      }
    }
  }

  if (urls.length === 0) {
    return { ok: false, error: "Missing URL(s)." };
  }

  if (!options.text) {
    options.text = { maxCharacters: 10000 };
  }

  return { ok: true, value: { kind: "contents", urls, options } };
}

function parseAnswer(args: string[]): ParseResult<Command> {
  const options: AnswerOptions = {};
  const queryParts: string[] = [];

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--text": {
        options.text = true;
        i += 1;
        break;
      }
      case "--system": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        options.systemPrompt = value;
        i += 2;
        break;
      }
      case "--schema": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        const parsed = parseJsonObject(value, arg);
        if (!parsed.ok) return parsed;
        options.outputSchema = parsed.value;
        i += 2;
        break;
      }
      case "--model": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        if (value !== "exa") {
          return { ok: false, error: `Unsupported model: ${value}` };
        }
        options.model = "exa";
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        queryParts.push(arg);
        i += 1;
      }
    }
  }

  const query = queryParts.join(" ").trim();
  if (!query) {
    return { ok: false, error: "Missing question." };
  }

  return { ok: true, value: { kind: "answer", query, options } };
}

function parseResearchStart(args: string[]): ParseResult<Command> {
  const options: {
    model?: ResearchCreateRequest["model"];
  } = {};
  const instructionParts: string[] = [];

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--model": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        if (!isResearchModel(value)) {
          return { ok: false, error: `Unsupported model: ${value}` };
        }
        options.model = value as ResearchCreateRequest["model"];
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        instructionParts.push(arg);
        i += 1;
      }
    }
  }

  const instructions = instructionParts.join(" ").trim();
  if (!instructions) {
    return { ok: false, error: "Missing instructions." };
  }

  return {
    ok: true,
    value: {
      kind: "research-start",
      instructions,
      options,
    },
  };
}

function parseResearchCheck(args: string[]): ParseResult<Command> {
  const id = args[0]?.trim();
  if (!id) {
    return { ok: false, error: "Missing task ID." };
  }
  if (args.length > 1) {
    return { ok: false, error: "research-check only accepts a task ID." };
  }
  return { ok: true, value: { kind: "research-check", id } };
}

function parseDeepSearch(args: string[]): ParseResult<Command> {
  const objectiveParts: string[] = [];
  let queries: string[] | undefined;

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--queries": {
        const value = args[i + 1];
        const parsed = parseCsv(value, arg);
        if (!parsed.ok) return parsed;
        queries = parsed.value;
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        objectiveParts.push(arg);
        i += 1;
      }
    }
  }

  const objective = objectiveParts.join(" ").trim();
  if (!objective) {
    return { ok: false, error: "Missing objective." };
  }

  return {
    ok: true,
    value: {
      kind: "deep-search",
      objective,
      ...(queries ? { queries } : {}),
    },
  };
}

function parseCodeContext(args: string[]): ParseResult<Command> {
  const queryParts: string[] = [];
  let tokensNum: number | undefined;

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--tokens": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        if (
          parsed.value < CODE_CONTEXT_TOKENS_MIN ||
          parsed.value > CODE_CONTEXT_TOKENS_MAX
        ) {
          return {
            ok: false,
            error: "--tokens must be between 1000 and 50000.",
          };
        }
        tokensNum = parsed.value;
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        queryParts.push(arg);
        i += 1;
      }
    }
  }

  const query = queryParts.join(" ").trim();
  if (!query) {
    return { ok: false, error: "Missing query." };
  }
  const resolvedTokens = tokensNum ?? CODE_CONTEXT_TOKENS_MAX;

  return {
    ok: true,
    value: {
      kind: "code-context",
      query,
      tokensNum: resolvedTokens,
    },
  };
}

function parseCompanyResearch(args: string[]): ParseResult<Command> {
  const nameParts: string[] = [];
  let numResults: number | undefined;

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "-n":
      case "--num": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        numResults = parsed.value;
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        nameParts.push(arg);
        i += 1;
      }
    }
  }

  const companyName = nameParts.join(" ").trim();
  if (!companyName) {
    return { ok: false, error: "Missing company name." };
  }

  return {
    ok: true,
    value: {
      kind: "company-research",
      companyName,
      ...(numResults ? { numResults } : {}),
    },
  };
}

function parseLinkedInSearch(args: string[]): ParseResult<Command> {
  const queryParts: string[] = [];
  let searchType: LinkedInSearchType | undefined;
  let numResults: number | undefined;

  let i = 0;
  while (i < args.length) {
    const arg = args[i];
    if (!arg) {
      i += 1;
      continue;
    }

    switch (arg) {
      case "--type": {
        const value = args[i + 1];
        if (!value) return missingValue(arg);
        if (!isLinkedInSearchType(value)) {
          return { ok: false, error: `Invalid LinkedIn type: ${value}` };
        }
        searchType = value;
        i += 2;
        break;
      }
      case "-n":
      case "--num": {
        const value = args[i + 1];
        const parsed = parsePositiveInt(value, arg);
        if (!parsed.ok) return parsed;
        numResults = parsed.value;
        i += 2;
        break;
      }
      default: {
        if (arg.startsWith("-")) {
          return { ok: false, error: `Unknown option: ${arg}` };
        }
        queryParts.push(arg);
        i += 1;
      }
    }
  }

  const query = queryParts.join(" ").trim();
  if (!query) {
    return { ok: false, error: "Missing query." };
  }

  return {
    ok: true,
    value: {
      kind: "linkedin-search",
      query,
      ...(searchType ? { searchType } : {}),
      ...(numResults ? { numResults } : {}),
    },
  };
}

function parsePositiveInt(
  value: string | undefined,
  flag: string,
): ParseResult<number> {
  if (!value) {
    return missingValue(flag);
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, error: `${flag} must be a positive integer.` };
  }
  return { ok: true, value: parsed };
}

function parseCsv(
  value: string | undefined,
  flag: string,
): ParseResult<string[]> {
  if (!value) {
    return missingValue(flag);
  }
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  if (items.length === 0) {
    return { ok: false, error: `${flag} must include at least one domain.` };
  }
  return { ok: true, value: items };
}

function parseJsonObject(
  value: string,
  flag: string,
): ParseResult<Record<string, unknown>> {
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { ok: true, value: parsed as Record<string, unknown> };
    }
  } catch {
    // fall through
  }
  return { ok: false, error: `${flag} must be valid JSON object.` };
}

function missingValue(flag: string): ParseResult<never> {
  return { ok: false, error: `Missing value for ${flag}.` };
}

function ensureContents(
  options: SearchOptionsInput,
): NonNullable<SearchOptionsInput["contents"]> {
  if (!options.contents) {
    options.contents = {};
  }
  return options.contents;
}

type TextOption = true | TextContentsOptions | undefined;

function mergeTextOptions(
  current: TextOption,
  update: Partial<TextContentsOptions>,
): TextContentsOptions {
  const base = isTextOptions(current) ? current : {};
  return { ...base, ...update };
}

function isTextOptions(value: TextOption): value is TextContentsOptions {
  return !!value && typeof value === "object";
}

function isSearchType(value: string): value is SearchType {
  return SEARCH_TYPES.has(value as SearchType);
}

function isResearchModel(
  value: string,
): value is "exa-research" | "exa-research-pro" {
  return value === "exa-research" || value === "exa-research-pro";
}

function isLinkedInSearchType(value: string): value is LinkedInSearchType {
  return value === "profiles" || value === "companies" || value === "all";
}
