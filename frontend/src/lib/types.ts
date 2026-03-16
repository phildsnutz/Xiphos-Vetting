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
  lo: number;
  hi: number;
  cov: number;
  mc: number;
  ct: Contribution[];
  stops: HardStop[];
  flags: Flag[];
  finds: string[];
  miv: MIV[];
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
}

export interface Alert {
  id: number;
  entity: string;
  sev: "critical" | "high" | "medium" | "low";
  title: string;
}
