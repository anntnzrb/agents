const PI_THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
type PiThinkingLevel = (typeof PI_THINKING_LEVELS)[number];

export function piThinkingLevelMap(
  efforts: readonly string[],
): Readonly<Record<PiThinkingLevel, string | null>> {
  const supported = new Set(efforts);
  const highest = efforts.at(-1) ?? null;
  return Object.fromEntries(
    PI_THINKING_LEVELS.map((level) => {
      if (level === "off") {
        return [level, supported.has("none") ? "none" : null];
      }
      if (level === "max") {
        return [level, highest];
      }
      return [level, supported.has(level) ? level : null];
    }),
  ) as Record<PiThinkingLevel, string | null>;
}
