export const normalizeSearchRoots = (paths: string[] | undefined): string[] => {
  const rawEntries: string[] = [];

  if (paths) {
    for (const entry of paths) {
      if (typeof entry !== "string") continue;
      const trimmedEntry = entry.trim();
      if (trimmedEntry.length === 0) continue;
      rawEntries.push(trimmedEntry);
    }
  }

  if (rawEntries.length === 0) return ["."];
  return [...new Set(rawEntries)];
};
