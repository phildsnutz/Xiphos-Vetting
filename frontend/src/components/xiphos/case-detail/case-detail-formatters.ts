import type { EnrichmentReport, ExportAuthorizationCaseInput, FociArtifactType, MonitoringHistoryEntry, SupplierPassport } from "@/lib/api";
import { T, TIER_META, parseTier } from "@/lib/tokens";
import type { EvidenceTabId } from "./case-detail-types";

export function inferFociArtifactType(filename: string): FociArtifactType {
  const lower = filename.toLowerCase();
  if (lower.includes("328")) return "foci_form_328";
  if (lower.includes("ownership") || lower.includes("org-chart") || lower.includes("orgchart")) return "foci_ownership_chart";
  if (lower.includes("cap") || lower.includes("stock") || lower.includes("ledger")) return "foci_cap_table_or_stock_ledger";
  if (lower.includes("board") || lower.includes("kmp") || lower.includes("director")) return "foci_kmp_or_board_list";
  if (lower.includes("mitigation") || lower.includes("ssa") || lower.includes("sca") || lower.includes("proxy") || lower.includes("trust")) {
    return "foci_mitigation_instrument";
  }
  return "foci_supporting_memo";
}

export function splitProductTermsInput(value: string) {
  return value
    .split(/\n|,/g)
    .map((term) => term.trim())
    .filter(Boolean);
}

export function sprsStatusLabel(status: string | null | undefined) {
  const normalized = String(status || "").trim();
  return normalized ? normalized.replaceAll("_", " ") : "Status not provided";
}

export function oscalArtifactTypeLabel(type: string) {
  switch (type) {
    case "oscal_ssp":
      return "OSCAL SSP";
    case "oscal_poam":
      return "OSCAL POA&M";
    default:
      return type.replaceAll("_", " ");
  }
}

export function monitoringEntryTone(entry: MonitoringHistoryEntry) {
  if (entry.risk_changed) {
    return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33`, label: "Risk changed" };
  }
  if ((entry.new_findings_count ?? 0) > 0) {
    return { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33`, label: "New findings" };
  }
  return { color: T.green, background: `${T.green}12`, border: `${T.green}33`, label: "Stable" };
}

export function defaultEvidenceTab(report: EnrichmentReport): EvidenceTabId {
  return report.intel_summary ? "intel" : "findings";
}

export function formatMonitorTierLabel(tier?: string | null) {
  if (!tier) return "Unknown";
  const parsed = parseTier(tier);
  return TIER_META[parsed]?.label ?? tier.replace(/^TIER_\d+_/, "").replaceAll("_", " ");
}

export function passportPostureTone(posture?: SupplierPassport["posture"] | null) {
  switch (String(posture || "").toLowerCase()) {
    case "approved":
      return { color: T.green, background: `${T.green}12`, border: `${T.green}33` };
    case "review":
      return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33` };
    case "blocked":
      return { color: T.red, background: `${T.red}12`, border: `${T.red}33` };
    default:
      return { color: T.muted, background: T.surface, border: T.border };
  }
}

export function officialCorroborationTone(
  official?: SupplierPassport["identity"]["official_corroboration"] | null,
) {
  switch (String(official?.coverage_level || "").toLowerCase()) {
    case "strong":
      return { color: T.green, background: `${T.green}12`, border: `${T.green}33` };
    case "partial":
      return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33` };
    case "public_only":
      return { color: T.red, background: `${T.red}12`, border: `${T.red}33` };
    default:
      return { color: T.muted, background: T.surface, border: T.border };
  }
}

export function exportRequestTypeLabel(requestType?: ExportAuthorizationCaseInput["request_type"] | null) {
  switch (requestType) {
    case "item_transfer":
      return "Item transfer";
    case "foreign_person_access":
      return "Foreign-person access";
    case "technical_data_release":
      return "Technical-data release";
    default:
      return "Authorization review";
  }
}

export function fociArtifactTypeLabel(type: FociArtifactType | string) {
  switch (type) {
    case "foci_form_328":
      return "FOCI Form 328";
    case "foci_ownership_chart":
      return "Ownership Chart";
    case "foci_cap_table_or_stock_ledger":
      return "Cap Table / Stock Ledger";
    case "foci_kmp_or_board_list":
      return "KMP / Board List";
    case "foci_mitigation_instrument":
      return "Mitigation Instrument";
    case "foci_supporting_memo":
      return "Supporting Memo";
    default:
      return type.replaceAll("_", " ");
  }
}
