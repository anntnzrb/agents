/**
 * Interactive Q&A component for answering extracted questions.
 */

import {
  type Component,
  Editor,
  type EditorTheme,
  type Focusable,
  Key,
  matchesKey,
  truncateToWidth,
  type TUI,
  visibleWidth,
  wrapTextWithAnsi,
} from "@mariozechner/pi-tui";
import { EMPTY_ANSWER_DEFAULT, SKIP_ANSWER_DEFAULT } from "./constants.ts";
import type { ExtractedQuestion } from "./types.ts";

interface RenderLayout {
  width: number;
  boxWidth: number;
  contentWidth: number;
}

const SKIP_ANSWER_RE = /^skip$/i;

export class QnAComponent implements Component, Focusable {
  private questions: ExtractedQuestion[];
  private answers: string[];
  private currentIndex = 0;
  private editor: Editor;
  private tui: TUI;
  private onDone: (result: string | null) => void;
  private showingConfirmation = false;

  private cachedWidth?: number;
  private cachedLines?: string[];

  private _focused = false;
  get focused(): boolean {
    return this._focused;
  }
  set focused(value: boolean) {
    this._focused = value;
    this.editor.focused = value;
  }

  private dim = (text: string) => `\x1b[2m${text}\x1b[0m`;
  private bold = (text: string) => `\x1b[1m${text}\x1b[0m`;
  private cyan = (text: string) => `\x1b[36m${text}\x1b[0m`;
  private green = (text: string) => `\x1b[32m${text}\x1b[0m`;
  private yellow = (text: string) => `\x1b[33m${text}\x1b[0m`;
  private gray = (text: string) => `\x1b[90m${text}\x1b[0m`;

  constructor(questions: ExtractedQuestion[], tui: TUI, onDone: (result: string | null) => void) {
    this.questions = questions;
    this.answers = questions.map(() => "");
    this.tui = tui;
    this.onDone = onDone;

    const editorTheme: EditorTheme = {
      borderColor: this.dim,
      selectList: {
        selectedBg: (text: string) => `\x1b[44m${text}\x1b[0m`,
        matchHighlight: this.cyan,
        itemSecondary: this.gray,
      },
    };

    this.editor = new Editor(tui, editorTheme);
    this.editor.disableSubmit = true;
    this.editor.onChange = () => {
      this.refresh();
    };
  }

  private saveCurrentAnswer(): void {
    this.answers[this.currentIndex] = this.editor.getText();
  }

  private navigateTo(index: number): void {
    if (index < 0 || index >= this.questions.length) return;
    this.saveCurrentAnswer();
    this.currentIndex = index;
    this.editor.setText(this.answers[index] || "");
    this.refresh();
  }

  private isSkipAnswer(answer: string): boolean {
    return SKIP_ANSWER_RE.test(answer.trim());
  }

  private resolveAnswer(rawAnswer: string | undefined): string {
    const trimmed = rawAnswer?.trim() ?? "";
    if (!trimmed) {
      return EMPTY_ANSWER_DEFAULT;
    }
    if (this.isSkipAnswer(trimmed)) {
      return SKIP_ANSWER_DEFAULT;
    }
    return trimmed;
  }

  private submit(): void {
    this.saveCurrentAnswer();

    const parts: string[] = [];
    for (let i = 0; i < this.questions.length; i++) {
      const question = this.questions[i];
      const answer = this.resolveAnswer(this.answers[i]);
      parts.push(`Q: ${question.question}`);
      if (question.context) {
        parts.push(`> ${question.context}`);
      }
      parts.push(`A: ${answer}`);
      parts.push("");
    }

    this.onDone(parts.join("\n").trim());
  }

  private cancel(): void {
    this.onDone(null);
  }

  private horizontalLine(count: number): string {
    return "─".repeat(count);
  }

  private boxLine(content: string, boxWidth: number, leftPad = 2): string {
    const paddedContent = " ".repeat(leftPad) + content;
    const contentLen = visibleWidth(paddedContent);
    const rightPad = Math.max(0, boxWidth - contentLen - 2);
    return `${this.dim("│")}${paddedContent}${" ".repeat(rightPad)}${this.dim("│")}`;
  }

  private emptyBoxLine(boxWidth: number): string {
    return `${this.dim("│")}${" ".repeat(boxWidth - 2)}${this.dim("│")}`;
  }

  private padToWidth(line: string, width: number): string {
    const len = visibleWidth(line);
    return `${line}${" ".repeat(Math.max(0, width - len))}`;
  }

  private pushLine(lines: string[], line: string, width: number): void {
    lines.push(this.padToWidth(line, width));
  }

  private pushBoxLine(lines: string[], content: string, layout: RenderLayout, leftPad = 2): void {
    this.pushLine(lines, this.boxLine(content, layout.boxWidth, leftPad), layout.width);
  }

  private pushEmptyBoxLine(lines: string[], layout: RenderLayout): void {
    this.pushLine(lines, this.emptyBoxLine(layout.boxWidth), layout.width);
  }

  private requestRender(): void {
    this.tui.requestRender();
  }

  private refresh(): void {
    this.invalidate();
    this.requestRender();
  }

  private isAbortKey(data: string): boolean {
    return matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"));
  }

  private isConfirmKey(data: string): boolean {
    return matchesKey(data, Key.enter) || data.toLowerCase() === "y";
  }

  private isDismissKey(data: string): boolean {
    return this.isAbortKey(data) || data.toLowerCase() === "n";
  }

  invalidate(): void {
    this.cachedWidth = undefined;
    this.cachedLines = undefined;
  }

  private handleConfirmationInput(data: string): boolean {
    if (!this.showingConfirmation) return false;
    if (this.isConfirmKey(data)) {
      this.submit();
      return true;
    }
    if (this.isDismissKey(data)) {
      this.showingConfirmation = false;
      this.refresh();
      return true;
    }
    return true;
  }

  private handleAbortInput(data: string): boolean {
    if (!this.isAbortKey(data)) return false;
    this.cancel();
    return true;
  }

  private handleTabNavigation(data: string): boolean {
    if (matchesKey(data, Key.tab)) {
      if (this.currentIndex < this.questions.length - 1) {
        this.navigateTo(this.currentIndex + 1);
      }
      return true;
    }

    if (matchesKey(data, Key.shift("tab"))) {
      if (this.currentIndex > 0) {
        this.navigateTo(this.currentIndex - 1);
      }
      return true;
    }

    return false;
  }

  private handleArrowNavigation(data: string): boolean {
    if (this.editor.getText() !== "") return false;
    if (matchesKey(data, Key.up)) {
      if (this.currentIndex > 0) {
        this.navigateTo(this.currentIndex - 1);
      }
      return true;
    }
    if (matchesKey(data, Key.down)) {
      if (this.currentIndex < this.questions.length - 1) {
        this.navigateTo(this.currentIndex + 1);
      }
      return true;
    }
    return false;
  }

  private handleSubmitKey(data: string): boolean {
    if (!matchesKey(data, Key.enter) || matchesKey(data, Key.shift("enter"))) {
      return false;
    }

    this.saveCurrentAnswer();
    if (this.currentIndex < this.questions.length - 1) {
      this.navigateTo(this.currentIndex + 1);
      return true;
    }

    this.showingConfirmation = true;
    this.refresh();
    return true;
  }

  private handleEditorInput(data: string): void {
    this.editor.handleInput(data);
    this.refresh();
  }

  handleInput(data: string): void {
    if (this.handleConfirmationInput(data)) return;
    if (this.handleAbortInput(data)) return;
    if (this.handleTabNavigation(data)) return;
    if (this.handleArrowNavigation(data)) return;
    if (this.handleSubmitKey(data)) return;
    this.handleEditorInput(data);
  }

  private getLayout(width: number): RenderLayout {
    const boxWidth = Math.min(width - 4, 120);
    return { width, boxWidth, contentWidth: boxWidth - 4 };
  }

  private renderHeader(lines: string[], layout: RenderLayout): void {
    const topBorder = this.dim(`╭${this.horizontalLine(layout.boxWidth - 2)}╮`);
    this.pushLine(lines, topBorder, layout.width);
    const title = `${this.bold(this.cyan("Questions"))} ${this.dim(
      `(${this.currentIndex + 1}/${this.questions.length})`
    )}`;
    this.pushBoxLine(lines, title, layout);
    const divider = this.dim(`├${this.horizontalLine(layout.boxWidth - 2)}┤`);
    this.pushLine(lines, divider, layout.width);
  }

  private renderProgress(lines: string[], layout: RenderLayout): void {
    const progressParts: string[] = [];
    for (let i = 0; i < this.questions.length; i++) {
      const answered = (this.answers[i]?.trim() || "").length > 0;
      const current = i === this.currentIndex;
      if (current) {
        progressParts.push(this.cyan("●"));
      } else if (answered) {
        progressParts.push(this.green("●"));
      } else {
        progressParts.push(this.dim("○"));
      }
    }
    this.pushBoxLine(lines, progressParts.join(" "), layout);
    this.pushEmptyBoxLine(lines, layout);
  }

  private renderQuestion(lines: string[], layout: RenderLayout): void {
    const question = this.questions[this.currentIndex];
    const questionText = `${this.bold("Q:")} ${question.question}`;
    const wrappedQuestion = wrapTextWithAnsi(questionText, layout.contentWidth);
    for (const line of wrappedQuestion) {
      this.pushBoxLine(lines, line, layout);
    }

    if (question.context) {
      this.pushEmptyBoxLine(lines, layout);
      const contextText = this.gray(`> ${question.context}`);
      const wrappedContext = wrapTextWithAnsi(contextText, layout.contentWidth - 2);
      for (const line of wrappedContext) {
        this.pushBoxLine(lines, line, layout);
      }
    }

    this.pushEmptyBoxLine(lines, layout);
  }

  private renderAnswerEditor(lines: string[], layout: RenderLayout): void {
    const answerPrefix = this.bold("A: ");
    const editorWidth = Math.max(1, layout.contentWidth - 7);
    const editorLines = this.editor.render(editorWidth);
    for (let i = 1; i < editorLines.length - 1; i++) {
      if (i === 1) {
        this.pushBoxLine(lines, `${answerPrefix}${editorLines[i]}`, layout);
      } else {
        this.pushBoxLine(lines, `   ${editorLines[i]}`, layout);
      }
    }
    this.pushEmptyBoxLine(lines, layout);
  }

  private renderFooter(lines: string[], layout: RenderLayout): void {
    const divider = this.dim(`├${this.horizontalLine(layout.boxWidth - 2)}┤`);
    this.pushLine(lines, divider, layout.width);

    if (this.showingConfirmation) {
      const confirmMsg = `${this.yellow("Submit all answers?")} ${this.dim(
        "(Enter/y to confirm, Esc/n to cancel)"
      )}`;
      this.pushBoxLine(lines, truncateToWidth(confirmMsg, layout.contentWidth), layout);
    } else {
      const controls = `${this.dim("Tab/Enter")} next · ${this.dim(
        "Shift+Tab"
      )} prev · ${this.dim("Shift+Enter")} newline · ${this.dim("Esc")} cancel`;
      this.pushBoxLine(lines, truncateToWidth(controls, layout.contentWidth), layout);
    }

    const bottomBorder = this.dim(`╰${this.horizontalLine(layout.boxWidth - 2)}╯`);
    this.pushLine(lines, bottomBorder, layout.width);
  }

  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const lines: string[] = [];
    const layout = this.getLayout(width);

    this.renderHeader(lines, layout);
    this.renderProgress(lines, layout);
    this.renderQuestion(lines, layout);
    this.renderAnswerEditor(lines, layout);
    this.renderFooter(lines, layout);

    this.cachedWidth = width;
    this.cachedLines = lines;
    return lines;
  }
}
