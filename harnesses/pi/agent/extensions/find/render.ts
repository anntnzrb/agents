import { dirname, basename, relative, resolve } from "node:path";
import type { Theme } from "@earendil-works/pi-coding-agent";
import { Text, visibleWidth, type Component } from "@earendil-works/pi-tui";
import type { Hit } from "./index.ts";

type FindTheme = Pick<Theme, "fg" | "bold">;

export function renderFindCall(
  args: { query?: string; path?: string },
  context: { executionStarted: boolean; isPartial: boolean; isError: boolean },
  theme: FindTheme,
): Text {
  const title = theme.fg("toolTitle", theme.bold("find"));
  const status = context.isError ? theme.fg("error", "failed")
    : context.isPartial ? theme.fg("muted", context.executionStarted ? "searching" : "composing") : "";
  const query = (args.query ?? "").replace(/\s+/g, " ").trim();
  const scope = args.path ? ` · ${theme.fg("muted", args.path)}` : "";
  return new Text(`${title}${status ? ` · ${status}` : ""}${query ? `\n  “${query}”${scope}` : scope}`, 0, 0);
}

export function renderFindResult(
  details: { hits: readonly Hit[]; model: string } | undefined,
  output: string,
  options: { isError: boolean; expanded: boolean; scope?: string; cwd?: string },
  theme: FindTheme,
): Component {
  if (options.isError || !details) {
    const lines = output.trimEnd().split("\n");
    const visible = options.expanded ? lines : lines.slice(0, 4);
    if (visible.length < lines.length) visible.push(`… ${lines.length - visible.length} more lines (expand for details)`);
    return new Text(theme.fg(options.isError ? "error" : "toolOutput", visible.join("\n")), 0, 0);
  }
  const { hits } = details;
  if (!hits.length) return new Text(theme.fg("warning", "  No verified hits"), 0, 0);
  const files = new Set(hits.map((hit) => hit.path)).size;
  const groups = new Map<string, Hit[]>();
  for (const hit of hits) {
    const directory = dirname(hit.path);
    const group = groups.get(directory) ?? [];
    group.push(hit);
    groups.set(directory, group);
  }
  const ordered = [...groups].map(([directory, ranges]) => {
    return {
      directory,
      score: Math.max(...ranges.map((hit) => hit.p)),
      ranges: [...ranges].sort((a, b) => b.p - a.p || a.path.localeCompare(b.path) || a.start - b.start),
    };
  }).sort((a, b) => b.score - a.score || a.directory.localeCompare(b.directory));
  const shown = options.expanded ? ordered : ordered.slice(0, 4);
  let hiddenRanges = 0;
  const displayed = shown.map((group) => {
    const ranges = options.expanded ? group.ranges : group.ranges.slice(0, 3);
    hiddenRanges += group.ranges.length - ranges.length;
    return { ...group, ranges };
  });
  return {
    invalidate() {},
    render(width) {
      const headings = displayed.map(({ directory }) => {
        const scoped = options.scope && options.cwd
          ? relative(resolve(options.cwd, options.scope), resolve(options.cwd, directory)) || "."
          : directory;
        const full = `${scoped}/`;
        const budget = width - 2 - ` · best 100%`.length;
        if (options.expanded || visibleWidth(full) <= budget) return full;
        const parts = scoped.split("/");
        // Remove only middle directories; never abbreviate individual names.
        let shortest = full;
        for (let omitted = 1; omitted < parts.length - 1; omitted++) {
          const short = `${parts[0]}/…/${parts.slice(omitted + 1).join("/")}/`;
          shortest = short;
          if (visibleWidth(short) <= budget) return short;
        }
        return shortest;
      });
      const lines = [theme.fg("muted", `  ${files} ${files === 1 ? "file" : "files"} · ${hits.length} ${hits.length === 1 ? "range" : "ranges"}`)];
      const blocks = displayed.map((group, index) => {
        const heading = headings[index]!;
        // Two different directories must never acquire the same shortened label.
        const collision = headings.filter((candidate) => candidate === heading).length > 1;
        const block = [theme.fg("muted", `  ${collision ? `${group.directory}/` : heading} · best ${Math.round(group.score * 100)}%`)];
        for (const hit of group.ranges) {
          const percent = Math.round(hit.p * 100);
          const color = percent >= 90 ? "success" : percent >= 75 ? "text" : "warning";
          const path = options.expanded ? hit.path : basename(hit.path);
          block.push(`    ${theme.fg("accent", path)}${theme.fg("muted", `:${hit.start}–${hit.end} · `)}${theme.fg(color, `${percent}%`)}`);
          if (options.expanded) block.push(theme.fg("toolOutput", `      ${hit.snippet}`));
        }
        return block;
      });
      const gutter = 4;
      const blockWidths = blocks.map((block) => Math.max(...block.map(visibleWidth)));
      let columns = 1;
      let columnWidths = [Math.max(...blockWidths)];
      if (!options.expanded) {
        for (let count = blocks.length; count >= 2; count--) {
          const widths = Array.from({ length: count }, (_, column) =>
            Math.max(...blockWidths.filter((_, index) => index % count === column)));
          if (widths.reduce((sum, value) => sum + value, 0) + gutter * (count - 1) <= width) {
            columns = count;
            columnWidths = widths;
            break;
          }
        }
      }
      for (let offset = 0; offset < blocks.length; offset += columns) {
        if (offset > 0) lines.push("");
        const band = blocks.slice(offset, offset + columns);
        for (let row = 0; row < Math.max(...band.map((block) => block.length)); row++) {
          let line = "";
          band.forEach((block, column) => {
            const cell = block[row] ?? "";
            line += cell;
            if (column < band.length - 1) line += " ".repeat(columnWidths[column]! - visibleWidth(cell) + gutter);
          });
          lines.push(line.trimEnd());
        }
      }
      const omissions: string[] = [];
      const hiddenDirectories = ordered.length - shown.length;
      if (hiddenDirectories) omissions.push(`${hiddenDirectories} more ${hiddenDirectories === 1 ? "directory" : "directories"}`);
      if (hiddenRanges) omissions.push(`${hiddenRanges} more ${hiddenRanges === 1 ? "range" : "ranges"} in shown directories`);
      if (omissions.length) lines.push(theme.fg("muted", `  … ${omissions.join(" · ")}`));
      if (options.expanded) lines.push(theme.fg("muted", `  Classifier: ${details.model}`));
      return new Text(lines.join("\n"), 0, 0).render(width);
    },
  };
}
