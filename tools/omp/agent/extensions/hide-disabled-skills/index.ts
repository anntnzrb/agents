import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const SKILL_FILE = "SKILL.md";
const SKILLS_HEADING = "# Skills";
const FRONTMATTER_DELIMITER = "---";

export interface SkillFrontmatter {
  readonly name: string | undefined;
  readonly disableModelInvocation: boolean;
}

export function parseSkillFrontmatter(text: string): SkillFrontmatter {
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== FRONTMATTER_DELIMITER) {
    return { name: undefined, disableModelInvocation: false };
  }

  let name: string | undefined;
  let disableModelInvocation = false;

  for (let index = 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line === undefined) break;

    const trimmed = line.trim();
    if (trimmed === FRONTMATTER_DELIMITER) break;
    if (trimmed.length === 0 || trimmed.startsWith("#")) continue;

    const separatorIndex = trimmed.indexOf(":");
    if (separatorIndex <= 0) continue;

    const key = trimmed.slice(0, separatorIndex).trim();
    const value = unquoteYamlScalar(trimmed.slice(separatorIndex + 1).trim());

    if (key === "name") {
      name = value.length > 0 ? value : undefined;
    } else if (key === "disable-model-invocation") {
      disableModelInvocation = value === "true";
    }
  }

  return { name, disableModelInvocation };
}

export async function scanSkillRoot(root: string): Promise<Set<string>> {
  const disabled = new Set<string>();
  let entries: fs.Dirent[];

  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch (error) {
    if (isEnoent(error)) return disabled;
    throw error;
  }

  await Promise.all(
    entries.map(async (entry) => {
      if (entry.name.startsWith(".") || (!entry.isDirectory() && !entry.isSymbolicLink())) {
        return;
      }

      const skillPath = path.join(root, entry.name, SKILL_FILE);
      const skillFile = Bun.file(skillPath);
      let text: string;
      try {
        text = await skillFile.text();
      } catch (error) {
        if (isEnoent(error) || isNotDir(error)) return;
        throw error;
      }

      const frontmatter = parseSkillFrontmatter(text);
      if (!frontmatter.disableModelInvocation) return;

      disabled.add(frontmatter.name?.trim() || entry.name);
    })
  );

  return disabled;
}

export async function disabledSkillNames(cwd: string): Promise<Set<string>> {
  const disabled = new Set<string>();
  const sets = await Promise.all(skillRoots(cwd).map((root) => scanSkillRoot(root)));
  for (const set of sets) {
    for (const name of set) {
      disabled.add(name);
    }
  }
  return disabled;
}

function skillRoots(cwd: string): string[] {
  return [path.join(os.homedir(), ".omp", "agent", "skills"), path.join(cwd, ".omp", "skills")];
}

export function filterSkillsSection(block: string, disabled: ReadonlySet<string>): string {
  if (disabled.size === 0 || !block.includes(SKILLS_HEADING)) return block;

  const lines = block.split("\n");
  const output: string[] = [];
  let changed = false;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line !== SKILLS_HEADING) {
      output.push(line ?? "");
      continue;
    }

    const sectionEnd = nextHeadingIndex(lines, index + 1);
    const body = lines.slice(index + 1, sectionEnd);
    const filteredBody = body.filter((bodyLine) => {
      const skillName = skillListName(bodyLine);
      if (skillName === undefined || !disabled.has(skillName)) return true;
      changed = true;
      return false;
    });

    if (hasSkillListEntries(filteredBody)) {
      output.push(line, ...filteredBody);
    } else {
      changed = true;
      output.push(...trimBlankLines(filteredBody));
    }

    index = sectionEnd - 1;
  }

  return changed ? output.join("\n") : block;
}

export default function hideDisabledSkillsExtension(pi: ExtensionAPI): void {
  pi.on("before_agent_start", async (event, ctx) => {
    const disabled = await disabledSkillNames(ctx.cwd);
    if (disabled.size === 0) return undefined;

    let changed = false;
    const systemPrompt = event.systemPrompt.map((block) => {
      const filtered = filterSkillsSection(block, disabled);
      if (filtered !== block) changed = true;
      return filtered;
    });

    return changed ? { systemPrompt } : undefined;
  });
}

function unquoteYamlScalar(value: string): string {
  const commentStart = value.search(/\s#/);
  const withoutComment = commentStart === -1 ? value : value.slice(0, commentStart).trimEnd();
  if (withoutComment.length < 2) return withoutComment;

  const first = withoutComment[0];
  const last = withoutComment[withoutComment.length - 1];
  if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
    return withoutComment.slice(1, -1).trim();
  }
  return withoutComment;
}

function nextHeadingIndex(lines: readonly string[], start: number): number {
  for (let index = start; index < lines.length; index += 1) {
    const line = lines[index];
    if (line !== undefined && /^#{1,6}\s/.test(line)) return index;
  }
  return lines.length;
}

function skillListName(line: string): string | undefined {
  const match = /^- ([^:\s][^:]*):/.exec(line);
  return match?.[1]?.trim();
}

function hasSkillListEntries(lines: readonly string[]): boolean {
  return lines.some((line) => skillListName(line) !== undefined);
}

function trimBlankLines(lines: readonly string[]): string[] {
  let start = 0;
  let end = lines.length;
  while (start < end && lines[start]?.trim() === "") start += 1;
  while (end > start && lines[end - 1]?.trim() === "") end -= 1;
  return lines.slice(start, end);
}

function isEnoent(error: unknown): boolean {
  return nodeErrorCode(error) === "ENOENT";
}

function isNotDir(error: unknown): boolean {
  return nodeErrorCode(error) === "ENOTDIR";
}

function nodeErrorCode(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error
    ? String((error as { readonly code: unknown }).code)
    : undefined;
}
