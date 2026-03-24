import { Type, type Static } from "@sinclair/typebox";

export const ClarifyOptionSchema = Type.Object({
	label: Type.String({ description: "Short option label returned if selected." }),
	description: Type.Optional(Type.String({ description: "Optional extra context shown under the option." })),
});

export const ClarifyQuestionSchema = Type.Object({
	id: Type.String({ description: "Stable machine-readable question id, e.g. scope, priority, runtime." }),
	question: Type.String({ description: "Focused user-facing question. Keep it specific and answerable." }),
	options: Type.Optional(
		Type.Array(ClarifyOptionSchema, {
			description: "Optional suggested answers. Prefer 2-6 focused options when choices are known.",
		}),
	),
	allowOther: Type.Optional(
		Type.Boolean({
			description: "Whether the user may type a different answer. Defaults to true.",
		}),
	),
});

export const ClarifyParamsSchema = Type.Object({
	questions: Type.Array(ClarifyQuestionSchema, {
		minItems: 1,
		maxItems: 3,
		description:
			"One to three focused clarification questions. Use one when a single blocker exists; use two or three only when all are necessary before proceeding.",
	}),
});

export type ClarifyParams = Static<typeof ClarifyParamsSchema>;
export type ClarifyQuestionInput = Static<typeof ClarifyQuestionSchema>;

export type ClarifyOption = {
	label: string;
	description?: string;
};

export type ClarifyQuestion = {
	id: string;
	question: string;
	options: ClarifyOption[];
	allowOther: boolean;
};

export type ClarifyAnswerSource = "option" | "other" | "text";

export type ClarifyAnswer = {
	id: string;
	question: string;
	answer: string;
	source: ClarifyAnswerSource;
	selectedOption?: string;
};

export type ClarifyResult = {
	cancelled: boolean;
	reason?: string;
	answers: ClarifyAnswer[];
};
