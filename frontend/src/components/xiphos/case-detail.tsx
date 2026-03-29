import { useState, useEffect, useMemo, useRef, useCallback, type ChangeEvent } from "react";
import { T, FS, FX, TIER_META, tierColor, parseTier, SENSITIVITY_META, parseSensitivity, tierBand, probLabel, displayName } from "@/lib/tokens";
import { ChevronLeft, FileText, Activity, Globe, Clock, XCircle, AlertTriangle, Loader2, TrendingUp, Radar, Lock, MoreHorizontal, Network, CheckCircle, Brain, Upload, Shield } from "lucide-react";
import { TierBadge } from "./badges";
import { Gauge } from "./gauge";
import { ContribBar } from "./charts";
import { EnrichmentPanel } from "./enrichment-panel";
import { EnrichmentStream } from "./enrichment-stream";
import { EntityGraph } from "./entity-graph";
import { AIAnalysisPanel } from "./ai-analysis-panel";
import { ActionPanel } from "./action-panel";
import { LoadingSpinner } from "./loader";
import { RiskStoryline } from "./risk-storyline";
import { buildProtectedUrl, computeCyberRiskScore, fetchAIAnalysisStatus, fetchCase, fetchCaseGraph, fetchCaseMonitorStatus, fetchCaseMonitoringHistory, fetchCaseNetworkRisk, fetchEnrichment, fetchSupplierPassport, generateDossier as requestDossier, listExportArtifacts, listFociArtifacts, listNvdOverlays, listOscalArtifacts, listSprsImports, runCaseMonitor, runNvdOverlay, uploadExportArtifact, uploadFociArtifact, uploadOscalArtifact, uploadSprsImport, runTransactionAuthorization, listTransactionAuthorizations, fetchTransactionAuthorization, fetchCaseScreenings, screenBatchCsv, screenPerson } from "@/lib/api";
import TransactionAuthorizationPanel from "./transaction-authorization-panel";
import type { TransactionAuthorizationResult } from "./transaction-authorization-panel";
import { getUser } from "@/lib/auth";
import { WORKFLOW_LANE_META } from "./portfolio-utils";
import type { WorkflowLane } from "./portfolio-utils";
import { formatFactorLabel, formatFindingCopy, formatRecommendationLabel, formatRelationshipLabel } from "@/lib/workflow-copy";
import type { AIAnalysisStatus, ApiCase, CaseGraphData, CaseMonitorStatus, CaseMonitoringHistory, CyberRiskScore, EnrichmentReport, ExportArtifactRecord, ExportArtifactType, ExportAuthorizationCaseInput, ExportAuthorizationGuidance, FociArtifactRecord, FociArtifactType, GraphRelationship, MonitoringHistoryEntry, NetworkRiskResult, NvdOverlayRecord, OscalArtifactRecord, PersonScreeningResult, RiskStoryline as RiskStorylineType, RiskStorylineCard, SprsImportRecord, SupplierPassport, SupplierPassportIdentifierStatus, WorkflowControlSummary } from "@/lib/api";
import type { VettingCase, ScoreSnapshot, Calibration } from "@/lib/types";
import { CONNECTOR_META } from "@/lib/connectors";

interface CaseDetailProps {
  c: VettingCase;
  onBack: () => void;
  onRescore?: (caseId: string) => Promise<void>;
  onDossier?: (caseId: string) => Promise<void>;
  onCaseRefresh?: (caseId: string) => Promise<void>;
  globalLane?: WorkflowLane;
  laneSummary?: {
    lane: WorkflowLane;
    label: string;
    shortLabel: string;
    description: string;
    activeCount: number;
    reviewCount: number;
    blockedCount: number;
    watchCount: number;
    summary: string;
    topCaseName: string | null;
  };
}

type EvidenceTab = "intel" | "findings" | "events" | "model" | "graph";
type GraphDepth = 3 | 4;
type AnalystView = "decision" | "evidence" | "model";

function monitorTone(status: string | null) {
  switch (status) {
    case "completed":
      return { color: T.green, background: `${T.green}18`, border: `${T.green}33`, icon: CheckCircle };
    case "running":
      return { color: T.accent, background: `${T.accent}18`, border: `${T.accent}33`, icon: Loader2 };
    case "queued":
      return { color: T.amber, background: `${T.amber}18`, border: `${T.amber}33`, icon: Clock };
    case "failed":
      return { color: T.red, background: T.redBg, border: `${T.red}33`, icon: XCircle };
    default:
      return { color: T.muted, background: T.surface, border: T.border, icon: Activity };
  }
}

function aiBriefTone(status: AIAnalysisStatus["status"] | null) {
  switch (status) {
    case "ready":
    case "completed":
      return { color: T.green, background: `${T.green}18`, border: `${T.green}33`, icon: CheckCircle };
    case "running":
      return { color: T.accent, background: `${T.accent}18`, border: `${T.accent}33`, icon: Loader2 };
    case "pending":
      return { color: T.amber, background: `${T.amber}18`, border: `${T.amber}33`, icon: Clock };
    case "failed":
      return { color: T.red, background: T.redBg, border: `${T.red}33`, icon: XCircle };
    case "missing":
      return { color: T.muted, background: T.surface, border: T.border, icon: Brain };
    default:
      return { color: T.muted, background: T.surface, border: T.border, icon: Brain };
  }
}

function connectorDisplayName(name: string) {
  return CONNECTOR_META[name as keyof typeof CONNECTOR_META]?.label || name;
}

function sourceStatusColor(hasData: boolean, error?: string) {
  if (error) return T.red;
  return hasData ? T.green : T.amber;
}

function sourceStatusTone(status: { has_data: boolean; error?: string }) {
  if (status.error) return "issue" as const;
  if (status.has_data) return "signal" as const;
  return "clear" as const;
}

function sourceStatusLabel(status: { has_data: boolean; error?: string }) {
  const tone = sourceStatusTone(status);
  if (tone === "issue") return "Attention needed";
  if (tone === "signal") return "Signal returned";
  return "Checked clear";
}

function formatMonitorTierLabel(tier?: string | null) {
  if (!tier) return "Unknown";
  const parsed = parseTier(tier);
  return TIER_META[parsed]?.label ?? tier.replace(/^TIER_\d+_/, "").replaceAll("_", " ");
}

function exportRequestTypeLabel(requestType?: ExportAuthorizationCaseInput["request_type"] | null) {
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

const CONTROL_PATH_RELATIONSHIPS = new Set([
  "backed_by",
  "depends_on_network",
  "depends_on_service",
  "routes_payment_through",
  "distributed_by",
  "operates_facility",
  "ships_via",
  "owned_by",
  "beneficially_owned_by",
]);

function formatGraphTimestamp(value?: string | null) {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatCaseHeaderTimestamp(value?: string | null) {
  if (!value) return "Unknown";
  const raw = String(value).trim();
  const candidates = [raw];
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw)) {
    candidates.push(raw.replace(" ", "T"));
  }
  for (const candidate of candidates) {
    const parsed = new Date(candidate);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }
  return raw;
}

function formatPassportPosture(posture?: string | null) {
  if (!posture) return "Pending";
  return posture.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function passportPostureTone(posture?: string | null) {
  switch (String(posture || "").toLowerCase()) {
    case "blocked":
      return { color: T.red, background: `${T.red}15`, border: `${T.red}33` };
    case "review":
      return { color: T.amber, background: `${T.amber}15`, border: `${T.amber}33` };
    case "approved":
      return { color: T.green, background: `${T.green}15`, border: `${T.green}33` };
    default:
      return { color: T.accent, background: `${T.accent}15`, border: `${T.accent}33` };
  }
}

function identifierStateLabel(status?: SupplierPassportIdentifierStatus | null) {
  const explicit = typeof status?.verification_label === "string" ? status.verification_label.trim() : "";
  if (explicit) return explicit;
  const state = String(status?.state || "").toLowerCase();
  const authority = String(status?.authority_level || "").toLowerCase();
  switch (state) {
    case "verified_present":
      if (authority === "first_party_self_disclosed") return "Publicly disclosed";
      if (authority === "third_party_public" || authority === "public_registry_aggregator") return "Publicly captured";
      return "Verified";
    case "verified_absent":
      return "Verified absent";
    case "unverified":
      return "Unverified";
    default:
      return "Missing";
  }
}

function identifierStateTone(status?: SupplierPassportIdentifierStatus | null) {
  const verificationTier = String(status?.verification_tier || "").toLowerCase();
  if (verificationTier === "verified") {
    return { color: T.green, background: `${T.green}15`, border: `${T.green}33` };
  }
  if (verificationTier === "publicly_disclosed") {
    return { color: T.accent, background: `${T.accent}15`, border: `${T.accent}33` };
  }
  if (verificationTier === "publicly_captured") {
    return { color: T.amber, background: `${T.amber}15`, border: `${T.amber}33` };
  }
  switch (String(status?.state || "").toLowerCase()) {
    case "verified_absent":
      return { color: T.muted, background: T.surface, border: `${T.border}` };
    case "unverified":
      return { color: T.amber, background: `${T.amber}15`, border: `${T.amber}33` };
    default:
      return { color: T.muted, background: T.surface, border: `${T.border}` };
  }
}

function tribunalViewTone(stance?: string | null) {
  switch (String(stance || "").toLowerCase()) {
    case "deny":
      return { color: T.red, background: T.redBg, border: `${T.red}33` };
    case "watch":
      return { color: T.amber, background: `${T.amber}15`, border: `${T.amber}33` };
    case "approve":
      return { color: T.green, background: `${T.green}15`, border: `${T.green}33` };
    default:
      return { color: T.accent, background: `${T.accent}15`, border: `${T.accent}33` };
  }
}

function supplierPassportControlField(
  workflowControl: SupplierPassport["ownership"]["workflow_control"] | null | undefined,
  key: "label" | "review_basis" | "action_owner",
) {
  if (!workflowControl || typeof workflowControl !== "object") return null;
  const value = workflowControl[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function officialCorroborationTone(
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

function officialFieldLabel(key?: string | null) {
  const normalized = String(key || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  const known: Record<string, string> = {
    cage: "CAGE",
    uei: "UEI",
    lei: "LEI",
    cik: "CIK",
    duns: "DUNS",
    website: "Website",
    uk_company_number: "UK company no.",
    ca_corporation_number: "CA corporation no.",
    abn: "ABN",
    acn: "ACN",
    uen: "UEN",
    nzbn: "NZBN",
    nz_company_number: "NZ company no.",
    norway_org_number: "NO org no.",
  };
  return known[normalized] || normalized.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatCountryHint(value?: string | null) {
  const normalized = String(value || "").trim().toUpperCase();
  if (!normalized) return "Unknown";
  const known: Record<string, string> = {
    US: "United States",
    USA: "United States",
    UK: "United Kingdom",
    GB: "United Kingdom",
    GBR: "United Kingdom",
    CA: "Canada",
    CAN: "Canada",
    AU: "Australia",
    AUS: "Australia",
    SG: "Singapore",
    SGP: "Singapore",
    NZ: "New Zealand",
    NZL: "New Zealand",
    NO: "Norway",
    NOR: "Norway",
  };
  return known[normalized] || normalized.replaceAll("_", " ");
}

function downloadSupplierPassportJson(passport: SupplierPassport) {
  const filenameBase = (passport.vendor.name || "supplier-passport")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "supplier-passport";
  const blob = new Blob([JSON.stringify(passport, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${filenameBase}-${passport.case_id}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function graphRelationshipPriority(relationship: GraphRelationship) {
  const corroboration = relationship.corroboration_count ?? relationship.data_sources?.length ?? 1;
  const confidence = relationship.confidence ?? 0;
  const controlPathBonus = CONTROL_PATH_RELATIONSHIPS.has(relationship.rel_type) ? 100 : 0;
  const sanctionBonus = relationship.rel_type === "sanctioned_on" || relationship.rel_type === "sanctioned_person" ? 120 : 0;
  return controlPathBonus + sanctionBonus + corroboration * 12 + confidence * 100;
}

function exportJurisdictionLabel(jurisdiction?: ExportAuthorizationCaseInput["jurisdiction_guess"] | null) {
  switch (jurisdiction) {
    case "itar":
      return "ITAR / USML";
    case "ear":
      return "EAR / ECCN";
    case "ofac_overlay":
      return "OFAC overlay";
    case "unknown":
      return "Needs jurisdiction review";
    default:
      return "Unspecified";
  }
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const deduped: string[] = [];
  for (const item of value) {
    const text = String(item || "").trim();
    if (text && !deduped.includes(text)) deduped.push(text);
  }
  return deduped;
}

function threatPressureTone(pressure?: string | null) {
  switch (String(pressure || "").toLowerCase()) {
    case "high":
      return { color: T.red, background: T.redBg, border: `${T.red}33` };
    case "medium":
      return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33` };
    case "low":
      return { color: T.green, background: `${T.green}12`, border: `${T.green}33` };
    default:
      return { color: T.muted, background: T.surface, border: T.border };
  }
}

function threatPressureLabel(pressure?: string | null) {
  const text = String(pressure || "").trim();
  if (!text) return "No active signal";
  return `${text.replaceAll("_", " ")} threat pressure`;
}

function exportGuidanceTone(posture?: ExportAuthorizationGuidance["posture"] | null) {
  switch (posture) {
    case "likely_prohibited":
      return { color: T.red, background: T.redBg, border: `${T.red}33`, label: "Likely prohibited" };
    case "likely_license_required":
      return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33`, label: "Likely license required" };
    case "likely_exception_or_exemption":
      return { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33`, label: "Exception / exemption path" };
    case "likely_nlr":
      return { color: T.green, background: `${T.green}12`, border: `${T.green}33`, label: "Likely NLR / low-friction" };
    case "escalate":
      return { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33`, label: "Escalate for review" };
    default:
      return { color: T.muted, background: T.surface, border: T.border, label: "Needs deeper review" };
  }
}

function controlSummaryTone(summary?: WorkflowControlSummary | null) {
  switch (summary?.support_level) {
    case "artifact_backed":
      return { color: T.green, background: `${T.green}12`, border: `${T.green}33` };
    case "partial":
      return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33` };
    case "triage_only":
      return { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33` };
    default:
      return { color: T.muted, background: T.surface, border: T.border };
  }
}

function exportArtifactTypeLabel(type: ExportArtifactType | string) {
  switch (type) {
    case "export_classification_memo":
      return "Classification memo";
    case "export_ccats_or_cj":
      return "CCATS / CJ";
    case "export_license_history":
      return "License history";
    case "export_access_control_record":
      return "Access-control record";
    case "export_technology_control_plan":
      return "Technology control plan";
    case "export_deccs_or_snapr_export":
      return "DECCS / SNAP-R export";
    default:
      return type.replaceAll("_", " ");
  }
}

function fociArtifactTypeLabel(type: FociArtifactType | string) {
  switch (type) {
    case "foci_form_328":
      return "Form 328";
    case "foci_ownership_chart":
      return "Ownership chart";
    case "foci_cap_table_or_stock_ledger":
      return "Cap table / stock ledger";
    case "foci_kmp_or_board_list":
      return "KMP / board list";
    case "foci_mitigation_instrument":
      return "Mitigation instrument";
    case "foci_supporting_memo":
      return "FOCI supporting memo";
    default:
      return type.replaceAll("_", " ");
  }
}

function inferFociArtifactType(filename: string): FociArtifactType {
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

function sprsStatusLabel(status: string | null | undefined) {
  const normalized = String(status || "").trim();
  return normalized ? normalized.replaceAll("_", " ") : "Status not provided";
}

function oscalArtifactTypeLabel(type: string) {
  switch (type) {
    case "oscal_ssp":
      return "OSCAL SSP";
    case "oscal_poam":
      return "OSCAL POA&M";
    default:
      return type.replaceAll("_", " ");
  }
}

function splitProductTermsInput(value: string) {
  return value
    .split(/\n|,/g)
    .map((term) => term.trim())
    .filter(Boolean);
}

function monitoringEntryTone(entry: MonitoringHistoryEntry) {
  if (entry.risk_changed) {
    return { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33`, label: "Risk changed" };
  }
  if ((entry.new_findings_count ?? 0) > 0) {
    return { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33`, label: "New findings" };
  }
  return { color: T.green, background: `${T.green}12`, border: `${T.green}33`, label: "Stable" };
}

function sourceStatusFindingSummary(status: { has_data: boolean; findings_count: number; error?: string }) {
  if (status.error) return "Connector error";
  if (status.has_data) {
    return status.findings_count === 1
      ? "1 finding surfaced"
      : `${status.findings_count} findings surfaced`;
  }
  return "No material return";
}

function defaultEvidenceTab(report: EnrichmentReport): EvidenceTab {
  return report.intel_summary ? "intel" : "findings";
}

function ScoreHistory({ history, current }: { history: ScoreSnapshot[]; current: { p: number; tier: string; ts: string } }) {
  const points = [...history, { p: current.p, tier: current.tier, sc: 0, ts: current.ts }];
  if (points.length < 2) return null;

  const w = 260;
  const h = 64;
  const padX = 24;
  const padY = 10;
  const chartW = w - padX * 2;
  const chartH = h - padY * 2;
  const maxP = Math.max(0.8, ...points.map((p) => p.p), 0.15) + 0.05;

  const x = (i: number) => padX + (i / (points.length - 1)) * chartW;
  const y = (p: number) => padY + chartH - (p / maxP) * chartH;
  const linePts = points.map((pt, i) => `${x(i)},${y(pt.p)}`).join(" ");

  const thresholds = [
    { val: 0.15, label: "CLR", color: T.green },
    { val: 0.30, label: "MON", color: T.amber },
    { val: 0.60, label: "STP", color: T.red },
  ].filter((t) => t.val < maxP);

  return (
    <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
      <div className="flex items-center gap-1.5 mb-2">
        <TrendingUp size={12} color={T.muted} />
        <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
          Score History
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          ({points.length} assessments)
        </span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", width: "100%", maxWidth: w }}>
        {thresholds.map((threshold) => (
          <g key={threshold.label}>
            <line
              x1={padX} y1={y(threshold.val)} x2={w - padX} y2={y(threshold.val)}
              stroke={threshold.color} strokeWidth={0.5} strokeDasharray="3,3" opacity={0.4}
            />
            <text x={w - padX + 3} y={y(threshold.val) + 3} fill={threshold.color} fontSize={7} fontFamily="monospace" opacity={0.6}>
              {threshold.label}
            </text>
          </g>
        ))}

        <polyline
          points={linePts}
          fill="none" stroke={T.accent} strokeWidth={1.5} strokeLinejoin="round"
        />

        {points.map((pt, i) => {
          const color = tierColor(parseTier(pt.tier));
          return (
            <g key={i}>
              <circle cx={x(i)} cy={y(pt.p)} r={3.5} fill={T.bg} stroke={color} strokeWidth={1.5} />
              {(i === 0 || i === points.length - 1) && (
                <text
                  x={x(i)} y={y(pt.p) - 7}
                  textAnchor="middle" fill={T.dim} fontSize={8} fontFamily="monospace"
                >
                  {Math.round(pt.p * 100)}%
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between mt-1">
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[0].ts.split("T")[0]}
        </span>
        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
          {points[points.length - 1].ts.split("T")[0]}
        </span>
      </div>
    </div>
  );
}

function fmtContrib(s: number): string {
  const pp = Math.abs(s * 100).toFixed(1);
  return s > 0 ? `+${pp} pp` : s < 0 ? `\u2212${pp} pp` : `${pp} pp`;
}

// ExpandableSection component for Level 2 (collapsed by default)
function ExpandableSection({
  title,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div style={{ borderBottom: `1px solid ${T.border}` }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 0",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: T.text,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
          {badge}
        </div>
        <span
          style={{
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 200ms ease-out",
            display: "inline-block",
          }}
        >
          ▾
        </span>
      </button>
      <div
        style={{
          overflow: 'hidden',
          transition: 'max-height 200ms ease-out, opacity 200ms ease-out',
          maxHeight: open ? '5000px' : 0,
          opacity: open ? 1 : 0,
          paddingBottom: open ? 20 : 0,
        }}
      >
        {children}
      </div>
    </div>
  );
}

function RegulatoryPanel({ cal }: { cal: Calibration }) {
  if (!cal.regulatoryStatus || cal.regulatoryStatus === "NOT_EVALUATED") {
    return null;
  }

  return (
    <div
      className="rounded-lg"
      style={{
        padding: 16,
        background: T.surface,
        border: `1px solid ${cal.regulatoryStatus === "NON_COMPLIANT" ? T.hardStopBorder : cal.regulatoryStatus === "REQUIRES_REVIEW" ? T.amber + "66" : T.green + "44"}`,
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Globe size={16} color={T.accent} />
        <span className="font-bold" style={{ fontSize: FS.md, color: T.text }}>DoD Compliance Assessment</span>
        {cal.sensitivityContext && cal.sensitivityContext !== "COMMERCIAL" && (() => {
          const sensitivity = SENSITIVITY_META[parseSensitivity(cal.sensitivityContext)];
          return (
            <span
              className="rounded px-2 py-0.5 font-semibold"
              style={{ fontSize: FS.sm, background: sensitivity.bg, color: sensitivity.color, border: `1px solid ${sensitivity.tagColor}44` }}
            >
              {sensitivity.label}
            </span>
          );
        })()}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Regulatory Status</div>
          <div className="font-bold" style={{
            fontSize: FS.sm,
            color: cal.regulatoryStatus === "COMPLIANT" ? T.green
              : cal.regulatoryStatus === "NON_COMPLIANT" ? T.red
                : T.amber,
          }}>
            {cal.regulatoryStatus.replace(/_/g, " ")}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>Recommendation</div>
          <div className="font-bold" style={{
            fontSize: FS.sm,
            color: cal.recommendation?.includes("APPROVED") ? T.green
              : cal.recommendation?.includes("DO_NOT") ? T.red
                : T.amber,
          }}>
            {formatRecommendationLabel(cal.tier)}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Eligible</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodEligible ? T.green : T.red }}>
            {cal.dodEligible ? "YES" : "NO"}
          </div>
        </div>
        <div className="rounded p-2" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 2 }}>DoD Qualified</div>
          <div className="font-bold" style={{ fontSize: FS.sm, color: cal.dodQualified ? T.green : T.red }}>
            {cal.dodQualified ? "YES" : "NO"}
          </div>
        </div>
      </div>

      {cal.regulatoryFindings && cal.regulatoryFindings.length > 0 && (
        <div className="mt-3" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Regulatory Gate Findings
          </div>
          {(cal.regulatoryFindings as Array<Record<string, unknown>>).map((finding, i) => (
            <div
              key={i}
              className="flex gap-2 mb-2 rounded p-2"
              style={{
                background: String(finding.status) === "FAIL" ? T.redBg : T.amberBg,
                border: `1px solid ${String(finding.status) === "FAIL" ? T.red + "33" : T.amber + "33"}`,
              }}
            >
              <div className="font-bold shrink-0" style={{
                fontSize: FS.sm,
                color: String(finding.status) === "FAIL" ? T.red : T.amber,
                minWidth: 40,
              }}>
                {String(finding.status)}
              </div>
              <div>
                <div className="font-semibold" style={{ fontSize: FS.sm, color: T.text }}>{String(finding.name)}</div>
                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 1 }}>{String(finding.explanation)}</div>
                {finding.remediation ? (
                  <div style={{ fontSize: FS.sm, color: T.amber, marginTop: 3 }}>Remediation: {String(finding.remediation)}</div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}

      {cal.modelVersion && (
        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, textAlign: "right" }}>
          Engine: {cal.modelVersion}
        </div>
      )}
    </div>
  );
}

export function CaseDetail({ c, onBack, onRescore, onDossier, onCaseRefresh, globalLane }: CaseDetailProps) {
  const cal = c.cal;
  const user = getUser();
  const isReadOnly = user?.role === "reviewer" || user?.role === "auditor";

  const [rescoring, setRescoring] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [loadingEnrichment, setLoadingEnrichment] = useState(true);
  const [enrichment, setEnrichment] = useState<EnrichmentReport | null>(null);
  const [showStream, setShowStream] = useState(false);
  const [showAI, setShowAI] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [showSourceStatus, setShowSourceStatus] = useState(false);
  const [analystView, setAnalystView] = useState<AnalystView>("decision");
  const [authorityLaneSelection, setAuthorityLaneSelection] = useState<{ caseId: string; lane: WorkflowLane } | null>(null);
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>("model");
  const [pendingEvidenceTab, setPendingEvidenceTab] = useState<EvidenceTab | null>(null);
  const [graphData, setGraphData] = useState<CaseGraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphDepth, setGraphDepth] = useState<GraphDepth>(3);
  const [networkRisk, setNetworkRisk] = useState<NetworkRiskResult | null>(null);
  const [storyline, setStoryline] = useState<RiskStorylineType | null>(null);
  const [exportAuthorization, setExportAuthorization] = useState<ExportAuthorizationCaseInput | null>(null);
  const [exportAuthorizationGuidance, setExportAuthorizationGuidance] = useState<ExportAuthorizationGuidance | null>(null);
  const [latestFociArtifact, setLatestFociArtifact] = useState<FociArtifactRecord | null>(null);
  const [fociArtifacts, setFociArtifacts] = useState<FociArtifactRecord[]>([]);
  const [uploadingFociArtifact, setUploadingFociArtifact] = useState(false);
  const [latestSprsImport, setLatestSprsImport] = useState<SprsImportRecord | null>(null);
  const [sprsImports, setSprsImports] = useState<SprsImportRecord[]>([]);
  const [uploadingSprsImport, setUploadingSprsImport] = useState(false);
  const [latestOscalArtifact, setLatestOscalArtifact] = useState<OscalArtifactRecord | null>(null);
  const [oscalArtifacts, setOscalArtifacts] = useState<OscalArtifactRecord[]>([]);
  const [uploadingOscalArtifact, setUploadingOscalArtifact] = useState(false);
  const [latestNvdOverlay, setLatestNvdOverlay] = useState<NvdOverlayRecord | null>(null);
  const [nvdOverlays, setNvdOverlays] = useState<NvdOverlayRecord[]>([]);
  const [runningNvdOverlay, setRunningNvdOverlay] = useState(false);
  const [nvdProductTermsInput, setNvdProductTermsInput] = useState("");
  const [cyberRiskScore, setCyberRiskScore] = useState<CyberRiskScore | null>(null);
  const [loadingCyberScore, setLoadingCyberScore] = useState(false);
  const [exportArtifacts, setExportArtifacts] = useState<ExportArtifactRecord[]>([]);
  const [personScreeningName, setPersonScreeningName] = useState("");
  const [personScreeningNationalities, setPersonScreeningNationalities] = useState("");
  const [personScreeningEmployer, setPersonScreeningEmployer] = useState("");
  const [personScreeningResult, setPersonScreeningResult] = useState<Record<string, unknown> | null>(null);
  const [personScreeningHistory, setPersonScreeningHistory] = useState<Array<Record<string, unknown>>>([]);
  const [screeningPerson, setScreeningPerson] = useState(false);
  const [txAuth, setTxAuth] = useState<TransactionAuthorizationResult | null>(null);
  const [txAuthLoading, setTxAuthLoading] = useState(false);
  const [batchScreeningFile, setBatchScreeningFile] = useState<File | null>(null);
  const [batchScreeningResults, setBatchScreeningResults] = useState<Array<Record<string, unknown>>>([]);
  const [screeningBatch, setScreeningBatch] = useState(false);
  const [batchScreeningError, setBatchScreeningError] = useState<string | null>(null);
  const [workflowControlSummary, setWorkflowControlSummary] = useState<WorkflowControlSummary | null>(null);
  const [supplierPassport, setSupplierPassport] = useState<SupplierPassport | null>(null);
  const [uploadingExportArtifact, setUploadingExportArtifact] = useState(false);
  const [monitorStatus, setMonitorStatus] = useState<CaseMonitorStatus | null>(null);
  const [monitoringHistory, setMonitoringHistory] = useState<CaseMonitoringHistory | null>(null);
  const [monitoringHistoryLoading, setMonitoringHistoryLoading] = useState(false);
  const [showMonitorHistory, setShowMonitorHistory] = useState(false);
  const [aiBriefStatus, setAiBriefStatus] = useState<AIAnalysisStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const evidenceRef = useRef<HTMLDivElement | null>(null);
  const actionPanelRef = useRef<HTMLDivElement | null>(null);
  const authorityInputsRef = useRef<HTMLDivElement | null>(null);
  const sourceStatusRef = useRef<HTMLDivElement | null>(null);
  const monitorHistoryRef = useRef<HTMLDivElement | null>(null);
  const moreActionsRef = useRef<HTMLDivElement | null>(null);
  const fociInputRef = useRef<HTMLInputElement | null>(null);
  const sprsInputRef = useRef<HTMLInputElement | null>(null);
  const oscalInputRef = useRef<HTMLInputElement | null>(null);
  const exportArtifactInputRef = useRef<HTMLInputElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const showFociPanel = c.profile === "defense_acquisition" || fociArtifacts.length > 0 || !!latestFociArtifact;
  const showSprsPanel = c.profile === "defense_acquisition" || sprsImports.length > 0 || !!latestSprsImport;
  const showOscalPanel = c.profile === "defense_acquisition" || oscalArtifacts.length > 0 || !!latestOscalArtifact;
  const showNvdPanel = c.profile === "defense_acquisition" || nvdOverlays.length > 0 || !!latestNvdOverlay;
  const graphProvenanceSummary = useMemo(() => {
    if (!graphData || graphData.relationships.length === 0) return null;

    const entitiesById = new Map(graphData.entities.map((entity) => [entity.id, entity]));
    const sourceCounts = new Map<string, number>();
    let corroboratedCount = 0;
    let controlPathCount = 0;

    for (const relationship of graphData.relationships) {
      const sources = relationship.data_sources?.length
        ? relationship.data_sources
        : relationship.data_source
          ? [relationship.data_source]
          : [];
      const corroborationCount = relationship.corroboration_count ?? sources.length ?? 1;
      if (corroborationCount > 1) corroboratedCount += 1;
      if (CONTROL_PATH_RELATIONSHIPS.has(relationship.rel_type)) controlPathCount += 1;
      for (const source of sources) {
        sourceCounts.set(source, (sourceCounts.get(source) ?? 0) + 1);
      }
    }

    const topSources = Array.from(sourceCounts.entries())
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, 4)
      .map(([source, count]) => ({
        source,
        label: connectorDisplayName(source),
        count,
      }));

    const highlights = [...graphData.relationships]
      .sort((left, right) => {
        const priorityDelta = graphRelationshipPriority(right) - graphRelationshipPriority(left);
        if (priorityDelta !== 0) return priorityDelta;
        return (right.confidence ?? 0) - (left.confidence ?? 0);
      })
      .slice(0, 3)
      .map((relationship) => {
        const source = entitiesById.get(relationship.source_entity_id);
        const target = entitiesById.get(relationship.target_entity_id);
        const sources = relationship.data_sources?.length
          ? relationship.data_sources
          : relationship.data_source
            ? [relationship.data_source]
            : [];
        return {
          id: String(relationship.id ?? `${relationship.source_entity_id}:${relationship.rel_type}:${relationship.target_entity_id}`),
          sourceLabel: source?.canonical_name || relationship.source_entity_id,
          targetLabel: target?.canonical_name || relationship.target_entity_id,
          relLabel: formatRelationshipLabel(relationship.rel_type),
          corroborationCount: relationship.corroboration_count ?? sources.length ?? 1,
          sourceLabels: sources.slice(0, 3).map((sourceName) => connectorDisplayName(sourceName)),
          evidenceSummary: relationship.evidence_summary || relationship.evidence || "",
          firstSeenAt: formatGraphTimestamp(relationship.first_seen_at || relationship.created_at),
          lastSeenAt: formatGraphTimestamp(relationship.last_seen_at || relationship.created_at),
        };
      });

    return {
      relationshipCount: graphData.relationships.length,
      corroboratedCount,
      controlPathCount,
      sourceCount: sourceCounts.size,
      topSources,
      highlights,
    };
  }, [graphData]);
  const supplierPassportTone = useMemo(
    () => passportPostureTone(supplierPassport?.posture),
    [supplierPassport?.posture],
  );
  const supplierPassportOfficialCorroboration = useMemo(
    () => supplierPassport?.identity?.official_corroboration ?? null,
    [supplierPassport],
  );
  const supplierPassportOfficialTone = useMemo(
    () => officialCorroborationTone(supplierPassportOfficialCorroboration),
    [supplierPassportOfficialCorroboration],
  );
  const supplierPassportOfficialIdentifiers = useMemo(() => {
    const official = supplierPassportOfficialCorroboration;
    const primary = official?.core_official_identifiers_verified?.length
      ? official.core_official_identifiers_verified
      : official?.official_identifiers_verified ?? [];
    return primary.slice(0, 4);
  }, [supplierPassportOfficialCorroboration]);
  const supplierPassportPublicCaptureFields = useMemo(
    () => (supplierPassportOfficialCorroboration?.public_capture_fields ?? []).slice(0, 3),
    [supplierPassportOfficialCorroboration],
  );
  const supplierPassportBlockedOfficialConnectors = useMemo(
    () => (supplierPassportOfficialCorroboration?.blocked_connectors ?? []).slice(0, 3),
    [supplierPassportOfficialCorroboration],
  );
  const supplierPassportCountryHints = useMemo(
    () => (supplierPassportOfficialCorroboration?.country_hints ?? []).slice(0, 4),
    [supplierPassportOfficialCorroboration],
  );
  const supplierPassportIdentityEntries = useMemo(() => {
    const statuses = supplierPassport?.identity.identifier_status ?? {};
    const orderedKeys = ["cage", "uei", "lei", "cik", "website"];
    const seen = new Set<string>();
    const rows = [
      ...orderedKeys.filter((key) => key in statuses),
      ...Object.keys(statuses).filter((key) => !orderedKeys.includes(key)),
    ]
      .filter((key) => {
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((key) => {
        const status = statuses[key] ?? {};
        return [key, status] as const;
      });
    return rows.slice(0, 5);
  }, [supplierPassport]);
  const supplierPassportControlPaths = useMemo(
    () => (supplierPassport?.graph.control_paths ?? []).slice(0, 3),
    [supplierPassport],
  );
  const supplierPassportWorkflowLabel = useMemo(
    () => supplierPassportControlField(supplierPassport?.ownership.workflow_control, "label"),
    [supplierPassport],
  );
  const supplierPassportWorkflowBasis = useMemo(
    () => supplierPassportControlField(supplierPassport?.ownership.workflow_control, "review_basis"),
    [supplierPassport],
  );
  const supplierPassportWorkflowOwner = useMemo(
    () => supplierPassportControlField(supplierPassport?.ownership.workflow_control, "action_owner"),
    [supplierPassport],
  );
  const supplierPassportTribunalViews = useMemo(
    () => supplierPassport?.tribunal?.views ?? [],
    [supplierPassport],
  );

  const refreshCaseContext = useCallback(async () => {
    const [detail, passport] = await Promise.all([
      fetchCase(c.id) as Promise<ApiCase>,
      fetchSupplierPassport(c.id).catch(() => null),
    ]);
    setStoryline(detail.storyline ?? null);
    setExportAuthorization(detail.export_authorization ?? null);
    setExportAuthorizationGuidance(detail.export_authorization_guidance ?? null);
    setLatestFociArtifact(detail.latest_foci_artifact ?? null);
    setLatestSprsImport(detail.latest_sprs_import ?? null);
    setLatestOscalArtifact(detail.latest_oscal_artifact ?? null);
    setLatestNvdOverlay(detail.latest_nvd_overlay ?? null);
    setWorkflowControlSummary(detail.workflow_control_summary ?? null);
    setSupplierPassport(passport);
  }, [c.id]);

  const refreshAiBriefStatus = useCallback(async () => {
    try {
      const status = await fetchAIAnalysisStatus(c.id);
      setAiBriefStatus(status);
    } catch {
      setAiBriefStatus(null);
    }
  }, [c.id]);

  const refreshMonitoringHistory = useCallback(async () => {
    setMonitoringHistoryLoading(true);
    try {
      const history = await fetchCaseMonitoringHistory(c.id, 10);
      setMonitoringHistory(history);
    } catch {
      setMonitoringHistory(null);
    } finally {
      setMonitoringHistoryLoading(false);
    }
  }, [c.id]);

  useEffect(() => {
    let cancelled = false;
    setStoryline(null);
    setExportAuthorization(null);
    setExportAuthorizationGuidance(null);
    setLatestFociArtifact(null);
    setFociArtifacts([]);
    setLatestSprsImport(null);
    setSprsImports([]);
    setLatestOscalArtifact(null);
    setOscalArtifacts([]);
    setLatestNvdOverlay(null);
    setNvdOverlays([]);
    setNvdProductTermsInput("");
    setExportArtifacts([]);
    setWorkflowControlSummary(null);
    setSupplierPassport(null);
    setMonitorStatus(null);
    setMonitoringHistory(null);
    setShowMonitorHistory(false);
    setAiBriefStatus(null);
    Promise.all([
      fetchCase(c.id).catch(() => null),
      fetchSupplierPassport(c.id).catch(() => null),
    ])
      .then(([detail, passport]) => {
        if (!cancelled) {
          if (detail) {
            const typed = detail as ApiCase;
            setStoryline(typed.storyline ?? null);
            setExportAuthorization(typed.export_authorization ?? null);
            setExportAuthorizationGuidance(typed.export_authorization_guidance ?? null);
            setLatestFociArtifact(typed.latest_foci_artifact ?? null);
            setLatestSprsImport(typed.latest_sprs_import ?? null);
            setLatestOscalArtifact(typed.latest_oscal_artifact ?? null);
            setLatestNvdOverlay(typed.latest_nvd_overlay ?? null);
            setWorkflowControlSummary(typed.workflow_control_summary ?? null);
          }
          setSupplierPassport(passport);
        }
      })
      .catch(() => {});
    refreshAiBriefStatus().catch(() => {});
    refreshMonitoringHistory().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [c.id, refreshAiBriefStatus, refreshMonitoringHistory]);

  useEffect(() => {
    let cancelled = false;
    if (!showFociPanel) {
      setFociArtifacts([]);
      return () => {
        cancelled = true;
      };
    }
    listFociArtifacts(c.id)
      .then((artifacts) => {
        if (!cancelled) {
          setFociArtifacts(artifacts);
          setLatestFociArtifact((current) => current ?? artifacts[0] ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFociArtifacts([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [c.id, showFociPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showSprsPanel) {
      setSprsImports([]);
      return () => {
        cancelled = true;
      };
    }
    listSprsImports(c.id)
      .then((imports) => {
        if (!cancelled) {
          setSprsImports(imports);
          setLatestSprsImport((current) => current ?? imports[0] ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSprsImports([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [c.id, showSprsPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showOscalPanel) {
      setOscalArtifacts([]);
      return () => {
        cancelled = true;
      };
    }
    listOscalArtifacts(c.id)
      .then((artifacts) => {
        if (!cancelled) {
          setOscalArtifacts(artifacts);
          setLatestOscalArtifact((current) => current ?? artifacts[0] ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOscalArtifacts([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [c.id, showOscalPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!showNvdPanel) {
      setNvdOverlays([]);
      return () => {
        cancelled = true;
      };
    }
    listNvdOverlays(c.id)
      .then((overlays) => {
        if (!cancelled) {
          setNvdOverlays(overlays);
          setLatestNvdOverlay((current) => current ?? overlays[0] ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setNvdOverlays([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [c.id, showNvdPanel]);

  useEffect(() => {
    let cancelled = false;
    if (!exportAuthorization) {
      setExportArtifacts([]);
      return () => {
        cancelled = true;
      };
    }
    listExportArtifacts(c.id)
      .then((artifacts) => {
        if (!cancelled) {
          setExportArtifacts(artifacts);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExportArtifacts([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [c.id, exportAuthorization]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (sourceStatusRef.current && !sourceStatusRef.current.contains(event.target as Node)) {
        setShowSourceStatus(false);
      }
      if (monitorHistoryRef.current && !monitorHistoryRef.current.contains(event.target as Node)) {
        setShowMonitorHistory(false);
      }
      if (moreActionsRef.current && !moreActionsRef.current.contains(event.target as Node)) {
        setShowMoreActions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    // Cancel any previous request if a new case is selected
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create new AbortController for this request
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    setLoadingEnrichment(true);
    fetchEnrichment(c.id).then((report) => {
      // Only update state if this request wasn't aborted
      if (!abortController.signal.aborted) {
        if (report) {
          setEnrichment(report);
          if (!pendingEvidenceTab) {
            setEvidenceTab(defaultEvidenceTab(report));
          }
        }
        setLoadingEnrichment(false);
      }
    }).catch((err) => {
      // Ignore abort errors
      if (err?.name !== 'AbortError' && !abortController.signal.aborted) {
        setLoadingEnrichment(false);
      }
    });

    return () => {
      abortController.abort();
    };
  }, [c.id, pendingEvidenceTab]);

  // Fetch network risk data
  useEffect(() => {
    fetchCaseNetworkRisk(c.id)
      .then((data) => { if (data && data.network_risk_score !== undefined) setNetworkRisk(data); })
      .catch(() => {});
  }, [c.id]);

  const loadGraphData = useCallback(async (depth: GraphDepth = graphDepth) => {
    if (graphLoading) return;
    setGraphLoading(true);
    try {
      const data = await fetchCaseGraph(c.id, depth);
      if (data.entities && data.relationships) {
        setGraphData(data);
      }
    } finally {
      setGraphLoading(false);
    }
  }, [c.id, graphDepth, graphLoading]);

  const refreshDerivedCaseData = useCallback(async ({
    enrichmentReport,
    reloadGraph = false,
  }: {
    enrichmentReport?: EnrichmentReport | null;
    reloadGraph?: boolean;
  } = {}) => {
    const [detail, passport, latestEnrichment, latestNetworkRisk] = await Promise.all([
      fetchCase(c.id).catch(() => null),
      fetchSupplierPassport(c.id).catch(() => null),
      enrichmentReport === undefined ? fetchEnrichment(c.id).catch(() => null) : Promise.resolve(enrichmentReport),
      fetchCaseNetworkRisk(c.id).catch(() => null),
    ]);

    if (detail) {
      const typed = detail as ApiCase;
      setStoryline(typed.storyline ?? null);
      setExportAuthorization(typed.export_authorization ?? null);
      setExportAuthorizationGuidance(typed.export_authorization_guidance ?? null);
      setLatestFociArtifact(typed.latest_foci_artifact ?? null);
      setLatestSprsImport(typed.latest_sprs_import ?? null);
      setLatestOscalArtifact(typed.latest_oscal_artifact ?? null);
      setLatestNvdOverlay(typed.latest_nvd_overlay ?? null);
      setWorkflowControlSummary(typed.workflow_control_summary ?? null);
    }
    setSupplierPassport(passport);
    setEnrichment(latestEnrichment ?? null);
    if (latestNetworkRisk && latestNetworkRisk.network_risk_score !== undefined) {
      setNetworkRisk(latestNetworkRisk);
    }
    if (reloadGraph && latestEnrichment) {
      await loadGraphData(graphDepth);
    }
  }, [c.id, graphDepth, loadGraphData]);

  const handleFociArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadingFociArtifact(true);
    setError(null);
    try {
      const artifact = await uploadFociArtifact(c.id, {
        file,
        artifactType: inferFociArtifactType(file.name),
      });
      setFociArtifacts((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestFociArtifact(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload FOCI artifact");
    } finally {
      setUploadingFociArtifact(false);
      if (event.target) {
        event.target.value = "";
      }
    }
  }, [c.id]);

  const handleExportArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !exportAuthorization) return;

    const nextArtifactType: ExportArtifactType =
      exportAuthorizationGuidance?.classification_analysis.known
        ? "export_license_history"
        : "export_classification_memo";

    setUploadingExportArtifact(true);
    setError(null);
    try {
      const artifact = await uploadExportArtifact(c.id, {
        file,
        artifactType: nextArtifactType,
        declaredClassification: exportAuthorization.classification_guess || "",
        declaredJurisdiction: exportAuthorization.jurisdiction_guess || "",
      });
      setExportArtifacts((current) => [artifact, ...current]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload export artifact");
    } finally {
      setUploadingExportArtifact(false);
      if (event.target) {
        event.target.value = "";
      }
    }
  }, [c.id, exportAuthorization, exportAuthorizationGuidance]);

  const handleSprsImportSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadingSprsImport(true);
    setError(null);
    try {
      const artifact = await uploadSprsImport(c.id, { file });
      setSprsImports((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestSprsImport(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload SPRS export");
    } finally {
      setUploadingSprsImport(false);
      if (event.target) {
        event.target.value = "";
      }
    }
  }, [c.id]);

  const handleOscalArtifactSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadingOscalArtifact(true);
    setError(null);
    try {
      const artifact = await uploadOscalArtifact(c.id, { file });
      setOscalArtifacts((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestOscalArtifact(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to upload OSCAL artifact");
    } finally {
      setUploadingOscalArtifact(false);
      if (event.target) {
        event.target.value = "";
      }
    }
  }, [c.id]);

  const handleRunNvdOverlay = useCallback(async () => {
    const productTerms = splitProductTermsInput(nvdProductTermsInput);
    if (productTerms.length === 0) {
      setError("Add at least one supplier product or software reference for the NVD overlay.");
      return;
    }

    setRunningNvdOverlay(true);
    setError(null);
    try {
      const artifact = await runNvdOverlay(c.id, { productTerms });
      setNvdOverlays((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)]);
      setLatestNvdOverlay(artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run NVD overlay");
    } finally {
      setRunningNvdOverlay(false);
    }
  }, [c.id, nvdProductTermsInput]);

  const handleScreenPerson = useCallback(async () => {
    if (!personScreeningName.trim()) {
      setError("Enter a person name for screening.");
      return;
    }

    setScreeningPerson(true);
    setError(null);
    try {
      const result = await screenPerson({
        name: personScreeningName,
        nationalities: personScreeningNationalities
          .split(",")
          .map((n) => n.trim())
          .filter((n) => n.length > 0),
        employer: personScreeningEmployer || undefined,
        case_id: c.id,
      });
      setPersonScreeningResult(result);

      setPersonScreeningHistory((current) => [
        { ...result, screened_at: String(result.created_at || new Date().toISOString()) },
        ...current,
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to screen person");
      setPersonScreeningResult(null);
    } finally {
      setScreeningPerson(false);
    }
  }, [c.id, personScreeningEmployer, personScreeningName, personScreeningNationalities]);

  const handleBatchScreenCsv = useCallback(async () => {
    if (!batchScreeningFile) {
      setError("Select a CSV file for batch screening.");
      return;
    }

    setScreeningBatch(true);
    setBatchScreeningError(null);
    setBatchScreeningResults([]);
    setError(null);
    try {
      const data = await screenBatchCsv(c.id, batchScreeningFile);
      const screenings = Array.isArray(data.screenings) ? data.screenings : [];
      setBatchScreeningResults(screenings);

      setPersonScreeningHistory((current) => [
        ...screenings.map((s: PersonScreeningResult) => ({
          ...s,
          screened_at: String(s.created_at || new Date().toISOString()),
        })),
        ...current,
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Batch screening failed";
      setBatchScreeningError(msg);
      setError(msg);
    } finally {
      setScreeningBatch(false);
    }
  }, [batchScreeningFile, c.id]);

  const handleDownloadCsvTemplate = useCallback(() => {
    const csvContent = "name,nationalities,employer\nJohn Doe,\"CN,HK\",Huawei Technologies\nJane Smith,RU,Rosatom\nAli Hassan,IR,\nMaria Garcia,MX,Pemex\n";
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "person_screening_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  // Load latest transaction authorization for this case
  const loadTxAuth = useCallback(async () => {
    try {
      const data = await listTransactionAuthorizations(c.id, undefined, 1);
      const latest = data.authorizations?.[0] as { id?: string } | undefined;
      if (!latest?.id) {
        setTxAuth(null);
        return;
      }
      const detail = await fetchTransactionAuthorization(latest.id);
      setTxAuth(detail as unknown as TransactionAuthorizationResult);
    } catch (err) {
      console.error("Failed to load transaction authorization:", err);
    }
  }, [c.id]);

  // Run a full transaction authorization pipeline
  const handleRunTxAuth = useCallback(async () => {
    if (!exportAuthorization) return;
    setTxAuthLoading(true);
    try {
      const nats = exportAuthorization.foreign_person_nationalities;
      const persons = nats && nats.length > 0
        ? [{
            name: exportAuthorization.recipient_name || "Unspecified person",
            nationalities: nats,
            employer: exportAuthorization.recipient_name || "",
          }]
        : [];

      const result = await runTransactionAuthorization({
        jurisdiction_guess: exportAuthorization.jurisdiction_guess || "unknown",
        request_type: exportAuthorization.request_type,
        classification_guess: exportAuthorization.classification_guess || "unknown",
        destination_country: exportAuthorization.destination_country || "",
        destination_company: exportAuthorization.recipient_name || "",
        item_or_data_summary: exportAuthorization.item_or_data_summary || "",
        end_use_summary: exportAuthorization.end_use_summary || "",
        access_context: exportAuthorization.access_context || "",
        persons,
        case_id: c.id,
        requested_by: getUser()?.email || "ui",
      });
      setTxAuth(result as unknown as TransactionAuthorizationResult);
    } catch (err) {
      console.error("Transaction authorization failed:", err);
    } finally {
      setTxAuthLoading(false);
    }
  }, [c.id, exportAuthorization]);

  const loadPersonScreeningHistory = useCallback(async () => {
    try {
      const data = await fetchCaseScreenings(c.id);
      const screenings = Array.isArray(data.screenings) ? data.screenings : [];
      setPersonScreeningHistory(
        screenings.map((item) => ({
          ...item,
          screened_at: String(item.screened_at || item.created_at || ""),
        })),
      );
    } catch (err) {
      console.error("Failed to load screening history:", err);
    }
  }, [c.id]);

  useEffect(() => {
    if (!monitorStatus?.sweep_id) return;
    if (!["queued", "running"].includes(monitorStatus.status)) return;

    let cancelled = false;
    let timer = 0;

    const poll = async () => {
      try {
        const next = await fetchCaseMonitorStatus(c.id, monitorStatus.sweep_id);
        if (cancelled) return;
        setMonitorStatus(next);
        if (next.status === "queued" || next.status === "running") {
          timer = window.setTimeout(poll, 2000);
          return;
        }
        if (next.status === "completed") {
          await Promise.all([
            refreshDerivedCaseData({ reloadGraph: evidenceTab === "graph" || !!graphData }),
            refreshAiBriefStatus(),
            refreshMonitoringHistory(),
            onCaseRefresh ? onCaseRefresh(c.id) : Promise.resolve(),
          ]);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Monitoring status check failed");
          setMonitorStatus((current) => current ? { ...current, status: "failed" } : current);
        }
      }
    };

    timer = window.setTimeout(poll, 1500);
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [c.id, evidenceTab, graphData, monitorStatus?.status, monitorStatus?.sweep_id, onCaseRefresh, refreshAiBriefStatus, refreshDerivedCaseData, refreshMonitoringHistory]);

  useEffect(() => {
    if (!aiBriefStatus) return;
    if (!["pending", "running"].includes(aiBriefStatus.status)) return;

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await fetchAIAnalysisStatus(c.id);
        if (!cancelled) {
          setAiBriefStatus(next);
        }
      } catch {
        if (!cancelled) {
          setAiBriefStatus(null);
        }
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [aiBriefStatus, c.id]);

  const handleEnrich = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot run enrichment on a case.");
      return;
    }
    setEnriching(true);
    setShowStream(true);
    setShowAI(false);
    setShowSourceStatus(false);
    setError(null);
  };

  const handleStreamComplete = async () => {
    try {
      const fullReport = await fetchEnrichment(c.id);
      setEnrichment(fullReport);
      const requestedTab = pendingEvidenceTab ?? defaultEvidenceTab(fullReport);
      setEvidenceTab(requestedTab);
      const shouldReloadGraph = requestedTab === "graph" || evidenceTab === "graph" || !!graphData;
      setPendingEvidenceTab(null);
      await Promise.all([
        refreshDerivedCaseData({ enrichmentReport: fullReport, reloadGraph: shouldReloadGraph }),
        refreshAiBriefStatus(),
        onCaseRefresh ? onCaseRefresh(c.id) : Promise.resolve(),
      ]);
      setShowStream(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load enrichment report");
    } finally {
      setEnriching(false);
    }
  };

  const handleRescore = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot re-score a case.");
      return;
    }
    if (!onRescore) return;
    setRescoring(true);
    setError(null);
    try {
      await onRescore(c.id);
      await Promise.all([refreshCaseContext(), refreshAiBriefStatus()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-score failed");
    } finally {
      setRescoring(false);
    }
  };

  const handleDossier = async () => {
    setGenerating(true);
    setError(null);
    try {
      const data = await requestDossier(c.id);
      const url = data.download_url || `/api/dossiers/dossier-${c.id}.html`;
      const protectedUrl = await buildProtectedUrl(url);
      window.open(protectedUrl, "_blank");
      void refreshAiBriefStatus();
    } catch (e) {
      // Fallback to client-side dossier
      if (onDossier) {
        try {
          await onDossier(c.id);
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : "Dossier generation failed");
        }
      } else {
        setError(e instanceof Error ? e.message : "Dossier generation failed");
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleMonitor = async () => {
    if (isReadOnly) {
      setError("Read-only users cannot run monitoring checks.");
      return;
    }
    setError(null);
    try {
      const queued = await runCaseMonitor(c.id);
      setMonitorStatus(queued);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Monitoring check failed");
    }
  };

  const hasApi = !!onRescore;
  const sortedCt = useMemo(
    () => (cal ? [...cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s)) : []),
    [cal],
  );
  const riskBand = cal ? tierBand(parseTier(cal.tier)) : "clear";
  const whyItems = useMemo(() => {
    if (!cal) return [];
    if (cal.stops.length > 0) {
      return cal.stops.slice(0, 3).map((stop) => stop.t);
    }

    const findings = cal.finds.slice(0, 3);
    if (findings.length > 0) return findings;

    const flags = cal.flags.slice(0, 3).map((flag) => `${flag.t}: ${flag.x}`);
    if (flags.length > 0) return flags;

    return sortedCt.slice(0, 3).map((factor) => factor.d);
  }, [cal, sortedCt]);

  const decisionHeadline = (() => {
    if (!cal) return "Assessment in progress";
    if (cal.stops.length > 0) return "Do not proceed";
    if (riskBand === "elevated") return "Enhanced review required";
    if (riskBand === "conditional") return "Conditional review recommended";
    return "Suitable for standard processing";
  })();

  const decisionSummary = (() => {
    if (!cal) return "Helios is assembling the evidence and recommendation.";
    if (cal.stops.length > 0) {
      return cal.stops[0]?.x || "A hard-stop condition prevents procurement until resolved.";
    }
    if (riskBand === "elevated") {
      return "The evidence warrants enhanced diligence before approval.";
    }
    if (riskBand === "conditional") {
      return "The vendor appears workable, but some targeted review is still warranted.";
    }
    return `${probLabel(cal.p)} with strong transparency and low immediate concern signals.`;
  })();

  const executiveSignals = useMemo(() => {
    if (!cal) return [];

    const confidencePct = Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)));
    const coveragePct = Math.round(cal.cov * 100);
    const latestMonitoringCheck = monitoringHistory?.monitoring_history?.[0] ?? null;
    const previousSnapshot = c.history && c.history.length > 0 ? c.history[c.history.length - 1] : null;
    const delta = previousSnapshot ? cal.p - previousSnapshot.p : null;
    const formattedTier = cal.tier.replaceAll("_", " ");
    const connectorsChecked = enrichment?.summary.connectors_run ?? enrichment?.summary.connectors_with_data ?? 0;

    const decisionCard = (() => {
      if (cal.stops.length > 0) {
        return {
          label: "Decision",
          value: "Blocked",
          detail: formattedTier,
          color: T.red,
          background: T.redBg,
          border: `${T.red}33`,
        };
      }
      if (riskBand === "elevated") {
        return {
          label: "Decision",
          value: "Enhanced review",
          detail: formattedTier,
          color: T.amber,
          background: `${T.amber}12`,
          border: `${T.amber}33`,
        };
      }
      if (riskBand === "conditional") {
        return {
          label: "Decision",
          value: "Conditional",
          detail: formattedTier,
          color: T.amber,
          background: `${T.amber}12`,
          border: `${T.amber}33`,
        };
      }
      return {
        label: "Decision",
        value: "Standard",
        detail: formattedTier,
        color: T.green,
        background: `${T.green}12`,
        border: `${T.green}33`,
      };
    })();

    const changeCard = (() => {
      if (latestMonitoringCheck) {
        const checkedLabel = latestMonitoringCheck.checked_at
          ? new Date(latestMonitoringCheck.checked_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
          : "Latest monitor check";
        if (latestMonitoringCheck.risk_changed) {
          return {
            label: "Change",
            value: "Tier shift",
            detail: `${formatMonitorTierLabel(latestMonitoringCheck.previous_risk)} -> ${formatMonitorTierLabel(latestMonitoringCheck.current_risk)} • ${checkedLabel}`,
            color: T.amber,
            background: `${T.amber}12`,
            border: `${T.amber}33`,
          };
        }
        if ((latestMonitoringCheck.new_findings_count ?? 0) > 0) {
          const findingsLabel = latestMonitoringCheck.new_findings_count === 1
            ? "1 new finding"
            : `${latestMonitoringCheck.new_findings_count} new findings`;
          return {
            label: "Change",
            value: "New findings",
            detail: `${findingsLabel} • ${checkedLabel}`,
            color: T.accent,
            background: `${T.accent}12`,
            border: `${T.accent}33`,
          };
        }
        return {
          label: "Change",
          value: "Stable",
          detail: `No tier shift on latest check • ${checkedLabel}`,
          color: T.green,
          background: `${T.green}12`,
          border: `${T.green}33`,
        };
      }
      if (delta == null) {
        return {
          label: "Change",
          value: "Baseline",
          detail: "First scored snapshot",
          color: T.dim,
          background: T.raised,
          border: T.border,
        };
      }
      if (Math.abs(delta) < 0.005) {
        return {
          label: "Change",
          value: "Stable",
          detail: `${Math.round(previousSnapshot!.p * 100)}% -> ${Math.round(cal.p * 100)}%`,
          color: T.dim,
          background: T.raised,
          border: T.border,
        };
      }
      const rising = delta > 0;
      return {
        label: "Change",
        value: `${rising ? "+" : "\u2212"}${Math.abs(delta * 100).toFixed(1)} pp`,
        detail: `${Math.round(previousSnapshot!.p * 100)}% -> ${Math.round(cal.p * 100)}%`,
        color: rising ? T.amber : T.green,
        background: rising ? `${T.amber}12` : `${T.green}12`,
        border: rising ? `${T.amber}33` : `${T.green}33`,
      };
    })();

    return [
      decisionCard,
      {
        label: "Confidence",
        value: `${confidencePct}%`,
        detail: "Model confidence",
        color: T.accent,
        background: `${T.accent}12`,
        border: `${T.accent}33`,
      },
      {
        label: "Coverage",
        value: `${coveragePct}%`,
        detail: connectorsChecked > 0 ? `${connectorsChecked} sources checked` : "Coverage depth",
        color: T.amber,
        background: `${T.amber}12`,
        border: `${T.amber}33`,
      },
      changeCard,
    ];
  }, [c.history, cal, enrichment, monitoringHistory, riskBand]);

  const evidenceTabs = [
    { id: "intel" as const, label: "Intel Summary", disabled: !enrichment },
    { id: "findings" as const, label: "Raw Findings", disabled: !enrichment },
    { id: "events" as const, label: "Events", disabled: !enrichment || (enrichment?.events?.length ?? 0) === 0 },
    { id: "model" as const, label: "Model Factors", disabled: !cal },
    { id: "graph" as const, label: "Entity Graph", disabled: !enrichment },
  ];

  const sourceStatuses = useMemo(() => {
    if (!enrichment) return [];
    return Object.entries(enrichment.connector_status).sort(([, a], [, b]) => {
      const aScore = a.error ? 2 : a.has_data ? 0 : 1;
      const bScore = b.error ? 2 : b.has_data ? 0 : 1;
      if (aScore !== bScore) return bScore - aScore;
      return b.elapsed_ms - a.elapsed_ms;
    });
  }, [enrichment]);

  const sourceStatusSummary = useMemo(() => {
    const totals = { green: 0, yellow: 0, red: 0 };
    for (const [, status] of sourceStatuses) {
      if (status.error) totals.red += 1;
      else if (status.has_data) totals.green += 1;
      else totals.yellow += 1;
    }
    return totals;
  }, [sourceStatuses]);
  const sourceStatusDetails = useMemo(() => {
    return sourceStatuses.map(([name, status]) => {
      const meta = CONNECTOR_META[name as keyof typeof CONNECTOR_META];
      return {
        name,
        status,
        color: sourceStatusColor(status.has_data, status.error),
        tone: sourceStatusTone(status),
        label: sourceStatusLabel(status),
        findingsSummary: sourceStatusFindingSummary(status),
        category: meta?.category || "Other",
        description: meta?.description || "Connector details unavailable",
      };
    });
  }, [sourceStatuses]);
  const sourceStatusSections = useMemo(() => {
    return {
      signal: sourceStatusDetails.filter((entry) => entry.tone === "signal"),
      clear: sourceStatusDetails.filter((entry) => entry.tone === "clear"),
      issue: sourceStatusDetails.filter((entry) => entry.tone === "issue"),
    };
  }, [sourceStatusDetails]);
  const sourceCategoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of sourceStatusDetails) {
      counts.set(entry.category, (counts.get(entry.category) ?? 0) + 1);
    }
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [sourceStatusDetails]);

  const openEvidence = (tab: EvidenceTab) => {
    if (tab !== "model" && !enrichment) {
      if (isReadOnly) {
        setError("Intel is unavailable until an analyst runs enrichment for this case.");
        return;
      }
      setPendingEvidenceTab(tab);
      setAnalystView("evidence");
      void handleEnrich();
      return;
    }
    setAnalystView(tab === "model" ? "model" : "evidence");
    setEvidenceTab(tab);
    setPendingEvidenceTab(null);

    // Load graph data on first open
    if (tab === "graph" && !graphData && !graphLoading) {
      void loadGraphData(graphDepth);
    }

    setTimeout(() => evidenceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };

  const switchGraphDepth = (depth: GraphDepth) => {
    if (depth === graphDepth) return;
    setGraphDepth(depth);
    if (evidenceTab === "graph") {
      void loadGraphData(depth);
    }
  };

  const focusAuthorityLane = useCallback((lane: WorkflowLane) => {
    const laneAvailable = lane === "counterparty"
      ? showFociPanel
      : lane === "cyber"
        ? (showSprsPanel || showOscalPanel || showNvdPanel)
        : (!!exportAuthorization || !!exportAuthorizationGuidance || exportArtifacts.length > 0);
    if (!laneAvailable) return false;
    setAuthorityLaneSelection({ caseId: c.id, lane });
    setAnalystView("decision");
    setTimeout(() => authorityInputsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    return true;
  }, [
    c.id,
    exportArtifacts.length,
    exportAuthorization,
    exportAuthorizationGuidance,
    showFociPanel,
    showNvdPanel,
    showOscalPanel,
    showSprsPanel,
  ]);

  const storylineAuthorityLane = (card: RiskStorylineCard): WorkflowLane | null => {
    for (const ref of card.source_refs) {
      const id = String(ref.id || "").toLowerCase();
      if (ref.kind === "export_guidance") return "export";
      if (ref.kind === "customer_artifact") {
        if (id.startsWith("foci_") || id.includes("ownership") || id.includes("mitigation")) return "counterparty";
        if (id.startsWith("export_") || id.includes("ccats") || id.includes("cj")) return "export";
        if (id.includes("sprs") || id.includes("oscal") || id.includes("nvd") || id.includes("cyber")) return "cyber";
      }
    }

    const narrative = `${card.title} ${card.body}`.toLowerCase();
    if (narrative.includes("authorization posture") || narrative.includes("export review") || narrative.includes("foreign-person")) return "export";
    if (narrative.includes("cmmc") || narrative.includes("poa&m") || narrative.includes("cyber") || narrative.includes("cve")) return "cyber";
    if (narrative.includes("foci") || narrative.includes("ownership") || narrative.includes("control chain") || narrative.includes("foreign ownership")) return "counterparty";
    return null;
  };

  const handleStorylineAction = (card: RiskStorylineCard) => {
    const target = card.cta_target;
    const authorityLane = storylineAuthorityLane(card);
    if (target.kind === "evidence_tab" && authorityLane && focusAuthorityLane(authorityLane)) {
      return;
    }
    if (target.kind === "action_panel") {
      setAnalystView("decision");
      setTimeout(() => actionPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 0);
      return;
    }

    if (target.kind === "deep_analysis") {
      if (target.section === "model") {
        openEvidence("model");
        return;
      }
      setAnalystView("decision");
      return;
    }

    if (target.kind === "graph_focus") {
      const requestedDepth = target.depth === 4 ? 4 : 3;
      setGraphDepth(requestedDepth);
      setAnalystView("evidence");
      setEvidenceTab("graph");
      setPendingEvidenceTab(null);
      void loadGraphData(requestedDepth);
      setTimeout(() => evidenceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
      return;
    }

    if (target.kind === "evidence_tab") {
      openEvidence(target.tab ?? "findings");
    }
  };

  const showLegacyWhyBlock = !storyline || storyline.cards.length === 0;
  const monitorVisual = monitorTone(monitorStatus?.status ?? null);
  const MonitorIcon = monitorVisual.icon;
  const aiBriefVisual = aiBriefTone(aiBriefStatus?.status ?? null);
  const AIBriefIcon = aiBriefVisual.icon;
  const monitorSummary = (() => {
    if (!monitorStatus) return null;
    if (monitorStatus.status === "completed") {
      if (monitorStatus.risk_changes && monitorStatus.risk_changes > 0) {
        return `${monitorStatus.risk_changes} change${monitorStatus.risk_changes === 1 ? "" : "s"} detected`;
      }
      return "No material change detected";
    }
    if (monitorStatus.status === "running") return "Rechecking live sources";
    if (monitorStatus.status === "queued") return "Queued in background";
    if (monitorStatus.status === "failed") return "Monitoring check failed";
    return null;
  })();
  const monitorDetail = (() => {
    if (!monitorStatus) return null;
    if (monitorStatus.status === "completed" && monitorStatus.latest_score?.tier) {
      const score = monitorStatus.latest_score.composite_score;
      return `${monitorStatus.latest_score.tier.replaceAll("_", " ")}${typeof score === "number" ? ` • ${score}/100` : ""}`;
    }
    if (monitorStatus.status === "completed" && monitorStatus.completed_at) {
      return `Completed ${new Date(monitorStatus.completed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    }
    if (monitorStatus.started_at) {
      return `Started ${new Date(monitorStatus.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    }
    if (monitorStatus.triggered_at) {
      return `Queued ${new Date(monitorStatus.triggered_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    }
    return null;
  })();
  const aiBriefSummary = (() => {
    if (!aiBriefStatus) return null;
    if (aiBriefStatus.status === "ready" || aiBriefStatus.status === "completed") return "AI brief ready";
    if (aiBriefStatus.status === "running") return "AI brief warming";
    if (aiBriefStatus.status === "pending") return "AI brief queued";
    if (aiBriefStatus.status === "failed") return "AI brief unavailable";
    if (aiBriefStatus.status === "missing") return "AI brief not warmed";
    return null;
  })();
  const aiBriefDetail = (() => {
    if (!aiBriefStatus) return null;
    if (aiBriefStatus.status === "ready" || aiBriefStatus.status === "completed") {
      if (aiBriefStatus.analysis?.created_at) {
        return `Ready for dossier and AI panel • ${new Date(aiBriefStatus.analysis.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
      }
      return "Ready for dossier and AI panel";
    }
    if (aiBriefStatus.status === "running") return "Preparing the narrative from the latest screening";
    if (aiBriefStatus.status === "pending") return "Queued behind the latest enrich or re-enrich run";
    if (aiBriefStatus.status === "failed") return "Will regenerate on dossier open if needed";
    if (aiBriefStatus.status === "missing") return enrichment ? "Older case; the brief will warm on next dossier or screening run" : "Will warm after screening completes";
    return null;
  })();
  const showAiBriefPill = !!aiBriefStatus && (aiBriefStatus.status !== "missing" || !!enrichment || generating);
  const latestMonitoringChecks = monitoringHistory?.monitoring_history ?? [];
  const monitoringHistorySummary = (() => {
    if (!monitoringHistory) return null;
    const changed = latestMonitoringChecks.filter((entry) => entry.risk_changed).length;
    const newFindings = latestMonitoringChecks.reduce((sum, entry) => sum + (entry.new_findings_count ?? 0), 0);
    return {
      runs: latestMonitoringChecks.length,
      changed,
      newFindings,
    };
  })();
  const latestFociSummary = latestFociArtifact?.structured_fields as Record<string, unknown> | undefined;
  const latestSprsSummary = latestSprsImport?.structured_fields?.summary as Record<string, unknown> | undefined;
  const latestOscalSummary = latestOscalArtifact?.structured_fields?.summary as Record<string, unknown> | undefined;
  const latestNvdSummary = latestNvdOverlay?.structured_fields?.summary as Record<string, unknown> | undefined;
  const passportCyberSummary = (supplierPassport?.cyber as Record<string, unknown> | null) ?? null;
  const passportThreatIntel = (supplierPassport?.threat_intel as Record<string, unknown> | null) ?? null;
  const showCyberLane = showSprsPanel || showOscalPanel || showNvdPanel;
  const showExportLane = !!exportAuthorization || !!exportAuthorizationGuidance || exportArtifacts.length > 0;
  const showWorkflowLanes = showFociPanel || showCyberLane || showExportLane;
  const fociForeignInterestPresent = !!latestFociSummary && (
    !!latestFociSummary.declared_foreign_owner
    || !!latestFociSummary.declared_foreign_country
    || !!latestFociSummary.contains_foreign_influence_terms
    || (typeof latestFociSummary.max_ownership_percent_mention === "number" && latestFociSummary.max_ownership_percent_mention > 0)
  );
  const fociMitigationPresent = !!latestFociSummary && (
    !!latestFociSummary.declared_mitigation_type
    || !!latestFociSummary.declared_mitigation_status
    || (Array.isArray(latestFociSummary.mitigation_tokens) && latestFociSummary.mitigation_tokens.length > 0)
  );
  const fociLaneTone = !latestFociSummary
    ? { color: T.muted, background: T.surface, border: T.border, label: "Awaiting evidence" }
    : fociForeignInterestPresent && !fociMitigationPresent
      ? { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33`, label: "Foreign interest under review" }
      : fociMitigationPresent
        ? { color: T.accent, background: `${T.accent}12`, border: `${T.accent}33`, label: "Mitigation documented" }
        : { color: T.green, background: `${T.green}12`, border: `${T.green}33`, label: "Control chain documented" };
  const fociLaneDetail = !latestFociSummary
    ? "Upload Form 328 records, ownership charts, and mitigation instruments to ground the decision."
    : fociMitigationPresent
      ? `${String(latestFociSummary.declared_mitigation_type || latestFociSummary.declared_mitigation_status || "Mitigation evidence").replaceAll("_", " ")} captured for adjudication.`
      : fociForeignInterestPresent
        ? `Foreign counterparty context points to ${String(latestFociSummary.declared_foreign_owner || latestFociSummary.declared_foreign_country || "a foreign interest")} and needs explicit adjudication.`
        : "Customer ownership and governance evidence is attached and available to the decision flow.";
  const latestSprsScore = typeof latestSprsSummary?.assessment_score === "number" ? latestSprsSummary.assessment_score : null;
  const latestCmmcLevel = latestSprsSummary?.current_cmmc_level != null ? String(latestSprsSummary.current_cmmc_level) : null;
  const latestOpenPoamItems = typeof latestOscalSummary?.open_poam_items === "number" ? latestOscalSummary.open_poam_items : null;
  const latestHighCriticalCves = typeof latestNvdSummary?.high_or_critical_cve_count === "number" ? latestNvdSummary.high_or_critical_cve_count : null;
  const cyberPressurePresent = (latestSprsSummary?.poam_active === true)
    || (typeof latestOpenPoamItems === "number" && latestOpenPoamItems > 0)
    || (typeof latestHighCriticalCves === "number" && latestHighCriticalCves > 0)
    || (typeof latestSprsScore === "number" && latestSprsScore < 90);
  const cyberLaneTone = !(latestSprsSummary || latestOscalSummary || latestNvdSummary)
    ? { color: T.muted, background: T.surface, border: T.border, label: "Awaiting evidence" }
    : cyberPressurePresent
      ? { color: T.amber, background: `${T.amber}12`, border: `${T.amber}33`, label: "Readiness gap in view" }
      : { color: T.green, background: `${T.green}12`, border: `${T.green}33`, label: "Readiness documented" };
  const cyberLaneDetail = !(latestSprsSummary || latestOscalSummary || latestNvdSummary)
    ? "Attach SPRS exports, OSCAL artifacts, SBOM or VEX evidence, and product references to ground supply chain assurance."
    : cyberPressurePresent
      ? `${typeof latestOpenPoamItems === "number" && latestOpenPoamItems > 0 ? `${latestOpenPoamItems} open POA&M items` : "Active remediation pressure"}${typeof latestHighCriticalCves === "number" && latestHighCriticalCves > 0 ? ` • ${latestHighCriticalCves} high / critical CVEs in scope` : ""}.`
      : "Customer attestation and remediation evidence is supporting the cyber readiness view.";
  const threatPressure = String(passportThreatIntel?.threat_pressure || passportCyberSummary?.threat_pressure || "").toLowerCase();
  const attackTechniqueIds = stringList(passportThreatIntel?.attack_technique_ids || passportCyberSummary?.attack_technique_ids);
  const cisaAdvisoryIds = stringList(passportThreatIntel?.cisa_advisory_ids || passportCyberSummary?.cisa_advisory_ids);
  const actorFamilies = stringList(passportThreatIntel?.attack_actor_families || passportCyberSummary?.attack_actor_families);
  const threatSectors = stringList(passportThreatIntel?.threat_sectors || passportCyberSummary?.threat_sectors);
  const openSourceRiskLevel = String(passportCyberSummary?.open_source_risk_level || "").toLowerCase();
  const openSourceAdvisoryCount = typeof passportCyberSummary?.open_source_advisory_count === "number"
    ? passportCyberSummary.open_source_advisory_count
    : 0;
  const scorecardLowRepoCount = typeof passportCyberSummary?.scorecard_low_repo_count === "number"
    ? passportCyberSummary.scorecard_low_repo_count
    : 0;
  const showThreatSignalCard = Boolean(
    threatPressure
    || attackTechniqueIds.length
    || cisaAdvisoryIds.length
    || actorFamilies.length
    || threatSectors.length
    || openSourceAdvisoryCount > 0
    || scorecardLowRepoCount > 0
  );
  const exportLaneTone = exportGuidanceTone(exportAuthorizationGuidance?.posture);
  const exportLaneLabel = exportAuthorizationGuidance?.posture_label || (exportAuthorization ? "Request captured" : "Awaiting request");
  const exportLaneDetail = exportAuthorizationGuidance?.recommended_next_step
    || exportAuthorizationGuidance?.reason_summary
    || (exportAuthorization
      ? `${exportRequestTypeLabel(exportAuthorization.request_type)} for ${exportAuthorization.destination_country || exportAuthorization.recipient_name || c.name}.`
      : "Capture an export authorization case to move this lane into decision support mode.");
  const activeLaneKey: WorkflowLane = c.workflowLane
    || (showExportLane ? "export" : showCyberLane ? "cyber" : "counterparty");
  const ActiveLaneIcon = activeLaneKey === "export" ? Lock : activeLaneKey === "cyber" ? Radar : Network;
  const activeLaneBrief = activeLaneKey === "export"
    ? {
        eyebrow: "Current workflow lane",
        title: "Export authorization",
        question: "Can this item, technical-data release, or foreign-person access request move forward under current control posture?",
        outputs: "Likely prohibited / License required / Exception path / Likely NLR / Escalate",
        evidence: "Classification memos, access-control records, customer export artifacts, and BIS or DDTC rule guidance.",
        nextAction: exportLaneDetail,
        tone: exportLaneTone,
        stats: [
          { label: "Authorization posture", value: exportLaneLabel },
          { label: "Request type", value: exportAuthorization ? exportRequestTypeLabel(exportAuthorization.request_type) : "Awaiting request" },
          { label: "Jurisdiction", value: exportAuthorization ? exportJurisdictionLabel(exportAuthorization.jurisdiction_guess) : "Needs review" },
        ],
      }
    : activeLaneKey === "cyber"
      ? {
          eyebrow: "Current workflow lane",
          title: "Supply chain assurance",
          question: "Can this supplier, product, and dependency stack be trusted with CUI-sensitive or mission-critical work given attestation, remediation, provenance, and vulnerability evidence?",
          outputs: "Ready / Qualified / Review / Blocked",
          evidence: "SPRS exports, OSCAL SSP or POA&M artifacts, SBOM or VEX evidence, and vulnerability overlays tied to the supplier and dependency stack.",
          nextAction: cyberLaneDetail,
          tone: cyberLaneTone,
          stats: [
            { label: "SPRS / CMMC", value: `${typeof latestSprsScore === "number" ? latestSprsScore : "Unknown"}${latestCmmcLevel ? ` • L${latestCmmcLevel}` : ""}` },
            { label: "Open POA&M", value: typeof latestOpenPoamItems === "number" ? String(latestOpenPoamItems) : "None captured" },
            { label: "High / critical CVEs", value: typeof latestHighCriticalCves === "number" ? String(latestHighCriticalCves) : "None captured" },
          ],
        }
      : {
          eyebrow: "Current workflow lane",
          title: "Defense counterparty trust",
          question: "Can we award, keep, or qualify this supplier given ownership, foreign-influence, and network evidence?",
          outputs: "Approved / Qualified / Review / Blocked",
          evidence: "Form 328 records, ownership charts, mitigation instruments, SAM.gov registration, SAM.gov subaward reporting, and prime or sub relationship evidence.",
          nextAction: fociLaneDetail,
          tone: fociLaneTone,
          stats: [
            { label: "FOCI posture", value: fociLaneTone.label },
            { label: "Artifacts", value: `${fociArtifacts.length}` },
            {
              label: "Foreign interest",
              value: String(
                latestFociSummary?.declared_foreign_ownership_pct
                || (typeof latestFociSummary?.max_ownership_percent_mention === "number"
                  ? `${latestFociSummary.max_ownership_percent_mention}%`
                  : latestFociSummary?.declared_foreign_country || "Not stated"),
              ),
            },
          ],
        };
  const activeControlSummary = workflowControlSummary && workflowControlSummary.lane === activeLaneKey
    ? workflowControlSummary
    : null;
  const activeControlTone = controlSummaryTone(activeControlSummary);
  const activeControlMissing = (activeControlSummary?.missing_inputs || []).slice(0, 3);
  const laneCoverageCards = [
    showFociPanel ? {
      key: "counterparty" as const,
      title: "Defense counterparty trust",
      subtitle: "FOCI / ownership adjudication",
      detail: fociLaneDetail,
      tone: fociLaneTone,
      stats: [
        { label: "Artifacts", value: `${fociArtifacts.length}` },
        {
          label: "Foreign interest",
          value: String(
            latestFociSummary?.declared_foreign_ownership_pct
            || (typeof latestFociSummary?.max_ownership_percent_mention === "number"
              ? `${latestFociSummary.max_ownership_percent_mention}%`
              : latestFociSummary?.declared_foreign_country || "Not stated"),
          ),
        },
      ],
    } : null,
    showCyberLane ? {
      key: "cyber" as const,
      title: "Supply chain assurance",
      subtitle: "CMMC / provenance / dependency posture",
      detail: cyberLaneDetail,
      tone: cyberLaneTone,
      stats: [
        { label: "SPRS / CMMC", value: `${typeof latestSprsScore === "number" ? latestSprsScore : "Unknown"}${latestCmmcLevel ? ` • L${latestCmmcLevel}` : ""}` },
        { label: "Open POA&M", value: typeof latestOpenPoamItems === "number" ? String(latestOpenPoamItems) : "None captured" },
      ],
    } : null,
    showExportLane ? {
      key: "export" as const,
      title: "Export authorization",
      subtitle: "Item / data / foreign-person review",
      detail: exportLaneDetail,
      tone: exportLaneTone,
      stats: [
        { label: "Request type", value: exportAuthorization ? exportRequestTypeLabel(exportAuthorization.request_type) : "Awaiting request" },
        { label: "Jurisdiction", value: exportAuthorization ? exportJurisdictionLabel(exportAuthorization.jurisdiction_guess) : "Needs review" },
      ],
    } : null,
  ].filter(Boolean) as Array<{
    key: WorkflowLane;
    title: string;
    subtitle: string;
    detail: string;
    tone: { color: string; background: string; border: string; label: string };
    stats: Array<{ label: string; value: string }>;
  }>;
  const authorityLaneTabs = [
    showFociPanel ? {
      key: "counterparty" as const,
      title: "Counterparty",
      subtitle: fociLaneTone.label,
      detail: "FOCI / ownership",
      tone: fociLaneTone,
    } : null,
    showCyberLane ? {
      key: "cyber" as const,
      title: "Cyber",
      subtitle: cyberLaneTone.label,
      detail: "SPRS / OSCAL / NVD",
      tone: cyberLaneTone,
    } : null,
    showExportLane ? {
      key: "export" as const,
      title: "Export",
      subtitle: exportLaneLabel,
      detail: "Authorization rules",
      tone: exportLaneTone,
    } : null,
  ].filter(Boolean) as Array<{
    key: WorkflowLane;
    title: string;
    subtitle: string;
    detail: string;
    tone: { color: string; background: string; border: string; label: string };
  }>;
  const authorityLaneKey: WorkflowLane = (() => {
    const selectedLane = authorityLaneSelection?.caseId === c.id ? authorityLaneSelection.lane : null;
    if (selectedLane && authorityLaneTabs.some((tab) => tab.key === selectedLane)) return selectedLane;
    if (globalLane && authorityLaneTabs.some((tab) => tab.key === globalLane)) return globalLane;
    if (authorityLaneTabs.some((tab) => tab.key === activeLaneKey)) return activeLaneKey;
    return authorityLaneTabs[0]?.key || activeLaneKey;
  })();
  // Auto-load person screening history and latest transaction auth when in export lane
  useEffect(() => {
    if (authorityLaneKey === "export") {
      loadPersonScreeningHistory();
      loadTxAuth();
    }
  }, [authorityLaneKey, loadPersonScreeningHistory, loadTxAuth]);

  const secondaryLaneCards = laneCoverageCards.filter((card) => card.key !== activeLaneKey);
  const operatingLaneMeta = globalLane ? WORKFLOW_LANE_META[globalLane] : null;
  const operatingModeMatchesCase = !globalLane || globalLane === activeLaneKey;
  const monitoringLaneCopy = activeLaneKey === "export"
    ? {
        title: "Authorization history",
        detail: "Recent authorization rechecks, posture drift, and what changed across live monitoring runs",
        runsLabel: "Rechecks",
        changedLabel: "Authorization shifts",
        findingsLabel: "New export findings",
        loadingLabel: "Loading authorization history...",
        emptyTitle: "No authorization rechecks yet",
        emptyDetail: "Run Monitor now to create the first live authorization timeline for this request.",
        findingsText: (count: number) => count === 1 ? "1 new export finding" : `${count} new export findings`,
        shiftedText: "Authorization posture shifted during this check",
        stableText: "No authorization shift",
      }
    : activeLaneKey === "cyber"
      ? {
          title: "Readiness history",
          detail: "Recent supplier cyber rechecks, readiness drift, and what changed across live monitoring runs",
          runsLabel: "Rechecks",
          changedLabel: "Readiness shifts",
          findingsLabel: "New cyber findings",
          loadingLabel: "Loading readiness history...",
          emptyTitle: "No readiness rechecks yet",
          emptyDetail: "Run Monitor now to create the first live supplier cyber recheck timeline.",
          findingsText: (count: number) => count === 1 ? "1 new cyber finding" : `${count} new cyber findings`,
          shiftedText: "Readiness posture shifted during this check",
          stableText: "No readiness shift",
        }
      : {
          title: "Counterparty history",
          detail: "Recent counterparty rechecks, posture drift, and what changed across live monitoring runs",
          runsLabel: "Rechecks",
          changedLabel: "Counterparty shifts",
          findingsLabel: "New counterparty findings",
          loadingLabel: "Loading counterparty history...",
          emptyTitle: "No counterparty rechecks yet",
          emptyDetail: "Run Monitor now to create the first live counterparty recheck timeline for this supplier.",
          findingsText: (count: number) => count === 1 ? "1 new counterparty finding" : `${count} new counterparty findings`,
          shiftedText: "Counterparty posture shifted during this check",
          stableText: "No counterparty shift",
        };

  return (
    <div className="flex flex-col gap-3 h-full">
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1 bg-transparent border-none p-0 cursor-pointer shrink-0 self-start"
        style={{ fontSize: FS.sm, color: T.muted }}
      >
        <ChevronLeft size={11} /> Back
      </button>


      <div className="flex-1 min-h-0 overflow-auto pr-1">
        <div className="rounded-[28px] shrink-0 helios-glass-strong" style={{ background: FX.hero, border: `1px solid ${activeLaneBrief.tone.border}`, padding: 18 }}>
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div style={{ flex: 1, minWidth: 260 }}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold" style={{ fontSize: 30, color: T.text, letterSpacing: "-0.04em", lineHeight: 1 }}>
                  {displayName(c.name)}
                </span>
                {cal && <TierBadge tier={cal.tier} />}
                {networkRisk && networkRisk.network_risk_score > 0 && (
                  <div className="inline-flex items-center gap-1 rounded px-1.5 py-0.5" style={{
                    background: networkRisk.network_risk_level === "critical" ? `${T.red}15` :
                                networkRisk.network_risk_level === "high" ? `${T.amber}15` : `#eab30815`,
                    border: `1px solid ${
                      networkRisk.network_risk_level === "critical" ? `${T.red}33` :
                      networkRisk.network_risk_level === "high" ? `${T.amber}33` : "#eab30833"
                    }`,
                  }}>
                    <Network size={10} color={
                      networkRisk.network_risk_level === "critical" ? T.red :
                      networkRisk.network_risk_level === "high" ? T.amber : "#eab308"
                    } />
                    <span className="font-mono" style={{
                      fontSize: 10, fontWeight: 600,
                      color: networkRisk.network_risk_level === "critical" ? T.red :
                             networkRisk.network_risk_level === "high" ? T.amber : "#eab308",
                    }}>
                      +{networkRisk.network_risk_score.toFixed(1)} net
                    </span>
                  </div>
                )}
                {isReadOnly && (
                  <div className="inline-flex items-center gap-1 rounded px-2 py-1" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                    <Lock size={10} color={T.muted} />
                    <span style={{ fontSize: FS.sm, color: T.muted, fontWeight: 600 }}>Read only</span>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 flex-wrap mt-2">
                {c.cc && (
                  <span className="inline-flex items-center gap-1" style={{ fontSize: FS.sm, color: T.muted }}>
                    <Globe size={11} />{c.cc}
                  </span>
                )}
                <span className="inline-flex items-center gap-1" style={{ fontSize: FS.sm, color: T.muted }}>
                  <Clock size={11} />
                  {formatCaseHeaderTimestamp(c.date)}
                </span>
              </div>
            </div>

            {cal && (
              <div className="flex items-center gap-3 flex-wrap justify-end">
                <div className="rounded-2xl px-3 py-2 helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.68)", border: `1px solid ${T.borderStrong}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Posterior</div>
                  <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>{Math.round(cal.p * 100)}%</div>
                </div>
                <div className="rounded-2xl px-3 py-2 helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.68)", border: `1px solid ${T.borderStrong}` }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Rubric</div>
                  <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>{c.sc}/100</div>
                </div>
              </div>
            )}
          </div>

          <div style={{ marginTop: 18, paddingTop: 18, borderTop: `1px solid ${T.borderStrong}` }}>
            <div style={{ fontSize: 26, fontWeight: 700, color: T.text, marginBottom: 8, letterSpacing: "-0.03em" }}>{decisionHeadline}</div>
            <div style={{ fontSize: FS.base, color: T.dim, lineHeight: 1.62, maxWidth: 760 }}>{decisionSummary}</div>
          </div>

          {showWorkflowLanes && (
            <div
              className="mt-4 rounded-[24px] helios-glass"
              style={{
                background: FX.panelStrong,
                border: `1px solid ${activeLaneBrief.tone.border}`,
                padding: 16,
              }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {activeLaneBrief.eyebrow}
                  </div>
                  <div className="flex items-center gap-2" style={{ marginTop: 4 }}>
                    <ActiveLaneIcon size={14} color={activeLaneBrief.tone.color} />
                    <div style={{ fontSize: FS.lg, color: T.text, fontWeight: 700 }}>{activeLaneBrief.title}</div>
                  </div>
                  {operatingLaneMeta && (
                    <div className="flex items-center gap-2 flex-wrap" style={{ marginTop: 8 }}>
                      <span
                        style={{
                          padding: "5px 9px",
                          borderRadius: 999,
                          background: T.surface,
                          border: `1px solid ${T.border}`,
                          fontSize: 11,
                          color: operatingModeMatchesCase ? T.text : T.accent,
                          fontWeight: 700,
                        }}
                      >
                        Operating mode: {operatingLaneMeta.shortLabel}
                      </span>
                      {!operatingModeMatchesCase && (
                        <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>
                          This case currently reads as {activeLaneBrief.title.toLowerCase()}.
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div
                  className="inline-flex items-center gap-2 rounded-full"
                  style={{
                    padding: "6px 10px",
                    background: activeLaneBrief.tone.background,
                    border: `1px solid ${activeLaneBrief.tone.border}`,
                    color: activeLaneBrief.tone.color,
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  {activeLaneBrief.stats[0].value}
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-[1.25fr,1fr] gap-3">
                <div className="rounded-2xl helios-glass" style={{ background: FX.panel, border: `1px solid ${T.borderStrong}`, padding: "13px 14px" }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Core question</div>
                  <div style={{ fontSize: FS.base, color: T.text, lineHeight: 1.5, marginTop: 8, letterSpacing: "-0.01em" }}>{activeLaneBrief.question}</div>

                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 12 }}>Decision outputs</div>
                  <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5, marginTop: 6, fontWeight: 700 }}>{activeLaneBrief.outputs}</div>

                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 12 }}>Evidence basis</div>
                  <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 6 }}>{activeLaneBrief.evidence}</div>
                </div>

                <div className="rounded-2xl helios-glass" style={{ background: FX.panel, border: `1px solid ${T.borderStrong}`, padding: "13px 14px" }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Lane readout</div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 xl:grid-cols-1 gap-2" style={{ marginTop: 8 }}>
                    {activeLaneBrief.stats.map((stat) => (
                      <div key={stat.label} className="rounded-2xl helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.72)", border: `1px solid ${T.borderStrong}`, padding: "10px 11px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{stat.label}</div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>{stat.value}</div>
                      </div>
                    ))}
                  </div>

                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 12 }}>Immediate next action</div>
                  <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 6 }}>{activeLaneBrief.nextAction}</div>
                </div>
              </div>

              {activeControlSummary && (
                <div className="rounded-2xl helios-glass" style={{ background: FX.panel, border: `1px solid ${T.borderStrong}`, padding: "12px 13px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Control posture</div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        What this lane is currently based on, what is still missing, and what it does not replace.
                      </div>
                    </div>
                    <div
                      className="inline-flex items-center gap-2 rounded-full"
                      style={{
                        padding: "6px 10px",
                        background: activeControlTone.background,
                        border: `1px solid ${activeControlTone.border}`,
                        color: activeControlTone.color,
                        fontSize: 11,
                        fontWeight: 700,
                      }}
                    >
                      {activeControlSummary.label}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
                    <div className="rounded-2xl helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.72)", border: `1px solid ${T.borderStrong}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Review basis</div>
                      <div style={{ fontSize: FS.sm, color: T.text, marginTop: 6, lineHeight: 1.55 }}>{activeControlSummary.review_basis}</div>
                    </div>
                    <div className="rounded-2xl helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.72)", border: `1px solid ${T.borderStrong}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Action owner</div>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>{activeControlSummary.action_owner}</div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 8 }}>{activeControlSummary.decision_boundary}</div>
                    </div>
                    <div className="rounded-2xl helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.72)", border: `1px solid ${T.borderStrong}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Missing inputs</div>
                      {activeControlMissing.length > 0 ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                          {activeControlMissing.map((item) => (
                            <div key={item} className="flex items-start gap-2" style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>
                              <AlertTriangle size={13} color={T.amber} style={{ marginTop: 2, flexShrink: 0 }} />
                              <span>{item}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 6 }}>
                          No major intake gap is currently flagged.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {executiveSignals.length > 0 && (
                <div className="rounded-2xl helios-glass" style={{ background: FX.panel, border: `1px solid ${T.borderStrong}`, padding: "12px 13px", marginTop: 12 }}>
                  <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>Executive summary</div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Decision, confidence, coverage, and recent change in one lane-specific readout.
                      </div>
                    </div>
                    <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      Decision / confidence / coverage / change
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                    {executiveSignals.map((signal) => (
                      <div
                        key={signal.label}
                        className="rounded-2xl helios-muted-ring"
                        style={{
                          background: signal.background,
                          border: `1px solid ${signal.border}`,
                          padding: "11px 12px 10px",
                        }}
                      >
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          {signal.label}
                        </div>
                        <div style={{ fontSize: FS.base, color: signal.color, fontWeight: 700, marginTop: 6 }}>
                          {signal.value}
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 6, lineHeight: 1.45 }}>
                          {signal.detail}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          )}

          {showWorkflowLanes && (
            <div
              className="mt-4 rounded-[24px] helios-glass"
              style={{
                background: FX.panel,
                border: `1px solid ${T.borderStrong}`,
                padding: 14,
              }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>Lane coverage</div>
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2, lineHeight: 1.45 }}>
                    The active lane is above. This section shows any other lane contributing evidence or review pressure.
                  </div>
                </div>
                <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  {secondaryLaneCards.length > 0 ? `${secondaryLaneCards.length} supporting lane${secondaryLaneCards.length === 1 ? "" : "s"}` : "No secondary lanes"}
                </div>
              </div>

              {secondaryLaneCards.length > 0 ? (
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                  {secondaryLaneCards.map((lane) => (
                    <button
                      key={lane.key}
                      type="button"
                      onClick={() => focusAuthorityLane(lane.key)}
                      className="rounded-2xl helios-card-hover helios-focus-ring"
                      style={{
                        background: FX.panelStrong,
                        border: `1px solid ${T.borderStrong}`,
                        padding: 12,
                        textAlign: "left",
                        cursor: "pointer",
                      }}
                    >
                      <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                        <div>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Supporting lane
                          </div>
                          <div style={{ fontSize: FS.base, color: T.text, fontWeight: 700, marginTop: 4 }}>
                            {lane.title}
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                            {lane.subtitle}
                          </div>
                        </div>
                        <div
                          className="inline-flex items-center gap-2 rounded-full"
                          style={{
                            padding: "6px 10px",
                            background: lane.tone.background,
                            border: `1px solid ${lane.tone.border}`,
                            color: lane.tone.color,
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          {lane.tone.label}
                        </div>
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{lane.detail}</div>
                      <div className="grid grid-cols-2 gap-2" style={{ marginTop: 10 }}>
                        {lane.stats.map((stat) => (
                          <div key={stat.label} className="rounded-2xl helios-muted-ring" style={{ background: "rgba(8, 13, 23, 0.72)", border: `1px solid ${T.borderStrong}`, padding: "10px 11px" }}>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{stat.label}</div>
                            <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>{stat.value}</div>
                          </div>
                        ))}
                      </div>
                      <div style={{ fontSize: 12, color: T.accent, fontWeight: 700, marginTop: 10 }}>
                        Open supporting evidence
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 13px" }}>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>Single-lane case</div>
                  <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginTop: 6 }}>
                    This case is currently driven by one decision lane. Detailed authority inputs below provide the source records behind that lane.
                  </div>
                </div>
              )}
            </div>
          )}

          {exportAuthorization && (
            <div
              className="mt-4 rounded-xl"
              style={{
                background: `linear-gradient(180deg, ${T.raised}, ${T.surface})`,
                border: `1px solid ${T.border}`,
                padding: 14,
              }}
            >
              <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>Export request profile</div>
                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2, lineHeight: 1.45 }}>
                    Captured intake for the export lane. The guidance and evidence below are what drive the authorization posture.
                  </div>
                </div>
                <div
                  className="inline-flex items-center gap-2 rounded-full"
                  style={{
                    padding: "6px 10px",
                    background: `${T.accent}12`,
                    border: `1px solid ${T.accent}33`,
                    color: T.accent,
                    fontSize: FS.sm,
                    fontWeight: 700,
                  }}
                >
                  <Lock size={12} />
                  {exportRequestTypeLabel(exportAuthorization.request_type)}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                {[
                  ["Recipient", exportAuthorization.recipient_name || c.name],
                  ["Destination / access country", exportAuthorization.destination_country || c.cc || "Unspecified"],
                  ["Jurisdiction guess", exportJurisdictionLabel(exportAuthorization.jurisdiction_guess)],
                  ["Classification", exportAuthorization.classification_guess || "Needs classification"],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-lg"
                    style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                  >
                    <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      {label}
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6, lineHeight: 1.45 }}>
                      {value}
                    </div>
                  </div>
                ))}
              </div>

              {(exportAuthorization.item_or_data_summary || exportAuthorization.end_use_summary || (exportAuthorization.foreign_person_nationalities?.length ?? 0) > 0) && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3" style={{ marginTop: 12 }}>
                  {exportAuthorization.item_or_data_summary && (
                    <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Item / data under review
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 6 }}>
                        {exportAuthorization.item_or_data_summary}
                      </div>
                    </div>
                  )}
                  <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                    <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      Context
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.55, marginTop: 6 }}>
                      {exportAuthorization.end_use_summary || exportAuthorization.access_context || "No additional context captured yet."}
                    </div>
                    {(exportAuthorization.foreign_person_nationalities?.length ?? 0) > 0 && (
                      <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {exportAuthorization.foreign_person_nationalities?.map((nationality) => (
                          <span
                            key={nationality}
                            style={{
                              padding: "3px 8px",
                              borderRadius: 999,
                              background: T.raised,
                              border: `1px solid ${T.border}`,
                              fontSize: 11,
                              color: T.text,
                              fontWeight: 600,
                            }}
                          >
                            {nationality}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

            </div>
          )}

          {/* LEVEL 1: Key Findings (always visible) */}
          {cal?.finds && cal.finds.length > 0 && (
            <div className="mt-3 rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
              <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                Key Findings
              </div>
              {cal.finds.map((finding, i) => (
                <div key={i} className="flex gap-2" style={{ marginTop: i > 0 ? 6 : 0 }}>
                  <span className="font-mono font-bold shrink-0" style={{ fontSize: FS.sm, color: T.accent }}>
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{finding}</span>
                </div>
              ))}
            </div>
          )}

          {showWorkflowLanes && (
                <div ref={authorityInputsRef} style={{ marginTop: 12, marginBottom: 2 }}>
                  <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Detailed authority inputs
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                    The sections below are the underlying customer artifacts, official sources, and rule inputs behind the workflow lanes.
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                    {authorityLaneTabs.map((tab) => {
                      const active = authorityLaneKey === tab.key;
                      return (
                        <button
                          key={tab.key}
                          onClick={() => setAuthorityLaneSelection({ caseId: c.id, lane: tab.key })}
                          style={{
                            minWidth: 142,
                            padding: "9px 11px",
                            borderRadius: 12,
                            border: `1px solid ${active ? tab.tone.border : T.border}`,
                            background: active ? tab.tone.background : T.surface,
                            color: active ? tab.tone.color : T.text,
                            textAlign: "left",
                            cursor: "pointer",
                          }}
                        >
                          <div style={{ fontSize: 12, fontWeight: 800 }}>{tab.title}</div>
                          <div style={{ fontSize: 11, marginTop: 3, color: active ? tab.tone.color : T.muted }}>
                            {tab.detail} • {tab.subtitle}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {showFociPanel && authorityLaneKey === "counterparty" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        FOCI detailed evidence
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Attach Form 328 records, ownership charts, cap tables, board rosters, or mitigation instruments so Helios can ground defense counterparty trust decisions in customer-controlled ownership and control evidence.
                      </div>
                    </div>
                    {!isReadOnly && (
                      <button
                        onClick={() => fociInputRef.current?.click()}
                        disabled={uploadingFociArtifact}
                        style={{
                          padding: "9px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: uploadingFociArtifact ? T.surface : `${T.accent}10`,
                          color: uploadingFociArtifact ? T.muted : T.accent,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                          cursor: uploadingFociArtifact ? "wait" : "pointer",
                        }}
                      >
                        <Upload size={14} />
                        {uploadingFociArtifact ? "Uploading..." : "Upload FOCI artifact"}
                      </button>
                    )}
                  </div>

                  <input
                    ref={fociInputRef}
                    type="file"
                    accept=".pdf,.doc,.docx,.xlsx,.xls,.csv,.txt,.json,.md"
                    style={{ display: "none" }}
                    onChange={handleFociArtifactSelected}
                  />

                  {latestFociSummary && (
                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-3" style={{ marginBottom: 10 }}>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Latest artifact
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(latestFociSummary.artifact_label || "FOCI artifact")}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Foreign ownership
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(
                            latestFociSummary.declared_foreign_ownership_pct
                            || latestFociSummary.max_ownership_percent_mention
                            || "Not stated",
                          )}
                          {typeof latestFociSummary.max_ownership_percent_mention === "number"
                            && !latestFociSummary.declared_foreign_ownership_pct
                            ? "%"
                            : ""}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Mitigation
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(
                            latestFociSummary.declared_mitigation_type
                            || (Array.isArray(latestFociSummary.mitigation_tokens) && latestFociSummary.mitigation_tokens.length > 0
                              ? latestFociSummary.mitigation_tokens[0]
                              : latestFociSummary.declared_mitigation_status || "Not stated"),
                          ).replaceAll("_", " ")}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Foreign counterparty
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(
                            latestFociSummary.declared_foreign_owner
                            || latestFociSummary.declared_foreign_country
                            || "Not stated",
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {fociArtifacts.length === 0 ? (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                      No customer-provided FOCI artifacts attached yet.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {fociArtifacts.slice(0, 4).map((artifact) => {
                        const summary = artifact.structured_fields as Record<string, unknown> | undefined;
                        const mitigationTokens = Array.isArray(summary?.mitigation_tokens)
                          ? (summary?.mitigation_tokens as string[])
                          : [];
                        return (
                          <div
                            key={artifact.id}
                            className="rounded-lg"
                            style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                          >
                            <div className="flex items-start justify-between gap-3 flex-wrap">
                              <div>
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  {fociArtifactTypeLabel(artifact.artifact_type)}
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3 }}>
                                  {artifact.filename}
                                </div>
                              </div>
                              <button
                                onClick={async () => {
                                  const url = await buildProtectedUrl(`/api/cases/${c.id}/foci-artifacts/${artifact.id}`);
                                  window.open(url, "_blank", "noopener,noreferrer");
                                }}
                                style={{ padding: "7px 10px", borderRadius: 9, border: `1px solid ${T.border}`, background: T.surface, color: T.text, fontSize: 12, fontWeight: 700, cursor: "pointer" }}
                              >
                                Open
                              </button>
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              <span>{artifact.parse_status.replaceAll("_", " ")}</span>
                              <span>•</span>
                              <span>{String(summary?.artifact_label || "FOCI artifact")}</span>
                              <span>•</span>
                              <span>
                                {String(
                                  summary?.declared_foreign_ownership_pct
                                  || (typeof summary?.max_ownership_percent_mention === "number"
                                    ? `${summary.max_ownership_percent_mention}%`
                                    : "Ownership not stated"),
                                )}
                              </span>
                            </div>
                            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 8, lineHeight: 1.5 }}>
                              {summary?.declared_foreign_owner ? `Declared foreign owner: ${String(summary.declared_foreign_owner)}. ` : ""}
                              {summary?.declared_foreign_country ? `Country: ${String(summary.declared_foreign_country)}. ` : ""}
                              {summary?.declared_mitigation_status ? `Mitigation status ${String(summary.declared_mitigation_status).replaceAll("_", " ")}. ` : ""}
                              {summary?.contains_foreign_influence_terms ? "Foreign-influence terms detected. " : ""}
                              {summary?.contains_governance_control_terms ? "Governance-control terms detected." : ""}
                            </div>
                            {mitigationTokens.length > 0 && (
                              <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                {mitigationTokens.slice(0, 4).map((token) => (
                                  <span
                                    key={token}
                                    style={{
                                      padding: "4px 8px",
                                      borderRadius: 999,
                                      background: T.surface,
                                      border: `1px solid ${T.border}`,
                                      color: T.text,
                                      fontSize: 11,
                                      fontWeight: 700,
                                    }}
                                  >
                                    {token.replaceAll("_", " ")}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {showSprsPanel && authorityLaneKey === "cyber" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        SPRS evidence
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Attach customer-controlled SPRS exports so Helios can ground supplier cyber-trust decisions in assessment score, current CMMC level, and POA&amp;M context.
                      </div>
                    </div>
                    {!isReadOnly && (
                      <button
                        onClick={() => sprsInputRef.current?.click()}
                        disabled={uploadingSprsImport}
                        style={{
                          padding: "9px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: uploadingSprsImport ? T.surface : `${T.accent}10`,
                          color: uploadingSprsImport ? T.muted : T.accent,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                          cursor: uploadingSprsImport ? "wait" : "pointer",
                        }}
                      >
                        <Upload size={14} />
                        {uploadingSprsImport ? "Uploading..." : "Upload SPRS export"}
                      </button>
                    )}
                  </div>

                  <input
                    ref={sprsInputRef}
                    type="file"
                    accept=".csv,.json,application/json,text/csv"
                    style={{ display: "none" }}
                    onChange={handleSprsImportSelected}
                  />

                  {latestSprsSummary && (
                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-3" style={{ marginBottom: 10 }}>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Latest score
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestSprsSummary.assessment_score === "number"
                            ? latestSprsSummary.assessment_score
                            : "Unknown"}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          CMMC level
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {latestSprsSummary.current_cmmc_level != null
                            ? String(latestSprsSummary.current_cmmc_level)
                            : "Unknown"}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Assessment status
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {sprsStatusLabel(String(latestSprsSummary.status || ""))}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          POA&amp;M
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {latestSprsSummary.poam_active === true
                            ? "Active"
                            : latestSprsSummary.poam_active === false
                              ? "Not active"
                              : "Not stated"}
                        </div>
                      </div>
                    </div>
                  )}

                  {sprsImports.length === 0 ? (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                      No customer-provided SPRS exports attached yet.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {sprsImports.slice(0, 3).map((artifact) => {
                        const summary = artifact.structured_fields?.summary as Record<string, unknown> | undefined;
                        return (
                          <div
                            key={artifact.id}
                            className="rounded-lg"
                            style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                          >
                            <div className="flex items-start justify-between gap-3 flex-wrap">
                              <div>
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  SPRS export
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3 }}>
                                  {artifact.filename}
                                </div>
                              </div>
                              <button
                                onClick={async () => {
                                  const url = await buildProtectedUrl(`/api/cases/${c.id}/sprs-imports/${artifact.id}`);
                                  window.open(url, "_blank", "noopener,noreferrer");
                                }}
                                style={{
                                  padding: "7px 10px",
                                  borderRadius: 9,
                                  border: `1px solid ${T.border}`,
                                  background: T.surface,
                                  color: T.text,
                                  fontSize: 12,
                                  fontWeight: 700,
                                  cursor: "pointer",
                                }}
                              >
                                Open
                              </button>
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              <span>{artifact.parse_status.replaceAll("_", " ")}</span>
                              <span>•</span>
                              <span>{typeof summary?.assessment_score === "number" ? `Score ${summary.assessment_score}` : "Score not stated"}</span>
                              <span>•</span>
                              <span>{summary?.assessment_date ? String(summary.assessment_date) : "Date not stated"}</span>
                            </div>
                            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 8, lineHeight: 1.5 }}>
                              {summary?.matched_supplier_name ? `Matched supplier: ${String(summary.matched_supplier_name)}. ` : ""}
                              {summary?.current_cmmc_level ? `Current CMMC level ${String(summary.current_cmmc_level)}. ` : ""}
                              {summary?.status ? `Status ${sprsStatusLabel(String(summary.status))}. ` : ""}
                              {summary?.poam_active === true ? "POA&M flagged active." : summary?.poam_active === false ? "No active POA&M indicated." : ""}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {showOscalPanel && authorityLaneKey === "cyber" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        OSCAL remediation evidence
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Attach OSCAL SSP or POA&amp;M JSON so Helios can ground supplier cyber-trust decisions in control-family coverage and active remediation work, not just assessment score.
                      </div>
                    </div>
                    {!isReadOnly && (
                      <button
                        onClick={() => oscalInputRef.current?.click()}
                        disabled={uploadingOscalArtifact}
                        style={{
                          padding: "9px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: uploadingOscalArtifact ? T.surface : `${T.accent}10`,
                          color: uploadingOscalArtifact ? T.muted : T.accent,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                          cursor: uploadingOscalArtifact ? "wait" : "pointer",
                        }}
                      >
                        <Upload size={14} />
                        {uploadingOscalArtifact ? "Uploading..." : "Upload OSCAL JSON"}
                      </button>
                    )}
                  </div>

                  <input
                    ref={oscalInputRef}
                    type="file"
                    accept=".json,application/json"
                    style={{ display: "none" }}
                    onChange={handleOscalArtifactSelected}
                  />

                  {latestOscalSummary && (
                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-3" style={{ marginBottom: 10 }}>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Latest document
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(latestOscalSummary.document_label || "OSCAL artifact")}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          System
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {String(latestOscalSummary.system_name || "Unnamed system")}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Open POA&amp;M items
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestOscalSummary.open_poam_items === "number"
                            ? latestOscalSummary.open_poam_items
                            : "0"}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Control references
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestOscalSummary.total_control_references === "number"
                            ? latestOscalSummary.total_control_references
                            : "0"}
                        </div>
                      </div>
                    </div>
                  )}

                  {oscalArtifacts.length === 0 ? (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                      No OSCAL security-plan or POA&amp;M artifacts attached yet.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {oscalArtifacts.slice(0, 3).map((artifact) => {
                        const summary = artifact.structured_fields?.summary as Record<string, unknown> | undefined;
                        const familyHighlights = Array.isArray(summary?.control_family_highlights)
                          ? (summary?.control_family_highlights as Array<{ family?: string; count?: number }>)
                          : [];
                        const remediationHighlights = Array.isArray(summary?.remediation_highlights)
                          ? (summary?.remediation_highlights as Array<{ title?: string; status?: string; due_date?: string }>)
                          : [];
                        return (
                          <div
                            key={artifact.id}
                            className="rounded-lg"
                            style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                          >
                            <div className="flex items-start justify-between gap-3 flex-wrap">
                              <div>
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  {oscalArtifactTypeLabel(artifact.artifact_type)}
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3 }}>
                                  {artifact.filename}
                                </div>
                              </div>
                              <button
                                onClick={async () => {
                                  const url = await buildProtectedUrl(`/api/cases/${c.id}/oscal-artifacts/${artifact.id}`);
                                  window.open(url, "_blank", "noopener,noreferrer");
                                }}
                                style={{
                                  padding: "7px 10px",
                                  borderRadius: 9,
                                  border: `1px solid ${T.border}`,
                                  background: T.surface,
                                  color: T.text,
                                  fontSize: 12,
                                  fontWeight: 700,
                                  cursor: "pointer",
                                }}
                              >
                                Open
                              </button>
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              <span>{artifact.parse_status.replaceAll("_", " ")}</span>
                              <span>•</span>
                              <span>{String(summary?.system_name || "Unnamed system")}</span>
                              <span>•</span>
                              <span>{typeof summary?.open_poam_items === "number" ? `${summary.open_poam_items} open items` : "No POA&M summary"}</span>
                            </div>
                            {familyHighlights.length > 0 && (
                              <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                {familyHighlights.slice(0, 4).map((entry) => (
                                  <span
                                    key={`${entry.family}-${entry.count}`}
                                    style={{
                                      padding: "4px 8px",
                                      borderRadius: 999,
                                      background: T.surface,
                                      border: `1px solid ${T.border}`,
                                      color: T.text,
                                      fontSize: 11,
                                      fontWeight: 700,
                                    }}
                                  >
                                    {String(entry.family || "CTRL")} {typeof entry.count === "number" ? entry.count : ""}
                                  </span>
                                ))}
                              </div>
                            )}
                            {remediationHighlights.length > 0 && (
                              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                                {remediationHighlights.slice(0, 2).map((item, idx) => (
                                  <div key={`${item.title}-${idx}`} style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.45 }}>
                                    {item.title || "Open remediation item"}
                                    {item.due_date ? ` • due ${item.due_date}` : ""}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {showNvdPanel && authorityLaneKey === "cyber" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        NVD vulnerability evidence
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Add a few supplier product or software references and Helios will summarize the broader NVD vulnerability posture behind the current CMMC and remediation evidence.
                      </div>
                    </div>
                    {!isReadOnly && (
                      <button
                        onClick={handleRunNvdOverlay}
                        disabled={runningNvdOverlay}
                        style={{
                          padding: "9px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: runningNvdOverlay ? T.surface : `${T.accent}10`,
                          color: runningNvdOverlay ? T.muted : T.accent,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 8,
                          cursor: runningNvdOverlay ? "wait" : "pointer",
                        }}
                      >
                        <Radar size={14} />
                        {runningNvdOverlay ? "Running..." : "Run NVD overlay"}
                      </button>
                    )}
                  </div>

                  {!isReadOnly && (
                    <textarea
                      value={nvdProductTermsInput}
                      onChange={(event) => setNvdProductTermsInput(event.target.value)}
                      placeholder={"Secure Portal\nRemote Access Gateway\nTelemetry Agent"}
                      rows={3}
                      style={{
                        width: "100%",
                        resize: "vertical",
                        padding: "10px 12px",
                        borderRadius: 10,
                        border: `1px solid ${T.border}`,
                        background: T.raised,
                        color: T.text,
                        fontSize: FS.sm,
                        lineHeight: 1.5,
                        marginBottom: 10,
                      }}
                    />
                  )}

                  {latestNvdSummary && (
                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-3" style={{ marginBottom: 10 }}>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Product refs
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {Array.isArray(latestNvdSummary.product_terms) ? latestNvdSummary.product_terms.length : 0}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Unique CVEs
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestNvdSummary.unique_cve_count === "number" ? latestNvdSummary.unique_cve_count : 0}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          High / critical
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestNvdSummary.high_or_critical_cve_count === "number" ? latestNvdSummary.high_or_critical_cve_count : 0}
                        </div>
                      </div>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          KEV-linked
                        </div>
                        <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                          {typeof latestNvdSummary.kev_flagged_cve_count === "number" ? latestNvdSummary.kev_flagged_cve_count : 0}
                        </div>
                      </div>
                    </div>
                  )}

                  {nvdOverlays.length === 0 ? (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                      No NVD product overlay has been run for this case yet.
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {nvdOverlays.slice(0, 3).map((artifact) => {
                        const summary = artifact.structured_fields?.summary as Record<string, unknown> | undefined;
                        const productTerms = Array.isArray(artifact.structured_fields?.product_terms)
                          ? artifact.structured_fields?.product_terms as string[]
                          : [];
                        return (
                          <div
                            key={artifact.id}
                            className="rounded-lg"
                            style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                          >
                            <div className="flex items-start justify-between gap-3 flex-wrap">
                              <div>
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  NVD overlay
                                </div>
                                <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3 }}>
                                  {productTerms.length > 0 ? productTerms.join(", ") : artifact.filename}
                                </div>
                              </div>
                              <button
                                onClick={async () => {
                                  const url = await buildProtectedUrl(`/api/cases/${c.id}/nvd-overlays/${artifact.id}`);
                                  window.open(url, "_blank", "noopener,noreferrer");
                                }}
                                style={{
                                  padding: "7px 10px",
                                  borderRadius: 9,
                                  border: `1px solid ${T.border}`,
                                  background: T.surface,
                                  color: T.text,
                                  fontSize: 12,
                                  fontWeight: 700,
                                  cursor: "pointer",
                                }}
                              >
                                Open
                              </button>
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              <span>{typeof summary?.unique_cve_count === "number" ? `${summary.unique_cve_count} CVEs` : "0 CVEs"}</span>
                              <span>•</span>
                              <span>{typeof summary?.high_or_critical_cve_count === "number" ? `${summary.high_or_critical_cve_count} high / critical` : "0 high / critical"}</span>
                              <span>•</span>
                              <span>{typeof summary?.kev_flagged_cve_count === "number" ? `${summary.kev_flagged_cve_count} KEV-linked` : "0 KEV-linked"}</span>
                            </div>
                            {productTerms.length > 0 && (
                              <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                {productTerms.slice(0, 4).map((term) => (
                                  <span
                                    key={`${artifact.id}-${term}`}
                                    style={{
                                      padding: "4px 8px",
                                      borderRadius: 999,
                                      background: T.surface,
                                      border: `1px solid ${T.border}`,
                                      color: T.text,
                                      fontSize: 11,
                                      fontWeight: 700,
                                    }}
                                  >
                                    {term}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {authorityLaneKey === "cyber" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Cyber risk score
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Multi-dimensional cyber risk assessment across CMMC readiness, vulnerability exposure, remediation posture, supply chain propagation, and compliance maturity.
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        setLoadingCyberScore(true);
                        try {
                          const result = await computeCyberRiskScore(c.id, c.profile);
                          setCyberRiskScore(result);
                        } catch (err) {
                          console.error("Cyber risk scoring failed:", err);
                        } finally {
                          setLoadingCyberScore(false);
                        }
                      }}
                      disabled={loadingCyberScore}
                      style={{
                        padding: "9px 12px",
                        borderRadius: 10,
                        border: `1px solid ${T.border}`,
                        background: loadingCyberScore ? T.surface : `${T.accent}10`,
                        color: loadingCyberScore ? T.muted : T.accent,
                        fontSize: FS.sm,
                        fontWeight: 700,
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 8,
                        cursor: loadingCyberScore ? "wait" : "pointer",
                      }}
                    >
                      <Shield size={14} />
                      {loadingCyberScore ? "Scoring..." : "Run cyber score"}
                    </button>
                  </div>

                  {showThreatSignalCard && (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px", marginBottom: 12 }}>
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Active threat signal
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                            Analyst-facing pressure from ATT&CK mappings, CISA advisories, and open-source exposure. This is here to explain why the supplier matters now, not to turn the case page into a threat feed.
                          </div>
                        </div>
                        <div
                          className="inline-flex items-center gap-2 rounded-full"
                          style={{
                            padding: "6px 10px",
                            background: threatPressureTone(threatPressure).background,
                            border: `1px solid ${threatPressureTone(threatPressure).border}`,
                            color: threatPressureTone(threatPressure).color,
                            fontSize: FS.sm,
                            fontWeight: 700,
                          }}
                        >
                          <AlertTriangle size={12} />
                          {threatPressureLabel(threatPressure)}
                        </div>
                      </div>

                      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3" style={{ marginTop: 10 }}>
                        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "10px 12px" }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            ATT&CK techniques
                          </div>
                          <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                            {attackTechniqueIds.length}
                          </div>
                        </div>
                        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "10px 12px" }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            CISA advisories
                          </div>
                          <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                            {cisaAdvisoryIds.length}
                          </div>
                        </div>
                        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "10px 12px" }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            OSS advisories
                          </div>
                          <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                            {openSourceAdvisoryCount}
                          </div>
                        </div>
                        <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "10px 12px" }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Low-score repos
                          </div>
                          <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700, marginTop: 6 }}>
                            {scorecardLowRepoCount}
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2" style={{ marginTop: 10 }}>
                        {actorFamilies.slice(0, 3).map((family) => (
                          <span
                            key={`actor-${family}`}
                            className="rounded-full"
                            style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.red, background: T.redBg }}
                          >
                            {family}
                          </span>
                        ))}
                        {threatSectors.slice(0, 3).map((sector) => (
                          <span
                            key={`sector-${sector}`}
                            className="rounded-full"
                            style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.accent, background: `${T.accent}18` }}
                          >
                            {sector}
                          </span>
                        ))}
                        {attackTechniqueIds.slice(0, 4).map((technique) => (
                          <span
                            key={`attack-${technique}`}
                            className="rounded-full"
                            style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.amber, background: T.amberBg }}
                          >
                            {technique}
                          </span>
                        ))}
                        {cisaAdvisoryIds.slice(0, 3).map((advisory) => (
                          <span
                            key={`cisa-${advisory}`}
                            className="rounded-full"
                            style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.text, background: T.surface, border: `1px solid ${T.border}` }}
                          >
                            {advisory}
                          </span>
                        ))}
                        {openSourceRiskLevel && (
                          <span
                            className="rounded-full"
                            style={{
                              padding: "4px 8px",
                              fontSize: 11,
                              fontWeight: 700,
                              color: openSourceRiskLevel === "high" ? T.red : openSourceRiskLevel === "medium" ? T.amber : T.green,
                              background: openSourceRiskLevel === "high" ? T.redBg : openSourceRiskLevel === "medium" ? T.amberBg : T.greenBg,
                            }}
                          >
                            OSS risk: {openSourceRiskLevel}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {cyberRiskScore && (() => {
                    const tierColors: Record<string, string> = {
                      LOW: T.green, MODERATE: T.accent, ELEVATED: T.amber,
                      HIGH: "#f97316", CRITICAL: T.red,
                    };
                    const tierColor = tierColors[cyberRiskScore.cyber_risk_tier] || T.muted;
                    const dims = cyberRiskScore.dimensions;
                    const dimEntries = [
                      { label: "CMMC readiness", key: "cmmc_readiness" as const, dim: dims.cmmc_readiness },
                      { label: "Vuln exposure", key: "vulnerability_exposure" as const, dim: dims.vulnerability_exposure },
                      { label: "Remediation", key: "remediation_posture" as const, dim: dims.remediation_posture },
                      { label: "Supply chain", key: "supply_chain_propagation" as const, dim: dims.supply_chain_propagation },
                      { label: "Compliance", key: "compliance_maturity" as const, dim: dims.compliance_maturity },
                    ];
                    return (
                      <div>
                        <div className="flex items-center gap-4" style={{ marginBottom: 12 }}>
                          <div style={{ fontSize: 32, fontWeight: 800, color: tierColor }}>
                            {(cyberRiskScore.cyber_risk_score * 100).toFixed(0)}
                          </div>
                          <div>
                            <div style={{
                              fontSize: FS.sm, fontWeight: 700, color: tierColor,
                              padding: "3px 10px", borderRadius: 999,
                              background: `${tierColor}18`, border: `1px solid ${tierColor}33`,
                              display: "inline-block",
                            }}>
                              {cyberRiskScore.cyber_risk_tier}
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>
                              Confidence: {(cyberRiskScore.confidence * 100).toFixed(0)}%
                            </div>
                          </div>
                        </div>

                        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
                          {dimEntries.map(({ label, dim }) => {
                            const pct = Math.round(dim.score * 100);
                            const barColor = dim.score >= 0.8 ? T.red : dim.score >= 0.6 ? "#f97316" : dim.score >= 0.4 ? T.amber : dim.score >= 0.2 ? T.accent : T.green;
                            return (
                              <div key={label}>
                                <div className="flex items-center justify-between" style={{ fontSize: 11, color: T.muted, marginBottom: 3 }}>
                                  <span>{label} ({(dim.weight * 100).toFixed(0)}%)</span>
                                  <span style={{ fontWeight: 700, color: barColor }}>{pct}</span>
                                </div>
                                <div style={{ height: 6, borderRadius: 3, background: T.raised, overflow: "hidden" }}>
                                  <div style={{ height: "100%", width: `${pct}%`, borderRadius: 3, background: barColor, transition: "width 0.4s ease" }} />
                                </div>
                              </div>
                            );
                          })}
                        </div>

                        {cyberRiskScore.top_findings.length > 0 && (
                          <div style={{ marginBottom: 10 }}>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                              Top findings
                            </div>
                            {cyberRiskScore.top_findings.slice(0, 3).map((f, i) => (
                              <div key={i} style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, padding: "4px 0", borderTop: i > 0 ? `1px solid ${T.border}` : undefined }}>
                                {f}
                              </div>
                            ))}
                          </div>
                        )}

                        {cyberRiskScore.recommended_actions.length > 0 && (
                          <div>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                              Recommended actions
                            </div>
                            {cyberRiskScore.recommended_actions.slice(0, 3).map((a, i) => (
                              <div key={i} style={{ fontSize: FS.sm, color: T.accent, lineHeight: 1.5, padding: "4px 0", borderTop: i > 0 ? `1px solid ${T.border}` : undefined }}>
                                {a}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              )}

              {authorityLaneKey === "export" && exportAuthorizationGuidance && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        BIS authority guidance
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginTop: 4 }}>
                        {exportAuthorizationGuidance.reason_summary}
                      </div>
                    </div>
                    <div
                      className="inline-flex items-center gap-2 rounded-full"
                      style={{
                        padding: "6px 10px",
                        background: exportGuidanceTone(exportAuthorizationGuidance.posture).background,
                        border: `1px solid ${exportGuidanceTone(exportAuthorizationGuidance.posture).border}`,
                        color: exportGuidanceTone(exportAuthorizationGuidance.posture).color,
                        fontSize: FS.sm,
                        fontWeight: 700,
                      }}
                    >
                      <AlertTriangle size={12} />
                      {exportAuthorizationGuidance.posture_label}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Country posture
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                        {exportAuthorizationGuidance.country_analysis.country_bucket}
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginTop: 6 }}>
                        {exportAuthorizationGuidance.country_analysis.rationale}
                      </div>
                    </div>

                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Classification posture
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700, marginTop: 6 }}>
                        {exportAuthorizationGuidance.classification_analysis.label}
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginTop: 6 }}>
                        {exportAuthorizationGuidance.classification_analysis.rationale}
                      </div>
                    </div>

                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Recommended next step
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, marginTop: 6 }}>
                        {exportAuthorizationGuidance.recommended_next_step}
                      </div>
                      <div style={{ fontSize: 11, color: T.muted, marginTop: 8 }}>
                        Confidence {Math.round(exportAuthorizationGuidance.confidence * 100)}% • {exportAuthorizationGuidance.authority_level.replaceAll("_", " ")}
                      </div>
                    </div>
                  </div>

                  {(exportAuthorizationGuidance.end_use_flags.length > 0 || exportAuthorizationGuidance.factors.length > 0) && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3" style={{ marginTop: 12 }}>
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                          Decision factors
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                          {exportAuthorizationGuidance.factors.slice(0, 4).map((factor) => (
                            <div key={factor} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>
                              <div style={{ width: 6, height: 6, borderRadius: 999, background: T.accent, marginTop: 7, flexShrink: 0 }} />
                              <div>{factor}</div>
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                          Official references
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                          {exportAuthorizationGuidance.official_references.slice(0, 3).map((reference) => (
                            <a
                              key={reference.title}
                              href={reference.url}
                              target="_blank"
                              rel="noreferrer"
                              style={{ display: "block", textDecoration: "none" }}
                            >
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{reference.title}</div>
                              <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.45, marginTop: 3 }}>{reference.note}</div>
                            </a>
                          ))}
                        </div>
                        {exportAuthorizationGuidance.end_use_flags.length > 0 && (
                          <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
                            {exportAuthorizationGuidance.end_use_flags.slice(0, 3).map((flag) => (
                              <span
                                key={flag.key}
                                style={{
                                  padding: "4px 8px",
                                  borderRadius: 999,
                                  background: flag.severity === "critical" ? T.redBg : `${T.amber}12`,
                                  border: `1px solid ${flag.severity === "critical" ? `${T.red}33` : `${T.amber}33`}`,
                                  color: flag.severity === "critical" ? T.red : T.amber,
                                  fontSize: 11,
                                  fontWeight: 700,
                                }}
                              >
                                {flag.label}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Transaction Authorization Pipeline (S12) */}
              {authorityLaneKey === "export" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: txAuth ? 12 : 0 }}>
                    <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      Transaction authorization pipeline
                    </div>
                    {exportAuthorization && !txAuthLoading && (
                      <button
                        onClick={handleRunTxAuth}
                        style={{
                          padding: "6px 12px",
                          borderRadius: 8,
                          border: `1px solid ${T.border}`,
                          background: `${T.accent}10`,
                          color: T.accent,
                          fontSize: 11,
                          fontWeight: 700,
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        {txAuth ? "Re-run" : "Run Authorization"}
                      </button>
                    )}
                  </div>
                  <TransactionAuthorizationPanel
                    authorization={txAuth}
                    loading={txAuthLoading}
                    onRerun={exportAuthorization ? handleRunTxAuth : undefined}
                  />
                </div>
              )}

              {authorityLaneKey === "export" && (
              <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                      Customer export artifacts
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                      Attach classification memos, CCATS / CJ outcomes, license history, or access-control records so the export case stays grounded in customer-controlled evidence.
                    </div>
                  </div>
                  {!isReadOnly && (
                    <button
                      onClick={() => exportArtifactInputRef.current?.click()}
                      disabled={uploadingExportArtifact}
                      style={{
                        padding: "9px 12px",
                        borderRadius: 10,
                        border: `1px solid ${T.border}`,
                        background: uploadingExportArtifact ? T.surface : `${T.accent}10`,
                        color: uploadingExportArtifact ? T.muted : T.accent,
                        fontSize: FS.sm,
                        fontWeight: 700,
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 8,
                        cursor: uploadingExportArtifact ? "wait" : "pointer",
                      }}
                    >
                      <Upload size={14} />
                      {uploadingExportArtifact ? "Uploading..." : "Upload artifact"}
                    </button>
                  )}
                </div>

                <input
                  ref={exportArtifactInputRef}
                  type="file"
                  style={{ display: "none" }}
                  onChange={handleExportArtifactSelected}
                />

                {exportArtifacts.length === 0 ? (
                  <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                    No customer-controlled export artifacts attached yet.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {exportArtifacts.slice(0, 4).map((artifact) => (
                      <div
                        key={artifact.id}
                        className="rounded-lg"
                        style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px" }}
                      >
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div>
                            <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                              {exportArtifactTypeLabel(artifact.artifact_type)}
                            </div>
                            <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 3 }}>
                              {artifact.filename}
                            </div>
                          </div>
                          <button
                            onClick={async () => {
                              const url = await buildProtectedUrl(`/api/cases/${c.id}/export-artifacts/${artifact.id}`);
                              window.open(url, "_blank", "noopener,noreferrer");
                            }}
                            style={{
                              padding: "7px 10px",
                              borderRadius: 9,
                              border: `1px solid ${T.border}`,
                              background: T.surface,
                              color: T.text,
                              fontSize: 12,
                              fontWeight: 700,
                              cursor: "pointer",
                            }}
                          >
                            Open
                          </button>
                        </div>
                        <div style={{ fontSize: 11, color: T.muted, marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <span>{artifact.parse_status.replaceAll("_", " ")}</span>
                          <span>•</span>
                          <span>{artifact.authority_level.replaceAll("_", " ")}</span>
                          <span>•</span>
                          <span>{Math.max(1, Math.round((artifact.size_bytes || 0) / 1024))} KB</span>
                        </div>
                        {Array.isArray(artifact.structured_fields?.detected_classifications) && (artifact.structured_fields?.detected_classifications as string[]).length > 0 && (
                          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
                            {(artifact.structured_fields.detected_classifications as string[]).slice(0, 3).map((value) => (
                              <span
                                key={value}
                                style={{
                                  padding: "3px 8px",
                                  borderRadius: 999,
                                  background: `${T.accent}12`,
                                  border: `1px solid ${T.accent}33`,
                                  color: T.accent,
                                  fontSize: 11,
                                  fontWeight: 700,
                                }}
                              >
                                {value}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              )}
              {authorityLaneKey === "export" && (
                <div className="rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "12px 12px 10px", marginTop: 12 }}>
                  <div className="flex items-start justify-between gap-3 flex-wrap" style={{ marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Person / POI clearance check
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>
                        Screen individuals against denied parties, sanctions lists, and screening databases to assess clearance status and export risk.
                      </div>
                    </div>
                  </div>

                  {!isReadOnly && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 10 }}>
                      <input
                        type="text"
                        placeholder="Person name (required)"
                        value={personScreeningName}
                        onChange={(e) => setPersonScreeningName(e.target.value)}
                        style={{
                          width: "100%",
                          padding: "10px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: T.raised,
                          color: T.text,
                          fontSize: FS.sm,
                        }}
                      />
                      <input
                        type="text"
                        placeholder="Nationalities (comma-separated ISO-2 codes, e.g., US, CN, RU)"
                        value={personScreeningNationalities}
                        onChange={(e) => setPersonScreeningNationalities(e.target.value)}
                        style={{
                          width: "100%",
                          padding: "10px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: T.raised,
                          color: T.text,
                          fontSize: FS.sm,
                        }}
                      />
                      <input
                        type="text"
                        placeholder="Employer / Affiliation (optional)"
                        value={personScreeningEmployer}
                        onChange={(e) => setPersonScreeningEmployer(e.target.value)}
                        style={{
                          width: "100%",
                          padding: "10px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: T.raised,
                          color: T.text,
                          fontSize: FS.sm,
                        }}
                      />
                      <button
                        onClick={handleScreenPerson}
                        disabled={screeningPerson}
                        style={{
                          padding: "9px 12px",
                          borderRadius: 10,
                          border: `1px solid ${T.border}`,
                          background: screeningPerson ? T.surface : `${T.accent}10`,
                          color: screeningPerson ? T.muted : T.accent,
                          fontSize: FS.sm,
                          fontWeight: 700,
                          cursor: screeningPerson ? "wait" : "pointer",
                        }}
                      >
                        {screeningPerson ? "Screening..." : "Screen Person"}
                      </button>
                    </div>
                  )}

                  {/* Batch CSV Upload Section */}
                  {!isReadOnly && (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px", marginBottom: 10 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Batch CSV screening (up to 50)
                        </div>
                        <button
                          onClick={handleDownloadCsvTemplate}
                          style={{
                            padding: "4px 10px",
                            borderRadius: 8,
                            border: `1px solid ${T.border}`,
                            background: "transparent",
                            color: T.accent,
                            fontSize: 11,
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                        >
                          Download template
                        </button>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <label
                          style={{
                            flex: 1,
                            padding: "9px 12px",
                            borderRadius: 10,
                            border: `1px dashed ${T.border}`,
                            background: T.surface,
                            color: batchScreeningFile ? T.text : T.muted,
                            fontSize: FS.sm,
                            cursor: "pointer",
                            textAlign: "center",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {batchScreeningFile ? batchScreeningFile.name : "Choose CSV file..."}
                          <input
                            type="file"
                            accept=".csv,text/csv"
                            style={{ display: "none" }}
                            onChange={(e) => {
                              setBatchScreeningFile(e.target.files?.[0] || null);
                              setBatchScreeningResults([]);
                              setBatchScreeningError(null);
                            }}
                          />
                        </label>
                        <button
                          onClick={handleBatchScreenCsv}
                          disabled={screeningBatch || !batchScreeningFile}
                          style={{
                            padding: "9px 16px",
                            borderRadius: 10,
                            border: `1px solid ${T.border}`,
                            background: screeningBatch || !batchScreeningFile ? T.surface : `${T.accent}10`,
                            color: screeningBatch || !batchScreeningFile ? T.muted : T.accent,
                            fontSize: FS.sm,
                            fontWeight: 700,
                            cursor: screeningBatch || !batchScreeningFile ? "default" : "pointer",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {screeningBatch ? "Screening..." : "Screen batch"}
                        </button>
                      </div>
                      {batchScreeningError && (
                        <div style={{ marginTop: 8, padding: "8px 10px", borderRadius: 8, background: `${T.red}12`, border: `1px solid ${T.red}33`, color: T.red, fontSize: FS.sm }}>
                          {batchScreeningError}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Batch Results Table */}
                  {batchScreeningResults.length > 0 && (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px", marginBottom: 10 }}>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                        Batch results ({batchScreeningResults.length} screened)
                      </div>
                      <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: FS.sm }}>
                          <thead>
                            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                              <th style={{ padding: "6px 8px", textAlign: "left", color: T.muted, fontSize: 11, fontWeight: 600 }}>Name</th>
                              <th style={{ padding: "6px 8px", textAlign: "left", color: T.muted, fontSize: 11, fontWeight: 600 }}>Status</th>
                              <th style={{ padding: "6px 8px", textAlign: "right", color: T.muted, fontSize: 11, fontWeight: 600 }}>Score</th>
                              <th style={{ padding: "6px 8px", textAlign: "left", color: T.muted, fontSize: 11, fontWeight: 600 }}>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {batchScreeningResults.map((r, idx) => {
                              const status = String(r.screening_status || "UNKNOWN");
                              const statusColor =
                                status === "CLEAR" ? T.green
                                  : status === "MATCH" ? T.red
                                    : status === "PARTIAL_MATCH" ? T.amber
                                      : status === "ESCALATE" ? T.red
                                        : T.dim;
                              return (
                                <tr key={idx} style={{ borderBottom: `1px solid ${T.border}` }}>
                                  <td style={{ padding: "7px 8px", color: T.text, fontWeight: 600 }}>
                                    {String(r.person_name || "Unknown")}
                                    {Array.isArray(r.nationalities) && (r.nationalities as string[]).length > 0 && (
                                      <span style={{ color: T.dim, fontWeight: 400, marginLeft: 6 }}>
                                        {(r.nationalities as string[]).join(", ")}
                                      </span>
                                    )}
                                  </td>
                                  <td style={{ padding: "7px 8px" }}>
                                    <span
                                      style={{
                                        display: "inline-block",
                                        padding: "2px 8px",
                                        borderRadius: 999,
                                        background: `${statusColor}18`,
                                        border: `1px solid ${statusColor}44`,
                                        color: statusColor,
                                        fontSize: 11,
                                        fontWeight: 700,
                                      }}
                                    >
                                      {status.replaceAll("_", " ")}
                                    </span>
                                  </td>
                                  <td style={{ padding: "7px 8px", textAlign: "right", color: T.text, fontWeight: 600 }}>
                                    {typeof r.composite_score === "number" ? ((r.composite_score as number) * 100).toFixed(1) + "%" : "N/A"}
                                  </td>
                                  <td style={{ padding: "7px 8px", color: T.dim, fontSize: 11 }}>
                                    {String(r.recommended_action || "").substring(0, 60)}
                                    {String(r.recommended_action || "").length > 60 ? "..." : ""}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                      {/* Batch summary stats */}
                      <div style={{ display: "flex", gap: 12, marginTop: 10, paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
                        {["CLEAR", "MATCH", "PARTIAL_MATCH", "ESCALATE"].map((s) => {
                          const count = batchScreeningResults.filter((r) => r.screening_status === s).length;
                          if (count === 0) return null;
                          const color = s === "CLEAR" ? T.green : s === "MATCH" ? T.red : s === "PARTIAL_MATCH" ? T.amber : T.red;
                          return (
                            <div key={s} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                              <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
                              <span style={{ fontSize: 11, color: T.dim }}>{count} {s.replaceAll("_", " ").toLowerCase()}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {personScreeningResult && (() => {
                    const psStatus = String(personScreeningResult.screening_status || personScreeningResult.status || "UNKNOWN");
                    const psColor = psStatus === "CLEAR" ? T.green : psStatus === "MATCH" ? T.red : psStatus === "PARTIAL_MATCH" ? T.amber : T.red;
                    return (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "11px 12px", marginBottom: 10 }}>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                          Screening status
                        </div>
                        <div
                          className="inline-flex items-center gap-2 rounded-full"
                          style={{
                            padding: "6px 10px",
                            background: `${psColor}12`,
                            border: `1px solid ${psColor}33`,
                            color: psColor,
                            fontSize: FS.sm,
                            fontWeight: 700,
                          }}
                        >
                          <CheckCircle size={12} />
                          {psStatus.replaceAll("_", " ")}
                        </div>
                      </div>

                      {typeof personScreeningResult.composite_score === "number" && (
                        <div style={{ marginBottom: 10 }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                            Composite score
                          </div>
                          <div style={{ fontSize: FS.md, color: T.text, fontWeight: 700 }}>
                            {((personScreeningResult.composite_score as number) * 100).toFixed(1)}%
                          </div>
                        </div>
                      )}

                      {Array.isArray(personScreeningResult.matched_lists) && personScreeningResult.matched_lists.length > 0 && (
                        <div style={{ marginBottom: 10 }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                            Matched lists
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {(personScreeningResult.matched_lists as Array<Record<string, unknown>>).slice(0, 5).map((match, idx) => (
                              <div
                                key={idx}
                                className="rounded-lg"
                                style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "8px 10px" }}
                              >
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  {String(match.entity_name || "Unknown")}
                                </div>
                                <div style={{ fontSize: 11, color: T.dim, marginTop: 3 }}>
                                  Score: {typeof match.match_score === "number" ? (match.match_score * 100).toFixed(1) : "N/A"}%
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {!!(personScreeningResult.deemed_export || personScreeningResult.deemed_export_assessment) && (
                        <div
                          className="rounded-lg"
                          style={{
                            background: `${T.amber}12`,
                            border: `1px solid ${T.amber}33`,
                            padding: "10px 12px",
                            marginBottom: 10,
                          }}
                        >
                          <div style={{ fontSize: 11, color: T.amber, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                            Deemed export assessment
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.amber }}>
                            {typeof personScreeningResult.deemed_export === "object" && personScreeningResult.deemed_export
                              ? String((personScreeningResult.deemed_export as Record<string, unknown>).rationale || JSON.stringify(personScreeningResult.deemed_export))
                              : String(personScreeningResult.deemed_export_assessment || "")}
                          </div>
                        </div>
                      )}

                      {typeof personScreeningResult.recommended_action === "string" && (
                        <div>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
                            Recommended action
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>
                            {personScreeningResult.recommended_action}
                          </div>
                        </div>
                      )}
                    </div>
                    );
                  })()}

                  {personScreeningHistory.length > 0 && (
                    <div>
                      <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                        Screening history
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {personScreeningHistory.slice(0, 10).map((item, idx) => (
                          <div
                            key={idx}
                            className="rounded-lg"
                            style={{ background: T.raised, border: `1px solid ${T.border}`, padding: "8px 10px" }}
                          >
                            <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                              {String(item.person_name || "Unknown")} • {String(item.screening_status || item.status || "UNKNOWN").replaceAll("_", " ")}
                            </div>
                            <div style={{ fontSize: 11, color: T.dim, marginTop: 2 }}>
                              Score: {typeof item.composite_score === "number" ? ((item.composite_score as number) * 100).toFixed(1) : "N/A"}%
                              {item.screened_at ? ` • ${new Date(String(item.screened_at)).toLocaleDateString()}` : ""}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {personScreeningHistory.length === 0 && !personScreeningResult && (
                    <div className="rounded-lg" style={{ background: T.raised, border: `1px dashed ${T.border}`, padding: "12px", fontSize: FS.sm, color: T.muted }}>
                      No person screenings have been run for this case yet.
                    </div>
                  )}
                </div>
              )}

          {storyline && storyline.cards.length > 0 && (


            <RiskStoryline storyline={storyline} onAction={handleStorylineAction} />
          )}

          {showLegacyWhyBlock && whyItems.length > 0 && (
            <div className="mt-4 rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 14 }}>
              <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
                Why Helios made this recommendation
              </div>
              <div className="flex flex-col gap-2">
                {whyItems.map((item, index) => (
                  <div key={`${item}-${index}`} className="flex gap-2">
                    <span style={{ color: T.accent, fontSize: FS.sm, lineHeight: 1.5 }}>•</span>
                    <span style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5 }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {cal && (
            <div ref={actionPanelRef} className="mt-4">
              <ActionPanel case={c} />
            </div>
          )}

          <div className="flex gap-2 flex-wrap mt-4">
            <button
              onClick={handleDossier}
              disabled={generating || !cal}
              className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
              style={{
                padding: "8px 12px", fontSize: FS.sm,
                background: T.raised, color: T.text, borderColor: T.border,
                opacity: generating || !cal ? 0.5 : 1,
              }}
            >
              {generating ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
              {generating ? "Generating..." : "Generate Dossier"}
            </button>

            {showAiBriefPill && aiBriefSummary && (
              <button
                onClick={() => {
                  setShowAI(true);
                  setShowMoreActions(false);
                }}
                className="inline-flex items-center gap-2 rounded-lg border cursor-pointer"
                style={{
                  padding: "7px 10px",
                  minHeight: 36,
                  background: aiBriefVisual.background,
                  borderColor: aiBriefVisual.border,
                }}
                title={aiBriefDetail || aiBriefSummary}
              >
                <AIBriefIcon
                  size={12}
                  color={aiBriefVisual.color}
                  className={aiBriefStatus?.status === "running" ? "animate-spin" : ""}
                />
                <div className="flex flex-col items-start" style={{ lineHeight: 1.25 }}>
                  <span style={{ fontSize: FS.sm, color: aiBriefVisual.color, fontWeight: 700 }}>
                    {aiBriefSummary}
                  </span>
                  {aiBriefDetail && (
                    <span style={{ fontSize: 11, color: T.muted, textAlign: "left" }}>
                      {aiBriefDetail}
                    </span>
                  )}
                </div>
              </button>
            )}

            {!isReadOnly && (
              <button
                onClick={handleEnrich}
                disabled={enriching}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "8px 12px", fontSize: FS.sm,
                  background: T.raised, color: T.dim, borderColor: T.border,
                  opacity: enriching ? 0.5 : 1,
                }}
              >
                {enriching ? <Loader2 size={12} className="animate-spin" /> : <Radar size={12} />}
                {enriching ? "Enriching..." : enrichment ? "Re-Enrich" : "Run Screening"}
              </button>
            )}

            {!isReadOnly && (
              <>
                <button
                  onClick={() => void handleMonitor()}
                  disabled={monitorStatus?.status === "queued" || monitorStatus?.status === "running"}
                  className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                  style={{
                    padding: "8px 12px",
                    fontSize: FS.sm,
                    background: monitorStatus ? monitorVisual.background : T.surface,
                    color: monitorStatus ? monitorVisual.color : T.dim,
                    borderColor: monitorStatus ? monitorVisual.border : T.border,
                    opacity: monitorStatus?.status === "queued" || monitorStatus?.status === "running" ? 0.85 : 1,
                  }}
                >
                  {monitorStatus?.status === "running"
                    ? <Loader2 size={12} className="animate-spin" />
                    : monitorStatus?.status === "completed"
                      ? <CheckCircle size={12} />
                      : <Activity size={12} />}
                  {monitorStatus?.status === "queued"
                    ? "Queued"
                    : monitorStatus?.status === "running"
                      ? "Monitoring..."
                      : monitorStatus?.status === "completed"
                        ? "Check again"
                        : "Monitor now"}
                </button>

                {monitorStatus && (
                  <div
                    className="inline-flex items-center gap-2 rounded-lg"
                    style={{
                      padding: "7px 10px",
                      background: monitorVisual.background,
                      border: `1px solid ${monitorVisual.border}`,
                      minHeight: 36,
                    }}
                  >
                    <MonitorIcon
                      size={12}
                      color={monitorVisual.color}
                      className={monitorStatus.status === "running" ? "animate-spin" : ""}
                    />
                    <div className="flex flex-col" style={{ lineHeight: 1.25 }}>
                      <span style={{ fontSize: FS.sm, color: monitorVisual.color, fontWeight: 700 }}>
                        {monitorSummary}
                      </span>
                      {monitorDetail && (
                        <span style={{ fontSize: 11, color: T.muted }}>
                          {monitorDetail}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
            <div ref={moreActionsRef} style={{ position: "relative" }}>
              <button
                onClick={() => setShowMoreActions((current) => !current)}
                className="inline-flex items-center gap-1.5 rounded font-medium border cursor-pointer"
                style={{
                  padding: "8px 12px", fontSize: FS.sm,
                  background: showMoreActions ? `${T.accent}18` : T.surface, color: showMoreActions ? T.accent : T.dim, borderColor: showMoreActions ? `${T.accent}44` : T.border,
                }}
              >
                <MoreHorizontal size={12} /> More
              </button>

              {showMoreActions && (
                <div
                  className="rounded-lg"
                  style={{
                    position: "absolute",
                    top: "calc(100% + 8px)",
                    right: 0,
                    minWidth: 220,
                    background: T.surface,
                    border: `1px solid ${T.border}`,
                    boxShadow: "0 12px 32px rgba(0,0,0,0.35)",
                    padding: 6,
                    zIndex: 20,
                  }}
                >
                  <button
                    onClick={() => {
                      openEvidence(enrichment?.intel_summary ? "intel" : "findings");
                      setShowMoreActions(false);
                    }}
                    disabled={showStream || (!enrichment && isReadOnly)}
                    className="w-full text-left rounded border-none cursor-pointer"
                    style={{ padding: "9px 10px", background: "transparent", color: T.text, fontSize: FS.sm, opacity: showStream || (!enrichment && isReadOnly) ? 0.5 : 1 }}
                  >
                    {enrichment ? "Open Intel" : isReadOnly ? "Intel unavailable" : "Run Intel"}
                  </button>
                  <button
                    onClick={() => {
                      const nextOpen = !showMonitorHistory;
                      setShowMonitorHistory(nextOpen);
                      setShowSourceStatus(false);
                      setShowMoreActions(false);
                      if (nextOpen) {
                        void refreshMonitoringHistory();
                      }
                    }}
                    className="w-full text-left rounded border-none cursor-pointer"
                    style={{ padding: "9px 10px", background: "transparent", color: showMonitorHistory ? T.accent : T.text, fontSize: FS.sm }}
                  >
                    {monitoringHistoryLoading ? "Loading history..." : monitoringLaneCopy.title}
                  </button>
                  <button
                    onClick={() => {
                      setShowSourceStatus((current) => !current);
                      setShowMonitorHistory(false);
                      setShowMoreActions(false);
                    }}
                    disabled={!enrichment || showStream}
                    className="w-full text-left rounded border-none cursor-pointer"
                    style={{ padding: "9px 10px", background: "transparent", color: showSourceStatus ? T.accent : T.text, fontSize: FS.sm, opacity: !enrichment || showStream ? 0.5 : 1 }}
                  >
                    Source status
                  </button>
                  <button
                    onClick={() => {
                      setShowAI((current) => !current);
                      setShowMoreActions(false);
                    }}
                    className="w-full text-left rounded border-none cursor-pointer"
                    style={{ padding: "9px 10px", background: "transparent", color: T.text, fontSize: FS.sm }}
                  >
                    {showAI ? "Hide AI Analysis" : "Open AI Analysis"}
                  </button>
                  {!isReadOnly && hasApi ? (
                    <button
                      onClick={() => {
                        void handleRescore();
                        setShowMoreActions(false);
                      }}
                      disabled={rescoring}
                      className="w-full text-left rounded border-none cursor-pointer"
                      style={{ padding: "9px 10px", background: "transparent", color: T.text, fontSize: FS.sm, opacity: rescoring ? 0.6 : 1 }}
                    >
                      {rescoring ? "Re-Scoring..." : "Re-Score"}
                    </button>
                  ) : !isReadOnly ? (
                    <div style={{ padding: "9px 10px", color: T.muted, fontSize: FS.sm }}>
                      Re-Score unavailable offline
                    </div>
                  ) : null}
                </div>
              )}
            </div>

          </div>

          {(showMonitorHistory || (showSourceStatus && enrichment)) && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 mt-3">
              {showMonitorHistory && (
                <div
                  ref={monitorHistoryRef}
                  className="rounded-lg"
                  style={{
                    background: T.surface,
                    border: `1px solid ${T.border}`,
                    padding: 12,
                  }}
                >
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{monitoringLaneCopy.title}</div>
                      <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                        {monitoringLaneCopy.detail}
                      </div>
                    </div>
                    {monitoringHistory?.latest_score?.tier && (
                      <div
                        className="rounded-full px-2 py-1"
                        style={{ background: `${T.accent}12`, color: T.accent, fontSize: 11, fontWeight: 700 }}
                      >
                        Current {formatMonitorTierLabel(monitoringHistory.latest_score.tier)}
                      </div>
                    )}
                  </div>

                  {monitoringHistorySummary && (
                    <div
                      className="rounded-lg"
                      style={{
                        background: T.raised,
                        border: `1px solid ${T.border}`,
                        padding: 10,
                        marginBottom: 10,
                      }}
                    >
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
                        {[
                          { label: monitoringLaneCopy.runsLabel, value: monitoringHistorySummary.runs, color: T.text, bg: T.surface },
                          { label: monitoringLaneCopy.changedLabel, value: monitoringHistorySummary.changed, color: T.amber, bg: `${T.amber}12` },
                          { label: monitoringLaneCopy.findingsLabel, value: monitoringHistorySummary.newFindings, color: T.accent, bg: `${T.accent}12` },
                        ].map((card) => (
                          <div key={card.label} className="rounded-lg" style={{ background: card.bg, padding: "10px 8px", border: `1px solid ${T.border}` }}>
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{card.label}</div>
                            <div style={{ fontSize: FS.base, color: card.color, fontWeight: 700, marginTop: 4 }}>{card.value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div style={{ maxHeight: 360, overflow: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
                    {monitoringHistoryLoading && !monitoringHistory ? (
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 12, color: T.muted, fontSize: FS.sm }}>
                        {monitoringLaneCopy.loadingLabel}
                      </div>
                    ) : latestMonitoringChecks.length === 0 ? (
                      <div className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 12 }}>
                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{monitoringLaneCopy.emptyTitle}</div>
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4, lineHeight: 1.5 }}>
                          {monitoringLaneCopy.emptyDetail}
                        </div>
                      </div>
                    ) : latestMonitoringChecks.map((entry, index) => {
                      const tone = monitoringEntryTone(entry);
                      return (
                        <div
                          key={`${entry.checked_at || "check"}-${index}`}
                          className="rounded-lg"
                          style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 10 }}
                        >
                          <div className="flex items-start justify-between gap-3 flex-wrap">
                            <div>
                              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                {entry.checked_at
                                  ? new Date(entry.checked_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
                                  : "Recent check"}
                              </div>
                              <div style={{ fontSize: 11, color: T.muted, marginTop: 3 }}>
                                {formatMonitorTierLabel(entry.previous_risk)} {"->"} {formatMonitorTierLabel(entry.current_risk)}
                              </div>
                            </div>
                            <span
                              style={{
                                padding: "4px 8px",
                                borderRadius: 999,
                                fontSize: 11,
                                color: tone.color,
                                background: tone.background,
                                border: `1px solid ${tone.border}`,
                                fontWeight: 700,
                              }}
                            >
                              {tone.label}
                            </span>
                          </div>

                          <div className="flex items-center gap-3 flex-wrap" style={{ marginTop: 8 }}>
                            <span style={{ fontSize: FS.sm, color: T.dim }}>
                              {monitoringLaneCopy.findingsText(entry.new_findings_count ?? 0)}
                            </span>
                            <span style={{ fontSize: FS.sm, color: T.dim }}>
                              {(entry.resolved_findings_count ?? 0) === 1 ? "1 resolved" : `${entry.resolved_findings_count ?? 0} resolved`}
                            </span>
                            {entry.risk_changed ? (
                              <span style={{ fontSize: FS.sm, color: T.amber, fontWeight: 600 }}>
                                {monitoringLaneCopy.shiftedText}
                              </span>
                            ) : (
                              <span style={{ fontSize: FS.sm, color: T.green, fontWeight: 600 }}>
                                {monitoringLaneCopy.stableText}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {showSourceStatus && enrichment && (
                <div
                  ref={sourceStatusRef}
                  className="rounded-lg"
                  style={{
                    background: T.surface,
                    border: `1px solid ${T.border}`,
                    padding: 12,
                  }}
                >
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div>
                      <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>Data sources</div>
                      <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                        Fast trust readout for the enrichment connectors used on this case
                      </div>
                    </div>
                    <div className="flex gap-2">
                      {([
                        ["green", sourceStatusSummary.green, T.green],
                        ["yellow", sourceStatusSummary.yellow, T.amber],
                        ["red", sourceStatusSummary.red, T.red],
                      ] as const).map(([key, count, color]) => (
                        <div key={key} className="inline-flex items-center gap-1 rounded-full px-2 py-1" style={{ background: `${color}14`, color, fontSize: 11, fontWeight: 700 }}>
                          <span style={{ width: 7, height: 7, borderRadius: 999, background: color, display: "inline-block" }} />
                          {count}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div
                    className="rounded-lg"
                    style={{
                      background: T.raised,
                      border: `1px solid ${T.border}`,
                      padding: 10,
                      marginBottom: 10,
                    }}
                  >
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
                      {[
                        { label: "Signal", value: sourceStatusSections.signal.length, color: T.green, bg: `${T.green}12` },
                        { label: "Clear", value: sourceStatusSections.clear.length, color: T.amber, bg: `${T.amber}12` },
                        { label: "Issues", value: sourceStatusSections.issue.length, color: T.red, bg: `${T.red}12` },
                        { label: "Runtime", value: `${(enrichment.total_elapsed_ms / 1000).toFixed(1)}s`, color: T.accent, bg: `${T.accent}12` },
                      ].map((card) => (
                        <div key={card.label} className="rounded-lg" style={{ background: card.bg, padding: "10px 8px", border: `1px solid ${card.color}24` }}>
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>{card.label}</div>
                          <div style={{ fontSize: FS.base, color: card.color, fontWeight: 700, marginTop: 4 }}>{card.value}</div>
                        </div>
                      ))}
                    </div>
                    {sourceCategoryCounts.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                        {sourceCategoryCounts.slice(0, 6).map(([category, count]) => (
                          <span
                            key={category}
                            style={{
                              padding: "4px 8px",
                              borderRadius: 999,
                              fontSize: 11,
                              color: T.dim,
                              background: T.surface,
                              border: `1px solid ${T.border}`,
                              fontWeight: 600,
                            }}
                          >
                            {category} {count}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div style={{ maxHeight: 360, overflow: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
                    {[
                      {
                        key: "signal",
                        title: "What moved the case",
                        description: "Connectors that returned evidence or findings.",
                        items: sourceStatusSections.signal,
                      },
                      {
                        key: "issue",
                        title: "Attention needed",
                        description: "Connectors that errored or need a rerun.",
                        items: sourceStatusSections.issue,
                      },
                      {
                        key: "clear",
                        title: "Checked clear",
                        description: "Connectors that ran clean with no material return.",
                        items: sourceStatusSections.clear,
                      },
                    ].map((section) => (
                      section.items.length > 0 ? (
                        <div key={section.key} className="rounded-lg" style={{ background: T.raised, border: `1px solid ${T.border}`, padding: 10 }}>
                          <div style={{ marginBottom: 8 }}>
                            <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>{section.title}</div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{section.description}</div>
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {section.items.map((entry) => (
                              <div
                                key={entry.name}
                                className="rounded-lg"
                                style={{ background: T.surface, border: `1px solid ${T.border}`, padding: "9px 10px" }}
                              >
                                <div className="flex items-start gap-2">
                                  <span style={{ width: 8, height: 8, borderRadius: 999, background: entry.color, display: "inline-block", flexShrink: 0, marginTop: 6 }} />
                                  <div style={{ flex: 1, minWidth: 0 }}>
                                    <div className="flex items-center gap-6 justify-between" style={{ flexWrap: "wrap" }}>
                                      <div style={{ minWidth: 0 }}>
                                        <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>{connectorDisplayName(entry.name)}</div>
                                        <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{entry.description}</div>
                                      </div>
                                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                                        <span style={{ padding: "4px 8px", borderRadius: 999, fontSize: 11, color: entry.color, background: `${entry.color}14`, fontWeight: 700 }}>
                                          {entry.label}
                                        </span>
                                        <span style={{ padding: "4px 8px", borderRadius: 999, fontSize: 11, color: T.dim, background: T.bg, fontWeight: 600 }}>
                                          {entry.category}
                                        </span>
                                      </div>
                                    </div>
                                    <div className="flex items-center justify-between gap-3" style={{ marginTop: 8, flexWrap: "wrap" }}>
                                      <div style={{ fontSize: FS.sm, color: T.text }}>{entry.findingsSummary}</div>
                                      <div className="font-mono" style={{ fontSize: 11, color: T.muted }}>
                                        {entry.status.elapsed_ms > 0 ? `${(entry.status.elapsed_ms / 1000).toFixed(1)}s` : "--"}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {error && (
            <div
              className="flex items-center gap-2 mt-3 rounded"
              style={{ padding: "8px 12px", background: T.redBg, border: `1px solid ${T.red}33` }}
            >
              <XCircle size={12} color={T.red} className="shrink-0" />
              <span style={{ fontSize: FS.sm, color: T.red }}>{error}</span>
            </div>
          )}
        </div>

        {showStream && enriching && (
          <div className="mt-3">
            <EnrichmentStream
              caseId={c.id}
              apiBase={import.meta.env.VITE_API_URL ?? ""}
              onComplete={handleStreamComplete}
            />
          </div>
        )}

        {showAI && (
          <div className="mt-3">
            <AIAnalysisPanel caseId={c.id} vendorName={c.name} />
          </div>
        )}

        <div className="mt-3 rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 12 }}>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>Analyst views</div>
              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 2 }}>
                Switch between the decision brief, evidence collection, and model-specific reasoning.
              </div>
            </div>
            <div className="flex gap-2 flex-wrap">
              {([
                { id: "decision" as const, label: "Decision", icon: Activity },
                { id: "evidence" as const, label: "Evidence", icon: Radar },
                { id: "model" as const, label: "Model", icon: Brain },
              ]).map((view) => {
                const Icon = view.icon;
                const active = analystView === view.id;
                return (
                  <button
                    key={view.id}
                    onClick={() => {
                      setAnalystView(view.id);
                      if (view.id === "model") {
                        setEvidenceTab("model");
                      } else if (view.id === "evidence" && evidenceTab === "model") {
                        setEvidenceTab(enrichment ? defaultEvidenceTab(enrichment) : "findings");
                      }
                    }}
                    className="inline-flex items-center gap-2 rounded-lg border cursor-pointer"
                    style={{
                      padding: "9px 12px",
                      background: active ? `${T.accent}18` : T.raised,
                      color: active ? T.accent : T.dim,
                      borderColor: active ? `${T.accent}44` : T.border,
                      fontSize: FS.sm,
                      fontWeight: 700,
                    }}
                  >
                    <Icon size={12} />
                    {view.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {analystView === "decision" && (
          <div className="flex flex-col gap-3 mt-3">
            {cal && (
              <ExpandableSection
                title="Regulatory Gates"
                badge={cal.regulatoryFindings && cal.regulatoryFindings.length > 0 ? (
                  <span style={{ fontSize: FS.sm, background: T.accent + "22", color: T.accent, padding: "2px 6px", borderRadius: 4, fontWeight: 600 }}>
                    {cal.regulatoryFindings.length} triggered
                  </span>
                ) : null}
                defaultOpen={cal.regulatoryStatus === "NON_COMPLIANT" || cal.regulatoryStatus === "REQUIRES_REVIEW"}
              >
                <RegulatoryPanel cal={cal} />
              </ExpandableSection>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <div className="flex flex-col gap-3">
                <div className="rounded-lg p-5" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                    Bayesian Posterior
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 10 }}>
                    What the evidence suggests, given the statistical model
                  </div>
                  {cal ? (
                    <div className="flex flex-col items-center">
                      <div className="mb-3">
                        <TierBadge tier={cal.tier} />
                      </div>
                      <div style={{ transform: "scale(1.3)", transformOrigin: "center", marginBottom: 12, marginTop: 4 }}>
                        <Gauge value={cal.p} lo={cal.lo} hi={cal.hi} />
                      </div>
                      <div className="flex gap-4 mt-2">
                        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                          Coverage {Math.round(cal.cov * 100)}%
                        </span>
                        <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                          Confidence {Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)))}%
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-8" style={{ fontSize: FS.sm, color: T.muted }}>
                      Scoring in progress...
                    </div>
                  )}
                </div>

                {cal && c.history && c.history.length > 0 && (
                  <ScoreHistory history={c.history} current={{ p: cal.p, tier: cal.tier, ts: new Date().toISOString() }} />
                )}

                {cal && (
                  <ExpandableSection
                    title="Risk Factor Contributions"
                    defaultOpen={false}
                  >
                    <div style={{ background: T.surface, padding: "8px 0" }}>
                    {sortedCt.map((ct, i) => (
                      <div
                        key={i}
                        style={{ padding: "8px 0", borderBottom: i < sortedCt.length - 1 ? `1px solid ${T.border}` : "none" }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium" style={{ fontSize: FS.sm, color: T.text }}>{formatFactorLabel(ct.n)}</span>
                          <div className="flex items-center gap-3">
                            <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                              w={ct.c.toFixed(1)}
                            </span>
                            <span
                              className="font-mono font-semibold"
                              style={{ fontSize: FS.sm, color: ct.s > 0 ? T.red : ct.s < 0 ? T.green : T.muted }}
                            >
                              {fmtContrib(ct.s)}
                            </span>
                          </div>
                        </div>
                        <ContribBar value={ct.raw} color={ct.raw > 0.7 ? T.red : ct.raw > 0.4 ? T.amber : T.green} />
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 3 }}>{formatFindingCopy(ct.d)}</div>
                      </div>
                    ))}
                    </div>
                  </ExpandableSection>
                )}
              </div>

              <div className="flex flex-col gap-3">
                <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                  <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                    Case Details
                  </div>
                  {[
                    ["Vendor", c.name],
                    ["Country", c.cc],
                    ["Case ID", c.id],
                    ["Date", c.date],
                    ["Status", c.cal ? "Complete" : "Scoring"],
                    ...(cal
                      ? [
                          ["Coverage", Math.round(cal.cov * 100) + "%"],
                          ["Confidence", Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100))) + "%"],
                        ]
                      : []),
                  ].map(([k, v], i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between"
                      style={{ padding: "5px 0", borderBottom: `1px solid ${T.border}` }}
                    >
                      <span style={{ fontSize: FS.sm, color: T.muted }}>{k}</span>
                      <span className="font-mono" style={{ fontSize: FS.sm, color: T.dim }}>{v}</span>
                    </div>
                  ))}

                  <div style={{ padding: "10px 0 0", marginTop: 6 }}>
                    <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                      Policy Rubric
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 6 }}>
                      What procurement policy prescribes for this vendor profile
                    </div>
                    <div className="flex items-baseline gap-1 mb-2">
                      <span className="font-mono font-bold" style={{ fontSize: 22, color: T.text }}>{c.sc}</span>
                      <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>/100</span>
                      <span className="font-mono ml-2" style={{ fontSize: FS.sm, color: T.muted }}>
                        ({Math.min(99, Math.max(0, Math.round((c.conf || 0.85) * 100)))}% confidence)
                      </span>
                    </div>
                    <div className="w-full rounded-full overflow-hidden" style={{ height: 4, background: T.border }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${c.sc}%`, background: c.sc > 70 ? T.red : c.sc > 40 ? T.amber : T.green }}
                      />
                    </div>
                    {cal && (() => {
                      const bayesPct = Math.round(cal.p * 100);
                      const divergence = Math.abs(bayesPct - c.sc);
                      if (divergence > 15) {
                        return (
                          <div
                            className="flex items-center gap-1.5 mt-2 rounded"
                            style={{ padding: "4px 8px", background: T.amberBg, border: `1px solid ${T.amber}33` }}
                          >
                            <AlertTriangle size={10} color={T.amber} className="shrink-0" />
                            <span style={{ fontSize: FS.sm, color: T.amber }}>
                              Consensus break: Bayesian ({bayesPct}%) and Policy Rubric ({c.sc}) diverge by {divergence} points
                            </span>
                          </div>
                        );
                      }
                      return null;
                    })()}
                  </div>
                </div>

                {supplierPassport && (
                  <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
                      <div>
                        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                          Supplier Passport
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                          Portable trust artifact for control-path, identity, and connector coverage.
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          onClick={() => downloadSupplierPassportJson(supplierPassport)}
                          className="rounded border cursor-pointer"
                          style={{
                            padding: "6px 10px",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            color: T.accent,
                            background: `${T.accent}12`,
                            borderColor: `${T.accent}33`,
                          }}
                        >
                          Download JSON
                        </button>
                        <span
                          className="rounded-full"
                          style={{
                            padding: "5px 10px",
                            fontSize: FS.sm,
                            fontWeight: 700,
                            color: supplierPassportTone.color,
                            background: supplierPassportTone.background,
                            border: `1px solid ${supplierPassportTone.border}`,
                          }}
                        >
                          {formatPassportPosture(supplierPassport.posture)}
                        </span>
                      </div>
                    </div>

                    <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", marginBottom: 12 }}>
                      {[
                        { label: "Connectors with data", value: supplierPassport.identity.connectors_with_data, tone: T.accent },
                        { label: "Findings", value: supplierPassport.identity.findings_total, tone: T.text },
                        { label: "Control paths", value: supplierPassport.graph.control_paths.length, tone: T.amber },
                        { label: "Artifacts", value: supplierPassport.artifacts.count, tone: T.green },
                        { label: "Contradicted claims", value: supplierPassport.graph.claim_health.contradicted_claims, tone: supplierPassport.graph.claim_health.contradicted_claims > 0 ? T.red : T.green },
                        { label: "Stale paths", value: supplierPassport.graph.claim_health.stale_paths, tone: supplierPassport.graph.claim_health.stale_paths > 0 ? T.amber : T.green },
                      ].map((item) => (
                        <div
                          key={item.label}
                          className="rounded-lg"
                          style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}` }}
                        >
                          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                            {item.label}
                          </div>
                          <div style={{ fontSize: 22, fontWeight: 700, color: item.tone, marginTop: 4, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                            {item.value}
                          </div>
                        </div>
                      ))}
                    </div>

                    {supplierPassportOfficialCorroboration && (
                      <div
                        className="rounded-lg"
                        style={{
                          padding: 12,
                          background: supplierPassportOfficialTone.background,
                          border: `1px solid ${supplierPassportOfficialTone.border}`,
                          marginBottom: 12,
                        }}
                      >
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div>
                            <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                              Official Corroboration
                            </div>
                            <div style={{ fontSize: 15, color: T.text, fontWeight: 700, marginTop: 6 }}>
                              {supplierPassportOfficialCorroboration.coverage_label || "No official corroboration captured"}
                            </div>
                            <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                              {`${supplierPassportOfficialCorroboration.core_official_identifier_count ?? 0} core official identifiers verified`}
                              {` · ${supplierPassportOfficialCorroboration.relevant_official_connectors_with_data ?? supplierPassportOfficialCorroboration.official_connectors_with_data ?? 0}/${supplierPassportOfficialCorroboration.relevant_official_connector_count ?? supplierPassportOfficialCorroboration.official_connector_count ?? 0} relevant official connectors returned data`}
                            </div>
                          </div>
                          <span
                            className="rounded-full"
                            style={{
                              padding: "4px 10px",
                              fontSize: 11,
                              fontWeight: 700,
                              color: supplierPassportOfficialTone.color,
                              background: `${supplierPassportOfficialTone.color}12`,
                              border: `1px solid ${supplierPassportOfficialTone.border}`,
                              textTransform: "uppercase",
                              letterSpacing: "0.04em",
                            }}
                          >
                            {String(supplierPassportOfficialCorroboration.coverage_level || "missing").replaceAll("_", " ")}
                          </span>
                        </div>

                        {supplierPassportOfficialIdentifiers.length > 0 && (
                          <div className="flex flex-wrap gap-2" style={{ marginTop: 10 }}>
                            {supplierPassportOfficialIdentifiers.map((field) => (
                              <span
                                key={field}
                                className="rounded-full"
                                style={{
                                  padding: "4px 10px",
                                  fontSize: 11,
                                  fontWeight: 700,
                                  color: T.text,
                                  background: T.surface,
                                  border: `1px solid ${T.border}`,
                                }}
                              >
                                {officialFieldLabel(field)}
                              </span>
                            ))}
                          </div>
                        )}

                        {supplierPassportPublicCaptureFields.length > 0 && (
                          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 10, lineHeight: 1.5 }}>
                            Public-only captured fields: {supplierPassportPublicCaptureFields.map((field) => officialFieldLabel(field)).join(", ")}
                          </div>
                        )}

                        {supplierPassportCountryHints.length > 0 && (
                          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8, lineHeight: 1.5 }}>
                            Jurisdiction hints: {supplierPassportCountryHints.map((hint) => formatCountryHint(hint)).join(", ")}
                          </div>
                        )}

                        {supplierPassportBlockedOfficialConnectors.length > 0 && (
                          <div style={{ fontSize: FS.sm, color: T.amber, marginTop: 8, lineHeight: 1.5 }}>
                            Relevant blocked official checks: {supplierPassportBlockedOfficialConnectors.map((connector) => connector.label || connectorDisplayName(String(connector.source || "official_registry"))).join(", ")}
                          </div>
                        )}
                      </div>
                    )}

                    <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                      <div className="rounded-lg" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}` }}>
                        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                          Identity Anchors
                        </div>
                        {supplierPassportIdentityEntries.length > 0 ? (
                          <div className="flex flex-col gap-2" style={{ marginTop: 10 }}>
                            {supplierPassportIdentityEntries.map(([key, status]) => {
                              const tone = identifierStateTone(status);
                              const primaryValue = status?.value !== null && status?.value !== undefined && String(status.value).trim() !== ""
                                ? String(status.value)
                                : identifierStateLabel(status);
                              const metaParts = [
                                status?.source ? connectorDisplayName(String(status.source)) : "",
                                status?.state === "unverified" && status?.reason ? String(status.reason) : "",
                                status?.next_access_time ? `Retry after ${String(status.next_access_time)}` : "",
                              ].filter(Boolean);
                              return (
                              <div key={key} className="flex items-start justify-between gap-3">
                                <span style={{ fontSize: FS.sm, color: T.muted }}>{key.toUpperCase()}</span>
                                <div style={{ textAlign: "right" }}>
                                  <div className="flex items-center justify-end gap-2 flex-wrap">
                                    <span className="font-mono" style={{ fontSize: FS.sm, color: T.text }}>
                                      {primaryValue}
                                    </span>
                                    <span
                                      className="rounded-full"
                                      style={{
                                        padding: "3px 8px",
                                        fontSize: 11,
                                        fontWeight: 700,
                                        color: tone.color,
                                        background: tone.background,
                                        border: `1px solid ${tone.border}`,
                                      }}
                                    >
                                      {identifierStateLabel(status)}
                                    </span>
                                  </div>
                                  {metaParts.length > 0 && (
                                    <div style={{ fontSize: 11, color: T.dim, marginTop: 4, lineHeight: 1.4, maxWidth: 320 }}>
                                      {metaParts.join(" · ")}
                                    </div>
                                  )}
                                </div>
                              </div>
                            )})}
                          </div>
                        ) : (
                          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 10 }}>
                            Awaiting stronger identifier coverage.
                          </div>
                        )}
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 10 }}>
                          {supplierPassport.identity.overall_risk ? `Overall risk: ${supplierPassport.identity.overall_risk}` : "No connector-level overall risk label yet."}
                        </div>
                      </div>

                      <div className="rounded-lg" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}` }}>
                        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                          Workflow Control
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.text, marginTop: 10, fontWeight: 600 }}>
                          {supplierPassportWorkflowLabel || workflowControlSummary?.label || "Awaiting analyst control summary"}
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
                          {supplierPassportWorkflowBasis || workflowControlSummary?.review_basis || "Control rationale will tighten as ownership and intermediary evidence lands."}
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 8 }}>
                          Owner: {supplierPassportWorkflowOwner || workflowControlSummary?.action_owner || "Analyst"}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-lg" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}`, marginTop: 12 }}>
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <div>
                          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                            Decision Tribunal
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                            Deterministic competing views for approve, watch, and deny.
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: tribunalViewTone(supplierPassport.tribunal.recommended_view).color, background: tribunalViewTone(supplierPassport.tribunal.recommended_view).background, border: `1px solid ${tribunalViewTone(supplierPassport.tribunal.recommended_view).border}` }}>
                            Recommended: {supplierPassport.tribunal.recommended_label}
                          </span>
                          <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.text, background: T.surface, border: `1px solid ${T.border}` }}>
                            Consensus: {supplierPassport.tribunal.consensus_level}
                          </span>
                        </div>
                      </div>
                      <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 8 }}>
                        Decision gap: {supplierPassport.tribunal.decision_gap.toFixed(2)} · Freshest control-path evidence: {formatGraphTimestamp(supplierPassport.graph.claim_health.freshest_observation_at)}
                      </div>
                      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", marginTop: 12 }}>
                        {supplierPassportTribunalViews.map((view) => {
                          const tone = tribunalViewTone(view.stance);
                          return (
                            <div key={view.stance} className="rounded-lg" style={{ padding: 12, background: T.surface, border: `1px solid ${tone.border}` }}>
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div style={{ fontSize: FS.sm, color: tone.color, fontWeight: 700 }}>
                                    {view.label}
                                  </div>
                                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                                    Owner: {view.owner}
                                  </div>
                                </div>
                                <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: tone.color, background: tone.background }}>
                                  {(view.score * 100).toFixed(0)}%
                                </span>
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.text, marginTop: 10, lineHeight: 1.5 }}>
                                {view.summary}
                              </div>
                              {view.reasons.length > 0 && (
                                <div className="flex flex-col gap-2" style={{ marginTop: 10 }}>
                                  {view.reasons.slice(0, 3).map((reason) => (
                                    <div key={reason} style={{ fontSize: FS.sm, color: T.muted }}>
                                      • {reason}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="rounded-lg" style={{ padding: 12, background: T.raised, border: `1px solid ${T.border}`, marginTop: 12 }}>
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                          Top Control Paths
                        </div>
                        <div style={{ fontSize: FS.sm, color: T.muted }}>
                          {supplierPassport.graph.entity_count} entities · {supplierPassport.graph.relationship_count} relationships
                        </div>
                      </div>
                      {supplierPassportControlPaths.length > 0 ? (
                        <div className="flex flex-col gap-3" style={{ marginTop: 10 }}>
                          {supplierPassportControlPaths.map((path, index) => (
                            <div
                              key={`${path.rel_type}-${path.source_entity_id || index}-${path.target_entity_id || index}`}
                              className="rounded-lg"
                              style={{ padding: 12, background: T.surface, border: `1px solid ${T.border}` }}
                            >
                              <div className="flex items-start justify-between gap-3 flex-wrap">
                                <div>
                                  <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>
                                    {path.source_name || "Unknown source"} → {path.target_name || "Unknown target"}
                                  </div>
                                  <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                                    {formatRelationshipLabel(path.rel_type)}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.accent, background: `${T.accent}15` }}>
                                    {(path.confidence * 100).toFixed(0)}% conf
                                  </span>
                                  <span className="rounded-full" style={{ padding: "4px 8px", fontSize: 11, fontWeight: 700, color: T.amber, background: `${T.amber}15` }}>
                                    {path.corroboration_count} source{path.corroboration_count === 1 ? "" : "s"}
                                  </span>
                                </div>
                              </div>
                              <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 8 }}>
                                {path.data_sources.length > 0
                                  ? path.data_sources.map((sourceName) => connectorDisplayName(sourceName)).join(" • ")
                                  : "Connector provenance pending"}
                              </div>
                              {path.evidence_refs.length > 0 && (
                                <div className="flex flex-col gap-1" style={{ marginTop: 8 }}>
                                  {path.evidence_refs.map((ref) => (
                                    <div key={`${ref.title}-${ref.url || ref.artifact_ref || "ref"}`} style={{ fontSize: FS.sm, color: T.muted }}>
                                      {ref.url ? (
                                        <a href={ref.url} target="_blank" rel="noreferrer" style={{ color: T.accent, textDecoration: "none" }}>
                                          {ref.title}
                                        </a>
                                      ) : (
                                        <span style={{ color: T.text }}>{ref.title}</span>
                                      )}
                                      {ref.source ? ` · ${connectorDisplayName(ref.source)}` : ""}
                                      {ref.artifact_ref ? ` · ${ref.artifact_ref}` : ""}
                                    </div>
                                  ))}
                                </div>
                              )}
                              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
                                Seen {formatGraphTimestamp(path.first_seen_at)} to {formatGraphTimestamp(path.last_seen_at)}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 10 }}>
                          No control-path edges yet. This case is a benchmark candidate for ownership and intermediary expansion.
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {cal?.miv && cal.miv.length > 0 && (
                  <ExpandableSection
                    title="Recommended Data Collection"
                    badge={cal.miv.length > 0 ? (
                      <span style={{ fontSize: FS.sm, background: T.accent + "22", color: T.accent, padding: "2px 6px", borderRadius: 4, fontWeight: 600 }}>
                        {cal.miv.length} items
                      </span>
                    ) : null}
                    defaultOpen={false}
                  >
                    <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    {cal.miv.map((m, i) => (
                      <div
                        key={i}
                        className="rounded"
                        style={{ padding: 10, background: T.raised, border: `1px solid ${T.border}`, marginTop: i > 0 ? 8 : 0 }}
                      >
                        <div className="font-medium" style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.4 }}>{m.t}</div>
                        <div className="flex gap-3 mt-1.5">
                          <span className="font-mono" style={{ fontSize: FS.sm, color: T.accent }}>
                            {m.i > 0 ? "\u2212" : "+"}{m.i.toFixed(1)} pp impact
                          </span>
                          <span className="font-mono" style={{ fontSize: FS.sm, color: T.muted }}>
                            {Math.round(m.tp * 100)}% tier change probability
                          </span>
                        </div>
                      </div>
                    ))}
                    </div>
                  </ExpandableSection>
                )}

                {/* LEVEL 2: Network Risk Propagation (collapsible) */}
                {networkRisk && networkRisk.network_risk_score > 0 && (
                  <ExpandableSection
                    title="Network Risk"
                    badge={
                      <span style={{ fontSize: FS.sm, fontWeight: 600, color: networkRisk.network_risk_level === "critical" ? T.red : networkRisk.network_risk_level === "high" ? T.amber : "#eab308" }}>
                        +{networkRisk.network_risk_score.toFixed(1)}
                      </span>
                    }
                    defaultOpen={networkRisk.network_risk_level === "critical" || networkRisk.network_risk_level === "high"}
                  >
                    <div className="rounded-lg p-4" style={{ background: T.surface, border: `1px solid ${T.border}` }}>
                    <div className="flex items-center gap-2 mb-3">
                      <Network size={13} color={
                        networkRisk.network_risk_level === "critical" ? T.red :
                        networkRisk.network_risk_level === "high" ? T.amber :
                        networkRisk.network_risk_level === "medium" ? "#eab308" : T.muted
                      } />
                      <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                        Network Risk Propagation
                      </div>
                    </div>
                    <div className="flex items-baseline gap-2 mb-2">
                      <span className="font-mono font-bold" style={{
                        fontSize: 20,
                        color: networkRisk.network_risk_level === "critical" ? T.red :
                               networkRisk.network_risk_level === "high" ? T.amber :
                               networkRisk.network_risk_level === "medium" ? "#eab308" : T.green,
                      }}>
                        +{networkRisk.network_risk_score.toFixed(1)}
                      </span>
                      <span className="font-mono uppercase" style={{
                        fontSize: FS.sm, padding: "1px 6px", borderRadius: 4,
                        background: networkRisk.network_risk_level === "critical" ? `${T.red}22` :
                                    networkRisk.network_risk_level === "high" ? `${T.amber}22` :
                                    networkRisk.network_risk_level === "medium" ? "#eab30822" : `${T.green}22`,
                        color: networkRisk.network_risk_level === "critical" ? T.red :
                               networkRisk.network_risk_level === "high" ? T.amber :
                               networkRisk.network_risk_level === "medium" ? "#eab308" : T.green,
                      }}>
                        {networkRisk.network_risk_level}
                      </span>
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.muted, marginBottom: 8 }}>
                      Risk modifier from {networkRisk.neighbor_count} connected entities
                      {networkRisk.high_risk_neighbors > 0 && (
                        <span style={{ color: T.amber }}> ({networkRisk.high_risk_neighbors} high-risk)</span>
                      )}
                    </div>
                    {networkRisk.risk_contributors && networkRisk.risk_contributors.length > 0 && (
                      <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
                        <div style={{ fontSize: 9, color: T.muted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                          Top Risk Contributors
                        </div>
                        {networkRisk.risk_contributors.slice(0, 5).map((rc, i: number) => (
                          <div key={i} className="flex items-center justify-between" style={{
                            padding: "3px 0", borderBottom: i < Math.min(4, networkRisk.risk_contributors!.length - 1) ? `1px solid ${T.border}` : "none",
                          }}>
                            <span style={{ fontSize: FS.sm, color: T.dim }}>{rc.entity_name}</span>
                            <div className="flex items-center gap-2">
                              <span className="font-mono" style={{ fontSize: 10, color: T.muted }}>
                                {formatRelationshipLabel(rc.rel_type ?? rc.relationship ?? "related")}
                              </span>
                              <span className="font-mono" style={{
                                fontSize: 10,
                                color: (rc.risk_score_pct ?? 0) >= 40 ? T.red : (rc.risk_score_pct ?? 0) >= 25 ? T.amber : T.muted,
                              }}>
                                {(rc.risk_score_pct ?? 0).toFixed(0)}%
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    </div>
                  </ExpandableSection>
                )}
              </div>
            </div>
          </div>
        )}

        {(analystView === "evidence" || analystView === "model") && (
          <div ref={evidenceRef} className="mt-3 rounded-lg" style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 14 }}>
            <div className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
              {analystView === "model" ? "Model" : "Evidence"}
            </div>
            <div style={{ fontSize: FS.sm, color: T.muted, marginTop: 4 }}>
              {analystView === "model"
                ? "Model-specific reasoning, confidence, and top contribution drivers."
                : "Connector outputs, findings, timelines, and graph evidence behind the decision."}
            </div>
            <div className="flex gap-2 flex-wrap mt-3">
              {evidenceTabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => openEvidence(tab.id)}
                  disabled={tab.disabled}
                  className="rounded font-medium border cursor-pointer"
                  style={{
                    padding: "7px 10px",
                    fontSize: FS.sm,
                    background: evidenceTab === tab.id ? T.accent + "18" : T.raised,
                    color: evidenceTab === tab.id ? T.accent : tab.disabled ? T.muted : T.dim,
                    borderColor: evidenceTab === tab.id ? T.accent + "44" : T.border,
                    opacity: tab.disabled ? 0.55 : 1,
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="mt-4">
              {loadingEnrichment && evidenceTab !== "model" && (
                <div className="flex items-center justify-center py-8">
                  <LoadingSpinner />
                </div>
              )}

              {evidenceTab === "model" && cal && (
                <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
                  <div className="rounded-lg p-4" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                    <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: FS.sm, color: T.muted }}>
                      Model View
                    </div>
                    <div style={{ fontSize: FS.xl, fontWeight: 700, color: T.text, marginBottom: 4, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                      {Math.round(cal.p * 100)}%
                    </div>
                    <div style={{ fontSize: FS.sm, color: T.dim, lineHeight: 1.5, fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
                      {probLabel(cal.p)}. Coverage {Math.round(cal.cov * 100)}%. Confidence {Math.min(99, Math.max(0, Math.round((cal.mc || 0.85) * 100)))}%.
                    </div>
                  </div>
                  <div className="rounded-lg p-4" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                    <div className="font-semibold uppercase tracking-wider mb-3" style={{ fontSize: FS.sm, color: T.muted }}>
                      Top Model Factors
                    </div>
                    <div className="flex flex-col gap-3">
                      {sortedCt.slice(0, 4).map((factor, index) => (
                        <div key={`${factor.n}-${index}`} style={{ paddingBottom: index < 3 ? 12 : 0, borderBottom: index < 3 ? `1px solid ${T.border}` : "none" }}>
                          <div className="flex items-center justify-between gap-3">
                            <span style={{ fontSize: FS.sm, color: T.text, fontWeight: 600 }}>{formatFactorLabel(factor.n)}</span>
                            <span style={{ fontSize: FS.sm, color: factor.s > 0 ? T.red : factor.s < 0 ? T.green : T.muted, fontFamily: "monospace" }}>
                              {fmtContrib(factor.s)}
                            </span>
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>{formatFindingCopy(factor.d)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {evidenceTab === "graph" && (
                <div className="rounded-lg p-4" style={{ background: T.raised, border: `1px solid ${T.border}` }}>
                  <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Network size={14} color={T.accent} />
                      <span className="font-semibold uppercase tracking-wider" style={{ fontSize: FS.sm, color: T.muted }}>
                        Entity Association Graph
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span style={{ fontSize: FS.sm, color: T.muted }}>
                        Scope
                      </span>
                      <button
                        onClick={() => switchGraphDepth(3)}
                        className="rounded font-medium border cursor-pointer"
                        style={{
                          padding: "7px 10px",
                          fontSize: FS.sm,
                          background: graphDepth === 3 ? T.accent + "18" : T.surface,
                          color: graphDepth === 3 ? T.accent : T.dim,
                          borderColor: graphDepth === 3 ? T.accent + "44" : T.border,
                        }}
                      >
                        Focused network
                      </button>
                      <button
                        onClick={() => switchGraphDepth(4)}
                        className="rounded font-medium border cursor-pointer"
                        style={{
                          padding: "7px 10px",
                          fontSize: FS.sm,
                          background: graphDepth === 4 ? T.accent + "18" : T.surface,
                          color: graphDepth === 4 ? T.accent : T.dim,
                          borderColor: graphDepth === 4 ? T.accent + "44" : T.border,
                        }}
                      >
                        Extended network
                      </button>
                    </div>
                  </div>
                  {graphProvenanceSummary && (
                    <div
                      className="rounded-lg p-4"
                      style={{ marginBottom: 14, background: T.surface, border: `1px solid ${T.border}` }}
                    >
                      <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginBottom: 12 }}>
                        <div>
                          <div className="font-semibold uppercase tracking-wider" style={{ fontSize: 11, color: T.muted }}>
                            Provenance Snapshot
                          </div>
                          <div style={{ fontSize: FS.sm, color: T.text, marginTop: 4 }}>
                            Analyst-facing summary of corroboration, connector spread, and highest-signal edges.
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          {graphProvenanceSummary.topSources.map((item) => (
                            <span
                              key={item.source}
                              className="rounded-full"
                              style={{
                                padding: "5px 10px",
                                fontSize: 11,
                                fontWeight: 700,
                                color: T.accent,
                                background: `${T.accent}14`,
                              }}
                            >
                              {item.label} · {item.count}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                        {[
                          { label: "Relationships", value: graphProvenanceSummary.relationshipCount, tone: T.text },
                          { label: "Corroborated", value: graphProvenanceSummary.corroboratedCount, tone: T.amber },
                          { label: "Connectors", value: graphProvenanceSummary.sourceCount, tone: T.accent },
                          { label: "Control-path edges", value: graphProvenanceSummary.controlPathCount, tone: T.amber },
                        ].map((item) => (
                          <div
                            key={item.label}
                            className="rounded-lg p-3"
                            style={{ background: T.bg, border: `1px solid ${T.border}` }}
                          >
                            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                              {item.label}
                            </div>
                            <div style={{ fontSize: 22, color: item.tone, fontWeight: 800, marginTop: 4 }}>
                              {item.value}
                            </div>
                          </div>
                        ))}
                      </div>
                      {graphProvenanceSummary.highlights.length > 0 && (
                        <div style={{ marginTop: 14, display: "grid", gap: 10 }}>
                          {graphProvenanceSummary.highlights.map((item) => (
                            <div
                              key={item.id}
                              className="rounded-lg p-3"
                              style={{ background: T.bg, border: `1px solid ${T.border}` }}
                            >
                              <div className="flex items-center justify-between gap-3 flex-wrap">
                                <div style={{ fontSize: FS.sm, color: T.text, fontWeight: 700 }}>
                                  {item.sourceLabel} <span style={{ color: T.muted, fontWeight: 500 }}>→</span> {item.targetLabel}
                                </div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span
                                    className="rounded-full"
                                    style={{
                                      padding: "4px 8px",
                                      fontSize: 11,
                                      fontWeight: 700,
                                      color: T.amber,
                                      background: `${T.amber}14`,
                                    }}
                                  >
                                    {item.relLabel}
                                  </span>
                                  <span
                                    className="rounded-full"
                                    style={{
                                      padding: "4px 8px",
                                      fontSize: 11,
                                      fontWeight: 700,
                                      color: T.amber,
                                      background: `${T.amber}14`,
                                    }}
                                  >
                                    {item.corroborationCount} records
                                  </span>
                                </div>
                              </div>
                              {item.evidenceSummary && (
                                <div style={{ marginTop: 8, fontSize: FS.sm, color: T.text, lineHeight: 1.55 }}>
                                  {item.evidenceSummary}
                                </div>
                              )}
                              <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginTop: 8 }}>
                                <div style={{ fontSize: 12, color: T.muted }}>
                                  First seen {item.firstSeenAt} · Last seen {item.lastSeenAt}
                                </div>
                                <div className="flex items-center gap-2 flex-wrap">
                                  {item.sourceLabels.map((label) => (
                                    <span
                                      key={`${item.id}-${label}`}
                                      className="rounded-full"
                                      style={{
                                        padding: "4px 8px",
                                        fontSize: 11,
                                        fontWeight: 700,
                                        color: T.dim,
                                        background: T.raised,
                                      }}
                                    >
                                      {label}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {graphLoading && (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="animate-spin" size={20} color={T.muted} />
                      <span style={{ fontSize: FS.sm, color: T.muted, marginLeft: 8 }}>Loading graph data...</span>
                    </div>
                  )}
                  {graphData && (
                    <EntityGraph
                      entities={graphData.entities}
                      relationships={graphData.relationships}
                      rootEntityId={graphData.root_entity_id}
                      width={780}
                      height={520}
                    />
                  )}
                  {!graphLoading && !graphData && (
                    <div className="text-center py-6" style={{ fontSize: FS.sm, color: T.muted }}>
                      No graph data yet. Re-run the assessment to populate the knowledge graph.
                    </div>
                  )}
                </div>
              )}

              {evidenceTab !== "model" && evidenceTab !== "graph" && enrichment && !showStream && (
                <EnrichmentPanel caseId={c.id} report={enrichment} section={evidenceTab} />
              )}

              {evidenceTab !== "model" && !enrichment && !showStream && !loadingEnrichment && (
                <div
                  className="rounded-lg p-5 text-center"
                  style={{ background: T.raised, border: `1px solid ${T.border}`, fontSize: FS.sm, color: T.muted }}
                >
                  Run screening to load evidence for this case.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
