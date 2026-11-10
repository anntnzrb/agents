import type { Theme } from "@oh-my-pi/pi-tui/theme";

/**
 * Maps a collapsed card's stock rows to the rows smolui draws. Returning
 * `undefined` keeps the stock rows: a view that does not recognise a card's
 * shape leaves it alone instead of guessing what is safe to hide.
 */
export type View = (lines: readonly string[], theme: Theme, isError: boolean) => readonly string[] | undefined;

type Kind = "top" | "tee" | "bottom" | "body" | "other";

const SGR = "(?:\\x1b\\[[0-9;:]*m)*";
// Trailing styling and padding after a box's right edge.
const TAIL = "(?:\\x1b\\[[0-9;:]*m|\\s)*$";
const RESET = "\x1b[0m";
const escape = (text: string) => text.replace(/[\\^$.*+?()[\]{}|-]/g, "\\$&");
// omp draws card rows with SGR styling only, so dropping SGR sequences leaves the visible text.
const visible = (text: string) => text.replace(/\x1b\[[0-9;:]*m/g, "").trim();

/**
 * Matches rows that carry omp's styled error or warning status glyph, the
 * mark omp itself puts on a problem: LSP diagnostics, failed requests,
 * timeouts. Color alone is not enough: diff removals and `-N` stats reuse the
 * error red. Each glyph comes from the theme (`styledSymbol`), so it follows
 * the symbol preset and any theme override. A theme that styles neither
 * returns `undefined`, and the caller then keeps the stock rows.
 */
const problemMatcher = (theme: Theme): ((raw: string) => boolean) | undefined => {
	const marks = [theme.styledSymbol("status.error", "error"), theme.styledSymbol("status.warning", "warning")];
	if (marks.some(mark => visible(mark).length === 0)) return undefined;
	return raw => marks.some(mark => raw.includes(mark));
};

/**
 * Reads framed tool cards drawn by `renderOutputBlock`. The ASCII symbol
 * preset draws every corner and tee as `+`, so a border row whose glyph fits
 * several kinds is resolved by position: outside a box it opens one; inside,
 * it is a tee when it carries a label or content rows follow, else the bottom.
 */
const frame = (theme: Theme) => {
	const { topLeft, topRight, teeRight, teeLeft, bottomLeft, horizontal, vertical } = theme.boxRound;
	const edge = (char: string) => new RegExp(`^${SGR}${escape(char)}`);
	const top = edge(topLeft);
	const tee = edge(teeRight);
	const bottom = edge(bottomLeft);
	const side = edge(vertical);
	const h = escape(horizontal);
	const v = escape(vertical);
	const opener = `(?:${escape(topLeft)}|${escape(teeRight)})`;
	const closer = `(?:${escape(topRight)}|${escape(teeLeft)})`;
	const lead = new RegExp(`^${SGR}${opener}(?:${SGR}${h})*${SGR} ?`);
	const trail = new RegExp(` ?${SGR}(?:${h}${SGR})*${closer}${TAIL}`);
	// After the left border only its own resets are skipped, so a row's first color stays on the content.
	const body = new RegExp(`^${SGR}${v}(?:\\x1b\\[(?:0|39|49)?m)* ?([\\s\\S]*?) ?${SGR}${v}${SGR}\\s*$`);
	const label = (line: string) => line.replace(lead, "").replace(trail, "");
	return {
		/** A bar's label with its styling; empty text when the bar has none. */
		label,
		/** A body row's content with its styling and padding, inside the side borders. */
		inner: (line: string) => body.exec(line)?.[1]?.trimEnd(),
		classify(lines: readonly string[]): Kind[] {
			let open = false;
			return lines.map((line, i) => {
				const isTop = top.test(line);
				const isTee = tee.test(line);
				const isBottom = bottom.test(line);
				let kind: Kind;
				if (!open) kind = isTop ? "top" : "other";
				else if (isTee && isBottom) {
					const next = lines[i + 1];
					kind = visible(label(line)) || (next !== undefined && side.test(next)) ? "tee" : "bottom";
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
 * Collapse a card to its title row(s), keeping problem blocks. Framed cards
 * contribute each top border's label (stacked multi-file edits keep one row
 * per file); frameless cards keep their first line. A body row with a
 * problem glyph stays, with every row after it, indented under the title:
 * the LSP diagnostics tree after an edit or write. Error results render stock.
 */
export const titleOnly: View = (lines, theme, isError) => {
	if (isError || lines.length === 0) return undefined;
	const problem = problemMatcher(theme);
	if (!problem) return undefined;
	const { label, inner, classify } = frame(theme);
	const kinds = classify(lines);
	if (!kinds.includes("top")) {
		const from = lines.findIndex((line, i) => i > 0 && problem(line));
		return from < 0 ? lines.slice(0, 1) : [lines[0]!, ...lines.slice(from)];
	}
	const out: string[] = [];
	// Once a problem block starts in a box, the rest of that box stays.
	let keeping = false;
	for (const [i, line] of lines.entries()) {
		const kind = kinds[i];
		if (kind === "top") {
			const text = label(line);
			// An unlabeled box has no title to collapse to.
			if (!visible(text)) return undefined;
			out.push(` ${text}${RESET}`);
			keeping = false;
		} else if (kind === "body") {
			const raw = inner(line);
			if (raw === undefined) continue;
			keeping ||= problem(raw);
			if (keeping) out.push(`   ${raw}${RESET}`);
		} else if (kind === "other" && problem(line)) {
			out.push(line);
		}
	}
	return out;
};

/** A section of a framed box: index 0 sits under the top border, each tee bar starts the next. */
export interface Section {
	readonly index: number;
	/** The bar's visible label; empty for section 0 and unlabeled dividers. */
	readonly label: string;
}

export interface HideOptions {
	/** Keep any row of the section whose styled content this accepts. */
	readonly keep?: (raw: string, theme: Theme) => boolean;
	/** Keep the section's trailing run of rows whose styled content this accepts. */
	readonly keepTail?: (raw: string, theme: Theme) => boolean;
}

/**
 * Drop the body rows of every section `pick` selects, errors included.
 * Rows with a problem glyph, and rows `keep` accepts, always stay. A section
 * left empty loses its separator bar so no hollow band remains; a box left
 * with no rows at all collapses to its title row.
 */
export const hideSection =
	(pick: (section: Section) => boolean, options: HideOptions = {}): View =>
	(lines, theme) => {
		const problem = problemMatcher(theme);
		if (!problem) return undefined;
		const { label, inner, classify } = frame(theme);
		const kinds = classify(lines);
		const out: string[] = [];
		let section: Section | undefined;
		// Index in `out` of the bar that opened the current section.
		let openedAt = -1;
		// Body rows of a picked section, held until it closes.
		let held: { line: string; raw: string }[] | undefined;

		const close = (next: Kind) => {
			if (!held || !section) return "keep" as const;
			const rows = held;
			held = undefined;
			let tail = rows.length;
			const { keep, keepTail } = options;
			if (keepTail) while (tail > 0 && keepTail(rows[tail - 1]!.raw, theme)) tail--;
			const kept = rows.filter(({ raw }, i) => i >= tail || problem(raw) || keep?.(raw, theme));
			out.push(...kept.map(row => row.line));
			if (kept.length > 0) return "keep" as const;
			if (section.index > 0) {
				out.splice(openedAt, 1);
				return "keep" as const;
			}
			// Empty first section: the next section hangs off the title bar.
			if (next === "tee") return "skip" as const;
			// Nothing else in the box: a hollow frame would hide the status, so keep only the title.
			const title = label(out[openedAt]!);
			if (next !== "bottom" || !visible(title)) return "keep" as const;
			out[openedAt] = ` ${title}${RESET}`;
			return "skip" as const;
		};

		for (const [i, line] of lines.entries()) {
			const kind = kinds[i]!;
			if (kind === "top" || kind === "tee" || kind === "bottom") {
				const closing = section;
				const action = close(kind);
				if (kind === "bottom") {
					section = undefined;
					if (action === "keep") out.push(line);
					continue;
				}
				section = { index: kind === "top" || !closing ? 0 : closing.index + 1, label: visible(label(line)) };
				if (action === "skip") {
					// The dropped bar's section still counts, so later indexes stay stable.
					openedAt = out.length - 1;
				} else {
					openedAt = out.length;
					out.push(line);
				}
				if (pick(section)) held = [];
				continue;
			}
			const raw = kind === "body" && held ? inner(line) : undefined;
			if (raw !== undefined) held!.push({ line, raw });
			else out.push(line);
		}
		close("other");
		return out;
	};
