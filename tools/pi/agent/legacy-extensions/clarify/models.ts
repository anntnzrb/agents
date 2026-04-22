import { Type, type Static } from "@sinclair/typebox";

export const ClarifyOptionSchema = Type.Object({
  label: Type.String({
    description: "Label.",
  }),
  description: Type.Optional(
    Type.String({
      description: "Details.",
    })
  ),
  recommended: Type.Optional(
    Type.Boolean({
      description: "Recommended.",
    })
  ),
  default: Type.Optional(
    Type.Boolean({
      description: "Alias.",
    })
  ),
});

export const ClarifyQuestionSchema = Type.Object({
  id: Type.String({
    description: "ID.",
  }),
  question: Type.String({
    description: "Question text.",
  }),
  options: Type.Optional(
    Type.Array(ClarifyOptionSchema, {
      description: "Options.",
    })
  ),
  allowOther: Type.Optional(
    Type.Boolean({
      description: "Allow custom answer.",
    })
  ),
  timeoutSeconds: Type.Optional(
    Type.Integer({
      minimum: 1,
      description: "Auto-select timeout.",
    })
  ),
});

export const ClarifyParamsSchema = Type.Object({
  questions: Type.Array(ClarifyQuestionSchema, {
    minItems: 1,
    maxItems: 3,
    description: "1-3 questions.",
  }),
});

export type ClarifyParams = Static<typeof ClarifyParamsSchema>;
export type ClarifyQuestionInput = Static<typeof ClarifyQuestionSchema>;

export type ClarifyOption = {
  label: string;
  description?: string;
  recommended: boolean;
  default: boolean;
};

export type ClarifyQuestion = {
  id: string;
  question: string;
  options: ClarifyOption[];
  allowOther: boolean;
  timeoutSeconds?: number;
};

export type ClarifyAnswerSource = "option" | "other" | "text";
export type ClarifyAnswerMode = "manual" | "timeout";

export type ClarifyAnswer = {
  id: string;
  question: string;
  answer: string;
  source: ClarifyAnswerSource;
  mode: ClarifyAnswerMode;
  selectedOption?: string;
  note?: string;
  recommended?: boolean;
  default?: boolean;
  timedOut?: boolean;
  timeoutSeconds?: number;
};

export type ClarifyResult = {
  cancelled: boolean;
  reason?: string;
  answers: ClarifyAnswer[];
};
