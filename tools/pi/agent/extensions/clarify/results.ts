import type { ClarifyAnswer, ClarifyQuestion, ClarifyQuestionInput } from "./models.js";

const normalizeText = (value: string): string => value.trim();

const normalizeOption = (option: { label: string; description?: string }) => ({
	label: normalizeText(option.label),
	description: option.description?.trim() || undefined,
});

export const normalizeQuestions = (questions: ClarifyQuestionInput[]): ClarifyQuestion[] =>
	questions.map((question) => ({
		id: normalizeText(question.id),
		question: normalizeText(question.question),
		options: (question.options ?? []).map(normalizeOption).filter((option) => option.label.length > 0),
		allowOther: question.allowOther !== false,
	}));

export const validateQuestions = (questions: ClarifyQuestion[]): string | null => {
	if (questions.length < 1 || questions.length > 3) {
		return "clarify expects 1 to 3 questions.";
	}
	const seen = new Set<string>();
	for (const question of questions) {
		if (!question.id) return "Every clarify question needs a non-empty id.";
		if (seen.has(question.id)) return `Duplicate clarify question id: ${question.id}`;
		seen.add(question.id);
		if (!question.question) return `Question ${question.id} is empty.`;
		if (question.options.length === 0) continue;
		const optionLabels = new Set<string>();
		for (const option of question.options) {
			if (!option.label) return `Question ${question.id} has an empty option label.`;
			if (optionLabels.has(option.label)) return `Question ${question.id} has duplicate option label: ${option.label}`;
			optionLabels.add(option.label);
		}
	}
	return null;
};

const formatAnswer = (answer: ClarifyAnswer): string => `${answer.id}=${answer.answer}`;

export const buildSuccessText = (answers: ClarifyAnswer[]): string => answers.map(formatAnswer).join("; ");

export const sortAnswers = (answers: ClarifyAnswer[], questions: ClarifyQuestion[]): ClarifyAnswer[] => {
	const order = new Map(questions.map((question, index) => [question.id, index]));
	return [...answers].sort((left, right) => (order.get(left.id) ?? 999) - (order.get(right.id) ?? 999));
};
