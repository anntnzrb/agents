import type { Theme } from "@earendil-works/pi-coding-agent";
import { Effect, Schedule, type Fiber } from "effect";

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
      },
    ];
  });

class ClarifyComponent implements Component {
  private currentIndex = 0;
  private optionIndex = 0;
  private drafts = new Map<string, DraftAnswer>();
  private showingConfirmation = false;
  private editor: Editor;
  private timeoutDeadline = 0;
  private timerFiber: Fiber.Fiber<any, any>;
  private cachedWidth: number | undefined;
  private cachedLines: string[] | undefined;
  private suppressEditorChange = false;

  constructor(
    private readonly questions: ClarifyQuestion[],
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly done: (result: ClarifyResult) => void,
  ) {
    this.editor = new Editor(this.tui, this.theme);
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

    const loop = Effect.sync(() => this.onTimerTick()).pipe(
      Effect.repeat(Schedule.spaced(TIMER_TICK_MS)),
    );
    this.timerFiber = Effect.runFork(loop);
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

  private syncOptionWithDraft(): void {
    const question = this.getCurrentQuestion();
    if (!question || !hasOptions(question)) {
      this.optionIndex = 0;
      return;
    }

    const options = this.getCurrentOptions();
    const draft = this.drafts.get(question.id);

    if (draft?.selectedOption) {
      const matchIndex = options.findIndex(
        (opt) => opt.label === draft.selectedOption,
      );
      if (matchIndex >= 0) {
        this.optionIndex = matchIndex;
        return;
      }
    }

    const rec = getRecommendedOption(question);
    if (rec) {
      const recIndex = options.findIndex((opt) => opt.label === rec.label);
      if (recIndex >= 0) {
        this.optionIndex = recIndex;
        return;
      }
    }

    this.optionIndex = 0;
  }

  private loadDraftIntoEditor(): void {
    const question = this.getCurrentQuestion();
    const draft = question ? this.drafts.get(question.id) : undefined;
    const text = getEditorText(question, draft);
    this.suppressEditorChange = true;
    this.editor.setText(text);
    this.suppressEditorChange = false;
  }

  private restartTimeout(): void {
    const question = this.getCurrentQuestion();
    const seconds =
      question?.timeoutSeconds &&
      question.timeoutSeconds >= MIN_IDLE_TIMEOUT_SECONDS
        ? question.timeoutSeconds
        : ACTIVE_TIMEOUT_SECONDS;
    this.timeoutDeadline = Date.now() + seconds * 1000;
  }

  private extendTimeoutForInteraction(): void {
    this.timeoutDeadline = Math.max(
      this.timeoutDeadline,
      Date.now() + ACTIVE_TIMEOUT_SECONDS * 1000,
    );
  }

  private onTimerTick(): void {
    const remaining = Math.max(0, this.timeoutDeadline - Date.now());
    if (remaining <= 0) {
      this.applyTimeoutFallback();
      this.submit();
      return;
    }
    this.refresh();
  }

  private applyTimeoutFallback(): void {
    for (const question of this.questions) {
      const existing = this.drafts.get(question.id);
      if (existing && isAnswered(existing)) continue;

      const auto = getAutoSelectOption(question);
      if (auto) {
        this.drafts.set(question.id, {
          answer: auto.label,
          source: "option",
          mode: "timeout",
          selectedOption: auto.label,
          recommended: auto.recommended,
          default: auto.default,
          timedOut: true,
        });
      } else {
        this.drafts.set(question.id, {
          answer: "(no response)",
          source: "freeform",
          mode: "timeout",
          timedOut: true,
        });
      }
    }
  }

  private saveCurrentDraft(): void {
    const question = this.getCurrentQuestion();
    if (!question) return;

    const options = this.getCurrentOptions();
    const selected = options[this.optionIndex];
    const editorText = this.editor.getText().trim();

    if (!hasOptions(question)) {
      this.drafts.set(question.id, {
        answer: editorText,
        source: "freeform",
        mode: "interactive",
      });
      return;
    }

    if (selected?.isOther) {
      this.drafts.set(question.id, {
        answer: editorText || OTHER_LABEL,
        source: "other",
        mode: "interactive",
        selectedOption: OTHER_LABEL,
        note: editorText || undefined,
      });
      return;
    }

    if (selected) {
      this.drafts.set(question.id, {
        answer: selected.label,
        source: "option",
        mode: "interactive",
        selectedOption: selected.label,
        note: editorText || undefined,
        recommended: selected.recommended,
        default: selected.default,
      });
    }
  }

  private submit(): void {
    this.dispose();
    const answers = toFinalAnswers(this.questions, this.drafts);
    this.done({ cancelled: false, answers });
  }

  private cancel(): void {
    this.dispose();
    this.done({ cancelled: true, answers: [] });
  }

  handleInput(data: string): void {
    if (matchesKey(data, Key.ctrl("c")) || matchesKey(data, "escape")) {
      if (this.showingConfirmation) {
        this.showingConfirmation = false;
        this.refresh();
        return;
      }
      this.cancel();
      return;
    }

    if (this.showingConfirmation) {
      if (matchesKey(data, "return") || data.toLowerCase() === "y") {
        this.submit();
        return;
      }
      if (matchesKey(data, "backspace") || data.toLowerCase() === "n") {
        this.showingConfirmation = false;
        this.refresh();
        return;
      }
      return;
    }

    this.extendTimeoutForInteraction();

    if (matchesKey(data, Key.up)) {
      const options = this.getCurrentOptions();
      if (options.length > 0) {
        this.optionIndex =
          (this.optionIndex - 1 + options.length) % options.length;
        this.saveCurrentDraft();
        this.refresh();
      }
      return;
    }

    if (matchesKey(data, Key.down)) {
      const options = this.getCurrentOptions();
      if (options.length > 0) {
        this.optionIndex = (this.optionIndex + 1) % options.length;
        this.saveCurrentDraft();
        this.refresh();
      }
      return;
    }

    if (matchesKey(data, Key.shift("tab"))) {
      if (this.currentIndex > 0) {
        this.saveCurrentDraft();
        this.currentIndex -= 1;
        this.syncOptionWithDraft();
        this.loadDraftIntoEditor();
        this.restartTimeout();
        this.refresh();
      }
      return;
    }

    if (matchesKey(data, "tab") || matchesKey(data, "return")) {
      this.saveCurrentDraft();
      if (this.currentIndex < this.questions.length - 1) {
        this.currentIndex += 1;
        this.syncOptionWithDraft();
        this.loadDraftIntoEditor();
        this.restartTimeout();
        this.refresh();
        return;
      }

      this.showingConfirmation = true;
      this.refresh();
      return;
    }

    this.editor.handleInput(data);
    this.refresh();
  }

  private bold(text: string): string {
    return this.theme.bold ? this.theme.bold(text) : text;
  }

  private dim(text: string): string {
    return this.theme.fg("dim", text);
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

  private padLine(line: string, width: number): string {
    const pad = Math.max(0, width - visibleWidth(line));
    return line + " ".repeat(pad);
  }

  private renderBoxLine(content: string, boxWidth: number): string {
    const inner = truncateToWidth(content, Math.max(1, boxWidth - 4));
    const pad = Math.max(0, boxWidth - 4 - visibleWidth(inner));
    return `${this.dim("│")} ${inner}${" ".repeat(pad)} ${this.dim("│")}`;
  }

  private renderEmptyBoxLine(boxWidth: number): string {
    return `${this.dim("│")}${" ".repeat(Math.max(1, boxWidth - 2))}${this.dim("│")}`;
  }

  private renderProgress(
    lines: string[],
    _contentWidth: number,
    boxWidth: number,
  ): void {
    const parts = this.questions.map((q, i) => {
      const draft = this.drafts.get(q.id);
      const answered = isAnswered(draft);
      const isCurrent = i === this.currentIndex;

      if (isCurrent) {
        return this.bold(this.accent(`[${i + 1}]`));
      }
      if (answered) {
        return this.success(`✓${i + 1}`);
      }
      return this.dim(`·${i + 1}`);
    });

    lines.push(this.renderBoxLine(parts.join("  "), boxWidth));
  }

  private renderWaiting(
    lines: string[],
    _contentWidth: number,
    boxWidth: number,
  ): void {
    const seconds = Math.max(
      0,
      Math.ceil((this.timeoutDeadline - Date.now()) / 1000),
    );
    const text = `Waiting for user (${seconds}s remaining)`;
    lines.push(this.renderBoxLine(this.dim(text), boxWidth));
  }

  private renderQuestion(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const q = this.getCurrentQuestion();
    if (!q) return;

    for (const line of wrapTextWithAnsi(
      this.bold(q.question),
      contentWidth,
    )) {
      lines.push(this.renderBoxLine(line, boxWidth));
    }
  }

  private renderOptions(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    const options = this.getCurrentOptions();
    if (options.length === 0) return;

    lines.push(this.renderEmptyBoxLine(boxWidth));

    options.forEach((opt, idx) => {
      const isSelected = idx === this.optionIndex;
      const marker = isSelected ? this.accent("●") : this.dim("○");
      let label = opt.label;
      if (opt.recommended) label += ` ${this.dim("(recommended)")}`;
      if (opt.default && !opt.recommended) label += ` ${this.dim("(default)")}`;

      const fullLine = `${marker} ${isSelected ? this.bold(label) : label}`;
      lines.push(
        this.renderBoxLine(truncateToWidth(fullLine, contentWidth), boxWidth),
      );

      if (opt.description) {
        const descLine = `  ${this.dim(opt.description)}`;
        for (const wrapped of wrapTextWithAnsi(descLine, contentWidth)) {
          lines.push(this.renderBoxLine(wrapped, boxWidth));
        }
      }
    });
  }

  private renderEditor(
    lines: string[],
    contentWidth: number,
    boxWidth: number,
  ): void {
    lines.push(this.renderEmptyBoxLine(boxWidth));
    const answerPrefix = this.dim(
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
