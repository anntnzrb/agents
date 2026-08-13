import { describe, expect, test } from "bun:test";
import {
    ATOMICITY_CRITIC_SYSTEM_PROMPT,
    buildAtomicityCriticPrompt,
    normalizeAtomicityDecision,
    shouldReviewAtomicity,
} from "./atomicity.js";

const narrowProposal = {
    summary: "Add export",
    details: ["Export account records."],
    stagedFileCount: 1,
    changedHunkCount: 1,
};

describe("autommit atomicity review", () => {
    test("skips a narrow one-file, one-hunk proposal", () => {
        expect(shouldReviewAtomicity(narrowProposal)).toBe(false);
        expect(shouldReviewAtomicity({ ...narrowProposal, stagedFileCount: 2 })).toBe(true);
    });

    test("normalizes valid decisions and rejects malformed ones", () => {
        expect(normalizeAtomicityDecision({
            decision: " accept ",
            concerns: [],
            rationale: " cohesive ",
        })).toEqual({ decision: "accept", concerns: [], rationale: "cohesive" });
        expect(() => normalizeAtomicityDecision({
            decision: "split",
            concerns: ["same", "same"],
            rationale: "reason",
        })).toThrow();
    });

    test("keeps the exact cached diff in the critic prompt", () => {
        const diff = "diff --git a/a.ts b/a.ts\n+one\n";
        const prompt = buildAtomicityCriticPrompt(narrowProposal, diff);
        expect(prompt).toContain(diff);
        expect(ATOMICITY_CRITIC_SYSTEM_PROMPT).toMatch(/untrusted evidence/i);
        expect(ATOMICITY_CRITIC_SYSTEM_PROMPT).toMatch(/independent.*revers/i);
    });
});
