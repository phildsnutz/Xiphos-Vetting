/**
 * Helios Design System v3.0
 *
 * "Simplicity is the ultimate sophistication."
 *
 * Typography: Comfortable at arm's length. Base 14px (not 13).
 * Color: Semantic only. Every color drives a decision.
 * Spacing: Consistent scale. Breathing room signals confidence.
 */

export const T = {
  // Backgrounds (darker = more depth)
  bg: "#0a0a0f",
  surface: "#111118",
  surfaceElevated: "#18181f",
  border: "#1e1e2a",
  borderActive: "#2a2a3a",

  // Text (3 levels: primary, secondary, tertiary)
  text: "#e8e8ed",
  textSecondary: "#9898a8",
  textTertiary: "#5a5a6a",

  // Primary action (ONE accent, cyan)
  accent: "#0ea5e9",
  accentHover: "#38bdf8",
  accentGlow: "rgba(14, 165, 233, 0.15)",

  // Semantic status colors (badges/indicators ONLY)
  statusBlocked: "#ef4444",
  statusReview: "#f59e0b",
  statusWatch: "#f59e0b",
  statusQualified: "#3b82f6",
  statusApproved: "#22c55e",

  // Backward-compatible aliases (used by App.tsx, case-detail.tsx, action-panel.tsx, etc.)
  muted: "#9898a8",
  dim: "#5a5a6a",
  raised: "#18181f",
  borderStrong: "#2a2a3a",
  green: "#22c55e",
  amber: "#f59e0b",
  amberBg: "rgba(245, 158, 11, 0.12)",
  red: "#ef4444",
  redBg: "rgba(239, 68, 68, 0.12)",
  greenBg: "rgba(34, 197, 94, 0.12)",
  accentSoft: "rgba(14, 165, 233, 0.12)",
  cyan: "#0ea5e9",
  gold: "#f59e0b",
  goldDim: "rgba(245, 158, 11, 0.5)",
  goldSoft: "rgba(245, 158, 11, 0.12)",
  teal: "#0ea5e9",
  tealSoft: "rgba(14, 165, 233, 0.12)",
  dRed: "#ef4444",
  dRedBg: "rgba(239, 68, 68, 0.12)",
  orange: "#f97316",
  orangeBg: "rgba(249, 115, 22, 0.12)",
  hover: "#18181f",
  borderLight: "#1e1e2a",
  hardStopBg: "rgba(239, 68, 68, 0.10)",
  hardStopBorder: "rgba(239, 68, 68, 0.3)",
} as const;

// FX object for backward compat (gradients stripped down)
export const FX = {
  glassCard: `background: #111118; border: 1px solid #1e1e2a; border-radius: 8px;`,
  glassBorder: "1px solid #1e1e2a",
  focusRing: "0 0 0 2px rgba(14, 165, 233, 0.3)",
  cardShadow: "0 2px 8px rgba(0,0,0,0.3)",
  cardHover: "0 4px 16px rgba(0,0,0,0.4)",
  softShadow: "0 2px 8px rgba(0,0,0,0.3)",
  shell: "background: #111118; border: 1px solid #1e1e2a; border-radius: 8px;",
  panel: "background: #111118; border: 1px solid #1e1e2a; border-radius: 8px;",
  panelStrong: "background: #18181f; border: 1px solid #2a2a3a; border-radius: 8px;",
  hero: "background: linear-gradient(135deg, #111118 0%, #0a0a0f 100%); border: 1px solid #1e1e2a; border-radius: 12px;",
  cardGlow: "0 0 20px rgba(14, 165, 233, 0.08)",
  tableRowHover: "0 4px 12px rgba(0,0,0,0.3)",
} as const;

export const FONTS = {
  mono: "'JetBrains Mono', 'Fira Code', monospace",
  sans: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
} as const;

/**
 * Type scale v3.0
 *
 * Minimum readable: 12px (captions)
 * Body text: 14px (base)
 * Headings: 18px (medium), 24px (large)
 *
 * Font stack: Inter, system fonts
 */
export const FS = {
  caption: 12,  // captions, timestamps, disabled text
  base: 14,     // body text, descriptions
  sm: 13,       // body secondary (metadata, labels)
  md: 18,       // heading medium, subheadings
  lg: 24,       // heading large, section titles
  xl: 32,       // hero / display
} as const;

/**
 * Spacing scale v3.0
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

/**
 * Display metadata for each tier.
 *
 * Operator-first normalization: all tiers in a band share the same
 * operator-facing label. Internal tier names stay in code, never on screen.
 *   TIER_1_* -> BLOCKED
 *   TIER_2_* -> REVIEW
 *   TIER_3_* -> WATCH
 *   TIER_4_* -> QUALIFIED / APPROVED
 */
export const TIER_META: Record<TierKey, { label: string; shortLabel: string; color: string; bg: string; band: TierBand }> = {
  UNSCORED:                     { label: "UNSCORED",    shortLabel: "UNSCORED",    color: T.textTertiary,    bg: "transparent",      band: "clear" },
  TIER_1_DISQUALIFIED:          { label: "BLOCKED",     shortLabel: "BLOCKED",     color: T.statusBlocked,   bg: T.statusBlocked,    band: "critical" },
  TIER_1_CRITICAL_CONCERN:      { label: "BLOCKED",     shortLabel: "BLOCKED",     color: T.statusBlocked,   bg: T.statusBlocked,    band: "critical" },
  TIER_2_ELEVATED_REVIEW:       { label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_2_CONDITIONAL_ACCEPTABLE:{ label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_2_HIGH_CONCERN:          { label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_2_ELEVATED:              { label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_2_CAUTION:               { label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_2_CAUTION_COMMERCIAL:    { label: "REVIEW",      shortLabel: "REVIEW",      color: T.statusReview,    bg: T.statusReview,     band: "elevated" },
  TIER_3_CONDITIONAL:           { label: "WATCH",       shortLabel: "WATCH",       color: T.statusWatch,     bg: T.statusWatch,      band: "conditional" },
  TIER_3_CRITICAL_ACCEPTABLE:   { label: "WATCH",       shortLabel: "WATCH",       color: T.statusWatch,     bg: T.statusWatch,      band: "conditional" },
  TIER_4_CRITICAL_QUALIFIED:    { label: "QUALIFIED",   shortLabel: "QUALIFIED",   color: T.statusQualified, bg: T.statusQualified,  band: "clear" },
  TIER_4_APPROVED:              { label: "APPROVED",    shortLabel: "APPROVED",    color: T.statusApproved,  bg: T.statusApproved,   band: "clear" },
  TIER_4_CLEAR:                 { label: "APPROVED",    shortLabel: "APPROVED",    color: T.statusApproved,  bg: T.statusApproved,   band: "clear" },
};

/**
 * Program Scrutiny Level metadata (sensitivity context).
 * These are Helios-native labels -- NOT classification markings.
 */
export type SensitivityKey = "CRITICAL_SAP" | "CRITICAL_SCI" | "ELEVATED" | "ENHANCED" | "CONTROLLED" | "STANDARD" | "COMMERCIAL";

export const SENSITIVITY_META: Record<SensitivityKey, { label: string; color: string; bg: string; tagColor: string }> = {
  CRITICAL_SAP: { label: "CRITICAL",    color: T.text,  bg: T.statusBlocked, tagColor: T.statusBlocked },
  CRITICAL_SCI: { label: "CRITICAL",    color: T.text,  bg: T.statusBlocked, tagColor: T.statusBlocked },
  ELEVATED:     { label: "ELEVATED",    color: T.text,  bg: T.statusReview,  tagColor: T.statusReview },
  ENHANCED:     { label: "ENHANCED",    color: T.text,  bg: T.statusReview,  tagColor: T.statusReview },
  CONTROLLED:   { label: "CONTROLLED",  color: T.text,  bg: T.statusQualified, tagColor: T.statusQualified },
  STANDARD:     { label: "STANDARD",    color: T.text,  bg: T.statusApproved,  tagColor: T.statusApproved },
  COMMERCIAL:   { label: "COMMERCIAL",  color: T.textSecondary, bg: T.surface, tagColor: T.textTertiary },
};

export function parseSensitivity(raw: string | undefined | null): SensitivityKey {
  if (!raw) return "COMMERCIAL";
  if (raw in SENSITIVITY_META) return raw as SensitivityKey;
  return "COMMERCIAL";
}

/** Band-level display metadata (for aggregated views like dashboards) */
export const BAND_META: Record<TierBand, { label: string; color: string; bg: string }> = {
  critical:    { label: "BLOCKED",      color: T.statusBlocked,  bg: T.statusBlocked },
  elevated:    { label: "REVIEW",       color: T.statusReview,   bg: T.statusReview },
  conditional: { label: "WATCH",        color: T.statusWatch,    bg: T.statusWatch },
  clear:       { label: "APPROVED",     color: T.statusApproved, bg: T.statusApproved },
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
  return TIER_META[tier]?.color ?? T.statusApproved;
}

/** Reverse map: operator label -> first matching TierKey */
const _LABEL_TO_TIER: Record<string, TierKey> = {};
for (const [k, v] of Object.entries(TIER_META)) {
  const lbl = v.label.toUpperCase();
  if (!(lbl in _LABEL_TO_TIER)) _LABEL_TO_TIER[lbl] = k as TierKey;
}

/** Safely parse a tier string from the backend. Falls back to TIER_4_CLEAR. */
export function parseTier(raw: string | undefined | null): TierKey {
  if (!raw) return "TIER_4_CLEAR";
  if (raw in TIER_META) return raw as TierKey;
  // Support operator-facing labels returned by the scoring engine (e.g. "BLOCKED", "REVIEW")
  const upper = raw.toUpperCase();
  if (upper in _LABEL_TO_TIER) return _LABEL_TO_TIER[upper];
  return "TIER_4_CLEAR";
}

/** The 4 bands in display order (most severe first) for dashboard aggregation */
export const TIER_BANDS: TierBand[] = ["critical", "elevated", "conditional", "clear"];

/** All tiers belonging to a band */
export function tiersInBand(band: TierBand): TierKey[] {
  return (Object.keys(TIER_META) as TierKey[]).filter(t => TIER_META[t].band === band);
}

export const RISK_META: Record<RiskKey, { label: string; color: string; bg: string }> = {
  low:      { label: "LOW",      color: T.statusApproved, bg: T.statusApproved  },
  medium:   { label: "MEDIUM",   color: T.statusWatch,    bg: T.statusWatch },
  elevated: { label: "ELEVATED", color: T.statusReview,   bg: T.statusReview },
  high:     { label: "HIGH",     color: T.statusReview,   bg: T.statusReview },
  critical: { label: "CRITICAL", color: T.statusBlocked,  bg: T.statusBlocked },
};

export function probColor(p: number): string {
  if (p < 0.15) return T.statusApproved;
  if (p < 0.3) return T.statusWatch;
  if (p < 0.5) return T.statusReview;
  return T.statusBlocked;
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

/**
 * Smart title-case for vendor names.
 * - Replaces underscores with spaces
 * - Strips state incorporation suffixes like /DE/, /NV/
 * - Title-cases each word
 * - Preserves corporate suffixes in uppercase (LLC, INC, CORP, etc.)
 */
export function displayName(raw: string): string {
  return raw
    .replace(/_/g, " ")
    .replace(/\s*\/[A-Z]{2}\/\s*/g, "")
    .replace(/\b\w+/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .replace(/\b(Llc|Inc|Corp|Ltd|Plc|Lp|Llp|Pllc|Co)\b/gi, (m) => m.toUpperCase())
    .trim();
}
