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
}

export interface Alert {
  id: number;
  entity: string;
  sev: "critical" | "high" | "medium" | "low";
  title: string;
}
