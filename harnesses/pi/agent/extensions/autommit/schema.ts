import { type } from "arktype";

const modelHunkSchema = type({
    "+": "reject",
    type: "'all' | 'indices' | 'lines'",
    indices: "number.integer[]",
    start: "number.integer",
    end: "number.integer",
});

const modelChangeSchema = type({
    "+": "reject",
    path: "string",
    hunks: modelHunkSchema,
});

const modelCommitSchema = type({
    "+": "reject",
    summary: "string",
    details: "string[]",
    changes: modelChangeSchema.array(),
});

/** Structural boundary for the payload emitted by the autommit planning model. */
export const modelProposalSchema = type({
    "+": "reject",
    commits: modelCommitSchema.array(),
});

export type ModelProposal = typeof modelProposalSchema.infer;

/** JSON Schema consumed by Pi's constrained model tool definition. */
export const modelProposalJsonSchema = modelProposalSchema.toJsonSchema();

const normalizedHunkSchema = type.or(
    "'all'",
    type({
        "+": "reject",
        type: "'indices'",
        indices: "number.integer[]",
    }),
    type({
        "+": "reject",
        type: "'lines'",
        start: "number.integer >= 1",
        end: "number.integer >= 1",
    }),
);

const normalizedChangeSchema = type({
    "+": "reject",
    path: "string",
    hunks: normalizedHunkSchema,
});

const normalizedCommitSchema = type({
    "+": "reject",
    summary: "string",
    "details?": "string[]",
    changes: normalizedChangeSchema.array(),
});

/** Structural boundary for the normalized proposal consumed by Git logic. */
export const normalizedProposalSchema = type({
    "+": "reject",
    commits: normalizedCommitSchema.array(),
});

export type NormalizedProposal = typeof normalizedProposalSchema.infer;

/** Structural boundary for the payload emitted by the atomicity critic model. */
export const atomicityDecisionSchema = type({
    "+": "reject",
    decision: "'accept' | 'split'",
    concerns: "string[]",
    rationale: "string",
});

export type AtomicityDecisionPayload = typeof atomicityDecisionSchema.infer;

/** JSON Schema consumed by Pi's constrained model tool definition. */
export const atomicityDecisionJsonSchema = atomicityDecisionSchema.toJsonSchema();
