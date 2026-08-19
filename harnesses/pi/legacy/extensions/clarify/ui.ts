import type { Theme } from "@earendil-works/pi-coding-agent";
import { Effect, type Fiber } from "effect";

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
} from "@earendil-works/pi-tui";
import type {
  ClarifyAnswer,
  ClarifyQuestion,
  ClarifyResult,
} from "./models.js";
import { getAutoSelectOption, getRecommendedOption } from "./results.js";

type RenderOption = {
  label: string;
  description?: string;
  isOther?: boolean;
  recommended?: boolean;
  default?: boolean;
};

type DraftAnswer = {
  answer: string;
  source: ClarifyAnswer["source"];
  mode: ClarifyAnswer["mode"];
  selectedOption?: string;
  note?: string;
  recommended?: boolean;
  default?: boolean;
  timedOut?: boolean;
  timeoutSeconds?: number;
};

const OTHER_LABEL = "Other";
const TIMER_TICK_MS = 250;
const MIN_IDLE_TIMEOUT_SECONDS = 60;
const ACTIVE_TIMEOUT_SECONDS = 180;

const hasOptions = (question: ClarifyQuestion): boolean =>
  question.options.length > 0;

const getOptions = (question: ClarifyQuestion): RenderOption[] => [
  ...question.options,
  ...(question.allowOther ? [{ label: OTHER_LABEL, isOther: true }] : []),
];

const isAnswered = (draft: DraftAnswer | undefined): boolean =>
  Boolean(draft?.answer.trim());

const getEditorText = (
  question: ClarifyQuestion | undefined,
  draft: DraftAnswer | undefined,
): string => {
  if (!question || !hasOptions(question)) {
    return draft?.answer ?? "";
  }

  if (draft?.note) {
    return draft.note;
  }

  if (draft?.source === "other" && draft.answer !== draft.selectedOption) {
    return draft.answer;
  }

  return "";
};

const getEditorLabel = (
  question: ClarifyQuestion | undefined,
  _selected: RenderOption | undefined,
): string => (question && hasOptions(question) ? "Note: " : "Answer: ");

const formatAnswerSummary = (answer: ClarifyAnswer): string => {
  const mode = answer.mode === "timeout" ? " [timeout]" : "";

  if (answer.source === "option") {
    const selected = answer.selectedOption ?? answer.answer;
    const note = answer.note ? ` · Note: ${answer.note}` : "";
    return `${answer.id}: ${selected}${note}${mode}`;
  }

  if (answer.source === "other") {
    const selected = answer.selectedOption ?? "Other";
    const freeform =
      answer.note ?? (answer.answer !== selected ? answer.answer : "");
    const text = freeform ? ` · Answer: ${freeform}` : "";
    return `${answer.id}: ${selected}${text}${mode}`;
  }

  return `${answer.id}: Answer: ${answer.answer}${mode}`;
};

const toFinalAnswers = (
  questions: ClarifyQuestion[],
  drafts: Map<string, DraftAnswer>,
): ClarifyAnswer[] =>
  questions.flatMap((question) => {
    const draft = drafts.get(question.id);
    if (!draft) return [];
    return [
      {
        id: question.id,
        question: question.question,
        answer: draft.answer,
        source: draft.source,
        mode: draft.mode,
        ...(draft.selectedOption
          ? { selectedOption: draft.selectedOption }
          : {}),
        ...(draft.note ? { note: draft.note } : {}),
        ...(draft.recommended !== undefined
          ? { recommended: draft.recommended }
          : {}),
        ...(draft.default !== undefined ? { default: draft.default } : {}),
        ...(draft.timedOut ? { timedOut: true } : {}),
        ...(draft.timeoutSeconds !== undefined
          ? { timeoutSeconds: draft.timeoutSeconds }
          : {}),
      },
    ];
  });

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
  private readonly timerFiber: Fiber.Fiber<never, never>;
  private currentIndex = 0;
  private optionIndex = 0;
  private showingConfirmation = false;
  private timeoutStartedAt = Date.now();
  private timeoutWindowSeconds = MIN_IDLE_TIMEOUT_SECONDS;
  private cachedWidth: number | undefined;
  private cachedLines: string[] | undefined;
  private suppressEditorChange = false;

  constructor(
    private readonly questions: ClarifyQuestion[],
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly done: (result: ClarifyResult) => void,
  ) {
    this.editor = new Editor(tui, buildEditorTheme(theme));
    this.editor.disableSubmit = true;
    this.editor.onChange = () => {
      if (this.suppressEditorChange) return;
      this.extendTimeoutForInteraction();
      this.saveCurrentDraft();
      this.refresh();
    };
    this.syncOptionWithDraft();
    this.loadDraftIntoEditor();
    this.restartTimeout();
    const tick = () => this.onTimerTick();
    this.timerFiber = Effect.runFork(
      Effect.gen(function*() {
        while (true) {
          yield* Effect.sleep(TIMER_TICK_MS);
          yield* Effect.sync(tick);
        }
      }),
    );
  }

  dispose(): void {
    this.timerFiber.interruptUnsafe();
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

  private getDraft(questionId: string): DraftAnswer | undefined {
    return this.drafts.get(questionId);
  }

  private getCurrentDraft(): DraftAnswer | undefined {
    const question = this.getCurrentQuestion();
    return question ? this.getDraft(question.id) : undefined;
  }

  private getProgressCounts(): { answered: number; total: number } {
    return {
      answered: this.questions.filter((question) =>
        isAnswered(this.getDraft(question.id)),
      ).length,
      total: this.questions.length,
    };
  }

  private getCurrentTimeoutBaseSeconds(): number | undefined {
    const question = this.getCurrentQuestion();
    if (!question?.timeoutSeconds) return undefined;
    return Math.max(question.timeoutSeconds, MIN_IDLE_TIMEOUT_SECONDS);
  }

  private restartTimeout(windowSeconds?: number): void {
    const baseSeconds = this.getCurrentTimeoutBaseSeconds();
    if (baseSeconds === undefined) return;
    this.timeoutWindowSeconds = Math.max(
      baseSeconds,
      windowSeconds ?? baseSeconds,
    );
    this.timeoutStartedAt = Date.now();
  }

  private extendTimeoutForInteraction(): void {
    this.restartTimeout(ACTIVE_TIMEOUT_SECONDS);
  }

  private setEditorText(text: string): void {
    this.suppressEditorChange = true;
    try {
      this.editor.setText(text);
    } finally {
      this.suppressEditorChange = false;
    }
  }

  private loadDraftIntoEditor(): void {
    this.setEditorText(
      getEditorText(this.getCurrentQuestion(), this.getCurrentDraft()),
    );
  }

  private createDraftFromSelection(
    mode: ClarifyAnswer["mode"],
  ): DraftAnswer | undefined {
    const question = this.getCurrentQuestion();
    if (!question) return undefined;

    const selected = this.getCurrentOptions()[this.optionIndex];
    const note = this.editor.getText().trim();

    if (hasOptions(question) && selected) {
      const metadata = {
        mode,
        selectedOption: selected.label,
        ...(note ? { note } : {}),
        ...(selected.recommended !== undefined
          ? { recommended: selected.recommended }
          : {}),
        ...(selected.default !== undefined
          ? { default: selected.default }
          : {}),
        ...(mode === "timeout"
          ? {
              timedOut: true,
              timeoutSeconds: question.timeoutSeconds,
            }
          : {}),
      };

      if (selected.isOther) {
        return {
          answer: note || selected.label,
          source: "other",
          ...metadata,
        };
      }

      return {
        answer: selected.label,
        source: "option",
        ...metadata,
      };
    }

    if (!note) return undefined;

    return {
      answer: note,
      source: "text",
      mode,
      ...(mode === "timeout"
        ? {
            timedOut: true,
            timeoutSeconds: question.timeoutSeconds,
          }
        : {}),
    };
  }

  private saveCurrentDraft(mode: ClarifyAnswer["mode"] = "manual"): void {
    const question = this.getCurrentQuestion();
    if (!question) return;
    const draft = this.createDraftFromSelection(mode);
    if (!draft) {
      this.drafts.delete(question.id);
      return;
    }
    this.drafts.set(question.id, draft);
  }

  private navigateTo(
    index: number,
    interaction = false,
    saveMode: ClarifyAnswer["mode"] = "manual",
  ): void {
    if (index < 0 || index >= this.questions.length) return;
    this.saveCurrentDraft(saveMode);
    this.currentIndex = index;
    this.showingConfirmation = false;
    this.syncOptionWithDraft();
    this.loadDraftIntoEditor();
    if (interaction) {
      this.extendTimeoutForInteraction();
    } else {
      this.restartTimeout();
    }
    this.refresh();
  }

  private syncOptionWithDraft(): void {
    const question = this.getCurrentQuestion();
    const draft = this.getCurrentDraft();
    const options = this.getCurrentOptions();

    if (!question || options.length === 0) {
      this.optionIndex = 0;
      return;
    }

    if (draft?.source === "option" && draft.selectedOption) {
      const selectedIndex = options.findIndex(
        (option) => option.label === draft.selectedOption,
      );
      this.optionIndex = selectedIndex >= 0 ? selectedIndex : 0;
      return;
    }

    if (draft?.source === "other") {
      const otherIndex = options.findIndex((option) => option.isOther);
      this.optionIndex = otherIndex >= 0 ? otherIndex : 0;
      return;
    }

    const recommended = getRecommendedOption(question);
    if (!recommended) {
      this.optionIndex = 0;
      return;
    }

    const recommendedIndex = options.findIndex(
      (option) => option.label === recommended.label,
    );
    this.optionIndex = recommendedIndex >= 0 ? recommendedIndex : 0;
  }

  private submit(saveMode: ClarifyAnswer["mode"] = "manual"): void {
    this.saveCurrentDraft(saveMode);
    this.dispose();
    this.done({
      cancelled: false,
      answers: toFinalAnswers(this.questions, this.drafts),
    });
  }

  private cancel(): void {
    this.saveCurrentDraft();
    this.dispose();
    this.done({
      cancelled: true,
      reason: "User cancelled clarification",
      answers: toFinalAnswers(this.questions, this.drafts),
    });
  }

  private moveToNextQuestion(): void {
    if (this.currentIndex < this.questions.length - 1) {
      this.navigateTo(this.currentIndex + 1, true);
      return;
    }
    this.saveCurrentDraft();
    this.showingConfirmation = true;
    this.extendTimeoutForInteraction();
    this.refresh();
  }

  private moveToPreviousQuestion(): void {
    if (this.showingConfirmation) {
      this.showingConfirmation = false;
      this.extendTimeoutForInteraction();
      this.refresh();
      return;
    }
    this.navigateTo(this.currentIndex - 1, true);
  }

  private chooseOption(index: number): void {
    const question = this.getCurrentQuestion();
    if (!question) return;

    this.optionIndex = index;
    const selected = this.getCurrentOptions()[index];
    if (!selected) return;

    const draft = this.getCurrentDraft();
    if (draft?.selectedOption === selected.label) {
      this.setEditorText(draft.note ?? "");
    } else {
      this.setEditorText("");
    }

    this.extendTimeoutForInteraction();
    this.saveCurrentDraft();
    this.refresh();
  }

  private autoAnswerCurrentQuestion(): void {
    const question = this.getCurrentQuestion();
    if (!question || !hasOptions(question)) return;

    if (isAnswered(this.getCurrentDraft())) {
      this.moveToNextQuestion();
      return;
    }

    const selected = getAutoSelectOption(question);
    if (!selected) return;

    const selectedIndex = this.getCurrentOptions().findIndex(
      (option) => option.label === selected.label,
    );
    this.optionIndex = selectedIndex >= 0 ? selectedIndex : 0;
    this.setEditorText("");
    this.saveCurrentDraft("timeout");

    if (this.currentIndex === this.questions.length - 1) {
      this.showingConfirmation = true;
      this.submit("timeout");
      return;
    }

    this.navigateTo(this.currentIndex + 1, false, "timeout");
  }

  private getTimeLeftSeconds(): number | undefined {
    const baseSeconds = this.getCurrentTimeoutBaseSeconds();
    if (baseSeconds === undefined || this.showingConfirmation) return undefined;
    const elapsedMs = Date.now() - this.timeoutStartedAt;
    const remainingMs = Math.max(
      0,
      this.timeoutWindowSeconds * 1000 - elapsedMs,
    );
    return Math.ceil(remainingMs / 1000);
  }

  private onTimerTick(): void {
    const timeLeft = this.getTimeLeftSeconds();
    if (timeLeft === undefined) return;
    if (timeLeft <= 0) {
      this.autoAnswerCurrentQuestion();
      return;
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
        data.toLowerCase() === "n" ||
        matchesKey(data, Key.backspace)
      ) {
        this.moveToPreviousQuestion();
        return;
      }
      return;
    }

    if (matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"))) {
      this.cancel();
      return;
    }

    if (matchesKey(data, Key.tab)) {
      this.moveToNextQuestion();
      return;
    }
    if (matchesKey(data, Key.shift("tab"))) {
      this.moveToPreviousQuestion();
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
      if (!hasOptions(question) && !this.editor.getText().trim()) {
        this.refresh();
        return;
      }
      this.saveCurrentDraft("manual");
      if (!this.getCurrentDraft()) {
        this.refresh();
        return;
      }
      this.moveToNextQuestion();
      return;
    }

    this.editor.handleInput(data);
    this.extendTimeoutForInteraction();
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

  private renderProgressBadge(index: number): string {
    const question = this.questions[index];
    if (!question) return "";
    const answered = isAnswered(this.getDraft(question.id));
    const current = index === this.currentIndex && !this.showingConfirmation;
    const marker = current
      ? this.accent("▸")
      : answered
        ? this.success("✓")
        : this.dim("·");
    return `${marker} ${index + 1}:${question.id}`;
  }

  private renderProgress(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const counts = this.getProgressCounts();
    const summary = `${this.bold("Progress:")} ${counts.answered}/${counts.total} answered`;
    lines.push(this.renderBoxLine(summary, boxWidth));

    const badges = this.questions
      .map((_, index) => this.renderProgressBadge(index))
      .join("  ");
    for (const line of wrapTextWithAnsi(badges, contentWidth)) {
      lines.push(this.renderBoxLine(line, boxWidth));
    }
  }

  private renderQuestion(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const question = this.getCurrentQuestion();
    if (!question) return;
    const title = `${this.bold("Q:")} ${question.question}`;
    for (const line of wrapTextWithAnsi(title, contentWidth)) {
      lines.push(this.renderBoxLine(line, boxWidth));
    }
  }

  private renderWaiting(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const question = this.getCurrentQuestion();
    if (!question) return;

    const timeLeft = this.getTimeLeftSeconds();
    const waitingText =
      timeLeft === undefined ? "Waiting..." : `Waiting... auto in ${timeLeft}s`;

    lines.push(this.renderEmptyBoxLine(boxWidth));
    lines.push(
      this.renderBoxLine(
        truncateToWidth(this.warning(waitingText), contentWidth),
        boxWidth,
      ),
    );
  }

  private renderOptions(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const question = this.getCurrentQuestion();
    if (!question || !hasOptions(question)) return;
    lines.push(this.renderEmptyBoxLine(boxWidth));

    for (const [index, option] of this.getCurrentOptions().entries()) {
      const prefix =
        index === this.optionIndex ? this.accent(">") : this.dim("·");
      const label = option.isOther ? `${option.label}…` : option.label;
      const markers = [
        option.recommended ? this.success("recommended") : "",
        !option.recommended && option.default ? this.success("default") : "",
      ].filter(Boolean);
      const suffix =
        markers.length > 0 ? ` ${this.dim(`[${markers.join(" · ")}]`)}` : "";
      lines.push(
        this.renderBoxLine(
          `${prefix} ${index + 1}. ${label}${suffix}`,
          boxWidth,
        ),
      );
      if (!option.description) continue;
      for (const line of wrapTextWithAnsi(
        this.muted(option.description),
        Math.max(16, contentWidth - 5),
      )) {
        lines.push(this.renderBoxLine(`    ${line}`, boxWidth));
      }
    }
  }

  private renderEditor(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    lines.push(this.renderEmptyBoxLine(boxWidth));
    const answerPrefix = this.bold(
      getEditorLabel(
        this.getCurrentQuestion(),
        this.getCurrentOptions()[this.optionIndex],
      ),
    );
    const editorWidth = Math.max(12, contentWidth - 5);
    const editorLines = this.editor.render(editorWidth);

    for (let index = 1; index < editorLines.length - 1; index += 1) {
      const line = editorLines[index];
      if (!line) continue;
      const content = index === 1 ? `${answerPrefix}${line}` : `   ${line}`;
      lines.push(this.renderBoxLine(content, boxWidth));
    }
  }

  private renderReview(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    lines.push(this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`));
    lines.push(
      this.renderBoxLine(
        this.warning("Review answers before submit"),
        boxWidth,
      ),
    );

    for (const answer of toFinalAnswers(this.questions, this.drafts)) {
      const summary = formatAnswerSummary(answer);
      for (const line of wrapTextWithAnsi(summary, contentWidth)) {
        lines.push(this.renderBoxLine(line, boxWidth));
      }
    }

    lines.push(this.renderEmptyBoxLine(boxWidth));
    lines.push(
      this.renderBoxLine(
        truncateToWidth(
          `${this.warning("Enter/y")}: submit · ${this.dim("Esc/n/Backspace")}: back`,
          contentWidth,
        ),
        boxWidth,
      ),
    );
  }

  private renderFooter(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    lines.push(this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`));
    const controls = `${this.dim("↑↓")} option · ${this.dim("Shift+Tab")} back · ${this.dim("Tab")} next · ${this.dim("Enter")} save/next · ${this.dim("Shift+Enter")} newline · ${this.dim("Esc")} cancel`;
    lines.push(
      this.renderBoxLine(truncateToWidth(controls, contentWidth), boxWidth),
    );
  }

  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) return this.cachedLines;

    const lines: string[] = [];
    const boxWidth = Math.min(Math.max(56, width - 4), 120);
    const contentWidth = Math.max(24, boxWidth - 4);
    const header = `${this.bold(this.accent("Clarify"))} ${this.dim(`step ${this.currentIndex + 1}/${this.questions.length}`)}`;

    lines.push(
      this.padLine(
        this.dim(`╭${"─".repeat(Math.max(1, boxWidth - 2))}╮`),
        width,
      ),
    );
    lines.push(this.padLine(this.renderBoxLine(header, boxWidth), width));
    lines.push(
      this.padLine(
        this.dim(`├${"─".repeat(Math.max(1, boxWidth - 2))}┤`),
        width,
      ),
    );

    this.renderProgress(lines, contentWidth, boxWidth);
    this.renderWaiting(lines, contentWidth, boxWidth);
    lines.push(this.renderEmptyBoxLine(boxWidth));
    this.renderQuestion(lines, contentWidth, boxWidth);
    this.renderOptions(lines, contentWidth, boxWidth);
    this.renderEditor(lines, contentWidth, boxWidth);

    if (this.showingConfirmation) {
      this.renderReview(lines, contentWidth, boxWidth);
    } else {
      this.renderFooter(lines, contentWidth, boxWidth);
    }

    lines.push(
      this.padLine(
        this.dim(`╰${"─".repeat(Math.max(1, boxWidth - 2))}╯`),
        width,
      ),
    );
    this.cachedWidth = width;
    this.cachedLines = lines.map((line) => this.padLine(line, width));
    return this.cachedLines;
  }
}

export const createClarifyComponent = (
  questions: ClarifyQuestion[],
  tui: TUI,
  theme: Theme,
  done: (result: ClarifyResult) => void,
): Component => new ClarifyComponent(questions, tui, theme, done);

export const renderCallText = (): string => "clarify · waiting for user";

export const renderResultText = (result: ClarifyResult): string => {
  if (result.cancelled) return "Cancelled";
  return result.answers.map(formatAnswerSummary).join("\n");
};
