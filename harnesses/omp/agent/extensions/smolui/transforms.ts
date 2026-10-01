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

const SGR = "(?:\\x1b\\[[0-9;:]*m)*";
const escape = (text: string) => text.replace(/[\\^$.*+?()[\]{}|-]/g, "\\$&");

/**
 * Collapse a card to its title row(s). Framed cards contribute the label from
 * each top border (stacked multi-file edits keep one row per file); frameless
 * cards keep their first line. Errors and expanded cards render in full.
 */
export const headerOnly: Transform = (component, options, theme, isError) => {
	if (isError) return component;
	const { topLeft, topRight, horizontal } = theme.boxRound;
	const h = escape(horizontal);
	const lead = new RegExp(`^${SGR}${escape(topLeft)}(?:${SGR}${h})*${SGR} ?`);
	const trail = new RegExp(` ?${SGR}(?:${h}${SGR})*${escape(topRight)}[\\s\\S]*$`);
	return {
		render: width => {
			const lines = component.render(width);
			if (options.expanded) return lines;
			const titles = lines.filter(line => lead.test(line)).map(line => ` ${line.replace(lead, "").replace(trail, "")}\x1b[0m`);
			return titles.length > 0 ? titles : lines.slice(0, 1);
		},
		invalidate: () => component.invalidate?.(),
	};
};

/**
 * Drop one section's body rows from every framed box, errors included.
 * Section 0 sits under the top border; each `├─` bar starts the next. Rows
 * whose visible text matches `keep` survive. A section left empty also loses
 * its separator bar, so no hollow band remains. Expanded cards render in full.
 */
export const elideSection =
	(section: number, keep?: (text: string, theme: Theme) => boolean): Transform =>
	(component, options, theme) => {
		const { topLeft, teeRight, bottomLeft, vertical } = theme.boxRound;
		const edge = (char: string) => new RegExp(`^${SGR}${escape(char)}`);
		const top = edge(topLeft);
		const tee = edge(teeRight);
		const bottom = edge(bottomLeft);
		const v = escape(vertical);
		const body = new RegExp(`^${SGR}${v}${SGR} ?([\\s\\S]*?) ?${SGR}${v}${SGR}\\s*$`);
		return {
			render: width => {
				const lines = component.render(width);
				if (options.expanded) return lines;
				const out: string[] = [];
				let current = -1;
				// Index in `out` of the bar that opened the target section, and whether any of its rows survived.
				let openedAt = -1;
				let kept = false;
				for (const line of lines) {
					const isTop = top.test(line);
					const isTee = tee.test(line);
					if (isTop || isTee || bottom.test(line)) {
						const closingEmpty = current === section && !kept;
						if (closingEmpty && section === 0 && isTee) {
							// Empty first section: drop the bar below it so the next section hangs off the title.
							current = 1;
							continue;
						}
						if (closingEmpty && section > 0 && openedAt >= 0) out.splice(openedAt, 1);
						current = isTop ? 0 : isTee ? current + 1 : -1;
						openedAt = current === section ? out.length : -1;
						kept = false;
						out.push(line);
						continue;
					}
					const row = current === section ? body.exec(line) : null;
					if (!row || keep?.(Bun.stripANSI(row[1]).trim(), theme)) {
						if (row) kept = true;
						out.push(line);
					}
				}
				return out;
			},
			invalidate: () => component.invalidate?.(),
		};
	};
