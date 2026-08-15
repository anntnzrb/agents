import { describe, expect, test } from "bun:test";
import {
    atomicityDecisionJsonSchema,
    atomicityDecisionSchema,
    modelProposalJsonSchema,
    modelProposalSchema,
    type AtomicityDecisionPayload,
    type ModelProposal,
} from "./schema.js";

const validProposal: ModelProposal = {
    commits: [{
        summary: "Add autommit schemas",
        details: ["Validate model payloads at the boundary."],
        changes: [{
            path: "src/autommit.ts",
            hunks: { type: "all", indices: [], start: 0, end: 0 },
        }],
    }],
};

const validDecision: AtomicityDecisionPayload = {
    decision: "split",
    concerns: ["The implementation and its tests can be reverted independently."],
    rationale: "The staged snapshot contains two independently reversible behaviors.",
};

describe("autommit boundary schemas", () => {
    test("accept valid model proposal and atomicity decision payloads", () => {
        expect(modelProposalSchema(validProposal)).toEqual(validProposal);
        expect(atomicityDecisionSchema(validDecision)).toEqual(validDecision);
    });

    test("reject extra keys at every object boundary", () => {
        const commit = validProposal.commits[0];
        if (!commit) throw new Error("valid proposal fixture is empty");
        const change = commit.changes[0];
        if (!change) throw new Error("valid commit fixture is empty");

        expect(modelProposalSchema.allows({ ...validProposal, extra: true })).toBe(false);
        expect(modelProposalSchema.allows({
            ...validProposal,
            commits: [{ ...commit, extra: true }],
        })).toBe(false);
        expect(modelProposalSchema.allows({
            ...validProposal,
            commits: [{
                ...commit,
                changes: [{ ...change, extra: true }],
            }],
        })).toBe(false);
        expect(modelProposalSchema.allows({
            ...validProposal,
            commits: [{
                ...commit,
                changes: [{
                    ...change,
                    hunks: { ...change.hunks, extra: true },
                }],
            }],
        })).toBe(false);
        expect(atomicityDecisionSchema.allows({ ...validDecision, extra: true })).toBe(false);
    });

    test("reject malformed payloads without applying domain validation", () => {
        const malformedProposals: unknown[] = [
            null,
            {},
            { commits: "not an array" },
            { commits: [{ summary: "missing details", changes: [] }] },
            {
                commits: [{
                    summary: "bad selector",
                    details: [],
                    changes: [{
                        path: "src/autommit.ts",
                        hunks: { type: "unknown", indices: [], start: 0, end: 0 },
                    }],
                }],
            },
            {
                commits: [{
                    summary: "bad index type",
                    details: [],
                    changes: [{
                        path: "src/autommit.ts",
                        hunks: { type: "indices", indices: ["one"], start: 0, end: 0 },
                    }],
                }],
            },
        ];
        for (const payload of malformedProposals) {
            expect(modelProposalSchema.allows(payload)).toBe(false);
        }

        const malformedDecisions: unknown[] = [
            null,
            {},
            { decision: "review", concerns: [], rationale: "reason" },
            { decision: "accept", concerns: "none", rationale: "reason" },
            { decision: "accept", concerns: [], rationale: 42 },
        ];
        for (const payload of malformedDecisions) {
            expect(atomicityDecisionSchema.allows(payload)).toBe(false);
        }
    });

    test("expose closed JSON Schema shapes for Pi tool definitions", () => {
        expect(modelProposalJsonSchema).toEqual({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            type: "object",
            properties: {
                commits: {
                    type: "array",
                    items: {
                        type: "object",
                        properties: {
                            changes: {
                                type: "array",
                                items: {
                                    type: "object",
                                    properties: {
                                        hunks: {
                                            type: "object",
                                            properties: {
                                                end: { type: "integer" },
                                                indices: {
                                                    type: "array",
                                                    items: { type: "integer" },
                                                },
                                                start: { type: "integer" },
                                                type: { enum: ["all", "indices", "lines"] },
                                            },
                                            required: ["end", "indices", "start", "type"],
                                            additionalProperties: false,
                                        },
                                        path: { type: "string" },
                                    },
                                    required: ["hunks", "path"],
                                    additionalProperties: false,
                                },
                            },
                            details: { type: "array", items: { type: "string" } },
                            summary: { type: "string" },
                        },
                        required: ["changes", "details", "summary"],
                        additionalProperties: false,
                    },
                },
            },
            required: ["commits"],
            additionalProperties: false,
        });
        expect(atomicityDecisionJsonSchema).toEqual({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            type: "object",
            properties: {
                concerns: { type: "array", items: { type: "string" } },
                decision: { enum: ["accept", "split"] },
                rationale: { type: "string" },
            },
            required: ["concerns", "decision", "rationale"],
            additionalProperties: false,
        });
    });
});

