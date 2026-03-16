/** Xiphos design tokens - matches the defense-tooling aesthetic */

export const T = {
  bg: "#0a0e17",
  surface: "#111827",
  hover: "#1a2234",
  raised: "#162032",
  border: "#1e293b",
  text: "#e2e8f0",
  dim: "#94a3b8",
  muted: "#64748b",
  accent: "#3b82f6",
  green: "#10b981",
  greenBg: "rgba(16,185,129,0.12)",
  amber: "#f59e0b",
  amberBg: "rgba(245,158,11,0.12)",
  orange: "#f97316",
  orangeBg: "rgba(249,115,22,0.12)",
  red: "#ef4444",
  redBg: "rgba(239,68,68,0.12)",
  dRed: "#dc2626",
  dRedBg: "rgba(220,38,38,0.15)",
} as const;

export type TierKey = "clear" | "monitor" | "elevated" | "hard_stop";
export type RiskKey = "low" | "medium" | "elevated" | "high" | "critical";

export const TIER_META: Record<TierKey, { label: string; color: string; bg: string }> = {
  clear:     { label: "CLEAR",     color: T.green,  bg: T.greenBg  },
  monitor:   { label: "MONITOR",   color: T.amber,  bg: T.amberBg  },
  elevated:  { label: "ELEVATED",  color: T.red,    bg: T.redBg    },
  hard_stop: { label: "HARD STOP", color: T.dRed,   bg: T.dRedBg   },
};

export const RISK_META: Record<RiskKey, { label: string; color: string; bg: string }> = {
  low:      { label: "LOW",      color: T.green,  bg: T.greenBg  },
  medium:   { label: "MEDIUM",   color: T.amber,  bg: T.amberBg  },
  elevated: { label: "ELEVATED", color: T.orange, bg: T.orangeBg },
  high:     { label: "HIGH",     color: T.red,    bg: T.redBg    },
  critical: { label: "CRITICAL", color: T.dRed,   bg: T.dRedBg   },
};

export function probColor(p: number): string {
  if (p < 0.15) return T.green;
  if (p < 0.3) return T.amber;
  if (p < 0.5) return T.orange;
  return T.red;
}

