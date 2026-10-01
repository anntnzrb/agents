import type { Component } from "@oh-my-pi/pi-tui";
import type { RenderResultOptions } from "@oh-my-pi/pi-tui/tools";
import type { Theme } from "@oh-my-pi/pi-tui/theme";

/** Restyles a built-in tool's rendered call or result component. */
export type Transform = (
	component: Component,
	options: RenderResultOptions,
	theme: Theme,
	isError?: boolean,
) => Component;

type Row = "top" | "tee" | "bottom" | "body" | "other";

const SGR = "(?:\\x1b\\[[0-9;:]*m)*";
// Trailing styling and padding after a box's right edge.
const TAIL = "(?:\\x1b\\[[0-9;:]*m|\\s)*$";
const escape = (text: string) => text.replace(/[\\^$.*+?()[\]{}|-]/g, "\\$&");

/**
 * Reads framed tool cards drawn by `renderOutputBlock`. The ASCII symbol
 * preset draws every corner and tee as `+`, so a border row whose glyph fits
 * several kinds is resolved by position: outside a box it opens one; inside,
 * it is a tee when it carries a label or content rows follow, else the bottom.
 */
const frame = (theme: Theme) => {
	const { topLeft, topRight, teeRight, bottomLeft, horizontal, vertical } = theme.boxRound;
	const edge = (char: string) => new RegExp(`^${SGR}${escape(char)}`);
	const top = edge(topLeft);
	const tee = edge(teeRight);
	const bottom = edge(bottomLeft);
	const side = edge(vertical);
	const h = escape(horizontal);
	const lead = new RegExp(`^${SGR}${escape(topLeft)}(?:${SGR}${h})*${SGR} ?`);
	const trail = new RegExp(` ?${SGR}(?:${h}${SGR})*${escape(topRight)}${TAIL}`);
	const labeled = (line: string) => /\s/.test(Bun.stripANSI(line).trim());
	return {
		/** One-row title taken from a top border's label. */
		title: (line: string) => ` ${line.replace(lead, "").replace(trail, "")}\x1b[0m`,
		classify(lines: readonly string[]): Row[] {
			let open = false;
			return lines.map((line, i) => {
				const isTop = top.test(line);
				const isTee = tee.test(line);
				const isBottom = bottom.test(line);
				let kind: Row;
				if (!open) kind = isTop ? "top" : "other";
				else if (isTee && isBottom) {
					const next = lines[i + 1];
					kind = labeled(line) || (next !== undefined && side.test(next)) ? "tee" : "bottom";
				} else if (isTee) kind = "tee";
				else if (isBottom) kind = "bottom";
				else if (isTop) kind = "top";
				else kind = side.test(line) ? "body" : "other";
				if (kind === "top") open = true;
				else if (kind === "bottom") open = false;
				return kind;
			});
		},
	};
};

/**
 * Collapse a card to its title row(s). Framed cards contribute the label from
 * each top border (stacked multi-file edits keep one row per file); frameless
 * cards keep their first line. Errors and expanded cards render in full.
 */
export const headerOnly: Transform = (component, options, theme, isError) => {
	if (isError) return component;
	const { title, classify } = frame(theme);
	return {
		render: width => {
			const lines = component.render(width);
			if (options.expanded) return lines;
			const kinds = classify(lines);
			const titles = lines.filter((_, i) => kinds[i] === "top").map(title);
			return titles.length > 0 ? titles : lines.slice(0, 1);
		},
		invalidate: () => component.invalidate?.(),
	};
};

/**
 * Drop one section's body rows from every framed box, errors included.
 * Section 0 sits under the top border; each tee bar starts the next. Rows
 * whose visible text matches `keep` survive. A section left empty also loses
 * its separator bar, so no hollow band remains; a box left with no rows at all
 * collapses to its title row. Expanded cards render in full.
 */
export const elideSection =
	(section: number, keep?: (text: string, theme: Theme) => boolean): Transform =>
	(component, options, theme) => {
		const { title, classify } = frame(theme);
		const v = escape(theme.boxRound.vertical);
		const body = new RegExp(`^${SGR}${v}${SGR} ?([\\s\\S]*?) ?${SGR}${v}${SGR}\\s*$`);
		return {
			render: width => {
				const lines = component.render(width);
				if (options.expanded) return lines;
				const kinds = classify(lines);
				const out: string[] = [];
				let current = -1;
				// Index in `out` of the bar that opened the target section, and whether any of its rows survived.
				let openedAt = -1;
				let kept = false;
				lines.forEach((line, i) => {
					const kind = kinds[i];
					if (kind === "top" || kind === "tee" || kind === "bottom") {
						const closingEmpty = current === section && !kept;
						if (closingEmpty && section === 0 && kind === "tee") {
							// Empty first section: drop the bar below it so the next section hangs off the title.
							current = 1;
							return;
						}
						if (closingEmpty && section === 0 && kind === "bottom" && openedAt >= 0) {
							// Nothing but the elided section: a hollow frame would hide the status, so keep the title.
							out[openedAt] = title(out[openedAt]);
							current = -1;
							openedAt = -1;
							return;
						}
						if (closingEmpty && section > 0 && openedAt >= 0) out.splice(openedAt, 1);
						current = kind === "top" ? 0 : kind === "tee" ? current + 1 : -1;
						openedAt = current === section ? out.length : -1;
						kept = false;
						out.push(line);
						return;
					}
					const row = current === section && kind === "body" ? body.exec(line) : null;
					if (!row || keep?.(Bun.stripANSI(row[1]).trim(), theme)) {
						if (row) kept = true;
						out.push(line);
					}
				});
				return out;
			},
			invalidate: () => component.invalidate?.(),
		};
	};
