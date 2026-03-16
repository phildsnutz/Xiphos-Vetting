/** Xiphos design tokens - defense-grade design system */

export const T = {
  // Backgrounds
  bg: "#0a0e17",
  surface: "#111827",
  hover: "#1a2234",
  raised: "#162032",
  border: "#1e293b",
  borderLight: "#2a3a52",

  // Text
  text: "#e2e8f0",
  dim: "#94a3b8",
  muted: "#64748b",

  // Primary
  accent: "#3b82f6",
  accentHover: "#2563eb",

  // Semantic
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

  // Hard stop specific
  hardStopBg: "#7f1d1d",
  hardStopBorder: "#b91c1c",
} as const;

/** Type scale - minimum 11px, modular scale */
export const FS = {
  xs: 11,     // smallest allowed (was 8-9)
  sm: 12,     // secondary text
  base: 13,   // body text
  md: 14,     // emphasized body
  lg: 16,     // section headers
  xl: 20,     // large numbers
  xxl: 28,    // hero metrics
  huge: 36,   // page titles
} as const;

/** Spacing scale */
export const SP = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export type TierKey = "clear" | "monitor" | "elevated" | "hard_stop";
export type RiskKey = "low" | "medium" | "elevated" | "high" | "critical";

export const TIER_META: Record<TierKey, { label: string; color: string; bg: string }> = {
  clear:     { label: "CLEAR",     color: T.green,  bg: T.greenBg  },
  monitor:   { label: "MONITOR",   color: T.amber,  bg: T.amberBg  },
  elevated:  { label: "ELEVATED",  color: T.red,    bg: T.redBg    },
  hard_stop: { label: "HARD STOP", color: "#ffffff", bg: T.hardStopBg },
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

/** Verbal interpretation of posterior probability */
export function probLabel(p: number): string {
  if (p < 0.10) return "Very low risk";
  if (p < 0.20) return "Low risk";
  if (p < 0.35) return "Moderate risk";
  if (p < 0.50) return "Elevated risk";
  if (p < 0.70) return "High risk";
  return "Very high risk";
}
