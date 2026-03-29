/**
 * workflow-copy.ts — Operator-facing copy, single source of truth.
 *
 * Every label, trigger explanation, severity name, and recommendation
 * string that reaches the operator flows through this file.
 *
 * Rules:
 *   1. No jargon. If a phrase needs a glossary, rewrite it.
 *   2. Actionable. Every trigger label ends with what the operator should do.
 *   3. Consistent. Same concept = same word everywhere.
 *   4. Fallback gracefully. Unmapped values get snake_case -> Title Case.
 *
 * Ported from CODEX, expanded with MERGED domain-specific additions.
 */

import type { VettingCase } from "./types";
import { parseTier, tierBand, type TierKey } from "./tokens";

// ---------------------------------------------------------------------------
// Program labels
// ---------------------------------------------------------------------------

const PROGRAM_LABELS: Record<string, string> = {
  dod_classified: "DoD/IC",
  dod_unclassified: "DoD",
  federal_non_dod: "Federal",
  regulated_commercial: "Regulated",
  commercial: "Commercial",
  defense_acquisition: "Defense",
  cat_xi_electronics: "ITAR XI",
  weapons_system: "DoD",
  mission_critical: "Federal",
  critical_infrastructure: "Federal",
  dual_use: "Regulated",
  dual_use_ear: "Regulated",
  standard_industrial: "Commercial",
  commercial_off_shelf: "Commercial",
  services: "Commercial",
};

export function formatProgramLabel(program?: string): string {
  if (!program) return "";
  if (PROGRAM_LABELS[program]) return PROGRAM_LABELS[program];
  return program
    .replace(/^cat_/i, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

// ---------------------------------------------------------------------------
// Trigger labels — plain-language, action-oriented
// ---------------------------------------------------------------------------

export function formatTriggerLabel(title: string): string {
  if (/^ENTITY Match:/i.test(title)) return "Confirm the legal entity before proceeding.";
  if (/Sanctions (List )?Match/i.test(title) || /OSINT Sanctions Match/i.test(title)) {
    return "Blocked by sanctions or restricted-party signal.";
  }
  if (/Limited Operating History/i.test(title)) return "Collect more operating history before award.";
  if (/Foreign Ownership/i.test(title)) return "Review foreign ownership and control evidence.";
  if (/Unresolved Beneficial Ownership/i.test(title)) return "Resolve beneficial ownership before award.";
  if (/Cross-Jurisdiction Name Similarity/i.test(title)) return "Confirm the cross-border entity match before proceeding.";
  if (/Adverse Media/i.test(title)) return "Review the adverse media signal before award.";
  if (/Deemed Export Risk/i.test(title)) return "Do not release data or access until export review clears.";
  if (/USML Category Control/i.test(title)) return "Confirm the item classification and export controls.";
  if (/ITAR/i.test(title) || /EAR/i.test(title)) return "Escalate export review before release.";
  if (/CMMC/i.test(title)) return "Collect supplier cyber readiness evidence before award.";
  return title.replace(/_/g, " ");
}

export function summarizePrimaryTrigger(c: VettingCase): {
  tone: "stop" | "flag" | null;
  label: string;
  extra: string;
} {
  if (c.cal?.stops?.length) {
    const extraCount = c.cal.stops.length - 1;
    return {
      tone: "stop",
      label: formatTriggerLabel(c.cal.stops[0].t),
      extra: extraCount > 0 ? `+${extraCount} more blocker${extraCount > 1 ? "s" : ""}` : "",
    };
  }
  if (c.cal?.flags?.length) {
    const extraCount = c.cal.flags.length - 1;
    return {
      tone: "flag",
      label: formatTriggerLabel(c.cal.flags[0].t),
      extra: extraCount > 0 ? `+${extraCount} more review trigger${extraCount > 1 ? "s" : ""}` : "",
    };
  }
  return { tone: null, label: "", extra: "" };
}

// ---------------------------------------------------------------------------
// Factor labels — risk model dimension names for operators
// ---------------------------------------------------------------------------

const FACTOR_LABELS: Record<string, string> = {
  sanctions: "Sanctions and denied-party screening",
  regulatory_gate_proximity: "Regulatory gate posture",
  foreign_ownership_depth: "Foreign ownership clarity",
  compliance_history: "Compliance history",
  geopolitical_sector_exposure: "Sector and geopolitical exposure",
  ear_control_status: "EAR control posture",
  cmmc_readiness: "CMMC readiness",
  single_source_risk: "Single-source risk",
  itar_exposure: "ITAR exposure",
  data_quality: "Record completeness",
  ownership: "Ownership resolution",
  financial_stability: "Financial stability",
  geography: "Geographic profile",
  executive: "Executive screening",
};

export function formatFactorLabel(name: string): string {
  if (FACTOR_LABELS[name]) return FACTOR_LABELS[name];
  return name.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

// ---------------------------------------------------------------------------
// Recommendation / decision headline
// ---------------------------------------------------------------------------

export function formatRecommendationLabel(tierRaw?: string | null): string {
  const tier = parseTier(tierRaw as TierKey | undefined);
  const band = tierBand(tier);
  if (band === "critical") return "Do not proceed";
  if (band === "elevated") return "Escalate for review";
  if (band === "conditional") return "Proceed with watch conditions";
  return "Proceed";
}

// ---------------------------------------------------------------------------
// Finding copy — translate model output into operator language
// ---------------------------------------------------------------------------

export function formatFindingCopy(text: string): string {
  if (/^\d+ advisory flag\(s\) requiring analyst review\./i.test(text)) {
    const count = text.match(/^(\d+)/)?.[1] ?? "1";
    return `${count} review trigger${count === "1" ? " requires" : "s require"} analyst attention.`;
  }
  if (/^Entity has only 0 year\(s\) of verifiable records\./i.test(text)) {
    return "No verifiable operating history was found.";
  }
  const yearsMatch = text.match(/^Entity has only (\d+) year\(s\) of verifiable records\./i);
  if (yearsMatch) {
    const years = yearsMatch[1];
    return `Only ${years} year${years === "1" ? "" : "s"} of verifiable operating history were found.`;
  }
  if (/^Hard stop triggered:/i.test(text)) {
    return text.replace(/^Hard stop triggered:\s*/i, "").replace(/\.\s*This is an absolute compliance barrier\.$/i, ".");
  }
  return text;
}

// ---------------------------------------------------------------------------
// Severity labels — map model severity to operator urgency
// ---------------------------------------------------------------------------

export function formatSeverityLabel(severity: string): string {
  const sev = severity.toLowerCase();
  if (sev === "critical") return "Urgent";
  if (sev === "high") return "High";
  if (sev === "medium") return "Review";
  if (sev === "low") return "Info";
  return severity.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

// ---------------------------------------------------------------------------
// Relationship labels — entity graph edges (MERGED addition)
// ---------------------------------------------------------------------------

export const REL_LABELS: Record<string, string> = {
  // Corporate structure
  subsidiary: "Subsidiary",
  subsidiary_of: "Subsidiary Of",
  parent: "Parent company",
  parent_of: "Parent Of",
  joint_venture: "Joint venture",
  beneficial_owner: "Beneficial owner",
  affiliate: "Affiliate",
  alias_of: "Alias",
  former_name: "Former Name",
  related_entity: "Related",
  // People
  director: "Director",
  officer: "Officer",
  officer_of: "Officer Of",
  shareholder: "Shareholder",
  agent: "Agent",
  // Contract / commercial
  supplier: "Supplier",
  customer: "Customer",
  partner: "Partner",
  subcontractor_of: "Subcontractor",
  prime_contractor_of: "Prime Contractor",
  contracts_with: "Contracts With",
  // Legal / regulatory
  sanctioned_on: "Sanctioned On",
  sanctioned_person: "Sanctioned Person",
  litigant_in: "Litigant In",
  filed_with: "Filed With",
  regulated_by: "Regulated By",
  mentioned_with: "Mentioned With",
  // Person screening / export
  employed_by: "Employed By",
  screened_for: "Screened For",
  deemed_export_subject: "Deemed Export Subject",
  co_national: "Co-National",
  national_of: "National Of",
};

export function formatRelationshipLabel(rel: string): string {
  if (REL_LABELS[rel]) return REL_LABELS[rel];
  return rel.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

// ---------------------------------------------------------------------------
// Date formatting
// ---------------------------------------------------------------------------

export function formatCaseDateLabel(rawDate: string): string {
  const date = new Date(rawDate);
  if (Number.isNaN(date.getTime())) {
    return rawDate;
  }
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
