import { expect, test } from "bun:test";
import { initTheme, ToolExecutionComponent, type Theme } from "@earendil-works/pi-coding-agent";
import { visibleWidth, type TUI } from "@earendil-works/pi-tui";
import { createApplyPatchTool } from "./index.ts";
import { renderPatchCall, renderPatchResult, summarizePatch } from "./render.ts";

const theme: Pick<Theme, "fg" | "bold"> = {
  fg: (color, text) => `<${color}>${text}</${color}>`,
  bold: (text) => text,
};
const patch = "*** Begin Patch\n*** Update File: src/parser.ts\n@@\n-old\n+new\n+extra\n context\n*** Add File: test.ts\n+test\n*** Delete File: gone.ts\n*** Update File: before.ts\n*** Move to: after.ts\n@@\n-a\n+b\n*** End Patch";
const pending = { argsComplete: false, executionStarted: false, isPartial: true, isError: false };

test("streaming only reveals complete file headers, with no raw input or unstable counts", () => {
  expect(summarizePatch("*** Begin Patch\n*** Update File: src/par", false)).toEqual([]);
  const text = renderPatchCall("*** Begin Patch\n*** Update File: src/parser.ts\n+partial", pending, theme).render(200).join("\n");
  expect(text).toContain("composing");
  expect(text).toContain("<warning>M</warning> src/parser.ts");
  expect(text).not.toContain("partial");
  expect(text).not.toContain("input=");
  expect(text).not.toContain("+1");
  expect(renderPatchCall("", pending, theme).render(200).join("\n")).toContain("composing");
});

test("summarizes adds, deletes, moves, blank changed lines and CRLF without counting context", () => {
  expect(summarizePatch(patch, true)).toEqual([
    { operation: "M", path: "src/parser.ts", added: 2, removed: 1 },
    { operation: "A", path: "test.ts", added: 1, removed: 0 },
    { operation: "D", path: "gone.ts", added: 0, removed: 0 },
    { operation: "R", path: "before.ts", destination: "after.ts", added: 1, removed: 1 },
  ]);
  expect(summarizePatch("*** Add File: blank.txt\r\n+\r\n*** End Patch", true)[0]?.added).toBe(1);
});

test("applying preserves file intent; completion shows theme-colored submitted-patch counts", () => {
  const applying = renderPatchCall(patch, { ...pending, argsComplete: true, executionStarted: true }, theme).render(300).join("\n");
  expect(applying).toContain("applying");
  expect(applying).not.toContain("+4");
  const done = renderPatchCall(patch, { ...pending, argsComplete: true, executionStarted: true, isPartial: false }, theme).render(300).join("\n");
  expect(done).toContain("4 files · patch");
  expect(done).toContain("<success>+4</success> <error>−2</error>");
  expect(done).toContain("<success>A</success> test.ts");
  expect(done).toContain("<error>D</error> gone.ts");
  expect(done).toContain("<accent>R</accent> before.ts → after.ts");
  expect(done).not.toContain("Success");
});

test("failure does not present requested operations as completed; diagnostics stay bounded", () => {
  const call = renderPatchCall(patch, { ...pending, isPartial: false, isError: true }, theme).render(300).join("\n");
  expect(call).toContain("failed");
  expect(call).toContain("changes may be partial");
  expect(call).not.toContain("parser.ts");
  const output = "context missing\na\nb\nc\nd\ne";
  expect(renderPatchResult(output, true, false, theme).render(300).join("\n")).toContain("2 more lines");
  expect(renderPatchResult(output, true, true, theme).render(300).join("\n")).toContain("\ne");
  expect(renderPatchResult("Success", false, false, theme).render(300).join("\n")).not.toContain("Success");
});

test("real Pi tool component transitions through streaming, execution, success and failure at narrow widths", () => {
  initTheme("dark", false);
  const tool = createApplyPatchTool({ exec: async () => ({ stdout: "", stderr: "", code: 0, killed: false }) });
  // Rendering only needs the host's redraw callback, not an attached terminal.
  const ui = { requestRender() {} } as TUI;
  const component = new ToolExecutionComponent("apply_patch", "render-test", { input: "" }, {}, tool, ui);
  const text = () => component.render(80).join("\n").replace(/\x1b\[[0-9;]*m/g, "");
  expect(text()).toContain("composing");
  component.updateArgs({ input: patch });
  component.setArgsComplete();
  component.markExecutionStarted();
  expect(text()).toContain("applying");
  component.updateResult({ content: [{ type: "text", text: "Success. Updated the following files:\nM src/parser.ts" }], details: {}, isError: false });
  expect(text()).toContain("4 files · patch +4 −2");
  expect(text()).not.toContain("applying");
  expect(text()).not.toContain("Success");
  expect(component.render(80).join("\n")).toContain("\x1b[");
  for (const width of [20, 40, 80]) {
    expect(component.render(width).every((line) => visibleWidth(line) <= width)).toBe(true);
  }
  component.setExpanded(true);
  expect(text()).toContain("Success");
  component.setExpanded(false);
  component.updateResult({ content: [{ type: "text", text: "Context not found" }], details: undefined, isError: true });
  expect(text()).toContain("failed");
  expect(text()).toContain("Context not found");
  expect(text()).not.toContain("+4");
});
