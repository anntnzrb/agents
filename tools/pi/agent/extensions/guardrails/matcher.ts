import type { BashAction, ExecutableMatch, GuardrailsConfig, Rule } from "./types.js";

import { executableBasename, splitShellSegments, tokenizeCommand, unique } from "./shell.js";
import { firstExecutableIndex, unwrapCommand } from "./wrappers.js";

const MAX_NESTING_DEPTH = 8;

interface Inspection {
  commands: string[];
  executables: string[];
}

function inspectCommand(command: string, depth = 0): Inspection {
  if (depth > MAX_NESTING_DEPTH) {
    return { commands: [], executables: [] };
  }

  const commandSet = new Set<string>();
  const executableSet = new Set<string>();
  const trimmed = command.trim();
  if (trimmed.length > 0) {
    commandSet.add(trimmed);
  }

  for (const segment of splitShellSegments(command)) {
    commandSet.add(segment);
    const inspected = inspectSegment(segment, depth);
    for (const nestedCommand of inspected.commands) {
      commandSet.add(nestedCommand);
    }
    for (const executable of inspected.executables) {
      executableSet.add(executable);
    }
  }

  return {
    commands: [...commandSet],
    executables: [...executableSet],
  };
}

function inspectSegment(segment: string, depth: number): Inspection {
  const tokens = tokenizeCommand(segment);
  if (tokens.length === 0) {
    return { commands: [], executables: [] };
  }

  return inspectTokens(tokens, depth);
}

function inspectTokens(tokens: string[], depth: number): Inspection {
  if (depth > MAX_NESTING_DEPTH || tokens.length === 0) {
    return { commands: [], executables: [] };
  }

  const index = firstExecutableIndex(tokens);
  if (index >= tokens.length) {
    return { commands: [], executables: [] };
  }

  const executable = tokens[index];
  const commands: string[] = [];
  const executables = [executable];
  const unwrapped = unwrapCommand(tokens, index);

  for (const nestedCommand of unwrapped.nestedCommands ?? []) {
    commands.push(nestedCommand);
    const nested = inspectCommand(nestedCommand, depth + 1);
    commands.push(...nested.commands);
    executables.push(...nested.executables);
  }

  if (unwrapped.remainderTokens && unwrapped.remainderTokens.length > 0) {
    const remainder = inspectTokens(unwrapped.remainderTokens, depth + 1);
    commands.push(...remainder.commands);
    executables.push(...remainder.executables);
  }

  return {
    commands: unique(commands),
    executables: unique(executables),
  };
}

function buildFlags(flags: string | undefined, caseSensitive: boolean | undefined): string {
  if (caseSensitive !== false) {
    return flags ?? "";
  }
  return flags?.includes("i") ? flags : `${flags ?? ""}i`;
}

function matchExecutable(actual: string, match: ExecutableMatch): boolean {
  const names = match.names ?? [];
  const patterns = match.patterns ?? [];
  const flags = buildFlags(match.flags, match.caseSensitive);
  const basename = executableBasename(actual);
  const values = [actual, basename];

  for (const name of names) {
    const normalizedName = match.caseSensitive === false ? name.toLowerCase() : name;
    for (const value of values) {
      const subject = match.caseSensitive === false ? value.toLowerCase() : value;
      if (name.includes("/") || name.includes("\\")) {
        if (subject === normalizedName) {
          return true;
        }
      } else if (subject === normalizedName || executableBasename(subject) === normalizedName) {
        return true;
      }
    }
  }

  for (const pattern of patterns) {
    const regex = new RegExp(pattern, flags);
    if (values.some((value) => regex.test(value))) {
      return true;
    }
  }

  return false;
}

function matchRule(inspection: Inspection, rule: Rule): boolean {
  const match = rule.match;
  if (match.type === "regex") {
    const regex = new RegExp(match.pattern, match.flags ?? "");
    return inspection.commands.some((command) => regex.test(command));
  }

  return inspection.executables.some((executable) => matchExecutable(executable, match));
}

export function actionForCommand(command: string, config: GuardrailsConfig): BashAction | null {
  const inspection = inspectCommand(command);

  for (const rule of config.agentBash.rules) {
    if (matchRule(inspection, rule)) {
      return rule.action;
    }
  }

  return null;
}

export function reasonForCommand(command: string, config: GuardrailsConfig): string | null {
  const action = actionForCommand(command, config);
  return action ? action.message : null;
}
