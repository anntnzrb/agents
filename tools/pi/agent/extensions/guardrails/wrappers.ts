import { executableBasename, isAssignmentToken } from "./shell.js";

const PASSTHROUGH_WRAPPERS = new Set(["builtin", "command", "exec", "nohup"]);
const SHELL_EXECUTABLES = new Set([
  "bash",
  "dash",
  "fish",
  "ksh",
  "mksh",
  "pwsh",
  "pwsh.exe",
  "powershell",
  "powershell.exe",
  "sh",
  "zsh",
]);

const SUDO_VALUE_OPTIONS = new Set([
  "-a",
  "-C",
  "-g",
  "-h",
  "-p",
  "-R",
  "-T",
  "-t",
  "-u",
  "--chdir",
  "--close-from",
  "--group",
  "--host",
  "--other-user",
  "--prompt",
  "--role",
  "--type",
  "--user",
]);

const EXEC_VALUE_OPTIONS = new Set(["-a"]);
const TIME_OPTIONS = new Set(["-p", "--portability"]);
const TIMEOUT_VALUE_OPTIONS = new Set(["-k", "-s", "--kill-after", "--signal"]);
const STDBUF_PREFIXES = ["-e", "-i", "-o"];

export interface UnwrappedCommand {
  remainderTokens?: string[];
  nestedCommands?: string[];
}

function tokenAt(tokens: string[], index: number): string | null {
  if (index < 0 || index >= tokens.length) {
    return null;
  }
  return tokens[index] ?? null;
}

export function firstExecutableIndex(tokens: string[]): number {
  let index = 0;
  while (index < tokens.length) {
    const token = tokenAt(tokens, index);
    if (!token || !isAssignmentToken(token)) {
      break;
    }
    index += 1;
  }
  return index;
}

export function unwrapCommand(tokens: string[], index: number): UnwrappedCommand {
  const executableToken = tokenAt(tokens, index);
  if (!executableToken) {
    return {};
  }

  const executable = executableBasename(executableToken).toLowerCase();

  if (executable === "env") {
    return unwrapEnv(tokens, index);
  }

  if (executable === "nice") {
    return unwrapNice(tokens, index);
  }

  if (executable === "stdbuf") {
    return unwrapStdbuf(tokens, index);
  }

  if (executable === "sudo") {
    return unwrapSudo(tokens, index);
  }

  if (executable === "time") {
    return unwrapTime(tokens, index);
  }

  if (executable === "timeout") {
    return unwrapTimeout(tokens, index);
  }

  if (PASSTHROUGH_WRAPPERS.has(executable)) {
    return unwrapPassthrough(tokens, index);
  }

  if (SHELL_EXECUTABLES.has(executable)) {
    return unwrapShell(tokens, index);
  }

  return {};
}

function unwrapPassthrough(tokens: string[], index: number): UnwrappedCommand {
  const executableToken = tokenAt(tokens, index);
  if (!executableToken) {
    return {};
  }

  const executable = executableBasename(executableToken);
  let i = index + 1;

  if (executable === "exec") {
    while (i < tokens.length) {
      const token = tokenAt(tokens, i);
      if (!token) {
        break;
      }
      if (token === "--") {
        i += 1;
        break;
      }
      if (!token.startsWith("-")) {
        break;
      }
      if (EXEC_VALUE_OPTIONS.has(token) && i + 1 < tokens.length) {
        i += 2;
        continue;
      }
      i += 1;
    }
    return { remainderTokens: tokens.slice(i) };
  }

  if (executable === "command") {
    while (i < tokens.length) {
      const token = tokenAt(tokens, i);
      if (!token) {
        break;
      }
      if (token === "--") {
        i += 1;
        break;
      }
      if (token === "-v" || token === "-V") {
        return {};
      }
      if (!token.startsWith("-")) {
        break;
      }
      i += 1;
    }
    return { remainderTokens: tokens.slice(i) };
  }

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }
    if (token === "--") {
      i += 1;
      break;
    }
    if (!token.startsWith("-")) {
      break;
    }
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapEnv(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }

    if (token === "--") {
      i += 1;
      break;
    }

    if (token === "-S" || token === "--split-string") {
      const split = tokenAt(tokens, i + 1);
      return { nestedCommands: split ? [split] : [] };
    }

    if (token === "-u" || token === "-C" || token === "--unset" || token === "--chdir" || token === "--argv0") {
      i += 2;
      continue;
    }

    if (token.startsWith("--unset=") || token.startsWith("--chdir=") || token.startsWith("--argv0=")) {
      i += 1;
      continue;
    }

    if (token.startsWith("-")) {
      i += 1;
      continue;
    }

    if (isAssignmentToken(token)) {
      i += 1;
      continue;
    }

    break;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapNice(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  if (tokenAt(tokens, i) === "--") {
    return { remainderTokens: tokens.slice(i + 1) };
  }

  const firstArg = tokenAt(tokens, i);
  if (firstArg === "-n" || firstArg === "--adjustment") {
    i += 2;
  } else if (firstArg && /^[+-]?\d+$/.test(firstArg)) {
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapStdbuf(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }
    if (token === "--") {
      i += 1;
      break;
    }
    if (!STDBUF_PREFIXES.some((prefix) => token.startsWith(prefix))) {
      break;
    }
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapSudo(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }
    if (token === "--") {
      i += 1;
      break;
    }
    if (!token.startsWith("-")) {
      break;
    }
    if (SUDO_VALUE_OPTIONS.has(token) && i + 1 < tokens.length) {
      i += 2;
      continue;
    }
    if (token.startsWith("--") && token.includes("=")) {
      i += 1;
      continue;
    }
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapTime(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }
    if (token === "--") {
      i += 1;
      break;
    }
    if (!TIME_OPTIONS.has(token)) {
      break;
    }
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapTimeout(tokens: string[], index: number): UnwrappedCommand {
  let i = index + 1;

  while (i < tokens.length) {
    const token = tokenAt(tokens, i);
    if (!token) {
      break;
    }
    if (token === "--") {
      i += 1;
      break;
    }
    if (!token.startsWith("-")) {
      break;
    }
    if (TIMEOUT_VALUE_OPTIONS.has(token) && i + 1 < tokens.length) {
      i += 2;
      continue;
    }
    if (token.startsWith("--signal=") || token.startsWith("--kill-after=")) {
      i += 1;
      continue;
    }
    i += 1;
  }

  if (i < tokens.length) {
    i += 1;
  }

  return { remainderTokens: tokens.slice(i) };
}

function unwrapShell(tokens: string[], index: number): UnwrappedCommand {
  const args = tokens.slice(index + 1);

  for (let i = 0; i < args.length; i += 1) {
    const token = tokenAt(args, i);
    if (!token) {
      break;
    }

    const normalized = token.toLowerCase();

    if (token === "--") {
      continue;
    }

    if (
      normalized === "-c" ||
      /^-[A-Za-z]*c[A-Za-z]*$/i.test(token) ||
      normalized === "-command"
    ) {
      const nested = tokenAt(args, i + 1);
      return { nestedCommands: nested ? [nested] : [] };
    }

    if (!token.startsWith("-")) {
      break;
    }
  }

  return {};
}
