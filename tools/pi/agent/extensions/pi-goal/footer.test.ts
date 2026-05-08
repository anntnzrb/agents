import { describe, expect, test } from "bun:test";
import { clearFooterContributionsForTests, getFooterContributions } from "../_shared/footer-contributions.js";
import { __test, registerGoalFooterContribution } from "./footer.js";

const theme = { fg: (_token: string, text: string) => text };

describe("pi-goal footer contribution", () => {
	test("extracts latest pi-goal state", () => {
		const activeGoal = { status: "active", timeUsedSeconds: 10 };
		const pausedGoal = { status: "paused", timeUsedSeconds: 90 };
		const entries = [
			{ type: "custom", customType: "pi-goal", data: { goal: activeGoal } },
			{ type: "custom", customType: "other", data: { goal: null } },
			{ type: "custom", customType: "pi-goal", data: { goal: pausedGoal } },
		];

		expect(__test.getLatestGoal(entries)).toEqual(pausedGoal);
	});

	test("renders goal badges", () => {
		expect(__test.buildGoalBadge(theme, { status: "active", timeUsedSeconds: 10 })).toBe("⚑10s");
		expect(__test.buildGoalBadge(theme, { status: "paused", timeUsedSeconds: 90 })).toBe("‖1m");
		expect(__test.buildGoalBadge(theme, { status: "complete", timeUsedSeconds: 90 })).toBe("✓1m");
	});

	test("registers optional footer contribution", () => {
		clearFooterContributionsForTests();
		registerGoalFooterContribution();
		const contribution = getFooterContributions().find((entry) => entry.id === "pi-goal");
		expect(contribution).toBeDefined();
		expect(
			contribution?.render(
				{ entries: [{ type: "custom", customType: "pi-goal", data: { goal: { status: "active", timeUsedSeconds: 10 } } }] },
				theme,
			),
		).toBe("⚑10s");
		clearFooterContributionsForTests();
	});
});
