/**
 * Domain model interfaces for Claude Code statusline
 */

/** Claude model information */
export interface ModelInfo {
  readonly id: string;
  readonly display_name: string;
}

/** Workspace directory paths */
export interface WorkspaceInfo {
  readonly current_dir: string;
  readonly project_dir: string;
}

/** Output style configuration */
export interface OutputStyle {
  readonly name: string;
}

/** Session cost and performance metrics */
export interface CostInfo {
  readonly total_cost_usd: number;
  readonly total_duration_ms: number;
  readonly total_api_duration_ms: number;
}

/** Token context metrics */
export interface TokenMetrics {
  readonly contextLength: number;
}

/** Complete Claude Code session data */
export interface StatusLineData {
  readonly session_id: string;
  readonly transcript_path: string;
  readonly cwd: string;
  readonly model: ModelInfo;
  readonly workspace: WorkspaceInfo;
  readonly version: string;
  readonly output_style: OutputStyle;
  readonly cost: CostInfo;
  readonly exceeds_200k_tokens: boolean;
}

/** Extended data with computed fields */
export interface EnrichedStatusLineData extends StatusLineData {
  readonly msgCount: number;
  readonly tokenMetrics: TokenMetrics;
}
