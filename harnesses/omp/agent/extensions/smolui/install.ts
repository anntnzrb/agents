// Each tool below maps to a view over its collapsed rows. Tool results sent
// to the model are untouched; only the terminal transcript changes. Native
// hosts (Tern) call the renderer's `describe*` hooks instead, so they always
// see omp's own view.
//
// Every seam with omp fails open. A missing registry entry, an unrecognised
// card shape, or a view that throws leaves the stock rows on screen, so an omp
// update can make cards noisier but never hides or breaks them.
import { type Component, visibleWidth } from "@oh-my-pi/pi-tui";
import type { Theme } from "@oh-my-pi/pi-tui/theme";
import { type RenderResultOptions, type ToolRenderer, toolRenderers } from "@oh-my-pi/pi-tui/tools";
import bash from "./bash.ts";
import evaluate from "./eval.ts";
import { titleOnly, type View } from "./transforms.ts";

/** Tool name → view. `edit` also covers `apply_patch`: both keys share one renderer. */
export const views: Readonly<Record<string, View>> = {
	bash,
	eval: evaluate,
	edit: titleOnly,
	find: titleOnly,
	glob: titleOnly,
	grep: titleOnly,
	read: titleOnly,
	write: titleOnly,
};

type Hooks = Pick<ToolRenderer, "renderCall" | "renderResult">;
type Patched = ToolRenderer & { [ORIGINAL]?: Hooks };

// Keeps the built-in hooks so reloads and repeated session starts never wrap a wrapper.
const ORIGINAL = Symbol.for("smolui.original");

/** Tool names in `views` that this omp build has no renderer for. */
export const missing = (): string[] => Object.keys(views).filter(name => !toolRenderers[name]);

/**
 * Wraps a component so collapsed renders go through `view`. Everything except
 * `render` reaches the original bound to itself: the framed-block marker,
 * cache release, disposal, input, and `describe`. ToolCard keeps state in
 * private fields, which a prototype-chained wrapper could not reach.
 */
const restyle = (
	component: Component,
	view: View,
	options: RenderResultOptions,
	theme: Theme,
	isError: boolean,
): Component => {
	let source: readonly string[] | undefined;
	let shown: readonly string[] = [];
	const render = (width: number): readonly string[] => {
		const lines = component.render(width);
		if (options.expanded) return lines;
		// Same stock rows → same array, which the TUI relies on to skip repaints.
		if (lines === source) return shown;
		source = lines;
		shown = shield(view, lines, theme, isError, width);
		return shown;
	};
	return new Proxy(component, {
		get(target, key) {
			if (key === "render") return render;
			const value: unknown = Reflect.get(target, key, target);
			return typeof value === "function" ? value.bind(target) : value;
		},
	});
};

/** Runs a view and falls back to the stock rows for any result the TUI could not safely draw. */
const shield = (
	view: View,
	lines: readonly string[],
	theme: Theme,
	isError: boolean,
	width: number,
): readonly string[] => {
	try {
		const next = view(lines, theme, isError);
		if (!next || next.length === 0 || next.length > lines.length) return lines;
		return next.every(line => visibleWidth(line) <= width) ? next : lines;
	} catch {
		return lines;
	}
};

export function install() {
	for (const [name, view] of Object.entries(views)) {
		const renderer: Patched | undefined = toolRenderers[name];
		if (!renderer) continue;
		const original = (renderer[ORIGINAL] ??= {
			renderCall: renderer.renderCall,
			renderResult: renderer.renderResult,
		});
		renderer.renderCall = (args, options, theme) => {
			const component = original.renderCall.call(renderer, args, options, theme);
			return component && restyle(component, view, options, theme, false);
		};
		renderer.renderResult = (result, options, theme, args) => {
			const component = original.renderResult.call(renderer, result, options, theme, args);
			return component && restyle(component, view, options, theme, result.isError === true);
		};
	}
}
