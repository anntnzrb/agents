import type { Theme } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";

type PatchTheme = Pick<Theme, "fg" | "bold">;

interface PatchFile {
  operation: "A" | "M" | "D" | "R";
  path: string;
  destination?: string;
  added: number;
  removed: number;
}

// This is a display summary, not a replacement for Codex's patch parser.
// During streaming, ignore the unterminated last line (especially partial paths).
export function summarizePatch(input: string, complete: boolean): PatchFile[] {
  const lines = input.replace(/\r\n/g, "\n").split("\n");
  if (!complete) lines.pop();
  const files: PatchFile[] = [];
  let current: PatchFile | undefined;
  for (const line of lines) {
    const header = /^\*\*\* (Add File|Update File|Delete File): (.+)$/.exec(line);
    if (header) {
      current = {
        operation: header[1] === "Add File" ? "A" : header[1] === "Delete File" ? "D" : "M",
        path: header[2]!.trimEnd(), added: 0, removed: 0,
      };
      files.push(current);
    } else if (current && line.startsWith("*** Move to: ")) {
      current.operation = "R";
      current.destination = line.slice("*** Move to: ".length).trimEnd();
    } else if (line === "*** End Patch") {
      current = undefined;
    } else if (current && line.startsWith("+")) {
      current.added++;
    } else if (current && line.startsWith("-")) {
      current.removed++;
    }
  }
  return files;
}

function counts(added: number, removed: number, theme: PatchTheme): string {
  return [
    added ? theme.fg("success", `+${added}`) : "",
    removed ? theme.fg("error", `−${removed}`) : "",
  ].filter(Boolean).join(" ");
}

export function renderPatchCall(
  input: string,
  context: { argsComplete: boolean; executionStarted: boolean; isPartial: boolean; isError: boolean },
  theme: PatchTheme,
): Text {
  const title = theme.fg("toolTitle", theme.bold("apply_patch"));
  if (context.isError) {
    return new Text(`${title} · ${theme.fg("error", "failed")} · ${theme.fg("warning", "changes may be partial")}`, 0, 0);
  }
  const files = summarizePatch(input, context.argsComplete);
  const finished = !context.isPartial;
  const added = files.reduce((sum, file) => sum + file.added, 0);
  const removed = files.reduce((sum, file) => sum + file.removed, 0);
  const total = counts(added, removed, theme);
  const status = finished
    ? `${files.length} ${files.length === 1 ? "file" : "files"}${total ? " · patch " : ""}`
    : context.executionStarted ? "applying" : "composing";
  const lines = [`${title} · ${theme.fg("muted", status)}${finished ? total : ""}`];
  for (const file of files) {
    const color = file.operation === "A" ? "success" : file.operation === "D" ? "error"
      : file.operation === "R" ? "accent" : "warning";
    const path = file.destination ? `${file.path} → ${file.destination}` : file.path;
    const change = finished ? counts(file.added, file.removed, theme) : "";
    lines.push(`  ${theme.fg(color, file.operation)} ${path}${change ? `  ${change}` : ""}`);
  }
  return new Text(lines.join("\n"), 0, 0);
}

export function renderPatchResult(output: string, isError: boolean, expanded: boolean, theme: PatchTheme): Text {
  if (!isError && !expanded) return new Text("", 0, 0);
  const lines = output.trimEnd().split("\n");
  const visible = expanded ? lines : lines.slice(0, 4);
  if (visible.length < lines.length) visible.push(`… ${lines.length - visible.length} more lines (expand for details)`);
  return new Text(theme.fg(isError ? "error" : "toolOutput", visible.join("\n")), 0, 0);
}
