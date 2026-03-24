import type { Theme } from "@mariozechner/pi-coding-agent";
import {
	Editor,
	type EditorTheme,
	Key,
	matchesKey,
	truncateToWidth,
	type Component,
	type TUI,
	visibleWidth,
	wrapTextWithAnsi,
} from "@mariozechner/pi-tui";
import type { ClarifyAnswer, ClarifyQuestion, ClarifyResult } from "./models.js";

type RenderOption = {
	label: string;
	description?: string;
	isOther?: boolean;
};

type DraftAnswer = {
	answer: string;
	source: ClarifyAnswer["source"];
	selectedOption?: string;
};

const OTHER_LABEL = "Other";

const hasOptions = (question: ClarifyQuestion): boolean => question.options.length > 0;

const getOptions = (question: ClarifyQuestion): RenderOption[] => [
	...question.options,
	...(question.allowOther ? [{ label: OTHER_LABEL, isOther: true }] : []),
];

const toFinalAnswers = (
	questions: ClarifyQuestion[],
	drafts: Map<string, DraftAnswer>,
): ClarifyAnswer[] => {
	const answers: ClarifyAnswer[] = [];
	for (const question of questions) {
		const draft = drafts.get(question.id);
		if (!draft) continue;
		answers.push({
			id: question.id,
			question: question.question,
			answer: draft.answer,
			source: draft.source,
			...(draft.selectedOption ? { selectedOption: draft.selectedOption } : {}),
		});
	}
	return answers;
};

const buildEditorTheme = (theme: Theme): EditorTheme => ({
	borderColor: (text) => theme.fg("dim", text),
	selectList: {
		selectedPrefix: (text) => theme.fg("accent", text),
		selectedText: (text) => theme.fg("accent", text),
		description: (text) => theme.fg("muted", text),
		scrollInfo: (text) => theme.fg("dim", text),
		noMatch: (text) => theme.fg("warning", text),
	},
});

class ClarifyComponent implements Component {
	private readonly editor: Editor;
	private readonly drafts = new Map<string, DraftAnswer>();
	private currentIndex = 0;
	private optionIndex = 0;
	private showingConfirmation = false;
	private cachedWidth: number | undefined;
	private cachedLines: string[] | undefined;

	constructor(
		private readonly questions: ClarifyQuestion[],
		private readonly tui: TUI,
		private readonly theme: Theme,
		private readonly done: (result: ClarifyResult) => void,
	) {
		this.editor = new Editor(tui, buildEditorTheme(theme));
		this.editor.disableSubmit = true;
		this.editor.onChange = () => this.refresh();
		this.loadDraftIntoEditor();
	}

	private refresh(): void {
		this.cachedWidth = undefined;
		this.cachedLines = undefined;
		this.tui.requestRender();
	}

	invalidate(): void {
		this.cachedWidth = undefined;
		this.cachedLines = undefined;
	}

	private getCurrentQuestion(): ClarifyQuestion | undefined {
		return this.questions[this.currentIndex];
	}

	private getCurrentOptions(): RenderOption[] {
		const question = this.getCurrentQuestion();
		return question ? getOptions(question) : [];
	}

	private getCurrentDraft(): DraftAnswer | undefined {
		const question = this.getCurrentQuestion();
		return question ? this.drafts.get(question.id) : undefined;
	}

	private loadDraftIntoEditor(): void {
		this.editor.setText(this.getCurrentDraft()?.answer ?? "");
	}

	private saveCurrentDraft(): void {
		const question = this.getCurrentQuestion();
		if (!question) return;
		const selected = this.getCurrentOptions()[this.optionIndex];
		const text = this.editor.getText().trim();
		if (!text) {
			this.drafts.delete(question.id);
			return;
		}
		if (selected?.isOther || !selected || !hasOptions(question)) {
			this.drafts.set(question.id, { answer: text, source: hasOptions(question) ? "other" : "text" });
			return;
		}
		this.drafts.set(question.id, {
			answer: text,
			source: "option",
			selectedOption: selected.label,
		});
	}

	private allAnswered(): boolean {
		this.saveCurrentDraft();
		return this.questions.every((question) => Boolean(this.drafts.get(question.id)?.answer.trim()));
	}

	private navigateTo(index: number): void {
		if (index < 0 || index >= this.questions.length) return;
		this.saveCurrentDraft();
		this.currentIndex = index;
		this.showingConfirmation = false;
		this.optionIndex = 0;
		this.syncOptionWithDraft();
		this.loadDraftIntoEditor();
		this.refresh();
	}

	private syncOptionWithDraft(): void {
		const question = this.getCurrentQuestion();
		const draft = this.getCurrentDraft();
		if (!question || !draft) {
			this.optionIndex = hasOptions(question ?? { options: [] } as ClarifyQuestion) ? 0 : 0;
			return;
		}
		const options = this.getCurrentOptions();
		if (draft.source === "option" && draft.selectedOption) {
			const index = options.findIndex((option) => option.label === draft.selectedOption);
			this.optionIndex = index >= 0 ? index : 0;
			return;
		}
		const otherIndex = options.findIndex((option) => option.isOther);
		this.optionIndex = otherIndex >= 0 ? otherIndex : 0;
	}

	private submit(): void {
		this.saveCurrentDraft();
		this.done({ cancelled: false, answers: toFinalAnswers(this.questions, this.drafts) });
	}

	private cancel(): void {
		this.saveCurrentDraft();
		this.done({
			cancelled: true,
			reason: "User cancelled clarification",
			answers: toFinalAnswers(this.questions, this.drafts),
		});
	}

	private moveToNextQuestion(): void {
		if (this.currentIndex < this.questions.length - 1) {
			this.navigateTo(this.currentIndex + 1);
			return;
		}
		this.showingConfirmation = true;
		this.refresh();
	}

	private chooseOption(index: number): void {
		const question = this.getCurrentQuestion();
		if (!question) return;
		this.optionIndex = index;
		const selected = this.getCurrentOptions()[index];
		if (!selected) return;
		if (selected.isOther) {
			const draft = this.getCurrentDraft();
			if (draft?.source === "other") {
				this.editor.setText(draft.answer);
			} else if (draft?.source !== "option") {
				this.editor.setText(draft?.answer ?? "");
			} else {
				this.editor.setText("");
			}
		} else {
			this.editor.setText(selected.label);
		}
		this.refresh();
	}

	handleInput(data: string): void {
		if (this.showingConfirmation) {
			if (matchesKey(data, Key.enter) || data.toLowerCase() === "y") {
				this.submit();
				return;
			}
			if (
				matchesKey(data, Key.escape) ||
				matchesKey(data, Key.ctrl("c")) ||
				data.toLowerCase() === "n"
			) {
				this.showingConfirmation = false;
				this.refresh();
				return;
			}
			return;
		}

		if (matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"))) {
			this.cancel();
			return;
		}

		if (matchesKey(data, Key.tab)) {
			this.navigateTo(this.currentIndex + 1);
			return;
		}
		if (matchesKey(data, Key.shift("tab"))) {
			this.navigateTo(this.currentIndex - 1);
			return;
		}

		const question = this.getCurrentQuestion();
		if (!question) return;
		const options = this.getCurrentOptions();

		if (hasOptions(question)) {
			if (matchesKey(data, Key.up)) {
				this.chooseOption(Math.max(0, this.optionIndex - 1));
				return;
			}
			if (matchesKey(data, Key.down)) {
				this.chooseOption(Math.min(options.length - 1, this.optionIndex + 1));
				return;
			}
		}

		if (matchesKey(data, Key.enter) && !matchesKey(data, Key.shift("enter"))) {
			const answer = this.editor.getText().trim();
			if (!answer) {
				this.refresh();
				return;
			}
			this.saveCurrentDraft();
			this.moveToNextQuestion();
			return;
		}

		this.editor.handleInput(data);
		this.refresh();
	}

	private dim(text: string): string {
		return this.theme.fg("dim", text);
	}

	private bold(text: string): string {
		return this.theme.bold(text);
	}

	private accent(text: string): string {
		return this.theme.fg("accent", text);
	}

	private success(text: string): string {
		return this.theme.fg("success", text);
	}

	private warning(text: string): string {
		return this.theme.fg("warning", text);
	}

	private muted(text: string): string {
		return this.theme.fg("muted", text);
	}

	private padLine(text: string, width: number): string {
		const length = visibleWidth(text);
		return text + " ".repeat(Math.max(0, width - length));
	}

	private renderBoxLine(content: string, boxWidth: number): string {
		const padded = `  ${content}`;
		const rightPad = Math.max(0, boxWidth - visibleWidth(padded) - 2);
		return `${this.dim("│")}${padded}${" ".repeat(rightPad)}${this.dim("│")}`;
	}

	private renderEmptyBoxLine(boxWidth: number): string {
		return `${this.dim("│")}${" ".repeat(Math.max(0, boxWidth - 2))}${this.dim("│")}`;
	}

	private renderProgress(): string {
		return this.questions
			.map((question, index) => {
				const answered = Boolean(this.drafts.get(question.id)?.answer.trim());
				if (index === this.currentIndex) return this.accent("●");
				return answered ? this.success("●") : this.dim("○");
			})
			.join(" ");
	}

	private renderQuestion(lines: string[], contentWidth: number, boxWidth: number): void {
		const question = this.getCurrentQuestion();
		if (!question) return;
		const title = `${this.bold("Q:")} ${question.question}`;
		for (const line of wrapTextWithAnsi(title, contentWidth)) {
			lines.push(this.renderBoxLine(line, boxWidth));
		}
	}

	private renderOptions(lines: string[], contentWidth: number, boxWidth: number): void {
		const question = this.getCurrentQuestion();
		if (!question || !hasOptions(question)) return;
		lines.push(this.renderEmptyBoxLine(boxWidth));
		for (const [index, option] of this.getCurrentOptions().entries()) {
			const prefix = index === this.optionIndex ? this.accent(">") : this.dim("·");
			const label = option.isOther ? `${option.label}…` : option.label;
			lines.push(this.renderBoxLine(`${prefix} ${index + 1}. ${label}`, boxWidth));
			if (!option.description) continue;
			for (const line of wrapTextWithAnsi(this.muted(option.description), Math.max(16, contentWidth - 5))) {
				lines.push(this.renderBoxLine(`    ${line}`, boxWidth));
			}
		}
	}

	private renderEditor(lines: string[], contentWidth: number, boxWidth: number): void {
		lines.push(this.renderEmptyBoxLine(boxWidth));
		const answerPrefix = this.bold("A: ");
		const editorWidth = Math.max(12, contentWidth - 5);
		const editorLines = this.editor.render(editorWidth);
		for (let index = 1; index < editorLines.length - 1; index += 1) {
			const line = editorLines[index];
			if (!line) continue;
			const content = index === 1 ? `${answerPrefix}${line}` : `   ${line}`;
			lines.push(this.renderBoxLine(content, boxWidth));
		}
	}

	private renderConfirmation(lines: string[], contentWidth: number, boxWidth: number): void {
		lines.push(this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`));
		const text = `${this.warning("Submit these answers?")} ${this.dim("(Enter/y confirm • Esc/n back)")}`;
		lines.push(this.renderBoxLine(truncateToWidth(text, contentWidth), boxWidth));
	}

	private renderFooter(lines: string[], contentWidth: number, boxWidth: number): void {
		lines.push(this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`));
		const controls = `${this.dim("↑↓")} option · ${this.dim("Tab")} next · ${this.dim("Shift+Tab")} prev · ${this.dim("Enter")} confirm · ${this.dim("Shift+Enter")} newline · ${this.dim("Esc")} cancel`;
		lines.push(this.renderBoxLine(truncateToWidth(controls, contentWidth), boxWidth));
	}

	render(width: number): string[] {
		if (this.cachedLines && this.cachedWidth === width) return this.cachedLines;

		const lines: string[] = [];
		const boxWidth = Math.min(Math.max(48, width - 4), 120);
		const contentWidth = Math.max(20, boxWidth - 4);
		const header = `${this.bold(this.accent("Clarify"))} ${this.dim(`(${this.currentIndex + 1}/${this.questions.length})`)}`;

		lines.push(this.padLine(this.dim(`╭${"─".repeat(Math.max(1, boxWidth - 2))}╮`), width));
		lines.push(this.padLine(this.renderBoxLine(header, boxWidth), width));
		lines.push(this.padLine(this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`), width));
		lines.push(this.padLine(this.renderBoxLine(this.renderProgress(), boxWidth), width));
		lines.push(this.padLine(this.renderEmptyBoxLine(boxWidth), width));

		this.renderQuestion(lines, contentWidth, boxWidth);
		this.renderOptions(lines, contentWidth, boxWidth);
		this.renderEditor(lines, contentWidth, boxWidth);

		if (this.showingConfirmation) {
			this.renderConfirmation(lines, contentWidth, boxWidth);
		} else {
			this.renderFooter(lines, contentWidth, boxWidth);
		}

		lines.push(this.padLine(this.dim(`╰${"─".repeat(Math.max(1, boxWidth - 2))}╯`), width));
		this.cachedWidth = width;
		this.cachedLines = lines;
		return lines;
	}
}

export const createClarifyComponent = (
	questions: ClarifyQuestion[],
	tui: TUI,
	theme: Theme,
	done: (result: ClarifyResult) => void,
): Component => new ClarifyComponent(questions, tui, theme, done);

export const renderCallText = (): string => "clarify";

export const renderResultText = (result: ClarifyResult): string => {
	if (result.cancelled) return "Cancelled";
	return result.answers.map((answer) => `${answer.id}: ${answer.answer}`).join("\n");
};
