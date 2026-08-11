export interface BlockAction {
  type: "block";
  message: string;
  requiresSkill?: string;
  requiredWorkflow?: string;
  requiresBinding?: string;
}

export interface WarnAction {
  type: "warn";
  message: string;
}

export type BashAction = BlockAction | WarnAction;

export interface ExecutableMatch {
  type: "executable";
  names?: string[];
  patterns?: string[];
  flags?: string;
  caseSensitive?: boolean;
}

export interface RegexMatch {
  type: "regex";
  pattern: string;
  flags?: string;
}

export type MatchConfig = ExecutableMatch | RegexMatch;

export interface Rule {
  id?: string;
  match: MatchConfig;
  action: BashAction;
}

export interface AgentBashConfig {
  rules: Rule[];
}

export interface ProtectedPathRule {
  id?: string;
  pattern: string;
  tools: Array<"read" | "write" | "edit">;
  action: BlockAction;
}

export interface ProtectedPathsConfig {
  rules: ProtectedPathRule[];
}

export interface SkillBinding {
  requiresSkill: string;
  requiredWorkflow?: string;
}

export interface GuardrailsConfig {
  version: 1;
  skillBindings: Record<string, SkillBinding>;
  agentBash: AgentBashConfig;
  protectedPaths: ProtectedPathsConfig;
}

export interface LoadConfigSuccess {
  ok: true;
  config: GuardrailsConfig;
}

export interface LoadConfigFailure {
  ok: false;
  reason: string;
}

export type LoadConfigResult = LoadConfigSuccess | LoadConfigFailure;
