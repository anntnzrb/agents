const PI_THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
type PiThinkingLevel = (typeof PI_THINKING_LEVELS)[number];

export function piThinkingLevelMap(
  efforts: readonly string[],
): Readonly<Record<PiThinkingLevel, string | null>> {
  const supported = new Set(efforts);
  const highest = efforts.at(-1) ?? null;
  const map: Record<PiThinkingLevel, string | null> = {
    off: supported.has("none") ? "none" : null,
    minimal: supported.has("minimal") ? "minimal" : null,
    low: supported.has("low") ? "low" : null,
    medium: supported.has("medium") ? "medium" : null,
    high: supported.has("high") ? "high" : null,
    xhigh: supported.has("xhigh") ? "xhigh" : null,
    max: highest,
  };
  return map;
}
