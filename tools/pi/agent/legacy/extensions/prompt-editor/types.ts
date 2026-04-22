export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh";

export type ModelSelectEvent = {
  model: {
    provider: string;
    id: string;
  };
};
