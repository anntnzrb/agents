export interface BlockAction {
  type: "block";
  message: string;
}

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
  action: BlockAction;
}

export interface AgentBashConfig {
  rules: Rule[];
}

export interface CommandGuardConfig {
  version: 1;
  agentBash: AgentBashConfig;
}

export interface LoadConfigSuccess {
  ok: true;
  config: CommandGuardConfig;
}

export interface LoadConfigFailure {
  ok: false;
  reason: string;
}

export type LoadConfigResult = LoadConfigSuccess | LoadConfigFailure;
