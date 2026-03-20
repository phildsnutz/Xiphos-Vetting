/**
 * Xiphos Design System v2.0
 *
 * "Simplicity is the ultimate sophistication."
 *
 * Typography: Comfortable at arm's length. Base 14px (not 13).
 * Color: Semantic only. Every color drives a decision.
 * Spacing: Consistent scale. Breathing room signals confidence.
 */

export const T = {
  // Backgrounds (darker = more depth)
  bg: "#0b1119",
  surface: "#101925",
  hover: "#162233",
  raised: "#131e2c",
  border: "rgba(148,163,184,0.14)",
  borderLight: "rgba(148,163,184,0.22)",

  // Text (3 levels: primary, secondary, tertiary)
  text: "#e6edf5",
  dim: "#a4b2c5",
  muted: "#6c7b91",

  // Primary action
  accent: "#60a5fa",
  accentHover: "#3b82f6",

  // Semantic (each color means exactly one thing)
  green: "#10b981",       // CLEAR / APPROVED
  greenBg: "rgba(16,185,129,0.10)",
  amber: "#f59e0b",       // CONDITIONAL / REVIEW
  amberBg: "rgba(245,158,11,0.10)",
  orange: "#f97316",      // ELEVATED / CAUTION
  orangeBg: "rgba(249,115,22,0.10)",
  red: "#ef4444",         // CRITICAL / BLOCK
  redBg: "rgba(239,68,68,0.10)",
  dRed: "#dc2626",
  dRedBg: "rgba(220,38,38,0.12)",

  // Hard stop (unmistakable prohibition)
  hardStopBg: "#7f3030",
  hardStopBorder: "#dc2626",
} as const;

/**
 * Type scale v2.1
 *
 * Minimum readable: 13px (labels, timestamps)
 * Body text: 15px (generous, confident, easy to scan)
 * Section heads: 20px (clear hierarchy)
 *
 * 3-level hierarchy: heading (lg/xl) > body (base/md) > caption (sm)
 */
export const FS = {
  sm: 13,       // labels, timestamps, metadata
  base: 15,     // body text, descriptions, findings
  md: 17,       // subheadings, emphasized text
  lg: 20,       // section headers
  xl: 24,       // page section titles
  xxl: 30,      // page titles
  huge: 40,     // hero metrics, dashboard KPIs
} as const;

/**
 * Spacing scale v2.0
 *
 * Consistent rhythm. No magic numbers.
 * Use SP.lg (16px) between related items.
 * Use SP.xl (24px) between sections.
 * Use SP.xxl (32px) for page-level breathing room.
 */
export const SP = {
  xs: 4,        // hairline (icon + text inline)
  sm: 8,        // tight gap (badge padding, inline items)
  md: 12,       // card internal padding
  lg: 16,       // between related items
  xl: 24,       // between sections
  xxl: 32,      // page margins
  xxxl: 48,     // hero/section separators
} as const;


// =============================================================================
// v5.0 TIER SYSTEM
// =============================================================================

/**
 * All v5.0 tier names from the FGAMLogit two-layer integration.
 * TIER_1 = critical/blocked, TIER_2 = elevated concern, TIER_3 = conditional, TIER_4 = approved/clear
 */
export type TierKey =
  | "UNSCORED"
  | "TIER_1_DISQUALIFIED"
  | "TIER_1_CRITICAL_CONCERN"
  | "TIER_2_ELEVATED_REVIEW"
  | "TIER_2_CONDITIONAL_ACCEPTABLE"
  | "TIER_2_HIGH_CONCERN"
  | "TIER_2_ELEVATED"
  | "TIER_2_CAUTION"
  | "TIER_2_CAUTION_COMMERCIAL"
  | "TIER_3_CONDITIONAL"
  | "TIER_3_CRITICAL_ACCEPTABLE"
  | "TIER_4_CRITICAL_QUALIFIED"
  | "TIER_4_APPROVED"
  | "TIER_4_CLEAR";

export type RiskKey = "low" | "medium" | "elevated" | "high" | "critical";

/** Tier category: groups individual tiers into 4 visual bands */
export type TierBand = "critical" | "elevated" | "conditional" | "clear";

/** Which band does this tier belong to? */
export function tierBand(tier: TierKey): TierBand {
  if (tier === "UNSCORED") return "clear";  // Unscored cases are neutral, not "clear"
  if (tier.startsWith("TIER_1")) return "critical";
  if (tier.startsWith("TIER_2")) return "elevated";
  if (tier.startsWith("TIER_3")) return "conditional";
  return "clear";
}

/** Display metadata for each tier */
export const TIER_META: Record<TierKey, { label: string; shortLabel: string; color: string; bg: string; band: TierBand }> = {
  UNSCORED:                     { label: "UNSCORED",                  shortLabel: "UNSCORED",         color: T.muted,    bg: "transparent",  band: "clear" },
  TIER_1_DISQUALIFIED:          { label: "DISQUALIFIED",              shortLabel: "DISQUALIFIED",     color: "#ffffff",  bg: T.hardStopBg,  band: "critical" },
  TIER_1_CRITICAL_CONCERN:      { label: "CRITICAL CONCERN",          shortLabel: "CRITICAL",         color: "#ffffff",  bg: T.hardStopBg,  band: "critical" },
  TIER_2_ELEVATED_REVIEW:       { label: "ELEVATED REVIEW",           shortLabel: "ELEVATED",         color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_CONDITIONAL_ACCEPTABLE:{ label: "CONDITIONAL ACCEPTABLE",    shortLabel: "CONDITIONAL",      color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_2_HIGH_CONCERN:          { label: "HIGH CONCERN",              shortLabel: "HIGH CONCERN",     color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_ELEVATED:              { label: "ELEVATED",                  shortLabel: "ELEVATED",         color: T.red,      bg: T.redBg,       band: "elevated" },
  TIER_2_CAUTION:               { label: "CAUTION",                   shortLabel: "CAUTION",          color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_2_CAUTION_COMMERCIAL:    { label: "CAUTION",                   shortLabel: "CAUTION",          color: T.orange,   bg: T.orangeBg,    band: "elevated" },
  TIER_3_CONDITIONAL:           { label: "CONDITIONAL",               shortLabel: "CONDITIONAL",      color: T.amber,    bg: T.amberBg,     band: "conditional" },
  TIER_3_CRITICAL_ACCEPTABLE:   { label: "CRITICAL ACCEPTABLE",       shortLabel: "CRITICAL OK",      color: T.amber,    bg: T.amberBg,     band: "conditional" },
  TIER_4_CRITICAL_QUALIFIED:    { label: "CRITICAL QUALIFIED",        shortLabel: "QUALIFIED",        color: T.green,    bg: T.greenBg,     band: "clear" },
  TIER_4_APPROVED:              { label: "APPROVED",                  shortLabel: "APPROVED",         color: T.green,    bg: T.greenBg,     band: "clear" },
  TIER_4_CLEAR:                 { label: "CLEAR",                     shortLabel: "CLEAR",            color: T.green,    bg: T.greenBg,     band: "clear" },
};

/**
 * Program Scrutiny Level metadata (sensitivity context).
 * These are Xiphos-native labels -- NOT classification markings.
 */
export type SensitivityKey = "CRITICAL_SAP" | "CRITICAL_SCI" | "ELEVATED" | "ENHANCED" | "CONTROLLED" | "STANDARD" | "COMMERCIAL";

export const SENSITIVITY_META: Record<SensitivityKey, { label: string; color: string; bg: string; tagColor: string }> = {
  CRITICAL_SAP: { label: "CRITICAL",    color: "#ffffff",  bg: "#991b1b", tagColor: "#ef4444" },
  CRITICAL_SCI: { label: "CRITICAL",    color: "#ffffff",  bg: "#991b1b", tagColor: "#ef4444" },
  ELEVATED:     { label: "ELEVATED",    color: "#ffffff",  bg: "#c2410c", tagColor: "#f97316" },
  ENHANCED:     { label: "ENHANCED",    color: "#ffffff",  bg: "#a16207", tagColor: "#f59e0b" },
  CONTROLLED:   { label: "CONTROLLED",  color: "#ffffff",  bg: "#1d4ed8", tagColor: "#3b82f6" },
  STANDARD:     { label: "STANDARD",    color: "#ffffff",  bg: "#15803d", tagColor: "#10b981" },
  COMMERCIAL:   { label: "COMMERCIAL",  color: T.dim,      bg: T.raised,  tagColor: T.muted },
};

export function parseSensitivity(raw: string | undefined | null): SensitivityKey {
  if (!raw) return "COMMERCIAL";
  if (raw in SENSITIVITY_META) return raw as SensitivityKey;
  return "COMMERCIAL";
}

/** Band-level display metadata (for aggregated views like dashboards) */
export const BAND_META: Record<TierBand, { label: string; color: string; bg: string }> = {
  critical:    { label: "CRITICAL",     color: "#ffffff",  bg: T.hardStopBg },
  elevated:    { label: "ELEVATED",     color: T.red,      bg: T.redBg },
  conditional: { label: "CONDITIONAL",  color: T.amber,    bg: T.amberBg },
  clear:       { label: "CLEAR",        color: T.green,    bg: T.greenBg },
};

/** Map a tier to risk level (for the legacy risk-level display) */
export function tierToRisk(tier: TierKey): RiskKey {
  const b = tierBand(tier);
  if (b === "critical") return "critical";
  if (b === "elevated") return "elevated";
  if (b === "conditional") return "medium";
  return "low";
}

/** Get color for a tier */
export function tierColor(tier: TierKey): string {
  return TIER_META[tier]?.color ?? T.green;
}

/** Safely parse a tier string from the backend. Falls back to TIER_4_CLEAR. */
export function parseTier(raw: string | undefined | null): TierKey {
  if (!raw) return "TIER_4_CLEAR";
  if (raw in TIER_META) return raw as TierKey;
  return "TIER_4_CLEAR";
}

/** The 4 bands in display order (most severe first) for dashboard aggregation */
export const TIER_BANDS: TierBand[] = ["critical", "elevated", "conditional", "clear"];

/** All tiers belonging to a band */
export function tiersInBand(band: TierBand): TierKey[] {
  return (Object.keys(TIER_META) as TierKey[]).filter(t => TIER_META[t].band === band);
}

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
