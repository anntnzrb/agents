import { expect, test } from "bun:test";
import { stripVTControlCharacters } from "node:util";
import { initTheme, type ExtensionAPI, type ToolDefinition, type Theme } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import { elidePatchLiterals, registerCompactCodemode } from "./codemode-preview.ts";

initTheme("dark", false);
const theme = { fg: (_color: string, text: string) => text, bold: (text: string) => text } as Theme;
let tool!: ToolDefinition;
registerCompactCodemode({ registerTool: (definition: ToolDefinition) => { tool = definition; } } as ExtensionAPI);

function context(code: string, expanded = false) {
  return {
    args: { code }, toolCallId: "preview", invalidate() {}, lastComponent: undefined,
    state: {}, cwd: "/", executionStarted: true, argsComplete: true,
    isPartial: false, expanded, showImages: false, isError: false,
  };
}

test("elides long patch scripts at visual widths and restores the full script on expansion", () => {
  const code = `await tools.apply_patch({ input: ${JSON.stringify("*** Begin Patch\n*** Add File: file.txt\n" + "+hello\n".repeat(200) + "*** End Patch")} });`;
  const args = { code };
  const collapsed = tool.renderCall!(args, theme, context(code));
  for (const width of [24, 80, 160]) {
    const lines = collapsed.render(width);
    expect(lines.length).toBeLessThanOrEqual(5);
    expect(lines.every((line) => visibleWidth(line) <= width)).toBe(true);
    const output = stripVTControlCharacters(lines.join(""));
    expect(output).toContain("<PATCH>");
    expect(output).not.toContain("hello");
  }
  // Pi passes the previous wrapper back on redraw and expansion.
  const expanded = tool.renderCall!(args, theme, { ...context(code, true), lastComponent: collapsed });
  const output = stripVTControlCharacters(expanded.render(80).join("")).replace(/\s/g, "");
  expect(output).toContain("***EndPatch");
  expect(expanded.render(80).length).toBeGreaterThan(5);
  expect(args.code).toBe(code);
});

test("elides JSON, single-quoted, template, and streaming patch literals only", () => {
  for (const quote of ['"', "'", "`"]) {
    const body = "*** Begin Patch\n*** Add File: file.txt\n+secret\n*** End Patch";
    const literal = quote === '"' ? JSON.stringify(body) : `${quote}${body}${quote}`;
    expect(elidePatchLiterals(`await tools.apply_patch({ input: ${literal} }); return 42;`))
      .toBe("await tools.apply_patch({ input: <PATCH> }); return 42;");
    expect(elidePatchLiterals(`const patch = ${literal.slice(0, -1)}`))
      .toBe("const patch = <PATCH>");
  }
  const code = 'text("ordinary string with \"quotes\""); return 42;';
  expect(elidePatchLiterals(code)).toBe(code);
});

test("leaves short scripts readable and supports partial arguments and redraws", () => {
  const code = "return 42;";
  const first = tool.renderCall!({ code }, theme, context(code));
  expect(stripVTControlCharacters(first.render(80).join("\n"))).toContain(code);
  const next = tool.renderCall!({ code }, theme, { ...context(code), lastComponent: first });
  next.invalidate();
  expect(next.render(80)).toEqual(first.render(80));
  expect(tool.renderCall!({}, theme, context("")).render(80).length).toBeLessThanOrEqual(4);
});
