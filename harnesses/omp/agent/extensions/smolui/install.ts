// Each tool listed below maps to a transform over its rendered call and
// result; `bash` and `eval` get their own modules, the rest collapse to the
// header. Tool results sent to the model are untouched; only the transcript
// view changes. Each transform decides how an error result renders.
import { type ToolRenderer, toolRenderers } from "@oh-my-pi/pi-tui/tools";
import bash from "./bash.ts";
import evaluate from "./eval.ts";
import { headerOnly, type Transform } from "./transforms.ts";

// `edit` also covers `apply_patch`: both registry keys share one renderer.
const overrides: Record<string, Transform> = {
	bash,
	eval: evaluate,
	edit: headerOnly,
	find: headerOnly,
	glob: headerOnly,
	grep: headerOnly,
	read: headerOnly,
	write: headerOnly,
};

// Keep the built-in hooks so reloads and repeated session starts never wrap a wrapper.
const ORIGINAL = Symbol.for("smolui.original");
type Patched = ToolRenderer & { [ORIGINAL]?: Pick<ToolRenderer, "renderCall" | "renderResult"> };

export function install() {
	for (const [name, transform] of Object.entries(overrides)) {
		const renderer: Patched | undefined = toolRenderers[name];
		if (!renderer) continue;
		const original = (renderer[ORIGINAL] ??= {
			renderCall: renderer.renderCall,
			renderResult: renderer.renderResult,
		});
		renderer.renderCall = (args, options, theme) => {
			const component = original.renderCall.call(renderer, args, options, theme);
			return component && transform(component, options, theme);
		};
		renderer.renderResult = (result, options, theme, args) => {
			const component = original.renderResult.call(renderer, result, options, theme, args);
			return component && transform(component, options, theme, result.isError === true);
		};
	}
}
