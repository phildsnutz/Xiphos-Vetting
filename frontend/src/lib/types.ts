import type { TierKey, RiskKey } from "./tokens";

export interface Contribution {
  n: string;
  raw: number;
  c: number;
  s: number;
  d: string;
}

export interface HardStop {
  t: string;
  x: string;
  c: number;
}

export interface Flag {
  t: string;
  x: string;
  c: number;
}

export interface MIV {
  t: string;
  i: number;
  tp: number;
}

export interface ScreeningPolicyBasis {
  composite_threshold: number;
  prefilter?: {
    jaro_winkler_floor?: number;
    token_overlap_ratio?: number;
  };
  signal_weights?: Record<string, number>;
  post_match_gates?: Record<string, number>;
}

export interface ScoringPolicyMetadata {
  mode?: "layered" | "standalone";
  sensitivity?: string;
  profile?: string;
  baseline_logodds?: number;
  profile_baseline_shift?: number;
  tier_weight_multiplier?: number;
  screening?: ScreeningPolicyBasis;
  sanctions_policy?: {
    hard_stop_threshold_default?: number;
    hard_stop_threshold_allied_cross_country?: number;
    soft_flag_floor?: number;
  };
  uncertainty?: {
    effective_n_base?: number;
    source_reliability_avg?: number;
    source_reliability_multiplier?: number;
    identifier_boost?: number;
    effective_n_final?: number;
  };
}

export interface ScreeningDecisionSummary {
  matched: boolean;
  bestScore: number;
  bestRawJw: number;
  matchedName: string;
  dbLabel: string;
  screeningMs: number;
  matchDetails?: Record<string, unknown>;
  policyBasis?: ScreeningPolicyBasis;
}

export interface Calibration {
  p: number;
  tier: TierKey;
  combinedTier?: TierKey;
  lo: number;
  hi: number;
  cov: number;
  mc: number;
  ct: Contribution[];
  stops: HardStop[];
  flags: Flag[];
  finds: string[];
  miv: MIV[];
  // v5.0 DoD layer fields
  dodEligible?: boolean;
  dodQualified?: boolean;
  recommendation?: string;
  regulatoryStatus?: string;
  regulatoryFindings?: Array<Record<string, unknown>>;
  sensitivityContext?: string;
  supplyChainTier?: number;
  modelVersion?: string;
  policy?: ScoringPolicyMetadata;
  screening?: ScreeningDecisionSummary;
}

export interface ScoreSnapshot {
  p: number;
  tier: TierKey;
  sc: number;
  ts: string; // ISO timestamp
}

export interface VettingCase {
  id: string;
  name: string;
  cc: string;
  date: string;
  rl: RiskKey;
  sc: number;
  conf: number;
  cal: Calibration | null;
  history?: ScoreSnapshot[];
  profile?: string;
  program?: string;
  workflowLane?: "counterparty" | "cyber" | "export";
  created_at?: string;
}

export interface Alert {
  id: number;
  entity: string;
  sev: "critical" | "high" | "medium" | "low";
  title: string;
}
