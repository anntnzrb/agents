import { createCodemodeExtension, keyHint, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";

// Display-only: recognize quoted patch bodies, including unfinished streaming literals.
export function elidePatchLiterals(code: string): string {
  return code.replace(/"(?:\\[\s\S]|[^"\\])*"?|'(?:\\[\s\S]|[^'\\])*'?|`(?:\\[\s\S]|[^`\\])*`?/g,
    (literal) => literal.slice(1).trimStart().startsWith("*** Begin Patch") ? "<PATCH>" : literal);
}

// Reuse the host definition so execution, loadout, storage, and results stay native.
export function registerCompactCodemode(pi: ExtensionAPI) {
  return createCodemodeExtension()({
    ...pi,
    registerTool(tool) {
      const renderCall = tool.renderCall;
      if (!renderCall) throw new Error("Pi codemode has no call renderer");
      pi.registerTool({
        ...tool,
        renderCall(args, theme, context) {
          const displayArgs = !context.expanded && typeof args.code === "string"
            ? { ...args, code: elidePatchLiterals(args.code) } : args;
          const full = renderCall(displayArgs, theme, { ...context, expanded: true, lastComponent: undefined });
          if (context.expanded) return full;
          return {
            render(width) {
              const lines = full.render(width);
              // Keep the title and three visual lines, including wrapped string literals.
              if (lines.length <= 4) return lines;
              const hint = theme.fg("muted", `… (${lines.length - 4} more lines, `)
                + keyHint("app.tools.expand", "to expand") + theme.fg("muted", ")");
              return [...lines.slice(0, 4), truncateToWidth(hint, width)];
            },
            invalidate() { full.invalidate(); },
          };
        },
      });
    },
  });
}
