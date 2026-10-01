// Each sibling module is named after the tool it restyles and exports a
// transform over that tool's rendered call and result. Tool results sent to
// the model are untouched; only the transcript view changes. Each transform
// decides how an error result renders.
import { toolRenderers } from "@oh-my-pi/pi-tui/tools";
import bash from "./bash.ts";
import edit from "./edit.ts";
import evaluate from "./eval.ts";
import find from "./find.ts";
import glob from "./glob.ts";
import grep from "./grep.ts";
import read from "./read.ts";
import type { Transform } from "./transforms.ts";
import write from "./write.ts";

// `edit` also covers `apply_patch`: both registry keys share one renderer.
const overrides: Record<string, Transform> = { bash, edit, eval: evaluate, find, glob, grep, read, write };

// Keep the built-in hooks so reloads and repeated session starts never wrap a wrapper.
const ORIGINAL = Symbol.for("smolui.original");

export function install() {
	for (const [name, transform] of Object.entries(overrides)) {
		const renderer = toolRenderers[name];
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
