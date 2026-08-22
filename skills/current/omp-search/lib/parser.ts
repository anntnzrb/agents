import type { SearchSource } from "./models.ts";

export const ANSI_RE = /\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
export const OSC_RE = /\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
export const HEADER_RE = /Web Search:\s*(?<provider>.+?)\s+(?<count>\d+)\s+sources?\b/;
export const SECTION_RE = /[-─]{3,}\s*(?<name>Answer|Sources|Metadata)\b/i;
export const SOURCE_RE =
  /^(?:[+*-]|[\u251c\u2514\u2500─]+\s*)\s*(?<title>.+?)\s+\((?<domain>[^();·]+?)(?:[;·]\s*(?<ageIn>[^()]+?))?\)(?:\s*[·;]\s*(?<ageOut>.+?))?$/;
export const MORE_LINES_RE = /(?:…|\.\.\.)\s*\d+\s+more\s+lines/;
export const SECRET_RE = /\bsk-[a-z0-9_-]{8,}\b/gi;
export const ASSIGNMENT_SECRET_RE =
  /(\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)\b\s*[=:]\s*)\S+/gi;
export const AUTH_SECRET_RE = /(\bAuthorization\s*:\s*Bearer\s+)\S+/gi;

export function stripTerminalControls(value: string): string {
  let cleaned = value.replace(OSC_RE, "");
  cleaned = cleaned.replace(ANSI_RE, "");
  return cleaned.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

export function redact(value: string): string {
  let cleaned = value.replace(SECRET_RE, "<redacted>");
  cleaned = cleaned.replace(ASSIGNMENT_SECRET_RE, "$1<redacted>");
  return cleaned.replace(AUTH_SECRET_RE, "$1<redacted>");
}

export function frameContent(line: string): string {
  let content = line;
  if (content.includes("│")) {
    const firstIdx = content.indexOf("│");
    content = content.slice(firstIdx + 1);
    if (content.includes("│")) {
      const lastIdx = content.lastIndexOf("│");
      content = content.slice(0, lastIdx);
    }
  }
  return content.trimEnd();
}

export interface ParsedSearchOutput {
  readonly query: string;
  readonly provider: string;
  readonly answer: string;
  readonly sources: readonly SearchSource[];
  readonly truncated: boolean;
  readonly parsed: boolean;
  readonly cleanedRaw: string;
}

export function parseSearchOutput(
  raw: string,
  fallbackQuery: string
): ParsedSearchOutput {
  const cleaned = stripTerminalControls(raw);
  const lines = cleaned.split("\n");
  let provider: string | null = null;
  let actualQuery = fallbackQuery;
  const answerLines: string[] = [];
  const sources: SearchSource[] = [];
  let section: "answer" | "sources" | "metadata" | null = null;
  let started = false;

  for (const line of lines) {
    if (!started) {
      const headerMatch = line.match(HEADER_RE);
      const providerGroup = headerMatch?.groups?.["provider"];
      if (providerGroup) {
        provider = providerGroup.trim();
        started = true;
        continue;
      }
    }

    if (line.includes("---") || line.includes("───")) {
      const sectionMatch = line.match(SECTION_RE);
      const nameGroup = sectionMatch?.groups?.["name"];
      if (nameGroup) {
        section = nameGroup.toLowerCase() as
          | "answer"
          | "sources"
          | "metadata";
        started = true;
        continue;
      }
      if (section !== null) {
        break;
      }
    }

    const content = frameContent(line);
    const trimmed = content.trim();

    if (/^query:\s*/i.test(trimmed)) {
      actualQuery = trimmed.replace(/^query:\s*/i, "").trim() || fallbackQuery;
      continue;
    }

    if (section === "answer") {
      answerLines.push(content);
    } else if (section === "sources") {
      const match = trimmed.match(SOURCE_RE);
      const title = match?.groups?.["title"];
      const domain = match?.groups?.["domain"];
      const ageIn = match?.groups?.["ageIn"];
      const ageOut = match?.groups?.["ageOut"];
      const age = ageIn || ageOut;
      if (title && domain) {
        sources.push({
          title: title.trim(),
          domain: domain.trim(),
          age: age ? age.trim() : null,
        });
      }
    } else if (section === "metadata" && /^provider:\s*/i.test(trimmed)) {
      provider = trimmed.replace(/^provider:\s*/i, "").trim() || provider;
    }
  }

  while (answerLines.length > 0 && !answerLines[0]) {
    answerLines.shift();
  }
  while (answerLines.length > 0 && !answerLines[answerLines.length - 1]) {
    answerLines.pop();
  }

  const answer = answerLines.join("\n");
  const truncated = MORE_LINES_RE.test(cleaned);
  const parsed = Boolean(provider || answer || sources.length > 0);

  return {
    query: actualQuery,
    provider: provider || "unknown",
    answer,
    sources,
    truncated,
    parsed,
    cleanedRaw: cleaned,
  };
}
