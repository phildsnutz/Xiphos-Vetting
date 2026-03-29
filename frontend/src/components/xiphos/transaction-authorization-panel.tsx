import { useState } from "react";
import { T, FS } from "@/lib/tokens";
import {
  Shield,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  User,
  ChevronDown,
  ChevronRight,
  Loader2,
  ExternalLink,
  Zap,
  Scale,
  Globe,
  FileCheck,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types matching the real API response from POST /api/export/authorize
/* ------------------------------------------------------------------ */

export interface PersonResult {
  name: string;
  role: string;
  screening_id: string;
  screening_status: "CLEAR" | "MATCH" | "PARTIAL_MATCH" | "ESCALATE" | "PENDING";
  composite_score: number;
  recommended_action: string;
  deemed_export: {
    required: boolean;
    country_group: string;
    license_type: string;
    rationale: string;
  } | null;
  network_risk_level: string;
  network_risk_signals: Array<{
    signal: string;
    severity: string;
    entity_name: string;
    entity_id: string;
    description: string;
  }>;
  matched_lists: Array<{ list: string; name: string; score: number }>;
  graph_ingested: boolean;
  error: string | null;
}

export interface LicenseExceptionMatch {
  exception_code: string;
  ear_reference: string;
  confidence: number;
  eligible: boolean;
  conditions: string[];
}

export interface LicenseExceptionResult {
  eligible: boolean;
  exception_code: string;
  exception_name: string;
  best_match: LicenseExceptionMatch | null;
  all_eligible: LicenseExceptionMatch[];
  all_ineligible: Array<{ code: string; name: string; reason: string }>;
  recommendation: string;
}

export interface PipelineLogEntry {
  stage: string;
  status: string;
  ts?: string;
  posture?: string;
  elevated?: boolean;
  persons_screened?: number;
  summary?: Record<string, number>;
  combined_posture?: string;
  duration_ms?: number;
}

export interface RulesGuidanceDetail {
  posture: string;
  posture_label: string;
  confidence: number;
  reason_summary: string;
  recommended_next_step: string;
  classification_analysis: {
    input: string;
    known: boolean;
    label: string;
    classification_family: string;
    rationale: string;
  };
  country_analysis: {
    destination_country: string;
    country_bucket: string;
    rationale: string;
  };
  factors: string[];
  official_references: Array<{
    title: string;
    url: string;
    note: string;
  }>;
  end_use_flags: string[];
  source: string;
  version: string;
}

export interface GraphIntelligence {
  graph_available: boolean;
  posture_elevated: boolean;
  elevation_reasons: string[];
  entity_risk: {
    found: boolean;
    available: boolean;
    entity_id: string;
    entity_name: string;
    entity_confidence: number;
    network_size: number;
    risk_signals: Array<{
      signal: string;
      severity: string;
      entity: string;
      description: string;
    }>;
    sanctions_exposure: { exposure_score: number; risk_level: string };
  };
  person_risk: unknown[];
}

export interface TransactionAuthorizationResult {
  id: string;
  case_id: string;
  combined_posture: string;
  combined_posture_label: string;
  confidence: number;
  duration_ms: number;
  created_at: string;
  requested_by: string;
  transaction_type: string;

  rules_posture: string;
  rules_confidence: number;
  rules_guidance: RulesGuidanceDetail;

  graph_posture: string;
  graph_elevated: boolean;
  graph_intelligence: GraphIntelligence;

  person_results: PersonResult[];
  person_summary?: {
    total: number;
    clear: number;
    match: number;
    partial_match: number;
    escalate: number;
    pending: number;
    errors: number;
    deemed_export_flags: number;
  };

  license_exception: LicenseExceptionResult | null;

  escalation_reasons: string[];
  blocking_factors: string[];
  all_factors: string[];
  recommended_next_step: string;

  pipeline_log: PipelineLogEntry[];
}

interface TransactionAuthorizationPanelProps {
  authorization: TransactionAuthorizationResult | null;
  loading?: boolean;
  onRerun?: () => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function postureColor(p: string): string {
  if (p === "likely_prohibited" || p === "escalate") return T.statusBlocked;
  if (p === "likely_license_required") return T.statusReview;
  if (p === "likely_exception_or_exemption") return T.statusQualified;
  if (p === "likely_nlr") return T.statusApproved;
  return T.textTertiary;
}

function screenColor(s: string): string {
  if (s === "CLEAR") return T.green;
  if (s === "MATCH" || s === "ESCALATE") return T.red;
  if (s === "PARTIAL_MATCH") return T.amber;
  return T.textTertiary;
}

function riskColor(r: string): string {
  if (r === "CRITICAL" || r === "HIGH") return T.red;
  if (r === "MEDIUM") return T.amber;
  return T.green;
}

function scoreBg(score: number): string {
  if (score >= 0.7) return T.red;
  if (score >= 0.4) return T.amber;
  return T.green;
}

const MONO = "'JetBrains Mono', 'Fira Code', monospace";

const sectionHeader: React.CSSProperties = {
  fontSize: FS.caption,
  fontWeight: 700,
  color: T.textSecondary,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 12,
};

const card: React.CSSProperties = {
  background: T.surface,
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  padding: 16,
};

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function derivePersonSummary(personResults: PersonResult[]) {
  return personResults.reduce(
    (summary, person) => {
      summary.total += 1;
      if (person.screening_status === "CLEAR") summary.clear += 1;
      else if (person.screening_status === "MATCH") summary.match += 1;
      else if (person.screening_status === "PARTIAL_MATCH") summary.partial_match += 1;
      else if (person.screening_status === "ESCALATE") summary.escalate += 1;
      else summary.pending += 1;
      if (person.error) summary.errors += 1;
      if (person.deemed_export?.required) summary.deemed_export_flags += 1;
      return summary;
    },
    {
      total: 0,
      clear: 0,
      match: 0,
      partial_match: 0,
      escalate: 0,
      pending: 0,
      errors: 0,
      deemed_export_flags: 0,
    },
  );
}

function Badge({ label, color, bg }: { label: string; color: string; bg?: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: FS.caption,
        fontWeight: 700,
        fontFamily: MONO,
        color,
        background: bg || `${color}18`,
        border: `1px solid ${color}30`,
      }}
    >
      {label}
    </span>
  );
}

/* Pipeline Timeline */
function PipelineTimeline({ log }: { log: PipelineLogEntry[] }) {
  const stageOrder = ["rules_engine", "graph_auth", "person_screening", "license_exception", "complete"];
  const stageLabels: Record<string, string> = {
    rules_engine: "Rules",
    graph_auth: "Graph",
    person_screening: "Persons",
    license_exception: "License",
    complete: "Done",
  };

  const stageStatus: Record<string, string> = {};
  for (const entry of log) {
    if (entry.status === "ok" || entry.status === "complete" || entry.stage === "complete") {
      stageStatus[entry.stage] = "ok";
    } else if (entry.status === "error") {
      stageStatus[entry.stage] = "error";
    } else if (entry.status === "started") {
      if (!stageStatus[entry.stage]) stageStatus[entry.stage] = "started";
    }
  }

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "8px 0", overflowX: "auto" }}>
      {stageOrder.map((stage, idx) => {
        const status = stageStatus[stage] || "pending";
        const isOk = status === "ok";
        const isErr = status === "error";
        const color = isOk ? T.green : isErr ? T.red : status === "started" ? T.accent : T.textTertiary;
        const Icon = isOk ? CheckCircle : isErr ? XCircle : status === "started" ? Clock : Clock;

        return (
          <div key={stage} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <Icon size={14} color={color} />
              <span style={{ fontSize: 9, fontWeight: 600, color, fontFamily: MONO }}>{stageLabels[stage]}</span>
            </div>
            {idx < stageOrder.length - 1 && (
              <div style={{ width: 20, height: 1, background: isOk ? `${T.green}50` : T.border, marginBottom: 14 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* Person Card */
function PersonCard({ p }: { p: PersonResult }) {
  const [expanded, setExpanded] = useState(false);
  const sc = screenColor(p.screening_status);
  const hasDE = p.deemed_export && p.deemed_export.required;
  const hasRisk = p.network_risk_level && p.network_risk_level !== "CLEAR";

  return (
    <div style={{ ...card, borderLeft: `3px solid ${sc}` }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <User size={14} color={T.textSecondary} />
            <span style={{ fontSize: FS.sm, fontWeight: 700, color: T.text }}>{p.name}</span>
            <Badge label={p.screening_status} color={sc} />
          </div>
          <div style={{ fontSize: FS.caption, color: T.textSecondary }}>{p.role}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: FS.caption, color: T.textTertiary, fontFamily: MONO }}>Score</div>
          <div style={{ fontSize: FS.md, fontWeight: 700, color: scoreBg(p.composite_score), fontFamily: MONO }}>
            {(p.composite_score * 100).toFixed(0)}
          </div>
        </div>
      </div>

      {/* Score bar */}
      <div style={{ marginTop: 8, height: 4, background: `${T.border}`, borderRadius: 2, overflow: "hidden" }}>
        <div
          style={{
            width: `${p.composite_score * 100}%`,
            height: "100%",
            background: scoreBg(p.composite_score),
            borderRadius: 2,
            transition: "width 0.5s ease",
          }}
        />
      </div>

      {/* Flags row */}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        {hasDE && (
          <Badge label={`DEEMED EXPORT: ${p.deemed_export!.license_type}`} color={T.amber} />
        )}
        {hasRisk && (
          <Badge label={`NET RISK: ${p.network_risk_level}`} color={riskColor(p.network_risk_level)} />
        )}
        {p.matched_lists.length > 0 && (
          <Badge label={`${p.matched_lists.length} LIST MATCH`} color={T.red} />
        )}
        {p.graph_ingested && (
          <Badge label="GRAPH" color={T.accent} />
        )}
      </div>

      {/* Expand toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          marginTop: 10,
          fontSize: FS.caption,
          color: T.textTertiary,
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
        }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Details
      </button>

      {expanded && (
        <div style={{ marginTop: 10, fontSize: FS.caption, color: T.textSecondary }}>
          {p.recommended_action && (
            <div style={{ marginBottom: 8, padding: 8, background: T.bg, borderRadius: 6, fontFamily: MONO, fontSize: 11 }}>
              {p.recommended_action}
            </div>
          )}
          {hasDE && p.deemed_export && (
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontWeight: 600, color: T.amber }}>Deemed Export: </span>
              {p.deemed_export.rationale}
              <span style={{ color: T.textTertiary }}> ({p.deemed_export.country_group})</span>
            </div>
          )}
          {p.network_risk_signals.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontWeight: 600, color: riskColor(p.network_risk_level) }}>Network Signals:</span>
              <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                {p.network_risk_signals.map((s, i) => (
                  <li key={i} style={{ marginBottom: 2 }}>
                    <span style={{ color: riskColor(s.severity) }}>[{s.severity}]</span> {s.description}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {p.matched_lists.length > 0 && (
            <div>
              <span style={{ fontWeight: 600, color: T.red }}>List Matches:</span>
              <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                {p.matched_lists.map((m, i) => (
                  <li key={i}>
                    {m.list}: {m.name} (score: {m.score})
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div style={{ marginTop: 6, color: T.textTertiary, fontFamily: MONO, fontSize: 10 }}>
            ID: {p.screening_id}
          </div>
        </div>
      )}
    </div>
  );
}

/* License Exception Section */
function LicenseExceptionSection({ le }: { le: LicenseExceptionResult }) {
  const [showIneligible, setShowIneligible] = useState(false);

  return (
    <div>
      <div style={sectionHeader}>
        <Scale size={12} style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} />
        License Exception Analysis
      </div>

      {/* Recommendation */}
      <div
        style={{
          ...card,
          borderLeft: le.eligible ? `3px solid ${T.statusQualified}` : `3px solid ${T.textTertiary}`,
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: FS.caption, fontWeight: 600, color: le.eligible ? T.statusQualified : T.textTertiary, marginBottom: 4 }}>
          {le.eligible ? "EXCEPTION AVAILABLE" : "NO EXCEPTION AVAILABLE"}
        </div>
        <div style={{ fontSize: FS.sm, color: T.text }}>{le.recommendation}</div>
      </div>

      {/* Best Match */}
      {le.best_match && (
        <div
          style={{
            ...card,
            border: `2px solid ${T.statusQualified}40`,
            marginBottom: 12,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <FileCheck size={16} color={T.statusQualified} />
              <span style={{ fontSize: FS.sm, fontWeight: 700, color: T.text, fontFamily: MONO }}>
                {le.best_match.exception_code}
              </span>
              <span style={{ fontSize: FS.caption, color: T.textSecondary }}>{le.best_match.ear_reference}</span>
            </div>
            <Badge
              label={`${(le.best_match.confidence * 100).toFixed(0)}% CONF`}
              color={T.statusQualified}
            />
          </div>
          {le.best_match.conditions.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: FS.caption, fontWeight: 600, color: T.textSecondary, marginBottom: 4 }}>CONDITIONS</div>
              {le.best_match.conditions.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 6,
                    fontSize: FS.caption,
                    color: T.textSecondary,
                    marginBottom: 3,
                    paddingLeft: 8,
                  }}
                >
                  <span style={{ color: T.statusQualified }}>{">"}</span>
                  {c}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Other eligible */}
      {le.all_eligible.length > 1 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
          {le.all_eligible
            .filter((e) => e.exception_code !== le.best_match?.exception_code)
            .map((e) => (
              <div key={e.exception_code} style={{ ...card, padding: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: FS.caption, fontWeight: 700, color: T.text, fontFamily: MONO }}>
                    {e.exception_code}
                  </span>
                  <span style={{ fontSize: 10, color: T.statusQualified, fontFamily: MONO }}>
                    {(e.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.textTertiary, marginTop: 2 }}>{e.ear_reference}</div>
              </div>
            ))}
        </div>
      )}

      {/* Ineligible (collapsible) */}
      {le.all_ineligible.length > 0 && (
        <div>
          <button
            onClick={() => setShowIneligible(!showIneligible)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: FS.caption,
              color: T.textTertiary,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              marginBottom: 8,
            }}
          >
            {showIneligible ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {le.all_ineligible.length} exceptions not applicable
          </button>
          {showIneligible && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {le.all_ineligible.map((ie) => (
                <div
                  key={ie.code}
                  style={{
                    display: "flex",
                    gap: 8,
                    fontSize: FS.caption,
                    color: T.textTertiary,
                    padding: "4px 8px",
                    background: T.bg,
                    borderRadius: 4,
                  }}
                >
                  <span style={{ fontFamily: MONO, fontWeight: 600, minWidth: 32 }}>{ie.code}</span>
                  <span>{ie.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* Rules Guidance Section */
function RulesGuidanceSection({ rg }: { rg: RulesGuidanceDetail }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          ...sectionHeader,
          cursor: "pointer",
          background: "none",
          border: "none",
          padding: 0,
        }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Globe size={12} style={{ verticalAlign: "middle" }} />
        Rules Engine Detail
      </button>

      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Classification */}
          <div style={card}>
            <div style={{ fontSize: FS.caption, fontWeight: 600, color: T.textSecondary, marginBottom: 6 }}>CLASSIFICATION</div>
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: FS.caption }}>
              <span style={{ color: T.textTertiary }}>Input:</span>
              <span style={{ color: T.text, fontFamily: MONO }}>{rg.classification_analysis.input}</span>
              <span style={{ color: T.textTertiary }}>Label:</span>
              <span style={{ color: T.text }}>{rg.classification_analysis.label}</span>
              <span style={{ color: T.textTertiary }}>Family:</span>
              <span style={{ color: T.text }}>{rg.classification_analysis.classification_family}</span>
            </div>
            <div style={{ fontSize: FS.caption, color: T.textSecondary, marginTop: 6 }}>
              {rg.classification_analysis.rationale}
            </div>
          </div>

          {/* Country */}
          <div style={card}>
            <div style={{ fontSize: FS.caption, fontWeight: 600, color: T.textSecondary, marginBottom: 6 }}>DESTINATION</div>
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: FS.caption }}>
              <span style={{ color: T.textTertiary }}>Country:</span>
              <span style={{ color: T.text, fontFamily: MONO }}>{rg.country_analysis.destination_country}</span>
              <span style={{ color: T.textTertiary }}>Bucket:</span>
              <span style={{ color: T.text }}>{rg.country_analysis.country_bucket}</span>
            </div>
            <div style={{ fontSize: FS.caption, color: T.textSecondary, marginTop: 6 }}>
              {rg.country_analysis.rationale}
            </div>
          </div>

          {/* References */}
          {rg.official_references.length > 0 && (
            <div style={card}>
              <div style={{ fontSize: FS.caption, fontWeight: 600, color: T.textSecondary, marginBottom: 6 }}>REFERENCES</div>
              {rg.official_references.map((ref, i) => (
                <div key={i} style={{ marginBottom: 6, fontSize: FS.caption }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <ExternalLink size={10} color={T.accent} />
                    <a
                      href={ref.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: T.accent, textDecoration: "none", fontWeight: 600 }}
                    >
                      {ref.title}
                    </a>
                  </div>
                  <div style={{ color: T.textTertiary, marginLeft: 14, marginTop: 1 }}>{ref.note}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export default function TransactionAuthorizationPanel({
  authorization: auth,
  loading,
  onRerun,
}: TransactionAuthorizationPanelProps) {
  if (loading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 48 }}>
        <Loader2 size={24} color={T.accent} className="animate-spin" />
        <div style={{ fontSize: FS.sm, color: T.textSecondary, marginTop: 12 }}>Running authorization pipeline...</div>
      </div>
    );
  }

  if (!auth) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <Shield size={32} color={T.textTertiary} style={{ margin: "0 auto 12px" }} />
        <div style={{ fontSize: FS.sm, color: T.textSecondary }}>
          No transaction authorization has been run for this case yet.
        </div>
        {onRerun && (
          <button
            onClick={onRerun}
            style={{
              marginTop: 16,
              padding: "8px 20px",
              background: T.accent,
              color: "#fff",
              border: "none",
              borderRadius: 6,
              fontSize: FS.sm,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Run Authorization
          </button>
        )}
      </div>
    );
  }

  const pc = postureColor(auth.combined_posture);
  const personSummary = auth.person_summary ?? derivePersonSummary(auth.person_results);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* -------- HEADER -------- */}
      <div
        style={{
          ...card,
          borderTop: `3px solid ${pc}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <Shield size={18} color={pc} />
            <Badge label={auth.combined_posture_label || auth.combined_posture.replace(/_/g, " ").toUpperCase()} color={pc} />
          </div>
          <div style={{ fontSize: FS.caption, color: T.textTertiary, fontFamily: MONO }}>{auth.id}</div>
          <div style={{ fontSize: FS.caption, color: T.textTertiary, marginTop: 2 }}>
            {auth.transaction_type} | {auth.requested_by} | {new Date(auth.created_at).toLocaleString()}
          </div>
        </div>
        <div style={{ display: "flex", gap: 16, textAlign: "center" }}>
          <div>
            <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase", letterSpacing: "0.05em" }}>Confidence</div>
            <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, fontFamily: MONO }}>
              {(auth.confidence * 100).toFixed(0)}%
            </div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase", letterSpacing: "0.05em" }}>Duration</div>
            <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, fontFamily: MONO }}>
              {(auth.duration_ms / 1000).toFixed(1)}s
            </div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase", letterSpacing: "0.05em" }}>Persons</div>
            <div style={{ fontSize: FS.md, fontWeight: 700, color: T.text, fontFamily: MONO }}>{personSummary.total}</div>
          </div>
        </div>
      </div>

      {/* -------- PIPELINE TIMELINE -------- */}
      <div style={{ ...card, padding: "8px 16px" }}>
        <PipelineTimeline log={auth.pipeline_log} />
      </div>

      {/* -------- RECOMMENDED NEXT STEP -------- */}
      <div
        style={{
          ...card,
          borderLeft: `3px solid ${pc}`,
          background: `${pc}08`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <Zap size={14} color={pc} />
          <span style={{ fontSize: FS.caption, fontWeight: 700, color: pc, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Recommended Action
          </span>
        </div>
        <div style={{ fontSize: FS.sm, color: T.text, lineHeight: 1.5 }}>{auth.recommended_next_step}</div>
      </div>

      {/* -------- ESCALATION / BLOCKING -------- */}
      {(auth.escalation_reasons.length > 0 || auth.blocking_factors.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {auth.blocking_factors.map((f, i) => (
            <div
              key={`block-${i}`}
              style={{
                ...card,
                padding: 10,
                borderLeft: `3px solid ${T.red}`,
                background: T.redBg,
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: FS.caption, color: T.text }}>
                <XCircle size={14} color={T.red} style={{ flexShrink: 0, marginTop: 1 }} />
                {f}
              </div>
            </div>
          ))}
          {auth.escalation_reasons.map((r, i) => (
            <div
              key={`esc-${i}`}
              style={{
                ...card,
                padding: 10,
                borderLeft: `3px solid ${T.amber}`,
                background: T.amberBg,
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: FS.caption, color: T.text }}>
                <AlertTriangle size={14} color={T.amber} style={{ flexShrink: 0, marginTop: 1 }} />
                {r}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* -------- PERSON SCREENING -------- */}
      {auth.person_results.length > 0 && (
        <div>
          <div style={sectionHeader}>
            <User size={12} style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} />
            Person Screening ({personSummary.total} persons |{" "}
            <span style={{ color: T.green }}>{personSummary.clear} clear</span>
            {personSummary.escalate > 0 && (
              <span style={{ color: T.red }}> | {personSummary.escalate} escalate</span>
            )}
            {personSummary.deemed_export_flags > 0 && (
              <span style={{ color: T.amber }}> | {personSummary.deemed_export_flags} deemed export</span>
            )}
            )
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {auth.person_results.map((p) => (
              <PersonCard key={p.screening_id || p.name} p={p} />
            ))}
          </div>
        </div>
      )}

      {/* -------- LICENSE EXCEPTION -------- */}
      {auth.license_exception && <LicenseExceptionSection le={auth.license_exception} />}

      {/* -------- GRAPH INTELLIGENCE -------- */}
      {auth.graph_intelligence?.graph_available && (
        <div>
          <div style={sectionHeader}>
            <Zap size={12} style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} />
            Graph Intelligence
          </div>
          <div style={card}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              <div>
                <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase" }}>Entity</div>
                <div style={{ fontSize: FS.caption, color: T.text, fontWeight: 600 }}>
                  {auth.graph_intelligence.entity_risk?.entity_name || "N/A"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase" }}>Network Size</div>
                <div style={{ fontSize: FS.caption, color: T.text, fontFamily: MONO }}>
                  {auth.graph_intelligence.entity_risk?.network_size || 0}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: T.textTertiary, textTransform: "uppercase" }}>Sanctions Exposure</div>
                <div
                  style={{
                    fontSize: FS.caption,
                    color: riskColor(auth.graph_intelligence.entity_risk?.sanctions_exposure?.risk_level || "CLEAR"),
                    fontWeight: 700,
                    fontFamily: MONO,
                  }}
                >
                  {auth.graph_intelligence.entity_risk?.sanctions_exposure?.risk_level || "CLEAR"}
                </div>
              </div>
            </div>
            {auth.graph_intelligence.entity_risk?.risk_signals?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                {auth.graph_intelligence.entity_risk.risk_signals.map((s, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      gap: 6,
                      fontSize: FS.caption,
                      color: T.textSecondary,
                      padding: "3px 0",
                    }}
                  >
                    <span style={{ color: riskColor(s.severity), fontFamily: MONO, fontWeight: 600 }}>[{s.severity}]</span>
                    {s.description}
                  </div>
                ))}
              </div>
            )}
            {auth.graph_elevated && (
              <div style={{ marginTop: 8, padding: "6px 10px", background: T.redBg, borderRadius: 4, fontSize: FS.caption, color: T.red }}>
                <AlertTriangle size={12} style={{ display: "inline", marginRight: 4, verticalAlign: "middle" }} />
                Graph intelligence elevated posture from {auth.rules_posture} to {auth.graph_posture}
              </div>
            )}
          </div>
        </div>
      )}

      {/* -------- RULES GUIDANCE -------- */}
      {auth.rules_guidance && <RulesGuidanceSection rg={auth.rules_guidance} />}

      {/* -------- RERUN BUTTON -------- */}
      {onRerun && (
        <div style={{ display: "flex", justifyContent: "center", paddingTop: 8 }}>
          <button
            onClick={onRerun}
            style={{
              padding: "8px 24px",
              background: "transparent",
              color: T.accent,
              border: `1px solid ${T.accent}40`,
              borderRadius: 6,
              fontSize: FS.caption,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: MONO,
            }}
          >
            Re-run Authorization
          </button>
        </div>
      )}
    </div>
  );
}
