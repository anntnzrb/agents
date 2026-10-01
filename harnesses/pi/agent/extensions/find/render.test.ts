import { expect, test } from "bun:test";
import { initTheme, ToolExecutionComponent, type ExtensionAPI, type Theme, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { visibleWidth, type TUI } from "@earendil-works/pi-tui";
import registerFind from "./index.ts";
import { renderFindCall, renderFindResult } from "./render.ts";

const theme: Pick<Theme, "fg" | "bold"> = {
  fg: (color, text) => `<${color}>${text}</${color}>`,
  bold: (text) => text,
};
const details = {
  model: "provider/judge",
  hits: [
    { path: "src/retry.ts", start: 12, end: 30, p: 0.93, snippet: "function retry() {}" },
    { path: "src/retry.ts", start: 40, end: 55, p: 0.81, snippet: "function backoff() {}" },
  ],
};

test("query and scope remain readable in every lifecycle state", () => {
  for (const state of [
    { executionStarted: false, isPartial: true, isError: false },
    { executionStarted: true, isPartial: true, isError: false },
    { executionStarted: true, isPartial: false, isError: false },
    { executionStarted: true, isPartial: false, isError: true },
  ]) {
    const text = renderFindCall({ query: "retry\n backoff", path: "src/" }, state, theme).render(200).join("\n");
    expect(text).toContain("“retry backoff”");
    expect(text).toContain("src/");
    expect(text).not.toContain("query=");
  }
});

test("compact results count unique files and show ranked locations without snippets", () => {
  const text = renderFindResult(details, "", { isError: false, expanded: false }, theme).render(200).join("\n");
  expect(text).toContain("1 file · 2 ranges");
  expect(text).toContain("<muted>  src/ · best 93%</muted>");
  expect(text).toContain("<accent>retry.ts</accent><muted>:12–30 · </muted><success>93%</success>");
  expect(text).toContain("<text>81%</text>");
  expect(text).not.toContain("function");
  expect(text).not.toContain("provider/judge");
  const expanded = renderFindResult(details, "", { isError: false, expanded: true }, theme).render(200).join("\n");
  expect(expanded).toContain("function retry");
  expect(expanded).toContain("provider/judge");
});

test("directory groups are scope-relative and relevance-ordered without changing hits", () => {
  const hits = [
    { ...details.hits[0]!, path: "src/uploads/retry.ts", p: 0.86 },
    { ...details.hits[0]!, path: "src/network/backoff.ts", p: 0.93 },
    { ...details.hits[1]!, path: "src/uploads/retry.ts", p: 0.72 },
    { ...details.hits[0]!, path: "src/uploads/queue.ts", p: 0.9 },
  ];
  const snapshot = JSON.stringify(hits);
  const text = renderFindResult({ ...details, hits }, "", {
    isError: false, expanded: false, scope: "src/", cwd: "/project",
  }, theme).render(200).join("\n");
  expect(text).toContain("  network/");
  expect(text).toContain("  uploads/");
  expect(text).not.toContain("src/uploads");
  expect(text.indexOf("network/")).toBeLessThan(text.indexOf("uploads/"));
  expect(text.indexOf("queue.ts")).toBeLessThan(text.indexOf("retry.ts"));
  expect(text).toContain("<warning>72%</warning>");
  expect(JSON.stringify(hits)).toBe(snapshot);
});

test("long headings elide middle directories only, without colliding, and expansion keeps full paths", () => {
  const hits = [
    { ...details.hits[0]!, path: "services/long-alpha-directory/workers/retry.ts" },
    { ...details.hits[1]!, path: "services/long-beta-directory/workers/retry.ts" },
  ];
  const plain = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
  const single = renderFindResult({ ...details, hits: hits.slice(0, 1) }, "", { isError: false, expanded: false }, plain);
  expect(single.render(30).join("\n")).toContain("services/…/workers/");
  const grouped = renderFindResult({ ...details, hits }, "", { isError: false, expanded: false }, plain);
  const text = grouped.render(30).join("\n");
  expect(text).toContain("long-alpha-directory");
  expect(text).toContain("long-beta-directory");
  expect(text).not.toContain("services/…/workers/");
  expect(renderFindResult({ ...details, hits }, "", { isError: false, expanded: true }, theme).render(200).join("\n"))
    .toContain(hits[0]!.path);
});

test("compact limits four directories and three ranges, with precise omissions and complete expansion", () => {
  const hits = [
    { ...details.hits[0]!, path: "a/first.ts", p: 0.99 },
    { ...details.hits[1]!, path: "a/first.ts", p: 0.8 },
    { ...details.hits[0]!, path: "a/second.ts", p: 0.98 },
    { ...details.hits[0]!, path: "a/third.ts", p: 0.97 },
    { ...details.hits[0]!, path: "a/fourth.ts", p: 0.96 },
    { ...details.hits[0]!, path: "b/first.ts", p: 0.95 },
    { ...details.hits[0]!, path: "c/first.ts", p: 0.94 },
    { ...details.hits[0]!, path: "c/second.ts", p: 0.93 },
    { ...details.hits[0]!, path: "d/first.ts", p: 0.92 },
    { ...details.hits[0]!, path: "e/first.ts", p: 0.91 },
  ];
  const plain = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
  const show = (expanded: boolean, selected = hits) => renderFindResult({ ...details, hits: selected }, "", { isError: false, expanded }, plain).render(200).join("\n");
  const compact = show(false);
  expect(compact).toContain("9 files · 10 ranges");
  expect(compact).toContain("a/ · best 99%");
  expect(compact).toContain("b/ · best 95%");
  expect(compact).toContain("c/");
  expect(compact).toContain("d/");
  expect(compact).not.toContain("e/");
  expect(compact).not.toContain("fourth.ts");
  expect(compact).not.toContain("first.ts:40–55 · 80%");
  expect(compact).toContain("… 1 more directory · 2 more ranges in shown directories");
  const expanded = show(true);
  for (const hit of hits) expect(expanded).toContain(hit.path);
  expect(expanded).not.toContain("more directory");
  expect(show(false, hits.filter((hit) => !hit.path.startsWith("e/"))))
    .toContain("… 2 more ranges in shown directories");
  const directoryOnly = show(false, hits.filter((hit) => hit.path !== "a/fourth.ts" && hit.p !== 0.8));
  expect(directoryOnly).toContain("… 1 more directory");
  expect(directoryOnly).not.toContain("in shown directories");
  expect(show(false, hits.filter((hit) => hit.path === "a/first.ts"))).not.toContain("…");
});

test("actual Pi component switches columns on pane resize, respects Unicode widths, and stacks expansion", () => {
  let tool: ToolDefinition | undefined;
  registerFind({ registerTool: (definition: ToolDefinition) => { tool = definition; } } as ExtensionAPI);
  if (!tool) throw new Error("find was not registered");
  initTheme("dark", false);
  const component = new ToolExecutionComponent("find", "columns-test", { query: "render results" }, {}, tool,
    { requestRender() {} } as TUI);
  const hits = [
    { ...details.hits[0]!, path: "a/界面.ts", p: 0.99 },
    { ...details.hits[1]!, path: "a/界面.ts", p: 0.9 },
    { ...details.hits[0]!, path: "b/worker.ts", p: 0.95 },
  ];
  component.setArgsComplete();
  component.updateResult({ content: [{ type: "text", text: "" }], details: { ...details, hits }, isError: false });
  const clean = (width: number) => component.render(width).map((line) => line.replace(/\x1b\[[0-9;]*m/g, ""));
  const sideBySide = (width: number) => clean(width).some((line) => line.includes("a/ · best") && line.includes("b/ · best"));
  expect(sideBySide(100)).toBe(true);
  const wide = clean(100);
  expect(wide.some((line) => line.includes("界面.ts:12–30") && line.includes("worker.ts:12–30"))).toBe(true);
  expect(wide.some((line) => line.includes("界面.ts:40–55"))).toBe(true);
  expect(sideBySide(40)).toBe(false);
  expect(sideBySide(100)).toBe(true);
  for (const width of [15, 25, 40, 60, 100]) {
    expect(component.render(width).every((line) => visibleWidth(line) <= width)).toBe(true);
  }
  component.setExpanded(true);
  expect(sideBySide(100)).toBe(false);
  expect(clean(100).join("\n")).toContain("a/界面.ts");
  component.setExpanded(false);
  component.updateResult({ content: [{ type: "text", text: "" }], details: { ...details, hits: [
    hits[0]!, { ...hits[2]!, path: `b/${"long-name-".repeat(8)}.ts` },
  ] }, isError: false });
  expect(sideBySide(100)).toBe(false);
});

test("four groups adapt through four, three, two and one columns without losing rows", () => {
  const plain = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
  const hits = ["a", "b", "c", "d"].flatMap((directory, index) => [
    { ...details.hits[0]!, path: `${directory}/x.ts`, p: 0.99 - index * 0.01 },
    { ...details.hits[1]!, path: `${directory}/y.ts`, p: 0.8 - index * 0.01 },
  ]);
  const component = renderFindResult({ ...details, hits }, "", { isError: false, expanded: false }, plain);
  // Each block is 22 columns, with a four-column gutter.
  for (const [width, columns] of [[100, 4], [74, 3], [48, 2], [30, 1], [100, 4]]) {
    const lines = component.render(width!);
    expect(lines.find((line) => line.includes("a/ · best"))?.match(/best/g)?.length).toBe(columns);
    for (const directory of ["a", "b", "c", "d"]) expect(lines.join("\n")).toContain(`${directory}/ · best`);
    expect(lines.filter((line) => line.includes("x.ts:")).join("\n").match(/x\.ts:/g)?.length).toBe(4);
    expect(lines.every((line) => visibleWidth(line) <= width!)).toBe(true);
  }
});

test("no hits are a warning and errors retain bounded diagnostics", () => {
  expect(renderFindResult({ ...details, hits: [] }, "", { isError: false, expanded: false }, theme).render(200).join("\n"))
    .toContain("<warning>  No verified hits</warning>");
  const text = renderFindResult(undefined, "classifier failed\na\nb\nc\nd", { isError: true, expanded: false }, theme).render(200).join("\n");
  expect(text).toContain("classifier failed");
  expect(text).toContain("1 more lines");
});

test("direct registration and actual Pi component keep the query after completion", () => {
  let tool: ToolDefinition | undefined;
  registerFind({ registerTool: (definition: ToolDefinition) => { tool = definition; } } as ExtensionAPI);
  if (!tool) throw new Error("find was not registered");
  expect(tool.exposure).toBe("direct");
  initTheme("dark", false);
  const ui = { requestRender() {} } as TUI;
  const component = new ToolExecutionComponent("find", "find-ui-test", { query: "retry backoff", path: "src/" }, {}, tool, ui);
  const text = () => component.render(80).join("\n").replace(/\x1b\[[0-9;]*m/g, "");
  expect(text()).toContain("composing");
  component.setArgsComplete();
  component.markExecutionStarted();
  expect(text()).toContain("searching");
  component.updateResult({ content: [{ type: "text", text: "raw report" }], details, isError: false });
  expect(text()).toContain("retry backoff");
  expect(text()).toContain("1 file · 2 ranges");
  expect(text()).not.toContain("searching");
  expect(text()).not.toContain("raw report");
  for (const width of [20, 40, 80]) {
    expect(component.render(width).every((line) => visibleWidth(line) <= width)).toBe(true);
  }
  component.setExpanded(true);
  expect(text()).toContain("function retry");
  component.updateResult({ content: [{ type: "text", text: "classifier failed" }], details: undefined, isError: true });
  expect(text()).toContain("failed");
  expect(text()).toContain("retry backoff");
});
