export type GoalStatus = "active" | "paused" | "complete";

export type GoalEventKind =
  | "active"
  | "continuation"
  | "paused"
  | "resumed"
  | "cleared"
  | "complete";

export type GoalState = {
  version: 1;
  id: string;
  objective: string;
  status: GoalStatus;
  timeUsedSeconds: number;
  createdAt: number;
  updatedAt: number;
};

export const MAX_GOAL_OBJECTIVE_CHARS = 4_000;

export const formatElapsed = (seconds: number): string => {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  if (safeSeconds < 60) return `${safeSeconds}s`;
  const minutes = Math.floor(safeSeconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const remMinutes = minutes % 60;
    return remMinutes === 0 ? `${hours}h` : `${hours}h ${remMinutes}m`;
  }
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  const remMinutes = minutes % 60;
  return `${days}d ${remHours}h ${remMinutes}m`;
};

export const goalStatusLabel = (status: GoalStatus): string => {
  switch (status) {
    case "active":
      return "active";
    case "paused":
      return "paused";
    case "complete":
      return "complete";
  }
};

export const goalEventStatus = (kind: GoalEventKind): string => {
  switch (kind) {
    case "active":
      return "active";
    case "continuation":
      return "continuing";
    case "paused":
      return "paused";
    case "resumed":
      return "resumed";
    case "cleared":
      return "cleared";
    case "complete":
      return "achieved";
  }
};

export const goalUsage = (state: GoalState): string =>
  formatElapsed(state.timeUsedSeconds);

export const goalUsageSummary = (state: GoalState): string => {
  const parts = [`Objective: ${state.objective}`];
  if (state.timeUsedSeconds > 0)
    parts.push(`Time: ${formatElapsed(state.timeUsedSeconds)}.`);
  return parts.join(" ");
};

export const statusLine = (state: GoalState | null): string | undefined => {
  if (!state) return undefined;
  const elapsed = ` (${formatElapsed(state.timeUsedSeconds)})`;
  if (state.status === "active") return `Pursuing goal${elapsed}`;
  if (state.status === "paused") return "Goal paused (/goal resume)";
  return `Goal achieved${elapsed}`;
};

export const truncateObjective = (objective: string, max = 96): string => {
  const singleLine = objective.replace(/\s+/g, " ").trim();
  return singleLine.length > max
    ? `${singleLine.slice(0, max - 1)}…`
    : singleLine;
};
