import type { Theme } from "@mariozechner/pi-coding-agent";

export type FooterContributionContext = {
	entries: readonly unknown[];
};

export type FooterContribution = {
	id: string;
	render: (context: FooterContributionContext, theme: Theme) => string | undefined;
};

const contributions = new Map<string, FooterContribution>();

export const registerFooterContribution = (contribution: FooterContribution): void => {
	contributions.set(contribution.id, contribution);
};

export const unregisterFooterContribution = (id: string): void => {
	contributions.delete(id);
};

export const getFooterContributions = (): FooterContribution[] => [...contributions.values()];

export const clearFooterContributionsForTests = (): void => {
	contributions.clear();
};
