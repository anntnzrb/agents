export function executableBasename(value: string): string {
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] ?? value;
}

export function isAssignmentToken(token: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*=.*/.test(token);
}

export function unique(values: string[]): string[] {
  return [...new Set(values.filter((value) => value.length > 0))];
}

const HEREDOC_PATTERN = /<<-?\s*(?!<)(["']?)([A-Za-z_][A-Za-z0-9_-]*)\1/g;

function isOutsideQuotes(value: string): boolean {
  let inSingle = false;
  let inDouble = false;
  let escaped = false;

  for (const ch of value) {
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === "\\" && !inSingle) {
      escaped = true;
      continue;
    }
    if (ch === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (ch === '"' && !inSingle) {
      inDouble = !inDouble;
    }
  }

  return !inSingle && !inDouble;
}

export function stripHeredocBodies(command: string): string {
  const lines = command.split(/\r?\n/);
  const kept: string[] = [];
  const pendingDelimiters: string[] = [];

  for (const line of lines) {
    if (pendingDelimiters.length > 0) {
      if (line.trim() === pendingDelimiters[0]) {
        pendingDelimiters.shift();
      }
      continue;
    }

    kept.push(line);
    HEREDOC_PATTERN.lastIndex = 0;
    for (const match of line.matchAll(HEREDOC_PATTERN)) {
      if (match.index !== undefined && isOutsideQuotes(line.slice(0, match.index))) {
        pendingDelimiters.push(match[2] ?? "");
      }
    }
  }

  return kept.join("\n");
}

export type ShellSegment = {
  text: string;
  stdinFromPipe: boolean;
  stdoutToPipe: boolean;
};

export function splitShellSegmentsDetailed(command: string): ShellSegment[] {
  const normalizedCommand = stripHeredocBodies(command);
  const segments: ShellSegment[] = [];
  let current = "";
  let inSingle = false;
  let inDouble = false;
  let inTemplate = false;
  let escaped = false;
  let nextStdinFromPipe = false;

  const push = (separator?: "pipe" | "other") => {
    const trimmed = current.trim();
    if (trimmed.length > 0) {
      segments.push({ text: trimmed, stdinFromPipe: nextStdinFromPipe, stdoutToPipe: separator === "pipe" });
    }
    current = "";
    nextStdinFromPipe = separator === "pipe";
  };

  for (let i = 0; i < normalizedCommand.length; i += 1) {
    const ch = normalizedCommand[i];
    if (ch === undefined) {
      continue;
    }

    const next = normalizedCommand[i + 1];

    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }

    if (ch === "\\" && !inSingle) {
      current += ch;
      escaped = true;
      continue;
    }

    if (ch === "'" && !inDouble && !inTemplate) {
      inSingle = !inSingle;
      current += ch;
      continue;
    }

    if (ch === '"' && !inSingle && !inTemplate) {
      inDouble = !inDouble;
      current += ch;
      continue;
    }

    if (ch === "`" && !inSingle && !inDouble) {
      inTemplate = !inTemplate;
      current += ch;
      continue;
    }

    if (!inSingle && !inDouble && !inTemplate) {
      if (ch === "\n" || ch === ";") {
        push("other");
        continue;
      }

      if ((ch === "&" && next === "&") || (ch === "|" && next === "|")) {
        push("other");
        i += 1;
        continue;
      }

      if (ch === "|") {
        push("pipe");
        continue;
      }
    }

    current += ch;
  }

  push("other");
  return segments;
}

export function splitShellSegments(command: string): string[] {
  return splitShellSegmentsDetailed(command).map((segment) => segment.text);
}

export function tokenizeCommand(segment: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let inSingle = false;
  let inDouble = false;
  let escaped = false;

  const push = () => {
    if (current.length > 0) {
      tokens.push(current);
      current = "";
    }
  };

  for (let i = 0; i < segment.length; i += 1) {
    const ch = segment[i];
    if (ch === undefined) {
      continue;
    }

    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }

    if (ch === "\\" && !inSingle) {
      escaped = true;
      continue;
    }

    if (ch === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }

    if (ch === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }

    if (!inSingle && !inDouble && /\s/.test(ch)) {
      push();
      continue;
    }

    current += ch;
  }

  push();
  return tokens;
}
