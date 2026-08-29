import type {
  ClarifyAnswer,
  ClarifyOption,
  ClarifyQuestion,
  ClarifyQuestionInput,
} from "./models.js";

const normalizeText = (value: string): string => value.trim();

const normalizeOption = (option: {
  label: string;
  description?: string;
  recommended?: boolean;
  default?: boolean;
}): ClarifyOption => ({
  label: normalizeText(option.label),
  ...(option.description?.trim()
    ? {
        description: option.description.trim(),
      }
    : {}),
  recommended: option.recommended === true || option.default === true,
  default: option.default === true || option.recommended === true,
});

export const normalizeQuestions = (
  questions: ClarifyQuestionInput[],
): ClarifyQuestion[] =>
  questions.map((question) => ({
    id: normalizeText(question.id),
    question: normalizeText(question.question),
    options: (question.options ?? [])
      .map(normalizeOption)
      .filter((option: ClarifyOption) => option.label.length > 0),
    allowOther: question.allowOther !== false,
    timeoutSeconds: question.timeoutSeconds,
  }));

const collectPreferredOptions = (options: ClarifyOption[]): ClarifyOption[] =>
  options.filter((option) => option.recommended || option.default);

export const getRecommendedOption = (
  question: ClarifyQuestion,
): ClarifyOption | undefined => collectPreferredOptions(question.options)[0];

export const getAutoSelectOption = (
  question: ClarifyQuestion,
): ClarifyOption | undefined =>
  getRecommendedOption(question) ?? question.options[0];

export const validateQuestions = (
  questions: ClarifyQuestion[],
): string | null => {
  if (questions.length < 1 || questions.length > 3) {
    return "clarify expects 1 to 3 questions.";
  }

  const seen = new Set<string>();
  for (const question of questions) {
    if (!question.id) return "Every clarify question needs a non-empty id.";
    if (seen.has(question.id))
      return `Duplicate clarify question id: ${question.id}`;
    seen.add(question.id);
    if (!question.question) return `Question ${question.id} is empty.`;
    if (
      question.timeoutSeconds !== undefined &&
      question.options.length === 0
    ) {
      return `Question ${question.id} cannot use timeoutSeconds without options.`;
    }

    const optionLabels = new Set<string>();
    const preferredOptions = collectPreferredOptions(question.options);
    if (preferredOptions.length > 1) {
      return `Question ${question.id} has multiple recommended/default options.`;
    }

    for (const option of question.options) {
      if (!option.label)
        return `Question ${question.id} has an empty option label.`;
      if (optionLabels.has(option.label)) {
        return `Question ${question.id} has duplicate option label: ${option.label}`;
      }
      optionLabels.add(option.label);
    }
  }
  return null;
};

const formatAnswer = (answer: ClarifyAnswer): string => {
  if (answer.source === "option") {
    const selected = answer.selectedOption ?? answer.answer;
    return answer.note
      ? `${answer.id}=${selected} (note: ${answer.note})`
      : `${answer.id}=${selected}`;
  }

  if (answer.source === "other") {
    const selected = answer.selectedOption ?? "Other";
    const freeform =
      answer.note ?? (answer.answer !== selected ? answer.answer : "");
    return freeform
      ? `${answer.id}=${selected} (answer: ${freeform})`
      : `${answer.id}=${selected}`;
  }

  return `${answer.id}=${answer.answer}`;
};

export const buildSuccessText = (answers: ClarifyAnswer[]): string =>
  answers.map(formatAnswer).join("; ");

export const sortAnswers = (
  answers: ClarifyAnswer[],
  questions: ClarifyQuestion[],
): ClarifyAnswer[] => {
  const order = new Map(
    questions.map((question, index) => [question.id, index]),
  );
  return [...answers].sort(
    (left, right) => (order.get(left.id) ?? 999) - (order.get(right.id) ?? 999),
  );
};
