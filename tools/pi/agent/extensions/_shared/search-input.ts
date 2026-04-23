export const normalizeSearchRoots = (singlePath: string | undefined, multiPath: string[] | undefined): string[] => {
	if (singlePath && multiPath && multiPath.length > 0) {
		throw new Error("Use either path or paths, not both");
	}

	const rawEntries: string[] = [];
	const trimmedSinglePath = singlePath?.trim();
	if (trimmedSinglePath) rawEntries.push(trimmedSinglePath);

	if (multiPath) {
		for (const entry of multiPath) {
			if (typeof entry !== "string") continue;
			const trimmedEntry = entry.trim();
			if (trimmedEntry.length === 0) continue;
			rawEntries.push(trimmedEntry);
		}
	}

	if (rawEntries.length === 0) return ["."];
	return [...new Set(rawEntries)];
};
