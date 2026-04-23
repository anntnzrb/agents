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

export function splitShellSegments(command: string): string[] {
  const segments: string[] = [];
  let current = "";
  let inSingle = false;
  let inDouble = false;
  let inTemplate = false;
  let escaped = false;

  const push = () => {
    const trimmed = current.trim();
    if (trimmed.length > 0) {
      segments.push(trimmed);
    }
    current = "";
  };

  for (let i = 0; i < command.length; i += 1) {
    const ch = command[i];
    if (ch === undefined) {
      continue;
    }

    const next = command[i + 1];

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
        push();
        continue;
      }

      if ((ch === "&" && next === "&") || (ch === "|" && next === "|")) {
        push();
        i += 1;
        continue;
      }

      if (ch === "|") {
        push();
        continue;
      }
    }

    current += ch;
  }

  push();
  return segments;
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
